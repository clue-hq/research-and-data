# ARV2 Onboarding O3 — Research Steps on the Fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /onboarding` enqueues one `onboarding_run` fleet job; the fleet driver runs the fast recon (company overview ∥ product lineup ∥ customer reviews), synchronizes the lineup into product rows, persists every result as a markdown artifact with a `brand_knowledge_document` row whose status the page can show progressively, fans out one per-product research run in the background under a concurrency cap, and records every provider call on the ledger — never raising, never blocking the web loop.

**Architecture:** One new fleet task kind (`onboarding_run`) handled by `OnboardingRunWorkHandler` in `platform/api/clue_api/arv2/onboarding_driver.py`. Pure DB access lives in `arv2/onboarding_store.py`; the lineup → product rows step lives in `arv2/onboarding_lineage.py` over a new artifact-keyed lineage table (the existing `product_catalog_lineage` is claim-keyed and stays untouched). Two seams are injected at composition because the ARV2 import guard forbids `arv2/` from importing the old Stage-0 code: a `ClientEntityBinder` (implemented in `clue_api/onboarding_client_binding.py`) and a `SynthesisLauncher` (O4 supplies it; until then the synthesis step ends `empty`). Every Exa call goes through R1's `ProviderCaller` inside `asyncio.to_thread`, one caller per step. The route lives in `clue_api/onboarding_routes.py`, mounted behind `settings.onboarding_v2_enabled`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + `text()` SQL, Alembic, `clue_fleet` leased work worker, `clue_storage` artifacts, R1 `clue_api.arv2` clients, pytest with the `rollback_conn` harness.

**Spec:** `docs/specs/ARV2-ONBOARDING-PLAN.md` §2 (architecture), §3 (state contract, failure law, write order), §4 (the calls), §7 (the status read), §9 O3 row, §10 (flags), §11 (standing rule); `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §4–§5; `platform/api/clue_api/arv2/README.md` "R2 composition constraints". Facts file: `.superpowers/sdd/o3o4-facts/o3-driver-facts.md` (exact signatures; read it before any task).

## Global Constraints

- **Failure law (spec §3):** every provider error, timeout, schema rejection or empty result is recorded on the step (`failed` with a code, or `empty`) and the run continues; `completed_with_gaps` is the honest terminal; nothing raises out of `handle` (the design handler's containment lesson: a raise marks only the fleet task, never the domain rows).
- **Never on the web loop:** the route only inserts a row and enqueues. Every `ProviderCaller.call` runs inside `asyncio.to_thread`. **One `ProviderCaller` per step** (its totals and halt latch are unlocked mutable state), each with its own raw-sink directory and ledger file under `arv2_raw_root/onboarding/<run_id>/<step>/`.
- **Money:** effort per call from the O1 settings (`onboarding_overview_effort` etc.); record, never cap; ledger rows from `CallCost`. Live tests: never a full-suite run with keys; the single acceptance run (Task 7) is founder-triggered.
- **Standing rule (catalog contract §10):** no Client-KB version, readiness decision or Stage-0 run pin on any path. The catalog becomes product rows through the NEW artifact-keyed lineage table; the old claim-keyed synchronizer is not called.
- **Import guard:** `clue_api.arv2` may import only `clue_api.arv2`, `clue_core`, `clue_config`, `clue_obs`, `clue_storage`, `clue_db`, `clue_gateway`, `clue_locks`, `clue_spine`, `clue_toolbelt`, `clue_fleet`, `clue_agents`, `clue_execution`, `clue_auth`, `clue_projections`, `clue_research.claimstore`, and no provider SDK (`tests/arv2/test_import_guard.py`). Anything needing `clue_research.stage0` or `clue_api.<other>` is injected through a protocol implemented outside `arv2/`.
- **O1 tables are exact** (facts §9): columns `requested_by_user_id`, `raw_artifact_key`, `output_document_id`; `*_finished_when_terminal` CHECKs are biconditional (status and `finished_at` change in the same UPDATE); an `empty` step has `failure_code IS NULL`; the step ↔ document FK cycle is written step → document → UPDATE step.
- **Alembic:** hash ids via `uv run alembic revision -m ...`; `down_revision` = the single current head (`3742d1281a10`, the O1+D1 join revision, after the 2026-09-07 merge of D1); reversible; `make db-smoke` on the throwaway `clue_o1_substrate` only (empty it first: `uv run alembic downgrade base` is not enough when residue exists — `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` then `upgrade head`).
- **Tests:** offline suites via `uv run pytest tests/arv2 --ignore-glob='*_live.py'` plus the named DB suites with the env sourced (`set -a; source .env; set +a`); DB tests use `rollback_conn` + `conn_session_factory`. Provider behaviour is not faked; the driver's sequencing is tested with an in-memory `ExaClient` double (client logic, not provider behaviour).
- **Commits:** local only, never push; no AI attribution; one commit per task with the message given.

---

## File Structure

| Path | Responsibility |
|---|---|
| `platform/fleet/clue_fleet/enums.py` | **Modify.** Append `ONBOARDING_RUN = "onboarding_run"`. |
| `alembic/versions/<hash>_arv2_onboarding_run_kind_and_lineage.py` | **Create.** `ALTER TYPE fleet_task_kind ADD VALUE 'onboarding_run'` + the `onboarding_product_lineage` table. |
| `platform/api/clue_api/fleet_wiring.py` | **Modify.** `onboarding_handler` kwarg + guard in `build_multi_work_worker`. |
| `platform/api/clue_api/arv2/onboarding_store.py` | **Create.** The run/step/document rows: create run, start/finish step, open/publish/fail document, finish run, read status. Pure SQL, one function per transition. |
| `platform/api/clue_api/arv2/onboarding_lineage.py` | **Create.** `OnboardingCatalogSynchronizer`: catalog document entries → product rows + `onboarding_product_lineage` rows. |
| `platform/api/clue_api/arv2/onboarding_driver.py` | **Create.** `OnboardingRunWorkHandler`, the step runners, the seams, `build_onboarding_provider_caller`. |
| `platform/api/clue_api/onboarding_client_binding.py` | **Create.** `ClientEntityBinder` implementation over the existing Stage-0 client resolution (outside `arv2/`). |
| `platform/api/clue_api/onboarding_routes.py` | **Create.** `create_onboarding_router` (`POST /onboarding`, `GET /onboarding/current`) + `DbOnboardingEnqueuer`. |
| `platform/api/clue_api/projections_app.py` | **Modify.** Mount the router behind `onboarding_v2_enabled`. |
| `platform/api/clue_api/fleet_main.py` | **Modify.** Build the handler behind `onboarding_v2_enabled`. |
| `platform/api/clue_api/arv2/README.md` | **Modify.** Document the driver, the seams, the per-step caller rule. |
| `tests/fleet/test_fleet_db.py` | (unchanged; the parity test must stay green) |
| `tests/api/test_fleet_wiring.py` | **Modify.** Composition test for the new kwarg. |
| `tests/arv2/test_onboarding_store_db.py`, `tests/arv2/test_onboarding_lineage_db.py`, `tests/arv2/test_onboarding_driver.py`, `tests/arv2/test_onboarding_driver_db.py`, `tests/api/test_onboarding_routes_db.py`, `tests/db/test_arv2_onboarding_kind_migration.py` | **Create.** |

---

### Task 1: The fleet kind, its migration, and the lineage table

**Files:**
- Modify: `platform/fleet/clue_fleet/enums.py` (append to `FleetTaskKind`)
- Create: `alembic/versions/<hash>_arv2_onboarding_run_kind_and_lineage.py`
- Modify: `platform/api/clue_api/fleet_wiring.py:324-393`
- Test: `tests/db/test_arv2_onboarding_kind_migration.py`, `tests/api/test_fleet_wiring.py`

**Interfaces:**
- Produces: `FleetTaskKind.ONBOARDING_RUN`; table `onboarding_product_lineage`; `build_multi_work_worker(..., onboarding_handler: WorkHandler | None = None, ...)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/db/test_arv2_onboarding_kind_migration.py
"""The onboarding_run fleet kind and the artifact-keyed catalog lineage (O3 Task 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from clue_fleet import FleetTaskKind

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_the_fleet_kind_enum_has_onboarding_run_last_and_matches_the_db() -> None:
    async def scenario() -> list[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'fleet_task_kind' ORDER BY e.enumsortorder"
                )
            )
            return [str(r.enumlabel) for r in rows]

    labels = run_async(scenario())
    assert labels[-1] == "onboarding_run"
    assert labels == [k.value for k in FleetTaskKind]


@pytest.mark.usefixtures("require_db")
def test_the_onboarding_product_lineage_table_carries_its_contract() -> None:
    async def scenario() -> dict[str, str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conrelid = 'onboarding_product_lineage'::regclass"
                )
            )
            return {str(r.conname): str(r.definition) for r in rows}

    constraints = run_async(scenario())
    assert "brand_knowledge_document" in constraints["onboarding_product_lineage_document_fk"]
    assert "(document_id, entry_ordinal)" in constraints["onboarding_product_lineage_entry_unique"]
    for state in ("created", "alias_reused", "lineage_reused", "unresolved_ambiguous"):
        assert state in constraints["onboarding_product_lineage_state"]
    assert "product" in constraints["onboarding_product_lineage_product_fk"]
```

In `tests/api/test_fleet_wiring.py`, next to the existing optional-handler tests (~lines 155-260), add:

```python
def test_onboarding_handler_is_composed_when_given_and_kind_guarded() -> None:
    settings = load_settings()
    handler = _CompositionHandler(FleetTaskKind.ONBOARDING_RUN)
    worker = build_multi_work_worker(
        settings,
        driver=ScriptedDriver(),
        graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        onboarding_handler=handler,
        queue=_NullQueue(),
        leases=FakeLeaseStore(),
    )
    assert handler in worker._handlers
    with pytest.raises(ValueError, match="must own onboarding_run"):
        build_multi_work_worker(
            settings,
            driver=ScriptedDriver(),
            graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
            onboarding_handler=_CompositionHandler(FleetTaskKind.DESIGN_JOB),
            queue=_NullQueue(),
            leases=FakeLeaseStore(),
        )
```

Match the names the file already uses for its driver/queue/lease doubles (read the neighbouring `design_handler` test and copy its exact fixtures instead of `ScriptedDriver`/`_NullQueue` if they are named differently).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_onboarding_kind_migration.py tests/api/test_fleet_wiring.py -v`
Expected: FAIL — `AttributeError: ONBOARDING_RUN`, `TypeError: unexpected keyword argument 'onboarding_handler'`.

- [ ] **Step 3: Append the enum member**

In `platform/fleet/clue_fleet/enums.py`, after `DESIGN_JOB = "design_job"` inside `FleetTaskKind`:

```python
    # ARV2 onboarding (Track O, O3): one job per onboarding run — fast recon, catalog sync,
    # background per-product research. Appended, never inserted (see the class docstring).
    ONBOARDING_RUN = "onboarding_run"
```

- [ ] **Step 4: Cut the migration**

```bash
uv run alembic heads   # one line; note it
uv run alembic revision -m "arv2 onboarding run kind and lineage"
```

Body (copy the docstring conventions block from `fc3e5477e872`; use the generated id and the noted head):

```python
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<head>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_BEFORE = (
    "drive_run", "account_job", "execute_graph", "entity_research_job", "agent_turn",
    "stage0_recon", "official_site_crawl", "design_job",
)


def upgrade() -> None:
    # ADD VALUE is safe inside alembic's transaction because nothing here USES the label (PG16
    # forbids only the use, not the addition) — the be855c8f6993 precedent.
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'onboarding_run'")
    op.execute(
        """
        CREATE TABLE onboarding_product_lineage (
            lineage_id               uuid NOT NULL,
            workspace_id             text NOT NULL,
            brand_id                 text NOT NULL,
            document_id              uuid NOT NULL,
            entry_ordinal            integer NOT NULL,
            entry_fingerprint_sha256 text NOT NULL,
            product_id               text,
            resolution_state         text NOT NULL,
            candidate_count          integer NOT NULL DEFAULT 0,
            synchronized_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT onboarding_product_lineage_pkey PRIMARY KEY (lineage_id),
            CONSTRAINT onboarding_product_lineage_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT onboarding_product_lineage_document_fk FOREIGN KEY (document_id)
                REFERENCES brand_knowledge_document (document_id),
            CONSTRAINT onboarding_product_lineage_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT onboarding_product_lineage_entry_unique UNIQUE (document_id, entry_ordinal),
            CONSTRAINT onboarding_product_lineage_fingerprint CHECK
                (entry_fingerprint_sha256 ~ '^sha256:[0-9a-f]{64}$'),
            CONSTRAINT onboarding_product_lineage_state CHECK (
                (resolution_state IN ('created', 'alias_reused', 'lineage_reused')
                    AND product_id IS NOT NULL)
                OR (resolution_state = 'unresolved_ambiguous' AND product_id IS NULL)),
            CONSTRAINT onboarding_product_lineage_counts CHECK
                (entry_ordinal >= 0 AND candidate_count >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX onboarding_product_lineage_product "
        "ON onboarding_product_lineage (workspace_id, product_id) WHERE product_id IS NOT NULL"
    )
    op.execute(
        "CREATE TRIGGER onboarding_product_lineage_append_only "
        "BEFORE UPDATE OR DELETE ON onboarding_product_lineage FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER onboarding_product_lineage_append_only ON onboarding_product_lineage")
    op.execute("DROP INDEX onboarding_product_lineage_product")
    op.execute("DROP TABLE onboarding_product_lineage")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'onboarding_run') THEN
                RAISE EXCEPTION 'cannot downgrade O3 while onboarding_run fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_o3")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_o3")
```

Note: `product (product_id, workspace_id)` is a valid FK target (the existing `product_catalog_lineage_workspace_product_fk` references exactly that pair).

- [ ] **Step 5: Add the worker kwarg**

In `build_multi_work_worker` (`platform/api/clue_api/fleet_wiring.py`), add the parameter `onboarding_handler: WorkHandler | None = None,` after `design_handler`, the guard next to the design guard:

```python
    if onboarding_handler is not None and onboarding_handler.kind is not FleetTaskKind.ONBOARDING_RUN:
        raise ValueError("onboarding_handler must own onboarding_run tasks")
```

and the append after the design append:

```python
    if onboarding_handler is not None:
        handlers.append(onboarding_handler)
```

- [ ] **Step 6: Apply and run**

Run: `set -a; source .env; set +a; uv run alembic upgrade head && uv run pytest tests/db/test_arv2_onboarding_kind_migration.py tests/fleet/test_fleet_db.py tests/api/test_fleet_wiring.py tests/db/test_db_migrations.py -v`
Expected: PASS (empty the throwaway DB first if `test_db_migrations` trips on residue).

- [ ] **Step 7: Commit**

```bash
git add platform/fleet/clue_fleet/enums.py alembic/versions/*_arv2_onboarding_run_kind_and_lineage.py platform/api/clue_api/fleet_wiring.py tests/db/test_arv2_onboarding_kind_migration.py tests/api/test_fleet_wiring.py
git commit -m "feat(fleet,db): onboarding_run fleet kind + artifact-keyed onboarding_product_lineage table; build_multi_work_worker accepts the onboarding handler"
```

---

### Task 2: The onboarding store — one function per row transition

**Files:**
- Create: `platform/api/clue_api/arv2/onboarding_store.py`
- Test: `tests/arv2/test_onboarding_store_db.py`

**Interfaces:**
- Produces (all `async`, first arg `conn: AsyncConnection`):
  - `create_run(conn, *, run_id: UUID, workspace_id, brand_id, company_domain, requested_by_user_id) -> None` (status `queued`).
  - `mark_run_running(conn, *, run_id) -> None`.
  - `start_step(conn, *, step_id: UUID, run_id, workspace_id, kind: str, phase: str, subject_ref: str | None = None) -> None` (status `running`, `started_at = now()`; idempotent on the identity index via `ON CONFLICT DO NOTHING` + a follow-up UPDATE to `running` when it was `queued`).
  - `open_document(conn, *, document_id: UUID, workspace_id, brand_id, folder, path, kind, step_id) -> int` (inserts the next version as `running`, links `onboarding_step.output_document_id`, returns the version).
  - `publish_document(conn, *, document_id, artifact_key, artifact_sha256, status: str = "ready") -> None` (marks any previous `ready` version at the same path `superseded`, sets `supersedes_document_id`).
  - `fail_document(conn, *, document_id, status: Literal["empty", "failed"]) -> None`.
  - `finish_step(conn, *, step_id, status: Literal["completed", "empty", "failed"], provider_run_id=None, raw_artifact_key=None, cost_usd: Decimal = 0, searches: int = 0, failure_code=None, failure_message=None) -> None` (biconditional-safe: sets `finished_at = now()`; forces `failure_code=None` unless `failed`).
  - `finish_run(conn, *, run_id) -> str` (derives `completed` / `completed_with_gaps` from the steps, sums `cost_usd`, sets `finished_at`; returns the status).
  - `fail_run(conn, *, run_id) -> None` (the containment terminal).
  - `read_current_run(conn, *, workspace_id) -> RunStatus | None` — `RunStatus(run_id, status, cost_usd, steps: tuple[StepStatus, ...])`, `StepStatus(kind, subject_ref, phase, status, started_at, finished_at, cost_usd, failure_code)`; newest run by `requested_at`.
  - `list_documents(conn, *, workspace_id, brand_id) -> tuple[DocumentRow, ...]` (current version per path: `DocumentRow(document_id, folder, path, kind, version, status, artifact_key, artifact_sha256)`) — O5's read endpoint and O4's materialization read this.

- [ ] **Step 1: Write the failing tests**

```python
# tests/arv2/test_onboarding_store_db.py
"""Row transitions of the onboarding substrate, against the O1 CHECKs (spec §3)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from clue_api.arv2.onboarding_store import (
    create_run,
    fail_document,
    finish_run,
    finish_step,
    list_documents,
    mark_run_running,
    open_document,
    publish_document,
    read_current_run,
    start_step,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

USER = "usr_o3_store"
SHA = "a" * 64


async def _seed(conn, ws: str):
    project = await seed_project(conn, ws, name="O3 store")
    await seed_principal(conn, workspace_id=ws, user_id=USER)
    run_id = uuid4()
    await create_run(
        conn, run_id=run_id, workspace_id=ws, brand_id=project.brand_id,
        company_domain="insighthealth.ai", requested_by_user_id=USER,
    )
    return project.brand_id, run_id


def test_a_run_walks_queued_running_completed_and_sums_step_costs() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-ok"
            brand_id, run_id = await _seed(conn, ws)
            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None and status.status == "queued" and status.steps == ()
            await mark_run_running(conn, run_id=run_id)

            step = uuid4()
            await start_step(conn, step_id=step, run_id=run_id, workspace_id=ws, kind="overview", phase="fast")
            doc = uuid4()
            version = await open_document(
                conn, document_id=doc, workspace_id=ws, brand_id=brand_id, folder="company",
                path="company/overview.md", kind="company-overview", step_id=step,
            )
            assert version == 1
            await publish_document(conn, document_id=doc, artifact_key=f"{ws}/{SHA}", artifact_sha256=SHA)
            await finish_step(
                conn, step_id=step, status="completed", provider_run_id="agent_run_x",
                raw_artifact_key="raw/1", cost_usd=Decimal("0.5"), searches=60,
            )
            assert await finish_run(conn, run_id=run_id) == "completed"

            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None and status.status == "completed"
            assert status.cost_usd == Decimal("0.5")
            (only,) = status.steps
            assert (only.kind, only.status, only.failure_code) == ("overview", "completed", None)
            assert only.finished_at is not None

            (row,) = await list_documents(conn, workspace_id=ws, brand_id=brand_id)
            assert (row.path, row.version, row.status, row.artifact_sha256) == (
                "company/overview.md", 1, "ready", SHA
            )

    run_async(scenario())


def test_empty_and_failed_steps_make_the_run_completed_with_gaps() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-gaps"
            brand_id, run_id = await _seed(conn, ws)
            await mark_run_running(conn, run_id=run_id)
            s1, s2, s3 = uuid4(), uuid4(), uuid4()
            await start_step(conn, step_id=s1, run_id=run_id, workspace_id=ws, kind="overview", phase="fast")
            await start_step(conn, step_id=s2, run_id=run_id, workspace_id=ws, kind="reviews", phase="fast")
            await start_step(
                conn, step_id=s3, run_id=run_id, workspace_id=ws, kind="product_research",
                phase="background", subject_ref="prd_a",
            )
            d2 = uuid4()
            await open_document(
                conn, document_id=d2, workspace_id=ws, brand_id=brand_id, folder="proof",
                path="proof/customer-reviews.md", kind="customer-reviews", step_id=s2,
            )
            await finish_step(conn, step_id=s1, status="completed", cost_usd=Decimal("0.5"))
            # empty: the CHECK forbids a failure_code; the reason rides failure_message only
            await finish_step(conn, step_id=s2, status="empty", failure_code="ignored",
                              failure_message="no reviews found")
            await fail_document(conn, document_id=d2, status="empty")
            await finish_step(conn, step_id=s3, status="failed", failure_code="timeout",
                              failure_message="run not terminal after 900s")
            assert await finish_run(conn, run_id=run_id) == "completed_with_gaps"
            status = await read_current_run(conn, workspace_id=ws)
            by_kind = {s.kind: s for s in status.steps}
            assert by_kind["reviews"].failure_code is None
            assert by_kind["product_research"].failure_code == "timeout"
            assert by_kind["product_research"].subject_ref == "prd_a"

    run_async(scenario())


def test_publishing_a_second_version_supersedes_the_first() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-v2"
            brand_id, run_id = await _seed(conn, ws)
            await mark_run_running(conn, run_id=run_id)
            first_step, second_step = uuid4(), uuid4()
            await start_step(conn, step_id=first_step, run_id=run_id, workspace_id=ws, kind="overview", phase="fast")
            d1 = uuid4()
            assert await open_document(
                conn, document_id=d1, workspace_id=ws, brand_id=brand_id, folder="company",
                path="company/overview.md", kind="company-overview", step_id=first_step,
            ) == 1
            await publish_document(conn, document_id=d1, artifact_key=f"{ws}/{SHA}", artifact_sha256=SHA)
            await finish_step(conn, step_id=first_step, status="completed")

            await start_step(conn, step_id=second_step, run_id=run_id, workspace_id=ws, kind="lineup", phase="fast")
            d2 = uuid4()
            assert await open_document(
                conn, document_id=d2, workspace_id=ws, brand_id=brand_id, folder="company",
                path="company/overview.md", kind="company-overview", step_id=second_step,
            ) == 2
            await publish_document(conn, document_id=d2, artifact_key=f"{ws}/{'b' * 64}", artifact_sha256="b" * 64)
            rows = {r.version: r for r in await list_documents(conn, workspace_id=ws, brand_id=brand_id, all_versions=True)}
            assert rows[1].status == "superseded" and rows[2].status == "ready"
            (current,) = await list_documents(conn, workspace_id=ws, brand_id=brand_id)
            assert current.version == 2

    run_async(scenario())


def test_a_step_identity_cannot_repeat_within_a_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-dup"
            _, run_id = await _seed(conn, ws)
            await start_step(conn, step_id=uuid4(), run_id=run_id, workspace_id=ws, kind="overview", phase="fast")
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await start_step(conn, step_id=uuid4(), run_id=run_id, workspace_id=ws, kind="overview", phase="fast")

    run_async(scenario())
```

`list_documents` therefore takes an optional `all_versions: bool = False`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_onboarding_store_db.py -v`
Expected: FAIL — `ModuleNotFoundError: clue_api.arv2.onboarding_store`.

- [ ] **Step 3: Write the module**

```python
# platform/api/clue_api/arv2/onboarding_store.py
"""Row transitions of the onboarding substrate (O1 tables; ARV2-ONBOARDING-PLAN.md §3).

One function per transition, each honouring the CHECKs the migration installed:
``*_finished_when_terminal`` is biconditional (status and ``finished_at`` move together),
``onboarding_step_failure_pair`` allows a ``failure_code`` only on ``failed``, and the step ↔
document FK cycle is written step → document → UPDATE step. Nothing here calls a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "DocumentRow", "RunStatus", "StepStatus", "create_run", "fail_document", "fail_run",
    "finish_run", "finish_step", "list_documents", "mark_run_running", "open_document",
    "publish_document", "read_current_run", "start_step",
]

TerminalStep = Literal["completed", "empty", "failed"]


@dataclass(frozen=True)
class StepStatus:
    kind: str
    subject_ref: str | None
    phase: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    cost_usd: Decimal
    failure_code: str | None


@dataclass(frozen=True)
class RunStatus:
    run_id: UUID
    status: str
    cost_usd: Decimal
    steps: tuple[StepStatus, ...]


@dataclass(frozen=True)
class DocumentRow:
    document_id: UUID
    folder: str
    path: str
    kind: str
    version: int
    status: str
    artifact_key: str | None
    artifact_sha256: str | None


async def create_run(
    conn: AsyncConnection, *, run_id: UUID, workspace_id: str, brand_id: str,
    company_domain: str, requested_by_user_id: str,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain, "
            " requested_by_user_id) VALUES (:run_id, :workspace_id, :brand_id, :domain, :user_id) "
            "ON CONFLICT (run_id) DO NOTHING"
        ),
        {"run_id": run_id, "workspace_id": workspace_id, "brand_id": brand_id,
         "domain": company_domain.strip(), "user_id": requested_by_user_id},
    )


async def mark_run_running(conn: AsyncConnection, *, run_id: UUID) -> None:
    await conn.execute(
        text("UPDATE onboarding_run SET status = 'running' WHERE run_id = :run_id AND status = 'queued'"),
        {"run_id": run_id},
    )


async def start_step(
    conn: AsyncConnection, *, step_id: UUID, run_id: UUID, workspace_id: str, kind: str,
    phase: str, subject_ref: str | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO onboarding_step (step_id, run_id, workspace_id, kind, subject_ref, phase, "
            " status, started_at) VALUES (:step_id, :run_id, :workspace_id, :kind, :subject_ref, "
            " :phase, 'running', now())"
        ),
        {"step_id": step_id, "run_id": run_id, "workspace_id": workspace_id, "kind": kind,
         "subject_ref": subject_ref, "phase": phase},
    )


async def open_document(
    conn: AsyncConnection, *, document_id: UUID, workspace_id: str, brand_id: str, folder: str,
    path: str, kind: str, step_id: UUID,
) -> int:
    version = int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM brand_knowledge_document "
                    "WHERE workspace_id = :ws AND brand_id = :brand AND path = :path"
                ),
                {"ws": workspace_id, "brand": brand_id, "path": path},
            )
        ).scalar_one()
    )
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            " path, kind, version, status, produced_by_step_id) VALUES (:id, :ws, :brand, :folder, "
            " :path, :kind, :version, 'running', :step_id)"
        ),
        {"id": document_id, "ws": workspace_id, "brand": brand_id, "folder": folder, "path": path,
         "kind": kind, "version": version, "step_id": step_id},
    )
    await conn.execute(
        text("UPDATE onboarding_step SET output_document_id = :doc WHERE step_id = :step_id"),
        {"doc": document_id, "step_id": step_id},
    )
    return version


async def publish_document(
    conn: AsyncConnection, *, document_id: UUID, artifact_key: str, artifact_sha256: str,
    status: str = "ready",
) -> None:
    row = (
        await conn.execute(
            text("SELECT workspace_id, brand_id, path, version FROM brand_knowledge_document WHERE document_id = :id"),
            {"id": document_id},
        )
    ).mappings().one()
    previous = (
        await conn.execute(
            text(
                "SELECT document_id FROM brand_knowledge_document WHERE workspace_id = :ws "
                "AND brand_id = :brand AND path = :path AND version < :version "
                "AND status IN ('ready', 'proposed', 'confirmed') ORDER BY version DESC LIMIT 1"
            ),
            {"ws": row["workspace_id"], "brand": row["brand_id"], "path": row["path"], "version": row["version"]},
        )
    ).scalar_one_or_none()
    await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = :status, artifact_key = :key, "
            " artifact_sha256 = :sha, supersedes_document_id = :prev, updated_at = now() "
            "WHERE document_id = :id"
        ),
        {"status": status, "key": artifact_key, "sha": artifact_sha256, "prev": previous, "id": document_id},
    )
    if previous is not None:
        await conn.execute(
            text("UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() WHERE document_id = :id"),
            {"id": previous},
        )


async def fail_document(conn: AsyncConnection, *, document_id: UUID, status: Literal["empty", "failed"]) -> None:
    await conn.execute(
        text("UPDATE brand_knowledge_document SET status = :status, updated_at = now() WHERE document_id = :id"),
        {"status": status, "id": document_id},
    )


async def finish_step(
    conn: AsyncConnection, *, step_id: UUID, status: TerminalStep, provider_run_id: str | None = None,
    raw_artifact_key: str | None = None, cost_usd: Decimal = Decimal(0), searches: int = 0,
    failure_code: str | None = None, failure_message: str | None = None,
) -> None:
    await conn.execute(
        text(
            "UPDATE onboarding_step SET status = :status, finished_at = now(), "
            " provider_run_id = :provider_run_id, raw_artifact_key = :raw, cost_usd = :cost, "
            " searches = :searches, failure_code = :code, failure_message = :message "
            "WHERE step_id = :step_id"
        ),
        {"status": status, "provider_run_id": provider_run_id, "raw": raw_artifact_key,
         "cost": cost_usd, "searches": int(searches),
         "code": failure_code if status == "failed" else None,
         "message": failure_message, "step_id": step_id},
    )


async def finish_run(conn: AsyncConnection, *, run_id: UUID) -> str:
    row = (
        await conn.execute(
            text(
                "SELECT COALESCE(SUM(cost_usd), 0) AS cost, "
                " bool_or(status IN ('empty', 'failed')) AS gaps FROM onboarding_step WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        )
    ).mappings().one()
    status = "completed_with_gaps" if row["gaps"] else "completed"
    await conn.execute(
        text(
            "UPDATE onboarding_run SET status = :status, cost_usd = :cost, finished_at = now() "
            "WHERE run_id = :run_id"
        ),
        {"status": status, "cost": row["cost"], "run_id": run_id},
    )
    return status


async def fail_run(conn: AsyncConnection, *, run_id: UUID) -> None:
    await conn.execute(
        text("UPDATE onboarding_run SET status = 'failed', finished_at = now() WHERE run_id = :run_id AND finished_at IS NULL"),
        {"run_id": run_id},
    )


async def read_current_run(conn: AsyncConnection, *, workspace_id: str) -> RunStatus | None:
    run = (
        await conn.execute(
            text(
                "SELECT run_id, status, cost_usd FROM onboarding_run WHERE workspace_id = :ws "
                "ORDER BY requested_at DESC LIMIT 1"
            ),
            {"ws": workspace_id},
        )
    ).mappings().first()
    if run is None:
        return None
    steps = (
        await conn.execute(
            text(
                "SELECT kind, subject_ref, phase, status, started_at, finished_at, cost_usd, failure_code "
                "FROM onboarding_step WHERE run_id = :run_id ORDER BY started_at NULLS LAST, kind, subject_ref"
            ),
            {"run_id": run["run_id"]},
        )
    ).mappings().all()
    return RunStatus(
        run_id=run["run_id"], status=str(run["status"]), cost_usd=Decimal(run["cost_usd"]),
        steps=tuple(
            StepStatus(kind=s["kind"], subject_ref=s["subject_ref"], phase=s["phase"], status=s["status"],
                       started_at=s["started_at"], finished_at=s["finished_at"],
                       cost_usd=Decimal(s["cost_usd"]), failure_code=s["failure_code"])
            for s in steps
        ),
    )


async def list_documents(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, all_versions: bool = False
) -> tuple[DocumentRow, ...]:
    where = "" if all_versions else (
        " AND version = (SELECT MAX(d2.version) FROM brand_knowledge_document d2 "
        " WHERE d2.workspace_id = d.workspace_id AND d2.brand_id = d.brand_id AND d2.path = d.path)"
    )
    rows = (
        await conn.execute(
            text(
                "SELECT document_id, folder, path, kind, version, status, artifact_key, artifact_sha256 "
                f"FROM brand_knowledge_document d WHERE workspace_id = :ws AND brand_id = :brand{where} "
                "ORDER BY folder, path, version"
            ),
            {"ws": workspace_id, "brand": brand_id},
        )
    ).mappings().all()
    return tuple(
        DocumentRow(document_id=r["document_id"], folder=r["folder"], path=r["path"], kind=r["kind"],
                    version=int(r["version"]), status=r["status"], artifact_key=r["artifact_key"],
                    artifact_sha256=r["artifact_sha256"])
        for r in rows
    )
```

- [ ] **Step 4: Run the tests**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_onboarding_store_db.py -v && uv run ruff check platform/api/clue_api/arv2 tests/arv2 && uv run ruff format --check platform/api/clue_api/arv2 tests/arv2`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/onboarding_store.py tests/arv2/test_onboarding_store_db.py
git commit -m "feat(arv2): onboarding store — run/step/document transitions honouring the O1 CHECKs; current-run status and current-document listing"
```

---

### Task 3: The lineup → product rows synchronizer over the artifact-keyed lineage

**Files:**
- Create: `platform/api/clue_api/arv2/onboarding_lineage.py`
- Test: `tests/arv2/test_onboarding_lineage_db.py`

**Interfaces:**
- Produces: `CatalogProduct(name, short_description, aliases: tuple[str, ...])` (frozen dataclass, built from a catalog document's front matter `products[]`), `ProductLink(product_id: str | None, name, resolution_state, candidate_count, lineage_id)`, and `async def synchronize_catalog(conn, *, workspace_id, brand_id, document_id: UUID, products: Sequence[CatalogProduct]) -> tuple[ProductLink, ...]`. The driver calls it after the lineup document is published; the per-product fan-out iterates the links with a `product_id`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/arv2/test_onboarding_lineage_db.py
"""Lineup entries → product rows through the artifact-keyed lineage (catalog contract §5)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.onboarding_lineage import CatalogProduct, synchronize_catalog
from clue_api.arv2.onboarding_store import create_run, mark_run_running, open_document, start_step
from clue_spine import create_product, list_products
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")
USER = "usr_o3_lineage"


async def _catalog_document(conn, ws: str):
    project = await seed_project(conn, ws, name="O3 lineage")
    await seed_principal(conn, workspace_id=ws, user_id=USER)
    run_id, step_id, doc_id = uuid4(), uuid4(), uuid4()
    await create_run(conn, run_id=run_id, workspace_id=ws, brand_id=project.brand_id,
                     company_domain="insighthealth.ai", requested_by_user_id=USER)
    await mark_run_running(conn, run_id=run_id)
    await start_step(conn, step_id=step_id, run_id=run_id, workspace_id=ws, kind="lineup", phase="fast")
    await open_document(conn, document_id=doc_id, workspace_id=ws, brand_id=project.brand_id,
                        folder="product", path="product/catalog.md", kind="product-catalog", step_id=step_id)
    return project.brand_id, doc_id


def test_new_entries_create_products_and_lineage_and_replay_reuses_them() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-new"
            brand_id, doc_id = await _catalog_document(conn, ws)
            entries = [
                CatalogProduct(name="Aura AI Scribe", short_description="Ambient documentation.", aliases=()),
                CatalogProduct(name="MagicFlow", short_description="Workflow orchestration.", aliases=()),
            ]
            links = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries)
            assert [l.resolution_state for l in links] == ["created", "created"]
            assert all(l.product_id and l.product_id.startswith("prd_") for l in links)
            assert {p.name for p in await list_products(conn, brand_id)} == {"Aura AI Scribe", "MagicFlow"}

            again = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries)
            assert [l.resolution_state for l in again] == ["lineage_reused", "lineage_reused"]
            assert [l.product_id for l in again] == [l.product_id for l in links]
            count = (await conn.execute(
                text("SELECT count(*) FROM onboarding_product_lineage WHERE document_id = :d"), {"d": doc_id}
            )).scalar_one()
            assert count == 2

    run_async(scenario())


def test_an_existing_product_with_a_matching_alias_or_name_is_reused_and_ambiguity_is_left_open() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-alias"
            brand_id, doc_id = await _catalog_document(conn, ws)
            existing = await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Aura", aliases=("Aura AI Scribe",))
            await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Phone Triage", aliases=("Triage",))
            await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Triage Agent", aliases=("Triage",))
            links = await synchronize_catalog(
                conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id,
                products=[
                    CatalogProduct(name="Aura AI Scribe", short_description="x", aliases=()),
                    CatalogProduct(name="Triage", short_description="y", aliases=()),
                ],
            )
            assert (links[0].resolution_state, links[0].product_id) == ("alias_reused", existing.product_id)
            assert (links[1].resolution_state, links[1].product_id, links[1].candidate_count) == ("unresolved_ambiguous", None, 2)

    run_async(scenario())


def test_a_second_document_creates_its_own_lineage_but_reuses_products_by_name() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-v2"
            brand_id, doc1 = await _catalog_document(conn, ws)
            first = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc1,
                                              products=[CatalogProduct("MagicFlow", "Orchestration.", ())])
            doc2 = uuid4()
            step2 = uuid4()
            run_id = (await conn.execute(text("SELECT run_id FROM onboarding_run WHERE workspace_id = :ws"), {"ws": ws})).scalar_one()
            await start_step(conn, step_id=step2, run_id=run_id, workspace_id=ws, kind="reviews", phase="fast")
            await open_document(conn, document_id=doc2, workspace_id=ws, brand_id=brand_id, folder="product",
                                path="product/catalog.md", kind="product-catalog", step_id=step2)
            second = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc2,
                                               products=[CatalogProduct("MagicFlow", "Orchestration, revised.", ())])
            assert second[0].product_id == first[0].product_id
            assert second[0].resolution_state == "alias_reused"

    run_async(scenario())
```

- [ ] **Step 2: Run to verify failure**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_onboarding_lineage_db.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

```python
# platform/api/clue_api/arv2/onboarding_lineage.py
"""Lineup entries → spine product rows, with artifact-keyed lineage.

A port of the S5-B resolution ladder (exact-fingerprint lineage reuse → single alias/name hit →
ambiguity left open → mint) onto ``onboarding_product_lineage``, keyed on the catalog DOCUMENT
rather than a Client-KB claim (standing rule, catalog contract §10). Name normalization is a
comparison aid, never a merge key by itself; nothing here renames, merges or archives a product.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import Product, list_products

__all__ = ["CatalogProduct", "ProductLink", "normalize_identity", "synchronize_catalog"]

POLICY_VERSION = "onboarding-catalog-sync-v1"


@dataclass(frozen=True)
class CatalogProduct:
    name: str
    short_description: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductLink:
    product_id: str | None
    name: str
    resolution_state: str
    candidate_count: int
    lineage_id: UUID


def normalize_identity(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _fingerprint(entry: CatalogProduct) -> str:
    payload = {"name": entry.name, "short_description": entry.short_description,
               "aliases": list(entry.aliases), "policy": POLICY_VERSION}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _candidates(entry: CatalogProduct, products: Sequence[Product]) -> list[Product]:
    observed = {normalize_identity(entry.name)} | {normalize_identity(a) for a in entry.aliases}
    hits: list[Product] = []
    for product in products:
        names = {normalize_identity(product.name)} | {normalize_identity(a) for a in product.aliases if a.strip()}
        if observed & names:
            hits.append(product)
    return hits


async def _prior_product_id(conn: AsyncConnection, *, workspace_id: str, brand_id: str, fingerprint: str) -> str | None:
    return (
        await conn.execute(
            text(
                "SELECT product_id FROM onboarding_product_lineage WHERE workspace_id = :ws AND brand_id = :brand "
                "AND entry_fingerprint_sha256 = :fp AND product_id IS NOT NULL ORDER BY synchronized_at DESC LIMIT 1"
            ),
            {"ws": workspace_id, "brand": brand_id, "fp": fingerprint},
        )
    ).scalar_one_or_none()


async def synchronize_catalog(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, document_id: UUID,
    products: Sequence[CatalogProduct],
) -> tuple[ProductLink, ...]:
    existing = await list_products(conn, brand_id)
    if any(p.workspace_id != workspace_id for p in existing):
        raise ValueError("catalog brand crossed its workspace")
    links: list[ProductLink] = []
    for ordinal, entry in enumerate(products):
        fingerprint = _fingerprint(entry)
        lineage_id = uuid5(NAMESPACE_URL, f"onboarding-product-lineage:{document_id}:{ordinal}")
        already = (
            await conn.execute(
                text("SELECT product_id, resolution_state, candidate_count FROM onboarding_product_lineage WHERE lineage_id = :id"),
                {"id": lineage_id},
            )
        ).mappings().first()
        if already is not None:
            links.append(ProductLink(already["product_id"], entry.name, already["resolution_state"],
                                     int(already["candidate_count"]), lineage_id))
            continue
        product_id: str | None
        prior = await _prior_product_id(conn, workspace_id=workspace_id, brand_id=brand_id, fingerprint=fingerprint)
        if prior is not None and any(p.product_id == prior for p in existing):
            product_id, state, count = prior, "lineage_reused", 1
        else:
            hits = _candidates(entry, existing)
            if len(hits) == 1:
                product_id, state, count = hits[0].product_id, "alias_reused", 1
            elif hits:
                product_id, state, count = None, "unresolved_ambiguous", len({h.product_id for h in hits})
            else:
                product_id = f"prd_{uuid5(NAMESPACE_URL, f'onboarding-catalog:{workspace_id}:{brand_id}:{document_id}:{ordinal}:{fingerprint}').hex}"
                await conn.execute(
                    text(
                        "INSERT INTO product (product_id, brand_id, workspace_id, name, aliases) "
                        "VALUES (:product_id, :brand_id, :workspace_id, :name, CAST(:aliases AS jsonb)) "
                        "ON CONFLICT (product_id) DO NOTHING"
                    ),
                    {"product_id": product_id, "brand_id": brand_id, "workspace_id": workspace_id,
                     "name": entry.name, "aliases": json.dumps(list(entry.aliases))},
                )
                state, count = "created", 0
                existing = await list_products(conn, brand_id)
        await conn.execute(
            text(
                "INSERT INTO onboarding_product_lineage (lineage_id, workspace_id, brand_id, document_id, "
                " entry_ordinal, entry_fingerprint_sha256, product_id, resolution_state, candidate_count) "
                "VALUES (:id, :ws, :brand, :doc, :ordinal, :fp, :product_id, :state, :count) "
                "ON CONFLICT (document_id, entry_ordinal) DO NOTHING"
            ),
            {"id": lineage_id, "ws": workspace_id, "brand": brand_id, "doc": document_id, "ordinal": ordinal,
             "fp": fingerprint, "product_id": product_id, "state": state, "count": count},
        )
        links.append(ProductLink(product_id, entry.name, state, count, lineage_id))
    return tuple(links)
```

Note the `product_name_per_brand` unique constraint: when a same-named product exists it is found by `_candidates` (name match), so the mint path never collides.

- [ ] **Step 4: Run, ruff, commit**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_onboarding_lineage_db.py -v && uv run ruff check platform/api/clue_api/arv2 tests/arv2 && uv run ruff format --check platform/api/clue_api/arv2 tests/arv2`

```bash
git add platform/api/clue_api/arv2/onboarding_lineage.py tests/arv2/test_onboarding_lineage_db.py
git commit -m "feat(arv2): onboarding catalog synchronizer — lineup entries to product rows over the artifact-keyed lineage (reuse ladder ported from S5-B)"
```

---

### Task 4: The driver — steps, seams, containment, fan-out

**Files:**
- Create: `platform/api/clue_api/arv2/onboarding_driver.py`
- Test: `tests/arv2/test_onboarding_driver.py` (offline, in-memory doubles), `tests/arv2/test_onboarding_driver_db.py` (DB rows through the real store)

**Interfaces:**
- Consumes: Task 2 store functions; Task 3 `synchronize_catalog`; O2's `ExaClient.agent_run` / `deep_reasoning`, templates and mappers; `DurableAgentArtifactStore.persist_body`.
- Produces:
  - `class ClientEntityBinder(Protocol)`: `async def ensure(self, conn, *, workspace_id: str, brand_id: str, company_domain: str, run_id: UUID) -> UUID | None`.
  - `class SynthesisLauncher(Protocol)`: `async def launch(self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID) -> SynthesisOutcome` where `SynthesisOutcome(status: Literal["completed","empty","failed"], failure_code: str | None, failure_message: str | None, cost_usd: Decimal)`.
  - `class ExaClientFactory(Protocol)`: `def __call__(self, *, run_id: UUID, step_label: str) -> ExaAgentSurface` where `ExaAgentSurface(Protocol)` has `agent_run(...)` and `deep_reasoning(...)` with `ExaClient`'s signatures — the seam the offline tests double.
  - `def build_onboarding_provider_caller(settings: Settings, *, run_id: UUID, step_label: str) -> ProviderCaller` (one per step; raw sink dir and ledger under `Path(settings.arv2_raw_root) / "onboarding" / str(run_id) / step_label`).
  - `def build_onboarding_exa_client_factory(settings: Settings, secrets: Secrets) -> ExaClientFactory`.
  - `class OnboardingRunWorkHandler`: `kind = FleetTaskKind.ONBOARDING_RUN`; `__init__(self, *, settings: Settings, conn_factory: ConnFactory, artifacts: DurableAgentArtifactStore, exa: ExaClientFactory, client_binder: ClientEntityBinder | None = None, synthesis: SynthesisLauncher | None = None, clock: Callable[[], date] = date.today)`; `async def handle(self, context: WorkContext) -> WorkResult`.
  - `onboarding_work_id(run_id: UUID) -> WorkId` (= `WorkId(run_id)`), `ONBOARDING_DEDUP_PREFIX = "onboarding-run:"`.

- [ ] **Step 1: Write the failing offline tests**

```python
# tests/arv2/test_onboarding_driver.py
"""The driver's sequencing, failure law and fan-out, on in-memory doubles (client logic, not provider behaviour)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaAgentRun, ExaDeepResult
from clue_api.arv2.onboarding_driver import (
    OnboardingRunWorkHandler,
    SynthesisOutcome,
    onboarding_work_id,
)
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext, WorkId


def _cost(usd: str, op: str = "agent-poll") -> CallCost:
    return CallCost(cost_usd=Decimal(usd), credits=Decimal(0), media_seconds=0, cost_source="metered",
                    provider="exa", operation=op, raw_ref=f"raw/{op}", ledger_row_id=f"row-{op}")


def _agent(structured: object, *, usd: str = "0.1", status: str = "completed") -> ExaAgentRun:
    return ExaAgentRun(run_id=f"agent_run_{uuid4().hex[:6]}", status=status, stop_reason="schema_satisfied" if status == "completed" else None,
                       output_text="ok" if status == "completed" else None, structured=structured if status == "completed" else None,
                       grounding=[], usage={"searches": 3}, cost_usd=Decimal(usd), error_code=None if status == "completed" else "provider_failed",
                       error_message=None if status == "completed" else "boom", polls=1, raw_refs=("raw/a",), ledger_row_ids=("row-a",),
                       costs=(_cost(usd),), cost=_cost(usd))


def _deep(products: list[dict]) -> ExaDeepResult:
    return ExaDeepResult(output_text="{}", output_object={"coverage_note": "own + open", "products": products}, report_text=None,
                         grounding=[], results=(), status=200, cost_usd=Decimal("0.015"), request_id="req", raw_ref="raw/d",
                         ledger_row_id="row-d", cost=_cost("0.015", "deep-reasoning"), retried=False)


OVERVIEW = {"facts": {"legal_name": "Insight Health AI, Inc."}, "sections": {k: "text" for k in
            ("origin_story", "business_model", "positioning", "market_position", "customer_segments", "leadership", "recent_context")},
            "competitors": [], "named_customers": [], "not_found": []}
REVIEWS = {"summary": "thin", "themes_positive": [], "themes_negative": [], "reviews": [], "case_studies": [], "not_found": ["no G2 page"]}
PRODUCT = {"overview": "x", "capabilities": ["a"], "use_cases": [], "integrations": [], "pricing": None, "differentiators": [],
           "competitors": [], "customer_evidence": [], "who_it_is_for": None, "not_found": []}


@dataclass
class FakeExa:
    """Answers by label; records the order calls were made in and which thread they ran on."""
    agent_answers: dict[str, ExaAgentRun]
    deep_answer: ExaDeepResult
    calls: list[str] = field(default_factory=list)
    threads: set[int] = field(default_factory=set)
    concurrent: int = 0
    peak: int = 0

    def agent_run(self, *, query, output_schema, effort, system_prompt=None, label="exa-agent", poll_interval_s=4.0, timeout_s=900.0):
        import threading, time
        self.threads.add(threading.get_ident())
        self.concurrent += 1; self.peak = max(self.peak, self.concurrent)
        time.sleep(0.01)
        self.calls.append(label)
        self.concurrent -= 1
        return self.agent_answers[label.split(":")[0]]

    def deep_reasoning(self, *, system_prompt, query, output_schema, label="exa-deep", **_):
        import threading
        self.threads.add(threading.get_ident())
        self.calls.append(label)
        return self.deep_answer


@dataclass
class FakeStore:
    """Records every transition the driver makes, in order."""
    events: list[tuple] = field(default_factory=list)
    documents: dict = field(default_factory=dict)

    # the driver calls these exact names on the injected store module
    async def create_run(self, conn, **kw): self.events.append(("create_run", kw))
    async def mark_run_running(self, conn, *, run_id): self.events.append(("run_running", run_id))
    async def start_step(self, conn, **kw): self.events.append(("start_step", kw["kind"], kw.get("subject_ref")))
    async def open_document(self, conn, **kw): self.events.append(("open_document", kw["path"])); return 1
    async def publish_document(self, conn, **kw): self.events.append(("publish", kw["document_id"])); self.documents[kw["document_id"]] = kw
    async def fail_document(self, conn, **kw): self.events.append(("fail_document", kw["status"]))
    async def finish_step(self, conn, **kw): self.events.append(("finish_step", kw["status"], kw.get("failure_code")))
    async def finish_run(self, conn, *, run_id): self.events.append(("finish_run", run_id)); return "completed"
    async def fail_run(self, conn, *, run_id): self.events.append(("fail_run", run_id))


class FakeArtifacts:
    def __init__(self): self.bodies: list[bytes] = []
    async def persist_body(self, *, workspace_id, data, media_type, subject_bindings=(), project_bindings=()):
        from clue_agents.contracts import ArtifactRef
        import hashlib
        self.bodies.append(data)
        sha = hashlib.sha256(data).hexdigest()
        return ArtifactRef(workspace_id=workspace_id, artifact_key=f"{workspace_id}/{sha}", sha256=sha, media_type=media_type, byte_count=len(data))


class NullConn:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None


def _context(run_id, ws="ws-drv", brand="brd-drv") -> WorkContext:
    return WorkContext(task_id=uuid4(), work_id=onboarding_work_id(run_id), worker_id="t", lease_generation=LeaseGeneration(1),
                       payload={"run_id": str(run_id), "workspace_id": ws, "brand_id": brand, "company_domain": "insighthealth.ai",
                                "company_name": "Insight Health"},
                       stop_requested=asyncio.Event(), lease_lost=asyncio.Event())


def _handler(exa: FakeExa, store: FakeStore, *, synthesis=None, links=None, settings_overrides=None):
    from clue_config import Settings
    settings = Settings(_env_file=None, **(settings_overrides or {}))
    return OnboardingRunWorkHandler(
        settings=settings, conn_factory=NullConn, artifacts=FakeArtifacts(), exa=lambda *, run_id, step_label: exa,
        client_binder=None, synthesis=synthesis, clock=lambda: date(2026, 9, 7), store=store,
        synchronize_catalog=links or (lambda conn, **kw: asyncio.sleep(0, result=())),
    )


def test_fast_recon_runs_the_three_calls_in_parallel_off_the_loop_then_syncs_then_synthesis() -> None:
    exa = FakeExa({"overview": _agent(OVERVIEW, usd="0.5"), "reviews": _agent(REVIEWS)}, _deep([{"name": "MagicFlow", "short_description": "Orchestration.", "offering_kind": "platform"}]))
    store = FakeStore()
    seen = {}
    async def fake_sync(conn, **kw):
        seen["products"] = kw["products"]; from clue_api.arv2.onboarding_lineage import ProductLink; from uuid import uuid4 as u
        return (ProductLink("prd_magicflow", "MagicFlow", "created", 0, u()),)
    outcome = SynthesisOutcome(status="completed", failure_code=None, failure_message=None, cost_usd=Decimal("0.2"))
    class Synth:
        async def launch(self, **kw): store.events.append(("synthesis", kw["step_id"] is not None)); return outcome
    handler = _handler(exa, store, synthesis=Synth(), links=fake_sync)
    run_id = uuid4()

    result = asyncio.run(handler.handle(_context(run_id)))

    assert handler.kind is FleetTaskKind.ONBOARDING_RUN
    assert result.outcome == "completed" and result.references["run_id"] == str(run_id)
    assert exa.peak >= 2, "the fast calls overlap"
    import threading
    assert threading.get_ident() not in exa.threads, "provider calls never run on the loop thread"
    kinds = [e[1] for e in store.events if e[0] == "start_step"]
    assert kinds[:3] == ["overview", "lineup", "reviews"]
    assert "catalog_sync" in kinds and kinds.index("catalog_sync") > kinds.index("lineup")
    assert kinds.index("synthesis") > kinds.index("catalog_sync")
    assert kinds[-1] == "product_research"  # background fan-out after synthesis started
    assert seen["products"][0].name == "MagicFlow"
    assert ("finish_run", run_id) in store.events
    publishes = [e for e in store.events if e[0] == "publish"]
    assert len(publishes) == 4  # overview, catalog, reviews, one product


def test_a_failed_provider_run_is_recorded_on_the_step_and_the_run_still_finishes() -> None:
    exa = FakeExa({"overview": _agent(None, status="failed"), "reviews": _agent(REVIEWS)}, _deep([]))
    store = FakeStore()
    handler = _handler(exa, store)
    result = asyncio.run(handler.handle(_context(uuid4())))
    assert result.outcome == "completed"
    finishes = [e for e in store.events if e[0] == "finish_step"]
    assert ("finish_step", "failed", "provider_failed") in finishes
    assert ("finish_step", "empty", None) in finishes  # the empty lineup
    assert ("finish_step", "empty", None) in finishes or ("finish_step", "completed", None) in finishes
    assert ("fail_document", "failed") in store.events
    assert ("finish_run", result.references and uuid4().__class__ and store.events[-1][1]) or True
    assert store.events[-1][0] == "finish_run"


def test_without_a_synthesis_launcher_the_synthesis_step_ends_empty_with_a_reason() -> None:
    exa = FakeExa({"overview": _agent(OVERVIEW), "reviews": _agent(REVIEWS)}, _deep([]))
    store = FakeStore()
    handler = _handler(exa, store, synthesis=None)
    asyncio.run(handler.handle(_context(uuid4())))
    synth_finish = [e for e in store.events if e[0] == "finish_step" and e[1] == "empty"]
    assert synth_finish, "synthesis ends empty when no launcher is composed"


def test_the_background_fan_out_respects_the_concurrency_cap() -> None:
    products = [{"name": f"P{i}", "short_description": "d", "offering_kind": "product"} for i in range(6)]
    exa = FakeExa({"overview": _agent(OVERVIEW), "reviews": _agent(REVIEWS), "product_research": _agent(PRODUCT)}, _deep(products))
    store = FakeStore()
    async def fake_sync(conn, **kw):
        from clue_api.arv2.onboarding_lineage import ProductLink; from uuid import uuid4 as u
        return tuple(ProductLink(f"prd_{i}", f"P{i}", "created", 0, u()) for i in range(6))
    handler = _handler(exa, store, links=fake_sync, settings_overrides={"onboarding_max_parallel_runs": 2})
    exa.peak = 0
    asyncio.run(handler.handle(_context(uuid4())))
    product_calls = [c for c in exa.calls if c.startswith("product_research")]
    assert len(product_calls) == 6
    assert exa.peak <= 3  # 2 background + at most one lingering fast call


def test_an_unexpected_exception_is_contained_and_fails_the_run_row() -> None:
    class Exploding(FakeExa):
        def agent_run(self, **kw): raise RuntimeError("kaboom")
    exa = Exploding({}, _deep([]))
    store = FakeStore()
    handler = _handler(exa, store)
    result = asyncio.run(handler.handle(_context(uuid4())))
    assert result.outcome == "failed"
    assert any(e[0] == "fail_run" for e in store.events) or any(e[0] == "finish_run" for e in store.events)
    assert result.requeue is False


def test_a_lost_lease_before_work_requeues_without_touching_rows() -> None:
    exa = FakeExa({}, _deep([]))
    store = FakeStore()
    handler = _handler(exa, store)
    ctx = _context(uuid4())
    ctx.lease_lost.set()
    result = asyncio.run(handler.handle(ctx))
    assert result.requeue is True and store.events == []
```

Two test lines above are deliberately loose (`or True`); tighten them while implementing to assert exactly `store.events[-1][0] == "finish_run"` — do not leave tautologies in the committed test.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/arv2/test_onboarding_driver.py -v`
Expected: FAIL — `ModuleNotFoundError: clue_api.arv2.onboarding_driver`.

- [ ] **Step 3: Write the driver**

```python
# platform/api/clue_api/arv2/onboarding_driver.py
"""The onboarding run on the fleet (ARV2-ONBOARDING-PLAN.md §2–§4; O3).

One ``onboarding_run`` task = one run: fast recon (overview ∥ lineup ∥ reviews), catalog sync,
the synthesis turn (through a seam O4 supplies), then the background per-product fan-out under
``onboarding_max_parallel_runs``. Every provider call is R1's synchronous ``ProviderCaller`` run in
``asyncio.to_thread`` with ONE caller per step. The failure law: a provider failure, timeout or
empty answer is a step outcome, never an exception; ``handle`` contains everything and the run
row ends ``completed`` / ``completed_with_gaps`` / ``failed``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol
from uuid import UUID, uuid5, NAMESPACE_URL

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_api.arv2 import onboarding_store as default_store
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.exa_client import ExaAgentRun, ExaClient, ExaDeepResult, product_catalog_output_schema
from clue_api.arv2.onboarding_documents import (
    KnowledgeDocument, company_overview_document, customer_reviews_document,
    product_catalog_document, product_research_document, render_markdown, slugify,
)
from clue_api.arv2.onboarding_lineage import CatalogProduct, ProductLink, synchronize_catalog as default_synchronize
from clue_api.arv2.onboarding_requests import (
    COMPANY_OVERVIEW_SYSTEM_PROMPT, CUSTOMER_REVIEWS_SYSTEM_PROMPT, PRODUCT_RESEARCH_SYSTEM_PROMPT,
    company_overview_output_schema, company_overview_query, customer_reviews_output_schema,
    customer_reviews_query, product_research_output_schema, product_research_query,
)
from clue_api.arv2.sinks import FileRawSink, JsonlLedger
from clue_api.arv2.transport import HttpxTransport
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_fleet import FleetTaskKind
from clue_fleet.work_worker import WorkContext, WorkId, WorkResult
from clue_obs import get_logger

log = get_logger("clue_api.arv2.onboarding_driver")

__all__ = [
    "ClientEntityBinder", "ExaAgentSurface", "ExaClientFactory", "ONBOARDING_DEDUP_PREFIX",
    "OnboardingRunWorkHandler", "SynthesisLauncher", "SynthesisOutcome",
    "build_onboarding_exa_client_factory", "build_onboarding_provider_caller", "onboarding_work_id",
]

ONBOARDING_DEDUP_PREFIX = "onboarding-run:"
LINEUP_SYSTEM_PROMPT = (
    "Prefer pages on the company's own domain; list every distinct product page; keep "
    "integrations and partner programs separate from standalone products; never invent an "
    "offering; when unsure of a field, omit it."
)


def onboarding_work_id(run_id: UUID) -> WorkId:
    return WorkId(run_id)


class ExaAgentSurface(Protocol):
    def agent_run(self, *, query: str, output_schema: Any, effort: str, system_prompt: str | None = None,
                  label: str = "exa-agent", poll_interval_s: float = 4.0, timeout_s: float = 900.0) -> ExaAgentRun: ...
    def deep_reasoning(self, *, system_prompt: str, query: str, output_schema: Any, num_results: int = 20,
                       additional_queries: Sequence[str] | None = None, include_domains: Sequence[str] | None = None,
                       text_max_chars: int = 10000, highlights_query: str | None = None,
                       highlights_max_chars: int = 2000, label: str = "exa-deep", timeout_s: float = 1200.0) -> ExaDeepResult: ...


class ExaClientFactory(Protocol):
    def __call__(self, *, run_id: UUID, step_label: str) -> ExaAgentSurface: ...


class ClientEntityBinder(Protocol):
    async def ensure(self, conn: AsyncConnection, *, workspace_id: str, brand_id: str, company_domain: str, run_id: UUID) -> UUID | None: ...


@dataclass(frozen=True)
class SynthesisOutcome:
    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal


class SynthesisLauncher(Protocol):
    async def launch(self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID) -> SynthesisOutcome: ...


def build_onboarding_provider_caller(settings: Settings, *, run_id: UUID, step_label: str) -> ProviderCaller:
    root = Path(settings.arv2_raw_root) / "onboarding" / str(run_id) / step_label.replace(":", "_")
    root.mkdir(parents=True, exist_ok=True)
    return ProviderCaller(
        transport=HttpxTransport(), raw_sink=FileRawSink(root / "raw"), ledger=JsonlLedger(root / "ledger.jsonl"),
        now=lambda: datetime.now(UTC),
    )


def build_onboarding_exa_client_factory(settings: Settings, secrets: Secrets) -> ExaClientFactory:
    key = secrets.exa_api_key
    if key is None or not key.get_secret_value().strip():
        raise ValueError("CLUE_EXA_API_KEY is required for the onboarding lane")

    def factory(*, run_id: UUID, step_label: str) -> ExaAgentSurface:
        return ExaClient(build_onboarding_provider_caller(settings, run_id=run_id, step_label=step_label), SecretStr(key.get_secret_value()))

    return factory


@dataclass(frozen=True)
class _Scope:
    run_id: UUID
    workspace_id: str
    brand_id: str
    company_domain: str
    company_name: str


@dataclass(frozen=True)
class _StepOutcome:
    status: Literal["completed", "empty", "failed"]
    document: KnowledgeDocument | None
    provider_run_id: str | None
    raw_artifact_key: str | None
    cost_usd: Decimal
    searches: int
    failure_code: str | None = None
    failure_message: str | None = None


class OnboardingRunWorkHandler:
    kind = FleetTaskKind.ONBOARDING_RUN

    def __init__(
        self, *, settings: Settings, conn_factory: ConnFactory, artifacts: Any, exa: ExaClientFactory,
        client_binder: ClientEntityBinder | None = None, synthesis: SynthesisLauncher | None = None,
        clock: Callable[[], date] = date.today, store: ModuleType | Any = default_store,
        synchronize_catalog: Callable[..., Any] = default_synchronize,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory
        self._artifacts = artifacts
        self._exa = exa
        self._binder = client_binder
        self._synthesis = synthesis
        self._clock = clock
        self._store = store
        self._sync = synchronize_catalog

    # -- fleet entry -----------------------------------------------------------------------------

    async def handle(self, context: WorkContext) -> WorkResult:
        if context.stop_requested.is_set() or context.lease_lost.is_set():
            return WorkResult(outcome="stopped", references={}, requeue=True)
        scope = self._scope(context.payload)
        if UUID(str(context.work_id)) != scope.run_id:
            raise ValueError("onboarding task work id disagrees with its run id")
        try:
            status = await self._run(scope, context)
        except Exception:  # noqa: BLE001 — containment: the fleet plane knows nothing about our rows
            log.exception("onboarding.run_contained_failure", run_id=str(scope.run_id))
            async with self._conn_factory() as conn:
                await self._store.fail_run(conn, run_id=scope.run_id)
            return WorkResult(outcome="failed", references={"run_id": str(scope.run_id)}, requeue=False)
        return WorkResult(outcome=status, references={"run_id": str(scope.run_id)})

    @staticmethod
    def _scope(payload: dict[str, Any]) -> _Scope:
        try:
            return _Scope(run_id=UUID(str(payload["run_id"])), workspace_id=str(payload["workspace_id"]),
                          brand_id=str(payload["brand_id"]), company_domain=str(payload["company_domain"]),
                          company_name=str(payload.get("company_name") or payload["company_domain"]))
        except (KeyError, ValueError) as error:
            raise ValueError("invalid onboarding task payload") from error

    # -- the run -----------------------------------------------------------------------------------

    async def _run(self, scope: _Scope, context: WorkContext) -> str:
        async with self._conn_factory() as conn:
            await self._store.mark_run_running(conn, run_id=scope.run_id)
            if self._binder is not None:
                await self._binder.ensure(conn, workspace_id=scope.workspace_id, brand_id=scope.brand_id,
                                          company_domain=scope.company_domain, run_id=scope.run_id)
        reviews_fast = self._settings.onboarding_reviews_phase == "fast"
        fast = [self._overview(scope), self._lineup(scope)]
        if reviews_fast:
            fast.append(self._reviews(scope, phase="fast"))
        results = await asyncio.gather(*fast)
        links: tuple[ProductLink, ...] = results[1] if isinstance(results[1], tuple) else ()
        synthesis_task = asyncio.create_task(self._synthesis_step(scope))
        background = [self._product_research(scope, link) for link in links if link.product_id]
        if not reviews_fast:
            background.append(self._reviews(scope, phase="background"))
        semaphore = asyncio.Semaphore(self._settings.onboarding_max_parallel_runs)

        async def bounded(coro):
            async with semaphore:
                return await coro

        await asyncio.gather(*(bounded(c) for c in background))
        await synthesis_task
        async with self._conn_factory() as conn:
            return await self._store.finish_run(conn, run_id=scope.run_id)

    # -- steps -------------------------------------------------------------------------------------

    def _step_id(self, scope: _Scope, kind: str, subject: str | None = None) -> UUID:
        return uuid5(NAMESPACE_URL, f"onboarding-step:{scope.run_id}:{kind}:{subject or ''}")

    async def _overview(self, scope: _Scope) -> None:
        await self._agent_step(
            scope, kind="overview", phase="fast", folder="company", path="company/overview.md", doc_kind="company-overview",
            query=company_overview_query(f"{scope.company_name} ({scope.company_domain})"),
            schema=company_overview_output_schema(), effort=self._settings.onboarding_overview_effort,
            system_prompt=COMPANY_OVERVIEW_SYSTEM_PROMPT,
            mapper=lambda run: company_overview_document(run, company_domain=scope.company_domain, as_of=self._clock()),
        )

    async def _reviews(self, scope: _Scope, *, phase: str) -> None:
        await self._agent_step(
            scope, kind="reviews", phase=phase, folder="proof", path="proof/customer-reviews.md", doc_kind="customer-reviews",
            query=customer_reviews_query(scope.company_name, scope.company_domain),
            schema=customer_reviews_output_schema(), effort=self._settings.onboarding_reviews_effort,
            system_prompt=CUSTOMER_REVIEWS_SYSTEM_PROMPT,
            mapper=lambda run: customer_reviews_document(run, company_domain=scope.company_domain, as_of=self._clock()),
        )

    async def _product_research(self, scope: _Scope, link: ProductLink) -> None:
        assert link.product_id is not None
        await self._agent_step(
            scope, kind="product_research", phase="background", subject=link.product_id, folder="product",
            path=f"product/{slugify(link.name)}.md", doc_kind="product-research",
            query=product_research_query(product_name=link.name, company_name=scope.company_name, official_url=None, sibling_names=[]),
            schema=product_research_output_schema(), effort=self._settings.onboarding_product_effort,
            system_prompt=PRODUCT_RESEARCH_SYSTEM_PROMPT,
            mapper=lambda run: product_research_document(run, product_id=link.product_id or "", product_name=link.name,
                                                         product_slug=slugify(link.name), as_of=self._clock()),
        )

    async def _agent_step(self, scope: _Scope, *, kind: str, phase: str, folder: str, path: str, doc_kind: str, query: str,
                          schema: Any, effort: str, system_prompt: str, mapper: Callable[[ExaAgentRun], KnowledgeDocument],
                          subject: str | None = None) -> None:
        step_id, document_id = self._step_id(scope, kind, subject), uuid5(NAMESPACE_URL, f"onboarding-document:{scope.run_id}:{path}")
        async with self._conn_factory() as conn:
            await self._store.start_step(conn, step_id=step_id, run_id=scope.run_id, workspace_id=scope.workspace_id,
                                         kind=kind, phase=phase, subject_ref=subject)
            await self._store.open_document(conn, document_id=document_id, workspace_id=scope.workspace_id, brand_id=scope.brand_id,
                                            folder=folder, path=path, kind=doc_kind, step_id=step_id)
        label = f"{kind}:{subject}" if subject else kind
        client = self._exa(run_id=scope.run_id, step_label=label)
        try:
            run = await asyncio.to_thread(client.agent_run, query=query, output_schema=schema, effort=effort,
                                          system_prompt=system_prompt, label=label)
        except Exception as error:  # noqa: BLE001 — a provider halt or transport failure is a step outcome
            await self._settle(scope, step_id, document_id, _StepOutcome("failed", None, None, None, Decimal(0), 0,
                                                                          failure_code=type(error).__name__, failure_message=str(error)[:500]))
            return
        if run.status != "completed" or not isinstance(run.structured, dict):
            outcome = _StepOutcome("failed", None, run.run_id, run.raw_refs[-1] if run.raw_refs else None,
                                   run.cost_usd or Decimal(0), int(run.usage.get("searches", 0) or 0),
                                   failure_code=run.error_code or run.status, failure_message=run.error_message)
            await self._settle(scope, step_id, document_id, outcome)
            return
        document = mapper(run)
        await self._settle(scope, step_id, document_id, _StepOutcome(
            "completed", document, run.run_id, run.raw_refs[-1] if run.raw_refs else None,
            run.cost_usd or Decimal(0), int(run.usage.get("searches", 0) or 0)))

    async def _lineup(self, scope: _Scope) -> tuple[ProductLink, ...]:
        step_id = self._step_id(scope, "lineup")
        document_id = uuid5(NAMESPACE_URL, f"onboarding-document:{scope.run_id}:product/catalog.md")
        async with self._conn_factory() as conn:
            await self._store.start_step(conn, step_id=step_id, run_id=scope.run_id, workspace_id=scope.workspace_id, kind="lineup", phase="fast")
            await self._store.open_document(conn, document_id=document_id, workspace_id=scope.workspace_id, brand_id=scope.brand_id,
                                            folder="product", path="product/catalog.md", kind="product-catalog", step_id=step_id)
        client = self._exa(run_id=scope.run_id, step_label="lineup")
        query = f"Exhaustive list of products of {scope.company_domain}"
        try:
            own = await asyncio.to_thread(client.deep_reasoning, system_prompt=LINEUP_SYSTEM_PROMPT, query=query,
                                          output_schema=product_catalog_output_schema(), num_results=40,
                                          include_domains=[scope.company_domain], label="lineup:own-domain")
            open_web = await asyncio.to_thread(client.deep_reasoning, system_prompt=LINEUP_SYSTEM_PROMPT, query=query,
                                               output_schema=product_catalog_output_schema(), num_results=40, label="lineup:open")
        except Exception as error:  # noqa: BLE001
            await self._settle(scope, step_id, document_id, _StepOutcome("failed", None, None, None, Decimal(0), 0,
                                                                          failure_code=type(error).__name__, failure_message=str(error)[:500]))
            return ()
        merged = _merge_lineups(own, open_web)
        document = product_catalog_document(merged, company_domain=scope.company_domain, as_of=self._clock())
        products = tuple(CatalogProduct(name=p["name"], short_description=p["short_description"], aliases=tuple(p.get("aliases") or ()))
                         for p in document.front_matter["products"])
        cost = (own.cost_usd or Decimal(0)) + (open_web.cost_usd or Decimal(0))
        if not products:
            await self._settle(scope, step_id, document_id, _StepOutcome("empty", document, own.request_id, own.raw_ref, cost, 0,
                                                                          failure_message="no products established"))
            return ()
        await self._settle(scope, step_id, document_id, _StepOutcome("completed", document, own.request_id, open_web.raw_ref, cost, 0))
        sync_step = self._step_id(scope, "catalog_sync")
        async with self._conn_factory() as conn:
            await self._store.start_step(conn, step_id=sync_step, run_id=scope.run_id, workspace_id=scope.workspace_id, kind="catalog_sync", phase="fast")
            try:
                links = await self._sync(conn, workspace_id=scope.workspace_id, brand_id=scope.brand_id, document_id=document_id, products=products)
            except Exception as error:  # noqa: BLE001
                await self._store.finish_step(conn, step_id=sync_step, status="failed", failure_code=type(error).__name__, failure_message=str(error)[:500])
                return ()
            await self._store.finish_step(conn, step_id=sync_step, status="completed")
        return tuple(links)

    async def _synthesis_step(self, scope: _Scope) -> None:
        step_id = self._step_id(scope, "synthesis")
        async with self._conn_factory() as conn:
            await self._store.start_step(conn, step_id=step_id, run_id=scope.run_id, workspace_id=scope.workspace_id, kind="synthesis", phase="fast")
        if self._synthesis is None:
            async with self._conn_factory() as conn:
                await self._store.finish_step(conn, step_id=step_id, status="empty", failure_message="synthesis agent not composed (O4)")
            return
        try:
            outcome = await self._synthesis.launch(workspace_id=scope.workspace_id, brand_id=scope.brand_id, run_id=scope.run_id, step_id=step_id)
        except Exception as error:  # noqa: BLE001
            outcome = SynthesisOutcome("failed", type(error).__name__, str(error)[:500], Decimal(0))
        async with self._conn_factory() as conn:
            await self._store.finish_step(conn, step_id=step_id, status=outcome.status, cost_usd=outcome.cost_usd,
                                          failure_code=outcome.failure_code, failure_message=outcome.failure_message)

    # -- settlement --------------------------------------------------------------------------------

    async def _settle(self, scope: _Scope, step_id: UUID, document_id: UUID, outcome: _StepOutcome) -> None:
        ref: ArtifactRef | None = None
        if outcome.document is not None:
            ref = await self._artifacts.persist_body(workspace_id=scope.workspace_id,
                                                     data=render_markdown(outcome.document).encode("utf-8"), media_type="text/markdown")
        async with self._conn_factory() as conn:
            if ref is not None and outcome.status == "completed":
                await self._store.publish_document(conn, document_id=document_id, artifact_key=ref.artifact_key, artifact_sha256=ref.sha256)
            elif ref is not None:
                await self._store.publish_document(conn, document_id=document_id, artifact_key=ref.artifact_key,
                                                   artifact_sha256=ref.sha256, status=outcome.status)
            else:
                await self._store.fail_document(conn, document_id=document_id, status="failed" if outcome.status == "failed" else "empty")
            await self._store.finish_step(conn, step_id=step_id, status=outcome.status, provider_run_id=outcome.provider_run_id,
                                          raw_artifact_key=outcome.raw_artifact_key, cost_usd=outcome.cost_usd, searches=outcome.searches,
                                          failure_code=outcome.failure_code, failure_message=outcome.failure_message)


def _merge_lineups(own: ExaDeepResult, open_web: ExaDeepResult) -> ExaDeepResult:
    """Union the two passes by normalized name; the own-domain pass wins on conflict."""
    from dataclasses import replace

    def entries(result: ExaDeepResult) -> list[dict[str, Any]]:
        parsed = result.output_object if isinstance(result.output_object, dict) else {}
        return [p for p in (parsed.get("products") or []) if isinstance(p, dict) and isinstance(p.get("name"), str)]

    seen: dict[str, dict[str, Any]] = {}
    for entry in entries(own) + entries(open_web):
        key = " ".join(entry["name"].casefold().split())
        seen.setdefault(key, entry)
    notes = [r.output_object.get("coverage_note") for r in (own, open_web)
             if isinstance(r.output_object, dict) and r.output_object.get("coverage_note")]
    grounding = list(own.grounding or []) + list(open_web.grounding or [])
    merged = {"coverage_note": " | ".join(str(n) for n in notes) or None, "products": list(seen.values())}
    return replace(own, output_object=merged, grounding=grounding)
```

Note on `_merge_lineups` and grounding: the open-web pass's grounding field paths (`products[i]`) refer to *its* ordering, not the merged one; the mapper attaches sources by index, so only the own-domain pass's grounding indexes are reliable. Keep only `own.grounding` in the merge (`grounding = list(own.grounding or [])`) and record in the README that open-web entries carry no per-entry sources. Adjust the code above accordingly.

- [ ] **Step 4: Write the DB-backed driver test**

```python
# tests/arv2/test_onboarding_driver_db.py
"""One run through the real store and artifact store (fake provider), asserting the rows the page reads."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.onboarding_driver import OnboardingRunWorkHandler, onboarding_work_id
from clue_api.arv2.onboarding_store import create_run, list_documents, read_current_run
from clue_config import Settings
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_storage import read_verified_artifact
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.arv2.test_onboarding_driver import OVERVIEW, PRODUCT, REVIEWS, FakeExa, _agent, _deep
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_a_run_publishes_readable_documents_and_products_and_status() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-driver-db"
            project = await seed_project(conn, ws, name="O3 driver")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_driver")
            run_id = uuid4()
            await create_run(conn, run_id=run_id, workspace_id=ws, brand_id=project.brand_id,
                             company_domain="insighthealth.ai", requested_by_user_id="usr_o3_driver")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
            exa = FakeExa({"overview": _agent(OVERVIEW, usd="0.5"), "reviews": _agent(REVIEWS), "product_research": _agent(PRODUCT)},
                          _deep([{"name": "MagicFlow", "short_description": "Orchestration.", "offering_kind": "platform"}]))
            handler = OnboardingRunWorkHandler(settings=Settings(_env_file=None), conn_factory=conn_session_factory(conn),
                                               artifacts=artifacts, exa=lambda *, run_id, step_label: exa)
            context = WorkContext(task_id=uuid4(), work_id=onboarding_work_id(run_id), worker_id="t", lease_generation=LeaseGeneration(1),
                                  payload={"run_id": str(run_id), "workspace_id": ws, "brand_id": project.brand_id,
                                           "company_domain": "insighthealth.ai", "company_name": "Insight Health"},
                                  stop_requested=asyncio.Event(), lease_lost=asyncio.Event())
            result = await handler.handle(context)
            assert result.outcome == "completed_with_gaps"  # synthesis is empty until O4
            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None and status.status == "completed_with_gaps"
            kinds = {(s.kind, s.subject_ref): s.status for s in status.steps}
            assert kinds[("overview", None)] == "completed" and kinds[("lineup", None)] == "completed"
            assert kinds[("catalog_sync", None)] == "completed" and kinds[("synthesis", None)] == "empty"
            assert any(k[0] == "product_research" and v == "completed" for k, v in kinds.items())
            docs = {d.path: d for d in await list_documents(conn, workspace_id=ws, brand_id=project.brand_id)}
            assert docs["company/overview.md"].status == "ready" and docs["product/catalog.md"].status == "ready"
            assert docs["product/magicflow.md"].status == "ready" and docs["proof/customer-reviews.md"].status == "ready"
            record, body = await read_verified_artifact(conn, storage, storage_key=docs["company/overview.md"].artifact_key, workspace_id=ws)
            assert body.startswith(b"---\nkind: company-overview")
            assert status.cost_usd >= 0.5

    run_async(scenario())
```

- [ ] **Step 5: Run everything, ruff, mypy, commit**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py tests/arv2/test_import_guard.py -v && uv run ruff check platform/api/clue_api/arv2 tests/arv2 && uv run ruff format --check platform/api/clue_api/arv2 tests/arv2 && uv run mypy platform/api/clue_api/arv2`
Expected: all PASS; the import guard proves the driver imports nothing quarantined.

```bash
git add platform/api/clue_api/arv2/onboarding_driver.py tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py
git commit -m "feat(arv2): onboarding run driver — fast recon in parallel off the loop, catalog sync, synthesis seam, capped background fan-out, failure law and containment"
```

---

### Task 5: The route and the enqueuer

**Files:**
- Create: `platform/api/clue_api/onboarding_routes.py`
- Modify: `platform/api/clue_api/projections_app.py` (mount + dependency override)
- Test: `tests/api/test_onboarding_routes_db.py`

**Interfaces:**
- Produces: `create_onboarding_router(*, conn_factory: ConnFactory, enqueuer: OnboardingEnqueuer, brand_kit_ingestion: BrandKitIngestionTrigger | None = None) -> APIRouter`; `class OnboardingEnqueuer(Protocol): async def enqueue(self, *, run_id: UUID, workspace_id, brand_id, company_domain, company_name) -> bool`; `class DbOnboardingEnqueuer(queue: WorkQueue | None = None)`; request `OnboardingStartRequest(company_domain: str, company_name: str | None = None, brand_id: str | None = None)`; responses `OnboardingStartResponse(schema_version, run_id, status="queued")` and `OnboardingStatusResponse` in the spec §7 shape (`runId`, `status`, `steps[{kind, subjectRef, phase, status, startedAt, finishedAt, costUsd, failureCode}]`, `costUsd`) with `status: "none"` when no run exists.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_onboarding_routes_db.py
"""POST /onboarding enqueues one fleet task and returns 202; GET /onboarding/current reads the rows."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.onboarding_routes import create_onboarding_router
from clue_fleet import FleetTaskKind
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.auth.conftest import rollback_conn, run_async
from tests.profiling.conftest import conn_session_factory, migrated_db  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _RecordingEnqueuer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue(self, **kw) -> bool:
        self.calls.append(kw)
        return len(self.calls) == 1


def test_start_creates_a_queued_run_and_enqueues_once_then_current_reads_it() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route"
            project = await seed_project(conn, ws, name="O3 route")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_route")
            enqueuer = _RecordingEnqueuer()
            app = FastAPI()
            app.include_router(create_onboarding_router(conn_factory=conn_session_factory(conn), enqueuer=enqueuer))
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                nothing = await client.get("/onboarding/current", headers={"X-Workspace-Id": ws})
                assert nothing.status_code == 200 and nothing.json()["status"] == "none"
                started = await client.post("/onboarding", headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_route"},
                                            json={"company_domain": "insighthealth.ai", "company_name": "Insight Health"})
                assert started.status_code == 202, started.text
                body = started.json()
                run_id = UUID(body["run_id"]); assert body["status"] == "queued"
                assert enqueuer.calls[0]["brand_id"] == project.brand_id and enqueuer.calls[0]["run_id"] == run_id
                current = await client.get("/onboarding/current", headers={"X-Workspace-Id": ws})
                assert current.json()["runId"] == str(run_id) and current.json()["status"] == "queued"
                assert current.json()["steps"] == []
                row = (await conn.execute(text("SELECT status, brand_id, requested_by_user_id FROM onboarding_run WHERE run_id = :r"), {"r": run_id})).mappings().one()
                assert (row["status"], row["brand_id"], row["requested_by_user_id"]) == ("queued", project.brand_id, "usr_o3_route")

                again = await client.post("/onboarding", headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_route"},
                                          json={"company_domain": "insighthealth.ai"})
                assert again.status_code == 409  # a queued/running run already exists for the workspace

    run_async(scenario())


def test_a_blank_domain_or_foreign_brand_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route-bad"
            await seed_project(conn, ws, name="O3 route bad")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_bad")
            app = FastAPI()
            app.include_router(create_onboarding_router(conn_factory=conn_session_factory(conn), enqueuer=_RecordingEnqueuer()))
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                blank = await client.post("/onboarding", headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_bad"}, json={"company_domain": "  "})
                assert blank.status_code == 422
                foreign = await client.post("/onboarding", headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_bad"},
                                            json={"company_domain": "x.io", "brand_id": "brd_not_mine"})
                assert foreign.status_code == 409 and foreign.json()["detail"]["error"] == "brand_unavailable"

    run_async(scenario())
```

The `X-Test-User-Id` header stands in for the principal only when no authenticated principal is present (the same fail-open-to-header seam the Stage-0 router uses for its workspace); production always has `request.state.clue_principal`. Model the resolver on `setup_workspace_resolver`.

- [ ] **Step 2: Run to verify failure**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_onboarding_routes_db.py -v`
Expected: FAIL — `ModuleNotFoundError: clue_api.onboarding_routes`.

- [ ] **Step 3: Write the router**

```python
# platform/api/clue_api/onboarding_routes.py
"""``POST /onboarding`` and ``GET /onboarding/current`` (ARV2-ONBOARDING-PLAN.md §3, §7; O3).

The route inserts the run row and enqueues the fleet job — nothing else runs on the web loop.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from clue_api.arv2.onboarding_driver import ONBOARDING_DEDUP_PREFIX, onboarding_work_id
from clue_api.arv2.onboarding_store import create_run, read_current_run
from clue_api.auth_wiring import principal_from_request
from clue_api.brand_kit_ingestion import BrandKitIngestionTrigger
from clue_db import ConnFactory
from clue_fleet import FleetTaskKind
from clue_fleet.queue import DbWorkQueue, WorkQueue
from clue_projections import PROJECTIONS_SCHEMA_VERSION
from clue_spine import get_brand, list_brands_for_workspace

__all__ = ["DbOnboardingEnqueuer", "OnboardingEnqueuer", "create_onboarding_router", "onboarding_workspace_resolver"]


def onboarding_workspace_resolver(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    return x_workspace_id


WorkspaceDep = Annotated[str, Depends(onboarding_workspace_resolver)]


class OnboardingEnqueuer(Protocol):
    async def enqueue(self, *, run_id: UUID, workspace_id: str, brand_id: str, company_domain: str, company_name: str) -> bool: ...


class DbOnboardingEnqueuer:
    def __init__(self, queue: WorkQueue | None = None) -> None:
        self._queue = queue if queue is not None else DbWorkQueue()

    async def enqueue(self, *, run_id: UUID, workspace_id: str, brand_id: str, company_domain: str, company_name: str) -> bool:
        return await self._queue.enqueue(
            kind=FleetTaskKind.ONBOARDING_RUN, work_id=onboarding_work_id(run_id),
            dedup_key=f"{ONBOARDING_DEDUP_PREFIX}{run_id}", priority=-150,
            payload={"run_id": str(run_id), "workspace_id": workspace_id, "brand_id": brand_id,
                     "company_domain": company_domain, "company_name": company_name},
            reopen_terminal=False,
        )


class OnboardingStartRequest(BaseModel):
    company_domain: str = Field(min_length=1, max_length=253)
    company_name: str | None = Field(default=None, max_length=200)
    brand_id: str | None = None


class OnboardingStartResponse(BaseModel):
    schema_version: str
    run_id: str
    status: Literal["queued"]


class OnboardingStepView(BaseModel):
    kind: str
    subjectRef: str | None
    phase: str
    status: str
    startedAt: str | None
    finishedAt: str | None
    costUsd: str
    failureCode: str | None


class OnboardingStatusResponse(BaseModel):
    schema_version: str
    runId: str | None
    status: str
    steps: list[OnboardingStepView]
    costUsd: str


def create_onboarding_router(
    *, conn_factory: ConnFactory, enqueuer: OnboardingEnqueuer,
    brand_kit_ingestion: BrandKitIngestionTrigger | None = None,
) -> APIRouter:
    router = APIRouter(tags=["onboarding"])

    def _user_id(request: Request) -> str:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("research.launch")
            return principal.user_id
        header = request.headers.get("X-Test-User-Id")
        if not header:
            raise HTTPException(status_code=401, detail="no principal")
        return header

    @router.post("/onboarding", response_model=OnboardingStartResponse, status_code=202)
    async def start_onboarding(request: Request, body: OnboardingStartRequest, workspace_id: WorkspaceDep) -> OnboardingStartResponse:
        domain = body.company_domain.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if not domain:
            raise HTTPException(status_code=422, detail="company_domain is blank")
        user_id = _user_id(request)
        async with conn_factory() as conn:
            if body.brand_id is not None:
                brand = await get_brand(conn, workspace_id=workspace_id, brand_id=body.brand_id)
            else:
                brands = await list_brands_for_workspace(conn, workspace_id)
                brand = brands[0] if len(brands) == 1 else None
            if brand is None:
                raise HTTPException(status_code=409, detail={"error": "brand_unavailable",
                                                             "reason": "name one brand of this workspace"})
            open_run = (await conn.execute(
                text("SELECT run_id FROM onboarding_run WHERE workspace_id = :ws AND status IN ('queued', 'running') LIMIT 1"),
                {"ws": workspace_id},
            )).scalar_one_or_none()
            if open_run is not None:
                raise HTTPException(status_code=409, detail={"error": "onboarding_in_progress", "reason": str(open_run)})
            run_id = uuid4()
            await create_run(conn, run_id=run_id, workspace_id=workspace_id, brand_id=brand.brand_id,
                             company_domain=domain, requested_by_user_id=user_id)
        await enqueuer.enqueue(run_id=run_id, workspace_id=workspace_id, brand_id=brand.brand_id,
                               company_domain=domain, company_name=(body.company_name or domain).strip())
        if brand_kit_ingestion is not None:
            await brand_kit_ingestion.ensure(workspace_id=workspace_id, website=f"https://{domain}")
        return OnboardingStartResponse(schema_version=PROJECTIONS_SCHEMA_VERSION, run_id=str(run_id), status="queued")

    @router.get("/onboarding/current", response_model=OnboardingStatusResponse)
    async def current_onboarding(workspace_id: WorkspaceDep) -> OnboardingStatusResponse:
        async with conn_factory() as conn:
            status = await read_current_run(conn, workspace_id=workspace_id)
        if status is None:
            return OnboardingStatusResponse(schema_version=PROJECTIONS_SCHEMA_VERSION, runId=None, status="none", steps=[], costUsd="0")
        return OnboardingStatusResponse(
            schema_version=PROJECTIONS_SCHEMA_VERSION, runId=str(status.run_id), status=status.status,
            steps=[OnboardingStepView(kind=s.kind, subjectRef=s.subject_ref, phase=s.phase, status=s.status,
                                      startedAt=s.started_at.isoformat() if s.started_at else None,
                                      finishedAt=s.finished_at.isoformat() if s.finished_at else None,
                                      costUsd=str(s.cost_usd), failureCode=s.failure_code) for s in status.steps],
            costUsd=str(status.cost_usd),
        )

    return router
```

Check the exact import path of `PROJECTIONS_SCHEMA_VERSION` in `stage0_setup.py` and use the same.

- [ ] **Step 4: Mount it**

In `platform/api/clue_api/projections_app.py`, next to the Stage-0 mount (~line 908), add:

```python
    if resolved.onboarding_v2_enabled:
        from clue_api.onboarding_routes import (
            DbOnboardingEnqueuer,
            create_onboarding_router,
            onboarding_workspace_resolver,
        )

        app.dependency_overrides[onboarding_workspace_resolver] = workspace_resolver
        app.include_router(
            create_onboarding_router(
                conn_factory=conn_factory,
                enqueuer=DbOnboardingEnqueuer(),
                brand_kit_ingestion=build_brand_kit_ingestion_trigger(settings=resolved, conn_factory=conn_factory),
            )
        )
```

(`workspace_resolver` is the authenticated resolver already used for `setup_workspace_resolver` at ~886; place the override where that one is.)

- [ ] **Step 5: Run, ruff, commit**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_onboarding_routes_db.py -v && uv run ruff check platform/api/clue_api/onboarding_routes.py platform/api/clue_api/projections_app.py tests/api/test_onboarding_routes_db.py && uv run ruff format --check platform/api/clue_api/onboarding_routes.py tests/api/test_onboarding_routes_db.py`

```bash
git add platform/api/clue_api/onboarding_routes.py platform/api/clue_api/projections_app.py tests/api/test_onboarding_routes_db.py
git commit -m "feat(api): POST /onboarding enqueues one onboarding_run fleet job (202) and GET /onboarding/current reads the run and steps; mounted behind CLUE_ONBOARDING_V2_ENABLED"
```

---

### Task 6: Client binding seam, fleet composition, README, close-out

**Files:**
- Create: `platform/api/clue_api/onboarding_client_binding.py`
- Modify: `platform/api/clue_api/fleet_main.py:844-859`
- Modify: `platform/api/clue_api/arv2/README.md`
- Test: `tests/api/test_onboarding_client_binding_db.py`
- Create: `_memory/2026-09-07-arv2-onboarding-o3-fleet-driver.md`

**Interfaces:**
- Produces: `class Stage0ClientEntityBinder(ClientEntityBinder)` with `ensure(conn, *, workspace_id, brand_id, company_domain, run_id) -> UUID | None`: reuses the existing binding when `workspace_client_binding` has one; otherwise resolves/creates the client entity through `prepare_client_kb_run(conn, ClientInput(name=company_domain, website=f"https://{company_domain}"), workspace_id=workspace_id, run_id=RunId(run_id))`, then `bind_workspace_client(conn, workspace_id=..., client_entity_id=...)`, and stamps `onboarding_run.client_entity_id`. Implemented OUTSIDE `arv2/` (it imports `clue_research.stage0` and `clue_api.client_context_binding`).
- Fleet composition: in `fleet_main._serve`, `onboarding_handler = OnboardingRunWorkHandler(settings=settings, conn_factory=transaction, artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction), exa=build_onboarding_exa_client_factory(settings, secrets), client_binder=Stage0ClientEntityBinder(), synthesis=None) if settings.onboarding_v2_enabled else None`, passed as `onboarding_handler=` to `build_multi_work_worker`.

- [ ] **Step 1: Write the failing binder test**

```python
# tests/api/test_onboarding_client_binding_db.py
from __future__ import annotations

from uuid import uuid4

import pytest

from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.onboarding_client_binding import Stage0ClientEntityBinder
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_the_binder_creates_a_client_once_and_reuses_it() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-binder"
            project = await seed_project(conn, ws, name="O3 binder")
            binder = Stage0ClientEntityBinder()
            first = await binder.ensure(conn, workspace_id=ws, brand_id=project.brand_id, company_domain="insighthealth.ai", run_id=uuid4())
            assert first is not None
            assert await workspace_client_entity_id(conn, workspace_id=ws) == first
            second = await binder.ensure(conn, workspace_id=ws, brand_id=project.brand_id, company_domain="insighthealth.ai", run_id=uuid4())
            assert second == first

    run_async(scenario())
```

`rollback_conn` seeds the core pack (`seed_pack=True`), which `prepare_client_kb_run` needs (`load_client_knowledge_pack`).

- [ ] **Step 2: Write the binder**

```python
# platform/api/clue_api/onboarding_client_binding.py
"""The onboarding lane's client-entity seam — implemented outside ``clue_api.arv2`` because it
reuses the Stage-0 client resolution (``clue_research.stage0``), which the ARV2 import guard
forbids inside the lane. No Client-KB version, readiness or Stage-0 pin is read or written."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import bind_workspace_client, workspace_client_entity_id
from clue_core import RunId
from clue_research.stage0 import ClientInput, prepare_client_kb_run

__all__ = ["Stage0ClientEntityBinder"]


class Stage0ClientEntityBinder:
    async def ensure(self, conn: AsyncConnection, *, workspace_id: str, brand_id: str, company_domain: str, run_id: UUID) -> UUID | None:
        existing = await workspace_client_entity_id(conn, workspace_id=workspace_id)
        if existing is None:
            entity_id = await prepare_client_kb_run(
                conn, ClientInput(name=company_domain, website=f"https://{company_domain}"),
                workspace_id=workspace_id, run_id=RunId(run_id),
            )
            await bind_workspace_client(conn, workspace_id=workspace_id, client_entity_id=entity_id)
            existing = entity_id
        await conn.execute(
            text("UPDATE onboarding_run SET client_entity_id = :entity WHERE run_id = :run_id AND client_entity_id IS NULL"),
            {"entity": UUID(str(existing)), "run_id": run_id},
        )
        return UUID(str(existing))
```

Confirm the exact import names (`ClientInput`, `prepare_client_kb_run` from `clue_research.stage0`; `RunId` from `clue_core`) by reading the modules; if `prepare_client_kb_run`'s `RunId` requires a registered run row first (`record_run_lineage` inserts it), no extra step is needed — it records the lineage itself.

- [ ] **Step 3: Compose on the fleet**

In `platform/api/clue_api/fleet_main.py` `_serve`, before `worker = build_multi_work_worker(`:

```python
        onboarding_handler = None
        if settings.onboarding_v2_enabled:
            from clue_api.agent_turn_wiring import DurableAgentArtifactStore
            from clue_api.arv2.onboarding_driver import (
                OnboardingRunWorkHandler,
                build_onboarding_exa_client_factory,
            )
            from clue_api.onboarding_client_binding import Stage0ClientEntityBinder

            onboarding_handler = OnboardingRunWorkHandler(
                settings=settings,
                conn_factory=transaction,
                artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction),
                exa=build_onboarding_exa_client_factory(settings, secrets),
                client_binder=Stage0ClientEntityBinder(),
                synthesis=None,  # O4 supplies the launcher
            )
```

and pass `onboarding_handler=onboarding_handler,` to `build_multi_work_worker`. Use the module's existing names for `storage`, `secrets`, `transaction` (read the surrounding code).

- [ ] **Step 4: README + tests + commit**

Add to `platform/api/clue_api/arv2/README.md` a section "Onboarding driver (O3)": the step graph, one `ProviderCaller` per step under `arv2_raw_root/onboarding/<run_id>/<step>/`, the two seams and why they are injected (import guard), the failure law, the merge rule for the two lineup passes (own-domain grounding only), and that `provider_call_ledger` (D1) replaces the JSONL sinks at composition when it lands.

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_onboarding_client_binding_db.py tests/arv2 --ignore-glob='*_live.py' tests/api/test_fleet_wiring.py -q && uv run ruff check platform/api/clue_api/onboarding_client_binding.py platform/api/clue_api/fleet_main.py && uv run mypy platform/api/clue_api/arv2`

```bash
git add platform/api/clue_api/onboarding_client_binding.py platform/api/clue_api/fleet_main.py platform/api/clue_api/arv2/README.md tests/api/test_onboarding_client_binding_db.py
git commit -m "feat(api,fleet): onboarding client-entity binder (outside the lane) and fleet composition of the onboarding handler behind CLUE_ONBOARDING_V2_ENABLED"
```

- [ ] **Step 5: Standing-rule checklist + memory note**

- `grep -rn "client_kb_version\|readiness_decision\|project_run_stage0_pins\|load_pinned_client_knowledge\|current_kb_version" platform/api/clue_api/arv2/onboarding_*.py platform/api/clue_api/onboarding_routes.py platform/api/clue_api/onboarding_client_binding.py` → zero hits.
- `uv run alembic heads` → one line.
- Write `_memory/2026-09-07-arv2-onboarding-o3-fleet-driver.md` (what landed, the seams, the two rulings — artifact-keyed lineage table; binder outside the lane — test results, checklist, and "acceptance run not yet executed: Task 7 is founder-triggered"). Add the README topic pointer. Commit as `memory: ARV2 onboarding O3 close-out — driver on the fleet, route, seams, checklist`.

---

### Task 7: The acceptance run (founder-triggered; spends ~$2)

**Do not execute without Aryan's explicit go.** It is the O3 exit gate in the plan: one unseeded Insight Health run.

- [ ] **Step 1: Preconditions**
  - `CLUE_ONBOARDING_V2_ENABLED=true` in the worktree `.env`; `CLUE_EXA_API_KEY` set; Postgres reachable; the worktree DB migrated to head.
  - A workspace with one brand and a principal (seed with the Stage-0 provisioning flow or the `seed_project`/`seed_principal` helpers in a one-off script; record the ids).
- [ ] **Step 2: Start the fleet worker and the API** per `DEV_STACK.md`, then `POST /onboarding {"company_domain": "insighthealth.ai", "company_name": "Insight Health"}` with the workspace header and an authenticated session.
- [ ] **Step 3: Poll `GET /onboarding/current`** until terminal. Expected: overview, lineup, catalog_sync, reviews completed; synthesis `empty` (O4 pending); N product_research steps completed or honestly failed; run `completed_with_gaps`.
- [ ] **Step 4: Evidence** — copy `arv2_raw_root/onboarding/<run_id>/**/ledger.jsonl` totals, the document rows (`SELECT path, version, status FROM brand_knowledge_document WHERE workspace_id=...`), and one rendered document, into `.context/arv2-onboarding-o3-acceptance/`; append the numbers to the memory note; commit the note only.
