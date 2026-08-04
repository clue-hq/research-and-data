"""Production Exa account-profile acquisition + snapshot binding (M8B O2)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from clue_api.account_research_wiring import (
    AccountResolverBindingAvailability,
    AccountResolverBindings,
)
from clue_api.deep.orchestrator import deep_account_run_id
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepAcquisitionOutcome,
    ExaDeepHttpAcquisitionTransport,
    compile_exa_deep_acquisition_plan,
)
from clue_api.exa_deep_materialization import ExaDeepSnapshotResolverProvider
from clue_config import Secrets, Settings
from clue_core import (
    EntityId,
    EntityScope,
    EntityType,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ProjectRunId,
    ResearchDirectivePin,
    ResearchMode,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import FieldRegistryScope, get_effective_field
from clue_research.directives import effective_account_research_directive
from clue_research.icp import get_icp_version
from clue_research.identity import get_account
from clue_research.resolvers.exa import SOURCE_KEY, ExaDeepConfig, ExaDeepFieldSpec
from clue_research.sources import get_source, plan_sources
from clue_storage import StorageBackend


class ExaDeepAccountResolverProvider:
    """Acquire only missing authorized snapshots, then expose the offline E2 resolver."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: StorageBackend,
        pre_spend_gate: PreSpendGate,
        coordinator: ExaDeepAcquisitionCoordinator,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._gate = pre_spend_gate
        self._coordinator = coordinator
        self._conn_factory = conn_factory
        self._snapshots = ExaDeepSnapshotResolverProvider(
            storage=storage,
            conn_factory=conn_factory,
        )

    async def resolver_bindings(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        research_directive: ResearchDirectivePin | None,
    ) -> AccountResolverBindings:
        materialized = await self._snapshots.resolver_bindings(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_entity_id=account_entity_id,
            research_directive=research_directive,
        )
        # With acquisition disabled this remains a strictly snapshot-backed provider.  When it is
        # enabled, however, one ready snapshot is not proof that a multi-bundle plan is complete:
        # the process may have crashed after persisting bundle 0 and before reserving bundle 1.
        # Recompile the exact governed plan and reconcile every deterministic bundle through E1;
        # already-ready bundles replay without HTTP or spend.
        if not self._settings.exa_account_deep_acquisition_enabled:
            return materialized
        if materialized.availability in {
            AccountResolverBindingAvailability.NOT_APPLICABLE,
            AccountResolverBindingAvailability.WAITING_EXTERNAL,
            AccountResolverBindingAvailability.FAILED_EXTERNAL,
        }:
            return materialized
        if research_directive is None:
            return AccountResolverBindings(
                availability=AccountResolverBindingAvailability.REQUIRED_MISSING,
                bindings={},
                reason_code="exa_deep_confirmed_directive_pin_required",
            )

        async with self._conn_factory() as conn:
            account = await get_account(conn, account_entity_id)
            if account is None or account.workspace_id != workspace_id:
                return AccountResolverBindings(
                    availability=AccountResolverBindingAvailability.REQUIRED_MISSING,
                    bindings={},
                    reason_code="exa_deep_account_not_resolved_in_workspace",
                )
            effective = await effective_account_research_directive(
                conn,
                workspace_id=workspace_id,
                directive_id=research_directive.directive_id,
                account_id=account_entity_id,
                expected_pin=research_directive,
            )
            if SOURCE_KEY not in effective.source_policy.allowed_source_keys:
                return materialized
            source = await get_source(conn, SOURCE_KEY)
            if source is None or not source.active:
                return AccountResolverBindings(
                    availability=AccountResolverBindingAvailability.REQUIRED_MISSING,
                    bindings={},
                    reason_code="exa_deep_source_manifest_unavailable",
                )
            icp = await get_icp_version(
                conn,
                workspace_id,
                effective.icp_key,
                effective.icp_version,
            )
            if icp is None:
                return AccountResolverBindings(
                    availability=AccountResolverBindingAvailability.REQUIRED_MISSING,
                    bindings={},
                    reason_code="exa_deep_pinned_icp_unavailable",
                )

            fields: list[ExaDeepFieldSpec] = []
            freshness_seconds: list[int] = []
            gate_rejections: list[str] = []
            for field_key in effective.field_keys:
                planned = await plan_sources(
                    conn,
                    spec=icp,
                    entity=account.as_entity(),
                    field=str(field_key),
                    mode=ResearchMode.ACCOUNT_PROFILING,
                    entity_tier=effective.effort_policy.tier,
                    entity_scope=EntityScope.ACCOUNT,
                    budget_envelope=effective.effort_policy.budget_cap_cents,
                )
                source_plan = planned.effective_source_plan
                if source_plan is None:
                    return AccountResolverBindings(
                        availability=AccountResolverBindingAvailability.REQUIRED_MISSING,
                        bindings={},
                        reason_code="exa_deep_effective_source_plan_missing",
                    )
                authorization = source_plan.authorization_for(SOURCE_KEY)
                selected_source_keys = set(planned.tier_plan())
                if authorization is None or SOURCE_KEY not in selected_source_keys:
                    continue
                definition = await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(workspace_id),
                    field_key=str(field_key),
                )
                if definition is None or definition.value_schema is None:
                    return AccountResolverBindings(
                        availability=AccountResolverBindingAvailability.REQUIRED_MISSING,
                        bindings={},
                        reason_code="exa_deep_effective_field_schema_missing",
                    )
                decision = await self._gate.check(
                    PreSpendRequest(
                        entity_id=account_entity_id,
                        entity_type=EntityType.ACCOUNT,
                        field_key=field_key,
                        source_tier=authorization.source_tier,
                        source_key=SOURCE_KEY,
                        effective_source_plan=source_plan,
                        run_id=deep_account_run_id(project_run_id, account_entity_id),
                    )
                )
                if decision.verdict is not PreSpendVerdict.PASS:
                    gate_rejections.extend(f"{field_key}:{reason}" for reason in decision.reasons)
                    continue
                fields.append(
                    ExaDeepFieldSpec(field_key=field_key, value_schema=definition.value_schema)
                )
                ttl = definition.field_def.freshness_ttl
                if ttl is not None:
                    freshness_seconds.append(max(1, int(ttl.total_seconds())))

        if not fields:
            return AccountResolverBindings(
                availability=AccountResolverBindingAvailability.NOT_APPLICABLE,
                bindings=materialized.bindings,
                reason_code="exa_deep_no_effective_authorized_fields",
                audit_refs=tuple(gate_rejections),
            )

        questions = tuple(
            item.text
            for item in sorted(
                effective.questions,
                key=lambda item: (item.priority, item.question_id),
            )
        )
        config = ExaDeepConfig(
            search_type=self._settings.exa_account_deep_search_type,
            num_results=self._settings.exa_account_deep_max_results,
            max_additional_queries=self._settings.exa_account_deep_max_additional_queries,
        )
        acquisition_plan = compile_exa_deep_acquisition_plan(
            workspace_id=workspace_id,
            project_id=effective.project_id,
            project_run_id=project_run_id,
            account=account,
            icp_key=effective.icp_key,
            icp_version=effective.icp_version,
            research_directive=research_directive,
            fields=fields,
            research_intent=(
                "Target-lock research to this canonical account and answer only the admitted "
                "structured fields with inspectable evidence."
            ),
            additional_queries=questions[: config.max_additional_queries],
            observation_window=f"project-run:{project_run_id}:account:{account_entity_id}",
            freshness_policy_ref=effective.effort_policy.freshness_policy_ref,
            freshness_seconds=min(freshness_seconds) if freshness_seconds else 86_400,
            cost_cents_reserved_per_bundle=Decimal(source.cost_cents),
            config=config,
        )
        operation_refs: list[str] = []
        for bundle in acquisition_plan.bundles:
            acquired = await self._coordinator.acquire(bundle)
            operation_refs.append(str(acquired.operation.operation_id))
            if acquired.outcome is ExaDeepAcquisitionOutcome.JOINED_IN_FLIGHT:
                return AccountResolverBindings(
                    availability=AccountResolverBindingAvailability.WAITING_EXTERNAL,
                    bindings={},
                    reason_code="exa_deep_acquisition_in_progress",
                    operation_ref=str(acquired.operation.operation_id),
                    retry_after=acquired.retry_after or datetime.now(UTC) + timedelta(seconds=30),
                    audit_refs=tuple(operation_refs),
                )
            if acquired.outcome in {
                ExaDeepAcquisitionOutcome.FAILED_TERMINAL,
                ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
            }:
                return AccountResolverBindings(
                    availability=AccountResolverBindingAvailability.FAILED_EXTERNAL,
                    bindings={},
                    reason_code=f"exa_deep_{acquired.outcome.value}",
                    operation_ref=str(acquired.operation.operation_id),
                    audit_refs=tuple(operation_refs),
                )

        resolved = await self._snapshots.resolver_bindings(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_entity_id=account_entity_id,
            research_directive=research_directive,
        )
        return replace(resolved, audit_refs=tuple(operation_refs))


def build_production_exa_deep_resolver_provider(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
    pre_spend_gate: PreSpendGate,
    conn_factory: ConnFactory = transaction,
) -> ExaDeepAccountResolverProvider:
    config = ExaDeepConfig(
        search_type=settings.exa_account_deep_search_type,
        num_results=settings.exa_account_deep_max_results,
        max_additional_queries=settings.exa_account_deep_max_additional_queries,
    )
    coordinator = ExaDeepAcquisitionCoordinator(
        transport=ExaDeepHttpAcquisitionTransport(config=config, secrets=secrets),
        storage=storage,
        conn_factory=conn_factory,
    )
    return ExaDeepAccountResolverProvider(
        settings=settings,
        storage=storage,
        pre_spend_gate=pre_spend_gate,
        coordinator=coordinator,
        conn_factory=conn_factory,
    )


__all__ = ["ExaDeepAccountResolverProvider", "build_production_exa_deep_resolver_provider"]
