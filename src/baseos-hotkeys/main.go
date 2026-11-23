// baseos-hotkeys handles resolved power and gamepad roles. A short power
// press toggles manual blanking; the board policy controls a two-second hold.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

const (
	evKey = 0x01

	keyPower  = 116 // KEY_POWER, axp2202-pek
	btnSelect = 310 // BTN_TL. Physical Select on the RG34XX.
	btnStart  = 311 // BTN_TR. Physical Start.
	// Linux calls 314/315 BTN_SELECT/BTN_START. This board's DTB wires those
	// codes to the L2/R2 shoulders. Select and Start are 310 and 311, so the
	// quit combo must not listen here or L2+R2 would leave the game.
	btnL2 = 314
	btnR2 = 315

	comboHold = 1500 * time.Millisecond
	longPress = 2 * time.Second

	// First repeat waits, then steps follow. A tap is exactly one step.
	brightDelay  = 380 * time.Millisecond
	brightRepeat = 150 * time.Millisecond
)

type inputEvent struct {
	Sec, Usec int64
	Type      uint16
	Code      uint16
	Value     int32
}

type options struct {
	powerDev        string
	padDev          string
	longPolicy      string
	logPath         string
	runtime         string
	foregroundApp   string
	forceQuitMarker string
	poweroff        string
	dryRun          bool
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

var baseosctl string

var displayMu sync.Mutex

// Callers serialize display operations, including brightness read/modify/write.
func display(args ...string) bool {
	if opt.dryRun {
		logf("dry-run: display %s", strings.Join(args, " "))
		return true
	}
	out, err := exec.Command(baseosctl, append([]string{"display"}, args...)...).CombinedOutput()
	if err != nil {
		logf("display %v: %v %s", args, err, out)
	}
	return err == nil
}

func manualBlanked() bool {
	_, err := os.Stat(os.Getenv("PJOS_RUN_ROOT") + "/run/baseos-display.manual")
	return err == nil
}

func wakePanel() bool {
	displayMu.Lock()
	defer displayMu.Unlock()
	return manualBlanked() && display("blank", "off", "manual")
}

// cmdlineIsGBA reports whether a RetroArch command line is a GBA ROM. The
// supervisor passes the ROM path as an argument, so ".gba" is in the bytes.
// ".gb" and ".gbc" do not contain that suffix.
func cmdlineIsGBA(cmdline string) bool {
	return strings.Contains(cmdline, ".gba")
}

func gbaSession() bool {
	for _, pid := range runtimePids("retroarch") {
		b, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
		if err != nil {
			continue
		}
		if cmdlineIsGBA(string(b)) {
			return true
		}
	}
	return false
}

// bright serialises shoulder-key repeats. L2 and R2 share one held direction.
var bright = struct {
	sync.Mutex
	dir  int
	stop chan struct{}
}{}

func adjustBrightness(dir int) {
	if !gbaSession() {
		return
	}
	displayMu.Lock()
	defer displayMu.Unlock()
	if manualBlanked() {
		return
	}
	if opt.dryRun {
		logf("dry-run: brightness step %d", dir)
		return
	}
	out, err := exec.Command(baseosctl, "display", "get-brightness").Output()
	if err != nil {
		logf("brightness: read failed: %v", err)
		return
	}
	level, err := strconv.Atoi(strings.TrimSpace(string(out)))
	if err != nil || level <= 0 || level > 255 {
		return
	}
	next := min(255, level+15)
	if dir < 0 {
		next = min(level, max(10, level-15))
	}
	if next != level {
		display("set-brightness", strconv.Itoa(next))
	}
}

func stopBrightnessLocked() {
	if bright.stop != nil {
		close(bright.stop)
		bright.stop = nil
	}
	bright.dir = 0
}

func onBrightnessKey(dir int, value int32) {
	// gpio-keys may also emit value 2. The timer below is the repeat.
	if value == 2 {
		return
	}
	if value == 0 {
		bright.Lock()
		if bright.dir == dir {
			stopBrightnessLocked()
		}
		bright.Unlock()
		return
	}
	if value != 1 || !gbaSession() {
		return
	}
	bright.Lock()
	stopBrightnessLocked()
	stop := make(chan struct{})
	bright.stop = stop
	bright.dir = dir
	bright.Unlock()
	go repeatBrightness(dir, stop)
}

func repeatBrightness(dir int, stop <-chan struct{}) {
	adjustBrightness(dir)
	timer := time.NewTimer(brightDelay)
	select {
	case <-stop:
		timer.Stop()
		return
	case <-timer.C:
	}
	ticker := time.NewTicker(brightRepeat)
	defer ticker.Stop()
	for {
		select {
		case <-stop:
			return
		case <-ticker.C:
			adjustBrightness(dir)
		}
	}
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
	targets := captureRuntimeTargets(strings.Split(opt.runtime, ","))
	// Capture identity before signaling: the supervisor clears it on child exit.
	appRaw, _ := os.ReadFile(opt.foregroundApp)
	app := strings.TrimSpace(string(appRaw))
	hasPocket := false
	for _, target := range targets {
		hasPocket = hasPocket || target.name == "pocket-linux-kms"
	}
	if app == "kanade" && !opt.dryRun && hasPocket {
		// Give the service a bounded chance to save playback before its UI dies.
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		cmd := exec.CommandContext(ctx, "/storage/System/compat/bin/kanade-ctl", "POST", "/api/player/stop")
		if err := cmd.Run(); err != nil {
			logf("combo: stop Kanade playback: %v", err)
		}
		cancel()
	}
	signaled := make(map[int]string)
	killed := 0
	foregroundKilled := false
	for _, target := range targets {
		logf("combo: SIGTERM %s pid %d", target.name, target.pid)
		if opt.dryRun {
			continue
		}
		if signalRuntimeTarget(target, syscall.SIGTERM) {
			signaled[target.pid] = target.started
			killed++
			if target.name == "pocket-linux-kms" || target.name == "retroarch" {
				foregroundKilled = true
			}
		}
	}
	if killed == 0 {
		logf("combo: nothing to stop (%s)", opt.runtime)
		return
	}
	// launch_frontend owns this volatile id only while an installed app runtime
	// is foreground. Never use last-active here: it survives ordinary exits and
	// would turn a later launcher quit into a false notification.
	if foregroundKilled && !opt.dryRun {
		if validAppID(app) {
			tmp := opt.forceQuitMarker + ".tmp"
			if err := os.WriteFile(tmp, []byte(app+"\n"), 0o600); err == nil {
				if err := os.Rename(tmp, opt.forceQuitMarker); err != nil {
					_ = os.Remove(tmp)
				}
			}
		}
	}
	go func() {
		time.Sleep(1500 * time.Millisecond)
		// Only retry the original children; a new launcher has the same name.
		for pid, started := range signaled {
			if started != "" && processStart(pid) == started {
				_ = syscall.Kill(pid, syscall.SIGKILL)
			}
		}
	}()
}

// Snapshot before calling a helper that can block: a normal exit during that
// call must never retarget the subsequently respawned launcher.
type runtimeTarget struct {
	name    string
	pid     int
	started string
}

func captureRuntimeTargets(names []string) []runtimeTarget {
	var targets []runtimeTarget
	for _, name := range names {
		name = strings.TrimSpace(name)
		if name == "" {
			continue
		}
		for _, pid := range runtimePids(name) {
			if pid == os.Getpid() {
				continue
			}
			if started := processStart(pid); started != "" {
				targets = append(targets, runtimeTarget{name, pid, started})
			}
		}
	}
	return targets
}

func signalRuntimeTarget(target runtimeTarget, signal syscall.Signal) bool {
	return target.started != "" && processStart(target.pid) == target.started && syscall.Kill(target.pid, signal) == nil
}

// /proc stat field 22 identifies the original process even if its PID is reused.
func processStart(pid int) string {
	raw, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return ""
	}
	end := strings.LastIndexByte(string(raw), ')')
	if end < 0 {
		return ""
	}
	fields := strings.Fields(string(raw)[end+1:])
	if len(fields) <= 19 {
		return ""
	}
	return fields[19]
}

func validAppID(s string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '_' || r == '-') {
			return false
		}
	}
	return true
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

func noteCombo(down *bool, downAt *time.Time, released *time.Time, value int32) {
	combo.Lock()
	defer combo.Unlock()
	if value == 1 {
		*down = true
		if downAt.IsZero() {
			*downAt = time.Now()
		}
		*released = time.Time{}
	} else if value == 0 {
		*down = false
		*released = time.Now()
	}
}

// powerKey is owned by the power loop; the reader never touches its timer or
// state. Keep down set after firing so repeats cannot start another gesture.
type powerKey struct {
	down, consumed bool
	deadline       time.Time
}

const deadlineReached = -1

func (k *powerKey) step(value int32, now time.Time, policy string) string {
	if value == 1 && !k.down {
		*k = powerKey{down: true, deadline: now.Add(longPress)}
		return ""
	}
	if !k.down || (value != 0 && value != deadlineReached) {
		return ""
	}
	action := ""
	if !k.consumed && !now.Before(k.deadline) {
		k.consumed = true
		action = policy
	} else if value == 0 && !k.consumed {
		action = "toggle"
	}
	if value == 0 {
		*k = powerKey{}
	}
	return action
}

func watchPower(events <-chan inputEvent) {
	var key powerKey
	var timer *time.Timer
	var deadline <-chan time.Time
	stopTimer := func() {
		if deadline != nil {
			if !timer.Stop() {
				<-deadline
			}
			deadline = nil
		}
	}
	defer stopTimer()
	for {
		var action string
		select {
		case ev, ok := <-events:
			if !ok {
				return
			}
			if ev.Type != evKey || ev.Code != keyPower || ev.Value < 0 || ev.Value > 2 {
				continue
			}
			wasDown := key.down
			action = key.step(ev.Value, time.Now(), opt.longPolicy)
			if !wasDown && key.down {
				timer = time.NewTimer(time.Until(key.deadline))
				deadline = timer.C
			} else if ev.Value == 0 {
				stopTimer()
			}
		case <-deadline:
			deadline = nil
			action = key.step(deadlineReached, key.deadline, opt.longPolicy)
		}
		switch action {
		case "toggle":
			displayMu.Lock()
			display("blank", "toggle", "manual")
			displayMu.Unlock()
		case "poweroff":
			powerOff()
		case "ignore":
			logf("power: long press ignored")
		}
	}
}

func readLoop(f *os.File, handle func(inputEvent)) {
	var ev inputEvent
	buf := unsafe.Slice((*byte)(unsafe.Pointer(&ev)), int(unsafe.Sizeof(ev)))
	for {
		n, err := f.Read(buf)
		if err != nil || n != len(buf) {
			logf("watch %s: read ended: %d bytes, %v", f.Name(), n, err)
			return
		}
		handle(ev)
	}
}

func handlePad(ev inputEvent) {
	if ev.Type != evKey || ev.Code == keyPower {
		return
	}
	woke := ev.Value == 1 && wakePanel()
	switch ev.Code {
	case btnSelect:
		noteCombo(&combo.selectDown, &combo.selectDownAt, &combo.selectReleased, ev.Value)
	case btnStart:
		noteCombo(&combo.startDown, &combo.startDownAt, &combo.startReleased, ev.Value)
	case btnL2:
		if !woke {
			onBrightnessKey(-1, ev.Value)
		}
	case btnR2:
		if !woke {
			onBrightnessKey(1, ev.Value)
		}
	}
}

func lockOwner(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, err
	}
	return f, nil
}

func openInput(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	info, err := f.Stat()
	if err == nil && info.Mode()&os.ModeCharDevice == 0 {
		err = fmt.Errorf("%s: not a character device", path)
	}
	if err != nil {
		f.Close()
		return nil, err
	}
	return f, nil
}

func run() error {
	lock, err := lockOwner("/run/baseos-hotkeys.lock")
	if err == syscall.EWOULDBLOCK {
		logf("already running; exiting")
		return nil
	}
	if err != nil {
		return err
	}
	defer lock.Close() // Never unlink: subsequent processes must lock the same inode.
	power, err := openInput(opt.powerDev)
	if err != nil {
		return err
	}
	defer power.Close()
	pad, err := openInput(opt.padDev)
	if err != nil {
		return err
	}
	defer pad.Close()
	logf("start power=%s pad=%s long-press=%s", opt.powerDev, opt.padDev, opt.longPolicy)
	go watchCombo()
	go readLoop(pad, handlePad)
	events := make(chan inputEvent)
	go func() {
		defer close(events)
		readLoop(power, func(ev inputEvent) {
			if ev.Type == evKey && ev.Code == keyPower {
				events <- ev
			}
		})
	}()
	watchPower(events)
	return nil
}

func main() {
	flag.StringVar(&baseosctl, "baseosctl", "/usr/sbin/baseosctl", "absolute path to the semantic hardware CLI")
	flag.StringVar(&opt.powerDev, "power-dev", "", "resolved evdev node carrying KEY_POWER")
	flag.StringVar(&opt.padDev, "pad-dev", "", "resolved evdev node carrying gamepad buttons")
	flag.StringVar(&opt.longPolicy, "long-press", "", "profile hold policy: ignore or poweroff")
	flag.StringVar(&opt.logPath, "log", "/tmp/baseos-hotkeys.log", "log file")
	flag.StringVar(&opt.runtime, "runtime", "pocket-linux-kms,retroarch", "comma-separated processes force-quit by SELECT+START")
	flag.StringVar(&opt.foregroundApp, "foreground-app", "/run/baseos-foreground-app", "volatile installed-app id while its runtime is foreground")
	flag.StringVar(&opt.forceQuitMarker, "force-quit-marker", "/run/baseos-force-quit", "one-shot installed-app force-quit notification")
	flag.StringVar(&opt.poweroff, "poweroff", "/usr/sbin/baseos-poweroff", "poweroff helper")
	flag.BoolVar(&opt.dryRun, "dry-run", false, "log actions without modifying the display or stopping processes")
	flag.Parse()
	if !filepath.IsAbs(baseosctl) || !filepath.IsAbs(opt.powerDev) || !filepath.IsAbs(opt.padDev) ||
		(opt.longPolicy != "ignore" && opt.longPolicy != "poweroff") || flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "required: --power-dev /absolute/node --pad-dev /absolute/node --long-press ignore|poweroff")
		os.Exit(2)
	}
	if err := run(); err != nil {
		logf("hotkeys: %v", err)
		os.Exit(1)
	}
}
