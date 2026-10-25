"""``find_crm_list@1`` and ``link_crm_list@1`` (CRM integration Phase 3, Task 7; R-11.11).

``find_crm_list`` gives the lists and campaigns Clue keeps for a project (and says when the CRM no
longer has one), and with a name looks the list up in the CRM by that exact name.
``link_crm_list`` keeps a list the person names, after checking in the CRM that it exists and can
take members. Nothing calls a real CRM: the fake gateway answers in the shapes verified live
(composio-api-notes.md § Phase 3 shapes). The database is the lane's test DB.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from clue_api.crm.composio_gateway import ExecuteResult
from clue_api.crm.lists import mark_gone, store_list
from clue_api.crm.target_tools import (
    FindCrmListInput,
    FindCrmListTool,
    LinkCrmListInput,
    LinkCrmListTool,
)
from clue_config import Settings
from clue_core import new_operation_id
from clue_toolbelt import PreconditionFailed, ToolContext
from tests.api.test_crm_tools_db import _connect
from tests.api.test_lane_d4_agent_gate_db import _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


#: HubSpot's verbatim answer for a list name it does not have (the normal "not made yet").
_NAME_MISSING = ExecuteResult(
    False,
    {"http_error": "404", "message": "Not Found", "status_code": 404},
    '{"status":"error","message":"List does not exist with name Q4 hotels and object type ID '
    '0-2.","correlationId":"c","context":{"listName":["Q4 hotels"],"objectTypeId":["0-2"]},'
    '"category":"OBJECT_NOT_FOUND","subCategory":"ListError.LIST_NAME_DOES_NOT_EXIST"}',
)


class _FakeCrm:
    """Answers the list reads the two tools make; every call is recorded."""

    def __init__(
        self,
        *,
        hubspot_lists: Sequence[Mapping[str, Any]] = (),
        campaigns: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self.hubspot_lists = [dict(item) for item in hubspot_lists]
        self.campaigns = [dict(item) for item in campaigns]
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
        if slug == "HUBSPOT_GET_CRM_LIST_BY_NAME":
            for item in self.hubspot_lists:
                if (
                    item["name"].lower() == arguments["list_name"].lower()
                    and item["objectTypeId"] == arguments["object_type_id"]
                ):
                    return ExecuteResult(True, {"data": {"list": item}}, None)
            return _NAME_MISSING
        if slug == "HUBSPOT_SEARCH_CRM_LISTS":
            found = [
                item
                for item in self.hubspot_lists
                if item["listId"] in arguments.get("listIds", [])
                and item["objectTypeId"] == arguments["objectTypeId"]
            ]
            body = {"lists": found, "total": len(found), "offset": 0, "hasMore": False}
            return ExecuteResult(True, {"data": body}, None)
        if slug == "SALESFORCE_GET_ORG_LIMITS":
            return ExecuteResult(
                True, {"data": {"DailyApiRequests": {"Max": 15000, "Remaining": 14000}}}, None
            )
        if slug == "SALESFORCE_RUN_SOQL_QUERY":
            query = arguments["query"]
            by_name = re.search(r"Name = '((?:[^'\\]|\\.)*)'", query)
            by_id = re.search(r"Id = '([A-Za-z0-9]+)'", query)
            if by_name is not None:
                wanted = re.sub(r"\\(.)", r"\1", by_name.group(1))
                found = [c for c in self.campaigns if c["Name"] == wanted]
            else:
                assert by_id is not None, query
                found = [c for c in self.campaigns if c["Id"][:15] == by_id.group(1)[:15]]
            records = [{"attributes": {"type": "Campaign"}, **c} for c in found]
            return ExecuteResult(
                True, {"data": {"records": records, "totalSize": len(records), "done": True}}, None
            )
        raise AssertionError(f"unexpected read {slug}")


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        crm_integration_enabled=True,
        composio_hubspot_auth_config_id="ac_h",
        composio_salesforce_auth_config_id="ac_s",
    )


def _ctx(conn: Any, workspace_id: str) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
    )


def _find(conn: Any, crm: _FakeCrm) -> FindCrmListTool:
    return FindCrmListTool(
        settings=_settings(),
        gateway=crm,  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
    )


def _link(conn: Any, crm: _FakeCrm) -> LinkCrmListTool:
    return LinkCrmListTool(
        settings=_settings(),
        gateway=crm,  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
    )


def _run(tmp_path: Path, label: str, body: Any, provider: str = "hubspot") -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmlt-{label}", label=label)
            connection = await _connect(conn, seeded.workspace_id, provider)
            await body(conn, seeded, connection)

    run_async(scenario())


async def _keep(
    conn: Any, seeded: Any, connection: Any, *, crm_list_id: str, name: str, by_clue: bool = True
) -> Any:
    return await store_list(
        conn,
        workspace_id=seeded.workspace_id,
        connection_id=connection.connection_id,
        provider=connection.provider,
        crm_object="company" if connection.provider == "hubspot" else "contact",
        crm_list_id=crm_list_id,
        name=name,
        kind="hubspot_list" if connection.provider == "hubspot" else "salesforce_campaign",
        created_by_clue=by_clue,
        created_by_write_id=None,
        project_id=seeded.project_id,
    )


def _hubspot_list(list_id: str, name: str, processing: str = "MANUAL") -> dict[str, Any]:
    return {
        "listId": list_id,
        "name": name,
        "objectTypeId": "0-2",
        "processingType": processing,
        "processingStatus": "COMPLETE",
        "listVersion": 1,
        "size": 3,
    }


def test_find_returns_the_stored_list_first(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _keep(conn, seeded, connection, crm_list_id="17", name="Clue: Q4 hotels")
        crm = _FakeCrm(hubspot_lists=[_hubspot_list("17", "Clue: Q4 hotels")])
        tool = _find(conn, crm)
        ctx = _ctx(conn, seeded.workspace_id)
        inputs = FindCrmListInput(project_id=seeded.project_id)
        assert await tool.preconditions(inputs, ctx) == ()
        refs = (await tool.invoke(inputs, ctx)).references
        assert refs["connected_crm"] == "hubspot"
        assert refs["lists"] == [
            {
                "crm_list_id": "17",
                "name": "Clue: Q4 hotels",
                "object": "company",
                "manual": True,
                "stored": True,
                "gone": False,
                "created_by_clue": True,
                "active": None,
            }
        ]
        assert refs["found"] == []
        # Without a name, only Clue's own records are read: the CRM is not called.
        assert crm.calls == []

    _run(tmp_path, "stored", body)


def test_find_by_name_in_the_crm(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _keep(conn, seeded, connection, crm_list_id="17", name="Clue: Q4 hotels")
        crm = _FakeCrm(
            hubspot_lists=[
                _hubspot_list("17", "Clue: Q4 hotels"),
                _hubspot_list("42", "Hotel groups EMEA"),
            ]
        )
        tool = _find(conn, crm)
        ctx = _ctx(conn, seeded.workspace_id)
        refs = (
            await tool.invoke(
                FindCrmListInput(project_id=seeded.project_id, name="hotel groups emea"), ctx
            )
        ).references
        # The project's kept list comes first; the one found by name is not kept yet.
        assert [item["crm_list_id"] for item in refs["lists"]] == ["17"]
        assert refs["found"] == [
            {
                "crm_list_id": "42",
                "name": "Hotel groups EMEA",
                "object": "company",
                "manual": True,
                "stored": False,
                "gone": False,
                "created_by_clue": False,
                "active": None,
            }
        ]
        assert crm.calls == [
            (
                "HUBSPOT_GET_CRM_LIST_BY_NAME",
                {"object_type_id": "0-2", "list_name": "hotel groups emea"},
            )
        ]
        # A name HubSpot does not have is an empty answer, said in words.
        missing = (
            await tool.invoke(FindCrmListInput(project_id=seeded.project_id, name="Q4 hotels"), ctx)
        ).references
        assert missing["found"] == []
        assert "Q4 hotels" in missing["note"]

    _run(tmp_path, "byname", body)


def test_find_by_name_on_salesforce_lists_every_campaign_of_that_name(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm = _FakeCrm(
            campaigns=[
                {
                    "Id": "701000000000001AAA",
                    "Name": "O'Hare events",
                    "IsActive": False,
                    "Status": "Completed",
                },
                {
                    "Id": "701000000000002AAA",
                    "Name": "O'Hare events",
                    "IsActive": True,
                    "Status": "In Progress",
                },
            ]
        )
        refs = (
            await _find(conn, crm).invoke(
                FindCrmListInput(project_id=seeded.project_id, name="O'Hare events"),
                _ctx(conn, seeded.workspace_id),
            )
        ).references
        assert [(f["crm_list_id"], f["active"], f["object"]) for f in refs["found"]] == [
            ("701000000000002AAA", True, "contact"),
            ("701000000000001AAA", False, "contact"),
        ]
        assert all(f["manual"] for f in refs["found"])
        assert "2 campaigns" in refs["note"]
        soql = [args["query"] for slug, args in crm.calls if slug == "SALESFORCE_RUN_SOQL_QUERY"]
        assert soql and "Name = 'O\\'Hare events'" in soql[0]
        # Each Salesforce read is taken from the org's daily share: the lookup, and the org-limits
        # read the share is checked against.
        counted = await conn.execute(
            text(
                "SELECT api_calls_count FROM workspace_integration_connection "
                "WHERE connection_id = :c"
            ),
            {"c": connection.connection_id},
        )
        assert counted.scalar_one() == 2

    _run(tmp_path, "sfname", body, provider="salesforce")


def test_a_gone_list_is_reported_as_gone(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _keep(conn, seeded, connection, crm_list_id="17", name="Clue: Q4 hotels")
        await _keep(conn, seeded, connection, crm_list_id="18", name="Clue: Q1 hotels")
        await mark_gone(conn, connection_id=connection.connection_id, crm_list_id="17")
        crm = _FakeCrm()
        refs = (
            await _find(conn, crm).invoke(
                FindCrmListInput(project_id=seeded.project_id), _ctx(conn, seeded.workspace_id)
            )
        ).references
        # The live list first, then the gone one, marked gone and not offered as kept.
        assert [(i["crm_list_id"], i["gone"], i["stored"]) for i in refs["lists"]] == [
            ("18", False, True),
            ("17", True, False),
        ]
        assert "Clue: Q4 hotels" in refs["note"] and "no longer" in refs["note"]

    _run(tmp_path, "gone", body)


def test_link_stores_a_named_manual_list_not_created_by_clue(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm = _FakeCrm(hubspot_lists=[_hubspot_list("42", "Hotel groups EMEA")])
        tool = _link(conn, crm)
        ctx = _ctx(conn, seeded.workspace_id)
        inputs = LinkCrmListInput(project_id=seeded.project_id, crm_list_id="42")
        assert await tool.preconditions(inputs, ctx) == ()
        refs = (await tool.invoke(inputs, ctx)).references
        assert refs["list"] == {
            "crm_list_id": "42",
            "name": "Hotel groups EMEA",
            "object": "company",
            "manual": True,
            "stored": True,
            "gone": False,
            "created_by_clue": False,
            "active": None,
        }
        assert crm.calls == [
            ("HUBSPOT_SEARCH_CRM_LISTS", {"objectTypeId": "0-2", "listIds": ["42"], "count": 1})
        ]
        # Linking again changes nothing.
        await tool.invoke(inputs, _ctx(conn, seeded.workspace_id))
        rows = await conn.execute(
            text(
                "SELECT l.crm_list_id, l.kind, l.crm_object, l.created_by_clue, p.project_id, "
                "p.linked_by FROM crm_list l JOIN crm_list_project p ON p.list_id = l.list_id "
                "WHERE l.connection_id = :c"
            ),
            {"c": connection.connection_id},
        )
        assert [tuple(row) for row in rows] == [
            ("42", "hubspot_list", "company", False, seeded.project_id, "person_named")
        ]
        # The project's list is offered by find_crm_list from now on.
        found = (
            await _find(conn, crm).invoke(
                FindCrmListInput(project_id=seeded.project_id), _ctx(conn, seeded.workspace_id)
            )
        ).references
        assert [item["crm_list_id"] for item in found["lists"]] == ["42"]

    _run(tmp_path, "link", body)


def test_link_stores_a_named_salesforce_campaign(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm = _FakeCrm(
            campaigns=[
                {
                    "Id": "701jV00000Hd83xQAB",
                    "Name": "Q4 events",
                    "IsActive": True,
                    "Status": "In Progress",
                }
            ]
        )
        refs = (
            await _link(conn, crm).invoke(
                LinkCrmListInput(project_id=seeded.project_id, crm_list_id="701jV00000Hd83x"),
                _ctx(conn, seeded.workspace_id),
            )
        ).references
        # Kept under the 18-character id Salesforce answers.
        assert refs["list"]["crm_list_id"] == "701jV00000Hd83xQAB"
        assert refs["list"]["object"] == "contact" and refs["list"]["active"] is True
        kind = await conn.execute(
            text("SELECT kind, created_by_clue FROM crm_list WHERE connection_id = :c"),
            {"c": connection.connection_id},
        )
        assert tuple(kind.one()) == ("salesforce_campaign", False)

    _run(tmp_path, "sflink", body, provider="salesforce")


def test_link_refuses_a_dynamic_list(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        crm = _FakeCrm(hubspot_lists=[_hubspot_list("43", "Hotels by rule", "DYNAMIC")])
        tool = _link(conn, crm)
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(
                LinkCrmListInput(project_id=seeded.project_id, crm_list_id="43"),
                _ctx(conn, seeded.workspace_id),
            )
        assert refused.value.failures[0].reason_code == "crm_list_not_manual"
        with pytest.raises(PreconditionFailed) as unknown:
            await tool.invoke(
                LinkCrmListInput(project_id=seeded.project_id, crm_list_id="999"),
                _ctx(conn, seeded.workspace_id),
            )
        assert unknown.value.failures[0].reason_code == "crm_list_not_found"
        kept = await conn.execute(
            text("SELECT count(*) FROM crm_list WHERE connection_id = :c"),
            {"c": connection.connection_id},
        )
        assert kept.scalar_one() == 0

    _run(tmp_path, "dynamic", body)


def test_link_refuses_another_workspaces_project(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        other = await _seed(conn, tmp_path, workspace_id="ws-crmlt-elsewhere", label="elsewhere")
        crm = _FakeCrm(hubspot_lists=[_hubspot_list("42", "Hotel groups EMEA")])
        tool = _link(conn, crm)
        ctx = _ctx(conn, seeded.workspace_id)
        inputs = LinkCrmListInput(project_id=other.project_id, crm_list_id="42")
        failures = await tool.preconditions(inputs, ctx)
        assert [f.reason_code for f in failures] == ["project_not_found"]
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(inputs, ctx)
        assert refused.value.failures[0].reason_code == "project_not_found"
        assert crm.calls == []
        find_failures = await _find(conn, crm).preconditions(
            FindCrmListInput(project_id=other.project_id), ctx
        )
        assert [f.reason_code for f in find_failures] == ["project_not_found"]

    _run(tmp_path, "otherws", body)
