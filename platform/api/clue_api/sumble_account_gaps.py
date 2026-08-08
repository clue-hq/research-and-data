"""M6A S1: selected-account Sumble v9 gap enrichment.

One operation is bound to the exact discovery seal, human tier decision, account, field plan,
observation window, provider contract, and spend authorization. Organization identity is acquired
once; jobs and confirmed technology are dependent snapshots. Claims are append-only and enter the
ordinary merge/corroboration substrate independently of Exa claims.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader

# The species read is the FI-2 read layer's, imported rather than restated (it resolves through
# ``core.resolve_research_scope`` over the effective registry) so the gap economics and the lens
# that renders the resulting claims never disagree about what a field's species is.
from clue_api.frontend_read.account_detail import field_species
from clue_api.sumble_claim_materialization import (
    SumbleClaimMaterializer,
    SumbleFieldDisposition,
)
from clue_config import Secrets, Settings
from clue_core import (
    AccountGapFieldPlan,
    AccountGapFieldResult,
    AccountGapFieldState,
    AccountGapOperation,
    AccountGapOperationState,
    AccountGapReason,
    AccountGapRequest,
    AccountGapSnapshot,
    AccountGapSnapshotState,
    AccountGapSpendOutcome,
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    FreshnessState,
    ProjectPhase,
    ProjectRunId,
    ResearchScope,
    new_account_gap_operation_id,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    claims_for,
    current_value,
    get_effective_field,
)
from clue_research.discovery_scoring.tiering import TIER_FIELD
from clue_research.durable import (
    AccountGapNotFound,
    AccountGapReplayConflict,
    DiscoverySealConflict,
    ProjectRunStatus,
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    claim_account_gap_operation,
    claim_account_gap_snapshot,
    find_account_gap_operation,
    find_account_gap_operation_for_fields,
    get_account_gap_operation,
    get_account_gap_snapshot,
    get_project_run,
    list_account_gap_field_results,
    list_account_gap_snapshots,
    put_account_gap_field_result,
    quarantine_dispatching_account_gap_snapshots,
    reserve_account_gap_operation,
    reserve_account_gap_snapshot,
    terminal_now,
    update_account_gap_operation,
    update_account_gap_snapshot,
)
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.identity import get_account, surviving_id
from clue_research.resolvers.http import ProviderResponseError
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_API_BASE,
    SUMBLE_API_VERSION,
    TECH_STACK_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
    SumbleJobsResponse,
    SumbleOrganizationsResponse,
    SumbleSnapshot,
    SumbleSpendOutcomeUnknown,
    SumbleTechStackResponse,
    engineering_jobs_request,
    matched_organization_id,
    organization_request,
)
from clue_storage import StorageBackend, content_address

SUMBLE_V9_CONTRACT_VERSION: Final = (
    "sumble-v9-openapi-c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c"
)
SUMBLE_ACCOUNT_GAP_FIELD_POLICY_VERSION: Final = "sumble-account-gaps-v1"
SUMBLE_ACCOUNT_GAP_PRICING_VERSION: Final = "sumble-v9-credits-2026-08-03"

_EMPLOYEE = "core.employee_count"
_DOMAIN = "core.primary_domain"
_INDUSTRY = "core.industry"
_HQ = "core.hq_location"
_HIRING = "account.hiring_velocity_eng"
_TECH = "core.primary_tech_stack"

_SOURCE_BY_FIELD: Final[dict[str, str]] = {
    _EMPLOYEE: ORGANIZATIONS_SOURCE_KEY,
    _DOMAIN: ORGANIZATIONS_SOURCE_KEY,
    _INDUSTRY: ORGANIZATIONS_SOURCE_KEY,
    _HQ: ORGANIZATIONS_SOURCE_KEY,
    _HIRING: JOBS_SOURCE_KEY,
    _TECH: TECH_STACK_SOURCE_KEY,
}
_ORG_FIELDS: Final[frozenset[str]] = frozenset({_EMPLOYEE, _DOMAIN, _INDUSTRY, _HQ})


class SumbleAccountGapError(RuntimeError):
    pass


class SumbleAccountGapEligibilityError(SumbleAccountGapError):
    pass


class SumbleAccountGapOutcome(StrEnum):
    COMPLETED = "completed"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class SumbleAccountGapPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = SUMBLE_ACCOUNT_GAP_FIELD_POLICY_VERSION
    eligible_tiers: frozenset[str] = frozenset({"high"})
    low_confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    maximum_fields: int = Field(default=6, ge=1)
    jobs_limit: int = Field(default=1, ge=1, le=200)


DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY = SumbleAccountGapPolicy()


class SumbleAccountGapPreflight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    request: AccountGapRequest
    organization_body: dict[str, JsonValue]
    bounded_provider_units: Decimal
    maximum_cost_cents: Decimal


class SumbleAccountGapResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: SumbleAccountGapOutcome
    operation: AccountGapOperation
    claim_ids: tuple[str, ...] = ()
    provider_calls: int = 0


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _wire_fingerprint(
    *, parent_fingerprint: str, source_key: str, method: str, path: str, body: object
) -> str:
    return hashlib.sha256(
        _json_bytes(
            {
                "parent_fingerprint": parent_fingerprint,
                "source_key": source_key,
                "method": method,
                "path": path,
                "body": body,
                "provider_api_version": SUMBLE_API_VERSION,
                "provider_contract_version": SUMBLE_V9_CONTRACT_VERSION,
            }
        )
    ).hexdigest()


async def _exact_selected_tier_claim(
    *,
    conn: Any,
    workspace_id: str,
    account_id: EntityId,
    project_run_id: ProjectRunId,
    batch_id: object,
    seal_sha256: str,
    icp_key: str,
    icp_version: int,
    policy: SumbleAccountGapPolicy,
) -> Claim:
    matching = []
    for claim in await claims_for(
        conn,
        account_id,
        TIER_FIELD,
        scope=WorkspaceScope.for_workspace(workspace_id),
    ):
        value = claim.value_json
        if not isinstance(value, dict):
            continue
        if (
            claim.extraction_method.value == "human"
            and claim.source_tier == 1
            and value.get("decision_basis") == "discovery_criteria"
            and value.get("project_run_id") == str(project_run_id)
            and value.get("discovery_batch_id") == str(batch_id)
            and value.get("discovery_seal_sha256") == seal_sha256
            and value.get("icp_key") == icp_key
            and value.get("icp_version") == icp_version
            and value.get("disposition") == "selected"
            and value.get("tier") in policy.eligible_tiers
        ):
            matching.append(claim)
    if len(matching) != 1:
        raise SumbleAccountGapEligibilityError(
            "account gap enrichment requires one exact live human-selected tier decision"
        )
    return matching[0]


async def compile_sumble_account_gap_preflight(
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    field_expected_value_credits: Mapping[str, Decimal],
    provider_credit_cap: int,
    allow_unbounded_tech: bool,
    observation_window: str,
    storage: StorageBackend,
    cents_per_credit: Decimal = Decimal(0),
    conn_factory: ConnFactory = transaction,
    policy: SumbleAccountGapPolicy = DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY,
    entity_research_job_id: UUID | None = None,
) -> SumbleAccountGapPreflight:
    """Compile only documented native fields with an evidence-backed gap and explicit value."""

    if cents_per_credit < 0:
        raise SumbleAccountGapEligibilityError("Sumble cents-per-credit cannot be negative")
    field_keys = tuple(sorted(field_expected_value_credits))
    if not field_keys or len(field_keys) > policy.maximum_fields:
        raise SumbleAccountGapEligibilityError("invalid Sumble account-gap field count")
    unknown = sorted(set(field_keys) - set(_SOURCE_BY_FIELD))
    if unknown:
        raise SumbleAccountGapEligibilityError(
            f"field(s) are not approved for Sumble S1: {', '.join(unknown)}"
        )
    values = {key: Decimal(field_expected_value_credits[key]) for key in field_keys}
    if any(value <= 0 for value in values.values()):
        raise SumbleAccountGapEligibilityError(
            "every Sumble-selected field needs positive expected value credits"
        )
    if (_TECH in field_keys) != allow_unbounded_tech:
        raise SumbleAccountGapEligibilityError(
            "confirmed-tech requires, and alone permits, explicit unbounded-call approval"
        )

    reader = DbSealedDiscoveryAccountManifestReader(storage=storage, conn_factory=conn_factory)
    async with conn_factory() as conn:
        run = await get_project_run(conn, project_run_id)
        if run is None or run.workspace_id != workspace_id:
            raise SumbleAccountGapEligibilityError("Sumble account-gap project run does not exist")
        if run.status is not ProjectRunStatus.ACTIVE:
            raise SumbleAccountGapEligibilityError(
                "Sumble account-gap enrichment requires an active project run"
            )
        if entity_research_job_id is None and run.phase is not ProjectPhase.DEEP:
            raise SumbleAccountGapEligibilityError(
                "historical Sumble account-gap enrichment requires an active deep-phase run"
            )
    if entity_research_job_id is not None:
        # M8D account research is an independently confirmed action, not a projection of the
        # outer project phase.  Prove the exact running R6 job before compiling any provider
        # request.  The durable reservation repeats this check in the transaction that inserts
        # the operation, so a cancellation between preflight and reservation still fails closed.
        try:
            async with conn_factory() as conn:
                await require_provider_spend_capacity(
                    conn,
                    project_run_id=project_run_id,
                    proposed_cents=Decimal(0),
                    allowed_phases=frozenset({ProjectPhase.DEEP}),
                    entity_research_job_id=entity_research_job_id,
                )
        except ProviderSpendGuardError as exc:
            raise SumbleAccountGapEligibilityError(
                "Sumble account-gap enrichment lacks exact live entity-research job authority"
            ) from exc
    try:
        sealed = await reader.read(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
        )
    except DiscoverySealConflict as exc:
        raise SumbleAccountGapEligibilityError(
            "Sumble account-gap enrichment requires an intact discovery seal"
        ) from exc
    if sealed is None or account_id not in set(sealed.account_ids):
        raise SumbleAccountGapEligibilityError("account is absent from the exact discovery seal")

    field_plans: list[AccountGapFieldPlan] = []
    async with conn_factory() as conn:
        if await surviving_id(conn, account_id, EntityType.ACCOUNT) != account_id:
            raise SumbleAccountGapEligibilityError("account is not the canonical survivor")
        account = await get_account(conn, account_id)
        if account is None or account.workspace_id != workspace_id or not account.primary_domain:
            raise SumbleAccountGapEligibilityError(
                "account lacks a workspace-local canonical primary domain"
            )
        tier_claim = await _exact_selected_tier_claim(
            conn=conn,
            workspace_id=workspace_id,
            account_id=account_id,
            project_run_id=project_run_id,
            batch_id=sealed.discovery_batch_id,
            seal_sha256=sealed.seal_sha256,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            policy=policy,
        )
        # FI-2 §6.3 species check.  The fresh-skip below is only meaningful for a *project-neutral*
        # field: a project-relative value is one project's answer and another project's fresh claim
        # is never a substitute for it.  Every field in ``_SOURCE_BY_FIELD`` is a structured world
        # fact and resolves neutral under the ratified §5.2 rule, so this is a verified invariant
        # rather than an assumption — and it is *enforced*, not assumed, because a workspace-level
        # registry override could declare one relative, and this preflight's economics would then
        # silently mean the wrong thing.
        species = await field_species(conn, workspace_id=workspace_id, field_keys=list(field_keys))
        relative = sorted(
            key
            for key in field_keys
            if species.get(key, ResearchScope.PROJECT_NEUTRAL) is not ResearchScope.PROJECT_NEUTRAL
        )
        if relative:
            raise SumbleAccountGapEligibilityError(
                "Sumble account-gap enrichment answers project-neutral world facts only; "
                f"declared project-relative: {', '.join(relative)}"
            )
        for field_key in field_keys:
            source_key = _SOURCE_BY_FIELD[field_key]
            definition = await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(workspace_id),
                field_key=field_key,
            )
            if definition is None or source_key not in definition.field_def.tier_plan:
                raise SumbleAccountGapEligibilityError(
                    f"field plan does not select {source_key} for {field_key}"
                )
            raw_claims = await claims_for(
                conn,
                account_id,
                field_key,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            merged = await current_value(
                conn,
                account_id,
                field_key,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            if merged is None:
                reason = AccountGapReason.MISSING
                basis = tuple(claim.id for claim in raw_claims)
            elif merged.conflict:
                reason = AccountGapReason.CONFLICT
                basis = merged.conflicting_claim_ids
            elif merged.provenance.confidence < policy.low_confidence_threshold:
                reason = AccountGapReason.LOW_CONFIDENCE
                basis = (merged.provenance.claim_id,)
            elif merged.freshness_state is not FreshnessState.FRESH:
                # FI-2 §6.3(a): confidence is not currency.  A confidently-resolved fact that is
                # past its field's TTL is exactly what a re-buy is *for* — the old code read only
                # confidence and conflict, so it refused to refresh a fact everybody knew was
                # expired.  The stale winner is the durable basis for the refresh.
                reason = AccountGapReason.STALE
                basis = (merged.provenance.claim_id,)
            else:
                raise SumbleAccountGapEligibilityError(
                    f"{field_key} is already confidently resolved, fresh, and without an open "
                    "conflict"
                )
            field_plans.append(
                AccountGapFieldPlan(
                    field_key=field_key,
                    source_key=source_key,
                    reason=reason,
                    expected_value_credits=values[field_key],
                    basis_claim_ids=basis,
                )
            )

    org_fields = tuple(key for key in field_keys if key in _ORG_FIELDS)
    organization_body, organization_max = organization_request(
        account.primary_domain, field_keys=org_fields
    )
    bounded = organization_max + (policy.jobs_limit if _HIRING in field_keys else 0)
    if provider_credit_cap < bounded:
        raise SumbleAccountGapEligibilityError(
            f"provider cap {provider_credit_cap} is below bounded request maximum {bounded}"
        )
    expected = sum(values.values(), Decimal(0))
    if expected < provider_credit_cap:
        raise SumbleAccountGapEligibilityError(
            "expected field value does not justify the authorized provider-credit cap"
        )
    request = AccountGapRequest(
        workspace_id=workspace_id,
        project_id=run.project_id,
        project_run_id=project_run_id,
        entity_research_job_id=entity_research_job_id,
        icp_key=run.icp_key,
        icp_version=run.icp_version,
        discovery_batch_id=sealed.discovery_batch_id,
        discovery_seal_sha256=sealed.seal_sha256,
        account_id=account_id,
        primary_domain=account.primary_domain,
        tier_claim_id=tier_claim.id,
        provider_api_version=SUMBLE_API_VERSION,
        provider_contract_version=SUMBLE_V9_CONTRACT_VERSION,
        pricing_policy_version=SUMBLE_ACCOUNT_GAP_PRICING_VERSION,
        field_policy_version=policy.version,
        observation_window=observation_window,
        fields=tuple(field_plans),
        provider_credit_cap=provider_credit_cap,
        expected_value_credits=expected,
        money_budget_cap_cents=Decimal(provider_credit_cap) * cents_per_credit,
        allow_unbounded_tech=allow_unbounded_tech,
    )
    return SumbleAccountGapPreflight(
        request=request,
        organization_body=organization_body,
        bounded_provider_units=Decimal(bounded),
        maximum_cost_cents=request.money_budget_cap_cents,
    )


class SumbleAccountGapCoordinator:
    """Crash-safe synchronous coordinator over independently durable Sumble snapshots."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        storage: StorageBackend,
        cents_per_credit: Decimal = Decimal(0),
        conn_factory: ConnFactory = transaction,
        policy: SumbleAccountGapPolicy = DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY,
        in_flight_grace_seconds: int = 60,
        client_factory: Callable[[int, Decimal], SumbleClient] | None = None,
    ) -> None:
        self._api_key = api_key
        self._storage = storage
        self._cents_per_credit = cents_per_credit
        self._conn_factory = conn_factory
        self._policy = policy
        self._in_flight_grace = timedelta(seconds=in_flight_grace_seconds)
        self._client_factory = client_factory or (
            lambda maximum, cents: SumbleClient(
                api_key=self._api_key,
                budget=SumbleCreditBudget(maximum=maximum),
                cents_per_credit=cents,
            )
        )
        self._materializer = SumbleClaimMaterializer(conn_factory=conn_factory)

    async def start(
        self,
        preflight: SumbleAccountGapPreflight,
        *,
        before_dispatch: Callable[[AccountGapOperation], Awaitable[None]] | None = None,
    ) -> SumbleAccountGapResult:
        operation, _created = await self._reserve(preflight)
        terminal = self._terminal_result(operation, replay=True)
        if terminal is not None:
            return terminal
        if operation.state is AccountGapOperationState.ACQUIRING:
            if (
                operation.updated_at
                and datetime.now(UTC) - operation.updated_at < self._in_flight_grace
            ):
                return SumbleAccountGapResult(
                    outcome=SumbleAccountGapOutcome.JOINED_IN_FLIGHT,
                    operation=operation,
                )
            async with self._conn_factory() as conn:
                quarantined = await quarantine_dispatching_account_gap_snapshots(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            if quarantined:
                return await self._mark_unknown(operation, "crash_after_possible_sumble_dispatch")
        elif operation.state in {
            AccountGapOperationState.PLANNED,
            AccountGapOperationState.FAILED_RETRYABLE,
        }:
            # M8D R5 binds the exact agent/tool cause after durable reservation and before any
            # snapshot dispatch can be claimed. Callback failure leaves the operation planned.
            if before_dispatch is not None:
                await before_dispatch(operation)
            async with self._conn_factory() as conn:
                claimed = await claim_account_gap_operation(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            if claimed is None:
                fresh = await self._get(operation)
                return SumbleAccountGapResult(
                    outcome=SumbleAccountGapOutcome.JOINED_IN_FLIGHT,
                    operation=fresh,
                )
            operation = claimed

        client = self._client_factory(
            operation.request.provider_credit_cap,
            self._cents_per_credit,
        )
        provider_calls = 0
        org_fields = tuple(
            str(item.field_key)
            for item in operation.request.fields
            if item.source_key == ORGANIZATIONS_SOURCE_KEY
        )
        try:
            org, called = await self._drive_snapshot(
                operation,
                source_key=ORGANIZATIONS_SOURCE_KEY,
                call=lambda: client.resolve_organization(
                    operation.request.primary_domain, field_keys=org_fields
                ),
            )
            provider_calls += called
            organization_id = matched_organization_id(org.payload)
            selected_sources = {item.source_key for item in operation.request.fields}
            snapshots: dict[str, SumbleSnapshot] = {ORGANIZATIONS_SOURCE_KEY: org}
            if organization_id is None:
                for source_key in selected_sources - {ORGANIZATIONS_SOURCE_KEY}:
                    await self._mark_not_applicable(operation, source_key)
            else:
                if JOBS_SOURCE_KEY in selected_sources:
                    body, maximum = engineering_jobs_request(
                        organization_id, limit=self._policy.jobs_limit
                    )
                    await self._ensure_dependent_snapshot(
                        operation,
                        source_key=JOBS_SOURCE_KEY,
                        method="POST",
                        path="/jobs",
                        body=body,
                        reserved=Decimal(maximum),
                        unbounded=False,
                    )
                    jobs, called = await self._drive_snapshot(
                        operation,
                        source_key=JOBS_SOURCE_KEY,
                        call=lambda: client.engineering_jobs(
                            organization_id, limit=self._policy.jobs_limit
                        ),
                    )
                    provider_calls += called
                    snapshots[JOBS_SOURCE_KEY] = jobs
                if TECH_STACK_SOURCE_KEY in selected_sources:
                    await self._ensure_dependent_snapshot(
                        operation,
                        source_key=TECH_STACK_SOURCE_KEY,
                        method="GET",
                        path=f"/organizations/{organization_id}/techs",
                        body=None,
                        reserved=Decimal(0),
                        unbounded=True,
                    )
                    tech, called = await self._drive_snapshot(
                        operation,
                        source_key=TECH_STACK_SOURCE_KEY,
                        call=lambda: client.tech_stack(organization_id, allow_unbounded=True),
                    )
                    provider_calls += called
                    snapshots[TECH_STACK_SOURCE_KEY] = tech
        except ProviderResponseError as exc:
            if exc.is_deterministic_rejection:
                return await self._mark_provider_rejected(
                    operation, error=exc, provider_calls=provider_calls + 1
                )
            return await self._mark_unknown(
                operation,
                "sumble_paid_dispatch_unreconciled",
                provider_calls=provider_calls + 1,
            )
        except Exception:
            return await self._mark_unknown(
                operation,
                "sumble_paid_dispatch_unreconciled",
                provider_calls=provider_calls + 1,
            )

        durable_snapshots = await self._load_all_snapshots(operation)
        charged = sum(
            (Decimal(item.credits_used) for item in durable_snapshots.values()), Decimal(0)
        )
        cost = sum((item.cost_cents for item in durable_snapshots.values()), Decimal(0))
        if charged > operation.request.provider_credit_cap:
            await self._fail_fields(operation, "sumble_unbounded_charge_exceeded_authorized_cap")
            receipt_key = await self._receipt(operation, durable_snapshots, claim_ids=())
            failed = operation.model_copy(
                update={
                    "state": AccountGapOperationState.FAILED_TERMINAL,
                    "spend_outcome": AccountGapSpendOutcome.CHARGED,
                    "receipt_manifest_key": receipt_key,
                    "provider_units_charged": charged,
                    "cost_cents_charged": cost,
                    "failure_code": "sumble_unbounded_charge_exceeded_authorized_cap",
                    "terminal_at": terminal_now(),
                }
            )
            async with self._conn_factory() as conn:
                stored = await update_account_gap_operation(conn, operation=failed)
            return SumbleAccountGapResult(
                outcome=SumbleAccountGapOutcome.FAILED_TERMINAL,
                operation=stored,
                provider_calls=provider_calls,
            )

        async with self._conn_factory() as conn:
            current = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise AccountGapNotFound("Sumble account-gap materialization")
            operation = await update_account_gap_operation(
                conn,
                operation=current.model_copy(
                    update={"state": AccountGapOperationState.MATERIALIZING}
                ),
            )
        claim_ids = await self._materialize(operation, durable_snapshots)
        receipt_key = await self._receipt(operation, durable_snapshots, claim_ids=claim_ids)
        completed = operation.model_copy(
            update={
                "state": AccountGapOperationState.SUCCEEDED,
                "spend_outcome": AccountGapSpendOutcome.CHARGED,
                "receipt_manifest_key": receipt_key,
                "provider_units_charged": charged,
                "cost_cents_charged": cost,
                "terminal_at": terminal_now(),
            }
        )
        async with self._conn_factory() as conn:
            stored = await update_account_gap_operation(conn, operation=completed)
        return SumbleAccountGapResult(
            outcome=SumbleAccountGapOutcome.COMPLETED,
            operation=stored,
            claim_ids=claim_ids,
            provider_calls=provider_calls,
        )

    def _terminal_result(
        self, operation: AccountGapOperation, *, replay: bool
    ) -> SumbleAccountGapResult | None:
        if operation.state is AccountGapOperationState.SUCCEEDED:
            return SumbleAccountGapResult(
                outcome=(
                    SumbleAccountGapOutcome.REPLAYED
                    if replay
                    else SumbleAccountGapOutcome.COMPLETED
                ),
                operation=operation,
            )
        if operation.state is AccountGapOperationState.SPEND_OUTCOME_UNKNOWN:
            return SumbleAccountGapResult(
                outcome=SumbleAccountGapOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=operation,
            )
        if operation.state in {
            AccountGapOperationState.FAILED_TERMINAL,
            AccountGapOperationState.CANCELLED,
        }:
            return SumbleAccountGapResult(
                outcome=SumbleAccountGapOutcome.FAILED_TERMINAL,
                operation=operation,
            )
        return None

    async def _reserve(
        self, preflight: SumbleAccountGapPreflight
    ) -> tuple[AccountGapOperation, bool]:
        request = preflight.request
        async with self._conn_factory() as conn:
            existing = await find_account_gap_operation(
                conn,
                workspace_id=request.workspace_id,
                account_id=request.account_id,
                request_fingerprint=request.request_fingerprint,
                observation_window=request.observation_window,
            )
            if existing is not None:
                return existing, False
            input_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=request.canonical_bytes(),
                media_type="application/json",
                source_key=ORGANIZATIONS_SOURCE_KEY,
                source_url=f"{SUMBLE_API_BASE}/organizations",
            )
            org_wire = {
                "method": "POST",
                "path": "/organizations",
                "body": preflight.organization_body,
            }
            request_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=_json_bytes(org_wire),
                media_type="application/json",
                source_key=ORGANIZATIONS_SOURCE_KEY,
                source_url=f"{SUMBLE_API_BASE}/organizations",
            )
            operation = AccountGapOperation(
                operation_id=new_account_gap_operation_id(),
                request=request,
                request_fingerprint=request.request_fingerprint,
                state=AccountGapOperationState.PLANNED,
                spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                input_artifact_key=input_key,
                provider_units_reserved=Decimal(request.provider_credit_cap),
                cost_cents_reserved=preflight.maximum_cost_cents,
                unbounded_call_approved=request.allow_unbounded_tech,
            )
            org_snapshot = AccountGapSnapshot(
                operation_id=operation.operation_id,
                workspace_id=request.workspace_id,
                account_id=request.account_id,
                source_key=ORGANIZATIONS_SOURCE_KEY,
                request_fingerprint=_wire_fingerprint(
                    parent_fingerprint=request.request_fingerprint,
                    source_key=ORGANIZATIONS_SOURCE_KEY,
                    method="POST",
                    path="/organizations",
                    body=preflight.organization_body,
                ),
                state=AccountGapSnapshotState.PLANNED,
                spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                request_artifact_key=request_key,
                provider_units_reserved=(
                    Decimal(
                        organization_request(
                            request.primary_domain,
                            field_keys=tuple(
                                str(item.field_key)
                                for item in request.fields
                                if item.source_key == ORGANIZATIONS_SOURCE_KEY
                            ),
                        )[1]
                    )
                ),
            )
            stored, created = await reserve_account_gap_operation(
                conn, operation=operation, snapshots=(org_snapshot,)
            )
            for key, kind in (
                (input_key, "sumble_gap_request"),
                (request_key, "sumble_org_request"),
            ):
                await self._bind(conn, stored, key, kind)
            return stored, created

    async def _get(self, operation: AccountGapOperation) -> AccountGapOperation:
        async with self._conn_factory() as conn:
            stored = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        if stored is None:
            raise AccountGapNotFound("Sumble account-gap operation")
        return stored

    async def _bind(
        self,
        conn: Any,
        operation: AccountGapOperation,
        artifact_key: str,
        kind: str,
    ) -> None:
        await bind_discovery_artifact_subject(
            conn,
            workspace_id=operation.request.workspace_id,
            artifact_key_value=artifact_key,
            subject_kind="account",
            subject_entity_id=operation.request.account_id,
            reference_kind=kind,
            reference_id=f"{operation.operation_id}:{kind}",
        )

    async def _ensure_dependent_snapshot(
        self,
        operation: AccountGapOperation,
        *,
        source_key: str,
        method: str,
        path: str,
        body: object,
        reserved: Decimal,
        unbounded: bool,
    ) -> AccountGapSnapshot:
        wire = {"method": method, "path": path, "body": body}
        async with self._conn_factory() as conn:
            existing = await get_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
            if existing is not None:
                return existing
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(wire),
                media_type="application/json",
                source_key=source_key,
                source_url=f"{SUMBLE_API_BASE}{path}",
            )
            snapshot = AccountGapSnapshot(
                operation_id=operation.operation_id,
                workspace_id=operation.request.workspace_id,
                account_id=operation.request.account_id,
                source_key=source_key,
                request_fingerprint=_wire_fingerprint(
                    parent_fingerprint=operation.request_fingerprint,
                    source_key=source_key,
                    method=method,
                    path=path,
                    body=body,
                ),
                state=AccountGapSnapshotState.PLANNED,
                spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                request_artifact_key=key,
                provider_units_reserved=reserved,
                unbounded_call_approved=unbounded,
            )
            stored, _ = await reserve_account_gap_snapshot(conn, snapshot=snapshot)
            await self._bind(conn, operation, key, f"{source_key}_request")
            return stored

    async def _drive_snapshot(
        self,
        operation: AccountGapOperation,
        *,
        source_key: str,
        call: Any,
    ) -> tuple[SumbleSnapshot, int]:
        async with self._conn_factory() as conn:
            row = await get_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
            if row is None:
                raise AccountGapNotFound(f"Sumble snapshot {source_key}")
            if row.state is AccountGapSnapshotState.SUCCEEDED:
                return await self._load_snapshot(row), 0
            claimed = await claim_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
        if claimed is None:
            raise AccountGapReplayConflict(f"Sumble snapshot {source_key} is already in flight")
        try:
            provider = await asyncio.to_thread(call)
        except SumbleSpendOutcomeUnknown:
            raise
        except Exception:
            raise
        body = _json_bytes(provider.payload)
        async with self._conn_factory() as conn:
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=body,
                media_type="application/json",
                source_key=source_key,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, key, f"{source_key}_response")
            stored = await update_account_gap_snapshot(
                conn,
                snapshot=claimed.model_copy(
                    update={
                        "state": AccountGapSnapshotState.SUCCEEDED,
                        "spend_outcome": AccountGapSpendOutcome.CHARGED,
                        "response_artifact_key": key,
                        "provider_request_id": provider.request_id,
                        "provider_units_charged": Decimal(provider.credits_used),
                        "credits_remaining": provider.credits_remaining,
                        "cost_cents_charged": provider.cost_cents,
                        "terminal_at": terminal_now(),
                    }
                ),
            )
        return provider.model_copy(update={"artifact_key": stored.response_artifact_key}), 1

    async def _load_snapshot(self, row: AccountGapSnapshot) -> SumbleSnapshot:
        if row.response_artifact_key is None or row.provider_request_id is None:
            raise AccountGapReplayConflict("successful Sumble snapshot lacks durable response")
        body = await self._storage.get(row.response_artifact_key)
        if not row.response_artifact_key.endswith(content_address(body)):
            raise AccountGapReplayConflict("Sumble snapshot artifact hash mismatch")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise AccountGapReplayConflict("Sumble snapshot artifact is not an object")
        model: type[BaseModel]
        if row.source_key == ORGANIZATIONS_SOURCE_KEY:
            model = SumbleOrganizationsResponse
        elif row.source_key == JOBS_SOURCE_KEY:
            model = SumbleJobsResponse
        elif row.source_key == TECH_STACK_SOURCE_KEY:
            model = SumbleTechStackResponse
        else:
            raise AccountGapReplayConflict("unknown Sumble snapshot source")
        parsed = model.model_validate(payload)
        if (
            parsed.id != row.provider_request_id
            or Decimal(parsed.credits_used) != row.provider_units_charged
        ):
            raise AccountGapReplayConflict("Sumble receipt differs from durable snapshot ledger")
        return SumbleSnapshot(
            source_key=row.source_key,  # type: ignore[arg-type]
            request_id=row.provider_request_id,
            credits_used=int(row.provider_units_charged),
            credits_remaining=row.credits_remaining or 0,
            payload=payload,
            cost_cents=row.cost_cents_charged,
            estimated_max_credits=(
                None if row.unbounded_call_approved else int(row.provider_units_reserved)
            ),
            unbounded_call_approved=row.unbounded_call_approved,
            artifact_key=row.response_artifact_key,
        )

    async def _load_all_snapshots(
        self, operation: AccountGapOperation
    ) -> dict[str, SumbleSnapshot]:
        async with self._conn_factory() as conn:
            rows = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        result: dict[str, SumbleSnapshot] = {}
        for row in rows:
            if row.state is AccountGapSnapshotState.SUCCEEDED:
                result[row.source_key] = await self._load_snapshot(row)
        return result

    async def _mark_not_applicable(self, operation: AccountGapOperation, source_key: str) -> None:
        path = f"dependency:{source_key}:no_matched_organization"
        await self._ensure_dependent_snapshot(
            operation,
            source_key=source_key,
            method="SKIP",
            path=path,
            body={"reason": "no_matched_sumble_organization"},
            reserved=Decimal(0),
            unbounded=False,
        )
        async with self._conn_factory() as conn:
            row = await get_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
            if row is not None and row.state is AccountGapSnapshotState.PLANNED:
                await update_account_gap_snapshot(
                    conn,
                    snapshot=row.model_copy(
                        update={
                            "state": AccountGapSnapshotState.NOT_APPLICABLE,
                            "spend_outcome": AccountGapSpendOutcome.NOT_CHARGED,
                            "failure_code": "no_matched_sumble_organization",
                            "terminal_at": terminal_now(),
                        }
                    ),
                )

    async def _materialize(
        self,
        operation: AccountGapOperation,
        snapshots: Mapping[str, SumbleSnapshot],
    ) -> tuple[str, ...]:
        claim_ids: list[str] = []
        await self._materializer.seed()
        async with self._conn_factory() as conn:
            existing_results = {
                str(item.field_key): item
                for item in await list_account_gap_field_results(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            }
            snapshot_rows = {
                item.source_key: item
                for item in await list_account_gap_snapshots(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            }
        for plan in operation.request.fields:
            prior_result = existing_results[str(plan.field_key)]
            if prior_result.state is not AccountGapFieldState.PENDING:
                if prior_result.sumble_claim_id is not None:
                    claim_ids.append(str(prior_result.sumble_claim_id))
                continue
            source_key = plan.source_key
            snapshot = snapshots.get(source_key)
            if snapshot is None:
                await self._put_field(
                    operation,
                    plan,
                    state=AccountGapFieldState.CONFIRMED_MISSING,
                    reason="no_matched_sumble_organization",
                )
                continue
            outcome = await self._materializer.materialize(
                workspace_id=operation.request.workspace_id,
                project_id=operation.request.project_id,
                project_run_id=operation.request.project_run_id,
                account_id=operation.request.account_id,
                field_key=str(plan.field_key),
                source_key=source_key,
                snapshot=snapshot,
                source_operation_ref=str(operation.operation_id),
                source_snapshot_ref=(
                    f"account-gap-snapshot:{operation.operation_id}:{source_key}:"
                    f"{snapshot_rows[source_key].request_fingerprint}"
                ),
                source_request_ref=snapshot.request_id,
            )
            if outcome.provider_claim_id is not None:
                claim_ids.append(str(outcome.provider_claim_id))
            await self._put_field(
                operation,
                plan,
                state={
                    SumbleFieldDisposition.CONFIRMED_MISSING: (
                        AccountGapFieldState.CONFIRMED_MISSING
                    ),
                    SumbleFieldDisposition.RESOLVED: AccountGapFieldState.RESOLVED,
                    SumbleFieldDisposition.CORROBORATED: AccountGapFieldState.CORROBORATED,
                    SumbleFieldDisposition.CONFLICT: AccountGapFieldState.CONFLICT,
                }[outcome.disposition],
                sumble_claim_id=outcome.provider_claim_id,
                current_claim_id=outcome.current_claim_id,
                conflicts=outcome.conflicting_claim_ids,
                reason=outcome.reason_code,
            )
        return tuple(sorted(set(claim_ids)))

    async def _put_field(
        self,
        operation: AccountGapOperation,
        plan: AccountGapFieldPlan,
        *,
        state: AccountGapFieldState,
        sumble_claim_id: ClaimId | None = None,
        current_claim_id: ClaimId | None = None,
        conflicts: Sequence[ClaimId] = (),
        reason: str,
    ) -> None:
        async with self._conn_factory() as conn:
            await put_account_gap_field_result(
                conn,
                workspace_id=operation.request.workspace_id,
                result=AccountGapFieldResult(
                    operation_id=operation.operation_id,
                    account_id=operation.request.account_id,
                    field_key=plan.field_key,
                    source_key=plan.source_key,
                    state=state,
                    sumble_claim_id=sumble_claim_id,
                    current_claim_id=current_claim_id,
                    conflicting_claim_ids=tuple(conflicts),
                    reason_code=reason,
                ),
            )

    async def _fail_fields(self, operation: AccountGapOperation, reason: str) -> None:
        async with self._conn_factory() as conn:
            fields = await list_account_gap_field_results(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        for result in fields:
            if result.state is AccountGapFieldState.PENDING:
                plan = next(
                    item for item in operation.request.fields if item.field_key == result.field_key
                )
                await self._put_field(
                    operation,
                    plan,
                    state=AccountGapFieldState.FAILED_TERMINAL,
                    reason=reason,
                )

    async def _receipt(
        self,
        operation: AccountGapOperation,
        snapshots: Mapping[str, SumbleSnapshot],
        *,
        claim_ids: Sequence[str],
    ) -> str:
        async with self._conn_factory() as conn:
            fields = await list_account_gap_field_results(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            payload = {
                "contract": "sumble-account-gap-receipt-v1",
                "operation_id": str(operation.operation_id),
                "request_fingerprint": operation.request_fingerprint,
                "discovery_seal_sha256": operation.request.discovery_seal_sha256,
                "provider_contract_version": operation.request.provider_contract_version,
                "provider_units_reserved": str(operation.provider_units_reserved),
                "provider_units_charged": str(
                    sum((Decimal(item.credits_used) for item in snapshots.values()), Decimal(0))
                ),
                "snapshots": {
                    key: {
                        "request_id": value.request_id,
                        "credits_used": value.credits_used,
                        "credits_remaining": value.credits_remaining,
                        "artifact_key": value.artifact_key,
                    }
                    for key, value in sorted(snapshots.items())
                },
                "fields": [item.model_dump(mode="json") for item in fields],
                "claim_ids": list(claim_ids),
            }
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(payload),
                media_type="application/json",
                source_key=ORGANIZATIONS_SOURCE_KEY,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, key, "sumble_gap_receipt")
            return key

    async def _mark_provider_rejected(
        self,
        operation: AccountGapOperation,
        *,
        error: ProviderResponseError,
        provider_calls: int = 0,
    ) -> SumbleAccountGapResult:
        """Persist a deterministic provider rejection with its exact diagnostic evidence.

        Sumble validates a request and prechecks the balance *before* charging, so a hard 4xx is a
        zero-credit terminal refusal — categorically different from a transport loss after dispatch,
        whose spend really is unknown. Collapsing both into ``spend_outcome_unknown`` cost a manual
        live replay just to learn the status code, so the failing snapshot now retains the HTTP
        status and the provider's own bounded error body as an ordinary response artifact.

        Only the in-flight (``DISPATCHING``) snapshot is refused. Any snapshot this operation had
        already settled keeps its real charge, and the operation's spend outcome is recomputed from
        the durable snapshot ledger rather than being asserted uncharged.
        """

        async with self._conn_factory() as conn:
            rows = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        dispatching = tuple(row for row in rows if row.state is AccountGapSnapshotState.DISPATCHING)
        source_key = dispatching[0].source_key if dispatching else "sumble"
        failure_code = f"{source_key}_provider_rejected_http_{error.status_code}"
        async with self._conn_factory() as conn:
            rejection_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(
                    {
                        "provider_rejection": {
                            "source_key": source_key,
                            "http_status": error.status_code,
                            "body_excerpt": error.body_excerpt,
                        }
                    }
                ),
                media_type="application/json",
                source_key=source_key,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, rejection_key, f"{source_key}_provider_rejection")
            for row in dispatching:
                await update_account_gap_snapshot(
                    conn,
                    snapshot=row.model_copy(
                        update={
                            "state": AccountGapSnapshotState.FAILED_TERMINAL,
                            "spend_outcome": AccountGapSpendOutcome.NOT_CHARGED,
                            "response_artifact_key": rejection_key,
                            "failure_code": failure_code,
                            "terminal_at": terminal_now(),
                        }
                    ),
                )
        await self._fail_fields(operation, failure_code)
        async with self._conn_factory() as conn:
            settled = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            charged = sum((row.provider_units_charged for row in settled), Decimal(0))
            cost = sum((row.cost_cents_charged for row in settled), Decimal(0))
            current = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise AccountGapNotFound("Sumble account-gap rejected operation")
            stored = await update_account_gap_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": AccountGapOperationState.FAILED_TERMINAL,
                        "spend_outcome": (
                            AccountGapSpendOutcome.CHARGED
                            if charged
                            else AccountGapSpendOutcome.NOT_CHARGED
                        ),
                        "provider_units_charged": charged,
                        "cost_cents_charged": cost,
                        "failure_code": failure_code,
                        "terminal_at": terminal_now(),
                    }
                ),
            )
        return SumbleAccountGapResult(
            outcome=SumbleAccountGapOutcome.FAILED_TERMINAL,
            operation=stored,
            provider_calls=provider_calls,
        )

    async def _mark_unknown(
        self,
        operation: AccountGapOperation,
        failure_code: str,
        *,
        provider_calls: int = 0,
    ) -> SumbleAccountGapResult:
        async with self._conn_factory() as conn:
            rows = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            for row in rows:
                if row.state is AccountGapSnapshotState.DISPATCHING:
                    await update_account_gap_snapshot(
                        conn,
                        snapshot=row.model_copy(
                            update={
                                "state": AccountGapSnapshotState.SPEND_OUTCOME_UNKNOWN,
                                "spend_outcome": AccountGapSpendOutcome.UNKNOWN,
                                "failure_code": failure_code,
                                "terminal_at": terminal_now(),
                            }
                        ),
                    )
            known_units = sum((row.provider_units_charged for row in rows), Decimal(0))
            known_cost = sum((row.cost_cents_charged for row in rows), Decimal(0))
            current = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise AccountGapNotFound("Sumble account-gap unknown-spend operation")
            stored = await update_account_gap_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": AccountGapOperationState.SPEND_OUTCOME_UNKNOWN,
                        "spend_outcome": AccountGapSpendOutcome.UNKNOWN,
                        "provider_units_charged": known_units,
                        "cost_cents_charged": known_cost,
                        "failure_code": failure_code,
                        "terminal_at": terminal_now(),
                    }
                ),
            )
        return SumbleAccountGapResult(
            outcome=SumbleAccountGapOutcome.SPEND_OUTCOME_UNKNOWN,
            operation=stored,
            provider_calls=provider_calls,
        )


class SumbleAccountGapStarter:
    def __init__(
        self,
        *,
        coordinator: SumbleAccountGapCoordinator,
        storage: StorageBackend,
        cents_per_credit: Decimal,
        conn_factory: ConnFactory = transaction,
        policy: SumbleAccountGapPolicy = DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY,
    ) -> None:
        self._coordinator = coordinator
        self._storage = storage
        self._cents_per_credit = cents_per_credit
        self._conn_factory = conn_factory
        self._policy = policy

    async def start(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_id: EntityId,
        field_expected_value_credits: Mapping[str, Decimal],
        provider_credit_cap: int,
        allow_unbounded_tech: bool,
        before_dispatch: Callable[[AccountGapOperation], Awaitable[None]] | None = None,
        entity_research_job_id: UUID | None = None,
    ) -> SumbleAccountGapResult:
        field_keys = tuple(sorted(field_expected_value_credits))
        window = f"project-run:{project_run_id}:sumble-gaps:{self._policy.version}"
        async with self._conn_factory() as conn:
            existing = await find_account_gap_operation_for_fields(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                observation_window=window,
                field_keys=field_keys,
            )
        if existing is not None:
            expected = sum(
                (Decimal(value) for value in field_expected_value_credits.values()), Decimal(0)
            )
            if (
                existing.request.project_run_id != project_run_id
                or existing.request.provider_credit_cap != provider_credit_cap
                or existing.request.expected_value_credits != expected
                or {
                    str(item.field_key): item.expected_value_credits
                    for item in existing.request.fields
                }
                != {key: Decimal(value) for key, value in field_expected_value_credits.items()}
                or existing.request.allow_unbounded_tech != allow_unbounded_tech
            ):
                raise AccountGapReplayConflict(
                    "same-window Sumble field set was replayed with different authorization"
                )
            terminal = self._coordinator._terminal_result(existing, replay=True)
            if terminal is not None:
                return terminal
            organization_body, organization_max = organization_request(
                existing.request.primary_domain,
                field_keys=tuple(
                    str(item.field_key)
                    for item in existing.request.fields
                    if item.source_key == ORGANIZATIONS_SOURCE_KEY
                ),
            )
            return await self._coordinator.start(
                SumbleAccountGapPreflight(
                    request=existing.request,
                    organization_body=organization_body,
                    bounded_provider_units=Decimal(organization_max),
                    maximum_cost_cents=existing.cost_cents_reserved,
                ),
                before_dispatch=before_dispatch,
            )
        preflight = await compile_sumble_account_gap_preflight(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_id=account_id,
            field_expected_value_credits=field_expected_value_credits,
            provider_credit_cap=provider_credit_cap,
            allow_unbounded_tech=allow_unbounded_tech,
            observation_window=window,
            storage=self._storage,
            cents_per_credit=self._cents_per_credit,
            conn_factory=self._conn_factory,
            policy=self._policy,
            entity_research_job_id=entity_research_job_id,
        )
        return await self._coordinator.start(preflight, before_dispatch=before_dispatch)


def build_production_sumble_account_gap_starter(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
) -> SumbleAccountGapStarter | None:
    if not settings.sumble_account_gap_enrichment_enabled:
        return None
    if secrets.sumble_api_key is None:
        raise RuntimeError(
            "Sumble account-gap enrichment is enabled but CLUE_SUMBLE_API_KEY is not configured"
        )
    coordinator = SumbleAccountGapCoordinator(
        api_key=secrets.sumble_api_key,
        storage=storage,
        cents_per_credit=settings.sumble_cents_per_credit,
        conn_factory=conn_factory,
    )
    return SumbleAccountGapStarter(
        coordinator=coordinator,
        storage=storage,
        cents_per_credit=settings.sumble_cents_per_credit,
        conn_factory=conn_factory,
    )


__all__ = [
    "DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY",
    "SUMBLE_ACCOUNT_GAP_FIELD_POLICY_VERSION",
    "SUMBLE_ACCOUNT_GAP_PRICING_VERSION",
    "SUMBLE_V9_CONTRACT_VERSION",
    "SumbleAccountGapCoordinator",
    "SumbleAccountGapEligibilityError",
    "SumbleAccountGapError",
    "SumbleAccountGapOutcome",
    "SumbleAccountGapPolicy",
    "SumbleAccountGapPreflight",
    "SumbleAccountGapResult",
    "SumbleAccountGapStarter",
    "build_production_sumble_account_gap_starter",
    "compile_sumble_account_gap_preflight",
]
