package main

import (
	"errors"
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
