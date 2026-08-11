"""Invitation acceptance and self-serve owner provisioning transactions for B1."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_auth.errors import IdentityConflictError, InvitationUnavailableError
from clue_auth.models import AuthIdentity, PlatformUser, WorkspaceInvitation, WorkspaceMembership
from clue_auth.store import (
    activate_invited_membership,
    create_platform_user,
    create_workspace_membership,
    get_auth_identity,
    get_platform_user,
    get_workspace_membership,
    link_auth_identity,
    lock_invitation_by_digest,
    mark_invitation_accepted,
    update_platform_user_profile,
)
from clue_spine import Brand, Workspace, create_brand, create_workspace, get_brand, get_workspace


class ProvisionedIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user: PlatformUser
    auth_identity: AuthIdentity
    membership: WorkspaceMembership
    invitation: WorkspaceInvitation


class ProvisionedWorkspaceOwner(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace: Workspace
    user: PlatformUser
    auth_identity: AuthIdentity
    membership: WorkspaceMembership


def hash_invitation_token(raw_token: str) -> str:
    """Return the SHA-256 digest stored in Postgres; raw bearer tokens never enter a row."""
    if not raw_token:
        raise ValueError("invitation token must be non-empty")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def _resolve_or_create_user(
    conn: AsyncConnection,
    *,
    provider_key: str,
    provider_subject: str,
    display_name: str | None,
) -> tuple[PlatformUser, AuthIdentity]:
    identity = await get_auth_identity(
        conn, provider_key=provider_key, provider_subject=provider_subject
    )
    if identity is not None:
        if identity.status != "active":
            raise IdentityConflictError("external identity mapping is not active")
        user = await get_platform_user(conn, identity.user_id)
        if user is None or user.status != "active":
            raise IdentityConflictError("mapped platform user is not active")
        return user, identity
    user = await create_platform_user(conn, display_name=display_name)
    identity = await link_auth_identity(
        conn,
        user_id=user.user_id,
        provider_key=provider_key,
        provider_subject=provider_subject,
    )
    return user, identity


async def accept_workspace_invitation(
    conn: AsyncConnection,
    *,
    raw_token: str,
    verified_address: str,
    provider_key: str,
    provider_subject: str,
    display_name: str | None = None,
    now: datetime | None = None,
) -> ProvisionedIdentity:
    """Accept one invitation using a provider-verified delivery address.

    The row is locked before identity or membership writes, making the transaction single-use.
    Retrying an already-accepted token is idempotent only for the same active mapped user.
    """
    at = now or datetime.now(UTC)
    digest = hash_invitation_token(raw_token)
    invitation = await lock_invitation_by_digest(conn, digest)
    if invitation is None:
        raise InvitationUnavailableError("invitation does not exist")

    identity = await get_auth_identity(
        conn, provider_key=provider_key, provider_subject=provider_subject
    )
    if invitation.status == "accepted":
        if (
            identity is None
            or identity.status != "active"
            or invitation.accepted_by_user_id != identity.user_id
        ):
            raise InvitationUnavailableError("invitation was accepted by another identity")
        user = await get_platform_user(conn, identity.user_id)
        membership = await get_workspace_membership(
            conn, workspace_id=invitation.workspace_id, user_id=identity.user_id
        )
        if (
            user is None
            or user.status != "active"
            or membership is None
            or membership.status != "active"
        ):
            raise InvitationUnavailableError("accepted invitation no longer resolves to access")
        return ProvisionedIdentity(
            user=user,
            auth_identity=identity,
            membership=membership,
            invitation=invitation,
        )

    if invitation.status != "pending" or invitation.expires_at <= at:
        raise InvitationUnavailableError("invitation is expired, revoked, or unavailable")
    invited = invitation.invited_address.strip().casefold().encode("utf-8")
    verified = verified_address.strip().casefold().encode("utf-8")
    if not hmac.compare_digest(invited, verified):
        raise InvitationUnavailableError("verified address does not match invitation")

    user, identity = await _resolve_or_create_user(
        conn,
        provider_key=provider_key,
        provider_subject=provider_subject,
        display_name=display_name,
    )
    membership = await get_workspace_membership(
        conn, workspace_id=invitation.workspace_id, user_id=user.user_id
    )
    if membership is None:
        membership = await create_workspace_membership(
            conn,
            workspace_id=invitation.workspace_id,
            user_id=user.user_id,
            role_key=invitation.role_key,
            status="active",
            now=at,
        )
    elif membership.status == "invited":
        membership = await activate_invited_membership(
            conn,
            membership_id=membership.membership_id,
            role_key=invitation.role_key,
            now=at,
        )
    elif membership.status != "active":
        raise InvitationUnavailableError("invitation cannot override suspended or revoked access")

    invitation = await mark_invitation_accepted(
        conn, invitation_id=invitation.invitation_id, user_id=user.user_id, now=at
    )
    return ProvisionedIdentity(
        user=user,
        auth_identity=identity,
        membership=membership,
        invitation=invitation,
    )


async def provision_workspace_owner(
    conn: AsyncConnection,
    *,
    workspace_name: str,
    provider_key: str,
    provider_subject: str,
    display_name: str | None = None,
    workspace_id: str | None = None,
    now: datetime | None = None,
) -> ProvisionedWorkspaceOwner:
    """Create the Clue workspace and owner membership under one caller-owned transaction."""
    at = now or datetime.now(UTC)
    user, identity = await _resolve_or_create_user(
        conn,
        provider_key=provider_key,
        provider_subject=provider_subject,
        display_name=display_name,
    )
    workspace = await create_workspace(conn, name=workspace_name, workspace_id=workspace_id)
    membership = await create_workspace_membership(
        conn,
        workspace_id=workspace.workspace_id,
        user_id=user.user_id,
        role_key="owner",
        status="active",
        now=at,
    )
    return ProvisionedWorkspaceOwner(
        workspace=workspace,
        user=user,
        auth_identity=identity,
        membership=membership,
    )


class ProvisionedSelfServeWorkspace(BaseModel):
    """Result of the FI-4 D-2 one-shot onboarding provisioning; ``created`` is False on replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace: Workspace
    brand: Brand
    user: PlatformUser
    auth_identity: AuthIdentity
    membership: WorkspaceMembership
    company_website: str | None
    created: bool


def _required(value: str, *, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} must be non-empty")
    return cleaned


async def provision_self_serve_workspace(
    conn: AsyncConnection,
    *,
    provider_key: str,
    provider_subject: str,
    company_name: str,
    first_name: str | None = None,
    last_name: str | None = None,
    job_role: str | None = None,
    company_website: str | None = None,
    now: datetime | None = None,
) -> ProvisionedSelfServeWorkspace:
    """The FI-4 D-2 operation: one replay-safe transaction from Clerk subject to owned workspace.

    Links the external identity to a Clue user, creates the company workspace, creates its first
    brand, makes the user the workspace owner, and saves the submitted profile. Idempotent on the
    ``self_serve_provisioning`` record keyed by the auth identity: a replay (browser retry,
    double-click) returns the workspace and brand recorded there — never a second workspace. A
    per-subject advisory transaction lock serializes concurrent first calls so exactly one of
    them creates; the loser observes the record and takes the replay path.

    Profile fields carry PUT semantics on every call (a replay with corrected spelling updates
    the user's own profile); workspace/brand names are fixed at creation and never renamed here.
    """
    at = now or datetime.now(UTC)
    name = _required(company_name, label="company_name")
    website = company_website.strip() if company_website and company_website.strip() else None
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"self-serve-provision:{provider_key}:{provider_subject}"},
    )
    user, identity = await _resolve_or_create_user(
        conn,
        provider_key=provider_key,
        provider_subject=provider_subject,
        display_name=None,
    )
    user = await update_platform_user_profile(
        conn,
        user.user_id,
        first_name=first_name,
        last_name=last_name,
        job_role=job_role,
    )
    existing = (
        await conn.execute(
            text(
                "SELECT workspace_id, brand_id, company_website FROM self_serve_provisioning "
                "WHERE auth_identity_id = :auth_identity_id"
            ),
            {"auth_identity_id": identity.auth_identity_id},
        )
    ).mappings().first()
    if existing is not None:
        workspace = await get_workspace(conn, existing["workspace_id"])
        brand = (
            None
            if workspace is None
            else await get_brand(
                conn, workspace_id=workspace.workspace_id, brand_id=existing["brand_id"]
            )
        )
        membership = (
            None
            if workspace is None
            else await get_workspace_membership(
                conn, workspace_id=workspace.workspace_id, user_id=user.user_id
            )
        )
        if workspace is None or brand is None or membership is None:
            raise IdentityConflictError(
                "self-serve provisioning record is inconsistent with its workspace"
            )
        return ProvisionedSelfServeWorkspace(
            workspace=workspace,
            brand=brand,
            user=user,
            auth_identity=identity,
            membership=membership,
            company_website=existing["company_website"],
            created=False,
        )
    workspace = await create_workspace(conn, name=name)
    brand = await create_brand(conn, workspace_id=workspace.workspace_id, name=name)
    membership = await create_workspace_membership(
        conn,
        workspace_id=workspace.workspace_id,
        user_id=user.user_id,
        role_key="owner",
        status="active",
        now=at,
    )
    await conn.execute(
        text(
            "INSERT INTO self_serve_provisioning "
            "(auth_identity_id, workspace_id, brand_id, company_website) "
            "VALUES (:auth_identity_id, :workspace_id, :brand_id, :company_website)"
        ),
        {
            "auth_identity_id": identity.auth_identity_id,
            "workspace_id": workspace.workspace_id,
            "brand_id": brand.brand_id,
            "company_website": website,
        },
    )
    return ProvisionedSelfServeWorkspace(
        workspace=workspace,
        brand=brand,
        user=user,
        auth_identity=identity,
        membership=membership,
        company_website=website,
        created=True,
    )
