package main

import (
	"archive/zip"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func (a *App) batchImages(w http.ResponseWriter, r *http.Request) {
	download := r.URL.Path == "/api/images/batch/download" && r.Method == "POST"
	if !download && (r.URL.Path != "/api/images/batch" || (r.Method != "PATCH" && r.Method != "DELETE")) {
		notFound()
	}
	u := a.require(r, false)
	v := body(r)
	ids, ok := v["ids"].([]any)
	if !ok || len(ids) == 0 || len(ids) > 500 {
		fail(400, "请选择 1–500 张图片")
	}
	rows, seen := []M{}, map[string]bool{}
	for _, value := range ids {
		id, ok := value.(string)
		if !ok || id == "" || len(id) > 128 {
			fail(400, "invalid image id")
		}
		if seen[id] {
			continue
		}
		seen[id] = true
		im := a.image(id)
		if im == nil {
			fail(404, "图片不存在，请刷新列表")
		}
		if !download && u["role"] != "admin" && im["owner_id"] != u["id"] {
			fail(403, "只能操作自己上传的图片")
		}
		rows = append(rows, im)
	}
	if download {
		a.downloadImages(w, r, rows)
		return
	}
	if r.Method == "PATCH" {
		tag, ok := v["tag"].(string)
		if !ok {
			fail(400, "tag is required")
		}
		args, marks := []any{truncate(strings.TrimSpace(tag), 40)}, []string{}
		for _, im := range rows {
			args = append(args, im["id"])
			marks = append(marks, "?")
		}
		a.exec("UPDATE images SET tag=? WHERE id IN ("+strings.Join(marks, ",")+")", args...)
		respond(w, M{"ok": true, "done": len(rows), "tag": args[0]})
		return
	}
	results, done := []M{}, 0
	for _, im := range rows {
		result := M{"id": im["id"], "ok": false}
		func() {
			defer func() {
				if p := recover(); p != nil {
					result["error"] = fmt.Sprint(p)
				}
			}()
			a.removeImage(im)
			result["ok"] = true
			done++
		}()
		results = append(results, result)
	}
	respond(w, M{"results": results, "done": done, "failed": len(rows) - done})
}

func (a *App) downloadImages(w http.ResponseWriter, r *http.Request, rows []M) {
	files := []*os.File{}
	defer func() {
		for _, f := range files {
			_ = f.Close()
		}
	}()
	// Validate/open every original before sending headers. Stream stored ZIP
	// entries: large selections do not become a large in-memory archive.
	for _, im := range rows {
		f, e := os.Open(pathIn(filepath.Join(a.data, "uploads"), str(im["key"])))
		if e != nil {
			fail(409, "部分原图已不存在或无法读取，请重建索引后重试")
		}
		files = append(files, f)
		fi, e := f.Stat()
		if e != nil || !fi.Mode().IsRegular() {
			fail(409, "原图无法读取")
		}
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="wusaqi-images-`+time.Now().Format("20060102-150405")+`.zip"`)
	w.Header().Set("Cache-Control", "no-store")
	z := zip.NewWriter(w)
	for i, f := range files {
		if r.Context().Err() != nil {
			return
		}
		entry, e := z.CreateHeader(&zip.FileHeader{Name: fmt.Sprintf("%03d-%s", i+1, filepath.Base(str(rows[i]["key"]))), Method: zip.Store})
		if e == nil {
			_, e = io.Copy(entry, f)
		}
		if e != nil {
			log.Printf("batch download interrupted: %v", e)
			return
		}
	}
	if e := z.Close(); e != nil {
		log.Printf("batch download interrupted: %v", e)
	}
}
