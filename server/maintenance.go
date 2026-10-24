package main

import (
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
)

func filePresent(p string) (bool, error) {
	fi, e := os.Stat(p)
	if os.IsNotExist(e) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	return fi.Mode().IsRegular(), nil
}

func (a *App) indexReport(apply bool) M {
	root := filepath.Join(a.data, "uploads")
	fi, e := os.Stat(root)
	if e != nil || !fi.IsDir() {
		fail(409, "原图目录不可用，请先确认数据卷和目录权限")
	}
	out := M{"applied": apply, "indexed": a.count("SELECT COUNT(*) FROM images"), "checked": 0,
		"missingOriginals": 0, "missingThumbs": 0, "missingCompressed": 0, "removed": 0, "resetCompressed": 0, "errorCount": 0}
	items, errors := []M{}, []M{}
	inc := func(k string) { out[k] = num(out[k]) + 1 }
	after := ""
	for {
		rows := a.rows("SELECT * FROM images WHERE id>? ORDER BY id LIMIT 100", after)
		if len(rows) == 0 {
			break
		}
		for _, im := range rows {
			after = str(im["id"])
			inc("checked")
			func() {
				defer func() {
					if p := recover(); p != nil {
						inc("errorCount")
						if len(errors) < 50 {
							errors = append(errors, M{"id": im["id"], "key": im["key"], "error": fmt.Sprint(p)})
						}
					}
				}()
				key, ck := str(im["key"]), str(im["c_key"])
				original, e := filePresent(pathIn(root, key))
				must(e)
				thumb, e := filePresent(pathIn(filepath.Join(a.data, "thumbs"), key+".webp"))
				must(e)
				compressed := false
				if ck != "" {
					compressed, e = filePresent(pathIn(filepath.Join(a.data, "compressed"), ck))
					must(e)
				}
				missingC := !compressed && str(im["mime"]) != "image/gif"
				if !original {
					inc("missingOriginals")
				} else {
					if !thumb {
						inc("missingThumbs")
					}
					if missingC {
						inc("missingCompressed")
					}
				}
				if (!original || !thumb || missingC) && len(items) < 100 {
					items = append(items, M{"id": im["id"], "key": key, "missingOriginal": !original, "missingThumb": !thumb, "missingCompressed": missingC})
				}
				if !apply {
					return
				}
				if !original {
					a.removeImage(im)
					inc("removed")
					return
				}
				if ck != "" && !compressed {
					a.exec("UPDATE images SET c_key=NULL,c_mime=NULL,c_width=NULL,c_height=NULL,c_size=NULL WHERE id=?", im["id"])
					inc("resetCompressed")
				}
			}()
		}
	}
	out["items"], out["errors"] = items, errors
	return out
}

func (a *App) maintenance(w http.ResponseWriter, r *http.Request) {
	apply := r.Method == "POST"
	if r.URL.Path == "/api/admin/local/index" && r.Method == "GET" {
		respond(w, a.indexReport(false))
		return
	}
	if !apply {
		notFound()
	}
	a.jobsMu.Lock()
	busy := truth(a.job["running"])
	a.jobsMu.Unlock()
	if busy {
		fail(409, "导入任务进行中，请结束或取消导入后再维护索引")
	}
	if r.URL.Path == "/api/admin/local/rebuild" {
		respond(w, a.indexReport(true))
		return
	}
	if r.URL.Path != "/api/admin/local/clear-derived" {
		notFound()
	}
	v := body(r)
	if v["confirm"] != "clear-derived" {
		fail(400, "请确认清空缩略图与压缩图")
	}
	removed, errorCount := 0, 0
	errors := []M{}
	for _, dir := range []string{"thumbs", "compressed"} {
		root := filepath.Join(a.data, dir)
		must(os.MkdirAll(root, 0755))
		e := filepath.WalkDir(root, func(p string, d fs.DirEntry, e error) error {
			if e == nil && d.IsDir() {
				return nil
			}
			if e == nil {
				e = os.Remove(p)
			}
			if e != nil {
				errorCount++
				if len(errors) < 50 {
					errors = append(errors, M{"path": p, "error": e.Error()})
				}
			} else {
				removed++
			}
			return nil
		})
		must(e)
	}
	// Original metadata, tags and ownership are preserved; generated files can
	// be recreated by the existing missing-asset repair operation.
	a.exec("UPDATE images SET c_key=NULL,c_mime=NULL,c_width=NULL,c_height=NULL,c_size=NULL")
	respond(w, M{"ok": errorCount == 0, "removedFiles": removed, "errorCount": errorCount, "errors": errors})
}
