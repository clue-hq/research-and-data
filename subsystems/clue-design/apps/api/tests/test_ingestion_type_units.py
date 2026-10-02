"""Plan 1 item A (2026-09-04): line-height and letter-spacing are ratios of the ELEMENT's font
size, never of the root 16px. The Apollo harvest stored a 72px headline leading as 4.5 (72/16)
and its -0.72px tracking as -0.045; the true values are 1.0 and -0.01."""

from __future__ import annotations

from pathlib import Path

from lumen_ingestion.capture.parse import _letter_spacing, _line_height, parse_site
from lumen_ingestion.capture.snapshot import Stylesheet, load_snapshot

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "snapshots"


def test_line_height_units_resolve_against_the_element_size() -> None:
    assert _line_height("1.1", 64.0) == 1.1
    assert _line_height("1.2em", 64.0) == 1.2
    assert _line_height("120%", 64.0) == 1.2
    assert _line_height("72px", 64.0) == 1.125
    assert _line_height("4.5rem", 64.0) == 1.125  # 4.5 × 16 = 72px, over 64px
    assert _line_height("72px", 72.0) == 1.0  # the Apollo headline
    assert _line_height("normal", 64.0) is None
    assert _line_height("", 64.0) is None


def test_a_length_with_no_element_size_is_an_honest_blank_not_px_over_16() -> None:
    assert _line_height("72px", None) is None
    assert _line_height("4.5rem", None) is None
    assert _line_height("1.1", None) == 1.1  # unitless never needed the size
    assert _letter_spacing("-0.72px", None) is None
    assert _letter_spacing("-0.01em", None) == -0.01


def test_letter_spacing_units_resolve_against_the_element_size() -> None:
    assert _letter_spacing("-0.72px", 72.0) == -0.01  # the Apollo headline
    assert _letter_spacing("-0.01em", 72.0) == -0.01
    assert _letter_spacing("0.5rem", 16.0) == 0.5  # 8px over 16px
    assert _letter_spacing("normal", 72.0) is None


def _with_css_and_samples(css: str, samples: list[dict]):
    snapshot = load_snapshot(FIXTURES / "insight_static.json")
    return snapshot.model_copy(
        update={
            "stylesheets": [Stylesheet(url="https://units.example/site.css", text=css)],
            "computed_samples": samples,
        }
    )


def test_parse_site_declared_px_line_height_uses_the_rule_font_size() -> None:
    css = 'h1{ font-family: "Aeonik"; font-size: 64px; line-height: 72px; letter-spacing: -0.64px; }'
    parsed = parse_site(_with_css_and_samples(css, []))
    h1 = next(t for t in parsed.type_samples if t.label == "h1" and t.size_px == 64.0)
    assert h1.line_height == 1.125
    assert h1.letter_spacing == -0.01


def test_parse_site_declared_px_line_height_before_font_size_still_resolves() -> None:
    # Declaration order must not matter: line-height first, font-size second.
    css = 'h1{ line-height: 72px; font-family: "Aeonik"; font-size: 64px; }'
    parsed = parse_site(_with_css_and_samples(css, []))
    h1 = next(t for t in parsed.type_samples if t.label == "h1" and t.size_px == 64.0)
    assert h1.line_height == 1.125


def test_parse_site_rendered_sample_uses_its_own_font_size() -> None:
    samples = [
        {
            "tag": "h1",
            "area": 50000,
            "fontFamily": "seasonMix",
            "fontSize": "72px",
            "fontWeight": "550",
            "lineHeight": "72px",
            "letterSpacing": "-0.72px",
        }
    ]
    parsed = parse_site(_with_css_and_samples("", samples))
    h1 = next(t for t in parsed.type_samples if t.locator.startswith("rendered ::") and t.label == "h1")
    assert h1.size_px == 72.0
    assert h1.line_height == 1.0
    assert h1.letter_spacing == -0.01
    assert h1.weight == 550
