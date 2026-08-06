"""Provider-neutral preparation seam before buying-committee materialization.

Implementations may submit or poll external provider work, but they do so before the orchestrator
opens the short claim/spend transaction.  A ready result may replace the statically configured
committee sources with snapshot-backed readers for this account only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from clue_core import EntityId, ExternalResearchPreparation, ProjectRunId, RunId
from clue_research.profiling import CommitteeSource


@dataclass(frozen=True, slots=True)
class PreparedCommitteeSources:
    """Preparation metadata plus optional per-account ready snapshot readers.

    ``sources=None`` preserves the orchestrator's statically configured sources.  An explicit empty
    tuple means the preparation intentionally produced no committee source.
    """

    preparation: ExternalResearchPreparation
    sources: tuple[CommitteeSource, ...] | None = None


@runtime_checkable
class CommitteePreparer(Protocol):
    """Acquire or reconcile committee inputs outside the committee claim transaction."""

    async def prepare(
        self,
        *,
        account_entity_id: EntityId,
        account_run_id: RunId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        tier: str,
    ) -> PreparedCommitteeSources: ...


class ExternalCommitteePreparationFailed(RuntimeError):
    """A terminal external preparation failure that must not enter materialization."""


__all__ = [
    "CommitteePreparer",
    "ExternalCommitteePreparationFailed",
    "PreparedCommitteeSources",
]
