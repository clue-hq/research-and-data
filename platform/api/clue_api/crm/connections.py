"""The workspace CRM connection and the connect requests that wait on it.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§4, §7; rulings R-3.1 (workspace-owned), R-3.10 (connect card + connect requests). A workspace has
at most one ``active`` connection (a partial unique index). A connect request is one connect card
shown in one chat; it records the latest login attempt (newest click wins) so the callback can be
verified before anything is activated, and activation fulfils every open request in the workspace
so each waiting chat can be woken.

Every function writes through the ``conn`` it is given and never commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.composio_gateway import CrmProvider

__all__ = [
    "ConnectRequest",
    "CrmConnection",
    "activate_from_attempt",
    "count_salesforce_call",
    "get_connect_request",
    "get_connection",
    "latest_connection",
    "mark_expired",
    "open_connect_request",
    "start_attempt",
]


@dataclass(frozen=True)
class CrmConnection:
    connection_id: UUID
    workspace_id: str
    provider: CrmProvider
    composio_connected_account_id: str
    composio_auth_config_id: str
    status: str
    connected_by_user_id: str
    connected_at: datetime


@dataclass(frozen=True)
class ConnectRequest:
    request_id: UUID
    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: UUID
    requested_by_user_id: str
    mode: str
    status: str
    pending_connected_account_id: str | None
    pending_provider: CrmProvider | None


_CONNECTION_COLUMNS = (
    "connection_id, workspace_id, provider, composio_connected_account_id, "
    "composio_auth_config_id, status, connected_by_user_id, connected_at"
)
_REQUEST_COLUMNS = (
    "request_id, workspace_id, project_id, thread_id, turn_id, requested_by_user_id, mode, "
    "status, pending_connected_account_id, pending_provider"
)


def _connection(row: Any) -> CrmConnection:
    return CrmConnection(**dict(row._mapping))


def _request(row: Any) -> ConnectRequest:
    return ConnectRequest(**dict(row._mapping))


async def latest_connection(conn: AsyncConnection, *, workspace_id: str) -> CrmConnection | None:
    """The active connection, else the most recently changed one (e.g. ``expired``)."""
    row = (
        await conn.execute(
            text(
                f"SELECT {_CONNECTION_COLUMNS} FROM workspace_integration_connection "
                "WHERE workspace_id = :ws "
                "ORDER BY (status = 'active') DESC, updated_at DESC LIMIT 1"
            ),
            {"ws": workspace_id},
        )
    ).first()
    return None if row is None else _connection(row)


async def get_connection(conn: AsyncConnection, *, connection_id: UUID) -> CrmConnection | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_CONNECTION_COLUMNS} FROM workspace_integration_connection "
                "WHERE connection_id = :id"
            ),
            {"id": connection_id},
        )
    ).first()
    return None if row is None else _connection(row)


async def open_connect_request(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    requested_by_user_id: str,
    mode: str,
) -> ConnectRequest:
    """One request per turn: a replayed ``connect_crm`` call returns the same request."""
    await conn.execute(
        text(
            "INSERT INTO crm_connect_request (request_id, workspace_id, project_id, thread_id, "
            "turn_id, requested_by_user_id, mode) VALUES (:id, :ws, :project, :thread, :turn, "
            ":user, :mode) ON CONFLICT (turn_id) DO NOTHING"
        ),
        {
            "id": uuid4(),
            "ws": workspace_id,
            "project": project_id,
            "thread": thread_id,
            "turn": turn_id,
            "user": requested_by_user_id,
            "mode": mode,
        },
    )
    row = (
        await conn.execute(
            text(f"SELECT {_REQUEST_COLUMNS} FROM crm_connect_request WHERE turn_id = :turn"),
            {"turn": turn_id},
        )
    ).one()
    return _request(row)


async def get_connect_request(
    conn: AsyncConnection, *, request_id: UUID, workspace_id: str
) -> ConnectRequest | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_REQUEST_COLUMNS} FROM crm_connect_request "
                "WHERE request_id = :id AND workspace_id = :ws"
            ),
            {"id": request_id, "ws": workspace_id},
        )
    ).first()
    return None if row is None else _request(row)


async def start_attempt(
    conn: AsyncConnection,
    *,
    request_id: UUID,
    workspace_id: str,
    provider: CrmProvider,
    connected_account_id: str,
    started_by_user_id: str,
) -> bool:
    """Record a login attempt on an open request; the newest click replaces any earlier one.

    Returns ``False`` when the request is not open (or not in this workspace).
    """
    result = await conn.execute(
        text(
            "UPDATE crm_connect_request SET pending_connected_account_id = :account, "
            "pending_provider = :provider, pending_started_by_user_id = :user, "
            "pending_started_at = now() "
            "WHERE request_id = :id AND workspace_id = :ws AND status = 'open'"
        ),
        {
            "account": connected_account_id,
            "provider": provider,
            "user": started_by_user_id,
            "id": request_id,
            "ws": workspace_id,
        },
    )
    return result.rowcount == 1


async def activate_from_attempt(
    conn: AsyncConnection,
    *,
    request_id: UUID,
    workspace_id: str,
    connected_account_id: str,
    auth_config_id: str,
) -> tuple[CrmConnection, list[ConnectRequest]] | None:
    """Activate the connection the request's latest attempt produced.

    Returns ``None`` unless the request is open and its latest attempt is exactly
    ``connected_account_id`` (a stale, replayed or forged callback activates nothing). Otherwise
    disconnects any other active connection (a switch), inserts the new active row, and marks every
    open request in the workspace ``fulfilled`` — returning them so each waiting chat can be woken.
    """
    request = (
        await conn.execute(
            text(
                "SELECT pending_connected_account_id, pending_provider, pending_started_by_user_id "
                "FROM crm_connect_request WHERE request_id = :id AND workspace_id = :ws "
                "AND status = 'open' FOR UPDATE"
            ),
            {"id": request_id, "ws": workspace_id},
        )
    ).first()
    if request is None or request.pending_connected_account_id != connected_account_id:
        return None
    await conn.execute(
        text(
            "UPDATE workspace_integration_connection SET status = 'disconnected', "
            "disconnected_at = now(), updated_at = now() "
            "WHERE workspace_id = :ws AND status = 'active'"
        ),
        {"ws": workspace_id},
    )
    row = (
        await conn.execute(
            text(
                "INSERT INTO workspace_integration_connection (connection_id, workspace_id, "
                "provider, composio_connected_account_id, composio_auth_config_id, status, "
                "connected_by_user_id) VALUES (:id, :ws, :provider, :account, :ac, 'active', "
                f":user) RETURNING {_CONNECTION_COLUMNS}"
            ),
            {
                "id": uuid4(),
                "ws": workspace_id,
                "provider": request.pending_provider,
                "account": connected_account_id,
                "ac": auth_config_id,
                "user": request.pending_started_by_user_id,
            },
        )
    ).one()
    fulfilled = (
        await conn.execute(
            text(
                "UPDATE crm_connect_request SET status = 'fulfilled', fulfilled_at = now() "
                f"WHERE workspace_id = :ws AND status = 'open' RETURNING {_REQUEST_COLUMNS}"
            ),
            {"ws": workspace_id},
        )
    ).all()
    return _connection(row), [_request(r) for r in fulfilled]


async def mark_expired(conn: AsyncConnection, *, connection_id: UUID) -> None:
    await conn.execute(
        text(
            "UPDATE workspace_integration_connection SET status = 'expired', updated_at = now() "
            "WHERE connection_id = :id AND status = 'active'"
        ),
        {"id": connection_id},
    )


async def count_salesforce_call(
    conn: AsyncConnection, *, connection_id: UUID, today: date, allowed: int | None = None
) -> int | None:
    """Count one Clue API call against the connection for ``today`` (UTC); returns the new count.

    With ``allowed``, the call is counted only while today's count is below it, in the same
    statement (two turns cannot both take the last call), and ``None`` means the share is used up.
    """
    count = (
        await conn.execute(
            text(
                "UPDATE workspace_integration_connection SET "
                "api_calls_count = CASE WHEN api_calls_day = :today "
                "THEN api_calls_count + 1 ELSE 1 END, api_calls_day = :today "
                "WHERE connection_id = :id AND (CAST(:allowed AS integer) IS NULL "
                "OR api_calls_day IS DISTINCT FROM :today OR api_calls_count < :allowed) "
                "RETURNING api_calls_count"
            ),
            {"today": today, "id": connection_id, "allowed": allowed},
        )
    ).scalar_one_or_none()
    return None if count is None else int(count)
