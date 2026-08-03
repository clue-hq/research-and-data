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

from clue_core import EntityType, OperationId, ResearchSubjectRef, ResearchViewComposer
from clue_db import ConnFactory, transaction
from clue_research.durable import append_subject_activity
from clue_research.narrative import (
    ActivityReferenceReader,
    CanonicalSubjectReader,
    CommitteeViewReader,
    CoverageViewReader,
    DerivedClaimReader,
    DeterministicResearchViewComposer,
    DirectClaimReader,
    FitResultReader,
    GovernedResearchOperationRequest,
    GovernedResearchOperationRequester,
    ResearchViewRecheckService,
    ResearchViewSnapshotService,
    SnapshotReachabilityReader,
    StatementGovernanceReader,
)
from clue_toolbelt import ToolContext, ToolInvoker


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
                               ce.account_entity_id AS parent_account_id,
                               COALESCE(ce.canonical_version, ae.canonical_version)
                                   AS canonical_version
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
                canonical_entity_version=int(row[3]),
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


class ToolInvokerResearchOperationRequester:
    """C7.5 adapter onto the existing replay-certified, budget-gated deep-account tool.

    The adapter chooses no model, source, threshold, quality mode, or evidence policy. It recovers
    the exact run-pinned ICP and latest durable account tier, then lets ``ToolInvoker`` and the
    existing tool own admission, journaling, budget, pre-spend checks, and replay.
    """

    def __init__(
        self,
        tool_invoker: ToolInvoker,
        *,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._tool_invoker = tool_invoker
        self._conn_factory = conn_factory

    async def request(self, request: GovernedResearchOperationRequest) -> OperationId:
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT pr.icp_key, ar.tier
                        FROM project_run pr
                        JOIN LATERAL (
                            SELECT tier
                            FROM account_run
                            WHERE project_run_id = pr.id
                              AND entity_id = :account_entity_id
                            ORDER BY updated_at DESC, id DESC
                            LIMIT 1
                        ) ar ON true
                        WHERE pr.id = :project_run_id
                          AND pr.workspace_id = :workspace_id
                          AND pr.project_id = :project_id
                        """
                    ),
                    {
                        "account_entity_id": str(request.account_entity_id),
                        "project_run_id": str(request.project_run_id),
                        "workspace_id": request.workspace_id,
                        "project_id": request.project_id,
                    },
                )
            ).first()
        if row is None:
            raise ValueError(
                "governed re-research requires an existing account run in the exact project scope"
            )
        await self._tool_invoker.invoke(
            "run_deep_account",
            {
                "account_entity_id": str(request.account_entity_id),
                "icp_key": str(row[0]),
                "tier": str(row[1]),
                "project_run_id": str(request.project_run_id),
            },
            ToolContext(
                workspace_id=request.workspace_id,
                actor="human",
                conn_factory=self._conn_factory,
                operation_id=request.operation_id,
            ),
            version="1",
        )
        return request.operation_id


def build_research_view_recheck_service(
    snapshots: ResearchViewSnapshotService,
    *,
    tool_invoker: ToolInvoker | None = None,
    conn_factory: ConnFactory = transaction,
    clock: Callable[[], datetime] | None = None,
) -> ResearchViewRecheckService:
    """Build C7.5 over the shared C7.4 snapshot service and optional governed operation seam."""

    requester: GovernedResearchOperationRequester | None = (
        ToolInvokerResearchOperationRequester(
            tool_invoker,
            conn_factory=conn_factory,
        )
        if tool_invoker is not None
        else None
    )
    return ResearchViewRecheckService(
        snapshots=snapshots,
        research_requester=requester,
        subject_activity_appender=append_subject_activity,
        conn_factory=conn_factory,
        clock=clock,
    )
