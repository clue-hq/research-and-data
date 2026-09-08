"""Slice 9A — the bounded, idempotent accounts-table action."""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import bind_workspace_client
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import AccountStatus, EntityId
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from tests._workspace import seed_project, seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "fi2-bulk-actions"
_OTHER_WS = "fi2-bulk-actions-other"
_BASE = f"{FRONTEND_READ_PREFIX}/accounts"


def _app(conn: AsyncConnection):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


async def _account(conn: AsyncConnection, *, name: str, workspace_id: str = _WS) -> uuid.UUID:
    return uuid.UUID(
        str(
            await insert_account_entity(
                conn,
                canonical_name=name,
                primary_domain=f"{name.lower()}.test",
                status=AccountStatus.ACTIVE,
                workspace_id=workspace_id,
            )
        )
    )


def test_account_batch_is_page_bounded_idempotent_and_audited() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, _WS, name="Active ABM")
            first = await _account(conn, name="First")
            second = await _account(conn, name="Second")
            workspace_client = await _account(conn, name="Insight Health")
            await bind_workspace_client(
                conn,
                workspace_id=_WS,
                client_entity_id=EntityId(workspace_client),
            )
            await ensure_project_account(
                conn,
                workspace_id=_WS,
                project_id=project.project_id,
                account_entity_id=first,
                added_via="imported",
            )
            await seed_workspace(conn, _OTHER_WS)
            foreign = await _account(conn, name="Foreign", workspace_id=_OTHER_WS)

            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn)), base_url="http://t"
            ) as client:
                capabilities = await client.get(
                    f"{_BASE}/bulk-capabilities", headers={"X-Workspace-Id": _WS}
                )
                assert capabilities.status_code == 200
                assert capabilities.json() == {
                    "addToProject": {"allowed": True, "maxItems": 100},
                    "addToChat": {"allowed": False, "maxItems": 100},
                    "projects": [
                        {"id": project.project_id, "name": "Active ABM", "status": "draft"}
                    ],
                }

                body = {
                    "accountIds": [
                        str(first),
                        str(second),
                        str(foreign),
                        str(workspace_client),
                    ],
                    "projectId": project.project_id,
                }
                headers = {"X-Workspace-Id": _WS, "Idempotency-Key": "page-1-add"}
                first_response = await client.post(
                    f"{_BASE}/bulk-actions/add-to-project", headers=headers, json=body
                )
                replay = await client.post(
                    f"{_BASE}/bulk-actions/add-to-project", headers=headers, json=body
                )

            assert first_response.status_code == 200
            payload = first_response.json()
            assert replay.json() == payload
            assert payload["state"] == "partial"
            assert payload["counts"] == {
                "requested": 4,
                "completed": 1,
                "unchanged": 1,
                "ineligible": 2,
                "failed": 0,
            }
            outcomes = {item["subjectId"]: item["outcome"] for item in payload["items"]}
            assert outcomes == {
                str(first): "unchanged",
                str(second): "completed",
                str(foreign): "ineligible",
                str(workspace_client): "ineligible",
            }
            memberships = (
                await conn.execute(
                    text(
                        "SELECT account_entity_id, added_via FROM project_account "
                        "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                        "ORDER BY account_entity_id"
                    ),
                    {"workspace_id": _WS, "project_id": project.project_id},
                )
            ).all()
            assert {uuid.UUID(str(row[0])): str(row[1]) for row in memberships} == {
                first: "imported",
                second: "manual",
            }
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM frontend_bulk_action_operation "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": _WS},
                )
            ).scalar_one() == 1
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM frontend_bulk_action_item "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": _WS},
                )
            ).scalar_one() == 4

    run_async(scenario())


def test_idempotency_key_cannot_name_a_different_account_request() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, _WS, name="Active ABM")
            first = await _account(conn, name="First")
            second = await _account(conn, name="Second")
            headers = {"X-Workspace-Id": _WS, "Idempotency-Key": "same-key"}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn)), base_url="http://t"
            ) as client:
                assert (
                    await client.post(
                        f"{_BASE}/bulk-actions/add-to-project",
                        headers=headers,
                        json={"accountIds": [str(first)], "projectId": project.project_id},
                    )
                ).status_code == 200
                conflict = await client.post(
                    f"{_BASE}/bulk-actions/add-to-project",
                    headers=headers,
                    json={"accountIds": [str(second)], "projectId": project.project_id},
                )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    run_async(scenario())


def test_the_account_batch_limit_is_enforced() -> None:
    """A page-bounded action refuses a page bigger than the table can show.

    (The contact half of this suite went with the contact bulk email-lookup route on 2026-09-09:
    the frontend never bound to it, and the single-contact lookup is the kept surface.)
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, _WS, name="Active ABM")
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn)), base_url="http://t"
            ) as client:
                account_limit = await client.post(
                    f"{_BASE}/bulk-actions/add-to-project",
                    headers={"X-Workspace-Id": _WS, "Idempotency-Key": "over-100"},
                    json={
                        "accountIds": [str(uuid.uuid4()) for _ in range(101)],
                        "projectId": project.project_id,
                    },
                )

            assert account_limit.status_code == 422

    run_async(scenario())
