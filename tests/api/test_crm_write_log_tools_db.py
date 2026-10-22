"""``crm_write_log@1`` and ``manage_crm_grants@1`` (CRM integration Phase 2, Task 8).

The log answers what Clue changed in the CRM (and its before values, so the agent can propose an
undo with ``propose_crm_changes``). The grants tool lists the active connection's standing
permissions in plain words and revokes one; granting happens only on the permission card. The CRM
is a fake gateway; the database is the lane's test DB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.crm import writes
from clue_api.crm.connections import activate_from_attempt, start_attempt
from clue_api.crm.write_tools import (
    CrmChangeInput,
    CrmWriteLogInput,
    CrmWriteLogTool,
    ManageCrmGrantsInput,
    ManageCrmGrantsTool,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_toolbelt import PreconditionFailed
from tests.api.test_crm_propose_db import _ctx, _FakeQueue, _input, _tool
from tests.api.test_crm_tools_db import _connect
from tests.api.test_crm_write_prepare_db import _FakeCrm
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


def _log_tool(conn: Any) -> CrmWriteLogTool:
    return CrmWriteLogTool(
        gateway=_FakeCrm(),  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
    )


def _grants_tool(conn: Any) -> ManageCrmGrantsTool:
    return ManageCrmGrantsTool(
        gateway=_FakeCrm(),  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
    )


def _set(
    record: str,
    field: str,
    value: object,
    *,
    reverses: UUID | None = None,
    slug: str = "HUBSPOT_UPDATE_COMPANY",
) -> CrmChangeInput:
    return CrmChangeInput(
        slug=slug,
        arguments={"companyId": record, "properties": {field: value}},
        reason="Undo the ICP tier." if reverses else "The ICP tiers Clue scored.",
        reverses_write_id=reverses,
    )


async def _propose(conn: Any, seeded: Any, gateway: _FakeCrm, *changes: CrmChangeInput) -> str:
    tool = _tool(conn, gateway, _FakeQueue())
    refs = (await tool.invoke(_input(seeded, *changes), _ctx(conn, seeded.workspace_id))).references
    return str(refs["proposal_id"])


async def _write_ids(conn: Any, proposal_id: str) -> list[UUID]:
    rows = await conn.execute(
        text("SELECT write_id FROM crm_write WHERE proposal_id = :id ORDER BY ordinal"),
        {"id": UUID(proposal_id)},
    )
    return [row.write_id for row in rows]


async def _finish(
    conn: Any,
    write_id: UUID,
    status: str,
    *,
    days_ago: int = 0,
    failure_kind: str | None = None,
    crm_message: str | None = None,
) -> None:
    await conn.execute(
        text(
            "UPDATE crm_write SET status = :status, failure_kind = :failure_kind, "
            "crm_message = :crm_message, sent_at = now() - make_interval(days => :days), "
            "finished_at = now() - make_interval(days => :days) WHERE write_id = :id"
        ),
        {
            "id": write_id,
            "status": status,
            "failure_kind": failure_kind,
            "crm_message": crm_message,
            "days": days_ago,
        },
    )


async def _grant(conn: Any, seeded: Any, connection: Any, scope_key: str) -> UUID:
    return await writes.insert_grant(
        conn,
        workspace_id=seeded.workspace_id,
        connection_id=connection.connection_id,
        scope_key=scope_key,
        granted_by_user_id=USER_ID,
    )


def _grants_input(seeded: Any, action: str, grant_id: UUID | None = None) -> ManageCrmGrantsInput:
    return ManageCrmGrantsInput(
        action=action,  # type: ignore[arg-type]
        grant_id=grant_id,
        source_turn_ref=derive_turn_action_ref(seeded.turn_id),
    )


def _run(tmp_path: Path, label: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crml-{label}", label=label)
            connection = await _connect(conn, seeded.workspace_id)
            await conn.execute(
                text("UPDATE platform_user SET display_name = 'Aryan' WHERE user_id = :user"),
                {"user": USER_ID},
            )
            await body(conn, seeded, connection)

    run_async(scenario())


def test_the_log_answers_what_changed_this_week(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _grant(conn, seeded, connection, "field:company.icp_tier")
        gateway = _FakeCrm(
            records={"101": {"icp_tier": None}, "102": {"icp_tier": None}, "103": {}}
        )
        this_week = await _propose(
            conn,
            seeded,
            gateway,
            _set("101", "icp_tier", "Tier 1"),
            _set("102", "icp_tier", "Tier 2"),
        )
        last_month = await _propose(conn, seeded, gateway, _set("103", "icp_tier", "Tier 3"))
        done, refused = await _write_ids(conn, this_week)
        (old,) = await _write_ids(conn, last_month)
        await _finish(conn, done, "succeeded")
        await _finish(
            conn,
            refused,
            "failed",
            failure_kind="validation_rule",
            crm_message="Tier 2 needs an owner.",
        )
        await _finish(conn, old, "succeeded", days_ago=20)
        await conn.execute(
            text(
                "UPDATE crm_write_proposal SET created_at = now() - interval '20 days' "
                "WHERE proposal_id = :id"
            ),
            {"id": UUID(last_month)},
        )
        tool = _log_tool(conn)
        ctx = _ctx(conn, seeded.workspace_id)

        refs = (await tool.invoke(CrmWriteLogInput(), ctx)).references

        # Newest first; changes finished together keep their order in the batch.
        assert [row["write_id"] for row in refs["writes"]] == [str(done), str(refused)]
        by_id = {row["write_id"]: row for row in refs["writes"]}
        assert set(by_id) == {str(done), str(refused)}
        assert by_id[str(done)] == {
            "write_id": str(done),
            "slug": "HUBSPOT_UPDATE_COMPANY",
            "object": "company",
            "kind": "field_update",
            "when": by_id[str(done)]["when"],
            "record_label": by_id[str(done)]["record_label"],
            "record_ref": "101",
            "field": "icp_tier",
            "before": None,
            "after": "Tier 1",
            "status": "succeeded",
            "failure_kind": None,
            "crm_message": None,
            "reason": "The ICP tiers Clue scored.",
            "proposal_id": this_week,
        }
        assert by_id[str(done)]["when"] is not None
        assert by_id[str(refused)]["failure_kind"] == "validation_rule"
        assert by_id[str(refused)]["crm_message"] == "Tier 2 needs an owner."

        # Narrowed: by status, by record, by proposal (which reaches past the week), and wider.
        failed = (await tool.invoke(CrmWriteLogInput(status="failed"), ctx)).references
        assert [row["write_id"] for row in failed["writes"]] == [str(refused)]
        record = (await tool.invoke(CrmWriteLogInput(record="101"), ctx)).references
        assert [row["write_id"] for row in record["writes"]] == [str(done)]
        older = (await tool.invoke(CrmWriteLogInput(proposal_id=UUID(last_month)), ctx)).references
        assert [row["write_id"] for row in older["writes"]] == [str(old)]
        month = (await tool.invoke(CrmWriteLogInput(since_days=30), ctx)).references
        assert len(month["writes"]) == 3
        limited = (await tool.invoke(CrmWriteLogInput(limit=1), ctx)).references
        assert [row["write_id"] for row in limited["writes"]] == [str(done)]

    _run(tmp_path, "week", body)


def test_an_undo_proposal_carries_the_before_values(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _grant(conn, seeded, connection, "field:company.icp_tier")
        # A person had set Tier 3; Clue's change to Tier 1 (approved on a card) went through.
        gateway = _FakeCrm(records={"101": {"icp_tier": "Tier 3"}})
        first = await _propose(conn, seeded, gateway, _set("101", "icp_tier", "Tier 1"))
        (write_id,) = await _write_ids(conn, first)
        await _finish(conn, write_id, "succeeded")
        gateway.records["101"]["icp_tier"] = "Tier 1"

        log = (
            await _log_tool(conn).invoke(
                CrmWriteLogInput(proposal_id=UUID(first)), _ctx(conn, seeded.workspace_id)
            )
        ).references
        (row,) = log["writes"]
        assert (row["before"], row["after"]) == ("Tier 3", "Tier 1")

        undo = await _propose(
            conn,
            seeded,
            gateway,
            _set(
                row["record_ref"],
                row["field"],
                row["before"],
                reverses=UUID(row["write_id"]),
                slug=row["slug"],
            ),
        )

        logged = (
            await conn.execute(
                text(
                    "SELECT reverses_write_id, before_value::text AS before_value, "
                    "after_value::text AS after_value, overwrites_person "
                    "FROM crm_write WHERE proposal_id = :id"
                ),
                {"id": UUID(undo)},
            )
        ).one()
        assert logged.reverses_write_id == write_id
        assert (json.loads(logged.before_value), json.loads(logged.after_value)) == (
            "Tier 1",
            "Tier 3",
        )
        # The value it replaces is Clue's own, so the undo does not count as overwriting a person.
        assert logged.overwrites_person is False

    _run(tmp_path, "undo", body)


def test_grants_are_listed_and_revoked(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        field = await _grant(conn, seeded, connection, "field:company.icp_tier")
        lists = await _grant(conn, seeded, connection, "kind:list_membership")
        granted_at = (await conn.execute(text("SELECT now()"))).scalar_one()
        when = f"{granted_at.day} {granted_at:%b}"
        tool = _grants_tool(conn)
        ctx = _ctx(conn, seeded.workspace_id)

        listed = (await tool.invoke(_grants_input(seeded, "list"), ctx)).references
        assert listed["revoked"] is None
        # Granted in one transaction, so in no particular order between themselves.
        assert {g["grant_id"]: g["phrase"] for g in listed["grants"]} == {
            str(field): f"Always allow setting “icp_tier” on companies — by Aryan, {when}",
            str(
                lists
            ): f"Always allow adding records to Clue lists and campaigns — by Aryan, {when}",
        }

        revoked = (await tool.invoke(_grants_input(seeded, "revoke", field), ctx)).references
        assert revoked["revoked"]["grant_id"] == str(field)
        assert [g["grant_id"] for g in revoked["grants"]] == [str(lists)]
        stamped = (
            await conn.execute(
                text(
                    "SELECT revoked_by_user_id, revoked_at FROM crm_write_grant "
                    "WHERE grant_id = :id"
                ),
                {"id": field},
            )
        ).one()
        assert stamped.revoked_by_user_id == USER_ID and stamped.revoked_at is not None

        assert revoked["already_revoked"] is False

        # Revoking it again (a replay) answers that it is already revoked and changes nothing.
        again = (await tool.invoke(_grants_input(seeded, "revoke", field), ctx)).references
        assert again["already_revoked"] is True
        assert again["revoked"]["grant_id"] == str(field)
        assert [g["grant_id"] for g in again["grants"]] == [str(lists)]
        restamped = (
            await conn.execute(
                text(
                    "SELECT revoked_by_user_id, revoked_at FROM crm_write_grant "
                    "WHERE grant_id = :id"
                ),
                {"id": field},
            )
        ).one()
        assert tuple(restamped) == tuple(stamped)

        # A revoke names the grant it revokes; a list names none.
        with pytest.raises(PreconditionFailed) as unnamed:
            await tool.invoke(_grants_input(seeded, "revoke"), ctx)
        assert [f.reason_code for f in unnamed.value.failures] == ["crm_grant_not_named"]
        with pytest.raises(PreconditionFailed):
            await tool.invoke(_grants_input(seeded, "revoke", uuid4()), ctx)

    _run(tmp_path, "grants", body)


def test_a_new_connection_starts_with_no_grants(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        old_grant = await _grant(conn, seeded, connection, "field:company.icp_tier")
        tool = _grants_tool(conn)
        ctx = _ctx(conn, seeded.workspace_id)
        before = (await tool.invoke(_grants_input(seeded, "list"), ctx)).references
        assert len(before["grants"]) == 1

        await _connect(conn, seeded.workspace_id, provider="salesforce")

        after = (await tool.invoke(_grants_input(seeded, "list"), ctx)).references
        assert after["grants"] == []

        # The old connection's grant no longer applies, so it cannot be revoked either: it reads
        # as unknown, like a missing id, and stays as it was.
        with pytest.raises(PreconditionFailed) as old:
            await tool.invoke(_grants_input(seeded, "revoke", old_grant), ctx)
        assert [f.reason_code for f in old.value.failures] == ["crm_grant_not_found"]
        assert await writes.live_grants(conn, connection_id=connection.connection_id)

    _run(tmp_path, "new-connection", body)


async def _connect_as(conn: Any, workspace_id: str, account_id: str) -> Any:
    """A HubSpot connection under its own connected account (``_connect`` reuses one id)."""
    request_id = (
        await conn.execute(
            text(
                "INSERT INTO crm_connect_request (request_id, workspace_id, project_id, "
                "thread_id, turn_id, requested_by_user_id, mode) VALUES (gen_random_uuid(), "
                ":ws, 'p', 't', gen_random_uuid(), :user, 'connect') RETURNING request_id"
            ),
            {"ws": workspace_id, "user": USER_ID},
        )
    ).scalar_one()
    await start_attempt(
        conn,
        request_id=request_id,
        workspace_id=workspace_id,
        provider="hubspot",
        connected_account_id=account_id,
        started_by_user_id=USER_ID,
    )
    activated = await activate_from_attempt(
        conn,
        request_id=request_id,
        workspace_id=workspace_id,
        connected_account_id=account_id,
        auth_config_id="ac_h",
    )
    assert activated is not None
    return activated[0]


def test_another_workspace_s_log_and_grants_are_out_of_reach(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        del connection
        other = await _seed(conn, tmp_path, workspace_id="ws-crml-iso-other", label="iso-other")
        other_connection = await _connect_as(conn, other.workspace_id, "ca_hubspot_other")
        foreign_grant = await _grant(conn, other, other_connection, "field:company.icp_tier")
        gateway = _FakeCrm(records={"101": {"icp_tier": None}})
        foreign = await _propose(conn, other, gateway, _set("101", "icp_tier", "Tier 1"))
        (foreign_write,) = await _write_ids(conn, foreign)
        await _finish(conn, foreign_write, "succeeded")
        log = _log_tool(conn)
        ctx = _ctx(conn, seeded.workspace_id)

        # Its own workspace reads it; this one does not, not even by its proposal id.
        theirs = (
            await log.invoke(
                CrmWriteLogInput(proposal_id=UUID(foreign)), _ctx(conn, other.workspace_id)
            )
        ).references
        assert [row["write_id"] for row in theirs["writes"]] == [str(foreign_write)]
        by_id = (await log.invoke(CrmWriteLogInput(proposal_id=UUID(foreign)), ctx)).references
        assert by_id["writes"] == []
        assert (await log.invoke(CrmWriteLogInput(), ctx)).references["writes"] == []

        # Its grant cannot be revoked from here, and stays live.
        with pytest.raises(PreconditionFailed) as elsewhere:
            await _grants_tool(conn).invoke(_grants_input(seeded, "revoke", foreign_grant), ctx)
        assert [f.reason_code for f in elsewhere.value.failures] == ["crm_grant_not_found"]
        assert [
            g.grant_id
            for g in await writes.live_grants(conn, connection_id=other_connection.connection_id)
        ] == [foreign_grant]

    _run(tmp_path, "isolation", body)


def test_both_tools_refuse_when_the_crm_is_not_configured(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        del connection
        ctx = _ctx(conn, seeded.workspace_id)
        log = CrmWriteLogTool(gateway=None, conn_factory=conn_session_factory(conn))
        grants = ManageCrmGrantsTool(gateway=None, conn_factory=conn_session_factory(conn))
        assert [f.reason_code for f in await log.preconditions(CrmWriteLogInput(), ctx)] == [
            "crm_not_configured"
        ]
        assert [
            f.reason_code for f in await grants.preconditions(_grants_input(seeded, "list"), ctx)
        ] == ["crm_not_configured"]

    _run(tmp_path, "unconfigured", body)


def test_a_list_create_grant_is_worded_like_the_card() -> None:
    from clue_api.crm.write_tools import _grant_phrase

    assert _grant_phrase("hubspot", "kind", "list_create", None, None) == "creating Clue lists"
    assert (
        _grant_phrase("salesforce", "kind", "list_create", None, None) == "creating Clue campaigns"
    )
    # R-12.8: one standing permission each for adding to and removing from any list or campaign.
    for provider in ("hubspot", "salesforce"):
        assert (
            _grant_phrase(provider, "kind", "list_membership", None, None)
            == "adding records to Clue lists and campaigns"
        )
        assert (
            _grant_phrase(provider, "kind", "list_removal", None, None)
            == "removing records from Clue lists and campaigns"
        )
