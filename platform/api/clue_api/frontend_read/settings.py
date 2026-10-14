"""Settings reads and writes over the authenticated frontend repository seam."""

from __future__ import annotations

import re
import secrets as random_secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.research_fields import register_research_field_routes
from clue_api.frontend_read.research_jobs import register_research_job_routes
from clue_api.frontend_read.settings_authority import lock_manager, principal_for, refused
from clue_auth.errors import LifecycleTransitionError, MembershipPermissionError
from clue_auth.principal import RequestPrincipal
from clue_auth.providers.clerk_api import ClerkApi, ClerkApiError
from clue_auth.provisioning import hash_invitation_token
from clue_auth.store import (
    change_workspace_member_role,
    create_workspace_invitation,
    get_membership,
    get_platform_user,
    lock_workspace_invitation,
    readmit_workspace_member,
    revoke_workspace_invitation,
    revoke_workspace_member,
    set_provider_invitation_id,
    update_platform_user_profile,
)
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_spine import rename_workspace


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(default="", max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class MemberRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "operator"]


class InvitationRequest(MemberRole):
    emails: list[str] = Field(min_length=1, max_length=50)


def split_full_name(value: str) -> tuple[str | None, str | None]:
    first, _, last = value.strip().partition(" ")
    return first or None, last.strip() or None


async def read_profile(conn: AsyncConnection, user_id: str) -> dict[str, Any]:
    user = await get_platform_user(conn, user_id)
    if user is None or user.status != "active":
        raise refused(404, "PROFILE_NOT_FOUND", "Your profile could not be found.")
    return {
        "user_id": user.user_id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": " ".join(part for part in (user.first_name, user.last_name) if part),
        "display_name": user.display_name,
        "email": user.email,
    }


def primary_logo_url(kit: Any) -> str | None:
    if not isinstance(kit, dict):
        return None
    logos = kit.get("assets", {}).get("logos", {}) if isinstance(kit.get("assets"), dict) else {}
    if not isinstance(logos, dict):
        return None
    for key in sorted(logos, key=lambda item: ("primary" not in item.lower(), item)):
        logo = logos[key]
        if not isinstance(logo, dict):
            continue
        for variant in logo.get("variants", []) or []:
            if not isinstance(variant, dict):
                continue
            asset_id = variant.get("asset_id")
            if isinstance(asset_id, str) and asset_id:
                return f"/api/clue/design/assets/{quote(asset_id, safe='')}/bytes"
    return None


async def read_workspace(conn: AsyncConnection, workspace_id: str) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT w.workspace_id, w.name, p.company_website, k.brand_kit_json "
                    "FROM workspace w LEFT JOIN self_serve_provisioning p USING (workspace_id) "
                    "LEFT JOIN LATERAL (SELECT brand_kit_json FROM design_brand_kit "
                    "WHERE workspace_id = w.workspace_id AND brand_id = p.brand_id "
                    "AND approval_status = 'approved' "
                    "ORDER BY updated_at DESC, version DESC, brand_kit_id "
                    "LIMIT 1) k ON true WHERE w.workspace_id = :ws"
                ),
                {"ws": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise refused(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    return {
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "website": row["company_website"],
        "logo_url": primary_logo_url(row["brand_kit_json"]),
    }


async def read_members(conn: AsyncConnection, principal: RequestPrincipal) -> list[dict[str, Any]]:
    members = (
        (
            await conn.execute(
                text(
                    "SELECT m.membership_id, m.user_id, m.role_key, m.status, m.activated_at, "
                    "u.display_name, u.first_name, u.last_name, u.email "
                    "FROM workspace_membership m "
                    "JOIN platform_user u USING (user_id) WHERE m.workspace_id = :ws "
                    "ORDER BY m.created_at, m.membership_id"
                ),
                {"ws": principal.workspace_id},
            )
        )
        .mappings()
        .all()
    )
    rows = [
        {
            "kind": "member",
            "id": row["membership_id"],
            "name": row["display_name"]
            or " ".join(part for part in (row["first_name"], row["last_name"]) if part)
            or None,
            "email": row["email"],
            "role_key": row["role_key"],
            "state": {"revoked": "removed", "invited": "invited", "suspended": "suspended"}.get(
                row["status"], "active"
            ),
            "joined_on": row["activated_at"].date().isoformat() if row["activated_at"] else None,
            "is_self": row["user_id"] == principal.user_id,
        }
        for row in members
    ]
    invitations = (
        (
            await conn.execute(
                text(
                    "SELECT invitation_id, invited_address, role_key FROM workspace_invitation "
                    "WHERE workspace_id = :ws AND status = 'pending' AND expires_at > now() "
                    "ORDER BY created_at, invitation_id"
                ),
                {"ws": principal.workspace_id},
            )
        )
        .mappings()
        .all()
    )
    rows.extend(
        {
            "kind": "invitation",
            "id": row["invitation_id"],
            "name": None,
            "email": row["invited_address"],
            "role_key": row["role_key"],
            "state": "invited",
            "joined_on": None,
            "is_self": False,
        }
        for row in invitations
    )
    return rows


def register_settings_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    settings: Settings,
    secrets: Secrets | None = None,
    clerk_api: ClerkApi | None = None,
) -> None:
    secret = secrets.auth_clerk_secret_key if secrets else None
    clerk = clerk_api or (ClerkApi(secret.get_secret_value()) if secret else None)

    register_research_field_routes(router, conn_factory=conn_factory)
    register_research_job_routes(router, conn_factory=conn_factory)

    @router.get("/settings/profile")
    async def profile(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal = principal_for(request, workspace_id)
        async with conn_factory() as conn:
            return await read_profile(conn, principal.user_id)

    @router.patch("/settings/profile")
    async def patch_profile(
        request: Request,
        workspace_id: WorkspaceDep,
        body: ProfilePatch,
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id)
        async with conn_factory() as conn:
            await conn.execute(
                text("SELECT user_id FROM platform_user WHERE user_id = :id FOR UPDATE"),
                {"id": principal.user_id},
            )
            current = await read_profile(conn, principal.user_id)
            first, last = (
                split_full_name(body.full_name)
                if "full_name" in body.model_fields_set
                else (None, None)
            )
            display = (
                body.display_name
                if "display_name" in body.model_fields_set
                else current["display_name"]
            )
            clear: set[Literal["first_name", "last_name", "display_name"]] = set()
            if "full_name" in body.model_fields_set:
                if first is None:
                    clear.add("first_name")
                if last is None:
                    clear.add("last_name")
            if not display or not display.strip():
                clear.add("display_name")
            await update_platform_user_profile(
                conn,
                principal.user_id,
                first_name=first,
                last_name=last,
                job_role=None,
                display_name=display,
                clear_fields=frozenset(clear),
            )
            return await read_profile(conn, principal.user_id)

    @router.get("/settings/workspace")
    async def workspace(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal_for(request, workspace_id)
        async with conn_factory() as conn:
            return await read_workspace(conn, workspace_id)

    @router.patch("/settings/workspace")
    async def patch_workspace(
        request: Request,
        workspace_id: WorkspaceDep,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission="workspace.manage_settings")
        if "website" in body or "logo_url" in body:
            raise refused(400, "FIELD_READ_ONLY", "Website and logo are read-only.")
        if set(body) != {"name"} or not isinstance(body["name"], str):
            raise refused(422, "VALIDATION_ERROR", "Provide an organization name.")
        async with conn_factory() as conn:
            await lock_manager(conn, principal, "workspace.manage_settings")
            try:
                await rename_workspace(conn, workspace_id, body["name"])
            except ValueError:
                raise refused(
                    422, "VALIDATION_ERROR", "Organization name must contain 1 to 200 characters."
                ) from None
            return await read_workspace(conn, workspace_id)

    @router.get("/settings/members")
    async def members(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal = principal_for(request, workspace_id)
        async with conn_factory() as conn:
            return {
                "rows": await read_members(conn, principal),
                "invitations_configured": clerk is not None,
            }

    async def member_write(
        request: Request,
        workspace_id: str,
        membership_id: str,
        action: str,
        role: str = "operator",
    ) -> dict[str, bool]:
        principal = principal_for(request, workspace_id, permission="workspace.manage_members")
        async with conn_factory() as conn:
            await lock_manager(conn, principal)
            target = await get_membership(
                conn, workspace_id=workspace_id, membership_id=membership_id
            )
            if target is None:
                raise refused(404, "MEMBER_NOT_FOUND", "Member not found.")
            if target.role_key == "owner":
                raise refused(
                    409,
                    "OWNER_PROTECTED",
                    "The workspace owner's role and access cannot be changed.",
                )
            if action == "remove" and target.user_id == principal.user_id:
                raise refused(
                    409, "INVALID_TRANSITION", "You cannot remove yourself from this screen."
                )
            try:
                if action == "remove":
                    await revoke_workspace_member(
                        conn,
                        acting_membership_id=principal.membership_id,
                        workspace_id=workspace_id,
                        membership_id=membership_id,
                    )
                elif action == "readmit":
                    await readmit_workspace_member(
                        conn,
                        acting_membership_id=principal.membership_id,
                        workspace_id=workspace_id,
                        membership_id=membership_id,
                        role_key=role,
                    )
                else:
                    await change_workspace_member_role(
                        conn,
                        acting_membership_id=principal.membership_id,
                        workspace_id=workspace_id,
                        membership_id=membership_id,
                        role_key=role,
                    )
            except MembershipPermissionError:
                raise refused(
                    403, "PERMISSION_REQUIRED", "This role change is not permitted."
                ) from None
            except LifecycleTransitionError:
                raise refused(
                    409, "INVALID_TRANSITION", "The member's state changed. Refresh and try again."
                ) from None
        return {"ok": True}

    @router.patch("/settings/members/{membership_id}")
    async def change_role(
        request: Request, workspace_id: WorkspaceDep, membership_id: str, body: MemberRole
    ) -> dict[str, bool]:
        return await member_write(request, workspace_id, membership_id, "role", body.role)

    @router.delete("/settings/members/{membership_id}")
    async def remove_member(
        request: Request, workspace_id: WorkspaceDep, membership_id: str
    ) -> dict[str, bool]:
        return await member_write(request, workspace_id, membership_id, "remove")

    @router.post("/settings/members/{membership_id}/readmit")
    async def readmit(
        request: Request, workspace_id: WorkspaceDep, membership_id: str, body: MemberRole
    ) -> dict[str, bool]:
        return await member_write(request, workspace_id, membership_id, "readmit", body.role)

    @router.post("/settings/members/invitations")
    async def invite(
        request: Request, workspace_id: WorkspaceDep, body: InvitationRequest
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission="workspace.manage_members")
        if clerk is None:
            raise refused(503, "INVITATIONS_UNCONFIGURED", "Invitation delivery is not configured.")
        outcomes = []
        for email in dict.fromkeys(address.strip().casefold() for address in body.emails):
            outcome = {"email": email, "outcome": "invalid"}
            if len(email) > 320 or not re.fullmatch(r"[^\s@,]+@[^\s@,]+\.[^\s@,]+", email):
                outcomes.append(outcome)
                continue
            token = random_secrets.token_urlsafe(32)
            async with conn_factory() as conn:
                await lock_manager(conn, principal)
                exists = await conn.scalar(
                    text(
                        "SELECT 1 FROM workspace_membership m JOIN platform_user u USING (user_id) "
                        "WHERE m.workspace_id = :ws AND lower(u.email) = :email LIMIT 1"
                    ),
                    {"ws": workspace_id, "email": email},
                )
                pending = (
                    (
                        await conn.execute(
                            text(
                                "SELECT invitation_id, provider_invitation_id "
                                "FROM workspace_invitation "
                                "WHERE workspace_id = :ws "
                                "AND lower(btrim(invited_address)) = :email "
                                "AND status = 'pending' AND expires_at > now() "
                                "ORDER BY created_at LIMIT 1 FOR UPDATE"
                            ),
                            {"ws": workspace_id, "email": email},
                        )
                    )
                    .mappings()
                    .first()
                )
                if exists or pending is not None:
                    outcome["outcome"] = "already_member" if exists else "already_invited"
                    outcomes.append(outcome)
                    continue
                invitation = await create_workspace_invitation(
                    conn,
                    workspace_id=workspace_id,
                    invited_address=email,
                    role_key=body.role,
                    token_digest=hash_invitation_token(token),
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                    invited_by_membership_id=principal.membership_id,
                )
                invitation_id = invitation.invitation_id
            # Commit the authoritative row before asking an external carrier to send mail.
            try:
                provider_id = await clerk.create_invitation(
                    email=email,
                    invitation_id=invitation_id,
                    redirect_url=(
                        f"{settings.app_origin.rstrip('/')}/invite/accept?"
                        f"{urlencode({'token': token})}"
                    ),
                )
            except ClerkApiError as error:
                outcome["outcome"] = {
                    "existing_account": "created_no_email",
                    "rate_limited": "rate_limited",
                }.get(error.code, "delivery_failed")
            else:
                async with conn_factory() as conn:
                    await set_provider_invitation_id(
                        conn, invitation_id=invitation_id, provider_invitation_id=provider_id
                    )
                outcome["outcome"] = "sent"
            outcomes.append(outcome)
        return {"outcomes": outcomes}

    @router.delete("/settings/members/invitations/{invitation_id}")
    async def revoke_invitation(
        request: Request, workspace_id: WorkspaceDep, invitation_id: str
    ) -> dict[str, bool]:
        principal = principal_for(request, workspace_id, permission="workspace.manage_members")
        async with conn_factory() as conn:
            await lock_manager(conn, principal)
            invitation = await lock_workspace_invitation(
                conn, workspace_id=workspace_id, invitation_id=invitation_id
            )
            if invitation is None:
                raise refused(404, "MEMBER_NOT_FOUND", "Invitation not found.")
            try:
                await revoke_workspace_invitation(conn, invitation_id)
            except LifecycleTransitionError:
                raise refused(
                    409, "INVALID_TRANSITION", "This invitation is no longer pending."
                ) from None
        if clerk is not None and invitation.provider_invitation_id:
            try:
                await clerk.revoke_invitation(invitation.provider_invitation_id)
            except ClerkApiError:
                raise refused(
                    502,
                    "INVITATION_DELIVERY_REVOKE_FAILED",
                    "Workspace invitation revoked; the email service could not cancel its link.",
                ) from None
        return {"ok": True}
