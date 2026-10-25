"""Connecting the workspace's CRM from the chat's connect card (CRM integration Task 5, R-3.10).

DB-backed and rollback-only. The asking turns are real submissions through the real turn route;
Composio is a fake injected through ``app.state.crm_gateway``. Proves: only owners/admins connect,
each click records its attempt, the callback activates only the recorded attempt, and activation
wakes every waiting chat once with a ``crm_connected`` derived turn.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Request
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.agent_turn_submission import DERIVATION_CRM_CONNECTED
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.crm.composio_gateway import (
    ComposioError,
    ConnectedAccount,
    ConnectLink,
    ExecuteResult,
)
from clue_api.crm.connections import open_connect_request, open_settings_connect_request
from clue_api.execution_wiring import build_tool_invoker
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.app import frontend_read_workspace_resolver
from clue_api.projections_app import create_projections_app
from clue_auth.policy import permissions_for_role
from clue_config import Settings, load_settings
from clue_spine import Project
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_crm_connect"
MEMBERSHIP_ID = "wsm_crm_connect"
CRM = f"{FRONTEND_READ_PREFIX}/crm"
ORIGIN = "http://app.test"
_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_db")


class FakeComposio:
    def __init__(self) -> None:
        self.links: list[dict[str, Any]] = []
        self.accounts: dict[str, ConnectedAccount] = {}
        #: The CRM account each grant belongs to, as "who am I" answers it; absent → the call fails.
        self.identities: dict[str, str] = {}
        #: The Salesforce org name each grant's Organization query answers; absent → it fails.
        self.org_names: dict[str, str] = {}
        self.soql: list[str] = []
        #: Each connected account deleted (a disconnect, R-15.3); ``delete_fails`` makes it fail.
        self.deleted: list[str] = []
        self.delete_fails = False

    async def create_link(self, **kwargs: Any) -> ConnectLink:
        self.links.append(kwargs)
        account = f"ca_{len(self.links)}"
        return ConnectLink(
            redirect_url=f"https://connect.test/link/lk_{len(self.links)}",
            connected_account_id=account,
            expires_at=_AT + timedelta(minutes=10),
        )

    async def get_account(self, connected_account_id: str) -> ConnectedAccount:
        return self.accounts[connected_account_id]

    async def search_tools(self, **_: Any) -> list[Any]:
        return []

    async def delete_account(self, connected_account_id: str) -> None:
        self.deleted.append(connected_account_id)
        if self.delete_fails:
            raise ComposioError("unavailable", None, "Composio is down")

    async def execute(
        self, *, slug: str, connected_account_id: str, arguments: Any = None, **_: Any
    ) -> Any:
        if slug == "SALESFORCE_RUN_SOQL_QUERY":
            self.soql.append(arguments["query"])
            name = self.org_names.get(connected_account_id)
            if name is None:
                return ExecuteResult(successful=False, data=None, error="INSUFFICIENT_ACCESS")
            return ExecuteResult(
                successful=True,
                data={"data": {"totalSize": 1, "records": [{"Name": name}]}},
                error=None,
            )
        if slug not in ("HUBSPOT_WHO_AM_I", "SALESFORCE_WHO_AM_I"):
            raise AssertionError("not used here")
        identity = self.identities.get(connected_account_id)
        if identity is None:
            return ExecuteResult(successful=False, data=None, error="who am I failed")
        key = "portal_id" if slug == "HUBSPOT_WHO_AM_I" else "organization_id"
        return ExecuteResult(successful=True, data={"data": {key: identity}}, error=None)


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

    async def list_blobs(self) -> Any:
        return
        yield


def _settings() -> Settings:
    return load_settings(
        _env_file=None,
        chat_enabled=True,
        frontend_read_enabled=True,
        arv2_display_generate_on_read=False,
        composio_hubspot_auth_config_id="ac_hubspot",
        composio_salesforce_auth_config_id="ac_salesforce",
        app_origin=ORIGIN,
    )


def _chat_principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=_AT,
    )


def _app(conn: Any, tmp_path: Any, composio: FakeComposio, *, role: str) -> Any:
    from clue_api.thread_wiring import register_thread_tools

    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
    settings = _settings()
    app = create_projections_app(
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
        ingestion_storage=FsStorage(tmp_path / "blobs"),
        chat_principal_resolver=_chat_principal,
    )
    app.state.crm_gateway = composio

    async def _resolver(request: Request) -> str:
        workspace_id = request.headers["X-Workspace-Id"]
        request.state.clue_principal = RequestPrincipal(
            user_id=USER_ID,
            membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
            workspace_id=workspace_id,
            role_key=role,  # type: ignore[arg-type]
            permissions=permissions_for_role(role),
            authenticated_at=_AT,
        )
        return workspace_id

    app.dependency_overrides[frontend_read_workspace_resolver] = _resolver
    return app


async def _seed(conn: Any, workspace_id: str) -> Project:
    project = await seed_project(conn, workspace_id, name="CRM connect")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
    )
    return project


async def _waiting_chat(conn: Any, client: httpx.AsyncClient, project: Project, name: str) -> Any:
    """A thread whose asking turn showed a connect card."""
    thread_id = f"thr_{name}_{project.workspace_id}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :ws, :project, :user)"
        ),
        {
            "id": thread_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "user": USER_ID,
        },
    )
    response = await client.post(
        f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
        json={"message": "What do our deals look like?"},
        headers={"X-Workspace-Id": project.workspace_id, "Idempotency-Key": f"ask-{name}"},
    )
    assert response.status_code == 202, response.text
    turn_id = UUID(response.json()["data"]["turn_id"])
    return await open_connect_request(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        requested_by_user_id=USER_ID,
        mode="connect",
    )


async def _wake_turns(conn: Any, workspace_id: str) -> list[Any]:
    return (
        await conn.execute(
            text(
                "SELECT thread_id, submitted_by_user_id, derived_from_turn_id "
                "FROM agent_turn_submission WHERE workspace_id = :ws AND derivation = :d"
            ),
            {"ws": workspace_id, "d": DERIVATION_CRM_CONNECTED},
        )
    ).all()


def _run(tmp_path: Any, role: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"ws_crm_{uuid4().hex[:8]}"
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:ws, 'CRM')"),
                {"ws": workspace_id},
            )
            project = await _seed(conn, workspace_id)
            composio = FakeComposio()
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn, tmp_path, composio, role=role)),
                base_url="http://t",
            ) as client:
                await body(conn, client, project, composio)

    run_async(scenario())


def _headers(project: Project) -> dict[str, str]:
    return {"X-Workspace-Id": project.workspace_id}


def test_connecting_needs_manage_settings(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        card = await _waiting_chat(conn, client, project, "a")
        denied = await client.post(
            f"{CRM}/connect-link",
            json={"request_id": str(card.request_id), "provider": "hubspot"},
            headers=_headers(project),
        )
        assert denied.status_code == 403

    _run(tmp_path, "operator", body)


def test_a_click_records_its_attempt_and_the_callback_page(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        card = await _waiting_chat(conn, client, project, "a")
        response = await client.post(
            f"{CRM}/connect-link",
            json={"request_id": str(card.request_id), "provider": "hubspot"},
            headers=_headers(project),
        )
        assert response.status_code == 200, response.text
        assert response.json()["redirectUrl"] == "https://connect.test/link/lk_1"
        sent = composio.links[0]
        assert sent["auth_config_id"] == "ac_hubspot"
        assert sent["user_id"] == f"ws_{project.workspace_id}"
        assert sent["callback_url"] == (
            f"{ORIGIN}/integrations/crm/callback?request={card.request_id}"
        )
        pending = (
            await conn.execute(
                text(
                    "SELECT pending_connected_account_id, pending_provider FROM "
                    "crm_connect_request WHERE request_id = :id"
                ),
                {"id": card.request_id},
            )
        ).one()
        assert tuple(pending) == ("ca_1", "hubspot")

    _run(tmp_path, "owner", body)


def test_completion_activates_and_wakes_every_waiting_chat_once(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        mine = await _waiting_chat(conn, client, project, "a")
        theirs = await _waiting_chat(conn, client, project, "b")
        await client.post(
            f"{CRM}/connect-link",
            json={"request_id": str(mine.request_id), "provider": "hubspot"},
            headers=_headers(project),
        )
        composio.accounts["ca_1"] = ConnectedAccount(id="ca_1", status="ACTIVE", toolkit="hubspot")
        complete = {
            "request_id": str(mine.request_id),
            "status": "success",
            "connected_account_id": "ca_1",
        }
        first = await client.post(f"{CRM}/complete", json=complete, headers=_headers(project))
        assert first.json() == {"outcome": "connected", "provider": "hubspot"}
        woken = await _wake_turns(conn, project.workspace_id)
        assert {row.thread_id for row in woken} == {mine.thread_id, theirs.thread_id}
        assert {row.derived_from_turn_id for row in woken} == {mine.turn_id, theirs.turn_id}
        assert {row.submitted_by_user_id for row in woken} == {USER_ID}
        replay = await client.post(f"{CRM}/complete", json=complete, headers=_headers(project))
        assert replay.json() == {"outcome": "stale"}
        assert len(await _wake_turns(conn, project.workspace_id)) == 2
        status = await client.get(f"{CRM}/connection", headers=_headers(project))
        assert status.json()["provider"] == "hubspot" and status.json()["status"] == "active"
        # The connect card's footer names who connected it.
        named = await conn.scalar(
            text("SELECT display_name FROM platform_user WHERE user_id = :id"), {"id": USER_ID}
        )
        assert status.json()["connectedByName"] == named

    _run(tmp_path, "owner", body)


def test_a_failed_login_activates_nothing(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        card = await _waiting_chat(conn, client, project, "a")
        await client.post(
            f"{CRM}/connect-link",
            json={"request_id": str(card.request_id), "provider": "salesforce"},
            headers=_headers(project),
        )
        composio.accounts["ca_1"] = ConnectedAccount(
            id="ca_1", status="INITIATED", toolkit="salesforce"
        )
        for status in ("failed", "success"):
            response = await client.post(
                f"{CRM}/complete",
                json={
                    "request_id": str(card.request_id),
                    "status": status,
                    "connected_account_id": "ca_1",
                },
                headers=_headers(project),
            )
            assert response.json() == {"outcome": "failed"}
        assert await _wake_turns(conn, project.workspace_id) == []
        status = await client.get(f"{CRM}/connection", headers=_headers(project))
        assert status.json() == {"status": "none"}

    _run(tmp_path, "owner", body)


def test_a_callback_for_another_attempt_is_stale(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        card = await _waiting_chat(conn, client, project, "a")
        for _ in range(2):  # the newest click wins
            await client.post(
                f"{CRM}/connect-link",
                json={"request_id": str(card.request_id), "provider": "hubspot"},
                headers=_headers(project),
            )
        composio.accounts["ca_1"] = ConnectedAccount(id="ca_1", status="ACTIVE", toolkit="hubspot")
        response = await client.post(
            f"{CRM}/complete",
            json={
                "request_id": str(card.request_id),
                "status": "success",
                "connected_account_id": "ca_1",
            },
            headers=_headers(project),
        )
        assert response.json() == {"outcome": "stale"}
        assert await _wake_turns(conn, project.workspace_id) == []

    _run(tmp_path, "owner", body)


def test_any_member_can_read_the_connection_status(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        del conn
        response = await client.get(f"{CRM}/connection", headers=_headers(project))
        assert response.status_code == 200
        assert response.json() == {"status": "none"}

    _run(tmp_path, "viewer", body)


def test_a_reconnect_to_the_same_crm_account_keeps_its_connection(tmp_path: Any) -> None:
    """D-2 (2026-10-25): completing a connection asks the CRM which account it is; the same
    HubSpot portal as the expired connection reuses that connection, another portal does not."""

    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        async def connect(chat: str, account: str) -> str:
            waiting = await _waiting_chat(conn, client, project, chat)
            await client.post(
                f"{CRM}/connect-link",
                json={"request_id": str(waiting.request_id), "provider": "hubspot"},
                headers=_headers(project),
            )
            composio.accounts[account] = ConnectedAccount(
                id=account, status="ACTIVE", toolkit="hubspot"
            )
            done = await client.post(
                f"{CRM}/complete",
                json={
                    "request_id": str(waiting.request_id),
                    "status": "success",
                    "connected_account_id": account,
                },
                headers=_headers(project),
            )
            assert done.json() == {"outcome": "connected", "provider": "hubspot"}
            return str(
                await conn.scalar(
                    text(
                        "SELECT connection_id FROM workspace_integration_connection "
                        "WHERE composio_connected_account_id = :a"
                    ),
                    {"a": account},
                )
            )

        composio.identities.update({"ca_1": "111", "ca_2": "111", "ca_3": "222"})
        first = await connect("a", "ca_1")
        await conn.execute(
            text(
                "UPDATE workspace_integration_connection SET status = 'expired' "
                "WHERE connection_id = :id"
            ),
            {"id": first},
        )
        assert await connect("b", "ca_2") == first  # same portal: the same connection again
        other = await connect("c", "ca_3")
        assert other != first  # another portal: a new connection
        unknown = await connect("d", "ca_4")  # "who am I" failed: a new connection, as before
        assert unknown not in (first, other)
        rows = await conn.execute(
            text(
                "SELECT composio_connected_account_id, status, external_account_id "
                "FROM workspace_integration_connection WHERE workspace_id = :ws "
                "ORDER BY connected_at"
            ),
            {"ws": project.workspace_id},
        )
        assert [tuple(r) for r in rows] == [
            ("ca_2", "disconnected", "111"),
            ("ca_3", "disconnected", "222"),
            ("ca_4", "active", None),
        ]
        # HubSpot's portal name needs a scope Clue does not ask for (R-15.3): never stored.
        names = await conn.execute(
            text(
                "SELECT external_account_name FROM workspace_integration_connection "
                "WHERE workspace_id = :ws"
            ),
            {"ws": project.workspace_id},
        )
        assert {r[0] for r in names} == {None}
        assert composio.soql == []

    _run(tmp_path, "owner", body)


def test_a_settings_connect_request_has_no_chat(tmp_path: Any) -> None:
    """R-15.3: connecting from Settings needs no chat. Its request carries no project, thread or
    turn; activation fulfils it, and only the chat that waited on a connect card is woken."""

    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        chat = await _waiting_chat(conn, client, project, "a")
        settings = await open_settings_connect_request(
            conn,
            workspace_id=project.workspace_id,
            requested_by_user_id=USER_ID,
            mode="connect",
        )
        assert (settings.project_id, settings.thread_id, settings.turn_id) == (None, None, None)
        link = await client.post(
            f"{CRM}/connect-link",
            json={"request_id": str(settings.request_id), "provider": "hubspot"},
            headers=_headers(project),
        )
        assert link.status_code == 200, link.text
        composio.accounts["ca_1"] = ConnectedAccount(id="ca_1", status="ACTIVE", toolkit="hubspot")
        complete = {
            "request_id": str(settings.request_id),
            "status": "success",
            "connected_account_id": "ca_1",
        }
        done = await client.post(f"{CRM}/complete", json=complete, headers=_headers(project))
        assert done.json() == {"outcome": "connected", "provider": "hubspot"}
        statuses = await conn.execute(
            text("SELECT request_id, status FROM crm_connect_request WHERE workspace_id = :ws"),
            {"ws": project.workspace_id},
        )
        assert {r.request_id: r.status for r in statuses} == {
            chat.request_id: "fulfilled",
            settings.request_id: "fulfilled",
        }
        woken = await _wake_turns(conn, project.workspace_id)
        assert [(r.thread_id, r.derived_from_turn_id) for r in woken] == [
            (chat.thread_id, chat.turn_id)
        ]
        replay = await client.post(f"{CRM}/complete", json=complete, headers=_headers(project))
        assert replay.json() == {"outcome": "stale"}
        assert len(await _wake_turns(conn, project.workspace_id)) == 1

    _run(tmp_path, "owner", body)


def test_salesforce_connection_keeps_the_org_name(tmp_path: Any) -> None:
    """R-15.3: Salesforce shows the org's name. It is read at completion from the Organization
    object; a failed name query still identifies the org, so the reconnect keeps its connection
    and the name already known."""

    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        async def connect(chat: str, account: str) -> Any:
            waiting = await _waiting_chat(conn, client, project, chat)
            await client.post(
                f"{CRM}/connect-link",
                json={"request_id": str(waiting.request_id), "provider": "salesforce"},
                headers=_headers(project),
            )
            composio.accounts[account] = ConnectedAccount(
                id=account, status="ACTIVE", toolkit="salesforce"
            )
            done = await client.post(
                f"{CRM}/complete",
                json={
                    "request_id": str(waiting.request_id),
                    "status": "success",
                    "connected_account_id": account,
                },
                headers=_headers(project),
            )
            assert done.json() == {"outcome": "connected", "provider": "salesforce"}
            return (
                await conn.execute(
                    text(
                        "SELECT connection_id, external_account_id, external_account_name "
                        "FROM workspace_integration_connection WHERE workspace_id = :ws "
                        "AND status = 'active'"
                    ),
                    {"ws": project.workspace_id},
                )
            ).one()

        composio.identities.update({"ca_1": "00DORG", "ca_2": "00DORG"})
        composio.org_names["ca_1"] = "Acme Robotics"
        first = await connect("a", "ca_1")
        assert (first.external_account_id, first.external_account_name) == (
            "00DORG",
            "Acme Robotics",
        )
        assert composio.soql == ["SELECT Name FROM Organization LIMIT 1"]
        again = await connect("b", "ca_2")  # the name query fails this time
        assert tuple(again) == (first.connection_id, "00DORG", "Acme Robotics")

    _run(tmp_path, "owner", body)
