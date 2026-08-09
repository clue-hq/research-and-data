"""Lane E E1 (WP-A) — the on-completion prose synthesizer (`account.summary`).

The pure machinery (the versioned prompt, the empty-beats-fabricated parser, the policy shape)
runs in ``make check`` with no DB; :class:`ProseSynthesizer` behaviour is exercised against a live
Postgres (skips without one, like the M12 positioner suite) because it reads the merge view and
writes an ``account.summary`` claim + its ``claim_support`` row.

Charter: ``docs/specs/FI-lane-E-on-completion-synthesis.md`` §2.3-§2.7.
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
    EntityId,
    ExtractionMethod,
    JudgeResult,
    JudgeVerdict,
    Message,
    ResearchMode,
    ReuseScope,
    RunId,
    VerificationStatus,
    account_claim,
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
from clue_research.identity import DEFAULT_REUSE_POLICY, insert_account_entity, stamp_reuse
from clue_research.narrative import ACCOUNT_SUMMARY, load_prose_pack, read_claim_support
from clue_research.narrative.prompts import AccountFact, fact_to_text
from clue_research.narrative.prose import (
    ACCOUNT_SUMMARY_PROMPT_VERSION,
    DEFAULT_PROSE_POLICY,
    GAP_INSUFFICIENT_FACTS,
    GAP_UNGROUNDED_SYNTHESIS,
    METRIC_PROSE_COVERAGE_GAP,
    METRIC_PROSE_JUDGE_SKIPPED,
    METRIC_PROSE_PRODUCED,
    PROSE_ACCOUNT_FIELDS,
    PROSE_PROMPTS,
    ProseOutcome,
    ProsePolicy,
    ProseSynthesizer,
    build_account_summary_messages,
    parse_prose_response,
)
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
        from clue_core import VerificationStatus
        from clue_research.claimstore import record_verification

        self.calls.append(claim)
        status = {
            JudgeVerdict.SUPPORTED: VerificationStatus.VERIFIED,
            JudgeVerdict.PARTIAL: VerificationStatus.FLAGGED,
            JudgeVerdict.UNSUPPORTED: VerificationStatus.REJECTED,
            JudgeVerdict.CONTRADICTED: VerificationStatus.REJECTED,
        }[self._verdict]
        await record_verification(self._conn, claim.id, status=status)
        return JudgeResult(claim_id=claim.id, verdict=self._verdict, score=self._score)


@asynccontextmanager
async def prose_conn() -> AsyncIterator[AsyncConnection]:
    """``rollback_conn`` plus the Lane E prose pack (so ``account.summary`` resolves) and the M8.2
    deep-profiling pack (so the ``account.resonance.*`` half of :data:`PROSE_ACCOUNT_FIELDS`
    resolves — only ``resonance.culture`` lives in ``CORE_PACK``). The shared harness loads the
    core + M12 narrative packs only."""
    async with rollback_conn() as conn:
        await load_prose_pack(conn)
        await load_deep_profiling_pack(conn)
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
    sink: InMemorySink | None = None,
) -> tuple[ProseSynthesizer, FakeGateway]:
    gateway = FakeGateway(response)
    return (
        ProseSynthesizer(
            gateway=gateway,
            judge=judge,
            policy=policy,
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
