"""M0.5 acceptance: metric emitters increment correctly from claim provenance."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from io import StringIO

import pytest
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

from clue_core import (
    Claim,
    ExtractionMethod,
    IdentityBinding,
    VerificationStatus,
)
from clue_obs.otel import (
    METRIC_CLAIMS_SURVIVING,
    METRIC_CLAIMS_TOTAL,
    METRIC_CONTACT_CLAIMS_TOTAL,
    METRIC_CONTACT_STRONG_BINDING,
    METRIC_COST_CAP_CENTS,
    METRIC_COST_CENTS,
    METRIC_PHASE_PROGRESS,
    METRIC_TIER4_PASSED,
    METRIC_TIER4_TOTAL,
    InMemorySink,
    configure_metric_exporter,
    get_metric_sink,
    record_cost_burndown,
    record_phase_progress,
    record_source_yield,
    record_verification_health,
)


def _verified(claim: Claim) -> Claim:
    return claim.model_copy(update={"verification_status": VerificationStatus.VERIFIED})


def test_source_yield_counts_surviving_by_source(make_account: Callable[..., Claim]) -> None:
    sink = InMemorySink()
    claims = [
        _verified(make_account(source_url="https://a")),
        make_account(source_url="https://a"),  # unverified -> does not survive
        _verified(make_account(source_url="https://b")),
    ]
    record_source_yield(claims, sink=sink)
    assert sink.counter(METRIC_CLAIMS_TOTAL, source="unregistered-url") == 3
    assert sink.counter(METRIC_CLAIMS_SURVIVING, source="unregistered-url") == 2
    assert all("https://" not in repr(key) for key in sink.counters)


def test_real_otel_sink_exports_and_restores_without_secret_attributes() -> None:
    prior = get_metric_sink()
    output = StringIO()
    runtime = configure_metric_exporter(
        ConsoleMetricExporter(out=output),
        service_name="clue-metric-test",
        export_interval_millis=60_000,
    )
    try:
        runtime.sink.add(
            "agent.context.cards.total",
            1,
            {"card_kind": "client_knowledge", "token": "never-export-this-secret"},
        )
        assert runtime.provider.force_flush(timeout_millis=5_000)
    finally:
        runtime.shutdown()
    exported = output.getvalue()
    assert "agent.context.cards.total" in exported
    assert "client_knowledge" in exported
    assert "never-export-this-secret" not in exported
    assert get_metric_sink() is prior


def test_verification_health(
    make_account: Callable[..., Claim], make_contact: Callable[..., Claim]
) -> None:
    sink = InMemorySink()
    claims = [
        _verified(
            make_account(
                source_tier=4, extraction_method=ExtractionMethod.LLM_SYNTHESIS, evidence_span="x"
            )
        ),
        make_account(
            source_tier=4, extraction_method=ExtractionMethod.LLM_SYNTHESIS, evidence_span="y"
        ),  # tier-4, judge not passed
        make_contact(identity_binding=IdentityBinding.STRONG),
        make_contact(identity_binding=IdentityBinding.WEAK),
    ]
    record_verification_health(claims, sink=sink)
    assert sink.counter(METRIC_TIER4_TOTAL) == 2
    assert sink.counter(METRIC_TIER4_PASSED) == 1
    assert sink.counter(METRIC_CONTACT_CLAIMS_TOTAL) == 2
    assert sink.counter(METRIC_CONTACT_STRONG_BINDING) == 1


def test_cost_burndown_sums_exactly(make_account: Callable[..., Claim]) -> None:
    sink = InMemorySink()
    claims = [make_account(cost_cents=Decimal("1.5")), make_account(cost_cents=Decimal("2.0"))]
    record_cost_burndown(claims, cap_cents=Decimal("100"), sink=sink)
    assert sink.gauge_value(METRIC_COST_CENTS) == 3.5
    assert sink.gauge_value(METRIC_COST_CAP_CENTS) == 100.0


def test_phase_progress(make_account: Callable[..., Claim]) -> None:
    sink = InMemorySink()
    record_phase_progress("discovery", completed=3, total=10, sink=sink)
    assert sink.gauge_value(METRIC_PHASE_PROGRESS, phase="discovery") == 0.3
    with pytest.raises(ValueError, match="unknown campaign phase"):
        record_phase_progress("not_a_phase", completed=1, total=2, sink=sink)
