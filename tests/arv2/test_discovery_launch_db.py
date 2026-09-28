"""R4's launch against the real tables: one run pinned to the project's ICP, replayable, offered.

The discovery launch is the same authority boundary R2's is, applied to a different act: it says
*which document* a long list will be built from, *how many* companies were asked for, and *which*
of the document's hard gates the provider filters on — and everything the driver later spends is
spent against that row. So the same three properties are pinned here: the run is deterministic (the
same request is one run, not two), every refusal is typed and named, and the fleet is told only
after the rows are committed.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.discovery_launch import (
    ARV2_DISCOVERY_DEDUP_PREFIX,
    ARV2_DISCOVERY_TASK_PRIORITY,
    Arv2DiscoveryRefused,
    Arv2DiscoveryRequest,
    DbArv2DiscoveryService,
    enqueue_discovery_run,
    launch_arv2_discovery,
    read_pinned_icp,
)
from clue_api.arv2.discovery_store import read_discovery_run
from clue_fleet import FleetTaskKind
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.arv2.icp_fixture import (
    ICP_KEY,
    USER_ID,
    FakeQueue,
    IcpFixture,
    seed_icp_fixture,
    settings_for,
)

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _settings(*, enabled: bool = True) -> Any:
    return settings_for(arv2_discovery_enabled=enabled)


def _request(fixture: IcpFixture, **overrides: Any) -> Arv2DiscoveryRequest:
    payload: dict[str, Any] = {
        "workspace_id": fixture.workspace_id,
        "project_id": fixture.project_id,
        "requested_by_user_id": USER_ID,
        "request_key": "turn-action:ask-1",
        "target_count": 20,
    }
    payload.update(overrides)
    return Arv2DiscoveryRequest(**payload)


def test_a_launch_creates_one_run_pinned_to_the_projects_icp_and_records_lineage(
    tmp_path: Any,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            receipt = await launch_arv2_discovery(
                conn,
                _request(fixture),
                settings=_settings(),
                storage=storage,
            )

            run = await read_discovery_run(conn, run_id=receipt.run_id)
            assert run is not None
            assert run.icp_artifact_sha256 == fixture.icp_artifact_sha256
            assert run.icp_artifact_key == fixture.icp_artifact_key
            assert run.icp_key == ICP_KEY and run.icp_version == 1
            assert run.brand_id == fixture.brand_id
            assert run.project_run_id == receipt.project_run_id
            assert run.requested_by_user_id == USER_ID
            # The relaxed flag comes from the settings when the request names none; the gate set
            # comes from the document itself — no ``criterion`` marks, so its first three gates —
            # and the run row records that resolution for every later attempt to compile from.
            # Nothing is asked of the provider yet: the searches record their asks as they run.
            assert run.target_count == 20 and run.asked is None
            assert run.relaxed_enabled is True
            assert run.criteria_gate_keys == ("geography", "stage", "hiring")
            assert run.status == "not_started"
            assert receipt.replayed is False and receipt.to_enqueue is True
            assert receipt.workspace_id == fixture.workspace_id

            lineage = (
                await conn.execute(
                    text(
                        "SELECT kind, project_id, project_run_id FROM run_lineage WHERE run_id = :r"
                    ),
                    {"r": receipt.run_id},
                )
            ).one()
            assert tuple(lineage) == ("discovery", fixture.project_id, receipt.project_run_id)

            # The offer is the caller's, made after the rows are committed.
            queue = FakeQueue()
            assert await enqueue_discovery_run(queue, receipt) is True
            offered = queue.calls[0]
            assert offered["kind"] is FleetTaskKind.ARV2_DISCOVERY
            assert offered["payload"] == {
                "run_id": str(receipt.run_id),
                "workspace_id": fixture.workspace_id,
            }
            assert offered["dedup_key"] == f"{ARV2_DISCOVERY_DEDUP_PREFIX}{receipt.run_id}"
            assert offered["priority"] == ARV2_DISCOVERY_TASK_PRIORITY
            # A relaxed request re-offers a finished run's task, so the offer must reopen it.
            assert offered["reopen_terminal"] is True

    run_async(scenario())


def test_the_same_ask_replays_to_the_same_run_and_a_new_ask_is_a_new_run(tmp_path: Any) -> None:
    """The same ask retried is one run — a replayed turn does not buy two long lists — while a new
    ask with the SAME numbers is a new run (founder ruling 2026-09-28: "find more" is a new run)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            first = await launch_arv2_discovery(
                conn, _request(fixture), settings=_settings(), storage=storage
            )
            second = await launch_arv2_discovery(
                conn, _request(fixture), settings=_settings(), storage=storage
            )

            assert second.run_id == first.run_id
            assert first.replayed is False and second.replayed is True
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_discovery_run WHERE project_id = :p"),
                    {"p": fixture.project_id},
                )
            ).scalar_one()
            assert count == 1

            # A different target is a different run — it is part of what was approved.
            other = await launch_arv2_discovery(
                conn, _request(fixture, target_count=40), settings=_settings(), storage=storage
            )
            assert other.run_id != first.run_id

            # And asking again for the very same number, in a new action, is a new run too.
            again = await launch_arv2_discovery(
                conn,
                _request(fixture, request_key="turn-action:ask-2"),
                settings=_settings(),
                storage=storage,
            )
            assert again.run_id not in {first.run_id, other.run_id}
            assert again.replayed is False and again.to_enqueue is True

    run_async(scenario())


def test_refusals_are_named(tmp_path: Any) -> None:
    """Every prerequisite failure is a typed code, never a stack trace the operator must read."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            with pytest.raises(Arv2DiscoveryRefused) as disabled:
                await launch_arv2_discovery(
                    conn, _request(fixture), settings=_settings(enabled=False), storage=storage
                )
            assert disabled.value.code == "lane_disabled"

            with pytest.raises(Arv2DiscoveryRefused) as unknown_project:
                await launch_arv2_discovery(
                    conn,
                    _request(fixture, project_id="prj_nowhere"),
                    settings=_settings(),
                    storage=storage,
                )
            assert unknown_project.value.code == "project_not_found"

            with pytest.raises(Arv2DiscoveryRefused) as bad_count:
                await launch_arv2_discovery(
                    conn, _request(fixture, target_count=0), settings=_settings(), storage=storage
                )
            assert bad_count.value.code == "target_count_invalid"

            with pytest.raises(Arv2DiscoveryRefused) as bad_gate:
                await launch_arv2_discovery(
                    conn,
                    _request(fixture, criteria_gate_keys=("vertical",)),
                    settings=_settings(),
                    storage=storage,
                )
            assert bad_gate.value.code == "unknown_criteria_gate_key"
            assert "vertical" in str(bad_gate.value)

            # A project that pinned nothing has no ICP, and saying so is the honest answer. The pin
            # table is append-only, so the unpinned case is a second project rather than a delete.
            unpinned_project = await seed_project(conn, fixture.workspace_id, name="No ICP here")
            with pytest.raises(Arv2DiscoveryRefused) as unpinned:
                await launch_arv2_discovery(
                    conn,
                    _request(fixture, project_id=unpinned_project.project_id),
                    settings=_settings(),
                    storage=storage,
                )
            assert unpinned.value.code == "project_icp_not_pinned"

    run_async(scenario())


def test_the_pinned_icp_read_serves_the_document_the_brief_is_compiled_from(
    tmp_path: Any,
) -> None:
    """The driver reads the same document the launch validated — front matter, body and pins."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            document = await read_pinned_icp(
                conn,
                storage,
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
            )

            assert document.icp_key == ICP_KEY and document.icp_version == 1
            assert document.artifact_sha256 == fixture.icp_artifact_sha256
            assert document.artifact_key == fixture.icp_artifact_key
            assert document.brand_id == fixture.brand_id
            assert [gate["key"] for gate in document.front["hard_gates"]] == [
                "geography",
                "stage",
                "hiring",
                "intent",
            ]
            assert document.body.lstrip().startswith("# Who we sell to")

    run_async(scenario())


def test_the_launch_cannot_enqueue_at_all() -> None:
    """Rows first, offer second — the launch takes no queue and cannot reach one."""
    parameters = inspect.signature(launch_arv2_discovery).parameters
    assert "queue" not in parameters
    assert ".enqueue(" not in inspect.getsource(launch_arv2_discovery)


def test_the_service_offers_the_task_only_after_the_launch_transaction_closes(
    tmp_path: Any,
) -> None:
    """The production seam's ordering, pinned: rows committed, THEN the fleet is told."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            trace: list[str] = []
            queue = FakeQueue(trace=trace)

            @asynccontextmanager
            async def factory() -> AsyncIterator[AsyncConnection]:
                trace.append("transaction_opened")
                try:
                    yield conn
                finally:
                    # The real ``transaction`` commits here; the test's connection rolls back at
                    # the end of the case, so what is asserted is the ORDER, not the durability.
                    trace.append("transaction_closed")

            service = DbArv2DiscoveryService(
                _settings(), storage, queue=queue, conn_factory=factory
            )

            receipt = await service.launch(_request(fixture))

            assert trace == ["transaction_opened", "transaction_closed", "enqueue"]
            assert queue.calls[0]["payload"]["run_id"] == str(receipt.run_id)

    run_async(scenario())
