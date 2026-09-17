"""The client interview as a governed source and open-ended routing surface."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityScope,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    MemoryAccepted,
    MemoryProvenanceClass,
    MemoryScopeType,
    MemorySubmission,
    MemoryType,
    MemoryWriteSeam,
    Modality,
    OnboardingInputId,
    ResearchMode,
    ReuseScope,
    RunId,
    ScopeRef,
    SourceManifest,
    UseClass,
    VolunteeredStatementId,
    new_run_id,
)
from clue_research.claimstore import (
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    WorkspaceScope,
    claims_by_ids,
    insert_claim,
    record_run_lineage,
    supersede_claim,
)
from clue_research.identity import get_account, get_contact
from clue_research.sources import RegistrySourceManifest, register_source
from clue_research.stage0.client_kb import (
    ClientKbWriteTarget,
    client_kb_write_target_for_materialization,
)
from clue_research.stage0.fields import PRODUCT_KNOWLEDGE_FIELDS
from clue_research.stage0.governed import StatementRoute, record_statement


class InterviewRoute(StrEnum):
    CLAIM = "claim"
    MEMORY = "memory"
    PROJECT_STATE = "project_state"
    FIELD_PROPOSAL = "field_proposal"
    SOURCE_PROPOSAL = "source_proposal"
    UNMAPPED = "unmapped"


class InterviewStatement(BaseModel):
    """One routed part of the captured answer: its species, its verbatim evidence quote, and the
    fields that species requires. (One minimal-actor classification; C6 can later produce the same
    contract.)

    **PC-C8 §6c-a — the model quotes text, the engine computes offsets.** The statement used to
    carry ``quote_start``/``quote_end``: the model counted characters in a message it was told not
    to retype, and any drift failed the call closed (12 such refusals in the 2026-08-01 acceptance
    run, all on long or bulleted turns). Counting is not classification. The model now copies the
    span it means; :func:`locate_quote` finds it by **exact substring search** over the captured
    answer the platform loaded, and the durable row keeps the same offsets + sha as before — only
    the authorship moved. There is deliberately no fuzzy matching anywhere on this path: the
    evidence lock's whole guarantee is "this exact span", and approximate location readmits
    paraphrase through the back door.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    route: InterviewRoute = Field(
        description=(
            "Which durable species this part of the answer is. `unmapped` is always legal and is "
            "the honest route when nothing else fits: it preserves the quote as evidence without "
            "asserting a fact."
        )
    )
    route_key: str = Field(
        description=(
            "Short stable label for what this statement is about (the field key, preference "
            "topic, or project decision). Recorded verbatim on the durable statement."
        )
    )
    quote: str = Field(
        description=(
            "The evidence span this statement rests on, copied exactly from the captured user "
            "message. Copy the span character-for-character out of the message — do not retype, "
            "tidy, re-punctuate, translate, or trim it. The platform searches the captured "
            "message for this exact text and records the offsets itself; a span that does not "
            "appear verbatim in that message is refused (`quote_not_found_verbatim`), and so is a "
            "blank one. There is no approximate matching: re-copy the span rather than "
            "paraphrasing it."
        )
    )
    occurrence: int = Field(
        default=1,
        ge=1,
        description=(
            "Which occurrence of `quote` in the captured user message to lock onto, 1-based; the "
            "default 1 means the first. The evidence bytes are identical wherever the span "
            "repeats, so leave this out unless you specifically mean a later one."
        ),
    )
    entity_id: EntityId | None = Field(
        default=None,
        description=(
            "Which entity a `claim` is about. Leave it out for a fact about the client itself — "
            "an `account` claim defaults to this project's own client entity, which the platform "
            "supplies. Fill it only to name a *different* entity, and then it must already exist "
            "in this workspace; an id that resolves to nothing is refused. A `contact` claim "
            "always needs it."
        ),
    )
    entity_type: EntityType | None = Field(
        default=None,
        description=(
            "`account` or `contact`; required on the `claim` route. A `contact` claim "
            "additionally requires `identity_binding` and `use_class`."
        ),
    )
    field_key: str | None = Field(
        default=None,
        description=(
            "Already-registered field this claim writes; required on the `claim` route. A novel "
            "field goes through `propose_field` instead of being invented here."
        ),
    )
    value: JsonValue | None = Field(
        default=None,
        description=(
            "The claim's value; required on the `claim` route, and always evidence-locked to "
            "`quote`. A **text** value must appear verbatim inside that quote — quote rather than "
            "summarize, and narrow the quote to the words that state the fact instead of "
            "rewording them. A **typed** value (true/false, a number, a list) cannot appear "
            "verbatim in prose, so it is checked instead by an entailment judge reading the quote "
            "alone: it is admitted only if those exact user words support it, and refused "
            "otherwise. Either way the quote must actually state the fact — a typed value is not "
            "a way around the evidence lock."
        ),
    )
    route_ref: str | None = Field(
        default=None,
        description=(
            "Reference to the existing `propose_field` / `propose_source` proposal; required on "
            "the `field_proposal` and `source_proposal` routes."
        ),
    )
    correction_of_statement_id: VolunteeredStatementId | None = Field(
        default=None,
        description=(
            "Prior interview statement this one corrects, when the user restates or contradicts "
            "something already routed. Recorded as durable correction lineage."
        ),
    )
    correction_of_claim_id: ClaimId | None = Field(
        default=None,
        description=(
            "Prior claim this claim supersedes; refused unless that claim is in this workspace "
            "with the same entity and the same field key."
        ),
    )
    memory_type: MemoryType | None = Field(
        default=None,
        description=(
            "`preference` or `behavioral_learning`; required on the `memory` route. Memory is "
            "advisory and never becomes fact."
        ),
    )
    memory_scope_type: MemoryScopeType | None = Field(
        default=None,
        description=(
            "Scope level the memory attaches to; required on the `memory` route. Pick the "
            "narrowest scope the preference actually holds for."
        ),
    )
    memory_scope_id: str | None = Field(
        default=None,
        description=(
            "Identifier of that scope (product, project, or account id) when the memory scope is "
            "not workspace-wide."
        ),
    )
    identity_binding: IdentityBinding | None = Field(
        default=None,
        description=(
            "How strongly this personal claim is bound to that exact person; required, with "
            "`use_class`, on every `contact` claim."
        ),
    )
    use_class: UseClass | None = Field(
        default=None,
        description=(
            "Permitted use class of this personal claim; required, with `identity_binding`, on "
            "every `contact` claim. A true fact can still be unusable for outreach."
        ),
    )

    @model_validator(mode="after")
    def _route_shape(self) -> InterviewStatement:
        # PC-C8 §8 (B1 layer 2): `entity_id` is no longer *required* on the claim route. An
        # `account` claim with no entity is engine-defaulted to the caller's trusted
        # `client_entity_id` in `route_interview_answer` — the same authority the constitution
        # serves — so the model neither needs the id nor gets to invent one. A `contact` claim
        # still names its entity, because there is no trusted default for a person.
        if self.route is InterviewRoute.CLAIM and (
            self.entity_type is None or self.field_key is None or self.value is None
        ):
            raise ValueError("claim route requires entity_type, field_key, and value")
        if (
            self.route is InterviewRoute.CLAIM
            and self.entity_type is EntityType.CONTACT
            and self.entity_id is None
        ):
            raise ValueError("contact claim route requires entity_id")
        if self.route is InterviewRoute.MEMORY and (
            self.memory_type is None or self.memory_scope_type is None
        ):
            raise ValueError("memory route requires memory_type and memory_scope_type")
        if (
            self.route
            in {
                InterviewRoute.FIELD_PROPOSAL,
                InterviewRoute.SOURCE_PROPOSAL,
            }
            and not self.route_ref
        ):
            raise ValueError("proposal routes require the C2 proposal reference")
        if self.entity_type is EntityType.CONTACT and (
            self.identity_binding is None or self.use_class is None
        ):
            raise ValueError("contact interview claims require identity_binding and use_class")
        return self


class InterviewClaimEntityRefused(ValueError):
    """A claim-route statement named an entity this workspace does not have (PC-C8 §8, B1).

    The behaviour this replaces accepted *any* well-formed UUID and silently wrote the claim at
    ``source_tier=3`` because it was not the client entity — so a hallucinated id became a durable,
    lower-trust claim about an entity that does not exist, and the only signal was a tier the model
    never saw. Fail-closed instead: an unresolvable entity is refused with a reason code the
    governed tool surfaces, and tiering becomes an explicit consequence of a *verified* identity
    rather than a fallback for an unverified one.
    """

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class InterviewEvidenceRefused(ValueError):
    """A statement's evidence did not hold up, so nothing about it may be written (PC-C8 §6c).

    Typed for the same reason :class:`InterviewClaimEntityRefused` is: the governed tool turns
    ``reason_code`` into a model-visible :class:`PreconditionFailure` the model can actually act on,
    instead of a bare ``ValueError`` whose only repair advice is its own prose. Every code here is
    a *repairable* condition — re-copy the span, name the occurrence, narrow the quote — which is
    why the failure is loud rather than a silent downgrade.
    """

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


#: The model quoted text that is not in the captured message (or asked for an occurrence that is
#: not there). The single repair is always the same: copy the span exactly from the message.
QUOTE_NOT_FOUND = "quote_not_found_verbatim"
#: A blank / whitespace-only quote proves nothing; it was refused before §6c too.
QUOTE_EMPTY = "interview_quote_empty"
#: A text value that is not inside its own quote (the byte-substring rule, unchanged since C4).
VALUE_NOT_ENTAILED = "claim_value_not_entailed"
#: A typed value arrived with no judge wired, so nothing can vouch for it. Refusing is *today's*
#: behaviour preserved, never a regression: before §6c-b a typed value could not pass the
#: substring rule at all.
VALUE_JUDGE_UNAVAILABLE = "claim_value_judge_unavailable"


class ClaimEntailment(BaseModel):
    """One judge's answer to "do these exact user words support this typed value?"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supported: bool
    #: The judge's own label (``supported`` / ``partial`` / ``unsupported`` / ``contradicted``), or
    #: ``unavailable`` when the judge could not be reached. Carried so the refusal can tell the
    #: model *which* of those two very different things happened.
    verdict: str
    score: float = 0.0


class ClaimEntailmentJudge(Protocol):
    """The seam a typed interview value is admitted through (PC-C8 §6c-b).

    Declared here and implemented at the ``api`` composition root over the shipped M9.3
    faithfulness judge — the same inversion :class:`~clue_projections.stage0.
    StatementEvidenceReader` uses, and for the same reason: ``clue_research.stage0`` may not import
    ``clue_research.verification`` (the milestone-independence contract), and a second entailment
    mechanism written here would be exactly the duplication the substrate forbids.

    Unwired is a legal state and means **refuse** — a typed value with nothing to vouch for it is
    not written.
    """

    async def entails(
        self,
        *,
        workspace_id: str,
        entity_id: EntityId,
        field_key: str,
        value: JsonValue,
        quote: str,
    ) -> ClaimEntailment: ...


def locate_quote(answer: str, *, quote: str, occurrence: int = 1) -> tuple[int, int]:
    """Find ``quote`` verbatim in ``answer`` and return its ``(start, end)`` character offsets.

    Exact substring search, **character domain** — the same decoded string ``record_statement``
    hashes and the same domain ``resolve_statement_quotes`` slices in, so an astral-plane emoji
    earlier in the message shifts nothing (a byte-domain search would silently misalign every
    following span). ``occurrence`` counts non-overlapping matches from the start, so the count in
    a not-found message agrees with :meth:`str.count`.

    Not found is a refusal, never a nearest match: fuzzy location would make the evidence lock mean
    "something like this span", which is the paraphrase this whole layer exists to refuse.
    """

    if not quote.strip():
        raise InterviewEvidenceRefused(
            reason_code=QUOTE_EMPTY,
            message="the evidence quote is blank; quote the user's actual words",
        )
    if occurrence < 1:
        # `InterviewStatement.occurrence` is `ge=1`, so no model can reach this — but the function
        # is public, and falling through would report the honest-sounding lie "it appears only N
        # time(s), so occurrence 0 does not exist" about a span that is right there in the message.
        raise ValueError(f"occurrence must be 1-based; got {occurrence}")
    start = -1
    cursor = 0
    for _ in range(occurrence):
        start = answer.find(quote, cursor)
        if start < 0:
            break
        cursor = start + len(quote)
    if start < 0:
        total = answer.count(quote)
        detail = (
            f"it appears only {total} time(s) there, so occurrence {occurrence} does not exist"
            if total
            else "it does not appear in that message"
        )
        raise InterviewEvidenceRefused(
            reason_code=QUOTE_NOT_FOUND,
            message=(
                f"the quote {_clip(quote)} was not found in the captured user message: {detail}. "
                "Copy the span exactly from the message — character for character, no retyping, "
                "tidying, or re-punctuating."
            ),
        )
    return start, start + len(quote)


def _clip(text: str, *, limit: int = 60) -> str:
    """The offending span, short enough to keep a refusal message readable."""

    flat = " ".join(text.split())
    return repr(flat if len(flat) <= limit else f"{flat[:limit]}…")


@dataclass(frozen=True, slots=True)
class _PreparedStatement:
    """One statement whose evidence has been located and (for claims) vouched for, before any
    write happens. Validating every statement first is what makes a multi-statement turn
    all-or-nothing rather than partially durable."""

    classified: InterviewStatement
    quote: str
    quote_start: int
    quote_end: int
    entity_id: EntityId | None
    judged: bool


class InterviewRoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_ids: tuple[VolunteeredStatementId, ...]
    claim_refs: tuple[ClaimId, ...]
    memory_refs: tuple[str, ...]
    project_state_refs: tuple[str, ...]
    proposal_refs: tuple[str, ...]
    unmapped_statement_ids: tuple[VolunteeredStatementId, ...]
    client_kb_version: int | None = None
    product_kb_version: int | None = None


#: The client's own words, admitted because the value is literally inside the cited span.
SOURCE_CLIENT_INTERVIEW = "client_interview"
# ``SOURCE_CLIENT_INTERVIEW_JUDGED`` is imported from claimstore beside the authoritative A→(Q,A)
# mapping. Stage 0 re-exports it for compatibility, but does not own a duplicate discriminator.

_INTERVIEW_SOURCES = (SOURCE_CLIENT_INTERVIEW, SOURCE_CLIENT_INTERVIEW_JUDGED)


async def register_client_interview_source(conn: AsyncConnection) -> None:
    """Register both interview sources (registration, not enumeration — conventions §2)."""
    for source_key in _INTERVIEW_SOURCES:
        await register_source(
            conn,
            RegistrySourceManifest(
                manifest=SourceManifest(
                    source_key=source_key,
                    modality=Modality.CONVERSATION,
                    entity_scope=EntityScope.BOTH,
                    yields=("client", "account", "contact"),
                    tier=1,
                ),
                provider="client",
            ),
        )


async def route_interview_answer(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    onboarding_input_id: OnboardingInputId,
    artifact_key: str,
    answer: str,
    statements: tuple[InterviewStatement, ...],
    actor: str,
    client_entity_id: EntityId,
    product_id: str | None = None,
    project_id: str | None = None,
    memory_write: MemoryWriteSeam | None = None,
    run_id: RunId | None = None,
    entailment_judge: ClaimEntailmentJudge | None = None,
) -> InterviewRoutingResult:
    """Locate and vouch for every quote, then route without dropping unknown statements.

    Two passes on purpose (PC-C8 §6c): pass one locates each quote in the captured answer and, for
    a claim, resolves its entity and proves its value is entailed; pass two writes. A turn whose
    third statement is unquotable therefore records *nothing* rather than two durable statements
    and a refusal the model must reconcile.
    """
    if (
        any(item.route is InterviewRoute.PROJECT_STATE for item in statements)
        and project_id is None
    ):
        raise ValueError("project-state interview statements require project_id")
    await register_client_interview_source(conn)
    run = run_id or new_run_id()
    # FI-2 P2 (spec §3): the interview writes Client-KB-shaped stage-0 claims, which spec §3 places
    # outside every project's lens — so ``project_id`` stays NULL even though a project-state
    # statement puts one in scope. Registered in the caller's transaction, ahead of every claim the
    # routing pass writes; idempotent, so a resumed turn (same ``run_id``) re-registers harmlessly.
    await record_run_lineage(conn, run_id=run, workspace_id=workspace_id, kind="stage0")
    prepared = await judge_interview_values(
        await prepare_interview_statements(
            conn,
            workspace_id=workspace_id,
            answer=answer,
            statements=statements,
            client_entity_id=client_entity_id,
        ),
        workspace_id=workspace_id,
        entailment_judge=entailment_judge,
    )
    company_target: ClientKbWriteTarget | None = None
    product_target: ClientKbWriteTarget | None = None
    company_fields: set[str] = set()
    product_fields: set[str] = set()
    for item in prepared:
        classified = item.classified
        if (
            classified.route is not InterviewRoute.CLAIM
            or item.entity_id != client_entity_id
            or classified.field_key is None
            or not classified.field_key.startswith("client.")
        ):
            continue
        if classified.field_key in PRODUCT_KNOWLEDGE_FIELDS:
            if product_id is None:
                raise ValueError(
                    "product-scoped client claim requires a human-confirmed project product"
                )
            product_fields.add(classified.field_key)
        else:
            company_fields.add(classified.field_key)
    # A claim row is not a published Client-KB checkpoint. Allocate the append-only target before
    # writing any governed client claim, inside this same transaction, so a later production turn
    # either observes the complete version or nothing. The captured input is the stable replay
    # identity even for direct callers that do not supply a run id.
    if company_fields:
        company_target = await client_kb_write_target_for_materialization(
            conn,
            workspace_id=workspace_id,
            client_entity_id=client_entity_id,
            product_id=None,
            operation_key=f"interview:{onboarding_input_id}:company",
            require_derived_version=True,
        )
    if product_fields:
        assert product_id is not None
        product_target = await client_kb_write_target_for_materialization(
            conn,
            workspace_id=workspace_id,
            client_entity_id=client_entity_id,
            product_id=product_id,
            operation_key=f"interview:{onboarding_input_id}:product:{product_id}",
            require_derived_version=True,
        )
    statement_ids: list[VolunteeredStatementId] = []
    claim_refs: list[ClaimId] = []
    memory_refs: list[str] = []
    project_refs: list[str] = []
    proposal_refs: list[str] = []
    unmapped: list[VolunteeredStatementId] = []
    for item in prepared:
        classified = item.classified
        quote = item.quote
        route_ref = classified.route_ref
        entity_id = item.entity_id
        if classified.route is InterviewRoute.CLAIM:
            assert entity_id is not None
            claim_run_id = run
            if entity_id == client_entity_id and classified.field_key in product_fields:
                assert product_target is not None
                claim_run_id = product_target.run_id
            elif entity_id == client_entity_id and classified.field_key in company_fields:
                assert company_target is not None
                claim_run_id = company_target.run_id
            claim_id = await _write_claim(
                conn,
                classified=classified,
                entity_id=entity_id,
                quote=quote,
                workspace_id=workspace_id,
                client_entity_id=client_entity_id,
                product_id=product_id,
                artifact_key=artifact_key,
                onboarding_input_id=onboarding_input_id,
                run_id=claim_run_id,
                judged=item.judged,
            )
            route_ref = str(claim_id)
            claim_refs.append(claim_id)
        elif classified.route is InterviewRoute.MEMORY:
            if memory_write is None:
                raise ValueError("memory statement supplied without the MemoryWriteSeam")
            assert classified.memory_scope_type is not None
            assert classified.memory_type is not None
            outcome = await memory_write.submit(
                MemorySubmission(
                    workspace_id=workspace_id,
                    scope=ScopeRef(
                        scope_type=classified.memory_scope_type,
                        scope_id=classified.memory_scope_id,
                    ),
                    type=classified.memory_type,
                    trigger=f"stage0-interview:{onboarding_input_id}",
                    body=str(classified.value) if classified.value is not None else quote,
                    provenance_class=MemoryProvenanceClass.USER_STATED,
                    creating_quote=quote,
                )
            )
            if isinstance(outcome, MemoryAccepted):
                route_ref = outcome.memory_id
                memory_refs.append(outcome.memory_id)
            else:
                route_ref = outcome.outcome
        statement_id = await record_statement(
            conn,
            onboarding_input_id=onboarding_input_id,
            workspace_id=workspace_id,
            brand_id=brand_id,
            product_id=product_id,
            project_id=project_id,
            client_entity_id=client_entity_id,
            entity_id=entity_id,
            route_kind=StatementRoute(classified.route.value),
            route_key=classified.route_key,
            route_ref=route_ref,
            quote=quote,
            quote_start=item.quote_start,
            quote_end=item.quote_end,
            correction_of_id=classified.correction_of_statement_id,
            created_by_actor=actor,
        )
        statement_ids.append(statement_id)
        if classified.route is InterviewRoute.PROJECT_STATE:
            project_refs.append(str(statement_id))
        elif classified.route in {
            InterviewRoute.FIELD_PROPOSAL,
            InterviewRoute.SOURCE_PROPOSAL,
        }:
            proposal_refs.append(route_ref or str(statement_id))
        elif classified.route is InterviewRoute.UNMAPPED:
            unmapped.append(statement_id)
    return InterviewRoutingResult(
        statement_ids=tuple(statement_ids),
        claim_refs=tuple(claim_refs),
        memory_refs=tuple(memory_refs),
        project_state_refs=tuple(project_refs),
        proposal_refs=tuple(proposal_refs),
        unmapped_statement_ids=tuple(unmapped),
        client_kb_version=(None if company_target is None else company_target.version),
        product_kb_version=(None if product_target is None else product_target.version),
    )


async def prepare_interview_statements(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    answer: str,
    statements: tuple[InterviewStatement, ...],
    client_entity_id: EntityId,
) -> tuple[_PreparedStatement, ...]:
    """Locate every statement's quote and resolve every claim's entity — writing nothing.

    The **DB half** of validation, kept separate from :func:`judge_interview_values` so the caller
    can release its connection before the judge's (multi-second, synchronous-gateway) call rather
    than holding a transaction open across it — the same discipline the M9.3 judge itself follows.

    Public because the governed tool runs it in ``preconditions`` too, so a refusal reaches the
    model as typed, repairable feedback instead of an exception from mid-write. The engine still
    runs it independently (this pair *is* the engine's pass one), so the guarantee never depends on
    the precondition having been called.
    """

    prepared: list[_PreparedStatement] = []
    for classified in statements:
        start, end = locate_quote(answer, quote=classified.quote, occurrence=classified.occurrence)
        entity_id = classified.entity_id
        if classified.route is InterviewRoute.CLAIM:
            entity_id = await resolve_claim_entity(
                conn,
                classified=classified,
                workspace_id=workspace_id,
                client_entity_id=client_entity_id,
            )
        prepared.append(
            _PreparedStatement(
                classified=classified,
                quote=answer[start:end],
                quote_start=start,
                quote_end=end,
                entity_id=entity_id,
                judged=False,
            )
        )
    return tuple(prepared)


async def judge_interview_values(
    prepared: tuple[_PreparedStatement, ...],
    *,
    workspace_id: str,
    entailment_judge: ClaimEntailmentJudge | None = None,
) -> tuple[_PreparedStatement, ...]:
    """Prove every claim value is entailed by its own quote; mark the ones the judge admitted.

    Holds no connection. Run twice per turn by design (precondition then engine) and costs one
    judgment either way: the port's implementation caches on the *content* of the question, so the
    engine's re-ask is a cache hit rather than a second LLM call.
    """

    checked: list[_PreparedStatement] = []
    for item in prepared:
        if item.classified.route is not InterviewRoute.CLAIM:
            checked.append(item)
            continue
        assert item.entity_id is not None
        assert item.classified.field_key is not None
        judged = await check_claim_value_entailment(
            workspace_id=workspace_id,
            field_key=item.classified.field_key,
            value=item.classified.value,
            quote=item.quote,
            entity_id=item.entity_id,
            entailment_judge=entailment_judge,
        )
        checked.append(replace(item, judged=judged))
    return tuple(checked)


def is_judged_value(value: JsonValue) -> bool:
    """Whether this claim value is admitted by the judge rather than by the substring rule.

    **The discrimination is the JSON type of the value as it will be stored in ``value_json``, and
    nothing else.** A JSON *string* is text the client can have said, so it keeps the pre-§6c rule
    byte-for-byte: it must appear inside its own quote. Every other JSON type — ``true``/``false``,
    a number, a list, an object, ``null`` — is a *rendering* of what the client said (``True``,
    ``['SOAP', 'APSO', 'H&P']``), and no rendering is ever a substring of English prose, which is
    why the acceptance run refused eight true, well-quoted facts. Those go to the judge.

    Note the honest consequence: ``"true"`` (the string) is byte-checked and ``true`` (the boolean)
    is judged. That is correct — they are different values, and the model chooses which it means.
    """

    return not isinstance(value, str)


async def check_claim_value_entailment(
    *,
    workspace_id: str,
    field_key: str,
    value: JsonValue,
    quote: str,
    entity_id: EntityId,
    entailment_judge: ClaimEntailmentJudge | None,
) -> bool:
    """Prove any interview-derived value against its exact quote.

    This is the one evidence-admission rule shared by direct claim routing and post-promotion
    dynamic-field materialization. It returns whether the typed-value judge, rather than the text
    substring rule, admitted the value.
    """
    if not is_judged_value(value):
        # Unchanged since C4, deliberately byte-for-byte: a text value must be inside its quote.
        rendered = str(value)
        if rendered.casefold() not in quote.casefold():
            raise InterviewEvidenceRefused(
                reason_code=VALUE_NOT_ENTAILED,
                message=(
                    "claim value is not textually entailed by the exact interview quote; quote "
                    "the words that state the fact, or send the fact as a typed value"
                ),
            )
        return False
    if entailment_judge is None:
        # R0 ruling (ARV2-R0-foundations-plan Part 3C fix 1): no judge composed (verification off)
        # means a typed value is admitted UNJUDGED, exactly like the substring path admits strings.
        # The claim is born UNVERIFIED, which is the durable record that no judge ran. Refusing
        # here was the kill-switch inversion: turning verification off bricked every typed
        # Client-KB fact, so the interview had to ask the user for everything in their own words.
        return False
    entailment = await entailment_judge.entails(
        workspace_id=workspace_id,
        entity_id=entity_id,
        field_key=field_key,
        value=value,
        quote=quote,
    )
    if entailment.supported:
        return True
    if entailment.verdict == "unavailable":
        raise InterviewEvidenceRefused(
            reason_code=VALUE_JUDGE_UNAVAILABLE,
            message=(
                "the entailment judge could not be reached, so this typed claim value cannot be "
                "admitted; nothing was written — try again, or route the statement as `unmapped`"
            ),
        )
    raise InterviewEvidenceRefused(
        reason_code=VALUE_NOT_ENTAILED,
        message=(
            f"the entailment judge read the quote alone and returned {entailment.verdict!r} for "
            "this typed claim value: those exact user words do not support it. Quote the sentence "
            "that actually states the fact, correct the value, or route the statement as "
            "`unmapped`"
        ),
    )


async def resolve_claim_entity(
    conn: AsyncConnection,
    *,
    classified: InterviewStatement,
    workspace_id: str,
    client_entity_id: EntityId,
) -> EntityId:
    """Decide which entity a claim-route statement is about (PC-C8 §8, B1 layer 2).

    Three rules, all fail-closed:

    * **Engine default.** An ``account`` claim with no ``entity_id`` is about this project's own
      client account — the id the caller's trusted ``client_entity_id`` already carries, sourced
      from the constitution. The model never has to know, quote, or invent it.
    * **Existence check.** Any id that *is* supplied must resolve to a live entity of the declared
      type in this workspace. The old behaviour accepted any UUID and expressed its doubt as a
      silent tier-3 downgrade; an id naming nothing is now refused outright, and the tier below is
      an explicit statement about a *verified* entity.
    * **Canonical only.** A merged-away entity (``merged_into`` set) is refused, not silently
      followed. ``get_account``/``get_contact`` deliberately do not chase the pointer (that is
      ``surviving_id``'s job), so accepting the loser would write a **durable** claim keyed to a
      row identity resolution has already retired — a worse form of the read-side hazard the M9.4
      backlog records, because the claim outlives the read. Redirecting silently is the tempting
      alternative and is wrong here for the same reason the existence check is: this function's
      contract is "a live entity", and quietly changing which entity a client's own words are
      attached to is not a repair the caller asked for. The refusal names the survivor so the
      caller can re-route deliberately.
    """

    entity_type = classified.entity_type
    assert entity_type is not None
    entity_id = classified.entity_id
    if entity_id is None:
        if entity_type is not EntityType.ACCOUNT:
            # Defence in depth, not a live path: `InterviewStatement._route_shape` already refuses
            # a contact claim with no entity, and both callers construct the model first. It stays
            # because this function is public and the invariant is its own, not the model's.
            raise InterviewClaimEntityRefused(
                reason_code="interview_entity_required",
                message="a contact claim must name the contact it is about",
            )
        entity_id = client_entity_id
    if entity_type is EntityType.ACCOUNT:
        account = await get_account(conn, entity_id)
        found = account is not None and account.workspace_id == workspace_id
        merged_into = account.merged_into if account is not None else None
    else:
        contact = await get_contact(conn, entity_id)
        found = contact is not None and contact.workspace_id == workspace_id
        merged_into = contact.merged_into if contact is not None else None
    if not found:
        raise InterviewClaimEntityRefused(
            reason_code="interview_entity_not_found",
            message=(
                f"claim names {entity_type.value} {entity_id}, which does not exist in this "
                "workspace"
            ),
        )
    if merged_into is not None:
        raise InterviewClaimEntityRefused(
            reason_code="interview_entity_merged",
            message=(
                f"claim names {entity_type.value} {entity_id}, which was merged into "
                f"{merged_into}; use the surviving entity"
            ),
        )
    return entity_id


async def _write_claim(
    conn: AsyncConnection,
    *,
    classified: InterviewStatement,
    entity_id: EntityId,
    quote: str,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str | None,
    artifact_key: str,
    onboarding_input_id: OnboardingInputId,
    run_id: RunId,
    judged: bool = False,
) -> ClaimId:
    assert classified.entity_type is not None
    assert classified.field_key is not None
    # Both branches now describe an entity `resolve_claim_entity` proved exists here: tier 1 is
    # "the client stating a fact about itself", tier 3 is "the client stating a fact about some
    # other resolved entity". Neither is a fallback for an id nobody could resolve.
    source_tier = 1 if entity_id == client_entity_id else 3
    claim_product_id = product_id if classified.field_key in PRODUCT_KNOWLEDGE_FIELDS else None
    if classified.field_key in PRODUCT_KNOWLEDGE_FIELDS and claim_product_id is None:
        raise ValueError("product-scoped client claim requires a human-confirmed project product")
    claim_id = ClaimId(
        uuid5(
            NAMESPACE_URL,
            f"stage0-interview-claim:{onboarding_input_id}:{entity_id}:{classified.field_key}",
        )
    )
    prior_by_id = await claims_by_ids(
        conn,
        (claim_id,),
        scope=WorkspaceScope.private_for_workspace(workspace_id),
        include_superseded=True,
    )
    if claim_id in prior_by_id:
        return claim_id
    claim = Claim(
        id=claim_id,
        entity_id=entity_id,
        entity_type=classified.entity_type,
        field_key=classified.field_key,
        value_json=classified.value,
        source_url=f"interview://{onboarding_input_id}",
        # PC-C8 §6c-b: how this value earned entry stays on the claim. Tier is untouched (it is a
        # statement about *whose* entity this is — 1.4's rule); only the method distinction is new.
        #
        # CORROBORATION-INDEPENDENCE INVARIANT — read before touching either side.
        # `verification.independent_source_count` treats two claims as ONE source when they share a
        # `source_url` host or a `source_key`. Two turns of one conversation have different
        # `interview://<onboarding_input_id>` hosts, so `source_key` is the ONLY thing stopping the
        # client's own repetition from counting as independent corroboration of itself. Splitting
        # that key in two therefore looks like it re-opens exactly that hole — and it does not,
        # for one reason and one reason only: **the two species can never land in the same value
        # group.** Independence is counted *within* a group of claims whose values agree, and a
        # `client_interview` claim's value is a JSON string by construction
        # (`is_judged_value` sends every non-string to the judge) while a
        # `client_interview_judged` claim's value is never a string — and `values_agree` never
        # equates across JSON types under any `equality_mode`.
        #
        # That is a coupling between three files, so it breaks silently if any one of them moves:
        # if `is_judged_value` ever admits a string, or `values_agree` ever equates `"true"` with
        # `true` (the `semantic` mode is the plausible route), two claims from ONE conversation
        # start counting as two independent sources and the interview self-corroborates. Pinned by
        # `tests/stage0/test_c8_evidence_ergonomics.py::
        # test_one_conversation_is_one_source_however_its_values_earned_entry`.
        source_key=(SOURCE_CLIENT_INTERVIEW_JUDGED if judged else SOURCE_CLIENT_INTERVIEW),
        artifact_key=artifact_key,
        source_tier=source_tier,
        extraction_method=ExtractionMethod.HUMAN,
        evidence_span=quote,
        confidence=1.0,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        identity_binding=classified.identity_binding,
        use_class=classified.use_class,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=workspace_id,
        product_id=claim_product_id,
    )
    if classified.correction_of_claim_id is None:
        return await insert_claim(conn, claim)
    prior = await claims_by_ids(
        conn,
        (classified.correction_of_claim_id,),
        scope=WorkspaceScope.private_for_workspace(workspace_id),
        include_superseded=True,
    )
    old = prior.get(classified.correction_of_claim_id)
    if old is None or old.entity_id != entity_id or old.field_key != classified.field_key:
        raise ValueError("correction claim does not match this workspace, entity, and field")
    return await supersede_claim(conn, classified.correction_of_claim_id, claim)


__all__ = [
    "QUOTE_EMPTY",
    "QUOTE_NOT_FOUND",
    "SOURCE_CLIENT_INTERVIEW",
    "SOURCE_CLIENT_INTERVIEW_JUDGED",
    "VALUE_JUDGE_UNAVAILABLE",
    "VALUE_NOT_ENTAILED",
    "ClaimEntailment",
    "ClaimEntailmentJudge",
    "InterviewClaimEntityRefused",
    "InterviewEvidenceRefused",
    "InterviewRoute",
    "InterviewRoutingResult",
    "InterviewStatement",
    "check_claim_value_entailment",
    "is_judged_value",
    "judge_interview_values",
    "locate_quote",
    "prepare_interview_statements",
    "register_client_interview_source",
    "resolve_claim_entity",
    "route_interview_answer",
]
