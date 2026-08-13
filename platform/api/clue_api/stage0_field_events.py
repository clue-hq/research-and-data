"""The per-field recon progress sink — Stage-0 reverse profiling → the ``run_event`` outbox.

The setup screen must show *real* motion while recon runs (founder ruling: no fake progress), and
the only honest source of motion is the reverse-profiling field loop itself. This module is the
composition-root sink that turns that loop's
:class:`~clue_research.stage0.types.FieldProgressStatus` callbacks into durable
``run.step.progress`` events a poller can read mid-lane.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_research.durable import RECON_FIELD_PROGRESS_KIND, RunEventTopic, emit_run_event
from clue_research.stage0 import FieldProgressStatus

log = get_logger("clue_api.stage0_field_events")


class ReconFieldProgressEmitter:
    """Per-field recon progress → run_event outbox.

    With ``conn_factory`` (production: :func:`clue_db.transaction`) events commit on an autonomous
    connection and are visible to concurrent pollers mid-lane — the ``DbSourceCallObserver`` /
    pre-spend-gate precedent. Without one, events ride the given lane connection (post-commit
    visibility; keeps every test conn-factory shape — locked, savepoint-per-acquisition —
    deadlock-free). Emission failures are swallowed with a log: observability never fails the lane.
    At-least-once: readers reduce last-writer-wins by ``seq`` per ``(lane, field_key)``.
    Events on the autonomous path survive a lane rollback by design; lane truth (the ``recon_run``
    status) supersedes on the read side.
    """

    def __init__(
        self,
        *,
        workspace_id: str,
        recon_run_id: UUID,
        lane: str,
        conn_factory: ConnFactory | None = None,
    ) -> None:
        self._workspace_id = workspace_id
        self._recon_run_id = recon_run_id
        self._lane = lane
        self._conn_factory = conn_factory

    async def __call__(
        self,
        conn: AsyncConnection,
        field_key: str,
        status: FieldProgressStatus,
    ) -> None:
        payload: dict[str, JsonValue] = {
            "kind": RECON_FIELD_PROGRESS_KIND,
            "recon_run_id": str(self._recon_run_id),
            "lane": self._lane,
            "field_key": field_key,
            "status": status.value,
        }
        try:
            if self._conn_factory is not None:
                async with self._conn_factory() as own:
                    await self._emit(own, payload)
            else:
                # The event rides the lane's own transaction, so a failed INSERT is contained in a
                # savepoint: swallowing it otherwise leaves the caller with an *aborted*
                # transaction — observability failing the lane after all, one statement later.
                async with conn.begin_nested():
                    await self._emit(conn, payload)
        except Exception:  # noqa: BLE001 - a progress event may never fail the recon lane
            log.warning(
                "stage0.recon.field_event_emit_failed",
                workspace_id=self._workspace_id,
                recon_run_id=str(self._recon_run_id),
                lane=self._lane,
                field_key=field_key,
                status=status.value,
                exc_info=True,
            )

    async def _emit(self, conn: AsyncConnection, payload: dict[str, JsonValue]) -> None:
        await emit_run_event(
            conn,
            workspace_id=self._workspace_id,
            run_id=ProjectRunId(self._recon_run_id),
            topic=RunEventTopic.STEP_PROGRESS.value,
            payload=payload,
        )


__all__ = ["ReconFieldProgressEmitter"]
