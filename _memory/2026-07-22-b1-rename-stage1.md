# 2026-07-22 — PB-B1 §1a stage-1 rename (campaign_run → project_run, fleet-owned surfaces)

**Branch:** `platform/b1-fleet-worker` (on top of the audit-repairs commits). Fleet-lane only per
the treaty; no `clue_api/`, `subsystems/research/clue_research/`, or `libs/` edits. Two commits
(the rename; then this playbook + backlog + memory). Harness §1a ruling: *project* = the
end-to-end ABM motion (historically "campaign_run"); *campaign* = a channel program within a
project — **bare "campaign" is NOT renamed**. This is stage 1 of a two-stage rename.

## What renamed (fleet-owned identifiers only)
- **`CampaignRunWorker` → `ProjectRunWorker`** — class, `__init__.py` export/`__all__`, `runner.py`
  entrypoint annotation, `worker.py` docstrings, the migration `COMMENT ON fleet_task`, the fleet
  `pyproject.toml` description, spec, and all tests. Clean break — no alias/shim.
- **`campaign_run_id` → `project_run_id`** across every fleet-owned identifier:
  - `lease.py` (`RunLeaseRow.project_run_id`, `LeaseStore` protocol, `DbLeaseStore`, module
    functions, SQL bind params) and `queue.py` (`FleetTaskRow.project_run_id`, `TaskQueue`
    protocol, `DbTaskQueue`, module functions, `_COLUMNS`, all SQL column refs + binds).
  - `worker.py` internals (`task.project_run_id`, the lease acquire/renew/release kwargs,
    `enqueue_drive(project_run_id=…)`), `scheduler.py` internals (all `self._queue.*(project_run_id=…)`
    calls + the `deep_drain.requeued_failed` log field).
  - `tests/fleet/` fakes (`FakeLeaseStore`, `FakeTaskQueue`, `run_row`), helpers, exit-gate harness
    helpers, and every DB/scheduler/worker/exit-gate test call site.
- **Migration `10642c862e43` edited in place** (branch-local, unmerged — no new migration):
  `run_lease.project_run_id` (PK column; constraint NAME `run_lease_pkey` unchanged),
  `fleet_task.project_run_id`, `fleet_task_dedup UNIQUE (kind, project_run_id, dedup_key)` and
  index `fleet_task_run (project_run_id, kind)` (names unchanged), docstring + COMMENT strings.
  The soft-FK prose now reads "soft FK to campaign_run (renames to project_run at the stage-2
  rename — see docs/specs/PB-rename-campaign-run-to-project-run.md)". The durable `campaign_run`
  table is NOT touched.

## Deliberate exceptions — KEPT legacy spelling (each marked `# §1a rename: flips at stage 2 (…)`)
1. **`QueueBackedScheduler.run_accounts(…, campaign_run_id=…)`** — structural seam
   conformance-tested against `clue_api.deep.handler.DeepAccountScheduler`
   (`test_scheduler_satisfies_the_deep_handler_seam`); B1 may not edit clue_api. Internally passes
   the value to the queue's renamed `project_run_id=` params.
2. **`RunDriver` protocol `status(campaign_run_id)` / `advance(campaign_run_id)` params** — the
   static `_CAMPAIGN_RUN_IS_A_RUN_DRIVER: type[RunDriver] = CampaignRun` assertion checks
   parameter-name compatibility against the untouchable `durable.CampaignRun`. Scripted fakes
   (`ScriptedDriver`, `ExplodingDriver`, `_ProbeDriver`) keep matching signatures. (Positional-only
   `/` alt not taken — kept names, simpler + lower risk.)
3. **Names imported from `clue_core` / `clue_research.durable` / `clue_api`** — `CampaignRunId`,
   `CampaignPhase`, `CampaignRun`, `CampaignRunRow`, `CampaignRunStatus`, `new_campaign_run_id`,
   `DbCampaignRunStore`, and their call-site kwargs (`ctx.campaign_run_id`,
   `machine.start(campaign_run_id=…)`). Type annotations therefore still read `CampaignRunId`.
4. **Direct SQL against the durable `campaign_run` table** — exit-gate test's
   `SELECT status FROM campaign_run WHERE id = :run`. (Its `fleet_task` reads DID flip to
   `project_run_id`.)

Grep-proof: `grep -rn campaign_run platform/fleet tests/fleet` shows ONLY the four exceptions (+
`new_campaign_run_id` imports, the `durable/campaign_run.py` module-ref comment, and durable-prose
`(campaign_run, phase)` phase-key mentions). `CampaignRunWorker` is gone from platform/tests/docs/specs.

## Verification (all green)
- `make db-fresh && alembic upgrade head` → clean to head `10642c862e43`.
- `make check` → **1999 passed** (83s); immediate rerun (the audit's non-hermetic gate) → **1999
  passed** (71s).
- `make db-smoke` → up→down→up reversible, **single head** `10642c862e43` (in-place edit reverses).
- `pytest tests/fleet/test_exit_gate.py` → passes (real subprocesses + SIGKILL);
  `test_scheduler_satisfies_the_deep_handler_seam` → passes (the pinned seam intact).

## Stage 2 (NOT this task)
The full A3.1-style repo rename — `docs/specs/PB-rename-campaign-run-to-project-run.md`. MUST run
immediately after B2→B3→B1 integrate (gates green) and BEFORE B4 opens. One reversible migration
(rename the `campaign_run` table + `campaign_phase`/`campaign_run_status` types + every
`campaign_run_id` column/trigger/view — carriers enumerated in the playbook), a frozen-`core`
contract-delta for `CampaignRunId`/`CampaignPhase`, then flip the four fleet exceptions (grep the
marker comment) and delete the markers, plus an empty-allowlist guard test. No aliases.
