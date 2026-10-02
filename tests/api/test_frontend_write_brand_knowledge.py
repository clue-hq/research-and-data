"""Durable, versioned human edits behind the existing Knowledge read seam."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_wiring import install_auth_wiring
from clue_api.frontend_read.brand_knowledge import KnowledgeDocumentUpdate, save_knowledge_document
from clue_auth import RequestPrincipal
from clue_storage import read_verified_artifact
from tests.api.test_frontend_read_brand_knowledge import (
    _BASE,
    _WS,
    ICP,
    _app,
    _document,
    _get,
    _seed,
)
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _put(conn, storage, doc_id, body, revision=2, ws=_WS, principal=None):
    app = _app(conn, storage)
    if principal:
        install_auth_wiring(app, service=Mock())

        @app.middleware("http")
        async def attach_principal(request, call_next):
            request.state.clue_principal = principal
            return await call_next(request)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://knowledge"
    ) as client:
        return await client.put(
            f"{_BASE}/knowledge/documents/{doc_id}",
            headers={"X-Workspace-Id": ws},
            json={"body": body, "expectedRevision": revision},
        )


def test_save_appends_version_preserves_original_and_round_trips_markdown():
    async def scenario():
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            old_id = ids["overview_v2"]
            original = await conn.scalar(
                text("SELECT artifact_key FROM brand_knowledge_document WHERE document_id=:id"),
                {"id": old_id},
            )
            _, original_bytes = await read_verified_artifact(
                conn, storage, storage_key=original, workspace_id=_WS
            )
            body = "\n\n# Human edit\n\n| A | B |\n| - | - |\n| x | y |\n\n> quote\n\n"
            response = await _put(conn, storage, old_id, body)
            assert response.status_code == 200, response.text
            saved = response.json()
            assert saved["version"] == 3 and saved["id"] != str(old_id)
            assert saved["markdown"] == body
            assert saved["frontMatter"]["user_edit"]["source_document_id"] == str(old_id)
            assert saved["sources"][0]["url"] == "https://www.insighthealth.ai/"
            fresh = await _get(conn, storage, f"/knowledge/documents/{saved['id']}")
            assert fresh.json()["markdown"] == body
            _, after = await read_verified_artifact(
                conn, storage, storage_key=original, workspace_id=_WS
            )
            assert after == original_bytes
            assert (
                await conn.scalar(
                    text("SELECT status FROM brand_knowledge_document WHERE document_id=:id"),
                    {"id": old_id},
                )
                == "superseded"
            )
            tree = (await _get(conn, storage, "/knowledge")).json()
            assert tree["folders"][0]["documents"][0]["id"] == saved["id"]
            # Replaying a stale write never overwrites the committed version.
            conflict = await _put(conn, storage, old_id, "# stale")
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "DOCUMENT_REVISION_CONFLICT"
            # Saving again uses the newly returned ID/version; an empty body is valid Markdown.
            empty = await _put(conn, storage, saved["id"], "", revision=3)
            assert empty.status_code == 200 and empty.json()["markdown"] == ""

    run_async(scenario())


def test_wrong_revision_other_tenant_and_missing_storage_cannot_write():
    async def scenario():
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            doc = ids["overview_v2"]
            assert (await _put(conn, storage, doc, "# wrong", revision=1)).status_code == 409
            assert (
                await _put(conn, storage, doc, "# foreign", ws="another-workspace")
            ).status_code == 404
            assert (await _put(conn, None, doc, "# no storage")).status_code == 503
            assert (await _put(conn, storage, doc, "# invalid", revision=0)).status_code == 422
            assert (
                await conn.scalar(
                    text("SELECT version FROM brand_knowledge_document WHERE document_id=:id"),
                    {"id": doc},
                )
                == 2
            )

    run_async(scenario())


def test_unchanged_save_does_not_create_a_version():
    async def scenario():
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            doc = ids["overview_v2"]
            original = (await _get(conn, storage, f"/knowledge/documents/{doc}")).json()
            saved = await _put(conn, storage, doc, original["markdown"])
            assert saved.status_code == 200 and saved.json()["id"] == str(doc)
            assert saved.json()["version"] == 2

    run_async(scenario())


def test_editing_confirmed_icp_creates_proposal_and_preserves_prior_approval():
    async def scenario():
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            brand, _ = await _seed(conn, storage)
            doc = await _document(
                conn,
                DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn)),
                ws=_WS,
                brand_id=brand,
                folder="audience",
                path="audience/approved-icp.md",
                kind="icp-definition",
                version=1,
                status="confirmed",
                body=ICP.replace(
                    "---\n\n",
                    "confirmed_by: original-approver\nconfirmed_at: '2026-09-12'\n"
                    "confirmed_for_project_id: old-project\nproduct_selection_version: 3\n---\n\n",
                ),
            )
            response = await _put(conn, storage, doc, "# Revised ICP", revision=1)
            assert response.status_code == 200, response.text
            saved = response.json()
            assert saved["status"] == "proposed"
            assert saved["frontMatter"]["status"] == "proposed"
            assert "confirmed_by" not in saved["frontMatter"]
            assert "confirmed_at" not in saved["frontMatter"]
            original = (await _get(conn, storage, f"/knowledge/documents/{doc}")).json()
            assert original["frontMatter"]["confirmed_by"] == "original-approver"
            assert (
                await conn.scalar(
                    text("SELECT status FROM brand_knowledge_document WHERE document_id=:id"),
                    {"id": doc},
                )
                == "confirmed"
            )

    run_async(scenario())


def test_failed_storage_write_rolls_back_and_preserves_the_original():
    async def scenario():
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            before = await conn.scalar(text("SELECT count(*) FROM artifact"))

            async def refuse(*args, **kwargs):
                raise OSError("storage unavailable")

            storage.put = refuse
            with pytest.raises(OSError):
                async with conn.begin_nested():
                    await save_knowledge_document(
                        conn,
                        storage,
                        workspace_id=_WS,
                        document_id=ids["overview_v2"],
                        update=KnowledgeDocumentUpdate(body="# Changed", expected_revision=2),
                        user_id="editor",
                    )
            assert await conn.scalar(text("SELECT count(*) FROM artifact")) == before
            original = (
                await _get(conn, storage, f"/knowledge/documents/{ids['overview_v2']}")
            ).json()
            assert original["version"] == 2 and original["status"] == "ready"

    run_async(scenario())


def test_viewer_principal_cannot_save():
    async def scenario():
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            viewer = RequestPrincipal(
                user_id="viewer",
                membership_id="member",
                workspace_id=_WS,
                role_key="viewer",
                permissions=frozenset({"project.read"}),
                authenticated_at=datetime.now(UTC),
            )
            response = await _put(conn, storage, ids["overview_v2"], "# refused", principal=viewer)
            assert response.status_code == 403
            assert len(storage.blobs) == 6

    run_async(scenario())
