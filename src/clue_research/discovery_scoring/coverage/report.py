"""The durable coverage read path (M6.5 / ENG-150) — reconstruct a run's coverage from telemetry.

The estimator (``estimator.py``) is pure; this is the thin, read-only layer that gathers its inputs
from what the discovery run durably wrote and the source registry already holds, so coverage is
**queryable by ``run_id``** after the fact (the M6.4 checkpoint + M13 observability seam) with no
dependence on in-memory run state:

* per-channel yield counters + ``stopping_reason`` — from the ``source_yield`` telemetry the
  discovery phase wrote (M6.1/M6.2), keyed by ``run_id`` (the ``disposition.kind = 'discovery'``
  rows). Discovery's yield write is append-only, so a M7 replay appends a *second* identical row per
  channel — we therefore take the **latest** measurement per ``(run_id, source_key)``, never the sum
  (summing would double-count a replay);
* the account-scope channel **universe** + ``geo_coverage`` — from the ``source_manifest`` registry
  (M4); ``entity_scope ∈ {account, both}``;
* the **planned** channel order + target geos — from the ICP spec's discovery strategy (so the curve
  is ordered by search priority, deterministically, not by wall-clock write time).

``coverage_report`` returns ``None`` when a run has no discovery telemetry (nothing to report); it
writes nothing (coverage gates nothing).
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import EntityScope, ICPSpec, RunId, decode_jsonb
from clue_research.discovery_scoring.coverage.config import (
    DEFAULT_COVERAGE_CONFIG,
    CoverageConfig,
)
from clue_research.discovery_scoring.coverage.estimator import estimate_coverage
from clue_research.discovery_scoring.coverage.results import (
    ChannelObservation,
    CoverageReport,
    UnsearchedChannel,
)
from clue_research.discovery_scoring.discovery import (
    DiscoveryStrategy,
    DiscoveryStrategyError,
    StoppingReason,
)
from clue_research.sources import entity_scope_serves, list_sources

# ICP-filter keys naming a target geography (the discovery strategy's ``icp_filters`` is free-form
# — M6 owns its meaning, D5/D6 — so geo is matched by a small synonym set, case-insensitively).
_GEO_KEYS = frozenset(
    {"geo", "geos", "region", "regions", "country", "countries", "hq_geo", "geo_coverage"}
)


def _strategy_geos(strategy: DiscoveryStrategy) -> tuple[str, ...]:
    """The ICP's target region codes pulled from the discovery strategy's free-form ``icp_filters``
    (empty ⇒ no geo constraint). Deduplicated, first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for key, value in strategy.icp_filters.items():
        if key.lower() not in _GEO_KEYS:
            continue
        values = value if isinstance(value, list) else [value]
        for raw in values:
            if isinstance(raw, str) and raw not in seen:
                seen.add(raw)
                out.append(raw)
    return tuple(out)


def _parse_strategy(spec: ICPSpec | None) -> DiscoveryStrategy:
    """The typed discovery strategy for ``spec`` (an empty strategy when absent/malformed — a
    coverage read must never fail on a bad slot; it just loses the planned-order/geo refinement)."""
    if spec is None:
        return DiscoveryStrategy()
    try:
        return DiscoveryStrategy.from_slot(spec.discovery_strategy)
    except DiscoveryStrategyError:
        return DiscoveryStrategy()


@dataclass(frozen=True)
class _DiscoveryTelemetry:
    """The run-level discovery telemetry coverage reads back from ``source_yield``: the per-channel
    observations plus the run-level facts denormalised onto each discovery row (the stopping reason
    and the M6.2 admitted-vs-seen counts). The run-level facts are absent on a legacy row."""

    observations: tuple[ChannelObservation, ...]
    stopping_reason: StoppingReason
    admitted: int | None
    needs_review: int | None
    rejected: int | None


async def _load_discovery_observations(
    conn: AsyncConnection, *, run_id: RunId
) -> _DiscoveryTelemetry:
    """The per-channel observations + the run's stopping reason + admitted-vs-seen counts.

    Takes the **latest** ``kind = 'discovery'`` row per ``source_key`` for this ``run_id``
    (``DISTINCT ON`` over ``recorded_at DESC`` — robust to a M7 replay's appended duplicate rows).
    The ``stopping_reason`` and the run-level admitted/needs_review/rejected counts are denormalised
    onto each discovery row; any row carries them (they agree), default ``EXHAUSTED`` / ``None`` for
    a legacy row written before they were stamped."""
    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (source_key)
                           source_key, disposition, cost_cents
                    FROM source_yield
                    WHERE run_id = :run_id AND disposition->>'kind' = 'discovery'
                    ORDER BY source_key, recorded_at DESC, id DESC
                    """
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .all()
    )
    observations: list[ChannelObservation] = []
    stopping_reason = StoppingReason.EXHAUSTED
    admitted = needs_review = rejected = None
    for row in rows:
        dispo = decode_jsonb(row["disposition"]) or {}
        if not isinstance(dispo, dict):
            continue
        reason_raw = dispo.get("stopping_reason")
        if isinstance(reason_raw, str):
            with contextlib.suppress(ValueError):
                stopping_reason = StoppingReason(reason_raw)
        admitted = _opt_int(dispo.get("admitted"), admitted)
        needs_review = _opt_int(dispo.get("needs_review"), needs_review)
        rejected = _opt_int(dispo.get("rejected"), rejected)
        observations.append(
            ChannelObservation(
                source_key=str(row["source_key"]),
                records_returned=_as_int(dispo.get("records_returned")),
                new_candidates=_as_int(dispo.get("new_candidates")),
                errors=_as_int(dispo.get("errors")),
                cost_cents=row["cost_cents"],
            )
        )
    return _DiscoveryTelemetry(
        observations=tuple(observations),
        stopping_reason=stopping_reason,
        admitted=admitted,
        needs_review=needs_review,
        rejected=rejected,
    )


def _as_int(value: object) -> int:
    """A non-negative int from a jsonb scalar (a malformed/absent counter reads ``0``)."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return 0


def _opt_int(value: object, current: int | None) -> int | None:
    """A non-negative int from a jsonb scalar, or ``current`` when the value is absent/malformed (so
    a denormalised run-level count that is missing on one row keeps the value seen on another)."""
    if isinstance(value, bool):
        return current
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return current


async def _load_account_universe(conn: AsyncConnection) -> tuple[UnsearchedChannel, ...]:
    """The universe of account-scope channels the registry could cover (``entity_scope`` serves
    ``account`` — i.e. ``account`` or ``both`` — active) — the set the unsearched-channels diff
    subtracts the searched channels from.

    "ICP applicability" (spec AC2) is realised here as the two axes the ``source_manifest`` actually
    exposes: account ``entity_scope`` + ``geo_coverage`` (the estimator applies the geo filter). The
    registry carries no vertical/pack column, so finer applicability (industry/pack relevance) is a
    deferred refinement; over-listing an inapplicable account-scope channel is the *safe* direction:
    it can only under-claim coverage, never imply exhaustiveness (Doc C §7)."""
    rows = await list_sources(conn, active=True)
    return tuple(
        UnsearchedChannel(source_key=row.source_key, tier=row.tier, geo_coverage=row.geo_coverage)
        for row in rows
        if entity_scope_serves(row.entity_scope, EntityScope.ACCOUNT)
    )


def _order_by_plan(
    observations: Sequence[ChannelObservation], planned: Sequence[str]
) -> tuple[ChannelObservation, ...]:
    """Order the observations by the ICP's planned channel priority (then ``source_key``), so the
    diminishing-yield curve follows search order deterministically — independent of write time."""
    index = {key: position for position, key in enumerate(planned)}
    return tuple(
        sorted(observations, key=lambda o: (index.get(o.source_key, len(index)), o.source_key))
    )


async def coverage_report(
    conn: AsyncConnection,
    *,
    run_id: RunId,
    spec: ICPSpec | None = None,
    admitted: int | None = None,
    needs_review: int | None = None,
    rejected: int | None = None,
    config: CoverageConfig = DEFAULT_COVERAGE_CONFIG,
) -> CoverageReport | None:
    """The coverage-confidence report for discovery ``run_id`` (the M6.5 seam), or ``None`` when the
    run has no discovery telemetry.

    Reads the durable per-channel yield + ``stopping_reason`` (``source_yield``), the account-scope
    channel universe (``source_manifest``), and the planned-channel order + target geos (the ICP
    ``spec``'s discovery strategy), then defers to the pure :func:`estimate_coverage`. The method
    lives entirely behind that call, so it is swappable without touching this read path or any
    consumer. ``admitted`` / ``needs_review`` / ``rejected`` (the M6.2 admitted-vs-seen context)
    default to the counts the discovery phase denormalised onto the telemetry; an explicit argument
    overrides them."""
    telemetry = await _load_discovery_observations(conn, run_id=run_id)
    if not telemetry.observations:
        return None
    strategy = _parse_strategy(spec)
    universe = await _load_account_universe(conn)
    return estimate_coverage(
        run_id=run_id,
        observations=_order_by_plan(telemetry.observations, strategy.channels),
        stopping_reason=telemetry.stopping_reason,
        universe=universe,
        icp_geos=_strategy_geos(strategy),
        admitted=admitted if admitted is not None else telemetry.admitted,
        needs_review=needs_review if needs_review is not None else telemetry.needs_review,
        rejected=rejected if rejected is not None else telemetry.rejected,
        config=config,
    )


__all__ = ["coverage_report"]
