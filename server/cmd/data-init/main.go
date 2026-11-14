//go:build linux

// data-init initializes only a dedicated bind/volume and never follows links.
// The actual service is subsequently started as UID/GID 10001.
package main

import (
	"bufio"
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

func prepare(dir string) error {
	path, e := filepath.Abs(dir)
	if e != nil {
		return e
	}
	if path == "/" || (strings.Count(path, "/") < 2 && path != "/data") {
		return fmt.Errorf("use a dedicated application data directory")
	}
	if e = os.MkdirAll(path, 0700); e != nil {
		return e
	}
	st, e := os.Lstat(path)
	if e != nil {
		return e
	}
	if !st.IsDir() {
		return fmt.Errorf("data directory must not be a symlink")
	}
	canonical, e := filepath.EvalSymlinks(path)
	if e != nil || canonical != path {
		return fmt.Errorf("data path must not traverse symlinks")
	}
	mounts, e := os.Open("/proc/self/mountinfo")
	if e != nil {
		return e
	}
	defer mounts.Close()
	scan := bufio.NewScanner(mounts)
	scan.Buffer(make([]byte, 4096), 1<<20)
	unescape := strings.NewReplacer(`\040`, " ", `\011`, "\t", `\012`, "\n", `\134`, `\`)
	for scan.Scan() {
		fields := strings.Fields(scan.Text())
		if len(fields) < 6 {
			return fmt.Errorf("invalid mount table")
		}
		if strings.HasPrefix(filepath.Clean(unescape.Replace(fields[4])), path+"/") {
			return fmt.Errorf("nested mount inside data directory; refusing ownership changes")
		}
	}
	if e = scan.Err(); e != nil {
		return e
	}
	root, e := os.OpenRoot(path)
	if e != nil {
		return e
	}
	defer root.Close()
	dev := st.Sys().(*syscall.Stat_t).Dev
	return fs.WalkDir(root.FS(), ".", func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("symlink inside data directory")
		}
		f, e := root.OpenFile(name, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
		if e != nil {
			return e
		}
		defer f.Close()
		info, e := f.Stat()
		if e != nil {
			return e
		}
		stat := info.Sys().(*syscall.Stat_t)
		if stat.Dev != dev || (!info.IsDir() && (!info.Mode().IsRegular() || stat.Nlink != 1)) {
			return fmt.Errorf("nested filesystem, hard link or special file")
		}
		if stat.Uid != 10001 || stat.Gid != 10001 {
			if e = f.Chown(10001, 10001); e != nil {
				return e
			}
		}
		mode := fs.FileMode(0600)
		if info.IsDir() {
			mode = 0700
		}
		if info.Mode().Perm() != mode {
			return f.Chmod(mode)
		}
		return nil
	})
}
func main() {
	dir := os.Getenv("DATA_DIR")
	if dir == "" {
		dir = "/data"
	}
	if e := prepare(dir); e != nil {
		log.Fatal("Cannot initialize dedicated data: ", e, ". Check NAS ACL/read-only/root-squash; do not use a shared/system directory.")
	}
}
