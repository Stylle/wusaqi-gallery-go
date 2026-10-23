package main

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func (a *App) counts() M {
	out := M{}
	for _, t := range []string{"images", "users", "visits", "bans", "ip_whitelist", "ip_blacklist"} {
		out[t] = a.count("SELECT COUNT(*) FROM " + t)
	}
	return out
}
func (a *App) backupStats() M {
	dirs := M{}
	fi, e := os.Stat(filepath.Join(a.data, "metadata.db"))
	var dbBytes int64
	if e == nil {
		dbBytes = fi.Size()
	}
	total := dbBytes
	for _, d := range []string{"uploads", "thumbs", "compressed"} {
		var n, b int64
		must(filepath.WalkDir(filepath.Join(a.data, d), func(p string, entry fs.DirEntry, e error) error {
			if e != nil {
				return e
			}
			if !entry.IsDir() && entry.Type()&os.ModeSymlink == 0 {
				fi, e := entry.Info()
				if e != nil {
					return e
				}
				n++
				b += fi.Size()
			}
			return nil
		}))
		dirs[d] = M{"bytes": b, "files": n}
		total += b
	}
	return M{"db_bytes": dbBytes, "dirs": dirs, "counts": a.counts(), "data_dir": a.data, "total_bytes": total}
}
func zipFile(z *zip.Writer, full, name string) error {
	f, e := os.Open(full)
	if e != nil {
		return e
	}
	defer f.Close()
	fi, e := f.Stat()
	if e != nil {
		return e
	}
	h, e := zip.FileInfoHeader(fi)
	if e != nil {
		return e
	}
	h.Name = name
	h.Method = zip.Store
	out, e := z.CreateHeader(h)
	if e != nil {
		return e
	}
	_, e = io.Copy(out, f)
	return e
}
func (a *App) downloadBackup(w http.ResponseWriter, r *http.Request) {
	a.writeMu.Lock()
	defer a.writeMu.Unlock()
	tmp, e := os.MkdirTemp(a.data, ".backup-")
	must(e)
	defer os.RemoveAll(tmp)
	snap := filepath.Join(tmp, "metadata.db")
	a.exec("VACUUM INTO '" + strings.ReplaceAll(snap, "'", "''") + "'")
	name := "wusaqi-backup-" + time.Now().Format("20060102-150405") + ".zip"
	dest := filepath.Join(tmp, name)
	f, e := os.Create(dest)
	must(e)
	z := zip.NewWriter(f)
	defer f.Close()
	defer z.Close()
	must(zipFile(z, snap, "metadata.db"))
	out, e := z.Create("MANIFEST.json")
	must(e)
	must(json.NewEncoder(out).Encode(M{"app": "wusaqi-gallery", "format": 1, "created_at": nowISO(), "counts": a.counts(), "data_dir": a.data}))
	for _, d := range []string{"uploads", "thumbs", "compressed"} {
		must(filepath.WalkDir(filepath.Join(a.data, d), func(p string, entry fs.DirEntry, e error) error {
			if e != nil {
				return e
			}
			if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 {
				return nil
			}
			rel, e := filepath.Rel(a.data, p)
			if e != nil {
				return e
			}
			return zipFile(z, p, filepath.ToSlash(rel))
		}))
	}
	must(z.Close())
	must(f.Close())
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"%s\"", name))
	w.Header().Set("X-Backup-Images", fmt.Sprint(a.count("SELECT COUNT(*) FROM images")))
	http.ServeFile(w, r, dest)
}
func extractBackup(file, stage string) (int, error) {
	z, e := zip.OpenReader(file)
	if e != nil {
		return 0, e
	}
	defer z.Close()
	var expanded uint64
	files := 0
	for _, entry := range z.File {
		name := strings.ReplaceAll(entry.Name, "\\", "/")
		if strings.HasPrefix(name, "/") || strings.Contains(name, ":") || entry.Mode()&os.ModeSymlink != 0 {
			return 0, fmt.Errorf("invalid backup path")
		}
		for _, part := range strings.Split(name, "/") {
			if part == ".." {
				return 0, fmt.Errorf("invalid backup path")
			}
		}
		if entry.FileInfo().IsDir() {
			continue
		}
		if name != "metadata.db" && name != "MANIFEST.json" && !strings.HasPrefix(name, "uploads/") && !strings.HasPrefix(name, "thumbs/") && !strings.HasPrefix(name, "compressed/") {
			continue
		}
		if entry.UncompressedSize64 > (20<<30)-expanded {
			return 0, fmt.Errorf("expanded backup larger than 20GB")
		}
		expanded += entry.UncompressedSize64
		dest := filepath.Join(stage, filepath.FromSlash(name))
		if e := os.MkdirAll(filepath.Dir(dest), 0755); e != nil {
			return 0, e
		}
		src, e := entry.Open()
		if e != nil {
			return 0, e
		}
		out, e := os.Create(dest)
		if e != nil {
			src.Close()
			return 0, e
		}
		_, ce := io.Copy(out, io.LimitReader(src, int64(entry.UncompressedSize64)+1))
		src.Close()
		e = out.Close()
		if ce != nil {
			return 0, ce
		}
		if e != nil {
			return 0, e
		}
		if name != "metadata.db" && name != "MANIFEST.json" {
			files++
		}
	}
	return files, nil
}
func (a *App) restoreBackup(w http.ResponseWriter, r *http.Request, u M) {
	r.Body = http.MaxBytesReader(w, r.Body, 20<<30)
	mr, e := r.MultipartReader()
	if e != nil {
		fail(400, "invalid multipart")
	}
	tmp, e := os.MkdirTemp(a.data, ".restore-")
	must(e)
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.RemoveAll(tmp)
		}
	}()
	archive := filepath.Join(tmp, "backup.zip")
	found := false
	for {
		part, e := mr.NextPart()
		if e == io.EOF {
			break
		}
		if e != nil {
			fail(400, e.Error())
		}
		if part.FormName() != "file" {
			part.Close()
			continue
		}
		if !strings.HasSuffix(strings.ToLower(part.FileName()), ".zip") {
			fail(400, "backup must be a .zip file")
		}
		f, e := os.Create(archive)
		must(e)
		_, ce := io.Copy(f, part)
		f.Close()
		part.Close()
		if ce != nil {
			fail(413, ce.Error())
		}
		found = true
		break
	}
	if !found {
		fail(400, "file is required")
	}
	stage := filepath.Join(tmp, "stage")
	must(os.MkdirAll(stage, 0755))
	copied, e := extractBackup(archive, stage)
	if e != nil {
		fail(400, e.Error())
	}
	dbPath := filepath.Join(stage, "metadata.db")
	if !exists(dbPath) {
		fail(400, "备份里没有 metadata.db")
	}
	// Validate and migrate off to the side. Invalid archives never touch live data.
	images := int64(0)
	func() {
		defer func() {
			if p := recover(); p != nil {
				fail(400, fmt.Sprint(p))
			}
		}()
		candidate := &App{data: stage, db: openDB(dbPath)}
		defer candidate.db.Close()
		if candidate.count("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='images'") != 1 {
			fail(400, "备份缺少 images 表")
		}
		if str(candidate.one("PRAGMA integrity_check")["integrity_check"]) != "ok" {
			fail(400, "invalid backup database")
		}
		candidate.initDB(false)
		candidate.exec("DELETE FROM sessions")
		images = candidate.count("SELECT COUNT(*) FROM images")
		for _, im := range candidate.rows("SELECT key,c_key FROM images") {
			pathIn(filepath.Join(stage, "uploads"), str(im["key"]))
			pathIn(filepath.Join(stage, "compressed"), str(im["c_key"]))
		}
		candidate.exec("PRAGMA wal_checkpoint(TRUNCATE)")
	}()
	for _, d := range []string{"uploads", "thumbs", "compressed"} {
		must(os.MkdirAll(filepath.Join(stage, d), 0755))
	}
	a.exec("PRAGMA wal_checkpoint(TRUNCATE)")
	old := filepath.Join(tmp, "previous")
	must(os.MkdirAll(old, 0755))
	movedOld, movedNew := []string{}, []string{}
	committed := false
	defer func() {
		if !committed {
			_ = a.db.Close()
			for i := len(movedNew) - 1; i >= 0; i-- {
				d := movedNew[i]
				if e := os.Rename(filepath.Join(a.data, d), filepath.Join(stage, d)); e != nil {
					cleanup = false
					log.Printf("restore rollback: %v; retained %s", e, tmp)
				}
			}
			for i := len(movedOld) - 1; i >= 0; i-- {
				d := movedOld[i]
				if e := os.Rename(filepath.Join(old, d), filepath.Join(a.data, d)); e != nil {
					cleanup = false
					log.Printf("restore rollback: %v; retained %s", e, tmp)
				}
			}
			a.db = openDB(filepath.Join(a.data, "metadata.db"))
		}
	}()
	must(a.db.Close())
	for _, d := range []string{"metadata.db", "metadata.db-wal", "metadata.db-shm", "uploads", "thumbs", "compressed"} {
		if _, e := os.Stat(filepath.Join(a.data, d)); os.IsNotExist(e) {
			continue
		}
		must(os.Rename(filepath.Join(a.data, d), filepath.Join(old, d)))
		movedOld = append(movedOld, d)
	}
	for _, d := range []string{"metadata.db", "uploads", "thumbs", "compressed"} {
		must(os.Rename(filepath.Join(stage, d), filepath.Join(a.data, d)))
		movedNew = append(movedNew, d)
	}
	a.db = openDB(filepath.Join(a.data, "metadata.db"))
	a.initDB(false)
	committed = true
	a.setJob(M{"running": false, "cancel": false, "current": ""})
	a.fire("restore", "", M{"images": images, "files": copied, "operator": u["username"]})
	respond(w, M{"ok": true, "relogin": true, "restored": M{"images": images, "files_copied": copied, "restored_at": nowISO()}})
}
