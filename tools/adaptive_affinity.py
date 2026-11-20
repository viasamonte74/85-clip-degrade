#!/usr/bin/env python3
"""Shared-machine helper: let the degradation loop use spare CPU capacity without taking it from other jobs.

The container has one CFS quota for every job on the box (here 23 CPUs; nice does not protect other jobs under
it, and bursty jobs hit the quota well before the average reaches it: measured 8-10 % of periods throttled at
an average of ~21-22 of 23). This watchdog samples the container's cpu.stat every --interval seconds and moves
the process tree of --pid (the degradation loop and every child) between CPU sets, one CPU at a time:

  level 0   --narrow (default 2,3), the agreed share
  level k   adds the first k CPUs of --extra (default 26,27: idle hyper-thread siblings of 2 and 3)

Step up one level only after --calm consecutive windows with no throttled period, the quota leaving room for one
more CPU plus --headroom, and any back-off hold expired. Drop to level 0 as soon as more than --max-throttle of
a window's periods were throttled, then hold for --hold seconds before trying again (doubling after every drop
within 30 min of the previous one, up to --max-hold). Every change is logged. Exits when --pid is gone.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

CG = Path("/sys/fs/cgroup/cpuacct")


def parse_cpus(s: str) -> set[int]:
    out: set[int] = set()
    for part in s.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def sample() -> tuple[int, int, int]:
    st = dict(line.split() for line in (CG / "cpu.stat").read_text().splitlines())
    return int((CG / "cpuacct.usage").read_text()), int(st["nr_periods"]), int(st["nr_throttled"])


def quota_cpus() -> float:
    q = int((CG / "cpu.cfs_quota_us").read_text())
    p = int((CG / "cpu.cfs_period_us").read_text())
    return q / p if q > 0 else float(os.cpu_count() or 1)


def tree(root: int) -> list[int]:
    kids: dict[int, list[int]] = {}
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                ppid = int((d / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            kids.setdefault(ppid, []).append(int(d.name))
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def apply(root: int, cpus: set[int]) -> int:
    n = 0
    for pid in tree(root):
        try:
            for tid in os.listdir(f"/proc/{pid}/task"):
                os.sched_setaffinity(int(tid), cpus)
            n += 1
        except OSError:
            pass
    return n


def stamp() -> str:
    return time.strftime("%FT%TZ", time.gmtime())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True, help="root of the process tree to manage (the degradation loop)")
    ap.add_argument("--narrow", default="2,3")
    ap.add_argument("--extra", default="26,27", help="CPUs added one at a time, in this order")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--headroom", type=float, default=2.0, help="CPUs of quota that must stay unused after a step up")
    ap.add_argument("--max-throttle", type=float, default=0.02)
    ap.add_argument("--calm", type=int, default=4)
    ap.add_argument("--hold", type=float, default=600)
    ap.add_argument("--max-hold", type=float, default=3600)
    a = ap.parse_args()
    narrow, extra, quota = parse_cpus(a.narrow), [int(x) for x in a.extra.split(",") if x], quota_cpus()
    levels = [narrow | set(extra[:k]) for k in range(len(extra) + 1)]
    lvl, calm, hold, hold_until, last_drop = 0, 0, a.hold, 0.0, 0.0
    print(f"{stamp()} managing pid {a.pid}: levels {[sorted(x) for x in levels]} quota {quota:.2f}", flush=True)
    apply(a.pid, levels[0])
    prev = sample()
    while os.path.exists(f"/proc/{a.pid}"):
        time.sleep(a.interval)
        cur = sample()
        used = (cur[0] - prev[0]) / 1e9 / a.interval
        thr = (cur[2] - prev[2]) / max(1, cur[1] - prev[1])
        prev = cur
        t = time.time()
        if thr > a.max_throttle:
            calm = 0
            if lvl > 0:
                hold = min(hold * 2, a.max_hold) if t - last_drop < 1800 else a.hold
                lvl, hold_until, last_drop = 0, t + hold, t
                n = apply(a.pid, levels[0])
                print(f"{stamp()} level 0: throttled {thr:.0%}, used {used:.2f}/{quota:.2f}; hold {hold / 60:.0f} min ({n} procs)",
                      flush=True)
            continue
        calm = calm + 1 if (thr == 0 and used + 1 + a.headroom <= quota) else 0
        if lvl < len(levels) - 1 and calm >= a.calm and t >= hold_until:
            lvl, calm = lvl + 1, 0
            n = apply(a.pid, levels[lvl])
            print(f"{stamp()} level {lvl} {sorted(levels[lvl])}: throttled {thr:.0%}, used {used:.2f}/{quota:.2f} ({n} procs)",
                  flush=True)
        elif lvl > 0:
            apply(a.pid, levels[lvl])  # children started since the last window inherit the set; re-apply for safety
    print(f"{stamp()} pid {a.pid} gone, exiting", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
