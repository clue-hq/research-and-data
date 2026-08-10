"""The FI Lane D **dev-lens** turn-context inspector — wire shapes and composition.

Four read views over one assistant turn, for one purpose: tuning prompts and skills by seeing what
the model was actually given and how it actually reacted. Everything served here is a C6 receipt the
turn already wrote (:mod:`clue_projections.turn_inspector` does the joins); this module adds the
wire spelling, the artifact hydration, and the byte budget.

Three rules the shapes enforce rather than merely document.

**Zero new storage.** Nothing is recorded so that the inspector can show it. A fact the platform did
not already make durable is absent from the response, with the reason it is absent, and is never
reconstructed from something adjacent.

**Bytes are budgeted, and truncation is loud.** A context layer can hold a compiled card of any
size, and a plan can be a large JSON document. One response therefore spends a cumulative byte
budget: bodies within it are hydrated in full, and everything past it comes back as its content
address plus ``omitted_reason='budget'``. There is no path that returns a shortened body — a
half-rendered prompt is worse than an honestly-absent one, because a developer would tune against
text the model never saw. ``truncated`` says so at the top of the response.

**Dev-only by construction.** These shapes are only ever built by routes that
``build_chat_router`` refuses to register unless ``settings.chat_dev_inspector_enabled``, and that
setting fails process construction in a production deployment
(``Settings._refuse_dev_lens_in_production``). The inspector is therefore unreachable in production
in the strongest available sense: the routes do not exist, in a process that would not have started.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.chat.message_bodies import hydrate_message_bodies
from clue_projections import (
    TurnContextReceiptView,
    TurnModelRoundView,
    TurnPlanReceiptView,
    TurnStatusEventView,
    TurnToolCallView,
)
from clue_storage import StorageBackend

__all__ = [
    "INSPECTOR_TABS",
    "InspectorCapabilityResponse",
    "InspectorCapabilityWire",
    "InspectorContextResponse",
    "InspectorPlanResponse",
    "InspectorRoundsResponse",
    "InspectorToolsResponse",
    "BodyWire",
    "context_response",
    "plan_response",
    "rounds_response",
    "tools_response",
]

#: The drawer's four tabs, named once so the capability probe and the routes cannot disagree.
INSPECTOR_TABS: tuple[str, ...] = ("context", "rounds", "plan", "tools")


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BodyWire(_Wire):
    """One content-addressed body, or the honest reason it is not here.

    Exactly one of ``text``/``omitted_reason`` is set. The reason codes are
    :func:`~clue_api.chat.message_bodies.hydrate_message_bodies`'s: ``budget`` (the response's byte
    budget was already spent), ``unavailable`` (erased, purged, tombstoned or no durable row),
    ``artifact_missing`` (the row exists but the physical blob is gone), ``digest_mismatch`` (the
    stored bytes no longer match what the receipt committed to), and ``not_text`` (a binary
    artifact is not a prompt and never becomes one by being decoded).
    """

    artifact_key: str
    sha256: str
    text: str | None = None
    omitted_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _Hydration:
    """The result of one response's bounded hydration pass."""

    bodies: dict[str, BodyWire]
    truncated: bool

    def of(self, artifact_key: str | None, sha256: str | None) -> BodyWire | None:
        if artifact_key is None or sha256 is None:
            return None
        return self.bodies.get(artifact_key)


async def _hydrate(
    conn: AsyncConnection,
    *,
    storage: StorageBackend | None,
    workspace_id: str,
    references: Sequence[tuple[str, str]],
    budget_bytes: int,
) -> _Hydration:
    """Resolve every ``(artifact_key, sha256)`` this response wants, within one shared budget.

    Without a storage backend nothing is hydrated and every body reports ``unavailable`` — the same
    posture the transcript's ``?include=bodies`` takes, and for the same reason: a surface that
    cannot read bytes must say so rather than serve an empty string.
    """

    if not references:
        return _Hydration(bodies={}, truncated=False)
    if storage is None:
        return _Hydration(
            bodies={
                key: BodyWire(artifact_key=key, sha256=sha, omitted_reason="unavailable")
                for key, sha in references
            },
            truncated=True,
        )
    hydrated = await hydrate_message_bodies(
        conn,
        storage=storage,
        workspace_id=workspace_id,
        references=references,
        budget_bytes=budget_bytes,
    )
    digests = dict(references)
    bodies = {
        key: BodyWire(
            artifact_key=key,
            sha256=digests.get(key, ""),
            text=item.body,
            omitted_reason=item.reason,
        )
        for key, item in hydrated.items()
    }
    return _Hydration(
        bodies=bodies,
        truncated=any(item.omitted_reason == "budget" for item in bodies.values()),
    )


# --- capability probe ----------------------------------------------------------------------------


class InspectorCapabilityWire(_Wire):
    """What the surface can serve. The frontend renders no affordance without this."""

    enabled: bool
    tabs: tuple[str, ...]
    budget_bytes: int
    #: False when the deployment has no artifact backend: the four tabs still serve their receipts,
    #: but every body comes back ``unavailable``.
    bodies_available: bool


class InspectorCapabilityResponse(_Wire):
    data: InspectorCapabilityWire


# --- tab 1: context -------------------------------------------------------------------------------


class InspectorContextRefWire(_Wire):
    disposition: str
    ordinal: int
    ref_kind: str
    artifact_key: str | None
    artifact_sha256: str | None
    object_type: str | None
    object_id: str | None
    object_version: int | None
    content_sha256: str | None
    materialized_path: str | None
    token_count: int | None
    exclusion_reason_code: str | None
    body: BodyWire | None


class InspectorContextLayerWire(_Wire):
    ordinal: int
    layer: str
    token_budget: int
    token_count: int
    included_count: int
    excluded_count: int
    refs: tuple[InspectorContextRefWire, ...]


class InspectorContextWire(_Wire):
    turn_id: str
    context_bundle_id: str
    schema_version: str
    policy_version: str
    token_counter_version: str
    aggregate_sha256: str
    assembled_at: str
    layers: tuple[InspectorContextLayerWire, ...]
    budget_bytes: int
    truncated: bool


class InspectorContextResponse(_Wire):
    #: ``None`` for a turn that never assembled a context bundle (it failed before L1) — an honest
    #: gap, not an empty seven-layer skeleton.
    data: InspectorContextWire | None


async def context_response(
    conn: AsyncConnection,
    *,
    storage: StorageBackend | None,
    workspace_id: str,
    turn_id: str,
    receipt: TurnContextReceiptView | None,
    budget_bytes: int,
) -> InspectorContextResponse:
    """The Context tab: the seven layers, their budgets, and the exact included bytes.

    Only **included** artifact refs are hydrated. An excluded ref was, by definition, not put in
    front of the model, so serving its body would answer a question nobody asked while spending the
    budget that answers the one they did — its reason code is the interesting fact, and it is
    already on the row.
    """

    if receipt is None:
        return InspectorContextResponse(data=None)
    references = [
        (ref.artifact_key, ref.artifact_sha256)
        for layer in receipt.layers
        for ref in layer.refs
        if ref.disposition == "included"
        and ref.artifact_key is not None
        and ref.artifact_sha256 is not None
    ]
    hydration = await _hydrate(
        conn,
        storage=storage,
        workspace_id=workspace_id,
        references=references,
        budget_bytes=budget_bytes,
    )
    return InspectorContextResponse(
        data=InspectorContextWire(
            turn_id=turn_id,
            context_bundle_id=str(receipt.context_bundle_id),
            schema_version=receipt.schema_version,
            policy_version=receipt.policy_version,
            token_counter_version=receipt.token_counter_version,
            aggregate_sha256=receipt.aggregate_sha256,
            assembled_at=receipt.assembled_at.isoformat(),
            layers=tuple(
                InspectorContextLayerWire(
                    ordinal=layer.ordinal,
                    layer=layer.layer,
                    token_budget=layer.token_budget,
                    token_count=layer.token_count,
                    included_count=layer.included_count,
                    excluded_count=layer.excluded_count,
                    refs=tuple(
                        InspectorContextRefWire(
                            disposition=ref.disposition,
                            ordinal=ref.ordinal,
                            ref_kind=ref.ref_kind,
                            artifact_key=ref.artifact_key,
                            artifact_sha256=ref.artifact_sha256,
                            object_type=ref.object_type,
                            object_id=ref.object_id,
                            object_version=ref.object_version,
                            content_sha256=ref.content_sha256,
                            materialized_path=ref.materialized_path,
                            token_count=ref.token_count,
                            exclusion_reason_code=ref.exclusion_reason_code,
                            body=(
                                hydration.of(ref.artifact_key, ref.artifact_sha256)
                                if ref.disposition == "included"
                                else None
                            ),
                        )
                        for ref in layer.refs
                    ),
                )
                for layer in receipt.layers
            ),
            budget_bytes=budget_bytes,
            truncated=hydration.truncated,
        )
    )


# --- tab 2: rounds --------------------------------------------------------------------------------


class InspectorRoundWire(_Wire):
    model_call_id: str
    sequence: int
    requested_model: str
    answering_model: str | None
    status: str
    input_tokens: int
    output_tokens: int
    cost_millicredits: int
    latency_ms: float
    error_code: str | None
    started_at: str
    completed_at: str | None


class InspectorRoundsResponse(_Wire):
    data: tuple[InspectorRoundWire, ...]


def rounds_response(rounds: Sequence[TurnModelRoundView]) -> InspectorRoundsResponse:
    """The Rounds tab: one row per governed model call, in call order.

    It carries no reasoning text. The raw reasoning trace of a round is a *stream* artefact with no
    durable counterpart (charter §3.3 and the dev lens's own ephemerality marker), so the drawer
    joins it in from the live turn stream rather than asking this read to invent a store for it.
    """

    return InspectorRoundsResponse(
        data=tuple(
            InspectorRoundWire(
                model_call_id=str(item.model_call_id),
                sequence=item.sequence,
                requested_model=item.requested_model,
                answering_model=item.answering_model,
                status=item.status,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                cost_millicredits=item.cost_millicredits,
                latency_ms=item.latency_ms,
                error_code=item.error_code,
                started_at=item.started_at.isoformat(),
                completed_at=None if item.completed_at is None else item.completed_at.isoformat(),
            )
            for item in rounds
        )
    )


# --- tab 3: plan ----------------------------------------------------------------------------------


class InspectorPlanOperationWire(_Wire):
    node_key: str
    ordinal: int
    operation_id: str
    kind: str
    address: str
    estimated_cost_millicents: int
    authority_sha256: str
    #: Always ``"admitted"``. Spelled out rather than implied because the field beside it —
    #: ``turn_events`` — is where a *refused* plan's verdict lives, and a reader must not have to
    #: infer which of the two they are looking at.
    validation: str = "admitted"


class InspectorPlanEventWire(_Wire):
    status: str
    reason_code: str | None
    created_at: str


class InspectorPlanWire(_Wire):
    plan_id: str
    role: str
    resource_manifest_sha256: str
    max_parallelism: int
    estimated_cost_millicents: int
    budget_limit_millicents: int
    validated_at: str
    #: What the model authored, verbatim.
    proposal: BodyWire
    #: What validation admitted. Diffing the two is how "which step was dropped?" is answered.
    validated: BodyWire
    operations: tuple[InspectorPlanOperationWire, ...]
    events: tuple[InspectorPlanEventWire, ...]


class InspectorPlanWireEnvelope(_Wire):
    turn_id: str
    plans: tuple[InspectorPlanWire, ...]
    #: The turn's own append-only status ledger. A plan the validator **rejects** raises before
    #: anything is journaled, so it has no ``agent_plan`` row and no per-operation verdict; its
    #: refusal is recorded here (and on the refused tool card in the turn stream). Reporting the gap
    #: is the honest move — manufacturing a "refused operation" row from an exception would not be.
    turn_events: tuple[InspectorPlanEventWire, ...]
    budget_bytes: int
    truncated: bool


class InspectorPlanResponse(_Wire):
    data: InspectorPlanWireEnvelope


async def plan_response(
    conn: AsyncConnection,
    *,
    storage: StorageBackend | None,
    workspace_id: str,
    turn_id: str,
    plans: Sequence[TurnPlanReceiptView],
    turn_events: Sequence[TurnStatusEventView],
    budget_bytes: int,
) -> InspectorPlanResponse:
    """The Plan tab: the authored plan, what was admitted, and the verdict ledgers."""

    references = [
        reference
        for plan in plans
        for reference in (
            (plan.proposal_artifact_key, plan.proposal_sha256),
            (plan.validated_artifact_key, plan.validated_sha256),
        )
    ]
    hydration = await _hydrate(
        conn,
        storage=storage,
        workspace_id=workspace_id,
        references=references,
        budget_bytes=budget_bytes,
    )

    def _body(key: str, sha: str) -> BodyWire:
        return hydration.bodies.get(key) or BodyWire(
            artifact_key=key, sha256=sha, omitted_reason="unavailable"
        )

    return InspectorPlanResponse(
        data=InspectorPlanWireEnvelope(
            turn_id=turn_id,
            plans=tuple(
                InspectorPlanWire(
                    plan_id=str(plan.plan_id),
                    role=plan.role,
                    resource_manifest_sha256=plan.resource_manifest_sha256,
                    max_parallelism=plan.max_parallelism,
                    estimated_cost_millicents=plan.estimated_cost_millicents,
                    budget_limit_millicents=plan.budget_limit_millicents,
                    validated_at=plan.validated_at.isoformat(),
                    proposal=_body(plan.proposal_artifact_key, plan.proposal_sha256),
                    validated=_body(plan.validated_artifact_key, plan.validated_sha256),
                    operations=tuple(
                        InspectorPlanOperationWire(
                            node_key=operation.node_key,
                            ordinal=operation.ordinal,
                            operation_id=str(operation.operation_id),
                            kind=operation.kind,
                            address=operation.address,
                            estimated_cost_millicents=operation.estimated_cost_millicents,
                            authority_sha256=operation.authority_sha256,
                        )
                        for operation in plan.operations
                    ),
                    events=tuple(
                        InspectorPlanEventWire(
                            status=event.status,
                            reason_code=event.reason_code,
                            created_at=event.created_at.isoformat(),
                        )
                        for event in plan.events
                    ),
                )
                for plan in plans
            ),
            turn_events=tuple(
                InspectorPlanEventWire(
                    status=event.status,
                    reason_code=event.reason_code,
                    created_at=event.created_at.isoformat(),
                )
                for event in turn_events
            ),
            budget_bytes=budget_bytes,
            truncated=hydration.truncated,
        )
    )


# --- tab 4: tools ---------------------------------------------------------------------------------


class InspectorToolCallWire(_Wire):
    plan_id: str
    node_key: str
    operation_id: str
    kind: str
    address: str
    estimated_cost_millicents: int
    #: The exact arguments the operation ran with, as the parameter snapshot recorded them.
    arguments: BodyWire
    #: The receipt, when the operation produced one. ``None`` means admitted-and-not-completed.
    result: BodyWire | None
    replayed: bool | None
    reference_count: int | None
    completed_at: str | None


class InspectorToolsWire(_Wire):
    turn_id: str
    calls: tuple[InspectorToolCallWire, ...]
    budget_bytes: int
    truncated: bool


class InspectorToolsResponse(_Wire):
    data: InspectorToolsWire


async def tools_response(
    conn: AsyncConnection,
    *,
    storage: StorageBackend | None,
    workspace_id: str,
    turn_id: str,
    calls: Sequence[TurnToolCallView],
    budget_bytes: int,
) -> InspectorToolsResponse:
    """The Tools tab: admitted operations, their arguments, and their receipts.

    A tool call refused *before* admission (``plan_rejected``) has no operation row and therefore no
    entry here; its refusal is a live turn-stream fact the drawer reads from the tool card, and the
    Plan tab's ``turn_events`` is its durable ledger. This tab does not pretend otherwise.
    """

    references = [
        reference
        for call in calls
        for reference in (
            [(call.parameter_artifact_key, call.parameter_sha256)]
            + (
                [(call.result_artifact_key, call.result_sha256)]
                if call.result_artifact_key is not None and call.result_sha256 is not None
                else []
            )
        )
    ]
    hydration = await _hydrate(
        conn,
        storage=storage,
        workspace_id=workspace_id,
        references=references,
        budget_bytes=budget_bytes,
    )

    def _body(key: str, sha: str) -> BodyWire:
        return hydration.bodies.get(key) or BodyWire(
            artifact_key=key, sha256=sha, omitted_reason="unavailable"
        )

    return InspectorToolsResponse(
        data=InspectorToolsWire(
            turn_id=turn_id,
            calls=tuple(
                InspectorToolCallWire(
                    plan_id=str(call.plan_id),
                    node_key=call.node_key,
                    operation_id=str(call.operation_id),
                    kind=call.kind,
                    address=call.address,
                    estimated_cost_millicents=call.estimated_cost_millicents,
                    arguments=_body(call.parameter_artifact_key, call.parameter_sha256),
                    result=(
                        None
                        if call.result_artifact_key is None or call.result_sha256 is None
                        else _body(call.result_artifact_key, call.result_sha256)
                    ),
                    replayed=call.replayed,
                    reference_count=call.reference_count,
                    completed_at=(
                        None if call.completed_at is None else call.completed_at.isoformat()
                    ),
                )
                for call in calls
            ),
            budget_bytes=budget_bytes,
            truncated=hydration.truncated,
        )
    )
