"""M11.3 — the **per-field** tier-4 verification-health surface (Doc C §6).

``obs.record_verification_health`` emits the tier-4 faithfulness-judge pass-rate as an AGGREGATE (no
field breakdown). The M11.3 spec asks for the *per-field* view — the share of **each** synthesis
field's tier-4 claims that pass the faithfulness judge — so the M13.4 verification-health surface
and the M4.6 source-learning loop (staged-flow §7e) can spot a field whose synthesis quality
regressed after a model/resolver swap, not just an aggregate dip.

This dimensions the SAME tier-4 metrics with a ``field_key`` attribute (one metric, dimensioned —
summing across ``field_key`` recovers the aggregate). It imports only ``obs`` (``synthesis -> obs``
is permitted); the live call site — the per-account verification pass / the ``api`` composition
root,
invoking it with the judged synthesis claims — is the deferred api-root integration step.

DO NOT also call ``obs.record_verification_health`` over the *same* claims: both bump
``tier4.total``/``tier4.passed`` and the counts would double. Pick one surface per claim set — this
one for synthesis claims (it carries the field breakdown the aggregate lacks). (Same "two surfaces,
do not sum" caution as the M9.4×M13.4 strong-binding metrics.)
"""

from __future__ import annotations

from collections.abc import Iterable

from clue_core import Claim, VerificationStatus
from clue_research.obs.metrics import (
    METRIC_TIER4_PASSED,
    METRIC_TIER4_TOTAL,
    MetricSink,
    get_metric_sink,
)


def record_synthesis_health(claims: Iterable[Claim], *, sink: MetricSink | None = None) -> None:
    """Emit the per-field tier-4 faithfulness pass-rate (Doc C §6).

    For every tier-4 claim, bump ``research.verification.tier4.total{field_key}`` and — when the
    faithfulness judge (M9.3) marked it ``verified`` — ``research.verification.tier4.passed
    {field_key}``. The per-field pass-rate the surface reads is ``passed / total`` at that
    ``field_key``. Tier≤3 claims are skipped (the faithfulness judge governs only tier-4 synthesis,
    substrate §6). Idempotency/dedup of the claim set is the caller's concern (counters accumulate).
    """
    sink = sink or get_metric_sink()
    for claim in claims:
        if claim.source_tier != 4:
            continue
        label = {"field_key": claim.field_key}
        sink.add(METRIC_TIER4_TOTAL, 1, label)
        if claim.verification_status is VerificationStatus.VERIFIED:
            sink.add(METRIC_TIER4_PASSED, 1, label)
