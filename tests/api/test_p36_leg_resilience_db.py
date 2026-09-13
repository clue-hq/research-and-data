"""P3.6 — the leg resilience battery (PD-part3 §4; master plan §3-III gate paragraph).

What this suite pins, on durable rows against the riyadh Postgres:

* **mid-leg worker restart** — a brand-new worker (every in-memory component rebuilt)
  resumes the leg with full context: prior exchanges in the next envelope, the pinned
  document's scene re-read from durable state, the same leg row;
* **mid-turn worker kill, both windows** — a worker that dies AFTER the design work landed
  (run terminal, turn unfinalized) and one that dies BEFORE it (run row queued, lane never
  completed): a fresh worker converges both — re-join in the first, re-drive of the same
  derived run in the second — with the history landing exactly once and the leg
  self-healing ``running`` → ``open_awaiting_user`` (the P3.4 review's pinned residual);
* **per-thread single-flight** — one in-flight ``agent_turn`` task per thread work id and
  FIFO next-pending dispatch (the umbrella that makes the leg state machine's guarded
  transitions sufficient), plus work-lease exclusivity on the same id;
* **cross-thread concurrency** — two legs on two threads run design turns genuinely
  simultaneously (a barrier proves both are in flight at once) with zero cross-talk;
* **the queued-race gate answer** (Part-III review finding C, worker half) — a gate answer
  accepted while no leg was open but *executed* after a leg opened is delivered to
  head-of-abm, never to the design agent.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentExecutionStatus
from clue_api.agent_gate import (
    DEFAULT_GATE_CURRENCY,
    KIND_DIRECTIVE_CONFIRMATION,
    insert_gate,
    insert_gate_answer,
)
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_fleet_wiring import ProjectConversationTurnRunner
from clue_api.agent_turn_submission import (
    AGENT_TURN_DEDUP_PREFIX,
    dispatch_next_thread_turn,
    thread_work_id,
)
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.design_leg_wiring import (
    DesignLegTurnRunner,
    design_leg_run_id,
    load_design_leg_history,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_action import derive_turn_action_ref
from clue_db import db_lifespan
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import create_document
from clue_fleet import WorkId, acquire_work_lease
from clue_storage import FsStorage
from tests.api.conftest import hermetic_flag_env
from tests.api.test_p34_design_leg_engine_db import (
    USER_ID,
    _card_payload,
    _FakeLane,
    _seed_leg_conversation,
    _submit_message,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

NOW_UTC = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)


class _WorkerDeath(BaseException):
    """Raised where the simulated worker dies. A ``BaseException`` on purpose so ordinary
    ``except Exception`` handlers cannot swallow it. Since the containment fix the runner's
    ``BaseException`` armor DOES run (mark-abandoned + terminal frame, then re-raise) — so
    these tests now prove the stronger property: convergence holds from the crash state
    WITH containment's writes present, and a true process death (no handler at all) leaves
    strictly less state, which the same derived-id retry machinery covers."""


class _DiesAfterCompletingRun:
    """The design work lands (run terminal), then the worker dies before finalizing."""

    def __init__(self, *, conn_factory: Any) -> None:
        self._conn_factory = conn_factory

    async def drive(self, *, envelope: Any) -> None:
        async with self._conn_factory() as conn:
            await design_runs.set_run_result(
                conn,
                workspace_id=envelope.workspace_id,
                run_id=envelope.run_id,
                status="succeeded",
                result={
                    "schema_version": 1,
                    "status": "accepted",
                    "stop_reason": "Visual reviewer accepted the artboard.",
                },
            )
        raise _WorkerDeath


class _DiesBeforeWork:
    """The worker dies after dispatch created the run row but before any design work."""

    async def drive(self, *, envelope: Any) -> None:
        raise _WorkerDeath


class _LaneThatMustNotRun:
    async def drive(self, *, envelope: Any) -> None:
        raise AssertionError("this turn must converge without re-driving the design lane")


class _BarrierLane:
    """Completes the run only once the OTHER thread's turn is also in flight — the proof
    the two design turns genuinely overlap rather than serializing behind a shared lock."""

    def __init__(
        self,
        *,
        conn_factory: Any,
        mine: asyncio.Event,
        other: asyncio.Event,
        stop_reason: str,
    ) -> None:
        self._conn_factory = conn_factory
        self._mine = mine
        self._other = other
        self._stop_reason = stop_reason

    async def drive(self, *, envelope: Any) -> None:
        self._mine.set()
        await asyncio.wait_for(self._other.wait(), timeout=10.0)
        async with self._conn_factory() as conn:
            await design_runs.set_run_result(
                conn,
                workspace_id=envelope.workspace_id,
                run_id=envelope.run_id,
                status="succeeded",
                result={
                    "schema_version": 1,
                    "status": "accepted",
                    "stop_reason": self._stop_reason,
                },
            )


def _fresh_worker_components(seeds: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    """Everything a worker process holds in memory, rebuilt from nothing but durable state:
    a new artifact store over the same storage root, new journal/history stores, a new
    profile registry. This IS the 'another worker' of the master-plan resumability test."""

    conn_factory = seeds["conn_factory"]
    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    return {
        "registry": registry,
        "artifacts": DurableAgentArtifactStore(
            storage=FsStorage(storage_root / "artifacts"),
            conn_factory=conn_factory,
        ),
        "turns": DbAgentTurnJournal(conn_factory=conn_factory),
        "history": DbAgentHistoryStore(conn_factory=conn_factory),
    }


def _fresh_runner(seeds: dict[str, Any], storage_root: Path, lane: Any) -> DesignLegTurnRunner:
    components = _fresh_worker_components(seeds, storage_root)
    return DesignLegTurnRunner(
        profiles=components["registry"],
        artifacts=components["artifacts"],
        turns=components["turns"],
        history=components["history"],
        lane=lane,
        conn_factory=seeds["conn_factory"],
    )


async def _run_on(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    runner: DesignLegTurnRunner,
    submission: Any,
) -> Any:
    from clue_api.agent_turn_submission import message_artifact_ref

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


async def _history_roles(conn: AsyncConnection, seeds: dict[str, Any]) -> list[str]:
    return list(
        (
            await conn.execute(
                text(
                    "SELECT role FROM agent_thread_message "
                    "WHERE workspace_id = :ws AND thread_id = :thread ORDER BY sequence"
                ),
                {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
            )
        ).scalars()
    )


def test_cancelled_design_lane_leaves_terminal_journaling_to_stop_owner(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="cancel")
            submission = await _submit_message(
                conn, seeds, label="cancel-1", message="Create a draft."
            )
            entered = asyncio.Event()

            class WaitingLane:
                async def drive(self, *, envelope: Any) -> None:
                    entered.set()
                    await asyncio.Event().wait()

            task = asyncio.create_task(
                _run_on(conn, seeds, _fresh_runner(seeds, tmp_path, WaitingLane()), submission)
            )
            await asyncio.wait_for(entered.wait(), timeout=10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            terminal_rows = (
                await conn.execute(
                    text(
                        "SELECT status, reason_code FROM agent_turn_event "
                        "WHERE turn_id=:turn AND status IN ('failed', 'abandoned', 'cancelled')"
                    ),
                    {"turn": submission.turn_id},
                )
            ).all()
            # A premature crash event closes the SSE before the outer Stop
            # owner can emit the actual cancellation. No terminal belongs here.
            assert terminal_rows == []
            run = await design_runs.get_run(
                conn,
                workspace_id=seeds["workspace_id"],
                run_id=design_leg_run_id(submission.turn_id),
            )
            assert run is not None and run["status"] == "queued"
            assert run["result"] is None

    run_async(scenario())


# --- mid-leg worker restart (the master-plan gate's 'survives a mid-leg worker restart') -------


def test_a_mid_leg_worker_restart_resumes_the_leg_with_context_intact(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Turn 1 on worker A; worker A is discarded wholesale; worker B — rebuilt from durable
    state alone — runs turn 2 and the leg continues: prior exchange in the envelope, the
    pinned document's scene re-read, the same leg row, zero lost context."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="restart")
            document = await create_document(
                conn,
                workspace_id=seeds["workspace_id"],
                scene={"meta": {"id": "doc_p36_restart", "title": "Restart artboard"}},
            )
            await conn.execute(
                text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
                {"doc": document["id"], "leg": seeds["leg"]["id"]},
            )

            first = await _submit_message(
                conn, seeds, label="restart-1", message="Make the headline bolder."
            )
            worker_a = _fresh_runner(seeds, tmp_path, _FakeLane(conn_factory=seeds["conn_factory"]))
            result_a = await _run_on(conn, seeds, worker_a, first)
            assert result_a.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            del worker_a  # the restart: nothing in-memory survives

            second = await _submit_message(
                conn, seeds, label="restart-2", message="Now try it on navy."
            )
            lane_b = _FakeLane(conn_factory=seeds["conn_factory"])
            worker_b = _fresh_runner(seeds, tmp_path, lane_b)
            result_b = await _run_on(conn, seeds, worker_b, second)
            assert result_b.outcome.status is AgentExecutionStatus.AWAITING_INPUT

            envelope = lane_b.envelopes[0]
            assert [(item["role"], item["text"]) for item in envelope.config["history"]] == [
                ("user", "Make the headline bolder."),
                ("assistant", result_a.assistant_message),
            ]
            assert envelope.config["request"]["scene"] == {
                "meta": {"id": document["id"], "title": "Restart artboard"}
            }
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"
            leg_history = await load_design_leg_history(
                seeds["conn_factory"],
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                leg_parent_execution_id=leg_after["parent_execution_id"],
            )
            assert [item.role for item in leg_history] == ["user", "assistant"] * 2

    run_async(scenario())


# --- mid-turn worker kill: both crash windows --------------------------------------------------


def test_a_worker_killed_after_the_design_work_landed_converges_on_a_fresh_worker(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The wider crash window: run terminal, turn unfinalized, leg stuck ``running``. The
    retry re-joins the terminal run (never re-drives), finalizes with the run's own stop
    reason, lands the history exactly once, and self-heals the leg."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="killafter")
            submission = await _submit_message(
                conn, seeds, label="killafter-1", message="Punch up the logo."
            )
            dying = _fresh_runner(
                seeds, tmp_path, _DiesAfterCompletingRun(conn_factory=seeds["conn_factory"])
            )
            with pytest.raises(_WorkerDeath):
                await _run_on(conn, seeds, dying, submission)

            # The crash state, exactly: terminal run, no assistant message, leg 'running'.
            run = await design_runs.get_run(
                conn,
                workspace_id=seeds["workspace_id"],
                run_id=design_leg_run_id(submission.turn_id),
            )
            assert run is not None and run["status"] == "succeeded"
            assert await _history_roles(conn, seeds) == ["user"]
            mid = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert mid["state"] == "running"

            retry = await _run_on(
                conn, seeds, _fresh_runner(seeds, tmp_path, _LaneThatMustNotRun()), submission
            )
            assert retry.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert retry.replayed is False
            assert retry.assistant_message == (
                "Design turn accepted: Visual reviewer accepted the artboard."
            )
            assert await _history_roles(conn, seeds) == ["user", "assistant"]
            healed = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert healed["state"] == "open_awaiting_user"

    run_async(scenario())


def test_a_worker_killed_before_the_design_work_landed_redrives_the_same_run(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The earlier window: the run row exists (queued) but the lane never completed it. The
    retry re-drives the SAME derived run to terminal — one run identity per turn, ever."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="killbefore")
            submission = await _submit_message(
                conn, seeds, label="killbefore-1", message="Try a serif face."
            )
            with pytest.raises(_WorkerDeath):
                await _run_on(
                    conn, seeds, _fresh_runner(seeds, tmp_path, _DiesBeforeWork()), submission
                )
            run_id = design_leg_run_id(submission.turn_id)
            run = await design_runs.get_run(conn, workspace_id=seeds["workspace_id"], run_id=run_id)
            assert run is not None and run["status"] == "queued"

            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            retry = await _run_on(conn, seeds, _fresh_runner(seeds, tmp_path, lane), submission)
            assert retry.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert [envelope.run_id for envelope in lane.envelopes] == [run_id]
            # MED-4 (adversarial-review fix): the retry's rebuilt envelope must equal the
            # FROZEN payload attempt 1 stored — the run row's re-offer contract. It used to
            # drift: the retry's prior-history load swept in this turn's OWN user message
            # (appended durably by attempt 1), so the design agent saw the message twice and
            # the judge's input changed across attempts.
            stored_payload = (
                await conn.execute(
                    text(
                        "SELECT payload FROM design_agent_run "
                        "WHERE workspace_id = :ws AND run_id = :run"
                    ),
                    {"ws": seeds["workspace_id"], "run": run_id},
                )
            ).scalar_one()
            assert lane.envelopes[0].model_dump(mode="json") == stored_payload
            assert await _history_roles(conn, seeds) == ["user", "assistant"]
            runs_for_leg = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM design_agent_run "
                        "WHERE workspace_id = :ws AND leg_id = CAST(:leg AS uuid)"
                    ),
                    {"ws": seeds["workspace_id"], "leg": seeds["leg"]["id"]},
                )
            ).scalar_one()
            assert int(runs_for_leg) == 1

    run_async(scenario())


class _DiesOnFinalizeCommit:
    """The real journal, except the first ``commit_finalization_authority`` is a process
    death — the exact window between the finalization record and its commit."""

    def __init__(self, inner: DbAgentTurnJournal) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def commit_finalization_authority(self, **kwargs: Any) -> Any:
        raise _WorkerDeath


def test_a_worker_killed_between_finalize_record_and_commit_converges(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Adversarial-review fix: the finalize envelope must be REPLAY-STABLE. The
    finalization id is derived, so the envelope's every immutable field must also be
    derived from durable state — a wall-clock ``finalized_at`` made the retry's envelope
    differ and ``record_finalization`` raise 'different immutable envelope' forever,
    sticking the turn in ``running``. With ``submission.requested_at`` (the head-of-abm
    precedent) the retry re-records the identical envelope and converges."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="finpoison")
            submission = await _submit_message(
                conn, seeds, label="finpoison-1", message="Bolder headline."
            )
            components = _fresh_worker_components(seeds, tmp_path)
            dying = DesignLegTurnRunner(
                profiles=components["registry"],
                artifacts=components["artifacts"],
                turns=_DiesOnFinalizeCommit(components["turns"]),  # type: ignore[arg-type]
                history=components["history"],
                lane=_FakeLane(conn_factory=seeds["conn_factory"]),
                conn_factory=seeds["conn_factory"],
            )
            with pytest.raises(_WorkerDeath):
                await _run_on(conn, seeds, dying, submission)

            # The crash state: finalization RECORDED but not committed, run terminal.
            retry = await _run_on(
                conn, seeds, _fresh_runner(seeds, tmp_path, _LaneThatMustNotRun()), submission
            )
            assert retry.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert await _history_roles(conn, seeds) == ["user", "assistant"]

    run_async(scenario())


# --- per-thread single-flight ------------------------------------------------------------------


def test_per_thread_single_flight_holds_at_the_fleet_seam(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The D4 umbrella, pinned where it is enforced: one in-flight ``agent_turn`` task per
    thread work id (the second dispatch offers nothing until the first is terminal, then
    offers the next submission FIFO), and one live work lease per that same id."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="oneflight")
            first = await _submit_message(
                conn, seeds, label="oneflight-1", message="Bolder headline."
            )
            second = await _submit_message(
                conn, seeds, label="oneflight-2", message="And a navy background."
            )
            workspace_id = seeds["workspace_id"]
            thread_id = seeds["thread_id"]

            offered = await dispatch_next_thread_turn(
                conn, workspace_id=workspace_id, thread_id=thread_id
            )
            assert offered == first.turn_id  # FIFO: the earlier submission goes first
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=workspace_id, thread_id=thread_id
                )
                is None
            )  # single-flight: an in-flight task means nothing else is offered

            # The execution side of the same guarantee: one live lease per thread work id.
            work_id = thread_work_id(workspace_id=workspace_id, thread_id=thread_id)
            held = await acquire_work_lease(conn, work_id=WorkId(work_id), worker_id="worker-a")
            assert held is not None
            assert (
                await acquire_work_lease(conn, work_id=WorkId(work_id), worker_id="worker-b")
                is None
            )

            # The first turn reaches a terminal task state -> the NEXT submission is offered.
            await conn.execute(
                text(
                    "UPDATE fleet_task SET status = 'done' "
                    "WHERE kind = CAST('agent_turn' AS fleet_task_kind) "
                    "AND work_id = :work AND dedup_key = :dedup"
                ),
                {"work": work_id, "dedup": f"{AGENT_TURN_DEDUP_PREFIX}{first.turn_id}"},
            )
            await conn.execute(
                text("DELETE FROM work_lease WHERE work_id = :work"), {"work": work_id}
            )
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=workspace_id, thread_id=thread_id
                )
                == second.turn_id
            )

    run_async(scenario())


# --- cross-thread concurrency ------------------------------------------------------------------


def test_two_threads_design_concurrently_without_cross_talk(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """D4's other half: concurrency is thread-parallelism. Two legs on two threads run
    design turns at the same time — a barrier makes both be mid-flight simultaneously, so
    serialization would deadlock the test — and neither leaks into the other's history."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        # Two conversations on two REAL connections (their own uncommitted transactions), so
        # the design turns can genuinely overlap. ``rollback_conn`` owns ``db_lifespan`` and
        # cannot nest, hence the manual pair; distinct user ids keep the two transactions
        # from blocking on a shared ``platform_user`` insert.
        async with db_lifespan() as engine:
            conn_a = await engine.connect()
            trans_a = await conn_a.begin()
            conn_b = await engine.connect()
            trans_b = await conn_b.begin()
            try:
                await _parallel_scenario(conn_a, conn_b)
            finally:
                await trans_a.rollback()
                await conn_a.close()
                await trans_b.rollback()
                await conn_b.close()

    async def _parallel_scenario(conn_a: AsyncConnection, conn_b: AsyncConnection) -> None:
        seeds_a = await _seed_leg_conversation(
            conn_a, storage_root=tmp_path, label="para", user_id="usr_p36_para"
        )
        seeds_b = await _seed_leg_conversation(
            conn_b, storage_root=tmp_path, label="parb", user_id="usr_p36_parb"
        )
        sub_a = await _submit_message(
            conn_a, seeds_a, label="par-a1", message="Thread A: bolder headline."
        )
        sub_b = await _submit_message(
            conn_b, seeds_b, label="par-b1", message="Thread B: warmer palette."
        )
        started_a, started_b = asyncio.Event(), asyncio.Event()
        runner_a = _fresh_runner(
            seeds_a,
            tmp_path,
            _BarrierLane(
                conn_factory=seeds_a["conn_factory"],
                mine=started_a,
                other=started_b,
                stop_reason="Thread A proposal ready.",
            ),
        )
        runner_b = _fresh_runner(
            seeds_b,
            tmp_path,
            _BarrierLane(
                conn_factory=seeds_b["conn_factory"],
                mine=started_b,
                other=started_a,
                stop_reason="Thread B proposal ready.",
            ),
        )
        result_a, result_b = await asyncio.wait_for(
            asyncio.gather(
                _run_on(conn_a, seeds_a, runner_a, sub_a),
                _run_on(conn_b, seeds_b, runner_b, sub_b),
            ),
            timeout=30.0,
        )
        assert result_a.outcome.status is AgentExecutionStatus.AWAITING_INPUT
        assert result_b.outcome.status is AgentExecutionStatus.AWAITING_INPUT
        assert result_a.assistant_message == "Design turn accepted: Thread A proposal ready."
        assert result_b.assistant_message == "Design turn accepted: Thread B proposal ready."
        assert await _history_roles(conn_a, seeds_a) == ["user", "assistant"]
        assert await _history_roles(conn_b, seeds_b) == ["user", "assistant"]

    run_async(scenario())


# --- the queued-race gate answer (review finding C, worker half) -------------------------------


def test_a_gate_answer_queued_behind_a_leg_opening_still_reaches_head_of_abm(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The accept-time 409 cannot see the future: an answer accepted while no leg was open
    can execute after a queued turn opened one. The worker's routing must then deliver it
    to head-of-abm — the gate flow's owner — never to the design agent as a prompt.

    The head-of-abm path is composed with ``None`` sentinels here (the P3.4 gate test's
    idiom), so *reaching* it raises ``AttributeError`` — the proof of delivery — while the
    design lane must see nothing and the leg must stay untouched.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="gaterace")
            workspace_id = seeds["workspace_id"]
            cf = seeds["conn_factory"]

            # The presenting head-of-abm turn the gate anchors to (FK: agent_turn).
            import json as _json

            manifest = await seeds["artifacts"].persist_body(
                workspace_id=workspace_id,
                data=_json.dumps({"resources": []}).encode(),
                media_type="application/json",
            )
            presenting_turn = uuid5(NAMESPACE_URL, "p36:gaterace:presenting")
            presenting_execution = uuid5(NAMESPACE_URL, "p36:gaterace:execution")
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) VALUES (:id, :ws, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": presenting_execution,
                    "ws": workspace_id,
                    "project": seeds["project"].project_id,
                    "hash": "0" * 64,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                    " workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at) "
                    "VALUES (:id, :execution, :ws, :project, :thread, :actor, 'head_of_abm', "
                    " 'root-p36', 'head-of-abm', 'v24', :sha, :key, :sha256, :sha256, 'test', "
                    " :at)"
                ),
                {
                    "id": presenting_turn,
                    "execution": presenting_execution,
                    "ws": workspace_id,
                    "project": seeds["project"].project_id,
                    "thread": seeds["thread_id"],
                    "actor": USER_ID,
                    "sha": "0" * 64,
                    "key": manifest.artifact_key,
                    "sha256": manifest.sha256,
                    "at": NOW_UTC,
                },
            )
            gate, _ = await insert_gate(
                conn,
                gate_id=uuid4(),
                workspace_id=workspace_id,
                project_id=seeds["project"].project_id,
                thread_id=seeds["thread_id"],
                turn_id=presenting_turn,
                kind=KIND_DIRECTIVE_CONFIRMATION,
                subject_ref="research-directive:33333333-3333-4333-8333-333333333333:v1",
                subject_revision=1,
                expected_subject_sha256="c" * 64,
                subject_snapshot={"research_directive_id": str(uuid4()), "account_count": 1},
                max_spend_cents=Decimal("600"),
                currency=DEFAULT_GATE_CURRENCY,
                addressee_user_id=USER_ID,
            )
            # The race's end state: the answer was ACCEPTED (submission + answer rows exist,
            # written by the route while no leg blocked it), and by execution time this
            # thread's leg is open.
            answer_submission = await _submit_message(
                conn,
                seeds,
                label="gaterace-answer",
                message='{"kind": "gate_response", "decision": "approved"}',
            )
            await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=workspace_id,
                turn_id=answer_submission.turn_id,
                action_ref=derive_turn_action_ref(answer_submission.turn_id),
                decision="approved",
                expected_subject_sha256="c" * 64,
                answered_by_user_id=USER_ID,
            )

            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=cf)
            runner = ProjectConversationTurnRunner(
                engine=None,  # type: ignore[arg-type]
                executor=None,  # type: ignore[arg-type]
                recipes=None,  # type: ignore[arg-type]
                starter=None,  # type: ignore[arg-type]
                parameters=None,  # type: ignore[arg-type]
                design_legs=DesignLegTurnRunner(
                    profiles=registry,
                    artifacts=seeds["artifacts"],
                    turns=DbAgentTurnJournal(conn_factory=cf),
                    history=DbAgentHistoryStore(conn_factory=cf),
                    lane=lane,
                    conn_factory=cf,
                ),
                conn_factory=cf,
                streaming=False,
            )
            # Reaching the head-of-abm machinery (recipes=None) raises: proof of delivery.
            with pytest.raises(AttributeError):
                await runner.run(turn_id=answer_submission.turn_id, workspace_id=workspace_id)

            assert lane.envelopes == []  # the design agent never saw the answer
            design_turns = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_turn "
                        "WHERE workspace_id = :ws AND thread_id = :thread AND role = 'design'"
                    ),
                    {"ws": workspace_id, "thread": seeds["thread_id"]},
                )
            ).scalar_one()
            assert int(design_turns) == 0
            leg_after = await design_legs.get_leg(
                conn, workspace_id=workspace_id, leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"  # the leg is untouched

            # And an ORDINARY message on the same thread still routes to the design agent —
            # the exception is exactly the gate answer, nothing wider.
            ordinary = await _submit_message(
                conn, seeds, label="gaterace-ordinary", message="Back to the artboard: bolder."
            )
            result = await runner.run(turn_id=ordinary.turn_id, workspace_id=workspace_id)
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert len(lane.envelopes) == 1

    run_async(scenario())


class _LaneThatRaisesMidDrive:
    """An exception-shaped lane failure (join timeout, unavailable lane, missing app) —
    NOT a process death: handlers run, so containment must produce a terminal turn."""

    async def drive(self, *, envelope: Any) -> None:
        raise RuntimeError("the design lane is on fire")


class _RecordingStream:
    def __init__(self) -> None:
        self.finished: list[dict[str, Any]] = []

    async def turn_started(self) -> None: ...

    async def rehydrate(self, *, reason: str) -> None: ...

    async def turn_finished(self, **kwargs: Any) -> None:
        self.finished.append(kwargs)


def test_an_exception_after_the_turn_starts_is_contained_as_a_terminal_turn(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Adversarial-review fix (design-lane failure containment): any raise after the turn
    starts used to leave the agent_turn 'running' forever with no terminal stream frame —
    an endless spinner, an unprunable stream, and a thread whose next turn dispatches on
    top of a zombie. The head-of-abm runner's armor, ported: the failure is marked
    abandoned with an honest reason, the stream gets its terminal frame, and the raise
    still propagates so the fleet task fails loudly."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.agent_turn_submission import message_artifact_ref

            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="contain")
            submission = await _submit_message(conn, seeds, label="contain-1", message="Bolder.")
            leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
            )
            assert leg is not None
            stream = _RecordingStream()
            with pytest.raises(RuntimeError, match="on fire"):
                await _fresh_runner(seeds, tmp_path, _LaneThatRaisesMidDrive()).run_leg_turn(
                    submission=submission,
                    leg=leg,
                    user_message_ref=await message_artifact_ref(conn, submission),
                    focus_refs=(),
                    card_payload=_card_payload(seeds),
                    stream=stream,  # type: ignore[arg-type]
                )

            status = (
                (
                    await conn.execute(
                        text(
                            "SELECT status, reason_code FROM agent_turn_event "
                            "WHERE turn_id = :turn ORDER BY seq DESC LIMIT 1"
                        ),
                        {"turn": submission.turn_id},
                    )
                )
                .mappings()
                .one()
            )
            assert status["status"] == "abandoned"
            assert status["reason_code"] == "design_leg_turn_crashed"
            assert stream.finished == [
                {"status": "failed", "failure_code": "design_leg_turn_crashed"}
            ]

    run_async(scenario())
