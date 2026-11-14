package main

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
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

type backupFile struct {
	Size   int64
	SHA256 string
}
type galleryManifest struct {
	App    string                `json:"app"`
	Format int                   `json:"format"`
	Files  map[string]backupFile `json:"files"`
}

func zipFile(z *zip.Writer, full, name string, files map[string]backupFile) error {
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
	hash := sha256.New()
	n, e := io.Copy(io.MultiWriter(out, hash), f)
	if e == nil {
		files[name] = backupFile{n, hex.EncodeToString(hash.Sum(nil))}
	}
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
	manifest := galleryManifest{App: "wusaqi-gallery", Format: 2, Files: map[string]backupFile{}}
	must(zipFile(z, snap, "metadata.db", manifest.Files))
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
			return zipFile(z, p, filepath.ToSlash(rel), manifest.Files)
		}))
	}
	out, e := z.Create("MANIFEST.json")
	must(e)
	must(json.NewEncoder(out).Encode(manifest))
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
	seen := map[string]bool{}
	if len(z.File) > 100000 {
		return 0, fmt.Errorf("too many backup entries")
	}
	for _, entry := range z.File {
		name := strings.ReplaceAll(entry.Name, "\\", "/")
		if strings.HasPrefix(name, "/") || strings.ContainsAny(name, ":\x00") || entry.Mode()&os.ModeSymlink != 0 {
			return 0, fmt.Errorf("invalid backup path")
		}
		for _, part := range strings.Split(name, "/") {
			if part == ".." || part == "." {
				return 0, fmt.Errorf("invalid backup path")
			}
		}
		if entry.FileInfo().IsDir() {
			continue
		}
		if !entry.Mode().IsRegular() || seen[name] || strings.Contains(name, "//") {
			return 0, fmt.Errorf("duplicate or invalid backup entry")
		}
		seen[name] = true
		if name != "metadata.db" && name != "MANIFEST.json" && !strings.HasPrefix(name, "uploads/") && !strings.HasPrefix(name, "thumbs/") && !strings.HasPrefix(name, "compressed/") {
			return 0, fmt.Errorf("unexpected backup entry")
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
	if e := verifyGalleryManifest(stage, seen); e != nil {
		return 0, e
	}
	return files, nil
}

func verifyGalleryManifest(stage string, seen map[string]bool) error {
	if !seen["MANIFEST.json"] {
		return nil
	} // Explicit compatibility with pre-manifest backups.
	f, e := os.Open(filepath.Join(stage, "MANIFEST.json"))
	if e != nil {
		return e
	}
	defer f.Close()
	var m galleryManifest
	if json.NewDecoder(io.LimitReader(f, 16<<20)).Decode(&m) != nil || m.App != "wusaqi-gallery" || (m.Format != 1 && m.Format != 2) {
		return fmt.Errorf("wrong application or unsupported backup format")
	}
	if m.Format == 1 {
		return nil
	}
	if len(m.Files) != len(seen)-1 {
		return fmt.Errorf("backup file inventory mismatch")
	}
	for name, expected := range m.Files {
		if name == "MANIFEST.json" || !seen[name] {
			return fmt.Errorf("missing backup file")
		}
		input, e := os.Open(filepath.Join(stage, filepath.FromSlash(name)))
		if e != nil {
			return e
		}
		hash := sha256.New()
		n, e := io.Copy(hash, input)
		input.Close()
		if e != nil || n != expected.Size || hex.EncodeToString(hash.Sum(nil)) != expected.SHA256 {
			return fmt.Errorf("backup checksum mismatch")
		}
	}
	return nil
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
		for _, table := range []string{"users", "settings"} {
			if candidate.count("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", table) != 1 {
				fail(400, "备份缺少账号或配置表")
			}
		}
		if candidate.count("SELECT COUNT(*) FROM users WHERE role='admin'") < 1 {
			fail(400, "备份缺少管理员账号")
		}
		if str(candidate.one("PRAGMA integrity_check")["integrity_check"]) != "ok" {
			fail(400, "invalid backup database")
		}
		candidate.initDB(false)
		// Staging payloads are not part of backups; never replay historical work.
		candidate.exec("DELETE FROM upload_sessions")
		candidate.exec("DELETE FROM repair_items")
		candidate.exec("DELETE FROM repair_job")
		candidate.exec("DELETE FROM sessions")
		images = candidate.count("SELECT COUNT(*) FROM images")
		for _, im := range candidate.rows("SELECT key,c_key FROM images") {
			original := pathIn(filepath.Join(stage, "uploads"), str(im["key"]))
			if st, e := os.Stat(original); e != nil || !st.Mode().IsRegular() {
				fail(400, "备份缺少原图文件")
			}
			pathIn(filepath.Join(stage, "compressed"), str(im["c_key"]))
		}
		candidate.exec("PRAGMA wal_checkpoint(TRUNCATE)")
	}()
	for _, d := range []string{"uploads", "thumbs", "compressed"} {
		must(os.MkdirAll(filepath.Join(stage, d), 0755))
	}
	a.exec("PRAGMA wal_checkpoint(TRUNCATE)")
	must(stageGalleryRestore(a.data, tmp))
	cleanup = false // The durable marker owns this staging directory now.
	a.restorePending.Store(true)
	must(a.db.Close())
	must(applyGalleryRestore(a.data))
	a.db = openDB(filepath.Join(a.data, "metadata.db"))
	a.initDB(false)
	a.restorePending.Store(false)
	a.telegram.changed()
	a.cleanUploadStaging()
	a.setJob(M{"running": false, "cancel": false, "current": ""})
	a.fire("restore", "", M{"images": images, "files": copied, "operator": u["username"]})
	respond(w, M{"ok": true, "relogin": true, "restored": M{"images": images, "files_copied": copied, "restored_at": nowISO()}})
}
