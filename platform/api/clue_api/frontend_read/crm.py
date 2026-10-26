"""``/frontend/v1/crm/*`` — connecting the workspace's CRM from the chat's connect card.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§4.1; rulings R-3.1, R-3.10. The card (drawn from the ``connect_crm`` tool's result) calls
``connect-link`` for a fresh Composio link on each click — links live about ten minutes, so none is
stored for reuse. Composio sends the browser back to the frontend's callback page, which calls
``complete``: the connection is activated only when Composio reports it ACTIVE and it is exactly
the attempt this request recorded, and then every chat waiting on the connection is woken, and
the CRM changes the replaced connection had not sent are closed (never sent on the new one) and
their chats asked to propose them again.

Connecting requires ``workspace.manage_settings`` (owners and admins); any member may read the
connection's status, and the progress of a CRM write permission card (``GET /crm/proposals/{id}``:
what was sent, what failed with the CRM's own message, what was skipped and why, who answered;
card spec §3 B–F, §6).

Settings → Integrations (R-15.1–R-15.3): any member reads ``GET /crm/integration`` and revokes a
standing permission; owners and admins open a connect request without a chat
(``POST /crm/connect-request``, then the same ``connect-link`` and ``complete``), disconnect, and
set how overwrites are treated.
"""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.crm.composio_gateway import (
    ComposioError,
    ComposioGateway,
    CrmProvider,
    build_composio_gateway,
    composio_user_id,
)
from clue_api.crm.connections import (
    CrmAccountIdentity,
    OverwritesMode,
    activate_from_attempt,
    crm_account_identity,
    disconnect,
    get_connect_request,
    latest_connection,
    open_settings_connect_request,
    set_connection_overwrites,
    start_attempt,
)
from clue_api.crm.settings_view import integration_view
from clue_api.crm.wake import queue_crm_connected_turns
from clue_api.crm.write_answer import proposal_progress
from clue_api.crm.write_executor import (
    close_disconnected_proposals,
    close_replaced_connection_proposals,
)
from clue_api.crm.writes import revoke_all_grants, revoke_grant
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.settings_authority import lock_manager, principal_for, refused
from clue_auth.policy import Permission
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_storage import StorageBackend

__all__ = ["CALLBACK_PATH", "auth_config_for", "register_crm_routes"]

log = get_logger("clue_api.frontend_read.crm")

PERMISSION: Permission = "workspace.manage_settings"
#: The frontend page Composio returns the browser to after the CRM's consent screen.
CALLBACK_PATH = "/integrations/crm/callback"


class ConnectLinkBody(WireModel):
    """Wire casing is camelCase (``requestId``); snake_case is accepted too."""

    request_id: UUID
    provider: CrmProvider


class CompleteBody(WireModel):
    request_id: UUID
    status: str
    connected_account_id: str


class ConnectRequestBody(WireModel):
    mode: Literal["connect", "reconnect", "switch"]


class OverwritesBody(WireModel):
    mode: OverwritesMode


def auth_config_for(settings: Settings, provider: CrmProvider) -> str:
    """The Composio auth config for ``provider``; empty when that CRM is not offered."""
    return (
        settings.composio_hubspot_auth_config_id
        if provider == "hubspot"
        else settings.composio_salesforce_auth_config_id
    ).strip()


_PROVIDERS: frozenset[str] = frozenset({"hubspot", "salesforce"})


def _toolkit_version(settings: Settings, provider: CrmProvider) -> str:
    return (
        settings.composio_hubspot_toolkit_version
        if provider == "hubspot"
        else settings.composio_salesforce_toolkit_version
    )


def register_crm_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    settings: Settings,
    secrets: Secrets | None,
    evidence_storage: StorageBackend | None,
) -> None:
    built = build_composio_gateway(settings=settings, secrets=secrets)
    artifacts = (
        None
        if evidence_storage is None
        else DurableAgentArtifactStore(storage=evidence_storage, conn_factory=conn_factory)
    )

    def _gateway(request: Request) -> ComposioGateway:
        # Tests inject a fake through app.state; production has nothing there.
        gateway = getattr(request.app.state, "crm_gateway", None) or built
        if gateway is None:
            raise refused(503, "crm_not_configured", "The CRM integration is not configured.")
        return gateway

    @router.post("/crm/connect-link")
    async def connect_link(
        body: ConnectLinkBody, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission=PERMISSION)
        gateway = _gateway(request)
        auth_config = auth_config_for(settings, body.provider)
        if not auth_config:
            raise refused(409, "crm_not_configured", f"{body.provider} is not offered here.")
        async with conn_factory() as conn:
            card = await get_connect_request(
                conn, request_id=body.request_id, workspace_id=workspace_id
            )
        if card is None or card.status != "open":
            raise refused(409, "connect_request_closed", "This connect card is no longer open.")
        callback = f"{settings.app_origin.rstrip('/')}{CALLBACK_PATH}?request={body.request_id}"
        try:
            link = await gateway.create_link(
                auth_config_id=auth_config,
                user_id=composio_user_id(workspace_id),
                callback_url=callback,
            )
        except ComposioError as error:
            raise refused(502, "crm_link_failed", error.message) from error
        async with conn_factory() as conn:
            await lock_manager(conn, principal, PERMISSION)
            recorded = await start_attempt(
                conn,
                request_id=body.request_id,
                workspace_id=workspace_id,
                provider=body.provider,
                connected_account_id=link.connected_account_id,
                started_by_user_id=principal.user_id,
            )
        if not recorded:
            raise refused(409, "connect_request_closed", "This connect card is no longer open.")
        return {
            "redirectUrl": link.redirect_url,
            "expiresAt": None if link.expires_at is None else link.expires_at.isoformat(),
        }

    @router.post("/crm/complete")
    async def complete(
        body: CompleteBody, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission=PERMISSION)
        gateway = _gateway(request)
        failed: dict[str, Any] = {"outcome": "failed"}
        if body.status != "success":
            return failed
        try:
            account = await gateway.get_account(body.connected_account_id)
        except ComposioError as error:
            log.warning("crm.complete.account_lookup_failed", kind=error.kind)
            return failed
        if account.status != "ACTIVE":
            return failed
        # Which CRM account the grant belongs to: the same one as an earlier connection is a
        # reconnect, and keeps that connection (D-2). Asked before any lock is held.
        identity: CrmAccountIdentity | None = None
        if account.toolkit in _PROVIDERS:
            toolkit = cast("CrmProvider", account.toolkit)
            identity = await crm_account_identity(
                gateway,
                provider=toolkit,
                connected_account_id=body.connected_account_id,
                workspace_id=workspace_id,
                version=_toolkit_version(settings, toolkit),
            )
        async with conn_factory() as conn:
            await lock_manager(conn, principal, PERMISSION)
            card = await get_connect_request(
                conn, request_id=body.request_id, workspace_id=workspace_id
            )
            provider = None if card is None else card.pending_provider
            if provider is None or account.toolkit != provider:
                return {"outcome": "stale"}
            activated = await activate_from_attempt(
                conn,
                request_id=body.request_id,
                workspace_id=workspace_id,
                connected_account_id=body.connected_account_id,
                auth_config_id=auth_config_for(settings, provider),
                external_account_id=None if identity is None else identity.external_id,
                external_account_name=None if identity is None else identity.name,
            )
            if activated is None:
                return {"outcome": "stale"}
            connection, waiting = activated
            if artifacts is None:
                log.warning("crm.complete.no_artifact_store", waiting=len(waiting))
            else:
                await queue_crm_connected_turns(
                    conn, artifacts, requests=waiting, provider=provider
                )
            # CRM changes the replaced connection had not sent are never sent on this one (it
            # may be another portal or org): they are closed and their chats asked to re-propose.
            await close_replaced_connection_proposals(
                conn,
                artifacts,
                workspace_id=workspace_id,
                active_connection_id=connection.connection_id,
            )
        return {"outcome": "connected", "provider": provider}

    @router.get("/crm/connection")
    async def connection(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal_for(request, workspace_id)
        async with conn_factory() as conn:
            current = await latest_connection(conn, workspace_id=workspace_id)
            name = (
                None
                if current is None
                else await conn.scalar(
                    text("SELECT display_name FROM platform_user WHERE user_id = :id"),
                    {"id": current.connected_by_user_id},
                )
            )
        if current is None:
            return {"status": "none"}
        status: Literal["active", "expired", "disconnected"] = current.status  # type: ignore[assignment]
        return {
            "provider": current.provider,
            "status": status,
            "connectedAt": current.connected_at.isoformat(),
            "connectedBy": current.connected_by_user_id,
            # The connect card's footer says who connected it ("Connected by …").
            "connectedByName": name,
        }

    @router.get("/crm/proposals/{proposal_id}")
    async def proposal(
        proposal_id: UUID, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal_for(request, workspace_id)
        async with conn_factory() as conn:
            progress = await proposal_progress(
                conn, workspace_id=workspace_id, proposal_id=proposal_id
            )
        if progress is None:
            raise refused(404, "crm_proposal_not_found", "No such CRM proposal here.")
        return progress

    @router.get("/crm/integration")
    async def integration(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal = principal_for(request, workspace_id)
        async with conn_factory() as conn:
            return await integration_view(
                conn,
                workspace_id=workspace_id,
                can_manage=PERMISSION in principal.permissions,
            )

    @router.post("/crm/connect-request")
    async def connect_request(
        body: ConnectRequestBody, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission=PERMISSION)
        async with conn_factory() as conn:
            await lock_manager(conn, principal, PERMISSION)
            opened = await open_settings_connect_request(
                conn,
                workspace_id=workspace_id,
                requested_by_user_id=principal.user_id,
                mode=body.mode,
            )
        return {"requestId": str(opened.request_id)}

    @router.post("/crm/disconnect")
    async def disconnect_crm(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission=PERMISSION)
        async with conn_factory() as conn:
            await lock_manager(conn, principal, PERMISSION)
            current = await latest_connection(conn, workspace_id=workspace_id)
            if current is None or current.status == "disconnected":
                raise refused(409, "crm_not_connected", "No CRM is connected.")
            await disconnect(conn, connection_id=current.connection_id)
            await revoke_all_grants(
                conn,
                connection_id=current.connection_id,
                revoked_by_user_id=principal.user_id,
            )
            await close_disconnected_proposals(conn, artifacts, connection_id=current.connection_id)
        # Clue's grant at Composio goes too (R-15.3). The disconnect stands if this fails: the
        # connection is no longer used either way.
        gateway = getattr(request.app.state, "crm_gateway", None) or built
        if gateway is None:
            log.warning("crm.disconnect.composio_not_configured")
        else:
            try:
                await gateway.delete_account(current.composio_connected_account_id)
            except ComposioError as error:
                log.warning("crm.disconnect.composio_delete_failed", kind=error.kind)
        return {"outcome": "disconnected"}

    @router.post("/crm/permissions/{grant_id}/revoke")
    async def revoke_permission(
        grant_id: UUID, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id)
        async with conn_factory() as conn:
            current = await latest_connection(conn, workspace_id=workspace_id)
            row = (
                None
                if current is None
                else (
                    await conn.execute(
                        text(
                            "SELECT revoked_at FROM crm_write_grant WHERE grant_id = :id "
                            "AND workspace_id = :ws AND connection_id = :c FOR UPDATE"
                        ),
                        {"id": grant_id, "ws": workspace_id, "c": current.connection_id},
                    )
                ).first()
            )
            # A grant of an older connection never applies again: unknown, like another
            # workspace's.
            if row is None:
                raise refused(404, "crm_permission_not_found", "No such permission here.")
            if row.revoked_at is not None:
                return {"outcome": "already_revoked"}
            await revoke_grant(conn, grant_id=grant_id, revoked_by_user_id=principal.user_id)
        return {"outcome": "revoked"}

    @router.put("/crm/overwrites")
    async def overwrites(
        body: OverwritesBody, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission=PERMISSION)
        async with conn_factory() as conn:
            await lock_manager(conn, principal, PERMISSION)
            current = await latest_connection(conn, workspace_id=workspace_id)
            if current is None or current.status == "disconnected":
                raise refused(409, "crm_not_connected", "No CRM is connected.")
            await set_connection_overwrites(
                conn, connection_id=current.connection_id, mode=body.mode
            )
        return {"overwrites": body.mode}
