"""Preparing a batch of CRM writes (CRM integration Phase 2, Task 4).

What the agent proposes becomes one prepared change per (record, field), each with the value the
CRM holds today, whether it overwrites a value a person set (R-6.5, R-6.25 call 11), the scope a
standing permission would cover, and the grant that covers it. Forbidden writes (consent, phone,
person fields outside R-8.7, values the CRM does not allow) are refused before any card is shown.
The CRM is a fake gateway; the database is the lane's test DB.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.crm import writes
from clue_api.crm.composio_gateway import ComposioError, ExecuteResult
from clue_api.crm.connections import CrmConnection
from clue_api.crm.write_prepare import (
    PreparedBatch,
    PreparedChange,
    ProposedChange,
    RefusedChange,
    WriteRefused,
    card_snapshot,
    prepare_changes,
)
from clue_config import Settings
from tests.api._crm_people import clear_people
from tests.api.test_crm_tools_db import _connect
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

SETTINGS = Settings(_env_file=None)


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
        {"name": "domain", "label": "Company domain name", "type": "string", "fieldType": "text"},
        {
            "name": "hs_is_target_account",
            "label": "Target Account",
            "type": "bool",
            "fieldType": "booleancheckbox",
        },
        {"name": "clue_marketing_consent", "label": "Marketing", "type": "string"},
    ],
    "contacts": [
        {"name": "email", "label": "Email", "type": "string", "fieldType": "text"},
        {"name": "jobtitle", "label": "Job title", "type": "string", "fieldType": "text"},
        {"name": "firstname", "label": "First name", "type": "string", "fieldType": "text"},
        {"name": "lastname", "label": "Last name", "type": "string", "fieldType": "text"},
        {
            "name": "hs_linkedin_url",
            "label": "LinkedIn URL",
            "type": "string",
            "fieldType": "text",
        },
        {
            "name": "hs_buying_role",
            "label": "Buying Role",
            "type": "enumeration",
            "fieldType": "checkbox",
            "options": [
                {"label": label, "value": value}
                for value, label in (
                    ("BUDGET_HOLDER", "Budget Holder"),
                    ("CHAMPION", "Champion"),
                    ("BLOCKER", "Blocker"),
                    ("END_USER", "End User"),
                    ("INFLUENCER", "Influencer"),
                )
            ],
        },
        {"name": "city", "label": "City", "type": "string", "fieldType": "text"},
    ],
}

_SALESFORCE_FIELDS: dict[str, list[dict[str, Any]]] = {
    "Account": [
        {"name": "Name", "label": "Account Name", "type": "string", "custom": False},
        {"name": "Website", "label": "Website", "type": "url", "custom": False},
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


#: HubSpot's answer to reading a record that is not there (HTTP 404 inside a refused call).
HUBSPOT_NOT_FOUND = ExecuteResult(
    False,
    {"http_error": "404", "status_code": 404, "message": "Not Found"},
    '{"status":"error","message":"Object not found.  objectId are usually numeric.",'
    '"category":"OBJECT_NOT_FOUND"}',
)


class _FakeCrm:
    """Answers the read actions preparation uses; every call is recorded."""

    def __init__(
        self,
        *,
        records: Mapping[str, Mapping[str, Any]] | None = None,
        lists: Mapping[str, list[str]] | None = None,
        malformed: frozenset[str] = frozenset(),
        missing: frozenset[str] = frozenset(),
        failing: Mapping[str, ExecuteResult | Exception] | None = None,
    ) -> None:
        #: Reads answered with a body of an unexpected shape.
        self.malformed = malformed
        #: HubSpot record ids the CRM does not have: reading one by id answers 404.
        self.missing = missing
        #: Reads that fail: a refused call (its result) or no answer at all (the exception).
        self.failing = dict(failing or {})
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
        failure = self.failing.get(slug)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if slug == "HUBSPOT_READ_CRM_OBJECT_BY_ID" and str(arguments["objectId"]) in self.missing:
            return HUBSPOT_NOT_FOUND
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
        if slug == "HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES":
            # HubSpot's batch read leaves out a record it does not have.
            return {
                "status": "COMPLETE",
                "results": [
                    {
                        "id": item["id"],
                        "properties": {
                            name: self.records.get(item["id"], {}).get(name)
                            for name in arguments["properties"]
                        },
                    }
                    for item in arguments["inputs"]
                    if item["id"] not in self.missing
                ],
            }
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
        if slug == "HUBSPOT_SEARCH_COMPANIES":
            # HubSpot keeps a company's domain as the bare host and matches it exactly.
            wanted = arguments["filterGroups"][0]["filters"][0]["value"]
            found = [
                {"id": rid, "properties": {k: rec.get(k) for k in arguments["properties"]}}
                for rid, rec in self.records.items()
                if rec.get("domain") == wanted
            ]
            return {"results": found, "total": len(found)}
        if slug == "SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT":
            return {"fields": _SALESFORCE_FIELDS[arguments["object_name"]]}
        if slug == "SALESFORCE_RUN_SOQL_QUERY":
            query = arguments["query"]
            like = re.search(r"Website LIKE '%(.*)%'", query)
            if like is not None:  # Salesforce's LIKE ignores case
                wanted = like.group(1).replace("\\", "").lower()
                found = [
                    {"attributes": {"type": "Account"}, "Id": rid, **rec}
                    for rid, rec in self.records.items()
                    if wanted in str(rec.get("Website") or "").lower()
                ]
                return {"records": found, "totalSize": len(found), "done": True}
            found = [
                {"attributes": {"type": "Account"}, "Id": rid, **rec}
                for rid, rec in self.records.items()
                if f"'{rid}'" in query
            ]
            return {"records": found, "totalSize": len(found), "done": True}
        raise AssertionError(f"unexpected read {slug}")


#: The reads of a record's current values: a company in a batch, a contact on its own.
_RECORD_READS = frozenset(
    {"HUBSPOT_READ_CRM_OBJECT_BY_ID", "HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES"}
)


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
            if provider == "hubspot":
                # The contact lists these tests add to are lists Clue keeps (fix round 1 #1).
                for list_id in ("9", "10"):
                    await _keep_list(
                        conn, seeded, connection, list_id, f"List {list_id}", "contact"
                    )
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
    batch = await _prepare_batch(conn, gateway, connection, proposal_id, changes, budget)
    assert batch.refused == []
    return batch.changes


async def _prepare_batch(
    conn: Any,
    gateway: _FakeCrm,
    connection: CrmConnection,
    proposal_id: UUID,
    changes: list[ProposedChange],
    budget: Any = None,
    **pause: Any,
) -> PreparedBatch:
    project = await conn.execute(
        text("SELECT project_id FROM crm_write_proposal WHERE proposal_id = :id"),
        {"id": proposal_id},
    )
    return await prepare_changes(
        conn,
        gateway=gateway,
        budget=budget,
        connection=connection,
        proposal_id=proposal_id,
        project_id=project.scalar_one(),
        changes=changes,
        version="v-test",
        settings=SETTINGS,
        **pause,
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
        assert not [c for c in gateway.calls if c[0] in _RECORD_READS]

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
        reads = [c for c in gateway.calls if c[0] in _RECORD_READS]
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
        prepared = await _prepare(
            conn, gateway, connection, proposal_id, await clear_people(conn, seeded, [create])
        )
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
        same_people = await clear_people(conn, seeded, [same])
        assert await _prepare(conn, gateway, connection, proposal_id, same_people) == []

        # Nothing found: it stays a create, scoped by its kind.
        new = ProposedChange("HUBSPOT_CREATE_CONTACT", {"email": "bo@acme.example.com"}, "x")
        (created,) = await _prepare(
            conn, gateway, connection, proposal_id, await clear_people(conn, seeded, [new])
        )
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
            "adding records to Clue lists and campaigns",
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


async def _added_by(
    conn: Any, seeded: Any, connection: CrmConnection, project_id: str, list_ref: str, record: str
) -> None:
    """A proposal of ``project_id`` whose list add succeeded, as the executor leaves it."""
    proposal_id = uuid4()
    await writes.insert_proposal(
        conn,
        proposal_id=proposal_id,
        workspace_id=seeded.workspace_id,
        connection_id=connection.connection_id,
        project_id=project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.turn_id,
        status="finished",
    )
    write_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO crm_write (write_id, proposal_id, workspace_id, connection_id, ordinal, "
            "slug, arguments, kind, object, record_ref, record_label, overwrites_person, reason, "
            "scope_key, selected, status, idempotency_key) VALUES (:id, :proposal, :ws, :c, 0, "
            "'HUBSPOT_UPDATE_LIST_MEMBERSHIPS', CAST('{}' AS jsonb), 'list_membership', "
            "'contact', :record, :record, false, 'committee', 'kind:list_membership', true, "
            "'succeeded', :key)"
        ),
        {
            "id": write_id,
            "proposal": proposal_id,
            "ws": seeded.workspace_id,
            "c": connection.connection_id,
            "record": record,
            "key": f"crm-write:{write_id}",
        },
    )
    await writes.record_membership_link(
        conn,
        workspace_id=seeded.workspace_id,
        connection_id=connection.connection_id,
        list_ref=list_ref,
        record_ref=record,
        write_id=write_id,
    )


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
        await _added_by(conn, seeded, connection, seeded.project_id, "9", "p2")
        (removal,) = await _prepare(
            conn, gateway, connection, proposal_id, [_remove_from_list("p2")]
        )
        assert removal.scope_key == "kind:list_removal"
        card = card_snapshot([removal], provider="hubspot", project_name="Q4")
        assert card["groups"][0]["always_allow"] == (
            "removing records from Clue lists and campaigns"
        )
        assert removal.before is True and removal.after is False
        # Clue's link to p2 in list 9 says nothing about list 10.
        with pytest.raises(WriteRefused):
            await _prepare(conn, gateway, connection, proposal_id, [_remove_from_list("p2", "10")])

    _run(tmp_path, "removal", body)


def _not_found(index: int, slug: str, record_ref: str, message: str) -> RefusedChange:
    return RefusedChange(
        index=index,
        slug=slug,
        record_ref=record_ref,
        reason_code="crm_record_not_found",
        message=message,
    )


def test_a_missing_hubspot_record_refuses_only_its_own_change(tmp_path: Path) -> None:
    """R-11.7 (live check L6): HubSpot's 404 for one company refused the whole batch."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={
                "101": {"icp_tier": "Tier 3", "name": "Cargoloop"},
                "102": {"icp_tier": None, "name": "Stackfield"},
            },
            missing=frozenset({"999999999999"}),
        )
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                _set_company("101", "icp_tier", "Tier 1"),
                _set_company("999999999999", "icp_tier", "Tier 1"),
                _set_company("102", "icp_tier", "Tier 2"),
            ],
        )
        assert batch.refused == [
            _not_found(
                1,
                "HUBSPOT_UPDATE_COMPANY",
                "999999999999",
                "HubSpot has no company 999999999999.",
            )
        ]
        assert [
            (p.parsed.record_ref, p.parsed.label, p.field, p.before, p.after) for p in batch.changes
        ] == [
            ("101", "Cargoloop", "icp_tier", "Tier 3", "Tier 1"),
            ("102", "Stackfield", "icp_tier", None, "Tier 2"),
        ]

    _run(tmp_path, "hsmissing", body)


def test_a_salesforce_record_the_read_does_not_return_refuses_only_its_own_change(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={
                "001A": {"Industry": "Retail", "Name": "Aldercare"},
                "001B": {"Industry": None, "Name": "Birchwood"},
            }
        )
        changes = [
            ProposedChange(
                "SALESFORCE_UPDATE_ACCOUNT", {"account_id": rid, "industry": "Hospitality"}, "x"
            )
            for rid in ("001A", "001Z", "001B")
        ]
        batch = await _prepare_batch(
            conn, gateway, connection, proposal_id, changes, _FakeBudget(gateway)
        )
        assert batch.refused == [
            _not_found(1, "SALESFORCE_UPDATE_ACCOUNT", "001Z", "Salesforce has no account 001Z.")
        ]
        # Never shown as empty: the missing account is not on the card at all.
        assert [(p.parsed.record_ref, p.before, p.after) for p in batch.changes] == [
            ("001A", "Retail", "Hospitality"),
            ("001B", None, "Hospitality"),
        ]

    _run(tmp_path, "sfmissing", body, provider="salesforce")


def test_a_batch_whose_every_record_is_missing_prepares_nothing_and_lists_each(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(missing=frozenset({"901", "902"}))
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            await clear_people(
                conn,
                seeded,
                [
                    _set_company("901", "icp_tier", "Tier 1"),
                    _set_contact("902", {"jobtitle": "COO"}),
                ],
            ),
        )
        assert batch.changes == []
        assert batch.refused == [
            _not_found(0, "HUBSPOT_UPDATE_COMPANY", "901", "HubSpot has no company 901."),
            _not_found(1, "HUBSPOT_UPDATE_CONTACTS", "902", "HubSpot has no contact 902."),
        ]

    _run(tmp_path, "allmissing", body)


_RATE_LIMITED = ExecuteResult(
    False,
    {"http_error": "429", "status_code": 429},
    '{"status":"error","message":"You have reached your secondly limit.","category":"RATE_LIMITS"}',
)


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (
            ExecuteResult(
                False,
                {"http_error": "401", "status_code": 401},
                '{"status":"error","message":"Authentication credentials not found.",'
                '"category":"INVALID_AUTHENTICATION"}',
            ),
            "crm_read_failed",
        ),
        # A rate limit or an unreachable CRM is temporary, not a failed read (final review I-3).
        (_RATE_LIMITED, "crm_rate_limited"),
        (
            ExecuteResult(False, {"http_error": "502", "status_code": 502}, "Bad Gateway"),
            "crm_unavailable",
        ),
    ],
)
def test_a_read_that_fails_for_any_other_reason_still_refuses_the_whole_batch(
    tmp_path: Path, failure: ExecuteResult, code: str
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={"101": {"icp_tier": None}, "201": {"jobtitle": None}},
            failing=dict.fromkeys(_RECORD_READS, failure),
        )
        for change in await clear_people(
            conn,
            seeded,
            [_set_company("101", "icp_tier", "Tier 1"), _set_contact("201", {"jobtitle": "COO"})],
        ):
            with pytest.raises(WriteRefused) as refused:
                await _prepare_batch(conn, gateway, connection, proposal_id, [change])
            assert refused.value.reason_code == code

    _run(tmp_path, "readfail", body)


def test_a_rate_limited_field_list_read_is_temporary(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={"101": {}},
            failing={"HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE": _RATE_LIMITED},
        )
        with pytest.raises(WriteRefused) as refused:
            await _prepare_batch(
                conn, gateway, connection, proposal_id, [_set_company("101", "icp_tier", "Tier 1")]
            )
        assert refused.value.reason_code == "crm_rate_limited"

    _run(tmp_path, "fieldlimit", body)


def test_hubspot_companies_are_read_in_batches_of_100(tmp_path: Path) -> None:
    """Final review I-3: one read per 100 companies, not one per company."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        ids = [str(1000 + n) for n in range(150)]
        gateway = _FakeCrm(records={rid: {"icp_tier": None, "name": f"Co {rid}"} for rid in ids})
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_set_company(rid, "icp_tier", "Tier 1") for rid in ids],
        )
        assert len(prepared) == 150
        assert {p.parsed.label for p in prepared} == {f"Co {rid}" for rid in ids}
        batches = [
            c[1] for c in gateway.calls if c[0] == "HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES"
        ]
        assert [len(b["inputs"]) for b in batches] == [100, 50]
        assert set(batches[0]["properties"]) == {"icp_tier", "name", "domain"}
        assert not [c for c in gateway.calls if c[0] == "HUBSPOT_READ_CRM_OBJECT_BY_ID"]

    _run(tmp_path, "batched", body)


def test_prepare_pauses_between_its_reads(tmp_path: Path) -> None:
    """R-7.3's pause between calls covers the reads before the card too."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        slept: list[float] = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)

        gateway = _FakeCrm(records={"101": {"icp_tier": None}, "201": {"jobtitle": None}})
        await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            await clear_people(
                conn,
                seeded,
                [
                    _set_company("101", "icp_tier", "Tier 1"),
                    _set_contact("201", {"jobtitle": "COO"}),
                ],
            ),
            min_interval_s=0.25,
            sleep=sleep,
        )
        assert len(gateway.calls) > 1
        assert slept == [0.25] * (len(gateway.calls) - 1)

    _run(tmp_path, "pause", body)


def test_a_read_with_no_answer_is_not_taken_for_a_missing_record(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        unreachable = ComposioError("unavailable", None, "ConnectTimeout")
        gateway = _FakeCrm(failing=dict.fromkeys(_RECORD_READS, unreachable))
        with pytest.raises(ComposioError):
            await _prepare_batch(
                conn, gateway, connection, proposal_id, [_set_company("101", "icp_tier", "Tier 1")]
            )

    _run(tmp_path, "noanswer", body)


@pytest.mark.parametrize(
    ("malformed", "change"),
    [
        ("HUBSPOT_READ_CRM_OBJECT_BY_ID", _set_contact("101", {"jobtitle": "COO"})),
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
            await _prepare(
                conn, gateway, connection, proposal_id, await clear_people(conn, seeded, [change])
            )
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
            await clear_people(
                conn,
                seeded,
                [
                    _set_company("101", "icp_tier", "Tier 1"),
                    _set_company("102", "icp_tier", "Tier 1"),
                    _set_company("103", "icp_tier", "Tier 1"),
                    _set_contact("201", {"jobtitle": "COO"}),
                    _set_contact("202", {"jobtitle": "CFO"}),
                ],
            ),
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
        (companies,) = [
            c[1] for c in gateway.calls if c[0] == "HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES"
        ]
        assert [item["id"] for item in companies["inputs"]] == ["101", "102", "103"]
        assert set(companies["properties"]) == {"icp_tier", "name", "domain"}
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
            conn,
            gateway,
            connection,
            proposal_id,
            await clear_people(conn, seeded, changes),
            _FakeBudget(gateway),
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


def _create_account(name: str, website: str) -> ProposedChange:
    return ProposedChange("SALESFORCE_CREATE_ACCOUNT", {"name": name, "website": website}, "x")


def test_a_salesforce_account_create_finds_its_record_by_the_website_host(tmp_path: Path) -> None:
    """Final review I-5: "https://www.Acme.com/about" and "acme.com" are one company."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(
            records={
                "001A": {"Name": "Acme", "Website": "https://www.Acme.com/about"},
                "001B": {"Name": "Notacme", "Website": "notacme.com"},
            }
        )
        budget = _FakeBudget(gateway)
        found = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_create_account("Acme Corp", "acme.com")],
            budget,
        )
        # The create became an update of the account it would have duplicated.
        assert [(p.parsed.record_ref, p.field, p.after) for p in found] == [
            ("001A", "Name", "Acme Corp")
        ]
        (query,) = [c[1]["query"] for c in gateway.calls if c[0] == "SALESFORCE_RUN_SOQL_QUERY"]
        assert "WHERE Website LIKE '%acme.com%'" in query

        # A host that only appears inside another company's website is not a match.
        other = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_create_account("Cme", "https://cme.com/")],
            budget,
        )
        assert [(p.parsed.record_ref, p.parsed.change_kind(p.spec)) for p in other] == [
            (None, "create_company")
        ]

    _run(tmp_path, "sfwebsite", body, provider="salesforce")


@pytest.mark.parametrize(
    ("provider", "changes"),
    [
        (
            "hubspot",
            [
                ProposedChange("HUBSPOT_CREATE_CONTACT", {"email": "Ana@acme.example.com"}, "x"),
                ProposedChange("HUBSPOT_CREATE_CONTACT", {"email": " ana@acme.example.com"}, "x"),
            ],
        ),
        (
            "hubspot",
            [
                ProposedChange(
                    "HUBSPOT_CREATE_COMPANY", {"name": "Acme", "domain": "acme.com"}, "x"
                ),
                ProposedChange(
                    "HUBSPOT_CREATE_COMPANY", {"name": "Acme Inc", "domain": "www.acme.com"}, "x"
                ),
            ],
        ),
        (
            "salesforce",
            [_create_account("Acme", "https://acme.com"), _create_account("Acme", "www.acme.com/")],
        ),
    ],
)
def test_two_creates_of_one_record_in_a_batch_are_refused(
    tmp_path: Path, provider: str, changes: list[ProposedChange]
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm()
        with pytest.raises(WriteRefused) as refused:
            await _prepare(conn, gateway, connection, proposal_id, changes, _FakeBudget(gateway))
        assert refused.value.reason_code == "crm_write_not_parsable"
        assert "proposed twice in this batch" in str(refused.value)
        assert gateway.calls == []  # refused before any read

    _run(tmp_path, f"twice{provider}", body, provider=provider)


def test_a_field_the_crm_does_not_have_refuses_only_its_own_change(tmp_path: Path) -> None:
    """Final review M-2: a typo'd property is refused before the card, not at send."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"101": {}, "102": {"icp_tier": None}})
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_set_company("101", "zz_foo", "x"), _set_company("102", "icp_tier", "Tier 2")],
        )
        assert batch.refused == [
            RefusedChange(
                index=0,
                slug="HUBSPOT_UPDATE_COMPANY",
                record_ref="101",
                reason_code="crm_field_unknown",
                message="HubSpot companies have no property zz_foo.",
            )
        ]
        assert [(p.parsed.record_ref, p.field) for p in batch.changes] == [("102", "icp_tier")]

    _run(tmp_path, "unknownfield", body)


def test_a_salesforce_field_the_org_does_not_have_refuses_only_its_own_change(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"001A": {"Industry": None}, "001B": {"Industry": None}})
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                ProposedChange(
                    "SALESFORCE_UPDATE_ACCOUNT",
                    {"account_id": "001A", "custom_fields": {"Zz__c": "x"}},
                    "x",
                ),
                ProposedChange(
                    "SALESFORCE_UPDATE_ACCOUNT", {"account_id": "001B", "industry": "Retail"}, "x"
                ),
            ],
            _FakeBudget(gateway),
        )
        assert [(r.index, r.reason_code, r.message) for r in batch.refused] == [
            (0, "crm_field_unknown", "Salesforce accounts have no field Zz__c.")
        ]
        assert [(p.parsed.record_ref, p.field) for p in batch.changes] == [("001B", "Industry")]

    _run(tmp_path, "sfunknownfield", body, provider="salesforce")


# --- Phase 3: lists Clue creates, and company lists (Task 3) ---------------------------------


def _create_list(name: str, object_type_id: str = "0-2") -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_CREATE_LIST",
        {"name": name, "object_type_id": object_type_id, "processing_type": "MANUAL"},
        "the project's target accounts",
    )


async def _keep_list(
    conn: Any,
    seeded: Any,
    connection: CrmConnection,
    crm_list_id: str,
    name: str,
    crm_object: str = "company",
) -> None:
    from clue_api.crm.lists import store_list

    await store_list(
        conn,
        workspace_id=seeded.workspace_id,
        connection_id=connection.connection_id,
        provider=connection.provider,
        crm_object=crm_object,  # type: ignore[arg-type]
        crm_list_id=crm_list_id,
        name=name,
        kind="hubspot_list" if connection.provider == "hubspot" else "salesforce_campaign",
        created_by_clue=True,
        created_by_write_id=None,
        project_id=seeded.project_id,
    )


def test_a_list_create_is_prepared_without_any_read(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm()
        (change,) = await _prepare(
            conn, gateway, connection, proposal_id, [_create_list("Clue: Q4 hotel groups")]
        )
        assert gateway.calls == []  # no before-value: the list does not exist yet
        assert change.parsed.change_kind(change.spec) == "list_create"
        assert (change.parsed.object, change.parsed.label) == ("company", "Clue: Q4 hotel groups")
        assert change.before is None and change.overwrites_person is False
        assert change.scope_key == "kind:list_create"
        assert change.arguments == {
            "name": "Clue: Q4 hotel groups",
            "object_type_id": "0-2",
            "processing_type": "MANUAL",
        }
        card = card_snapshot([change], provider="hubspot", project_name="Q4 hotel groups")
        (group,) = card["groups"]
        assert group["title"] == 'Create the list "Clue: Q4 hotel groups"'
        assert group["always_allow"] == "creating Clue lists"
        assert group["object"] == "list"
        assert [r["name"] for r in group["records"]] == ["Clue: Q4 hotel groups"]

        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=[change],
        )
        row = (
            await conn.execute(
                text(
                    "SELECT kind, object, record_ref, record_label FROM crm_write "
                    "WHERE proposal_id = :p"
                ),
                {"p": proposal_id},
            )
        ).one()
        assert tuple(row) == ("list_create", "company", None, "Clue: Q4 hotel groups")

    _run(tmp_path, "listcreate", body)


def test_a_salesforce_campaign_create_is_worded_as_a_campaign(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm()
        changes = [
            ProposedChange("SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q4"}, "committee"),
            ProposedChange("SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q1"}, "committee"),
        ]
        prepared = await _prepare(conn, gateway, connection, proposal_id, changes)
        assert gateway.calls == []
        card = card_snapshot(prepared, provider="salesforce", project_name="Q4")
        # Two lists are two groups, each named.
        assert [g["title"] for g in card["groups"]] == [
            'Create the campaign "Clue: Q4"',
            'Create the campaign "Clue: Q1"',
        ]
        assert [s["phrase"] for s in card["standing_permissions"]] == ["creating Clue campaigns"]

    _run(tmp_path, "campaigncreate", body, provider="salesforce")


def test_a_list_clue_already_keeps_is_not_created_again(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        from clue_api.crm.lists import mark_gone

        gateway = _FakeCrm()
        await _keep_list(conn, seeded, connection, "17", "Clue: Q4 hotel groups")
        with pytest.raises(WriteRefused) as refused:
            await _prepare(
                conn, gateway, connection, proposal_id, [_create_list("clue: q4 hotel groups")]
            )
        assert refused.value.reason_code == "crm_list_exists"
        assert "17" in str(refused.value)

        # Two creates of one name in one batch are refused too.
        with pytest.raises(WriteRefused) as twice:
            await _prepare(
                conn,
                gateway,
                connection,
                proposal_id,
                [_create_list("Clue: Q1"), _create_list("Clue: q1")],
            )
        assert twice.value.reason_code == "crm_write_not_parsable"

        # A list the CRM no longer has may be created again (R-11.11 (4)).
        await mark_gone(conn, connection_id=connection.connection_id, crm_list_id="17")
        (again,) = await _prepare(
            conn, gateway, connection, proposal_id, [_create_list("Clue: Q4 hotel groups")]
        )
        assert again.parsed.change_kind(again.spec) == "list_create"

    _run(tmp_path, "listexists", body)


def test_company_list_membership_parses_companies(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        await _keep_list(conn, seeded, connection, "17", "Clue: Q4 hotel groups")
        gateway = _FakeCrm(lists={"101": [], "102": ["17"], "201": []})
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_add_to_list("101", "17"), _add_to_list("102", "17"), _add_to_list("201", "9")],
        )
        # 102 is already in the list: nothing to change.
        company, contact = prepared
        assert (company.parsed.object, company.parsed.record_ref) == ("company", "101")
        # A contact list Clue keeps holds contacts.
        assert (contact.parsed.object, contact.parsed.record_ref) == ("contact", "201")
        reads = {
            c[1]["record_id"]: c[1]["object_type_id"]
            for c in gateway.calls
            if c[0] == "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS"
        }
        assert reads == {"101": "0-2", "102": "0-2", "201": "0-1"}

        card = card_snapshot([company], provider="hubspot", project_name="Q4")
        (group,) = card["groups"]
        assert group["title"] == 'Add 1 company to the list "17"'
        assert group["object"] == "company"
        # R-12.8: one scope for every list and campaign add, worded for all of them.
        assert group["always_allow"] == "adding records to Clue lists and campaigns"

        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=prepared,
        )
        objects = await conn.execute(
            text("SELECT record_ref, object FROM crm_write WHERE proposal_id = :p"),
            {"p": proposal_id},
        )
        assert dict(objects.all()) == {"101": "company", "201": "contact"}

    _run(tmp_path, "companylist", body)


LIST_NOT_KEPT = "Clue does not keep this list yet. Link it first with link_crm_list."
LIST_GONE = "The list no longer exists in HubSpot; find it by name or create it again."


def test_a_change_to_a_list_clue_does_not_keep_is_refused_alone(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(lists={"201": [], "202": ["55"], "203": []})
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_add_to_list("201", "55"), _remove_from_list("202", "55"), _add_to_list("203")],
        )
        # The add to list 9 (kept) goes on; both changes to list 55 are refused on their own,
        # the removal before any check of who added the member.
        assert [c.parsed.record_ref for c in batch.changes] == ["203"]
        assert [(r.index, r.reason_code, r.message) for r in batch.refused] == [
            (0, "crm_list_not_kept", LIST_NOT_KEPT),
            (1, "crm_list_not_kept", LIST_NOT_KEPT),
        ]
        # Nothing was read for a refused change.
        read = [c[1]["record_id"] for c in gateway.calls]
        assert read == ["203"]

    _run(tmp_path, "notkept", body)


def test_an_add_to_a_kept_list_that_is_gone_is_refused_alone(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        from clue_api.crm.lists import mark_gone

        await _keep_list(conn, seeded, connection, "17", "Clue: Q4")
        await mark_gone(conn, connection_id=connection.connection_id, crm_list_id="17")
        gateway = _FakeCrm(lists={"101": [], "201": []})
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_add_to_list("101", "17"), _add_to_list("201")],
        )
        assert [c.parsed.record_ref for c in batch.changes] == ["201"]
        assert [(r.index, r.reason_code, r.message) for r in batch.refused] == [
            (0, "crm_list_gone", LIST_GONE),
        ]

    _run(tmp_path, "keptgone", body)


# --- Task 3b (R-12.7): a list Clue creates and its first members are one card ----------------


def _add_to_new(record: str, name: str = "Clue: Q4", operation: str = "add") -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        {"list_id": f"new:{name}", "operation": operation, "record_ids": [record]},
        "the project's target accounts",
    )


def test_a_new_list_and_its_first_members_are_one_card(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm()
        # The agent may list the adds before the create: the create still comes first.
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [_add_to_new("101"), _create_list("Clue: Q4"), _add_to_new("102")],
        )
        # Nothing to read: the list is new, so it has no members yet.
        assert gateway.calls == []
        create, first, second = prepared
        assert create.parsed.change_kind(create.spec) == "list_create"
        for add in (first, second):
            assert add.parsed.change_kind(add.spec) == "list_membership"
            assert add.parsed.object == "company"  # the new list's object
            assert (add.before, add.after) == (False, True)
            assert add.arguments["list_id"] == "new:Clue: Q4"
        assert [first.parsed.record_ref, second.parsed.record_ref] == ["101", "102"]

        card = card_snapshot(prepared, provider="hubspot", project_name="Q4")
        assert [g["title"] for g in card["groups"]] == [
            'Create the list "Clue: Q4"',
            'Add 2 companies to the list "Clue: Q4"',
        ]
        assert card["allow_count"] == 3

    _run(tmp_path, "newlist", body)


def test_a_placeholder_naming_no_create_is_refused_alone(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        batch = await _prepare_batch(
            conn,
            _FakeCrm(),
            connection,
            proposal_id,
            [
                _create_list("Clue: Q4"),
                _add_to_new("101", "Clue: Q1"),  # no such create in the batch
                _add_to_new("102", operation="remove"),  # a new list has no members to remove
                _add_to_new("103", "clue: q4"),  # the name must be the create's, exactly
                _add_to_new("104"),
            ],
        )
        assert [c.parsed.record_ref for c in batch.changes] == [None, "104"]
        assert [(r.index, r.reason_code) for r in batch.refused] == [
            (1, "crm_write_not_parsable"),
            (2, "crm_write_not_parsable"),
            (3, "crm_write_not_parsable"),
        ]
        assert "new:Clue: Q1" in batch.refused[0].message

    _run(tmp_path, "newlistbad", body)


def test_a_new_campaign_and_its_contacts_are_one_card(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm()
        prepared = await _prepare(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                ProposedChange("SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q4"}, "committee"),
                ProposedChange(
                    "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN",
                    {"campaign_id": "new:Clue: Q4", "contact_id": "003A"},
                    "committee",
                ),
            ],
            _FakeBudget(gateway),
        )
        assert gateway.calls == []
        card = card_snapshot(prepared, provider="salesforce", project_name="Q4")
        assert [g["title"] for g in card["groups"]] == [
            'Create the campaign "Clue: Q4"',
            'Add 1 contact to the campaign "Clue: Q4"',
        ]

    _run(tmp_path, "newcampaign", body, provider="salesforce")


def test_a_covered_create_and_its_uncovered_adds_wait_for_one_card(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        await writes.insert_grant(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            scope_key="kind:list_create",
            granted_by_user_id=USER_ID,
        )
        create, add = await _prepare(
            conn,
            _FakeCrm(),
            connection,
            proposal_id,
            [_create_list("Clue: Q4"), _add_to_new("101")],
        )
        # Each permission applies on its own: the create is covered, the add asks.
        assert create.covered_by is not None and add.covered_by is None
        card = card_snapshot([create, add], provider="hubspot", project_name="Q4")
        assert [g["title"] for g in card["groups"]] == ['Add 1 company to the list "Clue: Q4"']

    _run(tmp_path, "newlistgrant", body)


def test_a_campaign_is_proposed_active_and_in_progress(tmp_path: Path) -> None:
    """R-12.9: the agent names the campaign; Clue creates it active, status "In Progress"."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        (create,) = await _prepare(
            conn,
            _FakeCrm(),
            connection,
            proposal_id,
            [ProposedChange("SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q4"}, "committee")],
        )
        expected = {"name": "Clue: Q4", "is_active": True, "status": "In Progress"}
        assert create.arguments == expected
        assert create.after == expected
        card = card_snapshot([create], provider="salesforce", project_name="Q4")
        (group,) = card["groups"]
        assert group["title"] == 'Create the campaign "Clue: Q4"'
        assert group["value_summary"] == 'Active, status "In Progress"'

        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=[create],
        )
        row = (
            await conn.execute(
                text("SELECT arguments, after_value FROM crm_write WHERE proposal_id = :p"),
                {"p": proposal_id},
            )
        ).one()
        assert row.arguments == row.after_value == expected

    _run(tmp_path, "campaignactive", body, provider="salesforce")


# --- a person value reaches the CRM only as Clue researched and cleared it (Phase 3, Task 5) ---


async def _researched(conn: Any, seeded: Any) -> Any:
    """Zafran in this project, scored High (tier_1), with two researched committee members:
    Nick (champion, verified email, title, LinkedIn) and Vari (a catch-all email)."""
    from clue_api.arv2.catalog_seed import load_arv2_pack
    from clue_research.profiling.committee.fields import load_committee_pack
    from tests.api.test_crm_targets_db import _World

    await load_committee_pack(conn)
    await load_arv2_pack(conn)
    world: Any = _World(conn, seeded)
    world.zafran = await world.account("Zafran Security", "zafran.io")
    await world.fit("fit", world.zafran, 0.81, world.project_id)
    world.nick = await world.person(
        world.zafran, "Nick Fisher", linkedin="https://www.linkedin.com/in/nickfisher"
    )
    await world.claim("nick_persona", world.nick, "contact.persona", "champion")
    await world.claim("nick_title", world.nick, "contact.current_title", "VP Marketing")
    await world.claim(
        "nick_email",
        world.nick,
        "core.work_email",
        {"address": "nick@zafran.io", "status": "verified_smtp"},
    )
    world.vari = await world.person(world.zafran, "Vari Bindra")
    await world.claim("vari_persona", world.vari, "contact.persona", "user")
    await world.claim(
        "vari_email",
        world.vari,
        "core.work_email",
        {"address": "vari@zafran.io", "status": "catch_all_valid"},
    )
    return world


def _create_person(fields: Mapping[str, object], clue_entity_id: object | None) -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_CREATE_CONTACT",
        dict(fields),
        "the buying committee",
        clue_entity_id=None if clue_entity_id is None else str(clue_entity_id),
    )


_NICK = {
    "firstname": "Nick",
    "lastname": "Fisher",
    "jobtitle": "VP Marketing",
    "email": "nick@zafran.io",
    "hs_buying_role": "CHAMPION",
    "hs_linkedin_url": "https://www.linkedin.com/in/nickfisher",
}


def _refusal(batch: PreparedBatch) -> list[tuple[int, str]]:
    return [(r.index, r.reason_code) for r in batch.refused]


def test_a_person_change_without_a_clue_contact_is_refused(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        await _researched(conn, seeded)
        gateway = _FakeCrm(records={"101": {"icp_tier": None}, "201": {"jobtitle": None}})
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_set_company("101", "icp_tier", "Tier 1"), _set_contact("201", {"jobtitle": "CEO"})],
        )
        assert _refusal(batch) == [(1, "crm_personal_data_not_allowed")]
        assert batch.refused[0].message == "Name the Clue contact this is about."
        assert [c.field for c in batch.changes] == ["icp_tier"]

    _run(tmp_path, "nocontact", body)


def test_an_email_the_agent_typed_is_refused_but_the_rest_proposes(tmp_path: Path) -> None:
    """Review Focus 5: one wrong value refuses its own change; the matching one goes on."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        typed = {**_NICK, "email": "n.fisher@zafran.io"}
        batch = await _prepare_batch(
            conn,
            _FakeCrm(),
            connection,
            proposal_id,
            [
                _create_person(typed, world.nick),
                _create_person({**_NICK, "email": "NICK@zafran.io "}, world.nick),
            ],
        )
        assert _refusal(batch) == [(0, "crm_personal_data_not_allowed")]
        message = batch.refused[0].message
        assert "email" in message and "not what Clue researched" in message
        assert "n.fisher" not in message  # the rejected value is never echoed
        (created,) = batch.changes
        assert created.spec.slug == "HUBSPOT_CREATE_CONTACT"

    _run(tmp_path, "typedemail", body)


def test_a_catch_all_email_is_refused_with_its_reason(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        batch = await _prepare_batch(
            conn,
            _FakeCrm(),
            connection,
            proposal_id,
            [
                _create_person(
                    {"firstname": "Vari", "lastname": "Bindra", "email": "vari@zafran.io"},
                    world.vari,
                )
            ],
        )
        assert _refusal(batch) == [(0, "crm_personal_data_not_allowed")]
        assert "not verified (catch_all_valid)" in batch.refused[0].message
        assert "vari@zafran.io" not in batch.refused[0].message
        assert batch.changes == []

    _run(tmp_path, "catchall", body)


def test_a_matching_contact_create_proposes_with_its_claim_ids(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        (created,) = await _prepare(
            conn,
            _FakeCrm(),
            connection,
            proposal_id,
            [_create_person({**_NICK, "lastname": " Fisher  "}, world.nick)],
        )
        assert created.clue_entity_id == str(world.nick)
        assert set(created.source_claim_ids) == {
            world.claims["nick_persona"],
            world.claims["nick_title"],
            world.claims["nick_email"],
        }
        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=[created],
        )
        row = (
            await conn.execute(
                text(
                    "SELECT source_claim_ids, clue_entity_id FROM crm_write WHERE proposal_id = :p"
                ),
                {"p": proposal_id},
            )
        ).one()
        assert set(row.source_claim_ids) == set(created.source_claim_ids)
        assert row.clue_entity_id == str(world.nick)

    _run(tmp_path, "matching", body)


def test_a_contact_update_cites_only_its_own_fields_claims(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        gateway = _FakeCrm(records={"201": {"jobtitle": None, "email": "nick@zafran.io"}})
        change = ProposedChange(
            "HUBSPOT_UPDATE_CONTACTS",
            {"inputs": [{"id": "201", "properties": {"jobtitle": "VP Marketing"}}]},
            "title",
            clue_entity_id=str(world.nick),
        )
        (update,) = await _prepare(conn, gateway, connection, proposal_id, [change])
        assert update.source_claim_ids == (world.claims["nick_title"],)
        assert update.clue_entity_id == str(world.nick)

        wrong = ProposedChange(
            "HUBSPOT_UPDATE_CONTACTS",
            {"inputs": [{"id": "201", "properties": {"jobtitle": "Chief Everything"}}]},
            "title",
            clue_entity_id=str(world.nick),
        )
        batch = await _prepare_batch(conn, gateway, connection, proposal_id, [wrong])
        assert _refusal(batch) == [(0, "crm_personal_data_not_allowed")]
        assert "Chief Everything" not in batch.refused[0].message

    _run(tmp_path, "contactupdate", body)


def test_the_buying_role_is_added_and_never_removes_one(tmp_path: Path) -> None:
    """hs_buying_role is multi-select (Task 1 ledger ruling): Clue writes the union of the roles
    the contact already has and its own, and a value that drops a role is refused."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        gateway = _FakeCrm(
            records={
                "201": {"hs_buying_role": "BLOCKER;END_USER"},
                "202": {"hs_buying_role": "BLOCKER;END_USER"},
                "203": {"hs_buying_role": "CHAMPION"},
            }
        )

        def role(record: str, value: str) -> ProposedChange:
            return ProposedChange(
                "HUBSPOT_UPDATE_CONTACTS",
                {"inputs": [{"id": record, "properties": {"hs_buying_role": value}}]},
                "role",
                clue_entity_id=str(world.nick),
            )

        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [role("201", "CHAMPION"), role("202", "CHAMPION;END_USER"), role("203", "CHAMPION")],
        )
        # Clue's role alone is composed with the roles already there; the same role already
        # held is no change.
        (added,) = batch.changes
        assert added.parsed.record_ref == "201"
        assert added.after == "BLOCKER;END_USER;CHAMPION"
        assert added.arguments == {
            "inputs": [{"id": "201", "properties": {"hs_buying_role": "BLOCKER;END_USER;CHAMPION"}}]
        }
        assert added.source_claim_ids == (world.claims["nick_persona"],)
        assert _refusal(batch) == [(1, "crm_personal_data_not_allowed")]
        assert "never removes one" in batch.refused[0].message

        other = await _prepare_batch(
            conn, gateway, connection, proposal_id, [role("201", "BUDGET_HOLDER")]
        )
        assert _refusal(other) == [(0, "crm_personal_data_not_allowed")]
        assert "not what Clue researched" in other.refused[0].message

    _run(tmp_path, "buyingrole", body)


def test_a_company_tier_must_match_the_fit_band(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        gateway = _FakeCrm(
            records={
                "101": {"hs_ideal_customer_profile": None, "hs_is_target_account": None},
                "102": {"hs_ideal_customer_profile": None},
                "103": {"hs_is_target_account": "true"},
            }
        )

        def company(record: str, fields: Mapping[str, object]) -> ProposedChange:
            return ProposedChange(
                "HUBSPOT_UPDATE_COMPANY",
                {"companyId": record, "properties": dict(fields)},
                "tiers",
                clue_entity_id=str(world.zafran),
            )

        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                company(
                    "101", {"hs_ideal_customer_profile": "tier_1", "hs_is_target_account": True}
                ),
                company("102", {"hs_ideal_customer_profile": "tier_2"}),
                company("103", {"hs_is_target_account": False}),
            ],
        )
        assert _refusal(batch) == [
            (1, "crm_personal_data_not_allowed"),
            (2, "crm_personal_data_not_allowed"),
        ]
        assert all("tier_2" not in r.message for r in batch.refused)
        tier = next(c for c in batch.changes if c.field == "hs_ideal_customer_profile")
        assert tier.after == "tier_1"
        assert tier.source_claim_ids == (world.claims["fit"],)
        assert tier.clue_entity_id == str(world.zafran)
        target = next(c for c in batch.changes if c.field == "hs_is_target_account")
        assert target.source_claim_ids == ()

    _run(tmp_path, "tier", body)


def test_a_contact_of_another_workspace_is_refused(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        await _researched(conn, seeded)
        theirs = await _seed(conn, tmp_path, workspace_id="ws-crmw-theirs", label="theirs")
        their_world = await _researched(conn, theirs)
        batch = await _prepare_batch(
            conn,
            _FakeCrm(),
            connection,
            proposal_id,
            [
                _create_person(_NICK, their_world.nick),
                _create_person({**_NICK, "email": "nick.f@zafran.io"}, "not-a-uuid"),
            ],
        )
        assert _refusal(batch) == [
            (0, "crm_personal_data_not_allowed"),
            (1, "crm_personal_data_not_allowed"),
        ]
        assert batch.changes == []

    _run(tmp_path, "otherws", body)


def test_a_domain_spelled_differently_finds_the_existing_company(tmp_path: Path) -> None:
    """Review Focus 2, HubSpot: the search uses the host HubSpot keeps in ``domain``."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"501": {"domain": "acme.com", "name": "Acme"}})
        for spelling in ("https://www.Acme.com/", "www.acme.com", "acme.com/"):
            create = ProposedChange(
                "HUBSPOT_CREATE_COMPANY", {"name": "Acme", "domain": spelling}, "x"
            )
            assert await _prepare(conn, gateway, connection, proposal_id, [create]) == []
        searches = [a for slug, a in gateway.calls if slug == "HUBSPOT_SEARCH_COMPANIES"]
        assert {s["filterGroups"][0]["filters"][0]["value"] for s in searches} == {"acme.com"}

    _run(tmp_path, "hsdomain", body)


def test_a_salesforce_website_spelled_differently_finds_the_existing_account(
    tmp_path: Path,
) -> None:
    """Review Focus 2, Salesforce: the I-5 host match."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        gateway = _FakeCrm(records={"001A": {"Name": "Acme", "Website": "https://acme.com"}})
        budget = _FakeBudget(gateway)
        for spelling in ("www.Acme.com/", "http://acme.com/about"):
            assert (
                await _prepare(
                    conn,
                    gateway,
                    connection,
                    proposal_id,
                    [_create_account("Acme", spelling)],
                    budget,
                )
                == []
            )

    _run(tmp_path, "sfdomain", body, provider="salesforce")
