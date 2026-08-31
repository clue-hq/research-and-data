"""Part II D8 (ruling R-D8-4) — the design run-event pruner's eligibility half and its floors.

The DELETE half (never a terminal row, never a project subject, prefix-only) is proven at the
substrate in ``tests/execution/test_retention_sweeps_db.py``. What is proven HERE is everything the
composition root adds on top, because each item is a way the sweep could quietly become dangerous:

* **only terminal runs** — an old ``running``/``queued`` run's stream is still being written;
* **the retention floor** — a configured retention below 7 days is clamped UP, never honoured, so
  retention keeps strictly exceeding the design stream's 24h replay horizon;
* **the SSE close-out survives pruning** — a fresh connect to a pruned run still ends in ``done``,
  which is the property the whole floor set exists to protect (D8 deleted the liveness net that
  used to cover a missing terminal event);
* **the default is OFF** — this is the only sweep in the platform that destroys durable
  run-visibility history, so a deployment gets it by asking, not by upgrading.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from lumen_api import event_pruner, run_stream
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import runs as design_runs
from tests.design.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_design_db")

#: Comfortably past the 7-day floor, so "eligible" in these tests is never accidental.
_OLD_ENOUGH_S = 30 * 86_400.0


async def _seed_workspace(conn: AsyncConnection, tag: str) -> str:
    workspace_id = f"ws_test_prune_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )
    return workspace_id


async def _finished_run(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    progress: int = 3,
    status: str = "succeeded",
    finished_days_ago: float = 40.0,
    emit_terminal: bool = True,
) -> str:
    """A design run with a real event stream, aged so ``updated_at`` says when it finished."""
    run_id = f"run_{uuid4().hex}"
    await design_runs.create_run(conn, workspace_id=workspace_id, run_id=run_id, document_id=None)
    await design_runs.claim_run_for_execution(
        conn,
        work_id=design_runs.work_id_for_run(run_id),
        worker_id="worker-test",
        lease_generation=1,
    )
    for index in range(progress):
        await run_stream.emit_progress(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="dsl_compiled",
            data={"n": index},
        )
    if emit_terminal:
        await run_stream.complete_run_and_emit(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            status=status,
            result={"schema_version": 1, "status": status, "summary": "done"},
            event_type="result" if status == "succeeded" else "error",
        )
    await _age_run(conn, run_id, days=finished_days_ago)
    return run_id


async def _age_run(conn: AsyncConnection, run_id: str, *, days: float) -> None:
    """Push the run row's ``updated_at`` back — "this run finished ``days`` ago"."""
    await conn.execute(
        text(
            "UPDATE design_agent_run SET updated_at = now() - make_interval(secs => :s)"
            " WHERE run_id = :r"
        ),
        {"s": days * 86_400.0, "r": run_id},
    )


async def _events(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> list[dict[str, Any]]:
    return await run_stream.run_snapshot_events(conn, workspace_id=workspace_id, run_id=run_id)


# --- eligibility ---------------------------------------------------------------------------------


def test_the_pruner_prunes_a_long_finished_run_and_keeps_its_terminal_event() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                workspace_id = await _seed_workspace(conn, "eligible")
                run_id = await _finished_run(conn, workspace_id=workspace_id, progress=4)
                assert len(await _events(conn, workspace_id=workspace_id, run_id=run_id)) == 5

                sweep = await event_pruner.prune_design_run_events(conn, retention_s=_OLD_ENOUGH_S)
                assert sweep.pruned_runs >= 1
                assert sweep.deleted_events >= 4

                remaining = await _events(conn, workspace_id=workspace_id, run_id=run_id)
                assert [event["type"] for event in remaining] == ["result"]
            finally:
                await trans.rollback()
                await conn.close()

    run_async(scenario())


def test_a_non_terminal_run_is_untouched_however_old_it_is() -> None:
    """Floor 3. Age is never sufficient — the run has to be FINISHED."""

    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                workspace_id = await _seed_workspace(conn, "running")
                run_id = await _finished_run(
                    conn,
                    workspace_id=workspace_id,
                    progress=3,
                    finished_days_ago=400.0,
                    emit_terminal=False,
                )
                row = await design_runs.require_run(conn, workspace_id=workspace_id, run_id=run_id)
                assert row["status"] == "running"

                sweep = await event_pruner.prune_design_run_events(conn, retention_s=_OLD_ENOUGH_S)

                assert len(await _events(conn, workspace_id=workspace_id, run_id=run_id)) == 3
                # It was not even a candidate: the eligibility scan filters on terminal status.
                assert sweep.deleted_events == 0
            finally:
                await trans.rollback()
                await conn.close()

    run_async(scenario())


def test_a_recently_finished_run_is_inside_the_retention_window() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                workspace_id = await _seed_workspace(conn, "young")
                run_id = await _finished_run(
                    conn, workspace_id=workspace_id, progress=3, finished_days_ago=1.0
                )

                await event_pruner.prune_design_run_events(conn, retention_s=_OLD_ENOUGH_S)

                assert len(await _events(conn, workspace_id=workspace_id, run_id=run_id)) == 4
            finally:
                await trans.rollback()
                await conn.close()

    run_async(scenario())


# --- the retention floor -------------------------------------------------------------------------


def test_the_retention_floor_strictly_exceeds_the_replay_horizon() -> None:
    """The inequality the [B4×SSE] answer rests on, asserted rather than asserted-about."""
    assert event_pruner.RETENTION_FLOOR_SECONDS > run_stream.REPLAY_HORIZON_SECONDS
    assert event_pruner.RETENTION_FLOOR_SECONDS == 7 * 86_400.0


def test_a_configured_retention_below_the_floor_is_clamped_up_not_honoured() -> None:
    assert event_pruner.effective_retention_s(0.0) == event_pruner.RETENTION_FLOOR_SECONDS
    assert event_pruner.effective_retention_s(60.0) == event_pruner.RETENTION_FLOOR_SECONDS
    # Exactly at the horizon — the value an operator would naively pick — is still clamped.
    assert (
        event_pruner.effective_retention_s(run_stream.REPLAY_HORIZON_SECONDS)
        == event_pruner.RETENTION_FLOOR_SECONDS
    )
    # Above the floor is honoured verbatim.
    assert event_pruner.effective_retention_s(90 * 86_400.0) == 90 * 86_400.0


def test_the_floor_is_enforced_on_rows_not_only_in_arithmetic() -> None:
    """A run that finished two days ago survives a pass configured to retain for one hour."""

    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                workspace_id = await _seed_workspace(conn, "floor")
                run_id = await _finished_run(
                    conn, workspace_id=workspace_id, progress=3, finished_days_ago=2.0
                )

                sweep = await event_pruner.prune_design_run_events(conn, retention_s=3600.0)

                assert sweep.deleted_events == 0
                assert len(await _events(conn, workspace_id=workspace_id, run_id=run_id)) == 4
            finally:
                await trans.rollback()
                await conn.close()

    run_async(scenario())


# --- the property all of it protects ---------------------------------------------------------


def test_a_fresh_connect_to_a_pruned_run_still_closes_on_its_terminal_event() -> None:
    """The SSE close-out, end to end, after the pruner has run.

    D8 deleted the idle-poll liveness net, so the terminal ``run_event`` row is now the ONLY thing
    that ends a subscriber's stream. This drives the real serve loop (``stream_run_events``) over a
    pruned run and asserts it yields exactly one frame — ``done``, built from the surviving terminal
    event's self-contained payload — and then returns.
    """

    async def scenario() -> None:
        async with db_lifespan() as engine:
            # COMMITTED, unlike every other test here: the serve loop opens its own engine and
            # connection (that is the shape being exercised), so it cannot see an open transaction.
            async with engine.connect() as setup, setup.begin():
                workspace_id = await _seed_workspace(setup, "sse")
                run_id = await _finished_run(setup, workspace_id=workspace_id, progress=4)
                await event_pruner.prune_design_run_events(setup, retention_s=_OLD_ENOUGH_S)
            try:
                frames = [
                    frame
                    async for frame in run_stream.stream_run_events(
                        workspace_id=workspace_id, run_id=run_id, cursor=None
                    )
                ]
            finally:
                async with engine.connect() as cleanup, cleanup.begin():
                    for statement in (
                        "DELETE FROM run_event WHERE workspace_id = :w",
                        "DELETE FROM design_agent_run WHERE workspace_id = :w",
                        "DELETE FROM workspace WHERE workspace_id = :w",
                    ):
                        await cleanup.execute(text(statement), {"w": workspace_id})

            # ``retry:`` preamble, then the done frame, then the generator RETURNS — no keepalives,
            # no hang, and no progress frames (they were pruned). The loop never reads the run row.
            assert frames[0].startswith("retry:")
            body = frames[1:]
            assert len(body) == 1, body
            assert "event: done\n" in body[0]
            assert '"summary": "done"' in body[0]

    run_async(scenario())


# --- the switch ------------------------------------------------------------------------------


def test_the_pruner_is_disabled_by_default_and_the_token_sweep_is_not() -> None:
    """The two D8 sweeps' defaults, stated where a reviewer will look for them.

    The asymmetry is the ruling: a spent ``stream_token`` is already unreadable by every code path,
    so sweeping it is unobservable and ships ON; the event pruner destroys durable history, so it
    ships OFF and is turned on deliberately.
    """
    from clue_config import Settings

    settings = Settings()
    assert settings.design_run_event_prune_interval_s == 0.0
    assert settings.stream_token_sweep_interval_s > 0
    assert settings.design_run_event_retention_s >= event_pruner.RETENTION_FLOOR_SECONDS
    assert event_pruner.start_pruner(interval_s=0.0, retention_s=_OLD_ENOUGH_S) is None
