"""W1.6 — the logo placement policy vocabulary, and LUMB0810's severity.

RED CASE (Cursor pilot, `.context/ref-ads-pilot-cursor-report.md` §9.5): the
references demanded a reversed wordmark on a dark field; the kit's logo policy
said `["surface.page", "surface.card"]` and had no way to say otherwise, so the
agent placed the mark on `$surface.inverse`, took `LUMB0810`, and recorded the
deviation. `test_red_case_*` below holds the shape of that kit.

Founder ruling D5: LUMB0810 stays ADVISORY. It must not block the agent or an
export. The `test_lumb0810_*` group pins that, because nothing pinned it before.
"""

from __future__ import annotations

import pytest

from lumen_ingestion.logo_policy import (
    DARK_SURFACES,
    LIGHT_SURFACES,
    allowed_backgrounds_for,
    allows_inverse_surfaces,
    extend_allowed_backgrounds,
)

# ===========================================================================
# The vocabulary
# ===========================================================================


def test_red_case_a_light_only_kit_cannot_express_inverse_placement() -> None:
    """RED: the Cursor kit. A full-colour-only slot allows no dark surface."""
    allowed = allowed_backgrounds_for(["full_color"])
    assert allowed == ["surface.page", "surface.card"]
    assert "surface.inverse" not in allowed


def test_a_reversed_variant_makes_the_kit_able_to_express_inverse_placement() -> None:
    """GREEN: the same slot, once it holds the reversed mark the references want."""
    allowed = allowed_backgrounds_for(["full_color", "reversed"])
    assert allowed == ["surface.page", "surface.card", "surface.inverse", "surface.brand"]


@pytest.mark.parametrize("mode", ["reversed", "light", "REVERSED", " Light "])
def test_every_inverse_capable_colour_mode_is_recognised(mode: str) -> None:
    assert allows_inverse_surfaces([mode]) is True
    assert "surface.inverse" in allowed_backgrounds_for([mode])


@pytest.mark.parametrize("mode", ["full_color", "one_color", "dark", None, "", "nonsense"])
def test_a_mark_drawn_for_light_fields_stays_on_light_fields(mode: str | None) -> None:
    assert allows_inverse_surfaces([mode]) is False
    assert allowed_backgrounds_for([mode]) == list(LIGHT_SURFACES)


def test_the_light_surfaces_are_never_withdrawn() -> None:
    """This can only ever be MORE permissive — it must not create a new diagnostic.

    A slot holding only a reversed variant still allows the light surfaces, so no
    placement that was clean before becomes a LUMB0810 after this change.
    """
    for modes in (["reversed"], ["light"], ["reversed", "light"], []):
        assert set(LIGHT_SURFACES) <= set(allowed_backgrounds_for(modes))


def test_the_order_is_stable_so_kit_serializations_do_not_churn() -> None:
    assert allowed_backgrounds_for(["reversed", "full_color"]) == allowed_backgrounds_for(
        ["full_color", "reversed"]
    )
    assert allowed_backgrounds_for(["reversed"]) == list(LIGHT_SURFACES) + list(DARK_SURFACES)


# ===========================================================================
# Widening an existing policy (the human-curation path)
# ===========================================================================


def test_promoting_a_reversed_logo_widens_a_light_only_slot() -> None:
    widened = extend_allowed_backgrounds(["surface.page", "surface.card"], ["reversed"])
    assert widened == ["surface.page", "surface.card", "surface.inverse", "surface.brand"]


def test_widening_never_drops_an_allowance_somebody_added() -> None:
    widened = extend_allowed_backgrounds(["surface.custom", "surface.inverse"], ["reversed"])
    assert widened == ["surface.custom", "surface.inverse", "surface.brand"]


def test_promoting_a_full_colour_logo_changes_nothing() -> None:
    existing = ["surface.page", "surface.card"]
    assert extend_allowed_backgrounds(existing, ["full_color"]) == existing


def test_an_empty_policy_stays_empty() -> None:
    """An empty list means "do not check this slot"; turning the check on is not ours."""
    assert extend_allowed_backgrounds([], ["reversed"]) == []
    assert extend_allowed_backgrounds(None, ["reversed"]) == []


# ===========================================================================
# Ingestion populates it
# ===========================================================================


def _logo(asset_id: str, color_mode: str | None):
    from lumen_ingestion.evidence import EvidencePointer, LogoEvidence

    return LogoEvidence(
        asset_id=asset_id,
        color_mode_hint=color_mode,
        usage_hint="primary",
        pointer=EvidencePointer(source="website", locator="fixture"),
    )


def _build_logos(logos):
    from lumen_ingestion.evidence import BrandEvidence
    from lumen_ingestion.normalizer.emit import KitBuilder

    builder = KitBuilder(
        BrandEvidence(source={"kind": "website", "url": "https://example.test"}),
        brand_kit_id="bk_test",
        version=1,
        name="Test",
        created_at="2026-08-26T00:00:00Z",
    )
    builder.add_logos(logos)
    return builder.logos


def test_ingestion_expresses_inverse_allowance_for_a_light_and_dark_pair() -> None:
    """The spec's case: a kit that HAS both light and dark logo variants."""
    logos = _build_logos(
        [_logo("asset_a", "full_color"), _logo("asset_b", "reversed")]
    )
    assert logos["primary"]["allowed_backgrounds"] == [
        "surface.page",
        "surface.card",
        "surface.inverse",
        "surface.brand",
    ]


def test_ingestion_leaves_a_light_only_kit_light_only() -> None:
    logos = _build_logos([_logo("asset_a", "full_color")])
    assert logos["primary"]["allowed_backgrounds"] == ["surface.page", "surface.card"]


def test_ingestion_recognises_a_light_variant_not_only_a_reversed_one() -> None:
    """`light` is a real `LogoColorMode`; the pre-W1.6 rule only looked for `reversed`."""
    logos = _build_logos([_logo("asset_a", "light")])
    assert "surface.inverse" in logos["primary"]["allowed_backgrounds"]


# ===========================================================================
# LUMB0810 is ADVISORY (founder ruling D5) — nothing here may block
# ===========================================================================


def test_lumb0810_is_not_on_the_export_blocking_path() -> None:
    """Export classifies PREFLIGHT diagnostics; brand governance is a separate action.

    Even handed to the classifier directly, the point stands for the severity the
    agent actually sees: governance runs at `strictness="advisory"`, which makes
    every governance code a `warning`, and a warning never blocked export.
    """
    from lumen_api.export_policy import is_blocking_export_diagnostic

    advisory = {"code": "LUMB0810", "severity": "warning", "message": "logo on inverse"}
    assert is_blocking_export_diagnostic(advisory) is False


def test_the_agent_asks_for_governance_in_advisory_strictness() -> None:
    """The agent's own call site is what decides LUMB0810's severity for a turn.

    Pinned by source inspection rather than a live engine call: the severity is
    chosen in Rust from the strictness this call passes, so the Python-side
    guarantee IS this argument.
    """
    import inspect

    from lumen_agent.tools import substrate

    source = inspect.getsource(substrate.LumenDesignTools.preflight_design)
    assert 'validate_scene_brand_governance(' in source
    assert 'strictness="advisory"' in source
    assert "raise_on_error=False" in source


def test_governance_diagnostics_never_reach_the_finalize_gate(tmp_path, monkeypatch) -> None:
    """P0.3 partitions `_latest_preflight_diagnostics`, which excludes governance.

    So a LUMB0810 can never refuse a finalize, whatever severity the engine gave
    it — the founder's D5 "no mechanical guards blocking the deepagent".
    """
    import inspect

    from lumen_agent.tools import substrate

    source = inspect.getsource(substrate.LumenDesignTools.preflight_design)
    # The gate's input is the RAW preflight list; the governance list is only
    # ever appended to the DISPLAY list handed back to the agent.
    assert "self._latest_preflight_diagnostics = raw_diagnostics" in source
    assert "self._latest_preflight_diagnostics = raw_diagnostics + governance" not in source

    finalize = inspect.getsource(substrate.LumenDesignTools.finalize_run)
    assert "self._latest_preflight_diagnostics" in finalize
    assert "governance_diagnostics" not in finalize
