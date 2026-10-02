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
from fastapi import Request
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.app import frontend_read_workspace_resolver
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_obs.otel.metrics import InMemorySink, set_metric_sink
from tests._identity import fixture_membership_id, seed_principal
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


async def _get(
    conn: Any, *, workspace_id: str, query: str = "", enabled: bool = True
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(conn, enabled=enabled)), base_url="http://t"
    ) as client:
        return await client.get(f"{_BASE}{query}", headers={"X-Workspace-Id": workspace_id})


async def _document_in_project(
    conn: Any,
    *,
    workspace_id: str,
    project_id: str,
    document_id: str,
    title: str,
    updated_at: datetime,
    doc_kind: str = "web",
) -> None:
    await _seed_design_document(
        conn,
        workspace_id=workspace_id,
        document_id=document_id,
        title=title,
        updated_at=updated_at,
        doc_kind=doc_kind,
    )
    thread_id = await _seed_thread(
        conn, workspace_id=workspace_id, project_id=project_id, thread_id=f"thr_{document_id}"
    )
    await _seed_leg(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        document_id=document_id,
    )


def test_lists_every_project_document_with_its_project_and_excludes_legless_and_foreign_rows() -> (
    None
):
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            first = await _seed_project_row(conn, "ws-artifacts-lib", name="Project one")
            ws = first.workspace_id
            second = await _seed_project_row(conn, ws, name="Project two")
            other = await _seed_project_row(conn, "ws-artifacts-other", name="Elsewhere")
            await seed_principal(conn, workspace_id=ws, user_id=USER_ID)
            await seed_principal(conn, workspace_id=other.workspace_id, user_id=USER_ID)
            await _document_in_project(
                conn,
                workspace_id=ws,
                project_id=first.project_id,
                document_id="doc_a",
                title="A",
                updated_at=_T0,
            )
            await _document_in_project(
                conn,
                workspace_id=ws,
                project_id=second.project_id,
                document_id="doc_b",
                title="B",
                updated_at=_T0 + timedelta(hours=1),
                doc_kind="scene",
            )
            await _seed_design_document(
                conn, workspace_id=ws, document_id="doc_legless", title="Legless"
            )
            await _document_in_project(
                conn,
                workspace_id=other.workspace_id,
                project_id=other.project_id,
                document_id="doc_foreign",
                title="Foreign",
                updated_at=_T0,
            )

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
                await _document_in_project(
                    conn,
                    workspace_id=ws,
                    project_id=project.project_id,
                    document_id=f"doc_{index}",
                    title=f"D{index}",
                    updated_at=_T0 + timedelta(minutes=index),
                )
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
            await _document_in_project(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                document_id="doc_page",
                title="Acme page",
                updated_at=_T0,
            )
            await conn.execute(
                text(
                    "UPDATE design_document SET account_id = 'acc_acme', archived_at = :at"
                    " WHERE id = 'doc_page'"
                ),
                {"at": _T0 + timedelta(days=1)},
            )
            rows = (await _get(conn, workspace_id=ws)).json()["data"]["artifacts"]
            assert rows[0]["account"] == {
                "id": "acc_acme",
                "name": "Acme Health",
                "domain": "acme.example",
                "account_entity_id": None,
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


def _principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=USER_ID),
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
    )


def _app_with_principal(conn: Any, workspace_id: str) -> Any:
    """The read surface under a real principal, the way production reaches it: ``projections_app``
    overrides ``frontend_read_workspace_resolver`` with the authenticated workspace dependency,
    whose ``PrincipalDependency`` stores the principal on ``request.state.clue_principal``. The test
    installs the same override with a resolver that stores the fixture principal.

    ``Request`` and the resolver are imported at module scope deliberately: this module uses
    postponed annotations, and FastAPI resolves an override's signature against its module
    globals — a function-local ``Request`` import leaves the annotation unresolvable, and the
    override's own ``request`` parameter is then read as a missing query parameter."""

    app = _app(conn)

    async def _resolver(request: Request) -> str:
        request.state.clue_principal = _principal(workspace_id)
        return workspace_id

    app.dependency_overrides[frontend_read_workspace_resolver] = _resolver
    return app


def test_saved_and_viewed_marks_are_the_callers_own_and_converge() -> None:
    async def scenario() -> None:
        sink = InMemorySink()
        set_metric_sink(sink)
        try:
            async with rollback_conn(seed_pack=False) as conn:
                project = await _seed_project_row(conn, "ws-artifacts-marks", name="Marks")
                ws = project.workspace_id
                await seed_principal(conn, workspace_id=ws, user_id=USER_ID)
                await _document_in_project(
                    conn,
                    workspace_id=ws,
                    project_id=project.project_id,
                    document_id="doc_m",
                    title="Marked",
                    updated_at=_T0,
                )
                app = _app_with_principal(conn, ws)
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://t"
                ) as client:
                    headers = {"X-Workspace-Id": ws}
                    saved = await client.put(
                        f"{_BASE}/doc_m/saved", json={"saved": True}, headers=headers
                    )
                    assert saved.status_code == 200, saved.text
                    assert saved.json()["data"] == {"saved": True}
                    again = await client.put(
                        f"{_BASE}/doc_m/saved", json={"saved": True}, headers=headers
                    )
                    assert again.json()["data"] == {"saved": True}
                    viewed = await client.post(f"{_BASE}/doc_m/viewed", headers=headers)
                    assert viewed.status_code == 200, viewed.text
                    assert viewed.json()["data"]["last_viewed_at"]
                    listed = await client.get(_BASE, headers=headers)
                    row = listed.json()["data"]["artifacts"][0]
                    assert row["saved"] is True and row["last_viewed_at"] is not None
                    foreign = await client.put(
                        f"{_BASE}/doc_missing/saved", json={"saved": True}, headers=headers
                    )
                    assert foreign.status_code == 404
                    assert foreign.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
                count = (
                    await conn.execute(text("SELECT count(*) FROM design_document_user_mark"))
                ).scalar_one()
                assert count == 1
                assert sink.counter("artifacts.mark.written", kind="saved", value="true") == 2
                assert sink.counter("artifacts.mark.written", kind="viewed", value="true") == 1
        finally:
            set_metric_sink(InMemorySink())

    run_async(scenario())


def test_mark_writes_need_an_authenticated_principal() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-artifacts-anon", name="Anon")
            ws = project.workspace_id
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn)), base_url="http://t"
            ) as client:
                response = await client.put(
                    f"{_BASE}/doc_x/saved",
                    json={"saved": True},
                    headers={"X-Workspace-Id": ws},
                )
            assert response.status_code == 401

    run_async(scenario())
