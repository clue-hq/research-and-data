"""`fetch_logo` on both design lanes.

The network is faked at the ladder's own driver seam, so these exercise what
the tool does with a resolution — ingest, register with the LANE-CORRECT
operation key, and refuse to place anything it cannot attribute.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import logo_fetch
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _vendor_rung_disabled(monkeypatch):
    """No test in this file may reach Brandfetch: the repo .env carries a real key.
    Tests that exercise the vendor path monkeypatch `logo_fetch._vendor_rung` themselves."""
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing

    def disabled(site, company):
        raise VendorCredentialsMissing()

    monkeypatch.setattr(logo_fetch, "_vendor_rung", disabled)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


def _svg(fill: str = "#101820", width: int = 160, height: int = 32) -> bytes:
    bars = "".join(
        f'<rect x="{x}" y="6" width="24" height="20" fill="{fill}"/>'
        for x in (4, 34, 64, 94)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{bars}</svg>'
    ).encode()


def _png(size: int = 180) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), (18, 32, 48, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


#: Ink colours the arbiter must be able to MEASURE off the bytes.
DARK_INK = (58, 38, 26)     # brown art: for LIGHT surfaces
ORANGE_INK = (240, 138, 44)  # mid-tone: measures `unknown`


def _flat_png(width: int, height: int, rgb: tuple) -> bytes:
    """Flat art on transparency, at a real logo's proportions."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(
        [width // 8, height // 4, width * 7 // 8, height * 3 // 4], fill=rgb + (255,)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


GOODMAN_HTML = """
<html><head><title>Goodman Campbell Brain and Spine</title>
  <link rel="apple-touch-icon" href="/brand/goodman-logomark.png"></head>
<body>
  <header><a href="/">
    <img src="/brand/goodman-alogo.svg" alt="Goodman Campbell" width="160" height="32">
  </a></header>
  <footer style="background:#10182f">
    <img src="/brand/goodman-logo-white.svg" alt="Goodman Campbell" width="160" height="32">
  </footer>
</body></html>
"""

GOODMAN_ASSETS = {
    "https://goodmancampbell.com/brand/goodman-alogo.svg": (_svg(), "image/svg+xml"),
    "https://goodmancampbell.com/brand/goodman-logo-white.svg": (_svg("#ffffff"), "image/svg+xml"),
    "https://goodmancampbell.com/brand/goodman-logomark.png": (_png(), "image/png"),
    "https://goodmancampbell.com/favicon.ico": (_png(32), "image/x-icon"),
}

# A page whose header holds only somebody else's logo: no asset on it carries
# our brand's name evidence, so nothing may be attributed to us.
PARTNER_ONLY_HTML = """
<html><head><title>Globex Industries</title></head>
<body><header><a href="/partners/aws">
  <img src="/cdn/aws-black.svg" alt="Amazon Web Services" width="66" height="40">
</a></header></body></html>
"""
PARTNER_ONLY_ASSETS = {
    "https://globex.io/cdn/aws-black.svg": (_svg("#000000", 66, 40), "image/svg+xml"),
    "https://globex.io/favicon.ico": (_png(32), "image/x-icon"),
}

JS_SHELL_HTML = "<html><head><title>Acme</title></head><body><div id=root></div></body></html>"


def _fake_site(monkeypatch, html: str, assets: dict, host: str) -> None:
    """Resolve the ladder against fixed page + asset bytes, with no sockets."""
    from lumen_ingestion import logo_ladder

    async def fake_driver(url_or_domain, *, company_name=None, **kwargs):
        page_url = logo_ladder.normalize_site_url(url_or_domain)
        candidates = logo_ladder.harvest(html, page_url)
        logo_ladder.attach_bytes(candidates, assets)
        meta = {
            "homepage_url": page_url,
            "page_title": logo_ladder.page_title(html),
            "jsonld_org_names": logo_ladder.jsonld_org_names(html),
            "tier": "static",
        }
        return logo_ladder.resolve(candidates, meta, host, company_name)

    monkeypatch.setattr(logo_ladder, "fetch_logo_family", fake_driver)


def _web_tools(tmp_path: Path) -> LumenWebTools:
    from lumen_api.core import CoreClient

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root"
    )
    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_web_test", "Test site", None)["web_doc"]
    return LumenWebTools(config, "Build an ABM page", initial_web_doc=seed)


def _scene_tools(tmp_path: Path, monkeypatch) -> LumenDesignTools:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    return LumenDesignTools(runtime_config(tmp_path), "Make an ABM poster")


# --------------------------------------------------------------------------- #
# shared helper
# --------------------------------------------------------------------------- #


def test_the_helper_shapes_one_ingest_per_resolved_slot(monkeypatch):
    _fake_site(monkeypatch, GOODMAN_HTML, GOODMAN_ASSETS, "goodmancampbell.com")
    outcome = logo_fetch.fetch_logo_family("goodmancampbell.com")

    cells = {p.cell for p in outcome.prepared}
    assert {"light_lockup", "dark_lockup"} <= cells
    assert not outcome.needs_review

    light = next(p for p in outcome.prepared if p.cell == "light_lockup")
    kwargs = light.ingest_kwargs("/tmp/store")
    # Content-addressed, so the same brand fetched twice is the same asset.
    assert kwargs["asset_id"] == light.asset_id
    assert light.asset_id.startswith("asset_ing_")
    assert kwargs["declared_mime_type"] == "image/svg+xml"
    assert kwargs["kind"] == "vector"
    assert kwargs["provenance"]["created_by"] == "logo_ladder"
    assert kwargs["source"]["kind"] == "website"
    assert kwargs["source"]["url"].endswith("goodman-alogo.svg")
    assert set(kwargs["tags"]) == set(logo_fetch.LOGO_TAGS)
    assert kwargs["raise_on_error"] is False


def test_the_helper_reports_review_without_preparing_anything(monkeypatch):
    _fake_site(monkeypatch, PARTNER_ONLY_HTML, PARTNER_ONLY_ASSETS, "globex.io")
    outcome = logo_fetch.fetch_logo_family("globex.io")

    assert outcome.needs_review
    assert outcome.prepared == []
    payload = logo_fetch.review_payload(outcome)
    assert payload["status"] == "needs_review"
    assert "Do not draw, recolor, or approximate" in payload["what_to_do"]


# --------------------------------------------------------------------------- #
# web lane
# --------------------------------------------------------------------------- #


def test_web_fetch_logo_registers_with_the_record_op_key(tmp_path, monkeypatch):
    _fake_site(monkeypatch, GOODMAN_HTML, GOODMAN_ASSETS, "goodmancampbell.com")
    tools = _web_tools(tmp_path)

    result = json.loads(tools.fetch_logo("goodmancampbell.com", "Goodman Campbell"))

    assert result["status"] in ("ok", "needs_review")
    assert result["logos"], "at least one cell must be registered"
    cells = {entry["cell"] for entry in result["logos"]}
    assert "light_lockup" in cells

    # Registered into the WebDoc's own asset table...
    for entry in result["logos"]:
        assert entry["asset_id"] in tools.web_doc["assets"]
    # ...through the checked op path, and the WEB key is `record`.
    upserts = [op for op in tools.operations_ledger if op.get("kind") == "upsert_asset"]
    assert upserts, "the registration must be in the replayable ledger"
    assert all("record" in op for op in upserts)
    assert all("asset" not in op for op in upserts)

    # Evidence travels with each cell so the agent can explain the choice.
    light = next(e for e in result["logos"] if e["cell"] == "light_lockup")
    assert light["rung"] in ("HEADER", "NAV_VISIBLE", "INLINE_SVG", "PAGE_LOGO_NAMED")
    assert light["source"] in ("ladder", "ladder-materialized")
    assert result["identity"]["passed"] is True
    assert "cache_hit" in result


def test_web_fetch_logo_threads_force_refresh_and_the_configured_cache(
    tmp_path, monkeypatch
):
    """The tool's `force_refresh` and the turn config's cache reach the prep layer."""
    from lumen_api.core import CoreClient

    sentinel = object()
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        logo_family_cache=sentinel,
    )
    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_web_cache", "Test site", None)["web_doc"]
    tools = LumenWebTools(config, "Build an ABM page", initial_web_doc=seed)

    captured: dict = {}

    def recorder(requested, **kwargs):
        captured["requested"] = requested
        captured.update(kwargs)
        return logo_fetch.LogoFetchOutcome(
            status="needs_review", site="https://acme.com/", company=None
        )

    monkeypatch.setattr(logo_fetch, "fetch_logo_family", recorder)

    result = json.loads(tools.fetch_logo("acme.com", force_refresh=True))

    assert result["status"] == "needs_review"
    assert captured["force_refresh"] is True
    assert captured["cache"] is sentinel


def test_web_fetch_logo_needs_review_ingests_nothing(tmp_path, monkeypatch):
    _fake_site(monkeypatch, PARTNER_ONLY_HTML, PARTNER_ONLY_ASSETS, "globex.io")
    tools = _web_tools(tmp_path)
    before = dict(tools.web_doc.get("assets") or {})

    result = json.loads(tools.fetch_logo("globex.io"))

    assert result["status"] == "needs_review"
    assert "logos" not in result
    assert result["ranked_candidates"], "a human needs the list to choose from"
    assert dict(tools.web_doc.get("assets") or {}) == before
    assert not [op for op in tools.operations_ledger if op.get("kind") == "upsert_asset"]


def test_web_fetch_logo_rejects_an_empty_domain(tmp_path):
    tools = _web_tools(tmp_path)
    result = json.loads(tools.fetch_logo("  "))
    assert result["error_code"] == "logo_fetch.bad_request"


def test_web_fetch_logo_reports_a_js_shell_honestly(tmp_path, monkeypatch):
    """No Playwright mid-turn: a JS-shell page says so rather than guessing."""
    _fake_site(monkeypatch, JS_SHELL_HTML, {}, "acme.com")
    tools = _web_tools(tmp_path)

    result = json.loads(tools.fetch_logo("acme.com"))

    assert result["status"] == "needs_review"
    assert not [op for op in tools.operations_ledger if op.get("kind") == "upsert_asset"]


# --------------------------------------------------------------------------- #
# scene lane
# --------------------------------------------------------------------------- #


def test_scene_fetch_logo_registers_with_the_asset_op_key(tmp_path, monkeypatch):
    _fake_site(monkeypatch, GOODMAN_HTML, GOODMAN_ASSETS, "goodmancampbell.com")
    tools = _scene_tools(tmp_path, monkeypatch)

    result = json.loads(tools.fetch_logo("goodmancampbell.com", "Goodman Campbell"))

    assert result["logos"]
    upserts = [
        op for op in tools.core.applied_operations if op.get("kind") == "upsert_asset"
    ]
    assert upserts, "the registration must reach the scene"
    # SCENE key is `asset`, never `record`.
    assert all("asset" in op for op in upserts)
    assert all("record" not in op for op in upserts)

    # It must be in the operations ledger, or the accept seam drops the mutation.
    logged = [
        entry for entry in tools.operations_ledger
        if entry.get("source") == "fetch_logo"
    ]
    assert logged, "an unlogged scene mutation vanishes at accept"

    assert "asset(action='place'" in result["next"]


def test_scene_fetch_logo_needs_review_ingests_nothing(tmp_path, monkeypatch):
    _fake_site(monkeypatch, PARTNER_ONLY_HTML, PARTNER_ONLY_ASSETS, "globex.io")
    tools = _scene_tools(tmp_path, monkeypatch)

    result = json.loads(tools.fetch_logo("globex.io"))

    assert result["status"] == "needs_review"
    assert not [
        op for op in tools.core.applied_operations if op.get("kind") == "upsert_asset"
    ]


def test_scene_fetch_logo_rejects_an_empty_domain(tmp_path, monkeypatch):
    tools = _scene_tools(tmp_path, monkeypatch)
    result = json.loads(tools.fetch_logo(""))
    assert result["error_code"] == "logo_fetch.bad_request"


# --------------------------------------------------------------------------- #
# registration on both harnesses
# --------------------------------------------------------------------------- #


def test_fetch_logo_is_offered_to_both_authors(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    scene_tools = LumenDesignTools(runtime_config(tmp_path), "Make a poster")
    assert callable(scene_tools.fetch_logo)

    web_tools = _web_tools(tmp_path)
    assert callable(web_tools.fetch_logo)

    from lumen_agent import harness, harness_web

    assert "tools.fetch_logo" in Path(harness.__file__).read_text()
    assert "tools.fetch_logo" in Path(harness_web.__file__).read_text()


# --------------------------------------------------------------------------- #
# ladder slots -> 2x2 cells
# --------------------------------------------------------------------------- #


def _slot(body: bytes, *, lockup: str, variant: str, provenance: str = "genuine",
          url: str = "https://acme.com/logo.svg", rung: str = "HEADER",
          content_type: str = "image/svg+xml", width: int | None = None,
          height: int | None = None):
    from lumen_ingestion.logo_ladder import LadderCandidate, LadderSlot

    fmt = "svg" if content_type == "image/svg+xml" else content_type.rsplit("/", 1)[-1]
    candidate = LadderCandidate(url=url, rung=rung, fmt=fmt, width=width, height=height)
    candidate.lockup = lockup
    candidate.variant = variant
    return LadderSlot(candidate=candidate, provenance=provenance, body=body,
                      content_type=content_type, basis="test basis")


def _resolution(slots):
    from lumen_ingestion.logo_ladder import LadderResolution

    res = LadderResolution(status="resolved", identity={"passed": True})
    res.slots = {"light": None, "dark": None, "mark": None, "wordmark": None, **slots}
    return res


def test_ladder_candidates_maps_lockup_primaries_and_variant_marks():
    from lumen_agent.tools.logo_fetch import ladder_candidates

    found = ladder_candidates(_resolution({
        "light": _slot(_svg(), lockup="full_lockup", variant="light",
                       content_type="image/png", width=400, height=80),
        "dark": _slot(_svg("#ffffff"), lockup="full_lockup", variant="dark"),
        "mark": _slot(_svg(), lockup="symbol", variant="unknown"),
    }))
    assert set(found) == {"light_lockup", "dark_lockup", "light_mark"}
    assert found["light_lockup"][0].source == "ladder"
    # The size the arbiter ranks on rides along with each candidate.
    assert found["light_lockup"][0].evidence["width"] == 400
    assert found["light_lockup"][0].evidence["height"] == 80


def test_ladder_candidates_symbol_primary_lands_in_the_mark_cell():
    from lumen_agent.tools.logo_fetch import ladder_candidates

    found = ladder_candidates(_resolution({
        "light": _slot(_svg(), lockup="symbol", variant="light"),
    }))
    assert list(found) == ["light_mark"]


def test_ladder_candidates_wordmark_competes_for_light_lockup_and_materialized_is_stamped():
    """The wordmark slot used to be dropped whenever the light slot was filled.
    It now stands beside it and the arbiter picks."""
    from lumen_agent.tools.logo_fetch import ladder_candidates

    found = ladder_candidates(_resolution({
        "light": _slot(_svg(), lockup="full_lockup", variant="light",
                       url="https://acme.com/header.svg"),
        "wordmark": _slot(_svg(), lockup="wordmark", variant="light",
                          url="https://acme.com/wordmark.svg"),
        "dark": _slot(_svg("#ffffff"), lockup="full_lockup", variant="adaptive",
                      provenance="materialized-adaptive"),
    }))
    assert [c.evidence["ladder_slot"] for c in found["light_lockup"]] == ["light", "wordmark"]
    assert found["dark_lockup"][0].source == "ladder-materialized"


def test_ladder_candidates_symbol_primary_and_mark_slot_both_propose():
    from lumen_agent.tools.logo_fetch import ladder_candidates

    found = ladder_candidates(_resolution({
        "light": _slot(_svg(), lockup="symbol", variant="light",
                       url="https://acme.com/primary.svg"),
        "mark": _slot(_svg(), lockup="symbol", variant="unknown",
                      url="https://acme.com/mark.svg"),
    }))
    assert list(found) == ["light_mark"]
    assert [c.origin_url for c in found["light_mark"]] == [
        "https://acme.com/primary.svg", "https://acme.com/mark.svg"
    ]


# --------------------------------------------------------------------------- #
# the two-rung dispatch
# --------------------------------------------------------------------------- #


class _RecordingCache:
    def __init__(self):
        self.stored = {}
        self.gets = []

    def get(self, site):
        self.gets.append(site)
        return self.stored.get(site)

    def put(self, site, outcome):
        self.stored[site] = outcome


def _vendor_cells(*names):
    from lumen_ingestion.logo_family import SOURCE_BRANDFETCH, FamilyCell

    return {
        n: FamilyCell(cell=n, body=_svg(), content_type="image/svg+xml",
                      source=SOURCE_BRANDFETCH, origin_url=f"https://a/{n}.svg",
                      evidence={"vendor_type": "symbol" if n.endswith("_mark") else "logo"})
        for n in names
    }


def test_dispatch_runs_the_ladder_even_when_the_vendor_filled_every_cell(monkeypatch):
    """Both sources always propose (founder ruling): a full vendor family no
    longer buys the site's own assets out of the running."""
    from lumen_agent.tools import logo_fetch

    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells(*logo_fetch.CELL_NAMES), []),
    )

    asked = []

    def ladder(site, company):
        asked.append(site)
        return _resolution({})

    monkeypatch.setattr(logo_fetch, "_ladder_rung", ladder)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert asked == ["https://acme.com/"]
    assert outcome.status == "ok"
    assert set(outcome.cells) == set(logo_fetch.CELL_NAMES)
    assert all(source == "brandfetch" for source in outcome.cells.values())
    assert {p.cell for p in outcome.prepared} == set(logo_fetch.CELL_NAMES)
    assert all(p.provenance["created_by"] == "brandfetch" for p in outcome.prepared)
    # The engine's AssetSource has no vendor variant: vendor cells ingest as `website`.
    assert all(p.source_ref["kind"] == "website" for p in outcome.prepared)
    assert all(
        p.ingest_kwargs("/tmp/store")["source"]["kind"] == "website"
        for p in outcome.prepared
    )


def test_dispatch_both_sources_compete_for_the_same_cell(monkeypatch):
    """The vendor's plain `logo` and the ladder's FULL lockup both propose for
    `light_lockup`; the more complete one takes it, and a note says so."""
    from lumen_agent.tools import logo_fetch

    monkeypatch.setattr(
        logo_fetch, "_vendor_rung", lambda site, company: (_vendor_cells("light_lockup"), [])
    )
    ladder = _resolution({
        "light": _slot(_svg(), lockup="full_lockup", variant="light",
                       url="https://acme.com/full.svg"),
        "dark": _slot(_svg("#fff"), lockup="full_lockup", variant="dark"),
        "mark": _slot(_svg(), lockup="symbol", variant="unknown"),
    })
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.cells["light_lockup"] == "ladder"
    assert outcome.cells["dark_lockup"] == "ladder"
    assert outcome.cells["light_mark"] == "ladder"
    light = next(p for p in outcome.prepared if p.cell == "light_lockup")
    assert light.evidence["arbitration"]["beat"] == ["brandfetch:light_lockup.svg"]
    assert any("light_lockup" in note and "brandfetch" in note for note in outcome.notes)


def test_dispatch_vendor_disabled_or_failing_degrades_to_ladder(monkeypatch):
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing, VendorLookupFailed

    ladder = _resolution({"light": _slot(_svg(), lockup="full_lockup", variant="light")})
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)

    def no_key(site, company):
        raise VendorCredentialsMissing()

    monkeypatch.setattr(logo_fetch, "_vendor_rung", no_key)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.cells == {"light_lockup": "ladder"}
    assert any("vendor rung disabled" in n for n in outcome.notes)

    def quota(site, company):
        raise VendorLookupFailed("quota", "429")

    monkeypatch.setattr(logo_fetch, "_vendor_rung", quota)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.cells == {"light_lockup": "ladder"}
    assert any("quota" in n for n in outcome.notes)


def test_dispatch_nothing_anywhere_is_fail_closed_needs_review(monkeypatch):
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.logo_ladder import LadderResolution

    empty = LadderResolution(status="needs_review",
                             identity={"passed": False, "reason": "no overlap"})
    empty.slots = {"light": None, "dark": None, "mark": None, "wordmark": None}
    monkeypatch.setattr(logo_fetch, "_vendor_rung", lambda site, company: ({}, ["no record"]))
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: empty)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.needs_review and outcome.prepared == []


def test_dispatch_cache_hit_skips_both_rungs_and_force_refresh_overwrites(monkeypatch):
    from lumen_agent.tools import logo_fetch

    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells(*logo_fetch.CELL_NAMES), []),
    )
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: _resolution({}))
    first = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert first.cache_hit is False and "https://acme.com/" in cache.stored

    def explode(site, company):
        raise AssertionError("vendor must not be called on a cache hit")

    monkeypatch.setattr(logo_fetch, "_vendor_rung", explode)
    second = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert second.cache_hit is True and set(second.cells) == set(logo_fetch.CELL_NAMES)

    # force_refresh bypasses the read and overwrites the entry
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup"), []),
    )
    ladder = _resolution({})
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)
    third = logo_fetch.fetch_logo_family("acme.com", cache=cache, force_refresh=True)
    assert third.cache_hit is False and list(third.cells) == ["light_lockup"]


def test_dispatch_hesitant_ladder_only_family_is_needs_review_and_not_cached(monkeypatch):
    from lumen_agent.tools import logo_fetch

    cache = _RecordingCache()
    monkeypatch.setattr(logo_fetch, "_vendor_rung", lambda site, company: ({}, []))
    hesitant = _resolution({"light": _slot(_svg(), lockup="full_lockup", variant="light")})
    hesitant.status = "needs_review"   # e.g. alternate lockups: a human call, not a scoring call
    hesitant.identity = {"passed": True}
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: hesitant)
    outcome = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert outcome.prepared and outcome.cells == {"light_lockup": "ladder"}
    assert outcome.status == "needs_review"
    assert cache.stored == {}


def test_dispatch_a_vendor_cell_makes_a_mixed_family_ok(monkeypatch):
    from lumen_agent.tools import logo_fetch

    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung", lambda site, company: (_vendor_cells("light_lockup"), [])
    )
    hesitant = _resolution({"dark": _slot(_svg("#fff"), lockup="full_lockup", variant="dark")})
    hesitant.status = "needs_review"
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: hesitant)
    outcome = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert outcome.status == "ok"
    assert outcome.cells == {"light_lockup": "brandfetch", "dark_lockup": "ladder"}
    assert "https://acme.com/" in cache.stored


def test_dispatch_keeps_vendor_cells_when_the_ladder_is_blocked(monkeypatch):
    """A blocked/unreachable site must not throw away what the vendor already answered."""
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.capture.net import CaptureError

    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup", "light_mark"), []),
    )

    def blocked(site, company):
        raise CaptureError("LUMI0501", "blocked")

    monkeypatch.setattr(logo_fetch, "_ladder_rung", blocked)
    outcome = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert outcome.status == "ok"
    assert outcome.cells == {"light_lockup": "brandfetch", "light_mark": "brandfetch"}
    assert any("ladder unavailable (LUMI0501)" in n for n in outcome.notes)
    assert "https://acme.com/" in cache.stored


def test_dispatch_reraises_a_blocked_ladder_when_the_vendor_had_nothing(monkeypatch):
    """With no vendor cell to keep, the ladder failure is still the caller's answer."""
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.capture.net import CaptureError

    cache = _RecordingCache()
    monkeypatch.setattr(logo_fetch, "_vendor_rung", lambda site, company: ({}, ["no record"]))

    def blocked(site, company):
        raise CaptureError("LUMI0501", "blocked")

    monkeypatch.setattr(logo_fetch, "_ladder_rung", blocked)
    with pytest.raises(CaptureError):
        logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert cache.stored == {}


def test_dispatch_freshcontext_replay(monkeypatch):
    """The case that forced the rule (freshcontext.ai, measured 2026-09-02).

    Brandfetch holds one asset: a 310x176 PNG of the short form, labelled
    `theme=light` -> our `dark_lockup`, but its ink is dark brown, so it is for
    LIGHT surfaces. The site publishes the real on-dark SVG and the complete
    1162x571 wordmark. Vendor-first with per-cell backfill kept the mislabelled
    asset and dropped both; both sources proposing gets all three cells right.
    """
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.logo_family import SOURCE_BRANDFETCH, FamilyCell

    vendor = FamilyCell(
        cell="dark_lockup", body=_flat_png(310, 176, DARK_INK), content_type="image/png",
        source=SOURCE_BRANDFETCH,
        origin_url="https://cdn.brandfetch.io/freshcontext.ai/logo.png",
        evidence={"vendor_theme": "light", "vendor_type": "logo",
                  "width": 310, "height": 176},
    )
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung", lambda site, company: ({"dark_lockup": vendor}, [])
    )
    ladder = _resolution({
        "light": _slot(_flat_png(310, 176, DARK_INK), lockup="wordmark", variant="unknown",
                       url="https://freshcontext.ai/images/logo-mark.png",
                       content_type="image/png", width=310, height=176),
        "dark": _slot(_svg("#ffffff"), lockup="wordmark", variant="dark",
                      url="https://freshcontext.ai/images/wordmark-ondark.svg"),
        "mark": _slot(_flat_png(180, 180, ORANGE_INK), lockup="symbol", variant="unknown",
                      url="https://freshcontext.ai/images/apple-icon.png",
                      content_type="image/png", width=180, height=180),
        "wordmark": _slot(_flat_png(1162, 571, DARK_INK), lockup="wordmark",
                          variant="unknown", url="https://freshcontext.ai/images/wordmark.png",
                          content_type="image/png", width=1162, height=571),
    })
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)

    outcome = logo_fetch.fetch_logo_family("freshcontext.ai")

    assert outcome.cells == {
        "light_lockup": "ladder", "dark_lockup": "ladder", "light_mark": "ladder"
    }
    assert "dark_mark" not in outcome.cells
    chosen = {p.cell: p.source_ref["url"] for p in outcome.prepared}
    assert chosen["light_lockup"].endswith("wordmark.png")       # the COMPLETE wordmark
    assert chosen["dark_lockup"].endswith("wordmark-ondark.svg")  # the real on-dark asset
    assert chosen["light_mark"].endswith("apple-icon.png")
    assert any("dark_lockup" in note and "brandfetch" in note for note in outcome.notes)


# --------------------------------------------------------------------------- #
# end to end: one family, two provenances
# --------------------------------------------------------------------------- #

#: A trimmed Brand API response (the `logos[]` shape of `apps/api/tests/test_logo_vendor.py`),
#: carrying ONLY vendor theme=`dark` art — dark-colored, so it is FOR light backgrounds — as one
#: `logo` and one `symbol`. Inverted and folded, that is exactly our `light_lockup` + `light_mark`,
#: leaving the two dark cells for the ladder. Asset srcs sit on the vendor's own CDN because the
#: driver refuses to fetch anything off the `brandfetch.io` allowlist.
E2E_BRAND_PAYLOAD = {
    "name": "Acme",
    "domain": "acme.com",
    "logos": [
        {
            "theme": "dark",
            "type": "logo",
            "tags": [],
            "formats": [
                {"src": "https://cdn.brandfetch.io/acme/lockup-dark.svg", "format": "svg",
                 "width": 400, "height": 80, "size": 4000, "background": "transparent"},
            ],
        },
        {
            "theme": "dark",
            "type": "symbol",
            "tags": [],
            "formats": [
                {"src": "https://cdn.brandfetch.io/acme/symbol-dark.svg", "format": "svg",
                 "width": 64, "height": 64, "size": 900, "background": "transparent"},
            ],
        },
    ],
}

#: Four distinct bodies, because an asset id is the sha256 of its bytes: identical art would
#: collapse two cells onto one asset id and hide a mis-keyed registration.
E2E_VENDOR_ASSETS = {
    "/acme/lockup-dark.svg": _svg("#101820"),
    "/acme/symbol-dark.svg": _svg("#101820", 64, 64),
}


def _e2e_vendor_handler(request):
    """Serve the Brand API lookup and the two CDN assets; 404 anything else."""
    import httpx

    if request.url.path == "/v2/brands/domain/acme.com":
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=E2E_BRAND_PAYLOAD)
    body = E2E_VENDOR_ASSETS.get(request.url.path)
    if body is not None:
        return httpx.Response(200, content=body, headers={"content-type": "image/svg+xml"})
    return httpx.Response(404)


def test_web_fetch_logo_end_to_end_mixed_vendor_and_ladder_family(tmp_path, monkeypatch):
    """The whole tool, both rungs live, nothing faked above the transport.

    The vendor rung runs the REAL `fetch_vendor_family` against an httpx MockTransport, so the
    lookup, the allowlist, the download, the theme inversion and the cell mapping all execute;
    the ladder rung is faked at its own driver seam, as every other test in this file does. Two
    cells therefore come from Brandfetch and two from the ladder, and the point of the test is
    that each ingested record carries ITS OWN source: a family is allowed to be mixed, and a
    reader must never have to guess which half of it the vendor served.
    """
    import httpx
    from lumen_ingestion.logo_vendor import fetch_vendor_family

    ladder = _resolution({
        "dark": _slot(_svg("#ffffff"), lockup="full_lockup", variant="dark",
                      url="https://acme.com/logo-white.svg"),
        "mark": _slot(_svg("#ffffff", 64, 64), lockup="symbol", variant="dark",
                      url="https://acme.com/mark-white.svg"),
    })
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)

    tools = _web_tools(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(_e2e_vendor_handler)) as client:
        monkeypatch.setattr(
            logo_fetch,
            "_vendor_rung",
            lambda site, company: fetch_vendor_family(
                site, api_key="test-key", base_url="https://vendor.test", client=client
            ),
        )
        result = json.loads(tools.fetch_logo("acme.com", "Acme"))

    assert result["status"] == "ok"
    assert result["cache_hit"] is False
    assert len(result["logos"]) == 4, result
    assert {entry["cell"]: entry["source"] for entry in result["logos"]} == {
        "light_lockup": "brandfetch",
        "light_mark": "brandfetch",
        "dark_lockup": "ladder",
        "dark_mark": "ladder",
    }

    # Four distinct assets, and every registered record says who served IT.
    expected_created_by = {
        "light_lockup": "brandfetch",
        "light_mark": "brandfetch",
        "dark_lockup": "logo_ladder",
        "dark_mark": "logo_ladder",
    }
    registry = tools.web_doc["assets"]
    assert len({entry["asset_id"] for entry in result["logos"]}) == 4
    for entry in result["logos"]:
        record = registry[entry["asset_id"]]
        assert record["provenance"]["created_by"] == expected_created_by[entry["cell"]], entry
        # The engine's AssetSource has no vendor variant: a vendor file is a URL capture too.
        assert record["source"]["kind"] == "website"
    assert registry[
        next(e["asset_id"] for e in result["logos"] if e["cell"] == "light_lockup")
    ]["source"]["url"].startswith("https://cdn.brandfetch.io/")
    assert registry[
        next(e["asset_id"] for e in result["logos"] if e["cell"] == "dark_lockup")
    ]["source"]["url"] == "https://acme.com/logo-white.svg"
