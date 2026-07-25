"""M0.4 — layered config loader tests (ENG-120).

Covers the loader acceptance criteria of docs/specs/M00 §M0.4:
* defaults → client → ICP precedence;
* rejects an unknown posture/jurisdiction/out-of-range cap on load (fail fast);
* versioned layers recorded on the merged Config;
* get_policy returns the merged policy.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_config import (
    ConfidenceThresholds,
    Config,
    ConfigError,
    ConfigOverlay,
    ConfigVersion,
    JurisdictionPolicy,
    OverlayStore,
    Posture,
    ScoringRubric,
    SourcePlanPolicy,
    SourceScope,
    SupervisorPolicy,
    get_config,
    get_policy,
    overlay_from_mapping,
)


@pytest.fixture
def store() -> OverlayStore:
    """A fresh, isolated overlay store per test (no shared global state)."""
    return OverlayStore()


def test_defaults_when_no_overlays(store: OverlayStore) -> None:
    cfg = get_config("acme", store=store)
    assert isinstance(cfg, Config)
    assert cfg.workspace_id == "acme"
    assert cfg.icp_id is None
    assert cfg.policy.posture is Posture.CONSERVATIVE_DEFAULT
    # only the defaults layer contributed
    assert [v.layer for v in cfg.applied_versions] == ["defaults"]


def test_client_overlay_overrides_defaults(store: OverlayStore) -> None:
    store.set_client_overlay(
        "acme",
        ConfigOverlay(
            version=ConfigVersion(layer="client", version=3, label="acme-regulated"),
            policy=JurisdictionPolicy(posture=Posture.PROFESSIONAL_PUBLIC_ONLY),
        ),
    )
    cfg = get_config("acme", store=store)
    assert cfg.policy.posture is Posture.PROFESSIONAL_PUBLIC_ONLY
    assert cfg.policy.source_scope is SourceScope.PROFESSIONAL_PUBLIC_ONLY
    assert [(v.layer, v.version) for v in cfg.applied_versions] == [
        ("defaults", 1),
        ("client", 3),
    ]


def test_icp_overlay_wins_over_client(store: OverlayStore) -> None:
    """Precedence: defaults → client → ICP. The ICP layer's sub-tree replaces the client's."""
    store.set_client_overlay(
        "acme",
        ConfigOverlay(scoring_rubric=ScoringRubric(fit_weight=0.7, intent_weight=0.3)),
    )
    store.set_icp_overlay(
        "acme",
        "icp-eu",
        ConfigOverlay(scoring_rubric=ScoringRubric(fit_weight=0.2, intent_weight=0.8)),
    )
    cfg = get_config("acme", "icp-eu", store=store)
    assert cfg.scoring_rubric.fit_weight == pytest.approx(0.2)
    assert cfg.scoring_rubric.intent_weight == pytest.approx(0.8)
    assert [v.layer for v in cfg.applied_versions] == ["defaults", "client", "icp"]


def test_icp_inherits_unset_subtrees_from_client(store: OverlayStore) -> None:
    """An overlay only changes what it sets; unset sub-trees inherit from beneath."""
    store.set_client_overlay(
        "acme",
        ConfigOverlay(policy=JurisdictionPolicy(posture=Posture.PROFESSIONAL_PUBLIC_ONLY)),
    )
    # ICP overlay touches only scoring; policy is inherited from the client layer.
    store.set_icp_overlay(
        "acme",
        "icp-eu",
        ConfigOverlay(scoring_rubric=ScoringRubric(fit_weight=0.6, intent_weight=0.4)),
    )
    cfg = get_config("acme", "icp-eu", store=store)
    assert cfg.policy.posture is Posture.PROFESSIONAL_PUBLIC_ONLY  # inherited from client
    assert cfg.scoring_rubric.fit_weight == pytest.approx(0.6)  # from ICP


def test_supervisor_policy_is_versioned_and_icp_overridable(store: OverlayStore) -> None:
    store.set_client_overlay(
        "acme",
        ConfigOverlay(
            supervisor_policy=SupervisorPolicy(
                version="client-supervisor-v2",
                canary_size=4,
            )
        ),
    )
    store.set_icp_overlay(
        "acme",
        "icp-eu",
        ConfigOverlay(
            supervisor_policy=SupervisorPolicy(
                version="icp-supervisor-v3",
                canary_size=2,
            )
        ),
    )
    assert get_config("acme", store=store).supervisor_policy.version == "client-supervisor-v2"
    icp_policy = get_config("acme", "icp-eu", store=store).supervisor_policy
    assert icp_policy.version == "icp-supervisor-v3"
    assert icp_policy.canary_size == 2


def test_get_policy_reflects_merged_overlays(store: OverlayStore) -> None:
    store.set_client_overlay(
        "acme",
        ConfigOverlay(policy=JurisdictionPolicy(posture=Posture.GATHER_BROADLY_GATE_AT_USE)),
    )
    policy = get_policy("acme", store=store)
    assert policy.posture is Posture.GATHER_BROADLY_GATE_AT_USE
    assert policy.source_scope is SourceScope.FULL_SWEEP


def test_overlay_from_mapping_accepts_valid_data() -> None:
    overlay = overlay_from_mapping(
        {
            "policy": {"posture": "professional_public_only", "jurisdiction": "us_state"},
            "budget_caps": {"per_campaign_hard_cap_cents": "100000"},
        }
    )
    assert overlay.policy is not None
    assert overlay.policy.posture is Posture.PROFESSIONAL_PUBLIC_ONLY
    assert overlay.budget_caps is not None
    assert overlay.budget_caps.per_campaign_hard_cap_cents == Decimal("100000")


def test_loader_rejects_unknown_posture() -> None:
    with pytest.raises(ConfigError):
        overlay_from_mapping({"policy": {"posture": "do_whatever_you_want"}})


def test_loader_rejects_unknown_jurisdiction() -> None:
    with pytest.raises(ConfigError):
        overlay_from_mapping({"policy": {"jurisdiction": "narnia"}})


def test_loader_rejects_out_of_range_cap() -> None:
    with pytest.raises(ConfigError):
        overlay_from_mapping({"budget_caps": {"per_campaign_hard_cap_cents": "-5"}})


def test_loader_rejects_out_of_range_scoring_weight() -> None:
    with pytest.raises(ConfigError):
        overlay_from_mapping({"scoring_rubric": {"fit_weight": 1.5, "intent_weight": 0.0}})


def test_isolated_clients_do_not_leak(store: OverlayStore) -> None:
    store.set_client_overlay(
        "acme",
        ConfigOverlay(policy=JurisdictionPolicy(posture=Posture.PROFESSIONAL_PUBLIC_ONLY)),
    )
    # A different client with no overlay still gets the conservative default.
    other = get_config("globex", store=store)
    assert other.policy.posture is Posture.CONSERVATIVE_DEFAULT


def test_budget_caps_dict_value_negative_rejected() -> None:
    with pytest.raises(ConfigError):
        overlay_from_mapping({"budget_caps": {"per_account_cap_cents": {"top": "-1"}}})


def test_budget_caps_valid_tiered() -> None:
    overlay = overlay_from_mapping(
        {"budget_caps": {"per_account_cap_cents": {"top": "500", "high": "200"}}}
    )
    assert overlay.budget_caps is not None
    assert overlay.budget_caps.per_account_cap_cents["top"] == Decimal("500")


def test_source_plan_policy_overlay_overrides_defaults(store: OverlayStore) -> None:
    """Lever 2: a client overlay flips the planner's tier reach (the deep-research toggle)."""
    store.set_client_overlay(
        "acme",
        ConfigOverlay(source_plan_policy=SourcePlanPolicy(tier_scope=3, prefer_deep_sources=True)),
    )
    cfg = get_config("acme", store=store)
    assert cfg.source_plan_policy.tier_scope == 3
    assert cfg.source_plan_policy.prefer_deep_sources is True
    # A different client still gets the conservative (all-tiers, no-prefer) default.
    assert get_config("globex", store=store).source_plan_policy == SourcePlanPolicy()


def test_confidence_thresholds_overlay_and_icp_precedence(store: OverlayStore) -> None:
    """Lever 1: the waterfall stop bar is layered config; the ICP layer wins over the client."""
    store.set_client_overlay(
        "acme",
        ConfigOverlay(confidence_thresholds=ConfidenceThresholds(default=0.5)),
    )
    store.set_icp_overlay(
        "acme",
        "icp-eu",
        ConfigOverlay(confidence_thresholds=ConfidenceThresholds(default=0.95)),
    )
    assert get_config("acme", store=store).confidence_thresholds.default == pytest.approx(0.5)
    icp = get_config("acme", "icp-eu", store=store).confidence_thresholds
    assert icp.default == pytest.approx(0.95)


def test_overlay_from_mapping_rejects_bad_tier_scope() -> None:
    with pytest.raises(ConfigError):
        overlay_from_mapping({"source_plan_policy": {"tier_scope": 9}})


def test_overlay_from_mapping_accepts_source_plan_policy() -> None:
    overlay = overlay_from_mapping(
        {"source_plan_policy": {"tier_scope": 4, "prefer_deep_sources": True}}
    )
    assert overlay.source_plan_policy is not None
    assert overlay.source_plan_policy.effective_max_tier() == 4
