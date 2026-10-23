//go:build !windows

package main

// Linux reads MemTotal and cgroup limits in effective().
func physicalMemoryMB() int64 { return 0 }
