"""Postgres-backed external-session resolution and internal authorization."""

from __future__ import annotations

from clue_auth.errors import (
    IdentityNotProvisioned,
    PermissionDenied,
    UserDisabled,
    WorkspaceForbidden,
)
from clue_auth.models import WorkspaceMembership
from clue_auth.policy import Permission, permissions_for_role
from clue_auth.principal import ExternalSession, InternalIdentity, RequestPrincipal
from clue_auth.store import (
    get_auth_identity,
    get_platform_user,
    get_workspace_membership,
    list_user_memberships,
)
from clue_db import ConnFactory


class DatabaseIdentityResolver:
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def resolve(self, session: ExternalSession) -> InternalIdentity:
        async with self._conn_factory() as conn:
            mapping = await get_auth_identity(
                conn,
                provider_key=session.provider_key,
                provider_subject=session.provider_subject,
            )
            if mapping is None or mapping.status != "active":
                raise IdentityNotProvisioned(
                    "authenticated identity is not provisioned in Clue",
                    subject=session.provider_subject,
                )
            user = await get_platform_user(conn, mapping.user_id)
            if user is None:
                raise IdentityNotProvisioned(
                    "authenticated identity has no Clue user",
                    subject=session.provider_subject,
                    user_id=mapping.user_id,
                )
            if user.status != "active":
                raise UserDisabled(
                    "Clue user is suspended or disabled",
                    subject=session.provider_subject,
                    user_id=mapping.user_id,
                )
        return InternalIdentity(
            user_id=mapping.user_id,
            auth_identity_id=mapping.auth_identity_id,
            user_status=user.status,
            authenticated_at=session.authenticated_at,
        )


class DatabaseAuthorizer:
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def require(
        self,
        identity: InternalIdentity,
        *,
        workspace_id: str,
        permission: Permission,
    ) -> RequestPrincipal:
        async with self._conn_factory() as conn:
            user = await get_platform_user(conn, identity.user_id)
            if user is None or user.status != "active":
                raise UserDisabled("Clue user is suspended or disabled", user_id=identity.user_id)
            membership = await get_workspace_membership(
                conn,
                workspace_id=workspace_id,
                user_id=identity.user_id,
            )
            if membership is None or membership.status != "active":
                raise WorkspaceForbidden(
                    "user has no active membership in this workspace", user_id=identity.user_id
                )
        permissions = permissions_for_role(membership.role_key)
        if permission not in permissions:
            raise PermissionDenied(
                f"permission {permission!r} is required", user_id=identity.user_id
            )
        return RequestPrincipal(
            user_id=identity.user_id,
            membership_id=membership.membership_id,
            workspace_id=membership.workspace_id,
            role_key=membership.role_key,
            permissions=permissions,
            authenticated_at=identity.authenticated_at,
        )


class DatabaseMembershipLoader:
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def __call__(self, user_id: str) -> tuple[WorkspaceMembership, ...]:
        async with self._conn_factory() as conn:
            return await list_user_memberships(conn, user_id)
