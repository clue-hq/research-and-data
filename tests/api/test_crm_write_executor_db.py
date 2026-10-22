"""The CRM write executor and its wake turn (CRM integration Phase 2, Task 6).

A queued proposal's chosen changes are logged ``sending`` before each call, checked against what
the CRM holds now (a record changed since the card is skipped as ``conflict``), sent, read back
(``succeeded`` only when the value landed, else ``failed`` / ``not_applied``), and never sent twice.
Rate limits requeue with back-off; refusals are not retried; an expired connection pauses the
proposal until a reconnect; a finished proposal wakes its chat once. The CRM is a fake gateway
that can fail chosen calls; the database is the lane's test DB.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.agent_turn_submission import DERIVATION_CRM_WRITES_FINISHED
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.crm import writes
from clue_api.crm.composio_gateway import ComposioError, ExecuteResult
from clue_api.crm.connections import (
    CrmConnection,
    activate_from_attempt,
    open_connect_request,
    start_attempt,
)
from clue_api.crm.lists import lists_for_project, store_list
from clue_api.crm.salesforce_budget import CrmBudgetExhausted
from clue_api.crm.wake import queue_crm_writes_finished_turn
from clue_api.crm.write_executor import (
    CrmWriteHandler,
    close_replaced_connection_proposals,
    crm_reply,
    failure_kind,
)
from clue_api.crm.write_prepare import ProposedChange, prepare_changes
from clue_api.crm.write_tools import CrmWriteLogInput
from clue_config import Settings
from clue_fleet import WorkContext, WorkId, WorkResult
from clue_storage import FsStorage
from tests.api.test_crm_propose_db import _ctx
from tests.api.test_crm_tools_db import _connect
from tests.api.test_crm_write_log_tools_db import _log_tool
from tests.api.test_crm_write_prepare_db import _FakeBudget, _FakeCrm
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
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


Hook = Callable[[str, dict[str, Any]], Awaitable[None]]


class _WritingCrm(_FakeCrm):
    """The read fake plus writes: it applies HubSpot batch updates and list memberships to its
    records, and fails chosen calls.

    ``failures[slug]`` is consumed one entry per call of that slug: a :class:`ComposioError` is
    raised, an :class:`ExecuteResult` is returned, ``"crash"`` applies the write then raises (the
    worker dies after the CRM wrote), ``None`` behaves normally. ``ignored`` properties are
    accepted and silently not written (HubSpot's read-only properties).
    """

    def __init__(
        self,
        *,
        failures: Mapping[str, list[Any]] | None = None,
        ignored: frozenset[str] = frozenset(),
        on_write: Hook | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.failures = {slug: list(items) for slug, items in (failures or {}).items()}
        self.ignored = ignored
        self.on_write = on_write
        #: Salesforce records the composite call refuses (inside a successful answer).
        self.refused_records: set[str] = set()
        #: Lists (HubSpot) and campaigns (Salesforce) by name: their CRM ids.
        self.crm_lists: dict[str, str] = {}
        #: (campaign id, contact id) of each Salesforce campaign member.
        self.campaign_members: set[tuple[str, str]] = set()

    @property
    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        return [call for call in self.calls if call[0] in _WRITE_SLUGS]

    async def execute(self, *, slug: str, arguments: Mapping[str, Any], **kwargs: Any) -> Any:
        queued = self.failures.get(slug)
        failure = queued.pop(0) if queued else None
        if slug not in _WRITE_SLUGS:
            list_read = self._list_read(slug, arguments)
            if list_read is not None and not isinstance(failure, ComposioError | ExecuteResult):
                self.calls.append((slug, dict(arguments)))
                return list_read
            if isinstance(failure, ComposioError):
                self.calls.append((slug, dict(arguments)))
                raise failure
            if isinstance(failure, ExecuteResult):
                self.calls.append((slug, dict(arguments)))
                return failure
            if slug == "HUBSPOT_READ_CRM_OBJECT_BY_ID" and str(arguments["objectId"]) not in (
                self.records
            ):
                self.calls.append((slug, dict(arguments)))
                return _NOT_FOUND
            if slug == _BATCH_READ:  # HubSpot leaves out a record it does not have
                self.calls.append((slug, dict(arguments)))
                held = [i for i in arguments["inputs"] if i["id"] in self.records]
                answer = self._answer(slug, {**arguments, "inputs": held})
                return ExecuteResult(True, {"data": answer}, None)
            return await super().execute(slug=slug, arguments=arguments, **kwargs)
        self.calls.append((slug, dict(arguments)))
        if self.on_write is not None:
            await self.on_write(slug, dict(arguments))
        if isinstance(failure, ComposioError):
            raise failure
        if isinstance(failure, ExecuteResult):
            return failure
        answer = self._write(slug, arguments)
        if failure == "crash":
            raise RuntimeError("the worker died after the CRM wrote")
        return ExecuteResult(True, {"data": answer}, None)

    def _list_read(self, slug: str, arguments: Mapping[str, Any]) -> ExecuteResult | None:
        """HubSpot's list-by-name read and Salesforce's Campaign SOQL (composio-api-notes.md
        § Phase 3 shapes)."""
        if slug == "HUBSPOT_SEARCH_CRM_LISTS":
            wanted = {str(i) for i in arguments.get("listIds") or []}
            found = [
                {"listId": i, "name": n, "objectTypeId": arguments["objectTypeId"]}
                for n, i in self.crm_lists.items()
                if i in wanted
            ]
            return ExecuteResult(
                True,
                {"data": {"lists": found, "total": len(found), "offset": 0, "hasMore": False}},
                None,
            )
        if slug == "HUBSPOT_GET_CRM_LIST_BY_NAME":
            name = str(arguments["list_name"])
            # HubSpot matches the name ignoring case, and answers the name it holds.
            held = next((n for n in self.crm_lists if n.lower() == name.lower()), None)
            if held is None:
                return _LIST_NAME_MISSING
            list_id = self.crm_lists[held]
            return ExecuteResult(
                True,
                {
                    "data": {
                        "list": {
                            "listId": list_id,
                            "name": held,
                            "objectTypeId": arguments["object_type_id"],
                            "processingType": "MANUAL",
                        }
                    }
                },
                None,
            )
        query = str(arguments.get("query", ""))
        if slug == "SALESFORCE_RUN_SOQL_QUERY" and "FROM CampaignMember" in query:
            campaign = re.search(r"CampaignId = '([^']*)'", query)
            assert campaign is not None
            found = [
                {"attributes": {"type": "CampaignMember"}, "ContactId": contact}
                for member_of, contact in sorted(self.campaign_members)
                if member_of == campaign.group(1) and f"'{contact}'" in query
            ]
            return ExecuteResult(
                True, {"data": {"records": found, "totalSize": len(found), "done": True}}, None
            )
        if slug == "SALESFORCE_RUN_SOQL_QUERY" and "FROM Campaign" in query:
            by_name = re.search(r"Name = '(.*)'", query)
            by_id = re.search(r"Id = '(.*)'", query)
            found = [
                {"attributes": {"type": "Campaign"}, "Id": i, "Name": n}
                for n, i in self.crm_lists.items()
                if (by_name is not None and n == by_name.group(1))
                or (by_id is not None and i == by_id.group(1))
            ]
            return ExecuteResult(
                True, {"data": {"records": found, "totalSize": len(found), "done": True}}, None
            )
        return None

    def _write(self, slug: str, arguments: Mapping[str, Any]) -> Any:
        if slug == "HUBSPOT_CREATE_LIST":
            list_id = str(17 + len(self.crm_lists))
            self.crm_lists[str(arguments["name"])] = list_id
            # The Task 1 answer: the list, with no size on create.
            return {
                "list": {
                    "listId": list_id,
                    "name": arguments["name"],
                    "objectTypeId": arguments["object_type_id"],
                    "processingType": "MANUAL",
                    "processingStatus": "COMPLETE",
                    "listVersion": 1,
                    "createdAt": "2026-10-23T10:00:00Z",
                }
            }
        if slug == "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN":
            self.campaign_members.add((str(arguments["campaign_id"]), str(arguments["contact_id"])))
            # The verified answer (composio-api-notes.md § Phase 3 shapes).
            return {"errors": [], "id": "00vjV000003bbV7QAI", "success": True}
        if slug == "SALESFORCE_CREATE_CAMPAIGN":
            # The verified answer (composio-api-notes.md § Phase 3 shapes): an 18-character id.
            campaign_id = f"701jV00000Hd83x{len(self.crm_lists):03d}"
            self.crm_lists[str(arguments["name"])] = campaign_id
            return {"errors": [], "id": campaign_id, "success": True}
        if slug == "HUBSPOT_CREATE_CONTACT":
            record_id = str(500 + len(self.records))
            self.records[record_id] = dict(arguments)
            # The created object, as the notes give it: {id, properties, createdAt, ...}.
            return {"id": record_id, "properties": dict(arguments), "createdAt": "2026-10-22"}
        if slug in ("HUBSPOT_UPDATE_COMPANIES", "HUBSPOT_UPDATE_CONTACTS"):
            for item in arguments["inputs"]:
                record = self.records.setdefault(str(item["id"]), {})
                record.update(
                    {k: v for k, v in item["properties"].items() if k not in self.ignored}
                )
            return {"status": "COMPLETE", "results": [{"id": i["id"]} for i in arguments["inputs"]]}
        if slug == "HUBSPOT_UPDATE_LIST_MEMBERSHIPS":
            for record in arguments["record_ids"]:
                lists = self.lists.setdefault(str(record), [])
                if arguments["operation"] == "add" and arguments["list_id"] not in lists:
                    lists.append(arguments["list_id"])
                if arguments["operation"] == "remove" and arguments["list_id"] in lists:
                    lists.remove(arguments["list_id"])
            return {"recordsIdsAdded": arguments["record_ids"], "recordIdsMissing": []}
        if slug == "SALESFORCE_PATCH_COMPOSITE_SOBJECTS":
            results = []
            for record in arguments["records"]:
                fields = {k: v for k, v in record.items() if k not in ("attributes", "Id")}
                if record["Id"] in self.refused_records:
                    errors = [
                        {
                            "statusCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION",
                            "message": "Tier accounts need an owner.",
                            "fields": [],
                        }
                    ]
                    results.append({"id": record["Id"], "success": False, "errors": errors})
                    continue
                self.records.setdefault(record["Id"], {}).update(fields)
                results.append({"id": record["Id"], "success": True, "errors": []})
            # Salesforce answers ``successful`` even when records fail.
            return {"results": results}
        raise AssertionError(f"unexpected write {slug}")


_WRITE_SLUGS = frozenset(
    {
        "HUBSPOT_UPDATE_COMPANIES",
        "HUBSPOT_UPDATE_CONTACTS",
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        "SALESFORCE_PATCH_COMPOSITE_SOBJECTS",
        "HUBSPOT_CREATE_CONTACT",
        "HUBSPOT_CREATE_LIST",
        "SALESFORCE_CREATE_CAMPAIGN",
        "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN",
    }
)

#: HubSpot's answer for a list name it does not have: the normal "not made yet" answer.
_LIST_NAME_MISSING = ExecuteResult(
    False,
    {"http_error": "404", "status_code": 404, "message": "Not Found"},
    '{"status":"error","message":"List does not exist with name Clue: Q4 and object type ID 0-2.",'
    '"correlationId":"c","context":{"listName":["Clue: Q4"],"objectTypeId":["0-2"]},'
    '"category":"OBJECT_NOT_FOUND","subCategory":"ListError.LIST_NAME_DOES_NOT_EXIST"}',
)
#: HubSpot's answer to a membership change of a list that was deleted (verbatim, Task 1).
_LIST_GONE_BODY = (
    '{"status":"error","message":"List does not exist with ID 17.","correlationId":"c",'
    '"context":{"listId":["17"]},"category":"OBJECT_NOT_FOUND",'
    '"subCategory":"ListError.LIST_ID_DOES_NOT_EXIST"}'
)
_LIST_GONE = ExecuteResult(
    False, {"http_error": "404", "status_code": 404, "message": "Not Found"}, _LIST_GONE_BODY
)
#: Salesforce's refusal of a campaign create by a user who is not a Marketing User (Task 1).
_NOT_A_MARKETING_USER = (
    '[{"message":"entity type cannot be inserted: Campaign",'
    '"errorCode":"CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY","fields":[]}]'
)

_BATCH_READ = "HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES"

#: HubSpot's answer for a record that is not there (HTTP 404 inside a refused call).
_NOT_FOUND = ExecuteResult(
    False,
    {"http_error": "404", "status_code": 404, "message": "Not Found"},
    '{"status":"error","message":"resource not found","category":"OBJECT_NOT_FOUND"}',
)
_INVALID_OPTION = ExecuteResult(
    False,
    {"http_error": "400", "status_code": 400},
    '{"status":"error","message":"Property values were not valid","errors":[{"code":'
    '"INVALID_OPTION"}],"category":"VALIDATION_ERROR"}',
)

_HUBSPOT_DUPLICATE = (
    '{"status":"error","message":"Cannot set PropertyValueCoordinates{portalId=1, '
    "objectTypeId=ObjectTypeId{legacyObjectType=CONTACT}, propertyName=email, value=a@b.co} on "
    '201. 202 already has that value.","correlationId":"c","category":"VALIDATION_ERROR"}'
)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "crm_integration_enabled": True,
        "composio_hubspot_auth_config_id": "ac_h",
        "composio_salesforce_auth_config_id": "ac_s",
        "crm_write_min_interval_s": 0,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def _context(connection: CrmConnection) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=WorkId(connection.connection_id),
        worker_id="test-worker",
        lease_generation=1,  # type: ignore[arg-type]
        payload={},
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def _handler(
    conn: Any, tmp_path: Path, gateway: _FakeCrm, budget: Any = None, **settings: Any
) -> CrmWriteHandler:
    return CrmWriteHandler(
        settings=_settings(**settings),
        gateway=gateway,  # type: ignore[arg-type]
        artifacts=DurableAgentArtifactStore(
            storage=FsStorage(tmp_path / "wake-artifacts"), conn_factory=conn_session_factory(conn)
        ),
        conn_factory=conn_session_factory(conn),
        budget=budget or _FakeBudget(gateway),
    )


def _tier(record: str, tier: str) -> ProposedChange:
    return ProposedChange(
        slug="HUBSPOT_UPDATE_COMPANY",
        arguments={"companyId": record, "properties": {"icp_tier": tier}},
        reason="The ICP tier Clue scored.",
    )


def _title(record: str, title: str) -> ProposedChange:
    return ProposedChange(
        slug="HUBSPOT_UPDATE_CONTACTS",
        arguments={"inputs": [{"id": record, "properties": {"jobtitle": title}}]},
        reason="The title Clue found.",
    )


def _email(record: str, email: str) -> ProposedChange:
    return ProposedChange(
        slug="HUBSPOT_UPDATE_CONTACTS",
        arguments={"inputs": [{"id": record, "properties": {"email": email}}]},
        reason="The work email Clue found.",
    )


async def _propose(
    conn: Any,
    seeded: Any,
    connection: CrmConnection,
    gateway: _FakeCrm,
    *changes: ProposedChange,
    status: str = "queued",
    unselect: frozenset[str] = frozenset(),
) -> UUID:
    """Prepare and log a proposal the way propose_crm_changes does, then move it to ``status``."""
    proposal_id = uuid4()
    calls_before = len(gateway.calls)
    batch = await prepare_changes(
        conn,
        gateway=gateway,  # type: ignore[arg-type]
        budget=_FakeBudget(gateway),
        connection=connection,
        proposal_id=proposal_id,
        project_id=seeded.project_id,
        changes=list(changes),
        version="v",
    )
    assert batch.refused == []
    prepared = batch.changes
    del gateway.calls[calls_before:]  # only the executor's calls are asserted
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
        prepared=prepared,
    )
    if unselect:
        await conn.execute(
            text(
                "UPDATE crm_write SET selected = false "
                "WHERE proposal_id = :id AND record_ref = ANY(:records)"
            ),
            {"id": proposal_id, "records": sorted(unselect)},
        )
    await writes.set_proposal_status(conn, proposal_id=proposal_id, status=status)
    # One test transaction gives every row the same now(): order proposals as they were made.
    await conn.execute(
        text(
            "UPDATE crm_write_proposal SET created_at = clock_timestamp() WHERE proposal_id = :id"
        ),
        {"id": proposal_id},
    )
    return proposal_id


async def _writes(conn: Any, proposal_id: UUID) -> dict[str, dict[str, Any]]:
    rows = await conn.execute(
        text(
            "SELECT record_ref, status, failure_kind, crm_message, crm_response, retryable, "
            "attempts, sent_at IS NOT NULL AS sent, crm_id FROM crm_write WHERE proposal_id = :id"
        ),
        {"id": proposal_id},
    )
    return {row.record_ref: dict(row._mapping) for row in rows}


async def _proposal_status(conn: Any, proposal_id: UUID) -> str:
    return str(
        await conn.scalar(
            text("SELECT status FROM crm_write_proposal WHERE proposal_id = :id"),
            {"id": proposal_id},
        )
    )


async def _wake_messages(conn: Any, workspace_id: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT s.idempotency_key FROM agent_turn_submission s "
            "WHERE s.workspace_id = :ws AND s.derivation = :d ORDER BY s.idempotency_key"
        ),
        {"ws": workspace_id, "d": DERIVATION_CRM_WRITES_FINISHED},
    )
    return [row.idempotency_key for row in rows]


async def _reconnect(conn: Any, workspace_id: str) -> CrmConnection:
    """The person connects the same CRM again: Composio gives a new connected account."""
    request = await open_connect_request(
        conn,
        workspace_id=workspace_id,
        project_id="p",
        thread_id="t",
        turn_id=uuid4(),
        requested_by_user_id=USER_ID,
        mode="reconnect",
    )
    await start_attempt(
        conn,
        request_id=request.request_id,
        workspace_id=workspace_id,
        provider="hubspot",
        connected_account_id="ca_hubspot_again",
        started_by_user_id=USER_ID,
    )
    activated = await activate_from_attempt(
        conn,
        request_id=request.request_id,
        workspace_id=workspace_id,
        connected_account_id="ca_hubspot_again",
        auth_config_id="ac_h",
    )
    assert activated is not None
    return activated[0]


async def _wake_message(conn: Any, tmp_path: Path, key: str) -> str:
    artifact_key = await conn.scalar(
        text("SELECT message_artifact_key FROM agent_turn_submission WHERE idempotency_key = :k"),
        {"k": key},
    )
    return (await FsStorage(tmp_path / "wake-artifacts").get(artifact_key)).decode()


async def _handle(handler: CrmWriteHandler, connection: CrmConnection) -> WorkResult:
    return await handler.handle(_context(connection))


def _run(tmp_path: Path, label: str, body: Any, provider: str = "hubspot") -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmx-{label}", label=label)
            connection = await _connect(conn, seeded.workspace_id, provider)
            await body(conn, seeded, connection)

    run_async(scenario())


def test_selected_changes_are_sent_and_logged_before_sending(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        logged_at_send: list[dict[str, dict[str, Any]]] = []
        proposal_holder: list[UUID] = []

        async def on_write(slug: str, arguments: dict[str, Any]) -> None:
            del slug, arguments
            logged_at_send.append(await _writes(conn, proposal_holder[0]))

        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "102": {"icp_tier": None}, "103": {}},
            on_write=on_write,
        )
        proposal_id = await _propose(
            conn,
            seeded,
            connection,
            gateway,
            _tier("101", "Tier 1"),
            _tier("102", "Tier 2"),
            _tier("103", "Tier 3"),
            unselect=frozenset({"103"}),
        )
        proposal_holder.append(proposal_id)
        # A declined proposal is never sent.
        declined = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 3"), status="declined"
        )

        result = await _handle(_handler(conn, tmp_path, gateway), connection)

        assert result.outcome == "done" and not result.requeue
        # One batch call carried the two chosen changes; the unchosen one was not sent.
        assert gateway.writes == [
            (
                "HUBSPOT_UPDATE_COMPANIES",
                {
                    "inputs": [
                        {"id": "101", "properties": {"icp_tier": "Tier 1"}},
                        {"id": "102", "properties": {"icp_tier": "Tier 2"}},
                    ]
                },
            )
        ]
        # At the moment of the call both were already logged as being sent.
        (at_send,) = logged_at_send
        for record in ("101", "102"):
            assert at_send[record]["status"] == "sending"
            assert at_send[record]["attempts"] == 1 and at_send[record]["sent"]
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == logged["102"]["status"] == "succeeded"
        assert logged["101"]["crm_id"] == "101"
        assert logged["103"]["status"] == "skipped" and not logged["103"]["sent"]
        assert gateway.records["101"]["icp_tier"] == "Tier 1"
        assert gateway.records["103"].get("icp_tier") is None
        assert await _proposal_status(conn, proposal_id) == "finished"
        assert await _proposal_status(conn, declined) == "declined"
        assert {row["status"] for row in (await _writes(conn, declined)).values()} == {"proposed"}

    _run(tmp_path, "send", body)


def test_a_record_changed_since_the_card_is_skipped_as_conflict(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={"101": {"icp_tier": None}, "102": {"icp_tier": None}})
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _tier("102", "Tier 2")
        )
        gateway.records["102"]["icp_tier"] = "Tier 3"  # a person changed it after the card

        await _handle(_handler(conn, tmp_path, gateway), connection)

        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == "succeeded"
        assert logged["102"]["status"] == "skipped"
        assert logged["102"]["failure_kind"] == "conflict"
        assert "'Tier 3'" in logged["102"]["crm_message"]
        assert not logged["102"]["sent"]
        assert gateway.writes == [
            (
                "HUBSPOT_UPDATE_COMPANIES",
                {"inputs": [{"id": "101", "properties": {"icp_tier": "Tier 1"}}]},
            )
        ]
        assert gateway.records["102"]["icp_tier"] == "Tier 3"

    _run(tmp_path, "conflict", body)


def test_a_retried_task_never_sends_a_change_twice(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        # The company batch goes through; the worker dies right after the CRM wrote the contact.
        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "201": {"jobtitle": None}},
            failures={"HUBSPOT_UPDATE_CONTACTS": ["crash"]},
        )
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _title("201", "CFO")
        )
        handler = _handler(conn, tmp_path, gateway)
        with pytest.raises(RuntimeError):
            await _handle(handler, connection)
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == "succeeded"
        assert logged["201"]["status"] == "sending" and logged["201"]["attempts"] == 1

        # The task is retried: the company is not sent again, and the contact — which the CRM
        # did write — is found written and not sent again either.
        result = await _handle(handler, connection)

        assert result.outcome == "done"
        assert [slug for slug, _ in gateway.writes] == [
            "HUBSPOT_UPDATE_COMPANIES",
            "HUBSPOT_UPDATE_CONTACTS",
        ]
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == logged["201"]["status"] == "succeeded"
        assert logged["101"]["attempts"] == logged["201"]["attempts"] == 1
        assert await _proposal_status(conn, proposal_id) == "finished"

    _run(tmp_path, "retry", body)


def test_a_rate_limit_requeues_with_backoff_and_a_refusal_is_not_retried(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        limited = ComposioError("rate_limited", 429, "Too many requests")
        refusal = ExecuteResult(
            False, {"http_error": "400", "status_code": 400}, _HUBSPOT_DUPLICATE
        )
        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "201": {"email": None}, "301": {"icp_tier": None}},
            failures={
                "HUBSPOT_UPDATE_COMPANIES": [limited, limited, limited],
                "HUBSPOT_UPDATE_CONTACTS": [refusal],
            },
        )
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _email("201", "a@b.co")
        )
        handler = _handler(conn, tmp_path, gateway, crm_write_max_attempts=2)

        first = await _handle(handler, connection)
        assert first.requeue and first.requeue_after == timedelta(seconds=30)
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == "queued" and logged["101"]["attempts"] == 1
        assert logged["201"]["attempts"] == 0  # nothing behind the limit was sent
        assert await _proposal_status(conn, proposal_id) == "queued"

        # The second send is limited again: that is its last attempt, so it fails (retryable) and
        # the contact goes on, which the CRM refuses — that is final.
        second = await _handle(handler, connection)
        assert not second.requeue
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == "failed"
        assert (logged["101"]["failure_kind"], logged["101"]["retryable"]) == ("rate_limited", True)
        assert logged["101"]["attempts"] == 2
        assert logged["201"]["status"] == "failed"
        assert (logged["201"]["failure_kind"], logged["201"]["retryable"]) == (
            "duplicate_rule",
            False,
        )
        # The card and the log show HubSpot's message; its whole answer is kept beside it.
        assert logged["201"]["crm_message"] == (
            "Cannot set PropertyValueCoordinates{portalId=1, objectTypeId=ObjectTypeId"
            "{legacyObjectType=CONTACT}, propertyName=email, value=a@b.co} on 201. 202 already "
            "has that value."
        )
        assert logged["201"]["crm_response"] == json.loads(_HUBSPOT_DUPLICATE)
        assert await _proposal_status(conn, proposal_id) == "finished"

        # A third run sends nothing: neither the refusal nor the spent change is retried.
        sent = len(gateway.writes)
        await _handle(handler, connection)
        assert len(gateway.writes) == sent

        # A fresh proposal's back-off doubles from the base by its own attempts.
        other = await _propose(conn, seeded, connection, gateway, _tier("301", "Tier 2"))
        limited_again = await _handle(
            _handler(conn, tmp_path, gateway, crm_write_retry_base_s=10), connection
        )
        assert limited_again.requeue_after == timedelta(seconds=10)
        assert (await _writes(conn, other))["301"]["status"] == "queued"

    _run(tmp_path, "ratelimit", body)


async def _connection_status(conn: Any, connection: CrmConnection) -> str:
    return str(
        await conn.scalar(
            text("SELECT status FROM workspace_integration_connection WHERE connection_id = :id"),
            {"id": connection.connection_id},
        )
    )


async def _reactivate(conn: Any, connection: CrmConnection) -> None:
    """The same connection row works again (Composio refreshed the connected account)."""
    await conn.execute(
        text(
            "UPDATE workspace_integration_connection SET status = 'active' "
            "WHERE connection_id = :id"
        ),
        {"id": connection.connection_id},
    )


def test_an_expired_connection_pauses_and_resumes(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        expired = ComposioError("connection_expired", 410, "Connected account expired")
        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "201": {"jobtitle": None}},
            failures={"HUBSPOT_UPDATE_CONTACTS": [expired]},
        )
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _title("201", "CFO")
        )

        result = await _handle(_handler(conn, tmp_path, gateway), connection)

        assert result.outcome == "crm_connection_expired" and not result.requeue
        assert await _connection_status(conn, connection) == "expired"
        assert await _proposal_status(conn, proposal_id) == "paused"
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == "succeeded"
        assert (logged["201"]["status"], logged["201"]["attempts"]) == ("queued", 0)
        assert await _wake_messages(conn, seeded.workspace_id) == [
            f"crm-writes-paused:{proposal_id}:1"
        ]
        # While the connection is expired its task sends nothing.
        assert (await _handle(_handler(conn, tmp_path, gateway), connection)).outcome == (
            "connection_not_active"
        )

        # The same connection works again: its task picks the paused proposal up, in order.
        await _reactivate(conn, connection)
        result = await _handle(_handler(conn, tmp_path, gateway), connection)

        assert result.outcome == "done"
        logged = await _writes(conn, proposal_id)
        assert logged["201"]["status"] == "succeeded"
        assert [slug for slug, _ in gateway.writes] == [
            "HUBSPOT_UPDATE_COMPANIES",
            "HUBSPOT_UPDATE_CONTACTS",
            "HUBSPOT_UPDATE_CONTACTS",
        ]
        assert await _proposal_status(conn, proposal_id) == "finished"
        assert await _wake_messages(conn, seeded.workspace_id) == [
            f"crm-writes-finished:{proposal_id}",
            f"crm-writes-paused:{proposal_id}:1",
        ]

    _run(tmp_path, "expired", body)


def test_a_connection_expired_before_the_batch_starts_pauses_and_wakes(tmp_path: Path) -> None:
    """Final review M-12: a queued proposal on a connection that expired before its task ran is
    paused and its chat woken once, as when the connection expires mid-batch."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={"101": {"icp_tier": None}})
        proposal_id = await _propose(conn, seeded, connection, gateway, _tier("101", "Tier 1"))
        await conn.execute(
            text(
                "UPDATE workspace_integration_connection SET status = 'expired' "
                "WHERE connection_id = :id"
            ),
            {"id": connection.connection_id},
        )

        for _ in range(2):  # a second run wakes nobody again
            result = await _handle(_handler(conn, tmp_path, gateway), connection)
            assert result.outcome == "connection_not_active" and not result.requeue

        assert await _proposal_status(conn, proposal_id) == "paused"
        assert gateway.calls == []
        key = f"crm-writes-paused:{proposal_id}:0"
        assert await _wake_messages(conn, seeded.workspace_id) == [key]
        message = await _wake_message(conn, tmp_path, key)
        assert "the HubSpot connection has expired or was revoked" in message

    _run(tmp_path, "expiredbefore", body)


def test_a_send_composio_refused_does_not_count_as_an_attempt(tmp_path: Path) -> None:
    """Final review M-9: a send Composio refused before reaching the CRM (its key or the connected
    account not accepted) pauses the proposal and leaves the change's attempts as they were."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}},
            failures={"HUBSPOT_UPDATE_COMPANIES": [ComposioError("auth", 401, "Invalid API key")]},
        )
        proposal_id = await _propose(conn, seeded, connection, gateway, _tier("101", "Tier 1"))

        result = await _handle(_handler(conn, tmp_path, gateway), connection)

        assert result.outcome == "crm_auth"
        assert await _proposal_status(conn, proposal_id) == "paused"
        change = (await _writes(conn, proposal_id))["101"]
        assert (change["status"], change["attempts"]) == ("queued", 0)

    _run(tmp_path, "authsend", body)


def test_a_paused_proposal_is_never_sent_on_a_different_connection(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        expired = ComposioError("connection_expired", 410, "Connected account expired")
        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "201": {"jobtitle": None}, "202": {}},
            failures={"HUBSPOT_UPDATE_CONTACTS": [expired]},
        )
        paused = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _title("201", "CFO")
        )
        queued = await _propose(conn, seeded, connection, gateway, _title("202", "CTO"))
        await _handle(_handler(conn, tmp_path, gateway), connection)
        assert await _proposal_status(conn, paused) == "paused"
        sent = len(gateway.writes)

        # The person connects again: a new connection row, maybe another portal. The connect
        # callback closes what the old connection had not sent.
        reconnected = await _reconnect(conn, seeded.workspace_id)
        artifacts = DurableAgentArtifactStore(
            storage=FsStorage(tmp_path / "wake-artifacts"), conn_factory=conn_session_factory(conn)
        )
        closed = await close_replaced_connection_proposals(
            conn,
            artifacts,
            workspace_id=seeded.workspace_id,
            active_connection_id=reconnected.connection_id,
        )
        assert set(closed) == {paused, queued}

        result = await _handle(_handler(conn, tmp_path, gateway), reconnected)

        assert result.references == {"proposals": 0}
        assert len(gateway.writes) == sent  # nothing was sent on the new connection
        for proposal_id, record in ((paused, "201"), (queued, "202")):
            assert await _proposal_status(conn, proposal_id) == "finished"
            change = (await _writes(conn, proposal_id))[record]
            assert change["status"] == "skipped"
            assert change["failure_kind"] == "connection_expired"
            assert change["crm_message"] == (
                "The CRM was reconnected or switched, so this was not sent; propose again."
            )
        assert (await _writes(conn, paused))["101"]["status"] == "succeeded"
        assert await _wake_messages(conn, seeded.workspace_id) == sorted(
            [
                f"crm-writes-finished:{paused}",
                f"crm-writes-finished:{queued}",
                f"crm-writes-paused:{paused}:1",
            ]
        )
        message = await _wake_message(conn, tmp_path, f"crm-writes-finished:{paused}")
        assert message == (
            "The CRM changes are finished: 1 done, 0 failed, 1 skipped — read the details with "
            f"crm_write_log(proposal_id={paused}). 1 were not sent (or not confirmed) because the "
            "CRM was reconnected or switched: they must be proposed again."
        )
        # Closing again finds nothing and wakes nobody twice.
        assert not await close_replaced_connection_proposals(
            conn,
            artifacts,
            workspace_id=seeded.workspace_id,
            active_connection_id=reconnected.connection_id,
        )

    _run(tmp_path, "switched", body)


def test_changes_the_crm_accepted_before_a_stop_keep_their_real_outcome(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        # The batch is refused whole, so each change is sent alone; the second meets the stop.
        expired = ComposioError("connection_expired", 410, "Connected account expired")
        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "102": {"icp_tier": None}},
            failures={"HUBSPOT_UPDATE_COMPANIES": [_INVALID_OPTION, None, expired]},
        )
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _tier("102", "Tier 2")
        )
        await _handle(_handler(conn, tmp_path, gateway), connection)

        logged = await _writes(conn, proposal_id)
        # 101 landed: it stays sent-awaiting-confirmation, never "already held, nothing sent".
        assert (logged["101"]["status"], logged["101"]["attempts"]) == ("sending", 1)
        assert (logged["102"]["status"], logged["102"]["attempts"]) == ("queued", 0)

        await _reactivate(conn, connection)
        await _handle(_handler(conn, tmp_path, gateway), connection)
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == logged["102"]["status"] == "succeeded"
        assert logged["101"]["attempts"] == 1  # not sent again

        # A rate limit instead: the change already accepted is read back at once.
        limited = ComposioError("rate_limited", 429, "Too many requests")
        gateway.records.update({"103": {"icp_tier": None}, "104": {"icp_tier": None}})
        later = await _propose(
            conn, seeded, connection, gateway, _tier("103", "Tier 1"), _tier("104", "Tier 2")
        )
        gateway.failures["HUBSPOT_UPDATE_COMPANIES"] = [_INVALID_OPTION, None, limited]
        result = await _handle(_handler(conn, tmp_path, gateway), connection)
        assert result.requeue
        logged = await _writes(conn, later)
        assert logged["103"]["status"] == "succeeded"
        assert (logged["104"]["status"], logged["104"]["attempts"]) == ("queued", 1)

    _run(tmp_path, "fallback", body)


def test_a_rate_limited_read_back_never_fails_a_change_the_crm_accepted(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        limited = ComposioError("rate_limited", 429, "Too many requests")
        gateway = _WritingCrm(records={"101": {"icp_tier": None}})
        proposal_id = await _propose(conn, seeded, connection, gateway, _tier("101", "Tier 1"))
        handler = _handler(conn, tmp_path, gateway, crm_write_max_attempts=2)
        gateway.failures["HUBSPOT_UPDATE_COMPANIES"] = [limited]
        await _handle(handler, connection)  # send 1 of 2 is rate limited

        # Send 2 — the last allowed — lands; the read-back right after is rate limited.
        gateway.failures[_BATCH_READ] = [None, limited]
        result = await _handle(handler, connection)

        assert result.requeue
        change = (await _writes(conn, proposal_id))["101"]
        assert (change["status"], change["attempts"], change["failure_kind"]) == (
            "sending",
            2,
            None,
        )
        assert gateway.records["101"]["icp_tier"] == "Tier 1"

        # The next run confirms it by reading, and sends nothing.
        await _handle(handler, connection)
        change = (await _writes(conn, proposal_id))["101"]
        assert (change["status"], change["attempts"]) == ("succeeded", 2)
        assert len(gateway.writes) == 2

        # A create whose only allowed send lands and whose read-back is rate limited: its id and
        # its "Clue created it" link are kept at once, and the next run confirms it.
        created = await _propose(conn, seeded, connection, gateway, _create("ana@new.co"))
        gateway.failures["HUBSPOT_READ_CRM_OBJECT_BY_ID"] = [limited]
        once = _handler(conn, tmp_path, gateway, crm_write_max_attempts=1)
        assert (await _handle(once, connection)).requeue
        change = await _created(conn, created)
        assert (change["status"], change["crm_id"]) == ("sending", "501")
        linked = await conn.scalar(
            text(
                "SELECT created_by_clue FROM crm_record_link WHERE connection_id = :c "
                "AND crm_id = '501' AND created_by_write_id = :w"
            ),
            {"c": connection.connection_id, "w": change["write_id"]},
        )
        assert linked is True
        await _handle(once, connection)
        assert (await _created(conn, created))["status"] == "succeeded"
        assert [slug for slug, _ in gateway.writes].count("HUBSPOT_CREATE_CONTACT") == 1

    _run(tmp_path, "readback", body)


def test_a_rate_limited_read_counts_as_an_attempt(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={"101": {"icp_tier": None}})
        proposal_id = await _propose(conn, seeded, connection, gateway, _tier("101", "Tier 1"))
        limited = ComposioError("rate_limited", 429, "Too many requests")
        gateway.failures[_BATCH_READ] = [limited, limited, limited]
        handler = _handler(conn, tmp_path, gateway, crm_write_max_attempts=3)

        first = await _handle(handler, connection)
        second = await _handle(handler, connection)
        assert (first.requeue_after, second.requeue_after) == (
            timedelta(seconds=30),
            timedelta(seconds=60),
        )
        third = await _handle(handler, connection)

        assert not third.requeue
        change = (await _writes(conn, proposal_id))["101"]
        assert (change["status"], change["failure_kind"], change["retryable"]) == (
            "failed",
            "rate_limited",
            True,
        )
        assert change["attempts"] == 3
        assert gateway.writes == []
        assert await _proposal_status(conn, proposal_id) == "finished"

    _run(tmp_path, "readlimit", body)


def test_a_confirming_read_that_keeps_failing_settles_the_change(tmp_path: Path) -> None:
    """Final review I-2: a change sent but never confirmed counts each stopped confirming read as
    an attempt, backs off, and at the cap is failed (retryable) so the proposal finishes and wakes
    its chat — it never spins as "sending" for ever."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        limited = ComposioError("rate_limited", 429, "Too many requests")
        gateway = _WritingCrm(records={"101": {"icp_tier": None}})
        proposal_id = await _propose(conn, seeded, connection, gateway, _tier("101", "Tier 1"))
        handler = _handler(conn, tmp_path, gateway, crm_write_max_attempts=3)
        # The check before sending passes, the send lands, every read after it is limited.
        gateway.failures[_BATCH_READ] = [None, limited, limited, limited]

        first = await _handle(handler, connection)
        assert first.requeue and first.requeue_after == timedelta(seconds=30)
        change = (await _writes(conn, proposal_id))["101"]
        assert (change["status"], change["attempts"]) == ("sending", 1)

        second = await _handle(handler, connection)
        assert second.requeue and second.requeue_after == timedelta(seconds=60)
        change = (await _writes(conn, proposal_id))["101"]
        assert (change["status"], change["attempts"]) == ("sending", 2)

        third = await _handle(handler, connection)
        assert not third.requeue
        change = (await _writes(conn, proposal_id))["101"]
        assert (change["status"], change["failure_kind"], change["retryable"]) == (
            "failed",
            "other",
            True,
        )
        assert change["crm_message"] == "Sent; Clue could not confirm it — check the CRM"
        assert len(gateway.writes) == 1  # never sent again
        assert await _proposal_status(conn, proposal_id) == "finished"
        assert await _wake_messages(conn, seeded.workspace_id) == [
            f"crm-writes-finished:{proposal_id}"
        ]

    _run(tmp_path, "confirmfail", body)


def test_hubspot_company_reads_are_batched(tmp_path: Path) -> None:
    """Final review I-3: the check before sending and the read-back read 100 companies a call."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        ids = [str(1000 + n) for n in range(150)]
        gateway = _WritingCrm(records={rid: {"icp_tier": None} for rid in ids})
        proposal_id = await _propose(
            conn, seeded, connection, gateway, *[_tier(rid, "Tier 1") for rid in ids]
        )

        assert (await _handle(_handler(conn, tmp_path, gateway), connection)).outcome == "done"

        logged = await _writes(conn, proposal_id)
        assert {change["status"] for change in logged.values()} == {"succeeded"}
        reads = [args for slug, args in gateway.calls if slug == _BATCH_READ]
        # Per chunk of the batch write: its check, its send, its read-back.
        assert [len(args["inputs"]) for args in reads] == [100, 100, 50, 50]
        assert not [slug for slug, _ in gateway.calls if slug == "HUBSPOT_READ_CRM_OBJECT_BY_ID"]
        assert [len(args["inputs"]) for _, args in gateway.writes] == [100, 50]

    _run(tmp_path, "batchread", body)


def test_a_refused_connection_pauses_and_a_missing_record_fails_alone(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={"101": {"icp_tier": None}, "102": {"icp_tier": None}})
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _tier("102", "Tier 2")
        )
        # Clue's Composio key is refused (401): nothing fails for good, the proposal pauses.
        gateway.failures[_BATCH_READ] = [ComposioError("auth", 401, "Invalid API key")]
        result = await _handle(_handler(conn, tmp_path, gateway), connection)

        assert result.outcome == "crm_auth" and not result.requeue
        assert await _proposal_status(conn, proposal_id) == "paused"
        assert {c["status"] for c in (await _writes(conn, proposal_id)).values()} == {"queued"}
        assert await _connection_status(conn, connection) == "active"
        assert await _wake_messages(conn, seeded.workspace_id) == [
            f"crm-writes-paused:{proposal_id}:0"
        ]

        # The key works again; meanwhile record 102 was deleted in the CRM (its read is a 404).
        del gateway.records["102"]
        await _handle(_handler(conn, tmp_path, gateway), connection)

        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == "succeeded"
        assert (logged["102"]["status"], logged["102"]["failure_kind"]) == ("failed", "not_found")
        assert await _proposal_status(conn, proposal_id) == "finished"

    _run(tmp_path, "auth", body)


def test_a_change_no_longer_allowed_fails_alone(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={"101": {"icp_tier": None}, "102": {"icp_tier": None}})
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _tier("102", "Tier 2")
        )
        gateway.records["201"] = {"jobtitle": None}
        later = await _propose(conn, seeded, connection, gateway, _title("201", "CFO"))
        # The allowlist changed between the card and the send.
        await conn.execute(
            text(
                "UPDATE crm_write SET slug = 'HUBSPOT_MERGE_COMPANIES' "
                "WHERE proposal_id = :id AND record_ref = '102'"
            ),
            {"id": proposal_id},
        )

        result = await _handle(_handler(conn, tmp_path, gateway), connection)

        assert result.outcome == "done"
        logged = await _writes(conn, proposal_id)
        assert logged["101"]["status"] == "succeeded"
        assert (logged["102"]["status"], logged["102"]["failure_kind"]) == ("failed", "other")
        assert logged["102"]["crm_message"] == (
            "This action is no longer allowed, so it was not sent."
        )
        assert (await _writes(conn, later))["201"]["status"] == "succeeded"
        assert await _proposal_status(conn, proposal_id) == "finished"

    _run(tmp_path, "disallowed", body)


def _create(email: str) -> ProposedChange:
    return ProposedChange(
        slug="HUBSPOT_CREATE_CONTACT",
        arguments={"email": email, "firstname": "Ana"},
        reason="A buying-committee member Clue found.",
    )


async def _created(conn: Any, proposal_id: UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                "SELECT status, failure_kind, crm_message, crm_id, attempts, write_id "
                "FROM crm_write WHERE proposal_id = :id"
            ),
            {"id": proposal_id},
        )
    ).one()
    return dict(row._mapping)


def test_a_create_stores_its_id_and_is_linked_as_created_by_clue(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={})
        proposal_id = await _propose(conn, seeded, connection, gateway, _create("ana@new.co"))

        await _handle(_handler(conn, tmp_path, gateway), connection)

        change = await _created(conn, proposal_id)
        assert (change["status"], change["crm_id"]) == ("succeeded", "500")
        assert gateway.records["500"]["email"] == "ana@new.co"
        link = (
            await conn.execute(
                text(
                    "SELECT crm_object, created_by_clue, created_by_write_id FROM crm_record_link "
                    "WHERE connection_id = :c AND crm_id = '500'"
                ),
                {"c": connection.connection_id},
            )
        ).one()
        assert (link.crm_object, link.created_by_clue) == ("contact", True)
        assert link.created_by_write_id == change["write_id"]
        # The create was looked for first (R-7.1), then read back by the id the CRM gave.
        assert [slug for slug, _ in gateway.calls] == [
            "HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA",
            "HUBSPOT_CREATE_CONTACT",
            "HUBSPOT_READ_CRM_OBJECT_BY_ID",
        ]
        # The write log names the new record, so the agent can tell the person its id (L9).
        logged = (
            await _log_tool(conn).invoke(
                CrmWriteLogInput(proposal_id=proposal_id), _ctx(conn, seeded.workspace_id)
            )
        ).references["writes"]
        assert [(w["status"], w["record_ref"]) for w in logged] == [("succeeded", "500")]
        # And so does the wake message.
        message = await _wake_message(conn, tmp_path, f"crm-writes-finished:{proposal_id}")
        assert f"Created {logged[0]['record_label']} (500)." in message

    _run(tmp_path, "create", body)


def test_a_salesforce_account_made_since_the_card_is_not_created_again(tmp_path: Path) -> None:
    """Final review I-5: the re-check before sending matches the website's host too."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={})
        proposal_id = await _propose(
            conn,
            seeded,
            connection,
            gateway,
            ProposedChange(
                "SALESFORCE_CREATE_ACCOUNT", {"name": "Acme", "website": "acme.com"}, "x"
            ),
        )
        # Someone made the account meanwhile, with the website spelled another way.
        gateway.records["001A"] = {"Name": "Acme", "Website": "https://www.acme.com/"}

        await _handle(_handler(conn, tmp_path, gateway), connection)

        (change,) = (await _writes(conn, proposal_id)).values()
        assert (change["status"], change["failure_kind"]) == ("skipped", "conflict")
        assert "001A" in change["crm_message"]
        assert gateway.writes == []

    _run(tmp_path, "sfcreate", body, provider="salesforce")


def test_a_refused_create_shows_the_crm_message_and_keeps_its_answer(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        refusal = ExecuteResult(
            False, {"http_error": "400", "status_code": 400}, _HUBSPOT_INVALID_EMAIL
        )
        gateway = _WritingCrm(records={}, failures={"HUBSPOT_CREATE_CONTACT": [refusal]})
        proposal_id = await _propose(conn, seeded, connection, gateway, _create("ana@new.test"))

        await _handle(_handler(conn, tmp_path, gateway), connection)

        row = (
            await conn.execute(
                text(
                    "SELECT status, crm_message, crm_response, record_ref, crm_id "
                    "FROM crm_write WHERE proposal_id = :id"
                ),
                {"id": proposal_id},
            )
        ).one()
        assert row.status == "failed"
        assert row.crm_message == "Email address ana@new.test is invalid"
        assert row.crm_response == json.loads(_HUBSPOT_INVALID_EMAIL)
        # Nothing was created, so the write names no record.
        assert (row.record_ref, row.crm_id) == (None, None)
        logged = (
            await _log_tool(conn).invoke(
                CrmWriteLogInput(proposal_id=proposal_id), _ctx(conn, seeded.workspace_id)
            )
        ).references["writes"]
        assert [(w["status"], w["record_ref"]) for w in logged] == [("failed", None)]
        message = await _wake_message(conn, tmp_path, f"crm-writes-finished:{proposal_id}")
        assert "Created" not in message

    _run(tmp_path, "createrefused", body)


def test_a_create_is_never_made_twice(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        # The worker dies right after the CRM created the contact, before its id was stored.
        gateway = _WritingCrm(records={}, failures={"HUBSPOT_CREATE_CONTACT": ["crash"]})
        crashed = await _propose(conn, seeded, connection, gateway, _create("ana@new.co"))
        with pytest.raises(RuntimeError):
            await _handle(_handler(conn, tmp_path, gateway), connection)
        await _handle(_handler(conn, tmp_path, gateway), connection)

        change = await _created(conn, crashed)
        assert (change["status"], change["failure_kind"]) == ("skipped", "conflict")
        assert "(500)" in change["crm_message"]
        # Someone created the record between the card and the send: it is not created again.
        racing = await _propose(conn, seeded, connection, gateway, _create("bo@new.co"))
        gateway.records["777"] = {"email": "bo@new.co"}
        await _handle(_handler(conn, tmp_path, gateway), connection)
        change = await _created(conn, racing)
        assert (change["status"], change["failure_kind"]) == ("skipped", "conflict")
        assert "(777)" in change["crm_message"]
        assert [slug for slug, _ in gateway.writes] == ["HUBSPOT_CREATE_CONTACT"]

    _run(tmp_path, "createonce", body)


def test_a_finished_proposal_wakes_its_chat_once(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={"101": {"icp_tier": None}, "102": {"icp_tier": None}})
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _tier("102", "Tier 2")
        )
        gateway.records["102"]["icp_tier"] = "Tier 3"
        handler = _handler(conn, tmp_path, gateway)

        await _handle(handler, connection)
        await _handle(handler, connection)
        proposal = await writes.get_proposal(conn, proposal_id=proposal_id)
        assert proposal is not None
        again = await queue_crm_writes_finished_turn(
            conn,
            DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "wake-artifacts"),
                conn_factory=conn_session_factory(conn),
            ),
            proposal=proposal,
        )

        assert again is None
        rows = (
            await conn.execute(
                text(
                    "SELECT thread_id, derived_from_turn_id, message_artifact_key "
                    "FROM agent_turn_submission WHERE workspace_id = :ws AND derivation = :d"
                ),
                {"ws": seeded.workspace_id, "d": DERIVATION_CRM_WRITES_FINISHED},
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].thread_id == seeded.thread_id
        assert rows[0].derived_from_turn_id == seeded.turn_id
        message = (
            await FsStorage(tmp_path / "wake-artifacts").get(rows[0].message_artifact_key)
        ).decode()
        assert message == (
            "The CRM changes are finished: 1 done, 0 failed, 1 skipped — read the details with "
            f"crm_write_log(proposal_id={proposal_id})."
        )

    _run(tmp_path, "wake", body)


def test_a_reported_success_that_did_not_land_is_not_applied(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        # HubSpot answers success for a property it silently does not write.
        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "102": {"icp_tier": None}},
            ignored=frozenset({"icp_tier"}),
        )
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _tier("101", "Tier 1"), _tier("102", "Tier 2")
        )

        await _handle(_handler(conn, tmp_path, gateway), connection)

        logged = await _writes(conn, proposal_id)
        for record in ("101", "102"):
            assert logged[record]["status"] == "failed"
            assert logged[record]["failure_kind"] == "not_applied"
            assert logged[record]["crm_message"] == (
                "The CRM reported success but the value did not change."
            )
        assert len(gateway.writes) == 1

    _run(tmp_path, "notapplied", body)


def test_a_proposal_queued_during_the_run_is_not_lost(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        later: list[UUID] = []

        async def on_write(slug: str, arguments: dict[str, Any]) -> None:
            del arguments
            if slug == "HUBSPOT_UPDATE_COMPANIES" and not later:
                # Another chat's changes are queued while this run is sending (its offer meets
                # this task still claimed).
                later.append(
                    await _propose(conn, seeded, connection, gateway, _title("201", "CFO"))
                )

        gateway = _WritingCrm(
            records={"101": {"icp_tier": None}, "201": {"jobtitle": None}}, on_write=on_write
        )
        first = await _propose(conn, seeded, connection, gateway, _tier("101", "Tier 1"))

        result = await _handle(_handler(conn, tmp_path, gateway), connection)

        assert result.outcome == "done" and result.references == {"proposals": 2}
        assert await _proposal_status(conn, first) == "finished"
        assert await _proposal_status(conn, later[0]) == "finished"
        assert [slug for slug, _ in gateway.writes] == [
            "HUBSPOT_UPDATE_COMPANIES",
            "HUBSPOT_UPDATE_CONTACTS",
        ]

    _run(tmp_path, "notlost", body)


def test_list_membership_links_follow_adds_and_removals(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        await store_list(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            provider="hubspot",
            crm_object="contact",
            crm_list_id="77",
            name="Q4 committee",
            kind="hubspot_list",
            created_by_clue=True,
            created_by_write_id=None,
            project_id=seeded.project_id,
        )
        gateway = _WritingCrm(lists={"201": []})
        add = ProposedChange(
            slug="HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
            arguments={"list_id": "77", "operation": "add", "record_ids": ["201"]},
            reason="Add to the campaign list.",
        )
        await _propose(conn, seeded, connection, gateway, add)
        handler = _handler(conn, tmp_path, gateway)
        await _handle(handler, connection)
        assert gateway.lists["201"] == ["77"]
        added = await writes.clue_added_members(
            conn, connection_id=connection.connection_id, pairs=[("77", "201")]
        )
        assert added == {("77", "201")}

        remove = ProposedChange(
            slug="HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
            arguments={"list_id": "77", "operation": "remove", "record_ids": ["201"]},
            reason="Take them off the list.",
        )
        await _propose(conn, seeded, connection, gateway, remove)
        await _handle(handler, connection)
        assert gateway.lists["201"] == []
        assert not await writes.clue_added_members(
            conn, connection_id=connection.connection_id, pairs=[("77", "201")]
        )

    _run(tmp_path, "lists", body)


def _industry(record: str, industry: str) -> ProposedChange:
    return ProposedChange(
        slug="SALESFORCE_UPDATE_ACCOUNT",
        arguments={"account_id": record, "industry": industry},
        reason="The industry Clue found.",
    )


class _ExhaustedBudget:
    async def take_call(self, conn: Any, *, connection: CrmConnection, today: Any) -> None:
        del conn, connection, today
        raise CrmBudgetExhausted(
            "salesforce_api_share_exhausted",
            "Clue has used its share of this Salesforce org's daily API calls.",
        )


def test_salesforce_hidden_failures_fail_and_every_call_takes_the_budget(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(records={"001A": {"Industry": None}, "001B": {"Industry": None}})
        gateway.refused_records.add("001B")
        proposal_id = await _propose(
            conn,
            seeded,
            connection,
            gateway,
            _industry("001A", "Retail"),
            _industry("001B", "Retail"),
        )
        budget = _FakeBudget(gateway)

        await _handle(_handler(conn, tmp_path, gateway, budget=budget), connection)

        logged = await _writes(conn, proposal_id)
        assert logged["001A"]["status"] == "succeeded"
        assert logged["001B"]["status"] == "failed"
        assert logged["001B"]["failure_kind"] == "validation_rule"
        assert logged["001B"]["crm_message"] == (
            "Tier accounts need an owner. (FIELD_CUSTOM_VALIDATION_EXCEPTION)"
        )
        assert logged["001B"]["crm_response"][0]["statusCode"] == (
            "FIELD_CUSTOM_VALIDATION_EXCEPTION"
        )
        # One composite call carried both; the read before and the read back were batched too,
        # and each of the three calls was taken from the budget before it was made.
        assert [slug for slug, _ in gateway.calls] == [
            "SALESFORCE_RUN_SOQL_QUERY",
            "SALESFORCE_PATCH_COMPOSITE_SOBJECTS",
            "SALESFORCE_RUN_SOQL_QUERY",
        ]
        assert budget.taken_at == [0, 1, 2]

        # The org's allowance runs out: the next proposal pauses without touching the connection
        # and the task comes back the next day.
        gateway.records["001C"] = {"Industry": None}
        paused = await _propose(conn, seeded, connection, gateway, _industry("001C", "Retail"))
        result = await _handle(
            _handler(conn, tmp_path, gateway, budget=_ExhaustedBudget()), connection
        )
        assert result.outcome == "crm_budget" and result.requeue
        assert result.requeue_after is not None
        assert timedelta(0) < result.requeue_after <= timedelta(days=1, minutes=1)
        assert await _proposal_status(conn, paused) == "paused"
        assert (await _writes(conn, paused))["001C"]["status"] == "queued"
        status = await conn.scalar(
            text("SELECT status FROM workspace_integration_connection WHERE connection_id = :id"),
            {"id": connection.connection_id},
        )
        assert status == "active"
        assert f"crm-writes-paused:{paused}:0" in await _wake_messages(conn, seeded.workspace_id)

    _run(tmp_path, "salesforce", body, provider="salesforce")


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ('[{"errorCode":"FIELD_CUSTOM_VALIDATION_EXCEPTION","message":"Tier needed"}]', "validation_rule"),  # noqa: E501
        ('{"statusCode": "REQUIRED_FIELD_MISSING", "message": "Required fields are missing: [Name]"}', "required_field"),  # noqa: E501
        ('[{"errorCode":"DUPLICATES_DETECTED","message":"Use one of these records?"}]', "duplicate_rule"),  # noqa: E501
        (_HUBSPOT_DUPLICATE, "duplicate_rule"),
        ('{"output":{"fieldErrors":{"Name":[{"duplicateRecordError":{"matchResults":[]}}]}}}', "duplicate_rule"),  # noqa: E501
        ('[{"message":"insufficient access rights on cross-reference id: 701000000000000","errorCode":"INSUFFICIENT_ACCESS_ON_CROSS_REFERENCE_ENTITY","fields":[]}]', "permission"),  # noqa: E501
        ('"errorCode":"INVALID_FIELD_FOR_INSERT_UPDATE","field":"CreatedDate"', "permission"),
        ('{"status":"error","message":"List does not exist with ID 999999999.","category":"OBJECT_NOT_FOUND"}', "not_found"),  # noqa: E501
        ('{"fieldErrors":{"BillingAddress":[{"duplicateRecordError":null,"errorCode":"INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST"}]}}', "other"),  # noqa: E501
        ("Invalid request data provided\n- Following fields are missing: {'account_id'}", "other"),
        (None, "other"),
    ],
)  # fmt: skip
def test_failure_kinds_come_from_the_crm_error_code(message: str | None, kind: str) -> None:
    assert failure_kind(message) == kind


#: The live check's two refusals (2026-10-22): HubSpot's invalid email, Salesforce's bad number.
_HUBSPOT_INVALID_EMAIL = (
    '{"status":"error","message":"Property values were not valid: [{\\"isValid\\":false,'
    '\\"message\\":\\"Email address ana@new.test is invalid\\",\\"error\\":'
    '\\"INVALID_EMAIL\\",\\"name\\":\\"email\\"}]","correlationId":"c1",'
    '"errors":[{"message":"Email address ana@new.test is invalid","code":"INVALID_EMAIL",'
    '"context":{"propertyName":["email"]}}],"category":"VALIDATION_ERROR"}'
)
_SALESFORCE_JSON_PARSER = (
    '[{"fields": [], "message": "Cannot deserialize instance of int from VALUE_STRING value '
    'about fifty or request may be missing a required field at [line:1, column:42]", '
    '"statusCode": "JSON_PARSER_ERROR"}]'
)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (_HUBSPOT_INVALID_EMAIL, "Email address ana@new.test is invalid"),
        (
            '{"status":"error","message":"List does not exist with ID 9.","category":"OBJECT_NOT_FOUND"}',  # noqa: E501
            "List does not exist with ID 9.",
        ),
        (
            '{"status":"error","message":"Two were wrong","errors":[{"message":"First is bad"},{"message":"Second is bad"}]}',  # noqa: E501
            "First is bad; Second is bad",
        ),
        (
            _SALESFORCE_JSON_PARSER,
            "Cannot deserialize instance of int from VALUE_STRING value about fifty or request "
            "may be missing a required field at [line:1, column:42] (JSON_PARSER_ERROR)",
        ),
        (
            '[{"errorCode":"FIELD_CUSTOM_VALIDATION_EXCEPTION","message":"Industry is required when Type is Customer"},{"errorCode":"REQUIRED_FIELD_MISSING","message":"Required fields are missing: [Name]"}]',  # noqa: E501
            "Industry is required when Type is Customer (FIELD_CUSTOM_VALIDATION_EXCEPTION); "
            "Required fields are missing: [Name] (REQUIRED_FIELD_MISSING)",
        ),
    ],
)
def test_the_crm_message_is_its_text_and_the_body_is_kept(body: str, message: str) -> None:
    assert crm_reply(body) == (message, json.loads(body))


def test_an_unreadable_crm_answer_is_shown_as_it_came() -> None:
    plain = "Invalid request data provided\n- Following fields are missing: {'account_id'}"
    # Short text is the message itself; nothing more to keep.
    assert crm_reply(plain) == (plain, None)
    # A long one is cut for the card; the whole answer is kept.
    long = "x" * 600
    assert crm_reply(long) == ("x" * 500, long)
    # JSON with no message in it: the body as it came, kept whole.
    shapeless = '{"output":{"fieldErrors":{"Name":[{"duplicateRecordError":{"matchResults":[]}}]}}}'
    assert crm_reply(shapeless) == (shapeless, json.loads(shapeless))
    # Clue's own sentences pass through untouched.
    assert crm_reply("Refused.") == ("Refused.", None)


# --- Phase 3: lists and campaigns Clue creates, and lists deleted in the CRM (Task 3) ---------


def _create_list(name: str) -> ProposedChange:
    return ProposedChange(
        slug="HUBSPOT_CREATE_LIST",
        arguments={"name": name, "object_type_id": "0-2", "processing_type": "MANUAL"},
        reason="The project's target accounts.",
    )


def test_a_created_list_is_stored_for_the_project(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm()
        proposal_id = await _propose(conn, seeded, connection, gateway, _create_list("Clue: Q4"))

        await _handle(_handler(conn, tmp_path, gateway), connection)

        change = await _created(conn, proposal_id)
        assert (change["status"], change["crm_id"]) == ("succeeded", "17")
        # Looked for by name first, created, then read back by the id HubSpot gave it.
        assert [slug for slug, _ in gateway.calls] == [
            "HUBSPOT_GET_CRM_LIST_BY_NAME",
            "HUBSPOT_CREATE_LIST",
            "HUBSPOT_SEARCH_CRM_LISTS",
        ]
        assert gateway.calls[-1][1]["listIds"] == ["17"]
        (kept,) = await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        )
        assert (kept.crm_list_id, kept.name, kept.crm_object, kept.kind) == (
            "17",
            "Clue: Q4",
            "company",
            "hubspot_list",
        )
        assert kept.created_by_clue and kept.created_by_write_id == change["write_id"]
        # A list is not a CRM record: no record link names it.
        links = await conn.scalar(
            text("SELECT count(*) FROM crm_record_link WHERE connection_id = :c AND crm_id = '17'"),
            {"c": connection.connection_id},
        )
        assert links == 0
        # The wake names the new list and its id, so the agent can add to it.
        message = await _wake_message(conn, tmp_path, f"crm-writes-finished:{proposal_id}")
        assert "Created Clue: Q4 (17)." in message

    _run(tmp_path, "listmade", body)


def test_a_created_campaign_is_stored_for_the_project(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm()
        proposal_id = await _propose(
            conn,
            seeded,
            connection,
            gateway,
            ProposedChange("SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q4"}, "committee"),
        )

        await _handle(_handler(conn, tmp_path, gateway), connection)

        change = await _created(conn, proposal_id)
        assert (change["status"], change["crm_id"]) == ("succeeded", "701jV00000Hd83x000")
        (kept,) = await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        )
        assert (kept.crm_list_id, kept.crm_object, kept.kind) == (
            "701jV00000Hd83x000",
            "contact",
            "salesforce_campaign",
        )

    _run(tmp_path, "campaignmade", body, provider="salesforce")


def test_a_list_made_since_the_card_is_not_created_again(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm()
        proposal_id = await _propose(conn, seeded, connection, gateway, _create_list("Clue: Q4"))
        gateway.crm_lists["Clue: Q4"] = "40"  # someone made it by hand meanwhile

        await _handle(_handler(conn, tmp_path, gateway), connection)

        change = await _created(conn, proposal_id)
        assert (change["status"], change["failure_kind"]) == ("skipped", "conflict")
        assert "40" in change["crm_message"]
        assert gateway.writes == []
        # Clue does not adopt a list it did not make: the person links it if they want it.
        assert not await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        )

    _run(tmp_path, "listmadeby", body)


def test_a_deleted_list_is_marked_gone_and_the_change_fails(tmp_path: Path) -> None:
    """Review Focus 3: the stored list was deleted in HubSpot."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        await store_list(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            provider="hubspot",
            crm_object="company",
            crm_list_id="17",
            name="Clue: Q4",
            kind="hubspot_list",
            created_by_clue=True,
            created_by_write_id=None,
            project_id=seeded.project_id,
        )
        gateway = _WritingCrm(
            lists={"101": [], "102": []},
            failures={"HUBSPOT_UPDATE_LIST_MEMBERSHIPS": [_LIST_GONE]},
        )
        add = [
            ProposedChange(
                "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
                {"list_id": "17", "operation": "add", "record_ids": [record]},
                "Target accounts.",
            )
            for record in ("101", "102")
        ]
        proposal_id = await _propose(conn, seeded, connection, gateway, *add)

        await _handle(_handler(conn, tmp_path, gateway), connection)

        changes = await _writes(conn, proposal_id)
        for record in ("101", "102"):
            assert changes[record]["status"] == "failed"
            assert changes[record]["failure_kind"] == "other"
            assert changes[record]["retryable"] is False
            assert changes[record]["crm_message"] == (
                "The list no longer exists in HubSpot; find it by name or create it again."
            )
            assert changes[record]["crm_response"] == json.loads(_LIST_GONE_BODY)
        # One call found it gone: the changes are not sent one by one after it.
        assert len(gateway.writes) == 1
        # The kept list is gone, so it is no longer offered for the project.
        assert not await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        )
        gone = await conn.scalar(
            text("SELECT gone_at IS NOT NULL FROM crm_list WHERE crm_list_id = '17'")
        )
        assert gone is True

    _run(tmp_path, "listgone", body)


MARKETING_USER = "Your Salesforce user needs the Marketing User permission to create campaigns."


def test_a_campaign_create_by_a_user_who_is_not_a_marketing_user_says_so(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        refusal = ExecuteResult(
            False, {"http_error": "400", "status_code": 400}, _NOT_A_MARKETING_USER
        )
        gateway = _WritingCrm(failures={"SALESFORCE_CREATE_CAMPAIGN": [refusal]})
        proposal_id = await _propose(
            conn,
            seeded,
            connection,
            gateway,
            ProposedChange("SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q4"}, "committee"),
        )

        await _handle(_handler(conn, tmp_path, gateway), connection)

        (change,) = (await _writes(conn, proposal_id)).values()
        assert change["status"] == "failed"
        assert change["crm_message"] == MARKETING_USER
        assert change["failure_kind"] == "permission"
        assert change["crm_response"] == json.loads(_NOT_A_MARKETING_USER)
        assert not await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        )

    _run(tmp_path, "marketinguser", body, provider="salesforce")


def test_the_marketing_user_refusal_is_shown_in_plain_words() -> None:
    assert crm_reply(_NOT_A_MARKETING_USER) == (MARKETING_USER, json.loads(_NOT_A_MARKETING_USER))
    assert failure_kind(_NOT_A_MARKETING_USER) == "permission"
    # The same code for another object is not a campaign permission.
    other = '[{"message":"entity type cannot be inserted: Lead","errorCode":"CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY"}]'  # noqa: E501
    assert crm_reply(other)[0] == (
        "entity type cannot be inserted: Lead (CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY)"
    )


def test_a_list_renamed_after_its_create_is_still_confirmed_by_its_id(tmp_path: Path) -> None:
    """Review #4: once HubSpot named the list's id, the read-back goes by the id."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm()
        proposal_id = await _propose(conn, seeded, connection, gateway, _create_list("Clue: Q4"))
        original = gateway._write

        def write_then_rename(slug: str, arguments: Mapping[str, Any]) -> Any:
            answer = original(slug, arguments)
            if slug == "HUBSPOT_CREATE_LIST":  # someone renames it as soon as it exists
                gateway.crm_lists["Clue: Q4 (renamed)"] = gateway.crm_lists.pop("Clue: Q4")
            return answer

        gateway._write = write_then_rename  # type: ignore[method-assign]

        await _handle(_handler(conn, tmp_path, gateway), connection)

        change = await _created(conn, proposal_id)
        assert (change["status"], change["crm_id"]) == ("succeeded", "17")

    _run(tmp_path, "listrenamed", body)


@pytest.mark.parametrize("provider", ["hubspot", "salesforce"])
def test_a_list_the_crm_made_before_a_crash_is_kept_and_not_made_again(
    tmp_path: Path, provider: str
) -> None:
    """Review #3: the worker dies after the CRM made the list, before Clue kept its id."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        slug = "HUBSPOT_CREATE_LIST" if provider == "hubspot" else "SALESFORCE_CREATE_CAMPAIGN"
        change = (
            _create_list("Clue: Q4")
            if provider == "hubspot"
            else ProposedChange(slug, {"name": "Clue: Q4"}, "committee")
        )
        gateway = _WritingCrm(failures={slug: ["crash"]})
        proposal_id = await _propose(conn, seeded, connection, gateway, change)
        handler = _handler(conn, tmp_path, gateway)
        with pytest.raises(RuntimeError):
            await _handle(handler, connection)
        sent = await _created(conn, proposal_id)
        assert (sent["status"], sent["crm_id"], sent["attempts"]) == ("sending", None, 1)

        await _handle(handler, connection)

        made = gateway.crm_lists["Clue: Q4"]
        settled = await _created(conn, proposal_id)
        assert (settled["status"], settled["crm_id"]) == ("succeeded", made)
        assert [s for s, _ in gateway.writes] == [slug]  # never made twice
        (kept,) = await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        )
        assert (kept.crm_list_id, kept.name, kept.created_by_clue) == (made, "Clue: Q4", True)
        assert kept.created_by_write_id == settled["write_id"]

    _run(tmp_path, f"listcrash{provider[:2]}", body, provider=provider)


def test_a_list_named_differently_in_case_is_not_taken_for_clues_own(tmp_path: Path) -> None:
    """After a crash, only a list of exactly the name Clue sent is taken as the one it made."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm()
        proposal_id = await _propose(conn, seeded, connection, gateway, _create_list("Clue: Q4"))
        # As a run that died after sending leaves it.
        await conn.execute(
            text("UPDATE crm_write SET status = 'sending', attempts = 1 WHERE proposal_id = :p"),
            {"p": proposal_id},
        )
        gateway.crm_lists["clue: q4"] = "40"  # a person's list, HubSpot matches it by name

        await _handle(_handler(conn, tmp_path, gateway), connection)

        change = await _created(conn, proposal_id)
        assert (change["status"], change["failure_kind"]) == ("skipped", "conflict")
        assert not await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        )

    _run(tmp_path, "listcase", body)


# --- Task 3b (R-12.7): a new list and its first members, sent in order ------------------------


NOT_CREATED = "The list was not created, so nothing was added to it."


def _add_to_new(record: str, name: str = "Clue: Q4") -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        {"list_id": f"new:{name}", "operation": "add", "record_ids": [record]},
        "Target accounts.",
    )


async def _arguments(conn: Any, proposal_id: UUID) -> dict[str | None, dict[str, Any]]:
    rows = await conn.execute(
        text("SELECT record_ref, arguments FROM crm_write WHERE proposal_id = :id"),
        {"id": proposal_id},
    )
    return {row.record_ref: row.arguments for row in rows}


def test_a_new_list_is_created_then_its_members_are_added_with_its_id(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(lists={"101": [], "102": []})
        proposal_id = await _propose(
            conn,
            seeded,
            connection,
            gateway,
            _add_to_new("101"),
            _create_list("Clue: Q4"),
            _add_to_new("102"),
        )

        await _handle(_handler(conn, tmp_path, gateway), connection)

        assert [slug for slug, _ in gateway.writes] == [
            "HUBSPOT_CREATE_LIST",
            "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        ]
        assert gateway.writes[1][1]["list_id"] == "17"
        assert gateway.lists == {"101": ["17"], "102": ["17"]}
        logged = await _writes(conn, proposal_id)
        assert {ref: row["status"] for ref, row in logged.items()} == {
            "17": "succeeded",
            "101": "succeeded",
            "102": "succeeded",
        }
        # The new id is kept on the adds, so a later run never sends the placeholder.
        arguments = await _arguments(conn, proposal_id)
        assert arguments["101"]["list_id"] == arguments["102"]["list_id"] == "17"
        added = await writes.clue_added_members(
            conn,
            connection_id=connection.connection_id,
            pairs=[("17", "101"), ("17", "102")],
            project_id=seeded.project_id,
        )
        assert added == {("17", "101"), ("17", "102")}

    _run(tmp_path, "newlistsent", body)


def test_a_failed_create_skips_its_members_with_the_reason(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        refusal = ExecuteResult(
            False,
            {"http_error": "400", "status_code": 400},
            '{"status":"error","message":"A list with this name already exists."}',
        )
        gateway = _WritingCrm(lists={"101": []}, failures={"HUBSPOT_CREATE_LIST": [refusal]})
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _create_list("Clue: Q4"), _add_to_new("101")
        )

        await _handle(_handler(conn, tmp_path, gateway), connection)

        logged: dict[Any, dict[str, Any]] = await _writes(conn, proposal_id)
        assert logged[None]["status"] == "failed"  # the create names no list: none was made
        assert (logged["101"]["status"], logged["101"]["crm_message"]) == ("skipped", NOT_CREATED)
        assert logged["101"]["sent"] is False
        assert [slug for slug, _ in gateway.writes] == ["HUBSPOT_CREATE_LIST"]
        assert await _proposal_status(conn, proposal_id) == "finished"

    _run(tmp_path, "newlistfail", body)


def test_an_unchosen_create_skips_its_members(tmp_path: Path) -> None:
    """A covered add whose create the person unticked is never sent."""

    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm(lists={"101": []})
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _create_list("Clue: Q4"), _add_to_new("101")
        )
        await conn.execute(
            text(
                "UPDATE crm_write SET selected = false WHERE proposal_id = :id "
                "AND kind = 'list_create'"
            ),
            {"id": proposal_id},
        )

        await _handle(_handler(conn, tmp_path, gateway), connection)

        logged = await _writes(conn, proposal_id)
        assert (logged["101"]["status"], logged["101"]["crm_message"]) == ("skipped", NOT_CREATED)
        assert gateway.writes == []

    _run(tmp_path, "newlistunchosen", body)


def test_a_resume_after_a_crash_between_the_create_and_the_adds_uses_the_kept_id(
    tmp_path: Path,
) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        crashed: list[bool] = []

        async def die_before_the_add(slug: str, arguments: dict[str, Any]) -> None:
            if slug == "HUBSPOT_UPDATE_LIST_MEMBERSHIPS" and not crashed:
                crashed.append(True)
                raise RuntimeError("the worker died after the list was made")

        gateway = _WritingCrm(lists={"101": []}, on_write=die_before_the_add)
        proposal_id = await _propose(
            conn, seeded, connection, gateway, _create_list("Clue: Q4"), _add_to_new("101")
        )
        handler = _handler(conn, tmp_path, gateway)
        with pytest.raises(RuntimeError):
            await _handle(handler, connection)
        assert (await _arguments(conn, proposal_id))["101"]["list_id"] == "17"

        await _handle(handler, connection)

        adds = [args for slug, args in gateway.writes if slug == "HUBSPOT_UPDATE_LIST_MEMBERSHIPS"]
        assert [a["list_id"] for a in adds] == ["17", "17"]
        assert [slug for slug, _ in gateway.writes].count("HUBSPOT_CREATE_LIST") == 1
        assert (await _writes(conn, proposal_id))["101"]["status"] == "succeeded"
        assert gateway.lists["101"] == ["17"]

    _run(tmp_path, "newlistcrash", body)


def test_a_new_campaign_is_created_then_its_contacts_are_added(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        gateway = _WritingCrm()
        proposal_id = await _propose(
            conn,
            seeded,
            connection,
            gateway,
            ProposedChange("SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q4"}, "committee"),
            ProposedChange(
                "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN",
                {"campaign_id": "new:Clue: Q4", "contact_id": "003A"},
                "committee",
            ),
        )

        await _handle(_handler(conn, tmp_path, gateway), connection)

        campaign = gateway.crm_lists["Clue: Q4"]
        assert [slug for slug, _ in gateway.writes] == [
            "SALESFORCE_CREATE_CAMPAIGN",
            "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN",
        ]
        assert gateway.writes[1][1] == {"campaign_id": campaign, "contact_id": "003A"}
        assert gateway.campaign_members == {(campaign, "003A")}
        logged = await _writes(conn, proposal_id)
        assert logged["003A"]["status"] == "succeeded"
        assert logged[campaign]["status"] == "succeeded"

    _run(tmp_path, "newcampaignsent", body, provider="salesforce")
