"""Wave 2 A9 business-logic scenarios: the measured brand, end to end (founder ruling 2026-10-13).

Each scenario drives the REAL composed system: a local page served from 127.0.0.1 (never a real
site) → `POST /brand-kits/ingest/website` → the embedded fleet worker → the real capture (rendered
tier, the configured backend, the state pass) → the real evidence builder → the real normalizer and
minting → the real engine helper (`validate_brand_kit`) → the real publish into the test database
(`clue_w2_a9`) and temp storage → `GET /brand-kits/{id}` and the curation, approval and tenancy routes.

The ONLY thing replaced is the SSRF guard's refusal of loopback: `guard_url` (capture/net.py, and the
name rendered.py imported, which the route's `_resolve_guard_url` also resolves) lets exactly
`http://127.0.0.1:<this server's port>` through and hands every other URL to the real guard.

Run keyless (no provider key, so no model call): the brief stage is unconfigured and stays silent.
A scenario that exposes a real defect stays failing as `xfail(strict=True, reason="A9 scenario: …")`.

Set `A9_SCENARIO_KIT_OUT=<path>` to have scenario 1 write the kit detail it read (the body of
`GET /brand-kits/{id}`) for site-kit's scenarios (apps/frontend/packages/site-kit/test/a9-scenarios.test.tsx).
"""

from __future__ import annotations

import copy
import functools
import json
import os
import re
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from lumen_ingestion.brief import kit_token_names
from lumen_ingestion.measured_components import (
    VARIANT_PATTERN,
    MeasuredComponents,
    token_references,
    validate_measured_components,
)
from lumen_ingestion.normalizer.component_tokens import is_component_token

from conftest import make_client, wait_for_ingestion_job

TESTS = Path(__file__).resolve().parent
DESIGN_ROOT = Path(__file__).resolve().parents[3]
CAPTURE = TESTS / "fixtures" / "capture"
PAGES = CAPTURE / "a9_scenarios"
GARNER_KIT = TESTS / "fixtures" / "ingestion" / "garner_kit.json"
LOGO_PNG = DESIGN_ROOT / "crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png"
#: A real rendered capture takes ~20 s here; a stale task in the shared test queue can come first.
INGESTION_TIMEOUT_S = 240.0

FIVE_BUTTONS = {"outline.0d2b25", "solid.047464", "solid.0a4a8a", "solid.28241e", "solid.7c4cff"}
BRIEF_CODES = {"LUMI0901", "LUMI0902", "LUMI0903"}

#: The kit group each measured slot's token must live in (site-kit reads each slot from that group:
#: colorOf → colors, pxOf → spacing/radii/stroke_widths/opacity/numbers, typographyOf, styleOf, shadowOf).
SLOT_GROUPS = {
    "fill": {"colors"}, "label": {"colors"}, "border": {"colors"}, "outline": {"colors"}, "icon-color": {"colors"},
    "border-width": {"stroke_widths"}, "outline-width": {"stroke_widths"},
    "border-style": {"styles"}, "outline-style": {"styles"}, "case": {"styles"}, "decoration": {"styles"},
    "cursor": {"styles"}, "filter": {"styles"}, "transform": {"styles"}, "icon-transform": {"styles"},
    "shadow": {"styles"}, "shadow-n": {"shadows"},
    "radius": {"radii"}, "padding": {"spacing"}, "gap": {"spacing"},
    "height": {"numbers"}, "outline-offset": {"numbers"},
    "decoration-thickness": {"numbers", "styles"}, "underline-offset": {"numbers", "styles"},
    "font": {"typography"}, "opacity": {"opacity"}, "icon-opacity": {"opacity"},
}


# --- the local site and the one guard relaxation ------------------------------------------------


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D102 — keep pytest output readable
        return None


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """style_states.html and the A9 variants, served from 127.0.0.1 on a random port."""
    root = tmp_path_factory.mktemp("a9-site")
    shutil.copy(CAPTURE / "style_states.html", root / "style_states.html")
    for page in PAGES.glob("*.html"):
        shutil.copy(page, root / page.name)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield SimpleNamespace(port=port, url=lambda name: f"http://127.0.0.1:{port}/{name}")
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def local_guard(monkeypatch: pytest.MonkeyPatch, site) -> None:
    """The SSRF guard, with exactly this test server let through; every other URL meets the real one."""
    from lumen_ingestion.capture import net, rendered

    real_guard = net.guard_url

    async def guard(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port == site.port:
            return url
        return await real_guard(url)

    monkeypatch.setattr(net, "guard_url", guard)
    monkeypatch.setattr(rendered, "guard_url", guard)


@pytest.fixture()
def client(tmp_path: Path, local_guard) -> TestClient:
    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache"))


# --- helpers -----------------------------------------------------------------------------------


def _ingest(client: TestClient, url: str, **request) -> dict:
    """The website route, the fleet worker and the whole pipeline; the job's terminal row."""
    post = client.post("/brand-kits/ingest/website", json={"url": url, **request})
    assert post.status_code == 200, post.text
    job = wait_for_ingestion_job(client, post.json()["job"]["job_id"], timeout_s=INGESTION_TIMEOUT_S)
    assert job.get("status") == "succeeded", json.dumps(job, indent=1)[:4000]
    return job


def _detail(client: TestClient, kit_id: str, version: int | None = None) -> dict:
    path = f"/brand-kits/{kit_id}" if version is None else f"/brand-kits/{kit_id}/versions/{version}"
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _kit_of(client: TestClient, url: str, **request) -> tuple[dict, dict]:
    job = _ingest(client, url, **request)
    detail = _detail(client, job["brand_kit_id"])
    return job, detail


#: Read-only scenarios over the same page share one real ingestion (each takes ~20 s); a scenario
#: that writes (curation, approval, re-extraction, tenancy) always ingests its own kit.
_PUBLISHED: dict[str, tuple[dict, dict]] = {}


def _published(client: TestClient, site, page: str) -> tuple[dict, dict]:
    if page not in _PUBLISHED:
        _PUBLISHED[page] = _kit_of(client, site.url(page))
    return copy.deepcopy(_PUBLISHED[page])


def _drain_enrichment(client: TestClient, headers: dict | None = None) -> None:
    """Wait for the asset-enrichment jobs an upload offered to finish while this test's workers live.

    An upload offers an `asset_enrichment` job whose collect loop (`ingestion_tasks.enqueue_and_collect`)
    polls until its child analysis tasks are terminal, with no deadline and no stop check. If the test
    ends first, the TestClient teardown stops the analysis worker and then waits forever for that
    thread (seen in this suite's first full run; see the A9 scenarios report).
    """
    import time

    deadline = time.monotonic() + 120.0
    while True:
        jobs = [j for j in client.get("/brand-kits/ingest", headers=headers or {}).json()["jobs"] if j.get("kind") == "asset_enrichment"]
        if all(j.get("status") in ("succeeded", "failed") for j in jobs):
            return
        assert time.monotonic() < deadline, jobs
        time.sleep(0.2)


def _groups_holding(kit: dict, name: str) -> set[str]:
    return {group for group, entries in (kit.get("tokens") or {}).items() if isinstance(entries, dict) and name in entries}


def _value(kit: dict, name: str, group: str | None = None) -> dict:
    groups = [group] if group else sorted(_groups_holding(kit, name))
    assert groups, f"{name} is not in the kit"
    return kit["tokens"][groups[0]][name]["value"]["default"]


def _hex(kit: dict, name: str) -> str:
    value = _value(kit, name, "colors")
    assert value.get("kind") == "hex", (name, value)
    return str(value["value"]).upper()


def _slot_kind(slot: str) -> str:
    if re.fullmatch(r"shadow-\d+", slot):
        return "shadow-n"
    return re.sub(r"-(top|right|bottom|left|tl|tr|br|bl)$", "", slot)


def _styles(kit: dict) -> list[dict]:
    return kit["measured_components"]["styles"]


def _style(kit: dict, component: str, variant: str) -> dict:
    found = [s for s in _styles(kit) if s["component"] == component and s["variant"] == variant]
    assert len(found) == 1, (component, variant, [(s["component"], s["variant"]) for s in _styles(kit)])
    return found[0]


def _variants(kit: dict, component: str) -> set[str]:
    return {s["variant"] for s in _styles(kit) if s["component"] == component}


def _minted(kit: dict) -> dict[tuple[str, str], dict]:
    """Every token the measurement added: component and motion tokens, band surfaces and band inks."""
    return {
        (group, name): entry["value"]["default"]
        for group, entries in (kit.get("tokens") or {}).items()
        if isinstance(entries, dict)
        for name, entry in entries.items()
        if is_component_token(name) or name.startswith(("surface.band.", "text.band."))
    }


def _style_refs(value: dict) -> list[str]:
    """Names a `styles` token value points at (an animation's keyframes and timing, a reveal's parts)."""
    kind = value.get("kind")
    if kind == "animation":
        return [n for n in (value.get("keyframes"), value.get("duration"), value.get("easing"), value.get("delay")) if n]
    if kind == "reveal":
        return [n for n in (value.get("from_opacity"), value.get("from_transform"), value.get("duration"), value.get("easing")) if n]
    return []


def _assert_sections_resolve(kit: dict) -> None:
    """The token law and the kind law: every name the section speaks is a token of THIS kit, in the
    group site-kit reads that slot from, and every motion name is a style token of the right kind."""
    section = MeasuredComponents.model_validate(kit["measured_components"])
    names = kit_token_names(kit)
    unresolved = [f"{where}={token}" for where, token in token_references(section) if token not in names]
    assert unresolved == [], unresolved
    wrong: list[str] = []
    for style in kit["measured_components"]["styles"]:
        where = f"{style['component']} {style['variant']}"
        slot_sets = [("rest", style["rest"])] + [(state, slots) for state, slots in style["states"].items()]
        for state, slots in slot_sets:
            for slot, token in slots.items():
                expected = SLOT_GROUPS[_slot_kind(slot)]
                if not expected & _groups_holding(kit, token):
                    wrong.append(f"{where} {state}.{slot}={token} in {sorted(_groups_holding(kit, token))}, want {sorted(expected)}")
        for step in style["motion"]:
            for key, kind in (("duration", "duration"), ("easing", "easing"), ("delay", "duration")):
                token = step.get(key)
                if token and _value(kit, token, "styles").get("kind") != kind:
                    wrong.append(f"{where} motion.{key}={token} is not a {kind}")
        if style.get("icon"):
            if _value(kit, style["icon"]["token"], "styles").get("kind") not in ("glyph", "svg"):
                wrong.append(f"{where} icon={style['icon']['token']} is not a glyph or svg")
    for token in kit["measured_components"]["motion"]["animations"]:
        if _value(kit, token, "styles").get("kind") != "animation":
            wrong.append(f"motion.animations {token} is not an animation")
    for token in kit["measured_components"]["motion"]["reveals"]:
        if _value(kit, token, "styles").get("kind") != "reveal":
            wrong.append(f"motion.reveals {token} is not a reveal")
    for name, entry in (kit["tokens"].get("styles") or {}).items():
        for ref in _style_refs(entry["value"]["default"]):
            if not _groups_holding(kit, ref):
                wrong.append(f"styles {name} points at {ref}, which the kit does not carry")
    assert wrong == [], "\n".join(wrong)


# --- 1. the extraction, end to end --------------------------------------------------------------


def test_scenario_1_the_extraction_publishes_every_measured_style_state_and_motion(client: TestClient, site) -> None:
    url = site.url("style_states.html")
    job, detail = _published(client, site, "style_states.html")
    kit = detail["brand_kit_json"]

    out = os.environ.get("A9_SCENARIO_KIT_OUT")
    if out:
        Path(out).write_text(json.dumps(detail, indent=1, sort_keys=True))

    # Published: version 1, auto-approved at publication (founder 2026-09-21).
    assert detail["brand_kit"]["version"] == 1
    assert detail["brand_kit"]["approval_status"] == "approved"
    assert detail["brand_kit"]["id"] == job["brand_kit_id"] and detail["brand_kit"]["source"] == "website"

    # The brief stage ran with no key: it was skipped (NullBriefAgent), the kit carries no brief and
    # says nothing about one — no LUMI0901/0902/0903 anywhere on the published version.
    assert "brief" not in kit
    codes = {d.get("code") for view in detail["diagnostics"].values() for d in view}
    assert not (codes & BRIEF_CODES), codes

    # The two code-owned sections ride the published kit, the measured one exactly as validated.
    assert kit["grammar_audit"]["schema_version"] == 1
    section = kit["measured_components"]
    assert section["schema_version"] == 1 and section["source"] == f"website:{url}"
    assert validate_measured_components(section, token_names=kit_token_names(kit)) == section
    assert kit["tokens"]["styles"], "the engine kept the styles group through its round trip"
    _assert_sections_resolve(kit)

    # Every minted token is reachable from the section (nothing minted that nothing names).
    reached = {token for _, token in token_references(MeasuredComponents.model_validate(section))}
    frontier = list(reached)
    while frontier:
        name = frontier.pop()
        if name in (kit["tokens"].get("styles") or {}):
            for ref in _style_refs(kit["tokens"]["styles"][name]["value"]["default"]):
                if ref not in reached:
                    reached.add(ref)
                    frontier.append(ref)
    orphans = sorted(name for (_, name) in _minted(kit) if is_component_token(name) and name not in reached)
    assert orphans == [], orphans

    # The five buttons, named by look; every one probed through a real pointer except the covered one.
    assert _variants(kit, "button") == FIVE_BUTTONS
    assert {(s["component"], s["variant"]) for s in _styles(kit) if s["component"] != "button"} >= {
        ("link", "ghost.0d2b25"), ("nav_link", "ghost.0d2b25"), ("card", "solid.f1f0de"),
    }
    assert {s["variant"]: s["probed"] for s in _styles(kit) if s["component"] == "button"} == {
        "outline.0d2b25": "pointer", "solid.047464": "pointer", "solid.0a4a8a": "forced",
        "solid.28241e": "pointer", "solid.7c4cff": "pointer",
    }
    for variant in FIVE_BUTTONS:
        assert re.fullmatch(VARIANT_PATTERN, variant)

    # The filled button in every state, with the values the page draws.
    solid = _style(kit, "button", "solid.047464")
    assert set(solid["states"]) == {"hover", "pressed", "focus", "disabled"}
    assert _hex(kit, solid["rest"]["fill"]) == "#047464"
    assert _hex(kit, solid["rest"]["label"]) == "#FFFFFF"
    assert _value(kit, solid["rest"]["case"])["value"] == "uppercase"
    assert solid["rest"]["radius"] == "radius.full", "a pill names the kit's fully round radius"
    assert _hex(kit, solid["states"]["hover"]["fill"]) == "#035A4E"
    hover_shadow = _value(kit, solid["states"]["hover"]["shadow-1"], "shadows")
    assert (hover_shadow["y"], hover_shadow["blur"]) == (4, 12)
    assert _value(kit, solid["states"]["hover"]["icon-transform"])["value"] == "matrix(1, 0, 0, 1, 4, 0)"
    assert _hex(kit, solid["states"]["pressed"]["fill"]) == "#023F37"
    assert _value(kit, solid["states"]["pressed"]["transform"])["value"] == "matrix(0.98, 0, 0, 0.98, 0, 0)"
    focus = solid["states"]["focus"]
    assert _hex(kit, focus["outline"]) == "#F5A623"
    assert _value(kit, focus["outline-width"], "stroke_widths")["value"] == 3
    assert _value(kit, focus["outline-offset"], "numbers")["value"] == 2
    assert _value(kit, focus["outline-style"])["value"] == "solid"
    assert _value(kit, solid["states"]["disabled"]["opacity"], "opacity")["value"] == 0.45
    assert _value(kit, solid["states"]["disabled"]["cursor"])["value"] == "not-allowed"
    steps = [
        (m["target"], m["property"], _value(kit, m["duration"])["ms"], _value(kit, m["easing"])["function"],
         _value(kit, m["delay"])["ms"] if m["delay"] else 0)
        for m in solid["motion"]
    ]
    assert steps == [
        ("self", "background-color", 200, "ease-out", 0), ("self", "transform", 150, "ease", 0),
        ("self", "box-shadow", 300, "ease", 50), ("icon", "transform", 200, "ease", 0),
    ]
    icon = _value(kit, solid["icon"]["token"], "styles")
    assert solid["icon"]["position"] == "end" and icon["kind"] == "svg" and icon["markup"].startswith("<svg")

    # The other buttons' own states: a label that turns white, a script-driven hover, a forced hover
    # under a covering element, a lift.
    outline = _style(kit, "button", "outline.0d2b25")
    assert _hex(kit, outline["states"]["hover"]["label"]) == "#FFFFFF"
    assert _value(kit, outline["icon"]["token"], "styles") == {"kind": "glyph", "text": "→"}
    scripted = _style(kit, "button", "solid.7c4cff")
    assert _hex(kit, scripted["states"]["hover"]["fill"]) == "#5A2FD6"
    assert scripted["browser_focus_ring"] is True and "focus" not in scripted["states"]
    covered = _style(kit, "button", "solid.0a4a8a")
    assert _hex(kit, covered["states"]["hover"]["fill"]) == "#083A6C"
    lift = _style(kit, "button", "solid.28241e")
    assert _value(kit, lift["states"]["hover"]["transform"])["value"] == "matrix(1, 0, 0, 1, 0, -2)"

    # A text link, a nav item and a card.
    link = _style(kit, "link", "ghost.0d2b25")
    assert _value(kit, link["states"]["hover"]["decoration"])["value"] == "underline"
    assert _value(kit, link["states"]["hover"]["decoration-thickness"])["value"] == 2
    assert _hex(kit, link["states"]["hover"]["label"]) == "#047464"
    assert _hex(kit, _style(kit, "nav_link", "ghost.0d2b25")["states"]["hover"]["label"]) == "#047464"
    card = _style(kit, "card", "solid.f1f0de")
    assert _value(kit, card["states"]["hover"]["shadow-1"], "shadows")["blur"] == 24

    # Motion: the pulse animation with its keyframes, the scroll reveal, and the scripted spinner.
    motion = section["motion"]
    assert motion["animations"] == ["motion.animation.pulse"]
    pulse = _value(kit, "motion.animation.pulse", "styles")
    assert (pulse["iterations"], pulse["direction"]) == ("infinite", "alternate")
    assert _value(kit, pulse["duration"])["ms"] == 1600 and _value(kit, pulse["easing"])["function"] == "ease-in-out"
    frames = _value(kit, pulse["keyframes"], "styles")["frames"]
    assert [f["offset"] for f in frames] == [0.0, 50.0, 100.0]
    assert len(motion["reveals"]) == 1
    reveal = _value(kit, motion["reveals"][0], "styles")
    assert _value(kit, reveal["from_transform"])["value"] == "matrix(1, 0, 0, 1, 0, 24)"
    assert _value(kit, reveal["from_opacity"], "opacity")["value"] == 0
    assert _value(kit, reveal["duration"])["ms"] == 600 and _value(kit, reveal["easing"])["function"] == "ease-out"
    assert motion["scripted"] == [{"kind": "scripted", "where": "div#spin.spin"}]

    # The dark band became a surface with its own text colour and contrast pair.
    assert _hex(kit, "surface.band.014036") == "#014036"
    pairs = [p for p in kit["constraints"]["contrast_pairs"] if p["background"] == "surface.band.014036"]
    assert len(pairs) == 1 and _hex(kit, pairs[0]["foreground"]) == "#FFFFFF"


# --- 2. stable names across extractions ---------------------------------------------------------


def test_scenario_2_a_second_extraction_of_the_same_page_names_everything_the_same(client: TestClient, site) -> None:
    url = site.url("style_states.html")
    first_job, first = _kit_of(client, url)
    kit_id = first_job["brand_kit_id"]
    second_job, second = _kit_of(client, url, brand_kit_id=kit_id)
    assert second_job["brand_kit_id"] == kit_id
    assert (first["brand_kit"]["version"], second["brand_kit"]["version"]) == (1, 2), "the re-extraction is the kit's next version"

    one, two = first["brand_kit_json"], second["brand_kit_json"]
    assert two["measured_components"] == one["measured_components"]
    assert sorted(_minted(two)) == sorted(_minted(one)), "the same minted token names"
    assert _minted(two) == _minted(one), "and the same values behind them"
    assert two["tokens"]["styles"].keys() == one["tokens"]["styles"].keys()

    # History keeps the first version whole.
    assert _detail(client, kit_id, 1)["brand_kit_json"]["measured_components"] == one["measured_components"]


# --- 3. twins and the accepted residual ---------------------------------------------------------


def test_scenario_3_twins_take_suffixes_and_dropping_one_gives_the_plain_name_back(client: TestClient, site) -> None:
    job, twins = _kit_of(client, site.url("twins.html"))
    kit = twins["brand_kit_json"]
    suffixed = sorted(v for v in _variants(kit, "button") if v.startswith("solid.047464"))
    assert len(suffixed) == 2 and all(re.fullmatch(r"solid\.047464\.[0-9a-f]{4}", v) for v in suffixed), suffixed
    _assert_sections_resolve(kit)
    pill = next(v for v in suffixed if _style(kit, "button", v)["rest"].get("radius") == "radius.full")
    square = next(v for v in suffixed if v != pill)
    assert _value(kit, _style(kit, "button", square)["rest"]["radius"], "radii")["value"] == 4

    # Re-extraction of the same lineage after the square twin is gone (twin_dropped.html).
    _, dropped = _kit_of(client, site.url("twin_dropped.html"), brand_kit_id=job["brand_kit_id"])
    after = dropped["brand_kit_json"]
    assert dropped["brand_kit"]["version"] == 2
    assert {v for v in _variants(after, "button") if v.startswith("solid.047464")} == {"solid.047464"}
    assert _style(after, "button", "solid.047464")["rest"]["radius"] == "radius.full", "the same pill"
    # The accepted residual (founder Q-A9-6): the pill's v1 name is gone from v2, so a document saved
    # with `buttonLook: "<pill's v1 name>"` no longer names a style of the re-extracted kit.
    assert pill not in _variants(after, "button")
    _assert_sections_resolve(after)


# --- 4. hostile icons ---------------------------------------------------------------------------

#: What no stored style token may carry: an event-handler attribute (whatever precedes it), a script,
#: a `<use>`, any href, a javascript: URL.
HOSTILE = [
    re.compile(r"[\s/\"'\\]on[a-z]+\s*="),
    re.compile(r"onload|onclick|onerror|onmouse", re.I),
    re.compile(r"<script", re.I),
    re.compile(r"<use", re.I),
    re.compile(r"href", re.I),
    re.compile(r"javascript:", re.I),
    re.compile(r"window\.__h"),
]
HOSTILE_BUTTONS = {"solid.1b5e20", "solid.b71c1c", "solid.0d47a1", "solid.4a148c", "solid.e65100"}


def test_scenario_4_hostile_icons_reach_no_style_token_and_the_engine_accepts_the_kit(client: TestClient, site) -> None:
    # The job succeeding IS the engine accepting the kit: the pipeline raises on any error diagnostic
    # from `validate_brand_kit` before it publishes.
    _, detail = _published(client, site, "hostile_icons.html")
    kit = detail["brand_kit_json"]
    assert _variants(kit, "button") >= HOSTILE_BUTTONS, _variants(kit, "button")
    styles_text = json.dumps(kit["tokens"]["styles"])
    found = [pattern.pattern for pattern in HOSTILE if pattern.search(styles_text)]
    assert found == [], found
    _assert_sections_resolve(kit)
    # Record the icons the capture kept (cleaned) for the report.
    print("A4 icons:", json.dumps({
        variant: (_value(kit, style["icon"]["token"], "styles") if (style := _style(kit, "button", variant))["icon"] else None)
        for variant in sorted(HOSTILE_BUTTONS)
    }, indent=1))


#: Strings only the hostile page's markup carries (the page's prose names none of them).
HOSTILE_MARKERS = ("window.__h", "onload", "onclick", "<script", "<use", "#arrow")


def test_scenario_4b_no_part_of_the_published_kit_carries_the_hostile_markup(client: TestClient, site) -> None:
    _, detail = _published(client, site, "hostile_icons.html")
    text = json.dumps(detail["brand_kit_json"])
    found = [marker for marker in HOSTILE_MARKERS if marker in text]
    assert found == [], found


def _icon_of(kit: dict, variant: str) -> dict | None:
    style = _style(kit, "button", variant)
    return _value(kit, style["icon"]["token"], "styles") if style["icon"] else None


def test_scenario_4d_a_sprite_icon_is_resolved_and_an_icon_that_draws_nothing_is_not_kept(
    client: TestClient, site
) -> None:
    # The capture reads a sprite icon with its in-page <use href="#arrow"> replaced by the symbol's
    # drawing, so the seller's arrow is kept; an icon with nothing left to draw is never kept.
    _, detail = _published(client, site, "hostile_icons.html")
    icon = _icon_of(detail["brand_kit_json"], "solid.4a148c")  # the <use href="#arrow"> button
    assert icon is not None and icon["kind"] == "svg" and "<path" in icon["markup"], icon


def test_scenario_4f_sprite_forms_xlink_resolves_and_an_external_sprite_is_not_kept(
    client: TestClient, site
) -> None:
    _, detail = _published(client, site, "sprite_icons.html")
    kit = detail["brand_kit_json"]
    # (a) <use xlink:href="#arrow">: resolved; the symbol's viewBox is copied onto the bare svg.
    xlink = _icon_of(kit, "solid.00695c")
    assert xlink is not None and "<path" in xlink["markup"], xlink
    assert 'viewBox="0 0 12 12"' in xlink["markup"], xlink
    # (b) <use href="/sprite.svg#arrow">: an external sprite is not resolved; nothing to draw.
    assert _icon_of(kit, "solid.ad1457") is None
    # (c) the control: a plain inline path.
    inline = _icon_of(kit, "solid.283593")
    assert inline is not None and "<path" in inline["markup"], inline
    _assert_sections_resolve(kit)


def _engine_verdict(client: TestClient, markup: str) -> set[str]:
    """`POST /brand-kits/validate` (the real helper) over a real kit carrying one svg icon token."""
    kit = json.loads(GARNER_KIT.read_text())
    kit.setdefault("tokens", {})["styles"] = {
        "button.solid-1b5e20.icon": {
            "value": {"default": {"kind": "svg", "markup": markup, "width": 12, "height": 12}},
            "description": None,
            "provenance": {"source": "website:http://127.0.0.1/ :: button solid.1b5e20 icon", "confidence": 0.9},
        }
    }
    response = client.post("/brand-kits/validate", json={"brand_kit": kit, "product_ready": False})
    assert response.status_code == 200, response.text
    return {d.get("code") for d in response.json()["diagnostics"]["current"] if d.get("severity") == "error"}


CLEAN_ICON = '<svg width="12" height="12" viewBox="0 0 12 12"><path d="M1 6h9" stroke="currentColor"></path></svg>'
#: The four forms the brief names, as raw markup (what a hand-written kit could post).
ENGINE_REFUSES = {
    "after a space": '<svg onload="alert(1)" width="12" height="12"><path d="M1 6h9"></path></svg>',
    "after a slash": '<svg/onload="alert(1)" width="12" height="12"><path d="M1 6h9"></path></svg>',
    "a script": '<svg width="12" height="12"><script>alert(1)</script><path d="M1 6h9"></path></svg>',
    "a use href": '<svg width="12" height="12"><use href="#arrow"></use></svg>',
}


def test_scenario_4c_the_engine_itself_refuses_each_hostile_icon_form(client: TestClient) -> None:
    assert "LUMB0265" not in _engine_verdict(client, CLEAN_ICON), "the control icon is accepted"
    verdicts = {form: _engine_verdict(client, markup) for form, markup in ENGINE_REFUSES.items()}
    assert {form: ("LUMB0265" in codes) for form, codes in verdicts.items()} == dict.fromkeys(ENGINE_REFUSES, True), verdicts


#: Beyond the brief's four: markup a hand-written kit (POST /brand-kits) could carry, which site-kit
#: inlines with dangerouslySetInnerHTML. Inside inline <svg>, an HTML parser breaks out of SVG at
#: <img>/<embed>, so those become live HTML elements that load what they name.
ENGINE_EXTRAS = {
    "an animated event attribute": '<svg width="12" height="12"><set attributeName="onclick" to="alert(1)"></set><path d="M1 6h9"></path></svg>',
    "an <img> breakout loading a remote file": '<svg width="12" height="12"><img src="https://tracker.invalid/p.gif"><path d="M1 6h9"></path></svg>',
    "an <embed> breakout": '<svg width="12" height="12"><embed src="https://evil.invalid/x"><path d="M1 6h9"></path></svg>',
}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A9 scenario (beyond the brief's four forms): the engine's icon check is a deny-list "
        "(lumen-core brand.rs icon_svg_ok) and accepts <svg> markup carrying an HTML <img>/<embed> "
        "breakout that loads a remote URL, or a <set attributeName=\"onclick\">; site-kit's own re-check "
        "(brand-values.ts isSafeIconSvg) accepts them too and Button inlines the markup. Reachable only "
        "through a hand-written kit (POST /brand-kits); ingestion's allow-list cleaner never emits them"
    ),
)
def test_scenario_4e_the_engine_refuses_icon_markup_that_loads_or_animates_handlers(client: TestClient) -> None:
    verdicts = {form: _engine_verdict(client, markup) for form, markup in ENGINE_EXTRAS.items()}
    print("A4e engine verdicts:", {form: sorted(codes) for form, codes in verdicts.items()})
    assert {form: ("LUMB0265" in codes) for form, codes in verdicts.items()} == dict.fromkeys(ENGINE_EXTRAS, True), verdicts


# --- 5. a hover that clears the fill ------------------------------------------------------------


def test_scenario_5_a_hover_that_clears_the_fill_mints_a_transparent_hover_fill(client: TestClient, site) -> None:
    _, detail = _published(client, site, "hover_clears.html")
    kit = detail["brand_kit_json"]
    style = _style(kit, "button", "solid.7a1f5c")
    assert _hex(kit, style["rest"]["fill"]) == "#7A1F5C"
    hover = style["states"]["hover"]
    assert "fill" in hover, hover
    assert _hex(kit, hover["fill"]) == "#00000000"
    assert _hex(kit, hover["label"]) == "#7A1F5C"
    _assert_sections_resolve(kit)


def test_scenario_5b_a_filled_cta_anchor_without_a_btn_class_is_measured_as_a_button(client: TestClient, site) -> None:
    _, detail = _published(client, site, "hover_clears.html")
    kit = detail["brand_kit_json"]
    print("A5b styles:", sorted((s["component"], s["variant"]) for s in _styles(kit)))
    assert "solid.3b2f8f" in _variants(kit, "button"), sorted((s["component"], s["variant"]) for s in _styles(kit))
    # The ordinary text link in the paragraph (unfilled) is still a link, and the CTA is not one.
    assert _variants(kit, "link") == {"ghost.1f4e79"}, _variants(kit, "link")


# --- 6. curation keeps the sections -------------------------------------------------------------

SECTIONS = ("measured_components", "grammar_audit", "brief")


def _sections(kit: dict) -> dict:
    return {key: kit.get(key) for key in SECTIONS} | {"styles": kit["tokens"].get("styles")}


def test_scenario_6_logo_and_describe_curation_republish_with_every_section(client: TestClient, site) -> None:
    job, first = _kit_of(client, site.url("style_states.html"))
    kit_id = job["brand_kit_id"]
    before = _sections(first["brand_kit_json"])
    assert before["measured_components"] and before["grammar_audit"] and before["styles"]
    assert before["brief"] is None, "keyless: no brief to carry (scenario 1)"

    uploaded = client.post(
        "/assets",
        files={"file": ("acme-logo.png", LOGO_PNG.read_bytes(), "image/png")},
        data={"label": "The real lockup", "kind": "logo", "uploaded_by": "designer"},
    )
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["asset"]["id"]
    chosen = client.post(f"/brand-kits/{kit_id}/logo", json={"asset_id": asset_id, "slot": "primary"})
    assert chosen.status_code == 200, chosen.text
    logo_version = _detail(client, kit_id)
    assert logo_version["brand_kit"]["version"] == 2
    assert [v["asset_id"] for v in logo_version["brand_kit_json"]["assets"]["logos"]["primary"]["variants"]] == [asset_id]
    assert _sections(logo_version["brand_kit_json"]) == before
    _assert_sections_resolve(logo_version["brand_kit_json"])

    # describe-assets with no describer (keyless): nothing new is stamped, so nothing is republished.
    idle = client.post(f"/brand-kits/{kit_id}/describe-assets")
    assert idle.status_code == 200, idle.text
    print("A6 keyless describe-assets:", json.dumps(idle.json())[:600])
    assert idle.json()["published"] is False
    # A human-written description is the cache it stamps from (no model): a new version.
    described = client.put(
        f"/assets/{asset_id}/description",
        json={"title": "Lockup", "description": "The red square mark.", "usage": "On light surfaces.", "tags": ["logo"]},
    )
    assert described.status_code == 200, described.text
    stamped = client.post(f"/brand-kits/{kit_id}/describe-assets")
    assert stamped.status_code == 200, stamped.text
    assert stamped.json()["published"] is True, stamped.json()
    third = _detail(client, kit_id)
    assert third["brand_kit"]["version"] == 3
    assert third["brand_kit_json"]["assets"]["logos"]["primary"]["description"] == "The red square mark."
    assert _sections(third["brand_kit_json"]) == before
    _assert_sections_resolve(third["brand_kit_json"])
    _drain_enrichment(client)


# --- 7. approval and the kit read ---------------------------------------------------------------


def test_scenario_7_approval_round_trips_keep_the_sections_on_the_kit_read(client: TestClient, site) -> None:
    job, first = _kit_of(client, site.url("style_states.html"))
    kit_id = job["brand_kit_id"]
    before = _sections(first["brand_kit_json"])
    for status in ("draft", "approved"):
        response = client.post(f"/brand-kits/{kit_id}/approval", json={"approval_status": status})
        assert response.status_code == 200, response.text
        assert response.json()["brand_kit"]["approval_status"] == status
        assert _sections(response.json()["brand_kit_json"]) == before
        read = _detail(client, kit_id)
        assert read["brand_kit"]["approval_status"] == status
        assert _sections(read["brand_kit_json"]) == before
    assert _detail(client, kit_id)["brand_kit"]["version"] == 1, "approval flips the version in place"


# --- 8. tenancy ---------------------------------------------------------------------------------


def test_scenario_8_another_workspace_can_neither_read_nor_curate_the_kit(client: TestClient, site, workspace_id: str) -> None:
    # The conftest has no two-workspace helper; workspace B is the same app called with another
    # X-Workspace-Id, the way test_workspace_seam.py builds its intruder. B is a workspace that has
    # used the product: its first request is a read that succeeds (see 8b for why that matters here).
    job, detail = _kit_of(client, site.url("style_states.html"))
    kit_id = job["brand_kit_id"]
    assert kit_id in {row["id"] for row in client.get("/brand-kits").json()}, "listed for workspace A"
    other = {"X-Workspace-Id": f"{workspace_id}_b"}
    assert kit_id not in {row["id"] for row in client.get("/brand-kits", headers=other).json()}
    assert client.get(f"/brand-kits/{kit_id}", headers=other).status_code == 404
    assert client.get(f"/brand-kits/{kit_id}/versions/1", headers=other).status_code == 404
    assert client.get(f"/brand-kits/ingest/{job['job_id']}", headers=other).status_code == 404
    assert client.post("/brand-kits/validate", json={"brand_kit_id": kit_id}, headers=other).status_code == 404
    assert client.post(f"/brand-kits/{kit_id}/approval", json={"approval_status": "draft"}, headers=other).status_code == 404
    assert client.post(f"/brand-kits/{kit_id}/describe-assets", headers=other).status_code == 404
    uploaded = client.post(
        "/assets",
        files={"file": ("acme-logo.png", LOGO_PNG.read_bytes(), "image/png")},
        data={"label": "B's logo", "kind": "logo"},
        headers=other,
    )
    assert uploaded.status_code == 200, uploaded.text
    stolen = client.post(f"/brand-kits/{kit_id}/logo", json={"asset_id": uploaded.json()["asset"]["id"]}, headers=other)
    assert stolen.status_code == 404, stolen.text
    _drain_enrichment(client, other)
    # Workspace A still reads it, unchanged.
    assert _detail(client, kit_id)["brand_kit_json"] == detail["brand_kit_json"]
    assert _detail(client, kit_id)["brand_kit"]["version"] == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "pre-existing, not A9 (dev/test workspace scaffolding): design_store._ensure_workspace adds the "
        "workspace to the process cache BEFORE its transaction commits; when that first request is a read "
        "that 404s, the INSERT rolls back but the cache says 'ensured', so every later governed write from "
        "that workspace fails the execution_workspace_fk constraint with a 500 instead of answering"
    ),
)
def test_scenario_8b_a_workspace_whose_first_request_404s_can_still_be_answered(client: TestClient, workspace_id: str) -> None:
    fresh = {"X-Workspace-Id": f"{workspace_id}_fresh"}
    assert client.get("/brand-kits/brand_kit_nope", headers=fresh).status_code == 404
    answered = client.post("/brand-kits/brand_kit_nope/approval", json={"approval_status": "draft"}, headers=fresh)
    assert answered.status_code == 404, answered.text[:400]
