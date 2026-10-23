package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

func (a *App) image(i any) M {
	return a.one("SELECT i.*,u.username AS owner_name FROM images i LEFT JOIN users u ON u.id=i.owner_id WHERE i.id=?", i)
}
func itemJSON(r, u M) M {
	own := u != nil && r["owner_id"] == u["id"]
	edit := u != nil && (u["role"] == "admin" || own)
	var c any
	if str(r["c_key"]) != "" {
		c = "/compressed/" + str(r["c_key"])
	}
	return M{"id": r["id"], "key": r["key"], "url": "/files/" + str(r["key"]), "thumb": "/thumbs/" + str(r["key"]) + ".webp", "compressed": c, "width": r["width"], "height": r["height"], "mimeType": r["mime"], "size": r["size"], "compressedSize": r["c_size"], "createdAt": r["created_at"], "tag": str(r["tag"]), "filename": filepath.Base(str(r["key"])), "origName": str(r["orig_name"]), "ownerId": str(r["owner_id"]), "owner": str(r["owner_name"]), "mine": own, "canEdit": edit}
}
func (a *App) images(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	page, limit := max(1, queryNum(r, "page", 1)), clamp(queryNum(r, "limit", 36), 1, 100)
	u := a.user(r)
	where := []string{"1=1"}
	args := []any{}
	if tag := strings.TrimSpace(q.Get("tag")); tag != "" {
		where = append(where, "i.tag=?")
		args = append(args, tag)
	}
	if truth(q.Get("mine")) {
		if u == nil {
			fail(401, "login required for mine filter")
		}
		where = append(where, "i.owner_id=?")
		args = append(args, u["id"])
	}
	total := a.count("SELECT COUNT(*) FROM images i WHERE "+strings.Join(where, " AND "), args...)
	if cursor := q.Get("cursor"); cursor != "" {
		b, e := base64.RawURLEncoding.DecodeString(cursor)
		var parts []string
		if e != nil || json.Unmarshal(b, &parts) != nil || len(parts) != 2 || len(b) > 512 {
			fail(400, "invalid cursor")
		}
		where = append(where, "(i.created_at<? OR (i.created_at=? AND i.id<?))")
		args = append(args, parts[0], parts[0], parts[1])
		page = 1
	}
	args = append(args, limit+1)
	sql := "SELECT i.*,u.username AS owner_name FROM images i LEFT JOIN users u ON u.id=i.owner_id WHERE " + strings.Join(where, " AND ") + " ORDER BY i.created_at DESC,i.id DESC LIMIT ?"
	if q.Get("cursor") == "" {
		sql += " OFFSET ?"
		args = append(args, (page-1)*limit)
	}
	rows := a.rows(sql, args...)
	more := len(rows) > int(limit)
	if more {
		rows = rows[:limit]
	}
	items := []M{}
	next := ""
	for _, im := range rows {
		items = append(items, itemJSON(im, u))
	}
	if more && len(rows) > 0 {
		last := rows[len(rows)-1]
		b, _ := json.Marshal([]string{str(last["created_at"]), str(last["id"])})
		next = base64.RawURLEncoding.EncodeToString(b)
	}
	respond(w, M{"items": items, "page": page, "limit": limit, "total": total, "hasMore": more, "nextCursor": next})
}
func (a *App) random(w http.ResponseWriter, r *http.Request) {
	if a.settings()["random_public"] != "1" {
		a.require(r, false)
	}
	row := a.one("SELECT * FROM images ORDER BY RANDOM() LIMIT 1")
	if row == nil {
		fail(404, "no images")
	}
	p := "/files/" + str(row["key"])
	if r.URL.Query().Get("variant") != "original" && str(row["c_key"]) != "" {
		p = "/compressed/" + str(row["c_key"])
	}
	w.Header().Set("Cache-Control", "no-store")
	if r.URL.Path == "/api/random/image" || truth(r.URL.Query().Get("redirect")) {
		http.Redirect(w, r, p, 302)
	} else {
		respond(w, itemJSON(row, nil))
	}
}

func (a *App) work(job M) (M, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	b, e := json.Marshal(job)
	if e != nil {
		return nil, e
	}
	cmd := exec.CommandContext(ctx, a.python, a.worker)
	cmd.Stdin = bytes.NewReader(b)
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	var out, stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr
	e = cmd.Run()
	var result struct {
		OK     bool   `json:"ok"`
		Result M      `json:"result"`
		Error  string `json:"error"`
	}
	if err := json.Unmarshal(out.Bytes(), &result); err != nil {
		return nil, fmt.Errorf("image worker unavailable: %v %s", e, stderr.String())
	}
	if !result.OK {
		return nil, fmt.Errorf("%s", result.Error)
	}
	return result.Result, nil
}
func (a *App) process(path, key string, lim M, thumb, compressed bool) (M, error) {
	a.poolMu.Lock()
	for a.active >= num(lim["concurrency"]) {
		a.poolCond.Wait()
	}
	a.active++
	a.poolMu.Unlock()
	defer func() { a.poolMu.Lock(); a.active--; a.poolCond.Broadcast(); a.poolMu.Unlock() }()
	job := M{"op": "process", "path": path, "limits": lim}
	if thumb {
		job["thumb"] = pathIn(filepath.Join(a.data, "thumbs"), key+".webp")
	}
	ext := map[string]string{"webp": "webp", "jpeg": "jpg", "png": "png"}[str(lim["format"])]
	ckey := strings.TrimSuffix(key, filepath.Ext(key)) + "." + ext
	if compressed {
		job["compressed"] = pathIn(filepath.Join(a.data, "compressed"), ckey)
	}
	info, err := a.work(job)
	if err != nil {
		return nil, err
	}
	if _, ok := info["c_size"]; ok {
		info["c_key"] = ckey
	}
	return info, nil
}
func (a *App) limits(u M) M {
	lim := a.effective()
	if f := str(u["comp_format"]); f != "" {
		lim["format"] = f
	}
	if u["comp_quality"] != nil {
		lim["quality"] = clamp(num(u["comp_quality"]), 1, 100)
	}
	if u["comp_max_width"] != nil {
		lim["maxWidth"] = max(0, num(u["comp_max_width"]))
	}
	return lim
}
func (a *App) checkUpload(u M, size int64) {
	if u["role"] == "admin" {
		return
	}
	s := a.settings()
	cap := num(u["max_upload_mb"])
	if cap == 0 {
		cap = num(s["upload_max_mb"])
	}
	if cap > 0 && size > cap*1048576 {
		fail(400, fmt.Sprintf("超过单图上限 %dMB", cap))
	}
	c := a.uploadCounts(u["id"])
	for k, col := range map[string]string{"day": "daily_limit", "week": "weekly_limit", "month": "monthly_limit"} {
		if n := num(u[col]); n > 0 && num(c[k]) >= n {
			fail(400, "上传张数已达上限")
		}
	}
	if n := num(u["quota_mb"]); n > 0 && num(a.usage(u["id"])["used"])+size > n*1048576 {
		fail(400, "quota exceeded")
	}
}
func (a *App) registerFile(path, key, filename string, u M, tag string, local bool) M {
	fi, e := os.Stat(path)
	must(e)
	if !local {
		a.checkUpload(u, fi.Size())
	}
	info, e := a.process(path, key, a.limits(u), true, true)
	if e != nil {
		fail(400, e.Error())
	}
	created := nowISO()
	if local {
		created = fi.ModTime().UTC().Format("2006-01-02T15:04:05+00:00")
	}
	row := M{"id": id(7), "key": key, "owner_id": u["id"], "tag": truncate(strings.TrimSpace(tag), 40), "orig_name": truncate(filepath.Base(filename), 120), "mime": info["mime"], "width": info["width"], "height": info["height"], "size": fi.Size(), "created_at": created}
	for _, k := range []string{"c_key", "c_mime", "c_width", "c_height", "c_size"} {
		row[k] = info[k]
	}
	a.insert("images", row)
	return itemJSON(a.image(row["id"]), u)
}
func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}
func (a *App) upload(w http.ResponseWriter, r *http.Request) {
	u := a.require(r, false)
	r.Body = http.MaxBytesReader(w, r.Body, 200<<20)
	defer func() {
		if r.MultipartForm != nil {
			_ = r.MultipartForm.RemoveAll()
		}
	}()
	if e := r.ParseMultipartForm(64 << 10); e != nil {
		fail(413, "invalid multipart or upload larger than 200MB")
	}
	files := r.MultipartForm.File["files"]
	if len(files) == 0 {
		fail(400, "files is required")
	}
	results := []M{}
	for _, f := range files {
		result := func() (res M) {
			res = M{"name": f.Filename, "ok": false}
			key := ""
			committed := false
			defer func() {
				if p := recover(); p != nil {
					switch v := p.(type) {
					case apiError:
						res["error"] = v.message
					default:
						res["error"] = fmt.Sprint(v)
					}
				}
				if !committed && key != "" {
					a.removeFiles(M{"key": key, "c_key": strings.TrimSuffix(key, filepath.Ext(key)) + "." + map[string]string{"webp": "webp", "jpeg": "jpg", "png": "png"}[str(a.limits(u)["format"])]})
				}
			}()
			a.checkUpload(u, f.Size)
			ext := strings.ToLower(strings.TrimPrefix(filepath.Ext(f.Filename), "."))
			if !strings.Contains(",jpg,jpeg,png,webp,avif,gif,bmp,", ","+ext+",") {
				fail(400, "unsupported image extension")
			}
			key = "uploads/" + time.Now().Format("20060102") + "/" + fmt.Sprint(time.Now().Unix()) + "-" + id(8) + "." + ext
			dest := pathIn(filepath.Join(a.data, "uploads"), key)
			must(os.MkdirAll(filepath.Dir(dest), 0755))
			src, e := f.Open()
			must(e)
			defer src.Close()
			out, e := os.Create(dest)
			must(e)
			_, e = io.Copy(out, src)
			ce := out.Close()
			must(e)
			must(ce)
			res["item"] = a.registerFile(dest, key, f.Filename, u, r.FormValue("tag"), false)
			res["ok"] = true
			committed = true
			return
		}()
		results = append(results, result)
	}
	respond(w, M{"results": results, "usage": a.publicUser(u)})
}
func (a *App) removeFiles(im M) {
	for dir, rel := range map[string]string{"uploads": str(im["key"]), "thumbs": str(im["key"]) + ".webp", "compressed": str(im["c_key"])} {
		if rel != "" {
			p := pathIn(filepath.Join(a.data, dir), rel)
			if e := os.Remove(p); e != nil && !os.IsNotExist(e) {
				panic(e)
			}
		}
	}
}
func (a *App) removeImage(im M) { a.removeFiles(im); a.exec("DELETE FROM images WHERE id=?", im["id"]) }

var badStem = regexp.MustCompile(`[\\/:*?"<>|\x00-\x1f]`)
var spaces = regexp.MustCompile(`\s+`)

func safeStem(s string) string {
	s = badStem.ReplaceAllString(strings.TrimSpace(s), "")
	s = strings.ReplaceAll(s, "..", "")
	s = strings.Trim(s, " .")
	s = spaces.ReplaceAllString(s, "-")
	return truncate(s, 80)
}
func (a *App) imageRoute(w http.ResponseWriter, r *http.Request) {
	if r.Method != "PATCH" && r.Method != "DELETE" {
		notFound()
	}
	u := a.require(r, false)
	uid := strings.TrimPrefix(r.URL.Path, "/api/images/")
	im := a.image(uid)
	if im == nil {
		fail(404, "图片不存在")
	}
	if u["role"] != "admin" && im["owner_id"] != u["id"] {
		fail(403, "只能操作自己上传的图片")
	}
	if r.Method == "DELETE" {
		a.removeImage(im)
		respond(w, M{"ok": true, "id": uid})
		return
	}
	v := body(r)
	fields := M{}
	completed := [][2]string{}
	renameSaved := false
	defer func() {
		if p := recover(); p != nil {
			if !renameSaved {
				for i := len(completed) - 1; i >= 0; i-- {
					_ = os.Rename(completed[i][1], completed[i][0])
				}
			}
			panic(p)
		}
	}()
	if tag, ok := v["tag"]; ok {
		fields["tag"] = truncate(strings.TrimSpace(str(tag)), 40)
	}
	if name := str(v["filename"]); name != "" {
		stem := safeStem(name)
		if stem == "" {
			fail(400, "文件名不能为空")
		}
		old := str(im["key"])
		ext := filepath.Ext(old)
		stem = strings.TrimSuffix(stem, ext)
		key := filepath.ToSlash(filepath.Join(filepath.Dir(old), stem+ext))
		if key != old {
			if a.one("SELECT id FROM images WHERE key=?", key) != nil {
				fail(409, "该文件名已存在")
			}
			moves := [][3]string{{"uploads", old, key}, {"thumbs", old + ".webp", key + ".webp"}}
			fields["key"], fields["orig_name"] = key, stem+ext
			if ck := str(im["c_key"]); ck != "" {
				nc := filepath.ToSlash(filepath.Join(filepath.Dir(ck), stem+filepath.Ext(ck)))
				fields["c_key"] = nc
				moves = append(moves, [3]string{"compressed", ck, nc})
			}
			for _, mv := range moves {
				src := pathIn(filepath.Join(a.data, mv[0]), mv[1])
				dst := pathIn(filepath.Join(a.data, mv[0]), mv[2])
				if src == dst {
					continue
				}
				if _, e := os.Stat(src); os.IsNotExist(e) {
					continue
				}
				if _, e := os.Stat(dst); e == nil {
					fail(409, "该文件名已存在")
				}
				must(os.Rename(src, dst))
				completed = append(completed, [2]string{src, dst})
			}
		}
	}
	a.update("images", "id", uid, fields)
	renameSaved = true
	respond(w, itemJSON(a.image(uid), u))
}
