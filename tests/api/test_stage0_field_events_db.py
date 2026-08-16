"""FI-4 slice 3: the per-field recon progress emitter (D-5 Path B) against a real database.

The point of this file is the *visibility* proof the setup screen depends on: with its own
connection factory the emitter's events are committed and readable by a concurrent poller **while
the recon lane's transaction is still open** — that is the whole reason the screen can show real
motion instead of a spinner. The factory-less shape (every test harness's serialized/savepoint
connection) is proven to ride the lane connection instead, and an emitter whose sink blows up is
proven not to take the lane down with it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import stage0_field_events
from clue_api.stage0_field_events import ReconFieldProgressEmitter
from clue_core import RECON_FIELD_PROGRESS_KIND, ProjectRunId
from clue_db import db_lifespan, transaction
from clue_execution.run_events import list_run_events
from clue_research.stage0 import FieldProgressStatus
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_FIELD = "client.value_prop"


async def _events(
    conn: AsyncConnection, workspace_id: str, recon_run_id: object
) -> list[dict[str, JsonValue]]:
    rows = await list_run_events(
        conn,
        workspace_id=workspace_id,
        run_id=ProjectRunId(recon_run_id),  # type: ignore[arg-type]
    )
    await conn.rollback()  # release the read snapshot; the next read sees fresh commits
    return [dict(row.payload) for row in rows]


async def _purge(workspace_id: str) -> None:
    """Autonomous events genuinely commit, so this file cleans up after itself."""
    async with transaction() as conn:
        await conn.execute(
            text("DELETE FROM run_event WHERE workspace_id = :ws"), {"ws": workspace_id}
        )


def test_autonomous_events_are_visible_before_the_lane_commits_and_survive_its_rollback() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine:
            workspace_id = f"ws-field-events-{uuid4()}"
            recon_run_id = uuid4()
            lane_conn = await engine.connect()
            observer = await engine.connect()
            try:
                trans = await lane_conn.begin()
                emitter = ReconFieldProgressEmitter(
                    workspace_id=workspace_id,
                    recon_run_id=recon_run_id,
                    lane="fast",
                    conn_factory=transaction,
                )
                await emitter(lane_conn, _FIELD, FieldProgressStatus.STARTED)
                await emitter(lane_conn, _FIELD, FieldProgressStatus.RESOLVED)

                # The lane transaction is STILL open and uncommitted…
                assert lane_conn.in_transaction()
                # …yet a concurrent poller on another connection already sees both events.
                payloads = await _events(observer, workspace_id, recon_run_id)
                assert [p["status"] for p in payloads] == ["started", "resolved"]
                assert payloads[0] == {
                    "kind": RECON_FIELD_PROGRESS_KIND,
                    "recon_run_id": str(recon_run_id),
                    "lane": "fast",
                    "field_key": _FIELD,
                    "status": "started",
                }

                # Documented semantics: the events survive a lane rollback by design (lane truth —
                # the recon_run row — supersedes on the read side).
                await trans.rollback()
                assert len(await _events(observer, workspace_id, recon_run_id)) == 2
            finally:
                await lane_conn.close()
                await observer.close()
                await _purge(workspace_id)

    run_async(scenario())


def test_a_factoryless_emitter_writes_on_the_lane_connection() -> None:
    """No factory ⇒ same-transaction write: post-commit visibility, deadlock-free under every
    test conn-factory shape (a serialized shared connection, savepoint-per-acquisition)."""

    async def scenario() -> None:
        async with db_lifespan() as engine:
            workspace_id = f"ws-field-events-{uuid4()}"
            recon_run_id = uuid4()
            lane_conn = await engine.connect()
            observer = await engine.connect()
            try:
                trans = await lane_conn.begin()
                emitter = ReconFieldProgressEmitter(
                    workspace_id=workspace_id,
                    recon_run_id=recon_run_id,
                    lane="background",
                )
                await emitter(lane_conn, _FIELD, FieldProgressStatus.EMPTY)

                # visible inside the lane's own transaction…
                inside = await list_run_events(
                    lane_conn,
                    workspace_id=workspace_id,
                    run_id=ProjectRunId(recon_run_id),
                )
                assert [row.payload["status"] for row in inside] == ["empty"]
                assert inside[0].payload["lane"] == "background"
                # …and nowhere else until it commits
                assert await _events(observer, workspace_id, recon_run_id) == []

                await trans.rollback()
                assert await _events(observer, workspace_id, recon_run_id) == []
            finally:
                await lane_conn.close()
                await observer.close()
                await _purge(workspace_id)

    run_async(scenario())


def test_an_emission_failure_never_fails_the_lane() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine:
            workspace_id = f"ws-field-events-{uuid4()}"
            recon_run_id = uuid4()
            lane_conn = await engine.connect()
            try:

                @asynccontextmanager
                async def broken_factory() -> AsyncIterator[AsyncConnection]:
                    raise RuntimeError("no connection for you")
                    yield  # pragma: no cover - unreachable, keeps the generator shape

                emitter = ReconFieldProgressEmitter(
                    workspace_id=workspace_id,
                    recon_run_id=recon_run_id,
                    lane="fast",
                    conn_factory=broken_factory,
                )
                # Observability never fails the lane: swallowed with a log, nothing propagates.
                await emitter(lane_conn, _FIELD, FieldProgressStatus.FAILED)
                assert await _events(lane_conn, workspace_id, recon_run_id) == []
            finally:
                await lane_conn.close()
                await _purge(workspace_id)

    run_async(scenario())


def test_a_failed_lane_write_does_not_poison_the_lane_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory-less path contains its own failure in a savepoint.

    Swallowing a failed INSERT on the caller's connection without one would leave the recon lane
    holding an aborted transaction — observability failing the lane one statement later, which is
    exactly what the swallow promises never to happen."""

    async def scenario() -> None:
        async with db_lifespan() as engine:
            workspace_id = f"ws-field-events-{uuid4()}"
            lane_conn = await engine.connect()
            try:
                trans = await lane_conn.begin()

                async def exploding_emit(conn: AsyncConnection, **_kwargs: object) -> None:
                    await conn.execute(text("SELECT 1 / 0"))

                monkeypatch.setattr(stage0_field_events, "emit_run_event", exploding_emit)
                emitter = ReconFieldProgressEmitter(
                    workspace_id=workspace_id,
                    recon_run_id=uuid4(),
                    lane="fast",
                )
                await emitter(lane_conn, _FIELD, FieldProgressStatus.STARTED)

                # the lane transaction is still alive and usable
                assert (await lane_conn.execute(text("SELECT 1"))).scalar_one() == 1
                await trans.rollback()
            finally:
                await lane_conn.close()
                await _purge(workspace_id)

    run_async(scenario())
