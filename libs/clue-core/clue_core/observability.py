"""The M13.4 coverage-confidence projection — the one additive Wave-1 ``core`` contract.

M13.4's :class:`~clue_research.review.ObservabilitySurface` exposes a ``coverage_confidence`` panel
(Doc C §7): the estimated share of the addressable account set found *via the channels searched*
**plus the channels not yet searched** — a trust statement, never a "we found them all" claim. The
underlying estimate (M6.5) is computed by ``discovery_scoring.coverage_report`` and lives in the
``discovery_scoring`` package, which ``review`` may **not** import (the import-linter independence
contract). So this module is the small, additive ``core`` projection the coverage bridge crosses on:
the ``api`` composition root maps the ``discovery_scoring.CoverageReport`` (or the serialized copy
persisted on the M6.4 ``tier_checkpoint`` payload) onto :class:`CoverageReport`, and the
``review``-owned surface returns it.

It lives in ``core`` (not ``review``) because both the ``review`` surface and the ``api``-root
coverage reader bind to one definition, exactly like the M13.1 ``core.review`` seam — and because a
shared honest-coverage contract sits naturally alongside the scalar
``core.handoff.AccountHandoff.coverage_confidence`` stamp. It is deliberately a *minimal* projection
of what a client-facing panel shows (the band, the framing, the unsearched-channel gap list); the
estimator internals (the per-channel saturation curve, the capture-recapture inputs) stay in
``discovery_scoring``.

The honesty guarantee is structural: the percent is carried as the pre-rendered ``~X–Y%`` string
(from ``CoverageBand.as_percent()`` — bounded by the M6.5 coverage ceiling, so it can never read
``100%``), and the framing is the completeness-free statement. Architecture sources: Doc C §7
(coverage confidence — estimate + unsearched channels, not exhaustiveness); overview §1 ("coverage
confidence, not a completeness guarantee").
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from clue_core.primitives import RunId, UnitInterval


class UnsearchedChannel(BaseModel):
    """An account-scope channel the source registry *could* cover but the run did **not** query — a
    named, actionable coverage gap (Doc C §7: "name the unsearched channels"). Projection of
    ``discovery_scoring.coverage.UnsearchedChannel``; ``geo_coverage`` empty == global."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    tier: int
    geo_coverage: tuple[str, ...] = ()


class CoverageReport(BaseModel):
    """A read projection of the M6.5 coverage estimate (Doc C §7), surfaced by the M13.4
    observability surface — *coverage confidence, not a completeness guarantee*.

    ``estimate_percent`` is the pre-rendered honest band (``~X–Y%`` / ``~X%`` — never ``100%`` or
    "complete", enforced by the M6.5 ceiling upstream); ``coverage_low``/``high``/``point`` carry
    the
    numeric band for a client that wants it. ``channels_not_searched`` is the *non-empty* gap list
    that makes the honesty guarantee load-bearing — an empty list here would read as "we found them
    all", which this subsystem never claims. ``confidence`` is the qualitative trust label
    (``none``/``low``/``moderate``/``high``, carried as a plain string so this stays a
    self-contained
    ``core`` add with no mirrored enum). ``framing`` is the one-line completeness-free statement.

    A pure value object: produced by the ``api``-root coverage reader from the M6.5 report; the
    surface writes nothing and gates nothing on it (replaceability)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    coverage_low: UnitInterval
    coverage_high: UnitInterval
    coverage_point: UnitInterval
    confidence: str  # none | low | moderate | high (mirrors discovery_scoring.CoverageConfidence)
    estimate_percent: str  # the honest "~X–Y%" band — never "100%"/"complete"
    channels_searched: tuple[str, ...] = ()
    channels_not_searched: tuple[UnsearchedChannel, ...] = ()
    stopping_reason: str = ""
    framing: str = ""
    recommendation: str | None = None

    @property
    def is_complete_claim(self) -> bool:
        """Always ``False`` — this surface never asserts completeness (Doc C §7). A convenience for
        a
        client that wants to assert "the panel is honest" without parsing the percent string."""
        return False
