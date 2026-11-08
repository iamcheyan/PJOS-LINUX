package main

import (
	"syscall"
	"unsafe"
)

func syscallIoctl(fd, req, arg uintptr) (uintptr, uintptr, syscall.Errno) {
	r, _, e := syscall.Syscall(syscall.SYS_IOCTL, fd, req, arg)
	return r, 0, e
}

var _ = unsafe.Pointer(nil)
