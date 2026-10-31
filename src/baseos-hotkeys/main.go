// baseos-hotkeys — the buttons BaseOS is missing on H700 handhelds.
//
// Two things the kernel delivers but nobody listened to:
//
//   - the PMIC power key (axp2202-pek, /dev/input/event0). A short press turns the
//     panel off (screen-off sleep: everything keeps running, any key wakes it), a
//     press held for two seconds powers the device off. ROCKNIX maps the short
//     press to suspend via logind; BaseOS has no logind and its kernel suspend is
//     unreliable, so the panel goes dark instead of freezing the board.
//
//   - SELECT + START on the gamepad. ROCKNIX quits the running program on that
//     combo; here the "program" is the PocketJS frontend, so the daemon terminates
//     it and `frontend-session` respawns the launcher.
//
// Build (static, for the card):
//
//	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o baseos-hotkeys .
package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	evSyn = 0x00
	evKey = 0x01

	keyPower  = 116 // KEY_POWER, axp2202-pek
	btnSelect = 310 // BTN_TL on the RG34XX vendor map
	btnStart  = 311 // BTN_TR
	// A few kernels expose START/SELECT at the mainline codes instead.
	btnSelectAlt = 314
	btnStartAlt  = 315

	comboWindow = 400 * time.Millisecond
	longPress   = 2 * time.Second
)

type inputEvent struct {
	Sec, Usec int64
	Type      uint16
	Code      uint16
	Value     int32
}

type options struct {
	powerDev string
	padDev   string
	panel    string
	level    string
	marker   string
	logPath  string
	runtime  string
	poweroff string
	dryRun   bool
}

var opt options

func logf(format string, args ...any) {
	line := fmt.Sprintf("%s %s", time.Now().Format("2006-01-02T15:04:05"), fmt.Sprintf(format, args...))
	fmt.Println(line)
	if opt.logPath == "" {
		return
	}
	f, err := os.OpenFile(opt.logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	f.WriteString(line + "\n")
}

// panelValue reads the first integer of the backlight node. The vendor node holds
// two space-separated numbers ("50 50"), so a plain Atoi on the whole file fails
// and every read looked like "panel is on".
func panelValue() (int, bool) {
	b, err := os.ReadFile(opt.panel)
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

// panelLit reports whether the panel is currently lit; unknown counts as lit so a
// missing node never leaves the user staring at a black screen.
func panelLit() bool {
	v, ok := panelValue()
	if !ok {
		return true
	}
	return v > 0
}

func panelGet() int {
	v, ok := panelValue()
	if !ok || v <= 0 {
		return 50
	}
	return v
}

func panelSet(level int) error {
	if opt.dryRun {
		logf("dry-run: panel <- %d", level)
		return nil
	}
	return os.WriteFile(opt.panel, []byte(strconv.Itoa(level)), 0o644)
}


// panelHelper returns the baseos-panel binary, which owns the FBIOBLANK ioctl.
func panelHelper() string {
	for _, candidate := range []string{"/mnt/sdcard/System/bin/baseos-panel", "/usr/sbin/baseos-panel"} {
		if st, err := os.Stat(candidate); err == nil && !st.IsDir() {
			return candidate
		}
	}
	return ""
}

// panelOff/panelOn prefer the helper (real panel power down) and fall back to the
// brightness register, which only dims the image.
func panelOff() bool {
	if helper := panelHelper(); helper != "" {
		if err := exec.Command(helper, "off").Run(); err == nil {
			os.WriteFile(opt.marker, nil, 0o644)
			return true
		}
	}
	if panelSet(0) == nil {
		os.WriteFile(opt.marker, nil, 0o644)
		return true
	}
	return false
}

func panelOn() bool {
	if helper := panelHelper(); helper != "" {
		if err := exec.Command(helper, "on").Run(); err == nil {
			os.Remove(opt.marker)
			return true
		}
	}
	level := 50
	if b, err := os.ReadFile(opt.level); err == nil {
		if v, err := strconv.Atoi(strings.TrimSpace(string(b))); err == nil && v > 0 {
			level = v
		}
	}
	if panelSet(level) == nil {
		os.Remove(opt.marker)
		return true
	}
	return false
}

func toggleSleep() {
	if _, err := os.Stat(opt.marker); err != nil && panelLit() {
		if !panelOff() {
			logf("power: panel off failed")
			return
		}
		logf("power: screen off")
		return
	}
	if !panelOn() {
		logf("power: panel on failed")
		return
	}
	logf("power: screen on")
}

// wakePanel restores the level saved before a power-key sleep and clears the
// marker, so screen-idle takes over again. Any face button does this, which is how
// a handheld is expected to wake.
func wakePanel() {
	if _, err := os.Stat(opt.marker); err != nil {
		return
	}
	if !panelOn() {
		logf("wake: panel on failed")
		return
	}
	logf("wake: panel on")
}

func powerOff() {
	logf("power: long press -> poweroff")
	if opt.dryRun {
		return
	}
	cmd := exec.Command(opt.poweroff)
	cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
	if err := cmd.Run(); err != nil {
		logf("power: %s failed: %v", opt.poweroff, err)
	}
}

// forceQuit stops the PocketJS runtime; frontend-session respawns the launcher.
func forceQuit() {
	pids := runtimePids(opt.runtime)
	if len(pids) == 0 {
		logf("combo: SELECT+START but no %s running", opt.runtime)
		return
	}
	for _, pid := range pids {
		if pid == os.Getpid() {
			continue
		}
		logf("combo: SELECT+START -> SIGTERM %s pid %d", opt.runtime, pid)
		syscall.Kill(pid, syscall.SIGTERM)
	}
	go func() {
		time.Sleep(2 * time.Second)
		for _, pid := range runtimePids(opt.runtime) {
			logf("combo: still alive, SIGKILL pid %d", pid)
			syscall.Kill(pid, syscall.SIGKILL)
		}
	}()
}

// runtimePids finds processes whose executable basename matches name.
func runtimePids(name string) []int {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil
	}
	var out []int
	for _, e := range entries {
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		exe, err := os.Readlink("/proc/" + e.Name() + "/exe")
		if err != nil {
			continue
		}
		if strings.HasSuffix(strings.TrimSuffix(exe, " (deleted)"), "/"+name) {
			out = append(out, pid)
		}
	}
	return out
}

func readLoop(dev string) {
	f, err := os.Open(dev)
	if err != nil {
		logf("watch %s: %v", dev, err)
		return
	}
	defer f.Close()

	size := int(unsafe.Sizeof(inputEvent{}))
	var (
		powerDownAt time.Time
		selectDown  time.Time
		startDown   time.Time
		comboFired  bool
	)
	for {
		buf := make([]byte, size)
		n, err := f.Read(buf)
		if err != nil || n != size {
			logf("watch %s: read ended: %v", dev, err)
			return
		}
		ev := *(*inputEvent)(unsafe.Pointer(&buf[0]))
		if ev.Type != evKey {
			continue
		}
		if ev.Value == 1 && ev.Code != keyPower {
			wakePanel()
		}
		switch ev.Code {
		case keyPower:
			if ev.Value == 1 {
				powerDownAt = time.Now()
			} else if ev.Value == 0 && !powerDownAt.IsZero() {
				held := time.Since(powerDownAt)
				powerDownAt = time.Time{}
				if held >= longPress {
					powerOff()
				} else {
					toggleSleep()
				}
			}
		case btnSelect, btnSelectAlt:
			if ev.Value == 1 {
				selectDown = time.Now()
				if !startDown.IsZero() && time.Since(startDown) < comboWindow && !comboFired {
					comboFired = true
					forceQuit()
				}
			} else if ev.Value == 0 {
				selectDown = time.Time{}
				comboFired = false
			}
		case btnStart, btnStartAlt:
			if ev.Value == 1 {
				startDown = time.Now()
				if !selectDown.IsZero() && time.Since(selectDown) < comboWindow && !comboFired {
					comboFired = true
					forceQuit()
				}
			} else if ev.Value == 0 {
				startDown = time.Time{}
				comboFired = false
			}
		}
	}
}

func main() {
	flag.StringVar(&opt.powerDev, "power-dev", "/dev/input/event0", "evdev node carrying KEY_POWER (axp2202-pek)")
	flag.StringVar(&opt.padDev, "pad-dev", "/dev/input/event1", "evdev node carrying the gamepad buttons")
	flag.StringVar(&opt.panel, "panel", "/sys/class/disp/disp/attr/enhance_bright", "panel brightness node")
	flag.StringVar(&opt.level, "level", "/run/panel.level", "where the pre-sleep level is stored")
	flag.StringVar(&opt.marker, "marker", "/run/panel.off", "marker written while the panel is off on purpose")
	flag.StringVar(&opt.logPath, "log", "/tmp/baseos-hotkeys.log", "log file")
	flag.StringVar(&opt.runtime, "runtime", "pocket-linux-kms", "frontend process to force-quit on SELECT+START")
	flag.StringVar(&opt.poweroff, "poweroff", "/usr/sbin/baseos-poweroff", "poweroff helper")
	flag.BoolVar(&opt.dryRun, "dry-run", false, "log actions without touching the panel or powering off")
	flag.Parse()

	// One instance only: a frontend restart replaces the helper, it must not stack
	// a second reader that would toggle the panel against the first.
	if b, err := os.ReadFile("/run/baseos-hotkeys.pid"); err == nil {
		if prev, err := strconv.Atoi(strings.TrimSpace(string(b))); err == nil && prev > 1 {
			if err := syscall.Kill(prev, 0); err == nil {
				logf("already running as %d; exiting", prev)
				return
			}
		}
	}
	os.WriteFile("/run/baseos-hotkeys.pid", []byte(strconv.Itoa(os.Getpid())+"\n"), 0o644)
	// Remember the level the panel booted at, so a power toggle restores the user's
	// brightness rather than whatever the last blanking cycle happened to save.
	if _, err := os.Stat(opt.level); err != nil {
		if v, ok := panelValue(); ok && v > 0 {
			os.WriteFile(opt.level, []byte(strconv.Itoa(v)), 0o644)
		}
	}
	logf("start power=%s pad=%s panel=%s", opt.powerDev, opt.padDev, opt.panel)

	go readLoop(opt.powerDev)
	go readLoop(opt.padDev)
	select {}
}
