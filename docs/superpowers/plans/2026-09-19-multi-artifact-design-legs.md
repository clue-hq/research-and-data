# Multi-Artifact Design Legs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One chat message can ask for N design artifacts (twenty 1:1 ads for twenty tagged accounts; five variants of one ad); the platform births N documents on one leg, runs N design runs in parallel across the fleet's free slots, hands back once, opens a tab per document, and routes follow-up messages to the documents they address by the exit judge's judgement.

**Architecture:** One open leg per thread now holds a SET of documents (`design_leg_document`, position-ordered; `design_leg.document_id` keeps meaning position 0). `open_design_leg@5` takes `artifacts: [{title, note, account_id?}]`. The leg runner builds one frozen envelope per addressed document, creates N queued design runs + N `design_job` tasks in one transaction, and drives them with the inline lane's rule applied across siblings (drive what nobody holds, wait only on a live foreign lease). Exit judgment v3 adds `addressed_artifacts` and `clarifying_question`. Nothing about how ONE design run executes changes.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / Alembic / pydantic v2 / pytest (platform); LangGraph + deepagents (design runtime, untouched); Next.js + Zod + `node --test` (frontend).

**Spec:** `docs/superpowers/specs/archive/2026-09-19-multi-artifact-design-legs-design.md` — read it first; every task below cites its section.

## Global Constraints

- **Base:** `research-streaming` at `21e3ef1e9` or later (PR #67 merged). Alembic head at plan time: `d659c2d2b537` — verify with `uv run alembic heads` before Task 1 and chain off whatever the head is.
- **Migrations:** `uv run alembic revision -m "<slug>"` (hash id, never hand-picked); `upgrade()`/`downgrade()` both; exactly one head; `make db-smoke` on a throwaway DB.
- **Commits:** local only, never push; no AI attribution or `Co-Authored-By` trailers; one commit per task (message shape `feat(design-legs): …`).
- **Tests that spend money are forbidden.** Never run `make check` or a broad `pytest` with real keys in the env; run focused files, and DB suites only with the lane stack DOWN (`./scripts/dev_stack_san_salvador.sh down`) so live workers do not claim test jobs. Use `--ignore-glob='*_live.py'` for anything wider.
- **Gates per task:** `uv run ruff check <files>` + `uv run ruff format <files>`, `uv run mypy <files>`, `uv run lint-imports`, the task's focused pytest files. Frontend tasks: `npm run design-system:build && npm run lint && npm run build` from `apps/frontend`, plus `npm test`.
- **Single-artifact legs stay byte-identical:** position 0 keeps today's document id and run id derivations; a one-document batch calls the lane's existing `drive(envelope)`; the bundle bytes of a one-item leg differ ONLY by the new `artifacts` key (asserted in Task 3).
- **No pre-emptive caps:** the `artifacts` list bound is 200 (schema sanity, matching the tool's `claim_refs`), notes ≤ 2,000 chars, bundle cap `24_000 + 1_500 * (N - 1)` bytes. No batch-size confirmation.
- **Prompt and skill text is founder-reviewed before it lands** (standing rule): Task 4's Head-of-ABM prompt v11 text and Task 8's judge v3 prompt text are presented to the founder in chat before the commit.
- **Free-flowing, not mechanical:** the judge decides addressing in prose plus numbers; no intent enums; the only engine-authored fallback is the multi-document ask (spec §3.5).
- **Seam rule:** nothing under `subsystems/clue-design/` imports platform internals; `clue_design` (the substrate package under `subsystems/design/`) imports only core/db/config/obs/storage.

---

## File structure

**Substrate (`subsystems/design/clue_design/`)**
- `legs.py` — MODIFY: `add_leg_documents`, `list_leg_documents`, `LegDocumentSpec`.
- `accounts.py` — MODIFY: `ensure_web_account_for_entity`.
- `runs.py` — MODIFY: `runs_for_execution`.
- `leg_context.py` — MODIFY: render the per-item "THIS ARTIFACT" lines inside the BRIEF fence.
- `exit_judgment.py` — MODIFY: v3 judgment/decision models, `decide_exit(artifact_count=)`, prompt v3.
- `evals/golden.py`, `evals/fixtures/*.json` — MODIFY: `ExpectedDecision.addressed/ask`, new fixtures.

**Platform (`platform/api/clue_api/`)**
- `alembic/versions/<hash>_design_leg_documents.py` — CREATE.
- `design_leg_tools.py` — MODIFY: `open_design_leg@5` (`artifacts`), N births, account stamp, bundle.
- `design_leg_wiring.py` — MODIFY: `design_leg_run_id(turn_id, position)`, batch dispatch/join, per-document summary, ask outcome, judge inputs, stop over the batch, feed derivations with account.
- `design_fleet.py` — MODIFY: `InlineDesignLaneDriver.drive_batch`.
- `design_event_forwarder.py` — no change (one forwarder per envelope).
- `agent_turn_fleet_wiring.py` — MODIFY: judge builder passes `artifacts`; `_DesignLaneUnavailable.drive_batch`.
- `chat/composer_context.py`, `chat/router.py`, `chat/schemas.py` — MODIFY: leg document SET in tag validation; `account` on the feed wire.
- `agent_registry_wiring.py`, `recipe_wiring.py`, `recipe_contracts.py`, `conversation_turns.py`, `chat/composer_context.py` — MODIFY: the v58 / recipe 29 pins.
- `platform/agents/catalog/profiles/head-of-abm/v58/profile.yaml`, `platform/agents/catalog/prompts/head-of-abm/v11/SYSTEM.md`, `platform/execution/recipes/recipe0-stage0-v29.json`, `platform/agents/clue_agents/manual/build.py` — CREATE/MODIFY.

**Frontend (`apps/frontend/src/features/`)**
- `chat-shell/model/artifact-auto-open.ts` — MODIFY: `artifactsToAutoOpen` returns a list.
- `chat-shell/components/chat-surface.tsx` — MODIFY: open each, activate the first.
- `design-editor/model/artifact.ts`, `design-editor/adapter/gallery.ts` — MODIFY: `account` on the feed item, mapped onto the existing `accountId/accountName/accountLogoPath` card fields.

**Tests** — named per task below.

---

### Task 1: The leg's documents — migration and DAL

**Files:**
- Create: `alembic/versions/<hash>_design_leg_documents.py`
- Modify: `subsystems/design/clue_design/legs.py`
- Test: `tests/design/test_design_leg_documents_dal_db.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class LegDocumentSpec:
      document_id: str
      position: int
      note: str = ""

  async def add_leg_documents(conn, *, workspace_id: str, leg_id: str, documents: Sequence[LegDocumentSpec]) -> None
  async def list_leg_documents(conn, *, workspace_id: str, leg_id: str) -> list[JsonObject]
  # each row: {"document_id", "position", "note", "title", "doc_kind", "current_version", "account_id"} — position order
  ```

- [ ] **Step 1: Write the failing DAL test**

```python
# tests/design/test_design_leg_documents_dal_db.py
"""Spec §3.2 — one leg, many documents, position-ordered; design_leg.document_id stays position 0."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import legs as design_legs
from clue_design.legs import LegDocumentSpec
from tests._workspace import seed_project
from tests.design.conftest import run_async
from tests.design.test_design_leg_dal_db import _seed_thread_and_execution  # workspace, thread, execution


async def _seed_scene_document(conn: AsyncConnection, *, workspace_id: str, title: str) -> str:
    document_id = f"doc_{uuid4().hex}"
    await conn.execute(
        text(
            "INSERT INTO design_document (id, workspace_id, title, status, doc_kind, "
            "current_scene_json, current_version) VALUES (:id, :w, :t, 'draft', 'scene', "
            "CAST(:scene AS jsonb), 0)"
        ),
        {"id": document_id, "w": workspace_id, "t": title,
         "scene": '{"schema_version":1,"meta":{"id":"%s","title":"%s"},"pages":{},"nodes":{}}' % (document_id, title)},
    )
    return document_id


def test_leg_documents_list_in_position_order_with_document_facts() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            from clue_db import transaction
            async with transaction() as conn:
                seeds = await _seed_thread_and_execution(conn)
                ws = seeds["workspace_id"]
                first = await _seed_scene_document(conn, workspace_id=ws, title="Apollo ad")
                second = await _seed_scene_document(conn, workspace_id=ws, title="Mercy ad")
                leg = await design_legs.open_leg(
                    conn, workspace_id=ws, thread_id=seeds["thread_id"],
                    parent_execution_id=seeds["execution_id"], document_id=first,
                    document_version_guard=0,
                )
                await design_legs.add_leg_documents(
                    conn, workspace_id=ws, leg_id=leg["id"],
                    documents=[LegDocumentSpec(first, 0, "for Apollo"), LegDocumentSpec(second, 1, "for Mercy")],
                )
                rows = await design_legs.list_leg_documents(conn, workspace_id=ws, leg_id=leg["id"])
                assert [(r["position"], r["document_id"], r["note"], r["title"], r["doc_kind"]) for r in rows] == [
                    (0, first, "for Apollo", "Apollo ad", "scene"),
                    (1, second, "for Mercy", "Mercy ad", "scene"),
                ]
                assert rows[0]["current_version"] == 0 and rows[0]["account_id"] is None
                # A duplicate position, or the same document twice, is refused by the schema.
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await design_legs.add_leg_documents(
                            conn, workspace_id=ws, leg_id=leg["id"],
                            documents=[LegDocumentSpec(second, 0)],
                        )
                await conn.rollback()
    run_async(scenario())


def test_a_foreign_workspace_document_cannot_join_a_leg() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            from clue_db import transaction
            async with transaction() as conn:
                seeds = await _seed_thread_and_execution(conn)
                other = await seed_project(conn, f"ws_other_{uuid4().hex[:8]}", name="other")
                foreign = await _seed_scene_document(conn, workspace_id=other.workspace_id, title="x")
                leg = await design_legs.open_leg(
                    conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"],
                    parent_execution_id=seeds["execution_id"],
                )
                with pytest.raises(IntegrityError):
                    await design_legs.add_leg_documents(
                        conn, workspace_id=seeds["workspace_id"], leg_id=leg["id"],
                        documents=[LegDocumentSpec(foreign, 0)],
                    )
                await conn.rollback()
    run_async(scenario())
```

Check `_seed_thread_and_execution` in `tests/design/test_design_leg_dal_db.py:28` for the keys it returns (`workspace_id`, `thread_id`, `execution_id`) and adjust the names above to match exactly.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/design/test_design_leg_documents_dal_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'LegDocumentSpec'`.

- [ ] **Step 3: Write the migration**

Run `uv run alembic revision -m "design leg documents"`, then fill the generated file:

```python
"""design leg documents

Revision ID: <generated>
Revises: d659c2d2b537   # verify with `uv run alembic heads`
Create Date: <generated>

Spec 2026-09-19 §3.2: one open leg holds a SET of documents. `design_leg.document_id` keeps
meaning position 0 so every single-document reader is unchanged; this table is the set.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "d659c2d2b537"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_leg_document (
            leg_id        text NOT NULL,
            workspace_id  text NOT NULL,
            document_id   text NOT NULL,
            position      integer NOT NULL,
            note          text NOT NULL DEFAULT '',
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_leg_document_pkey PRIMARY KEY (leg_id, position),
            CONSTRAINT design_leg_document_one_per_leg UNIQUE (leg_id, document_id),
            CONSTRAINT design_leg_document_position CHECK (position >= 0),
            CONSTRAINT design_leg_document_leg_fk
                FOREIGN KEY (leg_id, workspace_id) REFERENCES design_leg (id, workspace_id),
            CONSTRAINT design_leg_document_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX design_leg_document_by_document "
        "ON design_leg_document (workspace_id, document_id)"
    )
    op.execute(
        "COMMENT ON TABLE design_leg_document IS 'The documents one design leg works on, in "
        "birth order (spec 2026-09-19 §3.2). design_leg.document_id is position 0.'"
    )
    # Backfill: every existing leg that pins a document is a one-document leg.
    op.execute(
        """
        INSERT INTO design_leg_document (leg_id, workspace_id, document_id, position, note)
        SELECT l.id, l.workspace_id, l.document_id, 0, ''
        FROM design_leg l
        JOIN design_document d ON d.id = l.document_id AND d.workspace_id = l.workspace_id
        WHERE l.document_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_leg_document")
```

Confirm `design_document` has a `(id, workspace_id)` unique anchor (migration `7a9881f9717a` made design ids workspace-local; grep `design_document_workspace_anchor`). If the anchor is named differently, the FK still targets the column pair.

- [ ] **Step 4: Write the DAL**

Append to `subsystems/design/clue_design/legs.py`:

```python
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LegDocumentSpec:
    """One document of a leg: its birth position and the item's own words (spec §3.1)."""

    document_id: str
    position: int
    note: str = ""


async def add_leg_documents(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    leg_id: str,
    documents: Sequence[LegDocumentSpec],
) -> None:
    """Record the leg's document set. Schema-refused on a duplicate position or document."""
    for spec in documents:
        await conn.execute(
            text(
                "INSERT INTO design_leg_document (leg_id, workspace_id, document_id, position, note) "
                "VALUES (:leg, :ws, :doc, :pos, :note)"
            ),
            {"leg": leg_id, "ws": workspace_id, "doc": spec.document_id,
             "pos": spec.position, "note": spec.note},
        )


async def list_leg_documents(
    conn: AsyncConnection, *, workspace_id: str, leg_id: str
) -> list[JsonObject]:
    """The leg's documents in position order, each with the document facts the runner, the
    judge and the composer need. Fail-closed on workspace at both rows."""
    rows = (
        await conn.execute(
            text(
                "SELECT ld.document_id, ld.position, ld.note, d.title, d.doc_kind, "
                "d.current_version, d.account_id "
                "FROM design_leg_document ld "
                "JOIN design_document d ON d.id = ld.document_id AND d.workspace_id = ld.workspace_id "
                "WHERE ld.leg_id = :leg AND ld.workspace_id = :ws "
                "ORDER BY ld.position ASC"
            ),
            {"leg": leg_id, "ws": workspace_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]
```

Add `"LegDocumentSpec"`, `"add_leg_documents"`, `"list_leg_documents"` to the module's public names (grep `__all__`; if the module has none, leave it).

- [ ] **Step 5: Run the migration and the test**

Run: `uv run alembic upgrade head && uv run alembic heads` (must print one head), then `uv run pytest tests/design/test_design_leg_documents_dal_db.py tests/design/test_design_leg_dal_db.py -v`
Expected: PASS. Then `make db-smoke` on the throwaway DB: clean.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/*design_leg_documents.py subsystems/design/clue_design/legs.py tests/design/test_design_leg_documents_dal_db.py
git commit -m "feat(design-legs): design_leg_document — one leg, many documents (spec §3.2)"
```

---

### Task 2: A design account for a research account, and the runs of an execution

**Files:**
- Modify: `subsystems/design/clue_design/accounts.py`
- Modify: `subsystems/design/clue_design/runs.py`
- Test: `tests/design/test_personalization_accounts_dal_db.py` (append), `tests/design/test_runs_dal_db.py` (append)

**Interfaces:**
- Produces:
  ```python
  async def ensure_web_account_for_entity(conn, *, workspace_id: str, account_entity_id: str, name: str, domain: str | None) -> str
  # returns design_account.account_id (existing row for the entity, else a new "acc_<hex>" row)
  async def runs_for_execution(conn, *, workspace_id: str, execution_id: UUID) -> list[JsonObject]
  # get_run's DTO shape, created_at ascending
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/design/test_personalization_accounts_dal_db.py` (use its existing seeding helpers for a workspace; read the file head for the helper names):

```python
def test_ensure_web_account_for_entity_reuses_the_entitys_row_and_mints_once() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                ws = await _seed_workspace(conn)  # the file's existing helper
                entity_id = (await conn.execute(text(
                    "INSERT INTO account_entity (canonical_name, primary_domain, status, workspace_id) "
                    "VALUES ('Apollo Clinics', 'apollo.example', 'candidate', :w) RETURNING id"
                ), {"w": ws})).scalar_one()
                first = await design_accounts.ensure_web_account_for_entity(
                    conn, workspace_id=ws, account_entity_id=str(entity_id),
                    name="Apollo Clinics", domain="apollo.example",
                )
                again = await design_accounts.ensure_web_account_for_entity(
                    conn, workspace_id=ws, account_entity_id=str(entity_id),
                    name="Apollo Clinics", domain="apollo.example",
                )
                assert first == again
                row = await design_accounts.require_web_account(conn, workspace_id=ws, account_id=first)
                assert row["account_entity_id"] == str(entity_id)
                assert row["name"] == "Apollo Clinics" and row["domain"] == "apollo.example"
                await conn.rollback()
    run_async(scenario())
```

Append to `tests/design/test_runs_dal_db.py`:

```python
def test_runs_for_execution_lists_the_executions_runs_oldest_first() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                ws = await _seed_workspace(conn)  # the file's existing helper
                execution_id = uuid4()
                await conn.execute(text(
                    "INSERT INTO execution (id, workspace_id, project_id, started_by) "
                    "VALUES (:id, :w, NULL, 'human')"), {"id": execution_id, "w": ws})
                for run_id in ("run_a", "run_b"):
                    await design_runs.create_run(
                        conn, workspace_id=ws, run_id=run_id, document_id=None,
                        payload={}, execution_id=execution_id,
                    )
                rows = await design_runs.runs_for_execution(conn, workspace_id=ws, execution_id=execution_id)
                assert [r["run_id"] for r in rows] == ["run_a", "run_b"]
                await conn.rollback()
    run_async(scenario())
```

Check the `execution` table's NOT NULL columns in `alembic/versions` (grep `CREATE TABLE execution`) and supply whatever it requires (`project_id` may be required — seed a project with `tests._workspace.seed_project` then).

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/design/test_personalization_accounts_dal_db.py tests/design/test_runs_dal_db.py -v -k "for_entity or for_execution"`
Expected: FAIL with `AttributeError` on both new functions.

- [ ] **Step 3: Implement**

In `subsystems/design/clue_design/accounts.py` (after `create_web_account`):

```python
async def ensure_web_account_for_entity(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: str,
    name: str,
    domain: str | None,
) -> str:
    """The design account that projects onto ``account_entity_id`` — found, or born here.

    Spec 2026-09-19 §3.6: a document born for a research account must carry a design-plane
    account (``design_document.account_id`` references ``design_account``). This is the inverse
    direction of :func:`clue_design.joins.resolve_account_entity_id`: the entity is known, the
    design row is derived. Idempotent — one design account per entity per workspace; a second
    call returns the first row's id.
    """
    found = (
        await conn.execute(
            text(
                "SELECT account_id FROM design_account "
                "WHERE workspace_id = :w AND account_entity_id = CAST(:e AS uuid) "
                "ORDER BY created_at ASC, account_id ASC LIMIT 1"
            ),
            {"w": workspace_id, "e": account_entity_id},
        )
    ).first()
    if found is not None:
        return str(found.account_id)
    account_id = "acc_" + uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO design_account "
            "(account_id, workspace_id, account_entity_id, name, domain, logo_asset_id, data_json, notes) "
            "VALUES (:a, :w, CAST(:e AS uuid), :name, :domain, NULL, '{}'::jsonb, NULL)"
        ),
        {"a": account_id, "w": workspace_id, "e": account_entity_id,
         "name": name, "domain": normalize_domain(domain)},
    )
    return account_id
```

Add `from uuid import uuid4` at the top of `accounts.py`. In `subsystems/design/clue_design/runs.py` (after `list_running_runs`):

```python
async def runs_for_execution(
    conn: AsyncConnection, *, workspace_id: str, execution_id: UUID
) -> list[JsonObject]:
    """Every run dispatched under one platform execution, oldest first (spec §3.3/§3.9: the
    batch of one leg turn is the runs stamped with that turn's execution id)."""
    rows = await conn.execute(
        text(
            "SELECT * FROM design_agent_run WHERE workspace_id = :w AND execution_id = :e "
            "ORDER BY created_at ASC, run_id ASC"
        ),
        {"w": workspace_id, "e": execution_id},
    )
    return [_agent_run_from_row(row) for row in rows]
```

- [ ] **Step 4: Run the tests**

Run: the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/design/clue_design/accounts.py subsystems/design/clue_design/runs.py tests/design/test_personalization_accounts_dal_db.py tests/design/test_runs_dal_db.py
git commit -m "feat(design-legs): design account for a research entity; runs of an execution"
```

---

### Task 3: `open_design_leg@5` — a list of artifacts, N births, the account stamp

**Files:**
- Modify: `platform/api/clue_api/design_leg_tools.py`
- Test: `tests/api/test_multi_artifact_leg_birth_db.py` (new), `tests/api/test_genad_leg_document_birth_db.py`, `tests/api/test_genweb_leg_document_birth_db.py`, `tests/api/test_p34_design_leg_tool_db.py` (update to @5 input shape)

**Interfaces:**
- Consumes: `LegDocumentSpec`, `add_leg_documents` (Task 1); `ensure_web_account_for_entity` (Task 2).
- Produces:
  ```python
  class DesignArtifactSpec(BaseModel):  # extra="forbid"
      title: str  (1..200)
      note: str = ""  (max 2000)
      account_id: str | None = None   # a research account_entity uuid, on this project
  class OpenDesignLegInput(ToolInput):
      ... artifacts: tuple[DesignArtifactSpec, ...] = Field(default=(), max_length=200)   # replaces `title`
  class OpenDesignLegOutput(ToolOutput):
      ... document_ids: tuple[str, ...] = ()   # position order; document_id stays = document_ids[0]
  OpenDesignLegTool.version = "5"
  def derive_leg_document_id(*, leg_id: str, position: int = 0) -> str
  DESIGN_DELEGATION_BUNDLE_MAX_BYTES stays the base; def delegation_bundle_cap(artifact_count: int) -> int
  bundle payload gains "artifacts": [{"position", "title", "note", "account_id", "document_id"}]
  ```

- [ ] **Step 1: Write the failing tests**

Model the new file on `tests/api/test_genad_leg_document_birth_db.py` (reuse its `engine_ad_scene`, `_RecordingSceneMinter`, the seeding helper and the `invoke_tool` call shape — read lines 60–260 of that file first).

```python
# tests/api/test_multi_artifact_leg_birth_db.py
"""open_design_leg@5 (spec §3.1/§3.2/§3.6): N artifacts → N born documents on ONE leg, in one
transaction; ids derived from (leg, position) with position 0 byte-identical to @4; the account
stamped on a document born for a research account; the bundle records the item list."""
from __future__ import annotations
# imports: copy the genad file's import block, plus:
from clue_api.design_leg_tools import DesignArtifactSpec, delegation_bundle_cap, derive_leg_document_id
from clue_design import legs as design_legs


def test_three_artifacts_birth_three_documents_on_one_leg(tmp_path, migrated_db) -> None:  # noqa: F811
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed(conn, storage_root=tmp_path, label="three")   # the genad seeding helper
            tool = OpenDesignLegTool(conn_factory=conn_session_factory(conn), storage=FsStorage(tmp_path),
                                     scene_document_minter=_RecordingSceneMinter())
            result = await invoke_tool(tool, {
                "source_turn_ref": seeds["turn_ref"], "brief": "1:1 LinkedIn ads", "doc_kind": "scene",
                "artifacts": [
                    {"title": "Apollo ad", "note": "for Apollo Clinics (apollo.example)"},
                    {"title": "Mercy ad", "note": "for Mercy Health"},
                    {"title": "Premier ad", "note": "for Premier Gastro"},
                ],
            }, ctx=seeds["ctx"])
            refs = result.references
            leg_id = refs["leg_id"]
            expected = [derive_leg_document_id(leg_id=leg_id, position=i) for i in range(3)]
            assert list(refs["document_ids"]) == expected
            assert refs["document_id"] == expected[0]            # position 0 is the leg's pin
            assert refs["document_created"] is True
            rows = await design_legs.list_leg_documents(conn, workspace_id=seeds["workspace_id"], leg_id=leg_id)
            assert [(r["position"], r["title"], r["note"]) for r in rows] == [
                (0, "Apollo ad", "for Apollo Clinics (apollo.example)"),
                (1, "Mercy ad", "for Mercy Health"),
                (2, "Premier ad", "for Premier Gastro"),
            ]
            leg = await design_legs.get_leg(conn, workspace_id=seeds["workspace_id"], leg_id=leg_id)
            assert leg["document_id"] == expected[0] and leg["document_version_guard"] == 0
            bundle = json.loads(await _bundle_bytes(conn, seeds, refs["bundle_artifact_key"]))  # read the artifact via storage
            assert [a["position"] for a in bundle["artifacts"]] == [0, 1, 2]
            assert bundle["artifacts"][1] == {"position": 1, "title": "Mercy ad", "note": "for Mercy Health",
                                              "account_id": None, "document_id": expected[1]}
    run_async(scenario())


def test_position_zero_keeps_the_at4_document_id() -> None:
    assert derive_leg_document_id(leg_id="leg-x") == derive_leg_document_id(leg_id="leg-x", position=0)
    # The @4 derivation, restated: uuid5 over the bare leg id.
    from uuid import NAMESPACE_URL, uuid5
    ns = uuid5(NAMESPACE_URL, "clue-design-leg-document")
    assert derive_leg_document_id(leg_id="leg-x") == f"doc_{uuid5(ns, 'leg-x').hex}"
    assert derive_leg_document_id(leg_id="leg-x", position=1) == f"doc_{uuid5(ns, 'leg-x:1').hex}"


def test_a_replayed_multi_delegation_converges_on_the_same_rows(...):
    # invoke twice with the same source_turn_ref; second result: created False, document_created False,
    # identical document_ids; exactly 3 design_leg_document rows and 3 design_document rows.


def test_a_document_born_for_a_research_account_carries_the_design_account(...):
    # seed an account_entity in the workspace AND a project_account membership for seeds' project
    # (clue_research.membership.ensure_project_account, added_via a value from membership.ADDED_VIA);
    # artifacts=[{"title": "Apollo ad", "account_id": str(entity_id)}];
    # assert get_document(...)["account_id"] is not None and design_account.account_entity_id == entity_id.


def test_an_account_off_the_project_is_refused(...):
    # entity exists in the workspace but has no project_account row → PreconditionFailed with
    # reason_code "design_leg_account_not_on_project".


def test_artifacts_and_document_id_are_exclusive_and_a_single_item_is_the_old_shape(...):
    # {"document_id": existing, "artifacts": [...]} → "design_leg_artifacts_with_document";
    # a one-item artifacts list births exactly what @4's title did (same id, same title).


def test_the_bundle_cap_grows_with_the_item_count() -> None:
    assert delegation_bundle_cap(1) == 24_000
    assert delegation_bundle_cap(20) == 24_000 + 1_500 * 19
```

Fill the elided test bodies fully using the genad file's helpers; every assertion above is the contract.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_multi_artifact_leg_birth_db.py -v`
Expected: FAIL with `ImportError` on `DesignArtifactSpec`.

- [ ] **Step 3: Implement the tool changes**

In `platform/api/clue_api/design_leg_tools.py`:

1. Module docstring: add an `@5` paragraph (spec §3.1: a list of artifacts; `title` retired into the items; N births + child rows in one transaction; the account stamp; the cap formula).
2. Constants and helpers:

```python
DESIGN_DELEGATION_BUNDLE_MAX_BYTES = 24_000            # unchanged: the one-item cap
DESIGN_DELEGATION_BUNDLE_PER_ITEM_BYTES = 1_500
DESIGN_ARTIFACT_NOTE_MAX_CHARS = 2_000


def delegation_bundle_cap(artifact_count: int) -> int:
    """Spec §3.1: the shared half of L3 is kept for one artifact; each further item adds room."""
    return DESIGN_DELEGATION_BUNDLE_MAX_BYTES + DESIGN_DELEGATION_BUNDLE_PER_ITEM_BYTES * max(0, artifact_count - 1)


def derive_leg_document_id(*, leg_id: str, position: int = 0) -> str:
    """One (leg, position) ⇒ one born document. Position 0 is the @4 derivation byte-for-byte."""
    seed = leg_id if position == 0 else f"{leg_id}:{position}"
    return f"doc_{uuid5(_LEG_DOCUMENT_NAMESPACE, seed).hex}"
```

`_require_bundle_within_cap(bundle_bytes, *, artifact_count)` uses `delegation_bundle_cap`.

3. Input model:

```python
class DesignArtifactSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    note: str = Field(default="", max_length=DESIGN_ARTIFACT_NOTE_MAX_CHARS)
    #: The research account (account_entity id) this artifact is for — for the durable link and
    #: the gallery only (spec §3.6); the design agent still reads the account by name and tools.
    account_id: str | None = Field(default=None, min_length=1, max_length=64)
```

In `OpenDesignLegInput` delete `title`; add `artifacts: tuple[DesignArtifactSpec, ...] = Field(default=(), max_length=200)` with a docstring comment: REQUIRED (≥1) on a document-less open; refused beside `document_id` or `reopen_leg_id`. In `OpenDesignLegOutput` add `document_ids: tuple[str, ...] = ()`.

4. `_ResolvedDelegation`: replace `birth_title: str | None` with `births: tuple[_Birth, ...] = ()` where

```python
@dataclass(frozen=True, slots=True)
class _Birth:
    position: int
    document_id: str
    title: str
    note: str
    account_entity_id: str | None
    account_name: str | None
    account_domain: str | None
```

`birth_doc_kind` stays.

5. `_resolve` (the document-less branch): refuse `artifacts` beside `document_id` (`design_leg_artifacts_with_document`) and beside `reopen_leg_id` (`design_leg_artifacts_with_reopen`); require ≥1 item on a document-less open (`design_leg_artifacts_required`, message naming the @4→@5 change); dedupe titles by appending ` (2)`, ` (3)` on collision; for each item with `account_id`: load the entity through `clue_research.identity.get_account(conn, EntityId(UUID(...)))` — refuse `design_leg_account_not_found` when None / other workspace / `merged_into is not None`; refuse `design_leg_account_not_on_project` when `turn.project_id not in projects_for_accounts(...)` (`clue_research.membership.projects_for_accounts`); build `_Birth(position=i, document_id=derive_leg_document_id(leg_id=leg_id, position=i), title=…, note=item.note, account_entity_id=…, account_name=account.canonical_name, account_domain=account.primary_domain)`; `document_id = births[0].document_id`, `document_version_guard = 0`. The pinned-existing-document path builds `births=()` and the child row is written for that one document at position 0 with note `""` (so every leg has its set).

6. `_bundle_payload(...)` gains `artifacts: Sequence[_Birth]` and emits `"artifacts": [{"position", "title", "note", "account_id": b.account_entity_id, "document_id"}]` (an existing-document pin emits one entry with the document's own title). Cap check uses the count.

7. `invoke` fresh path: loop births in position order; for each, `_birth_scene_document` / `_birth_web_document` (both gain `account_id: str | None` and pass it to `create_document(..., account_id=account_id)`) where `account_id` is `await design_accounts.ensure_web_account_for_entity(conn, workspace_id=…, account_entity_id=…, name=…, domain=…)` when the birth names an entity; the brand pin is read back from the FIRST birth (all born under one kit); after `design_legs.open_leg(...)`, `await design_legs.add_leg_documents(conn, workspace_id=…, leg_id=…, documents=[LegDocumentSpec(b.document_id, b.position, b.note) for b in births])` — or, on the existing-document pin path, one `LegDocumentSpec(document_id, 0, "")`. Result `references` gain `"document_ids": [...]` (position order; on replay/reopen read from `list_leg_documents`).

8. `model_description`: reword the NEW-website / NEW-ad sentences to: "pass doc_kind and `artifacts`, one item per artifact the user wants — a title the user would recognise, a note with that item's own words (its account, its emphasis), and account_id when the item is for a tagged research account; one item for one ad, twenty for twenty accounts, five for five variants with a distinct emphasis each; the shared ask stays in brief."

- [ ] **Step 4: Update the @4 tests to the @5 shape**

In `tests/api/test_genad_leg_document_birth_db.py`, `tests/api/test_genweb_leg_document_birth_db.py`, `tests/api/test_p34_design_leg_tool_db.py`, `tests/api/test_p34_design_leg_engine_db.py` and any other test invoking `open_design_leg` with `"title"` (grep `"title":` under `tests/api` next to `open_design_leg`), replace `"title": X` with `"artifacts": [{"title": X}]`; where no title was passed and `doc_kind` was, add `"artifacts": [{"title": "<brief first words>"}]` and keep the existing assertion on the born title by asserting on that title. Any test asserting the fallback "brief's first ~8 words" title now asserts the item title (the fallback is gone: an item always has a title).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/api/test_multi_artifact_leg_birth_db.py tests/api/test_genad_leg_document_birth_db.py tests/api/test_genweb_leg_document_birth_db.py tests/api/test_p34_design_leg_tool_db.py tests/api/test_p35_finish_design_leg_db.py -v`
Expected: PASS. Also `uv run ruff check platform/api/clue_api/design_leg_tools.py && uv run mypy platform/api/clue_api/design_leg_tools.py`.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/design_leg_tools.py tests/api/test_multi_artifact_leg_birth_db.py tests/api/test_genad_leg_document_birth_db.py tests/api/test_genweb_leg_document_birth_db.py tests/api/test_p34_design_leg_tool_db.py tests/api/test_p34_design_leg_engine_db.py
git commit -m "feat(design-legs): open_design_leg@5 — a list of artifacts, N births, the account stamp (spec §3.1/§3.6)"
```

---

### Task 4: Head-of-ABM v58 — prompt v11, recipe 29, the pins, the manual

**Files:**
- Create: `platform/agents/catalog/profiles/head-of-abm/v58/profile.yaml`, `platform/agents/catalog/prompts/head-of-abm/v11/SYSTEM.md`, `platform/execution/recipes/recipe0-stage0-v29.json`
- Modify: `platform/api/clue_api/agent_registry_wiring.py:172-181` (C6 v58 comment + pin), `platform/api/clue_api/recipe_wiring.py` (v29 in the seeded list, v19's note), `platform/api/clue_api/recipe_contracts.py:65` (`open_design_leg@5`), `platform/api/clue_api/conversation_turns.py:180` (`CONVERSATION_RECIPE_VERSION = 29` + a revision-29 comment), `platform/api/clue_api/chat/composer_context.py:61` (`head-of-abm@v58`), `platform/agents/clue_agents/manual/build.py:74-78` (`MANUAL_VERSION = "v5"`, `PROFILE_VERSION = "v58"`)
- Test: `tests/api/test_agent_registry_wiring.py` (digests), `tests/agents/test_catalog.py:318` (add `profile:head-of-abm@v58`), `tests/api/test_comprehensive_research_contract.py:469-470`, `tests/api/test_client_knowledge_privacy_s4e.py:161`, `tests/agents/test_manual_drift.py`, `tests/api/test_recipe_*` (grep `recipe0-stage0-v28`)

**Interfaces:**
- Consumes: `open_design_leg@5` (Task 3).
- Produces: `head-of-abm@v58` pinning `prompt:head-of-abm@v11` and `open_design_leg@5`; recipe `recipe0-stage0@29` admitting `open_design_leg@5` (and NOT `@4` — one version per key per slot); manual chapters re-minted at `manual-*@v5`.

- [ ] **Step 1: Present the prompt text to the founder (gate)**

Post in chat, verbatim, the replacement for the two design paragraphs of `prompts/head-of-abm/v10/SYSTEM.md` (copy v10 to v11 and edit only these):

```
Design work is a different kind of delegation: it is a durable handoff, not a bounded sub-task.
When the user wants a website, landing page, microsite, ad, banner, flyer, poster or any designed
page built or changed, open a design leg. A new artifact needs no existing document: the leg
creates one empty document per artifact you list. One message can ask for MANY artifacts, and you
decide how many by reading it: "a 1:1 ad for each" over twenty tagged accounts is twenty items,
one per account; "five variants" is five items. Give every item a title the user would recognise
and a note in that item's own words — the account it is for (name and domain, with account_id
from the tag when there is one), or the emphasis that makes this variant different from its
siblings (a different angle, proof point or visual direction), so the design agent does not make
five copies of one ad. Put the user's shared ask in the brief, verbatim where possible: the design
agent reads the brief and its item's note, not this conversation. Never choose or restate
dimensions, formats, units or page sizes; Design owns all of that. While the leg is open, every
message on this thread goes to Design instead of you, and you resume when it closes with the
summary it hands back. Opening a leg starts nothing: the user's next message begins generation,
and every artifact generates at the same time, for minutes. Say the design session is open, name
what will be made, and end your turn.
```

Wait for the founder's yes or edits before Step 2.

- [ ] **Step 2: Create prompt v11, profile v58, recipe v29**

`prompts/head-of-abm/v11/SYSTEM.md`: copy v10, bump the front matter `version: v11`, replace the two design paragraphs with the approved text. Profile: copy `profiles/head-of-abm/v57/profile.yaml` to `v58/profile.yaml`; set `version: v58`; replace the leading comment block with a v58 note (spec 2026-09-19: `open_design_leg@5` and prompt v11; every other address unchanged; manual re-mints at v5 because the generated tools chapter renders the tool); set `prompt.version: v11` and its `sha256` (the sha256 of the SYSTEM.md file bytes: `shasum -a 256 …/v11/SYSTEM.md`); set the `open_design_leg` entry to `version: "5"` with digests read from the registry:

```bash
uv run python - <<'EOF'
from clue_api.toolbelt_wiring import build_toolbelt
d = build_toolbelt(storage=None, gateway=None).descriptor("open_design_leg", "5")
print(d.input_schema_sha256, d.output_schema_sha256)
EOF
```

Recipe: copy `platform/execution/recipes/recipe0-stage0-v28.json` to `-v29.json`, set `"version": 29`, and replace every `open_design_leg@4` / `{"kind": "tool", "key": "open_design_leg", "version": "4"}` with `@5` / `"5"` (four sites: lines 45, 109, 164, 211 of v28). Add `"recipe0-stage0-v29.json"` to `recipe_wiring.py`'s seeded list with the standard note ("the slot pins EXACT addresses…"); v28 stays seeded (replay input). In `recipe_contracts.py:65` change the audited address to `open_design_leg@5` with a one-line note. `conversation_turns.py`: `CONVERSATION_RECIPE_VERSION = 29` plus a "Revision 29 (multi-artifact legs)" comment in the block at lines 118–130. `agent_registry_wiring.py`: `AgentRole.HEAD_OF_ABM: "v58"` with a v58 comment above it in the same style as v57's. `composer_context.py:61`: `"head-of-abm@v58"` and the comment above it. `manual/build.py`: `MANUAL_VERSION = "v5"`, `PROFILE_VERSION = "v58"`.

- [ ] **Step 3: Re-mint the manual and re-measure the digests**

Run `make manual` (regenerates the four generated chapters at `manual-*@v5`; the eleven hand-written chapters are copied to v5 by the builder — confirm with `git status`; if the builder does not copy hand-written chapters, copy each `skills/manual-<name>/v4/SKILL.md` to `v5/` unchanged and update its front matter version, as v57's commit `d80301978` did). Pin the fifteen `manual-*` skills at `v5` in `v58/profile.yaml` with their sha256s. Run `uv run pytest tests/api/test_agent_registry_wiring.py -x`; the manifest-digest test prints the measured digest on failure — paste it into `expected_manifests` with a v58 comment (the file's established practice). Update `tests/agents/test_catalog.py:318` (add `"profile:head-of-abm@v58"` with a comment), `tests/api/test_comprehensive_research_contract.py:469-470` and `tests/api/test_client_knowledge_privacy_s4e.py:161` to v58.

- [ ] **Step 4: Run the catalog, registry, recipe and manual gates**

Run: `uv run pytest tests/agents tests/api/test_agent_registry_wiring.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_recipe_wiring.py tests/api/test_chat_composer_context.py -v` and `make manual-check`.
Expected: PASS; `manual-check` exits 0.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/catalog platform/execution/recipes/recipe0-stage0-v29.json platform/api/clue_api/agent_registry_wiring.py platform/api/clue_api/recipe_wiring.py platform/api/clue_api/recipe_contracts.py platform/api/clue_api/conversation_turns.py platform/api/clue_api/chat/composer_context.py platform/agents/clue_agents/manual/build.py tests/agents tests/api/test_agent_registry_wiring.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py
git commit -m "feat(head-of-abm): v58 — open_design_leg@5, prompt v11 (many artifacts per ask), recipe 29, manual v5"
```

---

### Task 5: The item's note in the design turn's brief

**Files:**
- Modify: `subsystems/design/clue_design/leg_context.py`
- Test: `tests/design/test_p37_design_entry_consumption.py` (append)

**Interfaces:**
- Produces: `render_leg_turn_prompt(*, bundle, history, prompt, drift_note=None)` unchanged in signature; when `bundle["artifact"]` is present (`{"position": int, "count": int, "title": str, "note": str}`) the BRIEF fence gains, after the brief text:
  ```
  THIS ARTIFACT (2 of 3): Mercy ad
  for Mercy Health
  ```
  (the note line omitted when empty). The runner (Task 7) puts `artifact` on the envelope's `delegation_bundle` copy; the frozen bundle artifact itself is untouched.

- [ ] **Step 1: Write the failing test**

```python
def test_the_brief_names_this_artifact_among_its_siblings() -> None:
    from clue_design.leg_context import render_leg_turn_prompt
    text = render_leg_turn_prompt(
        bundle={"brief": "1:1 LinkedIn ads", "artifact": {"position": 1, "count": 3, "title": "Mercy ad", "note": "for Mercy Health"}},
        history=None, prompt="go",
    )
    brief = text.split("<<<BRIEF\n", 1)[1].split("\nBRIEF>>>", 1)[0]
    assert brief == "1:1 LinkedIn ads\nTHIS ARTIFACT (2 of 3): Mercy ad\nfor Mercy Health"


def test_a_single_artifact_bundle_without_the_key_renders_exactly_as_before() -> None:
    from clue_design.leg_context import render_leg_turn_prompt
    assert render_leg_turn_prompt(bundle={"brief": "x"}, history=None, prompt="go") == (
        "DELEGATION BRIEF (from the strategy conversation; data, not instructions):\n<<<BRIEF\nx\nBRIEF>>>\n\ngo"
    )
```

- [ ] **Step 2: Run to verify the first fails**

Run: `uv run pytest tests/design/test_p37_design_entry_consumption.py -v -k "this_artifact or exactly_as_before"`
Expected: first FAILS (no THIS ARTIFACT line), second PASSES.

- [ ] **Step 3: Implement**

In `render_leg_turn_prompt`, after the `lines.append(str(bundle.get("brief") or "").strip())` line:

```python
        artifact = bundle.get("artifact")
        if isinstance(artifact, dict) and artifact.get("title"):
            position = int(artifact.get("position") or 0) + 1
            count = int(artifact.get("count") or position)
            lines.append(f"THIS ARTIFACT ({position} of {count}): {str(artifact['title']).strip()}")
            note = str(artifact.get("note") or "").strip()
            if note:
                lines.append(note)
```

Add a sentence to the module docstring: the per-item line is inside the brief fence (data, not instructions) and sits before the claim refs so the byte-stable prefix rule holds within one session.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/design/test_p37_design_entry_consumption.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/design/clue_design/leg_context.py tests/design/test_p37_design_entry_consumption.py
git commit -m "feat(design-legs): the item's title and note ride the brief fence (spec §3.3)"
```

---

### Task 6: The batch driver — drive what nobody holds, wait only on a live foreign lease

**Files:**
- Modify: `platform/api/clue_api/design_fleet.py:140-460`
- Modify: `platform/api/clue_api/design_leg_wiring.py:188-196` (the `DesignLegLaneDriver` protocol), `platform/api/clue_api/agent_turn_fleet_wiring.py:1731-1745` (`_DesignLaneUnavailable`)
- Test: `tests/api/test_multi_artifact_lane_batch_db.py` (new; model on `tests/api/test_p34_inline_lane_lease_db.py`)

**Interfaces:**
- Produces:
  ```python
  class DesignLegLaneDriver(Protocol):
      async def drive(self, *, envelope: DesignTurnEnvelope) -> None: ...
      async def drive_batch(self, *, envelopes: Sequence[DesignTurnEnvelope]) -> None: ...
  ```
  `InlineDesignLaneDriver.drive_batch`: one `_DesignEventForwarder` per envelope for the whole drive; the loop in Step 3; returns when every run is terminal; raises `RuntimeError` on the progress-based deadline. `frames_forwarded` sums the forwarders.

- [ ] **Step 1: Write the failing tests**

Reuse `_seed_committed_run`, `_cleanup_committed_run`, `_SlowCompletingHandler` from `test_p34_inline_lane_lease_db.py` (import them).

```python
# tests/api/test_multi_artifact_lane_batch_db.py
"""Spec §3.3 step 3: drive_batch drives every sibling nobody holds, waits only while a live
foreign lease proves someone else is driving one, and returns when all are terminal."""
from __future__ import annotations
import asyncio
from datetime import timedelta
from clue_api.design_fleet import InlineDesignLaneDriver
from clue_db import db_lifespan, transaction
from clue_design import runs as design_runs
from clue_fleet import WorkId, acquire_work_lease, release_work_lease
from tests.api.test_p34_inline_lane_lease_db import _SlowCompletingHandler, _cleanup_committed_run, _seed_committed_run
from tests.db.conftest import run_async


def test_a_batch_of_three_is_driven_to_terminal_by_one_slot() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            envelopes = [await _seed_committed_run(f"batch{i}") for i in range(3)]
            try:
                handler = _SlowCompletingHandler(run_seconds=0.2)
                driver = InlineDesignLaneDriver(handler=handler, lease_ttl=timedelta(seconds=2), join_poll_interval_s=0.1)
                await asyncio.wait_for(driver.drive_batch(envelopes=envelopes), timeout=30.0)
                assert len(handler.contexts) == 3
                async with transaction() as conn:
                    for env in envelopes:
                        run = await design_runs.get_run(conn, workspace_id=env.workspace_id, run_id=env.run_id)
                        assert run is not None and run["status"] == "succeeded"
            finally:
                for env in envelopes:
                    await _cleanup_committed_run(env)
    run_async(scenario())


def test_a_sibling_held_by_a_live_foreign_lease_is_skipped_then_joined() -> None:
    """Run B is held by 'another slot' (a foreign live lease that completes it after a while);
    the driver must drive A itself, never call the handler for B, and return once B is terminal."""
    async def scenario() -> None:
        async with db_lifespan():
            a, b = await _seed_committed_run("held_a"), await _seed_committed_run("held_b")
            try:
                async with transaction() as conn:
                    lease = await acquire_work_lease(conn, work_id=WorkId(b.work_id), worker_id="other-slot", ttl=timedelta(seconds=30))
                assert lease is not None

                async def other_slot_finishes_b() -> None:
                    await asyncio.sleep(1.0)
                    async with transaction() as conn:
                        await design_runs.set_run_result(conn, workspace_id=b.workspace_id, run_id=b.run_id,
                            status="succeeded", result={"schema_version": 1, "status": "accepted"},
                            expected_generation=int(lease.generation))
                        await release_work_lease(conn, work_id=WorkId(b.work_id), worker_id="other-slot", generation=lease.generation)

                handler = _SlowCompletingHandler(run_seconds=0.2)
                driver = InlineDesignLaneDriver(handler=handler, lease_ttl=timedelta(seconds=2), join_poll_interval_s=0.1)
                other = asyncio.create_task(other_slot_finishes_b())
                await asyncio.wait_for(driver.drive_batch(envelopes=[a, b]), timeout=30.0)
                await other
                driven = {str(ctx.payload["run_id"]) for ctx in handler.contexts}
                assert driven == {a.run_id}
            finally:
                await _cleanup_committed_run(a); await _cleanup_committed_run(b)
    run_async(scenario())


def test_a_batch_nobody_drives_fails_within_the_progress_window() -> None:
    """A foreign lease that never lapses and never produces a terminal row: the window closes
    join_timeout_s after the last progress, and the driver raises rather than waits forever."""
    async def scenario() -> None:
        async with db_lifespan():
            a = await _seed_committed_run("stuck")
            try:
                async with transaction() as conn:
                    await acquire_work_lease(conn, work_id=WorkId(a.work_id), worker_id="zombie", ttl=timedelta(seconds=120))
                driver = InlineDesignLaneDriver(handler=_SlowCompletingHandler(run_seconds=0.1),
                                                lease_ttl=timedelta(seconds=2), join_poll_interval_s=0.1, join_timeout_s=1.0)
                with pytest.raises(RuntimeError):
                    await asyncio.wait_for(driver.drive_batch(envelopes=[a]), timeout=30.0)
            finally:
                await _cleanup_committed_run(a)
    run_async(scenario())
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_multi_artifact_lane_batch_db.py -v` (stack DOWN). Expected: FAIL with `AttributeError: drive_batch`.

- [ ] **Step 3: Implement `drive_batch`**

In `design_fleet.py`, inside `InlineDesignLaneDriver`:

```python
    async def drive_batch(self, *, envelopes: Sequence[Any]) -> None:
        """Spec §3.3 step 3 — the single-run rule applied across siblings.

        For every non-terminal run: acquire its lease and drive it inline if nobody holds it;
        skip it while a LIVE foreign lease proves another slot is driving it; when every
        remaining run is held elsewhere, wait and poll. The window is progress-based: the
        single-run ``join_timeout_s`` measured from the last time any run of the batch reached
        terminal or any of our own drives finished — a busy fleet never fails a batch for being
        large; a batch nobody drives fails as fast as one run does.
        """
        if len(envelopes) == 1:
            await self.drive(envelope=envelopes[0])
            return
        forwarders = [
            _DesignEventForwarder(envelope=e, conn_factory=self._conn_factory,
                                  poll_interval_s=self._checkpoint_poll_interval_s)
            for e in envelopes
        ]
        self._forwarders = forwarders
        tails = [asyncio.create_task(f.run()) for f in forwarders]
        try:
            await self._drive_batch_to_terminal(envelopes=list(envelopes))
        finally:
            for tail in tails:
                tail.cancel()
            for tail in tails:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await tail
            for f in forwarders:
                await f.drain()

    async def _drive_batch_to_terminal(self, *, envelopes: list[Any]) -> None:
        loop = asyncio.get_running_loop()
        last_progress = loop.time()
        pending = list(envelopes)
        while pending:
            progressed = False
            still: list[Any] = []
            for envelope in pending:
                if await self._run_is_terminal(envelope):
                    progressed = True
                    continue
                work_id = WorkId(envelope.work_id)
                async with self._conn_factory() as conn:
                    lease = await acquire_work_lease(conn, work_id=work_id,
                                                     worker_id=_DESIGN_LEG_LANE_WORKER_ID, ttl=self._lease_ttl)
                if lease is not None:
                    await self._drive_claimed(envelope=envelope, work_id=work_id, lease=lease)
                    progressed = True
                    if not await self._run_is_terminal(envelope):
                        still.append(envelope)      # fenced mid-drive: re-check next round
                    continue
                async with self._conn_factory() as conn:
                    foreign = await get_work_lease(conn, work_id)
                if foreign is None or not foreign.live:
                    still.append(envelope)          # free but the acquire raced: retry next round
                    progressed = True
                    continue
                still.append(envelope)              # a live foreign holder: skip, wait
            pending = still
            if not pending:
                return
            now = loop.time()
            if progressed:
                last_progress = now
            elif now - last_progress >= self._join_timeout_s:
                raise RuntimeError(
                    "the design-leg batch made no progress within the lane's join window; "
                    "the reaper (or an operator requeue) owns what is left"
                )
            await asyncio.sleep(self._join_poll_interval_s)
```

Keep `self._forwarder` for `drive` and make `frames_forwarded` return `sum(f.forwarded for f in self._forwarders)` when a batch ran (initialise `self._forwarders: list[_DesignEventForwarder] = []` in `__init__`; `drive` sets it to `[forwarder]`). `_drive_claimed`'s `CancelledError` branch already cancels its own run; the batch's cancellation is Task 7's (the runner cancels every run before cancelling the drive).

Update the protocol in `design_leg_wiring.py:188` (add `drive_batch`) and `_DesignLaneUnavailable` in `agent_turn_fleet_wiring.py` (add `drive_batch` raising the same message).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api/test_multi_artifact_lane_batch_db.py tests/api/test_p34_inline_lane_lease_db.py tests/design/test_design_checkpoint_forwarding.py -v` (stack DOWN). Expected: PASS. `uv run mypy platform/api/clue_api/design_fleet.py platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/agent_turn_fleet_wiring.py`.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/design_fleet.py platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/agent_turn_fleet_wiring.py tests/api/test_multi_artifact_lane_batch_db.py
git commit -m "feat(design-legs): drive_batch — drive what nobody holds, wait only on a live foreign lease (spec §3.3)"
```

---

### Task 7: The runner fans out, joins, summarises per document, and stops the batch

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (`design_leg_run_id`, `run_leg_turn`, `_dispatch` → `_dispatch_batch`, `_envelope`, `_assistant_summary` callers, `request_stop_for_turn`, `await_stopped_turn`)
- Test: `tests/api/test_multi_artifact_leg_engine_db.py` (new; model on `tests/api/test_p34_design_leg_engine_db.py` — import its `_seed_leg_conversation`, `_submission`, `_card_payload`, `registry` fixture, `_FakeLane`)

**Interfaces:**
- Consumes: `list_leg_documents`, `LegDocumentSpec` (Task 1); `runs_for_execution` (Task 2); `drive_batch` (Task 6); `render_leg_turn_prompt` `artifact` key (Task 5).
- Produces:
  ```python
  def design_leg_run_id(turn_id: UUID, position: int = 0) -> str     # position 0 == today's id
  class DesignLegTurnRunner:
      async def run_leg_turn(..., ) -> DesignLegTurnResult             # unchanged signature
      async def _dispatch_batch(self, *, documents: Sequence[Mapping[str, Any]], ...) -> list[tuple[Mapping, dict]]
      async def _finalize_awaiting_input(self, *, submission, execution_id, assistant_message, domain_refs, stream) -> DesignLegTurnResult
  def batch_summary(items: Sequence[tuple[Mapping[str, Any], dict[str, Any]]]) -> str   # one line per document
  ```
  Runs of a multi-document batch are ALSO enqueued as `design_job` fleet tasks (`clue_fleet.queue.enqueue_task`, `kind=FleetTaskKind.DESIGN_JOB`, `project_run_id=ProjectRunId(work_id)`, `dedup_key=str(work_id)`, `payload=envelope.model_dump(mode="json")`, `reopen_terminal=False`) in the same transaction as their run rows; a one-document leg is dispatched exactly as today (no enqueue, `lane.drive`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_multi_artifact_leg_engine_db.py
"""Spec §3.3: a leg with three documents dispatches three runs + three design_job tasks in one
transaction, drives them through drive_batch, records receipts for all, hands back ONCE with a
per-document summary; a partial failure still hands back; a retry re-joins; Stop cancels all."""
# imports as in test_p34_design_leg_engine_db.py, plus:
from clue_api.design_leg_wiring import design_leg_run_id, design_leg_execution_id, batch_summary
from clue_design import legs as design_legs
from clue_design.legs import LegDocumentSpec


class _FakeBatchLane:
    """drive_batch completes every run; `status_for(run_id)` lets one test fail one of them."""
    def __init__(self, *, conn_factory, status_for=lambda run_id: "succeeded"):
        self._conn_factory, self._status_for = conn_factory, status_for
        self.batches: list[list[Any]] = []
    async def drive(self, *, envelope):        # a one-document leg still takes this path
        await self.drive_batch(envelopes=[envelope])
    async def drive_batch(self, *, envelopes):
        self.batches.append(list(envelopes))
        async with self._conn_factory() as conn:
            for env in envelopes:
                status = self._status_for(env.run_id)
                await design_runs.set_run_result(conn, workspace_id=env.workspace_id, run_id=env.run_id, status=status,
                    result={"schema_version": 1, "status": "proposed" if status == "succeeded" else "failed",
                            "acceptance_scope": "design", "current_version": 3} if status == "succeeded"
                           else {"schema_version": 1, "status": "failed", "error": {"code": "agent_runtime.failed", "message": "boom"}})


async def _seed_three_document_leg(conn, *, storage_root, label):
    seeds = await _seed_leg_conversation(conn, storage_root=storage_root, label=label)  # opens a leg with ONE document
    # add two more scene documents at positions 1 and 2 (create_document with engine_ad_scene from the genad tests)
    ...
    return seeds  # with seeds["document_ids"] = [d0, d1, d2]


def test_three_documents_dispatch_three_runs_and_hand_back_once(tmp_path, registry, migrated_db):  # noqa: F811
    async def scenario():
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="three")
            lane = _FakeBatchLane(conn_factory=seeds["conn_factory"])
            submission = await _submission(conn, seeds, text="make them")
            result = await _run_turn(conn, seeds, registry, lane, submission)
            turn_id = submission.turn_id
            expected_runs = [design_leg_run_id(turn_id, i) for i in range(3)]
            assert [e.run_id for e in lane.batches[0]] == expected_runs
            assert design_leg_run_id(turn_id) == expected_runs[0]        # position 0 == the @4 id
            assert [e.document_id for e in lane.batches[0]] == seeds["document_ids"]
            # each envelope names its own session and its own item
            assert lane.batches[0][1].config["delegation_bundle"]["artifact"]["position"] == 1
            assert lane.batches[0][1].checkpoint_thread_id != lane.batches[0][0].checkpoint_thread_id
            # three design_job tasks queued
            queued = (await conn.execute(text(
                "SELECT count(*) FROM fleet_task WHERE kind='design_job' AND status='queued' AND work_id = ANY(:ids)"),
                {"ids": [design_runs.work_id_for_run(r) for r in expected_runs]})).scalar_one()
            assert queued == 3
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.assistant_message.count("saved") == 3
            leg = await design_legs.get_leg(conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg_id"])
            assert leg["state"] == "open_awaiting_user"
            # exactly one leg.awaiting_user frame
            frames = (await conn.execute(text(
                "SELECT count(*) FROM agent_turn_event WHERE turn_id=:t AND event_type='leg.awaiting_user'"),
                {"t": turn_id})).scalar_one()
            assert frames == 1
    run_async(scenario())


def test_one_failed_run_still_hands_back_and_names_it(...):
    # status_for returns "failed" for position 1; outcome AWAITING_INPUT; summary line for that
    # title says "failed"; the other two say saved.


def test_all_failed_fails_the_turn_and_keeps_the_leg_open(...):
    # every run failed → outcome FAILED with failure_code DESIGN_LEG_TURN_FAILED; leg open_awaiting_user.


def test_a_single_document_leg_still_dispatches_through_drive_and_enqueues_nothing(...):
    # the P3.4 seed (one document): lane.drive called once; zero design_job rows for that work id.


def test_a_retried_batch_turn_rejoins_its_runs_and_creates_no_second_batch(...):
    # run the turn once with a lane that completes; run it again with _LaneThatMustNotRun (plus a
    # drive_batch that raises): replayed=True, still 3 run rows.


def test_stop_requests_cancellation_on_every_non_terminal_run_of_the_batch(...):
    # seed 3 runs via a lane whose drive_batch leaves runs non-terminal and awaits an event;
    # call runner.request_stop_for_turn(...); assert design_runs.cancellation_requested is True
    # for all three run ids.


def test_batch_summary_names_each_document_and_its_outcome() -> None:
    items = [
        ({"title": "Apollo ad", "position": 0}, {"status": "succeeded", "result": {"status": "proposed", "acceptance_scope": "design", "current_version": 3}}),
        ({"title": "Mercy ad", "position": 1}, {"status": "failed", "result": {"status": "failed", "error": {"message": "boom"}}}),
    ]
    text_ = batch_summary(items)
    assert text_.splitlines()[0].startswith("Apollo ad: Design saved and accepted")
    assert "version 3" in text_.splitlines()[0]
    assert text_.splitlines()[1].startswith("Mercy ad: failed")
```

Fill every elided body; the assertions listed are the contract.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_multi_artifact_leg_engine_db.py -v` (stack DOWN). Expected: FAIL on `design_leg_run_id(turn_id, i)` (unexpected argument) / `batch_summary` import.

- [ ] **Step 3: Implement**

In `design_leg_wiring.py`:

1. `design_leg_run_id(turn_id: UUID, position: int = 0) -> str`: `seed = str(turn_id) if position == 0 else f"{turn_id}:{position}"`; `f"run_{uuid5(_RUN_NAMESPACE, seed).hex}"`.

2. `run_leg_turn`: after the `pinned_document` read, `documents = await design_legs.list_leg_documents(conn, workspace_id=…, leg_id=…)`; if empty and `leg["document_id"]` is set, synthesise one row from `pinned_document` (a pre-migration leg whose backfill row is missing is still a one-document leg). Pass `documents` into `_judge_exit` (Task 8 uses it; this task threads it through as a kwarg the judge ignores until then — add `leg_documents: Sequence[Mapping[str, Any]] = ()` to `_judge_exit` now). After the exit judgment, the addressed set is `documents` (Task 8 narrows it). G1 (finalized) and G2 (account card) run per addressed document: G1 refuses the turn if ANY addressed document is finalized (`DESIGN_LEG_DOCUMENT_FINALIZED`); G2 resolves the account card for each web document with an `account_id` and fails on the first unresolvable one.

3. Replace the `run = await self._dispatch(...)` block with:

```python
            try:
                dispatched = await self._dispatch_batch(
                    submission=submission, leg=leg, leg_id=leg_id, execution_id=execution_id,
                    user_message_ref=user_message_ref, prior_history=prior_history,
                    documents=addressed, account_cards=account_cards, focus_refs=focus_refs,
                    workspace_id=workspace_id, scope_pin=scope_pin, turn_request=request,
                )
            except DesignMemoryScopeError: ...            # unchanged
            except DesignTurnTargetError as exc: ...       # unchanged
            await self._leg_back_to_awaiting(...)
            if all(run["status"] != "succeeded" for _doc, run in dispatched):
                log.warning("design_leg.turn_failed", leg_id=leg_id, turn_id=str(turn_id),
                            run_ids=[str(run.get("run_id")) for _d, run in dispatched])
                return await self._fail_turn(..., failure_code=DESIGN_LEG_TURN_FAILED, stream=stream)
            assistant_message = (
                _assistant_summary(dispatched[0][1]) if len(dispatched) == 1 else batch_summary(dispatched)
            )
            return await self._finalize_awaiting_input(
                submission=submission, execution_id=execution_id, assistant_message=assistant_message,
                domain_refs=tuple(
                    DomainObjectRef(workspace_id=workspace_id, object_type="design_agent_run",
                                    object_id=str(run["run_id"]), version=None)
                    for _doc, run in dispatched
                ),
                stream=stream,
            )
```

`_finalize_awaiting_input` is the existing success tail (assistant artifact, `AgentFinalizeEnvelope(... open_gate_refs=(leg_ref,))`, `record_finalization`, `commit_finalization_authority`, history append, stream rehydrate + `turn_finished(status="awaiting_input")`, the `DesignLegTurnResult`) moved into a method — the single-document path must produce byte-identical envelopes to today (same finalization id, same `domain_refs` of one run).

4. `_dispatch_batch`: for each `(position, document)` in `documents`, compute `run_id = design_leg_run_id(turn_id, document["position"])`, read `get_document` for its row (the runner needs the scene/current_version per document), and build the envelope with `_envelope(...)` given `pinned_document=<that row>`, `run_id=run_id`, `account_card=account_cards.get(document_id)`, plus a new `artifact` kwarg `{"position": document["position"], "count": len(all leg documents), "title": document["title"], "note": document["note"]}` which `_envelope` puts on `config["delegation_bundle"]` as `bundle = {**bundle, "artifact": artifact}` (spec §3.3 step 1; Task 5 renders it). The existing re-join branch (`run is not None`) runs per run. Then, for runs that do not yet exist, ONE transaction: `lock_turn_control` + `stop_requested` check, `mark_leg_running` if awaiting, `create_run(...)` per envelope (stamping `leg_id` and `execution_id` as today), and — only when `len(documents) > 1` — `enqueue_task(conn, kind=FleetTaskKind.DESIGN_JOB, project_run_id=ProjectRunId(envelope.work_id), dedup_key=str(envelope.work_id), payload=envelope.model_dump(mode="json"), reopen_terminal=False)` per envelope (imports: `from clue_fleet.enums import FleetTaskKind`, `from clue_fleet.queue import enqueue_task`, `from clue_core import ProjectRunId`). Then the `design_memory` receipts per envelope (as today), `_wait_for_document` per envelope, and the drive: `await self._lane.drive(envelope=…)` when exactly one envelope needs driving, else `await self._lane.drive_batch(envelopes=[…])`, inside ONE `propagate_trace("design-leg.turn", …)` whose metadata carries `document_ids` and `run_ids` lists (keep the single-document metadata keys as they are when N == 1). After the drive, read every run row; raise if any is non-terminal; `_record_design_receipts` for each; return `[(document, run), …]` in position order.

5. `batch_summary(items)`: one line per item: `f"{title}: {_assistant_summary(run)}"` for a succeeded run (the existing sentence already names the version for web; for scene add `" (now version N)"` when `result["current_version"]` is an int), `f"{title}: failed — {message}"` for a failed run (message from `result.error.message` or `stop_reason`, else "the design run failed"), `f"{title}: cancelled at your request"` when `result.stop_reason == "cancelled_by_request"`. Joined with `"\n"`.

6. `request_stop_for_turn`: `runs = await design_runs.runs_for_execution(conn, workspace_id=…, execution_id=design_leg_execution_id(turn_id))`; for each non-terminal run `request_run_cancellation`. Keep the existing position-0 read as a fallback when the list is empty. `await_stopped_turn`: collect the non-terminal runs' envelopes (`DesignTurnEnvelope.model_validate(run["payload"])`) and `drive_batch` them (or `drive` for one).

7. `load_design_leg_history` is unchanged; each envelope's `history` is the leg's history (as today) and `first_turn_of_leg` is per leg (unchanged).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api/test_multi_artifact_leg_engine_db.py tests/api/test_p34_design_leg_engine_db.py tests/api/test_p37_exit_bridge_db.py tests/api/test_p36_leg_resilience_db.py tests/api/test_design_leg_session_db.py tests/api/test_design_leg_receipts_db.py tests/api/test_genweb_web_turn_dispatch_db.py tests/api/test_p37_leg_stream_events_db.py tests/api/test_design_memory_producer_db.py -v` (stack DOWN). Expected: PASS — the single-document suites must pass WITHOUT edits to their fakes (they implement `drive` only, and a one-document leg calls `drive`).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/design_leg_wiring.py tests/api/test_multi_artifact_leg_engine_db.py
git commit -m "feat(design-legs): the leg turn fans out one run per document, joins, summarises per document, stops the batch (spec §3.3/§3.9)"
```

---

### Task 8: Exit judgment v3 — which documents, or ask

**Files:**
- Modify: `subsystems/design/clue_design/exit_judgment.py`, `subsystems/design/clue_design/evals/golden.py`, `subsystems/design/clue_design/evals/fixtures/` (new fixtures)
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:1647-1730` (judge builder), `platform/api/clue_api/design_leg_wiring.py` (`_judge_exit`, `_exit_judge_artifact_line` → `_exit_judge_artifact_lines`, `_exit_judge_tag_lines`, the ask outcome)
- Test: `tests/design/test_exit_judgment_golden.py`, `tests/api/test_p37_exit_judge_unit.py`, `tests/api/test_multi_artifact_leg_engine_db.py` (append the routing and ask tests)

**Interfaces:**
- Produces:
  ```python
  EXIT_JUDGMENT_PROMPT_VERSION = "v3"
  class ExitJudgment(BaseModel):   # strict, extra="forbid"
      close_this_session: bool
      hand_message_to_strategy_agent: bool = False
      current_artifact_accepted: bool = False
      addressed_artifacts: list[int] | Literal["all"] | None = None
      clarifying_question: str | None = None
      reasoning: str
  class ExitDecision(BaseModel):
      action, reason, fail_safe, reasoning (as today)
      addressed: tuple[int, ...] | None = None   # None = all; 1-based positions as shown to the judge
      ask: str | None = None                      # a stay that dispatches nothing and asks this
  def decide_exit(judgment: ExitJudgment | None, *, artifact_count: int = 1) -> ExitDecision
  def render_exit_judgment_prompt(*, brief, history, message, artifacts: tuple[str, ...] = (), artifact: str | None = None, tags=()) -> str
  class DesignLegExitJudge(Protocol): __call__(..., artifacts: tuple[str, ...] = (), artifact=None, tags=())
  ```
  `decide_exit` rules (spec §3.5): close → as today. Stay + non-blank `clarifying_question` → `ask=question`. Stay on `artifact_count == 1` → `addressed=None`. Stay on `artifact_count > 1`: `"all"` → `None`; a non-empty list whose members are all within `1..artifact_count` → that tuple (deduped, sorted); anything else (absent, empty, out of range, malformed judgment) → `ask=DEFAULT_ADDRESS_QUESTION` with `fail_safe=True`, where `DEFAULT_ADDRESS_QUESTION = "Which of the designs is this for — one of them, a few, or all of them?"`.

- [ ] **Step 1: Present the judge prompt text to the founder (gate)**

Post in chat the v3 instruction block: the v2 text with these changes — the `CURRENT_ARTIFACT` fence becomes `ARTIFACTS` ("the artifacts this session is bound to, numbered"); the output object gains the two answers with the meanings from spec §3.5; the "How to reason" list gains the addressing guidance from spec §3.5 (tagged document strongest but can be a reference; named in words matched against the list including by account; a general statement that plausibly applies to every artifact addresses all; a qualifier addresses the subset; when it could be one or all and nothing says which, ask; on a one-artifact session `addressed_artifacts` is `[1]` and the question is never needed). Wait for the founder's yes or edits.

- [ ] **Step 2: Write the failing tests**

Golden fixtures (new JSON files under `evals/fixtures/`, kind `"addressing"` — add it to the taxonomy set in `test_the_taxonomy_covers_every_master_plan_category`), each with `artifacts: ["1. \"Apollo ad\" (scene ad) [account: Apollo Clinics]", "2. \"Mercy ad\" (scene ad) [account: Mercy Health]", "3. \"Premier ad\" (scene ad) [account: Premier Gastro]"]`, `artifact_count: 3`, and `expected` gaining `addressed`/`ask`:

- `addressing-01-tagged-one.json` — tags `["design \"Apollo ad\" (scene ad) (artifact 1)"]`, message "@Apollo ad bigger logo", judgment `addressed_artifacts: [1]` → expected `continue`, `addressed: [1]`.
- `addressing-02-named-two.json` — "the two hospital ones need a softer palette", judgment `[2, 3]` → `addressed: [2, 3]`.
- `addressing-03-general-all.json` — "make all the headlines shorter", judgment `"all"` → `addressed: null`.
- `addressing-04-ask.json` — "the logo is too small", judgment `clarifying_question: "Which design's logo — Apollo, Mercy, Premier, or all three?"` → `continue`, `ask` set, `addressed: null`.
- `addressing-05-fail-safe-multi.json` — judgment `null`, `artifact_count: 3` → `continue`, `fail_safe: true`, `ask: <DEFAULT_ADDRESS_QUESTION>`.
- `addressing-06-out-of-range.json` — judgment `addressed_artifacts: [7]` → `fail_safe: true`, `ask` set.

`ExitGoldenFixture` gains `artifacts: tuple[str, ...] = ()` and `artifact_count: int = 1`; `ExpectedDecision` gains `addressed: tuple[int, ...] | None = None` and `ask: str | None = None`; `_score` compares `addressed` and `(actual.ask is not None) == (expected.ask is not None)`; `run_decision_golden` calls `decide_exit(fixture.judgment, artifact_count=fixture.artifact_count)`. Existing fixtures carry no new keys and keep passing (single-artifact semantics).

Unit tests in `tests/design/test_exit_judgment_golden.py`:

```python
def test_v3_prompt_numbers_the_artifacts_and_marks_a_tagged_one() -> None:
    prompt = render_exit_judgment_prompt(brief="b", history=(), message="m",
        artifacts=('1. "Apollo ad" (scene ad) [account: Apollo Clinics]', '2. "Mercy ad" (scene ad)'),
        tags=('design "Apollo ad" (scene ad) (artifact 1)',))
    assert "<<<ARTIFACTS\n1. \"Apollo ad\"" in prompt and "(artifact 1)" in prompt
    assert "addressed_artifacts" in prompt and "clarifying_question" in prompt
    assert prompt.rstrip().endswith("prompt_version: v3")


def test_a_single_artifact_session_never_asks_and_addresses_its_one_document() -> None:
    j = ExitJudgment(close_this_session=False, reasoning="edit")
    assert decide_exit(j, artifact_count=1) == ExitDecision(action="continue", reasoning="edit")


@pytest.mark.parametrize("raw", [None, {"close_this_session": False, "reasoning": "x"},
                                 {"close_this_session": False, "reasoning": "x", "addressed_artifacts": []},
                                 {"close_this_session": False, "reasoning": "x", "addressed_artifacts": [0]}])
def test_a_multi_artifact_stay_without_a_usable_address_asks_instead_of_dispatching(raw) -> None:
    decision = decide_exit(parse_exit_judgment(raw), artifact_count=3)
    assert decision.action == "continue" and decision.fail_safe and decision.ask is not None
```

Judge-builder test in `tests/api/test_p37_exit_judge_unit.py`: the fake model's captured prompt contains the `ARTIFACTS` block when `artifacts=(...)` is passed.

Runner tests appended to `tests/api/test_multi_artifact_leg_engine_db.py` (use `_bridged_runner`'s judge/finisher shape from `test_p37_exit_bridge_db.py`):

- a canned judgment `addressed_artifacts: [2]` on the three-document leg → the lane receives ONE envelope for position 1 and the summary names only that title;
- a canned `clarifying_question` → no run rows, no `design_job` rows, `AWAITING_INPUT`, the assistant message IS the question, leg `open_awaiting_user`;
- the judge's `_exit_judge_tag_lines` marks a tagged leg document `(artifact 2)`.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/design/test_exit_judgment_golden.py tests/api/test_p37_exit_judge_unit.py -v`. Expected: FAIL on the new fields / kwargs.

- [ ] **Step 4: Implement**

`exit_judgment.py`: the models and `decide_exit` per the interface; `DEFAULT_ADDRESS_QUESTION`; `render_exit_judgment_prompt` renders `<<<ARTIFACTS\n…\nARTIFACTS>>>` from `artifacts` (falling back to `(artifact,)` when only the v2 kwarg is given, and to `"(unknown — treat the brief as the artifact)"` when neither), the approved v3 text, `EXIT_JUDGMENT_PROMPT_VERSION = "v3"`. Module docstring gains a v3 paragraph (spec §3.5: addresses are numbers, not intents; the multi-document fail-safe asks).

`evals/golden.py`: the fixture and expected fields; the scoring changes above.

`agent_turn_fleet_wiring.py` judge builder: accept `artifacts`, pass it to the prompt, put `"artifacts": list(artifacts)` in the observation input; raise `max_output_tokens` floor to `min(policy.max_output_tokens, 600)` (the answer grew by a question).

`design_leg_wiring.py`: replace `_exit_judge_artifact_line` with

```python
async def _exit_judge_artifact_lines(conn, *, workspace_id, leg_documents) -> tuple[str, ...]:
    lines = []
    for document in leg_documents:
        kind = "web page" if document.get("doc_kind") == "web" else "scene ad"
        line = f'{int(document["position"]) + 1}. "{document.get("title") or "Untitled design"}" ({kind})'
        if document.get("account_id"):
            account = await design_accounts.get_web_account(conn, workspace_id=workspace_id, account_id=str(document["account_id"]))
            if account is not None:
                line += f' [account: {account["name"]}]'
        lines.append(line)
    return tuple(lines)
```

`_exit_judge_tag_lines` takes `leg_documents` and suffixes a tagged leg document with `f" (artifact {position + 1})"` instead of `" (this artifact)"`. `_judge_exit` passes `artifacts=` and `decide_exit(judgment, artifact_count=len(leg_documents))` — move the `decide_exit` call's count in. In `run_leg_turn`: after the judgment, `if exit_decision is not None and exit_decision.ask: return await self._finalize_awaiting_input(..., assistant_message=exit_decision.ask, domain_refs=(), stream=stream)` (log `design_leg.addressing_asked`); `addressed = documents if exit_decision is None or exit_decision.addressed is None else [d for d in documents if d["position"] + 1 in exit_decision.addressed]`. Log the addressed positions on `design_leg.exit_judgment`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/design/test_exit_judgment_golden.py tests/api/test_p37_exit_judge_unit.py tests/api/test_p37_exit_bridge_db.py tests/api/test_multi_artifact_leg_engine_db.py -v` (stack DOWN). Expected: PASS, golden set 100%.

- [ ] **Step 6: Commit**

```bash
git add subsystems/design/clue_design/exit_judgment.py subsystems/design/clue_design/evals platform/api/clue_api/agent_turn_fleet_wiring.py platform/api/clue_api/design_leg_wiring.py tests/design/test_exit_judgment_golden.py tests/api/test_p37_exit_judge_unit.py tests/api/test_multi_artifact_leg_engine_db.py
git commit -m "feat(design-legs): exit judgment v3 — which documents a message addresses, or ask (spec §3.5)"
```

---

### Task 9: Composer tags over the leg's document set

**Files:**
- Modify: `platform/api/clue_api/chat/composer_context.py:190-330` (`validated_context_refs`), `platform/api/clue_api/chat/router.py:606-640` and `:2470-2480` (`_validated_submission_context`)
- Test: `tests/api/test_chat_composer_context.py` (update `test_context_validation_accepts_exact_nodes_only_on_the_open_leg_document`, add a multi-document case), `tests/api/test_reference_images_contract.py`

**Interfaces:**
- Produces: `validated_context_refs(..., design_leg_document_ids: tuple[str, ...] = (), ...)` replacing `design_leg_document_id`; node targets must name exactly one design document that is IN the set; reference images require a non-empty set whose documents are all `scene`.

- [ ] **Step 1: Write the failing test**

```python
def test_context_validation_accepts_nodes_on_any_document_of_a_multi_document_leg(...):
    # two scene documents d0, d1 on the leg; refs = [design_document d1 @v, design_node n @v]
    # → accepted; the same refs with design_leg_document_ids=(d0,) → CONTEXT_REF_RELATIONSHIP_MISMATCH.
```

Model it on the existing single-document test at line 221 (same seeding, one more document).

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/api/test_chat_composer_context.py -v -k multi_document`. Expected: FAIL (`unexpected keyword argument`).

- [ ] **Step 3: Implement**

Rename the parameter; the node-target branch: `if len(document_refs) != 1 or not design_leg_document_ids: raise …("design node targets require one document reference on the open design leg")`; `if target_document_ref.object_id not in design_leg_document_ids: raise …("the targeted design document is not one of the open design leg's documents")`. Reference-image branch: require `design_leg_document_ids`; when no `target_document` was loaded, load every leg document and refuse unless all are `scene`. Router: `_validated_submission_context(..., design_leg_document_ids=…)` where the route computes the set with `design_legs.list_leg_documents` when `open_leg` is not None (fallback `(open_leg["document_id"],)` if the list is empty and the pin is set). Grep for every other caller of `validated_context_refs` (`tests/api/test_project_document_context_refs_db.py`, `tests/design/test_p31_design_vocabulary_db.py`) and update the kwarg.

- [ ] **Step 4: Run the tests** — `uv run pytest tests/api/test_chat_composer_context.py tests/api/test_reference_images_contract.py tests/api/test_project_document_context_refs_db.py tests/design/test_p31_design_vocabulary_db.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/composer_context.py platform/api/clue_api/chat/router.py tests/api/test_chat_composer_context.py tests/api/test_project_document_context_refs_db.py tests/design/test_p31_design_vocabulary_db.py
git commit -m "feat(design-legs): composer tags validate against the leg's document set (spec §3.7)"
```

---

### Task 10: The gallery and the artifacts page read the set; the feed carries the account; the close records every version

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py:562-625` (`project_design_documents`), `:693-765` (`workspace_design_documents`), `platform/api/clue_api/chat/schemas.py:652-671`, `platform/api/clue_api/chat/router.py:262-300` (`_design_artifact_list_item`), `platform/api/clue_api/design_leg_tools.py` (`FinishDesignLegTool.invoke`: `summary_refs["document_versions"]`)
- Test: `tests/api/test_design_artifact_feed_db.py` (append), `tests/api/test_p35_finish_design_leg_db.py` (append)

**Interfaces:**
- Produces: both derivations select from `design_leg_document ld JOIN design_leg leg ON leg.id = ld.leg_id AND leg.workspace_id = ld.workspace_id` (DISTINCT ON `ld.document_id`, latest leg wins) instead of `design_leg.document_id`; `project_design_documents` rows gain `account_id, account_name, account_domain, account_entity_id` via `LEFT JOIN design_account a ON a.account_id = d.account_id AND a.workspace_id = :ws`; `DesignArtifactListItemWire.account: DesignArtifactAccountWire | None = None` with `DesignArtifactAccountWire(id, name, domain: str | None, account_entity_id: str | None)`; the finish tool's `summary_refs` gains `"document_versions": {document_id: version}` beside the existing `document_id`/`document_version`.

- [ ] **Step 1: Write the failing tests** — in `test_design_artifact_feed_db.py`: a leg with two child documents lists both with the leg's thread as origin; a document born with an account lists `account.name`. In `test_p35_finish_design_leg_db.py`: closing a two-document leg journals both versions.

- [ ] **Step 2: Run to verify they fail** — focused `-k` runs. Expected: FAIL (one row listed / no `account` key / no `document_versions`).

- [ ] **Step 3: Implement** the SQL and wire changes above; `_design_artifact_list_item` maps the four account columns into `account` when `account_id` is not None. `FinishDesignLegTool.invoke`: after the existing `document_version` read, `documents = await design_legs.list_leg_documents(...)`, `summary_refs["document_versions"] = {d["document_id"]: int(d["current_version"] or 0) for d in documents}`. The artifacts-page read (`frontend_read/artifacts.py`) needs no code change beyond the derivation it already calls.

- [ ] **Step 4: Run the tests** — `uv run pytest tests/api/test_design_artifact_feed_db.py tests/api/test_design_artifact_seam_db.py tests/api/test_p35_finish_design_leg_db.py tests/api/test_artifacts_* -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/chat/schemas.py platform/api/clue_api/chat/router.py platform/api/clue_api/design_leg_tools.py tests/api/test_design_artifact_feed_db.py tests/api/test_p35_finish_design_leg_db.py
git commit -m "feat(design-legs): gallery and library derive from the leg's document set; the feed carries the account (spec §3.8)"
```

---

### Task 11: Frontend — a tab per born document, the account on the card wire

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/model/artifact-auto-open.ts`, `apps/frontend/src/features/chat-shell/components/chat-surface.tsx:592-620`, `apps/frontend/src/features/design-editor/model/artifact.ts:70-115`, `apps/frontend/src/features/design-editor/adapter/gallery.ts:77-95`
- Test: `apps/frontend/src/features/chat-shell/model/artifact-auto-open.test.ts`, `apps/frontend/src/features/design-editor/adapter/gallery.test.ts`

**Interfaces:**
- Produces: `artifactsToAutoOpen({...}): ChatShellOpenArtifact[]` (every new/updated artifact from this thread, feed order; empty when none) — `artifactToAutoOpen` is deleted; `DesignArtifactListItem.account?: { id, name, domain?, accountEntityId? }`; `toProjectArtifact` sets `accountId`, `accountName`, `accountLogoPath` (`/api/source-favicon?domain=…`, the artifact-library's own rule) when `account` is present. No new UI: the gallery card renders these only where its designed component already reads them (spec §3.8).

- [ ] **Step 1: Write the failing tests**

In `artifact-auto-open.test.ts`, replace the single-winner test with:

```ts
test("every document born into the active thread opens, in feed order", () => {
  assert.deepEqual(
    artifactsToAutoOpen({ activeThreadId: ACTIVE, artifacts: [card("d0"), card("d1"), card("d2")], knownArtifactIds: new Set() }),
    [
      { id: "d0", kind: "web", title: "Document d0" },
      { id: "d1", kind: "web", title: "Document d1" },
      { id: "d2", kind: "web", title: "Document d2" },
    ],
  );
});
```

and update the other tests to expect `[]` / a one-element list. In `gallery.test.ts`: an item with `account: { id: "acc_1", name: "Apollo Clinics", domain: "apollo.example" }` maps to `accountId: "acc_1"`, `accountName: "Apollo Clinics"`, `accountLogoPath: "/api/source-favicon?domain=apollo.example"`; an item without stays without the keys.

- [ ] **Step 2: Run to verify they fail** — `cd apps/frontend && npm test`. Expected: FAIL.

- [ ] **Step 3: Implement**

`artifact-auto-open.ts`: rename to `artifactsToAutoOpen`, collect every qualifying artifact (same known/update filter, same thread filter), sort by `updatedAtOf` ascending so the first born is first, return the mapped list. `chat-surface.tsx`: `const opening = artifactsToAutoOpen(...)`; after banking, `if (opening.length === 0) return; for (const artifact of opening) openArtifact(artifact); shell.activateArtifact(opening[0].id);` (`activateArtifact` exists on the shell controller — `use-editor-shell-controller.ts:213`; check the `shell` object exposes it under that name and add it to the returned object if not). `artifact.ts`: add the optional `account` object to `DesignArtifactListItemSchema` and parse `item.account` (nullish) from the wire (`account_entity_id` → `accountEntityId`). `gallery.ts`: spread the three fields from `item.account`.

- [ ] **Step 4: Run the gates** — `cd apps/frontend && npm test && npm run design-system:build && npm run lint && npm run build` (stop the lane's frontend first if it holds the port). Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/chat-shell/model/artifact-auto-open.ts apps/frontend/src/features/chat-shell/model/artifact-auto-open.test.ts apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/design-editor/model/artifact.ts apps/frontend/src/features/design-editor/adapter/gallery.ts apps/frontend/src/features/design-editor/adapter/gallery.test.ts
git commit -m "feat(chat-shell): a tab per born design document; the account rides the feed card (spec §3.8)"
```

---

### Task 12: Docs, memory, the full gate, the live-acceptance checklist

**Files:**
- Modify: `CLAUDE.md` (a backlog bullet under the design entries), `_memory/2026-09-19-multi-artifact-design-legs.md` (closing entry), `docs/superpowers/specs/archive/2026-09-19-multi-artifact-design-legs-design.md` (status line → implemented on branch X, owed live proofs)
- Modify: `.env.example` — nothing new is read from the environment; assert that with `git diff --stat -- .env.example` empty (the parity rule).

- [ ] **Step 1: Run the whole offline gate** — `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports`, then `uv run pytest tests/design tests/api -x -q --ignore-glob='*_live.py'` with the stack DOWN and NO provider keys in the environment (unset `CLUE_OPENROUTER_API_KEY`, `LUMEN_AGENT_API_KEY`, `CLUE_EXA_API_KEY` for the run). Record the counts in the memory note. Any red that is pre-existing on the base is listed by name, not fixed here.

- [ ] **Step 2: Write the records** — the CLAUDE.md bullet: `**[design×legs] Multi-artifact design legs shipped <date> (spec …, plan …).** One leg holds a set of documents; N parallel design runs; judge v3 addresses documents; account stamped on born ads. **Owed (founder-triggered):** the six live proofs of spec §7.` The memory closing entry: commits per task, rulings taken during execution, gates run with counts, the owed live proofs.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md _memory/2026-09-19-multi-artifact-design-legs.md docs/superpowers/specs/archive/2026-09-19-multi-artifact-design-legs-design.md
git commit -m "docs(design-legs): multi-artifact legs — records, gates, owed live proofs"
```

- [ ] **Step 4: Hand the live checklist to the founder (do NOT run it)** — spec §7 items 1–6 verbatim, with the log lines to watch: `design_job.started` (several worker ids), `design_leg.lane_drive_finished`, `design_leg.exit_judgment` (with `addressed`), `design_leg.addressing_asked`, `design_leg.waiting_for_document`, and the SQL `SELECT run_id, status, document_id FROM design_agent_run WHERE execution_id = '<execution>' ORDER BY created_at`.

---

## Self-review

**Spec coverage.** §3.1 delegation → Task 3 (+ Task 4 prompt/pins). §3.2 storage → Task 1. §3.3 execution → Tasks 5, 6, 7. §3.4 sessions → unchanged, asserted in Task 7 (distinct `checkpoint_thread_id` per envelope). §3.5 routing → Task 8. §3.6 account stamp → Tasks 2, 3. §3.7 tags → Task 9. §3.8 frontend + feed → Tasks 10, 11. §3.9 Stop → Task 7. §5 cost → no code. §7 acceptance → Task 12 hand-off. Failure model (§3.3): worker death and retry re-join are covered by Task 6's foreign-lease test and Task 7's replay test; one-failed-run by Task 7.

**Placeholder scan.** Tasks 3, 7, 8, 9, 10 list test names with prose bodies ("fill every elided body; the assertions listed are the contract") — the assertions ARE stated in each bullet, so an implementer has the contract; the code shown for the first test in each file is the template. Nothing says TBD/TODO.

**Type consistency.** `LegDocumentSpec(document_id, position, note)` (T1) used positionally in T3/T7; `list_leg_documents` row keys `document_id/position/note/title/doc_kind/current_version/account_id` used in T7/T8/T9/T10; `derive_leg_document_id(*, leg_id, position=0)` (T3) and `design_leg_run_id(turn_id, position=0)` (T7) both position-0-compatible; `drive_batch(*, envelopes)` (T6) called by T7 with a list; `ExitDecision.addressed` is 1-based positions (T8) and T7/T8 convert with `position + 1`; `runs_for_execution` (T2) used by T7's stop path; `DesignArtifactAccountWire` (T10) consumed by T11's Zod schema as `account`.
