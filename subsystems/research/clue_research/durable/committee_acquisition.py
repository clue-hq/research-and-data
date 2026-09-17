"""PostgreSQL repository for bounded, asynchronous committee acquisition (M6A S2B)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CommitteeAcquisitionAttempt,
    CommitteeAcquisitionOperation,
    CommitteeAcquisitionOperationId,
    CommitteeAcquisitionRequest,
    CommitteeAcquisitionSnapshot,
    CommitteeAcquisitionState,
    CommitteeAttemptKind,
    CommitteeSnapshotState,
    ProjectPhase,
    ProjectRunId,
)
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.durable.spend_posture import cap_refusal_is_enforced

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20).
_SITE_COMMITTEE_RESERVATION: Final = "sumble_committee_reservation"


class CommitteeAcquisitionRepositoryError(RuntimeError):
    pass


class CommitteeAcquisitionNotFound(CommitteeAcquisitionRepositoryError):
    pass


class CommitteeAcquisitionReplayConflict(CommitteeAcquisitionRepositoryError):
    pass


class CommitteeAcquisitionBudgetExceeded(CommitteeAcquisitionRepositoryError):
    pass


_OPERATION_COLUMNS = (
    "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
    "discovery_batch_id, discovery_seal_sha256, account_id, tier_claim_id, "
    "committee_plan_ref, research_direction_ref, organization_identity_ref, "
    "provider_organization_id, "
    "provider_api_version, provider_contract_version, pricing_policy_version, "
    "committee_policy_version, observation_window, request_fingerprint, request_json, "
    "state::text, spend_outcome::text, input_artifact_key, receipt_manifest_key, "
    "provider_units_reserved, provider_units_charged, cost_cents_reserved, "
    "cost_cents_charged, next_poll_at, failure_code, started_at, terminal_at, "
    "created_at, updated_at"
)
_SNAPSHOT_COLUMNS = (
    "operation_id, workspace_id, account_id, source_key, request_fingerprint, state::text, "
    "spend_outcome::text, request_artifact_key, response_artifact_key, "
    "provider_operation_id, provider_status, provider_units_reserved, "
    "provider_units_charged, credits_remaining, cost_cents_charged, failure_code, "
    "created_at, updated_at"
)
_ATTEMPT_COLUMNS = (
    "operation_id, workspace_id, ordinal, source_key, kind::text, state::text, "
    "request_artifact_key, response_artifact_key, provider_operation_id, provider_status, "
    "provider_units_charged, credits_remaining, failure_code, dispatched_at, completed_at"
)


def _operation(row: object) -> CommitteeAcquisitionOperation:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    request = CommitteeAcquisitionRequest.model_validate(data.pop("request_json"))
    for field in (
        "workspace_id",
        "project_id",
        "project_run_id",
        "icp_key",
        "icp_version",
        "discovery_batch_id",
        "discovery_seal_sha256",
        "account_id",
        "tier_claim_id",
        "committee_plan_ref",
        "research_direction_ref",
        "organization_identity_ref",
        "provider_organization_id",
        "provider_api_version",
        "provider_contract_version",
        "pricing_policy_version",
        "committee_policy_version",
        "observation_window",
    ):
        data.pop(field)
    data["operation_id"] = data.pop("id")
    data["request"] = request
    return CommitteeAcquisitionOperation.model_validate(data)


def _snapshot(row: object) -> CommitteeAcquisitionSnapshot:
    return CommitteeAcquisitionSnapshot.model_validate(dict(row._mapping))  # type: ignore[attr-defined]


def _attempt(row: object) -> CommitteeAcquisitionAttempt:
    return CommitteeAcquisitionAttempt.model_validate(dict(row._mapping))  # type: ignore[attr-defined]


async def find_committee_acquisition_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: object,
    request_fingerprint: str,
    observation_window: str,
) -> CommitteeAcquisitionOperation | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM committee_acquisition_operation "
                "WHERE workspace_id=:workspace_id AND account_id=:account_id "
                "AND request_fingerprint=:fingerprint AND observation_window=:window"
            ),
            {
                "workspace_id": workspace_id,
                "account_id": account_id,
                "fingerprint": request_fingerprint,
                "window": observation_window,
            },
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def get_committee_acquisition_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: CommitteeAcquisitionOperationId,
    for_update: bool = False,
) -> CommitteeAcquisitionOperation | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM committee_acquisition_operation "
                "WHERE workspace_id=:workspace_id AND id=:operation_id" + suffix
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def reserve_committee_acquisition(
    conn: AsyncConnection,
    *,
    operation: CommitteeAcquisitionOperation,
    snapshots: tuple[CommitteeAcquisitionSnapshot, CommitteeAcquisitionSnapshot],
    enforce_budget: bool = True,
) -> tuple[CommitteeAcquisitionOperation, bool]:
    """Reserve one bounded committee-acquisition operation.

    ``enforce_budget`` is the FI pilot budget-controls switch. It gates the project-run money check
    **and** — since the 2026-08-20 ruling that our own spend caps are record-only in the pilot
    posture — the two reserved-vs-cap comparisons below, which are pure arithmetic against numbers
    we chose. Both are still computed and announced
    (:mod:`clue_research.durable.spend_posture`); only the refusal goes inert. The reservation
    itself is the wire plan's own bounded maximum, so the ledger CHECK
    ``charged <= reserved`` keeps holding in both modes without anything being relaxed.
    """

    request = operation.request
    if operation.provider_units_reserved > Decimal(
        request.provider_credit_cap
    ) and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_COMMITTEE_RESERVATION,
        reason="reserved_units_above_cap",
        amounts={
            "provider_units_reserved": operation.provider_units_reserved,
            "provider_credit_cap": request.provider_credit_cap,
        },
    ):
        raise CommitteeAcquisitionBudgetExceeded("committee provider cap exceeded")
    if operation.cost_cents_reserved > request.money_budget_cap_cents and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_COMMITTEE_RESERVATION,
        reason="reserved_cost_above_cap",
        amounts={
            "cost_cents_reserved": operation.cost_cents_reserved,
            "money_budget_cap_cents": request.money_budget_cap_cents,
        },
    ):
        raise CommitteeAcquisitionBudgetExceeded("committee money cap exceeded")
    if {item.source_key for item in snapshots} != {"sumble_teams", "sumble_people"}:
        raise ValueError("committee reservation requires Teams and People snapshots")

    existing = await find_committee_acquisition_operation(
        conn,
        workspace_id=request.workspace_id,
        account_id=request.account_id,
        request_fingerprint=operation.request_fingerprint,
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
            allowed_phases=frozenset({ProjectPhase.DEEP}),
            entity_research_job_id=request.entity_research_job_id,
            enforce_budget=enforce_budget,
        )
    except ProviderSpendGuardError as exc:
        raise CommitteeAcquisitionBudgetExceeded(str(exc)) from exc
    existing = await find_committee_acquisition_operation(
        conn,
        workspace_id=request.workspace_id,
        account_id=request.account_id,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if existing is not None:
        _assert_replay(existing, operation)
        return existing, False

    inserted = await conn.execute(
        text(
            "INSERT INTO committee_acquisition_operation ("
            "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
            "discovery_batch_id, discovery_seal_sha256, account_id, tier_claim_id, "
            "committee_plan_ref, research_direction_ref, organization_identity_ref, "
            "provider_organization_id, "
            "provider_api_version, provider_contract_version, pricing_policy_version, "
            "committee_policy_version, observation_window, request_fingerprint, request_json, "
            "state, spend_outcome, input_artifact_key, provider_units_reserved, "
            "cost_cents_reserved) VALUES ("
            ":id, :workspace_id, :project_id, :project_run_id, :icp_key, :icp_version, "
            ":batch_id, :seal, :account_id, :tier_claim_id, :committee_plan_ref, "
            ":direction_ref, :organization_ref, :organization_id, :api_version, "
            ":contract_version, "
            ":pricing_version, :policy_version, :window, :fingerprint, "
            "CAST(:request_json AS jsonb), CAST(:state AS committee_acquisition_state), "
            "CAST(:spend AS committee_spend_outcome), :input_key, :reserved_units, "
            ":reserved_cost) ON CONFLICT (workspace_id, account_id, request_fingerprint, "
            "observation_window) DO NOTHING RETURNING id"
        ),
        {
            "id": operation.operation_id,
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "icp_key": request.icp_key,
            "icp_version": request.icp_version,
            "batch_id": request.discovery_batch_id,
            "seal": request.discovery_seal_sha256,
            "account_id": request.account_id,
            "tier_claim_id": request.tier_claim_id,
            "committee_plan_ref": request.committee_plan_ref,
            "direction_ref": request.research_direction_ref,
            "organization_ref": request.organization_identity_ref,
            "organization_id": request.provider_organization_id,
            "api_version": request.provider_api_version,
            "contract_version": request.provider_contract_version,
            "pricing_version": request.pricing_policy_version,
            "policy_version": request.committee_policy_version,
            "window": request.observation_window,
            "fingerprint": operation.request_fingerprint,
            "request_json": request.model_dump_json(),
            "state": operation.state.value,
            "spend": operation.spend_outcome.value,
            "input_key": operation.input_artifact_key,
            "reserved_units": operation.provider_units_reserved,
            "reserved_cost": operation.cost_cents_reserved,
        },
    )
    created = inserted.scalar_one_or_none() is not None
    stored = await find_committee_acquisition_operation(
        conn,
        workspace_id=request.workspace_id,
        account_id=request.account_id,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if stored is None:
        raise CommitteeAcquisitionNotFound("reserved committee acquisition")
    _assert_replay(stored, operation)
    if created:
        for snapshot in snapshots:
            await conn.execute(
                text(
                    "INSERT INTO committee_acquisition_snapshot ("
                    "operation_id, workspace_id, account_id, source_key, request_fingerprint, "
                    "state, spend_outcome, request_artifact_key, provider_units_reserved) VALUES ("
                    ":operation_id, :workspace_id, :account_id, :source_key, :fingerprint, "
                    "CAST(:state AS committee_snapshot_state), "
                    "CAST(:spend AS committee_spend_outcome), :request_key, :reserved)"
                ),
                {
                    "operation_id": stored.operation_id,
                    "workspace_id": snapshot.workspace_id,
                    "account_id": snapshot.account_id,
                    "source_key": snapshot.source_key,
                    "fingerprint": snapshot.request_fingerprint,
                    "state": snapshot.state.value,
                    "spend": snapshot.spend_outcome.value,
                    "request_key": snapshot.request_artifact_key,
                    "reserved": snapshot.provider_units_reserved,
                },
            )
    return stored, created


def _assert_replay(
    stored: CommitteeAcquisitionOperation, proposed: CommitteeAcquisitionOperation
) -> None:
    if (
        stored.request != proposed.request
        or stored.input_artifact_key != proposed.input_artifact_key
        or stored.provider_units_reserved != proposed.provider_units_reserved
        or stored.cost_cents_reserved != proposed.cost_cents_reserved
    ):
        raise CommitteeAcquisitionReplayConflict(
            "committee acquisition fingerprint reused with different immutable content"
        )


async def list_committee_acquisition_snapshots(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: CommitteeAcquisitionOperationId,
) -> tuple[CommitteeAcquisitionSnapshot, ...]:
    rows = (
        await conn.execute(
            text(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM committee_acquisition_snapshot "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "ORDER BY source_key"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).all()
    return tuple(_snapshot(row) for row in rows)


async def get_committee_acquisition_snapshot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: CommitteeAcquisitionOperationId,
    source_key: str,
    for_update: bool = False,
) -> CommitteeAcquisitionSnapshot | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM committee_acquisition_snapshot "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "AND source_key=:source_key" + suffix
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "source_key": source_key,
            },
        )
    ).one_or_none()
    return _snapshot(row) if row is not None else None


async def update_committee_acquisition_snapshot(
    conn: AsyncConnection, *, snapshot: CommitteeAcquisitionSnapshot
) -> CommitteeAcquisitionSnapshot:
    row = (
        await conn.execute(
            text(
                "UPDATE committee_acquisition_snapshot SET "
                "state=CAST(:state AS committee_snapshot_state), "
                "spend_outcome=CAST(:spend AS committee_spend_outcome), "
                "response_artifact_key=:response_key, provider_operation_id=:provider_id, "
                "provider_status=:provider_status, provider_units_charged=:charged, "
                "credits_remaining=:remaining, cost_cents_charged=:cost, "
                "failure_code=:failure, updated_at=now() WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id AND source_key=:source_key "
                "AND request_fingerprint=:fingerprint "
                f"RETURNING {_SNAPSHOT_COLUMNS}"
            ),
            {
                "state": snapshot.state.value,
                "spend": snapshot.spend_outcome.value,
                "response_key": snapshot.response_artifact_key,
                "provider_id": snapshot.provider_operation_id,
                "provider_status": snapshot.provider_status,
                "charged": snapshot.provider_units_charged,
                "remaining": snapshot.credits_remaining,
                "cost": snapshot.cost_cents_charged,
                "failure": snapshot.failure_code,
                "workspace_id": snapshot.workspace_id,
                "operation_id": snapshot.operation_id,
                "source_key": snapshot.source_key,
                "fingerprint": snapshot.request_fingerprint,
            },
        )
    ).one_or_none()
    if row is None:
        raise CommitteeAcquisitionReplayConflict("committee snapshot update lost lineage")
    return _snapshot(row)


async def claim_committee_acquisition_start(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: CommitteeAcquisitionOperationId,
) -> CommitteeAcquisitionOperation | None:
    row = (
        await conn.execute(
            text(
                "UPDATE committee_acquisition_operation SET state='acquiring_teams', "
                "started_at=COALESCE(started_at, now()), failure_code=NULL, updated_at=now() "
                "WHERE workspace_id=:workspace_id AND id=:operation_id AND state='planned' "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def claim_committee_acquisition_poll(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: CommitteeAcquisitionOperationId,
    now: datetime,
) -> CommitteeAcquisitionOperation | None:
    row = (
        await conn.execute(
            text(
                "UPDATE committee_acquisition_operation SET state='polling_people', "
                "next_poll_at=NULL, updated_at=now() WHERE workspace_id=:workspace_id "
                "AND id=:operation_id AND state='waiting_external' "
                "AND next_poll_at IS NOT NULL AND next_poll_at <= :now "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id, "now": now},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def list_due_committee_acquisition_project_runs(
    conn: AsyncConnection,
    *,
    now: datetime,
    limit: int = 100,
) -> tuple[ProjectRunId, ...]:
    """Return bounded DEEP runs whose durable committee poll is due.

    This read does not claim provider work.  It only identifies project runs that need their
    provider-neutral DEEP handler re-entered; the ordinary fleet queue supplies deduplication and
    the acquisition coordinator atomically claims the poll after the run wakes.
    """

    if limit < 1:
        raise ValueError("due committee acquisition limit must be positive")
    rows = (
        await conn.execute(
            text(
                "SELECT project_run_id, min(next_poll_at) AS due_at "
                "FROM committee_acquisition_operation "
                "WHERE state='waiting_external' AND next_poll_at IS NOT NULL "
                "AND next_poll_at <= :now "
                "GROUP BY project_run_id "
                "ORDER BY due_at, project_run_id "
                "LIMIT :limit"
            ),
            {"now": now, "limit": limit},
        )
    ).all()
    return tuple(ProjectRunId(row.project_run_id) for row in rows)


async def begin_committee_acquisition_attempt(
    conn: AsyncConnection,
    *,
    operation: CommitteeAcquisitionOperation,
    source_key: str,
    kind: CommitteeAttemptKind,
    request_artifact_key: str,
) -> CommitteeAcquisitionAttempt:
    current = await get_committee_acquisition_operation(
        conn,
        workspace_id=operation.request.workspace_id,
        operation_id=operation.operation_id,
        for_update=True,
    )
    if current is None:
        raise CommitteeAcquisitionNotFound("committee attempt operation")
    ordinal = int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(max(ordinal), -1) + 1 FROM committee_acquisition_attempt "
                    "WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation.operation_id},
            )
        ).scalar_one()
    )
    snapshot = await get_committee_acquisition_snapshot(
        conn,
        workspace_id=operation.request.workspace_id,
        operation_id=operation.operation_id,
        source_key=source_key,
        for_update=True,
    )
    if snapshot is None:
        raise CommitteeAcquisitionNotFound("committee attempt snapshot")
    if snapshot.state not in {
        CommitteeSnapshotState.PLANNED,
        CommitteeSnapshotState.WAITING_EXTERNAL,
    }:
        raise CommitteeAcquisitionReplayConflict("committee snapshot is not dispatchable")
    await update_committee_acquisition_snapshot(
        conn,
        snapshot=snapshot.model_copy(update={"state": CommitteeSnapshotState.DISPATCHING}),
    )
    row = (
        await conn.execute(
            text(
                "INSERT INTO committee_acquisition_attempt ("
                "operation_id, workspace_id, ordinal, source_key, kind, state, "
                "request_artifact_key) VALUES (:operation_id, :workspace_id, :ordinal, "
                ":source_key, CAST(:kind AS committee_attempt_kind), 'dispatching', :request_key) "
                f"RETURNING {_ATTEMPT_COLUMNS}"
            ),
            {
                "operation_id": operation.operation_id,
                "workspace_id": operation.request.workspace_id,
                "ordinal": ordinal,
                "source_key": source_key,
                "kind": kind.value,
                "request_key": request_artifact_key,
            },
        )
    ).one()
    return _attempt(row)


async def update_committee_acquisition_attempt(
    conn: AsyncConnection, *, attempt: CommitteeAcquisitionAttempt
) -> CommitteeAcquisitionAttempt:
    row = (
        await conn.execute(
            text(
                "UPDATE committee_acquisition_attempt SET "
                "state=CAST(:state AS committee_attempt_state), "
                "response_artifact_key=:response_key, provider_operation_id=:provider_id, "
                "provider_status=:provider_status, provider_units_charged=:charged, "
                "credits_remaining=:remaining, failure_code=:failure, completed_at=:completed "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "AND ordinal=:ordinal AND state='dispatching' "
                f"RETURNING {_ATTEMPT_COLUMNS}"
            ),
            {
                "state": attempt.state.value,
                "response_key": attempt.response_artifact_key,
                "provider_id": attempt.provider_operation_id,
                "provider_status": attempt.provider_status,
                "charged": attempt.provider_units_charged,
                "remaining": attempt.credits_remaining,
                "failure": attempt.failure_code,
                "completed": attempt.completed_at,
                "workspace_id": attempt.workspace_id,
                "operation_id": attempt.operation_id,
                "ordinal": attempt.ordinal,
            },
        )
    ).one_or_none()
    if row is None:
        raise CommitteeAcquisitionReplayConflict("committee attempt is already terminal")
    return _attempt(row)


async def list_committee_acquisition_attempts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: CommitteeAcquisitionOperationId,
) -> tuple[CommitteeAcquisitionAttempt, ...]:
    rows = (
        await conn.execute(
            text(
                f"SELECT {_ATTEMPT_COLUMNS} FROM committee_acquisition_attempt "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "ORDER BY ordinal"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).all()
    return tuple(_attempt(row) for row in rows)


async def update_committee_acquisition_operation(
    conn: AsyncConnection, *, operation: CommitteeAcquisitionOperation
) -> CommitteeAcquisitionOperation:
    current = await get_committee_acquisition_operation(
        conn,
        workspace_id=operation.request.workspace_id,
        operation_id=operation.operation_id,
        for_update=True,
    )
    if current is None:
        raise CommitteeAcquisitionNotFound("committee acquisition operation")
    if current.terminal_at is not None:
        if current == operation:
            return current
        raise CommitteeAcquisitionReplayConflict("terminal committee acquisition is immutable")
    if operation.state is CommitteeAcquisitionState.READY:
        snapshots = await list_committee_acquisition_snapshots(
            conn,
            workspace_id=operation.request.workspace_id,
            operation_id=operation.operation_id,
        )
        if {item.source_key for item in snapshots} != {"sumble_teams", "sumble_people"} or any(
            item.state is not CommitteeSnapshotState.SUCCEEDED for item in snapshots
        ):
            raise CommitteeAcquisitionReplayConflict(
                "ready committee acquisition requires succeeded Teams and People snapshots"
            )
    terminal = operation.state in {
        CommitteeAcquisitionState.READY,
        CommitteeAcquisitionState.FAILED_TERMINAL,
        CommitteeAcquisitionState.SPEND_OUTCOME_UNKNOWN,
        CommitteeAcquisitionState.CANCELLED,
    }
    if terminal and operation.cost_cents_charged:
        settled = await conn.execute(
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
        if settled.rowcount != 1:
            raise CommitteeAcquisitionReplayConflict("committee spend settlement lost run lineage")
    row = (
        await conn.execute(
            text(
                "UPDATE committee_acquisition_operation SET "
                "state=CAST(:state AS committee_acquisition_state), "
                "spend_outcome=CAST(:spend AS committee_spend_outcome), "
                "receipt_manifest_key=:receipt, provider_units_charged=:charged, "
                "cost_cents_charged=:cost, next_poll_at=:next_poll_at, failure_code=:failure, "
                "started_at=:started_at, terminal_at=:terminal_at, updated_at=now() "
                "WHERE workspace_id=:workspace_id AND id=:operation_id "
                "AND request_fingerprint=:fingerprint "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {
                "state": operation.state.value,
                "spend": operation.spend_outcome.value,
                "receipt": operation.receipt_manifest_key,
                "charged": operation.provider_units_charged,
                "cost": operation.cost_cents_charged,
                "next_poll_at": operation.next_poll_at,
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
        raise CommitteeAcquisitionReplayConflict("committee operation update lost lineage")
    return _operation(row)


__all__ = [
    "CommitteeAcquisitionBudgetExceeded",
    "CommitteeAcquisitionNotFound",
    "CommitteeAcquisitionReplayConflict",
    "CommitteeAcquisitionRepositoryError",
    "begin_committee_acquisition_attempt",
    "claim_committee_acquisition_poll",
    "claim_committee_acquisition_start",
    "find_committee_acquisition_operation",
    "get_committee_acquisition_operation",
    "get_committee_acquisition_snapshot",
    "list_committee_acquisition_attempts",
    "list_due_committee_acquisition_project_runs",
    "list_committee_acquisition_snapshots",
    "reserve_committee_acquisition",
    "update_committee_acquisition_attempt",
    "update_committee_acquisition_operation",
    "update_committee_acquisition_snapshot",
]
