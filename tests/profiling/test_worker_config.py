"""Lever 1/2 — the deep workers read the per-run source policies off the layered config (DB-free).

Proves the live-wiring crux without a DB: the account-axis worker resolves the waterfall stop bar
(``ConfidenceThresholds``, lever 1) + the planner tier reach (``SourcePlanPolicy``, lever 2) from
``get_config`` keyed by the run's ``client_id`` (via an injected ``OverlayStore``), and falls back
to the conservative defaults when no client coordinate / no overlay is present — so behaviour is
unchanged unless an overlay is registered.
"""

from __future__ import annotations

import pytest

from clue_research.config import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    DEFAULT_SOURCE_PLAN_POLICY,
    ConfidenceThresholds,
    ConfigOverlay,
    OverlayStore,
    SourcePlanPolicy,
)
from clue_research.profiling import AspectProfilingWorker
from clue_research.profiling.context import RunContext


def test_worker_resolves_policies_from_overlay() -> None:
    store = OverlayStore()
    store.set_client_overlay(
        "acme",
        ConfigOverlay(
            confidence_thresholds=ConfidenceThresholds(default=0.95),
            source_plan_policy=SourcePlanPolicy(tier_scope=3, prefer_deep_sources=True),
        ),
    )
    worker = AspectProfilingWorker("account", config_store=store)
    thresholds, plan_policy = worker._source_policies(RunContext(client_id="acme"))
    assert thresholds.default == pytest.approx(0.95)
    # tier_scope=3 widened to include tier-4 by prefer_deep_sources (lever 2).
    assert plan_policy.effective_max_tier() == 4


def test_worker_defaults_without_client_or_overlay() -> None:
    worker = AspectProfilingWorker("account", config_store=OverlayStore())
    # No client coordinate → conservative defaults, no config read at all.
    assert worker._source_policies(RunContext()) == (
        DEFAULT_CONFIDENCE_THRESHOLDS,
        DEFAULT_SOURCE_PLAN_POLICY,
    )
    # A known client with no overlay → the dense defaults from get_config (unchanged behaviour).
    thresholds, plan_policy = worker._source_policies(RunContext(client_id="globex"))
    assert thresholds == DEFAULT_CONFIDENCE_THRESHOLDS
    assert plan_policy == DEFAULT_SOURCE_PLAN_POLICY


def test_worker_icp_overlay_wins_over_client() -> None:
    store = OverlayStore()
    store.set_client_overlay(
        "acme",
        ConfigOverlay(confidence_thresholds=ConfidenceThresholds(default=0.5)),
    )
    store.set_icp_overlay(
        "acme",
        "icp-eu",
        ConfigOverlay(confidence_thresholds=ConfidenceThresholds(default=0.95)),
    )
    worker = AspectProfilingWorker("account", config_store=store)
    thresholds, _ = worker._source_policies(
        RunContext(client_id="acme", icp_key="icp-eu", icp_version=1)
    )
    assert thresholds.default == pytest.approx(0.95)
