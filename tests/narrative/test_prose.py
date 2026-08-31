"""Lane E E1/E2 (WP-A) — the on-completion prose synthesizer.

E1 covers ``account.summary``; E2 adds ``contact.overview`` plus the two governance rules a
person's write-up needs (claim-level G6 by ``use_class``, and the identity-binding stamp).

The pure machinery (the versioned prompts, the empty-beats-fabricated parser, the policy shapes)
runs in ``make check`` with no DB; :class:`ProseSynthesizer` behaviour is exercised against a live
Postgres (skips without one, like the M12 positioner suite) because it reads the merge view and
writes a prose claim + its ``claim_support`` row.

Charter: ``docs/specs/FI-lane-E-on-completion-synthesis.md`` §2.3-§2.7, §4.1-§4.2.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    Claim,
    ClaimId,
    Completion,
    Confidence,
    EntityId,
    ExtractionMethod,
    IdentityBinding,
    JudgeResult,
    JudgeVerdict,
    Message,
    ResearchMode,
    ReuseScope,
    RunId,
    UseClass,
    VerificationStatus,
    account_claim,
    can_be_promoted,
    contact_claim,
    new_run_id,
)
from clue_obs.otel import InMemorySink
from clue_research.claimstore import (
    WorkspaceScope,
    claims_for,
    current_values,
    insert_claim,
    record_verification,
)
from clue_research.identity import (
    DEFAULT_REUSE_POLICY,
    insert_account_entity,
    insert_contact_entity,
    stamp_reuse,
)
from clue_research.narrative import (
    ACCOUNT_SUMMARY,
    CONTACT_OVERVIEW,
    load_prose_pack,
    read_claim_support,
)
from clue_research.narrative.prompts import AccountFact, fact_to_text
from clue_research.narrative.prose import (
    ACCOUNT_SUMMARY_PROMPT_VERSION,
    CONTACT_OVERVIEW_PROMPT_VERSION,
    DEFAULT_CONTACT_PROSE_POLICY,
    DEFAULT_PROSE_POLICY,
    GAP_INSUFFICIENT_FACTS,
    GAP_UNGROUNDED_SYNTHESIS,
    METRIC_PROSE_COVERAGE_GAP,
    METRIC_PROSE_JUDGE_SKIPPED,
    METRIC_PROSE_PRODUCED,
    PROSE_ACCOUNT_FIELDS,
    PROSE_CONTACT_FIELDS,
    PROSE_PROMPTS,
    ProseOutcome,
    ProsePolicy,
    ProseSynthesizer,
    build_account_summary_messages,
    build_contact_overview_messages,
    parse_prose_response,
)
from clue_research.profiling.committee.fields import load_committee_pack
from clue_research.profiling.fields import load_deep_profiling_pack
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

# --- a deterministic fake gateway (records calls; returns canned JSON) -------


class FakeGateway:
    """A deterministic ``LLMGateway`` returning one canned response and recording every call."""

    def __init__(self, response_text: str, *, cost_cents: Decimal = Decimal("0.4")) -> None:
        self._response = response_text
        self._cost = cost_cents
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, list(messages)))
        return Completion(
            model=model, text=self._response, cost_cents=self._cost, finish_reason="stop"
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError("the prose synthesizer never embeds")


_SECOND_PARAGRAPH = "It employs 1200 people and is expanding to the EU."
_PARAGRAPHS = f'{{"paragraphs": ["Acme builds warehouse robotics.", "{_SECOND_PARAGRAPH}"]}}'
_EMPTY_PARAGRAPHS = '{"paragraphs": []}'


# === pure unit (no DB) ======================================================


def test_prompt_registry_and_unknown_version_raises() -> None:
    """Prompt-as-data: the registry is keyed by version, and an unknown version fails loud
    listing the registered versions (mirrors ``prompts.build_positioning_messages``)."""
    assert PROSE_PROMPTS[ACCOUNT_SUMMARY_PROMPT_VERSION]
    with pytest.raises(ValueError, match="unknown prose prompt_version"):
        build_account_summary_messages(account_facts=[], prompt_version="v999")


def test_account_summary_prompt_is_grounded_fenced_and_neutral() -> None:
    """§2.6: the system prompt carries the GROUNDING + SECURITY clauses and the empty-refusal
    output contract; the user message fences the facts as untrusted data; and NO persona / angle /
    client-capability material appears anywhere — that absence is the neutrality property."""
    facts = [
        AccountFact(
            field_key="account.operational_pain",
            value_text="manual scaling toil",
            evidence_span="the ops team scales clusters by hand",
        )
    ]
    messages = build_account_summary_messages(account_facts=facts)
    system, user = messages[0].content, messages[1].content

    assert messages[0].role.value == "system" and messages[1].role.value == "user"
    assert "GROUNDING" in system and "SECURITY" in system
    assert '"paragraphs"' in system  # the output contract
    assert "<<<ACCOUNT_FACTS>>>" in user and "<<<END_ACCOUNT_FACTS>>>" in user
    assert "untrusted data" in user.lower()
    assert "- [account.operational_pain] manual scaling toil" in user
    assert "evidence: the ops team scales clusters by hand" in user

    blob = (system + user).lower()
    for forbidden in ("persona", "angle", "client capabilit", "our client", "buying committee"):
        assert forbidden not in blob


def test_parse_prose_response_keeps_only_non_empty_strings() -> None:
    assert parse_prose_response(_PARAGRAPHS) == (
        "Acme builds warehouse robotics.",
        "It employs 1200 people and is expanding to the EU.",
    )
    fenced = 'Sure:\n```json\n{"paragraphs": ["one", "", "  ", "two"]}\n```\ndone'
    assert parse_prose_response(fenced) == ("one", "two")


def test_parse_prose_response_returns_empty_on_any_failure() -> None:
    """Empty beats fabricated: every malformed shape degrades to ``()`` and never raises."""
    for bad in (
        "",
        "not json at all",
        "{",
        _EMPTY_PARAGRAPHS,
        '{"argument": "wrong key"}',  # the positioner's key is not ours
        '{"paragraphs": "not a list"}',
        '{"paragraphs": [1, 2, 3]}',
        '{"paragraphs": null}',
        "[1, 2, 3]",  # a top-level array is not an object
    ):
        assert parse_prose_response(bad) == (), bad


def test_prose_account_fields_allowlist_excludes_pii_and_client_relative_fields() -> None:
    """§4.1: the allowlist is the ABOUT+INSIGHTS account surface; PII contact channels and
    client-relative scoring are deliberately excluded (a neutral world-fact summary)."""
    assert "core.account_name" in PROSE_ACCOUNT_FIELDS
    assert "account.operational_pain" in PROSE_ACCOUNT_FIELDS
    assert "account.resonance.culture" in PROSE_ACCOUNT_FIELDS
    for excluded in (
        "core.company_email",
        "core.company_phone",
        "core.work_email",
        "core.direct_phone",
        "account.scoring.fit",
        "account.scoring.intent",
        "account.crm_relationship_status",
    ):
        assert excluded not in PROSE_ACCOUNT_FIELDS
    assert len(set(PROSE_ACCOUNT_FIELDS)) == len(PROSE_ACCOUNT_FIELDS)  # no duplicates


# === E2 (WP-A2) — the contact-overview pure surface ==========================


def test_contact_overview_prompt_registry_and_unknown_version_raises() -> None:
    """Prompt-as-data, second tenant: the contact prompt lives in the same versioned registry and
    an unknown version fails loud rather than synthesizing with the account prompt."""
    assert PROSE_PROMPTS[CONTACT_OVERVIEW_PROMPT_VERSION]
    assert (
        PROSE_PROMPTS[CONTACT_OVERVIEW_PROMPT_VERSION]
        != PROSE_PROMPTS[ACCOUNT_SUMMARY_PROMPT_VERSION]
    )
    with pytest.raises(ValueError, match="unknown prose prompt_version"):
        build_contact_overview_messages(contact_facts=[], account_context=None, prompt_version="v9")


def test_default_contact_policy_is_the_contact_prompt_at_a_two_fact_floor() -> None:
    """§2.1: the contact policy is the same shape with its own prompt and the §2.6 contact floor —
    two *contact* facts (the account-context line is garnish and never counts)."""
    assert DEFAULT_CONTACT_PROSE_POLICY.prompt_version == CONTACT_OVERVIEW_PROMPT_VERSION
    assert DEFAULT_CONTACT_PROSE_POLICY.min_facts == 2
    assert DEFAULT_PROSE_POLICY.prompt_version == ACCOUNT_SUMMARY_PROMPT_VERSION  # E1 untouched


def test_contact_overview_prompt_fences_facts_and_optional_account_context() -> None:
    """§3.3: the contact facts are fenced as untrusted data; the account-context fence appears
    ONLY when there is account context; and no persona / client-capability material appears —
    that absence is the neutrality property, exactly as on the account side."""
    facts = [
        AccountFact(
            field_key="contact.current_title",
            value_text="VP of Engineering",
            evidence_span="listed as VP of Engineering on the team page",
        )
    ]
    messages = build_contact_overview_messages(
        contact_facts=facts, account_context="- [core.account_name] Acme Robotics"
    )
    system, user = messages[0].content, messages[1].content

    assert messages[0].role.value == "system" and messages[1].role.value == "user"
    assert "GROUNDING" in system and "SECURITY" in system
    assert '"paragraphs"' in system  # the output contract
    assert "<<<CONTACT_FACTS>>>" in user and "<<<END_CONTACT_FACTS>>>" in user
    assert "<<<ACCOUNT_CONTEXT>>>" in user and "<<<END_ACCOUNT_CONTEXT>>>" in user
    assert "untrusted data" in user.lower()
    assert "- [contact.current_title] VP of Engineering" in user
    assert "evidence: listed as VP of Engineering on the team page" in user
    assert "- [core.account_name] Acme Robotics" in user

    bare = build_contact_overview_messages(contact_facts=facts, account_context=None)[1].content
    assert "<<<CONTACT_FACTS>>>" in bare
    assert "ACCOUNT_CONTEXT" not in bare  # no empty fence when there is no context

    blob = (system + user).lower()
    for forbidden in ("persona", "angle", "client capabilit", "our client", "buying committee"):
        assert forbidden not in blob


def test_prose_contact_fields_allowlist_excludes_assessments_pii_and_compliance_records() -> None:
    """§3.1: the allowlist is the professional + facet contact surface. Client-relative committee
    assessments, PII channels and compliance records are excluded by KEY; the two escalatable
    facets stay ON the list because G6 excludes them per-CLAIM by ``use_class``."""
    for present in (
        "contact.current_title",
        "contact.job_function",
        "contact.organization_relationship",
        "contact.facet.career_history",
        "contact.facet.recent_post",
        # deliberately allowlisted: a de-escalated (non-sensitive) claim is legitimate material,
        # and the SENSITIVE ones are dropped per-claim by G6 — not by key.
        "contact.facet.causes",
        "contact.facet.stated_interests",
    ):
        assert present in PROSE_CONTACT_FIELDS
    for excluded in (
        "contact.role_on_committee",
        "contact.persona",
        "contact.class",
        "core.work_email",
        "core.direct_phone",
        "contact.import_record",
        "contact.jurisdiction",
    ):
        assert excluded not in PROSE_CONTACT_FIELDS
    assert len(set(PROSE_CONTACT_FIELDS)) == len(PROSE_CONTACT_FIELDS)  # no duplicates


# === DB-gated behaviour =====================================================


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


class FakeJudge:
    """A :class:`~clue_core.FaithfulnessJudge` that records its calls and applies the verdict's
    status the way the real M9.3 judge does (it drives ``verification_status`` itself, in its own
    transaction — ``verification/faithfulness.py::status_for_verdict``)."""

    def __init__(
        self,
        conn: AsyncConnection,
        *,
        verdict: JudgeVerdict = JudgeVerdict.SUPPORTED,
        score: float = 0.92,
    ) -> None:
        self._conn = conn
        self._verdict = verdict
        self._score = score
        self.calls: list[Claim] = []

    async def judge(self, claim: Claim) -> JudgeResult:
        self.calls.append(claim)
        status: VerificationStatus | None = {
            JudgeVerdict.SUPPORTED: VerificationStatus.VERIFIED,
            JudgeVerdict.PARTIAL: VerificationStatus.FLAGGED,
            JudgeVerdict.UNSUPPORTED: VerificationStatus.REJECTED,
            JudgeVerdict.CONTRADICTED: VerificationStatus.REJECTED,
        }[self._verdict]
        # ``supported`` promotes only a *structurally promotable* claim — a weak-binding contact
        # claim stays unverified however good the verdict is (``status_for_verdict`` /
        # ``can_be_promoted``). Mirroring that here is what makes the E2 binding-stamp test real:
        # a fake that promoted unconditionally would hide the guarantee it is meant to pin.
        if status is VerificationStatus.VERIFIED and not can_be_promoted(claim):
            status = None
        if status is not None:
            await record_verification(self._conn, claim.id, status=status)
        return JudgeResult(claim_id=claim.id, verdict=self._verdict, score=self._score)


@asynccontextmanager
async def prose_conn() -> AsyncIterator[AsyncConnection]:
    """``rollback_conn`` plus the Lane E prose pack (so ``account.summary`` / ``contact.overview``
    resolve), the M8.2 deep-profiling pack (the ``account.resonance.*`` half of
    :data:`PROSE_ACCOUNT_FIELDS` and the ``contact.facet.*`` half of
    :data:`PROSE_CONTACT_FIELDS` — only ``resonance.culture`` / ``facet.recent_post`` live in
    ``CORE_PACK``) and the M8.3 committee pack (the professional ``contact.*`` fields). The shared
    harness loads the core + M12 narrative packs only."""
    async with rollback_conn() as conn:
        await load_prose_pack(conn)
        await load_deep_profiling_pack(conn)
        await load_committee_pack(conn)
        yield conn


async def _account(conn: AsyncConnection, workspace_id: str = "tenant-a") -> EntityId:
    await seed_workspace(conn, workspace_id)
    return await insert_account_entity(
        conn,
        canonical_name="Acme",
        primary_domain="acme.com",
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )


async def _write_fact(
    conn: AsyncConnection,
    account: EntityId,
    field_key: str,
    value: JsonValue,
    *,
    workspace_id: str = "tenant-a",
    run_id: RunId | None = None,
) -> ClaimId:
    """Write a verified tier-4 account claim, so the merge view surfaces it as prose evidence."""
    claim = account_claim(
        entity_id=account,
        field_key=field_key,
        value_json=value,
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=run_id or new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://src.local/x",
        evidence_span=f"evidence for {field_key}",
    )
    claim = stamp_reuse(claim, workspace_id=workspace_id, policy=DEFAULT_REUSE_POLICY)
    claim_id = await insert_claim(conn, claim)
    await record_verification(conn, claim_id, status=VerificationStatus.VERIFIED)
    return claim_id


_THREE_FACTS: tuple[tuple[str, JsonValue], ...] = (
    ("core.account_name", "Acme Robotics"),
    ("core.industry", "warehouse automation"),
    ("account.strategic_moves", "expanding to the EU"),
)


async def _seed_facts(
    conn: AsyncConnection,
    account: EntityId,
    facts: tuple[tuple[str, JsonValue], ...] = _THREE_FACTS,
    *,
    workspace_id: str = "tenant-a",
) -> list[ClaimId]:
    return [
        await _write_fact(conn, account, key, value, workspace_id=workspace_id)
        for key, value in facts
    ]


def _synthesizer(
    conn: AsyncConnection,
    *,
    response: str = _PARAGRAPHS,
    judge: FakeJudge | None = None,
    policy: ProsePolicy = DEFAULT_PROSE_POLICY,
    contact_policy: ProsePolicy = DEFAULT_CONTACT_PROSE_POLICY,
    sink: InMemorySink | None = None,
) -> tuple[ProseSynthesizer, FakeGateway]:
    gateway = FakeGateway(response)
    return (
        ProseSynthesizer(
            gateway=gateway,
            judge=judge,
            policy=policy,
            contact_policy=contact_policy,
            conn_factory=_factory(conn),
            sink=sink,
        ),
        gateway,
    )


async def _synthesize(
    synthesizer: ProseSynthesizer,
    account: EntityId,
    *,
    workspace_id: str = "tenant-a",
    job_id: UUID | None = None,
    research_outcome: str = "completed",
) -> ProseOutcome:
    return await synthesizer.synthesize_account_summary(
        account_entity_id=account,
        workspace_id=workspace_id,
        research_run_id=new_run_id(),
        job_id=job_id or uuid4(),
        research_outcome=research_outcome,
    )


async def _live_summaries(
    conn: AsyncConnection, account: EntityId, *, workspace_id: str = "tenant-a"
) -> list[Claim]:
    return list(
        await claims_for(
            conn, account, ACCOUNT_SUMMARY, scope=WorkspaceScope.for_workspace(workspace_id)
        )
    )


@pytest.mark.usefixtures("require_narrative_db")
def test_below_min_facts_is_a_coverage_gap_with_no_spend() -> None:
    """§2.6: fewer than ``min_facts`` merge winners refuses *before* the model is called — no
    gateway call, no claim, a coverage-gap outcome and its metric."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            await _seed_facts(conn, account, _THREE_FACTS[:2])  # one short of the floor
            sink = InMemorySink()
            synthesizer, gateway = _synthesizer(conn, sink=sink)

            outcome = await _synthesize(synthesizer, account)

            assert outcome.kind == "coverage_gap"
            assert outcome.gap_reason == GAP_INSUFFICIENT_FACTS
            assert outcome.claim_id is None
            assert gateway.calls == []  # never spends to fabricate
            assert await _live_summaries(conn, account) == []
            assert (
                sink.counter(
                    METRIC_PROSE_COVERAGE_GAP,
                    field_key=ACCOUNT_SUMMARY,
                    reason=GAP_INSUFFICIENT_FACTS,
                )
                == 1
            )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_ungrounded_synthesis_is_a_coverage_gap_not_a_claim() -> None:
    """Empty beats fabricated: the model's own refusal (``{"paragraphs": []}``) writes no claim."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            await _seed_facts(conn, account)
            sink = InMemorySink()
            synthesizer, gateway = _synthesizer(conn, response=_EMPTY_PARAGRAPHS, sink=sink)

            outcome = await _synthesize(synthesizer, account)

            assert outcome.kind == "coverage_gap"
            assert outcome.gap_reason == GAP_UNGROUNDED_SYNTHESIS
            assert len(gateway.calls) == 1  # it *did* try — the refusal came from the model
            assert await _live_summaries(conn, account) == []
            assert (
                sink.counter(
                    METRIC_PROSE_COVERAGE_GAP,
                    field_key=ACCOUNT_SUMMARY,
                    reason=GAP_UNGROUNDED_SYNTHESIS,
                )
                == 1
            )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_happy_path_writes_one_verified_summary_with_support() -> None:
    """The E1 core: ONE live tier-4 ``account.summary`` claim carrying all five schema keys with
    ``project_id=None``, a ``claim_support`` row citing every fact placed in the prompt, promoted
    VERIFIED by the judge and therefore served by the canonical merge."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            evidence_ids = await _seed_facts(conn, account)
            job_id = uuid4()
            sink = InMemorySink()
            judge = FakeJudge(conn)
            synthesizer, gateway = _synthesizer(conn, judge=judge, sink=sink)

            outcome = await _synthesize(
                synthesizer, account, job_id=job_id, research_outcome="needs_review"
            )

            assert outcome.kind == "written"
            assert outcome.verification_status == VerificationStatus.VERIFIED.value
            assert set(outcome.support_claim_ids) == set(evidence_ids)
            assert len(judge.calls) == 1 and judge.calls[0].id == outcome.claim_id

            live = await _live_summaries(conn, account)
            assert len(live) == 1
            claim = live[0]
            assert claim.id == outcome.claim_id
            assert claim.source_tier == 4
            assert claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.workspace_id == "tenant-a"
            assert claim.product_id is None
            assert claim.evidence_span  # non-empty (tier-4 promotion + DB CHECK)
            assert claim.verification_status is VerificationStatus.VERIFIED

            value = claim.value_json
            assert isinstance(value, dict)
            assert set(value) == {
                "paragraphs",
                "prompt_version",
                "synthesized_from_job_id",
                "research_outcome",
                "project_id",
            }
            assert value["paragraphs"] == ["Acme builds warehouse robotics.", _SECOND_PARAGRAPH]
            assert value["prompt_version"] == ACCOUNT_SUMMARY_PROMPT_VERSION
            assert value["synthesized_from_job_id"] == str(job_id)
            assert value["research_outcome"] == "needs_review"  # §7-D1 honesty stamp
            assert value["project_id"] is None  # §7-D2 amendment slot, always null while neutral

            support = await read_claim_support(conn, claim.id)
            assert support is not None
            assert len(support.account_evidence_ids) >= 3
            assert set(support.account_evidence_ids) == set(evidence_ids)
            assert support.client_knowledge_ids == ()  # neutral prose cites no client knowledge

            served = await current_values(
                conn,
                [account],
                [ACCOUNT_SUMMARY],
                scope=WorkspaceScope.for_workspace("tenant-a"),
            )
            assert served[(account, ACCOUNT_SUMMARY)].provenance.claim_id == claim.id
            assert gateway.calls[0][0] == DEFAULT_PROSE_POLICY.synthesis_model
            assert sink.counter(METRIC_PROSE_PRODUCED, field_key=ACCOUNT_SUMMARY) == 1
            assert sink.counter(METRIC_PROSE_JUDGE_SKIPPED, field_key=ACCOUNT_SUMMARY) == 0

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_judge_rejected_summary_is_stored_but_never_served() -> None:
    """A judge refusal leaves the claim durable-but-invisible: the SUMMARY empty state stands, and
    the outcome reports the rejected status rather than a success."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            await _seed_facts(conn, account)
            synthesizer, _ = _synthesizer(
                conn, judge=FakeJudge(conn, verdict=JudgeVerdict.UNSUPPORTED, score=0.05)
            )

            outcome = await _synthesize(synthesizer, account)

            assert outcome.kind == "written"
            assert outcome.verification_status == VerificationStatus.REJECTED.value
            live = await _live_summaries(conn, account)
            assert len(live) == 1 and live[0].verification_status is VerificationStatus.REJECTED
            served = await current_values(
                conn,
                [account],
                [ACCOUNT_SUMMARY],
                scope=WorkspaceScope.for_workspace("tenant-a"),
            )
            assert (account, ACCOUNT_SUMMARY) not in served  # rejected never serves

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_judge_none_writes_unverified_prose_that_disabled_mode_still_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FI-M12 toggle compat §3-A/§3-B: with ``judge=None`` the claim is written at its born
    ``unverified`` status, the skip is recorded, and with ``CLUE_VERIFICATION_ENABLED=false`` the
    *defaulted* merge read still serves it (the tier-4 verified-only gate drops)."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            await _seed_facts(conn, account)
            sink = InMemorySink()
            synthesizer, _ = _synthesizer(conn, judge=None, sink=sink)

            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            outcome = await _synthesize(synthesizer, account)

            assert outcome.kind == "written"
            assert outcome.verification_status == VerificationStatus.UNVERIFIED.value
            assert sink.counter(METRIC_PROSE_JUDGE_SKIPPED, field_key=ACCOUNT_SUMMARY) == 1
            assert sink.counter(METRIC_PROSE_PRODUCED, field_key=ACCOUNT_SUMMARY) == 1

            scope = WorkspaceScope.for_workspace("tenant-a")
            served = await current_values(conn, [account], [ACCOUNT_SUMMARY], scope=scope)
            assert served[(account, ACCOUNT_SUMMARY)].provenance.claim_id == outcome.claim_id

            # ... and the same unverified claim is correctly invisible with the toggle on.
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "true")
            assert (account, ACCOUNT_SUMMARY) not in await current_values(
                conn, [account], [ACCOUNT_SUMMARY], scope=scope
            )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_second_synthesis_supersedes_the_prior_summary() -> None:
    """§2.5: one live claim per ``(entity, field, workspace, project_id=None)`` — a second
    completed job refreshes the prose rather than duplicating it, and the new claim gets its own
    ``claim_support`` row."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            await _seed_facts(conn, account)
            synthesizer, _ = _synthesizer(conn, judge=FakeJudge(conn))

            first = await _synthesize(synthesizer, account, job_id=uuid4())
            second = await _synthesize(synthesizer, account, job_id=uuid4())

            assert first.claim_id != second.claim_id
            scope = WorkspaceScope.for_workspace("tenant-a")
            live = await _live_summaries(conn, account)
            assert [claim.id for claim in live] == [second.claim_id]
            history = await claims_for(
                conn, account, ACCOUNT_SUMMARY, include_superseded=True, scope=scope
            )
            assert len(history) == 2  # the prior is retained, superseded (append-only)
            prior = next(claim for claim in history if claim.id == first.claim_id)
            assert prior.superseded_by == second.claim_id
            assert await read_claim_support(conn, second.claim_id) is not None

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_evidence_span_is_non_empty_and_capped_by_policy() -> None:
    """The judge's grounding is the assembled fact span, capped by ``max_evidence_chars``; the
    ``min_facts`` gate is what guarantees it is never empty on a written claim."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            await _seed_facts(conn, account)
            capped = DEFAULT_PROSE_POLICY.model_copy(update={"max_evidence_chars": 40})
            synthesizer, _ = _synthesizer(conn, judge=FakeJudge(conn), policy=capped)

            outcome = await _synthesize(synthesizer, account)

            claim = (await _live_summaries(conn, account))[0]
            assert claim.id == outcome.claim_id
            assert claim.evidence_span is not None
            assert len(claim.evidence_span) == 40

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_facts_render_through_fact_to_text_in_allowlist_order() -> None:
    """A structured (dict-valued) resonance fact reaches the prompt as deterministic canonical JSON
    via the shared ``fact_to_text``, and the facts appear in allowlist order so one set of facts
    always produces one prompt."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            sentiment: JsonValue = {"label": "mixed", "polarity": -0.1, "summary": "uneven"}
            await _seed_facts(
                conn,
                account,
                (
                    ("account.resonance.employee_sentiment", sentiment),
                    ("account.strategic_moves", "expanding to the EU"),
                    ("core.account_name", "Acme Robotics"),
                ),
            )
            synthesizer, gateway = _synthesizer(conn, judge=FakeJudge(conn))

            await _synthesize(synthesizer, account)
            await _synthesize(synthesizer, account)  # same facts -> byte-identical prompt

            user = gateway.calls[0][1][1].content
            assert user == gateway.calls[1][1][1].content  # deterministic

            # The dict reaches the prompt as compact canonical JSON of the value *as stored* —
            # jsonb normalizes object key order, so rendering the merge winner (not the dict the
            # test wrote) is what makes the prompt reproducible.
            field = "account.resonance.employee_sentiment"
            stored = (
                await current_values(
                    conn, [account], [field], scope=WorkspaceScope.for_workspace("tenant-a")
                )
            )[(account, field)].value_json
            rendered = fact_to_text(field, stored)
            # compact canonical JSON — lossless and separator-free (not pretty-printed prose).
            # The key ORDER is Postgres's jsonb normalization, which is why the rendering must be
            # taken from the merge winner rather than from the dict the test happened to write.
            assert json.loads(rendered) == {
                "label": "mixed",
                "polarity": -0.1,
                "summary": "uneven",
            }
            assert " " not in rendered
            assert f"- [{field}] {rendered}" in user
            # allowlist order, not insertion order: account_name < strategic_moves < resonance.*
            assert (
                user.index("core.account_name")
                < user.index("account.strategic_moves")
                < user.index(field)
            )

    run_async(_run())


# === E2 (WP-A2) — the contact overview, DB-gated ============================

_CONTACT_TITLE = "contact.current_title"
_CONTACT_FUNCTION = "contact.job_function"
_CONTACT_LEVEL = "contact.job_level"
_CONTACT_CAREER = "contact.facet.career_history"
_CONTACT_CAUSES = "contact.facet.causes"
_CONTACT_INTERESTS = "contact.facet.stated_interests"

_OVERVIEW_PARAGRAPH = "Dana Reed is VP of Engineering at Acme Robotics."
_CONTACT_PARAGRAPHS = f'{{"paragraphs": ["{_OVERVIEW_PARAGRAPH}"]}}'

_ACCOUNT_CONTEXT_FACTS: tuple[tuple[str, JsonValue], ...] = (
    ("core.account_name", "Acme Robotics"),
    ("core.company_about", "Acme builds warehouse robotics."),
)


async def _contact(
    conn: AsyncConnection, account: EntityId, *, full_name: str = "Dana Reed"
) -> EntityId:
    return await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name=full_name,
        linkedin_url=f"https://linkedin.com/in/{full_name.lower().replace(' ', '-')}",
    )


async def _write_contact_fact(
    conn: AsyncConnection,
    contact: EntityId,
    field_key: str,
    value: JsonValue,
    *,
    use_class: UseClass | None = UseClass.PROFESSIONAL_PUBLIC,
    binding: IdentityBinding | None = IdentityBinding.STRONG,
    workspace_id: str = "tenant-a",
) -> ClaimId:
    """Write a tier-1 contact claim the merge serves, stamped through the real ``contact_claim``
    factory + ``stamp_reuse`` path.

    ``binding`` / ``use_class`` may be ``None``: the 0004 governance CHECK requires them only for
    ``contact.facet.*``, so a *plain* ``contact.*`` claim with neither is representable, insertable
    and servable — precisely the hole E2's two governance rules have to close. The factory requires
    both, so the ``None`` is applied afterwards by ``model_copy`` (the shape
    ``tests/integration/test_fi2_slice1_read_layer.py`` uses)."""
    claim = stamp_reuse(
        contact_claim(
            entity_id=contact,
            field_key=field_key,
            value_json=value,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=Confidence(1.0),
            run_id=new_run_id(),
            research_mode=ResearchMode.CONTACT_PROFILING,
            identity_binding=binding or IdentityBinding.STRONG,
            use_class=use_class or UseClass.PROFESSIONAL_PUBLIC,
            evidence_span=f"evidence for {field_key}",
        ),
        workspace_id=workspace_id,
    ).model_copy(update={"identity_binding": binding, "use_class": use_class})
    return await insert_claim(conn, claim)


_TWO_CONTACT_FACTS: tuple[tuple[str, JsonValue], ...] = (
    (_CONTACT_TITLE, "VP of Engineering"),
    (_CONTACT_CAREER, [{"org": "Globex", "role": "Director of Engineering"}]),
)


async def _seed_contact_facts(
    conn: AsyncConnection,
    contact: EntityId,
    facts: tuple[tuple[str, JsonValue], ...] = _TWO_CONTACT_FACTS,
    *,
    binding: IdentityBinding | None = IdentityBinding.STRONG,
) -> list[ClaimId]:
    return [
        await _write_contact_fact(conn, contact, key, value, binding=binding)
        for key, value in facts
    ]


async def _synthesize_contact(
    synthesizer: ProseSynthesizer,
    contact: EntityId,
    *,
    parent_account_id: EntityId | None = None,
    workspace_id: str = "tenant-a",
    job_id: UUID | None = None,
    research_outcome: str = "completed",
) -> ProseOutcome:
    return await synthesizer.synthesize_contact_overview(
        contact_entity_id=contact,
        workspace_id=workspace_id,
        research_run_id=new_run_id(),
        job_id=job_id or uuid4(),
        research_outcome=research_outcome,
        parent_account_id=parent_account_id,
    )


async def _live_overviews(
    conn: AsyncConnection, contact: EntityId, *, workspace_id: str = "tenant-a"
) -> list[Claim]:
    return list(
        await claims_for(
            conn, contact, CONTACT_OVERVIEW, scope=WorkspaceScope.for_workspace(workspace_id)
        )
    )


@pytest.mark.usefixtures("require_narrative_db")
def test_contact_overview_happy_path_writes_one_strong_verified_claim() -> None:
    """The E2 core: STRONG professional + facet facts plus the parent account's context produce
    ONE live tier-4 ``contact.overview`` claim — born ``identity_binding=STRONG`` (§1.1: every
    cited contact claim is STRONG) and ``use_class=professional-public`` — carrying all five
    schema keys with ``project_id=None``, a support row citing the contact facts AND the
    account-context claims, promoted VERIFIED and served by the canonical merge."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            contact_ids = await _seed_contact_facts(conn, contact)
            context_ids = await _seed_facts(conn, account, _ACCOUNT_CONTEXT_FACTS)
            job_id = uuid4()
            sink = InMemorySink()
            judge = FakeJudge(conn)
            synthesizer, gateway = _synthesizer(
                conn, response=_CONTACT_PARAGRAPHS, judge=judge, sink=sink
            )

            outcome = await _synthesize_contact(
                synthesizer,
                contact,
                parent_account_id=account,
                job_id=job_id,
                research_outcome="needs_review",
            )

            assert outcome.kind == "written"
            assert outcome.verification_status == VerificationStatus.VERIFIED.value
            assert set(outcome.support_claim_ids) == set(contact_ids) | set(context_ids)
            assert len(judge.calls) == 1 and judge.calls[0].id == outcome.claim_id

            live = await _live_overviews(conn, contact)
            assert len(live) == 1
            claim = live[0]
            assert claim.id == outcome.claim_id
            assert claim.source_tier == 4
            assert claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
            assert claim.identity_binding is IdentityBinding.STRONG  # §1.1 all-STRONG inputs
            assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.workspace_id == "tenant-a"
            assert claim.product_id is None
            assert claim.evidence_span
            assert claim.verification_status is VerificationStatus.VERIFIED

            value = claim.value_json
            assert isinstance(value, dict)
            assert set(value) == {
                "paragraphs",
                "prompt_version",
                "synthesized_from_job_id",
                "research_outcome",
                "project_id",
            }
            assert value["paragraphs"] == [_OVERVIEW_PARAGRAPH]
            assert value["prompt_version"] == CONTACT_OVERVIEW_PROMPT_VERSION
            assert value["synthesized_from_job_id"] == str(job_id)
            assert value["research_outcome"] == "needs_review"
            assert value["project_id"] is None

            support = await read_claim_support(conn, claim.id)
            assert support is not None
            # The account-context ids ride the (legacy-named) account_evidence_ids leg with the
            # contact facts — one support surface, not an extended schema.
            assert set(support.account_evidence_ids) == set(contact_ids) | set(context_ids)
            assert support.client_knowledge_ids == ()

            served = await current_values(
                conn, [contact], [CONTACT_OVERVIEW], scope=WorkspaceScope.for_workspace("tenant-a")
            )
            assert served[(contact, CONTACT_OVERVIEW)].provenance.claim_id == claim.id
            assert sink.counter(METRIC_PROSE_PRODUCED, field_key=CONTACT_OVERVIEW) == 1
            assert sink.counter(METRIC_PROSE_JUDGE_SKIPPED, field_key=CONTACT_OVERVIEW) == 0
            # both fences reached the model
            user = gateway.calls[0][1][1].content
            assert "<<<CONTACT_FACTS>>>" in user and "<<<ACCOUNT_CONTEXT>>>" in user
            assert "Acme builds warehouse robotics." in user

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_contact_min_facts_counts_contact_facts_only() -> None:
    """§1.3: ``min_facts`` counts CONTACT facts. A single contact fact plus a full account context
    is still a coverage gap (the context is garnish, never coverage), and the floor itself is
    policy — ``contact_policy`` threads through the constructor."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _seed_contact_facts(conn, contact, _TWO_CONTACT_FACTS[:1])  # one contact fact
            await _seed_facts(conn, account, _ACCOUNT_CONTEXT_FACTS)  # ... plus full context
            sink = InMemorySink()
            synthesizer, gateway = _synthesizer(
                conn, response=_CONTACT_PARAGRAPHS, judge=FakeJudge(conn), sink=sink
            )

            outcome = await _synthesize_contact(synthesizer, contact, parent_account_id=account)

            assert outcome.kind == "coverage_gap"
            assert outcome.gap_reason == GAP_INSUFFICIENT_FACTS
            assert gateway.calls == []  # never spends to fabricate
            assert await _live_overviews(conn, contact) == []
            assert (
                sink.counter(
                    METRIC_PROSE_COVERAGE_GAP,
                    field_key=CONTACT_OVERVIEW,
                    reason=GAP_INSUFFICIENT_FACTS,
                )
                == 1
            )

            # the second contact fact clears the default floor ...
            await _seed_contact_facts(conn, contact, _TWO_CONTACT_FACTS[1:])
            assert (
                await _synthesize_contact(synthesizer, contact, parent_account_id=account)
            ).kind == "written"

            # ... and a stricter injected contact policy raises it again.
            strict, strict_gateway = _synthesizer(
                conn,
                response=_CONTACT_PARAGRAPHS,
                judge=FakeJudge(conn),
                contact_policy=DEFAULT_CONTACT_PROSE_POLICY.model_copy(update={"min_facts": 3}),
            )
            strict_outcome = await _synthesize_contact(strict, contact, parent_account_id=account)
            assert strict_outcome.kind == "coverage_gap"
            assert strict_gateway.calls == []

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_weak_bound_contact_facts_never_reach_the_prompt() -> None:
    """§1.1 (b): literally-WEAK contact claims are excluded by the merge in BOTH toggle modes, so
    they never surface as facts — the synthesis is a coverage gap, not a WEAK-stamped write."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _seed_contact_facts(conn, contact, binding=IdentityBinding.WEAK)
            sink = InMemorySink()
            synthesizer, gateway = _synthesizer(
                conn, response=_CONTACT_PARAGRAPHS, judge=FakeJudge(conn), sink=sink
            )

            outcome = await _synthesize_contact(synthesizer, contact, parent_account_id=account)

            assert outcome.kind == "coverage_gap"
            assert outcome.gap_reason == GAP_INSUFFICIENT_FACTS
            assert outcome.claim_id is None
            assert gateway.calls == []
            assert await _live_overviews(conn, contact) == []

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_contact_overview_without_account_context_still_synthesizes() -> None:
    """§1.3: absent account context — no ``parent_account_id``, or a parent with no name/about
    winners — is NOT a gap: no ACCOUNT_CONTEXT fence, no account ids in the support row, and the
    overview is written from the contact's own facts."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            contact_ids = await _seed_contact_facts(conn, contact)
            synthesizer, gateway = _synthesizer(
                conn, response=_CONTACT_PARAGRAPHS, judge=FakeJudge(conn)
            )

            # (a) no parent account passed at all
            outcome = await _synthesize_contact(synthesizer, contact)
            assert outcome.kind == "written"
            assert set(outcome.support_claim_ids) == set(contact_ids)
            user = gateway.calls[0][1][1].content
            assert "<<<CONTACT_FACTS>>>" in user and "ACCOUNT_CONTEXT" not in user
            support = await read_claim_support(conn, outcome.claim_id)
            assert support is not None and set(support.account_evidence_ids) == set(contact_ids)

            # (b) a parent account that has no name/about winners yet
            second = await _synthesize_contact(synthesizer, contact, parent_account_id=account)
            assert second.kind == "written"
            assert set(second.support_claim_ids) == set(contact_ids)
            assert "ACCOUNT_CONTEXT" not in gateway.calls[1][1][1].content

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_second_contact_synthesis_supersedes_the_prior_overview() -> None:
    """§2.5, contact tenant: one live claim per ``(entity, field, workspace, project_id=None)`` —
    a second completed contact job refreshes the overview rather than duplicating it."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _seed_contact_facts(conn, contact)
            synthesizer, _ = _synthesizer(conn, response=_CONTACT_PARAGRAPHS, judge=FakeJudge(conn))

            first = await _synthesize_contact(synthesizer, contact, job_id=uuid4())
            second = await _synthesize_contact(synthesizer, contact, job_id=uuid4())

            assert first.claim_id != second.claim_id
            live = await _live_overviews(conn, contact)
            assert [claim.id for claim in live] == [second.claim_id]
            history = await claims_for(
                conn,
                contact,
                CONTACT_OVERVIEW,
                include_superseded=True,
                scope=WorkspaceScope.for_workspace("tenant-a"),
            )
            assert len(history) == 2
            prior = next(claim for claim in history if claim.id == first.claim_id)
            assert prior.superseded_by == second.claim_id
            assert await read_claim_support(conn, second.claim_id) is not None

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_contact_overview_with_no_judge_is_unverified_and_disabled_mode_serves_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggle compat on the contact tenant: ``judge=None`` writes the overview at its born
    ``unverified`` status with the skip recorded; disabled mode serves it, enabled mode does
    not."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _seed_contact_facts(conn, contact)
            sink = InMemorySink()
            synthesizer, _ = _synthesizer(conn, response=_CONTACT_PARAGRAPHS, judge=None, sink=sink)

            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            outcome = await _synthesize_contact(synthesizer, contact, parent_account_id=account)

            assert outcome.kind == "written"
            assert outcome.verification_status == VerificationStatus.UNVERIFIED.value
            assert sink.counter(METRIC_PROSE_JUDGE_SKIPPED, field_key=CONTACT_OVERVIEW) == 1
            assert sink.counter(METRIC_PROSE_PRODUCED, field_key=CONTACT_OVERVIEW) == 1

            scope = WorkspaceScope.for_workspace("tenant-a")
            served = await current_values(conn, [contact], [CONTACT_OVERVIEW], scope=scope)
            assert served[(contact, CONTACT_OVERVIEW)].provenance.claim_id == outcome.claim_id

            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "true")
            assert (contact, CONTACT_OVERVIEW) not in await current_values(
                conn, [contact], [CONTACT_OVERVIEW], scope=scope
            )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_g6_sensitive_contact_claims_are_totally_absent() -> None:
    """§1.2 (G6): a contact claim tagged ``use_class=sensitive`` — including one that escalated
    per-claim on an allowlisted field — is absent from EVERYWHERE: the prompt the model sees, the
    stored claim's evidence span, and the support row's ids. The synthesis still succeeds on the
    remaining eligible facts, which is the whole point of a claim-level rule: the benign siblings
    of a sensitive field stay usable."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            eligible = await _seed_contact_facts(conn, contact)
            secret_cause: JsonValue = [{"cause": "unspeakable-marker", "context": "donor list"}]
            sensitive_ids = [
                await _write_contact_fact(
                    conn, contact, _CONTACT_CAUSES, secret_cause, use_class=UseClass.SENSITIVE
                ),
                await _write_contact_fact(
                    conn,
                    contact,
                    _CONTACT_INTERESTS,
                    ["unspeakable-marker rallies"],
                    use_class=UseClass.SENSITIVE,  # escalated per-claim on an allowlisted field
                ),
            ]
            synthesizer, gateway = _synthesizer(
                conn, response=_CONTACT_PARAGRAPHS, judge=FakeJudge(conn)
            )

            outcome = await _synthesize_contact(synthesizer, contact, parent_account_id=account)

            assert outcome.kind == "written"
            prompt = "\n".join(
                message.content for _model, msgs in gateway.calls for message in msgs
            )
            assert "unspeakable-marker" not in prompt
            assert _CONTACT_CAUSES not in prompt and _CONTACT_INTERESTS not in prompt

            claim = (await _live_overviews(conn, contact))[0]
            assert claim.evidence_span is not None
            assert "unspeakable-marker" not in claim.evidence_span

            support = await read_claim_support(conn, claim.id)
            assert support is not None
            assert set(support.account_evidence_ids).isdisjoint(sensitive_ids)
            assert set(outcome.support_claim_ids).isdisjoint(sensitive_ids)
            assert set(eligible) <= set(support.account_evidence_ids)

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_g6_is_fail_closed_on_a_contact_claim_with_no_use_class() -> None:
    """§1.2, fail-closed: a plain ``contact.*`` claim can legally be born with NO use-class (the
    0004 CHECK binds only ``contact.facet.*``), and the merge serves it. An unclassifiable claim
    is treated exactly like a sensitive one — dropped from the facts, and therefore from the
    coverage count too, so one eligible fact plus one unclassified fact is a gap, not a write."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _seed_contact_facts(conn, contact, _TWO_CONTACT_FACTS[:1])  # one eligible fact
            await _write_contact_fact(
                conn, contact, _CONTACT_FUNCTION, "unclassified-marker", use_class=None
            )
            sink = InMemorySink()
            synthesizer, gateway = _synthesizer(
                conn, response=_CONTACT_PARAGRAPHS, judge=FakeJudge(conn), sink=sink
            )

            outcome = await _synthesize_contact(synthesizer, contact, parent_account_id=account)

            assert outcome.kind == "coverage_gap"
            assert outcome.gap_reason == GAP_INSUFFICIENT_FACTS
            assert gateway.calls == []  # the unclassified claim never reached a paid call
            assert await _live_overviews(conn, contact) == []
            assert (
                sink.counter(
                    METRIC_PROSE_COVERAGE_GAP,
                    field_key=CONTACT_OVERVIEW,
                    reason=GAP_INSUFFICIENT_FACTS,
                )
                == 1
            )

    run_async(_run())


@pytest.mark.usefixtures("require_narrative_db")
def test_non_strong_bound_inputs_make_the_overview_born_weak_and_unservable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1.1: a served contact claim whose ``identity_binding`` is ``None`` is *not* STRONG, so the
    prose it grounds is born WEAK. That write is stored-but-never-served: the merge excludes it in
    BOTH toggle modes (identity protection is not verification) and it can never be promoted past
    ``unverified`` even on a supported verdict."""

    async def _run() -> None:
        async with prose_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _seed_contact_facts(conn, contact, _TWO_CONTACT_FACTS[:1])  # STRONG
            await _write_contact_fact(conn, contact, _CONTACT_FUNCTION, "engineering", binding=None)
            judge = FakeJudge(conn)  # SUPPORTED — promotion must still be refused
            synthesizer, _ = _synthesizer(conn, response=_CONTACT_PARAGRAPHS, judge=judge)

            outcome = await _synthesize_contact(synthesizer, contact, parent_account_id=account)

            assert outcome.kind == "written"  # a WEAK stamp is never a coverage gap
            assert outcome.verification_status == VerificationStatus.UNVERIFIED.value
            claim = (await _live_overviews(conn, contact))[0]
            assert claim.identity_binding is IdentityBinding.WEAK
            assert not can_be_promoted(claim)
            assert len(judge.calls) == 1  # it was judged; promotion was refused, not skipped

            scope = WorkspaceScope.for_workspace("tenant-a")
            assert (contact, CONTACT_OVERVIEW) not in await current_values(
                conn, [contact], [CONTACT_OVERVIEW], scope=scope
            )
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            assert (contact, CONTACT_OVERVIEW) not in await current_values(
                conn, [contact], [CONTACT_OVERVIEW], scope=scope
            )

    run_async(_run())
