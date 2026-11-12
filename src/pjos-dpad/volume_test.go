package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestRequestedVolumeUsesLogicalGetter(t *testing.T) {
	control := filepath.Join(t.TempDir(), "heya-control")
	for _, tc := range []struct {
		reply string
		exit  string
		want  int
		ok    bool
	}{
		{"40", "0", 40, true}, {"0", "0", 0, true}, {"100", "0", 100, true},
		{"101", "0", 0, false}, {"-1", "0", 0, false}, {"unknown", "0", 0, false}, {"40", "1", 0, false},
	} {
		script := "#!/bin/sh\n[ \"$1\" = volume-state ] || exit 2\necho '" + tc.reply + "'\nexit " + tc.exit + "\n"
		if err := os.WriteFile(control, []byte(script), 0755); err != nil {
			t.Fatal(err)
		}
		got, ok := requestedVolume(control)
		if got != tc.want || ok != tc.ok {
			t.Fatalf("reply %q exit %s: (%d,%v), want (%d,%v)", tc.reply, tc.exit, got, ok, tc.want, tc.ok)
		}
	}
}
