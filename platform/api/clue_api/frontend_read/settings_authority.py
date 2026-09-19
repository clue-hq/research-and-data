"""Shared Settings authority, rechecked under the workspace management transaction lock."""

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.auth_wiring import principal_from_request
from clue_auth.policy import Permission, role_has_permission
from clue_auth.principal import RequestPrincipal
from clue_auth.store import get_membership


def refused(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def principal_for(
    request: Request, workspace_id: str, *, permission: Permission | None = None
) -> RequestPrincipal:
    principal = principal_from_request(request)
    if principal is None or principal.workspace_id != workspace_id:
        raise refused(401, "UNAUTHORIZED", "Sign in to use Settings.")
    if permission and permission not in principal.permissions:
        raise refused(
            403, "PERMISSION_REQUIRED", "Workspace administration permission is required."
        )
    return principal


async def lock_manager(
    conn: AsyncConnection,
    principal: RequestPrincipal,
    permission: Permission = "workspace.manage_members",
) -> None:
    # Serialize management writes and recheck live authority inside the transaction.
    await conn.execute(
        text("SELECT workspace_id FROM workspace WHERE workspace_id = :ws FOR NO KEY UPDATE"),
        {"ws": principal.workspace_id},
    )
    actor = await get_membership(
        conn, workspace_id=principal.workspace_id, membership_id=principal.membership_id
    )
    if (
        actor is None
        or actor.status != "active"
        or not role_has_permission(actor.role_key, permission)
    ):
        raise refused(
            403, "PERMISSION_REQUIRED", "Workspace administration permission is required."
        )
