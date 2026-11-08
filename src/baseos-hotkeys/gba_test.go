package main

import "testing"

func TestCmdlineIsGBA(t *testing.T) {
	gba := "/usr/bin/retroarch\x00-L\x00/usr/lib/libretro/mgba_libretro.so\x00/storage/content/games/homebrew/zelda.gba\x00"
	if !cmdlineIsGBA(gba) {
		t.Fatal("gba command line was not recognised")
	}
	for _, other := range []string{
		"/usr/bin/retroarch\x00/storage/content/games/homebrew/apotris.gb\x00",
		"/usr/bin/retroarch\x00/storage/content/games/homebrew/apotris.gbc\x00",
		"pocket-linux-kms",
	} {
		if cmdlineIsGBA(other) {
			t.Fatalf("non-gba command line matched: %q", other)
		}
	}
}
