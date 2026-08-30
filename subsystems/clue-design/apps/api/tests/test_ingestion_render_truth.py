"""Phase-1 brand-color overhaul: census + render-truth election.

The pinned red case throughout is the live apollo.io failure: a phone-widget
FOCUS ring (#03B2CB cyan) elected as the brand because stylesheet rule-text
mentioned it with button vocabulary, while the real CTA yellow — visible on
rendered buttons — carried no hints. Under render-truth election that outcome
must be impossible: mentions cannot vote, pixels can.
"""

from __future__ import annotations

import base64
import hashlib
import io

import pytest
from PIL import Image

from lumen_ingestion.capture.parse import parse_color_value, parse_site
from lumen_ingestion.capture.snapshot import Download, SiteSnapshot, Stylesheet
from lumen_ingestion.census import build_render_truth, merge_counts
from lumen_ingestion.evidence import (
    AccentTextFamily,
    CensusCluster,
    ColorEvidence,
    EvidencePointer,
    GradientStopFamily,
    RegionColorFamily,
    RenderTruth,
)
from lumen_ingestion.normalizer.cluster import cluster_colors
from lumen_ingestion.normalizer.roles import (
    _BRAND_FALLBACK,
    _render_truth_candidates,
    assign_light_roles,
)

APOLLO_CYAN = "#03B2CB"
APOLLO_YELLOW = "#ECF414"


def _parse_color(value: str):
    return parse_color_value(value, {}, diagnostics=None)


def _pointer(locator: str) -> EvidencePointer:
    return EvidencePointer(source="website", locator=locator)


def _color(value: str, weight: float, hints: list[str]) -> ColorEvidence:
    return ColorEvidence(
        value=value, weight=weight, theme="light", role_hints=hints,
        name=None, pointer=_pointer("css :: test"),
    )


# --- the counter side (census) ---------------------------------------------------


def _png(draw) -> bytes:
    img = Image.new("RGB", (400, 600), "#FFFFFF")
    draw(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _snapshot_with(shot: bytes, probe: dict) -> SiteSnapshot:
    sha = hashlib.sha256(shot).hexdigest()
    return SiteSnapshot(
        requested_url="https://example.com",
        final_url="https://example.com",
        fetched_at="2026-08-30T00:00:00+00:00",
        tier="rendered",
        html="<html></html>",
        downloads=[
            Download(
                url="https://example.com#screenshot", kind="screenshot",
                content_type="image/png",
                bytes_b64=base64.b64encode(shot).decode("ascii"), sha256=sha,
            )
        ],
        render_probe=probe,
    )


def test_merge_counts_unifies_quantization_neighbours() -> None:
    from collections import Counter

    counts = Counter({(252, 244, 20): 800, (244, 244, 20): 200, (4, 4, 4): 500})
    clusters = merge_counts(counts)
    hexes = [c["hex"] for c in clusters]
    assert len(hexes) == 2  # the two yellows are one color; black is the other
    assert clusters[0]["hex"] == "#FCF414"
    assert clusters[0]["share"] == pytest.approx(1000 / 1500)


def test_census_elects_button_region_and_masks_photographs() -> None:
    import random

    rng = random.Random(7)

    def draw(img: Image.Image) -> None:
        # A yellow CTA at (40,40)-(140,80); a photograph (noise) at (200,200)-(360,400).
        img.paste(Image.new("RGB", (100, 40), APOLLO_YELLOW), (40, 40))
        noise = Image.new("RGB", (160, 200))
        noise.putdata(
            [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(160 * 200)]
        )
        img.paste(noise, (200, 200))

    probe = {
        "viewport_width": 400,
        "tokens": {"--cta": "rgb(236, 244, 20)", "--focus-ring": APOLLO_CYAN},
        "samples": [
            {"kind": "body", "box": {"l": 0, "t": 0, "w": 400, "h": 600},
             "bg": "rgb(255, 255, 255)", "color": "rgb(17, 17, 17)"},
            {"kind": "button", "box": {"l": 40, "t": 40, "w": 100, "h": 40},
             "bg": "rgb(236, 244, 20)", "color": "rgb(0, 0, 0)"},
        ],
        "media": [{"l": 200, "t": 200, "w": 160, "h": 200}],
        "gradients": [],
        "canvas_viewport_fraction": 0.0,
    }
    truth = build_render_truth(_snapshot_with(_png(draw), probe), _parse_color)

    assert truth is not None
    assert truth.body_bg == "#FFFFFF"
    assert truth.page_clusters[0].hex == "#FCFCFC"  # white family (bucket center)
    assert truth.masked_fraction > 0.1  # the photograph left the census
    button_hexes = [f.hex for f in truth.button_families]
    assert any(h.startswith("#EC") or h.startswith("#F4") for h in button_hexes)
    # The focus-ring token resolves but that alone is NOT rendered evidence:
    # no census cluster carries the cyan.
    assert all(
        c.hex != APOLLO_CYAN for c in truth.page_clusters + truth.fold_clusters
    )


def test_census_keeps_low_diversity_brand_art_in_the_census() -> None:
    def draw(img: Image.Image) -> None:
        img.paste(Image.new("RGB", (160, 200), "#543CFC"), (200, 200))

    probe = {
        "viewport_width": 400,
        "tokens": {},
        "samples": [],
        "media": [{"l": 200, "t": 200, "w": 160, "h": 200}],  # flat brand panel, media-shaped
        "gradients": [],
    }
    truth = build_render_truth(_snapshot_with(_png(draw), probe), _parse_color)
    assert truth is not None
    assert truth.masked_fraction == 0.0  # brand art is chrome, not photography
    assert any(c.hex == "#544CFC" or c.hex.startswith("#54") for c in truth.page_clusters)


# --- the election side ------------------------------------------------------------


def _apollo_truth() -> RenderTruth:
    return RenderTruth(
        page_clusters=[CensusCluster(hex="#FCFCFC", share=0.76), CensusCluster(hex=APOLLO_YELLOW, share=0.006)],
        fold_clusters=[CensusCluster(hex=APOLLO_YELLOW, share=0.006)],
        button_families=[RegionColorFamily(hex=APOLLO_YELLOW, count=2), RegionColorFamily(hex="#040404", count=5)],
        accent_text=[],
        gradient_stops=[],
        body_bg="#FFFFFF",
        body_text="#202020",
        resolved_tokens={"--PhoneInput-color--focus": APOLLO_CYAN},
    )


def _apollo_clusters():
    """The old winner's evidence: cyan heavily mentioned with button vocabulary."""
    return cluster_colors(
        [
            _color(APOLLO_CYAN, 13.5, ["button-text", "custom-prop:--PhoneInput-color--focus"]),
            _color("#212121", 190.0, ["body-text", "link"]),
            _color("#FFFFFF", 60.0, ["page-bg"]),
        ]
    )


def test_apollo_red_case_yellow_elected_cyan_impossible() -> None:
    light = assign_light_roles(_apollo_clusters(), None, _apollo_truth())
    assert light.assignments["surface.brand"].hex == APOLLO_YELLOW
    assert light.assignments["surface.page"].hex == "#FFFFFF"
    elected = {a.hex.upper() for a in light.assignments.values()}
    assert APOLLO_CYAN not in elected  # mentions cannot vote; the focus ring is dead
    brand = light.assignments["surface.brand"]
    assert brand.basis == "measured"
    assert "rendered buttons" in brand.provenance  # evidence rides the assignment


def test_without_render_truth_the_legacy_election_still_runs() -> None:
    light = assign_light_roles(_apollo_clusters(), None, None)
    # The legacy path (PDF/upload/pre-probe bundles) still elects from clusters —
    # including, for this fixture, the old cyan answer. That is exactly why
    # website captures now carry render truth.
    assert light.assignments["surface.brand"].hex == APOLLO_CYAN


def test_single_button_cannot_outrank_gradient_with_token() -> None:
    truth = RenderTruth(
        page_clusters=[CensusCluster(hex="#FCFCFC", share=0.75), CensusCluster(hex="#DC742C", share=0.009)],
        fold_clusters=[CensusCluster(hex="#DC742C", share=0.009)],
        button_families=[RegionColorFamily(hex="#6CAC4C", count=1)],  # freshcontext's pale green
        gradient_stops=[GradientStopFamily(hex="#DC742C", area_fraction=0.05)],
        resolved_tokens={"--fc-accent-deep": "#DC742C"},
    )
    candidates = _render_truth_candidates(truth)
    assert candidates[0]["hex"] == "#DC742C"
    assert any("token --fc-accent-deep" in e for e in candidates[0]["evidence"])
    light = assign_light_roles([], None, truth)
    assert light.assignments["surface.brand"].hex == "#DC742C"


def test_accent_text_votes_when_two_elements_agree() -> None:
    truth = RenderTruth(
        page_clusters=[CensusCluster(hex="#FCFCFC", share=0.9), CensusCluster(hex="#393CC1", share=0.003)],
        fold_clusters=[CensusCluster(hex="#393CC1", share=0.003)],
        accent_text=[AccentTextFamily(hex="#393CC1", count=3)],
        body_bg="#FFFFFF",
        body_text="#111111",
    )
    light = assign_light_roles([], None, truth)
    assert light.assignments["surface.brand"].hex == "#393CC1"


def test_blocked_capture_flags_needs_review_instead_of_inventing() -> None:
    truth = RenderTruth(
        page_clusters=[CensusCluster(hex="#FCFCFC", share=0.999)],
        fold_clusters=[CensusCluster(hex="#FCFCFC", share=0.999)],
        body_bg="#FFFFFF",
        body_text="#111111",
        canvas_viewport_fraction=0.6,
    )
    light = assign_light_roles([], None, truth)
    # The fallback hex still exists (downstream ramps need a value) but the kit
    # says LOUDLY that it is not the brand and why.
    assert light.assignments["surface.brand"].hex == _BRAND_FALLBACK
    codes = {d["code"] for d in light.diagnostics}
    assert "LUMI0203" in codes and "LUMI0531" in codes
    monochrome = next(d for d in light.diagnostics if d["code"] == "LUMI0531")
    assert "canvas" in monochrome["message"]  # the WebGL-hero hint is named


def test_declared_role_invisible_on_the_page_is_refused() -> None:
    """Live finding (apollo.io, 2026-08-30): the declared-role reader crowned
    `--PhoneInputCountryFlag-backgroundColor--loading` (#0000001A — 10%-alpha
    black) as surface.page. With render truth present, a declaration the page
    does not show is refused loudly and measured evidence answers."""
    from lumen_ingestion.evidence import DeclaredRoleEvidence, EvidencePointer

    declared = [
        DeclaredRoleEvidence(
            role="surface.page",
            property_name="--PhoneInputCountryFlag-backgroundColor--loading",
            value="#0000001A",
            pointer=EvidencePointer(source="website", locator="css :: test"),
        )
    ]
    light = assign_light_roles([], declared, _apollo_truth())
    page = light.assignments["surface.page"]
    assert page.hex == "#FFFFFF"  # measured body bg, not the phantom declaration
    assert page.basis == "measured"
    refusals = [d for d in light.diagnostics if d["code"] == "LUMI0534"]
    assert refusals and "PhoneInputCountryFlag" in refusals[0]["message"]


def test_declared_role_visible_on_the_page_still_outranks_measured() -> None:
    """The veto targets INVISIBLE declarations only: a brand the site both
    names and shows keeps its declared authority."""
    from lumen_ingestion.evidence import DeclaredRoleEvidence, EvidencePointer

    declared = [
        DeclaredRoleEvidence(
            role="surface.brand",
            property_name="--brand",
            value=APOLLO_YELLOW,
            pointer=EvidencePointer(source="website", locator="css :: test"),
        )
    ]
    light = assign_light_roles([], declared, _apollo_truth())
    brand = light.assignments["surface.brand"]
    assert brand.hex == APOLLO_YELLOW
    assert brand.basis == "declared"


# --- the retirement side ----------------------------------------------------------


def test_stylesheet_rule_text_no_longer_emits_palette_candidates() -> None:
    snapshot = SiteSnapshot(
        requested_url="https://example.com",
        final_url="https://example.com",
        fetched_at="2026-08-30T00:00:00+00:00",
        tier="rendered",
        html="<html><body></body></html>",
        stylesheets=[
            Stylesheet(
                url="inline:0",
                text=(
                    "body { background: #FFFFFF; color: #111111 }\n"
                    f"button:focus {{ outline-color: {APOLLO_CYAN}; background: {APOLLO_CYAN} }}\n"
                    f".css-x7k2f9 {{ background: {APOLLO_YELLOW} }}\n"
                ),
            )
        ],
    )
    parsed = parse_site(snapshot)
    rule_colors = [c for c in parsed.colors if c.locator.startswith("inline:0 ::")]
    assert rule_colors == []  # mentions are not evidence any more
    # The interaction-state record still captures the focus treatment — states
    # survive as VARIANTS; they simply cannot elect palette colors.
    assert any(s.state == "focus" for s in parsed.state_styles)
