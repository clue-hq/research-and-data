"""The compact brand card (K1): font glyph-gap honesty + image no-silent-caps.

Covers the two brand-card honesty fixes — surfacing the ingestion glyph-coverage
audit (fonts.*.metrics.missing_glyphs) as a short font-gap note, and replacing
the silent 8-image cap with a realistic cap plus an explicit truncation line.
Offline, no LLM.
"""

from __future__ import annotations

from lumen_agent.brand_card import (
    MAX_IMAGE_LIST,
    build_brand_card,
)


def _kit(**overrides):
    kit = {
        "id": "brand_kit_x",
        "version": 3,
        "name": "Insight Health",
        "tokens": {"colors": {}, "typography": {}},
        "assets": {"fonts": {}, "logos": {}, "images": {}},
        "constraints": {},
    }
    kit.update(overrides)
    return kit


def _font(family, missing=None, *, with_metrics=True):
    entry = {"family": family, "faces": [{"asset_id": "a1", "weight": 400}]}
    if with_metrics:
        metrics = {"x_height_ratio": 0.52}
        if missing is not None:
            metrics["missing_glyphs"] = missing
        entry["metrics"] = metrics
    return entry


# --- font glyph-gap note --------------------------------------------------------


def test_font_gap_note_surfaces_missing_glyphs() -> None:
    kit = _kit()
    kit["assets"]["fonts"] = {"brand": _font("Aeonik", ["/", "×", "—"])}
    card = build_brand_card(kit)
    assert card is not None
    assert card["font_gaps"] == ["Aeonik lacks: / × —"]


def test_font_gap_note_absent_when_face_is_complete() -> None:
    """A font whose metrics carry no missing_glyphs (full coverage) yields no
    note — the field is omitted, not an empty list."""
    kit = _kit()
    kit["assets"]["fonts"] = {"brand": _font("Aeonik", None)}
    card = build_brand_card(kit)
    assert "font_gaps" not in card


def test_font_gap_note_tolerates_old_kits_without_metrics() -> None:
    """Kits ingested before the audit lack the metrics/missing_glyphs field
    entirely — the card must render without a KeyError and omit the note."""
    kit = _kit()
    kit["assets"]["fonts"] = {"brand": _font("Aeonik", with_metrics=False)}
    card = build_brand_card(kit)
    assert "font_gaps" not in card


def test_font_gap_note_covers_multiple_faces() -> None:
    kit = _kit()
    kit["assets"]["fonts"] = {
        "brand": _font("Aeonik", ["×"]),
        "body": _font("Inter", None),
        "mono": _font("Space Mono", ["€", "£"]),
    }
    card = build_brand_card(kit)
    assert card["font_gaps"] == ["Aeonik lacks: ×", "Space Mono lacks: € £"]


def test_font_gap_note_summarizes_long_gap_lists() -> None:
    """A heavily-subset face gets its note capped with a (+N more) summary so
    the card stays compact."""
    many = [chr(c) for c in range(ord("A"), ord("A") + 25)]
    kit = _kit()
    kit["assets"]["fonts"] = {"brand": _font("Subset", many)}
    card = build_brand_card(kit)
    note = card["font_gaps"][0]
    assert note.startswith("Subset lacks: ")
    assert "(+9 more)" in note  # 25 missing, 16 shown


# --- image inventory: no silent caps -------------------------------------------


def _images(n):
    return {
        f"img_{i}": {"asset_id": f"a{i}", "role": "hero", "title": f"Image {i}"}
        for i in range(n)
    }


def test_realistic_thirteen_image_kit_shows_every_slot() -> None:
    """The real kit carries 13 image slots — all under the raised cap, so the
    agent sees every one and NO truncation line appears (the old MAX_LIST=8
    silently hid five)."""
    kit = _kit()
    kit["assets"]["images"] = _images(13)
    card = build_brand_card(kit)
    assert len(card["images"]) == 13
    assert all("note" not in e for e in card["images"])


def test_overflow_appends_explicit_truncation_line() -> None:
    """Past the cap, the agent is told explicitly rather than left blind."""
    kit = _kit()
    kit["assets"]["images"] = _images(MAX_IMAGE_LIST + 5)
    card = build_brand_card(kit)
    assert len(card["images"]) == MAX_IMAGE_LIST + 1  # entries + one note line
    note = card["images"][-1]
    assert note.get("note", "").startswith("5 more asset(s) available")
    assert "asset tool" in note["note"]


def test_no_truncation_line_exactly_at_cap() -> None:
    kit = _kit()
    kit["assets"]["images"] = _images(MAX_IMAGE_LIST)
    card = build_brand_card(kit)
    assert len(card["images"]) == MAX_IMAGE_LIST
    assert all("note" not in e for e in card["images"])
