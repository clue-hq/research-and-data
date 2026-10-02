"""Production A2/O2 inputs for bounded Sumble Teams + People acquisition."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader
from clue_api.sumble_committee_acquisition import (
    SUMBLE_COMMITTEE_CONTRACT_VERSION,
    SUMBLE_COMMITTEE_POLICY_VERSION,
    SUMBLE_COMMITTEE_PRICING_VERSION,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_preparation import (
    COMMITTEE_PROVIDER_IDENTITY_ABSENT,
    COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
    SumbleCommitteePreparationError,
    SumbleCommitteePreparationInputs,
    SumbleCommitteeProviderIdentityUnavailable,
)
from clue_config import Settings
from clue_core import (
    CommitteeAcquisitionRequest,
    CommitteeExecutionAuthorization,
    DiscoveryGapOperationState,
    EntityId,
    ProjectRunId,
    RunId,
    UseClass,
)
from clue_core.entity_research import EntityResearchJobAuthorization
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.directives import (
    effective_account_research_directive,
    get_research_directive,
)
from clue_research.discovery_scoring.tiering import TIER_CLAIM_MAX_SOURCE_TIER, TIER_FIELD
from clue_research.durable import (
    account_deep_launch_account_pins,
    get_account_deep_launch,
    get_account_run,
    get_project_run,
    latest_succeeded_account_gap_snapshot,
    list_discovery_gap_operations,
)
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_API_VERSION,
    matched_organization_id,
)
from clue_research.resolvers.sumble.people import people_search_request
from clue_research.resolvers.sumble.teams import teams_search_request
from clue_storage import StorageBackend, read_verified_artifact


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


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
        entity_research_job_id: UUID | None = None,
    ) -> SumbleCommitteePreparationInputs:
        discovery_receipt = None
        if entity_research_job_id is not None:
            async with self._conn_factory() as conn:
                authorization_json = (
                    await conn.execute(
                        text(
                            "SELECT authorization_json FROM entity_research_job "
                            "WHERE job_id=:job_id AND subject_type='account' "
                            "AND subject_entity_id=:account_id AND workspace_id=:workspace_id "
                            "AND project_run_id=:project_run_id"
                        ),
                        {
                            "job_id": entity_research_job_id,
                            "account_id": account_entity_id,
                            "workspace_id": workspace_id,
                            "project_run_id": project_run_id,
                        },
                    )
                ).scalar_one_or_none()
            if authorization_json is None:
                raise SumbleCommitteePreparationError(
                    "Sumble committee inputs require the exact Account research job"
                )
            discovery_receipt = EntityResearchJobAuthorization.model_validate(
                authorization_json
            ).selection.discovery_receipt
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
            discovery_receipt=discovery_receipt,
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
            budget_authorization_ref: str
            if entity_research_job_id is None:
                # Historical exact replay only. New M8D work is authorized by the separately
                # confirmed R6 account-fleet job below and never reconstructs this retired launch.
                launch = await get_account_deep_launch(
                    conn,
                    project_run_id,
                    workspace_id=workspace_id,
                )
                if launch is None:
                    raise SumbleCommitteePreparationError(
                        "historical account-deep launch authorization is absent"
                    )
                launch_pins = await account_deep_launch_account_pins(conn, launch)
                if pin not in launch_pins:
                    raise SumbleCommitteePreparationError(
                        "account is outside the exact historical directive selection"
                    )
                budget_authorization_ref = f"account-deep-launch:{launch.id}"
            else:
                authority = (
                    (
                        await conn.execute(
                            text(
                                "SELECT job.authorization_json, control.account_run_id, "
                                "control.admission_state::text AS admission_state, "
                                "fleet.workspace_id, fleet.project_run_id, fleet.state::text "
                                "AS fleet_state FROM entity_research_job job JOIN "
                                "entity_research_account_fleet_job_control control "
                                "USING (job_id, research_run_id) JOIN "
                                "entity_research_account_fleet fleet USING (research_run_id) "
                                "WHERE job.job_id=:job_id AND job.subject_type='account' AND "
                                "job.subject_entity_id=:account_id AND "
                                "job.project_run_id=:project_run_id AND "
                                "job.workspace_id=:workspace_id AND "
                                "control.account_run_id=:account_run_id AND "
                                "control.admission_state IN ('admitted', 'released') AND "
                                "job.state IN ('running', 'waiting_external')"
                            ),
                            {
                                "job_id": entity_research_job_id,
                                "account_id": account_entity_id,
                                "project_run_id": project_run_id,
                                "workspace_id": workspace_id,
                                "account_run_id": account_run_id,
                            },
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if authority is None:
                    raise SumbleCommitteePreparationError(
                        "Sumble committee inputs require the exact live R6 account job"
                    )
                job_authorization = EntityResearchJobAuthorization.model_validate(
                    authority["authorization_json"]
                )
                if (
                    job_authorization.subject_entity_id != account_entity_id
                    or job_authorization.project_run_id != project_run_id
                    or job_authorization.workspace_id != workspace_id
                    or job_authorization.selection.directive_ref != pin.directive_ref
                    or job_authorization.selection.directive_sha256 != pin.canonical_json_sha256
                ):
                    raise SumbleCommitteePreparationError(
                        "R6 account job authorization differs from its pinned directive"
                    )
                budget_authorization_ref = f"entity-research-job:{entity_research_job_id}"
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
            if entity_research_job_id is None:
                for claim in await claims_for(
                    conn,
                    account_entity_id,
                    TIER_FIELD,
                    scope=WorkspaceScope.for_workspace(workspace_id),
                ):
                    value = claim.value_json
                    if (
                        isinstance(value, dict)
                        and claim.source_tier <= TIER_CLAIM_MAX_SOURCE_TIER
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
                        "exact approved tier claim is absent for committee acquisition"
                    )

            organization_snapshot = await latest_succeeded_account_gap_snapshot(
                conn,
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_id=account_entity_id,
                source_key=ORGANIZATIONS_SOURCE_KEY,
            )
            if (
                organization_snapshot is not None
                and organization_snapshot.response_artifact_key is not None
            ):
                organization_response_artifact_key = organization_snapshot.response_artifact_key
                organization_identity_ref = (
                    f"account-gap-snapshot:{organization_snapshot.operation_id}:"
                    f"{ORGANIZATIONS_SOURCE_KEY}"
                )
            else:
                # Organization identity is first acquired during required-field discovery for
                # many accounts.  That paid, exact-batch Sumble response is every bit as durable
                # as the later account-gap snapshot and is already part of the sealed discovery
                # truth.  Requiring the account agent to re-buy an unrelated structured deep
                # field made committee acquisition unreachable for ICPs whose deep plan is
                # qualitative only.
                discovery_operations = await list_discovery_gap_operations(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=sealed.discovery_batch_id,
                )
                organization_candidates = tuple(
                    operation
                    for operation in discovery_operations
                    if operation.request.project_run_id == project_run_id
                    and operation.request.account_id == account_entity_id
                    and operation.request.source_key == ORGANIZATIONS_SOURCE_KEY
                    and operation.state is DiscoveryGapOperationState.SUCCEEDED
                    and operation.response_artifact_key is not None
                )
                if not organization_candidates:
                    # World fact, not a model mistake and not an authority breach: no Sumble
                    # Organizations response for this account exists anywhere in durable state, so
                    # the committee axis cannot be bought. Recoverable — see
                    # ``SumbleCommitteeProviderIdentityUnavailable``.
                    raise SumbleCommitteeProviderIdentityUnavailable(
                        COMMITTEE_PROVIDER_IDENTITY_ABSENT,
                        "ready Sumble organization identity is absent from account and "
                        "sealed-discovery enrichment",
                    )
                discovery_operation = max(
                    organization_candidates,
                    key=lambda operation: (
                        (
                            operation.updated_at.isoformat()
                            if operation.updated_at is not None
                            else ""
                        ),
                        str(operation.operation_id),
                    ),
                )
                assert discovery_operation.response_artifact_key is not None
                organization_response_artifact_key = discovery_operation.response_artifact_key
                organization_identity_ref = (
                    f"discovery-gap-operation:{discovery_operation.operation_id}:"
                    f"{ORGANIZATIONS_SOURCE_KEY}"
                )
            _, response_bytes = await read_verified_artifact(
                conn,
                self._storage,
                storage_key=organization_response_artifact_key,
                workspace_id=workspace_id,
            )

        payload = json.loads(response_bytes)
        if not isinstance(payload, dict):
            # Truth species and deliberately NOT converted: the artifact is digest-verified, so a
            # non-object payload means our own capture wrote something no Sumble response can be.
            raise SumbleCommitteePreparationError("Sumble organization snapshot is malformed")
        organization_id = matched_organization_id(payload)
        if organization_id is None:
            # The live ``dc86340f`` failure. Sumble's organization index has no exact match for
            # this account (a small Chicago physician group); every later committee call keys on
            # that id, so the axis is unbuyable — for this account, permanently. Same species as
            # the provider 402 that already folds terminally: the account settles with an honest
            # committee gap instead of the job dying on a raw escape.
            raise SumbleCommitteeProviderIdentityUnavailable(
                COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
                "Sumble organization snapshot has no exact matched organization",
            )

        plan = effective.committee_plan
        team_limit = min(plan.candidate_cap, max(1, len(plan.teams) or len(plan.functions) or 1))
        related_people = min(100, plan.candidate_cap)
        jobs_per_team = 1
        people_limit = plan.candidate_cap
        # The committee request deliberately carries NO advanced query. Sumble's documented
        # grammar has no multi-value operator (`IN`/`OR` do not exist; live HTTP 400), and
        # `/v9/teams` cannot filter on job level at all — see
        # `docs/specs/M8D-R10-sumble-contract-decision.md`. The plan's function/level/team
        # selectors remain durable authority for the local post-provider admission gate, never a
        # wire filter. Credit maxima are limit-derived and therefore unchanged.
        _, teams_maximum = teams_search_request(
            organization_id,
            limit=team_limit,
            max_people_per_team=related_people,
            max_jobs_per_team=jobs_per_team,
        )
        _, people_maximum = people_search_request(
            organization_id,
            limit=people_limit,
        )
        provider_credit_cap = teams_maximum + people_maximum
        committee_plan_ref = "committee-plan:" + _sha(plan.model_dump(mode="json"))
        privacy_ref = "research-privacy:" + _sha(effective.privacy_policy.model_dump(mode="json"))
        request = CommitteeAcquisitionRequest(
            workspace_id=workspace_id,
            project_id=effective.project_id,
            project_run_id=project_run_id,
            entity_research_job_id=entity_research_job_id,
            icp_key=effective.icp_key,
            icp_version=effective.icp_version,
            discovery_batch_id=sealed.discovery_batch_id,
            discovery_seal_sha256=sealed.seal_sha256,
            account_id=account_entity_id,
            tier_claim_id=tier_claim.id if tier_claim is not None else None,
            committee_plan_ref=committee_plan_ref,
            research_direction_ref=pin.directive_ref,
            research_directive=pin,
            organization_identity_ref=organization_identity_ref,
            provider_organization_id=str(organization_id),
            provider_api_version=SUMBLE_API_VERSION,
            provider_contract_version=SUMBLE_COMMITTEE_CONTRACT_VERSION,
            pricing_policy_version=SUMBLE_COMMITTEE_PRICING_VERSION,
            committee_policy_version=SUMBLE_COMMITTEE_POLICY_VERSION,
            observation_window=(
                f"project-run:{project_run_id}:account:{account_entity_id}:directive:{pin.canonical_json_sha256}"
            ),
            provider_filter_expression=None,
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
            budget_authorization_ref=budget_authorization_ref,
            contact_reveals_allowed=False,
        )
        return SumbleCommitteePreparationInputs(
            preflight=compile_sumble_committee_preflight(
                request,
                cents_per_credit=Decimal(self._settings.sumble_cents_per_credit),
                # FI pilot budget-controls, same switch the coordinator and the durable
                # reservation already read: with it off the wire plan's cost comparisons are
                # recorded rather than refused (founder ruling 2026-08-20).
                enforce_budget=self._settings.budget_controls_enabled,
            ),
            authorization=authorization,
            committee_plan=plan,
            discovery_receipt=discovery_receipt,
        )


__all__ = ["DurableSumbleCommitteeInputResolver"]
