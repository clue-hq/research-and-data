"""B2 FastAPI dependency/error contract over a real Clue identity fixture."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.auth_wiring import install_auth_wiring
from clue_auth import (
    DatabaseAuthorizer,
    DatabaseIdentityResolver,
    DatabaseMembershipLoader,
    LocalFixtureAuthenticator,
    PrincipalService,
    create_platform_user,
    link_auth_identity,
)
from clue_auth.store import create_workspace_membership
from clue_spine import create_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_auth_db")


def test_session_and_principal_routes_expose_internal_values_and_stable_errors() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            workspace = await create_workspace(conn, name="API auth workspace")
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="api-subject",
            )
            membership = await create_workspace_membership(
                conn,
                workspace_id=workspace.workspace_id,
                user_id=user.user_id,
                role_key="operator",
            )
            service = PrincipalService(
                authenticator=LocalFixtureAuthenticator(),
                identity_resolver=DatabaseIdentityResolver(conn_factory=conn_factory),
                authorizer=DatabaseAuthorizer(conn_factory=conn_factory),
                memberships_for_user=DatabaseMembershipLoader(conn_factory=conn_factory),
            )
            app = FastAPI()
            install_auth_wiring(app, service=service)
            transport = ASGITransport(app=app)
            with structlog.testing.capture_logs() as events:
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    missing = await client.get("/auth/v1/session")
                    unknown = await client.get(
                        "/auth/v1/session",
                        headers={"X-Clue-Local-Auth-Subject": "nobody-we-know"},
                    )
                    session = await client.get(
                        "/auth/v1/session",
                        headers={"X-Clue-Local-Auth-Subject": "api-subject"},
                    )
                    principal = await client.get(
                        "/auth/v1/principal",
                        headers={
                            "X-Clue-Local-Auth-Subject": "api-subject",
                            "X-Clue-Workspace-Id": workspace.workspace_id,
                        },
                    )
                    forbidden = await client.get(
                        "/auth/v1/principal",
                        headers={
                            "X-Clue-Local-Auth-Subject": "api-subject",
                            "X-Clue-Workspace-Id": "ws_not_a_member",
                        },
                    )

            assert missing.status_code == 401
            assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
            assert missing.json()["error"]["requestId"] == missing.headers["X-Request-Id"]
            assert session.status_code == 200
            assert session.json()["user_id"] == user.user_id
            assert session.json()["memberships"][0]["membership_id"] == membership.membership_id
            # A user picks a workspace by its name; the id never has to stand in for one.
            assert session.json()["memberships"][0]["workspace_name"] == "API auth workspace"
            assert principal.status_code == 200
            assert principal.json()["workspace_id"] == workspace.workspace_id
            assert "api-subject" not in principal.text
            assert "local_fixture" not in principal.text
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"
            # A verified-but-unlinked subject is refused 403 and the response never names it…
            assert unknown.status_code == 403
            assert unknown.json()["error"]["code"] == "IDENTITY_NOT_PROVISIONED"
            assert "nobody-we-know" not in unknown.text
            # …but the operator log does (2026-09-11): every refusal is logged with the route,
            # the code and who was refused, so a bounced browser session is diagnosable.
            refusals = [e for e in events if e["event"] == "auth.principal.refused"]
            by_code = {(e["error_code"], e["path"]): e for e in refusals}
            assert by_code[("AUTHENTICATION_REQUIRED", "/auth/v1/session")]["subject"] is None
            assert by_code[("IDENTITY_NOT_PROVISIONED", "/auth/v1/session")]["subject"] == (
                "nobody-we-know"
            )
            assert by_code[("WORKSPACE_FORBIDDEN", "/auth/v1/principal")]["user_id"] == (
                user.user_id
            )

    run_async(scenario())


def test_each_session_membership_carries_its_workspaces_logo() -> None:
    """The workspace switcher shows the company's logo (founder, 2026-09-30).

    The logo is Brandfetch's Logo API mark for the website given at onboarding: the sign-up
    website first, else the brand onboarding's domain; a workspace with neither has none (the
    switcher keeps its initials). Brandfetch URLs are embed-only, a pure function of the domain.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            from sqlalchemy import text

            from clue_spine import create_brand

            user = await create_platform_user(conn)
            identity = await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="logo-sub",
            )
            signed_up = await create_workspace(conn, name="Signed up")
            onboarded = await create_workspace(conn, name="Onboarded")
            bare = await create_workspace(conn, name="Bare")
            for workspace in (signed_up, onboarded, bare):
                await create_workspace_membership(
                    conn,
                    workspace_id=workspace.workspace_id,
                    user_id=user.user_id,
                    role_key="operator",
                )
            brand = await create_brand(conn, workspace_id=signed_up.workspace_id, name="Signed up")
            await conn.execute(
                text(
                    "INSERT INTO self_serve_provisioning"
                    " (auth_identity_id, user_id, workspace_id, brand_id, company_website)"
                    " VALUES (:identity, :user, :ws, :brand, 'https://www.InsightHealth.ai/about')"
                ),
                {
                    "identity": identity.auth_identity_id,
                    "user": user.user_id,
                    "ws": signed_up.workspace_id,
                    "brand": brand.brand_id,
                },
            )
            onboarded_brand = await create_brand(
                conn, workspace_id=onboarded.workspace_id, name="Onboarded"
            )
            await conn.execute(
                text(
                    "INSERT INTO onboarding_run"
                    " (run_id, workspace_id, brand_id, company_domain, requested_by_user_id)"
                    " VALUES (gen_random_uuid(), :ws, :brand, 'acme.example', :user)"
                ),
                {
                    "ws": onboarded.workspace_id,
                    "brand": onboarded_brand.brand_id,
                    "user": user.user_id,
                },
            )
            service = PrincipalService(
                authenticator=LocalFixtureAuthenticator(),
                identity_resolver=DatabaseIdentityResolver(conn_factory=conn_factory),
                authorizer=DatabaseAuthorizer(conn_factory=conn_factory),
                memberships_for_user=DatabaseMembershipLoader(conn_factory=conn_factory),
            )
            app = FastAPI()
            install_auth_wiring(
                app, service=service, conn_factory=conn_factory, brandfetch_client_id="bf-client"
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                session = await client.get(
                    "/auth/v1/session", headers={"X-Clue-Local-Auth-Subject": "logo-sub"}
                )

            logos = {
                item["workspace_id"]: item["workspace_logo_url"]
                for item in session.json()["memberships"]
            }
            assert logos[signed_up.workspace_id].startswith(
                "https://cdn.brandfetch.io/domain/insighthealth.ai/"
            )
            assert "c=bf-client" in logos[signed_up.workspace_id]
            assert logos[onboarded.workspace_id].startswith(
                "https://cdn.brandfetch.io/domain/acme.example/"
            )
            assert logos[bare.workspace_id] is None

    run_async(scenario())
