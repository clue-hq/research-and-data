"""S4 governed discovery and exact inspection of one production Client-KB checkpoint.

The opening ``ClientKnowledgeCard`` is intentionally a bounded index. These two read-only tools
make that index useful without placing the whole knowledge base in every turn:

* ``list_client_knowledge@1`` walks the exact account-wide KB version pinned in L3, with topic,
  field, and opaque cursor filters;
* ``inspect_client_claim@1`` resolves one reference only when it belongs to that same pinned
  corpus and remains retention-eligible, then returns bounded provenance rather than a raw body.

Project, client, and version are typed inputs for recipe/direct invocation compatibility but never
model-authored. Project/client come from the constitution and the version is injected from S3's
immutable ``client_knowledge`` domain ref by :mod:`clue_api.client_context_authority`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from pydantic import Field, JsonValue

from clue_api.client_context_authority import TRUSTED_CLIENT_KB_VERSION_FIELD
from clue_api.client_knowledge_contracts import (
    MAX_CLAIM_VALUE_BYTES,
    MAX_EVIDENCE_SPAN_BYTES,
    MAX_FIELD_BRIEF_BYTES,
    MAX_FIELD_DESCRIPTION_BYTES,
    MAX_PROVENANCE_REF_BYTES,
    canonical_json_bytes,
    sanitize_source_url,
    truncate_utf8,
)
from clue_api.client_knowledge_reader import (
    ClientKnowledgePositionInvalid,
    PinnedClientKnowledge,
    load_pinned_client_knowledge,
    select_client_knowledge_page,
)
from clue_api.tool_outputs import ClientClaimInspectionOutput, ClientKnowledgeListOutput
from clue_core import Claim, ClaimId, EntityId, reference_time
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_projections import (
    CLIENT_KNOWLEDGE_CARD_POLICY_V1,
    ClientKnowledgeTopic,
    client_knowledge_field_label,
    client_knowledge_topic,
    decode_card_cursor,
    encode_card_cursor,
)
from clue_research.claimstore import (
    ResolvedFieldDefinition,
)
from clue_spine import get_project_for_workspace
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

log = get_logger("clue_api.client_knowledge_tools")

MAX_CLIENT_KNOWLEDGE_PAGE = 20
CLIENT_KNOWLEDGE_CURSOR_KIND = "client_knowledge"


class ClientKnowledgeScopeInput(ToolInput):
    """Trusted S3 scope common to both tools."""

    project_id: str = Field(
        min_length=1,
        description="Trusted active project; supplied by the platform, never by you.",
    )
    client_entity_id: str = Field(
        min_length=1,
        description="Trusted canonical customer account; supplied by the platform, never by you.",
    )
    client_kb_version: int = Field(
        ge=1,
        description=(
            "Trusted exact Client-KB checkpoint from this turn's immutable context; supplied by "
            "the platform, never by you."
        ),
        json_schema_extra={TRUSTED_CLIENT_KB_VERSION_FIELD: True},
    )


class ListClientKnowledgeInput(ClientKnowledgeScopeInput):
    topic: ClientKnowledgeTopic | None = Field(
        default=None,
        description=(
            "Optional card topic to narrow discovery: product, positioning, pricing_and_proof, "
            "customers_and_buyers, or other. Leave out to inspect the whole bounded index."
        ),
    )
    field_key: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        description=(
            "Optional exact registered Client-KB field, such as client.product. Use this when the "
            "card description already identifies the field you need."
        ),
    )
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=4_096,
        description=(
            "Opaque continuation from the Client-KB card's client_knowledge_over_cap omission or "
            "a previous list_client_knowledge page. Pass it verbatim; never build or edit it."
        ),
    )


class InspectClientClaimInput(ClientKnowledgeScopeInput):
    claim_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Exact claim reference from the Client-KB card or list_client_knowledge. The tool "
            "will resolve it only inside this turn's pinned Client-KB checkpoint."
        ),
    )


def _fail(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _canonical_json(value: JsonValue) -> bytes:
    return canonical_json_bytes(value)


def _value_preview(value: JsonValue, *, limit: int) -> tuple[str, bool]:
    text_value = value if isinstance(value, str) else _canonical_json(value).decode()
    return truncate_utf8(text_value, limit)


def _bounded_ref(value: str | None) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return truncate_utf8(value, MAX_PROVENANCE_REF_BYTES)


class _ClientKnowledgeTool(Tool):
    version = "1"
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="exact project/client/version read of the immutable Client-KB checkpoint",
        operation_id_required=False,
        external_boundary=ExternalReplayBoundary.NONE,
        notes="read-only: no claim, artifact, event, memory, or provider call is created",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.READ
    pin_requirements: ClassVar[tuple[str, ...]] = ("project", "client_kb")

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conn_factory = conn_factory
        self._clock = clock

    async def _load_optional(
        self, inputs: ClientKnowledgeScopeInput, ctx: ToolContext
    ) -> PinnedClientKnowledge | None:
        try:
            client_entity_id = EntityId(UUID(inputs.client_entity_id))
        except ValueError:
            return None
        async with self._conn_factory() as conn:
            project = await get_project_for_workspace(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
            )
            pinned = (
                await load_pinned_client_knowledge(
                    conn,
                    workspace_id=ctx.workspace_id,
                    client_entity_id=client_entity_id,
                    client_kb_version=inputs.client_kb_version,
                )
                if project is not None
                else None
            )
        return pinned

    def _scope_refusal(
        self, inputs: ClientKnowledgeScopeInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        log.warning(
            "client_knowledge.scope_refused",
            tool=self.name,
            actor=ctx.actor,
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
        )
        return _fail(
            "client_knowledge_unavailable",
            "the production Client-KB checkpoint is unavailable for this project",
        )

    async def _load(
        self, inputs: ClientKnowledgeScopeInput, ctx: ToolContext
    ) -> PinnedClientKnowledge:
        pinned = await self._load_optional(inputs, ctx)
        if pinned is None:  # the runner checked immediately before invoke; fail closed on drift
            raise RuntimeError("Client-KB checkpoint disappeared after precondition evaluation")
        return pinned


def _decode_list_cursor(
    inputs: ListClientKnowledgeInput,
) -> tuple[dict[str, JsonValue], tuple[PreconditionFailure, ...]]:
    if inputs.cursor is None:
        return {}, ()
    try:
        payload = decode_card_cursor(inputs.cursor)
    except (ValueError, TypeError, UnicodeDecodeError):
        return {}, _fail("client_knowledge_cursor_invalid", "the cursor is not readable")
    required = {
        "kind": CLIENT_KNOWLEDGE_CURSOR_KIND,
        "client_kb_version": inputs.client_kb_version,
    }
    if any(payload.get(key) != value for key, value in required.items()):
        return {}, _fail(
            "client_knowledge_cursor_invalid",
            "the cursor does not belong to this Client-KB checkpoint",
        )
    cursor_client = payload.get("client_entity_id")
    if cursor_client is not None and cursor_client != inputs.client_entity_id:
        return {}, _fail(
            "client_knowledge_cursor_invalid",
            "the cursor does not belong to this Client-KB checkpoint",
        )
    schema_version = payload.get("schema_version")
    if schema_version not in {None, "1"}:
        return {}, _fail("client_knowledge_cursor_invalid", "the cursor schema is unsupported")
    policy = payload.get("compiler_policy_version")
    if policy not in {None, CLIENT_KNOWLEDGE_CARD_POLICY_V1.version}:
        return {}, _fail("client_knowledge_cursor_invalid", "the cursor policy is unsupported")
    cursor_topic = payload.get("topic")
    requested_topic = inputs.topic.value if inputs.topic is not None else None
    cursor_field = payload.get("field_key")
    if (
        cursor_topic is not None
        and cursor_topic != requested_topic
        or cursor_field is not None
        and cursor_field != inputs.field_key
    ):
        return {}, _fail(
            "client_knowledge_cursor_invalid",
            "the cursor filters differ from this request",
        )
    return payload, ()


class ListClientKnowledgeTool(_ClientKnowledgeTool):
    """Bounded discovery over the exact Client-KB card/index corpus."""

    name = "list_client_knowledge"
    input_model: ClassVar[type[ToolInput]] = ListClientKnowledgeInput
    output_model: ClassVar[type[ToolOutput]] = ClientKnowledgeListOutput
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("topic", "field_key", "cursor")
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ListClientKnowledgeInput)
        cursor, cursor_failure = _decode_list_cursor(inputs)
        if cursor_failure:
            return cursor_failure
        pinned = await self._load_optional(inputs, ctx)
        if pinned is None:
            return self._scope_refusal(inputs, ctx)
        after = cursor.get("after_field_key")
        try:
            select_client_knowledge_page(
                pinned,
                topic=inputs.topic,
                field_key=inputs.field_key,
                after_field_key=after if isinstance(after, str) else None,
                limit=MAX_CLIENT_KNOWLEDGE_PAGE,
            )
        except ClientKnowledgePositionInvalid:
            return _fail(
                "client_knowledge_cursor_invalid",
                "the cursor does not belong to this Client-KB checkpoint",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ListClientKnowledgeInput)
        cursor, _ = _decode_list_cursor(inputs)
        pinned = await self._load(inputs, ctx)
        after = cursor.get("after_field_key")
        page = select_client_knowledge_page(
            pinned,
            topic=inputs.topic,
            field_key=inputs.field_key,
            after_field_key=after if isinstance(after, str) else None,
            limit=MAX_CLIENT_KNOWLEDGE_PAGE,
        )
        next_cursor = (
            encode_card_cursor(
                {
                    "kind": CLIENT_KNOWLEDGE_CURSOR_KIND,
                    "schema_version": "1",
                    "client_entity_id": inputs.client_entity_id,
                    "client_kb_version": inputs.client_kb_version,
                    "compiler_policy_version": CLIENT_KNOWLEDGE_CARD_POLICY_V1.version,
                    "after_field_key": page.next_after_field_key,
                    "topic": inputs.topic.value if inputs.topic is not None else None,
                    "field_key": inputs.field_key,
                }
            )
            if page.has_more and page.next_after_field_key is not None
            else None
        )
        entries: list[dict[str, object]] = []
        for field_key in page.field_keys:
            claim = pinned.claims_by_field[field_key]
            definition = pinned.definitions.get(field_key)
            description_source = getattr(definition, "description", None) or (
                f"Registered Client-KB knowledge for {field_key}."
            )
            description, description_truncated = truncate_utf8(
                description_source, MAX_FIELD_DESCRIPTION_BYTES
            )
            brief, brief_truncated = _value_preview(claim.value_json, limit=MAX_FIELD_BRIEF_BYTES)
            entries.append(
                {
                    "field_key": field_key,
                    "label": client_knowledge_field_label(field_key),
                    "description": description,
                    "description_truncated": description_truncated,
                    "topic": client_knowledge_topic(field_key).value,
                    "brief_value": brief,
                    "brief_truncated": brief_truncated,
                    "claim_id": str(claim.id),
                    "retired": definition is not None and not definition.active,
                }
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=ClientKnowledgeListOutput(
                project_id=inputs.project_id,
                client_entity_id=inputs.client_entity_id,
                client_kb_version=inputs.client_kb_version,
                topic=inputs.topic.value if inputs.topic is not None else None,
                field_key=inputs.field_key,
                knowledge=entries,
                page_size=MAX_CLIENT_KNOWLEDGE_PAGE,
                returned=len(entries),
                total_matching=page.total_matching,
                has_more=page.has_more,
                next_cursor=next_cursor,
            ).model_dump(mode="json"),
        )


def _claim_payload(
    claim: Claim,
    *,
    definition: ResolvedFieldDefinition | None,
    now: datetime,
) -> dict[str, object]:
    raw_value = _canonical_json(claim.value_json)
    value_preview, value_truncated = _value_preview(claim.value_json, limit=MAX_CLAIM_VALUE_BYTES)
    evidence_span, evidence_truncated = (
        truncate_utf8(claim.evidence_span, MAX_EVIDENCE_SPAN_BYTES)
        if claim.evidence_span is not None
        else (None, False)
    )
    safe_url = sanitize_source_url(claim.source_url)
    artifact_key, artifact_key_truncated = _bounded_ref(claim.artifact_key)
    operation_ref, operation_ref_truncated = _bounded_ref(claim.source_operation_ref)
    snapshot_ref, snapshot_ref_truncated = _bounded_ref(claim.source_snapshot_ref)
    request_ref, request_ref_truncated = _bounded_ref(claim.source_request_ref)
    ttl = definition.field_def.freshness_ttl if definition is not None else None
    reference = reference_time(claim)
    if ttl is None:
        freshness = "not_configured"
        fresh_until = None
    else:
        fresh_until_at = reference + ttl
        freshness = "fresh" if now <= fresh_until_at else "stale"
        fresh_until = fresh_until_at.isoformat()
    return {
        "claim_id": str(claim.id),
        "field": {
            "field_key": str(claim.field_key),
            "label": client_knowledge_field_label(str(claim.field_key)),
            "topic": client_knowledge_topic(str(claim.field_key)).value,
            "description": (
                truncate_utf8(definition.description, MAX_FIELD_DESCRIPTION_BYTES)[0]
                if definition is not None and definition.description
                else f"Registered Client-KB knowledge for {claim.field_key}."
            ),
            "retired": definition is not None and not definition.active,
        },
        "value": claim.value_json if not value_truncated else None,
        "value_preview": value_preview,
        "value_sha256": f"sha256:{hashlib.sha256(raw_value).hexdigest()}",
        "value_truncated": value_truncated,
        "evidence_span": evidence_span,
        "evidence_span_truncated": evidence_truncated,
        "source": {
            "source_key": claim.source_key,
            "source_tier": int(claim.source_tier),
            "extraction_method": claim.extraction_method.value,
            "source_url": safe_url.public_origin,
            "source_url_sha256": safe_url.exact_sha256,
            "source_url_redacted": safe_url.redacted,
            "artifact_key": artifact_key,
            "artifact_key_truncated": artifact_key_truncated,
        },
        "provider_lineage": {
            "operation_ref": operation_ref,
            "operation_ref_truncated": operation_ref_truncated,
            "snapshot_ref": snapshot_ref,
            "snapshot_ref_truncated": snapshot_ref_truncated,
            "request_ref": request_ref,
            "request_ref_truncated": request_ref_truncated,
        },
        "quality": {
            "confidence": str(claim.confidence),
            "corroborations": int(claim.corroborations),
            "verification_status": claim.verification_status.value,
            "freshness": freshness,
            "freshness_reference_at": reference.isoformat(),
            "fresh_until": fresh_until,
        },
        "lineage": {
            "run_id": str(claim.run_id),
            "research_mode": claim.research_mode.value,
            "provenance_kind": (
                claim.provenance_kind.value if claim.provenance_kind is not None else None
            ),
            "claim_flavor": claim.claim_flavor.value,
            "reuse_scope": claim.reuse_scope.value,
            "product_id": claim.product_id,
            "observed_at": claim.observed_at.isoformat() if claim.observed_at else None,
            "collected_at": claim.collected_at.isoformat(),
        },
    }


class InspectClientClaimTool(_ClientKnowledgeTool):
    """Inspect one exact in-checkpoint claim with bounded, retention-safe provenance."""

    name = "inspect_client_claim"
    input_model: ClassVar[type[ToolInput]] = InspectClientClaimInput
    output_model: ClassVar[type[ToolOutput]] = ClientClaimInspectionOutput
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("claim_id",)
    )

    @staticmethod
    def _selected_claim(
        inputs: InspectClientClaimInput, pinned: PinnedClientKnowledge
    ) -> Claim | None:
        try:
            claim_id = ClaimId(UUID(inputs.claim_id))
        except ValueError:
            return None
        return pinned.claim(claim_id)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, InspectClientClaimInput)
        pinned = await self._load_optional(inputs, ctx)
        if pinned is None:
            return self._scope_refusal(inputs, ctx)
        if self._selected_claim(inputs, pinned) is None:
            # Foreign, unknown, non-member, wrong-version, and retention-expired are deliberately
            # the same answer. The caller learns no existence/state fact outside the pinned card.
            return _fail(
                "client_claim_not_found",
                "that claim is unavailable in this Client-KB checkpoint",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, InspectClientClaimInput)
        pinned = await self._load(inputs, ctx)
        claim = self._selected_claim(inputs, pinned)
        if claim is None:
            raise RuntimeError("Client-KB claim disappeared after precondition evaluation")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=ClientClaimInspectionOutput(
                project_id=inputs.project_id,
                client_entity_id=inputs.client_entity_id,
                client_kb_version=inputs.client_kb_version,
                claim=_claim_payload(
                    claim,
                    definition=pinned.definitions.get(str(claim.field_key)),
                    now=self._clock(),
                ),
            ).model_dump(mode="json"),
        )


def build_client_knowledge_tools(
    *,
    conn_factory: ConnFactory = transaction,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[Tool, ...]:
    return (
        ListClientKnowledgeTool(conn_factory=conn_factory, clock=clock),
        InspectClientClaimTool(conn_factory=conn_factory, clock=clock),
    )


__all__ = [
    "CLIENT_KNOWLEDGE_CURSOR_KIND",
    "MAX_CLIENT_KNOWLEDGE_PAGE",
    "InspectClientClaimInput",
    "InspectClientClaimTool",
    "ListClientKnowledgeInput",
    "ListClientKnowledgeTool",
    "build_client_knowledge_tools",
]
