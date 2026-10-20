"""The CRM connection store (CRM integration Task 4): one active connection per workspace, connect
requests per chat, newest-click-wins attempts, and the Salesforce daily call counter."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.connections import (
    activate_from_attempt,
    count_salesforce_call,
    get_connect_request,
    latest_connection,
    mark_expired,
    open_connect_request,
    start_attempt,
)
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
        project_id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        requested_by_user_id="user-asker",
        mode=mode,
    )


def test_a_connect_request_is_one_per_turn() -> None:
    async def body(conn: AsyncConnection, workspace: str) -> None:
        turn = uuid.uuid4()
        kwargs = {
            "workspace_id": workspace,
            "project_id": uuid.uuid4(),
            "thread_id": uuid.uuid4(),
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
