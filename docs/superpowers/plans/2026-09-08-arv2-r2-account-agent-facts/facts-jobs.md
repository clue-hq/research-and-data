# R2 facts — existing job substrate, launch path, run pins, product set, account entities (scouted 2026-09-08)

## DECISION (Fable, 2026-09-08): R2 gets its OWN run/job rows and its OWN fleet kind. Do not reuse
`entity_research_job` / `launch_entity_research_run` / `AccountResearchFleetLauncher`. Reasons, each a fact below:
1. `entity_research_job.product_id text NOT NULL` + CHECK-pinned `authorization_json.product_id` — ARV2 runs
   pin a product SET version, never one product (P1/P2; standing-rule item 5).
2. `AccountResearchFleetLauncher.launch` refuses unless `project_run.product_id is not None`, requires a
   sealed discovery (`require_sealed_account_discovery`), and gates on an `account_research_directive`
   whose FK is `icp_spec (workspace_id, icp_key, version)` — old Stage-0 machinery the new lane may not touch.
3. One handler per fleet kind: `FleetTaskKind.ENTITY_RESEARCH_JOB` is owned by the quarantined M8D handler.
4. Seam-1 job states are `not_started / in_progress / needs_review / completed / suspended`; the old
   enum is `queued/leased/running/waiting_external/terminal` + a six-value finalization outcome.
5. Neither `project_run`, `entity_research_run` nor `entity_research_job` has a home for
   `icp_artifact_ref` or `product_selection_version` (grep of alembic/versions: zero hits).
What IS reused: `run_lineage` (kind `entity_research`) so accounts-per-project reads work exactly as the
loader's do; `account_entity` rows (must pre-exist, box 1b); `project_product` / `current_project_product_set`
for the version; `record_run_lineage`; the sha-pin idea (profile ref + sha256 in the job row).

## 1. Existing `entity_research_job` (for reference only)
Migration `alembic/versions/022b1154b3aa_m8d_r2_entity_research_jobs.py:102-207`; columns incl. `authorization_json
jsonb NOT NULL` (CHECK-pinned to the row columns :139-163; BEFORE UPDATE trigger `entity_research_job_authority_immutable`),
`authorization_sha256`, `budget_envelope_ref NOT NULL`, `budget_cap_cents`, `checkpoint_thread_id NOT NULL`,
`current_state_sha256`, `state IN ('queued','leased','running','waiting_external','terminal')`,
`finalization_outcome IN ('completed','exhausted','needs_review','budget_stopped','cancelled','failed')`.
Profile pin lives INSIDE `authorization_json`: `EntityResearchJobAuthorization.agent_profile_ref /
agent_profile_sha256` (`libs/clue-core/clue_core/entity_research.py:629-671`). The account profile pin today:
```python
_ACCOUNT_PROFILE_VERSION = "v2"; _ACCOUNT_PROFILE_REF = f"agent-profile:account-research:{_ACCOUNT_PROFILE_VERSION}"
def account_research_profile_sha256(catalog_root: Path | None = None) -> str:   # account_entity_research_composition.py:336
    root = catalog_root or _account_catalog_root(_ACCOUNT_PROFILE_VERSION)
    return hashlib.sha256((root / "profile.md").read_bytes()).hexdigest()
```
Old launcher: `platform/api/clue_api/account_research_fleet_launch.py:159-190` `AccountResearchFleetLauncher.launch(request, *, actor,
source_action_ref, source_operation_id)`; job id `uuid5(_JOB_NAMESPACE, f"{research_run_id}:{account_id}")`; run id
`uuid5(_RUN_NAMESPACE, request_sha)`; it calls `record_run_lineage(conn, run_id=research_run_id, workspace_id=..., kind="entity_research",
project_id=..., project_run_id=...)` (:627-634). Old launch tool `entity_research_launch_tools.py:83` `LaunchAccountResearchInput(project_run_id,
research_directive_id, account_entity_ids (1..500), approved_budget_cap_cents, expected_estimated_cost_cents, concurrency_limit)`.

## 2. `project_run`
`subsystems/research/clue_research/durable/project_run.py:142-160`:
```python
async def ensure_project_run(conn, *, project_run_id: ProjectRunId, project_id: str, workspace_id: str, icp_key: str,
    icp_version: int, budget_cap_cents=None, tier_cutoffs=None, phase: ProjectPhase = ProjectPhase.REVERSE_PROFILING,
    status: ProjectRunStatus = ProjectRunStatus.ACTIVE, client_entity_id=None, client_kb_version=None, product_id=None,
    product_context_version_id=None, readiness_decision_id=None) -> None
```
INSERT selects `brand_id`/`workspace_id` FROM `project` (:112-129); `ON CONFLICT (id) DO NOTHING`. Stage-0 pin block is
all-or-nothing (`project_run_stage0_pins_complete`, `1b71451d48cd:511-536`); ARV2 leaves it all NULL (loader does).
`ProjectRunRow` (:43-67): id, project_id, brand_id, workspace_id, icp_key, icp_version, phase, status, budget_cap_cents,
spent_cents, tier_cutoffs, …, product_id=None, … .

## 3. Answer-key loader run + lineage — `platform/api/clue_api/arv2/answer_key_loader.py:154-181`
```python
await ensure_project_run(conn, project_run_id=manifest.project_run_id, project_id=manifest.project_id,
    workspace_id=manifest.workspace_id, icp_key=manifest.icp_key, icp_version=1, phase=ProjectPhase.DEEP)
selection_version = await _confirm_product_set(conn, manifest, product_id)
for run_id, kind in ((manifest.run_id, "entity_research"), (PEOPLE_RUN_ID, "contact_research")):
    await record_run_lineage(conn, run_id=run_id, workspace_id=manifest.workspace_id, kind=kind,
                             project_id=manifest.project_id, project_run_id=manifest.project_run_id)
```
`record_run_lineage(conn, *, run_id: UUID, workspace_id: str, kind: str, project_id: str | None = None,
project_run_id: UUID | None = None, created_at=None) -> None` (`clue_research/claimstore/run_lineage.py:82-91`);
`ON CONFLICT (run_id) DO NOTHING`; `RUN_LINEAGE_KINDS` :42-55 includes `entity_research`, `contact_research`.
Table `run_lineage(run_id PK, workspace_id, project_id, project_run_id FK project_run(id), kind CHECK, created_at)`.
`LoadReport` (:116-131) carries `product_selection_version` in memory only. ICP path `audience/icp-clue-abm-buyers.md`,
kind `icp-definition`; `manifest.icp_key = "clue-abm-buyers"`.

## 4. Product set (O1) — `libs/clue-spine/clue_spine/spine.py`
```python
class ProjectProductSet(BaseModel):  # :348
    workspace_id: str; project_id: str; brand_id: str; selection_version: int; product_ids: tuple[str, ...]
    gate_id: UUID; confirmed_by_user_id: str; confirmed_at: UtcDatetime
async def current_project_product_set(conn, *, workspace_id: str, project_id: str) -> ProjectProductSet | None  # :403
async def list_project_product_sets(conn, *, workspace_id, project_id) -> list[ProjectProductSet]        # :387
async def confirm_project_product_set(conn, *, workspace_id, project_id, product_ids, gate_id, confirmed_by_user_id) -> ProjectProductSet | None  # :410
```
Table `project_product (workspace_id, project_id, brand_id, product_id, selection_version >= 1, gate_id (not FK),
confirmed_by_user_id FK platform_user, confirmed_at)`; append-only trigger.

## 5. Account entities — `subsystems/research/clue_research/identity/entities.py:151-187`
```python
async def insert_account_entity(conn, *, canonical_name: str, primary_domain: str | None = None, aliases=(),
    hq_geo=None, registry_ids=None, status: AccountStatus = AccountStatus.CANDIDATE, workspace_id: str) -> EntityId
```
Workspace-scoped strong keys; composite anchor `account_entity (id, workspace_id)`. Loader then calls
`ensure_project_account(conn, workspace_id=…, project_id=…, account_entity_id=…, added_via="manual")` (:328-352).
