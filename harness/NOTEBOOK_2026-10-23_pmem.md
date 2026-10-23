# P arm memory growth, notebook 2026-10-23 (agent, Sonnet)

Stage: root cause NOT yet confirmed. No patch made. Measurement scripts committed. Stopped at the 50-call plan.

## Findings (measured)

- Live cl2_p_tomoe server (pid 30588, Python312 venv) at 07:30: working set 9.74 GB, private 12.3 GB, 79 threads, 759 handles. Thread and handle counts are normal, so it is heap, not thread leak. cl2_p_momoka server (pid 21728) is 22 MB (idle), not comparable.
- The ghost is NOT the 9 GB. Last backup ghost_108 (tick 108, 2654 knoxels, 102 cycles, 102 gwt turns, 338 commits): file 42.8 MB, 164-178 MB in RAM after load (tracemalloc), 4.1M float objects. Pickle bytes by part: knoxels 40.6 MB (CodeletPercept 31.7 MB for 1234 records), cycles 1.6 MB, gwt 0.42 MB, commits 0.04 MB. By field: mental_state_appraisal_vec 12.9 MB, mental_state_delta_vec 12.9 MB, embedding 9.2 MB (on CodeletPercept). This is P's own store, grows about 0.4 MB pickle per tick (0.54 MB at tick 1 to 42.8 MB at tick 108), about 1.6 MB in RAM per tick. At 1280 private cycles this is far below 9 GB. If every tick kept, 3 days stays under about 1.5 GB of ghost.
- So 9 GB minus about 0.2 GB ghost is elsewhere, about 1.1 MB per gateway call (9.3 GB / 7950 calls) or about 6 MB per workflow invocation if ~1500 invocations.
- One MemoryBashEnvironment (pm/memory/bash_view.py:51, one per workflow invocation, opened in pm/runs/workflow_module.py:164) costs 3.9 MB at tick 20 (521 knoxels) and 6.3 MB at tick 102 (2654 knoxels), measured with harness/measure_env.py. After del + gc it falls back to a constant 3.2 MB residual. So an environment is freed when nothing references it.
- Each workflow module keeps `last_environment` (workflow_module.py:165) and `_pending["environment"]`, bounded to one per module, ~7 modules, so at most ~45 MB. Not the leak.

## Prime suspect (NOT confirmed)

Per codelet-agent run, workflows/main_cognition/codelet_agent.py:104-115 builds `MemoryReadSession`, a fresh `FastMCP("codelet_mind")`, starts two uvicorn/FastMCP loopback servers via pm/host/mcp_listeners.py:`serve_services`, and a pm-coder session (arm.log shows pm-coder `mcp servers: memory, mind` per codelet, e.g. AbandonmentFearAppraisal_1). Closures in these hold `environment`/ghost views (visible_knoxels payload dicts, line 98-99 builds payloads of ALL records via RecordPayloads.values() per build). If any of FastMCP, uvicorn.Server, asyncio loop, or pydantic TypeAdapter caches keep the closure alive after `serve_services` exits, each codelet run leaks an environment-sized (MBs) object graph. Other places that run the same pattern: workflows/focus_management/steps.py:60, workflows/dialogue_assistant/host.py:68 (mcp_services_factory per run in workflow_module.py:196).
Also: pm_coder sessions persist to C:\Users\zenzen\.pm\private-machine\cache\agents (disk, on C:, against the F: only rule; set PM_PROMPT_LOG_DIR and the agents log root, not done).

## Not the cause (checked)

- ghost.states: 102 CycleState objects, 1.6 MB pickled in total.
- In-memory LLM cache: PM_COMPLETION_CACHE=0 is set (harness/arm.py:23); `cache_hit=False` in log; completion cache is on disk anyway.
- Arm lists: arm.calls is cleared on each emit; arm.outputs grows by one dict per output (tiny); module_errors small.
- copy.deepcopy: none in pm/ or workflows/. Snapshot (pm/memory/snapshot.py) shares record instances.
- pm_coder, pm_bash_machine, pm_workflows: no module-level caches (grep).
- Checkpoint pickling (pm/memory/checkpoint.py:write_checkpoint, store.commit and backup() per tick): transient 40 MB bytes, no retention, but it churns 4M floats per save (possible fragmentation, unmeasured).
- Prompt log (pm/llm/prompt_log.py): writes to disk, no memory retention.

## Tried / failed

- Live dev probe (harness/memprobe.py) NOT run: the compute ticket (scail/bz_dev_pmem, 2.5 GB) timed out twice because the PC has 0.3-0.8 GB free (the leaking pid 30588 holds 9.7 GB). Dev run folder var/bzdev... created: var/bzombie/runs/bzdev_pmem_1 (cap 0.3 USD, nothing spent). A background ticket wait wrote F:\temp\pmem_ticket.txt (check it; release any granted ticket with client.py release).
- No patch applied, so PR_NOTES.md not changed.

## Remaining steps (ordered)

1. Get the ticket (or run when the cl2 runs end and RAM frees). Run `python -m harness.memprobe bzdev_pmem_1 2 --trace` from this worktree with PYTHONPATH=. and TEMP=F:\temp via wt_bz_parm\.venv python; read F:\temp\memprobe_bzdev_pmem_1.log: RSS per step, gc census growth (look for FastMCP, uvicorn Server, Environment, BashMachine, dict counts), TM lines.
2. Cheaper offline check first (no model): loop N times { env = target.open; memory = MemoryReadSession(...); mind = FastMCP; with serve_services({"memory": memory.server(), "mind": mind}) }, then del and gc.collect, weakref the environment, see if it is alive and RSS per iteration. Use ghost_21 pickle (32 MB) from var/bzombie/p_homes/cl2_p_tomoe. Run under 1 GB.
3. If confirmed: break the reference (clear the closure/registry after serve_services exit, drop `last_environment` after publish, `del` FastMCP tool registry, or call gc.collect after each run). These do not change prompts or retrieval, so they fit the fairness rule. Record in PR_NOTES.md as fairness patch 3.
4. If NOT a leak but fragmentation from checkpoint churn: bound it by not re-saving identical state (skip backup() duplicates) or set MALLOC arena policy; measure bytes per cycle before and after.
5. Report the honest peak per simulated day. Until a fix lands: ~9.7 GB at 10.7 virtual hours (cl2_p_tomoe), about 0.9 GB per virtual hour, so a 3-day run would need about 65 GB.

## Scratch

- harness/measure_pickle.py, harness/measure_fields.py, harness/measure_env.py, harness/memprobe.py (dev only, read-only on run data).
- F:\temp\pmem_ticket.txt, F:\temp\memprobe_*.log.
- Gotcha: run python with PYTHONPATH=. and cwd = this worktree, venv at tmp\wt_bz_parm\.venv\Scripts\python.exe. The ghost backups in var\bzombie\p_homes\cl2_p_tomoe are live files: read only the ghost_N_* ones.
