"""M12.1 — the positioning step: account claims × client knowledge → per-persona value narrative.

This is the synthesis the whole subsystem exists to produce (Output 4; overview §1/§3, substrate
§8): for a high-tier account, join its **verified** account picture (operational pain, strategic
moves, the ``account.resonance.*`` emotional register) with the client's capabilities from the
Client Knowledge Base, and emit — *per ``(account, persona)``* — the grounded argument for why the
client matters and which angle to take. The non-negotiable discipline (substrate §0/§8, the
prototype's lesson): each narrative line is **itself a claim-with-provenance**, not a free-text
dossier, so it is verified by the same machinery as every other claim (the M9.3 faithfulness
judge) and never promoted unless its evidence entails it.

:class:`Positioner` is built like the M9.3 judge (the established pattern for an LLM step with
durable output): injected :class:`~clue_research.core.gateway.LLMGateway`, the
:class:`~clue_research.core.retrieval.ClientKnowledgeRetriever` (M5 seam), the
:class:`~clue_research.narrative.seams.CommitteeReader` (M8/M10 seam), the
:class:`~clue_research.core.verification.FaithfulnessJudge` (M9.3), a resolved
:class:`~clue_research.narrative.policy.PositioningPolicy`, and a connection factory. Every
concrete dependency is injected at the ``api`` composition root — ``narrative`` imports no sibling
worker.

``position()`` is the graph node, keyed on ``(account_entity_id, icp_spec_version)``. For each
committee persona it:

1. gathers the persona-relevant **verified** account ``current_values`` (the merge already
   excludes unverified tier-4 claims — ``require_verified_tier4`` — so the account evidence is
   verified by construction);
2. keeps only **use-cleared** facet hooks (``is_outreach_promotable`` — strong identity-binding
   AND the M10 use gate cleared it; a weak/disallowed hook never reaches the prompt — M12.1 AC5);
3. requires grounding on **both** sides (≥1 account-evidence id AND ≥1 client-knowledge id) or
   emits a coverage gap rather than a fabricated argument (M12.1 AC1/AC6);
4. synthesizes one grounded argument via the gateway, writes it as a tier-4 ``llm_synthesis``
   ``account.value_narrative`` claim (stamped ``TENANT_PRIVATE``) + its ``claim_support`` row,
   then runs the faithfulness judge — which promotes a grounded argument to ``verified`` and
   leaves an ungrounded one un-promoted (M12.1 AC2).

Re-running on the same ``(account, icp, persona)`` **supersedes** the prior narrative rather than
duplicating it (append-only + supersede; M12.1 AC7).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from time import perf_counter

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    TenantScope,
    claims_for,
    current_values,
    insert_claim,
    supersede_claim,
)
from clue_research.core import (
    Claim,
    ClaimId,
    CostCents,
    CurrentValue,
    EntityId,
    ExtractionMethod,
    FaithfulnessJudge,
    LLMGateway,
    Persona,
    ResearchMode,
    RunId,
    account_claim,
    is_outreach_promotable,
)
from clue_research.core.retrieval import ClientKnowledgeChunk, ClientKnowledgeRetriever
from clue_research.db import transaction
from clue_research.identity import stamp_reuse
from clue_research.narrative.fields import VALUE_NARRATIVE
from clue_research.narrative.policy import DEFAULT_POSITIONING_POLICY, PositioningPolicy
from clue_research.narrative.prompts import (
    AccountFact,
    angle_for,
    build_positioning_messages,
    fact_to_text,
    parse_positioning_response,
)
from clue_research.narrative.reuse import NARRATIVE_REUSE_POLICY
from clue_research.narrative.seams import CommitteeContact, CommitteeReader
from clue_research.narrative.support import write_claim_support
from clue_research.obs import (
    ATTR_CLIENT_ID,
    ATTR_COST_CENTS,
    ATTR_ENTITY_ID,
    ATTR_MODEL,
    MetricSink,
    apply_attributes,
    get_logger,
    get_metric_sink,
    traced_step,
)

_log = get_logger(__name__)

# The narrative is *about* the account (mode M2). A synthesized narrative has no single web URL;
# this stable synthetic URI satisfies the llm_synthesis source_url invariant — the real two-sided
# provenance lives in ``claim_support`` (account_evidence_ids × client_knowledge_ids).
_POSITIONING_SOURCE_URL = "clue://narrative/positioning"
_SYNTHESIS_TIER = 4
# The synthesis prior confidence carried on the claim; the faithfulness judge's score is the real
# accuracy signal (the merge admits a tier-4 narrative only once the judge marks it verified).
_SYNTHESIS_CONFIDENCE = 0.7

# M12-local span / metric names (the shared sink/tracer accept any string; defined here so narrative
# stays self-contained and never edits obs). Short attribute values (an enum string) pass redaction;
# entity/client ids are STANDARD_ATTRIBUTES (allowlisted).
SPAN_NARRATIVE_POSITION = "narrative.position"
ATTR_PERSONA = "narrative.persona"
ATTR_N_NARRATIVES = "narrative.n_narratives"
ATTR_N_COVERAGE_GAPS = "narrative.n_coverage_gaps"
METRIC_NARRATIVES_PRODUCED = "research.narrative.produced"
METRIC_NARRATIVE_COVERAGE_GAP = "research.narrative.coverage_gap"

# Why a persona produced no narrative (returned for observability; the durable signal is simply the
# absence of a narrative claim for a committee persona, which M12.2 reads as low coverage).
COVERAGE_NO_ACCOUNT_EVIDENCE = "no_account_evidence"
COVERAGE_NO_CLIENT_KNOWLEDGE = "no_client_knowledge"
COVERAGE_UNGROUNDED_SYNTHESIS = "ungrounded_synthesis"


class CoverageGap(BaseModel):
    """A ``(account, persona)`` for which no narrative could be grounded — emitted instead of a
    fabricated argument (M12.1 AC6; conventions §5: empty-flagged is correct).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    persona: Persona
    reason: str


class ValueNarrativeRef(BaseModel):
    """A produced narrative, by reference (substrate §5b — return claim ids, not blobs). Carries the
    two-sided support ids (mirrored into ``claim_support``) and the judge verdict for
    observability; the authoritative promotion state is ``claim.verification_status`` in the store
    (judge-driven).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    persona: Persona
    angle_label: str
    account_evidence_ids: tuple[ClaimId, ...]
    client_knowledge_ids: tuple[str, ...]
    judge_verdict: str | None = None


class PositioningResult(BaseModel):
    """The positioning step's output for one ``(account, icp)``: produced narratives (by
    reference), the per-persona coverage gaps, and the synthesis+judge spend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    icp_spec_version: int
    narratives: tuple[ValueNarrativeRef, ...] = ()
    coverage_gaps: tuple[CoverageGap, ...] = ()
    cost_cents: CostCents = Decimal(0)


def assemble_evidence_span(
    account_facts: list[AccountFact], client_chunks: list[ClientKnowledgeChunk], *, max_chars: int
) -> str:
    """Assemble the ``evidence_span`` the judge scores the argument against: the account facts
    (value + their own spans) ⊕ the client-knowledge passages, capped at ``max_chars``. This is the
    grounding the argument must be entailed by — so an ungrounded argument fails the judge."""
    parts: list[str] = []
    for fact in account_facts:
        parts.append(f"[{fact.field_key}] {fact.value_text}")
        if fact.evidence_span:
            parts.append(fact.evidence_span)
    parts.extend(chunk.chunk for chunk in client_chunks)
    return "\n".join(parts)[:max_chars]


class Positioner:
    """The M12.1 positioning step (the value-narrative graph node). Constructed with injected seams
    at the ``api`` composition root; per-client policy is loaded via
    :func:`~clue_research.narrative.policy.load_positioning_policy`.
    """

    def __init__(
        self,
        *,
        gateway: LLMGateway,
        retriever: ClientKnowledgeRetriever,
        committee_reader: CommitteeReader,
        judge: FaithfulnessJudge,
        policy: PositioningPolicy = DEFAULT_POSITIONING_POLICY,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]] = transaction,
        sink: MetricSink | None = None,
    ) -> None:
        self._gateway = gateway
        self._retriever = retriever
        self._committee_reader = committee_reader
        self._judge = judge
        self._policy = policy
        self._conn_factory = conn_factory
        self._sink = sink

    async def position(
        self,
        account_entity_id: EntityId,
        *,
        icp_spec_version: int,
        client_id: str,
        client_entity_id: EntityId,
        run_id: RunId,
        icp_key: str | None = None,
        kb_version: int | None = None,
    ) -> PositioningResult:
        """Produce the per-persona value narrative for one ``(account, icp)``.

        ``client_id`` is the tenant the narrative binds to (TENANT_PRIVATE); ``client_entity_id``
        is the client's resolved account entity, for Client-Knowledge retrieval. The merge reads
        are tenant-scoped to ``client_id`` (public account facts ∪ this tenant's private
        resonance).

        ``icp_key`` disambiguates *which* ICP segment this narrative is for: an ICP is
        ``(client_id, icp_key, version)`` and ``version`` restarts at 1 per ``icp_key`` (D5), so two
        segments can share ``icp_spec_version=1``. When provided it is stamped into the claim's
        ``value_json`` and keys supersession on ``(persona, icp_key, icp_version)`` — so segment B's
        re-synthesis never clobbers segment A's narrative at the same version. ``None`` preserves
        the
        legacy version-only keying (a single-segment account)."""
        policy = self._policy
        scope = TenantScope.for_tenant(client_id)
        with traced_step(
            SPAN_NARRATIVE_POSITION,
            **{
                ATTR_ENTITY_ID: str(account_entity_id),
                ATTR_CLIENT_ID: client_id,
                ATTR_MODEL: policy.narrative_model,
            },
        ) as span:
            # 1) Read the verified account picture once (the merge excludes unverified
            #    tier-4 claims).
            all_fields = tuple(
                sorted({f for fields in policy.field_relevance.values() for f in fields})
            )
            async with self._conn_factory() as conn:
                merged = await current_values(conn, [account_entity_id], all_fields, scope=scope)
            account_facts_by_field = {
                field_key: cv
                for (entity_id, field_key), cv in merged.items()
                if entity_id == account_entity_id
            }

            # 2) Read the use-cleared committee (the M8/M10 seam; production impl injected at api).
            committee = await self._committee_reader.committee_for(
                account_entity_id=account_entity_id, tenant_id=client_id
            )

            narratives: list[ValueNarrativeRef] = []
            gaps: list[CoverageGap] = []
            total_cost = Decimal(0)

            for member in committee:
                ref, gap, cost = await self._position_persona(
                    member,
                    account_entity_id=account_entity_id,
                    account_facts_by_field=account_facts_by_field,
                    icp_spec_version=icp_spec_version,
                    icp_key=icp_key,
                    client_id=client_id,
                    client_entity_id=client_entity_id,
                    run_id=run_id,
                    kb_version=kb_version,
                    scope=scope,
                )
                total_cost += cost
                if ref is not None:
                    narratives.append(ref)
                if gap is not None:
                    gaps.append(gap)

            apply_attributes(
                span,
                {
                    ATTR_N_NARRATIVES: len(narratives),
                    ATTR_N_COVERAGE_GAPS: len(gaps),
                    ATTR_COST_CENTS: total_cost,
                },
            )
            return PositioningResult(
                account_entity_id=account_entity_id,
                icp_spec_version=icp_spec_version,
                narratives=tuple(narratives),
                coverage_gaps=tuple(gaps),
                cost_cents=total_cost,
            )

    async def _position_persona(
        self,
        member: CommitteeContact,
        *,
        account_entity_id: EntityId,
        account_facts_by_field: dict[str, CurrentValue],
        icp_spec_version: int,
        icp_key: str | None,
        client_id: str,
        client_entity_id: EntityId,
        run_id: RunId,
        kb_version: int | None,
        scope: TenantScope,
    ) -> tuple[ValueNarrativeRef | None, CoverageGap | None, CostCents]:
        """Synthesize (or coverage-gap) one persona's narrative. Returns ``(ref, gap, cost)`` —
        exactly one of ``ref``/``gap`` is set.
        """
        policy = self._policy
        persona = member.persona

        # (a) persona-relevant verified account evidence.
        account_facts: list[AccountFact] = []
        account_evidence_ids: list[ClaimId] = []
        for field_key in policy.fields_for(persona):
            cv = account_facts_by_field.get(field_key)
            if cv is None:
                continue
            account_facts.append(
                AccountFact(
                    field_key=field_key,
                    value_text=fact_to_text(field_key, cv.value_json),
                    evidence_span=cv.provenance.evidence_span,
                )
            )
            account_evidence_ids.append(cv.provenance.claim_id)
        if len(account_evidence_ids) < policy.min_account_evidence:
            self._emit_gap(persona, COVERAGE_NO_ACCOUNT_EVIDENCE)
            return (
                None,
                CoverageGap(persona=persona, reason=COVERAGE_NO_ACCOUNT_EVIDENCE),
                Decimal(0),
            )

        # (b) use-cleared facet hooks only (weak/disallowed never reach the prompt — AC5).
        usable_facet_texts = [
            fact_to_text(hook.claim.field_key, hook.claim.value_json)
            for hook in member.facets
            if hook.decision is not None and is_outreach_promotable(hook.claim, hook.decision)
        ]

        # (c) client capabilities relevant to the account's pains (the M5 retrieval seam).
        query = " ".join(fact.value_text for fact in account_facts)
        chunks = list(
            await self._retriever.retrieve(
                client_entity_id=client_entity_id,
                client_id=client_id,
                query=query,
                kb_version=kb_version,
                limit=policy.retrieval_limit,
            )
        )
        if len(chunks) < policy.min_client_chunks:
            self._emit_gap(persona, COVERAGE_NO_CLIENT_KNOWLEDGE)
            return (
                None,
                CoverageGap(persona=persona, reason=COVERAGE_NO_CLIENT_KNOWLEDGE),
                Decimal(0),
            )

        # (d) synthesize one grounded argument (no DB connection held during the gateway call).
        messages = build_positioning_messages(
            persona=persona,
            account_facts=account_facts,
            client_chunks=[chunk.chunk for chunk in chunks],
            usable_facet_hooks=usable_facet_texts,
            prompt_version=policy.prompt_version,
        )
        start = perf_counter()
        completion = self._gateway.complete(model=policy.narrative_model, messages=messages)
        _latency_ms = (perf_counter() - start) * 1000.0
        cost = completion.cost_cents
        parsed = parse_positioning_response(completion.text)
        if not parsed.argument:
            self._emit_gap(persona, COVERAGE_UNGROUNDED_SYNTHESIS)
            return None, CoverageGap(persona=persona, reason=COVERAGE_UNGROUNDED_SYNTHESIS), cost

        # (e) build the tier-4 narrative claim (stamped TENANT_PRIVATE) + its claim_support row.
        angle = angle_for(persona)
        value_json: dict[str, JsonValue] = {
            "persona": persona.value,
            "argument": parsed.argument,
            "angle_label": angle.angle_label,
            "icp_spec_version": icp_spec_version,
        }
        if icp_key is not None:
            # The ICP segment (D5: version restarts per icp_key) — stamped so M12.2 reads the right
            # segment's narrative and supersession keys on (persona, icp_key, icp_version).
            value_json["icp_key"] = icp_key
        evidence_span = assemble_evidence_span(
            account_facts, chunks, max_chars=policy.max_evidence_chars
        )
        claim = account_claim(
            entity_id=account_entity_id,  # an ACCOUNT claim; persona lives in value_json
            field_key=VALUE_NARRATIVE,
            value_json=value_json,
            source_tier=_SYNTHESIS_TIER,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            confidence=_SYNTHESIS_CONFIDENCE,
            run_id=run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url=_POSITIONING_SOURCE_URL,
            evidence_span=evidence_span,
            cost_cents=cost,
        )
        claim = stamp_reuse(claim, tenant_id=client_id, policy=NARRATIVE_REUSE_POLICY)

        client_knowledge_ids = [chunk.client_knowledge_id for chunk in chunks]
        async with self._conn_factory() as conn:
            new_id = await self._write_narrative(
                conn,
                claim,
                persona=persona,
                icp_spec_version=icp_spec_version,
                icp_key=icp_key,
                scope=scope,
            )
            await write_claim_support(
                conn,
                new_id,
                account_evidence_ids=account_evidence_ids,
                client_knowledge_ids=client_knowledge_ids,
            )

        # (f) faithfulness gate: promotes a grounded argument, leaves an ungrounded one un-promoted.
        verdict = await self._judge.judge(claim)
        self._emit_produced(persona)
        ref = ValueNarrativeRef(
            claim_id=new_id,
            persona=persona,
            angle_label=angle.angle_label,
            account_evidence_ids=tuple(account_evidence_ids),
            client_knowledge_ids=tuple(client_knowledge_ids),
            judge_verdict=verdict.verdict.value,
        )
        return ref, None, cost

    async def _write_narrative(
        self,
        conn: AsyncConnection,
        claim: Claim,
        *,
        persona: Persona,
        icp_spec_version: int,
        icp_key: str | None,
        scope: TenantScope,
    ) -> ClaimId:
        """Insert the narrative claim, superseding any prior live narrative for the same ``(account,
        persona, icp_key, icp)`` (append-only + supersede; M12.1 AC7 — re-run never duplicates).
        When
        ``icp_key`` is set, segment B never supersedes segment A's narrative at the same version
        (D5).
        """
        live = await self._live_for_persona(
            conn,
            claim.entity_id,
            persona=persona,
            icp_spec_version=icp_spec_version,
            icp_key=icp_key,
            scope=scope,
        )
        if not live:
            return await insert_claim(conn, claim)
        if len(live) > 1:
            _log.warning(
                "more than one live value_narrative for (account=%s, persona=%s, icp_key=%s, "
                "icp=%s); superseding the most recent (the others are a pre-existing anomaly)",
                claim.entity_id,
                persona.value,
                icp_key,
                icp_spec_version,
            )
        return await supersede_claim(conn, live[0].id, claim)

    async def _live_for_persona(
        self,
        conn: AsyncConnection,
        account_entity_id: EntityId,
        *,
        persona: Persona,
        icp_spec_version: int,
        icp_key: str | None,
        scope: TenantScope,
    ) -> list[Claim]:
        """The live ``account.value_narrative`` claims for this exact ``(account, persona, icp_key,
        icp)`` (claims_for returns non-superseded; ordered collected_at DESC so ``[0]`` is the most
        recent). ``icp_key=None`` matches on version only (legacy single-segment keying).
        """
        claims = await claims_for(conn, account_entity_id, VALUE_NARRATIVE, scope=scope)
        result: list[Claim] = []
        for claim in claims:
            value = claim.value_json
            if (
                isinstance(value, dict)
                and value.get("persona") == persona.value
                and value.get("icp_spec_version") == icp_spec_version
                and (icp_key is None or value.get("icp_key") == icp_key)
            ):
                result.append(claim)
        return result

    def _emit_gap(self, persona: Persona, reason: str) -> None:
        sink = self._sink or get_metric_sink()
        sink.add(METRIC_NARRATIVE_COVERAGE_GAP, 1, {"persona": persona.value, "reason": reason})

    def _emit_produced(self, persona: Persona) -> None:
        sink = self._sink or get_metric_sink()
        sink.add(METRIC_NARRATIVES_PRODUCED, 1, {"persona": persona.value})
