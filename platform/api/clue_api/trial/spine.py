"""Operational direct-account spine for the Sumble-only Clue Trial.

This module composes existing authorities; it owns no parallel workflow. Stage 0 supplies the
confirmed client/product/ICP lineage, the M6 admission gate records direct human account input, the
Sumble acquisition service archives paid receipts, ``ComposingRunDriver`` executes the production
phase handlers, and C7 composes the inspectable result.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Final, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue, SecretStr
from sqlalchemy import text

from clue_api.composition import load_research_packs
from clue_api.research_view_runtime import ProductionResearchViewComposer
from clue_api.run_composition import ComposingRunDriver
from clue_api.stage0_tools import start_confirmed_project_run
from clue_api.stage0_trial import Stage0TrialState
from clue_api.storage_wiring import build_storage_backend
from clue_api.trial.sumble import DbSumbleReceiptStore, SumbleAcquisitionService
from clue_config import DEFAULT_STAGE0_POLICY, Secrets, Settings, load_settings
from clue_core import (
    EntityId,
    EntityType,
    LLMGateway,
    ProjectPhase,
    ProjectRunId,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    ResearchViewReadRequest,
    RunId,
)
from clue_db import ConnFactory, transaction
from clue_research.discovery_scoring import (
    AdmissionStatus,
    CandidateHypothesis,
    admit,
    project_discovery_run_id,
)
from clue_research.durable import ProjectRunRow, ProjectRunStatus
from clue_research.icp import get_icp_version
from clue_research.identity import registrable_domain
from clue_research.narrative import ResearchViewCompositionError
from clue_research.resolvers.sumble import (
    SUMBLE_SOURCE_KEYS,
    MutableSumbleSnapshotLookup,
    SumbleClient,
    SumbleCreditBudget,
    SumbleSnapshot,
    matched_organization_id,
    register_sumble_resolvers,
)
from clue_research.sources import clear_resolver_bindings
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    compile_product_context,
    evaluate_readiness,
    override_readiness,
    read_client_kb_claims,
)
from clue_storage import StorageBackend

_DIRECT_RESEARCH_CUTOFFS: Final[dict[str, JsonValue]] = {
    "bands": [
        {
            "tier": "trial_direct",
            "min_fit": 0.0,
            "min_intent": 0.0,
        }
    ],
    "fallback_tier": "not_selected",
}
SumbleClientFactory = Callable[[SecretStr, SumbleCreditBudget], SumbleClient]


class TrialReadinessOverrideRequired(RuntimeError):
    """Stage 0 did not clear the configured discovery-spend floor."""

    def __init__(self, reason_codes: tuple[str, ...]) -> None:
        super().__init__(
            "Stage 0 is not ready for provider spend; supply an explicit human override reason"
        )
        self.reason_codes = reason_codes


class TrialAccountNotAdmitted(RuntimeError):
    """The direct account failed or paused at the shared existence/identity gate."""


class TrialProjectRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    readiness_decision_id: ReadinessDecisionId
    product_context_version_id: UUID
    readiness_verdict: ReadinessVerdict
    readiness_overridden: bool


class SumbleAcquisitionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    organization_id: int | None
    snapshots: tuple[SumbleSnapshot, ...]
    skipped: tuple[str, ...] = ()

    @property
    def realized_credits(self) -> int:
        return sum(snapshot.credits_used for snapshot in self.snapshots)


class TrialResearchState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run: ProjectRunRow
    account_entity_id: EntityId
    checkpoint: dict[str, JsonValue] | None = None
    research_view: dict[str, JsonValue] | None = None
    research_view_error: str | None = None
    committee_posture: str = (
        "account-only trial: no committee source is configured; contact output is intentionally "
        "empty and must not be interpreted as a complete buying committee"
    )


def _domain(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    host = parsed.hostname
    if host is None:
        raise ValueError("account domain must be a hostname or URL")
    normalized = registrable_domain(host)
    if normalized is None:
        raise ValueError("account domain does not contain a registrable hostname")
    return normalized


def _acquisition_run_id(project_run_id: ProjectRunId, entity_id: EntityId) -> RunId:
    return RunId(
        uuid5(
            NAMESPACE_URL,
            f"clue:trial:sumble-acquisition:{project_run_id}:{entity_id}",
        )
    )


class ClueTrialSpine:
    """Thin API-root orchestrator over the production run and C7 seams."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        gateway: LLMGateway | None = None,
        storage: StorageBackend | None = None,
        snapshots: MutableSumbleSnapshotLookup | None = None,
        driver: ComposingRunDriver | None = None,
        sumble_client_factory: SumbleClientFactory | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings or load_settings()
        self._storage = storage or build_storage_backend(self._settings)
        self._snapshots = snapshots or MutableSumbleSnapshotLookup()
        self._conn_factory = conn_factory
        self._sumble_client_factory = sumble_client_factory or (
            lambda api_key, budget: SumbleClient(api_key=api_key, budget=budget)
        )

        # This app is a standalone Sumble-only canary process. Clear the process-global resolver
        # map once at composition so no resolver previously imported by another local surface can
        # silently participate in the first-wave run.
        clear_resolver_bindings()
        register_sumble_resolvers(self._snapshots)
        self._driver = driver or ComposingRunDriver(
            settings=self._settings,
            gateway=gateway,
            storage=self._storage,
            channels=None,
            committee_sources=(),
            session_factory=conn_factory,
        )
        self._views = ProductionResearchViewComposer()

    async def bootstrap(self) -> None:
        """Load the canonical field/source packs before any trial spends or writes claims."""

        async with self._conn_factory() as conn:
            await load_research_packs(conn)

    async def prepare_project_run(
        self,
        *,
        state: Stage0TrialState,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: Decimal,
        readiness_override_reason: str | None = None,
    ) -> TrialProjectRun:
        """Compile the confirmed Stage-0 context and start one idempotent run at DISCOVERY."""

        decision_id = ReadinessDecisionId(
            uuid5(
                state.session_id,
                f"clue-trial:discovery-readiness:{icp_key}:{icp_version}",
            )
        )
        project_run_id = ProjectRunId(
            uuid5(
                state.session_id,
                f"clue-trial:project-run:{icp_key}:{icp_version}",
            )
        )
        async with self._conn_factory() as conn:
            spec = await get_icp_version(
                conn,
                state.workspace_id,
                icp_key,
                icp_version,
            )
            if spec is None or spec.product_id != state.product_id:
                raise ValueError("confirmed ICP is absent or belongs to another product")
            claims = await read_client_kb_claims(
                conn,
                EntityId(state.client_entity_id),
                workspace_id=state.workspace_id,
                version=state.client_kb_version,
                product_id=state.product_id,
            )
            context = await compile_product_context(
                conn,
                workspace_id=state.workspace_id,
                brand_id=state.brand_id,
                product_id=state.product_id,
                client_entity_id=EntityId(state.client_entity_id),
                client_kb_version=state.client_kb_version,
                claim_refs=tuple(str(claim.id) for claim in claims.values()),
            )
            knowledge_fields = set(CLIENT_KNOWLEDGE_FIELDS)
            available = sorted(knowledge_fields.intersection(claims))
            coverage_ratio = len(available) / len(knowledge_fields) if knowledge_fields else 1.0
            readiness = await evaluate_readiness(
                conn,
                workspace_id=state.workspace_id,
                brand_id=state.brand_id,
                gate=ReadinessGate.DISCOVERY_SPEND,
                spec=DEFAULT_STAGE0_POLICY.readiness,
                metrics={
                    "coverage_ratio": coverage_ratio,
                    "verified_claims": sum(
                        claim.verification_status.value == "verified"
                        for claim in claims.values()
                    ),
                    "open_policy_blocks": 0,
                    "available_field_keys": cast(list[JsonValue], available),
                },
                created_by_actor="agent",
                product_id=state.product_id,
                project_id=state.project_id,
                client_entity_id=EntityId(state.client_entity_id),
                client_kb_version=state.client_kb_version,
                icp_key=icp_key,
                icp_version=icp_version,
                product_context_version_id=context.version_id,
                readiness_decision_id=decision_id,
            )
            overridden = False
            if readiness.verdict is ReadinessVerdict.NOT_READY:
                row = await conn.execute(
                    text("SELECT reason_codes FROM readiness_decision WHERE id=:id"),
                    {"id": decision_id},
                )
                reasons_value = row.scalar_one()
                reasons = tuple(
                    item for item in reasons_value if isinstance(item, str)
                )
                if not readiness_override_reason:
                    raise TrialReadinessOverrideRequired(reasons)
                await override_readiness(
                    conn,
                    decision_id=decision_id,
                    workspace_id=state.workspace_id,
                    gate=ReadinessGate.DISCOVERY_SPEND,
                    actor="human",
                    reason=readiness_override_reason,
                )
                overridden = True
            await start_confirmed_project_run(
                conn,
                project_run_id=project_run_id,
                workspace_id=state.workspace_id,
                project_id=state.project_id,
                client_entity_id=EntityId(state.client_entity_id),
                client_kb_version=state.client_kb_version,
                product_id=state.product_id,
                product_context_version_id=context.version_id,
                readiness_decision_id=decision_id,
                icp_key=icp_key,
                icp_version=icp_version,
                budget_cap_cents=budget_cap_cents,
            )
        return TrialProjectRun(
            project_run_id=project_run_id,
            readiness_decision_id=decision_id,
            product_context_version_id=UUID(str(context.version_id)),
            readiness_verdict=readiness.verdict,
            readiness_overridden=overridden,
        )

    async def admit_direct_account(
        self,
        *,
        state: Stage0TrialState,
        project_run: TrialProjectRun,
        icp_key: str,
        icp_version: int,
        domain: str,
        name: str | None = None,
    ) -> EntityId:
        """Route one human-provided domain through the shared M6 admission/identity gate."""

        normalized = _domain(domain)
        candidate = CandidateHypothesis(
            matched_channel="import",
            source_record_ref=(
                f"human:clue-trial:{state.session_id}:account:{normalized}"
            ),
            source_url=f"https://{normalized}",
            raw_name=name or normalized,
            candidate_domain=normalized,
            matched_signal="direct_human_account_input",
            resolver_confidence=1.0,
        )
        run_id = project_discovery_run_id(
            project_run_id=project_run.project_run_id,
            icp_key=icp_key,
            icp_version=icp_version,
        )
        async with self._conn_factory() as conn:
            result = await admit(
                conn,
                candidate,
                run_id,
                workspace_id=state.workspace_id,
            )
        if result.status is not AdmissionStatus.ADMITTED or result.account_entity_id is None:
            raise TrialAccountNotAdmitted(
                f"direct account admission ended as {result.status.value}: "
                f"{result.reason or result.review_task_id or 'no reason'}"
            )
        return result.account_entity_id

    async def acquire_sumble(
        self,
        *,
        state: Stage0TrialState,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        domain: str,
        max_credits: int,
        allow_unbounded_tech: bool,
    ) -> SumbleAcquisitionResult:
        """Archive and bind the three first-wave responses, skipping tech unless approved."""

        secret = Secrets().sumble_api_key
        if secret is None:
            raise RuntimeError("CLUE_SUMBLE_API_KEY is required for a live Sumble trial")
        budget = SumbleCreditBudget(maximum=max_credits)
        service = SumbleAcquisitionService(
            client=self._sumble_client_factory(secret, budget),
            receipts=DbSumbleReceiptStore(
                workspace_id=state.workspace_id,
                storage=self._storage,
                conn_factory=self._conn_factory,
            ),
        )
        acquisition_run = _acquisition_run_id(project_run_id, account_entity_id)
        organization = await service.organization(
            account_run_id=acquisition_run,
            entity_id=account_entity_id,
            domain=_domain(domain),
        )
        self._snapshots.put(account_entity_id, organization)
        snapshots = [organization]
        skipped: list[str] = []
        organization_id = matched_organization_id(organization.payload)
        if organization_id is None:
            skipped.extend(("sumble_jobs:no_matched_organization", "sumble_tech_stack:no_match"))
            return SumbleAcquisitionResult(
                account_entity_id=account_entity_id,
                organization_id=None,
                snapshots=tuple(snapshots),
                skipped=tuple(skipped),
            )
        jobs = await service.jobs(
            account_run_id=acquisition_run,
            entity_id=account_entity_id,
            organization_id=organization_id,
        )
        self._snapshots.put(account_entity_id, jobs)
        snapshots.append(jobs)
        if allow_unbounded_tech:
            tech = await service.tech_stack(
                account_run_id=acquisition_run,
                entity_id=account_entity_id,
                organization_id=organization_id,
                allow_unbounded=True,
            )
            self._snapshots.put(account_entity_id, tech)
            snapshots.append(tech)
        else:
            skipped.append("sumble_tech_stack:unbounded_credit_risk_not_approved")
        return SumbleAcquisitionResult(
            account_entity_id=account_entity_id,
            organization_id=organization_id,
            snapshots=tuple(snapshots),
            skipped=tuple(skipped),
        )

    async def drive_to_tier_checkpoint(
        self,
        *,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
    ) -> TrialResearchState:
        """Drive real DISCOVERY and SCORING handlers, stopping at the durable human gate."""

        while True:
            row = await self._driver.status(project_run_id)
            if row.status in (ProjectRunStatus.PAUSED, ProjectRunStatus.FAILED):
                break
            if row.phase is ProjectPhase.HANDOFF:
                break
            row = await self._driver.advance(project_run_id)
            if row.phase is ProjectPhase.TIER_CHECKPOINT and row.status is ProjectRunStatus.PAUSED:
                break
        checkpoint = None
        if row.phase is ProjectPhase.TIER_CHECKPOINT:
            composed = await self._driver.composed(row)
            stored = await composed.run.await_checkpoint(project_run_id)
            if stored is not None:
                checkpoint = stored.payload
        return TrialResearchState(
            project_run=row,
            account_entity_id=account_entity_id,
            checkpoint=checkpoint,
        )

    async def approve_direct_research(
        self,
        *,
        state: Stage0TrialState,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
    ) -> TrialResearchState:
        """Apply explicit human direct-research admission, then drive through REVIEW."""

        row = await self._driver.status(project_run_id)
        if (
            row.phase is ProjectPhase.TIER_CHECKPOINT
            and row.status is ProjectRunStatus.PAUSED
        ):
            composed = await self._driver.composed(row)
            row = await composed.run.submit_checkpoint(
                project_run_id,
                decision={
                    "action": "approve",
                    "tier_cutoffs": _DIRECT_RESEARCH_CUTOFFS,
                },
            )
        while row.status is ProjectRunStatus.ACTIVE and row.phase is not ProjectPhase.HANDOFF:
            row = await self._driver.advance(project_run_id)
            if row.status in (ProjectRunStatus.PAUSED, ProjectRunStatus.FAILED):
                break

        view_payload: dict[str, JsonValue] | None = None
        view_error: str | None = None
        try:
            view = await self._views.compose(
                ResearchViewReadRequest(
                    workspace_id=state.workspace_id,
                    project_id=state.project_id,
                    project_run_id=project_run_id,
                    subject_entity_id=account_entity_id,
                    subject_entity_type=EntityType.ACCOUNT,
                    product_id=state.product_id,
                )
            )
            view_payload = view.model_dump(mode="json")
        except ResearchViewCompositionError as exc:
            # The run state remains the authoritative diagnostic. A failed/empty DEEP may have no
            # account_run yet, in which case C7 correctly has no scoped subject to compose.
            view_error = str(exc)
        return TrialResearchState(
            project_run=row,
            account_entity_id=account_entity_id,
            research_view=view_payload,
            research_view_error=view_error,
        )

    @property
    def allowed_source_keys(self) -> frozenset[str]:
        return SUMBLE_SOURCE_KEYS


__all__ = [
    "ClueTrialSpine",
    "SumbleAcquisitionResult",
    "TrialAccountNotAdmitted",
    "TrialProjectRun",
    "TrialReadinessOverrideRequired",
    "TrialResearchState",
]
