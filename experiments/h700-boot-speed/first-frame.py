#!/usr/bin/env python3
"""Time the first frontend frame with the libraries served in different ways.

Usage: first-frame.py run ROUNDS VARIANT[,VARIANT...]
       first-frame.py summary

The device must run the startup script from evidence/first-frame-test-rcS.patch,
with a squashfs image of the rootfs at the start of the unused slot and the
library list in /etc/lab-preload.list. That script samples the card's read
counters and a hash of the framebuffer every 50 ms into /run/lab-trace. The
first frame is the first sample whose hash differs from the boot logo's.

A variant name selects the switches by the words it contains:
  shipped       change nothing; the build under test serves /usr/lib its own way
                and only needs the sampler at the end of the patch
  squashfs      bind /usr/lib from the squashfs image
  preload       read the library list in the background from the start of rcS
  preload-idle  the same at idle I/O priority
  preload-late  the same, started at the end of rcS
  ra1024        set the card's read-ahead window to 1024 KiB
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


def run(rounds: int, variants: list[str]) -> None:
    lab.identity()
    for _ in range(rounds):
        for label in variants:
            mode = ("idle" if "preload-idle" in label else "late" if "preload-late" in label
                    else "early" if "preload" in label else "")
            ahead = "1024" if "ra1024" in label else ""
            shipped = "shipped" in label
            if not shipped:
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
            lab.require(shipped or (bound == "1") == ("squashfs" in label),
                        f"{label}: /usr/lib is not served as intended")


def boots() -> dict:
    table: dict[str, list[dict]] = {}
    for trace in sorted(RUNS.glob("sq-*.trace")):
        rows = [line.split() for line in trace.read_text().splitlines() if len(line.split()) == 6]
        record = json.loads(trace.with_suffix(".json").read_text())
        handoff = record["legacy_handoff_s"]
        first = next(row for row in rows if row[5] != rows[0][5])
        at_handoff = next(row for row in rows if float(row[0]) >= handoff)
        table.setdefault(trace.name.rsplit("-", 1)[0], []).append({
            "before_linux": record["pre_kernel_s"], "handoff": handoff, "first_frame": float(first[0]),
            "read_mib": int(first[3]) / 2048, "busy_ms": int(first[4]) - int(at_handoff[4]),
        })
    return table


def summary() -> None:
    table = boots()
    print("Seconds are kernel uptime. Reads are the whole card's, in MiB, up to the first frame.")
    print("Busy is the time the card spent on requests between the handoff and the first frame.\n")
    print(f"{'variant':24s} {'boot':>4s} {'before Linux':>12s} {'handoff':>8s} {'first frame':>11s} {'reads':>6s} {'busy ms':>8s}")
    for label, rows in table.items():
        for n, row in enumerate(rows, 1):
            print(f"{label[3:]:24s} {n:4d} {row['before_linux']:12.3f} {row['handoff']:8.2f} {row['first_frame']:11.2f}"
                  f" {row['read_mib']:6.1f} {row['busy_ms']:8d}")
    print(f"\n{'medians':24s} {'n':>4s} {'':12s} {'handoff':>8s} {'first frame':>11s} {'reads':>6s} {'busy ms':>8s}")
    for label, rows in table.items():
        middle = {key: statistics.median(row[key] for row in rows) for key in rows[0]}
        print(f"{label[3:]:24s} {len(rows):4d} {'':12s} {middle['handoff']:8.2f} {middle['first_frame']:11.2f}"
              f" {middle['read_mib']:6.1f} {middle['busy_ms']:8.0f}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(int(sys.argv[2]), sys.argv[3].split(","))
    else:
        summary()
