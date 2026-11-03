//go:build !windows

package main

import "os"

func replaceOriginal(src, dest string) error { return os.Rename(src, dest) }

// Linux reads MemTotal and cgroup limits in effective().
func physicalMemoryMB() int64 { return 0 }
