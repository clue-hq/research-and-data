"""Read projections behind the FI Lane D **dev-lens** turn-context inspector.

The mini-slice's second half exists so a developer tuning a prompt or a skill can see *what the
model was given* and *how it reacted*, and its governing constraint is that it adds **zero
storage**: every view here is a join over C6 receipts a turn already wrote (migrations
``7e9269ed8a81`` for the turn/context/model-call tables and ``6628a407e993`` for the
plan/operation/tool-result tables). Nothing is recorded for the inspector's benefit; if a fact was
not already durable, the inspector does not show it.

Four views, one per drawer tab:

* :func:`turn_context_receipt` — the seven-layer assembly receipt: the bundle's versions and
  aggregate digest, each layer's token count against its budget, and every included *and excluded*
  pointer with the reason it was dropped. It carries content **addresses**, never bytes: the
  projections package is DB-only by contract, so hydration is the HTTP surface's job (which is also
  where a byte budget belongs).
* :func:`turn_model_rounds` — ``agent_model_call``: the requested and the answering model, tokens,
  cost, status and timing, per round.
* :func:`turn_plan_receipt` — the authored plan and what validation admitted: the proposal and
  validated artifact addresses, the admitted operations, and the plan's own event ledger.
* :func:`turn_tool_calls` — the admitted operations with their parameter and result addresses and
  replay/reference counts.

**One honest gap, stated rather than papered over.** A plan the validator *rejects* raises before
anything is journaled — ``C5AgentExecutionAdapter.validate_plan`` refuses ahead of
``record_validated`` — so there is no durable per-operation "refused" row to project, and inventing
one would be exactly the fabrication this platform exists not to do. What *is* durable for a refusal
is the turn's own event ledger (:func:`turn_status_ledger`, ``agent_turn_event.reason_code``) and
the refused tool card the stream emitted; the drawer reads both and says which is which.

Read-only and workspace-scoped in SQL on every statement, like every other member of this package.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import ConnFactory, transaction

__all__ = [
    "TurnContextLayerView",
    "TurnContextRefView",
    "TurnContextReceiptView",
    "TurnModelRoundView",
    "TurnPlanEventView",
    "TurnPlanOperationView",
    "TurnPlanReceiptView",
    "TurnStatusEventView",
    "TurnToolCallView",
    "turn_context_receipt",
    "turn_exists",
    "turn_model_rounds",
    "turn_plan_receipt",
    "turn_status_ledger",
    "turn_tool_calls",
]


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- context (tab 1) -----------------------------------------------------------------------------


class TurnContextRefView(_View):
    """One pointer the assembler either included in, or excluded from, a layer.

    ``artifact_key``/``artifact_sha256`` name the content-addressed body; ``content_sha256`` is the
    digest of the *compiled* item that was actually rendered into the window, which is why both
    exist. An excluded ref carries neither a token count nor a digest — only the reason code — and
    that asymmetry is a DB CHECK, not a convention.
    """

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


class TurnContextLayerView(_View):
    """One of the seven layers, with its spend against its budget and its pointers."""

    ordinal: int = Field(ge=1, le=7)
    layer: str
    token_budget: int = Field(ge=0)
    token_count: int = Field(ge=0)
    included_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    refs: tuple[TurnContextRefView, ...]


class TurnContextReceiptView(_View):
    """The whole assembly receipt for one turn — ``None`` when the turn assembled no context."""

    context_bundle_id: UUID
    schema_version: str
    policy_version: str
    token_counter_version: str
    aggregate_sha256: str
    assembled_at: AwareDatetime
    layers: tuple[TurnContextLayerView, ...]


# --- rounds (tab 2) ------------------------------------------------------------------------------


class TurnModelRoundView(_View):
    """One governed model call.

    ``requested_model`` is the id the platform asked for and ``answering_model`` the id that
    replied; they differ whenever the gateway's fallback fired, and keeping both is the difference
    between "we called GPT-5.6" and "we asked for GPT-5.6".
    """

    model_call_id: UUID
    sequence: int = Field(ge=1)
    requested_model: str
    answering_model: str | None
    status: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_millicredits: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    error_code: str | None
    started_at: AwareDatetime
    completed_at: AwareDatetime | None


# --- plan (tab 3) --------------------------------------------------------------------------------


class TurnPlanOperationView(_View):
    """One operation validation **admitted** into a plan."""

    node_key: str
    ordinal: int = Field(ge=0)
    operation_id: UUID
    kind: str
    address: str
    parameter_artifact_key: str
    parameter_sha256: str
    estimated_cost_millicents: int = Field(ge=0)
    authority_sha256: str


class TurnPlanEventView(_View):
    """One entry of a plan's append-only lifecycle ledger; ``reason_code`` names a refusal."""

    status: str
    reason_code: str | None
    created_at: AwareDatetime


class TurnPlanReceiptView(_View):
    """One validated plan: what the model authored, what was admitted, and what happened next.

    ``proposal_*`` is the model's authored plan verbatim; ``validated_*`` is what survived
    validation. Serving both addresses (and, at the HTTP surface, both bodies) is how "which step
    did validation drop?" is answered from receipts rather than from a re-derivation here.
    """

    plan_id: UUID
    role: str
    proposal_artifact_key: str
    proposal_sha256: str
    validated_artifact_key: str
    validated_sha256: str
    resource_manifest_sha256: str
    max_parallelism: int = Field(ge=1)
    estimated_cost_millicents: int = Field(ge=0)
    budget_limit_millicents: int = Field(ge=0)
    validated_at: AwareDatetime
    operations: tuple[TurnPlanOperationView, ...]
    events: tuple[TurnPlanEventView, ...]


class TurnStatusEventView(_View):
    """One entry of the turn's own status ledger — where a *rejected* plan's refusal is recorded."""

    status: str
    reason_code: str | None
    created_at: AwareDatetime


# --- tools (tab 4) -------------------------------------------------------------------------------


class TurnToolCallView(_View):
    """One admitted operation and its receipt, if it produced one.

    A row with ``result_artifact_key is None`` is an operation that was admitted and did not
    complete — the honest shape for a governed call that failed after validation.
    """

    plan_id: UUID
    node_key: str
    operation_id: UUID
    kind: str
    address: str
    parameter_artifact_key: str
    parameter_sha256: str
    estimated_cost_millicents: int = Field(ge=0)
    result_artifact_key: str | None
    result_sha256: str | None
    replayed: bool | None
    reference_count: int | None
    completed_at: AwareDatetime | None


# --- reads ---------------------------------------------------------------------------------------


async def turn_exists(
    *,
    workspace_id: str,
    thread_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> bool:
    """Whether this workspace's ``thread_id`` really holds ``turn_id``.

    The scope check every inspector read runs first, and the reason a turn of another thread — or
    another tenant — is *not found* rather than forbidden: a 403 would confirm the turn exists.
    """

    async with conn_factory() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT 1 FROM agent_turn "
                    "WHERE workspace_id = :workspace AND thread_id = :thread AND id = :turn"
                ),
                {"workspace": workspace_id, "thread": thread_id, "turn": turn_id},
            )
        ).first()
    return row is not None


async def turn_context_receipt(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> TurnContextReceiptView | None:
    async with conn_factory() as conn:
        bundle = (
            (
                await conn.execute(
                    text(
                        "SELECT id, schema_version, policy_version, token_counter_version, "
                        "aggregate_sha256, assembled_at FROM agent_context_bundle "
                        "WHERE workspace_id = :workspace AND turn_id = :turn"
                    ),
                    {"workspace": workspace_id, "turn": turn_id},
                )
            )
            .mappings()
            .first()
        )
        if bundle is None:
            return None
        layers = (
            (
                await conn.execute(
                    text(
                        "SELECT ordinal, layer, token_budget, token_count, included_count, "
                        "excluded_count FROM agent_context_layer "
                        "WHERE workspace_id = :workspace AND context_bundle_id = :bundle "
                        "ORDER BY ordinal"
                    ),
                    {"workspace": workspace_id, "bundle": bundle["id"]},
                )
            )
            .mappings()
            .all()
        )
        refs = (
            (
                await conn.execute(
                    text(
                        "SELECT layer_ordinal, disposition, ordinal, ref_kind, artifact_key, "
                        "artifact_sha256, object_type, object_id, object_version, content_sha256, "
                        "materialized_path, token_count, exclusion_reason_code "
                        "FROM agent_context_ref "
                        "WHERE workspace_id = :workspace AND context_bundle_id = :bundle "
                        "ORDER BY layer_ordinal, disposition, ordinal"
                    ),
                    {"workspace": workspace_id, "bundle": bundle["id"]},
                )
            )
            .mappings()
            .all()
        )
    by_layer: dict[int, list[TurnContextRefView]] = {}
    for item in refs:
        by_layer.setdefault(int(item["layer_ordinal"]), []).append(
            TurnContextRefView(
                disposition=item["disposition"],
                ordinal=int(item["ordinal"]),
                ref_kind=item["ref_kind"],
                artifact_key=item["artifact_key"],
                artifact_sha256=item["artifact_sha256"],
                object_type=item["object_type"],
                object_id=item["object_id"],
                object_version=item["object_version"],
                content_sha256=item["content_sha256"],
                materialized_path=item["materialized_path"],
                token_count=item["token_count"],
                exclusion_reason_code=item["exclusion_reason_code"],
            )
        )
    return TurnContextReceiptView(
        context_bundle_id=bundle["id"],
        schema_version=bundle["schema_version"],
        policy_version=bundle["policy_version"],
        token_counter_version=bundle["token_counter_version"],
        aggregate_sha256=bundle["aggregate_sha256"],
        assembled_at=bundle["assembled_at"],
        layers=tuple(
            TurnContextLayerView(
                ordinal=int(layer["ordinal"]),
                layer=layer["layer"],
                token_budget=int(layer["token_budget"]),
                token_count=int(layer["token_count"]),
                included_count=int(layer["included_count"]),
                excluded_count=int(layer["excluded_count"]),
                refs=tuple(by_layer.get(int(layer["ordinal"]), ())),
            )
            for layer in layers
        ),
    )


async def turn_model_rounds(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> tuple[TurnModelRoundView, ...]:
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT id, sequence, requested_model, answering_model, status, "
                        "input_tokens, output_tokens, cost_millicredits, latency_ms, error_code, "
                        "started_at, completed_at FROM agent_model_call "
                        "WHERE workspace_id = :workspace AND turn_id = :turn ORDER BY sequence"
                    ),
                    {"workspace": workspace_id, "turn": turn_id},
                )
            )
            .mappings()
            .all()
        )
    return tuple(
        TurnModelRoundView(
            model_call_id=row["id"],
            sequence=int(row["sequence"]),
            requested_model=row["requested_model"],
            answering_model=row["answering_model"],
            status=row["status"],
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cost_millicredits=int(row["cost_millicredits"]),
            latency_ms=float(row["latency_ms"]),
            error_code=row["error_code"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
        for row in rows
    )


async def _plan_rows(
    conn: AsyncConnection, *, workspace_id: str, turn_id: UUID
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in (
            (
                await conn.execute(
                    text(
                        "SELECT id, role, proposal_artifact_key, proposal_sha256, "
                        "validated_artifact_key, validated_sha256, resource_manifest_sha256, "
                        "max_parallelism, estimated_cost_millicents, budget_limit_millicents, "
                        "validated_at FROM agent_plan "
                        "WHERE workspace_id = :workspace AND turn_id = :turn "
                        "ORDER BY validated_at, id"
                    ),
                    {"workspace": workspace_id, "turn": turn_id},
                )
            )
            .mappings()
            .all()
        )
    ]


async def turn_plan_receipt(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> tuple[TurnPlanReceiptView, ...]:
    """Every plan this turn had validated, oldest first, with its operations and its ledger."""

    async with conn_factory() as conn:
        plans = await _plan_rows(conn, workspace_id=workspace_id, turn_id=turn_id)
        if not plans:
            return ()
        plan_ids = [row["id"] for row in plans]
        operations = (
            (
                await conn.execute(
                    text(
                        "SELECT plan_id, node_key, ordinal, operation_id, kind, address, "
                        "parameter_artifact_key, parameter_sha256, estimated_cost_millicents, "
                        "authority_sha256 FROM agent_plan_operation "
                        "WHERE workspace_id = :workspace "
                        "AND plan_id = ANY(CAST(:plans AS uuid[])) ORDER BY plan_id, ordinal"
                    ),
                    {"workspace": workspace_id, "plans": plan_ids},
                )
            )
            .mappings()
            .all()
        )
        events = (
            (
                await conn.execute(
                    text(
                        "SELECT plan_id, status, reason_code, created_at FROM agent_plan_event "
                        "WHERE workspace_id = :workspace "
                        "AND plan_id = ANY(CAST(:plans AS uuid[])) ORDER BY plan_id, seq"
                    ),
                    {"workspace": workspace_id, "plans": plan_ids},
                )
            )
            .mappings()
            .all()
        )
    operations_by_plan: dict[UUID, list[TurnPlanOperationView]] = {}
    for item in operations:
        operations_by_plan.setdefault(item["plan_id"], []).append(
            TurnPlanOperationView(
                node_key=item["node_key"],
                ordinal=int(item["ordinal"]),
                operation_id=item["operation_id"],
                kind=item["kind"],
                address=item["address"],
                parameter_artifact_key=item["parameter_artifact_key"],
                parameter_sha256=item["parameter_sha256"],
                estimated_cost_millicents=int(item["estimated_cost_millicents"]),
                authority_sha256=item["authority_sha256"],
            )
        )
    events_by_plan: dict[UUID, list[TurnPlanEventView]] = {}
    for item in events:
        events_by_plan.setdefault(item["plan_id"], []).append(
            TurnPlanEventView(
                status=item["status"],
                reason_code=item["reason_code"],
                created_at=item["created_at"],
            )
        )
    return tuple(
        TurnPlanReceiptView(
            plan_id=row["id"],
            role=row["role"],
            proposal_artifact_key=row["proposal_artifact_key"],
            proposal_sha256=row["proposal_sha256"],
            validated_artifact_key=row["validated_artifact_key"],
            validated_sha256=row["validated_sha256"],
            resource_manifest_sha256=row["resource_manifest_sha256"],
            max_parallelism=int(row["max_parallelism"]),
            estimated_cost_millicents=int(row["estimated_cost_millicents"]),
            budget_limit_millicents=int(row["budget_limit_millicents"]),
            validated_at=row["validated_at"],
            operations=tuple(operations_by_plan.get(row["id"], ())),
            events=tuple(events_by_plan.get(row["id"], ())),
        )
        for row in plans
    )


async def turn_status_ledger(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> tuple[TurnStatusEventView, ...]:
    """The turn's append-only status ledger, oldest first."""

    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT status, reason_code, created_at FROM agent_turn_event "
                        "WHERE workspace_id = :workspace AND turn_id = :turn ORDER BY seq"
                    ),
                    {"workspace": workspace_id, "turn": turn_id},
                )
            )
            .mappings()
            .all()
        )
    return tuple(
        TurnStatusEventView(
            status=row["status"],
            reason_code=row["reason_code"],
            created_at=row["created_at"],
        )
        for row in rows
    )


async def turn_tool_calls(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> tuple[TurnToolCallView, ...]:
    """Every governed operation this turn's plans admitted, with its receipt when it produced one.

    A LEFT JOIN, deliberately: an operation with no ``agent_tool_result`` is one that was admitted
    and did not complete, and dropping it would hide precisely the call a developer opened the
    drawer to look at.
    """

    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT o.plan_id, o.node_key, o.operation_id, o.kind, o.address, "
                        "o.parameter_artifact_key, o.parameter_sha256, "
                        "o.estimated_cost_millicents, r.result_artifact_key, r.result_sha256, "
                        "r.replayed, r.reference_count, r.completed_at "
                        "FROM agent_plan_operation o "
                        "JOIN agent_plan p ON p.id = o.plan_id AND p.workspace_id = o.workspace_id "
                        "LEFT JOIN agent_tool_result r ON r.operation_id = o.operation_id "
                        "WHERE o.workspace_id = :workspace AND p.turn_id = :turn "
                        "ORDER BY p.validated_at, p.id, o.ordinal"
                    ),
                    {"workspace": workspace_id, "turn": turn_id},
                )
            )
            .mappings()
            .all()
        )
    return tuple(
        TurnToolCallView(
            plan_id=row["plan_id"],
            node_key=row["node_key"],
            operation_id=row["operation_id"],
            kind=row["kind"],
            address=row["address"],
            parameter_artifact_key=row["parameter_artifact_key"],
            parameter_sha256=row["parameter_sha256"],
            estimated_cost_millicents=int(row["estimated_cost_millicents"]),
            result_artifact_key=row["result_artifact_key"],
            result_sha256=row["result_sha256"],
            replayed=row["replayed"],
            reference_count=(
                None if row["reference_count"] is None else int(row["reference_count"])
            ),
            completed_at=row["completed_at"],
        )
        for row in rows
    )
