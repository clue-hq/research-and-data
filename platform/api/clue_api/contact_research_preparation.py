"""Provider-neutral selected-contact preparation and batch composition (M8C C6)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_api.contact_channel_enrichment import (
    ContactChannelEligibilityError,
    ContactChannelEnrichmentOutcome,
    ExaContactChannelCoordinator,
)
from clue_api.contact_research_selection import ContactResearchSelectionMaterializer
from clue_api.exa_contact_acquisition import ExaDeepContactAcquisitionService
from clue_api.exa_contact_materialization import (
    ExaDeepContactSnapshotMaterializer,
    ExaDeepContactSnapshotResolverProvider,
)
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepAcquisitionOutcome,
    ExaDeepHttpAcquisitionTransport,
)
from clue_config import OverlayStore, Secrets, Settings
from clue_core import (
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    Claim,
    ClaimId,
    ContactChannel,
    ContactChannelValidator,
    ContactPreparationStatus,
    ContactResearchIntent,
    ContactResearchPolicyPin,
    ContactResearchPreparation,
    ContactResearchSelection,
    EntityId,
    FieldKey,
    PreSpendGate,
    ProjectRunId,
    RunId,
    UseDecision,
)
from clue_db import ConnFactory, transaction
from clue_research.adapters.exa_websets import ExaWebsetsImportTransport
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.compliance import UseGateImpl, load_workspace_policy
from clue_research.durable import (
    ContactChannelBudgetExceeded,
    ProjectRunStatus,
    contact_research_selection_cancellation,
    get_project_run,
)
from clue_research.resolvers.exa import SOURCE_KEY as EXA_DEEP_SOURCE_KEY
from clue_research.resolvers.exa import ExaDeepConfig
from clue_storage import StorageBackend


class ContactResearchPreparationError(RuntimeError):
    pass


class _WorkspaceContactChannelUseGate:
    """Resolve the tenant policy for each claim before the production C5 use decision."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def evaluate(self, claim: Claim) -> UseDecision:
        if claim.workspace_id is None:
            raise ContactResearchPreparationError(
                "a production contact-channel claim requires workspace authority"
            )
        async with self._conn_factory() as conn:
            policy = await load_workspace_policy(conn, workspace_id=claim.workspace_id)
        return await UseGateImpl(
            claim.workspace_id,
            policy=policy,
            conn_factory=self._conn_factory,
        ).evaluate(claim)


class ContactPreparationAdapterResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    preparation: ContactResearchPreparation
    claim_refs: tuple[ClaimId, ...] = ()


@runtime_checkable
class ContactPreparationAdapter(Protocol):
    """One registered source-family implementation; never visible to the orchestrator."""

    def claimed_source_keys(self, intent: ContactResearchIntent) -> frozenset[str]: ...

    async def prepare(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        run_id: RunId,
    ) -> ContactPreparationAdapterResult: ...


class PreparedContactTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    field_keys: tuple[FieldKey, ...]
    preparation: ContactResearchPreparation
    claim_refs: tuple[ClaimId, ...] = ()


class PreparedContactResearchBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    selection: ContactResearchSelection | None = None
    preparation: ContactResearchPreparation
    targets: tuple[PreparedContactTarget, ...] = ()


@runtime_checkable
class ContactStagePreparer(Protocol):
    """The sole post-committee seam consumed by ``AccountDeepOrchestrator``."""

    async def prepare(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        account_entity_id: EntityId,
        contact_entity_ids: Sequence[EntityId],
        committee_claim_ids: Sequence[ClaimId],
    ) -> PreparedContactResearchBatch: ...


class ExistingCommitteeContactAdapter:
    """Reuse Sumble-backed professional claims already materialized by committee discovery."""

    _SOURCES = frozenset({"sumble_people", "sumble_teams"})

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    def claimed_source_keys(self, intent: ContactResearchIntent) -> frozenset[str]:
        return self._SOURCES.intersection(intent.source_plan)

    async def prepare(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        run_id: RunId,
    ) -> ContactPreparationAdapterResult:
        del effective_policy
        professional = tuple(
            str(field_key)
            for field_key in intent.field_keys
            if str(field_key) in CONTACT_PROFESSIONAL_FIELD_KEYS
        )
        if not professional:
            raise ContactResearchPreparationError(
                "committee adapter was selected without professional fields"
            )
        target = next(
            item
            for item in intent.selection.body.targets
            if item.contact_entity_id == intent.contact_entity_id
        )
        claim_refs: list[ClaimId] = [
            *target.committee_claim_ids,
            *target.strong_identity_claim_ids,
            *target.effective_association_evidence_claim_ids,
        ]
        immutable_refs: list[str] = [f"claim:{claim_id}" for claim_id in claim_refs]
        async with self._conn_factory() as conn:
            for field_key in professional:
                candidates = await claims_for(
                    conn,
                    intent.contact_entity_id,
                    field_key,
                    scope=WorkspaceScope.for_workspace(intent.workspace_id),
                )
                matching = next(
                    (
                        claim
                        for claim in candidates
                        if claim.run_id == run_id
                        and claim.source_key in self._SOURCES
                        and claim.source_snapshot_ref is not None
                    ),
                    None,
                )
                if matching is None:
                    return ContactPreparationAdapterResult(
                        preparation=ContactResearchPreparation(
                            status=ContactPreparationStatus.NOT_ELIGIBLE,
                            reason_codes=(f"professional_snapshot_missing:{field_key}",),
                        )
                    )
                claim_refs.append(matching.id)
                immutable_refs.extend((f"claim:{matching.id}", str(matching.source_snapshot_ref)))
        return ContactPreparationAdapterResult(
            preparation=ContactResearchPreparation(
                status=ContactPreparationStatus.READY,
                snapshot_reference_ids=tuple(dict.fromkeys(immutable_refs)),
            ),
            claim_refs=tuple(dict.fromkeys(claim_refs)),
        )


class ExaDeepContactPreparationAdapter:
    """Acquire outside transactions, then materialize the exact ready contact snapshot."""

    def __init__(
        self,
        *,
        acquisition: ExaDeepContactAcquisitionService,
        materializer: ExaDeepContactSnapshotMaterializer,
        acquisition_enabled: bool,
        pre_spend_gate: PreSpendGate | None = None,
    ) -> None:
        self._acquisition = acquisition
        self._materializer = materializer
        self._enabled = acquisition_enabled
        self._pre_spend_gate = pre_spend_gate

    def claimed_source_keys(self, intent: ContactResearchIntent) -> frozenset[str]:
        return (
            frozenset({EXA_DEEP_SOURCE_KEY})
            if EXA_DEEP_SOURCE_KEY in intent.source_plan
            else frozenset()
        )

    async def prepare(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        run_id: RunId,
    ) -> ContactPreparationAdapterResult:
        if not self._enabled:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.NOT_ELIGIBLE,
                    reason_codes=("exa_contact_acquisition_disabled",),
                )
            )
        batch = await self._acquisition.acquire_intent(
            intent=intent,
            effective_policy=effective_policy,
            observation_window=(
                f"project-run:{intent.project_run_id}:contact:{intent.contact_entity_id}:"
                f"selection:{intent.selection_sha256}"
            ),
        )
        operation_refs = tuple(str(result.operation.operation_id) for result in batch.results)
        waiting = tuple(
            result
            for result in batch.results
            if result.outcome is ExaDeepAcquisitionOutcome.JOINED_IN_FLIGHT
        )
        if waiting:
            wake = min(
                result.retry_after or datetime.now(UTC) + timedelta(seconds=30)
                for result in waiting
            )
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.WAITING_EXTERNAL,
                    operation_reference_ids=operation_refs,
                    next_wake_at=wake,
                )
            )
        failed = tuple(
            result
            for result in batch.results
            if result.outcome
            in {
                ExaDeepAcquisitionOutcome.FAILED_TERMINAL,
                ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
            }
        )
        if failed:
            budget = any(result.operation.failure_code == "budget" for result in failed)
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=(
                        ContactPreparationStatus.BUDGET_PAUSED
                        if budget
                        else ContactPreparationStatus.FAILED
                    ),
                    operation_reference_ids=operation_refs,
                    reason_codes=tuple(
                        dict.fromkeys(
                            result.operation.failure_code or result.outcome.value
                            for result in failed
                        )
                    ),
                )
            )
        materialized = await self._materializer.materialize(
            intent=intent,
            effective_policy=effective_policy,
            run_id=run_id,
            pre_spend_gate=self._pre_spend_gate,
        )
        claims = tuple(
            dict.fromkeys(
                claim_id for field in materialized.fields for claim_id in field.claim_refs
            )
        )
        return ContactPreparationAdapterResult(
            preparation=ContactResearchPreparation(
                status=ContactPreparationStatus.READY,
                snapshot_reference_ids=materialized.snapshot_reference_ids,
                operation_reference_ids=materialized.operation_reference_ids,
                spend_settlement_reference_ids=tuple(
                    f"external-research-operation:{operation_id}"
                    for operation_id in materialized.operation_reference_ids
                ),
            ),
            claim_refs=claims,
        )


class ContactChannelPreparationAdapter:
    """Drive only explicitly selected channels through the accepted C5 coordinator."""

    def __init__(self, *, coordinator: ExaContactChannelCoordinator) -> None:
        self._coordinator = coordinator

    def claimed_source_keys(self, intent: ContactResearchIntent) -> frozenset[str]:
        target = next(
            item
            for item in intent.selection.body.targets
            if item.contact_entity_id == intent.contact_entity_id
        )
        return frozenset(
            source
            for authorization in (target.email, target.phone)
            if authorization.allowed
            for source in (
                *authorization.provider_source_keys,
                *authorization.validation_source_keys,
            )
        )

    async def prepare(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        run_id: RunId,
    ) -> ContactPreparationAdapterResult:
        del run_id
        target = next(
            item
            for item in intent.selection.body.targets
            if item.contact_entity_id == intent.contact_entity_id
        )
        results = []
        for channel, authorization in (
            (ContactChannel.EMAIL, target.email),
            (ContactChannel.PHONE, target.phone),
        ):
            if not authorization.allowed:
                continue
            try:
                result = await self._coordinator.start(
                    intent=intent,
                    effective_policy=effective_policy,
                    channel=channel,
                    observation_window=(
                        f"project-run:{intent.project_run_id}:contact:{intent.contact_entity_id}:"
                        f"channel:{channel.value}:selection:{intent.selection_sha256}"
                    ),
                )
            except ContactChannelBudgetExceeded:
                return ContactPreparationAdapterResult(
                    preparation=ContactResearchPreparation(
                        status=ContactPreparationStatus.BUDGET_PAUSED,
                        reason_codes=(f"{channel.value}_channel_budget_paused",),
                    )
                )
            except ContactChannelEligibilityError as exc:
                return ContactPreparationAdapterResult(
                    preparation=ContactResearchPreparation(
                        status=ContactPreparationStatus.NOT_ELIGIBLE,
                        reason_codes=(f"{channel.value}_channel_ineligible:{exc}",),
                    )
                )
            if (
                result.outcome
                in {
                    ContactChannelEnrichmentOutcome.WAITING_EXTERNAL,
                    ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT,
                }
                and result.operation.next_poll_at is not None
                and result.operation.next_poll_at <= datetime.now(UTC)
            ):
                result = await self._coordinator.drive_once(
                    workspace_id=intent.workspace_id,
                    operation_id=result.operation.operation_id,
                    effective_policy=effective_policy,
                )
            results.append(result)
        operations = tuple(
            f"contact-channel-operation:{result.operation.operation_id}" for result in results
        )
        waiting = tuple(
            result
            for result in results
            if result.outcome
            in {
                ContactChannelEnrichmentOutcome.CREATED,
                ContactChannelEnrichmentOutcome.WAITING_EXTERNAL,
                ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT,
                ContactChannelEnrichmentOutcome.FAILED_RETRYABLE,
            }
        )
        if waiting:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.WAITING_EXTERNAL,
                    operation_reference_ids=operations,
                    next_wake_at=min(
                        result.operation.next_poll_at or datetime.now(UTC) + timedelta(seconds=30)
                        for result in waiting
                    ),
                )
            )
        failed = tuple(
            result
            for result in results
            if result.outcome
            in {
                ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
            }
        )
        if failed:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.FAILED,
                    operation_reference_ids=operations,
                    reason_codes=tuple(
                        dict.fromkeys(
                            result.operation.failure_code or result.outcome.value
                            for result in failed
                        )
                    ),
                )
            )
        claim_refs = tuple(
            result.operation.observed_claim_id
            for result in results
            if result.operation.observed_claim_id is not None
        )
        return ContactPreparationAdapterResult(
            preparation=ContactResearchPreparation(
                status=ContactPreparationStatus.READY,
                snapshot_reference_ids=operations,
                operation_reference_ids=operations,
                spend_settlement_reference_ids=tuple(
                    f"contact-channel-settlement:{result.operation.operation_id}"
                    for result in results
                ),
            ),
            claim_refs=claim_refs,
        )


class RegisteredContactResearchPreparer:
    """Dispatch one intent only through adapters that explicitly claim its source plan."""

    def __init__(
        self,
        *,
        adapters: Sequence[ContactPreparationAdapter],
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._adapters = tuple(adapters)
        self._conn_factory = conn_factory

    async def prepare(
        self,
        *,
        intent: ContactResearchIntent,
        run_id: RunId,
    ) -> ContactPreparationAdapterResult:
        policy = intent.selection.body.policy
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, intent.project_run_id)
            cancellation = await contact_research_selection_cancellation(
                conn,
                workspace_id=intent.workspace_id,
                selection_id=intent.selection_id,
            )
        if cancellation is not None:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.NOT_ELIGIBLE,
                    reason_codes=(f"selection_cancelled:{cancellation.reason_code}",),
                )
            )
        if run is None or run.workspace_id != intent.workspace_id:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.NOT_ELIGIBLE,
                    reason_codes=("project_run_not_found",),
                )
            )
        if run.status is ProjectRunStatus.PAUSED:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.BUDGET_PAUSED,
                    reason_codes=("project_run_paused",),
                )
            )
        if run.status is not ProjectRunStatus.ACTIVE:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.NOT_ELIGIBLE,
                    reason_codes=(f"project_run_{run.status.value}",),
                )
            )
        chosen: list[tuple[ContactPreparationAdapter, frozenset[str]]] = []
        claimed: set[str] = set()
        for adapter in self._adapters:
            keys = adapter.claimed_source_keys(intent)
            if not keys:
                continue
            overlap = claimed.intersection(keys)
            if overlap:
                raise ContactResearchPreparationError(
                    f"contact preparation source registered twice: {sorted(overlap)!r}"
                )
            claimed.update(keys)
            chosen.append((adapter, keys))
        missing = set(intent.source_plan) - claimed
        if missing:
            return ContactPreparationAdapterResult(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.NOT_ELIGIBLE,
                    reason_codes=(f"contact_adapters_unregistered:{','.join(sorted(missing))}",),
                )
            )
        results: list[ContactPreparationAdapterResult] = []
        for adapter, _keys in chosen:
            # Recheck durable cancellation before every independently chargeable adapter.
            async with self._conn_factory() as conn:
                cancellation = await contact_research_selection_cancellation(
                    conn,
                    workspace_id=intent.workspace_id,
                    selection_id=intent.selection_id,
                )
            if cancellation is not None:
                return ContactPreparationAdapterResult(
                    preparation=ContactResearchPreparation(
                        status=ContactPreparationStatus.NOT_ELIGIBLE,
                        reason_codes=(f"selection_cancelled:{cancellation.reason_code}",),
                    )
                )
            result = await adapter.prepare(
                intent=intent,
                effective_policy=policy,
                run_id=run_id,
            )
            results.append(result)
            # The source plan is ordered authority, not a bag of independent calls. Do not start
            # a later (possibly paid) adapter until every earlier adapter is durably READY. A
            # resumed attempt replays the ready predecessor from its snapshot and then advances.
            if result.preparation.status is not ContactPreparationStatus.READY:
                break
        return _aggregate_adapter_results(results)


def _aggregate_adapter_results(
    results: Sequence[ContactPreparationAdapterResult],
) -> ContactPreparationAdapterResult:
    if not results:
        return ContactPreparationAdapterResult(
            preparation=ContactResearchPreparation(
                status=ContactPreparationStatus.NOT_ELIGIBLE,
                reason_codes=("contact_intent_has_no_registered_work",),
            )
        )
    preparations = tuple(result.preparation for result in results)
    statuses = {item.status for item in preparations}
    snapshots = tuple(
        dict.fromkeys(ref for item in preparations for ref in item.snapshot_reference_ids)
    )
    operations = tuple(
        dict.fromkeys(ref for item in preparations for ref in item.operation_reference_ids)
    )
    settlements = tuple(
        dict.fromkeys(ref for item in preparations for ref in item.spend_settlement_reference_ids)
    )
    reasons = tuple(dict.fromkeys(ref for item in preparations for ref in item.reason_codes))
    claims = tuple(dict.fromkeys(claim for result in results for claim in result.claim_refs))
    if ContactPreparationStatus.FAILED in statuses:
        status = ContactPreparationStatus.FAILED
    elif ContactPreparationStatus.BUDGET_PAUSED in statuses:
        status = ContactPreparationStatus.BUDGET_PAUSED
    elif ContactPreparationStatus.NOT_ELIGIBLE in statuses:
        status = ContactPreparationStatus.NOT_ELIGIBLE
    elif ContactPreparationStatus.WAITING_EXTERNAL in statuses:
        status = ContactPreparationStatus.WAITING_EXTERNAL
    else:
        status = ContactPreparationStatus.READY
    return ContactPreparationAdapterResult(
        preparation=ContactResearchPreparation(
            status=status,
            snapshot_reference_ids=snapshots,
            operation_reference_ids=operations,
            reason_codes=(
                reasons
                if reasons
                else (
                    ()
                    if status
                    in {
                        ContactPreparationStatus.READY,
                        ContactPreparationStatus.WAITING_EXTERNAL,
                    }
                    else (status.value,)
                )
            ),
            next_wake_at=(
                min(item.next_wake_at for item in preparations if item.next_wake_at is not None)
                if status is ContactPreparationStatus.WAITING_EXTERNAL
                else None
            ),
            spend_settlement_reference_ids=settlements,
        ),
        claim_refs=claims,
    )


class ContactResearchBatchPreparer:
    """Materialize selection, derive exact intents, and aggregate resumable outcomes."""

    def __init__(
        self,
        *,
        selections: ContactResearchSelectionMaterializer,
        preparer: RegisteredContactResearchPreparer,
    ) -> None:
        self._selections = selections
        self._preparer = preparer

    async def prepare(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        account_entity_id: EntityId,
        contact_entity_ids: Sequence[EntityId],
        committee_claim_ids: Sequence[ClaimId],
    ) -> PreparedContactResearchBatch:
        selection = await self._selections.materialize(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_run_id=account_run_id,
            account_entity_id=account_entity_id,
            contact_entity_ids=contact_entity_ids,
            committee_claim_ids=committee_claim_ids,
        )
        if selection is None:
            return PreparedContactResearchBatch(
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.NOT_ELIGIBLE,
                    reason_codes=("no_selected_contact_research_targets",),
                )
            )
        targets: list[PreparedContactTarget] = []
        for target in selection.body.targets:
            intent = ContactResearchIntent.from_selection(
                selection,
                contact_entity_id=target.contact_entity_id,
            )
            result = await self._preparer.prepare(intent=intent, run_id=account_run_id)
            targets.append(
                PreparedContactTarget(
                    contact_entity_id=target.contact_entity_id,
                    field_keys=target.field_keys,
                    preparation=result.preparation,
                    claim_refs=result.claim_refs,
                )
            )
            if result.preparation.status in {
                ContactPreparationStatus.FAILED,
                ContactPreparationStatus.BUDGET_PAUSED,
                ContactPreparationStatus.NOT_ELIGIBLE,
            }:
                break
        aggregate = _aggregate_adapter_results(
            tuple(
                ContactPreparationAdapterResult(
                    preparation=target.preparation,
                    claim_refs=target.claim_refs,
                )
                for target in targets
            )
        )
        return PreparedContactResearchBatch(
            selection=selection,
            preparation=aggregate.preparation,
            targets=tuple(targets),
        )

    async def prepare_independent(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        account_entity_id: EntityId,
        contact_entity_id: EntityId,
        committee_contact_entity_ids: Sequence[EntityId],
        committee_claim_ids: Sequence[ClaimId],
    ) -> PreparedContactResearchBatch:
        """Run the same governed seam for one already-known selected committee contact."""

        selection = await self._selections.materialize(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_run_id=account_run_id,
            account_entity_id=account_entity_id,
            contact_entity_ids=committee_contact_entity_ids,
            committee_claim_ids=committee_claim_ids,
        )
        if selection is None or contact_entity_id not in {
            target.contact_entity_id for target in selection.body.targets
        }:
            return PreparedContactResearchBatch(
                selection=selection,
                preparation=ContactResearchPreparation(
                    status=ContactPreparationStatus.NOT_ELIGIBLE,
                    reason_codes=("contact_not_selected_for_research",),
                ),
            )
        intent = ContactResearchIntent.from_selection(
            selection,
            contact_entity_id=contact_entity_id,
        )
        result = await self._preparer.prepare(intent=intent, run_id=account_run_id)
        target = next(
            item for item in selection.body.targets if item.contact_entity_id == contact_entity_id
        )
        return PreparedContactResearchBatch(
            selection=selection,
            preparation=result.preparation,
            targets=(
                PreparedContactTarget(
                    contact_entity_id=contact_entity_id,
                    field_keys=target.field_keys,
                    preparation=result.preparation,
                    claim_refs=result.claim_refs,
                ),
            ),
        )


def build_production_contact_channel_coordinator(
    *,
    transport: ExaWebsetsImportTransport,
    validator: ContactChannelValidator,
    storage: StorageBackend,
    pre_spend_gate: PreSpendGate,
    conn_factory: ConnFactory = transaction,
    enforce_budget: bool = True,
) -> ExaContactChannelCoordinator:
    """Compose the real C5 transport with an explicitly deployed independent validator."""

    return ExaContactChannelCoordinator(
        transport=transport,
        validator=validator,
        use_gate=_WorkspaceContactChannelUseGate(conn_factory=conn_factory),
        pre_spend_gate=pre_spend_gate,
        storage=storage,
        conn_factory=conn_factory,
        enforce_budget=enforce_budget,
    )


def build_production_contact_research_preparer(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
    pre_spend_gate: PreSpendGate,
    conn_factory: ConnFactory = transaction,
    config_store: OverlayStore | None = None,
    channel_coordinator: ExaContactChannelCoordinator | None = None,
) -> ContactResearchBatchPreparer:
    """Register C1/C4/C5 adapters behind one C6 seam.

    Exa contact Search is independently default-off. Channel composition fails loudly if its
    deployment switch is enabled without the separately accepted validator-backed coordinator;
    the platform never substitutes a fake validator in production.
    """

    config = ExaDeepConfig(
        search_type=settings.exa_account_deep_search_type,
        num_results=settings.exa_account_deep_max_results,
        max_additional_queries=settings.exa_account_deep_max_additional_queries,
    )
    coordinator = ExaDeepAcquisitionCoordinator(
        transport=ExaDeepHttpAcquisitionTransport(config=config, secrets=secrets),
        storage=storage,
        conn_factory=conn_factory,
        enforce_budget=settings.budget_controls_enabled,
    )
    acquisition = ExaDeepContactAcquisitionService(
        coordinator=coordinator,
        conn_factory=conn_factory,
    )
    materializer = ExaDeepContactSnapshotMaterializer(
        provider=ExaDeepContactSnapshotResolverProvider(
            storage=storage,
            conn_factory=conn_factory,
        ),
        conn_factory=conn_factory,
    )
    adapters: list[ContactPreparationAdapter] = [
        ExistingCommitteeContactAdapter(conn_factory=conn_factory),
        ExaDeepContactPreparationAdapter(
            acquisition=acquisition,
            materializer=materializer,
            acquisition_enabled=settings.exa_contact_deep_acquisition_enabled,
            pre_spend_gate=pre_spend_gate,
        ),
    ]
    if settings.contact_channel_enrichment_enabled:
        if channel_coordinator is None:
            raise RuntimeError(
                "selected-contact channel enrichment is enabled without a concrete "
                "validator-backed coordinator"
            )
        adapters.append(ContactChannelPreparationAdapter(coordinator=channel_coordinator))
    return ContactResearchBatchPreparer(
        selections=ContactResearchSelectionMaterializer(
            conn_factory=conn_factory,
            config_store=config_store,
        ),
        preparer=RegisteredContactResearchPreparer(
            adapters=adapters,
            conn_factory=conn_factory,
        ),
    )


__all__ = [
    "ContactChannelPreparationAdapter",
    "ContactPreparationAdapter",
    "ContactPreparationAdapterResult",
    "ContactResearchBatchPreparer",
    "ContactResearchPreparationError",
    "ContactStagePreparer",
    "ExaDeepContactPreparationAdapter",
    "ExistingCommitteeContactAdapter",
    "PreparedContactResearchBatch",
    "PreparedContactTarget",
    "RegisteredContactResearchPreparer",
    "build_production_contact_channel_coordinator",
    "build_production_contact_research_preparer",
]
