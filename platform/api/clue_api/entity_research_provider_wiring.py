"""R10 production provider composition for the shared account/contact research fleet.

The role agents select semantic tools. This module alone reconstructs concrete provider actions
from each immutable job and its durable directive/selection authority. It performs no acquisition
while composing: Exa/Sumble transports remain dormant until the responsible agent tool executes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue

from clue_agents.contracts import ModelPolicy
from clue_api.committee_eligibility import (
    CommitteeEligibilityService,
    CommitteeEnumerationSource,
)
from clue_api.contact_channel_enrichment import ExaContactChannelCoordinator
from clue_api.contact_entity_research import ContactChannelActions, ContactResearchStateStore
from clue_api.contact_entity_research_channels import GovernedContactChannelActions
from clue_api.contact_research_fleet_composition import (
    RunScopedContactResearchChannelActions,
    RunScopedContactResearchProviderActions,
)
from clue_api.entity_research_fleet_composition import (
    EntityResearchFleetComposition,
    build_entity_research_fleet_composition,
)
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchProviderAction,
    EntityResearchResultIntegrityError,
    ProviderActionBinding,
    ProviderResearchProjectionDraft,
)
from clue_api.exa_contact_acquisition import ExaDeepContactAcquisitionService
from clue_api.exa_contact_materialization import (
    ExaDeepContactSnapshotMaterializer,
    ExaDeepContactSnapshotResolverProvider,
)
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepHttpAcquisitionTransport,
    pack_exa_deep_field_bundles,
)
from clue_api.exa_deep_materialization import ExaDeepSnapshotResolverProvider
from clue_api.exa_entity_research_tools import (
    DEFAULT_ACCOUNT_RESEARCH_INTENT,
    ExaAccountSemanticResearchAction,
    ExaContactSemanticResearchAction,
    ExaEntityResearchProjectionBuilder,
)
from clue_api.prose_synthesis_step import ProseSynthesisStep
from clue_api.sumble_account_gaps import build_production_sumble_account_gap_starter
from clue_api.sumble_committee_acquisition import SumbleCommitteeAcquisitionCoordinator
from clue_api.sumble_committee_inputs import DurableSumbleCommitteeInputResolver
from clue_api.sumble_committee_preparation import SumbleCommitteePreparationInputs
from clue_api.sumble_entity_research_tools import (
    SumbleAccountSemanticEnrichmentAction,
    SumbleCommitteeSemanticResearchAction,
)
from clue_config import GatewayConfig, Secrets, Settings
from clue_core import (
    EntityId,
    LLMGateway,
    PreSpendGate,
    ProjectRunId,
    RunId,
    SourceTier,
)
from clue_core.contact_research import ContactResearchIntent, ContactResearchPolicyPin
from clue_core.entity_research import (
    GovernedResearchToolRequest,
    ResearchSubjectType,
)
from clue_db import ConnFactory, transaction
from clue_fleet import EntityResearchJobRow
from clue_research.claimstore import FieldRegistryScope, get_effective_field
from clue_research.directives import effective_account_research_directive
from clue_research.durable import get_account_run
from clue_research.identity import get_account
from clue_research.resolvers.exa import SOURCE_KEY as EXA_SOURCE_KEY
from clue_research.resolvers.exa import ExaDeepConfig, ExaDeepFieldSpec
from clue_research.resolvers.exa.deep_contract import EXA_OUTPUT_MAX_FIELDS
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    ORGANIZATIONS_SOURCE_KEY,
    TECH_STACK_SOURCE_KEY,
)
from clue_research.resolvers.sumble.committee_transport import SumbleV9CommitteeClient
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_research.resolvers.sumble.teams import TEAMS_SOURCE_KEY
from clue_research.sources import get_source
from clue_storage import StorageBackend


class EntityResearchProductionCompositionError(RuntimeError):
    """A promoted job cannot reconstruct its exact provider/runtime authority."""


class _UnavailableProviderAction(EntityResearchProviderAction):
    """Keep the frozen semantic surface while rejecting an unselected provider before dispatch."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Any,
        settle_terminal: Any,
    ) -> tuple[ProviderResearchProjectionDraft, ...]:
        del request, before_dispatch, settle_terminal
        # A model choosing a provider the exact job never selected is a repairable request, not a
        # job-integrity failure: refuse it back to the agent without suspending the account.
        raise EntityResearchGovernedRejection("provider_not_selected", self._reason)


@dataclass(frozen=True, slots=True)
class _ResolvedAccountContext:
    account_run_id: UUID
    tier: str
    directive: Any


class _AccountContextLoader:
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def load(
        self,
        job: EntityResearchJobRow,
        *,
        account_run_id: UUID,
    ) -> _ResolvedAccountContext:
        async with self._conn_factory() as conn:
            account_run = await get_account_run(conn, RunId(account_run_id))
            if (
                account_run is None
                or account_run.entity_id != EntityId(job.authorization.subject_entity_id)
                or account_run.project_run_id != ProjectRunId(job.authorization.project_run_id)
                or account_run.research_directive is None
            ):
                raise EntityResearchProductionCompositionError(
                    "account provider composition lacks its exact directive-pinned account run"
                )
            directive = await effective_account_research_directive(
                conn,
                workspace_id=job.workspace_id,
                directive_id=account_run.research_directive.directive_id,
                account_id=EntityId(job.authorization.subject_entity_id),
                expected_pin=account_run.research_directive,
            )
        if (
            directive.pin.directive_ref != job.authorization.selection.directive_ref
            or directive.pin.canonical_json_sha256 != job.authorization.selection.directive_sha256
        ):
            raise EntityResearchProductionCompositionError(
                "account provider composition observed changed directive authority"
            )
        return _ResolvedAccountContext(
            account_run_id=account_run_id,
            tier=account_run.tier,
            directive=directive,
        )


@dataclass(frozen=True, slots=True)
class _CommitteeInputs:
    resolver: DurableSumbleCommitteeInputResolver
    job: EntityResearchJobRow
    account_run_id: UUID
    tier: str

    async def resolve(self) -> SumbleCommitteePreparationInputs:
        return await self.resolver.resolve(
            account_entity_id=EntityId(self.job.authorization.subject_entity_id),
            account_run_id=RunId(self.account_run_id),
            project_run_id=ProjectRunId(self.job.authorization.project_run_id),
            workspace_id=self.job.workspace_id,
            tier=self.tier,
            entity_research_job_id=self.job.job_id,
        )


def _binding(
    action: EntityResearchProviderAction,
    *,
    family: str,
    reserve: Decimal,
    concurrency: int,
) -> ProviderActionBinding:
    if reserve <= 0:
        raise EntityResearchProductionCompositionError(
            f"provider {family} lacks a positive worst-case R9 reservation"
        )
    return ProviderActionBinding(
        action=action,
        version=1,
        provider_family=family,
        budget_reservation_cents=reserve,
        provider_rate_limit_ref=f"provider-rate:entity-research:{family}:v1",
        provider_concurrency_limit=concurrency,
    )


class ProductionAccountResearchProviderActions:
    """Build all R5 actions without doing provider work or reading process-local launch state."""

    def __init__(
        self,
        *,
        settings: Settings,
        secrets: Secrets,
        storage: StorageBackend,
        pre_spend_gate: PreSpendGate,
        gateway: LLMGateway,
        gateway_config: GatewayConfig,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._storage = storage
        self._gateway = gateway
        self._gateway_config = gateway_config
        self._conn_factory = conn_factory
        self._contexts = _AccountContextLoader(conn_factory=conn_factory)
        self._committee_inputs = DurableSumbleCommitteeInputResolver(
            settings=settings,
            storage=storage,
            conn_factory=conn_factory,
        )
        self._committee_eligibility = CommitteeEligibilityService(
            storage=storage,
            pre_spend_gate=pre_spend_gate,
            sources=(
                CommitteeEnumerationSource(source_key=TEAMS_SOURCE_KEY, source_tier=SourceTier(1)),
                CommitteeEnumerationSource(source_key=PEOPLE_SOURCE_KEY, source_tier=SourceTier(1)),
            ),
            conn_factory=conn_factory,
            enforce_budget=settings.budget_controls_enabled,
        )

    async def resolve(self, job: EntityResearchJobRow) -> dict[str, ProviderActionBinding]:
        if job.subject_type is not ResearchSubjectType.ACCOUNT:
            raise EntityResearchProductionCompositionError(
                "account provider resolver received a non-account job"
            )
        from clue_api.account_research_fleet_composition import DbAccountResearchJobContextResolver

        account_run_id = await DbAccountResearchJobContextResolver(
            conn_factory=self._conn_factory
        ).account_run_id(job)
        context = await self._contexts.load(job, account_run_id=account_run_id)
        authorization = job.authorization
        exa_fields = tuple(
            item.field_key
            for item in authorization.effective_field_source_authority
            if EXA_SOURCE_KEY in item.source_keys
        )
        structured_fields = tuple(
            item.field_key
            for item in authorization.effective_field_source_authority
            if any(
                source in {ORGANIZATIONS_SOURCE_KEY, JOBS_SOURCE_KEY, TECH_STACK_SOURCE_KEY}
                for source in item.source_keys
            )
        )
        concurrency = self._settings.entity_research_provider_concurrency_limit
        floor = self._settings.entity_research_unpriced_reservation_cents
        exa_config = _exa_config(self._settings)
        # The atomic reservation must cover the plan the action will actually compile, so it is
        # sized by the *same* packer. The old `ceil(fields / max-aliases)` estimate only knew the
        # alias cap; object-valued rows split earlier on the nested-property cap, so a real
        # comprehensive account compiled four bundles against a two-bundle reservation and the
        # settlement guard suspended every job.
        exa_bundles = await self._exa_bundle_count(job, exa_fields, config=exa_config)
        # Zero bundles means the job selected no Exa field at all, so no Exa operation can ever be
        # created: the slot below composes ``_UnavailableProviderAction``, which refuses before any
        # reservation is consumed. It still takes the unpriced floor because a binding must carry a
        # positive worst-case reservation.
        exa_reserve = await self._source_reservation(
            EXA_SOURCE_KEY, calls=max(1, exa_bundles), floor=floor
        )
        if exa_fields:
            if (
                not self._settings.exa_account_deep_acquisition_enabled
                or self._secrets.exa_api_key is None
            ):
                raise EntityResearchProductionCompositionError(
                    "selected Exa account fields require enabled acquisition and credentials"
                )
            exa_action: EntityResearchProviderAction = ExaAccountSemanticResearchAction(
                workspace_id=job.workspace_id,
                project_id=authorization.project_id,
                project_run_id=ProjectRunId(authorization.project_run_id),
                account_id=EntityId(authorization.subject_entity_id),
                icp_key=context.directive.icp_key,
                icp_version=context.directive.icp_version,
                research_directive=context.directive.pin,
                acquisition=ExaDeepAcquisitionCoordinator(
                    transport=ExaDeepHttpAcquisitionTransport(
                        config=exa_config, secrets=self._secrets
                    ),
                    storage=self._storage,
                    conn_factory=self._conn_factory,
                    enforce_budget=self._settings.budget_controls_enabled,
                ),
                snapshots=ExaDeepSnapshotResolverProvider(
                    storage=self._storage,
                    conn_factory=self._conn_factory,
                ),
                projector=ExaEntityResearchProjectionBuilder(
                    storage=self._storage,
                    conn_factory=self._conn_factory,
                ),
                conn_factory=self._conn_factory,
                observation_window=f"entity-research-account:{job.job_id}",
                research_intent="\n".join(authorization.effective_research_questions),
                freshness_policy_ref=context.directive.effort_policy.freshness_policy_ref,
                freshness_seconds=86_400,
                entity_research_job_id=job.job_id,
                cost_cents_reserved_per_bundle=exa_reserve / exa_bundles,
                config=exa_config,
            )
        else:
            exa_action = _UnavailableProviderAction(
                "the exact account job selected no Exa-applicable field"
            )

        sumble_reserve = max(
            floor,
            Decimal(self._settings.entity_research_sumble_provider_credit_cap)
            * Decimal(self._settings.sumble_cents_per_credit),
        )
        if structured_fields:
            starter = build_production_sumble_account_gap_starter(
                self._settings,
                secrets=self._secrets,
                storage=self._storage,
                conn_factory=self._conn_factory,
            )
            if starter is None:
                raise EntityResearchProductionCompositionError(
                    "selected Sumble account fields require enabled account enrichment"
                )
            provider_cap = self._settings.entity_research_sumble_provider_credit_cap
            sumble_action: EntityResearchProviderAction = SumbleAccountSemanticEnrichmentAction(
                starter=starter,
                storage=self._storage,
                conn_factory=self._conn_factory,
                workspace_id=job.workspace_id,
                project_id=authorization.project_id,
                project_run_id=ProjectRunId(authorization.project_run_id),
                account_id=EntityId(authorization.subject_entity_id),
                field_expected_value_credits={
                    field_key: Decimal(provider_cap) for field_key in structured_fields
                },
                provider_credit_cap=provider_cap,
                allow_unbounded_tech="core.primary_tech_stack" in structured_fields,
                entity_research_job_id=job.job_id,
            )
        else:
            sumble_action = _UnavailableProviderAction(
                "the exact account job selected no Sumble structured field"
            )

        # Committee configuration is required only by a job that actually selected committee
        # discovery. Account-only research (a confirmed directive with no committee source) used
        # to be uncomposable whenever no-reveal Sumble committee acquisition was off; the tool now
        # refuses the same way every other unselected provider does — governed, not fatal.
        committee_requested = bool(authorization.selection.committee_source_keys)
        committee_action: EntityResearchProviderAction
        if not committee_requested:
            committee_action = _UnavailableProviderAction(
                "this run's confirmed directive selected no committee discovery"
            )
        elif (
            not self._settings.sumble_committee_acquisition_enabled
            or self._secrets.sumble_api_key is None
        ):
            raise EntityResearchProductionCompositionError(
                "committee-selecting account research requires enabled no-reveal "
                "Sumble committee acquisition"
            )
        else:
            committee_action = SumbleCommitteeSemanticResearchAction(
                inputs=_CommitteeInputs(
                    resolver=self._committee_inputs,
                    job=job,
                    account_run_id=account_run_id,
                    tier=context.tier,
                ),
                eligibility=self._committee_eligibility,
                coordinator=SumbleCommitteeAcquisitionCoordinator(
                    transport=SumbleV9CommitteeClient(api_key=self._secrets.sumble_api_key),
                    storage=self._storage,
                    cents_per_credit=self._settings.sumble_cents_per_credit,
                    conn_factory=self._conn_factory,
                    poll_after_seconds=self._settings.sumble_committee_poll_after_s,
                    enforce_budget=self._settings.budget_controls_enabled,
                ),
                storage=self._storage,
                conn_factory=self._conn_factory,
                gateway=self._gateway,
                role_model=self._gateway_config.synthesis_model,
            )
        committee_reserve = max(
            floor,
            Decimal(context.directive.committee_plan.candidate_cap * 2)
            * Decimal(self._settings.sumble_cents_per_credit),
        )
        return {
            "research_account_deep": _binding(
                exa_action,
                family="exa_search",
                reserve=exa_reserve,
                concurrency=concurrency,
            ),
            "enrich_account": _binding(
                sumble_action,
                family="sumble_account",
                reserve=sumble_reserve,
                concurrency=concurrency,
            ),
            "discover_buying_committee": _binding(
                committee_action,
                family="sumble_committee",
                reserve=committee_reserve,
                concurrency=concurrency,
            ),
        }

    async def _exa_bundle_count(
        self,
        job: EntityResearchJobRow,
        exa_fields: Sequence[str],
        *,
        config: ExaDeepConfig,
    ) -> int:
        """How many Exa calls this job's admitted fields really compile into.

        Reads the same packer the action will run, over the *whole* admitted Exa set. A tool call
        may request a subset, and the greedy packer can only ever produce fewer bundles from
        fewer fields, so this is the exact worst case the atomic reservation has to cover.
        """

        if not exa_fields:
            return 0
        authorization = job.authorization
        async with self._conn_factory() as conn:
            account = await get_account(conn, EntityId(authorization.subject_entity_id))
            if account is None or account.workspace_id != job.workspace_id:
                raise EntityResearchProductionCompositionError(
                    "Exa account reservation cannot resolve its exact canonical account"
                )
            specs: list[ExaDeepFieldSpec] = []
            for field_key in exa_fields:
                effective = await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(job.workspace_id),
                    field_key=field_key,
                )
                if effective is None or effective.value_schema is None:
                    raise EntityResearchProductionCompositionError(
                        f"Exa field {field_key!r} lacks an effective value schema"
                    )
                specs.append(
                    ExaDeepFieldSpec(
                        field_key=effective.field_def.field_key,
                        value_schema=cast(dict[str, JsonValue], effective.value_schema),
                    )
                )
        questions = authorization.effective_research_questions
        return len(
            pack_exa_deep_field_bundles(
                account,
                specs,
                # Mirrors ``ExaAccountSemanticResearchAction.execute`` exactly; a different
                # planning sentence could compile a different request and desize the reservation.
                research_intent="\n".join(questions) or DEFAULT_ACCOUNT_RESEARCH_INTENT,
                additional_queries=questions,
                config=config,
            )
        )

    async def _source_reservation(
        self,
        source_key: str,
        *,
        calls: int,
        floor: Decimal,
    ) -> Decimal:
        async with self._conn_factory() as conn:
            source = await get_source(conn, source_key)
        if source is None or not source.active:
            raise EntityResearchProductionCompositionError(
                f"active source manifest {source_key!r} is absent"
            )
        return max(floor, Decimal(source.manifest.cost_cents) * calls)


class ProductionContactResearchProviderActions:
    def __init__(
        self,
        *,
        settings: Settings,
        secrets: Secrets,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._storage = storage
        self._conn_factory = conn_factory

    async def build(
        self,
        job: EntityResearchJobRow,
        *,
        intent: ContactResearchIntent,
    ) -> ProviderActionBinding:
        if (
            not self._settings.exa_contact_deep_acquisition_enabled
            or self._secrets.exa_api_key is None
        ):
            raise EntityResearchProductionCompositionError(
                "selected contact Exa research requires enabled acquisition and credentials"
            )
        target = next(
            item
            for item in intent.selection.body.targets
            if item.contact_entity_id == intent.contact_entity_id
        )
        source_fields = tuple(
            field_key
            for item in target.field_source_authority
            if EXA_SOURCE_KEY in item.source_keys
            for field_key in (item.field_key,)
        )
        if not source_fields:
            action: EntityResearchProviderAction = _UnavailableProviderAction(
                "the exact contact intent selected no Exa-applicable field"
            )
        else:
            config = _exa_config(self._settings)
            coordinator = ExaDeepAcquisitionCoordinator(
                transport=ExaDeepHttpAcquisitionTransport(config=config, secrets=self._secrets),
                storage=self._storage,
                conn_factory=self._conn_factory,
                enforce_budget=self._settings.budget_controls_enabled,
            )
            action = ExaContactSemanticResearchAction(
                intent=intent,
                effective_policy=intent.selection.body.policy,
                acquisition=ExaDeepContactAcquisitionService(
                    coordinator=coordinator,
                    conn_factory=self._conn_factory,
                ),
                materializer=ExaDeepContactSnapshotMaterializer(
                    provider=ExaDeepContactSnapshotResolverProvider(
                        storage=self._storage,
                        conn_factory=self._conn_factory,
                    ),
                    conn_factory=self._conn_factory,
                ),
                projector=ExaEntityResearchProjectionBuilder(
                    storage=self._storage,
                    conn_factory=self._conn_factory,
                ),
                run_id=RunId(job.research_run_id),
                observation_window=f"entity-research-contact:{job.job_id}",
                entity_research_job_id=job.job_id,
            )
        async with self._conn_factory() as conn:
            source = await get_source(conn, EXA_SOURCE_KEY)
        if source is None or not source.active:
            raise EntityResearchProductionCompositionError("active Exa source manifest is absent")
        reserve = max(
            self._settings.entity_research_unpriced_reservation_cents,
            Decimal(source.manifest.cost_cents)
            * max(1, ceil(len(source_fields) / EXA_OUTPUT_MAX_FIELDS)),
        )
        return _binding(
            action,
            family="exa_search",
            reserve=reserve,
            concurrency=self._settings.entity_research_provider_concurrency_limit,
        )


class _DisabledContactChannels(ContactChannelActions):
    def admission(self, *, stage: Any) -> None:
        del stage
        return None

    async def reveal(self, **values: Any) -> Any:
        del values
        raise EntityResearchResultIntegrityError(
            "contact channel acquisition is not composed for this deployment"
        )

    async def validate(self, **values: Any) -> Any:
        del values
        raise EntityResearchResultIntegrityError(
            "contact channel validation is not composed for this deployment"
        )


class ProductionContactResearchChannelActions:
    def __init__(
        self,
        *,
        settings: Settings,
        coordinator: ExaContactChannelCoordinator | None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        if settings.contact_channel_enrichment_enabled and coordinator is None:
            raise EntityResearchProductionCompositionError(
                "channel enrichment is enabled without an independent validator-backed coordinator"
            )
        self._settings = settings
        self._coordinator = coordinator
        self._conn_factory = conn_factory

    async def build(
        self,
        job: EntityResearchJobRow,
        *,
        intent: ContactResearchIntent,
        policy: ContactResearchPolicyPin,
        state: ContactResearchStateStore,
    ) -> ContactChannelActions:
        target = next(
            item
            for item in intent.selection.body.targets
            if item.contact_entity_id == intent.contact_entity_id
        )
        if (
            not any(item.allowed for item in (target.email, target.phone))
            or not self._settings.contact_channel_enrichment_enabled
        ):
            return _DisabledContactChannels()
        assert self._coordinator is not None
        return GovernedContactChannelActions(
            intent=intent,
            effective_policy=policy,
            coordinator=self._coordinator,
            state=state,
            observation_window=f"entity-research-contact-channel:{job.job_id}",
            entity_research_job_id=job.job_id,
            conn_factory=self._conn_factory,
            provider_concurrency_limit=(self._settings.entity_research_provider_concurrency_limit),
            enforce_budget=self._settings.budget_controls_enabled,
        )


def _exa_config(settings: Settings) -> ExaDeepConfig:
    return ExaDeepConfig(
        search_type=settings.exa_account_deep_search_type,
        num_results=settings.exa_account_deep_max_results,
        max_additional_queries=settings.exa_account_deep_max_additional_queries,
    )


def build_production_entity_research_fleet(
    *,
    settings: Settings,
    secrets: Secrets,
    storage: StorageBackend,
    models: Any,
    gateway: LLMGateway,
    gateway_config: GatewayConfig,
    pre_spend_gate: PreSpendGate,
    channel_coordinator: ExaContactChannelCoordinator | None = None,
    conn_factory: ConnFactory = transaction,
    prose_step: ProseSynthesisStep | None = None,
) -> EntityResearchFleetComposition | None:
    """Promote one shared entity fleet only under its independent R10 deployment switch."""

    if not settings.entity_research_runtime_enabled:
        return None
    accounts = ProductionAccountResearchProviderActions(
        settings=settings,
        secrets=secrets,
        storage=storage,
        pre_spend_gate=pre_spend_gate,
        gateway=gateway,
        gateway_config=gateway_config,
        conn_factory=conn_factory,
    )
    contacts = ProductionContactResearchProviderActions(
        settings=settings,
        secrets=secrets,
        storage=storage,
        conn_factory=conn_factory,
    )
    channels = ProductionContactResearchChannelActions(
        settings=settings,
        coordinator=channel_coordinator,
        conn_factory=conn_factory,
    )
    contact_providers = RunScopedContactResearchProviderActions(
        deep=contacts.build,
        enrichment=contacts.build,
        conn_factory=conn_factory,
    )
    return build_entity_research_fleet_composition(
        storage=storage,
        models=models,
        account_provider_actions=accounts,
        contact_provider_actions=contact_providers,
        contact_channel_actions=RunScopedContactResearchChannelActions(factory=channels.build),
        model_policy=ModelPolicy(
            model_id=gateway_config.synthesis_model,
            timeout_s=gateway_config.timeout_s,
            max_retries=gateway_config.max_retries,
            max_output_tokens=16_384,
            temperature=0,
        ),
        conn_factory=conn_factory,
        # Lane E E1: the fleet process is the only one with a real gateway, so it is the only
        # process that composes a step at all.
        prose_step=prose_step,
        # FI pilot budget-controls: the one place the deployment switch enters the fleets.
        enforce_budget=settings.budget_controls_enabled,
    )


__all__ = [
    "EntityResearchProductionCompositionError",
    "ProductionAccountResearchProviderActions",
    "ProductionContactResearchChannelActions",
    "ProductionContactResearchProviderActions",
    "build_production_entity_research_fleet",
]
