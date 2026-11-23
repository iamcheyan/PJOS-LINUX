package main

import "testing"

func TestParseKeyCodes(t *testing.T) {
	for name, want := range map[string]uint16{"KEY_POWER": 116, "BTN_START": 315, "0x74": 116, "97": 97} {
		got, err := parseKey(name)
		if err != nil || got != want { t.Fatalf("parseKey(%q)=(%d,%v), want %d", name, got, err, want) }
	}
	for _, name := range []string{"KEY_UNKNOWN", "-1", "768", "not-a-key"} {
		if _, err := parseKey(name); err == nil { t.Fatalf("parseKey(%q) unexpectedly succeeded", name) }
	}
}
