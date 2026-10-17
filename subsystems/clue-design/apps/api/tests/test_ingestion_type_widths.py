"""Responsive brand type, Task 2: type evidence at each measured width, parsed exactly as desktop."""

from __future__ import annotations

from lumen_ingestion.capture.parse import ParsedSite, _parse_computed_samples, parse_type_widths
from lumen_ingestion.capture.snapshot import SiteSnapshot
from lumen_ingestion.evidence import BrandEvidence


def _sample(selectorish: str, size: str) -> dict:
    return {"selectorish": selectorish, "tag": selectorish, "bg": None, "color": "rgb(0, 0, 0)", "fontFamily": "Georgia, serif",
            "fontSize": size, "fontWeight": "400", "lineHeight": "normal", "letterSpacing": "normal", "area": 1000.0, "behind": None, "boxArea": 1000.0}


def _snapshot(type_widths: dict | None) -> SiteSnapshot:
    return SiteSnapshot(
        requested_url="https://seller.example/", final_url="https://seller.example/", fetched_at="2026-10-18T00:00:00Z",
        tier="rendered", html="<html></html>",
        computed_samples=[_sample("body", "18px"), _sample("a", "16px"), _sample("h2", "56px")],
        type_widths=type_widths,
    )


def _read(size: str) -> dict:
    return {"fontSize": size, "lineHeight": "normal", "letterSpacing": "normal"}


def test_desktop_type_samples_carry_their_sample_index() -> None:
    parsed = ParsedSite()
    _parse_computed_samples(_snapshot(None), parsed)
    assert [(t.label, t.sample_index) for t in parsed.type_samples] == [("body", 0), ("h2", 2)]


def test_each_width_is_parsed_like_desktop() -> None:
    widths = {"capture_width": 1440, "widths": [
        {"width": 991, "samples": [_read("18px"), _read("16px"), _read("40px")]},
        {"width": 767, "samples": [_read("16px"), None, _read("34px")]},
    ]}
    parsed = parse_type_widths(_snapshot(widths), {})
    assert [width for width, _ in parsed] == [991, 767]
    at_991 = parsed[0][1]
    assert [(t.label, t.family, t.weight, t.size_px, t.sample_index) for t in at_991] == [("body", "Georgia", 400, 18.0, 0), ("h2", "Georgia", 400, 40.0, 2)]
    assert [(t.label, t.size_px) for t in parsed[1][1]] == [("body", 16.0), ("h2", 34.0)]


def test_a_sample_missing_at_a_width_is_left_out_there() -> None:
    widths = {"capture_width": 1440, "widths": [{"width": 390, "samples": [_read("16px"), None, None]}]}
    assert [(t.label, t.sample_index) for t in parse_type_widths(_snapshot(widths), {})[0][1]] == [("body", 0)]


def test_no_widths_parse_to_nothing() -> None:
    assert parse_type_widths(_snapshot(None), {}) == []


def test_evidence_without_widths_still_loads() -> None:
    evidence = BrandEvidence.model_validate({"source": {"kind": "website"}})
    assert evidence.type_widths is None and evidence.schema_version == 1
