"""The setup run: the write executor sets up Clue's own fields in the CRM once an owner or admin
allows the ``clue_fields_setup`` card (CRM integration Phase 4, Task 3; rulings R-13.1–R-13.7).

HubSpot: the property group ``clue`` on companies and contacts (409 = already there), each
property (409 = already there), then the contacts↔contacts "Possible duplicate" label (looked up
first; its ``typeId`` kept). Salesforce: each custom field (an inner ``success: false`` "There is
already a field named …" = already there), the "Clue fields" permission set, one
``FieldPermissions`` row per field, the assignment to the connected user (each looked up first),
then a SOQL read of every field proves the connected user sees them. Only then is the setup
``ready``; a refused step records ``partial``, names the step, and a later run finishes what is
missing without making anything twice.

Every test runs the real executor end to end (``CrmWriteHandler.handle``) against a fake CRM that
keeps the schema it was given. DB-backed and rollback-only, on the lane's test DB.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import text

from clue_api.crm import writes
from clue_api.crm.clue_fields import CLUE_FIELDS, clue_fields_state, record_clue_fields
from clue_api.crm.composio_gateway import ComposioError, ExecuteResult
from clue_api.crm.connections import CrmConnection
from clue_api.crm.salesforce_budget import CrmBudgetExhausted
from clue_api.crm.write_prepare import clue_fields_setup_change
from clue_storage import FsStorage
from tests.api.test_crm_clue_fields_setup_propose_db import (
    _propose as _propose_with_tool,
)
from tests.api.test_crm_clue_fields_setup_propose_db import (
    _set_role,
    _write_rows,
)
from tests.api.test_crm_tools_db import _connect
from tests.api.test_crm_write_answer_db import _answer, _client, _snapshot
from tests.api.test_crm_write_executor_db import (
    _context,
    _handler,
    _proposal_status,
    _wake_messages,
)
from tests.api.test_crm_write_prepare_db import _FakeBudget
from tests.api.test_lane_d4_agent_gate_db import OTHER_USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


SF_USER = "005jV00000ABCDEQAZ"
PERMISSION_SET_REFUSED = ExecuteResult(
    False,
    {"http_error": "400", "status_code": 400},
    '[{"message":"insufficient access rights on object id","errorCode":'
    '"INSUFFICIENT_ACCESS_OR_READONLY","fields":[]}]',
)
RATE_LIMITED = ExecuteResult(
    False,
    {"http_error": "429", "status_code": 429},
    '{"status":"error","message":"You have reached your ten secondly limit.",'
    '"category":"RATE_LIMITS"}',
)


def _hubspot_conflict(message: str, code: str) -> ExecuteResult:
    """HubSpot's 409 for a group or property that exists (composio-api-notes § Phase 4 shapes)."""
    body = {"status": "error", "message": message, "category": "CONFLICT", "subCategory": code}
    return ExecuteResult(
        False, {"http_error": "409", "status_code": 409, "message": "Conflict"}, json.dumps(body)
    )


class _SchemaCrm:
    """A CRM that keeps the schema Clue sets up in it.

    HubSpot: property groups and properties per object type, association labels (contacts to
    contacts). Salesforce: custom fields, permission sets, field permissions and assignments; a
    field is visible to the connected user only when a permission set assigned to them grants read
    on it (the spike: invisible until then). ``failures[slug]`` is consumed one entry per call of
    that slug and answered instead of the normal answer. ``grants_ignored`` makes Salesforce accept
    field permissions without them taking effect (so the read-back fails).
    """

    def __init__(
        self,
        *,
        failures: Mapping[str, list[ExecuteResult | Exception]] | None = None,
        grants_ignored: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failures = {slug: list(items) for slug, items in (failures or {}).items()}
        self.grants_ignored = grants_ignored
        self.groups: set[tuple[str, str]] = set()
        self.properties: dict[tuple[str, str], dict[str, Any]] = {}
        self.labels: dict[str, int] = {}
        self.sf_fields: dict[str, dict[str, Any]] = {}
        self.permission_sets: dict[str, str] = {}
        self.field_permissions: dict[tuple[str, str], dict[str, Any]] = {}
        self.assignments: set[tuple[str, str]] = set()

    def snapshot(self) -> tuple[Any, ...]:
        return (
            set(self.groups),
            dict(self.properties),
            dict(self.labels),
            dict(self.sf_fields),
            dict(self.permission_sets),
            dict(self.field_permissions),
            set(self.assignments),
        )

    def slugs(self) -> list[str]:
        return [slug for slug, _ in self.calls]

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
        queued = self.failures.get(slug)
        if queued:
            failure = queued.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        return self._answer(slug, arguments)

    def _answer(self, slug: str, arguments: Mapping[str, Any]) -> ExecuteResult:
        if slug == "HUBSPOT_CREATE_AND_RETURN_A_NEW_PROPERTY_GROUP":
            key = (str(arguments["objectType"]), str(arguments["name"]))
            if key in self.groups:
                return _hubspot_conflict(
                    f"A property group named {key[1]} already exists.", "GROUP_EXISTS"
                )
            self.groups.add(key)
            return _ok({"name": key[1], "label": arguments["label"], "archived": False})
        if slug == "HUBSPOT_CREATE_PROPERTY_FOR_SPECIFIED_OBJECT_TYPE":
            key = (str(arguments["objectType"]), str(arguments["name"]))
            assert (key[0], str(arguments["groupName"])) in self.groups, "group made first"
            if key in self.properties:
                return _hubspot_conflict(
                    f"Property {key[1]} already exists", "PROPERTY_ALREADY_EXISTS"
                )
            self.properties[key] = dict(arguments)
            return _ok({"name": key[1], "label": arguments["label"]})
        if slug == "HUBSPOT_LIST_ASSOCIATION_TYPES":
            results = [{"id": "449", "name": "contact_to_contact"}] + [
                {"id": str(type_id), "name": name} for name, type_id in self.labels.items()
            ]
            return _ok({"results": results})
        if slug == "HUBSPOT_CREATE_ASSOCIATION_LABEL":
            assert str(arguments["name"]) not in self.labels, "a label is never made twice"
            type_id = 7 + len(self.labels)
            self.labels[str(arguments["name"])] = type_id
            return _ok(
                {
                    "results": [
                        {
                            "category": "USER_DEFINED",
                            "typeId": type_id,
                            "label": arguments["label"],
                            "fromObjectTypeId": "0-1",
                            "toObjectTypeId": "0-1",
                        }
                    ]
                }
            )
        if slug == "SALESFORCE_CREATE_CUSTOM_FIELD":
            name = f"{arguments['object_api_name']}.{arguments['field_api_name']}"
            if name in self.sf_fields:  # the spike's trap: successful, inner success false
                return _ok(
                    {
                        "success": False,
                        "full_name": name,
                        "already_exists": False,
                        "errors": [
                            {
                                "message": f"There is already a field named "
                                f"{arguments['field_api_name'][:-3]} on "
                                f"{arguments['object_api_name']}.",
                                "statusCode": "DUPLICATE_DEVELOPER_NAME",
                            }
                        ],
                    }
                )
            self.sf_fields[name] = dict(arguments)
            return _ok({"id": f"00N{len(self.sf_fields):03d}", "success": True, "errors": []})
        if slug == "SALESFORCE_WHO_AM_I":
            return _ok(
                {
                    "data": {"user_id": SF_USER, "organization_id": "00DjV000001"},
                    "display_name": "admin@garner.test",
                }
            )
        if slug == "SALESFORCE_CREATE_S_OBJECT_RECORD":
            return self._create_record(str(arguments["sobject_type"]), arguments["fields"])
        if slug == "SALESFORCE_PATCH_COMPOSITE_SOBJECTS":
            assert arguments["sobject_name"] == "FieldPermissions"
            results = []
            for record in arguments["records"]:
                row = next(r for r in self.field_permissions.values() if r["Id"] == record["Id"])
                row.update({k: v for k, v in record.items() if k.startswith("Permissions")})
                results.append({"id": record["Id"], "success": True, "errors": []})
            return _ok(results)
        if slug == "SALESFORCE_RUN_SOQL_QUERY":
            return self._soql(str(arguments["query"]))
        raise AssertionError(f"unexpected call {slug}")

    def _create_record(self, sobject: str, fields: Mapping[str, Any]) -> ExecuteResult:
        if sobject == "PermissionSet":
            assert fields["Name"] not in self.permission_sets, "a permission set is made once"
            record_id = f"0PSjV0000000{len(self.permission_sets):03d}"
            self.permission_sets[str(fields["Name"])] = record_id
        elif sobject == "FieldPermissions":
            key = (str(fields["ParentId"]), str(fields["Field"]))
            assert key not in self.field_permissions, "a field permission is made once"
            assert fields["Field"] in self.sf_fields
            record_id = f"01kjV0000000{len(self.field_permissions):03d}"
            self.field_permissions[key] = {**fields, "Id": record_id}
        elif sobject == "PermissionSetAssignment":
            key = (str(fields["PermissionSetId"]), str(fields["AssigneeId"]))
            assert key not in self.assignments, "an assignment is made once"
            self.assignments.add(key)
            record_id = f"0PajV0000000{len(self.assignments):03d}"
        else:
            raise AssertionError(f"unexpected sobject {sobject}")
        return _ok({"id": record_id, "success": True, "errors": []})

    def _soql(self, query: str) -> ExecuteResult:
        if "FROM PermissionSetAssignment" in query:
            ps, assignee = re.findall(r"'([^']*)'", query)
            records = [{"Id": "0Pa1"}] if (ps, assignee) in self.assignments else []
            return _records(records)
        if "FROM PermissionSet " in query:
            (name,) = re.findall(r"Name = '([^']*)'", query)
            found = self.permission_sets.get(name)
            return _records([] if found is None else [{"Id": found, "Name": name}])
        if "FROM FieldPermissions" in query:
            (parent,) = re.findall(r"ParentId = '([^']*)'", query)
            return _records(
                [
                    {
                        "Id": row["Id"],
                        "Field": row["Field"],
                        "SobjectType": row["SobjectType"],
                        "PermissionsRead": row["PermissionsRead"],
                        "PermissionsEdit": row["PermissionsEdit"],
                    }
                    for (p, _), row in self.field_permissions.items()
                    if p == parent
                ]
            )
        match = re.match(r"SELECT (.*) FROM (Account|Contact)\b", query)
        assert match is not None, query
        sobject = match.group(2)
        for column in (c.strip() for c in match.group(1).split(",")):
            if column == "Id":
                continue
            if not self._visible(f"{sobject}.{column}"):
                return ExecuteResult(
                    False,
                    {"http_error": "400", "status_code": 400},
                    json.dumps(
                        [
                            {
                                "message": f"No such column '{column}' on entity '{sobject}'.",
                                "errorCode": "INVALID_FIELD",
                            }
                        ]
                    ),
                )
        return _records([])

    def _visible(self, field: str) -> bool:
        if field not in self.sf_fields or self.grants_ignored:
            return False
        return any(
            row["Field"] == field
            and row["PermissionsRead"]
            and (parent, SF_USER) in self.assignments
            for (parent, _), row in self.field_permissions.items()
        )


def _ok(data: Any) -> ExecuteResult:
    return ExecuteResult(True, data, None)


def _records(records: list[dict[str, Any]]) -> ExecuteResult:
    return _ok({"records": records, "totalSize": len(records), "done": True})


def _run(tmp_path: Path, label: str, body: Any, provider: str = "hubspot") -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmcfr-{label}", label=label)
            seeded.label = label
            seeded.storage = FsStorage(tmp_path / f"crm-clue-fields-run-{label}")
            connection = await _connect(conn, seeded.workspace_id, provider)
            await body(conn, seeded, connection)

    run_async(scenario())


async def _allowed_by_admin(conn: Any, seeded: Any) -> UUID:
    """Propose the setup with the tool and allow its card as an admin (the whole Task 2 path)."""
    await _set_role(conn, seeded, OTHER_USER_ID, "admin")
    proposed = await _propose_with_tool(conn, seeded)
    snapshot = await _snapshot(conn, seeded, proposed)
    (row,) = await _write_rows(conn, proposed["proposal_id"])
    async with _client(conn, seeded, OTHER_USER_ID) as client:
        response = await _answer(
            client, seeded, proposed, snapshot, key=f"admin-{uuid4()}", selected=[str(row.write_id)]
        )
    assert response.status_code == 202, response.text
    return UUID(proposed["proposal_id"])


async def _queued_setup(conn: Any, seeded: Any, connection: CrmConnection) -> UUID:
    """Another allowed setup (a later card of the chat), queued for the executor."""
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
    await writes.insert_writes(
        conn,
        proposal_id=proposal_id,
        workspace_id=seeded.workspace_id,
        connection_id=connection.connection_id,
        prepared=[
            clue_fields_setup_change(
                connection.provider,
                write_id=uuid5(proposal_id, "clue_fields_setup"),
                reason="Set up Clue's fields.",
            )
        ],
    )
    await writes.set_proposal_status(conn, proposal_id=proposal_id, status="queued")
    await conn.execute(
        text(
            "UPDATE crm_write_proposal SET created_at = clock_timestamp() WHERE proposal_id = :id"
        ),
        {"id": proposal_id},
    )
    return proposal_id


async def _setup_write(conn: Any, proposal_id: UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT status, failure_kind, crm_message, crm_response, retryable, attempts "
                "FROM crm_write WHERE proposal_id = :id"
            ),
            {"id": proposal_id},
        )
    ).one()


async def _execute(
    conn: Any, tmp_path: Path, connection: CrmConnection, crm: _SchemaCrm, budget: Any = None
) -> Any:
    handler = _handler(conn, tmp_path, crm, budget=budget)  # type: ignore[arg-type]
    return await handler.handle(_context(connection))


def _steps(write: Any) -> list[tuple[str, str]]:
    response = write.crm_response
    if isinstance(response, str):
        response = json.loads(response)
    return [(step["step"], step["result"]) for step in response["steps"]]


# --- HubSpot -----------------------------------------------------------------------------------


def test_hubspot_clean_run_creates_everything_in_order_and_records_ready(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _allowed_by_admin(conn, seeded)
        crm = _SchemaCrm()
        result = await _execute(conn, tmp_path, connection, crm)
        assert result.outcome == "done"

        fields = CLUE_FIELDS["hubspot"]
        assert crm.slugs() == [
            "HUBSPOT_CREATE_AND_RETURN_A_NEW_PROPERTY_GROUP",
            "HUBSPOT_CREATE_AND_RETURN_A_NEW_PROPERTY_GROUP",
            *["HUBSPOT_CREATE_PROPERTY_FOR_SPECIFIED_OBJECT_TYPE"] * len(fields),
            "HUBSPOT_LIST_ASSOCIATION_TYPES",
            "HUBSPOT_CREATE_ASSOCIATION_LABEL",
        ]
        assert crm.calls[0][1] == {"objectType": "companies", "name": "clue", "label": "Clue"}
        assert crm.calls[1][1] == {"objectType": "contacts", "name": "clue", "label": "Clue"}
        made = [args for slug, args in crm.calls if slug.endswith("SPECIFIED_OBJECT_TYPE")]
        assert [(a["objectType"], a["name"]) for a in made] == [
            (f.crm_object, f.crm_name) for f in fields
        ]
        tier = made[0]
        assert (tier["type"], tier["fieldType"], tier["groupName"]) == (
            "enumeration",
            "select",
            "clue",
        )
        assert [(o["value"], o["label"], o["displayOrder"]) for o in tier["options"]] == [
            ("tier_1", "Tier 1", 0),
            ("tier_2", "Tier 2", 1),
            ("tier_3", "Tier 3", 2),
        ]
        # R-13.7: the Clue id is unique; nothing else is.
        assert [a["name"] for a in made if a.get("hasUniqueValue")] == ["clue_id", "clue_id"]
        assert crm.calls[-1][1] == {
            "from_object_type": "contacts",
            "to_object_type": "contacts",
            "name": "clue_possible_duplicate",
            "label": "Possible duplicate",
        }

        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert state.status == "ready"
        assert state.created_names == tuple(f.qualified_name for f in fields)
        assert (state.label_type_id, state.permission_set_id) == ("7", None)

        write = await _setup_write(conn, proposal_id)
        assert write.status == "succeeded"
        assert write.crm_message == "Set up Clue's fields in HubSpot: 9 created, 0 already there."
        assert _steps(write)[0] == ('the property group "Clue" on companies', "created")
        assert _steps(write)[-1] == ('the "Possible duplicate" label for contacts', "created")
        assert await _proposal_status(conn, proposal_id) == "finished"
        assert await _wake_messages(conn, seeded.workspace_id) == [
            f"crm-writes-finished:{proposal_id}"
        ]

    _run(tmp_path, "hs-clean", body)


def test_hubspot_rerun_makes_nothing_twice_and_keeps_the_label_type(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm = _SchemaCrm()
        first = await _queued_setup(conn, seeded, connection)
        await _execute(conn, tmp_path, connection, crm)
        assert (await _setup_write(conn, first)).status == "succeeded"
        # The customer's setup is there, but Clue's record of it was lost (e.g. a partial run).
        await conn.execute(
            text("UPDATE crm_clue_fields SET status = 'partial', label_type_id = NULL")
        )
        before = crm.snapshot()
        crm.calls.clear()

        second = await _queued_setup(conn, seeded, connection)
        await _execute(conn, tmp_path, connection, crm)

        assert crm.snapshot() == before  # nothing new in the CRM
        assert "HUBSPOT_CREATE_ASSOCIATION_LABEL" not in crm.slugs()
        write = await _setup_write(conn, second)
        assert write.status == "succeeded"
        assert write.crm_message == "Set up Clue's fields in HubSpot: 0 created, 9 already there."
        assert {result for _, result in _steps(write)} == {"already there"}
        assert _steps(write)[-1] == ('the "Possible duplicate" label for contacts', "already there")
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert (state.status, state.label_type_id) == ("ready", "7")

    _run(tmp_path, "hs-rerun", body)


# --- Salesforce --------------------------------------------------------------------------------


def test_salesforce_clean_run_grants_access_and_proves_it_before_ready(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _allowed_by_admin(conn, seeded)
        crm = _SchemaCrm()
        budget = _FakeBudget(crm)  # type: ignore[arg-type]
        await _execute(conn, tmp_path, connection, crm, budget=budget)

        fields = CLUE_FIELDS["salesforce"]
        soql = "SALESFORCE_RUN_SOQL_QUERY"
        create = "SALESFORCE_CREATE_S_OBJECT_RECORD"
        assert crm.slugs() == [
            *["SALESFORCE_CREATE_CUSTOM_FIELD"] * len(fields),
            soql,  # the permission set by Name
            create,
            soql,  # its field permissions
            *[create] * len(fields),
            "SALESFORCE_WHO_AM_I",
            soql,  # the assignment
            create,
            soql,  # read back Account fields
            soql,  # read back Contact fields
        ]
        # Every Salesforce call is taken from the org's API budget first.
        assert len(budget.taken_at) == len(crm.calls)

        made = [args for slug, args in crm.calls if slug == "SALESFORCE_CREATE_CUSTOM_FIELD"]
        assert [(a["object_api_name"], a["field_api_name"]) for a in made] == [
            (f.crm_object, f.crm_name) for f in fields
        ]
        by_name = {a["field_api_name"] + "@" + a["object_api_name"]: a for a in made}
        assert by_name["Clue_Tier__c@Account"]["field_type"] == "Picklist"
        assert [v["full_name"] for v in by_name["Clue_Tier__c@Account"]["picklist_values"]] == [
            "Tier 1",
            "Tier 2",
            "Tier 3",
        ]
        clue_id = by_name["Clue_Id__c@Contact"]
        assert (clue_id["field_type"], clue_id["length"], clue_id["external_id"]) == (
            "Text",
            64,
            True,
        )
        assert clue_id["unique"] is True
        lookup = by_name["Clue_Possible_Duplicate__c@Contact"]
        assert (lookup["field_type"], lookup["reference_to"], lookup["relationship_name"]) == (
            "Lookup",
            "Contact",
            "Clue_Possible_Duplicates",
        )
        assert by_name["Clue_Research_Link__c@Account"]["field_type"] == "Url"

        (ps_id,) = crm.permission_sets.values()
        assert crm.permission_sets == {"Clue_Fields": ps_id}
        assert sorted(field for _, field in crm.field_permissions) == sorted(
            f.qualified_name for f in fields
        )
        assert all(
            row["PermissionsRead"] and row["PermissionsEdit"]
            for row in crm.field_permissions.values()
        )
        assert crm.assignments == {(ps_id, SF_USER)}
        account_read = crm.calls[-2][1]["query"]
        assert account_read.startswith("SELECT Id, Clue_Tier__c, Clue_Research_Link__c")
        assert "FROM Account" in account_read

        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert (state.status, state.permission_set_id) == ("ready", ps_id)
        assert state.created_names == tuple(f.qualified_name for f in fields)
        write = await _setup_write(conn, proposal_id)
        assert write.status == "succeeded"
        assert (
            write.crm_message == "Set up Clue's fields in Salesforce: 16 created, 0 already there."
        )
        assert _steps(write)[-1] == (
            "reading Clue's fields back as the connected user",
            "checked",
        )

    _run(tmp_path, "sf-clean", body, "salesforce")


def test_salesforce_rerun_sends_no_create_that_would_duplicate(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm = _SchemaCrm()
        await _queued_setup(conn, seeded, connection)
        await _execute(conn, tmp_path, connection, crm)
        await conn.execute(text("UPDATE crm_clue_fields SET status = 'partial'"))
        before = crm.snapshot()
        crm.calls.clear()

        second = await _queued_setup(conn, seeded, connection)
        await _execute(conn, tmp_path, connection, crm)

        assert crm.snapshot() == before
        assert "SALESFORCE_CREATE_S_OBJECT_RECORD" not in crm.slugs()
        write = await _setup_write(conn, second)
        assert write.status == "succeeded"
        assert (
            write.crm_message == "Set up Clue's fields in Salesforce: 0 created, 16 already there."
        )
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert state.status == "ready"

    _run(tmp_path, "sf-rerun", body, "salesforce")


def test_a_refused_permission_set_records_partial_and_a_later_run_resumes(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _allowed_by_admin(conn, seeded)
        crm = _SchemaCrm(failures={"SALESFORCE_CREATE_S_OBJECT_RECORD": [PERMISSION_SET_REFUSED]})
        await _execute(conn, tmp_path, connection, crm)

        write = await _setup_write(conn, proposal_id)
        assert write.status == "failed"
        assert write.crm_message == (
            "Salesforce refused the permission set: insufficient access rights on object id "
            "(INSUFFICIENT_ACCESS_OR_READONLY). The connected user needs to be a Salesforce admin."
        )
        assert (write.failure_kind, write.retryable) == ("permission", False)
        assert _steps(write)[-1] == ('the permission set "Clue fields"', "failed")
        # Nothing after the refused step was tried.
        assert "SALESFORCE_WHO_AM_I" not in crm.slugs()
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert state.status == "partial"
        assert state.permission_set_id is None
        assert state.created_names == tuple(f.qualified_name for f in CLUE_FIELDS["salesforce"])
        assert await _proposal_status(conn, proposal_id) == "finished"
        assert await _wake_messages(conn, seeded.workspace_id) == [
            f"crm-writes-finished:{proposal_id}"
        ]

        # An admin connects instead; the setup is proposed and allowed again.
        crm.calls.clear()
        again = await _queued_setup(conn, seeded, connection)
        await _execute(conn, tmp_path, connection, crm)
        assert (await _setup_write(conn, again)).status == "succeeded"
        assert crm.slugs().count("SALESFORCE_CREATE_CUSTOM_FIELD") == 7  # each answered "there"
        assert len(crm.sf_fields) == 7
        assert len(crm.permission_sets) == 1
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert state.status == "ready"

    _run(tmp_path, "sf-refused", body, "salesforce")


def test_ready_needs_the_read_back_to_see_every_field(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _queued_setup(conn, seeded, connection)
        crm = _SchemaCrm(grants_ignored=True)
        await _execute(conn, tmp_path, connection, crm)

        write = await _setup_write(conn, proposal_id)
        assert write.status == "failed"
        assert write.crm_message == (
            "Salesforce still hides Clue's fields from the connected user after the permission "
            "set: No such column 'Clue_Tier__c' on entity 'Account'. (INVALID_FIELD)."
        )
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert state.status == "partial"
        assert state.permission_set_id == crm.permission_sets["Clue_Fields"]

    _run(tmp_path, "sf-hidden", body, "salesforce")


def test_a_rate_limit_mid_setup_waits_and_the_retry_finishes_it(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _queued_setup(conn, seeded, connection)
        crm = _SchemaCrm(
            failures={"HUBSPOT_CREATE_PROPERTY_FOR_SPECIFIED_OBJECT_TYPE": [RATE_LIMITED]}
        )
        result = await _execute(conn, tmp_path, connection, crm)
        assert result.requeue is True and result.outcome == "crm_rate_limited"
        assert await _proposal_status(conn, proposal_id) == "queued"
        write = await _setup_write(conn, proposal_id)
        assert (write.status, write.attempts) == ("queued", 1)
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is None  # no field was found or made yet

        result = await _execute(conn, tmp_path, connection, crm)
        assert result.outcome == "done"
        write = await _setup_write(conn, proposal_id)
        assert write.status == "succeeded"
        # The groups made by the first run were found there, never made twice.
        assert write.crm_message == "Set up Clue's fields in HubSpot: 7 created, 2 already there."
        assert len(crm.groups) == 2

    _run(tmp_path, "hs-rate-limited", body)


def test_a_card_for_another_field_set_is_never_run(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        # The card listed a field set this Clue no longer defines (a deploy since the card).
        proposal_id = await _queued_setup(conn, seeded, connection)
        await conn.execute(
            text("UPDATE crm_write SET arguments = CAST(:args AS jsonb) WHERE proposal_id = :id"),
            {"args": json.dumps({"fields": ["companies.clue_tier"]}), "id": proposal_id},
        )
        crm = _SchemaCrm()
        await _execute(conn, tmp_path, connection, crm)
        assert crm.calls == []
        write = await _setup_write(conn, proposal_id)
        assert (write.status, write.crm_message) == (
            "failed",
            "This action is no longer allowed, so it was not sent.",
        )
        assert await clue_fields_state(conn, connection_id=connection.connection_id) is None

    _run(tmp_path, "other-field-set", body)


# --- two cards, and who may allow -------------------------------------------------------------


def test_a_second_allowed_setup_is_skipped_once_the_first_made_it_ready(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        first = await _queued_setup(conn, seeded, connection)
        second = await _queued_setup(conn, seeded, connection)
        crm = _SchemaCrm()
        await _execute(conn, tmp_path, connection, crm)
        calls = len(crm.calls)

        assert (await _setup_write(conn, first)).status == "succeeded"
        skipped = await _setup_write(conn, second)
        assert (skipped.status, skipped.crm_message) == (
            "skipped",
            "Clue's fields are already set up in HubSpot.",
        )
        assert skipped.attempts == 0
        assert await _proposal_status(conn, second) == "finished"
        assert len(crm.calls) == calls  # the second sent nothing

    _run(tmp_path, "two-cards", body)


def test_a_setup_allowed_when_already_ready_sends_nothing(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _queued_setup(conn, seeded, connection)
        await record_clue_fields(
            conn,
            connection_id=connection.connection_id,
            workspace_id=seeded.workspace_id,
            provider="salesforce",
            created=CLUE_FIELDS["salesforce"],
            permission_set_id="0PS1",
            label_type_id=None,
            status="ready",
        )
        crm = _SchemaCrm()
        await _execute(conn, tmp_path, connection, crm)
        assert crm.calls == []
        write = await _setup_write(conn, proposal_id)
        assert (write.status, write.crm_message) == (
            "skipped",
            "Clue's fields are already set up in Salesforce.",
        )

    _run(tmp_path, "already-ready", body, "salesforce")


@pytest.mark.parametrize("status", ["suspended", "revoked"])
def test_an_owner_no_longer_active_cannot_allow_the_setup(tmp_path: Path, status: str) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _set_role(conn, seeded, OTHER_USER_ID, "owner")
        await conn.execute(
            text(
                "UPDATE workspace_membership SET status = :status, "
                "revoked_at = CASE WHEN :status = 'revoked' THEN now() END "
                "WHERE workspace_id = :ws AND user_id = :user"
            ),
            {"status": status, "ws": seeded.workspace_id, "user": OTHER_USER_ID},
        )
        proposed = await _propose_with_tool(conn, seeded)
        snapshot = await _snapshot(conn, seeded, proposed)
        (row,) = await _write_rows(conn, proposed["proposal_id"])
        async with _client(conn, seeded, OTHER_USER_ID) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key=status, selected=[str(row.write_id)]
            )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "crm_setup_needs_admin"
        assert await _proposal_status(conn, UUID(proposed["proposal_id"])) == (
            "awaiting_permission"
        )

    _run(tmp_path, f"owner-{status}", body)


# --- fix round 1 -------------------------------------------------------------------------------

EDIT_REFUSED = ExecuteResult(
    True,
    [
        {
            "id": "01k",
            "success": False,
            "errors": [
                {
                    "message": "insufficient access rights on object id",
                    "statusCode": "INSUFFICIENT_ACCESS_OR_READONLY",
                }
            ],
        }
    ],
    None,
)


async def _ready_then_edit_unticked(
    conn: Any, seeded: Any, connection: Any, tmp_path: Path
) -> tuple[_SchemaCrm, UUID]:
    """A Salesforce setup made ready, after which an admin unticked Edit on one field's row and
    Clue's record went back to partial (a later setup is allowed)."""
    crm = _SchemaCrm()
    await _queued_setup(conn, seeded, connection)
    await _execute(conn, tmp_path, connection, crm)
    row = next(r for r in crm.field_permissions.values() if r["Field"] == "Contact.Clue_Id__c")
    row["PermissionsEdit"] = False
    await conn.execute(text("UPDATE crm_clue_fields SET status = 'partial'"))
    crm.calls.clear()
    return crm, await _queued_setup(conn, seeded, connection)


def test_a_field_permission_without_edit_is_given_edit_before_ready(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm, proposal_id = await _ready_then_edit_unticked(conn, seeded, connection, tmp_path)
        await _execute(conn, tmp_path, connection, crm)

        (patch,) = [
            args for slug, args in crm.calls if slug == "SALESFORCE_PATCH_COMPOSITE_SOBJECTS"
        ]
        assert [r["Id"] for r in patch["records"]] == [
            r["Id"] for r in crm.field_permissions.values() if r["Field"] == "Contact.Clue_Id__c"
        ]
        assert all(
            r["PermissionsRead"] and r["PermissionsEdit"] for r in crm.field_permissions.values()
        )
        assert "SALESFORCE_CREATE_S_OBJECT_RECORD" not in crm.slugs()
        write = await _setup_write(conn, proposal_id)
        assert write.status == "succeeded"
        assert ("access to Contact.Clue_Id__c", "updated") in _steps(write)
        assert write.crm_message == (
            "Set up Clue's fields in Salesforce: 0 created, 1 updated, 15 already there."
        )
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None and state.status == "ready"

    _run(tmp_path, "sf-edit-unticked", body, "salesforce")


def test_a_refused_edit_grant_records_partial_and_names_the_field(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm, proposal_id = await _ready_then_edit_unticked(conn, seeded, connection, tmp_path)
        crm.failures["SALESFORCE_PATCH_COMPOSITE_SOBJECTS"] = [EDIT_REFUSED]
        await _execute(conn, tmp_path, connection, crm)

        write = await _setup_write(conn, proposal_id)
        assert write.status == "failed"
        assert write.crm_message == (
            "Salesforce refused read and edit access to the field Contact.Clue_Id__c in the "
            "permission set: insufficient access rights on object id "
            "(INSUFFICIENT_ACCESS_OR_READONLY). The connected user needs to be a Salesforce admin."
        )
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None and state.status == "partial"

    _run(tmp_path, "sf-edit-refused", body, "salesforce")


def test_a_partial_run_never_shrinks_the_record(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        fields = CLUE_FIELDS["salesforce"]
        await record_clue_fields(
            conn,
            connection_id=connection.connection_id,
            workspace_id=seeded.workspace_id,
            provider="salesforce",
            created=fields,
            permission_set_id="0PSjV0000000000",
            label_type_id=None,
            status="ready",
        )
        await conn.execute(
            text(
                "UPDATE crm_clue_fields SET status = 'gone', gone_at = now(), "
                "gone_names = ARRAY['Account.Clue_Tier__c']"
            )
        )
        await _queued_setup(conn, seeded, connection)
        # The second field is refused: this run saw only the first one.
        refused = _ok({"success": False, "errors": [{"message": "Bad label", "statusCode": "X"}]})
        crm = _SchemaCrm(
            failures={
                "SALESFORCE_CREATE_CUSTOM_FIELD": [_ok({"success": True, "id": "00N1"}), refused]
            }
        )
        await _execute(conn, tmp_path, connection, crm)

        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert state.created_names == tuple(f.qualified_name for f in fields)
        assert state.permission_set_id == "0PSjV0000000000"
        # Only a run that reaches ready replaces the gone state.
        assert (state.status, state.gone_names) == ("gone", ("Account.Clue_Tier__c",))

    _run(tmp_path, "sf-no-shrink", body, "salesforce")


def test_a_setup_that_runs_out_of_attempts_names_the_step_it_stopped_at(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _queued_setup(conn, seeded, connection)
        await conn.execute(
            text("UPDATE crm_write SET attempts = 4 WHERE proposal_id = :id"), {"id": proposal_id}
        )
        crm = _SchemaCrm(
            failures={"HUBSPOT_CREATE_PROPERTY_FOR_SPECIFIED_OBJECT_TYPE": [RATE_LIMITED]}
        )
        handler = _handler(conn, tmp_path, crm, crm_write_max_attempts=5)  # type: ignore[arg-type]
        await handler.handle(_context(connection))

        write = await _setup_write(conn, proposal_id)
        assert (write.status, write.retryable, write.attempts) == ("failed", True, 5)
        assert write.crm_message == (
            'Setting up Clue\'s fields stopped at the field "Clue tier" on companies: You have '
            "reached your ten secondly limit. Propose the setup again to finish it."
        )
        assert _steps(write) == [
            ('the property group "Clue" on companies', "created"),
            ('the property group "Clue" on contacts', "created"),
        ]

    _run(tmp_path, "hs-out-of-attempts", body)


class _BudgetRunsOut(_FakeBudget):
    """Salesforce's budget runs out before the ``at``-th call of the run, once."""

    def __init__(self, gateway: Any, at: int) -> None:
        super().__init__(gateway)
        self.at = at

    async def take_call(self, conn: Any, *, connection: Any, today: Any) -> None:
        await super().take_call(conn, connection=connection, today=today)
        if len(self.taken_at) == self.at:
            raise CrmBudgetExhausted("salesforce_api_share_exhausted", "Clue's share is used up.")


def test_a_budget_stop_mid_setup_keeps_partial_and_the_resume_finishes(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _queued_setup(conn, seeded, connection)
        crm = _SchemaCrm()
        # Calls 1-7 make the fields; the 8th (the permission set look-up) finds no budget.
        result = await _execute(conn, tmp_path, connection, crm, budget=_BudgetRunsOut(crm, 8))
        assert result.outcome == "crm_budget" and result.requeue
        assert await _proposal_status(conn, proposal_id) == "paused"
        write = await _setup_write(conn, proposal_id)
        assert (write.status, write.attempts) == ("queued", 0)  # the attempt is refunded
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert (state.status, len(state.created_names)) == ("partial", 7)

        before = dict(crm.sf_fields)
        await _execute(conn, tmp_path, connection, crm)
        assert (await _setup_write(conn, proposal_id)).status == "succeeded"
        assert crm.sf_fields == before
        assert len(crm.permission_sets) == 1
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None and state.status == "ready"

    _run(tmp_path, "sf-budget", body, "salesforce")


def test_an_expired_connection_mid_setup_keeps_partial_and_pauses(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposal_id = await _queued_setup(conn, seeded, connection)
        expired = ComposioError("connection_expired", 410, "Connected account expired")
        crm = _SchemaCrm(failures={"SALESFORCE_CREATE_S_OBJECT_RECORD": [expired]})
        result = await _execute(conn, tmp_path, connection, crm)
        assert result.outcome == "crm_connection_expired"
        assert await _proposal_status(conn, proposal_id) == "paused"
        write = await _setup_write(conn, proposal_id)
        assert (write.status, write.attempts) == ("queued", 0)
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert (state.status, len(state.created_names)) == ("partial", 7)

        # The same connection works again (Composio's account restored): the paused setup resumes
        # and makes nothing twice.
        await conn.execute(
            text(
                "UPDATE workspace_integration_connection SET status = 'active' "
                "WHERE connection_id = :c"
            ),
            {"c": connection.connection_id},
        )
        before = dict(crm.sf_fields)
        await _execute(conn, tmp_path, connection, crm)
        assert (await _setup_write(conn, proposal_id)).status == "succeeded"
        assert crm.sf_fields == before
        assert len(crm.permission_sets) == 1

    _run(tmp_path, "sf-expired", body, "salesforce")
