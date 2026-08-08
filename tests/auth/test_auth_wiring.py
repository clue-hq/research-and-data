"""B2 FastAPI dependency/error contract over a real Clue identity fixture."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
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
    create_workspace_membership,
    link_auth_identity,
)
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
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                missing = await client.get("/auth/v1/session")
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
            assert session.status_code == 200
            assert session.json()["user_id"] == user.user_id
            assert session.json()["memberships"][0]["membership_id"] == membership.membership_id
            assert principal.status_code == 200
            assert principal.json()["workspace_id"] == workspace.workspace_id
            assert "api-subject" not in principal.text
            assert "local_fixture" not in principal.text
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"

    run_async(scenario())
