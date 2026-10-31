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
	"unsafe"
)

const (
	fbioBlank        = 0x4611
	fbBlankUnblank   = 0
	fbBlankPowerdown = 4

	brightnessNode = "/sys/class/disp/disp/attr/enhance_bright"
	levelFile      = "/run/panel.level"
	markerFile     = "/run/panel.off"
	fbDev          = "/dev/fb0"
)

func ioctlBlank(mode int) error {
	f, err := os.OpenFile(fbDev, os.O_RDWR, 0)
	if err != nil {
		return err
	}
	defer f.Close()
	m := mode
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, f.Fd(), fbioBlank, uintptr(unsafe.Pointer(&m)))
	if errno != 0 {
		return errno
	}
	return nil
}

// brightness reads the first integer of the vendor node ("120 120").
func brightness() (int, bool) {
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

func off() error {
	if v, ok := brightness(); ok && v > 0 {
		os.WriteFile(levelFile, []byte(strconv.Itoa(v)+"\n"), 0o644)
	}
	if err := ioctlBlank(fbBlankPowerdown); err == nil {
		os.WriteFile(markerFile, nil, 0o644)
		return nil
	}
	// Fallback: at least dim the image.
	if err := setBrightness(0); err != nil {
		return err
	}
	os.WriteFile(markerFile, nil, 0o644)
	return nil
}

func on() error {
	level := savedLevel()
	ioctlBlank(fbBlankUnblank) // ignore: the node fallback below still runs
	if err := setBrightness(level); err != nil {
		// Panel is unblanked; brightness node may be write-only or absent.
		if _, statErr := os.Stat(brightnessNode); statErr != nil {
			os.Remove(markerFile)
			return nil
		}
		return err
	}
	os.Remove(markerFile)
	return nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: baseos-panel off|on|level N")
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "off":
		err = off()
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
		err = setBrightness(v)
	default:
		err = fmt.Errorf("unknown command %q", os.Args[1])
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "baseos-panel:", err)
		os.Exit(1)
	}
}
