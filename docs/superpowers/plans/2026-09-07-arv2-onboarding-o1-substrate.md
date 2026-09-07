# ARV2 Onboarding O1 — Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the database and configuration substrate the new onboarding lane needs: the `onboarding_run` / `onboarding_step` / `brand_knowledge_document` tables, the versioned `project_product` set with its spine functions, the `product_set_selection` gate kind with its answer trigger, and every new flag in `Settings` + `.env.example`.

**Architecture:** One hand-written, reversible Alembic migration (hash id, chained off the current head) plus small additive Python: three settings fields, two gate constants and one gate-id derivation in `clue_api.agent_gate`, and three spine functions over the new `project_product` table in `clue_spine`. No driver, no route, no tool, no frontend — those are O3–O6. Nothing here reads or writes a Client-KB claim, a readiness decision, or a Stage-0 run pin (standing rule).

**Tech Stack:** Python 3.12, pydantic-settings, SQLAlchemy async + `text()` SQL, Alembic (raw `op.execute` DDL, named constraints), PostgreSQL 16, pytest (DB tests skip without `CLUE_DATABASE_URL`), `uv`.

**Spec:** `docs/specs/ARV2-ONBOARDING-PLAN.md` §3 (state contract), §6.1–6.2 (artifact statuses), §9 O1 row, §10 (flags), §11 (standing rule); `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §6.2–6.3 (`project_product`, the gate kind and its answer invariants), §10.

## Global Constraints

- **Revision ids are Alembic's random hashes.** Create the migration with `uv run alembic revision -m "arv2 onboarding substrate"`; never hand-pick an id. `down_revision` = the head at the moment you cut it (`uv run alembic heads` must print exactly one; today it is `44039cb83844`). If the D1 lane lands first and the head moved, run `uv run alembic merge -m "merge o1+d1" <head1> <head2>` after rebasing — never renumber.
- **Reversible:** every `upgrade()` statement has its mirror in `downgrade()`; `make db-smoke` (up → base → up) on a **throwaway, per-branch** database is the gate. Never run it against the shared dev DB.
- **Do not touch `libs/clue-core/clue_core/enums.py::Persona`** (nor its DB enum or parity test). D1 owns it.
- **Every flag appears in `.env.example` with its default in the same commit that introduces it** (`tests/arv2/test_settings.py` pattern; a `Literal` field must load from its documented env string).
- **No old-lane gate on any new path:** no Client-KB version, readiness decision, or Stage-0 pin is referenced by any table, constraint, function or test here.
- **Constraints are the enforcement.** Invalid states are refused by CHECK/FK/trigger and asserted as raw `IntegrityError`/`DBAPIError` in tests, never by handler logic.
- **Commits:** local only, never push; no AI attribution trailers; one commit per task.
- **Tests:** DB tests use the `rollback_conn` + `run_async` harness and skip when no DB is reachable; `make check` must stay green without a DB.

---

## File Structure

| Path | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_onboarding_substrate.py` | **Create.** The one migration: three onboarding tables, `project_product` + append-only trigger + the two identity indexes it needs, the gate-kind CHECK union, the redefined `agent_gate_answer_validate()` with the product-set branch. Tasks 2–4 each add a section to this same file. |
| `libs/clue-config/clue_config/settings.py` | **Modify.** Seven `onboarding_*` fields after the ARV2 block (line ~328). |
| `.env.example` | **Modify.** Seven `CLUE_ONBOARDING_*` lines after `CLUE_ARV2_RAW_ROOT` (line ~145) and two `ONBOARDING_SYNTHESIS_AGENT_MODEL*` lines in the agent-model block (after line ~160). |
| `tests/arv2/test_onboarding_settings.py` | **Create.** Defaults + parity + Literal-loading tests. |
| `libs/clue-spine/clue_spine/spine.py` | **Modify.** `ProjectProductSet` model and three functions after `confirm_project_product` (line ~340). |
| `libs/clue-spine/clue_spine/__init__.py` | **Modify.** Export the model and functions. |
| `tests/clue_spine/test_project_product.py` | **Create.** Spine round-trips and the constraint battery. |
| `platform/api/clue_api/agent_gate.py` | **Modify.** `KIND_PRODUCT_SET_SELECTION`, `GATE_KINDS`, `product_set_selection_gate_id`. |
| `tests/db/test_arv2_onboarding_substrate_migration.py` | **Create.** Installed-schema assertions for the three tables and `project_product`; validator-text equivalence with the previous migration when the product-set branch is off. |
| `tests/db/test_unified_agent_gate_migration.py` | **Modify.** Add `product_set_selection` to the kinds list and the new trigger fragments. |
| `tests/api/test_product_set_selection_gate_db.py` | **Create.** The trigger's positive/negative paths for the new kind, using the lane-D4 seed helpers. |
| `_memory/2026-09-07-arv2-onboarding-o1-substrate.md` | **Create.** Close-out note. |

---

### Task 1: Onboarding settings and their env lines

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `arv2_raw_root`, ~line 328)
- Modify: `.env.example` (after `CLUE_ARV2_RAW_ROOT=.artifacts/arv2`, ~line 145; and after `DESIGN_AGENT_MODEL_EFFORT=`, ~line 160)
- Test: `tests/arv2/test_onboarding_settings.py`

**Interfaces:**
- Produces: `Settings.onboarding_v2_enabled: bool`, `onboarding_overview_effort: str`, `onboarding_reviews_effort: str`, `onboarding_product_effort: str`, `onboarding_reviews_phase: Literal["fast","background"]`, `onboarding_max_parallel_runs: int`, `onboarding_persona_evidence_enabled: bool` — read by O3 (driver) and O4 (evidence tool). Env names: `CLUE_ONBOARDING_V2_ENABLED`, `CLUE_ONBOARDING_OVERVIEW_EFFORT`, `CLUE_ONBOARDING_REVIEWS_EFFORT`, `CLUE_ONBOARDING_PRODUCT_EFFORT`, `CLUE_ONBOARDING_REVIEWS_PHASE`, `CLUE_ONBOARDING_MAX_PARALLEL_RUNS`, `CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED`. Plus the documented-only `ONBOARDING_SYNTHESIS_AGENT_MODEL` / `ONBOARDING_SYNTHESIS_AGENT_MODEL_EFFORT` (consumed at O4 when `AgentRole.ONBOARDING_SYNTHESIS` exists).

- [ ] **Step 1: Write the failing tests**

```python
# tests/arv2/test_onboarding_settings.py
"""Track O flags: typed, defaulted, documented in .env.example, loadable from their env string."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Settings

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"

#: ARV2-ONBOARDING-PLAN.md §10 — every onboarding knob and the default the lane ships with.
ONBOARDING_SETTING_DEFAULTS: dict[str, object] = {
    "onboarding_v2_enabled": False,
    "onboarding_overview_effort": "high",
    "onboarding_reviews_effort": "medium",
    "onboarding_product_effort": "medium",
    "onboarding_reviews_phase": "fast",
    "onboarding_max_parallel_runs": 6,
    "onboarding_persona_evidence_enabled": True,
}

#: Documented in the agent-model block today; read by the registry once the role exists (O4).
AGENT_MODEL_LINES = (
    "ONBOARDING_SYNTHESIS_AGENT_MODEL=x-ai/grok-4.6",
    "ONBOARDING_SYNTHESIS_AGENT_MODEL_EFFORT=",
)


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_onboarding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for field_name in ONBOARDING_SETTING_DEFAULTS:
        monkeypatch.delenv(_env_name(field_name), raising=False)


def test_every_onboarding_setting_has_its_shipped_default(unset_onboarding_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, expected in ONBOARDING_SETTING_DEFAULTS.items():
        assert getattr(settings, field_name) == expected, field_name


def test_the_lane_flag_ships_off() -> None:
    """Flips only after O7 acceptance (plan §10)."""
    assert Settings.model_fields["onboarding_v2_enabled"].default is False


def test_reviews_phase_loads_from_its_env_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Literal that rejects its own documented env form is a bug (CLAUDE.md parity rule)."""
    monkeypatch.setenv("CLUE_ONBOARDING_REVIEWS_PHASE", "background")
    assert Settings(_env_file=None).onboarding_reviews_phase == "background"
    monkeypatch.setenv("CLUE_ONBOARDING_REVIEWS_PHASE", "sideways")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_max_parallel_runs_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_ONBOARDING_MAX_PARALLEL_RUNS", "0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_every_onboarding_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in ONBOARDING_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        shipped = str(default).lower() if isinstance(default, bool) else str(default)
        assert documented.group(1).strip() == shipped, field_name


def test_the_synthesis_agent_model_lines_are_documented() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in AGENT_MODEL_LINES:
        assert re.search(rf"^{re.escape(line)}$", text, re.MULTILINE), line
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_onboarding_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'onboarding_v2_enabled'` and the `.env.example` assertions fail.

- [ ] **Step 3: Add the settings fields**

In `libs/clue-config/clue_config/settings.py`, directly after the `arv2_raw_root` field (the last line of the "ARV2 research lane (R1)" block), add:

```python
    # --- ARV2 onboarding lane (Track O; ARV2-ONBOARDING-PLAN.md §10) --------------------------
    # Routes ``POST /onboarding`` to the new fleet driver (O3). Ships dark until O7 acceptance;
    # ``self_serve_provisioning_enabled`` (the old recon) stays false regardless.
    # Env: ``CLUE_ONBOARDING_V2_ENABLED``.
    onboarding_v2_enabled: bool = False
    # Exa Agent effort for the company-overview run (ARV2-COMPANY-OVERVIEW-CONTRACT.md §1).
    # Env: ``CLUE_ONBOARDING_OVERVIEW_EFFORT``.
    onboarding_overview_effort: str = "high"
    # Exa Agent effort for the customer-reviews run (plan §4.3). Env: ``CLUE_ONBOARDING_REVIEWS_EFFORT``.
    onboarding_reviews_effort: str = "medium"
    # Exa Agent effort for each per-product research run (plan §4.4; ruling O-D2 — raise to
    # ``high`` per deployment if the product files read thin). Env: ``CLUE_ONBOARDING_PRODUCT_EFFORT``.
    onboarding_product_effort: str = "medium"
    # When the reviews run happens (ruling O-D3: ``fast``). Env: ``CLUE_ONBOARDING_REVIEWS_PHASE``.
    onboarding_reviews_phase: Literal["fast", "background"] = "fast"
    # Cap on concurrent background per-product Exa Agent runs. Env: ``CLUE_ONBOARDING_MAX_PARALLEL_RUNS``.
    onboarding_max_parallel_runs: int = Field(default=6, ge=1)
    # The governed ``exa_search_evidence@1`` tool the synthesis agent may call once per persona
    # role (ruling O-D6: on). Env: ``CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED``.
    onboarding_persona_evidence_enabled: bool = True
```

Check the module's imports already include `Literal` (from `typing`) and `Field` (from `pydantic`); add whichever is missing to the existing import lines.

- [ ] **Step 4: Add the env lines**

In `.env.example`, directly after `CLUE_ARV2_RAW_ROOT=.artifacts/arv2` add:

```dotenv

# --- ARV2 onboarding lane (Track O; ARV2-ONBOARDING-PLAN.md §10) -----------
# Routes POST /onboarding to the new fleet driver. Ships dark until O7 acceptance.
CLUE_ONBOARDING_V2_ENABLED=false
# Exa Agent effort per research call (fixed prices: medium $0.10, high $0.50 per run).
CLUE_ONBOARDING_OVERVIEW_EFFORT=high
CLUE_ONBOARDING_REVIEWS_EFFORT=medium
CLUE_ONBOARDING_PRODUCT_EFFORT=medium
# When the customer-reviews run happens: fast | background (ruling O-D3).
CLUE_ONBOARDING_REVIEWS_PHASE=fast
# Cap on concurrent background per-product runs.
CLUE_ONBOARDING_MAX_PARALLEL_RUNS=6
# The persona evidence tool (one deep-reasoning search per persona role; ruling O-D6).
CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED=true
```

In the "Agent model configuration" block, directly after `DESIGN_AGENT_MODEL_EFFORT=` add:

```dotenv
# Onboarding synthesis agent (Track O, O4). Ruling O-D1: grok-4.6 at the model's default
# reasoning — leave EFFORT blank. Read by the registry once AgentRole.ONBOARDING_SYNTHESIS exists.
ONBOARDING_SYNTHESIS_AGENT_MODEL=x-ai/grok-4.6
ONBOARDING_SYNTHESIS_AGENT_MODEL_EFFORT=
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/arv2/test_onboarding_settings.py tests/arv2/test_settings.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example tests/arv2/test_onboarding_settings.py
git commit -m "feat(config): ARV2 onboarding lane flags (Track O §10) — seven CLUE_ONBOARDING_* settings with env parity, synthesis-agent model lines documented"
```

---

### Task 2: The migration — `onboarding_run`, `onboarding_step`, `brand_knowledge_document`

**Files:**
- Create: `alembic/versions/<hash>_arv2_onboarding_substrate.py` (via `alembic revision`)
- Test: `tests/db/test_arv2_onboarding_substrate_migration.py`

**Interfaces:**
- Produces: the three tables exactly as in the DDL below. O3's driver inserts into all three; O5's read endpoints select from `brand_knowledge_document`.

- [ ] **Step 1: Cut the migration file**

```bash
uv run alembic heads            # must print exactly ONE revision; note it — it is your down_revision
uv run alembic revision -m "arv2 onboarding substrate"
```

Open the generated file. Keep the generated `revision` id. Replace the docstring and body with the following (paste the module docstring conventions block verbatim from `alembic/versions/fc3e5477e872_allow_explicit_committee_job_without_.py` lines 1–12, adjusting the title):

```python
"""arv2 onboarding substrate

Revision ID: <generated>
Revises: <the head you noted>
Create Date: <generated>

Track O substrate (docs/specs/ARV2-ONBOARDING-PLAN.md §3, §6; ARV2-PRODUCT-CATALOG-CONTRACT.md §6):
onboarding runs/steps, brand knowledge documents, the versioned project product set, and the
product_set_selection human gate. Nothing here references a Client-KB version, a readiness
decision, or a Stage-0 run pin (standing rule, catalog contract §10).

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Append-only where stated; UTC ``timestamptz``; named constraints; forward + reverse.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<the head you noted>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_onboarding_tables()


def downgrade() -> None:
    _drop_onboarding_tables()


# --- §3 onboarding run / step / document ------------------------------------------------------


def _create_onboarding_tables() -> None:
    op.execute(
        """
        CREATE TABLE onboarding_run (
            run_id               uuid NOT NULL,
            workspace_id         text NOT NULL,
            brand_id             text NOT NULL,
            client_entity_id     uuid,
            company_domain       text NOT NULL,
            requested_by_user_id text NOT NULL,
            requested_at         timestamptz NOT NULL DEFAULT now(),
            status               text NOT NULL DEFAULT 'queued',
            lane_version         text NOT NULL DEFAULT 'onboarding-v2',
            cost_usd             numeric(12, 6) NOT NULL DEFAULT 0,
            finished_at          timestamptz,

            CONSTRAINT onboarding_run_pkey PRIMARY KEY (run_id),
            CONSTRAINT onboarding_run_status CHECK (status IN
                ('queued', 'running', 'completed', 'completed_with_gaps', 'failed')),
            CONSTRAINT onboarding_run_finished_when_terminal CHECK
                ((status IN ('queued', 'running')) = (finished_at IS NULL)),
            CONSTRAINT onboarding_run_domain_nonblank CHECK (length(btrim(company_domain)) > 0),
            CONSTRAINT onboarding_run_cost_nonnegative CHECK (cost_usd >= 0),
            CONSTRAINT onboarding_run_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT onboarding_run_user_fk FOREIGN KEY (requested_by_user_id)
                REFERENCES platform_user (user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX onboarding_run_workspace_requested "
        "ON onboarding_run (workspace_id, requested_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE onboarding_step (
            step_id            uuid NOT NULL,
            run_id             uuid NOT NULL,
            workspace_id       text NOT NULL,
            kind               text NOT NULL,
            subject_ref        text,
            phase              text NOT NULL,
            status             text NOT NULL DEFAULT 'queued',
            provider_run_id    text,
            raw_artifact_key   text,
            output_document_id uuid,
            cost_usd           numeric(12, 6) NOT NULL DEFAULT 0,
            searches           integer NOT NULL DEFAULT 0,
            started_at         timestamptz,
            finished_at        timestamptz,
            failure_code       text,
            failure_message    text,

            CONSTRAINT onboarding_step_pkey PRIMARY KEY (step_id),
            CONSTRAINT onboarding_step_run_fk FOREIGN KEY (run_id)
                REFERENCES onboarding_run (run_id),
            CONSTRAINT onboarding_step_kind CHECK (kind IN
                ('overview', 'lineup', 'catalog_sync', 'reviews', 'synthesis', 'product_research')),
            CONSTRAINT onboarding_step_phase CHECK (phase IN ('fast', 'background')),
            CONSTRAINT onboarding_step_status CHECK (status IN
                ('queued', 'running', 'completed', 'empty', 'failed')),
            CONSTRAINT onboarding_step_failure_pair CHECK
                ((status = 'failed') = (failure_code IS NOT NULL)),
            CONSTRAINT onboarding_step_finished_when_terminal CHECK
                ((status IN ('queued', 'running')) = (finished_at IS NULL)),
            CONSTRAINT onboarding_step_cost_nonnegative CHECK (cost_usd >= 0 AND searches >= 0)
        )
        """
    )
    # subject_ref is NULL for the single-subject kinds; COALESCE makes the identity unique anyway.
    op.execute(
        "CREATE UNIQUE INDEX onboarding_step_identity "
        "ON onboarding_step (run_id, kind, COALESCE(subject_ref, ''))"
    )
    op.execute("CREATE INDEX onboarding_step_run ON onboarding_step (run_id, phase, status)")
    op.execute(
        """
        CREATE TABLE brand_knowledge_document (
            document_id            uuid NOT NULL,
            workspace_id           text NOT NULL,
            brand_id               text NOT NULL,
            folder                 text NOT NULL,
            path                   text NOT NULL,
            kind                   text NOT NULL,
            version                integer NOT NULL,
            status                 text NOT NULL DEFAULT 'running',
            artifact_key           text,
            artifact_sha256        text,
            produced_by_step_id    uuid,
            produced_by_turn_id    uuid,
            supersedes_document_id uuid,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT brand_knowledge_document_pkey PRIMARY KEY (document_id),
            CONSTRAINT brand_knowledge_document_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT brand_knowledge_document_step_fk FOREIGN KEY (produced_by_step_id)
                REFERENCES onboarding_step (step_id),
            CONSTRAINT brand_knowledge_document_turn_fk FOREIGN KEY (produced_by_turn_id)
                REFERENCES agent_turn (id),
            CONSTRAINT brand_knowledge_document_supersedes_fk FOREIGN KEY (supersedes_document_id)
                REFERENCES brand_knowledge_document (document_id),
            CONSTRAINT brand_knowledge_document_folder CHECK (folder IN
                ('company', 'product', 'audience', 'proof', 'design')),
            CONSTRAINT brand_knowledge_document_kind CHECK (kind IN
                ('company-overview', 'product-catalog', 'product-research', 'customer-reviews',
                 'icp-definition', 'audience-persona', 'design-brief')),
            CONSTRAINT brand_knowledge_document_status CHECK (status IN
                ('running', 'ready', 'empty', 'failed', 'proposed', 'confirmed', 'superseded')),
            CONSTRAINT brand_knowledge_document_version_positive CHECK (version >= 1),
            CONSTRAINT brand_knowledge_document_path_in_folder CHECK (path LIKE folder || '/%'),
            CONSTRAINT brand_knowledge_document_one_producer CHECK
                (NOT (produced_by_step_id IS NOT NULL AND produced_by_turn_id IS NOT NULL)),
            -- A served status means bytes exist: key + a real sha256.
            CONSTRAINT brand_knowledge_document_body_when_served CHECK
                (status NOT IN ('ready', 'proposed', 'confirmed', 'superseded')
                 OR (artifact_key IS NOT NULL AND artifact_sha256 ~ '^[0-9a-f]{64}$')),
            CONSTRAINT brand_knowledge_document_path_version
                UNIQUE (workspace_id, brand_id, path, version)
        )
        """
    )
    op.execute(
        "CREATE INDEX brand_knowledge_document_tree "
        "ON brand_knowledge_document (workspace_id, brand_id, folder, path, version DESC)"
    )
    op.execute(
        "ALTER TABLE onboarding_step ADD CONSTRAINT onboarding_step_output_document_fk "
        "FOREIGN KEY (output_document_id) REFERENCES brand_knowledge_document (document_id)"
    )


def _drop_onboarding_tables() -> None:
    op.execute("ALTER TABLE onboarding_step DROP CONSTRAINT onboarding_step_output_document_fk")
    op.execute("DROP INDEX brand_knowledge_document_tree")
    op.execute("DROP TABLE brand_knowledge_document")
    op.execute("DROP INDEX onboarding_step_run")
    op.execute("DROP INDEX onboarding_step_identity")
    op.execute("DROP TABLE onboarding_step")
    op.execute("DROP INDEX onboarding_run_workspace_requested")
    op.execute("DROP TABLE onboarding_run")
```

- [ ] **Step 2: Write the failing installed-schema test**

```python
# tests/db/test_arv2_onboarding_substrate_migration.py
"""Installed-schema guards for the Track O substrate (ARV2-ONBOARDING-PLAN.md §3, §6)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _REPO_ROOT / "alembic" / "versions"


def _migration_module(prefix: str):
    """Load one migration module by its file-name prefix (they are not importable by name)."""
    (path,) = _VERSIONS.glob(f"{prefix}_*.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _onboarding_migration():
    (path,) = _VERSIONS.glob("*_arv2_onboarding_substrate.py")
    return _migration_module(path.stem.split("_")[0])


async def _constraints(conn, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = CAST(:table AS regclass)"
        ),
        {"table": table},
    )
    return {str(row.conname): str(row.definition) for row in rows}


@pytest.mark.usefixtures("require_db")
def test_the_three_onboarding_tables_carry_their_state_contract() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            run = await _constraints(conn, "onboarding_run")
            step = await _constraints(conn, "onboarding_step")
            doc = await _constraints(conn, "brand_knowledge_document")

        for status in ("queued", "running", "completed", "completed_with_gaps", "failed"):
            assert status in run["onboarding_run_status"]
        assert "finished_at IS NULL" in run["onboarding_run_finished_when_terminal"]
        assert "brand" in run["onboarding_run_brand_fk"]

        for kind in ("overview", "lineup", "catalog_sync", "reviews", "synthesis", "product_research"):
            assert kind in step["onboarding_step_kind"]
        assert "'fast'" in step["onboarding_step_phase"] and "'background'" in step["onboarding_step_phase"]
        assert "failure_code IS NOT NULL" in step["onboarding_step_failure_pair"]
        assert "brand_knowledge_document" in step["onboarding_step_output_document_fk"]

        for status in ("running", "ready", "empty", "failed", "proposed", "confirmed", "superseded"):
            assert status in doc["brand_knowledge_document_status"]
        for folder in ("company", "product", "audience", "proof", "design"):
            assert folder in doc["brand_knowledge_document_folder"]
        assert "[0-9a-f]{64}" in doc["brand_knowledge_document_body_when_served"]
        assert "path, version" in doc["brand_knowledge_document_path_version"]

    run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_a_document_cannot_be_served_without_bytes() -> None:
    """status=ready with no artifact is the exact lie the CHECK exists to refuse."""
    from sqlalchemy.exc import IntegrityError

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(text(
                    "INSERT INTO workspace (workspace_id, name) VALUES ('ws-o1-doc', 'O1') "
                    "ON CONFLICT DO NOTHING"
                ))
                await conn.execute(text(
                    "INSERT INTO brand (brand_id, workspace_id, name) "
                    "VALUES ('brd-o1-doc', 'ws-o1-doc', 'O1') ON CONFLICT DO NOTHING"
                ))
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text(
                            "INSERT INTO brand_knowledge_document "
                            "(document_id, workspace_id, brand_id, folder, path, kind, version, status) "
                            "VALUES (gen_random_uuid(), 'ws-o1-doc', 'brd-o1-doc', 'company', "
                            " 'company/overview.md', 'company-overview', 1, 'ready')"
                        ))
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text(
                            "INSERT INTO brand_knowledge_document "
                            "(document_id, workspace_id, brand_id, folder, path, kind, version, status) "
                            "VALUES (gen_random_uuid(), 'ws-o1-doc', 'brd-o1-doc', 'company', "
                            " 'product/overview.md', 'company-overview', 1, 'running')"
                        ))
            finally:
                await trans.rollback()

    run_async(scenario())
```

Check the `workspace` and `brand` insert column lists against `alembic/versions/98422adaaa38_object_spine.py` before running (the `name` column exists on both; if `brand` requires more NOT NULL columns, add them with placeholder values in the test).

- [ ] **Step 3: Run the test to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_onboarding_substrate_migration.py -v`
Expected: FAIL — `relation "onboarding_run" does not exist` (the test hits head; the migration is not applied yet), or SKIP if no DB is reachable (then start one with `make db-up` on a throwaway DSN before continuing).

- [ ] **Step 4: Apply and verify**

Run: `set -a; source .env; set +a; uv run alembic upgrade head && uv run pytest tests/db/test_arv2_onboarding_substrate_migration.py tests/db/test_db_migrations.py -v`
Expected: PASS, including `test_up_down_up_is_clean`.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/*_arv2_onboarding_substrate.py tests/db/test_arv2_onboarding_substrate_migration.py
git commit -m "feat(db): ARV2 onboarding substrate — onboarding_run, onboarding_step, brand_knowledge_document with the §3 state CHECKs (reversible)"
```

---

### Task 3: `project_product` — the versioned set, its trigger, and the spine functions

**Files:**
- Modify: `alembic/versions/<hash>_arv2_onboarding_substrate.py` (add a section)
- Modify: `libs/clue-spine/clue_spine/spine.py` (after `confirm_project_product`, ~line 340)
- Modify: `libs/clue-spine/clue_spine/__init__.py`
- Test: `tests/clue_spine/test_project_product.py`

**Interfaces:**
- Produces:
  - `class ProjectProductSet(BaseModel)`: `workspace_id: str`, `project_id: str`, `brand_id: str`, `selection_version: int`, `product_ids: tuple[str, ...]`, `gate_id: UUID`, `confirmed_by_user_id: str`, `confirmed_at: UtcDatetime`.
  - `async def confirm_project_product_set(conn, *, workspace_id: str, project_id: str, product_ids: Sequence[str], gate_id: UUID, confirmed_by_user_id: str) -> ProjectProductSet | None` — mints `max(selection_version)+1` under a row lock on the project; returns `None` when the project is absent/foreign or any product is not a same-workspace, same-brand product; raises `ValueError` on an empty list.
  - `async def current_project_product_set(conn, *, workspace_id: str, project_id: str) -> ProjectProductSet | None`.
  - `async def list_project_product_sets(conn, *, workspace_id: str, project_id: str) -> list[ProjectProductSet]` — oldest first.
  - O6's answer route calls `confirm_project_product_set`; O3's launcher and the L2 index card read `current_project_product_set`.

- [ ] **Step 1: Write the failing spine tests**

```python
# tests/clue_spine/test_project_product.py
"""The versioned project product set (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.2; rulings P1/P2)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import (
    confirm_project_product_set,
    create_brand,
    create_product,
    create_project,
    create_workspace,
    current_project_product_set,
    list_project_product_sets,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")

USER_ID = "usr_o1_product_set"


async def _seed(conn: AsyncConnection) -> tuple[str, str, str, list[str]]:
    ws = await create_workspace(conn, name="Insight")
    brand = await create_brand(conn, workspace_id=ws.workspace_id, name="Insight Health")
    project = await create_project(
        conn, workspace_id=ws.workspace_id, brand_id=brand.brand_id, name="Q4 GI outreach"
    )
    await conn.execute(
        text(
            "INSERT INTO platform_user (user_id, display_name) VALUES (:id, :name) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"id": USER_ID, "name": "O1 product set"},
    )
    products = [
        await create_product(conn, brand_id=brand.brand_id, workspace_id=ws.workspace_id, name=n)
        for n in ("Aura AI Scribe", "Phone Triage AI Agent", "MagicFlow")
    ]
    return ws.workspace_id, brand.brand_id, project.project_id, [p.product_id for p in products]


def test_confirming_a_set_mints_version_one_and_the_current_set_reads_it_back() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id, project_id, ids = await _seed(conn)
            gate_id = uuid4()
            confirmed = await confirm_project_product_set(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_ids=[ids[0], ids[1], ids[0]],  # a repeat collapses, order kept
                gate_id=gate_id,
                confirmed_by_user_id=USER_ID,
            )
            assert confirmed is not None
            assert confirmed.selection_version == 1
            assert confirmed.product_ids == (ids[0], ids[1])
            assert confirmed.brand_id == brand_id
            assert confirmed.gate_id == gate_id
            assert await current_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id
            ) == confirmed

    run_async(scenario())


def test_a_second_confirmation_is_a_new_version_and_the_old_one_survives() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, ids = await _seed(conn)
            first = await confirm_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id,
                product_ids=[ids[0]], gate_id=uuid4(), confirmed_by_user_id=USER_ID,
            )
            second = await confirm_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id,
                product_ids=[ids[2], ids[1]], gate_id=uuid4(), confirmed_by_user_id=USER_ID,
            )
            assert first is not None and second is not None
            assert (first.selection_version, second.selection_version) == (1, 2)
            history = await list_project_product_sets(
                conn, workspace_id=workspace_id, project_id=project_id
            )
            assert [s.selection_version for s in history] == [1, 2]
            assert history[0].product_ids == (ids[0],)
            assert history[1].product_ids == (ids[2], ids[1])
            current = await current_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id
            )
            assert current == second

    run_async(scenario())


def test_no_set_yet_reads_as_none_and_an_empty_set_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, _ = await _seed(conn)
            assert await current_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id
            ) is None
            with pytest.raises(ValueError):
                await confirm_project_product_set(
                    conn, workspace_id=workspace_id, project_id=project_id,
                    product_ids=[], gate_id=uuid4(), confirmed_by_user_id=USER_ID,
                )

    run_async(scenario())


def test_a_product_of_another_brand_or_workspace_returns_none_without_a_partial_write() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, ids = await _seed(conn)
            other_ws = await create_workspace(conn, name="Other")
            other_brand = await create_brand(conn, workspace_id=other_ws.workspace_id, name="Other")
            foreign = await create_product(
                conn, brand_id=other_brand.brand_id, workspace_id=other_ws.workspace_id, name="Foreign"
            )
            result = await confirm_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id,
                product_ids=[ids[0], foreign.product_id], gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            assert result is None
            assert await list_project_product_sets(
                conn, workspace_id=workspace_id, project_id=project_id
            ) == []
            # An absent project is the same honest None.
            assert await confirm_project_product_set(
                conn, workspace_id=workspace_id, project_id="prj_missing",
                product_ids=[ids[0]], gate_id=uuid4(), confirmed_by_user_id=USER_ID,
            ) is None

    run_async(scenario())


def test_rows_are_append_only() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, ids = await _seed(conn)
            await confirm_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id,
                product_ids=[ids[0]], gate_id=uuid4(), confirmed_by_user_id=USER_ID,
            )
            for statement in (
                "UPDATE project_product SET selection_version = 9 WHERE project_id = :p",
                "DELETE FROM project_product WHERE project_id = :p",
            ):
                with pytest.raises(DBAPIError):
                    async with conn.begin_nested():
                        await conn.execute(text(statement), {"p": project_id})

    run_async(scenario())
```

`platform_user` (migration `9398ae4467e3`) has `user_id` (PK), nullable `display_name`, and `status` defaulting to `active`; the seed above is the complete required set.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/clue_spine/test_project_product.py -v`
Expected: FAIL — `ImportError: cannot import name 'confirm_project_product_set' from 'clue_spine'`.

- [ ] **Step 3: Add the DDL section to the migration**

In the migration file, change `upgrade()` / `downgrade()` to:

```python
def upgrade() -> None:
    _create_onboarding_tables()
    _create_project_product()


def downgrade() -> None:
    _drop_project_product()
    _drop_onboarding_tables()
```

and add:

```python
# --- §6.2 the versioned project product set (rulings P1/P2) ------------------------------------


def _create_project_product() -> None:
    # The composite FKs below need matching unique targets; product_id / project_id are already
    # primary keys, so these indexes add no new invariant — they only make the triple referenceable.
    op.execute(
        "CREATE UNIQUE INDEX product_identity_triple ON product (product_id, brand_id, workspace_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX project_identity_triple ON project (project_id, brand_id, workspace_id)"
    )
    op.execute(
        """
        CREATE TABLE project_product (
            workspace_id          text NOT NULL,
            project_id            text NOT NULL,
            brand_id              text NOT NULL,
            product_id            text NOT NULL,
            selection_version     integer NOT NULL,
            gate_id               uuid NOT NULL,
            confirmed_by_user_id  text NOT NULL,
            confirmed_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT project_product_pkey PRIMARY KEY (project_id, selection_version, product_id),
            CONSTRAINT project_product_version_positive CHECK (selection_version >= 1),
            -- Same workspace AND same brand, structurally (the pin project.product_id had).
            CONSTRAINT project_product_product_fk FOREIGN KEY (product_id, brand_id, workspace_id)
                REFERENCES product (product_id, brand_id, workspace_id),
            CONSTRAINT project_product_project_fk FOREIGN KEY (project_id, brand_id, workspace_id)
                REFERENCES project (project_id, brand_id, workspace_id),
            CONSTRAINT project_product_user_fk FOREIGN KEY (confirmed_by_user_id)
                REFERENCES platform_user (user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX project_product_current "
        "ON project_product (project_id, selection_version DESC)"
    )
    # gate_id is the answered product_set_selection gate. It is deliberately NOT a foreign key:
    # clue_spine sits below clue_api.agent_gate, and the answer row (agent_gate_answer, PK gate_id)
    # is the durable proof the route checks before calling confirm_project_product_set.
    op.execute(
        "CREATE TRIGGER project_product_append_only "
        "BEFORE UPDATE OR DELETE ON project_product FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def _drop_project_product() -> None:
    op.execute("DROP TRIGGER project_product_append_only ON project_product")
    op.execute("DROP INDEX project_product_current")
    op.execute("DROP TABLE project_product")
    op.execute("DROP INDEX project_identity_triple")
    op.execute("DROP INDEX product_identity_triple")
```

`execution_reject_append_only_mutation()` is created by `128c83d5e151` (the C5.1 execution journal) and reused by `1043a61823f1`; its body is an unconditional `RAISE EXCEPTION '% is append-only', TG_TABLE_NAME`, so `BEFORE UPDATE OR DELETE` refuses both events.

- [ ] **Step 4: Add the spine model and functions**

In `libs/clue-spine/clue_spine/spine.py`, add `from collections.abc import Sequence` and `from uuid import UUID` to the imports if absent, then after `confirm_project_product` add:

```python
# --- project product set (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.2) -----------
_PROJECT_PRODUCT_COLUMNS = (
    "workspace_id, project_id, brand_id, product_id, selection_version, gate_id, "
    "confirmed_by_user_id, confirmed_at"
)


class ProjectProductSet(BaseModel):
    """One confirmed version of a project's product set. Rows are append-only; the current set is
    the highest ``selection_version``; a run pins the version it started under (ruling P2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    project_id: str
    brand_id: str
    selection_version: int
    product_ids: tuple[str, ...]
    gate_id: UUID
    confirmed_by_user_id: str
    confirmed_at: UtcDatetime


def _rows_to_sets(rows: list[dict[str, Any]]) -> list[ProjectProductSet]:
    """Group version rows (already ordered by version, then insertion) into sets."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["selection_version"]), []).append(row)
    sets: list[ProjectProductSet] = []
    for version, members in sorted(grouped.items()):
        head = members[0]
        sets.append(
            ProjectProductSet(
                workspace_id=head["workspace_id"],
                project_id=head["project_id"],
                brand_id=head["brand_id"],
                selection_version=version,
                product_ids=tuple(m["product_id"] for m in members),
                gate_id=head["gate_id"],
                confirmed_by_user_id=head["confirmed_by_user_id"],
                confirmed_at=head["confirmed_at"],
            )
        )
    return sets


async def list_project_product_sets(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> list[ProjectProductSet]:
    """Every confirmed version of the project's product set, oldest first; members keep the
    order the human chose them in (``ctid`` reflects insertion order within one version)."""
    result = await conn.execute(
        text(
            f"SELECT {_PROJECT_PRODUCT_COLUMNS} FROM project_product "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            "ORDER BY selection_version, ctid"
        ),
        {"workspace_id": workspace_id, "project_id": project_id},
    )
    return _rows_to_sets([dict(row) for row in result.mappings().all()])


async def current_project_product_set(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> ProjectProductSet | None:
    sets = await list_project_product_sets(conn, workspace_id=workspace_id, project_id=project_id)
    return sets[-1] if sets else None


async def confirm_project_product_set(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_ids: Sequence[str],
    gate_id: UUID,
    confirmed_by_user_id: str,
) -> ProjectProductSet | None:
    """Human-authorized confirmation of the whole set as a new version (rulings P1/P2).

    Returns ``None`` — without revealing which coordinate was foreign — when the project is absent
    from the workspace or any product is not a product of the project's own brand and workspace.
    Repeats in ``product_ids`` collapse, first occurrence wins. Raises ``ValueError`` on an empty
    list: an empty set is not a selection.
    """
    ordered = list(dict.fromkeys(product_ids))
    if not ordered:
        raise ValueError("a project product set needs at least one product")
    locked = (
        await conn.execute(
            text(
                "SELECT brand_id FROM project "
                "WHERE project_id = :project_id AND workspace_id = :workspace_id FOR UPDATE"
            ),
            {"project_id": project_id, "workspace_id": workspace_id},
        )
    ).mappings().first()
    if locked is None:
        return None
    brand_id = str(locked["brand_id"])
    known = (
        await conn.execute(
            text(
                "SELECT product_id FROM product WHERE product_id = ANY(:ids) "
                "AND brand_id = :brand_id AND workspace_id = :workspace_id"
            ),
            {"ids": ordered, "brand_id": brand_id, "workspace_id": workspace_id},
        )
    ).scalars().all()
    if set(known) != set(ordered):
        return None
    next_version = (
        await conn.execute(
            text(
                "SELECT COALESCE(MAX(selection_version), 0) + 1 FROM project_product "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
    ).scalar_one()
    for product_id in ordered:
        await conn.execute(
            text(
                "INSERT INTO project_product (workspace_id, project_id, brand_id, product_id, "
                " selection_version, gate_id, confirmed_by_user_id) "
                "VALUES (:workspace_id, :project_id, :brand_id, :product_id, :version, :gate_id, "
                " :user_id)"
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "brand_id": brand_id,
                "product_id": product_id,
                "version": int(next_version),
                "gate_id": gate_id,
                "user_id": confirmed_by_user_id,
            },
        )
    sets = await list_project_product_sets(conn, workspace_id=workspace_id, project_id=project_id)
    return sets[-1]
```

In `libs/clue-spine/clue_spine/__init__.py`, import and export `ProjectProductSet`, `confirm_project_product_set`, `current_project_product_set`, `list_project_product_sets` (add each to the import list and to `__all__`, alphabetically among their neighbours).

- [ ] **Step 5: Apply the migration section and run the tests**

Run: `set -a; source .env; set +a; uv run alembic downgrade -1 && uv run alembic upgrade head && uv run pytest tests/clue_spine/test_project_product.py tests/clue_spine/test_spine.py -v`
Expected: all PASS (the existing spine suite proves the two new unique indexes changed nothing).

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/*_arv2_onboarding_substrate.py libs/clue-spine/clue_spine/spine.py libs/clue-spine/clue_spine/__init__.py tests/clue_spine/test_project_product.py
git commit -m "feat(spine,db): project_product — the versioned, append-only project product set with confirm/current/list functions (rulings P1/P2)"
```

---

### Task 4: The `product_set_selection` gate kind and its answer trigger

**Files:**
- Modify: `alembic/versions/<hash>_arv2_onboarding_substrate.py` (add a section)
- Modify: `platform/api/clue_api/agent_gate.py:42-78` (exports, constants) and after `product_selection_gate_id` (~line 240)
- Modify: `tests/db/test_unified_agent_gate_migration.py:135-160`
- Test: `tests/db/test_arv2_onboarding_substrate_migration.py` (add two tests), `tests/api/test_product_set_selection_gate_db.py` (new)

**Interfaces:**
- Produces: `KIND_PRODUCT_SET_SELECTION = "product_set_selection"` in `GATE_KINDS`; `product_set_selection_gate_id(*, workspace_id: str, turn_id: UUID, subject_ref: str, expected_subject_sha256: str) -> UUID`. The DB accepts an `approved` answer for this kind only with `decision_payload = {"selected_option_refs": [...]}` (≥ 1, no repeats, every entry a `products[].product_id` of the gate's snapshot) and `selected_option_ref IS NULL`; `rejected`/`revised` carry an empty payload. O6's route and gate tool consume this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/db/test_arv2_onboarding_substrate_migration.py`:

```python
def _normalized_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_the_validator_without_the_product_set_branch_is_the_previous_migrations_text() -> None:
    """downgrade() must reinstall exactly what 064ad0f43519 installed — proven by text, not hope."""
    onboarding = _onboarding_migration()
    previous = _migration_module("064ad0f43519")
    assert _normalized_sql(onboarding._answer_validator(product_set=False)) == _normalized_sql(
        previous._answer_validator(discovery_configuration_revision=True)
    )


def test_the_validator_with_the_branch_adds_only_the_product_set_rules() -> None:
    onboarding = _onboarding_migration()
    with_branch = onboarding._answer_validator(product_set=True)
    for fragment in (
        "presented.kind = 'product_set_selection'",
        "selected_option_refs",
        "jsonb_array_elements_text",
        "candidate ->> 'product_id' = chosen.value",
        "product-set approval cannot repeat a product",
    ):
        assert fragment in with_branch
    assert "presented.kind = 'product_selection'" in with_branch  # the old kind is kept verbatim
```

In `tests/db/test_unified_agent_gate_migration.py`, add `"product_set_selection",` to the kinds tuple (after `"product_selection",`) and these fragments to the `enforced_fragment` tuple: `"presented.kind = 'product_set_selection'"`, `"selected_option_refs"`, `"candidate ->> 'product_id' = chosen.value"`.

Create `tests/api/test_product_set_selection_gate_db.py`:

```python
"""The product_set_selection answer trigger (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3).

Reuses the lane-D4 seed (a real workspace, project, thread, human turn and submission) so the
answer's foreign keys are real; presents a product-set gate and drives the trigger's rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from clue_api.agent_gate import (
    KIND_PRODUCT_SET_SELECTION,
    insert_gate,
    insert_gate_answer,
    product_set_selection_gate_id,
)
from clue_api.turn_action import derive_turn_action_ref
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

DIGEST = "c" * 64
CANDIDATES = [
    {"product_id": "prd_aura", "name": "Aura AI Scribe", "short_description": "…",
     "aliases": [], "status": "active"},
    {"product_id": "prd_triage", "name": "Phone Triage AI Agent", "short_description": "…",
     "aliases": [], "status": "active"},
]


@pytest.fixture
def require_gate_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_gate_db")


async def _present_set_gate(conn: Any, seeded: Any) -> Any:
    subject_ref = "client-product-catalog:11111111-1111-4111-8111-111111111111:v1"
    gate_id = product_set_selection_gate_id(
        workspace_id=seeded.workspace_id,
        turn_id=seeded.turn_id,
        subject_ref=subject_ref,
        expected_subject_sha256=DIGEST,
    )
    row, _ = await insert_gate(
        conn,
        gate_id=gate_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.turn_id,
        kind=KIND_PRODUCT_SET_SELECTION,
        subject_ref=subject_ref,
        subject_revision=1,
        expected_subject_sha256=DIGEST,
        subject_snapshot={"products": CANDIDATES, "omitted_count": 0},
        max_spend_cents=None,
        currency=None,
        addressee_user_id=USER_ID,
    )
    return row


async def _answer(conn: Any, seeded: Any, gate: Any, decision: str, payload: dict[str, Any] | None):
    return await insert_gate_answer(
        conn,
        gate_id=gate.gate_id,
        workspace_id=seeded.workspace_id,
        turn_id=seeded.turn_id,
        action_ref=derive_turn_action_ref(seeded.turn_id),
        decision=decision,
        expected_subject_sha256=gate.expected_subject_sha256,
        decision_payload=payload,
        answered_by_user_id=USER_ID,
    )


def test_an_approval_names_a_non_empty_subset_of_the_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o1-set-ok", label="set-ok")
            gate = await _present_set_gate(conn, seeded)
            answer = await _answer(
                conn, seeded, gate, "approved", {"selected_option_refs": ["prd_triage", "prd_aura"]}
            )
            assert answer.decision == "approved"
            assert answer.decision_payload == {"selected_option_refs": ["prd_triage", "prd_aura"]}
            assert answer.selected_option_ref is None

    run_async(scenario())


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        ({}, "empty"),
        ({"selected_option_refs": []}, "no-entries"),
        ({"selected_option_refs": ["prd_aura", "prd_aura"]}, "repeat"),
        ({"selected_option_refs": ["prd_aura", "prd_stranger"]}, "non-member"),
        ({"selected_option_refs": ["prd_aura"], "revision_request": "x"}, "extra-key"),
    ],
)
def test_the_trigger_refuses_every_bad_approval(tmp_path: Path, payload: dict, label: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-o1-set-{label}", label=f"set-{label}")
            gate = await _present_set_gate(conn, seeded)
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await _answer(conn, seeded, gate, "approved", payload)

    run_async(scenario())


def test_a_rejection_carries_no_payload(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o1-set-rej", label="set-rej")
            gate = await _present_set_gate(conn, seeded)
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await _answer(conn, seeded, gate, "rejected", {"selected_option_refs": ["prd_aura"]})
            answer = await _answer(conn, seeded, gate, "rejected", None)
            assert answer.decision == "rejected"

    run_async(scenario())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_onboarding_substrate_migration.py tests/api/test_product_set_selection_gate_db.py -v`
Expected: FAIL — `AttributeError: module has no attribute '_answer_validator'` and `ImportError: cannot import name 'KIND_PRODUCT_SET_SELECTION'`.

- [ ] **Step 3: Add the Python constants and gate-id derivation**

In `platform/api/clue_api/agent_gate.py`:

```python
# in __all__, after "KIND_PRODUCT_SELECTION",
    "KIND_PRODUCT_SET_SELECTION",
# ... and after "product_selection_gate_id",
    "product_set_selection_gate_id",

# constants block
KIND_PRODUCT_SET_SELECTION = "product_set_selection"
GATE_KINDS = (
    KIND_DIRECTIVE_CONFIRMATION,
    KIND_ICP_CONFIRMATION,
    KIND_PRODUCT_SELECTION,
    KIND_PRODUCT_SET_SELECTION,
)

# next to _PRODUCT_SELECTION_GATE_NAMESPACE
_PRODUCT_SET_SELECTION_GATE_NAMESPACE = uuid5(
    NAMESPACE_URL, "clue:arv2:onboarding:product-set-selection-gate"
)
```

and after `product_selection_gate_id`:

```python
def product_set_selection_gate_id(
    *,
    workspace_id: str,
    turn_id: UUID,
    subject_ref: str,
    expected_subject_sha256: str,
) -> UUID:
    """Derive one immutable product-SET selection gate for one pinned catalog presentation
    (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3; a project targets a set of products, ruling P1)."""

    framed = "".join(
        f"{len(part)}:{part}"
        for part in (workspace_id, str(turn_id), subject_ref, expected_subject_sha256)
    )
    return uuid5(_PRODUCT_SET_SELECTION_GATE_NAMESPACE, framed)
```

- [ ] **Step 4: Add the DDL section to the migration**

Change `upgrade()` / `downgrade()` to:

```python
def upgrade() -> None:
    _create_onboarding_tables()
    _create_project_product()
    _install_product_set_gate_kind()


def downgrade() -> None:
    _remove_product_set_gate_kind()
    _drop_project_product()
    _drop_onboarding_tables()
```

and add:

```python
# --- §6.3 the product_set_selection human gate ------------------------------------------------

_GATE_KINDS_BEFORE = (
    "'directive_confirmation', 'icp_confirmation', 'product_selection', "
    "'plan_approval', 'budget_approval'"
)
_GATE_KINDS_AFTER = (
    "'directive_confirmation', 'icp_confirmation', 'product_selection', "
    "'product_set_selection', 'plan_approval', 'budget_approval'"
)


def _install_product_set_gate_kind() -> None:
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        f"ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind CHECK (kind IN ({_GATE_KINDS_AFTER}))"
    )
    op.execute(_answer_validator(product_set=True))


def _remove_product_set_gate_kind() -> None:
    op.execute(_answer_validator(product_set=False))
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        f"ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind CHECK (kind IN ({_GATE_KINDS_BEFORE}))"
    )


def _answer_validator(*, product_set: bool) -> str:
    """The whole ``agent_gate_answer_validate()`` body, exactly as 064ad0f43519 installs it, with
    the product-set branch inserted before the generic refusal when ``product_set`` is true.
    ``tests/db/test_arv2_onboarding_substrate_migration.py`` proves the ``False`` form is
    text-identical to the previous migration's, so ``downgrade()`` reinstalls the real thing."""
    product_set_branch = (
        """
            ELSIF presented.kind = 'product_set_selection' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION
                        'a product-set answer carries its choices in decision_payload, '
                        'not selected_option_ref';
                END IF;
                IF NEW.decision = 'approved' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'selected_option_refs')
                          IS DISTINCT FROM 'array'
                       OR jsonb_array_length(NEW.decision_payload -> 'selected_option_refs') < 1 THEN
                        RAISE EXCEPTION
                            'product-set approval requires selected_option_refs with at least '
                            'one entry and nothing else';
                    END IF;
                    IF jsonb_typeof(presented.subject_snapshot -> 'products')
                       IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION 'product-set gate has no valid candidate array';
                    END IF;
                    IF (SELECT count(*) FROM jsonb_array_elements_text(
                            NEW.decision_payload -> 'selected_option_refs'))
                       <> (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(
                            NEW.decision_payload -> 'selected_option_refs')) THEN
                        RAISE EXCEPTION 'product-set approval cannot repeat a product';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(
                            NEW.decision_payload -> 'selected_option_refs') chosen
                        WHERE NOT EXISTS (
                            SELECT 1 FROM jsonb_array_elements(
                                presented.subject_snapshot -> 'products') candidate
                            WHERE jsonb_typeof(candidate) = 'object'
                              AND candidate ->> 'product_id' = chosen.value
                        )
                    ) THEN
                        RAISE EXCEPTION
                            'a selected product is not a candidate in the presented gate';
                    END IF;
                ELSIF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION 'product-set rejection/revision carries no decision payload';
                END IF;
    """
        if product_set
        else ""
    )
    discovery_branch = """
            ELSIF presented.kind = 'directive_confirmation'
                  AND presented.subject_snapshot ->> 'subject_kind'
                      = 'discovery_configuration' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION 'a discovery configuration cannot carry a selected option';
                END IF;
                IF NEW.decision = 'revised' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'revision_request') <> 'string'
                       OR length(btrim(NEW.decision_payload ->> 'revision_request'))
                          NOT BETWEEN 1 AND 4000
                       OR NEW.decision_payload ->> 'revision_request'
                          <> btrim(NEW.decision_payload ->> 'revision_request') THEN
                        RAISE EXCEPTION
                            'a discovery revision requires one trimmed revision_request '
                            'of 1-4000 characters';
                    END IF;
                ELSIF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION
                        'discovery approve/reject answers carry no decision payload';
                END IF;
    """
    return f"""
        CREATE OR REPLACE FUNCTION agent_gate_answer_validate() RETURNS trigger AS $$
        DECLARE
            presented agent_gate%ROWTYPE;
            answering_turn agent_turn_submission%ROWTYPE;
        BEGIN
            SELECT * INTO presented FROM agent_gate
            WHERE gate_id = NEW.gate_id AND workspace_id = NEW.workspace_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'agent gate does not exist in this workspace';
            END IF;
            IF presented.snapshot_erased_at IS NOT NULL THEN
                RAISE EXCEPTION 'an erased gate snapshot cannot be answered';
            END IF;
            IF NOT (NEW.decision = ANY(presented.permitted_decisions)) THEN
                RAISE EXCEPTION 'decision is not permitted by this gate';
            END IF;
            IF NEW.expected_subject_sha256 <> presented.expected_subject_sha256 THEN
                RAISE EXCEPTION 'answer digest does not match the presented gate';
            END IF;
            IF NEW.answered_by_user_id <> presented.addressee_user_id THEN
                RAISE EXCEPTION 'only the gate addressee may answer';
            END IF;
            IF NEW.selected_option_ref IS NOT NULL
               AND NEW.decision_payload <> '{{}}'::jsonb THEN
                RAISE EXCEPTION 'an answer cannot carry both a revision payload and a selection';
            END IF;

            IF presented.kind = 'icp_confirmation' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION 'an ICP answer cannot carry a selected option';
                END IF;
                IF NEW.decision = 'revised' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'revision_request') <> 'string'
                       OR length(btrim(NEW.decision_payload ->> 'revision_request'))
                          NOT BETWEEN 1 AND 4000
                       OR NEW.decision_payload ->> 'revision_request'
                          <> btrim(NEW.decision_payload ->> 'revision_request') THEN
                        RAISE EXCEPTION
                            'an ICP revision requires one trimmed revision_request '
                            'of 1-4000 characters';
                    END IF;
                ELSIF NEW.decision_payload <> '{{}}'::jsonb THEN
                    RAISE EXCEPTION 'ICP approve/reject answers carry no decision payload';
                END IF;
            ELSIF presented.kind = 'product_selection' THEN
                IF NEW.decision_payload <> '{{}}'::jsonb THEN
                    RAISE EXCEPTION 'product-selection answers carry no decision payload';
                END IF;
                IF NEW.decision = 'approved' THEN
                    IF NEW.selected_option_ref IS NULL
                       OR length(btrim(NEW.selected_option_ref)) = 0 THEN
                        RAISE EXCEPTION 'product approval requires one selected option';
                    END IF;
                    IF jsonb_typeof(presented.subject_snapshot -> 'products')
                       IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION 'product-selection gate has no valid candidate array';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                            presented.subject_snapshot -> 'products'
                        ) candidate
                        WHERE jsonb_typeof(candidate) = 'object'
                          AND candidate ->> 'product_id' = NEW.selected_option_ref
                    ) THEN
                        RAISE EXCEPTION
                            'selected option is not a candidate in the presented gate';
                    END IF;
                ELSIF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION 'product rejection/revision cannot carry a selected option';
                END IF;
{product_set_branch}{discovery_branch}
            ELSIF NEW.decision_payload <> '{{}}'::jsonb
                  OR NEW.selected_option_ref IS NOT NULL THEN
                RAISE EXCEPTION 'this gate kind does not accept auxiliary answer input';
            END IF;

            SELECT * INTO answering_turn FROM agent_turn_submission
            WHERE turn_id = NEW.turn_id AND workspace_id = NEW.workspace_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'answering turn does not exist in this workspace';
            END IF;
            IF answering_turn.project_id <> presented.project_id
               OR answering_turn.thread_id <> presented.thread_id THEN
                RAISE EXCEPTION 'answering turn does not belong to this gate thread';
            END IF;
            IF answering_turn.submitted_by_user_id <> NEW.answered_by_user_id THEN
                RAISE EXCEPTION 'answering turn was not submitted by the gate addressee';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
```

**Important:** the text above was transcribed from `064ad0f43519._answer_validator(discovery_configuration_revision=True)`. The equivalence test in Step 1 is the check that the transcription is exact. If it fails, diff the two normalized strings (print both in a scratch script) and fix the transcription in this migration — never edit `064ad0f43519`. Note the `{{}}` escapes inside the f-string body versus the plain `{}` inside the two branch literals (they are plain strings, not f-strings), matching how the original module writes them.

- [ ] **Step 5: Apply and run everything**

Run: `set -a; source .env; set +a; uv run alembic downgrade -1 && uv run alembic upgrade head && uv run pytest tests/db/test_arv2_onboarding_substrate_migration.py tests/db/test_unified_agent_gate_migration.py tests/api/test_product_set_selection_gate_db.py tests/api/test_lane_d4_agent_gate_db.py tests/api/test_product_selection_s5f_db.py -v`
Expected: all PASS — the old `product_selection` suite is untouched by the union.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/*_arv2_onboarding_substrate.py platform/api/clue_api/agent_gate.py tests/db/test_arv2_onboarding_substrate_migration.py tests/db/test_unified_agent_gate_migration.py tests/api/test_product_set_selection_gate_db.py
git commit -m "feat(db,api): product_set_selection gate kind — CHECK union, answer trigger with per-element snapshot membership, gate-id derivation (catalog contract §6.3)"
```

---

### Task 5: Close-out — one head, smoke on a throwaway DB, the standing-rule checklist, memory

**Files:**
- Create: `_memory/2026-09-07-arv2-onboarding-o1-substrate.md`

- [ ] **Step 1: Prove one head and reversibility on a throwaway database**

```bash
uv run alembic heads                       # exactly one line
createdb clue_smoke_o1 2>/dev/null || true # or your local equivalent; NEVER the shared dev DB
CLUE_DATABASE_URL=postgresql+asyncpg://localhost/clue_smoke_o1 make db-smoke
dropdb clue_smoke_o1
```

Expected: `db-smoke` prints the up → base → up sequence without error. If `alembic heads` prints two lines because D1 merged first: `uv run alembic merge -m "merge o1+d1" <o1_head> <d1_head>`, re-run the smoke, and commit the join revision on its own.

- [ ] **Step 2: Run the full gate**

Run: `make check`
Expected: green (the DB-backed tests skip without a DSN, run with one). Zero new failures against the base; if the base carries known reds (`_memory/2026-08-19-slice-d-make-check-baseline.md`), list them unchanged.

- [ ] **Step 3: Run the standing-rule checklist items O1 owns**

- Item 3 (scope-pin content): `grep -rn "client_kb_version\|readiness_decision\|project_run_stage0_pins" alembic/versions/*_arv2_onboarding_substrate.py libs/clue-spine/clue_spine/spine.py` → **zero** hits.
- Item 7 (`.env.example` posture): `grep -n "^CLUE_SELF_SERVE_PROVISIONING_ENABLED=\|^CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=\|^CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=" .env.example` → `false`, `off`, `false`.
- Persona enum untouched: `git diff origin/integration/design-improvement...HEAD -- libs/clue-core/clue_core/enums.py` → empty.

- [ ] **Step 4: Write the memory note**

```markdown
# 2026-09-07 — ARV2 onboarding O1: substrate landed

Plan: docs/superpowers/plans/2026-09-07-arv2-onboarding-o1-substrate.md (spec: ARV2-ONBOARDING-PLAN.md §3, §6, §10).

- Migration `<hash>` off `<down_revision>`: onboarding_run / onboarding_step / brand_knowledge_document;
  project_product (append-only, composite same-brand FKs, identity triple indexes); gate kind
  product_set_selection + redefined agent_gate_answer_validate (downgrade text proven identical to 064ad0f43519).
- Settings: seven CLUE_ONBOARDING_* fields + ONBOARDING_SYNTHESIS_AGENT_MODEL lines (parity tests green).
- Spine: ProjectProductSet, confirm_project_product_set / current_project_product_set / list_project_product_sets.
- Gate: KIND_PRODUCT_SET_SELECTION, product_set_selection_gate_id.
- Verification: `alembic heads` = 1; db-smoke on throwaway DB green; make check: <result>; standing-rule
  checklist items 3 and 7 pass; Persona enum untouched (D1's).
- Not done here (by design): the driver (O3), the gate tool + route (O6), the frontend (O5).
- Alembic merge with D1: <needed / not needed; join revision id if any>.
```

Add a one-line pointer under "Topic notes" in `_memory/README.md`.

- [ ] **Step 5: Commit**

```bash
git add _memory/2026-09-07-arv2-onboarding-o1-substrate.md _memory/README.md
git commit -m "memory: ARV2 onboarding O1 substrate close-out — one head, smoke green, standing-rule checklist"
```

Hand the branch name, this note, and the `make check` / `db-smoke` output to Aryan. Do not push.
