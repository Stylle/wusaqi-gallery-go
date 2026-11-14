package main

import (
	"archive/zip"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRestorePromotionResumesAfterEachInterruptedMove(t *testing.T) {
	for cut := 0; cut <= len(galleryRestoreNames); cut++ {
		t.Run(string(rune('0'+cut)), func(t *testing.T) {
			data := t.TempDir()
			root := filepath.Join(data, ".restore-fixture")
			stage := filepath.Join(root, "stage")
			must(os.MkdirAll(stage, 0700))
			for i, name := range galleryRestoreNames {
				if i == 0 {
					must(os.WriteFile(filepath.Join(data, name), []byte("old"), 0600))
					must(os.WriteFile(filepath.Join(stage, name), []byte("new"), 0600))
				} else {
					must(os.MkdirAll(filepath.Join(data, name), 0700))
					must(os.MkdirAll(filepath.Join(stage, name), 0700))
					must(os.WriteFile(filepath.Join(data, name, "old"), nil, 0600))
					must(os.WriteFile(filepath.Join(stage, name, "new"), nil, 0600))
				}
			}
			must(stageGalleryRestore(data, root))
			raw, e := os.ReadFile(filepath.Join(data, "restore-ready.json"))
			must(e)
			var p galleryRestorePlan
			must(json.Unmarshal(raw, &p))
			old := filepath.Join(data, p.Previous)
			must(os.MkdirAll(old, 0700))
			for _, name := range galleryRestoreNames[:cut] {
				must(os.Rename(filepath.Join(data, name), filepath.Join(old, name)))
				must(os.Rename(filepath.Join(stage, name), filepath.Join(data, name)))
			}
			must(applyGalleryRestore(data))
			must(applyGalleryRestore(data))
			current, e := os.ReadFile(filepath.Join(data, "metadata.db"))
			must(e)
			saved, e := os.ReadFile(filepath.Join(old, "metadata.db"))
			must(e)
			if string(current) != "new" || string(saved) != "old" {
				t.Fatal("restore lost data")
			}
		})
	}
}
func TestBackupManifestAndDuplicateValidation(t *testing.T) {
	for _, kind := range []string{"duplicate", "wrong-app", "checksum"} {
		t.Run(kind, func(t *testing.T) {
			file := filepath.Join(t.TempDir(), "backup.zip")
			f, e := os.Create(file)
			must(e)
			z := zip.NewWriter(f)
			w, e := z.Create("metadata.db")
			must(e)
			_, e = w.Write([]byte("fixture"))
			must(e)
			if kind == "duplicate" {
				w, e = z.Create("metadata.db")
				must(e)
				_, e = w.Write([]byte("other"))
				must(e)
			} else {
				w, e = z.Create("MANIFEST.json")
				must(e)
				app := "wusaqi-gallery"
				if kind == "wrong-app" {
					app = "other"
				}
				must(json.NewEncoder(w).Encode(galleryManifest{App: app, Format: 2, Files: map[string]backupFile{"metadata.db": {Size: 7, SHA256: strings.Repeat("0", 64)}}}))
			}
			must(z.Close())
			must(f.Close())
			if _, e = extractBackup(file, t.TempDir()); e == nil {
				t.Fatal("invalid backup accepted")
			}
		})
	}
}
