"""P3.7 — the §2.2 exit bridge: the judge decides, the engine executes, the leg closes.

The design orchestrator's leg-level exit, materialized: before a leg message dispatches to
the design lane, the composed :class:`DesignLegExitJudge` (the P3.6 judgment core's live
face) classifies it; a ``finish`` verdict is executed as the governed ``finish_design_leg``
invocation (derived operation id — a crash-retried exit replays, never collides), and the
closing turn finalizes ``COMPLETED`` with no leg gate ref and NO runner-authored assistant
message — the finish tool's leg-summary message is the turn's one durable assistant record
(the review's bridge-time finalize LOW, closed).

Fail-safe throughout: a judge that raises, a verdict without a reason, or a missing
finisher can only CONTINUE the leg. And the crash window between the close and the
finalization converges: the routing rule's closed-by-turn fallback re-delivers the retried
closing turn to the design runner, whose finisher replay + committed finalize finish the
job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from clue_agents import AgentExecutionStatus
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_fleet_wiring import ProjectConversationTurnRunner
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
)
from clue_api.chat.turn_events import list_turn_events
from clue_api.design_leg_wiring import (
    DesignLegTurnRunner,
    build_design_leg_finisher,
    exit_summary,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_design import legs as design_legs
from clue_design.exit_judgment import ExitJudgment
from clue_storage import FsStorage
from tests.api.conftest import hermetic_flag_env
from tests.api.test_p34_design_leg_engine_db import (
    _FakeLane,
    _run_turn,
    _RuntimeFailedLane,
    _seed_leg_conversation,
    _submit_message,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


class _ScriptedJudge:
    """Returns a fixed verdict and records exactly what it was asked."""

    def __init__(self, judgment: ExitJudgment | None) -> None:
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
    ) -> ExitJudgment | None:
        self.calls.append(
            {
                "brief": brief,
                "history": history,
                "message": message,
                # v3 shows the leg's artifacts numbered; ``artifact`` is v2's one line, kept
                # on the protocol for compatibility and unused by the runner.
                "artifacts": artifacts,
                "artifact": artifact,
                "tags": tags,
            }
        )
        return self._judgment


class _JudgeThatExplodes:
    async def __call__(self, **kwargs: Any) -> ExitJudgment | None:
        raise RuntimeError("the judge model is down")


class _WorkerDeath(BaseException):
    """Dies AFTER the real close landed — the crash window between close and finalize."""


def _finisher(seeds: dict[str, Any], storage_root: Path) -> Any:
    """The finisher over a REAL journaled ToolInvoker (the C5.1 discipline), exactly as
    the fleet root composes it — registry holding the finish tool, DB idempotency store,
    snapshot storage. The adversarial-review fix retired the bare-``invoke_tool`` path."""

    from clue_api.design_leg_tools import FinishDesignLegTool
    from clue_api.execution_wiring import build_tool_invoker
    from clue_config import load_settings
    from clue_toolbelt import DbIdempotencyStore, ToolRegistry

    cf = seeds["conn_factory"]
    registry = ToolRegistry()
    registry.register(
        FinishDesignLegTool(conn_factory=cf, storage=FsStorage(storage_root / "artifacts")),
        make_default=True,
    )
    return build_design_leg_finisher(
        invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=FsStorage(storage_root / "snapshots"),
            settings=load_settings(_env_file=None),
            conn_factory=cf,
        ),
        conn_factory=cf,
    )


def _bridged_runner(
    seeds: dict[str, Any],
    registry: Any,
    lane: Any,
    *,
    judge: Any,
    finisher: Any,
) -> DesignLegTurnRunner:
    return DesignLegTurnRunner(
        profiles=registry,
        artifacts=seeds["artifacts"],
        turns=DbAgentTurnJournal(conn_factory=seeds["conn_factory"]),
        history=DbAgentHistoryStore(conn_factory=seeds["conn_factory"]),
        lane=lane,
        exit_judge=judge,
        finisher=finisher,
        conn_factory=seeds["conn_factory"],
    )


async def _run_bridged(
    conn: Any,
    seeds: dict[str, Any],
    registry: Any,
    lane: Any,
    submission: Any,
    *,
    judge: Any,
    finisher: Any,
) -> Any:
    from clue_api.agent_turn_submission import message_artifact_ref
    from tests.api.test_p34_design_leg_engine_db import _card_payload

    leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    assert leg is not None
    return await _bridged_runner(
        seeds, registry, lane, judge=judge, finisher=finisher
    ).run_leg_turn(
        submission=submission,
        leg=leg,
        user_message_ref=await message_artifact_ref(conn, submission),
        focus_refs=(),
        card_payload=_card_payload(seeds),
        stream=None,
    )


async def _assistant_message_ids(conn: Any, seeds: dict[str, Any]) -> list[str]:
    return list(
        (
            await conn.execute(
                text(
                    "SELECT id::text FROM agent_thread_message "
                    "WHERE workspace_id = :ws AND thread_id = :thread AND role = 'assistant' "
                    "ORDER BY sequence"
                ),
                {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
            )
        ).scalars()
    )


def test_a_lock_in_verdict_closes_the_leg_and_finalizes_completed(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="lockin")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])

            # A prior design exchange, so the judge sees real history.
            first = await _submit_message(conn, seeds, label="lockin-1", message="Bolder.")
            await _run_turn(conn, seeds, registry, lane, first)

            judge = _ScriptedJudge(
                ExitJudgment(
                    close_this_session=True,
                    current_artifact_accepted=True,
                    reasoning="The user accepted it.",
                )
            )
            closing = await _submit_message(
                conn, seeds, label="lockin-2", message="Perfect - lock it in."
            )
            result = await _run_bridged(
                conn,
                seeds,
                registry,
                lane,
                closing,
                judge=judge,
                finisher=_finisher(seeds, tmp_path),
            )

            # The judge saw the §2.3 brief, the leg history, and the exiting message.
            assert judge.calls[0]["brief"] == "A launch artboard."
            assert judge.calls[0]["message"] == "Perfect - lock it in."
            assert [role for role, _ in judge.calls[0]["history"]] == ["user", "assistant"]

            # The bridge-time finalize shape: COMPLETED, no dispatch for the exiting turn.
            assert result.outcome.status is AgentExecutionStatus.COMPLETED
            assert result.assistant_message == exit_summary("locked", "The user accepted it.")
            assert len(lane.envelopes) == 1  # only the first turn ever dispatched

            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "closed"
            assert leg_after["close_reason"] == "locked"
            journal = (
                (
                    await conn.execute(
                        text(
                            "SELECT reason, summary_refs->>'closing_turn_id' AS closer "
                            "FROM design_leg_exit_journal WHERE workspace_id = :ws"
                        ),
                        {"ws": seeds["workspace_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert journal["reason"] == "locked"
            assert journal["closer"] == str(closing.turn_id)

            # ONE assistant record for the closing turn: the tool's leg summary — the
            # runner authored no second message (the double-message LOW, closed).
            assistants = await _assistant_message_ids(conn, seeds)
            assert len(assistants) == 2  # turn 1's summary + the leg summary
            events = await list_turn_events(conn, workspace_id=seeds["workspace_id"])
            closed = [e for e in events if e.event_type == "leg.closed"]
            assert len(closed) == 1 and closed[0].turn_id == closing.turn_id

    run_async(scenario())


def test_an_out_of_scope_verdict_redelivers_the_pending_question(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="oos")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            first = await _submit_message(conn, seeds, label="oos-1", message="Bolder.")
            await _run_turn(conn, seeds, registry, lane, first)

            closing = await _submit_message(
                conn, seeds, label="oos-2", message="Which accounts should we target?"
            )
            result = await _run_bridged(
                conn,
                seeds,
                registry,
                lane,
                closing,
                judge=_ScriptedJudge(
                    ExitJudgment(
                        close_this_session=True,
                        hand_message_to_strategy_agent=True,
                        reasoning="Not design work.",
                    )
                ),
                finisher=_finisher(seeds, tmp_path),
            )
            assert result.outcome.status is AgentExecutionStatus.COMPLETED

            # The user's own bytes, re-submitted under the derived redelivery identity — the
            # leg is closed in the same transaction, so the retried question routes to
            # head-of-abm and the user never repeats it.
            redelivered = (
                (
                    await conn.execute(
                        text(
                            "SELECT s.turn_id::text AS turn_id, s.message_sha256 "
                            "FROM agent_turn_submission s "
                            "WHERE s.workspace_id = :ws AND s.thread_id = :thread "
                            "AND s.idempotency_key LIKE 'design-leg-redelivery:%'"
                        ),
                        {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert redelivered["message_sha256"] == closing.message_sha256
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["close_reason"] == "out_of_scope"

    run_async(scenario())


def test_closing_after_a_failed_run_tells_the_strategy_agent_why(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Production 2026-10-05: the session's runs had failed before generating anything; the
    exit summary said only that the request was out of scope, so the strategy agent told the
    user the page "was never generated". The summary now carries the failure."""
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="oosfail")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            failing = _RuntimeFailedLane(conn_factory=seeds["conn_factory"])
            first = await _submit_message(conn, seeds, label="oosfail-1", message="Generate.")
            await _run_turn(conn, seeds, registry, failing, first)

            closing = await _submit_message(
                conn, seeds, label="oosfail-2", message="What's happening? Why is it not ready?"
            )
            result = await _run_bridged(
                conn,
                seeds,
                registry,
                failing,
                closing,
                judge=_ScriptedJudge(
                    ExitJudgment(
                        close_this_session=True,
                        hand_message_to_strategy_agent=True,
                        reasoning="A status question, not design work.",
                    )
                ),
                finisher=_finisher(seeds, tmp_path),
            )
            assert result.outcome.status is AgentExecutionStatus.COMPLETED
            message = result.assistant_message or ""
            assert message.startswith(
                exit_summary("out_of_scope", "A status question, not design work.")
            )
            assert "before anything was generated" in message
            assert "agent_runtime.failed" in message
            assert "/srv" not in message

    run_async(scenario())


@pytest.mark.parametrize(
    ("label", "judge"),
    [
        (
            "continues",
            lambda: _ScriptedJudge(
                ExitJudgment(close_this_session=False, reasoning="Still iterating.")
            ),
        ),
        ("unparseable", lambda: _ScriptedJudge(None)),
        ("reasoning-less", lambda: _ScriptedJudge(None)),
        ("explodes", lambda: _JudgeThatExplodes()),
    ],
)
def test_every_non_exit_shape_continues_the_leg_and_designs(
    tmp_path: Path,
    label: str,
    judge: Any,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The fail-safe, live: continue verdicts, garbage, reasonless finishes, and a judge
    that raises all take today's dispatch path — the leg stays open and the turn designs."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label=f"fs{label}")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn, seeds, label=f"fs{label}-1", message="Make the logo pop."
            )
            result = await _run_bridged(
                conn,
                seeds,
                registry,
                lane,
                submission,
                judge=judge(),
                finisher=_finisher(seeds, tmp_path),
            )
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert len(lane.envelopes) == 1  # the turn designed
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"

    run_async(scenario())


def test_the_close_to_finalize_crash_window_converges_through_the_routing_fallback(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Attempt 1 closes the leg and dies before finalizing. The retry finds no open leg —
    the routing rule's closed-by-turn fallback re-delivers it to the design runner, whose
    finisher replay + committed finalize converge on COMPLETED with no second close."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="crashwin")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            cf = seeds["conn_factory"]
            lane = _FakeLane(conn_factory=cf)
            first = await _submit_message(conn, seeds, label="crashwin-1", message="Bolder.")
            await _run_turn(conn, seeds, registry, lane, first)

            real_finisher = _finisher(seeds, tmp_path)

            async def dying_finisher(**kwargs: Any) -> dict[str, Any]:
                await real_finisher(**kwargs)
                raise _WorkerDeath  # the process dies with the close committed

            closing = await _submit_message(
                conn, seeds, label="crashwin-2", message="We're done, lock it."
            )
            with pytest.raises(_WorkerDeath):
                await _run_bridged(
                    conn,
                    seeds,
                    registry,
                    lane,
                    closing,
                    judge=_ScriptedJudge(
                        ExitJudgment(
                            close_this_session=True,
                            current_artifact_accepted=True,
                            reasoning="The user accepted it.",
                        )
                    ),
                    finisher=dying_finisher,
                )
            mid = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert mid["state"] == "closed"  # the close survived the death

            # The retry goes through the REAL worker routing: no open leg, but the exit
            # journal names this turn — so it comes back as a design turn and converges.
            retry_runner = ProjectConversationTurnRunner(
                engine=None,  # type: ignore[arg-type]
                executor=None,  # type: ignore[arg-type]
                recipes=None,  # type: ignore[arg-type]
                starter=None,  # type: ignore[arg-type]
                parameters=None,  # type: ignore[arg-type]
                design_legs=_bridged_runner(
                    seeds,
                    registry,
                    lane,
                    judge=_ScriptedJudge(
                        ExitJudgment(
                            close_this_session=True,
                            current_artifact_accepted=True,
                            reasoning="The user accepted it.",
                        )
                    ),
                    finisher=real_finisher,
                ),
                conn_factory=cf,
                streaming=False,
            )
            result = await retry_runner.run(
                turn_id=closing.turn_id, workspace_id=seeds["workspace_id"]
            )
            assert result.outcome.status is AgentExecutionStatus.COMPLETED
            assert result.assistant_message == exit_summary("locked", "The user accepted it.")
            # One close, ever: one journal row, one leg.closed frame, one leg summary.
            journal_count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_leg_exit_journal WHERE workspace_id = :ws"),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert int(journal_count) == 1
            events = await list_turn_events(conn, workspace_id=seeds["workspace_id"])
            assert len([e for e in events if e.event_type == "leg.closed"]) == 1

    run_async(scenario())
