"""R5 account-agent semantic contracts layered over the frozen M8D R0/R4 kernel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from clue_agents.entity_research_tools import EntityResearchSemanticToolInput
from clue_core import Persona
from clue_core.entity_research import ResearchFinalizationOutcome

NonEmptyStr = Annotated[str, Field(min_length=1)]
#: The reference schemes ``_persist_scope`` can resolve against this job's own retained evidence.
#: ``research-evidence:`` is the third, admitted historically and still valid, but it is not
#: advertised to the model: an evidence span is reached through its result.
_EVIDENCE_REF_PREFIXES = ("claim:", "research-result:", "research-evidence:")

#: One text per scope field, carried into the JSON schema the model reads on *every* call.
#: Written once and shared by the model-facing request shape and the durable resolved shape so the
#: two can never describe the same field differently. Before this existed the meaning of
#: ``evidence_refs`` lived only in a ``#`` comment and one manual sentence — invisible where the
#: model actually decides — and seven of eight live committee calls died at this boundary with
#: "Field required" and nothing to repair from (run ``dc86340f``, 2026-08-20).
_SCOPE_ID_DESC = (
    "Optional and ignored: the engine derives the durable scope id from this exact tool call. "
    "Omit it — inventing one can only collide with another call's scope."
)
_ACCOUNT_ENTITY_ID_DESC = (
    "Optional: defaults to this job's own account. Send it only to restate that account; any "
    "other uuid is refused."
)
_OFFICE_LABEL_DESC = (
    "Optional label for the buying unit, e.g. 'Fort Myers, Florida headquarters'. Omit it and the "
    "engine composes one from the account's own HQ-location evidence. Audited description, not a "
    "filter."
)
_FACILITY_NAME_DESC = (
    "Optional exact site/building. Omit the whole office block and the engine fills it from the "
    "account's HQ-location evidence."
)
_LOCALITY_DESC = (
    "Optional city. Engine-filled from the account's HQ-location evidence when omitted."
)
_REGION_DESC = (
    "Optional state/region. Engine-filled from the account's HQ-location evidence when omitted."
)
_COUNTRY_DESC = (
    "Optional country. Engine-filled from the account's HQ-location evidence when omitted."
)
_BUSINESS_UNIT_DESC = (
    "Optional, and the one office field that still narrows admission: an assertion of "
    "organization membership, matched against provider-returned team names and current-employer "
    "organization names. A candidate it does not cover is routed to review, never admitted. The "
    "engine never fills it — declare it only when you mean it."
)
_TARGET_FUNCTIONS_DESC = (
    "Advisory, 0-20 unique functions: which of the confirmed committee plan's functions you set "
    "out to map, kept as durable audited intent. Advisory means it admits and excludes nobody "
    "under the default 'company_wide' policy, so an empty list is a legal, honest answer. Each "
    "entry you do send must be copied from the confirmed plan (case-insensitive); an invented "
    "function is refused. Only 'same_office_strict' gates admission on it."
)
_EVIDENCE_REFS_DESC = (
    "0-20 unique retained account-evidence references, each exactly 'claim:<uuid>' or "
    "'research-result:<uuid>' (e.g. 'claim:31b404b5-4150-4a9b-b515-53f5d315372d', "
    "'research-result:255d9f35-0697-5e76-9e27-6ebdc1fdb7f2'). They come from your own "
    "read_account_research_state result index: 'result_refs' and 'existing_claims[].claim_ref'. "
    "Omit the key and the engine cites the account evidence this job already holds; a reference "
    "outside this job or account is refused."
)
_MATCH_POLICY_DESC = (
    "'company_wide' (the default — omit the key): the admission floor is provider-returned and "
    "nothing more, so the declared office and functions veto nobody. 'same_office_strict' is the "
    "retired policy, still selectable by name: office placement vetoes, target_functions gates, "
    "and a candidate with no direct People-page fact routes to review. It requires a declared "
    "facility_name / locality / region / business_unit, because it enforces one."
)
_BUYING_UNIT_SCOPE_DESC = (
    "The buying unit this call sets out to map, recorded durably for audit. Every field is "
    "optional and the whole object may be omitted: the engine composes the account, its office "
    "and its evidence references from this job's own durable state. Send only what you "
    "deliberately want to be narrower or different."
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountBuyingUnitScopeRequest(_FrozenModel):
    """What the *model* may declare about the buying unit — every field optional.

    Founder ruling 2026-08-20, "the engine disposes, it never quizzes": of the six fields this
    scope once demanded, five are things the engine already holds — the scope id (ceremony with a
    collision failure mode), the account (the job is bound to exactly one), the office (the
    account's own HQ-location evidence), and the evidence references (this job's own result index).
    Asking the model to restate them bought nothing and cost, live, seven of eight committee calls.
    What is left here is genuine judgment: which functions the agent set out to map, which policy
    it wants enforced, and any *deliberately narrower* office or business unit.

    :class:`AccountBuyingUnitScope` is the completed form the engine persists, hashes and gates on;
    a complete scope is a valid request, which is why it subclasses this shape (a model that still
    sends everything explicitly keeps working, unchanged).
    """

    scope_id: UUID | None = Field(default=None, description=_SCOPE_ID_DESC)
    account_entity_id: UUID | None = Field(default=None, description=_ACCOUNT_ENTITY_ID_DESC)
    office_label: NonEmptyStr | None = Field(default=None, description=_OFFICE_LABEL_DESC)
    facility_name: NonEmptyStr | None = Field(default=None, description=_FACILITY_NAME_DESC)
    locality: NonEmptyStr | None = Field(default=None, description=_LOCALITY_DESC)
    region: NonEmptyStr | None = Field(default=None, description=_REGION_DESC)
    country: NonEmptyStr | None = Field(default=None, description=_COUNTRY_DESC)
    business_unit: NonEmptyStr | None = Field(default=None, description=_BUSINESS_UNIT_DESC)
    target_functions: tuple[NonEmptyStr, ...] = Field(
        default=(), max_length=20, description=_TARGET_FUNCTIONS_DESC
    )
    evidence_refs: tuple[NonEmptyStr, ...] = Field(
        default=(), max_length=20, description=_EVIDENCE_REFS_DESC
    )
    match_policy: Literal["company_wide", "same_office_strict"] = Field(
        default="company_wide", description=_MATCH_POLICY_DESC
    )

    @field_validator("target_functions")
    @classmethod
    def _unique_target_functions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("buying-unit target functions must be unique")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _durable_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Unique, and each one a reference shape the engine can actually resolve.

        Checked on the *field* rather than the model so the refusal's location names
        ``evidence_refs`` and carries its correction (the exact ref formats and where the agent's
        own state surfaces them). Checked at all because the durable persist path parses these as
        uuids behind a prefix: a model-authored ``"the Q3 filing"`` used to reach it and raise the
        *suspending* integrity species over what is plainly a repairable typo.
        """

        if len(value) != len(set(value)):
            raise ValueError("buying-unit evidence references must be unique")
        for reference in value:
            prefix, _, identifier = reference.partition(":")
            if f"{prefix}:" not in _EVIDENCE_REF_PREFIXES:
                raise ValueError(
                    "buying-unit evidence reference must be 'claim:<uuid>' or "
                    f"'research-result:<uuid>', not {reference[:60]!r}"
                )
            try:
                UUID(identifier)
            except ValueError as invalid:
                raise ValueError(
                    f"buying-unit evidence reference {reference[:60]!r} does not carry a uuid"
                ) from invalid
        return value

    @model_validator(mode="after")
    def _bounded_declaration(self) -> Self:
        if self.match_policy == "same_office_strict" and not any(
            (self.facility_name, self.locality, self.region, self.business_unit)
        ):
            # The office rule survives exactly where it still means something. Under the retired
            # strict policy the office is an enforced veto, so a scope selecting it must declare
            # what it enforces. Under ``company_wide`` geography admits and excludes nobody, and
            # an account whose location nothing has yet evidenced would otherwise force the engine
            # to invent a locality to satisfy a rule that decides nothing.
            raise ValueError(
                "same_office_strict enforces office placement and needs a facility_name, "
                "locality, region, or business_unit to enforce"
            )
        return self


class AccountBuyingUnitScope(AccountBuyingUnitScopeRequest):
    """The complete office/facility/business unit an account job durably records for one call.

    This is the *resolved* scope — what the engine persists into
    ``entity_research_account_committee_scope``, hashes into ``scope_sha256`` and gates candidates
    with. Whatever the model declared, the engine composes the rest from durable state, so the
    account, its office label and its scope id are always present here even though the model may
    have sent none of them.

    The provider may enumerate a broader organization; the scope records, in durable audited form,
    which buying unit the agent set out to map.

    ``match_policy`` chooses how much of that declaration is *enforced*:

    - ``company_wide`` (default, founder rulings 2026-08-20) — the **truth floor is
      provider-returned, and nothing more**.  Every candidate the provider returned is admitted:
      People rows and Teams-organization-map rows alike, whatever function string the provider
      spells.  The declared office, functions and source path are descriptive, audited context.
      Two live executions forced this.  The first (913-person, multi-site physician group) fetched
      seven real candidates and admitted zero, because no provider profile value could place
      anyone at the declared headquarters.  The second, after the office veto retired, admitted
      one of the same seven: two current CXOs were excluded because the plan said "Clinical" where
      the provider says "Physician", and four more were routed to review only because their facts
      arrived through Teams rather than People.  Vocabulary and persona judgment are the account
      agent's work — taught by its operations manual, not enforced by string equality here.  A
      *declared* ``business_unit`` still narrows admission: that is organization membership the
      agent chose to assert, not geography and not a function synonym.
    - ``same_office_strict`` — the retired policy, still selectable explicitly: office placement
      vetoes, the target functions gate, and a candidate carrying no ``sumble_people`` fact routes
      to durable review.

    The rulings are policy retirements, not deletions: historical scopes replay byte-identically
    under the policy they recorded.

    The field *set* is frozen: ``scope_sha256`` is taken over ``model_dump(mode="json")`` and every
    persisted scope must re-hash to what it recorded. Requiredness may relax (a value the model
    used to send and the engine now composes dumps identically); a new or renamed field would
    break every historical replay.
    """

    scope_id: UUID = Field(description=_SCOPE_ID_DESC)
    account_entity_id: UUID = Field(description=_ACCOUNT_ENTITY_ID_DESC)
    office_label: NonEmptyStr = Field(description=_OFFICE_LABEL_DESC)


#: Keyed on the last recognised name in a Pydantic error location, so ``["buying_unit_scope",
#: "evidence_refs", 0]`` and ``["buying_unit_scope", "evidence_refs"]`` get the same repair.
_COMMITTEE_INPUT_CORRECTIONS: Mapping[str, str] = {
    "evidence_refs": (
        "'buying_unit_scope.evidence_refs' takes 0-20 unique retained account-evidence "
        "references, each exactly 'claim:<uuid>' or 'research-result:<uuid>' — for example "
        "'claim:31b404b5-4150-4a9b-b515-53f5d315372d' or "
        "'research-result:255d9f35-0697-5e76-9e27-6ebdc1fdb7f2'. Take them verbatim from your own "
        "read_account_research_state result index ('result_refs' and "
        "'existing_claims[].claim_ref'); never build one from another id. Simplest repair: drop "
        "the key entirely and the engine cites the evidence this job already holds."
    ),
    "source_keys": (
        "'source_keys' needs at least one committee-enumeration source key copied verbatim from "
        "read_account_research_state's 'committee_source_keys', for example ['sumble_people']."
    ),
    "field_keys": (
        "'field_keys' must be omitted or []: committee discovery enumerates people, never account "
        "fields. Research fields with research_account_deep or enrich_account instead."
    ),
    "questions": (
        "'questions' takes confirmed committee questions copied verbatim from the committee plan "
        "in your task instruction, or [] when it confirms none. Never paraphrase or invent one."
    ),
    "target_functions": (
        "'buying_unit_scope.target_functions' is advisory: 0-20 unique functions copied from the "
        "confirmed committee plan. Omit the key when in doubt — it admits and excludes nobody "
        "under the default 'company_wide' policy."
    ),
    "match_policy": (
        "'buying_unit_scope.match_policy' is 'company_wide' (the default — omit the key) or "
        "'same_office_strict'. The strict policy also requires a declared facility_name, "
        "locality, region, or business_unit, because it enforces one."
    ),
    "scope_id": (
        "'buying_unit_scope.scope_id' must be a uuid or, better, omitted entirely: the engine "
        "derives the durable scope id from this tool call."
    ),
    "account_entity_id": (
        "'buying_unit_scope.account_entity_id' must be this job's own account uuid (see "
        "read_account_research_state's 'account_entity_id'), or omitted so the engine fills it."
    ),
    "parent_operation_ref": (
        "'parent_operation_ref', 'parent_observation_ref' and 'follow_up_reason' must all be null "
        "or omitted: committee enumeration is not a field follow-up. Cite account evidence in "
        "'buying_unit_scope.evidence_refs' instead."
    ),
    "buying_unit_scope": (
        "'buying_unit_scope' is an object and every field in it is optional — the engine composes "
        "the account, its office and its evidence references from this job's durable state. Send "
        "{} (or omit it) unless you deliberately want a narrower office, a 'business_unit', "
        "advisory 'target_functions', or 'same_office_strict'."
    ),
}
_COMMITTEE_INPUT_CORRECTIONS = {
    **_COMMITTEE_INPUT_CORRECTIONS,
    "parent_observation_ref": _COMMITTEE_INPUT_CORRECTIONS["parent_operation_ref"],
    "follow_up_reason": _COMMITTEE_INPUT_CORRECTIONS["parent_operation_ref"],
}
#: Whole-object violations (a model validator, a non-object scope) carry no field location, so the
#: refusal states the one call shape that is always legal.
_COMMITTEE_WHOLE_INPUT_CORRECTION = (
    "The minimal legal committee call is {'source_keys': ['<an admitted committee source key>'], "
    "'field_keys': [], 'questions': []} — the engine composes the whole buying_unit_scope "
    "(account, office, and 'claim:<uuid>' / 'research-result:<uuid>' evidence references) from "
    "this job's durable state. read_account_research_state lists the admitted source keys and, in "
    "'result_refs' / 'existing_claims[].claim_ref', the exact references."
)


class DiscoverBuyingCommitteeInput(EntityResearchSemanticToolInput):
    """Committee research intent plus an account-evidence-backed office boundary."""

    field_keys: tuple[NonEmptyStr, ...] = Field(
        default=(),
        max_length=0,
        description="Always empty: committee discovery enumerates people, not account fields.",
    )
    source_keys: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description=(
            "At least one exact admitted committee-enumeration source key, copied verbatim from "
            "read_account_research_state's 'committee_source_keys' (for example "
            "['sumble_people']). A source outside that list is refused."
        ),
    )
    questions: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Verbatim confirmed committee questions only; never synthesize or paraphrase one. "
            "Leave empty when the confirmed committee plan carries no question — an empty tuple "
            "is the honest value, and the engine refuses any question the plan does not contain."
        ),
    )
    parent_operation_ref: None = Field(
        default=None,
        description="Always null: committee enumeration is not a field follow-up.",
    )
    parent_observation_ref: None = Field(
        default=None,
        description="Always null: cite account evidence in buying_unit_scope.evidence_refs.",
    )
    follow_up_reason: None = Field(
        default=None,
        description="Always null: committee enumeration is not a field follow-up.",
    )
    buying_unit_scope: AccountBuyingUnitScopeRequest = Field(
        default_factory=AccountBuyingUnitScopeRequest,
        description=_BUYING_UNIT_SCOPE_DESC,
    )

    @model_validator(mode="after")
    def _enumeration_is_not_field_research_or_follow_up(self) -> Self:
        if self.field_keys:
            raise ValueError("committee discovery enumerates people and must not request fields")
        if any(
            value is not None
            for value in (
                self.parent_operation_ref,
                self.parent_observation_ref,
                self.follow_up_reason,
            )
        ):
            raise ValueError("committee discovery is not an additive field follow-up")
        return self

    @classmethod
    def validation_correction(cls, location: Sequence[object]) -> str | None:
        """The exact next move for one rejected argument location, or ``None`` when unknown.

        A schema violation is refused *before* any provider call, so the only thing that decides
        whether the agent recovers is what the refusal says. ``{"location": ["buying_unit_scope",
        "evidence_refs"], "message": "Field required"}`` — the shape that killed seven of eight
        live committee calls — named the field and nothing else: not what belongs in it, not what
        one looks like, not where to get one. These corrections travel with the refusal so the
        message names the exact repair the same way the already-acquired refusal names the exact
        field set to re-ask (``b60824d4``).
        """

        for part in reversed([str(part) for part in location]):
            correction = _COMMITTEE_INPUT_CORRECTIONS.get(part)
            if correction is not None:
                return correction
        return _COMMITTEE_WHOLE_INPUT_CORRECTION


class ReadAccountResearchStateInput(_FrozenModel):
    include_result_index: bool = True


class CommitteeRoleInference(_FrozenModel):
    """One evidence-cited committee judgment authored by the responsible account agent."""

    contact_entity_id: UUID
    role: Persona
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2_000)
    evidence_claim_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)


class RecordCommitteeRoleInferencesInput(_FrozenModel):
    """A bounded batch of role judgments; omitted discovered members remain roleless."""

    inferences: tuple[CommitteeRoleInference, ...] = Field(min_length=1, max_length=64)


class InspectAccountEvidenceInput(_FrozenModel):
    result_refs: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("account evidence result references must be unique")
        return self


class AssessAccountCoverageInput(_FrozenModel):
    """Model explanation is advisory; the engine derives coverage from persisted results.

    ``result_refs`` may be **empty** (FI-2 §6.1): an account whose every admitted field was already
    known — fresh, evidence-backed, conflict-free and ``project_neutral`` — is researched by
    spending nothing, so there is no result to cite. The set is still authority-checked, just not
    by a length: the engine requires it to equal the job's persisted result set exactly (so a job
    that *did* research cannot zero-close), and it re-derives every completed field's evidence from
    durable rows regardless of what the model says here.
    """

    result_refs: tuple[NonEmptyStr, ...] = Field(max_length=100)
    assessment_note: NonEmptyStr

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("coverage result references must be unique")
        return self


class FinalizeAccountResearchInput(_FrozenModel):
    coverage_ledger_ref: NonEmptyStr
    requested_outcome: ResearchFinalizationOutcome


class AccountCommitteePlanProjection(_FrozenModel):
    """The confirmed committee authority of the job's pinned directive, projected read-only.

    The agent may narrow this plan for one office, but it may never widen or invent a target
    function: the engine validates every committee call's ``target_functions`` against it.
    """

    directive_ref: NonEmptyStr
    functions: tuple[NonEmptyStr, ...] = ()
    levels: tuple[NonEmptyStr, ...] = ()
    teams: tuple[NonEmptyStr, ...] = ()
    personas: tuple[NonEmptyStr, ...] = ()
    candidate_cap: int = Field(ge=1)
    questions: tuple[NonEmptyStr, ...] = ()


class AccountExistingClaimProjection(_FrozenModel):
    """One admitted field's *already known* current truth, read before this job spends (FI-2 §6.1).

    Mirrors ``ContactExistingClaimProjection`` and adds ``research_scope`` — the field's species,
    which the account economics need: a ``project_neutral`` fact is the world's answer and any
    project may reuse it while it is fresh, evidence-backed and conflict-free (born-complete);
    a ``project_relative`` value is *this* project's answer, so another project's fresh claim is
    never a substitute for researching it here.
    """

    field_key: NonEmptyStr
    claim_ref: NonEmptyStr
    value: JsonValue
    source_url: str | None = None
    source_tier: int = Field(ge=1, le=4)
    evidence_span: str | None = None
    confidence: float = Field(ge=0, le=1)
    freshness_state: Literal["fresh", "stale"]
    conflict: bool
    research_scope: Literal["project_neutral", "project_relative"]

    @property
    def born_complete(self) -> bool:
        """Whether this existing claim answers the field without spending anything (FI-2 §6.1)."""

        return (
            self.research_scope == "project_neutral"
            and self.freshness_state == "fresh"
            and bool(self.evidence_span)
            and not self.conflict
        )


class AccountResearchStateProjection(_FrozenModel):
    job_id: UUID
    account_entity_id: UUID
    current_state_sha256: NonEmptyStr
    admitted_field_keys: tuple[NonEmptyStr, ...]
    admitted_source_keys: tuple[NonEmptyStr, ...]
    committee_source_keys: tuple[NonEmptyStr, ...]
    existing_claims: tuple[AccountExistingClaimProjection, ...] = ()
    result_refs: tuple[NonEmptyStr, ...]
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    committee_result_refs: tuple[NonEmptyStr, ...]
    committee_member_ids: tuple[UUID, ...]
    pending_operation_refs: tuple[NonEmptyStr, ...]
    spent_cents: str
    contact_research_request_count: int = Field(ge=0)
    committee_plan: AccountCommitteePlanProjection | None = None


class AccountCoverageProjection(_FrozenModel):
    coverage_id: UUID
    coverage_ledger_ref: NonEmptyStr
    current_state_sha256: NonEmptyStr
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    unresolved_reasons: tuple[NonEmptyStr, ...]
    #: Why a completed field cost nothing — ``"<field_key>:existing_claim_fresh"`` per field the
    #: job never researched because a fresh, evidence-backed, conflict-free ``project_neutral``
    #: claim already answered it (FI-2 §6.1). It rides ``coverage_json`` rather than a column
    #: (there is none, and this is a ledger *explanation*, not authority — the authority is
    #: ``claim_refs``, which cites the exact claims that stood in for the spend).
    skipped_field_reasons: tuple[NonEmptyStr, ...] = ()
    committee_result_refs: tuple[NonEmptyStr, ...]
    committee_member_ids: tuple[UUID, ...]
    committee_status: Literal["complete", "partial", "needs_review"]
    committee_needs_review: int = Field(default=0, ge=0)
    claim_refs: tuple[NonEmptyStr, ...]
    evidence_refs: tuple[NonEmptyStr, ...]
    review_flags: tuple[NonEmptyStr, ...]
    review_item_refs: tuple[NonEmptyStr, ...]
    assessment_note: NonEmptyStr

    def as_json(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


__all__ = [
    "AccountBuyingUnitScope",
    "AccountBuyingUnitScopeRequest",
    "AccountCommitteePlanProjection",
    "AccountCoverageProjection",
    "AccountExistingClaimProjection",
    "AccountResearchStateProjection",
    "AssessAccountCoverageInput",
    "CommitteeRoleInference",
    "DiscoverBuyingCommitteeInput",
    "FinalizeAccountResearchInput",
    "InspectAccountEvidenceInput",
    "ReadAccountResearchStateInput",
    "RecordCommitteeRoleInferencesInput",
]
