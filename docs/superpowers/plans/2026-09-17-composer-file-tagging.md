# Composer `@` tagging of files, microsites and accounts — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user type `@` in a project chat and tag any Gallery file, any microsite, or any account/contact, so the agent receives an exact, version-pinned reference without the user ever seeing a path or an id.

**Architecture:** One new wire type, `project_document`, joins the existing `context_refs` mechanism (request Literal, database CHECK, validation, compiled focus card, transcript echo). Microsites and scene ads reuse the existing `design_document` ref, gaining project containment. The frontend builds the picker's Files and Microsites entries from the two feeds the Gallery already renders, widens the mention element to carry a type and a version, and replaces the flat picker with a two-level one (categories when the query is empty, cross-category search when it is not). Routing is untouched: an open design leg receives a turn, otherwise Head-of-ABM does, and no ref changes that.

**Tech Stack:** FastAPI + pydantic + SQLAlchemy text SQL + Alembic (backend); Next.js App Router, TypeScript, Slate, Zod, `node:test` via `tsx --test` (frontend).

**Spec:** `docs/superpowers/specs/archive/2026-09-17-composer-file-tagging-design.md` (approved 2026-09-17). Read it first; every value below comes from it or from the code as read on 2026-09-17.

## Global Constraints

- **Local commits only. Never `git push`, never open a PR.** No `Co-Authored-By` or any AI attribution in commit messages.
- **Never use `git stash`** (bare or otherwise). Set work aside with a WIP commit if you must.
- **Never run `make check`, the whole pytest suite, or any `*_live.py` test.** Run only the files named in each task, always with `-p no:cacheprovider --ignore-glob='*_live.py'`. DB tests run against the lane database named by `CLUE_DATABASE_URL` in `.env`, through the fixtures in `tests.claimstore.conftest` (`require_claimstore_db`, `migrated_db`, `rollback_conn`) and `tests.db.conftest.run_async`.
- **No new environment flags.** Nothing in this plan reads a new env setting; if you find yourself adding one, stop and escalate.
- **No path, id, version number or storage key may appear in any user-visible string** (picker rows, chips, transcript, aria-labels, titles). Titles and kind labels only.
- **Routing stays as it is.** Do not touch `agent_turn_fleet_wiring.py:433-461`, `design_leg_tools.py`, or anything that opens a design leg.
- **Alembic:** generate the migration with `uv run alembic revision -m "<slug>"` (random hash id) chained off the current single head (`uv run alembic heads` must print exactly one revision before and after). Hand-written `upgrade()` and `downgrade()`; never renumber.
- **Frontend gate** for any task that touches `apps/frontend`: from `apps/frontend`, `npm test` (all `*.test.ts` under `src`), then `npm run lint && npm run build`. Three pre-existing `tsc` errors in untouched test files are known; do not fix or widen them.
- **Backend gate** per task: the pytest files named in the task, plus `uv run ruff check <changed files>` and `uv run mypy <changed files>` where the repo's mypy config covers them.
- **Copy rules (verbatim):** category labels `Files`, `Microsites`, `Accounts`; empty lines `No files in the Gallery yet`, `No microsites yet`, `No accounts yet`, `No matches`; `@` button label `Add context`; listbox label `Choose context`; chip fallbacks `Selected file`, `Selected design`.
- **Limits (verbatim):** `MAX_CONTEXT_REFS_PER_TURN = 100` (unchanged), `MAX_DESIGN_REFERENCE_ASSETS = 4` (unchanged), mention query cap `60` characters.
- Do not dispatch subagents of your own. Report back; review comes from the controller.

---

## File map

| File | Responsibility in this plan |
|---|---|
| `platform/api/clue_api/chat/schemas.py` | `ContextRefRequest.object_type` gains `project_document` (Task 1) |
| `alembic/versions/<hash>_project_document_turn_context_refs.py` | CHECK widened (Task 1) |
| `tests/api/test_project_document_context_refs_db.py` | new DB test file shared by Tasks 1–3 |
| `platform/api/clue_api/arv2/project_documents.py` | `get_project_document`, `latest_project_document_version`, `document_title` (Task 2, 3) |
| `platform/api/clue_api/chat/composer_context.py` | `project_id` kwarg, `project_document` branch, design containment (Task 2); `context_ref_presentations` (Task 4) |
| `platform/api/clue_api/chat/router.py` | passes `project_id` (Task 2); presentations for all three types (Task 4) |
| `platform/api/clue_api/chat/stream.py` | live turn list merges presentations (Task 4) |
| `platform/api/clue_api/account_research_turn_wiring.py` | `project_document` focus card (Task 3) |
| `platform/api/clue_api/frontend_read/project_documents.py` | `_title` delegates to `document_title` (Task 3) |
| `tests/api/test_chat_composer_context.py` | unit tests for the new branches (Task 2, 4) |
| `apps/frontend/src/features/projects/model/project-workspace.ts` | entity type/category/icon widening; artifact `documentId`/`version` (Task 5) |
| `apps/frontend/src/features/projects/model/composer-context-catalog.ts` (+ `.test.ts`) | catalog builder, search, categories, mention query detection (Task 5) |
| `apps/frontend/src/features/projects/model/project-composer.ts`, `project-composer-editor.ts` | mention element carries type + version (Task 5) |
| `apps/frontend/src/features/projects/model/chat-context-handoff.ts`, `chat-turn.ts`, `chat-message.ts` | ref type widening; `kind` on echoed refs (Task 5) |
| `apps/frontend/src/features/design-editor/adapter/gallery.ts` | `toProjectArtifact` fills `documentId` and `version` (Task 5) |
| `apps/frontend/src/features/projects/hooks/use-project-workspace-controller.ts` | `setCatalogEntities` (Task 6) |
| `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` | documents hook, catalog, transcript entities (Task 6) |
| `apps/frontend/src/features/projects/components/conversation-content.tsx` | `contextEntities` prop (Task 6) |
| `apps/frontend/src/features/projects/components/entity-picker.tsx` | two-level picker (Task 7) |
| `apps/frontend/src/features/projects/components/project-composer-editor.tsx` | category state, keyboard, query regex, chip render (Task 7, 8) |
| `apps/frontend/src/features/projects/components/project-composer.tsx` | `@` button labels, `categoriesEnabled` (Task 7) |
| `apps/frontend/src/features/projects/components/project-flow.module.css` | category rows, icons (Task 7) |
| `apps/frontend/src/features/projects/components/chat-transcript.tsx` | chip fallbacks and `@` prefix (Task 8) |
| `apps/frontend/docs/api-contracts/projects.md`, `_memory/2026-09-17-composer-file-tagging.md`, `_memory/README.md` | contract notes and session memory (Task 8) |

---

### Task 1: `project_document` on the wire and in the CHECK

**Files:**
- Modify: `platform/api/clue_api/chat/schemas.py:196-205`
- Create: `alembic/versions/<hash>_project_document_turn_context_refs.py`
- Create: `tests/api/test_project_document_context_refs_db.py`

**Interfaces:**
- Consumes: `insert_submission(conn, *, turn_id, workspace_id, project_id, thread_id, submitted_by_user_id, submitted_via_membership_id, onboarding_input_id, message_artifact_key, message_sha256, idempotency_key, context_refs=(...), previous_turn_outcome=...)` and `submission_context_refs(conn, *, workspace_id, turn_id)` from `clue_api.agent_turn_submission`; `seed_project(conn, ws, name=...)` from `tests._workspace`; `write_project_plan(conn, storage, ProjectPlanWrite(...))` from `clue_api.arv2.project_documents`.
- Produces: the DB accepts `object_type='project_document'` rows; the test module's `_seed(conn, storage)` helper (dict with `ws`, `project_id`, `brand_id`, `thread_id`, `user_id`, `membership_id`, `onboarding_input_id`, `artifact_key`, `sha`, `plan` — a `WrittenDocument` with `document_id`, `path`, `version`) that Tasks 2 and 3 extend.

- [ ] **Step 1: Write the failing DB test**

Create `tests/api/test_project_document_context_refs_db.py`:

```python
"""``project_document`` context refs: the CHECK, the validation, the focus card.

One seed: a project with a plan written through the real writer, plus the smallest honest
submission scaffolding (artifact, onboarding input, thread, user, membership), so a submission
carrying a ``project_document`` ref can be inserted and re-read exactly as the fleet re-reads it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import DomainObjectRef
from clue_api.agent_turn_submission import insert_submission, submission_context_refs
from clue_api.arv2.project_documents import ProjectPlanWrite, write_project_plan
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

PLAN_BODY = """# Q4 expansion plan

## Outcome
Twenty qualified conversations with GI-focused ASCs by the end of the quarter.
"""


async def _seed(conn: AsyncConnection, storage: FsStorage) -> dict[str, Any]:
    ws = f"ws_test_pdref_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="Project document refs")
    plan = await write_project_plan(
        conn,
        storage,
        ProjectPlanWrite(
            workspace_id=ws,
            brand_id=str(project.brand_id),
            project_id=project.project_id,
            turn_id=uuid4(),
            user_id="usr_pdref",
            body=PLAN_BODY,
            expected_version=None,
        ),
    )
    sha = "b" * 64
    artifact_key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 5)"
        ),
        {"key": artifact_key, "ws": ws, "sha": sha},
    )
    onboarding_input_id = uuid5(NAMESPACE_URL, f"pdref-onb:{ws}")
    await conn.execute(
        text(
            "INSERT INTO onboarding_input (id, workspace_id, brand_id, kind, artifact_key, "
            " content_sha256, actor) "
            "VALUES (:id, :ws, :brand, 'user_turn', :key, :sha, 'human')"
        ),
        {
            "id": onboarding_input_id,
            "ws": ws,
            "brand": project.brand_id,
            "key": artifact_key,
            "sha": sha,
        },
    )
    thread_id = f"thr_pdref_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": ws, "project": project.project_id},
    )
    user_id = f"user_pdref_{uuid4().hex[:8]}"
    membership_id = f"member_pdref_{uuid4().hex[:8]}"
    await conn.execute(
        text("INSERT INTO platform_user (user_id) VALUES (:user)"), {"user": user_id}
    )
    await conn.execute(
        text(
            "INSERT INTO workspace_membership (membership_id, workspace_id, user_id, "
            " role_key, status, activated_at) "
            "VALUES (:membership, :ws, :user, 'owner', 'active', now())"
        ),
        {"membership": membership_id, "ws": ws, "user": user_id},
    )
    return {
        "ws": ws,
        "project_id": project.project_id,
        "brand_id": str(project.brand_id),
        "thread_id": thread_id,
        "user_id": user_id,
        "membership_id": membership_id,
        "onboarding_input_id": onboarding_input_id,
        "artifact_key": artifact_key,
        "sha": sha,
        "plan": plan,
    }


def _submission_kwargs(seeds: dict[str, Any], tag: str) -> dict[str, Any]:
    return {
        "turn_id": uuid5(NAMESPACE_URL, f"pdref:{tag}:{seeds['ws']}"),
        "workspace_id": seeds["ws"],
        "project_id": seeds["project_id"],
        "thread_id": seeds["thread_id"],
        "submitted_by_user_id": seeds["user_id"],
        "submitted_via_membership_id": seeds["membership_id"],
        "onboarding_input_id": seeds["onboarding_input_id"],
        "message_artifact_key": seeds["artifact_key"],
        "message_sha256": seeds["sha"],
        "idempotency_key": None,
    }


def test_project_document_ref_persists_on_submission(migrated_db: bool, tmp_path: Path) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            plan = seeds["plan"]
            kwargs = _submission_kwargs(seeds, "persist")
            ref = DomainObjectRef(
                workspace_id=seeds["ws"],
                object_type="project_document",
                object_id=str(plan.document_id),
                version=plan.version,
            )
            _row, created = await insert_submission(conn, context_refs=(ref,), **kwargs)
            assert created
            refs = await submission_context_refs(
                conn, workspace_id=seeds["ws"], turn_id=kwargs["turn_id"]
            )
            assert refs == (ref,)
            await txn.rollback()

    run_async(scenario())


def test_context_ref_type_is_check_bounded(migrated_db: bool, tmp_path: Path) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
            seeds = await _seed(conn, FsStorage(tmp_path))
            kwargs = _submission_kwargs(seeds, "bad-type")
            with pytest.raises(IntegrityError):
                await insert_submission(
                    conn,
                    context_refs=(
                        DomainObjectRef(
                            workspace_id=seeds["ws"],
                            object_type="gallery_card",
                            object_id="x",
                            version=1,
                        ),
                    ),
                    **kwargs,
                )

    run_async(scenario())
```

If `write_project_plan` requires the project's brand to carry a brand-knowledge scope or storage layout that `seed_project` does not create, read `tests/api/test_frontend_read_project_documents_db.py::_seed` (it writes a plan the same way) and mirror exactly what it seeds.

- [ ] **Step 2: Run it to see the first test fail on the CHECK**

Run: `uv run pytest tests/api/test_project_document_context_refs_db.py -p no:cacheprovider --ignore-glob='*_live.py' -v`
Expected: `test_project_document_ref_persists_on_submission` FAILS with `IntegrityError` naming `agent_turn_submission_context_ref_type`; `test_context_ref_type_is_check_bounded` PASSES.

- [ ] **Step 3: Widen the request Literal**

In `platform/api/clue_api/chat/schemas.py`, replace the `ContextRefRequest` body:

```python
class ContextRefRequest(_Request):
    """An ordered, workspace-scoped domain-object reference.

    ``design_document`` (P3.1) pins the open leg's document, or — with no nodes beside it — is a
    plain mention of a microsite or ad from the Gallery. ``design_node`` is the ordered,
    per-message selection inside that exact document scene. ``design_asset`` identifies one ready
    image in the design asset library for reference conditioning. ``project_document`` is a
    Gallery file (a row of ``brand_knowledge_document`` with a project), always version-pinned.
    """

    object_type: Literal[
        "account", "contact", "design_document", "design_node", "design_asset", "project_document"
    ]
    object_id: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, gt=0)
```

- [ ] **Step 4: Generate and fill the migration**

Run: `uv run alembic heads` (expect exactly one: `e8fdb29cd532` at the time of writing; use whatever it prints as `down_revision`), then `uv run alembic revision -m "project document turn context refs"`. Replace the generated file's body below the docstring with:

```python
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "<the id alembic generated>"
down_revision: str | None = "<the head alembic printed>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS = "('account', 'contact', 'design_document', 'design_node', 'design_asset')"
_CURRENT = (
    "('account', 'contact', 'design_document', 'design_node', 'design_asset', "
    "'project_document')"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        f"CHECK (object_type IN {_CURRENT})"
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account, contact, design-document, design-node, design-asset, or "
        "project-document references captured with one human chat submission. Design assets are "
        "accepted only as ready image references for an open scene-design leg; project documents "
        "are Gallery files pinned to the version the user tagged.'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        f"CHECK (object_type IN {_PREVIOUS})"
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account, contact, design-document, design-node, or design-asset "
        "references captured with one human chat submission. Design assets are accepted only "
        "as ready image references for an open scene-design leg.'"
    )
```

Keep the conventions docstring Alembic's template emits (the same one `db145059253b` carries).

- [ ] **Step 5: Apply to the lane DB and re-run**

Run: `set -a; source .env; set +a; uv run alembic upgrade head && uv run alembic heads` — one head. Then the Step 2 command. Expected: both tests PASS. Then `uv run alembic downgrade -1 && uv run alembic upgrade head` — clean both ways.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/chat/schemas.py alembic/versions/*_project_document_turn_context_refs.py tests/api/test_project_document_context_refs_db.py
git commit -m "feat(chat): accept project_document context refs on the wire and in the submission CHECK"
```

---

### Task 2: Validate `project_document` refs and contain design refs to the project

**Files:**
- Modify: `platform/api/clue_api/arv2/project_documents.py` (after `list_project_documents`, ~line 800)
- Modify: `platform/api/clue_api/chat/composer_context.py:135-165, 315-345, 413-430`
- Modify: `platform/api/clue_api/chat/router.py:609-646, 873-877, 1310-1314, 2350-2357`
- Test: `tests/api/test_chat_composer_context.py`, `tests/api/test_project_document_context_refs_db.py`

**Interfaces:**
- Consumes: `_document(conn, *, workspace_id, project_id, document_id, servable_only=True)` and `_row(mapping)` in `arv2/project_documents.py`; `project_design_documents(conn, *, workspace_id, project_id)` in `clue_api.design_leg_wiring` (returns dicts with `id`).
- Produces:
  - `async def get_project_document(conn, *, workspace_id: str, project_id: str, document_id: UUID) -> ProjectDocumentRow | None`
  - `async def latest_project_document_version(conn, *, workspace_id: str, project_id: str, path: str) -> int | None`
  - `validated_context_refs(conn, *, workspace_id, refs, design_leg_document_id=None, storage=None, project_id: str | None = None)`
  - `prepare_composer_context_entities(conn, *, workspace_id, refs, project_id: str | None = None)`
  - `_validated_submission_context(conn, *, workspace_id, refs, design_leg_document_id=None, storage=None, project_id=None)` in the router.

- [ ] **Step 1: Unit tests for the new branches (no DB)**

Append to `tests/api/test_chat_composer_context.py`:

```python
PLAN_DOCUMENT = UUID("00000000-0000-0000-0000-00000000d0c1")


def _plan_row(version: int = 2):
    return SimpleNamespace(
        document_id=PLAN_DOCUMENT,
        path="project/plan.md",
        kind="project-plan",
        version=version,
        status="ready",
        updated_at=None,
        artifact_key="ws/abc",
        artifact_sha256="a" * 64,
        icp_key=None,
    )


def test_project_document_refs_require_a_project_and_pin_the_latest_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_project_document(*_args: object, **kwargs: object):
        return _plan_row() if kwargs["document_id"] == PLAN_DOCUMENT else None

    async def latest_project_document_version(*_args: object, **_kwargs: object):
        return 2

    monkeypatch.setattr(composer_context, "get_project_document", get_project_document)
    monkeypatch.setattr(
        composer_context, "latest_project_document_version", latest_project_document_version
    )

    pinned = (_ref("project_document", PLAN_DOCUMENT, version=2),)
    assert (
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=pinned,
                project_id="prj_1",
            )
        )
        == pinned
    )

    with pytest.raises(ContextReferenceError) as no_project:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=pinned,
            )
        )
    assert no_project.value.code == "CONTEXT_REF_RELATIONSHIP_MISMATCH"

    with pytest.raises(ContextReferenceError) as unpinned:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("project_document", PLAN_DOCUMENT),),
                project_id="prj_1",
            )
        )
    assert unpinned.value.code == "CONTEXT_REF_STALE"

    with pytest.raises(ContextReferenceError) as missing:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("project_document", ACCOUNT_A, version=2),),
                project_id="prj_1",
            )
        )
    assert missing.value.code == "CONTEXT_REF_NOT_FOUND"


def test_project_document_refs_refuse_a_superseded_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_project_document(*_args: object, **_kwargs: object):
        return _plan_row(version=2)

    async def latest_project_document_version(*_args: object, **_kwargs: object):
        return 3

    monkeypatch.setattr(composer_context, "get_project_document", get_project_document)
    monkeypatch.setattr(
        composer_context, "latest_project_document_version", latest_project_document_version
    )
    with pytest.raises(ContextReferenceError) as stale:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("project_document", PLAN_DOCUMENT, version=2),),
                project_id="prj_1",
            )
        )
    assert stale.value.code == "CONTEXT_REF_STALE"


def test_design_document_mentions_must_belong_to_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_document(*_args: object, **_kwargs: object):
        return {"id": "doc_site", "doc_kind": "web", "current_version": 4}

    async def project_design_documents(*_args: object, **_kwargs: object):
        return ({"id": "doc_other"},)

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    monkeypatch.setattr(composer_context, "project_design_documents", project_design_documents)
    with pytest.raises(ContextReferenceError) as foreign:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_design_ref("design_document", "doc_site", version=4),),
                project_id="prj_1",
            )
        )
    assert foreign.value.code == "CONTEXT_REF_NOT_FOUND"

    async def containing(*_args: object, **_kwargs: object):
        return ({"id": "doc_site"},)

    monkeypatch.setattr(composer_context, "project_design_documents", containing)
    accepted = asyncio.run(
        validated_context_refs(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=(_design_ref("design_document", "doc_site", version=4),),
            project_id="prj_1",
        )
    )
    assert accepted[0].object_id == "doc_site"
```

- [ ] **Step 2: Run the unit tests to see them fail**

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_chat_composer_context.py -p no:cacheprovider --ignore-glob='*_live.py' -v -k "project_document or design_document_mentions"`
Expected: FAIL — `AttributeError` on `composer_context.get_project_document` / `project_design_documents`, or `TypeError: unexpected keyword argument 'project_id'`.

- [ ] **Step 3: Add the two read helpers**

Append to `platform/api/clue_api/arv2/project_documents.py` right after `list_project_documents`:

```python
async def get_project_document(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, document_id: UUID
) -> ProjectDocumentRow | None:
    """One servable document of this project by its row id, or ``None``.

    The composer's ``project_document`` context ref is validated through this read: a row of
    another project, another workspace, an unservable status, or one whose bytes were never
    written is indistinguishable from absence.
    """

    row = await _document(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        servable_only=True,
    )
    if row is None or row["artifact_key"] is None:
        return None
    return _row(row)


async def latest_project_document_version(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, path: str
) -> int | None:
    """The highest servable version of one path in this project — what the Gallery lists."""

    value = (
        await conn.execute(
            text(
                "SELECT version FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                "  AND path = :path AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "ORDER BY version DESC LIMIT 1"
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "path": path,
                "statuses": list(_SERVABLE_STATUSES),
            },
        )
    ).scalar()
    return None if value is None else int(value)
```

Add both names to the module's `__all__` if it has one.

- [ ] **Step 4: Widen `validated_context_refs`**

In `platform/api/clue_api/chat/composer_context.py`:

1. Add imports at module top (module-level, so tests can monkeypatch them):
```python
from clue_api.arv2.project_documents import (
    get_project_document,
    latest_project_document_version,
)
from clue_api.design_leg_wiring import project_design_documents
```
If importing `clue_api.design_leg_wiring` at module import time creates a cycle (`ImportError` on `uv run python -c "import clue_api.chat.composer_context"`), move that one import into a tiny module-level indirection instead:
```python
async def project_design_documents(conn, *, workspace_id: str, project_id: str):
    from clue_api.design_leg_wiring import project_design_documents as read
    return await read(conn, workspace_id=workspace_id, project_id=project_id)
```
Either way the test monkeypatches `composer_context.project_design_documents`.

2. Signature:
```python
async def validated_context_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[DomainObjectRef],
    design_leg_document_id: str | None = None,
    storage: StorageBackend | None = None,
    project_id: str | None = None,
) -> tuple[DomainObjectRef, ...]:
    """Validate tenancy, exact revisions, project containment, and contact/account relationship.

    ``project_id`` is the project the composer belongs to. ``project_document`` refs require it
    (a Gallery file is only addressable inside its project); ``design_document`` refs are
    additionally contained to the project's own design documents when it is given. The Home
    bootstrap has no project yet and passes ``None``.
    """
```

3. Just before the `for ref in refs:` loop at ~line 320 add:
```python
    project_design_ids: frozenset[str] | None = None
```

4. In the `design_document` branch, after the `CONTEXT_REF_STALE` check and before `continue`:
```python
            if project_id is not None:
                if project_design_ids is None:
                    project_design_ids = frozenset(
                        str(item["id"])
                        for item in await project_design_documents(
                            conn, workspace_id=workspace_id, project_id=project_id
                        )
                    )
                if ref.object_id not in project_design_ids:
                    raise ContextReferenceError(
                        "CONTEXT_REF_NOT_FOUND",
                        "a design document context reference is not in this project",
                    )
            continue
```

5. Add a new branch immediately after the `design_asset` `continue` and before the entity UUID parse:
```python
        if ref.object_type == "project_document":
            # A Gallery file. Always version-pinned to the latest servable row of its path: the
            # picker only offers the latest, and a tag that has since been superseded is refused
            # rather than silently repointed.
            if project_id is None:
                raise ContextReferenceError(
                    "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                    "a project document can be referenced only inside its project",
                )
            try:
                document_id = UUID(ref.object_id)
            except ValueError as exc:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a project document context reference is not available in this project",
                ) from exc
            row = await get_project_document(
                conn, workspace_id=workspace_id, project_id=project_id, document_id=document_id
            )
            if row is None:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a project document context reference is not available in this project",
                )
            if ref.version is None or ref.version != row.version:
                raise ContextReferenceError(
                    "CONTEXT_REF_STALE",
                    "a project document context reference must pin the document's version",
                )
            latest = await latest_project_document_version(
                conn, workspace_id=workspace_id, project_id=project_id, path=row.path
            )
            if latest != row.version:
                raise ContextReferenceError(
                    "CONTEXT_REF_STALE",
                    "a project document context reference no longer names the latest version",
                )
            continue
```

6. `prepare_composer_context_entities` gains `project_id: str | None = None` and passes it through to `validated_context_refs`. Its skip comment becomes "This endpoint hydrates mention-picker entities only. Design and project-document refs can be present on durable messages, but they are presented from their owning read models."

- [ ] **Step 5: Thread `project_id` through the router**

In `platform/api/clue_api/chat/router.py`:
- `_validated_submission_context` gains `project_id: str | None = None` and forwards it.
- Submit route (`:2350-2357`): add `project_id=project_id,`.
- Prepare route (`:1310-1314`): add `project_id=project_id,` to the `prepare_composer_context_entities` call.
- Home bootstrap (`:873-877`): unchanged (no project yet).

- [ ] **Step 6: Run the unit tests**

Same command as Step 2, without `-k`. Expected: whole file PASSES (existing tests unaffected, they pass no `project_id`).

- [ ] **Step 7: DB test against real rows**

Append to `tests/api/test_project_document_context_refs_db.py`:

```python
from clue_api.chat.composer_context import ContextReferenceError, validated_context_refs  # noqa: E402


def test_validated_context_refs_project_document_semantics(
    migrated_db: bool, tmp_path: Path
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            storage = FsStorage(tmp_path)
            seeds = await _seed(conn, storage)
            plan = seeds["plan"]

            def ref(object_id: str, version: int | None) -> DomainObjectRef:
                return DomainObjectRef(
                    workspace_id=seeds["ws"],
                    object_type="project_document",
                    object_id=object_id,
                    version=version,
                )

            accepted = await validated_context_refs(
                conn,
                workspace_id=seeds["ws"],
                refs=(ref(str(plan.document_id), plan.version),),
                project_id=seeds["project_id"],
            )
            assert accepted[0].version == plan.version

            other = await seed_project(conn, seeds["ws"], name="Another project")
            with pytest.raises(ContextReferenceError) as foreign:
                await validated_context_refs(
                    conn,
                    workspace_id=seeds["ws"],
                    refs=(ref(str(plan.document_id), plan.version),),
                    project_id=other.project_id,
                )
            assert foreign.value.code == "CONTEXT_REF_NOT_FOUND"

            newer = await write_project_plan(
                conn,
                storage,
                ProjectPlanWrite(
                    workspace_id=seeds["ws"],
                    brand_id=seeds["brand_id"],
                    project_id=seeds["project_id"],
                    turn_id=uuid4(),
                    user_id="usr_pdref",
                    body=PLAN_BODY + "\nMore.\n",
                    expected_version=plan.version,
                ),
            )
            assert newer.version == plan.version + 1
            with pytest.raises(ContextReferenceError) as stale:
                await validated_context_refs(
                    conn,
                    workspace_id=seeds["ws"],
                    refs=(ref(str(plan.document_id), plan.version),),
                    project_id=seeds["project_id"],
                )
            assert stale.value.code == "CONTEXT_REF_STALE"
            await txn.rollback()

    run_async(scenario())
```

Move the import to the top import block rather than leaving the `noqa`.

- [ ] **Step 8: Run both files, lint, type-check**

Run: `uv run pytest tests/api/test_project_document_context_refs_db.py tests/api/test_chat_composer_context.py -p no:cacheprovider --ignore-glob='*_live.py' -v` (prefix `env -u CLUE_CHAT_REASONING_TRACE_MODE` for the api file). Expected: all PASS. Then `uv run ruff check platform/api/clue_api/chat/composer_context.py platform/api/clue_api/chat/router.py platform/api/clue_api/arv2/project_documents.py` and `uv run mypy platform/api/clue_api/chat/composer_context.py platform/api/clue_api/arv2/project_documents.py`.

- [ ] **Step 9: Commit**

```bash
git add platform/api/clue_api/arv2/project_documents.py platform/api/clue_api/chat/composer_context.py platform/api/clue_api/chat/router.py tests/api/test_chat_composer_context.py tests/api/test_project_document_context_refs_db.py
git commit -m "feat(chat): validate project_document refs against the project's latest servable version and contain design refs to the project"
```

---

### Task 3: The `project_document` focus card

**Files:**
- Modify: `platform/api/clue_api/arv2/project_documents.py` (add `document_title`)
- Modify: `platform/api/clue_api/frontend_read/project_documents.py:131-141` (`_title` delegates)
- Modify: `platform/api/clue_api/account_research_turn_wiring.py:196-330` (new branch)
- Test: `tests/api/test_project_document_context_refs_db.py`

**Interfaces:**
- Consumes: `read_project_document(conn, storage, *, workspace_id, project_id, document_id) -> tuple[ProjectDocumentRow, dict, str] | None`; `workspace_path_of(path)`; `clue_api.arv2.icp_confirmation._title(front, body, *, icp_key)`; `DbCompiledContextCardReader(conn_factory=..., storage=...)`, `CompiledContextCard(ref=DomainObjectRef(...), body=...)`.
- Produces: `def document_title(front: Mapping[str, Any], body: str, *, path: str) -> str` in `arv2/project_documents.py`; a compiled card for `object_type="project_document"` whose body is the JSON below.

- [ ] **Step 1: Write the failing DB test**

Append to `tests/api/test_project_document_context_refs_db.py` (add `import json` and `from clue_api.account_research_turn_wiring import DbCompiledContextCardReader` to the imports; `conn_session_factory` from `tests.profiling.conftest`):

```python
def test_project_document_focus_card_names_the_mounted_path(
    migrated_db: bool, tmp_path: Path
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            storage = FsStorage(tmp_path)
            seeds = await _seed(conn, storage)
            plan = seeds["plan"]
            factory = conn_session_factory(conn)

            with_storage = DbCompiledContextCardReader(conn_factory=factory, storage=storage)
            card = await with_storage.read(
                workspace_id=seeds["ws"],
                object_type="project_document",
                object_id=str(plan.document_id),
            )
            assert card is not None
            assert card.ref.version == plan.version
            body = json.loads(card.body)
            assert body["path"] == "project/plan.md"
            assert body["title"] == "Q4 expansion plan"
            assert body["kind"] == "project-plan"
            assert body["version"] == plan.version
            assert body["document_id"] == str(plan.document_id)
            assert "artifact_key" not in body

            without_storage = DbCompiledContextCardReader(conn_factory=factory)
            bare = await without_storage.read(
                workspace_id=seeds["ws"],
                object_type="project_document",
                object_id=str(plan.document_id),
            )
            assert bare is not None
            assert json.loads(bare.body)["title"] == "plan"

            assert (
                await with_storage.read(
                    workspace_id="ws_someone_else",
                    object_type="project_document",
                    object_id=str(plan.document_id),
                )
                is None
            )
            assert (
                await with_storage.read(
                    workspace_id=seeds["ws"], object_type="project_document", object_id="nope"
                )
                is None
            )
            await txn.rollback()

    run_async(scenario())
```

If `seed_project` writes the plan with a kind other than `project-plan`, assert the kind the row actually carries (read it from `plan` or the table) — the assertion is that the card echoes the row's kind, not a guessed one.

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/api/test_project_document_context_refs_db.py -p no:cacheprovider --ignore-glob='*_live.py' -v -k focus_card`
Expected: FAIL — `card is None` (the reader's `else: return None`).

- [ ] **Step 3: One title helper, shared**

In `platform/api/clue_api/arv2/project_documents.py` add (near `workspace_path_of`):

```python
def document_title(front: Mapping[str, Any], body: str, *, path: str) -> str:
    """What this document is called on screen: front-matter title, first heading, else its file name.

    One rule for every surface that names a project document — the Gallery list, the transcript
    chip, the agent's focus card — so the same file is never called two things.
    """

    from clue_api.arv2.icp_confirmation import _title as titled_by_its_own_text

    name = path.rsplit("/", 1)[-1]
    if name.endswith(".md"):
        name = name[:-3]
    return titled_by_its_own_text(front, body, icp_key=name)
```

(The lazy import mirrors how `frontend_read/project_documents.py` already reaches `_title`; if `icp_confirmation` imports nothing from `project_documents`, make it a top-level import instead.)

In `platform/api/clue_api/frontend_read/project_documents.py` replace `_title`'s body with `return document_title(front, body, path=row.path)` and drop the now-unused `_titled_by_its_own_text` import and `_file_name` if nothing else uses it.

- [ ] **Step 4: The reader branch**

In `platform/api/clue_api/account_research_turn_wiring.py`, inside `DbCompiledContextCardReader.read`, add before the `elif object_type == "contact":` branch:

```python
            elif object_type == "project_document":
                # A Gallery file the user tagged. The card is a typed summary that says WHERE
                # the file is in the agent's workspace — the body already sits under the
                # read-only ``project`` mount — never the body itself (that is the
                # ``brand_knowledge_document`` branch's job for onboarding knowledge).
                from clue_api.arv2.project_documents import (
                    document_title,
                    read_project_document,
                    workspace_path_of,
                )

                try:
                    document_id = UUID(object_id)
                except ValueError:
                    return None
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT document_id, project_id, path, kind, version, status, "
                                "updated_at, artifact_key FROM brand_knowledge_document "
                                "WHERE document_id = :document_id "
                                "  AND workspace_id = :workspace_id "
                                "  AND project_id IS NOT NULL"
                            ),
                            {"document_id": document_id, "workspace_id": workspace_id},
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None or row["artifact_key"] is None:
                    return None
                front: dict[str, Any] = {}
                text_body = ""
                if self._storage is not None:
                    read = await read_project_document(
                        conn,
                        self._storage,
                        workspace_id=workspace_id,
                        project_id=str(row["project_id"]),
                        document_id=document_id,
                    )
                    if read is not None:
                        _, front, text_body = read
                value = None
                body = json.dumps(
                    {
                        "document_id": str(row["document_id"]),
                        "path": workspace_path_of(str(row["path"])),
                        "title": document_title(front, text_body, path=str(row["path"])),
                        "kind": row["kind"],
                        "version": int(row["version"]),
                        "status": row["status"],
                        "updated_at": row["updated_at"].isoformat(),
                    },
                    sort_keys=True,
                )
                version = int(row["version"])
```

Check the module already imports `text` from `sqlalchemy`, `json`, `UUID`, and `Any`; add what is missing. Update the class docstring line about storage: "Only the `brand_knowledge_document` and `project_document` types use blob bytes (the latter only for the title)…".

- [ ] **Step 5: Run the test file and gates**

Run: `uv run pytest tests/api/test_project_document_context_refs_db.py tests/api/test_frontend_read_project_documents_db.py -p no:cacheprovider --ignore-glob='*_live.py' -v`. Expected: all PASS (the frontend-read titles are unchanged by the delegation). Then `uv run ruff check` and `uv run mypy` on the three modified modules.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/project_documents.py platform/api/clue_api/frontend_read/project_documents.py platform/api/clue_api/account_research_turn_wiring.py tests/api/test_project_document_context_refs_db.py
git commit -m "feat(context): compile a project_document focus card naming the file's mounted path, title and version"
```

---

### Task 4: Transcript echo carries a label and kind for files and design documents

**Files:**
- Modify: `platform/api/clue_api/chat/composer_context.py:480-519` (generalise), `__all__` at `:35`
- Modify: `platform/api/clue_api/chat/router.py:76, 1499-1524`
- Modify: `platform/api/clue_api/chat/stream.py:310-343`
- Test: `tests/api/test_chat_composer_context.py`

**Interfaces:**
- Consumes: `design_asset_ref_presentations(conn, *, workspace_id, refs) -> dict[tuple[str, str], dict[str, str]]` (renamed here); `read_project_document`, `document_title`; `message_list_response(page, thread_id=, bodies=, ref_presentations=)`.
- Produces: `async def context_ref_presentations(conn, *, workspace_id: str, refs: Sequence[Any], storage: StorageBackend | None = None) -> dict[tuple[str, str], dict[str, str]]`; `PRESENTED_REF_TYPES = frozenset({"design_asset", "design_document", "project_document"})`. Echoed refs of the two new types carry `label` and `kind`.

- [ ] **Step 1: Unit test**

Append to `tests/api/test_chat_composer_context.py`:

```python
def test_context_ref_presentations_label_files_and_design_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from clue_api.chat.composer_context import context_ref_presentations

    async def project_document_rows(*_args: object, **_kwargs: object):
        return {
            str(PLAN_DOCUMENT): SimpleNamespace(
                document_id=PLAN_DOCUMENT, project_id="prj_1", path="project/plan.md",
                kind="project-plan",
            )
        }

    async def design_document_rows(*_args: object, **_kwargs: object):
        return {"doc_site": {"id": "doc_site", "title": "Spring launch page", "doc_kind": "web"}}

    async def read_project_document(*_args: object, **_kwargs: object):
        return (None, {"title": "Q4 expansion plan"}, "# ignored\n")

    monkeypatch.setattr(composer_context, "_project_document_rows", project_document_rows)
    monkeypatch.setattr(composer_context, "_design_document_rows", design_document_rows)
    monkeypatch.setattr(composer_context, "read_project_document", read_project_document)

    refs = (
        _ref("project_document", PLAN_DOCUMENT, version=2),
        _design_ref("design_document", "doc_site", version=4),
        _ref("account", ACCOUNT_A),
    )
    presentations = asyncio.run(
        context_ref_presentations(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=refs,
            storage=object(),  # type: ignore[arg-type]
        )
    )
    assert presentations[("project_document", str(PLAN_DOCUMENT))] == {
        "label": "Q4 expansion plan",
        "kind": "project-plan",
    }
    assert presentations[("design_document", "doc_site")] == {
        "label": "Spring launch page",
        "kind": "web",
    }
    assert ("account", str(ACCOUNT_A)) not in presentations

    no_storage = asyncio.run(
        context_ref_presentations(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=refs[:1],
        )
    )
    assert no_storage[("project_document", str(PLAN_DOCUMENT))]["label"] == "plan"
```

- [ ] **Step 2: Run it to see it fail**

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_chat_composer_context.py -p no:cacheprovider --ignore-glob='*_live.py' -v -k presentations`
Expected: FAIL with `ImportError` (`context_ref_presentations`).

- [ ] **Step 3: Generalise the presentation read**

In `composer_context.py`, rename `design_asset_ref_presentations` to `context_ref_presentations` with this shape (keep the design-asset body as the first block, verbatim):

```python
PRESENTED_REF_TYPES = frozenset({"design_asset", "design_document", "project_document"})


async def _project_document_rows(
    conn: AsyncConnection, *, workspace_id: str, document_ids: Sequence[UUID]
) -> dict[str, Any]:
    rows = (
        await conn.execute(
            text(
                "SELECT document_id, project_id, path, kind FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id "
                "  AND document_id = ANY(CAST(:ids AS uuid[])) AND project_id IS NOT NULL"
            ),
            {"workspace_id": workspace_id, "ids": [str(value) for value in document_ids]},
        )
    ).mappings()
    return {str(row["document_id"]): row for row in rows}


async def _design_document_rows(
    conn: AsyncConnection, *, workspace_id: str, document_ids: Sequence[str]
) -> dict[str, Any]:
    rows = (
        await conn.execute(
            text(
                "SELECT id, title, doc_kind FROM design_document "
                "WHERE workspace_id = :workspace_id AND id = ANY(:ids)"
            ),
            {"workspace_id": workspace_id, "ids": list(document_ids)},
        )
    ).mappings()
    return {str(row["id"]): row for row in rows}


async def context_ref_presentations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[Any],
    storage: StorageBackend | None = None,
) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve durable refs to read-time labels: asset filenames, file titles, design titles.

    The append-only submission row remains the source of *which* object was submitted. Mutable
    presentation metadata (a filename, a document's own title) is joined only while reading the
    transcript, so nothing user-facing is denormalized into the durable turn receipt — and no
    path or id is ever the label.
    """

    result: dict[tuple[str, str], dict[str, str]] = {}

    asset_ids = tuple(
        dict.fromkeys(str(ref.object_id) for ref in refs if ref.object_type == "design_asset")
    )
    if asset_ids:
        # (existing design-asset body, unchanged, filling ``result``)
        ...

    document_ids: list[UUID] = []
    for ref in refs:
        if ref.object_type != "project_document":
            continue
        try:
            document_ids.append(UUID(str(ref.object_id)))
        except ValueError:
            continue
    if document_ids:
        rows = await _project_document_rows(
            conn, workspace_id=workspace_id, document_ids=tuple(dict.fromkeys(document_ids))
        )
        for document_id, row in rows.items():
            front: Mapping[str, Any] = {}
            body = ""
            if storage is not None:
                read = await read_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=str(row["project_id"]),
                    document_id=UUID(document_id),
                )
                if read is not None:
                    _, front, body = read
            result[("project_document", document_id)] = {
                "label": document_title(front, body, path=str(row["path"])),
                "kind": str(row["kind"]),
            }

    design_ids = tuple(
        dict.fromkeys(str(ref.object_id) for ref in refs if ref.object_type == "design_document")
    )
    if design_ids:
        rows = await _design_document_rows(conn, workspace_id=workspace_id, document_ids=design_ids)
        for design_id, row in rows.items():
            result[("design_document", design_id)] = {
                "label": str(row["title"] or "Design"),
                "kind": "web" if row["doc_kind"] == "web" else "ad",
            }
    return result
```

Imports: `from clue_api.arv2.project_documents import document_title, read_project_document` (module-level, alongside the Task 2 imports), `from sqlalchemy import text`, `Mapping` from `collections.abc`. Update `__all__` (`context_ref_presentations`, drop the old name).

- [ ] **Step 4: Callers**

`router.py`: import `context_ref_presentations` and `PRESENTED_REF_TYPES`; at `:1500` replace `has_design_assets` with `has_presented = any(ref.object_type in PRESENTED_REF_TYPES for ref in all_refs)`; call `context_ref_presentations(conn, workspace_id=who.workspace_id, refs=all_refs, storage=storage)`.

`stream.py` (live turn list, `:310-343`): after `context_by_turn` is read, compute
```python
                presentations = await context_ref_presentations(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=tuple(ref for refs in context_by_turn.values() for ref in refs),
                    storage=storage,
                )
```
and in the `"refs"` comprehension build each dict then `| presentations.get((ref.object_type, ref.object_id), {})`.

- [ ] **Step 5: Run and gate**

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_chat_composer_context.py tests/api/test_lane_d2_turn_submission_db.py tests/projections/test_thread_shell_db.py -p no:cacheprovider --ignore-glob='*_live.py' -v`. Expected: PASS. `uv run ruff check` + `uv run mypy` on `composer_context.py`, `router.py`, `stream.py`.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/chat/composer_context.py platform/api/clue_api/chat/router.py platform/api/clue_api/chat/stream.py tests/api/test_chat_composer_context.py
git commit -m "feat(chat): echo a title and kind on project_document and design_document context refs"
```

---

### Task 5: Frontend model — typed entities, the catalog builder, and search

**Files:**
- Modify: `apps/frontend/src/features/projects/model/project-workspace.ts:9-17, 90-115`
- Modify: `apps/frontend/src/features/projects/model/project-composer.ts:16-25`
- Modify: `apps/frontend/src/features/projects/model/project-composer-editor.ts:16-29`
- Modify: `apps/frontend/src/features/projects/model/chat-context-handoff.ts:8-12`
- Modify: `apps/frontend/src/features/projects/model/chat-turn.ts:225-236`
- Modify: `apps/frontend/src/features/projects/model/chat-message.ts:27-49, 107-117`
- Modify: `apps/frontend/src/features/design-editor/adapter/gallery.ts:71-90`
- Create: `apps/frontend/src/features/projects/model/composer-context-catalog.ts`
- Test: `apps/frontend/src/features/projects/model/composer-context-catalog.test.ts`

**Interfaces:**
- Consumes: `ProjectDocument` (`id, path, kind, title, version, status, updatedAt, icpKey`) and `documentKindLabel(kind)` from `./project-documents`; `ProjectArtifact` (`id, title, type: table|website|canvas|presentation, collateralType?`) from `./project-workspace`; `DesignArtifactListItem.documentId`, `.currentVersionId`.
- Produces (all exported from `composer-context-catalog.ts`):
  - `type ComposerCategory = "files" | "microsites" | "accounts"`
  - `const COMPOSER_CATEGORIES: readonly { key: ComposerCategory; label: string; empty: string }[]` (labels `Files` / `Microsites` / `Accounts`; empties verbatim from Global Constraints)
  - `function entityCategory(entity: ProjectEntity): ComposerCategory`
  - `function buildComposerCatalog(input: { documents: readonly ProjectDocument[]; artifacts: readonly ProjectArtifact[]; entities: readonly ProjectEntity[] }): ProjectEntity[]`
  - `function searchComposerCatalog(catalog: readonly ProjectEntity[], query: string): ProjectEntity[]`
  - `function composerCategoryCounts(catalog: readonly ProjectEntity[]): Record<ComposerCategory, number>`
  - `const MENTION_QUERY_MAX = 60`
  - `function detectMentionQuery(beforeText: string): string | null`
  - `function shouldAutoCloseMention(query: string, matchCount: number): boolean`
- Schema changes: `ProjectEntitySchema.type` = `account | contact | project_document | design_document`; new optional `category`, `icon` (`file-text | image | web`), `imagePath` becomes optional; `ProjectArtifactSchema` gains optional `documentId` (min 1) and `version` (positive int); `ChatContextRefSchema.objectType` = the same four; `TurnContextObjectType` adds `project_document`; `MessageRefWireSchema` gains `kind: z.string().nullable().default(null)` mapped to `ChatMessageRef.kind`; `ProjectComposerMentionElement` gains `version?: number | null`, `icon?: "file-text" | "image" | "web"`, `imagePath?: string`, and `entityType: ProjectEntity["type"]`.

- [ ] **Step 1: Write the failing tests**

Create `apps/frontend/src/features/projects/model/composer-context-catalog.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import {
  buildComposerCatalog,
  composerCategoryCounts,
  detectMentionQuery,
  entityCategory,
  searchComposerCatalog,
  shouldAutoCloseMention,
} from "./composer-context-catalog";
import type { ProjectDocument } from "./project-documents";
import type { ProjectArtifact, ProjectEntity } from "./project-workspace";

const plan: ProjectDocument = {
  id: "doc-plan",
  path: "project/plan.md",
  kind: "project-plan",
  title: "Q4 expansion plan",
  version: 3,
  status: "ready",
  updatedAt: "2026-09-17T10:00:00+00:00",
  icpKey: null,
};
const site: ProjectArtifact = {
  documentId: "design-site",
  editedLabel: "Edited today",
  id: "design-site",
  originThreadId: "thr_1",
  title: "Spring launch page",
  type: "website",
  version: 4,
};
const ad: ProjectArtifact = {
  collateralType: "linkedin-ad",
  documentId: "design-ad",
  editedLabel: "Edited today",
  id: "design-ad",
  originThreadId: "thr_1",
  title: "GI North ad",
  type: "canvas",
  version: 2,
};
const table: ProjectArtifact = {
  editedLabel: "Edited today",
  id: "table-1",
  originThreadId: "thr_1",
  title: "Target accounts",
  type: "table",
};
const account: ProjectEntity = {
  id: "acct-1",
  imagePath: "/logos/clue.svg",
  label: "Lane Regional Medical Center",
  secondaryLabel: "lanermc.org",
  type: "account",
  version: 5,
};

test("the catalog puts documents and ads under files, web documents under microsites", () => {
  const catalog = buildComposerCatalog({
    documents: [plan],
    artifacts: [site, ad, table],
    entities: [account],
  });
  assert.deepEqual(
    catalog.map((entity) => [entity.id, entityCategory(entity), entity.type, entity.version]),
    [
      ["doc-plan", "files", "project_document", 3],
      ["design-ad", "files", "design_document", 2],
      ["design-site", "microsites", "design_document", 4],
      ["acct-1", "accounts", "account", 5],
    ],
  );
  const file = catalog[0]!;
  assert.equal(file.label, "Q4 expansion plan");
  assert.equal(file.secondaryLabel, "Plan");
  assert.equal(file.icon, "file-text");
  assert.equal(catalog[1]!.secondaryLabel, "LinkedIn ad");
  assert.equal(catalog[1]!.icon, "image");
  assert.equal(catalog[2]!.secondaryLabel, "Microsite");
  assert.equal(catalog[2]!.icon, "web");
  assert.deepEqual(composerCategoryCounts(catalog), { files: 2, microsites: 1, accounts: 1 });
  for (const entity of catalog) {
    assert.equal(JSON.stringify(entity).includes("project/plan.md"), false);
  }
});

test("an artifact without a design document id or a positive version is not offered", () => {
  const catalog = buildComposerCatalog({
    documents: [],
    artifacts: [{ ...site, documentId: undefined }, { ...ad, version: undefined }],
    entities: [],
  });
  assert.deepEqual(catalog, []);
});

test("search runs across every category and keeps category order", () => {
  const catalog = buildComposerCatalog({
    documents: [plan],
    artifacts: [site, ad],
    entities: [account],
  });
  assert.deepEqual(
    searchComposerCatalog(catalog, "lan").map((entity) => entity.id),
    ["doc-plan", "design-site", "acct-1"],
  );
  assert.deepEqual(searchComposerCatalog(catalog, "  "), []);
  assert.deepEqual(searchComposerCatalog(catalog, "north ad").map((e) => e.id), ["design-ad"]);
});

test("the mention query allows spaces, stops at a second @, and is capped", () => {
  assert.equal(detectMentionQuery("hello @Project plan"), "Project plan");
  assert.equal(detectMentionQuery("@"), "");
  assert.equal(detectMentionQuery("email me@example.com"), null);
  assert.equal(detectMentionQuery("@a @b"), "b");
  assert.equal(detectMentionQuery(`@${"x".repeat(61)}`), null);
  assert.equal(shouldAutoCloseMention("meet ", 0), true);
  assert.equal(shouldAutoCloseMention("meet", 0), false);
  assert.equal(shouldAutoCloseMention("meet ", 2), false);
});
```

- [ ] **Step 2: Run to see it fail**

From `apps/frontend`: `npx tsx --test src/features/projects/model/composer-context-catalog.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Widen the schemas**

`project-workspace.ts`:
```ts
export const ProjectEntityTypeSchema = z.enum([
  "account",
  "contact",
  "project_document",
  "design_document",
]);
export const ProjectEntityCategorySchema = z.enum(["accounts", "files", "microsites"]);
export const ProjectEntityIconSchema = z.enum(["file-text", "image", "web"]);

export const ProjectEntitySchema = z.object({
  accountName: z.string().optional(),
  // Absent means the legacy account/contact catalog served by the backend.
  category: ProjectEntityCategorySchema.optional(),
  icon: ProjectEntityIconSchema.optional(),
  id: z.string().min(1),
  imagePath: z.string().startsWith("/").optional(),
  label: z.string().min(1),
  secondaryLabel: z.string().min(1),
  type: ProjectEntityTypeSchema,
  version: z.number().int().positive().nullable().optional(),
});
```
`ProjectArtifactSchema` gains:
```ts
  // The design document behind a design artifact, and its current version — what a
  // composer tag of this artifact sends. Absent on table/presentation cards.
  documentId: z.string().min(1).optional(),
  version: z.number().int().positive().optional(),
```

`gallery.ts::toProjectArtifact` adds, inside the parsed object:
```ts
    documentId: item.documentId,
    ...(versionOf(item.currentVersionId) ? { version: versionOf(item.currentVersionId) } : {}),
```
with
```ts
function versionOf(currentVersionId: string): number | undefined {
  const value = Number(currentVersionId);
  return Number.isInteger(value) && value > 0 ? value : undefined;
}
```

`chat-context-handoff.ts`: `objectType: ProjectEntityTypeSchema` (import it). `chat-turn.ts`: add `| "project_document"` to `TurnContextObjectType`. `chat-message.ts`: add `kind: z.string().nullable().default(null)` to the wire schema, `kind: string | null` to `ChatMessageRef`, `kind: ref.kind` in `toChatMessage`.

`project-composer.ts`:
```ts
export interface ProjectComposerMentionElement {
  accountName?: string;
  children: [{ text: "" }];
  entityId: string;
  entityType: ProjectEntity["type"];
  icon?: ProjectEntity["icon"];
  imagePath?: string;
  label: string;
  secondaryLabel: string;
  type: "mention";
  version?: number | null;
}
```
(import `type ProjectEntity` from `./project-workspace`). `project-composer-editor.ts::createComposerMention` copies `icon`, `imagePath`, `version` as well.

- [ ] **Step 4: The catalog module**

Create `apps/frontend/src/features/projects/model/composer-context-catalog.ts`:

```ts
import { documentKindLabel, type ProjectDocument } from "./project-documents";
import type {
  GalleryCollateralType,
  ProjectArtifact,
  ProjectEntity,
} from "./project-workspace";

export type ComposerCategory = "files" | "microsites" | "accounts";

export const COMPOSER_CATEGORIES: readonly {
  key: ComposerCategory;
  label: string;
  empty: string;
}[] = [
  { key: "files", label: "Files", empty: "No files in the Gallery yet" },
  { key: "microsites", label: "Microsites", empty: "No microsites yet" },
  { key: "accounts", label: "Accounts", empty: "No accounts yet" },
];

export const MENTION_QUERY_MAX = 60;

const COLLATERAL_LABELS: Record<GalleryCollateralType, string> = {
  "account-list": "Account list",
  "direct-mail": "Direct mail",
  "linkedin-ad": "LinkedIn ad",
  "meta-ad": "Meta ad",
  microsite: "Microsite",
  presentation: "Presentation",
  report: "Report",
};

export function entityCategory(entity: ProjectEntity): ComposerCategory {
  return entity.category ?? "accounts";
}

function byLabel(left: ProjectEntity, right: ProjectEntity) {
  return left.label.localeCompare(right.label);
}

/**
 * The picker's whole catalog, built from the same feeds the Gallery renders. The Gallery is
 * the file system: nothing appears here that is not a Gallery card, and no card carries a
 * path or an id into a label.
 */
export function buildComposerCatalog({
  documents,
  artifacts,
  entities,
}: {
  documents: readonly ProjectDocument[];
  artifacts: readonly ProjectArtifact[];
  entities: readonly ProjectEntity[];
}): ProjectEntity[] {
  const files: ProjectEntity[] = documents.map((document) => ({
    category: "files",
    icon: "file-text",
    id: document.id,
    label: document.title,
    secondaryLabel: documentKindLabel(document.kind),
    type: "project_document",
    version: document.version,
  }));
  const ads: ProjectEntity[] = [];
  const microsites: ProjectEntity[] = [];
  for (const artifact of artifacts) {
    if (!artifact.documentId || !artifact.version) continue;
    if (artifact.type === "website") {
      microsites.push({
        category: "microsites",
        icon: "web",
        id: artifact.documentId,
        label: artifact.title,
        secondaryLabel: "Microsite",
        type: "design_document",
        version: artifact.version,
      });
    } else if (artifact.type === "canvas") {
      ads.push({
        category: "files",
        icon: "image",
        id: artifact.documentId,
        label: artifact.title,
        secondaryLabel: artifact.collateralType
          ? COLLATERAL_LABELS[artifact.collateralType]
          : "Ad",
        type: "design_document",
        version: artifact.version,
      });
    }
  }
  return [
    ...files.sort(byLabel),
    ...ads.sort(byLabel),
    ...microsites.sort(byLabel),
    ...entities.map((entity) => ({ ...entity, category: "accounts" as const })),
  ];
}

export function composerCategoryCounts(
  catalog: readonly ProjectEntity[],
): Record<ComposerCategory, number> {
  const counts = { files: 0, microsites: 0, accounts: 0 };
  for (const entity of catalog) counts[entityCategory(entity)] += 1;
  return counts;
}

/** Typing searches every category at once; the catalog's category order is kept. */
export function searchComposerCatalog(
  catalog: readonly ProjectEntity[],
  query: string,
): ProjectEntity[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [];
  return catalog.filter((entity) =>
    `${entity.label} ${entity.secondaryLabel} ${entity.accountName ?? ""}`
      .toLocaleLowerCase()
      .includes(needle),
  );
}

/**
 * The text after an `@` that starts a word, up to the caret. Spaces are allowed so a title
 * like "Project plan" can be typed; a second `@` starts a new query; an over-long query is no
 * query (the user is writing prose).
 */
export function detectMentionQuery(beforeText: string): string | null {
  const match = beforeText.match(/(?:^|\s)@([^@\n]*)$/);
  if (!match) return null;
  const query = match[1] ?? "";
  return query.length > MENTION_QUERY_MAX ? null : query;
}

/** Prose recovers by itself: a query that matches nothing and just gained a space closes the picker. */
export function shouldAutoCloseMention(query: string, matchCount: number): boolean {
  return matchCount === 0 && query.endsWith(" ");
}
```

Check `GalleryCollateralType` is exported from `project-workspace.ts` (the schema is `GalleryCollateralTypeSchema` at `:66`); export the inferred type if it is not. `Record<GalleryCollateralType, string>` is deliberate: a new collateral type fails to compile until it has a label.

- [ ] **Step 5: Run the tests and the type-check**

`npx tsx --test src/features/projects/model/composer-context-catalog.test.ts` → PASS. Then `npm test` (all model tests; the existing `project-composer-editor.test.ts`, `chat-context-handoff.test.ts`, `chat-schemas.test.ts`, `gallery.test.ts` must still pass) and `npx tsc --noEmit -p .` (only the three known pre-existing errors).

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/features/projects/model apps/frontend/src/features/design-editor/adapter/gallery.ts
git commit -m "feat(frontend): typed composer entities, the file/microsite/account catalog and cross-category search"
```

---

### Task 6: Wire the catalog into the composer and the transcript

**Files:**
- Modify: `apps/frontend/src/features/projects/hooks/use-project-workspace-controller.ts:63-90, 160-215`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (near `:257` documents, `:334` `feedArtifacts`, `:546` `<ConversationContent`, `:618` `entities=`, `:661-670` send path)
- Modify: `apps/frontend/src/features/projects/components/conversation-content.tsx:33-45, 113`

**Interfaces:**
- Consumes: `useProjectDocuments(projectId, { active, refreshToken })` → `{ documents, ... }`; `buildComposerCatalog`; `mergeComposerContextEntities`.
- Produces: `controller.setCatalogEntities(entities: ProjectEntity[])`; `controller.composerEntities` now = catalog ∪ workspace entities ∪ selection; `ConversationContent` prop `contextEntities: ProjectEntity[]`.

- [ ] **Step 1: Controller**

In `use-project-workspace-controller.ts` add `const [catalogEntities, setCatalogEntities] = useState<ProjectEntity[]>([]);` and change:
```ts
  const composerEntities = useMemo(
    () =>
      mergeComposerContextEntities(
        mergeComposerContextEntities(workspace.entities, catalogEntities),
        selectedEntities,
      ),
    [catalogEntities, selectedEntities, workspace.entities],
  );
```
Expose `setCatalogEntities` on the returned object (alphabetical position, next to `selectEntity`).

- [ ] **Step 2: Chat surface**

In `chat-surface.tsx`:
```ts
  // The composer's Files and Microsites come from the same feeds the Gallery draws. The
  // document list is fetched here unconditionally (the tabs hook fetches only while a
  // panel is open) and re-read when this thread writes a document.
  const composerDocuments = useProjectDocuments(projectId, {
    active: true,
    refreshToken: chat.planWriteRevision,
  });
  const composerCatalog = useMemo(
    () =>
      buildComposerCatalog({
        documents: composerDocuments.documents,
        artifacts: feedArtifacts,
        entities: workspace.entities,
      }),
    [composerDocuments.documents, feedArtifacts, workspace.entities],
  );
  const { setCatalogEntities } = controller;
  useEffect(() => {
    setCatalogEntities(composerCatalog);
  }, [composerCatalog, setCatalogEntities]);
```
Place it after `feedArtifacts` is defined (`:334`). Imports: `useProjectDocuments` from `@/features/projects/hooks/use-project-documents`, `buildComposerCatalog` from `@/features/projects/model/composer-context-catalog`.

Pass `contextEntities={controller.composerEntities}` to `<ConversationContent … />` at `:546`. The send path at `:661-670` needs no change: `entity.type` and `entity.version` already flow into `objectType`/`version`.

- [ ] **Step 3: Conversation content**

Add `contextEntities: ProjectEntity[]` to `ConversationContent`'s props and pass it to `<ChatTranscript contextEntities={contextEntities} …/>` instead of `workspace.entities`. Import `type ProjectEntity`.

- [ ] **Step 4: Type-check and build**

From `apps/frontend`: `npx tsc --noEmit -p .` (known errors only) and `npm run lint`. Then start or reuse the lane frontend on port 3020 and, in a project with documents, confirm in the browser that typing `@` then a document title's first word lists the document (Task 7 adds the categories; before it, the flat list already shows files because the catalog feeds the existing picker).

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/projects/hooks/use-project-workspace-controller.ts apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/projects/components/conversation-content.tsx
git commit -m "feat(frontend): feed the composer catalog with Gallery files and microsites and resolve transcript chips from it"
```

---

### Task 7: The two-level picker

**Files:**
- Rewrite: `apps/frontend/src/features/projects/components/entity-picker.tsx`
- Modify: `apps/frontend/src/features/projects/components/project-composer-editor.tsx:121-145, 160-176, 205-247, 249-270, 378-433, 440-458`
- Modify: `apps/frontend/src/features/projects/components/project-composer.tsx:183-195` and the `<ProjectComposerEditor>` render (pass `categoriesEnabled`)
- Modify: `apps/frontend/src/features/projects/components/project-flow.module.css` (after `.entityPickerEmpty`, ~`:435`)

**Interfaces:**
- Consumes: `COMPOSER_CATEGORIES`, `composerCategoryCounts`, `searchComposerCatalog`, `entityCategory`, `detectMentionQuery`, `shouldAutoCloseMention`, `ComposerCategory`.
- Produces: `EntityPicker` props
  ```ts
  {
    activeId?: string;                 // id of the active option row
    activeCategory?: ComposerCategory; // active category row while browsing
    categoriesEnabled: boolean;        // false on Home: flat accounts list as today
    catalog: ProjectEntity[];
    category: ComposerCategory | null; // opened category, or null for the category rows
    onActiveChange?: (entityId: string) => void;
    onBack: () => void;
    onOpenCategory: (category: ComposerCategory) => void;
    onSelect: (entityId: string) => void;
    query: string;
    results: ProjectEntity[];          // what the editor computed as visible
    selectedIds: string[];
  }
  ```
  `ProjectComposerEditor` prop `categoriesEnabled?: boolean` (default `true`); `ProjectComposer` passes `categoriesEnabled={variant !== "home"}`.

- [ ] **Step 1: Editor state and visibility**

In `project-composer-editor.tsx`:
1. Add prop `categoriesEnabled = true`.
2. Add state `const [mentionCategory, setMentionCategory] = useState<ComposerCategory | null>(null);` and reset it in `closeMentionPicker`.
3. Replace `visibleEntities`:
```ts
  const query = mentionQuery.trim();
  const visibleEntities = useMemo(() => {
    if (!categoriesEnabled) {
      const accounts = entities.filter((entity) => entityCategory(entity) === "accounts");
      return query ? searchComposerCatalog(accounts, query) : accounts;
    }
    if (query) return searchComposerCatalog(entities, query);
    if (mentionCategory) {
      return entities.filter((entity) => entityCategory(entity) === mentionCategory);
    }
    return [];
  }, [categoriesEnabled, entities, mentionCategory, query]);
  const browsingCategories = categoriesEnabled && !query && mentionCategory === null;
```
4. In `detectMentionTarget`, replace the regex block with:
```ts
    const mentionQueryText = detectMentionQuery(beforeText);
    if (mentionQueryText === null) {
      closeMentionPicker();
      return;
    }
    const mentionText = `@${mentionQueryText}`;
```
and keep the rest. After `setMentionQuery(mentionQueryText)`, if the query is non-empty and the category was open, keep it (typing inside a category still searches everywhere; that is the ruling).
5. Auto-close: add
```ts
  useEffect(() => {
    if (!mentionTarget) return;
    if (shouldAutoCloseMention(mentionQuery, visibleEntities.length)) closeMentionPicker();
  }, [closeMentionPicker, mentionQuery, mentionTarget, visibleEntities.length]);
```
6. Keyboard, inside `if (mentionTarget) {`, before the existing ArrowDown branch:
```ts
              if (browsingCategories) {
                const categories = COMPOSER_CATEGORIES;
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  const step = event.key === "ArrowDown" ? 1 : categories.length - 1;
                  setActiveIndex((current) => (current + step) % categories.length);
                  return;
                }
                if (event.key === "Enter" || event.key === "Tab" || event.key === "ArrowRight") {
                  event.preventDefault();
                  setMentionCategory(categories[activeIndex]?.key ?? "files");
                  setActiveIndex(0);
                  return;
                }
              } else if (mentionCategory && !query && event.key === "ArrowLeft") {
                event.preventDefault();
                setMentionCategory(null);
                setActiveIndex(COMPOSER_CATEGORIES.findIndex((c) => c.key === mentionCategory));
                return;
              }
```
The existing ArrowUp/Down/Enter/Tab/Escape branches then apply to option rows.
7. Render:
```tsx
      {mentionTarget ? (
        <EntityPicker
          activeCategory={browsingCategories ? COMPOSER_CATEGORIES[activeIndex]?.key : undefined}
          activeId={browsingCategories ? undefined : visibleEntities[activeIndex]?.id}
          catalog={entities}
          categoriesEnabled={categoriesEnabled}
          category={mentionCategory}
          onActiveChange={(entityId) => { /* unchanged */ }}
          onBack={() => { setMentionCategory(null); setActiveIndex(0); }}
          onOpenCategory={(category) => { setMentionCategory(category); setActiveIndex(0); }}
          onSelect={(entityId) => { /* unchanged */ }}
          query={mentionQuery}
          results={visibleEntities}
          selectedIds={mentionIds}
        />
      ) : null}
```
`insertMention` is unchanged except that `createComposerMention(entity)` now carries `version`/`icon` (Task 5).

- [ ] **Step 2: The picker**

Rewrite `entity-picker.tsx`:

```tsx
import Image from "next/image";
import {
  COMPOSER_CATEGORIES,
  composerCategoryCounts,
  entityCategory,
  type ComposerCategory,
} from "../model/composer-context-catalog";
import type { ProjectEntity } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

function EntityVisual({ entity }: { entity: ProjectEntity }) {
  if (entity.icon) {
    return (
      <span aria-hidden="true" className={styles.entityIcon}>
        <ProjectIcon name={entity.icon} size={16} />
      </span>
    );
  }
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={entity.type === "contact" ? styles.entityAvatar : styles.entityLogo}
      height={24}
      src={entity.imagePath ?? "/logos/clue.svg"}
      width={24}
    />
  );
}

function Option({
  active,
  entity,
  onActiveChange,
  onSelect,
  selected,
}: {
  active: boolean;
  entity: ProjectEntity;
  onActiveChange?: (entityId: string) => void;
  onSelect: (entityId: string) => void;
  selected: boolean;
}) {
  return (
    <button
      aria-selected={selected}
      className={styles.entityOption}
      data-active={active ? "true" : "false"}
      onMouseDown={(event) => event.preventDefault()}
      onMouseEnter={() => onActiveChange?.(entity.id)}
      onClick={() => onSelect(entity.id)}
      role="option"
      type="button"
    >
      <EntityVisual entity={entity} />
      <span>
        <strong>{entity.label}</strong>
        <small>
          {entity.secondaryLabel}
          {entity.accountName ? ` | ${entity.accountName}` : ""}
        </small>
      </span>
      {selected ? <ProjectIcon name="status-check" size={14} /> : null}
    </button>
  );
}

export function EntityPicker({
  activeCategory,
  activeId,
  catalog,
  categoriesEnabled,
  category,
  onActiveChange,
  onBack,
  onOpenCategory,
  onSelect,
  query,
  results,
  selectedIds,
}: {
  activeCategory?: ComposerCategory;
  activeId?: string;
  catalog: ProjectEntity[];
  categoriesEnabled: boolean;
  category: ComposerCategory | null;
  onActiveChange?: (entityId: string) => void;
  onBack: () => void;
  onOpenCategory: (category: ComposerCategory) => void;
  onSelect: (entityId: string) => void;
  query: string;
  selectedIds: string[];
  results: ProjectEntity[];
}) {
  const searching = query.trim().length > 0;
  const counts = composerCategoryCounts(catalog);

  if (categoriesEnabled && !searching && category === null) {
    return (
      <div aria-label="Choose context" className={styles.entityPicker} role="listbox">
        {COMPOSER_CATEGORIES.map((item) => (
          <button
            className={styles.pickerCategory}
            data-active={activeCategory === item.key ? "true" : "false"}
            key={item.key}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onOpenCategory(item.key)}
            role="option"
            aria-selected={false}
            type="button"
          >
            <span>{item.label}</span>
            <small>{counts[item.key]}</small>
            <ProjectIcon name="chevron-right" size={14} />
          </button>
        ))}
      </div>
    );
  }

  const groups = searching
    ? COMPOSER_CATEGORIES.filter((item) => results.some((e) => entityCategory(e) === item.key))
    : COMPOSER_CATEGORIES.filter((item) => item.key === (category ?? "accounts"));
  const emptyCopy = searching
    ? "No matches"
    : COMPOSER_CATEGORIES.find((item) => item.key === (category ?? "accounts"))?.empty;

  return (
    <div aria-label="Choose context" className={styles.entityPicker} role="listbox">
      {categoriesEnabled && !searching && category !== null ? (
        <button
          className={styles.pickerBack}
          onMouseDown={(event) => event.preventDefault()}
          onClick={onBack}
          type="button"
        >
          <ProjectIcon name="chevron-right" size={14} />
          Back
        </button>
      ) : null}
      {groups.map((item) => (
        <section key={item.key}>
          {searching || !categoriesEnabled ? (
            <p className={styles.pickerLabel}>
              {categoriesEnabled ? item.label : "Accounts"}
            </p>
          ) : null}
          {results
            .filter((entity) => entityCategory(entity) === item.key)
            .map((entity) => (
              <Option
                active={activeId === entity.id}
                entity={entity}
                key={entity.id}
                onActiveChange={onActiveChange}
                onSelect={onSelect}
                selected={selectedIds.includes(entity.id)}
              />
            ))}
        </section>
      ))}
      {results.length === 0 ? <p className={styles.entityPickerEmpty}>{emptyCopy}</p> : null}
    </div>
  );
}
```

The old `showSearch`/`onQueryChange` props are dropped (the only consumer passed `showSearch={false}`); remove the `.pickerSearch` rules only if no other selector references them (the Home variant does, at `:504`; leave CSS in place).

- [ ] **Step 3: CSS**

After `.entityPickerEmpty` add:
```css
.pickerCategory {
  display: flex;
  width: 100%;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 6px 8px;
  font-size: 14px;
  text-align: left;
}

.pickerCategory > span {
  flex: 1 1 auto;
}

.pickerCategory > small {
  color: var(--clue-ds-color-content-subtle);
  font-size: 12px;
}

.pickerCategory:hover,
.pickerCategory[data-active="true"] {
  background: var(--clue-ds-color-bg-page);
}

.pickerBack {
  display: flex;
  align-items: center;
  gap: 4px;
  border: 0;
  background: transparent;
  color: var(--clue-ds-color-content-subtle);
  cursor: pointer;
  padding: 6px 8px;
  font-size: 12px;
}

.pickerBack > svg {
  transform: rotate(180deg);
}

.entityIcon {
  display: inline-flex;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: var(--clue-ds-color-bg-page);
  color: var(--clue-ds-color-content-subtle);
}
```
If `ProjectIcon` renders an `<img>` rather than an inline `<svg>`, target `.pickerBack > *` for the rotation.

- [ ] **Step 4: The `@` button and Home**

`project-composer.tsx`: `aria-label="Add context"`, `title="Add context"`; pass `categoriesEnabled={variant !== "home"}` to `<ProjectComposerEditor>`.

- [ ] **Step 5: Gate and browser check**

`npm test && npm run lint && npm run build` from `apps/frontend`. Then in the lane frontend (port 3020), in a project with documents, an ad, a microsite and accounts: `@` shows three rows with counts; Enter on Files lists the files by title with kind labels; ArrowLeft returns; typing `@plan` groups matches under headers; Escape closes; `@meet ` with no match closes by itself; Home composer shows the flat accounts list. Record what you saw in the report.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/features/projects/components/entity-picker.tsx apps/frontend/src/features/projects/components/project-composer-editor.tsx apps/frontend/src/features/projects/components/project-composer.tsx apps/frontend/src/features/projects/components/project-flow.module.css
git commit -m "feat(frontend): two-level @ picker — Files, Microsites, Accounts with cross-category search"
```

---

### Task 8: Chips, contract notes, memory

**Files:**
- Modify: `apps/frontend/src/features/projects/components/project-composer-editor.tsx:79-119` (`ComposerMention`)
- Modify: `apps/frontend/src/features/projects/components/chat-transcript.tsx:105-140`
- Modify: `apps/frontend/docs/api-contracts/projects.md` (the `context_refs` paragraphs at ~`:946-990` and the message `refs` description near `:1182`)
- Modify: `_memory/2026-09-17-composer-file-tagging.md` (exists from the planning session; extend it); add one row to `_memory/README.md`

**Interfaces:**
- Consumes: `ProjectComposerMentionElement.icon/imagePath/entityType`; `ChatMessageRef.label/kind`.

- [ ] **Step 1: Composer chip**

In `ComposerMention`:
```tsx
const MENTION_TYPE_LABELS: Record<ProjectComposerMentionElement["entityType"], string> = {
  account: "Account",
  contact: "Contact",
  design_document: "Design",
  project_document: "File",
};
```
`aria-label={`${MENTION_TYPE_LABELS[element.entityType]} context: ${element.label}`}` and inside `.composerMentionVisual` render
```tsx
          {element.icon ? (
            <ProjectIcon name={element.icon} size={14} />
          ) : (
            <Image alt="" aria-hidden="true" className={element.entityType === "contact" ? styles.composerMentionAvatar : ""} height={16} src={element.imagePath ?? "/logos/clue.svg"} width={16} />
          )}
```

- [ ] **Step 2: Transcript chip**

In `chat-transcript.tsx` extend the fallback ladder with `project_document → "Selected file"` and change `design_document → "Selected design"`; prefix `@` for `account | contact | project_document | design_document`. Keep `design_node`/`design_asset` exactly as they are.

- [ ] **Step 3: Contract notes**

In `apps/frontend/docs/api-contracts/projects.md`, at the `context_refs` bullet (`:978-982`) replace "`object_type` is exactly `account | contact` for this composer." with:

> `object_type` is one of `account | contact | project_document | design_document` for this composer (`design_node`/`design_asset` ride the design leg). `project_document` is a Gallery file: `object_id` is the document's `id` from `GET /projects/{id}/documents` and `version` is required and must equal that listing's `version` (the latest); otherwise `409 CONTEXT_REF_STALE`. A `project_document` ref on `POST /projects` (Home) is refused with `409 CONTEXT_REF_RELATIONSHIP_MISMATCH`. `design_document` mentions carry the artifact's `document_id` and `Number(current_version_id)` and must belong to the project (`404 CONTEXT_REF_NOT_FOUND` otherwise). Tags never open a design leg; the agent decides that by reasoning. (2026-09-17, spec `docs/superpowers/specs/archive/2026-09-17-composer-file-tagging-design.md`.)

At the message `refs` description add: "Echoed `context` refs of type `project_document` and `design_document` carry `label` (the document's own title) and `kind` (the document kind, or `web|ad`), resolved at read time; the frontend renders the chip from `label` and never from the id."

- [ ] **Step 4: Memory note**

Extend `_memory/2026-09-17-composer-file-tagging.md` with: the rulings (copy the spec's status paragraph), the commit list of Tasks 1–8, the migration id, what was verified in the browser and by which tests, and the two owed items: a live turn proving the L5 card lands in the agent's `context/focus/` (read the turn's context-refs receipt) and a live microsite mention showing Head-of-ABM answering without a leg. Add a one-line row to `_memory/README.md`'s index.

- [ ] **Step 5: Gate**

`npm test && npm run lint && npm run build` from `apps/frontend`; in the browser send one message tagging a file and confirm the transcript chip shows the file's title and no path.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/features/projects/components/project-composer-editor.tsx apps/frontend/src/features/projects/components/chat-transcript.tsx apps/frontend/docs/api-contracts/projects.md _memory/2026-09-17-composer-file-tagging.md _memory/README.md
git commit -m "feat(frontend): typed tag chips in composer and transcript; contract and memory notes for file tagging"
```

---

## Self-review (done 2026-09-17 against the spec)

- **Spec coverage.** §3.1 → Task 1 (wire, CHECK) and Task 2 (`design_document` reuse with containment). §3.2 → Task 2. §3.3 → Task 1. §3.4 → Task 3 (card), routing untouched by construction. §3.5 → Task 4. §3.6 → Tasks 5–6. §3.7 → Task 7 (incl. the query-spaces ruling). §3.8 → Task 7 (`categoriesEnabled={variant !== "home"}`) and Task 2 (`project_id=None` refusal). §3.9 → Task 8. §5 acceptance items 1, 2, 6 are checked in Task 7's browser step; 3 and 4 are the live proofs recorded as owed in Task 8's memory note (they need a real agent turn); 5 is `test_validated_context_refs_project_document_semantics`; 7 is the per-task gates.
- **One deviation from the spec, ruled here:** §3.2 said a version is required for `design_document` mentions. The existing contract accepts an unpinned `design_document` ref because a fresh document's CAS counter is 0 and `DomainObjectRef.version` is ≥ 1 (`tests/design/test_p31_design_vocabulary_db.py::test_validated_context_refs_design_document_semantics`). The plan keeps `design_document` version optional on the backend; the frontend sends a version whenever the artifact has one (`versionOf`) and omits artifacts without one from the picker. `project_document` versions stay mandatory.
- **Type consistency.** `get_project_document` / `latest_project_document_version` / `document_title` names match between Tasks 2, 3, 4. `context_ref_presentations` + `PRESENTED_REF_TYPES` match between Task 4's module and callers. `ProjectEntity.category/icon/type` names match Tasks 5, 6, 7, 8. `EntityPicker` props match the editor render in Task 7. `setCatalogEntities` matches Task 6's controller and surface.
- **Placeholders.** None: every code step carries the code; the two "verify the constructor/enum" notes ask the implementer to confirm an existing signature, not to invent one.
