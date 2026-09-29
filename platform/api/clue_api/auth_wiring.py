"""Lane B authentication composition: provider session -> Clue request principal.

This module is the only API composition seam that selects an authentication adapter. Routes and
domain services consume :class:`clue_auth.RequestPrincipal`; they never import Clerk or inspect a
provider claim.
"""

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.logo_resolution import brandfetch_logo_url
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
    provision_self_serve_workspace,
)
from clue_auth.errors import (
    IdentityConflictError,
    InvitationAddressMismatch,
    InvitationUnavailableError,
    ProvisioningConflict,
)
from clue_auth.providers import ClerkAuthenticator, ClerkJwtConfig
from clue_auth.providers.clerk_api import ClerkApi, ClerkApiError
from clue_auth.provisioning import (
    ProvisionedIdentity,
    accept_pending_workspace_invitations,
    accept_workspace_invitation,
)
from clue_auth.store import (
    get_platform_user,
    update_platform_user_email,
)
from clue_config import Settings
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_obs.otel import bind_and_annotate
from clue_spine import DEFAULT_PAGES_SYSTEM_SUFFIX

AUTH_PREFIX = "/auth/v1"
WORKSPACE_HEADER = "X-Clue-Workspace-Id"
LOCAL_SUBJECT_HEADER = "X-Clue-Local-Auth-Subject"
REQUEST_ID_HEADER = "X-Request-Id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
log = get_logger("clue_api.auth")


def request_id_for(request: Request) -> str:
    existing = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if existing and _SAFE_REQUEST_ID.fullmatch(existing):
        return existing
    return uuid4().hex


class SessionMembershipResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    membership_id: str
    workspace_id: str
    # What the user is shown for this workspace. Always present on the wire, so no screen has to
    # fall back to an id.
    workspace_name: str
    role_key: str
    permissions: frozenset[str]
    #: The company's logo for the workspace switcher: Brandfetch's embed-only Logo API mark for
    #: the website given at onboarding. ``None`` when there is no website or no client id — the
    #: switcher then keeps the workspace's initials.
    workspace_logo_url: str | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    memberships: tuple[SessionMembershipResponse, ...]
    has_inactive_memberships: bool


class PrincipalResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    membership_id: str
    workspace_id: str
    role_key: str
    permissions: frozenset[str]


class ProvisionRequest(BaseModel):
    """FI-4 D-2 onboarding profile submission. ``job_role`` is a title, never ``role_key``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    first_name: str = Field(min_length=1, max_length=200)
    last_name: str = Field(min_length=1, max_length=200)
    job_role: str = Field(min_length=1, max_length=200)
    # Optional: a company name typed here wins, and a submission without one is named from
    # ``company_website`` by the shared canonical rule. Provisioning refuses (422,
    # ``COMPANY_NAME_REQUIRED``) only when neither can name the workspace.
    company_name: str | None = Field(default=None, max_length=200)
    company_website: str | None = Field(default=None, max_length=2000)

    @field_validator("first_name", "last_name", "job_role")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must contain non-whitespace characters")
        return cleaned

    @field_validator("company_name")
    @classmethod
    def _blank_company_name_is_absent(cls, value: str | None) -> str | None:
        """A blank or whitespace-only name is "not typed", not an error: the website names it."""
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("company_website")
    @classmethod
    def _normalize_website(cls, value: str | None) -> str | None:
        """Normalize to a canonical http(s) URL; scheme-less input gains ``https://``.

        Refuses userinfo (catches ``mailto:a@b``-shaped junk), dotless hosts (catches
        ``javascript:...`` and bare ``localhost``), and non-http(s) schemes; lowercases the
        scheme and host. This is submission hygiene, not the SSRF boundary — the Stage-0
        scrape path applies its own network guard before any fetch.
        """
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        candidate = cleaned if "://" in cleaned else f"https://{cleaned}"
        try:
            parsed = urlsplit(candidate)
            host = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise ValueError("company_website must be an http(s) URL") from error
        if (
            parsed.scheme.lower() not in ("http", "https")
            or not host
            or "." not in host
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("company_website must be an http(s) URL")
        netloc = host.lower() + (f":{port}" if port is not None else "")
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, ""))


class ProvisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    workspace_id: str
    brand_id: str
    membership_id: str
    role_key: str
    company_name: str
    company_website: str | None
    first_name: str | None
    last_name: str | None
    job_role: str | None
    created: bool
    # True on a replay whose submitted company_name differs from the recorded workspace name.
    # Workspace/brand names are fixed at creation (review ruling 2026-08-12); this flag makes
    # the divergence detectable instead of silently echoing the old name as if accepted.
    company_name_ignored: bool


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

    def __init__(self, service: PrincipalService, *, permission: Permission) -> None:
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
        principal = await self._service.principal(
            authentication_request(request),
            workspace_id=selected,
            permission=self._permission,
        )
        request.state.clue_principal = principal
        return principal


def require_principal(service: PrincipalService, *, permission: Permission) -> PrincipalDependency:
    return PrincipalDependency(service, permission=permission)


def authenticated_route_resolvers(
    service: PrincipalService,
    *,
    permission: Permission = "project.read",
) -> tuple[
    Callable[..., Awaitable[str]],
    Callable[..., Awaitable[Literal["human"]]],
]:
    """Return cache-coherent workspace/actor dependencies over one closed principal.

    Existing routers retain their replaceable workspace/actor seams. Both wrappers depend on the
    same dependency object, so FastAPI resolves the provider token and Postgres membership once per
    request and stores the resulting principal on ``request.state`` for ambient ToolContext wiring.
    """

    principal_dependency = PrincipalDependency(service, permission=permission)

    async def workspace(
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
    ) -> str:
        # Lane 3 slice 2: the authenticated tenant seam. ``bind_and_annotate`` (not a plain bind):
        # the server span opened in the instrumentor's middleware, before this dependency ran, so
        # the start-time context copy has already happened and the span needs the second write.
        bind_and_annotate(workspace_id=principal.workspace_id)
        return principal.workspace_id

    async def actor(
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
    ) -> Literal["human"]:
        del principal
        return "human"

    return workspace, actor


def principal_from_request(request: Request) -> RequestPrincipal | None:
    principal = getattr(request.state, "clue_principal", None)
    return principal if isinstance(principal, RequestPrincipal) else None


def build_principal_service(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
) -> tuple[PrincipalService, Callable[[], Awaitable[None]] | None]:
    """Build the configured provider adapter and internal Postgres resolvers.

    The optional closer belongs to the caller's app lifespan. A production process cannot build
    the local fixture adapter even if settings were constructed without normal validation.
    """

    if settings.auth_environment is None:
        raise RuntimeError(
            "authentication environment must be declared before adapter construction"
        )
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


def _website_domain(website: str | None) -> str | None:
    """``https://www.Example.com/about`` → ``example.com``: the domain Brandfetch keys a logo on."""
    if not website or not website.strip():
        return None
    value = website.strip()
    host = urlsplit(value if "://" in value else f"https://{value}").hostname
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


async def workspace_logo_urls(
    conn: AsyncConnection, *, workspace_ids: Sequence[str], brandfetch_client_id: str
) -> dict[str, str | None]:
    """Each workspace's logo, from the website given at onboarding (founder, 2026-09-30).

    The sign-up website (``self_serve_provisioning``) first; a workspace set up another way falls
    back to its latest brand onboarding's domain. Brandfetch is never fetched here — the URL is
    a pure function of the domain, embedded by the browser.
    """
    rows = await conn.execute(
        text(
            "SELECT w.workspace_id, COALESCE(p.company_website, o.company_domain) AS website"
            " FROM unnest(CAST(:ids AS text[])) AS w(workspace_id)"
            " LEFT JOIN self_serve_provisioning p ON p.workspace_id = w.workspace_id"
            " LEFT JOIN LATERAL ("
            "   SELECT r.company_domain FROM onboarding_run r"
            "   WHERE r.workspace_id = w.workspace_id"
            "   ORDER BY r.requested_at DESC LIMIT 1"
            " ) o ON true"
        ),
        {"ids": list(workspace_ids)},
    )
    logos: dict[str, str | None] = {}
    for workspace_id, website in rows.all():
        domain = _website_domain(website)
        logos[str(workspace_id)] = (
            brandfetch_logo_url(domain, client_id=brandfetch_client_id) if domain else None
        )
    return logos


def build_auth_router(
    *,
    service: PrincipalService,
    conn_factory: ConnFactory | None = None,
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
    clerk_api: ClerkApi | None = None,
    provision_enabled: bool = True,
    brandfetch_client_id: str = "",
) -> APIRouter:
    router = APIRouter(prefix=AUTH_PREFIX, tags=["authentication"])
    session_dependency = SessionDependency(service)
    principal_dependency = PrincipalDependency(service, permission="project.read")

    @router.get("/session", response_model=SessionResponse)
    async def get_session(
        session: Annotated[AuthenticatedSessionView, Depends(session_dependency)],
        request: Request,
    ) -> SessionResponse:
        if clerk_api is not None and conn_factory is not None:
            async with conn_factory() as conn:
                user = await get_platform_user(conn, session.user_id)
            if user is not None and user.email is None:
                external = await service.external_session(authentication_request(request))
                if external.provider_key == "clerk":
                    try:
                        email = await clerk_api.primary_email(external.provider_subject)
                    except ClerkApiError:
                        log.warning("auth.email_backfill.unavailable")
                    else:
                        if email:
                            async with conn_factory() as conn:
                                await update_platform_user_email(conn, session.user_id, email)
        logos: dict[str, str | None] = {}
        if conn_factory is not None and brandfetch_client_id and session.memberships:
            async with conn_factory() as conn:
                logos = await workspace_logo_urls(
                    conn,
                    workspace_ids=[item.workspace_id for item in session.memberships],
                    brandfetch_client_id=brandfetch_client_id,
                )
        return SessionResponse(
            user_id=session.user_id,
            memberships=tuple(
                SessionMembershipResponse(
                    membership_id=item.membership_id,
                    workspace_id=item.workspace_id,
                    # The database loader's join always carries the name; the fallback covers
                    # only in-memory membership loaders (tests), which read no workspace row.
                    workspace_name=item.workspace_name or item.workspace_id,
                    role_key=item.role_key,
                    permissions=permissions_for_role(item.role_key),
                    workspace_logo_url=logos.get(item.workspace_id),
                )
                for item in session.memberships
            ),
            has_inactive_memberships=session.has_inactive_memberships,
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

    if conn_factory is not None:
        register_invitation_acceptance(
            router, service=service, conn_factory=conn_factory, clerk_api=clerk_api
        )

    if conn_factory is not None and provision_enabled:

        @router.post("/provision", response_model=ProvisionResponse)
        async def provision(
            request: Request, response: Response, body: ProvisionRequest
        ) -> ProvisionResponse:
            """FI-4 D-2: one replay-safe operation from a live provider session to an owned
            workspace with its first brand. Requires authentication but deliberately NOT a
            provisioned identity or membership — this route is how both come to exist.

            Correctness note: this route relies on ``conn_factory`` having commit-on-exit
            semantics (``clue_db.transaction``) — the whole operation is one transaction and
            the 409 path must roll everything back. Wiring ``clue_db.connection`` here would
            silently roll back every successful provision."""
            request_id = request_id_for(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            log.info("auth.provision.started", request_id=request_id)
            try:
                session = await service.external_session(authentication_request(request))
                email = None
                if clerk_api is not None and session.provider_key == "clerk":
                    try:
                        email = await clerk_api.primary_email(session.provider_subject)
                    except ClerkApiError:
                        log.warning("auth.provision.email_unavailable")
                async with conn_factory() as conn:
                    provisioned = await provision_self_serve_workspace(
                        conn,
                        provider_key=session.provider_key,
                        provider_subject=session.provider_subject,
                        company_name=body.company_name,
                        first_name=body.first_name,
                        last_name=body.last_name,
                        job_role=body.job_role,
                        company_website=body.company_website,
                        pages_system_suffix=pages_system_suffix,
                    )
                    if email:
                        await update_platform_user_email(conn, provisioned.user.user_id, email)
            except IdentityConflictError as error:
                log.info(
                    "auth.provision.completed",
                    request_id=request_id,
                    outcome="conflict",
                    created=False,
                )
                raise ProvisioningConflict(str(error)) from error
            except PrincipalError:
                raise
            except Exception:
                log.exception(
                    "auth.provision.failed",
                    request_id=request_id,
                    outcome="unexpected_error",
                )
                raise
            log.info(
                "auth.provision.completed",
                request_id=request_id,
                outcome="created" if provisioned.created else "replayed",
                created=provisioned.created,
                user_id=provisioned.user.user_id,
                workspace_id=provisioned.workspace.workspace_id,
            )
            return ProvisionResponse(
                user_id=provisioned.user.user_id,
                workspace_id=provisioned.workspace.workspace_id,
                brand_id=provisioned.brand.brand_id,
                membership_id=provisioned.membership.membership_id,
                role_key=provisioned.membership.role_key,
                company_name=provisioned.workspace.name,
                company_website=provisioned.company_website,
                first_name=provisioned.user.first_name,
                last_name=provisioned.user.last_name,
                job_role=provisioned.user.job_role,
                created=provisioned.created,
                company_name_ignored=(
                    not provisioned.created
                    and body.company_name is not None
                    and provisioned.workspace.name != body.company_name
                ),
            )

    return router


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str | None = Field(default=None, min_length=1, max_length=512)


def register_invitation_acceptance(
    router: APIRouter,
    *,
    service: PrincipalService,
    conn_factory: ConnFactory,
    clerk_api: ClerkApi | None,
) -> None:
    @router.post("/invitations/accept")
    async def accept_invitation(
        request: Request,
        body: InvitationAcceptRequest,
    ) -> JSONResponse:
        request_id = request_id_for(request)

        def error(status: int, code: str, message: str) -> JSONResponse:
            return JSONResponse(
                status_code=status,
                content={"error": {"code": code, "message": message, "requestId": request_id}},
                headers={REQUEST_ID_HEADER: request_id},
            )

        external = await service.external_session(authentication_request(request))
        if clerk_api is None or external.provider_key != "clerk":
            return error(
                503, "INVITATIONS_UNCONFIGURED", "Invitation acceptance is not configured."
            )
        try:
            profile = await clerk_api.primary_profile(external.provider_subject)
        except ClerkApiError:
            return error(
                503, "INVITATIONS_UNAVAILABLE", "Invitation service is unavailable. Try again."
            )
        if profile is None:
            return error(
                409,
                "VERIFIED_EMAIL_REQUIRED",
                "Verify your primary email before accepting an invitation.",
            )
        try:
            async with conn_factory() as conn:
                accepted: tuple[ProvisionedIdentity, ...]
                if body.token:
                    accepted = (
                        await accept_workspace_invitation(
                            conn,
                            raw_token=body.token,
                            verified_address=profile.email,
                            provider_key=external.provider_key,
                            provider_subject=external.provider_subject,
                            initial_first_name=profile.first_name,
                            initial_last_name=profile.last_name,
                        ),
                    )
                else:
                    accepted = await accept_pending_workspace_invitations(
                        conn,
                        verified_address=profile.email,
                        provider_key=external.provider_key,
                        provider_subject=external.provider_subject,
                        initial_first_name=profile.first_name,
                        initial_last_name=profile.last_name,
                    )
                for item in accepted:
                    await update_platform_user_email(conn, item.user.user_id, profile.email)
        except InvitationAddressMismatch:
            return error(
                409,
                "ADDRESS_MISMATCH",
                "Sign in with the email address this invitation was sent to.",
            )
        except InvitationUnavailableError:
            return error(
                410,
                "INVITATION_UNAVAILABLE",
                "This invitation is expired, revoked, or unavailable.",
            )
        except IdentityConflictError:
            return error(
                409, "INVITATION_UNAVAILABLE", "This account cannot accept the invitation."
            )
        result: dict[str, str | int] = {"accepted": len(accepted)}
        if accepted:
            result.update(
                workspace_id=accepted[0].membership.workspace_id,
                membership_id=accepted[0].membership.membership_id,
            )
        return JSONResponse(content=result, headers={REQUEST_ID_HEADER: request_id})


def install_auth_wiring(
    app: FastAPI,
    *,
    service: PrincipalService,
    conn_factory: ConnFactory | None = None,
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
    clerk_api: ClerkApi | None = None,
    provision_enabled: bool = True,
    brandfetch_client_id: str = "",
) -> None:
    """Install the provider-free session routes and stable auth error envelope.

    ``conn_factory`` additionally enables ``POST /auth/v1/provision`` (FI-4 D-2 self-serve
    onboarding); without it the router serves only the session/principal reads.
    ``pages_system_suffix`` is the suffix a provisioned workspace's system hostname is allocated
    under (custom-domain publishing §4.1) — the composition root passes
    ``settings.pages_system_suffix``."""

    @app.exception_handler(PrincipalError)
    async def _principal_error_handler(request: Request, exc: PrincipalError) -> JSONResponse:
        request_id = request_id_for(request)
        # Every refusal is named in the operator log — the route, the code and, when the refusing
        # step knew it, WHO: the provider subject (a verified Clerk user id) and the Clue user.
        # Added 2026-09-11 after a browser session was bounced to provisioning with a bare 403
        # and nobody could tell which account had been refused, or why. The response body stays
        # the stable envelope below; the subject never leaves the log.
        log.warning(
            "auth.principal.refused",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            error_code=exc.code,
            status=exc.status_code,
            subject=exc.subject,
            user_id=exc.user_id,
        )
        if request.url.path == f"{AUTH_PREFIX}/provision":
            log.info(
                "auth.provision.completed",
                request_id=request_id,
                outcome="refused",
                created=False,
                error_code=exc.code,
                status=exc.status_code,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "requestId": request_id,
                }
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    app.include_router(
        build_auth_router(
            service=service,
            conn_factory=conn_factory,
            pages_system_suffix=pages_system_suffix,
            clerk_api=clerk_api,
            provision_enabled=provision_enabled,
            brandfetch_client_id=brandfetch_client_id,
        )
    )


__all__ = [
    "AUTH_PREFIX",
    "LOCAL_SUBJECT_HEADER",
    "PrincipalDependency",
    "SessionDependency",
    "WORKSPACE_HEADER",
    "authentication_request",
    "authenticated_route_resolvers",
    "build_auth_router",
    "build_principal_service",
    "install_auth_wiring",
    "principal_from_request",
    "request_id_for",
    "require_principal",
]
