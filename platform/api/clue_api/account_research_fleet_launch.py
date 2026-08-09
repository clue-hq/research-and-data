"""M8D R6 compiler from confirmed project direction to one exact account-fleet launch."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from clue_api.account_entity_research_composition import account_research_profile_sha256
from clue_api.account_research_estimate import (
    AccountTierCheckpointMissing,
    compute_account_research_estimate,
)
from clue_api.account_research_fleet import (
    AccountResearchFleetError,
    AccountResearchFleetPolicy,
    AccountResearchFleetProjection,
    AccountResearchFleetService,
)
from clue_core import (
    EntityId,
    EntityScope,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectiveStatus,
    ResearchMode,
    RunId,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
    ResearchOperationKind,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSelectionBasis,
    ResearchSubjectType,
    SelectedResearchSubject,
)
from clue_db import ConnFactory, transaction
from clue_fleet import EntityResearchJobEnvelope, EntityResearchRunEnvelope
from clue_research.claimstore import record_run_lineage
from clue_research.directives import get_research_directive
from clue_research.durable import (
    ensure_account_run,
    get_project_run,
    pin_account_run_research_directive,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.icp import get_icp_version
from clue_research.identity import get_account
from clue_research.resolvers.exa import SOURCE_KEY as EXA_DEEP_SOURCE_KEY
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    ORGANIZATIONS_SOURCE_KEY,
    TECH_STACK_SOURCE_KEY,
)
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_research.sources import (
    freeze_effective_source_plan,
    load_effective_source_plan,
    plan_sources,
)

Money = Annotated[Decimal, Field(ge=0)]

_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-run")
_SELECTION_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-selection")
_JOB_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-job")
_ACCOUNT_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-run-compatibility")
_ATTEMPT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-attempt")
_LEASE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-lease")
_SUPPORTED_FIELD_SOURCES = frozenset(
    {
        EXA_DEEP_SOURCE_KEY,
        ORGANIZATIONS_SOURCE_KEY,
        JOBS_SOURCE_KEY,
        TECH_STACK_SOURCE_KEY,
    }
)


class AccountResearchFleetLaunchError(RuntimeError):
    pass


class AccountResearchFleetLaunchRequest(BaseModel):
    """The explicit action parameters reviewed before a new paid account fleet is offered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_run_id: UUID
    research_directive_id: UUID
    account_entity_ids: tuple[UUID, ...] = Field(min_length=1, max_length=500)
    approved_budget_cap_cents: Money
    expected_estimated_cost_cents: Money
    concurrency_limit: int = Field(default=16, ge=1, le=64)
    supervisor_policy: AccountResearchFleetPolicy = Field(
        default_factory=AccountResearchFleetPolicy
    )

    @model_validator(mode="after")
    def _exact_set(self) -> Self:
        if len(self.account_entity_ids) != len(set(self.account_entity_ids)):
            raise ValueError("account research launch set must be unique")
        return self


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode()
    ).hexdigest()


class AccountResearchFleetLauncher:
    """Validate, persist, compile, and offer one exact account research run."""

    def __init__(
        self,
        *,
        fleets: AccountResearchFleetService,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._fleets = fleets
        self._conn_factory = conn_factory

    async def launch(
        self,
        request: AccountResearchFleetLaunchRequest,
        *,
        actor: str,
        source_action_ref: str,
        source_operation_id: UUID,
    ) -> AccountResearchFleetProjection:
        if not actor.strip() or not source_action_ref.strip():
            raise AccountResearchFleetLaunchError(
                "account research launch requires an attributable confirmed action"
            )
        account_ids = tuple(EntityId(value) for value in request.account_entity_ids)
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {
                    "scope": (
                        f"account-research-launch:{request.workspace_id}:{source_operation_id}"
                    )
                },
            )
            project_run = await get_project_run(conn, ProjectRunId(request.project_run_id))
            if (
                project_run is None
                or project_run.workspace_id != request.workspace_id
                or project_run.product_id is None
            ):
                raise AccountResearchFleetLaunchError(
                    "account research requires an exact project/product-bound run"
                )
            if project_run.status is ProjectRunStatus.FAILED:
                raise AccountResearchFleetLaunchError(
                    "a failed project run cannot authorize new account research"
                )
            directive = await get_research_directive(
                conn,
                ResearchDirectiveId(request.research_directive_id),
                workspace_id=request.workspace_id,
            )
            if (
                directive is None
                or directive.status is not ResearchDirectiveStatus.CONFIRMED
                or directive.confirming_turn_ref is None
                or directive.confirmed_at is None
            ):
                raise AccountResearchFleetLaunchError(
                    "account research requires the current human-confirmed directive"
                )
            if (
                directive.project_id != project_run.project_id
                or directive.product_id != project_run.product_id
                or directive.icp_key != project_run.icp_key
                or directive.icp_version != project_run.icp_version
            ):
                raise AccountResearchFleetLaunchError(
                    "directive lineage differs from the exact project run"
                )
            if not directive.body.privacy_policy.account_research_allowed:
                raise AccountResearchFleetLaunchError(
                    "directive policy does not authorize account research"
                )

            # FI Lane D D4 (§3-P5(b), ratified §6-D5): the Σ per-account budget-cap loop moved to
            # ``clue_api.account_research_estimate`` verbatim so the directive-confirmation gate
            # can write **the same number** this launcher then verifies. One computation, two
            # callers; the exact-match verification below is unchanged and stays the launcher's.
            try:
                estimate = await compute_account_research_estimate(
                    conn,
                    workspace_id=request.workspace_id,
                    project_run_id=ProjectRunId(request.project_run_id),
                    directive_id=directive.directive_id,
                    account_ids=account_ids,
                )
            except AccountTierCheckpointMissing as exc:
                raise AccountResearchFleetLaunchError(str(exc)) from exc
            effective_by_account = estimate.effective_by_account
            pins_by_account = {
                account_id: effective.pin
                for account_id, effective in effective_by_account.items()
            }
            estimated_cost = estimate.total_cents
            # FI-2 §6.2 estimate netting (spec §11 open item 3, a "should-have"): the estimate is
            # deliberately **gross** — it is not reduced by the fields the fresh-skip will make
            # free.  Four verified reasons, recorded so this is a decision and not an oversight:
            #
            # 1. ``effort_policy.budget_cap_cents`` is a per-account *cap*, not a per-field price.
            #    Nothing decomposes it per field, so "netting" it means inventing a cost model the
            #    directive does not carry.
            # 2. The same number is each job's ``budget_cap_cents`` below (and this sum is what
            #    ``approved_budget_cap_cents`` must cover).  Netting the sum without netting the
            #    per-job caps would let a launch be approved for less than the authority it hands
            #    out — the dangerous direction.
            # 3. ``expected_estimated_cost_cents`` is a *caller-supplied* input, equality-checked
            #    here; there is no server-side estimate-proposal surface for this launch at all
            #    (``LaunchAccountResearchTool.estimate`` just echoes the input back).  So netting
            #    would break every existing caller and has no producer to move in step — the
            #    opposite of "minimal".
            # 4. A launch-time freshness probe is a *prediction* that the runtime re-takes when the
            #    job plans, and it would enter the durably-replayed launch identity: a claim that
            #    expires between launch and replay would change the number and turn a legitimate
            #    idempotent replay into a conflict.
            #
            # The honest consequence, stated rather than hidden: the estimate is a **ceiling**, and
            # the fresh-skip materialises as under-spend.  Where the money actually went is already
            # answerable from data — per-job spend on the job row, and the coverage ledger's
            # per-field ``…:existing_claim_fresh`` skip reasons.  Netting belongs with an estimate
            # *proposal* surface, so both sides of the equality can move together.
            if estimated_cost != request.expected_estimated_cost_cents:
                raise AccountResearchFleetLaunchError(
                    "approved estimate differs from the current effective directives"
                )
            if request.approved_budget_cap_cents < estimated_cost:
                raise AccountResearchFleetLaunchError(
                    "approved account-fleet budget is below the reviewed estimate"
                )
            if project_run.budget_cap_cents is not None:
                remaining = max(Decimal(0), project_run.budget_cap_cents - project_run.spent_cents)
                if request.approved_budget_cap_cents > remaining:
                    raise AccountResearchFleetLaunchError(
                        "approved account-fleet budget exceeds remaining project headroom"
                    )
            first = effective_by_account[account_ids[0]]
            common_authority = (
                tuple(str(value) for value in first.field_keys),
                tuple(item.text for item in first.questions),
                first.source_policy,
                first.committee_plan,
                first.privacy_policy,
            )
            for account_id, effective in effective_by_account.items():
                authority = (
                    tuple(str(value) for value in effective.field_keys),
                    tuple(item.text for item in effective.questions),
                    effective.source_policy,
                    effective.committee_plan,
                    effective.privacy_policy,
                )
                if authority != common_authority:
                    raise AccountResearchFleetLaunchError(
                        "one account fleet currently requires common fields, questions, sources, "
                        f"committee, and privacy authority; account {account_id} has an override"
                    )

            field_keys = tuple(
                str(value) for value in first.field_keys if str(value).startswith("account.")
            )
            questions = tuple(item.text for item in first.questions)
            if not field_keys or not questions:
                raise AccountResearchFleetLaunchError(
                    "account research requires confirmed account fields and directional questions"
                )
            allowed_sources = set(first.source_policy.allowed_source_keys)
            icp = await get_icp_version(
                conn,
                request.workspace_id,
                first.icp_key,
                first.icp_version,
            )
            account = await get_account(conn, account_ids[0])
            if icp is None or account is None or account.workspace_id != request.workspace_id:
                raise AccountResearchFleetLaunchError(
                    "account research source compilation lacks its exact ICP/account"
                )
            authorities: list[FieldSourceAuthority] = []
            source_plan_values: list[dict[str, object]] = []
            for field_key in field_keys:
                plan = await load_effective_source_plan(
                    conn,
                    workspace_id=request.workspace_id,
                    icp_key=first.icp_key,
                    icp_version=first.icp_version,
                    field_key=field_key,
                )
                if plan is None:
                    planned = await plan_sources(
                        conn,
                        spec=icp,
                        entity=account.as_entity(),
                        field=field_key,
                        mode=ResearchMode.ACCOUNT_PROFILING,
                        entity_tier=str(first.effort_policy.tier),
                        entity_scope=EntityScope.ACCOUNT,
                        budget_envelope=first.effort_policy.budget_cap_cents,
                    )
                    if planned.effective_source_plan is None:
                        raise AccountResearchFleetLaunchError(
                            f"source planning produced no durable authority for {field_key}"
                        )
                    plan = await freeze_effective_source_plan(
                        conn,
                        planned.effective_source_plan,
                        source_profile_ref=icp.source_profile_ref,
                    )
                source_keys = tuple(
                    item.source_key
                    for item in plan.sources
                    if item.source_key in allowed_sources
                    and item.source_key in _SUPPORTED_FIELD_SOURCES
                )
                if not source_keys:
                    raise AccountResearchFleetLaunchError(
                        f"no composed R5 source is authorized for {field_key}"
                    )
                authorities.append(
                    FieldSourceAuthority(field_key=field_key, source_keys=source_keys)
                )
                source_plan_values.append(
                    {
                        "field_key": field_key,
                        "plan_sha256": plan.plan_sha256,
                        "source_keys": list(source_keys),
                    }
                )
            if (
                PEOPLE_SOURCE_KEY not in allowed_sources
                or not first.privacy_policy.committee_discovery_allowed
            ):
                raise AccountResearchFleetLaunchError(
                    "account fleet requires authorized no-reveal committee discovery"
                )

            source_keys = tuple(
                dict.fromkeys(
                    source for authority in authorities for source in authority.source_keys
                )
            )
            admitted_sources = (*source_keys, PEOPLE_SOURCE_KEY)
            field_plan_sha = _sha({"field_keys": field_keys})
            source_plan_sha = _sha(source_plan_values)
            request_sha = _sha(
                {
                    "workspace_id": request.workspace_id,
                    "project_id": project_run.project_id,
                    "product_id": project_run.product_id,
                    "project_run_id": str(request.project_run_id),
                    "directive_ref": directive.directive_ref,
                    "directive_sha256": directive.canonical_json_sha256,
                    "account_pins": [
                        pins_by_account[account_id].model_dump(mode="json")
                        for account_id in account_ids
                    ],
                    "account_entity_ids": [str(value) for value in account_ids],
                    "field_keys": list(field_keys),
                    "questions": list(questions),
                    "field_source_authority": [
                        value.model_dump(mode="json") for value in authorities
                    ],
                    "committee_source_keys": [PEOPLE_SOURCE_KEY],
                    "approved_budget_cap_cents": request.approved_budget_cap_cents,
                    "expected_estimated_cost_cents": request.expected_estimated_cost_cents,
                    "concurrency_limit": request.concurrency_limit,
                    "supervisor_policy_sha256": (request.supervisor_policy.policy_sha256),
                    "actor": actor,
                    "source_action_ref": source_action_ref,
                    "source_operation_id": str(source_operation_id),
                }
            )
            selection_id = uuid5(_SELECTION_NAMESPACE, request_sha)
            selection = EntityResearchSelection(
                selection_id=selection_id,
                workspace_id=request.workspace_id,
                project_id=project_run.project_id,
                product_id=project_run.product_id,
                project_run_id=request.project_run_id,
                subject_type=ResearchSubjectType.ACCOUNT,
                subjects=tuple(
                    SelectedResearchSubject(
                        subject_entity_id=account_id,
                        basis=ResearchSelectionBasis.ACCOUNT_SELECTION,
                    )
                    for account_id in account_ids
                ),
                directive_ref=directive.directive_ref,
                directive_sha256=directive.canonical_json_sha256,
                field_plan_ref=f"account-field-plan:{field_plan_sha}",
                source_plan_ref=f"effective-source-plans:{source_plan_sha}",
                admitted_field_keys=field_keys,
                admitted_source_keys=admitted_sources,
                field_source_authority=tuple(authorities),
                committee_source_keys=(PEOPLE_SOURCE_KEY,),
                research_questions=questions,
                policy_refs=(
                    f"account-research-launch:{request_sha}",
                    first.effort_policy.freshness_policy_ref,
                    first.effort_policy.recursion_policy_ref,
                    f"research-privacy:{_sha(first.privacy_policy.model_dump(mode='json'))}",
                    request.supervisor_policy.policy_ref,
                ),
                budget_envelope_ref=f"account-research-launch:{request_sha}",
                # The launching action and the directive's confirming turn, de-duplicated. They are
                # usually two acts ("you confirmed the direction last week; you approve this launch
                # now") and the pair records both. Under the FI Lane D Option-B kickoff they are
                # deliberately **one** act: the user's structured approval confirms the directive
                # and is the very turn the deepagent then launches from, so both names resolve to
                # the same ``turn-action:`` receipt. Listing it twice would claim two approvals
                # where there was one — and the selection contract rightly refuses duplicates.
                approval_refs=tuple(
                    dict.fromkeys((source_action_ref, directive.confirming_turn_ref))
                ),
                confirmed_by=actor,
                confirmed_at=directive.confirmed_at,
            )
            research_run_id = uuid5(_RUN_NAMESPACE, request_sha)
            # FI-2 P2 (spec §3): attribute the research run to its project inside the launch
            # transaction — the same one the run/job rows below commit in. Idempotent, so a
            # re-confirmed identical request (same ``request_sha`` -> same run id) re-registers
            # harmlessly. The per-tool-call materialization runs derived from this id register
            # themselves at their own mint sites (that is what ``claim.run_id`` actually carries).
            await record_run_lineage(
                conn,
                run_id=research_run_id,
                workspace_id=request.workspace_id,
                kind="entity_research",
                project_id=project_run.project_id,
                project_run_id=UUID(str(request.project_run_id)),
            )
            lifecycle = ResearchRunLifecycleContract(
                run_id=research_run_id,
                run_kind=ResearchRunKind.ACCOUNT_RESEARCH,
                selection=selection,
                user_confirmed_launch=True,
                operations=(
                    ResearchOperationKind.ACCOUNT_PROFILE,
                    ResearchOperationKind.COMMITTEE_DISCOVERY,
                ),
                automatic_successor_run=False,
            )
            profile_sha = account_research_profile_sha256()
            jobs: list[EntityResearchJobEnvelope] = []
            account_runs_by_job: dict[UUID, UUID] = {}
            for priority, account_id in enumerate(account_ids):
                effective = effective_by_account[account_id]
                account_run_id = RunId(
                    uuid5(
                        _ACCOUNT_RUN_NAMESPACE,
                        f"{request.project_run_id}:{account_id}:{request_sha}",
                    )
                )
                await ensure_account_run(
                    conn,
                    account_run_id=account_run_id,
                    project_run_id=ProjectRunId(request.project_run_id),
                    entity_id=account_id,
                    tier=str(effective.effort_policy.tier),
                    budget_cap_cents=effective.effort_policy.budget_cap_cents,
                )
                await pin_account_run_research_directive(
                    conn,
                    account_run_id=account_run_id,
                    pin=pins_by_account[account_id],
                )
                job_id = uuid5(_JOB_NAMESPACE, f"{research_run_id}:{account_id}")
                account_runs_by_job[job_id] = UUID(str(account_run_id))
                authorization = EntityResearchJobAuthorization(
                    job_id=job_id,
                    research_run_id=research_run_id,
                    subject_type=ResearchSubjectType.ACCOUNT,
                    subject_entity_id=account_id,
                    workspace_id=request.workspace_id,
                    project_id=project_run.project_id,
                    product_id=project_run.product_id,
                    project_run_id=request.project_run_id,
                    selection=selection,
                    agent_profile_ref="agent-profile:account-research:v1",
                    agent_profile_sha256=profile_sha,
                    checkpoint_thread_id=f"entity-research:{job_id}",
                    attempt_id=uuid5(_ATTEMPT_NAMESPACE, str(job_id)),
                    lease_id=uuid5(_LEASE_NAMESPACE, str(job_id)),
                )
                jobs.append(
                    EntityResearchJobEnvelope(
                        authorization=authorization,
                        priority=priority,
                        budget_envelope_ref=effective.effort_policy.budget_envelope_ref,
                        budget_cap_cents=effective.effort_policy.budget_cap_cents,
                    )
                )
            envelope = EntityResearchRunEnvelope(
                lifecycle=lifecycle,
                jobs=tuple(jobs),
                budget_cap_cents=request.approved_budget_cap_cents,
                concurrency_limit=request.concurrency_limit,
            )
            try:
                return await self._fleets.launch_in_transaction(
                    conn,
                    envelope,
                    policy=request.supervisor_policy,
                    actor=actor,
                    source_operation_id=source_operation_id,
                    source_action_ref=source_action_ref,
                    account_run_ids=account_runs_by_job,
                )
            except AccountResearchFleetError as exc:
                raise AccountResearchFleetLaunchError(str(exc)) from exc


__all__ = [
    "AccountResearchFleetLaunchError",
    "AccountResearchFleetLaunchRequest",
    "AccountResearchFleetLauncher",
]
