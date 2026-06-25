"""M9.3 (ENG-139) — faithfulness judge: LLM-as-judge claim-level entailment.

Every §M9.3 acceptance criterion has a dedicated test. The pure machinery (prompt assembly, response
parsing, the verdict→status rule, the re-retrieval predicate) runs without a database (in ``make
check``); the ``FaithfulnessJudgeImpl.judge`` behaviour is exercised against a live Postgres (skips
without one, like the M9.1/M9.2 suites) because it reads/writes the ``faithfulness_verdict`` cache,
the ``judge_policy`` config, and the ``claim.verification_status`` verdict.

The LLM call is exercised with a deterministic **fake gateway** that returns canned JSON — the real
``StubGateway`` returns ``stub:<digest>`` (not a parseable verdict), by design (the stub is not a
real judge). The fake records its calls so "zero LLM calls" / caching / model-swap are assertable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import insert_claim, register_field
from clue_research.core import (
    AccountStatus,
    Claim,
    ClaimId,
    Completion,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    JudgeVerdict,
    Message,
    PassKind,
    ResearchMode,
    UseClass,
    VerificationStatus,
    new_entity_id,
    new_run_id,
)
from clue_research.identity import insert_account_entity
from clue_research.obs import (
    SPAN_VERIFICATION_FAITHFULNESS_JUDGE,
    InMemorySink,
    collect_spans,
)
from clue_research.verification import (
    DEFAULT_JUDGE_POLICY,
    PROMPT_VERSION,
    PROMPTS,
    FaithfulnessJudgeImpl,
    JudgePolicy,
    ParsedVerdict,
    build_judge_messages,
    needs_re_retrieval,
    parse_judge_response,
    status_for_verdict,
)
from clue_research.verification.faithfulness import (
    METRIC_FAITHFULNESS_JUDGMENTS,
    METRIC_FAITHFULNESS_RE_RETRIEVAL,
    METRIC_FAITHFULNESS_SUPPORTED,
)

from .conftest import rollback_conn, run_async

# --- a deterministic fake gateway (records calls; returns canned JSON) -------


class FakeGateway:
    """A deterministic :class:`~clue_research.core.gateway.LLMGateway` for the judge tests: returns
    one canned response and records every ``complete`` call (model + messages) so the test can
    assert *which* model was called and *how many times* (caching / no-call / model-swap)."""

    def __init__(
        self,
        response_text: str,
        *,
        cost_cents: Decimal = Decimal("0.5"),
        answering_model: str | None = None,
    ) -> None:
        self._response = response_text
        self._cost = cost_cents
        # When set, the completion reports a DIFFERENT model than the one requested — simulating an
        # OpenRouter fallback so the test can assert ``answering_model`` is recorded distinctly from
        # the requested ``judge_model`` (the cache key).
        self._answering_model = answering_model
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, list(messages)))
        return Completion(
            model=self._answering_model or model,
            text=self._response,
            cost_cents=self._cost,
            finish_reason="stop",
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError("the faithfulness judge never embeds")


_SUPPORTED = '{"verdict": "supported", "score": 0.92, "rationale": "the span states the value"}'
_UNSUPPORTED = (
    '{"verdict": "unsupported", "score": 0.08, "rationale": "the span does not state it"}'
)
_CONTRADICTED = '{"verdict": "contradicted", "score": 0.03, "rationale": "the span says otherwise"}'
_PARTIAL = '{"verdict": "partial", "score": 0.55, "rationale": "the span supports part of it"}'


def _claim(
    *,
    value: object = "Snowflake",
    tier: int = 4,
    span: str | None = "Acme runs its warehouse on Snowflake.",
    entity_id: EntityId | None = None,
    entity_type: EntityType = EntityType.ACCOUNT,
    field_key: str = "account.synth",
    identity_binding: IdentityBinding | None = None,
    use_class: UseClass | None = None,
    status: VerificationStatus = VerificationStatus.UNVERIFIED,
) -> Claim:
    """Build an in-memory claim. Tier-4 ⇒ llm_synthesis (+ a source_url); lower tiers ⇒ scrape."""
    method = ExtractionMethod.LLM_SYNTHESIS if tier == 4 else ExtractionMethod.SCRAPE
    return Claim(
        entity_id=entity_id or new_entity_id(),
        entity_type=entity_type,
        field_key=field_key,
        value_json=value,  # type: ignore[arg-type]
        source_url="https://llm.local/x" if tier == 4 else "https://a.com/x",
        source_key="exa_deep" if tier == 4 else "exa",
        source_tier=tier,  # type: ignore[arg-type]
        extraction_method=method,
        evidence_span=span,
        confidence=0.9,  # type: ignore[arg-type]
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        identity_binding=identity_binding,
        use_class=use_class,
        verification_status=status,
    )


# --- pure unit (no DB) ------------------------------------------------------


def test_parse_supported_partial_unsupported_contradicted() -> None:
    assert parse_judge_response(_SUPPORTED).verdict is JudgeVerdict.SUPPORTED
    assert parse_judge_response(_PARTIAL).verdict is JudgeVerdict.PARTIAL
    assert parse_judge_response(_UNSUPPORTED).verdict is JudgeVerdict.UNSUPPORTED
    assert parse_judge_response(_CONTRADICTED).verdict is JudgeVerdict.CONTRADICTED
    assert parse_judge_response(_SUPPORTED).score == pytest.approx(0.92)


def test_parse_tolerates_prose_and_fences() -> None:
    fenced = 'Here is my judgment:\n```json\n{"verdict": "supported", "score": 0.8}\n```\nDone.'
    parsed = parse_judge_response(fenced)
    assert parsed.verdict is JudgeVerdict.SUPPORTED and parsed.score == pytest.approx(0.8)


def test_parse_unparseable_is_conservative_unsupported() -> None:
    # an unparseable judgment must never promote (empty beats fabricated): it is unsupported.
    assert parse_judge_response("stub:deadbeef").verdict is JudgeVerdict.UNSUPPORTED
    assert parse_judge_response("stub:deadbeef").score == 0.0
    assert parse_judge_response("").verdict is JudgeVerdict.UNSUPPORTED
    assert parse_judge_response('{"verdict": "bananas"}').verdict is JudgeVerdict.UNSUPPORTED


def test_parse_missing_or_bad_score_defaults_by_verdict() -> None:
    # a supported verdict with no score defaults high; unsupported defaults to 0.
    assert parse_judge_response('{"verdict": "supported"}').score == 1.0
    assert parse_judge_response('{"verdict": "unsupported"}').score == 0.0
    # a bool score is not a number → default by verdict; an out-of-range score clamps into [0,1].
    assert parse_judge_response('{"verdict": "partial", "score": true}').score == 0.5
    assert parse_judge_response('{"verdict": "supported", "score": 5}').score == 1.0
    assert parse_judge_response('{"verdict": "supported", "score": -3}').score == 0.0


def test_build_messages_is_claim_level_not_document_level() -> None:
    # the judge prompt carries ONLY the field/value/span — never a wider document (claim-level).
    claim = _claim(value="Snowflake", span="Acme uses Snowflake.")
    messages = build_judge_messages(claim, prompt_version=PROMPT_VERSION)
    assert messages[0].role.value == "system" and "ON ITS OWN" in messages[0].content
    user = messages[1].content
    assert "account.synth" in user and "Snowflake" in user and "Acme uses Snowflake." in user
    assert "DOCUMENT" not in user.upper()  # only the EVIDENCE SPAN, no wider doc


def test_build_messages_unknown_version_raises() -> None:
    with pytest.raises(ValueError, match="unknown faithfulness prompt_version"):
        build_judge_messages(_claim(), prompt_version="v999")


def test_prompt_registry_has_current_version() -> None:
    assert PROMPT_VERSION in PROMPTS and PROMPTS[PROMPT_VERSION]


def test_needs_re_retrieval() -> None:
    assert needs_re_retrieval(JudgeVerdict.UNSUPPORTED)
    assert needs_re_retrieval(JudgeVerdict.CONTRADICTED)
    assert not needs_re_retrieval(JudgeVerdict.SUPPORTED)
    assert not needs_re_retrieval(JudgeVerdict.PARTIAL)


def test_status_for_verdict_rule() -> None:
    claim = _claim(tier=4)  # promotable tier-4 (has span)
    supported = ParsedVerdict(verdict=JudgeVerdict.SUPPORTED, score=0.92)
    partial = ParsedVerdict(verdict=JudgeVerdict.PARTIAL, score=0.55)
    unsupported = ParsedVerdict(verdict=JudgeVerdict.UNSUPPORTED, score=0.08)
    contradicted = ParsedVerdict(verdict=JudgeVerdict.CONTRADICTED, score=0.03)
    assert (
        status_for_verdict(supported, claim, supported_threshold=0.7) is VerificationStatus.VERIFIED
    )
    assert status_for_verdict(partial, claim, supported_threshold=0.7) is VerificationStatus.FLAGGED
    assert (
        status_for_verdict(unsupported, claim, supported_threshold=0.7)
        is VerificationStatus.REJECTED
    )
    assert (
        status_for_verdict(contradicted, claim, supported_threshold=0.7)
        is VerificationStatus.REJECTED
    )
    # supported but below threshold → leave unchanged (not a fabrication, just not promoted).
    low = ParsedVerdict(verdict=JudgeVerdict.SUPPORTED, score=0.5)
    assert status_for_verdict(low, claim, supported_threshold=0.7) is None


def test_status_for_verdict_weak_binding_not_promoted() -> None:
    # a weak-binding contact claim is not promotable (M9.4's axis) → supported does not promote.
    weak = _claim(
        tier=4,
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.hobby",
        identity_binding=IdentityBinding.WEAK,
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    )
    supported = ParsedVerdict(verdict=JudgeVerdict.SUPPORTED, score=0.95)
    assert status_for_verdict(supported, weak, supported_threshold=0.7) is None


def test_judge_policy_defaults() -> None:
    assert DEFAULT_JUDGE_POLICY.prompt_version == PROMPT_VERSION
    assert 0.0 <= DEFAULT_JUDGE_POLICY.supported_threshold <= 1.0
    assert DEFAULT_JUDGE_POLICY.judge_model  # a non-empty gateway model id


# --- DB-gated behaviour -----------------------------------------------------


def _judge(
    conn: AsyncConnection,
    gateway: FakeGateway,
    *,
    policy: JudgePolicy = DEFAULT_JUDGE_POLICY,
    sink: InMemorySink | None = None,
) -> FaithfulnessJudgeImpl:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return FaithfulnessJudgeImpl(gateway=gateway, policy=policy, conn_factory=factory, sink=sink)


async def _account(conn: AsyncConnection) -> EntityId:
    return await insert_account_entity(  # type: ignore[return-value]
        conn, canonical_name="Acme", primary_domain="acme.com", status=AccountStatus.ACTIVE
    )


async def _register(conn: AsyncConnection, field_key: str = "account.synth") -> None:
    await register_field(
        conn,
        FieldDef(field_key=field_key, value_type="str", pass_kind=PassKind.DEEP),
        corroboration_min=1,
    )


async def _status(conn: AsyncConnection, claim_id: ClaimId) -> str:
    row = (
        await conn.execute(
            text("SELECT verification_status FROM claim WHERE id = :id"), {"id": claim_id}
        )
    ).first()
    assert row is not None
    return row[0]


async def _verdict_rows(conn: AsyncConnection, claim_id: ClaimId) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM faithfulness_verdict WHERE claim_id = :id"),
                {"id": claim_id},
            )
        ).scalar_one()
    )


async def _pg_enum_labels(conn: AsyncConnection, type_name: str) -> set[str]:
    result = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid WHERE t.typname = :n"
        ),
        {"n": type_name},
    )
    return set(result.scalars().all())


@pytest.mark.usefixtures("require_verification_db")
def test_judge_verdict_enum_matches_core() -> None:
    """The DB judge_verdict enum stays in lock-step with core.JudgeVerdict (drift guard)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = await _pg_enum_labels(conn, "judge_verdict")
        assert labels == {v.value for v in JudgeVerdict}

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_no_span_tier4_rejected_with_zero_llm_calls() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity, span=None)  # tier-4, no evidence_span
            await insert_claim(conn, claim)
            gateway = FakeGateway(_SUPPORTED)  # would say supported if ever called
            result = await _judge(conn, gateway).judge(claim)
            assert gateway.calls == []  # structural pre-check: ZERO LLM calls
            assert result.verdict is JudgeVerdict.UNSUPPORTED
            assert await _status(conn, claim.id) == "rejected"
            assert await _verdict_rows(conn, claim.id) == 1

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_fabrication_rejected_and_emits_re_retrieval_never_verified() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            sink = InMemorySink()
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(
                entity_id=entity
            )  # value NOT entailed by its span (the judge will say so)
            await insert_claim(conn, claim)
            gateway = FakeGateway(_UNSUPPORTED)
            result = await _judge(conn, gateway, sink=sink).judge(claim)
            assert len(gateway.calls) == 1
            assert result.verdict is JudgeVerdict.UNSUPPORTED
            assert await _status(conn, claim.id) == "rejected"  # never verified
            assert sink.counter(METRIC_FAITHFULNESS_RE_RETRIEVAL, field_key="account.synth") == 1

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_contradicted_rejected() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            result = await _judge(conn, FakeGateway(_CONTRADICTED)).judge(claim)
            assert result.verdict is JudgeVerdict.CONTRADICTED
            assert await _status(conn, claim.id) == "rejected"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_entailed_supported_promotes_tier4_to_verified() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            sink = InMemorySink()
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)  # value entailed by its span
            await insert_claim(conn, claim)
            result = await _judge(conn, FakeGateway(_SUPPORTED), sink=sink).judge(claim)
            assert result.verdict is JudgeVerdict.SUPPORTED
            # the judge is the terminal accuracy gate for tier-4 (corroboration leaves tier-4 to it,
            # and merge admits a tier-4 claim only when verified) → supported promotes to verified.
            assert await _status(conn, claim.id) == "verified"
            assert sink.counter(METRIC_FAITHFULNESS_SUPPORTED, field_key="account.synth") == 1

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_partial_flagged_for_review() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            result = await _judge(conn, FakeGateway(_PARTIAL)).judge(claim)
            assert result.verdict is JudgeVerdict.PARTIAL
            assert await _status(conn, claim.id) == "flagged"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_supported_below_threshold_left_unverified() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            # supported but score 0.5 < the default 0.7 threshold → not promoted, not rejected.
            low = '{"verdict": "supported", "score": 0.5, "rationale": "weakish"}'
            await _judge(conn, FakeGateway(low)).judge(claim)
            assert await _status(conn, claim.id) == "unverified"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_non_tier4_claim_judged_but_status_untouched() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            # a tier-3 claim handed to the judge: it records a verdict but must NOT mutate status
            # (tier≤3 status is corroboration's domain — one judge-supported tier-3 claim must not
            # bypass corroboration_min).
            claim = _claim(entity_id=entity, tier=3, span="Acme uses Snowflake.")
            await insert_claim(conn, claim)
            await _judge(conn, FakeGateway(_SUPPORTED)).judge(claim)
            assert await _status(conn, claim.id) == "unverified"  # untouched
            assert await _verdict_rows(conn, claim.id) == 1  # but the verdict is recorded

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_rejudge_is_cached_and_prompt_bump_forces_fresh() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            gateway = FakeGateway(_SUPPORTED)
            judge = _judge(conn, gateway)
            first = await judge.judge(claim)
            second = await judge.judge(
                claim
            )  # same (claim, model, prompt) → cache hit, no 2nd call
            assert len(gateway.calls) == 1
            assert first.verdict == second.verdict and second.verdict is JudgeVerdict.SUPPORTED
            assert await _verdict_rows(conn, claim.id) == 1  # no new row

            # bump prompt_version → cache miss → a fresh LLM call and a new row.
            PROMPTS["v-test"] = PROMPTS[PROMPT_VERSION]
            try:
                bumped = _judge(conn, gateway, policy=JudgePolicy(prompt_version="v-test"))
                await bumped.judge(claim)
            finally:
                del PROMPTS["v-test"]
            assert len(gateway.calls) == 2  # fresh judgment
            assert await _verdict_rows(conn, claim.id) == 2

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_model_swap_changes_the_model_called_no_code_change() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            gateway = FakeGateway(_SUPPORTED)
            policy = JudgePolicy(judge_model="anthropic/claude-3-haiku")
            await _judge(conn, gateway, policy=policy).judge(claim)
            assert gateway.calls and gateway.calls[0][0] == "anthropic/claude-3-haiku"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_span_emitted_with_model_prompt_score_cost_latency() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            await _judge(conn, FakeGateway(_SUPPORTED)).judge(claim)

    with collect_spans() as exporter:
        run_async(_run())
    spans = [
        s for s in exporter.get_finished_spans() if s.name == SPAN_VERIFICATION_FAITHFULNESS_JUDGE
    ]
    assert spans, "the faithfulness judge must emit its dedicated span"
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("model")
    assert attrs.get("verification.faithfulness.prompt_version") == PROMPT_VERSION
    assert attrs.get("verification.faithfulness.verdict") == "supported"
    assert "verification.faithfulness.score" in attrs
    assert "cost_cents" in attrs and "latency_ms" in attrs


@pytest.mark.usefixtures("require_verification_db")
def test_claim_level_not_document_level_span_unsupported() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            # the value is true in the wider world / document but the CITED span does not state it;
            # the judge (fed only the span) returns unsupported → rejected, never verified.
            claim = _claim(
                entity_id=entity,
                value="Series C funding",
                span="Acme was founded in 2014 in Denver.",  # says nothing about funding
            )
            await insert_claim(conn, claim)
            result = await _judge(conn, FakeGateway(_UNSUPPORTED)).judge(claim)
            assert result.verdict is JudgeVerdict.UNSUPPORTED
            assert await _status(conn, claim.id) == "rejected"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_idempotent_rejudge_writes_no_new_rows_and_keeps_status() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            judge = _judge(conn, FakeGateway(_UNSUPPORTED))
            await judge.judge(claim)
            status1 = await _status(conn, claim.id)
            rows1 = await _verdict_rows(conn, claim.id)
            await judge.judge(claim)
            assert await _status(conn, claim.id) == status1 == "rejected"
            assert await _verdict_rows(conn, claim.id) == rows1 == 1

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_load_judge_policy_per_client_then_global_then_default() -> None:
    async def _run() -> None:
        from clue_research.verification import load_judge_policy

        async with rollback_conn() as conn:
            # no rows → built-in default.
            assert await load_judge_policy(conn) == DEFAULT_JUDGE_POLICY
            # a global row is read when no client row matches.
            await conn.execute(
                text(
                    "INSERT INTO judge_policy "
                    "(policy_id, client_id, judge_model, prompt_version, supported_threshold) "
                    "VALUES ('global', NULL, 'm/global', 'v1', 0.6)"
                )
            )
            glob = await load_judge_policy(conn, client_id="acme")
            assert glob.judge_model == "m/global" and glob.supported_threshold == pytest.approx(0.6)
            # a per-client row wins over the global one.
            await conn.execute(
                text(
                    "INSERT INTO judge_policy "
                    "(policy_id, client_id, judge_model, prompt_version, supported_threshold) "
                    "VALUES ('acme', 'acme', 'm/acme', 'v1', 0.8)"
                )
            )
            cli = await load_judge_policy(conn, client_id="acme")
            assert cli.judge_model == "m/acme" and cli.supported_threshold == pytest.approx(0.8)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_metrics_judgments_counter_emitted() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            sink = InMemorySink()
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            await _judge(conn, FakeGateway(_SUPPORTED), sink=sink).judge(claim)
            assert sink.counter(METRIC_FAITHFULNESS_JUDGMENTS, field_key="account.synth") == 1

    run_async(_run())


# --- parse robustness (no DB) — the greedy-regex defect the audit found ------


def test_parse_object_then_trailing_prose_with_brace() -> None:
    # a real judge appends reasoning; a trailing `}` must not drop a clearly-supported verdict.
    resp = '{"verdict": "supported", "score": 0.9}\nReasoning: the value {Snowflake} matches.'
    assert parse_judge_response(resp).verdict is JudgeVerdict.SUPPORTED


def test_parse_two_objects_returns_first() -> None:
    resp = '{"verdict": "unsupported", "score": 0.1} {"verdict": "supported", "score": 0.9}'
    assert parse_judge_response(resp).verdict is JudgeVerdict.UNSUPPORTED  # the first object wins


def test_parse_brace_in_prose_before_object() -> None:
    # a stray brace BEFORE the object must be skipped, not derail extraction.
    resp = 'note {here}: {"verdict": "supported", "score": 0.95}'
    assert parse_judge_response(resp).verdict is JudgeVerdict.SUPPORTED


def test_judge_verdict_migration_tuple_matches_core() -> None:
    """Pure no-DB drift guard (runs in ``make check``): the migration's hand-copied verdict tuple
    must equal ``core.JudgeVerdict`` exactly AND in order — mirroring the M9.2 static conflict-tier
    guard, so a label or ordering drift fails the build loudly without a database."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/911a1beeb9c1_m9_3_faithfulness_judge_tables.py"
    )
    spec = importlib.util.spec_from_file_location("_m93_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert tuple(v.value for v in JudgeVerdict) == module._JUDGE_VERDICT


# --- status transitions from a non-UNVERIFIED start (judge owns tier-4) ------


@pytest.mark.usefixtures("require_verification_db")
def test_flagged_claim_promoted_to_verified_on_supported() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity, status=VerificationStatus.FLAGGED)
            await insert_claim(conn, claim)
            await _judge(conn, FakeGateway(_SUPPORTED)).judge(claim)
            assert await _status(conn, claim.id) == "verified"  # FLAGGED → VERIFIED on supported

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_verified_claim_demoted_to_rejected_on_unsupported() -> None:
    # the judge must be able to DEMOTE a previously-promoted tier-4 value — the "bad base facts
    # never overwritten" anti-pattern, here exercised in the demote direction (substrate §0/§1).
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity, status=VerificationStatus.VERIFIED)
            await insert_claim(conn, claim)
            await _judge(conn, FakeGateway(_UNSUPPORTED)).judge(claim)
            assert await _status(conn, claim.id) == "rejected"  # VERIFIED → REJECTED on unsupported

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_verdict_row_content_persists_and_replays() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            judge = _judge(conn, FakeGateway(_SUPPORTED, cost_cents=Decimal("0.5")))
            first = await judge.judge(claim)
            row = (
                await conn.execute(
                    text(
                        "SELECT verdict, score, rationale, judge_model, prompt_version, "
                        "cost_cents, latency_ms, answering_model "
                        "FROM faithfulness_verdict WHERE claim_id = :id"
                    ),
                    {"id": claim.id},
                )
            ).first()
            assert row is not None
            assert row[0] == "supported"
            assert row[1] == pytest.approx(0.92)
            assert row[2]  # a non-empty rationale persisted
            assert row[3] == DEFAULT_JUDGE_POLICY.judge_model
            assert row[4] == PROMPT_VERSION
            assert row[5] == Decimal("0.5")
            assert row[6] is not None  # latency recorded
            # no fallback configured → the model that answered == the requested judge_model.
            assert row[7] == DEFAULT_JUDGE_POLICY.judge_model
            # the cache replay reconstructs the same JudgeResult from the row (no second LLM call).
            second = await judge.judge(claim)
            assert second.verdict is first.verdict
            assert second.score == pytest.approx(first.score)
            assert second.cost_cents == first.cost_cents and second.rationale == first.rationale

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_answering_model_records_fallback_distinct_from_cache_key() -> None:
    """[M9.3×M12] When the gateway falls back (the completion reports a different model than the one
    requested), the verdict row records the **answering** model in ``answering_model`` while
    ``judge_model`` stays the requested id — so the cache key is stable across the fallback and a
    re-judge is still a cache hit (no duplicate row), yet M12.2 cites the model that actually
    answered."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity)
            await insert_claim(conn, claim)
            gateway = FakeGateway(_SUPPORTED, answering_model="anthropic/claude-3-opus-fallback")
            judge = _judge(conn, gateway)
            await judge.judge(claim)
            rows = (
                await conn.execute(
                    text(
                        "SELECT judge_model, answering_model FROM faithfulness_verdict "
                        "WHERE claim_id = :id"
                    ),
                    {"id": claim.id},
                )
            ).all()
            assert len(rows) == 1  # one row keyed on the REQUESTED model
            assert rows[0][0] == DEFAULT_JUDGE_POLICY.judge_model  # cache key = requested
            assert rows[0][1] == "anthropic/claude-3-opus-fallback"  # cited = answered
            # re-judge: cache hit on the (claim, requested judge_model, prompt) key → still one row.
            await judge.judge(claim)
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM faithfulness_verdict WHERE claim_id = :id"),
                    {"id": claim.id},
                )
            ).scalar()
            assert count == 1
            # the M12.2 citation reader reports the answering model (read via the narrative seam).
            from clue_research.narrative import read_faithfulness_citation

            citation = await read_faithfulness_citation(conn, claim.id)
            assert citation is not None
            assert citation.answering_model == "anthropic/claude-3-opus-fallback"
            assert citation.judge_model == DEFAULT_JUDGE_POLICY.judge_model
            assert citation.verdict == "supported"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_answering_model_for_span_less_claim_is_the_requested_model() -> None:
    """A span-less tier-4 claim is auto-``unsupported`` with ZERO LLM calls (no completion exists),
    so ``answering_model`` is, correctly, the requested ``judge_model`` (no fallback could occur) —
    never NULL."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity, span=None)  # tier-4, no evidence_span
            await insert_claim(conn, claim)
            gateway = FakeGateway(_SUPPORTED)
            judge = _judge(conn, gateway)
            await judge.judge(claim)
            assert gateway.calls == []  # the kill switch: no LLM call
            row = (
                await conn.execute(
                    text(
                        "SELECT verdict, answering_model FROM faithfulness_verdict "
                        "WHERE claim_id = :id"
                    ),
                    {"id": claim.id},
                )
            ).first()
            assert row is not None
            assert row[0] == "unsupported"
            assert row[1] == DEFAULT_JUDGE_POLICY.judge_model

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_unregistered_prompt_version_falls_back_to_default() -> None:
    # a stale/typo prompt_version in a config row must degrade to the default prompt at load time,
    # never raise per-claim mid-spend.
    async def _run() -> None:
        from clue_research.verification import load_judge_policy

        async with rollback_conn() as conn:
            await conn.execute(
                text(
                    "INSERT INTO judge_policy "
                    "(policy_id, client_id, judge_model, prompt_version, supported_threshold) "
                    "VALUES ('global', NULL, 'm/global', 'v-retired-999', 0.7)"
                )
            )
            policy = await load_judge_policy(conn)
            assert policy.judge_model == "m/global"  # the row is still honoured...
            assert (
                policy.prompt_version == DEFAULT_JUDGE_POLICY.prompt_version
            )  # ...prompt falls back

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_no_span_path_emits_span_with_zero_calls() -> None:
    # acceptance criterion 1's "emits the span" sub-clause, on the structural no-span path.
    gateway = FakeGateway(_SUPPORTED)

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn)
            claim = _claim(entity_id=entity, span=None)
            await insert_claim(conn, claim)
            await _judge(conn, gateway).judge(claim)

    with collect_spans() as exporter:
        run_async(_run())
    assert gateway.calls == []  # zero LLM calls on the no-span path
    spans = [
        s for s in exporter.get_finished_spans() if s.name == SPAN_VERIFICATION_FAITHFULNESS_JUDGE
    ]
    assert spans, "the no-span path must still emit the dedicated span"
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("verification.faithfulness.verdict") == "unsupported"
    # M9-local span attrs go through the obs redaction path, which stringifies bools ("True"); the
    # standard ``cache_hit`` key is coerced natively (bool preserved). Accept either coercion.
    assert attrs.get("verification.faithfulness.re_retrieval") in (True, "True")
    assert attrs.get("cache_hit") in (False, "False")
