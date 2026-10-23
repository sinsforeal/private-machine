"""Dev measurement: bytes of one MemoryBashEnvironment (one workflow invocation) over a stored ghost.

    python -m harness.measure_env <ghost.pickle>

Loads the ghost, opens one environment, reports tracemalloc bytes held by the ghost and by the environment, and
repeats open() N times keeping the last K to see what a module's `last_environment` costs.
"""
from __future__ import annotations

import gc
import sys
import tracemalloc
from pathlib import Path

from pm.memory.store import MemoryStore


def main(path: str) -> None:
    tracemalloc.start()
    ghost = MemoryStore.from_checkpoint(Path(path))
    ghost.checkpoint = None
    gc.collect()
    base = tracemalloc.get_traced_memory()[0]
    print("ghost MB", round(base / 1e6), "knoxels", len(ghost._all_knoxels), "gwt", len(ghost.gwt_turns))
    target = ghost.create_bash_environment("read")
    env = target.open("x")
    gc.collect()
    one = tracemalloc.get_traced_memory()[0] - base
    print("one environment MB", round(one / 1e6, 2))
    envs = [target.open(str(i)) for i in range(3)]
    gc.collect()
    print("3 more MB", round((tracemalloc.get_traced_memory()[0] - base - one) / 1e6, 2))
    del envs, env
    gc.collect()
    print("after free MB", round((tracemalloc.get_traced_memory()[0] - base) / 1e6, 2))


if __name__ == "__main__":
    main(sys.argv[1])
