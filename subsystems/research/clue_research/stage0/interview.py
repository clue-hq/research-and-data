"""The client interview as a governed source and open-ended routing surface."""

from __future__ import annotations

from enum import StrEnum
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
from clue_research.claimstore import WorkspaceScope, claims_by_ids, insert_claim, supersede_claim
from clue_research.sources import RegistrySourceManifest, register_source
from clue_research.stage0.governed import StatementRoute, record_statement


class InterviewRoute(StrEnum):
    CLAIM = "claim"
    MEMORY = "memory"
    PROJECT_STATE = "project_state"
    FIELD_PROPOSAL = "field_proposal"
    SOURCE_PROPOSAL = "source_proposal"
    UNMAPPED = "unmapped"


class InterviewStatement(BaseModel):
    """One routed part of the captured answer: its species, its exact evidence quote offsets, and
    the fields that species requires. (One minimal-actor classification; C6 can later produce the
    same contract.)"""

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
    quote_start: int = Field(
        description=(
            "Start character offset of the evidence quote inside the captured user message the "
            "platform supplies as `answer` (0-based, inclusive; characters, not bytes). An "
            "offset past the end of that message, or a blank span, is refused."
        )
    )
    quote_end: int = Field(
        description=(
            "End character offset inside that captured user message (exclusive). The slice "
            "`answer[quote_start:quote_end]` is taken from the platform-loaded capture, so it "
            "must be the exact user words this statement rests on."
        )
    )
    entity_id: EntityId | None = Field(
        default=None,
        description=(
            "Entity this claim is about; required on the `claim` route. Use the supplied client "
            "entity id for facts about the client."
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
            "The claim's value; required on the `claim` route and refused unless it appears "
            "verbatim inside `answer[quote_start:quote_end]` — the slice of the captured user "
            "message the platform loads. Facts are evidence-locked to the user's exact words, so "
            "quote rather than summarize: narrow the offsets to the words that state the fact "
            "instead of rewording them."
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
        if self.route is InterviewRoute.CLAIM and (
            self.entity_id is None
            or self.entity_type is None
            or self.field_key is None
            or self.value is None
        ):
            raise ValueError("claim route requires entity_id, entity_type, field_key, and value")
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


class InterviewRoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_ids: tuple[VolunteeredStatementId, ...]
    claim_refs: tuple[ClaimId, ...]
    memory_refs: tuple[str, ...]
    project_state_refs: tuple[str, ...]
    proposal_refs: tuple[str, ...]
    unmapped_statement_ids: tuple[VolunteeredStatementId, ...]


async def register_client_interview_source(conn: AsyncConnection) -> None:
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key="client_interview",
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
) -> InterviewRoutingResult:
    """Validate exact quotes, then route without dropping unknown statements."""
    if (
        any(item.route is InterviewRoute.PROJECT_STATE for item in statements)
        and project_id is None
    ):
        raise ValueError("project-state interview statements require project_id")
    await register_client_interview_source(conn)
    run = run_id or new_run_id()
    statement_ids: list[VolunteeredStatementId] = []
    claim_refs: list[ClaimId] = []
    memory_refs: list[str] = []
    project_refs: list[str] = []
    proposal_refs: list[str] = []
    unmapped: list[VolunteeredStatementId] = []
    for classified in statements:
        quote = _exact_quote(answer, classified)
        route_ref = classified.route_ref
        if classified.route is InterviewRoute.CLAIM:
            claim_id = await _write_claim(
                conn,
                classified=classified,
                quote=quote,
                workspace_id=workspace_id,
                client_entity_id=client_entity_id,
                product_id=product_id,
                artifact_key=artifact_key,
                onboarding_input_id=onboarding_input_id,
                run_id=run,
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
            entity_id=classified.entity_id,
            route_kind=StatementRoute(classified.route.value),
            route_key=classified.route_key,
            route_ref=route_ref,
            quote=quote,
            quote_start=classified.quote_start,
            quote_end=classified.quote_end,
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
    )


def _exact_quote(answer: str, classified: InterviewStatement) -> str:
    if classified.quote_start < 0 or classified.quote_end > len(answer):
        raise ValueError("interview quote offsets fall outside the captured answer")
    quote = answer[classified.quote_start : classified.quote_end]
    if not quote.strip():
        raise ValueError("interview evidence quote must be non-empty")
    if classified.route is InterviewRoute.CLAIM:
        rendered = str(classified.value)
        if rendered.casefold() not in quote.casefold():
            raise ValueError("claim value is not textually entailed by the exact interview quote")
    return quote


async def _write_claim(
    conn: AsyncConnection,
    *,
    classified: InterviewStatement,
    quote: str,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str | None,
    artifact_key: str,
    onboarding_input_id: OnboardingInputId,
    run_id: RunId,
) -> ClaimId:
    assert classified.entity_id is not None
    assert classified.entity_type is not None
    assert classified.field_key is not None
    source_tier = 1 if classified.entity_id == client_entity_id else 3
    claim_product_id = product_id if classified.field_key.startswith("client.") else None
    if classified.field_key.startswith("client.") and claim_product_id is None:
        raise ValueError("product-scoped client claim requires a confirmed product")
    claim_id = ClaimId(
        uuid5(
            NAMESPACE_URL,
            f"stage0-interview-claim:{onboarding_input_id}:{classified.entity_id}:"
            f"{classified.field_key}",
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
        entity_id=classified.entity_id,
        entity_type=classified.entity_type,
        field_key=classified.field_key,
        value_json=classified.value,
        source_url=f"interview://{onboarding_input_id}",
        source_key="client_interview",
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
    if (
        old is None
        or old.entity_id != classified.entity_id
        or old.field_key != classified.field_key
    ):
        raise ValueError("correction claim does not match this workspace, entity, and field")
    return await supersede_claim(conn, classified.correction_of_claim_id, claim)


__all__ = [
    "InterviewRoute",
    "InterviewRoutingResult",
    "InterviewStatement",
    "register_client_interview_source",
    "route_interview_answer",
]
