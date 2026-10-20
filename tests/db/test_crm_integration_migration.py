"""CRM integration Phase 1: the connection table, the connect-request table, and the
``crm_connected`` derived-turn kind (spec docs/superpowers/specs/crm-integration/, R-3.10)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan

from .conftest import run_async

WS = "ws-crm-migration"


async def _with_rollback(body) -> None:  # type: ignore[no-untyped-def]
    async with db_lifespan() as engine, engine.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(
                text(
                    "INSERT INTO workspace (workspace_id, name) VALUES (:ws, 'CRM') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"ws": WS},
            )
            await body(conn)
        finally:
            await tx.rollback()


async def _connection(conn: AsyncConnection, *, status: str, provider: str = "hubspot") -> None:
    await conn.execute(
        text(
            "INSERT INTO workspace_integration_connection (connection_id, workspace_id, provider, "
            "composio_connected_account_id, composio_auth_config_id, status, connected_by_user_id) "
            "VALUES (:id, :ws, :provider, :acct, 'ac_test', :status, 'user-1')"
        ),
        {
            "id": uuid.uuid4(),
            "ws": WS,
            "provider": provider,
            "acct": f"ca_{uuid.uuid4().hex[:8]}",
            "status": status,
        },
    )


@pytest.mark.usefixtures("require_db")
def test_one_active_connection_per_workspace() -> None:
    async def body(conn: AsyncConnection) -> None:
        await _connection(conn, status="expired")
        await _connection(conn, status="active")
        nested = await conn.begin_nested()
        with pytest.raises(IntegrityError):
            await _connection(conn, status="active", provider="salesforce")
        await nested.rollback()

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
@pytest.mark.parametrize(("provider", "status"), [("pipedrive", "active"), ("hubspot", "pending")])
def test_provider_and_status_are_checked(provider: str, status: str) -> None:
    async def body(conn: AsyncConnection) -> None:
        with pytest.raises(IntegrityError):
            await _connection(conn, status=status, provider=provider)

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
@pytest.mark.parametrize(("mode", "status"), [("merge", "open"), ("connect", "done")])
def test_connect_request_mode_and_status_are_checked(mode: str, status: str) -> None:
    async def body(conn: AsyncConnection) -> None:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO crm_connect_request (request_id, workspace_id, project_id, "
                    "thread_id, turn_id, requested_by_user_id, mode, status) VALUES (:id, :ws, "
                    ":p, :t, :turn, 'user-1', :mode, :status)"
                ),
                {
                    "id": uuid.uuid4(),
                    "ws": WS,
                    "p": "prj-1",
                    "t": "thr-1",
                    "turn": uuid.uuid4(),
                    "mode": mode,
                    "status": status,
                },
            )

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
def test_the_derived_turn_kind_admits_crm_connected_and_keeps_the_others() -> None:
    async def read() -> str:
        async with db_lifespan() as engine, engine.connect() as conn:
            found = await conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'agent_turn_submission'::regclass "
                    "AND conname = 'agent_turn_submission_derivation_kind'"
                )
            )
            return str(found.scalar_one())

    definition = run_async(read())
    for kind in (
        "crm_connected",
        "discovery_finished",
        "design_leg_first_turn",
        "design_leg_redelivery",
    ):
        assert f"'{kind}'" in definition, kind
