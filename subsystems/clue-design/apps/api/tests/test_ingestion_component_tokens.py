"""Measured styles become brand-scoped kit tokens (Wave 2 A9, Task X4)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from lumen_api.core import CoreClient
from lumen_ingestion.brief_agent import build_brief_request
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes, clean_icon_svg
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.evidence import BrandEvidence, EvidencePointer, MeasuredStyle, MotionEvidence, StyleLook
from lumen_ingestion.normalizer import component_tokens
from lumen_ingestion.normalizer.component_tokens import (
    easing_ok, glyph_ok, is_component_token, keyword_ok, mint_component_tokens, svg_ok, transform_ok,
)

TESTS = Path(__file__).resolve().parent
HARVEST = json.loads((TESTS / "fixtures" / "capture" / "style_states.harvest.json").read_text())
CSS = (TESTS / "fixtures" / "capture" / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
#: Garner's published kit (the puck spike's `garner/kit.json`) without its `brief` and `grammar_audit`.
GARNER = TESTS / "fixtures" / "ingestion" / "garner_kit.json"
#: The icon-markup vectors the engine (brand_style_tokens.rs) and site-kit (isSafeIconSvg) read too.
ICON_SVG_CASES = json.loads(
    (TESTS.parents[2] / "crates" / "lumen-core" / "fixtures" / "brand" / "icon_svg_cases.json").read_text()
)
ICON = (
    '<svg viewBox="0 0 12 12" fill="none"><path d="M1 6h9M7 2l4 4-4 4" stroke="currentColor" '
    'stroke-width="1.5"></path></svg>'
)


def _kit() -> dict:
    return json.loads(GARNER.read_text())


def _mint(kit: dict | None = None):
    kit = _kit() if kit is None else kit
    parsed = parse_geometry(HARVEST, page_url="https://fixture.test/")
    motion = attach_keyframes(parsed.motion, [Stylesheet(url="https://fixture.test/", text=CSS)])
    return kit, mint_component_tokens(kit, parsed.styles, motion)


def _value(kit: dict, group: str, name: str):
    return kit["tokens"][group][name]["value"]["default"]


def _recipe(kit: dict, result, component: str, fill: str | None = None):
    for recipe in result.section["styles"]:
        if recipe["component"] != component:
            continue
        if fill is None or (recipe["rest"].get("fill") and _value(kit, "colors", recipe["rest"]["fill"])["value"] == fill):
            return recipe
    raise AssertionError(f"no {component} recipe with fill {fill}")


def test_measured_values_become_tokens_named_for_where_they_were_measured() -> None:
    kit, result = _mint()
    solid = _recipe(kit, result, "button", "#047464")
    assert solid["variant"] == "solid.047464", "a style is named by its look (Q-A9-6)"
    assert solid["rest"]["fill"] == "surface.brand", "Garner's surface.brand holds exactly #047464"
    assert solid["rest"]["label"] == "text.inverse"
    assert solid["rest"]["radius"] == "radius.full", "a pill is 9999px, radius.full exactly"
    # `.btn:hover` paints #035A4E on the `.lift` button too, so the one shared token is named by its
    # value and its provenance names both buttons.
    lift = _recipe(kit, result, "button", "#28241E")
    hover_fill = "button.shared-035a4e.fill"
    assert solid["states"]["hover"]["fill"] == lift["states"]["hover"]["fill"] == hover_fill
    assert _value(kit, "colors", hover_fill) == {"kind": "hex", "value": "#035A4E"}
    entry = kit["tokens"]["colors"][hover_fill]
    sharing = ", ".join(sorted((solid["variant"], lift["variant"])))
    assert entry["provenance"] == {"source": f"website:https://fixture.test/ :: button shared fill ({sharing})", "confidence": 0.8}
    assert entry["role"] == "component"
    assert _value(kit, "styles", solid["states"]["pressed"]["transform"]) == {"kind": "transform", "value": "matrix(0.98, 0, 0, 0.98, 0, 0)"}
    assert _value(kit, "styles", solid["rest"]["case"]) == {"kind": "keyword", "property": "text-transform", "value": "uppercase"}
    assert _value(kit, "colors", solid["states"]["focus"]["outline"]) == {"kind": "hex", "value": "#F5A623"}
    assert _value(kit, "opacity", solid["states"]["disabled"]["opacity"]) == {"kind": "number", "unit": "ratio", "value": 0.45}
    assert solid["icon"]["position"] == "end" and _value(kit, "styles", solid["icon"]["token"])["kind"] == "svg"
    assert [step["property"] for step in solid["motion"]] == ["background-color", "transform", "box-shadow", "transform"]
    assert [step["target"] for step in solid["motion"]] == ["self", "self", "self", "icon"]
    assert _value(kit, "styles", solid["motion"][0]["duration"]) == {"kind": "duration", "ms": 200.0}
    assert solid["motion"][2]["delay"] and _value(kit, "styles", solid["motion"][2]["delay"]) == {"kind": "duration", "ms": 50.0}
    js = _recipe(kit, result, "button", "#7C4CFF")
    assert js["browser_focus_ring"] is True and "focus" not in js["states"]
    link = _recipe(kit, result, "link")
    assert _value(kit, "styles", link["states"]["hover"]["decoration"])["value"] == "underline"
    assert _value(kit, "numbers", link["states"]["hover"]["decoration-thickness"]) == {"kind": "number", "unit": "px", "value": 2.0}
    pulse = _value(kit, "styles", "motion.animation.pulse")
    assert pulse["keyframes"] == "motion.keyframes.pulse" and pulse["iterations"] == "infinite"
    assert [f["offset"] for f in _value(kit, "styles", "motion.keyframes.pulse")["frames"]] == [0.0, 50.0, 100.0]
    (reveal,) = result.section["motion"]["reveals"]
    assert reveal.startswith("motion.reveal.") and _value(kit, "styles", reveal)["kind"] == "reveal"
    assert result.section["motion"]["scripted"] == [{"kind": "scripted", "where": "div#spin.spin"}]


def _digest(value: dict) -> str:
    """The key of a shared non-colour value: sha1 of its canonical JSON, six hex digits."""
    return hashlib.sha1(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:6]


def test_a_value_several_styles_share_is_named_by_its_value() -> None:
    """A value two buttons share is named after the value, never after whichever button the page
    uses most (founder ruling 2026-10-13, option C)."""
    kit, result = _mint()
    solid = _recipe(kit, result, "button", "#047464")
    lift = _recipe(kit, result, "button", "#28241E")
    assert solid["states"]["hover"]["fill"] == lift["states"]["hover"]["fill"] == "button.shared-035a4e.fill"
    assert _value(kit, "colors", "button.shared-035a4e.fill") == {"kind": "hex", "value": "#035A4E"}
    # Its provenance names every style that shares it, sorted, not the one measured first.
    assert kit["tokens"]["colors"]["button.shared-035a4e.fill"]["provenance"] == {
        "source": "website:https://fixture.test/ :: button shared fill (solid.047464, solid.28241e)", "confidence": 0.8,
    }
    shadows = {
        recipe["states"]["hover"]["shadow-1"]
        for recipe in result.section["styles"]
        if recipe["component"] == "button" and "shadow-1" in recipe["states"].get("hover", {})
    }
    (shadow,) = shadows
    assert re.fullmatch(r"button\.shared-[0-9a-f]{6}\.shadow", shadow), shadow
    assert shadow == f"button.shared-{_digest(_value(kit, 'shadows', shadow))}.shadow"


def test_a_value_one_style_uses_keeps_its_own_name() -> None:
    kit, result = _mint()
    solid = _recipe(kit, result, "button", "#047464")
    assert solid["states"]["hover"]["icon-transform"] == "button.solid-047464.hover.icon-transform"
    assert solid["icon"]["token"] == "button.solid-047464.icon"
    # One style using a value in two slots of one kind still names it from where it measured it first.
    js = _recipe(kit, result, "button", "#7C4CFF")
    assert js["rest"]["padding-top"] == js["rest"]["padding-bottom"] == "button.solid-7c4cff.padding-top"


def _button_styles_reversed(styles: list) -> list:
    """The same styles with the buttons in reverse order and every other style where it was."""
    buttons = iter(reversed([style for style in styles if style.surface == "button"]))
    return [next(buttons) if style.surface == "button" else style for style in styles]


def test_shared_names_do_not_depend_on_style_order() -> None:
    """A re-extraction whose usage counts move reorders the buttons; no name may move with them."""
    parsed = parse_geometry(HARVEST, page_url="https://fixture.test/")
    motion = attach_keyframes(parsed.motion, [Stylesheet(url="https://fixture.test/", text=CSS)])
    reordered = _button_styles_reversed(parsed.styles)
    assert [s.variant for s in reordered] != [s.variant for s in parsed.styles]
    first_kit, second_kit = _kit(), _kit()
    first = mint_component_tokens(first_kit, parsed.styles, motion)
    second = mint_component_tokens(second_kit, reordered, motion)

    def by_style(result) -> dict:
        return {(r["component"], r["variant"]): r for r in result.section["styles"]}

    assert by_style(first) == by_style(second)

    def minted(kit: dict, result) -> dict:
        """Every minted entry in full: value, role, description and provenance."""
        return {name: entries[name] for entries in kit["tokens"].values() for name in result.minted if name in entries}

    assert set(first.minted) == set(second.minted)
    assert minted(first_kit, first) == minted(second_kit, second)


def test_identical_values_share_one_token() -> None:
    kit, result = _mint()
    shadows = {
        recipe["states"]["hover"]["shadow-1"]
        for recipe in result.section["styles"]
        if recipe["component"] == "button" and "shadow-1" in recipe["states"].get("hover", {})
    }
    assert len(shadows) == 1, "every .btn hover casts the same shadow"
    assert len(result.minted) == len(set(result.minted))


def _kind(name: str) -> str:
    """The kind of slot a name is for: its last segment without a side, corner or ordinal suffix."""
    return re.sub(r"-(?:top|right|bottom|left|tl|tr|br|bl|\d+)$", "", name.rsplit(".", 1)[-1])


def test_a_minted_token_names_only_its_own_kind_of_slot() -> None:
    """A 2px outline offset is not a link's underline thickness, and a label colour is not a border."""
    kit, result = _mint()
    for recipe in result.section["styles"]:
        for slots in (recipe["rest"], *recipe["states"].values()):
            for slot, token in slots.items():
                if is_component_token(token):
                    assert _kind(token) == _kind(slot), (recipe["component"], recipe["variant"], slot, token)
        for step in recipe["motion"]:
            assert (_kind(step["duration"]), _kind(step["easing"])) == ("duration", "easing"), step
            assert step["delay"] is None or _kind(step["delay"]) == "delay", step
        assert recipe["icon"] is None or _kind(recipe["icon"]["token"]) == "icon"
    link = _recipe(kit, result, "link")
    assert link["states"]["hover"]["decoration-thickness"].startswith("link.")


def _component(name: str) -> str:
    """The component a name is for: its first segment, or its second under `motion.`."""
    parts = name.split(".")
    return parts[1] if parts[0] == "motion" else parts[0]


def test_a_minted_token_names_only_its_own_component() -> None:
    """A link's text is not a button's label, and a card's transition is not a button's."""
    kit, result = _mint()
    for recipe in result.section["styles"]:
        root = component_tokens.COMPONENT_ROOTS[recipe["component"]]
        for slots in (recipe["rest"], *recipe["states"].values()):
            for slot, token in slots.items():
                if is_component_token(token):
                    assert _component(token) == root, (recipe["component"], recipe["variant"], slot, token)
        for step in recipe["motion"]:
            for token in (step["duration"], step["easing"], step["delay"]):
                if token is not None and is_component_token(token):
                    assert _component(token) == root, (recipe["component"], recipe["variant"], step)
        assert recipe["icon"] is None or _component(recipe["icon"]["token"]) == root
    link = _recipe(kit, result, "link")
    assert link["rest"]["label"].startswith("link."), link["rest"]["label"]
    card = _recipe(kit, result, "card")
    assert all(_component(step["duration"]) == "card" for step in card["motion"]), card["motion"]


def test_reuse_is_exact_with_no_tolerance() -> None:
    kit = _kit()
    # Every token holding #047464 (surface.brand, text.brand, palette.primary.600) moves one step off it.
    moved = 0
    for entry in kit["tokens"]["colors"].values():
        default = entry["value"]["default"]
        if default.get("kind") == "hex" and default["value"].upper() == "#047464":
            default["value"], moved = "#047465", moved + 1
    assert moved == 3
    kit, result = _mint(kit)
    solid = _recipe(kit, result, "button", "#047464")
    assert solid["rest"]["fill"] == f"button.{solid['variant'].replace('.', '-')}.fill"


def test_minting_twice_over_the_same_page_names_the_same_tokens() -> None:
    first_kit, first = _mint()
    second_kit, second = _mint()
    assert first.section == second.section
    assert json.dumps(first_kit["tokens"], sort_keys=True) == json.dumps(second_kit["tokens"], sort_keys=True)


def test_the_cap_skips_values_loudly_and_reuse_still_works(monkeypatch) -> None:
    monkeypatch.setattr(component_tokens, "MAX_MINTED_TOKENS", 5)
    kit, result = _mint()
    assert len(result.minted) == 5
    (diagnostic,) = [d for d in result.diagnostics if d["code"] == "LUMI0607"]
    assert "cap of 5 tokens" in diagnostic["message"]
    assert _recipe(kit, result, "button", "#047464")["rest"]["fill"] == "surface.brand"
    monkeypatch.setattr(component_tokens, "MAX_MINTED_TOKENS", 192)
    monkeypatch.setattr(component_tokens, "MAX_MINTED_COLORS", 1)
    colour_kit, limited = _mint()
    assert sum(1 for name in limited.minted if name in colour_kit["tokens"]["colors"]) == 1


def test_a_colour_a_state_clears_is_minted_as_transparent() -> None:
    """A hover that drops the fill draws no fill: the state's `#00000000` is a token like any other."""
    pointer = EvidencePointer(source="website", locator="https://fixture.test/ :: button solid.047464")
    style = MeasuredStyle(
        surface="button", variant="solid.047464", probed="pointer",
        rest=StyleLook(background="#047464"), hover=StyleLook(background="#00000000"), pointer=pointer,
    )
    kit = _kit()
    result = mint_component_tokens(kit, [style], MotionEvidence())
    (recipe,) = result.section["styles"]
    assert recipe["rest"]["fill"] == "surface.brand", "the rest fill is unchanged"
    cleared = recipe["states"]["hover"]["fill"]
    assert cleared in kit["tokens"]["colors"]
    assert _value(kit, "colors", cleared) == {"kind": "hex", "value": "#00000000"}


def test_a_kit_with_minted_tokens_comes_back_from_the_engine_whole() -> None:
    kit, _ = _mint()
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    assert validation["ok"] is True
    returned = validation["brand_kit"]["tokens"]
    for group in ("colors", "radii", "spacing", "stroke_widths", "opacity", "shadows", "typography", "numbers", "styles"):
        assert returned.get(group, {}) == kit["tokens"].get(group, {}), group


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"kind": "keyword", "property": "cursor", "value": "pointer"}, True),
        ({"kind": "keyword", "property": "cursor", "value": "url(a), auto"}, False),
        ({"kind": "keyword", "property": "box-shadow", "value": "none"}, True),
        ({"kind": "keyword", "property": "box-shadow", "value": "0 0 1px red"}, False),
        ({"kind": "keyword", "property": "cursor", "value": "pointer\n"}, False),
        ({"kind": "keyword", "property": "cursor", "value": "   "}, False),
        ({"kind": "easing", "function": "cubic-bezier(0.2, 0.8, 0.2, 1)"}, True),
        ({"kind": "easing", "function": "spring(1)"}, False),
        ({"kind": "transform", "value": "matrix(1, 0, 0, 1, 0, -2)"}, True),
        ({"kind": "transform", "value": "rotate(4deg)"}, False),
        ({"kind": "transform", "value": "matrix(1, 0, 0, 1, 0, -2)\n"}, False),
        ({"kind": "glyph", "text": "→"}, True),
        ({"kind": "glyph", "text": "&"}, False),
        ({"kind": "glyph", "text": "\x7f"}, False),
        ({"kind": "svg", "markup": ICON, "width": 12.0, "height": 12.0}, True),
        ({"kind": "svg", "markup": '<svg onload="x()"></svg>', "width": 12.0, "height": 12.0}, False),
        ({"kind": "svg", "markup": "<svg/onload=x()></svg>", "width": 12.0, "height": 12.0}, False),
        ({"kind": "svg", "markup": "<svg\nonload=x()></svg>", "width": 12.0, "height": 12.0}, False),
        ({"kind": "svg", "markup": '<svg a="1"onload="x()"></svg>', "width": 12.0, "height": 12.0}, False),
    ],
)
def test_ingestion_and_the_engine_agree_on_every_style_value(value: dict, expected: bool) -> None:
    python_ok = {
        "keyword": lambda v: keyword_ok(v["property"], v["value"]),
        "easing": lambda v: easing_ok(v["function"]),
        "transform": lambda v: transform_ok(v["value"]),
        "glyph": lambda v: glyph_ok(v["text"]),
        "svg": lambda v: svg_ok(v["markup"]),
    }[value["kind"]](value)
    assert python_ok is expected
    kit = _kit()
    kit["tokens"]["styles"] = {"button.solid-047464.x": {"value": {"default": value, "modes": {}}, "description": None, "provenance": None}}
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    engine_ok = not any(d["severity"] == "error" and d["code"].startswith("LUMB026") for d in validation["diagnostics"])
    assert engine_ok is expected


def test_svg_ok_accepts_exactly_the_shared_icon_vectors() -> None:
    wrong = [f"refused: {markup!r}" for markup in ICON_SVG_CASES["accept"] if not svg_ok(markup)]
    wrong += [
        f"accepted ({case['why']}): {case['markup']!r}" for case in ICON_SVG_CASES["refuse"] if svg_ok(case["markup"])
    ]
    assert wrong == []


#: Icon markup as real pages write it; the cleaner must turn each into the canonical form or None.
MESSY_ICONS = {
    "a self-closing path": '<svg viewBox="0 0 12 12"><path d="M1 6h9" stroke="currentColor"/></svg>',
    "single quotes": "<svg viewBox='0 0 12 12' fill='none'><path d='M1 6h9' stroke='currentColor'></path></svg>",
    "an onload": '<svg onload="alert(1)" viewBox="0 0 12 12"><path d="M1 6h9"></path></svg>',
    "a title": '<svg viewBox="0 0 12 12"><title>Arrow</title><path d="M1 6h9"></path></svg>',
    "whitespace and newlines between elements": (
        '<svg viewBox="0 0 12 12">\n  <g fill="none">\n    <path d="M1 6h9"></path>\n  </g>\n</svg>'
    ),
    "uppercase names and an xmlns": (
        '<SVG xmlns="http://www.w3.org/2000/svg" VIEWBOX="0 0 12 12"><PATH D="M1 6h9"></PATH></SVG>'
    ),
    "a value ending in a newline": '<svg viewBox="0 0 12 12"><path d="M1 6h9\n" stroke="currentColor"></path></svg>',
    "an img breakout": '<svg viewBox="0 0 12 12"><img src="https://example.com/x.png"><path d="M1 6h9"></path></svg>',
    "nesting deeper than 32": '<svg viewBox="0 0 12 12">' + "<g>" * 40 + '<path d="M1 1"></path>' + "</g>" * 40 + "</svg>",
}


@pytest.mark.parametrize("raw", MESSY_ICONS.values(), ids=MESSY_ICONS.keys())
def test_the_cleaner_only_ever_emits_markup_svg_ok_accepts(raw: str) -> None:
    cleaned = clean_icon_svg(raw)
    assert cleaned is None or svg_ok(cleaned), cleaned


def test_the_cleaner_keeps_messy_icons_that_still_draw() -> None:
    kept = {name: clean_icon_svg(raw) for name, raw in MESSY_ICONS.items()}
    assert kept["a self-closing path"] == '<svg viewBox="0 0 12 12"><path d="M1 6h9" stroke="currentColor"></path></svg>'
    assert kept["single quotes"] == (
        '<svg viewBox="0 0 12 12" fill="none"><path d="M1 6h9" stroke="currentColor"></path></svg>'
    )
    assert kept["an onload"] == kept["a title"] == '<svg viewBox="0 0 12 12"><path d="M1 6h9"></path></svg>'
    assert kept["whitespace and newlines between elements"] == (
        '<svg viewBox="0 0 12 12"><g fill="none"><path d="M1 6h9"></path></g></svg>'
    )
    assert kept["a value ending in a newline"] == '<svg viewBox="0 0 12 12"><path stroke="currentColor"></path></svg>'
    assert kept["nesting deeper than 32"] is None


def test_component_tokens_are_known_by_their_root() -> None:
    assert is_component_token("button.solid-047464.fill") and is_component_token("motion.reveal.ab12cd34")
    assert not is_component_token("surface.band.014036") and not is_component_token("space.card.padding")


def test_the_brief_agents_spacing_ladder_has_no_minted_tokens() -> None:
    kit, _ = _mint()
    evidence = BrandEvidence.model_validate(json.loads((TESTS / "fixtures" / "ingestion" / "evidence_website_insight.json").read_text()))
    request = build_brief_request(evidence, kit)
    assert request.spacing_ladder and not any(is_component_token(row["name"]) for row in request.spacing_ladder)
    assert any(is_component_token(row["name"]) for row in request.tokens), "the model may still name them"
