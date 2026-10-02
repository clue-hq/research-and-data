"""PC-C8 §6c — quote-by-text location and judge-gated typed values, at the engine seam.

Every fixture here is derived from the 2026-08-01 live acceptance run
(`_memory/2026-08-01-c8-acceptance-run.md`), which produced two families of honest-but-costly
refusals:

* **12 × "quote offsets fall outside the captured answer"** on long, bulleted turns — the model
  authored character offsets into a message it never echoed back. Those failures are impossible by
  construction once the model copies the span and the engine locates it (§6c-a);
* **8 × "claim value is not textually entailed by the exact interview quote"** — every one a true
  fact the client had stated plainly ("we are fully HIPAA compliant"; "we support SOAP, APSO, and
  H&P formats"), refused because a boolean or a list can never be a substring of prose. Those are
  now the entailment judge's question (§6c-b), and the claims that pass carry a distinct
  ``source_key`` so provenance says *how* they earned entry.

The judge is stubbed deterministically: a live LLM call does not belong in this suite, and the
real M9.3-backed wrapper has its own contract test in ``tests/api/test_c8_claim_entailment.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    OnboardingInputKind,
    PassKind,
    ReuseScope,
)
from clue_research.claimstore import WorkspaceScope, claims_by_ids, register_field
from clue_research.identity import insert_account_entity
from clue_research.stage0 import (
    SOURCE_CLIENT_INTERVIEW,
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    ClaimEntailment,
    InterviewEvidenceRefused,
    InterviewRoute,
    InterviewStatement,
    is_judged_value,
    locate_quote,
    route_interview_answer,
    submit_onboarding_input,
)
from clue_research.stage0.fields import CLIENT_PACK, CLIENT_VALUE_PROP
from clue_research.verification import (
    DEFAULT_CORROBORATION_POLICY,
    EqualityMode,
    independent_source_count,
    values_agree,
)
from clue_spine import create_brand, create_product, create_project
from clue_storage import artifact_key as make_artifact_key
from clue_storage import record_artifact
from tests._run_lineage import assert_written_claims_are_attributable
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")

_WORKSPACE = "c8-evidence-ergonomics"

# The client pack registers no boolean or string-list field today, and §6c-b is not the place to
# decide which client facts deserve one (that changes reverse-profiling coverage). The typed
# targets are therefore registered here, the way the platform intends new fields to arrive —
# registry rows, not a forked pipeline (conventions §2). The registry's value-schema check is what
# makes this necessary at all, and it is the honest live constraint too: a typed interview value
# needs a registered field whose schema accepts that JSON type.
BOOL_FIELD = "client.hipaa_compliant"
LIST_FIELD = "client.document_formats"


async def _register_typed_client_fields(conn: AsyncConnection) -> None:
    for field_key, schema in (
        (BOOL_FIELD, {"type": "boolean"}),
        (LIST_FIELD, {"type": "array", "items": {"type": "string"}}),
    ):
        await register_field(
            conn,
            FieldDef(
                field_key=field_key,
                value_type="bool" if schema["type"] == "boolean" else "list",
                tier_plan=(),
                pass_kind=PassKind.DEEP,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
            ),
            value_schema=schema,
            pack=CLIENT_PACK,
        )


# The exact turn shape that failed 12× live: a preamble plus bullets, long enough that offset
# arithmetic drifts and structured enough that the model rewrites punctuation while "quoting".
BULLETED_ANSWER = (
    "Here's the fuller picture of who we sell to and why it matters:\n"
    "- We target independent U.S. neurosurgery practices with 2-15 neurosurgeons.\n"
    "- We are fully HIPAA compliant, and every deployment is BAA-backed.\n"
    "- We support SOAP, APSO, and H&P formats out of the box.\n"
    "- The champion is usually the practice administrator, who owns scheduling throughput.\n"
    "- Hospital-employed departments are explicitly out of scope for this campaign."
)

HIPAA_QUOTE = "We are fully HIPAA compliant, and every deployment is BAA-backed."
FORMATS_QUOTE = "We support SOAP, APSO, and H&P formats out of the box."
TARGET_QUOTE = "We target independent U.S. neurosurgery practices with 2-15 neurosurgeons."


@dataclass
class _StubJudge:
    """A deterministic ``ClaimEntailmentJudge``: answers from a table, records every question.

    Keyed on ``(field_key, value, quote)`` — the same content the real wrapper content-addresses —
    so a test can prove that changing the quote asks a *different* question.
    """

    verdicts: dict[tuple[str, str, str], ClaimEntailment] = field(default_factory=dict)
    default: ClaimEntailment = ClaimEntailment(supported=True, verdict="supported", score=0.95)
    asked: list[tuple[str, JsonValue, str]] = field(default_factory=list)

    async def entails(
        self,
        *,
        workspace_id: str,
        entity_id: EntityId,
        field_key: str,
        value: JsonValue,
        quote: str,
    ) -> ClaimEntailment:
        del workspace_id
        self.asked.append((field_key, value, quote))
        return self.verdicts.get((field_key, repr(value), quote), self.default)


@dataclass(frozen=True)
class _Turn:
    """One captured turn, ready to route against."""

    brand_id: str
    product_id: str
    project_id: str
    client: EntityId
    onboarding_input_id: object
    artifact_key: str
    answer: str


async def _capture(conn: AsyncConnection, answer: str, *, suffix: str = "") -> _Turn:
    await _register_typed_client_fields(conn)
    brand = await create_brand(conn, workspace_id=_WORKSPACE, name=f"Ergonomics{suffix}")
    product = await create_product(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        name=f"Ergonomics product{suffix}",
    )
    project = await create_project(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        name=f"Ergonomics project{suffix}",
    )
    client = await insert_account_entity(
        conn,
        canonical_name=f"Ergonomics Client{suffix}",
        primary_domain=f"ergonomics{suffix or '0'}.example",
        workspace_id=_WORKSPACE,
        status=AccountStatus.ACTIVE,
    )
    digest = hashlib.sha256(answer.encode()).hexdigest()
    key = make_artifact_key(_WORKSPACE, digest)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=_WORKSPACE,
        content_sha256=digest,
        media_type="text/plain",
        size_bytes=len(answer.encode()),
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        client_entity_id=client,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=key,
        content_sha256=digest,
        actor="human",
    )
    return _Turn(
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client=client,
        onboarding_input_id=captured.onboarding_input_id,
        artifact_key=key,
        answer=answer,
    )


async def _route(
    conn: AsyncConnection,
    turn: _Turn,
    *statements: InterviewStatement,
    judge: object | None = None,
) -> object:
    return await route_interview_answer(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=turn.brand_id,
        product_id=turn.product_id,
        project_id=turn.project_id,
        client_entity_id=turn.client,
        onboarding_input_id=turn.onboarding_input_id,  # type: ignore[arg-type]
        artifact_key=turn.artifact_key,
        answer=turn.answer,
        statements=statements,
        actor="human",
        entailment_judge=judge,  # type: ignore[arg-type]
    )


async def _statement_rows(conn: AsyncConnection) -> list[dict[str, object]]:
    rows = (
        await conn.execute(
            text(
                "SELECT route_key, quote_start, quote_end, quote_sha256, onboarding_input_id "
                "FROM volunteered_statement WHERE workspace_id = :ws ORDER BY route_key"
            ),
            {"ws": _WORKSPACE},
        )
    ).mappings()
    return [dict(row) for row in rows]


# --- (a) quote-by-text ------------------------------------------------------


def test_locate_quote_is_exact_character_domain_and_never_approximate() -> None:
    """The whole of §6c-a's location rule, with no DB in the way."""

    answer = "We ship to café owners 🎯 and the administrators own scheduling."
    start, end = locate_quote(answer, quote="administrators")
    # Character offsets, past both multi-byte characters: a byte-domain search lands 5 short.
    assert (start, end) == (answer.index("administrators"), answer.index("administrators") + 14)
    assert answer[start:end] == "administrators"
    assert start != answer.encode().index(b"administrators")

    # Nothing fuzzy: a retyped span is simply absent.
    with pytest.raises(InterviewEvidenceRefused) as retyped:
        locate_quote(answer, quote="Administrators")
    assert retyped.value.reason_code == "quote_not_found_verbatim"
    assert "copy the span exactly" in str(retyped.value).casefold()

    with pytest.raises(InterviewEvidenceRefused) as blank:
        locate_quote(answer, quote="   ")
    assert blank.value.reason_code == "interview_quote_empty"


def test_locate_quote_defaults_to_the_first_occurrence_and_counts_the_rest() -> None:
    answer = "we ship fast. we ship fast. we ship fast."
    assert locate_quote(answer, quote="we ship fast") == (0, 12)
    assert locate_quote(answer, quote="we ship fast", occurrence=1) == (0, 12)
    assert locate_quote(answer, quote="we ship fast", occurrence=3) == (28, 40)

    with pytest.raises(InterviewEvidenceRefused) as beyond:
        locate_quote(answer, quote="we ship fast", occurrence=4)
    assert beyond.value.reason_code == "quote_not_found_verbatim"
    assert "only 3 time(s)" in str(beyond.value)

    # A blank quote can never make the occurrence loop spin: it is refused first.
    with pytest.raises(InterviewEvidenceRefused):
        locate_quote(answer, quote="", occurrence=9)

    # Unreachable through the schema (`ge=1`), but the public function refuses it as the caller
    # error it is rather than reporting a present span as absent.
    with pytest.raises(ValueError, match="1-based"):
        locate_quote(answer, quote="we ship fast", occurrence=0)


def test_a_long_bulleted_turn_lands_every_span_the_offsets_used_to_miss() -> None:
    """The 12-failure replay: three spans out of a long bulleted message, all located exactly."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, BULLETED_ANSWER)
            result = await _route(
                conn,
                turn,
                InterviewStatement(
                    route=InterviewRoute.PROJECT_STATE,
                    route_key="a_target_market",
                    quote=TARGET_QUOTE,
                ),
                InterviewStatement(
                    route=InterviewRoute.PROJECT_STATE,
                    route_key="b_champion",
                    quote="The champion is usually the practice administrator",
                ),
                InterviewStatement(
                    route=InterviewRoute.PROJECT_STATE,
                    route_key="c_exclusion",
                    quote="Hospital-employed departments are explicitly out of scope",
                ),
            )
            assert len(result.statement_ids) == 3  # type: ignore[attr-defined]

            rows = await _statement_rows(conn)
            expected = [
                TARGET_QUOTE,
                "The champion is usually the practice administrator",
                "Hospital-employed departments are explicitly out of scope",
            ]
            for row, quote in zip(rows, expected, strict=True):
                start = BULLETED_ANSWER.index(quote)
                assert (row["quote_start"], row["quote_end"]) == (start, start + len(quote))
                assert BULLETED_ANSWER[row["quote_start"] : row["quote_end"]] == quote
                assert row["quote_sha256"] == hashlib.sha256(quote.encode()).hexdigest()

    run_async(_run())


def test_a_retyped_span_is_refused_with_repair_feedback_and_writes_nothing() -> None:
    """Fail-closed, all-or-nothing: statement one is quotable, statement two is not."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, BULLETED_ANSWER)
            with pytest.raises(InterviewEvidenceRefused) as refused:
                await _route(
                    conn,
                    turn,
                    InterviewStatement(
                        route=InterviewRoute.PROJECT_STATE,
                        route_key="a_target_market",
                        quote=TARGET_QUOTE,
                    ),
                    InterviewStatement(
                        route=InterviewRoute.PROJECT_STATE,
                        route_key="b_formats",
                        # Tidied: an en dash for the hyphen and a dropped "out of the box".
                        quote="We support SOAP, APSO and H&P formats",
                    ),
                )
            assert refused.value.reason_code == "quote_not_found_verbatim"
            assert "copy the span exactly" in str(refused.value).casefold()
            # The first statement was quotable, but validation precedes every write.
            assert await _statement_rows(conn) == []

    run_async(_run())


def test_a_repeated_span_locks_onto_the_occurrence_the_model_names() -> None:
    async def _run() -> None:
        answer = "We are growing. We are growing. That is the whole story."
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, answer)
            await _route(
                conn,
                turn,
                InterviewStatement(
                    route=InterviewRoute.PROJECT_STATE,
                    route_key="a_first",
                    quote="We are growing",
                ),
                InterviewStatement(
                    route=InterviewRoute.PROJECT_STATE,
                    route_key="b_second",
                    quote="We are growing",
                    occurrence=2,
                ),
            )
            rows = await _statement_rows(conn)
            assert [(row["quote_start"], row["quote_end"]) for row in rows] == [(0, 14), (16, 30)]
            # Position is metadata; the evidence bytes are identical either way.
            assert rows[0]["quote_sha256"] == rows[1]["quote_sha256"]

    run_async(_run())


def test_two_byte_identical_turns_each_locate_into_their_own_capture() -> None:
    """F1-adjacent: repeats bind their own turn, and located offsets ride that binding.

    The live F1 fix keyed the captured-turn cache on the turn rather than its bytes. Location is
    downstream of that binding — it searches *the answer the binding produced* — so the guarantee
    has to survive here too: two byte-identical answers give two statements under two different
    onboarding inputs, with identical spans.
    """

    async def _run() -> None:
        answer = "Note this for the record: the champion wants faster clinic throughput."
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            first = await _capture(conn, answer)
            second = await _capture(conn, answer, suffix="-2")
            assert first.onboarding_input_id != second.onboarding_input_id
            assert first.artifact_key == second.artifact_key  # content-addressed

            statement = InterviewStatement(
                route=InterviewRoute.PROJECT_STATE,
                route_key="champion_desired_outcome",
                quote="the champion wants faster clinic throughput",
            )
            one = await _route(conn, first, statement)
            two = await _route(conn, second, statement)

            assert one.statement_ids != two.statement_ids  # type: ignore[attr-defined]
            rows = await _statement_rows(conn)
            assert len(rows) == 2
            assert {row["onboarding_input_id"] for row in rows} == {
                first.onboarding_input_id,
                second.onboarding_input_id,
            }
            assert {(row["quote_start"], row["quote_end"]) for row in rows} == {(26, 69)}
            assert len({row["quote_sha256"] for row in rows}) == 1

    run_async(_run())


# --- (b) judge-gated typed values -------------------------------------------


def test_is_judged_value_discriminates_on_the_json_type_and_nothing_else() -> None:
    assert is_judged_value(True) is True
    assert is_judged_value(False) is True
    assert is_judged_value(12) is True
    assert is_judged_value(1.5) is True
    assert is_judged_value(["SOAP", "APSO", "H&P"]) is True
    assert is_judged_value({"formats": 3}) is True
    assert is_judged_value(None) is True
    # A JSON string is text the client can have said, so it keeps the substring rule — including
    # the string "true", which is a different value from the boolean.
    assert is_judged_value("revenue clarity") is False
    assert is_judged_value("true") is False


def test_the_hipaa_boolean_lands_as_a_judged_claim_with_its_own_source_key() -> None:
    """Acceptance refusal #1, replayed: a true fact, plainly stated, no longer refused."""

    async def _run() -> None:
        judge = _StubJudge()
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, BULLETED_ANSWER)
            result = await _route(
                conn,
                turn,
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=BOOL_FIELD,
                    quote=HIPAA_QUOTE,
                    entity_type=EntityType.ACCOUNT,
                    field_key=BOOL_FIELD,
                    value=True,
                ),
                judge=judge,
            )
            assert judge.asked == [(BOOL_FIELD, True, HIPAA_QUOTE)]
            (claim_id,) = result.claim_refs  # type: ignore[attr-defined]
            claim = (
                await claims_by_ids(
                    conn,
                    (ClaimId(claim_id),),
                    scope=WorkspaceScope.private_for_workspace(_WORKSPACE),
                )
            )[ClaimId(claim_id)]
            assert claim.value_json is True
            # The method stamp: same conversation, same tier, different way of earning entry.
            assert claim.source_key == SOURCE_CLIENT_INTERVIEW_JUDGED
            assert claim.source_tier == 1
            assert claim.extraction_method is ExtractionMethod.HUMAN
            # The evidence is still the verbatim span, not the judge's opinion about it.
            assert claim.evidence_span == HIPAA_QUOTE
            # FI-2 P2: the interview turn's run is a workspace-level stage-0 run (no project).
            await assert_written_claims_are_attributable(
                conn,
                claim.run_id,
                kind="stage0",
                workspace_id=_WORKSPACE,
                project_id=None,
            )

    run_async(_run())


def test_the_document_format_list_lands_as_a_judged_claim() -> None:
    """Acceptance refusal #2, replayed: ``["SOAP", "APSO", "H&P"]`` from one sentence."""

    async def _run() -> None:
        judge = _StubJudge()
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, BULLETED_ANSWER)
            result = await _route(
                conn,
                turn,
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=LIST_FIELD,
                    quote=FORMATS_QUOTE,
                    entity_type=EntityType.ACCOUNT,
                    field_key=LIST_FIELD,
                    value=["SOAP", "APSO", "H&P"],
                ),
                judge=judge,
            )
            (claim_id,) = result.claim_refs  # type: ignore[attr-defined]
            claim = (
                await claims_by_ids(
                    conn,
                    (ClaimId(claim_id),),
                    scope=WorkspaceScope.private_for_workspace(_WORKSPACE),
                )
            )[ClaimId(claim_id)]
            assert claim.value_json == ["SOAP", "APSO", "H&P"]
            assert claim.source_key == SOURCE_CLIENT_INTERVIEW_JUDGED
            assert claim.evidence_span == FORMATS_QUOTE

    run_async(_run())


def test_a_text_value_never_reaches_the_judge_and_lands_exactly_as_before() -> None:
    """The string-literal path is byte-for-byte the pre-§6c one — the fixture is the whole row."""

    async def _run() -> None:
        judge = _StubJudge()
        answer = "Our value proposition is revenue clarity."
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, answer)
            result = await _route(
                conn,
                turn,
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=CLIENT_VALUE_PROP,
                    quote=answer,
                    entity_type=EntityType.ACCOUNT,
                    field_key=CLIENT_VALUE_PROP,
                    value="revenue clarity",
                ),
                judge=judge,
            )
            assert judge.asked == []  # the judge is not even consulted
            (claim_id,) = result.claim_refs  # type: ignore[attr-defined]
            claim = (
                await claims_by_ids(
                    conn,
                    (ClaimId(claim_id),),
                    scope=WorkspaceScope.private_for_workspace(_WORKSPACE),
                )
            )[ClaimId(claim_id)]
            assert {
                "value_json": claim.value_json,
                "source_key": claim.source_key,
                "source_url": claim.source_url,
                "source_tier": claim.source_tier,
                "extraction_method": claim.extraction_method,
                "evidence_span": claim.evidence_span,
                "confidence": claim.confidence,
                "entity_id": claim.entity_id,
                "artifact_key": claim.artifact_key,
            } == {
                "value_json": "revenue clarity",
                "source_key": SOURCE_CLIENT_INTERVIEW,
                "source_url": f"interview://{turn.onboarding_input_id}",
                "source_tier": 1,
                "extraction_method": ExtractionMethod.HUMAN,
                "evidence_span": answer,
                "confidence": 1.0,
                "entity_id": turn.client,
                "artifact_key": turn.artifact_key,
            }

            # And a paraphrase is still refused by the substring rule, not by the judge.
            with pytest.raises(InterviewEvidenceRefused) as refused:
                await _route(
                    conn,
                    turn,
                    InterviewStatement(
                        route=InterviewRoute.CLAIM,
                        route_key="paraphrase",
                        quote=answer,
                        entity_type=EntityType.ACCOUNT,
                        field_key=CLIENT_VALUE_PROP,
                        value="clarity about revenue",
                    ),
                    judge=judge,
                )
            assert refused.value.reason_code == "claim_value_not_entailed"
            assert judge.asked == []

    run_async(_run())


def test_typed_value_without_a_judge_is_admitted_unjudged_r0() -> None:
    """R0 ruling (ARV2-R0-foundations-plan Part 3C fix 1): no judge composed != refusal.

    This test held the opposite until 2026-09-01, and that was the kill-switch inversion: with
    `CLUE_VERIFICATION_ENABLED=false` no entailment judge is composed, so every boolean/number/
    list/object Client-KB fact was refused outright and the interview could only accept the
    client's own words. An unwired judge now admits the typed value UNJUDGED, exactly like the
    substring path admits a string — the claim lands under the plain `client_interview` source key
    and is born UNVERIFIED, which is the durable record that no judge ran. A judge that IS wired
    but cannot be reached stays a retryable refusal (an outage is transient, not a posture) — that
    is `test_a_judge_that_cannot_be_reached_is_reported_as_unavailable_not_as_disbelief`.
    """

    async def _run() -> None:
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, BULLETED_ANSWER)
            result = await _route(
                conn,
                turn,
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=BOOL_FIELD,
                    quote=HIPAA_QUOTE,
                    entity_type=EntityType.ACCOUNT,
                    field_key=BOOL_FIELD,
                    value=True,
                ),
            )
            (claim_id,) = result.claim_refs  # type: ignore[attr-defined]
            claim = (
                await claims_by_ids(
                    conn,
                    (ClaimId(claim_id),),
                    scope=WorkspaceScope.private_for_workspace(_WORKSPACE),
                )
            )[ClaimId(claim_id)]
            assert claim.value_json is True
            assert claim.evidence_span == HIPAA_QUOTE
            # Not judge-admitted, so it must NOT carry the judged provenance key.
            assert claim.source_key == SOURCE_CLIENT_INTERVIEW
            assert claim.source_key != SOURCE_CLIENT_INTERVIEW_JUDGED
            # The statement was durably recorded rather than discarded by a refusal.
            assert [row["route_key"] for row in await _statement_rows(conn)] == [BOOL_FIELD]

            # Unchanged behaviour pin: the string substring rule still refuses a non-substring
            # string with no judge in play. Dropping the judge relaxes the typed path only.
            with pytest.raises(InterviewEvidenceRefused) as refused:
                await _route(
                    conn,
                    turn,
                    InterviewStatement(
                        route=InterviewRoute.CLAIM,
                        route_key="paraphrase",
                        quote=HIPAA_QUOTE,
                        entity_type=EntityType.ACCOUNT,
                        field_key=CLIENT_VALUE_PROP,
                        value="a paraphrase nobody said",
                    ),
                )
            assert refused.value.reason_code == "claim_value_not_entailed"

    run_async(_run())


def test_an_unsupported_verdict_refuses_and_a_re_quote_is_a_different_question() -> None:
    """Repair has to work: the judgment is asked about the *content*, not about the claim id.

    Both attempts here target the same ``(turn, entity, field)`` — so they would share one
    interview claim id — but they cite different spans, and the second must be able to succeed.
    """

    async def _run() -> None:
        judge = _StubJudge(
            verdicts={
                (BOOL_FIELD, repr(True), TARGET_QUOTE): ClaimEntailment(
                    supported=False, verdict="unsupported", score=0.1
                )
            }
        )
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, BULLETED_ANSWER)

            def statement(quote: str) -> InterviewStatement:
                return InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=BOOL_FIELD,
                    quote=quote,
                    entity_type=EntityType.ACCOUNT,
                    field_key=BOOL_FIELD,
                    value=True,
                )

            with pytest.raises(InterviewEvidenceRefused) as refused:
                await _route(conn, turn, statement(TARGET_QUOTE), judge=judge)
            assert refused.value.reason_code == "claim_value_not_entailed"
            assert "'unsupported'" in str(refused.value)
            assert await _statement_rows(conn) == []

            result = await _route(conn, turn, statement(HIPAA_QUOTE), judge=judge)
            assert len(result.claim_refs) == 1  # type: ignore[attr-defined]
            assert [asked[2] for asked in judge.asked] == [TARGET_QUOTE, HIPAA_QUOTE]

    run_async(_run())


def test_a_judge_that_cannot_be_reached_is_reported_as_unavailable_not_as_disbelief() -> None:
    async def _run() -> None:
        judge = _StubJudge(default=ClaimEntailment(supported=False, verdict="unavailable"))
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            turn = await _capture(conn, BULLETED_ANSWER)
            with pytest.raises(InterviewEvidenceRefused) as refused:
                await _route(
                    conn,
                    turn,
                    InterviewStatement(
                        route=InterviewRoute.CLAIM,
                        route_key=BOOL_FIELD,
                        quote=HIPAA_QUOTE,
                        entity_type=EntityType.ACCOUNT,
                        field_key=BOOL_FIELD,
                        value=True,
                    ),
                    judge=judge,
                )
            assert refused.value.reason_code == "claim_value_judge_unavailable"
            assert "could not be reached" in str(refused.value)

    run_async(_run())


def test_one_conversation_is_one_source_however_its_values_earned_entry() -> None:
    """The invariant the §6c-b source-key split rests on (see `interview._write_claim`).

    `independent_source_count` unifies claims that share a `source_url` host **or** a `source_key`.
    Two turns of one conversation carry different `interview://<onboarding_input_id>` hosts, so
    `source_key` is the only thing preventing the client's own repetition from corroborating
    itself — and §6c-b split that key in two. This is safe only because the two species can never
    co-group: the byte-literal path's value is a JSON string by construction and the judged path's
    never is, and `values_agree` equates nothing across JSON types. Both halves are asserted here,
    so if `is_judged_value` or `values_agree` moves, this fails instead of the interview quietly
    becoming its own corroboration.
    """

    async def _run() -> None:
        judge = _StubJudge()
        answer = "Our value proposition is revenue clarity."
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            first = await _capture(conn, answer)
            second = await _capture(conn, answer, suffix="-2")
            third = await _capture(conn, answer, suffix="-3")

            def literal(field: str) -> InterviewStatement:
                return InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=field,
                    quote=answer,
                    entity_type=EntityType.ACCOUNT,
                    field_key=field,
                    value="revenue clarity",
                )

            one = await _route(conn, first, literal(CLIENT_VALUE_PROP), judge=judge)
            two = await _route(conn, second, literal(CLIENT_VALUE_PROP), judge=judge)
            judged = await _route(
                conn,
                third,
                InterviewStatement(
                    route=InterviewRoute.CLAIM,
                    route_key=BOOL_FIELD,
                    quote=answer,
                    entity_type=EntityType.ACCOUNT,
                    field_key=BOOL_FIELD,
                    value=True,
                ),
                judge=judge,
            )
            ids = (
                *one.claim_refs,  # type: ignore[attr-defined]
                *two.claim_refs,  # type: ignore[attr-defined]
                *judged.claim_refs,  # type: ignore[attr-defined]
            )
            claims = await claims_by_ids(
                conn,
                tuple(ClaimId(i) for i in ids),
                scope=WorkspaceScope.private_for_workspace(_WORKSPACE),
            )
            byte_literal = [c for c in claims.values() if c.source_key == SOURCE_CLIENT_INTERVIEW]
            judged_claims = [
                c for c in claims.values() if c.source_key == SOURCE_CLIENT_INTERVIEW_JUDGED
            ]
            assert len(byte_literal) == 2 and len(judged_claims) == 1
            # Two different turns: different hosts, so only the shared source_key unifies them.
            assert len({c.source_url for c in byte_literal}) == 2
            assert independent_source_count(byte_literal) == 1

            # The load-bearing half: the two species cannot share a value group under ANY equality
            # mode, so their different source_keys can never be counted inside one group.
            for mode in EqualityMode:
                assert not values_agree(
                    byte_literal[0].value_json,
                    judged_claims[0].value_json,
                    mode=mode,
                    policy=DEFAULT_CORROBORATION_POLICY,
                )
            # Stated as the property it protects: were they ever to co-group, this would be 2.
            assert independent_source_count([byte_literal[0], judged_claims[0]]) == 2

    run_async(_run())
