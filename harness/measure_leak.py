"""Dev measurement, no model: what one codelet-agent run (workflows/main_cognition/codelet_agent.py:104-115) retains.

    python -m harness.measure_leak <ghost.pickle> [iterations] [--no-servers] [--walk]

Per iteration: open an environment, build MemoryReadSession + FastMCP like build_codelet_agent, serve_services
(real loopback uvicorn servers), exit, del, gc. Reports process RSS and tracemalloc bytes per iteration and
whether a weakref to the environment, session and FastMCP survives. --walk names the referrers of survivors.
"""
from __future__ import annotations

import gc
import os
import sys
import tracemalloc
import weakref
from pathlib import Path

from fastmcp import FastMCP

from pm.host.mcp_listeners import serve_services
from pm.memory.agent_tools import MemoryReadSession, MemoryToolConfig, MemoryView
from pm.memory.store import MemoryStore


def rss_mb() -> float:
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("Peak", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                                           "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                           "PagefileUsage", "PeakPagefileUsage")]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(pmc)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1e6


def one_run(ghost, servers: bool):
    target = ghost.create_bash_environment("read")
    environment = target.open("leak")
    ids = frozenset(environment.visible_knoxels)
    scopes = frozenset((r["data"]["scope"]["reality_id"], r["data"]["scope"]["frame"])
                       for r in environment.visible_knoxels.values())
    memory = MemoryReadSession(MemoryToolConfig(ghost, MemoryView(ids, scopes), semantic=False, lexical=True,
                                                graph=True, embeddings=None, cancel=None))
    mind = FastMCP("codelet_mind")

    def mind_view() -> str:
        """Return the thoughts that are active in the character's mind."""
        return "x"

    mind.tool(name="mind_view")(mind_view)
    if servers:
        with memory, serve_services({"memory": memory.server(), "mind": mind}) as svc:
            assert svc
    else:
        with memory:
            memory.server()
    return {"environment": weakref.ref(environment), "memory": weakref.ref(memory), "mind": weakref.ref(mind)}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path, n = args[0], int(args[1]) if len(args) > 1 else 6
    servers = "--no-servers" not in sys.argv
    tracemalloc.start(15)
    ghost = MemoryStore.from_checkpoint(Path(path))
    ghost.checkpoint = None
    gc.collect()
    base = tracemalloc.get_traced_memory()[0]
    print(f"ghost MB {base / 1e6:.0f} rss {rss_mb():.0f} servers={servers}")
    refs = []
    last = base
    for i in range(n):
        refs.append(one_run(ghost, servers))
        gc.collect()
        now = tracemalloc.get_traced_memory()[0]
        alive = {k: r() is not None for k, r in refs[-1].items()}
        print(f"iter {i}: traced +{(now - last) / 1e6:.2f} MB total +{(now - base) / 1e6:.2f} rss {rss_mb():.0f} alive {alive}")
        last = now
    survivors = [(i, k, r()) for i, d in enumerate(refs) for k, r in d.items() if r() is not None]
    if "--walk" in sys.argv and survivors:
        i, k, obj = survivors[0]
        print(f"walk iter {i} {k} {type(obj)}")
        for ref in gc.get_referrers(obj):
            if ref is survivors or ref is refs:
                continue
            desc = repr(ref)[:200]
            print("  referrer", type(ref).__name__, desc)
            if hasattr(ref, "__code__"):
                print("    at", ref.__code__.co_filename, ref.__code__.co_firstlineno)
            for ref2 in gc.get_referrers(ref)[:4]:
                if ref2 is survivors:
                    continue
                print("    <-", type(ref2).__name__, repr(ref2)[:160])
    snap = tracemalloc.take_snapshot()
    for stat in snap.statistics("traceback")[:0]:
        pass
    print("top by lineno")
    for stat in snap.statistics("lineno")[:12]:
        print("  ", stat)


if __name__ == "__main__":
    main()
