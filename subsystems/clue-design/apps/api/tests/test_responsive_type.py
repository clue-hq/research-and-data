"""Responsive brand type, Task 3: the kit's twelve roles worked out at each measured width (desktop's
selection kept) and stored as the `responsive_type` kit section, outside the engine."""

from __future__ import annotations

from lumen_api.brand_kit_sections import KIT_SECTIONS_OUTSIDE_ENGINE, carry_kit_sections
from lumen_ingestion.evidence import BrandEvidence, EvidencePointer, TypeSample, TypeWidth, TypeWidths
from lumen_ingestion.normalizer.responsive_type import responsive_type_section
from lumen_ingestion.normalizer.typography import build_type_styles, resolve_anchors
from lumen_ingestion.pipeline import _attach_responsive_type


def _sample(label: str, size: float, index: int) -> TypeSample:
    return TypeSample(label=label, family="Georgia", weight=400, size_px=size, line_height=1.2,
                      pointer=EvidencePointer(source="website", locator=f"rendered :: {label}"), sample_index=index)


def _evidence(h2: list[float | None], body: list[float | None], widths: list[int] | None = None) -> BrandEvidence:
    """Desktop h1 56 / body 18 at a 1440 capture, then one entry per width (None = not read there)."""
    widths = widths if widths is not None else [991, 767]
    rows = []
    for width, h, b in zip(widths, h2, body):
        samples = [s for s in (_sample("h1", h, 1) if h else None, _sample("body", b, 0) if b else None) if s]
        rows.append(TypeWidth(width=width, type_samples=samples))
    return BrandEvidence(
        source={"kind": "website", "url": "https://seller.example/", "captured_at": "2026-10-18T00:00:00Z"},
        type_samples=[_sample("body", 18, 0), _sample("h1", 56, 1)],
        type_widths=TypeWidths(capture_width=1440, widths=rows) if widths else None,
    )


def _section(evidence: BrandEvidence) -> dict | None:
    anchors = resolve_anchors(evidence)
    return responsive_type_section(anchors, evidence, lambda a: build_type_styles(a)[0])


def test_a_stepping_page_gives_headline_and_body_steps() -> None:
    section = _section(_evidence([40, 34], [18, 16]))
    assert section["measured_from"] == 1440 and section["widths"] == [991, 767]
    assert section["source"]["url"] == "https://seller.example/"
    assert section["roles"]["type.headline"] == [{"max_width": 991, "font_size": 40.0}, {"max_width": 767, "font_size": 34.0}]
    assert section["roles"]["type.body"] == [{"max_width": 767, "font_size": 16.0}]
    assert section["roles"]["type.title"] == [{"max_width": 991, "font_size": 29.0}, {"max_width": 767, "font_size": 24.5}], "derived from H"
    assert len(section["roles"]) == 12


def test_a_page_that_never_changes_gives_empty_steps() -> None:
    section = _section(_evidence([56, 56], [18, 18]))
    assert section is not None and all(steps == [] for steps in section["roles"].values())


def test_no_measured_width_gives_no_section() -> None:
    assert _section(_evidence([], [], widths=[])) is None


def test_a_sample_hidden_at_a_width_keeps_the_wider_size() -> None:
    section = _section(_evidence([40, None], [18, 16], widths=[991, 390]))
    assert section["roles"]["type.headline"] == [{"max_width": 991, "font_size": 40.0}], "no jump back to 56 at 390"


def test_desktop_styles_are_unchanged() -> None:
    with_widths = _evidence([40, 34], [18, 16])
    without = with_widths.model_copy(update={"type_widths": None})
    assert build_type_styles(resolve_anchors(with_widths)) == build_type_styles(resolve_anchors(without))


def test_the_section_survives_revalidation_and_is_attached_after_validation() -> None:
    assert "responsive_type" in KIT_SECTIONS_OUTSIDE_ENGINE
    section = {"version": 1, "roles": {}}
    assert carry_kit_sections({"id": "k", "responsive_type": section}, {"id": "k"})["responsive_type"] == section
    assert _attach_responsive_type({"id": "k"}, section) == {"id": "k", "responsive_type": section}
    assert _attach_responsive_type({"id": "k"}, None) == {"id": "k"}
