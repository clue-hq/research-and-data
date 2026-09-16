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
