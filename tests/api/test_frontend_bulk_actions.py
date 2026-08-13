"""FI-2 Slice 9A — bounded, idempotent Account/Contact table actions."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.contact_email_lookup import ContactEmailLookupService
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import AccountStatus
from clue_research.adapters.exa_websets import EXA_WEBSETS_SOURCE_KEY
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from tests._workspace import seed_project, seed_workspace
from tests.api.test_frontend_contact_email_lookup_db import _ImmediateProvider, _MemoryStorage
from tests.api.test_frontend_read_contacts import _WS as _CONTACT_WS
from tests.api.test_frontend_read_contacts import _build as _build_contacts
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "fi2-bulk-actions"
_OTHER_WS = "fi2-bulk-actions-other"
_BASE = f"{FRONTEND_READ_PREFIX}/accounts"


def _app(conn: AsyncConnection, *, contact_email_lookup=None):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
        contact_email_lookup=contact_email_lookup,
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
                    "accountIds": [str(first), str(second), str(foreign)],
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
                "requested": 3,
                "completed": 1,
                "unchanged": 1,
                "ineligible": 1,
                "failed": 0,
            }
            outcomes = {item["subjectId"]: item["outcome"] for item in payload["items"]}
            assert outcomes == {
                str(first): "unchanged",
                str(second): "completed",
                str(foreign): "ineligible",
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
            ).scalar_one() == 3

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


def test_batch_limits_and_unconfigured_contact_capability_are_honest() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, _WS, name="Active ABM")
            account = await _account(conn, name="First")
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
                contact_capability = await client.get(
                    f"{_BASE}/{account}/contacts/bulk-capabilities",
                    headers={"X-Workspace-Id": _WS},
                )
                contact_limit = await client.post(
                    f"{_BASE}/{account}/contacts/bulk-actions/email-lookup",
                    headers={"X-Workspace-Id": _WS, "Idempotency-Key": "over-20"},
                    json={"contactIds": [str(uuid.uuid4()) for _ in range(21)]},
                )

            assert account_limit.status_code == 422
            assert contact_capability.status_code == 200
            assert contact_capability.json() == {
                "lookupWorkEmails": {"allowed": False, "maxItems": 20},
                "addToChat": {"allowed": False, "maxItems": 100},
            }
            assert contact_limit.status_code == 422

    run_async(scenario())


def test_contact_batch_reuses_the_governed_email_service_and_replays_without_spend() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_contacts(conn)
            exa = _ImmediateProvider(EXA_WEBSETS_SOURCE_KEY, "committee@example.test")
            sumble = _ImmediateProvider(PEOPLE_SOURCE_KEY, "committee@example.test")
            lock = asyncio.Lock()

            @asynccontextmanager
            async def service_connection():
                async with lock:
                    yield conn

            service = ContactEmailLookupService(
                providers=(exa, sumble),
                storage=_MemoryStorage(),
                conn_factory=service_connection,
            )
            headers = {
                "X-Workspace-Id": _CONTACT_WS,
                "Idempotency-Key": "contacts-page-1-email",
            }
            body = {"contactIds": [str(fixture.shared), str(fixture.solo)]}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn, contact_email_lookup=service)),
                base_url="http://t",
            ) as client:
                capability = await client.get(
                    f"{_BASE}/{fixture.acme}/contacts/bulk-capabilities",
                    headers={"X-Workspace-Id": _CONTACT_WS},
                )
                first = await client.post(
                    f"{_BASE}/{fixture.acme}/contacts/bulk-actions/email-lookup",
                    headers=headers,
                    json=body,
                )
                replay = await client.post(
                    f"{_BASE}/{fixture.acme}/contacts/bulk-actions/email-lookup",
                    headers=headers,
                    json=body,
                )

            assert capability.json() == {
                "lookupWorkEmails": {"allowed": True, "maxItems": 20},
                "addToChat": {"allowed": False, "maxItems": 100},
            }
            assert first.status_code == 200
            assert replay.json() == first.json()
            assert first.json()["counts"] == {
                "requested": 2,
                "completed": 2,
                "unchanged": 0,
                "ineligible": 0,
                "failed": 0,
            }
            assert all(
                item["emailLookup"]["emails"][0]["value"] == "committee@example.test"
                for item in first.json()["items"]
            )
            # Two Contacts × one kickoff per provider. Replaying the batch dispatches nothing.
            assert exa.calls == sumble.calls == 2
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM frontend_bulk_action_item "
                        "WHERE workspace_id=:workspace_id AND outcome='completed'"
                    ),
                    {"workspace_id": _CONTACT_WS},
                )
            ).scalar_one() == 2

    run_async(scenario())
