// baseos-input-state reads key state from a role-resolved Linux evdev node.
package main

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"syscall"
	"unsafe"
)

const (
	evIOCGBit = 0x20
	evIOCGKey = 0x18
	evKey     = 0x01
	maxKeyCode = 0x2ff
)

var keyCodes = map[string]uint16{
	"KEY_RESERVED": 0, "KEY_ESC": 1, "KEY_1": 2, "KEY_2": 3, "KEY_3": 4,
	"KEY_4": 5, "KEY_5": 6, "KEY_6": 7, "KEY_7": 8, "KEY_8": 9,
	"KEY_9": 10, "KEY_0": 11, "KEY_MINUS": 12, "KEY_EQUAL": 13,
	"KEY_BACKSPACE": 14, "KEY_TAB": 15, "KEY_Q": 16, "KEY_W": 17,
	"KEY_E": 18, "KEY_R": 19, "KEY_T": 20, "KEY_Y": 21, "KEY_U": 22,
	"KEY_I": 23, "KEY_O": 24, "KEY_P": 25, "KEY_LEFTBRACE": 26,
	"KEY_RIGHTBRACE": 27, "KEY_ENTER": 28, "KEY_LEFTCTRL": 29,
	"KEY_A": 30, "KEY_S": 31, "KEY_D": 32, "KEY_F": 33, "KEY_G": 34,
	"KEY_H": 35, "KEY_J": 36, "KEY_K": 37, "KEY_L": 38, "KEY_SEMICOLON": 39,
	"KEY_APOSTROPHE": 40, "KEY_GRAVE": 41, "KEY_LEFTSHIFT": 42,
	"KEY_BACKSLASH": 43, "KEY_Z": 44, "KEY_X": 45, "KEY_C": 46,
	"KEY_V": 47, "KEY_B": 48, "KEY_N": 49, "KEY_M": 50,
	"KEY_COMMA": 51, "KEY_DOT": 52, "KEY_SLASH": 53, "KEY_RIGHTSHIFT": 54,
	"KEY_KPASTERISK": 55, "KEY_LEFTALT": 56, "KEY_SPACE": 57,
	"KEY_CAPSLOCK": 58, "KEY_F1": 59, "KEY_F2": 60, "KEY_F3": 61,
	"KEY_F4": 62, "KEY_F5": 63, "KEY_F6": 64, "KEY_F7": 65,
	"KEY_F8": 66, "KEY_F9": 67, "KEY_F10": 68, "KEY_NUMLOCK": 69,
	"KEY_SCROLLLOCK": 70, "KEY_KP7": 71, "KEY_KP8": 72, "KEY_KP9": 73,
	"KEY_KPMINUS": 74, "KEY_KP4": 75, "KEY_KP5": 76, "KEY_KP6": 77,
	"KEY_KPPLUS": 78, "KEY_KP1": 79, "KEY_KP2": 80, "KEY_KP3": 81,
	"KEY_KP0": 82, "KEY_KPDOT": 83, "KEY_F11": 87, "KEY_F12": 88,
	"KEY_KPENTER": 96, "KEY_RIGHTCTRL": 97, "KEY_KPSLASH": 98,
	"KEY_RIGHTALT": 100, "KEY_HOME": 102, "KEY_UP": 103, "KEY_PAGEUP": 104,
	"KEY_LEFT": 105, "KEY_RIGHT": 106, "KEY_END": 107, "KEY_DOWN": 108,
	"KEY_PAGEDOWN": 109, "KEY_INSERT": 110, "KEY_DELETE": 111,
	"KEY_MUTE": 113, "KEY_VOLUMEDOWN": 114, "KEY_VOLUMEUP": 115,
	"KEY_POWER": 116, "KEY_PAUSE": 119, "KEY_LEFTMETA": 125,
	"KEY_RIGHTMETA": 126, "KEY_MENU": 139, "KEY_SLEEP": 142,
	"KEY_WAKEUP": 143, "KEY_SEARCH": 217, "KEY_BACK": 158,
	"BTN_A": 304, "BTN_B": 305,
	"BTN_C": 306, "BTN_X": 307, "BTN_Y": 308, "BTN_Z": 309,
	"BTN_SELECT": 314, "BTN_START": 315, "BTN_MODE": 316,
	"BTN_THUMBL": 317, "BTN_THUMBR": 318, "BTN_DPAD_UP": 544,
	"BTN_DPAD_DOWN": 545, "BTN_DPAD_LEFT": 546, "BTN_DPAD_RIGHT": 547,
}

func ioctl(fd int, request uintptr, arg unsafe.Pointer) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), request, uintptr(arg))
	if errno != 0 { return errno }
	return nil
}

func request(group byte, number, size uintptr) uintptr {
	return uintptr(3<<30) | (size << 16) | (uintptr(group) << 8) | number
}

func parseKey(text string) (uint16, error) {
	if code, ok := keyCodes[text]; ok { return code, nil }
	if strings.HasPrefix(text, "KEY_") || strings.HasPrefix(text, "BTN_") {
		return 0, fmt.Errorf("unknown Linux input key: %s", text)
	}
	if strings.HasPrefix(text, "0x") { text = text[2:]; if text == "" { return 0, errors.New("invalid numeric key code") }; n, err := strconv.ParseUint(text, 16, 16); if err != nil || n > maxKeyCode { return 0, errors.New("key code out of range") }; return uint16(n), nil }
	n, err := strconv.ParseUint(text, 10, 16)
	if err != nil || n > maxKeyCode { return 0, errors.New("key must be a Linux key name or numeric code") }
	return uint16(n), nil
}

func keyState(path, key string) (bool, error) {
	code, err := parseKey(key)
	if err != nil { return false, err }
	f, err := os.Open(path)
	if err != nil { return false, err }
	defer f.Close()
	var supported [((maxKeyCode + 1) + 7) / 8]byte
	if err := ioctl(int(f.Fd()), request('E', evIOCGBit+evKey, uintptr(len(supported))), unsafe.Pointer(&supported[0])); err != nil { return false, err }
	if supported[code/8]&(1<<(code%8)) == 0 { return false, errors.New("key is not supported by input device") }
	var pressed [((maxKeyCode + 1) + 7) / 8]byte
	if err := ioctl(int(f.Fd()), request('E', evIOCGKey, uintptr(len(pressed))), unsafe.Pointer(&pressed[0])); err != nil { return false, err }
	return pressed[code/8]&(1<<(code%8)) != 0, nil
}

func run(args []string) int {
	if len(args) != 2 { fmt.Fprintln(os.Stderr, "usage: baseos-input-state <event-node> <KEY_NAME|CODE>"); return 2 }
	pressed, err := keyState(args[0], args[1])
	if err != nil { fmt.Fprintln(os.Stderr, "baseos-input-state:", err); return 3 }
	if pressed { fmt.Println("pressed=1") } else { fmt.Println("pressed=0") }
	return 0
}

func main() { os.Exit(run(os.Args[1:])) }
