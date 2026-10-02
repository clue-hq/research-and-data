"""S2D seven-condition gate for one-account committee acquisition.

The service is provider-neutral: callers supply the bounded enumeration source keys and a typed
no-reveal authorization receipt. It reads immutable discovery/ICP lineage, invokes the shared
pre-spend gate, proves project budget capacity, detects exact fresh snapshot reuse, and appends one
auditable decision. It never calls a provider or creates a paid acquisition operation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader
from clue_core import (
    CommitteeAcquisitionRequest,
    CommitteeAcquisitionState,
    CommitteeEligibilityCondition,
    CommitteeEligibilityConditionResult,
    CommitteeEligibilityDecision,
    CommitteeEligibilityOutcome,
    CommitteeExecutionAuthorization,
    EntityType,
    EnumerationScope,
    PreSpendGate,
    PreSpendKind,
    PreSpendRequest,
    PreSpendVerdict,
    ProjectPhase,
    RunId,
    SourceTier,
    UseClass,
    new_committee_eligibility_decision_id,
)
from clue_core.entity_research import SealedDiscoveryLaunchReceipt
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.discovery_scoring.tiering import (
    ACCOUNT_RESEARCH_ELIGIBLE_TIERS,
    TIER_CLAIM_MAX_SOURCE_TIER,
    TIER_FIELD,
    DiscoverySelectionDisposition,
    DiscoverySelectionPolicy,
    load_discovery_criteria_selection,
)
from clue_research.durable import (
    DiscoverySealConflict,
    find_committee_acquisition_operation,
    get_checkpoint,
    get_project_run,
    record_committee_eligibility_decision,
)
from clue_research.durable.enums import PhaseCheckpointStatus, ProjectRunStatus
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.icp import get_icp_version
from clue_storage import StorageBackend

COMMITTEE_ELIGIBILITY_POLICY_VERSION = "committee-eligibility-s2d-v1"


class CommitteeEnumerationSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str = Field(min_length=1)
    source_tier: SourceTier


class CommitteeEligibilityPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = COMMITTEE_ELIGIBILITY_POLICY_VERSION
    committee_eligible_tiers: frozenset[str] = ACCOUNT_RESEARCH_ELIGIBLE_TIERS
    reusable_snapshot_ttl_seconds: int = Field(default=30 * 24 * 60 * 60, ge=0)
    required_use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC

    @model_validator(mode="after")
    def _usable_policy(self) -> CommitteeEligibilityPolicy:
        if not self.version.strip() or not self.committee_eligible_tiers:
            raise ValueError("committee eligibility policy requires a version and eligible tiers")
        if any(not value.strip() for value in self.committee_eligible_tiers):
            raise ValueError("committee eligible tiers must be non-empty")
        return self


DEFAULT_COMMITTEE_ELIGIBILITY_POLICY = CommitteeEligibilityPolicy()


def _condition(
    condition: CommitteeEligibilityCondition,
    passed: bool,
    *,
    reasons: Sequence[str] = (),
    evidence: Sequence[str] = (),
) -> CommitteeEligibilityConditionResult:
    return CommitteeEligibilityConditionResult(
        condition=condition,
        passed=passed,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence_refs=tuple(dict.fromkeys(evidence)),
    )


class CommitteeEligibilityService:
    """Evaluate and persist S2 eligibility without acquiring Teams or People."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        pre_spend_gate: PreSpendGate,
        sources: Sequence[CommitteeEnumerationSource],
        conn_factory: ConnFactory = transaction,
        policy: CommitteeEligibilityPolicy = DEFAULT_COMMITTEE_ELIGIBILITY_POLICY,
        enforce_budget: bool = True,
    ) -> None:
        if not sources or len(sources) != len({item.source_key for item in sources}):
            raise ValueError("committee eligibility requires unique bounded enumeration sources")
        self._storage = storage
        self._pre_spend_gate = pre_spend_gate
        self._sources = tuple(sources)
        self._conn_factory = conn_factory
        self._policy = policy
        # FI pilot budget-controls: threaded from ``Settings.budget_controls_enabled`` at
        # the composition root and passed to the durable reservation, which stops raising
        # on the project-run cap while writing every ledger row unchanged.
        self._enforce_budget = enforce_budget

    async def evaluate(
        self,
        request: CommitteeAcquisitionRequest,
        *,
        authorization: CommitteeExecutionAuthorization,
        proposed_cost_cents: Decimal,
        now: datetime | None = None,
        discovery_receipt: SealedDiscoveryLaunchReceipt | None = None,
    ) -> CommitteeEligibilityDecision:
        if proposed_cost_cents < 0:
            raise ValueError("committee eligibility proposed cost cannot be negative")
        evaluated_at = now or datetime.now(UTC)
        reader = DbSealedDiscoveryAccountManifestReader(
            storage=self._storage, conn_factory=self._conn_factory
        )
        sealed = None
        seal_reasons: list[str] = []
        try:
            sealed = await reader.read(
                workspace_id=request.workspace_id,
                project_run_id=request.project_run_id,
                icp_key=request.icp_key,
                icp_version=request.icp_version,
                discovery_receipt=discovery_receipt,
            )
        except DiscoverySealConflict:
            seal_reasons.append("discovery_seal_conflict")
        if sealed is None:
            seal_reasons.append("sealed_discovery_batch_missing")
        elif (
            sealed.discovery_batch_id != request.discovery_batch_id
            or sealed.seal_sha256 != request.discovery_seal_sha256
            or request.account_id not in set(sealed.account_ids)
        ):
            seal_reasons.append("account_not_in_exact_sealed_batch")
        sealed_ok = not seal_reasons
        seal_evidence = (
            (
                f"discovery-batch:{sealed.discovery_batch_id}",
                f"discovery-seal:{sealed.seal_sha256}",
            )
            if sealed_ok and sealed is not None
            else ()
        )

        pass_a_reasons: list[str] = []
        pass_a_evidence: list[str] = []
        criteria_reasons: list[str] = []
        criteria_evidence: list[str] = []
        tier_reasons: list[str] = []
        tier_evidence: list[str] = []
        reusable_operation = None
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, request.project_run_id)
            if (
                run is None
                or run.workspace_id != request.workspace_id
                or run.project_id != request.project_id
                or run.icp_key != request.icp_key
                or run.icp_version != request.icp_version
            ):
                pass_a_reasons.append("project_run_lineage_mismatch")
            elif (
                request.entity_research_job_id is None and run.status is not ProjectRunStatus.ACTIVE
            ):
                pass_a_reasons.append("project_run_not_active")
            elif request.entity_research_job_id is None and run.phase is not ProjectPhase.DEEP:
                pass_a_reasons.append("historical_project_run_not_active_deep")
            if request.entity_research_job_id is not None:
                # An exact live R6 account job is already the durable, explicit selection and
                # provider authority for this account. Requiring the legacy scoring checkpoint
                # here reintroduced a signal gate after the user had directly launched research.
                pass_a_evidence.append(f"entity-research-job:{request.entity_research_job_id}")
            else:
                scoring = await get_checkpoint(conn, request.project_run_id, ProjectPhase.SCORING)
                if scoring is None or scoring.status is not PhaseCheckpointStatus.COMMITTED:
                    pass_a_reasons.append("pass_a_scoring_checkpoint_not_committed")
                else:
                    pass_a_evidence.append(f"phase-checkpoint:{scoring.id}")

            selection_policy = None
            selection = None
            if request.entity_research_job_id is not None:
                # Must-have criteria decide broad discovery selection. They are not a second
                # committee gate after a human explicitly selected this exact account and the R6
                # job reached committee work. This condition remains in the audit trail, proven
                # by that exact job rather than a synthetic high/low signal classification.
                criteria_evidence.append(f"entity-research-job:{request.entity_research_job_id}")
            else:
                try:
                    spec = await get_icp_version(
                        conn, request.workspace_id, request.icp_key, request.icp_version
                    )
                    if spec is None:
                        raise ValueError("pinned ICP version does not exist")
                    selection_policy = DiscoverySelectionPolicy.from_slot(spec.discovery_strategy)
                except (LookupError, ValueError):
                    criteria_reasons.append("pinned_icp_selection_policy_invalid")
                if selection_policy is not None:
                    if not selection_policy.required_criteria:
                        criteria_reasons.append("pinned_icp_has_no_must_have_criteria")
                    elif sealed is None:
                        criteria_reasons.append("must_have_proof_requires_sealed_batch")
                    else:
                        try:
                            selection = await load_discovery_criteria_selection(
                                conn,
                                sealed=sealed,
                                workspace_id=request.workspace_id,
                                policy=selection_policy,
                            )
                        except ValueError:
                            criteria_reasons.append("sealed_must_have_selection_invalid")
            selected_view = None
            if selection is not None:
                selected_view = next(
                    (item for item in selection.accounts if item.account_id == request.account_id),
                    None,
                )
                if (
                    selected_view is None
                    or selected_view.disposition is not DiscoverySelectionDisposition.SELECTED
                ):
                    criteria_reasons.append("account_did_not_pass_every_must_have")
                else:
                    for criterion in selected_view.criteria:
                        supported = (
                            criterion.decision.value == "yes"
                            and criterion.observations
                            and any(item.references for item in criterion.observations)
                        )
                        if not supported:
                            criteria_reasons.append(
                                "must_have_not_evidence_backed:" + criterion.criterion
                            )
                            continue
                        for observation in criterion.observations:
                            criteria_evidence.append(f"claim:{observation.claim_id}")
                            criteria_evidence.extend(
                                reference.url for reference in observation.references
                            )

            if request.entity_research_job_id is not None:
                # The exact running R6 job is the explicit human selection. Its provider-spend
                # capacity check below proves that durable authority transactionally, so legacy
                # discovery tier labels are neither required nor interpreted here.
                tier_evidence.append(f"entity-research-job:{request.entity_research_job_id}")
            else:
                tier_checkpoint = await get_checkpoint(
                    conn, request.project_run_id, ProjectPhase.TIER_CHECKPOINT
                )
                if (
                    tier_checkpoint is None
                    or tier_checkpoint.status is not PhaseCheckpointStatus.COMMITTED
                    or tier_checkpoint.payload.get("decision_action") != "approve"
                ):
                    tier_reasons.append("human_tier_checkpoint_not_approved")
                else:
                    tier_evidence.append(f"phase-checkpoint:{tier_checkpoint.id}")
                matching_tiers = []
                for claim in await claims_for(
                    conn,
                    request.account_id,
                    TIER_FIELD,
                    scope=WorkspaceScope.for_workspace(request.workspace_id),
                ):
                    value = claim.value_json
                    if not isinstance(value, dict):
                        continue
                    if (
                        claim.id == request.tier_claim_id
                        and claim.source_tier <= TIER_CLAIM_MAX_SOURCE_TIER
                        and value.get("decision_basis") == "discovery_criteria"
                        and value.get("project_run_id") == str(request.project_run_id)
                        and sealed is not None
                        and value.get("discovery_batch_id") == str(sealed.discovery_batch_id)
                        and value.get("discovery_seal_sha256") == sealed.seal_sha256
                        and value.get("icp_key") == request.icp_key
                        and value.get("icp_version") == request.icp_version
                        and value.get("disposition") == "selected"
                        and value.get("tier") in self._policy.committee_eligible_tiers
                        and selection_policy is not None
                        and value.get("selection_policy_version") == selection_policy.policy_version
                    ):
                        matching_tiers.append(claim)
                if len(matching_tiers) != 1:
                    tier_reasons.append("exact_committee_eligible_tier_claim_missing")
                else:
                    tier_evidence.append(f"claim:{matching_tiers[0].id}")

            reusable_operation = await find_committee_acquisition_operation(
                conn,
                workspace_id=request.workspace_id,
                account_id=request.account_id,
                request_fingerprint=request.request_fingerprint,
                observation_window=request.observation_window,
            )

        plan_reasons: list[str] = []
        plan_evidence: list[str] = []
        authorization_matches = (
            authorization.workspace_id == request.workspace_id
            and authorization.project_id == request.project_id
            and authorization.project_run_id == request.project_run_id
            and authorization.account_id == request.account_id
            and authorization.committee_plan_ref == request.committee_plan_ref
            and request.research_direction_ref is not None
            and authorization.research_direction_ref == request.research_direction_ref
            and authorization.research_directive == request.research_directive
        )
        if not authorization_matches:
            plan_reasons.append("confirmed_directive_lineage_mismatch")
        if not authorization.confirmed_by_human:
            plan_reasons.append("committee_directive_not_human_confirmed")
        if not plan_reasons:
            plan_evidence.extend(
                (
                    authorization.confirmation_ref,
                    authorization.committee_plan_ref,
                    authorization.research_direction_ref,
                )
            )

        governance_reasons: list[str] = []
        governance_evidence: list[str] = []
        if not authorization.personal_data_allowed:
            governance_reasons.append("personal_data_acquisition_not_allowed")
        if not authorization.jurisdiction_allowed:
            governance_reasons.append("jurisdiction_policy_rejected")
        if self._policy.required_use_class not in authorization.allowed_use_classes:
            governance_reasons.append("professional_public_use_class_not_allowed")
        if not authorization.identity_acquisition_allowed:
            governance_reasons.append("identity_acquisition_not_allowed")
        if authorization.contact_reveals_allowed:
            governance_reasons.append("contact_reveal_not_permitted_in_s2")
        for source in self._sources:
            decision = await self._pre_spend_gate.check(
                PreSpendRequest(
                    entity_id=request.account_id,
                    entity_type=EntityType.ACCOUNT,
                    kind=PreSpendKind.ENUMERATION,
                    scope=EnumerationScope.COMMITTEE,
                    source_tier=source.source_tier,
                    source_key=source.source_key,
                    run_id=RunId(request.project_run_id),
                )
            )
            if decision.verdict is not PreSpendVerdict.PASS:
                governance_reasons.extend(
                    f"pre_spend_rejected:{source.source_key}:{reason}"
                    for reason in decision.reasons
                )
            else:
                governance_evidence.append(f"pre-spend:{source.source_key}:pass")

        freshness_reasons: list[str] = []
        freshness_evidence: list[str] = []
        fresh_reusable = False
        stale_ready = False
        if reusable_operation is not None:
            cutoff = evaluated_at - timedelta(seconds=self._policy.reusable_snapshot_ttl_seconds)
            fresh_reusable = (
                reusable_operation.state is CommitteeAcquisitionState.READY
                and reusable_operation.terminal_at is not None
                and reusable_operation.terminal_at >= cutoff
            )
            if fresh_reusable:
                freshness_reasons.append("fresh_exact_snapshot_reusable")
                freshness_evidence.append(f"committee-operation:{reusable_operation.operation_id}")
            elif reusable_operation.state is CommitteeAcquisitionState.READY:
                stale_ready = True
                freshness_reasons.append("same_window_operation_is_not_fresh_reusable")

        try:
            async with self._conn_factory() as conn:
                capacity = await require_provider_spend_capacity(
                    conn,
                    project_run_id=request.project_run_id,
                    proposed_cents=(
                        Decimal(0) if reusable_operation is not None else proposed_cost_cents
                    ),
                    allowed_phases=frozenset({ProjectPhase.DEEP}),
                    entity_research_job_id=request.entity_research_job_id,
                    enforce_budget=self._enforce_budget,
                )
            governance_evidence.extend(
                (
                    authorization.jurisdiction_policy_ref,
                    authorization.identity_policy_ref,
                    authorization.budget_authorization_ref,
                    f"budget-cap:{capacity.cap_cents}",
                    f"budget-spent:{capacity.spent_cents}",
                    f"budget-outstanding:{capacity.outstanding_cents}",
                )
            )
        except ProviderSpendGuardError as exc:
            governance_reasons.append(f"provider_budget_rejected:{type(exc).__name__}")

        conditions = (
            _condition(
                CommitteeEligibilityCondition.SEALED_BATCH_MEMBERSHIP,
                sealed_ok,
                reasons=seal_reasons,
                evidence=seal_evidence,
            ),
            _condition(
                CommitteeEligibilityCondition.PASS_A_COMPLETE,
                not pass_a_reasons,
                reasons=pass_a_reasons,
                evidence=pass_a_evidence,
            ),
            _condition(
                CommitteeEligibilityCondition.MUST_HAVE_CRITERIA,
                not criteria_reasons,
                reasons=criteria_reasons,
                evidence=criteria_evidence,
            ),
            _condition(
                CommitteeEligibilityCondition.HUMAN_APPROVED_TIER,
                not tier_reasons,
                reasons=tier_reasons,
                evidence=tier_evidence,
            ),
            _condition(
                CommitteeEligibilityCondition.CONFIRMED_COMMITTEE_PLAN,
                not plan_reasons,
                reasons=plan_reasons,
                evidence=plan_evidence,
            ),
            _condition(
                CommitteeEligibilityCondition.GOVERNANCE_AND_BUDGET,
                not governance_reasons,
                reasons=governance_reasons,
                evidence=governance_evidence,
            ),
            _condition(
                CommitteeEligibilityCondition.NO_FRESH_REUSABLE_SNAPSHOT,
                not fresh_reusable and not stale_ready,
                reasons=freshness_reasons,
                evidence=freshness_evidence,
            ),
        )
        non_freshness_failed = any(not item.passed for item in conditions[:-1])
        if non_freshness_failed or stale_ready:
            outcome = CommitteeEligibilityOutcome.INELIGIBLE
            reusable_id = None
        elif fresh_reusable:
            outcome = CommitteeEligibilityOutcome.REUSABLE
            assert reusable_operation is not None
            reusable_id = reusable_operation.operation_id
        else:
            outcome = CommitteeEligibilityOutcome.ELIGIBLE
            reusable_id = None
        draft = CommitteeEligibilityDecision(
            decision_id=new_committee_eligibility_decision_id(),
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            project_run_id=request.project_run_id,
            account_id=request.account_id,
            request_fingerprint=request.request_fingerprint,
            authorization_fingerprint=authorization.authorization_fingerprint,
            policy_version=self._policy.version,
            outcome=outcome,
            conditions=conditions,
            reusable_operation_id=reusable_id,
        )
        async with self._conn_factory() as conn:
            recorded, _created = await record_committee_eligibility_decision(conn, draft)
        return recorded


__all__ = [
    "COMMITTEE_ELIGIBILITY_POLICY_VERSION",
    "DEFAULT_COMMITTEE_ELIGIBILITY_POLICY",
    "CommitteeEligibilityPolicy",
    "CommitteeEligibilityService",
    "CommitteeEnumerationSource",
]
