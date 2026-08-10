"""Pre-seal required-field waterfall using bounded Sumble organization snapshots."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, SecretStr

from clue_api.sumble_claim_materialization import (
    SumbleClaimMaterializer,
    SumbleFieldDisposition,
)
from clue_config import Secrets, Settings
from clue_core import (
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryFieldResolution,
    DiscoveryFieldResolutionState,
    DiscoveryGapFieldPlan,
    DiscoveryGapFieldResult,
    DiscoveryGapFieldState,
    DiscoveryGapOperation,
    DiscoveryGapOperationState,
    DiscoveryGapRequest,
    DiscoveryGapSpendOutcome,
    EntityId,
    EntityType,
    PhaseContext,
    ProjectPhase,
    new_discovery_gap_operation_id,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    claims_for,
    get_effective_field,
)
from clue_research.discovery_scoring.tiering import classify_required_criteria_claims
from clue_research.discovery_scoring.tiering.selection import DiscoveryCriterionDecision
from clue_research.durable import (
    DiscoveryGapNotFound,
    DiscoveryGapReplayConflict,
    ProjectRunStatus,
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    claim_discovery_gap_operation,
    find_discovery_gap_operation,
    get_current_discovery_batch,
    get_discovery_batch,
    get_discovery_field_resolution,
    get_discovery_gap_operation,
    get_discovery_plan,
    get_project_run,
    list_discovery_field_resolutions,
    list_discovery_gap_field_results,
    list_discovery_gap_operations,
    put_discovery_field_resolution,
    put_discovery_gap_field_result,
    reserve_discovery_gap_operation,
    update_discovery_gap_operation,
)
from clue_research.identity import get_account, surviving_id
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_API_BASE,
    SUMBLE_API_VERSION,
    SumbleClient,
    SumbleCreditBudget,
    SumbleOrganizationsResponse,
    SumbleSnapshot,
    organization_request,
)
from clue_storage import StorageBackend, content_address

SUMBLE_DISCOVERY_GAP_CONTRACT_VERSION: Final = (
    "sumble-v9-openapi-c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c"
)
SUMBLE_DISCOVERY_GAP_POLICY_VERSION: Final = "sumble-discovery-required-fields-v1"
SUMBLE_DISCOVERY_GAP_PRICING_VERSION: Final = "sumble-v9-credits-2026-08-03"
DISCOVERY_PROVENANCE_FIELD: Final = "core.discovery_provenance"

_SUMBLE_FIELD_BY_LOGICAL: Final[dict[str, str]] = {
    "discovery.industry": "core.industry",
    "discovery.employee_size": "core.employee_count",
    "discovery.headquarters": "core.hq_location",
}


class SumbleDiscoveryGapError(RuntimeError):
    pass


class SumbleDiscoveryGapOutcome(StrEnum):
    COMPLETE = "complete"
    WAITING_EXTERNAL = "waiting_external"
    BLOCKED_REVIEW = "blocked_review"


class SumbleDiscoveryGapProgress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: SumbleDiscoveryGapOutcome
    pending_before: int
    provider_calls: int = 0
    operations_created: int = 0
    operations_replayed: int = 0
    fields_resolved: int = 0
    fields_terminal_missing: int = 0
    fields_blocked_by_policy: int = 0


class SumbleDiscoveryGapPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = SUMBLE_DISCOVERY_GAP_POLICY_VERSION
    expected_value_credits_per_field: Decimal = Decimal(2)
    low_confidence_threshold: float = 0.8
    in_flight_grace_seconds: int = 60


DEFAULT_SUMBLE_DISCOVERY_GAP_POLICY = SumbleDiscoveryGapPolicy()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()


def _criteria_for_plan(plan: object) -> tuple[str, ...]:
    descriptions: list[str] = []
    for search in plan.searches:  # type: ignore[attr-defined]
        for criterion in search.criteria:
            if criterion.description not in descriptions:
                descriptions.append(criterion.description)
    if not descriptions:
        raise SumbleDiscoveryGapError("discovery-gap eligibility requires planned criteria")
    return tuple(descriptions)


class SumbleDiscoveryGapResolver:
    """Terminalize every pending required field before D5 is allowed to seal."""

    def __init__(
        self,
        *,
        enabled: bool,
        api_key: SecretStr | None,
        storage: StorageBackend,
        cents_per_credit: Decimal = Decimal(0),
        conn_factory: ConnFactory = transaction,
        policy: SumbleDiscoveryGapPolicy = DEFAULT_SUMBLE_DISCOVERY_GAP_POLICY,
        client_factory: Callable[[int, Decimal], SumbleClient] | None = None,
        enforce_budget: bool = True,
    ) -> None:
        if enabled and api_key is None:
            raise ValueError("enabled Sumble discovery gaps require an API key")
        self._enabled = enabled
        self._api_key = api_key
        self._storage = storage
        self._cents_per_credit = cents_per_credit
        self._conn_factory = conn_factory
        self._policy = policy
        self._client_factory = client_factory
        self._materializer = SumbleClaimMaterializer(conn_factory=conn_factory)
        # FI pilot budget-controls: threaded from ``Settings.budget_controls_enabled`` at
        # the composition root and passed to the durable reservation, which stops raising
        # on the project-run cap while writing every ledger row unchanged.
        self._enforce_budget = enforce_budget

    async def ensure_terminal(
        self, ctx: PhaseContext, batch_id: DiscoveryBatchId
    ) -> SumbleDiscoveryGapProgress:
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, ctx.project_run_id)
            batch = await get_discovery_batch(
                conn, workspace_id=ctx.workspace_id, batch_id=batch_id
            )
            current = await get_current_discovery_batch(
                conn,
                workspace_id=ctx.workspace_id,
                project_run_id=ctx.project_run_id,
            )
            if (
                run is None
                or run.workspace_id != ctx.workspace_id
                or run.status is not ProjectRunStatus.ACTIVE
                or run.phase is not ProjectPhase.DISCOVERY
                or batch is None
                or current is None
                or batch.id != current.id
                or batch.state
                in {
                    DiscoveryBatchState.SEALED,
                    DiscoveryBatchState.CANCELLED_UNSEALED,
                    DiscoveryBatchState.FAILED_TERMINAL,
                }
                or batch.project_id != ctx.project_id
                or batch.icp_key != ctx.icp_key
                or batch.icp_version != ctx.icp_version
            ):
                raise SumbleDiscoveryGapError(
                    "required-field waterfall requires the active current discovery generation"
                )
            plan_row = await get_discovery_plan(
                conn,
                workspace_id=ctx.workspace_id,
                plan_id=batch.discovery_plan_id,
            )
            if plan_row is None:
                raise SumbleDiscoveryGapError("required-field waterfall lost its discovery plan")
            operations = await list_discovery_gap_operations(
                conn,
                workspace_id=ctx.workspace_id,
                batch_id=batch_id,
            )

        totals = {
            "provider_calls": 0,
            "operations_created": 0,
            "operations_replayed": 0,
            "fields_resolved": 0,
            "fields_terminal_missing": 0,
            "fields_blocked_by_policy": 0,
        }
        blocked_review = False
        # A crash may occur after field reconciliation commits but before the operation-success
        # receipt does. Resume from the durable provider snapshot even when no field remains
        # pending, otherwise D5 would wait forever on operation terminality.
        for operation in operations:
            if operation.state is not DiscoveryGapOperationState.MATERIALIZING:
                continue
            succeeded, resolved, missing = await self._finish_materializing(operation)
            totals["operations_replayed"] += 1
            totals["fields_resolved"] += resolved
            totals["fields_terminal_missing"] += missing
            blocked_review = blocked_review or not succeeded

        async with self._conn_factory() as conn:
            pending = await list_discovery_field_resolutions(
                conn,
                workspace_id=ctx.workspace_id,
                batch_id=batch_id,
                state=DiscoveryFieldResolutionState.PENDING,
            )
        if not pending:
            return SumbleDiscoveryGapProgress(
                outcome=(
                    SumbleDiscoveryGapOutcome.BLOCKED_REVIEW
                    if blocked_review
                    else SumbleDiscoveryGapOutcome.COMPLETE
                ),
                pending_before=0,
                **totals,
            )

        required_fields = {str(value) for value in plan_row.plan.required_account_fields}
        required_criteria = _criteria_for_plan(plan_row.plan)
        grouped: dict[EntityId, list[DiscoveryFieldResolution]] = defaultdict(list)
        for resolution in pending:
            if str(resolution.logical_field_key) not in required_fields:
                raise SumbleDiscoveryGapError("optional discovery field was left pending")
            grouped[resolution.account_entity_id].append(resolution)

        waiting = False
        for account_id, resolutions in sorted(grouped.items(), key=lambda item: str(item[0])):
            result = await self._resolve_account(
                ctx=ctx,
                batch_id=batch_id,
                account_id=account_id,
                resolutions=tuple(resolutions),
                required_criteria=required_criteria,
                field_policy_version=plan_row.plan.field_policy_version,
            )
            for key in totals:
                totals[key] += int(getattr(result, key))
            waiting = waiting or result.outcome is SumbleDiscoveryGapOutcome.WAITING_EXTERNAL
            blocked_review = (
                blocked_review or result.outcome is SumbleDiscoveryGapOutcome.BLOCKED_REVIEW
            )
        outcome = (
            SumbleDiscoveryGapOutcome.WAITING_EXTERNAL
            if waiting
            else (
                SumbleDiscoveryGapOutcome.BLOCKED_REVIEW
                if blocked_review
                else SumbleDiscoveryGapOutcome.COMPLETE
            )
        )
        return SumbleDiscoveryGapProgress(
            outcome=outcome,
            pending_before=len(pending),
            **totals,
        )

    async def _resolve_account(
        self,
        *,
        ctx: PhaseContext,
        batch_id: DiscoveryBatchId,
        account_id: EntityId,
        resolutions: tuple[DiscoveryFieldResolution, ...],
        required_criteria: tuple[str, ...],
        field_policy_version: str,
    ) -> SumbleDiscoveryGapProgress:
        unsupported = tuple(
            value
            for value in resolutions
            if str(value.logical_field_key) not in _SUMBLE_FIELD_BY_LOGICAL
        )
        if unsupported:
            await self._terminalize_without_provider(
                workspace_id=ctx.workspace_id,
                resolutions=unsupported,
                state=DiscoveryFieldResolutionState.CONFIRMED_MISSING,
                reason="required_field_waterfall_exhausted_after_exa",
            )
        supported = tuple(value for value in resolutions if value not in unsupported)
        if not supported:
            return SumbleDiscoveryGapProgress(
                outcome=SumbleDiscoveryGapOutcome.COMPLETE,
                pending_before=len(resolutions),
                fields_terminal_missing=len(unsupported),
            )

        async with self._conn_factory() as conn:
            if await surviving_id(conn, account_id, EntityType.ACCOUNT) != account_id:
                raise SumbleDiscoveryGapError("discovery-gap account is not the canonical survivor")
            account = await get_account(conn, account_id)
            if (
                account is None
                or account.workspace_id != ctx.workspace_id
                or not account.primary_domain
            ):
                raise SumbleDiscoveryGapError(
                    "discovery-gap account lacks a workspace-local canonical domain"
                )
            provenance = await claims_for(
                conn,
                account_id,
                DISCOVERY_PROVENANCE_FIELD,
                scope=WorkspaceScope.for_workspace(ctx.workspace_id),
            )
        reviews = classify_required_criteria_claims(
            claims=provenance,
            required_criteria=required_criteria,
        )
        eligibility_claim_ids = tuple(
            sorted(
                {observation.claim_id for review in reviews for observation in review.observations},
                key=str,
            )
        )
        decisions = {review.decision for review in reviews}
        if decisions != {DiscoveryCriterionDecision.YES} or not eligibility_claim_ids:
            reason = "required_field_waterfall_ineligible:criteria_" + "_".join(
                sorted(value.value for value in decisions)
            )
            await self._terminalize_without_provider(
                workspace_id=ctx.workspace_id,
                resolutions=supported,
                state=DiscoveryFieldResolutionState.BLOCKED_BY_POLICY,
                reason=reason,
                additional_claim_ids=eligibility_claim_ids,
            )
            return SumbleDiscoveryGapProgress(
                outcome=SumbleDiscoveryGapOutcome.COMPLETE,
                pending_before=len(resolutions),
                fields_terminal_missing=len(unsupported),
                fields_blocked_by_policy=len(supported),
            )
        if not self._enabled:
            await self._terminalize_without_provider(
                workspace_id=ctx.workspace_id,
                resolutions=supported,
                state=DiscoveryFieldResolutionState.BLOCKED_BY_POLICY,
                reason="required_field_waterfall_source_disabled:sumble_organizations",
                additional_claim_ids=eligibility_claim_ids,
            )
            return SumbleDiscoveryGapProgress(
                outcome=SumbleDiscoveryGapOutcome.COMPLETE,
                pending_before=len(resolutions),
                fields_terminal_missing=len(unsupported),
                fields_blocked_by_policy=len(supported),
            )

        field_plans: list[DiscoveryGapFieldPlan] = []
        async with self._conn_factory() as conn:
            for resolution in supported:
                logical_key = str(resolution.logical_field_key)
                field_key = _SUMBLE_FIELD_BY_LOGICAL[logical_key]
                definition = await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(ctx.workspace_id),
                    field_key=field_key,
                )
                if (
                    definition is None
                    or ORGANIZATIONS_SOURCE_KEY not in definition.field_def.tier_plan
                ):
                    raise SumbleDiscoveryGapError(
                        f"registered field waterfall does not admit Sumble for {field_key}"
                    )
                field_plans.append(
                    DiscoveryGapFieldPlan(
                        logical_field_key=resolution.logical_field_key,
                        field_key=field_key,
                        source_key=ORGANIZATIONS_SOURCE_KEY,
                        expected_value_credits=self._policy.expected_value_credits_per_field,
                        basis_claim_ids=resolution.claim_ids,
                        source_item_ids=resolution.source_item_ids,
                    )
                )
        field_plans.sort(key=lambda value: str(value.logical_field_key))
        provider_fields = tuple(str(value.field_key) for value in field_plans)
        organization_body, provider_cap = organization_request(
            account.primary_domain,
            field_keys=provider_fields,
        )
        expected = sum(
            (value.expected_value_credits for value in field_plans),
            Decimal(0),
        )
        request = DiscoveryGapRequest(
            workspace_id=ctx.workspace_id,
            project_id=ctx.project_id,
            project_run_id=ctx.project_run_id,
            icp_key=ctx.icp_key,
            icp_version=ctx.icp_version,
            discovery_batch_id=batch_id,
            account_id=account_id,
            primary_domain=account.primary_domain,
            source_key=ORGANIZATIONS_SOURCE_KEY,
            provider_api_version=SUMBLE_API_VERSION,
            provider_contract_version=SUMBLE_DISCOVERY_GAP_CONTRACT_VERSION,
            pricing_policy_version=SUMBLE_DISCOVERY_GAP_PRICING_VERSION,
            field_policy_version=field_policy_version,
            observation_window=(
                f"discovery-batch:{batch_id}:required-fields:{self._policy.version}"
            ),
            required_criteria=required_criteria,
            eligibility_claim_ids=eligibility_claim_ids,
            fields=tuple(field_plans),
            provider_credit_cap=provider_cap,
            expected_value_credits=expected,
            money_budget_cap_cents=Decimal(provider_cap) * self._cents_per_credit,
        )
        operation, created = await self._reserve(request, organization_body)
        terminal = operation.state in {
            DiscoveryGapOperationState.SUCCEEDED,
            DiscoveryGapOperationState.FAILED_TERMINAL,
            DiscoveryGapOperationState.SPEND_OUTCOME_UNKNOWN,
            DiscoveryGapOperationState.CANCELLED,
        }
        if terminal:
            return SumbleDiscoveryGapProgress(
                outcome=(
                    SumbleDiscoveryGapOutcome.COMPLETE
                    if operation.state is DiscoveryGapOperationState.SUCCEEDED
                    else SumbleDiscoveryGapOutcome.BLOCKED_REVIEW
                ),
                pending_before=len(resolutions),
                operations_replayed=1,
                fields_terminal_missing=len(unsupported),
            )
        if operation.state is DiscoveryGapOperationState.DISPATCHING:
            if operation.updated_at and datetime.now(UTC) - operation.updated_at < timedelta(
                seconds=self._policy.in_flight_grace_seconds
            ):
                return SumbleDiscoveryGapProgress(
                    outcome=SumbleDiscoveryGapOutcome.WAITING_EXTERNAL,
                    pending_before=len(resolutions),
                    operations_replayed=int(not created),
                    fields_terminal_missing=len(unsupported),
                )
            await self._mark_unknown(operation, "crash_after_possible_sumble_dispatch")
            return SumbleDiscoveryGapProgress(
                outcome=SumbleDiscoveryGapOutcome.BLOCKED_REVIEW,
                pending_before=len(resolutions),
                operations_replayed=int(not created),
                fields_terminal_missing=len(unsupported),
            )
        if operation.state in {
            DiscoveryGapOperationState.PLANNED,
            DiscoveryGapOperationState.FAILED_RETRYABLE,
        }:
            async with self._conn_factory() as conn:
                claimed = await claim_discovery_gap_operation(
                    conn,
                    workspace_id=ctx.workspace_id,
                    operation_id=operation.operation_id,
                )
            if claimed is None:
                return SumbleDiscoveryGapProgress(
                    outcome=SumbleDiscoveryGapOutcome.WAITING_EXTERNAL,
                    pending_before=len(resolutions),
                    operations_replayed=int(not created),
                    fields_terminal_missing=len(unsupported),
                )
            operation = claimed

        provider_calls = 0
        if operation.state is DiscoveryGapOperationState.DISPATCHING:
            assert self._api_key is not None
            client = (
                self._client_factory(provider_cap, self._cents_per_credit)
                if self._client_factory is not None
                else SumbleClient(
                    api_key=self._api_key,
                    budget=SumbleCreditBudget(maximum=provider_cap),
                    cents_per_credit=self._cents_per_credit,
                )
            )
            try:
                snapshot = await asyncio.to_thread(
                    client.resolve_organization,
                    request.primary_domain,
                    field_keys=provider_fields,
                )
                provider_calls = 1
                operation = await self._persist_snapshot(operation, snapshot)
            except Exception:
                await self._mark_unknown(operation, "sumble_paid_dispatch_unreconciled")
                return SumbleDiscoveryGapProgress(
                    outcome=SumbleDiscoveryGapOutcome.BLOCKED_REVIEW,
                    pending_before=len(resolutions),
                    provider_calls=provider_calls + 1,
                    operations_created=int(created),
                    operations_replayed=int(not created),
                    fields_terminal_missing=len(unsupported),
                )
        succeeded, resolved, missing = await self._finish_materializing(operation)
        if not succeeded:
            return SumbleDiscoveryGapProgress(
                outcome=SumbleDiscoveryGapOutcome.BLOCKED_REVIEW,
                pending_before=len(resolutions),
                provider_calls=provider_calls,
                operations_created=int(created),
                operations_replayed=int(not created),
                fields_terminal_missing=len(unsupported),
            )
        return SumbleDiscoveryGapProgress(
            outcome=SumbleDiscoveryGapOutcome.COMPLETE,
            pending_before=len(resolutions),
            provider_calls=provider_calls,
            operations_created=int(created),
            operations_replayed=int(not created),
            fields_resolved=resolved,
            fields_terminal_missing=len(unsupported) + missing,
        )

    async def _finish_materializing(
        self,
        operation: DiscoveryGapOperation,
    ) -> tuple[bool, int, int]:
        try:
            snapshot = await self._load_snapshot(operation)
            resolved, missing = await self._materialize_and_reconcile(operation, snapshot)
            receipt_key = await self._receipt(operation)
            async with self._conn_factory() as conn:
                current = await get_discovery_gap_operation(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                    for_update=True,
                )
                if current is None:
                    raise DiscoveryGapNotFound("discovery-gap success operation")
                if current.state is DiscoveryGapOperationState.SUCCEEDED:
                    return True, resolved, missing
                if current.state is not DiscoveryGapOperationState.MATERIALIZING:
                    raise DiscoveryGapReplayConflict(
                        "discovery-gap materialization resumed from an incompatible state"
                    )
                await update_discovery_gap_operation(
                    conn,
                    operation=current.model_copy(
                        update={
                            "state": DiscoveryGapOperationState.SUCCEEDED,
                            "receipt_artifact_key": receipt_key,
                            "terminal_at": datetime.now(UTC),
                        }
                    ),
                )
            return True, resolved, missing
        except Exception as exc:
            await self._fail_materialization(operation, type(exc).__name__)
            return False, 0, 0

    async def _terminalize_without_provider(
        self,
        *,
        workspace_id: str,
        resolutions: Sequence[DiscoveryFieldResolution],
        state: DiscoveryFieldResolutionState,
        reason: str,
        additional_claim_ids: Sequence[object] = (),
    ) -> None:
        async with self._conn_factory() as conn:
            for resolution in resolutions:
                await put_discovery_field_resolution(
                    conn,
                    workspace_id=workspace_id,
                    resolution=resolution.model_copy(
                        update={
                            "state": state,
                            "claim_ids": tuple(
                                sorted(
                                    {*resolution.claim_ids, *additional_claim_ids},
                                    key=str,
                                )
                            ),
                            "winning_claim_id": None,
                            "reason_code": reason,
                            "updated_at": datetime.now(UTC),
                        }
                    ),
                )

    async def _reserve(
        self,
        request: DiscoveryGapRequest,
        organization_body: Mapping[str, object],
    ) -> tuple[DiscoveryGapOperation, bool]:
        async with self._conn_factory() as conn:
            existing = await find_discovery_gap_operation(
                conn,
                workspace_id=request.workspace_id,
                batch_id=request.discovery_batch_id,
                account_id=request.account_id,
                source_key=request.source_key,
                observation_window=request.observation_window,
            )
            if existing is not None:
                if existing.request != request:
                    raise DiscoveryGapReplayConflict(
                        "same discovery-gap source window was replayed with a changed request"
                    )
                return existing, False
            request_payload = {
                "contract": "discovery-required-field-gap-request-v1",
                "request": request.model_dump(mode="json"),
                "wire": {"method": "POST", "path": "/organizations", "body": organization_body},
            }
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=_json_bytes(request_payload),
                media_type="application/json",
                source_key=request.source_key,
                source_url=f"{SUMBLE_API_BASE}/organizations",
            )
            operation = DiscoveryGapOperation(
                operation_id=new_discovery_gap_operation_id(),
                request=request,
                request_fingerprint=request.request_fingerprint,
                state=DiscoveryGapOperationState.PLANNED,
                spend_outcome=DiscoveryGapSpendOutcome.NOT_DISPATCHED,
                request_artifact_key=key,
                provider_units_reserved=Decimal(request.provider_credit_cap),
                cost_cents_reserved=request.money_budget_cap_cents,
            )
            stored, created = await reserve_discovery_gap_operation(
                conn, operation=operation, enforce_budget=self._enforce_budget
            )
            await self._bind(conn, stored, key, "sumble_discovery_gap_request")
            return stored, created

    async def _persist_snapshot(
        self, operation: DiscoveryGapOperation, snapshot: SumbleSnapshot
    ) -> DiscoveryGapOperation:
        body = _json_bytes(snapshot.payload)
        async with self._conn_factory() as conn:
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=body,
                media_type="application/json",
                source_key=operation.request.source_key,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, key, "sumble_discovery_gap_response")
            current = await get_discovery_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise DiscoveryGapNotFound("discovery-gap response operation")
            return await update_discovery_gap_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": DiscoveryGapOperationState.MATERIALIZING,
                        "spend_outcome": DiscoveryGapSpendOutcome.CHARGED,
                        "response_artifact_key": key,
                        "provider_request_id": snapshot.request_id,
                        "provider_units_charged": Decimal(snapshot.credits_used),
                        "credits_remaining": snapshot.credits_remaining,
                        "cost_cents_charged": snapshot.cost_cents,
                    }
                ),
            )

    async def _load_snapshot(self, operation: DiscoveryGapOperation) -> SumbleSnapshot:
        if operation.response_artifact_key is None or operation.provider_request_id is None:
            raise DiscoveryGapReplayConflict("materializing discovery gap lacks a durable response")
        body = await self._storage.get(operation.response_artifact_key)
        if not operation.response_artifact_key.endswith(content_address(body)):
            raise DiscoveryGapReplayConflict("discovery-gap response artifact hash mismatch")
        payload = json.loads(body)
        parsed = SumbleOrganizationsResponse.model_validate(payload)
        if (
            parsed.id != operation.provider_request_id
            or Decimal(parsed.credits_used) != operation.provider_units_charged
        ):
            raise DiscoveryGapReplayConflict(
                "discovery-gap response differs from its durable ledger"
            )
        return SumbleSnapshot(
            source_key=ORGANIZATIONS_SOURCE_KEY,
            request_id=parsed.id,
            credits_used=parsed.credits_used,
            credits_remaining=parsed.credits_remaining,
            payload=payload,
            cost_cents=operation.cost_cents_charged,
            estimated_max_credits=int(operation.provider_units_reserved),
            artifact_key=operation.response_artifact_key,
        )

    async def _materialize_and_reconcile(
        self,
        operation: DiscoveryGapOperation,
        snapshot: SumbleSnapshot,
    ) -> tuple[int, int]:
        await self._materializer.seed()
        existing = {}
        async with self._conn_factory() as conn:
            existing = {
                str(item.logical_field_key): item
                for item in await list_discovery_gap_field_results(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            }
        resolved = 0
        missing = 0
        for plan in operation.request.fields:
            prior = existing[str(plan.logical_field_key)]
            if prior.state is not DiscoveryGapFieldState.PENDING:
                if prior.state is DiscoveryGapFieldState.CONFIRMED_MISSING:
                    missing += 1
                else:
                    resolved += 1
                continue
            outcome = await self._materializer.materialize(
                workspace_id=operation.request.workspace_id,
                project_id=operation.request.project_id,
                project_run_id=operation.request.project_run_id,
                account_id=operation.request.account_id,
                field_key=str(plan.field_key),
                source_key=plan.source_key,
                snapshot=snapshot,
            )
            gap_state = {
                SumbleFieldDisposition.CONFIRMED_MISSING: DiscoveryGapFieldState.CONFIRMED_MISSING,
                SumbleFieldDisposition.RESOLVED: DiscoveryGapFieldState.RESOLVED,
                SumbleFieldDisposition.CORROBORATED: DiscoveryGapFieldState.CORROBORATED,
                SumbleFieldDisposition.CONFLICT: DiscoveryGapFieldState.CONFLICT,
            }[outcome.disposition]
            resolution_state = {
                SumbleFieldDisposition.CONFIRMED_MISSING: (
                    DiscoveryFieldResolutionState.CONFIRMED_MISSING
                ),
                SumbleFieldDisposition.RESOLVED: DiscoveryFieldResolutionState.RESOLVED,
                SumbleFieldDisposition.CORROBORATED: DiscoveryFieldResolutionState.RESOLVED,
                SumbleFieldDisposition.CONFLICT: DiscoveryFieldResolutionState.CONFLICT,
            }[outcome.disposition]
            async with self._conn_factory() as conn:
                resolution = await get_discovery_field_resolution(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    batch_id=operation.request.discovery_batch_id,
                    account_entity_id=operation.request.account_id,
                    logical_field_key=str(plan.logical_field_key),
                )
                if resolution is None:
                    raise DiscoveryGapNotFound("pending discovery resolution disappeared")
                provider_claims = tuple(
                    value
                    for value in (outcome.provider_claim_id, outcome.current_claim_id)
                    if value is not None
                )
                claim_ids = tuple(
                    sorted(
                        {
                            *resolution.claim_ids,
                            *provider_claims,
                            *outcome.conflicting_claim_ids,
                        },
                        key=str,
                    )
                )
                await put_discovery_gap_field_result(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    result=DiscoveryGapFieldResult(
                        operation_id=operation.operation_id,
                        account_id=operation.request.account_id,
                        logical_field_key=plan.logical_field_key,
                        field_key=plan.field_key,
                        source_key=plan.source_key,
                        state=gap_state,
                        provider_claim_id=outcome.provider_claim_id,
                        current_claim_id=outcome.current_claim_id,
                        conflicting_claim_ids=outcome.conflicting_claim_ids,
                        reason_code=outcome.reason_code,
                    ),
                )
                await put_discovery_field_resolution(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    resolution=resolution.model_copy(
                        update={
                            "state": resolution_state,
                            "claim_ids": claim_ids,
                            "winning_claim_id": (
                                outcome.current_claim_id
                                if resolution_state is DiscoveryFieldResolutionState.RESOLVED
                                else None
                            ),
                            "reason_code": (
                                None
                                if resolution_state is DiscoveryFieldResolutionState.RESOLVED
                                else outcome.reason_code
                            ),
                            "updated_at": datetime.now(UTC),
                        }
                    ),
                )
            if outcome.disposition is SumbleFieldDisposition.CONFIRMED_MISSING:
                missing += 1
            else:
                resolved += 1
        return resolved, missing

    async def _receipt(self, operation: DiscoveryGapOperation) -> str:
        async with self._conn_factory() as conn:
            fields = await list_discovery_gap_field_results(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            payload = {
                "contract": "sumble-discovery-required-field-receipt-v1",
                "operation_id": str(operation.operation_id),
                "request_fingerprint": operation.request_fingerprint,
                "discovery_batch_id": str(operation.request.discovery_batch_id),
                "provider_contract_version": operation.request.provider_contract_version,
                "provider_request_id": operation.provider_request_id,
                "provider_units_reserved": str(operation.provider_units_reserved),
                "provider_units_charged": str(operation.provider_units_charged),
                "cost_cents_charged": str(operation.cost_cents_charged),
                "response_artifact_key": operation.response_artifact_key,
                "fields": [item.model_dump(mode="json") for item in fields],
            }
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(payload),
                media_type="application/json",
                source_key=operation.request.source_key,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, key, "sumble_discovery_gap_receipt")
            return key

    async def _mark_unknown(self, operation: DiscoveryGapOperation, reason: str) -> None:
        async with self._conn_factory() as conn:
            current = await get_discovery_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise DiscoveryGapNotFound("unknown-spend discovery-gap operation")
            if current.terminal_at is not None:
                return
            await update_discovery_gap_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": DiscoveryGapOperationState.SPEND_OUTCOME_UNKNOWN,
                        "spend_outcome": DiscoveryGapSpendOutcome.UNKNOWN,
                        "failure_code": reason,
                        "terminal_at": datetime.now(UTC),
                    }
                ),
            )

    async def _fail_materialization(
        self, operation: DiscoveryGapOperation, failure_code: str
    ) -> None:
        async with self._conn_factory() as conn:
            fields = await list_discovery_gap_field_results(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            for field in fields:
                if field.state is DiscoveryGapFieldState.PENDING:
                    await put_discovery_gap_field_result(
                        conn,
                        workspace_id=operation.request.workspace_id,
                        result=field.model_copy(
                            update={
                                "state": DiscoveryGapFieldState.FAILED_TERMINAL,
                                "reason_code": failure_code,
                            }
                        ),
                    )
                    resolution = await get_discovery_field_resolution(
                        conn,
                        workspace_id=operation.request.workspace_id,
                        batch_id=operation.request.discovery_batch_id,
                        account_entity_id=operation.request.account_id,
                        logical_field_key=str(field.logical_field_key),
                    )
                    if resolution is not None and (
                        resolution.state is DiscoveryFieldResolutionState.PENDING
                    ):
                        await put_discovery_field_resolution(
                            conn,
                            workspace_id=operation.request.workspace_id,
                            resolution=resolution.model_copy(
                                update={
                                    "state": DiscoveryFieldResolutionState.FAILED_TERMINAL,
                                    "reason_code": f"sumble_materialization_failed:{failure_code}",
                                    "updated_at": datetime.now(UTC),
                                }
                            ),
                        )
        receipt = await self._receipt(operation)
        async with self._conn_factory() as conn:
            current = await get_discovery_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None or current.terminal_at is not None:
                return
            await update_discovery_gap_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": DiscoveryGapOperationState.FAILED_TERMINAL,
                        "receipt_artifact_key": receipt,
                        "failure_code": failure_code,
                        "terminal_at": datetime.now(UTC),
                    }
                ),
            )

    async def _bind(
        self,
        conn: object,
        operation: DiscoveryGapOperation,
        artifact_key: str,
        reference_kind: str,
    ) -> None:
        await bind_discovery_artifact_subject(
            conn,  # type: ignore[arg-type]
            workspace_id=operation.request.workspace_id,
            artifact_key_value=artifact_key,
            subject_kind="account",
            subject_entity_id=operation.request.account_id,
            reference_kind=reference_kind,
            reference_id=f"{operation.operation_id}:{reference_kind}",
        )


def build_production_sumble_discovery_gap_resolver(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
) -> SumbleDiscoveryGapResolver:
    if settings.sumble_discovery_gap_enrichment_enabled and secrets.sumble_api_key is None:
        raise RuntimeError(
            "Sumble required-field waterfall is enabled but CLUE_SUMBLE_API_KEY is not configured"
        )
    return SumbleDiscoveryGapResolver(
        enabled=settings.sumble_discovery_gap_enrichment_enabled,
        api_key=secrets.sumble_api_key,
        storage=storage,
        cents_per_credit=settings.sumble_cents_per_credit,
        conn_factory=conn_factory,
        enforce_budget=settings.budget_controls_enabled,
    )


__all__ = [
    "DEFAULT_SUMBLE_DISCOVERY_GAP_POLICY",
    "SUMBLE_DISCOVERY_GAP_CONTRACT_VERSION",
    "SUMBLE_DISCOVERY_GAP_POLICY_VERSION",
    "SUMBLE_DISCOVERY_GAP_PRICING_VERSION",
    "SumbleDiscoveryGapError",
    "SumbleDiscoveryGapOutcome",
    "SumbleDiscoveryGapPolicy",
    "SumbleDiscoveryGapProgress",
    "SumbleDiscoveryGapResolver",
    "build_production_sumble_discovery_gap_resolver",
]
