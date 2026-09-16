# Artifacts Page Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the cross-project `/artifacts` library end to end: one workspace-wide read, per-user saved and last-viewed marks, governed rename and archive on design documents, the dummy's library UI bound to real data, and the `?open=` param that lands a new chat with the artifact's editor tab open.

**Architecture:** The platform serves `GET /frontend/v1/artifacts` (leg-derived, workspace-wide, cursor-paged) plus two per-user mark writes on the same surface. The design subsystem gains two governed tools, rename and set-archived, exposed as `PUT /documents/{id}/title` and `PUT /documents/{id}/archived` on the design API, registered ungranted and human-only on the platform. The frontend lifts the dummy's library, preview dialog and CSS into `src/features/artifacts/`, binds them through `fetchRead` / `fetchMutation` / the design BFF, and re-applies the dummy's gallery-model changes by hand onto our diverged gallery.

**Tech Stack:** FastAPI + SQLAlchemy Core (async) + Alembic on Postgres; Pydantic v2 wire models; the `clue_toolbelt` governed-tool substrate; Next.js App Router + TypeScript + Zod; `node:test` for frontend unit tests; pytest for the backend.

**Spec:** `docs/superpowers/specs/2026-09-15-artifacts-page-integration-design.md`

## Global Constraints

- Presentation truth is the dummy at `/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain` (commits `45892a6`, `93c6120`). Lift, do not invent. Our `Button` has no `primary` variant: the dummy's `variant: "primary"` becomes our `"default"`; `secondary`, `transparent`, `md`, `sm`, `icon-sm` exist on both.
- Alembic: hash ids from `uv run alembic revision -m "<slug>"`, `down_revision` = current head (`b7193eb28363` after the 2026-09-16 rebase onto `research-streaming`; re-check with `uv run alembic heads`), reversible `downgrade()`, exactly one head, `make db-smoke` on the lane's throwaway DB only.
- Every design document mutation is a toolbelt tool (`subsystems/clue-design/apps/api/tests/test_write_path_governance.py` refuses otherwise). New tools are registered ungranted and human-only.
- No new env flags. `.env.example` is unchanged. The lane's `.env` keeps full key parity with `.env.example`.
- Backend suites run on the lane DB only, never `make check` with real keys: `uv run pytest <file> --ignore-glob='*_live.py'`. Load env with `set -a; source .env; set +a` first.
- Frontend gate: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`; unit tests with `node --import tsx --test <file>` (the `tsx --test` CLI's IPC is sandbox-denied).
- Commit locally at each task's end, on this branch (`artifacts-page`). Never push. No AI attribution in commit messages.
- Honest absence everywhere: no fixture data in HTTP mode, no invented account, size, or channel, never a fallback to fixtures on failure.

### Telemetry, logging and tracing standard (applies to every task)

Verified against the codebase on 2026-09-16 (`libs/clue-obs`, `platform/api/clue_api/production_tracing.py`, `platform/toolbelt/clue_toolbelt/invoker.py`, `_memory/2026-09-14-lane3-telemetry-rulings.md`). New code follows it exactly; nothing new is invented.

- **Loggers.** Platform Python: `from clue_obs import get_logger` and `log = get_logger("clue_api.<module path>")` at module scope. Never `logging.getLogger` (`tests/clue_obs/test_logging_discipline.py` fails the build) and never `print` (ruff T20). Design API Python (`lumen_api`): `from py_lumen_obs import get_logger` / the module's existing `api_logger`, as its routes already do.
- **Event names and fields.** Dotted, snake-case, `<module>.<what_happened>` (`project_documents.document_unreadable`, `design_leg.exit_judge_raised`, `tracing.installed`). Keyword fields are identifiers only: `workspace_id`, `project_id`, `document_id`, `user_id`, `artifact_id`, counts, and `error=str(error)`. Never a title, a payload, a claim value, a token or a blob; the redaction processor is a backstop, not a licence.
- **When to log.** `warning` for a failure the code swallows or degrades on; `info` for composition-time facts. Routes do not log successful requests (the FastAPI instrumentor's span is the record), and typed 4xx refusals are not logged either (they are the response). DAL functions and pure query helpers are silent, like their siblings in `clue_design/documents.py` and `design_leg_wiring.project_design_documents`.
- **Tracing.** FastAPI and httpx are instrumented at the roots (`install_production_tracing`), so every route already has a server span, and `bind_and_annotate(request_id=…)` runs per request. Multi-statement or hot steps get `with traced_step("<domain>.<step>", **ids)` from `clue_obs.otel`; attributes pass through `safe_attributes`, so only ids and small scalars go on them. The `/frontend/v1` tenant resolver does not yet stamp the workspace on the span the way the `/api/v1` header seam does; Task 5 adds that one line so the library's spans (and every other read-surface span) carry `workspace_id`.
- **Run context.** Never bind run ids by hand inside a route; the seams do it. The marks routes read the principal (`principal_from_request`) exactly as the bulk actions do.
- **Metrics.** Domain counters go through `get_metric_sink().add("<domain>.<metric>", 1, {"<attr>": "<low-cardinality string>"})` from `clue_obs.otel`, the way `value_narrative_tools._emit` does. Tests swap in `InMemorySink` via `set_metric_sink` and read `sink.counter(name, **attrs)`. This plan adds one counter per write (`artifacts.mark.written`, `design.document.renamed`, `design.document.archived`); reads add none.
- **Langfuse.** Governed tools are observed automatically: `ToolInvoker.invoke` opens `governed.<name>@<version>` with the inputs the tool's `parameter_policy.safe_display_fields` allows. The two new design tools therefore need no Langfuse code; their `safe_display_fields` (`document_id`, `title` / `document_id`, `enabled`) ARE the observation contract. The design API root has no OTel, Sentry or Langfuse installed today (founder ruling 2026-09-14 §5, held), so the observation is a no-op there until that lane runs; nothing in this plan changes that.
- **Sentry.** Installed at the roots with PII off; nothing per feature. Do not swallow exceptions without a `warning` log; let genuine errors propagate to the envelope middleware.
- **Frontend.** There is no telemetry stack in `apps/frontend`. The one convention is `console.warn("[<feature>] <what was refused>:", error)` in a catch that degrades to a notice, tagged with the feature name as `brand-context` does; never `console.log`, never a console line on the happy path.
- **Tests.** A log event is asserted with `from clue_obs import capture_events` → `with capture_events(mode="info") as cap: …; cap.events("<event>")`. A metric is asserted through `InMemorySink`.

---

## File map

**Platform backend**
- Create `platform/api/clue_api/frontend_read/artifacts.py` — the library read, the two mark writes, their wire models, `register_artifact_routes`.
- Modify `platform/api/clue_api/frontend_read/app.py` — register the routes.
- Modify `platform/api/clue_api/design_leg_wiring.py` — `project_design_documents` gains the archive filter; new `workspace_design_documents` query; new `design_document_card_fields` row helper shared with the chat router.
- Modify `platform/api/clue_api/chat/router.py` — `_design_artifact_list_item` uses the shared helper.
- Modify `platform/auth/clue_auth/store.py`, `platform/auth/clue_auth/models.py` — erasure deletes marks.
- Modify `platform/api/clue_api/agent_registry_wiring.py` — two authority entries + human-only membership.
- Create `alembic/versions/<hash>_design_document_archived_at.py`, `alembic/versions/<hash>_design_document_user_mark.py`.
- Tests: `tests/api/test_frontend_read_artifacts_db.py` (new), `tests/api/test_design_artifact_feed_db.py`, `tests/auth/test_identity_substrate.py`, `tests/agents/test_tool_authority_audit.py`, `tests/api/test_toolbelt_wiring.py`.

**Design subsystem**
- Modify `subsystems/design/clue_design/documents.py` — `rename_document`, `set_document_archived`, `archived_at` on the row mapper.
- Modify `subsystems/clue-design/apps/api/lumen_api/design_store.py` — two store methods.
- Modify `subsystems/clue-design/apps/api/lumen_api/toolbelt/documents.py`, `toolbelt/__init__.py`, `toolbelt/factory.py` — two tools.
- Modify `subsystems/clue-design/apps/api/lumen_api/models.py`, `main.py` — two request models, two routes.
- Tests: `tests/design/test_document_marks_dal_db.py` (new), `subsystems/clue-design/apps/api/tests/test_document_title_and_archive.py` (new), `subsystems/clue-design/apps/api/tests/test_write_path_governance.py`.

**Frontend (`apps/frontend`)**
- Create `src/features/artifacts/model/artifact-library.ts`, `model/artifact-library.test.ts`, `data/artifact-library.repository.ts`, `data/artifact-marks.repository.ts`, `data/artifact-document.repository.ts`, `components/artifact-library.tsx`, `components/artifact-library-preview.tsx`, `components/artifact-library.module.css`, `hooks/use-artifact-actions.ts`.
- Create `src/app/(protected)/artifacts/page.tsx`, `loading.tsx`, `error.tsx`.
- Modify `src/features/gallery/model/project-gallery.ts`, `hooks/use-project-gallery-controller.ts`, `components/gallery-toolbar.tsx`, `model/project-gallery.test.ts`.
- Modify `src/features/chat-shell/hooks/use-image-export-controller.ts` — optional `onExport`.
- Create `src/features/chat-shell/model/open-artifact-param.ts` + test; modify `components/chat-surface.tsx`, `components/editor-surface.tsx`, `model/chat-shell-routes.ts`.
- Modify `src/features/design-editor/engine/scene/documentStore.ts` — `renameDocument`, `setDocumentArchived`; `engine/scene/exportRunner.ts` — export `exportResultFromUnknown`.
- Create `docs/api-contracts/artifacts.md`.

---

### Task 1: Lane setup and the contract document

**Files:**
- Create: `scripts/dev_stack_melbourne.sh`
- Create: `.env` (gitignored; from `.env.example`)
- Create: `apps/frontend/docs/api-contracts/artifacts.md`

**Interfaces:**
- Produces: a migrated lane database named in `.env` as `CLUE_DATABASE_URL`, and the contract every later task implements.

- [ ] **Step 1: Create the lane `.env` at full parity**

```bash
cp .env.example .env
# Edit ONLY these lines in .env (secrets stay placeholders unless you have them):
#   CLUE_DATABASE_URL=postgresql+psycopg://<user>:<pass>@127.0.0.1:<port>/clue_melbourne
# Copy the value from the san-salvador lane's .env for host/port/user and change the database name.
#   CLUE_LANGFUSE_ENVIRONMENT=lane-melbourne
# (Langfuse is enabled by default since research-streaming took lane 3; blank keys are a logged skip, never a crash.)
```

Create the database and migrate:

```bash
createdb clue_melbourne   # or: psql -c 'CREATE DATABASE clue_melbourne' on the same server
set -a; source .env; set +a
make migrate
uv run alembic heads      # expect exactly one head
```

- [ ] **Step 2: Write the stack wrapper**

```bash
cat > scripts/dev_stack_melbourne.sh <<'EOF'
#!/bin/bash
# The melbourne lane's stack (branch artifacts-page): same processes, ports and login as
# scripts/dev_stack.sh (read DEV_STACK.md), against THIS checkout's throwaway database taken
# from .env, one fleet worker, its own agent-workspace root and logs under /tmp/melbourne_*.log.
#
#   ./scripts/dev_stack_melbourne.sh up|down|restart-api|restart-workers|status
#
# It cannot share the box with another lane's stack on the same ports: stop one first.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

DEV_STACK_DB_URL="$(grep -E '^CLUE_DATABASE_URL=' "$ROOT/.env" | cut -d= -f2- | tr -d '"')"
[ -n "$DEV_STACK_DB_URL" ] || { echo "CLUE_DATABASE_URL missing from $ROOT/.env" >&2; exit 2; }
export DEV_STACK_DB_URL
export DEV_STACK_WORKERS=1
export DEV_STACK_WORKER_CONCURRENCY=1
export DEV_STACK_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-melbourne
export DEV_STACK_LOG_PREFIX=/tmp/melbourne

exec "$ROOT/scripts/dev_stack.sh" "$@"
EOF
chmod +x scripts/dev_stack_melbourne.sh
```

- [ ] **Step 3: Write the contract document**

Create `apps/frontend/docs/api-contracts/artifacts.md`:

```markdown
# Artifacts API contract

Status: as-built contract for the cross-project artifacts library, ratified 2026-09-15.
Spec: `docs/superpowers/specs/2026-09-15-artifacts-page-integration-design.md` (repo root).

The dummy's `/artifacts` read `workspace.artifacts` per project. In this repo `workspace.artifacts`
is the schema-hard empty tuple; the library reads ONE workspace-wide endpoint instead.

## Reads (`/frontend/v1`, server, `fetchRead`)

`GET /frontend/v1/artifacts?cursor=&limit=` → `{ "data": { "artifacts": [...] }, "meta": { "next_cursor": string|null } }`
Default limit 50, max 200. Keyset cursor over `(updated_at DESC, id DESC)`; bad cursor → 400 `INVALID_CURSOR` (the accounts list's convention on this surface).
Rows are the workspace-wide form of the per-project design-artifact feed (leg-derived; a document
no leg names is not listed). Archived rows ARE included; the per-project feed excludes them.

Row: `id`, `document_id`, `project_id`, `project_title`, `kind` (`web`|`ad`), `title`, `status`,
`current_version`, `created_at`, `updated_at`, `origin_thread_id`, `artifact_type|null`,
`width_px|null`, `height_px|null`, `account: null | { id, name, domain|null, account_entity_id|null }`,
`archived_at|null`, `saved: bool`, `last_viewed_at|null` (the caller's own marks).
Thumbnails are not on the wire: `/api/clue/design/documents/{document_id}/thumbnail?v={current_version}`.

## Per-user marks (`/frontend/v1`, browser, `fetchMutation`)

`PUT /frontend/v1/artifacts/{id}/saved` body `{ "saved": bool }` → `{ "data": { "saved": bool } }`
`POST /frontend/v1/artifacts/{id}/viewed` → `{ "data": { "last_viewed_at": string } }`
401 without an authenticated principal; 404 `ARTIFACT_NOT_FOUND` for a document outside the workspace.

## Document writes (design API through `/api/clue/design`)

`PUT /documents/{id}/title` body `{ "title": string }` → `{ "schema_version": 1, "document_id", "title" }`
  Governed tool `design_rename_document@1`; bumps `current_version`; refuses a finalized document (409).
`PUT /documents/{id}/archived` body `{ "archived": bool }` → `{ "schema_version": 1, "document_id", "archived_at": string|null }`
  Governed tool `design_set_document_archived@1`; no version bump; archive and publish are independent.
Both tools are registered ungranted and human-only.

## Chats route vocabulary

`?open=<artifactId>` on `/projects/:id/chats/:chatId` is read ONCE at mount, resolved against the
project's own feed (unknown ids are ignored), opens that artifact tab, and is never written back.
This answers the open 2026-08-19 question on artifact identity in shared links; `?artifact=` stays
forbidden. Documents keep `?document=<path>`.

## Library behaviour

Whole library server-rendered by walking the cursor. Collections: All (not archived), Saved (saved
and not archived), Archived. Default sort last-viewed (own mark, falling back to updated_at).
Account filter/group options come only from accounts on artifacts. Open editor creates a thread
under the artifact's project titled with the artifact's title and navigates with `?open=` and
`surface=web|ad`. Open source conversation → the origin thread. Copy link → the editor route
`/projects/:id/artifacts/:artifactId`. Downloads: ads = real engine export (PNG 1x–4x, SVG, PDF);
web pages = the thumbnail PNG only. Create in chat → `/`.
```

- [ ] **Step 4: Commit**

```bash
git add scripts/dev_stack_melbourne.sh apps/frontend/docs/api-contracts/artifacts.md
git commit -m "docs(artifacts): lane stack wrapper and the artifacts API contract"
```

---

### Task 2: Migration — `design_document.archived_at`

**Files:**
- Create: `alembic/versions/<hash>_design_document_archived_at.py`

**Interfaces:**
- Produces: column `design_document.archived_at timestamptz NULL`.

- [ ] **Step 1: Generate the revision**

```bash
set -a; source .env; set +a
uv run alembic revision -m "design_document_archived_at"
```

- [ ] **Step 2: Write the migration body** (keep the generated `revision`/`down_revision` values)

```python
"""design_document.archived_at — the library's archive state (artifacts-page spec 2026-09-15 §4.1)

One nullable column. Archiving is a gallery/library state: an archived document leaves the
per-project feed and the Archived collection lists it. Publish is independent (founder ruling
2026-09-15). Reversible: downgrade drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<generated>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE design_document ADD COLUMN archived_at timestamptz NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE design_document DROP COLUMN archived_at")
```

- [ ] **Step 3: Smoke it**

```bash
make db-smoke && uv run alembic heads
```
Expected: up → down → up clean; exactly one head.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/*_design_document_archived_at.py
git commit -m "feat(design): archived_at on design_document (artifacts library archive state)"
```

---

### Task 3: Migration — `design_document_user_mark`

**Files:**
- Create: `alembic/versions/<hash>_design_document_user_mark.py`

**Interfaces:**
- Produces: table `design_document_user_mark(workspace_id, user_id, document_id, saved, last_viewed_at, updated_at)`.

- [ ] **Step 1: Generate the revision** (`down_revision` = Task 2's revision)

```bash
uv run alembic revision -m "design_document_user_mark"
```

- [ ] **Step 2: Write the migration body**

```python
"""design_document_user_mark — per-user saved / last-viewed marks (artifacts-page spec §4.2)

User metadata about a design document, never document state: one row per (workspace, user,
document). Cascades on document delete; the user row is never deleted, so erasure deletes marks
explicitly (clue_auth.store.erase_platform_user).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<task 2 revision>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_document_user_mark (
            workspace_id   text        NOT NULL,
            user_id        text        NOT NULL,
            document_id    text        NOT NULL,
            saved          boolean     NOT NULL DEFAULT false,
            last_viewed_at timestamptz NULL,
            updated_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_document_user_mark_pkey PRIMARY KEY (workspace_id, user_id, document_id),
            CONSTRAINT design_document_user_mark_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_document_user_mark_user_fk FOREIGN KEY (user_id)
                REFERENCES platform_user (user_id),
            CONSTRAINT design_document_user_mark_document_fk FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX design_document_user_mark_by_user "
        "ON design_document_user_mark (workspace_id, user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_document_user_mark")
```

- [ ] **Step 3: Smoke it**

```bash
make db-smoke && uv run alembic heads
```

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/*_design_document_user_mark.py
git commit -m "feat(platform): design_document_user_mark table for per-user saved and last-viewed"
```

---

### Task 4: The workspace-wide query, the shared row helper, and the feed's archive filter

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (around `project_design_documents`, line ~436, and `document_page_pixels`, line ~497)
- Modify: `platform/api/clue_api/chat/router.py:254-283` (`_design_artifact_list_item`)
- Test: `tests/api/test_design_artifact_feed_db.py`

**Interfaces:**
- Produces:
  - `design_document_card_fields(document: Mapping[str, Any]) -> dict[str, Any]` returning `{"kind": "web"|"ad", "artifact_type": str|None, "width_px": int|None, "height_px": int|None}`.
  - `async workspace_design_documents(conn, *, workspace_id: str, user_id: str | None, limit: int, cursor_updated_at: datetime | None, cursor_id: str | None) -> tuple[Mapping[str, Any], ...]` returning rows with keys: `id, title, status, doc_kind, current_version, created_at, updated_at, origin_thread_id, artifact_type, pages_json, project_id, project_title, account_id, account_name, account_domain, account_entity_id, archived_at, saved, last_viewed_at`.

- [ ] **Step 1: Write the failing feed test (archived rows leave the per-project feed)**

Append to `tests/api/test_design_artifact_feed_db.py`:

```python
def test_an_archived_document_leaves_the_project_feed(require_chat_db: None) -> None:
    """Artifacts-page spec §3.5: archive is a gallery state, so the feed drops the row."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-archived", name="Gallery")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            for document_id, title in (("doc_live", "Live"), ("doc_archived", "Archived")):
                await _seed_design_document(
                    conn, workspace_id=workspace_id, document_id=document_id, title=title
                )
                thread_id = await _seed_thread(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=f"thr_{document_id}",
                )
                await _seed_leg(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    document_id=document_id,
                )
            await conn.execute(
                text("UPDATE design_document SET archived_at = now() WHERE id = 'doc_archived'")
            )
            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            assert [row["id"] for row in feed] == ["doc_live"]

    run_async(scenario())
```

- [ ] **Step 2: Run it to verify it fails**

```bash
set -a; source .env; set +a
uv run pytest tests/api/test_design_artifact_feed_db.py -q -k archived
```
Expected: FAIL (both ids listed).

- [ ] **Step 3: Add the archive filter and the shared helper, then the workspace query**

In `design_leg_wiring.py`, inside `project_design_documents`, change the final join/order lines to:

```python
                    " JOIN design_document d"
                    "   ON d.id = origin.document_id AND d.workspace_id = :ws"
                    # Artifacts-page spec §3.5: archived documents leave the gallery, the
                    # project library and the agent's listing in one place — here.
                    " WHERE d.archived_at IS NULL"
                    " ORDER BY d.updated_at DESC, d.id"
```

Add, after `document_page_pixels`:

```python
def design_document_card_fields(document: Mapping[str, Any]) -> dict[str, Any]:
    """What a listed design document says about itself, for every artifact list.

    One helper for the per-project feed (chat router) and the workspace-wide library
    (frontend_read.artifacts) so the two cannot disagree on kind, channel or size. Absent
    stays ``None`` — a card states nothing rather than inventing (G-H).
    """

    pixels = document_page_pixels(document.get("pages_json"))
    artifact_type = document.get("artifact_type")
    return {
        "kind": "web" if document["doc_kind"] == "web" else "ad",
        "artifact_type": str(artifact_type) if artifact_type else None,
        "width_px": pixels[0] if pixels else None,
        "height_px": pixels[1] if pixels else None,
    }


async def workspace_design_documents(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    user_id: str | None,
    limit: int,
    cursor_updated_at: datetime | None = None,
    cursor_id: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Every design document any thread in the workspace worked on — the artifacts library.

    The workspace-wide form of :func:`project_design_documents`: the same leg derivation
    (latest leg wins as origin, one row per document), joined to the origin project for its
    title, left-joined to ``design_account`` for the page's account when it has one, and
    left-joined to the CALLER's own marks. Archived rows are included (the library partitions
    them); keyset-paged newest-updated first. Fail-closed on workspace at the leg, the
    document, the project and the account.
    """

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT d.id, d.title, d.status, d.doc_kind, d.current_version,"
                    " d.created_at, d.updated_at, d.archived_at,"
                    " origin.thread_id AS origin_thread_id, origin.project_id,"
                    " p.name AS project_title,"
                    " d.current_scene_json #>> '{meta,artifact_type}' AS artifact_type,"
                    " d.current_scene_json #>> '{pages}' AS pages_json,"
                    " a.account_id, a.name AS account_name, a.domain AS account_domain,"
                    " a.account_entity_id,"
                    " COALESCE(m.saved, false) AS saved, m.last_viewed_at"
                    " FROM ("
                    "   SELECT DISTINCT ON (leg.document_id)"
                    "          leg.document_id, leg.thread_id, t.project_id"
                    "   FROM design_leg leg"
                    "   JOIN agent_thread t"
                    "     ON t.id = leg.thread_id AND t.workspace_id = leg.workspace_id"
                    "   WHERE leg.workspace_id = :ws"
                    "     AND leg.document_id IS NOT NULL"
                    "   ORDER BY leg.document_id, leg.created_at DESC, leg.id DESC"
                    " ) origin"
                    " JOIN design_document d"
                    "   ON d.id = origin.document_id AND d.workspace_id = :ws"
                    " JOIN project p"
                    "   ON p.project_id = origin.project_id AND p.workspace_id = :ws"
                    " LEFT JOIN design_account a"
                    "   ON a.account_id = d.account_id AND a.workspace_id = :ws"
                    " LEFT JOIN design_document_user_mark m"
                    "   ON m.document_id = d.id AND m.workspace_id = :ws AND m.user_id = :user"
                    " WHERE ("
                    "   CAST(:cursor_updated_at AS timestamptz) IS NULL"
                    "   OR (d.updated_at, d.id) < (:cursor_updated_at, CAST(:cursor_id AS text))"
                    " )"
                    " ORDER BY d.updated_at DESC, d.id DESC"
                    " LIMIT :limit"
                ),
                {
                    "ws": workspace_id,
                    "user": user_id,
                    "cursor_updated_at": cursor_updated_at,
                    "cursor_id": cursor_id,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(dict(row) for row in rows)
```

Add `from datetime import datetime` to the module imports if absent (it imports `json` already; check the header).

In `chat/router.py`, replace the body of `_design_artifact_list_item` with:

```python
    fields = design_document_card_fields(document)
    return DesignArtifactListItemWire(
        id=str(document["id"]),
        project_id=project_id,
        document_id=str(document["id"]),
        kind=fields["kind"],
        title=str(document["title"]),
        status=str(document["status"]),
        current_version_id=str(document["current_version"]),
        created_at=document["created_at"].isoformat(),
        updated_at=document["updated_at"].isoformat(),
        origin_thread_id=str(document["origin_thread_id"]),
        artifact_type=fields["artifact_type"],
        width_px=fields["width_px"],
        height_px=fields["height_px"],
    )
```

and import `design_document_card_fields` next to the router's existing `document_page_pixels` import (drop `document_page_pixels` from the import if nothing else in the router uses it).

- [ ] **Step 4: Run the feed suite**

```bash
uv run pytest tests/api/test_design_artifact_feed_db.py tests/api/test_design_artifact_seam_db.py -q
```
Expected: PASS including the new test.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/chat/router.py tests/api/test_design_artifact_feed_db.py
git commit -m "feat(artifacts): workspace-wide design document query, shared card fields, archived rows leave the feed"
```

---

### Task 5: The library read on `/frontend/v1/artifacts`

**Files:**
- Create: `platform/api/clue_api/frontend_read/artifacts.py`
- Modify: `platform/api/clue_api/frontend_read/app.py:233-310` (the `build_frontend_read_router` registration block)
- Test: `tests/api/test_frontend_read_artifacts_db.py`

**Interfaces:**
- Consumes: `workspace_design_documents`, `design_document_card_fields` (Task 4); `encode_cursor`/`decode_cursor`/`InvalidCursorError` from `clue_projections.pagination`; `principal_from_request` from `clue_api.auth_wiring`; `WorkspaceDep` from `frontend_read.app`.
- Produces: `register_artifact_routes(router, *, conn_factory)`; wire models `ArtifactV1`, `ArtifactAccountV1`, `ArtifactListResponseV1` (Task 6 adds the mark routes to the same module).

- [ ] **Step 1: Write the failing DB tests**

Create `tests/api/test_frontend_read_artifacts_db.py`:

```python
"""The artifacts library read: ``GET /frontend/v1/artifacts`` (spec 2026-09-15 §3.1).

Harness: the projections app with the frontend-read flag on, the DB seam bound to one rolled-back
connection (as the account-detail suite), and the design-feed suite's seeders for documents,
threads and legs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from tests._identity import seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.api.test_design_artifact_feed_db import (  # noqa: PLC2701
    USER_ID,
    _seed_design_document,
    _seed_leg,
    _seed_thread,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_BASE = f"{FRONTEND_READ_PREFIX}/artifacts"
_T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _app(conn: Any, *, enabled: bool = True) -> Any:
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(
            _env_file=None, frontend_read_enabled=enabled, arv2_display_generate_on_read=False
        ),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


async def _get(conn: Any, *, workspace_id: str, query: str = "", enabled: bool = True) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn, enabled=enabled)), base_url="http://t") as client:
        return await client.get(f"{_BASE}{query}", headers={"X-Workspace-Id": workspace_id})


async def _document_in_project(
    conn: Any, *, workspace_id: str, project_id: str, document_id: str, title: str, updated_at: datetime,
    doc_kind: str = "web",
) -> None:
    await _seed_design_document(
        conn, workspace_id=workspace_id, document_id=document_id, title=title,
        updated_at=updated_at, doc_kind=doc_kind,
    )
    thread_id = await _seed_thread(
        conn, workspace_id=workspace_id, project_id=project_id, thread_id=f"thr_{document_id}"
    )
    await _seed_leg(
        conn, workspace_id=workspace_id, project_id=project_id, thread_id=thread_id, document_id=document_id
    )


def test_lists_every_project_document_with_its_project_and_excludes_legless_and_foreign_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            first = await _seed_project_row(conn, "ws-artifacts-lib", name="Project one")
            ws = first.workspace_id
            second = await _seed_project_row(conn, ws, name="Project two")
            other = await _seed_project_row(conn, "ws-artifacts-other", name="Elsewhere")
            await seed_principal(conn, workspace_id=ws, user_id=USER_ID)
            await seed_principal(conn, workspace_id=other.workspace_id, user_id=USER_ID)
            await _document_in_project(conn, workspace_id=ws, project_id=first.project_id,
                                       document_id="doc_a", title="A", updated_at=_T0)
            await _document_in_project(conn, workspace_id=ws, project_id=second.project_id,
                                       document_id="doc_b", title="B", updated_at=_T0 + timedelta(hours=1),
                                       doc_kind="scene")
            await _seed_design_document(conn, workspace_id=ws, document_id="doc_legless", title="Legless")
            await _document_in_project(conn, workspace_id=other.workspace_id, project_id=other.project_id,
                                       document_id="doc_foreign", title="Foreign", updated_at=_T0)

            response = await _get(conn, workspace_id=ws)
            assert response.status_code == 200, response.text
            rows = response.json()["data"]["artifacts"]
            assert [row["id"] for row in rows] == ["doc_b", "doc_a"]
            by_id = {row["id"]: row for row in rows}
            assert by_id["doc_a"]["project_title"] == "Project one"
            assert by_id["doc_a"]["kind"] == "web"
            assert by_id["doc_b"]["kind"] == "ad"
            assert by_id["doc_a"]["account"] is None
            assert by_id["doc_a"]["archived_at"] is None
            assert by_id["doc_a"]["saved"] is False
            assert by_id["doc_a"]["last_viewed_at"] is None
            assert by_id["doc_a"]["origin_thread_id"] == "thr_doc_a"
            assert response.json()["meta"]["next_cursor"] is None

    run_async(scenario())


def test_pages_stably_across_the_cursor_and_refuses_a_bad_one() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-artifacts-page", name="Paged")
            ws = project.workspace_id
            await seed_principal(conn, workspace_id=ws, user_id=USER_ID)
            for index in range(3):
                await _document_in_project(conn, workspace_id=ws, project_id=project.project_id,
                                           document_id=f"doc_{index}", title=f"D{index}",
                                           updated_at=_T0 + timedelta(minutes=index))
            first = await _get(conn, workspace_id=ws, query="?limit=2")
            assert first.status_code == 200, first.text
            page_one = first.json()
            assert [row["id"] for row in page_one["data"]["artifacts"]] == ["doc_2", "doc_1"]
            cursor = page_one["meta"]["next_cursor"]
            assert cursor
            second = await _get(conn, workspace_id=ws, query=f"?limit=2&cursor={cursor}")
            page_two = second.json()
            assert [row["id"] for row in page_two["data"]["artifacts"]] == ["doc_0"]
            assert page_two["meta"]["next_cursor"] is None
            bad = await _get(conn, workspace_id=ws, query="?cursor=not-a-cursor")
            assert bad.status_code == 400
            assert bad.json()["error"]["code"] == "INVALID_CURSOR"

    run_async(scenario())


def test_carries_the_account_when_the_page_is_stamped_and_the_archive_timestamp() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-artifacts-acct", name="Accounts")
            ws = project.workspace_id
            await seed_principal(conn, workspace_id=ws, user_id=USER_ID)
            await conn.execute(
                text(
                    "INSERT INTO design_account (account_id, workspace_id, name, domain)"
                    " VALUES ('acc_acme', :ws, 'Acme Health', 'acme.example')"
                ),
                {"ws": ws},
            )
            await _document_in_project(conn, workspace_id=ws, project_id=project.project_id,
                                       document_id="doc_page", title="Acme page", updated_at=_T0)
            await conn.execute(
                text("UPDATE design_document SET account_id = 'acc_acme', archived_at = :at WHERE id = 'doc_page'"),
                {"at": _T0 + timedelta(days=1)},
            )
            rows = (await _get(conn, workspace_id=ws)).json()["data"]["artifacts"]
            assert rows[0]["account"] == {
                "id": "acc_acme", "name": "Acme Health", "domain": "acme.example", "account_entity_id": None,
            }
            assert rows[0]["archived_at"] is not None

    run_async(scenario())


def test_is_absent_when_the_read_surface_flag_is_off() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-artifacts-off", name="Off")
            response = await _get(conn, workspace_id=project.workspace_id, enabled=False)
            assert response.status_code == 404

    run_async(scenario())
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/api/test_frontend_read_artifacts_db.py -q
```
Expected: FAIL with 404 on the flag-on tests (route absent).

- [ ] **Step 3: Write the module**

Create `platform/api/clue_api/frontend_read/artifacts.py`:

```python
"""The artifacts library on ``/frontend/v1``: one workspace-wide read and the caller's marks.

Spec ``docs/superpowers/specs/2026-09-15-artifacts-page-integration-design.md`` §3.1–§3.2.
The read is the workspace-wide form of the per-project design-artifact feed; the marks are user
metadata (saved, last-viewed) and never document state — document writes (rename, archive) are
governed design tools on the design API, not routes here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from clue_api.auth_wiring import principal_from_request
from clue_api.design_leg_wiring import design_document_card_fields, workspace_design_documents
from clue_api.frontend_read.app import WorkspaceDep
from clue_db import ConnFactory
from clue_projections.pagination import InvalidCursorError, decode_cursor, encode_cursor

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class ArtifactAccountV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    domain: str | None
    account_entity_id: str | None


class ArtifactV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    document_id: str
    project_id: str
    project_title: str
    kind: str
    title: str
    status: str
    current_version: int
    created_at: str
    updated_at: str
    origin_thread_id: str
    artifact_type: str | None
    width_px: int | None
    height_px: int | None
    account: ArtifactAccountV1 | None
    archived_at: str | None
    saved: bool
    last_viewed_at: str | None


class ArtifactListV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifacts: list[ArtifactV1]


class ArtifactPageMetaV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    next_cursor: str | None


class ArtifactListResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ArtifactListV1
    meta: ArtifactPageMetaV1


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _wire(row: Mapping[str, Any]) -> ArtifactV1:
    fields = design_document_card_fields(row)
    account = (
        ArtifactAccountV1(
            id=str(row["account_id"]),
            name=str(row["account_name"]),
            domain=row["account_domain"],
            account_entity_id=None if row["account_entity_id"] is None else str(row["account_entity_id"]),
        )
        if row["account_id"] is not None
        else None
    )
    return ArtifactV1(
        id=str(row["id"]),
        document_id=str(row["id"]),
        project_id=str(row["project_id"]),
        project_title=str(row["project_title"]),
        kind=fields["kind"],
        title=str(row["title"]),
        status=str(row["status"]),
        current_version=int(row["current_version"]),
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
        origin_thread_id=str(row["origin_thread_id"]),
        artifact_type=fields["artifact_type"],
        width_px=fields["width_px"],
        height_px=fields["height_px"],
        account=account,
        archived_at=_iso(row["archived_at"]),
        saved=bool(row["saved"]),
        last_viewed_at=_iso(row["last_viewed_at"]),
    )


def _caller_user_id(request: Request) -> str | None:
    principal = principal_from_request(request)
    return None if principal is None else principal.user_id


def _require_caller(request: Request) -> str:
    """The marks are the caller's own, so a write needs a real user (401 otherwise; no dev stand-in —
    the marks table's user FK would refuse one anyway)."""

    user_id = _caller_user_id(request)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "an authenticated session is required"},
        )
    return user_id


def register_artifact_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    @router.get("/artifacts", response_model=ArtifactListResponseV1)
    async def list_artifacts(
        request: Request,
        workspace_id: WorkspaceDep,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query()] = None,
    ) -> ArtifactListResponseV1:
        cursor_updated_at: datetime | None = None
        cursor_id: str | None = None
        if cursor is not None:
            try:
                position, cursor_id = decode_cursor(cursor, parts=2)
                cursor_updated_at = datetime.fromisoformat(position)
            except (InvalidCursorError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail={"code": "INVALID_CURSOR", "message": str(exc)}
                ) from exc
        async with conn_factory() as conn:
            rows = await workspace_design_documents(
                conn,
                workspace_id=workspace_id,
                user_id=_caller_user_id(request),
                limit=limit + 1,
                cursor_updated_at=cursor_updated_at,
                cursor_id=cursor_id,
            )
        page = rows[:limit]
        next_cursor = (
            encode_cursor(page[-1]["updated_at"].isoformat(), str(page[-1]["id"]))
            if len(rows) > limit
            else None
        )
        return ArtifactListResponseV1(
            data=ArtifactListV1(artifacts=[_wire(row) for row in page]),
            meta=ArtifactPageMetaV1(next_cursor=next_cursor),
        )
```

Check how the surface's error middleware shapes `HTTPException(detail={"code", "message"})` into `{"error": {"code", "message"}}` — `bulk_actions.py` raises exactly this shape, so the envelope is already handled.

Telemetry (standard above): add `from clue_obs import get_logger` and `from clue_obs.otel import traced_step` to the module imports, `log = get_logger("clue_api.frontend_read.artifacts")` at module scope, and run the query inside a step span:

```python
        async with conn_factory() as conn:
            with traced_step(
                "artifacts.library_read",
                workspace_id=workspace_id,
                limit=limit,
                paged=cursor is not None,
            ):
                rows = await workspace_design_documents(
                    conn,
                    workspace_id=workspace_id,
                    user_id=_caller_user_id(request),
                    limit=limit + 1,
                    cursor_updated_at=cursor_updated_at,
                    cursor_id=cursor_id,
                )
```

The 400 on a bad cursor is a typed refusal and is not logged. Then stamp the workspace on the read surface's spans in header (local) mode: in production `projections_app` overrides `frontend_read_workspace_resolver` with the authenticated `workspace` dependency, which already calls `bind_and_annotate(workspace_id=…)`; the header-mode resolver never did. In `frontend_read/app.py::frontend_read_workspace_resolver`, before `return x_workspace_id`, add `bind_and_annotate(workspace_id=x_workspace_id)` with `from clue_obs.otel import bind_and_annotate` (mirror the comment at `projections_app.py:156-159`), so both modes stamp the span the same way.

Register it in `app.py` after `register_project_document_routes(...)`:

```python
    from clue_api.frontend_read.artifacts import register_artifact_routes
    ...
    # The cross-project artifacts library and the caller's marks (spec 2026-09-15).
    register_artifact_routes(router, conn_factory=conn_factory)
```

(Put the import with the other local imports at the top of `build_frontend_read_router`.)

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/api/test_frontend_read_artifacts_db.py tests/api/test_frontend_read_app.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/frontend_read/artifacts.py platform/api/clue_api/frontend_read/app.py tests/api/test_frontend_read_artifacts_db.py
git commit -m "feat(artifacts): GET /frontend/v1/artifacts — the workspace-wide, cursor-paged library read"
```

---

### Task 6: The per-user mark writes and the erasure step

**Files:**
- Modify: `platform/api/clue_api/frontend_read/artifacts.py`
- Modify: `platform/auth/clue_auth/store.py:864-935` (`erase_platform_user`), `platform/auth/clue_auth/models.py:111-120` (`IdentityErasureResult`)
- Test: `tests/api/test_frontend_read_artifacts_db.py`, `tests/auth/test_identity_substrate.py`

**Interfaces:**
- Produces: `PUT /frontend/v1/artifacts/{id}/saved`, `POST /frontend/v1/artifacts/{id}/viewed`; `IdentityErasureResult.artifact_marks_deleted: int = 0`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_frontend_read_artifacts_db.py`. A principal reaches `/frontend/v1` only through the resolver override production installs; the test installs the same override:

```python
from datetime import datetime as _dt
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from tests._identity import fixture_membership_id


def _principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=USER_ID),
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=_dt(2026, 9, 15, 9, 0, tzinfo=UTC),
    )


def _app_with_principal(conn: Any, workspace_id: str) -> Any:
    """The read surface under a real principal, the way production reaches it: `projections_app`
    overrides `frontend_read_workspace_resolver` with the authenticated workspace dependency, whose
    `PrincipalDependency` stores the principal on `request.state.clue_principal`. The test installs
    the same override with a resolver that stores the fixture principal."""
    from fastapi import Request
    from clue_api.frontend_read.app import frontend_read_workspace_resolver

    app = _app(conn)

    async def _resolver(request: Request) -> str:
        request.state.clue_principal = _principal(workspace_id)
        return workspace_id

    app.dependency_overrides[frontend_read_workspace_resolver] = _resolver
    return app


def test_saved_and_viewed_marks_are_the_callers_own_and_converge() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-artifacts-marks", name="Marks")
            ws = project.workspace_id
            await seed_principal(conn, workspace_id=ws, user_id=USER_ID)
            await _document_in_project(conn, workspace_id=ws, project_id=project.project_id,
                                       document_id="doc_m", title="Marked", updated_at=_T0)
            app = _app_with_principal(conn, ws)
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                headers = {"X-Workspace-Id": ws}
                saved = await client.put(f"{_BASE}/doc_m/saved", json={"saved": True}, headers=headers)
                assert saved.status_code == 200, saved.text
                assert saved.json()["data"] == {"saved": True}
                again = await client.put(f"{_BASE}/doc_m/saved", json={"saved": True}, headers=headers)
                assert again.json()["data"] == {"saved": True}
                viewed = await client.post(f"{_BASE}/doc_m/viewed", headers=headers)
                assert viewed.status_code == 200, viewed.text
                assert viewed.json()["data"]["last_viewed_at"]
                listed = await client.get(_BASE, headers=headers)
                row = listed.json()["data"]["artifacts"][0]
                assert row["saved"] is True and row["last_viewed_at"] is not None
                foreign = await client.put(f"{_BASE}/doc_missing/saved", json={"saved": True}, headers=headers)
                assert foreign.status_code == 404
                assert foreign.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
            count = (await conn.execute(text("SELECT count(*) FROM design_document_user_mark"))).scalar_one()
            assert count == 1

    run_async(scenario())


def test_mark_writes_need_an_authenticated_principal() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-artifacts-anon", name="Anon")
            ws = project.workspace_id
            async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn)), base_url="http://t") as client:
                response = await client.put(f"{_BASE}/doc_x/saved", json={"saved": True},
                                            headers={"X-Workspace-Id": ws})
            assert response.status_code == 401

    run_async(scenario())
```

Extend `tests/auth/test_identity_substrate.py::test_identity_dsar_erases_provider_values_but_keeps_internal_audit_ids`: after `accepted = ...` and before `erase_platform_user`, seed one document and one mark, then assert the mark is gone:

```python
            await conn.execute(
                text(
                    "INSERT INTO design_document (id, workspace_id, title, status, doc_kind, current_scene_json, current_version)"
                    " VALUES ('doc_dsar', :ws, 'Doc', 'draft', 'web', '{}'::jsonb, 0)"
                ),
                {"ws": owner.workspace.workspace_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO design_document_user_mark (workspace_id, user_id, document_id, saved)"
                    " VALUES (:ws, :user, 'doc_dsar', true)"
                ),
                {"ws": owner.workspace.workspace_id, "user": accepted.user.user_id},
            )
```
and after the existing assertions:
```python
            assert result.artifact_marks_deleted == 1
            remaining = (
                await conn.execute(text("SELECT count(*) FROM design_document_user_mark WHERE user_id = :u"),
                                   {"u": accepted.user.user_id})
            ).scalar_one()
            assert remaining == 0
```
(Add `from sqlalchemy import text` to that test module if absent.)

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/api/test_frontend_read_artifacts_db.py -q -k "marks or principal"
uv run pytest tests/auth/test_identity_substrate.py -q -k dsar
```
Expected: FAIL (405/404 on the routes; `artifact_marks_deleted` missing).

- [ ] **Step 3: Add the routes**

In `artifacts.py`, add the models and routes inside `register_artifact_routes` (after `list_artifacts`):

```python
class ArtifactSavedUpdateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved: bool


class ArtifactSavedV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    saved: bool


class ArtifactSavedResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ArtifactSavedV1


class ArtifactViewedV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    last_viewed_at: str


class ArtifactViewedResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ArtifactViewedV1


async def _require_document(conn: Any, *, workspace_id: str, document_id: str) -> None:
    exists = (
        await conn.execute(
            text("SELECT 1 FROM design_document WHERE id = :d AND workspace_id = :w"),
            {"d": document_id, "w": workspace_id},
        )
    ).first()
    if exists is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": "no such artifact in this workspace"},
        )
```

```python
    @router.put("/artifacts/{artifact_id}/saved", response_model=ArtifactSavedResponseV1)
    async def set_saved(
        artifact_id: str, body: ArtifactSavedUpdateV1, request: Request, workspace_id: WorkspaceDep
    ) -> ArtifactSavedResponseV1:
        user_id = _require_caller(request)
        async with conn_factory() as conn:
            await _require_document(conn, workspace_id=workspace_id, document_id=artifact_id)
            await conn.execute(
                text(
                    "INSERT INTO design_document_user_mark (workspace_id, user_id, document_id, saved)"
                    " VALUES (:w, :u, :d, :s)"
                    " ON CONFLICT (workspace_id, user_id, document_id)"
                    " DO UPDATE SET saved = EXCLUDED.saved, updated_at = now()"
                ),
                {"w": workspace_id, "u": user_id, "d": artifact_id, "s": body.saved},
            )
            await conn.commit()
        return ArtifactSavedResponseV1(data=ArtifactSavedV1(saved=body.saved))

    @router.post("/artifacts/{artifact_id}/viewed", response_model=ArtifactViewedResponseV1)
    async def record_viewed(
        artifact_id: str, request: Request, workspace_id: WorkspaceDep
    ) -> ArtifactViewedResponseV1:
        user_id = _require_caller(request)
        viewed_at = datetime.now(UTC)
        async with conn_factory() as conn:
            await _require_document(conn, workspace_id=workspace_id, document_id=artifact_id)
            await conn.execute(
                text(
                    "INSERT INTO design_document_user_mark (workspace_id, user_id, document_id, last_viewed_at)"
                    " VALUES (:w, :u, :d, :at)"
                    " ON CONFLICT (workspace_id, user_id, document_id)"
                    " DO UPDATE SET last_viewed_at = EXCLUDED.last_viewed_at, updated_at = now()"
                ),
                {"w": workspace_id, "u": user_id, "d": artifact_id, "at": viewed_at},
            )
            await conn.commit()
        return ArtifactViewedResponseV1(data=ArtifactViewedV1(last_viewed_at=viewed_at.isoformat()))
```

Check how the other frontend_read writers commit (the project-documents PUT); if the connection factory yields a transaction-managed connection that commits on exit, drop the explicit `await conn.commit()` calls to match.

Telemetry: count each mark write. Add `from clue_obs.otel import get_metric_sink` and, after each successful upsert:

```python
        get_metric_sink().add("artifacts.mark.written", 1, {"kind": "saved", "value": "true" if body.saved else "false"})
```
and in the viewed route `{"kind": "viewed", "value": "true"}`. No success log (the span is the record); the 401 and 404 are typed refusals and are not logged.

Extend the marks test to assert the counter: install a fresh sink at the top of the scenario —
```python
from clue_obs.otel.metrics import InMemorySink, set_metric_sink
            sink = InMemorySink()
            set_metric_sink(sink)
```
and after the writes: `assert sink.counter("artifacts.mark.written", kind="saved", value="true") == 2` and `assert sink.counter("artifacts.mark.written", kind="viewed", value="true") == 1`. Restore the previous sink in a `finally` (`set_metric_sink(InMemorySink())`).

- [ ] **Step 4: Add the erasure step**

In `models.py`, add to `IdentityErasureResult`:
```python
    artifact_marks_deleted: int = 0
```
In `store.py::erase_platform_user`, after the `provisionings` statement:
```python
    marks = await conn.execute(
        text("DELETE FROM design_document_user_mark WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
```
and pass `artifact_marks_deleted=marks.rowcount` into the returned `IdentityErasureResult`.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/api/test_frontend_read_artifacts_db.py tests/auth/test_identity_substrate.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/frontend_read/artifacts.py platform/auth/clue_auth/store.py platform/auth/clue_auth/models.py tests/api/test_frontend_read_artifacts_db.py tests/auth/test_identity_substrate.py
git commit -m "feat(artifacts): per-user saved and last-viewed marks; erasure deletes them"
```

---

### Task 7: Design DAL — `rename_document` and `set_document_archived`

**Files:**
- Modify: `subsystems/design/clue_design/documents.py` (`_document_from_row` ~line 137; add functions after `set_web_noindex` ~line 358)
- Test: `tests/design/test_document_marks_dal_db.py`

**Interfaces:**
- Produces:
  - `async rename_document(conn, *, workspace_id: str, document_id: str, title: str) -> JsonObject` (the re-read document; raises `ValueError("title must not be blank")` on a blank title; raises `DesignNotFoundError` when absent).
  - `async set_document_archived(conn, *, workspace_id: str, document_id: str, enabled: bool) -> JsonObject`.
  - `_document_from_row` gains `"archived_at": str | None`.

- [ ] **Step 1: Write the failing DAL tests**

Create `tests/design/test_document_marks_dal_db.py`:

```python
"""Rename and archive on the design DAL (artifacts-page spec §3.3–§3.4)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import documents as design_documents
from tests.design.conftest import run_async

pytestmark = pytest.mark.usefixtures("migrated_db")


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_marks_{uuid4().hex[:12]}"
    await conn.execute(text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws})
    return ws


def _scene(doc_id: str, title: str = "Before") -> dict[str, Any]:
    return {"meta": {"id": doc_id, "title": title, "status": {"kind": "draft"}}, "nodes": []}


def test_rename_updates_row_and_scene_title_and_bumps_the_version() -> None:
    async def scenario() -> None:
        async with db_lifespan() as db, db.connect() as conn, conn.begin() as tx:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            created = await design_documents.create_document(conn, workspace_id=ws, scene=_scene(doc_id))
            before = created["current_version"]
            renamed = await design_documents.rename_document(
                conn, workspace_id=ws, document_id=doc_id, title="  After  "
            )
            assert renamed["title"] == "After"
            assert renamed["scene"]["meta"]["title"] == "After"
            assert renamed["current_version"] == before + 1
            with pytest.raises(ValueError):
                await design_documents.rename_document(conn, workspace_id=ws, document_id=doc_id, title="   ")
            await tx.rollback()

    run_async(scenario())


def test_archive_sets_and_clears_without_touching_the_version() -> None:
    async def scenario() -> None:
        async with db_lifespan() as db, db.connect() as conn, conn.begin() as tx:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            created = await design_documents.create_document(conn, workspace_id=ws, scene=_scene(doc_id))
            assert created["archived_at"] is None
            archived = await design_documents.set_document_archived(
                conn, workspace_id=ws, document_id=doc_id, enabled=True
            )
            assert archived["archived_at"] is not None
            again = await design_documents.set_document_archived(
                conn, workspace_id=ws, document_id=doc_id, enabled=True
            )
            assert again["archived_at"] == archived["archived_at"]  # converges
            assert again["current_version"] == created["current_version"]
            restored = await design_documents.set_document_archived(
                conn, workspace_id=ws, document_id=doc_id, enabled=False
            )
            assert restored["archived_at"] is None
            await tx.rollback()

    run_async(scenario())
```

Mirror the connection/transaction idiom of `tests/design/test_personalization_accounts_dal_db.py` exactly if it differs from the above (open that file and copy its `async with` lines).

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/design/test_document_marks_dal_db.py -q
```
Expected: FAIL (`AttributeError: rename_document`).

- [ ] **Step 3: Implement**

In `_document_from_row` add, next to `"updated_at"`:
```python
        # Artifacts-page spec §3.4: the library's archive state; None when live.
        "archived_at": None if row.archived_at is None else iso(row.archived_at),
```

After `set_web_noindex` add:

```python
async def rename_document(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, title: str
) -> JsonObject:
    """Rename one document: the row's ``title`` AND the document JSON's own title, together.

    Every state write (``replace_scene``, ``update_document_state``, ``update_web_document``)
    rewrites the column from the JSON, so a column-only rename would be reverted by the next
    save; and a JSON edit without a version bump would be overwritten by an editor holding the
    old title. So this bumps ``current_version`` under the row lock: an open editor's next
    write fails its compare-and-set and takes its quiet-reload path (``replace_scene`` already
    bumps without a history row — not a new pattern).
    """
    clean = title.strip()
    if not clean:
        raise ValueError("title must not be blank")
    document = await get_document(conn, workspace_id=workspace_id, document_id=document_id, for_update=True)
    path = "{title}" if document["doc_kind"] == "web" else "{meta,title}"
    await conn.execute(
        text(
            "UPDATE design_document"
            " SET title = :title,"
            "     current_scene_json = jsonb_set(current_scene_json, CAST(:path AS text[]), to_jsonb(CAST(:title AS text)), true),"
            "     current_version = current_version + 1, updated_at = now()"
            " WHERE id = :d AND workspace_id = :w"
        ),
        {"title": clean, "path": path, "d": document_id, "w": workspace_id},
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def set_document_archived(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, enabled: bool
) -> JsonObject:
    """Archive (or restore) one document — a gallery/library state, independent of publish.

    Converges: archiving twice keeps the first timestamp. No version bump and no ``updated_at``
    touch: archiving is not an edit, and the library's "last edited" must stay honest.
    """
    await get_document(conn, workspace_id=workspace_id, document_id=document_id, for_update=True)
    await conn.execute(
        text(
            "UPDATE design_document"
            " SET archived_at = CASE WHEN :e THEN COALESCE(archived_at, now()) ELSE NULL END"
            " WHERE id = :d AND workspace_id = :w"
        ),
        {"e": enabled, "d": document_id, "w": workspace_id},
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)
```

Telemetry: none. The DAL is silent like every sibling in this module; the blank-title `ValueError` and `DesignNotFoundError` propagate to the tool gate and the route.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/design/test_document_marks_dal_db.py tests/design/test_personalization_accounts_dal_db.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/design/clue_design/documents.py tests/design/test_document_marks_dal_db.py
git commit -m "feat(design): rename_document and set_document_archived on the design DAL"
```

---

### Task 8: Design toolbelt tools, store methods, request models, and routes

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (after `set_web_noindex`, ~line 735)
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/documents.py` (after `SetWebNoindexTool`, ~line 567)
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/__init__.py` (import block ~line 96; `__all__` ~line 257)
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/factory.py` (import ~line 58; `DESIGN_TOOL_TYPES` ~line 108)
- Modify: `subsystems/clue-design/apps/api/lumen_api/models.py` (after `SetWebNoindexRequest`, ~line 285)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (after the `web-noindex` route, ~line 2562)
- Test: `subsystems/clue-design/apps/api/tests/test_document_title_and_archive.py` (new), `subsystems/clue-design/apps/api/tests/test_write_path_governance.py`

**Interfaces:**
- Produces: tools `design_rename_document@1` (input `{document_id, title}`, output `ToggleRef(field="title")`) and `design_set_document_archived@1` (input `{document_id, enabled}`, output `ToggleRef(field="archived_at")`); routes `PUT /documents/{id}/title` → `{schema_version, document_id, title}` and `PUT /documents/{id}/archived` → `{schema_version, document_id, archived_at}`; store methods `rename_document(document_id, title)` and `set_document_archived(document_id, enabled)`.

- [ ] **Step 1: Write the failing design API tests**

Create `subsystems/clue-design/apps/api/tests/test_document_title_and_archive.py`:

```python
"""PUT /documents/{id}/title and /archived — the artifacts library's two governed writes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lumen_api.design_store import HybridRepository


def _scene(doc_id: str, title: str = "Before") -> dict:
    return {"meta": {"id": doc_id, "title": title, "status": {"kind": "draft"}}, "nodes": []}


def _create(client: TestClient, doc_id: str) -> str:
    created = client.post("/documents", json={"document_id": doc_id, "scene": _scene(doc_id)})
    assert created.status_code in (200, 201), created.text
    return doc_id


def test_rename_writes_row_and_scene_and_bumps_version(client: TestClient, workspace_id: str) -> None:
    doc_id = _create(client, "doc_rename_route")
    repo = HybridRepository(workspace_id=workspace_id)
    before = repo.require_document(doc_id)["current_version"]
    renamed = client.put(f"/documents/{doc_id}/title", json={"title": " After "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {"schema_version": 1, "document_id": doc_id, "title": "After"}
    document = repo.require_document(doc_id)
    assert document["title"] == "After"
    assert document["scene"]["meta"]["title"] == "After"
    assert document["current_version"] == before + 1


def test_rename_refuses_blank_and_finalized(client: TestClient, workspace_id: str) -> None:
    doc_id = _create(client, "doc_rename_refused")
    assert client.put(f"/documents/{doc_id}/title", json={"title": "   "}).status_code == 422
    finalized = client.post(f"/documents/{doc_id}/finalize", json={})
    assert finalized.status_code == 200, finalized.text
    refused = client.put(f"/documents/{doc_id}/title", json={"title": "Nope"})
    assert refused.status_code == 409, refused.text


def test_archive_toggles_and_converges_without_a_version_bump(client: TestClient, workspace_id: str) -> None:
    doc_id = _create(client, "doc_archive_route")
    repo = HybridRepository(workspace_id=workspace_id)
    version = repo.require_document(doc_id)["current_version"]
    assert client.put(f"/documents/{doc_id}/archived", json={}).status_code == 422
    archived = client.put(f"/documents/{doc_id}/archived", json={"archived": True})
    assert archived.status_code == 200, archived.text
    stamp = archived.json()["archived_at"]
    assert stamp
    again = client.put(f"/documents/{doc_id}/archived", json={"archived": True})
    assert again.json()["archived_at"] == stamp
    assert repo.require_document(doc_id)["current_version"] == version
    restored = client.put(f"/documents/{doc_id}/archived", json={"archived": False})
    assert restored.json()["archived_at"] is None
```

Check the document-create route's exact body in `main.py` (`@app.post("/documents")`) and the finalize route's body, and adjust `_create` / the finalize call to match before running. Add a `client` fixture the way sibling suites do (look at how `test_abm_batch_publish.py` obtains `client`; if it is built per-module with `make_client(create_app(...))`, copy that fixture verbatim into this file).

Update `test_write_path_governance.py`:
- In `_GOVERNED` (near line 94–98) add:
  ```python
      "rename_document": ("method", ("lumen_api/design_store.py",)),
      "set_document_archived": ("method", ("lumen_api/design_store.py",)),
  ```
- In `test_design_tool_names_are_stable` add after `"design_set_web_noindex",`:
  ```python
          # Artifacts page (2026-09-15): the library's two curation writes. Ungranted, human-only
          # on the platform, like noindex.
          "design_rename_document",
          "design_set_document_archived",
  ```

- [ ] **Step 2: Run to verify they fail**

```bash
cd subsystems/clue-design/apps/api && uv run pytest tests/test_document_title_and_archive.py tests/test_write_path_governance.py -q; cd -
```
(If the design app uses a different runner, follow `subsystems/clue-design/AGENTS.md`: `pytest apps/api/tests` from `subsystems/clue-design`.) Expected: FAIL (404/405 on the routes; governance name set mismatch).

- [ ] **Step 3: Store methods**

In `design_store.py`, after `set_web_noindex`:

```python
    def rename_document(self, document_id: str, title: str) -> JsonObject:
        """Artifacts page (2026-09-15): governed (``design_rename_document``) — the row title and
        the document JSON's title together, with a version bump (see the DAL docstring)."""
        return self._bridge._run(
            lambda conn: design_documents.rename_document(
                conn, workspace_id=self.workspace_id, document_id=document_id, title=title
            )
        )

    def set_document_archived(self, document_id: str, enabled: bool) -> JsonObject:
        """Artifacts page (2026-09-15): governed (``design_set_document_archived``); converges."""
        return self._bridge._run(
            lambda conn: design_documents.set_document_archived(
                conn, workspace_id=self.workspace_id, document_id=document_id, enabled=enabled
            )
        )
```

- [ ] **Step 4: Tools**

In `toolbelt/documents.py`, after `SetWebNoindexTool`:

```python
class RenameDocumentInput(ToolInput):
    document_id: str
    title: str


class RenameDocumentTool(DesignTool):
    """Rename one document — row title and document JSON title together, version bumped."""

    name = "design_rename_document"
    version = "1"
    model_description = (
        "Rename a design document. Writes the title on the row AND inside the document JSON so "
        "the next save cannot revert it, and advances the document version."
    )
    input_model: ClassVar[type[ToolInput]] = RenameDocumentInput
    output_model: ClassVar[type[ToolOutput]] = ToggleRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + document_id (design_document.title)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="assigning the same title twice converges on the title; the version advances each time",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "title")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, RenameDocumentInput)
        if not inputs.title.strip():
            return (
                PreconditionFailure(
                    reason_code="design_document_title_blank",
                    message="a document title must not be blank",
                ),
            )
        # Both kinds rename; a finalized document is frozen against every mutation.
        return document_failures(
            self.host.repository(ctx.workspace_id), inputs.document_id, draft=True, action="rename"
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RenameDocumentInput)
        document = self.host.repository(ctx.workspace_id).rename_document(
            inputs.document_id, inputs.title
        )
        return ToggleRef(document_id=inputs.document_id, field="title", value=document["title"])


class SetDocumentArchivedInput(ToolInput):
    document_id: str
    #: REQUIRED, no default: a caller who names no value cannot reach the tool (the noindex rule).
    enabled: bool


class SetDocumentArchivedTool(DesignTool):
    """Archive or restore one document — a library/gallery state, independent of publish."""

    name = "design_set_document_archived"
    version = "1"
    model_description = (
        "Archive or restore a design document. An archived document leaves the project gallery "
        "and the artifacts library's default view; publishing is unaffected."
    )
    input_model: ClassVar[type[ToolInput]] = SetDocumentArchivedInput
    output_model: ClassVar[type[ToolOutput]] = ToggleRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + document_id (design_document.archived_at)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: archiving twice keeps the first timestamp",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "enabled")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetDocumentArchivedInput)
        return document_failures(self.host.repository(ctx.workspace_id), inputs.document_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetDocumentArchivedInput)
        document = self.host.repository(ctx.workspace_id).set_document_archived(
            inputs.document_id, inputs.enabled
        )
        return ToggleRef(
            document_id=inputs.document_id, field="archived_at", value=document["archived_at"]
        )
```

Register: in `toolbelt/__init__.py` add `RenameDocumentInput, RenameDocumentTool, SetDocumentArchivedInput, SetDocumentArchivedTool` to the `.documents` import block and to `__all__` (alphabetical positions). In `toolbelt/factory.py` add `RenameDocumentTool, SetDocumentArchivedTool` to the `.documents` import and to `DESIGN_TOOL_TYPES` right after `SetWebNoindexTool` (registration order is the inventory order).

Telemetry for the tools: the Langfuse observation is automatic (`ToolInvoker.invoke` opens `governed.design_rename_document@1` / `governed.design_set_document_archived@1`, showing exactly the `safe_display_fields` declared above — do not widen them). Add one domain counter at the end of each `run()`, before the `return`, with `from clue_obs.otel import get_metric_sink` at the module top (the design toolbelt already depends on `clue_toolbelt`, which depends on `clue_obs`):

```python
        get_metric_sink().add("design.document.renamed", 1, {"doc_kind": str(document.get("doc_kind", "scene"))})
```
```python
        get_metric_sink().add("design.document.archived", 1, {"enabled": "true" if inputs.enabled else "false"})
```
No logging in the tools or the routes: a refused precondition is a typed 4xx/409 through `run_design_tool`'s refusal map, and nothing is swallowed.

- [ ] **Step 5: Request models and routes**

In `models.py` after `SetWebNoindexRequest`:

```python
class RenameDocumentRequest(BaseModel):
    """Artifacts page (2026-09-15): the new title; blank is refused (422) by the tool gate."""

    title: str


class SetDocumentArchivedRequest(BaseModel):
    """Artifacts page (2026-09-15): REQUIRED, no default — same rule as ``SetWebNoindexRequest``."""

    archived: bool
```

In `main.py`, after the `web-noindex` route:

```python
    @app.put("/documents/{document_id}/title")
    def rename_document(
        document_id: str,
        payload: RenameDocumentRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Artifacts page (2026-09-15): rename from the library preview or the editor header."""
        require_document(repo, document_id)
        written = run_design_tool(
            "design_rename_document",
            {"document_id": document_id, "title": payload.title},
            workspace_id=store_workspace_id(repo),
            refusals={
                **_document_refusals(document_id),
                "design_document_title_blank": HTTPException(
                    status_code=422,
                    detail={"code": "document.title_blank", "message": "title must not be blank"},
                ),
            },
        )
        return {"schema_version": 1, "document_id": document_id, "title": written["value"]}

    @app.put("/documents/{document_id}/archived")
    def set_document_archived(
        document_id: str,
        payload: SetDocumentArchivedRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Artifacts page (2026-09-15): archive/restore; publish is independent by ruling."""
        require_document(repo, document_id)
        written = run_design_tool(
            "design_set_document_archived",
            {"document_id": document_id, "enabled": payload.archived},
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        return {"schema_version": 1, "document_id": document_id, "archived_at": written["value"]}
```

Import the two request models where `SetWebNoindexRequest` is imported. Check `_document_refusals` returns a dict keyed by reason code mapping to `HTTPException`s (read its body at `main.py:1115-1150`) and that `design_document_finalized` is already mapped to a 409 there; if not, add that key beside the blank-title one.

- [ ] **Step 6: Run the design tests**

```bash
cd subsystems/clue-design/apps/api && uv run pytest tests/test_document_title_and_archive.py tests/test_write_path_governance.py -q; cd -
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api subsystems/clue-design/apps/api/tests/test_document_title_and_archive.py subsystems/clue-design/apps/api/tests/test_write_path_governance.py
git commit -m "feat(design): governed rename and set-archived tools with PUT /documents/{id}/title and /archived"
```

---

### Task 9: Platform authority entries and the wiring/audit tests

**Files:**
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (the `design_*` block ~line 270-296; `_HUMAN_ONLY_TOOLS` ~line 655-672)
- Test: `tests/agents/test_tool_authority_audit.py:149,215`, `tests/api/test_toolbelt_wiring.py:330,753,1409,1444,1480,1502`

**Interfaces:**
- Consumes: the two tool names from Task 8.

- [ ] **Step 1: Run the audit and wiring tests to see them fail**

```bash
uv run pytest tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py -q
```
Expected: FAIL (registry names 136 ≠ authority 134; matrix missing the two names).

- [ ] **Step 2: Add the authority entries**

In the `design_*` block, after `"design_set_web_noindex": (),` add:
```python
    # Artifacts page (founder ruling 2026-09-15): the library's two curation writes — rename and
    # archive — are human acts from the library or the editor header. Registered UNGRANTED and
    # human-only like `design_set_web_noindex`; granting later is a reviewed profile bump.
    "design_rename_document": (),
    "design_set_document_archived": (),
```
In `_HUMAN_ONLY_TOOLS` after `"design_set_web_noindex",` add:
```python
        "design_rename_document",
        "design_set_document_archived",
```

- [ ] **Step 3: Update the tests**

- `test_tool_authority_audit.py:149`: `== 134` → `== 136`; line 215: `== 54` → `== 56`. Add beside them:
  ```python
      assert C6_AGENT_TOOL_AUTHORITY["design_rename_document"] == ()
      assert C6_AGENT_TOOL_AUTHORITY["design_set_document_archived"] == ()
  ```
- `test_toolbelt_wiring.py`: precondition matrix (near line 330) add
  ```python
      "design_rename_document": ("precondition", ("design_runtime_not_configured",)),
      "design_set_document_archived": ("precondition", ("design_runtime_not_configured",)),
  ```
  body matrix (near line 753) add
  ```python
      "design_rename_document": {"document_id": "doc_matrix", "title": "Renamed"},
      "design_set_document_archived": {"document_id": "doc_matrix", "enabled": True},
  ```
  counts: `len(registry.names()) == 134` → `136` (both sites), `len(registry) == 154` → `156` (both sites), with a comment line: `# Artifacts page (2026-09-15): design_rename_document and design_set_document_archived, ungranted (134 -> 136 / 154 -> 156).`

- [ ] **Step 4: Run them**

```bash
uv run pytest tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/agent_registry_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py
git commit -m "feat(platform): register design_rename_document and design_set_document_archived ungranted, human-only"
```

---

### Task 10: Frontend library model and repositories

**Files:**
- Create: `apps/frontend/src/features/artifacts/model/artifact-library.ts`, `model/artifact-library.test.ts`
- Modify: `apps/frontend/src/features/design-editor/adapter/gallery.ts` (export `collateralTypeFor` and `sizeFor`, unchanged)
- Create: `apps/frontend/src/features/artifacts/data/artifact-library.repository.ts`, `data/artifact-marks.repository.ts`
- Create: `apps/frontend/src/features/artifacts/data/artifact-library.repository.test.ts`

**Interfaces:**
- Produces:
  - `LibraryArtifact` = `ProjectArtifact & { projectId: string; projectTitle: string; documentId: string; kind: "web" | "ad"; account?: LibraryAccount; archivedAt?: string; saved: boolean; lastViewedAt?: string }` where `LibraryAccount = { id: string; name: string; domain?: string; accountEntityId?: string }`.
  - `toLibraryArtifact(row: ArtifactWire, now?: Date): LibraryArtifact`, `libraryKey(a: {projectId: string; id: string}): string`, `ArtifactLibraryData = { artifacts: LibraryArtifact[] }`.
  - `getArtifactLibrary(read?): Promise<ArtifactLibraryData>`; `setArtifactSaved(id, saved)`, `recordArtifactViewed(id)`.

- [ ] **Step 1: Write the failing model tests**

Create `model/artifact-library.test.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { ArtifactWireSchema, libraryKey, toLibraryArtifact } from "./artifact-library";

const row = ArtifactWireSchema.parse({
  id: "doc_1", document_id: "doc_1", project_id: "prj_1", project_title: "Launch",
  kind: "ad", title: "Square ad", status: "draft", current_version: 3,
  created_at: "2026-09-01T09:00:00+00:00", updated_at: "2026-09-02T09:00:00+00:00",
  origin_thread_id: "thr_1", artifact_type: "linkedin_square_ad", width_px: 1080, height_px: 1080,
  account: { id: "acc_1", name: "Acme", domain: "acme.example", account_entity_id: null },
  archived_at: null, saved: true, last_viewed_at: "2026-09-03T09:00:00+00:00",
});

test("an ad row maps to a canvas artifact with real size, channel, account, project and marks", () => {
  const artifact = toLibraryArtifact(row, new Date("2026-09-03T12:00:00Z"));
  assert.equal(artifact.type, "canvas");
  assert.equal(artifact.kind, "ad");
  assert.equal(artifact.collateralType, "linkedin-ad");
  assert.deepEqual(artifact.size, { category: "square", height: 1080, label: "1080 × 1080", width: 1080 });
  assert.equal(artifact.imagePath, "/api/clue/design/documents/doc_1/thumbnail?v=3");
  assert.equal(artifact.projectId, "prj_1");
  assert.equal(artifact.projectTitle, "Launch");
  assert.equal(artifact.accountId, "acc_1");
  assert.equal(artifact.accountName, "Acme");
  assert.equal(artifact.accountLogoPath, "/api/source-favicon?domain=acme.example");
  assert.equal(artifact.account?.accountEntityId, undefined);
  assert.equal(artifact.saved, true);
  assert.equal(artifact.lastViewedAt, "2026-09-03T09:00:00.000Z");
  assert.equal(artifact.updatedAt, "2026-09-02T09:00:00.000Z");
  assert.equal(artifact.archivedAt, undefined);
});

test("a web row is a website artifact; absent account and size stay absent; last-viewed falls back to updated", () => {
  const artifact = toLibraryArtifact(
    ArtifactWireSchema.parse({ ...row, id: "doc_2", document_id: "doc_2", kind: "web", artifact_type: null,
      width_px: null, height_px: null, account: null, saved: false, last_viewed_at: null,
      archived_at: "2026-09-04T09:00:00+00:00" }),
    new Date("2026-09-03T12:00:00Z"),
  );
  assert.equal(artifact.type, "website");
  assert.equal(artifact.collateralType, "microsite");
  assert.equal(artifact.size, undefined);
  assert.equal(artifact.account, undefined);
  assert.equal(artifact.accountLogoPath, undefined);
  assert.equal(artifact.lastViewedAt, "2026-09-02T09:00:00.000Z");
  assert.equal(artifact.archivedAt, "2026-09-04T09:00:00.000Z");
});

test("the library key is project plus artifact id, never the title", () => {
  assert.equal(libraryKey({ projectId: "p", id: "a" }), JSON.stringify(["p", "a"]));
  assert.notEqual(libraryKey({ projectId: "p", id: "a" }), libraryKey({ projectId: "q", id: "a" }));
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/frontend && node --import tsx --test src/features/artifacts/model/artifact-library.test.ts
```
Expected: FAIL (module not found).

- [ ] **Step 3: Write the model**

Create `model/artifact-library.ts`:

```ts
import { z } from "zod";
import { collateralTypeFor, editedLabelFor, sizeFor } from "@/features/design-editor/adapter/gallery";
import {
  ProjectArtifactSchema,
  type ProjectArtifact,
} from "@/features/projects/model/project-workspace";

/** `GET /frontend/v1/artifacts` row, as the backend serializes it (snake_case, offsets allowed). */
export const ArtifactWireSchema = z.object({
  id: z.string().min(1),
  document_id: z.string().min(1),
  project_id: z.string().min(1),
  project_title: z.string().min(1),
  kind: z.enum(["web", "ad"]),
  title: z.string().min(1),
  status: z.string().min(1),
  current_version: z.number().int().nonnegative(),
  created_at: z.string().min(1),
  updated_at: z.string().min(1),
  origin_thread_id: z.string().min(1),
  artifact_type: z.string().min(1).nullable(),
  width_px: z.number().int().positive().nullable(),
  height_px: z.number().int().positive().nullable(),
  account: z
    .object({
      id: z.string().min(1),
      name: z.string().min(1),
      domain: z.string().min(1).nullable(),
      account_entity_id: z.string().min(1).nullable(),
    })
    .nullable(),
  archived_at: z.string().min(1).nullable(),
  saved: z.boolean(),
  last_viewed_at: z.string().min(1).nullable(),
});
export type ArtifactWire = z.infer<typeof ArtifactWireSchema>;

export const ArtifactListResponseSchema = z.object({
  data: z.object({ artifacts: z.array(ArtifactWireSchema) }),
  meta: z.object({ next_cursor: z.string().nullable() }),
});

export interface LibraryAccount {
  id: string;
  name: string;
  domain?: string;
  accountEntityId?: string;
}

export type LibraryArtifact = ProjectArtifact & {
  projectId: string;
  projectTitle: string;
  documentId: string;
  kind: "web" | "ad";
  account?: LibraryAccount;
  archivedAt?: string;
  saved: boolean;
};

export interface ArtifactLibraryData {
  artifacts: LibraryArtifact[];
}

export function libraryKey(artifact: { projectId: string; id: string }): string {
  return JSON.stringify([artifact.projectId, artifact.id]);
}

function utcInstant(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) throw new TypeError(`artifact timestamp is not a date: ${timestamp}`);
  return parsed.toISOString();
}

// Ruling (pre-flight scan): the channel and size rules are the gallery adapter's, imported, never
// re-implemented here. Task 10 first exports `collateralTypeFor` and `sizeFor` from
// `design-editor/adapter/gallery.ts` (they are module-private today; export them unchanged, keep
// their call sites) and imports them:
// import { collateralTypeFor, editedLabelFor, sizeFor } from "@/features/design-editor/adapter/gallery";
// The adapter's signatures take `string | undefined` / `number | undefined`; pass `row.artifact_type ?? undefined`
// and `row.width_px ?? undefined`, `row.height_px ?? undefined`.

export function toLibraryArtifact(row: ArtifactWire, now = new Date()): LibraryArtifact {
  const ad = row.kind === "ad";
  const collateralType = ad ? collateralTypeFor(row.artifact_type ?? undefined) : "microsite";
  const size = ad ? sizeFor(row.width_px ?? undefined, row.height_px ?? undefined) : undefined;
  const updatedAt = utcInstant(row.updated_at);
  const account: LibraryAccount | undefined = row.account
    ? {
        id: row.account.id,
        name: row.account.name,
        ...(row.account.domain ? { domain: row.account.domain } : {}),
        ...(row.account.account_entity_id ? { accountEntityId: row.account.account_entity_id } : {}),
      }
    : undefined;
  const base = ProjectArtifactSchema.parse({
    ...(collateralType ? { collateralType } : {}),
    ...(size ? { size } : {}),
    ...(account ? { accountId: account.id, accountName: account.name } : {}),
    ...(account?.domain ? { accountLogoPath: `/api/source-favicon?domain=${encodeURIComponent(account.domain)}` } : {}),
    createdAt: utcInstant(row.created_at),
    editedLabel: editedLabelFor(row.updated_at, now),
    id: row.id,
    imagePath: `/api/clue/design/documents/${encodeURIComponent(row.document_id)}/thumbnail?v=${encodeURIComponent(String(row.current_version))}`,
    lastViewedAt: row.last_viewed_at ? utcInstant(row.last_viewed_at) : updatedAt,
    originThreadId: row.origin_thread_id,
    title: row.title,
    type: ad ? "canvas" : "website",
    updatedAt,
  });
  return {
    ...base,
    projectId: row.project_id,
    projectTitle: row.project_title,
    documentId: row.document_id,
    kind: row.kind,
    ...(account ? { account } : {}),
    ...(row.archived_at ? { archivedAt: utcInstant(row.archived_at) } : {}),
    saved: row.saved,
  };
}
```

`editedLabelFor` is exported from `design-editor/adapter/gallery.ts` already; if the import pulls a `server-only` graph into node tests, move `editedLabelFor` unchanged into a tiny `design-editor/adapter/edited-label.ts` and re-export it from `gallery.ts`.

- [ ] **Step 4: Run the model tests**

```bash
node --import tsx --test src/features/artifacts/model/artifact-library.test.ts
```
Expected: PASS.

- [ ] **Step 5: Write the failing repository test**

Create `data/artifact-library.repository.test.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { getArtifactLibrary } from "./artifact-library.repository";

const row = (id: string) => ({
  id, document_id: id, project_id: "prj", project_title: "P", kind: "web", title: id, status: "draft",
  current_version: 1, created_at: "2026-09-01T00:00:00+00:00", updated_at: "2026-09-01T00:00:00+00:00",
  origin_thread_id: "thr", artifact_type: null, width_px: null, height_px: null, account: null,
  archived_at: null, saved: false, last_viewed_at: null,
});

test("walks every page of the cursor and returns one flat list", async () => {
  const calls: Array<Record<string, string | number | undefined>> = [];
  const read = async (_path: string, options?: { searchParams?: Record<string, string | number | undefined> }) => {
    calls.push(options?.searchParams ?? {});
    return calls.length === 1
      ? { data: { artifacts: [row("a"), row("b")] }, meta: { next_cursor: "c2" } }
      : { data: { artifacts: [row("c")] }, meta: { next_cursor: null } };
  };
  const library = await getArtifactLibrary(read as never);
  assert.deepEqual(library.artifacts.map((artifact) => artifact.id), ["a", "b", "c"]);
  assert.equal(calls[0].cursor, undefined);
  assert.equal(calls[1].cursor, "c2");
});
```

- [ ] **Step 6: Write the repositories**

Create `data/artifact-library.repository.ts`:

```ts
import { fetchRead } from "@/features/accounts/data/frontend-api";
import { resolveChatTransport } from "@/features/projects/data/chat-api";
import {
  ArtifactListResponseSchema,
  toLibraryArtifact,
  type ArtifactLibraryData,
} from "../model/artifact-library";

const PAGE_SIZE = 200;
/** Ruling: the whole library is server-rendered by walking the cursor. The ceiling only stops a
 * cursor that never terminates; 50 × 200 rows is far beyond any workspace today. */
const MAX_PAGES = 50;

export async function getArtifactLibrary(read: typeof fetchRead = fetchRead): Promise<ArtifactLibraryData> {
  if (resolveChatTransport().mode === "fixture") return { artifacts: [] };
  const artifacts: ArtifactLibraryData["artifacts"] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const body = ArtifactListResponseSchema.parse(
      await read("/artifacts", { searchParams: { cursor, limit: PAGE_SIZE } }),
    );
    for (const row of body.data.artifacts) artifacts.push(toLibraryArtifact(row));
    if (!body.meta.next_cursor) return { artifacts };
    cursor = body.meta.next_cursor;
  }
  throw new Error("The artifacts library did not finish paging.");
}
```

Fixture mode returns an honestly empty library: there is no designed fixture set for the library in this repo, and the gallery feed's two fixture cards carry no project title.

Create `data/artifact-marks.repository.ts`:

```ts
import { z } from "zod";
import { fetchMutation } from "@/features/accounts/data/frontend-mutation";

const SavedResponseSchema = z.object({ data: z.object({ saved: z.boolean() }) });
const ViewedResponseSchema = z.object({ data: z.object({ last_viewed_at: z.string().min(1) }) });

export async function setArtifactSaved(artifactId: string, saved: boolean): Promise<boolean> {
  const body = await fetchMutation(`/artifacts/${encodeURIComponent(artifactId)}/saved`, {
    method: "PUT",
    body: JSON.stringify({ saved }),
  });
  return SavedResponseSchema.parse(body).data.saved;
}

export async function recordArtifactViewed(artifactId: string): Promise<string> {
  const body = await fetchMutation(`/artifacts/${encodeURIComponent(artifactId)}/viewed`, { method: "POST" });
  return ViewedResponseSchema.parse(body).data.last_viewed_at;
}
```

- [ ] **Step 7: Run the repository test**

```bash
node --import tsx --test src/features/artifacts/data/artifact-library.repository.test.ts
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/features/artifacts
git commit -m "feat(artifacts): library wire model, cursor-walking read repository, and mark writes"
```

---

### Task 11: Gallery model changes for the library (project, project filter/group/sorts, toolbar library mode)

**Files:**
- Modify: `apps/frontend/src/features/gallery/model/project-gallery.ts`
- Modify: `apps/frontend/src/features/gallery/hooks/use-project-gallery-controller.ts`
- Modify: `apps/frontend/src/features/gallery/components/gallery-toolbar.tsx`
- Test: `apps/frontend/src/features/gallery/model/project-gallery.test.ts`

**Interfaces:**
- Produces: `GalleryArtifact.project?: { id: string; title: string }`; `GalleryFilters.projectIds?: string[]`; `GalleryGroupBy` gains `"project"`; `GallerySort` gains `"account-asc" | "type-asc" | "project-asc"`; controller gains `projects: {id,title}[]` and `toggleProject(id)`; `GalleryToolbar` gains `library?: boolean`.

- [ ] **Step 1: Write the failing tests**

Append to `project-gallery.test.ts`:

```ts
import type { GalleryArtifact } from "./project-gallery";
import { countActiveGalleryFilters } from "./project-gallery";

const withProject = (artifact: GalleryArtifact, id: string, title: string): GalleryArtifact => ({
  ...artifact, project: { id, title },
});

test("library: project filter, project group and the three extra sorts", () => {
  const [first, second, third] = artifacts;
  const rows = [withProject(first, "p1", "Beta"), withProject(second, "p2", "Alpha"), withProject(third, "p1", "Beta")];
  const filtered = filterGalleryArtifacts({
    artifacts: rows, query: "", filters: { ...DEFAULT_GALLERY_FILTERS, projectIds: ["p2"] },
  });
  assert.deepEqual(filtered.map((row) => row.project?.id), ["p2"]);
  assert.equal(countActiveGalleryFilters({ ...DEFAULT_GALLERY_FILTERS, projectIds: ["p2"] }), 1);
  const groups = groupGalleryArtifacts(rows, "project");
  assert.deepEqual(groups.map((group) => [group.id, group.label, group.artifacts.length]), [["p1", "Beta", 2], ["p2", "Alpha", 1]]);
  assert.deepEqual(sortGalleryArtifacts(rows, "project-asc").map((row) => row.project?.title), ["Alpha", "Beta", "Beta"]);
  const byType = sortGalleryArtifacts(rows, "type-asc");
  assert.ok(byType.every((row, index) => index === 0 || byType[index - 1].collateralTypeLabel.localeCompare(row.collateralTypeLabel) <= 0));
  const byAccount = sortGalleryArtifacts(rows, "account-asc");
  assert.ok(byAccount.every((row, index) => index === 0 || (byAccount[index - 1].account?.name ?? "").localeCompare(row.account?.name ?? "") <= 0));
});

test("library: a project title is searchable", () => {
  const rows = [withProject(artifacts[0], "p1", "Northwind launch")];
  assert.equal(filterGalleryArtifacts({ artifacts: rows, query: "northwind", filters: DEFAULT_GALLERY_FILTERS }).length, 1);
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
node --import tsx --test src/features/gallery/model/project-gallery.test.ts
```
Expected: FAIL (type errors / wrong groups).

- [ ] **Step 3: Apply the model changes** (`project-gallery.ts`)

- `GalleryGroupBy`: `"none" | "account" | "type" | "project"`.
- `GallerySort`: add `| "account-asc" | "type-asc" | "project-asc"`.
- `GalleryFilters`: add `projectIds?: string[];`.
- `GalleryArtifact`: add `/** The owning project — set by the library, absent in a project gallery. */ project?: { id: string; title: string };`.
- `normalizeGalleryArtifact`: add, reading the optional library fields structurally:
  ```ts
  const library = artifact as ProjectArtifact & { projectId?: string; projectTitle?: string };
  ...
    project: library.projectId ? { id: library.projectId, title: library.projectTitle ?? "Untitled project" } : undefined,
  ```
  (place `project:` in the returned object).
- `filterGalleryArtifacts`: first predicate
  ```ts
  if (filters.projectIds?.length && !filters.projectIds.includes(artifact.project?.id ?? "")) return false;
  ```
  and add `artifact.project?.title ?? ""` to the searched values.
- `sortGalleryArtifacts`: before the `name-asc` line add
  ```ts
  if (sort === "account-asc")
    return (left.account?.name ?? "").localeCompare(right.account?.name ?? "") || left.title.localeCompare(right.title);
  if (sort === "type-asc")
    return left.collateralTypeLabel.localeCompare(right.collateralTypeLabel) || left.title.localeCompare(right.title);
  if (sort === "project-asc")
    return (left.project?.title ?? "").localeCompare(right.project?.title ?? "") || left.title.localeCompare(right.title);
  ```
- `groupGalleryArtifacts`: compute id/label with a `project` branch first:
  ```ts
  const id = groupBy === "project"
    ? (artifact.project?.id ?? "unassigned")
    : groupBy === "account" ? (artifact.account?.id ?? "unattributed") : (artifact.collateralType ?? "untyped");
  const label = groupBy === "project"
    ? (artifact.project?.title ?? "No project")
    : /* existing account/type label expression unchanged */;
  ```
- `countActiveGalleryFilters`: add `+ (filters.projectIds?.length ?? 0)`.

- [ ] **Step 4: Controller** (`use-project-gallery-controller.ts`)

After `accounts`, add:
```ts
  const projects = useMemo(() => {
    const index = new Map(
      normalizedArtifacts.flatMap((artifact) => artifact.project ? [[artifact.project.id, artifact.project] as const] : []),
    );
    return [...index.values()];
  }, [normalizedArtifacts]);
```
and return `projects,` plus:
```ts
    toggleProject(projectId: string) {
      setFilters((current) => ({
        ...current,
        projectIds: current.projectIds?.includes(projectId)
          ? current.projectIds.filter((id) => id !== projectId)
          : [...(current.projectIds ?? []), projectId],
      }));
    },
```

- [ ] **Step 5: Toolbar** (`gallery-toolbar.tsx`)

Change the signature to `export function GalleryToolbar({ controller, library = false }: { controller: ProjectGalleryController; library?: boolean })` and at the top of the body:
```ts
  const groupOptions = library ? [...GROUP_OPTIONS, { label: "Project", value: "project" as const }] : GROUP_OPTIONS;
  const sortOptions = library
    ? [...SORT_OPTIONS,
       { label: "Account · A–Z", value: "account-asc" as const },
       { label: "Type · A–Z", value: "type-asc" as const },
       { label: "Project · A–Z", value: "project-asc" as const }]
    : SORT_OPTIONS;
```
Replace the three uses of `SORT_OPTIONS` inside the component (the `sortLabel` lookup and the sort menu map) with `sortOptions`, and the two uses of `GROUP_OPTIONS` (the group label and the group menu map) with `groupOptions`. In the filter menu, before the `Account` section, add:
```tsx
              {library ? (
                <section className={styles.accountFilterSection}>
                  <h3>Project</h3>
                  {controller.projects.map((project) => (
                    <FilterCheck
                      checked={controller.filters.projectIds?.includes(project.id) ?? false}
                      key={project.id}
                      onChange={() => controller.toggleProject(project.id)}
                    >
                      {project.title}
                    </FilterCheck>
                  ))}
                </section>
              ) : null}
```
and change the search input's `aria-label` to `{library ? "Search all artifacts" : "Search project artifacts"}`.

- [ ] **Step 6: Run the gallery tests and lint**

```bash
node --import tsx --test src/features/gallery/model/project-gallery.test.ts src/features/gallery/model/project-document-cards.test.ts && npx eslint src/features/gallery
```
Expected: PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add src/features/gallery
git commit -m "feat(gallery): project on cards, project filter/group, three library sorts, toolbar library mode"
```

---

### Task 12: Document writes and ad export from the frontend

**Files:**
- Modify: `apps/frontend/src/features/design-editor/engine/scene/documentStore.ts` (after `saveLayoutManagedEditing`, ~line 340)
- Modify: `apps/frontend/src/features/design-editor/engine/scene/exportRunner.ts:256` (export `exportResultFromUnknown`); `apps/frontend/src/features/design-editor/hooks/use-scene-export.ts:36` (export `downloadDataUrl`)
- Modify: `apps/frontend/src/features/chat-shell/hooks/use-image-export-controller.ts`
- Create: `apps/frontend/src/features/artifacts/data/artifact-document.repository.ts`
- Test: `apps/frontend/src/features/artifacts/data/artifact-document.repository.test.ts`

**Interfaces:**
- Produces:
  - `renameDocument(options: DocumentStoreOptions, documentId: string, title: string): Promise<string>`; `saveDocumentArchived(options, documentId, archived: boolean): Promise<string | null>` in `documentStore.ts`.
  - `renameArtifactDocument(documentId, title)`, `setArtifactArchived(documentId, archived)`, `exportAdArtifact({ documentId, title, format, scale })` in the artifacts repository (browser-only; they call `designBffConfig()`).
  - `useImageExportController({ title, onExport? })` — when `onExport` is given, `requestExport` awaits it and reports `${format} download started` or the error message; `controller.exporting: boolean`.

- [ ] **Step 1: Write the failing test for the pure export payload**

Create `data/artifact-document.repository.test.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { adExportRequestBody } from "./artifact-document.repository";

test("an ad export asks the design API for the saved document at the chosen profile, never persisting", () => {
  const body = adExportRequestBody("PNG", "2x");
  assert.equal(body.format, "png");
  assert.deepEqual(body.page_ids, []);
  assert.equal(body.persist_preflight, false);
  assert.equal((body.profile as { raster: { scale: number } }).raster.scale, 2);
  assert.equal(adExportRequestBody("SVG", "4x").format, "svg");
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
node --import tsx --test src/features/artifacts/data/artifact-document.repository.test.ts
```

- [ ] **Step 3: Document-store functions**

In `documentStore.ts` add:

```ts
/** Artifacts page (2026-09-15): persist a new title (row + document JSON; the version advances). */
export async function renameDocument(
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
  documentId: string,
  title: string
): Promise<string> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/title`, apiBaseUrl),
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ title }) }
  );
  if (!response.ok) throw new Error(`renaming the document failed (HTTP ${response.status})`);
  const payload = (await response.json()) as { title?: unknown };
  if (typeof payload.title !== "string") throw new Error("renaming the document returned no title");
  return payload.title;
}

/** Artifacts page (2026-09-15): archive or restore. Returns the archive timestamp, null when live. */
export async function saveDocumentArchived(
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
  documentId: string,
  archived: boolean
): Promise<string | null> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/archived`, apiBaseUrl),
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ archived }) }
  );
  if (!response.ok) throw new Error(`archiving the document failed (HTTP ${response.status})`);
  const payload = (await response.json()) as { archived_at?: unknown };
  return typeof payload.archived_at === "string" ? payload.archived_at : null;
}
```

In `exportRunner.ts` change `function exportResultFromUnknown` to `export function exportResultFromUnknown`.

- [ ] **Step 4: The artifacts document repository**

Create `data/artifact-document.repository.ts`:

```ts
"use client";

import { designBffConfig } from "@/features/design-editor/data/design-bff";
import { sceneExportProfile, sceneExportScaleMultiplier, exportFilename, sceneExportResultMessage } from "@/features/design-editor/adapter/scene-export";
import { exportResultFromUnknown } from "@/features/design-editor/engine/scene/exportRunner";
import { downloadDataUrl } from "@/features/design-editor/hooks/use-scene-export";
import { renameDocument, saveDocumentArchived } from "@/features/design-editor/engine/scene/documentStore";
import type { ImageExportFormat, ImageExportScale } from "@/features/chat-shell/model/image-export";

export function renameArtifactDocument(documentId: string, title: string): Promise<string> {
  return renameDocument(designBffConfig(), documentId, title);
}

export function setArtifactArchived(documentId: string, archived: boolean): Promise<string | null> {
  return saveDocumentArchived(designBffConfig(), documentId, archived);
}

/** The saved document's export request: the same profile the ad editor sends, no scene upload
 * (the API exports the stored scene), all pages, and never a persisted preflight. */
export function adExportRequestBody(format: ImageExportFormat, scale: ImageExportScale) {
  const profile = sceneExportProfile(format, sceneExportScaleMultiplier(scale));
  return { format: profile.format, page_ids: [] as string[], profile, persist_preflight: false };
}

// Ruling (pre-flight scan): `downloadDataUrl` already exists, module-private, in
// `design-editor/hooks/use-scene-export.ts`. Export it unchanged from there and import it here;
// do not re-implement it.

export async function exportAdArtifact({ documentId, title, format, scale }: {
  documentId: string; title: string; format: ImageExportFormat; scale: ImageExportScale;
}): Promise<void> {
  const { apiBaseUrl, fetchImpl } = designBffConfig();
  const response = await fetchImpl!(new URL(`/documents/${encodeURIComponent(documentId)}/export`, apiBaseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(adExportRequestBody(format, scale)),
  });
  if (!response.ok) throw new Error(`Export request failed with HTTP ${response.status}`);
  const result = exportResultFromUnknown(await response.json());
  if (result.status !== "ok") throw new Error(sceneExportResultMessage(format, result));
  const dataUrl = result.artifacts[0]?.data_url ?? null;
  if (!dataUrl) throw new Error(`${format} export returned no file`);
  downloadDataUrl(dataUrl, exportFilename(title, format));
}
```

If `designBffConfig()`'s `fetchImpl` is typed optional, the `!` is correct; otherwise drop it. If the `"use client"` directive breaks the node test import, move `adExportRequestBody` into `model/artifact-export.ts` (pure) and import it here.

- [ ] **Step 5: The export controller's `onExport` hook**

In `use-image-export-controller.ts`:
```ts
export function useImageExportController({ title, onExport }: {
  title: string;
  onExport?: (options: { format: ImageExportFormat; scale: ImageExportScale }) => Promise<void>;
}) {
  ...
  const [exporting, setExporting] = useState(false);
  ...
  const requestExport = useCallback(async () => {
    if (onExport) {
      if (exporting) return;
      setExporting(true);
      setStatusMessage("");
      try {
        await onExport({ format, scale });
        setStatusMessage(`${format} download started`);
      } catch (error) {
        setStatusMessage(error instanceof Error ? error.message : "Export failed. Please try again.");
      } finally {
        setExporting(false);
      }
      return;
    }
    /* existing event-dispatch body unchanged */
  }, [exporting, format, onExport, scale, title]);
```
and add `exporting,` to the returned `controller`. The editor's callers pass no `onExport`, so their behaviour is unchanged.

- [ ] **Step 6: Run tests and lint**

```bash
node --import tsx --test src/features/artifacts/data/artifact-document.repository.test.ts && npx eslint src/features/artifacts src/features/chat-shell/hooks src/features/design-editor/engine/scene
```

- [ ] **Step 7: Commit**

```bash
git add src/features/artifacts src/features/design-editor/engine/scene src/features/chat-shell/hooks/use-image-export-controller.ts
git commit -m "feat(artifacts): rename/archive through the design BFF and the saved-document ad export"
```

---

### Task 13: The library screen, the preview dialog, and the route

**Files:**
- Create: `apps/frontend/src/features/artifacts/components/artifact-library.tsx`, `artifact-library-preview.tsx`, `artifact-library.module.css`
- Create: `apps/frontend/src/features/artifacts/hooks/use-artifact-actions.ts`
- Create: `apps/frontend/src/app/(protected)/artifacts/page.tsx`, `loading.tsx`, `error.tsx`
- Modify: `apps/frontend/src/features/chat-shell/model/chat-shell-routes.ts` (add `open` to the accepted query)

**Interfaces:**
- Consumes: Task 10 model/repositories, Task 11 gallery, Task 12 writes.
- Produces: the `/artifacts` page; `useArtifactActions()` returning `{ notice, dismissNotice, save(artifact, saved), archive(artifact, archived), rename(artifact, title), viewed(artifact), openEditor(artifact), busy }`.

- [ ] **Step 1: Lift the dummy files**

```bash
D=/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain
cp "$D/src/features/artifacts/components/artifact-library.module.css" src/features/artifacts/components/
cp "$D/src/features/artifacts/components/artifact-library.tsx" src/features/artifacts/components/
cp "$D/src/features/artifacts/components/artifact-library-preview.tsx" src/features/artifacts/components/
mkdir -p "src/app/(protected)/artifacts"
cp "$D/src/app/artifacts/loading.tsx" "$D/src/app/artifacts/error.tsx" "src/app/(protected)/artifacts/"
```

- [ ] **Step 2: The actions hook**

Create `hooks/use-artifact-actions.ts`:

```ts
"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { useChatRepositories } from "@/features/projects/data/projects-transport";
import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";
import { recordArtifactViewed, setArtifactSaved } from "../data/artifact-marks.repository";
import { renameArtifactDocument, setArtifactArchived } from "../data/artifact-document.repository";
import type { LibraryArtifact } from "../model/artifact-library";

export function useArtifactActions() {
  const router = useRouter();
  const repositories = useChatRepositories();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (work: () => Promise<string>, failure: string) => {
    setBusy(true);
    try {
      setNotice(await work());
      router.refresh();
      return true;
    } catch (error) {
      console.warn("[artifacts] the change was refused:", error);
      setNotice(failure);
      return false;
    } finally {
      setBusy(false);
    }
  }, [router]);

  return {
    busy,
    notice,
    dismissNotice: () => setNotice(""),
    save: (artifact: LibraryArtifact, saved: boolean) =>
      run(async () => {
        await setArtifactSaved(artifact.id, saved);
        return saved ? "Added to saved artifacts." : "Removed from saved artifacts.";
      }, "Your change couldn’t be saved. Please try again."),
    archive: (artifact: LibraryArtifact, archived: boolean) =>
      run(async () => {
        await setArtifactArchived(artifact.documentId, archived);
        return archived ? "Artifact archived. You can restore it from Archived." : "Artifact restored.";
      }, "Your change couldn’t be saved. Please try again."),
    rename: (artifact: LibraryArtifact, title: string) =>
      run(async () => {
        await renameArtifactDocument(artifact.documentId, title);
        return "Artifact renamed.";
      }, "The new name couldn’t be saved. Please try again."),
    viewed: (artifact: LibraryArtifact) => {
      void recordArtifactViewed(artifact.id).catch((error: unknown) => {
        console.warn("[artifacts] the viewed mark was refused:", error);
        setNotice("Preview opened. Last viewed couldn’t be saved.");
      });
    },
    openEditor: async (artifact: LibraryArtifact) => {
      setBusy(true);
      try {
        const thread = await repositories.threads.create({
          idempotencyKey: crypto.randomUUID(),
          projectId: artifact.projectId,
          title: artifact.title,
        });
        router.push(projectChatHref(artifact.projectId, thread.id, { open: artifact.id, surface: artifact.kind }));
      } catch (error) {
        console.warn("[artifacts] opening a new chat was refused:", error);
        setNotice("Couldn’t open a new chat for this artifact. Please try again.");
        setBusy(false);
      }
    },
  };
}
```

Check `ChatThreadsRepository.create`'s exact input/return shape in `chat-threads.repository.ts:27-35` and use the returned thread's id field name.

- [ ] **Step 3: Adapt `artifact-library.tsx`**

Edit the lifted file:
- Replace the `useArtifactOrganization` / `libraryKey` / `ArtifactOrganization` / `downloadFilename` imports with `import { libraryKey, type ArtifactLibraryData, type LibraryArtifact } from "../model/artifact-library";` and `import { useArtifactActions } from "../hooks/use-artifact-actions";` and `import { exportFilename } from "@/features/design-editor/adapter/scene-export";`.
- Replace `const store = useArtifactOrganization(data.artifacts, data.demo);` with `const actions = useArtifactActions();`.
- Collections: `scoped` filters by `artifact.archivedAt` / `artifact.saved` instead of `store.organization[...]`:
  ```ts
  .filter((artifact) => collection === "archived" ? !!artifact.archivedAt : !artifact.archivedAt && (collection !== "saved" || artifact.saved))
  ```
  and the "All artifacts" count is `data.artifacts.filter((a) => !a.archivedAt).length`. Remove every `data.demo ?` guard so Saved/Archived tabs and the bookmark button always render (`data.demo` no longer exists; `ArtifactLibraryData` has only `artifacts`).
- `update(...)` becomes calls into `actions` (`actions.save(artifact.source as LibraryArtifact, !artifact.source.saved)`); the notice is `actions.notice`, dismissed by `actions.dismissNotice`.
- `open(artifact)`: `setSelectedKey(libraryKey(artifact.source as LibraryArtifact)); actions.viewed(artifact.source as LibraryArtifact);`.
- The card's `GalleryArtifactCard` and `GalleryToolbar controller={controller} library` stay. The grid card's download link uses `exportFilename(artifact.title, "PNG")` and `artifact.imagePath!` (a library row always has a thumbnail URL).
- The `failedProjects` warning block is removed (one read; errors reach `error.tsx`).
- `buttonVariants({ variant: "primary" })` → `variant: "default"` wherever present.
- `ApplicationShell activeHref="/artifacts"` stays.
- Pass to the preview: `artifact={selected}`, `onClose`, `actions`.

- [ ] **Step 4: Adapt `artifact-library-preview.tsx`**

- Props become `{ artifact: LibraryArtifact; actions: ReturnType<typeof useArtifactActions>; onClose: () => void }`; drop `demo`, `onUpdate`, `organization`.
- `href` (editor route, used by Copy link): `projectArtifactHref(artifact.projectId, artifact.id)` with no query.
- "Open editor" becomes a `<Button variant="secondary" size="md" disabled={actions.busy} onClick={() => actions.openEditor(artifact)}>`.
- "Open source conversation": `projectChatHref(artifact.projectId, artifact.originThreadId)` unchanged.
- Rename form submits `actions.rename(artifact, title.trim())`; on success close the rename editor.
- Save/Archive buttons call `actions.save(artifact, !artifact.saved)` and `actions.archive(artifact, !artifact.archivedAt)` (archive closes the dialog on success), always rendered.
- Downloads:
  - `artifact.kind === "ad"`: keep the `ImageExportMenu` block; `useImageExportController({ title: artifact.title, onExport: ({ format, scale }) => exportAdArtifact({ documentId: artifact.documentId, title: artifact.title, format, scale }) })`; the button label stays "Download preview" and the menu's status line shows the controller's message. Pass only `controller` to `ImageExportMenu` (its other props are optional; verify in `image-export-menu.tsx:52-58`).
  - `artifact.kind === "web"`: render one `<a download={exportFilename(artifact.title, "PNG")} href={artifact.imagePath}>Download preview (PNG)</a>` and no menu. Remove the separate "Original image" link for ads too? No: keep it for both kinds (it is the thumbnail); the dummy shows it.
  - `tableContent` CSV block: keep the conditional as lifted (never renders).
- Details list: Account → `artifact.account ? (artifact.account.accountEntityId ? <Link href={`/accounts/${artifact.account.accountEntityId}`}>{name}</Link> : name) : "No account"`; Size → only when `artifact.size`; Project → `projectGalleryHref(artifact.projectId, artifact.originThreadId)` unchanged.
- Remove `canvasPagePaths` paging (our rows have none) or keep the code path — it degrades to one page; keep it.
- `buttonVariants({ variant: "primary" })` → `"default"`.

- [ ] **Step 5: The route files**

`src/app/(protected)/artifacts/page.tsx`:
```tsx
import type { Metadata } from "next";
import { ArtifactLibrary } from "@/features/artifacts/components/artifact-library";
import { getArtifactLibrary } from "@/features/artifacts/data/artifact-library.repository";

export const metadata: Metadata = { title: "Artifacts" };
export const dynamic = "force-dynamic";

export default async function ArtifactsPage() {
  return <ArtifactLibrary data={await getArtifactLibrary()} />;
}
```
`loading.tsx` and `error.tsx` are the lifted files; fix their imports to our paths (`@/components/shell/application-shell`, `@/features/gallery/components/gallery-artifact-card`, `@/components/ui/button`).

In `chat-shell-routes.ts` nothing structural changes: `projectChatHref` already accepts any query keys, so `{ open, surface }` rides through `withQuery`.

- [ ] **Step 6: Gate**

```bash
npm run design-system:build && npm run lint && npm run build
```
Expected: clean. Fix type errors where the lifted code referenced dummy-only fields.

- [ ] **Step 7: Commit**

```bash
git add src/features/artifacts "src/app/(protected)/artifacts"
git commit -m "feat(artifacts): the /artifacts library and preview dialog bound to the workspace-wide read and the marks"
```

---

### Task 14: The `?open=` param on the chats route

**Files:**
- Create: `apps/frontend/src/features/chat-shell/model/open-artifact-param.ts`, `open-artifact-param.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (read the param after the auto-open effect ~line 340; strip it in the write-back effect ~line 376)
- Modify: `apps/frontend/src/app/(protected)/projects/[projectId]/chats/[chatId]/page.tsx` (accept `open` in `searchParams` typing; nothing else)

**Interfaces:**
- Produces: `openArtifactFromParam({ openId, artifacts }): ChatShellOpenArtifact | null`.

- [ ] **Step 1: Write the failing test**

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { openArtifactFromParam } from "./open-artifact-param";

const feed = [
  { id: "doc_web", title: "Landing", type: "website" as const },
  { id: "doc_ad", title: "Square", type: "canvas" as const },
];

test("resolves a feed artifact by id with the gallery's kind derivation", () => {
  assert.deepEqual(openArtifactFromParam({ openId: "doc_ad", artifacts: feed }), { id: "doc_ad", kind: "ad", title: "Square" });
  assert.deepEqual(openArtifactFromParam({ openId: "doc_web", artifacts: feed }), { id: "doc_web", kind: "web", title: "Landing" });
});

test("ignores an absent, blank or unknown id — never fabricates a tab", () => {
  assert.equal(openArtifactFromParam({ openId: null, artifacts: feed }), null);
  assert.equal(openArtifactFromParam({ openId: "", artifacts: feed }), null);
  assert.equal(openArtifactFromParam({ openId: "doc_missing", artifacts: feed }), null);
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
node --import tsx --test src/features/chat-shell/model/open-artifact-param.test.ts
```

- [ ] **Step 3: The pure rule**

```ts
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { ChatShellOpenArtifact } from "./chat-shell";

/**
 * `?open=<artifactId>` (ratified 2026-09-15): read once at mount, resolved against the project's
 * own feed so a foreign or stale id opens nothing, never written back. The superseded `?artifact=`
 * stays forbidden; documents keep `?document=`.
 */
export function openArtifactFromParam({ openId, artifacts }: {
  openId: string | null;
  artifacts: readonly Pick<ProjectArtifact, "id" | "title" | "type">[];
}): ChatShellOpenArtifact | null {
  if (!openId) return null;
  const match = artifacts.find((artifact) => artifact.id === openId);
  if (!match) return null;
  return { id: match.id, kind: match.type === "website" ? "web" : "ad", title: match.title };
}
```

- [ ] **Step 4: Wire it in `chat-surface.tsx`**

After the auto-open effect, add:
```ts
  // `?open=` (2026-09-15): land with one artifact tab open. Read once (the ref), resolved against
  // the server-fetched feed, and stripped by the write-back below.
  const openParamHandled = useRef(false);
  useEffect(() => {
    if (openParamHandled.current) return;
    openParamHandled.current = true;
    const opening = openArtifactFromParam({ openId: searchParams.get("open"), artifacts: feedArtifacts });
    if (opening) openArtifact(opening);
  }, [feedArtifacts, openArtifact, searchParams]);
```
In the write-back effect add `query.delete("open");` beside the other deletes. Import `openArtifactFromParam`.

In the chats page, add `open?: string;` to the `searchParams` type (documentation of the vocabulary; the surface reads it from `useSearchParams`).

- [ ] **Step 5: Tests, lint, build**

```bash
node --import tsx --test src/features/chat-shell/model/open-artifact-param.test.ts src/features/chat-shell/model/chat-surface-params.test.ts && npm run lint && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add src/features/chat-shell "src/app/(protected)/projects/[projectId]/chats/[chatId]/page.tsx"
git commit -m "feat(chat-shell): read-once ?open= param opens an artifact tab from the project feed"
```

---

### Task 15: The editor header rename persists

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (`onRenameArtifact` ~line 752)
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx` (`onRenameArtifact` ~line 16 of the excerpt; the component receives `documentIds`)

**Interfaces:**
- Consumes: `renameArtifactDocument` (Task 12); `documentIds: Record<string, string>` (artifact id → document id) already on both mounts; `session.onWriteReload` / `sceneSession.onWriteReload` in `chat-surface.tsx`.

- [ ] **Step 1: Chat surface**

Replace the `onRenameArtifact` handler with:
```ts
        onRenameArtifact={(title) => {
          const artifactId = shell.activeArtifactId;
          if (!artifactId) return;
          const documentId = documentIds?.[artifactId] ?? artifactId;
          void renameArtifactDocument(documentId, title)
            .then((persisted) => {
              shell.setArtifactTitleFor(artifactId, persisted);
              // The rename advanced the version: reload the canvas and the feed so nothing
              // holds the pre-rename document.
              reloadWebCanvas();
              reloadSceneCanvas();
              router.refresh();
            })
            .catch((error: unknown) => {
              // Local state stays as it was; the header shows the stored title again.
              console.warn("[chat-shell] the rename was refused:", error);
            });
        }}
```
Import `renameArtifactDocument` from `@/features/artifacts/data/artifact-document.repository`.

- [ ] **Step 2: Editor surface**

Same shape, using `controller.activeArtifactId`, `controller.setArtifactTitleFor`, the component's `documentIds`, and the `router.refresh()` from `useRouter()` (add the hook if the component lacks it; call the editing session's reload the way that component already does for inspector writes, or `router.refresh()` alone if it has no session handle).

- [ ] **Step 3: Lint and build**

```bash
npm run lint && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add src/features/chat-shell/components/chat-surface.tsx src/features/chat-shell/components/editor-surface.tsx
git commit -m "feat(chat-shell): the editor header rename persists through the design API"
```

---

### Task 16: Gates, browser walk, and close-out

**Files:**
- Modify: `_memory/2026-09-15-artifacts-page-exploration.md` (closing entry), `_memory/README.md`
- Modify: `apps/frontend/docs/api-contracts/artifacts.md` only if the walk changes a contract detail

- [ ] **Step 1: Backend gates on the lane DB**

```bash
set -a; source .env; set +a
uv run pytest tests/api/test_frontend_read_artifacts_db.py tests/api/test_design_artifact_feed_db.py tests/api/test_design_artifact_seam_db.py tests/design/test_document_marks_dal_db.py tests/auth/test_identity_substrate.py tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py tests/api/test_frontend_read_app.py -q --ignore-glob='*_live.py'
uv run ruff check platform tests && uv run mypy platform
uv run pytest tests/clue_obs -q   # the logging-discipline guard (no logging.getLogger, no print)
make db-smoke && uv run alembic heads
cd subsystems/clue-design/apps/api && uv run pytest tests/test_document_title_and_archive.py tests/test_write_path_governance.py -q; cd -
```
Expected: all PASS; one head.

- [ ] **Step 2: Frontend gate**

```bash
cd apps/frontend && npm run design-system:build && npm run lint && npm run build && npm test; cd -
```
Expected: clean; the test count grows by the new files' tests.

- [ ] **Step 3: Browser walk on the lane stack**

```bash
./scripts/dev_stack_melbourne.sh up && ./scripts/dev_stack_melbourne.sh status
```
Sign in per `DEV_STACK.md`, then verify on `http://localhost:3020/artifacts` with real documents from at least two projects (create two through chat first if the lane DB is empty):
1. Every project's design artifacts appear once; counts match the database.
2. Search by title and by project title; group by project; the account filter lists only stamped accounts.
3. Open the preview: details, Size only when recorded, Account with the favicon.
4. Open editor: a new thread appears under the project titled with the artifact; the chat lands with the artifact tab open; the URL carries no `open=` after mount.
5. Open source conversation lands on the origin thread.
6. Copy link → the editor route opens the artifact.
7. Ad download in PNG 2x, SVG and PDF; web "Export" (the static-site zip opens locally with styles, fonts and images).
8. Rename from the preview: the library, the project gallery and the editor header agree; an editor open on that document reloads rather than reverting.
9. Archive and restore: the row moves between All and Archived; the project gallery drops it; the editor route still opens it; a published page stays published.
10. Save and unsave; last-viewed ordering after opening previews.
11. A fresh workspace shows the empty state with "Create in chat" → Home.
12. With `CLUE_FRONTEND_READ_ENABLED=false` on the API, `/artifacts` renders `error.tsx`.
13. Telemetry: with the lane's `CLUE_OTEL_TRACES_ENDPOINT` unset, spans are created and dropped (the root logs `tracing.installed exporting=false`), so the check here is the unit level: the marks test's counters, and one library read under `capture_events` producing no event (reads are silent by standard). If an OTLP endpoint is configured on the lane, open one library read's trace and confirm the server span carries `workspace_id` and a child `artifacts.library_read` span.

Record every finding, including failures, in `_memory/2026-09-15-artifacts-page-exploration.md`.

- [ ] **Step 4: Close-out**

Append a closing entry to the memory note (state, commits, verification, owed items) and adjust the README pointer line. Commit:

```bash
git add _memory docs apps/frontend/docs
git commit -m "docs(artifacts): close-out — gates, browser walk findings, owed verification"
```

---

## Self-review

- **Telemetry standard.** Every task names its logging, span, metric and Langfuse obligations against the standard in Global Constraints; reads are silent, writes count, governed tools are observed automatically, frontend catches warn with the feature tag.
- **Spec coverage.** §3.1 read → Task 5; §3.2 marks → Task 6; §3.3 rename → Tasks 7–9; §3.4 archive → Tasks 2, 7–9; §3.5 readers → Task 4; §3.6 erasure → Task 6; §4 migrations → Tasks 2–3; §5.1 layout → Tasks 10, 13; §5.2 gallery → Task 11; §5.3 collections/marks → Task 13; §5.4 actions → Tasks 12–13; §5.5 `?open=` → Task 14; §5.6 header rename → Task 15; §6 lane → Task 1; §7 testing/walk → every task + Task 16; §9 order → task order.
- **Placeholders.** Task 8 Step 1 asks the implementer to align the create/finalize bodies with the design API's actual routes and to copy the `client` fixture from a sibling suite. Everything else is concrete.
- **Type consistency.** `workspace_design_documents` row keys (Task 4) match `_wire` (Task 5); `design_document_card_fields` keys match both consumers; `ToggleRef.value` accepts `str | None` for `archived_at`; `LibraryArtifact.documentId` feeds `renameArtifactDocument` / `setArtifactArchived` / `exportAdArtifact` (Tasks 12–13); `openArtifactFromParam` takes `{ openId, artifacts }` in test and use; `useImageExportController({ title, onExport })` matches the preview's call.
