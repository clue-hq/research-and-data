"""Compose S2D eligibility, S2B acquisition, and S2C materialization for account-deep.

This is the only Sumble-specific layer in the DEEP path.  It implements the provider-neutral
``CommitteePreparer`` seam: eligibility and provider submit/poll complete outside the orchestrator's
claim transaction, while ready operations become snapshot-only ``SumbleCommitteeSource`` readers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from clue_api.committee_eligibility import (
    CommitteeEligibilityService,
    CommitteeEnumerationSource,
)
from clue_api.deep.committee_preparation import PreparedCommitteeSources
from clue_api.sumble_committee_acquisition import (
    CommitteeRateLimiter,
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    SumbleCommitteePreflight,
)
from clue_api.sumble_committee_launch import GatedSumbleCommitteeLauncher
from clue_api.sumble_committee_source import SumbleCommitteeSource
from clue_config import Secrets, Settings
from clue_core import (
    CommitteeAcquisitionOperation,
    CommitteeAcquisitionOperationId,
    CommitteeAcquisitionState,
    CommitteeEligibilityOutcome,
    CommitteeExecutionAuthorization,
    CommitteeSnapshotState,
    EntityId,
    ExternalResearchPreparation,
    ExternalResearchPreparationOutcome,
    PreSpendGate,
    ProjectRunId,
    ResearchCommitteePlan,
    RunId,
    SourceTier,
)
from clue_core.entity_research import SealedDiscoveryLaunchReceipt
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    get_account_run,
    get_committee_acquisition_operation,
    list_committee_acquisition_snapshots,
)
from clue_research.resolvers.sumble.committee_transport import SumbleV9CommitteeClient
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_research.resolvers.sumble.teams import TEAMS_SOURCE_KEY
from clue_storage import StorageBackend


class SumbleCommitteePreparationInputs(BaseModel):
    """The A2/composition-owned launch inputs for one exact account and project run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preflight: SumbleCommitteePreflight
    authorization: CommitteeExecutionAuthorization
    committee_plan: ResearchCommitteePlan
    discovery_receipt: SealedDiscoveryLaunchReceipt | None = None
    """The confirmed plan the request's ``committee_plan_ref`` addresses.

    Carried typed so the engine can validate an agent-authored buying-unit scope against the
    durable committee authority instead of re-deriving it from a provider-shaped request."""


class SumbleCommitteeInputResolver(Protocol):
    """Resolve a pinned directive/authorization and bounded Sumble plan from durable state."""

    async def resolve(
        self,
        *,
        account_entity_id: EntityId,
        account_run_id: RunId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        tier: str,
    ) -> SumbleCommitteePreparationInputs: ...


class SumbleCommitteePreparationError(RuntimeError):
    pass


#: The reason codes a world-fact committee refusal may carry. Kept in lockstep with the
#: ``entity_research_committee_unavailable_reason`` CHECK (migration ``612428f3731f``).
COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED = "committee_provider_organization_unmatched"
COMMITTEE_PROVIDER_IDENTITY_ABSENT = "committee_provider_identity_absent"


class SumbleCommitteeProviderIdentityUnavailable(SumbleCommitteePreparationError):
    """The provider's organization index cannot serve this exact account — a world fact.

    Distinct from every other preparation failure on this path, all of which are authority or
    integrity species (a scope that crosses accounts, an unconfirmed directive, a tampered
    authorization) and must keep suspending the job. This one is a fact about the provider's data:
    Sumble has no exact matched organization for the account, or no Organizations response for it
    exists anywhere in durable state. Nothing the model can say changes either, and no money or
    truth is at stake — so the M8D committee tool converts *this class only* into a recoverable
    governed rejection and records the committee axis as terminally attempted.

    Live: run ``dc86340f``, "Greater Chicago Specialty Physicians LLC", 2026-08-20 21:36:47 IST —
    the unmatched-organization case escaped raw as ``execution_failed`` and requeued the job.

    Being a subclass keeps every existing ``except SumbleCommitteePreparationError`` caller —
    notably the DEEP-path :class:`SumbleCommitteePreparer` — byte-identical in behaviour.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SumbleCommitteePreparer:
    """Adapt the complete no-reveal Sumble S2 lane to provider-neutral DEEP preparation."""

    def __init__(
        self,
        *,
        inputs: SumbleCommitteeInputResolver,
        launcher: GatedSumbleCommitteeLauncher,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        fallback_poll_after_seconds: int = 30,
    ) -> None:
        if fallback_poll_after_seconds < 1:
            raise ValueError("Sumble committee fallback poll interval must be positive")
        self._inputs = inputs
        self._launcher = launcher
        self._storage = storage
        self._conn_factory = conn_factory
        self._fallback_poll_after = timedelta(seconds=fallback_poll_after_seconds)

    async def prepare(
        self,
        *,
        account_entity_id: EntityId,
        account_run_id: RunId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        tier: str,
    ) -> PreparedCommitteeSources:
        inputs = await self._inputs.resolve(
            account_entity_id=account_entity_id,
            account_run_id=account_run_id,
            project_run_id=project_run_id,
            workspace_id=workspace_id,
            tier=tier,
        )
        request = inputs.preflight.request
        async with self._conn_factory() as conn:
            account_run = await get_account_run(conn, account_run_id)
        if account_run is None or account_run.research_directive is None:
            raise SumbleCommitteePreparationError(
                "Sumble committee preparation requires a directive-pinned account run"
            )
        if (
            request.research_directive != account_run.research_directive
            or inputs.authorization.research_directive != account_run.research_directive
        ):
            raise SumbleCommitteePreparationError(
                "Sumble committee request does not carry the account run's exact directive pin"
            )
        if (
            request.account_id != account_entity_id
            or request.project_run_id != project_run_id
            or request.workspace_id != workspace_id
        ):
            raise SumbleCommitteePreparationError(
                "Sumble committee preparation inputs do not match the account-deep run"
            )

        launched = await self._launcher.start(
            inputs.preflight,
            authorization=inputs.authorization,
        )
        decision = launched.eligibility
        audit_ref = f"committee-eligibility:{decision.decision_id}"
        if decision.outcome is CommitteeEligibilityOutcome.INELIGIBLE:
            reasons = tuple(
                reason
                for condition in decision.conditions
                if not condition.passed
                for reason in condition.reason_codes
            )
            return PreparedCommitteeSources(
                preparation=ExternalResearchPreparation(
                    outcome=ExternalResearchPreparationOutcome.INELIGIBLE,
                    audit_refs=(audit_ref,),
                    reason_code=reasons[0] if reasons else "committee_ineligible",
                ),
                sources=(),
            )
        if decision.outcome is CommitteeEligibilityOutcome.REUSABLE:
            operation_id = decision.reusable_operation_id
            if operation_id is None:  # defended by CommitteeEligibilityDecision
                raise SumbleCommitteePreparationError("reusable decision lacks an operation")
            return await self._ready(
                workspace_id=workspace_id,
                account_entity_id=account_entity_id,
                operation_id=operation_id,
                audit_ref=audit_ref,
            )

        acquisition = launched.acquisition
        if acquisition is None:  # defended by GatedSumbleCommitteeResult
            raise SumbleCommitteePreparationError("eligible decision did not start acquisition")
        operation = acquisition.operation
        if acquisition.outcome in {
            SumbleCommitteeOutcome.READY,
            SumbleCommitteeOutcome.REPLAYED,
        }:
            return await self._ready(
                workspace_id=workspace_id,
                account_entity_id=account_entity_id,
                operation_id=operation.operation_id,
                audit_ref=audit_ref,
            )
        if acquisition.outcome in {
            SumbleCommitteeOutcome.WAITING_EXTERNAL,
            SumbleCommitteeOutcome.JOINED_IN_FLIGHT,
            SumbleCommitteeOutcome.RATE_LIMITED,
        }:
            retry_after = operation.next_poll_at or datetime.now(UTC) + self._fallback_poll_after
            return PreparedCommitteeSources(
                preparation=ExternalResearchPreparation(
                    outcome=ExternalResearchPreparationOutcome.WAITING_EXTERNAL,
                    operation_ref=_operation_ref(operation.operation_id),
                    retry_after=retry_after,
                    audit_refs=(audit_ref,),
                    reason_code=acquisition.outcome.value,
                )
            )
        return PreparedCommitteeSources(
            preparation=ExternalResearchPreparation(
                outcome=ExternalResearchPreparationOutcome.FAILED,
                operation_ref=_operation_ref(operation.operation_id),
                audit_refs=(audit_ref,),
                reason_code=operation.failure_code or acquisition.outcome.value,
            ),
            sources=(),
        )

    async def _ready(
        self,
        *,
        workspace_id: str,
        account_entity_id: EntityId,
        operation_id: CommitteeAcquisitionOperationId,
        audit_ref: str,
    ) -> PreparedCommitteeSources:
        async with self._conn_factory() as conn:
            operation = await get_committee_acquisition_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )
            if operation is None:
                raise SumbleCommitteePreparationError("ready Sumble committee operation is missing")
            self._validate_ready_operation(operation, account_entity_id=account_entity_id)
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )
        if {item.source_key for item in snapshots} != {TEAMS_SOURCE_KEY, PEOPLE_SOURCE_KEY} or any(
            item.state is not CommitteeSnapshotState.SUCCEEDED or item.response_artifact_key is None
            for item in snapshots
        ):
            raise SumbleCommitteePreparationError(
                "ready Sumble committee operation lacks succeeded Teams and People snapshots"
            )
        snapshot_refs = tuple(
            item.response_artifact_key
            for item in snapshots
            if item.response_artifact_key is not None
        )
        assert operation.receipt_manifest_key is not None
        source = SumbleCommitteeSource(
            operation_ids={account_entity_id: operation_id},
            storage=self._storage,
            conn_factory=self._conn_factory,
        )
        return PreparedCommitteeSources(
            preparation=ExternalResearchPreparation(
                outcome=ExternalResearchPreparationOutcome.READY,
                operation_ref=_operation_ref(operation_id),
                snapshot_refs=snapshot_refs,
                cost_receipt_ref=operation.receipt_manifest_key,
                audit_refs=(audit_ref,),
            ),
            sources=(source,),
        )

    @staticmethod
    def _validate_ready_operation(
        operation: CommitteeAcquisitionOperation, *, account_entity_id: EntityId
    ) -> None:
        if operation.request.account_id != account_entity_id:
            raise SumbleCommitteePreparationError(
                "ready Sumble committee operation belongs to another account"
            )
        if operation.state is not CommitteeAcquisitionState.READY:
            raise SumbleCommitteePreparationError(
                f"Sumble committee operation is {operation.state.value}, not ready"
            )


def _operation_ref(operation_id: CommitteeAcquisitionOperationId) -> str:
    return f"committee-operation:{operation_id}"


def build_production_sumble_committee_preparer(
    settings: Settings,
    *,
    secrets: Secrets,
    inputs: SumbleCommitteeInputResolver,
    storage: StorageBackend,
    pre_spend_gate: PreSpendGate,
    conn_factory: ConnFactory = transaction,
    rate_limiter: CommitteeRateLimiter | None = None,
) -> SumbleCommitteePreparer | None:
    """Build the live S2 preparer only under its independent default-off authorization."""

    if not settings.sumble_committee_acquisition_enabled:
        return None
    if secrets.sumble_api_key is None:
        raise RuntimeError(
            "Sumble committee acquisition is enabled but CLUE_SUMBLE_API_KEY is not configured"
        )
    coordinator = SumbleCommitteeAcquisitionCoordinator(
        transport=SumbleV9CommitteeClient(api_key=secrets.sumble_api_key),
        storage=storage,
        cents_per_credit=settings.sumble_cents_per_credit,
        conn_factory=conn_factory,
        poll_after_seconds=settings.sumble_committee_poll_after_s,
        rate_limiter=rate_limiter,
        enforce_budget=settings.budget_controls_enabled,
    )
    eligibility = CommitteeEligibilityService(
        storage=storage,
        pre_spend_gate=pre_spend_gate,
        sources=(
            CommitteeEnumerationSource(source_key=TEAMS_SOURCE_KEY, source_tier=SourceTier(1)),
            CommitteeEnumerationSource(source_key=PEOPLE_SOURCE_KEY, source_tier=SourceTier(1)),
        ),
        conn_factory=conn_factory,
        enforce_budget=settings.budget_controls_enabled,
    )
    return SumbleCommitteePreparer(
        inputs=inputs,
        launcher=GatedSumbleCommitteeLauncher(
            eligibility=eligibility,
            starter=coordinator,
        ),
        storage=storage,
        conn_factory=conn_factory,
        fallback_poll_after_seconds=settings.sumble_committee_poll_after_s,
    )


__all__ = [
    "COMMITTEE_PROVIDER_IDENTITY_ABSENT",
    "COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED",
    "SumbleCommitteeInputResolver",
    "SumbleCommitteePreparationError",
    "SumbleCommitteePreparationInputs",
    "SumbleCommitteePreparer",
    "SumbleCommitteeProviderIdentityUnavailable",
    "build_production_sumble_committee_preparer",
]
