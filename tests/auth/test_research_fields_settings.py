"""Research fields API: real authorization, registry persistence and error contracts."""

import httpx
import pytest

from clue_auth.store import create_platform_user, create_workspace_membership, link_auth_identity
from clue_research.claimstore import load_core_pack, register_workspace_research_field

from .conftest import rollback_conn, run_async
from .test_settings_integration import build_app, headers, seed

pytestmark = pytest.mark.usefixtures("require_auth_db")
PATH = "/frontend/v1/settings/research-fields"


def test_research_field_round_trip_and_platform_protection():
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await load_core_pack(conn)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [])),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id),
            ) as client:
                response = await client.post(
                    PATH,
                    json={
                        "entity": "accounts",
                        "label": "Uses CRM",
                        "description": "Find their current CRM.",
                    },
                )
                assert response.status_code == 201, response.text
                row = response.json()
                assert row["created_by"] == "Ada Lovelace"
                assert row["key"] == "account.uses_crm" and row["origin"] == "workspace"
                assert (await client.get(PATH, params={"entity": "accounts"})).json()["rows"][
                    -1
                ] == row
                duplicate = await client.post(
                    PATH,
                    json={
                        "entity": "accounts",
                        "label": "Uses CRM",
                        "description": "Other instruction",
                    },
                )
                assert (
                    duplicate.status_code == 409
                    and duplicate.json()["error"]["code"] == "KEY_TAKEN"
                )
                bad = await client.post(
                    PATH, json={"entity": "accounts", "label": "!!!", "description": "Find."}
                )
                assert bad.status_code == 400
                changed = await client.patch(
                    f"{PATH}/{row['key']}", json={"description": "Find cited evidence."}
                )
                assert changed.status_code == 200 and changed.json()["label"] == row["label"]
                assert (
                    await client.patch(f"{PATH}/core.industry", json={"label": "Changed"})
                ).status_code == 409
                assert (await client.delete(f"{PATH}/{row['key']}")).status_code == 200
                assert all(
                    r["key"] != row["key"]
                    for r in (await client.get(PATH, params={"entity": "accounts"})).json()["rows"]
                )
                assert (
                    await client.patch(f"{PATH}/{row['key']}", json={"label": "Restore"})
                ).status_code == 404

    run_async(scenario())


@pytest.mark.parametrize("role", ["owner", "admin", "operator", "viewer"])
def test_research_field_permissions(role):
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn, user_id=user.user_id, provider_key="clerk", provider_subject="reader"
            )
            await create_workspace_membership(
                conn, workspace_id=owner.workspace.workspace_id, user_id=user.user_id, role_key=role
            )
            existing = await register_workspace_research_field(
                conn,
                workspace_id=owner.workspace.workspace_id,
                entity="contacts",
                label="Existing field",
                description="Existing instruction",
                created_by="human:test",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [])),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id, "reader"),
            ) as client:
                assert (await client.get(PATH, params={"entity": "contacts"})).status_code == 200
                result = await client.post(
                    PATH,
                    json={
                        "entity": "contacts",
                        "label": "Public talk",
                        "description": "Find an attributed talk.",
                    },
                )
                assert result.status_code == (201 if role in ("owner", "admin") else 403), (
                    result.text
                )
                key = existing.field_def.field_key
                expected = 200 if role in ("owner", "admin") else 403
                assert (
                    await client.patch(f"{PATH}/{key}", json={"label": "Edited"})
                ).status_code == expected
                assert (await client.delete(f"{PATH}/{key}")).status_code == expected

    run_async(scenario())


def test_research_field_payload_validation_and_authenticated_workspace_isolation():
    from tests._workspace import seed_workspace

    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            ws = owner.workspace.workspace_id
            other = await seed_workspace(conn, "research-fields-api-neighbor")
            await create_workspace_membership(
                conn, workspace_id=other, user_id=owner.user.user_id, role_key="admin"
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [])),
                base_url="http://test",
                headers=headers(ws),
            ) as client:
                body = {"entity": "accounts", "label": "Custom field", "description": "Find it."}
                for extra in (
                    {"workspace_id": other},
                    {"created_by": "someone"},
                    {"value_type": "string"},
                ):
                    assert (await client.post(PATH, json={**body, **extra})).status_code == 422
                created = await client.post(PATH, json=body)
                assert created.status_code == 201
                key = created.json()["key"]
                for patch in ({"key": "account.changed"}, {"label": None}, {"description": " "}):
                    assert (await client.patch(f"{PATH}/{key}", json=patch)).status_code in (
                        400,
                        422,
                    )
                assert (await client.get(PATH, params={"entity": "projects"})).status_code == 422
                neighbor = await client.get(
                    PATH, params={"entity": "accounts"}, headers=headers(other)
                )
                assert neighbor.status_code == 200
                assert all(row["key"] != key for row in neighbor.json()["rows"])
                assert (
                    await client.patch(
                        f"{PATH}/{key}", json={"label": "Crossed"}, headers=headers(other)
                    )
                ).status_code == 404
                assert (
                    await client.delete(f"{PATH}/{key}", headers=headers(other))
                ).status_code == 404
                contacts = await client.get(PATH, params={"entity": "contacts"})
                assert all(row["key"] != key for row in contacts.json()["rows"])

    run_async(scenario())


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_research_writes_recheck_membership_after_principal_resolution(monkeypatch, method):
    from sqlalchemy import text

    from clue_api.frontend_read import research_fields

    original = research_fields.lock_manager

    async def remove_before_transaction_check(conn, principal, permission):
        await conn.execute(
            text(
                "UPDATE workspace_membership SET status='revoked', revoked_at=now() "
                "WHERE membership_id=:id"
            ),
            {"id": principal.membership_id},
        )
        await original(conn, principal, permission)

    monkeypatch.setattr(research_fields, "lock_manager", remove_before_transaction_check)

    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn, user_id=user.user_id, provider_key="clerk", provider_subject="admin"
            )
            await create_workspace_membership(
                conn,
                workspace_id=owner.workspace.workspace_id,
                user_id=user.user_id,
                role_key="admin",
            )
            field = await register_workspace_research_field(
                conn,
                workspace_id=owner.workspace.workspace_id,
                entity="accounts",
                label="Field",
                description="Find.",
                created_by="human:test",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=build_app(conn, [])),
                base_url="http://test",
                headers=headers(owner.workspace.workspace_id, "admin"),
            ) as client:
                path = PATH if method == "POST" else f"{PATH}/{field.field_def.field_key}"
                body = (
                    {"entity": "accounts", "label": "Other", "description": "Find."}
                    if method == "POST"
                    else {"label": "Edited"}
                )
                response = await client.request(
                    method, path, **({"json": body} if method != "DELETE" else {})
                )
                assert response.status_code == 403, response.text
                assert response.json()["error"]["code"] == "PERMISSION_REQUIRED"

    run_async(scenario())
