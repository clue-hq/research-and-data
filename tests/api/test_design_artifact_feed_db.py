"""Slice 1 — the project's design-artifact feed (DB-gated).

``GET /api/v1/projects/{project_id}/design-artifacts`` is the gallery's list read. The
document row carries a workspace, not a project, so the project binding is the design
**leg**: the web documents named by the legs of this project's threads, deduplicated to
one row per document. Same fail-closed workspace posture as the W1.3 single-artifact
sibling (``test_design_artifact_seam_db.py``), whose harness this mirrors.

The ratified v1 gaps these tests pin: a document no leg names belongs to no project and
is listed nowhere; ``scene`` documents never appear.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api import build_tool_invoker, create_projections_app
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_config import Settings, load_settings
from clue_design import legs as design_legs
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import fixture_membership_id, seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_gallery_feed_test"
_AUTHENTICATED_AT = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


def _settings() -> Settings:
    return load_settings(_env_file=None, chat_enabled=True)


def _principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=USER_ID),
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=_AUTHENTICATED_AT,
    )


def _app(conn: Any, *, settings: Settings) -> Any:
    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=settings,
            conn_factory=cf,
        ),
        settings=settings,
        conn_factory=cf,
        manage_db_lifespan=False,
        chat_principal_resolver=_principal,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _feed(conn: Any, *, workspace_id: str, project_id: str) -> list[dict[str, Any]]:
    app = _app(conn, settings=_settings())
    async with _client(app) as client:
        response = await client.get(
            f"/api/v1/projects/{project_id}/design-artifacts",
            headers={"X-Workspace-Id": workspace_id},
        )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert isinstance(data, list)
    return data


async def _seed_design_document(
    conn: Any,
    *,
    workspace_id: str,
    document_id: str,
    doc_kind: str = "web",
    title: str = "Landing page",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_document"
            " (id, workspace_id, title, status, doc_kind, current_scene_json, current_version)"
            " VALUES (:id, :w, :title, 'draft', :kind, CAST(:scene AS jsonb), 0)"
        ),
        {"id": document_id, "w": workspace_id, "title": title, "kind": doc_kind, "scene": "{}"},
    )


async def _seed_thread(conn: Any, *, workspace_id: str, project_id: str, thread_id: str) -> str:
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user)"
        ),
        {"id": thread_id, "workspace": workspace_id, "project": project_id, "user": USER_ID},
    )
    return thread_id


async def _seed_leg(
    conn: Any,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    document_id: str | None,
    created_at: datetime | None = None,
) -> str:
    """Open one leg on ``thread_id``, optionally naming a document and a birth time.

    ``created_at`` is set explicitly where a test cares which leg is the *latest*: every
    row born in one transaction shares ``now()``, so the ordering would otherwise tie.
    """

    execution_id = uuid5(NAMESPACE_URL, f"gallery-feed:{workspace_id}:{thread_id}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {"id": execution_id, "workspace": workspace_id, "project": project_id, "hash": "0" * 64},
    )
    leg = await design_legs.open_leg(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        parent_execution_id=execution_id,
        document_id=document_id,
    )
    leg_id = str(leg["id"])
    if created_at is not None:
        await conn.execute(
            text("UPDATE design_leg SET created_at = :born WHERE id = :id"),
            {"born": created_at, "id": leg_id},
        )
    return leg_id


def test_each_project_lists_only_the_documents_its_own_threads_worked_on(
    require_chat_db: None,
) -> None:
    """THE requirement: two projects in one workspace never see each other's artifacts."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            first = await _seed_project_row(conn, "ws-gallery-cross", name="Gallery one")
            workspace_id = first.workspace_id
            second = await _seed_project_row(conn, workspace_id, name="Gallery two")
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)

            for project, thread_id, document_id, title in (
                (first, "thr_gallery_one", "doc_gallery_one", "One"),
                (second, "thr_gallery_two", "doc_gallery_two", "Two"),
            ):
                await _seed_design_document(
                    conn, workspace_id=workspace_id, document_id=document_id, title=title
                )
                await _seed_thread(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                )
                await _seed_leg(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    document_id=document_id,
                )

            first_feed = await _feed(conn, workspace_id=workspace_id, project_id=first.project_id)
            second_feed = await _feed(conn, workspace_id=workspace_id, project_id=second.project_id)

            assert [item["id"] for item in first_feed] == ["doc_gallery_one"]
            assert [item["id"] for item in second_feed] == ["doc_gallery_two"]
            item = first_feed[0]
            assert item["project_id"] == first.project_id
            assert item["document_id"] == "doc_gallery_one"
            assert item["kind"] == "web"
            assert item["title"] == "One"
            assert item["status"] == "draft"
            assert item["current_version_id"] == "0"
            assert item["origin_thread_id"] == "thr_gallery_one"
            assert set(item) == {
                "id",
                "project_id",
                "document_id",
                "kind",
                "title",
                "status",
                "current_version_id",
                "created_at",
                "updated_at",
                "origin_thread_id",
            }
            assert datetime.fromisoformat(item["created_at"]).tzinfo is not None
            assert datetime.fromisoformat(item["updated_at"]).tzinfo is not None

    run_async(scenario())


def test_a_foreign_workspaces_documents_are_invisible(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ours = await _seed_project_row(conn, "ws-gallery-ours", name="Gallery ours")
            theirs = await _seed_project_row(conn, "ws-gallery-theirs", name="Gallery theirs")
            await seed_principal(conn, workspace_id=ours.workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn, workspace_id=theirs.workspace_id, document_id="doc_gallery_foreign"
            )
            await _seed_thread(
                conn,
                workspace_id=theirs.workspace_id,
                project_id=theirs.project_id,
                thread_id="thr_gallery_foreign",
            )
            await _seed_leg(
                conn,
                workspace_id=theirs.workspace_id,
                project_id=theirs.project_id,
                thread_id="thr_gallery_foreign",
                document_id="doc_gallery_foreign",
            )
            # ``design_leg.document_id`` carries no foreign key, so one of our own legs can
            # name their document id. The document's workspace pin is what keeps it invisible.
            await _seed_thread(
                conn,
                workspace_id=ours.workspace_id,
                project_id=ours.project_id,
                thread_id="thr_gallery_reaching",
            )
            await _seed_leg(
                conn,
                workspace_id=ours.workspace_id,
                project_id=ours.project_id,
                thread_id="thr_gallery_reaching",
                document_id="doc_gallery_foreign",
            )

            assert (
                await _feed(conn, workspace_id=ours.workspace_id, project_id=ours.project_id) == []
            )

            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                across = await client.get(
                    f"/api/v1/projects/{theirs.project_id}/design-artifacts",
                    headers={"X-Workspace-Id": ours.workspace_id},
                )
            assert across.status_code == 404
            assert across.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    run_async(scenario())


def test_a_project_with_no_legs_lists_nothing(require_chat_db: None) -> None:
    """Ruling 1's accepted gap: a document no leg names belongs to no project."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-empty", name="Gallery empty")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn, workspace_id=project.workspace_id, document_id="doc_gallery_orphan"
            )
            await _seed_thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id="thr_gallery_empty",
            )

            assert (
                await _feed(conn, workspace_id=project.workspace_id, project_id=project.project_id)
                == []
            )

    run_async(scenario())


def test_two_legs_on_one_document_list_it_once_with_the_latest_legs_thread(
    require_chat_db: None,
) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-dedup", name="Gallery dedup")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn, workspace_id=workspace_id, document_id="doc_gallery_shared"
            )
            born = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
            for thread_id, offset in (("thr_gallery_first", 0), ("thr_gallery_latest", 1)):
                await _seed_thread(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                )
                await _seed_leg(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    document_id="doc_gallery_shared",
                    created_at=born + timedelta(hours=offset),
                )

            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            assert [item["id"] for item in feed] == ["doc_gallery_shared"]
            assert feed[0]["origin_thread_id"] == "thr_gallery_latest"

    run_async(scenario())


def test_a_leg_with_no_document_contributes_nothing(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-null", name="Gallery null")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn, workspace_id=workspace_id, document_id="doc_gallery_named"
            )
            await _seed_thread(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id="thr_gallery_unnamed",
            )
            await _seed_leg(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id="thr_gallery_unnamed",
                document_id=None,
            )
            await _seed_thread(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id="thr_gallery_named",
            )
            await _seed_leg(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id="thr_gallery_named",
                document_id="doc_gallery_named",
            )

            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            assert [item["id"] for item in feed] == ["doc_gallery_named"]
            assert feed[0]["origin_thread_id"] == "thr_gallery_named"

    run_async(scenario())


def test_a_scene_document_is_excluded(require_chat_db: None) -> None:
    """Ruling 3: the gallery serves web documents only."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-scene", name="Gallery scene")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            for document_id, doc_kind, thread_id in (
                ("doc_gallery_web", "web", "thr_gallery_web"),
                ("doc_gallery_scene", "scene", "thr_gallery_scene"),
            ):
                await _seed_design_document(
                    conn,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    doc_kind=doc_kind,
                )
                await _seed_thread(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                )
                await _seed_leg(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    document_id=document_id,
                )

            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            assert [item["id"] for item in feed] == ["doc_gallery_web"]

    run_async(scenario())
