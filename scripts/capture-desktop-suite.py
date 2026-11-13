#!/usr/bin/env python3
import os
import signal
import subprocess
import time
from pathlib import Path

DISPLAY = ":95"
HOME = Path.home()
EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "2026-11-14-pocketshell"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = Path(os.environ.get("PJOS_ARTIFACT_DIR", str(EVIDENCE_DIR)))

def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=True, check=True, text=True, capture_output=True, **kwargs)

def send_key(win_id, key, hold=0.25):
    os.system(f"DISPLAY={DISPLAY} xdotool windowfocus {win_id} keydown {key}")
    time.sleep(hold)
    os.system(f"DISPLAY={DISPLAY} xdotool keyup {key}")
    time.sleep(0.3)

def capture(win_id, name):
    raw_path = f"/tmp/{name}.png"
    out_evidence = EVIDENCE_DIR / f"{name}.png"
    out_artifact = ARTIFACT_DIR / f"{name}.png"
    run(f"DISPLAY={DISPLAY} import -window root -crop 720x480+0+0 +repage {raw_path}")
    run(f"convert {raw_path} -filter point -resize 720x480 {out_evidence}")
    run(f"cp {out_evidence} {out_artifact}")
    print(f"Captured {name} -> {out_evidence}")

def cleanup_pid(pid):
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as e:
        print(f"Cleanup error for PID {pid}: {e}")

def main():
    # Only clean up existing process on DISPLAY :95 if one exists
    try:
        res = subprocess.run("fuser /tmp/.X11-unix/X95 2>/dev/null", shell=True, text=True, capture_output=True)
        for p in res.stdout.strip().split():
            try:
                os.kill(int(p), signal.SIGKILL)
            except:
                pass
        if os.path.exists("/tmp/.X11-unix/X95"):
            os.remove("/tmp/.X11-unix/X95")
    except Exception:
        pass
    time.sleep(0.5)
    
    # Start Xvfb :95
    xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "720x540x24", "-nolisten", "tcp"])
    time.sleep(2)

    env = os.environ.copy()
    env.pop("WAYLAND_DISPLAY", None)
    env["DISPLAY"] = DISPLAY
    env["WINIT_UNIX_BACKEND"] = "x11"
    env["POCKETSHELL_TEST_LIBRARY"] = "/tmp/pocketshell-all-apps.json"
    env["POCKETSHELL_TEST_FAVORITES"] = "/tmp/pocketshell-favorites-test.txt"
    env["POCKETJS_SDK"] = str(HOME / "development" / ".pocketjs-star-drift-sdk")
    env["POCKETJS_FONT_REGULAR"] = str(HOME / "development" / "pocketshell" / "app" / "fonts" / "FusionPixel-12px-monospaced-zh_hans.ttf")
    env["POCKETJS_FONT_BOLD"] = env["POCKETJS_FONT_REGULAR"]
    env["POCKETJS_FONT_MONO"] = env["POCKETJS_FONT_REGULAR"]

    print("Launching /tmp/pocketshell-desktop/program/run directly...")
    proc = subprocess.Popen(
        ["./run"],
        cwd="/tmp/pocketshell-desktop/program",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Wait for window
    win_id = None
    for _ in range(30):
        time.sleep(1)
        res = subprocess.run(f"DISPLAY={DISPLAY} xwininfo -root -tree", shell=True, text=True, capture_output=True)
        for line in res.stdout.splitlines():
            if "pjos" in line.lower() or "pocket" in line.lower() or "720x480" in line:
                parts = line.strip().split()
                if len(parts) >= 1 and parts[0].startswith("0x"):
                    win_id = parts[0]
                    break
        if win_id:
            break

    if not win_id:
        print("Could not find window. Tree was:")
        print(subprocess.run(f"DISPLAY={DISPLAY} xwininfo -root -tree", shell=True, text=True, capture_output=True).stdout)
        proc.kill()
        xvfb.terminate()
        return 1

    print(f"Found window ID: {win_id}")
    time.sleep(2)
    os.system(f"DISPLAY={DISPLAY} xdotool windowfocus {win_id}")
    time.sleep(1)

    # 1. Home Carousel Vector (first app: pocketfetch)
    capture(win_id, "01-home-carousel-vector")

    # 2. Right -> Terminal card
    send_key(win_id, "Right")
    time.sleep(0.5)
    capture(win_id, "08-selected-terminal-card")

    # 3. Press 'x' (A / Confirm) to open Terminal
    send_key(win_id, "x")
    time.sleep(1.0)
    capture(win_id, "09-terminal-window-open")

    # 4. Press 'x' (A / Confirm) to open Virtual Keyboard
    send_key(win_id, "x")
    time.sleep(1.2)
    capture(win_id, "10-virtual-keyboard-large-layout")

    # 5. Press 'x' to type 'date' command into input bar
    send_key(win_id, "x")
    time.sleep(1.0)
    capture(win_id, "11-virtual-keyboard-typing-test")

    # 6. Press 'x' to execute 'date'
    send_key(win_id, "x")
    time.sleep(1.2)
    capture(win_id, "12-terminal-execution-result")

    # 7. Press 'z' (B / Back) to exit terminal
    send_key(win_id, "z")
    time.sleep(0.8)

    # 8. Move Right -> Kanade
    send_key(win_id, "Right")
    time.sleep(0.5)
    capture(win_id, "02-carousel-next-card")

    # 9. Move Right -> Apotris
    send_key(win_id, "Right")
    time.sleep(0.5)

    # 10. Move Right -> Celeste
    send_key(win_id, "Right")
    time.sleep(0.5)
    capture(win_id, "03-carousel-celeste-card")

    # 11. Move Right -> Google Dino
    send_key(win_id, "Right")
    time.sleep(0.5)
    capture(win_id, "04-carousel-dino-card")

    # 12. Move Right -> Snek
    send_key(win_id, "Right")
    time.sleep(0.5)
    capture(win_id, "05-carousel-snek-card")

    # 13. Switch to Settings (press 'w' shoulder key)
    send_key(win_id, "w")
    time.sleep(0.8)
    capture(win_id, "06-settings-screen-m3")

    # 14. Switch to System (press 'w' shoulder key again)
    send_key(win_id, "w")
    time.sleep(0.8)
    capture(win_id, "07-system-screen-m3")

    # Clean up
    print("Done capturing. Cleaning up...")
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except:
        proc.kill()
    xvfb.terminate()
    return 0

if __name__ == "__main__":
    exit(main())
