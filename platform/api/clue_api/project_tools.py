"""Governed project-label mutation for the human project sidebar."""

from collections.abc import Sequence
from typing import Annotated, ClassVar

from pydantic import Field, StringConstraints

from clue_db import ConnFactory, transaction
from clue_spine import get_project_for_workspace, set_project_name
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)


class RenameProjectInput(ToolInput):
    project_id: str = Field(min_length=1, max_length=255)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RenameProjectOutput(ToolOutput):
    id: str
    title: str


class RenameProjectTool(Tool):
    name = "rename_project"
    version = "1"
    model_description = "Rename a project without changing its contents or identity."
    input_model: ClassVar[type[ToolInput]] = RenameProjectInput
    output_model: ClassVar[type[ToolOutput]] = RenameProjectOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project(project_id, workspace_id)",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id",))

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RenameProjectInput)
        async with self._conn_factory() as conn:
            project = await get_project_for_workspace(
                conn, workspace_id=ctx.workspace_id, project_id=inputs.project_id
            )
        if project is None:
            return (
                PreconditionFailure(
                    reason_code="project_not_found", message="no such project in this workspace"
                ),
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RenameProjectInput)
        async with self._conn_factory() as conn:
            project = await set_project_name(
                conn, workspace_id=ctx.workspace_id, project_id=inputs.project_id, name=inputs.title
            )
        if project is None:
            raise ValueError("project disappeared from its workspace during the rename")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"id": project.project_id, "title": project.name},
        )
