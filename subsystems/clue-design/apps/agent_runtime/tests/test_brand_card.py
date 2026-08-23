"""The compact brand card (K1): font glyph-gap honesty + image no-silent-caps.

Covers the two brand-card honesty fixes — surfacing the ingestion glyph-coverage
audit (fonts.*.metrics.missing_glyphs) as a short font-gap note, and replacing
the silent 8-image cap with a realistic cap plus an explicit truncation line.
W1.3 adds the two facts the author could not read off the card at all: an
image's PIXEL SIZE (so a 2460px panel is distinguishable from a 296px crop) and
the class-shaped token name behind each kit color role (so `text.brand` is never
transposed into the invalid class `text-brand`). Offline, no LLM.
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


# --- W1.3: image/logo rows carry their true pixel size -------------------------
#
# The card is the agent's visual MENU, and until now every row read the same
# size — nothing distinguished a 2460px hero panel from a 296px thumbnail, so
# the author could not prefer the panel or know which assets clear the 512px
# style-anchor floor. The dimensions live on the ASSET RECORD (the kit's own
# `assets.images` entry carries only an asset_id), which is why the card now
# takes the same by-value asset manifest `use_brand_asset` reads.


def _manifest(asset_id, block="raster", width=2460, height=1060):
    record = {"id": asset_id}
    if block is not None:
        record[block] = {"pixel_width": width, "pixel_height": height}
    return {asset_id: {"record": record}}


def test_image_row_carries_px_from_the_asset_record() -> None:
    kit = _kit()
    kit["assets"]["images"] = {"img.1": {"asset_id": "a1", "role": "hero"}}
    card = build_brand_card(kit, asset_manifest=_manifest("a1"))
    assert card["images"][0]["px"] == "2460x1060"


def test_image_row_omits_px_when_the_record_has_no_dimensions() -> None:
    """Never fabricate a size: a record with no raster/logo block (or no
    manifest entry at all) simply carries no `px` field."""
    kit = _kit()
    kit["assets"]["images"] = {"img.1": {"asset_id": "a1"}, "img.2": {"asset_id": "a2"}}
    card = build_brand_card(kit, asset_manifest=_manifest("a1", block=None))
    assert "px" not in card["images"][0]
    assert "px" not in card["images"][1]


def test_image_row_omits_px_without_a_manifest() -> None:
    """The scene lane and every older caller pass no manifest — the card must
    render exactly as before rather than raising."""
    kit = _kit()
    kit["assets"]["images"] = {"img.1": {"asset_id": "a1"}}
    card = build_brand_card(kit)
    assert "px" not in card["images"][0]


def test_logo_variant_rows_carry_px_too() -> None:
    """A logo's pixels decide whether it survives a small header slot; the logo
    block is where a logo record keeps them."""
    kit = _kit()
    kit["assets"]["logos"] = {
        "primary": {
            "usage": "primary",
            "variants": [{"name": "full_color", "asset_id": "l1"}],
        }
    }
    manifest = _manifest("l1", block="logo", width=800, height=300)
    card = build_brand_card(kit, asset_manifest=manifest)
    variant = card["logos"][0]["variants"][0]
    assert variant["px"] == "800x300"


def test_logo_variant_row_omits_px_when_unknown() -> None:
    kit = _kit()
    kit["assets"]["logos"] = {
        "primary": {"usage": "primary", "variants": [{"name": "mono", "asset_id": "l1"}]}
    }
    card = build_brand_card(kit, asset_manifest={})
    assert "px" not in card["logos"][0]["variants"][0]


# --- W1.3: color roles state the class-shaped token name ----------------------
#
# 153 live rejections came from reading `text.brand` off this block and writing
# the class `text-brand` — which the engine parses as color-prefix `text-` plus
# token `brand`, and `brand` is not a token. The row now states the token the
# compiled theme actually emits for that role, and the block says outright that
# roles are not classes.


def _color_kit():
    def hex_token(value):
        return {"value": {"default": {"kind": "hex", "value": value}}}

    kit = _kit()
    kit["tokens"]["colors"] = {
        "surface.brand": hex_token("#00525C"),
        "surface.brand.subtle": hex_token("#E6F2F3"),
        "text.brand": hex_token("#00525C"),
        "text.primary": hex_token("#111111"),
        "border.brand": hex_token("#00525C"),
    }
    return kit


def test_color_role_rows_carry_the_sanitized_token_name() -> None:
    card = build_brand_card(_color_kit())
    roles = card["color_roles"]["roles"]
    assert roles["text.brand"] == {"token": "text-brand", "value": "#00525C"}
    assert roles["surface.brand"]["token"] == "surface-brand"
    assert roles["surface.brand.subtle"]["token"] == "surface-brand-subtle"
    assert roles["border.brand"]["token"] == "border-brand"


def test_color_role_block_says_roles_are_not_class_tokens() -> None:
    card = build_brand_card(_color_kit())
    note = card["color_roles"]["note"]
    assert "not class" in note.lower()
    assert "THEME TOKENS" in note
    # The note teaches the mechanically correct class shape.
    assert "bg-surface-brand" in note


def test_color_role_block_omits_roles_the_kit_cannot_resolve() -> None:
    """An unresolvable role is left out entirely — the card never advertises a
    color the theme will not carry."""
    kit = _color_kit()
    kit["tokens"]["colors"]["text.brand"] = {
        "value": {"default": {"kind": "alias", "token": "colors.gone"}}
    }
    roles = build_brand_card(kit)["color_roles"]["roles"]
    assert "text.brand" not in roles
    assert "surface.brand" in roles


# --- W1.5: the card's 16 are the 16 LARGEST, not the 16 listed first ----------
#
# The card took the first 16 slots in INSERTION order, which for a PDF or manual
# kit is not quality order — it could show sixteen small crops while the assets
# big enough to carry a band never appeared. It now ranks by pixel area first,
# off the same manifest records it already reads for `px`.
#
# What this deliberately does NOT claim: alignment with the W1.4 describe bound.
# `describe._select_for_describe` uses the same `(-area, position)` SHAPE, but
# its area comes from capture evidence (DOM attributes), while the card's comes
# from the record's raster block — and a website kit's birth order is
# `(DOM-attr area, file_size)` with CSS-background art appended at area 0. So
# this sort is not a no-op for website kits and the two selections can still
# diverge (a big CSS-background hero can enter the card's 16 uncaptioned). That
# gap is the ledgered describe-ranking-source item. Record dims are the truer
# ranking, so the card uses them and prints the size it ranked by.


def _sized_images(sizes):
    """`{slot: image}` in the given insertion order, plus the matching manifest."""
    images = {}
    manifest = {}
    for index, (name, width, height) in enumerate(sizes):
        asset_id = f"a_{name}"
        images[f"img.{index}"] = {"asset_id": asset_id, "title": name}
        manifest[asset_id] = {
            "record": {"id": asset_id, "raster": {"pixel_width": width, "pixel_height": height}}
        }
    return images, manifest


def test_card_shows_the_largest_images_when_insertion_order_is_not_area_order() -> None:
    """A PDF-shaped kit: 18 slots, the two biggest last. Before W1.5 they were
    the two the cap dropped."""
    sizes = [(f"small{i}", 300, 200) for i in range(16)]
    sizes += [("giant", 2400, 1600), ("large", 1800, 1200)]
    images, manifest = _sized_images(sizes)
    kit = _kit()
    kit["assets"]["images"] = images

    rows = build_brand_card(kit, asset_manifest=manifest)["images"]

    assert [row["title"] for row in rows[:2]] == ["giant", "large"]
    assert len(rows) == MAX_IMAGE_LIST + 1  # 16 rows + the truncation line
    assert rows[-1]["note"].startswith("2 more asset(s) available")


def test_a_kit_already_ordered_by_record_dims_is_left_untouched() -> None:
    """The sort is a no-op for a kit whose insertion order ALREADY descends by
    record dimensions — every row identical, in the identical order, including
    the truncation line.

    Note what this does not say: a website kit is ordered by DOM-attribute area
    at birth, not by record dims, so it is not automatically such a kit. This
    pins the sort's stability, not a claim about website kits.
    """
    sizes = [(f"img{i}", 2400 - i * 100, 1600 - i * 50) for i in range(20)]
    images, manifest = _sized_images(sizes)
    kit = _kit()
    kit["assets"]["images"] = images

    rows = build_brand_card(kit, asset_manifest=manifest)["images"]

    # The head of the kit in INSERTION order, built through a card where the cap
    # cannot bite and the sort therefore cannot matter — no duplicated row shape.
    head_kit = _kit()
    head_kit["assets"]["images"] = dict(list(images.items())[:MAX_IMAGE_LIST])
    expected_head = build_brand_card(head_kit, asset_manifest=manifest)["images"]

    # Full rows, not just the title sequence: asset, asset_id, role, title and px
    # must all be unchanged, not merely the order.
    assert rows[:MAX_IMAGE_LIST] == expected_head
    assert rows[-1]["note"].startswith("4 more asset(s) available")
    assert len(rows) == MAX_IMAGE_LIST + 1


def test_equal_area_images_keep_their_insertion_order() -> None:
    """Ties break on kit order — the same tie-break `_select_for_describe` uses.
    The two can still diverge even here (a website kit's record dims can be
    uniform while the DOM areas describe ranks by are not — the ledgered
    describe-ranking-source item above); this pins only that the CARD's tie-break
    is kit order, and therefore deterministic."""
    sizes = [(f"img{i}", 800, 600) for i in range(6)]
    images, manifest = _sized_images(sizes)
    kit = _kit()
    kit["assets"]["images"] = images

    rows = build_brand_card(kit, asset_manifest=manifest)["images"]

    assert [row["title"] for row in rows] == [f"img{i}" for i in range(6)]


def test_images_without_dimensions_sort_last_but_are_not_dropped() -> None:
    """A record that states no size is not evidence of a big asset — it ranks
    below every measured one, and is still shown when the cap allows."""
    images, manifest = _sized_images([("small", 300, 200), ("big", 2000, 1500)])
    images["img.9"] = {"asset_id": "a_unknown", "title": "unmeasured"}
    kit = _kit()
    kit["assets"]["images"] = images

    rows = build_brand_card(kit, asset_manifest=manifest)["images"]

    assert [row["title"] for row in rows] == ["big", "small", "unmeasured"]


def test_ordering_is_unchanged_without_a_manifest() -> None:
    """No manifest → no dimensions to rank by → the kit's own order stands."""
    kit = _kit()
    kit["assets"]["images"] = _images(5)

    rows = build_brand_card(kit)["images"]

    assert [row["title"] for row in rows] == [f"Image {i}" for i in range(5)]
