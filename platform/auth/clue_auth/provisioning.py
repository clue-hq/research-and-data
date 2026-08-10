"""Invitation acceptance and self-serve owner provisioning transactions for B1."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
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
)
from clue_spine import Workspace, create_workspace


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
