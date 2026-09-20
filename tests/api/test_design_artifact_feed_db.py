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

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

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
    updated_at: datetime | None = None,
) -> None:
    """``updated_at`` is set explicitly where a test cares about feed order: every
    row born in one transaction shares ``now()``, so ordering would otherwise tie."""

    await conn.execute(
        text(
            "INSERT INTO design_document"
            " (id, workspace_id, title, status, doc_kind, current_scene_json, current_version)"
            " VALUES (:id, :w, :title, 'draft', :kind, CAST(:scene AS jsonb), 0)"
        ),
        {"id": document_id, "w": workspace_id, "title": title, "kind": doc_kind, "scene": "{}"},
    )
    if updated_at is not None:
        await conn.execute(
            text("UPDATE design_document SET updated_at = :touched WHERE id = :id"),
            {"touched": updated_at, "id": document_id},
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
    documents: Sequence[str] | None = None,
) -> str:
    """Open one leg on ``thread_id``, optionally naming a document and a birth time.

    ``created_at`` is set explicitly where a test cares which leg is the *latest*: every
    row born in one transaction shares ``now()``, so the ordering would otherwise tie.

    Spec §3.2: a leg holds a SET of documents (``design_leg_document``) and its own
    ``document_id`` column means position 0. The DAL's ``open_leg`` writes only the column,
    so this seeder writes the child rows the shipped tool always writes — ``documents``
    names the whole set (default: just ``document_id``), and an explicit empty sequence
    seeds a leg whose column names a document it holds no child row for.
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
    held = (
        tuple(documents)
        if documents is not None
        else ((document_id,) if document_id is not None else ())
    )
    if held:
        await design_legs.add_leg_documents(
            conn,
            workspace_id=workspace_id,
            leg_id=leg_id,
            documents=[
                design_legs.LegDocumentSpec(document_id=held_id, position=position)
                for position, held_id in enumerate(held)
            ],
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
                "artifact_type",
                "width_px",
                "height_px",
                "account",
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
            # The leg's child row is the second wall: ``design_leg_document``'s composite FK
            # refuses a document from another workspace outright, so the reaching leg holds
            # the id in its column and nothing in its set.
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
                documents=(),
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


def test_a_scene_document_lists_beside_a_web_one_with_its_own_kind(
    require_chat_db: None,
) -> None:
    """AD2.1 supersedes Ruling 3's web-only filter: the gallery serves both kinds.

    A ``scene`` document reports ``kind == "ad"`` and a ``web`` document still reports
    ``kind == "web"`` — one project, both kinds, ordering untouched (``updated_at DESC``).
    """

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-scene", name="Gallery scene")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            touched = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
            for document_id, doc_kind, thread_id, age_hours in (
                ("doc_gallery_web", "web", "thr_gallery_web", 1),
                ("doc_gallery_scene", "scene", "thr_gallery_scene", 0),
            ):
                await _seed_design_document(
                    conn,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    doc_kind=doc_kind,
                    updated_at=touched - timedelta(hours=age_hours),
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
            assert [(item["id"], item["kind"]) for item in feed] == [
                ("doc_gallery_scene", "ad"),
                ("doc_gallery_web", "web"),
            ]
            # ``doc_kind`` is read, never leaked: the wire says ``kind``, and the rest
            # is the G-H card set (artifact type and page size ride along).
            assert set(feed[0]) == {
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
                "artifact_type",
                "width_px",
                "height_px",
                "account",
            }

    run_async(scenario())


def test_the_feed_orders_documents_newest_updated_first(require_chat_db: None) -> None:
    """The card order is user-visible: ``updated_at DESC``, whatever the leg order was."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-order", name="Gallery order")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            touched = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
            # Seed in an order that a leg-insertion or id sort would NOT produce.
            for document_id, thread_id, age_hours in (
                ("doc_gallery_middle", "thr_gallery_middle", 1),
                ("doc_gallery_newest", "thr_gallery_newest", 0),
                ("doc_gallery_oldest", "thr_gallery_oldest", 2),
            ):
                await _seed_design_document(
                    conn,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    updated_at=touched - timedelta(hours=age_hours),
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
            assert [item["id"] for item in feed] == [
                "doc_gallery_newest",
                "doc_gallery_middle",
                "doc_gallery_oldest",
            ]

    run_async(scenario())


def test_legs_born_at_the_same_instant_tie_break_on_leg_id(require_chat_db: None) -> None:
    """Two legs with equal ``created_at`` (one transaction shares ``now()``) must still
    pick a deterministic ``origin_thread_id``: the higher leg id wins (``leg.id DESC``,
    Postgres uuids compare bytewise, matching Python's ``UUID`` ordering)."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-tie", name="Gallery tie")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn, workspace_id=workspace_id, document_id="doc_gallery_tied"
            )
            born = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
            legs: dict[str, str] = {}
            for thread_id in ("thr_gallery_tie_a", "thr_gallery_tie_b"):
                await _seed_thread(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                )
                legs[thread_id] = await _seed_leg(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    document_id="doc_gallery_tied",
                    created_at=born,
                )

            expected_thread = max(legs, key=lambda thread_id: UUID(legs[thread_id]))
            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            assert [item["id"] for item in feed] == ["doc_gallery_tied"]
            assert feed[0]["origin_thread_id"] == expected_thread

    run_async(scenario())


def test_a_forty_document_project_serves_its_whole_feed_in_order(
    require_chat_db: None,
) -> None:
    """The read has no LIMIT — a many-document project must serve every card, still
    newest-updated first (pins no-silent-truncation while pagination is future work)."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-volume", name="Gallery volume")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            newest = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
            for index in range(40):
                await _seed_design_document(
                    conn,
                    workspace_id=workspace_id,
                    document_id=f"doc_gallery_bulk_{index:02d}",
                    updated_at=newest - timedelta(minutes=index),
                )
                await _seed_thread(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=f"thr_gallery_bulk_{index:02d}",
                )
                await _seed_leg(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=f"thr_gallery_bulk_{index:02d}",
                    document_id=f"doc_gallery_bulk_{index:02d}",
                )

            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            assert [item["id"] for item in feed] == [
                f"doc_gallery_bulk_{index:02d}" for index in range(40)
            ]

    run_async(scenario())


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


def test_a_leg_with_two_documents_lists_both_with_its_thread_as_origin(
    require_chat_db: None,
) -> None:
    """Spec §3.2/§3.8: the feed derives from the leg's document SET.

    One leg, two artboards: the pinned ``design_leg.document_id`` column names only
    position 0, so a derivation reading the column would show one card and lose the
    other. Both belong to the leg's project, and both report the leg's thread as origin.
    """

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-batch", name="Gallery batch")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            touched = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
            for document_id, title, age_hours in (
                ("doc_batch_first", "First artboard", 0),
                ("doc_batch_second", "Second artboard", 1),
            ):
                await _seed_design_document(
                    conn,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    doc_kind="scene",
                    title=title,
                    updated_at=touched - timedelta(hours=age_hours),
                )
            await _seed_thread(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id="thr_gallery_batch",
            )
            await _seed_leg(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id="thr_gallery_batch",
                document_id="doc_batch_first",
                documents=("doc_batch_first", "doc_batch_second"),
            )

            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            assert [item["id"] for item in feed] == ["doc_batch_first", "doc_batch_second"]
            assert {item["origin_thread_id"] for item in feed} == {"thr_gallery_batch"}
            assert [item["title"] for item in feed] == ["First artboard", "Second artboard"]

    run_async(scenario())


def test_a_document_born_with_an_account_carries_it_on_the_card_wire(
    require_chat_db: None,
) -> None:
    """Spec §3.8: the gallery feed carries the document's account, in the artifacts
    page's own shape. A document with no account says ``None`` — never an invented one."""

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-gallery-account", name="Gallery account")
            workspace_id = project.workspace_id
            await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
            await conn.execute(
                text(
                    "INSERT INTO design_account (account_id, workspace_id, name, domain)"
                    " VALUES ('acc_gallery_acme', :ws, 'Acme Health', 'acme.example')"
                ),
                {"ws": workspace_id},
            )
            touched = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
            for document_id, age_hours in (("doc_acct_stamped", 0), ("doc_acct_plain", 1)):
                await _seed_design_document(
                    conn,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    updated_at=touched - timedelta(hours=age_hours),
                )
                await _seed_thread(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=f"thr_{document_id}",
                )
                await _seed_leg(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id=f"thr_{document_id}",
                    document_id=document_id,
                )
            await conn.execute(
                text(
                    "UPDATE design_document SET account_id = 'acc_gallery_acme'"
                    " WHERE id = 'doc_acct_stamped'"
                )
            )

            feed = await _feed(conn, workspace_id=workspace_id, project_id=project.project_id)
            by_id = {item["id"]: item for item in feed}
            stamped = by_id["doc_acct_stamped"]["account"]
            assert {key: stamped[key] for key in ("id", "name", "domain", "account_entity_id")} == {
                "id": "acc_gallery_acme",
                "name": "Acme Health",
                "domain": "acme.example",
                "account_entity_id": None,
            }
            # Brandfetch's mark rides along when the deployment has a client id (the lane's
            # `.env` does); without one the key is honestly null. Either is correct here.
            logo = stamped["logo_path"]
            assert logo is None or logo.startswith("https://cdn.brandfetch.io/domain/acme.example/")
            assert by_id["doc_acct_plain"]["account"] is None

    run_async(scenario())


def test_the_feed_account_carries_brandfetchs_logo_when_a_client_id_is_configured() -> None:
    """Founder 2026-09-20: the gallery card's account mark is Brandfetch's Logo API URL — the
    accounts screens' own rule — built from the account's domain and the configured client id.
    No client id, or no domain, means no logo path; the card then shows nothing. No DB."""
    from types import SimpleNamespace

    from clue_api.chat.router import _design_artifact_list_item

    document = {
        "id": "doc_1",
        "title": "Apollo ad",
        "status": "draft",
        "doc_kind": "scene",
        "current_version": 0,
        "created_at": datetime(2026, 9, 20, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 20, tzinfo=UTC),
        "origin_thread_id": "thr_1",
        "artifact_type": None,
        "pages_json": None,
        "account_id": "acc_1",
        "account_name": "Apollo Clinics",
        "account_domain": "apollo.example",
        "account_entity_id": None,
    }
    settings = SimpleNamespace(brandfetch_client_id="cid-1")
    wire = _design_artifact_list_item("prj_1", document, settings=settings)  # type: ignore[arg-type]
    assert wire.account is not None
    assert wire.account.logo_path == (
        "https://cdn.brandfetch.io/domain/apollo.example/w/128/h/128/fallback/lettermark/type/icon"
        "?c=cid-1"
    )
    unconfigured = _design_artifact_list_item(
        "prj_1",
        document,
        settings=SimpleNamespace(brandfetch_client_id=""),  # type: ignore[arg-type]
    )
    assert unconfigured.account is not None and unconfigured.account.logo_path is None
    assert _design_artifact_list_item("prj_1", document).account.logo_path is None  # type: ignore[union-attr]
