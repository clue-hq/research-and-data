# Part II D5 Round B — design turns onto the fleet (handler, checkpointer, API switch)

Branch `platform/design-integration`, on top of `c24eeae0` (D4) **plus the uncommitted D5 Round A
tree** (`_memory/2026-08-09-part2-d5a-durable-foundation.md`). Uncommitted at the time of writing
— the reviewer commits. Round C owns ingestion-onto-fleet, the D2.5A workspace-threading debts,
and the O5-bridge death.

## What landed

### R-D5-B1 — the two design-tree shims become real workspace members
`py_lumen_obs` / `py_lumen_config` **moved** into their own distribution directories
(`subsystems/clue-design/packages/py-lumen-{obs,config}/`) and are explicit-path uv workspace
members, declared as dependencies of `lumen-api` and `lumen-agent-runtime`. Content byte-identical
apart from `py_lumen_config.config._REPO_ROOT` (`parents[1]` → `parents[3]`, which anchors `.env`
and the engine-cache default — silent breakage if missed).

The move was forced: hatchling refuses a `packages`/`only-include` path escaping the project root,
and the `force-include ../../pkg` workaround produces an "editable" wheel that **copies** the
sources (a stale snapshot of a live tree — worse than the shim). Both were verified empirically
before choosing.

`lumen_api.main.ensure_agent_runtime_path` is DELETED. The lazy `lumen_agent` import +
`agent_runtime.unavailable` degradation contract is untouched.

### R-D5-B2/B3 — the handler
`subsystems/clue-design/apps/api/lumen_api/fleet_handler.py` (new): `DesignJobWorkHandler`
(`kind = FleetTaskKind.DESIGN_JOB`), the `DesignTurnHost` process-capability record,
`postgres_design_checkpointer`, and `build_design_job_handler` — the ONE factory both deployments
compose. `platform/api/clue_api/design_fleet.py` (new) is a thin lazy-import registration wrapper
for `fleet_main`; `build_multi_work_worker` gained `design_handler=` (kind-checked) and
`fleet_main` passes it behind the new `settings.design_runtime_enabled` (default `False`).

Handler flow: parse envelope → `claim_run_for_execution` (off-loop) → `asyncio.to_thread(turn)`
raced against `lease_lost`/`stop_requested` → `complete_run(expected_generation=…)`. On a fencing
event it returns `requeue=True` **without awaiting the thread** (documented zombie residual). A
refused claim / unknown work id / ingestion envelope → `task_finalized=True`, never a requeue loop.

### R-D5-B3 — the generation fence
`clue_design.runs.set_run_result` / `complete_run` / `append_run_event` take
`expected_generation`; the predicate refuses when the row's `lease_generation` is HIGHER, raising
the new `DesignRunFencedError`. `complete_run` writes the result first, so a fenced zombie appends
no event either — the stream can never read terminal-then-more-events.

### R-D5-B4 — checkpointer + **resume-as-restart** (honest finding)
`run_deepagent_turn` / `run_deepagent_web_turn` (and their factories) accept `checkpointer=` /
`thread_id=`; the thread id is the DESIGN RUN ID. New `lumen_agent/checkpoint.py` owns the resume
decision.

**True mid-turn resume is impossible today and was NOT faked.** `LumenDesignTools` /
`LumenWebTools` mint a fresh `run_id` in `__init__` and derive `trace_dir` from it; the scene, the
operations ledger, the round dirs, and `final.json` (the harness's sole outcome authority) all
live there and in tool-object memory. None of it is in the checkpoint. A resumed graph would hand
a message history describing a dead workspace to an empty tool substrate. A *completed* snapshot
cannot be short-circuited either — its outcome is in the dead attempt's `final.json`. So a thread
that already carries state is **deleted and re-invoked from the top** from the same frozen
envelope, logged `turn.checkpoint_restart`. Prior `design_run_event` rows are preserved.

### R-D5-B5 — the API switch
- `POST /agent/turns` / `POST /documents/{id}/web/turns`: all pre-run-row validation unchanged
  (references still resolved before the row exists, account card still 404s first); then ONE
  transaction creates the run and offers its `design_job`
  (`HybridRepository.create_run_and_offer`, the `launch_entity_research_run` precedent). The
  envelope is stored twice from one object (`design_agent_run.payload` + `fleet_task.payload_json`)
  so they cannot disagree. Response status now honestly reads `"queued"`; the editor's
  `agentRunner.ts` reads only `run_id`.
- DELETED: both `threading.Thread` spawns and their worker closures (promoted to
  `execute_agent_turn_job` / `execute_web_turn_job` in `main.py`, driven from the envelope),
  `_fail_orphaned_runs` + `list_orphaned_runs_across_workspaces`, the Round-A
  `create_run` claim half + `_INPROCESS_WORKER_ID`. `import threading` / `import sys` are gone
  from `main.py`.
- **Embedded worker**: lifespan task, `LUMEN_EMBEDDED_FLEET_WORKER` (default `true`), design
  handler only, host built from live `app.state` per turn. It needs the process-global engine, so
  the lifespan conditionally enters `db_lifespan()` (the design store still owns private engines —
  the O5 rule is untouched).
- Conftest: `make_client` now `__enter__`s the TestClient (Starlette runs lifespan only inside the
  context manager) with an autouse teardown fixture. One helper adapted, no per-test churn.

## Decisions / deviations

1. **The handler class lives in `lumen_api`, not `clue_api`.** Executing a turn needs
   `lumen_agent` + `main.py`'s by-value resolvers; `lumen_api -> clue_api` is forbidden (Rule 5).
   New edges: `lumen_api -> clue_fleet` and `clue_api -> lumen_api`, both invisible to
   import-linter (`root_packages` excludes `lumen_api`). **No contract was edited** — 25/25 kept.
2. **`clue_fleet` is imported LAZILY inside `create_run_and_offer`.** A module-level import
   regressed the standing `test_import_pulls_no_pil_or_httpx` guard: `import clue_fleet` reaches
   `clue_research.durable` → langgraph → langsmith → httpx, and `design_store` is on
   `lumen_ingestion.describe`'s import path. Caught by the full suite, fixed at the source.
3. **mypy override added** for `lumen_api.*` (`follow_imports = "skip"`, `ignore_missing_imports`)
   — the design tree carries no `py.typed` and is outside the root mypy `files`. The handler is
   duck-typed at the seam and its `kind` is re-checked at construction.
4. **`_KilledWorkerLeases` in the gate test.** Cancelling a worker task is not a faithful death:
   `_run_task`'s `finally` still releases the lease, the row is deleted, and the next acquire
   restarts at generation 1 — no takeover is observable. A killed process never releases, so the
   test suppresses only `release`.
5. `test_startup_sweep_fails_runs_orphaned_by_a_restart` REPLACED by
   `test_a_restart_leaves_an_unclaimed_run_recoverable` — the inverse contract. A boot sweep would
   now destroy recoverable work.

## Gates

- `uv run python -c "import lumen_agent.harness"` from the repo root, **no PYTHONPATH**: green.
- `make db-smoke` on a fresh DB (up → base → head): green. `alembic heads` = `50b84c524fa2` alone.
  No new migration was needed (`fleet_task` has no FK on `project_run_id`).
- `tests/design/ tests/fleet/` fresh DB: **163 passed** (Round A: 160; +3 = the D5 gate file).
- Full design-API suite (`apps/api/tests`, canonical invocation, fresh DB): **501 passed / 9
  skipped / 0 failed** (510 collected). Two runs used: run 1 caught the httpx-guard regression
  (decision 2 above), run 2 is the clean one. NB the suite prints no count line under `-q`; the
  numbers are the collected total minus the `s` marks, with `EXIT=0`.
- Agent-runtime suite: **551 passed / 2 skipped**, byte-identical with and WITHOUT the documented
  PYTHONPATH (Round A: 546/2; +5 = the new checkpoint test).
- Offline platform suite: **2197 passed / 1522 skipped** (baseline 2195; +2 = the new
  fleet-wiring tests — the 3 DB-backed gate tests correctly skip offline).
- `uv run mypy` 590 files clean · `ruff check` clean · `lint-imports` 25/25 · `ruff format --check`
  = the known **23** pre-existing files, zero overlap with D5 files.

## Tests added

- `tests/design/test_design_fleet_turns_db.py` — the D5 gate: kill-and-resume with a real queue and
  real leases, the fence in isolation at the DAL, and two-workspace concurrency.
- `subsystems/clue-design/apps/agent_runtime/tests/test_checkpoint_resume.py` — pins
  resume-as-restart (a stale thread is CLEARED and re-invoked with full initial state, never
  continued with input `None`) and the harness signatures the handler calls by name.
- `tests/api/test_fleet_wiring.py` — the design handler joins the ONE drain, kind-checked at
  construction; and `design_fleet.build_design_job_handler(enabled=False) is None`.
- Adapted: `test_api.py` (`queued` status + a terminal-aware poller + the restart test inversion),
  `test_web_turns.py` (`queued` status), `tests/conftest.py` (lifespan-entered client).

## Pre-existing defects found (reported, NOT fixed)

- **`apps/editor/src/engine/webDocuments.ts::fetchWebRunSnapshot` will THROW on `"queued"`.** It
  validates `status` against exactly `running|succeeded|failed` and raises "Run lookup returned an
  unreadable status" otherwise. It is only reached on the SSE-error recovery path in
  `useWebAgentTurn` (the happy path is POST-then-SSE, which is unchanged and green), so a stream
  blip while a turn is still queued would surface a hard error instead of reconnecting. NOT fixed
  here: `apps/editor/` is out of this round's scope. One-line widening; must land before the
  editor meets a real queue.
- The two `test_web_substrate.py` failures seen in one run were a cargo rebuild race on
  `target/debug/lumen-api-helper` (the background API suite rebuilding it concurrently), not a
  regression — green standalone and on a clean re-run.

## Residuals for Round C

- **Zombie threads.** A fenced-out worker's synchronous turn body runs to completion (Python
  cannot interrupt a thread). Its writes are refused, but it burns CPU and an LLM budget. The
  platform hard-fence-token work remains the `[B1×integration]` residual.
- **Resume-as-restart, not resume.** Making `LumenDesignTools` reconstructible from a run id is
  what would flip `checkpoint.py`'s restart branch into a real resume branch.
- **Ingestion is not on the fleet.** The handler parks a `DesignIngestionEnvelope` finalized with
  a loud log; nothing enqueues one yet.
- **Cross-test queue bleed.** The design suite shares one `fleet_task` table, so a test's embedded
  worker may drain a previous test's leftover run (executing it with the current test's stub). It
  is harmless — nobody reads those runs — but it is noise in the logs and worth a per-suite queue
  or a workspace-scoped claim if it ever bites.
- **A design task that FAILS (not a failed turn — a store fault raising out of the handler) leaves
  its run `running` with no terminal row.** The fleet marks the task `failed` and nothing re-offers
  it; the old daemon path had the startup sweep for this shape. Needs a re-offer or a reaper.
- **The design tree is still outside the root lint/mypy/import-linter graph.** Part-I Step-2 owns
  that, and with it the fold of `py_lumen_obs`/`py_lumen_config` into `clue_obs`/`clue_config`
  (this round only packaged them).
