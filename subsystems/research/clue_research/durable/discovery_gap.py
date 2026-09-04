"""Durable provider-neutral required-field operations before the D5 discovery seal."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    DiscoveryGapFieldResult,
    DiscoveryGapFieldState,
    DiscoveryGapOperation,
    DiscoveryGapOperationId,
    DiscoveryGapOperationState,
    DiscoveryGapRequest,
    DiscoveryGapSpendOutcome,
    ProjectPhase,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.durable.spend_posture import cap_refusal_is_enforced

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20).
_SITE_GAP_RESERVATION: Final = "discovery_gap_reservation"


class DiscoveryGapRepositoryError(RuntimeError):
    pass


class DiscoveryGapNotFound(DiscoveryGapRepositoryError):
    pass


class DiscoveryGapReplayConflict(DiscoveryGapRepositoryError):
    pass


class DiscoveryGapBudgetExceeded(DiscoveryGapRepositoryError):
    pass


_REQUEST_ADAPTER = TypeAdapter(DiscoveryGapRequest)
_OPERATION_COLUMNS = (
    "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
    "discovery_batch_id, account_id, primary_domain, source_key, provider_api_version, "
    "provider_contract_version, pricing_policy_version, field_policy_version, observation_window, "
    "request_fingerprint, request_json, state::text, spend_outcome::text, request_artifact_key, "
    "response_artifact_key, receipt_artifact_key, provider_request_id, provider_units_reserved, "
    "provider_units_charged, credits_remaining, cost_cents_reserved, cost_cents_charged, "
    "failure_code, started_at, terminal_at, created_at, updated_at"
)
_REQUEST_IDENTITY_COLUMNS = (
    "workspace_id",
    "project_id",
    "project_run_id",
    "icp_key",
    "icp_version",
    "discovery_batch_id",
    "account_id",
    "primary_domain",
    "source_key",
    "provider_api_version",
    "provider_contract_version",
    "pricing_policy_version",
    "field_policy_version",
    "observation_window",
)


def _operation(row: object) -> DiscoveryGapOperation:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    request = _REQUEST_ADAPTER.validate_python(decode_jsonb(data.pop("request_json")))
    for column in _REQUEST_IDENTITY_COLUMNS:
        stored = data.pop(column)
        if stored != getattr(request, column):
            raise DiscoveryGapRepositoryError(
                f"discovery-gap indexed request identity differs at {column}"
            )
    data["operation_id"] = data.pop("id")
    data["request"] = request
    return DiscoveryGapOperation.model_validate(data)


async def find_discovery_gap_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: object,
    account_id: object,
    source_key: str,
    observation_window: str,
) -> DiscoveryGapOperation | None:
    rows = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM discovery_gap_operation "
                "WHERE workspace_id=:workspace_id AND discovery_batch_id=:batch_id "
                "AND account_id=:account_id AND source_key=:source_key "
                "AND observation_window=:window ORDER BY created_at"
            ),
            {
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "account_id": account_id,
                "source_key": source_key,
                "window": observation_window,
            },
        )
    ).all()
    if len(rows) > 1:
        raise DiscoveryGapReplayConflict(
            "multiple discovery-gap operations share one source window"
        )
    return _operation(rows[0]) if rows else None


async def get_discovery_gap_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryGapOperationId,
    for_update: bool = False,
) -> DiscoveryGapOperation | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM discovery_gap_operation "
                "WHERE workspace_id=:workspace_id AND id=:operation_id" + suffix
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def list_discovery_gap_operations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: object,
) -> tuple[DiscoveryGapOperation, ...]:
    rows = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM discovery_gap_operation "
                "WHERE workspace_id=:workspace_id AND discovery_batch_id=:batch_id "
                "ORDER BY account_id, source_key"
            ),
            {"workspace_id": workspace_id, "batch_id": batch_id},
        )
    ).all()
    return tuple(_operation(row) for row in rows)


def _assert_replay(stored: DiscoveryGapOperation, proposed: DiscoveryGapOperation) -> None:
    if (
        stored.request != proposed.request
        or stored.request_artifact_key != proposed.request_artifact_key
        or stored.provider_units_reserved != proposed.provider_units_reserved
        or stored.cost_cents_reserved != proposed.cost_cents_reserved
    ):
        raise DiscoveryGapReplayConflict(
            "discovery-gap fingerprint was reused with different immutable content"
        )


async def reserve_discovery_gap_operation(
    conn: AsyncConnection,
    *,
    operation: DiscoveryGapOperation,
    enforce_budget: bool = True,
) -> tuple[DiscoveryGapOperation, bool]:
    """Reserve one bounded discovery-gap operation.

    ``enforce_budget`` is the FI pilot budget-controls switch. It gates the project-run money
    check **and** — since the 2026-08-20 ruling that our own spend caps are record-only in the
    pilot posture — this operation's two reserved-vs-cap comparisons. Each is still computed and
    announced (:mod:`clue_research.durable.spend_posture`); only the refusal goes inert. The
    ledger's own invariants are untouched in both modes.
    """

    request = operation.request
    if operation.provider_units_reserved > Decimal(
        request.provider_credit_cap
    ) and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_GAP_RESERVATION,
        reason="reserved_units_above_cap",
        amounts={
            "provider_units_reserved": operation.provider_units_reserved,
            "provider_credit_cap": request.provider_credit_cap,
        },
    ):
        raise DiscoveryGapBudgetExceeded("discovery-gap provider cap exceeded")
    if operation.cost_cents_reserved > Decimal(
        request.money_budget_cap_cents
    ) and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_GAP_RESERVATION,
        reason="reserved_cost_above_cap",
        amounts={
            "cost_cents_reserved": operation.cost_cents_reserved,
            "money_budget_cap_cents": request.money_budget_cap_cents,
        },
    ):
        raise DiscoveryGapBudgetExceeded("discovery-gap money cap exceeded")
    existing = await find_discovery_gap_operation(
        conn,
        workspace_id=request.workspace_id,
        batch_id=request.discovery_batch_id,
        account_id=request.account_id,
        source_key=request.source_key,
        observation_window=request.observation_window,
    )
    if existing is not None:
        _assert_replay(existing, operation)
        return existing, False
    try:
        await require_provider_spend_capacity(
            conn,
            project_run_id=request.project_run_id,
            proposed_cents=operation.cost_cents_reserved,
            allowed_phases=frozenset({ProjectPhase.DISCOVERY}),
            enforce_budget=enforce_budget,
        )
    except ProviderSpendGuardError as exc:
        raise DiscoveryGapBudgetExceeded(str(exc)) from exc
    inserted = await conn.execute(
        text(
            "INSERT INTO discovery_gap_operation ("
            "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
            "discovery_batch_id, account_id, primary_domain, source_key, provider_api_version, "
            "provider_contract_version, pricing_policy_version, field_policy_version, "
            "observation_window, request_fingerprint, request_json, state, spend_outcome, "
            "request_artifact_key, provider_units_reserved, cost_cents_reserved) VALUES ("
            ":id, :workspace_id, :project_id, :project_run_id, :icp_key, :icp_version, :batch_id, "
            ":account_id, :domain, :source_key, :api_version, :contract_version, :pricing_version, "
            ":field_version, :window, :fingerprint, CAST(:request_json AS jsonb), "
            "CAST(:state AS discovery_gap_operation_state), "
            "CAST(:spend AS discovery_gap_spend_outcome), :request_key, :reserved, :cost) "
            "ON CONFLICT DO NOTHING RETURNING id"
        ),
        {
            "id": operation.operation_id,
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "icp_key": request.icp_key,
            "icp_version": request.icp_version,
            "batch_id": request.discovery_batch_id,
            "account_id": request.account_id,
            "domain": request.primary_domain,
            "source_key": request.source_key,
            "api_version": request.provider_api_version,
            "contract_version": request.provider_contract_version,
            "pricing_version": request.pricing_policy_version,
            "field_version": request.field_policy_version,
            "window": request.observation_window,
            "fingerprint": operation.request_fingerprint,
            "request_json": request.model_dump_json(),
            "state": operation.state.value,
            "spend": operation.spend_outcome.value,
            "request_key": operation.request_artifact_key,
            "reserved": operation.provider_units_reserved,
            "cost": operation.cost_cents_reserved,
        },
    )
    created = inserted.scalar_one_or_none() is not None
    stored = await find_discovery_gap_operation(
        conn,
        workspace_id=request.workspace_id,
        batch_id=request.discovery_batch_id,
        account_id=request.account_id,
        source_key=request.source_key,
        observation_window=request.observation_window,
    )
    if stored is None:
        raise DiscoveryGapNotFound("reserved discovery-gap operation")
    _assert_replay(stored, operation)
    if not created:
        return stored, False
    for plan in request.fields:
        await conn.execute(
            text(
                "INSERT INTO discovery_gap_field_result ("
                "operation_id, workspace_id, discovery_batch_id, account_id, logical_field_key, "
                "field_key, source_key, expected_value_credits, basis_claim_ids, source_item_ids, "
                "state, reason_code) VALUES ("
                ":operation_id, :workspace_id, :batch_id, :account_id, :logical_key, :field_key, "
                ":source_key, :expected, CAST(:basis AS jsonb), CAST(:items AS jsonb), 'pending', "
                "'awaiting_provider_snapshot')"
            ),
            {
                "operation_id": stored.operation_id,
                "workspace_id": request.workspace_id,
                "batch_id": request.discovery_batch_id,
                "account_id": request.account_id,
                "logical_key": str(plan.logical_field_key),
                "field_key": str(plan.field_key),
                "source_key": plan.source_key,
                "expected": plan.expected_value_credits,
                "basis": serialize_value_json([str(value) for value in plan.basis_claim_ids]),
                "items": serialize_value_json([str(value) for value in plan.source_item_ids]),
            },
        )
    await conn.execute(
        text(
            "UPDATE discovery_batch SET provider_units_reserved=provider_units_reserved+:units, "
            "updated_at=now() WHERE id=:batch_id AND workspace_id=:workspace_id"
        ),
        {
            "units": operation.provider_units_reserved,
            "batch_id": request.discovery_batch_id,
            "workspace_id": request.workspace_id,
        },
    )
    return stored, True


async def claim_discovery_gap_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryGapOperationId,
) -> DiscoveryGapOperation | None:
    row = (
        await conn.execute(
            text(
                "UPDATE discovery_gap_operation SET state='dispatching', "
                "started_at=COALESCE(started_at, now()), updated_at=now(), failure_code=NULL "
                "WHERE workspace_id=:workspace_id AND id=:operation_id "
                "AND state IN ('planned', 'failed_retryable') "
                "AND spend_outcome IN ('not_dispatched', 'not_charged') "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def list_discovery_gap_field_results(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryGapOperationId,
) -> tuple[DiscoveryGapFieldResult, ...]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT operation_id, account_id, logical_field_key, field_key, source_key, "
                    "state::text, provider_claim_id, current_claim_id, conflicting_claim_ids, "
                    "reason_code, updated_at FROM discovery_gap_field_result "
                    "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                    "ORDER BY logical_field_key"
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .all()
    )
    values: list[DiscoveryGapFieldResult] = []
    for row in rows:
        data = dict(row)
        data["conflicting_claim_ids"] = tuple(decode_jsonb(data["conflicting_claim_ids"]))
        values.append(DiscoveryGapFieldResult.model_validate(data))
    return tuple(values)


async def put_discovery_gap_field_result(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    result: DiscoveryGapFieldResult,
) -> DiscoveryGapFieldResult:
    row = (
        (
            await conn.execute(
                text(
                    "UPDATE discovery_gap_field_result SET "
                    "state=CAST(:state AS discovery_gap_field_state), "
                    "provider_claim_id=:provider_claim_id, current_claim_id=:current_claim_id, "
                    "conflicting_claim_ids=CAST(:conflicts AS jsonb), reason_code=:reason, "
                    "updated_at=now() WHERE workspace_id=:workspace_id "
                    "AND operation_id=:operation_id AND account_id=:account_id "
                    "AND logical_field_key=:logical_key AND field_key=:field_key "
                    "RETURNING operation_id, account_id, logical_field_key, field_key, source_key, "
                    "state::text, provider_claim_id, current_claim_id, conflicting_claim_ids, "
                    "reason_code, updated_at"
                ),
                {
                    "state": result.state.value,
                    "provider_claim_id": result.provider_claim_id,
                    "current_claim_id": result.current_claim_id,
                    "conflicts": serialize_value_json(
                        [str(value) for value in result.conflicting_claim_ids]
                    ),
                    "reason": result.reason_code,
                    "workspace_id": workspace_id,
                    "operation_id": result.operation_id,
                    "account_id": result.account_id,
                    "logical_key": str(result.logical_field_key),
                    "field_key": str(result.field_key),
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DiscoveryGapNotFound("discovery-gap field result")
    data = dict(row)
    data["conflicting_claim_ids"] = tuple(decode_jsonb(data["conflicting_claim_ids"]))
    return DiscoveryGapFieldResult.model_validate(data)


async def update_discovery_gap_operation(
    conn: AsyncConnection,
    *,
    operation: DiscoveryGapOperation,
) -> DiscoveryGapOperation:
    current = await get_discovery_gap_operation(
        conn,
        workspace_id=operation.request.workspace_id,
        operation_id=operation.operation_id,
        for_update=True,
    )
    if current is None:
        raise DiscoveryGapNotFound("discovery-gap operation")
    if current.terminal_at is not None:
        if current == operation:
            return current
        raise DiscoveryGapReplayConflict("terminal discovery-gap operation is immutable")
    if current.request != operation.request:
        raise DiscoveryGapReplayConflict("discovery-gap request changed during update")
    if operation.state is DiscoveryGapOperationState.SUCCEEDED:
        fields = await list_discovery_gap_field_results(
            conn,
            workspace_id=operation.request.workspace_id,
            operation_id=operation.operation_id,
        )
        if not fields or any(
            item.state
            in {
                DiscoveryGapFieldState.PENDING,
                DiscoveryGapFieldState.BLOCKED_BY_POLICY,
                DiscoveryGapFieldState.FAILED_TERMINAL,
            }
            for item in fields
        ):
            raise DiscoveryGapReplayConflict(
                "discovery-gap success requires terminal provider field outcomes"
            )
    terminal_settlement = operation.terminal_at is not None and operation.spend_outcome in {
        DiscoveryGapSpendOutcome.CHARGED,
        DiscoveryGapSpendOutcome.UNKNOWN,
    }
    if terminal_settlement:
        run_update = await conn.execute(
            text(
                "UPDATE project_run SET spent_cents=spent_cents+:cost, updated_at=now() "
                "WHERE id=:run_id AND workspace_id=:workspace_id"
            ),
            {
                "cost": operation.cost_cents_charged,
                "run_id": operation.request.project_run_id,
                "workspace_id": operation.request.workspace_id,
            },
        )
        batch_update = await conn.execute(
            text(
                "UPDATE discovery_batch SET "
                "provider_units_charged=provider_units_charged+:units, "
                "cost_cents_charged=cost_cents_charged+:cost, updated_at=now() "
                "WHERE id=:batch_id AND workspace_id=:workspace_id"
            ),
            {
                "units": operation.provider_units_charged,
                "cost": operation.cost_cents_charged,
                "batch_id": operation.request.discovery_batch_id,
                "workspace_id": operation.request.workspace_id,
            },
        )
        if run_update.rowcount != 1 or batch_update.rowcount != 1:
            raise DiscoveryGapReplayConflict("discovery-gap settlement lost run/batch lineage")
    row = (
        await conn.execute(
            text(
                "UPDATE discovery_gap_operation SET "
                "state=CAST(:state AS discovery_gap_operation_state), "
                "spend_outcome=CAST(:spend AS discovery_gap_spend_outcome), "
                "response_artifact_key=:response_key, receipt_artifact_key=:receipt_key, "
                "provider_request_id=:provider_request_id, provider_units_charged=:charged, "
                "credits_remaining=:remaining, cost_cents_charged=:cost, failure_code=:failure, "
                "started_at=:started_at, terminal_at=:terminal_at, updated_at=now() "
                "WHERE workspace_id=:workspace_id AND id=:operation_id "
                "AND request_fingerprint=:fingerprint "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {
                "state": operation.state.value,
                "spend": operation.spend_outcome.value,
                "response_key": operation.response_artifact_key,
                "receipt_key": operation.receipt_artifact_key,
                "provider_request_id": operation.provider_request_id,
                "charged": operation.provider_units_charged,
                "remaining": operation.credits_remaining,
                "cost": operation.cost_cents_charged,
                "failure": operation.failure_code,
                "started_at": operation.started_at,
                "terminal_at": operation.terminal_at,
                "workspace_id": operation.request.workspace_id,
                "operation_id": operation.operation_id,
                "fingerprint": operation.request_fingerprint,
            },
        )
    ).one_or_none()
    if row is None:
        raise DiscoveryGapReplayConflict("discovery-gap operation update lost request lineage")
    return _operation(row)


def terminal_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "DiscoveryGapBudgetExceeded",
    "DiscoveryGapNotFound",
    "DiscoveryGapReplayConflict",
    "DiscoveryGapRepositoryError",
    "claim_discovery_gap_operation",
    "find_discovery_gap_operation",
    "get_discovery_gap_operation",
    "list_discovery_gap_field_results",
    "list_discovery_gap_operations",
    "put_discovery_gap_field_result",
    "reserve_discovery_gap_operation",
    "terminal_now",
    "update_discovery_gap_operation",
]
