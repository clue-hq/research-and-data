"""Production A2/O2 inputs for bounded Sumble Teams + People acquisition."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader
from clue_api.sumble_committee_acquisition import (
    SUMBLE_COMMITTEE_CONTRACT_VERSION,
    SUMBLE_COMMITTEE_POLICY_VERSION,
    SUMBLE_COMMITTEE_PRICING_VERSION,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_preparation import (
    SumbleCommitteePreparationError,
    SumbleCommitteePreparationInputs,
)
from clue_config import Settings
from clue_core import (
    CommitteeAcquisitionRequest,
    CommitteeExecutionAuthorization,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    RunId,
    UseClass,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.directives import (
    effective_account_research_directive,
    get_research_directive,
)
from clue_research.discovery_scoring.tiering import TIER_FIELD
from clue_research.durable import (
    account_deep_launch_account_pins,
    get_account_deep_launch,
    get_account_run,
    get_project_run,
    latest_succeeded_account_gap_snapshot,
)
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_API_VERSION,
    matched_organization_id,
)
from clue_research.resolvers.sumble.people import SumbleAdvancedQuery, people_search_request
from clue_research.resolvers.sumble.teams import teams_search_request
from clue_storage import StorageBackend, read_verified_artifact


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _provider_filter(functions: tuple[str, ...], levels: tuple[str, ...]) -> str | None:
    clauses: list[str] = []
    if functions:
        clauses.append(f"job_function IN ({_quoted(functions)})")
    if levels:
        clauses.append(f"job_level IN ({_quoted(levels)})")
    return " AND ".join(clauses) or None


class DurableSumbleCommitteeInputResolver:
    """Compile one exact, no-reveal S2 request solely from durable launch/directive state."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._conn_factory = conn_factory

    async def resolve(
        self,
        *,
        account_entity_id: EntityId,
        account_run_id: RunId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        tier: str,
    ) -> SumbleCommitteePreparationInputs:
        reader = DbSealedDiscoveryAccountManifestReader(
            storage=self._storage,
            conn_factory=self._conn_factory,
        )
        async with self._conn_factory() as conn:
            project_run = await get_project_run(conn, project_run_id)
        if project_run is None or project_run.workspace_id != workspace_id:
            raise SumbleCommitteePreparationError("project run is absent or cross-workspace")
        sealed = await reader.read(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            icp_key=project_run.icp_key,
            icp_version=project_run.icp_version,
        )
        if sealed is None or account_entity_id not in set(sealed.account_ids):
            raise SumbleCommitteePreparationError(
                "Sumble committee inputs require exact sealed-batch membership"
            )

        async with self._conn_factory() as conn:
            account_run = await get_account_run(conn, account_run_id)
            if (
                account_run is None
                or account_run.project_run_id != project_run_id
                or account_run.entity_id != account_entity_id
                or account_run.research_directive is None
            ):
                raise SumbleCommitteePreparationError(
                    "Sumble committee inputs require the exact directive-pinned account run"
                )
            pin = account_run.research_directive
            launch = await get_account_deep_launch(
                conn,
                project_run_id,
                workspace_id=workspace_id,
            )
            if launch is None:
                raise SumbleCommitteePreparationError("account-deep launch authorization is absent")
            launch_pins = await account_deep_launch_account_pins(conn, launch)
            if pin not in launch_pins:
                raise SumbleCommitteePreparationError(
                    "account is outside the exact launched directive selection"
                )
            directive = await get_research_directive(
                conn,
                pin.directive_id,
                workspace_id=workspace_id,
            )
            if directive is None or directive.confirming_turn_ref is None:
                raise SumbleCommitteePreparationError(
                    "committee acquisition requires a human-confirmed directive"
                )
            effective = await effective_account_research_directive(
                conn,
                workspace_id=workspace_id,
                directive_id=pin.directive_id,
                account_id=account_entity_id,
                expected_pin=pin,
            )
            if tier != effective.effort_policy.tier:
                raise SumbleCommitteePreparationError(
                    "account tier differs from the effective committee direction"
                )

            tier_claim = None
            for claim in await claims_for(
                conn,
                account_entity_id,
                TIER_FIELD,
                scope=WorkspaceScope.for_workspace(workspace_id),
            ):
                value = claim.value_json
                if (
                    isinstance(value, dict)
                    and claim.extraction_method is ExtractionMethod.HUMAN
                    and claim.source_tier == 1
                    and value.get("project_run_id") == str(project_run_id)
                    and value.get("discovery_batch_id") == str(sealed.discovery_batch_id)
                    and value.get("discovery_seal_sha256") == sealed.seal_sha256
                    and value.get("tier") == tier
                    and value.get("disposition") == "selected"
                ):
                    tier_claim = claim
                    break
            if tier_claim is None:
                raise SumbleCommitteePreparationError(
                    "exact human-approved tier claim is absent for committee acquisition"
                )

            organization_snapshot = await latest_succeeded_account_gap_snapshot(
                conn,
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_id=account_entity_id,
                source_key=ORGANIZATIONS_SOURCE_KEY,
            )
            if organization_snapshot is None or organization_snapshot.response_artifact_key is None:
                raise SumbleCommitteePreparationError(
                    "ready Sumble organization identity snapshot is absent"
                )
            _, response_bytes = await read_verified_artifact(
                conn,
                self._storage,
                storage_key=organization_snapshot.response_artifact_key,
                workspace_id=workspace_id,
            )

        payload = json.loads(response_bytes)
        if not isinstance(payload, dict):
            raise SumbleCommitteePreparationError("Sumble organization snapshot is malformed")
        organization_id = matched_organization_id(payload)
        if organization_id is None:
            raise SumbleCommitteePreparationError(
                "Sumble organization snapshot has no exact matched organization"
            )

        plan = effective.committee_plan
        team_limit = min(plan.candidate_cap, max(1, len(plan.teams) or len(plan.functions) or 1))
        related_people = min(100, plan.candidate_cap)
        jobs_per_team = 1
        people_limit = plan.candidate_cap
        provider_filter = _provider_filter(
            tuple(str(value) for value in plan.functions),
            tuple(str(value) for value in plan.levels),
        )
        advanced = None
        if provider_filter is not None:
            advanced = SumbleAdvancedQuery(expression=provider_filter)
        _, teams_maximum = teams_search_request(
            organization_id,
            limit=team_limit,
            max_people_per_team=related_people,
            max_jobs_per_team=jobs_per_team,
            advanced_query=advanced,
        )
        _, people_maximum = people_search_request(
            organization_id,
            limit=people_limit,
            advanced_query=advanced,
        )
        provider_credit_cap = teams_maximum + people_maximum
        committee_plan_ref = "committee-plan:" + _sha(plan.model_dump(mode="json"))
        privacy_ref = "research-privacy:" + _sha(effective.privacy_policy.model_dump(mode="json"))
        request = CommitteeAcquisitionRequest(
            workspace_id=workspace_id,
            project_id=effective.project_id,
            project_run_id=project_run_id,
            icp_key=effective.icp_key,
            icp_version=effective.icp_version,
            discovery_batch_id=sealed.discovery_batch_id,
            discovery_seal_sha256=sealed.seal_sha256,
            account_id=account_entity_id,
            tier_claim_id=tier_claim.id,
            committee_plan_ref=committee_plan_ref,
            research_direction_ref=pin.directive_ref,
            research_directive=pin,
            organization_identity_ref=(
                f"account-gap-snapshot:{organization_snapshot.operation_id}:"
                f"{ORGANIZATIONS_SOURCE_KEY}"
            ),
            provider_organization_id=str(organization_id),
            provider_api_version=SUMBLE_API_VERSION,
            provider_contract_version=SUMBLE_COMMITTEE_CONTRACT_VERSION,
            pricing_policy_version=SUMBLE_COMMITTEE_PRICING_VERSION,
            committee_policy_version=SUMBLE_COMMITTEE_POLICY_VERSION,
            observation_window=(
                f"project-run:{project_run_id}:account:{account_entity_id}:directive:{pin.canonical_json_sha256}"
            ),
            provider_filter_expression=provider_filter,
            team_limit=team_limit,
            related_people_per_team=related_people,
            jobs_per_team=jobs_per_team,
            people_limit=people_limit,
            provider_credit_cap=provider_credit_cap,
            money_budget_cap_cents=effective.effort_policy.budget_cap_cents,
        )
        authorization = CommitteeExecutionAuthorization(
            workspace_id=workspace_id,
            project_id=effective.project_id,
            project_run_id=project_run_id,
            account_id=account_entity_id,
            research_direction_ref=pin.directive_ref,
            research_directive=pin,
            committee_plan_ref=committee_plan_ref,
            confirmation_ref=directive.confirming_turn_ref,
            confirmed_by_human=True,
            personal_data_allowed=effective.privacy_policy.committee_discovery_allowed,
            jurisdiction_policy_ref=privacy_ref,
            jurisdiction_allowed=(
                UseClass.PROFESSIONAL_PUBLIC in effective.privacy_policy.allowed_use_classes
            ),
            allowed_use_classes=effective.privacy_policy.allowed_use_classes,
            identity_policy_ref="sumble-professional-public-no-reveal:v1",
            identity_acquisition_allowed=effective.privacy_policy.committee_discovery_allowed,
            budget_authorization_ref=f"account-deep-launch:{launch.id}",
            contact_reveals_allowed=False,
        )
        return SumbleCommitteePreparationInputs(
            preflight=compile_sumble_committee_preflight(
                request,
                cents_per_credit=Decimal(self._settings.sumble_cents_per_credit),
            ),
            authorization=authorization,
        )


__all__ = ["DurableSumbleCommitteeInputResolver"]
