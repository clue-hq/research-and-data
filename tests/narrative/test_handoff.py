"""M12.2 — the ``account_handoff`` assembler + provenance index.

Every §M12.2 acceptance criterion has a dedicated test. The pure machinery (the ``Score`` /
committee-filter / non-fit helpers) runs in ``make check`` with no DB; the ``HandoffAssembler``
behaviour is exercised against a live Postgres (skips without one, like the M9 / M12.1 suites)
because it reads the merge view, the ``account.scoring.*`` claims, the committee seam, the verified
``account.value_narrative`` claims + their ``claim_support``, and the ``faithfulness_verdict``
citation, then resolves every claim id to its provenance.

The end-to-end test drives the **real** M12.1 ``Positioner`` (so the narrative claim is genuinely
judge-promoted and carries an ``answering_model`` verdict) before assembling — proving the
M12.1→M9.3→M12.2 chain; the focused tests write claims directly for precise control of one axis.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    insert_claim,
    record_verification,
    supersede_claim,
)
from clue_research.core import (
    AccountStatus,
    ClaimId,
    CommitteeMember,
    Completion,
    EntityId,
    ExtractionMethod,
    IdentityBinding,
    Message,
    Persona,
    ProfileClaimView,
    ResearchMode,
    UseClass,
    UseDecision,
    UseReason,
    VerificationStatus,
    account_claim,
    contact_claim,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_research.core.retrieval import ClientKnowledgeChunk
from clue_research.identity import DEFAULT_REUSE_POLICY, insert_account_entity, stamp_reuse
from clue_research.narrative import (
    FIT_FIELD,
    INTENT_FIELD,
    NARRATIVE_REUSE_POLICY,
    VALUE_NARRATIVE,
    CommitteeContact,
    HandoffAssembler,
    HandoffAssemblyError,
    HandoffCommitteeMember,
    InMemoryClientKnowledgeRetriever,
    InMemoryCommitteeReader,
    InMemoryHandoffCommitteeReader,
    Positioner,
    read_handoff,
    write_claim_support,
    write_handoff,
)
from clue_research.narrative.handoff import (
    _facet_outreach_eligible,
    _filter_committee_member,
    _score_from_value_json,
)
from clue_research.verification import FaithfulnessJudgeImpl

from .conftest import rollback_conn, run_async

_CLIENT = "client-acme"
_AT = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
_AT2 = datetime(2026, 6, 24, 13, 0, tzinfo=UTC)


class FakeGateway:
    """A deterministic ``LLMGateway`` returning one canned response (used for the positioner's
    synthesis call and the judge's verdict call in the end-to-end test)."""

    def __init__(self, response_text: str, *, cost_cents: Decimal = Decimal("0.3")) -> None:
        self._response = response_text
        self.calls: list[tuple[str, list[Message]]] = []
        self._cost = cost_cents

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, list(messages)))
        return Completion(
            model=model, text=self._response, cost_cents=self._cost, finish_reason="stop"
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError


_ARGUMENT = '{"argument": "Acme can cut its cloud spend with our autoscaling platform."}'
_SUPPORTED = '{"verdict": "supported", "score": 0.92, "rationale": "the span supports it"}'


# === pure unit (no DB) ======================================================


def _score_payload(value: float, evidence: list[str], *, icp_version: int, non_fit: bool) -> dict:
    return {
        "value": value,
        "components": [
            {"name": "firmographic", "weight": 1.0, "value": value, "evidence_claim_ids": evidence}
        ],
        "rubric_version": 1,
        "non_fit_flag": non_fit,
        "fit_floor": 0.3,
        "icp_key": "default",
        "icp_version": icp_version,
    }


def test_score_from_value_json_strips_extras_and_reads_non_fit() -> None:
    cid = str(new_claim_id())
    score, non_fit = _score_from_value_json(_score_payload(0.8, [cid], icp_version=1, non_fit=True))
    assert score.value == pytest.approx(0.8)
    assert len(score.components) == 1
    assert str(score.components[0].evidence_claim_ids[0]) == cid  # coerced back to ClaimId
    assert non_fit is True
    # the intent payload carries no non_fit_flag → defaults False.
    intent_payload = {"value": 0.5, "components": [], "rubric_version": 1, "icp_version": 1}
    _, intent_non_fit = _score_from_value_json(intent_payload)
    assert intent_non_fit is False


def test_facet_outreach_eligibility_is_two_axis() -> None:
    strong = ProfileClaimView(claim_id=new_claim_id(), value_json="x", source_tier=4)
    strong = strong.model_copy(update={"identity_binding": IdentityBinding.STRONG})
    weak = strong.model_copy(update={"identity_binding": IdentityBinding.WEAK})
    assert _facet_outreach_eligible(strong, True) is True
    assert _facet_outreach_eligible(strong, False) is False  # use-disallowed
    assert _facet_outreach_eligible(weak, True) is False  # weak binding


def test_filter_committee_member_drops_weak_and_disallowed_facets() -> None:
    role = ProfileClaimView(claim_id=new_claim_id(), value_json="economic_buyer", source_tier=2)
    kept = ProfileClaimView(
        claim_id=new_claim_id(),
        value_json="ex-Stripe",
        source_tier=4,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    weak = ProfileClaimView(
        claim_id=new_claim_id(),
        value_json="maybe",
        source_tier=4,
        identity_binding=IdentityBinding.WEAK,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    sensitive = ProfileClaimView(
        claim_id=new_claim_id(),
        value_json="health",
        source_tier=4,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.SENSITIVE,
    )
    member = CommitteeMember(
        contact_entity_id=new_entity_id(),
        persona=Persona.ECONOMIC_BUYER,
        role_on_committee="economic_buyer",
        profile_claims=(role, kept, weak, sensitive),
    )
    hm = HandoffCommitteeMember(
        member=member,
        use_decisions={
            kept.claim_id: UseDecision(
                claim_id=kept.claim_id,
                usable_for_outreach=True,
                reason=UseReason.ALLOWED,
                policy_version=1,
            ),
            weak.claim_id: UseDecision(
                claim_id=weak.claim_id,
                usable_for_outreach=True,
                reason=UseReason.ALLOWED,
                policy_version=1,
            ),
            sensitive.claim_id: UseDecision(
                claim_id=sensitive.claim_id,
                usable_for_outreach=False,
                reason=UseReason.SENSITIVE_LOCKED,
                policy_version=1,
            ),
        },
    )
    filtered = _filter_committee_member(hm)
    kept_ids = {pv.claim_id for pv in filtered.profile_claims}
    assert kept_ids == {
        role.claim_id,
        kept.claim_id,
    }  # role (identifying) + the strong+allowed facet
    assert weak.claim_id not in kept_ids and sensitive.claim_id not in kept_ids


# === DB-backed helpers ======================================================


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


def _assembler() -> HandoffAssembler:
    return HandoffAssembler(committee_reader=InMemoryHandoffCommitteeReader())


async def _account(conn: AsyncConnection, *, name: str = "Acme") -> EntityId:
    return await insert_account_entity(
        conn, canonical_name=name, primary_domain=f"{name.lower()}.com", status=AccountStatus.ACTIVE
    )


async def _profile_fact(
    conn: AsyncConnection,
    account: EntityId,
    field_key: str,
    value: object,
    *,
    tier: int = 4,
    verified: bool = True,
) -> ClaimId:
    claim = account_claim(
        entity_id=account,
        field_key=field_key,
        value_json=value,
        source_tier=tier,
        extraction_method=(
            ExtractionMethod.LLM_SYNTHESIS if tier == 4 else ExtractionMethod.SCRAPE
        ),
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://src.local/x",
        evidence_span=f"evidence that {value}" if tier == 4 else None,
    )
    claim = stamp_reuse(claim, tenant_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
    cid = await insert_claim(conn, claim)
    if verified:
        await record_verification(conn, cid, status=VerificationStatus.VERIFIED)
    return cid


async def _write_score(
    conn: AsyncConnection,
    account: EntityId,
    field_key: str,
    payload: dict,
) -> ClaimId:
    claim = account_claim(
        entity_id=account,
        field_key=field_key,
        value_json=payload,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
    )
    claim = stamp_reuse(claim, tenant_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
    return await insert_claim(conn, claim)


async def _write_narrative(
    conn: AsyncConnection,
    account: EntityId,
    persona: Persona,
    *,
    icp_version: int,
    account_evidence_ids: list[ClaimId],
    client_knowledge_ids: list[str],
    verified: bool = True,
) -> ClaimId:
    claim = account_claim(
        entity_id=account,
        field_key=VALUE_NARRATIVE,
        value_json={
            "persona": persona.value,
            "argument": f"why we matter to {persona.value}",
            "angle_label": "roi",
            "icp_spec_version": icp_version,
        },
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.7,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="clue://narrative/positioning",
        evidence_span="the grounding span",
    )
    claim = stamp_reuse(claim, tenant_id=_CLIENT, policy=NARRATIVE_REUSE_POLICY)
    cid = await insert_claim(conn, claim)
    await write_claim_support(
        conn,
        cid,
        account_evidence_ids=account_evidence_ids,
        client_knowledge_ids=client_knowledge_ids,
    )
    if verified:
        await record_verification(conn, cid, status=VerificationStatus.VERIFIED)
    return cid


async def _real_committee_claim(conn: AsyncConnection, contact: EntityId, value: str) -> ClaimId:
    """A real, governed contact-facet claim (so the handoff committee's profile_claim ids resolve in
    the provenance index)."""
    claim = contact_claim(
        entity_id=contact,
        field_key="contact.facet.recent_post",
        value_json=value,
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        source_url="https://src.local/c",
        evidence_span=f"the span for {value}",
    )
    claim = stamp_reuse(claim, tenant_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
    return await insert_claim(conn, claim)


def _committee(
    members: tuple[HandoffCommitteeMember, ...], account: EntityId
) -> InMemoryHandoffCommitteeReader:
    return InMemoryHandoffCommitteeReader({account: members})


# === DB-backed acceptance criteria ==========================================


@pytest.mark.usefixtures("require_narrative_db")
def test_assembles_all_outputs_end_to_end() -> None:
    """AC1/AC3: a fully-profiled account assembles all five sections — decomposed scores (with
    per-component evidence), verified profile claims, the governed committee, the judge-promoted
    value narrative, and a fully-resolvable provenance index — with the scope stamps set. Drives the
    REAL positioner + judge so the narrative is genuinely promoted and citable."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            client_entity = await _account(conn, name="ClientCo")
            run_id = new_run_id()
            # verified account profile facts (Output 2) + a signal claim the score cites.
            pain = await _profile_fact(conn, account, "account.operational_pain", "cloud overspend")
            await _profile_fact(conn, account, "account.strategic_moves", "expanding to EU")
            signal = await _profile_fact(conn, account, "core.employee_count", 500, tier=1)
            # decomposed scores citing the signal.
            await _write_score(
                conn,
                account,
                FIT_FIELD,
                _score_payload(0.82, [str(signal)], icp_version=1, non_fit=False),
            )
            await _write_score(
                conn,
                account,
                INTENT_FIELD,
                {
                    "value": 0.6,
                    "components": [],
                    "rubric_version": 1,
                    "icp_key": "default",
                    "icp_version": 1,
                },
            )
            # the REAL positioner produces a judge-promoted narrative for the economic buyer.
            positioner = Positioner(
                gateway=FakeGateway(_ARGUMENT),
                retriever=InMemoryClientKnowledgeRetriever(
                    {
                        client_entity: (
                            ClientKnowledgeChunk(
                                client_knowledge_id="ck0", chunk="autoscaling cuts cloud spend"
                            ),
                        )
                    }
                ),
                committee_reader=InMemoryCommitteeReader(
                    {
                        account: (
                            CommitteeContact(
                                contact_entity_id=new_entity_id(),
                                persona=Persona.ECONOMIC_BUYER,
                                role_on_committee="economic_buyer",
                                facets=(),
                            ),
                        )
                    }
                ),
                judge=FaithfulnessJudgeImpl(
                    gateway=FakeGateway(_SUPPORTED), conn_factory=_factory(conn)
                ),
                conn_factory=_factory(conn),
            )
            result = await positioner.position(
                account,
                icp_spec_version=1,
                client_id=_CLIENT,
                client_entity_id=client_entity,
                run_id=run_id,
            )
            assert len(result.narratives) == 1

            # committee for the handoff: one member with a real (resolvable) facet claim.
            facet_cid = await _real_committee_claim(conn, new_entity_id(), "ex-Stripe eng leader")
            member = HandoffCommitteeMember(
                member=CommitteeMember(
                    contact_entity_id=new_entity_id(),
                    persona=Persona.ECONOMIC_BUYER,
                    role_on_committee="economic_buyer",
                    profile_claims=(
                        ProfileClaimView(
                            claim_id=facet_cid,
                            value_json="ex-Stripe eng leader",
                            source_tier=4,
                            identity_binding=IdentityBinding.STRONG,
                            use_class=UseClass.PROFESSIONAL_PUBLIC,
                        ),
                    ),
                ),
                use_decisions={
                    facet_cid: UseDecision(
                        claim_id=facet_cid,
                        usable_for_outreach=True,
                        reason=UseReason.ALLOWED,
                        policy_version=1,
                    )
                },
            )
            assembler = HandoffAssembler(committee_reader=_committee((member,), account))
            assembled = await assembler.assemble(
                conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
            )
            h = assembled.handoff
            # all five sections populated.
            assert h.fit_score.value == pytest.approx(0.82)
            assert h.fit_score.components and h.fit_score.components[0].evidence_claim_ids == (
                signal,
            )
            assert h.intent_score.value == pytest.approx(0.6)
            assert {str(pv.claim_id) for pv in h.account_profile_claims} >= {str(pain)}
            assert len(h.committee) == 1 and len(h.committee[0].profile_claims) == 1
            assert len(h.value_narrative) == 1
            assert h.value_narrative[0].persona is Persona.ECONOMIC_BUYER
            # the scope stamps (AC: (account, icp) is the handoff scope).
            assert h.icp_spec_version == 1 and h.assembled_at == _AT
            # every claim id appearing resolves in the provenance index (AC2).
            narr_id = h.value_narrative[0].claim_id
            for cid in (pain, signal, facet_cid, narr_id):
                assert str(cid) in h.provenance_index
                assert h.provenance_index[str(cid)].source_tier in (1, 4)
            # the answering-model citation rides the wrapper (backlog [M9.3×M12]).
            assert str(narr_id) in assembled.narrative_citations
            assert assembled.narrative_citations[str(narr_id)].answering_model

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_provenance_dangling_reference_fails_the_build() -> None:
    """AC2: a value pointing at a non-existent / out-of-scope claim id raises — never a silent drop.
    Plant a fit score whose component evidence id resolves to no live claim."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            ghost = str(new_claim_id())  # never inserted
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.5, [ghost], icp_version=1, non_fit=False)
            )
            with pytest.raises(HandoffAssemblyError):
                await _assembler().assemble(
                    conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
                )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_superseded_evidence_reference_still_resolves_in_provenance() -> None:
    """A score's decomposition evidence cited a signal that has since been *superseded* (e.g. a
    refreshed signal, no re-score): provenance resolves it to its immutable source — it does NOT
    dangling-fail the build (which re-assembly could never fix). Only a never-inserted id fails."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            old_signal = await _profile_fact(conn, account, "core.employee_count", 500, tier=1)
            # refresh the signal → the old one is superseded, but the score still cites it.
            fresh = account_claim(
                entity_id=account,
                field_key="core.employee_count",
                value_json=520,
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=1.0,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://src.local/x",
            )
            fresh = stamp_reuse(fresh, tenant_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
            await supersede_claim(conn, old_signal, fresh)
            await _write_score(
                conn,
                account,
                FIT_FIELD,
                _score_payload(0.7, [str(old_signal)], icp_version=1, non_fit=False),
            )
            h = (
                await _assembler().assemble(
                    conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
                )
            ).handoff
            # the superseded-but-cited signal still has a provenance entry (traceable, not gone).
            assert str(old_signal) in h.provenance_index

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_committee_excludes_weak_and_sensitive_from_outreach_and_provenance() -> None:
    """AC4: a weak-binding facet and a `sensitive` (use-disallowed) facet are absent from the
    assembled committee AND the provenance index; the identifying + strong-allowed claims remain."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = new_entity_id()
            role_cid = await _real_committee_claim(conn, contact, "economic_buyer")
            kept_cid = await _real_committee_claim(conn, contact, "ex-Stripe")
            weak_cid, sensitive_cid = new_claim_id(), new_claim_id()  # excluded → never resolved

            def _view(
                cid: ClaimId, value: str, binding: IdentityBinding, uc: UseClass
            ) -> ProfileClaimView:
                return ProfileClaimView(
                    claim_id=cid,
                    value_json=value,
                    source_tier=4,
                    identity_binding=binding,
                    use_class=uc,
                )

            member = HandoffCommitteeMember(
                member=CommitteeMember(
                    contact_entity_id=contact,
                    persona=Persona.CHAMPION,
                    role_on_committee="champion",
                    profile_claims=(
                        _view(
                            role_cid,
                            "champion",
                            IdentityBinding.STRONG,
                            UseClass.PROFESSIONAL_PUBLIC,
                        ),
                        _view(
                            kept_cid,
                            "ex-Stripe",
                            IdentityBinding.STRONG,
                            UseClass.PROFESSIONAL_PUBLIC,
                        ),
                        _view(
                            weak_cid, "rumor", IdentityBinding.WEAK, UseClass.PROFESSIONAL_PUBLIC
                        ),
                        _view(sensitive_cid, "health", IdentityBinding.STRONG, UseClass.SENSITIVE),
                    ),
                ),
                use_decisions={
                    role_cid: UseDecision(
                        claim_id=role_cid,
                        usable_for_outreach=True,
                        reason=UseReason.ALLOWED,
                        policy_version=1,
                    ),
                    kept_cid: UseDecision(
                        claim_id=kept_cid,
                        usable_for_outreach=True,
                        reason=UseReason.ALLOWED,
                        policy_version=1,
                    ),
                    weak_cid: UseDecision(
                        claim_id=weak_cid,
                        usable_for_outreach=True,
                        reason=UseReason.ALLOWED,
                        policy_version=1,
                    ),
                    sensitive_cid: UseDecision(
                        claim_id=sensitive_cid,
                        usable_for_outreach=False,
                        reason=UseReason.SENSITIVE_LOCKED,
                        policy_version=1,
                    ),
                },
            )
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.5, [], icp_version=1, non_fit=False)
            )
            assembler = HandoffAssembler(committee_reader=_committee((member,), account))
            h = (
                await assembler.assemble(
                    conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
                )
            ).handoff
            kept = {pv.claim_id for pv in h.committee[0].profile_claims}
            assert role_cid in kept and kept_cid in kept
            assert weak_cid not in kept and sensitive_cid not in kept
            # the excluded ids are absent from the provenance index too (M13.1: rejected absent).
            assert str(weak_cid) not in h.provenance_index
            assert str(sensitive_cid) not in h.provenance_index
            # the kept committee claim carries identity_binding + use_class (Doc D §7).
            kept_view = next(pv for pv in h.committee[0].profile_claims if pv.claim_id == kept_cid)
            assert kept_view.identity_binding is IdentityBinding.STRONG
            assert kept_view.use_class is UseClass.PROFESSIONAL_PUBLIC

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_assembly_is_pure_and_deterministic() -> None:
    """AC5: two assemble() calls over an unchanged claim state with the same stamp produce equal
    objects (byte-stable); the assembler makes no LLM call."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            await _profile_fact(conn, account, "account.operational_pain", "cloud overspend")
            await _profile_fact(conn, account, "account.strategic_moves", "expanding to EU")
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.7, [], icp_version=1, non_fit=False)
            )
            await _write_narrative(
                conn,
                account,
                Persona.ECONOMIC_BUYER,
                icp_version=1,
                account_evidence_ids=[],
                client_knowledge_ids=["ck0"],
            )
            assembler = _assembler()
            a = await assembler.assemble(
                conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
            )
            b = await assembler.assemble(
                conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
            )
            assert a.model_dump(mode="json") == b.model_dump(mode="json")

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_conflict_and_coverage_flags_propagate() -> None:
    """AC6: a planted tier≤2 conflict on a profile field surfaces in field_conflicts; the injected
    coverage_confidence rides through; a committee persona with no narrative is a coverage gap."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            # two disagreeing tier-2 sources on one field → a conflict (mode-aware, exact here).
            a = await _profile_fact(
                conn, account, "account.operational_pain", "overspend", tier=2, verified=False
            )
            b = await _profile_fact(
                conn, account, "account.operational_pain", "security gaps", tier=2, verified=False
            )
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.5, [], icp_version=1, non_fit=False)
            )
            # a committee persona with no narrative claim → coverage gap.
            facet_cid = await _real_committee_claim(conn, new_entity_id(), "ex-Stripe")
            member = HandoffCommitteeMember(
                member=CommitteeMember(
                    contact_entity_id=new_entity_id(),
                    persona=Persona.BLOCKER,
                    role_on_committee="blocker",
                    profile_claims=(
                        ProfileClaimView(claim_id=facet_cid, value_json="ex-Stripe", source_tier=4),
                    ),
                ),
            )
            assembler = HandoffAssembler(committee_reader=_committee((member,), account))
            assembled = await assembler.assemble(
                conn,
                account,
                icp_spec_version=1,
                client_id=_CLIENT,
                assembled_at=_AT,
                coverage_confidence=0.42,
            )
            h = assembled.handoff
            assert "account.operational_pain" in h.field_conflicts
            assert set(h.field_conflicts["account.operational_pain"]) == {a, b}
            assert h.coverage_confidence == pytest.approx(0.42)
            assert Persona.BLOCKER in assembled.coverage_gap_personas

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_non_fit_flag_travels_with_fit() -> None:
    """AC7: an account flagged non-fit during back-scoring carries that flag (D6) with its fit score
    — surfaced on the wrapper since the frozen AccountHandoff has no field for it."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.1, [], icp_version=1, non_fit=True)
            )
            assembled = await _assembler().assemble(
                conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
            )
            assert assembled.non_fit is True

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_reassembly_after_supersede_reflects_new_truth() -> None:
    """AC8: re-assembling after a claim is superseded reflects the new current truth and stamps a
    fresh assembled_at."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            old = await _profile_fact(conn, account, "account.operational_pain", "old pain")
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.5, [], icp_version=1, non_fit=False)
            )
            assembler = _assembler()
            first = await assembler.assemble(
                conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
            )
            old_view = next(pv for pv in first.handoff.account_profile_claims if pv.claim_id == old)
            assert old_view.value_json == "old pain"

            # supersede the pain claim with a new value.
            new_claim = account_claim(
                entity_id=account,
                field_key="account.operational_pain",
                value_json="new pain",
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://src.local/x",
                evidence_span="evidence that new pain",
            )
            new_claim = stamp_reuse(new_claim, tenant_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
            new_cid = await supersede_claim(conn, old, new_claim)
            await record_verification(conn, new_cid, status=VerificationStatus.VERIFIED)

            second = await assembler.assemble(
                conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT2
            )
            values = {str(pv.value_json) for pv in second.handoff.account_profile_claims}
            assert "new pain" in values and "old pain" not in values
            assert str(old) not in second.handoff.provenance_index  # the superseded claim is gone
            assert second.handoff.assembled_at == _AT2

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_two_icps_yield_distinct_handoffs() -> None:
    """AC9 / D5: an account scored + narrated under two ICPs yields a distinct handoff per ICP — the
    assembler keys scores and narrative on the ICP, never mixing them."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.3, [], icp_version=1, non_fit=False)
            )
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.9, [], icp_version=2, non_fit=False)
            )
            await _write_narrative(
                conn,
                account,
                Persona.CHAMPION,
                icp_version=1,
                account_evidence_ids=[],
                client_knowledge_ids=["a"],
            )
            await _write_narrative(
                conn,
                account,
                Persona.BLOCKER,
                icp_version=2,
                account_evidence_ids=[],
                client_knowledge_ids=["b"],
            )
            assembler = _assembler()
            h1 = (
                await assembler.assemble(
                    conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
                )
            ).handoff
            h2 = (
                await assembler.assemble(
                    conn, account, icp_spec_version=2, client_id=_CLIENT, assembled_at=_AT
                )
            ).handoff
            assert h1.fit_score.value == pytest.approx(0.3) and h2.fit_score.value == pytest.approx(
                0.9
            )
            assert {i.persona for i in h1.value_narrative} == {Persona.CHAMPION}
            assert {i.persona for i in h2.value_narrative} == {Persona.BLOCKER}

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_unverified_narrative_is_not_handed_off() -> None:
    """AC2-adjacent / M13.1: an unpromoted (unverified) narrative claim is not in the handoff — only
    judge-verified arguments cross."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.5, [], icp_version=1, non_fit=False)
            )
            await _write_narrative(
                conn,
                account,
                Persona.CHAMPION,
                icp_version=1,
                account_evidence_ids=[],
                client_knowledge_ids=["a"],
                verified=False,
            )
            h = (
                await _assembler().assemble(
                    conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
                )
            ).handoff
            assert h.value_narrative == ()

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_materialization_round_trip_and_tenant_isolation() -> None:
    """The materialised account_handoff round-trips (write → read equal); another client reads None
    for the same account+ICP (tenant isolation — substrate §2)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            await _profile_fact(conn, account, "account.operational_pain", "cloud overspend")
            await _write_score(
                conn, account, FIT_FIELD, _score_payload(0.6, [], icp_version=1, non_fit=False)
            )
            assembled = await _assembler().assemble(
                conn, account, icp_spec_version=1, client_id=_CLIENT, assembled_at=_AT
            )
            await write_handoff(conn, assembled, client_id=_CLIENT)
            got = await read_handoff(
                conn, client_id=_CLIENT, account_entity_id=account, icp_spec_version=1
            )
            assert got is not None
            assert got.model_dump(mode="json") == assembled.model_dump(mode="json")
            # a different client cannot read this client's assembled handoff.
            other = await read_handoff(
                conn, client_id="other-client", account_entity_id=account, icp_spec_version=1
            )
            assert other is None

    run_async(_run())
