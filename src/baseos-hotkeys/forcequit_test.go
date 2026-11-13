package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
)

func TestSignalsRequireCapturedProcessIdentity(t *testing.T) {
	current := runtimeTarget{pid: os.Getpid(), started: processStart(os.Getpid())}
	if !signalRuntimeTarget(current, 0) {
		t.Fatal("current identity not found")
	}
	current.started = "not-the-original-process"
	if signalRuntimeTarget(current, 0) {
		t.Fatal("stale identity accepted")
	}
}

func TestRespawnWithSameNameIsNotAForceQuitTarget(t *testing.T) {
	name := fmt.Sprintf("hk-test-%d", os.Getpid())
	path := filepath.Join(t.TempDir(), name)
	raw, err := os.ReadFile("/bin/sleep")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0700); err != nil {
		t.Fatal(err)
	}
	start := func() *exec.Cmd {
		child := exec.Command(path, "30")
		if err := child.Start(); err != nil {
			t.Fatal(err)
		}
		return child
	}
	first := start()
	targets := captureRuntimeTargets([]string{name})
	if len(targets) != 1 {
		first.Process.Kill()
		first.Wait()
		t.Fatalf("targets: %v", targets)
	}
	first.Process.Kill()
	first.Wait()
	replacement := start()
	defer func() { replacement.Process.Kill(); replacement.Wait() }()
	if signalRuntimeTarget(targets[0], syscall.SIGTERM) {
		t.Fatal("exited target still accepted")
	}
	if err := replacement.Process.Signal(syscall.Signal(0)); err != nil {
		t.Fatal("replacement was stopped", err)
	}
	live := captureRuntimeTargets([]string{name})
	if len(live) != 1 || live[0].pid != replacement.Process.Pid {
		t.Fatalf("replacement: %v", live)
	}
}
