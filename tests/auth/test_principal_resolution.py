"""B2 external-session -> internal identity -> membership authorization acceptance."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_auth import (
    AuthenticationRequest,
    DatabaseAuthorizer,
    DatabaseIdentityResolver,
    DatabaseMembershipLoader,
    ExternalSession,
    IdentityNotProvisioned,
    LocalFixtureAuthenticator,
    PermissionDenied,
    PrincipalService,
    UserDisabled,
    WorkspaceForbidden,
    create_platform_user,
    create_workspace_membership,
    link_auth_identity,
    suspend_platform_user,
    suspend_workspace_membership,
)
from clue_spine import create_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_auth_db")
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _session(subject: str) -> ExternalSession:
    return ExternalSession(
        provider_key="local_fixture",
        provider_subject=subject,
        session_id=f"local:{subject}",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        authenticated_at=NOW,
    )


def test_resolver_and_authorizer_emit_only_internal_principal_values() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            workspace = await create_workspace(conn, name="Auth workspace")
            user = await create_platform_user(conn, display_name="Auth user")
            mapping = await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="fixture-subject",
            )
            membership = await create_workspace_membership(
                conn,
                workspace_id=workspace.workspace_id,
                user_id=user.user_id,
                role_key="operator",
                now=NOW,
            )
            service = PrincipalService(
                authenticator=LocalFixtureAuthenticator(),
                identity_resolver=DatabaseIdentityResolver(conn_factory=conn_factory),
                authorizer=DatabaseAuthorizer(conn_factory=conn_factory),
                memberships_for_user=DatabaseMembershipLoader(conn_factory=conn_factory),
            )

            principal = await service.principal(
                AuthenticationRequest(local_subject="fixture-subject"),
                workspace_id=workspace.workspace_id,
                permission="thread.write",
            )
            session = await service.session_view(
                AuthenticationRequest(local_subject="fixture-subject")
            )

            assert principal.user_id == user.user_id
            assert principal.membership_id == membership.membership_id
            assert principal.workspace_id == workspace.workspace_id
            assert principal.principal_kind == "human"
            assert mapping.provider_subject not in principal.model_dump_json()
            assert "local_fixture" not in principal.model_dump_json()
            assert session.user_id == user.user_id
            assert session.memberships == (membership,)

    run_async(scenario())


def test_unprovisioned_disabled_cross_workspace_and_permission_cases_are_distinct() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            workspace = await create_workspace(conn, name="Auth workspace")
            other_workspace = await create_workspace(conn, name="Other workspace")
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="viewer-subject",
            )
            membership = await create_workspace_membership(
                conn,
                workspace_id=workspace.workspace_id,
                user_id=user.user_id,
                role_key="viewer",
                now=NOW,
            )
            resolver = DatabaseIdentityResolver(conn_factory=conn_factory)
            authorizer = DatabaseAuthorizer(conn_factory=conn_factory)

            with pytest.raises(IdentityNotProvisioned):
                await resolver.resolve(_session("absent-subject"))
            identity = await resolver.resolve(_session("viewer-subject"))
            with pytest.raises(WorkspaceForbidden):
                await authorizer.require(identity, workspace_id=other_workspace.workspace_id)
            with pytest.raises(PermissionDenied):
                await authorizer.require(
                    identity,
                    workspace_id=workspace.workspace_id,
                    permission="thread.write",
                )

            await suspend_workspace_membership(conn, membership.membership_id, now=NOW)
            with pytest.raises(WorkspaceForbidden):
                await authorizer.require(identity, workspace_id=workspace.workspace_id)
            await suspend_platform_user(conn, user.user_id, now=NOW)
            with pytest.raises(UserDisabled):
                await resolver.resolve(_session("viewer-subject"))

    run_async(scenario())
