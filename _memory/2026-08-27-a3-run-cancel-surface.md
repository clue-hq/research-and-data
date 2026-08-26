# Wave A / A3 — a cancel surface for an in-flight design agent run (defect R3-D)

Date: 2026-08-27. Base attested: `46bc872f5` (worktree was stale at `5ea7a8791`; reset, no stash —
AGENTS.md §4). Commits: `8d800a60c` (the surface), `89646146c` (website-mode extension).

## The defect

`.context/w5-apollo-e2e-report.md` §R3.7, R3-D: "no cancel surface for an in-flight agent turn".
A doomed manual-reference run had to be watched to completion because nothing could stop it.

## What was built

**Durable flag.** `design_agent_run.cancel_requested_at timestamptz NULL`, migration
`518a3784f3a4` (up→down→up proven; single head). Write-once, never cleared. It is a ROW because
the asker (web process) and the driver (fleet worker, detached or embedded) share nothing but
Postgres — and a lease takeover redrives the same frozen envelope, so an in-memory flag would
silently un-cancel the run.

**DAL** (`subsystems/design/clue_design/runs.py`): `request_run_cancellation` (idempotent,
write-once, three outcomes `requested` / `already_requested` / `already_terminal`,
`DesignNotFoundError` fail-closed) and `cancellation_requested` (the worker's boolean probe).
Neither touches `status`.

**Route**: `POST /agent/runs/{run_id}/cancel` (`lumen_api/main.py`, beside the run snapshot).
All three outcomes are HTTP 200 with an honest body; 404 on unknown/cross-tenant. Uses
`Depends(repository)` so the O4 route-table guard covers it automatically (no ALLOWLIST entry).
**Deliberately NOT a governed toolbelt tool** — the D6 tool layer governs design-domain mutations
an AGENT may make; cancel is human control-plane, like `mint_run_stream_token` (also durable, also
not a tool). Making it a tool would also have meant granting a role the power to cancel runs.

**Boundary** (`lumen_agent/cancellation.py`, new): the budget backstop's twin. The drive loop is a
LangGraph graph entered once, so the langchain `raise_error` callback seam before each model call
is the only place a running graph can be refused. `CancellationProbe` is sticky, throttled on the
negative answer (1s), and FAIL-OPEN (a DB blip reads as "not cancelled"). Attached to all three
roles; plus one check before the graph is entered at all, so a run cancelled while queued pays for
zero calls.

**Finalize REUSED, not reimplemented.** `_finalize_on_budget_exhausted`'s body extracted to
`harness._finalize_interrupted_run`; both interrupts now differ only in wording. Cancelled scene
run → `completed_with_warnings` when a draft stands (P0.4 checkpointed rounds kept) / `failed` when
nothing was authored, gap recorded, `stop_reason = "cancelled_by_request"`. Run event
`run_cancelled` fires the moment the cancel is honoured (via `tools.record`, which is both trace
and SSE push), ahead of the terminal `done` frame.

**Website mode** (2nd commit): same wiring, but web has no P0.4 checkpointing, so a cancelled web
turn takes the harness's PRE-EXISTING honest-failure finalize — `failed`, empty operations ledger,
nothing applied — with a truthful reason. No `completed_with_warnings` branch, deliberately.

## Decisions taken

1. **Status vocabulary REUSED; `DesignRunStatus` NOT widened.** The enum (queued/running/
   succeeded/failed) genuinely has a suitable terminal value under the shipped convention: the
   budget backstop already lands a deliberate non-failure stop as `succeeded` with the honest WHY
   in `result_json.stop_reason`. Widening would also have needed a 4th `RunEventTopic` in
   `clue_core` (the design topic allow-list is exactly three and is enforced), a PG enum rebuild,
   parity-test reordering, and updates to three independent `TERMINAL_RUN_STATUSES` restatements —
   platform-level blast radius, and a status label the editor does not know (D4: no frontend work).
   A cancelled run is identifiable at rest by `cancel_requested_at` + `stop_reason`.
2. `_instrument`'s new `cancel_probe` is KEYWORD-ONLY and omitted when absent — a 6th positional
   arg broke two shipped monkeypatch spies (`test_fast_loop.py`). Pinned by a test.
3. `GET /agent/runs/{run_id}` was NOT widened with `cancel_requested_at` (shipped response shape;
   the D5 columns were deliberately kept out of it too).

## Residuals / open questions for the founder

- **No `cancel_requested_at` on the run snapshot.** A UI that wants to show "cancelling…" between
  the ask and the terminal frame has nothing to read. Trivial to add when Part IV's editor UI wants
  it; left out because D4 stands (no frontend work) and the DTO is a shipped shape.
- **Latency is one model call**, bounded by `agent_llm_timeout_s` (up to ~the per-call timeout).
  Stated at the route docstring. A hard kill would need the lease, not this route.
- **Web mode has no `stop_reason` field at all** (`finalize_web_run` takes only status+summary), so
  the cancelled truth lives in the summary sentence there. Pre-existing asymmetry, left alone.
- **A cancel that lands after the orchestrator wrote `final.json` is too late** and does not rewrite
  the result. Intentional; pinned by a test.

## Verification

- New: `apps/agent_runtime/tests/test_cancellation.py` (19), `apps/api/tests/test_agent_run_cancel.py`
  (10) — all green.
- **Red case proven at base `46bc872f5`**: zero occurrences of `runs/{run_id}/cancel` in `main.py`,
  zero `TurnCancelled` in `harness.py`, zero `cancel` in the runs DAL, and `cancellation.py` absent.
  Plus an EXECUTED red case in the suite (`test_the_defect_itself_a_run_with_no_cancel_path_cannot_
  be_stopped`) showing the same doomed-run agent running to its guard when no probe exists.
- Full `apps/agent_runtime/tests`: 11 failures, ALL pre-existing — proven by running the same files
  against a clean `git archive` export of `46bc872f5` at `/tmp/a3-base` (identical failure set;
  `test_web_retokenize` needs an installed tailwind theme, `test_web_substrate` needs the engine).
- Full `apps/api/tests`: 57 failures, ALL pre-existing — the exact failing node-id list was replayed
  against the same base export: 55 reproduced in that batch, and the remaining 2
  (`test_the_web_turn_persist_honours_the_envelopes_base_version`,
  `test_a_refused_brief_still_publishes_the_kit`) reproduced on base when re-run in isolation a few
  minutes later. **Those two are FLAKY under sibling load, and the mechanism is worth knowing: the
  design fleet queue lives in the shared DB, so an embedded worker in ANOTHER agent's process can
  lease this suite's `design_job` and execute it there — where `app.state.web_turn_runner` was never
  set, so the real runtime runs and the turn fails instead of returning the stubbed `conflicted`.**
  Any design-fleet test run against a shared database is exposed to this; use a per-branch DB
  (`CLUE_DATABASE_URL=…/clue_<branch>`), as one sibling worktree already does.
- `tests/design`: 1 failure (`test_the_floor_is_enforced_on_rows_not_only_in_arithmetic`), identical
  on the base tree — shared-DB event pollution from sibling agents.
- Seam/governance: `test_workspace_seam_route_table.py`, `test_workspace_seam.py`,
  `test_write_path_governance.py` all green (the tool-name set is unchanged — no new tool).

## Environment gotchas for the next agent

- **Shared-venv trap is REAL here.** The colombo venv's editable `.pth` files point at the MAIN
  workspace, so `clue_design` / `clue_core` / `clue_toolbelt` resolve THERE unless this worktree's
  package roots come first on `PYTHONPATH`. `lumen_api` / `lumen_agent` resolved correctly by
  accident (different mechanism). Verify with an explicit `__file__` print before trusting any run.
- **The dev DB is shared across worktrees.** Applying this branch's migration stamps the shared DB
  at a revision sibling worktrees do not have, which makes their `tests/design` session fixture
  (`command.upgrade(cfg, "head")`) raise a revision `KeyError`. Ran `alembic downgrade 50ce19bf5ef7`
  at the end of this session for that reason, so **the DB no longer has `cancel_requested_at` —
  run `alembic upgrade head` from this branch before exercising the cancel tests.**
- **The shared DB also shares the fleet queue** (see the two flaky tests above). Prefer a
  per-branch `CLUE_DATABASE_URL` for anything that drives a design run.
- `apps/api/tests` does NOT migrate; `tests/design` does (session fixture). That asymmetry is why
  the cancel API tests need a hand-run `alembic upgrade head` first.
