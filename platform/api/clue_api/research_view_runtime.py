"""Complete production composition root for C7 research-view serving."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.evidence_access import (
    EphemeralEvidenceCapabilityBroker,
    EvidenceAccessServiceImpl,
)
from clue_api.research_view_governance import (
    CurrentStatementGovernanceEvaluator,
    ProductionEvidenceAccessAuthorizer,
    ProductionStatementGovernanceReader,
)
from clue_api.research_view_owner_refs import ProductionOwnerReferenceResolver
from clue_api.research_view_readers import (
    DbActivityReferenceReader,
    DbCanonicalSubjectReader,
    DbCommitteeViewReader,
    DbCoverageViewReader,
    DbDerivedClaimReader,
    DbDirectClaimReader,
    DbFitResultReader,
    ResearchViewScopeNotFound,
    ResearchViewScopeResolver,
)
from clue_api.research_view_wiring import (
    ToolInvokerResearchOperationRequester,
    build_research_view_composer,
    build_research_view_snapshot_service,
)
from clue_core import OperationId, ResearchView, ResearchViewReadRequest
from clue_db import ConnFactory, repeatable_read_transaction, transaction
from clue_research.durable import append_subject_activity
from clue_research.narrative import (
    GovernedResearchOperationRequest,
    GovernedResearchOperationRequester,
    ResearchViewCompositionError,
    ResearchViewRecheckService,
    ResearchViewSnapshotService,
)
from clue_storage import StorageBackend
from clue_toolbelt import ToolInvoker


class ProductionResearchViewComposer:
    """Open one repeatable-read snapshot and install connection-bound real readers."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = repeatable_read_transaction,
        scope_resolver: ResearchViewScopeResolver | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._scope_resolver = scope_resolver or ResearchViewScopeResolver()

    async def compose(self, request: ResearchViewReadRequest) -> ResearchView:
        async with self._conn_factory() as conn:
            return await self.compose_on_connection(conn, request)

    async def compose_on_connection(
        self,
        conn: AsyncConnection,
        request: ResearchViewReadRequest,
    ) -> ResearchView:
        """Compose inside an existing request snapshot for owner-reference batch resolution."""

        try:
            scope = await self._scope_resolver.resolve(conn, request)
        except ResearchViewScopeNotFound as exc:
            raise ResearchViewCompositionError("subject_not_found") from exc
        evaluator = CurrentStatementGovernanceEvaluator(
            conn,
            member_entity_ids=scope.canonical_member_entity_ids,
            allowed_run_ids=(
                str(request.project_run_id),
                str(scope.account_run.id),
            ),
        )
        composer = build_research_view_composer(
            subjects=DbCanonicalSubjectReader(scope),
            direct_claims=DbDirectClaimReader(conn, scope),
            derived_claims=DbDerivedClaimReader(conn, scope),
            fit=DbFitResultReader(conn, scope),
            committee=DbCommitteeViewReader(conn, scope),
            coverage=DbCoverageViewReader(conn, scope),
            activity=DbActivityReferenceReader(conn, scope),
            governance=ProductionStatementGovernanceReader(evaluator),
        )
        return await composer.compose(request)


class DeferredGovernedResearchOperationRequester:
    """Break the recheck/tool-registry cycle without permitting a silent no-op."""

    def __init__(self) -> None:
        self._delegate: GovernedResearchOperationRequester | None = None

    @property
    def is_bound(self) -> bool:
        return self._delegate is not None

    def bind(self, delegate: GovernedResearchOperationRequester) -> None:
        if self._delegate is not None:
            raise RuntimeError("governed research requester is already bound")
        self._delegate = delegate

    async def request(self, request: GovernedResearchOperationRequest) -> OperationId:
        if self._delegate is None:
            raise RuntimeError("governed research requester is not bound")
        return await self._delegate.request(request)


@dataclass(frozen=True)
class ProductionResearchViewRuntime:
    composer: ProductionResearchViewComposer
    snapshots: ResearchViewSnapshotService
    recheck: ResearchViewRecheckService
    evidence_access: EvidenceAccessServiceImpl
    owner_references: ProductionOwnerReferenceResolver
    deferred_requester: DeferredGovernedResearchOperationRequester

    def bind_tool_invoker(
        self,
        tool_invoker: ToolInvoker,
        *,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self.deferred_requester.bind(
            ToolInvokerResearchOperationRequester(
                tool_invoker,
                conn_factory=conn_factory,
            )
        )


def build_production_research_view_composer(
    *,
    conn_factory: ConnFactory = repeatable_read_transaction,
) -> ProductionResearchViewComposer:
    """The real production caller of the low-level eight-reader composer factory."""

    return ProductionResearchViewComposer(conn_factory=conn_factory)


def build_production_research_view_runtime(
    *,
    storage: StorageBackend,
    read_conn_factory: ConnFactory = repeatable_read_transaction,
    write_conn_factory: ConnFactory = transaction,
) -> ProductionResearchViewRuntime:
    """Build every C7 collaborator; callers bind the ToolInvoker exactly once afterward."""

    composer = build_production_research_view_composer(conn_factory=read_conn_factory)
    snapshots = build_research_view_snapshot_service(
        composer,
        conn_factory=write_conn_factory,
    )
    deferred = DeferredGovernedResearchOperationRequester()
    recheck = ResearchViewRecheckService(
        snapshots=snapshots,
        research_requester=deferred,
        subject_activity_appender=append_subject_activity,
        conn_factory=write_conn_factory,
    )
    authorizer = ProductionEvidenceAccessAuthorizer(
        conn_factory=read_conn_factory,
    )
    evidence_access = EvidenceAccessServiceImpl(
        authorizer,
        storage,
        EphemeralEvidenceCapabilityBroker(),
        conn_factory=write_conn_factory,
    )
    owner_references = ProductionOwnerReferenceResolver(
        composer,
        conn_factory=read_conn_factory,
    )
    return ProductionResearchViewRuntime(
        composer=composer,
        snapshots=snapshots,
        recheck=recheck,
        evidence_access=evidence_access,
        owner_references=owner_references,
        deferred_requester=deferred,
    )


__all__ = [
    "DeferredGovernedResearchOperationRequester",
    "ProductionResearchViewComposer",
    "ProductionResearchViewRuntime",
    "build_production_research_view_composer",
    "build_production_research_view_runtime",
]
