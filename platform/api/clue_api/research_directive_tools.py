"""A2 non-spending tools for drafting and human-confirming account research direction."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_core import (
    EntityId,
    MemoryWriteSeam,
    ResearchDirectiveAccountOverrideBody,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchDirectiveStatus,
)
from clue_db import ConnFactory, transaction
from clue_projections import project_research_directive_preview
from clue_research.directives import (
    ResearchDirectiveError,
    confirm_research_directive,
    draft_research_directive,
    get_research_directive,
    research_directive_confirmation_replay_matches,
    research_directive_draft_replay_matches,
    research_directive_draft_request_sha256,
    validate_research_directive_draft,
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

MemoryWriteFactory = Callable[[AsyncConnection], MemoryWriteSeam]


class ResearchDirectiveOverrideInput(ToolInput):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: EntityId
    body: ResearchDirectiveAccountOverrideBody


class DraftAccountResearchDirectiveInput(ToolInput):
    project_id: str = Field(
        min_length=1,
        max_length=255,
        description="Trusted current project; supplied by the platform.",
    )
    product_id: str = Field(min_length=1, max_length=255)
    icp_key: str = Field(min_length=1, max_length=255)
    icp_version: int = Field(ge=1)
    body: ResearchDirectiveBody
    account_overrides: tuple[ResearchDirectiveOverrideInput, ...] = Field(
        default=(), max_length=500
    )
    predecessor_id: ResearchDirectiveId | None = None
    user_instruction: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})

    @model_validator(mode="after")
    def overrides_are_unique(self) -> DraftAccountResearchDirectiveInput:
        account_ids = tuple(item.account_id for item in self.account_overrides)
        if len(account_ids) != len(set(account_ids)):
            raise ValueError("account research directive overrides must be unique by account")
        return self


class DraftAccountResearchDirectiveOutput(ToolOutput):
    directive_id: str
    directive_ref: str
    version: int
    canonical_json_sha256: str
    status: str
    memory_refs: list[str]
    account_override_refs: list[str]
    preview_ref: str
    preview_hypothesis_count: int
    preview_account_count: int
    unresolved_prerequisites: list[str]


class ConfirmAccountResearchDirectiveInput(ToolInput):
    directive_id: ResearchDirectiveId
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_by: str = Field(min_length=1, max_length=255)
    confirming_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class ConfirmAccountResearchDirectiveOutput(ToolOutput):
    directive_id: str
    directive_ref: str
    version: int
    canonical_json_sha256: str
    status: str
    confirmation_ref: str


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _created_by(ctx: ToolContext) -> str:
    return f"{ctx.actor}:{ctx.execution_id or 'direct'}"


class DraftAccountResearchDirectiveTool(Tool):
    name = "draft_account_research_directive"
    version = "1"
    input_model = DraftAccountResearchDirectiveInput
    output_model = DraftAccountResearchDirectiveOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="ResearchDirectiveId(operation_id)",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "product_id", "icp_key", "icp_version")
    )
    pin_requirements = ("project", "product", "icp", "field_registry", "source_registry")

    def __init__(
        self,
        *,
        memory_write_factory: MemoryWriteFactory | None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._memory_write_factory = memory_write_factory
        self._conn_factory = conn_factory

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DraftAccountResearchDirectiveInput)
        if self._memory_write_factory is None:
            return _failure(
                "memory_write_not_configured",
                "project research direction requires the scoped-memory write seam",
            )
        try:
            async with self._conn_factory() as conn:
                request_sha256 = research_directive_draft_request_sha256(
                    workspace_id=ctx.workspace_id,
                    project_id=inputs.project_id,
                    product_id=inputs.product_id,
                    icp_key=inputs.icp_key,
                    icp_version=inputs.icp_version,
                    body=inputs.body,
                    account_overrides={
                        item.account_id: item.body for item in inputs.account_overrides
                    },
                    user_instruction=inputs.user_instruction,
                    source_turn_ref=inputs.source_turn_ref,
                    created_by=_created_by(ctx),
                    actor_type=ctx.actor,
                    predecessor_id=inputs.predecessor_id,
                )
                replay = await research_directive_draft_replay_matches(
                    conn,
                    workspace_id=ctx.workspace_id,
                    operation_id=ctx.operation_id,
                    expected_request_sha256=request_sha256,
                )
                if replay is True:
                    return ()
                if replay is False:
                    return _failure(
                        "research_directive_replay_conflict",
                        "draft operation id was already used with different research direction",
                    )
                await validate_research_directive_draft(
                    conn,
                    workspace_id=ctx.workspace_id,
                    project_id=inputs.project_id,
                    product_id=inputs.product_id,
                    icp_key=inputs.icp_key,
                    icp_version=inputs.icp_version,
                    body=inputs.body,
                    overrides={item.account_id: item.body for item in inputs.account_overrides},
                )
        except ResearchDirectiveError as exc:
            return _failure("research_directive_invalid", str(exc))
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, DraftAccountResearchDirectiveInput)
        if self._memory_write_factory is None:
            raise RuntimeError("research directive memory write seam is not configured")
        async with self._conn_factory() as conn:
            drafted = await draft_research_directive(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                product_id=inputs.product_id,
                icp_key=inputs.icp_key,
                icp_version=inputs.icp_version,
                body=inputs.body,
                account_overrides={item.account_id: item.body for item in inputs.account_overrides},
                user_instruction=inputs.user_instruction,
                source_turn_ref=inputs.source_turn_ref,
                created_by=_created_by(ctx),
                actor_type=ctx.actor,
                operation_id=ctx.operation_id,
                memory_write=self._memory_write_factory(conn),
                predecessor_id=inputs.predecessor_id,
            )
        preview = project_research_directive_preview(drafted.directive, drafted.overrides)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "directive_id": str(drafted.directive.directive_id),
                "directive_ref": drafted.directive.directive_ref,
                "version": drafted.directive.version,
                "canonical_json_sha256": drafted.directive.canonical_json_sha256,
                "status": drafted.directive.status.value,
                "memory_refs": list(drafted.directive.memory_refs),
                "account_override_refs": [item.override_ref for item in drafted.overrides],
                "preview_ref": drafted.directive.directive_ref,
                "preview_hypothesis_count": len(preview.hypotheses),
                "preview_account_count": len(preview.account_ids),
                "unresolved_prerequisites": list(preview.unresolved_prerequisites),
            },
        )


class ConfirmAccountResearchDirectiveTool(Tool):
    name = "confirm_account_research_directive"
    version = "1"
    input_model = ConfirmAccountResearchDirectiveInput
    output_model = ConfirmAccountResearchDirectiveOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="directive confirmation operation receipt",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("directive_id",))
    pin_requirements = ("research_directive",)

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, ConfirmAccountResearchDirectiveInput)
        async with self._conn_factory() as conn:
            directive = await get_research_directive(
                conn,
                inputs.directive_id,
                workspace_id=ctx.workspace_id,
            )
        return {
            "directive_id": str(inputs.directive_id),
            "exists": directive is not None,
            "status": directive.status.value if directive is not None else None,
            "canonical_json_sha256": (
                directive.canonical_json_sha256 if directive is not None else None
            ),
        }

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ConfirmAccountResearchDirectiveInput)
        if ctx.actor != "human":
            return _failure("human_required", "only a human can confirm research direction")
        async with self._conn_factory() as conn:
            directive = await get_research_directive(
                conn,
                inputs.directive_id,
                workspace_id=ctx.workspace_id,
            )
        if directive is None:
            return _failure("research_directive_not_found", "no such workspace directive")
        if directive.canonical_json_sha256 != inputs.expected_sha256:
            return _failure(
                "research_directive_digest_mismatch",
                "the confirmation digest differs from the reviewed draft",
            )
        if directive.status is ResearchDirectiveStatus.CONFIRMED:
            if await self._confirmation_replay_matches(inputs, ctx):
                return ()
            return _failure(
                "research_directive_not_draft",
                "directive was already confirmed by another or different request",
            )
        if directive.status is not ResearchDirectiveStatus.DRAFT:
            return _failure(
                "research_directive_not_draft",
                "only the current draft can be confirmed",
            )
        return ()

    async def _confirmation_replay_matches(
        self,
        inputs: ConfirmAccountResearchDirectiveInput,
        ctx: ToolContext,
    ) -> bool:
        async with self._conn_factory() as conn:
            return await research_directive_confirmation_replay_matches(
                conn,
                workspace_id=ctx.workspace_id,
                directive_id=inputs.directive_id,
                operation_id=ctx.operation_id,
                confirmed_by=inputs.confirmed_by,
                confirming_turn_ref=inputs.confirming_turn_ref,
            )

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ConfirmAccountResearchDirectiveInput)
        if ctx.actor != "human":
            raise ValueError("only a human can confirm research direction")
        async with self._conn_factory() as conn:
            directive = await confirm_research_directive(
                conn,
                workspace_id=ctx.workspace_id,
                directive_id=inputs.directive_id,
                expected_sha256=inputs.expected_sha256,
                confirmed_by=inputs.confirmed_by,
                confirming_turn_ref=inputs.confirming_turn_ref,
                operation_id=ctx.operation_id,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "directive_id": str(directive.directive_id),
                "directive_ref": directive.directive_ref,
                "version": directive.version,
                "canonical_json_sha256": directive.canonical_json_sha256,
                "status": directive.status.value,
                "confirmation_ref": f"research-directive-confirmation:{ctx.operation_id}",
            },
        )


def build_research_directive_tools(
    *,
    memory_write_factory: MemoryWriteFactory | None,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, Tool]:
    return (
        DraftAccountResearchDirectiveTool(
            memory_write_factory=memory_write_factory,
            conn_factory=conn_factory,
        ),
        ConfirmAccountResearchDirectiveTool(conn_factory=conn_factory),
    )


__all__ = [
    "ConfirmAccountResearchDirectiveInput",
    "ConfirmAccountResearchDirectiveOutput",
    "ConfirmAccountResearchDirectiveTool",
    "DraftAccountResearchDirectiveInput",
    "DraftAccountResearchDirectiveOutput",
    "DraftAccountResearchDirectiveTool",
    "ResearchDirectiveOverrideInput",
    "build_research_directive_tools",
]
