package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type galleryRestorePlan struct{ Stage, Previous string }

var galleryRestoreNames = []string{"metadata.db", "uploads", "thumbs", "compressed"}

func stageGalleryRestore(data, stage string) error {
	p := galleryRestorePlan{Stage: filepath.Base(stage), Previous: "previous-" + id(16)}
	marker := filepath.Join(data, "restore-ready.json")
	if _, e := os.Lstat(marker); !errors.Is(e, os.ErrNotExist) {
		return fmt.Errorf("restore already pending")
	}
	f, e := os.CreateTemp(data, ".restore-plan-")
	if e != nil {
		return e
	}
	temp := f.Name()
	defer os.Remove(temp)
	if e = json.NewEncoder(f).Encode(p); e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e != nil {
		return e
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(temp, marker)
}

// Restartable filesystem promotion. SQLite must be closed before this call.
func applyGalleryRestore(data string) error {
	marker := filepath.Join(data, "restore-ready.json")
	raw, e := os.ReadFile(marker)
	if errors.Is(e, os.ErrNotExist) {
		return nil
	}
	if e != nil {
		return e
	}
	var p galleryRestorePlan
	safe := func(v, prefix string) bool {
		return strings.HasPrefix(v, prefix) && filepath.Base(v) == v && !strings.ContainsAny(v, "/\\:\x00")
	}
	if json.Unmarshal(raw, &p) != nil || !safe(p.Stage, ".restore-") || !safe(p.Previous, "previous-") {
		return fmt.Errorf("invalid restore plan")
	}
	stageRoot := filepath.Join(data, p.Stage)
	stage := filepath.Join(stageRoot, "stage")
	old := filepath.Join(data, p.Previous)
	if e = os.MkdirAll(old, 0700); e != nil {
		return e
	}
	for _, name := range append([]string{"metadata.db-wal", "metadata.db-shm"}, galleryRestoreNames...) {
		sidecar := strings.HasSuffix(name, "-wal") || strings.HasSuffix(name, "-shm")
		incoming, current, saved := filepath.Join(stage, name), filepath.Join(data, name), filepath.Join(old, name)
		if !sidecar {
			if _, e = os.Stat(incoming); errors.Is(e, os.ErrNotExist) {
				continue
			} else if e != nil {
				return e
			}
		}
		if _, e = os.Stat(saved); errors.Is(e, os.ErrNotExist) {
			if e = os.Rename(current, saved); e != nil && !errors.Is(e, os.ErrNotExist) {
				return e
			}
		} else if e != nil {
			return e
		}
		if !sidecar {
			if e = os.Rename(incoming, current); e != nil {
				return e
			}
		}
	}
	if e = os.Remove(marker); e != nil {
		return e
	}
	return os.RemoveAll(stageRoot)
}
