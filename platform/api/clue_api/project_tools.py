"""Governed project-row mutation for the human projects directory and sidebar.

Five tools — ``rename_project@1`` plus the projects-directory set ``create_project@1``,
``update_project_details@1``, ``set_project_pinned@1`` and ``set_project_archived@1``. They are
tools rather than endpoint bodies because Doc A makes the toolbelt the only write path, so every
project-row change inherits parameter snapshotting, the execution journal and A9 idempotency.

All five are **ungranted**: the C6 authority map gives them to no model role. A project is a
human's filing cabinet — naming it, pinning it and archiving it are the human's decisions, and an
agent that could archive a project could hide its own work.
"""

from collections.abc import Sequence
from typing import Annotated, ClassVar

from pydantic import Field, StringConstraints
from sqlalchemy import text

from clue_db import ConnFactory, transaction
from clue_projections import threads_running
from clue_spine import (
    UNTITLED_PROJECT_NAME,
    Project,
    create_project,
    get_brand,
    get_project_for_workspace,
    set_project_archived,
    set_project_name,
    set_project_pinned,
    update_project_details,
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


class _ProjectMutationTool(Tool):
    """Shared precondition: the project exists in this workspace and is a marketing project.

    A ``system`` project (the invisible scope anchor onboarding writes against) refuses with the
    *not-found* sentence on purpose — it is not a project the human filed, so naming it in an
    error would disclose a row the directory never shows.
    """

    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id",))

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        # Shell state only: no model call, no provider call, no external spend.
        return ToolEstimate.free()

    async def _project(self, *, workspace_id: str, project_id: str) -> Project | None:
        async with self._conn_factory() as conn:
            return await get_project_for_workspace(
                conn, workspace_id=workspace_id, project_id=project_id
            )

    @staticmethod
    def _shared_failures(project: Project | None) -> tuple[PreconditionFailure, ...]:
        if project is None:
            return (
                PreconditionFailure(
                    reason_code="project_not_found", message="no such project in this workspace"
                ),
            )
        if project.kind == "system":
            return (
                PreconditionFailure(
                    reason_code="project_system", message="no such project in this workspace"
                ),
            )
        return ()


_Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_Description = Annotated[str, StringConstraints(max_length=2000)]


class CreateProjectInput(ToolInput):
    project_id: str = Field(min_length=1, max_length=255)
    brand_id: str = Field(min_length=1, max_length=255)
    title: _Title
    description: _Description = ""


class CreateProjectOutput(ToolOutput):
    id: str
    title: str


class CreateProjectTool(_ProjectMutationTool):
    name = "create_project"
    version = "1"
    model_description = "Create an empty marketing project with a human-given title and objective."
    input_model: ClassVar[type[ToolInput]] = CreateProjectInput
    output_model: ClassVar[type[ToolOutput]] = CreateProjectOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project(project_id, workspace_id)",
        external_boundary=ExternalReplayBoundary.NONE,
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, CreateProjectInput)
        if inputs.title == UNTITLED_PROJECT_NAME:
            return (
                PreconditionFailure(
                    reason_code="project_title_reserved", message="choose a project name"
                ),
            )
        async with self._conn_factory() as conn:
            brand = await get_brand(conn, workspace_id=ctx.workspace_id, brand_id=inputs.brand_id)
        if brand is None:
            return (
                PreconditionFailure(
                    reason_code="brand_not_found", message="no such brand in this workspace"
                ),
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, CreateProjectInput)
        async with self._conn_factory() as conn:
            existing = await get_project_for_workspace(
                conn, workspace_id=ctx.workspace_id, project_id=inputs.project_id
            )
            project = existing or await create_project(
                conn,
                workspace_id=ctx.workspace_id,
                brand_id=inputs.brand_id,
                name=inputs.title,
                project_id=inputs.project_id,
                status="active",
                description=inputs.description,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"id": project.project_id, "title": project.name},
        )


class UpdateProjectDetailsInput(ToolInput):
    project_id: str = Field(min_length=1, max_length=255)
    title: _Title
    description: _Description


class UpdateProjectDetailsTool(_ProjectMutationTool):
    name = "update_project_details"
    version = "1"
    model_description = "Change a project's title and objective without changing its identity."
    input_model: ClassVar[type[ToolInput]] = UpdateProjectDetailsInput
    output_model: ClassVar[type[ToolOutput]] = RenameProjectOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project(project_id, workspace_id)",
        external_boundary=ExternalReplayBoundary.NONE,
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, UpdateProjectDetailsInput)
        project = await self._project(workspace_id=ctx.workspace_id, project_id=inputs.project_id)
        shared = self._shared_failures(project)
        if shared or project is None:
            return shared
        if project.status == "archived":
            return (
                PreconditionFailure(
                    reason_code="project_archived",
                    message="restore this project before making changes",
                ),
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, UpdateProjectDetailsInput)
        async with self._conn_factory() as conn:
            project = await update_project_details(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                name=inputs.title,
                description=inputs.description,
            )
        if project is None:
            raise ValueError("project disappeared from its workspace during the update")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"id": project.project_id, "title": project.name},
        )


class SetProjectPinnedInput(ToolInput):
    project_id: str = Field(min_length=1, max_length=255)
    pinned: bool


class SetProjectPinnedOutput(ToolOutput):
    id: str
    pinned: bool


class SetProjectPinnedTool(_ProjectMutationTool):
    name = "set_project_pinned"
    version = "1"
    model_description = "Pin or unpin a project for the whole workspace."
    input_model: ClassVar[type[ToolInput]] = SetProjectPinnedInput
    output_model: ClassVar[type[ToolOutput]] = SetProjectPinnedOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project(project_id, workspace_id)",
        external_boundary=ExternalReplayBoundary.NONE,
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SetProjectPinnedInput)
        # Pinning is allowed in every non-system state, archived included: an archived project a
        # human still wants at the top of the list is their call, not the tool's.
        return self._shared_failures(
            await self._project(workspace_id=ctx.workspace_id, project_id=inputs.project_id)
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SetProjectPinnedInput)
        async with self._conn_factory() as conn:
            project = await set_project_pinned(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                pinned=inputs.pinned,
            )
        if project is None:
            raise ValueError("project disappeared from its workspace during the pin")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"id": project.project_id, "pinned": project.pinned},
        )


class SetProjectArchivedInput(ToolInput):
    project_id: str = Field(min_length=1, max_length=255)
    archived: bool


class SetProjectArchivedOutput(ToolOutput):
    id: str
    status: str


class SetProjectArchivedTool(_ProjectMutationTool):
    name = "set_project_archived"
    version = "1"
    model_description = "Archive a project (reversible) or restore it."
    input_model: ClassVar[type[ToolInput]] = SetProjectArchivedInput
    output_model: ClassVar[type[ToolOutput]] = SetProjectArchivedOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project(project_id, workspace_id)",
        external_boundary=ExternalReplayBoundary.NONE,
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SetProjectArchivedInput)
        project = await self._project(workspace_id=ctx.workspace_id, project_id=inputs.project_id)
        shared = self._shared_failures(project)
        if shared or project is None:
            return shared
        if project.status == "draft":
            return (
                PreconditionFailure(
                    reason_code="project_draft", message="this project has not started yet"
                ),
            )
        # Only an archival of a live project asks the running-work question; a restore never
        # does, so a project cannot be trapped in the archive by work it started before.
        if inputs.archived and project.status == "active":
            async with self._conn_factory() as conn:
                thread_ids = [
                    str(row[0])
                    for row in await conn.execute(
                        text(
                            "SELECT id FROM agent_thread "
                            "WHERE workspace_id = :w AND project_id = :p AND status = 'active'"
                        ),
                        {"w": ctx.workspace_id, "p": inputs.project_id},
                    )
                ]
            running = await threads_running(
                workspace_id=ctx.workspace_id,
                thread_ids=thread_ids,
                conn_factory=self._conn_factory,
            )
            if running:
                return (
                    PreconditionFailure(
                        reason_code="project_running",
                        message=(
                            "This project has running work. Wait for it to finish before archiving."
                        ),
                    ),
                )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SetProjectArchivedInput)
        async with self._conn_factory() as conn:
            project = await set_project_archived(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                archived=inputs.archived,
            )
        if project is None:
            raise ValueError("project disappeared from its workspace during the archive")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"id": project.project_id, "status": project.status},
        )
