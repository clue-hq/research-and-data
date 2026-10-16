"""Graceful drain on deploy for a site turn on the INLINE design-leg lane (Task 4).

Site-turn durability, 2026-10-16. A chat worker being shut down lets its running agent turns
finish; the inline lane never sees the stop (it hands the design handler a stop event nobody
sets). When the worker's drain bound passes, it asks every drain-aware handler to drain: the
agent-turn handler forwards that to its design-leg lane, whose design handler drains the site turn
at its next step boundary. The lane then releases the run's lease, and the agent turn ends with
``WorkDrained``, which the worker turns into a requeue. Nothing is saved, no crash is contained
(the leg is not handed back, no terminal turn event), and the next attempt at the same chat turn
continues the design run from its working copy.

The production lane, handler, executor, harness, Postgres checkpointer and save are used unchanged
(BV1b's composition, ``test_site_lane_b_scenarios_db``); only the chat model is scripted.
"""

from __future__ import annotations

import asyncio
import threading
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text

from clue_agents import AgentExecutionStatus
from clue_api.agent_turn_submission import get_submission, message_artifact_ref
from clue_api.design_leg_wiring import design_leg_run_id
from clue_db import db_lifespan, transaction
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_fleet import WorkDrained, WorkId, get_work_lease
from tests.api.test_genweb_web_turn_dispatch_db import _card_payload, _runner
from tests.api.test_site_lane_b_scenarios_db import (  # noqa: F401 - fixtures are used by name
    REQUEST_1,
    WARM_PROOF,
    DesignEnv,
    ModelSeam,
    Script,
    _chat_message,
    _edit_heading_call,
    _leg_state,
    _production_lane,
    _registry,
    _run_columns,
    _site_leg,
    _stored,
    _thread_messages,
    _with_heading,
    call,
    design_env,
    logos,
    model,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

CTA = "Book SCSD's free analysis this month"


class HookedScript(Script):
    """``hooks`` maps a call number (0-based) to a callable run before that call answers."""

    hooks: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        hook = self.hooks.get(len(self.seen))
        if hook is not None:
            hook()
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


async def _terminal_turn_events(turn_id) -> list:
    async with transaction() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status FROM agent_turn_event WHERE turn_id = :turn"
                    " AND status IN ('failed', 'abandoned', 'cancelled')"
                ),
                {"turn": turn_id},
            )
        ).all()


def test_l_a_an_inline_site_turn_at_the_bound_is_handed_to_the_next_attempt(
    design_env: DesignEnv,  # noqa: F811 - the imported fixture
    model: ModelSeam,  # noqa: F811
    logos: list[dict],  # noqa: F811
) -> None:
    registry = _registry()

    async def scenario() -> None:
        async with db_lifespan():
            leg = await _site_leg(design_env, f"drain{uuid4().hex[:8]}")
            lane = _production_lane(design_env.storage)
            loop = asyncio.get_running_loop()
            asked = threading.Event()

            def the_bound_passes() -> None:
                # What the chat worker does at its drain bound: AgentTurnWorkHandler.request_drain
                # forwards to its lane. Called on the worker's loop, as the worker calls it.
                def drain() -> None:
                    lane.inner.request_drain("the chat worker is shutting down")
                    asked.set()

                loop.call_soon_threadsafe(drain)
                assert asked.wait(30), "the drain never reached the lane"

            a = HookedScript(
                messages=iter(
                    [
                        AIMessage(
                            content="",
                            tool_calls=[_edit_heading_call(leg.born, "/", "proof", WARM_PROOF, 1)],
                        ),
                        AIMessage(
                            content="",
                            tool_calls=[_edit_heading_call(leg.born, "/analysis", "cta", CTA, 2)],
                        ),
                        AIMessage(content="never reached"),
                    ]
                ),
                hooks={1: the_bound_passes},
            )
            model.scripts.append(a)
            label = f"{leg.seeds['thread_id']}-1"
            with pytest.raises(WorkDrained):
                await _chat_message(leg, lane, registry, label=label, message=REQUEST_1)

            # ``_submit_message`` derives the turn id from the label.
            turn_id = uuid5(NAMESPACE_URL, f"genweb:{label}:turn")
            run_id = design_leg_run_id(turn_id)
            assert len(a.seen) == 2
            # The run was handed back, not failed: still running, its lease released, nothing saved.
            columns = await _run_columns(leg, run_id)
            assert columns["status"] == "running", columns
            async with transaction() as conn:
                lease = await get_work_lease(conn, WorkId(design_runs.work_id_for_run(run_id)))
            assert lease is not None and not lease.live
            assert (await asyncio.to_thread(_stored, leg))["current_version"] == 0
            # No crash was contained: no assistant message, no terminal turn event, and the
            # leg is still running.
            assert [role for role, _turn, _body in await _thread_messages(leg)] == ["user"]
            assert await _terminal_turn_events(turn_id) == []
            assert await _leg_state(leg) == "running"

            # The next attempt at the same chat turn (another worker) continues the run.
            b = model.next(
                AIMessage(content="", tool_calls=[call("validate_page", {}, 13)]),
                AIMessage(content="Both headings are updated."),
            )
            async with transaction() as conn:
                row = await get_submission(conn, workspace_id=leg.workspace_id, turn_id=turn_id)
                open_leg = await design_legs.get_open_leg_for_thread(
                    conn, workspace_id=leg.workspace_id, thread_id=leg.thread_id
                )
                user_message_ref = await message_artifact_ref(conn, row)
            result = await _runner(
                leg.seeds, registry, _production_lane(design_env.storage)
            ).run_leg_turn(
                submission=row,
                leg=open_leg,
                user_message_ref=user_message_ref,
                focus_refs=(),
                card_payload=_card_payload(leg.seeds),
                stream=None,
            )
            assert len(b.seen) == 2
            seen_results = {getattr(m, "tool_call_id", None) for m in b.seen[0]}
            assert {"call_1", "call_2"} <= seen_results
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            stored = await asyncio.to_thread(_stored, leg)
            both = _with_heading(
                _with_heading(leg.born, "/", "proof", WARM_PROOF), "/analysis", "cta", CTA
            )
            assert stored["current_version"] == 1 and stored["scene"] == both
            finished = await _run_columns(leg, run_id)
            assert (
                finished["status"] == "succeeded"
                and finished["lease_generation"] > columns["lease_generation"]
            )
            assert await _leg_state(leg) == "open_awaiting_user"

    run_async(scenario())


def test_l_b_the_chat_worker_s_drain_reaches_its_design_leg_lane() -> None:
    """``AgentTurnWorkHandler`` is drain-aware: the worker's bound reaches the lane it composed."""
    from clue_api.agent_turn_fleet_wiring import AgentTurnWorkHandler
    from clue_fleet import DrainAware

    class Lane:
        def __init__(self) -> None:
            self.reasons: list[str] = []

        def request_drain(self, reason: str) -> None:
            self.reasons.append(reason)

    lane = Lane()
    handler = AgentTurnWorkHandler(runner=object(), queue=object(), design_lane=lane)  # type: ignore[arg-type]
    assert isinstance(handler, DrainAware)
    handler.request_drain("the chat worker is shutting down")
    assert lane.reasons == ["the chat worker is shutting down"]
    # A worker composed without the design runtime has no lane to drain; the call is harmless.
    AgentTurnWorkHandler(runner=object(), queue=object()).request_drain("x")  # type: ignore[arg-type]
