// baseos-panel — turn the H700 panel off and on.
//
// The vendor kernel exposes no /sys/class/backlight: the only brightness node
// (disp/attr/enhance_bright) is an image-enhancement register, and writing 0 to it
// leaves the backlight lit. The panel itself is powered down through the
// framebuffer's FBIOBLANK ioctl, which the fb driver implements; the brightness
// node is kept as a fallback so a kernel without FBIOBLANK still dims.
//
//	baseos-panel off          # FB_BLANK_POWERDOWN (panel dark, framebuffer kept)
//	baseos-panel on           # FB_BLANK_UNBLANK, restore the saved level
//	baseos-panel level 120    # set brightness only
//
// Build: CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o baseos-panel .
package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	brightnessNode = "/sys/class/disp/disp/attr/enhance_bright"
	levelFile      = "/run/panel.level"
	markerFile     = "/run/panel.off"
	dispDev        = "/dev/disp"

	// Allwinner disp commands (the vendor u-boot uses the same numbers for
	// backlight on/off; the kernel's /dev/disp ioctl takes a pointer to two u32:
	// {display selector, argument}).
	dispCmdLcdSetBright = 0x102
	dispCmdLcdGetBright = 0x103
	dispCmdBacklightOn  = 0x104
	dispCmdBacklightOff = 0x105
)

// dispCall issues a disp ioctl. The kernel expects a pointer to a u32 pair even
// for the on/off commands — a bare value returns EFAULT.
func dispCall(cmd uintptr, selector, value uint32) (int, error) {
	f, err := os.OpenFile(dispDev, os.O_RDWR, 0)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	args := [2]uint32{selector, value}
	r, _, errno := syscall.Syscall(syscall.SYS_IOCTL, f.Fd(), cmd, uintptr(unsafe.Pointer(&args[0])))
	if errno != 0 {
		return int(r), errno
	}
	return int(r), nil
}

func dispGetBright() (int, error) {
	f, err := os.OpenFile(dispDev, os.O_RDWR, 0)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	args := [2]uint32{0, 0}
	r, _, errno := syscall.Syscall(syscall.SYS_IOCTL, f.Fd(), dispCmdLcdGetBright, uintptr(unsafe.Pointer(&args[0])))
	if errno != 0 {
		return 0, errno
	}
	return int(r), nil
}

// setLevel tries the disp brightness command first. On this driver it answers
// EPERM (the kernel keeps brightness for itself), so the enhancement node — the
// same register the launcher's slider writes — is the fallback.
func setLevel(level int) error {
	if _, err := dispCall(dispCmdLcdSetBright, 0, uint32(level)); err == nil {
		return nil
	}
	return setBrightness(level)
}

func screenOff() error {
	_, err := dispCall(dispCmdBacklightOff, 0, 0)
	return err
}

func screenOn() error {
	_, err := dispCall(dispCmdBacklightOn, 0, 0)
	return err
}

// brightness prefers the disp driver's real backlight value (the ioctl returns it
// directly); the enhancement node is only a fallback.
func brightness() (int, bool) {
	if v, err := dispGetBright(); err == nil && v >= 0 {
		return v, true
	}
	return nodeBrightness()
}

func nodeBrightness() (int, bool) {
	b, err := os.ReadFile(brightnessNode)
	if err != nil {
		return 0, false
	}
	fields := strings.Fields(string(b))
	if len(fields) == 0 {
		return 0, false
	}
	v, err := strconv.Atoi(fields[0])
	if err != nil {
		return 0, false
	}
	return v, true
}

func setBrightness(v int) error {
	return os.WriteFile(brightnessNode, []byte(strconv.Itoa(v)+"\n"), 0o644)
}

func savedLevel() int {
	if b, err := os.ReadFile(levelFile); err == nil {
		if v, err := strconv.Atoi(strings.TrimSpace(string(b))); err == nil && v > 0 {
			return v
		}
	}
	return 120
}

// runtimePids finds the PocketJS frontend by executable basename.
func runtimePids() []int {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil
	}
	var out []int
	for _, e := range entries {
		pid, err := strconv.Atoi(e.Name())
		if err != nil || pid == os.Getpid() {
			continue
		}
		exe, err := os.Readlink("/proc/" + e.Name() + "/exe")
		if err != nil {
			continue
		}
		if strings.HasSuffix(strings.TrimSuffix(exe, " (deleted)"), "/pocket-linux-kms") {
			out = append(out, pid)
		}
	}
	return out
}

// offLevel switches the backlight off through the vendor disp ioctl — the only
// path that actually stops the panel on this kernel (there is no
// /sys/class/backlight, the PWM channels belong to the disp driver and FBIOBLANK
// never unblanks). The PanelOn ioctl brings it back, so sleep is reversible.
func offLevel(_ int) error {
	if v, ok := brightness(); ok && v > 0 {
		os.WriteFile(levelFile, []byte(strconv.Itoa(v)+"\n"), 0o644)
	}
	if err := screenOff(); err != nil {
		return err
	}
	os.WriteFile(markerFile, nil, 0o644)
	return nil
}

func on() error {
	now := time.Now()
	os.Chtimes("/run/screen-idle.stamp", now, now)
	os.WriteFile("/run/screen-idle.stamp", nil, 0o644)
	if err := screenOn(); err != nil {
		return err
	}
	os.Remove(markerFile)
	return nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: baseos-panel off [1-4]|on|level N")
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "off":
		err = offLevel(0)
	case "on":
		err = on()
	case "level":
		if len(os.Args) < 3 {
			err = fmt.Errorf("level needs a value")
			break
		}
		v, convErr := strconv.Atoi(os.Args[2])
		if convErr != nil {
			err = convErr
			break
		}
		err = setLevel(v)
	default:
		err = fmt.Errorf("unknown command %q", os.Args[1])
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "baseos-panel:", err)
		os.Exit(1)
	}
}
