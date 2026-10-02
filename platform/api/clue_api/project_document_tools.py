"""``write_project_document@1`` — the Head of ABM writes this project's plan.

A project has one plan, ``project/plan.md``, and two hands write it: the agent through this
tool, the human through the project-document editor. That makes it a lost-update problem, so the
model must say **which version it read** — ``expected_version`` — and the platform refuses by name
when the file has moved since, rather than overwriting words the human typed in between.

Everything about *who* and *where* is derived, never model-authored. The turn binding is why this
module sits at the ``clue_api`` root rather than inside ``clue_api.arv2``: the lane may not import
``clue_api.turn_action`` / ``turn_binding`` (Global Constraint 7), and the platform must say which
turn, which project, which brand and which human this write belongs to:

* the **presenting turn** supplies the project and the human it credits;
* the **project** supplies the brand and proves the turn is this workspace's to write in;
* the **write** (:func:`~clue_api.arv2.project_documents.write_project_plan`) owns the path, the
  status, the version chain and the revision check.

The service seam lives here too, beside the tool that is its only caller: one transaction per
written version, and a deployment without storage registers the tool and refuses by name.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, Protocol

from pydantic import Field, StringConstraints

from clue_api.arv2.project_documents import (
    ProjectDocumentRefused,
    ProjectPlanWrite,
    WrittenDocument,
    write_project_plan,
)
from clue_api.turn_action import (
    TurnActionUnresolvable,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_spine import get_project
from clue_storage import StorageBackend
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
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

if TYPE_CHECKING:  # the refresher's module imports this one's neighbours; only the type is needed
    from clue_api.project_library_refresh import ProjectLibraryRefresher

__all__ = [
    "DbProjectDocumentService",
    "ProjectDocumentService",
    "WriteProjectDocumentInput",
    "WriteProjectDocumentOutput",
    "WriteProjectDocumentTool",
    "build_project_document_tools",
]

#: A plan long enough for a real one — outcome, profile, products, motion, channels, owners, the
#: ninety-day picture and the next steps — and bounded so one call cannot become an upload.
_PLAN_MAX_CHARS = 200_000


# =================================================================================================
# the service seam + its production implementation
# =================================================================================================


class ProjectDocumentService(Protocol):
    """What the toolbelt tool calls. One transaction per call is the implementation's business."""

    async def write_plan(self, request: ProjectPlanWrite) -> WrittenDocument: ...


class DbProjectDocumentService:
    """The production service: one transaction per written version, artifact row and blob."""

    def __init__(
        self,
        storage: StorageBackend,
        *,
        conn_factory: ConnFactory = transaction,
        library: ProjectLibraryRefresher | None = None,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory
        self._library = library

    async def write_plan(self, request: ProjectPlanWrite) -> WrittenDocument:
        async with self._conn_factory() as conn:
            written = await write_project_plan(conn, self._storage, request)
        # After the commit, never inside it: the library's compile takes this project's row lock,
        # which this transaction was holding. Best-effort by contract — a plan that saved must not
        # report failure because its rendering could not be written, and the next turn's digest
        # would rebuild it anyway. Its point is the frontend, which reads the rendering.
        if self._library is not None:
            await self._library.refresh(
                workspace_id=request.workspace_id, project_id=request.project_id
            )
        return written


# =================================================================================================
# the tool
# =================================================================================================


class WriteProjectDocumentInput(ToolInput):
    """The plan and the version it was written against. Scope, authorship and the path itself are
    derived from the presenting turn and the rows it names."""

    document: Literal["plan"]
    body: str = Field(min_length=1, max_length=_PLAN_MAX_CHARS)
    #: The version of ``project/plan.md`` this body was written against; omitted only when
    #: no plan exists yet.
    expected_version: int | None = Field(default=None, ge=1)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class WriteProjectDocumentOutput(ToolOutput):
    document_id: str
    path: str
    version: int
    workspace_path: str
    replayed: bool


class _WriteRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WriteProjectDocumentTool(Tool):
    """Store one plan as the next version of this project's ``project/plan.md``."""

    name = "write_project_document"
    version = "1"
    model_description = (
        "Write this project's plan (project/plan.md) as markdown: the execution plan you "
        "and the human settled — outcome, the confirmed profile and products, the account motion, "
        "channels, owners, what day ninety looks like, and the next steps. Write it once the "
        "strategy, the ICP and the product set are agreed, never on the first turn. Pass "
        "expected_version = the version of the file you read (omit it only when no plan exists "
        "yet); the platform refuses when the human has edited it since, and you then re-read it. "
        "The new version appears in your workspace on the next turn. Include {object_type: "
        "'project_document', object_id: <document_id>, version: <version>} in your finalization's "
        "domain_refs so the plan card appears in the chat."
    )
    input_model: ClassVar[type[ToolInput]] = WriteProjectDocumentInput
    output_model: ClassVar[type[ToolOutput]] = WriteProjectDocumentOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="presenting turn + document + expected version + body",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        # The plan itself stays artifact-backed rather than displayed: it is the whole document.
        safe_display_fields=("document", "expected_version")
    )
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(
        self,
        service: ProjectDocumentService | None,
        *,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._service = service
        self._conn_factory = conn_factory

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, WriteProjectDocumentInput)
        if self._service is None:
            return (
                PreconditionFailure(
                    reason_code="project_documents_not_composed",
                    message="project documents are not composed on this deployment",
                ),
            )
        try:
            await self._resolve(inputs, ctx)
        except _WriteRefused as exc:
            return (PreconditionFailure(reason_code=exc.code, message=str(exc)),)
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        # Writing down a plan the agent and the human already settled buys nothing from anybody.
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, WriteProjectDocumentInput)
        assert self._service is not None
        request = await self._resolve(inputs, ctx)
        try:
            written = await self._service.write_plan(request)
        except ProjectDocumentRefused as refused:
            # A revision conflict is feedback the author can act on — re-read the plan and write
            # again — so it arrives as a typed precondition failure, never a stack trace.
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = WriteProjectDocumentOutput(
            document_id=str(written.document_id),
            path=written.path,
            version=written.version,
            workspace_path=written.workspace_path,
            replayed=written.replayed,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(),
            replayed=written.replayed,
        )

    async def _resolve(
        self, inputs: WriteProjectDocumentInput, ctx: ToolContext
    ) -> ProjectPlanWrite:
        """Everything the model may not author, read from the rows that own it."""

        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _WriteRefused("project_document_turn_ref_malformed", str(exc)) from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
            if turn is None:
                raise _WriteRefused(
                    "project_document_turn_not_found",
                    "the presenting turn is not part of this workspace",
                )
            if turn.submitted_by_user_id is None:
                raise _WriteRefused(
                    "project_document_addressee_missing",
                    "the presenting turn records no human to credit this plan to",
                )
            project = await get_project(conn, turn.project_id)
            if project is None or project.workspace_id != ctx.workspace_id:
                # Fail-closed and indistinguishable from an unresolvable turn: a turn whose project
                # this workspace cannot see is not a turn this workspace may write in.
                raise _WriteRefused(
                    "project_document_turn_not_found",
                    "the presenting turn's project is not part of this workspace",
                )
        return ProjectPlanWrite(
            workspace_id=ctx.workspace_id,
            brand_id=project.brand_id,
            project_id=turn.project_id,
            turn_id=turn.turn_id,
            user_id=turn.submitted_by_user_id,
            body=inputs.body,
            expected_version=inputs.expected_version,
        )


def build_project_document_tools(
    service: ProjectDocumentService | None,
    *,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    """The project-document write surface. Registered everywhere; composed where storage exists.

    Registering it uncomposed is deliberate, for the reason its ARV2 neighbours give: the
    platform's write surface stays complete (the authority audit sees every tool), and an agent
    that reaches for the plan on a deployment without it gets the named
    ``project_documents_not_composed`` refusal rather than an ``UnknownTool`` it cannot explain.
    """

    return (WriteProjectDocumentTool(service, conn_factory=conn_factory),)
