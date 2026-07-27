"""C7 research-view tools.

C7.5 supplies the replay-certified re-check tool. Central registry activation stays with the C7.7
serving cutover, when the complete research-view composer/read surface is composed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar
from uuid import UUID

from pydantic import Field
from sqlalchemy import text

from clue_api.tool_outputs import ResearchViewChangeReportOutput
from clue_core import (
    EntityId,
    ResearchSectionKind,
    ResearchViewRecheckRequest,
    ResearchViewSnapshotId,
)
from clue_research.narrative import ResearchViewRecheckService
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


class RecheckResearchViewInput(ToolInput):
    project_id: str = Field(min_length=1)
    subject_entity_id: UUID
    snapshot_id: UUID
    section_kinds: tuple[ResearchSectionKind, ...] = ()
    request_research: bool = False


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

    def __init__(self, service: ResearchViewRecheckService) -> None:
        self._service = service

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RecheckResearchViewInput)
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
    service: ResearchViewRecheckService,
) -> tuple[Tool, ...]:
    """Return the C7 tool set available at this slice for C7.7 registry activation."""

    return (RecheckResearchViewTool(service),)
