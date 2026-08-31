"""The Stage-0 recon envelopes are deployment settings, and the composition root uses them.

Founder ruling (``docs/specs/FI-onboarding-contract-gap-review.md`` §9, 2026-08-13): onboarding
forms the base of everything downstream, so an envelope must **never** truncate onboarding
research — quality before cost. Until this landed the ruling had no mechanism: ``Stage0Policy``
was a frozen model of constants and ``build_toolbelt`` hard-wired ``DEFAULT_STAGE0_POLICY``'s 5¢
fast cap, which at the default ``CLUE_SCRAPE_BACKEND=firecrawl`` (~1¢/fetch) released the user
with the last checklist groups reading "stopped at the research budget".

Two things are pinned here:

1. the env → :class:`~clue_config.Settings` → :class:`~clue_config.Stage0Policy` round trip
   (:func:`~clue_config.stage0_policy_from_settings`), and
2. that the composed ``start_recon`` tool actually runs under the settings-derived policy — a
   mechanism nothing reads is not a mechanism.

``DEFAULT_STAGE0_POLICY`` stays at 5¢/100¢ on purpose (many tests and uncomposed callers pin that
library default); the *production* default is the 25¢ settings one, and that difference is
asserted rather than left to be rediscovered.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import (
    DEFAULT_STAGE0_POLICY,
    Settings,
    load_settings,
    stage0_policy_from_settings,
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_default_settings_raise_the_fast_envelope_above_the_library_default() -> None:
    """The production default covers the whole eleven-field firecrawl walk (~11¢) with headroom."""
    policy = stage0_policy_from_settings(_settings())
    assert policy.fast_budget_cents == Decimal("25")
    assert policy.background_budget_cents == Decimal("100")
    assert DEFAULT_STAGE0_POLICY.fast_budget_cents == Decimal("5")


def test_the_two_envelopes_round_trip_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment raises a cap with an env var, not a code change (the ruling's mechanism)."""
    monkeypatch.setenv("CLUE_STAGE0_FAST_BUDGET_CENTS", "60")
    monkeypatch.setenv("CLUE_STAGE0_BACKGROUND_BUDGET_CENTS", "250")
    policy = stage0_policy_from_settings(load_settings(_env_file=None))
    assert policy.fast_budget_cents == Decimal("60")
    assert policy.background_budget_cents == Decimal("250")


def test_only_the_budgets_move_dedupe_and_readiness_stay_the_versioned_constants() -> None:
    """Cost knobs are deployment settings; the dedupe window and the readiness floors are
    correctness/governance and must not become per-deployment."""
    policy = stage0_policy_from_settings(_settings(stage0_fast_budget_cents=Decimal("7")))
    assert policy.recon_dedupe_ttl_seconds == DEFAULT_STAGE0_POLICY.recon_dedupe_ttl_seconds
    assert policy.readiness == DEFAULT_STAGE0_POLICY.readiness


def test_a_zero_envelope_is_refused_at_construction() -> None:
    """A zero cap researches nothing; the ruling says an envelope must never truncate onboarding,
    so a mistyped ``0`` fails loudly instead of silently shipping an empty onboarding."""
    with pytest.raises(ValueError):
        _settings(stage0_fast_budget_cents=Decimal("0"))


def test_build_toolbelt_composes_start_recon_under_the_settings_policy() -> None:
    """The composition root threads the settings-derived policy, not ``DEFAULT_STAGE0_POLICY``."""
    registry = build_toolbelt(storage=None, gateway=None, settings=_settings())
    policy = registry.get("start_recon")._policy  # type: ignore[attr-defined]
    assert policy.fast_budget_cents == Decimal("25")

    raised = build_toolbelt(
        storage=None,
        gateway=None,
        settings=_settings(stage0_fast_budget_cents=Decimal("80")),
    )
    assert raised.get("start_recon")._policy.fast_budget_cents == Decimal("80")  # type: ignore[attr-defined]
