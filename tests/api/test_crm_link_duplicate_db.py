"""Duplicate links (CRM integration Phase 4, Task 5; R-6.13, R-6.14, R-13.5).

Clue never merges CRM records. A duplicate is only two (or more) CRM contacts Clue's
find-before-create finds for one Clue person (R-13.5): the create is refused, naming them, and
the agent may propose a ``link_duplicate`` between them. On HubSpot that is the contacts-to-contacts
"Possible duplicate" association label Clue's setup made; on Salesforce Clue's lookup field
``Clue_Possible_Duplicate__c`` on one contact, pointing at the other. Both records must be the
person Clue researched (their email, read before the card). Without Clue's fields set up, Clue
writes nothing (R-6.14). Clue removes only a link it made itself (an undo of its own change).

The CRM is a fake gateway; the database is the lane's test DB.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from clue_api.crm import writes
from clue_api.crm.clue_fields import CLUE_FIELDS, record_clue_fields
from clue_api.crm.composio_gateway import ExecuteResult
from clue_api.crm.connections import CrmConnection
from clue_api.crm.write_actions import WriteNotParsable, write_spec
from clue_api.crm.write_prepare import PreparedBatch, ProposedChange, card_snapshot
from tests.api.test_crm_write_executor_db import (
    _WRITE_SLUGS,
    _handle,
    _handler,
    _writes,
    _WritingCrm,
)
from tests.api.test_crm_write_prepare_db import (
    _NICK,
    _FakeBudget,
    _prepare_batch,
    _refusal,
    _researched,
    _run,
)
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


_LINK_SLUG = "HUBSPOT_CREATE_OBJECT_ASSOCIATION"
_SF_LINK_FIELD = "Clue_Possible_Duplicate__c"
_CANT_LINK = "Clue can't link duplicates in {crm} until Clue's fields are set up."
_NOT_THE_PERSON = "This CRM record is not the person Clue researched."


class _Crm(_WritingCrm):
    """The executor's fake, plus Salesforce's contact search by email and HubSpot's association
    create (answered as HubSpot's v4 association answer)."""

    def _answer(self, slug: str, arguments: Mapping[str, Any]) -> Any:
        query = str(arguments.get("query", ""))
        by_email = re.search(r"WHERE Email = '([^']*)'", query)
        if slug == "SALESFORCE_RUN_SOQL_QUERY" and by_email is not None:
            wanted = by_email.group(1).lower()  # Salesforce matches an email without case
            found = [
                {"attributes": {"type": "Contact"}, "Id": rid, **rec}
                for rid, rec in self.records.items()
                if str(rec.get("Email") or "").lower() == wanted
            ]
            return {"records": found, "totalSize": len(found), "done": True}
        by_id = re.search(r"WHERE Id IN \(([^)]*)\)", query)
        if slug == "SALESFORCE_RUN_SOQL_QUERY" and by_id is not None:
            # Salesforce finds a record by its 15- or 18-character id and answers 18 characters.
            wanted = {i.strip("' ")[:15] for i in by_id.group(1).split(",")}
            found = [
                {"attributes": {"type": "Contact"}, "Id": rid, **rec}
                for rid, rec in self.records.items()
                if rid[:15] in wanted
            ]
            return {"records": found, "totalSize": len(found), "done": True}
        return super()._answer(slug, arguments)

    def _write(self, slug: str, arguments: Mapping[str, Any]) -> Any:
        if slug == "SALESFORCE_PATCH_COMPOSITE_SOBJECTS":  # an id written as Salesforce keeps it
            records = [
                {**r, "Id": next((k for k in self.records if k[:15] == r["Id"][:15]), r["Id"])}
                for r in arguments["records"]
            ]
            arguments = {**arguments, "records": records}
        return super()._write(slug, arguments)

    async def execute(self, *, slug: str, arguments: Mapping[str, Any], **kwargs: Any) -> Any:
        if slug == _LINK_SLUG:
            self.calls.append((slug, dict(arguments)))
            label = arguments["labels"][0]
            return ExecuteResult(
                True,
                {
                    "data": {
                        "fromObjectTypeId": "0-1",
                        "fromObjectId": int(arguments["objectId"]),
                        "toObjectTypeId": "0-1",
                        "toObjectId": int(arguments["toObjectId"]),
                        "labels": [label],
                    }
                },
                None,
            )
        return await super().execute(slug=slug, arguments=arguments, **kwargs)


async def _set_up(
    conn: Any, connection: CrmConnection, *, status: str = "ready", label: str | None = "7"
) -> None:
    await record_clue_fields(
        conn,
        connection_id=connection.connection_id,
        workspace_id=connection.workspace_id,
        provider=connection.provider,
        created=CLUE_FIELDS[connection.provider],
        permission_set_id=None,
        label_type_id=label if connection.provider == "hubspot" else None,
        status=status,  # type: ignore[arg-type]
    )


def _hubspot_link(one: str, other: str, entity: object, **extra: Any) -> ProposedChange:
    return ProposedChange(
        _LINK_SLUG,
        {"objectId": one, "toObjectId": other, **extra.pop("arguments", {})},
        "Two HubSpot contacts for Nick",
        clue_entity_id=None if entity is None else str(entity),
        **extra,
    )


def _sf_link(one: str, other: object, entity: object, **extra: Any) -> ProposedChange:
    return ProposedChange(
        "SALESFORCE_UPDATE_CONTACT",
        {"contact_id": one, "custom_fields": {_SF_LINK_FIELD: other}},
        "Two Salesforce contacts for Nick",
        clue_entity_id=None if entity is None else str(entity),
        **extra,
    )


_TWO_NICKS_HUBSPOT = {
    "201": {"email": "nick@zafran.io", "firstname": "Nick", "lastname": "Fisher"},
    "202": {"email": "Nick@Zafran.io", "firstname": "Nicholas", "lastname": "Fisher"},
}
_TWO_NICKS_SALESFORCE = {
    "003A": {"Email": "nick@zafran.io", "Name": "Nick Fisher", _SF_LINK_FIELD: None},
    "003B": {"Email": "NICK@zafran.io", "Name": "Nicholas Fisher", _SF_LINK_FIELD: None},
}


def _refused(batch: PreparedBatch) -> list[tuple[int, str, str]]:
    return [(r.index, r.reason_code, r.message) for r in batch.refused]


# --- D-4: find-before-create finds two records for one person ---------------------------------


def test_a_hubspot_person_create_finding_two_contacts_is_refused_naming_both(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        gateway = _Crm(records=_TWO_NICKS_HUBSPOT | {"202": {"email": "nick@zafran.io"}})
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                ProposedChange(
                    "HUBSPOT_CREATE_CONTACT", dict(_NICK), "x", clue_entity_id=str(world.nick)
                )
            ],
        )
        assert batch.changes == []  # prepare proposes nothing itself
        ((index, code, message),) = _refused(batch)
        assert (index, code) == (0, "crm_possible_duplicate")
        assert "201" in message and "202" in message
        assert "link_duplicate" in message and _LINK_SLUG in message
        assert "nick@zafran.io" not in message  # the person's email is never echoed

    _run(tmp_path, "dupcreatehs", body)


def test_a_salesforce_person_create_finding_two_contacts_is_refused_naming_both(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        gateway = _Crm(records=_TWO_NICKS_SALESFORCE)
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                ProposedChange(
                    "SALESFORCE_CREATE_CONTACT",
                    {"first_name": "Nick", "last_name": "Fisher", "email": "nick@zafran.io"},
                    "x",
                    clue_entity_id=str(world.nick),
                )
            ],
            _FakeBudget(gateway),
        )
        assert batch.changes == []
        ((index, code, message),) = _refused(batch)
        assert (index, code) == (0, "crm_possible_duplicate")
        assert "003A" in message and "003B" in message and _SF_LINK_FIELD in message

        # One record found: the create becomes that record's update, as before.
        del gateway.records["003B"]
        one = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                ProposedChange(
                    "SALESFORCE_CREATE_CONTACT",
                    {"first_name": "Nick", "last_name": "Fisher", "email": "nick@zafran.io"},
                    "x",
                    clue_entity_id=str(world.nick),
                )
            ],
            _FakeBudget(gateway),
        )
        assert one.refused == []
        assert {c.parsed.record_ref for c in one.changes} == {"003A"}

    _run(tmp_path, "dupcreatesf", body, provider="salesforce")


# --- link_duplicate ----------------------------------------------------------------------------


def test_a_hubspot_link_between_two_records_of_the_person_is_proposed_and_sent(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        gateway = _Crm(records=_TWO_NICKS_HUBSPOT)
        batch = await _prepare_batch(
            conn, gateway, connection, proposal_id, [_hubspot_link("201", "202", world.nick)]
        )
        assert batch.refused == []
        (link,) = batch.changes
        assert link.parsed.change_kind(link.spec) == "link_duplicate"
        assert link.scope_key == "kind:link_duplicate"
        assert dict(link.arguments) == {
            "objectType": "contacts",
            "objectId": "201",
            "toObjectType": "contacts",
            "toObjectId": "202",
            "labels": [{"associationCategory": "USER_DEFINED", "associationTypeId": 7}],
        }
        assert link.clue_entity_id == str(world.nick)
        assert link.source_claim_ids == (world.claims["nick_email"],)
        # The card names both people, never by their ids.
        assert link.parsed.label == "Nick Fisher and Nicholas Fisher (nick@zafran.io)"
        snapshot = card_snapshot([link], provider="hubspot", project_name="Q4")
        (group,) = snapshot["groups"]
        assert group["title"] == "Mark 1 possible duplicate"
        assert group["always_allow"] == "marking possible duplicates"
        assert group["value_summary"] is None and group["field"] is None
        assert [r["name"] for r in group["records"]] == [link.parsed.label]

        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=[link],
        )
        await writes.set_proposal_status(conn, proposal_id=proposal_id, status="queued")
        del gateway.calls[:]
        await _handle(_handler(conn, tmp_path, gateway), connection)
        assert [call for call in gateway.calls if call[0] == _LINK_SLUG] == [
            (_LINK_SLUG, dict(link.arguments))
        ]
        logged = await _writes(conn, proposal_id)
        assert logged["201"]["status"] == "succeeded"
        assert not [call for call in gateway.calls if call[0] in _WRITE_SLUGS]

    _run(tmp_path, "linkhs", body)


def test_a_salesforce_link_sets_clues_lookup_on_one_contact_and_is_sent(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        gateway = _Crm(records=_TWO_NICKS_SALESFORCE)
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A", "003B", world.nick)],
            _FakeBudget(gateway),
        )
        assert batch.refused == []
        (link,) = batch.changes
        assert link.parsed.change_kind(link.spec) == "link_duplicate"
        assert (link.field, link.before, link.after) == (_SF_LINK_FIELD, None, "003B")
        assert dict(link.arguments) == {
            "contact_id": "003A",
            "custom_fields": {_SF_LINK_FIELD: "003B"},
        }
        assert link.scope_key == "kind:link_duplicate"
        assert link.parsed.label == "Nick Fisher and Nicholas Fisher (nick@zafran.io)"

        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=[link],
        )
        await writes.set_proposal_status(conn, proposal_id=proposal_id, status="queued")
        await _handle(_handler(conn, tmp_path, gateway), connection)
        assert (await _writes(conn, proposal_id))["003A"]["status"] == "succeeded"
        assert gateway.records["003A"][_SF_LINK_FIELD] == "003B"

        # Undo: Clue removes the link it made, setting the field back to its before value.
        write_id = await conn.scalar(
            text("SELECT write_id FROM crm_write WHERE proposal_id = :p"), {"p": proposal_id}
        )
        undo = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A", None, None, reverses_write_id=write_id)],
            _FakeBudget(gateway),
        )
        assert undo.refused == []
        (back,) = undo.changes
        assert (back.field, back.before, back.after) == (_SF_LINK_FIELD, "003B", None)
        assert not back.overwrites_person and back.clue_entity_id == str(world.nick)

    _run(tmp_path, "linksf", body, provider="salesforce")


def test_a_link_to_a_record_that_is_not_the_person_is_refused(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        gateway = _Crm(
            records={
                **_TWO_NICKS_HUBSPOT,
                "203": {"email": "john@zafran.io", "firstname": "John"},
                "204": {"firstname": "No email"},
            }
        )
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                _hubspot_link("201", "203", world.nick),
                _hubspot_link("204", "202", world.nick),
                _hubspot_link("201", "202", None),
            ],
        )
        assert _refused(batch) == [
            (0, "crm_personal_data_not_allowed", _NOT_THE_PERSON),
            (1, "crm_personal_data_not_allowed", _NOT_THE_PERSON),
            (2, "crm_personal_data_not_allowed", "Name the Clue contact this is about."),
        ]
        assert batch.changes == []

        # Vari's email is not verified: Clue has nothing to match both records by.
        vari = await _prepare_batch(
            conn, gateway, connection, proposal_id, [_hubspot_link("201", "202", world.vari)]
        )
        assert _refusal(vari) == [(0, "crm_personal_data_not_allowed")]
        assert "vari@zafran.io" not in vari.refused[0].message

    _run(tmp_path, "linkwrong", body)


def test_a_salesforce_link_to_another_persons_contact_is_refused(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        gateway = _Crm(
            records={**_TWO_NICKS_SALESFORCE, "003C": {"Email": "john@zafran.io", "Name": "John"}}
        )
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A", "003C", world.nick)],
            _FakeBudget(gateway),
        )
        assert _refused(batch) == [(0, "crm_personal_data_not_allowed", _NOT_THE_PERSON)]

    _run(tmp_path, "linkwrongsf", body, provider="salesforce")


@pytest.mark.parametrize("state", ["never", "partial", "no_label"])
def test_without_clues_fields_hubspot_writes_no_link(tmp_path: Path, state: str) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        if state == "partial":
            await _set_up(conn, connection, status="partial")
        if state == "no_label":  # e.g. a HubSpot plan below Professional: no label was made
            await _set_up(conn, connection, label=None)
        gateway = _Crm(records=_TWO_NICKS_HUBSPOT)
        batch = await _prepare_batch(
            conn, gateway, connection, proposal_id, [_hubspot_link("201", "202", world.nick)]
        )
        assert _refused(batch) == [
            (0, "crm_clue_fields_not_set_up", _CANT_LINK.format(crm="HubSpot"))
        ]
        assert batch.changes == []

    _run(tmp_path, f"linknotsetup{state}", body)


def test_without_clues_fields_salesforce_writes_no_link(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        gateway = _Crm(records=_TWO_NICKS_SALESFORCE)
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A", "003B", world.nick)],
            _FakeBudget(gateway),
        )
        assert _refused(batch) == [
            (0, "crm_clue_fields_not_set_up", _CANT_LINK.format(crm="Salesforce"))
        ]
        assert batch.changes == []

    _run(tmp_path, "linknotsetupsf", body, provider="salesforce")


def test_clue_never_removes_a_link_it_did_not_make(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        records = {
            "003A": {**_TWO_NICKS_SALESFORCE["003A"], _SF_LINK_FIELD: "003Z"},
            "003B": _TWO_NICKS_SALESFORCE["003B"],
        }
        gateway = _Crm(records=records)
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                # Clearing a link someone else made.
                _sf_link("003A", None, world.nick),
                # Pointing a linked contact elsewhere would remove that link too.
                _sf_link("003A", "003B", world.nick),
            ],
            _FakeBudget(gateway),
        )
        assert _refusal(batch) == [(0, "crm_removal_not_allowed"), (1, "crm_removal_not_allowed")]
        assert batch.changes == []

    _run(tmp_path, "linknoremove", body, provider="salesforce")


def test_a_hubspot_link_is_never_undone_by_clue(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        gateway = _Crm(records=_TWO_NICKS_HUBSPOT)
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_hubspot_link("201", "202", world.nick, reverses_write_id=proposal_id)],
        )
        ((_, code, message),) = _refused(batch)
        assert code == "crm_write_not_parsable"
        assert "HubSpot" in message and "remove" in message

        # Another label than Clue's is never sent.
        other = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                _hubspot_link(
                    "201",
                    "202",
                    world.nick,
                    arguments={
                        "labels": [{"associationCategory": "USER_DEFINED", "associationTypeId": 9}]
                    },
                )
            ],
        )
        assert _refusal(other) == [(0, "crm_write_not_parsable")]

    _run(tmp_path, "linknoundo", body)


@pytest.mark.parametrize(
    ("provider", "slug", "arguments"),
    [
        ("hubspot", _LINK_SLUG, {"objectId": "201", "toObjectId": "201"}),
        ("hubspot", _LINK_SLUG, {"objectId": "201", "toObjectId": "101", "toObjectType": "0-2"}),
        (
            "salesforce",
            "SALESFORCE_UPDATE_CONTACT",
            {"contact_id": "003A", "custom_fields": {_SF_LINK_FIELD: "003A"}},
        ),
        (
            "salesforce",
            "SALESFORCE_UPDATE_CONTACT",
            {"contact_id": "003A", "title": "CEO", "custom_fields": {_SF_LINK_FIELD: "003B"}},
        ),
    ],
)
def test_a_link_names_two_different_contacts_and_nothing_else(
    provider: Any, slug: str, arguments: dict[str, Any]
) -> None:
    spec = write_spec(provider, slug)
    assert spec is not None
    with pytest.raises(WriteNotParsable):
        spec.parse(arguments)


# --- Task 4 review M-3: creates carrying Clue fields -------------------------------------------


def test_a_create_carrying_a_wrong_or_unowned_clue_value_is_refused(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        batch = await _prepare_batch(
            conn,
            _Crm(),
            connection,
            proposal_id,
            [
                ProposedChange(
                    "HUBSPOT_CREATE_CONTACT",
                    {**_NICK, "clue_committee_role": "BLOCKER"},  # Nick is the champion
                    "x",
                    clue_entity_id=str(world.nick),
                ),
                ProposedChange(
                    "HUBSPOT_CREATE_COMPANY",
                    {"name": "Zafran Security", "domain": "zafran.io", "clue_tier": "tier_1"},
                    "x",  # no Clue account named
                ),
            ],
        )
        assert _refusal(batch) == [
            (0, "crm_personal_data_not_allowed"),
            (1, "crm_personal_data_not_allowed"),
        ]
        assert "BLOCKER" not in batch.refused[0].message
        assert "clue_entity_id" in batch.refused[1].message
        assert batch.changes == []

    _run(tmp_path, "m3creates", body)


def test_a_create_meeting_two_contacts_at_send_is_skipped_naming_both(tmp_path: Path) -> None:
    """The second record appeared after the card: the create makes nothing and takes neither
    record for the person's (R-13.5); the message names both and the link the agent may propose."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        gateway = _Crm()
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [
                ProposedChange(
                    "HUBSPOT_CREATE_CONTACT", dict(_NICK), "x", clue_entity_id=str(world.nick)
                )
            ],
        )
        await writes.insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            prepared=batch.changes,
        )
        await writes.set_proposal_status(conn, proposal_id=proposal_id, status="queued")
        gateway.records.update(
            {"201": {"email": "nick@zafran.io"}, "202": {"email": "nick@zafran.io"}}
        )
        await _handle(_handler(conn, tmp_path, gateway), connection)
        row = (
            await conn.execute(
                text(
                    "SELECT status, failure_kind, crm_message, record_ref FROM crm_write "
                    "WHERE proposal_id = :p"
                ),
                {"p": proposal_id},
            )
        ).one()
        assert (row.status, row.failure_kind, row.record_ref) == ("skipped", "conflict", None)
        assert "201" in row.crm_message and "202" in row.crm_message
        assert "link_duplicate" in row.crm_message
        links = await conn.scalar(
            text("SELECT count(*) FROM crm_record_link WHERE connection_id = :c"),
            {"c": connection.connection_id},
        )
        assert links == 0
        assert not [call for call in gateway.calls if call[0] in _WRITE_SLUGS]

    _run(tmp_path, "dupatsend", body)


_SF_18 = {
    "003A00000000001AAA": {"Email": "nick@zafran.io", "Name": "Nick Fisher", _SF_LINK_FIELD: None},
    "003B00000000002AAA": {"Email": "nick@zafran.io", "Name": "N. Fisher", _SF_LINK_FIELD: None},
}


async def _send(
    conn: Any,
    seeded: Any,
    connection: CrmConnection,
    tmp_path: Path,
    batch: Any,
    proposal_id: UUID,
    gateway: _Crm,
) -> None:
    await writes.insert_writes(
        conn,
        proposal_id=proposal_id,
        workspace_id=seeded.workspace_id,
        connection_id=connection.connection_id,
        prepared=batch.changes,
    )
    await writes.set_proposal_status(conn, proposal_id=proposal_id, status="queued")
    await _handle(_handler(conn, tmp_path, gateway), connection)


def test_a_salesforce_link_named_by_15_character_ids_lands_and_can_be_undone(
    tmp_path: Path,
) -> None:
    """Salesforce answers 18-character ids: Clue sends and keeps the id it read, so its read-back
    finds the link, and its own undo knows the value as its own."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        gateway = _Crm(records=_SF_18)
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A00000000001", "003B00000000002", world.nick)],
            _FakeBudget(gateway),
        )
        (link,) = batch.changes
        assert link.after == "003B00000000002AAA"
        assert link.arguments["custom_fields"] == {_SF_LINK_FIELD: "003B00000000002AAA"}
        await _send(conn, seeded, connection, tmp_path, batch, proposal_id, gateway)
        row = (
            await conn.execute(
                text("SELECT write_id, status FROM crm_write WHERE proposal_id = :p"),
                {"p": proposal_id},
            )
        ).one()
        assert row.status == "succeeded"

        undo = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A00000000001", None, None, reverses_write_id=row.write_id)],
            _FakeBudget(gateway),
        )
        assert undo.refused == []
        (back,) = undo.changes
        assert back.after is None and not back.overwrites_person

    _run(tmp_path, "link15", body, provider="salesforce")


def test_an_undo_never_removes_a_link_someone_repointed(tmp_path: Path) -> None:
    """Clue linked 003A to 003B; someone pointed 003A at 003Z since. Undoing Clue's write would
    remove their link (R-6.13), so it is refused."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection, proposal_id: UUID) -> None:
        world = await _researched(conn, seeded)
        await _set_up(conn, connection)
        gateway = _Crm(records=_SF_18)
        batch = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A00000000001AAA", "003B00000000002AAA", world.nick)],
            _FakeBudget(gateway),
        )
        await _send(conn, seeded, connection, tmp_path, batch, proposal_id, gateway)
        write_id = await conn.scalar(
            text("SELECT write_id FROM crm_write WHERE proposal_id = :p AND status = 'succeeded'"),
            {"p": proposal_id},
        )
        gateway.records["003A00000000001AAA"][_SF_LINK_FIELD] = "003Z00000000009AAA"
        undo = await _prepare_batch(
            conn,
            gateway,
            connection,
            proposal_id,
            [_sf_link("003A00000000001AAA", None, None, reverses_write_id=write_id)],
            _FakeBudget(gateway),
        )
        assert _refusal(undo) == [(0, "crm_removal_not_allowed")]
        assert undo.changes == []

    _run(tmp_path, "linkrepointed", body, provider="salesforce")
