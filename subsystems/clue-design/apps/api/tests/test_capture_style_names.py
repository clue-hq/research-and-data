"""Look-keyed style names (Wave 2 A9, founder Q-A9-6): a style is named by what it looks like, so a
re-extraction whose counts or page order shift keeps every name. No browser, no network."""

from __future__ import annotations

import json
from pathlib import Path

from lumen_ingestion.capture.geometry import look_names, parse_geometry, shape_groups, shape_key, variant_base

#: The real Stripe harvest test_ingestion_geometry.py already uses (top-level `surfaces`, 176 elements).
STRIPE = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "geometry" / "stripe_home.json"


def _el(cls: str = "button", *, bg=None, color="rgb(255, 255, 255)", border=(0, 0, 0, 0), border_color=None,
        style="none", radius=(8, 8, 8, 8), pill=False, shadow=None) -> dict:
    return {"cls": cls, "bg": bg, "color": color, "border": list(border), "borderColor": border_color,
            "borderStyle": style, "radius": list(radius), "pill": pill, "shadow": shadow}


#: The five buttons and the text link of tests/fixtures/capture/style_states.html, as the probe reads them.
FIXTURE = [
    _el(bg="rgb(4, 116, 100)", border=(1, 1, 1, 1), border_color="rgb(4, 116, 100)", style="solid",
        radius=(999, 999, 999, 999), pill=True),
    _el(color="rgb(13, 43, 37)", border=(1, 1, 1, 1), border_color="rgb(13, 43, 37)", style="solid",
        radius=(999, 999, 999, 999), pill=True),
    _el(bg="rgb(40, 36, 30)"),
    _el(bg="rgb(124, 76, 255)", radius=(6, 6, 6, 6)),
    _el(bg="rgb(10, 74, 138)", border=(1, 1, 1, 1), border_color="rgb(10, 74, 138)", style="solid",
        radius=(999, 999, 999, 999), pill=True),
    _el("link", color="rgb(13, 43, 37)"),
]


def _names(surfaces: list[dict], classes=("button", "link")) -> list[str]:
    return [name for name, _ in shape_groups(surfaces, classes)]


def test_a_style_is_named_by_the_colour_it_is_told_by() -> None:
    assert sorted(_names(FIXTURE)) == [
        "ghost.0d2b25", "outline.0d2b25", "solid.047464", "solid.0a4a8a", "solid.28241e", "solid.7c4cff",
    ]
    assert variant_base("solid", "#047464") == "solid.047464" and variant_base("ghost", None) == "ghost.none"


def test_a_shift_in_use_or_page_order_renames_nothing() -> None:
    before = set(_names(FIXTURE))
    busier = FIXTURE + [FIXTURE[2]] * 4  # the dark button is now the most used
    assert set(_names(busier)) == before
    assert _names(busier)[0] == "solid.28241e", "order follows use; names do not"
    assert set(_names(list(reversed(FIXTURE)))) == before


def test_two_looks_sharing_a_colour_each_take_a_suffix_of_their_own_look() -> None:
    square, pill = _el(bg="rgb(4, 116, 100)"), _el(bg="rgb(4, 116, 100)", radius=(999,) * 4, pill=True)
    assert sorted(_names([square, pill], ("button",))) == ["solid.047464.d36e", "solid.047464.dfdd"]
    assert set(_names([pill, square, pill], ("button",))) == set(_names([square, pill], ("button",)))


def test_an_outline_of_another_colour_is_another_style() -> None:
    dark = _el(color="rgb(13, 43, 37)", border=(1, 1, 1, 1), border_color="rgb(13, 43, 37)", style="solid")
    white = _el(color="rgb(255, 255, 255)", border=(1, 1, 1, 1), border_color="rgb(255, 255, 255)", style="solid")
    assert sorted(_names([dark, white], ("button",))) == ["outline.0d2b25", "outline.ffffff"]
    assert shape_key(dark) != shape_key(white)


def test_a_transparent_border_is_no_border() -> None:
    # Bootstrap's `.btn { border: 1px solid transparent }`, Tailwind's `border-transparent`: the probe
    # reads the width and the style, and no colour (or a colour that paints nothing).
    dark = _el(color="rgb(13, 43, 37)", border=(1, 1, 1, 1), style="solid")
    red = _el(color="rgb(198, 40, 40)", border=(1, 1, 1, 1), style="solid")
    assert sorted(_names([dark, red], ("button",))) == ["ghost.0d2b25", "ghost.c62828"]
    clear = _el(color="rgb(13, 43, 37)", border=(1, 1, 1, 1), border_color="rgba(255, 255, 255, 0)", style="solid")
    assert _names([clear], ("button",)) == ["ghost.0d2b25"]
    drawn = _el(color="rgb(13, 43, 37)", border=(1, 1, 1, 1), border_color="rgb(13, 43, 37)", style="solid")
    assert _names([drawn], ("button",)) == ["outline.0d2b25"]


def test_the_same_look_has_the_same_name_in_the_shape_records_and_the_state_pass() -> None:
    harvest = json.loads(STRIPE.read_text())
    parsed = parse_geometry(harvest, page_url="https://stripe.com/")
    buttons = [s for s in parsed.surfaces if s.surface == "button"]
    assert len({s.variant for s in buttons}) == len(buttons), "one name per look"
    state_names = {name for name, members in shape_groups(harvest["surfaces"], ("button", "link", "nav_link", "card"))
                   if members[0].get("cls") == "button"}
    assert {s.variant for s in buttons} == state_names
    assert look_names([]) == {}
