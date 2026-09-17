"""Generic durable ledger for bounded external-research acquisition (M8B E1).

Provider adapters compile and execute requests; later slices materialize claims.  This module owns
the state between those boundaries: exact immutable request lineage, shared-budget reservation,
one dispatch lease, terminal spend classification, immutable snapshots/results/receipts, and
fresh-process replay.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityId,
    EntityType,
    ExternalResearchAcquisitionRequest,
    ExternalResearchCostDisposition,
    ExternalResearchOperationId,
    ExternalResearchOperationState,
    ExternalResearchReconciliationState,
    ExternalResearchSnapshotId,
    ExternalResearchSnapshotRef,
    ExternalResearchSpendOutcome,
    ExternalResearchSubjectKind,
    ProjectPhase,
    ProjectRunId,
    UtcDatetime,
    new_external_research_operation_id,
    new_external_research_snapshot_id,
)
from clue_research.durable.provider_spend import require_provider_spend_capacity
from clue_research.identity import get_account, get_contact, surviving_id


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


def _validate_subject_shape(
    *,
    subject_kind: ExternalResearchSubjectKind,
    contact_id: EntityId | None,
) -> None:
    if subject_kind is ExternalResearchSubjectKind.ACCOUNT and contact_id is not None:
        raise ValueError("account external research cannot carry a contact id")
    if subject_kind is ExternalResearchSubjectKind.CONTACT and contact_id is None:
        raise ValueError("contact external research requires a contact id")


class ExternalResearchOperationRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: ExternalResearchOperationId
    workspace_id: str
    project_id: str
    project_run_id: UUID
    subject_kind: ExternalResearchSubjectKind
    account_id: EntityId
    contact_id: EntityId | None = None
    contact_selection_id: UUID | None = None
    contact_selection_sha256: str | None = None
    contact_intent_sha256: str | None = None
    source_key: str
    observation_window: str
    freshness_seconds: int
    reuse_fingerprint: str
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

    @model_validator(mode="after")
    def _subject_is_exact(self) -> ExternalResearchOperationRow:
        _validate_subject_shape(subject_kind=self.subject_kind, contact_id=self.contact_id)
        authority = (
            self.contact_selection_id,
            self.contact_selection_sha256,
            self.contact_intent_sha256,
        )
        if any(authority) and not all(authority):
            raise ValueError("external research carries partial contact selection authority")
        if self.subject_kind is ExternalResearchSubjectKind.ACCOUNT and any(authority):
            raise ValueError("account external research carries contact selection authority")
        return self

    @property
    def subject_entity_id(self) -> EntityId:
        """The exact entity a provider-neutral dispatcher/materializer must route."""

        if self.subject_kind is ExternalResearchSubjectKind.CONTACT:
            assert self.contact_id is not None
            return self.contact_id
        return self.account_id


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


class ExternalResearchCostReconciliationRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reconciliation_id: UUID
    operation_id: ExternalResearchOperationId
    workspace_id: str
    disposition: ExternalResearchCostDisposition
    settled_cost_cents: Decimal
    evidence_artifact_key: str
    actor_ref: str
    created_at: UtcDatetime


_OPERATION_COLUMNS = (
    "id AS operation_id, workspace_id, project_id, project_run_id, subject_kind::text, "
    "account_id, contact_id, contact_selection_id, contact_selection_sha256, "
    "contact_intent_sha256, source_key, "
    "observation_window, freshness_seconds, reuse_fingerprint, request_fingerprint, "
    "wire_request_sha256, state::text, "
    "spend_outcome::text, request_artifact_key, cost_cents_reserved, provider_request_id, "
    "dispatch_lease_expires_at, fresh_until, failure_code, terminal_at"
)


def _operation(row: object) -> ExternalResearchOperationRow:
    return ExternalResearchOperationRow.model_validate(row)


async def _require_canonical_subject(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: ExternalResearchSubjectKind,
    account_id: EntityId,
    contact_id: EntityId | None,
) -> None:
    """Fail closed unless the subject is the current canonical entity under the exact account.

    A merge never rewrites immutable provider history. New work must be recompiled for the
    survivor, yielding a survivor-specific request fingerprint; loser snapshots are not silently
    adopted through a name/employer match.
    """

    _validate_subject_shape(subject_kind=subject_kind, contact_id=contact_id)
    account = await get_account(conn, account_id)
    if (
        account is None
        or account.workspace_id != workspace_id
        or await surviving_id(conn, account_id, EntityType.ACCOUNT) != account_id
    ):
        raise ExternalResearchReplayConflict(
            "external research account subject is missing, foreign, or non-canonical"
        )
    if subject_kind is ExternalResearchSubjectKind.ACCOUNT:
        return
    assert contact_id is not None
    contact = await get_contact(conn, contact_id)
    if (
        contact is None
        or contact.workspace_id != workspace_id
        or contact.account_entity_id != account_id
        or await surviving_id(conn, contact_id, EntityType.CONTACT) != contact_id
    ):
        raise ExternalResearchReplayConflict(
            "external research contact must be the canonical contact under the exact account"
        )


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


async def _lock_external_research_reuse(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    reuse_fingerprint: str,
) -> None:
    """Serialize semantic-equivalent reserve/reuse decisions across runs and windows.

    A transaction-scoped advisory lock is appropriate here because a ready operation eventually
    expires and therefore cannot carry a permanent UNIQUE constraint on the semantic key. A hash
    collision only serializes unrelated requests; it cannot merge them because the subsequent
    lookup still compares the full digest and immutable lineage.
    """

    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:reuse_key, 0))"),
        {"reuse_key": f"{workspace_id}:{reuse_fingerprint}"},
    )


async def find_reusable_external_research_operation(
    conn: AsyncConnection,
    *,
    request: ExternalResearchAcquisitionRequest,
    now: datetime,
) -> ExternalResearchOperationRow | None:
    """Find one semantic-equivalent active operation or a still-fresh ready snapshot."""

    await _require_canonical_subject(
        conn,
        workspace_id=request.workspace_id,
        subject_kind=request.subject_kind,
        account_id=request.account_id,
        contact_id=request.contact_id,
    )
    pin = request.research_directive
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM external_research_operation "
                    "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                    "AND subject_kind=CAST(:subject_kind AS external_research_subject_kind) "
                    "AND account_id=:account_id "
                    "AND contact_id IS NOT DISTINCT FROM :contact_id "
                    "AND source_key=:source_key "
                    "AND icp_key=:icp_key AND icp_version=:icp_version "
                    "AND research_directive_id=:directive_id "
                    "AND research_directive_version=:directive_version "
                    "AND research_directive_sha256=:directive_sha "
                    "AND research_override_id IS NOT DISTINCT FROM :override_id "
                    "AND research_override_sha256 IS NOT DISTINCT FROM :override_sha "
                    "AND freshness_policy_ref=:freshness_policy_ref "
                    "AND freshness_seconds=:freshness_seconds "
                    "AND reuse_fingerprint=:reuse_fingerprint "
                    "AND wire_request_sha256=:wire_request_sha256 "
                    "AND NOT EXISTS (SELECT 1 FROM external_research_operation_stop stop "
                    "WHERE stop.operation_id=external_research_operation.id) "
                    "AND (state IN ('planned', 'dispatching') "
                    "     OR (state='ready' AND fresh_until > :now)) "
                    "ORDER BY CASE WHEN state='ready' THEN 0 ELSE 1 END, "
                    "fresh_until DESC NULLS LAST, created_at DESC LIMIT 1"
                ),
                {
                    "workspace_id": request.workspace_id,
                    "project_id": request.project_id,
                    "subject_kind": request.subject_kind.value,
                    "account_id": request.account_id,
                    "contact_id": request.contact_id,
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
                    "reuse_fingerprint": request.reuse_fingerprint,
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
    now: datetime,
    enforce_budget: bool = True,
) -> tuple[ExternalResearchOperationRow, bool]:
    """Atomically reuse or reserve one semantic request without duplicate capacity.

    This function is the sole lock owner.  Callers may perform an unlocked reusable lookup as a
    fast path, but correctness never depends on composing a separate lock/lookup before reserve.
    Under the transaction-scoped reuse lock we repeat the semantic lookup, validate exact replay,
    check provider-spend capacity, and insert the planned operation.
    """

    await _lock_external_research_reuse(
        conn,
        workspace_id=request.workspace_id,
        reuse_fingerprint=request.reuse_fingerprint,
    )
    reusable = await find_reusable_external_research_operation(
        conn,
        request=request,
        now=now,
    )
    if reusable is not None:
        return reusable, False
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
        entity_research_job_id=request.entity_research_job_id,
        enforce_budget=enforce_budget,
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
                contact_id, contact_selection_id, contact_selection_sha256,
                contact_intent_sha256, icp_key, icp_version, research_directive_id,
                research_directive_version, research_directive_sha256, research_override_id,
                research_override_sha256, source_key, observation_window, freshness_policy_ref,
                freshness_seconds, reuse_fingerprint, request_fingerprint,
                wire_request_sha256, request_json,
                state, spend_outcome,
                request_artifact_key, cost_cents_reserved
            ) VALUES (
                :id, :workspace_id, :project_id, :project_run_id,
                CAST(:subject_kind AS external_research_subject_kind), :account_id, :contact_id,
                :contact_selection_id, :contact_selection_sha, :contact_intent_sha,
                :icp_key, :icp_version, :directive_id, :directive_version, :directive_sha,
                :override_id, :override_sha, :source_key, :observation_window,
                :freshness_policy_ref, :freshness_seconds, :reuse_fingerprint,
                :request_fingerprint,
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
            "contact_selection_id": None,
            "contact_selection_sha": None,
            "contact_intent_sha": None,
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
            "reuse_fingerprint": request.reuse_fingerprint,
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
        stored.subject_kind is not request.subject_kind
        or stored.account_id != request.account_id
        or stored.contact_id != request.contact_id
        or stored.project_run_id != request.project_run_id
        or stored.reuse_fingerprint != request.reuse_fingerprint
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
    recover_spend_unknown: bool = False,
    recovery_parser_version: str | None = None,
    recovery_actor_ref: str | None = None,
) -> ExternalResearchSnapshotRef:
    operation = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id, for_update=True
    )
    expected_state = (
        ExternalResearchOperationState.SPEND_OUTCOME_UNKNOWN
        if recover_spend_unknown
        else ExternalResearchOperationState.DISPATCHING
    )
    if operation.state is not expected_state:
        raise ExternalResearchTransitionConflict(
            f"cannot settle external research from {operation.state.value}"
        )
    if recover_spend_unknown:
        if not (recovery_parser_version or "").strip() or not (recovery_actor_ref or "").strip():
            raise ValueError("spend-unknown recovery requires parser version and actor")
        reconciled = (
            await conn.execute(
                text(
                    "SELECT 1 FROM external_research_cost_reconciliation "
                    "WHERE workspace_id=:workspace_id AND operation_id=:operation_id"
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        ).scalar_one_or_none()
        if reconciled is not None:
            raise ExternalResearchTransitionConflict(
                "a billing-reconciled spend-unknown response cannot become a ready snapshot"
            )
        await conn.execute(
            text(
                "INSERT INTO external_research_response_recovery ("
                "recovery_id, operation_id, workspace_id, response_artifact_key, "
                "provider_request_id, parser_version, actor_ref, recovered_at) VALUES ("
                ":recovery_id, :operation_id, :workspace_id, :response_key, "
                ":provider_request_id, :parser_version, :actor_ref, :now)"
            ),
            {
                "recovery_id": uuid4(),
                "operation_id": operation_id,
                "workspace_id": workspace_id,
                "response_key": response_artifact_key,
                "provider_request_id": provider_request_id,
                "parser_version": recovery_parser_version,
                "actor_ref": recovery_actor_ref,
                "now": now,
            },
        )
    stopped = (
        await conn.execute(
            text(
                "SELECT 1 FROM external_research_operation_stop "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).scalar_one_or_none()
    if stopped is not None:
        # The operation lock serializes this fence with cancellation/objection/erasure. The
        # caller settles already-dispatched cost through the stopped-operation receipt; this
        # transaction must not create a snapshot or materializable provider artifacts.
        raise ExternalResearchTransitionConflict("external research authority was stopped")
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
    attempt = await conn.execute(
        text(
            "UPDATE external_research_attempt SET state='responded', "
            "response_artifact_key=:response_key, provider_request_id=:provider_request_id, "
            "failure_code=NULL, failure_detail=NULL, dispatch_lease_expires_at=NULL, "
            "completed_at=CASE WHEN :recover THEN completed_at ELSE :now END "
            "WHERE operation_id=:operation_id AND ordinal=:ordinal "
            "AND state=CAST(:expected_state AS external_research_attempt_state) "
            "AND (:recover = false OR response_artifact_key=:response_key)"
        ),
        {
            "operation_id": operation_id,
            "ordinal": attempt_ordinal,
            "response_key": response_artifact_key,
            "provider_request_id": provider_request_id,
            "expected_state": expected_state.value,
            "recover": recover_spend_unknown,
            "now": now,
        },
    )
    if attempt.rowcount != 1:
        raise ExternalResearchTransitionConflict(
            "external research success attempt no longer matches its retained response"
        )
    await conn.execute(
        text(
            """
            INSERT INTO external_research_snapshot (
                id, operation_id, workspace_id, subject_kind, account_id, contact_id, source_key,
                request_fingerprint,
                request_artifact_key, response_artifact_key, normalization_artifact_key,
                provider_request_id, provider_reported_cost_cents, all_null, fresh_until
            ) VALUES (
                :id, :operation_id, :workspace_id,
                CAST(:subject_kind AS external_research_subject_kind), :account_id, :contact_id,
                :source_key,
                :request_fingerprint, :request_key, :response_key, :normalization_key,
                :provider_request_id, :reported_cost, :all_null, :fresh_until
            )
            """
        ),
        {
            "id": snapshot_id,
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "subject_kind": operation.subject_kind.value,
            "account_id": operation.account_id,
            "contact_id": operation.contact_id,
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
            "dispatch_lease_expires_at=NULL, fresh_until=:fresh_until, failure_code=NULL, "
            "failure_detail=NULL, terminal_at=:now, updated_at=:now WHERE id=:operation_id"
        ),
        {
            "operation_id": operation_id,
            "provider_request_id": provider_request_id,
            "fresh_until": fresh_until,
            "now": now,
        },
    )
    snapshot = await get_external_research_snapshot(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )
    await _insert_snapshot_use(
        conn,
        operation=operation,
        snapshot=snapshot,
        project_run_id=operation.project_run_id,
        consumer_request_fingerprint=operation.request_fingerprint,
        consumer_observation_window=operation.observation_window,
        adopted_at=now,
    )
    return snapshot


async def complete_external_research_cancelled_after_dispatch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    attempt_ordinal: int,
    provider_request_id: str,
    provider_reported_cost_cents: Decimal,
    receipt_artifact_key: str,
    failure_code: str,
    now: datetime,
) -> ExternalResearchOperationRow:
    """Settle accepted provider work without creating a reusable/materializable snapshot."""

    operation = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id, for_update=True
    )
    if operation.state is not ExternalResearchOperationState.DISPATCHING:
        return operation
    if provider_reported_cost_cents > operation.cost_cents_reserved:
        await _mark_unknown_sql(
            conn,
            operation=operation,
            now=now,
            failure_code="provider_cost_exceeds_reservation_after_stop",
            failure_detail="stopped operation reported cost above its reservation",
        )
        return await get_external_research_operation(
            conn, workspace_id=workspace_id, operation_id=operation_id
        )
    await conn.execute(
        text(
            "UPDATE external_research_attempt SET state='failed_terminal', "
            "provider_request_id=:provider_request_id, failure_code=:failure_code, "
            "failure_detail='authority stopped after provider dispatch', "
            "dispatch_lease_expires_at=NULL, completed_at=:now WHERE "
            "operation_id=:operation_id AND ordinal=:ordinal AND state='dispatching'"
        ),
        {
            "operation_id": operation_id,
            "ordinal": attempt_ordinal,
            "provider_request_id": provider_request_id,
            "failure_code": failure_code,
            "now": now,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO external_research_receipt (id, operation_id, workspace_id, source_key, "
            "provider_request_id, cost_cents_reserved, provider_reported_cost_cents, "
            "settled_cost_cents, reconciliation_state, receipt_artifact_key) VALUES "
            "(:id, :operation_id, :workspace_id, :source_key, :provider_request_id, :reserved, "
            ":reported, :reported, 'pending_provider_billing', :receipt_key)"
        ),
        {
            "id": uuid4(),
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "source_key": operation.source_key,
            "provider_request_id": provider_request_id,
            "reserved": operation.cost_cents_reserved,
            "reported": provider_reported_cost_cents,
            "receipt_key": receipt_artifact_key,
        },
    )
    await conn.execute(
        text("UPDATE project_run SET spent_cents=spent_cents+:cost WHERE id=:project_run_id"),
        {"project_run_id": operation.project_run_id, "cost": provider_reported_cost_cents},
    )
    await conn.execute(
        text(
            "UPDATE external_research_operation SET state='cancelled', "
            "spend_outcome='provider_reported', provider_request_id=:provider_request_id, "
            "dispatch_lease_expires_at=NULL, failure_code=:failure_code, terminal_at=:now, "
            "updated_at=:now WHERE id=:operation_id"
        ),
        {
            "operation_id": operation_id,
            "provider_request_id": provider_request_id,
            "failure_code": failure_code,
            "now": now,
        },
    )
    return await get_external_research_operation(
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
    response_artifact_key: str | None = None,
    provider_request_id: str | None = None,
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
        response_artifact_key=response_artifact_key,
        provider_request_id=provider_request_id,
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
    response_artifact_key: str | None = None,
    provider_request_id: str | None = None,
) -> None:
    await conn.execute(
        text(
            "UPDATE external_research_attempt SET state='spend_outcome_unknown', "
            "failure_code=:failure_code, failure_detail=:failure_detail, "
            "response_artifact_key=COALESCE(:response_key, response_artifact_key), "
            "provider_request_id=COALESCE(:provider_request_id, provider_request_id), "
            "dispatch_lease_expires_at=NULL, completed_at=:now "
            "WHERE operation_id=:operation_id AND state='dispatching'"
        ),
        {
            "operation_id": operation.operation_id,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "response_key": response_artifact_key,
            "provider_request_id": provider_request_id,
            "now": now,
        },
    )
    await conn.execute(
        text(
            "UPDATE external_research_operation SET state='spend_outcome_unknown', "
            "spend_outcome='unknown', dispatch_lease_expires_at=NULL, "
            "provider_request_id=COALESCE(:provider_request_id, provider_request_id), "
            "failure_code=:failure_code, failure_detail=:failure_detail, terminal_at=:now, "
            "updated_at=:now WHERE id=:operation_id"
        ),
        {
            "operation_id": operation.operation_id,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "provider_request_id": provider_request_id,
            "now": now,
        },
    )


async def _insert_snapshot_use(
    conn: AsyncConnection,
    *,
    operation: ExternalResearchOperationRow,
    snapshot: ExternalResearchSnapshotRef,
    project_run_id: UUID,
    consumer_request_fingerprint: str,
    consumer_observation_window: str,
    adopted_at: datetime,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO external_research_snapshot_use ("
            "workspace_id, project_id, project_run_id, subject_kind, account_id, contact_id, "
            "source_key, snapshot_id, "
            "reuse_fingerprint, consumer_request_fingerprint, consumer_observation_window, "
            "adopted_at) VALUES ("
            ":workspace_id, :project_id, :project_run_id, "
            "CAST(:subject_kind AS external_research_subject_kind), :account_id, :contact_id, "
            ":source_key, "
            ":snapshot_id, :reuse_fingerprint, :consumer_fingerprint, :consumer_window, :now) "
            "ON CONFLICT (workspace_id, project_run_id, snapshot_id) DO NOTHING"
        ),
        {
            "workspace_id": operation.workspace_id,
            "project_id": operation.project_id,
            "project_run_id": project_run_id,
            "subject_kind": operation.subject_kind.value,
            "account_id": operation.account_id,
            "contact_id": operation.contact_id,
            "source_key": operation.source_key,
            "snapshot_id": snapshot.snapshot_id,
            "reuse_fingerprint": operation.reuse_fingerprint,
            "consumer_fingerprint": consumer_request_fingerprint,
            "consumer_window": consumer_observation_window,
            "now": adopted_at,
        },
    )


async def adopt_external_research_snapshot(
    conn: AsyncConnection,
    *,
    request: ExternalResearchAcquisitionRequest,
    operation_id: ExternalResearchOperationId,
    now: datetime,
) -> ExternalResearchSnapshotRef:
    """Bind a fresh semantic-equivalent snapshot to the consuming project run exactly once."""

    await _require_canonical_subject(
        conn,
        workspace_id=request.workspace_id,
        subject_kind=request.subject_kind,
        account_id=request.account_id,
        contact_id=request.contact_id,
    )
    operation = await get_external_research_operation(
        conn,
        workspace_id=request.workspace_id,
        operation_id=operation_id,
        for_update=True,
    )
    stopped = (
        await conn.execute(
            text(
                "SELECT 1 FROM external_research_operation_stop "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id"
            ),
            {"workspace_id": request.workspace_id, "operation_id": operation_id},
        )
    ).scalar_one_or_none()
    if (
        stopped is not None
        or operation.state is not ExternalResearchOperationState.READY
        or operation.fresh_until is None
        or operation.fresh_until <= now
        or operation.project_id != request.project_id
        or operation.subject_kind is not request.subject_kind
        or operation.account_id != request.account_id
        or operation.contact_id != request.contact_id
        or operation.source_key != request.source_key
        or operation.reuse_fingerprint != request.reuse_fingerprint
        or operation.wire_request_sha256 != request.wire_request_sha256
    ):
        raise ExternalResearchReplayConflict(
            "ready external research operation is not reusable for this consumer"
        )
    snapshot = await get_external_research_snapshot(
        conn,
        workspace_id=request.workspace_id,
        operation_id=operation_id,
    )
    await _insert_snapshot_use(
        conn,
        operation=operation,
        snapshot=snapshot,
        project_run_id=request.project_run_id,
        consumer_request_fingerprint=request.request_fingerprint,
        consumer_observation_window=request.observation_window,
        adopted_at=now,
    )
    return snapshot


async def get_external_research_cost_reconciliation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
) -> ExternalResearchCostReconciliationRow | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT id AS reconciliation_id, operation_id, workspace_id, "
                    "disposition::text, settled_cost_cents, evidence_artifact_key, actor_ref, "
                    "created_at FROM external_research_cost_reconciliation "
                    "WHERE workspace_id=:workspace_id AND operation_id=:operation_id"
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else ExternalResearchCostReconciliationRow.model_validate(row)


async def reconcile_external_research_cost(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    disposition: ExternalResearchCostDisposition,
    settled_cost_cents: Decimal,
    evidence_artifact_key: str,
    actor_ref: str,
    now: datetime,
) -> ExternalResearchCostReconciliationRow:
    """Append one billing fact and adjust the owning run's recorded spend exactly once."""

    if settled_cost_cents < 0:
        raise ValueError("settled external research cost cannot be negative")
    if disposition is ExternalResearchCostDisposition.NOT_CHARGED and settled_cost_cents != 0:
        raise ValueError("not-charged reconciliation must settle at zero")
    operation = await get_external_research_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id, for_update=True
    )
    existing = await get_external_research_cost_reconciliation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )
    if existing is not None:
        if (
            existing.disposition is not disposition
            or existing.settled_cost_cents != settled_cost_cents
            or existing.evidence_artifact_key != evidence_artifact_key
            or existing.actor_ref != actor_ref
        ):
            raise ExternalResearchReplayConflict(
                "external research cost was already reconciled differently"
            )
        return existing
    if operation.state not in {
        ExternalResearchOperationState.READY,
        ExternalResearchOperationState.SPEND_OUTCOME_UNKNOWN,
    }:
        raise ExternalResearchTransitionConflict(
            "cost reconciliation requires a ready or spend-unknown operation"
        )
    already_recorded = Decimal(0)
    if operation.state is ExternalResearchOperationState.READY:
        already_recorded = Decimal(
            (
                await conn.execute(
                    text(
                        "SELECT settled_cost_cents FROM external_research_receipt "
                        "WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": operation_id},
                )
            ).scalar_one()
        )
    reconciliation_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO external_research_cost_reconciliation ("
            "id, operation_id, workspace_id, disposition, settled_cost_cents, "
            "evidence_artifact_key, actor_ref, created_at) VALUES ("
            ":id, :operation_id, :workspace_id, CAST(:disposition AS "
            "external_research_cost_disposition), :settled, :evidence, :actor, :now)"
        ),
        {
            "id": reconciliation_id,
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "disposition": disposition.value,
            "settled": settled_cost_cents,
            "evidence": evidence_artifact_key,
            "actor": actor_ref,
            "now": now,
        },
    )
    delta = settled_cost_cents - already_recorded
    await conn.execute(
        text("UPDATE project_run SET spent_cents=spent_cents+:delta WHERE id=:project_run_id"),
        {"project_run_id": operation.project_run_id, "delta": delta},
    )
    reconciled = await get_external_research_cost_reconciliation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )
    assert reconciled is not None
    return reconciled


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
                    "subject_kind::text, contact_id, "
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


async def list_ready_external_research_snapshots(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: UUID,
    account_id: EntityId,
    subject_kind: ExternalResearchSubjectKind = ExternalResearchSubjectKind.ACCOUNT,
    contact_id: EntityId | None = None,
    source_key: str,
    research_directive_id: UUID,
    research_directive_version: int,
    research_directive_sha256: str,
    research_override_id: UUID | None,
    research_override_sha256: str | None,
    contact_selection_id: UUID | None = None,
    contact_selection_sha256: str | None = None,
    contact_intent_sha256: str | None = None,
    now: datetime | None = None,
) -> tuple[ExternalResearchSnapshotRef, ...]:
    """Ready snapshots for one exact subject/run/directive/source lineage.

    Materialization never searches by account alone: an older directive, different override,
    sibling project run, or expired snapshot must not become evidence for the current operation.
    Results are newest-first so the materializer can make a newer null/unsupported field outcome
    shadow an older value when an authorized refresh overlaps an earlier bundle.
    """

    observed_at = now or datetime.now(UTC)
    await _require_canonical_subject(
        conn,
        workspace_id=workspace_id,
        subject_kind=subject_kind,
        account_id=account_id,
        contact_id=contact_id,
    )
    contact_authority = (
        contact_selection_id,
        contact_selection_sha256,
        contact_intent_sha256,
    )
    if any(value is not None for value in contact_authority) and not all(
        value is not None for value in contact_authority
    ):
        raise ValueError("contact snapshot lookup requires complete selection authority")
    contact_authority_sql = ""
    contact_authority_params: dict[str, object] = {}
    if contact_selection_id is not None:
        contact_authority_sql = (
            "AND operation.contact_selection_id=:contact_selection_id "
            "AND operation.contact_selection_sha256=:contact_selection_sha256 "
            "AND operation.contact_intent_sha256=:contact_intent_sha256 "
        )
        contact_authority_params = {
            "contact_selection_id": contact_selection_id,
            "contact_selection_sha256": contact_selection_sha256,
            "contact_intent_sha256": contact_intent_sha256,
        }

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT snapshot.id AS snapshot_id, snapshot.operation_id, "
                    "snapshot.workspace_id, snapshot.subject_kind::text, snapshot.account_id, "
                    "snapshot.contact_id, snapshot.source_key, "
                    "snapshot.request_fingerprint, snapshot.request_artifact_key, "
                    "snapshot.response_artifact_key, snapshot.normalization_artifact_key, "
                    "snapshot.provider_request_id, snapshot.provider_reported_cost_cents, "
                    "snapshot.all_null, snapshot.fresh_until "
                    "FROM external_research_snapshot snapshot "
                    "JOIN external_research_operation operation "
                    "ON operation.id=snapshot.operation_id "
                    "AND operation.workspace_id=snapshot.workspace_id "
                    "JOIN external_research_snapshot_use snapshot_use "
                    "ON snapshot_use.snapshot_id=snapshot.id "
                    "AND snapshot_use.workspace_id=snapshot.workspace_id "
                    "WHERE operation.workspace_id=:workspace_id "
                    "AND snapshot_use.project_run_id=:project_run_id "
                    "AND operation.subject_kind=CAST(:subject_kind AS "
                    "external_research_subject_kind) "
                    "AND snapshot.subject_kind=operation.subject_kind "
                    "AND snapshot_use.subject_kind=operation.subject_kind "
                    "AND operation.account_id=:account_id "
                    "AND snapshot.account_id=operation.account_id "
                    "AND snapshot_use.account_id=operation.account_id "
                    "AND operation.contact_id IS NOT DISTINCT FROM :contact_id "
                    "AND snapshot.contact_id IS NOT DISTINCT FROM operation.contact_id "
                    "AND snapshot_use.contact_id IS NOT DISTINCT FROM operation.contact_id "
                    "AND operation.source_key=:source_key "
                    "AND operation.research_directive_id=:directive_id "
                    "AND operation.research_directive_version=:directive_version "
                    "AND operation.research_directive_sha256=:directive_sha256 "
                    "AND operation.research_override_id IS NOT DISTINCT FROM :override_id "
                    "AND operation.research_override_sha256 IS NOT DISTINCT FROM :override_sha "
                    f"{contact_authority_sql}"
                    "AND operation.state='ready' "
                    "AND NOT EXISTS (SELECT 1 FROM external_research_operation_stop stop "
                    "WHERE stop.operation_id=operation.id) "
                    "AND snapshot.fresh_until > :now "
                    "ORDER BY operation.terminal_at DESC, snapshot.created_at DESC, "
                    "operation.id DESC"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_run_id": project_run_id,
                    "subject_kind": subject_kind.value,
                    "account_id": account_id,
                    "contact_id": contact_id,
                    "source_key": source_key,
                    "directive_id": research_directive_id,
                    "directive_version": research_directive_version,
                    "directive_sha256": research_directive_sha256,
                    "override_id": research_override_id,
                    "override_sha": research_override_sha256,
                    "now": observed_at,
                    **contact_authority_params,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(ExternalResearchSnapshotRef.model_validate(row) for row in rows)


async def find_active_external_research_operation_for_materialization(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: UUID,
    account_id: EntityId,
    subject_kind: ExternalResearchSubjectKind = ExternalResearchSubjectKind.ACCOUNT,
    contact_id: EntityId | None = None,
    source_key: str,
    research_directive_id: UUID,
    research_directive_version: int,
    research_directive_sha256: str,
    research_override_id: UUID | None,
    research_override_sha256: str | None,
) -> ExternalResearchOperationRow | None:
    await _require_canonical_subject(
        conn,
        workspace_id=workspace_id,
        subject_kind=subject_kind,
        account_id=account_id,
        contact_id=contact_id,
    )
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM external_research_operation "
                    "WHERE workspace_id=:workspace_id AND project_run_id=:project_run_id "
                    "AND subject_kind=CAST(:subject_kind AS external_research_subject_kind) "
                    "AND account_id=:account_id "
                    "AND contact_id IS NOT DISTINCT FROM :contact_id "
                    "AND source_key=:source_key "
                    "AND research_directive_id=:directive_id "
                    "AND research_directive_version=:directive_version "
                    "AND research_directive_sha256=:directive_sha256 "
                    "AND research_override_id IS NOT DISTINCT FROM :override_id "
                    "AND research_override_sha256 IS NOT DISTINCT FROM :override_sha "
                    "AND NOT EXISTS (SELECT 1 FROM external_research_operation_stop stop "
                    "WHERE stop.operation_id=external_research_operation.id) "
                    "AND state IN ('planned', 'dispatching') "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_run_id": project_run_id,
                    "subject_kind": subject_kind.value,
                    "account_id": account_id,
                    "contact_id": contact_id,
                    "source_key": source_key,
                    "directive_id": research_directive_id,
                    "directive_version": research_directive_version,
                    "directive_sha256": research_directive_sha256,
                    "override_id": research_override_id,
                    "override_sha": research_override_sha256,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _operation(row)


async def list_due_contact_external_research_project_runs(
    conn: AsyncConnection,
    *,
    now: datetime,
    limit: int = 100,
) -> tuple[ProjectRunId, ...]:
    """Find contact operations whose interrupted dispatch lease needs a fresh run wake."""

    if limit < 1:
        raise ValueError("external contact due-run limit must be positive")
    rows = (
        await conn.execute(
            text(
                "SELECT project_run_id, min(dispatch_lease_expires_at) AS due_at "
                "FROM external_research_operation WHERE subject_kind='contact' "
                "AND state='dispatching' AND dispatch_lease_expires_at <= :now "
                "GROUP BY project_run_id ORDER BY due_at, project_run_id LIMIT :limit"
            ),
            {"now": now, "limit": limit},
        )
    ).all()
    return tuple(ProjectRunId(row.project_run_id) for row in rows)


async def list_contact_external_research_operations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    contact_id: EntityId,
) -> tuple[ExternalResearchOperationRow, ...]:
    """Read exact-contact acquisition history for C7 coverage; never dispatch a provider."""

    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_OPERATION_COLUMNS} FROM external_research_operation "
                    "WHERE workspace_id=:workspace_id AND project_run_id=:project_run_id "
                    "AND subject_kind='contact' AND account_id=:account_id "
                    "AND contact_id=:contact_id ORDER BY terminal_at DESC NULLS FIRST, id DESC"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_run_id": project_run_id,
                    "account_id": account_id,
                    "contact_id": contact_id,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(_operation(row) for row in rows)


__all__ = [
    "ExternalResearchCostReconciliationRow",
    "ExternalResearchDispatchClaim",
    "ExternalResearchDispatchDecision",
    "ExternalResearchLedgerError",
    "ExternalResearchNotFound",
    "ExternalResearchOperationRow",
    "ExternalResearchReplayConflict",
    "ExternalResearchResultArtifactInput",
    "ExternalResearchTransitionConflict",
    "adopt_external_research_snapshot",
    "claim_external_research_dispatch",
    "complete_external_research_pre_dispatch_failure",
    "complete_external_research_cancelled_after_dispatch",
    "complete_external_research_success",
    "find_external_research_operation",
    "find_active_external_research_operation_for_materialization",
    "find_reusable_external_research_operation",
    "get_external_research_cost_reconciliation",
    "get_external_research_operation",
    "get_external_research_snapshot",
    "list_external_research_result_artifacts",
    "list_due_contact_external_research_project_runs",
    "list_contact_external_research_operations",
    "list_ready_external_research_snapshots",
    "mark_external_research_spend_unknown",
    "reconcile_external_research_cost",
    "reserve_external_research_operation",
]
