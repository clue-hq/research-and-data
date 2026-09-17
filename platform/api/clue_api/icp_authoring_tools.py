"""``author_icp_document@1`` — the Head of ABM stores an ICP it drafted, as a proposal.

The lane's other ICP surfaces present and confirm documents that already exist. This one is where a
document comes from: the agent has read the brand's knowledge files, has talked to the human about
who they sell to, and writes the profile down — either a new brand-level ICP, or a project-local
variant with its own key and a ``derived_from`` naming the brand profile it adapts.

It writes a *proposal* and nothing more. Nothing is confirmed by this call, no project pin moves,
and no research is launched: the human's yes is still the ICP confirmation gate, which is the tool
the agent reaches for next.

The turn binding is why this module sits at the ``clue_api`` root rather than inside
``clue_api.arv2``: the lane may not import ``clue_api.turn_action`` / ``turn_binding`` (Global
Constraint 7), and the platform — not the model — must say which turn, which project, which brand
and which human this act belongs to. The model supplies only the document, its key, its scope and
the key it derives from; everything else comes from durable rows:

* the **presenting turn** supplies the project and the human it credits;
* the **project** supplies the brand and proves the turn is this workspace's to write in;
* the **write** (:func:`~clue_api.arv2.icp_authoring.author_icp_document`) owns status, scope,
  lineage and the version chain.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, ClassVar, Literal

from pydantic import Field, StringConstraints

from clue_api.arv2.icp_authoring import (
    ICP_KEY_MAX_LENGTH,
    ICP_KEY_PATTERN,
    IcpAuthoringRefused,
    IcpAuthoringRequest,
    IcpAuthoringService,
)
from clue_api.turn_action import (
    TurnActionUnresolvable,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_spine import get_project
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

__all__ = [
    "AuthorIcpDocumentInput",
    "AuthorIcpDocumentOutput",
    "AuthorIcpDocumentTool",
    "build_icp_authoring_tools",
]

#: A document long enough for a real ICP — gates, exclusions, persona map, qualifier fields and
#: prose — and bounded so one call cannot become an unbounded upload.
_DOCUMENT_MAX_CHARS = 200_000


class AuthorIcpDocumentInput(ToolInput):
    """The document and what it is. Scope's *coordinates*, authorship and lineage ids are derived
    from the presenting turn and the rows it names."""

    icp_key: str = Field(min_length=1, max_length=ICP_KEY_MAX_LENGTH, pattern=ICP_KEY_PATTERN)
    document: str = Field(min_length=1, max_length=_DOCUMENT_MAX_CHARS)
    scope: Literal["brand", "project"]
    #: The brand ICP a project-local variant adapts, by key. ``None`` for an original profile.
    derived_from_icp_key: str | None = None
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class AuthorIcpDocumentOutput(ToolOutput):
    document_id: str
    icp_key: str
    version: int
    path: str
    workspace_path: str
    status: str
    replayed: bool


class _AuthoringRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuthorIcpDocumentTool(Tool):
    """Store one authored ICP as a proposed knowledge document version."""

    name = "author_icp_document"
    version = "1"
    model_description = (
        "Store an ICP document you drafted from the brand's knowledge files as a proposed version "
        "— brand-level (a new profile for the whole brand) or project-local (a variant for this "
        "project only, with its own key and derived_from naming the brand profile it adapts). The "
        "document must carry the icp-definition front matter: kind, icp_key, product_ids, "
        "hard_gates, exclusions, persona_map, qualifier_fields, then the body. The platform owns "
        "status, scope and lineage. Nothing is confirmed by this call: open the ICP confirmation "
        "gate afterwards."
    )
    input_model: ClassVar[type[ToolInput]] = AuthorIcpDocumentInput
    output_model: ClassVar[type[ToolOutput]] = AuthorIcpDocumentOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="presenting turn + scope + icp_key",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        # The document itself stays artifact-backed rather than displayed: it is the whole ICP.
        safe_display_fields=("icp_key", "scope", "derived_from_icp_key")
    )
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(
        self,
        service: IcpAuthoringService | None,
        *,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._service = service
        self._conn_factory = conn_factory

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, AuthorIcpDocumentInput)
        if self._service is None:
            return (
                PreconditionFailure(
                    reason_code="icp_authoring_not_composed",
                    message="ICP authoring is not composed on this deployment",
                ),
            )
        try:
            await self._resolve(inputs, ctx)
        except _AuthoringRefused as exc:
            return (PreconditionFailure(reason_code=exc.code, message=str(exc)),)
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        # Writing a file the agent already drafted buys nothing from anybody.
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, AuthorIcpDocumentInput)
        assert self._service is not None
        request = await self._resolve(inputs, ctx)
        try:
            authored = await self._service.author(request)
        except IcpAuthoringRefused as refused:
            # A domain refusal is feedback the author can act on — a typed precondition failure,
            # never a stack trace the model has to guess at.
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = AuthorIcpDocumentOutput(
            document_id=str(authored.document_id),
            icp_key=authored.icp_key,
            version=authored.version,
            path=authored.path,
            workspace_path=authored.workspace_path,
            status=authored.status,
            replayed=authored.replayed,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(),
            replayed=authored.replayed,
        )

    async def _resolve(
        self, inputs: AuthorIcpDocumentInput, ctx: ToolContext
    ) -> IcpAuthoringRequest:
        """Everything the model may not author, read from the rows that own it."""

        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _AuthoringRefused("authoring_turn_ref_malformed", str(exc)) from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
            if turn is None:
                raise _AuthoringRefused(
                    "authoring_turn_not_found",
                    "the presenting turn is not part of this workspace",
                )
            if turn.submitted_by_user_id is None:
                raise _AuthoringRefused(
                    "authoring_addressee_missing",
                    "the presenting turn records no human to credit this document to",
                )
            project = await get_project(conn, turn.project_id)
            if project is None or project.workspace_id != ctx.workspace_id:
                # Fail-closed and indistinguishable from an unresolvable turn: a turn whose project
                # this workspace cannot see is not a turn this workspace may write in.
                raise _AuthoringRefused(
                    "authoring_turn_not_found",
                    "the presenting turn's project is not part of this workspace",
                )
        return IcpAuthoringRequest(
            workspace_id=ctx.workspace_id,
            brand_id=project.brand_id,
            project_id=turn.project_id,
            turn_id=turn.turn_id,
            user_id=turn.submitted_by_user_id,
            icp_key=inputs.icp_key,
            document_text=inputs.document,
            scope=inputs.scope,
            derived_from_icp_key=inputs.derived_from_icp_key,
        )


def build_icp_authoring_tools(
    service: IcpAuthoringService | None,
    *,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    """The authoring surface. Registered on every deployment; composed where storage exists.

    Registering it uncomposed is deliberate, for the reason the ARV2 launch tools give: the
    platform's write surface stays complete (the authority audit sees every tool), and an agent
    that reaches for authoring on a deployment without it gets the named
    ``icp_authoring_not_composed`` refusal rather than an ``UnknownTool`` it cannot explain.
    """

    return (AuthorIcpDocumentTool(service, conn_factory=conn_factory),)
