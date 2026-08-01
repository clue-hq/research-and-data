"""PC-C8 task 1.1 — the Stage-0 project card compiler (``clue_projections.stage0``).

What this suite pins, and why each matters:

* **determinism** — identical durable state plus an identical policy version compile byte-identical
  bytes and the same sha256. That is the whole basis for content-addressed card reuse across turns
  (spec §3 "Determinism", AC-8's in-process half; the cross-restart half is the api-side hash test);
* **every §3.1 cap and its overflow path** — statement count, per-quote bytes, aggregate quote
  bytes, per-KB-brief bytes, aggregate KB bytes, the omission-list cap, and the whole-card cap.
  A cap without an exercised overflow path is a number in a docstring, not a bound;
* **AC-1's shape** — a breadth fixture (well over the cap, maximum-length quotes, oversized KB
  values) compiles to ≤ 24,000 bytes *with correct omissions*: the card is bounded by construction
  at any ledger size, which is the defect the whole slice exists to fix;
* **selection order** — dedup → supersession → newest-first, so the bound drops the least
  load-bearing statements and the card names the order it actually used;
* **honest absence** — missing evidence is surfaced as a typed omission, never silently dropped;
  a gate with no lineage-current authoritative decision says so rather than showing a stale verdict
  (AC-2); a human override is applied through the *shared* helper ``stage0_readiness`` also uses;
* **fail-closed scoping** — a cross-workspace compile raises (AC-10).

The evidence port is injected as a test double here on purpose: that is the proof it is genuinely
inverted (the projection layer may not import storage). The artifact-backed implementation, its
verbatim-quote guarantee and its erasure semantics are covered in
``tests/api/test_c8_statement_evidence.py``.

DB-backed; every test runs inside an always-rolled-back transaction and skips without a reachable
``CLUE_DATABASE_URL``, so ``make check`` stays green without one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import DEFAULT_STAGE0_POLICY
from clue_core import (
    EntityId,
    OnboardingInputId,
    OnboardingInputKind,
    ReadinessDecisionId,
    ReadinessGate,
    VolunteeredStatementId,
)
from clue_projections.stage0 import (
    NOT_EVALUATED_FOR_CURRENT_LINEAGE,
    STAGE0_CARD_POLICY_V1,
    STATEMENT_SELECTION_ORDER,
    ExcludedEvidence,
    ExcludedEvidenceReason,
    ResolvedQuote,
    Stage0CardOmission,
    Stage0CardOmissionKind,
    Stage0CardPolicy,
    Stage0CardTooLarge,
    Stage0ProjectCard,
    compile_stage0_project_card,
    decode_card_cursor,
)
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    ClientInput,
    StatementRoute,
    VolunteeredMaterial,
    VolunteeredStatementRow,
    evaluate_readiness,
    override_readiness,
    read_readiness_decisions,
    read_statements,
    record_statement,
    reverse_profile,
    submit_onboarding_input,
)
from clue_spine import create_brand, create_product, create_project
from clue_storage import record_artifact
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_ROUTE_KEYS = (
    "campaign_goal_and_target_scope",
    "target_segment",
    "buying_committee_shape",
    "channel_preference",
)


class _FakeEvidence:
    """A ``StatementEvidenceReader`` double: a quote per statement id, or a missing-evidence id.

    Exists to prove the port is genuinely injected — the compiler resolves quotes through whatever
    the composition root hands it and never reaches storage itself.
    """

    def __init__(
        self,
        *,
        quotes: dict[str, str] | None = None,
        default: str = "we target neurosurgery practices",
        missing: frozenset[str] = frozenset(),
    ) -> None:
        self._quotes = quotes or {}
        self._default = default
        self._missing = missing

    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow
    ) -> ResolvedQuote | ExcludedEvidence:
        del workspace_id
        if str(statement.id) in self._missing:
            return ExcludedEvidence(
                statement_id=statement.id,
                reason=ExcludedEvidenceReason.ARTIFACT_MISSING,
            )
        return ResolvedQuote(
            statement_id=statement.id,
            quote=self._quotes.get(str(statement.id), self._default),
        )

    async def resolve_quotes(
        self, *, workspace_id: str, statements: Sequence[VolunteeredStatementRow]
    ) -> tuple[ResolvedQuote | ExcludedEvidence, ...]:
        return tuple(
            [
                await self.resolve_quote(workspace_id=workspace_id, statement=row)
                for row in statements
            ]
        )


class _Scope:
    """The durable Stage-0 identities one card is compiled over."""

    def __init__(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        product_id: str,
        project_id: str,
        client_entity_id: EntityId,
        client_kb_version: int,
    ) -> None:
        self.workspace_id = workspace_id
        self.brand_id = brand_id
        self.product_id = product_id
        self.project_id = project_id
        self.client_entity_id = client_entity_id
        self.client_kb_version = client_kb_version


async def _seed_scope(
    conn: AsyncConnection,
    *,
    suffix: str,
    confirm_product: bool = True,
    materials: tuple[VolunteeredMaterial, ...] = (),
) -> _Scope:
    """A workspace/brand/product/project + a versioned Client KB, all in one rolled-back txn."""

    workspace_id = f"c8-card-{suffix}"
    await seed_workspace(conn, workspace_id)
    brand = await create_brand(conn, workspace_id=workspace_id, name=f"Aura {suffix}")
    product = await create_product(
        conn, workspace_id=workspace_id, brand_id=brand.brand_id, name="Aura ABM"
    )
    project = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id if confirm_product else None,
        name="Aura Stage 0",
    )
    profiled = await reverse_profile(
        conn,
        ClientInput(
            name=f"Aura AI {suffix}",
            website=f"https://aura-{suffix}.invalid",
            materials=materials,
        ),
        workspace_id=workspace_id,
        product_id=product.product_id,
        budget_cap_cents=Decimal(0),
        max_source_tier=0,
    )
    return _Scope(
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client_entity_id=profiled.ref.client_entity_id,
        client_kb_version=profiled.ref.client_kb_version,
    )


async def _record_turn(
    conn: AsyncConnection,
    scope: _Scope,
    *,
    index: int,
    route_key: str | None = None,
    route_kind: StatementRoute = StatementRoute.PROJECT_STATE,
    corrects: VolunteeredStatementId | None = None,
) -> VolunteeredStatementId:
    """One captured turn plus its routed statement — what a live Stage-0 turn durably writes."""

    body = f"turn {index} body".encode()
    digest = hashlib.sha256(body).hexdigest()
    key = f"{scope.workspace_id}/{digest}"
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=scope.workspace_id,
        content_sha256=digest,
        media_type="text/plain",
        size_bytes=len(body),
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=scope.workspace_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        client_entity_id=scope.client_entity_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=key,
        content_sha256=digest,
        actor="human",
        onboarding_input_id=OnboardingInputId(
            uuid5(NAMESPACE_URL, f"c8-card:{scope.project_id}:input:{index}:{route_kind.value}")
        ),
    )
    return await record_statement(
        conn,
        onboarding_input_id=captured.onboarding_input_id,
        workspace_id=scope.workspace_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        client_entity_id=scope.client_entity_id,
        entity_id=scope.client_entity_id,
        route_kind=route_kind,
        route_key=route_key or _ROUTE_KEYS[index % len(_ROUTE_KEYS)],
        quote=f"quote {index}",
        quote_start=0,
        quote_end=7,
        created_by_actor="agent",
        correction_of_id=corrects,
    )


async def _record_decision(
    conn: AsyncConnection,
    scope: _Scope,
    *,
    index: int,
    gate: ReadinessGate = ReadinessGate.ICP_SYNTHESIS,
    client_kb_version: int | None = None,
    actor: str = "system",
    metrics: dict[str, object] | None = None,
) -> ReadinessDecisionId:
    ref = await evaluate_readiness(
        conn,
        workspace_id=scope.workspace_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        client_entity_id=scope.client_entity_id,
        client_kb_version=(
            client_kb_version if client_kb_version is not None else scope.client_kb_version
        ),
        gate=gate,
        spec=DEFAULT_STAGE0_POLICY.readiness,
        metrics=metrics or {"project_state_statements": index, "verified_claims": 0},  # type: ignore[arg-type]
        created_by_actor=actor,
        readiness_decision_id=ReadinessDecisionId(
            uuid5(NAMESPACE_URL, f"c8-card:{scope.project_id}:readiness:{gate.value}:{index}")
        ),
    )
    return ref.readiness_decision_id


async def _compile(
    conn: AsyncConnection,
    scope: _Scope,
    *,
    evidence: _FakeEvidence | None = None,
    policy: Stage0CardPolicy = STAGE0_CARD_POLICY_V1,
    workspace_id: str | None = None,
    **kwargs: object,
) -> Stage0ProjectCard:
    return await compile_stage0_project_card(
        project_id=scope.project_id,
        workspace_id=workspace_id or scope.workspace_id,
        client_entity_id=scope.client_entity_id,
        client_kb_version=scope.client_kb_version,
        product_id=scope.product_id,
        evidence=evidence or _FakeEvidence(),
        policy=policy,
        conn_factory=conn_session_factory(conn),
        **kwargs,  # type: ignore[arg-type]
    )


def _omission(card: Stage0ProjectCard, kind: Stage0CardOmissionKind) -> Stage0CardOmission | None:
    return next((item for item in card.omissions if item.kind is kind), None)


# --- determinism -------------------------------------------------------------


def test_two_compiles_of_the_same_state_are_byte_identical() -> None:
    """Same durable state + same policy version ⇒ same bytes ⇒ same sha256.

    This is what makes the card content-addressable: an unchanged project across turns re-uses one
    artifact instead of writing a new one every turn (spec §3, AC-8/AC-9).
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"det{uuid4().hex[:6]}")
            for index in range(3):
                await _record_turn(conn, scope, index=index)
            await _record_decision(conn, scope, index=3)

            first = await _compile(conn, scope)
            second = await _compile(conn, scope)

            assert first.canonical_bytes() == second.canonical_bytes()
            assert first.content_sha256() == second.content_sha256()
            # canonical: sorted keys, no NaN, and no null fields left in the body
            payload = json.loads(first.canonical_bytes())
            assert list(payload) == sorted(payload)
            assert None not in payload.values()

    run_async(_run())


def test_the_policy_version_participates_in_the_card_bytes() -> None:
    """A cap change is a *visible* card change — policy is data, and the data is in the artifact."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"pol{uuid4().hex[:6]}")
            await _record_turn(conn, scope, index=0)

            default = await _compile(conn, scope)
            relabelled = await _compile(
                conn,
                scope,
                policy=STAGE0_CARD_POLICY_V1.model_copy(update={"version": "test-policy-v9"}),
            )

            assert relabelled.compiler_policy_version == "test-policy-v9"
            assert relabelled.compiled_from.compiler_policy_version == "test-policy-v9"
            assert relabelled.content_sha256() != default.content_sha256()

    run_async(_run())


# --- AC-1: the card is bounded by construction -------------------------------


def test_a_breadth_conversation_compiles_under_the_card_cap_with_correct_omissions() -> None:
    """AC-1: 60 distinct effective statements with maximum-length quotes and oversized KB values
    compile to ≤ 24,000 bytes — and the card says exactly how much it left out.

    The pre-C8 path grew ~2.3 KB per material turn and blew a 48,000-byte layer budget around turn
    20. The bound here is structural, not a hope: the compiler sheds statements until the canonical
    bytes fit, and every shed statement is counted into ``omissions``.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(
                conn,
                suffix=f"breadth{uuid4().hex[:6]}",
                materials=(
                    VolunteeredMaterial(
                        kind="deck",
                        label="pitch.pdf",
                        content="Everything about Aura.",
                        asserted_fields=dict.fromkeys(CLIENT_KNOWLEDGE_FIELDS, "x" * 4000),
                    ),
                ),
            )
            statements = 60
            for index in range(statements):
                await _record_turn(conn, scope, index=index, route_key=f"route_{index}")
            for index in range(30):
                await _record_decision(conn, scope, index=index)

            # A distinct maximum-length quote per statement (no dedup, no aggregate slack).
            rows = await read_statements(
                conn, workspace_id=scope.workspace_id, project_id=scope.project_id
            )
            quotes = {str(row.id): f"{index} " + "q" * 2_000 for index, row in enumerate(rows)}
            card = await _compile(conn, scope, evidence=_FakeEvidence(quotes=quotes))

            size = len(card.canonical_bytes())
            assert size <= STAGE0_CARD_POLICY_V1.max_card_bytes, size
            included = card.interview.selection.included
            assert included <= STAGE0_CARD_POLICY_V1.max_statements
            assert card.interview.selection.total_effective == statements
            over_cap = _omission(card, Stage0CardOmissionKind.STATEMENTS_OVER_CAP)
            assert over_cap is not None
            assert over_cap.count == statements - included
            # the ledger is not resident: latest-per-gate only, the rest reachable by cursor
            assert card.readiness.ledger_length == 30
            assert len(card.readiness.latest_by_gate) == 1
            history = _omission(card, Stage0CardOmissionKind.READINESS_HISTORY)
            assert history is not None
            assert history.count == 29
            # every quote is truncated at the per-quote cap, and says so
            assert all(item.quote_truncated for item in card.interview.current_effective_statements)
            assert all(
                len(item.quoted_text.encode()) <= STAGE0_CARD_POLICY_V1.max_quote_bytes
                for item in card.interview.current_effective_statements
            )

    run_async(_run())


def test_the_card_carries_no_raw_row_payload() -> None:
    """AC-5's projection half: a statement entry is six named fields, not a ``to_jsonb(row)`` dump.

    The pre-C8 snapshot shipped every column — tenancy ids, hashes, timestamps — repeated per row,
    and *zero bytes of the quoted text*: oversized and unreadable at once.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"shape{uuid4().hex[:6]}")
            await _record_turn(conn, scope, index=0)
            card = await _compile(conn, scope)

            payload = json.loads(card.canonical_bytes())
            (entry,) = payload["interview"]["current_effective_statements"]
            assert set(entry) <= {
                "statement_id",
                "route_key",
                "route_kind",
                "quoted_text",
                "quote_truncated",
                "supersedes",
            }
            # tenancy is compiled once in the identity frame, never repeated per row
            assert "workspace_id" not in entry
            assert "quote_sha256" not in entry
            assert entry["quoted_text"]  # the words the model actually needs

    run_async(_run())


# --- the §3.1 caps, one overflow path each -----------------------------------


def test_an_oversized_quote_truncates_at_a_utf8_boundary() -> None:
    """Truncation never splits a codepoint, and it is marked so the reader knows to go look."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"utf8{uuid4().hex[:6]}")
            statement = await _record_turn(conn, scope, index=0)
            # 999 ASCII bytes then a 3-byte character straddling the 1,000-byte cap.
            quote = "a" * 999 + "éé"
            card = await _compile(
                conn, scope, evidence=_FakeEvidence(quotes={str(statement): quote})
            )

            (entry,) = card.interview.current_effective_statements
            assert entry.quote_truncated is True
            assert entry.quoted_text == "a" * 999  # the split character is dropped whole
            assert len(entry.quoted_text.encode()) <= STAGE0_CARD_POLICY_V1.max_quote_bytes

    run_async(_run())


def test_the_aggregate_quote_cap_reduces_the_statement_count() -> None:
    """Below the 40-statement cap the aggregate byte cap still bites — newest-first survives."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"agg{uuid4().hex[:6]}")
            for index in range(12):
                await _record_turn(conn, scope, index=index, route_key=f"route_{index}")
            policy = STAGE0_CARD_POLICY_V1.model_copy(
                update={"version": "test-agg-v1", "max_quote_total_bytes": 300}
            )
            card = await _compile(
                conn,
                scope,
                evidence=_FakeEvidence(default="z" * 100),
                policy=policy,
            )

            assert card.interview.selection.included == 3  # 300 / 100
            assert card.interview.selection.total_effective == 12
            over_cap = _omission(card, Stage0CardOmissionKind.STATEMENTS_OVER_CAP)
            assert over_cap is not None and over_cap.count == 9

    run_async(_run())


def test_a_client_knowledge_brief_is_capped_per_field_and_in_aggregate() -> None:
    """A brief is a reading aid; the claim ref beside it is how the exact value is recovered."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(
                conn,
                suffix=f"kb{uuid4().hex[:6]}",
                materials=(
                    VolunteeredMaterial(
                        kind="deck",
                        label="pitch.pdf",
                        content="Everything about Aura.",
                        asserted_fields=dict.fromkeys(CLIENT_KNOWLEDGE_FIELDS, "v" * 1000),
                    ),
                ),
            )
            card = await _compile(conn, scope)

            assert card.client_knowledge.known_fields
            for field in card.client_knowledge.known_fields:
                assert field.brief_truncated is True
                assert len(field.brief_value.encode()) <= STAGE0_CARD_POLICY_V1.max_kb_brief_bytes
                assert field.claim_id  # the exact value is one claim read away

            # and the aggregate cap bites before the per-field one runs out of fields
            tight = STAGE0_CARD_POLICY_V1.model_copy(
                update={"version": "test-kb-v1", "max_kb_total_bytes": 600}
            )
            bounded = await _compile(conn, scope, policy=tight)
            assert len(bounded.client_knowledge.known_fields) < len(
                card.client_knowledge.known_fields
            )
            withheld = _omission(bounded, Stage0CardOmissionKind.CLIENT_KNOWLEDGE_OVER_CAP)
            assert withheld is not None

    run_async(_run())


def test_the_omission_list_itself_collapses_when_it_overflows() -> None:
    """Even the honesty surface is bounded: the overflow becomes one honest counter, not a list."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(
                conn,
                suffix=f"omit{uuid4().hex[:6]}",
                materials=(
                    VolunteeredMaterial(
                        kind="deck",
                        label="pitch.pdf",
                        content="Everything about Aura.",
                        asserted_fields=dict.fromkeys(CLIENT_KNOWLEDGE_FIELDS, "v" * 1000),
                    ),
                ),
            )
            statements = [await _record_turn(conn, scope, index=index) for index in range(6)]
            await _record_decision(conn, scope, index=0)
            await _record_decision(conn, scope, index=1)
            policy = STAGE0_CARD_POLICY_V1.model_copy(
                update={
                    "version": "test-omit-v1",
                    "max_statements": 2,
                    "max_kb_total_bytes": 600,
                    "max_omissions": 2,
                }
            )
            card = await _compile(
                conn,
                scope,
                evidence=_FakeEvidence(missing=frozenset({str(statements[0])})),
                policy=policy,
            )

            assert len(card.omissions) == 2
            collapsed = card.omissions[-1]
            assert collapsed.kind is Stage0CardOmissionKind.OMISSIONS_TRUNCATED
            assert collapsed.count >= 1
            assert collapsed.cursor is None

    run_async(_run())


def test_oversized_readiness_evidence_cannot_starve_the_interview_section() -> None:
    """Readiness evidence is bounded *before* the fit loop, so it sheds itself and not the words.

    Without the per-gate cap the shed order inverts: three gates carrying 6 KB of caller-supplied
    metrics each consume the whole card budget, the fit loop drops every statement, and the model
    is handed a zero-quote card — the exact unreadable-context defect this slice exists to fix.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"rdyb{uuid4().hex[:6]}")
            for index in range(10):
                await _record_turn(conn, scope, index=index, route_key=f"route_{index}")
            for gate in ReadinessGate:
                await _record_decision(
                    conn,
                    scope,
                    index=0,
                    gate=gate,
                    metrics={
                        "coverage_ratio": 0.5,
                        "verified_claims": 2,
                        "project_state_statements": 10,
                        # a caller-supplied blob an unbounded card would happily serialize
                        "diagnostic_trace": ["t" * 100] * 60,
                    },
                )

            card = await _compile(conn, scope)

            assert len(card.readiness.latest_by_gate) == 3
            for entry in card.readiness.latest_by_gate:
                evidence_bytes = len(
                    json.dumps(
                        {"metrics": entry.metrics, "reason_codes": list(entry.reason_codes)},
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                )
                assert evidence_bytes <= STAGE0_CARD_POLICY_V1.max_gate_evidence_bytes
                assert entry.evidence_truncated is True
                # the load-bearing summary keys survive; only the blob is dropped
                assert entry.metrics["coverage_ratio"] == 0.5
                assert entry.metrics["project_state_statements"] == 10
                assert "diagnostic_trace" not in entry.metrics
            # and the interview section is intact: the words were never the thing to shed
            assert card.interview.selection.included == 10
            assert len(card.canonical_bytes()) <= STAGE0_CARD_POLICY_V1.max_card_bytes

    run_async(_run())


def test_the_whole_card_fit_loop_sheds_beyond_what_the_per_dimension_caps_allow() -> None:
    """The fit loop is load-bearing, not decorative: it cuts where the §3.1 caps alone would not.

    Every per-dimension cap here is satisfied by all 40 statements (40 ≤ ``max_statements``, and
    40 × 400 B of quotes is inside the 16,000 B aggregate), so anything shed is shed by the
    whole-card loop. Deleting that loop makes this fixture fail rather than quietly pass.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"fit{uuid4().hex[:6]}")
            for index in range(40):
                await _record_turn(conn, scope, index=index, route_key=f"route_{index}")
            policy = STAGE0_CARD_POLICY_V1.model_copy(
                update={"version": "test-fit-v1", "max_card_bytes": 8_000}
            )
            quote = "q" * 400
            card = await _compile(conn, scope, evidence=_FakeEvidence(default=quote), policy=policy)

            per_dimension_allowance = min(
                policy.max_statements, policy.max_quote_total_bytes // len(quote.encode())
            )
            assert per_dimension_allowance == 40  # the caps alone would admit every statement
            assert 0 < card.interview.selection.included < per_dimension_allowance
            assert len(card.canonical_bytes()) <= 8_000
            over_cap = _omission(card, Stage0CardOmissionKind.STATEMENTS_OVER_CAP)
            assert over_cap is not None
            assert over_cap.count == 40 - card.interview.selection.included

    run_async(_run())


def test_the_fit_loop_sheds_client_knowledge_once_it_runs_out_of_statements() -> None:
    """The second shed step: statements go first, Client-KB briefs only after they are exhausted.

    Statements are what the model cannot reconstruct; a KB brief always has its ``claim_id`` beside
    it, so it is the cheaper thing to lose. The target size is measured from an unbounded compile
    so the fixture cannot drift into asserting nothing.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(
                conn,
                suffix=f"kbshed{uuid4().hex[:6]}",
                materials=(
                    VolunteeredMaterial(
                        kind="deck",
                        label="pitch.pdf",
                        content="Everything about Aura.",
                        asserted_fields=dict.fromkeys(CLIENT_KNOWLEDGE_FIELDS, "v" * 1_000),
                    ),
                ),
            )
            await _record_turn(conn, scope, index=0)
            unbounded = await _compile(
                conn,
                scope,
                policy=STAGE0_CARD_POLICY_V1.model_copy(
                    update={"version": "test-kbshed-full", "max_card_bytes": 1_000_000}
                ),
            )
            assert unbounded.client_knowledge.known_fields
            target = len(unbounded.canonical_bytes()) - 500

            card = await _compile(
                conn,
                scope,
                policy=STAGE0_CARD_POLICY_V1.model_copy(
                    update={"version": "test-kbshed-v1", "max_card_bytes": target}
                ),
            )

            assert card.interview.current_effective_statements == ()  # statements shed first
            assert len(card.client_knowledge.known_fields) < len(
                unbounded.client_knowledge.known_fields
            )
            assert _omission(card, Stage0CardOmissionKind.CLIENT_KNOWLEDGE_OVER_CAP) is not None
            assert len(card.canonical_bytes()) <= target

    run_async(_run())


def test_a_policy_whose_unsheddable_sections_exceed_the_cap_raises() -> None:
    """The genuine-bug backstop. Not reachable by a conversation — only by a broken policy."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"toobig{uuid4().hex[:6]}")
            await _record_turn(conn, scope, index=0)
            policy = STAGE0_CARD_POLICY_V1.model_copy(
                update={"version": "test-toobig-v1", "max_card_bytes": 10}
            )

            with pytest.raises(Stage0CardTooLarge, match="nothing left to drop"):
                await _compile(conn, scope, policy=policy)

    run_async(_run())


# --- selection order ---------------------------------------------------------


def test_selection_dedups_then_keeps_the_newest() -> None:
    """Exact ``(route_key, quote)`` repeats collapse; the newest survivors make the cut.

    Same discipline as ``icp_synthesis._bounded_statements`` — a client who says the same thing
    twice should not weigh twice, and the newest targeting talk is what an ICP should follow.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"sel{uuid4().hex[:6]}")
            for index in range(5):
                await _record_turn(conn, scope, index=index, route_key="target_segment")
            # Quotes are assigned in the *durable* ``read_statements`` order — one rolled-back
            # transaction stamps every row with the same ``now()``, so insertion order is not the
            # conversation order the compiler sees. The rule under test is "newest of the durable
            # order wins", so the fixture speaks that order.
            rows = await read_statements(
                conn, workspace_id=scope.workspace_id, project_id=scope.project_id
            )
            # the two oldest say exactly the same thing; the rest are distinct
            words = ("same words", "same words", "second", "third", "fourth")
            quotes = {str(row.id): words[index] for index, row in enumerate(rows)}
            policy = STAGE0_CARD_POLICY_V1.model_copy(
                update={"version": "test-sel-v1", "max_statements": 2}
            )
            card = await _compile(conn, scope, evidence=_FakeEvidence(quotes=quotes), policy=policy)

            selection = card.interview.selection
            assert selection.order == STATEMENT_SELECTION_ORDER
            assert selection.total_effective == 4  # the duplicate collapsed
            assert selection.deduped_count == 1
            # every reduction between the durable rows and the shown ones is accounted for, so
            # the collapsed duplicate cannot quietly vanish from the card's own arithmetic
            over_cap = _omission(card, Stage0CardOmissionKind.STATEMENTS_OVER_CAP)
            assert over_cap is not None
            assert selection.included + over_cap.count + selection.deduped_count == len(rows)
            assert [item.quoted_text for item in card.interview.current_effective_statements] == [
                "fourth",
                "third",
            ]
            cursor = card.interview.selection.cursor
            assert cursor is not None
            assert decode_card_cursor(cursor) == {
                "kind": "statements",
                "before_statement_id": str(rows[3].id),
            }

    run_async(_run())


def test_a_corrected_statement_is_superseded_and_only_counted() -> None:
    """Latest-correction-wins: a retracted claim about targeting must not keep steering the card."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"sup{uuid4().hex[:6]}")
            original = await _record_turn(conn, scope, index=0, route_key="target_segment")
            await _record_turn(conn, scope, index=1, route_key="target_segment", corrects=original)
            card = await _compile(
                conn, scope, evidence=_FakeEvidence(quotes={str(original): "healthcare"})
            )

            (entry,) = card.interview.current_effective_statements
            assert entry.statement_id != str(original)
            assert entry.supersedes == str(original)
            assert card.interview.superseded_count == 1
            assert card.interview.selection.total_effective == 1

    run_async(_run())


def test_an_unmapped_route_is_counted_but_never_shown_as_project_state() -> None:
    """UNMAPPED is the honest "nothing material here" escape — a count, not a statement."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"unm{uuid4().hex[:6]}")
            await _record_turn(conn, scope, index=0)
            await _record_turn(conn, scope, index=1, route_kind=StatementRoute.UNMAPPED)
            card = await _compile(conn, scope)

            assert card.interview.unmapped_count == 1
            assert len(card.interview.current_effective_statements) == 1

    run_async(_run())


# --- honest absence ----------------------------------------------------------


def test_missing_evidence_is_surfaced_as_an_omission_never_silently_dropped() -> None:
    """An erased turn removes words from the card, not the fact that words are missing."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"evid{uuid4().hex[:6]}")
            gone = await _record_turn(conn, scope, index=0)
            await _record_turn(conn, scope, index=1)
            card = await _compile(
                conn, scope, evidence=_FakeEvidence(missing=frozenset({str(gone)}))
            )

            shown = {item.statement_id for item in card.interview.current_effective_statements}
            assert str(gone) not in shown
            excluded = _omission(card, Stage0CardOmissionKind.EXCLUDED_STATEMENT_EVIDENCE_MISSING)
            assert excluded is not None
            assert excluded.count == 1
            assert excluded.cursor is not None
            # a count and a cursor — never the ids of what was left out
            assert str(gone) not in card.canonical_bytes().decode()

    run_async(_run())


def test_readiness_shows_the_latest_authoritative_decision_per_gate() -> None:
    """One entry per gate: the latest ``created_by_actor='system'`` decision in ledger order.

    "Latest" is the ledger's own ``(created_at, id)`` order, so the expectation is read from the
    ledger rather than from insertion order (a rolled-back transaction stamps one ``now()`` on
    every row). The actor rule gets its own unambiguous fixture below.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"rdy{uuid4().hex[:6]}")
            for index in range(3):
                await _record_decision(conn, scope, index=index)
            await _record_decision(conn, scope, index=0, gate=ReadinessGate.DISCOVERY_SPEND)

            ledger = await read_readiness_decisions(
                conn, workspace_id=scope.workspace_id, project_id=scope.project_id
            )
            card = await _compile(conn, scope)

            gates = {item.gate: item for item in card.readiness.latest_by_gate}
            assert set(gates) == {"icp_synthesis", "discovery_spend"}
            expected = [row for row in ledger if row.gate is ReadinessGate.ICP_SYNTHESIS][-1]
            assert gates["icp_synthesis"].decision_id == str(expected.id)
            assert gates["icp_synthesis"].metrics == expected.metrics
            assert card.readiness.ledger_length == 4
            assert card.compiled_from.readiness_decision_ids == tuple(
                item.decision_id for item in card.readiness.latest_by_gate
            )

    run_async(_run())


def test_an_agent_authored_decision_is_never_shown_as_a_machine_verdict() -> None:
    """An agent-authored readiness row is evidence about the agent, not an authoritative verdict.

    The gate has history — so it appears — but with no *authoritative* lineage-current decision it
    says ``not_evaluated_for_current_lineage`` rather than laundering the agent's opinion.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"actor{uuid4().hex[:6]}")
            await _record_decision(conn, scope, index=0, actor="agent")

            card = await _compile(conn, scope)

            (gate,) = card.readiness.latest_by_gate
            assert gate.gate == "icp_synthesis"
            assert gate.verdict == NOT_EVALUATED_FOR_CURRENT_LINEAGE
            assert gate.decision_id is None
            assert card.readiness.ledger_length == 1

    run_async(_run())


def test_a_stale_lineage_gate_reports_not_evaluated_instead_of_a_stale_verdict() -> None:
    """AC-2: the opening prompt must never present a superseded lineage's verdict as current."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"stale{uuid4().hex[:6]}")
            # a decision taken against a *previous* Client-KB version
            await _record_decision(conn, scope, index=0, client_kb_version=scope.client_kb_version)
            current = await _compile(conn, scope)
            assert current.readiness.latest_by_gate[0].verdict != NOT_EVALUATED_FOR_CURRENT_LINEAGE

            moved = await compile_stage0_project_card(
                project_id=scope.project_id,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version + 1,
                product_id=scope.product_id,
                evidence=_FakeEvidence(),
                conn_factory=conn_session_factory(conn),
            )

            (gate,) = moved.readiness.latest_by_gate
            assert gate.verdict == NOT_EVALUATED_FOR_CURRENT_LINEAGE
            assert gate.effective_verdict == NOT_EVALUATED_FOR_CURRENT_LINEAGE
            assert gate.decision_id is None
            # the stale decision is still reachable as history, just not as a verdict
            assert moved.readiness.ledger_length == 1
            assert _omission(moved, Stage0CardOmissionKind.READINESS_HISTORY) is not None

    run_async(_run())


def test_an_overridden_decision_carries_its_override_ref_and_effective_verdict() -> None:
    """AC-2's other half — and it goes through the same helper ``stage0_readiness`` uses."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"ovr{uuid4().hex[:6]}")
            decision = await _record_decision(conn, scope, index=0)
            override = await override_readiness(
                conn,
                decision_id=decision,
                workspace_id=scope.workspace_id,
                gate=ReadinessGate.ICP_SYNTHESIS,
                actor="human",
                reason="the human accepts the risk",
            )
            card = await _compile(conn, scope)

            (gate,) = card.readiness.latest_by_gate
            # the machine verdict is preserved, not rewritten — the override sits beside it
            assert gate.verdict in {"ready", "not_ready"}
            assert gate.effective_verdict == "overridden"
            assert gate.override_ref == str(override)

    run_async(_run())


# --- ICP + scoping -----------------------------------------------------------


def test_the_icp_section_carries_refs_and_caller_supplied_proposal_state_only() -> None:
    """Proposal *bodies* live on the human surface; the card carries refs + two booleans (§5.1)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"icp{uuid4().hex[:6]}")
            card = await _compile(conn, scope, proposals_pending=True, proposals_stale=True)

            assert card.icp.confirmed == ()
            assert card.icp.proposals_pending is True
            assert card.icp.proposals_stale is True
            assert "proposal" not in json.loads(card.canonical_bytes())["icp"].get("confirmed", "")

    run_async(_run())


def test_an_unconfirmed_product_is_reported_as_unconfirmed() -> None:
    """Stage 0 profiles a *candidate* product before the human confirms it; the card says which."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"prod{uuid4().hex[:6]}", confirm_product=False)
            card = await _compile(conn, scope)

            assert card.product.confirmed is False
            assert card.product.product_id == scope.product_id  # the candidate, named honestly

    run_async(_run())


def test_a_cross_workspace_compile_raises() -> None:
    """AC-10: fail closed. A card is never compiled for a project this workspace does not own."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn, suffix=f"scope{uuid4().hex[:6]}")
            other = await seed_workspace(conn, f"{scope.workspace_id}-other")

            with pytest.raises(ValueError, match="does not exist in this workspace"):
                await _compile(conn, scope, workspace_id=other)

    run_async(_run())
