"""M8D R6 compiler from confirmed project direction to one exact account-fleet launch."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from clue_api.account_entity_research_composition import (
    ACCOUNT_RESEARCH_PROFILE_REF,
    account_research_profile_sha256,
)
from clue_api.account_research_discovery_readiness import (
    AccountResearchDiscoveryNotReady,
    require_sealed_account_discovery,
)
from clue_api.account_research_estimate import compute_account_research_estimate
from clue_api.account_research_fleet import (
    AccountResearchFleetError,
    AccountResearchFleetPolicy,
    AccountResearchFleetProjection,
    AccountResearchFleetService,
)
from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    source_can_request,
)
from clue_core import (
    EffectiveFieldSourcePlan,
    EffectiveSourceAuthorization,
    EntityId,
    EntityScope,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectiveStatus,
    ResearchMode,
    RunId,
    SourceTier,
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
    SealedDiscoveryLaunchReceipt,
    SelectedResearchSubject,
)
from clue_core.field import account_axis_field_keys
from clue_db import ConnFactory, transaction
from clue_fleet import EntityResearchJobEnvelope, EntityResearchRunEnvelope
from clue_obs import get_logger
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
    get_source,
    load_effective_source_plan,
    plan_sources,
    sources_for,
)

log = get_logger("clue_api.account_research_fleet_launch")

Money = Annotated[Decimal, Field(ge=0)]

_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-run")
_SELECTION_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-selection")
_JOB_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-job")
_ACCOUNT_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-run-compatibility")
_ATTEMPT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-attempt")
_LEASE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-research-lease")
#: §3.1 rows whose ownership tuple is empty — reused or derived, never bought (see the launch
#: partition below). Derived from the frozen contract map so the two can never drift.
_ZERO_ACQUISITION_PROFILE_FIELDS = frozenset(
    field for field, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items() if not sources
)

_SUPPORTED_FIELD_SOURCES = frozenset(
    {
        EXA_DEEP_SOURCE_KEY,
        ORGANIZATIONS_SOURCE_KEY,
        JOBS_SOURCE_KEY,
        TECH_STACK_SOURCE_KEY,
    }
)


#: Intersecting requestability into the *authority* at launch is what keeps the two halves of the
#: platform honest: a pair nobody can ever dispatch must not be born as an obligation the
#: completeness reader then waits on forever. The predicate itself lives in the frozen contract
#: module, because the completeness reader must apply exactly the same one to selections minted
#: before this intersection existed.
_source_can_request = source_can_request


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
    """Validate, persist, compile, and offer one exact account research run.

    ``enforce_budget`` is ``Settings.budget_controls_enabled`` (FI pilot budget-controls). With it
    False the three *economic* admission checks below — the caller's estimate echo, the approved cap
    vs the estimate, and the remaining project headroom — are skipped, because the pilot's ruling is
    that nothing stops a pre-approved action on budget grounds and, with the amount withheld from
    every surface, the caller has no number to echo in the first place. Every *structural* check is
    untouched in both modes: the directive must still be the current human-confirmed one, its
    lineage must still match the run, its privacy policy must still authorize the research, and each
    job is still launched with the directive's own per-account ``budget_cap_cents``, so spend is
    still fully attributed and recorded."""

    def __init__(
        self,
        *,
        fleets: AccountResearchFleetService,
        conn_factory: ConnFactory = transaction,
        enforce_budget: bool = True,
    ) -> None:
        self._fleets = fleets
        self._conn_factory = conn_factory
        self._enforce_budget = enforce_budget

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
            try:
                discovery = await require_sealed_account_discovery(
                    conn,
                    workspace_id=request.workspace_id,
                    project_run_id=ProjectRunId(request.project_run_id),
                    icp_key=project_run.icp_key,
                    icp_version=project_run.icp_version,
                    for_update=True,
                )
            except AccountResearchDiscoveryNotReady as exc:
                raise AccountResearchFleetLaunchError(str(exc)) from exc
            selected_outside_seal = set(account_ids) - set(discovery.account_ids)
            if selected_outside_seal:
                raise AccountResearchFleetLaunchError(
                    "account research selection contains an Account outside the exact sealed "
                    "discovery membership"
                )
            discovery_receipt = SealedDiscoveryLaunchReceipt(
                discovery_batch_id=UUID(str(discovery.discovery_batch_id)),
                discovery_generation=discovery.discovery_generation,
                discovery_seal_sha256=discovery.discovery_seal_sha256,
                account_manifest_ref=discovery.account_manifest_ref,
                account_manifest_sha256=discovery.account_manifest_sha256,
                claim_manifest_ref=discovery.claim_manifest_ref,
                claim_manifest_sha256=discovery.claim_manifest_sha256,
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
                # All three halves of the confirmation receipt or none: the directive's own row is
                # the only place the human approver is recorded, and the frozen selection below
                # cites it (see ``confirmed_by`` there).
                or directive.confirmed_by is None
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
            estimate = await compute_account_research_estimate(
                conn,
                workspace_id=request.workspace_id,
                project_run_id=ProjectRunId(request.project_run_id),
                directive_id=directive.directive_id,
                account_ids=account_ids,
            )
            effective_by_account = estimate.effective_by_account
            pins_by_account = {
                account_id: effective.pin for account_id, effective in effective_by_account.items()
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
            if self._enforce_budget:
                if estimated_cost != request.expected_estimated_cost_cents:
                    raise AccountResearchFleetLaunchError(
                        "approved estimate differs from the current effective directives"
                    )
                if request.approved_budget_cap_cents < estimated_cost:
                    raise AccountResearchFleetLaunchError(
                        "approved account-fleet budget is below the reviewed estimate"
                    )
                if project_run.budget_cap_cents is not None:
                    remaining = max(
                        Decimal(0), project_run.budget_cap_cents - project_run.spent_cents
                    )
                    if request.approved_budget_cap_cents > remaining:
                        raise AccountResearchFleetLaunchError(
                            "approved account-fleet budget exceeds remaining project headroom"
                        )
            else:
                # FI pilot budget-controls: the estimate is still recomputed above (it is what the
                # per-account job caps and the durable launch identity are built from) and is logged
                # here so the record of what this launch was priced at survives, even though no
                # caller-supplied number gates it.
                log.info(
                    "account_research.launch.budget_controls_disabled",
                    workspace_id=request.workspace_id,
                    project_run_id=str(request.project_run_id),
                    directive_ref=directive.directive_ref,
                    account_count=len(account_ids),
                    recomputed_estimate_cents=str(estimated_cost),
                    caller_expected_cents=str(request.expected_estimated_cost_cents),
                    approved_budget_cap_cents=str(request.approved_budget_cap_cents),
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

            # Project the confirmed authority onto the shared account axis (CORE | ACCOUNT |
            # ACCOUNT_RESONANCE | PACK) — the same projection the in-job Exa preparation applies.
            # A raw ``account.`` prefix filter silently dropped the comprehensive profile's
            # ``core.*`` firmographic fields, so launcher and runtime disagreed about the field
            # universe; contact fields stay excluded for the later committee/contact fleet.
            field_keys = tuple(str(key) for key in account_axis_field_keys(first.field_keys))
            questions = tuple(item.text for item in first.questions)
            # ``ResearchDirectiveBody`` deliberately permits a field-only directive. The fixed
            # comprehensive profile already supplies the complete 21-field execution authority;
            # no placeholder question is invented merely to satisfy the older R0 envelope.
            # Question-only directives remain ineligible because this launcher needs at least one
            # governed acquisition field.
            if not field_keys:
                raise AccountResearchFleetLaunchError(
                    "account research requires confirmed account fields"
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
            # §3.1 rows 1/5/8 own no acquisition source: core.account_name is reused canonical
            # identity truth, and core.employee_range / core.revenue_band are derived from
            # governed evidence at finalization. The directive keeps carrying them (the runtime
            # drives preparation and coverage off the directive's full field universe), but the
            # launch selection admits only acquisition fields — you cannot buy, estimate, or
            # authorize a source for a field that has none, and EntityResearchSelection requires
            # source authority to cover every admitted field.
            acquisition_field_keys = tuple(
                key for key in field_keys if key not in _ZERO_ACQUISITION_PROFILE_FIELDS
            )
            if not acquisition_field_keys:
                raise AccountResearchFleetLaunchError(
                    "account research requires at least one acquisition field"
                )
            field_keys = acquisition_field_keys
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
                    compiled = planned.effective_source_plan
                    if not compiled.sources:
                        # Some Stage-0 ICPs intentionally have no authored source-profile slot.
                        # The confirmed directive has already validated its exact source keys
                        # against the active registry and this field. Preserve that bounded
                        # authority instead of turning the absent override into a research ban.
                        capable = set(
                            await sources_for(
                                conn,
                                field_key,
                                entity_scope=EntityScope.ACCOUNT,
                                active=True,
                            )
                        )
                        explicit_sources: list[EffectiveSourceAuthorization] = []
                        for source_key in first.source_policy.allowed_source_keys:
                            if (
                                source_key not in capable
                                or source_key not in _SUPPORTED_FIELD_SOURCES
                            ):
                                continue
                            source = await get_source(conn, source_key)
                            if source is not None:
                                explicit_sources.append(
                                    EffectiveSourceAuthorization(
                                        source_key=source_key,
                                        source_tier=SourceTier(source.tier),
                                    )
                                )
                        if explicit_sources:
                            compiled = EffectiveFieldSourcePlan.compile(
                                workspace_id=request.workspace_id,
                                icp_key=first.icp_key,
                                icp_version=first.icp_version,
                                field_key=field_key,
                                sources=tuple(explicit_sources),
                            )
                    plan = await freeze_effective_source_plan(
                        conn,
                        compiled,
                        source_profile_ref=icp.source_profile_ref,
                    )
                authorized = tuple(
                    item.source_key
                    for item in plan.sources
                    if item.source_key in allowed_sources
                    and item.source_key in _SUPPORTED_FIELD_SOURCES
                )
                if not authorized:
                    raise AccountResearchFleetLaunchError(
                        f"no composed R5 source is authorized for {field_key}"
                    )
                # Requestability is intersected into the effective authority here, once, at the
                # only place that mints it. A source whose pinned action structurally cannot ask
                # for this field never enters the field's authorized list, so no unbuyable
                # (field, source) pair is ever born: the field either keeps its remaining sources
                # (e.g. ``account.total_funding`` keeps Exa Deep after Sumble Organizations drops
                # out) or is admitted with *no* authority and settles like the zero-acquisition
                # rows — an honest gap the coverage ledger reports and finalization closes
                # ``needs_review``, instead of an obligation no dispatch could ever discharge.
                source_keys = tuple(
                    source_key
                    for source_key in authorized
                    if _source_can_request(source_key, field_key)
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
            source_keys = tuple(
                dict.fromkeys(
                    source for authority in authorities for source in authority.source_keys
                )
            )
            committee_source_keys = (
                (PEOPLE_SOURCE_KEY,)
                if PEOPLE_SOURCE_KEY in allowed_sources
                and first.privacy_policy.committee_discovery_allowed
                else ()
            )
            admitted_sources = (*source_keys, *committee_source_keys)
            if not admitted_sources:
                # Every admitted field lost its whole authority to the requestability intersection
                # and no committee source is authorized either: this launch could dispatch nothing
                # at all. Refuse it here, loudly, rather than emitting a selection with no admitted
                # source for the envelope contract to reject as a shape error.
                raise AccountResearchFleetLaunchError(
                    "no admitted account field can be requested from any authorized source"
                )
            field_plan_sha = _sha({"field_keys": field_keys})
            source_plan_sha = _sha(source_plan_values)
            request_sha = _sha(
                {
                    "workspace_id": request.workspace_id,
                    "project_id": project_run.project_id,
                    "product_id": project_run.product_id,
                    "project_run_id": str(request.project_run_id),
                    "discovery_receipt": discovery_receipt.model_dump(mode="json"),
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
                    "committee_source_keys": list(committee_source_keys),
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
                discovery_receipt=discovery_receipt,
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
                committee_source_keys=committee_source_keys,
                research_questions=questions,
                # These are references, not typed policy slots. Two slots can legitimately point
                # at the same shared policy (the browser's default profile currently uses
                # ``"default"`` for both freshness and recursion), so flatten them into a stable
                # unique set before validating the selection envelope.
                policy_refs=tuple(
                    dict.fromkeys(
                        (
                            f"account-research-launch:{request_sha}",
                            first.effort_policy.freshness_policy_ref,
                            first.effort_policy.recursion_policy_ref,
                            (
                                "research-privacy:"
                                f"{_sha(first.privacy_policy.model_dump(mode='json'))}"
                            ),
                            request.supervisor_policy.policy_ref,
                        )
                    )
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
                # The **human who confirmed the directive**, read from the directive row — not the
                # identity that happens to be invoking the launch. Its pair, ``confirmed_at``, is
                # already read from there, and the two must describe one act.
                #
                # Before the Lane B ⇄ Lane D join this was ``actor``, and the two agreed by luck:
                # the launcher's caller was the same user. B4 makes the launching invoker a
                # *service* principal whenever the deepagent launches from a model-planned node
                # (Lane B ruling 8 — a worker executes an approved act without becoming its
                # approver), so ``actor`` would now write ``svc_execution_worker`` into a field
                # meaning "who approved this spend", beside a timestamp of when the human did.
                # The receipt is the human's; the worker's identity is already recorded as the
                # fleet row's creator and in the C5 journal.
                confirmed_by=directive.confirmed_by,
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
                operations=(ResearchOperationKind.ACCOUNT_PROFILE,)
                + ((ResearchOperationKind.COMMITTEE_DISCOVERY,) if committee_source_keys else ()),
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
                    agent_profile_ref=ACCOUNT_RESEARCH_PROFILE_REF,
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
                # With budget controls off the caller's approved cap is an ignored courier field, so
                # honouring it here would be incoherent: it can be smaller than the per-account caps
                # this launch just handed out, and the envelope's own invariant ("a job budget
                # cannot exceed its run-wide cap") would then reject the launch with a validation
                # error — enforcement by the back door. The run-level cap becomes the server's
                # recomputed Σ instead: the honest record of the authority actually issued.
                budget_cap_cents=(
                    request.approved_budget_cap_cents if self._enforce_budget else estimated_cost
                ),
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
