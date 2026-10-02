"""M6A S1: selected-account Sumble v9 gap enrichment.

One operation is bound to the exact discovery seal, human tier decision, account, field plan,
observation window, provider contract, and spend authorization. Organization identity is acquired
once; jobs and confirmed technology are dependent snapshots. Claims are append-only and enter the
ordinary merge/corroboration substrate independently of Exa claims.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr
from sqlalchemy import text

from clue_api.comprehensive_research_contract import COMPREHENSIVE_ACCOUNT_FIELD_SOURCES
from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader
from clue_api.sumble_claim_materialization import (
    SumbleClaimMaterializer,
    SumbleFieldDisposition,
)
from clue_config import Secrets, Settings
from clue_core import (
    AccountGapFieldPlan,
    AccountGapFieldResult,
    AccountGapFieldState,
    AccountGapOperation,
    AccountGapOperationState,
    AccountGapReason,
    AccountGapRequest,
    AccountGapSnapshot,
    AccountGapSnapshotState,
    AccountGapSpendOutcome,
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    FreshnessState,
    ProjectPhase,
    ProjectRunId,
    ResearchScope,
    new_account_gap_operation_id,
)
from clue_core.entity_research import EntityResearchJobAuthorization
from clue_db import ConnFactory, transaction
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    claims_for,
    current_value,
    # One species derivation for the whole platform (it resolves through
    # ``core.resolve_research_scope`` over the effective registry), so the gap economics and the
    # lens that renders the resulting claims never disagree about what a field's species is.
    field_species,
    get_effective_field,
)
from clue_research.discovery_scoring.tiering import (
    ACCOUNT_RESEARCH_ELIGIBLE_TIERS,
    TIER_CLAIM_MAX_SOURCE_TIER,
    TIER_FIELD,
)
from clue_research.durable import (
    AccountGapFieldWindowConflict,
    AccountGapNotFound,
    AccountGapReplayConflict,
    DiscoverySealConflict,
    ProjectRunStatus,
    account_gap_window_field_owners,
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    claim_account_gap_operation,
    claim_account_gap_snapshot,
    find_account_gap_operation,
    find_account_gap_operation_for_fields,
    get_account_gap_operation,
    get_account_gap_snapshot,
    get_project_run,
    list_account_gap_field_results,
    list_account_gap_snapshots,
    put_account_gap_field_result,
    quarantine_dispatching_account_gap_snapshots,
    reserve_account_gap_operation,
    reserve_account_gap_snapshot,
    terminal_now,
    update_account_gap_operation,
    update_account_gap_snapshot,
)
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.durable.spend_posture import cap_refusal_is_enforced
from clue_research.identity import get_account, surviving_id
from clue_research.resolvers.http import ProviderResponseError
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_API_BASE,
    SUMBLE_API_VERSION,
    SUMBLE_SOURCE_KEYS,
    TECH_STACK_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
    SumbleJobsResponse,
    SumbleOrganizationsResponse,
    SumbleSnapshot,
    SumbleSpendOutcomeUnknown,
    SumbleTechStackResponse,
    engineering_jobs_request,
    matched_organization_id,
    organization_request,
    sumble_action_supports_field,
)
from clue_storage import StorageBackend, content_address

SUMBLE_V9_CONTRACT_VERSION: Final = (
    "sumble-v9-openapi-c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c"
)
SUMBLE_ACCOUNT_GAP_FIELD_POLICY_VERSION: Final = "sumble-account-gaps-v1"
SUMBLE_ACCOUNT_GAP_PRICING_VERSION: Final = "sumble-v9-credits-2026-08-03"

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20; see
#: :mod:`clue_research.durable.spend_posture`). Two distinct sites because they fail at opposite
#: ends of the money: the preflight one can still save a call, the dispatch one never can.
_SITE_GAP_PREFLIGHT: Final = "sumble_account_gap_preflight"
_SITE_GAP_DISPATCH: Final = "sumble_account_gap_dispatch"

_EMPLOYEE = "core.employee_count"
_DOMAIN = "core.primary_domain"
_INDUSTRY = "core.industry"
_HQ = "core.hq_location"
_HIRING = "account.hiring_velocity_eng"
_TECH = "core.primary_tech_stack"

#: Which Sumble source owns which field — derived from the frozen §3.1 ownership table so this
#: compiler and the contract can never disagree (Slice-A carry-forward). ``core.primary_domain``
#: is the one deliberate addition: it is canonical identity truth outside the 21-field profile
#: that the organization action has always answered.
_SOURCE_BY_FIELD: Final[Mapping[str, str]] = MappingProxyType(
    {
        **{
            field_key: next(source for source in sources if source in SUMBLE_SOURCE_KEYS)
            for field_key, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items()
            if any(source in SUMBLE_SOURCE_KEYS for source in sources)
        },
        _DOMAIN: ORGANIZATIONS_SOURCE_KEY,
    }
)


def _requestable(field_key: str) -> bool:
    """Whether the pinned v9 action that owns ``field_key`` can actually ask for it.

    §3.1 grants ``sumble_organizations`` seven account rows; its pinned v9 organization action
    supports three of them (plus ``core.primary_domain``). A row it owns but cannot request is
    never faked and never crashes ``organization_request`` — it settles as an honest
    ``confirmed_missing`` so the field's next authorized source, or an honest empty, takes over.
    """

    source_key = _SOURCE_BY_FIELD.get(field_key)
    return source_key is not None and sumble_action_supports_field(field_key, source_key)


def _organization_request_fields(field_keys: Sequence[str]) -> tuple[str, ...]:
    """The subset of ``field_keys`` the v9 organization action may put on the wire."""

    return tuple(
        key
        for key in field_keys
        if _SOURCE_BY_FIELD.get(key) == ORGANIZATIONS_SOURCE_KEY and _requestable(key)
    )


def _authorized_provider_credit_cap(
    provider_credit_cap: int, *, bounded: int, enforce_budget: bool
) -> int:
    """The credit cap this request is actually reserved against.

    Enforcing posture: the caller's cap, unchanged (a cap below the bounded worst case is refused
    before this is ever consulted). Record-only posture (the 2026-08-20 ruling): the refusal is
    skipped, so the call *will* go out and may be charged the full bounded maximum — the
    reservation is therefore raised to that maximum rather than weakening the ledger's
    ``charged <= reserved`` invariant. Pure and deterministic, because
    :class:`SumbleAccountGapStarter` must reach the same number when it checks a replay's stored
    authorization against the arguments it was handed again.
    """

    if enforce_budget or provider_credit_cap >= bounded:
        return provider_credit_cap
    return bounded


class SumbleAccountGapError(RuntimeError):
    pass


class SumbleAccountGapEligibilityError(SumbleAccountGapError):
    """Any reason this exact request may not be compiled into a provider dispatch."""


class SumbleAccountGapNotEligible(SumbleAccountGapEligibilityError):
    """The narrow member of that family FI-2 §6.3(b) governs: the field is already answered.

    Split out because the two halves of the family want opposite handling on the M8D path. This
    one is a statement about the *request*: the workspace already holds a confident, fresh,
    conflict-free answer, so there is nothing to buy — a zero-spend, zero-state refusal the agent
    repairs by dropping the field, choosing another admitted source, or finalizing with an honest
    gap (the model-repairable R10 species). Every other ``SumbleAccountGapEligibilityError`` is a
    statement about the *world* — job authority lost, discovery seal conflicted, account not the
    canonical survivor, a field mis-declared — which no choice of the agent's can repair, and
    which therefore keeps propagating and suspending the job.
    """


class SumbleAccountGapFieldsUnrequestable(SumbleAccountGapNotEligible):
    """No requested field can be put on any pinned v9 Sumble wire.

    A statement about the *request*, so it is deliberately the model-repairable species: the agent
    drops those fields, chooses another admitted source, or finalizes with an honest gap. Paying
    an organization credit for a call whose whole field set the action cannot even ask about would
    buy nothing. A request that mixes requestable and unrequestable fields is **not** refused: it
    proceeds for what it can buy and settles the rest as ``confirmed_missing``.
    """


class SumbleAccountGapFieldAlreadyAcquired(SumbleAccountGapNotEligible):
    """This window already bought these fields for this account, so there is nothing to re-buy.

    The observation window is per *project run*, not per job — that is the anti-double-spend rule,
    and cross-job reuse inside a run is the point of it. The durable
    ``account_gap_field_no_overlap`` trigger enforces one purchase per
    ``(workspace, account, field, window)``; ``find_account_gap_operation_for_fields`` only rejoins
    an *exactly equal* field set, so a later job asking for a strict subset (or any overlapping
    set) of an earlier job's fields used to walk past the rejoin and straight into that trigger.
    Live on 2026-08-20, job ``3cc0a4f2`` asked for ``core.hq_location`` alone after job
    ``eea48931`` had bought ``core.employee_count`` + ``core.hq_location`` together: the raw
    ``DBAPIError`` escaped as ``execution_failed`` and paused the whole job.

    It is a statement about the *request*, so it is the model-repairable species: the agent reads
    the answer the owning operation already produced (``read_account_research_state`` serves the
    claim), drops the field, chooses another admitted source, or finalizes with an honest gap.
    Re-buying it is never the repair — the ledger already holds that purchase's outcome, including
    an honest ``confirmed_missing`` or an unresolved ``conflict``.
    """


def _already_acquired_detail(
    *,
    requested: Sequence[str],
    owning_field_sets: Sequence[Sequence[str]],
) -> str:
    """Name the bought fields AND the exact set to re-ask, which is the only legal exit.

    An already-bought pair stays OUTSTANDING for a later job until that job attempts it, and
    ``assess_account_coverage`` refuses to close while anything is outstanding. The one attempt
    that succeeds is re-asking an owning operation's *exact* field set: the starter rejoins it
    before compiling anything and replays it zero-spend, landing a result under the new job's own
    tool request. Live job ``3cc0a4f2`` proved that a refusal naming only the overlap is not
    enough — the agent read state, tried three subsets, and never found this move.
    """

    acquired = sorted(set(requested) & {key for fields in owning_field_sets for key in fields})
    sets = " or ".join(f"[{', '.join(fields)}]" for fields in owning_field_sets)
    return (
        f"already acquired in this observation window: {', '.join(acquired)} — that purchase is "
        f"durable and cannot be repeated. This window's operations acquired exactly {sets}; "
        "re-ask one of those exact field sets to replay its durable outcome at zero spend (that "
        "is what makes the field terminal for coverage), or finalize with the honest gap. "
        "Re-asking a subset or a different overlapping set can never succeed."
    )


class SumbleAccountGapOutcome(StrEnum):
    COMPLETED = "completed"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class SumbleAccountGapPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = SUMBLE_ACCOUNT_GAP_FIELD_POLICY_VERSION
    eligible_tiers: frozenset[str] = ACCOUNT_RESEARCH_ELIGIBLE_TIERS
    low_confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    maximum_fields: int = Field(default=6, ge=1)
    jobs_limit: int = Field(default=1, ge=1, le=200)


DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY = SumbleAccountGapPolicy()


class SumbleAccountGapPreflight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    request: AccountGapRequest
    organization_body: dict[str, JsonValue]
    bounded_provider_units: Decimal
    maximum_cost_cents: Decimal


class SumbleAccountGapResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: SumbleAccountGapOutcome
    operation: AccountGapOperation
    claim_ids: tuple[str, ...] = ()
    provider_calls: int = 0


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _wire_fingerprint(
    *, parent_fingerprint: str, source_key: str, method: str, path: str, body: object
) -> str:
    return hashlib.sha256(
        _json_bytes(
            {
                "parent_fingerprint": parent_fingerprint,
                "source_key": source_key,
                "method": method,
                "path": path,
                "body": body,
                "provider_api_version": SUMBLE_API_VERSION,
                "provider_contract_version": SUMBLE_V9_CONTRACT_VERSION,
            }
        )
    ).hexdigest()


async def _exact_selected_tier_claim(
    *,
    conn: Any,
    workspace_id: str,
    account_id: EntityId,
    project_run_id: ProjectRunId,
    batch_id: object,
    seal_sha256: str,
    icp_key: str,
    icp_version: int,
    policy: SumbleAccountGapPolicy,
) -> Claim:
    matching = []
    for claim in await claims_for(
        conn,
        account_id,
        TIER_FIELD,
        scope=WorkspaceScope.for_workspace(workspace_id),
    ):
        value = claim.value_json
        if not isinstance(value, dict):
            continue
        if (
            claim.source_tier <= TIER_CLAIM_MAX_SOURCE_TIER
            and value.get("decision_basis") == "discovery_criteria"
            and value.get("project_run_id") == str(project_run_id)
            and value.get("discovery_batch_id") == str(batch_id)
            and value.get("discovery_seal_sha256") == seal_sha256
            and value.get("icp_key") == icp_key
            and value.get("icp_version") == icp_version
            and value.get("disposition") == "selected"
            and value.get("tier") in policy.eligible_tiers
        ):
            matching.append(claim)
    if len(matching) != 1:
        raise SumbleAccountGapEligibilityError(
            "account gap enrichment requires one exact live selected tier decision"
        )
    return matching[0]


async def compile_sumble_account_gap_preflight(
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    field_expected_value_credits: Mapping[str, Decimal],
    provider_credit_cap: int,
    allow_unbounded_tech: bool,
    observation_window: str,
    storage: StorageBackend,
    cents_per_credit: Decimal = Decimal(0),
    conn_factory: ConnFactory = transaction,
    policy: SumbleAccountGapPolicy = DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY,
    entity_research_job_id: UUID | None = None,
    enforce_budget: bool = True,
) -> SumbleAccountGapPreflight:
    """Compile only documented native fields with an evidence-backed gap and explicit value.

    ``enforce_budget`` is the FI pilot budget-controls switch. The capacity probe below is
    dual-purpose: it proves the run/job *authority* (which holds in both modes) and, with a
    zero proposal, would still refuse when prior spend already exceeds the cap. Only that
    money half goes inert when controls are off.
    """

    if cents_per_credit < 0:
        raise SumbleAccountGapEligibilityError("Sumble cents-per-credit cannot be negative")
    field_keys = tuple(sorted(field_expected_value_credits))
    # Only requestable fields consume the per-call cap: an unrequestable §3.1 row costs no
    # provider call and settles as an honest unresolved plan row, so a comprehensive request
    # naming all nine Sumble-owned fields (five requestable under the pinned v9 actions) must
    # not be refused on raw count. An all-unrequestable set is refused separately below.
    requestable_count = sum(1 for key in field_keys if _requestable(key))
    if not field_keys or requestable_count > policy.maximum_fields:
        raise SumbleAccountGapEligibilityError("invalid Sumble account-gap field count")
    unknown = sorted(set(field_keys) - set(_SOURCE_BY_FIELD))
    if unknown:
        raise SumbleAccountGapEligibilityError(
            f"field(s) are not approved for Sumble S1: {', '.join(unknown)}"
        )
    if not any(_requestable(key) for key in field_keys):
        raise SumbleAccountGapFieldsUnrequestable(
            "the pinned Sumble v9 actions cannot request any selected field: "
            f"{', '.join(field_keys)}"
        )
    values = {key: Decimal(field_expected_value_credits[key]) for key in field_keys}
    if any(value <= 0 for value in values.values()):
        raise SumbleAccountGapEligibilityError(
            "every Sumble-selected field needs positive expected value credits"
        )
    if (_TECH in field_keys) != allow_unbounded_tech:
        raise SumbleAccountGapEligibilityError(
            "confirmed-tech requires, and alone permits, explicit unbounded-call approval"
        )

    reader = DbSealedDiscoveryAccountManifestReader(storage=storage, conn_factory=conn_factory)
    discovery_receipt = None
    async with conn_factory() as conn:
        run = await get_project_run(conn, project_run_id)
        if run is None or run.workspace_id != workspace_id:
            raise SumbleAccountGapEligibilityError("Sumble account-gap project run does not exist")
        if entity_research_job_id is not None:
            exact_job = (
                await conn.execute(
                    text(
                        "SELECT authorization_json FROM entity_research_job WHERE job_id=:job_id "
                        "AND subject_type='account' AND subject_entity_id=:account_id "
                        "AND workspace_id=:workspace_id AND project_id=:project_id "
                        "AND project_run_id=:project_run_id"
                    ),
                    {
                        "job_id": entity_research_job_id,
                        "account_id": account_id,
                        "workspace_id": workspace_id,
                        "project_id": run.project_id,
                        "project_run_id": project_run_id,
                    },
                )
            ).scalar_one_or_none()
            if exact_job is None:
                raise SumbleAccountGapEligibilityError(
                    "Sumble account-gap enrichment requires the exact Account research job"
                )
            job_authorization = EntityResearchJobAuthorization.model_validate(exact_job)
            discovery_receipt = job_authorization.selection.discovery_receipt
        if entity_research_job_id is None:
            if run.status is not ProjectRunStatus.ACTIVE:
                raise SumbleAccountGapEligibilityError(
                    "Sumble account-gap enrichment requires an active project run"
                )
            if run.phase is not ProjectPhase.DEEP:
                raise SumbleAccountGapEligibilityError(
                    "historical Sumble account-gap enrichment requires an active deep-phase run"
                )
    if entity_research_job_id is not None:
        # M8D account research is an independently confirmed action, not a projection of the
        # outer project phase.  Prove the exact running R6 job before compiling any provider
        # request.  The durable reservation repeats this check in the transaction that inserts
        # the operation, so a cancellation between preflight and reservation still fails closed.
        try:
            async with conn_factory() as conn:
                await require_provider_spend_capacity(
                    conn,
                    project_run_id=project_run_id,
                    proposed_cents=Decimal(0),
                    allowed_phases=frozenset({ProjectPhase.DEEP}),
                    entity_research_job_id=entity_research_job_id,
                    enforce_budget=enforce_budget,
                )
        except ProviderSpendGuardError as exc:
            raise SumbleAccountGapEligibilityError(
                "Sumble account-gap enrichment lacks exact live entity-research job authority"
            ) from exc
    try:
        sealed = await reader.read(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            discovery_receipt=discovery_receipt,
        )
    except DiscoverySealConflict as exc:
        raise SumbleAccountGapEligibilityError(
            "Sumble account-gap enrichment requires an intact discovery seal"
        ) from exc
    if sealed is None or account_id not in set(sealed.account_ids):
        raise SumbleAccountGapEligibilityError("account is absent from the exact discovery seal")

    field_plans: list[AccountGapFieldPlan] = []
    async with conn_factory() as conn:
        if await surviving_id(conn, account_id, EntityType.ACCOUNT) != account_id:
            raise SumbleAccountGapEligibilityError("account is not the canonical survivor")
        account = await get_account(conn, account_id)
        if account is None or account.workspace_id != workspace_id or not account.primary_domain:
            raise SumbleAccountGapEligibilityError(
                "account lacks a workspace-local canonical primary domain"
            )
        tier_claim = None
        if entity_research_job_id is None:
            tier_claim = await _exact_selected_tier_claim(
                conn=conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                batch_id=sealed.discovery_batch_id,
                seal_sha256=sealed.seal_sha256,
                icp_key=run.icp_key,
                icp_version=run.icp_version,
                policy=policy,
            )
        # FI-2 §6.3 species check.  The freshness ladder below reads the *workspace-merged*
        # current value, so "already answered, don't re-buy" is only a correct thing to say about
        # a **project_neutral** field: a project-relative value is one project's answer, and
        # refusing another project's enrichment because that answer exists would hand it the wrong
        # project's fact.  Every field in ``_SOURCE_BY_FIELD`` is a structured world fact and
        # resolves neutral today — the test asserts that through the registry rather than assuming
        # it.  It is nonetheless *enforced* here, because the reachable way to break it is a
        # declaration change (a new Sumble-approved field, or a re-declared existing one, carrying
        # ``research_scope=project_relative``): the ladder would keep working and quietly mean the
        # wrong thing.  This refusal turns that into a visible failure — deliberately the *base*
        # ``SumbleAccountGapEligibilityError``, so on the M8D path it propagates and suspends the
        # job rather than becoming a governed turn: a mis-declared field is a broken declaration,
        # not a request the agent can repair by choosing another field.
        # (Note: it cannot be broken by a *workspace* override — ``register_workspace_field``
        # accepts only ``client.*`` keys and forces the neutral species.)
        species = await field_species(conn, workspace_id=workspace_id, field_keys=list(field_keys))
        relative = sorted(
            key
            for key in field_keys
            # Fail closed on an unresolvable species: not-neutral is the refusing answer, and
            # "we cannot tell" must not buy the fresh-skip.  Unreachable today (``field_species``
            # answers for every declared field, and every Sumble field is declared).
            if species.get(key, ResearchScope.PROJECT_RELATIVE) is not ResearchScope.PROJECT_NEUTRAL
        )
        if relative:
            raise SumbleAccountGapEligibilityError(
                "Sumble account-gap enrichment answers project-neutral world facts only; "
                f"declared project-relative: {', '.join(relative)}"
            )
        # Pre-check the durable anti-double-spend rule *before* compiling a request that the
        # ``account_gap_field_no_overlap`` trigger would refuse with a raw database error. The
        # trigger stays the authority (this read can be raced, and the reservation converts its
        # own raise); this exists so the ordinary case — a later job in the same project run
        # asking again for a field an earlier job already bought, which the exact-field-set rejoin
        # cannot serve — is a plain governed refusal instead of a suspended job.
        #
        # The refusal is whole-request even when only some fields overlap: dropping the bought
        # ones silently would change the field set the agent authorized, and the agent can simply
        # re-ask for the remainder. The message names exactly which fields to drop.
        owners = await account_gap_window_field_owners(
            conn,
            workspace_id=workspace_id,
            account_id=account_id,
            observation_window=observation_window,
            field_keys=field_keys,
        )
        if owners:
            raise SumbleAccountGapFieldAlreadyAcquired(
                _already_acquired_detail(requested=field_keys, owning_field_sets=owners)
            )
        for field_key in field_keys:
            source_key = _SOURCE_BY_FIELD[field_key]
            if not _requestable(field_key):
                # Consumer obligation (contract §3.1 docstring): intersect ownership with what the
                # pinned action can request *before* dispatch. The plan keeps the field so the
                # durable ledger explains it and the R4 projection has a row for every requested
                # key; ``_materialize`` settles it ``confirmed_missing``. No provider attribute is
                # requested for it, so it costs nothing, and the registry's ``tier_plan`` is not
                # consulted: that check gates *buying* a field from a source, and this field is
                # not being bought from anyone.
                field_plans.append(
                    AccountGapFieldPlan(
                        field_key=field_key,
                        source_key=source_key,
                        reason=AccountGapReason.MISSING,
                        expected_value_credits=values[field_key],
                        basis_claim_ids=(),
                    )
                )
                continue
            definition = await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(workspace_id),
                field_key=field_key,
            )
            if definition is None or source_key not in definition.field_def.tier_plan:
                raise SumbleAccountGapEligibilityError(
                    f"field plan does not select {source_key} for {field_key}"
                )
            raw_claims = await claims_for(
                conn,
                account_id,
                field_key,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            merged = await current_value(
                conn,
                account_id,
                field_key,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            if merged is None:
                reason = AccountGapReason.MISSING
                basis = tuple(claim.id for claim in raw_claims)
            elif merged.conflict:
                reason = AccountGapReason.CONFLICT
                basis = merged.conflicting_claim_ids
            elif merged.provenance.confidence < policy.low_confidence_threshold:
                reason = AccountGapReason.LOW_CONFIDENCE
                basis = (merged.provenance.claim_id,)
            elif merged.freshness_state is not FreshnessState.FRESH:
                # FI-2 §6.3(a): confidence is not currency.  A confidently-resolved fact that is
                # past its field's TTL is exactly what a re-buy is *for* — the old code read only
                # confidence and conflict, so it refused to refresh a fact everybody knew was
                # expired.  The stale winner is the durable basis for the refresh.
                reason = AccountGapReason.STALE
                basis = (merged.provenance.claim_id,)
            elif not merged.evidence_backed:
                # The same span rule the completeness reader satisfies a field with
                # (``CurrentValue.evidence_backed`` — one predicate, not two).  A fresh,
                # confident, unconflicted winner carrying *no evidence span* is not an answer:
                # refusing to re-buy it while nothing can ever count it as satisfied left the
                # field permanently outstanding, so the account could never settle.  It is a gap
                # like any other, and it is bought like any other; the span-less winner is the
                # durable basis for the purchase.
                reason = AccountGapReason.NO_EVIDENCE
                basis = (merged.provenance.claim_id,)
            else:
                # The one refusal §6.3(b) converts into a governed agent turn: the ladder found
                # the field already answered.  Everything else in this function stays the base
                # class and keeps suspending.
                raise SumbleAccountGapNotEligible(
                    f"{field_key} is already confidently resolved, fresh, evidence-backed, and "
                    "without an open conflict"
                )
            field_plans.append(
                AccountGapFieldPlan(
                    field_key=field_key,
                    source_key=source_key,
                    reason=reason,
                    expected_value_credits=values[field_key],
                    basis_claim_ids=basis,
                )
            )

    organization_body, organization_max = organization_request(
        account.primary_domain, field_keys=_organization_request_fields(field_keys)
    )
    bounded = organization_max + (policy.jobs_limit if _HIRING in field_keys else 0)
    if provider_credit_cap < bounded and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_GAP_PREFLIGHT,
        reason="cap_below_bounded_maximum",
        amounts={"provider_credit_cap": provider_credit_cap, "bounded_maximum": bounded},
    ):
        raise SumbleAccountGapEligibilityError(
            f"provider cap {provider_credit_cap} is below bounded request maximum {bounded}"
        )
    authorized_cap = _authorized_provider_credit_cap(
        provider_credit_cap, bounded=bounded, enforce_budget=enforce_budget
    )
    expected = sum(values.values(), Decimal(0))
    if expected < authorized_cap and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_GAP_PREFLIGHT,
        reason="value_below_authorized_cap",
        amounts={"expected_value_credits": expected, "provider_credit_cap": authorized_cap},
    ):
        raise SumbleAccountGapEligibilityError(
            "expected field value does not justify the authorized provider-credit cap"
        )
    request = AccountGapRequest(
        workspace_id=workspace_id,
        project_id=run.project_id,
        project_run_id=project_run_id,
        entity_research_job_id=entity_research_job_id,
        icp_key=run.icp_key,
        icp_version=run.icp_version,
        discovery_batch_id=sealed.discovery_batch_id,
        discovery_seal_sha256=sealed.seal_sha256,
        account_id=account_id,
        primary_domain=account.primary_domain,
        tier_claim_id=tier_claim.id if tier_claim is not None else None,
        provider_api_version=SUMBLE_API_VERSION,
        provider_contract_version=SUMBLE_V9_CONTRACT_VERSION,
        pricing_policy_version=SUMBLE_ACCOUNT_GAP_PRICING_VERSION,
        field_policy_version=policy.version,
        observation_window=observation_window,
        fields=tuple(field_plans),
        provider_credit_cap=authorized_cap,
        expected_value_credits=expected,
        money_budget_cap_cents=Decimal(authorized_cap) * cents_per_credit,
        allow_unbounded_tech=allow_unbounded_tech,
    )
    return SumbleAccountGapPreflight(
        request=request,
        organization_body=organization_body,
        bounded_provider_units=Decimal(bounded),
        maximum_cost_cents=request.money_budget_cap_cents,
    )


class SumbleAccountGapCoordinator:
    """Crash-safe synchronous coordinator over independently durable Sumble snapshots."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        storage: StorageBackend,
        cents_per_credit: Decimal = Decimal(0),
        conn_factory: ConnFactory = transaction,
        policy: SumbleAccountGapPolicy = DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY,
        in_flight_grace_seconds: int = 60,
        client_factory: Callable[[int, Decimal], SumbleClient] | None = None,
        enforce_budget: bool = True,
    ) -> None:
        self._api_key = api_key
        self._storage = storage
        self._cents_per_credit = cents_per_credit
        self._conn_factory = conn_factory
        self._policy = policy
        self._in_flight_grace = timedelta(seconds=in_flight_grace_seconds)
        self._client_factory = client_factory or (
            lambda maximum, cents: SumbleClient(
                api_key=self._api_key,
                budget=SumbleCreditBudget(maximum=maximum),
                cents_per_credit=cents,
            )
        )
        self._materializer = SumbleClaimMaterializer(conn_factory=conn_factory)
        # FI pilot budget-controls: threaded from ``Settings.budget_controls_enabled`` at
        # the composition root and passed to the durable reservation, which stops raising
        # on the project-run cap while writing every ledger row unchanged.
        self._enforce_budget = enforce_budget

    async def start(
        self,
        preflight: SumbleAccountGapPreflight,
        *,
        before_dispatch: Callable[[AccountGapOperation], Awaitable[None]] | None = None,
    ) -> SumbleAccountGapResult:
        try:
            operation, _created = await self._reserve(preflight)
        except AccountGapFieldWindowConflict as conflict:
            # The pre-check lost a race with a concurrent create (or a caller reached the
            # coordinator without one). The reservation transaction rolled back, so this is still
            # zero-spend and zero-state; keep it the model-repairable species rather than letting
            # a raw DBAPIError suspend the job.
            raise SumbleAccountGapFieldAlreadyAcquired(
                f"already acquired in this observation window: {conflict} — that purchase is "
                "durable and cannot be repeated; re-ask the exact field set of the operation that "
                "bought it to replay its durable outcome at zero spend, or finalize with the "
                "honest gap"
            ) from conflict
        terminal = self._terminal_result(operation, replay=True)
        if terminal is not None:
            return terminal
        if operation.state is AccountGapOperationState.ACQUIRING:
            if (
                operation.updated_at
                and datetime.now(UTC) - operation.updated_at < self._in_flight_grace
            ):
                return SumbleAccountGapResult(
                    outcome=SumbleAccountGapOutcome.JOINED_IN_FLIGHT,
                    operation=operation,
                )
            async with self._conn_factory() as conn:
                quarantined = await quarantine_dispatching_account_gap_snapshots(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            if quarantined:
                return await self._mark_unknown(operation, "crash_after_possible_sumble_dispatch")
        elif operation.state in {
            AccountGapOperationState.PLANNED,
            AccountGapOperationState.FAILED_RETRYABLE,
        }:
            # M8D R5 binds the exact agent/tool cause after durable reservation and before any
            # snapshot dispatch can be claimed. Callback failure leaves the operation planned.
            if before_dispatch is not None:
                await before_dispatch(operation)
            async with self._conn_factory() as conn:
                claimed = await claim_account_gap_operation(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            if claimed is None:
                fresh = await self._get(operation)
                return SumbleAccountGapResult(
                    outcome=SumbleAccountGapOutcome.JOINED_IN_FLIGHT,
                    operation=fresh,
                )
            operation = claimed

        client = self._client_factory(
            operation.request.provider_credit_cap,
            self._cents_per_credit,
        )
        provider_calls = 0
        org_fields = _organization_request_fields(
            [str(item.field_key) for item in operation.request.fields]
        )
        try:
            org, called = await self._drive_snapshot(
                operation,
                source_key=ORGANIZATIONS_SOURCE_KEY,
                call=lambda: client.resolve_organization(
                    operation.request.primary_domain, field_keys=org_fields
                ),
            )
            provider_calls += called
            organization_id = matched_organization_id(org.payload)
            selected_sources = {item.source_key for item in operation.request.fields}
            snapshots: dict[str, SumbleSnapshot] = {ORGANIZATIONS_SOURCE_KEY: org}
            if organization_id is None:
                for source_key in selected_sources - {ORGANIZATIONS_SOURCE_KEY}:
                    await self._mark_not_applicable(operation, source_key)
            else:
                if JOBS_SOURCE_KEY in selected_sources:
                    body, maximum = engineering_jobs_request(
                        organization_id, limit=self._policy.jobs_limit
                    )
                    await self._ensure_dependent_snapshot(
                        operation,
                        source_key=JOBS_SOURCE_KEY,
                        method="POST",
                        path="/jobs",
                        body=body,
                        reserved=Decimal(maximum),
                        unbounded=False,
                    )
                    jobs, called = await self._drive_snapshot(
                        operation,
                        source_key=JOBS_SOURCE_KEY,
                        call=lambda: client.engineering_jobs(
                            organization_id, limit=self._policy.jobs_limit
                        ),
                    )
                    provider_calls += called
                    snapshots[JOBS_SOURCE_KEY] = jobs
                if TECH_STACK_SOURCE_KEY in selected_sources:
                    await self._ensure_dependent_snapshot(
                        operation,
                        source_key=TECH_STACK_SOURCE_KEY,
                        method="GET",
                        path=f"/organizations/{organization_id}/techs",
                        body=None,
                        reserved=Decimal(0),
                        unbounded=True,
                    )
                    tech, called = await self._drive_snapshot(
                        operation,
                        source_key=TECH_STACK_SOURCE_KEY,
                        call=lambda: client.tech_stack(organization_id, allow_unbounded=True),
                    )
                    provider_calls += called
                    snapshots[TECH_STACK_SOURCE_KEY] = tech
        except ProviderResponseError as exc:
            if exc.is_deterministic_rejection:
                return await self._mark_provider_rejected(
                    operation, error=exc, provider_calls=provider_calls + 1
                )
            return await self._mark_unknown(
                operation,
                "sumble_paid_dispatch_unreconciled",
                provider_calls=provider_calls + 1,
            )
        except Exception:
            return await self._mark_unknown(
                operation,
                "sumble_paid_dispatch_unreconciled",
                provider_calls=provider_calls + 1,
            )

        durable_snapshots = await self._load_all_snapshots(operation)
        charged = sum(
            (Decimal(item.credits_used) for item in durable_snapshots.values()), Decimal(0)
        )
        cost = sum((item.cost_cents for item in durable_snapshots.values()), Decimal(0))
        # The money is already gone by the time this comparison can be made: ``/techs`` has no
        # caller-side limit, so refusing here saves nothing and only destroys data we were billed
        # for (it did exactly that live on 2026-08-19). Under the record-only posture the true
        # charge is recorded and the operation is allowed to keep what it bought.
        if charged > operation.request.provider_credit_cap and cap_refusal_is_enforced(
            self._enforce_budget,
            site=_SITE_GAP_DISPATCH,
            reason="charge_above_authorized_cap",
            amounts={
                "provider_units_charged": charged,
                "provider_credit_cap": operation.request.provider_credit_cap,
                "cost_cents_charged": cost,
            },
        ):
            await self._fail_fields(operation, "sumble_unbounded_charge_exceeded_authorized_cap")
            receipt_key = await self._receipt(operation, durable_snapshots, claim_ids=())
            failed = operation.model_copy(
                update={
                    "state": AccountGapOperationState.FAILED_TERMINAL,
                    "spend_outcome": AccountGapSpendOutcome.CHARGED,
                    "receipt_manifest_key": receipt_key,
                    "provider_units_charged": charged,
                    "cost_cents_charged": cost,
                    "failure_code": "sumble_unbounded_charge_exceeded_authorized_cap",
                    "terminal_at": terminal_now(),
                }
            )
            async with self._conn_factory() as conn:
                stored = await update_account_gap_operation(conn, operation=failed)
            return SumbleAccountGapResult(
                outcome=SumbleAccountGapOutcome.FAILED_TERMINAL,
                operation=stored,
                provider_calls=provider_calls,
            )

        async with self._conn_factory() as conn:
            current = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise AccountGapNotFound("Sumble account-gap materialization")
            operation = await update_account_gap_operation(
                conn,
                operation=current.model_copy(
                    update={"state": AccountGapOperationState.MATERIALIZING}
                ),
            )
        claim_ids = await self._materialize(operation, durable_snapshots)
        receipt_key = await self._receipt(operation, durable_snapshots, claim_ids=claim_ids)
        completed = operation.model_copy(
            update={
                "state": AccountGapOperationState.SUCCEEDED,
                "spend_outcome": AccountGapSpendOutcome.CHARGED,
                "receipt_manifest_key": receipt_key,
                "provider_units_charged": charged,
                "cost_cents_charged": cost,
                "terminal_at": terminal_now(),
            }
        )
        async with self._conn_factory() as conn:
            stored = await update_account_gap_operation(conn, operation=completed)
        return SumbleAccountGapResult(
            outcome=SumbleAccountGapOutcome.COMPLETED,
            operation=stored,
            claim_ids=claim_ids,
            provider_calls=provider_calls,
        )

    def _terminal_result(
        self, operation: AccountGapOperation, *, replay: bool
    ) -> SumbleAccountGapResult | None:
        if operation.state is AccountGapOperationState.SUCCEEDED:
            return SumbleAccountGapResult(
                outcome=(
                    SumbleAccountGapOutcome.REPLAYED
                    if replay
                    else SumbleAccountGapOutcome.COMPLETED
                ),
                operation=operation,
            )
        if operation.state is AccountGapOperationState.SPEND_OUTCOME_UNKNOWN:
            return SumbleAccountGapResult(
                outcome=SumbleAccountGapOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=operation,
            )
        if operation.state in {
            AccountGapOperationState.FAILED_TERMINAL,
            AccountGapOperationState.CANCELLED,
        }:
            return SumbleAccountGapResult(
                outcome=SumbleAccountGapOutcome.FAILED_TERMINAL,
                operation=operation,
            )
        return None

    async def _reserve(
        self, preflight: SumbleAccountGapPreflight
    ) -> tuple[AccountGapOperation, bool]:
        request = preflight.request
        async with self._conn_factory() as conn:
            existing = await find_account_gap_operation(
                conn,
                workspace_id=request.workspace_id,
                account_id=request.account_id,
                request_fingerprint=request.request_fingerprint,
                observation_window=request.observation_window,
            )
            if existing is not None:
                return existing, False
            input_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=request.canonical_bytes(),
                media_type="application/json",
                source_key=ORGANIZATIONS_SOURCE_KEY,
                source_url=f"{SUMBLE_API_BASE}/organizations",
            )
            org_wire = {
                "method": "POST",
                "path": "/organizations",
                "body": preflight.organization_body,
            }
            request_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=_json_bytes(org_wire),
                media_type="application/json",
                source_key=ORGANIZATIONS_SOURCE_KEY,
                source_url=f"{SUMBLE_API_BASE}/organizations",
            )
            operation = AccountGapOperation(
                operation_id=new_account_gap_operation_id(),
                request=request,
                request_fingerprint=request.request_fingerprint,
                state=AccountGapOperationState.PLANNED,
                spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                input_artifact_key=input_key,
                provider_units_reserved=Decimal(request.provider_credit_cap),
                cost_cents_reserved=preflight.maximum_cost_cents,
                unbounded_call_approved=request.allow_unbounded_tech,
            )
            org_snapshot = AccountGapSnapshot(
                operation_id=operation.operation_id,
                workspace_id=request.workspace_id,
                account_id=request.account_id,
                source_key=ORGANIZATIONS_SOURCE_KEY,
                request_fingerprint=_wire_fingerprint(
                    parent_fingerprint=request.request_fingerprint,
                    source_key=ORGANIZATIONS_SOURCE_KEY,
                    method="POST",
                    path="/organizations",
                    body=preflight.organization_body,
                ),
                state=AccountGapSnapshotState.PLANNED,
                spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                request_artifact_key=request_key,
                provider_units_reserved=(
                    Decimal(
                        organization_request(
                            request.primary_domain,
                            field_keys=_organization_request_fields(
                                [str(item.field_key) for item in request.fields]
                            ),
                        )[1]
                    )
                ),
            )
            stored, created = await reserve_account_gap_operation(
                conn,
                operation=operation,
                snapshots=(org_snapshot,),
                enforce_budget=self._enforce_budget,
            )
            for key, kind in (
                (input_key, "sumble_gap_request"),
                (request_key, "sumble_org_request"),
            ):
                await self._bind(conn, stored, key, kind)
            return stored, created

    async def _get(self, operation: AccountGapOperation) -> AccountGapOperation:
        async with self._conn_factory() as conn:
            stored = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        if stored is None:
            raise AccountGapNotFound("Sumble account-gap operation")
        return stored

    async def _bind(
        self,
        conn: Any,
        operation: AccountGapOperation,
        artifact_key: str,
        kind: str,
    ) -> None:
        await bind_discovery_artifact_subject(
            conn,
            workspace_id=operation.request.workspace_id,
            artifact_key_value=artifact_key,
            subject_kind="account",
            subject_entity_id=operation.request.account_id,
            reference_kind=kind,
            reference_id=f"{operation.operation_id}:{kind}",
        )

    async def _ensure_dependent_snapshot(
        self,
        operation: AccountGapOperation,
        *,
        source_key: str,
        method: str,
        path: str,
        body: object,
        reserved: Decimal,
        unbounded: bool,
    ) -> AccountGapSnapshot:
        wire = {"method": method, "path": path, "body": body}
        async with self._conn_factory() as conn:
            existing = await get_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
            if existing is not None:
                return existing
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(wire),
                media_type="application/json",
                source_key=source_key,
                source_url=f"{SUMBLE_API_BASE}{path}",
            )
            snapshot = AccountGapSnapshot(
                operation_id=operation.operation_id,
                workspace_id=operation.request.workspace_id,
                account_id=operation.request.account_id,
                source_key=source_key,
                request_fingerprint=_wire_fingerprint(
                    parent_fingerprint=operation.request_fingerprint,
                    source_key=source_key,
                    method=method,
                    path=path,
                    body=body,
                ),
                state=AccountGapSnapshotState.PLANNED,
                spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                request_artifact_key=key,
                provider_units_reserved=reserved,
                unbounded_call_approved=unbounded,
            )
            stored, _ = await reserve_account_gap_snapshot(conn, snapshot=snapshot)
            await self._bind(conn, operation, key, f"{source_key}_request")
            return stored

    async def _drive_snapshot(
        self,
        operation: AccountGapOperation,
        *,
        source_key: str,
        call: Any,
    ) -> tuple[SumbleSnapshot, int]:
        async with self._conn_factory() as conn:
            row = await get_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
            if row is None:
                raise AccountGapNotFound(f"Sumble snapshot {source_key}")
            if row.state is AccountGapSnapshotState.SUCCEEDED:
                return await self._load_snapshot(row), 0
            claimed = await claim_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
        if claimed is None:
            raise AccountGapReplayConflict(f"Sumble snapshot {source_key} is already in flight")
        try:
            provider = await asyncio.to_thread(call)
        except SumbleSpendOutcomeUnknown:
            raise
        except Exception:
            raise
        body = _json_bytes(provider.payload)
        async with self._conn_factory() as conn:
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=body,
                media_type="application/json",
                source_key=source_key,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, key, f"{source_key}_response")
            stored = await update_account_gap_snapshot(
                conn,
                snapshot=claimed.model_copy(
                    update={
                        "state": AccountGapSnapshotState.SUCCEEDED,
                        "spend_outcome": AccountGapSpendOutcome.CHARGED,
                        "response_artifact_key": key,
                        "provider_request_id": provider.request_id,
                        "provider_units_charged": Decimal(provider.credits_used),
                        "credits_remaining": provider.credits_remaining,
                        "cost_cents_charged": provider.cost_cents,
                        "terminal_at": terminal_now(),
                    }
                ),
            )
        return provider.model_copy(update={"artifact_key": stored.response_artifact_key}), 1

    async def _load_snapshot(self, row: AccountGapSnapshot) -> SumbleSnapshot:
        if row.response_artifact_key is None or row.provider_request_id is None:
            raise AccountGapReplayConflict("successful Sumble snapshot lacks durable response")
        body = await self._storage.get(row.response_artifact_key)
        if not row.response_artifact_key.endswith(content_address(body)):
            raise AccountGapReplayConflict("Sumble snapshot artifact hash mismatch")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise AccountGapReplayConflict("Sumble snapshot artifact is not an object")
        model: type[BaseModel]
        if row.source_key == ORGANIZATIONS_SOURCE_KEY:
            model = SumbleOrganizationsResponse
        elif row.source_key == JOBS_SOURCE_KEY:
            model = SumbleJobsResponse
        elif row.source_key == TECH_STACK_SOURCE_KEY:
            model = SumbleTechStackResponse
        else:
            raise AccountGapReplayConflict("unknown Sumble snapshot source")
        parsed = model.model_validate(payload)
        if (
            parsed.id != row.provider_request_id
            or Decimal(parsed.credits_used) != row.provider_units_charged
        ):
            raise AccountGapReplayConflict("Sumble receipt differs from durable snapshot ledger")
        return SumbleSnapshot(
            source_key=row.source_key,  # type: ignore[arg-type]
            request_id=row.provider_request_id,
            credits_used=int(row.provider_units_charged),
            credits_remaining=row.credits_remaining or 0,
            payload=payload,
            cost_cents=row.cost_cents_charged,
            estimated_max_credits=(
                None if row.unbounded_call_approved else int(row.provider_units_reserved)
            ),
            unbounded_call_approved=row.unbounded_call_approved,
            artifact_key=row.response_artifact_key,
        )

    async def _load_all_snapshots(
        self, operation: AccountGapOperation
    ) -> dict[str, SumbleSnapshot]:
        async with self._conn_factory() as conn:
            rows = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        result: dict[str, SumbleSnapshot] = {}
        for row in rows:
            if row.state is AccountGapSnapshotState.SUCCEEDED:
                result[row.source_key] = await self._load_snapshot(row)
        return result

    async def _mark_not_applicable(self, operation: AccountGapOperation, source_key: str) -> None:
        path = f"dependency:{source_key}:no_matched_organization"
        await self._ensure_dependent_snapshot(
            operation,
            source_key=source_key,
            method="SKIP",
            path=path,
            body={"reason": "no_matched_sumble_organization"},
            reserved=Decimal(0),
            unbounded=False,
        )
        async with self._conn_factory() as conn:
            row = await get_account_gap_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
            if row is not None and row.state is AccountGapSnapshotState.PLANNED:
                await update_account_gap_snapshot(
                    conn,
                    snapshot=row.model_copy(
                        update={
                            "state": AccountGapSnapshotState.NOT_APPLICABLE,
                            "spend_outcome": AccountGapSpendOutcome.NOT_CHARGED,
                            "failure_code": "no_matched_sumble_organization",
                            "terminal_at": terminal_now(),
                        }
                    ),
                )

    async def _materialize(
        self,
        operation: AccountGapOperation,
        snapshots: Mapping[str, SumbleSnapshot],
    ) -> tuple[str, ...]:
        claim_ids: list[str] = []
        await self._materializer.seed()
        async with self._conn_factory() as conn:
            existing_results = {
                str(item.field_key): item
                for item in await list_account_gap_field_results(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            }
            snapshot_rows = {
                item.source_key: item
                for item in await list_account_gap_snapshots(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            }
        for plan in operation.request.fields:
            prior_result = existing_results[str(plan.field_key)]
            if prior_result.state is not AccountGapFieldState.PENDING:
                if prior_result.sumble_claim_id is not None:
                    claim_ids.append(str(prior_result.sumble_claim_id))
                continue
            source_key = plan.source_key
            if not _requestable(str(plan.field_key)):
                # Owned by this source under §3.1, unrequestable by its pinned v9 action: an
                # honest terminal gap for the field's next authorized source, not a fabricated
                # value and not a failure of this operation.
                await self._put_field(
                    operation,
                    plan,
                    state=AccountGapFieldState.CONFIRMED_MISSING,
                    reason="source_cannot_request_field",
                )
                continue
            snapshot = snapshots.get(source_key)
            if snapshot is None:
                await self._put_field(
                    operation,
                    plan,
                    state=AccountGapFieldState.CONFIRMED_MISSING,
                    reason="no_matched_sumble_organization",
                )
                continue
            outcome = await self._materializer.materialize(
                workspace_id=operation.request.workspace_id,
                project_id=operation.request.project_id,
                project_run_id=operation.request.project_run_id,
                account_id=operation.request.account_id,
                field_key=str(plan.field_key),
                source_key=source_key,
                snapshot=snapshot,
                source_operation_ref=str(operation.operation_id),
                source_snapshot_ref=(
                    f"account-gap-snapshot:{operation.operation_id}:{source_key}:"
                    f"{snapshot_rows[source_key].request_fingerprint}"
                ),
                source_request_ref=snapshot.request_id,
            )
            if outcome.provider_claim_id is not None:
                claim_ids.append(str(outcome.provider_claim_id))
            await self._put_field(
                operation,
                plan,
                state={
                    SumbleFieldDisposition.CONFIRMED_MISSING: (
                        AccountGapFieldState.CONFIRMED_MISSING
                    ),
                    SumbleFieldDisposition.RESOLVED: AccountGapFieldState.RESOLVED,
                    SumbleFieldDisposition.CORROBORATED: AccountGapFieldState.CORROBORATED,
                    SumbleFieldDisposition.CONFLICT: AccountGapFieldState.CONFLICT,
                }[outcome.disposition],
                sumble_claim_id=outcome.provider_claim_id,
                current_claim_id=outcome.current_claim_id,
                conflicts=outcome.conflicting_claim_ids,
                reason=outcome.reason_code,
            )
        return tuple(sorted(set(claim_ids)))

    async def _put_field(
        self,
        operation: AccountGapOperation,
        plan: AccountGapFieldPlan,
        *,
        state: AccountGapFieldState,
        sumble_claim_id: ClaimId | None = None,
        current_claim_id: ClaimId | None = None,
        conflicts: Sequence[ClaimId] = (),
        reason: str,
    ) -> None:
        async with self._conn_factory() as conn:
            await put_account_gap_field_result(
                conn,
                workspace_id=operation.request.workspace_id,
                result=AccountGapFieldResult(
                    operation_id=operation.operation_id,
                    account_id=operation.request.account_id,
                    field_key=plan.field_key,
                    source_key=plan.source_key,
                    state=state,
                    sumble_claim_id=sumble_claim_id,
                    current_claim_id=current_claim_id,
                    conflicting_claim_ids=tuple(conflicts),
                    reason_code=reason,
                ),
            )

    async def _fail_fields(self, operation: AccountGapOperation, reason: str) -> None:
        async with self._conn_factory() as conn:
            fields = await list_account_gap_field_results(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        for result in fields:
            if result.state is AccountGapFieldState.PENDING:
                plan = next(
                    item for item in operation.request.fields if item.field_key == result.field_key
                )
                await self._put_field(
                    operation,
                    plan,
                    state=AccountGapFieldState.FAILED_TERMINAL,
                    reason=reason,
                )

    async def _receipt(
        self,
        operation: AccountGapOperation,
        snapshots: Mapping[str, SumbleSnapshot],
        *,
        claim_ids: Sequence[str],
    ) -> str:
        async with self._conn_factory() as conn:
            fields = await list_account_gap_field_results(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            payload = {
                "contract": "sumble-account-gap-receipt-v1",
                "operation_id": str(operation.operation_id),
                "request_fingerprint": operation.request_fingerprint,
                "discovery_seal_sha256": operation.request.discovery_seal_sha256,
                "provider_contract_version": operation.request.provider_contract_version,
                "provider_units_reserved": str(operation.provider_units_reserved),
                "provider_units_charged": str(
                    sum((Decimal(item.credits_used) for item in snapshots.values()), Decimal(0))
                ),
                "snapshots": {
                    key: {
                        "request_id": value.request_id,
                        "credits_used": value.credits_used,
                        "credits_remaining": value.credits_remaining,
                        "artifact_key": value.artifact_key,
                    }
                    for key, value in sorted(snapshots.items())
                },
                "fields": [item.model_dump(mode="json") for item in fields],
                "claim_ids": list(claim_ids),
            }
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(payload),
                media_type="application/json",
                source_key=ORGANIZATIONS_SOURCE_KEY,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, key, "sumble_gap_receipt")
            return key

    async def _mark_provider_rejected(
        self,
        operation: AccountGapOperation,
        *,
        error: ProviderResponseError,
        provider_calls: int = 0,
    ) -> SumbleAccountGapResult:
        """Persist a deterministic provider rejection with its exact diagnostic evidence.

        Sumble validates a request and prechecks the balance *before* charging, so a hard 4xx is a
        zero-credit terminal refusal — categorically different from a transport loss after dispatch,
        whose spend really is unknown. Collapsing both into ``spend_outcome_unknown`` cost a manual
        live replay just to learn the status code, so the failing snapshot now retains the HTTP
        status and the provider's own bounded error body as an ordinary response artifact.

        Only the in-flight (``DISPATCHING``) snapshot is refused. Any snapshot this operation had
        already settled keeps its real charge, and the operation's spend outcome is recomputed from
        the durable snapshot ledger rather than being asserted uncharged.
        """

        async with self._conn_factory() as conn:
            rows = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        dispatching = tuple(row for row in rows if row.state is AccountGapSnapshotState.DISPATCHING)
        source_key = dispatching[0].source_key if dispatching else "sumble"
        failure_code = f"{source_key}_provider_rejected_http_{error.status_code}"
        async with self._conn_factory() as conn:
            rejection_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(
                    {
                        "provider_rejection": {
                            "source_key": source_key,
                            "http_status": error.status_code,
                            "body_excerpt": error.body_excerpt,
                        }
                    }
                ),
                media_type="application/json",
                source_key=source_key,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, rejection_key, f"{source_key}_provider_rejection")
            for row in dispatching:
                await update_account_gap_snapshot(
                    conn,
                    snapshot=row.model_copy(
                        update={
                            "state": AccountGapSnapshotState.FAILED_TERMINAL,
                            "spend_outcome": AccountGapSpendOutcome.NOT_CHARGED,
                            "response_artifact_key": rejection_key,
                            "failure_code": failure_code,
                            "terminal_at": terminal_now(),
                        }
                    ),
                )
        await self._fail_fields(operation, failure_code)
        async with self._conn_factory() as conn:
            settled = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            charged = sum((row.provider_units_charged for row in settled), Decimal(0))
            cost = sum((row.cost_cents_charged for row in settled), Decimal(0))
            current = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise AccountGapNotFound("Sumble account-gap rejected operation")
            stored = await update_account_gap_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": AccountGapOperationState.FAILED_TERMINAL,
                        "spend_outcome": (
                            AccountGapSpendOutcome.CHARGED
                            if charged
                            else AccountGapSpendOutcome.NOT_CHARGED
                        ),
                        "provider_units_charged": charged,
                        "cost_cents_charged": cost,
                        "failure_code": failure_code,
                        "terminal_at": terminal_now(),
                    }
                ),
            )
        return SumbleAccountGapResult(
            outcome=SumbleAccountGapOutcome.FAILED_TERMINAL,
            operation=stored,
            provider_calls=provider_calls,
        )

    async def _mark_unknown(
        self,
        operation: AccountGapOperation,
        failure_code: str,
        *,
        provider_calls: int = 0,
    ) -> SumbleAccountGapResult:
        async with self._conn_factory() as conn:
            rows = await list_account_gap_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            for row in rows:
                if row.state is AccountGapSnapshotState.DISPATCHING:
                    await update_account_gap_snapshot(
                        conn,
                        snapshot=row.model_copy(
                            update={
                                "state": AccountGapSnapshotState.SPEND_OUTCOME_UNKNOWN,
                                "spend_outcome": AccountGapSpendOutcome.UNKNOWN,
                                "failure_code": failure_code,
                                "terminal_at": terminal_now(),
                            }
                        ),
                    )
            known_units = sum((row.provider_units_charged for row in rows), Decimal(0))
            known_cost = sum((row.cost_cents_charged for row in rows), Decimal(0))
            current = await get_account_gap_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise AccountGapNotFound("Sumble account-gap unknown-spend operation")
            stored = await update_account_gap_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": AccountGapOperationState.SPEND_OUTCOME_UNKNOWN,
                        "spend_outcome": AccountGapSpendOutcome.UNKNOWN,
                        "provider_units_charged": known_units,
                        "cost_cents_charged": known_cost,
                        "failure_code": failure_code,
                        "terminal_at": terminal_now(),
                    }
                ),
            )
        return SumbleAccountGapResult(
            outcome=SumbleAccountGapOutcome.SPEND_OUTCOME_UNKNOWN,
            operation=stored,
            provider_calls=provider_calls,
        )


class SumbleAccountGapStarter:
    def __init__(
        self,
        *,
        coordinator: SumbleAccountGapCoordinator,
        storage: StorageBackend,
        cents_per_credit: Decimal,
        conn_factory: ConnFactory = transaction,
        policy: SumbleAccountGapPolicy = DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY,
        enforce_budget: bool = True,
    ) -> None:
        self._coordinator = coordinator
        self._storage = storage
        self._cents_per_credit = cents_per_credit
        self._conn_factory = conn_factory
        self._policy = policy
        # FI pilot budget-controls, threaded from ``Settings.budget_controls_enabled`` at the
        # composition root. False means this path never refuses on budget grounds; every
        # durable row it writes is unchanged.
        self._enforce_budget = enforce_budget

    async def start(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_id: EntityId,
        field_expected_value_credits: Mapping[str, Decimal],
        provider_credit_cap: int,
        allow_unbounded_tech: bool,
        before_dispatch: Callable[[AccountGapOperation], Awaitable[None]] | None = None,
        entity_research_job_id: UUID | None = None,
    ) -> SumbleAccountGapResult:
        field_keys = tuple(sorted(field_expected_value_credits))
        window = f"project-run:{project_run_id}:sumble-gaps:{self._policy.version}"
        async with self._conn_factory() as conn:
            existing = await find_account_gap_operation_for_fields(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                observation_window=window,
                field_keys=field_keys,
            )
        if existing is not None:
            expected = sum(
                (Decimal(value) for value in field_expected_value_credits.values()), Decimal(0)
            )
            organization_body, organization_max = organization_request(
                existing.request.primary_domain,
                field_keys=_organization_request_fields(
                    [str(item.field_key) for item in existing.request.fields]
                ),
            )
            # The stored cap is the *authorized* one, which the record-only posture may have
            # raised to the bounded worst case. Re-derive it the same way, or an exact replay of
            # the caller's own arguments would read as a changed authorization.
            authorized_cap = _authorized_provider_credit_cap(
                provider_credit_cap,
                bounded=organization_max
                + (self._policy.jobs_limit if _HIRING in field_keys else 0),
                enforce_budget=self._enforce_budget,
            )
            if (
                existing.request.project_run_id != project_run_id
                or existing.request.provider_credit_cap != authorized_cap
                or existing.request.expected_value_credits != expected
                or {
                    str(item.field_key): item.expected_value_credits
                    for item in existing.request.fields
                }
                != {key: Decimal(value) for key, value in field_expected_value_credits.items()}
                or existing.request.allow_unbounded_tech != allow_unbounded_tech
            ):
                raise AccountGapReplayConflict(
                    "same-window Sumble field set was replayed with different authorization"
                )
            terminal = self._coordinator._terminal_result(existing, replay=True)
            if terminal is not None:
                return terminal
            return await self._coordinator.start(
                SumbleAccountGapPreflight(
                    request=existing.request,
                    organization_body=organization_body,
                    bounded_provider_units=Decimal(organization_max),
                    maximum_cost_cents=existing.cost_cents_reserved,
                ),
                before_dispatch=before_dispatch,
            )
        preflight = await compile_sumble_account_gap_preflight(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_id=account_id,
            field_expected_value_credits=field_expected_value_credits,
            provider_credit_cap=provider_credit_cap,
            allow_unbounded_tech=allow_unbounded_tech,
            observation_window=window,
            storage=self._storage,
            cents_per_credit=self._cents_per_credit,
            conn_factory=self._conn_factory,
            policy=self._policy,
            entity_research_job_id=entity_research_job_id,
            enforce_budget=self._enforce_budget,
        )
        return await self._coordinator.start(preflight, before_dispatch=before_dispatch)


def build_production_sumble_account_gap_starter(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
) -> SumbleAccountGapStarter | None:
    if not settings.sumble_account_gap_enrichment_enabled:
        return None
    if secrets.sumble_api_key is None:
        raise RuntimeError(
            "Sumble account-gap enrichment is enabled but CLUE_SUMBLE_API_KEY is not configured"
        )
    coordinator = SumbleAccountGapCoordinator(
        api_key=secrets.sumble_api_key,
        storage=storage,
        cents_per_credit=settings.sumble_cents_per_credit,
        conn_factory=conn_factory,
        enforce_budget=settings.budget_controls_enabled,
    )
    return SumbleAccountGapStarter(
        coordinator=coordinator,
        storage=storage,
        cents_per_credit=settings.sumble_cents_per_credit,
        conn_factory=conn_factory,
        enforce_budget=settings.budget_controls_enabled,
    )


__all__ = [
    "DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY",
    "SUMBLE_ACCOUNT_GAP_FIELD_POLICY_VERSION",
    "SUMBLE_ACCOUNT_GAP_PRICING_VERSION",
    "SUMBLE_V9_CONTRACT_VERSION",
    "SumbleAccountGapCoordinator",
    "SumbleAccountGapEligibilityError",
    "SumbleAccountGapError",
    "SumbleAccountGapFieldAlreadyAcquired",
    "SumbleAccountGapFieldsUnrequestable",
    "SumbleAccountGapNotEligible",
    "SumbleAccountGapOutcome",
    "SumbleAccountGapPolicy",
    "SumbleAccountGapPreflight",
    "SumbleAccountGapResult",
    "SumbleAccountGapStarter",
    "build_production_sumble_account_gap_starter",
    "compile_sumble_account_gap_preflight",
]
