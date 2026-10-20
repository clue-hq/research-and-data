"""``/frontend/v1/crm/*`` — connecting the workspace's CRM from the chat's connect card.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§4.1; rulings R-3.1, R-3.10. The card (drawn from the ``connect_crm`` tool's result) calls
``connect-link`` for a fresh Composio link on each click — links live about ten minutes, so none is
stored for reuse. Composio sends the browser back to the frontend's callback page, which calls
``complete``: the connection is activated only when Composio reports it ACTIVE and it is exactly
the attempt this request recorded, and then every chat waiting on the connection is woken.

Connecting requires ``workspace.manage_settings`` (owners and admins); any member may read the
connection's status.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.crm.composio_gateway import (
    ComposioError,
    ComposioGateway,
    CrmProvider,
    build_composio_gateway,
    composio_user_id,
)
from clue_api.crm.connections import (
    activate_from_attempt,
    get_connect_request,
    latest_connection,
    start_attempt,
)
from clue_api.crm.wake import queue_crm_connected_turns
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


class ConnectLinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    provider: CrmProvider


class CompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: str
    connected_account_id: str


def auth_config_for(settings: Settings, provider: CrmProvider) -> str:
    """The Composio auth config for ``provider``; empty when that CRM is not offered."""
    return (
        settings.composio_hubspot_auth_config_id
        if provider == "hubspot"
        else settings.composio_salesforce_auth_config_id
    ).strip()


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
            )
            if activated is None:
                return {"outcome": "stale"}
            _, waiting = activated
            if artifacts is None:
                log.warning("crm.complete.no_artifact_store", waiting=len(waiting))
            else:
                await queue_crm_connected_turns(
                    conn, artifacts, requests=waiting, provider=provider
                )
        return {"outcome": "connected", "provider": provider}

    @router.get("/crm/connection")
    async def connection(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal_for(request, workspace_id)
        async with conn_factory() as conn:
            current = await latest_connection(conn, workspace_id=workspace_id)
        if current is None:
            return {"status": "none"}
        status: Literal["active", "expired", "disconnected"] = current.status  # type: ignore[assignment]
        return {
            "provider": current.provider,
            "status": status,
            "connectedAt": current.connected_at.isoformat(),
            "connectedBy": current.connected_by_user_id,
        }
