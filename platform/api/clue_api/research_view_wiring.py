"""API-root wiring for C7 deterministic research-view composition.

Concrete owner adapters are deliberately assembled here, the one package allowed to import every
subsystem. C7.3 exposes this factory so later API/tool/snapshot slices share one composer rather
than creating parallel dossier implementations.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from clue_core import EntityType, ResearchSubjectRef, ResearchViewComposer
from clue_db import ConnFactory, transaction
from clue_research.narrative import (
    ActivityReferenceReader,
    CanonicalSubjectReader,
    CommitteeViewReader,
    CoverageViewReader,
    DerivedClaimReader,
    DeterministicResearchViewComposer,
    DirectClaimReader,
    FitResultReader,
    ResearchViewSnapshotService,
    SnapshotReachabilityReader,
    StatementGovernanceReader,
)


def build_research_view_composer(
    *,
    subjects: CanonicalSubjectReader,
    direct_claims: DirectClaimReader,
    derived_claims: DerivedClaimReader,
    fit: FitResultReader,
    committee: CommitteeViewReader,
    coverage: CoverageViewReader,
    activity: ActivityReferenceReader,
    governance: StatementGovernanceReader,
    clock: Callable[[], datetime] | None = None,
) -> DeterministicResearchViewComposer:
    """Construct the sole C7 live composer from concrete/injected owner readers."""

    return DeterministicResearchViewComposer(
        subjects=subjects,
        direct_claims=direct_claims,
        derived_claims=derived_claims,
        fit=fit,
        committee=committee,
        coverage=coverage,
        activity=activity,
        governance=governance,
        clock=clock,
    )


class ClaimSnapshotReachabilityReader:
    """API-root adapter from claim ids to exact reachable subjects for DSAR indexing."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def subjects_for_claims(
        self,
        *,
        workspace_id: str,
        claim_ids: tuple[UUID, ...],
    ) -> tuple[ResearchSubjectRef, ...]:
        if not claim_ids:
            return ()
        async with self._conn_factory() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT DISTINCT c.entity_id, c.entity_type,
                               ce.account_entity_id AS parent_account_id
                        FROM claim c
                        LEFT JOIN contact_entity ce
                          ON c.entity_type = 'contact' AND ce.id = c.entity_id
                        LEFT JOIN account_entity ae
                          ON c.entity_type = 'account' AND ae.id = c.entity_id
                        WHERE c.id = ANY(CAST(:claim_ids AS uuid[]))
                          AND (
                              c.reuse_scope = 'public_footprint'
                              OR c.workspace_id = :workspace_id
                          )
                          AND (
                              (c.entity_type = 'contact' AND ce.workspace_id = :workspace_id)
                              OR
                              (c.entity_type = 'account' AND ae.workspace_id = :workspace_id)
                          )
                        ORDER BY c.entity_type, c.entity_id
                        """
                    ),
                    {
                        "claim_ids": [str(value) for value in claim_ids],
                        "workspace_id": workspace_id,
                    },
                )
            ).all()
        return tuple(
            ResearchSubjectRef(
                entity_id=row[0],
                entity_type=EntityType(row[1]),
                # Entity rows do not yet expose a durable revision counter. C7.4's reachability
                # table indexes identity only; version 1 is therefore a non-authoritative adapter
                # value and is never persisted by the subject index.
                canonical_entity_version=1,
                parent_account_id=row[2],
            )
            for row in rows
        )


def build_research_view_snapshot_service(
    composer: ResearchViewComposer,
    *,
    conn_factory: ConnFactory = transaction,
    clock: Callable[[], datetime] | None = None,
) -> ResearchViewSnapshotService:
    """Build the C7.4 receipt service with the API-root claim reachability adapter."""

    reachability: SnapshotReachabilityReader = ClaimSnapshotReachabilityReader(
        conn_factory=conn_factory
    )
    return ResearchViewSnapshotService(
        composer,
        reachability,
        conn_factory=conn_factory,
        clock=clock,
    )
