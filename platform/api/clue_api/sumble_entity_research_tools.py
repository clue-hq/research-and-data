"""M8D R5 Sumble account enrichment projection behind the provider-neutral R4 seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, NamedTuple, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import (
    AccountBuyingUnitScope,
    AccountBuyingUnitScopeRequest,
    DiscoverBuyingCommitteeInput,
)
from clue_agents.entity_research_runtime import current_entity_research_tool_execution
from clue_api.committee_eligibility import CommitteeEligibilityService
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchProviderAction,
    EntityResearchProviderWait,
    EntityResearchResultIntegrityError,
    ExternalResearchProjectionDraft,
    ProviderObservationDisposition,
    ProviderOperationObservation,
    ProviderOperationReservation,
    ProviderResultLineage,
    ProviderResultLineageReader,
)
from clue_api.sumble_account_gaps import (
    SumbleAccountGapFieldAlreadyAcquired,
    SumbleAccountGapNotEligible,
    SumbleAccountGapOutcome,
    SumbleAccountGapStarter,
)
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    SumbleCommitteePreflight,
)
from clue_api.sumble_committee_preparation import (
    COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
    SumbleCommitteePreparationInputs,
    SumbleCommitteeProviderIdentityUnavailable,
)
from clue_api.sumble_committee_source import SumbleCommitteeSource
from clue_core import (
    AccountGapFieldResult,
    AccountGapFieldState,
    AccountGapOperation,
    AccountGapOperationState,
    AccountGapSnapshotState,
    ClaimId,
    CommitteeAcquisitionOperation,
    CommitteeEligibilityOutcome,
    EntityId,
    LLMGateway,
    ProjectRunId,
    ResearchCommitteePlan,
    RunId,
    decode_jsonb,
    decode_jsonb_scalar,
    serialize_value_json,
)
from clue_core.entity_research import (
    GovernedResearchToolRequest,
    PersistedResearchToolResult,
    ResearchClaimDelta,
    ResearchDiscoveredSubjectProjection,
    ResearchEvidenceProjection,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchSubjectType,
)
from clue_obs import get_logger
from clue_research.claimstore import WorkspaceScope, current_values, record_run_lineage
from clue_research.durable import (
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    list_account_gap_field_results,
    list_account_gap_snapshots,
    list_committee_acquisition_snapshots,
)
from clue_research.identity import get_account
from clue_research.profiling.committee import (
    CURRENT_LOCATION,
    JOB_FUNCTION,
    ORGANIZATION_RELATIONSHIP,
    TEAM_MEMBERSHIP,
    CommitteePersonCandidate,
    CommitteeResult,
    CommitteeSource,
    discover_committee,
)
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_storage import StorageBackend, content_address, read_verified_artifact

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:sumble-account-evidence")
#: One tool call, one durable scope id. Derived rather than model-invented so a repeat committee
#: call can never reuse an earlier call's scope id (live run ``dc86340f``: the same invented uuid
#: rode four attempts against one account, which would have silently left the later attempts with
#: no scope row of their own and their coverage in ``committee_scope_missing_or_ambiguous``).
_COMMITTEE_SCOPE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:account-committee-scope")
_HQ_LOCATION_FIELD: Final[str] = "core.hq_location"
_MAX_SCOPE_EVIDENCE_REFS: Final[int] = 20
log = get_logger("clue_api.sumble_entity_research_tools")


def _hq_office_values(value: object) -> Mapping[str, str]:
    """The office discriminators an account's ``core.hq_location`` value actually evidences.

    The shape every writer of that field produces (``exa_websets_materialization``,
    ``sumble_discovery_gaps``) is ``{"raw", "city", "region", "country", "country_code"}``. Only
    what is present and non-empty is returned: the engine declares the office the account's own
    evidence supports and nothing beyond it.
    """

    if not isinstance(value, Mapping):
        return {}
    office: dict[str, str] = {}
    for claim_key, scope_key in (
        ("raw", "raw"),
        ("city", "locality"),
        ("region", "region"),
        ("country", "country"),
    ):
        item = value.get(claim_key)
        if isinstance(item, str) and item.strip():
            office[scope_key] = item.strip()
    return office


def _committee_unavailable_detail(error: SumbleCommitteeProviderIdentityUnavailable) -> str:
    """Tell the agent the axis is closed and name its one remaining move.

    The manual's loop rule is the whole point: a refusal that only states a fact invites the agent
    to re-send the identical call until the round budget dies (live jobs ``5d9dfe7b``/``16e846d6``
    did exactly that on a different committee refusal). This one says the attempt is durable and
    terminal, so the next call is coverage.
    """

    if error.code == COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED:
        cause = (
            "the committee provider's organization index has no exact match for this account, so "
            "no committee call can be made for it"
        )
    else:
        cause = (
            "no committee-provider organization identity exists for this account in any durable "
            "response, so no committee call can be made for it"
        )
    return (
        f"{cause} ({error.detail}). Nothing was spent and nothing is pending. This attempt is "
        "recorded and the committee axis is now terminal: the committee for this account is an "
        "honest gap. Do not call discover_buying_committee again - call assess_account_coverage "
        "and finalize."
    )


def _incomplete_scope_rejection(error: ValidationError) -> EntityResearchGovernedRejection:
    """Render a resolved-scope violation with the exact repair, never a bare schema echo."""

    items = error.errors(include_url=False, include_input=False)
    faults = "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'buying_unit_scope'}: {item['msg']}"
        for item in items
    )
    corrections = " ".join(
        dict.fromkeys(
            correction
            for item in items
            if (correction := DiscoverBuyingCommitteeInput.validation_correction(item["loc"]))
        )
    )
    return EntityResearchGovernedRejection(
        "committee_scope_incomplete",
        f"the buying unit this call resolves to is not complete ({faults}). {corrections}",
    )


async def resolve_account_buying_unit_scope(
    conn: AsyncConnection,
    *,
    request: GovernedResearchToolRequest,
    requested: AccountBuyingUnitScopeRequest,
    workspace_id: str,
) -> AccountBuyingUnitScope:
    """Complete the model's declaration into the durable scope, from state the engine already holds.

    Founder ruling 2026-08-20 — *the engine disposes, it never quizzes*. Five of the six values
    this scope used to demand were never the model's to know better than the engine: the scope id
    (this tool call), the account (the job is bound to exactly one), the office (the account's own
    ``core.hq_location`` evidence), and the evidence references (this job's own result index).
    Live run ``dc86340f`` paid for that: seven of eight committee calls died at the Pydantic
    boundary on a missing ``evidence_refs`` — no provider call, no operation, no spend — and one
    account burned its whole 900s runtime budget on four of them.

    What the model still owns is preserved exactly: ``target_functions`` (advisory judgment),
    ``match_policy``, and any deliberately narrower office or ``business_unit``. The engine fills
    what was omitted and never overwrites what was sent — a *wrong* declaration (a foreign
    ``account_entity_id``, an invented target function) still meets the same refusals it always
    did, downstream of here.

    Replay is durable-first: a scope already recorded for this tool request is returned exactly as
    it was stored, so a historical scope replays byte-identically no matter how the account's
    evidence has moved since, and ``scope_sha256`` stays stable for the job's state digest.
    """

    stored = (
        await conn.execute(
            text(
                "SELECT scope_json FROM entity_research_account_committee_scope "
                "WHERE tool_request_id=:tool_request_id"
            ),
            {"tool_request_id": request.tool_call_id},
        )
    ).scalar_one_or_none()
    if stored is not None:
        return AccountBuyingUnitScope.model_validate(decode_jsonb(stored))

    values = dict(requested.model_dump())
    values["scope_id"] = uuid5(_COMMITTEE_SCOPE_NAMESPACE, str(request.tool_call_id))
    if values["account_entity_id"] is None:
        values["account_entity_id"] = request.target_entity_id
    account_id = EntityId(request.target_entity_id)
    hq = (
        await current_values(
            conn,
            [account_id],
            [_HQ_LOCATION_FIELD],
            scope=WorkspaceScope.for_workspace(workspace_id),
        )
    ).get((account_id, _HQ_LOCATION_FIELD))
    office = _hq_office_values(hq.value_json) if hq is not None else {}
    if not any(
        values[key] is not None
        for key in ("office_label", "facility_name", "locality", "region", "country")
    ):
        # Only when the model declared no geography at all: a model that named one office must not
        # find a different city grafted onto it. ``business_unit`` is deliberately absent from that
        # test and never filled — it is the one discriminator that still narrows admission, so the
        # engine may not assert one on the agent's behalf.
        for key in ("locality", "region", "country"):
            values[key] = office.get(key)
    if values["office_label"] is None:
        account = await get_account(conn, account_id)
        values["office_label"] = office.get("raw") or (
            f"{account.canonical_name} (company-wide)" if account is not None else "company-wide"
        )
    if not values["evidence_refs"]:
        values["evidence_refs"] = await _composed_scope_evidence_refs(
            conn,
            request=request,
            hq_claim_id=None if hq is None else UUID(str(hq.provenance.claim_id)),
        )
        if not values["evidence_refs"]:
            # The honest answer, recorded rather than fabricated: this account job holds no result
            # and no current claim to cite, so the scope is persisted citing nothing and says so.
            # The empty ``evidence_refs`` in the durable ``scope_json`` IS the audit trail (and it
            # rides ``scope_sha256`` into the job's state digest). The alternative would be
            # inventing a reference; refusing the call outright would put the committee behind
            # research this job may not owe — an account whose every field was borrowed still owes
            # its committee attempt.
            log.warning(
                "committee_scope_evidence_unavailable",
                job_id=str(request.job_id),
                account_entity_id=str(request.target_entity_id),
                tool_request_id=str(request.tool_call_id),
                detail="the account job holds no persisted result and no current claim to cite",
            )
    try:
        return AccountBuyingUnitScope.model_validate(values)
    except ValidationError as error:
        raise _incomplete_scope_rejection(error) from error


async def _composed_scope_evidence_refs(
    conn: AsyncConnection,
    *,
    request: GovernedResearchToolRequest,
    hq_claim_id: UUID | None,
) -> tuple[str, ...]:
    """This job's own retained account evidence, in the exact forms ``_persist_scope`` admits.

    The HQ claim leads because it is the lineage of an engine-composed office; the job's persisted
    results follow in creation order. Both are re-validated by ``_persist_scope`` against the same
    job/account authority a model-authored reference meets, so composition can widen nothing.
    """

    refs: list[str] = []
    if hq_claim_id is not None:
        refs.append(f"claim:{hq_claim_id}")
    rows = (
        await conn.execute(
            text(
                "SELECT result.result_id FROM entity_research_result result "
                "JOIN entity_research_tool_request request_row "
                "ON request_row.tool_request_id=result.tool_request_id "
                "WHERE request_row.job_id=:job_id "
                "ORDER BY result.created_at, result.result_id"
            ),
            {"job_id": request.job_id},
        )
    ).scalars()
    refs.extend(f"research-result:{value}" for value in rows)
    return tuple(dict.fromkeys(refs))[:_MAX_SCOPE_EVIDENCE_REFS]


class _AdmittedProjection(NamedTuple):
    """What this provider operation's FIRST admitted result actually recorded."""

    snapshot_ref: str
    result: PersistedResearchToolResult


async def _first_admitted_projection(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    operation_ref: str,
) -> _AdmittedProjection | None:
    """The projection the operation's earliest ``entity_research_result`` admitted, or ``None``.

    The distinction the projection replay turns on. A projection is *history* only once a result
    carrying it reached a turn — that is what an ``entity_research_result`` row records, and what
    downstream consumed. An operation with no result row anywhere was shown to nobody, so its
    stored first draft is a failed draft, not a fact about the past.

    "A result exists" is NOT the same question as "the stored projection row is what was admitted",
    and live (job 3cc0a4f2, 06:37:33) they diverged permanently: operation 7e29c0bf's stored row
    was the pre-aa88e0b0 defective draft, its first replay served the fresh recomputation because
    nothing had been admitted yet, and the result admitted from THAT recomputation then made the
    next job serve the stored draft again — straight back into the span guard. So the answer is
    read from the admitted result itself, which is correct in both worlds: an old-code admission
    recorded the stored draft (unchanged behaviour), a new-code admission recorded the fresh
    projection, and either way the served spans are the ones that passed the anti-fabrication guard
    at admission.

    The admitted result's own fields/evidence rows are the index; their content lives in the result
    artifact the row pins by digest (``entity_research_result_evidence`` keeps only the span's
    sha256, never its text), so the artifact is read the way every other reader of an admitted
    result reads it — ``read_verified_artifact`` + a ``content_address`` check against
    ``result_sha256`` (``EntityResearchResultStore._load_existing`` / ``read_result`` / the
    follow-up parent read) — and then reconciled against the durable rows: every served span must
    hash to an evidence row of that result, and an indexed value is rehydrated from the exact value
    artifact its field row names.
    """

    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT result_id, result_artifact_key, result_sha256, workspace_id,
                           provider_snapshot_ref
                    FROM entity_research_result
                    WHERE provider_operation_ref=:operation_ref
                    ORDER BY created_at, result_id
                    LIMIT 1
                    """
                ),
                {"operation_ref": operation_ref},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    workspace_id = str(row["workspace_id"])
    _, data = await read_verified_artifact(
        conn,
        storage,
        storage_key=str(row["result_artifact_key"]),
        workspace_id=workspace_id,
    )
    if content_address(data) != str(row["result_sha256"]):
        raise EntityResearchResultIntegrityError(
            "admitted result artifact differs from its durable digest"
        )
    result = PersistedResearchToolResult.model_validate_json(data)
    admitted_evidence = {
        (str(evidence["artifact_key"]), str(evidence["evidence_span_sha256"]))
        for evidence in (
            (
                await conn.execute(
                    text(
                        "SELECT artifact_key, evidence_span_sha256 "
                        "FROM entity_research_result_evidence WHERE result_id=:result_id"
                    ),
                    {"result_id": row["result_id"]},
                )
            )
            .mappings()
            .all()
        )
    }
    value_keys = {
        (cast(UUID, field["target_entity_id"]), str(field["field_key"])): str(
            field["value_artifact_key"]
        )
        for field in (
            (
                await conn.execute(
                    text(
                        "SELECT target_entity_id, field_key, value_artifact_key "
                        "FROM entity_research_result_field "
                        "WHERE result_id=:result_id AND value_artifact_key IS NOT NULL"
                    ),
                    {"result_id": row["result_id"]},
                )
            )
            .mappings()
            .all()
        )
    }

    async def restore(
        fields: tuple[ResearchFieldResultProjection, ...], *, subject_entity_id: UUID
    ) -> tuple[ResearchFieldResultProjection, ...]:
        restored: list[ResearchFieldResultProjection] = []
        for field in fields:
            for evidence in field.evidence:
                admitted = (
                    evidence.artifact_ref.removeprefix("artifact:"),
                    hashlib.sha256(evidence.evidence_span.encode()).hexdigest(),
                )
                if admitted not in admitted_evidence:
                    raise EntityResearchResultIntegrityError(
                        "admitted result artifact cites evidence its durable rows never recorded"
                    )
            value_key = value_keys.get((subject_entity_id, field.field_key))
            if field.value_ref is None or value_key is None:
                restored.append(field)
                continue
            _, value_data = await read_verified_artifact(
                conn, storage, storage_key=value_key, workspace_id=workspace_id
            )
            payload = json.loads(value_data)
            if payload.get("field_key") != field.field_key or payload.get(
                "subject_entity_id"
            ) != str(subject_entity_id):
                raise EntityResearchResultIntegrityError(
                    "indexed admitted value belongs to another subject or field"
                )
            restored.append(field.model_copy(update={"value": payload.get("value")}))
        return tuple(restored)

    subjects: list[ResearchDiscoveredSubjectProjection] = []
    for subject in result.discovered_subjects:
        subjects.append(
            subject.model_copy(
                update={
                    "fields": await restore(
                        subject.fields, subject_entity_id=subject.target_entity_id
                    )
                }
            )
        )
    return _AdmittedProjection(
        snapshot_ref=str(row["provider_snapshot_ref"]),
        result=result.model_copy(
            update={
                "fields": await restore(result.fields, subject_entity_id=result.target_entity_id),
                "discovered_subjects": tuple(subjects),
            }
        ),
    )


def _match_haystack(*values: object) -> str:
    """Fold provider-returned string values (never JSON keys) into one search haystack.

    Values are newline-delimited so a scope term can never match a phrase stitched together
    across two unrelated values.
    """

    parts: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            if value:
                parts.append(value)
        elif isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, Sequence):
            for item in value:
                collect(item)

    for value in values:
        collect(value)
    return "\n".join(parts).casefold()


# US state name <-> USPS abbreviation, both directions, for the region tier of the office gate.
# Providers spell regions out ("New Jersey") while an agent scope may abbreviate ("NJ"); in the
# first live canary that single spelling difference vetoed a provider-perfect Paramus candidate
# whose row satisfied locality, function, and exact current employer. Normalization is bounded to
# this one closed vocabulary; free-text geo is never guessed.
_US_STATE_BY_ABBREVIATION: Final[dict[str, str]] = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "de": "delaware",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new hampshire",
    "nj": "new jersey",
    "nm": "new mexico",
    "ny": "new york",
    "nc": "north carolina",
    "nd": "north dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode island",
    "sc": "south carolina",
    "sd": "south dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
    "dc": "district of columbia",
}
_US_STATE_ABBREVIATION_BY_NAME: Final[dict[str, str]] = {
    name: abbreviation for abbreviation, name in _US_STATE_BY_ABBREVIATION.items()
}


def _region_alternatives(region: str) -> tuple[str, ...]:
    """Return the declared region plus its US-state spelling twin, casefolded."""

    folded = region.casefold().strip()
    twin = _US_STATE_BY_ABBREVIATION.get(folded) or _US_STATE_ABBREVIATION_BY_NAME.get(folded)
    return (folded, twin) if twin else (folded,)


def _location_scope_match(scope: AccountBuyingUnitScope, *, haystack: str) -> bool:
    """Match the office scope against provider-returned location values, most specific first.

    Under the default ``company_wide`` policy this tier does not run at all: office placement is
    never a veto, so the declared office is descriptive/audit context and every candidate passes
    the location dimension. Founder ruling 2026-08-20, after the first complete live committee
    execution (Millennium Physician Group — 913 people, multi-site) fetched seven real candidates
    and admitted zero because no provider profile value could place anyone at the Fort Myers HQ.
    Only the office-geography veto retires; the current-employer/organization-relationship and
    target-function gates below are untouched and still decide admission.

    Under the explicitly-selected ``same_office_strict`` policy the original contract stands, and
    every historical scope replays under exactly the policy it recorded:

    The declared terms form a containment hierarchy (facility ⊂ locality ⊂ region ⊂ country).
    Only the most specific declared tier must be evidenced: once "Paramus" is present in the
    provider values, "New Jersey"/"United States" are containers of the same fact and requiring
    them independently can only manufacture false vetoes (the first live canary lost a perfect
    candidate to "NJ" vs "New Jersey"). A candidate whose values evidence no declared tier still
    fails closed to review — profile metros are never inferred to be office assignments.
    """

    if scope.match_policy == "company_wide":
        return True
    if scope.facility_name is not None or scope.locality is not None:
        alternatives = tuple(
            value.casefold() for value in (scope.facility_name, scope.locality) if value is not None
        )
        return any(value in haystack for value in alternatives)
    if scope.region is not None:
        return any(value in haystack for value in _region_alternatives(scope.region))
    if scope.country is not None:
        return scope.country.casefold() in haystack
    return True


def _organization_names(facts: object) -> tuple[str, ...]:
    """Extract only the provider-returned current-employer organization names."""

    names: list[str] = []
    if isinstance(facts, Sequence):
        for fact in facts:
            if isinstance(fact, Mapping):
                name = fact.get("organization_name")
                if isinstance(name, str) and name:
                    names.append(name)
    return tuple(names)


def _operation_ref(operation: AccountGapOperation) -> str:
    return f"sumble-account-operation:{operation.operation_id}"


class SumbleEntityResearchLineageReader(ProviderResultLineageReader):
    """Read the immutable normalized projection joining Sumble's provider-owned ledgers."""

    def __init__(self, *, provider_kind: str, conn_factory: ConnFactory) -> None:
        self.provider_kind = provider_kind
        self._conn_factory = conn_factory

    async def load(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
    ) -> ProviderResultLineage:
        if operation.provider_kind != self.provider_kind:
            raise EntityResearchResultIntegrityError("Sumble lineage reader received another kind")
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT workspace_id, provider_snapshot_ref,
                                   normalized_result_artifact_key,
                                   raw_response_artifact_refs, retained_result_artifact_refs,
                                   provider_receipt_ref, cost_settlement_ref,
                                   provider_request_id, provider_reported_cost_cents,
                                   settled_cost_cents
                            FROM entity_research_sumble_projection
                            WHERE provider_operation_ref=:operation_ref
                            """
                        ),
                        {"operation_ref": operation.operation_ref},
                    )
                )
                .mappings()
                .first()
            )
            component_snapshot_refs, component_source_keys = await self._component_snapshots(
                conn,
                operation=operation,
            )
        if (
            row is None
            or str(row["workspace_id"]) != operation.workspace_id
            or str(row["provider_snapshot_ref"]) != snapshot_ref
            or request.target_entity_id != operation.target_entity_id
        ):
            raise EntityResearchResultIntegrityError("Sumble lineage crosses exact operation scope")
        return ProviderResultLineage(
            operation=operation,
            snapshot_ref=snapshot_ref,
            claim_source_snapshot_refs=component_snapshot_refs,
            claim_source_keys=component_source_keys,
            raw_response_artifact_refs=tuple(
                str(value) for value in row["raw_response_artifact_refs"]
            ),
            retained_result_artifact_refs=tuple(
                str(value) for value in row["retained_result_artifact_refs"]
            ),
            normalized_result_artifact_ref=f"artifact:{row['normalized_result_artifact_key']}",
            provider_receipt_ref=str(row["provider_receipt_ref"]),
            cost_settlement_ref=str(row["cost_settlement_ref"]),
            provider_request_id=str(row["provider_request_id"]),
            provider_reported_cost_cents=Decimal(row["provider_reported_cost_cents"]),
            settled_cost_cents=Decimal(row["settled_cost_cents"]),
        )

    async def _component_snapshots(
        self,
        conn: AsyncConnection,
        *,
        operation: ProviderOperationReservation,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Resolve claim-level snapshots from the immutable owning Sumble ledger.

        Returns the component snapshot refs and the source keys that produced them.

        Account enrichment normalizes the organization lookup and the selected structured source
        into one aggregate entity-research snapshot, while every claim correctly retains the
        specific `account_gap_snapshot` that supplied it. Committee acquisition has the same
        shape for Teams and People. The generic result store must validate those claim refs against
        provider-owned rows rather than incorrectly requiring the aggregate ref on every claim —
        or, for a discovered contact, the aggregate *source key*: a committee member the Teams
        organization map returned carries only ``sumble_teams`` facts, and refusing those was the
        last mechanical blocker on a provider-returned candidate.
        """

        try:
            operation_id = UUID(operation.operation_ref.rsplit(":", 1)[-1])
        except ValueError as error:
            raise EntityResearchResultIntegrityError(
                "Sumble operation reference is malformed"
            ) from error
        if self.provider_kind == "sumble_account":
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_key, request_fingerprint FROM account_gap_snapshot "
                            "WHERE operation_id=:operation_id AND workspace_id=:workspace_id "
                            "AND state='succeeded'"
                        ),
                        {
                            "operation_id": operation_id,
                            "workspace_id": operation.workspace_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            return (
                tuple(
                    sorted(
                        f"account-gap-snapshot:{operation_id}:{row['source_key']}:"
                        f"{row['request_fingerprint']}"
                        for row in rows
                    )
                ),
                tuple(sorted({str(row["source_key"]) for row in rows})),
            )
        if self.provider_kind == "sumble_committee":
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_key, request_fingerprint "
                            "FROM committee_acquisition_snapshot "
                            "WHERE operation_id=:operation_id AND workspace_id=:workspace_id "
                            "AND state='succeeded'"
                        ),
                        {
                            "operation_id": operation_id,
                            "workspace_id": operation.workspace_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            return (
                tuple(
                    sorted(
                        f"committee-snapshot:{operation_id}:{row['source_key']}:"
                        f"{row['request_fingerprint']}"
                        for row in rows
                    )
                ),
                tuple(sorted({str(row["source_key"]) for row in rows})),
            )
        raise EntityResearchResultIntegrityError("unknown Sumble provider lineage kind")


class SumbleAccountSemanticEnrichmentAction(EntityResearchProviderAction):
    """Run one exact structured-source field group, independent from qualitative Exa research."""

    provider_kind = "sumble_account"

    def __init__(
        self,
        *,
        starter: SumbleAccountGapStarter,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_id: EntityId,
        field_expected_value_credits: Mapping[str, Decimal],
        provider_credit_cap: int,
        allow_unbounded_tech: bool = False,
        entity_research_job_id: UUID | None = None,
    ) -> None:
        self._starter = starter
        self._storage = storage
        self._conn_factory = conn_factory
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._project_run_id = project_run_id
        self._account_id = account_id
        self._values = dict(field_expected_value_credits)
        self._provider_credit_cap = provider_credit_cap
        self._allow_unbounded_tech = allow_unbounded_tech
        self._entity_research_job_id = entity_research_job_id

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
        settle_terminal: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ExternalResearchProjectionDraft]:
        if (
            request.subject_type is not ResearchSubjectType.ACCOUNT
            or request.target_entity_id != self._account_id
            or set(request.field_keys) - set(self._values)
            or request.parent_operation_ref is not None
            or len(request.source_keys) != 1
            or any(
                tuple(item.source_keys) != request.source_keys
                for item in request.field_source_authority
            )
        ):
            raise EntityResearchGovernedRejection(
                "field_source_authority_mismatch",
                "Sumble account enrichment differs from exact structured field/source authority",
            )
        caused = False

        async def bind_sumble_before_dispatch(operation: AccountGapOperation) -> None:
            nonlocal caused
            descriptor = self._descriptor(
                operation,
                source_key=request.source_keys[0],
                field_keys=request.field_keys,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=False,
            )
            observation = await before_dispatch(descriptor)
            caused = (
                observation.tool_request_id == request.tool_call_id
                and observation.disposition == ProviderObservationDisposition.CAUSED.value
            )

        try:
            result = await self._starter.start(
                workspace_id=self._workspace_id,
                project_run_id=self._project_run_id,
                account_id=self._account_id,
                field_expected_value_credits={key: self._values[key] for key in request.field_keys},
                provider_credit_cap=self._provider_credit_cap,
                # One composed action serves independently partitioned Sumble source calls.  The
                # directive-level authority may include tech, but only the tech partition should
                # carry that provider-specific approval; applying it to a simultaneous jobs or
                # organizations call makes the preflight correctly reject that non-tech call.
                allow_unbounded_tech=(
                    self._allow_unbounded_tech and "core.primary_tech_stack" in request.field_keys
                ),
                before_dispatch=bind_sumble_before_dispatch,
                entity_research_job_id=self._entity_research_job_id,
            )
        except SumbleAccountGapFieldAlreadyAcquired as exc:
            # The same species, refused one rung earlier: this window already bought the field for
            # this account, so no purchase is possible and none was attempted.  Its own code,
            # because the repair differs from §6.3(b)'s — there is a durable operation holding the
            # answer (which may itself be an honest ``confirmed_missing`` or an unresolved
            # ``conflict``), and the agent must read it rather than re-ask for it.
            raise EntityResearchGovernedRejection(
                "account_gap_field_already_acquired",
                f"Sumble account enrichment cannot re-buy this account's field: {exc}",
            ) from exc
        except SumbleAccountGapNotEligible as exc:
            # FI-2 §6.3(b), and *only* §6.3(b): the ladder found the field already confidently and
            # freshly answered.  The preflight refuses before any operation row or dispatch, so
            # this is a zero-spend, zero-state refusal of the request the agent made — the
            # model-repairable species (R10), not a job suspension.  The agent drops that field,
            # picks another admitted source, or finalizes with an honest gap.
            #
            # Deliberately the subclass, not the ``SumbleAccountGapEligibilityError`` family: the
            # other members (job authority lost, discovery seal conflicted, account not the
            # canonical survivor, a field mis-declared as project-relative) are facts about the
            # world that no choice of the agent's repairs, and they were suspending before §6.3(b)
            # existed.  Catching the base class here would have converted a fenced-out job's
            # authority failure into a turn it could keep taking.  (The legacy toolbelt path does
            # convert the whole family, to ``PreconditionFailed`` — a human-facing precondition,
            # not an agent turn.)
            raise EntityResearchGovernedRejection(
                "account_gap_ineligible",
                f"Sumble account enrichment is not eligible for this request: {exc}",
            ) from exc
        if result.outcome is SumbleAccountGapOutcome.JOINED_IN_FLIGHT:
            raise EntityResearchProviderWait(
                self._descriptor(
                    result.operation,
                    source_key=request.source_keys[0],
                    field_keys=request.field_keys,
                    disposition=ProviderObservationDisposition.JOINED,
                    include_dispatch=True,
                )
            )
        if result.outcome is SumbleAccountGapOutcome.FAILED_TERMINAL:
            # Deterministic provider refusal: zero-charge, diagnostics durable on the gap ledger.
            # The agent may pick another admitted source or finalize with an explicit gap. The
            # settlement must carry the operation's real dispatch time as well as the fold —
            # execution closure counts neither an undispatched operation nor a bare fold.
            await settle_terminal(
                self._descriptor(
                    result.operation,
                    source_key=request.source_keys[0],
                    field_keys=request.field_keys,
                    disposition=(
                        ProviderObservationDisposition.CAUSED
                        if caused
                        else ProviderObservationDisposition.REPLAY
                    ),
                    include_dispatch=True,
                )
            )
            raise EntityResearchGovernedRejection(
                "provider_rejected",
                "Sumble account enrichment was terminally rejected by the provider "
                f"(failure_code={result.operation.failure_code or 'unrecorded'}); the durable "
                "operation ledger retains the exact provider diagnostic",
            )
        if result.outcome is SumbleAccountGapOutcome.SPEND_OUTCOME_UNKNOWN:
            # The provider may have charged for a dispatch we could not reconcile (a crash between
            # dispatch and receipt quarantines the snapshot; an unreconciled paid dispatch marks
            # the same state).  That is a *provider* outcome, not a violation of the result
            # contract, and it is durably terminal: ``_terminal_result`` replays it forever, so
            # raising here left the job re-suspending on every resume with nothing it could do.
            # Settle it exactly like the deterministic refusal — the operation's real dispatch
            # time plus an append-only zero-cost fold, so the (field, source) pair reaches a
            # terminal attempt and coverage can close honestly — and refuse the call back to the
            # agent, which may pick another admitted source or finalize with the gap.
            await settle_terminal(
                self._descriptor(
                    result.operation,
                    source_key=request.source_keys[0],
                    field_keys=request.field_keys,
                    disposition=(
                        ProviderObservationDisposition.CAUSED
                        if caused
                        else ProviderObservationDisposition.REPLAY
                    ),
                    include_dispatch=True,
                )
            )
            raise EntityResearchGovernedRejection(
                "provider_spend_unreconciled",
                "Sumble account enrichment dispatched but its spend outcome could not be "
                f"reconciled (failure_code={result.operation.failure_code or 'unrecorded'}); the "
                "durable operation ledger retains the exact provider diagnostic and the attempt "
                "is terminal",
            )
        if (
            result.outcome
            not in {
                SumbleAccountGapOutcome.COMPLETED,
                SumbleAccountGapOutcome.REPLAYED,
            }
            or result.operation.state is not AccountGapOperationState.SUCCEEDED
        ):
            raise EntityResearchResultIntegrityError(
                f"Sumble account enrichment did not settle safely: {result.outcome.value}"
            )
        operation = self._descriptor(
            result.operation,
            source_key=request.source_keys[0],
            field_keys=request.field_keys,
            disposition=(
                ProviderObservationDisposition.CAUSED
                if caused
                else ProviderObservationDisposition.REPLAY
            ),
            include_dispatch=True,
        )
        snapshot_ref, fields = await self._persist_projection(
            request=request,
            operation=result.operation,
            provider_operation=operation,
        )
        return (
            ExternalResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                requested_field_keys=request.field_keys,
                fields=fields,
            ),
        )

    def _descriptor(
        self,
        operation: AccountGapOperation,
        *,
        source_key: str,
        field_keys: tuple[str, ...],
        disposition: ProviderObservationDisposition,
        include_dispatch: bool,
    ) -> ProviderOperationReservation:
        created = operation.created_at or datetime.now(UTC)
        return ProviderOperationReservation(
            provider_kind=self.provider_kind,
            operation_ref=_operation_ref(operation),
            workspace_id=operation.request.workspace_id,
            project_id=operation.request.project_id,
            project_run_id=UUID(str(operation.request.project_run_id)),
            subject_type=ResearchSubjectType.ACCOUNT,
            target_entity_id=UUID(str(operation.request.account_id)),
            source_key=source_key,
            field_keys=field_keys,
            request_artifact_ref=f"artifact:{operation.input_artifact_key}",
            reserved_at=created,
            dispatched_at=(operation.started_at if include_dispatch else None),
            observation_disposition=disposition,
        )

    async def _persist_projection(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: AccountGapOperation,
        provider_operation: ProviderOperationReservation,
    ) -> tuple[str, tuple[ResearchFieldResultProjection, ...]]:
        async with self._conn_factory() as conn:
            snapshots = await list_account_gap_snapshots(
                conn,
                workspace_id=self._workspace_id,
                operation_id=operation.operation_id,
            )
            field_results = {
                str(item.field_key): item
                for item in await list_account_gap_field_results(
                    conn,
                    workspace_id=self._workspace_id,
                    operation_id=operation.operation_id,
                )
            }
            claim_ids = {
                UUID(str(claim_id))
                for result in field_results.values()
                for claim_id in (
                    *((result.sumble_claim_id,) if result.sumble_claim_id else ()),
                    *result.conflicting_claim_ids,
                )
            }
            claims = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, field_key, value_json, source_key, source_url,
                                   artifact_key, evidence_span, confidence,
                                   verification_status::text, corroborations
                            FROM claim WHERE id=ANY(:claim_ids) ORDER BY collected_at DESC, id
                            """
                        ),
                        {"claim_ids": list(claim_ids)},
                    )
                )
                .mappings()
                .all()
                if claim_ids
                else ()
            )
            claims_by_id: dict[UUID, Mapping[str, object]] = {
                UUID(str(row["id"])): cast(Mapping[str, object], row) for row in claims
            }
            projected = tuple(
                self._field(
                    field_results[field_key],
                    claims_by_id=claims_by_id,
                    provider_request_id=";".join(
                        sorted(
                            str(item.provider_request_id)
                            for item in snapshots
                            if item.provider_request_id is not None
                        )
                    ),
                    operation_id=UUID(str(operation.operation_id)),
                )
                for field_key in request.field_keys
            )
            payload = {
                "contract": "m8d-r5-sumble-account-projection-v1",
                "operation": operation.model_dump(mode="json"),
                "snapshots": [item.model_dump(mode="json") for item in snapshots],
                "fields": [item.model_dump(mode="json") for item in projected],
            }
            normalized_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=self._workspace_id,
                content=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                media_type="application/json",
                source_key=provider_operation.source_key,
            )
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=self._workspace_id,
                artifact_key_value=normalized_key,
                subject_kind="account",
                subject_entity_id=self._account_id,
                reference_kind="entity_research_sumble_normalized",
                reference_id=provider_operation.operation_ref,
            )
            successful = [
                item
                for item in snapshots
                if item.state is AccountGapSnapshotState.SUCCEEDED
                and item.response_artifact_key is not None
            ]
            raw_refs = [f"artifact:{item.response_artifact_key}" for item in successful]
            if not raw_refs or operation.receipt_manifest_key is None:
                raise EntityResearchResultIntegrityError(
                    "settled Sumble account operation lacks raw response or receipt"
                )
            snapshot_ref = (
                f"sumble-account-snapshot:{operation.operation_id}:"
                f"{hashlib.sha256('|'.join(sorted(raw_refs)).encode()).hexdigest()}"
            )
            provider_request_id = ";".join(
                sorted(
                    str(item.provider_request_id)
                    for item in successful
                    if item.provider_request_id is not None
                )
            ) or str(operation.operation_id)
            values = {
                "operation_ref": provider_operation.operation_ref,
                "workspace_id": self._workspace_id,
                "snapshot_ref": snapshot_ref,
                "normalized_key": normalized_key,
                "raw_refs": raw_refs,
                "receipt_ref": f"artifact:{operation.receipt_manifest_key}",
                "settlement_ref": f"sumble-account-settlement:{operation.operation_id}",
                "provider_request_id": provider_request_id,
                "reported_cost": operation.cost_cents_charged,
                "settled_cost": operation.cost_cents_charged,
                "metadata": "{}",
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_sumble_projection
                        (provider_operation_ref, workspace_id, provider_snapshot_ref,
                         normalized_result_artifact_key, raw_response_artifact_refs,
                         retained_result_artifact_refs, provider_receipt_ref,
                         cost_settlement_ref, provider_request_id,
                         provider_reported_cost_cents, settled_cost_cents, metadata_json)
                    VALUES (:operation_ref, :workspace_id, :snapshot_ref, :normalized_key,
                            :raw_refs, :raw_refs, :receipt_ref, :settlement_ref,
                            :provider_request_id, :reported_cost, :settled_cost,
                            CAST(:metadata AS jsonb))
                    ON CONFLICT (provider_operation_ref) DO NOTHING
                    """
                ),
                values,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT provider_snapshot_ref, normalized_result_artifact_key "
                            "FROM entity_research_sumble_projection "
                            "WHERE provider_operation_ref=:operation_ref"
                        ),
                        {"operation_ref": provider_operation.operation_ref},
                    )
                )
                .mappings()
                .one()
            )
            replay_differs = (
                str(stored["provider_snapshot_ref"]) != snapshot_ref
                or str(stored["normalized_result_artifact_key"]) != normalized_key
            )
            # First write wins — for ADMITTED history, and only for it, and what replays is what
            # the ADMITTED RESULT recorded, never the stored projection row. The same lesson as
            # the seal reader and the settlement fold: what a job was actually shown, and what
            # downstream consumed, is served from durable history, never recomputed under newer
            # code. A projection-composition improvement (live: aa88e0b0's conflict-evidence fix)
            # legitimately changes what today's code would project for a terminal operation
            # recorded yesterday; refusing that replay suspended the job ("Sumble projection replay
            # changed").
            #
            # An operation with NO ``entity_research_result`` anywhere has no admitted history: no
            # turn was ever shown its stored first write, so that write is a failed draft, not a
            # fact about the past. Live (job eea48931), the pre-aa88e0b0 draft published a conflict
            # contender's evidence span, the span-fidelity guard refused it at 02:14, and serving
            # that same draft back at 03:46 raised the identical refusal, so the job re-wedged on
            # every resume. For that draft the immutable truth is the retained provider snapshot,
            # and the only projection of it that can ever pass the guard is the fresh one
            # recomputed above from the durable gap-ledger snapshots — so it is returned.
            # Supersession is by NON-ADOPTION: the projection table is append-only, so the refused
            # first draft stays exactly where it is as the audit record of what defective code
            # wrote, and the replay stays deterministic (same snapshot + same code = same fresh
            # projection). One accepted residual follows: the lineage reader serves this
            # append-only row, so a result admitted from the fresh projection carries a
            # ``normalized_result_artifact_ref`` naming the superseded draft. Nothing recomputes
            # or compares that artifact downstream (``_validate_artifacts`` only
            # existence-verifies it), the snapshot_ref both sides cite is content-derived from
            # the durable raw refs and therefore identical, and the fresh normalized artifact is
            # captured and subject-bound above — both normalizations survive in storage.
            #
            # That residual is exactly why the admitted case may NOT read the stored row: "a result
            # was admitted for this operation" is not "the stored row is what was admitted", and
            # live (job 3cc0a4f2, 06:37:33) the two diverged permanently — eea48931's resume served
            # the fresh recomputation while nothing was admitted, the result admitted from it
            # (c8be9969) recorded that fresh projection, the append-only row still held the
            # defective draft, and the next job to replay the operation was handed the refused span
            # straight back into the guard. ``_first_admitted_projection`` answers with the earliest
            # admitted result's own record instead: an old-code admission recorded the stored draft
            # (c7d6da82's case, behaviour unchanged), a new-code admission recorded the fresh
            # projection, and either way every span served is one that already passed the guard.
            admitted = (
                await _first_admitted_projection(
                    conn, self._storage, operation_ref=provider_operation.operation_ref
                )
                if replay_differs
                else None
            )
            if admitted is not None:
                if {field.field_key for field in admitted.result.fields} != set(request.field_keys):
                    # Fail closed rather than serve a projection that cannot answer this request.
                    # The gap ledger keys an operation by its exact field set, so this is
                    # unreachable unless that invariant breaks.
                    raise EntityResearchResultIntegrityError(
                        "admitted Sumble projection does not index this request's exact fields"
                    )
                return admitted.snapshot_ref, admitted.result.fields
        return snapshot_ref, projected

    def _field(
        self,
        result: object,
        *,
        claims_by_id: Mapping[UUID, Mapping[str, object]],
        provider_request_id: str,
        operation_id: UUID,
    ) -> ResearchFieldResultProjection:
        field = cast("AccountGapFieldResult", result)
        if field.state is AccountGapFieldState.CONFIRMED_MISSING:
            return ResearchFieldResultProjection(
                field_key=str(field.field_key),
                outcome=ResearchFieldOutcome.NULL,
                claim_delta=ResearchClaimDelta.NONE,
                verification_status=field.reason_code or "confirmed_missing",
            )
        contenders: tuple[ClaimId | None, ...]
        if field.state is AccountGapFieldState.CONFLICT:
            # The provider's own contender is part of its conflict by definition; the corroborator
            # is not required to list it, so name it explicitly rather than rely on the group.
            contenders = field.conflicting_claim_ids + (
                ()
                if field.sumble_claim_id is None
                or field.sumble_claim_id in field.conflicting_claim_ids
                else (field.sumble_claim_id,)
            )
        else:
            contenders = (field.sumble_claim_id,) if field.sumble_claim_id else ()
        ids = tuple(UUID(str(value)) for value in contenders)
        rows = tuple(claims_by_id[value] for value in ids)
        # Evidence is this operation's own retained provenance, never a contender's.  A conflict's
        # foreign claims are cited by *reference* (``claim_refs`` plus the durable conflict
        # decision) and the agent reads them through the claim surface.  Projecting their spans
        # here would have this tool vouch for artifacts it neither bought nor was authorized for:
        # the engine's exact field/source authority refuses that, and rightly — a Sumble result
        # citing an Exa artifact is provenance laundering, not corroboration.
        evidence = tuple(
            ResearchEvidenceProjection(
                evidence_ref=(
                    f"research-evidence:{uuid5(_EVIDENCE_NAMESPACE, f'{operation_id}:{row["id"]}')}"
                ),
                source_key=str(row["source_key"]),
                provider_source_id=provider_request_id,
                source_url=str(row["source_url"]) if row["source_url"] else None,
                artifact_ref=f"artifact:{row['artifact_key']}",
                evidence_span=str(row["evidence_span"]),
            )
            for row in rows
            if str(row["source_key"]) == str(field.source_key)
        )
        if field.state is AccountGapFieldState.CONFLICT:
            return ResearchFieldResultProjection(
                field_key=str(field.field_key),
                outcome=ResearchFieldOutcome.CONFLICT,
                claim_delta=ResearchClaimDelta.CONFLICTING,
                claim_refs=tuple(f"claim:{value}" for value in ids),
                decision_refs=(f"conflict:{field.account_id}:{field.field_key}",),
                evidence=evidence,
                confidence=max(float(cast(Decimal, row["confidence"])) for row in rows),
                verification_status="flagged_conflict",
            )
        if not rows:
            raise EntityResearchResultIntegrityError("resolved Sumble field lacks its claim")
        row = rows[0]
        corroborating = field.state is AccountGapFieldState.CORROBORATED
        return ResearchFieldResultProjection(
            field_key=str(field.field_key),
            outcome=ResearchFieldOutcome.FOUND,
            value=decode_jsonb_scalar(row["value_json"]),
            claim_delta=(
                ResearchClaimDelta.CORROBORATING if corroborating else ResearchClaimDelta.ACCEPTED
            ),
            claim_refs=(f"claim:{row['id']}",),
            evidence=evidence,
            confidence=float(cast(Decimal, row["confidence"])),
            verification_status=str(row["verification_status"]),
        )


class _PreparedCommitteeSource(CommitteeSource):
    source_key = PEOPLE_SOURCE_KEY
    tier = 1

    def __init__(self, candidates: Sequence[CommitteePersonCandidate]) -> None:
        self._candidates = tuple(candidates)

    async def find_candidates(
        self, account: object, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]:
        del account
        return self._candidates[:limit]


class SumbleCommitteeAgentInputResolver(Protocol):
    async def resolve(self) -> SumbleCommitteePreparationInputs: ...


class SumbleCommitteeSemanticResearchAction(EntityResearchProviderAction):
    """Acquire Teams/People, apply the declared buying-unit scope, then project admitted members."""

    provider_kind = "sumble_committee"

    def __init__(
        self,
        *,
        preflight: SumbleCommitteePreflight | None = None,
        inputs: SumbleCommitteeAgentInputResolver | None = None,
        eligibility: CommitteeEligibilityService | None = None,
        coordinator: SumbleCommitteeAcquisitionCoordinator,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        gateway: LLMGateway,
        role_model: str,
    ) -> None:
        if (preflight is None) == (inputs is None):
            raise ValueError("committee action requires exactly one static or run-scoped input")
        if inputs is not None and eligibility is None:
            raise ValueError("run-scoped committee input requires the complete S2 eligibility gate")
        self._preflight = preflight
        self._inputs = inputs
        self._eligibility = eligibility
        self._coordinator = coordinator
        self._storage = storage
        self._conn_factory = conn_factory
        self._gateway = gateway
        self._role_model = role_model

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
        settle_terminal: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ExternalResearchProjectionDraft]:
        active = current_entity_research_tool_execution()
        semantic = DiscoverBuyingCommitteeInput.model_validate(active.call.arguments)
        try:
            preflight, committee_plan = await self._resolve_inputs()
        except SumbleCommitteeProviderIdentityUnavailable as unavailable:
            # World fact, not model input and not job integrity: the provider's organization index
            # cannot serve this account, so no committee call is possible for it — ever, for the
            # unmatched case. Record the zero-cost terminal attempt, then refuse recoverably. The
            # live ``dc86340f`` shape (Greater Chicago, 2026-08-20 21:36:47) raised this raw and
            # killed the drive with ``execution_failed``.
            await self._record_committee_axis_unavailable(
                request=request,
                workspace_id=active.context.authorization.workspace_id,
                error=unavailable,
            )
            raise EntityResearchGovernedRejection(
                unavailable.code, _committee_unavailable_detail(unavailable)
            ) from unavailable
        durable = preflight.request
        async with self._conn_factory() as conn:
            # The engine composes what it already knows (scope id, account, office, evidence) so
            # the model cannot get it wrong; everything the model *did* declare survives verbatim
            # into the durable scope and meets every authority check below unchanged.
            scope = await resolve_account_buying_unit_scope(
                conn,
                request=request,
                requested=semantic.buying_unit_scope,
                workspace_id=durable.workspace_id,
            )
        self._validate_scope_against_plan(scope, plan=committee_plan)
        if (
            request.subject_type is not ResearchSubjectType.ACCOUNT
            or request.target_entity_id != durable.account_id
            or scope.account_entity_id != request.target_entity_id
            or set(request.source_keys) != {PEOPLE_SOURCE_KEY}
            or request.field_keys
            or request.parent_operation_ref is not None
        ):
            raise EntityResearchGovernedRejection(
                "committee_request_authority_mismatch",
                "Sumble committee request differs from exact account/people/scope authority",
            )
        await self._persist_scope(
            request=request,
            scope=scope,
            workspace_id=durable.workspace_id,
        )
        caused = False

        async def bind_sumble_before_dispatch(operation: object) -> None:
            nonlocal caused
            typed = cast("CommitteeAcquisitionOperation", operation)
            descriptor = self._committee_descriptor(
                typed,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=False,
            )
            observation = await before_dispatch(descriptor)
            caused = caused or (
                observation.tool_request_id == request.tool_call_id
                and observation.disposition == ProviderObservationDisposition.CAUSED.value
            )

        acquired = await self._coordinator.start(
            preflight, before_dispatch=bind_sumble_before_dispatch
        )
        if acquired.outcome in {
            SumbleCommitteeOutcome.WAITING_EXTERNAL,
            SumbleCommitteeOutcome.JOINED_IN_FLIGHT,
            SumbleCommitteeOutcome.RATE_LIMITED,
        }:
            raise EntityResearchProviderWait(
                self._committee_descriptor(
                    acquired.operation,
                    # A newly dispatched asynchronous operation remains caused by this exact
                    # tool while it waits.  Only a later tool that joined an existing operation
                    # is a joined observation.  Re-labelling the causal row as joined made the
                    # immutable causation ledger reject honest Sumble polling waits.
                    disposition=self._wait_disposition(caused=caused),
                    include_dispatch=True,
                )
            )
        if acquired.outcome is SumbleCommitteeOutcome.FAILED_TERMINAL:
            # Deterministic provider refusal (for example a validated zero-charge HTTP 4xx): the
            # committee ledger retains the status and the provider's own bounded error body. The
            # agent decides — repair, another admitted source, or an explicit partial committee.
            await settle_terminal(
                self._committee_descriptor(
                    acquired.operation,
                    disposition=(
                        ProviderObservationDisposition.CAUSED
                        if caused
                        else ProviderObservationDisposition.REPLAY
                    ),
                    include_dispatch=True,
                )
            )
            raise EntityResearchGovernedRejection(
                "provider_rejected",
                "Sumble committee acquisition was terminally rejected "
                f"(failure_code={acquired.operation.failure_code or 'unrecorded'}); the durable "
                "committee ledger retains the exact provider diagnostic",
            )
        if acquired.outcome is SumbleCommitteeOutcome.SPEND_OUTCOME_UNKNOWN:
            # Same species as the account lane above: a dispatched committee call whose charge we
            # cannot reconcile is a durably terminal provider outcome, not a result-contract
            # violation.  Settle the attempt (real dispatch time + zero-cost fold) and refuse the
            # call back to the agent instead of suspending the job on every resume.
            await settle_terminal(
                self._committee_descriptor(
                    acquired.operation,
                    disposition=(
                        ProviderObservationDisposition.CAUSED
                        if caused
                        else ProviderObservationDisposition.REPLAY
                    ),
                    include_dispatch=True,
                )
            )
            raise EntityResearchGovernedRejection(
                "provider_spend_unreconciled",
                "Sumble committee acquisition dispatched but its spend outcome could not be "
                f"reconciled (failure_code={acquired.operation.failure_code or 'unrecorded'}); "
                "the durable committee ledger retains the exact provider diagnostic and the "
                "attempt is terminal",
            )
        if acquired.outcome not in {
            SumbleCommitteeOutcome.READY,
            SumbleCommitteeOutcome.REPLAYED,
        }:
            raise EntityResearchResultIntegrityError(
                f"Sumble committee acquisition did not settle safely: {acquired.outcome.value}"
            )
        async with self._conn_factory() as conn:
            account = await get_account(conn, EntityId(request.target_entity_id))
        if account is None or account.workspace_id != durable.workspace_id:
            raise EntityResearchResultIntegrityError("committee account is absent or foreign")
        source = SumbleCommitteeSource(
            operation_ids={EntityId(request.target_entity_id): acquired.operation.operation_id},
            storage=self._storage,
            conn_factory=self._conn_factory,
        )
        candidates = tuple(await source.find_candidates(account, limit=durable.people_limit))
        selected, excluded, ambiguous = self._office_candidates(candidates, scope=scope)
        # Committee claims are stamped with the exact project run: the M8C C1 lineage trigger
        # refuses a Sumble professional claim whose run differs from its ready operation's
        # project_run_id (a synthetic per-tool-call run id was rejected live), and the project
        # run is also the correct idempotency domain — a repeat committee call replays the
        # existing member/role claims instead of superseding them per tool call.
        run_id = RunId(UUID(str(durable.project_run_id)))
        async with self._conn_factory() as conn:
            # FI-2 P2 (spec §3): register the committee run in the same transaction as the
            # role/persona/discovery claims ``discover_committee`` writes below. Idempotent, so a
            # repeat committee call re-registers harmlessly. Because this run id *is* the project
            # run, the enrichment materializer may already have registered it under its own kind —
            # first writer wins on ``kind``; the project attribution is identical either way.
            await record_run_lineage(
                conn,
                run_id=UUID(str(run_id)),
                workspace_id=durable.workspace_id,
                kind="committee",
                project_id=durable.project_id,
                project_run_id=UUID(str(durable.project_run_id)),
            )
            committee = await self._discover_committee_members(
                conn,
                account_entity_id=EntityId(request.target_entity_id),
                run_id=run_id,
                workspace_id=durable.workspace_id,
                selected=selected,
                budget_cap_cents=durable.money_budget_cap_cents,
            )
        operation = self._committee_descriptor(
            acquired.operation,
            disposition=(
                ProviderObservationDisposition.CAUSED
                if caused
                else ProviderObservationDisposition.REPLAY
            ),
            include_dispatch=True,
        )
        snapshot_ref, subjects = await self._persist_committee_projection(
            request=request,
            operation=acquired.operation,
            provider_operation=operation,
            committee=committee,
            excluded=excluded,
            ambiguous=ambiguous,
        )
        return (
            ExternalResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                discovered_subjects=subjects,
                confirmed_empty_discovery=not subjects,
            ),
        )

    async def _discover_committee_members(
        self,
        conn: AsyncConnection,
        *,
        account_entity_id: EntityId,
        run_id: RunId,
        workspace_id: str,
        selected: Sequence[CommitteePersonCandidate],
        budget_cap_cents: Decimal | None,
    ) -> CommitteeResult:
        """Discover + identity-resolve the admitted buying unit, WITHOUT judging roles.

        Contract §5.2 steps 1-2: this provider action's job is discovery and identity — who is
        really in the declared buying unit, with provider evidence behind them. The committee *role*
        is a judgment the responsible account agent makes, on the evidence, and writes back through
        its own governed tool. So discovery runs in ``agent_deferred`` mode: it makes no gateway
        call and writes no role/persona claim, and the admitted members come back roleless (visible
        as discovered subjects with their People facts). Between this and the agent's role write,
        a committee legitimately has members and no roles — that is honest, not incomplete."""
        return await discover_committee(
            conn,
            account_entity_id=account_entity_id,
            run_id=run_id,
            workspace_id=workspace_id,
            sources=(_PreparedCommitteeSource(selected),),
            gateway=self._gateway,
            role_model=self._role_model,
            source_plan=(PEOPLE_SOURCE_KEY,),
            budget_cap_cents=budget_cap_cents,
            role_inference="agent_deferred",
        )

    async def _record_committee_axis_unavailable(
        self,
        *,
        request: GovernedResearchToolRequest,
        workspace_id: str,
        error: SumbleCommitteeProviderIdentityUnavailable,
    ) -> None:
        """Record this exact committee call as a real, zero-cost, terminal attempt.

        There is deliberately no provider operation here: the refusal happens before any
        reservation, so nothing was dispatched, nothing charged, and there is no settlement to
        fold. Stamping a dispatch to reuse the fold machinery would fabricate an attempt the
        provider never received — the one thing the settlement contract refuses. So the attempt is
        recorded on its own terms, keyed on the journalled tool request (which exists only because
        the agent really made this call under this job's authority), and
        ``read_account_research_execution_completeness`` reads it as the committee axis's terminal
        disposition. Idempotent: a checkpoint replay of the same tool call re-records nothing.
        """

        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_committee_unavailable
                        (tool_request_id, research_run_id, job_id, workspace_id,
                         account_entity_id, source_keys, reason_code, detail)
                    VALUES (:tool_request_id, :run_id, :job_id, :workspace_id, :account_id,
                            :source_keys, :reason_code, :detail)
                    ON CONFLICT (tool_request_id) DO NOTHING
                    """
                ),
                {
                    "tool_request_id": request.tool_call_id,
                    "run_id": request.research_run_id,
                    "job_id": request.job_id,
                    "workspace_id": workspace_id,
                    "account_id": request.target_entity_id,
                    "source_keys": list(request.source_keys),
                    "reason_code": error.code,
                    "detail": error.detail,
                },
            )
        log.info(
            "committee axis is unbuyable for this account",
            job_id=str(request.job_id),
            account_entity_id=str(request.target_entity_id),
            reason_code=error.code,
            source_keys=list(request.source_keys),
        )

    async def _resolve_inputs(
        self,
    ) -> tuple[SumbleCommitteePreflight, ResearchCommitteePlan | None]:
        if self._inputs is None:
            assert self._preflight is not None
            # Static construction remains a deterministic R5 test/historical seam. Production
            # uses the resolver path below so no eligibility decision or provider preparation can
            # occur before the responsible agent's committee tool call.  It carries no durable
            # committee plan, so it cannot bound the agent's declared target functions.
            return self._preflight, None
        prepared = await self._inputs.resolve()
        assert self._eligibility is not None
        decision = await self._eligibility.evaluate(
            prepared.preflight.request,
            authorization=prepared.authorization,
            proposed_cost_cents=prepared.preflight.maximum_cost_cents,
            discovery_receipt=prepared.discovery_receipt,
        )
        if decision.outcome not in {
            CommitteeEligibilityOutcome.ELIGIBLE,
            CommitteeEligibilityOutcome.REUSABLE,
        }:
            reasons = ",".join(
                reason for condition in decision.conditions for reason in condition.reason_codes
            )
            raise EntityResearchGovernedRejection(
                "committee_eligibility_rejected",
                "Sumble committee eligibility rejected before provider dispatch: " + reasons,
            )
        # REUSABLE is still valid execution authority: the durable coordinator performs an
        # exact-fingerprint replay and returns before claiming a provider dispatch. Rejecting it
        # here would turn the required zero-spend replay path into an agent-visible failure.
        return prepared.preflight, prepared.committee_plan

    @staticmethod
    def _validate_scope_against_plan(
        scope: AccountBuyingUnitScope, *, plan: ResearchCommitteePlan | None
    ) -> None:
        """The agent may narrow the confirmed committee functions; it may never invent one.

        Matching is exact and case-insensitive: a plan function is a confirmed selector, not a
        substring to be widened into a neighbouring function.
        """

        if plan is None or not plan.functions:
            return
        allowed = {str(value).casefold(): str(value) for value in plan.functions}
        offending = tuple(
            value for value in scope.target_functions if value.casefold() not in allowed
        )
        if offending:
            # An invented function is a repairable model mistake: refuse it back to the agent
            # (R10 partial-failure policy) rather than suspending the whole account job.
            raise EntityResearchGovernedRejection(
                "committee_scope_outside_plan",
                "buying-unit scope targets functions outside the confirmed committee plan: "
                f"{', '.join(offending)}; the plan allows: {', '.join(allowed.values())}",
            )

    @staticmethod
    def _wait_disposition(*, caused: bool) -> ProviderObservationDisposition:
        return (
            ProviderObservationDisposition.CAUSED
            if caused
            else ProviderObservationDisposition.JOINED
        )

    async def _persist_scope(
        self,
        *,
        request: GovernedResearchToolRequest,
        scope: AccountBuyingUnitScope,
        workspace_id: str,
    ) -> None:
        if not all(
            ref.startswith(("research-evidence:", "claim:", "research-result:"))
            for ref in scope.evidence_refs
        ):
            # Unreachable from a model now — ``evidence_refs`` is shape-checked at the tool's own
            # input boundary — and kept as the substrate backstop for any other caller.
            raise EntityResearchResultIntegrityError(
                "buying-unit scope requires durable account evidence references"
            )
        async with self._conn_factory() as conn:
            # Result/evidence references are scoped by their owning exact job. Claim references are
            # allowed only when the claim belongs to the account itself.
            for ref in scope.evidence_refs:
                if ref.startswith("research-result:"):
                    found = await conn.execute(
                        text(
                            "SELECT 1 FROM entity_research_result result JOIN "
                            "entity_research_tool_request request_row ON "
                            "request_row.tool_request_id=result.tool_request_id "
                            "WHERE result.result_id=:id AND request_row.job_id=:job_id"
                        ),
                        {
                            "id": UUID(ref.removeprefix("research-result:")),
                            "job_id": request.job_id,
                        },
                    )
                elif ref.startswith("research-evidence:"):
                    found = await conn.execute(
                        text(
                            "SELECT 1 FROM entity_research_result_evidence evidence JOIN "
                            "entity_research_result result ON result.result_id=evidence.result_id "
                            "JOIN entity_research_tool_request request_row ON "
                            "request_row.tool_request_id=result.tool_request_id "
                            "WHERE evidence.evidence_id=:id AND request_row.job_id=:job_id"
                        ),
                        {
                            "id": UUID(ref.removeprefix("research-evidence:")),
                            "job_id": request.job_id,
                        },
                    )
                else:
                    found = await conn.execute(
                        text("SELECT 1 FROM claim WHERE id=:id AND entity_id=:account_id"),
                        {
                            "id": UUID(ref.removeprefix("claim:")),
                            "account_id": request.target_entity_id,
                        },
                    )
                if found.scalar_one_or_none() is None:
                    # A model-authored reference to something this job/account does not own is the
                    # repairable species (the same class ``cd15398d`` converted across the read
                    # tools), not a truth violation: refuse it back with the exact repair instead
                    # of suspending the job. An engine-composed reference cannot land here — it is
                    # read from this job's own results and the account's own claim.
                    raise EntityResearchGovernedRejection(
                        "committee_scope_evidence_outside_job",
                        f"buying_unit_scope.evidence_refs cites {ref[:80]!r}, which this account "
                        "job does not own. Use only references your own "
                        "read_account_research_state result index surfaces "
                        "('result_refs' like 'research-result:<uuid>', "
                        "'existing_claims[].claim_ref' like 'claim:<uuid>'), or omit the key "
                        "entirely and the engine cites the evidence this job already holds.",
                    )
            values = {
                "scope_id": scope.scope_id,
                "tool_request_id": request.tool_call_id,
                "run_id": request.research_run_id,
                "job_id": request.job_id,
                "workspace_id": workspace_id,
                "account_id": request.target_entity_id,
                "scope_json": serialize_value_json(scope.model_dump(mode="json")),
                "scope_sha": hashlib.sha256(
                    json.dumps(
                        scope.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_committee_scope
                        (scope_id, tool_request_id, research_run_id, job_id, workspace_id,
                         account_entity_id, scope_json, scope_sha256)
                    VALUES (:scope_id, :tool_request_id, :run_id, :job_id, :workspace_id,
                            :account_id, CAST(:scope_json AS jsonb), :scope_sha)
                    ON CONFLICT DO NOTHING
                    """
                ),
                values,
            )
            stored = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT scope_id, tool_request_id, research_run_id, job_id, "
                            "workspace_id, account_entity_id, scope_sha256 FROM "
                            "entity_research_account_committee_scope "
                            "WHERE scope_id=:scope_id OR tool_request_id=:tool_request_id "
                            "ORDER BY created_at, scope_id"
                        ),
                        {
                            "scope_id": scope.scope_id,
                            "tool_request_id": request.tool_call_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            if (
                len(stored) != 1
                or stored[0]["scope_id"] != scope.scope_id
                or stored[0]["research_run_id"] != request.research_run_id
                or stored[0]["job_id"] != request.job_id
                or str(stored[0]["workspace_id"]) != workspace_id
                or stored[0]["account_entity_id"] != request.target_entity_id
                or str(stored[0]["scope_sha256"]) != values["scope_sha"]
            ):
                raise EntityResearchResultIntegrityError("buying-unit scope replay changed")

    @staticmethod
    def _office_candidates(
        candidates: Sequence[CommitteePersonCandidate], *, scope: AccountBuyingUnitScope
    ) -> tuple[tuple[CommitteePersonCandidate, ...], int, int]:
        """Classify provider-returned candidates into selected / excluded / review-routed.

        Under the default ``company_wide`` policy the floor is **provider-returned, and nothing
        more** (founder rulings 2026-08-20). Three discriminators retired, in this order, each
        after a live execution that admitted real people it should not have refused:

        * office placement — a multi-site HQ committee is not evidenced by profile metros;
        * the ``sumble_people`` grounding filter — a Teams-organization-map row is provider data
          bought in the same paid operation, not a weaker species of truth;
        * the ``target_functions`` string match — the provider's vocabulary is its own
          ("Physician" where the plan says "Clinical", "Uncategorized" where it says nothing at
          all), and reconciling vocabulary is agent judgment, not string equality.

        What survives under ``company_wide`` is the one discriminator the agent *declares on
        purpose*: a non-null ``business_unit`` is an assertion of organization membership, matched
        against provider-returned team names and current-employer organization names. A candidate
        the agent's own declared unit does not cover routes to review, never to silent admission.

        ``same_office_strict``, selected by name, keeps all three retired tiers exactly as they
        were, so every historical scope replays under the policy it recorded.
        """

        selected: list[CommitteePersonCandidate] = []
        excluded = ambiguous = 0
        strict = scope.match_policy == "same_office_strict"
        for candidate in candidates:
            people_facts = tuple(
                fact
                for fact in candidate.professional_facts
                if fact.source_key == PEOPLE_SOURCE_KEY
            )
            facts_by_field: dict[str, list[object]] = {}
            for fact in candidate.professional_facts:
                facts_by_field.setdefault(str(fact.field_key), []).append(fact.value_json)
            # Every discriminator matches provider-returned *values* only. Serializing whole fact
            # objects let a scope term collide with structural JSON keys ("relationship",
            # "current_employee", "teams"), which is a match against our own schema, not against
            # evidence.
            location_haystack = _match_haystack(
                candidate.geo,
                facts_by_field.get(str(CURRENT_LOCATION), ()),
            )
            business_unit_haystack = _match_haystack(
                candidate.team_names,
                facts_by_field.get(str(TEAM_MEMBERSHIP), ()),
                # A buying unit may be the exact organization itself (common for a small
                # practice) rather than a provider-modeled sub-team.  Sumble's returned
                # current-employer organization *name* is a strong, inspectable organization
                # binding and may satisfy that organization-wide unit.  A title, free-text
                # location, or inferred employer never participates in this discriminator.
                _organization_names(facts_by_field.get(str(ORGANIZATION_RELATIONSHIP), ())),
            )
            function_haystack = _match_haystack(
                candidate.job_function,
                facts_by_field.get(str(JOB_FUNCTION), ()),
                # A title is an allowed fallback only inside the function dimension; it can
                # never satisfy an office, facility, or business-unit discriminator.
                candidate.title,
            )
            # Always True under the default ``company_wide`` policy (founder ruling 2026-08-20):
            # office placement can no longer send a candidate to review or exclusion. The
            # business-unit discriminator below is organization membership, not geography, and
            # stays live under both policies.
            location_match = _location_scope_match(scope, haystack=location_haystack)
            business_unit_match = (
                scope.business_unit is None
                or scope.business_unit.casefold() in business_unit_haystack
            )
            # Retired under ``company_wide``: a provider-returned candidate is grounded by having
            # been returned, whichever page returned them, and the provider's function vocabulary
            # is not the confirmed plan's vocabulary.
            grounded = bool(people_facts) if strict else True
            function_match = (
                any(value.casefold() in function_haystack for value in scope.target_functions)
                if strict
                else True
            )
            if not grounded:
                ambiguous += 1
            elif location_match and business_unit_match and function_match:
                selected.append(candidate)
            elif not location_match or not business_unit_match:
                ambiguous += 1
            else:
                excluded += 1
        return tuple(selected), excluded, ambiguous

    def _committee_descriptor(
        self,
        operation: object,
        *,
        disposition: ProviderObservationDisposition,
        include_dispatch: bool,
    ) -> ProviderOperationReservation:
        typed = cast("CommitteeAcquisitionOperation", operation)
        created = typed.created_at or datetime.now(UTC)
        return ProviderOperationReservation(
            provider_kind=self.provider_kind,
            operation_ref=f"committee-operation:{typed.operation_id}",
            workspace_id=typed.request.workspace_id,
            project_id=typed.request.project_id,
            project_run_id=UUID(str(typed.request.project_run_id)),
            subject_type=ResearchSubjectType.ACCOUNT,
            target_entity_id=UUID(str(typed.request.account_id)),
            source_key=PEOPLE_SOURCE_KEY,
            field_keys=(),
            request_artifact_ref=f"artifact:{typed.input_artifact_key}",
            reserved_at=created,
            dispatched_at=typed.started_at if include_dispatch else None,
            observation_disposition=disposition,
        )

    async def _persist_committee_projection(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: object,
        provider_operation: ProviderOperationReservation,
        committee: object,
        excluded: int,
        ambiguous: int,
    ) -> tuple[str, tuple[ResearchDiscoveredSubjectProjection, ...]]:
        typed = cast("CommitteeAcquisitionOperation", operation)
        result = cast("CommitteeResult", committee)
        async with self._conn_factory() as conn:
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=typed.request.workspace_id,
                operation_id=typed.operation_id,
            )
            people_snapshot = next(
                item for item in snapshots if item.source_key == PEOPLE_SOURCE_KEY
            )
            if people_snapshot.response_artifact_key is None:
                raise EntityResearchResultIntegrityError("People committee snapshot lacks evidence")
            # The operation's snapshot_ref remains the People one: it names the whole semantic
            # acquisition, and both component snapshots hang off the same operation id.
            snapshot_ref = (
                f"committee-snapshot:{typed.operation_id}:{PEOPLE_SOURCE_KEY}:"
                f"{people_snapshot.request_fingerprint}"
            )
            # Every component snapshot this exact operation paid for is admissible provenance
            # (founder ruling 2026-08-20 — the truth floor is provider-returned, and a Teams
            # organization-map row is provider data bought in the same call). A member whose
            # facts came only through Teams was previously refused here as "lacking direct People
            # facts", which is how the live v9 review class would have suspended the job.
            snapshot_ref_by_source = {
                item.source_key: (
                    f"committee-snapshot:{typed.operation_id}:{item.source_key}:"
                    f"{item.request_fingerprint}"
                )
                for item in snapshots
                if item.response_artifact_key is not None
            }
            provider_source_id_by_source = {
                item.source_key: (item.provider_operation_id or str(typed.operation_id))
                for item in snapshots
            }
            subjects: list[ResearchDiscoveredSubjectProjection] = []
            for member in result.members:
                candidate_claim_ids = [UUID(str(value)) for value in member.professional_claim_ids]
                if candidate_claim_ids:
                    rows = (
                        (
                            await conn.execute(
                                text(
                                    """
                                    SELECT id, field_key, value_json, source_key, source_url,
                                           artifact_key, evidence_span, confidence,
                                           verification_status::text
                                    FROM claim WHERE id=ANY(:claim_ids)
                                      AND source_key=ANY(:source_keys)
                                      AND source_operation_ref=:operation_ref
                                      AND source_snapshot_ref=ANY(:snapshot_refs)
                                    ORDER BY collected_at, id
                                    """
                                ),
                                {
                                    "claim_ids": candidate_claim_ids,
                                    "source_keys": list(snapshot_ref_by_source),
                                    "operation_ref": f"committee-operation:{typed.operation_id}",
                                    "snapshot_refs": list(snapshot_ref_by_source.values()),
                                },
                            )
                        )
                        .mappings()
                        .all()
                    )
                else:
                    rows = ()
                if not rows:
                    raise EntityResearchResultIntegrityError(
                        "admitted committee member lacks provider-returned facts from this "
                        "operation"
                    )
                fields = tuple(
                    ResearchFieldResultProjection(
                        field_key=str(row["field_key"]),
                        outcome=ResearchFieldOutcome.FOUND,
                        value=decode_jsonb_scalar(row["value_json"]),
                        claim_delta=ResearchClaimDelta.ACCEPTED,
                        claim_refs=(f"claim:{row['id']}",),
                        evidence=(
                            ResearchEvidenceProjection(
                                evidence_ref=self._committee_evidence_ref(
                                    typed.operation_id, row["id"]
                                ),
                                source_key=str(row["source_key"]),
                                provider_source_id=provider_source_id_by_source.get(
                                    str(row["source_key"]), str(typed.operation_id)
                                ),
                                source_url=(str(row["source_url"]) if row["source_url"] else None),
                                artifact_ref=f"artifact:{row['artifact_key']}",
                                evidence_span=str(row["evidence_span"]),
                            ),
                        ),
                        confidence=float(cast(Decimal, row["confidence"])),
                        verification_status=str(row["verification_status"]),
                    )
                    for row in rows
                )
                subjects.append(
                    ResearchDiscoveredSubjectProjection(
                        subject_type=ResearchSubjectType.CONTACT,
                        target_entity_id=UUID(str(member.contact_entity_id)),
                        parent_account_id=request.target_entity_id,
                        strong_identity_claim_refs=(f"claim:{member.discovery_claim_id}",),
                        association_evidence_refs=(f"claim:{member.discovery_claim_id}",),
                        fields=fields,
                    )
                )
            raw_refs = [
                f"artifact:{item.response_artifact_key}"
                for item in snapshots
                if item.response_artifact_key is not None
            ]
            payload = {
                "contract": "m8d-r5-sumble-office-committee-v1",
                "operation_id": str(typed.operation_id),
                "coverage": result.coverage.model_dump(mode="json"),
                "members": [item.model_dump(mode="json") for item in subjects],
                "excluded_candidate_count": excluded,
                "ambiguous_candidate_count": ambiguous,
            }
            normalized_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=typed.request.workspace_id,
                content=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                media_type="application/json",
                source_key=PEOPLE_SOURCE_KEY,
            )
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=typed.request.workspace_id,
                artifact_key_value=normalized_key,
                subject_kind="account",
                subject_entity_id=typed.request.account_id,
                reference_kind="entity_research_sumble_committee_normalized",
                reference_id=provider_operation.operation_ref,
            )
            if not raw_refs or typed.receipt_manifest_key is None:
                raise EntityResearchResultIntegrityError(
                    "settled committee operation lacks raw responses or receipt"
                )
            values = {
                "operation_ref": provider_operation.operation_ref,
                "workspace_id": typed.request.workspace_id,
                "snapshot_ref": snapshot_ref,
                "normalized_key": normalized_key,
                "raw_refs": raw_refs,
                "receipt_ref": f"artifact:{typed.receipt_manifest_key}",
                "settlement_ref": f"sumble-committee-settlement:{typed.operation_id}",
                "provider_request_id": (
                    people_snapshot.provider_operation_id or str(typed.operation_id)
                ),
                "reported_cost": typed.cost_cents_charged,
                "settled_cost": typed.cost_cents_charged,
                "metadata": serialize_value_json(
                    {
                        "excluded_candidate_count": excluded,
                        "ambiguous_candidate_count": ambiguous,
                    }
                ),
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_sumble_projection
                        (provider_operation_ref, workspace_id, provider_snapshot_ref,
                         normalized_result_artifact_key, raw_response_artifact_refs,
                         retained_result_artifact_refs, provider_receipt_ref,
                         cost_settlement_ref, provider_request_id,
                         provider_reported_cost_cents, settled_cost_cents, metadata_json)
                    VALUES (:operation_ref, :workspace_id, :snapshot_ref, :normalized_key,
                            :raw_refs, :raw_refs, :receipt_ref, :settlement_ref,
                            :provider_request_id, :reported_cost, :settled_cost,
                            CAST(:metadata AS jsonb))
                    ON CONFLICT (provider_operation_ref) DO NOTHING
                    """
                ),
                values,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT provider_snapshot_ref, normalized_result_artifact_key, "
                            "raw_response_artifact_refs, provider_receipt_ref, "
                            "cost_settlement_ref, provider_request_id, "
                            "provider_reported_cost_cents, settled_cost_cents, metadata_json "
                            "FROM entity_research_sumble_projection "
                            "WHERE provider_operation_ref=:operation_ref"
                        ),
                        {"operation_ref": provider_operation.operation_ref},
                    )
                )
                .mappings()
                .one()
            )
            replay_differs = (
                str(stored["provider_snapshot_ref"]) != snapshot_ref
                or str(stored["normalized_result_artifact_key"]) != normalized_key
                or tuple(str(value) for value in stored["raw_response_artifact_refs"])
                != tuple(raw_refs)
                or str(stored["provider_receipt_ref"]) != values["receipt_ref"]
                or str(stored["cost_settlement_ref"]) != values["settlement_ref"]
                or str(stored["provider_request_id"]) != values["provider_request_id"]
                or Decimal(str(stored["provider_reported_cost_cents"]))
                != Decimal(str(values["reported_cost"]))
                or Decimal(str(stored["settled_cost_cents"]))
                != Decimal(str(values["settled_cost"]))
                or serialize_value_json(stored["metadata_json"]) != values["metadata"]
            )
            # Same rule as the account projection above, with the same two boundaries: an operation
            # whose replay differs and that carries an admitted result serves what THAT RESULT
            # recorded (its discovered subjects, evidence spans and all), never the stored
            # projection row — the row and the admitted record diverge permanently once a
            # never-admitted operation's first replay serves fresh (live job 3cc0a4f2, 06:37:33) —
            # and an operation with no admitted result anywhere was shown to no turn, so its stored
            # first write is a failed draft and the fresh recomputation is returned. The
            # append-only table keeps the first write at rest as audit either way (see the account
            # branch for the live wedge this closes).
            admitted = (
                await _first_admitted_projection(
                    conn, self._storage, operation_ref=provider_operation.operation_ref
                )
                if replay_differs
                else None
            )
            if admitted is not None:
                return admitted.snapshot_ref, admitted.result.discovered_subjects
        return snapshot_ref, tuple(subjects)

    @staticmethod
    def _committee_evidence_ref(operation_id: object, claim_id: object) -> str:
        identity = uuid5(_EVIDENCE_NAMESPACE, f"{operation_id}:{claim_id}")
        return f"research-evidence:{identity}"


__all__ = [
    "SumbleAccountSemanticEnrichmentAction",
    "SumbleCommitteeSemanticResearchAction",
    "SumbleEntityResearchLineageReader",
    "resolve_account_buying_unit_scope",
]
