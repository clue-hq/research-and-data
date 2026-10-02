"""``/frontend/v1/projects/{id}/instructions`` — one document at ``project/instructions.md``.

The project home's Instructions panel has exactly one document behind it, and this walks its whole
life against the real tables: empty before anything is written, created by a PUT that carries no
revision, edited by a PUT that carries the one it read, refused when the revision it carries is
stale, refused again when a second create is attempted over an existing document, and refused once
the project is archived. Another workspace's project is absent rather than refused.

The app is the real projections app the documents walk uses, so the assertions are about what a
browser receives rather than what the store underneath it does.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

from clue_api.frontend_read.app import FRONTEND_READ_PREFIX
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.api.test_frontend_read_project_documents_db import _app, _client
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WS = "ws_project_instructions_http"


async def _put(
    client: httpx.AsyncClient, project_id: str, body: str, revision: int | None
) -> httpx.Response:
    return await client.put(
        f"{FRONTEND_READ_PREFIX}/projects/{project_id}/instructions",
        json={"body": body, "expected_revision": revision},
        headers={"X-Workspace-Id": WS},
    )


def test_instructions_create_edit_conflict_and_archived_refusal(tmp_path):
    async def scenario():
        async with rollback_conn() as conn:
            project = await seed_project(conn, WS, name="Instructed")
            await conn.execute(
                text("UPDATE project SET status='active' WHERE project_id=:id"),
                {"id": project.project_id},
            )
            storage = FsStorage(tmp_path)
            path = f"{FRONTEND_READ_PREFIX}/projects/{project.project_id}/instructions"
            async with _client(_app(conn, storage)) as client:
                assert (await client.get(path, headers={"X-Workspace-Id": WS})).json() == {
                    "data": None
                }

                created = await _put(
                    client, project.project_id, "Always lead with the ROI case.", None
                )
                assert created.status_code == 200, created.text
                assert created.json()["data"]["body"] == "Always lead with the ROI case."
                assert created.json()["data"]["revision"] == 1

                fetched = await client.get(path, headers={"X-Workspace-Id": WS})
                assert fetched.json()["data"]["revision"] == 1
                assert fetched.json()["data"]["body"] == "Always lead with the ROI case."

                # The panel draws it; the Plan/Gallery document feed must not draw a second card
                # for it (spec §1.4). It is still a document of this project — by id, and in the
                # agent's mounted library — it is only absent from this list.
                listed = await client.get(
                    f"{FRONTEND_READ_PREFIX}/projects/{project.project_id}/documents",
                    headers={"X-Workspace-Id": WS},
                )
                assert listed.status_code == 200, listed.text
                assert "project/instructions.md" not in [
                    document["path"] for document in listed.json()["data"]["documents"]
                ]

                edited = await _put(client, project.project_id, "Lead with ROI. Never discount.", 1)
                assert edited.status_code == 200, edited.text
                assert edited.json()["data"]["revision"] == 2
                assert edited.json()["data"]["body"] == "Lead with ROI. Never discount."

                stale = await _put(client, project.project_id, "stale", 1)
                assert stale.status_code == 409, stale.text
                assert stale.json()["error"]["code"] == "DOCUMENT_REVISION_CONFLICT"

                twice = await _put(client, project.project_id, "again", None)
                assert twice.status_code == 409, twice.text
                assert twice.json()["error"]["code"] == "DOCUMENT_REVISION_CONFLICT"

                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT path, kind, version, status, produced_by_turn_id "
                                "FROM brand_knowledge_document WHERE project_id=:p "
                                "ORDER BY version DESC LIMIT 1"
                            ),
                            {"p": project.project_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert (row["path"], row["kind"], row["version"], row["status"]) == (
                    "project/instructions.md",
                    "project-instructions",
                    2,
                    "ready",
                )
                assert row["produced_by_turn_id"] is None

                touched = (
                    await conn.execute(
                        text("SELECT updated_at > created_at FROM project WHERE project_id=:p"),
                        {"p": project.project_id},
                    )
                ).scalar_one()
                assert touched is True

                await conn.execute(
                    text(
                        "UPDATE project SET status='archived', archived_at=now() "
                        "WHERE project_id=:id"
                    ),
                    {"id": project.project_id},
                )
                refused = await _put(client, project.project_id, "x", 2)
                assert refused.status_code == 409, refused.text
                assert refused.json()["error"]["code"] == "PROJECT_ARCHIVED"

                foreign = await client.get(path, headers={"X-Workspace-Id": "ws_other"})
                assert foreign.status_code == 404

    run_async(scenario())


def test_blank_body_is_refused_and_writes_nothing(tmp_path):
    """A blank create is a 422 the writer decides, not a version of an empty document."""

    async def scenario():
        async with rollback_conn() as conn:
            project = await seed_project(conn, WS, name="Blank")
            storage = FsStorage(tmp_path)
            async with _client(_app(conn, storage)) as client:
                blank = await _put(client, project.project_id, "   \n", None)
                assert blank.status_code == 422, blank.text
                assert blank.json()["error"]["code"] == "PROJECT_DOCUMENT_BODY_EMPTY"
                versions = await conn.scalar(
                    text(
                        "SELECT count(*) FROM brand_knowledge_document "
                        "WHERE project_id=:p AND path='project/instructions.md'"
                    ),
                    {"p": project.project_id},
                )
                assert versions == 0

    run_async(scenario())
