"""Provider-neutral durable discovery-batch repository (M6A D1).

This module is the only production write/read path to the D1 discovery tables.  Every operation is
workspace-scoped, all provider bytes are captured through the shared content-addressed artifact
store, and the seal writer derives the fourteen completion predicates from one locked PostgreSQL
snapshot.  No caller can hand the writer a precomputed readiness flag.

The module deliberately knows no provider.  D2+ adapters persist their request/response/event/page
contracts through these functions and consume only references on replay.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    FIRST_PAGE_CURSOR,
    DiscoveryBatchId,
    DiscoveryBatchSeal,
    DiscoveryBatchState,
    DiscoveryCandidateAdmissionState,
    DiscoveryEventDisposition,
    DiscoveryFieldResolution,
    DiscoveryFieldResolutionState,
    DiscoveryItemSnapshot,
    DiscoveryItemSnapshotId,
    DiscoveryNormalizationState,
    DiscoveryOperation,
    DiscoveryOperationId,
    DiscoveryPageReceipt,
    DiscoveryPlan,
    DiscoveryPlanId,
    DiscoveryProviderEvent,
    DiscoverySealBlocker,
    DiscoverySealReadiness,
    DiscoveryWakeRequest,
    DiscoveryWakeScheduler,
    EntityId,
    ProjectRunId,
    UtcDatetime,
    decode_jsonb,
    discovery_plan_sha256,
    evaluate_discovery_seal,
    serialize_value_json,
)
from clue_db import ConnFactory, transaction
from clue_storage import StorageBackend, artifact_key, content_address
from clue_storage.artifacts import erase_if_unreferenced, record_artifact


class DiscoveryRepositoryError(RuntimeError):
    """Base failure raised by the durable discovery repository."""


class DiscoveryNotFound(DiscoveryRepositoryError):
    """The scoped discovery object does not exist."""


class DiscoveryReplayConflict(DiscoveryRepositoryError):
    """A stable idempotency key was reused with different immutable content."""


class DiscoverySealBlocked(DiscoveryRepositoryError):
    """The SQL-derived completion barrier is not yet satisfied."""

    def __init__(self, blockers: tuple[DiscoverySealBlocker, ...]) -> None:
        self.blockers = blockers
        super().__init__("discovery seal blocked: " + ", ".join(item.value for item in blockers))


class DiscoverySealConflict(DiscoveryRepositoryError):
    """A concurrent/replayed seal attempt proposed different immutable manifests."""


class DiscoveryPlanRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: DiscoveryPlan
    plan_sha256: str
    created_at: UtcDatetime


class DiscoveryBatchRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: DiscoveryBatchId
    workspace_id: str
    project_id: str
    project_run_id: ProjectRunId
    icp_key: str
    icp_version: int
    discovery_plan_id: DiscoveryPlanId
    state: DiscoveryBatchState
    generation: int
    provider_units_reserved: Decimal
    provider_units_charged: Decimal
    cost_cents_charged: Decimal
    failure_code: str | None
    replacement_batch_id: DiscoveryBatchId | None
    started_at: UtcDatetime
    updated_at: UtcDatetime
    sealed_at: UtcDatetime | None


class DiscoveryCandidateLinkRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    batch_id: DiscoveryBatchId
    item_snapshot_id: DiscoveryItemSnapshotId
    raw_name: str | None
    candidate_domain: str | None
    source_url: str | None
    admission_status: DiscoveryCandidateAdmissionState
    account_entity_id: EntityId | None
    survivor_entity_id: EntityId | None
    disposition_reason: str | None
    updated_at: UtcDatetime


class DiscoveryArtifactSubjectRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    workspace_id: str
    artifact_key: str
    subject_kind: str
    subject_entity_id: EntityId
    reference_kind: str
    reference_id: str
    created_at: UtcDatetime
    tombstoned_at: UtcDatetime | None


class DiscoveryWakeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    workspace_id: str
    project_run_id: ProjectRunId
    batch_id: DiscoveryBatchId
    operation_id: DiscoveryOperationId | None
    reason: str
    available_at: UtcDatetime
    dedupe_key: str
    created_at: UtcDatetime
    claimed_at: UtcDatetime | None
    processed_at: UtcDatetime | None


class DiscoverySealDraft(BaseModel):
    """Only the artifact refs that cannot be derived from relational discovery state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_manifest_artifact_key: str
    account_manifest_sha256: str
    raw_artifact_manifest_key: str
    claim_id_manifest_key: str
    coverage_report_ref: str

    @model_validator(mode="after")
    def _sha_is_canonical(self) -> DiscoverySealDraft:
        if re.fullmatch(r"[0-9a-f]{64}", self.account_manifest_sha256) is None:
            raise ValueError("account_manifest_sha256 must be 64 lowercase hex characters")
        return self


class DiscoveryBatchStatusProjection(BaseModel):
    """Bounded, body-free operational status for one discovery batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch: DiscoveryBatchRow
    operation_count: int
    operation_state_counts: dict[str, int]
    pending_operation_ids: tuple[DiscoveryOperationId, ...]
    next_poll_at: UtcDatetime | None
    item_count: int
    candidate_state_counts: dict[str, int]
    field_state_counts: dict[str, int]
    seal_blockers: tuple[DiscoverySealBlocker, ...]
    seal_sha256: str | None


_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set_cookie",
        "x_api_key",
        "api_key",
        "access_token",
        "refresh_token",
        "webhook_secret",
        "client_secret",
        "password",
    }
)


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _assert_secret_free_json(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _normalized_key(str(key)) in _SENSITIVE_KEYS:
                raise ValueError(f"discovery artifact contains forbidden credential key {key!r}")
            _assert_secret_free_json(child)
    elif isinstance(value, list):
        for child in value:
            _assert_secret_free_json(child)


def _assert_safe_source_url(source_url: str | None) -> None:
    if source_url is None:
        return
    parsed = urlsplit(source_url)
    if parsed.username or parsed.password:
        raise ValueError("credential-bearing discovery artifact URL is forbidden")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if _normalized_key(key) in _SENSITIVE_KEYS:
            raise ValueError("credential-bearing discovery artifact URL is forbidden")


async def capture_discovery_artifact(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    content: bytes,
    media_type: str,
    source_key: str,
    source_url: str | None = None,
) -> str:
    """Capture sanitized provider bytes under a workspace-scoped content address.

    JSON artifacts are rejected when they contain credential-shaped keys.  Authorization headers
    are transport metadata and therefore never valid raw-evidence content.
    """

    if not workspace_id.strip():
        raise ValueError("workspace_id must be non-empty")
    _assert_safe_source_url(source_url)
    if "json" in media_type.lower():
        try:
            decoded = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON discovery artifact is not valid JSON") from exc
        _assert_secret_free_json(decoded)
    sha256 = content_address(content)
    key = artifact_key(workspace_id, sha256)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha256,
        media_type=media_type,
        size_bytes=len(content),
        source_key=source_key,
        source_url=source_url,
    )
    if not await storage.exists(key):
        await storage.put(key, content, media_type=media_type)
    return key


_PLAN_COLUMNS = "plan_json, plan_sha256, created_at"


async def put_discovery_plan(
    conn: AsyncConnection, *, workspace_id: str, plan: DiscoveryPlan
) -> DiscoveryPlanRow:
    if plan.workspace_id != workspace_id:
        raise ValueError("discovery plan workspace does not match repository scope")
    plan_sha = discovery_plan_sha256(plan)
    await conn.execute(
        text(
            """
            INSERT INTO discovery_plan (
                id, workspace_id, project_id, project_run_id, icp_key, icp_version, plan_version,
                plan_sha256, provider_policy_version, field_policy_version,
                provider_contract_version, plan_json
            ) VALUES (
                :id, :workspace_id, :project_id, :project_run_id, :icp_key, :icp_version,
                :plan_version, :plan_sha256, :provider_policy_version, :field_policy_version,
                :provider_contract_version, CAST(:plan_json AS jsonb)
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": plan.discovery_plan_id,
            "workspace_id": workspace_id,
            "project_id": plan.project_id,
            "project_run_id": plan.project_run_id,
            "icp_key": plan.icp_key,
            "icp_version": plan.icp_version,
            "plan_version": plan.plan_version,
            "plan_sha256": plan_sha,
            "provider_policy_version": plan.provider_policy_version,
            "field_policy_version": plan.field_policy_version,
            "provider_contract_version": plan.provider_contract_version,
            "plan_json": serialize_value_json(cast(JsonValue, plan.model_dump(mode="json"))),
        },
    )
    row = await get_discovery_plan(conn, workspace_id=workspace_id, plan_id=plan.discovery_plan_id)
    if row is None:
        raise DiscoveryNotFound(f"discovery plan {plan.discovery_plan_id}")
    if row.plan_sha256 != plan_sha:
        raise DiscoveryReplayConflict(f"discovery plan {plan.discovery_plan_id} content changed")
    return row


async def get_discovery_plan(
    conn: AsyncConnection, *, workspace_id: str, plan_id: DiscoveryPlanId
) -> DiscoveryPlanRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_PLAN_COLUMNS} FROM discovery_plan "
                    "WHERE workspace_id = :workspace_id AND id = :id"
                ),
                {"workspace_id": workspace_id, "id": plan_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    plan_json = decode_jsonb(row["plan_json"])
    return DiscoveryPlanRow(
        plan=DiscoveryPlan.model_validate(plan_json),
        plan_sha256=str(row["plan_sha256"]),
        created_at=row["created_at"],
    )


_BATCH_COLUMNS = (
    "id, workspace_id, project_id, project_run_id, icp_key, icp_version, discovery_plan_id, "
    "state, generation, provider_units_reserved, provider_units_charged, cost_cents_charged, "
    "failure_code, replacement_batch_id, started_at, updated_at, sealed_at"
)


async def create_discovery_batch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    plan_id: DiscoveryPlanId,
    generation: int,
) -> DiscoveryBatchRow:
    if generation < 1:
        raise ValueError("discovery batch generation must be positive")
    await conn.execute(
        text(
            """
            INSERT INTO discovery_batch (
                id, workspace_id, project_id, project_run_id, icp_key, icp_version,
                discovery_plan_id, generation
            )
            SELECT :batch_id, p.workspace_id, p.project_id, p.project_run_id, p.icp_key,
                   p.icp_version, p.id, :generation
            FROM discovery_plan p
            WHERE p.id = :plan_id AND p.workspace_id = :workspace_id
            ON CONFLICT (workspace_id, project_run_id, generation) DO NOTHING
            """
        ),
        {
            "batch_id": batch_id,
            "plan_id": plan_id,
            "workspace_id": workspace_id,
            "generation": generation,
        },
    )
    row = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    if row is None:
        existing = (
            (
                await conn.execute(
                    text(
                        f"SELECT {_BATCH_COLUMNS} FROM discovery_batch "
                        "WHERE workspace_id = :workspace_id AND discovery_plan_id = :plan_id "
                        "AND generation = :generation"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "plan_id": plan_id,
                        "generation": generation,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is None:
            raise DiscoveryNotFound(f"discovery plan {plan_id} in workspace {workspace_id}")
        row = _batch_row(existing)
    if row.discovery_plan_id != plan_id or row.generation != generation:
        raise DiscoveryReplayConflict(f"discovery batch {batch_id} identity changed")
    return row


async def get_discovery_batch(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> DiscoveryBatchRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_BATCH_COLUMNS} FROM discovery_batch "
                    "WHERE workspace_id = :workspace_id AND id = :id"
                ),
                {"workspace_id": workspace_id, "id": batch_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _batch_row(row) if row is not None else None


async def update_discovery_batch_state(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    state: DiscoveryBatchState,
    failure_code: str | None = None,
) -> DiscoveryBatchRow:
    if state is DiscoveryBatchState.SEALED:
        raise ValueError("only seal_discovery_batch may transition a batch to sealed")
    result = await conn.execute(
        text(
            """
            UPDATE discovery_batch
            SET state = CAST(:state AS discovery_batch_state), failure_code = :failure_code,
                updated_at = now()
            WHERE workspace_id = :workspace_id AND id = :id AND state <> 'sealed'
            """
        ),
        {
            "workspace_id": workspace_id,
            "id": batch_id,
            "state": state.value,
            "failure_code": failure_code,
        },
    )
    if result.rowcount != 1:
        raise DiscoveryNotFound(f"mutable discovery batch {batch_id}")
    row = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    assert row is not None
    return row


_OPERATION_COLUMNS = (
    "id, batch_id, workspace_id, source_key, provider_api_version, request_fingerprint, "
    "observation_window, provider_external_id, provider_operation_id, state, spend_outcome, "
    "next_poll_at, submitted_receipt_ref, final_receipt_ref, raw_request_artifact_key, "
    "raw_response_manifest_key, provider_units_reserved, provider_units_charged, "
    "cost_cents_charged, started_at, terminal_at"
)


async def put_discovery_operation(
    conn: AsyncConnection, *, workspace_id: str, operation: DiscoveryOperation
) -> DiscoveryOperation:
    if operation.workspace_id != workspace_id:
        raise ValueError("discovery operation workspace does not match repository scope")
    await conn.execute(
        text(
            """
            INSERT INTO discovery_operation (
                id, workspace_id, batch_id, source_key, provider_api_version,
                request_fingerprint, observation_window, provider_external_id,
                provider_operation_id, state, spend_outcome, next_poll_at,
                submitted_receipt_ref, final_receipt_ref, raw_request_artifact_key,
                raw_response_manifest_key, provider_units_reserved, provider_units_charged,
                cost_cents_charged, started_at, terminal_at
            ) VALUES (
                :id, :workspace_id, :batch_id, :source_key, :provider_api_version,
                :request_fingerprint, :observation_window, :provider_external_id,
                :provider_operation_id, CAST(:state AS discovery_operation_state),
                CAST(:spend_outcome AS discovery_spend_outcome), :next_poll_at,
                :submitted_receipt_ref, :final_receipt_ref, :raw_request_artifact_key,
                :raw_response_manifest_key, :provider_units_reserved, :provider_units_charged,
                :cost_cents_charged, :started_at, :terminal_at
            )
            ON CONFLICT (workspace_id, source_key, request_fingerprint, observation_window)
            DO NOTHING
            """
        ),
        _operation_params(operation),
    )
    row = await find_reusable_discovery_operation(
        conn,
        workspace_id=workspace_id,
        source_key=operation.source_key,
        request_fingerprint=operation.request_fingerprint,
        observation_window=operation.observation_window,
    )
    if row is None:
        raise DiscoveryNotFound(f"discovery operation {operation.operation_id}")
    if row.operation_id != operation.operation_id or row.batch_id != operation.batch_id:
        raise DiscoveryReplayConflict(
            "request fingerprint already belongs to a different durable discovery operation"
        )
    return row


async def update_discovery_operation(
    conn: AsyncConnection, *, workspace_id: str, operation: DiscoveryOperation
) -> DiscoveryOperation:
    if operation.workspace_id != workspace_id:
        raise ValueError("discovery operation workspace does not match repository scope")
    result = await conn.execute(
        text(
            """
            UPDATE discovery_operation
            SET provider_operation_id = :provider_operation_id,
                state = CAST(:state AS discovery_operation_state),
                spend_outcome = CAST(:spend_outcome AS discovery_spend_outcome),
                next_poll_at = :next_poll_at,
                submitted_receipt_ref = :submitted_receipt_ref,
                final_receipt_ref = :final_receipt_ref,
                raw_request_artifact_key = :raw_request_artifact_key,
                raw_response_manifest_key = :raw_response_manifest_key,
                provider_units_reserved = :provider_units_reserved,
                provider_units_charged = :provider_units_charged,
                cost_cents_charged = :cost_cents_charged,
                started_at = :started_at,
                terminal_at = :terminal_at,
                updated_at = now()
            WHERE workspace_id = :workspace_id AND id = :id AND batch_id = :batch_id
              AND source_key = :source_key AND request_fingerprint = :request_fingerprint
              AND observation_window = :observation_window AND state <> 'succeeded'
            """
        ),
        _operation_params(operation),
    )
    if result.rowcount != 1:
        existing = await get_discovery_operation(
            conn, workspace_id=workspace_id, operation_id=operation.operation_id
        )
        if existing == operation:
            return existing
        raise DiscoveryReplayConflict(f"terminal discovery operation {operation.operation_id}")
    row = await get_discovery_operation(
        conn, workspace_id=workspace_id, operation_id=operation.operation_id
    )
    assert row is not None
    return row


async def mark_discovery_operation_reconciled(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
    final_reconciliation: bool = True,
    pagination_exhausted: bool = True,
) -> None:
    result = await conn.execute(
        text(
            """
            UPDATE discovery_operation
            SET final_reconciled_at = CASE WHEN :final THEN now() ELSE final_reconciled_at END,
                pagination_exhausted_at = CASE
                    WHEN :pages THEN now() ELSE pagination_exhausted_at END,
                updated_at = now()
            WHERE workspace_id = :workspace_id AND id = :id
            """
        ),
        {
            "workspace_id": workspace_id,
            "id": operation_id,
            "final": final_reconciliation,
            "pages": pagination_exhausted,
        },
    )
    if result.rowcount != 1:
        raise DiscoveryNotFound(f"discovery operation {operation_id}")


async def get_discovery_operation(
    conn: AsyncConnection, *, workspace_id: str, operation_id: DiscoveryOperationId
) -> DiscoveryOperation | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM discovery_operation "
                    "WHERE workspace_id = :workspace_id AND id = :id"
                ),
                {"workspace_id": workspace_id, "id": operation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _operation_row(row) if row is not None else None


async def find_reusable_discovery_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    source_key: str,
    request_fingerprint: str,
    observation_window: str,
) -> DiscoveryOperation | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM discovery_operation "
                    "WHERE workspace_id = :workspace_id AND source_key = :source_key "
                    "AND request_fingerprint = :request_fingerprint "
                    "AND observation_window = :observation_window"
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
    return _operation_row(row) if row is not None else None


def _operation_params(operation: DiscoveryOperation) -> dict[str, object]:
    return {
        "id": operation.operation_id,
        "workspace_id": operation.workspace_id,
        "batch_id": operation.batch_id,
        "source_key": operation.source_key,
        "provider_api_version": operation.provider_api_version,
        "request_fingerprint": operation.request_fingerprint,
        "observation_window": operation.observation_window,
        "provider_external_id": operation.provider_external_id,
        "provider_operation_id": operation.provider_operation_id,
        "state": operation.state.value,
        "spend_outcome": operation.spend_outcome.value,
        "next_poll_at": operation.next_poll_at,
        "submitted_receipt_ref": operation.submitted_receipt_ref,
        "final_receipt_ref": operation.final_receipt_ref,
        "raw_request_artifact_key": operation.raw_request_artifact_key,
        "raw_response_manifest_key": operation.raw_response_manifest_key,
        "provider_units_reserved": operation.provider_units_reserved,
        "provider_units_charged": operation.provider_units_charged,
        "cost_cents_charged": operation.cost_cents_charged,
        "started_at": operation.started_at,
        "terminal_at": operation.terminal_at,
    }


def _operation_row(row: Any) -> DiscoveryOperation:
    return DiscoveryOperation.model_validate(
        {
            "operation_id": row["id"],
            "batch_id": row["batch_id"],
            "workspace_id": row["workspace_id"],
            "source_key": row["source_key"],
            "provider_api_version": row["provider_api_version"],
            "request_fingerprint": row["request_fingerprint"],
            "observation_window": row["observation_window"],
            "provider_external_id": row["provider_external_id"],
            "provider_operation_id": row["provider_operation_id"],
            "state": row["state"],
            "spend_outcome": row["spend_outcome"],
            "next_poll_at": row["next_poll_at"],
            "submitted_receipt_ref": row["submitted_receipt_ref"],
            "final_receipt_ref": row["final_receipt_ref"],
            "raw_request_artifact_key": row["raw_request_artifact_key"],
            "raw_response_manifest_key": row["raw_response_manifest_key"],
            "provider_units_reserved": row["provider_units_reserved"],
            "provider_units_charged": row["provider_units_charged"],
            "cost_cents_charged": row["cost_cents_charged"],
            "started_at": row["started_at"],
            "terminal_at": row["terminal_at"],
        }
    )


def _batch_row(row: Any) -> DiscoveryBatchRow:
    return DiscoveryBatchRow.model_validate(dict(row))


async def put_discovery_event(
    conn: AsyncConnection, *, workspace_id: str, event: DiscoveryProviderEvent
) -> UUID:
    """Persist an event idempotently without assuming delivery order."""

    batch_state = (
        await conn.execute(
            text(
                "SELECT batch.state::text FROM discovery_operation operation "
                "JOIN discovery_batch batch ON batch.id = operation.batch_id "
                "AND batch.workspace_id = operation.workspace_id "
                "WHERE operation.workspace_id = :workspace_id AND operation.id = :operation_id"
            ),
            {"workspace_id": workspace_id, "operation_id": event.operation_id},
        )
    ).scalar_one_or_none()
    if batch_state == DiscoveryBatchState.SEALED.value:
        event = DiscoveryProviderEvent.model_validate(
            {
                **event.model_dump(mode="python"),
                "processed_at": event.processed_at or event.received_at,
                "processing_disposition": DiscoveryEventDisposition.LATE_AFTER_SEAL,
            }
        )

    event_id = uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO discovery_provider_event (
                id, workspace_id, operation_id, provider_event_id, event_type,
                signature_verified, payload_artifact_key, provider_created_at, received_at,
                processed_at, processing_disposition
            ) VALUES (
                :id, :workspace_id, :operation_id, :provider_event_id, :event_type,
                :signature_verified, :payload_artifact_key, :provider_created_at, :received_at,
                :processed_at, CAST(:processing_disposition AS discovery_event_disposition)
            )
            ON CONFLICT (workspace_id, operation_id, provider_event_id) DO NOTHING
            """
        ),
        {
            "id": event_id,
            "workspace_id": workspace_id,
            "operation_id": event.operation_id,
            "provider_event_id": event.provider_event_id,
            "event_type": event.event_type,
            "signature_verified": event.signature_verified,
            "payload_artifact_key": event.payload_artifact_key,
            "provider_created_at": event.provider_created_at,
            "received_at": event.received_at,
            "processed_at": event.processed_at,
            "processing_disposition": event.processing_disposition.value,
        },
    )
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, event_type, signature_verified, payload_artifact_key,
                       provider_created_at, received_at, processed_at, processing_disposition
                FROM discovery_provider_event
                WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                  AND provider_event_id = :provider_event_id
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation_id": event.operation_id,
                    "provider_event_id": event.provider_event_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DiscoveryNotFound(f"discovery event {event.provider_event_id}")
    immutable_actual = (
        row["event_type"],
        row["signature_verified"],
        row["payload_artifact_key"],
        row["provider_created_at"],
    )
    immutable_expected = (
        event.event_type,
        event.signature_verified,
        event.payload_artifact_key,
        event.provider_created_at,
    )
    if immutable_actual != immutable_expected:
        raise DiscoveryReplayConflict(
            f"provider event {event.provider_event_id!r} was replayed with different content"
        )
    return cast(UUID, row["id"])


async def finish_discovery_event(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
    provider_event_id: str,
    disposition: DiscoveryEventDisposition,
) -> None:
    if disposition is DiscoveryEventDisposition.PENDING:
        raise ValueError("finish_discovery_event requires a terminal disposition")
    result = await conn.execute(
        text(
            """
            UPDATE discovery_provider_event
            SET processing_disposition = CAST(:disposition AS discovery_event_disposition),
                processed_at = COALESCE(processed_at, now())
            WHERE workspace_id = :workspace_id AND operation_id = :operation_id
              AND provider_event_id = :provider_event_id
              AND processing_disposition = 'pending'
            """
        ),
        {
            "workspace_id": workspace_id,
            "operation_id": operation_id,
            "provider_event_id": provider_event_id,
            "disposition": disposition.value,
        },
    )
    if result.rowcount == 0:
        row = (
            await conn.execute(
                text(
                    "SELECT processing_disposition FROM discovery_provider_event "
                    "WHERE workspace_id = :workspace_id AND operation_id = :operation_id "
                    "AND provider_event_id = :provider_event_id"
                ),
                {
                    "workspace_id": workspace_id,
                    "operation_id": operation_id,
                    "provider_event_id": provider_event_id,
                },
            )
        ).scalar_one_or_none()
        if row == DiscoveryEventDisposition.LATE_AFTER_SEAL.value:
            return
        if row != disposition.value:
            raise DiscoveryReplayConflict(
                f"provider event {provider_event_id!r} already has disposition {row!r}"
            )


async def put_discovery_page(
    conn: AsyncConnection, *, workspace_id: str, page: DiscoveryPageReceipt
) -> UUID:
    page_id = uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO discovery_page_receipt (
                id, workspace_id, operation_id, resource_kind, request_cursor_key, next_cursor,
                has_more, payload_artifact_key, payload_sha256, item_count, fetched_at
            ) VALUES (
                :id, :workspace_id, :operation_id,
                CAST(:resource_kind AS discovery_page_resource), :request_cursor_key, :next_cursor,
                :has_more, :payload_artifact_key, :payload_sha256, :item_count, :fetched_at
            )
            ON CONFLICT (workspace_id, operation_id, resource_kind, request_cursor_key) DO NOTHING
            """
        ),
        {
            "id": page_id,
            "workspace_id": workspace_id,
            "operation_id": page.operation_id,
            "resource_kind": page.resource_kind.value,
            "request_cursor_key": page.request_cursor,
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
            "payload_artifact_key": page.payload_artifact_key,
            "payload_sha256": page.payload_sha256,
            "item_count": page.item_count,
            "fetched_at": page.fetched_at,
        },
    )
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, next_cursor, has_more, payload_artifact_key, payload_sha256,
                       item_count, fetched_at
                FROM discovery_page_receipt
                WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                  AND resource_kind = CAST(:resource_kind AS discovery_page_resource)
                  AND request_cursor_key = :request_cursor_key
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation_id": page.operation_id,
                    "resource_kind": page.resource_kind.value,
                    "request_cursor_key": page.request_cursor,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DiscoveryNotFound(f"discovery page {page.operation_id}:{page.request_cursor}")
    actual = (
        row["next_cursor"],
        row["has_more"],
        row["payload_artifact_key"],
        row["payload_sha256"],
        row["item_count"],
    )
    expected = (
        page.next_cursor,
        page.has_more,
        page.payload_artifact_key,
        page.payload_sha256,
        page.item_count,
    )
    if actual != expected:
        raise DiscoveryReplayConflict(
            f"page cursor {page.request_cursor!r} was replayed with different content"
        )
    return cast(UUID, row["id"])


async def get_discovery_page(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
    resource_kind: str,
    request_cursor: str = FIRST_PAGE_CURSOR,
) -> DiscoveryPageReceipt | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT operation_id, resource_kind, request_cursor_key, next_cursor, has_more,
                       payload_artifact_key, payload_sha256, item_count, fetched_at
                FROM discovery_page_receipt
                WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                  AND resource_kind = CAST(:resource_kind AS discovery_page_resource)
                  AND request_cursor_key = :request_cursor
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation_id": operation_id,
                    "resource_kind": resource_kind,
                    "request_cursor": request_cursor,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    data = dict(row)
    data["request_cursor"] = data.pop("request_cursor_key")
    return DiscoveryPageReceipt.model_validate(data)


async def put_discovery_item(
    conn: AsyncConnection, *, workspace_id: str, item: DiscoveryItemSnapshot
) -> DiscoveryItemSnapshot:
    await conn.execute(
        text(
            """
            INSERT INTO discovery_item_snapshot (
                id, workspace_id, operation_id, provider_item_id, source_kind, source_id,
                raw_artifact_key, item_sha256, observed_at, normalization_state, normalized_at
            ) VALUES (
                :id, :workspace_id, :operation_id, :provider_item_id, :source_kind, :source_id,
                :raw_artifact_key, :item_sha256, :observed_at,
                CAST(:normalization_state AS discovery_normalization_state), :normalized_at
            )
            ON CONFLICT (workspace_id, operation_id, provider_item_id, item_sha256) DO NOTHING
            """
        ),
        {
            "id": item.item_snapshot_id,
            "workspace_id": workspace_id,
            "operation_id": item.operation_id,
            "provider_item_id": item.provider_item_id,
            "source_kind": item.source_kind,
            "source_id": item.source_id,
            "raw_artifact_key": item.raw_artifact_key,
            "item_sha256": item.item_sha256,
            "observed_at": item.observed_at,
            "normalization_state": item.normalization_state.value,
            "normalized_at": item.normalized_at,
        },
    )
    row = await get_discovery_item(
        conn, workspace_id=workspace_id, item_snapshot_id=item.item_snapshot_id
    )
    if row is None:
        existing = (
            await conn.execute(
                text(
                    """
                    SELECT id FROM discovery_item_snapshot
                    WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                      AND provider_item_id = :provider_item_id AND item_sha256 = :item_sha256
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation_id": item.operation_id,
                    "provider_item_id": item.provider_item_id,
                    "item_sha256": item.item_sha256,
                },
            )
        ).scalar_one_or_none()
        if existing is None:
            raise DiscoveryNotFound(f"discovery item {item.item_snapshot_id}")
        row = await get_discovery_item(
            conn,
            workspace_id=workspace_id,
            item_snapshot_id=DiscoveryItemSnapshotId(existing),
        )
    assert row is not None
    immutable_actual = (
        row.operation_id,
        row.provider_item_id,
        row.source_kind,
        row.source_id,
        row.raw_artifact_key,
        row.item_sha256,
        row.observed_at,
    )
    immutable_expected = (
        item.operation_id,
        item.provider_item_id,
        item.source_kind,
        item.source_id,
        item.raw_artifact_key,
        item.item_sha256,
        item.observed_at,
    )
    if immutable_actual != immutable_expected:
        raise DiscoveryReplayConflict(
            f"provider item {item.provider_item_id!r} was replayed with different content"
        )
    return row


async def normalize_discovery_item(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    item_snapshot_id: DiscoveryItemSnapshotId,
    normalized_at: datetime | None = None,
) -> DiscoveryItemSnapshot:
    result = await conn.execute(
        text(
            """
            UPDATE discovery_item_snapshot
            SET normalization_state = 'normalized', normalized_at = :normalized_at
            WHERE workspace_id = :workspace_id AND id = :id
              AND normalization_state IN ('raw', 'failed_retryable')
            """
        ),
        {
            "workspace_id": workspace_id,
            "id": item_snapshot_id,
            "normalized_at": normalized_at or datetime.now(UTC),
        },
    )
    row = await get_discovery_item(
        conn, workspace_id=workspace_id, item_snapshot_id=item_snapshot_id
    )
    if row is None:
        raise DiscoveryNotFound(f"discovery item {item_snapshot_id}")
    if (
        result.rowcount == 0
        and row.normalization_state is not DiscoveryNormalizationState.NORMALIZED
    ):
        raise DiscoveryReplayConflict(f"discovery item {item_snapshot_id} cannot be normalized")
    return row


async def get_discovery_item(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    item_snapshot_id: DiscoveryItemSnapshotId,
) -> DiscoveryItemSnapshot | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, operation_id, provider_item_id, source_kind, source_id,
                       raw_artifact_key, item_sha256, observed_at, normalization_state,
                       normalized_at
                FROM discovery_item_snapshot
                WHERE workspace_id = :workspace_id AND id = :id
                """
                ),
                {"workspace_id": workspace_id, "id": item_snapshot_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    data = dict(row)
    data["item_snapshot_id"] = data.pop("id")
    return DiscoveryItemSnapshot.model_validate(data)


async def link_discovery_page_item(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
    page_receipt_id: UUID,
    item_snapshot_id: DiscoveryItemSnapshotId,
    ordinal: int,
) -> None:
    try:
        await conn.execute(
            text(
                """
                INSERT INTO discovery_page_item (
                    workspace_id, operation_id, page_receipt_id, item_snapshot_id, ordinal
                ) VALUES (
                    :workspace_id, :operation_id, :page_receipt_id, :item_snapshot_id, :ordinal
                )
                ON CONFLICT (workspace_id, page_receipt_id, item_snapshot_id) DO NOTHING
                """
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "page_receipt_id": page_receipt_id,
                "item_snapshot_id": item_snapshot_id,
                "ordinal": ordinal,
            },
        )
    except Exception as exc:
        # The page+ordinal uniqueness is the important replay conflict; retain the DB exception as
        # cause while exposing a provider-neutral durable error.
        raise DiscoveryReplayConflict(
            f"page {page_receipt_id} ordinal {ordinal} already names another item"
        ) from exc


async def put_discovery_candidate_link(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    item_snapshot_id: DiscoveryItemSnapshotId,
    admission_status: DiscoveryCandidateAdmissionState,
    raw_name: str | None = None,
    candidate_domain: str | None = None,
    source_url: str | None = None,
    account_entity_id: EntityId | None = None,
    survivor_entity_id: EntityId | None = None,
    disposition_reason: str | None = None,
) -> DiscoveryCandidateLinkRow:
    _validate_candidate_shape(
        admission_status=admission_status,
        account_entity_id=account_entity_id,
        survivor_entity_id=survivor_entity_id,
        disposition_reason=disposition_reason,
    )
    existing = await get_discovery_candidate_link(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        item_snapshot_id=item_snapshot_id,
        for_update=True,
    )
    if existing is None:
        await conn.execute(
            text(
                """
                INSERT INTO discovery_candidate_link (
                    workspace_id, batch_id, item_snapshot_id, raw_name, candidate_domain,
                    source_url, admission_status, account_entity_id, survivor_entity_id,
                    disposition_reason
                )
                SELECT :workspace_id, :batch_id, item.id, :raw_name, :candidate_domain,
                       :source_url, CAST(:admission_status AS discovery_candidate_admission_state),
                       :account_entity_id, :survivor_entity_id, :disposition_reason
                FROM discovery_item_snapshot item
                JOIN discovery_operation operation
                  ON operation.id = item.operation_id AND operation.workspace_id = item.workspace_id
                WHERE item.workspace_id = :workspace_id AND item.id = :item_snapshot_id
                  AND operation.batch_id = :batch_id
                """
            ),
            {
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "item_snapshot_id": item_snapshot_id,
                "raw_name": raw_name,
                "candidate_domain": candidate_domain,
                "source_url": source_url,
                "admission_status": admission_status.value,
                "account_entity_id": account_entity_id,
                "survivor_entity_id": survivor_entity_id,
                "disposition_reason": disposition_reason,
            },
        )
    elif existing.admission_status is DiscoveryCandidateAdmissionState.PENDING:
        await conn.execute(
            text(
                """
                UPDATE discovery_candidate_link
                SET raw_name = COALESCE(:raw_name, raw_name),
                    candidate_domain = COALESCE(:candidate_domain, candidate_domain),
                    source_url = COALESCE(:source_url, source_url),
                    admission_status = CAST(
                        :admission_status AS discovery_candidate_admission_state
                    ),
                    account_entity_id = :account_entity_id,
                    survivor_entity_id = :survivor_entity_id,
                    disposition_reason = :disposition_reason,
                    updated_at = now()
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                  AND item_snapshot_id = :item_snapshot_id
                """
            ),
            {
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "item_snapshot_id": item_snapshot_id,
                "raw_name": raw_name,
                "candidate_domain": candidate_domain,
                "source_url": source_url,
                "admission_status": admission_status.value,
                "account_entity_id": account_entity_id,
                "survivor_entity_id": survivor_entity_id,
                "disposition_reason": disposition_reason,
            },
        )
    else:
        proposed = (
            admission_status,
            account_entity_id,
            survivor_entity_id,
            disposition_reason,
        )
        actual = (
            existing.admission_status,
            existing.account_entity_id,
            existing.survivor_entity_id,
            existing.disposition_reason,
        )
        if proposed != actual:
            raise DiscoveryReplayConflict(
                f"candidate {item_snapshot_id} already has terminal disposition"
            )
        return existing
    row = await get_discovery_candidate_link(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        item_snapshot_id=item_snapshot_id,
    )
    if row is None:
        raise DiscoveryNotFound(f"candidate item {item_snapshot_id} in batch {batch_id}")
    return row


async def get_discovery_candidate_link(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    item_snapshot_id: DiscoveryItemSnapshotId,
    for_update: bool = False,
) -> DiscoveryCandidateLinkRow | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT workspace_id, batch_id, item_snapshot_id, raw_name, candidate_domain,
                       source_url, admission_status, account_entity_id, survivor_entity_id,
                       disposition_reason, updated_at
                FROM discovery_candidate_link
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                  AND item_snapshot_id = :item_snapshot_id
                """
                    + suffix
                ),
                {
                    "workspace_id": workspace_id,
                    "batch_id": batch_id,
                    "item_snapshot_id": item_snapshot_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return DiscoveryCandidateLinkRow.model_validate(dict(row)) if row is not None else None


def _validate_candidate_shape(
    *,
    admission_status: DiscoveryCandidateAdmissionState,
    account_entity_id: EntityId | None,
    survivor_entity_id: EntityId | None,
    disposition_reason: str | None,
) -> None:
    if admission_status is DiscoveryCandidateAdmissionState.PENDING:
        valid = (
            account_entity_id is None and survivor_entity_id is None and disposition_reason is None
        )
    elif admission_status is DiscoveryCandidateAdmissionState.ADMITTED:
        valid = (
            account_entity_id is not None
            and survivor_entity_id == account_entity_id
            and disposition_reason is None
        )
    elif admission_status is DiscoveryCandidateAdmissionState.MERGED:
        valid = (
            account_entity_id is not None
            and survivor_entity_id is not None
            and survivor_entity_id != account_entity_id
            and bool(disposition_reason)
        )
    else:
        valid = (
            account_entity_id is None and survivor_entity_id is None and bool(disposition_reason)
        )
    if not valid:
        raise ValueError(f"invalid {admission_status.value} candidate disposition shape")


_FIELD_TERMINAL = frozenset(
    {
        DiscoveryFieldResolutionState.RESOLVED,
        DiscoveryFieldResolutionState.CONFIRMED_MISSING,
        DiscoveryFieldResolutionState.CONFLICT,
        DiscoveryFieldResolutionState.ACCEPTED_MISSING,
        DiscoveryFieldResolutionState.ACCOUNT_EXCLUDED,
        DiscoveryFieldResolutionState.BLOCKED_BY_POLICY,
    }
)


async def put_discovery_field_resolution(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    resolution: DiscoveryFieldResolution,
) -> DiscoveryFieldResolution:
    """Upsert one operational field decision and normalized claim/item edges atomically."""

    existing_row = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, state FROM discovery_field_resolution
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                  AND account_entity_id = :account_entity_id
                  AND logical_field_key = :logical_field_key
                FOR UPDATE
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "batch_id": resolution.batch_id,
                    "account_entity_id": resolution.account_entity_id,
                    "logical_field_key": str(resolution.logical_field_key),
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    resolution_id = cast(UUID, existing_row["id"]) if existing_row is not None else uuid4()
    if existing_row is not None:
        existing = await get_discovery_field_resolution(
            conn,
            workspace_id=workspace_id,
            batch_id=resolution.batch_id,
            account_entity_id=resolution.account_entity_id,
            logical_field_key=str(resolution.logical_field_key),
        )
        assert existing is not None
        if existing.state in _FIELD_TERMINAL:
            if existing == resolution:
                return existing
            raise DiscoveryReplayConflict(
                f"field {resolution.logical_field_key} already has a seal-terminal decision"
            )
        allowed = {
            DiscoveryFieldResolutionState.PENDING: set(DiscoveryFieldResolutionState),
            DiscoveryFieldResolutionState.REVIEW_REQUIRED: {
                DiscoveryFieldResolutionState.RESOLVED,
                DiscoveryFieldResolutionState.ACCEPTED_MISSING,
                DiscoveryFieldResolutionState.ACCOUNT_EXCLUDED,
                DiscoveryFieldResolutionState.BLOCKED_BY_POLICY,
            },
            DiscoveryFieldResolutionState.FAILED_RETRYABLE: set(DiscoveryFieldResolutionState),
            DiscoveryFieldResolutionState.FAILED_TERMINAL: {
                DiscoveryFieldResolutionState.ACCEPTED_MISSING,
                DiscoveryFieldResolutionState.ACCOUNT_EXCLUDED,
            },
        }
        previous = DiscoveryFieldResolutionState(str(existing_row["state"]))
        if resolution.state not in allowed.get(previous, set()):
            raise DiscoveryReplayConflict(
                f"field resolution cannot transition {previous.value} -> {resolution.state.value}"
            )

    # Validate claim ownership and winning membership before the operational row can reference it.
    if resolution.claim_ids:
        claims = (
            (
                await conn.execute(
                    text(
                        """
                    SELECT id, entity_id, workspace_id
                    FROM claim
                    WHERE id = ANY(:claim_ids)
                    """
                    ),
                    {"claim_ids": list(resolution.claim_ids)},
                )
            )
            .mappings()
            .all()
        )
        if len(claims) != len(resolution.claim_ids) or any(
            claim["entity_id"] != resolution.account_entity_id
            or claim["workspace_id"] not in (None, workspace_id)
            for claim in claims
        ):
            raise ValueError("discovery field claims must belong to the scoped account/workspace")

    params = {
        "id": resolution_id,
        "workspace_id": workspace_id,
        "batch_id": resolution.batch_id,
        "account_entity_id": resolution.account_entity_id,
        "logical_field_key": str(resolution.logical_field_key),
        "state": resolution.state.value,
        "winning_claim_id": resolution.winning_claim_id,
        "reason_code": resolution.reason_code,
        "review_disposition_ref": resolution.review_disposition_ref,
        "updated_at": resolution.updated_at,
    }
    if existing_row is None:
        await conn.execute(
            text(
                """
                INSERT INTO discovery_field_resolution (
                    id, workspace_id, batch_id, account_entity_id, logical_field_key, state,
                    winning_claim_id, reason_code, review_disposition_ref, updated_at
                ) VALUES (
                    :id, :workspace_id, :batch_id, :account_entity_id, :logical_field_key,
                    CAST(:state AS discovery_field_resolution_state), :winning_claim_id,
                    :reason_code, :review_disposition_ref, :updated_at
                )
                """
            ),
            params,
        )
    else:
        await conn.execute(
            text(
                """
                UPDATE discovery_field_resolution
                SET state = CAST(:state AS discovery_field_resolution_state),
                    winning_claim_id = :winning_claim_id, reason_code = :reason_code,
                    review_disposition_ref = :review_disposition_ref, updated_at = :updated_at
                WHERE workspace_id = :workspace_id AND id = :id
                """
            ),
            params,
        )
        await conn.execute(
            text(
                "DELETE FROM discovery_field_claim "
                "WHERE workspace_id = :workspace_id AND resolution_id = :id"
            ),
            {"workspace_id": workspace_id, "id": resolution_id},
        )
        await conn.execute(
            text(
                "DELETE FROM discovery_field_source_item "
                "WHERE workspace_id = :workspace_id AND resolution_id = :id"
            ),
            {"workspace_id": workspace_id, "id": resolution_id},
        )
    for claim_id in resolution.claim_ids:
        await conn.execute(
            text(
                "INSERT INTO discovery_field_claim (workspace_id, resolution_id, claim_id) "
                "VALUES (:workspace_id, :resolution_id, :claim_id)"
            ),
            {
                "workspace_id": workspace_id,
                "resolution_id": resolution_id,
                "claim_id": claim_id,
            },
        )
    for item_id in resolution.source_item_ids:
        await conn.execute(
            text(
                "INSERT INTO discovery_field_source_item "
                "(workspace_id, resolution_id, item_snapshot_id) "
                "VALUES (:workspace_id, :resolution_id, :item_id)"
            ),
            {
                "workspace_id": workspace_id,
                "resolution_id": resolution_id,
                "item_id": item_id,
            },
        )
    row = await get_discovery_field_resolution(
        conn,
        workspace_id=workspace_id,
        batch_id=resolution.batch_id,
        account_entity_id=resolution.account_entity_id,
        logical_field_key=str(resolution.logical_field_key),
    )
    assert row is not None
    return row


async def get_discovery_field_resolution(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    account_entity_id: EntityId,
    logical_field_key: str,
) -> DiscoveryFieldResolution | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, batch_id, account_entity_id, logical_field_key, state,
                       winning_claim_id, reason_code, review_disposition_ref, updated_at
                FROM discovery_field_resolution
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                  AND account_entity_id = :account_entity_id
                  AND logical_field_key = :logical_field_key
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "batch_id": batch_id,
                    "account_entity_id": account_entity_id,
                    "logical_field_key": logical_field_key,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    claim_ids = (
        (
            await conn.execute(
                text(
                    "SELECT claim_id FROM discovery_field_claim "
                    "WHERE workspace_id = :workspace_id AND resolution_id = :id ORDER BY claim_id"
                ),
                {"workspace_id": workspace_id, "id": row["id"]},
            )
        )
        .scalars()
        .all()
    )
    item_ids = (
        (
            await conn.execute(
                text(
                    "SELECT item_snapshot_id FROM discovery_field_source_item "
                    "WHERE workspace_id = :workspace_id AND resolution_id = :id "
                    "ORDER BY item_snapshot_id"
                ),
                {"workspace_id": workspace_id, "id": row["id"]},
            )
        )
        .scalars()
        .all()
    )
    data = dict(row)
    data.pop("id")
    return DiscoveryFieldResolution.model_validate(
        {**data, "claim_ids": tuple(claim_ids), "source_item_ids": tuple(item_ids)}
    )


async def bind_discovery_artifact_subject(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    artifact_key_value: str,
    subject_kind: str,
    subject_entity_id: EntityId,
    reference_kind: str,
    reference_id: str,
) -> UUID:
    if subject_kind not in {"account", "contact"}:
        raise ValueError("discovery artifact subject_kind must be account or contact")
    table = "account_entity" if subject_kind == "account" else "contact_entity"
    exists = (
        await conn.execute(
            text(f"SELECT 1 FROM {table} WHERE id = :id AND workspace_id = :workspace_id"),
            {"id": subject_entity_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    if exists is None:
        raise DiscoveryNotFound(
            f"{subject_kind} subject {subject_entity_id} in workspace {workspace_id}"
        )
    link_id = uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO discovery_artifact_subject (
                id, workspace_id, artifact_key, subject_kind, subject_entity_id,
                reference_kind, reference_id
            ) VALUES (
                :id, :workspace_id, :artifact_key, :subject_kind, :subject_entity_id,
                :reference_kind, :reference_id
            )
            ON CONFLICT (
                workspace_id, artifact_key, subject_kind, subject_entity_id,
                reference_kind, reference_id
            ) DO UPDATE SET tombstoned_at = NULL
            RETURNING id
            """
        ),
        {
            "id": link_id,
            "workspace_id": workspace_id,
            "artifact_key": artifact_key_value,
            "subject_kind": subject_kind,
            "subject_entity_id": subject_entity_id,
            "reference_kind": reference_kind,
            "reference_id": reference_id,
        },
    )
    row_id = (
        await conn.execute(
            text(
                """
                SELECT id FROM discovery_artifact_subject
                WHERE workspace_id = :workspace_id AND artifact_key = :artifact_key
                  AND subject_kind = :subject_kind AND subject_entity_id = :subject_entity_id
                  AND reference_kind = :reference_kind AND reference_id = :reference_id
                """
            ),
            {
                "workspace_id": workspace_id,
                "artifact_key": artifact_key_value,
                "subject_kind": subject_kind,
                "subject_entity_id": subject_entity_id,
                "reference_kind": reference_kind,
                "reference_id": reference_id,
            },
        )
    ).scalar_one()
    return cast(UUID, row_id)


async def index_account_discovery_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    account_entity_id: EntityId,
) -> tuple[str, ...]:
    """Index every raw/receipt artifact in the account's source operations for DSAR reachability.

    Shared page/event artifacts are conservatively linked to every account represented by the
    operation.  This may over-enumerate during erasure, but it cannot miss a raw payload containing
    the subject.
    """

    artifacts = (
        (
            await conn.execute(
                text(
                    """
                WITH subject_ops AS (
                    SELECT DISTINCT item.operation_id
                    FROM discovery_candidate_link candidate
                    JOIN discovery_item_snapshot item
                      ON item.workspace_id = candidate.workspace_id
                     AND item.id = candidate.item_snapshot_id
                    WHERE candidate.workspace_id = :workspace_id
                      AND candidate.batch_id = :batch_id
                      AND candidate.survivor_entity_id = :account_entity_id
                ), refs AS (
                    SELECT operation.id::text AS reference_id, 'operation'::text AS reference_kind,
                           artifact_key
                    FROM discovery_operation operation
                    JOIN subject_ops ON subject_ops.operation_id = operation.id
                    CROSS JOIN LATERAL unnest(ARRAY[
                        operation.submitted_receipt_ref,
                        operation.final_receipt_ref,
                        operation.raw_request_artifact_key,
                        operation.raw_response_manifest_key
                    ]) artifact_key
                    WHERE artifact_key IS NOT NULL
                    UNION ALL
                    SELECT event.id::text, 'event', event.payload_artifact_key
                    FROM discovery_provider_event event
                    JOIN subject_ops ON subject_ops.operation_id = event.operation_id
                    UNION ALL
                    SELECT page.id::text, 'page', page.payload_artifact_key
                    FROM discovery_page_receipt page
                    JOIN subject_ops ON subject_ops.operation_id = page.operation_id
                    UNION ALL
                    SELECT item.id::text, 'item', item.raw_artifact_key
                    FROM discovery_item_snapshot item
                    JOIN subject_ops ON subject_ops.operation_id = item.operation_id
                )
                SELECT DISTINCT reference_id, reference_kind, artifact_key FROM refs
                ORDER BY artifact_key, reference_kind, reference_id
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "batch_id": batch_id,
                    "account_entity_id": account_entity_id,
                },
            )
        )
        .mappings()
        .all()
    )
    for row in artifacts:
        await bind_discovery_artifact_subject(
            conn,
            workspace_id=workspace_id,
            artifact_key_value=str(row["artifact_key"]),
            subject_kind="account",
            subject_entity_id=account_entity_id,
            reference_kind=str(row["reference_kind"]),
            reference_id=str(row["reference_id"]),
        )
    return tuple(sorted({str(row["artifact_key"]) for row in artifacts}))


async def enumerate_discovery_subject_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: str,
    subject_entity_id: EntityId,
    limit: int = 500,
) -> tuple[DiscoveryArtifactSubjectRow, ...]:
    if not 1 <= limit <= 500:
        raise ValueError("discovery subject artifact limit must be between 1 and 500")
    rows = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, workspace_id, artifact_key, subject_kind, subject_entity_id,
                       reference_kind, reference_id, created_at, tombstoned_at
                FROM discovery_artifact_subject
                WHERE workspace_id = :workspace_id AND subject_kind = :subject_kind
                  AND subject_entity_id = :subject_entity_id AND tombstoned_at IS NULL
                ORDER BY created_at, id
                LIMIT :limit
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "subject_kind": subject_kind,
                    "subject_entity_id": subject_entity_id,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(DiscoveryArtifactSubjectRow.model_validate(dict(row)) for row in rows)


async def tombstone_discovery_subject_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: str,
    subject_entity_id: EntityId,
) -> tuple[str, ...]:
    """Tombstone subject edges and mark now-unshared/unclaimed blobs for post-commit purge."""

    keys = (
        (
            await conn.execute(
                text(
                    """
                UPDATE discovery_artifact_subject
                SET tombstoned_at = COALESCE(tombstoned_at, now())
                WHERE workspace_id = :workspace_id AND subject_kind = :subject_kind
                  AND subject_entity_id = :subject_entity_id AND tombstoned_at IS NULL
                RETURNING artifact_key
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "subject_kind": subject_kind,
                    "subject_entity_id": subject_entity_id,
                },
            )
        )
        .scalars()
        .all()
    )
    marked: list[str] = []
    for key in sorted(set(keys)):
        other_subject = (
            await conn.execute(
                text(
                    "SELECT 1 FROM discovery_artifact_subject "
                    "WHERE workspace_id = :workspace_id AND artifact_key = :key "
                    "AND tombstoned_at IS NULL LIMIT 1"
                ),
                {"workspace_id": workspace_id, "key": key},
            )
        ).scalar_one_or_none()
        if other_subject is None and await erase_if_unreferenced(conn, str(key)):
            marked.append(str(key))
    return tuple(marked)


async def schedule_discovery_wake(
    conn: AsyncConnection, *, workspace_id: str, request: DiscoveryWakeRequest
) -> UUID:
    if request.workspace_id != workspace_id:
        raise ValueError("discovery wake workspace does not match repository scope")
    wake_id = uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO discovery_wake_outbox (
                id, workspace_id, project_run_id, batch_id, operation_id, reason,
                available_at, dedupe_key
            )
            SELECT :id, :workspace_id, :project_run_id, batch.id, :operation_id, :reason,
                   :available_at, :dedupe_key
            FROM discovery_batch batch
            WHERE batch.id = :batch_id AND batch.workspace_id = :workspace_id
              AND batch.project_run_id = :project_run_id
            ON CONFLICT (workspace_id, dedupe_key) DO NOTHING
            """
        ),
        {
            "id": wake_id,
            "workspace_id": workspace_id,
            "project_run_id": request.project_run_id,
            "batch_id": request.discovery_batch_id,
            "operation_id": request.operation_id,
            "reason": request.reason.value,
            "available_at": request.available_at,
            "dedupe_key": request.dedupe_key,
        },
    )
    existing = (
        (
            await conn.execute(
                text(
                    "SELECT id, batch_id, operation_id, reason, available_at "
                    "FROM discovery_wake_outbox "
                    "WHERE workspace_id = :workspace_id AND dedupe_key = :dedupe_key"
                ),
                {"workspace_id": workspace_id, "dedupe_key": request.dedupe_key},
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is None:
        raise DiscoveryNotFound(f"discovery batch {request.discovery_batch_id}")
    expected = (
        request.discovery_batch_id,
        request.operation_id,
        request.reason.value,
        request.available_at,
    )
    actual = (
        existing["batch_id"],
        existing["operation_id"],
        existing["reason"],
        existing["available_at"],
    )
    if expected != actual:
        raise DiscoveryReplayConflict(f"wake dedupe key {request.dedupe_key!r} changed")
    return cast(UUID, existing["id"])


async def claim_due_discovery_wakes(
    conn: AsyncConnection, *, limit: int = 100, now: datetime | None = None
) -> tuple[DiscoveryWakeRow, ...]:
    if not 1 <= limit <= 100:
        raise ValueError("discovery wake claim limit must be between 1 and 100")
    rows = (
        (
            await conn.execute(
                text(
                    """
                WITH due AS (
                    SELECT id FROM discovery_wake_outbox
                    WHERE processed_at IS NULL AND claimed_at IS NULL AND available_at <= :now
                    ORDER BY available_at, id
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE discovery_wake_outbox wake
                SET claimed_at = :now
                FROM due
                WHERE wake.id = due.id
                RETURNING wake.id, wake.workspace_id, wake.project_run_id, wake.batch_id,
                          wake.operation_id, wake.reason, wake.available_at, wake.dedupe_key,
                          wake.created_at, wake.claimed_at, wake.processed_at
                """
                ),
                {"now": now or datetime.now(UTC), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return tuple(DiscoveryWakeRow.model_validate(dict(row)) for row in rows)


async def complete_discovery_wake(
    conn: AsyncConnection, *, workspace_id: str, wake_id: UUID
) -> None:
    result = await conn.execute(
        text(
            """
            UPDATE discovery_wake_outbox
            SET processed_at = COALESCE(processed_at, now())
            WHERE id = :id AND workspace_id = :workspace_id AND claimed_at IS NOT NULL
            """
        ),
        {"id": wake_id, "workspace_id": workspace_id},
    )
    if result.rowcount != 1:
        raise DiscoveryNotFound(f"claimed discovery wake {wake_id}")


class DbDiscoveryWakeScheduler:
    """Transactional-outbox implementation of the core scheduler seam."""

    def __init__(self, *, workspace_id: str, conn_factory: ConnFactory = transaction) -> None:
        self._workspace_id = workspace_id
        self._conn_factory = conn_factory

    async def schedule(self, request: DiscoveryWakeRequest) -> str:
        async with self._conn_factory() as conn:
            wake_id = await schedule_discovery_wake(
                conn, workspace_id=self._workspace_id, request=request
            )
        return str(wake_id)


_WAKE_SCHEDULER_CONFORMS: type[DiscoveryWakeScheduler] = DbDiscoveryWakeScheduler
assert isinstance(DbDiscoveryWakeScheduler(workspace_id="contract-only"), DiscoveryWakeScheduler)


async def reconcile_discovery_batch_costs(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> DiscoveryBatchRow:
    """Fold operation reservations/settlement into the batch's authoritative counters."""

    result = await conn.execute(
        text(
            """
            UPDATE discovery_batch batch
            SET provider_units_reserved = totals.reserved,
                provider_units_charged = totals.charged,
                cost_cents_charged = totals.cost,
                updated_at = now()
            FROM (
                SELECT COALESCE(sum(provider_units_reserved), 0) AS reserved,
                       COALESCE(sum(provider_units_charged), 0) AS charged,
                       COALESCE(sum(cost_cents_charged), 0) AS cost
                FROM discovery_operation
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
            ) totals
            WHERE batch.workspace_id = :workspace_id AND batch.id = :batch_id
              AND batch.state <> 'sealed'
            """
        ),
        {"workspace_id": workspace_id, "batch_id": batch_id},
    )
    if result.rowcount != 1:
        raise DiscoveryNotFound(f"mutable discovery batch {batch_id}")
    row = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    assert row is not None
    return row


_READINESS_SQL = text(
    """
    WITH target AS (
        SELECT batch.*, plan.plan_json, plan.plan_sha256, plan.plan_version,
               plan.provider_policy_version, plan.field_policy_version,
               plan.provider_contract_version
        FROM discovery_batch batch
        JOIN discovery_plan plan
          ON plan.id = batch.discovery_plan_id AND plan.workspace_id = batch.workspace_id
        WHERE batch.workspace_id = :workspace_id AND batch.id = :batch_id
    ), operations AS (
        SELECT operation.*
        FROM discovery_operation operation
        WHERE operation.workspace_id = :workspace_id AND operation.batch_id = :batch_id
    ), admitted AS (
        SELECT DISTINCT candidate.survivor_entity_id AS account_entity_id
        FROM discovery_candidate_link candidate
        WHERE candidate.workspace_id = :workspace_id AND candidate.batch_id = :batch_id
          AND candidate.admission_status IN ('admitted', 'merged')
    ), required_fields AS (
        SELECT required.value AS logical_field_key
        FROM target
        CROSS JOIN LATERAL jsonb_array_elements_text(
            target.plan_json -> 'required_account_fields'
        ) required(value)
    )
    SELECT
        EXISTS (
            SELECT 1 FROM target
            JOIN project_run run
              ON run.id = target.project_run_id
             AND run.workspace_id = target.workspace_id
             AND run.project_id = target.project_id
            WHERE run.icp_key = target.icp_key AND run.icp_version = target.icp_version
              AND (target.plan_json ->> 'workspace_id') = target.workspace_id
              AND (target.plan_json ->> 'project_id') = target.project_id
              AND (target.plan_json ->> 'project_run_id') = target.project_run_id::text
              AND (target.plan_json ->> 'icp_key') = target.icp_key
              AND (target.plan_json ->> 'icp_version')::integer = target.icp_version
        ) AS plan_lineage_matches,

        COALESCE((SELECT count(*) FROM operations), 0) > 0
        AND (SELECT count(*) FROM operations) =
            (SELECT jsonb_array_length(plan_json -> 'searches') FROM target)
        AND NOT EXISTS (
            SELECT 1 FROM operations
            WHERE state NOT IN ('succeeded', 'accepted_terminal_failure')
        ) AS operations_terminal,

        NOT EXISTS (
            SELECT 1 FROM operations operation
            WHERE operation.submitted_receipt_ref IS NULL
               OR operation.final_receipt_ref IS NULL
               OR operation.raw_request_artifact_key IS NULL
               OR (operation.state = 'succeeded'
                   AND operation.raw_response_manifest_key IS NULL)
               OR NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.storage_key = operation.submitted_receipt_ref
                      AND artifact.workspace_id = :workspace_id
                      AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
               )
               OR NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.storage_key = operation.final_receipt_ref
                      AND artifact.workspace_id = :workspace_id
                      AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
               )
               OR NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.storage_key = operation.raw_request_artifact_key
                      AND artifact.workspace_id = :workspace_id
                      AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
               )
               OR (operation.state = 'succeeded' AND NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.storage_key = operation.raw_response_manifest_key
                      AND artifact.workspace_id = :workspace_id
                      AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
               ))
        ) AS dispatch_receipts_complete,

        NOT EXISTS (
            SELECT 1 FROM discovery_provider_event event
            WHERE event.workspace_id = :workspace_id
              AND event.operation_id IN (SELECT id FROM operations)
              AND (event.processing_disposition = 'pending' OR event.processed_at IS NULL)
        ) AS provider_events_accounted,

        NOT EXISTS (
            SELECT 1 FROM operations WHERE final_reconciled_at IS NULL
        ) AS final_reconciliation_complete,

        NOT EXISTS (
            SELECT 1 FROM operations WHERE pagination_exhausted_at IS NULL
        )
        AND NOT EXISTS (
            SELECT 1 FROM operations operation
            WHERE operation.state = 'succeeded'
              AND NOT EXISTS (
                SELECT 1 FROM discovery_page_receipt page
                WHERE page.workspace_id = :workspace_id
                  AND page.operation_id = operation.id
                  AND page.resource_kind = 'items' AND NOT page.has_more
            )
        )
        AND NOT EXISTS (
            SELECT 1 FROM discovery_page_receipt page
            WHERE page.workspace_id = :workspace_id
              AND page.operation_id IN (SELECT id FROM operations)
              AND page.has_more
              AND NOT EXISTS (
                  SELECT 1 FROM discovery_page_receipt next_page
                  WHERE next_page.workspace_id = page.workspace_id
                    AND next_page.operation_id = page.operation_id
                    AND next_page.resource_kind = page.resource_kind
                    AND next_page.request_cursor_key = page.next_cursor
              )
        ) AS pagination_exhausted,

        NOT EXISTS (
            SELECT 1 FROM discovery_page_receipt page
            WHERE page.workspace_id = :workspace_id
              AND page.operation_id IN (SELECT id FROM operations)
              AND page.item_count <> (
                  SELECT count(*) FROM discovery_page_item page_item
                  WHERE page_item.workspace_id = page.workspace_id
                    AND page_item.page_receipt_id = page.id
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM discovery_item_snapshot item
            LEFT JOIN artifact
              ON artifact.storage_key = item.raw_artifact_key
             AND artifact.workspace_id = item.workspace_id
            WHERE item.workspace_id = :workspace_id
              AND item.operation_id IN (SELECT id FROM operations)
              AND (
                  item.normalization_state <> 'normalized'
                  OR item.normalized_at IS NULL
                  OR artifact.storage_key IS NULL
                  OR artifact.erased_at IS NOT NULL
                  OR artifact.purged_at IS NOT NULL
                  OR NOT EXISTS (
                      SELECT 1 FROM discovery_page_item page_item
                      WHERE page_item.workspace_id = item.workspace_id
                        AND page_item.item_snapshot_id = item.id
                  )
              )
        ) AS items_materialized,

        NOT EXISTS (
            SELECT 1 FROM discovery_item_snapshot item
            WHERE item.workspace_id = :workspace_id
              AND item.operation_id IN (SELECT id FROM operations)
              AND NOT EXISTS (
                  SELECT 1 FROM discovery_candidate_link candidate
                  WHERE candidate.workspace_id = item.workspace_id
                    AND candidate.batch_id = :batch_id
                    AND candidate.item_snapshot_id = item.id
                    AND candidate.admission_status IN ('admitted', 'merged', 'excluded')
              )
        ) AS candidate_identities_terminal,

        NOT EXISTS (
            SELECT 1 FROM admitted
            LEFT JOIN account_entity account
              ON account.id = admitted.account_entity_id
             AND account.workspace_id = :workspace_id
            WHERE account.id IS NULL OR length(btrim(account.canonical_name)) = 0
               OR account.primary_domain IS NULL
               OR length(btrim(account.primary_domain)) = 0
        ) AS hard_identities_complete,

        NOT EXISTS (
            SELECT 1 FROM admitted CROSS JOIN required_fields
            WHERE NOT EXISTS (
                SELECT 1 FROM discovery_field_resolution resolution
                WHERE resolution.workspace_id = :workspace_id
                  AND resolution.batch_id = :batch_id
                  AND resolution.account_entity_id = admitted.account_entity_id
                  AND resolution.logical_field_key = required_fields.logical_field_key
                  AND resolution.state IN (
                      'resolved', 'confirmed_missing', 'conflict', 'accepted_missing',
                      'account_excluded', 'blocked_by_policy'
                  )
            )
        ) AS required_fields_terminal,

        NOT EXISTS (
            SELECT 1 FROM discovery_field_resolution resolution
            WHERE resolution.workspace_id = :workspace_id
              AND resolution.batch_id = :batch_id
              AND (
                  (resolution.state = 'resolved' AND (
                      resolution.winning_claim_id IS NULL
                      OR NOT EXISTS (
                          SELECT 1 FROM discovery_field_claim field_claim
                          JOIN claim
                            ON claim.id = field_claim.claim_id
                           AND claim.entity_id = resolution.account_entity_id
                           AND (claim.workspace_id IS NULL
                                OR claim.workspace_id = :workspace_id)
                          WHERE field_claim.workspace_id = :workspace_id
                            AND field_claim.resolution_id = resolution.id
                            AND field_claim.claim_id = resolution.winning_claim_id
                      )
                  ))
                  OR (resolution.state IN (
                          'confirmed_missing', 'conflict', 'accepted_missing',
                          'account_excluded', 'blocked_by_policy'
                      ) AND resolution.reason_code IS NULL)
              )
        ) AS claims_or_dispositions_complete,

        NOT EXISTS (
            SELECT 1 FROM discovery_candidate_link candidate
            LEFT JOIN account_entity survivor
              ON survivor.id = candidate.survivor_entity_id
             AND survivor.workspace_id = candidate.workspace_id
            LEFT JOIN account_entity source_account
              ON source_account.id = candidate.account_entity_id
             AND source_account.workspace_id = candidate.workspace_id
            WHERE candidate.workspace_id = :workspace_id
              AND candidate.batch_id = :batch_id
              AND (
                  candidate.admission_status = 'pending'
                  OR (candidate.admission_status IN ('admitted', 'merged') AND (
                      survivor.id IS NULL OR survivor.merged_into IS NOT NULL
                      OR (candidate.admission_status = 'admitted'
                          AND source_account.id <> survivor.id)
                      OR (candidate.admission_status = 'merged'
                          AND source_account.merged_into <> survivor.id)
                  ))
              )
        ) AS survivor_links_complete,

        EXISTS (SELECT 1 FROM target)
        AND (SELECT provider_units_charged FROM target) =
            (SELECT COALESCE(sum(provider_units_charged), 0) FROM operations)
        AND (SELECT cost_cents_charged FROM target) =
            (SELECT COALESCE(sum(cost_cents_charged), 0) FROM operations)
        AND NOT EXISTS (
            SELECT 1 FROM operations WHERE spend_outcome IN ('unknown', 'not_dispatched')
        ) AS spend_reconciled,

        CAST(:account_manifest AS text) IS NOT NULL
        AND CAST(:raw_manifest AS text) IS NOT NULL
        AND CAST(:claim_manifest AS text) IS NOT NULL
        AND CAST(:coverage_ref AS text) IS NOT NULL
        AND NOT EXISTS (
            SELECT required.key
            FROM (VALUES
                (CAST(:account_manifest AS text)),
                (CAST(:raw_manifest AS text)),
                (CAST(:claim_manifest AS text)),
                (CAST(:coverage_ref AS text))
            ) required(key)
            WHERE NOT EXISTS (
                SELECT 1 FROM artifact
                WHERE artifact.storage_key = required.key
                  AND artifact.workspace_id = :workspace_id
                  AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
            )
        )
        AND EXISTS (
            SELECT 1 FROM artifact
            WHERE artifact.storage_key = CAST(:account_manifest AS text)
              AND artifact.workspace_id = :workspace_id
              AND artifact.content_sha256 = CAST(:account_manifest_sha256 AS text)
              AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
        ) AS final_manifests_exist
    """
)


async def read_discovery_seal_readiness(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    draft: DiscoverySealDraft | None = None,
) -> DiscoverySealReadiness:
    params = {
        "workspace_id": workspace_id,
        "batch_id": batch_id,
        "account_manifest": draft.account_manifest_artifact_key if draft else None,
        "account_manifest_sha256": draft.account_manifest_sha256 if draft else None,
        "raw_manifest": draft.raw_artifact_manifest_key if draft else None,
        "claim_manifest": draft.claim_id_manifest_key if draft else None,
        "coverage_ref": draft.coverage_report_ref if draft else None,
    }
    row = (await conn.execute(_READINESS_SQL, params)).mappings().one()
    return DiscoverySealReadiness.model_validate(dict(row))


_SEAL_COLUMNS = (
    "batch_id, project_run_id, icp_key, icp_version, discovery_plan_id, plan_sha256, sealed_at, "
    "account_count, account_manifest_artifact_key, account_manifest_sha256, "
    "excluded_candidate_count, field_resolution_summary, provider_operation_ids, "
    "request_fingerprints, raw_artifact_manifest_key, claim_id_manifest_key, "
    "provider_units_charged, cost_cents_charged, coverage_report_ref, seal_sha256"
)


async def get_discovery_batch_seal(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> DiscoveryBatchSeal | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_SEAL_COLUMNS} FROM discovery_batch_seal "
                    "WHERE workspace_id = :workspace_id AND batch_id = :batch_id"
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    data = dict(row)
    data["field_resolution_summary"] = decode_jsonb(data["field_resolution_summary"])
    data["provider_operation_ids"] = tuple(decode_jsonb(data["provider_operation_ids"]))
    data["request_fingerprints"] = tuple(decode_jsonb(data["request_fingerprints"]))
    return DiscoveryBatchSeal.model_validate(data)


async def seal_discovery_batch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    draft: DiscoverySealDraft,
) -> DiscoveryBatchSeal:
    """Lock, derive all fourteen predicates, and insert the immutable seal in one transaction."""

    locked = (
        await conn.execute(
            text(
                "SELECT id FROM discovery_batch "
                "WHERE workspace_id = :workspace_id AND id = :batch_id FOR UPDATE"
            ),
            {"workspace_id": workspace_id, "batch_id": batch_id},
        )
    ).scalar_one_or_none()
    if locked is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")

    existing = await get_discovery_batch_seal(conn, workspace_id=workspace_id, batch_id=batch_id)
    if existing is not None:
        _assert_seal_draft_matches(existing, draft)
        return existing

    readiness = await read_discovery_seal_readiness(
        conn, workspace_id=workspace_id, batch_id=batch_id, draft=draft
    )
    decision = evaluate_discovery_seal(readiness)
    if not decision.sealable:
        raise DiscoverySealBlocked(decision.blockers)

    metadata = (
        (
            await conn.execute(
                text(
                    """
                WITH admitted AS (
                    SELECT DISTINCT survivor_entity_id AS account_entity_id
                    FROM discovery_candidate_link
                    WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                      AND admission_status IN ('admitted', 'merged')
                ), operation_manifest AS (
                    SELECT COALESCE(jsonb_agg(id::text ORDER BY id::text), '[]'::jsonb) AS ids,
                           COALESCE(jsonb_agg(request_fingerprint ORDER BY id::text), '[]'::jsonb)
                               AS fingerprints
                    FROM discovery_operation
                    WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                ), field_summary AS (
                    SELECT COALESCE(jsonb_object_agg(state, count), '{}'::jsonb) AS summary
                    FROM (
                        SELECT state::text AS state, count(*)::integer AS count
                        FROM discovery_field_resolution
                        WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                        GROUP BY state
                    ) grouped
                )
                SELECT batch.project_run_id, batch.icp_key, batch.icp_version,
                       batch.discovery_plan_id, plan.plan_sha256,
                       batch.provider_units_charged, batch.cost_cents_charged,
                       (SELECT count(*) FROM admitted) AS account_count,
                       (SELECT count(*) FROM discovery_candidate_link
                        WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                          AND admission_status = 'excluded') AS excluded_candidate_count,
                       operation_manifest.ids AS provider_operation_ids,
                       operation_manifest.fingerprints AS request_fingerprints,
                       field_summary.summary AS field_resolution_summary,
                       transaction_timestamp() AS sealed_at
                FROM discovery_batch batch
                JOIN discovery_plan plan
                  ON plan.id = batch.discovery_plan_id AND plan.workspace_id = batch.workspace_id
                CROSS JOIN operation_manifest
                CROSS JOIN field_summary
                WHERE batch.workspace_id = :workspace_id AND batch.id = :batch_id
                """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .one()
    )
    seal_without_hash = {
        "batch_id": batch_id,
        "project_run_id": metadata["project_run_id"],
        "icp_key": metadata["icp_key"],
        "icp_version": metadata["icp_version"],
        "discovery_plan_id": metadata["discovery_plan_id"],
        "plan_sha256": metadata["plan_sha256"],
        "sealed_at": metadata["sealed_at"],
        "account_count": metadata["account_count"],
        "account_manifest_artifact_key": draft.account_manifest_artifact_key,
        "account_manifest_sha256": draft.account_manifest_sha256,
        "excluded_candidate_count": metadata["excluded_candidate_count"],
        "field_resolution_summary": decode_jsonb(metadata["field_resolution_summary"]),
        "provider_operation_ids": tuple(decode_jsonb(metadata["provider_operation_ids"])),
        "request_fingerprints": tuple(decode_jsonb(metadata["request_fingerprints"])),
        "raw_artifact_manifest_key": draft.raw_artifact_manifest_key,
        "claim_id_manifest_key": draft.claim_id_manifest_key,
        "provider_units_charged": metadata["provider_units_charged"],
        "cost_cents_charged": metadata["cost_cents_charged"],
        "coverage_report_ref": draft.coverage_report_ref,
    }
    seal_sha = _seal_sha256(seal_without_hash)
    seal = DiscoveryBatchSeal.model_validate({**seal_without_hash, "seal_sha256": seal_sha})
    await conn.execute(
        text(
            """
            INSERT INTO discovery_batch_seal (
                batch_id, workspace_id, seal_sha256, project_run_id, icp_key, icp_version,
                discovery_plan_id, plan_sha256, sealed_at, account_count,
                account_manifest_artifact_key, account_manifest_sha256,
                excluded_candidate_count, field_resolution_summary, provider_operation_ids,
                request_fingerprints, raw_artifact_manifest_key, claim_id_manifest_key,
                provider_units_charged, cost_cents_charged, coverage_report_ref
            ) VALUES (
                :batch_id, :workspace_id, :seal_sha256, :project_run_id, :icp_key, :icp_version,
                :discovery_plan_id, :plan_sha256, :sealed_at, :account_count,
                :account_manifest_artifact_key, :account_manifest_sha256,
                :excluded_candidate_count, CAST(:field_resolution_summary AS jsonb),
                CAST(:provider_operation_ids AS jsonb), CAST(:request_fingerprints AS jsonb),
                :raw_artifact_manifest_key, :claim_id_manifest_key, :provider_units_charged,
                :cost_cents_charged, :coverage_report_ref
            )
            """
        ),
        {
            **seal.model_dump(mode="python"),
            "workspace_id": workspace_id,
            "field_resolution_summary": serialize_value_json(
                cast(JsonValue, seal.field_resolution_summary)
            ),
            "provider_operation_ids": serialize_value_json(
                cast(JsonValue, [str(value) for value in seal.provider_operation_ids])
            ),
            "request_fingerprints": serialize_value_json(
                cast(JsonValue, list(seal.request_fingerprints))
            ),
        },
    )
    await conn.execute(
        text(
            """
            UPDATE discovery_batch
            SET state = 'sealed', sealed_at = :sealed_at, updated_at = now()
            WHERE workspace_id = :workspace_id AND id = :batch_id AND state <> 'sealed'
            """
        ),
        {
            "workspace_id": workspace_id,
            "batch_id": batch_id,
            "sealed_at": seal.sealed_at,
        },
    )
    manifest_refs = (
        (draft.account_manifest_artifact_key, "account_manifest"),
        (draft.raw_artifact_manifest_key, "raw_manifest"),
        (draft.claim_id_manifest_key, "claim_manifest"),
        (draft.coverage_report_ref, "coverage_report"),
    )
    account_ids = (
        (
            await conn.execute(
                text(
                    """
                SELECT DISTINCT survivor_entity_id
                FROM discovery_candidate_link
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                  AND admission_status IN ('admitted', 'merged')
                """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .scalars()
        .all()
    )
    for account_id in account_ids:
        for key, kind in manifest_refs:
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=workspace_id,
                artifact_key_value=key,
                subject_kind="account",
                subject_entity_id=EntityId(account_id),
                reference_kind=kind,
                reference_id=str(batch_id),
            )
    return seal


def _seal_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _assert_seal_draft_matches(seal: DiscoveryBatchSeal, draft: DiscoverySealDraft) -> None:
    actual = (
        seal.account_manifest_artifact_key,
        seal.account_manifest_sha256,
        seal.raw_artifact_manifest_key,
        seal.claim_id_manifest_key,
        seal.coverage_report_ref,
    )
    expected = (
        draft.account_manifest_artifact_key,
        draft.account_manifest_sha256,
        draft.raw_artifact_manifest_key,
        draft.claim_id_manifest_key,
        draft.coverage_report_ref,
    )
    if actual != expected:
        raise DiscoverySealConflict("sealed batch manifests differ from replayed seal draft")


async def get_discovery_batch_status(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    pending_operation_limit: int = 100,
) -> DiscoveryBatchStatusProjection:
    if not 1 <= pending_operation_limit <= 100:
        raise ValueError("pending operation projection limit must be between 1 and 100")
    batch = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    if batch is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")
    seal = await get_discovery_batch_seal(conn, workspace_id=workspace_id, batch_id=batch_id)
    draft = (
        DiscoverySealDraft(
            account_manifest_artifact_key=seal.account_manifest_artifact_key,
            account_manifest_sha256=seal.account_manifest_sha256,
            raw_artifact_manifest_key=seal.raw_artifact_manifest_key,
            claim_id_manifest_key=seal.claim_id_manifest_key,
            coverage_report_ref=seal.coverage_report_ref,
        )
        if seal is not None
        else None
    )
    readiness = await read_discovery_seal_readiness(
        conn, workspace_id=workspace_id, batch_id=batch_id, draft=draft
    )
    operation_rows = (
        (
            await conn.execute(
                text(
                    """
                SELECT state::text AS state, count(*)::integer AS count
                FROM discovery_operation
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                GROUP BY state ORDER BY state
                """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .all()
    )
    pending_rows = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, next_poll_at FROM discovery_operation
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                  AND state NOT IN ('succeeded', 'accepted_terminal_failure')
                ORDER BY next_poll_at NULLS LAST, id
                LIMIT :limit
                """
                ),
                {
                    "workspace_id": workspace_id,
                    "batch_id": batch_id,
                    "limit": pending_operation_limit,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped = (
        (
            await conn.execute(
                text(
                    """
                SELECT 'candidate' AS kind, admission_status::text AS state, count(*)::integer
                FROM discovery_candidate_link
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                GROUP BY admission_status
                UNION ALL
                SELECT 'field', state::text, count(*)::integer
                FROM discovery_field_resolution
                WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                GROUP BY state
                """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .all()
    )
    item_count = (
        await conn.execute(
            text(
                """
                SELECT count(*) FROM discovery_item_snapshot item
                JOIN discovery_operation operation
                  ON operation.id = item.operation_id AND operation.workspace_id = item.workspace_id
                WHERE operation.workspace_id = :workspace_id AND operation.batch_id = :batch_id
                """
            ),
            {"workspace_id": workspace_id, "batch_id": batch_id},
        )
    ).scalar_one()
    candidate_counts = {
        str(row["state"]): int(row["count"]) for row in grouped if row["kind"] == "candidate"
    }
    field_counts = {
        str(row["state"]): int(row["count"]) for row in grouped if row["kind"] == "field"
    }
    poll_times = [row["next_poll_at"] for row in pending_rows if row["next_poll_at"] is not None]
    return DiscoveryBatchStatusProjection(
        batch=batch,
        operation_count=sum(int(row["count"]) for row in operation_rows),
        operation_state_counts={str(row["state"]): int(row["count"]) for row in operation_rows},
        pending_operation_ids=tuple(DiscoveryOperationId(row["id"]) for row in pending_rows),
        next_poll_at=min(poll_times) if poll_times else None,
        item_count=int(item_count),
        candidate_state_counts=candidate_counts,
        field_state_counts=field_counts,
        seal_blockers=evaluate_discovery_seal(readiness).blockers,
        seal_sha256=seal.seal_sha256 if seal else None,
    )
