"""Provider-neutral authenticated-principal contract for Lane B.

Provider data ends at :class:`ExternalSession`.  Every object after that seam carries only
Clue-owned identifiers and policy values.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from clue_auth.models import RoleKey, WorkspaceMembership
from clue_auth.policy import Permission
from clue_core import UtcDatetime


class AuthenticationRequest(BaseModel):
    """The minimum HTTP material an authenticator may inspect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorization: str | None = None
    local_subject: str | None = None


class ExternalSession(BaseModel):
    """A validated, short-lived provider assertion; never persisted as domain identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_key: str
    provider_subject: str
    session_id: str
    issued_at: UtcDatetime
    expires_at: UtcDatetime
    authenticated_at: UtcDatetime


class InternalIdentity(BaseModel):
    """The canonical Clue user resolved from an external session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    auth_identity_id: str
    authenticated_at: UtcDatetime


class RequestPrincipal(BaseModel):
    """Closed request authority: internal human, active membership, internal permissions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_kind: Literal["human"] = "human"
    user_id: str
    membership_id: str
    workspace_id: str
    role_key: RoleKey
    permissions: frozenset[Permission]
    authenticated_at: UtcDatetime

    def require(self, permission: Permission) -> None:
        from clue_auth.errors import PermissionDenied

        if permission not in self.permissions:
            raise PermissionDenied(f"permission {permission!r} is required")


class AuthenticatedSessionView(BaseModel):
    """Provider-free session data safe for the Next.js server DAL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    memberships: tuple[WorkspaceMembership, ...]
    authenticated_at: UtcDatetime


class Authenticator(Protocol):
    async def authenticate(self, request: AuthenticationRequest) -> ExternalSession: ...


class IdentityResolver(Protocol):
    async def resolve(self, session: ExternalSession) -> InternalIdentity: ...


class Authorizer(Protocol):
    async def require(
        self,
        identity: InternalIdentity,
        *,
        workspace_id: str,
        permission: Permission | None = None,
    ) -> RequestPrincipal: ...


MembershipLoader = Callable[[str], Awaitable[tuple[WorkspaceMembership, ...]]]


class PrincipalService:
    """Compose authentication, internal identity resolution, and workspace authorization."""

    def __init__(
        self,
        *,
        authenticator: Authenticator,
        identity_resolver: IdentityResolver,
        authorizer: Authorizer,
        memberships_for_user: MembershipLoader,
    ) -> None:
        self._authenticator = authenticator
        self._identity_resolver = identity_resolver
        self._authorizer = authorizer
        self._memberships_for_user = memberships_for_user

    async def identity(self, request: AuthenticationRequest) -> InternalIdentity:
        session = await self._authenticator.authenticate(request)
        return await self._identity_resolver.resolve(session)

    async def session_view(self, request: AuthenticationRequest) -> AuthenticatedSessionView:
        identity = await self.identity(request)
        memberships = tuple(
            membership
            for membership in await self._memberships_for_user(identity.user_id)
            if membership.status == "active"
        )
        return AuthenticatedSessionView(
            user_id=identity.user_id,
            memberships=memberships,
            authenticated_at=identity.authenticated_at,
        )

    async def principal(
        self,
        request: AuthenticationRequest,
        *,
        workspace_id: str,
        permission: Permission | None = None,
    ) -> RequestPrincipal:
        identity = await self.identity(request)
        return await self._authorizer.require(
            identity,
            workspace_id=workspace_id,
            permission=permission,
        )


def utc_from_timestamp(value: int | float) -> datetime:
    """Convert a JWT NumericDate to the timezone-aware form used by Clue models."""

    from datetime import UTC

    return datetime.fromtimestamp(value, tz=UTC)
