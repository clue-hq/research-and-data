"""Preparing a batch of CRM writes (CRM integration Phase 2, Task 4).

What the agent proposes becomes one prepared change per (record, field), each with the value the
CRM holds today, whether it overwrites a value a person set (R-6.5, R-6.25 call 11), the scope a
standing permission would cover, and the grant that covers it. Forbidden writes (consent, phone,
person fields outside R-8.7, values the CRM does not allow) are refused before any card is shown.
The CRM is a fake gateway; the database is the lane's test DB.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.crm import writes
from clue_api.crm.composio_gateway import ExecuteResult
from clue_api.crm.connections import CrmConnection
from clue_api.crm.write_prepare import (
    PreparedChange,
    ProposedChange,
    WriteRefused,
    card_snapshot,
    prepare_changes,
)
from tests.api.test_crm_tools_db import _connect
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


_TIERS = [{"label": t, "value": t} for t in ("Tier 1", "Tier 2", "Tier 3")]

_HUBSPOT_PROPERTIES: dict[str, list[dict[str, Any]]] = {
    "companies": [
        {"name": "name", "label": "Company name", "type": "string", "fieldType": "text"},
        {
            "name": "icp_tier",
            "label": "ICP tier",
            "type": "enumeration",
            "fieldType": "select",
            "options": _TIERS,
        },
        {
            "name": "hs_ideal_customer_profile",
            "label": "Ideal Customer Profile Tier",
            "type": "enumeration",
            "fieldType": "radio",
            "options": [
                {"label": "Tier 1", "value": "tier_1"},
                {"label": "Tier 2", "value": "tier_2"},
                {"label": "Tier 3", "value": "tier_3"},
            ],
        },
        {"name": "x_flag", "label": "Do not call", "type": "bool", "fieldType": "booleancheckbox"},
        {"name": "clue_marketing_consent", "label": "Marketing", "type": "string"},
    ],
    "contacts": [
        {"name": "email", "label": "Email", "type": "string", "fieldType": "text"},
        {"name": "jobtitle", "label": "Job title", "type": "string", "fieldType": "text"},
        {"name": "firstname", "label": "First name", "type": "string", "fieldType": "text"},
        {"name": "city", "label": "City", "type": "string", "fieldType": "text"},
    ],
}

_SALESFORCE_FIELDS: dict[str, list[dict[str, Any]]] = {
    "Account": [
        {"name": "Name", "label": "Account Name", "type": "string", "custom": False},
        {
            "name": "Industry",
            "label": "Industry",
            "type": "picklist",
            "custom": False,
            "picklistValues": [
                {"value": "Hospitality", "label": "Hospitality", "active": True},
                {"value": "Retail", "label": "Retail", "active": True},
                {"value": "Old", "label": "Old", "active": False},
            ],
        },
        {
            "name": "Tier__c",
            "label": "Tier",
            "type": "picklist",
            "custom": True,
            "picklistValues": [
                {"value": "T1", "label": "Tier One", "active": True},
                {"value": "T2", "label": "Tier Two", "active": True},
            ],
        },
    ],
    "Contact": [
        {"name": "Title", "label": "Title", "type": "string", "custom": False},
    ],
}


class _FakeCrm:
    """Answers the read actions preparation uses; every call is recorded."""

    def __init__(
        self,
        *,
        records: Mapping[str, Mapping[str, Any]] | None = None,
        lists: Mapping[str, list[str]] | None = None,
        malformed: frozenset[str] = frozenset(),
    ) -> None:
        #: Reads answered with a body of an unexpected shape.
        self.malformed = malformed
        self.records = {key: dict(value) for key, value in (records or {}).items()}
        self.lists = dict(lists or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        *,
        slug: str,
        arguments: Mapping[str, Any],
        connected_account_id: str,
        user_id: str,
        version: str,
    ) -> ExecuteResult:
        del connected_account_id, user_id, version
        self.calls.append((slug, dict(arguments)))
        if slug in self.malformed:
            return ExecuteResult(True, {"data": {"message": "unexpected"}}, None)
        return ExecuteResult(True, {"data": self._answer(slug, arguments)}, None)

    def _answer(self, slug: str, arguments: Mapping[str, Any]) -> Any:
        if slug == "HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE":
            return {"results": _HUBSPOT_PROPERTIES[arguments["objectType"]]}
        if slug == "HUBSPOT_READ_CRM_OBJECT_BY_ID":
            record = self.records.get(str(arguments["objectId"]), {})
            props = {name: record.get(name) for name in arguments["properties"]}
            return {"id": str(arguments["objectId"]), "properties": props}
        if slug == "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS":
            lists = self.lists.get(str(arguments["record_id"]), [])
            return {"results": [{"listId": list_id} for list_id in lists]}
        if slug == "HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA":
            wanted = arguments["filterGroups"][0]["filters"][0]["value"]
            found = [
                {"id": rid, "properties": {k: rec.get(k) for k in arguments["properties"]}}
                for rid, rec in self.records.items()
                if rec.get("email") == wanted
            ]
            return {"results": found, "total": len(found)}
        if slug == "SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT":
            return {"fields": _SALESFORCE_FIELDS[arguments["object_name"]]}
        if slug == "SALESFORCE_RUN_SOQL_QUERY":
            query = arguments["query"]
            found = [
                {"attributes": {"type": "Account"}, "Id": rid, **rec}
                for rid, rec in self.records.items()
                if f"'{rid}'" in query
            ]
            return {"records": found, "totalSize": len(found), "done": True}
        raise AssertionError(f"unexpected read {slug}")


class _FakeBudget:
    def __init__(self, gateway: _FakeCrm) -> None:
        self.gateway = gateway
        #: How many CRM calls had been made when each call was taken from the budget.
        self.taken_at: list[int] = []

    async def take_call(self, conn: Any, *, connection: CrmConnection, today: date) -> None:
        del conn, connection, today
        self.taken_at.append(len(self.gateway.calls))


def _run(tmp_path: Path, label: str, body: Any, provider: str = "hubspot") -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmw-{label}", label=label)
            connection = await _connect(conn, seeded.workspace_id, provider)
            proposal_id = uuid4()
            await writes.insert_proposal(
                conn,
                proposal_id=proposal_id,
                workspace_id=seeded.workspace_id,
                connection_id=connection.connection_id,
                project_id=seeded.project_id,
                thread_id=seeded.thread_id,
                turn_id=seeded.turn_id,
            )
            await body(conn, seeded, connection, proposal_id)

    run_async(scenario())


async def _prepare(
    conn: Any,
    gateway: _FakeCrm,
    connection: CrmConnection,
    proposal_id: UUID,
    changes: list[ProposedChange],
    budget: Any = None,
) -> list[PreparedChange]:
    return await prepare_changes(
        conn,
        gateway=gateway,
        budget=budget,
        connection=connection,
        proposal_id=proposal_id,
        changes=changes,
        version="v-test",
    )


def _set_company(record: str, field: str, value: object, reason: str = "tiers") -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_UPDATE_COMPANY", {"companyId": record, "properties": {field: value}}, reason
    )


def _set_contact(record: str, fields: Mapping[str, object]) -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_UPDATE_CONTACTS",
        {"inputs": [{"id": record, "properties": dict(fields)}]},
        "committee",
    )


def _add_to_list(record: str, list_id: str = "9") -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        {"list_id": list_id, "operation": "add", "record_ids": [record]},
        "the buying committees found for the 12 accounts",
    )


async def _write_count(conn: Any, workspace_id: str) -> int:
    result = await conn.execute(
        text("SELECT count(*) FROM crm_write WHERE workspace_id = :ws"), {"ws": workspace_id}
    )
    return int(result.scalar_one())


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (_set_contact("201", {"hs_email_optout": True}), "crm_field_forbidden"),
        (_set_contact("201", {"phone": "+1 555 0100"}), "crm_field_forbidden"),
        (_set_contact("201", {"city": "Lisbon"}), "crm_field_forbidden"),  # outside R-8.7
        (_set_company("101", "clue_marketing_consent", "yes"), "crm_field_forbidden"),
        (_set_company("101", "x_flag", True), "crm_field_forbidden"),  # label "Do not call"
        (
            ProposedChange("HUBSPOT_DELETE_CONTACT", {"contactId": "201"}, "x"),
            "crm_write_not_allowed",
        ),
        (
            ProposedChange("HUBSPOT_UPDATE_COMPANY", {"companyId": "101"}, "x"),
            "crm_write_not_parsable",
        ),
    ],
)
def test_forbidden_writes_are_refused_before_the_card(
    tmp_path: Path, change: ProposedChange, code: str
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"101": {}, "201": {}})
        allowed = _set_company("101", "name", "Aldercare")
        with pytest.raises(WriteRefused) as refused:
            await _prepare(conn, gateway, connection, proposal_id, [allowed, change])
        assert refused.value.reason_code == code
        assert await _write_count(conn, seeded.workspace_id) == 0
        # Refused before any record was read.
        assert not [c for c in gateway.calls if c[0] == "HUBSPOT_READ_CRM_OBJECT_BY_ID"]

    _run(tmp_path, "refuse", body)


def test_a_value_the_crm_does_not_allow_is_refused_with_the_allowed_values(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"101": {}})
        with pytest.raises(WriteRefused) as refused:
            await _prepare(
                conn, gateway, connection, proposal_id, [_set_company("101", "icp_tier", "Tier 9")]
            )
        assert refused.value.reason_code == "crm_value_not_allowed"
        assert "Tier 1, Tier 2, Tier 3" in str(refused.value)

    _run(tmp_path, "picklist", body)


def test_salesforce_picklist_values_are_checked_even_though_salesforce_would_save_them(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"001A": {"Industry": None}})
        change = ProposedChange(
            "SALESFORCE_UPDATE_ACCOUNT", {"account_id": "001A", "industry": "Old"}, "x"
        )
        with pytest.raises(WriteRefused) as refused:
            await _prepare(conn, gateway, connection, proposal_id, [change], _FakeBudget(gateway))
        assert refused.value.reason_code == "crm_value_not_allowed"
        assert "Hospitality, Retail" in str(refused.value)  # inactive values are not offered

    _run(tmp_path, "sfpick", body, provider="salesforce")


def test_a_filled_value_a_person_set_is_an_overwrite_and_a_value_clue_wrote_is_not(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        # Clue set Tier 2 on 102 earlier; a person set Tier 3 on 101.
        earlier = uuid4()
        await writes.insert_proposal(
            conn,
            proposal_id=earlier,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            project_id=seeded.project_id,
            thread_id=seeded.thread_id,
            turn_id=seeded.turn_id,
        )
        gateway = _FakeCrm(records={"102": {"icp_tier": None}})
        old = await _prepare(
            conn, gateway, connection, earlier, [_set_company("102", "icp_tier", "Tier 2")]
        )
        await writes.insert_writes(
            conn,
            proposal_id=earlier,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=old,
        )
        await conn.execute(
            text("UPDATE crm_write SET status = 'succeeded' WHERE write_id = :id"),
            {"id": old[0].write_id},
        )

        gateway = _FakeCrm(records={"101": {"icp_tier": "Tier 3"}, "102": {"icp_tier": "Tier 2"}})
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_set_company("101", "icp_tier", "Tier 1"), _set_company("102", "icp_tier", "Tier 1")],
        )
        by_record = {p.parsed.record_ref: p for p in prepared}
        assert by_record["101"].before == "Tier 3" and by_record["101"].overwrites_person is True
        assert by_record["102"].before == "Tier 2" and by_record["102"].overwrites_person is False
        assert by_record["101"].scope_key == "field:company.icp_tier"

    _run(tmp_path, "overwrite", body)


def test_an_empty_field_is_a_fill_not_an_overwrite(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"101": {"icp_tier": None, "name": ""}})
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                ProposedChange(
                    "HUBSPOT_UPDATE_COMPANY",
                    {"companyId": "101", "properties": {"icp_tier": "Tier 1", "name": "Acme"}},
                    "fill",
                )
            ],
        )
        # One change per field, from one read of the record.
        assert sorted(p.field for p in prepared) == ["icp_tier", "name"]
        assert all(p.before is None and p.overwrites_person is False for p in prepared)
        reads = [c for c in gateway.calls if c[0] == "HUBSPOT_READ_CRM_OBJECT_BY_ID"]
        assert len(reads) == 1
        tier = next(p for p in prepared if p.field == "icp_tier")
        assert tier.arguments == {"companyId": "101", "properties": {"icp_tier": "Tier 1"}}

    _run(tmp_path, "fill", body)


def test_a_create_that_finds_the_record_becomes_an_update(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={"77": {"email": "ana@acme.example.com", "jobtitle": "", "firstname": "Ana"}}
        )
        create = ProposedChange(
            "HUBSPOT_CREATE_CONTACT",
            {"email": "ana@acme.example.com", "firstname": "Ana", "jobtitle": "COO"},
            "committee",
        )
        prepared = await _prepare(conn, gateway, connection, proposal_id, [create])
        assert len(prepared) == 1  # email and first name already match: nothing to change
        (change,) = prepared
        assert change.spec.slug == "HUBSPOT_UPDATE_CONTACTS"
        assert change.parsed.record_ref == "77" and change.field == "jobtitle"
        assert change.before is None and change.after == "COO"
        assert change.scope_key == "field:contact.jobtitle"

        # A create of a record that already holds every value is no change at all.
        same = ProposedChange(
            "HUBSPOT_CREATE_CONTACT", {"email": "ana@acme.example.com", "firstname": "Ana"}, "x"
        )
        assert await _prepare(conn, gateway, connection, proposal_id, [same]) == []

        # Nothing found: it stays a create, scoped by its kind.
        new = ProposedChange("HUBSPOT_CREATE_CONTACT", {"email": "bo@acme.example.com"}, "x")
        (created,) = await _prepare(conn, gateway, connection, proposal_id, [new])
        assert created.spec.slug == "HUBSPOT_CREATE_CONTACT" and created.field is None
        assert created.scope_key == "kind:create_contact"

    _run(tmp_path, "create", body)


def test_a_grant_covers_fills_but_never_overwrites(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        grant_id = await writes.insert_grant(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            scope_key="field:company.icp_tier",
            granted_by_user_id=USER_ID,
        )
        gateway = _FakeCrm(records={"101": {"icp_tier": None}, "102": {"icp_tier": "Tier 3"}})
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_set_company("101", "icp_tier", "Tier 1"), _set_company("102", "icp_tier", "Tier 1")],
        )
        by_record = {p.parsed.record_ref: p for p in prepared}
        assert by_record["101"].covered_by == f"grant:{grant_id}"
        assert by_record["102"].overwrites_person is True and by_record["102"].covered_by is None

        # A covered change never appears on the card; the overwrite does.
        card = card_snapshot(prepared, provider="hubspot", project_name="Q4")
        assert card["groups"] == [] and len(card["overwrites"]) == 1

        # A revoked grant covers nothing.
        assert await writes.revoke_grant(conn, grant_id=grant_id, revoked_by_user_id=USER_ID)
        again = await _prepare(
            conn, gateway, connection, proposal_id, [_set_company("101", "icp_tier", "Tier 1")]
        )
        assert again[0].covered_by is None

    _run(tmp_path, "grant", body)


def test_the_card_snapshot_groups_by_action_and_field_with_counts_and_lists_overwrites_alone(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        companies = {f"c{i}": {"icp_tier": None} for i in range(12)}
        companies.update({"o1": {"icp_tier": "Tier 3"}, "o2": {"icp_tier": "Tier 2"}})
        gateway = _FakeCrm(records=companies)
        changes = [_add_to_list(f"p{i}") for i in range(48)]
        changes += [
            _set_company(f"c{i}", "icp_tier", "Tier 1" if i < 5 else "Tier 2", "tiers from the ICP")
            for i in range(12)
        ]
        changes += [
            _set_company("o1", "icp_tier", "Tier 1"),
            _set_company("o2", "icp_tier", "Tier 1"),
        ]
        prepared = await _prepare(conn, gateway, connection, proposal_id, changes)
        card = card_snapshot(prepared, provider="hubspot", project_name="Q4 hotel groups")

        assert card["title"] == "Clue wants to update HubSpot"
        assert card["description"] == 'For "Q4 hotel groups". Nothing is sent until you allow it.'
        lists, tiers = card["groups"]
        assert lists["count"] == 48 and lists["value_summary"] is None
        assert lists["title"] == 'Add 48 contacts to the list "9"'
        assert lists["reason"] == "the buying committees found for the 12 accounts"
        assert tiers["count"] == 12 and tiers["title"] == 'Set "ICP tier" on 12 companies'
        assert tiers["value_summary"] == "Empty today → Tier 1 (5), Tier 2 (7)"
        assert len(tiers["records"]) == 12
        assert len(card["overwrites"]) == 2
        assert all(row["selected"] is False for row in card["overwrites"])
        assert {row["before"] for row in card["overwrites"]} == {"Tier 3", "Tier 2"}
        assert card["overwrites"][0]["set_by"] is None
        assert [s["phrase"] for s in card["standing_permissions"]] == [
            "adding contacts to Clue lists",
            'setting "ICP tier" on companies',
        ]
        assert card["allow_count"] == 60

        # The same changes land in the write log, overwrites unticked.
        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=prepared,
        )
        rows = await conn.execute(
            text(
                "SELECT count(*) FILTER (WHERE selected), "
                "count(*) FILTER (WHERE overwrites_person) FROM crm_write WHERE proposal_id = :p"
            ),
            {"p": proposal_id},
        )
        assert tuple(rows.one()) == (60, 2)

    _run(tmp_path, "card", body)


def test_salesforce_before_reads_take_from_the_budget(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"001A": {"Industry": None}, "001B": {"Industry": "Retail"}})
        budget = _FakeBudget(gateway)
        changes = [
            ProposedChange(
                "SALESFORCE_UPDATE_ACCOUNT", {"account_id": rid, "industry": "Hospitality"}, "x"
            )
            for rid in ("001A", "001B")
        ]
        prepared = await _prepare(conn, gateway, connection, proposal_id, changes, budget)
        # One describe and one batched SOQL read, each taken from the budget before it ran.
        assert [slug for slug, _ in gateway.calls] == [
            "SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT",
            "SALESFORCE_RUN_SOQL_QUERY",
        ]
        assert budget.taken_at == [0, 1]
        by_record = {p.parsed.record_ref: p for p in prepared}
        assert by_record["001A"].before is None and not by_record["001A"].overwrites_person
        assert by_record["001B"].before == "Retail" and by_record["001B"].overwrites_person

    _run(tmp_path, "sfbudget", body, provider="salesforce")


def test_proposal_status_and_record_links_are_kept(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        await writes.set_proposal_status(
            conn, proposal_id=proposal_id, status="declined", answered_by_user_id=USER_ID
        )
        row = await conn.execute(
            text(
                "SELECT status, answered_by_user_id, answered_at IS NOT NULL, "
                "finished_at IS NOT NULL FROM crm_write_proposal WHERE proposal_id = :p"
            ),
            {"p": proposal_id},
        )
        assert tuple(row.one()) == ("declined", USER_ID, True, True)

        entity = uuid4()
        link = {
            "workspace_id": seeded.workspace_id,
            "connection_id": connection.connection_id,
            "crm_object": "contact",
            "crm_id": "77",
        }
        await writes.record_link(conn, **link, created_by_clue=True)
        await writes.record_link(conn, **link, created_by_clue=False, clue_entity_id=entity)
        row = await conn.execute(
            text("SELECT clue_entity_id, created_by_clue FROM crm_record_link WHERE crm_id = '77'")
        )
        assert tuple(row.one()) == (entity, True)  # Clue created it, whatever a later link says

    _run(tmp_path, "status", body)


def _remove_from_list(record: str, list_id: str = "9") -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        {"list_id": list_id, "operation": "remove", "record_ids": [record]},
        "no longer on the committee",
    )


def test_clue_removes_only_members_it_added(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(lists={"p1": ["9"], "p2": ["9"]})
        # p1 was added to list 9 by a person: removing it is refused, and nothing is logged.
        with pytest.raises(WriteRefused) as refused:
            await _prepare(conn, gateway, connection, proposal_id, [_remove_from_list("p1")])
        assert refused.value.reason_code == "crm_removal_not_allowed"
        assert "only removes members it added" in str(refused.value)
        assert await _write_count(conn, seeded.workspace_id) == 0

        # p2 was added by Clue: the removal is prepared.
        await writes.record_membership_link(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            list_ref="9",
            record_ref="p2",
            write_id=None,
        )
        (removal,) = await _prepare(
            conn, gateway, connection, proposal_id, [_remove_from_list("p2")]
        )
        assert removal.scope_key == "kind:list_removal"
        assert removal.before is True and removal.after is False
        # Clue's link to p2 in list 9 says nothing about list 10.
        with pytest.raises(WriteRefused):
            await _prepare(conn, gateway, connection, proposal_id, [_remove_from_list("p2", "10")])

    _run(tmp_path, "removal", body)


def test_a_salesforce_record_the_read_does_not_return_is_refused_not_shown_as_empty(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"001A": {"Industry": None}})
        changes = [
            ProposedChange(
                "SALESFORCE_UPDATE_ACCOUNT", {"account_id": rid, "industry": "Hospitality"}, "x"
            )
            for rid in ("001A", "001Z")
        ]
        with pytest.raises(WriteRefused) as refused:
            await _prepare(conn, gateway, connection, proposal_id, changes, _FakeBudget(gateway))
        assert refused.value.reason_code == "crm_read_failed"
        assert "001Z" in str(refused.value) and "001A" not in str(refused.value)

    _run(tmp_path, "sfmissing", body, provider="salesforce")


@pytest.mark.parametrize(
    ("malformed", "change"),
    [
        ("HUBSPOT_READ_CRM_OBJECT_BY_ID", _set_company("101", "icp_tier", "Tier 1")),
        ("HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS", _add_to_list("p1")),
        (
            "HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA",
            ProposedChange("HUBSPOT_CREATE_CONTACT", {"email": "a@acme.example.com"}, "x"),
        ),
        ("HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE", _set_company("101", "icp_tier", "Tier 1")),
    ],
)
def test_an_answer_of_an_unexpected_shape_is_refused_not_read_as_empty(
    tmp_path: Path, malformed: str, change: ProposedChange
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={"101": {"icp_tier": "Tier 3"}}, malformed=frozenset({malformed})
        )
        with pytest.raises(WriteRefused) as refused:
            await _prepare(conn, gateway, connection, proposal_id, [change])
        assert refused.value.reason_code == "crm_read_failed"

    _run(tmp_path, "shape", body)


def test_an_update_names_its_records_from_the_read_not_by_their_ids(tmp_path: Path) -> None:
    """The live defect: an update that does not set a name was labelled by its CRM id."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={
                "101": {"icp_tier": None, "name": "Cargoloop", "domain": "cargoloop.test"},
                "102": {"icp_tier": None, "name": "", "domain": "stackfield.test"},
                "103": {"icp_tier": None},
                "201": {
                    "jobtitle": None,
                    "firstname": "Ana",
                    "lastname": "Lima",
                    "email": "a@x.io",
                },
                "202": {"jobtitle": None, "email": "bo@x.io"},
            }
        )
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                _set_company("101", "icp_tier", "Tier 1"),
                _set_company("102", "icp_tier", "Tier 1"),
                _set_company("103", "icp_tier", "Tier 1"),
                _set_contact("201", {"jobtitle": "COO"}),
                _set_contact("202", {"jobtitle": "CFO"}),
            ],
        )
        labels = {p.parsed.record_ref: p.parsed.label for p in prepared}
        assert labels == {
            "101": "Cargoloop",
            "102": "stackfield.test",  # no name: the domain
            "103": "103",  # the read holds nothing to name it by: the id
            "201": "Ana Lima",
            "202": "bo@x.io",
        }
        # Display properties are read alongside, never compared: one change per proposed field.
        assert sorted((p.parsed.record_ref, p.field) for p in prepared) == [
            ("101", "icp_tier"),
            ("102", "icp_tier"),
            ("103", "icp_tier"),
            ("201", "jobtitle"),
            ("202", "jobtitle"),
        ]
        assert all(p.parsed.fields.keys() == {p.field} for p in prepared)
        reads = {
            c[1]["objectId"]: set(c[1]["properties"])
            for c in gateway.calls
            if c[0] == "HUBSPOT_READ_CRM_OBJECT_BY_ID"
        }
        assert reads["101"] == {"icp_tier", "name", "domain"}
        assert reads["201"] == {"jobtitle", "firstname", "lastname", "email"}

        # The write log keeps the name too.
        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=prepared,
        )
        rows = await conn.execute(
            text("SELECT record_ref, record_label FROM crm_write WHERE proposal_id = :p"),
            {"p": proposal_id},
        )
        assert dict(rows.all())["101"] == "Cargoloop"
        card = card_snapshot(prepared, provider="hubspot", project_name="Q4")
        names = {r["record_ref"]: r["name"] for g in card["groups"] for r in g["records"]}
        assert names["101"] == "Cargoloop" and names["201"] == "Ana Lima"

    _run(tmp_path, "labels", body)


def test_a_display_value_does_not_change_overwrite_detection(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        # A person set the name; the change sets only the tier, which a person also set.
        gateway = _FakeCrm(records={"101": {"icp_tier": "Tier 3", "name": "Cargoloop"}})
        (change,) = await _prepare(
            conn, gateway, connection, proposal_id, [_set_company("101", "icp_tier", "Tier 1")]
        )
        assert change.field == "icp_tier" and change.before == "Tier 3"
        assert change.overwrites_person is True
        assert change.arguments == {"companyId": "101", "properties": {"icp_tier": "Tier 1"}}

        # Renaming names the record by its name today; the name is still the compared field.
        (rename,) = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_set_company("101", "name", "Cargoloop Inc")],
        )
        assert rename.parsed.label == "Cargoloop"
        assert rename.before == "Cargoloop" and rename.after == "Cargoloop Inc"
        assert rename.overwrites_person is True

    _run(tmp_path, "labelsover", body)


def test_salesforce_records_are_named_by_their_name_then_email(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={
                "001A": {"Industry": None, "Name": "Cargoloop"},
                "001B": {"Industry": None},
                "003A": {"Title": None, "Name": "Ana Lima", "Email": "a@x.io"},
                "003B": {"Title": None, "Name": None, "Email": "bo@x.io"},
            }
        )
        changes = [
            ProposedChange(
                "SALESFORCE_UPDATE_ACCOUNT", {"account_id": rid, "industry": "Hospitality"}, "x"
            )
            for rid in ("001A", "001B")
        ] + [
            ProposedChange("SALESFORCE_UPDATE_CONTACT", {"contact_id": rid, "title": "COO"}, "x")
            for rid in ("003A", "003B")
        ]
        prepared = await _prepare(
            conn, gateway, connection, proposal_id, changes, _FakeBudget(gateway)
        )
        labels = {p.parsed.record_ref: p.parsed.label for p in prepared}
        assert labels == {
            "001A": "Cargoloop",
            "001B": "001B",
            "003A": "Ana Lima",
            "003B": "bo@x.io",
        }
        assert sorted(p.field for p in prepared) == ["Industry", "Industry", "Title", "Title"]
        queries = [c[1]["query"] for c in gateway.calls if c[0] == "SALESFORCE_RUN_SOQL_QUERY"]
        assert any(q.startswith("SELECT Id, Industry, Name FROM Account") for q in queries)
        assert any(q.startswith("SELECT Id, Email, Name, Title FROM Contact") for q in queries)

    _run(tmp_path, "sflabels", body, provider="salesforce")


def test_the_card_shows_option_labels_but_keeps_the_values_it_sends(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        # R-11.5: "Tier 1", not "tier_1". A value with no option (the person's own "legacy")
        # shows as it is; a field with no options is unchanged.
        gateway = _FakeCrm(
            records={
                "101": {"hs_ideal_customer_profile": None, "name": ""},
                "102": {"hs_ideal_customer_profile": None, "name": "Moxa"},
                "103": {"hs_ideal_customer_profile": "legacy", "name": "Orbit"},
            }
        )
        changes = [
            _set_company("101", "hs_ideal_customer_profile", "tier_1"),
            _set_company("102", "hs_ideal_customer_profile", "tier_1"),
            _set_company("103", "hs_ideal_customer_profile", "tier_2"),
            _set_company("101", "name", "tier_1 Holdings"),
        ]
        prepared = await _prepare(conn, gateway, connection, proposal_id, changes)
        card = card_snapshot(prepared, provider="hubspot", project_name="Q4")

        tiers, names = card["groups"]
        assert tiers["value_summary"] == "Empty today \u2192 Tier 1 (2)"
        assert {r["after"] for r in tiers["records"]} == {"Tier 1"}
        assert names["value_summary"] == "Empty today \u2192 tier_1 Holdings (1)"
        (overwrite,) = card["overwrites"]
        assert overwrite["before"] == "legacy" and overwrite["after"] == "Tier 2"

        # What is stored and sent stays the internal value.
        by_record = {
            p.parsed.record_ref: p for p in prepared if p.field == "hs_ideal_customer_profile"
        }
        assert by_record["101"].after == "tier_1"
        assert by_record["101"].arguments == {
            "companyId": "101",
            "properties": {"hs_ideal_customer_profile": "tier_1"},
        }
        assert by_record["103"].before == "legacy" and by_record["103"].after == "tier_2"
        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=prepared,
        )
        rows = await conn.execute(
            text(
                "SELECT after_value #>> '{}' FROM crm_write "
                "WHERE proposal_id = :p AND field = 'hs_ideal_customer_profile'"
            ),
            {"p": proposal_id},
        )
        assert {row[0] for row in rows.all()} == {"tier_1", "tier_2"}

    _run(tmp_path, "optlabels", body)


def test_a_salesforce_card_shows_picklist_labels(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={"001A": {"Tier__c": None, "Name": "Cargoloop"}, "001B": {"Tier__c": None}}
        )
        changes = [
            ProposedChange(
                "SALESFORCE_UPDATE_ACCOUNT",
                {"account_id": rid, "custom_fields": {"Tier__c": value}},
                "x",
            )
            for rid, value in (("001A", "T1"), ("001B", "T2"))
        ]
        prepared = await _prepare(
            conn, gateway, connection, proposal_id, changes, _FakeBudget(gateway)
        )
        card = card_snapshot(prepared, provider="salesforce", project_name="Q4")
        (group,) = card["groups"]
        assert group["value_summary"] == "Empty today \u2192 Tier One (1), Tier Two (1)"
        assert sorted(r["after"] for r in group["records"]) == ["Tier One", "Tier Two"]
        assert sorted(str(p.after) for p in prepared) == ["T1", "T2"]

    _run(tmp_path, "sfoptlabels", body, provider="salesforce")
