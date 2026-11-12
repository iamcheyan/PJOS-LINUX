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
//
// The volume wheel is wired to KEY_VOLUMEUP/DOWN on the same two nodes and had
// no listener at all, so rolling it did nothing. Those codes step the mixer
// through the same heya-control the settings row uses, which also plays the
// per-step tick.
package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"sync"
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

	// Measured on the shell: rolling the wheel right emits 115 and rolling it
	// left emits 114, i.e. the vendor labels and the Linux codes disagree.
	keyVolumeUp   = 115
	keyVolumeDown = 114
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
	ui          *os.File
	state       padState
	dirNames    = [4]uint16{keyUp, keyDown, keyLeft, keyRight}
	volumeSteps = make(chan int, 8)
	// One detent can surface on both nodes and the encoder bounces; without a
	// gate one flick jumped the whole range. Steps closer than this are merged.
	volumeGate   = 140 * time.Millisecond
	lastVolumeAt time.Time
	volumeMu     sync.Mutex
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
		case hat && ev.Type == evKey && (ev.Code == keyVolumeUp || ev.Code == keyVolumeDown):
			if ev.Value == 1 {
				step := 5
				if ev.Code == keyVolumeDown {
					step = -5
				}
				requestVolumeStep(step)
			}
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
			case keyVolumeUp:
				if ev.Value == 1 {
					requestVolumeStep(5)
				}
				continue
			case keyVolumeDown:
				if ev.Value == 1 {
					requestVolumeStep(-5)
				}
				continue
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

// heya-control is the single place that knows the mixer, and it plays the tick,
// so the wheel goes through it instead of talking to amixer itself.
func volumeControlPath() string {
	for _, candidate := range []string{
		"/storage/System/compat/bin/heya-control",
		"/usr/share/pocketshell/System/compat/bin/heya-control",
		"/usr/bin/heya-control",
	} {
		if st, err := os.Stat(candidate); err == nil && !st.IsDir() {
			return candidate
		}
	}
	return ""
}

// PCM startup/shutdown ramps temporarily expose maximum codec gain. Read the
// same requested level as the settings UI rather than stepping from that ramp.
func requestedVolume(control string) (int, bool) {
	if control == "" {
		return 0, false
	}
	out, err := exec.Command(control, "volume-state").Output()
	if err != nil {
		return 0, false
	}
	value, err := strconv.Atoi(strings.TrimSpace(string(out)))
	if err != nil || value < 0 || value > 100 {
		return 0, false
	}
	return value, true
}

func currentVolume() int {
	if value, ok := requestedVolume(volumeControlPath()); ok {
		return value
	}
	for _, candidate := range []string{"/bin/amixer", "/usr/bin/amixer"} {
		out, err := exec.Command(candidate, "-c", "0", "sget", "digital volume").Output()
		if err != nil {
			continue
		}
		fields := strings.Split(string(out), "[")
		for _, field := range fields {
			end := strings.IndexByte(field, '%')
			if end <= 0 {
				continue
			}
			if value, err := strconv.Atoi(field[:end]); err == nil {
				return value
			}
		}
	}
	return 50
}

func requestVolumeStep(step int) {
	now := time.Now()
	volumeMu.Lock()
	if now.Sub(lastVolumeAt) < volumeGate {
		volumeMu.Unlock()
		return
	}
	lastVolumeAt = now
	volumeMu.Unlock()
	select {
	case volumeSteps <- step:
	default:
	}
}

func volumeWorker() {
	control := volumeControlPath()
	if control == "" {
		fmt.Fprintln(os.Stderr, "pjos-dpad: heya-control not found; volume keys ignored")
		return
	}
	for step := range volumeSteps {
		// Collapse everything queued behind this step: one flick of the wheel
		// must not walk the whole range while the previous tick still plays.
		for {
			select {
			case queued := <-volumeSteps:
				step = queued
			default:
				goto apply
			}
		}
	apply:
		next := currentVolume() + step
		if next < 0 {
			next = 0
		}
		if next > 100 {
			next = 100
		}
		if err := exec.Command(control, "volume", strconv.Itoa(next)).Run(); err != nil {
			fmt.Fprintf(os.Stderr, "pjos-dpad: volume %d: %v\n", next, err)
		}
		// Pace the wheel: the tick is the feedback, so the next step waits for
		// this one to be heard.
		time.Sleep(120 * time.Millisecond)
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

	go volumeWorker()
	go readDevices(*keyDev, false)
	readDevices(*hatDev, true)
}
