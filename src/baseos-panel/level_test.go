package main

import "testing"

func TestStepped(t *testing.T) {
	cases := []struct{ current, delta, want int }{
		{120, -stepDelta, 105},
		{120, stepDelta, 135},
		{12, -stepDelta, stepFloor},
		{stepFloor, -stepDelta, stepFloor},
		{5, -stepDelta, 5},
		{5, stepDelta, 20},
		{250, stepDelta, dispLevelMax},
		{dispLevelMax, stepDelta, dispLevelMax},
		{100, 0, 100},
	}
	for _, tc := range cases {
		if got := stepped(tc.current, tc.delta); got != tc.want {
			t.Errorf("stepped(%d, %d) = %d, want %d", tc.current, tc.delta, got, tc.want)
		}
	}
}
