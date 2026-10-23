//go:build windows

package main

import (
	"golang.org/x/sys/windows"
	"unsafe"
)

func physicalMemoryMB() int64 {
	var status struct {
		Length, Load                                                                                         uint32
		TotalPhys, AvailPhys, TotalPageFile, AvailPageFile, TotalVirtual, AvailVirtual, AvailExtendedVirtual uint64
	}
	status.Length = uint32(unsafe.Sizeof(status))
	proc := windows.NewLazySystemDLL("kernel32.dll").NewProc("GlobalMemoryStatusEx")
	ok, _, _ := proc.Call(uintptr(unsafe.Pointer(&status)))
	if ok == 0 {
		return 0
	}
	return int64(status.TotalPhys / 1048576)
}
