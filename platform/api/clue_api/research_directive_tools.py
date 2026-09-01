"""A2 non-spending tools for drafting and human-confirming account research direction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Annotated, ClassVar, Literal

from pydantic import ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.auth_tool_context import require_human_authority
from clue_api.comprehensive_research_contract import COMPREHENSIVE_ACCOUNT_FIELDS
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_core import (
    USER_RESEARCH_INSTRUCTION_MAX_BYTES,
    EntityId,
    MemoryWriteSeam,
    ResearchDirectiveAccountOverrideBody,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchDirectiveStatus,
)
from clue_core.research_directive import ResearchCommitteePlan, StableKey
from clue_db import ConnFactory, transaction
from clue_projections import ResearchDirectivePreview, project_research_directive_preview
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
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
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
        # The agent-facing runtime model deliberately removes trusted turn fields from its
        # schema.  It still inherits this validator, so validate the byte ceiling only when the
        # full tool input is being materialized after trusted-turn injection.  Accessing the
        # removed field directly made a valid browser tool call crash before it could reach the
        # governed execution seam.
        user_instruction = getattr(self, "user_instruction", None)
        if (
            user_instruction is not None
            and len(user_instruction.encode("utf-8")) > USER_RESEARCH_INSTRUCTION_MAX_BYTES
        ):
            raise ValueError(
                "user research instruction exceeds its "
                f"{USER_RESEARCH_INSTRUCTION_MAX_BYTES}-byte context contract"
            )
        return self


class DraftAccountResearchDirectiveInputV3(ToolInput):
    """Agent-plan-safe directive input; v2's frozen ``body`` field remains replayable."""

    project_id: str = Field(
        min_length=1,
        max_length=255,
        description="Trusted current project; supplied by the platform.",
    )
    product_id: str = Field(min_length=1, max_length=255)
    icp_key: str = Field(min_length=1, max_length=255)
    icp_version: int = Field(ge=1)
    directive: ResearchDirectiveBody
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
    def overrides_are_unique(self) -> DraftAccountResearchDirectiveInputV3:
        account_ids = tuple(item.account_id for item in self.account_overrides)
        if len(account_ids) != len(set(account_ids)):
            raise ValueError("account research directive overrides must be unique by account")
        user_instruction = getattr(self, "user_instruction", None)
        if (
            user_instruction is not None
            and len(user_instruction.encode("utf-8")) > USER_RESEARCH_INSTRUCTION_MAX_BYTES
        ):
            raise ValueError(
                "user research instruction exceeds its "
                f"{USER_RESEARCH_INSTRUCTION_MAX_BYTES}-byte context contract"
            )
        return self


class DraftAccountResearchDirectiveInputV4(DraftAccountResearchDirectiveInputV3):
    """v3 plus the deterministic breadth declaration the comprehensive contract (§3.2/§3.3) wants.

    Field breadth is a *contract*, not a model decision: the normal request is the whole fixed
    21-field account profile, and the model's job is to say which of the two breadths the human
    asked for — not to retype a field list it could truncate or invent. So ``profile`` defaults to
    ``comprehensive`` and the expansion happens here, mechanically, from
    :data:`COMPREHENSIVE_ACCOUNT_FIELDS`. ``custom`` is the narrower request the human explicitly
    asked for and passes through untouched. Declaring ``comprehensive`` *and* an explicit field
    list is two conflicting statements of breadth, so it is refused rather than silently resolved.
    """

    profile: Literal["comprehensive", "custom"] = "comprehensive"

    @model_validator(mode="before")
    @classmethod
    def profile_decides_field_breadth(cls, data: object) -> object:
        """Expand before validation so every later reader sees one already-decided field set.

        A ``mode="after"`` validator cannot do this: the input model is frozen, and pydantic does
        not honour a replacement instance returned from an after-validator constructed via
        ``__init__``. Expanding here also means the directive body is validated exactly once, in
        its final 21-field shape.
        """

        if not isinstance(data, dict):
            return data
        if data.get("profile", "comprehensive") != "comprehensive":
            return data
        directive = data.get("directive")
        if isinstance(directive, ResearchDirectiveBody):
            body = directive.model_dump()
        elif isinstance(directive, dict):
            body = dict(directive)
        else:
            return data  # absent or wrongly typed — let normal validation report it
        if body.get("field_keys"):
            raise ValueError(
                "a comprehensive research directive covers the whole fixed 21-field account "
                "profile; pass profile='custom' to request an explicit narrower field set"
            )
        body["field_keys"] = list(COMPREHENSIVE_ACCOUNT_FIELDS)
        return {**data, "directive": body}


class ResearchDirectiveBodyDraftInput(ResearchDirectiveBody):
    """The v5 draft-input directive body: ``field_keys`` is omittable at the schema level.

    ``ResearchDirectiveBody.field_keys`` carries no default, so every input model embedding the
    body advertised the key as *required* in its JSON schema — which made v4's comprehensive
    contract structurally unsatisfiable for a schema-honouring model: the skill says "no field
    list", the schema says the list is mandatory, and any non-empty value is refused as ambiguous
    breadth (found live in the Slice B browser gate; the agent looped plan-rejected and gave up).
    Only the *advertised input schema* relaxes here: the durable body type is unchanged, and the
    v4 expansion always fills the final 21-field shape before ``ResearchDirectiveBody``'s
    at-least-one-field validation runs, so no draft is ever persisted with an empty field set.
    """

    field_keys: tuple[StableKey, ...] = Field(
        default=(),
        max_length=128,
        description=(
            "Omit for the normal comprehensive request — the tool itself expands the fixed "
            "21-field account profile. List fields only together with profile='custom' when the "
            "user explicitly asked for a narrower subset."
        ),
    )

    @model_validator(mode="after")
    def _committee_intent_names_a_capable_source(self) -> ResearchDirectiveBodyDraftInput:
        """An intentional committee plan must be executable, or committee-off must be explicit.

        ``committee_plan`` is required on every body, so "plan present, no people source" is also
        the legitimate committee-off shape — the launcher compiles committee sources from
        ``source_policy`` ∩ privacy, not from the plan. That made a silent contradiction
        representable: found live when a draft repair stripped ``sumble_people`` from
        ``allowed_source_keys`` (person-adjacent memory guard) while keeping the human's explicit
        cap-200/depth-2 plan, so the confirmation card still showed committee discovery while the
        launched selection carried zero committee sources. A plan that departs from the model
        defaults states committee intent; a draft stating that intent while authorizing no
        committee-capable source is refused here — restore the source or reset the plan to its
        defaults so the card honestly shows committee discovery off. Draft-input only: durable
        historical bodies never re-validate through this subclass.
        """

        if self.committee_plan == ResearchCommitteePlan():
            return self
        people_allowed = (
            PEOPLE_SOURCE_KEY in self.source_policy.allowed_source_keys
            and PEOPLE_SOURCE_KEY not in self.source_policy.excluded_source_keys
        )
        if people_allowed and self.privacy_policy.committee_discovery_allowed:
            return self
        raise ValueError(
            "the draft states an intentional buying-committee plan but authorizes no "
            f"committee-capable source: include '{PEOPLE_SOURCE_KEY}' in "
            "source_policy.allowed_source_keys with privacy committee discovery allowed, or "
            "reset committee_plan to its defaults to state explicitly that committee discovery "
            "is off"
        )


class DraftAccountResearchDirectiveInputV5(DraftAccountResearchDirectiveInputV4):
    """v4's breadth contract with a satisfiable schema: ``directive.field_keys`` is optional.

    ``comprehensive`` expands mechanically and ``custom`` passes through untouched, exactly as in
    v4. Two v5-only changes, both found at the live Slice B browser gate: the advertised schema
    finally agrees with the steering skill (the model may — and should — omit ``field_keys``
    entirely), and an explicit list that is *exactly* the full fixed profile normalizes to the
    contract order instead of being refused — a model whose steering card lists the 21 rows
    reliably retypes them, and an identical statement of breadth is not an ambiguity. Any other
    non-empty list under ``comprehensive`` is still two conflicting statements of breadth and is
    refused; a truncated or invented retyping therefore still fails loudly rather than silently
    narrowing the profile.
    """

    directive: ResearchDirectiveBodyDraftInput

    @model_validator(mode="before")
    @classmethod
    def profile_decides_field_breadth(cls, data: object) -> object:
        """v4's expansion, plus tolerance for a verbatim full-profile retyping (v5 docstring)."""

        if not isinstance(data, dict):
            return data
        if data.get("profile", "comprehensive") != "comprehensive":
            return data
        directive = data.get("directive")
        if isinstance(directive, ResearchDirectiveBody):
            body = directive.model_dump()
        elif isinstance(directive, dict):
            body = dict(directive)
        else:
            return data  # absent or wrongly typed — let normal validation report it
        explicit = body.get("field_keys")
        if explicit and {str(key) for key in explicit} != set(COMPREHENSIVE_ACCOUNT_FIELDS):
            raise ValueError(
                "a comprehensive research directive covers the whole fixed 21-field account "
                "profile; pass profile='custom' to request an explicit narrower field set"
            )
        body["field_keys"] = list(COMPREHENSIVE_ACCOUNT_FIELDS)
        return {**data, "directive": body}


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


class DraftAccountResearchDirectiveOutputV2(ToolOutput):
    directive_id: str
    directive_ref: str
    version: int
    canonical_json_sha256: str
    status: str
    memory_outcome: str
    future_thread_memory_persisted: bool
    memory_refs: list[str]
    account_override_refs: list[str]
    preview_sha256: str
    preview: ResearchDirectivePreview


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


class ConfirmAccountResearchDirectiveInputV2(ToolInput):
    directive_id: ResearchDirectiveId
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConfirmAccountResearchDirectiveOutputV2(ConfirmAccountResearchDirectiveOutput):
    confirmed_by: str
    confirming_action_ref: str


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _created_by(ctx: ToolContext) -> str:
    return ctx.actor_id or f"{ctx.actor}:{ctx.execution_id or 'direct'}"


class DraftAccountResearchDirectiveTool(Tool):
    name = "draft_account_research_directive"
    version = "1"
    model_description = (
        "Persist one non-spending immutable account-research directive draft only after the "
        "human has finished revising the conversational working plan. The result is a complete "
        "review preview, not human confirmation, spend authorization, launch, or research."
    )
    input_model: ClassVar[type[ToolInput]] = DraftAccountResearchDirectiveInput
    output_model: ClassVar[type[ToolOutput]] = DraftAccountResearchDirectiveOutput
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


class DraftAccountResearchDirectiveToolV2(DraftAccountResearchDirectiveTool):
    """Truthful preview/memory result; v1 remains replayable for its frozen profile."""

    version = "2"
    output_model = DraftAccountResearchDirectiveOutputV2

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
        preview = project_research_directive_preview(
            drafted.directive,
            drafted.overrides,
            resolved_account_ids=drafted.account_ids,
            memory_outcome=drafted.memory_outcome,
        )
        preview_bytes = json.dumps(
            preview.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "directive_id": str(drafted.directive.directive_id),
                "directive_ref": drafted.directive.directive_ref,
                "version": drafted.directive.version,
                "canonical_json_sha256": drafted.directive.canonical_json_sha256,
                "status": drafted.directive.status.value,
                "memory_outcome": drafted.memory_outcome,
                "future_thread_memory_persisted": bool(drafted.directive.memory_refs),
                "memory_refs": list(drafted.directive.memory_refs),
                "account_override_refs": [item.override_ref for item in drafted.overrides],
                "preview_sha256": hashlib.sha256(preview_bytes).hexdigest(),
                "preview": preview.model_dump(mode="json"),
            },
        )


class DraftAccountResearchDirectiveToolV3(DraftAccountResearchDirectiveToolV2):
    """Plan-safe field spelling while preserving v2's durable directive semantics."""

    version = "3"
    input_model = DraftAccountResearchDirectiveInputV3

    @staticmethod
    def _v2_input(inputs: ToolInput) -> DraftAccountResearchDirectiveInput:
        assert isinstance(inputs, DraftAccountResearchDirectiveInputV3)
        return DraftAccountResearchDirectiveInput(
            project_id=inputs.project_id,
            product_id=inputs.product_id,
            icp_key=inputs.icp_key,
            icp_version=inputs.icp_version,
            body=inputs.directive,
            account_overrides=inputs.account_overrides,
            predecessor_id=inputs.predecessor_id,
            user_instruction=inputs.user_instruction,
            source_turn_ref=inputs.source_turn_ref,
        )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        return await super().preconditions(self._v2_input(inputs), ctx)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        return await super().invoke(self._v2_input(inputs), ctx)


class DraftAccountResearchDirectiveToolV4(DraftAccountResearchDirectiveToolV3):
    """Comprehensive-by-default field breadth; v3's durable directive semantics are unchanged.

    The only difference from v3 is the input contract: the agent declares *which breadth* the human
    asked for and the input model expands ``comprehensive`` to the full §3.1 profile before any
    validation, spend, or persistence sees it. Everything after that point — validation, replay
    identity, the drafted directive — is v3's, so a v3 draft replays as a v3 draft.
    """

    version = "4"
    input_model = DraftAccountResearchDirectiveInputV4

    @staticmethod
    def _v2_input(inputs: ToolInput) -> DraftAccountResearchDirectiveInput:
        assert isinstance(inputs, DraftAccountResearchDirectiveInputV4)
        return DraftAccountResearchDirectiveInput(
            project_id=inputs.project_id,
            product_id=inputs.product_id,
            icp_key=inputs.icp_key,
            icp_version=inputs.icp_version,
            body=inputs.directive,
            account_overrides=inputs.account_overrides,
            predecessor_id=inputs.predecessor_id,
            user_instruction=inputs.user_instruction,
            source_turn_ref=inputs.source_turn_ref,
        )


class DraftAccountResearchDirectiveToolV5(DraftAccountResearchDirectiveToolV4):
    """v4's comprehensive breadth contract behind a schema the model can actually satisfy.

    The only difference from v4 is the advertised input schema: ``directive.field_keys`` is
    optional (see :class:`ResearchDirectiveBodyDraftInput`), so the steering skill's "profile=
    'comprehensive' and no field list" instruction is expressible instead of contradicting a
    required-key schema. Expansion, validation, spend, persistence, and replay identity are all
    v4's — a v4 draft replays as a v4 draft.
    """

    version = "5"
    input_model: ClassVar[type[DraftAccountResearchDirectiveInputV4]] = (
        DraftAccountResearchDirectiveInputV5
    )

    @staticmethod
    def _v2_input(inputs: ToolInput) -> DraftAccountResearchDirectiveInput:
        assert isinstance(inputs, DraftAccountResearchDirectiveInputV5)
        return DraftAccountResearchDirectiveInput(
            project_id=inputs.project_id,
            product_id=inputs.product_id,
            icp_key=inputs.icp_key,
            icp_version=inputs.icp_version,
            body=inputs.directive,
            account_overrides=inputs.account_overrides,
            predecessor_id=inputs.predecessor_id,
            user_instruction=inputs.user_instruction,
            source_turn_ref=inputs.source_turn_ref,
        )


class ConfirmAccountResearchDirectiveTool(Tool):
    name = "confirm_account_research_directive"
    version = "1"
    input_model: ClassVar[type[ToolInput]] = ConfirmAccountResearchDirectiveInput
    output_model: ClassVar[type[ToolOutput]] = ConfirmAccountResearchDirectiveOutput
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
        authority = require_human_authority(
            ctx,
            action_ref_required=True,
            message=(
                "confirmation requires authenticated human identity and captured action reference"
            ),
        )
        if authority:
            return authority
        if ctx.actor_id is None or ctx.action_ref is None:
            return _failure(
                "trusted_human_receipt_required",
                "confirmation requires authenticated human identity and captured action reference",
            )
        if inputs.confirmed_by != ctx.actor_id or inputs.confirming_turn_ref != ctx.action_ref:
            return _failure(
                "trusted_human_receipt_mismatch",
                "caller-authored confirmation attribution differs from the invocation context",
            )
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
        if ctx.actor_id is None or ctx.action_ref is None:
            raise ValueError("trusted human confirmation receipt is missing")
        if inputs.confirmed_by != ctx.actor_id or inputs.confirming_turn_ref != ctx.action_ref:
            raise ValueError("caller-authored confirmation attribution is not trusted")
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


class ConfirmAccountResearchDirectiveToolV2(ConfirmAccountResearchDirectiveTool):
    """Human gate whose attribution exists only in the authenticated invocation context."""

    version = "2"
    input_model = ConfirmAccountResearchDirectiveInputV2
    output_model = ConfirmAccountResearchDirectiveOutputV2

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, ConfirmAccountResearchDirectiveInputV2)
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
        assert isinstance(inputs, ConfirmAccountResearchDirectiveInputV2)
        authority = require_human_authority(
            ctx,
            action_ref_required=True,
            message=(
                "confirmation requires authenticated human identity and captured action reference"
            ),
        )
        if authority:
            return authority
        if ctx.actor_id is None or ctx.action_ref is None:
            return _failure(
                "trusted_human_receipt_required",
                "confirmation requires authenticated human identity and captured action reference",
            )
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
            async with self._conn_factory() as conn:
                replay = await research_directive_confirmation_replay_matches(
                    conn,
                    workspace_id=ctx.workspace_id,
                    directive_id=inputs.directive_id,
                    operation_id=ctx.operation_id,
                    confirmed_by=ctx.actor_id,
                    confirming_turn_ref=ctx.action_ref,
                )
            if replay:
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

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ConfirmAccountResearchDirectiveInputV2)
        if ctx.actor != "human" or ctx.actor_id is None or ctx.action_ref is None:
            raise ValueError("trusted human confirmation receipt is missing")
        async with self._conn_factory() as conn:
            directive = await confirm_research_directive(
                conn,
                workspace_id=ctx.workspace_id,
                directive_id=inputs.directive_id,
                expected_sha256=inputs.expected_sha256,
                confirmed_by=ctx.actor_id,
                confirming_turn_ref=ctx.action_ref,
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
                "confirmed_by": ctx.actor_id,
                "confirming_action_ref": ctx.action_ref,
            },
        )


def build_research_directive_tools(
    *,
    memory_write_factory: MemoryWriteFactory | None,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    return (
        DraftAccountResearchDirectiveTool(
            memory_write_factory=memory_write_factory,
            conn_factory=conn_factory,
        ),
        ConfirmAccountResearchDirectiveTool(conn_factory=conn_factory),
        DraftAccountResearchDirectiveToolV2(
            memory_write_factory=memory_write_factory,
            conn_factory=conn_factory,
        ),
        DraftAccountResearchDirectiveToolV3(
            memory_write_factory=memory_write_factory,
            conn_factory=conn_factory,
        ),
        DraftAccountResearchDirectiveToolV4(
            memory_write_factory=memory_write_factory,
            conn_factory=conn_factory,
        ),
        DraftAccountResearchDirectiveToolV5(
            memory_write_factory=memory_write_factory,
            conn_factory=conn_factory,
        ),
        ConfirmAccountResearchDirectiveToolV2(conn_factory=conn_factory),
    )


__all__ = [
    "ConfirmAccountResearchDirectiveInput",
    "ConfirmAccountResearchDirectiveOutput",
    "ConfirmAccountResearchDirectiveInputV2",
    "ConfirmAccountResearchDirectiveOutputV2",
    "ConfirmAccountResearchDirectiveTool",
    "ConfirmAccountResearchDirectiveToolV2",
    "DraftAccountResearchDirectiveInput",
    "DraftAccountResearchDirectiveInputV3",
    "DraftAccountResearchDirectiveInputV4",
    "DraftAccountResearchDirectiveInputV5",
    "DraftAccountResearchDirectiveOutput",
    "DraftAccountResearchDirectiveOutputV2",
    "DraftAccountResearchDirectiveTool",
    "DraftAccountResearchDirectiveToolV2",
    "DraftAccountResearchDirectiveToolV3",
    "DraftAccountResearchDirectiveToolV4",
    "DraftAccountResearchDirectiveToolV5",
    "ResearchDirectiveBodyDraftInput",
    "ResearchDirectiveOverrideInput",
    "build_research_directive_tools",
]
