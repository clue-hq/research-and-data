"""The per-style state pass on a live page (Wave 2 A9, Task X2).

The real probe in headless Chromium — Playwright's and patchright's (the stealth backend's) — over a
local fixture page: CSS hover, press and focus-visible, a script-driven hover, a transform under a
transition, a moving icon, a disabled control, a covered button, a text link, a nav item, a card, a
CSS reveal, a keyframe animation and a scripted animation; and pages that fight the pass — buttons
that leave the page after they were marked (one replaced by a clone of itself), a pulsing call to
action, entrances still running, twin pulses a phase apart, cards wrapped in anchors. No network.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path

import pytest

from lumen_ingestion.capture import states as states_module
from lumen_ingestion.capture.geometry import GEOMETRY_JS, parse_geometry, shape_groups
from lumen_ingestion.capture.states import LOOK_JS, REVEAL_BEFORE_JS, STATE_PASS_DEADLINE_S, probe_states

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "capture"

#: Every marked element's look, in one evaluate: an element that has left the page is simply absent.
LOOKS_JS = (
    "() => Object.fromEntries([...document.querySelectorAll('[data-lumen-probe]')]"
    f".map((el) => [el.dataset.lumenProbe, ({LOOK_JS})(el)]))"
)


async def _capture(engine: str, *, fixture: str = "style_states.html", before_probe=None, after_probe=None) -> dict:
    if engine == "patchright":
        from patchright.async_api import async_playwright
    else:
        from playwright.async_api import async_playwright
    diagnostics: list[dict] = []
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"{engine} chromium unavailable: {error}")
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.goto((FIXTURES / fixture).as_uri())
            reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
            for y in range(0, 4200, 600):
                await page.evaluate(f"window.scrollTo(0, {y})")
                await page.wait_for_timeout(120)
            await page.wait_for_timeout(700)
            await page.evaluate("window.scrollTo(0, 0)")
            geometry = await page.evaluate(GEOMETRY_JS)
            ids = await page.evaluate(
                "() => Object.fromEntries([...document.querySelectorAll('[data-lumen-probe]')]"
                ".map((el) => [el.dataset.lumenProbe, el.id]))"
            )
            if before_probe is not None:
                await before_probe(page)
            looks_before = await page.evaluate(LOOKS_JS)
            shot_before = hashlib.sha256(await page.screenshot(full_page=True)).hexdigest()
            started = time.monotonic()
            result = await probe_states(page, geometry, reveal_before=reveal_before, diagnostics=diagnostics)
            elapsed = time.monotonic() - started
            after = await after_probe(page) if after_probe is not None else None
            await page.evaluate("window.scrollTo(0, 0)")
            looks_after = await page.evaluate(LOOKS_JS)
            shot_after = hashlib.sha256(await page.screenshot(full_page=True)).hexdigest()
            clicked = await page.evaluate("window.__clicked || 0")
        finally:
            await browser.close()
    by_id = {ids.get(str(record["idx"])): record for record in result["styles"]}
    return {
        "geometry": geometry, "result": result, "by_id": by_id, "diagnostics": diagnostics, "elapsed": elapsed,
        "after": after, "same_looks": looks_before == looks_after, "same_shot": shot_before == shot_after,
        "clicked": clicked,
    }


async def _stop_motion(page) -> None:
    await page.evaluate("window.__stopMotion()")


@pytest.mark.parametrize("engine", ["playwright", "patchright"])
def test_each_style_is_measured_in_every_state(engine: str) -> None:
    run = asyncio.run(_capture(engine))
    solid = run["by_id"]["b-solid"]
    assert solid["how"] == "pointer"
    assert solid["hover"]["background"] == "rgb(3, 90, 78)"
    assert "0px 4px 12px" in solid["hover"]["box_shadow"]
    assert solid["hover"]["icon_transform"] == "matrix(1, 0, 0, 1, 4, 0)"
    assert solid["pressed"]["background"] == "rgb(2, 63, 55)"
    assert solid["pressed"]["transform"] == "matrix(0.98, 0, 0, 0.98, 0, 0)"
    assert solid["focus"]["outline_style"] == "solid"
    assert solid["focus"]["outline_color"] == "rgb(245, 166, 35)"
    assert solid["focus"]["outline_width"] == 3 and solid["focus"]["outline_offset"] == 2
    assert solid["disabled"] == {"opacity": 0.45, "cursor": "not-allowed"}
    assert [(t["property"], t["duration_ms"], t["easing"], t["delay_ms"]) for t in solid["motion"]["transitions"]] == [
        ("background-color", 200, "ease-out", 0), ("transform", 150, "ease", 0), ("box-shadow", 300, "ease", 50),
    ]
    assert solid["motion"]["icon"]["kind"] == "svg" and solid["motion"]["icon"]["position"] == "end"
    assert "style=" not in solid["motion"]["icon"]["svg"], "the geometry probe's motion hold leaves no trace"
    assert solid["rest"]["text_transform"] == "uppercase" and solid["rest"]["letter_spacing"] == 0.28

    outline = run["by_id"]["b-outline"]
    assert outline["motion"]["icon"] == {"kind": "glyph", "position": "end", "glyph": "→"}
    assert outline["hover"]["label_color"] == "rgb(255, 255, 255)"

    assert run["by_id"]["b-js"]["hover"]["background"] == "rgb(90, 47, 214)", "the mouseenter hover"
    assert run["by_id"]["b-js"]["focus"] == {"browser_focus_ring": True}, "the browser's ring is not a brand value"
    assert run["by_id"]["b-lift"]["hover"]["transform"] == "matrix(1, 0, 0, 1, 0, -2)"
    covered = run["by_id"]["b-covered"]
    assert covered["how"] == "forced" and covered["hover"]["background"] == "rgb(8, 58, 108)"

    link = run["by_id"]["l-text"]
    assert link["hover"]["decoration_line"] == "underline"
    assert link["hover"]["decoration_thickness"] == "2px"
    assert link["hover"]["color"] == "rgb(4, 116, 100)"
    assert run["by_id"]["n-home"]["hover"]["color"] == "rgb(4, 116, 100)"
    assert "0px 8px 24px" in run["by_id"]["c-card"]["hover"]["box_shadow"]

    assert run["clicked"] == 0, "pressing never clicks"
    assert run["same_looks"], "every element is left as the pass found it"


@pytest.mark.parametrize("engine", ["playwright", "patchright"])
def test_animations_reveals_and_scripted_motion_are_found(engine: str) -> None:
    run = asyncio.run(_capture(engine))
    pulse = next(a for a in run["geometry"]["animations"] if a["name"] == "pulse")
    assert (pulse["duration"], pulse["iterations"], pulse["direction"]) == ("1.6s", "infinite", "alternate")
    reveal = next(r for r in run["result"]["reveals"] if r["where"] == "section#reveal.reveal")
    assert reveal["kind"] == "css" and reveal["from_opacity"] == 0
    assert reveal["from_transform"] == "matrix(1, 0, 0, 1, 0, 24)" and reveal["trigger"] == ["is-in"]
    assert {"kind": "scripted", "where": "div#spin.spin"} in run["result"]["scripted"]
    band = next(s for s in run["geometry"]["sections"] if s.get("id") == "band")
    assert band["ink"] == "rgb(255, 255, 255)"


def test_the_pass_leaves_the_pixels_as_it_found_them() -> None:
    run = asyncio.run(_capture("playwright", before_probe=_stop_motion))
    assert run["same_shot"]


def test_without_a_cdp_session_pointer_hovers_are_still_measured(monkeypatch) -> None:
    async def no_cdp(page) -> None:
        async def refuse(_page):
            raise RuntimeError("no cdp here")
        monkeypatch.setattr(page.context, "new_cdp_session", refuse)

    run = asyncio.run(_capture("playwright", before_probe=no_cdp))
    solid = run["by_id"]["b-solid"]
    assert solid["hover"]["background"] == "rgb(3, 90, 78)"
    assert "pressed" not in solid and "focus" not in solid
    assert any(d["code"] == "LUMI0543" for d in run["diagnostics"])


def test_the_pass_stops_at_its_deadline(monkeypatch) -> None:
    monkeypatch.setattr(states_module, "STATE_PASS_DEADLINE_S", 0.0)
    run = asyncio.run(_capture("playwright"))
    assert run["result"]["styles"] == [] and run["result"]["truncated"] is True
    assert any(d["code"] == "LUMI0544" for d in run["diagnostics"])


def test_a_target_that_leaves_the_page_costs_no_more_than_the_deadline() -> None:
    """A carousel or a re-hydrating framework replaces a marked element: the pass skips it at once and
    measures the rest, inside its wall clock (a wait on the vanished element took the page's default
    timeout, 30 s here and 90 s under the stealth backend)."""

    async def rerender_after_marking(page) -> None:
        await page.evaluate("window.__rerender(document.getElementById('b-gone'))")

    run = asyncio.run(_capture("playwright", fixture="vanishing_targets.html", before_probe=rerender_after_marking))
    assert run["elapsed"] < STATE_PASS_DEADLINE_S + 3, f"state pass took {run['elapsed']:.1f}s"
    assert run["result"]["truncated"] is False
    stay = run["by_id"]["b-stay"]
    assert stay["how"] == "pointer" and stay["hover"]["background"] == "rgb(3, 90, 78)"
    assert run["by_id"]["n-home"]["how"] == "pointer", "the styles after the vanished ones are measured too"
    # The element re-rendered under the pointer is not measured by half: no record rather than the
    # empty reads of a detached element.
    assert "b-gone" not in run["by_id"] and "b-rerender" not in run["by_id"]
    # Nor is one replaced by a clone of itself: the clone keeps the probe's mark, so the forced states
    # still find a marked element, and only the read of the detached one it holds can refuse it.
    assert "b-clone" not in run["by_id"], run["by_id"].get("b-clone")


def test_a_running_animation_is_not_read_as_a_state() -> None:
    """A pulsing CTA: rest is the authored static look, hover is the fill alone, and no frame of the
    pulse (its halo, its scale) becomes the rest, hover or disabled look. A CTA that faded in on load
    is read as it ended, not from its authored `opacity: 0`."""

    async def pulse_after(page) -> list:
        return await page.evaluate(
            "() => { const el = document.getElementById('b-pulse');"
            " return [el.style.cssText, getComputedStyle(el).animationName]; }"
        )

    run = asyncio.run(_capture("playwright", fixture="animated_cta.html", after_probe=pulse_after))
    pulse = run["by_id"]["b-pulse"]
    assert pulse["rest"]["box_shadow"] is None and pulse["rest"]["transform"] is None, pulse["rest"]
    assert pulse["how"] == "pointer", "a still element takes the real pointer"
    assert pulse["hover"] == {"background": "rgb(3, 90, 78)"}
    assert not {"box_shadow", "transform"} & set(pulse["pressed"]), pulse["pressed"]
    assert not {"box_shadow", "transform"} & set(pulse["disabled"]), pulse["disabled"]
    assert run["after"] == ["", "pulse"], "the animation is given back"

    styles = {s.variant: s for s in parse_geometry({**run["geometry"], "states": run["result"]},
                                                    page_url="https://fixture.test/").styles}
    assert styles["solid.047464"].rest.box_shadow is None and styles["solid.047464"].rest.transform is None

    # An entrance that has finished keeps its last frame (opaque, no offset): the CTA the page shows,
    # not its authored start (`opacity: 0`, 16px down).
    fade = run["by_id"]["b-fade"]
    assert fade["rest"]["opacity"] == 1 and fade["rest"]["transform"] == "matrix(1, 0, 0, 1, 0, 0)", fade["rest"]
    assert fade["hover"] == {"background": "rgb(0, 0, 0)"}


#: A transform with no offset: none, or the identity an entrance that ends on `transform: none` holds.
_NO_OFFSET = (None, "matrix(1, 0, 0, 1, 0, 0)")


def test_an_entrance_still_running_is_read_where_it_ends() -> None:
    """A CTA fading in over 4 s, and one waiting out a 3 s delay before a short fade, are still moving
    when the probes reach them: each is read at rest as the page will show it (opaque, in place), never
    from its authored start (`opacity: 0`, 16px down). Run as the capture runs it, and again with every
    animation rewound to its start just before the state pass, so the state pass's own rule is held to it."""

    async def rewind(page) -> None:
        await page.evaluate("() => document.getAnimations().forEach((a) => { a.currentTime = 0; })")

    for before_probe in (None, rewind):
        run = asyncio.run(_capture("playwright", fixture="entrance_ctas.html", before_probe=before_probe))
        for key in ("b-slow", "b-late"):
            rest = run["by_id"][key]["rest"]
            assert rest["opacity"] == 1 and rest["transform"] in _NO_OFFSET, (before_probe, key, rest)
        assert run["by_id"]["b-slow"]["hover"] == {"background": "rgb(3, 90, 78)"}


def test_twin_pulses_a_phase_apart_are_one_style_with_one_name() -> None:
    """Two identical buttons pulsing a box-shadow forever, a phase apart: the geometry probe reads each
    without its pulse, so they are one look with one plain name, the same on every extraction, and the
    pulse is still captured as page motion."""
    runs = [asyncio.run(_capture("playwright", fixture="pulse_twins.html")) for _ in range(2)]
    names = [[(name, len(members)) for name, members in shape_groups(run["geometry"]["surfaces"], ("button",))]
             for run in runs]
    assert names[0] == names[1] == [("solid.047464", 2)], names
    for run in runs:
        assert [s["shadow"] for s in run["geometry"]["surfaces"] if s["cls"] == "button"] == [None, None]
        assert any(a["name"] == "pulse" for a in run["geometry"]["animations"])
        assert run["by_id"]["b-first"]["rest"]["box_shadow"] is None

def test_cards_wrapped_in_anchors_are_not_the_text_link_style() -> None:
    """Six anchor-wrapped feature cards outnumber the two inline links; the link style is still the
    inline links' look, and a menu entry wrapped in an anchor is not a nav item."""
    run = asyncio.run(_capture("playwright", fixture="anchor_cards.html"))
    parsed = parse_geometry({**run["geometry"], "states": run["result"]}, page_url="https://fixture.test/")
    links = [(s.variant, s.count, s.probed) for s in parsed.styles if s.surface == "link"]
    assert links == [("ghost.0b5cad", 2, "pointer")], links
    assert run["by_id"]["l-docs"]["hover"]["color"] == "rgb(8, 66, 124)"
    assert {s.variant for s in parsed.styles if s.surface == "nav_link"} == {"ghost.0d2b25"}
