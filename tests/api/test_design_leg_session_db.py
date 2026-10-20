"""Design session continuity — the leg turn's thread is the DOCUMENT's session (2026-09-18).

One design document = one persistent design-agent session (design note
``docs/superpowers/specs/archive/2026-09-18-design-session-continuity-design.md``). Four durable
consequences are pinned here, all on the real :class:`DesignLegTurnRunner` with a faked lane:

* **the envelope names the session** — a document-pinned leg turn's ``checkpoint_thread_id`` is
  ``design_session_id(workspace, document)``, so the design runtime resumes the thread it wrote
  last turn instead of opening a fresh graph beside it. A document-less leg has nothing to be
  continuous about and keeps the D5 run-as-thread.
* **the envelope says which turn this is** — ``config["leg"]["first_turn_of_leg"]`` is the design
  side's one read for "send the brief / do not re-send the history".
* **the run row stores the thread it was dispatched on** — the column is what an operator (and a
  resume) reads, so it must be the session, not the run.
* **a second leg turn on a driven document waits** (founder ruling 2026-09-18). With sessions this
  is a correctness rule: two turns continuing one LangGraph thread at once interleave their
  checkpoints.

All writes run in rolled-back transactions against the session-migrated DB — nothing is
committed, so a live lane worker can never claim the runs these tests create.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import AgentTurnSubmissionRow, message_artifact_ref
from clue_api.agent_turn_wiring import DbAgentHistoryStore, DbAgentTurnJournal
from clue_api.design_leg_wiring import DesignLegTurnRunner, design_leg_run_id
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.enums import DesignRunKind
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.sessions import design_session_id
from tests.api.test_p34_design_leg_engine_db import (
    _card_payload,
    _FakeLane,
    _LaneThatMustNotRun,
    _pin_document,
    _seed_leg_conversation,
    _submit_message,
    registry,  # noqa: F401 -- shared profile fixture
)
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401 -- DB fixture


def _runner(
    seeds: dict[str, Any],
    profiles: Any,
    lane: Any,
    **waits: float,
) -> DesignLegTurnRunner:
    return DesignLegTurnRunner(
        profiles=profiles,
        artifacts=seeds["artifacts"],
        turns=DbAgentTurnJournal(conn_factory=seeds["conn_factory"]),
        history=DbAgentHistoryStore(conn_factory=seeds["conn_factory"]),
        lane=lane,
        conn_factory=seeds["conn_factory"],
        **waits,
    )


async def _run_turn(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    runner: DesignLegTurnRunner,
    submission: AgentTurnSubmissionRow,
) -> Any:
    leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    assert leg is not None
    return await runner.run_leg_turn(
        submission=submission,
        leg=leg,
        user_message_ref=await message_artifact_ref(conn, submission),
        focus_refs=(),
        card_payload=_card_payload(seeds),
        stream=None,
    )


async def _insert_holding_run(
    conn: AsyncConnection, seeds: dict[str, Any], *, document_id: str
) -> str:
    """A foreign run of this workspace, ``running`` on ``document_id`` — the holder to wait on."""

    run_id = f"run_{uuid4().hex}"
    envelope = DesignTurnEnvelope(
        kind="agent_turn",
        work_id=design_runs.work_id_for_run(run_id),
        workspace_id=seeds["workspace_id"],
        run_id=run_id,
        checkpoint_thread_id=design_session_id(seeds["workspace_id"], document_id),
        document_id=document_id,
        config={"request": {"prompt": "An earlier turn, still designing.", "scene": {}}},
    )
    await design_runs.create_run(
        conn,
        workspace_id=seeds["workspace_id"],
        run_id=run_id,
        document_id=document_id,
        kind=DesignRunKind.AGENT_TURN,
        payload=envelope.model_dump(mode="json"),
        work_id=envelope.work_id,
        checkpoint_thread_id=envelope.checkpoint_thread_id,
    )
    await conn.execute(
        text(
            "UPDATE design_agent_run SET status = CAST('running' AS design_run_status)"
            " WHERE run_id = :r AND workspace_id = :w"
        ),
        {"r": run_id, "w": seeds["workspace_id"]},
    )
    return run_id


def test_a_pinned_leg_turn_names_the_document_session_as_its_thread(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
) -> None:
    """The turn continues the DOCUMENT's session, and says it is the leg's first turn."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="session")
            document = await _pin_document(conn, seeds, doc_kind="scene", version=2)
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn, seeds, label="session", message="Make the headline two lines."
            )
            await _run_turn(conn, seeds, _runner(seeds, registry, lane), submission)

            envelope = lane.envelopes[0]
            assert envelope.checkpoint_thread_id == design_session_id(
                seeds["workspace_id"], document["id"]
            )
            assert envelope.checkpoint_thread_id != envelope.run_id
            assert envelope.config["leg"]["first_turn_of_leg"] is True

    run_async(scenario())


def test_a_later_turn_on_the_leg_is_not_the_first(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
) -> None:
    """Second message, same leg, same session — the brief is not re-sent."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="second")
            document = await _pin_document(conn, seeds, doc_kind="scene", version=2)
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            first = await _submit_message(conn, seeds, label="second1", message="Bolder.")
            await _run_turn(conn, seeds, _runner(seeds, registry, lane), first)
            second = await _submit_message(conn, seeds, label="second2", message="Now try navy.")
            await _run_turn(conn, seeds, _runner(seeds, registry, lane), second)

            assert lane.envelopes[1].config["leg"]["first_turn_of_leg"] is False
            # Same document, same session: the two turns continue ONE thread.
            assert lane.envelopes[1].checkpoint_thread_id == lane.envelopes[0].checkpoint_thread_id
            assert lane.envelopes[1].checkpoint_thread_id == design_session_id(
                seeds["workspace_id"], document["id"]
            )

    run_async(scenario())


def test_a_document_less_leg_keeps_the_run_id_as_its_thread(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
) -> None:
    """Nothing to be continuous about: the D5 run-as-thread stands, byte for byte."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="nodoc")
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(conn, seeds, label="nodoc", message="Bolder.")
            await _run_turn(conn, seeds, _runner(seeds, registry, lane), submission)

            envelope = lane.envelopes[0]
            assert envelope.checkpoint_thread_id == envelope.run_id
            assert envelope.checkpoint_thread_id == design_leg_run_id(submission.turn_id)

    run_async(scenario())


def test_dispatch_stores_the_session_thread_on_the_run_row(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
) -> None:
    """The column an operator and a resume read must be the session, not the run."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="runrow")
            document = await _pin_document(conn, seeds, doc_kind="scene", version=1)
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(conn, seeds, label="runrow", message="Warmer.")
            await _run_turn(conn, seeds, _runner(seeds, registry, lane), submission)

            stored = (
                await conn.execute(
                    text(
                        "SELECT checkpoint_thread_id FROM design_agent_run"
                        " WHERE run_id = :r AND workspace_id = :w"
                    ),
                    {"r": design_leg_run_id(submission.turn_id), "w": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert stored == design_session_id(seeds["workspace_id"], document["id"])

    run_async(scenario())


def test_dispatch_refuses_to_drive_while_another_run_holds_the_document(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
) -> None:
    """A holder that never finishes: the turn waits out its window and fails, never driving."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="held")
            document = await _pin_document(conn, seeds, doc_kind="scene", version=1)
            await _insert_holding_run(conn, seeds, document_id=document["id"])
            submission = await _submit_message(conn, seeds, label="held", message="Try navy.")
            runner = _runner(
                seeds,
                registry,
                _LaneThatMustNotRun(),
                document_wait_poll_s=0.01,
                document_wait_timeout_s=0.05,
            )
            with pytest.raises(RuntimeError, match="held this document past the wait window"):
                await _run_turn(conn, seeds, runner, submission)

    run_async(scenario())


def test_dispatch_drives_once_the_holding_run_goes_terminal(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wait lifts by itself: the holder goes terminal and the queued turn drives, once.

    The holder is released from INSIDE the waiting task's own probe — one connection, one task,
    no cross-task race on the rolled-back transaction — and the lane records how many probes had
    already run when it was finally handed the envelope.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="release")
            document = await _pin_document(conn, seeds, doc_kind="scene", version=1)
            holder = await _insert_holding_run(conn, seeds, document_id=document["id"])
            submission = await _submit_message(conn, seeds, label="release", message="Try navy.")

            probes: list[str] = []
            real = design_runs.active_run_for_document

            async def probe(
                probe_conn: AsyncConnection, *, workspace_id: str, document_id: str
            ) -> str | None:
                probes.append(document_id)
                if len(probes) == 3:
                    await probe_conn.execute(
                        text(
                            "UPDATE design_agent_run"
                            " SET status = CAST('succeeded' AS design_run_status)"
                            " WHERE run_id = :r AND workspace_id = :w"
                        ),
                        {"r": holder, "w": seeds["workspace_id"]},
                    )
                return await real(probe_conn, workspace_id=workspace_id, document_id=document_id)

            monkeypatch.setattr(design_runs, "active_run_for_document", probe)

            class _CountingLane(_FakeLane):
                probes_at_drive: int | None = None

                async def drive(self, *, envelope: Any) -> None:
                    self.probes_at_drive = len(probes)
                    await super().drive(envelope=envelope)

            lane = _CountingLane(conn_factory=seeds["conn_factory"])
            runner = _runner(
                seeds,
                registry,
                lane,
                document_wait_poll_s=0.01,
                document_wait_timeout_s=5.0,
            )
            await _run_turn(conn, seeds, runner, submission)

            # It polled, waited, and drove exactly once — on the probe that saw the holder gone.
            assert lane.probes_at_drive == 3
            assert [envelope.run_id for envelope in lane.envelopes] == [
                design_leg_run_id(submission.turn_id)
            ]

    run_async(scenario())
