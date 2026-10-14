"""Invitation acceptance and self-serve owner provisioning transactions for B1."""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_auth.errors import (
    IdentityConflictError,
    InvitationAddressMismatch,
    InvitationUnavailableError,
    ProvisioningValidationError,
)
from clue_auth.models import AuthIdentity, PlatformUser, WorkspaceInvitation, WorkspaceMembership
from clue_auth.store import (
    activate_invited_membership,
    create_platform_user,
    create_workspace_membership,
    get_auth_identity,
    get_platform_user,
    get_workspace_membership,
    link_auth_identity,
    list_user_memberships,
    lock_invitation_by_digest,
    lock_workspace_invitation,
    mark_invitation_accepted,
    update_platform_user_email,
    update_platform_user_profile,
)
from clue_core.normalize import canonical_workspace_name
from clue_spine import (
    DEFAULT_PAGES_SYSTEM_SUFFIX,
    Brand,
    Workspace,
    create_brand,
    create_workspace,
    get_brand,
    get_workspace,
)


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


async def _lock_accepting_identity(
    conn: AsyncConnection, provider_key: str, provider_subject: str
) -> None:
    # Lock identity before invitation rows in both entrypoints to avoid lock-order cycles.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": f"{provider_key}:{provider_subject}"},
    )


async def accept_workspace_invitation(
    conn: AsyncConnection,
    *,
    raw_token: str,
    verified_address: str,
    provider_key: str,
    provider_subject: str,
    display_name: str | None = None,
    now: datetime | None = None,
    initial_first_name: str | None = None,
    initial_last_name: str | None = None,
) -> ProvisionedIdentity:
    """Accept one invitation using a provider-verified delivery address.

    The row is locked before identity or membership writes, making the transaction single-use.
    Retrying an already-accepted token is idempotent only for the same active mapped user.
    """
    at = now or datetime.now(UTC)
    await _lock_accepting_identity(conn, provider_key, provider_subject)
    digest = hash_invitation_token(raw_token)
    invitation = await lock_invitation_by_digest(conn, digest)
    if invitation is None:
        raise InvitationUnavailableError("invitation does not exist")

    return await _accept_locked_invitation(
        conn,
        invitation=invitation,
        verified_address=verified_address,
        provider_key=provider_key,
        provider_subject=provider_subject,
        display_name=display_name,
        at=at,
        initial_first_name=initial_first_name,
        initial_last_name=initial_last_name,
    )


async def accept_pending_workspace_invitations(
    conn: AsyncConnection,
    *,
    verified_address: str,
    provider_key: str,
    provider_subject: str,
    now: datetime | None = None,
    initial_first_name: str | None = None,
    initial_last_name: str | None = None,
) -> tuple[ProvisionedIdentity, ...]:
    """Accept email-addressed invitations without reconstructing their bearer tokens."""
    at = now or datetime.now(UTC)
    await _lock_accepting_identity(conn, provider_key, provider_subject)
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT workspace_id, invitation_id FROM workspace_invitation "
                    "WHERE lower(btrim(invited_address)) = :address AND status = 'pending' "
                    "AND expires_at > :now ORDER BY created_at, invitation_id"
                ),
                {"address": verified_address.strip().casefold(), "now": at},
            )
        )
        .mappings()
        .all()
    )
    accepted = []
    for row in rows:
        # A stale/removed membership must never regain access through a pending invite.
        # A refusal in one workspace must not prevent joining unrelated workspaces.
        try:
            async with conn.begin_nested():
                invitation = await lock_workspace_invitation(
                    conn, workspace_id=row["workspace_id"], invitation_id=row["invitation_id"]
                )
                if invitation is not None:
                    accepted.append(
                        await _accept_locked_invitation(
                            conn,
                            invitation=invitation,
                            verified_address=verified_address,
                            provider_key=provider_key,
                            provider_subject=provider_subject,
                            display_name=None,
                            at=at,
                            initial_first_name=initial_first_name,
                            initial_last_name=initial_last_name,
                        )
                    )
        except InvitationUnavailableError:
            continue
    return tuple(accepted)


async def _accept_locked_invitation(
    conn: AsyncConnection,
    *,
    invitation: WorkspaceInvitation,
    verified_address: str,
    provider_key: str,
    provider_subject: str,
    display_name: str | None,
    at: datetime,
    initial_first_name: str | None,
    initial_last_name: str | None,
) -> ProvisionedIdentity:
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
        raise InvitationAddressMismatch("verified address does not match invitation")

    created_user = identity is None
    user, identity = await _resolve_or_create_user(
        conn,
        provider_key=provider_key,
        provider_subject=provider_subject,
        display_name=display_name,
    )
    if created_user and (initial_first_name or initial_last_name):
        # Seed provider signup names only at identity creation, under the identity lock.
        user = await update_platform_user_profile(
            conn,
            user.user_id,
            first_name=initial_first_name,
            last_name=initial_last_name,
            display_name=display_name,
            job_role=None,
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
    user = await update_platform_user_email(conn, user.user_id, verified_address)
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
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
) -> ProvisionedWorkspaceOwner:
    """Create the Clue workspace and owner membership under one caller-owned transaction.

    ``pages_system_suffix`` is handed to :func:`clue_spine.create_workspace`, which allocates the
    workspace's system hostname in the same transaction. Composition roots pass
    ``settings.pages_system_suffix``; the default is the production suffix.
    """
    at = now or datetime.now(UTC)
    user, identity = await _resolve_or_create_user(
        conn,
        provider_key=provider_key,
        provider_subject=provider_subject,
        display_name=display_name,
    )
    workspace = await create_workspace(
        conn,
        name=workspace_name,
        workspace_id=workspace_id,
        pages_system_suffix=pages_system_suffix,
    )
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


async def provision_self_serve_workspace(
    conn: AsyncConnection,
    *,
    provider_key: str,
    provider_subject: str,
    company_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    job_role: str | None = None,
    company_website: str | None = None,
    now: datetime | None = None,
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
) -> ProvisionedSelfServeWorkspace:
    """The FI-4 D-2 operation: one replay-safe transaction from Clerk subject to owned workspace.

    Links the external identity to a Clue user, creates the company workspace (with its system
    hostname under ``pages_system_suffix`` — composition roots pass
    ``settings.pages_system_suffix``), creates its first brand, makes the user the workspace
    owner, and saves the submitted profile. Idempotent on
    the ``self_serve_provisioning`` record keyed by the durable ``user_id`` (UNIQUE): a replay
    (browser retry, double-click, or a second linked identity of the same human) returns the
    workspace and brand recorded there — never a second workspace. A per-subject advisory
    transaction lock serializes concurrent first calls; a loser that races past it under a
    snapshot isolation level is caught at the record INSERT, rolls back its own creations to a
    savepoint, and returns the winner's workspace as a normal replay.

    Every supplied field carries uniform PATCH semantics: a provided value is written (a replay
    with corrected spelling updates the profile; a corrected ``company_website`` sticks — the
    slice-2 recon composition reads it), and ``None`` preserves the stored value. The one
    exception is ``company_name``: workspace/brand names are fixed at creation and never
    renamed here — the HTTP layer surfaces a divergent replayed name via
    ``company_name_ignored`` rather than pretending it was accepted.

    The name itself is a typed company name when one was submitted, else the shared
    ``canonical_workspace_name`` rule over ``company_website`` — a workspace is always named
    something a human recognizes, and never its id. A submission carrying neither is refused
    (``COMPANY_NAME_REQUIRED``) rather than provisioned nameless; the check runs before the
    replay read, so a replay must submit the same minimum as a first call.

    Only a user who currently holds an ACTIVE membership (and has no provisioning record) is
    refused — self-serve provisioning is first-time setup, never a second-workspace factory.
    Invited/suspended/revoked memberships do not block: those are per-workspace states about
    someone else's workspace and must not prevent a first self-serve signup; the frontend
    separately routes users with inactive memberships away from onboarding via the session
    view's ``has_inactive_memberships``.
    """
    at = now or datetime.now(UTC)
    typed = company_name.strip() if company_name and company_name.strip() else None
    name = typed or canonical_workspace_name(company_website)
    if name is None:
        raise ProvisioningValidationError(
            "COMPANY_NAME_REQUIRED",
            "a company name or a website with a nameable domain is required",
        )
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
    replay = await _replay_self_serve_record(
        conn, user=user, identity=identity, company_website=website
    )
    if replay is not None:
        return replay
    memberships = await list_user_memberships(conn, user.user_id)
    if any(membership.status == "active" for membership in memberships):
        raise IdentityConflictError(
            "user already holds an active workspace membership; "
            "self-serve provisioning only performs first-time setup"
        )
    savepoint = await conn.begin_nested()
    workspace = await create_workspace(conn, name=name, pages_system_suffix=pages_system_suffix)
    brand = await create_brand(conn, workspace_id=workspace.workspace_id, name=name)
    membership = await create_workspace_membership(
        conn,
        workspace_id=workspace.workspace_id,
        user_id=user.user_id,
        role_key="owner",
        status="active",
        now=at,
    )
    inserted = await conn.execute(
        text(
            "INSERT INTO self_serve_provisioning "
            "(auth_identity_id, user_id, workspace_id, brand_id, company_website) "
            "VALUES (:auth_identity_id, :user_id, :workspace_id, :brand_id, :company_website) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "auth_identity_id": identity.auth_identity_id,
            "user_id": user.user_id,
            "workspace_id": workspace.workspace_id,
            "brand_id": brand.brand_id,
            "company_website": website,
        },
    )
    if inserted.rowcount == 0:
        # A concurrent transaction won under an isolation level where the advisory lock's
        # post-lock read could not see its row. Roll back OUR creations to the savepoint and
        # return the winner's workspace as an ordinary replay (never a duplicate, never a
        # spurious conflict for a transient race).
        await savepoint.rollback()
        replay = await _replay_self_serve_record(
            conn, user=user, identity=identity, company_website=website
        )
        if replay is None:
            raise IdentityConflictError("concurrent provisioning detected; retry the request")
        return replay
    await savepoint.commit()
    return ProvisionedSelfServeWorkspace(
        workspace=workspace,
        brand=brand,
        user=user,
        auth_identity=identity,
        membership=membership,
        company_website=website,
        created=True,
    )


_HTTP_WEBSITE = re.compile(r"https?://[^\s/?#]+\.[^\s/?#]+(?:[/?#]\S*)?", re.IGNORECASE)


class ProvisionedAdditionalWorkspace(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace: Workspace
    brand: Brand
    user: PlatformUser
    membership: WorkspaceMembership
    company_website: str


async def provision_additional_workspace(
    conn: AsyncConnection,
    *,
    email: str,
    company_website: str,
    company_name: str | None = None,
    now: datetime | None = None,
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
) -> ProvisionedAdditionalWorkspace:
    """Give an EXISTING user one more workspace they own — an operator action, not signup.

    Self-serve provisioning is first-time setup only (it refuses a user with an active
    membership, and ``self_serve_provisioning`` is one row per user), so a second workspace for
    someone who already has one is created here instead: the workspace, its single brand
    (``POST /onboarding`` starts a run only for a workspace with exactly one brand), and an
    active owner membership. No signup record is written and the user's other workspaces are
    untouched. Onboarding then starts from the product's setting-up screen, so brand-kit
    ingestion runs on the platform API exactly as it does for a signup.

    Refuses, before any write: a website that is not an http(s) URL with a dotted host; an email
    that matches no user or more than one; a user who is not active; and a user who already owns
    an active workspace with the same name (a re-run of the same operator command). The user row
    is locked first so two concurrent runs for one user cannot both pass the duplicate check.
    """
    at = now or datetime.now(UTC)
    website = company_website.strip()
    if not _HTTP_WEBSITE.fullmatch(website):
        raise ProvisioningValidationError(
            "COMPANY_WEBSITE_REQUIRED", "an http(s) company website with a domain is required"
        )
    typed = company_name.strip() if company_name and company_name.strip() else None
    name = typed or canonical_workspace_name(website)
    if name is None:
        raise ProvisioningValidationError(
            "COMPANY_NAME_REQUIRED",
            "a company name or a website with a nameable domain is required",
        )
    address = email.strip().casefold()
    user_ids = (
        (
            await conn.execute(
                text(
                    "SELECT user_id FROM platform_user WHERE lower(email) = :email "
                    "ORDER BY user_id FOR UPDATE"
                ),
                {"email": address},
            )
        )
        .scalars()
        .all()
    )
    if not user_ids:
        raise IdentityConflictError(f"no Clue user has the email {address}")
    if len(user_ids) > 1:
        raise IdentityConflictError(f"more than one Clue user has the email {address}")
    user = await get_platform_user(conn, user_ids[0])
    if user is None or user.status != "active":
        raise IdentityConflictError(f"the Clue user {address} is not active")
    duplicate = (
        await conn.execute(
            text(
                "SELECT w.workspace_id FROM workspace_membership m "
                "JOIN workspace w USING (workspace_id) "
                "WHERE m.user_id = :user_id AND m.role_key = 'owner' AND m.status = 'active' "
                "AND lower(w.name) = lower(:name) LIMIT 1"
            ),
            {"user_id": user.user_id, "name": name},
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise IdentityConflictError(
            f"{address} already owns a workspace named {name!r} ({duplicate})"
        )
    workspace = await create_workspace(conn, name=name, pages_system_suffix=pages_system_suffix)
    brand = await create_brand(conn, workspace_id=workspace.workspace_id, name=name)
    membership = await create_workspace_membership(
        conn,
        workspace_id=workspace.workspace_id,
        user_id=user.user_id,
        role_key="owner",
        status="active",
        now=at,
    )
    return ProvisionedAdditionalWorkspace(
        workspace=workspace,
        brand=brand,
        user=user,
        membership=membership,
        company_website=website,
    )


async def _replay_self_serve_record(
    conn: AsyncConnection,
    *,
    user: PlatformUser,
    identity: AuthIdentity,
    company_website: str | None,
) -> ProvisionedSelfServeWorkspace | None:
    existing = (
        (
            await conn.execute(
                text(
                    "SELECT workspace_id, brand_id, company_website "
                    "FROM self_serve_provisioning WHERE user_id = :user_id"
                ),
                {"user_id": user.user_id},
            )
        )
        .mappings()
        .first()
    )
    if existing is None:
        return None
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
    if membership.status != "active":
        raise IdentityConflictError("the provisioned workspace membership is no longer active")
    stored_website = existing["company_website"]
    if company_website is not None and company_website != stored_website:
        await conn.execute(
            text(
                "UPDATE self_serve_provisioning SET company_website = :company_website "
                "WHERE user_id = :user_id"
            ),
            {"company_website": company_website, "user_id": user.user_id},
        )
        stored_website = company_website
    return ProvisionedSelfServeWorkspace(
        workspace=workspace,
        brand=brand,
        user=user,
        auth_identity=identity,
        membership=membership,
        company_website=stored_website,
        created=False,
    )
