"""D6 production composition for confirmed ICP -> durable Exa Websets acquisition.

The lifecycle worker can only reconcile operations that already exist.  This module owns the
missing API-root boundary: compile the exact pinned ICP into an immutable provider-neutral
``DiscoveryPlan``, create its closed batch, and submit each planned Exa search through D2's
durable paid-call guard.  Stable ids and the request fingerprint make a process restart a pure
database replay; provider transport is never used by an already-terminal/in-flight operation.

The default policy admits the Stage-0 safe default of ten companies and the confirmed upper bound
of fifty, while keeping LinkedIn/revenue enrichments and contact-enrichment opt-in.  The requested
count always comes from the immutable run receipt, never from a provider-specific ICP slot.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from clue_api.discovery_configuration import get_discovery_configuration_receipt
from clue_api.exa_websets_submit import (
    DEFAULT_EXA_WEBSETS_PRICING,
    DurableExaWebsetSubmitter,
    ExaSubmitResult,
    ExaWebsetsPricingPolicy,
)
from clue_api.stage0_project_contracts import DiscoveryConfigurationContract
from clue_core import (
    DiscoveryBatchId,
    DiscoveryCriterionPlan,
    DiscoveryEnrichmentFormat,
    DiscoveryEnrichmentOption,
    DiscoveryEnrichmentPlan,
    DiscoveryEntityKind,
    DiscoveryPlan,
    DiscoveryPlanId,
    DiscoverySearchPlan,
    ICPSpec,
    PhaseContext,
    ProjectPhase,
)
from clue_db import ConnFactory, transaction
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_CONTRACT_VERSION,
    EXA_WEBSETS_SOURCE_KEY,
    ExaWebsetsTransport,
)
from clue_research.discovery_scoring.discovery import (
    DISCOVERY_ENVELOPE_POLICY_V1,
    REVENUE_BAND_OPTIONS,
)
from clue_research.durable import (
    DiscoveryBudgetExceeded,
    DiscoveryReplayConflict,
    ProjectRunStatus,
    create_discovery_batch,
    get_current_discovery_batch,
    get_project_run,
    put_discovery_plan,
)
from clue_research.icp import get_icp_version
from clue_storage import StorageBackend

TransportFactory = Callable[[], AbstractAsyncContextManager[ExaWebsetsTransport]]


class ExaDiscoveryAcquisitionError(RuntimeError):
    """The pinned run/ICP cannot safely produce the bounded D6 paid workload."""


class _ExaStrategySlot(BaseModel):
    """Only the acquisition-owned subset of the otherwise opaque ICP strategy slot."""

    model_config = ConfigDict(frozen=True, extra="allow")

    channels: tuple[str, ...] = ()
    requested_count: int = Field(ge=1)
    entity_type: DiscoveryEntityKind
    query: str = Field(min_length=1)
    must_have_criteria: tuple[str, ...] = Field(min_length=1, max_length=5)


class ExaDiscoveryAcquisitionPolicy(BaseModel):
    """Versioned deployment limits for originating Exa discovery work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "exa-websets-d6-acquisition-policy-v2"
    compiler_version: str = "provider-neutral-discovery-configuration-to-exa-v2"
    maximum_results: int = Field(default=50, ge=1, le=100)
    maximum_provider_credits: int = Field(default=700, ge=0)
    maximum_cost_cents: Decimal = Field(default=Decimal("315"), ge=0)
    include_contact_enrichments: bool = False
    search_key: str = "account-discovery"


DEFAULT_EXA_DISCOVERY_ACQUISITION_POLICY = ExaDiscoveryAcquisitionPolicy()


class ExaDiscoveryPreflight(BaseModel):
    """Non-secret, deterministic evidence shown before a possible paid create."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: DiscoveryPlan
    batch_id: DiscoveryBatchId
    observation_window: str
    maximum_provider_credits: Decimal
    maximum_cost_cents: Decimal
    contact_enrichments_enabled: bool


class ExaDiscoveryStartResult(BaseModel):
    """The durable acquisition result; submit results expose exact network-call counts."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    preflight: ExaDiscoveryPreflight
    submissions: tuple[ExaSubmitResult, ...]


def _semantic_uuid(label: str, ctx: PhaseContext, policy: ExaDiscoveryAcquisitionPolicy) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        (
            f"clue://discovery/{ctx.workspace_id}/{ctx.project_run_id}/{ctx.icp_key}/"
            f"v{ctx.icp_version}/{policy.compiler_version}/{policy.version}/"
            f"contacts-{int(policy.include_contact_enrichments)}/{label}"
        ),
    )


def _observation_window(ctx: PhaseContext, policy: ExaDiscoveryAcquisitionPolicy) -> str:
    identity = _semantic_uuid("observation", ctx, policy)
    return f"project-run:{ctx.project_run_id}:d6:{identity}"


def _enrichments(*, include_contacts: bool) -> tuple[DiscoveryEnrichmentPlan, ...]:
    enrichments = [
        DiscoveryEnrichmentPlan(
            field_key="core.company_linkedin_url",
            description="The official LinkedIn company page URL for this organization",
            format=DiscoveryEnrichmentFormat.URL,
        ),
        DiscoveryEnrichmentPlan(
            field_key="core.revenue_band",
            description=(
                "The organization's estimated annual revenue band in USD; return exactly one "
                "provided option"
            ),
            format=DiscoveryEnrichmentFormat.OPTIONS,
            options=tuple(DiscoveryEnrichmentOption(label=label) for label in REVENUE_BAND_OPTIONS),
        ),
    ]
    if include_contacts:
        enrichments.extend(
            (
                DiscoveryEnrichmentPlan(
                    field_key="core.company_email",
                    description="A public general company email address for this organization",
                    format=DiscoveryEnrichmentFormat.EMAIL,
                ),
                DiscoveryEnrichmentPlan(
                    field_key="core.company_phone",
                    description="A public main company phone number for this organization",
                    format=DiscoveryEnrichmentFormat.PHONE,
                ),
            )
        )
    return tuple(enrichments)


def _exa_criteria(configuration: DiscoveryConfigurationContract) -> tuple[str, ...]:
    """Pack every must/exclusion rule into Exa's five 1,000-character criterion slots."""

    statements = tuple(
        [f"Must match: {item}" for item in configuration.must_have_criteria]
        + [f"Must not match: {item}" for item in configuration.exclusion_criteria]
    )
    packed: list[str] = []
    for statement in statements:
        if len(statement) > 1_000:
            raise ExaDiscoveryAcquisitionError("one discovery criterion exceeds Exa's limit")
        if packed and len(packed[-1]) + 2 + len(statement) <= 1_000:
            packed[-1] = packed[-1] + "; " + statement
        else:
            packed.append(statement)
    if len(packed) > 5:
        raise ExaDiscoveryAcquisitionError(
            "the confirmed discovery criteria cannot fit Exa's five bounded criterion slots"
        )
    return tuple(packed)


def compile_exa_discovery_preflight(
    *,
    ctx: PhaseContext,
    spec: ICPSpec,
    configuration: DiscoveryConfigurationContract | None = None,
    policy: ExaDiscoveryAcquisitionPolicy = DEFAULT_EXA_DISCOVERY_ACQUISITION_POLICY,
    pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
) -> ExaDiscoveryPreflight:
    """Compile one pinned ICP without I/O and enforce the complete paid-workload envelope."""

    if ctx.phase is not ProjectPhase.DISCOVERY:
        raise ExaDiscoveryAcquisitionError("Exa acquisition may originate only in discovery")
    if (
        spec.workspace_id != ctx.workspace_id
        or spec.icp_key != ctx.icp_key
        or spec.version != ctx.icp_version
    ):
        raise ExaDiscoveryAcquisitionError("ICP spec does not match the project-run lineage")
    if configuration is None:
        # Historical project runs have no run-level configuration receipt.  Preserve only their
        # explicit Exa-shaped contract; current Stage-0 firmographics must never be reinterpreted
        # here because that was the production failure this boundary replaces.
        strategy = _ExaStrategySlot.model_validate(spec.discovery_strategy)
        if EXA_WEBSETS_SOURCE_KEY not in strategy.channels:
            raise ExaDiscoveryAcquisitionError("confirmed ICP does not enable Exa Websets")
        entity_type = strategy.entity_type
        requested_count = strategy.requested_count
        query = strategy.query
        criteria = strategy.must_have_criteria
    else:
        if configuration.approved_icp_ref != (
            f"icp-spec:{ctx.workspace_id}:{ctx.icp_key}:v{ctx.icp_version}"
        ):
            raise ExaDiscoveryAcquisitionError(
                "discovery configuration does not match the project-run ICP"
            )
        entity_type = DiscoveryEntityKind(configuration.entity_type)
        requested_count = configuration.requested_account_count
        query = configuration.search_intent
        criteria = _exa_criteria(configuration)
    if entity_type is not DiscoveryEntityKind.COMPANY:
        raise ExaDiscoveryAcquisitionError("D6 production acquisition supports company rows only")
    if requested_count > policy.maximum_results:
        raise ExaDiscoveryAcquisitionError(
            f"requested {requested_count} rows exceeds policy maximum {policy.maximum_results}"
        )
    search = DiscoverySearchPlan(
        search_key=policy.search_key,
        channel_key=EXA_WEBSETS_SOURCE_KEY,
        normalized_query=query,
        entity_type=entity_type,
        requested_count=requested_count,
        criteria=tuple(DiscoveryCriterionPlan(description=description) for description in criteria),
        enrichments=_enrichments(include_contacts=policy.include_contact_enrichments),
    )
    maximum_units = pricing.maximum_units(search)
    maximum_cost = pricing.maximum_cost_cents(search)
    if maximum_units > policy.maximum_provider_credits:
        raise ExaDiscoveryAcquisitionError(
            f"maximum Exa spend {maximum_units} credits exceeds policy cap "
            f"{policy.maximum_provider_credits}"
        )
    if maximum_cost > policy.maximum_cost_cents:
        raise ExaDiscoveryAcquisitionError(
            f"maximum allocated cost {maximum_cost} cents exceeds policy cap "
            f"{policy.maximum_cost_cents}"
        )
    if maximum_units != maximum_units.to_integral_value():
        raise ExaDiscoveryAcquisitionError("provider credit reservation must be integral")
    plan = DiscoveryPlan(
        discovery_plan_id=DiscoveryPlanId(_semantic_uuid("plan", ctx, policy)),
        plan_version=1,
        workspace_id=ctx.workspace_id,
        project_id=ctx.project_id,
        project_run_id=ctx.project_run_id,
        icp_key=ctx.icp_key,
        icp_version=ctx.icp_version,
        provider_policy_version=pricing.version,
        field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
        provider_contract_version=EXA_WEBSETS_CONTRACT_VERSION,
        channels=(EXA_WEBSETS_SOURCE_KEY,),
        searches=(search,),
        required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
        optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
        provider_credit_cap=int(maximum_units),
        money_budget_cap_cents=maximum_cost,
        stopping_policy={
            "closed_batch": True,
            "requested_count": requested_count,
            "advance_only_after": "immutable_discovery_batch_seal",
            "policy_version": policy.version,
        },
        snapshot_reuse_policy="same_project_run_and_pinned_icp",
    )
    return ExaDiscoveryPreflight(
        plan=plan,
        batch_id=DiscoveryBatchId(_semantic_uuid("batch-generation-1", ctx, policy)),
        observation_window=_observation_window(ctx, policy),
        maximum_provider_credits=maximum_units,
        maximum_cost_cents=maximum_cost,
        contact_enrichments_enabled=policy.include_contact_enrichments,
    )


class ExaWebsetsDiscoveryStarter:
    """Production ``DiscoveryBatchStarter`` backed by D1/D2 durability and Exa transport."""

    def __init__(
        self,
        *,
        transport_factory: TransportFactory,
        storage: StorageBackend,
        policy: ExaDiscoveryAcquisitionPolicy = DEFAULT_EXA_DISCOVERY_ACQUISITION_POLICY,
        pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
        conn_factory: ConnFactory = transaction,
        enforce_budget: bool = True,
    ) -> None:
        self._transport_factory = transport_factory
        self._storage = storage
        self._policy = policy
        self._pricing = pricing
        self._conn_factory = conn_factory
        # FI pilot budget-controls, threaded from ``Settings.budget_controls_enabled`` at the
        # composition root. False means this path never refuses on budget grounds; every
        # durable row it writes is unchanged.
        self._enforce_budget = enforce_budget

    async def preflight(self, ctx: PhaseContext) -> ExaDiscoveryPreflight:
        async with self._conn_factory() as conn:
            spec = await get_icp_version(conn, ctx.workspace_id, ctx.icp_key, ctx.icp_version)
            run = await get_project_run(conn, ctx.project_run_id)
            configuration_receipt = await get_discovery_configuration_receipt(
                conn,
                project_run_id=ctx.project_run_id,
                workspace_id=ctx.workspace_id,
            )
        if spec is None:
            raise ExaDiscoveryAcquisitionError("pinned ICP spec is missing")
        if run is None or run.workspace_id != ctx.workspace_id or run.project_id != ctx.project_id:
            raise ExaDiscoveryAcquisitionError("project run is missing or outside the phase scope")
        if (
            run.status is not ProjectRunStatus.ACTIVE
            or run.phase is not ProjectPhase.DISCOVERY
            or run.phase is not ctx.phase
        ):
            raise ExaDiscoveryAcquisitionError("project run is not currently in discovery")
        result = compile_exa_discovery_preflight(
            ctx=ctx,
            spec=spec,
            configuration=(
                configuration_receipt.configuration if configuration_receipt is not None else None
            ),
            policy=self._policy,
            pricing=self._pricing,
        )
        # FI pilot budget-controls: the discovery preflight's remaining-headroom refusal is a
        # pre-action stop on budget grounds, so it goes inert with the switch off. The bound on
        # *how much* this discovery may buy is unchanged — it is the plan's own
        # ``maximum_cost_cents``, a structural fan-out cap, and it still rides the plan row.
        if self._enforce_budget and run.budget_cap_cents is not None:
            remaining = run.budget_cap_cents - run.spent_cents
            if result.maximum_cost_cents > remaining:
                raise DiscoveryBudgetExceeded(
                    "bounded Exa discovery reservation exceeds remaining project-run budget"
                )
        return result

    async def start(self, ctx: PhaseContext) -> ExaDiscoveryStartResult:
        preflight = await self.preflight(ctx)
        plan = preflight.plan
        async with self._conn_factory() as conn:
            current = await get_current_discovery_batch(
                conn,
                workspace_id=ctx.workspace_id,
                project_run_id=ctx.project_run_id,
            )
            if current is not None and current.id != preflight.batch_id:
                raise DiscoveryReplayConflict(
                    "project run already owns a different discovery generation"
                )
            await put_discovery_plan(conn, workspace_id=ctx.workspace_id, plan=plan)
            batch = await create_discovery_batch(
                conn,
                workspace_id=ctx.workspace_id,
                batch_id=preflight.batch_id,
                plan_id=plan.discovery_plan_id,
                generation=1,
            )

        submissions: list[ExaSubmitResult] = []
        for search in plan.searches:
            async with self._transport_factory() as transport:
                submitter = DurableExaWebsetSubmitter(
                    transport=transport,
                    storage=self._storage,
                    pricing=self._pricing,
                    conn_factory=self._conn_factory,
                    enforce_budget=self._enforce_budget,
                )
                submissions.append(
                    await submitter.submit(
                        workspace_id=ctx.workspace_id,
                        batch_id=batch.id,
                        search_key=search.search_key,
                        observation_window=preflight.observation_window,
                    )
                )
        return ExaDiscoveryStartResult(preflight=preflight, submissions=tuple(submissions))

    async def ensure_started(self, ctx: PhaseContext) -> DiscoveryBatchId:
        return (await self.start(ctx)).preflight.batch_id


__all__ = [
    "DEFAULT_EXA_DISCOVERY_ACQUISITION_POLICY",
    "ExaDiscoveryAcquisitionError",
    "ExaDiscoveryAcquisitionPolicy",
    "ExaDiscoveryPreflight",
    "ExaDiscoveryStartResult",
    "ExaWebsetsDiscoveryStarter",
    "TransportFactory",
    "compile_exa_discovery_preflight",
]
