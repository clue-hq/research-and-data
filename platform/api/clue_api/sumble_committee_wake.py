"""Durable wake worker for asynchronous Sumble committee acquisition.

The provider coordinator owns submit/poll and spend settlement.  This worker only re-offers the
owning project run when a persisted committee operation becomes due, so the provider-neutral DEEP
phase can resume from its ``WAITING_EXTERNAL`` checkpoint.  Queue deduplication makes concurrent
wakers safe and prevents a due row from creating duplicate run work.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from clue_core import ProjectRunId
from clue_db import ConnFactory, transaction
from clue_research.durable import list_due_committee_acquisition_project_runs

ProjectRunWaker = Callable[[ProjectRunId], Awaitable[bool]]


class SumbleCommitteeWakeWorker:
    """Offer each due committee acquisition's owning run back to the fleet once."""

    def __init__(
        self,
        *,
        project_run_waker: ProjectRunWaker,
        conn_factory: ConnFactory = transaction,
        batch_limit: int = 100,
    ) -> None:
        if batch_limit < 1:
            raise ValueError("Sumble committee wake batch limit must be positive")
        self._project_run_waker = project_run_waker
        self._conn_factory = conn_factory
        self._batch_limit = batch_limit

    async def run_due(self, *, now: datetime | None = None) -> int:
        observed_at = now or datetime.now(UTC)
        async with self._conn_factory() as conn:
            project_run_ids = await list_due_committee_acquisition_project_runs(
                conn,
                now=observed_at,
                limit=self._batch_limit,
            )
        offered = 0
        for project_run_id in project_run_ids:
            if await self._project_run_waker(project_run_id):
                offered += 1
        return offered


__all__ = ["ProjectRunWaker", "SumbleCommitteeWakeWorker"]
