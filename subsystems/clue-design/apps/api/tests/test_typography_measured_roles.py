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



# --- 2026-10-05: prominent section headings, measured light weights -------------------------


def _h2s(sizes: list[float]) -> list[TypeSample]:
    return [_sample("h2", "Inter", 400, size) for size in sizes]


def test_the_section_title_is_the_size_that_fills_the_most_heading_space():
    # garnerhealth.com: four 18px tab labels come first, then seven 56px section headings.
    garner = _styles([_sample("h1", "Inter", 500, 87), *_h2s([18, 18, 18, 18, 56, 56, 56, 56, 56, 56, 56, 40, 40]),
                      _sample("body", "Inter", 400, 16)])
    assert garner["type.title"]["font_size"] == 56.0


def test_many_small_card_titles_do_not_outvote_fewer_big_section_headings():
    # ramp.com: six 28px card titles against five 48px section headings.
    ramp = _styles([_sample("h1", "Inter", 500, 64), *_h2s([28, 40, 40, 48, 48, 28, 28, 28, 48, 28, 28, 48, 24]),
                    _sample("body", "Inter", 400, 14)])
    assert ramp["type.title"]["font_size"] == 48.0
    # notion.com: three 22px feature headings against two 54px section headings.
    notion = _styles([_sample("h1", "Inter", 500, 96), *_h2s([54, 22, 22, 22, 54, 42]),
                      _sample("body", "Inter", 400, 20)])
    assert notion["type.title"]["font_size"] == 54.0


def test_one_giant_call_to_action_heading_does_not_become_the_section_title():
    # conduit.ai: five 48px section headings and one 56px closing CTA.
    conduit = _styles([_sample("h1", "Inter", 400, 56), *_h2s([48, 48, 48, 48, 48, 56]),
                       _sample("body", "Inter", 400, 18)])
    assert conduit["type.title"]["font_size"] == 48.0


def test_instancing_also_cuts_the_weights_the_site_actually_uses():
    from lumen_ingestion.capture.font_instances import INSTANCE_WEIGHTS, instance_weights

    measured = [_sample("h1", "sohne-var", 300, 48), _sample("body", "sohne-var", 400, 16),
                _sample("h1", "Other Font", 250, 40)]
    assert instance_weights("sohne-var", measured) == (300, 400, 500, 600, 700)
    assert instance_weights("SOHNE-VAR", measured)[0] == 300
    assert instance_weights("Unmeasured", measured) == INSTANCE_WEIGHTS


_NAV_PAGE = """
<style>body{font-family:Arial;margin:0}</style>
<nav><h2 style="font-size:12px">Menu heading</h2></nav>
""" + "".join(f'<h2 style="font-size:{18 if i < 4 else 56}px">Heading {i}</h2>' for i in range(12)) + """
<footer><h2 style="font-size:13px">Footer column</h2></footer>
"""


def test_capture_samples_many_visible_headings_and_skips_nav_and_footer():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_content(_NAV_PAGE)
        result = page.evaluate(_EVALUATE_JS)
        browser.close()
    h2 = [s["fontSize"] for s in result["samples"] if s["selectorish"] == "h2"]
    assert "12px" not in h2 and "13px" not in h2
    assert h2.count("56px") >= 8


# --- 2026-10-17: the heading ink needs each heading's colour and what is behind it ----------

_INK_PAGE = """
<style>body{font-family:Arial;margin:0;background:#FFFFFF}</style>
<section style="background:#014036;height:600px"><h1 style="color:#FFFFFF">Hero</h1></section>
<section style="background:#F9FAF8;margin-top:1200px"><h2 style="color:#014036">Below the fold</h2></section>
"""


def test_capture_reads_what_is_behind_each_heading_and_its_whole_box():
    from lumen_ingestion.capture.parse import parse_site
    from lumen_ingestion.capture.snapshot import SiteSnapshot

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_content(_INK_PAGE)
        result = page.evaluate(_EVALUATE_JS)
        browser.close()
    h2 = next(s for s in result["samples"] if s["selectorish"] == "h2")
    assert h2["behind"] == "#F9FAF8"
    assert h2["area"] == 0 and h2["boxArea"] > 0  # out of the first viewport, still measured
    snapshot = SiteSnapshot(
        requested_url="https://ink.example", final_url="https://ink.example",
        fetched_at="2026-10-17", tier="rendered", html="<html></html>",
        computed_samples=result["samples"],
    )
    samples = {t.label: t for t in parse_site(snapshot).type_samples if t.label in {"h1", "h2"}}
    assert (samples["h2"].color, samples["h2"].background) == ("#014036", "#F9FAF8")
    assert samples["h2"].area == h2["boxArea"]
    assert (samples["h1"].color, samples["h1"].background) == ("#FFFFFF", "#014036")
