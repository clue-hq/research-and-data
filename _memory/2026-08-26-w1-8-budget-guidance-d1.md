# W1.8 — fast-loop budgets become guidance (founder ruling D1)

Spec: `subsystems/clue-design/docs/brand-ad-assets-v1-spec.md` §3 D1, §5 W1 item 8.
Base attested: `1324539a787ef30f6f5af381ae99aa02cbadd677` (worktree arrived stale at
`5ea7a8791`, fast-forwarded to the spec commit before any edit).
Commit: `cfeb978a7`.

## What changed

One hard ceiling per axis became two numbers with two jobs.

| | calls | wall | who sees it |
|---|---|---|---|
| target (guidance) | 45 | 900s | the agent — prompt + BUDGET LEFT line |
| backstop (circuit breaker) | 90 | 1800s | nobody in any prompt |

- `py_lumen_config`: added `LUMEN_AGENT_FAST_LOOP_TARGET_{LLM_CALLS,WALL_CLOCK_S}`.
  The existing `_MAX_LLM_CALLS`/`_WALL_CLOCK_S` keep their names and are repointed
  to the backstop (45→90, 600→1800). New `model_validator` refuses a backstop
  below its own target — that would hard-stop a run before it ever crossed the
  guidance, making the prompt's "nothing cuts you off" a lie.
- `budget.RunBudget`: `check_and_count` records a target crossing (sticky,
  `{kind,target,observed}`) and **admits the call anyway**. Only the backstop
  raises `BudgetExhausted`. `remaining()`/`status_line()` now measure against the
  target and gained a past-target verdict. `target_*` default to the backstop so
  single-number construction still means what it meant.
- `run_metrics`: `budget_target_exceeded` (informational, `target` key) is a
  separate field / snapshot entry / human-line phrase from `budget_exhausted`
  (abnormal, `limit` key). The human line reads `· past target (wall_clock)` vs
  `· BUDGET BACKSTOP HIT (wall_clock)`. Different key names AND different dict
  shapes, so a consumer cannot confuse them.
- `prompts._ORCHESTRATOR_BUDGETS`: rewritten as plain one-idea-per-sentence
  guidance ("Aim to finish this turn inside 15 minutes of wall clock." /
  "Nothing stops you the moment you pass a target."). `build_orchestrator_prompt`
  takes `target_*` params only — it has no backstop parameter at all, so the
  circuit breaker cannot leak into a prompt by accident.
- `.env.example`: **the actual D1-clause-1 fix.** The code default for
  `LUMEN_AGENT_REASONING` has been `"medium"` since the P3.2 gate finding, but
  `.env.example` still shipped `LUMEN_AGENT_REASONING=` (blank = unset = no
  reasoning field), so every fresh deployment got the slow configuration the
  Apollo A/B measured. Now `=medium`, with the four budget knobs documented.

The graceful-finalize path (`_finalize_on_budget_exhausted`) was not touched.

## Evidence this rests on

Apollo POC A/B, 2026-08-26 (`.context/ref-ads-pilot-apollo-report.md`): 600s hard
wall → run cut right after its first look, `reference_fidelity` 1. 900s → same
brief reacted to its own critique, fidelity 2. Medium reasoning cut author-call
latency ~170s → 55–69s.

## Verification

- `apps/agent_runtime/tests`: **914 passed, 3 skipped** (85 in `test_fast_loop.py`,
  17 of them new D1 cases).
- Flag-off byte identity: 19 `flag_off`/identity tests green, prompts unchanged.
- The load-bearing case is
  `test_a_run_past_its_target_keeps_working_then_the_backstop_finalizes_it`:
  simulated clock, real runner, 30 calls admitted across 30 simulated minutes
  (15 of them past the 900s target), then the backstop stops it and the finalize
  keeps the work — `completed_with_warnings`, gap in the ledger, both metrics
  facts on disk.
- Module-origin checked explicitly (shared-venv trap): tests import
  `lumen_agent`/`py_lumen_config` from THIS worktree, not the shared checkout.
  The shared `.venv` has `py_lumen_config` installed editable against
  `workspaces/research-and-data/colombo`, so every run here needs
  `PYTHONPATH=<worktree>/subsystems/clue-design/packages/py-lumen-config:...`
  ahead of it.

## Residuals / notes for the next agent

- `apps/api/tests::test_agent_custom_components.py::test_compile_gate_and_page_local_repin_preserve_other_document`
  fails with `compile_status: transient_error` — **pre-existing**, verified by
  stashing this branch's changes and reproducing it at the pristine base commit.
  Local TSX/esbuild toolchain, unrelated to budgets.
- `remaining()`'s dict renamed `max_llm_calls`/`wall_clock_s` →
  `target_llm_calls`/`target_wall_clock_s` and added `backstop_*` + `past_target`.
  `snapshot()` deliberately KEPT `max_llm_calls`/`wall_clock_s` (now the backstop
  values) because those are the names of the knobs that configure them.
- No engine (`crates/`) change, so no wasm rebuild/handshake was required.
- Not done, deliberately (other W1 items own them): reviewer quarantine, autofix,
  skill files.
