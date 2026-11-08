// pjos-dpad — publish the RG34XX D-pad as ordinary arrow keys.
//
// The vendor DTB reports directions on two nodes that the PocketJS launcher
// would each have to understand: ANBERNIC-keys carries them as ABS_HAT0X/Y
// (the node RetroArch reads) and dierct-keys-polled repeats them as
// KEY_UP/DOWN/LEFT/RIGHT. Either way, the event that reaches the panel depends
// on which node the vendor driver felt like updating.
//
// This daemon reads both and mirrors the combined state into one uinput
// keyboard device ("PJOS D-pad") that emits only arrow keys. The frontend
// passes that node to the runtime and skips the raw D-pad node, so exactly one
// source of directions exists no matter which node the kernel updates.
package main

import (
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"
	"unsafe"
)

const (
	evSyn = 0x00
	evKey = 0x01
	evAbs = 0x03

	uiSetEvBit   = 0x40045564
	uiSetKeyBit  = 0x40045565
	uiDevCreate  = 0x5501
	uiDevDestroy = 0x5502

	absHat0X = 0x10
	absHat0Y = 0x11

	keyUp    = 103
	keyDown  = 108
	keyLeft  = 105
	keyRight = 106
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

// One slot per direction; the two nodes may disagree for a moment, so each
// source has its own flag and the emitted state is their union.
type padState struct {
	hat  [4]bool // up, down, left, right
	keys [4]bool
	live [4]bool
}

var (
	ui       *os.File
	state    padState
	dirNames = [4]uint16{keyUp, keyDown, keyLeft, keyRight}
)

func ioctlErr(fd uintptr, req uintptr, arg uintptr) error {
	if _, _, e := syscall.Syscall(syscall.SYS_IOCTL, fd, req, arg); e != 0 {
		return e
	}
	return nil
}

func emit(code uint16, pressed bool) {
	value := int32(0)
	if pressed {
		value = 1
	}
	writeEvent(inputEvent{Type: evKey, Code: code, Value: value})
	writeEvent(inputEvent{Type: evSyn})
}

func writeEvent(ev inputEvent) {
	buf := (*[unsafe.Sizeof(inputEvent{})]byte)(unsafe.Pointer(&ev))[:]
	ui.Write(buf)
}

func publish() {
	for i := 0; i < 4; i++ {
		live := state.hat[i] || state.keys[i]
		if live == state.live[i] {
			continue
		}
		state.live[i] = live
		emit(dirNames[i], live)
	}
}

func createDevice(name string) error {
	f, err := os.OpenFile("/dev/uinput", os.O_WRONLY, 0)
	if err != nil {
		return err
	}
	ui = f
	fd := f.Fd()
	for _, bit := range []uintptr{evKey, evSyn} {
		if err := ioctlErr(fd, uiSetEvBit, bit); err != nil {
			return err
		}
	}
	for _, code := range dirNames {
		if err := ioctlErr(fd, uiSetKeyBit, uintptr(code)); err != nil {
			return err
		}
	}
	dev := uinputUserDev{ID: inputID{BusType: 0x03, Vendor: 0x1234, Product: 0x5679, Version: 1}}
	copy(dev.Name[:], name)
	if _, err := ui.Write((*[unsafe.Sizeof(uinputUserDev{})]byte)(unsafe.Pointer(&dev))[:]); err != nil {
		return err
	}
	if err := ioctlErr(fd, uiDevCreate, 0); err != nil {
		return err
	}
	return nil
}

func readDevices(path string, hat bool) {
	f, err := os.Open(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pjos-dpad: %s: %v\n", path, err)
		return
	}
	defer f.Close()
	size := int(unsafe.Sizeof(inputEvent{}))
	for {
		buf := make([]byte, size)
		n, err := f.Read(buf)
		if err != nil || n != size {
			return
		}
		ev := *(*inputEvent)(unsafe.Pointer(&buf[0]))
		switch {
		case hat && ev.Type == evAbs && (ev.Code == absHat0X || ev.Code == absHat0Y):
			if ev.Code == absHat0Y {
				state.hat[0] = ev.Value < 0
				state.hat[1] = ev.Value > 0
			} else {
				state.hat[2] = ev.Value < 0
				state.hat[3] = ev.Value > 0
			}
			publish()
		case !hat && ev.Type == evKey:
			switch ev.Code {
			case keyUp:
				state.keys[0] = ev.Value != 0
			case keyDown:
				state.keys[1] = ev.Value != 0
			case keyLeft:
				state.keys[2] = ev.Value != 0
			case keyRight:
				state.keys[3] = ev.Value != 0
			default:
				continue
			}
			publish()
		}
	}
}

func main() {
	hatDev := flag.String("hat-dev", "/dev/input/event1", "node reporting ABS_HAT0X/Y")
	keyDev := flag.String("keys-dev", "/dev/input/event2", "node reporting arrow key codes")
	name := flag.String("name", "PJOS D-pad", "uinput device name")
	flag.Parse()

	if err := createDevice(*name); err != nil {
		fmt.Fprintf(os.Stderr, "pjos-dpad: %v\n", err)
		os.Exit(1)
	}
	fmt.Println("pjos-dpad: created", *name)
	time.Sleep(200 * time.Millisecond)

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		<-stop
		ioctlErr(ui.Fd(), uiDevDestroy, 0)
		os.Exit(0)
	}()

	go readDevices(*keyDev, false)
	readDevices(*hatDev, true)
}
