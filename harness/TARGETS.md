# Inject targets of the P arm

POST /control/inject {target, value}. Implemented in harness/arm.py `_apply_one`. Not yet tested.

- `phase.<name>` value `skip` or `run`: skips one main-cognition phase (triage, appraise, retrieve, codelets, structures, attention, experience, goals, decide, route, commit). Uses `workflows.main_cognition.steps.SKIPPED_PHASES`. Skipping codelets or attention may break later phases; the test shows whether.
- `private_loop` value `off` or `on`: stops or restarts the 30 s tick of the private thought loop.
- `codelet.<Name>` value `off` or `on`: writes a copy of codelets.yaml without the named codelets into the run home and points main cognition at it.
- `state.<dotted.path>` value: sets a field on the latest cycle state under the ghost lock, coerced to the old value's type.
