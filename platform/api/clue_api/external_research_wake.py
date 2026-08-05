"""Provider-neutral due-operation dispatcher for the existing detached fleet (M8C C6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    list_due_committee_acquisition_project_runs,
    list_due_contact_channel_project_runs,
    list_due_contact_external_research_project_runs,
)

ProjectRunWaker = Callable[[ProjectRunId], Awaitable[bool]]
ExternalResearchWakeSource = Callable[
    [AsyncConnection, datetime, int], Awaitable[Sequence[ProjectRunId]]
]


async def _committee_due(
    conn: AsyncConnection, now: datetime, limit: int
) -> Sequence[ProjectRunId]:
    return await list_due_committee_acquisition_project_runs(conn, now=now, limit=limit)


async def _contact_external_due(
    conn: AsyncConnection, now: datetime, limit: int
) -> Sequence[ProjectRunId]:
    return await list_due_contact_external_research_project_runs(conn, now=now, limit=limit)


async def _channel_due(conn: AsyncConnection, now: datetime, limit: int) -> Sequence[ProjectRunId]:
    return await list_due_contact_channel_project_runs(conn, now=now, limit=limit)


def registered_external_research_wake_sources(
    *,
    committee_enabled: bool,
    contact_external_enabled: bool,
    contact_channel_enabled: bool,
) -> tuple[ExternalResearchWakeSource, ...]:
    """Compile the exact enabled wake registry; disabled sources are never even scanned."""

    sources: list[ExternalResearchWakeSource] = []
    if committee_enabled:
        sources.append(_committee_due)
    if contact_external_enabled:
        sources.append(_contact_external_due)
    if contact_channel_enabled:
        sources.append(_channel_due)
    return tuple(sources)


class ExternalResearchWakeDispatcher:
    """Re-offer owning runs; provider polling remains inside registered preparation adapters."""

    def __init__(
        self,
        *,
        project_run_waker: ProjectRunWaker,
        sources: Sequence[ExternalResearchWakeSource] = (
            _committee_due,
            _contact_external_due,
            _channel_due,
        ),
        conn_factory: ConnFactory = transaction,
        batch_limit: int = 100,
    ) -> None:
        if batch_limit < 1:
            raise ValueError("external-research wake batch limit must be positive")
        self._project_run_waker = project_run_waker
        self._sources = tuple(sources)
        self._conn_factory = conn_factory
        self._batch_limit = batch_limit

    async def run_due(self, *, now: datetime | None = None) -> int:
        observed_at = now or datetime.now(UTC)
        run_ids: list[ProjectRunId] = []
        async with self._conn_factory() as conn:
            for source in self._sources:
                run_ids.extend(await source(conn, observed_at, self._batch_limit))
        offered = 0
        for project_run_id in tuple(dict.fromkeys(run_ids))[: self._batch_limit]:
            if await self._project_run_waker(project_run_id):
                offered += 1
        return offered


__all__ = [
    "ExternalResearchWakeDispatcher",
    "ExternalResearchWakeSource",
    "ProjectRunWaker",
    "registered_external_research_wake_sources",
]
