"""Provider-neutral PostgreSQL repository for post-seal targeted enrichment (M6A E1)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityId,
    ProjectPhase,
    TargetedEnrichmentFieldResult,
    TargetedEnrichmentOperation,
    TargetedEnrichmentOperationId,
    TargetedEnrichmentRequest,
    TargetedEnrichmentSpendOutcome,
    TargetedEnrichmentState,
    UtcDatetime,
)
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.durable.spend_posture import cap_refusal_is_enforced

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20).
_SITE_TARGETED_RESERVATION: Final = "targeted_enrichment_reservation"


class TargetedEnrichmentRepositoryError(RuntimeError):
    pass


class TargetedEnrichmentNotFound(TargetedEnrichmentRepositoryError):
    pass


class TargetedEnrichmentReplayConflict(TargetedEnrichmentRepositoryError):
    pass


class TargetedEnrichmentBudgetExceeded(TargetedEnrichmentRepositoryError):
    pass


class TargetedEnrichmentItemSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: TargetedEnrichmentOperationId
    workspace_id: str
    provider_item_id: str
    source_entity_id: str
    account_id: EntityId
    raw_artifact_key: str
    item_sha256: str
    observed_at: UtcDatetime
    materialized_at: UtcDatetime | None = None
    created_at: UtcDatetime | None = None


class TargetedEnrichmentArtifactRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: TargetedEnrichmentOperationId
    workspace_id: str
    ordinal: int
    artifact_kind: str
    artifact_key: str
    content_sha256: str
    provider_request_id: str | None = None
    created_at: UtcDatetime


_OPERATION_COLUMNS = (
    "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
    "discovery_batch_id, discovery_seal_sha256, source_key, provider_api_version, "
    "provider_contract_version, pricing_policy_version, field_policy_version, "
    "observation_window, request_fingerprint, request_json, provider_external_id, state::text, "
    "spend_outcome::text, import_id, provider_operation_id, input_artifact_key, csv_artifact_key, "
    "submitted_receipt_ref, final_receipt_ref, raw_response_manifest_key, "
    "provider_units_reserved, provider_units_charged, cost_cents_reserved, cost_cents_charged, "
    "next_poll_at, failure_code, started_at, terminal_at, created_at, updated_at"
)
_QUALIFIED_OPERATION_COLUMNS = ", ".join(
    f"operation.{column.strip()}" for column in _OPERATION_COLUMNS.split(",")
)


def _operation(row: object) -> TargetedEnrichmentOperation:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    request = TargetedEnrichmentRequest.model_validate(data.pop("request_json"))
    # These columns make the lineage queryable and enforceable by PostgreSQL, but the request is
    # the single immutable owner of their values in the provider-neutral domain contract.
    for request_field in (
        "workspace_id",
        "project_id",
        "project_run_id",
        "icp_key",
        "icp_version",
        "discovery_batch_id",
        "discovery_seal_sha256",
        "source_key",
        "provider_api_version",
        "provider_contract_version",
        "pricing_policy_version",
        "field_policy_version",
        "observation_window",
    ):
        data.pop(request_field)
    data["operation_id"] = data.pop("id")
    data["request"] = request
    return TargetedEnrichmentOperation.model_validate(data)


async def reserve_targeted_enrichment_operation(
    conn: AsyncConnection,
    *,
    operation: TargetedEnrichmentOperation,
    enforce_budget: bool = True,
) -> tuple[TargetedEnrichmentOperation, bool]:
    """Reserve one bounded targeted-enrichment operation.

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
        site=_SITE_TARGETED_RESERVATION,
        reason="reserved_units_above_cap",
        amounts={
            "provider_units_reserved": operation.provider_units_reserved,
            "provider_credit_cap": request.provider_credit_cap,
        },
    ):
        raise TargetedEnrichmentBudgetExceeded("targeted enrichment provider cap exceeded")
    if operation.cost_cents_reserved > Decimal(
        request.money_budget_cap_cents
    ) and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_TARGETED_RESERVATION,
        reason="reserved_cost_above_cap",
        amounts={
            "cost_cents_reserved": operation.cost_cents_reserved,
            "money_budget_cap_cents": request.money_budget_cap_cents,
        },
    ):
        raise TargetedEnrichmentBudgetExceeded("targeted enrichment money cap exceeded")

    existing = await find_targeted_enrichment_operation(
        conn,
        workspace_id=request.workspace_id,
        source_key=request.source_key,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if existing is not None:
        _assert_targeted_enrichment_replay(existing, operation)
        return existing, False

    try:
        await require_provider_spend_capacity(
            conn,
            project_run_id=request.project_run_id,
            proposed_cents=operation.cost_cents_reserved,
            allowed_phases=frozenset({ProjectPhase.DEEP}),
            enforce_budget=enforce_budget,
        )
    except ProviderSpendGuardError as exc:
        raise TargetedEnrichmentBudgetExceeded(str(exc)) from exc

    # A competing reservation for this run had to release the same project-run lock before this
    # transaction acquired it. Recheck the fingerprint under the lock so an exact replay never
    # consumes capacity and a conflicting replay fails before any child rows are written.
    existing = await find_targeted_enrichment_operation(
        conn,
        workspace_id=request.workspace_id,
        source_key=request.source_key,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if existing is not None:
        _assert_targeted_enrichment_replay(existing, operation)
        return existing, False

    inserted = await conn.execute(
        text(
            "INSERT INTO targeted_enrichment_operation ("
            "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
            "discovery_batch_id, discovery_seal_sha256, source_key, provider_api_version, "
            "provider_contract_version, pricing_policy_version, field_policy_version, "
            "observation_window, request_fingerprint, request_json, provider_external_id, state, "
            "spend_outcome, input_artifact_key, csv_artifact_key, provider_units_reserved, "
            "cost_cents_reserved) VALUES ("
            ":id, :workspace_id, :project_id, :project_run_id, :icp_key, :icp_version, "
            ":batch_id, :seal, :source_key, :api_version, :contract_version, :pricing_version, "
            ":field_policy_version, :window, :fingerprint, CAST(:request_json AS jsonb), "
            ":external, "
            "CAST(:state AS targeted_enrichment_state), "
            "CAST(:spend AS targeted_enrichment_spend_outcome), :input_key, :csv_key, "
            ":reserved_units, :reserved_cost) "
            "ON CONFLICT (workspace_id, source_key, request_fingerprint, observation_window) "
            "DO NOTHING RETURNING id"
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
            "source_key": request.source_key,
            "api_version": request.provider_api_version,
            "contract_version": request.provider_contract_version,
            "pricing_version": request.pricing_policy_version,
            "field_policy_version": request.field_policy_version,
            "window": request.observation_window,
            "fingerprint": operation.request_fingerprint,
            "request_json": request.model_dump_json(),
            "external": operation.provider_external_id,
            "state": operation.state.value,
            "spend": operation.spend_outcome.value,
            "input_key": operation.input_artifact_key,
            "csv_key": operation.csv_artifact_key,
            "reserved_units": operation.provider_units_reserved,
            "reserved_cost": operation.cost_cents_reserved,
        },
    )
    created = inserted.scalar_one_or_none() is not None
    stored = await find_targeted_enrichment_operation(
        conn,
        workspace_id=request.workspace_id,
        source_key=request.source_key,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if stored is None:
        raise TargetedEnrichmentNotFound("reserved targeted enrichment operation")
    _assert_targeted_enrichment_replay(stored, operation)
    if created:
        for ordinal, target in enumerate(request.targets):
            await conn.execute(
                text(
                    "INSERT INTO targeted_enrichment_target ("
                    "operation_id, workspace_id, account_id, identifier_url, tier_claim_id, ordinal"
                    ") VALUES (:operation_id, :workspace_id, :account_id, :url, :claim_id, "
                    ":ordinal)"
                ),
                {
                    "operation_id": stored.operation_id,
                    "workspace_id": request.workspace_id,
                    "account_id": target.account_id,
                    "url": target.identifier_url,
                    "claim_id": target.tier_claim_id,
                    "ordinal": ordinal,
                },
            )
            for field in request.fields:
                await conn.execute(
                    text(
                        "INSERT INTO targeted_enrichment_field_result ("
                        "operation_id, workspace_id, account_id, field_key, state, reason_code) "
                        "VALUES (:operation_id, :workspace_id, :account_id, :field_key, "
                        "'pending', 'awaiting_provider')"
                    ),
                    {
                        "operation_id": stored.operation_id,
                        "workspace_id": request.workspace_id,
                        "account_id": target.account_id,
                        "field_key": str(field.field_key),
                    },
                )
    return stored, created


def _assert_targeted_enrichment_replay(
    stored: TargetedEnrichmentOperation,
    proposed: TargetedEnrichmentOperation,
) -> None:
    immutable_match = (
        stored.request == proposed.request
        and stored.provider_external_id == proposed.provider_external_id
        and stored.input_artifact_key == proposed.input_artifact_key
        and stored.csv_artifact_key == proposed.csv_artifact_key
        and stored.provider_units_reserved == proposed.provider_units_reserved
        and stored.cost_cents_reserved == proposed.cost_cents_reserved
    )
    if not immutable_match:
        raise TargetedEnrichmentReplayConflict(
            "targeted enrichment fingerprint was reused with different immutable content"
        )


async def get_targeted_enrichment_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: TargetedEnrichmentOperationId,
    for_update: bool = False,
) -> TargetedEnrichmentOperation | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM targeted_enrichment_operation "
                "WHERE workspace_id=:workspace_id AND id=:operation_id" + suffix
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def find_targeted_enrichment_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    source_key: str,
    request_fingerprint: str,
    observation_window: str,
) -> TargetedEnrichmentOperation | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM targeted_enrichment_operation "
                "WHERE workspace_id=:workspace_id AND source_key=:source_key "
                "AND request_fingerprint=:fingerprint AND observation_window=:window"
            ),
            {
                "workspace_id": workspace_id,
                "source_key": source_key,
                "fingerprint": request_fingerprint,
                "window": observation_window,
            },
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def claim_targeted_enrichment_dispatch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: TargetedEnrichmentOperationId,
) -> TargetedEnrichmentOperation | None:
    row = (
        await conn.execute(
            text(
                "UPDATE targeted_enrichment_operation SET state='submitting', "
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


async def claim_due_targeted_enrichment_operations(
    conn: AsyncConnection,
    *,
    now: datetime,
    limit: int = 10,
    lease_seconds: int = 60,
) -> tuple[TargetedEnrichmentOperation, ...]:
    """Lease due provider-running E1 operations for crash-resumable fleet polling.

    Moving ``next_poll_at`` forward is the lease. A killed worker makes the row due again after the
    bounded interval; ``FOR UPDATE SKIP LOCKED`` prevents two healthy workers polling it together.
    """

    if not 1 <= limit <= 100:
        raise ValueError("targeted enrichment claim limit must be between 1 and 100")
    if lease_seconds < 1:
        raise ValueError("targeted enrichment lease must be positive")
    rows = (
        await conn.execute(
            text(
                f"""
                    WITH due AS (
                        SELECT id
                        FROM targeted_enrichment_operation
                        WHERE state IN ('provider_running', 'waiting_external', 'reconciling')
                          AND next_poll_at IS NOT NULL AND next_poll_at <= :now
                        ORDER BY next_poll_at, id
                        FOR UPDATE SKIP LOCKED
                        LIMIT :limit
                    )
                    UPDATE targeted_enrichment_operation operation
                    SET next_poll_at = :now + (:lease_seconds * interval '1 second'),
                        updated_at = now()
                    FROM due
                    WHERE operation.id = due.id
                    RETURNING {_QUALIFIED_OPERATION_COLUMNS}
                    """
            ),
            {"now": now, "limit": limit, "lease_seconds": lease_seconds},
        )
    ).all()
    return tuple(_operation(row) for row in rows)


async def update_targeted_enrichment_operation(
    conn: AsyncConnection,
    *,
    operation: TargetedEnrichmentOperation,
) -> TargetedEnrichmentOperation:
    if operation.state is TargetedEnrichmentState.SUCCEEDED:
        pending = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM targeted_enrichment_field_result "
                    "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                    "AND state='pending'"
                ),
                {
                    "workspace_id": operation.request.workspace_id,
                    "operation_id": operation.operation_id,
                },
            )
        ).scalar_one()
        if pending:
            raise TargetedEnrichmentReplayConflict(
                "targeted enrichment cannot succeed with pending field outcomes"
            )
    row = (
        await conn.execute(
            text(
                "UPDATE targeted_enrichment_operation SET "
                "state=CAST(:state AS targeted_enrichment_state), "
                "spend_outcome=CAST(:spend AS targeted_enrichment_spend_outcome), "
                "import_id=:import_id, provider_operation_id=:provider_operation_id, "
                "submitted_receipt_ref=:submitted_receipt_ref, "
                "final_receipt_ref=:final_receipt_ref, "
                "raw_response_manifest_key=:manifest_key, provider_units_charged=:charged_units, "
                "cost_cents_charged=:charged_cost, next_poll_at=:next_poll_at, "
                "failure_code=:failure_code, started_at=:started_at, terminal_at=:terminal_at, "
                "updated_at=now() WHERE workspace_id=:workspace_id AND id=:operation_id "
                "AND request_fingerprint=:fingerprint "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {
                "state": operation.state.value,
                "spend": operation.spend_outcome.value,
                "import_id": operation.import_id,
                "provider_operation_id": operation.provider_operation_id,
                "submitted_receipt_ref": operation.submitted_receipt_ref,
                "final_receipt_ref": operation.final_receipt_ref,
                "manifest_key": operation.raw_response_manifest_key,
                "charged_units": operation.provider_units_charged,
                "charged_cost": operation.cost_cents_charged,
                "next_poll_at": operation.next_poll_at,
                "failure_code": operation.failure_code,
                "started_at": operation.started_at,
                "terminal_at": operation.terminal_at,
                "workspace_id": operation.request.workspace_id,
                "operation_id": operation.operation_id,
                "fingerprint": operation.request_fingerprint,
            },
        )
    ).one_or_none()
    if row is None:
        raise TargetedEnrichmentReplayConflict("targeted enrichment operation update lost lineage")
    return _operation(row)


async def put_targeted_enrichment_item(
    conn: AsyncConnection,
    *,
    snapshot: TargetedEnrichmentItemSnapshot,
) -> TargetedEnrichmentItemSnapshot:
    await conn.execute(
        text(
            "INSERT INTO targeted_enrichment_item_snapshot ("
            "operation_id, workspace_id, provider_item_id, source_entity_id, account_id, "
            "raw_artifact_key, item_sha256, observed_at, materialized_at) VALUES ("
            ":operation_id, :workspace_id, :provider_item_id, :source_entity_id, :account_id, "
            ":artifact_key, :sha256, :observed_at, :materialized_at) ON CONFLICT DO NOTHING"
        ),
        {
            "operation_id": snapshot.operation_id,
            "workspace_id": snapshot.workspace_id,
            "provider_item_id": snapshot.provider_item_id,
            "source_entity_id": snapshot.source_entity_id,
            "account_id": snapshot.account_id,
            "artifact_key": snapshot.raw_artifact_key,
            "sha256": snapshot.item_sha256,
            "observed_at": snapshot.observed_at,
            "materialized_at": snapshot.materialized_at,
        },
    )
    row = (
        await conn.execute(
            text(
                "SELECT operation_id, workspace_id, provider_item_id, source_entity_id, "
                "account_id, "
                "raw_artifact_key, item_sha256, observed_at, materialized_at, created_at "
                "FROM targeted_enrichment_item_snapshot WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id AND provider_item_id=:provider_item_id"
            ),
            {
                "workspace_id": snapshot.workspace_id,
                "operation_id": snapshot.operation_id,
                "provider_item_id": snapshot.provider_item_id,
            },
        )
    ).one_or_none()
    if row is None:
        raise TargetedEnrichmentNotFound("targeted enrichment item")
    stored = TargetedEnrichmentItemSnapshot.model_validate(dict(row._mapping))
    expected = snapshot.model_dump(exclude={"created_at"})
    actual = stored.model_dump(exclude={"created_at"})
    if expected != actual:
        raise TargetedEnrichmentReplayConflict("provider item id was reused with different bytes")
    return stored


async def append_targeted_enrichment_artifact(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: TargetedEnrichmentOperationId,
    artifact_kind: str,
    artifact_key: str,
    content_sha256: str,
    provider_request_id: str | None = None,
) -> TargetedEnrichmentArtifactRow:
    # Serialize ordinal allocation on the operation. Reusing the same content-addressed artifact is
    # idempotent even if a response-persistence transaction is replayed.
    await conn.execute(
        text(
            "SELECT id FROM targeted_enrichment_operation WHERE workspace_id=:workspace_id "
            "AND id=:operation_id FOR UPDATE"
        ),
        {"workspace_id": workspace_id, "operation_id": operation_id},
    )
    existing = (
        await conn.execute(
            text(
                "SELECT operation_id, workspace_id, ordinal, artifact_kind, artifact_key, "
                "content_sha256, provider_request_id, created_at "
                "FROM targeted_enrichment_artifact WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id AND artifact_kind=:kind "
                "AND content_sha256=:sha256 "
                "AND provider_request_id IS NOT DISTINCT FROM :request_id"
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "kind": artifact_kind,
                "sha256": content_sha256,
                "request_id": provider_request_id,
            },
        )
    ).one_or_none()
    if existing is not None:
        stored = TargetedEnrichmentArtifactRow.model_validate(dict(existing._mapping))
        if stored.artifact_key != artifact_key:
            raise TargetedEnrichmentReplayConflict(
                "targeted enrichment response identity was replayed with different bytes"
            )
        return stored
    ordinal = (
        await conn.execute(
            text(
                "SELECT COALESCE(max(ordinal), -1) + 1 FROM targeted_enrichment_artifact "
                "WHERE operation_id=:operation_id"
            ),
            {"operation_id": operation_id},
        )
    ).scalar_one()
    row = (
        await conn.execute(
            text(
                "INSERT INTO targeted_enrichment_artifact ("
                "operation_id, workspace_id, ordinal, artifact_kind, artifact_key, content_sha256, "
                "provider_request_id) VALUES (:operation_id, :workspace_id, :ordinal, :kind, "
                ":artifact_key, :sha256, :request_id) RETURNING operation_id, workspace_id, "
                "ordinal, artifact_kind, artifact_key, content_sha256, provider_request_id, "
                "created_at"
            ),
            {
                "operation_id": operation_id,
                "workspace_id": workspace_id,
                "ordinal": ordinal,
                "kind": artifact_kind,
                "artifact_key": artifact_key,
                "sha256": content_sha256,
                "request_id": provider_request_id,
            },
        )
    ).one()
    return TargetedEnrichmentArtifactRow.model_validate(dict(row._mapping))


async def list_targeted_enrichment_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: TargetedEnrichmentOperationId,
) -> tuple[TargetedEnrichmentArtifactRow, ...]:
    rows = (
        await conn.execute(
            text(
                "SELECT operation_id, workspace_id, ordinal, artifact_kind, artifact_key, "
                "content_sha256, provider_request_id, created_at "
                "FROM targeted_enrichment_artifact WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id ORDER BY ordinal"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).all()
    return tuple(TargetedEnrichmentArtifactRow.model_validate(dict(row._mapping)) for row in rows)


async def put_targeted_enrichment_field_result(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    result: TargetedEnrichmentFieldResult,
) -> TargetedEnrichmentFieldResult:
    row = (
        await conn.execute(
            text(
                "UPDATE targeted_enrichment_field_result SET "
                "state=CAST(:state AS targeted_enrichment_field_state), "
                "provider_item_id=:provider_item_id, item_artifact_key=:artifact_key, "
                "claim_id=:claim_id, reason_code=:reason_code, updated_at=now() "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "AND account_id=:account_id AND field_key=:field_key AND state='pending' "
                "RETURNING operation_id, account_id, field_key, state::text, provider_item_id, "
                "item_artifact_key, claim_id, reason_code, updated_at"
            ),
            {
                "state": result.state.value,
                "provider_item_id": result.provider_item_id,
                "artifact_key": result.item_artifact_key,
                "claim_id": result.claim_id,
                "reason_code": result.reason_code,
                "workspace_id": workspace_id,
                "operation_id": result.operation_id,
                "account_id": result.account_id,
                "field_key": str(result.field_key),
            },
        )
    ).one_or_none()
    if row is not None:
        return TargetedEnrichmentFieldResult.model_validate(dict(row._mapping))
    existing = await get_targeted_enrichment_field_result(
        conn,
        workspace_id=workspace_id,
        operation_id=result.operation_id,
        account_id=result.account_id,
        field_key=str(result.field_key),
    )
    if existing is None:
        raise TargetedEnrichmentNotFound("targeted enrichment field result")
    # Timestamps are observational and do not participate in replay equivalence.
    if existing.model_dump(exclude={"updated_at"}) != result.model_dump(exclude={"updated_at"}):
        raise TargetedEnrichmentReplayConflict(
            "targeted enrichment field already has a different terminal result"
        )
    return existing


async def get_targeted_enrichment_field_result(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: TargetedEnrichmentOperationId,
    account_id: EntityId,
    field_key: str,
) -> TargetedEnrichmentFieldResult | None:
    row = (
        await conn.execute(
            text(
                "SELECT operation_id, account_id, field_key, state::text, provider_item_id, "
                "item_artifact_key, claim_id, reason_code, updated_at "
                "FROM targeted_enrichment_field_result WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id AND account_id=:account_id AND field_key=:field_key"
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "account_id": account_id,
                "field_key": field_key,
            },
        )
    ).one_or_none()
    return (
        TargetedEnrichmentFieldResult.model_validate(dict(row._mapping))
        if row is not None
        else None
    )


async def list_targeted_enrichment_field_results(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: TargetedEnrichmentOperationId,
) -> tuple[TargetedEnrichmentFieldResult, ...]:
    rows = (
        await conn.execute(
            text(
                "SELECT operation_id, account_id, field_key, state::text, provider_item_id, "
                "item_artifact_key, claim_id, reason_code, updated_at "
                "FROM targeted_enrichment_field_result WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id ORDER BY account_id::text, field_key"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).all()
    return tuple(TargetedEnrichmentFieldResult.model_validate(dict(row._mapping)) for row in rows)


async def fail_targeted_enrichment_predispatch(
    conn: AsyncConnection,
    *,
    operation: TargetedEnrichmentOperation,
    failure_code: str,
) -> TargetedEnrichmentOperation:
    return await update_targeted_enrichment_operation(
        conn,
        operation=operation.model_copy(
            update={
                "state": TargetedEnrichmentState.FAILED_RETRYABLE,
                "spend_outcome": TargetedEnrichmentSpendOutcome.NOT_CHARGED,
                "failure_code": failure_code,
                "next_poll_at": None,
            }
        ),
    )


__all__ = [
    "TargetedEnrichmentBudgetExceeded",
    "TargetedEnrichmentArtifactRow",
    "TargetedEnrichmentItemSnapshot",
    "TargetedEnrichmentNotFound",
    "TargetedEnrichmentReplayConflict",
    "TargetedEnrichmentRepositoryError",
    "append_targeted_enrichment_artifact",
    "claim_targeted_enrichment_dispatch",
    "claim_due_targeted_enrichment_operations",
    "fail_targeted_enrichment_predispatch",
    "find_targeted_enrichment_operation",
    "get_targeted_enrichment_field_result",
    "get_targeted_enrichment_operation",
    "list_targeted_enrichment_artifacts",
    "list_targeted_enrichment_field_results",
    "put_targeted_enrichment_field_result",
    "put_targeted_enrichment_item",
    "reserve_targeted_enrichment_operation",
    "update_targeted_enrichment_operation",
]
