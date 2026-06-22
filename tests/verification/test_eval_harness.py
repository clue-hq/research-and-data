"""M9.6 (ENG-156) — eval harness + golden set + rubric scoring.

Every §M9.6 acceptance criterion has a dedicated test. The battery is offline-capable, so the rubric
+ mechanism metrics, the regression gate, and the gold-pack coverage all run without a database (in
``make check``) using the deterministic stub judges and the pure classifiers; the DB-backed half
(golden-fixture round-trip, ``eval_run`` persistence, the human spot-check sampler, the real
pre-spend gate) is exercised against a live Postgres (skips without one, like the M9.1–M9.5 suites).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import ALL_TENANTS, insert_claim
from clue_research.config.gateway import GatewayConfig
from clue_research.core import (
    EntityId,
    ExtractionMethod,
    PreSpendRequest,
    ResearchMode,
    VerificationStatus,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.core.enums import EntityType
from clue_research.evals import (
    EvalHarness,
    EvalReport,
    FixtureKind,
    GoldClaim,
    GroundedStubJudge,
    MechanismMetric,
    Regression,
    StubJudge,
    default_scorers,
)
from clue_research.gateway.stub import StubGateway
from clue_research.obs import InMemorySink, collect_spans
from clue_research.verification import (
    GOLD_SUITE,
    GatewayJudge,
    PreSpendGateImpl,
    VerificationEvalHarness,
    check_regressions,
    corroboration_metric,
    faithfulness_metric,
    freshness_metric,
    gate_block_metric,
    identity_binding_metric,
    ingest_spot_check,
    load_golden_fixtures,
    record_eval_run,
    regression_exit_code,
    sample_promoted_claims,
    seed_golden_fixtures,
    verification_gold_pack,
)
from clue_research.verification.eval_cli import main as eval_cli_main
from clue_research.verification.eval_harness import (
    METRIC_EVAL_MECHANISM_RECALL,
    METRIC_EVAL_RUBRIC_PASS_RATE,
    SPAN_EVAL_MECHANISM,
    SPAN_EVAL_RUBRIC,
    SPAN_EVAL_RUN,
)

from .conftest import rollback_conn, run_async

_PACK = verification_gold_pack()
_MODES = (
    ResearchMode.ACCOUNT_DISCOVERY,
    ResearchMode.ACCOUNT_PROFILING,
    ResearchMode.COMMITTEE_DISCOVERY,
    ResearchMode.CONTACT_PROFILING,
)


# --- pure unit (no DB) ------------------------------------------------------


def test_gold_pack_spans_modes_and_mechanisms() -> None:
    # AC: the gold set has positive AND negative fixtures across the four research modes, and a
    # planted negative for each of the faithfulness / identity-binding / freshness mechanisms.
    by_mode_pos: dict[ResearchMode, int] = dict.fromkeys(_MODES, 0)
    by_mode_neg: dict[ResearchMode, int] = dict.fromkeys(_MODES, 0)
    kinds: set[FixtureKind] = set()
    for entity in _PACK.gold.entities:
        for gold in entity.claims:
            kinds.add(gold.fixture_kind)
            assert gold.mode is not None
            if gold.is_negative:
                by_mode_neg[gold.mode] += 1
            else:
                by_mode_pos[gold.mode] += 1
    for mode in _MODES:
        assert by_mode_pos[mode] >= 1, f"{mode} has no positive fixture"
        assert by_mode_neg[mode] >= 1, f"{mode} has no negative fixture"
    # each evidence/identity/freshness negative kind is represented (the documented catches)
    assert FixtureKind.NEGATIVE_FABRICATION in kinds
    assert FixtureKind.NEGATIVE_UNSUPPORTED in kinds
    assert FixtureKind.NEGATIVE_SAMENAME in kinds
    assert FixtureKind.NEGATIVE_STALE in kinds


def test_identity_binding_metric_catches_samename_no_false_positive() -> None:
    # AC: the same-name trap is caught by the identity-binding metric; a verified-handle positive
    # contact claim is NOT wrongly flagged weak.
    metric = identity_binding_metric(_PACK)
    assert metric.expected >= 1
    assert metric.detected == metric.expected  # every same-name trap classified weak
    assert metric.recall == 1.0
    assert metric.false_positive == 0


def test_freshness_metric_catches_stale_no_false_positive() -> None:
    # AC: the stale fixture is caught by the freshness metric; fresh positives are not flagged.
    metric = freshness_metric(_PACK)
    assert metric.expected >= 1
    assert metric.detected == metric.expected
    assert metric.false_positive == 0


def test_faithfulness_metric_catches_unsupported_with_grounded_judge() -> None:
    # AC: the unsupported-span / fabrication fixtures are caught by the faithfulness metric (the
    # grounded judge); a faithful tier-4 positive is entailed (no false positive). The lenient stub
    # judge misses them (recall 0) — the regression-on-swap signal.
    grounded = faithfulness_metric(_PACK, GroundedStubJudge())
    assert grounded.expected >= 2  # fabrication + unsupported
    assert grounded.detected == grounded.expected
    assert grounded.false_positive == 0  # the faithful tier-4 resonance fixture stays entailed
    lenient = faithfulness_metric(_PACK, StubJudge())
    assert lenient.detected == 0  # the lenient judge passes everything with a span


def test_gate_block_metric_blocks_doomed() -> None:
    metric = gate_block_metric()
    assert metric.detected == metric.expected == 2  # tier-4-no-span + weak-binding both blocked
    assert metric.false_positive == 0  # the valid tier-1 claim is promotable


def test_corroboration_metric_withholds_under_corroborated() -> None:
    metric = corroboration_metric()
    assert metric.detected == 1  # one source < the load-bearing threshold -> not promoted
    assert metric.false_positive == 0  # two independent sources DO meet the threshold


def test_factual_accuracy_catches_wrong_value() -> None:
    # AC: a swapped resolver returning a known-wrong value is caught by the factual-accuracy rubric
    # (the gold pack plants core.industry = "agriculture" against an expected "robotics").
    report = VerificationEvalHarness(judge=GroundedStubJudge()).run(_PACK)
    factual = report.by_rubric()["factual_accuracy"]
    assert 0.0 < factual.pass_rate < 1.0  # it scores, and the planted wrong value drags it below 1


def test_harness_run_emits_rubrics_and_mechanism_metrics() -> None:
    # AC: the harness produces per-rubric scores AND per-mechanism metrics over the gold set.
    report = VerificationEvalHarness(judge=GroundedStubJudge()).run(_PACK)
    assert {"factual_accuracy", "citation_validity", "source_quality"} <= set(report.metrics())
    mechanisms = report.by_mechanism()
    assert {
        "pre_spend_gate",
        "corroboration",
        "faithfulness",
        "identity_binding",
        "freshness",
    } == set(mechanisms)
    assert all(0.0 <= m.recall <= 1.0 for m in report.mechanism_metrics)


def test_scoreboard_namespaces_mechanisms_no_collision() -> None:
    # the rubric "faithfulness" (pass-rate) and the mechanism "faithfulness" (recall) must NOT
    # collide — the mechanism is namespaced so neither masks the other's regression.
    report = VerificationEvalHarness(judge=GroundedStubJudge()).run(_PACK)
    board = report.scoreboard()
    assert "faithfulness" in board  # the rubric
    assert "mechanism:faithfulness" in board  # the mechanism, distinct
    assert board["faithfulness"] != board["mechanism:faithfulness"]


def test_regression_gate_fails_on_weakened_judge() -> None:
    # AC: a weakened judge produces a measurable regression and the CI gate FAILS. Baseline = the
    # strong (grounded) judge; candidate = the weak (lenient) judge that misses the negatives.
    pack = _PACK
    strong = VerificationEvalHarness(judge=GroundedStubJudge()).run(pack)
    weak = VerificationEvalHarness(judge=StubJudge()).run(pack, baseline=strong, tolerance=0.0)
    assert weak.has_regression
    regressed = {reg.metric for reg in weak.regressions}
    assert "mechanism:faithfulness" in regressed  # the faithfulness recall dropped 1.0 -> 0.0
    # the gate function agrees and is non-empty (it fails)
    assert check_regressions(weak, strong, tolerance=0.0)


def test_regression_gate_clean_when_identical() -> None:
    report = VerificationEvalHarness(judge=GroundedStubJudge()).run(_PACK)
    assert check_regressions(report, report, tolerance=0.0) == ()
    assert not report.has_regression


def test_regression_exit_code() -> None:
    # the CI-gate primitive: a report with a regression -> exit 1 (the gate FAILS); else exit 0.
    strong = VerificationEvalHarness(judge=GroundedStubJudge()).run(_PACK)
    weak = VerificationEvalHarness(judge=StubJudge()).run(_PACK, baseline=strong)
    assert regression_exit_code(weak) == 1
    assert regression_exit_code(strong) == 0


def test_eval_cli_demo_runs_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    # the offline demo is CI-safe: it prints the regression-on-swap verdict and returns None (exit
    # 0) — it is a demo, not the gate (the gate is regression_exit_code, proven above).
    eval_cli_main()
    out = capsys.readouterr().out
    assert "baseline" in out and "candidate" in out
    assert "mechanism:faithfulness" in out  # the weakened-judge regression is shown


def test_regression_gate_tolerance_absorbs_small_drop() -> None:
    base = EvalReport(gold_set="s", judge="j", rubric_scores=())
    base = base.model_copy(
        update={"mechanism_metrics": (MechanismMetric(mechanism="m", detected=10, expected=10),)}
    )
    # a metric that drops from 1.0 to 0.95: regressed at tolerance 0.0, absorbed at tolerance 0.1.
    current = EvalReport(
        gold_set="s",
        judge="j",
        mechanism_metrics=(MechanismMetric(mechanism="m", detected=95, expected=100),),
    )
    assert check_regressions(current, base, tolerance=0.0)
    assert check_regressions(current, base, tolerance=0.1) == ()


def test_regression_record_shapes() -> None:
    reg = Regression(metric="m", baseline=1.0, current=0.7, tolerance=0.0)
    assert reg.delta == pytest.approx(-0.3)
    assert reg.regressed
    assert not Regression(metric="m", baseline=0.7, current=1.0, tolerance=0.0).regressed
    metric = MechanismMetric(mechanism="m", detected=2, expected=4, false_positive=1)
    assert metric.recall == 0.5
    assert metric.precision == pytest.approx(2 / 3)
    # no negatives to catch -> recall 1.0 by convention; nothing flagged -> precision 1.0
    assert MechanismMetric(mechanism="m").recall == 1.0
    assert MechanismMetric(mechanism="m").precision == 1.0


def test_gateway_judge_reuses_m93_and_is_offline_deterministic() -> None:
    # the GatewayJudge wraps the M9.3 prompt/parser behind an injected gateway; with the StubGateway
    # the canned response parses to unsupported (not entailed) deterministically — no live call.
    judge = GatewayJudge(StubGateway(GatewayConfig()))
    pack = _PACK
    a_claim = next(c for c in pack.produced if c.evidence_span)
    verdict = judge.judge(a_claim)
    assert verdict.entailed is False  # stub gateway -> unparseable -> unsupported (fail-safe)
    no_span = next(c for c in pack.produced if not c.evidence_span)
    assert judge.judge(no_span).entailed is False  # structural pre-check, zero gateway calls


def test_eval_spans_emitted() -> None:
    # AC2: per-rubric AND per-mechanism metrics each emit their own trace span, under the run span.
    with collect_spans() as exporter:
        VerificationEvalHarness(judge=GroundedStubJudge()).run(_PACK)
    names = {s.name for s in exporter.get_finished_spans()}
    assert SPAN_EVAL_RUN in names
    assert SPAN_EVAL_MECHANISM in names
    assert SPAN_EVAL_RUBRIC in names  # a span per rubric (not just under the run span)


def test_eval_metrics_emitted() -> None:
    sink = InMemorySink()
    VerificationEvalHarness(judge=GroundedStubJudge(), sink=sink).run(_PACK)
    assert sink.gauge_value(METRIC_EVAL_RUBRIC_PASS_RATE, rubric="factual_accuracy") > 0.0
    assert sink.gauge_value(METRIC_EVAL_MECHANISM_RECALL, mechanism="identity_binding") == 1.0


def test_fixture_kind_enum_parity_with_migration() -> None:
    """Pure no-DB drift guard (runs in ``make check``): the migration's ``fixture_kind`` enum tuple
    matches the code :class:`FixtureKind` (mirrors the M9.3 judge_verdict parity guard)."""
    src = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/015474d0a18c_m9_6_eval_harness_golden_fixture_eval_.py"
    ).read_text()
    start = src.index("_FIXTURE_KIND = (")
    block = src[start : src.index(")", start)]
    migration_values = set(re.findall(r'"([a-z_]+)"', block))
    assert migration_values == {kind.value for kind in FixtureKind}


# --- DB-gated behaviour -----------------------------------------------------


@pytest.mark.usefixtures("require_verification_db")
def test_seed_and_load_golden_fixtures_round_trip() -> None:
    # AC: the durable gold set is a faithful round-trip — not just the (entity, field, kind) keys
    # but every GoldClaim provenance-bar field (value, tier, source, requires_evidence_span, mode),
    # so a swap scored against the durable set matches scoring against the in-code pack (no drift).
    def _claim_record(entity_id: EntityId, claim: GoldClaim) -> tuple[object, ...]:
        return (
            str(entity_id),
            str(claim.field_key),
            claim.fixture_kind,
            json.dumps(claim.expected_value, sort_keys=True),  # canonical (jsonb may reorder keys)
            int(claim.max_source_tier),
            claim.requires_evidence_span,
            claim.expected_source_url,
            claim.mode,
        )

    async def _run() -> None:
        async with rollback_conn() as conn:
            inserted = await seed_golden_fixtures(conn, _PACK.gold)
            assert inserted == sum(len(e.claims) for e in _PACK.gold.entities)
            # re-seeding is idempotent (ON CONFLICT DO NOTHING).
            assert await seed_golden_fixtures(conn, _PACK.gold) == 0
            loaded = await load_golden_fixtures(conn)
            original = {
                _claim_record(e.entity_id, c) for e in _PACK.gold.entities for c in e.claims
            }
            roundtripped = {
                _claim_record(e.entity_id, c) for e in loaded.entities for c in e.claims
            }
            assert original == roundtripped  # full-field equivalence, incl. requires_evidence_span

            # scoring the produced pack against the DB-loaded gold == scoring against the in-code
            # gold (true round-trip score-equivalence, the loader's documented purpose).
            scorers = default_scorers()
            in_code = EvalHarness(scorers, GroundedStubJudge()).run(_PACK.gold, _PACK.produced)
            durable = EvalHarness(scorers, GroundedStubJudge()).run(loaded, _PACK.produced)
            assert in_code.metrics() == durable.metrics()

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_record_eval_run_persists_config_and_report() -> None:
    # AC: eval runs are recorded with a config snapshot so a regression traces to the exact swap.
    async def _run() -> None:
        async with rollback_conn() as conn:
            report = VerificationEvalHarness(judge=GroundedStubJudge()).run(_PACK)
            await record_eval_run(conn, report)
            row = (
                await conn.execute(
                    text(
                        "SELECT suite, config_snapshot_json, report_json FROM eval_run "
                        "WHERE suite = :s ORDER BY started_at DESC LIMIT 1"
                    ),
                    {"s": GOLD_SUITE},
                )
            ).first()
            assert row is not None
            suite, config_snapshot, report_json = row
            assert suite == GOLD_SUITE
            assert config_snapshot["judge"] == "grounded_stub"  # the exact judge that ran
            # the snapshot pins the swappable thresholds a mechanism regression would trace to.
            assert config_snapshot["binding_min_identifiers_k"] == 2
            assert config_snapshot["corroboration_threshold"] == 2
            assert "freshness_cadence_version" in config_snapshot
            assert "mechanism_metrics" in report_json

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_spot_check_sampler_stratified_and_ingest_round_trip() -> None:
    # AC: the sampler returns a stratified sample of promoted production claims, and a reviewed
    # sample ingests back as a new positive golden fixture (the feedback loop).
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            run = new_run_id()
            # two verified claims in different field-classes + one tier-1 to over-fill a stratum.
            fixtures: tuple[tuple[str, object], ...] = (
                ("core.employee_count", 500),
                ("account.recent_funding", {"round": "B"}),
                ("core.primary_domain", "acme.com"),
            )
            for field_key, value in fixtures:
                claim = account_claim(
                    entity_id=entity,
                    field_key=field_key,
                    value_json=value,  # type: ignore[arg-type]
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.99,
                    run_id=run,
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="https://api.example.com/x",
                )
                await insert_claim(
                    conn,
                    claim.model_copy(update={"verification_status": VerificationStatus.VERIFIED}),
                    validate_field=False,
                )
            samples = await sample_promoted_claims(conn, per_stratum=1, scope=ALL_TENANTS)
            classes = [s.field_class for s in samples]
            # stratified: at most one per field-class (core has 2 claims -> only 1 sampled).
            assert classes.count("core") == 1
            assert {"core", "account"} <= set(classes)

            wrote = await ingest_spot_check(conn, samples[0])
            assert wrote is True
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM golden_fixture WHERE entity_ref = :e "
                        "AND fixture_kind = 'positive'"
                    ),
                    {"e": str(samples[0].entity_id)},
                )
            ).scalar_one()
            assert count >= 1

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_pre_spend_gate_blocks_unknown_field() -> None:
    # the gate-block mechanism in the DB plane: the REAL M9.1 pre-spend gate rejects a request for
    # an unregistered field (offline, gate_block_metric uses the structural can_be_promoted proxy).
    async def _run() -> None:
        from collections.abc import AsyncIterator
        from contextlib import asynccontextmanager

        async with rollback_conn() as conn:

            @asynccontextmanager
            async def factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            gate = PreSpendGateImpl(conn_factory=factory, record_decisions=False)
            request = PreSpendRequest(
                entity_id=new_entity_id(),
                entity_type=EntityType.ACCOUNT,
                field_key="account.totally_unregistered_field",
                source_tier=2,
                run_id=new_run_id(),
            )
            decision = await gate.check(request)
            assert decision.verdict.value == "reject"
            assert any("not registered" in reason for reason in decision.reasons)

    run_async(_run())
