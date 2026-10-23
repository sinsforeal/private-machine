"""Dev measurement: load a ghost pickle and report RSS and per-part pickle sizes.

    python -m harness.measure_pickle <ghost.pickle> [more.pickle ...]

Read-only. Prints one line per file. Not part of the arm.
"""
from __future__ import annotations

import ctypes
import gc
import os
import pickle
import sys
from collections import Counter
from ctypes import wintypes


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_mb() -> float:
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1e6


def main(paths: list[str]) -> None:
    for path in paths:
        gc.collect()
        before = rss_mb()
        with open(path, "rb") as handle:
            ck = pickle.load(handle)
        gc.collect()
        after = rss_mb()
        st = ck.state
        kinds = Counter(type(k).__name__ for k in st.knoxels)
        emb = sum(1 for k in st.knoxels if k.embedding)
        sizes = {
            "knoxels": len(pickle.dumps(list(st.knoxels), 5)),
            "cycles": len(pickle.dumps(st.cycles, 5)),
            "gwt": len(pickle.dumps(ck.gwt_turns, 5)),
            "commits": len(pickle.dumps(ck.applied_commits, 5)),
            "runs": len(pickle.dumps(ck.managed_runs, 5)),
            "consol": len(pickle.dumps(ck.consolidations, 5)),
        }
        print(os.path.basename(path), "file_mb", round(os.path.getsize(path) / 1e6, 1), "load_rss_mb", round(after - before),
              "n_knoxel", len(st.knoxels), "with_emb", emb, "n_cycles", len(st.cycles), "n_gwt", len(ck.gwt_turns),
              "n_commits", len(ck.applied_commits), "bytes", sizes, dict(kinds.most_common(6)))
        del ck, st


if __name__ == "__main__":
    main(sys.argv[1:])
