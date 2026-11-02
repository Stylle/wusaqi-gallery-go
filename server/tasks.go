package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Four attempts = the initial attempt plus at most three automatic retries.
const workAttempts = 4

func caught(fn func()) (err error) {
	defer func() {
		if p := recover(); p != nil {
			if e, ok := p.(apiError); ok {
				err = fmt.Errorf("%s", e.message)
			} else {
				err = fmt.Errorf("%v", p)
			}
		}
	}()
	fn()
	return
}
func (a *App) writing(fn func()) { a.writeMu.Lock(); defer a.writeMu.Unlock(); fn() }
func (a *App) recoverWork() {
	a.exec("UPDATE repair_items SET status='pending',attempts=MAX(attempts-1,0) WHERE status='processing'")
	a.exec("UPDATE upload_sessions SET status='queued',attempts=MAX(attempts-1,0) WHERE status='processing'")
	if job := a.one("SELECT batch_size FROM repair_job WHERE status='building'"); job != nil {
		a.buildRepair(num(job["batch_size"]))
	}
	// Incomplete payloads are deliberately outside the import/backup directories.
	a.expireUploads()
	a.cleanUploadStaging()
}
func (a *App) repairActive() bool {
	return a.count("SELECT COUNT(*) FROM repair_job WHERE status IN ('building','running')") > 0
}
func (a *App) tasksBusy() bool {
	return a.repairActive() || a.count("SELECT COUNT(*) FROM repair_items WHERE status='processing'") > 0 || a.count("SELECT COUNT(*) FROM upload_sessions WHERE status IN ('queued','processing')") > 0
}
func (a *App) workLoop() {
	defer a.workerWG.Done()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	cleaned := time.Now()
	for {
		select {
		case <-a.stop:
			return
		case <-ticker.C:
		}
		func() {
			a.dataMu.RLock()
			defer a.dataMu.RUnlock()
			defer func() {
				if p := recover(); p != nil {
					log.Printf("work queue: %v", p)
					_ = caught(func() {
						a.writing(func() {
							a.exec("UPDATE repair_items SET status='pending',attempts=MAX(attempts-1,0) WHERE status='processing'")
							a.exec("UPDATE upload_sessions SET status='queued',attempts=MAX(attempts-1,0) WHERE status='processing'")
						})
					})
				}
			}()
			if time.Since(cleaned) > time.Hour {
				a.writeMu.Lock()
				func() { defer a.writeMu.Unlock(); a.expireUploads() }()
				cleaned = time.Now()
			}
			if row := a.one("SELECT * FROM upload_sessions WHERE status='queued' AND next_attempt<=? ORDER BY created_at,id LIMIT 1", time.Now().Unix()); row != nil {
				a.runUpload(row)
				return
			}
			job := a.one("SELECT * FROM repair_job WHERE id=1 AND status='running'")
			if job == nil {
				return
			}
			for n := int64(0); n < num(job["batch_size"]); n++ {
				if a.workerContext.Err() != nil || !a.repairActive() {
					return
				}
				row := a.one("SELECT * FROM repair_items WHERE status='pending' AND next_attempt<=? ORDER BY image_id LIMIT 1", time.Now().Unix())
				if row == nil {
					break
				}
				a.runRepair(row)
				if a.count("SELECT COUNT(*) FROM upload_sessions WHERE status='queued' AND next_attempt<=?", time.Now().Unix()) > 0 {
					break
				}
			}
			a.writeMu.Lock()
			defer a.writeMu.Unlock()
			if a.count("SELECT COUNT(*) FROM repair_items WHERE status IN ('pending','processing')") == 0 {
				a.exec("UPDATE repair_job SET status='completed',updated_at=? WHERE id=1 AND status='running'", nowISO())
			}
		}()
	}
}
func (a *App) repairStatus() M {
	job := a.one("SELECT * FROM repair_job WHERE id=1")
	if job == nil {
		job = M{"status": "idle", "batch_size": 5}
	}
	counts := M{"total": a.count("SELECT COUNT(*) FROM repair_items"), "pending": 0, "processing": 0, "done": 0, "failed": 0, "skipped": 0, "retried": 0}
	for _, r := range a.rows("SELECT status,COUNT(*) AS n FROM repair_items GROUP BY status") {
		counts[str(r["status"])] = r["n"]
	}
	counts["retried"] = a.count("SELECT COALESCE(SUM(MAX(attempts-1,0)),0) FROM repair_items")
	return M{"job": job, "counts": counts, "failures": a.rows("SELECT image_id,error,attempts FROM repair_items WHERE status='failed' ORDER BY image_id LIMIT 50"), "current": a.one("SELECT image_id,attempts FROM repair_items WHERE status='processing' LIMIT 1"), "maxRetries": 3}
}
func (a *App) repairRoute(w http.ResponseWriter, r *http.Request) {
	if r.Method == "GET" && r.URL.Path == "/api/admin/local/repair" {
		respond(w, a.repairStatus())
		return
	}
	if r.Method != "POST" {
		notFound()
	}
	switch r.URL.Path {
	case "/api/admin/local/repair":
		if a.repairActive() || a.count("SELECT COUNT(*) FROM repair_items WHERE status='processing'") > 0 {
			fail(409, "补齐队列已在运行")
		}
		a.jobsMu.Lock()
		busy := truth(a.job["running"])
		a.jobsMu.Unlock()
		if busy {
			fail(409, "请先结束本地导入任务")
		}
		v := body(r)
		size := num(v["batchSize"])
		if size < 1 || size > 50 {
			fail(400, "每批张数应为 1–50")
		}
		a.buildRepair(size)
	case "/api/admin/local/repair/pause":
		a.exec("UPDATE repair_job SET status='paused',updated_at=? WHERE id=1 AND status='running'", nowISO())
	case "/api/admin/local/repair/resume", "/api/admin/local/repair/retry-failed":
		if r.ContentLength != 0 {
			size := num(body(r)["batchSize"])
			if size < 1 || size > 50 {
				fail(400, "每批张数应为 1–50")
			}
			a.exec("UPDATE repair_job SET batch_size=? WHERE id=1", size)
		}
		a.jobsMu.Lock()
		busy := truth(a.job["running"])
		a.jobsMu.Unlock()
		if busy {
			fail(409, "请先结束本地导入任务")
		}
		if a.one("SELECT id FROM repair_job WHERE id=1") == nil {
			fail(404, "没有可继续的补齐队列")
		}
		if strings.HasSuffix(r.URL.Path, "retry-failed") {
			a.exec("UPDATE repair_items SET status='pending',attempts=0,next_attempt=0,error='' WHERE status='failed'")
		}
		a.exec("UPDATE repair_job SET status='running',updated_at=? WHERE id=1", nowISO())
	default:
		notFound()
	}
	respond(w, a.repairStatus())
}
func (a *App) buildRepair(size int64) {
	// A crash while scanning leaves 'building'; startup restarts the scan instead
	// of silently treating a partially populated queue as the whole library.
	a.exec("INSERT INTO repair_job(id,status,batch_size,started_at,updated_at) VALUES(1,'building',?,?,?) ON CONFLICT(id) DO UPDATE SET status='building',batch_size=excluded.batch_size,started_at=excluded.started_at,updated_at=excluded.updated_at", size, nowISO(), nowISO())
	a.exec("DELETE FROM repair_items")
	after := ""
	for {
		rows := a.rows("SELECT * FROM images WHERE id>? ORDER BY id LIMIT 100", after)
		if len(rows) == 0 {
			break
		}
		for _, im := range rows {
			after = str(im["id"])
			if c, t := a.missingVariants(im); c || t {
				a.exec("INSERT INTO repair_items(image_id,status) VALUES(?,'pending')", im["id"])
			}
		}
	}
	a.exec("UPDATE repair_job SET status='running',updated_at=? WHERE id=1", nowISO())
}
func (a *App) missingVariants(im M) (bool, bool) {
	if im == nil || !exists(pathIn(filepath.Join(a.data, "uploads"), str(im["key"]))) {
		return false, false
	}
	ck := str(im["c_key"])
	return str(im["mime"]) != "image/gif" && (ck == "" || !exists(pathIn(filepath.Join(a.data, "compressed"), ck))), !exists(pathIn(filepath.Join(a.data, "thumbs"), str(im["key"])+".webp"))
}
func (a *App) runRepair(task M) {
	imageID := task["image_id"]
	var im M
	var c, t, started bool
	a.writing(func() {
		if !a.repairActive() {
			return
		}
		a.exec("UPDATE repair_items SET status='processing',attempts=attempts+1 WHERE image_id=?", imageID)
		im = a.image(imageID)
		c, t = a.missingVariants(im)
		started = true
	})
	if !started {
		return
	}
	if !c && !t {
		a.writeMu.Lock()
		defer a.writeMu.Unlock()
		a.exec("UPDATE repair_items SET status='skipped',error='' WHERE image_id=?", imageID)
		return
	}
	stage, e := os.MkdirTemp(a.data, ".repair-")
	var info M
	err := e
	if err == nil {
		defer os.RemoveAll(stage)
		lim := a.effective()
		thumb, comp := "", ""
		if t {
			thumb = filepath.Join(stage, "thumb.webp")
		}
		if c {
			comp = filepath.Join(stage, "compressed."+outputExt(lim))
		}
		err = caught(func() {
			var pe error
			info, pe = a.processTo(pathIn(filepath.Join(a.data, "uploads"), str(im["key"])), lim, thumb, comp)
			must(pe)
		})
		if err == nil {
			a.writeMu.Lock()
			err = caught(func() {
				fresh := a.image(imageID)
				if fresh == nil || fresh["key"] != im["key"] {
					a.exec("UPDATE repair_items SET status='skipped',error='' WHERE image_id=?", imageID)
					return
				}
				if t {
					must(promoteFile(thumb, pathIn(filepath.Join(a.data, "thumbs"), str(im["key"])+".webp")))
				}
				if c && info["c_size"] != nil {
					key := strings.TrimSuffix(str(im["key"]), filepath.Ext(str(im["key"]))) + "." + outputExt(lim)
					must(promoteFile(comp, pathIn(filepath.Join(a.data, "compressed"), key)))
					fields := M{"c_key": key}
					for _, k := range []string{"c_mime", "c_width", "c_height", "c_size"} {
						fields[k] = info[k]
					}
					a.update("images", "id", imageID, fields)
					if old := str(im["c_key"]); old != "" && old != key {
						_ = os.Remove(pathIn(filepath.Join(a.data, "compressed"), old))
					}
				}
				a.exec("UPDATE repair_items SET status='done',error='' WHERE image_id=?", imageID)
			})
			a.writeMu.Unlock()
		}
	}
	if err != nil {
		a.writeMu.Lock()
		defer a.writeMu.Unlock()
		if a.workerContext.Err() != nil {
			a.exec("UPDATE repair_items SET status='pending',attempts=MAX(attempts-1,0) WHERE image_id=?", imageID)
			return
		}
		attempts := num(task["attempts"]) + 1
		status := "pending"
		if attempts >= workAttempts {
			status = "failed"
		}
		a.exec("UPDATE repair_items SET status=?,next_attempt=?,error=? WHERE image_id=?", status, time.Now().Unix()+(1<<min(attempts-1, 3)), truncate(err.Error(), 300), imageID)
	}
}
func outputExt(lim M) string {
	return map[string]string{"webp": "webp", "jpeg": "jpg", "png": "png"}[str(lim["format"])]
}
func promoteFile(src, dest string) error {
	if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
		return err
	}
	// Worker output is complete before it replaces a generated file. On Windows,
	// os.Rename cannot replace an existing file; missing-asset tasks normally have none.
	if exists(dest) {
		if err := os.Remove(dest); err != nil {
			return err
		}
	}
	return os.Rename(src, dest)
}
