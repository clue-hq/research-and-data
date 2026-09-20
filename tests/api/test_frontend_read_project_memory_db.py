"""``/frontend/v1/projects/{id}/memory`` — the project home's notes, on the real write seam.

The walk is the panel's whole life against the real tables: an empty project lists nothing, a
typed note goes through :class:`~clue_memory.WriteSeam` (so it is a *memory*, reconciled and
journaled, not a row this surface invented), the list shows it beside the thread it came out of,
an edit retires the old record and submits the new one in one transaction, a removal invalidates
it, and a repeat removal is a 404 rather than a second write.

Three refusals are asserted because each is a different answer to the human:

* a note whose body carries verbatim contact data is **rejected** by the seam's fail-closed
  subject binding — ``422 MEMORY_REJECTED``, and on a PUT the old note survives, because the
  retire and the submit share one transaction;
* the workspace (or deploy) kill-switch being off is ``409 MEMORY_DISABLED``, on the read too —
  the panel says memory is off rather than drawing an empty list that looks like "no notes";
* an archived project refuses every write with ``409 PROJECT_ARCHIVED``, as its neighbours do.

The connection seam is a **savepoint** factory, not the plain pass-through the other
frontend-read suites use: what the rejected-PUT case asserts is that the route's transaction
rolls back, so the test's seam has to have the production ``clue_db.transaction`` semantics
(commit on success, roll back on a raise) rather than swallowing them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.app import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_api.thread_store import create_thread
from clue_config import MemoryCaps, Settings, load_settings
from clue_core import ReconcileJudgment, ReconcileVerdictKind
from clue_memory import WriteSeam
from tests._workspace import seed_project
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.memory.conftest import ScriptedJudge

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_project_memory_http"
NOTE = "Prefer short subject lines."
EDITED_NOTE = "Prefer subject lines under 40 characters."
#: Verbatim contact data with no resolved subject — the seam's fail-closed binding refuses it.
FACT_SHAPED = "Acme's CFO is Jane Doe (jane@acme.com)."


def _settings(**overrides: object) -> Settings:
    """The test's own settings: ``local_header`` + auth off is what allows local mutations."""

    return load_settings(
        _env_file=None,
        **{
            "frontend_read_enabled": True,
            "auth_enabled": False,
            "auth_environment": "local",
            "projections_auth_mode": "local_header",
            "memory_enabled": True,
            **overrides,
        },
    )


def _savepoint_factory(conn: AsyncConnection):
    """A ``ConnFactory`` with production transaction semantics over the test's connection.

    ``clue_db.transaction`` commits on success and rolls back on a raise; a savepoint is the same
    contract nested inside the suite's rolled-back outer transaction, so a route that raises
    leaves nothing behind — which is exactly what the rejected-PUT case is about.
    """

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncConnection]:
        async with conn.begin_nested():
            yield conn

    return _factory


def _app(
    conn: AsyncConnection,
    *,
    settings: Settings | None = None,
    with_memory: bool = True,
) -> FastAPI:
    resolved = settings if settings is not None else _settings()
    judge = ScriptedJudge(ReconcileJudgment(verdict=ReconcileVerdictKind.ADD, rationale="scripted"))
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=resolved,
        conn_factory=_savepoint_factory(conn),
        manage_db_lifespan=False,
        memory_write_factory=(
            (lambda c: WriteSeam(c, judge, settings=resolved, caps=MemoryCaps()))
            if with_memory
            else None
        ),
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://memory")


def test_notes_list_add_edit_remove_and_honest_rejection() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WORKSPACE, name="Remembered")
            await conn.execute(
                text("UPDATE project SET status = 'active' WHERE project_id = :id"),
                {"id": project.project_id},
            )
            thread = await create_thread(
                conn,
                thread_id="thr_mem_http",
                workspace_id=WORKSPACE,
                project_id=project.project_id,
                title="Kickoff",
            )
            base = f"{FRONTEND_READ_PREFIX}/projects/{project.project_id}/memory"
            headers = {"X-Workspace-Id": WORKSPACE}

            async with _client(_app(conn)) as client:
                empty = await client.get(base, headers=headers)
                assert empty.status_code == 200, empty.text
                assert empty.json() == {"data": []}

                added = await client.post(
                    base,
                    json={"text": NOTE, "source_thread_id": thread.id},
                    headers=headers,
                )
                assert added.status_code == 201, added.text
                note = added.json()["data"]
                assert note["text"] == NOTE
                assert note["source_thread_id"] == thread.id
                assert note["source_thread_title"] == "Kickoff"
                assert added.json()["verdict"] == "add"

                listed = (await client.get(base, headers=headers)).json()["data"]
                assert [item["id"] for item in listed] == [note["id"]]

                # A note whose source thread belongs to nothing in this project is refused
                # before the seam is ever asked.
                foreign = await client.post(
                    base,
                    json={"text": "x", "source_thread_id": "thr_not_here"},
                    headers=headers,
                )
                assert foreign.status_code == 422, foreign.text
                assert foreign.json()["error"]["code"] == "MEMORY_SOURCE_NOT_IN_PROJECT"

                # A refused edit leaves the note it was retiring exactly where it was: the
                # retire and the submit are one transaction.
                refused_edit = await client.put(
                    f"{base}/{note['id']}", json={"text": FACT_SHAPED}, headers=headers
                )
                assert refused_edit.status_code == 422, refused_edit.text
                assert refused_edit.json()["error"]["code"] == "MEMORY_REJECTED"
                survived = (await client.get(base, headers=headers)).json()["data"]
                assert [item["id"] for item in survived] == [note["id"]]

                edited = await client.put(
                    f"{base}/{note['id']}", json={"text": EDITED_NOTE}, headers=headers
                )
                assert edited.status_code == 200, edited.text
                successor = edited.json()["data"]
                assert successor["id"] != note["id"]
                listed = (await client.get(base, headers=headers)).json()["data"]
                assert [item["text"] for item in listed] == [EDITED_NOTE]
                assert listed[0]["source_thread_id"] is None
                assert listed[0]["source_thread_title"] is None

                # The old record is retired, not deleted — a second edit of it is a 404.
                stale = await client.put(
                    f"{base}/{note['id']}", json={"text": "again"}, headers=headers
                )
                assert stale.status_code == 404, stale.text
                assert stale.json()["error"]["code"] == "MEMORY_NOT_FOUND"

                # A fresh note is rejected the same way an edited one is.
                fact = await client.post(base, json={"text": FACT_SHAPED}, headers=headers)
                assert fact.status_code == 422, fact.text
                assert fact.json()["error"]["code"] == "MEMORY_REJECTED"
                assert fact.json()["error"]["message"]

                removed = await client.delete(f"{base}/{successor['id']}", headers=headers)
                assert removed.status_code == 204, removed.text
                assert (await client.get(base, headers=headers)).json() == {"data": []}
                repeat = await client.delete(f"{base}/{successor['id']}", headers=headers)
                assert repeat.status_code == 404, repeat.text

                # A sibling project's note is not this project's to touch, even for the same
                # tenant: the path names the project, so the record must be in it.
                sibling = await seed_project(conn, WORKSPACE, name="Sibling")
                await conn.execute(
                    text("UPDATE project SET status = 'active' WHERE project_id = :id"),
                    {"id": sibling.project_id},
                )
                sibling_base = f"{FRONTEND_READ_PREFIX}/projects/{sibling.project_id}/memory"
                sibling_note = await client.post(
                    sibling_base, json={"text": "Sibling note."}, headers=headers
                )
                assert sibling_note.status_code == 201, sibling_note.text
                sibling_id = sibling_note.json()["data"]["id"]
                crossed = await client.delete(f"{base}/{sibling_id}", headers=headers)
                assert crossed.status_code == 404, crossed.text
                still_there = (await client.get(sibling_base, headers=headers)).json()["data"]
                assert [item["id"] for item in still_there] == [sibling_id]

                # Another workspace's project is absent, not refused.
                foreign_ws = await client.get(base, headers={"X-Workspace-Id": "ws_someone_else"})
                assert foreign_ws.status_code == 404, foreign_ws.text
                assert foreign_ws.json()["error"]["code"] == "PROJECT_NOT_FOUND"

            # No gateway in this process ⇒ no write seam: the list still serves, writes refuse.
            async with _client(_app(conn, with_memory=False)) as client:
                assert (await client.get(base, headers=headers)).status_code == 200
                unavailable = await client.post(base, json={"text": "later"}, headers=headers)
                assert unavailable.status_code == 503, unavailable.text
                assert unavailable.json()["error"]["code"] == "MEMORY_UNAVAILABLE"

            # Memory off is a stated refusal, on the read too.
            async with _client(_app(conn, settings=_settings(memory_enabled=False))) as client:
                off = await client.get(base, headers=headers)
                assert off.status_code == 409, off.text
                assert off.json()["error"]["code"] == "MEMORY_DISABLED"

            await conn.execute(
                text(
                    "UPDATE project SET status = 'archived', archived_at = now() "
                    "WHERE project_id = :id"
                ),
                {"id": project.project_id},
            )
            async with _client(_app(conn)) as client:
                archived = await client.post(base, json={"text": "later"}, headers=headers)
                assert archived.status_code == 409, archived.text
                assert archived.json()["error"]["code"] == "PROJECT_ARCHIVED"

    run_async(scenario())
