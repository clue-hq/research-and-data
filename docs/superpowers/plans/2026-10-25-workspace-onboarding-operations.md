# Workspace Onboarding Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo the founder's standing rule is that the session implements plans itself (no implementer subagents) and reviews once at the end.

**Goal:** Give operators four operations — add a workspace, start onboarding, check providers, repair a workspace. Each is available both as an unauthenticated `/ops/v1` route and as a script, and both call the same function. Make brand-kit jobs report gaps honestly.

**Architecture:**
- **Platform.** One module family, `platform/api/clue_api/workspace_ops/`, owns the four operations. One FastAPI router exposes them. Scripts in `scripts/` call the same functions.
- **Brand-kit planning.** It reads design tables through the shared `clue_design` data-access package, in-process.
- **Brand-kit offering.** The platform writes the `design_ingestion_job` row plus its `design_job` fleet task, in the same transaction as the onboarding repair run and the audit row.
- **Repair execution.** It happens on existing machinery:
  - a new `repair` kind of `onboarding_run`, driven by the existing fleet handler
  - a new `kit_repair` design ingestion kind, run on the design coordinator

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async (Postgres), Alembic, the in-repo fleet queue (`clue_fleet`), httpx, pytest; TypeScript/Zod for four frontend status readers.

**Spec:** `docs/superpowers/specs/2026-10-25-workspace-onboarding-operations-design.md`. It was approved by the founder on 2026-10-25, with these rulings:
- D1: open routes, no sign-in.
- D2–D8: as recommended.
- My calls: accepted.

## Global Constraints

**Database and migrations**
- Alembic uses hash revision ids. Each migration is reversible, and there is exactly one head (`alembic heads` returns one revision).
- Postgres enum values are only ever APPENDED. `tests/design/test_design_schema_db.py` asserts label order lock-step with `clue_design.enums`.

**Seams**
- The platform may import `clue_design` (data access) and `clue_fleet`. It must never import `lumen_*`.
- `clue_design` must never import `clue_fleet`. The import-linter contract and the `envelopes.py` docstring both forbid it.

**Configuration**
- Every new env flag goes into `.env.example` with its default in the same commit that introduces it. The flags are `CLUE_OPS_ROUTES_ENABLED=true` and `CLUE_PREFLIGHT_OPENROUTER_MIN_CREDIT_USD=5`.

**Routes**
- `/ops/v1` routes have no principal, no membership and no permission check (founder ruling D1).
- `operator_email` must name an existing `platform_user`. If it does not, the route returns `422 operator_unknown`.
- Refusal bodies use `{"detail": {"code": <code>, "message": <text>}}`, the `settings_authority.refused` shape.

**Statuses and names**
- The new design status is exactly `succeeded_with_gaps`. The new design kind is exactly `kit_repair`. The new onboarding run kind is exactly `repair`.
- An `empty` research step is never a gap. A harvest with no ads is never a gap. A harvest's `deferred` card step is never a gap.

**Repair semantics**
- Dry run is the default everywhere. Apply requires the `plan_digest` from a dry run, refuses `409 plan_changed` on drift, and refuses `409 nothing_to_repair` on an empty plan.
- Repair never re-harvests ads, never re-runs a whole onboarding, and never offers one description job per asset.

**Testing**
- Tests run against a throwaway database (Task 0) with no real provider keys.
- Never run `subsystems/clue-design/apps/api/tests` as a folder. Name test files only.
- Never use `make check` or broad pytest with real keys.

**Production**
- Do not touch production. Do not repair Illumio.

**Commits**
- Commit locally after each task. Never push.
- Commit messages carry no AI attribution (repo `CLAUDE.md` overrides the harness reminder).

## Review Focus

1. **Two applies at once for the same workspace.** Exactly one should win. The other should get `409 nothing_to_repair`, or `onboarding_in_progress` because the first one's run is now open. Task 9 takes the per-workspace advisory lock (`ops-repair:<ws>`) before re-planning and pins this with a test that applies the same digest twice.
2. **A workspace whose newest kit-building job is still `running` when someone asks for a repair.** The brand-kit half should be reported as in flight, not planned. Task 6 has a test for it.
3. **Partial-state replays.** A `kit_repair` job re-offered by the reaper after its worker died mid-way must not publish two extra kit versions or offer two card jobs:
   - the republish compares against the kit's current content
   - the card offer is keyed on the next attempt number derived from existing rows

   Task 5 has a test that runs the job twice.
4. **An `operator_email` given in a different case or with surrounding spaces** (`" Aryan@CLUEHQ.ai "`). It should resolve the same user. Task 7 normalizes with `strip().casefold()`, as `provision_additional_workspace` does, and tests it.
5. **Pre-flight with a key that is missing (empty env), not invalid.** It should report `not_configured` and refuse. It must never send an empty bearer token to the provider. Task 8 has a test for it.

---

## File Structure

**Platform: new package `platform/api/clue_api/workspace_ops/`**
- `__init__.py`: re-exports the public functions below.
- `operators.py`: `resolve_operator(conn, email) -> Operator`, plus the `OpsRefused` error.
- `audit.py`: `record_operation(...)`, which writes `workspace_operation`.
- `preflight.py`: `check_providers(...) -> PreflightReport`.
- `onboarding_start.py`: `start_onboarding(...)`, the shared start used by both routes.
- `onboarding_plan.py`: `plan_onboarding_repair(conn, ws) -> OnboardingRepairPlan`, which reads only.
- `kit_offer.py`: `offer_design_job(conn, ...)`, the in-process `design_ingestion_job` row plus the `design_job` task.
- `repair.py`: `plan_repair(...)`, `apply_repair(...)` and `RepairPlan`.
- `routes.py`: `create_ops_router(...)`.

**Platform: modified**
- `platform/api/clue_api/onboarding_routes.py`: the body moves into `start_onboarding`, and `/onboarding/current` gains `gaps`.
- `platform/api/clue_api/arv2/onboarding_driver.py`: the `repair` kind.
- `platform/api/clue_api/arv2/onboarding_store.py`: `create_repair_run`.
- `platform/api/clue_api/brand_kit_ingestion.py`: a gap-aware `ensure`, plus a status read that accepts the new value.
- `platform/api/clue_api/projections_app.py`: mount the router behind the flag.
- `libs/clue-config/clue_config/settings.py`: two settings.

**Shared design data access: new `subsystems/design/clue_design/kit_repair.py`**
- `plan_kit_repair(conn, ws) -> KitRepairPlan`, which reads only.

**Shared design data access: modified**
- `clue_design/enums.py`: the two new enum values.
- `clue_design/ingestion.py`: `complete` derives `succeeded_with_gaps` from the evidence `gaps`.

**Design app (`subsystems/clue-design/apps/api/`)**
- New `lumen_ingestion/kit_republish.py`: `republish_kit_with_descriptions(...)`, extracted from the describe-assets route.
- New `lumen_ingestion/kit_repair.py`: `run_kit_repair(...)`, the job runner.
- Modified:
  - `lumen_ingestion/describe.py`: only `ready` rows count as cached.
  - `lumen_ingestion/pipeline.py`: gaps in website, PDF and upload evidence.
  - `lumen_ingestion/ad_library/onboarding.py`: gaps for the harvest and card phases.
  - `lumen_ingestion/ad_library/auto_card.py`: card attempts, and reading the new status.
  - `lumen_api/asset_enrichment.py`: a partial result means complete with gaps, not fail.
  - `lumen_api/main.py`: dispatch `kit_repair`, the route calls `republish_kit_with_descriptions`, the DTO serves `gaps`.

**Migrations and scripts**
- New migration `alembic/versions/<hash>_workspace_onboarding_operations.py`.
- New scripts:
  - `scripts/start_workspace_onboarding.py`
  - `scripts/check_onboarding_providers.py`
  - `scripts/repair_workspace.py`
  - `scripts/workspace_onboarding_operations.md` (the runbook)
- Modified: `scripts/provision_additional_workspace.py`.

**Frontend**
- `apps/frontend/src/features/onboarding/data/setup.ts`
- `apps/frontend/src/features/onboarding/model/setup-items.ts`
- `apps/frontend/src/features/brand-context/model/brand-kit-actions.ts`
- `subsystems/clue-design/apps/editor/src/components/brand/IngestConsole.tsx`

---

### Task 0: Test environment baseline

**Files:** none committed. The commands are recorded in `_memory/2026-10-25-workspace-onboarding-operations.md`.

- [ ] **Step 1: Read the area guides**

Read `subsystems/clue-design/AGENTS.md` and `apps/frontend/AGENTS.md`. Note any rule that changes a later task, for example design test invocation or frontend lint rules, in the memory file.

- [ ] **Step 2: Create a throwaway database and migrate it to head**

```bash
docker exec clue-pg-papeete psql -U postgres -c "CREATE DATABASE clue_onb_ops_test"
set -a; source .env; set +a
CLUE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55040/clue_onb_ops_test uv run alembic upgrade head
```

Expected: the upgrade ends at the single current head. Use the user and password `.env`'s other lane DSNs use on port 55040. If the database name is taken, pick another and record it.

- [ ] **Step 3: Prove both test harnesses run green before any change**

```bash
CLUE_DATABASE_URL=…/clue_onb_ops_test uv run pytest tests/api/test_onboarding_routes_db.py tests/scripts/test_provision_additional_workspace.py -q
```

Expected: everything passes, with **0 skipped**. A skip means the database fixture did not connect.

Find the design-app invocation that runs one named file, for example `subsystems/clue-design/apps/api/tests/test_ingestion_jobs.py`, with `LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0`. Record the exact working command in the memory file. Every later "design test" step uses it.

---

### Task 1: Migration and enums

**Files:**
- Create: `alembic/versions/<hash>_workspace_onboarding_operations.py`, via `uv run alembic revision -m "workspace onboarding operations"`, with `down_revision` set to the current head.
- Modify: `subsystems/design/clue_design/enums.py`. Append `SUCCEEDED_WITH_GAPS = "succeeded_with_gaps"` to `DesignIngestionStatus` and `KIT_REPAIR = "kit_repair"` to `DesignIngestionKind`.
- Test: `tests/db/test_workspace_onboarding_operations_migration.py` (new), plus the existing `tests/design/test_design_schema_db.py`.

**Interfaces:**
- Produces, on `onboarding_run`:
  - `kind` gains the allowed value `repair`
  - a new column `planned_steps jsonb NULL`
  - a CHECK requiring `planned_steps IS NOT NULL` exactly when `kind = 'repair'`
- Produces the table `workspace_operation`:
  - `operation_id uuid PRIMARY KEY`
  - `operation text NOT NULL`, with a CHECK on `operation IN ('add_workspace','start_onboarding','repair')`
  - `workspace_id text NOT NULL`
  - `actor text NOT NULL`, with a CHECK that it is non-blank
  - `reason text NULL`, with a CHECK that it is non-blank when not null
  - `plan_json jsonb NOT NULL DEFAULT '{}'`
  - `estimated_cost_usd numeric(12,4) NOT NULL DEFAULT 0`
  - `onboarding_run_id uuid NULL`
  - `design_job_ids text[] NOT NULL DEFAULT '{}'`
  - `created_at timestamptz NOT NULL DEFAULT now()`
  - an index on `(workspace_id, created_at DESC)`
- Produces the enum values `design_ingestion_status.succeeded_with_gaps` and `design_ingestion_kind.kit_repair`.

- [ ] **Step 1: Write the failing migration test**

`test_upgrade_adds_repair_kind_operation_table_and_design_enum_values`:
- After upgrade, inserting an `onboarding_run` with `kind='repair', planned_steps='[]'` succeeds.
- `kind='repair'` with `planned_steps NULL` raises an IntegrityError.
- A `workspace_operation` row with `operation='repair', actor='operator:a@b.c'` inserts.
- `'succeeded_with_gaps' = ANY(enum_range(NULL::design_ingestion_status)::text[])`.
- `'kit_repair' = ANY(enum_range(NULL::design_ingestion_kind)::text[])`.

`test_downgrade_maps_gapped_jobs_back_and_refuses_with_kit_repair_rows`:
- On a separate throwaway database (the `make db-smoke` shape), a `design_ingestion_job` with `status='succeeded_with_gaps'` becomes `succeeded` after downgrade.
- A `kit_repair` row makes the downgrade raise.

- [ ] **Step 2: Run it and see it fail**

```bash
uv run pytest tests/db/test_workspace_onboarding_operations_migration.py -q
```

Expected: FAIL.

- [ ] **Step 3: Write the migration**

- **`upgrade()`.** Read the current names of the `onboarding_run.kind` CHECK and the kind/persona CHECKs from `b953bf11e2a9` and `ddf063300a0b`. Drop them and recreate them with `repair` added. Add the column and the new CHECK. Create the table. Then run `ALTER TYPE … ADD VALUE IF NOT EXISTS` for each enum value, inside `op.get_context().autocommit_block()`, because Postgres refuses `ADD VALUE` in a transaction that later uses the value.
- **`downgrade()`.**
  - Refuse with `RuntimeError` if any `kit_repair` job exists.
  - Map `succeeded_with_gaps` rows to `succeeded`.
  - Rebuild each enum type without the value (rename the old type, create the new one, `ALTER COLUMN … TYPE … USING col::text::newtype`, drop the old type).
  - Drop the table, the column and the CHECK, and restore the old kind CHECK.

- [ ] **Step 4: Update the enum members, then run the migration and schema-parity tests**

```bash
uv run pytest tests/db/test_workspace_onboarding_operations_migration.py tests/design/test_design_schema_db.py -q && uv run alembic heads
```

Expected: PASS, and exactly one head.

- [ ] **Step 5: Commit**

`git commit -m "Migration: onboarding repair runs, workspace_operation audit, design gaps status and kit_repair kind"`

---

### Task 2: Honest brand-kit job status

**Files:**
- Modify: `subsystems/design/clue_design/ingestion.py` (`complete`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/pipeline.py` (`_evidence_dump` and its three callers)
- Modify: `lumen_ingestion/ad_library/onboarding.py` (`_complete`)
- Modify: `lumen_api/asset_enrichment.py` (`run_asset_enrichment`)
- Modify: `lumen_ingestion/ad_library/auto_card.py` (`_newest_usable_harvest`, `_newest_kit`)
- Modify: `lumen_api/dto.py` (`ingestion_job_dto`)
- Modify: `platform/api/clue_api/brand_kit_ingestion.py` (`read_newest_ingestion_job`)
- Test: `tests/design/test_ingestion_gaps_db.py` (new)
- Test: design tests `test_ingestion_jobs.py`, `test_ad_assets_onboarding.py`, `test_asset_enrichment_api.py`, extended

**Interfaces:**
- Produces the gap entry shape. One evidence key, `gaps: list[Gap]`, where
  `Gap = {"area": "descriptions"|"brief"|"grammar_audit"|"ad_analyses"|"ad_card", "failed": int, "reason": str}`.
  `failed` is a count. It is `1` for brief, grammar audit and card.
- Produces this behaviour: `clue_design.ingestion.complete(...)` writes `succeeded_with_gaps` when the evidence JSON is an object whose `gaps` is a non-empty array, and `succeeded` otherwise. There is no new parameter.
- Produces `pipeline.ingestion_gaps(evidence, diagnostics) -> list[dict]`:
  - one `descriptions` gap when `evidence.description_progress["failed"] > 0`. Its reason is the most common failure code in the LUMI0803 diagnostics, or `"analysis failed"`.
  - one `brief` gap when a `LUMI0903` diagnostic exists
  - one `grammar_audit` gap when a `LUMI0910` diagnostic exists
- Produces the DTO field `gaps`, the evidence `gaps` list (default `[]`).

- [ ] **Step 1: Write the failing tests**

`tests/design/test_ingestion_gaps_db.py`:
- `test_complete_with_gaps_in_evidence_is_succeeded_with_gaps`: create a job, then `complete(evidence_json='{"gaps":[{"area":"descriptions","failed":3,"reason":"x"}]}')`. The status is `succeeded_with_gaps`.
- `test_complete_without_gaps_or_with_non_object_evidence_is_succeeded`: evidence `'{"gaps":[]}'`, `'[]'` and `None` all give `succeeded`.

Design tests:
- `test_ingestion_jobs.py::test_ingestion_gaps_names_failed_descriptions_brief_and_grammar`: `ingestion_gaps` over evidence with `description_progress={"failed":2,…}` and LUMI0903 and LUMI0910 diagnostics returns exactly three gaps, with areas `descriptions`, `brief` and `grammar_audit`.
- `test_ad_assets_onboarding.py`, for the harvest phase:
  - `test_harvest_with_failed_ad_analyses_records_an_ad_analyses_gap`: `evidence["gaps"] == [{"area":"ad_analyses","failed":<n>,…}]`.
  - `test_harvest_with_no_ads_or_deferred_card_has_no_gaps`: `gaps == []`.
- `test_ad_assets_onboarding.py`, for the card phase: `test_card_phase_distil_failure_records_an_ad_card_gap`.
- `test_asset_enrichment_api.py::test_partial_enrichment_completes_with_gaps_not_failed`: two targets, one describer failure. The job status is `succeeded_with_gaps` and `error` is null.
- `test_ad_assets_onboarding.py::test_card_offer_accepts_a_gapped_kit_and_harvest`: the kit job and the harvest are both `succeeded_with_gaps`, and `offer_card_if_ready` still returns a job id.

- [ ] **Step 2: Run them and see them fail**

Use the design invocation from Task 0 on the three design files, plus `uv run pytest tests/design/test_ingestion_gaps_db.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

- **`complete`.** The status is chosen in SQL from the evidence, so no caller can forget:
  ```sql
  CASE WHEN jsonb_typeof(CAST(:evidence AS jsonb)) = 'object'
        AND jsonb_typeof(CAST(:evidence AS jsonb)->'gaps') = 'array'
        AND jsonb_array_length(CAST(:evidence AS jsonb)->'gaps') > 0
       THEN 'succeeded_with_gaps' ELSE 'succeeded' END
  ```
- **The pipeline.** Add `gaps=ingestion_gaps(evidence, diagnostics)` to the payload `_evidence_dump` writes, at its three call sites (lines ~1181, 1737, 2009). Thread `diagnostics` through.
- **The ad lane.** In `_complete`, set `evidence["gaps"]`:
  - harvest: when `steps.enrich.status == "failed"`, add `ad_analyses` with `failed = total - ready`
  - card: when `steps.distill.status == "failed"`, add `ad_card`
- **Asset enrichment.** When `summary["ready"] != summary["total"]`, call `store.complete(job_id, None, None, json.dumps({**counts, "gaps": [{"area": "descriptions", "failed": counts["failed"], "reason": "analysis failed"}]}))`.
- **The card readiness checks.** Both accept `status in ("succeeded", "succeeded_with_gaps")`.
- **The DTO.** It adds `"gaps": (job.get("evidence") or {}).get("gaps", [])` when evidence is a dict.
- **`read_newest_ingestion_job`.** Accept the new value in its status filter.

- [ ] **Step 4: Run the Step 2 commands again.** Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Brand-kit jobs that finish with gaps say succeeded_with_gaps and list their gaps"`

---

### Task 3: Kit backfill heals failed descriptions, and the republish becomes reusable

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/kit_republish.py`
- Modify: `lumen_ingestion/describe.py` (`describe_kit_assets`)
- Modify: `lumen_api/main.py` (the `describe_brand_kit_assets` route body)
- Test: design test `test_ingestion_describe.py`, extended

**Interfaces:**
- Produces:
  ```python
  def republish_kit_with_descriptions(
      repo: HybridRepository, *, brand_kit_id: str, describer: Any, core: Any,
      publish: Callable[[JsonObject, JsonObject, list, int], JsonObject],
      cache_dir: str,
  ) -> JsonObject
  ```
  It returns `{"brand_kit_id", "published": bool, "counts", "diagnostics", "created": JsonObject | None}`.
  - `publish(brand_kit, brand_summary, diagnostics, expected_base_version) -> created_kit_record`.
  - Every engine failure re-raises `CoreError`. The route keeps its `core_http_error` mapping.
- `describe_kit_assets` treats only rows whose `analysis_status == "ready"` as cached. Rows that are not ready are misses. The legacy rows have no `analysis_status`; treat a missing status with a non-empty `description` as ready.

- [ ] **Step 1: Write the failing tests**

- `test_kit_backfill_redescribes_failed_rows`: seed a kit with two image entries, one description row `ready` and one `failed`. Call `describe_kit_assets` with a stub describer that records calls. The stub is called once, for the failed asset only. `counts["cached"] == 1` and `counts["described"] == 1`.
- `test_republish_publishes_a_new_version_only_when_something_was_stamped`: call `republish_kit_with_descriptions` with an inactive describer.
  - With a ready, unstamped description: `published is True`, and `publish` is called with `expected_base_version` equal to the kit's version.
  - Called again: `published is False`.

- [ ] **Step 2: Run the design test file and see it fail**

- [ ] **Step 3: Implement**

Move the route body from `ensure_type_size_ramp` down to the `_publish_brand_kit_version` call into `republish_kit_with_descriptions`. The route then becomes:

```python
result = republish_kit_with_descriptions(repo, brand_kit_id=brand_kit_id, describer=resolve_describer(), core=app.state.core, publish=lambda kit, summary, diags, base: _publish_brand_kit_version(repo, kit, summary, diags, "manual", expected_base_version=base), cache_dir=request_cache_dir(repo))
```

The route keeps its response shape, its `log_event` call and its `brand_kit_created_dto(created, diagnostics)` call. Change the `describe.py` cache test as specified.

- [ ] **Step 4: Run** `test_ingestion_describe.py`, plus the describe-assets route tests in `test_api.py`. Find them with `grep -n "describe-assets" apps/api/tests/test_api.py` and run those test names only. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Kit backfill re-describes failed rows; the describe-and-republish step is one reusable function"`

---

### Task 4: A failed ad-DNA card can be offered again

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/auto_card.py`
- Test: design test `test_ad_assets_onboarding.py`

**Interfaces:**
- `card_job_id(workspace_id: str, harvest_job_id: str, attempt: int = 0) -> str`:
  - attempt 0 returns exactly today's value
  - attempt n > 0 hashes `f"{workspace_id}:{harvest_job_id}:{n}"`
  - the work id follows the same rule: `clue:adcard:{ws}:{harvest}` at 0, and with `:{n}` appended for n > 0
- `offer_card_if_ready(workspace_id: str, *, tools: Any = None, retry: bool = False) -> Optional[str]`:
  - With `retry=False` the behaviour is unchanged.
  - With `retry=True`, when no `design_ad_dna_card` exists for the harvest (`clue_design.ad_assets.ad_dna_card_for_harvest_job`) and no card job for that harvest is `queued` or `running`, it offers attempt `n`. `n` is the number of existing card jobs whose `request.harvest_job_id` equals that harvest.

- [ ] **Step 1: Write the failing tests**

- `test_card_job_id_attempt_zero_is_unchanged`: assert `card_job_id("ws","h") == "ingest_adcard_" + sha256(b"ws:h").hexdigest()[:24]`.
- `test_failed_card_is_reoffered_as_attempt_one_on_retry`: seed a harvest and a kit, offer once, mark that card job `succeeded_with_gaps` with no card row. Then:
  - `offer_card_if_ready(ws)` returns `None`
  - `offer_card_if_ready(ws, retry=True)` returns `card_job_id(ws, h, 1)`
  - a second `retry=True` call returns `None`, because attempt 1 is queued

- [ ] **Step 2: Run, and see it fail. Step 3: Implement. Step 4: Run, and see it pass.**

- [ ] **Step 5: Commit**

`git commit -m "Ad-DNA card: attempt-numbered job ids so a failed card can be re-offered from the same harvest"`

---

### Task 5: The `kit_repair` job

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/kit_repair.py`
- Modify: `lumen_api/main.py`. Add `DesignIngestionKind.KIT_REPAIR: run_kit_repair` to the dispatch table at ~12682.
- Test: new design test `apps/api/tests/test_kit_repair.py`

**Interfaces:**
- The job's request, written by Task 6's planner:
  ```json
  {"targets": {"<asset_id>": {}}, "republish_brand_kit_id": "<id>|null",
   "offer_card": true|false, "actor": "...", "reason": "...", "operation_id": "<uuid>"}
  ```
- Produces:
  ```python
  def run_kit_repair(engine_cache_dir: str, job_id: str, *, workspace_id: str,
                     storage: Any = None, expected_generation: int | None = None) -> None
  ```
  Like every runner, it never raises. It uses `run_ingestion_job` (`lumen_ingestion/jobs.py`). Its `work(report)`:
  1. When targets exist, call `enrich_assets(targets, …)` exactly as `run_asset_enrichment` builds its resolvers. Inside a coordinator job this fans out to the analysis pool.
  2. When `republish_brand_kit_id` is set, call `republish_kit_with_descriptions(...)` with:
     - `describer` set to an object whose `active` is `False`
     - `core=_core_client()`
     - `publish` going through `_worker_design_tools(...)` and invoking `design_publish_brand_kit_version` with `source="ingestion"`
  3. When `offer_card` is set, call `offer_card_if_ready(ws, retry=True)`.
  4. It returns `(kit_id_or_None, version_or_None, json.dumps(evidence))`. The evidence is `{"description_progress": counts, "republish": {...}, "card_job_id": …, "gaps": [...]}`. There is one `descriptions` gap when any target is still not `ready` after the enrichment.

- [ ] **Step 1: Write the failing tests**

`test_kit_repair.py`, with a stub describer and a stub core:
- `test_kit_repair_describes_republishes_and_offers_card`:
  - seed a kit with three image entries whose description rows are `failed`
  - seed a succeeded harvest with custodied creatives and no card
  - run a `kit_repair` job with all three targets, `republish_brand_kit_id` and `offer_card: true`
  - the job is `succeeded`, all three rows are `ready`, the kit is at version `base+1` with descriptions stamped, and a card job for attempt 0 (or 1) exists
- `test_kit_repair_with_a_still_failing_asset_ends_with_gaps`: the describer fails one asset, so the status is `succeeded_with_gaps` with one `descriptions` gap.
- `test_kit_repair_run_twice_publishes_once_and_offers_one_card`: run the same job body twice (Review Focus 3). The kit version advances once, and exactly one card job is queued.

- [ ] **Step 2: Run, and see it fail. Step 3: Implement. Step 4: Run, and see it pass.**

- [ ] **Step 5: Commit**

`git commit -m "kit_repair ingestion job: batch-describe, republish with descriptions, re-offer the ad card"`

---

### Task 6: Brand-kit repair planner, and the in-process offer

**Files:**
- Create: `subsystems/design/clue_design/kit_repair.py`
- Create: `platform/api/clue_api/workspace_ops/kit_offer.py`
- Test: `tests/design/test_kit_repair_plan_db.py` (new), `tests/api/test_workspace_ops_kit_offer_db.py` (new)

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class KitRepairPlan:
      capture_website: str | None          # URL of the failed capture when no kit exists at all
      describe: tuple[str, ...]             # asset ids: analysis_status 'failed' or 'stale', sorted
      unsupported: tuple[str, ...]          # listed, never re-run
      republish_brand_kit_id: str | None    # newest kit lineage, when describe is non-empty OR a ready description is not stamped on its kit entry
      offer_card_for_harvest: str | None    # newest usable harvest with no card and no open card job
      in_flight: tuple[str, ...]            # human-readable reasons: an open kit job, an open kit_repair, queued/analyzing rows
  async def plan_kit_repair(conn: AsyncConnection, *, workspace_id: str) -> KitRepairPlan
  ```
  The rules:
  - **The kit.** The newest kit is the newest `website`, `pdf` or `asset_upload` job with status `succeeded` or `succeeded_with_gaps` and a `brand_kit_id`. Read the kit record through the existing `clue_design` brand-kit data access at that job's `(brand_kit_id, brand_kit_version)`, or at the lineage's latest version. Use whichever reader `HybridRepository.require_brand_kit` uses.
  - **A kit-building job still running.** When the newest kit-building job is `queued` or `running`, everything is `in_flight` and nothing is planned.
  - **An open `kit_repair` job** makes everything `in_flight` too.
  - **No kit and a failed newest job.** `capture_website = request["url"]`, and nothing else is planned.
- Produces:
  ```python
  async def offer_design_job(conn: AsyncConnection, *, workspace_id: str, kind: str,
                             request: dict[str, Any], priority: int = 0) -> str
  ```
  It returns the job id. It mints `job_id = clue_design.ingestion.new_id("ingest")` and `work_id = uuid4()`, builds a `DesignIngestionEnvelope(work_id, workspace_id, kind="ingestion", job_id, ingestion_kind=kind)`, then calls `create_job(...)` and `clue_fleet.queue.enqueue_task(conn, kind=FleetTaskKind.DESIGN_JOB, project_run_id=ProjectRunId(work_id), dedup_key=str(work_id), payload=envelope, priority=priority, reopen_terminal=False)`. This mirrors `lumen_ingestion.jobs.create_and_offer`. Say so in a docstring line, because the platform may not import `lumen_*`.

- [ ] **Step 1: Write the failing tests**

`test_kit_repair_plan_db.py`:
- `test_illumio_shape_plans_descriptions_republish_and_card`: a kit job `succeeded`, 5 rows (3 `failed`, 1 `ready` but unstamped, 1 `unsupported`), and a succeeded harvest with creatives and no card. The plan has `describe` = the 3 failed ids, `unsupported` = the 1, `republish_brand_kit_id` = the kit, and `offer_card_for_harvest` = the harvest.
- `test_running_kit_job_means_everything_in_flight` (Review Focus 2).
- `test_no_kit_and_failed_capture_plans_only_capture`.
- `test_complete_workspace_plans_nothing`.

`test_workspace_ops_kit_offer_db.py`:
- `test_offer_design_job_writes_job_row_and_design_task_together`: a `design_ingestion_job` row with `kind='kit_repair'`, `status='queued'` and `work_id` set, plus one `fleet_task` row with `kind='design_job'`, `dedup_key=str(work_id)`, and a payload whose `ingestion_kind == 'kit_repair'` and whose `job_id` matches.

- [ ] **Step 2: Run, and see it fail. Step 3: Implement. Step 4: Run, and see it pass.** Also run `uv run lint-imports`. Expected: all contracts kept.

- [ ] **Step 5: Commit**

`git commit -m "Brand-kit repair planner in clue_design; platform offers design jobs in-process"`

---

### Task 7: Operators, audit, and the onboarding repair planner

**Files:**
- Create: `platform/api/clue_api/workspace_ops/__init__.py`, `operators.py`, `audit.py`, `onboarding_plan.py`
- Test: `tests/api/test_workspace_ops_onboarding_plan_db.py` (new)

**Interfaces:**
- Produces:
  ```python
  class OpsRefused(Exception):
      def __init__(self, status: int, code: str, message: str, *, detail: dict | None = None)
  @dataclass(frozen=True)
  class Operator: user_id: str; email: str
  async def resolve_operator(conn, email: str) -> Operator
  ```
  It normalizes with `strip().casefold()` and matches `lower(email)` on `platform_user`. If no user matches, it raises `OpsRefused(422, "operator_unknown", …)`. Its actor string is `f"operator:{email}"`.
- Produces:
  ```python
  async def record_operation(conn, *, operation: Literal["add_workspace","start_onboarding","repair"],
      workspace_id: str, actor: str, reason: str | None, plan: dict, estimated_cost_usd: Decimal,
      onboarding_run_id: UUID | None, design_job_ids: Sequence[str]) -> UUID
  ```
- Produces:
  ```python
  @dataclass(frozen=True)
  class PlannedStep: kind: str; subject_ref: str | None; reason: str; estimate_usd: Decimal
  @dataclass(frozen=True)
  class OnboardingRepairPlan:
      steps: tuple[PlannedStep, ...]
      in_flight: tuple[str, ...]
      brand_id: str | None; company_domain: str | None; company_name: str | None
  async def plan_onboarding_repair(conn, *, workspace_id: str) -> OnboardingRepairPlan
  ESTIMATE_USD: Mapping[str, Decimal]
  ```
  `ESTIMATE_USD` is the one fixed-figure table:
  - Exa steps take their configured effort's figure from `exa_client.AGENT_EFFORT_ESTIMATE_USD`
  - `lineup` = 2 × `DEEP_REASONING_ESTIMATE_USD`
  - `synthesis` = `Decimal("1.00")` and `persona` = `Decimal("0.50")`. These are placeholders to replace from recent `agent_model_call` totals. Record the query and the figures in the memory file when the table is written.
  - `description` = `Decimal("0.002")` per asset
- The merge rule:
  - Take the newest `kind='full'` run, plus every `kind='repair'` run created after it.
  - For each `(kind, coalesce(subject_ref,''))`, the newest attempt wins, by `started_at` and then by run `requested_at`.
  - A queued repair run's `planned_steps` count as in flight.
  - Any `full` or `repair` run that is `queued` or `running` puts everything in flight.
- What is planned:
  - every step whose newest attempt is `failed`
  - `lineup` when `catalog_sync` failed
  - all `persona` steps for current brand-level ICPs when `synthesis` is planned
  - a `persona` step for a failed persona whose ICP document is current
  - **never** a step whose newest attempt is `empty` or `completed`
- `company_domain` comes from the newest full run. `company_name` comes from the brand's name.
- No full run at all means nothing is planned, with `in_flight=("no onboarding has run; start one",)`.

- [ ] **Step 1: Write the failing tests**

- `test_failed_icp_plans_synthesis_and_its_personas`: a full run with `synthesis` failed (`provider_refused:openrouter:auth_invalid`), with overview, lineup and reviews completed. The plan is exactly `synthesis` plus a `persona` step for each current ICP. With none current, it is `synthesis` alone. Each reason names the failure code.
- `test_empty_steps_are_never_planned`: reviews `empty`, so it is not in the plan.
- `test_a_later_repair_attempt_supersedes_the_full_runs_failure`: the full run's `synthesis` failed, then a later repair run's `synthesis` completed. The plan is empty.
- `test_queued_repair_run_puts_its_planned_steps_in_flight`.
- `test_resolve_operator_normalizes_case_and_spaces` (Review Focus 4), and `test_unknown_operator_is_refused_422`.

- [ ] **Step 2: Run, and see it fail. Step 3: Implement. Step 4: Run, and see it pass.**

- [ ] **Step 5: Commit**

`git commit -m "workspace_ops: operator resolution, operation audit, onboarding repair planner"`

---

### Task 8: Pre-flight

**Files:**
- Create: `platform/api/clue_api/workspace_ops/preflight.py`
- Modify: `libs/clue-config/clue_config/settings.py` (`preflight_openrouter_min_credit_usd: Decimal = Decimal("5")`), `.env.example`
- Test: `tests/api/test_workspace_ops_preflight.py` (new, offline, with a scripted httpx transport)

**Interfaces:**
- Produces:
  ```python
  ProbeOutcome = Literal["ok", "low_credit", "no_credit", "key_invalid", "unreachable", "not_configured"]
  @dataclass(frozen=True)
  class ProbeResult: provider: str; outcome: ProbeOutcome; required: bool; detail: str; credit_usd: Decimal | None
  @dataclass(frozen=True)
  class PreflightReport:
      results: tuple[ProbeResult, ...]
      @property
      def blocking(self) -> tuple[ProbeResult, ...]   # required and outcome not in ("ok","low_credit")
  async def check_providers(*, settings: Settings, workspace_id: str,
                            http: httpx.AsyncClient, exa_probe: ExaProbe) -> PreflightReport
  ExaProbe = Callable[[str], Awaitable[ProbeResult]]   # workspace_id -> result
  def build_exa_probe(settings: Settings, conn_factory: ConnFactory) -> ExaProbe
  ```
- **The providers.**
  - `openrouter_platform` (`settings.openrouter_api_key`) and `openrouter_design`. The design key is the design `OPENROUTER_API_KEY` env value, falling back to the platform key. When it is the same key, probe only once and report the second as `ok` with detail "same key as platform".
  - `exa`
  - `design_api`: `GET {CLUE_DESIGN_API_BASE_URL}/health`, or the design API's existing health path; find it with `grep -n "/health" lumen_api/main.py`. When the setting is unset, it is `not_configured`.
  - `adyntel` and `pdl`: key presence only, and only when `LUMEN_BRAND_AD_ASSETS` is on. Not required.
- **How OpenRouter's credit is read.**
  - `GET https://openrouter.ai/api/v1/key` with a 5 s timeout. A 401 or 403 is `key_invalid`.
  - Credit = the minimum of the readable figures: `data.limit_remaining`, `data.effective_budget.remaining_usd`, and `GET /api/v1/credits` (`total_credits - total_usage`, ignored on 401/403).
  - At or below 0 it is `no_credit`. Below the floor it is `low_credit`.
  - A missing key is `not_configured` and no request is sent (Review Focus 5).
- **The Exa probe.** `build_exa_probe` makes one `ExaClient.search("example", num_results=1, type="keyword")` through `build_onboarding_provider_caller` over buffered sinks. It drains them with `drain_provider_calls` stamped `LedgerStamp(workspace_id=ws)`.
  - A `ProviderHalted` with `payment_required` or `credit_exhausted` is `no_credit`.
  - A halt with `forbidden`, or a 401, is `key_invalid`.
  - A missing `CLUE_EXA_API_KEY` is `not_configured`.
- All probes run under `asyncio.gather`.

- [ ] **Step 1: Write the failing tests**

All use a scripted `httpx.MockTransport` and a fake `exa_probe`:
- `test_disabled_openrouter_key_blocks`: `/key` returns 401, so the outcome is `key_invalid` and it is in `blocking`.
- `test_openrouter_zero_budget_is_no_credit_and_below_floor_is_low_credit`.
- `test_credits_endpoint_refusal_falls_back_to_key_figures`.
- `test_missing_key_is_not_configured_and_sends_nothing` (Review Focus 5): the transport records zero requests.
- `test_exa_payment_required_blocks`.
- `test_ad_lane_keys_only_warn`.

- [ ] **Step 2: Run, and see it fail. Step 3: Implement, adding the setting to `settings.py` and `.env.example`. Step 4: Run, and see it pass.**

- [ ] **Step 5: Commit**

`git commit -m "Onboarding pre-flight: probe OpenRouter, Exa, the design API and ad-lane keys before spending"`

---

### Task 9: The shared start, the gap-aware `ensure`, onboarding gaps, and the repair driver

**Files:**
- Create: `platform/api/clue_api/workspace_ops/onboarding_start.py`, `repair.py`
- Modify:
  - `platform/api/clue_api/onboarding_routes.py`
  - `platform/api/clue_api/arv2/onboarding_store.py`
  - `platform/api/clue_api/arv2/onboarding_driver.py`
  - `platform/api/clue_api/brand_kit_ingestion.py`
- Test: `tests/api/test_workspace_ops_repair_db.py` (new), plus `tests/api/test_onboarding_routes_db.py` and `tests/api/test_brand_kit_onboarding_ingestion_db.py`, extended

**Interfaces:**
- Produces:
  ```python
  async def start_onboarding(conn_factory, *, workspace_id: str, domain: str, brand_id: str | None,
      company_name: str | None, requested_by_user_id: str, enqueuer: OnboardingEnqueuer,
      brand_kit_ingestion: BrandKitIngestionTrigger | None, preflight: Callable[[str], Awaitable[PreflightReport]] | None
  ) -> UUID
  ```
  It raises `OpsRefused`:
  - `422 blank_domain`
  - `409 brand_unavailable`
  - `409 onboarding_in_progress`: an open `full` **or `repair`** run
  - `503 providers_unavailable`, with `detail={"providers": [...]}`, when `preflight(ws).blocking` is non-empty
  - `503 enqueue_failed`

  `POST /onboarding` keeps its exact wire shapes. It maps `OpsRefused` onto its existing `{"error": code, "reason": message}` 409 and 503 bodies and passes the composed preflight (D8).
- Produces `async def create_repair_run(conn, *, run_id, workspace_id, brand_id, company_domain, requested_by_user_id, planned_steps: list[dict]) -> None` (`kind='repair'`).
- In the driver:
  - `_Scope.kind` gains `"repair"`, and `_Scope.planned` gains `tuple[tuple[str, str | None], ...]`, read from `payload["planned_steps"]`.
  - `_repair_only(scope)` marks the run running, then runs only the planned steps:
    1. `overview`, `lineup` and `reviews` in parallel, under the same semaphore.
    2. `product_research` for every link that `lineup` returned with no current `product/<slug>.md`, plus planned `product_research` subjects, resolved to a `ProductLink` from the `product` row.
    3. `customers`.
    4. `synthesis`. Its ICPs feed `persona` steps.
    5. Planned `persona` subjects, resolved to `IcpRef` from the current brand-level `audience/icp-<key>.md` document.
    6. `finish_run`.
  - `OnboardingEnqueuer.enqueue_repair(*, run_id, workspace_id, brand_id, company_domain, company_name, planned_steps)` has the `enqueue_customers` shape, with `"kind": "repair"`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class RepairPlan:
      workspace_id: str; onboarding: OnboardingRepairPlan; kit: KitRepairPlan
      estimated_cost_usd: Decimal; plan_digest: str          # sha256 of canonical JSON of the planned items only
      def as_json(self) -> dict[str, Any]
  async def plan_repair(conn, *, workspace_id: str) -> RepairPlan
  async def apply_repair(conn_factory, *, workspace_id: str, plan_digest: str, operator: Operator,
      reason: str, enqueuer: OnboardingEnqueuer) -> dict[str, Any]   # {operation_id, onboarding_run_id, design_job_ids, plan}
  ```
  **Apply runs in one transaction:**
  1. `pg_advisory_xact_lock('ops-repair:<ws>')`, then `plan_repair`.
     - On a digest mismatch it refuses `409 plan_changed`, with `detail={"plan": new.as_json()}`.
     - On an empty plan it refuses `409 nothing_to_repair`.
     - A blank reason is refused with `422 reason_required`.
  2. When the onboarding half is non-empty, it calls `create_repair_run` and `enqueue_repair`.
  3. When the kit half has `capture_website`, it calls `offer_design_job(kind="website", request={"url": …})`. Use the request shape the design API's `POST /brand-kits/ingest/website` stores; copy it from that route's `_offer_ingestion` call.
  4. Otherwise, when `describe`, `republish_brand_kit_id` or `offer_card_for_harvest` is set, it calls `offer_design_job(kind="kit_repair", request={...Task 5 shape..., "operation_id": op_id})`.
  5. `record_operation(...)`.
- **`brand_kit_ingestion.ensure`.** The early return becomes: skip when the newest kit-building job is `queued`, `running`, `succeeded` or `succeeded_with_gaps`. Proceed when there is no job, or when the newest is `failed` and no kit exists. The ad-harvest guard is unchanged.
- **`GET /onboarding/current`.** It adds `gaps: list[{"area","item","code","message"}]`:
  - research and ICP gaps from the merged newest attempts (Task 7's rule), with `failure_message[:200]`
  - plus the newest kit job's evidence `gaps`

  This needs `failure_message` added to `read_current_run`'s step select.

- [ ] **Step 1: Write the failing tests**

`test_workspace_ops_repair_db.py`. Each test seeds through real rows and uses a recording enqueuer:
- `test_illumio_replay_dry_run_then_apply_then_nothing` (spec §10 item 1):
  - The seeds are a full run with `synthesis` failed, a kit job, 4 `failed` description rows, and a harvest with creatives and no card.
  - The dry run plans `synthesis` plus 4 descriptions, a republish and a card, with an estimate above 0.
  - Apply with that digest gives one `repair` run with `planned_steps=[{"kind":"synthesis",…}]`, one `enqueue_repair` call, one `kit_repair` job whose request has 4 targets, and one `workspace_operation` row whose actor is `operator:<email>`.
  - Apply again with the same digest refuses `409` with `nothing_to_repair`, because everything is now in flight.
- `test_two_applies_race_one_wins` (Review Focus 1): two `apply_repair` calls on separate connections give exactly one success and one `409`.
- `test_apply_with_stale_digest_is_plan_changed`.
- `test_repair_run_drives_only_planned_steps`: drive the fleet handler with fake Exa and synthesis seams on a `repair` payload that names `synthesis` only. The only step rows are `synthesis` and the personas, and the run is `completed`.

`test_onboarding_routes_db.py`:
- `test_start_refuses_when_preflight_blocks_and_creates_no_run`: the response is 503, its body's `error` is `providers_unavailable`, and there is no `onboarding_run` row.
- `test_start_refuses_while_a_repair_run_is_open`.
- `test_current_lists_gaps`.

`test_brand_kit_onboarding_ingestion_db.py`:
- `test_ensure_recaptures_when_newest_failed_and_no_kit`.
- `test_ensure_skips_a_gapped_kit`.

- [ ] **Step 2: Run, and see it fail. Step 3: Implement. Step 4: Run, and see it pass.** Also run `uv run pytest tests/api/test_onboarding_routes_db.py tests/api/test_brand_kit_onboarding_ingestion_db.py -q`. Expected: PASS, including the previously existing tests.

- [ ] **Step 5: Commit**

`git commit -m "Repair: gap-driven plan/apply across onboarding steps and the brand kit; shared start with pre-flight; gap-aware ensure"`

---

### Task 10: The `/ops/v1` router, and the add-workspace operation

**Files:**
- Create: `platform/api/clue_api/workspace_ops/routes.py`
- Modify: `platform/api/clue_api/projections_app.py`. Mount the router when `settings.ops_routes_enabled`, next to the onboarding router at ~1076. Do NOT put it behind the authenticated dependency overrides.
- Modify: `settings.py` (`ops_routes_enabled: bool = True`) and `.env.example` (`CLUE_OPS_ROUTES_ENABLED=true`).
- Test: `tests/api/test_workspace_ops_routes_db.py` (new)

**Interfaces:**
- Produces `create_ops_router(*, conn_factory, enqueuer, brand_kit_ingestion, preflight_factory, settings) -> APIRouter`.
- The routes are exactly those in spec §8 D1:

  | Route | Body | Returns |
  |---|---|---|
  | `POST /ops/v1/workspaces` | `{email, website, company_name?, operator_email, apply=false}` | `{user, workspace_id, workspace_name, brand_id, onboarding_link, applied}` |
  | `GET /ops/v1/workspaces/{ws}/preflight` | none | `{results:[…], blocking:bool}` |
  | `POST /ops/v1/workspaces/{ws}/onboarding` | `{domain, company_name?, operator_email, apply=false}` | dry run: `{preflight, would_start:bool}`; apply: `{run_id}` |
  | `GET /ops/v1/workspaces/{ws}/repair-plan` | none | `RepairPlan.as_json()` |
  | `POST /ops/v1/workspaces/{ws}/repair` | `{plan_digest, reason, operator_email}` | `apply_repair` result |

  - **Add workspace.** It calls `clue_auth.provision_additional_workspace` inside a transaction that is rolled back unless `apply`. On apply it calls `record_operation("add_workspace", …)`. `IdentityConflictError` becomes 409 `workspace_exists` when the message names an existing workspace, and 422 `identity_conflict` otherwise. `ProvisioningValidationError` becomes 422 with its code.
  - **Onboarding link.** It uses `operator_setup_url`, which moves from the script into `workspace_ops/__init__.py` so the script and the route share it.
  - **Error mapping.** `OpsRefused` becomes `HTTPException(status, {"code", "message", **detail})`.
  - **Unknown workspaces.** A workspace id that does not exist returns `404 workspace_not_found`.

- [ ] **Step 1: Write the failing tests**

All requests are sent with no auth headers:
- `test_add_workspace_dry_run_writes_nothing_and_apply_writes_once_then_duplicate_409`.
- `test_unknown_workspace_404_and_unknown_operator_422`.
- `test_repair_plan_then_apply_through_http_matches_function`.
- `test_routes_absent_when_flag_off`: an app built with `ops_routes_enabled=False` returns 404 for `/ops/v1/workspaces/x/repair-plan`.

- [ ] **Step 2: Run, and see it fail. Step 3: Implement. Step 4: Run, and see it pass.**

- [ ] **Step 5: Commit**

`git commit -m "Open /ops/v1 operator routes (founder ruling D1) behind CLUE_OPS_ROUTES_ENABLED"`

---

### Task 11: Scripts and runbook

**Files:**
- Modify: `scripts/provision_additional_workspace.py`. It gains `--operator-email`, writes the audit row on `--apply` through the shared add-workspace function from Task 10, and keeps its output lines.
- Create: `scripts/start_workspace_onboarding.py`, with `--workspace --domain --operator-email [--company-name] [--apply]`.
- Create: `scripts/check_onboarding_providers.py`, with `--workspace`.
- Create: `scripts/repair_workspace.py`, with `--workspace --operator-email [--reason] [--apply]`. On `--apply` it runs a fresh dry run, prints it, and applies with its digest, so the operator applies exactly what was printed in that same invocation.
- Create: `scripts/workspace_onboarding_operations.md`, the runbook. It covers:
  - the per-environment commands
  - the dry-run-then-apply order
  - every refusal code and what it means
  - that `start_workspace_onboarding.py` must run on platform-api (`railway ssh`), because `ensure` calls the design API over HTTP
- Test: `tests/scripts/test_workspace_ops_scripts_db.py` (new), plus the existing `tests/scripts/test_provision_additional_workspace.py`

**Interfaces:**
- Each script is a single file that imports only from the installed image (`clue_api.workspace_ops`, `clue_auth`, `clue_config`, `clue_db`). It follows the `_DryRun`-exception pattern of `provision_additional_workspace.py`, and prints `DRY RUN: …` or `APPLIED: …`.

- [ ] **Step 1: Write the failing tests**

- `test_repair_script_dry_run_writes_nothing`: the row counts of `onboarding_run`, `design_ingestion_job` and `workspace_operation` are unchanged.
- `test_repair_script_apply_matches_route_effect`.
- `test_provision_script_apply_writes_audit_row`.
- `test_repair_script_runs_without_design_api_configured`: `CLUE_DESIGN_API_BASE_URL` is unset, and the script still plans and applies both halves.

- [ ] **Step 2: Run, and see it fail. Step 3: Implement. Step 4: Run, and see it pass.**

- [ ] **Step 5: Commit**

`git commit -m "Operator scripts and runbook for add/start/check/repair, same code path as /ops/v1"`

---

### Task 12: Frontend readers learn `succeeded_with_gaps`

**Files:**
- Modify:
  - `apps/frontend/src/features/onboarding/data/setup.ts:22`: add the value to the enum.
  - `apps/frontend/src/features/onboarding/model/setup-items.ts`: treat it as `succeeded`.
  - `apps/frontend/src/features/brand-context/model/brand-kit-actions.ts:12`: same.
  - `subsystems/clue-design/apps/editor/src/components/brand/IngestConsole.tsx:105,181`: same.
- Test: `apps/frontend/src/features/onboarding/data/setup.test.ts`, `model/setup-items.test.ts`, `brand-context/model/brand-kit-actions.test.ts`

- [ ] **Step 1: Write the failing tests**

- `setup.test.ts`: a wire `brandKitIngestion.status: "succeeded_with_gaps"` parses to `"succeeded_with_gaps"`, not `"running"`.
- `setup-items.test.ts`: the brand-kit row is `complete` for `succeeded_with_gaps`.
- `brand-kit-actions.test.ts`: it maps to the same action state as `succeeded`.

- [ ] **Step 2: Run, and see it fail**

```bash
cd apps/frontend && npm test -- setup setup-items brand-kit-actions
```

Use the repo's actual test runner. `package.json` names it.

- [ ] **Step 3: Implement. Step 4: Run the gate.**

```bash
cd apps/frontend && npm run design-system:build && npm run lint && npm run build
```

Expected: exit 0. If a dev server owns `.next`, record that the build was not run and why.

- [ ] **Step 5: Commit**

`git commit -m "Frontend: succeeded_with_gaps reads as a finished brand kit"`

---

### Task 13: Close-out

- [ ] **Step 1: Check the seams.** Run `uv run lint-imports` and `uv run alembic heads`. Run ruff on every changed Python file, in the root workspace only, since `subsystems/clue-design` is excluded.
- [ ] **Step 2: Run every test file this plan touched, by name.** Use the platform command, then the design invocation from Task 0. Expected: all pass, with 0 skipped DB tests.
- [ ] **Step 3: Record the work.**
  - Update `_memory/2026-10-25-workspace-onboarding-operations.md`: commits, the test evidence, the `ESTIMATE_USD` sources, and what is owed.
  - Owed: the founder-triggered live proof (spec §10 item 11), and deploy plus the Illumio repair, which is the founder's call.
  - Add a one-line pointer in `_memory/README.md` topic notes.
- [ ] **Step 4: Self-review the branch.** Run `git diff main...HEAD`.
- [ ] **Step 5: Commit the memory update**

`git commit -m "Memory: workspace onboarding operations close-out"`
