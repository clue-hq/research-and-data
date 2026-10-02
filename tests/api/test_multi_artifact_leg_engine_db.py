"""Spec §3.3/§3.9 — one leg turn, many documents: fan out, join, summarise, stop.

A leg with three documents dispatches three design runs (one per document, each with its own
derived run id, its own session thread and its own item line on the brief) plus three
``design_job`` fleet tasks in ONE transaction, drives them through ``drive_batch``, records
receipts for all of them and hands back ONCE with a per-document summary. A partial failure
still hands back; a total failure fails the turn and leaves the leg open; a retry re-joins
without creating a second batch; Stop asks every non-terminal run of the batch to cancel.

A ONE-document leg keeps the shipped path byte-for-byte: ``lane.drive`` (never
``drive_batch``), no fleet task, position-0 run id, ``_assistant_summary`` as the message.

§3.5 rides the same seeds: the exit judge is shown the leg's artifacts NUMBERED, a staying
verdict that addresses artifact 2 dispatches that document alone, and a verdict that asks a
clarifying question dispatches nothing at all.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentExecutionStatus, DomainObjectRef
from clue_api.design_leg_wiring import (
    DESIGN_LEG_TURN_FAILED,
    _exit_judge_artifact_lines,
    _exit_judge_tag_lines,
    batch_summary,
    design_leg_execution_id,
    design_leg_run_id,
)
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import create_document
from clue_design.exit_judgment import ExitJudgment
from clue_design.legs import LegDocumentSpec
from tests.api.test_genad_leg_document_birth_db import engine_ad_scene
from tests.api.test_p34_design_leg_engine_db import (
    _card_payload,
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


# --- §3.5: the exit judge addresses documents, or asks -----------------------------------------


class _CannedJudge:
    """Returns one fixed verdict and records the numbered artifacts it was shown."""

    def __init__(self, judgment: Any) -> None:
        self._judgment = judgment
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        *,
        brief: str,
        history: tuple[tuple[str, str], ...],
        message: str,
        artifacts: tuple[str, ...] = (),
        artifact: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> Any:
        self.calls.append({"artifacts": artifacts, "tags": tags, "message": message})
        return self._judgment


async def _run_judged_turn(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    profiles: Any,
    lane: Any,
    submission: Any,
    *,
    judge: Any,
    storage_root: Path,
) -> Any:
    """``_run_turn`` with the exit bridge composed — the judge AND the real journaled
    finisher, since a judge without a finisher is treated as absent (P3.7)."""

    from clue_api.agent_turn_submission import message_artifact_ref
    from clue_api.agent_turn_wiring import DbAgentHistoryStore, DbAgentTurnJournal
    from clue_api.design_leg_wiring import DesignLegTurnRunner
    from tests.api.test_p37_exit_bridge_db import _finisher

    leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    assert leg is not None
    runner = DesignLegTurnRunner(
        profiles=profiles,
        artifacts=seeds["artifacts"],
        turns=DbAgentTurnJournal(conn_factory=seeds["conn_factory"]),
        history=DbAgentHistoryStore(conn_factory=seeds["conn_factory"]),
        lane=lane,
        exit_judge=judge,
        finisher=_finisher(seeds, storage_root),
        conn_factory=seeds["conn_factory"],
    )
    return await runner.run_leg_turn(
        submission=submission,
        leg=leg,
        user_message_ref=await message_artifact_ref(conn, submission),
        focus_refs=(),
        card_payload=_card_payload(seeds),
        stream=None,
    )


def test_an_addressed_subset_dispatches_only_those_documents(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    """§3.5: a follow-up the judge addresses to artifact 2 drives ONE run — the second
    document's — and the hand-back names only that title. The other two are untouched."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="addr")
            lane = _FakeBatchLane(conn_factory=seeds["conn_factory"])
            judge = _CannedJudge(
                ExitJudgment(
                    close_this_session=False,
                    addressed_artifacts=[2],
                    reasoning="only the Mercy ad is named",
                )
            )
            submission = await _submit_message(
                conn, seeds, label="addr", message="the Mercy one needs a softer palette"
            )
            result = await _run_judged_turn(
                conn, seeds, registry, lane, submission, judge=judge, storage_root=tmp_path
            )

            # the judge saw all three, numbered and in position order
            assert [line.split(".")[0] for line in judge.calls[0]["artifacts"]] == ["1", "2", "3"]
            assert '"Mercy ad" (scene ad)' in judge.calls[0]["artifacts"][1]

            # exactly one envelope, for position 1, on the second document
            assert len(lane.batches) == 1
            assert [envelope.run_id for envelope in lane.batches[0]] == [
                design_leg_run_id(submission.turn_id, 1)
            ]
            assert [str(e.document_id) for e in lane.batches[0]] == [seeds["document_ids"][1]]
            artifact = lane.batches[0][0].config["delegation_bundle"]["artifact"]
            assert artifact["position"] == 1
            # the leg's size is what the brief states, not the addressed subset's
            assert artifact["count"] == 3

            # one run row, for that document only
            runs = await design_runs.runs_for_execution(
                conn,
                workspace_id=seeds["workspace_id"],
                execution_id=design_leg_execution_id(submission.turn_id),
            )
            assert [str(run["run_id"]) for run in runs] == [
                design_leg_run_id(submission.turn_id, 1)
            ]
            # Narrowed to ONE, the turn is a one-document turn in every respect: the
            # shipped single-run seam drives it and nothing is offered to the fleet.
            assert [envelope.run_id for envelope in lane.singles] == [
                design_leg_run_id(submission.turn_id, 1)
            ]
            tasks = await _fleet_design_tasks(conn)
            for position in range(3):
                work_id = str(
                    design_runs.work_id_for_run(design_leg_run_id(submission.turn_id, position))
                )
                assert work_id not in tasks

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.assistant_message is not None
            assert "Apollo ad" not in result.assistant_message
            assert "Vertex ad" not in result.assistant_message
            # N == 1 after narrowing: the shipped single-document sentence, not a batch list
            assert "\n" not in result.assistant_message

    run_async(scenario())


def test_a_clarifying_question_dispatches_nothing_and_asks_the_user(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    """§3.5's ask: no run rows, no fleet tasks, no design spend. The turn ends
    AWAITING_INPUT with the question as its assistant message and the leg still open, so
    the user's answer is simply the next message on it."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="ask")
            question = "Which design's logo — Apollo, Mercy, Vertex, or all three?"
            judge = _CannedJudge(
                ExitJudgment(
                    close_this_session=False,
                    clarifying_question=question,
                    reasoning="could be any of the three",
                )
            )
            submission = await _submit_message(
                conn, seeds, label="ask", message="the logo is too small"
            )
            result = await _run_judged_turn(
                conn,
                seeds,
                registry,
                _BatchLaneThatMustNotRun(),
                submission,
                judge=judge,
                storage_root=tmp_path,
            )

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.assistant_message == question

            runs = await design_runs.runs_for_execution(
                conn,
                workspace_id=seeds["workspace_id"],
                execution_id=design_leg_execution_id(submission.turn_id),
            )
            assert runs == []
            tasks = await _fleet_design_tasks(conn)
            for position in range(3):
                assert (
                    str(
                        design_runs.work_id_for_run(design_leg_run_id(submission.turn_id, position))
                    )
                    not in tasks
                )

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(seeds["leg"]["id"])
            )
            assert leg["state"] == "open_awaiting_user"
            assert leg["close_reason"] is None

    run_async(scenario())


def test_a_tagged_leg_document_is_marked_with_its_artifact_number(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    """The tag block's number IS the address the judge answers in (§3.5/§3.7)."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="tagnum")
            documents = [
                dict(row)
                for row in await design_legs.list_leg_documents(
                    conn,
                    workspace_id=seeds["workspace_id"],
                    leg_id=str(seeds["leg"]["id"]),
                )
            ]
            lines = await _exit_judge_tag_lines(
                conn,
                workspace_id=seeds["workspace_id"],
                focus_refs=(
                    DomainObjectRef(
                        workspace_id=seeds["workspace_id"],
                        object_type="design_document",
                        object_id=seeds["document_ids"][1],
                        version=None,
                    ),
                ),
                leg_documents=documents,
            )
            assert lines == ('design "Mercy ad" (scene ad) (artifact 2)',)

            # The numbered lines the judge is shown, from the same document set.
            assert await _exit_judge_artifact_lines(
                conn, workspace_id=seeds["workspace_id"], leg_documents=documents
            ) == (
                '1. "Apollo ad" (scene ad)',
                '2. "Mercy ad" (scene ad)',
                '3. "Vertex ad" (scene ad)',
            )

            # Spec 2026-09-20 §2.5: the artifact that stopped to ask carries its open question,
            # so a bare answer ("the 40% stat") reads as work on THAT one. Only that line
            # changes — an artifact with no open question is untouched.
            mercy = seeds["document_ids"][1]
            run_id = str(uuid5(NAMESPACE_URL, f"p34e:tagnum:asked:{mercy}"))
            await design_runs.create_run(
                conn,
                workspace_id=seeds["workspace_id"],
                run_id=run_id,
                document_id=mercy,
                payload={"document_id": mercy},
            )
            await design_runs.set_run_result(
                conn,
                workspace_id=seeds["workspace_id"],
                run_id=run_id,
                status="succeeded",
                result={
                    "status": "clarification_requested",
                    "clarification": {
                        "questions": [
                            {
                                "id": "proof",
                                "question": "Which proof point should lead the ad?",
                                "default": "The 40% stat",
                            }
                        ]
                    },
                },
            )
            assert await _exit_judge_artifact_lines(
                conn, workspace_id=seeds["workspace_id"], leg_documents=documents
            ) == (
                '1. "Apollo ad" (scene ad)',
                '2. "Mercy ad" (scene ad) [asked: "Which proof point should lead the ad?"]',
                '3. "Vertex ad" (scene ad)',
            )

    run_async(scenario())


def test_a_stopped_design_turn_hands_the_leg_back(
    tmp_path: Path,
    registry: Any,  # noqa: F811
    migrated_db: bool,  # noqa: F811
) -> None:
    """Stop must free the thread, exactly as a crash does (live incident 2026-09-29).

    The Stop path cancelled the turn and its runs but left the leg ``running``: the chat kept
    saying "Agent is designing", queued every later message and Stop had nothing left to stop.
    """
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_three_document_leg(conn, storage_root=tmp_path, label="stopped")
            submission = await _submit_message(conn, seeds, label="stopped", message="make them")
            leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
            )
            assert leg is not None
            await design_legs.mark_leg_running(
                conn, workspace_id=seeds["workspace_id"], leg_id=leg["id"]
            )

            runner = _runner(seeds, registry, _LaneThatNeverTerminalizes())
            await runner.request_stop_for_turn(
                workspace_id=seeds["workspace_id"], turn_id=submission.turn_id
            )
            await runner.await_stopped_turn(
                workspace_id=seeds["workspace_id"], turn_id=submission.turn_id
            )

            after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=leg["id"]
            )
            assert after["state"] == "open_awaiting_user"
            announced = await conn.scalar(
                text(
                    "SELECT count(*) FROM agent_turn_event_stream "
                    "WHERE workspace_id=:ws AND turn_id=:turn AND event_type='leg.awaiting_user'"
                ),
                {"ws": seeds["workspace_id"], "turn": submission.turn_id},
            )
            assert announced == 1

    run_async(scenario())
