"""M12.1 (ENG-158) — the positioning step: account claims × client knowledge → value narrative.

Every §M12.1 acceptance criterion has a dedicated test. The pure machinery (prompt assembly,
response parsing, the field-def / policy / reuse shapes) runs in ``make check`` with no DB; the
``Positioner`` behaviour is exercised against a live Postgres (skips without one, like the M9
suites) because it reads the merge view, writes ``account.value_narrative`` claims +
``claim_support``, and drives the real M9.3 faithfulness judge (which writes the verdict + the
claim's verification status).

The two LLM calls are deterministic **fake gateways**: one returns a canned positioning argument,
the other (inside the real judge) returns a canned verdict — so "ungrounded → not promoted",
"persona-distinct angles", "use-cleared hooks only" and "thin KB → coverage gap" are assertable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    ClaimId,
    Completion,
    EntityId,
    ExtractionMethod,
    IdentityBinding,
    Message,
    Persona,
    ResearchMode,
    ReuseScope,
    UseClass,
    UseDecision,
    UseReason,
    VerificationStatus,
    account_claim,
    contact_claim,
    new_entity_id,
    new_run_id,
)
from clue_core.retrieval import ClientKnowledgeChunk
from clue_research.claimstore import (
    PUBLIC_ONLY,
    WorkspaceScope,
    claims_for,
    insert_claim,
    record_verification,
)
from clue_research.identity import (
    DEFAULT_REUSE_POLICY,
    classify_reuse_scope,
    insert_account_entity,
    stamp_reuse,
)
from clue_research.narrative import (
    ACCOUNT_OPERATIONAL_PAIN,
    ACCOUNT_RESONANCE_CULTURE,
    ACCOUNT_STRATEGIC_MOVES,
    DEFAULT_POSITIONING_POLICY,
    NARRATIVE_PACK,
    NARRATIVE_REUSE_POLICY,
    PROMPT_VERSION,
    VALUE_NARRATIVE,
    AccountFact,
    CommitteeContact,
    FacetHook,
    InMemoryClientKnowledgeRetriever,
    InMemoryCommitteeReader,
    Positioner,
    PositioningPolicy,
    angle_for,
    assemble_evidence_span,
    build_positioning_messages,
    fact_to_text,
    load_positioning_policy,
    parse_positioning_response,
    rank_by_query_overlap,
    read_claim_support,
)
from clue_research.narrative.policy import _parse_field_relevance
from clue_research.narrative.positioner import (
    COVERAGE_NO_ACCOUNT_EVIDENCE,
    COVERAGE_NO_CLIENT_KNOWLEDGE,
)
from clue_research.verification import FaithfulnessJudgeImpl

from .conftest import rollback_conn, run_async

# --- a deterministic fake gateway (records calls; returns canned JSON) -------


class FakeGateway:
    """A deterministic ``LLMGateway`` returning one canned response and recording every call (so a
    test can assert which model was called and what the prompt contained)."""

    def __init__(self, response_text: str, *, cost_cents: Decimal = Decimal("0.3")) -> None:
        self._response = response_text
        self._cost = cost_cents
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, list(messages)))
        return Completion(
            model=model, text=self._response, cost_cents=self._cost, finish_reason="stop"
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError("the positioner never embeds")


_ARGUMENT = '{"argument": "Acme can cut its cloud spend with our autoscaling platform."}'
_EMPTY_ARGUMENT = '{"argument": ""}'
_SUPPORTED = '{"verdict": "supported", "score": 0.92, "rationale": "the span supports it"}'
_UNSUPPORTED = '{"verdict": "unsupported", "score": 0.05, "rationale": "the span does not"}'


# === pure unit (no DB) ======================================================


def test_field_def_is_tenant_private_tier4_deep() -> None:
    field = NARRATIVE_PACK[0].field_def
    assert field.field_key == VALUE_NARRATIVE == "account.value_narrative"
    assert field.reuse_scope is ReuseScope.TENANT_PRIVATE  # never public (cross-tenant leak guard)
    assert field.tier_plan == ()  # produced by the positioner, not the M4 waterfall
    assert field.pass_kind.value == "deep"


def test_reuse_policy_classifies_value_narrative_private() -> None:
    # the default policy would classify account.* public; the narrative policy adds the prefix.
    assert (
        classify_reuse_scope(
            VALUE_NARRATIVE, ExtractionMethod.LLM_SYNTHESIS, 4, DEFAULT_REUSE_POLICY
        )
        is ReuseScope.PUBLIC_FOOTPRINT
    )
    assert (
        classify_reuse_scope(
            VALUE_NARRATIVE, ExtractionMethod.LLM_SYNTHESIS, 4, NARRATIVE_REUSE_POLICY
        )
        is ReuseScope.TENANT_PRIVATE
    )


def test_default_field_relevance_gives_personas_distinct_evidence() -> None:
    econ = DEFAULT_POSITIONING_POLICY.fields_for(Persona.ECONOMIC_BUYER)
    tech = DEFAULT_POSITIONING_POLICY.fields_for(Persona.TECHNICAL_EVALUATOR)
    assert set(econ) != set(tech)  # AC3 foundation: different lenses read different evidence
    assert (
        angle_for(Persona.ECONOMIC_BUYER).angle_label
        != angle_for(Persona.TECHNICAL_EVALUATOR).angle_label
    )


def test_all_personas_have_distinct_angle_labels() -> None:
    labels = {angle_for(p).angle_label for p in Persona}
    assert len(labels) == len(Persona)


def test_positioning_policy_defaults() -> None:
    assert DEFAULT_POSITIONING_POLICY.narrative_model  # non-empty gateway model id
    assert DEFAULT_POSITIONING_POLICY.prompt_version
    assert DEFAULT_POSITIONING_POLICY.min_account_evidence >= 1
    assert DEFAULT_POSITIONING_POLICY.min_client_chunks >= 1


def test_parse_positioning_response() -> None:
    assert parse_positioning_response(_ARGUMENT).argument.startswith("Acme can cut")
    fenced = 'Sure:\n```json\n{"argument": "x"}\n```\ndone'
    assert parse_positioning_response(fenced).argument == "x"
    # an empty / unparseable / non-string argument never becomes a stored narrative.
    assert parse_positioning_response(_EMPTY_ARGUMENT).argument == ""
    assert parse_positioning_response("not json at all").argument == ""
    assert parse_positioning_response('{"argument": 5}').argument == ""


def test_build_messages_is_grounded_and_fenced() -> None:
    facts = [AccountFact(field_key=ACCOUNT_OPERATIONAL_PAIN, value_text="manual scaling toil")]
    messages = build_positioning_messages(
        persona=Persona.ECONOMIC_BUYER,
        account_facts=facts,
        client_chunks=["our platform autoscales"],
        usable_facet_hooks=[],
    )
    assert messages[0].role.value == "system" and "GROUNDING" in messages[0].content
    user = messages[1].content
    assert "economic_buyer" in user
    assert "manual scaling toil" in user and "our platform autoscales" in user
    assert "untrusted data" in user.lower()  # the injection-fencing instruction


def test_build_messages_unknown_version_raises() -> None:
    with pytest.raises(ValueError, match="unknown positioning prompt_version"):
        build_positioning_messages(
            persona=Persona.CHAMPION,
            account_facts=[],
            client_chunks=[],
            usable_facet_hooks=[],
            prompt_version="v999",
        )


def test_assemble_evidence_span_caps() -> None:
    facts = [AccountFact(field_key="account.x", value_text="A" * 100, evidence_span="B" * 100)]
    chunks = [ClientKnowledgeChunk(client_knowledge_id="c1", chunk="C" * 100)]
    span = assemble_evidence_span(facts, chunks, max_chars=50)
    assert len(span) == 50


def test_fact_to_text() -> None:
    assert fact_to_text("account.x", "plain string") == "plain string"
    assert fact_to_text("account.x", {"a": 1}) == '{"a":1}'


def test_rank_by_query_overlap() -> None:
    chunks = (
        ClientKnowledgeChunk(client_knowledge_id="a", chunk="autoscaling reduces cloud cost"),
        ClientKnowledgeChunk(client_knowledge_id="b", chunk="unrelated marketing copy"),
        ClientKnowledgeChunk(client_knowledge_id="c", chunk="cloud cost optimization platform"),
    )
    ranked = rank_by_query_overlap(chunks, "cloud cost", limit=10)
    # highest token overlap first ("cloud cost" matches a and c, not b)
    assert [r.client_knowledge_id for r in ranked[:2]] == ["a", "c"]
    assert len(rank_by_query_overlap(chunks, "cloud", limit=1)) == 1  # honours limit
    assert rank_by_query_overlap(chunks, "", limit=10) == chunks  # empty query → stable order


# === DB-gated behaviour =====================================================


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


def _judge(conn: AsyncConnection, verdict_text: str = _SUPPORTED) -> FaithfulnessJudgeImpl:
    return FaithfulnessJudgeImpl(gateway=FakeGateway(verdict_text), conn_factory=_factory(conn))


async def _account(conn: AsyncConnection) -> EntityId:
    return await insert_account_entity(
        conn, canonical_name="Acme", primary_domain="acme.com", status=AccountStatus.ACTIVE
    )


async def _write_fact(
    conn: AsyncConnection,
    account: EntityId,
    field_key: str,
    value: str,
    *,
    workspace_id: str,
    run_id: object,
) -> ClaimId:
    """Write a verified tier-4 account claim (so the merge view surfaces it as the account side)."""
    claim = account_claim(
        entity_id=account,
        field_key=field_key,
        value_json=value,
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=run_id,  # type: ignore[arg-type]
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://src.local/x",
        evidence_span=f"evidence that {value}",
    )
    claim = stamp_reuse(claim, workspace_id=workspace_id, policy=DEFAULT_REUSE_POLICY)
    cid = await insert_claim(conn, claim)
    await record_verification(conn, cid, status=VerificationStatus.VERIFIED)
    return cid


def _member(persona: Persona, *, facets: tuple[FacetHook, ...] = ()) -> CommitteeContact:
    return CommitteeContact(
        contact_entity_id=new_entity_id(),
        persona=persona,
        role_on_committee=persona.value,
        facets=facets,
    )


def _positioner(
    conn: AsyncConnection,
    *,
    retriever: InMemoryClientKnowledgeRetriever,
    committee: InMemoryCommitteeReader,
    argument: str = _ARGUMENT,
    verdict: str = _SUPPORTED,
    policy: PositioningPolicy = DEFAULT_POSITIONING_POLICY,
) -> tuple[Positioner, FakeGateway]:
    synth = FakeGateway(argument)
    positioner = Positioner(
        gateway=synth,
        retriever=retriever,
        committee_reader=committee,
        judge=_judge(conn, verdict),
        conn_factory=_factory(conn),
        policy=policy,
    )
    return positioner, synth


def _retriever(
    client_entity_id: EntityId, chunks: tuple[str, ...]
) -> InMemoryClientKnowledgeRetriever:
    items = tuple(
        ClientKnowledgeChunk(client_knowledge_id=f"ck{i}", chunk=c) for i, c in enumerate(chunks)
    )
    return InMemoryClientKnowledgeRetriever({client_entity_id: items})


@pytest.mark.usefixtures("require_narrative_db")
def test_produces_one_verified_narrative_per_persona() -> None:
    """AC1/AC2: ≥1 claim per persona, each tier-4 llm_synthesis with an argument, an evidence_span,
    and ≥1 id in BOTH account_evidence_ids and client_knowledge_ids; the judge promotes it."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            await _write_fact(
                conn,
                account,
                ACCOUNT_STRATEGIC_MOVES,
                "expanding to EU",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("our platform autoscales clusters",))
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, _ = _positioner(conn, retriever=retriever, committee=committee)

            result = await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )

            assert len(result.narratives) == 1
            ref = result.narratives[0]
            assert ref.persona is Persona.ECONOMIC_BUYER
            assert ref.account_evidence_ids and ref.client_knowledge_ids  # both-sided (AC1)
            assert ref.judge_verdict == "supported"

            claims = await claims_for(
                conn, account, VALUE_NARRATIVE, scope=WorkspaceScope.for_workspace(workspace_id)
            )
            assert len(claims) == 1
            claim = claims[0]
            assert claim.source_tier == 4
            assert claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
            assert claim.evidence_span  # non-empty (AC1)
            assert claim.value_json["argument"].startswith("Acme can cut")  # type: ignore[index]
            assert claim.verification_status is VerificationStatus.VERIFIED  # judge promoted (AC2)

            support = await read_claim_support(conn, ref.claim_id)
            assert support is not None
            assert set(support.account_evidence_ids) == set(ref.account_evidence_ids)
            assert set(support.client_knowledge_ids) == set(ref.client_knowledge_ids)

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_ungrounded_argument_not_promoted() -> None:
    """AC2: an argument whose evidence does not entail it (judge unsupported) is not promoted."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("unrelated client capability",))
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, _ = _positioner(
                conn, retriever=retriever, committee=committee, verdict=_UNSUPPORTED
            )

            result = await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            ref = result.narratives[0]
            assert ref.judge_verdict == "unsupported"
            claim = (
                await claims_for(
                    conn, account, VALUE_NARRATIVE, scope=WorkspaceScope.for_workspace(workspace_id)
                )
            )[0]
            assert claim.verification_status is VerificationStatus.REJECTED  # never verified

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_personas_argue_from_different_evidence() -> None:
    """AC3: economic-buyer and technical-evaluator narratives differ in angle + cited evidence."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            pain = await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            moves = await _write_fact(
                conn,
                account,
                ACCOUNT_STRATEGIC_MOVES,
                "expanding to EU",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            culture = await _write_fact(
                conn,
                account,
                ACCOUNT_RESONANCE_CULTURE,
                "engineering-led culture",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("our platform autoscales",))
            committee = InMemoryCommitteeReader(
                {account: (_member(Persona.ECONOMIC_BUYER), _member(Persona.TECHNICAL_EVALUATOR))}
            )
            positioner, _ = _positioner(conn, retriever=retriever, committee=committee)

            result = await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            by_persona = {r.persona: r for r in result.narratives}
            econ, tech = by_persona[Persona.ECONOMIC_BUYER], by_persona[Persona.TECHNICAL_EVALUATOR]
            assert econ.angle_label != tech.angle_label
            # econ reads pain+moves, tech reads culture+moves → different account evidence sets
            assert set(econ.account_evidence_ids) != set(tech.account_evidence_ids)
            assert pain in econ.account_evidence_ids and culture in tech.account_evidence_ids
            assert moves in econ.account_evidence_ids and moves in tech.account_evidence_ids

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_referential_integrity_of_supporting_ids() -> None:
    """AC4: every account_evidence_id resolves to a real verified account claim; every
    client_knowledge_id resolves to a real KB entry (the retriever's id set)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            # write >1 account fact (the econ persona reads pain + moves) so the per-id check is
            # genuinely multi-field, not a single-element coincidence.
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            await _write_fact(
                conn,
                account,
                ACCOUNT_STRATEGIC_MOVES,
                "expanding to EU",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("cap one", "cap two"))
            kb_ids = {"ck0", "ck1"}
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, _ = _positioner(conn, retriever=retriever, committee=committee)

            result = await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            ref = result.narratives[0]
            assert len(ref.account_evidence_ids) >= 2  # multi-field set, not a single coincidence
            # every account_evidence_id resolves, field-agnostically, to a real live account claim.
            scope = WorkspaceScope.for_workspace(workspace_id)
            real_verified: dict[ClaimId, str] = {}
            for fk in (ACCOUNT_OPERATIONAL_PAIN, ACCOUNT_STRATEGIC_MOVES):
                for c in await claims_for(conn, account, fk, scope=scope):
                    real_verified[c.id] = c.field_key
            for cid in ref.account_evidence_ids:
                assert cid in real_verified  # resolves to a real, live account claim (AC4)
            # every client_knowledge_id resolves to a real KB entry (the retriever's id set).
            assert set(ref.client_knowledge_ids).issubset(kb_ids)

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_only_use_cleared_facets_reach_the_argument() -> None:
    """AC5: a weak-binding facet and a `sensitive` (use-disallowed) facet never reach the prompt;
    a strong + use-allowed facet does."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            contact = new_entity_id()
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )

            def _facet(value: str, binding: IdentityBinding, use_class: UseClass) -> object:
                return contact_claim(
                    entity_id=contact,
                    field_key="contact.facet.recent_post",
                    value_json=value,
                    source_tier=4,
                    extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                    confidence=0.8,
                    run_id=run_id,
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    source_url="https://src.local/post",
                    evidence_span=value,
                    identity_binding=binding,
                    use_class=use_class,
                )

            def _decision(claim: object, usable: bool, reason: UseReason) -> UseDecision:
                return UseDecision(
                    claim_id=claim.id,  # type: ignore[attr-defined]
                    usable_for_outreach=usable,
                    reason=reason,
                    policy_version=1,
                )

            good = _facet(
                "wrote a blog on kubernetes", IdentityBinding.STRONG, UseClass.PROFESSIONAL_PUBLIC
            )
            weak = _facet(
                "plays in a metal band",
                IdentityBinding.WEAK,
                UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
            )
            sens = _facet("attends synagogue weekly", IdentityBinding.STRONG, UseClass.SENSITIVE)
            facets = (
                FacetHook(claim=good, decision=_decision(good, True, UseReason.ALLOWED)),
                FacetHook(claim=weak, decision=_decision(weak, True, UseReason.ALLOWED)),
                FacetHook(claim=sens, decision=_decision(sens, False, UseReason.SENSITIVE_LOCKED)),
            )
            retriever = _retriever(client_entity, ("our platform autoscales",))
            committee = InMemoryCommitteeReader(
                {account: (_member(Persona.CHAMPION, facets=facets),)}
            )
            positioner, synth = _positioner(conn, retriever=retriever, committee=committee)

            await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            prompt = "\n".join(m.content for _, msgs in synth.calls for m in msgs)
            assert "kubernetes" in prompt  # strong + allowed hook reaches the prompt
            assert "metal band" not in prompt  # weak binding excluded (AC5)
            assert "synagogue" not in prompt  # sensitive / use-disallowed excluded (AC5)

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_thin_kb_emits_coverage_gap_not_fabrication() -> None:
    """AC6: when the Client Knowledge Base cannot ground an argument, emit a coverage gap (no
    claim)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ())  # empty KB
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, synth = _positioner(conn, retriever=retriever, committee=committee)

            result = await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            assert result.narratives == ()
            assert len(result.coverage_gaps) == 1
            assert result.coverage_gaps[0].reason == COVERAGE_NO_CLIENT_KNOWLEDGE
            assert synth.calls == []  # no synthesis call (no fabrication)
            assert (
                await claims_for(
                    conn, account, VALUE_NARRATIVE, scope=WorkspaceScope.for_workspace(workspace_id)
                )
                == []
            )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_rerun_supersedes_not_duplicates() -> None:
    """AC7: re-running on the same (account, icp, persona) supersedes the prior narrative."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("our platform autoscales",))
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, _ = _positioner(conn, retriever=retriever, committee=committee)

            async def _position() -> None:
                await positioner.position(
                    account,
                    icp_spec_version=1,
                    workspace_id=workspace_id,
                    client_entity_id=client_entity,
                    run_id=run_id,
                )

            await _position()
            await _position()  # re-run: supersede, do not duplicate

            scope = WorkspaceScope.for_workspace(workspace_id)
            live = await claims_for(conn, account, VALUE_NARRATIVE, scope=scope)
            assert len(live) == 1  # one live narrative, not two (AC7)
            allc = await claims_for(
                conn, account, VALUE_NARRATIVE, include_superseded=True, scope=scope
            )
            assert len(allc) == 2  # the prior is retained, superseded (append-only)
            superseded = [c for c in allc if c.superseded_by is not None]
            assert len(superseded) == 1 and superseded[0].superseded_by == live[0].id

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_config_swap_changes_cited_evidence() -> None:
    """AC8: swapping the field-relevance map (config, not code) changes which evidence is cited."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            pain = await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            moves = await _write_fact(
                conn,
                account,
                ACCOUNT_STRATEGIC_MOVES,
                "expanding to EU",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("our platform autoscales",))
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})

            moves_only = DEFAULT_POSITIONING_POLICY.model_copy(
                update={"field_relevance": {Persona.ECONOMIC_BUYER: (ACCOUNT_STRATEGIC_MOVES,)}}
            )
            positioner, _ = _positioner(
                conn, retriever=retriever, committee=committee, policy=moves_only
            )
            result = await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            ref = result.narratives[0]
            assert moves in ref.account_evidence_ids
            assert pain not in ref.account_evidence_ids  # config pointed the lens away from pain

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_narrative_claim_is_tenant_private() -> None:
    """The written narrative is TENANT_PRIVATE: visible to its tenant, never to the public scope."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("our platform autoscales",))
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, _ = _positioner(conn, retriever=retriever, committee=committee)

            await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            tenant = await claims_for(
                conn, account, VALUE_NARRATIVE, scope=WorkspaceScope.for_workspace(workspace_id)
            )
            assert len(tenant) == 1
            assert tenant[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            assert tenant[0].workspace_id == workspace_id
            public = await claims_for(conn, account, VALUE_NARRATIVE, scope=PUBLIC_ONLY)
            assert public == []  # a client-tuned narrative never amortizes cross-tenant

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_no_account_evidence_emits_coverage_gap() -> None:
    """AC1/AC6 (account side): no verified account evidence → a coverage gap, never a fabrication —
    the symmetric counterpart of the thin-KB test, locking the min_account_evidence floor."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            # write NO persona-relevant account facts; the KB is non-empty so the gap is
            # unambiguously the account side.
            retriever = _retriever(client_entity, ("our platform autoscales",))
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, synth = _positioner(conn, retriever=retriever, committee=committee)

            result = await positioner.position(
                account,
                icp_spec_version=1,
                workspace_id=workspace_id,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            assert result.narratives == ()
            assert len(result.coverage_gaps) == 1
            assert result.coverage_gaps[0].reason == COVERAGE_NO_ACCOUNT_EVIDENCE
            assert synth.calls == []  # returns before synthesis — no fabrication
            assert (
                await claims_for(
                    conn, account, VALUE_NARRATIVE, scope=WorkspaceScope.for_workspace(workspace_id)
                )
                == []
            )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_multi_icp_produces_separate_claims() -> None:
    """D5 (multi-ICP): the same (account, persona) under two ICP versions yields two distinct live
    narratives — neither supersedes the other (the icp_spec_version half of the keying)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id, run_id = "tenant-a", new_run_id()
            account = await _account(conn)
            client_entity = new_entity_id()
            await _write_fact(
                conn,
                account,
                ACCOUNT_OPERATIONAL_PAIN,
                "manual scaling toil",
                workspace_id=workspace_id,
                run_id=run_id,
            )
            retriever = _retriever(client_entity, ("our platform autoscales",))
            committee = InMemoryCommitteeReader({account: (_member(Persona.ECONOMIC_BUYER),)})
            positioner, _ = _positioner(conn, retriever=retriever, committee=committee)

            for icp in (1, 2):
                await positioner.position(
                    account,
                    icp_spec_version=icp,
                    workspace_id=workspace_id,
                    client_entity_id=client_entity,
                    run_id=run_id,
                )
            scope = WorkspaceScope.for_workspace(workspace_id)
            live = await claims_for(conn, account, VALUE_NARRATIVE, scope=scope)
            assert len(live) == 2  # one per ICP — neither superseded the other (D5)
            assert {c.value_json["icp_spec_version"] for c in live} == {1, 2}  # type: ignore[index]
            assert all(c.superseded_by is None for c in live)

    run_async(_run())


async def _insert_positioning_policy(
    conn: AsyncConnection,
    *,
    policy_id: str,
    workspace_id: str | None,
    model: str,
    prompt_version: str = PROMPT_VERSION,
    version: int = 1,
    min_account_evidence: int = 1,
    retrieval_limit: int = 8,
    field_relevance: dict[str, list[str]] | None = None,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO positioning_policy
                (policy_id, workspace_id, narrative_model, prompt_version, min_account_evidence,
                 min_client_chunks, retrieval_limit, max_evidence_chars, field_relevance, version)
            VALUES (:pid, :cid, :model, :pv, :mae, 1, :rl, 4000, CAST(:fr AS jsonb), :ver)
            """
        ),
        {
            "pid": policy_id,
            "cid": workspace_id,
            "model": model,
            "pv": prompt_version,
            "mae": min_account_evidence,
            "rl": retrieval_limit,
            "fr": json.dumps(field_relevance or {}),
            "ver": version,
        },
    )


@pytest.mark.usefixtures("require_narrative_db")
def test_load_positioning_policy_precedence_and_degrade() -> None:
    """AC8 (the 'load from versioned config' half): the DB loader resolves per-client → global →
    default, wires every configurable field, and degrades a stale prompt_version fail-soft."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            # no rows → the built-in default
            assert (
                await load_positioning_policy(conn, workspace_id="acme")
                == DEFAULT_POSITIONING_POLICY
            )

            # a global row (workspace_id NULL) wins when there is no per-client row, and every
            # configurable knob round-trips (incl. min_account_evidence / retrieval_limit).
            await _insert_positioning_policy(
                conn,
                policy_id="g1",
                workspace_id=None,
                model="model/global",
                min_account_evidence=2,
                retrieval_limit=3,
                field_relevance={"economic_buyer": [ACCOUNT_STRATEGIC_MOVES]},
            )
            loaded = await load_positioning_policy(conn, workspace_id="acme")
            assert loaded.narrative_model == "model/global"
            assert loaded.min_account_evidence == 2 and loaded.retrieval_limit == 3
            assert loaded.fields_for(Persona.ECONOMIC_BUYER) == (ACCOUNT_STRATEGIC_MOVES,)

            # a per-client row beats the global (most-specific scope wins)
            await _insert_positioning_policy(
                conn, policy_id="c1", workspace_id="acme", model="model/acme"
            )
            assert (
                await load_positioning_policy(conn, workspace_id="acme")
            ).narrative_model == "model/acme"

            # a later version whose prompt_version is unregistered degrades to the default prompt
            # (fail-soft — a stale config row never raises per-account mid-run)
            await _insert_positioning_policy(
                conn,
                policy_id="c2",
                workspace_id="acme",
                model="model/acme2",
                prompt_version="vDOESNOTEXIST",
                version=2,
            )
            degraded = await load_positioning_policy(conn, workspace_id="acme")
            assert degraded.narrative_model == "model/acme2"
            assert degraded.prompt_version == DEFAULT_POSITIONING_POLICY.prompt_version

    run_async(_run())


def test_parse_field_relevance_is_fail_soft() -> None:
    # a decoded dict and a JSON string both parse to the typed map.
    parsed = _parse_field_relevance({"economic_buyer": [ACCOUNT_STRATEGIC_MOVES]})
    assert parsed[Persona.ECONOMIC_BUYER] == (ACCOUNT_STRATEGIC_MOVES,)
    as_str = _parse_field_relevance('{"champion": ["account.operational_pain"]}')
    assert as_str[Persona.CHAMPION] == ("account.operational_pain",)
    # an unknown persona key or a non-list value is skipped; nothing valid → the default map.
    fallback = _parse_field_relevance({"bogus": ["x"], "champion": "not-a-list"})
    assert Persona.ECONOMIC_BUYER in fallback  # degraded to DEFAULT_FIELD_RELEVANCE
    assert Persona.ECONOMIC_BUYER in _parse_field_relevance("not json at all")
