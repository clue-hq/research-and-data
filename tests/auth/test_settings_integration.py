"""Settings API contracts and lifecycle against an isolated migrated database."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_store import create_run
from clue_api.auth_wiring import authenticated_route_resolvers, install_auth_wiring
from clue_api.frontend_read.app import (
    frontend_read_workspace_resolver,
    install_frontend_read_surface,
)
from clue_api.frontend_read.settings import register_settings_routes
from clue_auth import (
    DatabaseAuthorizer,
    DatabaseIdentityResolver,
    DatabaseMembershipLoader,
    LocalFixtureAuthenticator,
    PrincipalService,
)
from clue_auth.providers.clerk_api import ClerkApi
from clue_auth.provisioning import (
    hash_invitation_token,
    provision_additional_workspace,
    provision_self_serve_workspace,
)
from clue_auth.store import (
    create_platform_user,
    create_workspace_invitation,
    create_workspace_membership,
    erase_platform_user,
    get_platform_user,
    link_auth_identity,
    update_platform_user_email,
)
from clue_config import Settings
from clue_spine import create_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_auth_db")
PREFIX = "/frontend/v1/settings"


class TestAuthenticator(LocalFixtureAuthenticator):
    __test__ = False
    provider_key = "clerk"


def build_app(
    conn: AsyncConnection,
    delivery: list[dict],
    *,
    configured: bool = True,
    provision_enabled: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        async with conn.begin_nested():
            yield conn

    def provider(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            subject = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "primary_email_address_id": "email",
                    "first_name": "Invited",
                    "last_name": "Person",
                    "email_addresses": [
                        {
                            "id": "email",
                            "email_address": f"{subject}@example.com",
                            "verification": {"status": "verified"},
                        }
                    ],
                },
            )
        if request.url.path.endswith("/revoke"):
            delivery.append({"revoked": request.url.path})
            return httpx.Response(200, json={"revoked": True})
        body = json.loads(request.content)
        delivery.append(body)
        address = body["email_address"]
        if address.startswith("existing"):
            return httpx.Response(422, json={"errors": [{"code": "form_identifier_exists"}]})
        if address.startswith("limited"):
            return httpx.Response(429, json={})
        if address.startswith("failed"):
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"id": f"provider_{len(delivery)}"})

    clerk = (
        ClerkApi("test-only-secret", transport=httpx.MockTransport(provider))
        if configured
        else None
    )
    service = PrincipalService(
        authenticator=TestAuthenticator(),
        identity_resolver=DatabaseIdentityResolver(conn_factory=factory),
        authorizer=DatabaseAuthorizer(conn_factory=factory),
        memberships_for_user=DatabaseMembershipLoader(conn_factory=factory),
    )
    app = FastAPI()
    install_auth_wiring(
        app,
        service=service,
        conn_factory=factory,
        clerk_api=clerk,
        provision_enabled=provision_enabled,
    )
    settings = Settings(
        _env_file=None, frontend_read_enabled=False, app_origin="http://localhost:3020"
    )
    install_frontend_read_surface(app, settings=settings, conn_factory=factory)
    router = APIRouter(prefix="/frontend/v1")
    register_settings_routes(router, conn_factory=factory, settings=settings, clerk_api=clerk)
    app.include_router(router)
    workspace, _ = authenticated_route_resolvers(service)
    app.dependency_overrides[frontend_read_workspace_resolver] = workspace
    return app


async def seed(conn: AsyncConnection):
    owner = await provision_self_serve_workspace(
        conn,
        provider_key="clerk",
        provider_subject="owner",
        first_name="Ada",
        last_name="Lovelace",
        job_role="Founder",
        company_name="Settings test",
        company_website="https://example.com",
    )
    await update_platform_user_email(conn, owner.user.user_id, "owner@example.com")
    return owner


def headers(workspace_id: str, subject: str = "owner") -> dict[str, str]:
    return {"X-Clue-Local-Auth-Subject": subject, "X-Clue-Workspace-Id": workspace_id}


def test_profile_patch_clear_preserve_and_email_erasure() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed(conn)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [])),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id),
            ) as client:
                before = (await client.get(f"{PREFIX}/profile")).json()
                assert before["full_name"] == "Ada Lovelace"
                renamed = await client.patch(
                    f"{PREFIX}/profile", json={"full_name": "  Grace Brewster Murray  "}
                )
                assert renamed.status_code == 200, renamed.text
                assert renamed.json()["first_name"] == "Grace"
                assert renamed.json()["last_name"] == "Brewster Murray"
                assert renamed.json()["display_name"] == before["display_name"]
                for value in [None, "  "]:
                    cleared = await client.patch(f"{PREFIX}/profile", json={"display_name": value})
                    assert cleared.json()["display_name"] is None
                one_name = await client.patch(f"{PREFIX}/profile", json={"full_name": "Grace"})
                assert one_name.json()["last_name"] is None
                assert (
                    await client.patch(f"{PREFIX}/profile", json={"job_role": "Changed"})
                ).status_code == 422
            user = await get_platform_user(conn, owner.user.user_id)
            assert user.job_role == "Founder"
            await erase_platform_user(conn, owner.user.user_id)
            user = await get_platform_user(conn, owner.user.user_id)
            assert user.email is None
            assert user.first_name is None

    run_async(scenario())


@pytest.mark.parametrize("role", ["owner", "admin", "operator", "viewer"])
def test_workspace_and_members_permissions(role: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed(conn)
            user = await create_platform_user(conn, display_name="Actor")
            await link_auth_identity(
                conn, user_id=user.user_id, provider_key="clerk", provider_subject="actor"
            )
            actor = await create_workspace_membership(
                conn, workspace_id=owner.workspace.workspace_id, user_id=user.user_id, role_key=role
            )
            outsider = await create_workspace(conn, name="Other workspace")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [])),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id, "actor"),
            ) as client:
                assert (await client.get(f"{PREFIX}/members")).status_code == 200
                response = await client.patch(f"{PREFIX}/workspace", json={"name": "  Renamed  "})
                assert response.status_code == (200 if role in ("owner", "admin") else 403), (
                    response.text
                )
                if role in ("owner", "admin"):
                    assert response.json()["name"] == "Renamed"
                    assert response.json()["website"] == "https://example.com"
                    assert (
                        await client.patch(f"{PREFIX}/workspace", json={"name": " "})
                    ).status_code == 422
                    assert (
                        await client.patch(f"{PREFIX}/workspace", json={"website": "changed"})
                    ).status_code == 400
                    assert (
                        await client.delete(f"{PREFIX}/members/{owner.membership.membership_id}")
                    ).status_code == 409
                    assert (
                        await client.delete(f"{PREFIX}/members/{actor.membership_id}")
                    ).status_code == 409
                    assert (
                        await client.patch(
                            f"{PREFIX}/members/{owner.membership.membership_id}",
                            json={"role": "operator"},
                        )
                    ).status_code == 409
                assert (
                    await client.get(
                        f"{PREFIX}/workspace", headers=headers(outsider.workspace_id, "actor")
                    )
                ).status_code == 403
            assert (
                await conn.scalar(
                    text("SELECT name FROM brand WHERE brand_id = :id"),
                    {"id": owner.brand.brand_id},
                )
                == "Settings test"
            )

    run_async(scenario())


def test_invitation_batch_lifecycle_and_session_acceptance() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed(conn)
            delivery = []
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, delivery)),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id),
            ) as client:
                sent = await client.post(
                    f"{PREFIX}/members/invitations",
                    json={
                        "emails": [
                            "New@Example.com",
                            "existing@example.com",
                            "limited@example.com",
                            "failed@example.com",
                            "invalid",
                            "owner@example.com",
                            "New@Example.com",
                        ],
                        "role": "operator",
                    },
                )
                assert sent.status_code == 200, sent.text
                assert [item["outcome"] for item in sent.json()["outcomes"]] == [
                    "sent",
                    "created_no_email",
                    "rate_limited",
                    "delivery_failed",
                    "invalid",
                    "already_member",
                ]
                duplicate = await client.post(
                    f"{PREFIX}/members/invitations",
                    json={"emails": ["new@example.com"], "role": "operator"},
                )
                assert duplicate.json()["outcomes"][0]["outcome"] == "already_invited"
                token = parse_qs(urlparse(delivery[0]["redirect_url"]).query)["token"][0]
                digest = await conn.scalar(
                    text(
                        "SELECT token_digest FROM workspace_invitation "
                        "WHERE invited_address = 'new@example.com'"
                    )
                )
                assert digest == hash_invitation_token(token) and digest != token
                wrong = await client.post(
                    "/auth/v1/invitations/accept",
                    json={"token": token},
                    headers=headers(owner.workspace.workspace_id, "wrong"),
                )
                assert (
                    wrong.status_code == 409 and wrong.json()["error"]["code"] == "ADDRESS_MISMATCH"
                )
                accepted = await client.post(
                    "/auth/v1/invitations/accept",
                    json={"token": token},
                    headers={"X-Clue-Local-Auth-Subject": "new", "X-Clue-Workspace-Id": ""},
                )
                assert accepted.status_code == 200, accepted.text
                membership_id = accepted.json()["membership_id"]
                invited_profile = await client.get(
                    f"{PREFIX}/profile", headers=headers(owner.workspace.workspace_id, "new")
                )
                assert invited_profile.json()["full_name"] == "Invited Person"
                await client.patch(
                    f"{PREFIX}/profile",
                    json={"full_name": "Chosen Name"},
                    headers=headers(owner.workspace.workspace_id, "new"),
                )
                replay = await client.post(
                    "/auth/v1/invitations/accept",
                    json={"token": token},
                    headers=headers(owner.workspace.workspace_id, "new"),
                )
                assert replay.json() == accepted.json()
                assert (
                    await client.get(
                        f"{PREFIX}/profile", headers=headers(owner.workspace.workspace_id, "new")
                    )
                ).json()["full_name"] == "Chosen Name"
                automatic = await client.post(
                    "/auth/v1/invitations/accept",
                    json={},
                    headers=headers(owner.workspace.workspace_id, "existing"),
                )
                assert automatic.json()["accepted"] == 1
                assert (
                    await client.patch(f"{PREFIX}/members/{membership_id}", json={"role": "admin"})
                ).status_code == 200
                assert (await client.delete(f"{PREFIX}/members/{membership_id}")).status_code == 200
                rows = (await client.get(f"{PREFIX}/members")).json()["rows"]
                removed = next(row for row in rows if row["id"] == membership_id)
                assert removed["state"] == "removed" and removed["email"] == "new@example.com"
                blocked = await client.post(
                    "/auth/v1/invitations/accept",
                    json={"token": token},
                    headers=headers(owner.workspace.workspace_id, "new"),
                )
                assert blocked.status_code == 410
                assert (
                    await client.post(
                        f"{PREFIX}/members/{membership_id}/readmit", json={"role": "operator"}
                    )
                ).status_code == 200
                pending = next(row for row in rows if row["kind"] == "invitation")
                assert (
                    await client.delete(f"{PREFIX}/members/invitations/{pending['id']}")
                ).status_code == 200

    run_async(scenario())


def test_expired_revoked_scope_and_missing_configuration() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed(conn)
            expired = await create_workspace_invitation(
                conn,
                workspace_id=owner.workspace.workspace_id,
                invited_address="expired@example.com",
                role_key="operator",
                token_digest=hash_invitation_token("expired"),
                invited_by_membership_id=owner.membership.membership_id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            await conn.execute(
                text(
                    "UPDATE workspace_invitation SET created_at = now() - interval '2 days', "
                    "expires_at = now() - interval '1 day' WHERE invitation_id = :id"
                ),
                {"id": expired.invitation_id},
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [])),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id, "expired"),
            ) as client:
                response = await client.post(
                    "/auth/v1/invitations/accept", json={"token": "expired"}
                )
                assert response.status_code == 410, response.text
                assert (await client.post("/auth/v1/invitations/accept", json={})).json() == {
                    "accepted": 0
                }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [], configured=False)),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id),
            ) as client:
                assert not (await client.get(f"{PREFIX}/members")).json()["invitations_configured"]
                response = await client.post(
                    f"{PREFIX}/members/invitations",
                    json={"emails": ["nobody@example.com"], "role": "operator"},
                )
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "INVITATIONS_UNCONFIGURED"

    run_async(scenario())


def test_email_backfill_provisioning_and_primary_brand_logo() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await conn.execute(
                text("UPDATE platform_user SET email = NULL WHERE user_id = :id"),
                {"id": owner.user.user_id},
            )
            # Opaque asset ids are resolved through the authenticated design asset seam.
            await conn.execute(
                text(
                    "INSERT INTO design_brand_kit (brand_kit_id, version, workspace_id, brand_id, "
                    "name, approval_status, source, brand_kit_json, "
                    "brand_summary_json, diagnostics_json) "
                    "VALUES ('bk_settings_test', 1, :ws, :brand, 'Test kit', "
                    "'approved', 'uploaded', "
                    "CAST(:kit AS jsonb), '{}', '[]')"
                ),
                {
                    "ws": owner.workspace.workspace_id,
                    "brand": owner.brand.brand_id,
                    "kit": json.dumps(
                        {
                            "assets": {
                                "logos": {
                                    "primary": {"variants": [{"asset_id": "asset_test_logo"}]}
                                }
                            }
                        }
                    ),
                },
            )
            app = build_app(conn, [], provision_enabled=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id),
            ) as client:
                assert (await client.get("/auth/v1/session")).status_code == 200
                user = await get_platform_user(conn, owner.user.user_id)
                assert user.email == "owner@example.com"
                assert (await client.get(f"{PREFIX}/workspace")).json()[
                    "logo_url"
                ] == "/api/clue/design/assets/asset_test_logo/bytes"
                response = await client.post(
                    "/auth/v1/provision",
                    headers=headers("", "provisioned"),
                    json={
                        "first_name": "New",
                        "last_name": "Person",
                        "job_role": "Founder",
                        "company_name": "New workspace",
                        "company_website": "https://example.com",
                    },
                )
                assert response.status_code == 200, response.text
                user = await get_platform_user(conn, response.json()["user_id"])
                assert user.email == "provisioned@example.com"

    run_async(scenario())


def test_operator_workspace_reads_its_website_from_onboarding_and_its_kit_logo() -> None:
    """A workspace an operator added has no signup record, so Settings falls back to the
    latest full onboarding run's domain and to the workspace's approved brand kit."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed(conn)
            added = await provision_additional_workspace(
                conn, email="owner@example.com", company_website="https://acme.example"
            )
            ws = added.workspace.workspace_id
            app = build_app(conn, [])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers(ws),
            ) as client:
                before = (await client.get(f"{PREFIX}/workspace")).json()
                assert before["website"] is None
                assert before["logo_url"] is None
                await create_run(
                    conn,
                    run_id=uuid4(),
                    workspace_id=ws,
                    brand_id=added.brand.brand_id,
                    company_domain="acme.example",
                    requested_by_user_id=owner.user.user_id,
                )
                await conn.execute(
                    text(
                        "INSERT INTO design_brand_kit (brand_kit_id, version, workspace_id, "
                        "brand_id, name, approval_status, source, brand_kit_json, "
                        "brand_summary_json, diagnostics_json) "
                        "VALUES ('bk_operator_test', 1, :ws, :brand, 'Acme kit', 'approved', "
                        "'uploaded', CAST(:kit AS jsonb), '{}', '[]')"
                    ),
                    {
                        "ws": ws,
                        "brand": added.brand.brand_id,
                        "kit": json.dumps(
                            {
                                "assets": {
                                    "logos": {
                                        "primary": {"variants": [{"asset_id": "asset_acme_logo"}]}
                                    }
                                }
                            }
                        ),
                    },
                )
                after = (await client.get(f"{PREFIX}/workspace")).json()
                assert after["website"] == "https://acme.example"
                assert after["logo_url"] == "/api/clue/design/assets/asset_acme_logo/bytes"

    run_async(scenario())
