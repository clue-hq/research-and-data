"""Type roles follow what the source page actually shows (website-quality week 1, A4).

Four defects found in the 2026-09-29 audits and re-verified 2026-10-04:
- a hidden heading earlier in the DOM became the kit's headline (capture sampled it);
- one frequency-elected heading family overwrote the H1's own family;
- display and stat were forced to weight 700, so every ad headline came out bold;
- with no H1 on the page the headline fell back to 32px/700, smaller than the measured H2.
"""

from __future__ import annotations

from lumen_ingestion.capture.rendered import _EVALUATE_JS
from lumen_ingestion.evidence import BrandEvidence, EvidencePointer, TypeSample
from lumen_ingestion.normalizer.typography import build_type_styles, resolve_anchors
from playwright.sync_api import sync_playwright


def _sample(label: str, family: str, weight: int, size: float) -> TypeSample:
    return TypeSample(
        label=label,
        family=family,
        weight=weight,
        size_px=size,
        pointer=EvidencePointer(source="website", locator=f"rendered :: {label}"),
    )


def _styles(samples: list[TypeSample]) -> dict[str, dict]:
    evidence = BrandEvidence(source={"kind": "website"}, type_samples=samples)
    styles, _ = build_type_styles(resolve_anchors(evidence))
    return styles


def test_a_light_source_keeps_its_light_weight_on_display_and_stat():
    styles = _styles([
        _sample("h1", "Inter", 400, 56),
        _sample("h2", "Inter", 400, 40),
        _sample("body", "Inter", 400, 16),
    ])
    assert styles["type.display"]["font_weight"] == 400
    assert styles["type.stat"]["font_weight"] == 400
    assert styles["type.headline"]["font_weight"] == 400


def test_a_light_headline_stays_light_even_when_lighter_than_400():
    styles = _styles([_sample("h1", "Sohne", 300, 64), _sample("body", "Sohne", 400, 16)])
    assert styles["type.display"]["font_weight"] == 300
    assert styles["type.stat"]["font_weight"] == 300


def test_the_h1_keeps_its_own_family_when_other_headings_use_another():
    styles = _styles([
        _sample("h1", "Playfair Display", 400, 56),
        _sample("h2", "Inter", 500, 32),
        _sample("h3", "Inter", 500, 24),
        _sample("body", "Inter", 400, 16),
    ])
    assert styles["type.headline"]["font_family"] == "Playfair Display"
    assert styles["type.display"]["font_family"] == "Playfair Display"
    assert styles["type.title"]["font_family"] == "Inter"


def test_with_no_h1_the_headline_comes_from_the_largest_measured_heading():
    styles = _styles([_sample("h2", "Inter", 400, 40), _sample("body", "Inter", 400, 16)])
    assert styles["type.headline"]["font_size"] >= styles["type.title"]["font_size"]
    assert styles["type.headline"]["font_weight"] == 400
    assert styles["type.display"]["font_weight"] == 400


def test_eyebrow_and_label_follow_the_measured_button_weight():
    styles = _styles([
        _sample("h1", "Inter", 400, 56),
        _sample("body", "Inter", 400, 16),
        _sample("button", "Inter", 500, 16),
    ])
    assert styles["type.cta"]["font_weight"] == 500
    assert styles["type.eyebrow"]["font_weight"] == 500
    assert styles["type.label"]["font_weight"] == 500


def test_nothing_measured_keeps_the_old_defaults():
    styles = _styles([])
    assert styles["type.headline"]["font_weight"] == 700
    assert styles["type.headline"]["font_size"] == 32.0


_PAGE = """
<style>body{font-family:Arial;margin:0}</style>
<h1 style="display:none;font-size:90px;font-weight:700">Hidden by display</h1>
<div style="opacity:0"><h1 style="font-size:91px;font-weight:700">Hidden by a parent</h1></div>
<div role="dialog"><h2 style="font-size:92px;font-weight:700">Cookie settings</h2></div>
<h1 style="font-size:56px;font-weight:400">Visible headline</h1>
<h2 style="font-size:40px;font-weight:400">Visible section heading</h2>
<p>Body copy.</p>
"""


def test_capture_samples_only_headings_a_visitor_can_see():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_content(_PAGE)
        result = page.evaluate(_EVALUATE_JS)
        browser.close()
    headings = [s for s in result["samples"] if s["selectorish"] in {"h1", "h2"}]
    assert {s["fontSize"] for s in headings} == {"40px", "56px"}

