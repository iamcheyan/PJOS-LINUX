// baseos-panel — set the H700 panel's backlight, and turn it off and on.
//
// The vendor kernel exposes no /sys/class/backlight, and its /dev/disp
// brightness ioctls (0x102 set, 0x106) answer EPERM for every screen selector
// because the display driver owns the value. Writing disp/attr/enhance_bright
// changes nothing physical: it is an image-enhancement register, not the
// backlight, which is why the settings slider moved while the panel did not.
//
// The value that does drive the panel is the PWM channel the display driver
// holds for the LCD (pwm-0 of /sys/class/pwm/pwmchip0, period 20000 ns). The
// driver exposes it through debugfs: write a command name, a display name and a
// 0..255 level to /sys/kernel/debug/dispdbg, then raise "start", and the
// driver's own backlight path runs. Measured on the RG34XX: 0 -> duty 0 ns,
// 100 -> 7891 ns, 255 -> 19922 ns; disp/attr/sys then reports "backlight(N)".
//
//	baseos-panel level 120    # set the backlight (0..255)
//	baseos-panel off          # backlight off; the framebuffer keeps running
//	baseos-panel on           # restore the saved level
//
// Build: CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o baseos-panel .
package main

import (
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	levelFile  = "/run/panel.level"
	markerFile = "/run/panel.off"

	// The display driver's debugfs control surface. "start" is a trigger, so
	// the command, display and level must be written first and start last.
	dispDbgDir   = "/sys/kernel/debug/dispdbg"
	dispDisplay  = "lcd0"
	dispLevelMax = 255

	// The driver prints its live level here as "backlight( 50)".
	dispSysFile = "/sys/class/disp/disp/attr/sys"
)

// dispWrite stores one value in a dispdbg attribute. Every write is its own
// open: the driver latches the command when "start" is written, not before.
func dispWrite(attr, value string) error {
	return os.WriteFile(dispDbgDir+"/"+attr, []byte(value+"\n"), 0o644)
}

// dispCommand runs one of the display driver's own commands against the LCD.
// level is the argument of "setbl" and is ignored by the others.
func dispCommand(command string, level int) error {
	if err := dispWrite("start", "0"); err != nil {
		return err
	}
	if err := dispWrite("name", dispDisplay); err != nil {
		return err
	}
	if err := dispWrite("command", command); err != nil {
		return err
	}
	if err := dispWrite("param", strconv.Itoa(level)); err != nil {
		return err
	}
	return dispWrite("start", "1")
}

var backlightPattern = regexp.MustCompile(`backlight\(\s*(\d+)\s*\)`)

// brightness reads the level the driver actually applied. Reading it back from
// dispdbg's "info" is not enough on its own: it echoes the last request, so a
// refused write would still look applied. disp/attr/sys prints the live value.
func brightness() (int, bool) {
	b, err := os.ReadFile(dispSysFile)
	if err != nil {
		return 0, false
	}
	m := backlightPattern.FindSubmatch(b)
	if m == nil {
		return 0, false
	}
	v, err := strconv.Atoi(string(m[1]))
	if err != nil {
		return 0, false
	}
	return v, true
}

// setLevel writes the backlight and verifies the read-back, so a kernel without
// the dispdbg surface fails loudly instead of leaving a slider that lies.
func setLevel(level int) error {
	level = clampLevel(level)
	if err := dispCommand("setbl", level); err != nil {
		return err
	}
	if got, ok := brightness(); ok && got != level {
		return fmt.Errorf("backlight reads %d after setting %d", got, level)
	}
	return nil
}

func clampLevel(level int) int {
	if level < 0 {
		return 0
	}
	if level > dispLevelMax {
		return dispLevelMax
	}
	return level
}

func savedLevel() int {
	if b, err := os.ReadFile(levelFile); err == nil {
		if v, err := strconv.Atoi(strings.TrimSpace(string(b))); err == nil && v > 0 {
			return clampLevel(v)
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

// offLevel stores the real level then asks the display driver to turn the
// backlight off. The framebuffer keeps running, so key wake is immediate.
func offLevel(_ int) error {
	if v, ok := brightness(); ok && v > 0 {
		_ = os.WriteFile(levelFile, []byte(strconv.Itoa(v)+"\n"), 0o644)
	}
	if err := dispCommand("setbl", 0); err != nil {
		return err
	}
	_ = os.WriteFile(markerFile, nil, 0o644)
	return nil
}

func on() error {
	if err := dispCommand("setbl", savedLevel()); err != nil {
		return err
	}
	now := time.Now()
	_ = os.Chtimes("/run/screen-idle.stamp", now, now)
	_ = os.WriteFile("/run/screen-idle.stamp", nil, 0o644)
	_ = os.Remove(markerFile)
	return nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: baseos-panel off|on|level [N]")
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "off":
		err = offLevel(0)
	case "on":
		err = on()
	case "level":
		if len(os.Args) == 2 {
			if value, ok := brightness(); ok {
				fmt.Println(value)
			} else {
				err = fmt.Errorf("cannot read driver's backlight level")
			}
			break
		}
		value, convErr := strconv.Atoi(os.Args[2])
		if convErr != nil {
			err = convErr
			break
		}
		err = setLevel(value)
		if err == nil {
			if actual, ok := brightness(); ok {
				fmt.Println(actual)
			} else {
				err = fmt.Errorf("cannot read driver's backlight level")
			}
		}
	default:
		err = fmt.Errorf("unknown command %q", os.Args[1])
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "baseos-panel:", err)
		os.Exit(1)
	}
}
