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


# Task 6: re-measuring an existing kit applies the measured narrowing to the kit's STORED desktop sizes.
from lumen_ingestion.normalizer.responsive_type import kit_with_section, remeasured_section


def _kit(headline: float, body: float) -> dict:
    style = lambda size: {"value": {"default": {"kind": "style", "font_size": size}}}  # noqa: E731
    return {"id": "brand_kit_ing_x", "tokens": {"typography": {"type.headline": style(headline), "type.body": style(body)}}}


def _fresh(h1: list[float], body: list[float]) -> BrandEvidence:
    """Today's page: desktop h1 h1[0] / body body[0], then widths 991 and 767."""
    rows = [TypeWidth(width=w, type_samples=[_sample("h1", h, 1), _sample("body", b, 0)]) for w, h, b in zip([991, 767], h1[1:], body[1:])]
    return BrandEvidence(source={"kind": "website", "url": "https://seller.example/"},
                         type_samples=[_sample("body", body[0], 0), _sample("h1", h1[0], 1)],
                         type_widths=TypeWidths(capture_width=1440, widths=rows))


def _remeasure(kit: dict, evidence: BrandEvidence):
    return remeasured_section(kit, evidence, resolve_anchors, lambda a: build_type_styles(a)[0])


def test_steps_are_scaled_onto_the_stored_desktop() -> None:
    section, skipped = _remeasure(_kit(56, 18), _fresh([60, 43, 36], [18, 18, 18]))
    assert section["roles"]["type.headline"] == [{"max_width": 991, "font_size": 40.0}, {"max_width": 767, "font_size": 33.5}]
    assert section["roles"]["type.body"] == []
    assert "type.headline" not in skipped and "type.body" not in skipped
    assert "type.caption" in skipped, "a role the stored kit does not carry is left out and named"


def test_a_role_far_from_the_stored_size_is_skipped_and_named() -> None:
    section, skipped = _remeasure(_kit(30, 18), _fresh([60, 43, 36], [18, 18, 18]))
    assert "type.headline" not in section["roles"] and "type.headline" in skipped


def test_the_new_version_differs_only_in_the_section() -> None:
    kit = _kit(56, 18)
    section, _ = _remeasure(kit, _fresh([60, 43, 36], [18, 18, 18]))
    updated = kit_with_section(kit, section)
    assert {key for key in updated if updated[key] != kit.get(key)} == {"responsive_type"}
    assert kit_with_section(kit, None) == kit


def test_a_role_whose_source_was_never_read_narrower_is_left_out() -> None:
    """Review finding 2: Framer-style sites hide the desktop copy at narrower widths. A role whose
    element was never read there is unmeasured (left out, drawn as today), not 'never changes'."""
    body_only = _evidence([None, None], [18, 16])
    section = _section(body_only)
    assert section["roles"]["type.body"] == [{"max_width": 767, "font_size": 16.0}]
    assert "type.headline" not in section["roles"] and "type.title" not in section["roles"], "derived from an unread headline"
    assert _section(_evidence([None, None], [None, None])) is None, "nothing read at any narrower width: no section"


def test_the_kits_desktop_typography_is_byte_for_byte_unchanged() -> None:
    """Review finding 13: the normalizer's whole kit typography, with and without the widths."""
    import json
    from pathlib import Path
    from lumen_ingestion.normalizer import normalize_evidence

    raw = json.loads((Path(__file__).resolve().parent / "fixtures" / "ingestion" / "evidence_website_insight.json").read_text())
    evidence = BrandEvidence.model_validate(raw)
    indexed = [sample.model_copy(update={"sample_index": i}) for i, sample in enumerate(evidence.type_samples)]
    narrower = [sample.model_copy(update={"size_px": (sample.size_px or 16) * 0.7}) for sample in indexed]
    measured_evidence = evidence.model_copy(update={
        "type_samples": indexed,
        "type_widths": TypeWidths(capture_width=1440, widths=[TypeWidth(width=767, type_samples=narrower)]),
    })
    kwargs = {"brand_kit_id": "brand_kit_ing_x", "name": "X", "created_at": "2026-10-18T00:00:00Z"}
    plain = normalize_evidence(evidence, **kwargs)
    measured = normalize_evidence(measured_evidence, **kwargs)
    assert measured.brand_kit["tokens"]["typography"] == plain.brand_kit["tokens"]["typography"]
    assert measured.responsive_type is not None and plain.responsive_type is None


def test_a_remeasure_that_keeps_no_role_says_so() -> None:
    """Review finding 11: every role far from the stored kit → nothing to publish."""
    section, skipped = _remeasure(_kit(20, 40), _fresh([60, 43, 36], [18, 18, 18]))
    assert section is None and {"type.headline", "type.body"} <= set(skipped)
