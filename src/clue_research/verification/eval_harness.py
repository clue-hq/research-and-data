"""M9.6 — the verification eval harness: rubric battery + per-mechanism metrics + regression gate.

This is how an accuracy claim is *defended* to an enterprise buyer and how a model/resolver swap's
regressions are caught (substrate §6). It *fills* the M0.6 ``clue_research.evals`` scaffold with the
real verification battery: it reuses the scaffold's rubric :class:`~clue_research.evals.Scorer`
battery and faithfulness :class:`~clue_research.evals.Judge` seam, and adds the **per-mechanism
metrics** that exercise all six M9 issues over the hand-verified
:class:`~clue_research.verification.golden.GoldPack`:

* ``pre_spend_gate`` (M9.1) — a structurally doomed claim (tier-4 with no span / weak-bound contact)
  is blocked (``can_be_promoted`` is False) before it can be used (an offline structural proxy for
  the gate's spend-block; the full field-registry/identity gate runs in the DB-gated tests).
* ``corroboration`` (M9.2) — an under-corroborated load-bearing claim is **not** promotable while N
  independent agreeing sources are (via the M9.2 ``independent_source_count`` rule).
* ``faithfulness`` (M9.3) — a fabricated / unsupported tier-4 value is not entailed by its span (the
  injected ``Judge``; the LLM judge reuses the M9.3 prompt/parser behind :class:`GatewayJudge`).
* ``identity_binding`` (M9.4) — a same-name / look-alike contact claim classifies ``weak`` (via
  :func:`~clue_research.verification.classify_binding`).
* ``freshness`` (M9.5) — a past-TTL fact is reported ``stale`` / ``expired`` (via the M9.5 engine).

The harness is **offline-capable** (no DB, no live LLM): the mechanism metrics run the pure
classifiers and the deterministic stub judges, so ``make eval`` and CI make no live call (the M0.6
acceptance). The DB-backed half (golden-fixture round-trip, ``eval_run`` persistence, the human
spot-check sampler) lives behind passed connections. The whole thing is the **regression gate**:
:func:`check_regressions` fails (a non-empty result) when any rubric pass-rate or mechanism recall
drops beyond a tolerance vs a baseline — so a judge-model / resolver / threshold swap is caught
before it merges (the report's ``config_snapshot`` pins the exact config so a regression is traced).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from opentelemetry.trace import Span
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import ALL_TENANTS, TenantScope
from clue_research.core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    FreshnessState,
    IdentityBinding,
    ResearchMode,
    UseClass,
    account_claim,
    can_be_promoted,
    contact_claim,
    decode_jsonb_scalar,
    new_entity_id,
    new_run_id,
    serialize_value_json,
)
from clue_research.core import JudgeVerdict as CoreJudgeVerdict
from clue_research.core.field import classify_field_key
from clue_research.core.gateway import LLMGateway
from clue_research.evals import (
    EvalHarness,
    EvalReport,
    FixtureKind,
    Judge,
    JudgeVerdict,
    MechanismMetric,
    Regression,
    RubricScore,
    Scorer,
    default_scorers,
)
from clue_research.obs import (
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)
from clue_research.verification.corroboration import independent_source_count
from clue_research.verification.faithfulness import (
    DEFAULT_JUDGE_POLICY,
    JudgePolicy,
    build_judge_messages,
    parse_judge_response,
)
from clue_research.verification.freshness import FreshnessImpl
from clue_research.verification.golden import GoldPack, ingest_golden_fixture
from clue_research.verification.identity_binding import (
    DEFAULT_BINDING_POLICY,
    BindingPolicy,
    classify_binding,
)

# Verification-health metrics (Doc C §6) + spans/attrs. M9-local name strings (the shared
# sink/tracer accept any string), defined here so M9.6 stays self-contained and never edits obs.
SPAN_EVAL_RUN = "verification.eval.run"
SPAN_EVAL_MECHANISM = "verification.eval.mechanism"
SPAN_EVAL_RUBRIC = "verification.eval.rubric"
METRIC_EVAL_RUBRIC_PASS_RATE = "research.verification.eval.rubric_pass_rate"
METRIC_EVAL_MECHANISM_RECALL = "research.verification.eval.mechanism_recall"
METRIC_EVAL_REGRESSIONS = "research.verification.eval.regressions"
ATTR_EVAL_SUITE = "verification.eval.suite"
ATTR_EVAL_MECHANISM = "verification.eval.mechanism"
ATTR_EVAL_RUBRIC = "verification.eval.rubric"
ATTR_EVAL_RECALL = "verification.eval.recall"
ATTR_EVAL_PASS_RATE = "verification.eval.pass_rate"
ATTR_EVAL_DETECTED = "verification.eval.detected"
ATTR_EVAL_EXPECTED = "verification.eval.expected"
ATTR_EVAL_REGRESSED = "verification.eval.regressed"

# The five mechanism names (the per-gate recall keys; stable so a report's mechanism series and the
# regression gate's metric names never drift).
MECH_PRE_SPEND_GATE = "pre_spend_gate"
MECH_CORROBORATION = "corroboration"
MECH_FAITHFULNESS = "faithfulness"
MECH_IDENTITY_BINDING = "identity_binding"
MECH_FRESHNESS = "freshness"

# The corroboration threshold the load-bearing-field scenario asserts against (the # of independent
# tier≤3 sources required to promote). Named so the config snapshot can pin it and a future
# fixture-driven corroboration mechanism can read one value.
CORROBORATION_THRESHOLD = 2


# --- the LLM-as-judge adapter (reuses the M9.3 judge infra behind the evals.Judge seam) -----------


class GatewayJudge:
    """An :class:`~clue_research.evals.Judge` backed by the M9.3 LLM-as-judge infra: it builds the
    M9.3 entailment messages, calls the injected ``core`` :class:`~clue_research.core.gateway.
    LLMGateway`, and parses the verdict with the M9.3 parser — so the faithfulness rubric uses the
    **real** judge and a judge-model swap is a config change (regression-checked by this battery).

    Offline (a ``StubGateway``) the canned response parses to ``unsupported`` (a model that won't
    entail), so it is deterministic and makes no live call; the deterministic ``GroundedStubJudge``
    is the offline default judge for the battery."""

    def __init__(self, gateway: LLMGateway, *, policy: JudgePolicy = DEFAULT_JUDGE_POLICY) -> None:
        self._gateway = gateway
        self._policy = policy
        self.name = f"gateway:{policy.judge_model}@{policy.prompt_version}"

    def judge(self, claim: Claim) -> JudgeVerdict:
        if not claim.evidence_span:
            return JudgeVerdict(entailed=False, reason="no evidence span (substrate §1)")
        messages = build_judge_messages(claim, prompt_version=self._policy.prompt_version)
        completion = self._gateway.complete(model=self._policy.judge_model, messages=messages)
        parsed = parse_judge_response(completion.text)
        entailed = (
            parsed.verdict is CoreJudgeVerdict.SUPPORTED
            and parsed.score >= self._policy.supported_threshold
        )
        return JudgeVerdict(entailed=entailed, reason=parsed.rationale or parsed.verdict.value)


# --- the five mechanism metrics (pure, over a GoldPack / constructed scenarios) -------------------


def identity_binding_metric(
    pack: GoldPack, *, policy: BindingPolicy = DEFAULT_BINDING_POLICY
) -> MechanismMetric:
    """M9.4 recall: every ``negative_samename`` contact claim must classify ``weak``; a positive
    (verified-handle) contact claim must stay ``strong`` (no false positive)."""
    produced = pack.produced_index()
    detected = expected = false_positive = 0
    for entity in pack.gold.entities:
        for gold in entity.claims:
            claim = produced.get((entity.entity_id, str(gold.field_key)))
            if claim is None or claim.entity_type is not EntityType.CONTACT:
                continue
            contact = pack.contacts.get(claim.entity_id)
            account = pack.accounts.get(contact.account_entity_id) if contact is not None else None
            binding = classify_binding(
                claim,
                contact,
                account_name=account.canonical_name if account is not None else None,
                account_aliases=account.aliases if account is not None else (),
                manifest_prior=None,
                policy=policy,
            )
            weak = binding.strength is IdentityBinding.WEAK
            if gold.fixture_kind is FixtureKind.NEGATIVE_SAMENAME:
                expected += 1
                detected += int(weak)
            elif gold.fixture_kind is FixtureKind.POSITIVE:
                false_positive += int(weak)
    return MechanismMetric(
        mechanism=MECH_IDENTITY_BINDING,
        detected=detected,
        expected=expected,
        false_positive=false_positive,
    )


def freshness_metric(pack: GoldPack, *, engine: FreshnessImpl | None = None) -> MechanismMetric:
    """M9.5 recall: every ``negative_stale`` fact must read ``stale``/``expired`` at ``pack.now``; a
    positive (recently observed) fact must read fresh (no false positive)."""
    engine = engine or FreshnessImpl()
    produced = pack.produced_index()
    detected = expected = false_positive = 0
    for entity in pack.gold.entities:
        for gold in entity.claims:
            claim = produced.get((entity.entity_id, str(gold.field_key)))
            if claim is None:
                continue
            state = engine.evaluate(claim, now=pack.now).state
            stale = state in (FreshnessState.STALE, FreshnessState.EXPIRED)
            if gold.fixture_kind is FixtureKind.NEGATIVE_STALE:
                expected += 1
                detected += int(stale)
            elif gold.fixture_kind is FixtureKind.POSITIVE:
                false_positive += int(stale)
    return MechanismMetric(
        mechanism=MECH_FRESHNESS,
        detected=detected,
        expected=expected,
        false_positive=false_positive,
    )


def faithfulness_metric(pack: GoldPack, judge: Judge) -> MechanismMetric:
    """M9.3 recall: every ``negative_fabrication``/``negative_unsupported`` tier-4 value must be
    judged *not* entailed by its span; a positive (faithful) tier-4 value must be entailed (no false
    positive). Reuses the injected ``Judge`` (the stub offline, :class:`GatewayJudge` live)."""
    produced = pack.produced_index()
    detected = expected = false_positive = 0
    for entity in pack.gold.entities:
        for gold in entity.claims:
            claim = produced.get((entity.entity_id, str(gold.field_key)))
            if claim is None:
                continue
            if gold.fixture_kind in (
                FixtureKind.NEGATIVE_FABRICATION,
                FixtureKind.NEGATIVE_UNSUPPORTED,
            ):
                expected += 1
                detected += int(not judge.judge(claim).entailed)
            elif gold.fixture_kind is FixtureKind.POSITIVE and claim.source_tier == 4:
                false_positive += int(not judge.judge(claim).entailed)
    return MechanismMetric(
        mechanism=MECH_FAITHFULNESS,
        detected=detected,
        expected=expected,
        false_positive=false_positive,
    )


def corroboration_metric() -> MechanismMetric:
    """M9.2 recall (scenario-driven): an under-corroborated load-bearing claim (one source) must
    count below the threshold (not promotable), while two **independent** agreeing sources must meet
    it (no false positive). Uses the M9.2 independence rule directly."""
    run = new_run_id()
    entity = new_entity_id()
    threshold = CORROBORATION_THRESHOLD

    def _claim(host: str) -> Claim:
        return account_claim(
            entity_id=entity,
            field_key="account.recent_funding",
            value_json={"round": "B"},
            source_tier=3,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.9,
            run_id=run,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url=f"https://{host}/x",
            evidence_span="Series B reported.",
        )

    under_corroborated = [_claim("a.example.com")]
    corroborated = [_claim("a.example.com"), _claim("b.example.com")]
    detected = int(independent_source_count(under_corroborated) < threshold)
    false_positive = int(independent_source_count(corroborated) < threshold)
    return MechanismMetric(
        mechanism=MECH_CORROBORATION, detected=detected, expected=1, false_positive=false_positive
    )


def gate_block_metric() -> MechanismMetric:
    """M9.1 recall (offline structural proxy): a structurally doomed claim must be blocked before it
    can be used — a tier-4 synthesized claim with no evidence span (a fabricated fact) and a
    weak-binding contact claim (someone else's fact) are both ``can_be_promoted == False``, while a
    valid tier-1 claim is promotable (no false positive). The full field-registry / identity /
    tier-plan gate is exercised against the real ``PreSpendGateImpl`` in the DB-gated tests."""
    run = new_run_id()
    account = new_entity_id()
    contact = new_entity_id()
    doomed = [
        account_claim(
            entity_id=account,
            field_key="account.strategic_move",
            value_json="acquiring BetaCorp",
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            confidence=0.5,
            run_id=run,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://exa.example.com/x",
            evidence_span=None,  # tier-4 with no span -> never promotable (the kill-switch)
        ),
        contact_claim(
            entity_id=contact,
            field_key="contact.facet.hobby",
            value_json="rock climbing",
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.5,
            run_id=run,
            research_mode=ResearchMode.CONTACT_PROFILING,
            identity_binding=IdentityBinding.WEAK,  # weak binding -> never promotable
            use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
            source_url="https://blog.example.com/x",
            evidence_span="A blog mentions the name.",
        ),
    ]
    valid = account_claim(
        entity_id=account,
        field_key="core.employee_count",
        value_json=100,
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        confidence=0.99,
        run_id=run,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://api.example.com/x",
    )
    detected = sum(1 for claim in doomed if not can_be_promoted(claim))
    false_positive = int(not can_be_promoted(valid))
    return MechanismMetric(
        mechanism=MECH_PRE_SPEND_GATE,
        detected=detected,
        expected=len(doomed),
        false_positive=false_positive,
    )


# --- the regression gate ----------------------------------------------------


def check_regressions(
    current: EvalReport, baseline: EvalReport, *, tolerance: float = 0.0
) -> tuple[Regression, ...]:
    """The CI regression gate: every rubric pass-rate AND mechanism recall is compared to the
    baseline; the ones that **dropped** strictly beyond ``tolerance`` are returned (an empty tuple =
    no regression = the gate passes). A non-empty result fails the gate — so a judge-model /
    resolver / threshold swap that degrades accuracy is caught before it merges (substrate §6)."""
    current_board, baseline_board = current.scoreboard(), baseline.scoreboard()
    regressions: list[Regression] = []
    for metric in sorted(current_board):
        if metric not in baseline_board:
            continue
        regression = Regression(
            metric=metric,
            baseline=baseline_board[metric],
            current=current_board[metric],
            tolerance=tolerance,
        )
        if regression.regressed:
            regressions.append(regression)
    return tuple(regressions)


def regression_exit_code(report: EvalReport) -> int:
    """The CI exit code for a scored report: ``1`` when it carries any regression (the gate FAILS),
    else ``0``. The actual fail-on-regression command is wired at the ``api`` composition root —
    it scores the **current** config against a stored ``eval_run`` baseline (or a committed baseline
    report), sets ``report.regressions`` via :func:`check_regressions`, and does
    ``raise SystemExit(regression_exit_code(report))`` to fail a swap-gating CI step. (The offline
    ``eval_cli`` is a *demo*, not the gate — it always weakens the judge, so it would always fail;
    the enforced offline proof is the ``test_regression_gate_fails_on_weakened_judge`` test.)"""
    return 1 if report.has_regression else 0


# --- the harness ------------------------------------------------------------


class VerificationEvalHarness:
    """Runs the rubric battery + the five mechanism metrics over a :class:`GoldPack` and reports the
    extended :class:`~clue_research.evals.EvalReport`. Scorers + judge + the binding/freshness
    engines are injected (swappable — the whole point). Emits the ``verification.eval.*`` spans and
    the verification-health metrics."""

    def __init__(
        self,
        *,
        judge: Judge,
        scorers: Sequence[Scorer] | None = None,
        freshness: FreshnessImpl | None = None,
        binding_policy: BindingPolicy = DEFAULT_BINDING_POLICY,
        sink: MetricSink | None = None,
    ) -> None:
        self._scorers = tuple(scorers) if scorers is not None else default_scorers()
        self._judge = judge
        self._freshness = freshness or FreshnessImpl()
        self._binding_policy = binding_policy
        self._sink = sink

    def run(
        self,
        pack: GoldPack,
        *,
        baseline: EvalReport | None = None,
        tolerance: float = 0.0,
        config_snapshot: dict[str, JsonValue] | None = None,
    ) -> EvalReport:
        """Score ``pack`` and return the report. When ``baseline`` is given, the report's
        ``regressions`` are the metrics that dropped beyond ``tolerance`` (the gate verdict)."""
        with traced_step(SPAN_EVAL_RUN, **{ATTR_EVAL_SUITE: pack.gold.name}) as span:
            rubric = EvalHarness(self._scorers, self._judge).run(pack.gold, pack.produced)
            self._emit_rubric_spans(rubric.rubric_scores)
            mechanisms = self._run_mechanisms(pack)
            snapshot = (
                dict(config_snapshot) if config_snapshot is not None else self._config_snapshot()
            )
            report = EvalReport(
                gold_set=pack.gold.name,
                judge=getattr(self._judge, "name", "judge"),
                rubric_scores=rubric.rubric_scores,
                mechanism_metrics=mechanisms,
                config_snapshot=snapshot,
            )
            if baseline is not None:
                report = report.model_copy(
                    update={"regressions": check_regressions(report, baseline, tolerance=tolerance)}
                )
            self._emit(span, report)
            return report

    def _emit_rubric_spans(self, scores: tuple[RubricScore, ...]) -> None:
        """A ``verification.eval.rubric`` span per rubric (the base M0.6 runner emits none), so the
        AC2 per-rubric-span requirement holds beside the per-mechanism spans."""
        for score in scores:
            with traced_step(SPAN_EVAL_RUBRIC, **{ATTR_EVAL_RUBRIC: score.rubric}) as rspan:
                apply_attributes(rspan, {ATTR_EVAL_PASS_RATE: score.pass_rate})

    def _run_mechanisms(self, pack: GoldPack) -> tuple[MechanismMetric, ...]:
        """Compute all five mechanism metrics, each in its own ``verification.eval.mechanism``."""
        computed: list[MechanismMetric] = []
        builders = (
            gate_block_metric,
            corroboration_metric,
            lambda: faithfulness_metric(pack, self._judge),
            lambda: identity_binding_metric(pack, policy=self._binding_policy),
            lambda: freshness_metric(pack, engine=self._freshness),
        )
        for build in builders:
            metric = build()
            with traced_step(
                SPAN_EVAL_MECHANISM, **{ATTR_EVAL_MECHANISM: metric.mechanism}
            ) as mspan:
                apply_attributes(
                    mspan,
                    {
                        ATTR_EVAL_RECALL: metric.recall,
                        ATTR_EVAL_DETECTED: metric.detected,
                        ATTR_EVAL_EXPECTED: metric.expected,
                    },
                )
            computed.append(metric)
        return tuple(computed)

    def _config_snapshot(self) -> dict[str, JsonValue]:
        """The config a regression traces back to (AC7): the judge (name embeds model@prompt_version
        for the real :class:`GatewayJudge`), the rubric set, and the swappable thresholds the
        mechanisms read — the identity-binding K, the corroboration threshold, and the freshness
        cadence-policy version — so a threshold/cadence swap that moves a mechanism's recall is
        traceable from the snapshot alone."""
        return {
            "judge": getattr(self._judge, "name", "judge"),
            "scorers": [scorer.name for scorer in self._scorers],
            "binding_min_identifiers_k": self._binding_policy.min_identifiers_k,
            "corroboration_threshold": CORROBORATION_THRESHOLD,
            "freshness_cadence_version": self._freshness.policy.version,
        }

    def _emit(self, span: Span, report: EvalReport) -> None:
        apply_attributes(span, {ATTR_EVAL_REGRESSED: report.has_regression})
        sink = self._sink or get_metric_sink()
        for score in report.rubric_scores:
            sink.gauge(METRIC_EVAL_RUBRIC_PASS_RATE, score.pass_rate, {"rubric": score.rubric})
        for metric in report.mechanism_metrics:
            sink.gauge(METRIC_EVAL_MECHANISM_RECALL, metric.recall, {"mechanism": metric.mechanism})
        if report.has_regression:
            sink.add(METRIC_EVAL_REGRESSIONS, len(report.regressions), {})


# --- eval_run persistence + the human spot-check loop -----------------------


async def record_eval_run(
    conn: AsyncConnection, report: EvalReport, *, suite: str | None = None
) -> None:
    """Append the run to ``eval_run`` (the audit trail): the config snapshot (so a regression traces
    to the exact swap) + the full report. Append-only; the caller owns the transaction."""
    await conn.execute(
        text(
            """
            INSERT INTO eval_run (suite, config_snapshot_json, report_json)
            VALUES (:suite, CAST(:cfg AS jsonb), CAST(:report AS jsonb))
            """
        ),
        {
            "suite": suite or report.gold_set,
            "cfg": serialize_value_json(report.config_snapshot),
            "report": serialize_value_json(report.model_dump(mode="json")),
        },
    )


class SpotCheckSample(BaseModel):
    """One promoted production claim pulled for human review (M9.6 spot-check). Light by design —
    the reviewer needs the value + its provenance bar, and a confirmed sample becomes a positive
    ``golden_fixture`` (via :func:`ingest_spot_check`), folding production into the gold set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: str
    field_class: str
    value_json: JsonValue
    source_url: str | None
    source_tier: int
    research_mode: ResearchMode


async def sample_promoted_claims(
    conn: AsyncConnection,
    *,
    per_stratum: int = 3,
    scope: TenantScope = ALL_TENANTS,
    max_scan: int = 10_000,
) -> tuple[SpotCheckSample, ...]:
    """Pull a **stratified** sample of promoted (``verified``) production field claims for human
    review (M09 §M9.6) — up to ``per_stratum`` per field-class, so the sample spans the schema and
    does not over-represent the busiest field. Returns light samples; a reviewer confirms them and
    :func:`ingest_spot_check` writes each back as a new positive golden fixture (the feedback loop).
    ``scope`` is a required-with-a-default operator scan (the samples carry ids/values, an operator
    review surface).

    The stratum key is a *derived* field-class (``classify_field_key``), which the ``claim`` table
    does not store as a column, so the cap is applied in Python — bounded by ``max_scan``, a
    defensive ``LIMIT`` so memory stays O(max_scan), not O(verified claims), on a large store
    (ordered by ``field_key`` so each class is contiguous and the early classes are always covered).
    A full-coverage sweep on a very large table is a future enhancement (a ``field_class`` column +
    a per-class window)."""
    scope_sql, scope_params = scope.predicate()
    rows = (
        await conn.execute(
            text(
                f"""
                SELECT entity_id, field_key, value_json, source_url, source_tier, research_mode
                FROM claim
                WHERE verification_status = 'verified'
                  AND superseded_by IS NULL
                  AND claim_flavor = 'field_claim'
                  AND {scope_sql}
                ORDER BY field_key, id
                LIMIT :max_scan
                """
            ),
            {**scope_params, "max_scan": max_scan},
        )
    ).all()

    by_class: dict[str, list[SpotCheckSample]] = defaultdict(list)
    for entity_id, field_key, value, source_url, source_tier, research_mode in rows:
        field_class = str(classify_field_key(field_key))
        if len(by_class[field_class]) >= per_stratum:
            continue
        by_class[field_class].append(
            SpotCheckSample(
                entity_id=entity_id,
                field_key=field_key,
                field_class=field_class,
                value_json=decode_jsonb_scalar(value),
                source_url=source_url,
                source_tier=int(source_tier),
                research_mode=ResearchMode(research_mode),
            )
        )
    return tuple(sample for samples in by_class.values() for sample in samples)


async def ingest_spot_check(conn: AsyncConnection, sample: SpotCheckSample) -> bool:
    """Ingest a human-reviewed :class:`SpotCheckSample` as a new positive ``golden_fixture`` (the
    spot-check feedback loop). Idempotent. Returns whether a row was written."""
    return await ingest_golden_fixture(
        conn,
        entity_id=sample.entity_id,
        field_key=sample.field_key,
        expected_value=sample.value_json,
        source_url=sample.source_url,
        expected_tier=sample.source_tier,
        mode=sample.research_mode,
        fixture_kind=FixtureKind.POSITIVE,
    )
