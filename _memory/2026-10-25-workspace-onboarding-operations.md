# 2026-10-25: Workspace onboarding operations (add, start, pre-flight, repair)

## Context

- **Branch:** `claude/onboarding-repair-routes-a187b5`, cut from `main` at `ab10fd287`.
- **Origin:** started from the session `seed-acc` (`local_fa6da6a8…`) after the 2026-10-23 Illumio
  incident. In that incident Exa returned 402, the OpenRouter key was disabled, every ingestion job
  still reported `succeeded`, and recovery was manual.
- **Founder approval (2026-10-25):** build the operator lifecycle in code, everything through API
  routes. The same day the founder added: matching scripts in `scripts/`, runnable from a
  production container.

## State

- **Spec drafted:** `docs/superpowers/specs/2026-10-25-workspace-onboarding-operations-design.md`.
- **Spec approved by the founder, 2026-10-25.**
  - D1: open `/ops/v1` routes with no sign-in. The founder chose this explicitly over "any
    signed-in user", after being told the risk.
  - D2–D8: as recommended. My calls: accepted.
- **Plan:** `docs/superpowers/plans/2026-10-25-workspace-onboarding-operations.md`, tasks 0–13.
  Awaiting the founder's review.
- **Execution:** native. The session implements the tasks itself, then one review at the end.
- **Built (2026-10-26):** all 13 tasks, commits `70fa994`..`ea122df` on this branch. Local only;
  never pushed.
- **Decision ledger:** the `Ruling:` lines in
  `.superpowers/sdd/2026-10-25-workspace-onboarding-operations/progress.md`, which is gitignored.
  The key rulings are copied below.

## Verified facts (recon, 2026-10-25)

**Onboarding run status**
- `onboarding_run.status` already has `completed_with_gaps`. `finish_run` sets it when any step is
  `empty` or `failed` (`arv2/onboarding_store.py:457`).
- The setup screen treats `completed_with_gaps` as complete.

**Re-running steps**
- Step ids and the ICP turn id derive from the run id. Re-running a step therefore needs a new run.
- The narrow `customers` and `personas` run kinds already exist.

**Design ingestion jobs**
- Statuses and kinds are Postgres enums (`design_ingestion_status`, `design_ingestion_kind`).
- Website, PDF and upload jobs swallow description failures and still go `succeeded`
  (`jobs.py:186-247`, `pipeline.py:709`).

**Offering design jobs**
- Offering a design job is an in-process database write through the design tools
  (`_worker_design_tools`), not an HTTP call.
- So the brand-kit repair can be offered from any container that has the design code on its path
  (one image everywhere: `docker/backend/entrypoint.sh`).
- Only work inside a design-API request needs the design API, for example the synchronous
  `describe-assets` republish.

**Exa**
- Exa has no free balance endpoint. Its usage API needs an admin service key. The pre-flight
  therefore uses one 1-result search (about half a cent).

**Frontend status parsers**
- These parsers `.catch` unknown ingestion statuses to `running`, so a new status must be taught
  to them:
  - `apps/frontend/.../onboarding/data/setup.ts:22`
  - `brand-context/model/brand-kit-actions.ts:12`
  - `design-editor/engine/webDocuments.ts`
  - the clue-design editor's `webDocuments.ts`
  - `IngestConsole.tsx`

**Staff roles**
- No staff or platform-admin concept exists. "Operator" is a workspace role.

## Follow-ups

- After approval: write the plan, implement, run the scenario tests on a throwaway database, and
  commit locally. Never push.
- Never touch production or Illumio. The founder decides when to deploy and run.

## Test commands (Task 0, 2026-10-26)

**Test database**
- `clue_onb_ops_test` on `clue-pg-papeete:55040`, user `clue`. It is a throwaway database,
  migrated to `cba395a41e66`.
- The DSN is the nashville lane's, with the database name swapped.

**Platform tests**

```bash
CLUE_DATABASE_URL=… uv run pytest <files> -q -rs
```

**Design tests**

Run one named file at a time:

```bash
cd subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/<file>
```

Set `LUMEN_INGESTION_DESCRIBE=0` and `LUMEN_INGESTION_VISION=0` for these runs.

## What was built (2026-10-26)

**Migration `177d009a8b9d`**
- `onboarding_run.kind` gains `repair`, plus a `planned_steps` column.
- New `workspace_operation` audit table.
- Design enums gain `succeeded_with_gaps` and `kit_repair`, rebuilt reversibly. The downgrade
  refuses while any repair run or `kit_repair` job exists.

**Honest status**
- `clue_design.ingestion.complete` sets `succeeded_with_gaps` whenever the evidence `gaps` list is
  non-empty.
- These jobs now list their gaps:
  - website, PDF and upload jobs: descriptions, brief, grammar audit
  - ad harvests: failed ad analyses
  - card jobs: a failed distil. A `skipped` distil is not a gap.
  - a partial enrichment, where some assets are ready
- Card readiness accepts gapped jobs.
- The job DTO serves `gaps`.

**Repair, brand-kit side**
- The `describe_kit_assets` cache no longer counts a failed AI row as described.
- The describe-and-republish step was extracted to `lumen_ingestion/kit_republish.py`.
- Ad card job ids carry an attempt number, and `offer_card_if_ready(retry=True)` re-offers a
  failed card.
- New `kit_repair` job kind (`lumen_ingestion/kit_repair.py`).
- `clue_design/kit_repair.py` plans the brand-kit half.

**Platform: `workspace_ops/`**
- operators, audit, the onboarding plan, pre-flight, the shared start, repair and add-workspace,
  and the routes.
- The onboarding driver gains a `repair` run kind (`_repair_only`).
- `POST /onboarding` now runs pre-flight (ruling D8).
- `ensure` captures again only when the newest capture failed and no kit exists.
- `/onboarding/current` serves `gaps`.
- `/ops/v1` routes have no sign-in and are mounted unless `CLUE_OPS_ROUTES_ENABLED=false`.

**Scripts**
- `provision_additional_workspace.py` now requires `--operator-email`.
- New: `start_workspace_onboarding.py` (platform-api only), `check_onboarding_providers.py`,
  `repair_workspace.py` (runs on the VM or platform-api).
- Runbook: `scripts/workspace_onboarding_operations.md`.

**Frontend**
- The setup and brand-kit parsers, `setup-items` and the design editor's `isTerminalJob` /
  `IngestConsole` all accept `succeeded_with_gaps`.

**New environment settings:** `CLUE_PREFLIGHT_OPENROUTER_MIN_CREDIT_USD=5`,
`CLUE_OPS_ROUTES_ENABLED=true`.

## Key rulings (full list in the ledger)

- **Placeholder estimates.** Fixed figures: ICP $1.00, persona $0.50, description $0.002,
  card $0.05, capture $1.00. None was measured against production.
- **Atomic apply.** A repair is applied in one transaction, and the onboarding task is offered on
  the same connection.
- **Locks.** Repair takes the start lock too, so a start and a repair cannot overlap.
- **Probe placement.** Pre-flight runs before the start lock is taken.
- **Design key source.** The design-side OpenRouter key is read from `os.environ`, because the
  platform may not import `py_lumen_config`.
- **Lanes that now refuse.** A lane without `CLUE_DESIGN_API_BASE_URL`, an OpenRouter key or an
  Exa key now refuses `POST /onboarding` with `503 providers_unavailable`.
- **Pre-existing import failure.** lint-imports reports one BROKEN contract,
  `clue_agents.compaction_config` → `clue_gateway`, in code this branch never touches.

## Verification (2026-10-26)

- **Platform:** all 14 touched platform test files, plus the onboarding store and provisioning
  tests: 130 passed, 0 skipped. They ran on the throwaway database `clue_onb_ops_test`.
- **Design:** `test_kit_repair`, `ingestion_jobs`, `ingestion_describe`, `ad_assets_onboarding`
  and `asset_enrichment_api` are green, as are the `test_api` describe-assets test and the `a9`
  scenario-6 test.
- **Frontend:** 51/51 tests pass. The gate (`design-system:build`, `lint`, `build`) exits 0.
- **Editor:** vitest 6/6.
- **Checks:** `alembic heads` shows one head, `177d009a8b9d`. ruff is clean on the changed files.
- **Weaker evidence:** the script tests and the Exa probe database test were written after the
  code.

## Final review and fix pass (2026-10-26)

**Reviewer:** a fresh Fable reviewer. Verdict: "With fixes". Every fix below has a test that
failed first and then passed. Commit `Final review fixes…`.

- **Brand-kit planner job window.** The planner read the 50 newest jobs of every kind, so Illumio's
  100+ `asset_enrichment` retry jobs would have hidden the kit and the harvest, and the plan would
  have come out empty. Fix: it now reads each kind separately.
- **Repaired gaps.** They now clear from `/onboarding/current`: a finished `kit_repair` job speaks
  for the kit.
- **Ad-harvest guard.** A replace-all edit had copied the kit's re-capture rule into the ad-harvest
  guard in `ensure`. Restored.
- **Repair during onboarding.** A repair is now refused with `409 onboarding_in_progress` while a
  full run is open.
- **Pre-flight.** A non-JSON answer from OpenRouter now reads `unreachable` instead of failing
  with a 500.
- **Ad-analysis gaps.** Only analyses that ran and failed count as a gap. Analysis switched off is
  not a gap.
- **Hung test run (2 h 40 min).** Tests that commit a repair had left queued fleet tasks behind,
  and the design suite's fleet-worker test claimed one and waited on an analysis pool that does
  not exist in tests.
  - Fix: `close_open_work` closes them at teardown.
  - **Hazard for any lane:** design test runs leave queued `ad_assets` tasks of their own. Clear
    queued `fleet_task` rows before running a design fleet-worker test on a shared database.
- **Pre-existing failures, not from this branch:** two `test_ad_assets_advertiser_resolution`
  tests fail on `outcome partial == ok` when run with `LUMEN_INGESTION_DESCRIBE=0`. They fail
  identically at the base commit `ab10fd287`.
- **Deferred minors:**
  - The editor's `ingestModel.ts` stage text does not treat a gapped job as done.
  - The check script has no workspace-exists guard.
  - The credit floor is compared with `<` rather than `<=`.
  - The wording of spec §6 is out of date.
  - The trigger and pre-flight are built twice in `projections_app`.
  - Undescribable SVGs with no description row are planned once each.
- **Final verification:** platform 135/135, frontend gate exit 0, editor 6/6. The touched design
  files are green apart from the two pre-existing failures above.

## Owed (all founder-triggered)

- **Push and PR:** only on instruction.
- **Deploy:** run the migration, deploy, and set the design-side environment variables on
  platform-api if they are needed.
- **Live proof (spec §10 item 11, spends money):**
  1. On a dev lane, revoke a key and confirm the start is refused.
  2. Restore it, break the ICP turn, repair, and confirm the repair finishes.
- **Illumio repair:**
  1. `check_onboarding_providers.py`
  2. a `repair_workspace.py` dry run
  3. `--apply`

  The founder decides when.
- **Estimates:** replace the placeholders with figures measured from `agent_model_call` and the
  ledger.

## Live proof (2026-10-26, onbops lane)

**The lane**
- Wrapper `scripts/dev_stack_onbops.sh`. It is untracked and lives in this worktree only.
- Ports: frontend 3071, design API 8071, platform API 8072, platform API twin 8073, pages 8074,
  site editor 3171.
- Database `clue_onbops` on `clue-pg-papeete:55040`, Redis DB 11.
- `.env` was built from nashville's, with every lane-specific value replaced.
- The design helper binary was built from this branch's own source.

**The proof**
- **Operator.** A seeded user, `proof.operator@cluehq.ai`, in the lane database only.
- **Workspace.** "Clue Proof" (cluehq.ai), added through `POST /ops/v1/workspaces`: a dry run
  first, then apply.

**Step 1: refusal**
- The check refuses a bad Exa key: `exa key_invalid`, then `503 providers_unavailable`, and no
  run is created.
- **Bug found on the first try.** With a bad key, Exa answers HTTP 401, and `ExaClient` returns
  that as `result.status` instead of raising. The probe read it as `ok`, and one normal onboarding
  started (about $2).
- **Fixed** in `485f21926` with tests that failed first.

**The baseline onboarding (organic gaps, not induced)**
- The run ended `completed_with_gaps`: one persona turn hit an OpenRouter timeout.
- The website job ended `succeeded_with_gaps`: 4 descriptions failed on malformed model JSON.
- The harvest found no ads (`empty`), so no card was planned.

**Step 2: repair through `/ops/v1`**
- The plan was the persona plus 4 descriptions plus a kit republish, estimated at $0.51.
- After apply:
  - one repair run, `completed`: it re-ran only that persona, for $0.075
  - one `kit_repair` job, `succeeded`: all 21 descriptions ready, kit version 2 with 18 of 18
    images described
- A second apply returned `409 nothing_to_repair`.
- Afterwards the dry run says `nothing_to_repair`, and the research and brand-kit gaps are both
  empty.
- Three audit rows were written: `add_workspace`, `start_onboarding`, `repair`.

**Spend on the lane:** about $2.73 on the provider ledger and $2.45 in model calls.

**Not proven live:**
- repairing the ICP turn
- rebuilding a card (this company has no ads)
- the induced outage with a broken OpenRouter key on the workers

**Lane state:** the stack is still up. Stop it with `./scripts/dev_stack_onbops.sh down`.
