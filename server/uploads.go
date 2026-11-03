package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const uploadChunkSize = 1 << 20

var uploadIDPattern = regexp.MustCompile(`^[a-f0-9]{32}$`)
var clientIDPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]{16,80}$`)

func (a *App) uploadDir(uploadID string) string {
	if !uploadIDPattern.MatchString(uploadID) {
		fail(400, "invalid upload id")
	}
	return filepath.Join(a.data, ".incoming", uploadID)
}
func (a *App) sessionFor(r *http.Request, u M) M {
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/uploads/"), "/")
	if len(parts) > 2 || !uploadIDPattern.MatchString(parts[0]) {
		notFound()
	}
	row := a.one("SELECT * FROM upload_sessions WHERE id=? AND owner_id=?", parts[0], u["id"])
	if row == nil {
		fail(404, "上传任务不存在或已过期")
	}
	return row
}
func (a *App) uploadStatus(row, u M) M {
	out := M{"id": row["id"], "clientId": row["client_id"], "name": row["filename"], "size": row["size"], "received": row["received"], "status": row["status"], "attempts": row["attempts"], "maxRetries": 3, "error": row["error"], "expires": row["expires"], "chunkSize": uploadChunkSize}
	out["sha256"], out["tag"] = row["sha256"], row["tag"]
	if row["status"] == "done" {
		if im := a.image(row["image_id"]); canViewImage(im, u) {
			out["item"] = a.itemJSON(im, u)
		} else {
			out["status"] = "deleted"
		}
	}
	return out
}
func (a *App) uploadSessions(w http.ResponseWriter, r *http.Request) {
	u := a.require(r, false)
	if r.Method == "PUT" && strings.HasSuffix(r.URL.Path, "/chunk") {
		a.receiveChunk(w, r, u)
		return
	}
	if r.Method != "GET" {
		a.writeMu.Lock()
		defer a.writeMu.Unlock()
	}
	if r.URL.Path == "/api/uploads" {
		if r.Method == "GET" {
			rows := a.rows("SELECT * FROM upload_sessions WHERE owner_id=? AND status NOT IN ('cancelled','expired') ORDER BY CASE WHEN status='done' THEN 1 ELSE 0 END,created_at DESC,id DESC LIMIT 50", u["id"])
			out := []M{}
			for _, row := range rows {
				out = append(out, a.uploadStatus(row, u))
			}
			respond(w, M{"items": out})
			return
		}
		if r.Method != "POST" {
			notFound()
		}
		v := body(r)
		client := str(v["clientId"])
		size := num(v["size"])
		filename := filepath.Base(str(v["filename"]))
		checksum := strings.ToLower(str(v["sha256"]))
		if b, e := hex.DecodeString(checksum); e != nil || len(b) != 32 {
			fail(400, "file SHA256 is required")
		}
		tag := cleanTag(v["tag"], u)
		if !clientIDPattern.MatchString(client) || size < 1 || size > 200<<20 || filename == "" || len(filename) > 240 {
			fail(400, "上传参数无效，单图最多 200MiB")
		}
		ext := strings.ToLower(filepath.Ext(filename))
		if !strings.Contains(",.jpg,.jpeg,.png,.webp,.avif,.gif,.bmp,", ","+ext+",") || ext == "" {
			fail(400, "unsupported image extension")
		}
		if old := a.one("SELECT * FROM upload_sessions WHERE owner_id=? AND client_id=?", u["id"], client); old != nil {
			if num(old["size"]) != size || old["filename"] != filename || old["tag"] != tag || old["sha256"] != checksum {
				fail(409, "上传标识已用于其他文件或标签")
			}
			respond(w, a.uploadStatus(old, u))
			return
		}
		a.checkUpload(u, size)
		if a.count("SELECT COUNT(*) FROM upload_sessions WHERE owner_id=? AND status IN ('receiving','queued','processing','failed')", u["id"]) >= 20 {
			fail(429, "未完成的上传任务过多，请先继续或取消旧任务")
		}
		if quota := num(u["quota_mb"]); u["role"] != "admin" && quota > 0 {
			reserved := a.count("SELECT COALESCE(SUM(size),0) FROM upload_sessions WHERE owner_id=? AND status IN ('receiving','queued','processing','failed')", u["id"])
			if num(a.usage(u["id"])["used"])+reserved+size > quota*1048576 {
				fail(400, "quota exceeded (including pending uploads)")
			}
		}
		uploadID := id(16)
		dir := a.uploadDir(uploadID)
		must(os.MkdirAll(dir, 0700))
		f, e := os.Create(filepath.Join(dir, "original.part"))
		must(e)
		must(f.Close())
		row := M{"id": uploadID, "owner_id": u["id"], "client_id": client, "filename": filename, "tag": tag, "size": size, "received": 0, "status": "receiving", "image_id": id(7), "key": "uploads/" + time.Now().Format("20060102") + "/" + uploadID + ext, "created_at": nowISO(), "updated_at": nowISO(), "expires": time.Now().Add(24 * time.Hour).Unix()}
		row["sha256"] = checksum
		err := caught(func() { a.insert("upload_sessions", row) })
		if err != nil {
			_ = os.RemoveAll(dir)
			panic(err)
		}
		respond(w, a.uploadStatus(a.one("SELECT * FROM upload_sessions WHERE id=?", uploadID), u))
		return
	}
	row := a.sessionFor(r, u)
	dir := a.uploadDir(str(row["id"]))
	if r.Method == "GET" && r.URL.Path == "/api/uploads/"+str(row["id"]) {
		respond(w, a.uploadStatus(row, u))
		return
	}
	if r.Method == "DELETE" && r.URL.Path == "/api/uploads/"+str(row["id"]) {
		if row["status"] == "done" {
			fail(409, "图片已完成入库，请在画廊删除")
		}
		a.exec("UPDATE upload_sessions SET status='cancelled',updated_at=?,expires=? WHERE id=?", nowISO(), time.Now().Add(24*time.Hour).Unix(), row["id"])
		must(os.RemoveAll(dir))
		respond(w, M{"ok": true})
		return
	}
	if r.Method != "POST" {
		notFound()
	}
	if strings.HasSuffix(r.URL.Path, "/retry") {
		if row["status"] != "failed" {
			fail(409, "只有处理失败的上传可以重试")
		}
		if num(row["received"]) != num(row["size"]) || !exists(filepath.Join(dir, "original.part")) {
			fail(409, "文件未接收完整，请重新选择文件续传")
		}
		a.exec("UPDATE upload_sessions SET status='queued',attempts=0,next_attempt=0,error='',updated_at=? WHERE id=?", nowISO(), row["id"])
	} else if strings.HasSuffix(r.URL.Path, "/complete") {
		if row["status"] == "receiving" {
			fi, e := os.Stat(filepath.Join(dir, "original.part"))
			if e != nil || fi.Size() != num(row["size"]) || num(row["received"]) != num(row["size"]) {
				fail(409, "文件尚未接收完整，不能提交处理")
			}
			a.exec("UPDATE upload_sessions SET status='queued',updated_at=? WHERE id=?", nowISO(), row["id"])
		} else if row["status"] == "cancelled" || row["status"] == "expired" {
			fail(410, "上传任务已取消或过期")
		}
	} else {
		notFound()
	}
	respond(w, a.uploadStatus(a.one("SELECT * FROM upload_sessions WHERE id=?", row["id"]), u))
}

// Only called at startup, before any request can be writing a chunk.
func (a *App) cleanUploadStaging() {
	root := filepath.Join(a.data, ".incoming")
	d, e := os.Open(root)
	if e != nil {
		return
	}
	defer d.Close()
	for {
		entries, e := d.ReadDir(100)
		for _, entry := range entries {
			if !entry.IsDir() || !uploadIDPattern.MatchString(entry.Name()) {
				continue
			}
			row := a.one("SELECT status FROM upload_sessions WHERE id=?", entry.Name())
			dir := a.uploadDir(entry.Name())
			if row == nil || row["status"] == "done" || row["status"] == "cancelled" {
				_ = os.RemoveAll(dir)
				continue
			}
			files, _ := os.ReadDir(dir)
			for _, file := range files {
				if strings.HasPrefix(file.Name(), "chunk-") {
					_ = os.Remove(filepath.Join(dir, file.Name()))
				}
			}
		}
		if e != nil {
			break
		}
	}
}
func (a *App) receiveChunk(w http.ResponseWriter, r *http.Request, u M) {
	row := a.sessionFor(r, u)
	if row["status"] != "receiving" {
		fail(409, "上传不在接收状态，请查询任务结果")
	}
	offset, e := strconv.ParseInt(r.Header.Get("Upload-Offset"), 10, 64)
	if e != nil || offset < 0 {
		fail(400, "invalid upload offset")
	}
	expected := strings.ToLower(r.Header.Get("X-Chunk-SHA256"))
	if b, e := hex.DecodeString(expected); e != nil || len(b) != 32 {
		fail(400, "chunk SHA256 is required")
	}
	dir := a.uploadDir(str(row["id"]))
	tmp, e := os.CreateTemp(dir, "chunk-")
	must(e)
	defer os.Remove(tmp.Name())
	defer tmp.Close()
	_ = http.NewResponseController(w).SetReadDeadline(time.Now().Add(60 * time.Second))
	defer http.NewResponseController(w).SetReadDeadline(time.Time{})
	hash := sha256.New()
	n, e := io.Copy(io.MultiWriter(tmp, hash), io.LimitReader(r.Body, uploadChunkSize+1))
	if e != nil {
		fail(400, "分块传输中断，已接收进度未改变")
	}
	if n < 1 || n > uploadChunkSize || offset > num(row["size"])-n {
		fail(400, "invalid chunk size")
	}
	if hex.EncodeToString(hash.Sum(nil)) != expected {
		fail(400, "分块校验失败，请重传当前块")
	}
	must(tmp.Close())
	a.writeMu.Lock()
	defer a.writeMu.Unlock()
	row = a.sessionFor(r, u)
	if row["status"] != "receiving" {
		fail(409, "上传状态已改变，请查询任务结果")
	}
	if num(row["expires"]) <= time.Now().Unix() {
		fail(410, "上传任务已过期")
	}
	dest, e := os.OpenFile(filepath.Join(dir, "original.part"), os.O_RDWR, 0600)
	must(e)
	defer dest.Close()
	fi, e := dest.Stat()
	must(e)
	received := num(row["received"])
	if fi.Size() < received {
		fail(409, "暂存文件不完整，请取消后重新上传")
	}
	// Crash after a write but before the SQLite commit: roll back unacknowledged bytes.
	if fi.Size() > received {
		must(dest.Truncate(received))
	}
	if offset < received {
		if offset+n > received {
			fail(409, "分块偏移不一致，请查询已接收进度")
		}
		hash = sha256.New()
		_, e = io.Copy(hash, io.NewSectionReader(dest, offset, n))
		must(e)
		if hex.EncodeToString(hash.Sum(nil)) != expected {
			fail(409, "重复分块内容不一致")
		}
	} else {
		if offset != received {
			fail(409, "分块偏移不一致，请查询已接收进度")
		}
		source, e := os.Open(tmp.Name())
		must(e)
		defer source.Close()
		_, e = dest.Seek(received, io.SeekStart)
		must(e)
		// A failed write is never acknowledged and is truncated on the next attempt.
		_, e = io.Copy(dest, source)
		must(e)
		must(dest.Sync())
		a.exec("UPDATE upload_sessions SET received=?,updated_at=?,expires=? WHERE id=?", received+n, nowISO(), time.Now().Add(24*time.Hour).Unix(), row["id"])
	}
	respond(w, a.uploadStatus(a.one("SELECT * FROM upload_sessions WHERE id=?", row["id"]), u))
}
func (a *App) runUpload(row M) {
	uploadID := row["id"]
	dir := a.uploadDir(str(uploadID))
	var fresh, u M
	a.writing(func() {
		fresh = a.one("SELECT * FROM upload_sessions WHERE id=? AND status='queued'", uploadID)
		if fresh == nil {
			return
		}
		a.exec("UPDATE upload_sessions SET status='processing',attempts=attempts+1,updated_at=? WHERE id=?", nowISO(), uploadID)
		u = a.one("SELECT * FROM users WHERE id=? AND enabled=1", row["owner_id"])
	})
	if fresh == nil {
		return
	}
	// The original remains in staging until BOTH the image row and its receipt commit.
	// This makes a lost HTTP response and a process restart safe to reconcile.
	var info M
	var lim M
	err := caught(func() {
		if u == nil {
			fail(403, "上传账号已停用或删除")
		}
		path := filepath.Join(dir, "original.part")
		fi, e := os.Stat(path)
		must(e)
		if fi.Size() != num(row["size"]) {
			fail(409, "暂存原图不完整")
		}
		input, e := os.Open(path)
		must(e)
		hash := sha256.New()
		_, he := io.Copy(hash, input)
		input.Close()
		must(he)
		if hex.EncodeToString(hash.Sum(nil)) != str(row["sha256"]) {
			fail(400, "整图 SHA256 校验失败，请取消后重新上传")
		}
		lim = a.limits(u)
		// A failed codec may have left a partial output. Never reuse it as a valid thumbnail.
		for _, name := range []string{"clean.original", "thumb.webp", "compressed.webp", "compressed.jpg", "compressed.png"} {
			if e := os.Remove(filepath.Join(dir, name)); e != nil && !os.IsNotExist(e) {
				must(e)
			}
		}
		info, e = a.processTo(path, lim, filepath.Join(dir, "thumb.webp"), filepath.Join(dir, "compressed."+outputExt(lim)), filepath.Join(dir, "clean.original"))
		must(e)
	})
	a.writeMu.Lock()
	defer a.writeMu.Unlock()
	fresh = a.one("SELECT * FROM upload_sessions WHERE id=?", uploadID)
	if fresh == nil || fresh["status"] != "processing" {
		_ = os.RemoveAll(dir)
		return
	}
	if a.workerContext.Err() != nil {
		a.exec("UPDATE upload_sessions SET status='queued',attempts=MAX(attempts-1,0) WHERE id=?", uploadID)
		return
	}
	if err == nil {
		err = caught(func() {
			u = a.one("SELECT * FROM users WHERE id=? AND enabled=1", row["owner_id"])
			if u == nil {
				fail(403, "上传账号已停用或删除")
			}
			cleanSize := num(info["original_size"])
			if cleanSize <= 0 {
				fail(400, "未生成已清除个人信息的原图")
			}
			a.checkUpload(u, cleanSize)
			key := str(row["key"])
			ckey := ""
			if info["c_size"] != nil {
				ckey = strings.TrimSuffix(key, filepath.Ext(key)) + "." + outputExt(lim)
			}
			// A previous interrupted commit can leave files at these random, task-owned paths.
			if a.image(row["image_id"]) != nil {
				panic("upload receipt conflict")
			}
			must(copyOriginal(filepath.Join(dir, "clean.original"), pathIn(filepath.Join(a.data, "uploads"), key)))
			must(promoteFile(filepath.Join(dir, "thumb.webp"), pathIn(filepath.Join(a.data, "thumbs"), key+".webp")))
			if ckey != "" {
				must(promoteFile(filepath.Join(dir, "compressed."+outputExt(lim)), pathIn(filepath.Join(a.data, "compressed"), ckey)))
			}
			tx, e := a.db.Begin()
			must(e)
			defer tx.Rollback()
			_, e = tx.Exec("INSERT INTO images(id,key,owner_id,tag,orig_name,mime,width,height,size,c_key,c_mime,c_width,c_height,c_size,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row["image_id"], key, u["id"], row["tag"], filepath.Base(key), info["mime"], info["width"], info["height"], cleanSize, nilIfEmpty(ckey), info["c_mime"], info["c_width"], info["c_height"], info["c_size"], nowISO())
			must(e)
			_, e = tx.Exec("UPDATE upload_sessions SET status='done',error='',updated_at=?,expires=? WHERE id=?", nowISO(), time.Now().Add(7*24*time.Hour).Unix(), uploadID)
			must(e)
			must(tx.Commit())
		})
	}
	if err == nil {
		_ = os.RemoveAll(dir)
		return
	}
	// Never remove a file that has already committed, even if cleanup fails.
	if a.image(row["image_id"]) == nil {
		for _, ext := range []string{"webp", "jpg", "png"} {
			_ = os.Remove(pathIn(filepath.Join(a.data, "compressed"), strings.TrimSuffix(str(row["key"]), filepath.Ext(str(row["key"])))+"."+ext))
		}
		_ = os.Remove(pathIn(filepath.Join(a.data, "thumbs"), str(row["key"])+".webp"))
		_ = os.Remove(pathIn(filepath.Join(a.data, "uploads"), str(row["key"])))
	}
	attempts := num(row["attempts"]) + 1
	status := "queued"
	if attempts >= workAttempts {
		status = "failed"
	}
	a.exec("UPDATE upload_sessions SET status=?,next_attempt=?,error=?,updated_at=?,expires=? WHERE id=?", status, time.Now().Unix()+(1<<min(attempts-1, 3)), truncate(err.Error(), 300), nowISO(), time.Now().Add(24*time.Hour).Unix(), uploadID)
}
func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}
func copyOriginal(src, dest string) error {
	if e := os.MkdirAll(filepath.Dir(dest), 0755); e != nil {
		return e
	}
	// Copy keeps the resumable source intact through a process crash during promotion.
	in, e := os.Open(src)
	if e != nil {
		return e
	}
	defer in.Close()
	out, e := os.Create(dest)
	if e != nil {
		return e
	}
	_, e = io.Copy(out, in)
	if e == nil {
		e = out.Sync()
	}
	ce := out.Close()
	if e != nil {
		return e
	}
	return ce
}
func (a *App) expireUploads() {
	for {
		rows := a.rows("SELECT id FROM upload_sessions WHERE expires<=? AND status NOT IN ('queued','processing') LIMIT 100", time.Now().Unix())
		if len(rows) == 0 {
			break
		}
		for _, row := range rows {
			dir := a.uploadDir(str(row["id"]))
			if e := os.RemoveAll(dir); e != nil {
				logUploadCleanup(e)
				return
			}
			a.exec("DELETE FROM upload_sessions WHERE id=?", row["id"])
		}
	}
	// Failed chunks and abandoned repair staging files are not importable images.
	entries, _ := os.ReadDir(a.data)
	for _, entry := range entries {
		if entry.IsDir() && strings.HasPrefix(entry.Name(), ".repair-") {
			if _, e := os.Stat(filepath.Join(a.data, entry.Name(), ".keep")); e == nil {
				continue
			}
			_ = os.RemoveAll(filepath.Join(a.data, entry.Name()))
		}
	}
}
func logUploadCleanup(err error) { fmt.Printf("upload staging cleanup: %v\n", err) }
