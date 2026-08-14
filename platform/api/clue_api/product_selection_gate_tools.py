"""S5-F governed presentation of the human project-product selection gate.

The model may decide that the conversation is ready to ask the human, but it cannot propose the
candidate set, the client, a knowledge version, an addressee, or the selected product.  This tool
derives all of those values from the current turn's durable scope pin and the exact synchronized
``ClientKnowledgeCard@2`` catalog.  It writes only the immutable question.  The chat route records
the human's structured answer and invokes ``confirm_project_product@1`` outside the model surface.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, ClassVar, cast
from uuid import UUID

from pydantic import Field, JsonValue, StringConstraints

from clue_api.agent_gate import (
    DEFAULT_GATE_CURRENCY,
    KIND_PRODUCT_SELECTION,
    insert_gate,
    product_selection_gate_id,
)
from clue_api.agent_gate_tools import gate_ref
from clue_api.agent_turn_scope_pin import get_agent_turn_scope_pin
from clue_api.product_context_compiler import (
    ProductContextScopeError,
    compile_client_knowledge_card_v2,
)
from clue_api.turn_action import (
    TurnActionUnresolvable,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
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

__all__ = [
    "OpenProductSelectionGateInput",
    "OpenProductSelectionGateOutput",
    "OpenProductSelectionGateTool",
    "build_product_selection_gate_tools",
]


class OpenProductSelectionGateInput(ToolInput):
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class OpenProductSelectionGateOutput(ToolOutput):
    gate_id: str
    gate_ref: str
    gate_kind: str
    candidate_count: int
    addressee_user_id: str
    created: bool


class _SelectionRefused(ValueError):
    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _ResolvedSelection:
    gate_id: UUID
    turn_id: UUID
    thread_id: str
    project_id: str
    addressee: str
    company_version: int
    subject_ref: str
    digest: str
    snapshot: dict[str, JsonValue]
    candidate_count: int


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


class OpenProductSelectionGateTool(Tool):
    name = "open_product_selection_gate"
    version = "1"
    model_description = (
        "Present the current human with the product choices from the exact turn-pinned company "
        "catalog. The platform derives the candidates and authority; this call confirms nothing. "
        "End the turn awaiting input with the returned gate_ref."
    )
    input_model: ClassVar[type[ToolInput]] = OpenProductSelectionGateInput
    output_model: ClassVar[type[ToolOutput]] = OpenProductSelectionGateOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="one product-selection presentation for one turn-pinned catalog",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=())
    pin_requirements = ("project", "client_kb")

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OpenProductSelectionGateInput)
        try:
            await self._resolve(inputs, ctx)
        except _SelectionRefused as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OpenProductSelectionGateInput)
        resolved = await self._resolve(inputs, ctx)
        async with self._conn_factory() as conn:
            row, created = await insert_gate(
                conn,
                gate_id=resolved.gate_id,
                workspace_id=ctx.workspace_id,
                project_id=resolved.project_id,
                thread_id=resolved.thread_id,
                turn_id=resolved.turn_id,
                kind=KIND_PRODUCT_SELECTION,
                subject_ref=resolved.subject_ref,
                subject_revision=resolved.company_version,
                expected_subject_sha256=resolved.digest,
                subject_snapshot=resolved.snapshot,
                max_spend_cents=Decimal(0),
                currency=DEFAULT_GATE_CURRENCY,
                addressee_user_id=resolved.addressee,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "gate_id": str(row.gate_id),
                "gate_ref": gate_ref(row.gate_id),
                "gate_kind": row.kind,
                "candidate_count": resolved.candidate_count,
                "addressee_user_id": row.addressee_user_id,
                "created": created,
            },
        )

    async def _resolve(
        self, inputs: OpenProductSelectionGateInput, ctx: ToolContext
    ) -> _ResolvedSelection:
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _SelectionRefused(
                "the current turn reference is unavailable",
                reason_code="product_selection_turn_not_found",
            ) from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
            pin = await get_agent_turn_scope_pin(
                conn, workspace_id=ctx.workspace_id, turn_id=turn_id
            )
        if turn is None or pin is None or turn.project_id != pin.project_id:
            raise _SelectionRefused(
                "the current turn has no durable project scope",
                reason_code="product_selection_scope_unavailable",
            )
        if not turn.submitted_by_user_id:
            raise _SelectionRefused(
                "the current turn has no human addressee",
                reason_code="product_selection_addressee_missing",
            )
        if pin.product_id is not None:
            raise _SelectionRefused(
                "this project already has an immutable selected product",
                reason_code="project_product_already_confirmed",
            )
        if pin.client_entity_id is None or pin.client_kb_version is None:
            raise _SelectionRefused(
                "the company catalog is not available for this turn",
                reason_code="product_catalog_unavailable",
            )
        try:
            card = await compile_client_knowledge_card_v2(
                workspace_id=ctx.workspace_id,
                client_entity_id=pin.client_entity_id,
                company_client_kb_version=pin.client_kb_version,
                conn_factory=self._conn_factory,
            )
        except ProductContextScopeError as exc:
            raise _SelectionRefused(
                "the company catalog is not available for this turn",
                reason_code="product_catalog_unavailable",
            ) from exc
        products: list[dict[str, JsonValue]] = [
            {
                "product_id": item.product_id,
                "name": item.name,
                "short_description": item.short_description,
                "aliases": list(item.aliases),
                "status": item.status,
            }
            for item in card.product_catalog.entries
        ]
        if not products:
            raise _SelectionRefused(
                "the company catalog contains no selectable products",
                reason_code="product_catalog_empty",
            )
        snapshot: dict[str, JsonValue] = {
            "client_entity_id": str(pin.client_entity_id),
            "company_client_kb_version": pin.client_kb_version,
            "products": cast(JsonValue, products),
            "omitted_count": sum(item.count for item in card.product_catalog.omissions),
        }
        canonical = json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        subject_ref = f"client-product-catalog:{pin.client_entity_id}:v{pin.client_kb_version}"
        return _ResolvedSelection(
            turn_id=turn.turn_id,
            thread_id=turn.thread_id,
            project_id=turn.project_id,
            addressee=turn.submitted_by_user_id,
            company_version=pin.client_kb_version,
            subject_ref=subject_ref,
            digest=digest,
            snapshot=snapshot,
            candidate_count=len(products),
            gate_id=product_selection_gate_id(
                workspace_id=ctx.workspace_id,
                turn_id=turn.turn_id,
                subject_ref=subject_ref,
                expected_subject_sha256=digest,
            ),
        )


def build_product_selection_gate_tools(
    *, conn_factory: ConnFactory = transaction
) -> tuple[Tool, ...]:
    return (OpenProductSelectionGateTool(conn_factory=conn_factory),)
