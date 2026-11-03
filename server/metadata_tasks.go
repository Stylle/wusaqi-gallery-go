package main

import (
	"fmt"
	"os"
	"path/filepath"
)

// Existing media is replaced only after every available variant has cleaned
// successfully. Atomic replacements keep each served file complete. Backups
// allow a failed file/database commit to restore the previous originals.
func (a *App) runMetadata(task M) {
	imageID := task["image_id"]
	var im M
	started := false
	a.writing(func() {
		if !a.repairActive() {
			return
		}
		a.exec("UPDATE repair_items SET status='processing',attempts=attempts+1 WHERE image_id=?", imageID)
		im = a.image(imageID)
		started = true
	})
	if !started {
		return
	}
	if im == nil {
		a.writing(func() {
			a.exec("UPDATE repair_items SET status='skipped',error='图片已删除' WHERE image_id=?", imageID)
		})
		return
	}
	type file struct {
		source, clean, backup string
		before                os.FileInfo
	}
	files := []file{}
	stage, err := os.MkdirTemp(a.data, ".repair-")
	if err != nil {
		a.repairError(task, err)
		return
	}
	keep := false
	defer func() {
		if !keep {
			_ = os.RemoveAll(stage)
		}
	}()
	var info M
	err = caught(func() {
		jobFiles := []M{}
		for _, item := range []struct{ dir, key, kind string }{
			{"uploads", str(im["key"]), "original"},
			{"thumbs", str(im["key"]) + ".webp", "thumb"},
			{"compressed", str(im["c_key"]), "compressed"},
		} {
			if item.key == "" {
				continue
			}
			source := pathIn(filepath.Join(a.data, item.dir), item.key)
			before, e := os.Stat(source)
			if os.IsNotExist(e) && item.kind != "original" {
				continue
			}
			must(e)
			if !before.Mode().IsRegular() {
				fail(409, "图片不是可读取的普通文件")
			}
			clean := filepath.Join(stage, item.kind+".clean")
			files = append(files, file{source, clean, filepath.Join(stage, item.kind+".backup"), before})
			jobFiles = append(jobFiles, M{"path": source, "out": clean, "kind": item.kind})
		}
		var e error
		info, e = a.processJob(M{"op": "sanitize-existing", "files": jobFiles, "limits": a.effective()}, a.effective())
		must(e)
		if num(info["original_size"]) <= 0 {
			fail(400, "未生成清理后的原图")
		}
	})
	if err == nil {
		a.writeMu.Lock()
		func() {
			defer a.writeMu.Unlock()
			completed := 0
			committed := false
			defer func() {
				if !committed {
					for n := completed - 1; n >= 0; n-- {
						if e := replaceOriginal(files[n].backup, files[n].source); e != nil {
							keep = true
							_ = os.WriteFile(filepath.Join(stage, ".keep"), []byte("Metadata cleanup rollback failed; preserve original backups."), 0600)
							err = fmt.Errorf("%v; 恢复原文件失败，备份保留于 %s: %v", err, stage, e)
						}
					}
				}
			}()
			err = caught(func() {
				fresh := a.image(imageID)
				if fresh == nil || fresh["key"] != im["key"] || str(fresh["c_key"]) != str(im["c_key"]) {
					fail(409, "图片在清理期间发生变动，将重试")
				}
				for _, f := range files {
					current, e := os.Stat(f.source)
					must(e)
					if current.Size() != f.before.Size() || !current.ModTime().Equal(f.before.ModTime()) {
						fail(409, "图片文件已发生变动，将重试")
					}
					must(copyOriginal(f.source, f.backup))
					must(os.Chmod(f.backup, f.before.Mode().Perm()))
				}
				for _, f := range files {
					must(replaceOriginal(f.clean, f.source))
					completed++
				}
				tx, e := a.db.Begin()
				must(e)
				defer tx.Rollback()
				_, e = tx.Exec("UPDATE images SET size=?,width=?,height=?,orig_name=?,c_size=COALESCE(?,c_size),c_width=COALESCE(?,c_width),c_height=COALESCE(?,c_height) WHERE id=?", info["original_size"], info["width"], info["height"], filepath.Base(str(im["key"])), info["c_size"], info["c_width"], info["c_height"], imageID)
				must(e)
				_, e = tx.Exec("UPDATE repair_items SET status='done',error='' WHERE image_id=?", imageID)
				must(e)
				must(tx.Commit())
				committed = true
			})
		}()
	}
	a.repairError(task, err)
}
