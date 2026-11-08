// pjos-padmerge — one gamepad out of two kernel devices.
//
// The RG34XX panel exposes the face/shoulder/menu buttons through
// ANBERNIC-keys (event1) already carries the D-pad as ABS_HAT0X/ABS_HAT0Y
// (vendor DTB linux,input-type = EV_ABS). RetroArch's linuxraw driver reads
// one js device and has no hat ids, so those axes must be bound by number
// (js0 axis 3 = HAT0X, axis 4 = HAT0Y). This daemon is not used for that.
// It still mirrors event1 buttons and hats, plus KEY_UP/DOWN/LEFT/RIGHT if
// dierct-keys-polled emits them, into one uinput gamepad ("PJOS Pad").
package main

import (
	"fmt"
	"os"
	"time"
	"unsafe"
)

const (
	evSyn = 0x00
	evKey = 0x01
	evAbs = 0x03

	uiSetEvBit  = 0x40045564
	uiSetKeyBit = 0x40045565
	uiSetAbsBit = 0x40045567
	uiDevCreate = 0x5501

	absHat0X = 0x10
	absHat0Y = 0x11

	keyUp    = 103
	keyDown  = 108
	keyLeft  = 105
	keyRight = 106

	btnDpadUp    = 0x220 // BTN_DPAD_UP (544) -> joydev button 11
	btnDpadDown  = 0x221 // BTN_DPAD_DOWN (545) -> joydev button 12
	btnDpadLeft  = 0x222 // BTN_DPAD_LEFT (546) -> joydev button 13
	btnDpadRight = 0x223 // BTN_DPAD_RIGHT (547) -> joydev button 14
)

type inputID struct {
	BusType, Vendor, Product, Version uint16
}

type uinputUserDev struct {
	Name    [80]byte
	ID      inputID
	FFMax   uint32
	AbsMax  [64]int32
	AbsMin  [64]int32
	AbsFuzz [64]int32
	AbsFlat [64]int32
}

type inputEvent struct {
	Sec, Usec int64
	Type      uint16
	Code      uint16
	Value     int32
}

var buttons = []uint16{
	0x130, 0x131, 0x132, 0x133, 0x134, 0x135, 0x136, 0x137, 0x138, 0x13a, 0x13b,
	btnDpadUp, btnDpadDown, btnDpadLeft, btnDpadRight,
}

var uinputFile *os.File

func ioctl(fd uintptr, req uintptr, arg uintptr) error {
	if _, _, e := syscallIoctl(fd, req, arg); e != 0 {
		return e
	}
	return nil
}

func main() {
	ui, err := os.OpenFile("/dev/uinput", os.O_WRONLY, 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "padmerge: /dev/uinput: %v\n", err)
		os.Exit(1)
	}
	fd := ui.Fd()
	uinputFile = ui
	for _, bit := range []uintptr{evKey, evSyn, evAbs} {
		ioctl(fd, uiSetEvBit, bit)
	}
	for _, code := range buttons {
		ioctl(fd, uiSetKeyBit, uintptr(code))
	}
	for _, axis := range []uintptr{absHat0X, absHat0Y} {
		ioctl(fd, uiSetAbsBit, axis)
	}
	dev := uinputUserDev{ID: inputID{BusType: 0x03, Vendor: 0x1234, Product: 0x5678, Version: 1}}
	copy(dev.Name[:], "PJOS Pad")
	dev.AbsMin[absHat0X], dev.AbsMax[absHat0X] = -1, 1
	dev.AbsMin[absHat0Y], dev.AbsMax[absHat0Y] = -1, 1
	if _, err := ui.Write((*[unsafe.Sizeof(uinputUserDev{})]byte)(unsafe.Pointer(&dev))[:]); err != nil {
		fmt.Fprintf(os.Stderr, "padmerge: write device: %v\n", err)
		os.Exit(1)
	}
	if err := ioctl(fd, uiDevCreate, 0); err != nil {
		fmt.Fprintf(os.Stderr, "padmerge: create: %v\n", err)
		os.Exit(1)
	}
	fmt.Println("padmerge: PJOS Pad created")
	time.Sleep(300 * time.Millisecond)

	go forward("/dev/input/event1", func(ev inputEvent) bool {
		switch ev.Type {
		case evKey:
			for _, b := range buttons {
				if ev.Code == b {
					emit(fd, evKey, ev.Code, ev.Value)
					return true
				}
			}
		case evAbs:
			// Vendor DTB: left/right are HAT0X -1/+1, up/down are HAT0Y -1/+1.
			if ev.Code == absHat0X || ev.Code == absHat0Y {
				emit(fd, evAbs, ev.Code, ev.Value)
				mirrorHat(fd, ev.Code, ev.Value)
				return true
			}
		}
		return false
	})
	go forward("/dev/input/event2", func(ev inputEvent) bool {
		if ev.Type != evKey {
			return false
		}
		switch ev.Code {
		case keyUp:
			emit(fd, evAbs, absHat0Y, -ev.Value)
			emit(fd, evKey, btnDpadUp, ev.Value)
		case keyDown:
			emit(fd, evAbs, absHat0Y, ev.Value)
			emit(fd, evKey, btnDpadDown, ev.Value)
		case keyLeft:
			emit(fd, evAbs, absHat0X, -ev.Value)
			emit(fd, evKey, btnDpadLeft, ev.Value)
		case keyRight:
			emit(fd, evAbs, absHat0X, ev.Value)
			emit(fd, evKey, btnDpadRight, ev.Value)
		default:
			return false
		}
		return true
	})
	select {}
}

func emit(fd uintptr, kind uint16, code uint16, value int32) {
	ev := inputEvent{Type: kind, Code: code, Value: value}
	writeEvent(fd, ev)
	writeEvent(fd, inputEvent{Type: evSyn})
}

func writeEvent(fd uintptr, ev inputEvent) {
	buf := (*[unsafe.Sizeof(inputEvent{})]byte)(unsafe.Pointer(&ev))[:]
	uinputFile.Write(buf)
}

func mirrorHat(fd uintptr, code uint16, value int32) {
	var neg, pos uint16 = btnDpadLeft, btnDpadRight
	if code == absHat0Y {
		neg, pos = btnDpadUp, btnDpadDown
	}
	switch {
	case value < 0:
		emit(fd, evKey, neg, 1)
		emit(fd, evKey, pos, 0)
	case value > 0:
		emit(fd, evKey, pos, 1)
		emit(fd, evKey, neg, 0)
	default:
		emit(fd, evKey, neg, 0)
		emit(fd, evKey, pos, 0)
	}
}

func forward(path string, handle func(ev inputEvent) bool) {
	f, err := os.Open(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "padmerge: %s: %v\n", path, err)
		return
	}
	defer f.Close()
	size := int(unsafe.Sizeof(inputEvent{}))
	for {
		buf := make([]byte, size)
		n, err := f.Read(buf)
		if err != nil || n != size {
			fmt.Fprintf(os.Stderr, "padmerge: %s read: %v\n", path, err)
			return
		}
		ev := *(*inputEvent)(unsafe.Pointer(&buf[0]))
		if ev.Type == evSyn {
			continue
		}
		handle(ev)
	}
}
