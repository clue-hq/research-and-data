"""Generic durable ledger for bounded external-research acquisition (M8B E1).

Provider adapters compile and execute requests; later slices materialize claims.  This module owns
the state between those boundaries: exact immutable request lineage, shared-budget reservation,
one dispatch lease, terminal spend classification, immutable snapshots/results/receipts, and
fresh-process replay.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityId,
    ExternalResearchAcquisitionRequest,
    ExternalResearchOperationId,
    ExternalResearchOperationState,
    ExternalResearchReconciliationState,
    ExternalResearchSnapshotId,
    ExternalResearchSnapshotRef,
    ExternalResearchSpendOutcome,
    ProjectPhase,
    UtcDatetime,
    new_external_research_operation_id,
    new_external_research_snapshot_id,
)
from clue_research.durable.provider_spend import require_provider_spend_capacity


class ExternalResearchLedgerError(RuntimeError):
    """Base error for invalid durable acquisition transitions."""


class ExternalResearchNotFound(ExternalResearchLedgerError):
    """A requested operation or snapshot does not exist in this workspace."""


class ExternalResearchReplayConflict(ExternalResearchLedgerError):
    """One fingerprint was reused with different immutable request content."""


class ExternalResearchTransitionConflict(ExternalResearchLedgerError):
    """A caller attempted a transition from the wrong durable state."""


class ExternalResearchDispatchDecision(StrEnum):
    ACQUIRED = "acquired"
    JOIN_ACTIVE = "join_active"
    READY = "ready"
    TERMINAL = "terminal"
    QUARANTINED_STALE_DISPATCH = "quarantined_stale_dispatch"


class ExternalResearchOperationRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: ExternalResearchOperationId
    workspace_id: str
    project_id: str
    project_run_id: UUID
    account_id: EntityId
    source_key: str
    observation_window: str
    freshness_seconds: int
    request_fingerprint: str
    wire_request_sha256: str
    state: ExternalResearchOperationState
    spend_outcome: ExternalResearchSpendOutcome
    request_artifact_key: str
    cost_cents_reserved: Decimal
    provider_request_id: str | None = None
    dispatch_lease_expires_at: UtcDatetime | None = None
    fresh_until: UtcDatetime | None = None
    failure_code: str | None = None
    terminal_at: UtcDatetime | None = None


class ExternalResearchDispatchClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: ExternalResearchDispatchDecision
    operation: ExternalResearchOperationRow
    attempt_ordinal: int | None = None


class ExternalResearchResultArtifactInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_key: str
    source_url: str
    source_title: str


_OPERATION_COLUMNS = (
    "id AS operation_id, workspace_id, project_id, project_run_id, account_id, source_key, "
    "observation_window, freshness_seconds, request_fingerprint, wire_request_sha256, state::text, "
    "spend_outcome::text, request_artifact_key, cost_cents_reserved, provider_request_id, "
    "dispatch_lease_expires_at, fresh_until, failure_code, terminal_at"
)


def _operation(row: object) -> ExternalResearchOperationRow:
    return ExternalResearchOperationRow.model_validate(row)


async def find_external_research_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    source_key: str,
    request_fingerprint: str,
    observation_window: str,
    for_update: bool = False,
) -> ExternalResearchOperationRow | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM external_research_operation "
                    "WHERE workspace_id=:workspace_id AND source_key=:source_key "
                    "AND request_fingerprint=:request_fingerprint "
                    f"AND observation_window=:observation_window{suffix}"
                ),
                {
                    "workspace_id": workspace_id,
                    "source_key": source_key,
                    "request_fingerprint": request_fingerprint,
                    "observation_window": observation_window,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _operation(row)


async def get_external_research_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    for_update: bool = False,
) -> ExternalResearchOperationRow:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM external_research_operation "
                    f"WHERE workspace_id=:workspace_id AND id=:operation_id{suffix}"
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ExternalResearchNotFound(f"external research operation {operation_id}")
    return _operation(row)


async def find_fresh_external_research_operation(
    conn: AsyncConnection,
    *,
    request: ExternalResearchAcquisitionRequest,
    now: datetime,
) -> ExternalResearchOperationRow | None:
    """Find an exact-wire, exact-directive ready snapshot still reusable under its policy."""

    pin = request.research_directive
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM external_research_operation "
                    "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                    "AND account_id=:account_id AND source_key=:source_key "
                    "AND icp_key=:icp_key AND icp_version=:icp_version "
                    "AND research_directive_id=:directive_id "
                    "AND research_directive_version=:directive_version "
                    "AND research_directive_sha256=:directive_sha "
                    "AND research_override_id IS NOT DISTINCT FROM :override_id "
                    "AND research_override_sha256 IS NOT DISTINCT FROM :override_sha "
                    "AND freshness_policy_ref=:freshness_policy_ref "
                    "AND freshness_seconds=:freshness_seconds "
                    "AND wire_request_sha256=:wire_request_sha256 "
                    "AND state='ready' AND fresh_until > :now "
                    "ORDER BY fresh_until DESC, created_at DESC LIMIT 1"
                ),
                {
                    "workspace_id": request.workspace_id,
                    "project_id": request.project_id,
                    "account_id": request.account_id,
                    "source_key": request.source_key,
                    "icp_key": request.icp_key,
                    "icp_version": request.icp_version,
                    "directive_id": pin.directive_id,
                    "directive_version": pin.version,
                    "directive_sha": pin.canonical_json_sha256,
                    "override_id": pin.override_id,
                    "override_sha": pin.override_sha256,
                    "freshness_policy_ref": request.freshness_policy_ref,
                    "freshness_seconds": request.freshness_seconds,
                    "wire_request_sha256": request.wire_request_sha256,
                    "now": now,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _operation(row)


async def reserve_external_research_operation(
    conn: AsyncConnection,
    *,
    request: ExternalResearchAcquisitionRequest,
    request_artifact_key: str,
) -> tuple[ExternalResearchOperationRow, bool]:
    """Reserve once under the shared project-run lock; exact replay consumes no new capacity."""

    existing = await find_external_research_operation(
        conn,
        workspace_id=request.workspace_id,
        source_key=request.source_key,
        request_fingerprint=request.request_fingerprint,
        observation_window=request.observation_window,
    )
    if existing is not None:
        _assert_replay(existing, request, request_artifact_key)
        return existing, False
    await require_provider_spend_capacity(
        conn,
        project_run_id=request.project_run_id,
        proposed_cents=request.cost_cents_reserved,
        allowed_phases=frozenset({ProjectPhase.DEEP}),
    )
    existing = await find_external_research_operation(
        conn,
        workspace_id=request.workspace_id,
        source_key=request.source_key,
        request_fingerprint=request.request_fingerprint,
        observation_window=request.observation_window,
        for_update=True,
    )
    if existing is not None:
        _assert_replay(existing, request, request_artifact_key)
        return existing, False
    operation_id = new_external_research_operation_id()
    pin = request.research_directive
    await conn.execute(
        text(
            """
            INSERT INTO external_research_operation (
                id, workspace_id, project_id, project_run_id, subject_kind, account_id,
                contact_id, icp_key, icp_version, research_directive_id,
                research_directive_version, research_directive_sha256, research_override_id,
                research_override_sha256, source_key, observation_window, freshness_policy_ref,
                freshness_seconds, request_fingerprint, wire_request_sha256, request_json,
                state, spend_outcome,
                request_artifact_key, cost_cents_reserved
            ) VALUES (
                :id, :workspace_id, :project_id, :project_run_id,
                CAST(:subject_kind AS external_research_subject_kind), :account_id, :contact_id,
                :icp_key, :icp_version, :directive_id, :directive_version, :directive_sha,
                :override_id, :override_sha, :source_key, :observation_window,
                :freshness_policy_ref, :freshness_seconds, :request_fingerprint,
                :wire_request_sha256,
                CAST(:request_json AS jsonb), 'planned', 'not_dispatched',
                :request_artifact_key, :reserved
            )
            """
        ),
        {
            "id": operation_id,
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "subject_kind": request.subject_kind.value,
            "account_id": request.account_id,
            "contact_id": request.contact_id,
            "icp_key": request.icp_key,
            "icp_version": request.icp_version,
            "directive_id": pin.directive_id,
            "directive_version": pin.version,
            "directive_sha": pin.canonical_json_sha256,
            "override_id": pin.override_id,
            "override_sha": pin.override_sha256,
            "source_key": request.source_key,
            "observation_window": request.observation_window,
            "freshness_policy_ref": request.freshness_policy_ref,
            "freshness_seconds": request.freshness_seconds,
            "request_fingerprint": request.request_fingerprint,
            "wire_request_sha256": request.wire_request_sha256,
            "request_json": request.model_dump_json(),
            "request_artifact_key": request_artifact_key,
            "reserved": request.cost_cents_reserved,
        },
    )
    return (
        await get_external_research_operation(
            conn, workspace_id=request.workspace_id, operation_id=operation_id
        ),
        True,
    )


def _assert_replay(
    stored: ExternalResearchOperationRow,
    request: ExternalResearchAcquisitionRequest,
    request_artifact_key: str,
) -> None:
    if (
        stored.account_id != request.account_id
        or stored.project_run_id != request.project_run_id
        or stored.wire_request_sha256 != request.wire_request_sha256
        or stored.request_artifact_key != request_artifact_key
        or stored.cost_cents_reserved != request.cost_cents_reserved
    ):
        raise ExternalResearchReplayConflict(
            "external research fingerprint reused with different immutable content"
        )


async def claim_external_research_dispatch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    now: datetime,
    lease_expires_at: datetime,
) -> ExternalResearchDispatchClaim:
    operation = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id, for_update=True
    )
    if operation.state is ExternalResearchOperationState.READY:
        return ExternalResearchDispatchClaim(
            decision=ExternalResearchDispatchDecision.READY, operation=operation
        )
    if operation.state in {
        ExternalResearchOperationState.FAILED_TERMINAL,
        ExternalResearchOperationState.SPEND_OUTCOME_UNKNOWN,
        ExternalResearchOperationState.CANCELLED,
    }:
        return ExternalResearchDispatchClaim(
            decision=ExternalResearchDispatchDecision.TERMINAL, operation=operation
        )
    if operation.state is ExternalResearchOperationState.DISPATCHING:
        if (
            operation.dispatch_lease_expires_at is not None
            and operation.dispatch_lease_expires_at > now
        ):
            return ExternalResearchDispatchClaim(
                decision=ExternalResearchDispatchDecision.JOIN_ACTIVE, operation=operation
            )
        await _mark_unknown_sql(
            conn,
            operation=operation,
            now=now,
            failure_code="dispatch_lease_expired",
            failure_detail="dispatch ownership expired before a durable provider outcome",
        )
        quarantined = await get_external_research_operation(
            conn, workspace_id=workspace_id, operation_id=operation_id
        )
        return ExternalResearchDispatchClaim(
            decision=ExternalResearchDispatchDecision.QUARANTINED_STALE_DISPATCH,
            operation=quarantined,
        )
    ordinal = int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(max(ordinal), -1) + 1 FROM external_research_attempt "
                    "WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation_id},
            )
        ).scalar_one()
    )
    await conn.execute(
        text(
            "UPDATE external_research_operation SET state='dispatching', "
            "dispatch_lease_expires_at=:lease, started_at=COALESCE(started_at, :now), "
            "updated_at=:now WHERE id=:operation_id"
        ),
        {"operation_id": operation_id, "lease": lease_expires_at, "now": now},
    )
    await conn.execute(
        text(
            "INSERT INTO external_research_attempt ("
            "operation_id, workspace_id, ordinal, state, request_artifact_key, "
            "dispatch_lease_expires_at, dispatched_at) VALUES ("
            ":operation_id, :workspace_id, :ordinal, 'dispatching', :request_key, :lease, :now)"
        ),
        {
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "ordinal": ordinal,
            "request_key": operation.request_artifact_key,
            "lease": lease_expires_at,
            "now": now,
        },
    )
    claimed = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )
    return ExternalResearchDispatchClaim(
        decision=ExternalResearchDispatchDecision.ACQUIRED,
        operation=claimed,
        attempt_ordinal=ordinal,
    )


async def complete_external_research_success(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    attempt_ordinal: int,
    response_artifact_key: str,
    normalization_artifact_key: str,
    provider_request_id: str,
    provider_reported_cost_cents: Decimal,
    all_null: bool,
    fresh_until: datetime,
    result_artifacts: tuple[ExternalResearchResultArtifactInput, ...],
    receipt_artifact_key: str,
    now: datetime,
) -> ExternalResearchSnapshotRef:
    operation = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id, for_update=True
    )
    if operation.state is not ExternalResearchOperationState.DISPATCHING:
        raise ExternalResearchTransitionConflict(
            f"cannot settle external research from {operation.state.value}"
        )
    if provider_reported_cost_cents > operation.cost_cents_reserved:
        await _mark_unknown_sql(
            conn,
            operation=operation,
            now=now,
            failure_code="provider_cost_exceeds_reservation",
            failure_detail="provider-reported cost exceeded the authorized reservation",
        )
        raise ExternalResearchTransitionConflict("provider-reported cost exceeds reservation")
    snapshot_id = new_external_research_snapshot_id()
    await conn.execute(
        text(
            "UPDATE external_research_attempt SET state='responded', "
            "response_artifact_key=:response_key, provider_request_id=:provider_request_id, "
            "dispatch_lease_expires_at=NULL, completed_at=:now "
            "WHERE operation_id=:operation_id AND ordinal=:ordinal AND state='dispatching'"
        ),
        {
            "operation_id": operation_id,
            "ordinal": attempt_ordinal,
            "response_key": response_artifact_key,
            "provider_request_id": provider_request_id,
            "now": now,
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO external_research_snapshot (
                id, operation_id, workspace_id, account_id, source_key, request_fingerprint,
                request_artifact_key, response_artifact_key, normalization_artifact_key,
                provider_request_id, provider_reported_cost_cents, all_null, fresh_until
            ) VALUES (
                :id, :operation_id, :workspace_id, :account_id, :source_key,
                :request_fingerprint, :request_key, :response_key, :normalization_key,
                :provider_request_id, :reported_cost, :all_null, :fresh_until
            )
            """
        ),
        {
            "id": snapshot_id,
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "account_id": operation.account_id,
            "source_key": operation.source_key,
            "request_fingerprint": operation.request_fingerprint,
            "request_key": operation.request_artifact_key,
            "response_key": response_artifact_key,
            "normalization_key": normalization_artifact_key,
            "provider_request_id": provider_request_id,
            "reported_cost": provider_reported_cost_cents,
            "all_null": all_null,
            "fresh_until": fresh_until,
        },
    )
    for ordinal, result in enumerate(result_artifacts):
        await conn.execute(
            text(
                "INSERT INTO external_research_result_artifact ("
                "snapshot_id, workspace_id, ordinal, artifact_key, source_url, source_title) "
                "VALUES (:snapshot_id, :workspace_id, :ordinal, :artifact_key, :source_url, "
                ":source_title)"
            ),
            {
                "snapshot_id": snapshot_id,
                "workspace_id": workspace_id,
                "ordinal": ordinal,
                "artifact_key": result.artifact_key,
                "source_url": result.source_url,
                "source_title": result.source_title,
            },
        )
    await conn.execute(
        text(
            """
            INSERT INTO external_research_receipt (
                id, operation_id, workspace_id, source_key, provider_request_id,
                cost_cents_reserved, provider_reported_cost_cents, settled_cost_cents,
                reconciliation_state, receipt_artifact_key
            ) VALUES (
                :id, :operation_id, :workspace_id, :source_key, :provider_request_id,
                :reserved, :reported, :settled, CAST(:reconciliation AS
                external_research_reconciliation_state), :receipt_key
            )
            """
        ),
        {
            "id": uuid4(),
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "source_key": operation.source_key,
            "provider_request_id": provider_request_id,
            "reserved": operation.cost_cents_reserved,
            "reported": provider_reported_cost_cents,
            "settled": provider_reported_cost_cents,
            "reconciliation": ExternalResearchReconciliationState.PENDING_PROVIDER_BILLING.value,
            "receipt_key": receipt_artifact_key,
        },
    )
    await conn.execute(
        text("UPDATE project_run SET spent_cents=spent_cents+:cost WHERE id=:project_run_id"),
        {"project_run_id": operation.project_run_id, "cost": provider_reported_cost_cents},
    )
    await conn.execute(
        text(
            "UPDATE external_research_operation SET state='ready', "
            "spend_outcome='provider_reported', provider_request_id=:provider_request_id, "
            "dispatch_lease_expires_at=NULL, fresh_until=:fresh_until, terminal_at=:now, "
            "updated_at=:now WHERE id=:operation_id"
        ),
        {
            "operation_id": operation_id,
            "provider_request_id": provider_request_id,
            "fresh_until": fresh_until,
            "now": now,
        },
    )
    return await get_external_research_snapshot(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )


async def complete_external_research_pre_dispatch_failure(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    attempt_ordinal: int,
    failure_code: str,
    failure_detail: str,
    now: datetime,
    dispatched: bool = False,
) -> ExternalResearchOperationRow:
    operation = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id, for_update=True
    )
    if operation.state is not ExternalResearchOperationState.DISPATCHING:
        raise ExternalResearchTransitionConflict("pre-dispatch failure requires dispatch ownership")
    attempt_state = "failed_terminal" if dispatched else "failed_pre_dispatch"
    await conn.execute(
        text(
            "UPDATE external_research_attempt SET state=CAST(:state AS "
            "external_research_attempt_state), "
            "failure_code=:failure_code, failure_detail=:failure_detail, "
            "dispatch_lease_expires_at=NULL, "
            "dispatched_at=CASE WHEN :dispatched THEN dispatched_at ELSE NULL END, "
            "completed_at=:now "
            "WHERE operation_id=:operation_id AND ordinal=:ordinal"
        ),
        {
            "operation_id": operation_id,
            "ordinal": attempt_ordinal,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "now": now,
            "state": attempt_state,
            "dispatched": dispatched,
        },
    )
    await conn.execute(
        text(
            "UPDATE external_research_operation SET state='failed_terminal', "
            "spend_outcome='not_charged', dispatch_lease_expires_at=NULL, "
            "failure_code=:failure_code, failure_detail=:failure_detail, terminal_at=:now, "
            "updated_at=:now WHERE id=:operation_id"
        ),
        {
            "operation_id": operation_id,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "now": now,
        },
    )
    return await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )


async def mark_external_research_spend_unknown(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    failure_code: str,
    failure_detail: str,
    now: datetime,
) -> ExternalResearchOperationRow:
    operation = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id, for_update=True
    )
    if operation.state is not ExternalResearchOperationState.DISPATCHING:
        if operation.state is ExternalResearchOperationState.SPEND_OUTCOME_UNKNOWN:
            return operation
        raise ExternalResearchTransitionConflict("spend ambiguity requires a dispatching operation")
    await _mark_unknown_sql(
        conn,
        operation=operation,
        now=now,
        failure_code=failure_code,
        failure_detail=failure_detail,
    )
    return await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )


async def _mark_unknown_sql(
    conn: AsyncConnection,
    *,
    operation: ExternalResearchOperationRow,
    now: datetime,
    failure_code: str,
    failure_detail: str,
) -> None:
    await conn.execute(
        text(
            "UPDATE external_research_attempt SET state='spend_outcome_unknown', "
            "failure_code=:failure_code, failure_detail=:failure_detail, "
            "dispatch_lease_expires_at=NULL, completed_at=:now "
            "WHERE operation_id=:operation_id AND state='dispatching'"
        ),
        {
            "operation_id": operation.operation_id,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "now": now,
        },
    )
    await conn.execute(
        text(
            "UPDATE external_research_operation SET state='spend_outcome_unknown', "
            "spend_outcome='unknown', dispatch_lease_expires_at=NULL, "
            "failure_code=:failure_code, failure_detail=:failure_detail, terminal_at=:now, "
            "updated_at=:now WHERE id=:operation_id"
        ),
        {
            "operation_id": operation.operation_id,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "now": now,
        },
    )


async def get_external_research_snapshot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
) -> ExternalResearchSnapshotRef:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT id AS snapshot_id, operation_id, workspace_id, account_id, "
                    "source_key, request_fingerprint, request_artifact_key, "
                    "response_artifact_key, normalization_artifact_key, provider_request_id, "
                    "provider_reported_cost_cents, all_null, fresh_until "
                    "FROM external_research_snapshot WHERE workspace_id=:workspace_id "
                    "AND operation_id=:operation_id"
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ExternalResearchNotFound(f"external research snapshot for {operation_id}")
    return ExternalResearchSnapshotRef.model_validate(row)


async def list_external_research_result_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    snapshot_id: ExternalResearchSnapshotId,
) -> tuple[ExternalResearchResultArtifactInput, ...]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT artifact_key, source_url, source_title "
                    "FROM external_research_result_artifact WHERE workspace_id=:workspace_id "
                    "AND snapshot_id=:snapshot_id ORDER BY ordinal"
                ),
                {"workspace_id": workspace_id, "snapshot_id": snapshot_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(ExternalResearchResultArtifactInput.model_validate(row) for row in rows)


__all__ = [
    "ExternalResearchDispatchClaim",
    "ExternalResearchDispatchDecision",
    "ExternalResearchLedgerError",
    "ExternalResearchNotFound",
    "ExternalResearchOperationRow",
    "ExternalResearchReplayConflict",
    "ExternalResearchResultArtifactInput",
    "ExternalResearchTransitionConflict",
    "claim_external_research_dispatch",
    "complete_external_research_pre_dispatch_failure",
    "complete_external_research_success",
    "find_fresh_external_research_operation",
    "find_external_research_operation",
    "get_external_research_operation",
    "get_external_research_snapshot",
    "list_external_research_result_artifacts",
    "mark_external_research_spend_unknown",
    "reserve_external_research_operation",
]
