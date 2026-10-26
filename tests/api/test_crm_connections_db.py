"""The CRM connection store (CRM integration Task 4): one active connection per workspace, connect
requests per chat, newest-click-wins attempts, and the Salesforce daily call counter."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.connections import (
    activate_from_attempt,
    count_salesforce_call,
    get_connect_request,
    latest_connection,
    mark_expired,
    open_connect_request,
    open_settings_connect_request,
    start_attempt,
)
from clue_api.crm.writes import insert_grant
from clue_db import db_lifespan

from .conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _in_rollback(body: Callable[[AsyncConnection, str], Awaitable[None]]) -> None:
    async def run() -> None:
        workspace = f"ws-crm-{uuid.uuid4().hex[:8]}"
        async with db_lifespan() as engine, engine.connect() as conn:
            tx = await conn.begin()
            try:
                await conn.execute(
                    text("INSERT INTO workspace (workspace_id, name) VALUES (:ws, 'CRM')"),
                    {"ws": workspace},
                )
                await body(conn, workspace)
            finally:
                await tx.rollback()

    run_async(run())


async def _request(conn: AsyncConnection, workspace: str, *, mode: str = "connect"):  # type: ignore[no-untyped-def]
    return await open_connect_request(
        conn,
        workspace_id=workspace,
        project_id=f"prj-{uuid.uuid4().hex[:8]}",
        thread_id=f"thr-{uuid.uuid4().hex[:8]}",
        turn_id=uuid.uuid4(),
        requested_by_user_id="user-asker",
        mode=mode,
    )


def test_a_connect_request_is_one_per_turn() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        turn = uuid.uuid4()
        kwargs = {
            "workspace_id": workspace,
            "project_id": "prj-1",
            "thread_id": "thr-1",
            "turn_id": turn,
            "requested_by_user_id": "user-asker",
            "mode": "connect",
        }
        first = await open_connect_request(conn, **kwargs)  # type: ignore[arg-type]
        again = await open_connect_request(conn, **kwargs)  # type: ignore[arg-type]
        assert first.request_id == again.request_id
        assert first.status == "open"

    _in_rollback(body)


def test_activation_requires_the_attempt_it_recorded() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        request = await _request(conn, workspace)
        assert await start_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            provider="hubspot",
            connected_account_id="ca_right",
            started_by_user_id="user-admin",
        )
        refused = await activate_from_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            connected_account_id="ca_wrong",
            auth_config_id="ac_1",
        )
        assert refused is None
        assert await latest_connection(conn, workspace_id=workspace) is None

    _in_rollback(body)


def test_activation_fulfils_every_waiting_chat_in_the_workspace() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        mine = await _request(conn, workspace)
        theirs = await _request(conn, workspace)
        await start_attempt(
            conn,
            request_id=mine.request_id,
            workspace_id=workspace,
            provider="hubspot",
            connected_account_id="ca_1",
            started_by_user_id="user-admin",
        )
        activated = await activate_from_attempt(
            conn,
            request_id=mine.request_id,
            workspace_id=workspace,
            connected_account_id="ca_1",
            auth_config_id="ac_1",
        )
        assert activated is not None
        connection, woken = activated
        assert connection.status == "active" and connection.provider == "hubspot"
        assert connection.connected_by_user_id == "user-admin"
        assert {r.request_id for r in woken} == {mine.request_id, theirs.request_id}
        reread = await get_connect_request(
            conn, request_id=theirs.request_id, workspace_id=workspace
        )
        assert reread is not None and reread.status == "fulfilled"
        # A replayed callback finds nothing open any more.
        assert (
            await activate_from_attempt(
                conn,
                request_id=mine.request_id,
                workspace_id=workspace,
                connected_account_id="ca_1",
                auth_config_id="ac_1",
            )
            is None
        )

    _in_rollback(body)


def test_the_newest_click_wins() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        request = await _request(conn, workspace)
        for account in ("ca_first", "ca_second"):
            await start_attempt(
                conn,
                request_id=request.request_id,
                workspace_id=workspace,
                provider="salesforce",
                connected_account_id=account,
                started_by_user_id="user-admin",
            )
        stale = await activate_from_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            connected_account_id="ca_first",
            auth_config_id="ac_1",
        )
        assert stale is None

    _in_rollback(body)


def test_switching_disconnects_the_previous_crm() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        for provider, account in (("hubspot", "ca_h"), ("salesforce", "ca_s")):
            request = await _request(conn, workspace, mode="switch")
            await start_attempt(
                conn,
                request_id=request.request_id,
                workspace_id=workspace,
                provider=provider,  # type: ignore[arg-type]
                connected_account_id=account,
                started_by_user_id="user-admin",
            )
            assert await activate_from_attempt(
                conn,
                request_id=request.request_id,
                workspace_id=workspace,
                connected_account_id=account,
                auth_config_id="ac_1",
            )
        latest = await latest_connection(conn, workspace_id=workspace)
        assert latest is not None and latest.provider == "salesforce" and latest.status == "active"
        old = await conn.execute(
            text(
                "SELECT status FROM workspace_integration_connection "
                "WHERE composio_connected_account_id = 'ca_h'"
            )
        )
        assert old.scalar_one() == "disconnected"

    _in_rollback(body)


def test_an_attempt_on_a_closed_request_is_refused() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        request = await _request(conn, workspace)
        await conn.execute(
            text("UPDATE crm_connect_request SET status = 'cancelled' WHERE request_id = :id"),
            {"id": request.request_id},
        )
        assert not await start_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            provider="hubspot",
            connected_account_id="ca_1",
            started_by_user_id="user-admin",
        )

    _in_rollback(body)


def test_an_expired_connection_is_reported_as_latest() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        request = await _request(conn, workspace)
        await start_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            provider="hubspot",
            connected_account_id="ca_1",
            started_by_user_id="user-admin",
        )
        activated = await activate_from_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            connected_account_id="ca_1",
            auth_config_id="ac_1",
        )
        assert activated is not None
        await mark_expired(conn, connection_id=activated[0].connection_id)
        latest = await latest_connection(conn, workspace_id=workspace)
        assert latest is not None and latest.status == "expired"

    _in_rollback(body)


def test_the_salesforce_counter_resets_each_day() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        request = await _request(conn, workspace)
        await start_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            provider="salesforce",
            connected_account_id="ca_sf",
            started_by_user_id="user-admin",
        )
        activated = await activate_from_attempt(
            conn,
            request_id=request.request_id,
            workspace_id=workspace,
            connected_account_id="ca_sf",
            auth_config_id="ac_1",
        )
        assert activated is not None
        connection_id = activated[0].connection_id
        day = date(2026, 10, 20)
        assert await count_salesforce_call(conn, connection_id=connection_id, today=day) == 1
        assert await count_salesforce_call(conn, connection_id=connection_id, today=day) == 2
        next_day = date(2026, 10, 21)
        assert await count_salesforce_call(conn, connection_id=connection_id, today=next_day) == 1

    _in_rollback(body)


async def _connect(
    conn: AsyncConnection,
    workspace: str,
    *,
    provider: str,
    account: str,
    external: str | None,
    auth_config: str = "ac_1",
    name: str | None = None,
):  # type: ignore[no-untyped-def]
    request = await _request(conn, workspace)
    await start_attempt(
        conn,
        request_id=request.request_id,
        workspace_id=workspace,
        provider=provider,  # type: ignore[arg-type]
        connected_account_id=account,
        started_by_user_id="user-admin",
    )
    activated = await activate_from_attempt(
        conn,
        request_id=request.request_id,
        workspace_id=workspace,
        connected_account_id=account,
        auth_config_id=auth_config,
        external_account_id=external,
        external_account_name=name,
    )
    assert activated is not None
    return activated[0]


async def _rows(conn: AsyncConnection, workspace: str) -> list[tuple[str, str, str | None]]:
    rows = await conn.execute(
        text(
            "SELECT composio_connected_account_id, status, external_account_id "
            "FROM workspace_integration_connection WHERE workspace_id = :ws "
            "ORDER BY connected_at, composio_connected_account_id"
        ),
        {"ws": workspace},
    )
    return [tuple(r) for r in rows]  # type: ignore[misc]


def test_a_reconnect_to_the_same_crm_account_keeps_the_connection() -> None:
    """D-2 (2026-10-25): an expired connection reconnected to the same Salesforce org (or HubSpot
    portal) is the same CRM — the connection, and everything keyed on it (undo, Clue's fields,
    list and record links), carries on."""

    async def body(conn: AsyncConnection, workspace: str) -> None:
        first = await _connect(
            conn, workspace, provider="salesforce", account="ca_old", external="00DORG"
        )
        await mark_expired(conn, connection_id=first.connection_id)
        again = await _connect(
            conn,
            workspace,
            provider="salesforce",
            account="ca_new",
            external="00DORG",
            auth_config="ac_own",
        )
        assert again.connection_id == first.connection_id
        assert again.status == "active"
        assert again.composio_connected_account_id == "ca_new"
        assert again.composio_auth_config_id == "ac_own"
        assert await _rows(conn, workspace) == [("ca_new", "active", "00DORG")]

    _in_rollback(body)


def test_a_reconnect_while_still_active_keeps_the_connection() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        first = await _connect(conn, workspace, provider="hubspot", account="ca_1", external="111")
        again = await _connect(conn, workspace, provider="hubspot", account="ca_2", external="111")
        assert again.connection_id == first.connection_id
        assert await _rows(conn, workspace) == [("ca_2", "active", "111")]

    _in_rollback(body)


def test_switching_clears_the_previous_connections_standing_permissions() -> None:
    """The Change CRM dialog says "Always allow" permissions are cleared: a switch revokes the old
    connection's grants, as Disconnect does, so a later reconnect to that account brings none
    back (final review 2026-10-26)."""

    async def body(conn: AsyncConnection, workspace: str) -> None:
        first = await _connect(conn, workspace, provider="hubspot", account="ca_1", external="111")
        await insert_grant(
            conn,
            workspace_id=workspace,
            connection_id=first.connection_id,
            scope_key="field:company.clue_fit_level",
            granted_by_user_id="user-admin",
        )
        await _connect(conn, workspace, provider="hubspot", account="ca_2", external="222")
        live = await conn.scalar(
            text(
                "SELECT count(*) FROM crm_write_grant "
                "WHERE connection_id = :c AND revoked_at IS NULL"
            ),
            {"c": first.connection_id},
        )
        assert live == 0
        back = await _connect(conn, workspace, provider="hubspot", account="ca_3", external="111")
        assert back.connection_id == first.connection_id
        assert (
            await conn.scalar(
                text(
                    "SELECT count(*) FROM crm_write_grant "
                    "WHERE connection_id = :c AND revoked_at IS NULL"
                ),
                {"c": back.connection_id},
            )
            == 0
        )

    _in_rollback(body)


def test_another_crm_account_is_a_new_connection() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        first = await _connect(conn, workspace, provider="hubspot", account="ca_1", external="111")
        other = await _connect(conn, workspace, provider="hubspot", account="ca_2", external="222")
        assert other.connection_id != first.connection_id
        assert await _rows(conn, workspace) == [
            ("ca_1", "disconnected", "111"),
            ("ca_2", "active", "222"),
        ]

    _in_rollback(body)


def test_an_unknown_crm_account_is_a_new_connection() -> None:
    """When the account cannot be identified, nothing is assumed: a new connection, as before."""

    async def body(conn: AsyncConnection, workspace: str) -> None:
        first = await _connect(conn, workspace, provider="hubspot", account="ca_1", external="111")
        await mark_expired(conn, connection_id=first.connection_id)
        unknown = await _connect(conn, workspace, provider="hubspot", account="ca_2", external=None)
        assert unknown.connection_id != first.connection_id
        assert await _rows(conn, workspace) == [
            ("ca_1", "expired", "111"),
            ("ca_2", "active", None),
        ]

    _in_rollback(body)


def test_a_settings_connect_request_is_fulfilled_with_the_chats() -> None:
    """R-15.3: Settings connects without a chat — its request has no project, thread or turn, and
    activation fulfils it along with every waiting chat's request."""

    async def body(conn: AsyncConnection, workspace: str) -> None:
        chat = await _request(conn, workspace)
        settings = await open_settings_connect_request(
            conn, workspace_id=workspace, requested_by_user_id="user-admin", mode="switch"
        )
        assert (settings.project_id, settings.thread_id, settings.turn_id) == (None, None, None)
        assert settings.status == "open" and settings.mode == "switch"
        assert await start_attempt(
            conn,
            request_id=settings.request_id,
            workspace_id=workspace,
            provider="salesforce",
            connected_account_id="ca_settings",
            started_by_user_id="user-admin",
        )
        activated = await activate_from_attempt(
            conn,
            request_id=settings.request_id,
            workspace_id=workspace,
            connected_account_id="ca_settings",
            auth_config_id="ac_1",
        )
        assert activated is not None
        assert {r.request_id for r in activated[1]} == {chat.request_id, settings.request_id}

    _in_rollback(body)


def test_a_connect_request_has_all_of_its_chat_or_none_of_it() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        nested = await conn.begin_nested()
        with pytest.raises(IntegrityError, match="crm_connect_request_chat_all_or_none"):
            await conn.execute(
                text(
                    "INSERT INTO crm_connect_request (request_id, workspace_id, project_id, "
                    "requested_by_user_id, mode) VALUES (:id, :ws, 'prj-1', 'user-a', 'connect')"
                ),
                {"id": uuid.uuid4(), "ws": workspace},
            )
        await nested.rollback()

    _in_rollback(body)


def test_the_crm_account_name_is_kept_and_refreshed_on_reconnect() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        first = await _connect(
            conn, workspace, provider="salesforce", account="ca_1", external="00D", name="Acme"
        )
        assert first.external_account_name == "Acme"
        renamed = await _connect(
            conn, workspace, provider="salesforce", account="ca_2", external="00D", name="Acme Inc"
        )
        assert renamed.connection_id == first.connection_id
        assert renamed.external_account_name == "Acme Inc"
        # A reconnect whose name query failed keeps the name already known.
        unnamed = await _connect(
            conn, workspace, provider="salesforce", account="ca_3", external="00D", name=None
        )
        assert unnamed.external_account_name == "Acme Inc"

    _in_rollback(body)
