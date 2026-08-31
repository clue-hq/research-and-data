"""S5-D governed discovery and inspection of one exact Product-KB checkpoint.

The product id and Product-KB version are trusted execution authority.  They are removed from the
model-facing schema and restored only from the turn's validated ``product_knowledge`` artifact.
Both tools are bounded, read-only, provider-free, and intentionally collapse all out-of-scope
claim states into one non-oracular refusal.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import ClassVar

from clue_api.client_knowledge_contracts import (
    MAX_FIELD_BRIEF_BYTES,
    MAX_FIELD_DESCRIPTION_BYTES,
    truncate_utf8,
)
from clue_api.client_knowledge_tools import claim_v2_payload
from clue_api.product_knowledge_contracts import (
    InspectProductClaimInput,
    ListProductKnowledgeInput,
    ProductClaimInspectionOutput,
    ProductKnowledgeCursor,
    ProductKnowledgeCursorRefused,
    ProductKnowledgeListEntry,
    ProductKnowledgeListOutput,
    ProductKnowledgeRefusalCode,
    decode_product_knowledge_cursor,
    encode_product_knowledge_cursor,
)
from clue_api.product_knowledge_reader import (
    PinnedProductKnowledge,
    ProductKnowledgePositionInvalid,
    load_pinned_product_knowledge,
    select_product_knowledge_page,
)
from clue_core import Claim, ClaimId, EntityId
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_projections import product_knowledge_topic
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

log = get_logger("clue_api.product_knowledge_tools")


def _fail(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _value_preview(value: object) -> tuple[str, bool]:
    if isinstance(value, str):
        rendered = value
    else:
        from clue_api.client_knowledge_contracts import canonical_json_bytes

        rendered = canonical_json_bytes(value).decode()
    return truncate_utf8(rendered, MAX_FIELD_BRIEF_BYTES)


def _field_label(field_key: str) -> str:
    label = field_key.rsplit(".", 1)[-1].replace("_", " ").title()
    return label or field_key


def _field_description(field_key: str, definition: object | None) -> tuple[str, bool]:
    description = getattr(definition, "description", None)
    source = description or f"Registered product knowledge for {field_key}."
    return truncate_utf8(source, MAX_FIELD_DESCRIPTION_BYTES)


ProductKnowledgeInput = ListProductKnowledgeInput | InspectProductClaimInput


class _ProductKnowledgeTool(Tool):
    version = "1"
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="exact workspace/client/product/version Product-KB checkpoint read",
        operation_id_required=False,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "read-only: creates no claim, artifact, event, memory, storage, spend, or provider call"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.READ
    pin_requirements: ClassVar[tuple[str, ...]] = ("product_kb",)

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conn_factory = conn_factory
        self._clock = clock

    async def _load_optional(
        self,
        inputs: ProductKnowledgeInput,
        ctx: ToolContext,
    ) -> PinnedProductKnowledge | None:
        async with self._conn_factory() as conn:
            return await load_pinned_product_knowledge(
                conn,
                workspace_id=ctx.workspace_id,
                client_entity_id=EntityId(inputs.client_entity_id),
                product_id=inputs.product_id,
                product_kb_version=inputs.product_kb_version,
            )

    def _scope_refusal(self, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        log.warning(
            "product_knowledge.scope_refused",
            tool=self.name,
            version=self.version,
            actor=ctx.actor,
            workspace_id=ctx.workspace_id,
        )
        return _fail(
            ProductKnowledgeRefusalCode.SCOPE_UNAVAILABLE,
            "the selected Product-KB checkpoint is unavailable",
        )

    async def _load(
        self,
        inputs: ProductKnowledgeInput,
        ctx: ToolContext,
    ) -> PinnedProductKnowledge:
        pinned = await self._load_optional(inputs, ctx)
        if pinned is None:
            raise RuntimeError("Product-KB checkpoint disappeared after precondition evaluation")
        return pinned


def _decode_cursor(
    inputs: ListProductKnowledgeInput,
) -> tuple[str | None, tuple[PreconditionFailure, ...]]:
    if inputs.cursor is None:
        return None, ()
    try:
        cursor = decode_product_knowledge_cursor(
            inputs.cursor,
            client_entity_id=inputs.client_entity_id,
            product_id=inputs.product_id,
            product_kb_version=inputs.product_kb_version,
            topic=inputs.topic,
            field_key=inputs.field_key,
            limit=inputs.limit,
        )
    except ProductKnowledgeCursorRefused:
        return None, _fail(
            ProductKnowledgeRefusalCode.CURSOR_INVALID,
            "the cursor is unavailable for this Product-KB view",
        )
    return cursor.after_field_key, ()


class ListProductKnowledgeTool(_ProductKnowledgeTool):
    name = "list_product_knowledge"
    input_model: ClassVar[type[ToolInput]] = ListProductKnowledgeInput
    output_model: ClassVar[type[ToolOutput]] = ProductKnowledgeListOutput
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("topic", "field_key", "limit")
    )

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ListProductKnowledgeInput)
        after, failure = _decode_cursor(inputs)
        if failure:
            return failure
        pinned = await self._load_optional(inputs, ctx)
        if pinned is None:
            return self._scope_refusal(ctx)
        try:
            select_product_knowledge_page(
                pinned,
                topic=inputs.topic,
                field_key=inputs.field_key,
                after_field_key=after,
                limit=inputs.limit,
            )
        except ProductKnowledgePositionInvalid:
            return _fail(
                ProductKnowledgeRefusalCode.CURSOR_INVALID,
                "the cursor is unavailable for this Product-KB view",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ListProductKnowledgeInput)
        after, _ = _decode_cursor(inputs)
        pinned = await self._load(inputs, ctx)
        page = select_product_knowledge_page(
            pinned,
            topic=inputs.topic,
            field_key=inputs.field_key,
            after_field_key=after,
            limit=inputs.limit,
        )
        entries: list[ProductKnowledgeListEntry] = []
        for field_key in page.field_keys:
            claim = pinned.claims_by_field[field_key]
            definition = pinned.definitions.get(field_key)
            description, description_truncated = _field_description(field_key, definition)
            brief, brief_truncated = _value_preview(claim.value_json)
            entries.append(
                ProductKnowledgeListEntry(
                    field_key=field_key,
                    label=_field_label(field_key),
                    description=description,
                    description_truncated=description_truncated,
                    topic=product_knowledge_topic(field_key),
                    brief_value=brief,
                    brief_truncated=brief_truncated,
                    claim_id=claim.id,
                    retired=definition is not None and not definition.active,
                )
            )
        next_cursor = (
            encode_product_knowledge_cursor(
                ProductKnowledgeCursor(
                    client_entity_id=inputs.client_entity_id,
                    product_id=inputs.product_id,
                    product_kb_version=inputs.product_kb_version,
                    after_field_key=page.next_after_field_key,
                    topic=inputs.topic,
                    field_key=inputs.field_key,
                    limit=inputs.limit,
                )
            )
            if page.has_more and page.next_after_field_key is not None
            else None
        )
        output = ProductKnowledgeListOutput(
            client_entity_id=inputs.client_entity_id,
            product_id=inputs.product_id,
            product_kb_version=inputs.product_kb_version,
            topic=inputs.topic,
            field_key=inputs.field_key,
            requested_limit=inputs.limit,
            knowledge=tuple(entries),
            returned=len(entries),
            total_matching=page.total_matching,
            has_more=page.has_more,
            next_cursor=next_cursor,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(mode="json"),
        )


class InspectProductClaimTool(_ProductKnowledgeTool):
    name = "inspect_product_claim"
    input_model: ClassVar[type[ToolInput]] = InspectProductClaimInput
    output_model: ClassVar[type[ToolOutput]] = ProductClaimInspectionOutput
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("claim_id",)
    )

    @staticmethod
    def _selected_claim(
        inputs: InspectProductClaimInput,
        pinned: PinnedProductKnowledge,
    ) -> Claim | None:
        return pinned.claim(ClaimId(inputs.claim_id))

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, InspectProductClaimInput)
        pinned = await self._load_optional(inputs, ctx)
        if pinned is None:
            return self._scope_refusal(ctx)
        if self._selected_claim(inputs, pinned) is None:
            return _fail(
                ProductKnowledgeRefusalCode.CLAIM_NOT_FOUND,
                "that claim is unavailable in this Product-KB checkpoint",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, InspectProductClaimInput)
        pinned = await self._load(inputs, ctx)
        claim = self._selected_claim(inputs, pinned)
        if claim is None:
            raise RuntimeError("Product-KB claim disappeared after precondition evaluation")
        output = ProductClaimInspectionOutput(
            client_entity_id=inputs.client_entity_id,
            product_id=inputs.product_id,
            product_kb_version=inputs.product_kb_version,
            claim=claim_v2_payload(
                claim,
                definition=pinned.definitions.get(str(claim.field_key)),
                now=self._clock(),
            ),
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(mode="json"),
        )


def build_product_knowledge_tools(
    *,
    conn_factory: ConnFactory = transaction,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[Tool, ...]:
    return (
        ListProductKnowledgeTool(conn_factory=conn_factory, clock=clock),
        InspectProductClaimTool(conn_factory=conn_factory, clock=clock),
    )


__all__ = [
    "InspectProductClaimTool",
    "ListProductKnowledgeTool",
    "build_product_knowledge_tools",
]
