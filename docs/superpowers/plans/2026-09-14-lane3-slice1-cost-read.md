# Lane 3 slice 1 — the cost read — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One read that answers, from the rows that already exist, "how much did this run / this account research / this customer cost us, and which provider and model spent it" — served as a projection endpoint and an operator CLI — with the one durable gap that would make the answer a lie (conversation-turn model calls recorded at zero cost) closed first.

**Architecture:** No new cost table. Provider spend and the ARV2 research agent's own model rounds already sit in `provider_call_ledger`; conversation-turn model calls sit in `agent_model_call`. Slice 1 (a) adds a nullable `cost_usd` + `cost_source` to `agent_model_call` and stamps them from the cost the gateway already measured on every answer, (b) adds a read-only module `clue_projections.cost` that groups the two ledgers by provider, operation, model, job and project under workspace-scoped filters, (c) exposes it at `GET /cost/report` on the projections router and as `python -m clue_projections.cost_cli`. Everything is Postgres-only, MVCC-only reads in the projections package (the no-write guard enforces it).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async `text()` queries, Pydantic v2 DTOs, Alembic (hash revision ids), pytest with the repo's rolled-back-connection DB harness, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` (§2 R2, R8, R9, R11, R12; §3; §5.5; §9 slice 1; §10 items 4–5). Rulings ledger: `_memory/2026-09-14-lane3-telemetry-rulings.md`.

## Global Constraints

- **Worktree and branch.** Lane 3 runs in its own worktree off `research-streaming`; branch name `lane3/slice1-cost-read`. Tasks 1–3 touch two files lane 1 also edits (`platform/api/clue_api/agent_runtime_wiring.py`, `platform/api/clue_api/agent_turn_wiring.py`); keep those commits small and land them first so lane 1's remaining plans rebase over them (design note §9, lane index "Lane 1 ↔ Lane 3").
- **Postgres is the ledger of record (R2).** No cost is recomputed anywhere in this slice; every number is read from a row that a writer already settled. The chat receipt's new `cost_usd` is the gateway's own stamped figure, never a rate applied here.
- **`cost_millicredits` stays 0.** It is the uncomposed credits milestone's policy (comment at `agent_runtime_wiring.py:282-289`). This slice records USD beside it; it does not touch millicredits.
- **The projections package writes nothing** (`tests/projections/test_no_write_sql_guard.py` scans for `INSERT INTO` / `UPDATE … SET` / `DELETE FROM` / `CREATE TABLE` / `ALTER TABLE` / `TRUNCATE` in any `clue_projections` file, including docstrings — do not spell those tokens in prose there). It may import only `clue_research` read surfaces + `clue_core` / `clue_db` / `clue_obs` / `clue_config` (pyproject `[tool.importlinter]` "projections import only research read surfaces + shared base").
- **Migrations:** `uv run alembic revision -m "<slug>"` assigns the hash id and `down_revision` (current head at planning time: `639d081ad799`; re-check with `uv run alembic heads` at execution time — lane 1 may have added one). Hand-written, reversible, named CHECKs. `uv run alembic heads` must print one head.
- **Legacy research lane untouched (R11):** nothing under `subsystems/research/clue_research/**` beyond the shared libraries is edited. This slice edits `platform/**`, `libs/clue-gateway/clue_gateway/metadata.py`, `alembic/versions/`, `tests/**`, `Makefile`, docs.
- **Design subsystem untouched (R12 hold).** Its spend is listed by the report as "not covered".
- **Tests spend no money.** DB tests run only against the lane's throwaway database (`CLUE_DATABASE_URL` from the worktree `.env`, loaded with `set -a; source .env; set +a`); they `pytest.skip` without one. Never run `make check` or a broad `pytest` with real provider keys in the environment; scope runs to the files named in each task, or use `--ignore-glob='*_live.py'`.
- **No UI.** The frontend has no cost slot; per the standing rule (dummy frontend is presentation truth) none is invented. The endpoint and CLI are the surfaces.
- **Type and lint gates per task:** `uv run ruff format <files> && uv run ruff check <files>`, `uv run mypy` (strict; the package files are in `[tool.mypy] files`), `uv run lint-imports` after any import change.
- **Commits:** local only, never push; no AI attribution trailer; one commit per task, message states what and why.

## What the plan discovered (read before Task 1)

1. **Conversation-turn model spend is recorded at zero.** `DurableAgentModelCallHandler._record` (`platform/api/clue_api/agent_runtime_wiring.py:282-289`) writes `cost_millicredits=0` on purpose, while the gateway stamps the measured cost on every answer's `response_metadata` under `clue_cost_cents` / `clue_cost_source` (`libs/clue-gateway/clue_gateway/metadata.py`). The ARV2 research agent already reads exactly those keys and writes USD to its ledger rows (`platform/api/clue_api/arv2/account_research_agent.py:238-252`). Tasks 1–3 give the chat receipt the same two facts. Without them the report would show every Head of ABM turn as free.
2. **ARV2 research-job model rounds are already on `provider_call_ledger`** as `provider='openrouter', operation='agent_completion'` rows with `extras_json` carrying `model`, `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens`, `cost_source` (`account_research_agent.py:175-215`). They are **not** in `agent_model_call`. So the two tables never overlap and can be summed. Structuring and Gemini calls also land as `provider='openrouter'` rows with `operation='chat/completions'`.
3. **Three ARV2 callers ledger to JSONL files, not Postgres:** the onboarding lane (`arv2/onboarding_driver.py:281-295`, composed at `fleet_main.py:720`), the display prewrite command (`arv2/display/page.py:100-118`), and the persona-evidence tool (`onboarding_evidence_tools.py:228-245`). Their spend is invisible to any SQL read. **Out of this slice**; recorded as slice 1b in Task 8 with the mechanics needed (a `LedgerStamp` with optional `project_id` / `project_run_id`, `BufferedLedger` + `drain_provider_calls` under the driver's own connection, the run id as the job stamp the way discovery already does at `discovery_driver.py:1221-1225`). The report names them under `not_covered` so nobody reads a partial total as a whole one.
4. **Ledger rows come in two phases.** `phase='estimate'` is a reservation written before the wire; `phase='result'` is money. Only result rows are summed (`provider_ledger.py:DrainReport` docstring; `tests/arv2/test_provider_ledger_db.py:160`).
5. **`cost_source` vocabularies differ by table.** Provider rows: `metered` / `estimate` / `free` (from `arv2/calls.py:CostSource`), plus `unpriced` written by the research agent's model rounds. Gateway-stamped model calls: `metered` / `estimate` / `unpriced`. The report reports counts per label; it never collapses them.

## File structure

| File | Responsibility |
| --- | --- |
| `alembic/versions/<hash>_agent_model_call_cost_usd.py` | **Create.** Adds `cost_usd numeric(12,6)` + `cost_source text` (CHECK) to `agent_model_call`; reversible. |
| `libs/clue-gateway/clue_gateway/metadata.py` | **Modify.** One shared reader `cost_cents_from_metadata(metadata) -> (Decimal \| None, CostSource \| None)` so the chat recorder and the ARV2 agent parse the stamp identically. |
| `platform/api/clue_api/arv2/account_research_agent.py:238-252` | **Modify.** `_cost_cents` delegates to the shared reader (DRY; behaviour identical). |
| `platform/agents/clue_agents/turns.py:78-104` | **Modify.** `AgentModelCallReceipt` gains `cost_usd: Decimal \| None`, `cost_source: ModelCostSource \| None`. |
| `platform/api/clue_api/agent_turn_wiring.py:614-712` | **Modify.** `record_model_call` writes and replay-compares the two columns. |
| `platform/api/clue_api/agent_runtime_wiring.py:186-300` | **Modify.** `on_llm_end` reads the stamp; `_record` threads it into the receipt. |
| `platform/projections/clue_projections/cost.py` | **Create.** DTOs + `cost_report()` — the read. |
| `platform/projections/clue_projections/cost_cli.py` | **Create.** `python -m clue_projections.cost_cli`: argparse → `cost_report` → text/JSON on stdout. |
| `platform/projections/clue_projections/__init__.py` | **Modify.** Export the cost DTOs and `cost_report`. |
| `platform/api/clue_api/projections_app.py:215-320` | **Modify.** `GET /cost/report` on the projections router. |
| `Makefile` | **Modify.** `cost-report` target. |
| `tests/db/test_agent_model_call_cost_migration.py` | **Create.** Columns + CHECK exist; downgrade path proven by `make db-smoke`. |
| `tests/api/test_agent_model_call_cost_receipt_db.py` | **Create.** Receipt → row round trip, replay compare, NULL for pre-migration rows. |
| `tests/api/test_agent_runtime_wiring_cost_stamp.py` | **Create.** The handler stamps `cost_usd`/`cost_source` from `response_metadata` (no DB). |
| `tests/gateway/test_metadata_cost_reader.py` | **Create.** The shared reader's four shapes. |
| `tests/projections/test_cost_db.py` | **Create.** The read over seeded rows: scoping, phases, labels, filters, jobs, projects. |
| `tests/projections/test_cost_cli.py` | **Create.** `render_report` and `main` argument handling (no DB). |
| `tests/api/test_cost_report_endpoint_db.py` | **Create.** The route through the ASGI app. |
| `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` §5.5 | **Modify.** Record discoveries 1 and 3; slice 1b. |
| `docs/superpowers/plans/2026-09-13-lane-plan-index.md` | **Modify.** Lane 3 section. |
| `_memory/2026-09-14-lane3-slice1-cost-read.md` | **Create.** Session note with the proof. |

---

### Task 1: `agent_model_call` gains `cost_usd` and `cost_source`

**Files:**
- Create: `alembic/versions/<hash>_agent_model_call_cost_usd.py` (hash assigned by Alembic)
- Test: `tests/db/test_agent_model_call_cost_migration.py`

**Interfaces:**
- Produces: two nullable columns on `agent_model_call` — `cost_usd numeric(12, 6)`, `cost_source text` with `CONSTRAINT agent_model_call_cost_source CHECK (cost_source IS NULL OR cost_source IN ('metered', 'estimate', 'unpriced'))`. Historical rows stay NULL/NULL, which the read treats as "unpriced before this migration".

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_agent_model_call_cost_migration.py
"""Lane 3 slice 1, Task 1: ``agent_model_call`` carries the gateway-measured cost beside the
still-zero ``cost_millicredits`` (which remains the uncomposed credits milestone's policy)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_agent_model_call_has_nullable_cost_usd_and_cost_source() -> None:
    async def scenario() -> list[tuple[str, str, str]]:
        async with rollback_conn(seed_pack=False) as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'agent_model_call' "
                    "AND column_name IN ('cost_usd', 'cost_source') ORDER BY column_name"
                )
            )
            return [(r[0], r[1], r[2]) for r in rows]

    assert run_async(scenario()) == [
        ("cost_source", "text", "YES"),
        ("cost_usd", "numeric", "YES"),
    ]


def test_cost_source_check_rejects_a_word_outside_the_gateway_vocabulary() -> None:
    async def scenario() -> str:
        async with rollback_conn(seed_pack=False) as conn:
            check = await conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'agent_model_call_cost_source'"
                )
            )
            return str(check.scalar_one())

    definition = run_async(scenario())
    for word in ("metered", "estimate", "unpriced"):
        assert word in definition
    assert "free" not in definition  # the provider ledger's label, never a model call's
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_agent_model_call_cost_migration.py -v`
Expected: both FAIL (`[] != [...]`; `NoResultFound` on the constraint lookup).

- [ ] **Step 3: Generate the migration file and fill it in**

Run: `uv run alembic revision -m "agent model call cost usd"` and open the file it prints. Replace its body with:

```python
"""agent model call cost usd

Revision ID: <keep the generated id>
Revises: <keep the generated down_revision>
Create Date: <keep>

Lane 3 slice 1 (telemetry and cost design note §5.5). ``agent_model_call`` was born with
``cost_millicredits``, deliberately written as 0 until the credits milestone owns the
cents→millicredits policy. The gateway already measures every answer's cost and stamps it on the
response metadata (``clue_cost_cents`` / ``clue_cost_source``); the ARV2 research agent already
records that figure on its ledger rows. This migration gives the conversation-turn receipt the same
two facts so the cost read never reports a turn as free.

Both columns are nullable: every row written before this migration is NULL/NULL, which the read
reports as "unpriced before <this revision>" rather than as zero. ``cost_source`` is bounded to the
gateway's three words — ``free`` is the provider ledger's label and never applies to a model call.

Reversible: the downgrade drops the CHECK and both columns; no row data outside them is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<generated>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "ADD COLUMN cost_usd numeric(12, 6), "
        "ADD COLUMN cost_source text, "
        "ADD CONSTRAINT agent_model_call_cost_source CHECK ("
        "cost_source IS NULL OR cost_source IN ('metered', 'estimate', 'unpriced'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "DROP CONSTRAINT agent_model_call_cost_source, "
        "DROP COLUMN cost_source, "
        "DROP COLUMN cost_usd"
    )
```

- [ ] **Step 4: Apply it and run the test**

Run: `set -a; source .env; set +a; uv run alembic upgrade head && uv run alembic heads && uv run pytest tests/db/test_agent_model_call_cost_migration.py -v`
Expected: `alembic heads` prints exactly one id (the new one); both tests PASS.

- [ ] **Step 5: Prove reversibility**

Run: `set -a; source .env; set +a; make db-smoke`
Expected: up → down → up completes without error. (This is the lane's throwaway DB; never a shared one.)

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/*_agent_model_call_cost_usd.py tests/db/test_agent_model_call_cost_migration.py
git commit -m "feat(agent-ledger): agent_model_call carries the gateway-measured cost_usd and cost_source

cost_millicredits stays 0 (credits milestone policy); these two nullable columns record the
figure the gateway already stamps on every answer so the lane 3 cost read never reports a
conversation turn as free. Reversible; historical rows stay NULL."
```

---

### Task 2: One shared reader for the gateway's cost stamp

**Files:**
- Modify: `libs/clue-gateway/clue_gateway/metadata.py` (append after `CostSource`)
- Modify: `platform/api/clue_api/arv2/account_research_agent.py:238-252` (`_cost_cents` delegates)
- Test: `tests/gateway/test_metadata_cost_reader.py`

**Interfaces:**
- Produces: `clue_gateway.metadata.cost_cents_from_metadata(metadata: Mapping[str, object]) -> tuple[Decimal | None, CostSource | None]`. Returns `(cents, source)`: `source` is the stamped word when it is one of `metered` / `estimate` / `unpriced`, else `None`; `cents` is a `Decimal` only when `source` is `metered` or `estimate` and `clue_cost_cents` parses, else `None`. An `unpriced` answer therefore yields `(None, "unpriced")` — a blank, never a measured zero.
- Consumed by: Task 3 (chat recorder) and the ARV2 agent (already reads the same keys).

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/test_metadata_cost_reader.py
"""The one place the gateway's cost stamp is parsed (lane 3 slice 1, Task 2)."""

from __future__ import annotations

from decimal import Decimal

from clue_gateway.metadata import COST_CENTS_KEY, COST_SOURCE_KEY, cost_cents_from_metadata


def test_metered_answer_yields_its_cents_as_a_decimal() -> None:
    assert cost_cents_from_metadata({COST_CENTS_KEY: "1.2345", COST_SOURCE_KEY: "metered"}) == (
        Decimal("1.2345"),
        "metered",
    )


def test_estimate_answer_is_priced_but_labelled_estimate() -> None:
    assert cost_cents_from_metadata({COST_CENTS_KEY: "0.5", COST_SOURCE_KEY: "estimate"}) == (
        Decimal("0.5"),
        "estimate",
    )


def test_unpriced_answer_is_a_blank_not_a_zero() -> None:
    assert cost_cents_from_metadata({COST_CENTS_KEY: "0", COST_SOURCE_KEY: "unpriced"}) == (
        None,
        "unpriced",
    )


def test_missing_or_malformed_stamp_is_blank() -> None:
    assert cost_cents_from_metadata({}) == (None, None)
    assert cost_cents_from_metadata({COST_SOURCE_KEY: "metered"}) == (None, "metered")
    assert cost_cents_from_metadata({COST_CENTS_KEY: "not-a-number", COST_SOURCE_KEY: "metered"}) == (
        None,
        "metered",
    )
    assert cost_cents_from_metadata({COST_CENTS_KEY: "1", COST_SOURCE_KEY: "free"}) == (None, None)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/gateway/test_metadata_cost_reader.py -v`
Expected: FAIL with `ImportError: cannot import name 'cost_cents_from_metadata'`.

- [ ] **Step 3: Implement the reader**

Append to `libs/clue-gateway/clue_gateway/metadata.py` (keep the module import-free beyond stdlib; add `from collections.abc import Mapping`, `from decimal import Decimal, InvalidOperation`, `from typing import Literal, get_args` to its imports; add `"cost_cents_from_metadata"` to `__all__`):

```python
_COST_SOURCES: frozenset[str] = frozenset(get_args(CostSource))


def cost_cents_from_metadata(
    metadata: Mapping[str, object],
) -> tuple[Decimal | None, CostSource | None]:
    """Read the cost stamp off one answer's ``response_metadata``.

    Returns ``(cents, source)``. ``source`` is the stamped word when it is one of the three
    :data:`CostSource` values, else ``None``. ``cents`` is a ``Decimal`` only for a ``metered`` or
    ``estimate`` answer whose ``clue_cost_cents`` parses; an ``unpriced`` answer carries a zero
    that means "no rate", and that must never become a measured zero — so it reads as ``None``.
    Every reader of the stamp (the conversation-turn recorder, the ARV2 research agent) goes
    through here so the two ledgers can never disagree on what a stamp means.
    """
    raw_source = metadata.get(COST_SOURCE_KEY)
    source: CostSource | None = (
        raw_source if isinstance(raw_source, str) and raw_source in _COST_SOURCES else None  # type: ignore[assignment]
    )
    if source is None or source == "unpriced":
        return None, source
    raw = metadata.get(COST_CENTS_KEY)
    if raw is None:
        return None, source
    try:
        return Decimal(str(raw)), source
    except InvalidOperation:
        return None, source
```

Then in `platform/api/clue_api/arv2/account_research_agent.py`, replace the body of `_cost_cents` (lines 238-252) so it delegates, keeping its name and signature (its callers are unchanged):

```python
def _cost_cents(metadata: Any) -> Decimal | None:
    """The gateway's stamped cost for one answer, or ``None`` when it could not price the model.

    Delegates to the shared reader so this ledger and the conversation-turn receipt parse the
    stamp identically (an ``unpriced`` answer is a blank, never a measured zero).
    """
    cents, _source = cost_cents_from_metadata(metadata)
    return cents
```

and add `cost_cents_from_metadata` to the module's existing `from clue_gateway.metadata import (...)` line. Remove the now-unused `InvalidOperation` import if nothing else in the file uses it (`uv run ruff check` will say).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/gateway/test_metadata_cost_reader.py tests/arv2/test_account_research_agent.py -v && uv run ruff format libs/clue-gateway/clue_gateway/metadata.py platform/api/clue_api/arv2/account_research_agent.py && uv run ruff check libs/clue-gateway platform/api/clue_api/arv2/account_research_agent.py && uv run mypy && uv run lint-imports`
Expected: all PASS; ruff, mypy, import-linter clean (the ARV2 agent already imports `clue_gateway.metadata`, so no new edge).

- [ ] **Step 5: Commit**

```bash
git add libs/clue-gateway/clue_gateway/metadata.py platform/api/clue_api/arv2/account_research_agent.py tests/gateway/test_metadata_cost_reader.py
git commit -m "feat(gateway): one shared reader for the cost stamp on an answer's metadata

cost_cents_from_metadata() is the single parse of clue_cost_cents/clue_cost_source; the ARV2
research agent's _cost_cents now delegates to it so the two ledgers cannot drift on what
'unpriced' means (a blank, never a zero)."
```

---

### Task 3: The conversation-turn receipt records the measured cost

**Files:**
- Modify: `platform/agents/clue_agents/turns.py:78-104` (`AgentModelCallReceipt`)
- Modify: `platform/api/clue_api/agent_turn_wiring.py:614-712` (`DbAgentTurnJournal.record_model_call`)
- Modify: `platform/api/clue_api/agent_runtime_wiring.py:186-300` (`DurableAgentModelCallHandler`)
- Test: `tests/api/test_agent_model_call_cost_receipt_db.py`, `tests/api/test_agent_runtime_wiring_cost_stamp.py`

**Interfaces:**
- Consumes: Task 1 columns; Task 2 `cost_cents_from_metadata`.
- Produces: `AgentModelCallReceipt.cost_usd: Decimal | None = None`, `AgentModelCallReceipt.cost_source: ModelCostSource | None = None` where `ModelCostSource = Literal["metered", "estimate", "unpriced"]` (defined in `clue_agents.turns`; kept local so `clue_agents` gains no new import edge). Rows carry them; replay compares them.

- [ ] **Step 1: Write the failing DB test (receipt → row → replay)**

```python
# tests/api/test_agent_model_call_cost_receipt_db.py
"""Lane 3 slice 1, Task 3: the durable model-call receipt carries the gateway-measured cost.

Pins: the receipt→row round trip for a priced and an unpriced call; the replay compare treating
cost as part of the immutable receipt; a pre-migration-shaped receipt (no cost) still lands as
NULL/NULL rather than as zero.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import AgentRole
from clue_agents.turns import AgentModelCallReceipt, AgentModelCallStatus
from clue_api.agent_turn_wiring import DbAgentTurnJournal
from clue_core import ExecutionId
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

NOW = datetime.now(UTC)


async def _seed_turn(conn: AsyncConnection) -> dict[str, Any]:
    ws = f"ws_cost_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="cost receipt")
    thread_id = f"thread-{ws}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p)"),
        {"id": thread_id, "ws": ws, "p": project.project_id},
    )
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'agent', :hash, :hash)"
        ),
        {"id": execution_id, "ws": ws, "p": project.project_id, "hash": "0" * 64},
    )
    sha = "d" * 64
    manifest_key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'application/json', :size)"
        ),
        {"key": manifest_key, "ws": ws, "sha": sha, "size": len(json.dumps({"resources": []}))},
    )
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :p, :thread, 'actor-cost', 'head_of_abm', "
            " 'root-cost', 'head-of-abm', 'v1', :sha, :key, :sha, :sha, 'test', :requested)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "ws": ws,
            "p": project.project_id,
            "thread": thread_id,
            "sha": sha,
            "key": manifest_key,
            "requested": NOW,
        },
    )
    return {"ws": ws, "turn_id": turn_id, "execution_id": execution_id}


def _receipt(
    seeds: dict[str, Any],
    *,
    sequence: int,
    cost_usd: Decimal | None,
    cost_source: str | None,
) -> AgentModelCallReceipt:
    return AgentModelCallReceipt(
        model_call_id=uuid5(NAMESPACE_URL, f"cost:{seeds['ws']}:call:{sequence}"),
        turn_id=seeds["turn_id"],
        execution_id=ExecutionId(seeds["execution_id"]),
        workspace_id=seeds["ws"],
        sequence=sequence,
        requested_model="x-ai/grok-4.6",
        answering_model="x-ai/grok-4.6",
        status=AgentModelCallStatus.COMPLETED,
        input_tokens=100,
        output_tokens=10,
        cost_millicredits=0,
        cost_usd=cost_usd,
        cost_source=cost_source,  # type: ignore[arg-type]
        latency_ms=12.5,
        role=AgentRole.HEAD_OF_ABM,
        started_at=NOW,
        completed_at=NOW,
    )


async def _row(conn: AsyncConnection, seeds: dict[str, Any], sequence: int) -> tuple[Any, Any]:
    got = await conn.execute(
        text(
            "SELECT cost_usd, cost_source FROM agent_model_call "
            "WHERE turn_id = :turn AND sequence = :sequence"
        ),
        {"turn": seeds["turn_id"], "sequence": sequence},
    )
    row = got.one()
    return row[0], row[1]


def test_priced_unpriced_and_legacy_receipts_round_trip() -> None:
    async def scenario() -> list[tuple[Any, Any]]:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed_turn(conn)
            journal = DbAgentTurnJournal(conn_factory=conn_session_factory(conn))
            await journal.record_model_call(
                receipt=_receipt(seeds, sequence=1, cost_usd=Decimal("0.012345"), cost_source="metered")
            )
            await journal.record_model_call(
                receipt=_receipt(seeds, sequence=2, cost_usd=None, cost_source="unpriced")
            )
            await journal.record_model_call(
                receipt=_receipt(seeds, sequence=3, cost_usd=None, cost_source=None)
            )
            return [await _row(conn, seeds, s) for s in (1, 2, 3)]

    assert run_async(scenario()) == [
        (Decimal("0.012345"), "metered"),
        (None, "unpriced"),
        (None, None),
    ]


def test_replay_with_a_different_cost_is_refused() -> None:
    async def scenario() -> str:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed_turn(conn)
            journal = DbAgentTurnJournal(conn_factory=conn_session_factory(conn))
            first = _receipt(seeds, sequence=1, cost_usd=Decimal("0.01"), cost_source="metered")
            await journal.record_model_call(receipt=first)
            await journal.record_model_call(receipt=first)  # identical replay: fine
            changed = _receipt(seeds, sequence=1, cost_usd=Decimal("0.02"), cost_source="metered")
            try:
                await journal.record_model_call(receipt=changed)
            except ValueError as error:
                return str(error)
            return "no error"

    assert "different immutable receipt" in run_async(scenario())
```

`DbAgentTurnJournal(*, conn_factory: ConnFactory = transaction)` is the constructor (`agent_turn_wiring.py:393-395`); `conn_session_factory(conn)` from the profiling conftest is the same shape the p32 test hand-rolls.

- [ ] **Step 2: Run the DB test to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_agent_model_call_cost_receipt_db.py -v`
Expected: FAIL — `ValidationError: ... cost_usd ... extra fields not permitted` (or `TypeError` on the unknown keyword).

- [ ] **Step 3: Extend the receipt**

In `platform/agents/clue_agents/turns.py`, above `class AgentModelCallReceipt` add:

```python
#: Which cost authority answered a model call, as the gateway stamped it: ``metered`` (the
#: provider reported the charge), ``estimate`` (our price sheet), ``unpriced`` (no rate — a
#: blank, never a zero). Spelled here rather than imported so this package gains no new edge; the
#: gateway's ``CostSource`` is the same three words.
ModelCostSource = Literal["metered", "estimate", "unpriced"]
```

(the module currently imports nothing from `typing` or `decimal`: add `from decimal import Decimal` and `from typing import Literal` beside `from uuid import UUID`), and inside the class, directly after `cost_millicredits: int = Field(ge=0)`:

```python
    # Lane 3 slice 1: the gateway-measured cost of THIS call, in USD, read off the answer's
    # ``clue_cost_cents`` stamp. Beside ``cost_millicredits`` (still 0: the credits milestone's
    # policy), never derived from it. None = unpriced or recorded before the column existed.
    cost_usd: Decimal | None = Field(default=None, ge=0)
    cost_source: ModelCostSource | None = None
```

Add `"ModelCostSource"` to the module's `__all__` if it has one.

- [ ] **Step 4: Write and compare the two columns in the journal**

In `platform/api/clue_api/agent_turn_wiring.py` `record_model_call`:

The INSERT column list becomes `(..., cost_millicredits, cost_usd, cost_source, latency_ms, error_code, role, started_at, completed_at)` and the VALUES list `(..., :cost, :cost_usd, :cost_source, :latency, :error, :role, :started, :completed)`; add to the parameter dict:

```python
                    "cost_usd": receipt.cost_usd,
                    "cost_source": receipt.cost_source,
```

The replay SELECT adds `cost_usd, cost_source` after `cost_millicredits`; the `actual` tuple adds, after `int(row["cost_millicredits"])`:

```python
                    None if row["cost_usd"] is None else Decimal(row["cost_usd"]),
                    row["cost_source"],
```

and `expected` adds, after `receipt.cost_millicredits`:

```python
                    receipt.cost_usd,
                    receipt.cost_source,
```

(import `Decimal` from `decimal` if the module does not already).

- [ ] **Step 5: Run the DB test**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_agent_model_call_cost_receipt_db.py tests/api/test_p32_model_call_role_db.py tests/api/test_agent_turn_wiring_db.py -v`
Expected: all PASS (the p32 and turn-wiring suites prove nothing else about the receipt moved).

- [ ] **Step 6: Write the failing handler test (no DB)**

```python
# tests/api/test_agent_runtime_wiring_cost_stamp.py
"""Lane 3 slice 1, Task 3: the durable model-call handler stamps the gateway's measured cost on
the receipt. Drives the callback with fakes; no database, no model."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from clue_agents.contracts import AgentRole
from clue_api.agent_runtime_wiring import DurableAgentModelCallHandler
from clue_gateway.metadata import COST_CENTS_KEY, COST_SOURCE_KEY
from tests.db.conftest import run_async


class _Artifacts:
    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> Any:
        return SimpleNamespace(
            workspace_id=workspace_id, artifact_key=f"{workspace_id}/{len(data)}", sha256="0" * 64,
            media_type=media_type, byte_count=len(data),
        )


class _Turns:
    def __init__(self) -> None:
        self.receipts: list[Any] = []

    async def record_model_call(self, *, receipt: Any, input_ref: Any = None, output_ref: Any = None) -> None:
        self.receipts.append(receipt)


def _handler(turns: _Turns) -> DurableAgentModelCallHandler:
    request = SimpleNamespace(
        turn_id=uuid4(),
        constitution=SimpleNamespace(
            workspace_id="ws-cost", execution_id=uuid4(), role=AgentRole.HEAD_OF_ABM
        ),
    )
    return DurableAgentModelCallHandler(
        request=request,  # type: ignore[arg-type]
        requested_model="x-ai/grok-4.6",
        initial_sequence=1,
        artifacts=_Artifacts(),  # type: ignore[arg-type]
        turns=turns,  # type: ignore[arg-type]
    )


def _answer(metadata: dict[str, Any]) -> LLMResult:
    message = AIMessage(
        content="ok",
        response_metadata=metadata,
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]], llm_output={})


async def _drive(metadata: dict[str, Any]) -> Any:
    turns = _Turns()
    handler = _handler(turns)
    run_id = uuid4()
    await handler.on_chat_model_start({}, [[AIMessage(content="hi")]], run_id=run_id)
    await handler.on_llm_end(_answer(metadata), run_id=run_id)
    return turns.receipts[0]


def test_metered_answer_lands_its_usd_and_source_on_the_receipt() -> None:
    receipt = run_async(_drive({COST_CENTS_KEY: "1.2345", COST_SOURCE_KEY: "metered", "model_name": "x-ai/grok-4.6"}))
    assert receipt.cost_usd == Decimal("0.012345")
    assert receipt.cost_source == "metered"
    assert receipt.cost_millicredits == 0  # untouched: the credits milestone's policy


def test_unpriced_answer_is_blank_not_zero() -> None:
    receipt = run_async(_drive({COST_CENTS_KEY: "0", COST_SOURCE_KEY: "unpriced"}))
    assert receipt.cost_usd is None
    assert receipt.cost_source == "unpriced"


def test_answer_without_a_stamp_is_blank() -> None:
    receipt = run_async(_drive({"model_name": "x-ai/grok-4.6"}))
    assert receipt.cost_usd is None
    assert receipt.cost_source is None


def test_failed_call_records_no_cost() -> None:
    async def scenario() -> Any:
        turns = _Turns()
        handler = _handler(turns)
        run_id = uuid4()
        await handler.on_chat_model_start({}, [[AIMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_error(RuntimeError("boom"), run_id=run_id)
        return turns.receipts[0]

    receipt = run_async(scenario())
    assert receipt.cost_usd is None and receipt.cost_source is None
```

`AgentRole.HEAD_OF_ABM = "head_of_abm"` (`platform/agents/clue_agents/contracts.py:219-220`).

- [ ] **Step 7: Run the handler test to verify it fails**

Run: `uv run pytest tests/api/test_agent_runtime_wiring_cost_stamp.py -v`
Expected: first test FAILS on `receipt.cost_usd == Decimal("0.012345")` (it is `None`).

- [ ] **Step 8: Stamp the cost in the handler**

In `platform/api/clue_api/agent_runtime_wiring.py`:

Add `from clue_gateway.metadata import cost_cents_from_metadata` and `from decimal import Decimal` to the imports; import `ModelCostSource` from `clue_agents.turns`.

In `on_llm_end`, after `response_metadata = getattr(message, "response_metadata", None) or {}` add:

```python
        cents, cost_source = cost_cents_from_metadata(response_metadata)
        cost_usd = None if cents is None else (cents / Decimal(100)).quantize(Decimal("0.000001"))
```

and pass `cost_usd=cost_usd, cost_source=cost_source,` into the `await self._record(...)` call.

In `_record`, add two keyword parameters after `error_code: str | None = None`:

```python
        cost_usd: Decimal | None = None,
        cost_source: ModelCostSource | None = None,
```

and in the `AgentModelCallReceipt(...)` construction, replace the seven-line comment block plus `cost_millicredits=0,` with:

```python
            # cost_millicredits stays 0 by decision (P3.2, PD-part3 delta 6): converting cents
            # to credits is the uncomposed credits milestone's policy, and inventing a rate here
            # would create a second cost authority. The USD beside it is NOT a conversion — it is
            # the gateway's own measurement (clue_cost_cents), read by the shared reader, so the
            # conversation-turn ledger and the ARV2 research ledger record the same fact the same
            # way (lane 3 slice 1).
            cost_millicredits=0,
            cost_usd=cost_usd,
            cost_source=cost_source,
```

The failure path (`on_llm_error` → `_record(...)`) passes nothing, so it records `None`/`None`.

- [ ] **Step 9: Run every test this task touches, plus the gates**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_agent_runtime_wiring_cost_stamp.py tests/api/test_agent_model_call_cost_receipt_db.py tests/api/test_agent_runtime_wiring_db.py tests/api/test_p32_model_call_role_db.py tests/agents -v --ignore-glob='*_live.py' && uv run ruff format platform/agents/clue_agents/turns.py platform/api/clue_api/agent_turn_wiring.py platform/api/clue_api/agent_runtime_wiring.py && uv run ruff check platform/agents platform/api/clue_api/agent_turn_wiring.py platform/api/clue_api/agent_runtime_wiring.py && uv run mypy && uv run lint-imports`
Expected: all PASS; gates clean.

- [ ] **Step 10: Commit**

```bash
git add platform/agents/clue_agents/turns.py platform/api/clue_api/agent_turn_wiring.py platform/api/clue_api/agent_runtime_wiring.py tests/api/test_agent_model_call_cost_receipt_db.py tests/api/test_agent_runtime_wiring_cost_stamp.py
git commit -m "feat(agent-ledger): the conversation-turn receipt records the gateway-measured cost

on_llm_end reads clue_cost_cents/clue_cost_source through the shared reader and lands
cost_usd + cost_source on agent_model_call beside the still-zero cost_millicredits. Replay
compares them; failed and unpriced calls record a blank, never a zero."
```

---

### Task 4: The read — `clue_projections.cost`

**Files:**
- Create: `platform/projections/clue_projections/cost.py`
- Modify: `platform/projections/clue_projections/__init__.py` (exports)
- Test: `tests/projections/test_cost_db.py`

**Interfaces:**
- Consumes: `provider_call_ledger` (Task-independent), `agent_model_call.cost_usd` / `cost_source` (Task 1), `agent_turn` (project/thread keys), `clue_db.ConnFactory` / `transaction`.
- Produces:

```python
class CostFilters(BaseModel):            # frozen, extra=forbid
    project_id: str | None = None
    project_run_id: str | None = None    # text on the ledger; unavailable to turn receipts
    job_id: UUID | None = None           # entity_research_job_id; unavailable to turn receipts
    thread_id: str | None = None         # turn receipts only
    since: AwareDatetime | None = None   # inclusive; ledger.recorded_at / receipt.started_at
    until: AwareDatetime | None = None   # exclusive

class ProviderSpendLine(BaseModel): provider, operation, calls, ok_calls, cost_usd, credits, media_seconds, metered_calls, estimated_calls, free_calls, unpriced_calls
class ModelSpendLine(BaseModel):    source: Literal["turn_receipts", "research_ledger"], model, role: str | None, calls, input_tokens, cached_input_tokens, output_tokens, cost_usd, unpriced_calls
class JobSpendLine(BaseModel):      job_id: UUID, calls, cost_usd, credits, media_seconds
class ProjectSpendLine(BaseModel):  project_id, provider_usd, turn_model_usd, total_usd
class CostReport(BaseModel):        workspace_id, filters, provider_usd, turn_model_usd, total_usd, credits, media_seconds, providers, models, jobs, projects, not_covered: tuple[str, ...], notes: tuple[str, ...]

async def cost_report(*, workspace_id: str, filters: CostFilters | None = None, conn_factory: ConnFactory = transaction, job_limit: int = 50) -> CostReport
```

Accounting rules (state them in the module docstring, they are the contract):
1. Provider lines sum only `phase = 'result'` rows; `cost_usd` NULL counts as 0 and as an `unpriced_call`. Labels come from `extras_json->>'cost_source'`.
2. `provider_usd` = Σ provider lines. It already includes the ARV2 research agent's own model rounds (`provider='openrouter'`).
3. `turn_model_usd` = Σ `agent_model_call.cost_usd` (NULL → 0, counted `unpriced`). These rows are never on the provider ledger, so `total_usd = provider_usd + turn_model_usd` double-counts nothing.
4. `models` has two sources. `turn_receipts` lines are the conversation turns (`agent_model_call` ⋈ `agent_turn`, grouped by `COALESCE(answering_model, requested_model)` and `role`). `research_ledger` lines are the `provider='openrouter'` ledger rows grouped by `operation` + `extras_json->>'model'`; they are a subset of `providers` and are shown for the model breakdown only — never added to a total.
5. A `project_run_id` or `job_id` filter cannot apply to turn receipts (turns carry neither); the report then returns no `turn_receipts` lines and says so in `notes`. A `thread_id` filter cannot apply to the ledger; the report returns no provider lines and says so.
6. `not_covered` is constant and honest: the onboarding lane, the display prewrite, the persona-evidence tool (JSONL ledgers), the design subsystem's own providers (R12 hold), and conversation-turn model calls recorded before the cost columns existed (NULL cost; counted `unpriced`).

- [ ] **Step 1: Write the failing DB test**

```python
# tests/projections/test_cost_db.py
"""Lane 3 slice 1, Task 4: the cost read over the two ledgers.

Seeds one workspace with a conversation turn (three model-call receipts: metered, unpriced, and a
legacy NULL row) and six provider ledger rows (a metered Exa search, its estimate-phase twin, a
free ATS fetch, an AI Ark credits call, a research-agent model round, and a row for a second job),
plus a second workspace with one row of each kind that must never leak in. Then asserts every
accounting rule in ``clue_projections.cost``'s docstring.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_projections.cost import CostFilters, CostReport, cost_report
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

T0 = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
SHA = "e" * 64


async def _turn(conn: AsyncConnection, *, ws: str, project_id: str, thread_id: str) -> UUID:
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": thread_id, "ws": ws, "p": project_id},
    )
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'human', :hash, :hash)"
        ),
        {"id": execution_id, "ws": ws, "p": project_id, "hash": "0" * 64},
    )
    key = f"{ws}/{SHA}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 11) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": key, "ws": ws, "sha": SHA},
    )
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn (id, execution_id, workspace_id, project_id, thread_id, "
            " actor_id, role, workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :p, :thread, 'actor-1', 'head_of_abm', 'root-1', "
            " 'head-of-abm', 'v1', :hash, :key, :sha, :hash, 'standard', :at)"
        ),
        {
            "id": turn_id, "execution": execution_id, "ws": ws, "p": project_id,
            "thread": thread_id, "hash": "0" * 64, "key": key, "sha": SHA, "at": T0,
        },
    )
    return turn_id


async def _model_call(
    conn: AsyncConnection, *, ws: str, turn_id: UUID, sequence: int,
    cost_usd: Decimal | None, cost_source: str | None, started_at: datetime = T0,
) -> None:
    execution_id = (
        await conn.execute(text("SELECT execution_id FROM agent_turn WHERE id = :t"), {"t": turn_id})
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO agent_model_call (id, turn_id, execution_id, workspace_id, sequence, "
            " requested_model, answering_model, status, input_tokens, cache_read_input_tokens, "
            " output_tokens, cost_millicredits, cost_usd, cost_source, latency_ms, role, "
            " started_at, completed_at) "
            "VALUES (:id, :turn, :execution, :ws, :seq, 'x-ai/grok-4.6', 'x-ai/grok-4.6', "
            " 'completed', 100, 40, 10, 0, :cost, :source, 5, 'head_of_abm', :at, :at)"
        ),
        {
            "id": uuid4(), "turn": turn_id, "execution": execution_id, "ws": ws, "seq": sequence,
            "cost": cost_usd, "source": cost_source, "at": started_at,
        },
    )


async def _ledger(
    conn: AsyncConnection, *, ws: str, project_id: str, project_run_id: str, job_id: UUID | None,
    provider: str, operation: str, phase: str = "result", outcome: str = "ok",
    cost_usd: Decimal | None, credits: Decimal | None = None, media_seconds: int | None = None,
    extras: dict[str, Any] | None = None, recorded_at: datetime = T0,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO provider_call_ledger (call_id, workspace_id, project_id, project_run_id, "
            " entity_research_job_id, provider, operation, label, phase, http_status, latency_ms, "
            " attempts, estimate_usd, cost_usd, credits, media_seconds, outcome, extras_json, "
            " recorded_at) "
            "VALUES (:call, :ws, :p, :run, :job, :provider, :op, :label, :phase, 200, 100, 1, "
            " 0.01, :cost, :credits, :media, :outcome, CAST(:extras AS jsonb), :at)"
        ),
        {
            "call": uuid4(), "ws": ws, "p": project_id, "run": project_run_id, "job": job_id,
            "provider": provider, "op": operation, "label": f"{provider}-{operation}",
            "phase": phase, "cost": cost_usd, "credits": credits, "media": media_seconds,
            "outcome": outcome, "extras": json.dumps(extras) if extras is not None else None,
            "at": recorded_at,
        },
    )


async def _seed(conn: AsyncConnection) -> dict[str, Any]:
    ws = f"ws_cost_{uuid4().hex[:10]}"
    project = await seed_project(conn, ws, name="cost read")
    run_a = str(uuid4())
    job_1, job_2 = uuid4(), uuid4()
    turn = await _turn(conn, ws=ws, project_id=project.project_id, thread_id=f"thread-{ws}")
    await _model_call(conn, ws=ws, turn_id=turn, sequence=1, cost_usd=Decimal("0.02"), cost_source="metered")
    await _model_call(conn, ws=ws, turn_id=turn, sequence=2, cost_usd=None, cost_source="unpriced")
    await _model_call(conn, ws=ws, turn_id=turn, sequence=3, cost_usd=None, cost_source=None,
                      started_at=T0 - timedelta(days=2))
    p = project.project_id
    await _ledger(conn, ws=ws, project_id=p, project_run_id=run_a, job_id=job_1, provider="exa",
                  operation="search", cost_usd=Decimal("0.007"), extras={"cost_source": "metered"})
    await _ledger(conn, ws=ws, project_id=p, project_run_id=run_a, job_id=job_1, provider="exa",
                  operation="search", phase="estimate", outcome="estimate", cost_usd=None)
    await _ledger(conn, ws=ws, project_id=p, project_run_id=run_a, job_id=job_1, provider="ats",
                  operation="board", cost_usd=Decimal("0"), extras={"cost_source": "free"})
    await _ledger(conn, ws=ws, project_id=p, project_run_id=run_a, job_id=job_1, provider="aiark",
                  operation="company", cost_usd=Decimal("0"), credits=Decimal("1.5"),
                  extras={"cost_source": "metered"})
    await _ledger(conn, ws=ws, project_id=p, project_run_id=run_a, job_id=job_1, provider="openrouter",
                  operation="agent_completion", cost_usd=Decimal("0.5"),
                  extras={"cost_source": "metered", "model": "x-ai/grok-4.6",
                          "prompt_tokens": 1000, "completion_tokens": 200, "cached_prompt_tokens": 300})
    await _ledger(conn, ws=ws, project_id=p, project_run_id=run_a, job_id=job_2, provider="exa",
                  operation="contents", cost_usd=Decimal("0.003"), extras={"cost_source": "metered"},
                  recorded_at=T0 + timedelta(hours=1))
    # the other tenant: one of each, never visible
    other = f"ws_other_{uuid4().hex[:10]}"
    other_project = await seed_project(conn, other, name="other")
    other_turn = await _turn(conn, ws=other, project_id=other_project.project_id, thread_id=f"thread-{other}")
    await _model_call(conn, ws=other, turn_id=other_turn, sequence=1, cost_usd=Decimal("9"), cost_source="metered")
    await _ledger(conn, ws=other, project_id=other_project.project_id, project_run_id=str(uuid4()),
                  job_id=uuid4(), provider="exa", operation="search", cost_usd=Decimal("9"),
                  extras={"cost_source": "metered"})
    return {"ws": ws, "project_id": p, "run_a": run_a, "job_1": job_1, "job_2": job_2,
            "thread_id": f"thread-{ws}"}


def _report(filters: CostFilters | None = None) -> tuple[dict[str, Any], CostReport]:
    async def scenario() -> tuple[dict[str, Any], CostReport]:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            report = await cost_report(
                workspace_id=seeds["ws"], filters=filters, conn_factory=conn_session_factory(conn)
            )
            return seeds, report

    return run_async(scenario())


def test_totals_sum_result_rows_and_turn_receipts_without_double_counting() -> None:
    _, report = _report()
    assert report.provider_usd == Decimal("0.510000")      # 0.007 + 0 + 0 + 0.5 + 0.003
    assert report.turn_model_usd == Decimal("0.020000")    # NULL rows count 0
    assert report.total_usd == Decimal("0.530000")
    assert report.credits == Decimal("1.500")
    assert report.media_seconds == 0


def test_provider_lines_carry_labels_and_skip_the_estimate_phase() -> None:
    _, report = _report()
    lines = {(line.provider, line.operation): line for line in report.providers}
    exa = lines[("exa", "search")]
    assert (exa.calls, exa.ok_calls, exa.cost_usd, exa.metered_calls) == (1, 1, Decimal("0.007000"), 1)
    assert lines[("ats", "board")].free_calls == 1
    assert lines[("aiark", "company")].credits == Decimal("1.500")
    assert report.providers[0].cost_usd >= report.providers[-1].cost_usd  # ordered by spend


def test_model_lines_split_turn_receipts_from_the_research_ledger() -> None:
    _, report = _report()
    turn = [m for m in report.models if m.source == "turn_receipts"]
    ledger = [m for m in report.models if m.source == "research_ledger"]
    assert len(turn) == 1 and turn[0].model == "x-ai/grok-4.6" and turn[0].role == "head_of_abm"
    assert (turn[0].calls, turn[0].cost_usd, turn[0].unpriced_calls) == (3, Decimal("0.020000"), 2)
    assert (turn[0].input_tokens, turn[0].cached_input_tokens, turn[0].output_tokens) == (300, 120, 30)
    assert len(ledger) == 1 and ledger[0].model == "x-ai/grok-4.6"
    assert (ledger[0].calls, ledger[0].cost_usd, ledger[0].input_tokens) == (1, Decimal("0.500000"), 1000)


def test_jobs_and_projects_break_the_spend_down() -> None:
    seeds, report = _report()
    jobs = {line.job_id: line for line in report.jobs}
    assert jobs[seeds["job_1"]].cost_usd == Decimal("0.507000")
    assert jobs[seeds["job_2"]].cost_usd == Decimal("0.003000")
    assert report.jobs[0].job_id == seeds["job_1"]  # largest first
    assert len(report.projects) == 1
    project = report.projects[0]
    assert (project.provider_usd, project.turn_model_usd, project.total_usd) == (
        Decimal("0.510000"), Decimal("0.020000"), Decimal("0.530000"),
    )


def test_job_filter_narrows_the_ledger_and_says_turn_receipts_cannot_follow() -> None:
    seeds, _ = _report()
    _, report = _report(CostFilters(job_id=seeds["job_2"]))
    assert report.provider_usd == Decimal("0.003000")
    assert report.turn_model_usd == Decimal("0")
    assert not [m for m in report.models if m.source == "turn_receipts"]
    assert any("turn" in note for note in report.notes)


def test_thread_filter_narrows_the_receipts_and_says_the_ledger_cannot_follow() -> None:
    seeds, _ = _report()
    _, report = _report(CostFilters(thread_id=seeds["thread_id"]))
    assert report.turn_model_usd == Decimal("0.020000")
    assert report.provider_usd == Decimal("0") and report.providers == ()
    assert any("ledger" in note for note in report.notes)


def test_time_window_applies_to_both_ledgers() -> None:
    _, report = _report(CostFilters(since=T0 - timedelta(minutes=1), until=T0 + timedelta(minutes=1)))
    assert report.provider_usd == Decimal("0.507000")   # job_2's row at T0+1h excluded
    turn = [m for m in report.models if m.source == "turn_receipts"][0]
    assert turn.calls == 2                              # the legacy row two days earlier excluded


def test_not_covered_names_every_ledger_this_read_cannot_see() -> None:
    _, report = _report()
    text_ = " ".join(report.not_covered)
    for word in ("onboarding", "display", "evidence", "design", "before"):
        assert word in text_
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/projections/test_cost_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clue_projections.cost'`.

- [ ] **Step 3: Write the module**

```python
# platform/projections/clue_projections/cost.py
"""The cost read (lane 3 slice 1): what a workspace's work cost, from the rows that recorded it.

Two ledgers, summed once each, never recomputed:

* ``provider_call_ledger`` — every paid call ARV2 makes through ``ProviderCaller`` (Exa, AI Ark,
  Gemini media, structuring, the ATS fetches) **and** the ARV2 research agent's own model rounds
  (``provider='openrouter'``). Only ``phase='result'`` rows are money; an ``estimate`` row is a
  reservation written before the wire. ``extras_json->>'cost_source'`` labels each row
  ``metered`` / ``estimate`` / ``free`` / ``unpriced``.
* ``agent_model_call`` — every conversation-turn model call (Head of ABM and its delegates), with
  the gateway-measured ``cost_usd`` beside the still-zero ``cost_millicredits``. A NULL
  ``cost_usd`` is an unpriced model or a row older than the cost columns; it counts as 0 and as
  ``unpriced``, never as a measured zero.

The two tables never hold the same call, so ``total_usd = provider_usd + turn_model_usd``. The
``models`` section shows the research ledger's model rounds beside the turn receipts for a
per-model view; those research lines are a subset of ``providers`` and are not added to any total.

What this read cannot see is named in ``not_covered`` on every report: the onboarding lane, the
display prewrite and the persona-evidence tool ledger to JSONL files on disk; the design
subsystem's own providers are held (design note R12); turn rows before the cost columns are blank.

Every query is workspace-scoped and read-only (the projections package writes nothing).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import ConnFactory, transaction

__all__ = [
    "CostFilters",
    "CostReport",
    "JobSpendLine",
    "ModelSpendLine",
    "NOT_COVERED",
    "ProjectSpendLine",
    "ProviderSpendLine",
    "cost_report",
]

_ZERO = Decimal("0")
_USD = Decimal("0.000001")
_CREDITS = Decimal("0.001")

#: The spend this read cannot see. Constant and printed on every report so a partial total is
#: never mistaken for a whole one. Each entry names the ledger and the reason.
NOT_COVERED: tuple[str, ...] = (
    "onboarding lane: ProviderCaller writes a JSONL ledger under arv2_raw_root/onboarding "
    "(slice 1b routes it to provider_call_ledger)",
    "display prewrite: JSONL ledger under arv2_raw_root/ledger.jsonl (slice 1b)",
    "persona evidence tool: JSONL ledger under arv2_raw_root/evidence (slice 1b)",
    "design subsystem providers (text-to-image, ad-DNA model): no ledger rows yet (R12 hold)",
    "conversation-turn model calls recorded before agent_model_call.cost_usd existed: blank, "
    "counted as unpriced",
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CostFilters(_Frozen):
    """Narrow the report. A filter a ledger cannot honour empties that ledger's half and adds a
    note; it never silently returns the unfiltered figure."""

    project_id: str | None = None
    project_run_id: str | None = None
    job_id: UUID | None = None
    thread_id: str | None = None
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None


class ProviderSpendLine(_Frozen):
    provider: str
    operation: str
    calls: int = Field(ge=0)
    ok_calls: int = Field(ge=0)
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int = Field(ge=0)
    metered_calls: int = Field(ge=0)
    estimated_calls: int = Field(ge=0)
    free_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)


class ModelSpendLine(_Frozen):
    source: Literal["turn_receipts", "research_ledger"]
    model: str
    role: str | None
    calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal
    unpriced_calls: int = Field(ge=0)


class JobSpendLine(_Frozen):
    job_id: UUID
    calls: int = Field(ge=0)
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int = Field(ge=0)


class ProjectSpendLine(_Frozen):
    project_id: str
    provider_usd: Decimal
    turn_model_usd: Decimal
    total_usd: Decimal


class CostReport(_Frozen):
    workspace_id: str
    filters: CostFilters
    provider_usd: Decimal
    turn_model_usd: Decimal
    total_usd: Decimal
    credits: Decimal
    media_seconds: int = Field(ge=0)
    providers: tuple[ProviderSpendLine, ...]
    models: tuple[ModelSpendLine, ...]
    jobs: tuple[JobSpendLine, ...]
    projects: tuple[ProjectSpendLine, ...]
    not_covered: tuple[str, ...]
    notes: tuple[str, ...]


def _usd(value: Any) -> Decimal:
    return (Decimal(value) if value is not None else _ZERO).quantize(_USD)


def _credits(value: Any) -> Decimal:
    return (Decimal(value) if value is not None else _ZERO).quantize(_CREDITS)


def _ledger_where(filters: CostFilters, workspace_id: str) -> tuple[str, dict[str, Any]]:
    clauses = ["workspace_id = :workspace", "phase = 'result'"]
    params: dict[str, Any] = {"workspace": workspace_id}
    if filters.project_id is not None:
        clauses.append("project_id = :project")
        params["project"] = filters.project_id
    if filters.project_run_id is not None:
        clauses.append("project_run_id = :project_run")
        params["project_run"] = filters.project_run_id
    if filters.job_id is not None:
        clauses.append("entity_research_job_id = :job")
        params["job"] = filters.job_id
    if filters.since is not None:
        clauses.append("recorded_at >= :since")
        params["since"] = filters.since
    if filters.until is not None:
        clauses.append("recorded_at < :until")
        params["until"] = filters.until
    return " AND ".join(clauses), params


def _receipt_where(filters: CostFilters, workspace_id: str) -> tuple[str, dict[str, Any]]:
    clauses = ["m.workspace_id = :workspace"]
    params: dict[str, Any] = {"workspace": workspace_id}
    if filters.project_id is not None:
        clauses.append("t.project_id = :project")
        params["project"] = filters.project_id
    if filters.thread_id is not None:
        clauses.append("t.thread_id = :thread")
        params["thread"] = filters.thread_id
    if filters.since is not None:
        clauses.append("m.started_at >= :since")
        params["since"] = filters.since
    if filters.until is not None:
        clauses.append("m.started_at < :until")
        params["until"] = filters.until
    return " AND ".join(clauses), params


_PROVIDER_LINES = (
    "SELECT provider, operation, count(*) AS calls, "
    " count(*) FILTER (WHERE outcome = 'ok') AS ok_calls, "
    " COALESCE(sum(cost_usd), 0) AS cost_usd, COALESCE(sum(credits), 0) AS credits, "
    " COALESCE(sum(media_seconds), 0) AS media_seconds, "
    " count(*) FILTER (WHERE extras_json->>'cost_source' = 'metered') AS metered_calls, "
    " count(*) FILTER (WHERE extras_json->>'cost_source' = 'estimate') AS estimated_calls, "
    " count(*) FILTER (WHERE extras_json->>'cost_source' = 'free') AS free_calls, "
    " count(*) FILTER (WHERE cost_usd IS NULL OR extras_json->>'cost_source' = 'unpriced') "
    "   AS unpriced_calls "
    "FROM provider_call_ledger WHERE {where} "
    "GROUP BY provider, operation ORDER BY cost_usd DESC, provider, operation"
)

_RESEARCH_MODEL_LINES = (
    "SELECT operation, COALESCE(NULLIF(extras_json->>'model', ''), 'unknown') AS model, "
    " count(*) AS calls, "
    " COALESCE(sum((extras_json->>'prompt_tokens')::bigint), 0) AS input_tokens, "
    " COALESCE(sum((extras_json->>'cached_prompt_tokens')::bigint), 0) AS cached_input_tokens, "
    " COALESCE(sum((extras_json->>'completion_tokens')::bigint), 0) AS output_tokens, "
    " COALESCE(sum(cost_usd), 0) AS cost_usd, "
    " count(*) FILTER (WHERE cost_usd IS NULL OR extras_json->>'cost_source' = 'unpriced') "
    "   AS unpriced_calls "
    "FROM provider_call_ledger WHERE {where} AND provider = 'openrouter' "
    "GROUP BY operation, model ORDER BY cost_usd DESC, model"
)

_JOB_LINES = (
    "SELECT entity_research_job_id AS job_id, count(*) AS calls, "
    " COALESCE(sum(cost_usd), 0) AS cost_usd, COALESCE(sum(credits), 0) AS credits, "
    " COALESCE(sum(media_seconds), 0) AS media_seconds "
    "FROM provider_call_ledger WHERE {where} AND entity_research_job_id IS NOT NULL "
    "GROUP BY entity_research_job_id ORDER BY cost_usd DESC, job_id LIMIT :job_limit"
)

_PROVIDER_BY_PROJECT = (
    "SELECT project_id, COALESCE(sum(cost_usd), 0) AS cost_usd "
    "FROM provider_call_ledger WHERE {where} AND project_id IS NOT NULL GROUP BY project_id"
)

_TURN_MODEL_LINES = (
    "SELECT COALESCE(m.answering_model, m.requested_model) AS model, m.role, count(*) AS calls, "
    " COALESCE(sum(m.input_tokens), 0) AS input_tokens, "
    " COALESCE(sum(m.cache_read_input_tokens), 0) AS cached_input_tokens, "
    " COALESCE(sum(m.output_tokens), 0) AS output_tokens, "
    " COALESCE(sum(m.cost_usd), 0) AS cost_usd, "
    " count(*) FILTER (WHERE m.cost_usd IS NULL) AS unpriced_calls "
    "FROM agent_model_call m JOIN agent_turn t "
    " ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
    "WHERE {where} GROUP BY model, m.role ORDER BY cost_usd DESC, model, m.role"
)

_TURN_MODEL_BY_PROJECT = (
    "SELECT t.project_id, COALESCE(sum(m.cost_usd), 0) AS cost_usd "
    "FROM agent_model_call m JOIN agent_turn t "
    " ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
    "WHERE {where} GROUP BY t.project_id"
)


async def _rows(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await conn.execute(text(sql), params)
    return [dict(row) for row in result.mappings().all()]


async def cost_report(
    *,
    workspace_id: str,
    filters: CostFilters | None = None,
    conn_factory: ConnFactory = transaction,
    job_limit: int = 50,
) -> CostReport:
    """Build one workspace's cost report under ``filters`` (see the module docstring for the
    accounting rules). Always returns a report; an empty workspace is all zeros, not an error."""
    resolved = filters or CostFilters()
    notes: list[str] = []
    ledger_applies = resolved.thread_id is None
    receipts_apply = resolved.project_run_id is None and resolved.job_id is None
    if not ledger_applies:
        notes.append(
            "thread_id filter: the provider ledger carries no thread, so provider lines, jobs "
            "and provider_usd are empty under this filter"
        )
    if not receipts_apply:
        notes.append(
            "project_run_id / job_id filter: conversation-turn receipts carry neither, so "
            "turn_receipts model lines and turn_model_usd are empty under this filter"
        )

    providers: list[ProviderSpendLine] = []
    research_models: list[ModelSpendLine] = []
    jobs: list[JobSpendLine] = []
    provider_by_project: dict[str, Decimal] = {}
    turn_models: list[ModelSpendLine] = []
    turn_by_project: dict[str, Decimal] = {}

    async with conn_factory() as conn:
        if ledger_applies:
            where, params = _ledger_where(resolved, workspace_id)
            for row in await _rows(conn, _PROVIDER_LINES.format(where=where), params):
                providers.append(
                    ProviderSpendLine(
                        provider=row["provider"],
                        operation=row["operation"],
                        calls=int(row["calls"]),
                        ok_calls=int(row["ok_calls"]),
                        cost_usd=_usd(row["cost_usd"]),
                        credits=_credits(row["credits"]),
                        media_seconds=int(row["media_seconds"]),
                        metered_calls=int(row["metered_calls"]),
                        estimated_calls=int(row["estimated_calls"]),
                        free_calls=int(row["free_calls"]),
                        unpriced_calls=int(row["unpriced_calls"]),
                    )
                )
            for row in await _rows(conn, _RESEARCH_MODEL_LINES.format(where=where), params):
                research_models.append(
                    ModelSpendLine(
                        source="research_ledger",
                        model=str(row["model"]),
                        role=str(row["operation"]),
                        calls=int(row["calls"]),
                        input_tokens=int(row["input_tokens"]),
                        cached_input_tokens=int(row["cached_input_tokens"]),
                        output_tokens=int(row["output_tokens"]),
                        cost_usd=_usd(row["cost_usd"]),
                        unpriced_calls=int(row["unpriced_calls"]),
                    )
                )
            for row in await _rows(
                conn, _JOB_LINES.format(where=where), {**params, "job_limit": job_limit}
            ):
                jobs.append(
                    JobSpendLine(
                        job_id=row["job_id"],
                        calls=int(row["calls"]),
                        cost_usd=_usd(row["cost_usd"]),
                        credits=_credits(row["credits"]),
                        media_seconds=int(row["media_seconds"]),
                    )
                )
            for row in await _rows(conn, _PROVIDER_BY_PROJECT.format(where=where), params):
                provider_by_project[str(row["project_id"])] = _usd(row["cost_usd"])
        if receipts_apply:
            where, params = _receipt_where(resolved, workspace_id)
            for row in await _rows(conn, _TURN_MODEL_LINES.format(where=where), params):
                turn_models.append(
                    ModelSpendLine(
                        source="turn_receipts",
                        model=str(row["model"]),
                        role=None if row["role"] is None else str(row["role"]),
                        calls=int(row["calls"]),
                        input_tokens=int(row["input_tokens"]),
                        cached_input_tokens=int(row["cached_input_tokens"]),
                        output_tokens=int(row["output_tokens"]),
                        cost_usd=_usd(row["cost_usd"]),
                        unpriced_calls=int(row["unpriced_calls"]),
                    )
                )
            for row in await _rows(conn, _TURN_MODEL_BY_PROJECT.format(where=where), params):
                turn_by_project[str(row["project_id"])] = _usd(row["cost_usd"])

    provider_usd = sum((line.cost_usd for line in providers), _ZERO).quantize(_USD)
    turn_model_usd = sum((line.cost_usd for line in turn_models), _ZERO).quantize(_USD)
    projects = tuple(
        ProjectSpendLine(
            project_id=project_id,
            provider_usd=provider_by_project.get(project_id, _ZERO).quantize(_USD),
            turn_model_usd=turn_by_project.get(project_id, _ZERO).quantize(_USD),
            total_usd=(
                provider_by_project.get(project_id, _ZERO) + turn_by_project.get(project_id, _ZERO)
            ).quantize(_USD),
        )
        for project_id in sorted(
            set(provider_by_project) | set(turn_by_project),
            key=lambda p: -(provider_by_project.get(p, _ZERO) + turn_by_project.get(p, _ZERO)),
        )
    )
    return CostReport(
        workspace_id=workspace_id,
        filters=resolved,
        provider_usd=provider_usd,
        turn_model_usd=turn_model_usd,
        total_usd=(provider_usd + turn_model_usd).quantize(_USD),
        credits=sum((line.credits for line in providers), _ZERO).quantize(_CREDITS),
        media_seconds=sum(line.media_seconds for line in providers),
        providers=tuple(providers),
        models=tuple(turn_models) + tuple(research_models),
        jobs=tuple(jobs),
        projects=projects,
        not_covered=NOT_COVERED,
        notes=tuple(notes),
    )
```

Note the `research_ledger` model line reuses `role` to carry the ledger `operation` (`agent_completion` vs `chat/completions`) — the DTO docstring must say so; add above the `role` field: `#: turn_receipts: the agent role; research_ledger: the ledger operation (agent_completion / chat/completions).`

Then in `platform/projections/clue_projections/__init__.py` add, in alphabetical position among the existing `from clue_projections.<module> import (...)` blocks:

```python
from clue_projections.cost import (
    NOT_COVERED,
    CostFilters,
    CostReport,
    JobSpendLine,
    ModelSpendLine,
    ProjectSpendLine,
    ProviderSpendLine,
    cost_report,
)
```

and the same eight names to its `__all__`.

- [ ] **Step 4: Run the tests and the guards**

Run: `set -a; source .env; set +a; uv run pytest tests/projections/test_cost_db.py tests/projections/test_no_write_sql_guard.py -v && uv run ruff format platform/projections/clue_projections/cost.py platform/projections/clue_projections/__init__.py && uv run ruff check platform/projections && uv run mypy && uv run lint-imports`
Expected: all PASS. If a Decimal comparison fails on scale (e.g. `Decimal("0.51")` vs `Decimal("0.510000")`), the quantize is missing on that path — fix the path, not the test. The no-write guard must stay green: the docstring says "writes nothing", never the SQL tokens.

- [ ] **Step 5: Commit**

```bash
git add platform/projections/clue_projections/cost.py platform/projections/clue_projections/__init__.py tests/projections/test_cost_db.py
git commit -m "feat(projections): the cost read — provider, model, job and project spend from the two ledgers

Sums provider_call_ledger result rows and agent_model_call receipts once each (the tables never
overlap), labels every line by cost_source, honours workspace/project/run/job/thread/time
filters, and names on every report the ledgers it cannot see (JSONL onboarding/display/evidence,
the design subsystem's providers, pre-cost-column turn rows)."
```

---

### Task 5: `GET /cost/report` on the projections router

**Files:**
- Modify: `platform/api/clue_api/projections_app.py` (inside `create_projections_router`, after the `/agent/...` routes, ~line 300)
- Test: `tests/api/test_cost_report_endpoint_db.py`

**Interfaces:**
- Consumes: Task 4 `cost_report`, `CostFilters`; the router's `conn_factory`; `WorkspaceDep` (the `X-Workspace-Id` header seam).
- Produces: `GET /cost/report?project_id&project_run_id&job_id&thread_id&since&until` → `{"schema_version": PROJECTIONS_SCHEMA_VERSION, "report": <CostReport json>}`; `422` when `since >= until`; `401` without the workspace header (existing seam).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_cost_report_endpoint_db.py
"""Lane 3 slice 1, Task 5: ``GET /cost/report`` through the real projections app, bound to the
test's rolled-back connection (the ``test_projections_app`` idiom)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _app(conn: AsyncConnection):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


async def _seed_one_exa_row(conn: AsyncConnection) -> str:
    ws = f"ws_cost_ep_{uuid4().hex[:10]}"
    project = await seed_project(conn, ws, name="endpoint")
    await conn.execute(
        text(
            "INSERT INTO provider_call_ledger (call_id, workspace_id, project_id, project_run_id, "
            " entity_research_job_id, provider, operation, label, phase, attempts, estimate_usd, "
            " cost_usd, outcome, extras_json, recorded_at) "
            "VALUES (:call, :ws, :p, :run, :job, 'exa', 'search', 'search-x', 'result', 1, 0.01, "
            " 0.007, 'ok', CAST('{\"cost_source\": \"metered\"}' AS jsonb), :at)"
        ),
        {"call": uuid4(), "ws": ws, "p": project.project_id, "run": str(uuid4()), "job": uuid4(),
         "at": datetime(2026, 9, 14, tzinfo=UTC)},
    )
    return ws


async def _get(conn: AsyncConnection, *, workspace_id: str | None, **params: Any) -> httpx.Response:
    headers = {} if workspace_id is None else {"X-Workspace-Id": workspace_id}
    async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn)), base_url="http://t") as client:
        return await client.get("/cost/report", params=params, headers=headers)


def test_report_is_served_workspace_scoped() -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _seed_one_exa_row(conn)
            mine = await _get(conn, workspace_id=ws)
            theirs = await _get(conn, workspace_id="ws_nobody")
            return mine.json(), theirs.json()

    mine, theirs = run_async(scenario())
    assert mine["schema_version"] == "2"
    assert Decimal(mine["report"]["provider_usd"]) == Decimal("0.007")
    assert mine["report"]["providers"][0]["provider"] == "exa"
    assert Decimal(theirs["report"]["total_usd"]) == Decimal("0")
    assert theirs["report"]["not_covered"]  # the honesty list rides every response


def test_missing_workspace_header_is_401_and_bad_window_is_422() -> None:
    async def scenario() -> tuple[int, int]:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _seed_one_exa_row(conn)
            no_header = await _get(conn, workspace_id=None)
            bad_window = await _get(
                conn, workspace_id=ws, since="2026-09-14T12:00:00Z", until="2026-09-14T11:00:00Z"
            )
            return no_header.status_code, bad_window.status_code

    assert run_async(scenario()) == (401, 422)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_cost_report_endpoint_db.py -v`
Expected: FAIL — `404` where `200` was expected (`mine["report"]` KeyError).

- [ ] **Step 3: Add the route**

In `platform/api/clue_api/projections_app.py`, add to the `from clue_projections import (...)` import block: `CostFilters, cost_report` (and `from datetime import datetime` / `from uuid import UUID` if not already imported). Inside `create_projections_router`, after the `@router.get("/agent/routes/{surface_name}/{subject_id}")` handler block, add:

```python
    # -- cost (lane 3 slice 1): the two ledgers summed once each, workspace-scoped --

    @router.get("/cost/report")
    async def get_cost_report(
        workspace_id: WorkspaceDep,
        project_id: str | None = None,
        project_run_id: str | None = None,
        job_id: UUID | None = None,
        thread_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        if since is not None and until is not None and since >= until:
            raise HTTPException(status_code=422, detail="since must be before until")
        filters = CostFilters(
            project_id=project_id,
            project_run_id=project_run_id,
            job_id=job_id,
            thread_id=thread_id,
            since=since,
            until=until,
        )
        report = await cost_report(
            workspace_id=workspace_id, filters=filters, conn_factory=conn_factory
        )
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "report": report.model_dump(mode="json"),
        }
```

`CostFilters.since`/`until` are `AwareDatetime`; FastAPI parses `2026-09-14T12:00:00Z` as aware. A naive value raises a Pydantic `ValidationError` inside the handler — wrap the `CostFilters(...)` construction in `try/except ValidationError as error: raise HTTPException(status_code=422, detail=str(error))` (import `ValidationError` from `pydantic`).

- [ ] **Step 4: Run the test and gates**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_cost_report_endpoint_db.py -v && uv run ruff format platform/api/clue_api/projections_app.py && uv run ruff check platform/api/clue_api/projections_app.py && uv run mypy`
Expected: PASS; gates clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/projections_app.py tests/api/test_cost_report_endpoint_db.py
git commit -m "feat(api): GET /cost/report serves the lane 3 cost read, workspace-scoped

One route with project/run/job/thread/time filters over clue_projections.cost_report; 422 on an
inverted window; the existing X-Workspace-Id seam scopes it."
```

---

### Task 6: The operator CLI and `make cost-report`

**Files:**
- Create: `platform/projections/clue_projections/cost_cli.py`
- Modify: `Makefile` (after the `eval-design-exit` target)
- Test: `tests/projections/test_cost_cli.py`

**Interfaces:**
- Consumes: Task 4 `cost_report`, `CostFilters`, `CostReport`.
- Produces: `render_report(report: CostReport) -> str` (pure), `build_parser() -> argparse.ArgumentParser`, `main(argv: Sequence[str] | None = None) -> int`. `python -m clue_projections.cost_cli --workspace <id> [--project ID] [--project-run ID] [--job UUID] [--thread ID] [--since ISO] [--until ISO] [--json]`. Reads `CLUE_DATABASE_URL` through `clue_db.transaction` (the default `conn_factory`).

- [ ] **Step 1: Write the failing test**

```python
# tests/projections/test_cost_cli.py
"""Lane 3 slice 1, Task 6: the cost CLI renders a report without touching a database."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from clue_projections.cost import (
    NOT_COVERED,
    CostFilters,
    CostReport,
    JobSpendLine,
    ModelSpendLine,
    ProjectSpendLine,
    ProviderSpendLine,
)
from clue_projections.cost_cli import build_parser, render_report

JOB = UUID("00000000-0000-0000-0000-000000000001")


def _report() -> CostReport:
    return CostReport(
        workspace_id="acme",
        filters=CostFilters(project_id="p1"),
        provider_usd=Decimal("0.510000"),
        turn_model_usd=Decimal("0.020000"),
        total_usd=Decimal("0.530000"),
        credits=Decimal("1.500"),
        media_seconds=0,
        providers=(
            ProviderSpendLine(provider="openrouter", operation="agent_completion", calls=1, ok_calls=1,
                              cost_usd=Decimal("0.500000"), credits=Decimal("0"), media_seconds=0,
                              metered_calls=1, estimated_calls=0, free_calls=0, unpriced_calls=0),
            ProviderSpendLine(provider="exa", operation="search", calls=2, ok_calls=2,
                              cost_usd=Decimal("0.010000"), credits=Decimal("0"), media_seconds=0,
                              metered_calls=2, estimated_calls=0, free_calls=0, unpriced_calls=0),
        ),
        models=(
            ModelSpendLine(source="turn_receipts", model="x-ai/grok-4.6", role="head_of_abm", calls=3,
                           input_tokens=300, cached_input_tokens=120, output_tokens=30,
                           cost_usd=Decimal("0.020000"), unpriced_calls=2),
        ),
        jobs=(JobSpendLine(job_id=JOB, calls=3, cost_usd=Decimal("0.507000"), credits=Decimal("1.500"),
                           media_seconds=0),),
        projects=(ProjectSpendLine(project_id="p1", provider_usd=Decimal("0.510000"),
                                   turn_model_usd=Decimal("0.020000"), total_usd=Decimal("0.530000")),),
        not_covered=NOT_COVERED,
        notes=("a note",),
    )


def test_render_report_prints_every_section_and_the_honesty_list() -> None:
    out = render_report(_report())
    assert "workspace acme" in out and "project_id=p1" in out
    assert "total_usd 0.530000" in out
    assert "openrouter  agent_completion" in out and "exa  search" in out
    assert "x-ai/grok-4.6" in out and "unpriced 2" in out
    assert str(JOB) in out
    assert "p1" in out
    assert "NOT COVERED" in out and "onboarding" in out
    assert "a note" in out


def test_parser_maps_every_flag_to_a_filter() -> None:
    args = build_parser().parse_args(
        ["--workspace", "acme", "--project", "p1", "--job", str(JOB),
         "--since", "2026-09-14T00:00:00Z", "--until", "2026-09-15T00:00:00Z", "--json"]
    )
    assert args.workspace == "acme" and args.project == "p1" and args.job == JOB
    assert args.since == datetime(2026, 9, 14, tzinfo=UTC)
    assert args.until == datetime(2026, 9, 15, tzinfo=UTC)
    assert args.json is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/projections/test_cost_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clue_projections.cost_cli'`.

- [ ] **Step 3: Write the CLI**

```python
# platform/projections/clue_projections/cost_cli.py
"""``python -m clue_projections.cost_cli`` — the operator's view of :func:`cost_report`.

Prints the report as aligned text (default) or JSON (``--json``). Reads the database named by
``CLUE_DATABASE_URL`` through the package's default connection factory; nothing here writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from clue_projections.cost import CostFilters, CostReport, cost_report

__all__ = ["build_parser", "main", "render_report"]


def _iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{value!r} needs a timezone (e.g. 2026-09-14T00:00:00Z)")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m clue_projections.cost_cli",
        description="What a workspace's work cost, from the provider ledger and the turn receipts.",
    )
    parser.add_argument("--workspace", required=True, help="workspace id (the tenant)")
    parser.add_argument("--project", default=None, help="project id")
    parser.add_argument("--project-run", dest="project_run", default=None, help="project run id")
    parser.add_argument("--job", type=UUID, default=None, help="account-research job id")
    parser.add_argument("--thread", default=None, help="conversation thread id (turn receipts only)")
    parser.add_argument("--since", type=_iso, default=None, help="inclusive ISO-8601 with timezone")
    parser.add_argument("--until", type=_iso, default=None, help="exclusive ISO-8601 with timezone")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def _section(title: str, header: str, rows: list[str]) -> list[str]:
    if not rows:
        return [f"{title}: none"]
    return [title, f"  {header}", *(f"  {row}" for row in rows)]


def render_report(report: CostReport) -> str:
    filters = ", ".join(
        f"{name}={value}" for name, value in report.filters.model_dump().items() if value is not None
    )
    lines = [
        f"cost report — workspace {report.workspace_id}" + (f" ({filters})" if filters else ""),
        f"  total_usd {report.total_usd}  provider_usd {report.provider_usd}  "
        f"turn_model_usd {report.turn_model_usd}  credits {report.credits}  "
        f"media_seconds {report.media_seconds}",
        "",
    ]
    lines += _section(
        "providers (result rows only)",
        "provider  operation  calls  ok  usd  credits  media_s  metered/estimate/free/unpriced",
        [
            f"{p.provider}  {p.operation}  {p.calls}  {p.ok_calls}  {p.cost_usd}  {p.credits}  "
            f"{p.media_seconds}  {p.metered_calls}/{p.estimated_calls}/{p.free_calls}/{p.unpriced_calls}"
            for p in report.providers
        ],
    )
    lines.append("")
    lines += _section(
        "models",
        "source  model  role/operation  calls  in  cached  out  usd  unpriced",
        [
            f"{m.source}  {m.model}  {m.role or '-'}  {m.calls}  {m.input_tokens}  "
            f"{m.cached_input_tokens}  {m.output_tokens}  {m.cost_usd}  unpriced {m.unpriced_calls}"
            for m in report.models
        ],
    )
    lines.append("")
    lines += _section(
        "jobs (largest first)",
        "job_id  calls  usd  credits  media_s",
        [f"{j.job_id}  {j.calls}  {j.cost_usd}  {j.credits}  {j.media_seconds}" for j in report.jobs],
    )
    lines.append("")
    lines += _section(
        "projects",
        "project_id  provider_usd  turn_model_usd  total_usd",
        [f"{p.project_id}  {p.provider_usd}  {p.turn_model_usd}  {p.total_usd}" for p in report.projects],
    )
    lines.append("")
    lines += ["NOT COVERED by this read:", *(f"  - {item}" for item in report.not_covered)]
    if report.notes:
        lines += ["", "notes:", *(f"  - {note}" for note in report.notes)]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    filters = CostFilters(
        project_id=args.project,
        project_run_id=args.project_run,
        job_id=args.job,
        thread_id=args.thread,
        since=args.since,
        until=args.until,
    )
    report = asyncio.run(cost_report(workspace_id=args.workspace, filters=filters))
    if args.json:
        sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(render_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by hand and by the live proof
    raise SystemExit(main())
```

Add to the `Makefile` after `eval-design-exit`:

```make
# --- cost (lane 3 slice 1) ---------------------------------------------------
cost-report: ## Print a workspace's cost report from the two ledgers. Usage: make cost-report ARGS="--workspace acme [--project P] [--json]"
	uv run python -m clue_projections.cost_cli $(ARGS)
```

(The `Makefile` has no pass-through variable today; `ARGS` is introduced here.)

- [ ] **Step 4: Run the test and gates**

Run: `uv run pytest tests/projections/test_cost_cli.py tests/projections/test_no_write_sql_guard.py -v && uv run ruff format platform/projections/clue_projections/cost_cli.py && uv run ruff check platform/projections && uv run mypy && uv run lint-imports && uv run python -m clue_projections.cost_cli --help`
Expected: PASS; `--help` prints the usage.

- [ ] **Step 5: Commit**

```bash
git add platform/projections/clue_projections/cost_cli.py tests/projections/test_cost_cli.py Makefile
git commit -m "feat(projections): cost_cli and make cost-report — the operator's cost view

Text or JSON rendering of cost_report with every filter as a flag; prints the not-covered
list on every run so a partial total is never read as a whole one."
```

---

### Task 7: Live proof on the lane stack

**Files:**
- Create: `_memory/2026-09-14-lane3-slice1-cost-read.md`

**Interfaces:**
- Consumes: everything above, running on the lane stack (`./scripts/dev_stack_san_salvador.sh up`; ports 3020 / 8010 / 8020 / 8030). The stack must be restarted after Task 3 so the fleet worker and API twins run the new recorder.

- [ ] **Step 1: Migrate the lane database and restart the stack**

Run: `set -a; source .env; set +a; uv run alembic upgrade head && ./scripts/dev_stack_san_salvador.sh down && ./scripts/dev_stack_san_salvador.sh up && ./scripts/dev_stack_san_salvador.sh status`
Expected: one head; all processes up (start the workers staggered, per the runbook note on the field-registry seed race).

- [ ] **Step 2: Produce one cheap conversation turn**

Send one short message in an existing project thread through the frontend at `:3020` (e.g. "What is in this project's library?" — a read-only turn, one or two model rounds). This spends real money (cents); it is the one live call this slice makes. Note the thread id from the URL.

- [ ] **Step 3: Prove the receipt carries the cost**

Run (substituting the thread id):

```bash
set -a; source .env; set +a
psql "$CLUE_DATABASE_URL" -c "
SELECT m.sequence, m.answering_model, m.cost_usd, m.cost_source, m.cost_millicredits
FROM agent_model_call m JOIN agent_turn t ON t.id = m.turn_id
WHERE t.thread_id = '<thread id>' ORDER BY m.started_at DESC, m.sequence LIMIT 5;"
```

Expected: the newest rows show a non-NULL `cost_usd`, `cost_source = 'metered'` (OpenRouter reports usage) and `cost_millicredits = 0`. If `cost_source` is `unpriced`, the gateway did not stamp a rate for the configured model — that is a model-configuration fact to record, not a slice-1 defect; the report will show it as unpriced.

- [ ] **Step 4: Prove the read and the two surfaces agree**

```bash
set -a; source .env; set +a
make cost-report ARGS="--workspace <workspace id> --thread <thread id>"
make cost-report ARGS="--workspace <workspace id>"
curl -s -H "X-Workspace-Id: <workspace id>" "http://localhost:<projections port>/cost/report" | python -m json.tool | head -60
```

Expected: the thread-filtered run shows the turn's model spend and the note that the ledger cannot follow a thread filter; the unfiltered run shows the workspace's provider lines (Exa, AI Ark, OpenRouter research rounds from earlier research runs on this database), the jobs list largest-first, and the NOT COVERED list; the endpoint's `total_usd` equals the CLI's for the same filters.

- [ ] **Step 5: Write the session note**

```markdown
# 2026-09-14 — Lane 3 slice 1: the cost read — proven on the lane stack

Branch `lane3/slice1-cost-read` (worktree off `research-streaming`). Commits: <list the seven>.

## What landed
- `agent_model_call.cost_usd` + `cost_source` (migration <id>); the conversation-turn recorder
  stamps them from the gateway's clue_cost_cents/clue_cost_source through the one shared reader
  `clue_gateway.metadata.cost_cents_from_metadata` (the ARV2 agent's `_cost_cents` delegates).
  `cost_millicredits` untouched (still 0; credits milestone).
- `clue_projections.cost` — `cost_report()`; `GET /cost/report`; `python -m
  clue_projections.cost_cli` / `make cost-report`.

## Proof
- Turn <id> in thread <id>: rows sequence 1..N carry cost_usd=<…>, cost_source=metered.
- `make cost-report --workspace <ws>`: total_usd <…>; providers: <top three lines>.
- Endpoint total equals CLI total for the same filters.

## Discovered, recorded, not done here
- Slice 1b: onboarding lane, display prewrite, persona-evidence tool ledger to JSONL
  (`arv2/onboarding_driver.py:281-295` via `fleet_main.py:720`; `arv2/display/page.py:100-118`;
  `onboarding_evidence_tools.py:228-245`). Route them to `provider_call_ledger`: `LedgerStamp`
  gains optional `project_id` / `project_run_id`; the onboarding driver already holds a
  `conn_factory` and an `ArtifactSink`, so it swaps `JsonlLedger`/`FileRawSink` for
  `BufferedLedger`/`BufferedRawSink` and drains after each step under its own connection with
  `job_id = run_id` (discovery's pattern, `discovery_driver.py:1221-1225`). The reconciler
  (`fleet_main.py:720`) builds its own caller per run and needs the same treatment. The
  evidence tool runs inside a chat turn with no connection in hand — needs a drain seam.
- Design subsystem spend (R12 hold).

## Verification owed
- <anything skipped, with why>
```

- [ ] **Step 6: Commit**

```bash
git add _memory/2026-09-14-lane3-slice1-cost-read.md
git commit -m "docs(memory): lane 3 slice 1 proven on the lane stack; slice 1b recorded"
```

---

### Task 8: Design note and lane index reflect what was found

**Files:**
- Modify: `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` (§3 table "LLM cost per call" row; §5.5; §9)
- Modify: `docs/superpowers/plans/2026-09-13-lane-plan-index.md` (new "Lane 3" section)

**Interfaces:** none (documentation).

- [ ] **Step 1: Correct the design note**

In §3's table, change the "LLM cost per call" row's State cell to: `Measured at the gateway on every call; the ARV2 research ledger records it. The conversation-turn receipt recorded 0 until slice 1 (Task 1–3) added cost_usd/cost_source.` Add a row: `| Onboarding / display / evidence spend | ProviderCaller with JsonlLedger (arv2/onboarding_driver.py, arv2/display/page.py, onboarding_evidence_tools.py) | On disk, not queryable — slice 1b routes them to provider_call_ledger. |`

In §5.5, replace the paragraph starting "No new table. One read" with:

```markdown
No new table. One read, `clue_projections.cost.cost_report`, over the two ledgers:

- provider spend from `provider_call_ledger` (`phase='result'` rows only), grouped by provider and
  operation, with the four `cost_source` labels counted per line, plus per-job and per-project
  lines. The ARV2 research agent's own model rounds are on this ledger as `openrouter` rows.
- conversation-turn model spend from `agent_model_call` joined through the turn to its project and
  thread, grouped by model and role. **Slice 1 discovered this table recorded every call at zero
  cost** (`cost_millicredits=0`, deferred to the credits milestone) and added `cost_usd` +
  `cost_source`, stamped from the cost the gateway already measures; rows older than that are
  blank and counted `unpriced`.

The two tables never hold the same call, so the total is their plain sum. Served as
`GET /cost/report` on the projections router and as `make cost-report`. Every report carries a
`not_covered` list naming the spend this read cannot see: the onboarding lane, the display
prewrite and the persona-evidence tool (JSONL ledgers on disk — **slice 1b** routes them to the
Postgres ledger), the design subsystem's providers (R12 hold), and pre-cost-column turn rows.
```

In §9, after slice 1 add: `1b. **JSONL ledgers onto Postgres.** The onboarding lane, the display prewrite and the persona-evidence tool write through \`ProviderCaller\` to JSONL files; route them to \`provider_call_ledger\` (mechanics in \`_memory/2026-09-14-lane3-slice1-cost-read.md\`). Runs after slice 1, before the pilot's first customer onboarding is counted.`

- [ ] **Step 2: Add lane 3 to the lane index**

Append to `docs/superpowers/plans/2026-09-13-lane-plan-index.md` after the Lane 2 section:

```markdown
## Lane 3 — telemetry and cost (worktree `lane3/*` off `research-streaming`)

Design note: `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md`.

| # | Plan | What it builds | Depends on |
| --- | --- | --- | --- |
| 1 | `2026-09-14-lane3-slice1-cost-read.md` | `agent_model_call.cost_usd`/`cost_source` stamped from the gateway; `clue_projections.cost`; `GET /cost/report`; `make cost-report` | nothing |
| 1b | (to write) | onboarding / display / evidence JSONL ledgers onto `provider_call_ledger` | 1 |
| 2 | (to write) | OTel exporter + FastAPI/httpx instrumentors + Sentry at the roots; traceparent on turn and job rows | 1 (sequencing only) |
| 3 | (to write) | Langfuse: callback in the runtime tuple, gateway path, provider-caller observations, redaction, ids stamped back | 2 |
| 4 | (to write) | entity tags on traces | 3 |

Held, high priority: the design subsystem (R12). Separate lane after 1–3: ARV2 erasure (R13).
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md docs/superpowers/plans/2026-09-13-lane-plan-index.md
git commit -m "docs(lane3): design note records the zero-cost receipt and JSONL ledger findings; lane index gains lane 3"
```

---

## Self-review

**Spec coverage.** §5.5 "one read over the two ledgers, per run / job / workspace / overall, by provider and operation, served as a projection endpoint and a make target" → Tasks 4, 5, 6. §10 item 4 (LLM calls capture cost) → Tasks 1–3 close the gap the note did not know about. §10 item 5 (expensive APIs capture cost) → already true for ARV2; the JSONL gap is named (Task 8, slice 1b), not hidden. R2 (Postgres is the record; never recompute) → no rate is applied anywhere; the receipt stores the gateway's figure. R9 (no per-agent cost columns) → the read groups by role only because the row already carries it. R11/R12 → no legacy or design file is touched. §9 "each slice closes with a live proof on the lane stack" → Task 7.

**Placeholders.** None: every step carries its code; the two `<generated>` markers in Task 1 are Alembic's own output, and Task 7's `<…>` are values read off the live run.

**Type consistency.** `cost_cents_from_metadata` (Task 2) is what Task 3 imports; `ModelCostSource` is defined in Task 3 step 3 and imported in step 8; `CostFilters` / `CostReport` / `cost_report` (Task 4) are the names Tasks 5 and 6 use; `render_report` / `build_parser` / `main` (Task 6) match its test. `ProviderSpendLine` fields in the Task 6 test match the Task 4 DTO field for field. `ModelSpendLine.role` carries the ledger `operation` for `research_ledger` lines, stated in both the DTO comment and the module docstring.
