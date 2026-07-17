"""Pure tests for the recursion policy-as-data (M7.2) — no DB.

``RecursionPolicy`` is the versioned, per-ICP-overridable dial behind the bounded recursion knob.
These assert the per-tier cap resolution, the eligibility rule, validation on load, and that
retuning the dial is a *config* change (an overlay), never a code change.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_config import (
    Config,
    ConfigOverlay,
    OverlayStore,
    RecursionPolicy,
    TierRecursionCaps,
    get_config,
)


def test_caps_for_resolves_per_tier_with_default_fallback() -> None:
    policy = RecursionPolicy()
    assert policy.caps_for("top").max_depth == 2
    assert policy.caps_for("high").max_depth == 1
    # an unlisted tier falls back to the conservative default — no recursion.
    assert policy.caps_for("low").max_depth == 0
    assert policy.caps_for("anything-else").max_depth == 0


def test_eligibility_only_for_resonance_and_facet_classes() -> None:
    policy = RecursionPolicy()
    assert policy.is_eligible("account.resonance")
    assert policy.is_eligible("account.resonance.culture")  # nests under an eligible class
    assert policy.is_eligible("contact.facet")
    assert not policy.is_eligible("account")
    assert not policy.is_eligible("core")
    assert not policy.is_eligible("contact")


def test_validation_rejects_out_of_range_caps() -> None:
    with pytest.raises(ValidationError):
        TierRecursionCaps(max_depth=3)  # max_depth is bounded 0..2
    with pytest.raises(ValidationError):
        TierRecursionCaps(max_facet_workers_per_aspect=-1)
    with pytest.raises(ValidationError):
        TierRecursionCaps(max_aspect_workers=-1)


def test_default_config_carries_a_recursion_policy() -> None:
    cfg = Config(client_id="acme")
    assert isinstance(cfg.recursion_policy, RecursionPolicy)
    assert cfg.recursion_policy.caps_for("top").max_depth == 2


def test_retuning_is_a_config_overlay_not_a_code_change() -> None:
    # The Doc C §8 deferred numbers are tuned by overriding the policy per client/ICP — data, not
    # code. Here a client raises every tier to depth 2 and widens the facet cap via an overlay.
    store = OverlayStore()
    tuned = RecursionPolicy(
        by_tier={
            "top": TierRecursionCaps(
                max_depth=2, max_aspect_workers=12, max_facet_workers_per_aspect=8
            ),
            "low": TierRecursionCaps(
                max_depth=1, max_aspect_workers=4, max_facet_workers_per_aspect=2
            ),
        }
    )
    store.set_client_overlay("acme", ConfigOverlay(recursion_policy=tuned))

    cfg = get_config("acme", store=store)
    # the overlay won: "low" now recurses one level, the facet cap widened — with zero code change.
    assert cfg.recursion_policy.caps_for("low").max_depth == 1
    assert cfg.recursion_policy.caps_for("top").max_facet_workers_per_aspect == 8
    # an unconfigured client still gets the conservative default.
    assert get_config("other", store=store).recursion_policy.caps_for("low").max_depth == 0
