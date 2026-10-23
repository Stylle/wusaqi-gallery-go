package main

import (
	"encoding/json"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io/fs"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	_ "golang.org/x/image/bmp"
	_ "golang.org/x/image/webp"
)

func (a *App) imageInfo(p string) (M, error) {
	f, e := os.Open(p)
	if e != nil {
		return nil, e
	}
	cfg, format, e := image.DecodeConfig(f)
	f.Close()
	if e == nil {
		return M{"width": cfg.Width, "height": cfg.Height, "format": strings.ToUpper(format)}, nil
	}
	return a.work(M{"op": "info", "path": p})
}
func (a *App) walkPending(visit func(M) bool) int {
	scanned := 0
	root := filepath.Join(a.data, "uploads")
	e := filepath.WalkDir(root, func(p string, d fs.DirEntry, e error) error {
		if e != nil {
			return e
		}
		if d.IsDir() {
			return nil
		}
		scanned++
		if d.Type()&os.ModeSymlink != 0 {
			return nil
		}
		rel, e := filepath.Rel(root, p)
		if e != nil {
			return e
		}
		key := filepath.ToSlash(rel)
		if a.one("SELECT id FROM images WHERE key=?", key) != nil {
			return nil
		}
		fi, e := d.Info()
		if e != nil {
			return e
		}
		item := M{"key": key, "size": fi.Size(), "ok": true, "error": "", "width": nil, "height": nil}
		ext := strings.ToLower(filepath.Ext(key))
		if !strings.Contains(",.jpg,.jpeg,.png,.webp,.gif,.avif,.bmp,", ","+ext+",") || ext == "" {
			item["ok"], item["error"] = false, "不支持的扩展名"
		} else if info, e := a.imageInfo(p); e != nil {
			item["ok"], item["error"] = false, "无法解析为图片"
		} else {
			item["width"], item["height"], item["format"] = info["width"], info["height"], info["format"]
		}
		if !visit(item) {
			return fs.SkipAll
		}
		return nil
	})
	must(e)
	return scanned
}
func (a *App) failedQueue() []M {
	out := []M{}
	_ = json.Unmarshal([]byte(a.settings()["local_import_failed"]), &out)
	return out
}
func (a *App) storeQueue(q []M) {
	b, e := json.Marshal(q)
	must(e)
	a.updateSettings(map[string]string{"local_import_failed": string(b)})
}
func (a *App) setJob(v M) {
	a.jobsMu.Lock()
	defer a.jobsMu.Unlock()
	for k, x := range v {
		a.job[k] = x
	}
}
func (a *App) cancelled() bool {
	a.jobsMu.Lock()
	defer a.jobsMu.Unlock()
	return truth(a.job["cancel"])
}
func (a *App) tryImport(item, u M) (err error) {
	defer func() {
		if p := recover(); p != nil {
			if e, ok := p.(apiError); ok {
				err = fmt.Errorf("%s", e.message)
			} else {
				err = fmt.Errorf("%v", p)
			}
		}
	}()
	key := str(item["key"])
	if a.one("SELECT id FROM images WHERE key=?", key) != nil {
		return nil
	}
	a.registerFile(pathIn(filepath.Join(a.data, "uploads"), key), key, filepath.Base(key), u, "", true)
	return nil
}
func (a *App) importWorker(uid any) {
	defer func() {
		if p := recover(); p != nil {
			log.Printf("local import failed: %v", p)
			a.setJob(M{"errors": []string{fmt.Sprint(p)}})
		}
		a.setJob(M{"running": false, "current": "", "finishedAt": nowISO()})
	}()
	// Hold a read lease for the whole task so restore cannot swap its database/files.
	a.dataMu.RLock()
	defer a.dataMu.RUnlock()
	u := a.one("SELECT * FROM users WHERE id=?", uid)
	if u == nil {
		panic("import owner no longer exists")
	}
	total := 0
	a.walkPending(func(p M) bool {
		if truth(p["ok"]) {
			total++
		}
		return !a.cancelled()
	})
	a.setJob(M{"total": total})
	old := a.failedQueue()
	attempts := map[string]int64{}
	for _, f := range old {
		attempts[str(f["key"])] = num(f["attempts"])
	}
	// Persist failures incrementally. The next run rescans unindexed files, so an
	// interrupted process or cancellation cannot lose pending work.
	failures := []M{}
	done, imported, retried := 0, 0, 0
	a.walkPending(func(p M) bool {
		if a.cancelled() {
			return false
		}
		if !truth(p["ok"]) {
			return true
		}
		key := str(p["key"])
		a.setJob(M{"current": key})
		var err error
		tries := int64(0)
		for n := 0; n < 3; n++ {
			if a.cancelled() {
				return false
			}
			tries++
			if n > 0 {
				retried++
			}
			a.writeMu.Lock()
			func() { defer a.writeMu.Unlock(); err = a.tryImport(p, u) }()
			if err == nil {
				break
			}
		}
		done++
		if err == nil {
			imported++
		} else {
			failures = append(failures, M{"key": key, "error": truncate(err.Error(), 200), "attempts": attempts[key] + tries})
		}
		a.writeMu.Lock()
		func() { defer a.writeMu.Unlock(); a.storeQueue(failures) }()
		a.setJob(M{"done": done, "imported": imported, "failed": len(failures), "retried": retried, "queueSize": len(failures)})
		return true
	})
	if !a.cancelled() {
		a.writeMu.Lock()
		defer a.writeMu.Unlock()
		a.storeQueue(failures)
	}
}
func (a *App) localRoute(w http.ResponseWriter, r *http.Request, u M) {
	switch {
	case r.URL.Path == "/api/admin/local/scan" && r.Method == "GET":
		if r.URL.Query().Get("dry_run") == "false" {
			fail(400, "请使用 POST /api/admin/local/import")
		}
		limit := int(clamp(queryNum(r, "limit", 50), 1, 100))
		pending, invalid := []M{}, []M{}
		pc, ic := 0, 0
		scanned := a.walkPending(func(p M) bool {
			if truth(p["ok"]) {
				pc++
				if len(pending) < limit {
					pending = append(pending, p)
				}
			} else {
				ic++
				if len(invalid) < limit {
					invalid = append(invalid, p)
				}
			}
			return true
		})
		respond(w, M{"dryRun": true, "scanned": scanned, "indexed": a.count("SELECT COUNT(*) FROM images"), "pendingCount": pc, "invalidCount": ic, "pending": pending, "invalid": invalid})
	case r.URL.Path == "/api/admin/local/import" && r.Method == "POST":
		a.jobsMu.Lock()
		if truth(a.job["running"]) {
			a.jobsMu.Unlock()
			fail(409, "导入任务进行中")
		}
		a.job = M{"running": true, "cancel": false, "total": 0, "done": 0, "imported": 0, "failed": 0, "retried": 0, "queueSize": 0, "current": "", "startedAt": nowISO(), "finishedAt": "", "errors": []any{}}
		a.jobsMu.Unlock()
		go a.importWorker(u["id"])
		respond(w, M{"started": true})
	case r.URL.Path == "/api/admin/local/status" && r.Method == "GET":
		q := a.failedQueue()
		a.jobsMu.Lock()
		state := M{}
		for k, v := range a.job {
			state[k] = v
		}
		a.jobsMu.Unlock()
		state["queueSize"] = len(q)
		if len(q) > 50 {
			q = q[:50]
		}
		state["queue"] = q
		respond(w, state)
	case r.URL.Path == "/api/admin/local/import/cancel" && r.Method == "POST":
		a.setJob(M{"cancel": true})
		respond(w, M{"ok": true})
	case r.URL.Path == "/api/admin/local/compress" && r.Method == "POST":
		a.compressLocal(w, r)
	default:
		notFound()
	}
}
func (a *App) compressLocal(w http.ResponseWriter, r *http.Request) {
	lim := a.effective()
	limit := int(clamp(queryNum(r, "limit", 5), 1, 50))
	dry := r.URL.Query().Get("dry_run") != "false"
	todo := 0
	batch := []M{}
	after := ""
	// Bounded SQL batches instead of materializing the whole library.
	for {
		rows := a.rows("SELECT * FROM images WHERE id>? ORDER BY id LIMIT 100", after)
		if len(rows) == 0 {
			break
		}
		for _, im := range rows {
			after = str(im["id"])
			ck := str(im["c_key"])
			needC := ck == "" || !exists(pathIn(filepath.Join(a.data, "compressed"), ck))
			if str(im["mime"]) == "image/gif" {
				needC = false
			}
			needT := !exists(pathIn(filepath.Join(a.data, "thumbs"), str(im["key"])+".webp"))
			if needC || needT {
				todo++
				if len(batch) < limit {
					batch = append(batch, M{"row": im, "compressed": needC, "thumb": needT, "key": im["key"], "filename": filepath.Base(str(im["key"])), "size": im["size"]})
				}
			}
		}
	}
	done := 0
	failed := []M{}
	if !dry {
		for _, item := range batch {
			im := item["row"].(M)
			key := str(im["key"])
			info, e := a.process(pathIn(filepath.Join(a.data, "uploads"), key), key, lim, truth(item["thumb"]), truth(item["compressed"]))
			if e != nil {
				failed = append(failed, M{"key": key, "error": e.Error()})
				continue
			}
			fields := M{}
			for _, k := range []string{"c_key", "c_mime", "c_width", "c_height", "c_size"} {
				if v, ok := info[k]; ok {
					fields[k] = v
				}
			}
			a.update("images", "id", im["id"], fields)
			if old := str(im["c_key"]); old != "" && fields["c_key"] != nil && old != str(fields["c_key"]) {
				_ = os.Remove(pathIn(filepath.Join(a.data, "compressed"), old))
			}
			done++
		}
	}
	for _, b := range batch {
		delete(b, "row")
	}
	respond(w, M{"dryRun": dry, "todoCount": todo, "done": done, "remaining": todo - done, "settings": lim, "items": batch, "failed": failed})
}
func exists(p string) bool { fi, e := os.Stat(p); return e == nil && !fi.IsDir() }
