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
	"time"
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

// paintBlack fills the framebuffer so the panel reads as dark even though the
// vendor kernel gives us no way to switch the backlight off (there is no
// /sys/class/backlight, lcd_bright rejects writes and FBIOBLANK never comes back).
func paintBlack(on bool) error {
	f, err := os.OpenFile(fbDev, os.O_RDWR, 0)
	if err != nil {
		return err
	}
	defer f.Close()
	if !on {
		return nil
	}
	// The panel is 32 bpp with a double buffer (720x960 total).
	buf := make([]byte, 2764800)
	_, err = f.Write(buf)
	return err
}

func freezeRuntime(freeze bool) {
	sig := syscall.SIGSTOP
	if !freeze {
		sig = syscall.SIGCONT
	}
	for _, pid := range runtimePids() {
		syscall.Kill(pid, sig)
	}
}

// offLevel puts the panel to "sleep" without FBIOBLANK: that ioctl powers the
// vendor display engine down and unblank does not bring it back, leaving the
// handheld permanently dark until reboot. Instead freeze the frontend, paint the
// framebuffer black and dim the backlight register — all reversible.
func offLevel(level int) error {
	if v, ok := brightness(); ok && v > 0 {
		os.WriteFile(levelFile, []byte(strconv.Itoa(v)+"\n"), 0o644)
	}
	freezeRuntime(true)
	if err := paintBlack(true); err != nil {
		freezeRuntime(false)
		return err
	}
	setBrightness(0)
	os.WriteFile(markerFile, nil, 0o644)
	return nil
}

func on() error {
	level := savedLevel()
	// Refresh the idle stamp: without it the idle daemon still sees an ancient
	// timestamp and blanks the panel again on its next tick.
	now := time.Now()
	os.Chtimes("/run/screen-idle.stamp", now, now)
	os.WriteFile("/run/screen-idle.stamp", nil, 0o644)
	setBrightness(level)
	// Unblank in case an older build left the engine powered down.
	ioctlBlank(fbBlankUnblank)
	freezeRuntime(false)
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
		// Optional blank level: 1 = FB_BLANK_NORMAL, 4 = FB_BLANK_POWERDOWN (default).
		// Some vendor fb drivers stop the display engine on powerdown and never bring
		// it back on unblank, so the level is selectable.
		level := fbBlankPowerdown
		if len(os.Args) > 2 {
			if v, convErr := strconv.Atoi(os.Args[2]); convErr == nil && v >= 1 && v <= 4 {
				level = v
			}
		}
		err = offLevel(level)
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
