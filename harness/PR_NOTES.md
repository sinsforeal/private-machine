# PR notes (bz/parm-patch), for tk-q5k

## fairness patches

Patches that change what the P arm delivers because the original code mis-parsed the model output, not because of his method. Each is labelled in the code.

1. workflows/dialogue_story/steps.py `clean_reply` (2026-10-22). Old: cut at the first other-speaker marker, then kept only the text after the LAST own marker. On run bz_p_e2e_live_7530 call 502 the completion held four Momoka lines before an invented "User says:", and the reply delivered the 4th ("……ねえ、聞こえてる？ 一悟。") while the 1st ("おかえり、一悟。...") answered him. New: cut at the first other marker (unchanged), then keep every own-marker segment in order, joined with newlines (one multi-bubble reply), markers and quotes stripped. Text before the first own marker is bubble 1 when a prefill was sent (it continues the open quote), a dropped preamble otherwise. Test: tests/unit/test_dialogue_fairness.py (call 502 text, call 269 single turn, preamble, echoed prefill, other speaker first).
2. harness/arm.py `build_app(record_lifecycle=False)` (2026-10-22 20:20). With True, `workflows/companion.py:626` `record_startup` (`pm/app/lifecycle_records.py:113`) stores "I started again. I have no record of a clean shutdown, so the previous ending is uncertain." on every harness boot. A bench run is a first meeting, so the event asserts a past that never happened: on bz_p_tomoe_d1a (review call c57a5c3b) Tomoe's first reply invented a fight ("like nothing happened? i had a whole thing ready") and a goal about "last night"; the sentence sat in 124 Momoka calls too. The S arm has no such event. Upstream note: on a first boot (empty store) the startup record could say so instead of implying an unclean shutdown.

## upstream notes

- `uv sync --locked` fails: uv.lock records pm-coder from tool.uv.sources (?rev=main), pyproject has a direct `@main` URL. Fix one of them.
