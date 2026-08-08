"""Lane B authentication composition: provider session -> Clue request principal.

This module is the only API composition seam that selects an authentication adapter. Routes and
domain services consume :class:`clue_auth.RequestPrincipal`; they never import Clerk or inspect a
provider claim.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from clue_auth import (
    AuthenticatedSessionView,
    AuthenticationRequest,
    Authenticator,
    DatabaseAuthorizer,
    DatabaseIdentityResolver,
    DatabaseMembershipLoader,
    LocalFixtureAuthenticator,
    Permission,
    PrincipalError,
    PrincipalService,
    RequestPrincipal,
    WorkspaceForbidden,
    permissions_for_role,
)
from clue_auth.providers import ClerkAuthenticator, ClerkJwtConfig
from clue_config import Settings
from clue_db import ConnFactory

AUTH_PREFIX = "/auth/v1"
WORKSPACE_HEADER = "X-Clue-Workspace-Id"
LOCAL_SUBJECT_HEADER = "X-Clue-Local-Auth-Subject"


class SessionMembershipResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    membership_id: str
    workspace_id: str
    role_key: str
    permissions: frozenset[str]


class SessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    memberships: tuple[SessionMembershipResponse, ...]


class PrincipalResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    membership_id: str
    workspace_id: str
    role_key: str
    permissions: frozenset[str]


def authentication_request(request: Request) -> AuthenticationRequest:
    return AuthenticationRequest(
        authorization=request.headers.get("Authorization"),
        local_subject=request.headers.get(LOCAL_SUBJECT_HEADER),
    )


class SessionDependency:
    def __init__(self, service: PrincipalService) -> None:
        self._service = service

    async def __call__(self, request: Request) -> AuthenticatedSessionView:
        return await self._service.session_view(authentication_request(request))


class PrincipalDependency:
    """FastAPI dependency resolving the selected workspace to a closed internal principal."""

    def __init__(self, service: PrincipalService, *, permission: Permission | None = None) -> None:
        self._service = service
        self._permission = permission

    async def __call__(
        self,
        request: Request,
        workspace_id: Annotated[str | None, Header(alias=WORKSPACE_HEADER)] = None,
    ) -> RequestPrincipal:
        selected = workspace_id.strip() if workspace_id else ""
        if not selected:
            raise WorkspaceForbidden("a workspace selection is required")
        return await self._service.principal(
            authentication_request(request),
            workspace_id=selected,
            permission=self._permission,
        )


def require_principal(
    service: PrincipalService, *, permission: Permission | None = None
) -> PrincipalDependency:
    return PrincipalDependency(service, permission=permission)


def build_principal_service(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
) -> tuple[PrincipalService, Callable[[], Awaitable[None]] | None]:
    """Build the configured provider adapter and internal Postgres resolvers.

    The optional closer belongs to the caller's app lifespan. A production process cannot build
    the local fixture adapter even if settings were constructed without normal validation.
    """

    if settings.auth_environment == "production" and settings.auth_mode != "clerk":
        raise RuntimeError("production authentication requires the Clerk adapter")
    closer: Callable[[], Awaitable[None]] | None = None
    authenticator: Authenticator
    if settings.auth_mode == "local_fixture":
        authenticator = LocalFixtureAuthenticator()
    else:
        missing = [
            name
            for name, value in (
                ("CLUE_AUTH_CLERK_JWKS_URL", settings.auth_clerk_jwks_url),
                ("CLUE_AUTH_CLERK_ISSUER", settings.auth_clerk_issuer),
                ("CLUE_AUTH_CLERK_AUDIENCE", settings.auth_clerk_audience),
            )
            if not value
        ]
        if not settings.auth_clerk_authorized_parties:
            missing.append("CLUE_AUTH_CLERK_AUTHORIZED_PARTIES")
        if missing:
            raise RuntimeError(
                f"Clerk authentication is missing required settings: {', '.join(missing)}"
            )
        assert settings.auth_clerk_jwks_url is not None
        assert settings.auth_clerk_issuer is not None
        clerk = ClerkAuthenticator(
            ClerkJwtConfig.model_validate(
                {
                    "jwks_url": settings.auth_clerk_jwks_url,
                    "issuer": settings.auth_clerk_issuer,
                    "audience": settings.auth_clerk_audience,
                    "authorized_parties": settings.auth_clerk_authorized_parties,
                }
            )
        )
        authenticator = clerk
        closer = clerk.aclose

    service = PrincipalService(
        authenticator=authenticator,
        identity_resolver=DatabaseIdentityResolver(conn_factory=conn_factory),
        authorizer=DatabaseAuthorizer(conn_factory=conn_factory),
        memberships_for_user=DatabaseMembershipLoader(conn_factory=conn_factory),
    )
    return service, closer


def build_auth_router(*, service: PrincipalService) -> APIRouter:
    router = APIRouter(prefix=AUTH_PREFIX, tags=["authentication"])
    session_dependency = SessionDependency(service)
    principal_dependency = PrincipalDependency(service)

    @router.get("/session", response_model=SessionResponse)
    async def get_session(
        session: Annotated[AuthenticatedSessionView, Depends(session_dependency)],
    ) -> SessionResponse:
        return SessionResponse(
            user_id=session.user_id,
            memberships=tuple(
                SessionMembershipResponse(
                    membership_id=item.membership_id,
                    workspace_id=item.workspace_id,
                    role_key=item.role_key,
                    permissions=permissions_for_role(item.role_key),
                )
                for item in session.memberships
            ),
        )

    @router.get("/principal", response_model=PrincipalResponse)
    async def get_principal(
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
    ) -> PrincipalResponse:
        return PrincipalResponse(
            user_id=principal.user_id,
            membership_id=principal.membership_id,
            workspace_id=principal.workspace_id,
            role_key=principal.role_key,
            permissions=principal.permissions,
        )

    return router


def install_auth_wiring(app: FastAPI, *, service: PrincipalService) -> None:
    """Install the provider-free session routes and stable auth error envelope."""

    @app.exception_handler(PrincipalError)
    async def _principal_error_handler(_request: Request, exc: PrincipalError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(build_auth_router(service=service))


__all__ = [
    "AUTH_PREFIX",
    "LOCAL_SUBJECT_HEADER",
    "PrincipalDependency",
    "SessionDependency",
    "WORKSPACE_HEADER",
    "authentication_request",
    "build_auth_router",
    "build_principal_service",
    "install_auth_wiring",
    "require_principal",
]
