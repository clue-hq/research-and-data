"""Plain async CRUD and lifecycle operations for Lane B B1.

The module follows the object-spine's raw-SQL style: frozen row models plus functions over an
``AsyncConnection``. Callers own the transaction. Provider-specific validation belongs to B2's
``Authenticator`` adapter; this store only receives an already-validated opaque provider subject
and maps it to Clue-owned ids.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_auth.errors import LifecycleTransitionError, MembershipPermissionError
from clue_auth.models import (
    AuthIdentity,
    IdentityBundle,
    IdentityErasureResult,
    PlatformUser,
    SelfServeProvisioningRecord,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from clue_auth.policy import require_role_key, role_can_assign, role_has_permission


def new_user_id() -> str:
    return "usr_" + uuid4().hex


def new_auth_identity_id() -> str:
    return "aid_" + uuid4().hex


def new_membership_id() -> str:
    return "wsm_" + uuid4().hex


def new_invitation_id() -> str:
    return "wsi_" + uuid4().hex


_USER_COLUMNS = (
    "user_id, display_name, first_name, last_name, job_role, email, "
    "status, created_at, suspended_at, disabled_at"
)
_IDENTITY_COLUMNS = (
    "auth_identity_id, user_id, provider_key, provider_subject, status, linked_at, revoked_at"
)
_MEMBERSHIP_COLUMNS = (
    "membership_id, workspace_id, user_id, role_key, status, created_at, activated_at, revoked_at"
)
_INVITATION_COLUMNS = (
    "invitation_id, provider_invitation_id, workspace_id, invited_address, "
    "role_key, status, expires_at, "
    "invited_by_membership_id, accepted_by_user_id, created_at, accepted_at, revoked_at"
)


def _clean(value: str, *, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} must be non-empty")
    return cleaned


def _model[ModelT: BaseModel](model: type[ModelT], row: Any) -> ModelT:
    return model(**dict(row))


async def create_platform_user(
    conn: AsyncConnection,
    *,
    display_name: str | None = None,
    user_id: str | None = None,
) -> PlatformUser:
    result = await conn.execute(
        text(
            f"INSERT INTO platform_user (user_id, display_name) "
            f"VALUES (:user_id, :display_name) RETURNING {_USER_COLUMNS}"
        ),
        {
            "user_id": user_id or new_user_id(),
            "display_name": display_name.strip() if display_name and display_name.strip() else None,
        },
    )
    return _model(PlatformUser, result.mappings().one())


async def get_platform_user(conn: AsyncConnection, user_id: str) -> PlatformUser | None:
    result = await conn.execute(
        text(f"SELECT {_USER_COLUMNS} FROM platform_user WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    row = result.mappings().first()
    return _model(PlatformUser, row) if row is not None else None


async def update_platform_user_email(
    conn: AsyncConnection, user_id: str, verified_email: str
) -> PlatformUser:
    """Persist a provider-verified address as profile data, never as an identity lookup."""
    result = await conn.execute(
        text(
            "UPDATE platform_user SET email = :email WHERE user_id = :user_id "
            f"AND status = 'active' RETURNING {_USER_COLUMNS}"
        ),
        {"user_id": user_id, "email": _clean(verified_email, label="email").casefold()},
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError("active platform user not found")
    return _model(PlatformUser, row)


async def lock_workspace_invitation(
    conn: AsyncConnection, *, workspace_id: str, invitation_id: str
) -> WorkspaceInvitation | None:
    result = await conn.execute(
        text(
            f"SELECT {_INVITATION_COLUMNS} FROM workspace_invitation "
            "WHERE workspace_id = :ws AND invitation_id = :id FOR UPDATE"
        ),
        {"ws": workspace_id, "id": invitation_id},
    )
    row = result.mappings().first()
    return _model(WorkspaceInvitation, row) if row is not None else None


async def set_provider_invitation_id(
    conn: AsyncConnection, *, invitation_id: str, provider_invitation_id: str
) -> None:
    await conn.execute(
        text(
            "UPDATE workspace_invitation SET provider_invitation_id = :provider "
            "WHERE invitation_id = :id AND status = 'pending'"
        ),
        {"provider": provider_invitation_id, "id": invitation_id},
    )


async def update_platform_user_display_name(
    conn: AsyncConnection, user_id: str, display_name: str | None
) -> PlatformUser:
    result = await conn.execute(
        text(
            f"UPDATE platform_user SET display_name = :display_name "
            f"WHERE user_id = :user_id RETURNING {_USER_COLUMNS}"
        ),
        {
            "user_id": user_id,
            "display_name": display_name.strip() if display_name and display_name.strip() else None,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError(f"platform_user {user_id!r} does not exist")
    return _model(PlatformUser, row)


def _optional(value: str | None) -> str | None:
    """Normalize an optional profile value: whitespace-only and empty become NULL."""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


async def update_platform_user_profile(
    conn: AsyncConnection,
    user_id: str,
    *,
    first_name: str | None,
    last_name: str | None,
    job_role: str | None,
    display_name: str | None = None,
    clear_fields: frozenset[Literal["first_name", "last_name", "display_name"]] = frozenset(),
) -> PlatformUser:
    """Update profile fields, preserving the onboarding PATCH contract by default.

    ``None`` (or whitespace-only) means "not supplied — preserve the stored value" for every
    field. Settings can explicitly clear a supplied field through ``clear_fields``; callers
    that omit it keep the onboarding semantics.
    ``display_name`` handling: an explicit value wins; otherwise the column is recomposed from
    the effective "first last" only when it is empty OR still equals the previous automatic
    composition — a display name a user chose by hand is never overwritten, while an
    auto-composed one follows name corrections.
    """

    result = await conn.execute(
        text(
            f"UPDATE platform_user SET "
            f"first_name = CASE WHEN :clear_first THEN NULL "
            f"ELSE COALESCE(CAST(:first_name AS text), first_name) END, "
            f"last_name = CASE WHEN :clear_last THEN NULL "
            f"ELSE COALESCE(CAST(:last_name AS text), last_name) END, "
            f"job_role = COALESCE(CAST(:job_role AS text), job_role), "
            f"display_name = CASE "
            f"  WHEN :clear_display THEN NULL "
            f"  WHEN CAST(:explicit_display AS text) IS NOT NULL "
            f"    THEN CAST(:explicit_display AS text) "
            f"  WHEN display_name IS NULL OR display_name = NULLIF(btrim("
            f"    COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), '') "
            f"  THEN NULLIF(btrim(CASE WHEN :clear_first THEN '' ELSE "
            f"    COALESCE(CAST(:first_name AS text), first_name, '') END || ' ' || "
            f"    CASE WHEN :clear_last THEN '' ELSE "
            f"    COALESCE(CAST(:last_name AS text), last_name, '') END), '') "
            f"  ELSE display_name END "
            f"WHERE user_id = :user_id RETURNING {_USER_COLUMNS}"
        ),
        {
            "user_id": user_id,
            "first_name": _optional(first_name),
            "last_name": _optional(last_name),
            "job_role": _optional(job_role),
            "explicit_display": _optional(display_name),
            "clear_first": "first_name" in clear_fields,
            "clear_last": "last_name" in clear_fields,
            "clear_display": "display_name" in clear_fields,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError(f"platform_user {user_id!r} does not exist")
    return _model(PlatformUser, row)


async def link_auth_identity(
    conn: AsyncConnection,
    *,
    user_id: str,
    provider_key: str,
    provider_subject: str,
    auth_identity_id: str | None = None,
) -> AuthIdentity:
    result = await conn.execute(
        text(
            f"INSERT INTO auth_identity "
            f"(auth_identity_id, user_id, provider_key, provider_subject) "
            f"VALUES (:auth_identity_id, :user_id, :provider_key, :provider_subject) "
            f"RETURNING {_IDENTITY_COLUMNS}"
        ),
        {
            "auth_identity_id": auth_identity_id or new_auth_identity_id(),
            "user_id": user_id,
            "provider_key": _clean(provider_key, label="provider_key"),
            "provider_subject": _clean(provider_subject, label="provider_subject"),
        },
    )
    return _model(AuthIdentity, result.mappings().one())


async def get_auth_identity(
    conn: AsyncConnection, *, provider_key: str, provider_subject: str
) -> AuthIdentity | None:
    result = await conn.execute(
        text(
            f"SELECT {_IDENTITY_COLUMNS} FROM auth_identity "
            "WHERE provider_key = :provider_key AND provider_subject = :provider_subject"
        ),
        {"provider_key": provider_key, "provider_subject": provider_subject},
    )
    row = result.mappings().first()
    return _model(AuthIdentity, row) if row is not None else None


async def list_auth_identities(conn: AsyncConnection, user_id: str) -> tuple[AuthIdentity, ...]:
    rows = (
        await conn.execute(
            text(
                f"SELECT {_IDENTITY_COLUMNS} FROM auth_identity "
                "WHERE user_id = :user_id ORDER BY linked_at, auth_identity_id"
            ),
            {"user_id": user_id},
        )
    ).mappings()
    return tuple(_model(AuthIdentity, row) for row in rows)


async def create_workspace_membership(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    user_id: str,
    role_key: str,
    status: Literal["invited", "active"] = "active",
    membership_id: str | None = None,
    now: datetime | None = None,
) -> WorkspaceMembership:
    at = now or datetime.now(UTC)
    result = await conn.execute(
        text(
            f"INSERT INTO workspace_membership "
            f"(membership_id, workspace_id, user_id, role_key, status, activated_at) "
            f"VALUES (:membership_id, :workspace_id, :user_id, :role_key, :status, :activated_at) "
            f"RETURNING {_MEMBERSHIP_COLUMNS}"
        ),
        {
            "membership_id": membership_id or new_membership_id(),
            "workspace_id": workspace_id,
            "user_id": user_id,
            "role_key": require_role_key(role_key),
            "status": status,
            "activated_at": at if status == "active" else None,
        },
    )
    return _model(WorkspaceMembership, result.mappings().one())


async def get_workspace_membership(
    conn: AsyncConnection, *, workspace_id: str, user_id: str
) -> WorkspaceMembership | None:
    result = await conn.execute(
        text(
            f"SELECT {_MEMBERSHIP_COLUMNS} FROM workspace_membership "
            "WHERE workspace_id = :workspace_id AND user_id = :user_id"
        ),
        {"workspace_id": workspace_id, "user_id": user_id},
    )
    row = result.mappings().first()
    return _model(WorkspaceMembership, row) if row is not None else None


async def get_membership(
    conn: AsyncConnection, *, workspace_id: str, membership_id: str
) -> WorkspaceMembership | None:
    result = await conn.execute(
        text(
            f"SELECT {_MEMBERSHIP_COLUMNS} FROM workspace_membership "
            "WHERE workspace_id = :workspace_id AND membership_id = :membership_id"
        ),
        {"workspace_id": workspace_id, "membership_id": membership_id},
    )
    row = result.mappings().first()
    return _model(WorkspaceMembership, row) if row is not None else None


async def list_user_memberships(
    conn: AsyncConnection, user_id: str
) -> tuple[WorkspaceMembership, ...]:
    # The only membership read that joins the workspace row: the session view it feeds is where
    # a user picks a workspace, and they must see its name, never its id.
    rows = (
        await conn.execute(
            text(
                "SELECT m.membership_id, m.workspace_id, m.user_id, m.role_key, m.status, "
                "m.created_at, m.activated_at, m.revoked_at, w.name AS workspace_name "
                "FROM workspace_membership m JOIN workspace w USING (workspace_id) "
                "WHERE m.user_id = :user_id ORDER BY m.created_at, m.membership_id"
            ),
            {"user_id": user_id},
        )
    ).mappings()
    return tuple(_model(WorkspaceMembership, row) for row in rows)


async def set_workspace_membership_role(
    conn: AsyncConnection, membership_id: str, role_key: str
) -> WorkspaceMembership:
    result = await conn.execute(
        text(
            f"UPDATE workspace_membership SET role_key = :role_key "
            f"WHERE membership_id = :membership_id AND status <> 'revoked' "
            f"RETURNING {_MEMBERSHIP_COLUMNS}"
        ),
        {"membership_id": membership_id, "role_key": require_role_key(role_key)},
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError("membership is absent or revoked")
    return _model(WorkspaceMembership, row)


async def _require_membership_manager(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    acting_membership_id: str,
) -> WorkspaceMembership:
    actor = await get_membership(
        conn,
        workspace_id=workspace_id,
        membership_id=acting_membership_id,
    )
    if (
        actor is None
        or actor.status != "active"
        or not role_has_permission(actor.role_key, "workspace.manage_members")
    ):
        raise MembershipPermissionError(
            "an active workspace membership with workspace.manage_members is required"
        )
    return actor


async def _require_owner_survives(
    conn: AsyncConnection,
    *,
    target: WorkspaceMembership,
) -> None:
    if target.status != "active" or target.role_key != "owner":
        return
    remaining = int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM workspace_membership "
                    "WHERE workspace_id = :workspace_id AND membership_id <> :membership_id "
                    "AND status = 'active' AND role_key = 'owner'"
                ),
                {
                    "workspace_id": target.workspace_id,
                    "membership_id": target.membership_id,
                },
            )
        ).scalar_one()
    )
    if remaining == 0:
        raise MembershipPermissionError("a workspace must retain at least one active owner")


async def create_workspace_member(
    conn: AsyncConnection,
    *,
    acting_membership_id: str,
    workspace_id: str,
    user_id: str,
    role_key: str,
    status: Literal["invited", "active"] = "active",
    membership_id: str | None = None,
    now: datetime | None = None,
) -> WorkspaceMembership:
    actor = await _require_membership_manager(
        conn,
        workspace_id=workspace_id,
        acting_membership_id=acting_membership_id,
    )
    if not role_can_assign(actor.role_key, role_key):
        raise MembershipPermissionError("membership manager cannot grant this role")
    return await create_workspace_membership(
        conn,
        workspace_id=workspace_id,
        user_id=user_id,
        role_key=role_key,
        status=status,
        membership_id=membership_id,
        now=now,
    )


async def change_workspace_member_role(
    conn: AsyncConnection,
    *,
    acting_membership_id: str,
    workspace_id: str,
    membership_id: str,
    role_key: str,
) -> WorkspaceMembership:
    actor = await _require_membership_manager(
        conn,
        workspace_id=workspace_id,
        acting_membership_id=acting_membership_id,
    )
    if not role_can_assign(actor.role_key, role_key):
        raise MembershipPermissionError("membership manager cannot grant this role")
    target = await get_membership(
        conn,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )
    if target is None or target.status == "revoked":
        raise LifecycleTransitionError("membership is absent or revoked")
    if target.role_key == "owner" and role_key != "owner":
        await _require_owner_survives(conn, target=target)
    return await set_workspace_membership_role(conn, membership_id, role_key)


async def create_workspace_invitation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    invited_address: str,
    role_key: str,
    token_digest: str,
    expires_at: datetime,
    invited_by_membership_id: str,
    invitation_id: str | None = None,
    now: datetime | None = None,
) -> WorkspaceInvitation:
    at = now or datetime.now(UTC)
    if expires_at <= at:
        raise ValueError("invitation expires_at must be in the future")
    inviter = await get_membership(
        conn, workspace_id=workspace_id, membership_id=invited_by_membership_id
    )
    if inviter is None or inviter.status != "active":
        raise MembershipPermissionError("inviter must be an active membership in the workspace")
    if not role_has_permission(inviter.role_key, "workspace.manage_members"):
        raise MembershipPermissionError("inviter lacks workspace.manage_members")
    if not role_can_assign(inviter.role_key, role_key):
        raise MembershipPermissionError("inviter cannot grant a role above its own")
    result = await conn.execute(
        text(
            f"INSERT INTO workspace_invitation "
            f"(invitation_id, workspace_id, invited_address, role_key, token_digest, expires_at, "
            f" invited_by_membership_id) "
            f"VALUES (:invitation_id, :workspace_id, :invited_address, :role_key, :token_digest, "
            f" :expires_at, :invited_by_membership_id) RETURNING {_INVITATION_COLUMNS}"
        ),
        {
            "invitation_id": invitation_id or new_invitation_id(),
            "workspace_id": workspace_id,
            "invited_address": _clean(invited_address, label="invited_address"),
            "role_key": require_role_key(role_key),
            "token_digest": _clean(token_digest, label="token_digest"),
            "expires_at": expires_at,
            "invited_by_membership_id": invited_by_membership_id,
        },
    )
    return _model(WorkspaceInvitation, result.mappings().one())


async def lock_invitation_by_digest(
    conn: AsyncConnection, token_digest: str
) -> WorkspaceInvitation | None:
    result = await conn.execute(
        text(
            f"SELECT {_INVITATION_COLUMNS} FROM workspace_invitation "
            "WHERE token_digest = :token_digest FOR UPDATE"
        ),
        {"token_digest": token_digest},
    )
    row = result.mappings().first()
    return _model(WorkspaceInvitation, row) if row is not None else None


async def mark_invitation_accepted(
    conn: AsyncConnection, *, invitation_id: str, user_id: str, now: datetime
) -> WorkspaceInvitation:
    result = await conn.execute(
        text(
            f"UPDATE workspace_invitation SET status = 'accepted', "
            f"accepted_by_user_id = :user_id, accepted_at = :now "
            f"WHERE invitation_id = :invitation_id AND status = 'pending' "
            f"RETURNING {_INVITATION_COLUMNS}"
        ),
        {"invitation_id": invitation_id, "user_id": user_id, "now": now},
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError("invitation is no longer pending")
    return _model(WorkspaceInvitation, row)


async def revoke_workspace_invitation(
    conn: AsyncConnection, invitation_id: str, *, now: datetime | None = None
) -> WorkspaceInvitation:
    return cast(
        WorkspaceInvitation,
        await _transition(
            conn,
            table="workspace_invitation",
            id_column="invitation_id",
            row_id=invitation_id,
            from_statuses=("pending",),
            set_sql="status = 'revoked', revoked_at = :now",
            columns=_INVITATION_COLUMNS,
            model=WorkspaceInvitation,
            now=now or datetime.now(UTC),
        ),
    )


async def expire_workspace_invitations(
    conn: AsyncConnection, *, now: datetime | None = None
) -> int:
    result = await conn.execute(
        text(
            "UPDATE workspace_invitation SET status = 'expired' "
            "WHERE status = 'pending' AND expires_at <= :now"
        ),
        {"now": now or datetime.now(UTC)},
    )
    return result.rowcount


async def activate_invited_membership(
    conn: AsyncConnection, *, membership_id: str, role_key: str, now: datetime
) -> WorkspaceMembership:
    result = await conn.execute(
        text(
            f"UPDATE workspace_membership SET status = 'active', role_key = :role_key, "
            f"activated_at = :now WHERE membership_id = :membership_id AND status = 'invited' "
            f"RETURNING {_MEMBERSHIP_COLUMNS}"
        ),
        {"membership_id": membership_id, "role_key": require_role_key(role_key), "now": now},
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError("membership is no longer invited")
    return _model(WorkspaceMembership, row)


async def _transition(
    conn: AsyncConnection,
    *,
    table: str,
    id_column: str,
    row_id: str,
    from_statuses: tuple[str, ...],
    set_sql: str,
    columns: str,
    model: type[Any],
    now: datetime,
) -> Any:
    result = await conn.execute(
        text(
            f"UPDATE {table} SET {set_sql} WHERE {id_column} = :row_id "
            "AND status = ANY(:from_statuses) "
            f"RETURNING {columns}"
        ),
        {"row_id": row_id, "from_statuses": list(from_statuses), "now": now},
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError(
            f"{table} {row_id!r} is absent or cannot transition from its current status"
        )
    return _model(model, row)


async def suspend_platform_user(
    conn: AsyncConnection, user_id: str, *, now: datetime | None = None
) -> PlatformUser:
    return cast(
        PlatformUser,
        await _transition(
            conn,
            table="platform_user",
            id_column="user_id",
            row_id=user_id,
            from_statuses=("active",),
            set_sql="status = 'suspended', suspended_at = :now",
            columns=_USER_COLUMNS,
            model=PlatformUser,
            now=now or datetime.now(UTC),
        ),
    )


async def reactivate_platform_user(
    conn: AsyncConnection, user_id: str, *, now: datetime | None = None
) -> PlatformUser:
    return cast(
        PlatformUser,
        await _transition(
            conn,
            table="platform_user",
            id_column="user_id",
            row_id=user_id,
            from_statuses=("suspended",),
            set_sql="status = 'active', suspended_at = NULL",
            columns=_USER_COLUMNS,
            model=PlatformUser,
            now=now or datetime.now(UTC),
        ),
    )


async def disable_platform_user(
    conn: AsyncConnection, user_id: str, *, now: datetime | None = None
) -> PlatformUser:
    return cast(
        PlatformUser,
        await _transition(
            conn,
            table="platform_user",
            id_column="user_id",
            row_id=user_id,
            from_statuses=("active", "suspended"),
            set_sql="status = 'disabled', disabled_at = :now",
            columns=_USER_COLUMNS,
            model=PlatformUser,
            now=now or datetime.now(UTC),
        ),
    )


async def unlink_auth_identity(
    conn: AsyncConnection, auth_identity_id: str, *, now: datetime | None = None
) -> AuthIdentity:
    return cast(
        AuthIdentity,
        await _transition(
            conn,
            table="auth_identity",
            id_column="auth_identity_id",
            row_id=auth_identity_id,
            from_statuses=("active",),
            set_sql="status = 'unlinked'",
            columns=_IDENTITY_COLUMNS,
            model=AuthIdentity,
            now=now or datetime.now(UTC),
        ),
    )


async def relink_auth_identity(
    conn: AsyncConnection, auth_identity_id: str, *, now: datetime | None = None
) -> AuthIdentity:
    return cast(
        AuthIdentity,
        await _transition(
            conn,
            table="auth_identity",
            id_column="auth_identity_id",
            row_id=auth_identity_id,
            from_statuses=("unlinked",),
            set_sql="status = 'active'",
            columns=_IDENTITY_COLUMNS,
            model=AuthIdentity,
            now=now or datetime.now(UTC),
        ),
    )


async def revoke_auth_identity(
    conn: AsyncConnection, auth_identity_id: str, *, now: datetime | None = None
) -> AuthIdentity:
    return cast(
        AuthIdentity,
        await _transition(
            conn,
            table="auth_identity",
            id_column="auth_identity_id",
            row_id=auth_identity_id,
            from_statuses=("active", "unlinked"),
            set_sql="status = 'revoked', revoked_at = :now",
            columns=_IDENTITY_COLUMNS,
            model=AuthIdentity,
            now=now or datetime.now(UTC),
        ),
    )


async def suspend_workspace_membership(
    conn: AsyncConnection, membership_id: str, *, now: datetime | None = None
) -> WorkspaceMembership:
    return cast(
        WorkspaceMembership,
        await _transition(
            conn,
            table="workspace_membership",
            id_column="membership_id",
            row_id=membership_id,
            from_statuses=("active",),
            set_sql="status = 'suspended'",
            columns=_MEMBERSHIP_COLUMNS,
            model=WorkspaceMembership,
            now=now or datetime.now(UTC),
        ),
    )


async def reactivate_workspace_membership(
    conn: AsyncConnection, membership_id: str, *, now: datetime | None = None
) -> WorkspaceMembership:
    return cast(
        WorkspaceMembership,
        await _transition(
            conn,
            table="workspace_membership",
            id_column="membership_id",
            row_id=membership_id,
            from_statuses=("suspended",),
            set_sql="status = 'active'",
            columns=_MEMBERSHIP_COLUMNS,
            model=WorkspaceMembership,
            now=now or datetime.now(UTC),
        ),
    )


async def revoke_workspace_membership(
    conn: AsyncConnection, membership_id: str, *, now: datetime | None = None
) -> WorkspaceMembership:
    return cast(
        WorkspaceMembership,
        await _transition(
            conn,
            table="workspace_membership",
            id_column="membership_id",
            row_id=membership_id,
            from_statuses=("invited", "active", "suspended"),
            set_sql="status = 'revoked', revoked_at = :now",
            columns=_MEMBERSHIP_COLUMNS,
            model=WorkspaceMembership,
            now=now or datetime.now(UTC),
        ),
    )


async def revoke_workspace_member(
    conn: AsyncConnection,
    *,
    acting_membership_id: str,
    workspace_id: str,
    membership_id: str,
    now: datetime | None = None,
) -> WorkspaceMembership:
    await _require_membership_manager(
        conn,
        workspace_id=workspace_id,
        acting_membership_id=acting_membership_id,
    )
    target = await get_membership(
        conn,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )
    if target is None:
        raise LifecycleTransitionError("membership is absent")
    await _require_owner_survives(conn, target=target)
    return await revoke_workspace_membership(conn, membership_id, now=now)


async def readmit_workspace_member(
    conn: AsyncConnection,
    *,
    acting_membership_id: str,
    workspace_id: str,
    membership_id: str,
    role_key: str,
    now: datetime | None = None,
) -> WorkspaceMembership:
    actor = await _require_membership_manager(
        conn,
        workspace_id=workspace_id,
        acting_membership_id=acting_membership_id,
    )
    if not role_can_assign(actor.role_key, role_key):
        raise MembershipPermissionError("membership manager cannot grant this role")
    result = await conn.execute(
        text(
            f"UPDATE workspace_membership SET status = 'active', role_key = :role_key, "
            f"activated_at = :now, revoked_at = NULL "
            f"WHERE membership_id = :membership_id AND workspace_id = :workspace_id "
            f"AND status = 'revoked' RETURNING {_MEMBERSHIP_COLUMNS}"
        ),
        {
            "membership_id": membership_id,
            "workspace_id": workspace_id,
            "role_key": require_role_key(role_key),
            "now": now or datetime.now(UTC),
        },
    )
    row = result.mappings().first()
    if row is None:
        raise LifecycleTransitionError("membership is absent or not revoked")
    return _model(WorkspaceMembership, row)


async def erase_invitation_delivery_target(
    conn: AsyncConnection,
    invited_address: str,
) -> int:
    """Erase pending/expired/revoked invitation PII before it ever maps to a user id."""

    normalized = _clean(invited_address, label="invited_address").casefold()
    result = await conn.execute(
        text(
            "UPDATE workspace_invitation SET invited_address = 'erased:' || invitation_id "
            "WHERE accepted_by_user_id IS NULL "
            "AND lower(btrim(invited_address)) = :invited_address "
            "AND invited_address <> 'erased:' || invitation_id"
        ),
        {"invited_address": normalized},
    )
    return result.rowcount


async def identity_bundle(conn: AsyncConnection, user_id: str) -> IdentityBundle | None:
    user = await get_platform_user(conn, user_id)
    if user is None:
        return None
    invitation_rows = (
        await conn.execute(
            text(
                f"SELECT {_INVITATION_COLUMNS} FROM workspace_invitation "
                "WHERE accepted_by_user_id = :user_id ORDER BY created_at, invitation_id"
            ),
            {"user_id": user_id},
        )
    ).mappings()
    provisioning_rows = (
        await conn.execute(
            text(
                "SELECT auth_identity_id, user_id, workspace_id, brand_id, company_website, "
                "created_at FROM self_serve_provisioning WHERE user_id = :user_id "
                "ORDER BY created_at, auth_identity_id"
            ),
            {"user_id": user_id},
        )
    ).mappings()
    return IdentityBundle(
        user=user,
        auth_identities=await list_auth_identities(conn, user_id),
        memberships=await list_user_memberships(conn, user_id),
        accepted_invitations=tuple(_model(WorkspaceInvitation, row) for row in invitation_rows),
        self_serve_provisionings=tuple(
            _model(SelfServeProvisioningRecord, row) for row in provisioning_rows
        ),
    )


async def erase_platform_user(
    conn: AsyncConnection, user_id: str, *, now: datetime | None = None
) -> IdentityErasureResult:
    """Erase mutable profile/provider values while preserving internal audit references.

    The Clue ``user_id`` and membership rows survive because domain receipts must remain
    attributable. A row that is purely this human's own metadata — the artifacts library's
    saved/last-viewed marks — is deleted outright instead, since nothing downstream cites it.
    External subjects and accepted invitation addresses are replaced with stable, non-personal
    tombstones; every authentication mapping and membership is revoked.

    ``workspace.name``/``brand.name`` deliberately survive even though self-serve provisioning
    copies the submitted company name into both: a workspace is a shared org object other
    members may still administer, so renaming it is not this function's call (review ruling
    2026-08-12). ``self_serve_provisioning.company_website`` IS erased — it can identify a
    solo founder. Known residual (slice-2 review BE-M7): the workspace-setup capture stores
    the submitted URL as artifact BYTES (content-addressed blob + ``artifact`` row); those are
    not reachable from here (append-only capture substrate, cross-package seam) and survive
    erasure. The setup surface deliberately writes no ``onboarding_input.source_ref`` copy so
    the un-redactable append-only row carries no URL; full artifact tombstoning rides the
    B2/DSAR artifact machinery — tracked in ``_memory`` until that lands.
    """
    at = now or datetime.now(UTC)
    user_result = await conn.execute(
        text(
            "UPDATE platform_user SET display_name = NULL, first_name = NULL, "
            "last_name = NULL, job_role = NULL, email = NULL, status = 'disabled', "
            "disabled_at = COALESCE(disabled_at, :now) WHERE user_id = :user_id RETURNING user_id"
        ),
        {"user_id": user_id, "now": at},
    )
    if user_result.scalar_one_or_none() is None:
        raise LifecycleTransitionError(f"platform_user {user_id!r} does not exist")
    identities = await conn.execute(
        text(
            "UPDATE auth_identity SET provider_subject = 'erased:' || auth_identity_id, "
            "status = 'revoked', revoked_at = COALESCE(revoked_at, :now) "
            "WHERE user_id = :user_id"
        ),
        {"user_id": user_id, "now": at},
    )
    memberships = await conn.execute(
        text(
            "UPDATE workspace_membership SET status = 'revoked', "
            "revoked_at = COALESCE(revoked_at, :now) WHERE user_id = :user_id"
        ),
        {"user_id": user_id, "now": at},
    )
    invitations = await conn.execute(
        text(
            "UPDATE workspace_invitation SET invited_address = 'erased:' || invitation_id "
            "WHERE accepted_by_user_id = :user_id "
            "AND invited_address <> 'erased:' || invitation_id"
        ),
        {"user_id": user_id},
    )
    provisionings = await conn.execute(
        text(
            "UPDATE self_serve_provisioning SET company_website = NULL "
            "WHERE user_id = :user_id AND company_website IS NOT NULL"
        ),
        {"user_id": user_id},
    )
    # The mark rows are this human's own metadata about documents (saved, last-viewed) and carry
    # no audit value, so erasure deletes them outright rather than tombstoning: the document
    # survives, the fact that this person saved it does not.
    marks = await conn.execute(
        text("DELETE FROM design_document_user_mark WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    return IdentityErasureResult(
        user_id=user_id,
        auth_identities_revoked=identities.rowcount,
        memberships_revoked=memberships.rowcount,
        invitation_addresses_erased=invitations.rowcount,
        provisioning_websites_erased=provisionings.rowcount,
        artifact_marks_deleted=marks.rowcount,
    )
