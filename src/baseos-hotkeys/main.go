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
//   - SELECT + START held for three seconds on the gamepad. ROCKNIX quits the
//     running program on that combo; here the "program" may be a PocketJS app
//     (pocket-linux-kms) or the emulator (retroarch), so the daemon terminates
//     whichever owns the panel and the frontend supervisor respawns the launcher.
//     A short press does nothing: three seconds of intent avoids a lost game.
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
	"sync"
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

	comboHold = 1500 * time.Millisecond
	longPress = 2 * time.Second
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

// forceQuit ends whatever owns the panel: a PocketJS app runtime or the
// emulator started for a ROM. The frontend supervisor sees its child exit and
// brings the launcher back.
func forceQuit() {
	names := strings.Split(opt.runtime, ",")
	killed := 0
	for _, name := range names {
		name = strings.TrimSpace(name)
		if name == "" {
			continue
		}
		for _, pid := range runtimePids(name) {
			if pid == os.Getpid() {
				continue
			}
			logf("combo: SIGTERM %s pid %d", name, pid)
			syscall.Kill(pid, syscall.SIGTERM)
			killed++
		}
	}
	if killed == 0 {
		logf("combo: nothing to stop (%s)", opt.runtime)
		return
	}
	go func() {
		time.Sleep(1500 * time.Millisecond)
		for _, name := range names {
			name = strings.TrimSpace(name)
			for _, pid := range runtimePids(name) {
				logf("combo: still alive, SIGKILL %s pid %d", name, pid)
				syscall.Kill(pid, syscall.SIGKILL)
			}
		}
	}()
}

// runtimePids finds processes whose executable basename or comm matches name.
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
		// Match by comm
		commBytes, _ := os.ReadFile(fmt.Sprintf("/proc/%d/comm", pid))
		if strings.TrimSpace(string(commBytes)) == name {
			out = append(out, pid)
			continue
		}
		// Match by exe
		exe, err := os.Readlink(fmt.Sprintf("/proc/%d/exe", pid))
		if err == nil {
			if strings.HasSuffix(strings.TrimSuffix(exe, " (deleted)"), "/"+name) {
				out = append(out, pid)
			}
		}
	}
	return out
}

// combo tracks SELECT+START so the hold can be timed from the moment both
// buttons are down, without blocking on evdev reads. Jitter/bounce under 250ms
// is debounced so micro-switch bounce does not reset the hold timer.
var combo = struct {
	sync.Mutex
	selectDown     bool
	startDown      bool
	selectDownAt   time.Time
	startDownAt    time.Time
	selectReleased time.Time
	startReleased  time.Time
	fired          bool
}{}

func watchCombo() {
	for now := range time.Tick(50 * time.Millisecond) {
		combo.Lock()
		if !combo.selectDown && !combo.selectReleased.IsZero() && now.Sub(combo.selectReleased) > 250*time.Millisecond {
			combo.selectDownAt = time.Time{}
			combo.fired = false
		}
		if !combo.startDown && !combo.startReleased.IsZero() && now.Sub(combo.startReleased) > 250*time.Millisecond {
			combo.startDownAt = time.Time{}
			combo.fired = false
		}

		both := !combo.selectDownAt.IsZero() && !combo.startDownAt.IsZero()
		since := combo.selectDownAt
		if combo.startDownAt.After(since) {
			since = combo.startDownAt
		}
		fire := both && !combo.fired && now.Sub(since) >= comboHold
		if fire {
			combo.fired = true
		}
		combo.Unlock()
		if fire {
			logf("combo: SELECT+START held %s -> ending the foreground program", comboHold)
			forceQuit()
		}
	}
}

func readLoop(dev string) {
	f, err := os.Open(dev)
	if err != nil {
		logf("watch %s: %v", dev, err)
		return
	}
	defer f.Close()

	size := int(unsafe.Sizeof(inputEvent{}))
	var powerDownAt time.Time
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
			combo.Lock()
			if ev.Value == 1 {
				combo.selectDown = true
				if combo.selectDownAt.IsZero() {
					combo.selectDownAt = time.Now()
				}
				combo.selectReleased = time.Time{}
			} else if ev.Value == 0 {
				combo.selectDown = false
				combo.selectReleased = time.Now()
			}
			combo.Unlock()
		case btnStart, btnStartAlt:
			combo.Lock()
			if ev.Value == 1 {
				combo.startDown = true
				if combo.startDownAt.IsZero() {
					combo.startDownAt = time.Now()
				}
				combo.startReleased = time.Time{}
			} else if ev.Value == 0 {
				combo.startDown = false
				combo.startReleased = time.Now()
			}
			combo.Unlock()
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
	flag.StringVar(&opt.runtime, "runtime", "pocket-linux-kms,retroarch", "comma-separated processes force-quit by SELECT+START")
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
	go watchCombo()
	select {}
}
