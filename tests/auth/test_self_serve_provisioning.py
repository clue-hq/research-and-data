"""FI-4 slice 1: the D-2 self-serve provisioning operation and its HTTP route."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.auth_wiring import install_auth_wiring
from clue_auth import (
    DatabaseAuthorizer,
    DatabaseIdentityResolver,
    DatabaseMembershipLoader,
    LocalFixtureAuthenticator,
    PrincipalService,
    erase_platform_user,
    get_platform_user,
    identity_bundle,
    link_auth_identity,
    provision_self_serve_workspace,
    provision_workspace_owner,
)
from clue_auth.errors import IdentityConflictError, ProvisioningValidationError
from clue_auth.providers import ClerkAuthenticator, ClerkJwtConfig
from clue_auth.store import suspend_platform_user, suspend_workspace_membership

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_auth_db")

PROFILE = {
    "first_name": "Aakash",
    "last_name": "Shrivastava",
    "job_role": "Founder",
    "company_name": "Insight Health",
    "company_website": "https://insight.health",
}


def test_provision_creates_workspace_brand_owner_and_profile() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            result = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="self-serve-subject-1",
                **PROFILE,
            )
            assert result.created is True
            assert result.workspace.name == "Insight Health"
            assert result.brand.name == "Insight Health"
            assert result.brand.workspace_id == result.workspace.workspace_id
            assert result.membership.role_key == "owner"
            assert result.membership.status == "active"
            assert result.user.first_name == "Aakash"
            assert result.user.last_name == "Shrivastava"
            assert result.user.job_role == "Founder"
            assert result.user.display_name == "Aakash Shrivastava"
            assert result.company_website == "https://insight.health"

    run_async(scenario())


def test_provision_replay_returns_the_same_workspace_and_brand() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="self-serve-subject-2",
                **PROFILE,
            )
            replay = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="self-serve-subject-2",
                **{**PROFILE, "first_name": "Aakash-Corrected"},
            )
            assert replay.created is False
            assert replay.workspace.workspace_id == first.workspace.workspace_id
            assert replay.brand.brand_id == first.brand.brand_id
            assert replay.membership.membership_id == first.membership.membership_id
            # Profile writes carry PUT semantics even on replay (the user's own data)...
            assert replay.user.first_name == "Aakash-Corrected"
            # ...but exactly one workspace exists for the company name.
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM workspace WHERE name = 'Insight Health'"),
                )
            ).scalar_one()
            assert count == 1

    run_async(scenario())


def test_second_identity_for_the_same_user_replays_the_same_workspace() -> None:
    """Adversarial finding 3: idempotency keys on the durable human, not the identity row."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="multi-identity-subject",
                **PROFILE,
            )
            await link_auth_identity(
                conn,
                user_id=first.user.user_id,
                provider_key="google",
                provider_subject="multi-identity-google",
            )
            replay = await provision_self_serve_workspace(
                conn,
                provider_key="google",
                provider_subject="multi-identity-google",
                **PROFILE,
            )
            assert replay.created is False
            assert replay.workspace.workspace_id == first.workspace.workspace_id

    run_async(scenario())


def test_provision_refuses_a_user_who_already_belongs_to_a_workspace() -> None:
    """Adversarial finding 3b: an operator-path or invited user gets no second workspace."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await provision_workspace_owner(
                conn,
                workspace_name="Existing Co",
                provider_key="clerk",
                provider_subject="legacy-owner-subject",
            )
            assert owner.membership.status == "active"
            with pytest.raises(IdentityConflictError):
                await provision_self_serve_workspace(
                    conn,
                    provider_key="clerk",
                    provider_subject="legacy-owner-subject",
                    **PROFILE,
                )

    run_async(scenario())


def test_replay_updates_the_company_website_and_refuses_inactive_membership() -> None:
    """Adversarial findings 4 and 6: website corrections stick; dead memberships fail loud."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="website-fix-subject",
                **PROFILE,
            )
            corrected = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="website-fix-subject",
                **{**PROFILE, "company_website": "https://insight-health.com"},
            )
            assert corrected.created is False
            assert corrected.company_website == "https://insight-health.com"
            await suspend_workspace_membership(conn, first.membership.membership_id)
            with pytest.raises(IdentityConflictError):
                await provision_self_serve_workspace(
                    conn,
                    provider_key="clerk",
                    provider_subject="website-fix-subject",
                    **PROFILE,
                )

    run_async(scenario())


def test_a_typed_company_name_wins_over_the_website() -> None:
    """Precedence: what the human typed names the workspace, even when a website could."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            result = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="typed-name-subject",
                **{**PROFILE, "company_name": "Insight Health", "company_website": "acme.com"},
            )
            assert result.workspace.name == "Insight Health"
            assert result.brand.name == "Insight Health"

    run_async(scenario())


def test_a_blank_company_name_is_named_from_the_website() -> None:
    """No name typed: the shared canonical rule names the workspace AND its first brand."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            result = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="website-name-subject",
                **{
                    **PROFILE,
                    "company_name": "   ",
                    "company_website": "https://www.acme-health.com",
                },
            )
            assert result.workspace.name == "Acme Health"
            assert result.brand.name == "Acme Health"

    run_async(scenario())


def test_neither_a_name_nor_a_nameable_website_is_refused() -> None:
    """A workspace is never provisioned nameless — and never named after its id."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(ProvisioningValidationError) as refused:
                await provision_self_serve_workspace(
                    conn,
                    provider_key="clerk",
                    provider_subject="nameless-subject",
                    **{**PROFILE, "company_name": None, "company_website": None},
                )
            assert refused.value.code == "COMPANY_NAME_REQUIRED"
            assert refused.value.status_code == 422

            # A website that names nothing (an IP literal) is no better than no website.
            with pytest.raises(ProvisioningValidationError):
                await provision_self_serve_workspace(
                    conn,
                    provider_key="clerk",
                    provider_subject="nameless-subject-2",
                    **{**PROFILE, "company_name": "", "company_website": "https://192.168.1.1"},
                )

    run_async(scenario())


def test_whitespace_only_profile_values_are_refused_by_the_database() -> None:
    """Adversarial finding 8: the CHECKs use a non-whitespace regex, not space-only btrim."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "INSERT INTO platform_user (user_id, first_name) "
                        "VALUES ('usr_ws_probe', E'\\t')"
                    ),
                )

    run_async(scenario())


def test_provision_refuses_a_suspended_user() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="self-serve-subject-3",
                **PROFILE,
            )
            await suspend_platform_user(conn, first.user.user_id)
            with pytest.raises(IdentityConflictError):
                await provision_self_serve_workspace(
                    conn,
                    provider_key="clerk",
                    provider_subject="self-serve-subject-3",
                    **PROFILE,
                )

    run_async(scenario())


def test_erasure_clears_the_new_profile_fields() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            result = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="self-serve-subject-4",
                **PROFILE,
            )
            bundle_before = await identity_bundle(conn, result.user.user_id)
            assert bundle_before is not None
            assert bundle_before.self_serve_provisionings[0].company_website == (
                "https://insight.health"
            )
            erasure = await erase_platform_user(conn, result.user.user_id)
            assert erasure.provisioning_websites_erased == 1
            erased = await get_platform_user(conn, result.user.user_id)
            assert erased is not None
            assert erased.display_name is None
            assert erased.first_name is None
            assert erased.last_name is None
            assert erased.job_role is None
            assert erased.status == "disabled"
            bundle_after = await identity_bundle(conn, result.user.user_id)
            assert bundle_after is not None
            assert bundle_after.self_serve_provisionings[0].company_website is None

    run_async(scenario())


def test_provision_route_is_absent_without_conn_factory_and_flag() -> None:
    """The conditional registration is a guarantee, not an accident (review finding 5)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

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
                absent = await client.post(
                    "/auth/v1/provision",
                    json=dict(PROFILE, **{"job_role": "Founder"}),
                    headers={"X-Clue-Local-Auth-Subject": "absent-route-subject"},
                )
                assert absent.status_code == 404

    run_async(scenario())


def test_session_read_reports_inactive_memberships() -> None:
    """Lost-access users are distinguishable from never-provisioned users (ruling FE7)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="local_fixture",
                provider_subject="revoked-subject",
                **PROFILE,
            )
            from clue_auth.store import revoke_workspace_membership

            await revoke_workspace_membership(conn, provisioned.membership.membership_id)
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
                session = await client.get(
                    "/auth/v1/session",
                    headers={"X-Clue-Local-Auth-Subject": "revoked-subject"},
                )
                assert session.status_code == 200
                payload = session.json()
                assert payload["memberships"] == []
                assert payload["has_inactive_memberships"] is True

    run_async(scenario())


def test_provision_route_end_to_end_with_replay_and_errors() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            service = PrincipalService(
                authenticator=LocalFixtureAuthenticator(),
                identity_resolver=DatabaseIdentityResolver(conn_factory=conn_factory),
                authorizer=DatabaseAuthorizer(conn_factory=conn_factory),
                memberships_for_user=DatabaseMembershipLoader(conn_factory=conn_factory),
            )
            app = FastAPI()
            install_auth_wiring(app, service=service, conn_factory=conn_factory)
            body = {
                "first_name": "Aakash",
                "last_name": "Shrivastava",
                "job_role": "Founder",
                "company_name": "Insight Health",
                "company_website": "https://insight.health",
            }
            headers = {
                "X-Clue-Local-Auth-Subject": "route-subject-1",
                "X-Request-Id": "provision-route-request-1",
            }
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                unauthenticated = await client.post("/auth/v1/provision", json=body)
                assert unauthenticated.status_code == 401
                assert unauthenticated.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

                created = await client.post("/auth/v1/provision", json=body, headers=headers)
                assert created.status_code == 200
                assert created.headers["X-Request-Id"] == "provision-route-request-1"
                first = created.json()
                assert first["created"] is True
                assert first["workspace_id"].startswith("ws_")
                assert first["brand_id"].startswith("brd_")
                assert first["role_key"] == "owner"
                assert first["job_role"] == "Founder"
                assert first["company_name_ignored"] is False

                replay = await client.post("/auth/v1/provision", json=body, headers=headers)
                assert replay.status_code == 200
                second = replay.json()
                assert second["created"] is False
                assert second["workspace_id"] == first["workspace_id"]
                assert second["brand_id"] == first["brand_id"]
                assert second["company_name_ignored"] is False

                # A corrected company name on replay is not silently swallowed: the workspace
                # name stays fixed and the divergence is flagged (review ruling 2026-08-12).
                renamed = await client.post(
                    "/auth/v1/provision",
                    json={**body, "company_name": "Insight Health Corrected"},
                    headers=headers,
                )
                assert renamed.status_code == 200
                third = renamed.json()
                assert third["company_name"] == "Insight Health"
                assert third["company_name_ignored"] is True

                # A blank company name is no longer a validation error: the website names the
                # workspace. (This subject already owns one, so the call replays and the
                # recorded name stands — nothing was submitted to ignore.)
                blank = await client.post(
                    "/auth/v1/provision",
                    json={**body, "company_name": "   "},
                    headers=headers,
                )
                assert blank.status_code == 200
                assert blank.json()["company_name"] == "Insight Health"
                assert blank.json()["company_name_ignored"] is False

                # Neither a typed name nor a nameable website: refused on the wire with the
                # code, before the replay read — a workspace is never provisioned nameless.
                nameless = await client.post(
                    "/auth/v1/provision",
                    json={**body, "company_name": "", "company_website": None},
                    headers=headers,
                )
                assert nameless.status_code == 422
                assert nameless.json()["error"]["code"] == "COMPANY_NAME_REQUIRED"
                assert nameless.json()["error"]["requestId"] == nameless.headers["X-Request-Id"]

                # The freshly provisioned identity now serves a normal session read, and the
                # session names every workspace it offers.
                session = await client.get("/auth/v1/session", headers=headers)
                assert session.status_code == 200
                memberships = session.json()["memberships"]
                assert [m["workspace_id"] for m in memberships] == [first["workspace_id"]]
                assert memberships[0]["role_key"] == "owner"
                assert memberships[0]["workspace_name"] == "Insight Health"

                await suspend_platform_user(conn, first["user_id"])
                conflicted = await client.post("/auth/v1/provision", json=body, headers=headers)
                assert conflicted.status_code == 409
                assert conflicted.json()["error"]["code"] == "PROVISIONING_CONFLICT"

                bad_website = await client.post(
                    "/auth/v1/provision",
                    json={**body, "company_website": "file:///etc/passwd"},
                    headers=headers,
                )
                assert bad_website.status_code == 422

    run_async(scenario())


def test_real_clerk_session_token_provisions_the_internal_identity_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live composition seam: signed Clerk-shaped JWT -> Clue-owned relational ids."""

    logged: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def info(self, event: str, **fields: object) -> None:
            logged.append((event, fields))

        def exception(self, event: str, **fields: object) -> None:
            logged.append((event, fields))

    monkeypatch.setattr("clue_api.auth_wiring.log", RecordingLogger())

    async def scenario() -> None:
        issuer = "https://clerk.provisioning.test"
        authorized_party = "http://localhost:3000"
        key_id = "provisioning-test-key"
        provider_subject = "user_clerk_provisioning_composition"
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk: dict[str, Any] = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
        jwk.update({"kid": key_id, "alg": "RS256", "use": "sig"})

        def jwks(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"keys": [jwk]})

        authenticator = ClerkAuthenticator(
            ClerkJwtConfig(
                jwks_url=f"{issuer}/.well-known/jwks.json",
                issuer=issuer,
                authorized_parties=(authorized_party,),
            ),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(jwks)),
        )
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "iss": issuer,
                "sub": provider_subject,
                "sid": "session_clerk_provisioning_composition",
                "iat": int((now - timedelta(seconds=1)).timestamp()),
                "nbf": int((now - timedelta(seconds=1)).timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
                "azp": authorized_party,
                "sts": "active",
            },
            private,
            algorithm="RS256",
            headers={"kid": key_id, "typ": "JWT"},
        )

        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            service = PrincipalService(
                authenticator=authenticator,
                identity_resolver=DatabaseIdentityResolver(conn_factory=conn_factory),
                authorizer=DatabaseAuthorizer(conn_factory=conn_factory),
                memberships_for_user=DatabaseMembershipLoader(conn_factory=conn_factory),
            )
            app = FastAPI()
            install_auth_wiring(app, service=service, conn_factory=conn_factory)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                created = await client.post(
                    "/auth/v1/provision",
                    json={
                        "first_name": "Onboarding",
                        "last_name": "Test",
                        "job_role": "Founder",
                        "company_name": "Insight Health",
                        "company_website": "https://insighthealth.ai",
                    },
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Request-Id": "clerk-composition-request-1",
                    },
                )
                assert created.status_code == 200
                assert created.headers["X-Request-Id"] == "clerk-composition-request-1"
                payload = created.json()
                assert payload["created"] is True

                principal = await client.get(
                    "/auth/v1/principal",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Clue-Workspace-Id": payload["workspace_id"],
                    },
                )
                assert principal.status_code == 200
                assert principal.json()["user_id"] == payload["user_id"]
                assert principal.json()["workspace_id"] == payload["workspace_id"]

            bundle = await identity_bundle(conn, payload["user_id"])
            assert bundle is not None
            assert len(bundle.auth_identities) == 1
            assert bundle.auth_identities[0].provider_key == "clerk"
            assert bundle.auth_identities[0].provider_subject == provider_subject
            assert len(bundle.memberships) == 1
            assert bundle.memberships[0].workspace_id == payload["workspace_id"]
            assert bundle.memberships[0].role_key == "owner"
            assert len(bundle.self_serve_provisionings) == 1
            assert bundle.self_serve_provisionings[0].workspace_id == payload["workspace_id"]

            assert logged == [
                (
                    "auth.provision.started",
                    {"request_id": "clerk-composition-request-1"},
                ),
                (
                    "auth.provision.completed",
                    {
                        "request_id": "clerk-composition-request-1",
                        "outcome": "created",
                        "created": True,
                        "user_id": payload["user_id"],
                        "workspace_id": payload["workspace_id"],
                    },
                ),
            ]
            serialized_log = repr(logged)
            assert provider_subject not in serialized_log
            assert token not in serialized_log
            assert "onboarding+" not in serialized_log

    run_async(scenario())
