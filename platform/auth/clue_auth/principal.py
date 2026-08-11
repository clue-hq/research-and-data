"""Provider-neutral authenticated-principal contract for Lane B.

Provider data ends at :class:`ExternalSession`.  Every object after that seam carries only
Clue-owned identifiers and policy values.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from clue_auth.models import RoleKey, UserStatus, WorkspaceMembership
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
    provider_session_subject: str | None = None
    issued_at: UtcDatetime
    expires_at: UtcDatetime
    authenticated_at: UtcDatetime


class InternalIdentity(BaseModel):
    """The canonical Clue user resolved from an external session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    auth_identity_id: str
    user_status: UserStatus
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


class ServicePrincipal(BaseModel):
    """Closed machine authority for detached work; never a human or provider subject."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_kind: Literal["service"] = "service"
    service_id: str
    workspace_id: str
    permissions: frozenset[Permission]
    authenticated_at: UtcDatetime

    def require(self, permission: Permission) -> None:
        from clue_auth.errors import PermissionDenied

        if permission not in self.permissions:
            raise PermissionDenied(f"permission {permission!r} is required")


class AuthenticatedSessionView(BaseModel):
    """Provider-free session data safe for the Next.js server DAL.

    ``memberships`` carries ACTIVE memberships only. ``has_inactive_memberships`` lets the
    frontend distinguish "never had access" (route to self-serve onboarding) from "had access,
    lost it" (route to access-denied) without exposing the inactive rows themselves —
    FI-4 slice-1 review ruling, 2026-08-12.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    memberships: tuple[WorkspaceMembership, ...]
    authenticated_at: UtcDatetime
    has_inactive_memberships: bool = False


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
        permission: Permission,
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

    async def external_session(self, request: AuthenticationRequest) -> ExternalSession:
        """Authenticate the provider session WITHOUT requiring a provisioned Clue identity.

        This is the provisioning seam (FI-4 D-2): a brand-new Clerk user has no
        ``auth_identity`` yet, so ``identity()`` would refuse with IDENTITY_NOT_PROVISIONED.
        The returned session is short-lived provider material — callers may hand its subject
        to the provisioning transaction and must never persist it as domain identity.
        """
        return await self._authenticator.authenticate(request)

    async def session_view(self, request: AuthenticationRequest) -> AuthenticatedSessionView:
        identity = await self.identity(request)
        all_memberships = await self._memberships_for_user(identity.user_id)
        memberships = tuple(
            membership for membership in all_memberships if membership.status == "active"
        )
        return AuthenticatedSessionView(
            user_id=identity.user_id,
            memberships=memberships,
            authenticated_at=identity.authenticated_at,
            has_inactive_memberships=len(memberships) < len(all_memberships),
        )

    async def principal(
        self,
        request: AuthenticationRequest,
        *,
        workspace_id: str,
        permission: Permission,
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
