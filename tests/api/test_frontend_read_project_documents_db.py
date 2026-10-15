"""``/frontend/v1/projects/{id}/documents`` — the list, the one, and the human's versioned PUT.

The walk is the Plan tab's whole life against the real tables: a project with a plan and two
audience documents lists all three with the titles the tab draws, the plan opens with its markdown
and front matter, a human's edit appends the next version stamped ``user_edit``, the same edit sent
twice is refused with ``DOCUMENT_REVISION_CONFLICT`` rather than overwriting, and another project's
document is absent — the same 404 a document that never existed gets.

The app is the real projections app with the frontend-read flag on, so the assertions are about
status codes and payloads a browser would actually receive, not about the store underneath it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.project_documents import PLAN_PATH, ProjectPlanWrite, write_project_plan
from clue_api.frontend_read.app import FRONTEND_READ_PREFIX
from clue_api.knowledge_bytes import clear_knowledge_byte_cache
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.arv2.icp_fixture import seed_icp_document
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_project_documents_http"

PLAN_BODY = """# Q4 expansion plan

## Outcome
Twenty qualified conversations with GI-focused ASCs by the end of the quarter.
"""

ICP_BODY = """---
kind: icp-definition
icp_key: gi-dac
title: GI-focused ambulatory surgery centers
status: proposed
---

# GI groups

Body.
"""

PERSONA_BODY = """---
kind: audience-persona
icp_key: gi-dac
---

# Personas

Body.
"""


def _app(conn: AsyncConnection, storage: FsStorage | None) -> FastAPI:
    """The real projections app, its DB seam bound to the test's connection.

    The auth settings are the test's own rather than the box's: ``local_header`` + auth off is what
    makes ``allow_local_mutations`` true, which is the mode the PUT is exercised in here. A box
    whose ``.env`` enables auth would otherwise turn every write into a 401.
    """

    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(
            _env_file=None,
            frontend_read_enabled=True,
            auth_enabled=False,
            auth_environment="local",
            projections_auth_mode="local_header",
        ),
        conn_factory=conn_session_factory(conn),
        ingestion_storage=storage,
        manage_db_lifespan=False,
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://documents")


async def _get(
    conn: AsyncConnection,
    storage: FsStorage | None,
    path: str,
    *,
    workspace_id: str = WORKSPACE,
) -> httpx.Response:
    async with _client(_app(conn, storage)) as client:
        return await client.get(
            f"{FRONTEND_READ_PREFIX}{path}", headers={"X-Workspace-Id": workspace_id}
        )


async def _put(
    conn: AsyncConnection,
    storage: FsStorage | None,
    path: str,
    *,
    body: str,
    expected_revision: int,
    workspace_id: str = WORKSPACE,
    app: FastAPI | None = None,
) -> httpx.Response:
    async with _client(app or _app(conn, storage)) as client:
        return await client.put(
            f"{FRONTEND_READ_PREFIX}{path}",
            headers={"X-Workspace-Id": workspace_id},
            json={"body": body, "expected_revision": expected_revision},
        )


async def _seed(conn: AsyncConnection, storage: FsStorage) -> tuple[str, str, dict[str, str]]:
    """One project with a plan, a project-local ICP and its persona document."""

    project = await seed_project(conn, WORKSPACE)
    plan = await write_project_plan(
        conn,
        storage,
        ProjectPlanWrite(
            workspace_id=project.workspace_id,
            brand_id=str(project.brand_id),
            project_id=project.project_id,
            turn_id=uuid4(),
            user_id="usr_project_documents",
            body=PLAN_BODY,
            expected_version=None,
        ),
    )
    icp_id, _, _ = await seed_icp_document(
        conn,
        storage,
        workspace_id=project.workspace_id,
        brand_id=str(project.brand_id),
        project_id=project.project_id,
        path="audience/icp-gi-dac.md",
        status="proposed",
        body=ICP_BODY,
    )
    persona_id, _, _ = await seed_icp_document(
        conn,
        storage,
        workspace_id=project.workspace_id,
        brand_id=str(project.brand_id),
        project_id=project.project_id,
        path="audience/persona-gi-dac.md",
        kind="audience-persona",
        status="ready",
        body=PERSONA_BODY,
    )
    return (
        project.workspace_id,
        project.project_id,
        {
            "plan": str(plan.document_id),
            "icp": str(icp_id),
            "persona": str(persona_id),
        },
    )


def test_the_list_names_every_document_this_project_owns(tmp_path: Any) -> None:
    """Every document is titled by its own text: front matter ``title``, else its first heading.

    No kind is named by what the platform thinks it is (founder ruling 2026-09-14) — the agent
    writes any document under ``project/``, so a title invented here would be the one place a
    document is called something it never called itself.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            _, project_id, ids = await _seed(conn, storage)

            response = await _get(conn, storage, f"/projects/{project_id}/documents")

            assert response.status_code == 200, response.text
            documents = response.json()["data"]["documents"]
            assert [(row["path"], row["kind"], row["title"]) for row in documents] == [
                (
                    "audience/icp-gi-dac.md",
                    "icp-definition",
                    "GI-focused ambulatory surgery centers",
                ),
                ("audience/persona-gi-dac.md", "audience-persona", "Personas"),
                # The plan body says nothing about what it is, so the row calls it a document.
                (PLAN_PATH, "document", "Q4 expansion plan"),
            ]
            plan = documents[-1]
            assert plan["id"] == ids["plan"]
            assert (plan["version"], plan["status"], plan["icp_key"]) == (1, "ready", None)
            assert plan["updated_at"].endswith("Z")
            assert [row["icp_key"] for row in documents] == ["gi-dac", "gi-dac", None]
            # Another tenant's header sees this project as empty, never as someone else's.
            other = await _get(
                conn, storage, f"/projects/{project_id}/documents", workspace_id="ws_someone_else"
            )
            assert other.status_code == 200 and other.json()["data"]["documents"] == []

    run_async(scenario())


def test_the_detail_serves_the_markdown_and_front_matter_the_editor_loads(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            _, project_id, ids = await _seed(conn, storage)

            response = await _get(conn, storage, f"/projects/{project_id}/documents/{ids['plan']}")

            assert response.status_code == 200, response.text
            document = response.json()["data"]
            assert document["id"] == ids["plan"]
            assert document["title"] == "Q4 expansion plan"
            assert document["markdown"] == PLAN_BODY
            # Six stamped facts and not one more: the platform never adds a kind the document
            # did not claim for itself.
            assert "kind" not in document["front_matter"]
            assert document["front_matter"]["project_id"] == project_id
            # A process with no artifact storage says so rather than serving a document without
            # its bytes.
            assert (
                await _get(conn, None, f"/projects/{project_id}/documents/{ids['plan']}")
            ).status_code == 503

    run_async(scenario())


def test_the_put_appends_the_next_version_with_the_humans_edit_stamp(tmp_path: Any) -> None:
    """The save is an append: a new id, the next version, ``user_edit`` in the front matter, and the
    detail route now serving the human's words."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            _, project_id, ids = await _seed(conn, storage)
            path = f"/projects/{project_id}/documents/{ids['plan']}"

            saved = await _put(conn, storage, path, body="# Edited plan\n", expected_revision=1)

            assert saved.status_code == 200, saved.text
            document = saved.json()["data"]
            assert document["version"] == 2 and document["id"] != ids["plan"]
            # The human retyped the document, heading and all, so it is called what they typed.
            assert document["status"] == "ready" and document["title"] == "Edited plan"
            assert document["markdown"] == "# Edited plan\n"
            assert document["front_matter"]["user_edit"] == {
                "user_id": "local-development-user",
                "edited_at": document["front_matter"]["user_edit"]["edited_at"],
                "source_document_id": ids["plan"],
                "source_version": 1,
            }
            fresh = await _get(conn, storage, f"/projects/{project_id}/documents/{document['id']}")
            assert fresh.status_code == 200
            assert fresh.json()["data"]["markdown"] == "# Edited plan\n"
            # The version it was typed over is retired, so the list serves exactly one plan.
            listed = (await _get(conn, storage, f"/projects/{project_id}/documents")).json()
            plans = [row for row in listed["data"]["documents"] if row["path"] == PLAN_PATH]
            assert [(row["id"], row["version"]) for row in plans] == [(document["id"], 2)]

    run_async(scenario())


def test_a_stale_revision_is_refused_and_nothing_is_overwritten(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            _, project_id, ids = await _seed(conn, storage)
            path = f"/projects/{project_id}/documents/{ids['plan']}"
            first = await _put(conn, storage, path, body="# First edit\n", expected_revision=1)
            assert first.status_code == 200, first.text

            stale = await _put(conn, storage, path, body="# Second edit\n", expected_revision=1)

            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "DOCUMENT_REVISION_CONFLICT"
            current = await _get(
                conn, storage, f"/projects/{project_id}/documents/{first.json()['data']['id']}"
            )
            assert current.json()["data"]["markdown"] == "# First edit\n"

    run_async(scenario())


def test_another_projects_document_and_an_empty_body_are_refused(tmp_path: Any) -> None:
    """Scope is identity: another project's document is absent on both verbs. An empty body is a
    422 rather than a saved blank page."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, ids = await _seed(conn, storage)
            other = await seed_project(conn, workspace_id, name="Another project")
            foreign = f"/projects/{other.project_id}/documents/{ids['plan']}"

            assert (await _get(conn, storage, foreign)).status_code == 404
            refused = await _put(conn, storage, foreign, body="# Not yours\n", expected_revision=1)
            assert refused.status_code == 404
            assert refused.json()["error"]["code"] == "PROJECT_DOCUMENT_NOT_FOUND"
            assert (await _get(conn, storage, f"/projects/{other.project_id}/documents")).json()[
                "data"
            ]["documents"] == []

            empty = await _put(
                conn,
                storage,
                f"/projects/{project_id}/documents/{ids['plan']}",
                body="   \n",
                expected_revision=1,
            )
            assert empty.status_code == 422
            assert empty.json()["error"]["code"] == "DOCUMENT_BODY_EMPTY"
            # A missing document id is the same 404 as another project's.
            assert (
                await _get(conn, storage, f"/projects/{project_id}/documents/{uuid4()}")
            ).status_code == 404

    run_async(scenario())


def test_a_process_without_local_mutations_refuses_the_put(tmp_path: Any) -> None:
    """No principal and no local-mutation allowance is a 401 — the Knowledge PUT's rule, here."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            _, project_id, ids = await _seed(conn, storage)
            authenticated = create_projections_app(
                surface=None,  # type: ignore[arg-type]
                tool_invoker=None,  # type: ignore[arg-type]
                settings=load_settings(
                    _env_file=None,
                    frontend_read_enabled=True,
                    auth_enabled=False,
                    projections_auth_mode="authenticated_principal",
                ),
                conn_factory=conn_session_factory(conn),
                ingestion_storage=storage,
                manage_db_lifespan=False,
            )

            response = await _put(
                conn,
                storage,
                f"/projects/{project_id}/documents/{ids['plan']}",
                body="# Anonymous\n",
                expected_revision=1,
                app=authenticated,
            )

            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"

    run_async(scenario())


class _CountingStorage(FsStorage):
    """Filesystem storage that remembers which blobs the route actually read."""

    def __init__(self, root: Any) -> None:
        super().__init__(root)
        self.reads: list[str] = []

    async def get(self, key: str) -> bytes:
        self.reads.append(key)
        return await super().get(key)


def test_the_detail_serves_a_superseded_version_so_its_editor_can_rebase(tmp_path: Any) -> None:
    """M3. A version this project has since superseded still exists, and the editor holding it is
    told so — with its real status — rather than being told the document is gone.

    The PUT already answers a stale revision with "a newer version exists"; a 404 on the same row
    from the GET would leave the Plan tab rendering "document not found" instead of the rebase the
    409 is designed for. Only a document this project does not own — or one that never existed —
    is absent.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, ids = await _seed(conn, storage)
            saved = await _put(
                conn,
                storage,
                f"/projects/{project_id}/documents/{ids['plan']}",
                body="# Edited plan\n",
                expected_revision=1,
            )
            assert saved.status_code == 200, saved.text

            superseded = await _get(
                conn, storage, f"/projects/{project_id}/documents/{ids['plan']}"
            )

            assert superseded.status_code == 200, superseded.text
            document = superseded.json()["data"]
            assert (document["id"], document["version"]) == (ids["plan"], 1)
            assert document["status"] == "superseded"
            assert document["markdown"] == PLAN_BODY
            # It is still only the servable version that the list serves.
            listed = (await _get(conn, storage, f"/projects/{project_id}/documents")).json()
            assert [
                row["version"] for row in listed["data"]["documents"] if row["path"] == PLAN_PATH
            ] == [2]
            # Another project's superseded version is absent, exactly as its servable one is.
            other = await seed_project(conn, workspace_id, name="Another project")
            assert (
                await _get(conn, storage, f"/projects/{other.project_id}/documents/{ids['plan']}")
            ).status_code == 404
            assert (
                await _get(conn, storage, f"/projects/{project_id}/documents/{uuid4()}")
            ).status_code == 404

    run_async(scenario())


def test_the_list_titles_every_document_from_its_own_bytes(tmp_path: Any) -> None:
    """One blob read per row, because no document's title is known without its own text.

    The list used to skip the plan and the persona set — they were titled by what they *were* — and
    open only the ICP-shaped one. Every document now names itself, so every one is read. A document
    whose bytes have vanished is still listed, by the name on its path: a missing object is a reason
    to show less, never a reason to fail the whole tab.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _CountingStorage(tmp_path)
            _, project_id, _ids = await _seed(conn, storage)
            storage.reads.clear()
            clear_knowledge_byte_cache()

            listed = await _get(conn, storage, f"/projects/{project_id}/documents")

            assert listed.status_code == 200, listed.text
            documents = listed.json()["data"]["documents"]
            assert [row["title"] for row in documents] == [
                "GI-focused ambulatory surgery centers",
                "Personas",
                "Q4 expansion plan",
            ]
            assert len(storage.reads) == 3, storage.reads

            # The ICP's bytes vanish: the tab still lists every document, by path-derived name.
            # (A process that already holds the verified bytes keeps serving them — erasure and
            # purge are refused by the database check every read runs — so the cache is cleared
            # to exercise the vanished-blob path.)
            await storage.delete(storage.reads[0])
            clear_knowledge_byte_cache()
            degraded = await _get(conn, storage, f"/projects/{project_id}/documents")
            assert degraded.status_code == 200, degraded.text
            assert [row["title"] for row in degraded.json()["data"]["documents"]] == [
                "icp-gi-dac",
                "Personas",
                "Q4 expansion plan",
            ]

    run_async(scenario())
