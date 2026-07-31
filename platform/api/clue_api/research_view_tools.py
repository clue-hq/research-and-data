"""C7 research-view tools.

All three tools delegate to the one deterministic composer/snapshot/re-check path.  In particular,
``compose_dossier@1`` is the retained compatibility name for composing a structured research-view
receipt; it never creates a rendered dossier body or a second persistence model.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from pydantic import Field
from sqlalchemy import text

from clue_api.tool_outputs import (
    ResearchViewChangeReportOutput,
    ResearchViewReceiptOutput,
    ResearchViewRefOutput,
)
from clue_core import (
    EntityId,
    ProjectRunId,
    ResearchSectionKind,
    ResearchViewComposer,
    ResearchViewReadRequest,
    ResearchViewRecheckRequest,
    ResearchViewRef,
    ResearchViewSnapshotId,
)
from clue_research.narrative import (
    ResearchViewRecheckService,
    ResearchViewSnapshotCommand,
    ResearchViewSnapshotService,
    append_research_view_event,
)
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)


class ResearchViewScopeInput(ToolInput):
    project_id: str = Field(min_length=1)
    project_run_id: UUID
    subject_entity_id: UUID
    product_id: str | None = Field(default=None, min_length=1)


class ComposeDossierInput(ResearchViewScopeInput):
    supersedes_snapshot_id: UUID | None = None


class GetResearchViewInput(ResearchViewScopeInput):
    pass


class RecheckResearchViewInput(ToolInput):
    project_id: str = Field(min_length=1)
    subject_entity_id: UUID
    snapshot_id: UUID
    section_kinds: tuple[ResearchSectionKind, ...] = ()
    request_research: bool = False


class _ResearchViewScopeTool(Tool):
    """Shared fail-closed authorization for exact project/run/product/subject scope."""

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ResearchViewScopeInput)
        async with ctx.conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM project p
                        JOIN project_run pr
                          ON pr.project_id = p.project_id
                         AND pr.workspace_id = p.workspace_id
                        WHERE p.project_id = :project_id
                          AND p.workspace_id = :workspace_id
                          AND pr.id = CAST(:project_run_id AS uuid)
                          AND p.product_id IS NOT DISTINCT FROM :product_id
                          AND (
                              pr.product_id IS NULL
                              OR pr.product_id IS NOT DISTINCT FROM :product_id
                          )
                          AND (
                              EXISTS (
                                  SELECT 1
                                  FROM account_entity ae
                                  JOIN account_run ar
                                    ON ar.entity_id = ae.id
                                   AND ar.project_run_id = pr.id
                                  WHERE ae.id = CAST(:subject_entity_id AS uuid)
                                    AND ae.workspace_id = :workspace_id
                                    AND ae.merged_into IS NULL
                              )
                              OR EXISTS (
                                  SELECT 1
                                  FROM contact_entity ce
                                  JOIN account_run ar
                                    ON ar.entity_id = ce.account_entity_id
                                   AND ar.project_run_id = pr.id
                                  WHERE ce.id = CAST(:subject_entity_id AS uuid)
                                    AND ce.workspace_id = :workspace_id
                                    AND ce.merged_into IS NULL
                              )
                          )
                        """
                    ),
                    {
                        "project_id": inputs.project_id,
                        "workspace_id": ctx.workspace_id,
                        "project_run_id": inputs.project_run_id,
                        "product_id": inputs.product_id,
                        "subject_entity_id": inputs.subject_entity_id,
                    },
                )
            ).first()
        if row is None:
            return (
                PreconditionFailure(
                    reason_code="research_view_subject_not_found",
                    message=(
                        "no canonical research subject exists in the exact "
                        "workspace/project/run/product scope"
                    ),
                ),
            )
        return ()

    @staticmethod
    def _request(inputs: ResearchViewScopeInput, ctx: ToolContext) -> ResearchViewReadRequest:
        return ResearchViewReadRequest(
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
            project_run_id=ProjectRunId(inputs.project_run_id),
            subject_entity_id=EntityId(inputs.subject_entity_id),
            product_id=inputs.product_id,
        )


class ComposeDossierTool(_ResearchViewScopeTool):
    """Compose one structured research-view receipt, never a rendered dossier document."""

    name = "compose_dossier"
    version = "1"
    input_model: ClassVar[type[ToolInput]] = ComposeDossierInput
    output_model: ClassVar[type[ToolOutput]] = ResearchViewReceiptOutput
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + ToolContext.operation_id + exact research-view scope",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes="the snapshot receipt is append-only and unique on workspace + operation id",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=(
            "project_id",
            "project_run_id",
            "subject_entity_id",
            "product_id",
            "supersedes_snapshot_id",
        )
    )
    pin_requirements: ClassVar[tuple[str, ...]] = (
        "project_run",
        "field_registry",
        "verification_policy",
    )

    def __init__(self, service: ResearchViewSnapshotService | None) -> None:
        self._service = service

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        if self._service is None:
            return (
                PreconditionFailure(
                    reason_code="research_view_not_configured",
                    message="the research-view composer is not configured in this process",
                ),
            )
        return await super().preconditions(inputs, ctx)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ComposeDossierInput)
        assert self._service is not None
        receipt = await self._service.compose_and_save(
            ResearchViewSnapshotCommand(
                operation_id=ctx.operation_id,
                request=self._request(inputs, ctx),
                supersedes_snapshot_id=(
                    ResearchViewSnapshotId(inputs.supersedes_snapshot_id)
                    if inputs.supersedes_snapshot_id is not None
                    else None
                ),
            )
        )
        async with ctx.conn_factory() as conn:
            section_ids = tuple(
                str(row[0])
                for row in (
                    await conn.execute(
                        text(
                            """
                            SELECT section_id
                            FROM research_view_snapshot_section
                            WHERE snapshot_id = CAST(:snapshot_id AS uuid)
                            ORDER BY ordinal
                            """
                        ),
                        {"snapshot_id": receipt.snapshot_id},
                    )
                ).all()
            )
            await append_research_view_event(
                conn,
                event_key=f"snapshot:{receipt.snapshot_id}:updated",
                topic="research_view.updated",
                workspace_id=receipt.workspace_id,
                project_id=receipt.project_id,
                project_run_id=UUID(str(receipt.project_run_id)),
                subject_entity_id=UUID(str(receipt.subject.entity_id)),
                snapshot_id=receipt.snapshot_id,
                report_id=None,
                section_ids=section_ids,
                item_ids=(),
                reason_codes=("snapshot_composed",),
                fetch_ref=receipt.fetch_ref,
                created_at=datetime.now(UTC),
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=receipt.model_dump(mode="json"),
        )


class GetResearchViewTool(_ResearchViewScopeTool):
    """Resolve the live governed view and return only its stable fetch reference and hashes."""

    name = "get_research_view"
    version = "1"
    input_model: ClassVar[type[ToolInput]] = GetResearchViewInput
    output_model: ClassVar[type[ToolOutput]] = ResearchViewRefOutput
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="exact workspace/project/run/product/subject read",
        operation_id_required=False,
        external_boundary=ExternalReplayBoundary.NONE,
        notes="the tool resolves current authority and returns references only",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.READ
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=(
            "project_id",
            "project_run_id",
            "subject_entity_id",
            "product_id",
        )
    )
    pin_requirements: ClassVar[tuple[str, ...]] = (
        "project_run",
        "field_registry",
        "verification_policy",
    )

    def __init__(self, composer: ResearchViewComposer | None) -> None:
        self._composer = composer

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        if self._composer is None:
            return (
                PreconditionFailure(
                    reason_code="research_view_not_configured",
                    message="the research-view composer is not configured in this process",
                ),
            )
        return await super().preconditions(inputs, ctx)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, GetResearchViewInput)
        assert self._composer is not None
        view = await self._composer.compose(self._request(inputs, ctx))
        async with ctx.conn_factory() as conn:
            snapshot_id = (
                await conn.execute(
                    text(
                        """
                        SELECT snapshot_id
                        FROM research_view_snapshot
                        WHERE workspace_id = :workspace_id
                          AND project_id = :project_id
                          AND project_run_id = CAST(:project_run_id AS uuid)
                          AND subject_entity_id = CAST(:subject_entity_id AS uuid)
                          AND product_id IS NOT DISTINCT FROM :product_id
                          AND source_state_sha256 = :source_state_sha256
                        ORDER BY created_at DESC, snapshot_id DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "workspace_id": ctx.workspace_id,
                        "project_id": inputs.project_id,
                        "project_run_id": inputs.project_run_id,
                        "subject_entity_id": inputs.subject_entity_id,
                        "product_id": inputs.product_id,
                        "source_state_sha256": view.source_state_sha256,
                    },
                )
            ).scalar_one_or_none()
        ref = ResearchViewRef(
            view_id=view.view_id,
            snapshot_id=(ResearchViewSnapshotId(snapshot_id) if snapshot_id is not None else None),
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
            subject_entity_id=EntityId(inputs.subject_entity_id),
            product_id=inputs.product_id,
            source_state_sha256=view.source_state_sha256,
            fetch_ref=f"research-view:{view.view_id}",
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=ref.model_dump(mode="json"),
        )


class RecheckResearchViewTool(Tool):
    """Thin tool envelope over the additive C7.5 service."""

    name = "recheck_research_view"
    version = "1"
    input_model: ClassVar[type[ToolInput]] = RecheckResearchViewInput
    output_model: ClassVar[type[ToolOutput]] = ResearchViewChangeReportOutput
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + ToolContext.operation_id + old snapshot",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes="stable child research/snapshot ids make every crash boundary replay-safe",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=(
            "project_id",
            "subject_entity_id",
            "snapshot_id",
            "section_kinds",
            "request_research",
        )
    )
    pin_requirements: ClassVar[tuple[str, ...]] = (
        "project_run",
        "field_registry",
        "verification_policy",
    )

    def __init__(self, service: ResearchViewRecheckService | None) -> None:
        self._service = service

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RecheckResearchViewInput)
        if self._service is None:
            return (
                PreconditionFailure(
                    reason_code="research_view_not_configured",
                    message="the research-view re-check service is not configured in this process",
                ),
            )
        row = None
        async with ctx.conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM research_view_snapshot
                        WHERE snapshot_id = CAST(:snapshot_id AS uuid)
                          AND workspace_id = :workspace_id
                          AND project_id = :project_id
                          AND subject_entity_id = CAST(:subject_entity_id AS uuid)
                        """
                    ),
                    {
                        "snapshot_id": inputs.snapshot_id,
                        "workspace_id": ctx.workspace_id,
                        "project_id": inputs.project_id,
                        "subject_entity_id": inputs.subject_entity_id,
                    },
                )
            ).first()
        if row is None:
            return (
                PreconditionFailure(
                    reason_code="research_view_snapshot_not_found",
                    message="no research-view snapshot exists in the exact requested scope",
                ),
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RecheckResearchViewInput)
        assert self._service is not None
        report = await self._service.recheck(
            ResearchViewRecheckRequest(
                operation_id=ctx.operation_id,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                subject_entity_id=EntityId(inputs.subject_entity_id),
                snapshot_id=ResearchViewSnapshotId(inputs.snapshot_id),
                section_kinds=tuple(inputs.section_kinds),
                request_research=inputs.request_research,
            )
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=report.model_dump(mode="json"),
        )


def build_research_view_tools(
    *,
    composer: ResearchViewComposer | None,
    snapshots: ResearchViewSnapshotService | None,
    recheck: ResearchViewRecheckService | None,
) -> tuple[Tool, ...]:
    """Return all exact C7.7 contracts, fail-closed when a process lacks serving collaborators."""

    return (
        ComposeDossierTool(snapshots),
        GetResearchViewTool(composer),
        RecheckResearchViewTool(recheck),
    )
