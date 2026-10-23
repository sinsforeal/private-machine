"""Dev measurement: pickled bytes per knoxel field and per knoxel type, from one ghost pickle (read-only)."""
from __future__ import annotations

import pickle
import sys
import tracemalloc
from collections import defaultdict


def main(path: str) -> None:
    tracemalloc.start()
    with open(path, "rb") as handle:
        ck = pickle.load(handle)
    cur, peak = tracemalloc.get_traced_memory()
    print("tracemalloc after load MB", round(cur / 1e6), "peak", round(peak / 1e6))
    st = ck.state
    by_type = defaultdict(lambda: [0, 0])
    by_field = defaultdict(int)
    for k in st.knoxels:
        total = len(pickle.dumps(k, 5))
        by_type[type(k).__name__][0] += 1
        by_type[type(k).__name__][1] += total
        for name in type(k).model_fields:
            by_field[name] += len(pickle.dumps(getattr(k, name), 5))
    print("by type (n, MB)", {t: (n, round(b / 1e6, 2)) for t, (n, b) in sorted(by_type.items(), key=lambda x: -x[1][1])[:8]})
    print("by field MB", {f: round(b / 1e6, 2) for f, b in sorted(by_field.items(), key=lambda x: -x[1])[:8]})
    snap = tracemalloc.take_snapshot()
    for stat in snap.statistics("lineno")[:8]:
        print(stat)


if __name__ == "__main__":
    main(sys.argv[1])
