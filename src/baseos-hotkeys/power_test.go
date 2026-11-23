package main

import (
	"errors"
    "os"
    "io"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestPowerGestures(t *testing.T) {
	start := time.Now()
	for _, policy := range []string{"ignore", "poweroff"} {
		var key powerKey
		step := func(value int32, at time.Duration, want string) {
			t.Helper()
			if got := key.step(value, start.Add(at), policy); got != want {
				t.Fatalf("%s value=%d at=%s: got %q want %q", policy, value, at, got, want)
			}
		}
		step(0, 0, "")
		step(1, 0, "")
		step(2, time.Second, "")
		step(1, time.Second, "")
		step(-1, longPress, policy) // deadline, without waiting for release
		step(-1, longPress, "")
		step(0, longPress, "")
		step(1, longPress, "")
		step(0, 2*longPress, policy) // release and deadline simultaneously ready
		step(1, 2*longPress, "")
		step(0, 3*longPress-time.Nanosecond, "toggle")
	}
}

func TestHotkeyBindingsFollowBoardMap(t *testing.T) {
    for _, tc := range []struct{ mapping string; selectKey, startKey, l2, r2 uint16 }{
        {"schema=pjos.input/1\nSELECT key 310\nSTART key 28 311 312\nZL key 314\nZR key 315\n", 310, 311, 314, 315},
        {"schema=pjos.input/1\nSELECT key 314\nSTART key 28 315 316\nZL key 312\nZR key 313\n", 314, 315, 312, 313},
    } {
        binding, err := parseHotkeyBindings(tc.mapping)
        if err != nil { t.Fatal(err) }
        if binding.selectKey != tc.selectKey || binding.startKey != tc.startKey || binding.l2 != tc.l2 || binding.r2 != tc.r2 {
            t.Fatalf("wrong profile binding: %+v", binding)
        }
    }
    for _, bad := range []string{"", "schema=pjos.input/2\n", "schema=pjos.input/1\nSELECT key 310\n", "schema=pjos.input/1\nSELECT key nope\n"} {
        if _, err := parseHotkeyBindings(bad); err == nil { t.Fatalf("accepted incomplete mapping %q", bad) }
    }
}

func TestInputDisconnectPropagates(t *testing.T) {
    read, write, err := os.Pipe()
    if err != nil { t.Fatal(err) }
    defer read.Close()
    write.Close()
    err = readLoop(read, func(inputEvent) { t.Fatal("unexpected input") })
    if !errors.Is(err, io.EOF) { t.Fatalf("lost EOF: %v", err) }
    failures := make(chan error, 1)
    sentinel := errors.New("pad disconnected")
    failures <- sentinel
    if err := watchPower(make(chan inputEvent), failures); err != sentinel { t.Fatalf("lost pad failure: %v", err) }
}

func TestLifetimeLock(t *testing.T) {
	path := filepath.Join(t.TempDir(), "owner")
	owner, err := lockOwner(path)
	if err != nil { t.Fatal(err) }
	if _, err := lockOwner(path); !errors.Is(err, syscall.EWOULDBLOCK) { t.Fatalf("second lock: %v", err) }
	owner.Close()
	next, err := lockOwner(path)
	if err != nil { t.Fatal(err) }
	next.Close()
}
