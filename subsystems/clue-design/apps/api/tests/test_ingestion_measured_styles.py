"""Measured styles and motion as evidence (Wave 2 A9, Task X3).

From the real probe's harvest of the fixture page (fixtures/capture/style_states.harvest.json, written
by make_style_states_harvest.py in Task X2), so every value here is one a browser computed.
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_ingestion.brief_agent import build_brief_request
from lumen_ingestion.capture.geometry import measured_styles, parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes, clean_icon_svg, keyframe_steps
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.evidence import BrandEvidence, MotionEvidence

TESTS = Path(__file__).resolve().parent
HARVEST = json.loads((TESTS / "fixtures" / "capture" / "style_states.harvest.json").read_text())
URL = "https://fixture.test/"


def _parsed():
    return parse_geometry(HARVEST, page_url=URL)


def _button(styles, background: str):
    return next(s for s in styles if s.surface == "button" and s.rest.background == background)


def test_each_measured_style_carries_its_states_motion_and_icon() -> None:
    styles = _parsed().styles
    solid = _button(styles, "#047464")
    assert solid.variant == "solid.047464" and solid.probed == "pointer", "named by its fill (Q-A9-6)"
    assert solid.rest.text_transform == "uppercase" and solid.rest.letter_spacing == 0.28
    assert (solid.rest.font_family, solid.rest.font_size, solid.rest.font_weight) == ("Arial", 14, 500)
    assert solid.rest.pill is True and solid.rest.padding == [12, 24, 12, 24]
    assert solid.hover.background == "#035A4E"
    assert solid.pressed.transform == "matrix(0.98, 0, 0, 0.98, 0, 0)"
    assert (solid.focus.outline_color, solid.focus.outline_width, solid.focus.outline_offset) == ("#F5A623", 3, 2)
    assert (solid.disabled.opacity, solid.disabled.cursor) == (0.45, "not-allowed")
    assert [(t.target, t.property, t.duration_ms, t.delay_ms) for t in solid.transitions] == [
        ("self", "background-color", 200, 0), ("self", "transform", 150, 0), ("self", "box-shadow", 300, 50),
        ("icon", "transform", 200, 0),
    ]
    assert solid.icon.kind == "svg" and solid.icon.position == "end"
    assert solid.icon.svg.startswith('<svg width="12" height="12" viewBox="0 0 12 12"') and "<path" in solid.icon.svg
    assert solid.hover.icon_transform == "matrix(1, 0, 0, 1, 4, 0)"

    outline = next(s for s in styles if s.surface == "button" and s.variant == "outline.0d2b25")
    assert (outline.icon.kind, outline.icon.glyph) == ("glyph", "→")
    assert outline.hover.label_color == "#FFFFFF"
    js = _button(styles, "#7C4CFF")
    assert js.focus.browser_focus_ring is True and js.focus.outline_color is None
    assert _button(styles, "#0A4A8A").probed == "forced"

    link = next(s for s in styles if s.surface == "link")
    assert (link.hover.decoration_line, link.hover.decoration_thickness, link.hover.color) == ("underline", "2px", "#047464")
    assert next(s for s in styles if s.surface == "nav_link").hover.color == "#047464"
    assert next(s for s in styles if s.surface == "card").hover.box_shadow.startswith("rgba(0, 0, 0, 0.12)")


def test_links_and_nav_items_add_no_scale_samples_and_no_shape_records() -> None:
    parsed = _parsed()
    assert all(shape.surface not in ("link", "nav_link") for shape in parsed.surfaces)
    stripped = {**HARVEST, "surfaces": [s for s in HARVEST["surfaces"] if s["cls"] not in ("link", "nav_link")]}
    assert parse_geometry(stripped, page_url=URL).numbers == parsed.numbers


def test_motion_evidence_holds_the_animation_the_reveal_and_the_scripted_note() -> None:
    parsed = _parsed()
    pulse = next(a for a in parsed.motion.animations if a.name == "pulse")
    assert (pulse.duration_ms, pulse.easing, pulse.iterations, pulse.direction) == (1600, "ease-in-out", "infinite", "alternate")
    reveal = parsed.motion.reveals[0]
    assert (reveal.from_opacity, reveal.from_transform) == (0, "matrix(1, 0, 0, 1, 0, 24)")
    assert (reveal.duration_ms, reveal.easing, reveal.trigger) == (600, "ease-out", ["is-in"])
    assert [(n.kind, n.where) for n in parsed.motion.scripted] == [("scripted", "div#spin.spin")]
    band = next(b for b in parsed.background_sequence if b.background == "#014036")
    assert band.ink == "#FFFFFF"


def _sheet(text: str) -> Stylesheet:
    return Stylesheet(url="https://fixture.test/a.css", text=text)


def test_keyframes_come_from_the_captured_stylesheets_in_cascade_order() -> None:
    sheets = [
        _sheet("@keyframes pulse{from{opacity:1}to{opacity:.2}}"),
        _sheet(
            "@media (min-width:1px){@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}"
            "50%{opacity:.5;background-image:url(x.png);color:var(--x)}}}"
        ),
    ]
    steps = keyframe_steps(sheets, "pulse")
    assert [(s.offset, s.declarations) for s in steps] == [
        (0.0, {"opacity": "1", "transform": "scale(1)"}),
        (50.0, {"opacity": ".5"}),
        (100.0, {"opacity": "1", "transform": "scale(1)"}),
    ]
    assert keyframe_steps(sheets, "missing") == []


def test_a_keyframe_step_outside_0_to_100_percent_is_dropped() -> None:
    steps = keyframe_steps([_sheet("@keyframes k{0%{opacity:1}150%{opacity:.3}100%{opacity:0}}")], "k")
    assert [(s.offset, s.declarations) for s in steps] == [(0.0, {"opacity": "1"}), (100.0, {"opacity": "0"})]


def _surface(idx: int, **overrides) -> dict:
    """A button entry in the probe's surface shape (style_states.harvest.json)."""
    entry = {
        "bg": "rgb(4, 116, 100)", "bgImage": None, "border": [1, 1, 1, 1], "borderColor": "rgb(4, 116, 100)",
        "borderStyle": "solid", "cls": "button", "color": "rgb(255, 255, 255)", "disabled": False,
        "font": "500 14px/19.6px Arial", "gap": [8, 8], "h": 45.59, "idx": idx, "padding": [12, 24, 12, 24],
        "pill": True, "radius": [999, 999, 999, 999], "shadow": None, "tag": "a", "w": 245.22,
    }
    return {**entry, **overrides}


def _record(idx: int, rest: dict, hover: dict) -> dict:
    """A state-pass record in the probe's shape (style_states.harvest.json `states.styles`)."""
    return {
        "idx": idx, "how": "pointer",
        "rest": {"color": "rgb(255, 255, 255)", "cursor": "pointer", **rest},
        "hover": hover, "pressed": {}, "focus": {}, "disabled": {},
        "motion": {"icon": None, "icon_transitions": [], "label_transitions": [], "transitions": []},
    }


def test_a_colour_a_state_clears_is_kept_as_transparent() -> None:
    surfaces = [
        _surface(0),
        # Transparent at rest and in no state: the browser serializes the fill as rgba(0, 0, 0, 0).
        _surface(1, bg=None, borderColor="rgb(13, 43, 37)", color="rgb(13, 43, 37)"),
    ]
    states = {"styles": [
        _record(0, {"background": "rgb(4, 116, 100)"}, {"background": "rgba(0, 0, 0, 0)"}),
        # The rest probe's own transparent colours stay unset (only a state's delta clears one).
        _record(1, {"background": "rgba(0, 0, 0, 0)", "label_color": "rgba(0, 0, 0, 0)"}, {}),
    ]}
    styles = measured_styles(surfaces, states, URL)
    solid = next(s for s in styles if s.variant == "solid.047464")
    assert solid.rest.background == "#047464"
    assert solid.hover.background == "#00000000", "a fill the hover clears is recorded, not read as unchanged"
    outline = next(s for s in styles if s.variant == "outline.0d2b25")
    assert outline.rest.background is None and outline.rest.label_color is None and outline.hover is None


def test_an_animation_without_a_usable_definition_is_dropped() -> None:
    motion = _parsed().motion
    assert attach_keyframes(motion, []).animations == []
    css = (TESTS / "fixtures" / "capture" / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
    attached = attach_keyframes(motion, [_sheet(css)])
    assert [step.offset for step in attached.animations[0].frames] == [0.0, 50.0, 100.0]


def test_an_icon_svg_keeps_only_drawing_elements_and_attributes() -> None:
    raw = (
        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" onload="x()"><script>x()</script>'
        '<path d="M1 6h9" stroke="currentColor" style="fill:url(#a)"/><use href="#b"/>'
        "<foreignObject><div>x</div></foreignObject></svg>"
    )
    assert clean_icon_svg(raw) == (
        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 6h9" stroke="currentColor"></path></svg>'
    )
    assert clean_icon_svg("<div>no</div>") is None
    assert clean_icon_svg("<svg>" + '<path d="M0 0"></path>' * 400 + "</svg>") is None


def test_the_brief_agents_evidence_is_unchanged_by_the_new_measurements() -> None:
    evidence = BrandEvidence.model_validate(
        json.loads((TESTS / "fixtures" / "ingestion" / "evidence_website_insight.json").read_text())
    )
    geometry = _parsed().evidence()
    with_new = evidence.model_copy(update={"geometry": geometry})
    without = evidence.model_copy(update={"geometry": geometry.model_copy(update={
        "styles": [], "motion": MotionEvidence(),
        "background_sequence": [band.model_copy(update={"ink": None}) for band in geometry.background_sequence],
    })})
    assert build_brief_request(with_new, {}).evidence_json() == build_brief_request(without, {}).evidence_json()
