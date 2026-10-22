# Inject targets of the P arm

POST /control/inject {target, value}. Implemented in harness/arm.py `_apply_one`. Tested 2026-10-22.

- `phase.<name>` value `skip` or `run`: skips one main-cognition phase via `workflows.main_cognition.steps.SKIPPED_PHASES`.
  Dummy cognition: all 11 names (triage, appraise, retrieve, codelets, structures, attention, experience, goals, decide, route, commit) return 200 and the set updates, a reply still comes ("I heard you, User."). No observable effect on dummy, it has no phases. Effect on real cognition: NOT tested.
- `private_loop` value `off` or `on`: works on dummy (200, tick stops/restarts). The off call returned in 0.7 s and the loop resumed on `on`.
- `codelet.<Name>` value `off` or `on`: dummy cognition: 500 AttributeError ('DummyMainCogLoop' has no codelet_definitions), so codelet targets need real cognition. Real cognition: `codelet.AbsurditySampler off` returned 200 {"codelets_off": ["AbsurditySampler"]}; effect on a cycle NOT tested; unknown codelet name NOT confirmed (the call hung, see notebook). Unknown names are not validated in arm.py, add a check.
- `state.<dotted.path>` value: works on dummy: `state.mental_state.state_core.valence` 0.7 returned old 0.0 new 0.7 and the field read back 0.7, then dummy overwrote it next cycle (0.0). `state.mental_state.state_emotions.joy` "0.4" coerced to float, OK. `state.tick_id` OK. Unknown path -> 500 AttributeError. Effect on real cognition (state carries over via EMA): NOT tested.
