package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestZirconTakesPriorityOverLauncher(t *testing.T) {
	card := t.TempDir()
	t.Setenv("PJOS_CARD_ROOT", card)
	previous := opt
	defer func() { opt = previous }()
	opt = options{runtime: "hk-launcher", foregroundApp: filepath.Join(card, "foreground")}

	start := func(rel string) *exec.Cmd {
		t.Helper()
		path := filepath.Join(card, rel)
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			t.Fatal(err)
		}
		b, err := os.ReadFile("/bin/sleep")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(path, b, 0700); err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command(path, "30")
		if err = cmd.Start(); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
		return cmd
	}
	launcher := start("hk-launcher")
	unrelated := start("elsewhere/Mir2eiClient")
	zircon := start("apps/Zircon/GodotClient/Mir2eiClient")
	forceQuit()
	wait := make(chan error, 1)
	go func() { wait <- zircon.Wait() }()
	select {
	case err := <-wait:
		if err == nil || zircon.ProcessState.String() != "signal: terminated" {
			t.Fatalf("Zircon exit: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		_ = zircon.Process.Kill()
		<-wait
		t.Fatal("SELECT+START did not stop the installed Zircon client")
	}
	for _, cmd := range []*exec.Cmd{launcher, unrelated} {
		if processStart(cmd.Process.Pid) == "" || cmd.ProcessState != nil {
			t.Fatalf("stopped unrelated process %s", cmd.Path)
		}
		b, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", cmd.Process.Pid))
		if err != nil || strings.Contains(string(b), ") Z ") {
			t.Fatalf("unrelated process no longer live: %s", cmd.Path)
		}
	}
}

func TestGamepadCannotWakeManualBlank(t *testing.T) {
	root := t.TempDir()
	t.Setenv("PJOS_RUN_ROOT", root)
	if err := os.Mkdir(filepath.Join(root, "run"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "run/baseos-display.manual"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	previous := opt
	defer func() { opt = previous }()
	opt = options{dryRun: true, logPath: filepath.Join(root, "hotkeys.log")}
	for _, code := range []uint16{304, 305, 544, 114, 115} {
		handlePad(inputEvent{Type: evKey, Code: code, Value: 1})
	}
	if b, _ := os.ReadFile(opt.logPath); len(b) != 0 {
		t.Fatalf("non-power input caused an action while manually blanked: %s", b)
	}
}
