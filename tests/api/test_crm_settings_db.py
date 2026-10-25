"""Settings → Integrations: the CRM's routes (R-15.1–R-15.3; plan 2026-10-25 Task 3).

DB-backed and rollback-only, through the real ``/frontend/v1/crm/*`` routes, with Composio a fake
injected through ``app.state.crm_gateway`` (the harness of ``test_frontend_read_crm_db``).
Proves: any member reads the page and revokes a standing permission; only owners and admins open
a connect request, disconnect and set overwrites; the research setup's state follows the Clue
fields registry and the setup cards; a person never reads a CRM API name; a disconnect closes the
connection's open cards, revokes its permissions and deletes Clue's grant at Composio.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from clue_api.agent_gate import KIND_CRM_WRITE_PERMISSION, insert_gate
from clue_api.agent_turn_submission import DERIVATION_CRM_WRITES_FINISHED
from clue_api.crm.clue_fields import (
    CLUE_FIELDS,
    mark_clue_field_gone,
    record_clue_fields,
    record_partial_clue_fields,
)
from clue_api.crm.composio_gateway import ConnectedAccount
from clue_api.crm.write_executor import DISCONNECTED_MESSAGE
from clue_api.crm.writes import insert_grant, insert_proposal
from clue_spine import Project
from tests._workspace import seed_project
from tests.api.test_frontend_read_crm_db import (
    CRM,
    USER_ID,
    FakeComposio,
    _headers,
    _run,
    _waiting_chat,
)
from tests.api.test_lane_d4_agent_gate_db import _seed as _seed_turn
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
)


@pytest.fixture
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_db")

MEMBER = "operator"  # a member without workspace.manage_settings


# --- seeding --------------------------------------------------------------------------------


async def _connection(
    conn: Any,
    project: Project,
    *,
    provider: str = "hubspot",
    status: str = "active",
    external: str | None = "111",
    name: str | None = None,
    account: str = "ca_seeded",
) -> UUID:
    connection_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO workspace_integration_connection (connection_id, workspace_id, provider, "
            "composio_connected_account_id, composio_auth_config_id, status, connected_by_user_id, "
            "external_account_id, external_account_name, disconnected_at) VALUES (:id, :ws, :p, "
            ":account, 'ac', :status, :user, :external, :name, "
            "CASE WHEN :status = 'disconnected' THEN now() END)"
        ),
        {
            "id": connection_id,
            "ws": project.workspace_id,
            "p": provider,
            "account": account,
            "status": status,
            "user": USER_ID,
            "external": external,
            "name": name,
        },
    )
    return connection_id


async def _registry(
    conn: Any, project: Project, connection_id: UUID, *, provider: str = "hubspot", **kw: Any
) -> None:
    fields = kw.pop("fields", CLUE_FIELDS[provider])  # type: ignore[index]
    await record_clue_fields(
        conn,
        connection_id=connection_id,
        workspace_id=project.workspace_id,
        provider=provider,  # type: ignore[arg-type]
        created=fields,
        permission_set_id=None,
        label_type_id=None,
        status=kw.pop("status", "ready"),
    )


async def _setup_card(
    conn: Any,
    project: Project,
    connection_id: UUID,
    *,
    proposal_status: str,
    write_status: str,
    thread_id: str = "thr_setup",
    failure_kind: str | None = None,
    message: str | None = None,
    response: dict[str, Any] | None = None,
    write_kind: str = "clue_fields_setup",
    turn_id: UUID | None = None,
    field: str | None = None,
) -> UUID:
    """A setup card (or with ``write_kind``, a change card) as the propose tools record it."""
    proposal_id = uuid4()
    await insert_proposal(
        conn,
        proposal_id=proposal_id,
        workspace_id=project.workspace_id,
        connection_id=connection_id,
        project_id=project.project_id,
        thread_id=thread_id,
        turn_id=turn_id or uuid4(),
        status=proposal_status,
    )
    await conn.execute(
        text(
            "INSERT INTO crm_write (write_id, proposal_id, workspace_id, connection_id, ordinal, "
            "slug, arguments, kind, object, record_ref, record_label, field, overwrites_person, "
            "reason, scope_key, selected, status, failure_kind, crm_message, crm_response, "
            "idempotency_key) VALUES (:w, :p, :ws, :c, 0, 'SLUG', '{}'::jsonb, :kind, 'company', "
            ":record, 'Acme', :field, false, 'why', :scope, true, :status, :fk, :msg, "
            "CAST(:resp AS jsonb), :key)"
        ),
        {
            "w": uuid4(),
            "p": proposal_id,
            "ws": project.workspace_id,
            "c": connection_id,
            "kind": write_kind,
            "record": None if field is None else "101",
            "field": field,
            "scope": f"kind:{write_kind}" if field is None else f"field:company.{field}",
            "status": write_status,
            "fk": failure_kind,
            "msg": message,
            "resp": None if response is None else json.dumps(response),
            "key": str(uuid4()),
        },
    )
    return proposal_id


async def _integration(client: httpx.AsyncClient, project: Project) -> dict[str, Any]:
    response = await client.get(f"{CRM}/integration", headers=_headers(project))
    assert response.status_code == 200, response.text
    return response.json()


def _statuses(page: dict[str, Any]) -> dict[str, str]:
    return {item["key"]: item["status"] for item in page["research"]["items"]}


_ITEM_KEYS = [
    "company_research_links",
    "contact_profile_links",
    "contact_buying_roles",
    "company_fit",
]


# --- GET /crm/integration and the research states ------------------------------------------


def test_not_connected_page(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        del conn
        page = await _integration(client, project)
        assert page["connection"] is None
        assert page["canManage"] is True
        assert page["permissions"] == []
        assert page["overwrites"] == "ask"
        research = page["research"]
        assert research["state"] == "not_connected"
        assert (research["failedField"], research["reason"], research["reviewChat"]) == (
            None,
            None,
            None,
        )
        assert [item["key"] for item in research["items"]] == _ITEM_KEYS
        assert set(_statuses(page).values()) == {"pending"}
        # Nothing was connected from a chat: the most recently active project.
        assert page["askClueProjectId"] == project.project_id

    _run(tmp_path, "owner", body)


def test_integration_shows_the_hubspot_connection(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        await _connection(conn, project, external="4455")
        page = await _integration(client, project)
        name = await conn.scalar(
            text("SELECT display_name FROM platform_user WHERE user_id = :id"), {"id": USER_ID}
        )
        connection = page["connection"]
        assert connection["provider"] == "hubspot"
        assert connection["status"] == "active"
        assert connection["accountLabel"] == "Portal 4455"
        assert connection["connectedByName"] == name
        assert connection["connectedAt"]
        items = {item["key"]: item for item in page["research"]["items"]}
        assert items["company_research_links"] == {
            "key": "company_research_links",
            "title": "Company research links",
            "description": "A link on each company record to its research in Clue.",
            "status": "pending",
        }
        assert items["company_fit"]["description"] == (
            "High, Medium, or Low fit, saved in the “Clue fit level” field."
        )

    _run(tmp_path, "owner", body)


def test_integration_labels_a_salesforce_org_and_an_unnamed_portal(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(
            conn, project, provider="salesforce", external="00DORG", name="Acme Robotics"
        )
        page = await _integration(client, project)
        assert page["connection"]["accountLabel"] == "Acme Robotics"
        items = {item["key"]: item for item in page["research"]["items"]}
        assert items["company_research_links"]["description"] == (
            "A link on each account record to its research in Clue."
        )
        await conn.execute(
            text(
                "UPDATE workspace_integration_connection SET external_account_name = NULL "
                "WHERE connection_id = :id"
            ),
            {"id": connection_id},
        )
        assert (await _integration(client, project))["connection"][
            "accountLabel"
        ] == "Salesforce organization"
        await conn.execute(
            text(
                "UPDATE workspace_integration_connection SET provider = 'hubspot', "
                "external_account_id = NULL WHERE connection_id = :id"
            ),
            {"id": connection_id},
        )
        assert (await _integration(client, project))["connection"][
            "accountLabel"
        ] == "HubSpot portal"

    _run(tmp_path, "owner", body)


def test_approval_needed_without_a_pending_card(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        await _connection(conn, project)
        research = (await _integration(client, project))["research"]
        assert research["state"] == "approval_needed"
        assert research["reviewChat"] is None

    _run(tmp_path, "viewer", body)


def test_approval_needed_when_ready_lacks_a_current_field(tmp_path: Any) -> None:
    """A setup ``ready`` before Clue fit level existed is not ready (Task 1 ruling)."""

    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        older = [f for f in CLUE_FIELDS["hubspot"] if f.key != "clue_fit_level"]
        await _registry(conn, project, connection_id, fields=older)
        page = await _integration(client, project)
        assert page["research"]["state"] == "approval_needed"
        assert _statuses(page)["company_fit"] == "pending"
        assert _statuses(page)["company_research_links"] == "created"

    _run(tmp_path, "owner", body)


def test_approval_needed_with_a_pending_card_names_its_chat(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        await _setup_card(
            conn,
            project,
            connection_id,
            proposal_status="awaiting_permission",
            write_status="proposed",
            thread_id="thr_waiting_setup",
        )
        research = (await _integration(client, project))["research"]
        assert research["state"] == "approval_needed"
        assert research["reviewChat"] == {
            "projectId": project.project_id,
            "threadId": "thr_waiting_setup",
        }

    _run(tmp_path, "owner", body)


def test_preparing_while_the_setup_is_queued(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        await _setup_card(
            conn, project, connection_id, proposal_status="queued", write_status="queued"
        )
        research = (await _integration(client, project))["research"]
        assert research["state"] == "preparing"
        assert research["reviewChat"] is None

    _run(tmp_path, "owner", body)


def test_ready_when_every_field_is_set_up(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        await _registry(conn, project, connection_id)
        page = await _integration(client, project)
        assert page["research"]["state"] == "ready"
        assert set(_statuses(page).values()) == {"created"}

    _run(tmp_path, "owner", body)


def test_needs_attention_names_the_missing_field(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        await _registry(conn, project, connection_id)
        await mark_clue_field_gone(
            conn, connection_id=connection_id, obj="company", crm_name="clue_research_link"
        )
        page = await _integration(client, project)
        assert page["research"]["state"] == "needs_attention"
        assert page["research"]["failedField"] == "Clue research link"
        assert page["research"]["reason"] == (
            "Clue’s field “Clue research link” was deleted in HubSpot."
        )
        assert _statuses(page)["company_research_links"] == "missing"
        assert _statuses(page)["company_fit"] == "created"

    _run(tmp_path, "owner", body)


_REFUSED_STEPS = {
    "steps": [
        {"step": 'the property group "Clue" on companies', "result": "created"},
        {"step": 'the field "Clue research link" on companies', "result": "failed"},
    ],
}


@pytest.mark.parametrize(
    ("failure_kind", "answer"),
    [
        ("permission", '{"category":"MISSING_SCOPES","message":"missing scopes"}'),
        ("other", '{"status_code": 403, "message": "Forbidden"}'),
        ("permission", '[{"errorCode":"INSUFFICIENT_ACCESS_OR_READONLY"}]'),
    ],
)
def test_permission_needed_when_the_crm_names_a_permission(
    tmp_path: Any, failure_kind: str, answer: str
) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        await record_partial_clue_fields(
            conn,
            connection_id=connection_id,
            workspace_id=project.workspace_id,
            provider="hubspot",
            found=[],
            permission_set_id=None,
            label_type_id=None,
        )
        message = 'HubSpot refused the field "Clue research link" on companies: Not allowed.'
        await _setup_card(
            conn,
            project,
            connection_id,
            proposal_status="finished",
            write_status="failed",
            failure_kind=failure_kind,
            message=message,
            response={**_REFUSED_STEPS, "crm_answer": answer},
        )
        page = await _integration(client, project)
        assert page["research"]["state"] == "permission_needed"
        # Clue's own sentence, never the CRM's message.
        assert page["research"]["reason"] == (
            "The connected HubSpot user doesn’t have permission to create fields on company "
            "records."
        )
        assert _statuses(page) == {
            "company_research_links": "permission_needed",
            "contact_profile_links": "pending",
            "contact_buying_roles": "pending",
            "company_fit": "pending",
        }

    _run(tmp_path, "owner", body)


def test_couldnt_finish_when_the_crm_refused_otherwise(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        message = (
            'HubSpot refused the field "Clue research link" on companies: Property limit reached.'
        )
        await _setup_card(
            conn,
            project,
            connection_id,
            proposal_status="finished",
            write_status="failed",
            failure_kind="other",
            message=message,
            response={**_REFUSED_STEPS, "crm_answer": '{"message":"Property limit reached"}'},
        )
        page = await _integration(client, project)
        assert page["research"]["state"] == "couldnt_finish"
        assert page["research"]["reason"] == (
            "HubSpot stopped part of the setup. Clue can retry the remaining steps."
        )
        assert set(_statuses(page).values()) == {"pending"}

    _run(tmp_path, "owner", body)


def test_permission_needed_on_salesforce_names_the_records_or_says_these(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project, provider="salesforce", name="Acme")

        async def refused(step: str) -> str:
            await conn.execute(
                text("DELETE FROM crm_write WHERE connection_id = :c"), {"c": connection_id}
            )
            await _setup_card(
                conn,
                project,
                connection_id,
                proposal_status="finished",
                write_status="failed",
                failure_kind="permission",
                message="Salesforce refused it.",
                response={
                    "steps": [{"step": step, "result": "failed"}],
                    "crm_answer": '[{"errorCode":"INSUFFICIENT_ACCESS_OR_READONLY"}]',
                },
            )
            research = (await _integration(client, project))["research"]
            assert research["state"] == "permission_needed"
            return str(research["reason"])

        assert await refused("access to Account.Clue_Research_Link__c") == (
            "The connected Salesforce user doesn’t have permission to create fields on account "
            "records."
        )
        assert await refused('the permission set "Clue fields"') == (
            "The connected Salesforce user doesn’t have permission to create fields on these "
            "records."
        )

    _run(tmp_path, "owner", body)


def test_review_chat_is_only_given_while_approval_is_needed(tmp_path: Any) -> None:
    """An older card still waits, but a newer setup failed: the page shows the failure."""

    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        older = await _setup_card(
            conn,
            project,
            connection_id,
            proposal_status="awaiting_permission",
            write_status="proposed",
            thread_id="thr_old_card",
        )
        await conn.execute(
            text(
                "UPDATE crm_write_proposal SET created_at = now() - interval '1 hour' "
                "WHERE proposal_id = :p"
            ),
            {"p": older},
        )
        await _setup_card(
            conn,
            project,
            connection_id,
            proposal_status="finished",
            write_status="failed",
            failure_kind="other",
            message="HubSpot refused it.",
            response={**_REFUSED_STEPS, "crm_answer": '{"message":"limit"}'},
        )
        research = (await _integration(client, project))["research"]
        assert research["state"] == "couldnt_finish"
        assert research["reviewChat"] is None

    _run(tmp_path, "owner", body)


def test_a_gone_field_clue_no_longer_sets_up_is_ignored(tmp_path: Any) -> None:
    """The test CRMs' old "Clue tier" field (R-14.6) is not a missing field."""

    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        await _registry(conn, project, connection_id)
        await conn.execute(
            text(
                "UPDATE crm_clue_fields SET status = 'gone', gone_at = now(), "
                "created_names = array_append(created_names, 'companies.clue_tier'), "
                "gone_names = ARRAY['companies.clue_tier'] WHERE connection_id = :c"
            ),
            {"c": connection_id},
        )
        research = (await _integration(client, project))["research"]
        assert research["state"] == "ready"
        assert (research["failedField"], research["reason"]) == (None, None)

    _run(tmp_path, "owner", body)


# --- standing permissions -------------------------------------------------------------------


def test_permissions_never_show_a_crm_api_name(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)

        async def grant(scope: str) -> UUID:
            return await insert_grant(
                conn,
                workspace_id=project.workspace_id,
                connection_id=connection_id,
                scope_key=scope,
                granted_by_user_id=USER_ID,
            )

        await grant("field:company.clue_fit_level")
        await grant("kind:list_create")
        await grant("kind:list_membership")
        await grant("field:company.industry")
        await grant("field:company.hs_custom_x__c")
        # The card that offered "industry" showed HubSpot's own label for it.
        seeded = await _seed_turn(conn, tmp_path, workspace_id=project.workspace_id, label="ind")
        proposal_id = await _setup_card(
            conn,
            project,
            connection_id,
            proposal_status="finished",
            write_status="succeeded",
            write_kind="field_update",
            field="industry",
            thread_id=seeded.thread_id,
            turn_id=seeded.turn_id,
        )
        snapshot = {"groups": [{"scope_key": "field:company.industry", "field_label": "Industry"}]}
        gate, _ = await insert_gate(
            conn,
            gate_id=uuid4(),
            workspace_id=project.workspace_id,
            project_id=seeded.project_id,
            thread_id=seeded.thread_id,
            turn_id=seeded.turn_id,
            kind=KIND_CRM_WRITE_PERMISSION,
            subject_ref=f"crm_write_proposal:{proposal_id}",
            subject_revision=None,
            expected_subject_sha256="0" * 64,
            subject_snapshot=snapshot,
            max_spend_cents=None,
            currency=None,
            addressee_user_id=USER_ID,
            permitted_decisions=("approved", "rejected"),
        )
        await conn.execute(
            text("UPDATE crm_write_proposal SET gate_id = :g WHERE proposal_id = :p"),
            {"g": gate.gate_id, "p": proposal_id},
        )
        page = await _integration(client, project)
        descriptions = [p["description"] for p in page["permissions"]]
        assert sorted(descriptions) == sorted(
            [
                "Always set Clue fit level on companies",
                "Always create Clue lists",
                "Always add records to Clue lists and campaigns",
                "Always set Industry on companies",
                "Always set a field on companies",
            ]
        )
        for text_ in descriptions:
            assert "clue_" not in text_ and "__c" not in text_
        name = await conn.scalar(
            text("SELECT display_name FROM platform_user WHERE user_id = :id"), {"id": USER_ID}
        )
        assert {p["grantedByName"] for p in page["permissions"]} == {name}
        assert all(p["grantedAt"] and p["grantId"] for p in page["permissions"])

    _run(tmp_path, "viewer", body)


def test_salesforce_permissions_say_accounts_and_the_field_label(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project, provider="salesforce", name="Acme")
        for scope in (
            "field:account.Clue_Fit_Level__c",
            "kind:list_create",
            "kind:create_company",
            "kind:list_membership",
        ):
            await insert_grant(
                conn,
                workspace_id=project.workspace_id,
                connection_id=connection_id,
                scope_key=scope,
                granted_by_user_id=USER_ID,
            )
        page = await _integration(client, project)
        assert sorted(p["description"] for p in page["permissions"]) == sorted(
            [
                "Always set Clue fit level on accounts",
                "Always create Clue campaigns",
                "Always create accounts",
                "Always add records to Clue lists and campaigns",
            ]
        )

    _run(tmp_path, "owner", body)


def test_a_member_can_revoke(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        connection_id = await _connection(conn, project)
        grant_id = await insert_grant(
            conn,
            workspace_id=project.workspace_id,
            connection_id=connection_id,
            scope_key="kind:list_create",
            granted_by_user_id="usr_someone_else",
        )
        url = f"{CRM}/permissions/{grant_id}/revoke"
        first = await client.post(url, headers=_headers(project))
        assert first.status_code == 200, first.text
        assert first.json() == {"outcome": "revoked"}
        again = await client.post(url, headers=_headers(project))
        assert again.json() == {"outcome": "already_revoked"}
        by = await conn.scalar(
            text("SELECT revoked_by_user_id FROM crm_write_grant WHERE grant_id = :id"),
            {"id": grant_id},
        )
        assert by == USER_ID
        assert (await _integration(client, project))["permissions"] == []

    _run(tmp_path, MEMBER, body)


def test_revoking_another_workspaces_or_an_old_connections_grant_is_not_found(
    tmp_path: Any,
) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        old = await _connection(conn, project, status="disconnected", account="ca_old")
        await _connection(conn, project)
        old_grant = await insert_grant(
            conn,
            workspace_id=project.workspace_id,
            connection_id=old,
            scope_key="kind:list_create",
            granted_by_user_id=USER_ID,
        )
        elsewhere = await seed_project(conn, f"{project.workspace_id}_other", name="Other")
        theirs = await _connection(conn, elsewhere, account="ca_theirs")
        their_grant = await insert_grant(
            conn,
            workspace_id=elsewhere.workspace_id,
            connection_id=theirs,
            scope_key="kind:list_create",
            granted_by_user_id=USER_ID,
        )
        for grant_id in (old_grant, their_grant, uuid4()):
            response = await client.post(
                f"{CRM}/permissions/{grant_id}/revoke", headers=_headers(project)
            )
            assert response.status_code == 404, response.text
            assert response.json()["error"]["code"] == "crm_permission_not_found"
        live = await conn.scalar(
            text(
                "SELECT count(*) FROM crm_write_grant WHERE revoked_at IS NULL "
                "AND grant_id = ANY(:ids)"
            ),
            {"ids": [old_grant, their_grant]},
        )
        assert live == 2

    _run(tmp_path, "owner", body)


# --- overwrites -----------------------------------------------------------------------------


def test_overwrites_are_stored_on_the_connection(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        url = f"{CRM}/overwrites"
        not_connected = await client.put(
            url, json={"mode": "follow_grants"}, headers=_headers(project)
        )
        assert not_connected.status_code == 409
        assert not_connected.json()["error"]["code"] == "crm_not_connected"
        connection_id = await _connection(conn, project)
        assert (await _integration(client, project))["overwrites"] == "ask"
        response = await client.put(url, json={"mode": "follow_grants"}, headers=_headers(project))
        assert response.status_code == 200, response.text
        assert response.json() == {"overwrites": "follow_grants"}
        stored = await conn.scalar(
            text("SELECT settings FROM workspace_integration_connection WHERE connection_id = :id"),
            {"id": connection_id},
        )
        assert stored == {"overwrites": "follow_grants"}
        assert (await _integration(client, project))["overwrites"] == "follow_grants"
        bad = await client.put(url, json={"mode": "always"}, headers=_headers(project))
        assert bad.status_code == 422

    _run(tmp_path, "admin", body)


def test_a_member_cannot_change_overwrites_or_open_a_connect_request(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        await _connection(conn, project)
        put = await client.put(
            f"{CRM}/overwrites", json={"mode": "follow_grants"}, headers=_headers(project)
        )
        assert put.status_code == 403
        opened = await client.post(
            f"{CRM}/connect-request", json={"mode": "switch"}, headers=_headers(project)
        )
        assert opened.status_code == 403
        page = await _integration(client, project)
        assert page["canManage"] is False
        assert page["overwrites"] == "ask"

    _run(tmp_path, MEMBER, body)


# --- connect from Settings ------------------------------------------------------------------


async def _connect_from_settings(
    client: httpx.AsyncClient, project: Project, composio: FakeComposio, mode: str
) -> dict[str, Any]:
    opened = await client.post(
        f"{CRM}/connect-request", json={"mode": mode}, headers=_headers(project)
    )
    assert opened.status_code == 200, opened.text
    request_id = opened.json()["requestId"]
    link = await client.post(
        f"{CRM}/connect-link",
        json={"requestId": request_id, "provider": "hubspot"},
        headers=_headers(project),
    )
    assert link.status_code == 200, link.text
    account = f"ca_{len(composio.links)}"
    composio.accounts[account] = ConnectedAccount(id=account, status="ACTIVE", toolkit="hubspot")
    done = await client.post(
        f"{CRM}/complete",
        json={"requestId": request_id, "status": "success", "connectedAccountId": account},
        headers=_headers(project),
    )
    return {"request_id": request_id, "account": account, **done.json()}


def test_connect_request_reuses_an_open_settings_request(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        async def open_(mode: str) -> str:
            response = await client.post(
                f"{CRM}/connect-request", json={"mode": mode}, headers=_headers(project)
            )
            assert response.status_code == 200, response.text
            return str(response.json()["requestId"])

        first = await open_("connect")
        assert await open_("connect") == first
        assert await open_("switch") != first
        composio.identities["ca_1"] = "111"
        done = await _connect_from_settings(client, project, composio, "connect")
        assert done["request_id"] == first
        assert done["outcome"] == "connected"
        open_left = await conn.scalar(
            text(
                "SELECT count(*) FROM crm_connect_request WHERE workspace_id = :ws "
                "AND status = 'open'"
            ),
            {"ws": project.workspace_id},
        )
        assert open_left == 0  # activation fulfilled the switch request too
        assert await open_("connect") != first  # a fulfilled request is never reused

    _run(tmp_path, "owner", body)


# --- disconnect -----------------------------------------------------------------------------


def test_a_member_cannot_disconnect(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        await _connection(conn, project)
        response = await client.post(f"{CRM}/disconnect", headers=_headers(project))
        assert response.status_code == 403
        assert composio.deleted == []
        assert (await _integration(client, project))["connection"]["status"] == "active"

    _run(tmp_path, MEMBER, body)


def test_disconnect_closes_cards_and_clears_grants(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        composio.identities.update({"ca_1": "111", "ca_2": "111"})
        done = await _connect_from_settings(client, project, composio, "connect")
        assert done["outcome"] == "connected"
        connection_id = await conn.scalar(
            text(
                "SELECT connection_id FROM workspace_integration_connection "
                "WHERE workspace_id = :ws"
            ),
            {"ws": project.workspace_id},
        )
        await insert_grant(
            conn,
            workspace_id=project.workspace_id,
            connection_id=connection_id,
            scope_key="kind:list_create",
            granted_by_user_id="usr_granter",
        )
        chat = await _waiting_chat(conn, client, project, "waiting_card")
        card = await _setup_card(
            conn,
            project,
            connection_id,
            proposal_status="awaiting_permission",
            write_status="proposed",
            write_kind="field_update",
            field="industry",
            thread_id=str(chat.thread_id),
            turn_id=chat.turn_id,
        )
        response = await client.post(f"{CRM}/disconnect", headers=_headers(project))
        assert response.status_code == 200, response.text
        assert response.json() == {"outcome": "disconnected"}
        assert composio.deleted == ["ca_1"]
        row = (
            await conn.execute(
                text(
                    "SELECT status, disconnected_at FROM workspace_integration_connection "
                    "WHERE connection_id = :id"
                ),
                {"id": connection_id},
            )
        ).one()
        assert row.status == "disconnected" and row.disconnected_at is not None
        grants = (
            await conn.execute(
                text(
                    "SELECT revoked_at, revoked_by_user_id FROM crm_write_grant "
                    "WHERE connection_id = :id"
                ),
                {"id": connection_id},
            )
        ).all()
        assert [(g.revoked_at is not None, g.revoked_by_user_id) for g in grants] == [
            (True, USER_ID)
        ]
        # The waiting card is closed the way a reconnect closes one, with the disconnect named.
        write = (
            await conn.execute(
                text("SELECT status, crm_message FROM crm_write WHERE proposal_id = :id"),
                {"id": card},
            )
        ).one()
        assert tuple(write) == ("skipped", DISCONNECTED_MESSAGE)
        progress = await client.get(f"{CRM}/proposals/{card}", headers=_headers(project))
        assert progress.json()["state"] == "closed"
        woken = await conn.scalar(
            text(
                "SELECT count(*) FROM agent_turn_submission WHERE workspace_id = :ws "
                "AND derivation = :d AND thread_id = :t"
            ),
            {"ws": project.workspace_id, "d": DERIVATION_CRM_WRITES_FINISHED, "t": chat.thread_id},
        )
        assert woken == 1
        page = await _integration(client, project)
        assert page["connection"]["status"] == "disconnected"
        assert page["research"]["state"] == "not_connected"
        assert page["permissions"] == []
        again = await client.post(f"{CRM}/disconnect", headers=_headers(project))
        assert again.status_code == 409
        # A later connect to the same portal reuses the row, with no permissions carried over.
        later = await _connect_from_settings(client, project, composio, "connect")
        assert later["outcome"] == "connected"
        reused = await conn.scalar(
            text("SELECT count(*) FROM workspace_integration_connection WHERE workspace_id = :ws"),
            {"ws": project.workspace_id},
        )
        assert reused == 1
        page = await _integration(client, project)
        assert page["connection"]["status"] == "active"
        assert page["permissions"] == []

    _run(tmp_path, "owner", body)


def test_disconnect_stands_when_composio_delete_fails(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, composio: Any) -> None:
        await _connection(conn, project, status="expired", account="ca_expired")
        composio.delete_fails = True
        response = await client.post(f"{CRM}/disconnect", headers=_headers(project))
        assert response.status_code == 200, response.text
        assert composio.deleted == ["ca_expired"]
        assert (await _integration(client, project))["connection"]["status"] == "disconnected"

    _run(tmp_path, "owner", body)


# --- Ask Clue's project ---------------------------------------------------------------------


def test_ask_clue_opens_in_the_project_the_crm_was_connected_from(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        later = await seed_project(conn, project.workspace_id, name="Later")
        await _waiting_chat(conn, client, project, "connect_here")
        await conn.execute(
            text("UPDATE project SET updated_at = now() + interval '1 hour' WHERE project_id = :p"),
            {"p": later.project_id},
        )
        page = await _integration(client, project)
        assert page["askClueProjectId"] == project.project_id

    _run(tmp_path, "owner", body)


def test_ask_clue_falls_back_when_the_connect_project_is_archived(tmp_path: Any) -> None:
    async def body(conn: Any, client: httpx.AsyncClient, project: Project, _: Any) -> None:
        other = await seed_project(conn, project.workspace_id, name="Other")
        await _waiting_chat(conn, client, project, "connect_here")
        await conn.execute(
            text(
                "UPDATE project SET status = 'archived', archived_at = now() WHERE project_id = :p"
            ),
            {"p": project.project_id},
        )
        page = await _integration(client, project)
        assert page["askClueProjectId"] == other.project_id

    _run(tmp_path, "owner", body)
