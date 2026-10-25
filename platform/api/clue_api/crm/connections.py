"""The workspace CRM connection and the connect requests that wait on it.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§4, §7; rulings R-3.1 (workspace-owned), R-3.10 (connect card + connect requests), R-15.3
(Settings connects without a chat). A workspace has at most one ``active`` connection (a partial
unique index). A connect request is one connect card shown in one chat, or one connect from
Settings (no project, thread or turn); it records the latest login attempt (newest click wins) so
the callback can be verified before anything is activated, and activation fulfils every open
request in the workspace so each waiting chat can be woken.

Every function writes through the ``conn`` it is given and never commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.composio_gateway import (
    ComposioError,
    ComposioGateway,
    CrmProvider,
    ExecuteResult,
    composio_user_id,
)

__all__ = [
    "ConnectRequest",
    "CrmAccountIdentity",
    "CrmConnection",
    "OVERWRITES_MODES",
    "OverwritesMode",
    "activate_from_attempt",
    "connection_overwrites",
    "count_salesforce_call",
    "crm_account_identity",
    "disconnect",
    "get_connect_request",
    "get_connection",
    "latest_connection",
    "mark_expired",
    "open_connect_request",
    "open_settings_connect_request",
    "set_connection_overwrites",
    "start_attempt",
]


#: The "who am I" action of each CRM and the field naming its account (verified live 2026-10-25:
#: HubSpot ``portal_id``, Salesforce ``organization_id``; neither needs an extra scope).
_IDENTITY: dict[CrmProvider, tuple[str, str]] = {
    "hubspot": ("HUBSPOT_WHO_AM_I", "portal_id"),
    "salesforce": ("SALESFORCE_WHO_AM_I", "organization_id"),
}


#: The Salesforce org's name (R-15.3). HubSpot's portal name needs a scope Clue does not ask
#: for, so a HubSpot connection has no name and the page shows "Portal <id>".
_SALESFORCE_ORG_NAME_QUERY = "SELECT Name FROM Organization LIMIT 1"


@dataclass(frozen=True)
class CrmAccountIdentity:
    """The CRM account a grant belongs to: its id, and its name when the CRM gives one."""

    external_id: str
    name: str | None


def _body(result: ExecuteResult) -> dict[str, Any]:
    """A successful answer's body; Composio sometimes nests the CRM's body under ``data``."""
    data = result.data if result.successful and isinstance(result.data, dict) else {}
    inner = data.get("data")
    return inner if isinstance(inner, dict) else data


async def crm_account_identity(
    gateway: ComposioGateway,
    *,
    provider: CrmProvider,
    connected_account_id: str,
    workspace_id: str,
    version: str,
) -> CrmAccountIdentity | None:
    """The CRM account a new grant belongs to (HubSpot portal id, Salesforce org id and name), or
    ``None`` when the CRM does not say which account — then the grant is treated as a new
    connection (D-2). A failed name query leaves the name ``None`` and keeps the id."""

    async def call(slug: str, arguments: dict[str, Any]) -> ExecuteResult | None:
        try:
            return await gateway.execute(
                slug=slug,
                arguments=arguments,
                connected_account_id=connected_account_id,
                user_id=composio_user_id(workspace_id),
                version=version,
            )
        except ComposioError:
            return None

    slug, field = _IDENTITY[provider]
    who = await call(slug, {})
    value = None if who is None else _body(who).get(field)
    if value in (None, ""):
        return None
    name: str | None = None
    if provider == "salesforce":
        answer = await call("SALESFORCE_RUN_SOQL_QUERY", {"query": _SALESFORCE_ORG_NAME_QUERY})
        records = None if answer is None else _body(answer).get("records")
        first = records[0] if isinstance(records, list) and records else None
        found = first.get("Name") if isinstance(first, dict) else None
        if found is not None and str(found).strip():
            name = str(found).strip()
    return CrmAccountIdentity(external_id=str(value), name=name)


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
    external_account_id: str | None = None
    external_account_name: str | None = None


@dataclass(frozen=True)
class ConnectRequest:
    """One connect card in a chat, or one connect from Settings — then ``project_id``,
    ``thread_id`` and ``turn_id`` are all ``None`` (there is no chat to wake)."""

    request_id: UUID
    workspace_id: str
    project_id: str | None
    thread_id: str | None
    turn_id: UUID | None
    requested_by_user_id: str
    mode: str
    status: str
    pending_connected_account_id: str | None
    pending_provider: CrmProvider | None


_CONNECTION_COLUMNS = (
    "connection_id, workspace_id, provider, composio_connected_account_id, "
    "composio_auth_config_id, status, connected_by_user_id, connected_at, "
    "external_account_id, external_account_name"
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


async def open_settings_connect_request(
    conn: AsyncConnection, *, workspace_id: str, requested_by_user_id: str, mode: str
) -> ConnectRequest:
    """A connect request from Settings (R-15.3): no chat, so nothing is woken when it is fulfilled.
    An open Settings request of the workspace with the same mode is reused (each click records its
    own attempt on it, newest wins), so clicking again never piles up requests; activation fulfils
    it with every other open request."""
    found = (
        await conn.execute(
            text(
                f"SELECT {_REQUEST_COLUMNS} FROM crm_connect_request "
                "WHERE workspace_id = :ws AND status = 'open' AND turn_id IS NULL "
                "AND mode = :mode ORDER BY created_at DESC LIMIT 1 FOR UPDATE"
            ),
            {"ws": workspace_id, "mode": mode},
        )
    ).first()
    if found is not None:
        return _request(found)
    row = (
        await conn.execute(
            text(
                "INSERT INTO crm_connect_request (request_id, workspace_id, requested_by_user_id, "
                f"mode) VALUES (:id, :ws, :user, :mode) RETURNING {_REQUEST_COLUMNS}"
            ),
            {"id": uuid4(), "ws": workspace_id, "user": requested_by_user_id, "mode": mode},
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
    external_account_id: str | None = None,
    external_account_name: str | None = None,
) -> tuple[CrmConnection, list[ConnectRequest]] | None:
    """Activate the connection the request's latest attempt produced.

    Returns ``None`` unless the request is open and its latest attempt is exactly
    ``connected_account_id`` (a stale, replayed or forged callback activates nothing). Otherwise
    disconnects any other active connection (a switch), activates the connection, and marks every
    open request in the workspace ``fulfilled`` — returning them so each waiting chat can be woken.

    ``external_account_id`` is the CRM account the new grant belongs to (Salesforce org id, HubSpot
    portal id). A grant to the account an earlier connection of this workspace already holds is a
    **reconnect**: that connection is made active again with the new grant, so everything keyed on
    it — undo, Clue's fields, list and record links — carries on (D-2, 2026-10-25). A grant to
    another account, or one that could not be identified, is a new connection, as before.
    ``external_account_name`` is the account's name (Salesforce org name); a reconnect refreshes
    it when one was found and otherwise keeps the name already known.
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
    same_account = (
        None
        if external_account_id is None
        else (
            await conn.execute(
                text(
                    "SELECT connection_id FROM workspace_integration_connection "
                    "WHERE workspace_id = :ws AND provider = :provider "
                    "AND external_account_id = :external "
                    "ORDER BY connected_at DESC LIMIT 1 FOR UPDATE"
                ),
                {
                    "ws": workspace_id,
                    "provider": request.pending_provider,
                    "external": external_account_id,
                },
            )
        ).scalar_one_or_none()
    )
    await conn.execute(
        text(
            "UPDATE workspace_integration_connection SET status = 'disconnected', "
            "disconnected_at = now(), updated_at = now() "
            "WHERE workspace_id = :ws AND status = 'active' "
            "AND connection_id IS DISTINCT FROM :keep"
        ),
        {"ws": workspace_id, "keep": same_account},
    )
    values = {
        "ws": workspace_id,
        "provider": request.pending_provider,
        "account": connected_account_id,
        "ac": auth_config_id,
        "user": request.pending_started_by_user_id,
        "external": external_account_id,
        "name": external_account_name,
    }
    if same_account is not None:
        row = (
            await conn.execute(
                text(
                    "UPDATE workspace_integration_connection SET status = 'active', "
                    "composio_connected_account_id = :account, composio_auth_config_id = :ac, "
                    "connected_by_user_id = :user, connected_at = now(), disconnected_at = NULL, "
                    "external_account_name = COALESCE(CAST(:name AS text), external_account_name), "
                    "updated_at = now() WHERE connection_id = :id "
                    f"RETURNING {_CONNECTION_COLUMNS}"
                ),
                {**values, "id": same_account},
            )
        ).one()
    else:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO workspace_integration_connection (connection_id, workspace_id, "
                    "provider, composio_connected_account_id, composio_auth_config_id, status, "
                    "connected_by_user_id, external_account_id, external_account_name) VALUES "
                    "(:id, :ws, :provider, :account, :ac, 'active', :user, :external, :name) "
                    f"RETURNING {_CONNECTION_COLUMNS}"
                ),
                {**values, "id": uuid4()},
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


async def disconnect(conn: AsyncConnection, *, connection_id: UUID) -> bool:
    """Disconnect an active or expired connection (Settings, R-15.3); ``False`` when it was
    already disconnected. The row is kept: a later connect to the same CRM account reuses it."""
    result = await conn.execute(
        text(
            "UPDATE workspace_integration_connection SET status = 'disconnected', "
            "disconnected_at = now(), updated_at = now() "
            "WHERE connection_id = :id AND status IN ('active', 'expired')"
        ),
        {"id": connection_id},
    )
    return result.rowcount == 1


#: How Clue treats a change that overwrites a value a person set (R-15.1): ``ask`` on a card
#: every time (the default), or ``follow_grants`` — standing permissions cover it too.
OverwritesMode = Literal["ask", "follow_grants"]
OVERWRITES_MODES: tuple[OverwritesMode, ...] = ("ask", "follow_grants")


async def connection_overwrites(conn: AsyncConnection, *, connection_id: UUID) -> OverwritesMode:
    """The connection's overwrites setting (``settings.overwrites``); ``ask`` when unset."""
    value = await conn.scalar(
        text(
            "SELECT settings ->> 'overwrites' FROM workspace_integration_connection "
            "WHERE connection_id = :id"
        ),
        {"id": connection_id},
    )
    return "follow_grants" if value == "follow_grants" else "ask"


async def set_connection_overwrites(
    conn: AsyncConnection, *, connection_id: UUID, mode: OverwritesMode
) -> None:
    await conn.execute(
        text(
            "UPDATE workspace_integration_connection SET "
            "settings = settings || jsonb_build_object('overwrites', CAST(:mode AS text)), "
            "updated_at = now() WHERE connection_id = :id"
        ),
        {"id": connection_id, "mode": mode},
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
