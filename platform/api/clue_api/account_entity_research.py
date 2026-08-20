"""M8D R5 engine-owned account-agent state, coverage, review, guard, and finalization."""

from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import (
    AccountCommitteePlanProjection,
    AccountCoverageProjection,
    AccountExistingClaimProjection,
    AccountResearchStateProjection,
    AssessAccountCoverageInput,
    CommitteeRoleInference,
    FinalizeAccountResearchInput,
    InspectAccountEvidenceInput,
    ReadAccountResearchStateInput,
    RecordCommitteeRoleInferencesInput,
)
from clue_agents.entity_research_contracts import (
    EntityResearchRuntimeContext,
    EntityResearchToolBinding,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    EntityResearchExecutionGuard,
    EntityResearchFinalizationEngine,
    EntityResearchFinalizationRejected,
    EntityResearchGovernedToolRefusal,
    current_entity_research_tool_execution,
)
from clue_api.account_field_derivation import (
    DERIVED_ACCOUNT_FIELD_SOURCES,
    AccountFieldDerivation,
    derive_account_fields,
)
from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    source_can_request,
)
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    convert_engine_authority_rejections,
    semantic_validation_error,
)
from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    ExtractionMethod,
    IdentityBinding,
    ProjectRunId,
    ResearchScope,
    RunId,
    SourceTier,
    serialize_value_json,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    FinalizationVerification,
    ResearchFinalizationOutcome,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchSubjectType,
)

# "Is this field project-relative?" must have exactly one answer for the economics here and for
# the lens that renders the resulting claims, so the species read is imported rather than restated
# (it resolves through `core.resolve_research_scope` over the *effective* registry, retired
# declarations included — see its docstring).
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    claims_for_entities,
    current_values,
    field_species,
)
from clue_research.directives import effective_account_research_directive
from clue_research.durable import find_account_runs_for_entity
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    PERSONA,
    ROLE_ON_COMMITTEE,
    write_committee_claim,
)

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
NonEmptyStr = Annotated[str, Field(min_length=1)]
_PROPOSAL_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:account-finalization-proposal")
_RECEIPT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:account-finalization-receipt")
_QUALITATIVE_SOURCE = "exa_deep"
_CONTACT_TOOL_PREFIXES = (
    "research_contact",
    "enrich_contact",
    "reveal_contact",
    "validate_contact",
)
#: Account tools that buy nothing: they read durable state this job already owns. Two of them in
#: one model round is neither duplicated provider work nor a widened scope — it is the agent
#: reading two persisted results at once. Live, a round holding two ``read_research_result`` calls
#: was refused as "duplicate account provider work" and suspended the whole job.
_READ_ONLY_TOOL_NAMES = frozenset(
    {
        "read_account_research_state",
        "inspect_account_evidence",
        "read_research_result",
        "read_evidence",
    }
)


def pending_provider_operations_sql(job_expression: str) -> str:
    """The one definition of "provider work this job is still waiting on".

    Spec §5.4 makes assessment and finalization re-derive the same invariant independently, so
    both must read *this* predicate and can never drift apart: ``_pending_refs`` selects the refs,
    the finalization guard counts them, and the body below is written once.

    An observation is pending unless one of three things is true.

    1. Its operation produced a result in this job.
    2. Its operation carries a settlement fold with no result — a real provider exchange that
       terminally refused or could not be settled (the live Sumble 402 livelock). A fold means
       settlement and nothing else; it is never written for work the provider never received.
       The fold releases the operation **whichever job filed it**: a fold is a property of the
       operation ("the provider is done with this"), not of the asker, and the observation join
       above already scopes the release to operations *this* job observed. Operations are
       content-keyed and deliberately reused across jobs, so a later job re-derives the same ref
       and only replays it; the fold is inserted once, ON CONFLICT DO NOTHING, under whoever
       settled it first. Demanding one's own job id wedged the live 2026-08-19 Millennium jobs
       forever on ``sumble-account-operation:89f64be2`` (HTTP 402, folded under an earlier job):
       every ``assess_account_coverage`` and ``finalize_account_research`` refused with pending
       work, and no retry could repair it because the replay hits the terminal rejection and the
       first job's fold survives. Spend attribution stays job-scoped — the replaying job paid
       nothing — and a result must still be *this* job's, because a cross-job result is repairable
       by a zero-spend replay that writes a result row under this job's own tool request.
    3. Its operation was **never dispatched** and the batch member that caused it is durably
       ``failed`` — a sibling failure, a lost lease or a crash. Nothing was sent, so nothing will
       arrive; the operation stops blocking. This is a pending-release only: the row keeps
       ``dispatched_at IS NULL``, so ``read_account_research_execution_completeness`` still
       refuses to count it as an attempt and the member's fields go back to outstanding for the
       agent to research again. A member that *did* dispatch is deliberately excluded — that
       outcome belongs to the provider's own attempt ledger and its unknown-spend machinery.
    """

    return f"""
        SELECT observation.provider_operation_ref
        FROM entity_research_provider_observation observation
        JOIN entity_research_tool_request request_row
          ON request_row.tool_request_id=observation.tool_request_id
        WHERE request_row.job_id={job_expression}
          AND NOT EXISTS (
              SELECT 1 FROM entity_research_result result
              JOIN entity_research_tool_request result_request
                ON result_request.tool_request_id=result.tool_request_id
              WHERE result.provider_operation_ref=observation.provider_operation_ref
                AND result_request.job_id=request_row.job_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM entity_research_provider_settlement_fold fold
              WHERE fold.provider_operation_ref=observation.provider_operation_ref
                AND NOT EXISTS (
                    SELECT 1 FROM entity_research_result settled
                    WHERE settled.provider_operation_ref=fold.provider_operation_ref
                )
          )
          AND NOT EXISTS (
              SELECT 1
              FROM entity_research_provider_operation operation
              JOIN entity_research_tool_batch batch
                ON batch.agent_turn_id=request_row.agent_turn_id
              JOIN entity_research_tool_batch_member member
                ON member.batch_id=batch.batch_id
               AND member.raw_tool_call_id=request_row.raw_tool_call_id
              JOIN entity_research_tool_batch_event event
                ON event.batch_id=member.batch_id
               AND event.raw_tool_call_id=member.raw_tool_call_id
              WHERE operation.operation_ref=observation.provider_operation_ref
                AND operation.dispatched_at IS NULL
                AND event.event_kind='failed'
          )
    """


class AccountResearchAuthorityError(EntityResearchGovernedToolRefusal):
    """Model-repairable account guard/engine refusal (returned to the agent, never fatal)."""


class AccountResearchExecutionCompleteness(BaseModel):
    """Durably re-derived proof that every authorized Account action reached a disposition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    satisfied_field_keys: tuple[str, ...]
    terminal_field_source_pairs: tuple[tuple[str, str], ...]
    outstanding_field_source_pairs: tuple[tuple[str, str], ...]
    outstanding_non_acquisition_fields: tuple[str, ...]
    terminal_committee_source_keys: tuple[str, ...]
    outstanding_committee_source_keys: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not (
            self.outstanding_field_source_pairs
            or self.outstanding_non_acquisition_fields
            or self.outstanding_committee_source_keys
        )

    def outstanding_summary(self) -> str:
        parts = [
            *(
                f"{field_key}@{source_key}"
                for field_key, source_key in self.outstanding_field_source_pairs
            ),
            *(
                f"{field_key}@reuse-or-derive"
                for field_key in self.outstanding_non_acquisition_fields
            ),
            *(f"committee@{source_key}" for source_key in self.outstanding_committee_source_keys),
        ]
        return ", ".join(parts)


async def committee_axis_unavailable_source_keys(
    conn: AsyncConnection, *, job_id: UUID
) -> frozenset[str]:
    """The committee sources this job durably attempted and found the provider cannot serve.

    The committee twin of a settlement fold, for the one case that has no operation to fold: the
    provider's organization index carries no exact match for the account (live ``dc86340f``,
    "Greater Chicago Specialty Physicians LLC"), or no organization response for it exists at all.
    Both refusals happen *before* any reservation, so nothing was dispatched and nothing charged —
    there is no operation row and never will be. The engine records the refused tool call instead
    (``entity_research_account_committee_unavailable``, one row per journalled call), and that row
    is what makes the axis terminal here.

    This is an attempt in exactly the sense the settlement contract means: the agent really called
    the tool, under this job's authority, and the engine really established from durable state
    that the provider cannot be asked. It is never a *result* — a successful committee call still
    takes precedence — and it never counts toward a field/source pair (a committee operation
    carries no field keys).
    """

    return frozenset(
        str(value)
        for value in (
            (
                await conn.execute(
                    text(
                        "SELECT DISTINCT unnest(source_keys) FROM "
                        "entity_research_account_committee_unavailable WHERE job_id=:job_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .scalars()
            .all()
        )
    )


async def committee_axis_unavailable_reasons(
    conn: AsyncConnection, *, job_id: UUID
) -> tuple[str, ...]:
    """The distinct world-fact reason codes behind this job's terminal committee attempts."""

    return tuple(
        str(value)
        for value in (
            (
                await conn.execute(
                    text(
                        "SELECT DISTINCT reason_code FROM "
                        "entity_research_account_committee_unavailable "
                        "WHERE job_id=:job_id ORDER BY 1"
                    ),
                    {"job_id": job_id},
                )
            )
            .scalars()
            .all()
        )
    )


async def read_account_research_execution_completeness(
    conn: AsyncConnection, *, authorization: EntityResearchJobAuthorization
) -> AccountResearchExecutionCompleteness:
    """Compute execution completeness from claims plus dispatched, terminal provider ledgers.

    A tool request or reservation is not an attempt. A field/source pair counts only when its
    provider operation was durably **dispatched** and then produced either a persisted result or
    an idempotent terminal settlement fold. The dispatch stamp is load-bearing and deliberately
    not relaxed for a fold: a settlement written over an operation the provider never received
    (a sibling-cancelled or crashed member) releases that operation's pending-ness, but it is not
    evidence that anything was researched, and the ratified contract refuses to let a cancellation
    settle a field. Every fold that *does* represent a real provider exchange stamps the true
    dispatch time from the provider's own attempt ledger first, so it counts. Successful evidence
    may stop a field's waterfall.
    """

    acquisition_fields = tuple(authorization.selection.admitted_field_keys)
    non_acquisition_fields = await non_acquisition_account_profile_fields(
        conn, authorization=authorization
    )
    profile_fields = tuple(dict.fromkeys((*acquisition_fields, *non_acquisition_fields)))
    result_evidence_fields = frozenset(
        str(value)
        for value in (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT result_field.field_key
                    FROM entity_research_result_field result_field
                    JOIN entity_research_result result
                      ON result.result_id=result_field.result_id
                    JOIN entity_research_tool_request request_row
                      ON request_row.tool_request_id=result.tool_request_id
                    JOIN entity_research_result_evidence evidence
                      ON evidence.result_id=result_field.result_id
                     AND evidence.field_ordinal=result_field.ordinal
                    WHERE request_row.job_id=:job_id
                      AND result_field.subject_type='account'
                      AND result_field.target_entity_id=:account_id
                      AND result_field.outcome='found'
                    """
                ),
                {
                    "job_id": authorization.job_id,
                    "account_id": authorization.subject_entity_id,
                },
            )
        ).scalars()
    )
    current = (
        {}
        if not profile_fields
        else await current_values(
            conn,
            [EntityId(authorization.subject_entity_id)],
            profile_fields,
            scope=WorkspaceScope.for_workspace(str(authorization.workspace_id)),
        )
    )
    species = (
        {}
        if not profile_fields
        else await field_species(
            conn,
            workspace_id=str(authorization.workspace_id),
            field_keys=profile_fields,
        )
    )
    reusable_fields = {
        field_key
        for (_entity_id, field_key), value in current.items()
        # ``evidence_backed`` is the one shared satisfaction test (fresh, unconflicted, spanned);
        # species is applied beside it because reusability across projects is a field property.
        if value.evidence_backed
        and species.get(field_key, ResearchScope.PROJECT_RELATIVE) is ResearchScope.PROJECT_NEUTRAL
    }
    satisfied_fields = frozenset(result_evidence_fields | reusable_fields)

    terminal_rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT operation.source_key, operation.field_keys,
                           request_row.tool_name
                    FROM entity_research_provider_operation operation
                    JOIN entity_research_provider_observation observation
                      ON observation.provider_operation_ref=operation.operation_ref
                    JOIN entity_research_tool_request request_row
                      ON request_row.tool_request_id=observation.tool_request_id
                    WHERE request_row.job_id=:job_id
                      AND operation.dispatched_at IS NOT NULL
                      AND (
                          EXISTS (
                              SELECT 1 FROM entity_research_result result
                              JOIN entity_research_tool_request result_request
                                ON result_request.tool_request_id=result.tool_request_id
                              WHERE result.provider_operation_ref=operation.operation_ref
                                AND result_request.job_id=:job_id
                          )
                          OR EXISTS (
                              -- A fold belongs to the operation, not to whoever filed it: it is
                              -- written once, ON CONFLICT DO NOTHING, under the first job to
                              -- settle it, while content-keyed operations are deliberately reused
                              -- across jobs. The join above already requires *this* job to have
                              -- observed the operation and the operation to have dispatched, so
                              -- "this job attempted it and the provider is terminally done" is an
                              -- honest attempt for this job too (spec §5.2). Demanding one's own
                              -- job id left a replaying job with no attempt and no pending work it
                              -- could ever clear — the live 2026-08-19 Millennium wedge.
                              SELECT 1 FROM entity_research_provider_settlement_fold fold
                              WHERE fold.provider_operation_ref=operation.operation_ref
                          )
                      )
                    ORDER BY operation.source_key, request_row.tool_name
                    """
                ),
                {"job_id": authorization.job_id},
            )
        )
        .mappings()
        .all()
    )
    terminal_pairs = frozenset(
        (str(field_key), str(row["source_key"]))
        for row in terminal_rows
        for field_key in row["field_keys"]
    )
    authority = {
        # Requestability is intersected here for exactly the reason the launcher intersects it
        # into a new selection's authority (``source_can_request``): an already-durable selection
        # minted before that intersection existed still names pairs whose pinned provider action
        # structurally cannot ask for the field. The tool refuses such a request as ineligible and
        # coverage refuses to close while it is outstanding, so the agent loops between the two
        # until the graph recursion cap kills the job — observed live on
        # ``account.recent_funding@sumble_organizations``. An unrequestable pair is exhausted by
        # construction: never outstanding, never terminal, reported as an honest gap. This does not
        # relax the no-work rule — a pair no dispatch can carry was never work.
        item.field_key: tuple(
            source_key
            for source_key in item.source_keys
            if source_can_request(source_key, item.field_key)
        )
        for item in authorization.effective_field_source_authority
    }
    outstanding_pairs = tuple(
        (field_key, source_key)
        for field_key in acquisition_fields
        if field_key not in satisfied_fields
        for source_key in authority[field_key]
        if (field_key, source_key) not in terminal_pairs
    )
    exhausted_acquisition_fields = {
        field_key
        for field_key in acquisition_fields
        if field_key in satisfied_fields
        or all((field_key, source_key) in terminal_pairs for source_key in authority[field_key])
    }
    outstanding_non_acquisition = []
    for field_key in non_acquisition_fields:
        if field_key in satisfied_fields:
            continue
        source_field = DERIVED_ACCOUNT_FIELD_SOURCES.get(field_key)
        if source_field is None:
            # A row that is neither acquired nor derived (``core.account_name`` is the only one)
            # has no provider action and no source field, so nothing can ever exhaust it. Holding
            # it outstanding blocked both assessment and finalization forever whenever its
            # identity claim was absent, stale, conflicted or span-less; the honest disposition is
            # a gap the coverage ledger reports, which is what the canonical-identity review flag
            # already exists to say.
            continue
        if source_field not in authority:
            # A narrow historical/non-comprehensive directive may request a derived display row
            # without authorizing acquisition of its numeric source. There is then no applicable
            # provider action to attempt; the derived row may close as an honest gap.
            continue
        if source_field in exhausted_acquisition_fields:
            continue
        outstanding_non_acquisition.append(field_key)

    terminal_committee_sources = frozenset(
        str(row["source_key"])
        for row in terminal_rows
        if str(row["tool_name"]) == "discover_buying_committee"
    ) | await committee_axis_unavailable_source_keys(conn, job_id=authorization.job_id)
    committee_result_exists = bool(
        (
            await conn.execute(
                text(
                    """
                    SELECT 1 FROM entity_research_result result
                    JOIN entity_research_tool_request request_row
                      ON request_row.tool_request_id=result.tool_request_id
                    WHERE request_row.job_id=:job_id
                      AND request_row.tool_name='discover_buying_committee'
                    LIMIT 1
                    """
                ),
                {"job_id": authorization.job_id},
            )
        ).scalar_one_or_none()
    )
    committee_sources = tuple(authorization.selection.committee_source_keys)
    outstanding_committee = (
        ()
        if committee_result_exists
        else tuple(
            source_key
            for source_key in committee_sources
            if source_key not in terminal_committee_sources
        )
    )
    return AccountResearchExecutionCompleteness(
        satisfied_field_keys=tuple(
            field_key for field_key in profile_fields if field_key in satisfied_fields
        ),
        terminal_field_source_pairs=tuple(
            (field_key, source_key)
            for field_key in acquisition_fields
            for source_key in authority[field_key]
            if (field_key, source_key) in terminal_pairs
        ),
        outstanding_field_source_pairs=outstanding_pairs,
        outstanding_non_acquisition_fields=tuple(outstanding_non_acquisition),
        terminal_committee_source_keys=tuple(
            source_key
            for source_key in committee_sources
            if source_key in terminal_committee_sources
        ),
        outstanding_committee_source_keys=outstanding_committee,
    )


async def existing_account_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: UUID,
    field_keys: Sequence[str],
) -> tuple[AccountExistingClaimProjection, ...]:
    """What this workspace already knows about ``field_keys`` for one account (FI-2 §6.1).

    One canonical-merge read (never a raw ``claim.workspace_id`` filter — the workspace scope is
    the claimstore's own predicate) plus one species read, so the agent sees the account's current
    truth before it plans, and every economics consumer decides "born complete?" from the same two
    reads rather than from a private re-derivation of its own.
    """

    subject = EntityId(account_entity_id)
    current = await current_values(
        conn,
        [subject],
        field_keys,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    species = await field_species(conn, workspace_id=workspace_id, field_keys=list(field_keys))
    return tuple(
        AccountExistingClaimProjection(
            field_key=key,
            claim_ref=f"claim:{value.provenance.claim_id}",
            value=value.value_json,
            source_url=value.provenance.source_url,
            source_tier=int(value.provenance.source_tier),
            evidence_span=value.provenance.evidence_span,
            confidence=float(value.provenance.confidence),
            freshness_state=cast(Literal["fresh", "stale"], value.freshness_state.value),
            conflict=value.conflict,
            # Fail closed: an unresolvable species is reported *relative*, the species that is
            # never skippable.  ``field_species`` answers for every declared field, so this
            # default is unreachable today; if it ever becomes reachable, the safe reading of
            # "we do not know whose answer this is" is "it is not the workspace's to borrow".
            research_scope=species.get(key, ResearchScope.PROJECT_RELATIVE).value,
        )
        for key in field_keys
        if (value := current.get((subject, key))) is not None
    )


async def born_complete_account_field_keys(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: UUID,
    field_keys: Sequence[str],
) -> frozenset[str]:
    """The subset of ``field_keys`` no provider may be paid for (FI-2 §6.2).

    The *one* borrowed-set derivation: the R5 guard (which refuses a call that would re-buy one of
    these) and the Exa bundle compiler (which never puts one in a bundle) both read it here, so the
    guard's "every primary Exa field" rule and the bundle's contents can never disagree about what
    the workspace already knows.
    """

    return frozenset(
        item.field_key
        for item in await existing_account_claims(
            conn,
            workspace_id=workspace_id,
            account_entity_id=account_entity_id,
            field_keys=field_keys,
        )
        if item.born_complete
    )


async def pinned_account_research_directive(
    conn: AsyncConnection, *, authorization: EntityResearchJobAuthorization
) -> Any:
    """The effective directive this job's account run pinned, or ``None`` when it pinned none.

    One read for every consumer of the job's *confirmed direction* (the committee plan below and
    the derive-only profile axis), so they can never disagree about which directive governs.  A job
    whose account run carries no directive pin is the historical/static R5 seam: it has no
    confirmed direction to project, which is different from having an empty one.
    """

    runs = await find_account_runs_for_entity(
        conn,
        project_run_id=ProjectRunId(authorization.project_run_id),
        entity_id=EntityId(authorization.subject_entity_id),
        directive_ref=authorization.selection.directive_ref,
    )
    pinned = tuple(run for run in runs if run.research_directive is not None)
    if not pinned:
        return None
    if len(pinned) != 1:
        raise AccountResearchAuthorityError(
            "multiple account runs pin the job's exact authorized directive"
        )
    pin = pinned[0].research_directive
    assert pin is not None
    if pin.directive_ref != authorization.selection.directive_ref:
        raise AccountResearchAuthorityError(
            "account run pins a directive the job selection did not authorize"
        )
    return await effective_account_research_directive(
        conn,
        workspace_id=authorization.workspace_id,
        directive_id=pin.directive_id,
        account_id=EntityId(authorization.subject_entity_id),
        expected_pin=pin,
    )


async def derivable_account_profile_fields(
    conn: AsyncConnection, *, authorization: EntityResearchJobAuthorization
) -> tuple[str, ...]:
    """The derive-only §3.1 rows (5 and 8) this job's confirmed directive actually asked for.

    They are deliberately absent from ``selection.admitted_field_keys``: a field with no
    acquisition source cannot be bought, estimated, or authorized against a source, so the launcher
    partitions it out of the paid selection.  It is still part of the profile the directive
    confirmed, so coverage answers for it — this is the exact set the coverage ledger adds to the
    admitted axis, read from the same durable authority by the assessor and by the finalization
    engine that verifies the assessor.
    """

    directive = await pinned_account_research_directive(conn, authorization=authorization)
    if directive is None:
        return ()
    return tuple(
        str(field_key)
        for field_key in directive.field_keys
        if str(field_key) in DERIVED_ACCOUNT_FIELD_SOURCES
    )


async def non_acquisition_account_profile_fields(
    conn: AsyncConnection, *, authorization: EntityResearchJobAuthorization
) -> tuple[str, ...]:
    """Confirmed profile rows that are reused/derived and therefore absent from paid authority."""

    directive = await pinned_account_research_directive(conn, authorization=authorization)
    if directive is None:
        return ()
    return tuple(
        str(field_key)
        for field_key in directive.field_keys
        if str(field_key) in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES
        and not COMPREHENSIVE_ACCOUNT_FIELD_SOURCES[str(field_key)]
    )


async def read_account_committee_plan(
    conn: AsyncConnection, *, authorization: EntityResearchJobAuthorization
) -> AccountCommitteePlanProjection | None:
    """Project the confirmed committee plan of the account run's pinned directive.

    This is a read-only projection of durable authority: the account run pins the directive, the
    directive (plus any account override) composes the effective committee plan, and the plan is
    what the engine later validates a committee tool call against.  A job whose account run carries
    no directive pin (the historical/static R5 seam) has no plan to show, so the block is absent
    rather than invented.
    """

    effective = await pinned_account_research_directive(conn, authorization=authorization)
    if effective is None:
        return None
    plan = effective.committee_plan
    return AccountCommitteePlanProjection(
        directive_ref=effective.pin.directive_ref,
        functions=tuple(str(value) for value in plan.functions),
        levels=tuple(str(value) for value in plan.levels),
        teams=tuple(str(value) for value in plan.teams),
        personas=tuple(str(value) for value in plan.personas),
        candidate_cap=plan.candidate_cap,
        questions=tuple(item.text for item in effective.questions),
    )


class _EmptyInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountResearchStateStore:
    """Derive account coverage from persisted R4 results; model prose is never authority."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    @staticmethod
    def _active_account() -> ActiveEntityResearchToolExecution:
        active = current_entity_research_tool_execution()
        if active.context.authorization.subject_type is not ResearchSubjectType.ACCOUNT:
            raise AccountResearchAuthorityError("account engine tool used by a non-account job")
        return active

    async def state(
        self, active: ActiveEntityResearchToolExecution | None = None
    ) -> AccountResearchStateProjection:
        active = active or self._active_account()
        authorization = active.context.authorization
        admitted = authorization.selection.admitted_field_keys
        async with self._conn_factory() as conn:
            job = (
                (
                    await conn.execute(
                        text(
                            "SELECT current_state_sha256, spent_cents FROM entity_research_job "
                            "WHERE job_id=:job_id AND research_run_id=:run_id "
                            "AND workspace_id=:workspace_id AND subject_type='account' "
                            "AND subject_entity_id=:account_id"
                        ),
                        {
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "account_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if job is None:
                raise AccountResearchAuthorityError(
                    "account research job is absent or out of scope"
                )
            results = await self._result_rows(conn, authorization.job_id)
            fields = await self._field_rows(conn, authorization.job_id)
            pending = await self._pending_refs(conn, authorization.job_id)
            contact_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_tool_request "
                            "WHERE research_run_id=:run_id AND subject_type='contact'"
                        ),
                        {"run_id": authorization.research_run_id},
                    )
                ).scalar_one()
            )
            committee_plan = await read_account_committee_plan(conn, authorization=authorization)
            existing_claims = await self._existing_claims(
                conn, authorization=authorization, admitted=admitted
            )
        latest: dict[str, Mapping[str, object]] = {}
        committee_refs: list[str] = []
        member_ids: list[UUID] = []
        for row in results:
            if str(row["tool_name"]) == "discover_buying_committee":
                committee_refs.append(f"research-result:{row['result_id']}")
        for row in fields:
            if str(row["subject_type"]) == ResearchSubjectType.ACCOUNT.value:
                latest.setdefault(str(row["field_key"]), cast(Mapping[str, object], row))
            else:
                value = cast(UUID, row["target_entity_id"])
                if value not in member_ids:
                    member_ids.append(value)
        # FI-2 §6.1: a field this workspace already knows — neutral species, fresh, evidence-backed
        # and conflict-free — is born complete: the job never plans, spends or researches it, and
        # the coverage ledger cites the existing claim instead of a result of its own.
        born_complete = {item.field_key for item in existing_claims if item.born_complete}
        completed = tuple(
            key
            for key in admitted
            if key in born_complete or (key in latest and str(latest[key]["outcome"]) == "found")
        )
        unresolved = tuple(key for key in admitted if key not in set(completed))
        return AccountResearchStateProjection(
            job_id=authorization.job_id,
            account_entity_id=authorization.subject_entity_id,
            current_state_sha256=str(job["current_state_sha256"]),
            admitted_field_keys=admitted,
            admitted_source_keys=authorization.selection.admitted_source_keys,
            committee_source_keys=authorization.selection.committee_source_keys,
            existing_claims=existing_claims,
            result_refs=tuple(f"research-result:{row['result_id']}" for row in results),
            completed_field_keys=completed,
            unresolved_field_keys=unresolved,
            committee_result_refs=tuple(committee_refs),
            committee_member_ids=tuple(member_ids),
            pending_operation_refs=tuple(pending),
            spent_cents=str(Decimal(job["spent_cents"])),
            contact_research_request_count=contact_count,
            committee_plan=committee_plan,
        )

    async def _derive_profile_fields(
        self, authorization: EntityResearchJobAuthorization
    ) -> tuple[AccountFieldDerivation, ...]:
        """Settle the confirmed directive's derive-only §3.1 rows (contract rows 5 and 8).

        One transaction: the derivation reads the governed employee-count / annual-revenue claims
        and writes the band claims it can justify. It is deliberately *before* the state read, so
        a band derived in this assessment is already the account's current truth when coverage
        cites it.
        """

        async with self._conn_factory() as conn:
            field_keys = await derivable_account_profile_fields(conn, authorization=authorization)
            if not field_keys:
                return ()
            return await derive_account_fields(
                conn,
                workspace_id=str(authorization.workspace_id),
                project_id=str(authorization.project_id),
                project_run_id=ProjectRunId(authorization.project_run_id),
                account_entity_id=EntityId(authorization.subject_entity_id),
                field_keys=field_keys,
            )

    @staticmethod
    async def _existing_claims(
        conn: AsyncConnection,
        *,
        authorization: EntityResearchJobAuthorization,
        admitted: Sequence[str],
    ) -> tuple[AccountExistingClaimProjection, ...]:
        """This job's view of :func:`existing_account_claims` over its admitted fields."""

        return await existing_account_claims(
            conn,
            workspace_id=str(authorization.workspace_id),
            account_entity_id=authorization.subject_entity_id,
            field_keys=admitted,
        )

    async def evidence(self, inputs: InspectAccountEvidenceInput) -> dict[str, JsonValue]:
        active = self._active_account()
        expected = set(inputs.result_refs)
        state = await self.state(active)
        if not expected.issubset(state.result_refs):
            raise AccountResearchAuthorityError(
                "evidence request cites a result outside the exact job"
            )
        ids = [UUID(ref.removeprefix("research-result:")) for ref in inputs.result_refs]
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT result.result_id, field.field_key, field.outcome,
                                   field.verification_status, evidence.evidence_id,
                                   evidence.source_key, evidence.source_url,
                                   evidence.provider_source_id,
                                   'artifact:' || evidence.artifact_key AS artifact_ref
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            JOIN entity_research_result_field field
                              ON field.result_id=result.result_id
                            LEFT JOIN entity_research_result_evidence evidence
                              ON evidence.result_id=field.result_id
                             AND evidence.field_ordinal=field.ordinal
                            WHERE result.result_id=ANY(:result_ids)
                              AND request_row.job_id=:job_id
                            ORDER BY result.created_at, field.ordinal, evidence.evidence_ordinal
                            """
                        ),
                        {"result_ids": ids, "job_id": active.context.authorization.job_id},
                    )
                )
                .mappings()
                .all()
            )
        return {
            "result_refs": list(inputs.result_refs),
            "evidence_index": [self._json_row(row) for row in rows],
            "current_state_sha256": state.current_state_sha256,
        }

    async def record_committee_role_inferences(
        self, inputs: RecordCommitteeRoleInferencesInput
    ) -> dict[str, JsonValue]:
        """Persist job-local, evidence-cited agent judgments for discovered committee members.

        Membership and admissible evidence are reconstructed from this account job's persisted
        committee result fields. All inputs are validated before either half of a role/persona pair
        is written, so an outsider or cross-contact citation cannot partially mutate the batch.
        Omitted discovered members remain honestly roleless.
        """

        active = self._active_account()
        authorization = active.context.authorization
        contact_ids = [item.contact_entity_id for item in inputs.inferences]
        if len(contact_ids) != len(set(contact_ids)):
            raise AccountResearchAuthorityError("committee role inference batch repeats a contact")

        scope = WorkspaceScope.for_workspace(authorization.workspace_id)
        async with self._conn_factory() as conn:
            member_claim_ids = await self._committee_member_claim_ids(
                conn,
                job_id=authorization.job_id,
                account_entity_id=authorization.subject_entity_id,
            )
            outsiders = [value for value in contact_ids if value not in member_claim_ids]
            if outsiders:
                raise AccountResearchAuthorityError(
                    "committee role inference contact is outside this account job's discovered "
                    "members"
                )

            all_member_claim_ids = {
                claim_id for values in member_claim_ids.values() for claim_id in values
            }
            member_claims = await claims_by_ids(
                conn,
                all_member_claim_ids,
                scope=scope,
            )

            prepared: list[tuple[CommitteeRoleInference, str, str, RunId]] = []
            for inference in inputs.inferences:
                allowed = member_claim_ids[inference.contact_entity_id]
                cited_ids = {ClaimId(value) for value in inference.evidence_claim_ids}
                if not cited_ids <= allowed:
                    raise AccountResearchAuthorityError(
                        "committee role inference evidence is not one of this contact's own "
                        "claims from this account research job"
                    )
                if not cited_ids <= set(member_claims):
                    raise AccountResearchAuthorityError(
                        "committee role inference evidence is absent, superseded, expired, or "
                        "out of scope"
                    )
                cited = [member_claims[ClaimId(value)] for value in inference.evidence_claim_ids]
                if any(claim.entity_id != EntityId(inference.contact_entity_id) for claim in cited):
                    raise AccountResearchAuthorityError(
                        "committee role inference evidence belongs to another contact"
                    )
                run_ids = {claim.run_id for claim in cited}
                if len(run_ids) != 1:
                    raise AccountResearchAuthorityError(
                        "committee role inference evidence crosses committee runs"
                    )

                primary = cited[0]
                title_claim = next(
                    (
                        claim
                        for claim_id in sorted(allowed, key=str)
                        if claim_id in member_claims
                        if (claim := member_claims[claim_id]).field_key
                        in {CURRENT_TITLE, "contact.profile.title"}
                        and isinstance(claim.value_json, str)
                        and claim.value_json.strip()
                    ),
                    None,
                )
                source_url: str | None
                evidence_span: str | None
                if primary.source_url and primary.evidence_span:
                    source_url = primary.source_url
                    evidence_span = primary.evidence_span
                else:
                    source_url = title_claim.source_url if title_claim is not None else None
                    evidence_span = (
                        f"title: {title_claim.value_json}" if title_claim is not None else None
                    )
                if not source_url or not evidence_span:
                    raise AccountResearchAuthorityError(
                        "committee role inference requires a cited source URL and evidence span "
                        "(or the discovered member's grounded title span)"
                    )
                prepared.append((inference, source_url, evidence_span, next(iter(run_ids))))

            recorded: list[dict[str, JsonValue]] = []
            for inference, source_url, evidence_span, run_id in prepared:
                role_claim_id = await write_committee_claim(
                    conn,
                    EntityId(inference.contact_entity_id),
                    ROLE_ON_COMMITTEE,
                    {
                        "role": inference.role.value,
                        "confidence": inference.confidence,
                        "plausible": True,
                        "rationale": inference.reasoning,
                    },
                    confidence=inference.confidence,
                    method=ExtractionMethod.LLM_SYNTHESIS,
                    tier=SourceTier(4),
                    source_url=source_url,
                    evidence_span=evidence_span,
                    run_id=run_id,
                    workspace_id=authorization.workspace_id,
                    identity_binding=IdentityBinding.STRONG,
                    product_id=authorization.product_id,
                )
                persona_claim_id = await write_committee_claim(
                    conn,
                    EntityId(inference.contact_entity_id),
                    PERSONA,
                    inference.role.value,
                    confidence=inference.confidence,
                    method=ExtractionMethod.LLM_SYNTHESIS,
                    tier=SourceTier(4),
                    source_url=source_url,
                    evidence_span=evidence_span,
                    run_id=run_id,
                    workspace_id=authorization.workspace_id,
                    identity_binding=IdentityBinding.STRONG,
                    product_id=authorization.product_id,
                )
                recorded.append(
                    {
                        "contact_entity_id": str(inference.contact_entity_id),
                        "role_claim_ref": f"claim:{role_claim_id}",
                        "persona_claim_ref": f"claim:{persona_claim_id}",
                    }
                )

            role_claims = await self._committee_role_claims(
                conn,
                member_claim_ids=member_claim_ids,
                scope=scope,
            )

        inferred_member_count = len(self._inferred_committee_member_ids(role_claims))
        member_count = len(member_claim_ids)
        needs_review = member_count - inferred_member_count
        return {
            "recorded_inferences": cast(Any, recorded),
            "committee_member_count": member_count,
            "inferred_member_count": inferred_member_count,
            "needs_review": needs_review,
            "committee_status": "complete" if needs_review == 0 else "needs_review",
        }

    async def assess(
        self,
        inputs: AssessAccountCoverageInput,
        active: ActiveEntityResearchToolExecution | None = None,
    ) -> AccountCoverageProjection:
        active = active or self._active_account()
        authorization = active.context.authorization
        # Contract §3.1 rows 5 and 8 settle here, before the coverage row is written, so a run that
        # acquired ``core.employee_count`` closes with its ``core.employee_range`` derived in the
        # same run. Nothing is bought: the deriver only restates governed evidence already on file
        # (or leaves the row honestly unresolved), and it is idempotent on (entity, field, run).
        derivation = await self._derive_profile_fields(authorization)
        state = await self.state(active)
        if set(inputs.result_refs) != set(state.result_refs):
            raise AccountResearchAuthorityError(
                "coverage must inspect the complete current result set without omission"
            )
        if state.pending_operation_refs:
            raise AccountResearchAuthorityError("coverage cannot close over pending provider work")
        if state.contact_research_request_count:
            raise AccountResearchAuthorityError(
                "account coverage observed forbidden contact research"
            )
        async with self._conn_factory() as conn:
            execution = await read_account_research_execution_completeness(
                conn, authorization=authorization
            )
            non_acquisition_fields = await non_acquisition_account_profile_fields(
                conn, authorization=authorization
            )
            non_acquisition_existing = await existing_account_claims(
                conn,
                workspace_id=str(authorization.workspace_id),
                account_entity_id=authorization.subject_entity_id,
                field_keys=non_acquisition_fields,
            )
        if not execution.complete:
            # Name the exact next call, not just the gap. Observed live (jobs 5d9dfe7b and
            # 16e846d6): a model refused here for an unattempted committee source ping-ponged
            # read_account_research_state <-> assess_account_coverage to the recursion cap
            # without once calling discover_buying_committee - it knew what was missing but not
            # what to do. The committee call for this authorization has zero planning freedom
            # (sources and plan are confirmed), so the refusal spells it out literally.
            detail = (
                "coverage cannot close before every authorized field/source and committee "
                f"attempt is terminal: {execution.outstanding_summary()}"
            )
            if execution.outstanding_committee_source_keys:
                sources_json = json.dumps(list(execution.outstanding_committee_source_keys))
                detail += (
                    "; to attempt the committee now, call discover_buying_committee with "
                    f'arguments {{"source_keys": {sources_json}}} and no questions - do not '
                    "read state again first"
                )
            raise AccountResearchAuthorityError(detail)
        # A zero-result close is legal exactly once (FI-2 §6.1): when the account was researched by
        # spending nothing, i.e. every completed field is borrowed from a claim already on file.
        # The set-equality above already refuses an agent that omits results it produced; this
        # refuses the opposite mistake — closing empty over work that did complete a field.
        if not state.result_refs:
            borrowed = {item.field_key for item in state.existing_claims if item.born_complete}
            if not set(state.completed_field_keys) <= borrowed:
                raise AccountResearchAuthorityError(
                    "coverage without results is admissible only when every completed field is "
                    "answered by an existing claim"
                )
        coverage_id = uuid4()
        unresolved_reasons: list[str] = []
        async with self._conn_factory() as conn:
            field_rows = await self._field_rows(conn, authorization.job_id)
            latest_account: dict[str, Mapping[str, object]] = {}
            for row in field_rows:
                if str(row["subject_type"]) == "account":
                    latest_account.setdefault(
                        str(row["field_key"]), cast(Mapping[str, object], row)
                    )
            # The ledger explains every field's money: a field this job researched reports its
            # result outcome; a field it did not reports *why* the claim already on file could not
            # stand in for the spend (FI-2 §6.1 — same reason vocabulary as the contact runtime,
            # plus the species reason only the account axis can produce).
            existing_by_field = {item.field_key: item for item in state.existing_claims}
            for field_key in state.unresolved_field_keys:
                selected_row = latest_account.get(field_key)
                existing = existing_by_field.get(field_key)
                if selected_row is not None:
                    reason = f"{selected_row['outcome']}:{selected_row['verification_status']}"
                elif existing is None:
                    reason = "not_researched"
                elif existing.research_scope != "project_neutral":
                    # A fresh relative claim is another project's answer, never this project's.
                    reason = "existing_claim_project_relative"
                elif existing.conflict:
                    reason = "existing_claim_conflict"
                elif existing.freshness_state != "fresh":
                    reason = f"existing_claim_{existing.freshness_state}"
                else:
                    reason = "existing_claim_missing_evidence"
                unresolved_reasons.append(f"{field_key}:{reason}")
            # §3.1 rows 5 and 8 join the axis here. They are not admitted (they own no acquisition
            # source, so the launcher partitions them out of the paid selection) but the confirmed
            # directive asked for them, so the ledger answers for them: settled with the derived or
            # reused claim as its evidence, or unresolved with the exact derivation reason.
            derived_completed = tuple(item.field_key for item in derivation if item.settled)
            derived_unresolved = tuple(item.field_key for item in derivation if not item.settled)
            unresolved_reasons.extend(
                f"{item.field_key}:{item.reason}" for item in derivation if not item.settled
            )
            non_derived_zero = tuple(
                item
                for item in non_acquisition_existing
                if item.field_key not in DERIVED_ACCOUNT_FIELD_SOURCES
            )
            zero_completed = tuple(
                item.field_key for item in non_derived_zero if item.born_complete
            )
            zero_unresolved = tuple(
                item.field_key for item in non_derived_zero if not item.born_complete
            )
            unresolved_reasons.extend(
                f"{item.field_key}:canonical_identity_missing_evidence"
                for item in non_derived_zero
                if not item.born_complete
            )
            completed_field_keys = (
                *state.completed_field_keys,
                *zero_completed,
                *derived_completed,
            )
            unresolved_field_keys = (
                *state.unresolved_field_keys,
                *zero_unresolved,
                *derived_unresolved,
            )
            # "Skipped" means the money was never spent, so *any* result row for the field
            # disqualifies it — a failed or empty attempt cost just as much as a successful one,
            # and reporting it as never-spent would misstate the spend trail.
            completed = set(state.completed_field_keys)
            researched = set(latest_account)
            skipped_field_reasons = (
                *(
                    f"{item.field_key}:existing_claim_fresh"
                    for item in state.existing_claims
                    if item.born_complete
                    and item.field_key in completed
                    and item.field_key not in researched
                ),
                # A derived row costs nothing either, and its reason says which of the two §3.1
                # dispositions ("reuse **or** derive") answered it.
                *(f"{item.field_key}:{item.reason}" for item in derivation if item.settled),
                *(
                    f"{item.field_key}:existing_claim_fresh"
                    for item in non_derived_zero
                    if item.born_complete
                ),
            )

            scope_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_account_committee_scope "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            ambiguous_count = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT COALESCE(sum(
                                (projection.metadata_json->>'ambiguous_candidate_count')::integer
                            ), 0)
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            JOIN entity_research_sumble_projection projection
                              ON projection.provider_operation_ref=result.provider_operation_ref
                            WHERE request_row.job_id=:job_id
                              AND request_row.tool_name='discover_buying_committee'
                            """
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            confirmed_empty_count = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            WHERE request_row.job_id=:job_id
                              AND request_row.tool_name='discover_buying_committee'
                              AND result.confirmed_empty_discovery IS TRUE
                            """
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            committee_status, committee_flags = self._committee_coverage_status(
                committee_requested=bool(authorization.selection.committee_source_keys),
                result_count=len(state.committee_result_refs),
                member_count=len(state.committee_member_ids),
                scope_count=scope_count,
                ambiguous_count=ambiguous_count,
                confirmed_empty_count=confirmed_empty_count,
                provider_unavailable_reasons=await committee_axis_unavailable_reasons(
                    conn, job_id=authorization.job_id
                ),
            )
            member_claim_ids = await self._committee_member_claim_ids(
                conn,
                job_id=authorization.job_id,
                account_entity_id=authorization.subject_entity_id,
            )
            committee_role_claims = await self._committee_role_claims(
                conn,
                member_claim_ids=member_claim_ids,
                scope=WorkspaceScope.for_workspace(authorization.workspace_id),
            )
            committee_needs_review = max(
                0,
                len(state.committee_member_ids)
                - len(self._inferred_committee_member_ids(committee_role_claims)),
            )
            review_flags = list(committee_flags)
            if committee_needs_review:
                committee_status = "needs_review"
                review_flags.append("committee_roles_uninferred")
            if unresolved_field_keys:
                review_flags.append("account_fields_unresolved")

            result_ids = [UUID(ref.removeprefix("research-result:")) for ref in state.result_refs]
            claim_ids = tuple(
                str(value)
                for value in (
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT unnest(claim_refs) "
                                "FROM entity_research_result_field "
                                "WHERE result_id=ANY(:result_ids) ORDER BY 1"
                            ),
                            {"result_ids": result_ids},
                        )
                    )
                    .scalars()
                    .all()
                )
            )
            evidence_ids = tuple(
                str(value)
                for value in (
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT evidence_id FROM entity_research_result_evidence "
                                "WHERE result_id=ANY(:result_ids) ORDER BY 1"
                            ),
                            {"result_ids": result_ids},
                        )
                    )
                    .scalars()
                    .all()
                )
            )
            # A born-complete field's evidence is the claim that made it complete: fold those claim
            # ids into the ledger so the coverage cites what stood in for the research spend, and
            # the finalization engine can verify it (FI-2 §6.1, the contact runtime's mechanism).
            existing_claim_ids = tuple(
                item.claim_ref.removeprefix("claim:")
                for item in (*state.existing_claims, *non_acquisition_existing)
                if item.born_complete and item.field_key in set(completed_field_keys)
            )
            derived_claim_ids = tuple(
                str(item.claim_id) for item in derivation if item.claim_id is not None
            )
            committee_role_claim_ids = tuple(str(claim.id) for claim in committee_role_claims)
            claim_ids = tuple(
                dict.fromkeys(
                    (
                        *claim_ids,
                        *existing_claim_ids,
                        *derived_claim_ids,
                        *committee_role_claim_ids,
                    )
                )
            )
            projection = AccountCoverageProjection(
                coverage_id=coverage_id,
                coverage_ledger_ref=f"account-coverage:{coverage_id}",
                current_state_sha256=state.current_state_sha256,
                completed_field_keys=completed_field_keys,
                unresolved_field_keys=unresolved_field_keys,
                unresolved_reasons=tuple(unresolved_reasons),
                skipped_field_reasons=skipped_field_reasons,
                committee_result_refs=state.committee_result_refs,
                committee_member_ids=state.committee_member_ids,
                committee_status=cast(Any, committee_status),
                committee_needs_review=committee_needs_review,
                claim_refs=tuple(f"claim:{value}" for value in claim_ids),
                evidence_refs=tuple(f"research-evidence:{value}" for value in evidence_ids),
                review_flags=tuple(dict.fromkeys(review_flags)),
                review_item_refs=(),
                assessment_note=inputs.assessment_note,
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_coverage
                        (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                         result_refs, completed_field_keys, unresolved_field_keys,
                         unresolved_reasons, committee_result_refs, committee_member_ids,
                         committee_status, review_flags, claim_refs, evidence_refs,
                         coverage_json, coverage_sha256)
                    VALUES
                        (:coverage_id, :research_run_id, :job_id, :workspace_id, :account_id,
                         :result_refs, :completed, :unresolved, :reasons, :committee_refs,
                         :member_ids, :committee_status, :review_flags, :claim_refs,
                         :evidence_refs, CAST(:coverage_json AS jsonb), :coverage_sha256)
                    """
                ),
                {
                    "coverage_id": coverage_id,
                    "research_run_id": authorization.research_run_id,
                    "job_id": authorization.job_id,
                    "workspace_id": authorization.workspace_id,
                    "account_id": authorization.subject_entity_id,
                    "result_refs": list(state.result_refs),
                    "completed": list(completed_field_keys),
                    "unresolved": list(unresolved_field_keys),
                    "reasons": unresolved_reasons,
                    "committee_refs": list(state.committee_result_refs),
                    "member_ids": list(state.committee_member_ids),
                    "committee_status": committee_status,
                    "review_flags": review_flags,
                    "claim_refs": list(projection.claim_refs),
                    "evidence_refs": list(projection.evidence_refs),
                    "coverage_json": serialize_value_json(projection.model_dump(mode="json")),
                    "coverage_sha256": canonical_sha256(projection),
                },
            )
            review_refs: list[str] = []
            for flag in projection.review_flags:
                review_id = uuid4()
                await conn.execute(
                    text(
                        """
                        INSERT INTO entity_research_account_review_item
                            (review_item_id, coverage_id, research_run_id, job_id, workspace_id,
                             account_entity_id, reason_code, details_json)
                        VALUES (:review_id, :coverage_id, :run_id, :job_id, :workspace_id,
                                :account_id, :reason, CAST(:details AS jsonb))
                        """
                    ),
                    {
                        "review_id": review_id,
                        "coverage_id": coverage_id,
                        "run_id": authorization.research_run_id,
                        "job_id": authorization.job_id,
                        "workspace_id": authorization.workspace_id,
                        "account_id": authorization.subject_entity_id,
                        "reason": flag,
                        "details": serialize_value_json(
                            {"coverage_ref": projection.coverage_ledger_ref, "reason": flag}
                        ),
                    },
                )
                review_refs.append(f"account-review:{review_id}")
            digest = await self._refresh_account_state(conn, authorization.job_id)
        return projection.model_copy(
            update={"current_state_sha256": digest, "review_item_refs": tuple(review_refs)}
        )

    async def propose(self, inputs: FinalizeAccountResearchInput) -> ResearchFinalizationProposal:
        active = self._active_account()
        authorization = active.context.authorization
        coverage_id = self._ref_uuid(inputs.coverage_ledger_ref, "account-coverage:")
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT coverage_id, completed_field_keys, unresolved_field_keys,
                                   unresolved_reasons, committee_status, review_flags,
                                   claim_refs, evidence_refs, result_refs
                            FROM entity_research_account_coverage
                            WHERE coverage_id=:coverage_id AND job_id=:job_id
                              AND research_run_id=:run_id AND workspace_id=:workspace_id
                              AND account_entity_id=:account_id
                            """
                        ),
                        {
                            "coverage_id": coverage_id,
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "account_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AccountResearchAuthorityError("finalization cites foreign coverage")
            pending = await self._pending_refs(conn, authorization.job_id)
            if pending:
                raise AccountResearchAuthorityError("finalization cannot retain pending operations")
            state_sha = str(
                (
                    await conn.execute(
                        text(
                            "SELECT current_state_sha256 FROM entity_research_job "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            unresolved = tuple(str(value) for value in row["unresolved_field_keys"])
            review_flags = tuple(str(value) for value in row["review_flags"])
            expected_outcome = (
                ResearchFinalizationOutcome.NEEDS_REVIEW
                if review_flags or unresolved or str(row["committee_status"]) != "complete"
                else ResearchFinalizationOutcome.COMPLETED
            )
            # The outcome is engine-derived from the persisted coverage; the model's requested
            # value never reaches the proposal. Refusing a mismatch here only quizzed the model on
            # a fact it does not own — observed live: an agent asked for `completed`, was refused,
            # and went back to re-buying terminally-unproductive fields to "earn" it, looping until
            # the graph recursion cap suspended the job. The engine disposes: the proposal carries
            # the honest derived outcome and the tool result is the correction the model reads.
            proposal_id = uuid5(
                _PROPOSAL_NAMESPACE,
                f"{authorization.job_id}:{coverage_id}:{state_sha}:{expected_outcome.value}",
            )
            proposal = ResearchFinalizationProposal(
                proposal_id=proposal_id,
                subject_type=ResearchSubjectType.ACCOUNT,
                target_entity_id=authorization.subject_entity_id,
                outcome=expected_outcome,
                current_state_sha256=state_sha,
                coverage_ledger_ref=inputs.coverage_ledger_ref,
                claim_delta_ledger_ref=f"account-claim-delta-ledger:{coverage_id}",
                spend_reconciliation_ref=f"account-spend-reconciliation:{coverage_id}",
                identity_use_verification_ref=f"account-identity-use-verification:{coverage_id}",
                completed_field_keys=tuple(str(value) for value in row["completed_field_keys"]),
                unresolved_field_keys=unresolved,
                claim_refs=tuple(str(value) for value in row["claim_refs"]),
                evidence_refs=tuple(str(value) for value in row["evidence_refs"]),
                result_refs=tuple(str(value) for value in row["result_refs"]),
                unresolved_reasons=tuple(str(value) for value in row["unresolved_reasons"]),
                review_flags=review_flags,
            )
            values = {
                "proposal_id": proposal_id,
                "coverage_id": coverage_id,
                "run_id": authorization.research_run_id,
                "job_id": authorization.job_id,
                "workspace_id": authorization.workspace_id,
                "account_id": authorization.subject_entity_id,
                "state_sha": state_sha,
                "proposal_json": serialize_value_json(proposal.model_dump(mode="json")),
                "proposal_sha": canonical_sha256(proposal),
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_finalization_intent
                        (proposal_id, coverage_id, research_run_id, job_id, workspace_id,
                         account_entity_id, current_state_sha256, proposal_json, proposal_sha256)
                    VALUES (:proposal_id, :coverage_id, :run_id, :job_id, :workspace_id,
                            :account_id, :state_sha, CAST(:proposal_json AS jsonb), :proposal_sha)
                    ON CONFLICT (proposal_id) DO NOTHING
                    """
                ),
                values,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT proposal_json, proposal_sha256 FROM "
                            "entity_research_account_finalization_intent "
                            "WHERE proposal_id=:proposal_id"
                        ),
                        {"proposal_id": proposal_id},
                    )
                )
                .mappings()
                .one()
            )
            if str(stored["proposal_sha256"]) != canonical_sha256(proposal):
                raise AccountResearchAuthorityError("finalization proposal replay changed")
        return ResearchFinalizationProposal.model_validate(stored["proposal_json"])

    async def _refresh_account_state(self, conn: AsyncConnection, job_id: UUID) -> str:
        initial = str(
            (
                await conn.execute(
                    text(
                        "SELECT initial_state_sha256 FROM entity_research_job "
                        "WHERE job_id=:job_id FOR UPDATE"
                    ),
                    {"job_id": job_id},
                )
            ).scalar_one()
        )
        request_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT tool_request_id, tool_input_sha256, idempotency_key, "
                        "parent_operation_ref, parent_observation_ref, prior_result_sha256 "
                        "FROM entity_research_tool_request WHERE job_id=:job_id "
                        "ORDER BY created_at, tool_request_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        observation_rows = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT observation.tool_request_id, observation.provider_operation_ref,
                               observation.disposition, operation.provider_kind,
                               operation.source_key, operation.field_keys,
                               operation.request_artifact_ref, operation.reserved_at,
                               operation.dispatched_at
                        FROM entity_research_provider_observation observation
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=observation.tool_request_id
                        JOIN entity_research_provider_operation operation
                          ON operation.operation_ref=observation.provider_operation_ref
                        WHERE request_row.job_id=:job_id
                        ORDER BY observation.created_at, observation.observation_id
                        """
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        result_rows = await self._result_rows(conn, job_id)
        scope_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT tool_request_id, scope_sha256 FROM "
                        "entity_research_account_committee_scope WHERE job_id=:job_id "
                        "ORDER BY created_at, scope_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        coverage_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT coverage_id, coverage_sha256 FROM entity_research_account_coverage "
                        "WHERE job_id=:job_id ORDER BY created_at, coverage_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        digest = canonical_sha256(
            {
                "contract": "m8d-account-research-state-r5-v1",
                "initial_state_sha256": initial,
                "requests": [self._json_row(row) for row in request_rows],
                "observations": [self._json_row(row) for row in observation_rows],
                "results": [self._json_row(row) for row in result_rows],
                "committee_scopes": [self._json_row(row) for row in scope_rows],
                "coverage": [self._json_row(row) for row in coverage_rows],
            }
        )
        await conn.execute(
            text(
                "UPDATE entity_research_job SET current_state_sha256=:digest, "
                "updated_at=now() WHERE job_id=:job_id"
            ),
            {"digest": digest, "job_id": job_id},
        )
        return digest

    @staticmethod
    async def _committee_member_claim_ids(
        conn: AsyncConnection,
        *,
        job_id: UUID,
        account_entity_id: UUID,
    ) -> dict[UUID, frozenset[ClaimId]]:
        """Exact discovered-member -> own professional-claim authority for one account job."""

        rows = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT field.target_entity_id, field.claim_refs
                        FROM entity_research_result_field field
                        JOIN entity_research_result result ON result.result_id=field.result_id
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=result.tool_request_id
                        WHERE request_row.job_id=:job_id
                          AND request_row.tool_name='discover_buying_committee'
                          AND field.subject_type='contact'
                          AND field.parent_account_id=:account_id
                        ORDER BY result.created_at, result.result_id, field.ordinal
                        """
                    ),
                    {"job_id": job_id, "account_id": account_entity_id},
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[UUID, set[ClaimId]] = {}
        for row in rows:
            grouped.setdefault(UUID(str(row["target_entity_id"])), set()).update(
                ClaimId(UUID(str(value))) for value in row["claim_refs"]
            )
        return {contact_id: frozenset(values) for contact_id, values in grouped.items()}

    @staticmethod
    async def _committee_role_claims(
        conn: AsyncConnection,
        *,
        member_claim_ids: Mapping[UUID, frozenset[ClaimId]],
        scope: WorkspaceScope,
    ) -> tuple[Claim, ...]:
        """Current role/persona claims in the same run as this job's discovered-member evidence."""

        if not member_claim_ids:
            return ()
        evidence = await claims_by_ids(
            conn,
            {claim_id for values in member_claim_ids.values() for claim_id in values},
            scope=scope,
        )
        allowed_runs = {
            EntityId(contact_id): {
                evidence[claim_id].run_id for claim_id in claim_ids if claim_id in evidence
            }
            for contact_id, claim_ids in member_claim_ids.items()
        }
        claims = await claims_for_entities(
            conn,
            [EntityId(value) for value in member_claim_ids],
            (ROLE_ON_COMMITTEE, PERSONA),
            scope=scope,
        )
        return tuple(
            claim for claim in claims if claim.run_id in allowed_runs.get(claim.entity_id, set())
        )

    @staticmethod
    def _inferred_committee_member_ids(claims: Sequence[Claim]) -> frozenset[UUID]:
        """Members carrying the complete role/persona pair; either half stays reviewable."""

        role_members = {
            UUID(str(claim.entity_id))
            for claim in claims
            if str(claim.field_key) == ROLE_ON_COMMITTEE
        }
        persona_members = {
            UUID(str(claim.entity_id)) for claim in claims if str(claim.field_key) == PERSONA
        }
        return frozenset(role_members & persona_members)

    @staticmethod
    async def _result_rows(conn: AsyncConnection, job_id: UUID) -> Sequence[RowMapping]:
        return (
            (
                await conn.execute(
                    text(
                        """
                        SELECT result.result_id, result.tool_request_id,
                               result.provider_operation_ref, result.provider_snapshot_ref,
                               result.result_sha256, result.delivery, request_row.tool_name
                        FROM entity_research_result result
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=result.tool_request_id
                        WHERE request_row.job_id=:job_id
                        ORDER BY result.created_at DESC, result.result_id DESC
                        """
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _committee_coverage_status(
        *,
        committee_requested: bool = True,
        result_count: int,
        member_count: int,
        scope_count: int,
        ambiguous_count: int,
        confirmed_empty_count: int,
        provider_unavailable_reasons: tuple[str, ...] = (),
    ) -> tuple[str, tuple[str, ...]]:
        if not committee_requested:
            return "complete", ()
        if result_count == 0:
            # ``committee_not_researched`` is true but mute. When the axis went terminal because
            # the provider cannot serve this account at all, the ledger says which world fact it
            # was, so the review surface shows a reviewer the difference between "nobody tried"
            # and "the provider has no such organization".
            if provider_unavailable_reasons:
                return "needs_review", provider_unavailable_reasons
            return "needs_review", ("committee_not_researched",)
        if scope_count != result_count:
            return "needs_review", ("committee_scope_missing_or_ambiguous",)
        if ambiguous_count:
            return "needs_review", ("committee_office_candidates_ambiguous",)
        if member_count:
            return "complete", ()
        if confirmed_empty_count == result_count:
            return "complete", ()
        return "partial", ("committee_no_identity_admitted_member",)

    @staticmethod
    async def _field_rows(conn: AsyncConnection, job_id: UUID) -> Sequence[RowMapping]:
        return (
            (
                await conn.execute(
                    text(
                        """
                        SELECT field.field_key, field.outcome, field.verification_status,
                               field.subject_type, field.target_entity_id,
                               result.created_at, result.result_id
                        FROM entity_research_result_field field
                        JOIN entity_research_result result ON result.result_id=field.result_id
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=result.tool_request_id
                        WHERE request_row.job_id=:job_id
                        ORDER BY result.created_at DESC, result.result_id DESC, field.ordinal
                        """
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    async def _pending_refs(conn: AsyncConnection, job_id: UUID) -> Sequence[str]:
        # Shares one body with the finalization guard's ``pending_operations`` count; see
        # ``pending_provider_operations_sql``.
        return tuple(
            str(value)
            for value in (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT provider_operation_ref FROM ("
                            f"{pending_provider_operations_sql(':job_id')}"
                            ") pending ORDER BY provider_operation_ref"
                        ),
                        {"job_id": job_id},
                    )
                )
                .scalars()
                .all()
            )
        )

    @staticmethod
    def _json_row(row: Mapping[str, object] | RowMapping) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            {
                key: str(value) if isinstance(value, (UUID, Decimal, datetime)) else value
                for key, value in row.items()
            },
        )

    @staticmethod
    def _ref_uuid(reference: str, prefix: str) -> UUID:
        if not reference.startswith(prefix):
            raise AccountResearchAuthorityError("reference uses the wrong account-research scheme")
        try:
            return UUID(reference.removeprefix(prefix))
        except ValueError as exc:
            raise AccountResearchAuthorityError("account-research reference is malformed") from exc


class AccountResearchExecutionGuard(EntityResearchExecutionGuard):
    """R5 purpose/source/bundle/order guard; R9 owns atomic parallel budget hardening."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def authorize_parallel(
        self, *, context: EntityResearchRuntimeContext, calls: Sequence[EntityResearchToolCall]
    ) -> None:
        if context.authorization.subject_type is not ResearchSubjectType.ACCOUNT:
            raise AccountResearchAuthorityError("account guard received another subject type")
        names = [call.tool_name for call in calls]
        duplicates = {
            name for name in names if names.count(name) > 1 and name not in _READ_ONLY_TOOL_NAMES
        }
        if duplicates:
            if duplicates != {"enrich_account"}:
                raise AccountResearchAuthorityError(
                    "one model round cannot duplicate account provider work"
                )
            source_sets = [
                set(cast(Sequence[str], call.arguments.get("source_keys", ())))
                for call in calls
                if call.tool_name == "enrich_account"
            ]
            if any(not source_keys for source_keys in source_sets) or any(
                left & right
                for index, left in enumerate(source_sets)
                for right in source_sets[index + 1 :]
            ):
                raise AccountResearchAuthorityError(
                    "parallel account enrichment calls require disjoint structured sources"
                )
        if "assess_account_coverage" in names and len(names) > 1:
            raise AccountResearchAuthorityError("coverage must follow settled provider results")
        if "finalize_account_research" in names and len(names) > 1:
            raise AccountResearchAuthorityError("finalization is a dependent terminal decision")

    async def authorize_tool(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        journal_event_ref: str,
    ) -> None:
        del journal_event_ref
        if any(call.tool_name.startswith(prefix) for prefix in _CONTACT_TOOL_PREFIXES):
            raise AccountResearchAuthorityError("account agent cannot perform contact research")
        sources = set(cast(Sequence[str], call.arguments.get("source_keys", ())))
        fields = set(cast(Sequence[str], call.arguments.get("field_keys", ())))
        if call.tool_name == "research_account_deep":
            if sources != {_QUALITATIVE_SOURCE}:
                raise AccountResearchAuthorityError("qualitative account research uses Exa Deep")
            if not fields:
                # A zero-field bundle buys nothing and cannot be repaired downstream:
                # ``EntityResearchSemanticToolInput.field_keys`` has no minimum length and the
                # record-time field/source pairing check is itself conditional on a non-empty
                # ``field_keys``, so the call would reach the Exa action and die there on
                # ``EntityResearchResultIntegrityError`` — the *suspending* species under R10.
                # The first-call rule used to catch it as a side effect; net of the borrowed set
                # a wholly-borrowed account has an empty ``primary``, so it no longer does.
                # Refuse it here instead, as the turn the agent can act on: the correct move on an
                # all-borrowed account is to finalize, not to call with nothing.
                raise AccountResearchAuthorityError(
                    "Exa account research needs at least one field to buy"
                )
            # FI-2 §6.2: the borrowed set — admitted fields a fresh, evidence-backed,
            # conflict-free *neutral* claim already answers.  The M8D Exa bundle is compiled
            # straight from ``field_keys``, and Exa (unlike Sumble, whose own preflight refuses a
            # fresh field under §6.3) has no provider-side freshness check, so this guard is the
            # only layer that can keep the invariant "no provider is paid for a born-complete
            # field" on the qualitative path.  It is also why the first-call rule below is stated
            # *net* of the borrowed set: the agent sees exactly these fields as already complete
            # in its state read, so a prompt-obedient omission must pass, not cost a turn.
            #
            # Every fact the three rules below weigh is read on **one** connection, inside one
            # transaction: the borrowed set and the prior-call history decide the same question
            # ("what is left to buy?"), and reading them on two connections could interleave a
            # concurrent write between them and answer it inconsistently.  The injected factory is
            # ``clue_db.transaction`` in production, which is READ COMMITTED: this is one
            # transaction, not one snapshot — each statement
            # still sees its own snapshot; the guarantee here is that they are ordered, not
            # that they are simultaneous.  (``repeatable_read_transaction`` exists for the
            # stronger property and is deliberately not used: the guard reads far less than it
            # would cost to serialize.)
            async with self._conn_factory() as conn:
                borrowed = await born_complete_account_field_keys(
                    conn,
                    workspace_id=str(context.authorization.workspace_id),
                    account_entity_id=context.authorization.subject_entity_id,
                    field_keys=context.authorization.selection.admitted_field_keys,
                )
                prior = int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM entity_research_tool_request "
                                "WHERE job_id=:job_id AND tool_name='research_account_deep'"
                            ),
                            {"job_id": context.authorization.job_id},
                        )
                    ).scalar_one()
                )
                prior_structured_fields = set(
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT unnest(field_keys) FROM "
                                "entity_research_tool_request WHERE job_id=:job_id "
                                "AND NOT (:exa = ANY(source_keys))"
                            ),
                            {
                                "job_id": context.authorization.job_id,
                                "exa": _QUALITATIVE_SOURCE,
                            },
                        )
                    ).scalars()
                )
            already_known = fields & borrowed
            if already_known:
                raise AccountResearchAuthorityError(
                    "Exa account research cannot re-buy a field an existing fresh claim already "
                    f"answers: {', '.join(sorted(already_known))}"
                )
            exa_authority = {
                item.field_key: item.source_keys
                for item in context.authorization.selection.field_source_authority
                if _QUALITATIVE_SOURCE in item.source_keys
            }
            primary = {
                field_key
                for field_key, source_keys in exa_authority.items()
                if source_keys[0] == _QUALITATIVE_SOURCE
            } - borrowed
            # A borrowed Exa-primary field would fall out of ``primary`` and land here as if it
            # were a fallback; it cannot, because ``already_known`` refused the call above.
            fallback = fields - primary
            if fallback - prior_structured_fields:
                raise AccountResearchAuthorityError(
                    "Exa fallback fields require a preceding structured-source attempt"
                )
            if prior == 0 and primary - fields:
                raise AccountResearchAuthorityError(
                    "first Exa account call must include every primary Exa field"
                )
        elif call.tool_name == "enrich_account" and _QUALITATIVE_SOURCE in sources:
            raise AccountResearchAuthorityError("structured enrichment is independent of Exa Deep")
        elif call.tool_name == "discover_buying_committee":
            scope = call.arguments.get("buying_unit_scope")
            if scope is not None and not isinstance(scope, dict):
                raise AccountResearchAuthorityError(
                    "committee discovery's buying_unit_scope must be an object, or omitted "
                    "entirely so the engine composes it"
                )
            declared = scope.get("account_entity_id") if isinstance(scope, dict) else None
            # An omitted account is now the *engine's* to fill (founder ruling 2026-08-20): the job
            # is bound to exactly one account, so restating it was ceremony. A declared account is
            # still an assertion, and a foreign one is still refused here and again at the
            # provider action's account/people/scope authority check.
            if declared is not None and str(declared) != str(
                context.authorization.subject_entity_id
            ):
                raise AccountResearchAuthorityError(
                    "committee discovery requires the exact account buying-unit scope: "
                    "buying_unit_scope.account_entity_id must be "
                    f"{context.authorization.subject_entity_id} (this job's account, as "
                    "read_account_research_state reports it), or omitted so the engine fills it"
                )
        elif call.tool_name in {"assess_account_coverage", "finalize_account_research"}:
            async with self._conn_factory() as conn:
                pending = await AccountResearchStateStore._pending_refs(
                    conn, context.authorization.job_id
                )
            if pending:
                raise AccountResearchAuthorityError("dependent account decision has pending work")
        async with self._conn_factory() as conn:
            closed = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_account_coverage "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": context.authorization.job_id},
                    )
                ).scalar_one()
            )
        if closed and call.tool_name in {
            "research_account_deep",
            "enrich_account",
            "discover_buying_committee",
            "record_committee_role_inferences",
        }:
            raise AccountResearchAuthorityError(
                "account research cannot resume after coverage close"
            )

    async def observe_tool_result(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None:
        del context, call, result


class AccountResearchFinalizationEngine(EntityResearchFinalizationEngine):
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def accept(
        self, *, context: EntityResearchRuntimeContext, proposal: ResearchFinalizationProposal
    ) -> ResearchFinalizationReceipt:
        authorization = context.authorization
        if (
            authorization.subject_type is not ResearchSubjectType.ACCOUNT
            or proposal.subject_type is not ResearchSubjectType.ACCOUNT
            or proposal.target_entity_id != authorization.subject_entity_id
        ):
            raise EntityResearchFinalizationRejected(
                "account finalization widens subject authority"
            )
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT intent.proposal_json, intent.proposal_sha256,
                                   intent.current_state_sha256, coverage.committee_status,
                                   coverage.completed_field_keys,
                                   job.current_state_sha256 AS job_state,
                                   job.spent_cents AS job_spent_cents,
                                   run.spent_cents AS run_spent_cents,
                                   (SELECT COALESCE(sum(fold.settled_cost_cents), 0)
                                    FROM entity_research_provider_settlement_fold fold
                                    WHERE fold.job_id=intent.job_id
                                   ) AS result_spent_cents,
                                   (SELECT COALESCE(sum(run_job.spent_cents), 0)
                                    FROM entity_research_job run_job
                                    WHERE run_job.research_run_id=intent.research_run_id
                                   ) AS run_job_spent_cents,
                                   (SELECT count(*) FROM entity_research_account_review_item review
                                    WHERE review.coverage_id=coverage.coverage_id
                                      AND review.state='open') AS open_reviews,
                                   (SELECT count(*) FROM entity_research_tool_request request_row
                                    WHERE request_row.research_run_id=intent.research_run_id
                                      AND request_row.subject_type='contact') AS contact_requests,
                                   -- Shares one body with ``_pending_refs``; see
                                   -- ``pending_provider_operations_sql``.
                                   (SELECT count(*) FROM (
                                    """
                            + pending_provider_operations_sql("intent.job_id")
                            + """
                                   ) pending) AS pending_operations
                                   ,ARRAY(SELECT DISTINCT result_field.field_key
                                     FROM entity_research_result_field result_field
                                     JOIN entity_research_result result
                                       ON result.result_id=result_field.result_id
                                     JOIN entity_research_result_evidence evidence
                                       ON evidence.result_id=result_field.result_id
                                      AND evidence.field_ordinal=result_field.ordinal
                                     WHERE 'research-result:' || result.result_id::text =
                                           ANY(coverage.result_refs)
                                       AND result_field.subject_type='account'
                                       AND result_field.target_entity_id=intent.account_entity_id
                                       AND result_field.outcome='found') AS result_evidence_fields
                                   ,(SELECT count(*)
                                     FROM unnest(coverage.completed_field_keys) completed(field_key)
                                     WHERE NOT EXISTS (
                                         SELECT 1
                                         FROM entity_research_result_field result_field
                                         JOIN entity_research_result result
                                           ON result.result_id=result_field.result_id
                                         JOIN entity_research_result_evidence evidence
                                           ON evidence.result_id=result_field.result_id
                                          AND evidence.field_ordinal=result_field.ordinal
                                         WHERE 'research-result:' || result.result_id::text =
                                               ANY(coverage.result_refs)
                                           AND result_field.subject_type='account'
                                           AND result_field.target_entity_id=
                                               intent.account_entity_id
                                           AND result_field.field_key=completed.field_key
                                           AND result_field.outcome='found'
                                     )
                                     -- FI-2 §6.1: a field this job never researched is evidenced
                                     -- by the live claim the coverage cited instead of spending
                                     -- (born-complete). The claim must still be visible to this
                                     -- workspace and carry an evidence span, so "completed" never
                                     -- means "asserted without evidence".
                                     AND NOT EXISTS (
                                         SELECT 1 FROM claim existing
                                         WHERE 'claim:' || existing.id::text =
                                               ANY(coverage.claim_refs)
                                           AND existing.entity_id=intent.account_entity_id
                                           AND existing.field_key=completed.field_key
                                           AND existing.superseded_by IS NULL
                                           AND existing.evidence_span IS NOT NULL
                                           AND btrim(existing.evidence_span)<>''
                                           AND (existing.reuse_scope='public_footprint'
                                                OR existing.workspace_id=intent.workspace_id)
                                     )) AS missing_completed_evidence
                            FROM entity_research_account_finalization_intent intent
                            JOIN entity_research_account_coverage coverage
                              ON coverage.coverage_id=intent.coverage_id
                            JOIN entity_research_job job ON job.job_id=intent.job_id
                            JOIN entity_research_run run
                              ON run.research_run_id=intent.research_run_id
                            WHERE intent.proposal_id=:proposal_id AND intent.job_id=:job_id
                              AND intent.research_run_id=:run_id
                              AND intent.workspace_id=:workspace_id
                              AND intent.account_entity_id=:account_id
                            """
                        ),
                        {
                            "proposal_id": proposal.proposal_id,
                            "job_id": authorization.job_id,
                            "run_id": authorization.research_run_id,
                            "workspace_id": authorization.workspace_id,
                            "account_id": authorization.subject_entity_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            # The engine re-derives the skip rule itself rather than trusting the coverage: every
            # completed field with no result of its own must still be answered, right now, by a
            # fresh, evidence-backed, conflict-free *neutral* claim (FI-2 §6.1).
            existing_completed = (
                frozenset()
                if row is None
                else frozenset(row["completed_field_keys"])
                - frozenset(row["result_evidence_fields"])
            )
            current = (
                {}
                if not existing_completed
                else await current_values(
                    conn,
                    [EntityId(authorization.subject_entity_id)],
                    existing_completed,
                    scope=WorkspaceScope.for_workspace(str(authorization.workspace_id)),
                )
            )
            species = (
                {}
                if not existing_completed
                else await field_species(
                    conn,
                    workspace_id=str(authorization.workspace_id),
                    field_keys=sorted(existing_completed),
                )
            )
            # The coverage axis is the admitted (paid) field set plus every confirmed
            # zero-acquisition §3.1 row (canonical name and both derived bands). The engine
            # re-reads that durable authority itself rather than trusting the coverage row.
            non_acquisition_axis = frozenset(
                await non_acquisition_account_profile_fields(conn, authorization=authorization)
            )
            execution = await read_account_research_execution_completeness(
                conn, authorization=authorization
            )
        if (
            row is None
            or ResearchFinalizationProposal.model_validate(row["proposal_json"]) != proposal
        ):
            raise EntityResearchFinalizationRejected(
                "model finalization lacks the exact engine-tool proposal intent"
            )
        borrowable = {
            key
            for (_entity_id, key), value in current.items()
            if value.freshness_state.value == "fresh"
            and value.provenance.evidence_span
            and not value.conflict
        }
        relative_borrowed = {
            key
            for key in existing_completed
            # Fail closed, like the other two species lookups (the §6.1 state read and the §6.3
            # Sumble ladder): an unresolvable species is treated as *relative*, the species that
            # may never close a field with another project's claim. ``field_species`` answers for
            # every declared field, so this default is unreachable today; if it ever becomes
            # reachable, "we cannot tell whose answer this is" must not buy the borrow.
            if species.get(key, ResearchScope.PROJECT_RELATIVE) is not ResearchScope.PROJECT_NEUTRAL
        }
        no_pending = int(row["pending_operations"]) == 0
        state_matches = (
            str(row["job_state"])
            == proposal.current_state_sha256
            == str(row["current_state_sha256"])
        )
        coverage_matches = (
            set(proposal.completed_field_keys + proposal.unresolved_field_keys)
            == set(authorization.selection.admitted_field_keys) | non_acquisition_axis
            and execution.complete
        )
        review_shape = (
            proposal.outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
            and int(row["open_reviews"]) > 0
        ) or (
            proposal.outcome is ResearchFinalizationOutcome.COMPLETED
            and int(row["open_reviews"]) == 0
        )
        verification = FinalizationVerification(
            no_pending_operations=no_pending,
            evidence_complete=(
                int(row["missing_completed_evidence"]) == 0 and existing_completed <= borrowable
            ),
            coverage_matches=coverage_matches and review_shape,
            spend_reconciled=(
                no_pending
                and Decimal(row["job_spent_cents"]) == Decimal(row["result_spent_cents"])
                and Decimal(row["run_spent_cents"]) == Decimal(row["run_job_spent_cents"])
            ),
            identity_use_verification_complete=(
                bool(proposal.identity_use_verification_ref)
                and str(row["committee_status"]) in {"complete", "partial", "needs_review"}
            ),
            # A project-relative field is this project's own question: no other project's claim,
            # however fresh, may close it (FI-2 §6.1 / R3).
            policy_scope_respected=int(row["contact_requests"]) == 0 and not relative_borrowed,
            current_state_matches=state_matches,
        )
        if not verification.all_passed():
            raise EntityResearchFinalizationRejected(
                f"account finalization verification failed: {verification.model_dump()}"
            )
        receipt_id = uuid5(_RECEIPT_NAMESPACE, str(proposal.proposal_id))
        return ResearchFinalizationReceipt(
            receipt_id=receipt_id,
            proposal=proposal,
            proposal_ref=f"account-finalization-proposal:{proposal.proposal_id}",
            engine_actor="account-research-finalization-engine@1",
            accepted_at=datetime.now(UTC),
            accepted_state_sha256=proposal.current_state_sha256,
            verification=verification,
        )


def account_engine_tool_bindings(
    store: AccountResearchStateStore,
) -> Mapping[str, EntityResearchToolBinding]:
    def repairable(
        coroutine: Callable[..., Awaitable[dict[str, JsonValue]]],
    ) -> Callable[..., Awaitable[dict[str, JsonValue]]]:
        governed = convert_engine_authority_rejections(
            coroutine,
            error_types=(AccountResearchAuthorityError,),
        )

        @functools.wraps(governed)
        async def guarded(*args: object, **kwargs: object) -> dict[str, JsonValue]:
            try:
                return await governed(*args, **kwargs)
            except ValidationError as error:
                # These tools validate their own arguments inside the body, so a malformed
                # argument surfaces here rather than through LangChain's args_schema path (which
                # is bound to the same handler below). Either way it is a model mistake the agent
                # can repair — never an uncaught exception that kills a live research job.
                raise ToolException(semantic_validation_error(error)) from error
            except EntityResearchGovernedRejection as rejection:
                # Already the repairable species (e.g. a model-typed reference of the wrong
                # type) — but the engine-tool path has no downstream converter, so without this
                # it escaped raw and suspended the job (live: run 1d39023a, read_research_result
                # handed a sumble-account-operation ref). Render it as the error tool message the
                # species promises.
                raise ToolException(rejection.render()) from rejection

        return guarded

    async def read_state(include_result_index: bool = True) -> dict[str, JsonValue]:
        value = await store.state()
        payload = value.model_dump(mode="json")
        if not include_result_index:
            payload["result_refs"] = []
        return cast(dict[str, JsonValue], payload)

    async def inspect(**values: object) -> dict[str, JsonValue]:
        return await store.evidence(InspectAccountEvidenceInput.model_validate(values))

    async def assess(**values: object) -> dict[str, JsonValue]:
        coverage = await store.assess(AssessAccountCoverageInput.model_validate(values))
        return cast(dict[str, JsonValue], coverage.model_dump(mode="json"))

    async def record_inferences(**values: object) -> dict[str, JsonValue]:
        return await store.record_committee_role_inferences(
            RecordCommitteeRoleInferencesInput.model_validate(values)
        )

    async def finalize(**values: object) -> dict[str, JsonValue]:
        proposal = await store.propose(FinalizeAccountResearchInput.model_validate(values))
        return cast(dict[str, JsonValue], proposal.model_dump(mode="json"))

    tools = {
        "read_account_research_state": StructuredTool.from_function(
            coroutine=repairable(read_state),
            name="read_account_research_state",
            description=(
                "Read exact persisted account results, gaps, committee, pending work, and spend."
            ),
            args_schema=ReadAccountResearchStateInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "inspect_account_evidence": StructuredTool.from_function(
            coroutine=repairable(inspect),
            name="inspect_account_evidence",
            description="Inspect the complete evidence index for exact persisted account results.",
            args_schema=InspectAccountEvidenceInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "record_committee_role_inferences": StructuredTool.from_function(
            coroutine=repairable(record_inferences),
            name="record_committee_role_inferences",
            description=(
                "Record evidence-cited role judgments for exact members discovered by this "
                "account job; omit any member whose role cannot be supported."
            ),
            args_schema=RecordCommitteeRoleInferencesInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "assess_account_coverage": StructuredTool.from_function(
            coroutine=repairable(assess),
            name="assess_account_coverage",
            description="Derive durable account-field and office-coherent committee coverage.",
            args_schema=AssessAccountCoverageInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
        "finalize_account_research": StructuredTool.from_function(
            coroutine=repairable(finalize),
            name="finalize_account_research",
            description=(
                "Ask the engine once for the only admissible typed finalization proposal. "
                "Immediately emit the returned JSON unchanged through the "
                "ResearchFinalizationProposal response-format tool and stop."
            ),
            args_schema=FinalizeAccountResearchInput,
            handle_validation_error=semantic_validation_error,
            handle_tool_error=True,
        ),
    }
    return {name: EntityResearchToolBinding(tool=tool, version=1) for name, tool in tools.items()}


__all__ = [
    "AccountResearchAuthorityError",
    "AccountResearchExecutionCompleteness",
    "AccountResearchExecutionGuard",
    "AccountResearchFinalizationEngine",
    "AccountResearchStateStore",
    "account_engine_tool_bindings",
    "born_complete_account_field_keys",
    "committee_axis_unavailable_reasons",
    "committee_axis_unavailable_source_keys",
    "derivable_account_profile_fields",
    "existing_account_claims",
    "non_acquisition_account_profile_fields",
    "pinned_account_research_directive",
    "read_account_committee_plan",
    "read_account_research_execution_completeness",
]
