"""Clue keeps the CRM lists and campaigns it uses (CRM integration Phase 3, Task 2; R-11.11).

A list (HubSpot) or campaign (Salesforce) is one ``crm_list`` row per connection and CRM id,
linked to every project that uses it through ``crm_list_project``. Membership stays per list
member in ``crm_record_link``, and a member counts as a project's only when that project's
proposal added it, so one project never removes a member another project added. The database is
the lane's test DB; nothing calls a CRM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_api.crm import writes
from clue_api.crm.connections import CrmConnection
from clue_api.crm.lists import (
    link_project,
    lists_for_project,
    mark_gone,
    store_list,
)
from clue_api.crm.write_prepare import ProposedChange, WriteRefused, prepare_changes
from tests._workspace import seed_project
from tests.api.test_crm_tools_db import _connect
from tests.api.test_crm_write_prepare_db import _added_by, _FakeCrm
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


def _run(tmp_path: Path, label: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crml-{label}", label=label)
            connection = await _connect(conn, seeded.workspace_id)
            await body(conn, seeded, connection)

    run_async(scenario())


async def _store(
    conn: Any,
    seeded: Any,
    connection: CrmConnection,
    *,
    crm_list_id: str = "17",
    project_id: str | None = None,
    connection_id: UUID | None = None,
) -> Any:
    return await store_list(
        conn,
        workspace_id=seeded.workspace_id,
        connection_id=connection_id or connection.connection_id,
        provider="hubspot",
        crm_object="contact",
        crm_list_id=crm_list_id,
        name="Q4 buying committees",
        kind="hubspot_list",
        created_by_clue=True,
        created_by_write_id=None,
        project_id=project_id or seeded.project_id,
    )


def test_a_created_list_is_stored_once_and_linked_to_its_project(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        first = await _store(conn, seeded, connection)
        again = await _store(conn, seeded, connection)
        assert again.list_id == first.list_id
        assert first.crm_list_id == "17" and first.kind == "hubspot_list"
        assert first.crm_object == "contact" and first.created_by_clue and first.gone_at is None
        rows = await conn.execute(
            text("SELECT count(*) FROM crm_list WHERE connection_id = :c"),
            {"c": connection.connection_id},
        )
        assert rows.scalar_one() == 1
        links = await conn.execute(
            text("SELECT project_id, linked_by FROM crm_list_project WHERE list_id = :l"),
            {"l": first.list_id},
        )
        assert [tuple(row) for row in links] == [(seeded.project_id, "clue_created")]
        assert await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        ) == [first]

    _run(tmp_path, "stored", body)


def test_a_list_serves_two_projects(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        other = await seed_project(conn, seeded.workspace_id, name="Second motion")
        stored = await _store(conn, seeded, connection)
        await link_project(
            conn,
            list_id=stored.list_id,
            project_id=other.project_id,
            workspace_id=seeded.workspace_id,
            linked_by="person_named",
        )
        # Linking twice changes nothing.
        await link_project(
            conn,
            list_id=stored.list_id,
            project_id=other.project_id,
            workspace_id=seeded.workspace_id,
            linked_by="person_named",
        )
        for project_id in (seeded.project_id, other.project_id):
            assert await lists_for_project(
                conn,
                workspace_id=seeded.workspace_id,
                project_id=project_id,
                connection_id=connection.connection_id,
            ) == [stored]

    _run(tmp_path, "twoprojects", body)


def test_a_gone_list_is_not_offered(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        await _store(conn, seeded, connection, crm_list_id="17")
        kept = await _store(conn, seeded, connection, crm_list_id="18")
        await mark_gone(conn, connection_id=connection.connection_id, crm_list_id="17")
        assert await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        ) == [kept]
        gone_at = await conn.execute(
            text("SELECT gone_at FROM crm_list WHERE crm_list_id = '17' AND connection_id = :c"),
            {"c": connection.connection_id},
        )
        assert gone_at.scalar_one() is not None

    _run(tmp_path, "gone", body)


async def _other_connection(conn: Any, workspace_id: str) -> UUID:
    connection_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO workspace_integration_connection (connection_id, workspace_id, provider, "
            "composio_connected_account_id, composio_auth_config_id, status, connected_by_user_id) "
            "VALUES (:id, :ws, 'hubspot', :acct, 'ac_test', 'disconnected', :u)"
        ),
        {"id": connection_id, "ws": workspace_id, "acct": f"ca_{uuid4().hex[:8]}", "u": USER_ID},
    )
    return connection_id


def test_lists_are_per_connection(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        other = await _other_connection(conn, seeded.workspace_id)
        here = await _store(conn, seeded, connection)
        there = await _store(conn, seeded, connection, connection_id=other)
        assert here.list_id != there.list_id
        assert there.connection_id == other
        assert await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        ) == [here]

    _run(tmp_path, "perconn", body)


def _remove(record: str, list_id: str = "17") -> ProposedChange:
    return ProposedChange(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        {"list_id": list_id, "operation": "remove", "record_ids": [record]},
        "no longer on the committee",
    )


def test_members_added_for_one_project_are_not_removable_as_anothers(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        other = await seed_project(conn, seeded.workspace_id, name="Second motion")
        stored = await _store(conn, seeded, connection)
        await link_project(
            conn,
            list_id=stored.list_id,
            project_id=other.project_id,
            workspace_id=seeded.workspace_id,
            linked_by="person_named",
        )
        await _added_by(conn, seeded, connection, seeded.project_id, "17", "p1")

        # Membership stays keyed by list: Clue added p1 to list 17.
        pairs = [("17", "p1")]
        assert await writes.clue_added_members(
            conn, connection_id=connection.connection_id, pairs=pairs
        ) == {("17", "p1")}
        assert await writes.clue_added_members(
            conn,
            connection_id=connection.connection_id,
            pairs=pairs,
            project_id=seeded.project_id,
        ) == {("17", "p1")}
        assert not await writes.clue_added_members(
            conn,
            connection_id=connection.connection_id,
            pairs=pairs,
            project_id=other.project_id,
        )

        gateway = _FakeCrm(lists={"p1": ["17"]})

        async def prepare(project_id: str) -> Any:
            return await prepare_changes(
                conn,
                gateway=gateway,  # type: ignore[arg-type]
                budget=None,
                connection=connection,
                proposal_id=uuid4(),
                project_id=project_id,
                changes=[_remove("p1")],
                version="v-test",
            )

        # The second project shares the list but never added p1: its removal is refused.
        with pytest.raises(WriteRefused) as refused:
            await prepare(other.project_id)
        assert refused.value.reason_code == "crm_removal_not_allowed"

        # The project that added p1 may remove it.
        batch = await prepare(seeded.project_id)
        assert [change.scope_key for change in batch.changes] == ["kind:list_removal"]

    _run(tmp_path, "members", body)


def test_a_list_found_again_after_it_was_gone_is_offered_again(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        stored = await _store(conn, seeded, connection)
        await mark_gone(conn, connection_id=connection.connection_id, crm_list_id="17")
        found = await _store(conn, seeded, connection)
        assert found.list_id == stored.list_id and found.gone_at is None
        assert await lists_for_project(
            conn,
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            connection_id=connection.connection_id,
        ) == [found]

    _run(tmp_path, "foundagain", body)


def test_a_list_is_never_linked_to_a_project_of_another_workspace(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        stored = await _store(conn, seeded, connection)
        foreign = await seed_project(conn, f"{seeded.workspace_id}-other", name="Elsewhere")
        for workspace_id in (seeded.workspace_id, foreign.workspace_id):
            savepoint = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await link_project(
                    conn,
                    list_id=stored.list_id,
                    project_id=foreign.project_id,
                    workspace_id=workspace_id,
                    linked_by="person_named",
                )
            await savepoint.rollback()

    _run(tmp_path, "foreign", body)
