#!/usr/bin/env python3
"""Time the first frontend frame, on any build and with test variants.

Usage: first-frame.py hook STARTUP_SCRIPT OUTPUT
       first-frame.py run ROUNDS LABEL[,LABEL...]
       first-frame.py summary

`hook` copies a device's /etc/init.d/rcS with a sampler added at its end. The
sampler records, every 50 ms for 11 s, the kernel uptime, the card read
counters and an MD5 of the first framebuffer in /run/lab-trace. The first
frame is the first sample whose hash differs from the boot logo's. Install the
copy with `lab.py deploy`, and put the original back when done.

`run` restarts the device ROUNDS times per label and keeps each trace. A label
that starts with `sq-` selects test switches by the words it contains. Those
need the startup script from evidence/first-frame-test-rcS.patch, a squashfs
image of the rootfs at the start of the unused slot and the library list in
/etc/lab-preload.list:
  squashfs      bind /usr/lib from the squashfs image
  preload       read the library list in the background from the start of rcS
  preload-idle  the same at idle I/O priority
  preload-late  the same, started at the end of rcS
  ra1024        set the card's read-ahead window to 1024 KiB
Any other label, or one with the word `shipped`, changes nothing on the device
and measures the build as it is.

lab.py's environment variables select the device.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lab  # noqa: E402

RUNS = lab.WORK / "runs"
LAST_LINE = "\n: # rcS must succeed; init proceeds to respawn frontend-session\n"
SAMPLER = r'''
# LAB: sample card reads and the screen for about 11 s.
(
	IFS=, read -r _ lab_rows < /sys/class/graphics/fb0/virtual_size
	read -r lab_stride < /sys/class/graphics/fb0/stride
	lab_frame=$((lab_stride * lab_rows / 2))
	lab_card=
	while read -r lab_device lab_dir _; do
		[ "$lab_dir" != /mnt/sdcard ] || lab_card=${lab_device#/dev/}
	done < /proc/mounts
	i=0
	while [ "$i" -lt 220 ]; do
		read -r up _ < /proc/uptime
		read -r _ _ s5 _ < /sys/class/block/mmcblk0p5/stat
		s7=0
		[ -z "$lab_card" ] || read -r _ _ s7 _ < "/sys/class/block/$lab_card/stat"
		read -r _ _ sa _ _ _ _ _ _ ta _ < /sys/block/mmcblk0/stat
		fb=$(/bin/dd if=/dev/fb0 bs="$lab_frame" count=1 2>/dev/null | /bin/md5sum)
		echo "$up $s5 $s7 $sa $ta ${fb%% *} ${lab_card:-none}"
		i=$((i + 1))
		/bin/usleep 30000
	done > /run/lab-trace
) &
'''


def hook(source: str, output: str) -> None:
    script = Path(source).read_text()
    lab.require(script.count(LAST_LINE) == 1 and "LAB:" not in script, "not a plain BaseOS rcS")
    Path(output).write_text(script.replace(LAST_LINE, SAMPLER + LAST_LINE))


def run(rounds: int, labels: list[str]) -> None:
    lab.identity()
    for _ in range(rounds):
        for label in labels:
            switched = label.startswith("sq-") and "shipped" not in label
            if switched:
                mode = ("idle" if "preload-idle" in label else "late" if "preload-late" in label
                        else "early" if "preload" in label else "")
                ahead = "1024" if "ra1024" in label else ""
                lab.sh("rm -f /etc/lab-sqfs /etc/lab-sqfs.used /etc/lab-preload-mode /etc/lab-ra;"
                       + (" touch /etc/lab-sqfs;" if "squashfs" in label else "")
                       + (f" echo {mode} > /etc/lab-preload-mode;" if mode else "")
                       + (f" echo {ahead} > /etc/lab-ra;" if ahead else "")
                       + " sync")
            lab.reboot()
            lab.collect(label)
            newest = max(RUNS.glob(f"{label}-*.json"), key=lambda p: p.stat().st_mtime)
            newest.with_suffix(".trace").write_text(lab.sh("cat /run/lab-trace") + "\n")
            bound = lab.sh("grep -c ' /usr/lib squashfs ' /proc/mounts || true")
            lab.require(not switched or (bound == "1") == ("squashfs" in label),
                        f"{label}: /usr/lib is not served as intended")


def boots() -> dict:
    table: dict[str, list[dict]] = {}
    for trace in sorted(RUNS.glob("*.trace")):
        rows = [line.split() for line in trace.read_text().splitlines() if len(line.split()) in (6, 7)]
        record = json.loads(trace.with_suffix(".json").read_text())
        handoff = record["legacy_handoff_s"]
        first = next(row for row in rows if row[5] != rows[0][5])
        at_handoff = next(row for row in rows if float(row[0]) >= handoff)
        # Older traces have no seventh column: the frontend card was mmcblk0p7.
        second_card = len(first) == 7 and not first[6].startswith("mmcblk0")
        label = trace.name.rsplit("-", 1)[0]
        table.setdefault(label[3:] if label.startswith("sq-") else label, []).append({
            "before_linux": record["pre_kernel_s"], "handoff": handoff, "first_frame": float(first[0]),
            "root_mib": int(first[1]) / 2048, "frontend_mib": int(first[2]) / 2048,
            "read_mib": (int(first[3]) + (int(first[2]) if second_card else 0)) / 2048,
            "busy_ms": int(first[4]) - int(at_handoff[4]),
        })
    return table


def summary() -> None:
    table = boots()
    print("Seconds are kernel uptime. Reads are in MiB up to the first frame: from the root")
    print("partition, from the frontend card's partition, and from both cards together.")
    print("Busy is the time the internal card spent on requests between the handoff and the first frame.\n")
    columns = f"{'handoff':>8s} {'first frame':>11s} {'root':>6s} {'frontend':>8s} {'all':>6s} {'busy ms':>8s}"
    print(f"{'build or variant':24s} {'boot':>4s} {'before Linux':>12s} {columns}")
    for label, rows in table.items():
        for n, row in enumerate(rows, 1):
            print(f"{label:24s} {n:4d} {row['before_linux']:12.3f} {row['handoff']:8.2f} {row['first_frame']:11.2f}"
                  f" {row['root_mib']:6.1f} {row['frontend_mib']:8.1f} {row['read_mib']:6.1f} {row['busy_ms']:8d}")
    print(f"\n{'medians':24s} {'n':>4s} {'before Linux':>12s} {columns}")
    for label, rows in table.items():
        middle = {key: statistics.median(row[key] for row in rows) for key in rows[0]}
        print(f"{label:24s} {len(rows):4d} {middle['before_linux']:12.3f} {middle['handoff']:8.2f} {middle['first_frame']:11.2f}"
              f" {middle['root_mib']:6.1f} {middle['frontend_mib']:8.1f} {middle['read_mib']:6.1f} {middle['busy_ms']:8.0f}")


if __name__ == "__main__":
    if sys.argv[1] == "hook":
        hook(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "run":
        run(int(sys.argv[2]), sys.argv[3].split(","))
    else:
        summary()
