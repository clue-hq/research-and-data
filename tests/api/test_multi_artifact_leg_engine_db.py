"""Spec §3.3/§3.9 — one leg turn, many documents: fan out, join, summarise, stop.

A leg with three documents dispatches three design runs (one per document, each with its own
derived run id, its own session thread and its own item line on the brief) plus three
``design_job`` fleet tasks in ONE transaction, drives them through ``drive_batch``, records
receipts for all of them and hands back ONCE with a per-document summary. A partial failure
still hands back; a total failure fails the turn and leaves the leg open; a retry re-joins
without creating a second batch; Stop asks every non-terminal run of the batch to cancel.

A ONE-document leg keeps the shipped path byte-for-byte: ``lane.drive`` (never
``drive_batch``), no fleet task, position-0 run id, ``_assistant_summary`` as the message.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentExecutionStatus
from clue_api.design_leg_wiring import (
    DESIGN_LEG_TURN_FAILED,
    batch_summary,
    design_leg_execution_id,
    design_leg_run_id,
)
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import create_document
from clue_design.legs import LegDocumentSpec
from tests.api.test_genad_leg_document_birth_db import engine_ad_scene
from tests.api.test_p34_design_leg_engine_db import (
    _run_turn,
    _runner,
    _seed_leg_conversation,
    _submit_message,
    registry,  # noqa: F401 -- exposes the module-scoped fixture to this module
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

_TITLES = ("Apollo ad", "Mercy ad", "Vertex ad")


class _FakeBatchLane:
    """Completes every run of the batch; ``status_for`` lets one test fail one of them."""

    def __init__(
        self,
        *,
        conn_factory: Any,
        status_for: Any = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._status_for = status_for or (lambda run_id: "succeeded")
        self.batches: list[list[Any]] = []
        self.singles: list[Any] = []

    async def drive(self, *, envelope: Any) -> None:
        # A one-document leg still takes this path — the shipped single-run seam.
        self.singles.append(envelope)
        await self.drive_batch(envelopes=[envelope])

    async def drive_batch(self, *, envelopes: Any) -> None:
        self.batches.append(list(envelopes))
        async with self._conn_factory() as conn:
            for envelope in envelopes:
                status = self._status_for(envelope.run_id)
                await design_runs.set_run_result(
                    conn,
                    workspace_id=envelope.workspace_id,
                    run_id=envelope.run_id,
                    status=status,
                    result=(
                        {
                            "schema_version": 1,
                            "status": "proposed",
                            "acceptance_scope": "design",
                            "current_version": 3,
                        }
                        if status == "succeeded"
                        else {
                            "schema_version": 1,
                            "status": "failed",
                            "error": {"code": "agent_runtime.failed", "message": "boom"},
                        }
                    ),
                )


class _LaneThatNeverTerminalizes:
    """Creates the rows, drives nothing — the Stop test's fixture."""

    def __init__(self) -> None:
        self.batches: list[list[Any]] = []

    async def drive(self, *, envelope: Any) -> None:
        await self.drive_batch(envelopes=[envelope])

    async def drive_batch(self, *, envelopes: Any) -> None:
        self.batches.append(list(envelopes))


class _BatchLaneThatMustNotRun:
    async def drive(self, *, envelope: Any) -> None:
        raise AssertionError("a committed design turn must never be re-dispatched")

    async def drive_batch(self, *, envelopes: Any) -> None:
        raise AssertionError("a committed design turn must never be re-dispatched")


async def _add_documents(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    *,
    label: str,
    count: int,
    note: Any = None,
) -> list[str]:
    """Birth ``count`` scene documents and record them as this leg's set, positions 0..n-1."""

    workspace_id = seeds["workspace_id"]
    leg_id = str(seeds["leg"]["id"])
    document_ids: list[str] = []
    for position in range(count):
        document_id = f"doc_{label}_{position}_{uuid4().hex[:8]}"
        await create_document(
            conn,
            workspace_id=workspace_id,
            scene=engine_ad_scene(document_id=document_id, title=_TITLES[position]),
            doc_kind="scene",
        )
        document_ids.append(document_id)
    await design_legs.add_leg_documents(
        conn,
        workspace_id=workspace_id,
        leg_id=leg_id,
        documents=[
            LegDocumentSpec(
                document_id=document_id,
                position=position,
                note=f"note {position}" if note is None else note,
            )
            for position, document_id in enumerate(document_ids)
        ],
    )
    # The tool pins position 0 on the leg itself (``births[0].document_id``); the DAL seed
    # opens a document-less leg, so this reproduces the shipped shape.
    await conn.execute(
        text("UPDATE design_leg SET document_id = :doc WHERE id = :leg AND workspace_id = :ws"),
        {"doc": document_ids[0], "leg": leg_id, "ws": workspace_id},
    )
    seeds["document_ids"] = document_ids
    return document_ids


async def _seed_three_document_leg(
    conn: AsyncConnection, *, storage_root: Path, label: str
) -> dict[str, Any]:
    seeds = await _seed_leg_conversation(conn, storage_root=storage_root, label=label)
    await _add_documents(conn, seeds, label=label, count=3)
    return seeds


async def _fleet_design_tasks(conn: AsyncConnection) -> dict[str, str]:
    rows = (
        await conn.execute(
            text("SELECT work_id, status, dedup_key FROM fleet_task WHERE kind = 'design_job'")
        )
    ).all()
    for row in rows:
        assert str(row.dedup_key) == str(row.work_id)
    return {str(row.work_id): str(row.status) for row in rows}


def test_three_documents_dispatch_three_runs_and_hand_back_once(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="three")
            lane = _FakeBatchLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(conn, seeds, label="three", message="make them all")
            result = await _run_turn(conn, seeds, registry, lane, submission)
            turn_id = submission.turn_id
            expected_runs = [design_leg_run_id(turn_id, position) for position in range(3)]

            assert len(lane.batches) == 1
            assert lane.singles == []
            assert [envelope.run_id for envelope in lane.batches[0]] == expected_runs
            # position 0 keeps today's derivation
            assert design_leg_run_id(turn_id) == expected_runs[0]
            assert [str(e.document_id) for e in lane.batches[0]] == seeds["document_ids"]

            # each envelope names its own item and its own session
            second = lane.batches[0][1]
            artifact = second.config["delegation_bundle"]["artifact"]
            assert artifact["position"] == 1
            assert artifact["count"] == 3
            assert artifact["title"] == "Mercy ad"
            assert artifact["note"] == "note 1"
            assert second.checkpoint_thread_id != lane.batches[0][0].checkpoint_thread_id

            # three design_job tasks queued, one per run, in the run rows' own transaction
            tasks = await _fleet_design_tasks(conn)
            for run_id in expected_runs:
                assert tasks.get(str(design_runs.work_id_for_run(run_id))) == "queued"

            runs = await design_runs.runs_for_execution(
                conn,
                workspace_id=seeds["workspace_id"],
                execution_id=design_leg_execution_id(turn_id),
            )
            assert sorted(str(run["run_id"]) for run in runs) == sorted(expected_runs)
            stamped = (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT leg_id::text FROM design_agent_run "
                            "WHERE workspace_id = :ws AND execution_id = :e"
                        ),
                        {
                            "ws": seeds["workspace_id"],
                            "e": design_leg_execution_id(turn_id),
                        },
                    )
                )
                .scalars()
                .all()
            )
            assert list(stamped) == [str(seeds["leg"]["id"])]

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.assistant_message is not None
            assert result.assistant_message.count("saved") == 3
            assert result.assistant_message.splitlines()[0].startswith("Apollo ad: ")
            assert len(result.assistant_message.splitlines()) == 3

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(seeds["leg"]["id"])
            )
            assert leg["state"] == "open_awaiting_user"
            frames = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_turn_event_stream "
                        "WHERE turn_id = :t AND event_type = 'leg.awaiting_user'"
                    ),
                    {"t": turn_id},
                )
            ).scalar_one()
            assert frames == 1

    run_async(scenario())


def test_one_failed_run_still_hands_back_and_names_it(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="partial")
            submission = await _submit_message(
                conn, seeds, label="partial", message="make them all"
            )
            failed_run = design_leg_run_id(submission.turn_id, 1)
            lane = _FakeBatchLane(
                conn_factory=seeds["conn_factory"],
                status_for=lambda run_id: "failed" if run_id == failed_run else "succeeded",
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.assistant_message is not None
            lines = result.assistant_message.splitlines()
            assert len(lines) == 3
            assert lines[0].startswith("Apollo ad: ") and "saved" in lines[0]
            assert lines[1].startswith("Mercy ad: failed")
            assert "boom" in lines[1]
            assert lines[2].startswith("Vertex ad: ") and "saved" in lines[2]

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(seeds["leg"]["id"])
            )
            assert leg["state"] == "open_awaiting_user"

    run_async(scenario())


def test_all_failed_fails_the_turn_and_keeps_the_leg_open(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="allfail")
            lane = _FakeBatchLane(
                conn_factory=seeds["conn_factory"], status_for=lambda run_id: "failed"
            )
            submission = await _submit_message(
                conn, seeds, label="allfail", message="make them all"
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == DESIGN_LEG_TURN_FAILED
            assert result.assistant_message is None
            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(seeds["leg"]["id"])
            )
            assert leg["state"] == "open_awaiting_user"

    run_async(scenario())


def test_a_single_document_leg_still_dispatches_through_drive_and_enqueues_nothing(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="one")
            # The shipped pin path records its one document with an EMPTY note.
            document_ids = await _add_documents(conn, seeds, label="one", count=1, note="")
            lane = _FakeBatchLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(conn, seeds, label="one", message="make it")
            result = await _run_turn(conn, seeds, registry, lane, submission)

            run_id = design_leg_run_id(submission.turn_id)
            assert [envelope.run_id for envelope in lane.singles] == [run_id]
            envelope = lane.singles[0]
            assert str(envelope.document_id) == document_ids[0]
            # byte-identity: the shipped bundle carries no per-item key on a lone artifact
            assert "artifact" not in envelope.config["delegation_bundle"]
            tasks = await _fleet_design_tasks(conn)
            assert str(design_runs.work_id_for_run(run_id)) not in tasks
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.assistant_message is not None
            assert "\n" not in result.assistant_message
            assert not result.assistant_message.startswith("Apollo ad:")

    run_async(scenario())


def test_a_retried_batch_turn_rejoins_its_runs_and_creates_no_second_batch(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="retry")
            lane = _FakeBatchLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(conn, seeds, label="retry", message="make them")
            first = await _run_turn(conn, seeds, registry, lane, submission)
            assert first.replayed is False

            again = await _run_turn(conn, seeds, registry, _BatchLaneThatMustNotRun(), submission)
            assert again.replayed is True
            assert again.assistant_message == first.assistant_message

            rows = await design_runs.runs_for_execution(
                conn,
                workspace_id=seeds["workspace_id"],
                execution_id=design_leg_execution_id(submission.turn_id),
            )
            assert len(rows) == 3

    run_async(scenario())


def test_stop_requests_cancellation_on_every_non_terminal_run_of_the_batch(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="stop")
            lane = _LaneThatNeverTerminalizes()
            submission = await _submit_message(conn, seeds, label="stop", message="make them")
            # The lane returns with the runs still queued — the runner raises rather than
            # inventing a terminal result, which is exactly the mid-batch state Stop meets.
            with pytest.raises(RuntimeError):
                await _run_turn(conn, seeds, registry, lane, submission)

            runner = _runner(seeds, registry, lane)
            await runner.request_stop_for_turn(
                workspace_id=seeds["workspace_id"], turn_id=submission.turn_id
            )
            for position in range(3):
                run_id = design_leg_run_id(submission.turn_id, position)
                assert (
                    await design_runs.cancellation_requested(
                        conn, workspace_id=seeds["workspace_id"], run_id=run_id
                    )
                    is True
                )

    run_async(scenario())


def test_batch_summary_names_each_document_and_its_outcome() -> None:
    items = [
        (
            {"title": "Apollo ad", "position": 0},
            {
                "status": "succeeded",
                "result": {
                    "status": "proposed",
                    "acceptance_scope": "design",
                    "current_version": 3,
                },
            },
        ),
        (
            {"title": "Mercy ad", "position": 1},
            {
                "status": "failed",
                "result": {"status": "failed", "error": {"message": "boom"}},
            },
        ),
        (
            {"title": "Vertex ad", "position": 2},
            {
                "status": "succeeded",
                "result": {
                    "status": "proposed",
                    "acceptance_scope": "design",
                    "stop_reason": "cancelled_by_request",
                    "current_version": 2,
                },
            },
        ),
    ]
    lines = batch_summary(items).splitlines()
    assert lines[0].startswith("Apollo ad: Design saved and accepted")
    assert "version 3" in lines[0]
    assert lines[1].startswith("Mercy ad: failed")
    assert "boom" in lines[1]
    assert lines[2].startswith("Vertex ad: cancelled at your request")
    assert "version 2" in lines[2]


def test_the_summary_of_one_document_is_the_shipped_sentence() -> None:
    """N == 1 never goes through ``batch_summary`` — pinned here so the runner keeps that rule."""

    item = (
        {"title": "Apollo ad", "position": 0},
        {"status": "succeeded", "result": {"status": "proposed", "acceptance_scope": "design"}},
    )
    assert batch_summary([item]) == "Apollo ad: Design saved and accepted by the design review."
