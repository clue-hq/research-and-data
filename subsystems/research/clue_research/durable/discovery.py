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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    FIRST_PAGE_CURSOR,
    DiscoveryAccountManifest,
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
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPlan,
    DiscoveryPlanId,
    DiscoveryProviderEvent,
    DiscoverySealBlocker,
    DiscoverySealReadiness,
    DiscoverySpendOutcome,
    DiscoveryWakeRequest,
    DiscoveryWakeScheduler,
    EntityId,
    ProjectPhase,
    ProjectRunId,
    UtcDatetime,
    decode_jsonb,
    discovery_plan_sha256,
    evaluate_discovery_seal,
    serialize_value_json,
)
from clue_db import ConnFactory, transaction
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.durable.spend_posture import cap_refusal_is_enforced
from clue_storage import StorageBackend, artifact_key, content_address
from clue_storage.artifacts import erase_if_unreferenced, record_artifact

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20).
_SITE_DISCOVERY_RESERVATION: Final = "discovery_reservation"


class DiscoveryRepositoryError(RuntimeError):
    """Base failure raised by the durable discovery repository."""


class DiscoveryNotFound(DiscoveryRepositoryError):
    """The scoped discovery object does not exist."""


class DiscoveryReplayConflict(DiscoveryRepositoryError):
    """A stable idempotency key was reused with different immutable content."""


class DiscoveryBudgetExceeded(DiscoveryRepositoryError):
    """A paid discovery reservation would exceed its immutable plan cap."""


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
    cost_cents_reserved: Decimal
    cost_cents_charged: Decimal
    failure_code: str | None
    replacement_batch_id: DiscoveryBatchId | None
    started_at: UtcDatetime
    updated_at: UtcDatetime
    sealed_at: UtcDatetime | None


class DiscoveryBatchManifestBundle(BaseModel):
    """Immutable relational proof behind the four D5 manifest artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: DiscoveryBatchId
    workspace_id: str
    project_id: str
    project_run_id: ProjectRunId
    icp_key: str
    icp_version: int
    discovery_plan_id: DiscoveryPlanId
    plan_sha256: str
    generation: int
    contract_version: str = "discovery-batch-manifest-v1"
    account_ids: tuple[EntityId, ...]
    claim_ids: tuple[UUID, ...]
    raw_artifact_keys: tuple[str, ...]
    coverage_payload: dict[str, JsonValue]
    account_manifest_artifact_key: str
    account_manifest_sha256: str
    claim_manifest_artifact_key: str
    claim_manifest_sha256: str
    raw_manifest_artifact_key: str
    raw_manifest_sha256: str
    coverage_report_artifact_key: str
    coverage_report_sha256: str
    created_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _canonical_bundle(self) -> DiscoveryBatchManifestBundle:
        if self.generation < 1:
            raise ValueError("discovery manifest generation must be positive")
        if self.contract_version != "discovery-batch-manifest-v1":
            raise ValueError("unsupported discovery manifest contract")
        for label, values in (
            ("account_ids", self.account_ids),
            ("claim_ids", self.claim_ids),
            ("raw_artifact_keys", self.raw_artifact_keys),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"discovery manifest {label} must be unique")
        for value in (
            self.account_manifest_sha256,
            self.claim_manifest_sha256,
            self.raw_manifest_sha256,
            self.coverage_report_sha256,
        ):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("discovery manifest hashes must be canonical SHA-256")
        if self.icp_version < 1 or re.fullmatch(r"[0-9a-f]{64}", self.plan_sha256) is None:
            raise ValueError("discovery manifest ICP and plan lineage is invalid")
        account_payload = DiscoveryAccountManifest(
            workspace_id=self.workspace_id,
            discovery_batch_id=self.batch_id,
            project_id=self.project_id,
            project_run_id=self.project_run_id,
            icp_key=self.icp_key,
            icp_version=self.icp_version,
            discovery_plan_id=self.discovery_plan_id,
            plan_sha256=self.plan_sha256,
            generation=self.generation,
            account_ids=self.account_ids,
        ).model_dump(mode="json")
        claim_payload = {
            "contract": "discovery-claim-manifest-v1",
            "workspace_id": self.workspace_id,
            "discovery_batch_id": str(self.batch_id),
            "project_id": self.project_id,
            "project_run_id": str(self.project_run_id),
            "claim_ids": [str(value) for value in self.claim_ids],
        }
        raw_payload = {
            "contract": "discovery-raw-artifact-manifest-v1",
            "workspace_id": self.workspace_id,
            "discovery_batch_id": str(self.batch_id),
            "project_id": self.project_id,
            "project_run_id": str(self.project_run_id),
            "artifact_keys": list(self.raw_artifact_keys),
        }
        expected = (
            (self.account_manifest_artifact_key, self.account_manifest_sha256, account_payload),
            (self.claim_manifest_artifact_key, self.claim_manifest_sha256, claim_payload),
            (self.raw_manifest_artifact_key, self.raw_manifest_sha256, raw_payload),
            (
                self.coverage_report_artifact_key,
                self.coverage_report_sha256,
                self.coverage_payload,
            ),
        )
        for key, expected_sha, payload in expected:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            if (
                content_address(body) != expected_sha
                or artifact_key(self.workspace_id, expected_sha) != key
            ):
                raise ValueError("discovery manifest artifact does not match its canonical payload")
        return self

    @property
    def seal_draft(self) -> DiscoverySealDraft:
        return DiscoverySealDraft(
            account_manifest_artifact_key=self.account_manifest_artifact_key,
            account_manifest_sha256=self.account_manifest_sha256,
            raw_artifact_manifest_key=self.raw_manifest_artifact_key,
            claim_id_manifest_key=self.claim_manifest_artifact_key,
            coverage_report_ref=self.coverage_report_artifact_key,
        )


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
    review_task_id: EntityId | None
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


class DiscoveryPageRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    receipt: DiscoveryPageReceipt


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
    "state, generation, provider_units_reserved, provider_units_charged, cost_cents_reserved, "
    "cost_cents_charged, "
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
    replay = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    if replay is not None:
        if replay.discovery_plan_id != plan_id or replay.generation != generation:
            raise DiscoveryReplayConflict(f"discovery batch {batch_id} identity changed")
        return replay
    plan = await get_discovery_plan(conn, workspace_id=workspace_id, plan_id=plan_id)
    if plan is None:
        raise DiscoveryNotFound(f"discovery plan {plan_id} in workspace {workspace_id}")
    # Serialize current-generation creation on the owning run. This prevents a second active
    # generation from appearing beside provider work that is already in flight.
    locked_run = (
        await conn.execute(
            text(
                "SELECT id FROM project_run WHERE id = :run_id AND workspace_id = :workspace_id "
                "FOR UPDATE"
            ),
            {"run_id": plan.plan.project_run_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    if locked_run is None:
        raise DiscoveryNotFound(f"project run {plan.plan.project_run_id}")
    latest_row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_BATCH_COLUMNS} FROM discovery_batch "
                    "WHERE workspace_id = :workspace_id AND project_run_id = :run_id "
                    "ORDER BY generation DESC LIMIT 1 FOR UPDATE"
                ),
                {"workspace_id": workspace_id, "run_id": plan.plan.project_run_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    latest = _batch_row(latest_row) if latest_row is not None else None
    if latest is not None:
        if latest.state is DiscoveryBatchState.SEALED:
            raise DiscoveryReplayConflict("a sealed discovery generation cannot be replaced")
        if latest.state not in {
            DiscoveryBatchState.FAILED_TERMINAL,
            DiscoveryBatchState.CANCELLED_UNSEALED,
        }:
            raise DiscoveryReplayConflict(
                "an active discovery generation requires replace_discovery_batch"
            )
        if latest.replacement_batch_id is not None:
            raise DiscoveryReplayConflict("the current terminal generation was already replaced")
        if generation != latest.generation + 1:
            raise DiscoveryReplayConflict("a replacement must use the next discovery generation")
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
    if row.id != batch_id or row.discovery_plan_id != plan_id or row.generation != generation:
        raise DiscoveryReplayConflict(f"discovery batch {batch_id} identity changed")
    if latest is not None:
        await conn.execute(
            text(
                "UPDATE discovery_batch SET replacement_batch_id = :replacement, "
                "updated_at = now() WHERE workspace_id = :workspace_id AND id = :id "
                "AND replacement_batch_id IS NULL"
            ),
            {
                "replacement": row.id,
                "workspace_id": workspace_id,
                "id": latest.id,
            },
        )
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


async def get_current_discovery_batch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    for_update: bool = False,
) -> DiscoveryBatchRow | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_BATCH_COLUMNS} FROM discovery_batch "
                    "WHERE workspace_id = :workspace_id AND project_run_id = :project_run_id "
                    f"ORDER BY generation DESC LIMIT 1{suffix}"
                ),
                {"workspace_id": workspace_id, "project_run_id": project_run_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _batch_row(row) if row is not None else None


async def lock_discovery_batch_for_materialization(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
) -> DiscoveryBatchRow:
    """Lock one D4 batch for the caller's transaction and enter field materialization.

    Holding the row lock until commit serializes D4 workers, making the claim-equivalence check and
    subsequent append atomic. ``seal_pending`` is accepted for exact replay; D4 never mutates a
    sealed batch.
    """

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_BATCH_COLUMNS} FROM discovery_batch "
                    "WHERE workspace_id = :workspace_id AND id = :id FOR UPDATE"
                ),
                {"workspace_id": workspace_id, "id": batch_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")
    batch = _batch_row(row)
    if batch.state is DiscoveryBatchState.IDENTITY_RESOLUTION:
        await conn.execute(
            text(
                "UPDATE discovery_batch SET state = 'field_materialization', updated_at = now() "
                "WHERE workspace_id = :workspace_id AND id = :id"
            ),
            {"workspace_id": workspace_id, "id": batch_id},
        )
        updated = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
        assert updated is not None
        return updated
    if batch.state not in {
        DiscoveryBatchState.FIELD_MATERIALIZATION,
        DiscoveryBatchState.SEAL_PENDING,
    }:
        raise DiscoveryReplayConflict(
            f"batch {batch_id} in state {batch.state.value} cannot run D4 materialization"
        )
    return batch


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


async def pause_discovery_batch(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> DiscoveryBatchRow:
    batch = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    if batch is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")
    if batch.state is DiscoveryBatchState.PAUSED_BY_USER:
        return batch
    if batch.state in {
        DiscoveryBatchState.SEALED,
        DiscoveryBatchState.FAILED_TERMINAL,
        DiscoveryBatchState.CANCELLED_UNSEALED,
    }:
        raise DiscoveryReplayConflict(f"terminal batch {batch_id} cannot be paused")
    return await update_discovery_batch_state(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        state=DiscoveryBatchState.PAUSED_BY_USER,
    )


async def resume_discovery_batch(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> DiscoveryBatchRow:
    batch = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    if batch is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")
    if batch.state is not DiscoveryBatchState.PAUSED_BY_USER:
        return batch
    # Leave the protected paused state, then use the one existing operation-folding function to
    # derive the truthful resumable state. No operation identity or receipt is reset.
    await update_discovery_batch_state(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        state=DiscoveryBatchState.PLANNED,
    )
    return await reconcile_discovery_batch_state(conn, workspace_id=workspace_id, batch_id=batch_id)


async def _retire_discovery_wakes(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> None:
    await conn.execute(
        text(
            "UPDATE discovery_wake_outbox "
            "SET claimed_at = COALESCE(claimed_at, now()), "
            "processed_at = COALESCE(processed_at, now()) "
            "WHERE workspace_id = :workspace_id AND batch_id = :batch_id "
            "AND processed_at IS NULL"
        ),
        {"workspace_id": workspace_id, "batch_id": batch_id},
    )


async def cancel_discovery_batch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    reason_code: str = "cancelled_by_user",
) -> DiscoveryBatchRow:
    if not reason_code.strip():
        raise ValueError("discovery cancellation reason must be non-empty")
    selected = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    if selected is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")
    batch = await get_current_discovery_batch(
        conn,
        workspace_id=workspace_id,
        project_run_id=selected.project_run_id,
        for_update=True,
    )
    if batch is None or batch.id != batch_id:
        raise DiscoveryReplayConflict(
            "only the exact current discovery generation can be cancelled"
        )
    if batch.state is DiscoveryBatchState.CANCELLED_UNSEALED:
        return batch
    if batch.state in {DiscoveryBatchState.SEALED, DiscoveryBatchState.FAILED_TERMINAL}:
        raise DiscoveryReplayConflict(f"terminal batch {batch_id} cannot be cancelled")
    cancelled = await update_discovery_batch_state(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        state=DiscoveryBatchState.CANCELLED_UNSEALED,
        failure_code=reason_code.strip(),
    )
    await _retire_discovery_wakes(conn, workspace_id=workspace_id, batch_id=batch_id)
    return cancelled


async def replace_discovery_batch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    old_batch_id: DiscoveryBatchId,
    new_batch_id: DiscoveryBatchId,
    new_plan_id: DiscoveryPlanId,
) -> DiscoveryBatchRow:
    old = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=old_batch_id)
    if old is None:
        raise DiscoveryNotFound(f"discovery batch {old_batch_id}")
    await conn.execute(
        text(
            "SELECT id FROM project_run WHERE id = :run_id AND workspace_id = :workspace_id "
            "FOR UPDATE"
        ),
        {"run_id": old.project_run_id, "workspace_id": workspace_id},
    )
    current = await get_current_discovery_batch(
        conn,
        workspace_id=workspace_id,
        project_run_id=old.project_run_id,
        for_update=True,
    )
    if current is None or current.id != old_batch_id:
        if old.replacement_batch_id == new_batch_id:
            replay = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=new_batch_id
            )
            if replay is not None and replay.discovery_plan_id == new_plan_id:
                return replay
        raise DiscoveryReplayConflict("only the exact current discovery generation can be replaced")
    if current.state is DiscoveryBatchState.SEALED:
        raise DiscoveryReplayConflict("a sealed discovery generation cannot be replaced")
    new_plan = await get_discovery_plan(conn, workspace_id=workspace_id, plan_id=new_plan_id)
    old_plan = await get_discovery_plan(
        conn, workspace_id=workspace_id, plan_id=current.discovery_plan_id
    )
    if new_plan is None or old_plan is None:
        raise DiscoveryNotFound("replacement discovery plan")
    if (
        new_plan.plan.project_run_id != current.project_run_id
        or new_plan.plan.project_id != current.project_id
        or new_plan.plan.icp_key != current.icp_key
        or new_plan.plan.icp_version != current.icp_version
        or new_plan.plan.plan_version <= old_plan.plan.plan_version
    ):
        raise DiscoveryReplayConflict("replacement plan lineage or version is invalid")
    if current.state not in {
        DiscoveryBatchState.FAILED_TERMINAL,
        DiscoveryBatchState.CANCELLED_UNSEALED,
    }:
        await update_discovery_batch_state(
            conn,
            workspace_id=workspace_id,
            batch_id=current.id,
            state=DiscoveryBatchState.CANCELLED_UNSEALED,
            failure_code="replaced_by_new_generation",
        )
        await _retire_discovery_wakes(conn, workspace_id=workspace_id, batch_id=current.id)
    return await create_discovery_batch(
        conn,
        workspace_id=workspace_id,
        batch_id=new_batch_id,
        plan_id=new_plan_id,
        generation=current.generation + 1,
    )


_OPERATION_COLUMNS = (
    "id, batch_id, workspace_id, source_key, provider_api_version, request_fingerprint, "
    "observation_window, provider_external_id, provider_operation_id, state, spend_outcome, "
    "next_poll_at, submitted_receipt_ref, final_receipt_ref, raw_request_artifact_key, "
    "raw_response_manifest_key, provider_units_reserved, provider_units_charged, "
    "cost_cents_reserved, cost_cents_charged, started_at, terminal_at, "
    "final_reconciled_at, pagination_exhausted_at"
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
                cost_cents_reserved, cost_cents_charged, started_at, terminal_at
            ) VALUES (
                :id, :workspace_id, :batch_id, :source_key, :provider_api_version,
                :request_fingerprint, :observation_window, :provider_external_id,
                :provider_operation_id, CAST(:state AS discovery_operation_state),
                CAST(:spend_outcome AS discovery_spend_outcome), :next_poll_at,
                :submitted_receipt_ref, :final_receipt_ref, :raw_request_artifact_key,
                :raw_response_manifest_key, :provider_units_reserved, :provider_units_charged,
                :cost_cents_reserved, :cost_cents_charged, :started_at, :terminal_at
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


async def reserve_discovery_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation: DiscoveryOperation,
    enforce_budget: bool = True,
) -> tuple[DiscoveryOperation, bool]:
    """Atomically reserve one potentially-paid operation under the persisted plan cap.

    The batch row serializes competing reservations.  The cap is read from the immutable plan,
    never accepted from a caller.  An exact concurrent/restarted request returns the existing row
    with ``created=False``; it does not mint a second operation or increment the batch reservation.

    ``enforce_budget`` is the FI pilot budget-controls switch. It gates the *project-run* money
    check below **and** — since the 2026-08-20 ruling that our own spend caps are record-only in
    the pilot posture — the immutable plan's two running-total caps. Both are still computed and
    announced (:mod:`clue_research.durable.spend_posture`); only the refusal goes inert. Note the
    running totals mean a record-only batch can overshoot its plan cap, which is exactly the point
    (the true ceiling is the provider console); the durable reserved/charged numbers stay exact.
    """

    if operation.workspace_id != workspace_id:
        raise ValueError("discovery operation workspace does not match repository scope")
    if operation.state is not DiscoveryOperationState.PLANNED:
        raise ValueError("a new discovery reservation must start in planned state")
    if operation.spend_outcome is not DiscoverySpendOutcome.NOT_DISPATCHED:
        raise ValueError("a new discovery reservation must start as not_dispatched")
    locked = (
        (
            await conn.execute(
                text(
                    """
                    SELECT batch.id, batch.state, batch.discovery_plan_id, plan.plan_json
                    FROM discovery_batch batch
                    JOIN discovery_plan plan
                      ON plan.workspace_id = batch.workspace_id
                     AND plan.id = batch.discovery_plan_id
                    WHERE batch.workspace_id = :workspace_id AND batch.id = :batch_id
                    FOR UPDATE OF batch
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": operation.batch_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if locked is None:
        raise DiscoveryNotFound(f"discovery batch {operation.batch_id}")
    if str(locked["state"]) in {
        DiscoveryBatchState.SEALED.value,
        DiscoveryBatchState.FAILED_TERMINAL.value,
        DiscoveryBatchState.CANCELLED_UNSEALED.value,
    }:
        raise DiscoveryReplayConflict("discovery batch no longer accepts paid reservations")

    existing = await find_reusable_discovery_operation(
        conn,
        workspace_id=workspace_id,
        source_key=operation.source_key,
        request_fingerprint=operation.request_fingerprint,
        observation_window=operation.observation_window,
    )
    if existing is not None:
        immutable_matches = (
            existing.batch_id == operation.batch_id
            and existing.provider_api_version == operation.provider_api_version
            and existing.provider_external_id == operation.provider_external_id
            and existing.raw_request_artifact_key == operation.raw_request_artifact_key
            and existing.provider_units_reserved == operation.provider_units_reserved
            and existing.cost_cents_reserved == operation.cost_cents_reserved
        )
        if not immutable_matches:
            raise DiscoveryReplayConflict(
                "request fingerprint already belongs to different discovery operation content"
            )
        return existing, False

    plan_payload = decode_jsonb(locked["plan_json"])
    plan = DiscoveryPlan.model_validate(plan_payload)
    reserved_before = Decimal(
        (
            await conn.execute(
                text(
                    """
                    SELECT COALESCE(sum(provider_units_reserved), 0)
                    FROM discovery_operation
                    WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": operation.batch_id},
            )
        ).scalar_one()
    )
    reserved_after = reserved_before + operation.provider_units_reserved
    if reserved_after > Decimal(plan.provider_credit_cap) and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_DISCOVERY_RESERVATION,
        reason="batch_reserved_units_above_plan_cap",
        amounts={
            "batch_provider_units_reserved": reserved_after,
            "provider_credit_cap": plan.provider_credit_cap,
        },
    ):
        raise DiscoveryBudgetExceeded(
            "discovery provider-unit reservation exceeds the immutable plan cap"
        )
    cost_reserved_before = Decimal(
        (
            await conn.execute(
                text(
                    """
                    SELECT COALESCE(sum(cost_cents_reserved), 0)
                    FROM discovery_operation
                    WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": operation.batch_id},
            )
        ).scalar_one()
    )
    cost_reserved_after = cost_reserved_before + operation.cost_cents_reserved
    if cost_reserved_after > plan.money_budget_cap_cents and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_DISCOVERY_RESERVATION,
        reason="batch_reserved_cost_above_plan_cap",
        amounts={
            "batch_cost_cents_reserved": cost_reserved_after,
            "money_budget_cap_cents": plan.money_budget_cap_cents,
        },
    ):
        raise DiscoveryBudgetExceeded(
            "discovery monetary reservation exceeds the immutable plan cap"
        )

    try:
        await require_provider_spend_capacity(
            conn,
            project_run_id=plan.project_run_id,
            proposed_cents=operation.cost_cents_reserved,
            allowed_phases=frozenset({ProjectPhase.DISCOVERY}),
            enforce_budget=enforce_budget,
        )
    except ProviderSpendGuardError as exc:
        raise DiscoveryBudgetExceeded(str(exc)) from exc

    stored = await put_discovery_operation(
        conn,
        workspace_id=workspace_id,
        operation=operation,
    )
    await reconcile_discovery_batch_costs(
        conn,
        workspace_id=workspace_id,
        batch_id=operation.batch_id,
    )
    return stored, True


async def claim_discovery_operation_dispatch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
) -> DiscoveryOperation | None:
    """Claim the one create dispatch transition or return ``None`` to a replaying caller.

    Only a never-dispatched planned row, or a proven pre-dispatch retryable row, can win.  Moving
    to ``submitting`` commits before HTTP starts; every competing process observes that state and
    must join/reconcile instead of creating again.
    """

    row = (
        (
            await conn.execute(
                text(
                    f"""
                    UPDATE discovery_operation
                    SET state = 'submitting', spend_outcome = 'not_dispatched',
                        started_at = COALESCE(started_at, now()), updated_at = now()
                    WHERE workspace_id = :workspace_id AND id = :id
                      AND state IN ('planned', 'failed_retryable')
                      AND spend_outcome = 'not_dispatched'
                      AND provider_operation_id IS NULL
                      AND submitted_receipt_ref IS NULL
                    RETURNING {_OPERATION_COLUMNS}
                    """
                ),
                {"workspace_id": workspace_id, "id": operation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _operation_row(row) if row is not None else None


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
              AND observation_window = :observation_window
              AND state NOT IN (
                  'succeeded', 'accepted_terminal_failure', 'failed_terminal', 'cancelled'
              )
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


async def list_discovery_operations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
) -> tuple[DiscoveryOperation, ...]:
    """List a batch's provider operations in stable creation/id order."""

    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM discovery_operation "
                    "WHERE workspace_id = :workspace_id AND batch_id = :batch_id "
                    "ORDER BY started_at NULLS FIRST, id"
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(_operation_row(row) for row in rows)


async def find_discovery_operation_by_provider_id(
    conn: AsyncConnection,
    *,
    source_key: str,
    provider_operation_id: str,
) -> DiscoveryOperation | None:
    """Resolve signed team-level provider ingress to its tenant-local durable operation.

    This intentionally has no caller-supplied workspace: the globally unique provider operation id
    is the routing identity, and the returned operation supplies the workspace under which any raw
    event may subsequently be persisted.  It is for verified provider ingress only.
    """

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM discovery_operation "
                    "WHERE source_key = :source_key "
                    "AND provider_operation_id = :provider_operation_id"
                ),
                {
                    "source_key": source_key,
                    "provider_operation_id": provider_operation_id,
                },
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
        "cost_cents_reserved": operation.cost_cents_reserved,
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
            "cost_cents_reserved": row["cost_cents_reserved"],
            "cost_cents_charged": row["cost_cents_charged"],
            "started_at": row["started_at"],
            "terminal_at": row["terminal_at"],
            "final_reconciled_at": row["final_reconciled_at"],
            "pagination_exhausted_at": row["pagination_exhausted_at"],
        }
    )


def _batch_row(row: Any) -> DiscoveryBatchRow:
    return DiscoveryBatchRow.model_validate(dict(row))


async def record_discovery_event(
    conn: AsyncConnection, *, workspace_id: str, event: DiscoveryProviderEvent
) -> tuple[UUID, bool]:
    """Persist an event without assuming order and report whether this call inserted it."""

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
    elif batch_state in {
        DiscoveryBatchState.FAILED_TERMINAL.value,
        DiscoveryBatchState.CANCELLED_UNSEALED.value,
    }:
        event = DiscoveryProviderEvent.model_validate(
            {
                **event.model_dump(mode="python"),
                "processed_at": event.processed_at or event.received_at,
                "processing_disposition": DiscoveryEventDisposition.SUPERSEDED,
            }
        )

    event_id = uuid4()
    inserted = (
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
            RETURNING id
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
    ).scalar_one_or_none()
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
    return cast(UUID, row["id"]), inserted is not None


async def put_discovery_event(
    conn: AsyncConnection, *, workspace_id: str, event: DiscoveryProviderEvent
) -> UUID:
    event_id, _ = await record_discovery_event(conn, workspace_id=workspace_id, event=event)
    return event_id


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
        if row in {
            DiscoveryEventDisposition.LATE_AFTER_SEAL.value,
            DiscoveryEventDisposition.SUPERSEDED.value,
        }:
            return
        if row != disposition.value:
            raise DiscoveryReplayConflict(
                f"provider event {provider_event_id!r} already has disposition {row!r}"
            )


async def list_discovery_events(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
) -> tuple[DiscoveryProviderEvent, ...]:
    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT operation_id, provider_event_id, event_type, signature_verified,
                           payload_artifact_key, provider_created_at, received_at, processed_at,
                           processing_disposition
                    FROM discovery_provider_event
                    WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                    ORDER BY provider_created_at, provider_event_id
                    """
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(DiscoveryProviderEvent.model_validate(dict(row)) for row in rows)


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


async def get_discovery_page_row(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
    resource_kind: str,
    request_cursor: str = FIRST_PAGE_CURSOR,
) -> DiscoveryPageRow | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT id, operation_id, resource_kind, request_cursor_key, next_cursor,
                           has_more, payload_artifact_key, payload_sha256, item_count, fetched_at
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
    page_id = data.pop("id")
    data["request_cursor"] = data.pop("request_cursor_key")
    return DiscoveryPageRow(
        id=page_id,
        receipt=DiscoveryPageReceipt.model_validate(data),
    )


async def list_discovery_pages(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
) -> tuple[DiscoveryPageRow, ...]:
    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT id, operation_id, resource_kind, request_cursor_key, next_cursor,
                           has_more, payload_artifact_key, payload_sha256, item_count, fetched_at
                    FROM discovery_page_receipt
                    WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                    ORDER BY fetched_at, resource_kind, request_cursor_key
                    """
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .all()
    )
    result: list[DiscoveryPageRow] = []
    for row in rows:
        data = dict(row)
        page_id = data.pop("id")
        data["request_cursor"] = data.pop("request_cursor_key")
        result.append(
            DiscoveryPageRow(
                id=page_id,
                receipt=DiscoveryPageReceipt.model_validate(data),
            )
        )
    return tuple(result)


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


async def list_discovery_items(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
) -> tuple[DiscoveryItemSnapshot, ...]:
    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT id, operation_id, provider_item_id, source_kind, source_id,
                           raw_artifact_key, item_sha256, observed_at, normalization_state,
                           normalized_at
                    FROM discovery_item_snapshot
                    WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                    ORDER BY observed_at, provider_item_id, item_sha256
                    """
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .all()
    )
    result: list[DiscoveryItemSnapshot] = []
    for row in rows:
        data = dict(row)
        data["item_snapshot_id"] = data.pop("id")
        result.append(DiscoveryItemSnapshot.model_validate(data))
    return tuple(result)


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
    review_task_id: EntityId | None = None,
) -> DiscoveryCandidateLinkRow:
    _validate_candidate_shape(
        admission_status=admission_status,
        account_entity_id=account_entity_id,
        survivor_entity_id=survivor_entity_id,
        disposition_reason=disposition_reason,
        review_task_id=review_task_id,
    )
    existing = await get_discovery_candidate_link(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        item_snapshot_id=item_snapshot_id,
        for_update=True,
    )
    survivor_redirect = (
        existing is not None
        and existing.admission_status
        in {
            DiscoveryCandidateAdmissionState.ADMITTED,
            DiscoveryCandidateAdmissionState.MERGED,
        }
        and admission_status is DiscoveryCandidateAdmissionState.MERGED
        and existing.account_entity_id == account_entity_id
        and existing.survivor_entity_id != survivor_entity_id
        and survivor_entity_id != account_entity_id
        and bool(disposition_reason)
    )
    if existing is None:
        await conn.execute(
            text(
                """
                INSERT INTO discovery_candidate_link (
                    workspace_id, batch_id, item_snapshot_id, raw_name, candidate_domain,
                    source_url, admission_status, account_entity_id, survivor_entity_id,
                    disposition_reason, review_task_id
                )
                SELECT :workspace_id, :batch_id, item.id, :raw_name, :candidate_domain,
                       :source_url, CAST(:admission_status AS discovery_candidate_admission_state),
                       :account_entity_id, :survivor_entity_id, :disposition_reason,
                       :review_task_id
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
                "review_task_id": review_task_id,
            },
        )
    elif (
        existing.admission_status
        in {
            DiscoveryCandidateAdmissionState.PENDING,
            DiscoveryCandidateAdmissionState.REVIEW_REQUIRED,
        }
        or survivor_redirect
    ):
        if (
            existing.admission_status is DiscoveryCandidateAdmissionState.REVIEW_REQUIRED
            and admission_status
            not in {
                DiscoveryCandidateAdmissionState.REVIEW_REQUIRED,
                DiscoveryCandidateAdmissionState.ADMITTED,
                DiscoveryCandidateAdmissionState.MERGED,
                DiscoveryCandidateAdmissionState.EXCLUDED,
            }
        ):
            raise DiscoveryReplayConflict("identity review cannot transition back to pending")
        if (
            existing.admission_status is DiscoveryCandidateAdmissionState.REVIEW_REQUIRED
            and admission_status is not DiscoveryCandidateAdmissionState.REVIEW_REQUIRED
            and review_task_id != existing.review_task_id
        ):
            raise DiscoveryReplayConflict(
                "identity review transition must preserve its review task lineage"
            )
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
                    review_task_id = :review_task_id,
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
                "review_task_id": review_task_id,
            },
        )
    else:
        proposed = (
            admission_status,
            account_entity_id,
            survivor_entity_id,
            disposition_reason,
            review_task_id,
        )
        actual = (
            existing.admission_status,
            existing.account_entity_id,
            existing.survivor_entity_id,
            existing.disposition_reason,
            existing.review_task_id,
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
                       disposition_reason, review_task_id, updated_at
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
    review_task_id: EntityId | None,
) -> None:
    if admission_status is DiscoveryCandidateAdmissionState.PENDING:
        valid = (
            account_entity_id is None
            and survivor_entity_id is None
            and disposition_reason is None
            and review_task_id is None
        )
    elif admission_status is DiscoveryCandidateAdmissionState.REVIEW_REQUIRED:
        valid = (
            account_entity_id is None
            and survivor_entity_id is None
            and disposition_reason is None
            and review_task_id is not None
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
        # Every state, including review/retry/failure blockers, must be exact-replay safe. The
        # transition table below governs changes; it must not reject a byte-for-byte replay of the
        # same durable decision.
        if existing == resolution:
            return existing
        if existing.state in _FIELD_TERMINAL:
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
                    WITH RECURSIVE members AS (
                        SELECT id
                        FROM account_entity
                        WHERE id = :account_entity_id AND workspace_id = :workspace_id
                        UNION
                        SELECT account.id
                        FROM account_entity account
                        JOIN members ON account.merged_into = members.id
                        WHERE account.workspace_id = :workspace_id
                    )
                    SELECT claim.id, claim.entity_id, claim.workspace_id,
                           (members.id IS NOT NULL) AS belongs_to_survivor
                    FROM claim
                    LEFT JOIN members ON members.id = claim.entity_id
                    WHERE claim.id = ANY(:claim_ids)
                    """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "account_entity_id": resolution.account_entity_id,
                        "claim_ids": list(resolution.claim_ids),
                    },
                )
            )
            .mappings()
            .all()
        )
        if len(claims) != len(resolution.claim_ids) or any(
            not claim["belongs_to_survivor"] or claim["workspace_id"] not in (None, workspace_id)
            for claim in claims
        ):
            raise ValueError(
                "discovery field claims must belong to the scoped survivor or a merged member"
            )

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


async def list_discovery_field_resolutions(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    state: DiscoveryFieldResolutionState | None = None,
) -> tuple[DiscoveryFieldResolution, ...]:
    params: dict[str, object] = {"workspace_id": workspace_id, "batch_id": batch_id}
    predicate = ""
    if state is not None:
        predicate = " AND state = CAST(:state AS discovery_field_resolution_state)"
        params["state"] = state.value
    rows = (
        await conn.execute(
            text(
                "SELECT account_entity_id, logical_field_key FROM discovery_field_resolution "
                "WHERE workspace_id=:workspace_id AND batch_id=:batch_id"
                + predicate
                + " ORDER BY account_entity_id, logical_field_key"
            ),
            params,
        )
    ).all()
    values: list[DiscoveryFieldResolution] = []
    for account_entity_id, logical_field_key in rows:
        resolution = await get_discovery_field_resolution(
            conn,
            workspace_id=workspace_id,
            batch_id=batch_id,
            account_entity_id=EntityId(account_entity_id),
            logical_field_key=str(logical_field_key),
        )
        assert resolution is not None
        values.append(resolution)
    return tuple(values)


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
    conn: AsyncConnection,
    *,
    limit: int = 100,
    now: datetime | None = None,
    claim_stale_after: timedelta = timedelta(minutes=5),
    source_key: str | None = None,
    workspace_id: str | None = None,
) -> tuple[DiscoveryWakeRow, ...]:
    if not 1 <= limit <= 100:
        raise ValueError("discovery wake claim limit must be between 1 and 100")
    if claim_stale_after.total_seconds() <= 0:
        raise ValueError("discovery wake claim_stale_after must be positive")
    claim_now = now or datetime.now(UTC)
    rows = (
        (
            await conn.execute(
                text(
                    """
                WITH due AS (
                    SELECT wake.id FROM discovery_wake_outbox wake
                    JOIN discovery_batch batch
                      ON batch.id = wake.batch_id AND batch.workspace_id = wake.workspace_id
                    WHERE wake.processed_at IS NULL AND wake.available_at <= :now
                      AND batch.state NOT IN (
                          'paused_by_user', 'failed_terminal', 'cancelled_unsealed', 'sealed'
                      )
                      AND (wake.claimed_at IS NULL OR wake.claimed_at <= :stale_before)
                      AND (
                          CAST(:workspace_id AS text) IS NULL
                          OR wake.workspace_id = CAST(:workspace_id AS text)
                      )
                      AND (
                          CAST(:source_key AS text) IS NULL
                          OR EXISTS (
                              SELECT 1 FROM discovery_operation operation
                              WHERE operation.workspace_id = wake.workspace_id
                                AND operation.id = wake.operation_id
                                AND operation.source_key = CAST(:source_key AS text)
                          )
                      )
                    ORDER BY wake.available_at, wake.id
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
                {
                    "now": claim_now,
                    "stale_before": claim_now - claim_stale_after,
                    "limit": limit,
                    "source_key": source_key,
                    "workspace_id": workspace_id,
                },
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
                cost_cents_reserved = totals.cost_reserved,
                cost_cents_charged = totals.cost,
                updated_at = now()
            FROM (
                SELECT COALESCE(sum(operation.provider_units_reserved), 0) AS reserved,
                       COALESCE(sum(operation.provider_units_charged), 0) AS charged,
                       COALESCE(sum(operation.cost_cents_reserved), 0) AS cost_reserved,
                       COALESCE(sum(operation.cost_cents_charged), 0) AS cost
                FROM (
                    SELECT provider_units_reserved, provider_units_charged,
                           cost_cents_reserved, cost_cents_charged
                    FROM discovery_operation
                    WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                    UNION ALL
                    SELECT provider_units_reserved, provider_units_charged,
                           cost_cents_reserved, cost_cents_charged
                    FROM discovery_gap_operation
                    WHERE workspace_id = :workspace_id
                      AND discovery_batch_id = :batch_id
                ) operation
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


async def reconcile_discovery_batch_state(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
) -> DiscoveryBatchRow:
    """Fold every planned operation into one truthful pre-identity batch state.

    In particular, a successful operation cannot advance a multi-search plan while another planned
    operation is absent or non-terminal.  Final/paused/user-owned states are never overwritten.
    """

    locked = (
        (
            await conn.execute(
                text(
                    """
                    SELECT batch.state, jsonb_array_length(plan.plan_json -> 'searches') AS planned
                    FROM discovery_batch batch
                    JOIN discovery_plan plan
                      ON plan.id = batch.discovery_plan_id
                     AND plan.workspace_id = batch.workspace_id
                    WHERE batch.workspace_id = :workspace_id AND batch.id = :batch_id
                    FOR UPDATE OF batch
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if locked is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")
    current = DiscoveryBatchState(str(locked["state"]))
    protected = {
        DiscoveryBatchState.IDENTITY_RESOLUTION,
        DiscoveryBatchState.FIELD_MATERIALIZATION,
        DiscoveryBatchState.SEAL_PENDING,
        DiscoveryBatchState.SEALED,
        DiscoveryBatchState.PAUSED_BY_USER,
        DiscoveryBatchState.FAILED_TERMINAL,
        DiscoveryBatchState.CANCELLED_UNSEALED,
    }
    if current in protected:
        row = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
        assert row is not None
        return row

    states = tuple(
        str(value)
        for value in (
            await conn.execute(
                text(
                    "SELECT state FROM discovery_operation "
                    "WHERE workspace_id = :workspace_id AND batch_id = :batch_id"
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        ).scalars()
    )
    planned = int(locked["planned"])
    terminal = {
        DiscoveryOperationState.SUCCEEDED.value,
        DiscoveryOperationState.ACCEPTED_TERMINAL_FAILURE.value,
    }
    if len(states) == planned and states and all(state in terminal for state in states):
        target = DiscoveryBatchState.IDENTITY_RESOLUTION
    elif DiscoveryOperationState.SPEND_OUTCOME_UNKNOWN.value in states:
        target = DiscoveryBatchState.SPEND_OUTCOME_UNKNOWN
    elif len(states) < planned:
        target = DiscoveryBatchState.SUBMITTING
    elif DiscoveryOperationState.RECONCILING.value in states:
        target = DiscoveryBatchState.RECONCILING
    elif DiscoveryOperationState.INGESTING.value in states:
        target = DiscoveryBatchState.INGESTING_EVENTS_AND_PAGES
    elif DiscoveryOperationState.PROVIDER_RUNNING.value in states:
        target = DiscoveryBatchState.PROVIDER_RUNNING
    elif any(
        state
        in {
            DiscoveryOperationState.WAITING_EXTERNAL.value,
            DiscoveryOperationState.FAILED_RETRYABLE.value,
        }
        for state in states
    ):
        target = DiscoveryBatchState.WAITING_EXTERNAL
    elif states:
        target = DiscoveryBatchState.SUBMITTING
    else:
        target = DiscoveryBatchState.PLANNED
    return await update_discovery_batch_state(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        state=target,
    )


async def claim_discovery_operation_reconciliation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: DiscoveryOperationId,
    now: datetime | None = None,
    lease_for: timedelta = timedelta(minutes=2),
) -> DiscoveryOperation | None:
    """Atomically claim one poll/reconciliation driver, including an expired crash lease."""

    if lease_for.total_seconds() <= 0:
        raise ValueError("discovery reconciliation lease_for must be positive")
    claim_now = now or datetime.now(UTC)
    row = (
        (
            await conn.execute(
                text(
                    f"""
                    UPDATE discovery_operation
                    SET state = 'reconciling', next_poll_at = :lease_until, updated_at = now()
                    WHERE workspace_id = :workspace_id AND id = :id
                      AND provider_operation_id IS NOT NULL
                      AND submitted_receipt_ref IS NOT NULL
                      AND spend_outcome = 'charged'
                      AND (
                          state IN (
                              'provider_running', 'waiting_external', 'ingesting',
                              'failed_retryable'
                          )
                          OR (state = 'reconciling' AND next_poll_at <= :now)
                      )
                    RETURNING {_OPERATION_COLUMNS}
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "id": operation_id,
                    "now": claim_now,
                    "lease_until": claim_now + lease_for,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return _operation_row(row) if row is not None else None


_MANIFEST_COLUMNS = (
    "batch_id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
    "discovery_plan_id, plan_sha256, generation, contract_version, "
    "account_ids, claim_ids, raw_artifact_keys, coverage_payload, "
    "account_manifest_artifact_key, account_manifest_sha256, "
    "claim_manifest_artifact_key, claim_manifest_sha256, "
    "raw_manifest_artifact_key, raw_manifest_sha256, "
    "coverage_report_artifact_key, coverage_report_sha256, created_at"
)


def _manifest_bundle(row: Any) -> DiscoveryBatchManifestBundle:
    data = dict(row)
    data["account_ids"] = tuple(
        EntityId(UUID(value)) for value in decode_jsonb(data["account_ids"])
    )
    data["claim_ids"] = tuple(UUID(value) for value in decode_jsonb(data["claim_ids"]))
    data["raw_artifact_keys"] = tuple(decode_jsonb(data["raw_artifact_keys"]))
    data["coverage_payload"] = decode_jsonb(data["coverage_payload"])
    return DiscoveryBatchManifestBundle.model_validate(data)


async def get_discovery_batch_manifest(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> DiscoveryBatchManifestBundle | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_MANIFEST_COLUMNS} FROM discovery_batch_manifest "
                    "WHERE workspace_id = :workspace_id AND batch_id = :batch_id"
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _manifest_bundle(row) if row is not None else None


async def discovery_manifest_members(
    conn: AsyncConnection, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> tuple[tuple[EntityId, ...], tuple[UUID, ...], tuple[str, ...]]:
    account_ids = tuple(
        EntityId(value)
        for value in (
            await conn.execute(
                text(
                    "SELECT DISTINCT survivor_entity_id FROM discovery_candidate_link "
                    "WHERE workspace_id = :workspace_id AND batch_id = :batch_id "
                    "AND admission_status IN ('admitted', 'merged') "
                    "ORDER BY survivor_entity_id"
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        ).scalars()
    )
    claim_ids = tuple(
        UUID(str(value))
        for value in (
            await conn.execute(
                text(
                    """
                    WITH batch_claims AS (
                        SELECT edge.claim_id
                        FROM discovery_field_claim edge
                        JOIN discovery_field_resolution resolution
                          ON resolution.id = edge.resolution_id
                         AND resolution.workspace_id = edge.workspace_id
                        WHERE resolution.workspace_id = :workspace_id
                          AND resolution.batch_id = :batch_id
                        UNION
                        SELECT materialized.id AS claim_id
                        FROM discovery_candidate_link candidate
                        JOIN discovery_item_snapshot item
                          ON item.id = candidate.item_snapshot_id
                         AND item.workspace_id = candidate.workspace_id
                        JOIN claim materialized
                          ON materialized.entity_id = candidate.survivor_entity_id
                         AND materialized.artifact_key = item.raw_artifact_key
                        WHERE candidate.workspace_id = :workspace_id
                          AND candidate.batch_id = :batch_id
                          AND candidate.admission_status IN ('admitted', 'merged')
                    )
                    SELECT DISTINCT claim_id FROM batch_claims ORDER BY claim_id
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        ).scalars()
    )
    raw_keys = tuple(
        str(value)
        for value in (
            await conn.execute(
                text(
                    """
                    WITH operations AS (
                        SELECT * FROM discovery_operation
                        WHERE workspace_id = :workspace_id AND batch_id = :batch_id
                    ), refs AS (
                        SELECT ref.key
                        FROM operations operation
                        CROSS JOIN LATERAL (VALUES
                            (operation.submitted_receipt_ref),
                            (operation.final_receipt_ref),
                            (operation.raw_request_artifact_key),
                            (operation.raw_response_manifest_key)
                        ) ref(key)
                        WHERE ref.key IS NOT NULL
                        UNION
                        SELECT event.payload_artifact_key
                        FROM discovery_provider_event event
                        WHERE event.workspace_id = :workspace_id
                          AND event.operation_id IN (SELECT id FROM operations)
                          AND event.processing_disposition NOT IN (
                              'late_after_seal', 'superseded'
                          )
                        UNION
                        SELECT page.payload_artifact_key
                        FROM discovery_page_receipt page
                        WHERE page.workspace_id = :workspace_id
                          AND page.operation_id IN (SELECT id FROM operations)
                        UNION
                        SELECT item.raw_artifact_key
                        FROM discovery_item_snapshot item
                        WHERE item.workspace_id = :workspace_id
                          AND item.operation_id IN (SELECT id FROM operations)
                        UNION
                        SELECT ref.key
                        FROM discovery_gap_operation gap
                        CROSS JOIN LATERAL (VALUES
                            (gap.request_artifact_key),
                            (gap.response_artifact_key),
                            (gap.receipt_artifact_key)
                        ) ref(key)
                        WHERE gap.workspace_id = :workspace_id
                          AND gap.discovery_batch_id = :batch_id
                          AND ref.key IS NOT NULL
                    )
                    SELECT key FROM refs ORDER BY key
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        ).scalars()
    )
    return account_ids, claim_ids, raw_keys


async def put_discovery_batch_manifest(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    bundle: DiscoveryBatchManifestBundle,
) -> DiscoveryBatchManifestBundle:
    if bundle.workspace_id != workspace_id:
        raise ValueError("discovery manifest workspace does not match repository scope")
    existing = await get_discovery_batch_manifest(
        conn, workspace_id=workspace_id, batch_id=bundle.batch_id
    )
    if existing is not None:
        if existing.model_copy(update={"created_at": None}) != bundle.model_copy(
            update={"created_at": None}
        ):
            raise DiscoveryReplayConflict("discovery batch manifest content changed")
        return existing
    batch = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=bundle.batch_id)
    if batch is None:
        raise DiscoveryNotFound(f"discovery batch {bundle.batch_id}")
    if batch.state in {
        DiscoveryBatchState.SEALED,
        DiscoveryBatchState.FAILED_TERMINAL,
        DiscoveryBatchState.CANCELLED_UNSEALED,
    }:
        raise DiscoveryReplayConflict(
            f"batch {bundle.batch_id} in state {batch.state.value} cannot create final manifests"
        )
    plan_row = await get_discovery_plan(
        conn, workspace_id=workspace_id, plan_id=batch.discovery_plan_id
    )
    if plan_row is None:
        raise DiscoveryNotFound(f"discovery plan {batch.discovery_plan_id}")
    if (
        bundle.project_id != batch.project_id
        or bundle.project_run_id != batch.project_run_id
        or bundle.icp_key != batch.icp_key
        or bundle.icp_version != batch.icp_version
        or bundle.discovery_plan_id != batch.discovery_plan_id
        or bundle.plan_sha256 != plan_row.plan_sha256
        or bundle.generation != batch.generation
    ):
        raise DiscoveryReplayConflict("discovery manifest lineage does not match its batch")
    account_ids, claim_ids, raw_keys = await discovery_manifest_members(
        conn, workspace_id=workspace_id, batch_id=bundle.batch_id
    )
    if (
        bundle.account_ids != account_ids
        or bundle.claim_ids != claim_ids
        or bundle.raw_artifact_keys != raw_keys
    ):
        raise DiscoveryReplayConflict("discovery manifest members differ from durable ledgers")
    coverage = bundle.coverage_payload
    required_coverage = {
        "contract": "discovery-coverage-report-v1",
        "workspace_id": workspace_id,
        "discovery_batch_id": str(batch.id),
        "project_id": batch.project_id,
        "project_run_id": str(batch.project_run_id),
        "generation": batch.generation,
        "admitted_account_count": len(account_ids),
    }
    if any(coverage.get(key) != value for key, value in required_coverage.items()):
        raise DiscoveryReplayConflict("discovery coverage payload lineage or counts changed")
    readiness = await read_discovery_seal_readiness(
        conn, workspace_id=workspace_id, batch_id=bundle.batch_id
    )
    blockers = tuple(
        blocker
        for blocker in evaluate_discovery_seal(readiness).blockers
        if blocker is not DiscoverySealBlocker.FINAL_MANIFESTS
    )
    if blockers:
        raise DiscoverySealBlocked(blockers)
    await conn.execute(
        text(
            """
            INSERT INTO discovery_batch_manifest (
                batch_id, workspace_id, project_id, project_run_id, icp_key, icp_version,
                discovery_plan_id, plan_sha256, generation, contract_version,
                account_ids, claim_ids, raw_artifact_keys, coverage_payload,
                account_manifest_artifact_key, account_manifest_sha256,
                claim_manifest_artifact_key, claim_manifest_sha256,
                raw_manifest_artifact_key, raw_manifest_sha256,
                coverage_report_artifact_key, coverage_report_sha256
            ) VALUES (
                :batch_id, :workspace_id, :project_id, :project_run_id, :icp_key, :icp_version,
                :discovery_plan_id, :plan_sha256, :generation,
                :contract_version, CAST(:account_ids AS jsonb), CAST(:claim_ids AS jsonb),
                CAST(:raw_artifact_keys AS jsonb), CAST(:coverage_payload AS jsonb),
                :account_manifest_artifact_key, :account_manifest_sha256,
                :claim_manifest_artifact_key, :claim_manifest_sha256,
                :raw_manifest_artifact_key, :raw_manifest_sha256,
                :coverage_report_artifact_key, :coverage_report_sha256
            ) ON CONFLICT (batch_id) DO NOTHING
            """
        ),
        {
            **bundle.model_dump(
                mode="python",
                exclude={
                    "account_ids",
                    "claim_ids",
                    "raw_artifact_keys",
                    "coverage_payload",
                    "created_at",
                },
            ),
            "account_ids": serialize_value_json(
                cast(JsonValue, [str(value) for value in bundle.account_ids])
            ),
            "claim_ids": serialize_value_json(
                cast(JsonValue, [str(value) for value in bundle.claim_ids])
            ),
            "raw_artifact_keys": serialize_value_json(
                cast(JsonValue, list(bundle.raw_artifact_keys))
            ),
            "coverage_payload": serialize_value_json(cast(JsonValue, bundle.coverage_payload)),
        },
    )
    stored = await get_discovery_batch_manifest(
        conn, workspace_id=workspace_id, batch_id=bundle.batch_id
    )
    if stored is None:
        raise DiscoveryNotFound(f"discovery batch manifest {bundle.batch_id}")
    if stored.model_copy(update={"created_at": None}) != bundle.model_copy(
        update={"created_at": None}
    ):
        raise DiscoveryReplayConflict("discovery batch manifest content changed")
    return stored


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
    ), gap_operations AS (
        SELECT operation.*
        FROM discovery_gap_operation operation
        WHERE operation.workspace_id = :workspace_id
          AND operation.discovery_batch_id = :batch_id
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
    ), manifest AS (
        SELECT bundle.*
        FROM discovery_batch_manifest bundle
        WHERE bundle.workspace_id = :workspace_id AND bundle.batch_id = :batch_id
    ), manifest_claims AS (
        SELECT DISTINCT field_claim.claim_id
        FROM discovery_field_claim field_claim
        JOIN discovery_field_resolution resolution
          ON resolution.id = field_claim.resolution_id
         AND resolution.workspace_id = field_claim.workspace_id
        WHERE resolution.workspace_id = :workspace_id AND resolution.batch_id = :batch_id
        UNION
        SELECT materialized.id AS claim_id
        FROM discovery_candidate_link candidate
        JOIN discovery_item_snapshot item
          ON item.id = candidate.item_snapshot_id
         AND item.workspace_id = candidate.workspace_id
        JOIN claim materialized
          ON materialized.entity_id = candidate.survivor_entity_id
         AND materialized.artifact_key = item.raw_artifact_key
        WHERE candidate.workspace_id = :workspace_id
          AND candidate.batch_id = :batch_id
          AND candidate.admission_status IN ('admitted', 'merged')
    ), raw_artifacts AS (
        SELECT ref.key
        FROM operations operation
        CROSS JOIN LATERAL (VALUES
            (operation.submitted_receipt_ref),
            (operation.final_receipt_ref),
            (operation.raw_request_artifact_key),
            (operation.raw_response_manifest_key)
        ) ref(key)
        WHERE ref.key IS NOT NULL
        UNION
        SELECT event.payload_artifact_key
        FROM discovery_provider_event event
        WHERE event.workspace_id = :workspace_id
          AND event.operation_id IN (SELECT id FROM operations)
          AND event.processing_disposition NOT IN ('late_after_seal', 'superseded')
        UNION
        SELECT page.payload_artifact_key
        FROM discovery_page_receipt page
        WHERE page.workspace_id = :workspace_id
          AND page.operation_id IN (SELECT id FROM operations)
        UNION
        SELECT item.raw_artifact_key
        FROM discovery_item_snapshot item
        WHERE item.workspace_id = :workspace_id
          AND item.operation_id IN (SELECT id FROM operations)
        UNION
        SELECT ref.key
        FROM gap_operations operation
        CROSS JOIN LATERAL (VALUES
            (operation.request_artifact_key),
            (operation.response_artifact_key),
            (operation.receipt_artifact_key)
        ) ref(key)
        WHERE ref.key IS NOT NULL
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
        )
        AND NOT EXISTS (
            SELECT 1 FROM gap_operations WHERE state <> 'succeeded'
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
        )
        AND NOT EXISTS (
            SELECT 1 FROM gap_operations operation
            WHERE operation.request_artifact_key IS NULL
               OR operation.response_artifact_key IS NULL
               OR operation.receipt_artifact_key IS NULL
               OR operation.provider_request_id IS NULL
               OR NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.storage_key = operation.request_artifact_key
                      AND artifact.workspace_id = :workspace_id
                      AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
               )
               OR NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.storage_key = operation.response_artifact_key
                      AND artifact.workspace_id = :workspace_id
                      AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
               )
               OR NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.storage_key = operation.receipt_artifact_key
                      AND artifact.workspace_id = :workspace_id
                      AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
               )
        ) AS dispatch_receipts_complete,

        NOT EXISTS (
            SELECT 1 FROM discovery_provider_event event
            WHERE event.workspace_id = :workspace_id
              AND event.operation_id IN (SELECT id FROM operations)
              AND (
                  NOT event.signature_verified
                  OR event.processing_disposition = 'pending'
                  OR event.processed_at IS NULL
              )
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
              AND page.resource_kind = 'items'
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
                    AND (
                        candidate.review_task_id IS NULL
                        OR EXISTS (
                            SELECT 1 FROM identity_review_task review
                            WHERE review.id = candidate.review_task_id
                              AND review.workspace_id = candidate.workspace_id
                              AND review.status IN ('resolved', 'dismissed')
                        )
                    )
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
                           AND (claim.workspace_id IS NULL
                                OR claim.workspace_id = :workspace_id)
                          WHERE field_claim.workspace_id = :workspace_id
                            AND field_claim.resolution_id = resolution.id
                            AND field_claim.claim_id = resolution.winning_claim_id
                            AND claim.entity_id IN (
                                WITH RECURSIVE members AS (
                                    SELECT id
                                    FROM account_entity
                                    WHERE id = resolution.account_entity_id
                                      AND workspace_id = :workspace_id
                                    UNION
                                    SELECT account.id
                                    FROM account_entity account
                                    JOIN members ON account.merged_into = members.id
                                    WHERE account.workspace_id = :workspace_id
                                )
                                SELECT id FROM members
                            )
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
                      OR (candidate.admission_status = 'merged' AND (
                          source_account.id IS NULL OR source_account.id = survivor.id
                          OR NOT EXISTS (
                              WITH RECURSIVE chain AS (
                                  SELECT id, merged_into
                                  FROM account_entity
                                  WHERE id = source_account.id
                                    AND workspace_id = candidate.workspace_id
                                  UNION
                                  SELECT account.id, account.merged_into
                                  FROM account_entity account
                                  JOIN chain ON account.id = chain.merged_into
                                  WHERE account.workspace_id = candidate.workspace_id
                              )
                              SELECT 1 FROM chain WHERE id = survivor.id
                          )
                      ))
                  ))
              )
        ) AS survivor_links_complete,

        EXISTS (SELECT 1 FROM target)
        AND (SELECT provider_units_charged FROM target) =
            (SELECT COALESCE(sum(provider_units_charged), 0) FROM operations)
            + (SELECT COALESCE(sum(provider_units_charged), 0) FROM gap_operations)
        AND (SELECT cost_cents_charged FROM target) =
            (SELECT COALESCE(sum(cost_cents_charged), 0) FROM operations)
            + (SELECT COALESCE(sum(cost_cents_charged), 0) FROM gap_operations)
        AND NOT EXISTS (
            SELECT 1 FROM operations WHERE spend_outcome IN ('unknown', 'not_dispatched')
        )
        AND NOT EXISTS (
            SELECT 1 FROM gap_operations WHERE spend_outcome IN ('unknown', 'not_dispatched')
        ) AS spend_reconciled,

        EXISTS (
            SELECT 1
            FROM manifest bundle
            CROSS JOIN target
            WHERE bundle.project_run_id = target.project_run_id
              AND bundle.project_id = target.project_id
              AND bundle.icp_key = target.icp_key
              AND bundle.icp_version = target.icp_version
              AND bundle.discovery_plan_id = target.discovery_plan_id
              AND bundle.plan_sha256 = target.plan_sha256
              AND bundle.generation = target.generation
              AND bundle.contract_version = 'discovery-batch-manifest-v1'
              AND bundle.account_manifest_artifact_key = CAST(:account_manifest AS text)
              AND bundle.account_manifest_sha256 = CAST(:account_manifest_sha256 AS text)
              AND bundle.raw_manifest_artifact_key = CAST(:raw_manifest AS text)
              AND bundle.claim_manifest_artifact_key = CAST(:claim_manifest AS text)
              AND bundle.coverage_report_artifact_key = CAST(:coverage_ref AS text)
              AND jsonb_array_length(bundle.account_ids) = (SELECT count(*) FROM admitted)
              AND NOT EXISTS (
                  SELECT 1 FROM admitted
                  WHERE NOT bundle.account_ids ? admitted.account_entity_id::text
              )
              AND jsonb_array_length(bundle.claim_ids) = (SELECT count(*) FROM manifest_claims)
              AND NOT EXISTS (
                  SELECT 1 FROM manifest_claims
                  WHERE NOT bundle.claim_ids ? manifest_claims.claim_id::text
              )
              AND jsonb_array_length(bundle.raw_artifact_keys) =
                  (SELECT count(*) FROM raw_artifacts)
              AND NOT EXISTS (
                  SELECT 1 FROM raw_artifacts
                  WHERE NOT bundle.raw_artifact_keys ? raw_artifacts.key
              )
              AND bundle.coverage_payload ->> 'contract' = 'discovery-coverage-report-v1'
              AND bundle.coverage_payload ->> 'workspace_id' = target.workspace_id
              AND bundle.coverage_payload ->> 'discovery_batch_id' = target.id::text
              AND bundle.coverage_payload ->> 'project_run_id' = target.project_run_id::text
              AND bundle.coverage_payload ->> 'project_id' = target.project_id
              AND (bundle.coverage_payload ->> 'generation')::integer = target.generation
              AND (bundle.coverage_payload ->> 'admitted_account_count')::integer =
                  (SELECT count(*) FROM admitted)
              AND NOT EXISTS (
                  SELECT 1 FROM (VALUES
                      (bundle.account_manifest_artifact_key, bundle.account_manifest_sha256),
                      (bundle.claim_manifest_artifact_key, bundle.claim_manifest_sha256),
                      (bundle.raw_manifest_artifact_key, bundle.raw_manifest_sha256),
                      (bundle.coverage_report_artifact_key, bundle.coverage_report_sha256)
                  ) required(key, sha256)
                  WHERE NOT EXISTS (
                      SELECT 1 FROM artifact
                      WHERE artifact.storage_key = required.key
                        AND artifact.workspace_id = :workspace_id
                        AND artifact.content_sha256 = required.sha256
                        AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
                  )
              )
              AND NOT EXISTS (
                  SELECT 1 FROM raw_artifacts raw
                  WHERE NOT EXISTS (
                      SELECT 1 FROM artifact
                      WHERE artifact.storage_key = raw.key
                        AND artifact.workspace_id = :workspace_id
                        AND artifact.erased_at IS NULL AND artifact.purged_at IS NULL
                  )
              )
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

    manifest = await get_discovery_batch_manifest(
        conn, workspace_id=workspace_id, batch_id=batch_id
    )
    if manifest is None:
        raise DiscoverySealBlocked((DiscoverySealBlocker.FINAL_MANIFESTS,))
    if manifest.seal_draft != draft:
        raise DiscoverySealConflict("seal draft differs from immutable discovery manifest bundle")

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
    manifest = await get_discovery_batch_manifest(
        conn, workspace_id=workspace_id, batch_id=batch_id
    )
    draft = (
        DiscoverySealDraft(
            account_manifest_artifact_key=seal.account_manifest_artifact_key,
            account_manifest_sha256=seal.account_manifest_sha256,
            raw_artifact_manifest_key=seal.raw_artifact_manifest_key,
            claim_id_manifest_key=seal.claim_id_manifest_key,
            coverage_report_ref=seal.coverage_report_ref,
        )
        if seal is not None
        else (manifest.seal_draft if manifest is not None else None)
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
