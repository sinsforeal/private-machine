"""Dev memory probe for the P arm (not part of a bench run).

    python -m harness.memprobe <run_id> <virtual_hours> [--trace]

Starts an Arm in this process on an existing run folder (create it with
`bzombie.harness new`; run ids bzdev_pmem_*), advances virtual time in 10 minute steps and writes one line
per step to F:\\temp\\memprobe_<run_id>.log: RSS, gc object count, ghost size, top growing object types.
Stops itself above 2.5 GB.
"""
from __future__ import annotations

import gc
import sys
import time
import tracemalloc
from collections import Counter
from datetime import timedelta

from harness.arm import Arm
from harness.measure_pickle import rss_mb

LIMIT_MB = 2500
STEP = timedelta(minutes=10)


def census() -> Counter:
    return Counter(type(o).__name__ for o in gc.get_objects())


def main() -> None:
    run_id, hours = sys.argv[1], float(sys.argv[2])
    trace = "--trace" in sys.argv
    out = open(rf"F:\temp\memprobe_{run_id}.log", "a", encoding="utf-8", buffering=1)
    if trace:
        tracemalloc.start(8)
    arm = Arm()
    start = "2026-10-26T07:00:00+09:00"
    arm.start(run_id, "tomoe", "en", start)
    base = census()
    prev = base
    snap0 = tracemalloc.take_snapshot() if trace else None
    t0 = time.time()
    end = arm.clock.now() + timedelta(hours=hours)
    step = 0
    while arm.clock.now() < end:
        target = arm.clock.now() + STEP
        arm.advance(target.isoformat() + "+09:00")
        step += 1
        gc.collect()
        now = census()
        growth = {k: now[k] - prev[k] for k in now if now[k] - prev[k] > 2000}
        prev = now
        ghost = arm.app.ghost
        out.write(f"step {step} virt {arm.clock.now().time()} wall {time.time() - t0:.0f}s rss_mb {rss_mb():.0f} "
                  f"objs {sum(now.values())} states {len(ghost.states)} knoxels {len(ghost._all_knoxels)} "
                  f"gwt {len(ghost.gwt_turns)} commits {len(ghost.applied_commits)} grew {growth}\n")
        if rss_mb() > LIMIT_MB:
            out.write("STOP rss limit\n")
            break
    if trace:
        snap1 = tracemalloc.take_snapshot()
        for stat in snap1.compare_to(snap0, "lineno")[:25]:
            out.write(f"TM {stat}\n")
    arm.stop()
    out.write("done\n")


if __name__ == "__main__":
    main()
