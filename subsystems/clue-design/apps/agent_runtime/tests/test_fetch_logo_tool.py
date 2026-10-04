"""`fetch_logo` on both design lanes.

The network is faked at the ladder's own driver seam, so these exercise what
the tool does with a resolution — ingest, register with the LANE-CORRECT
operation key, and refuse to place anything it cannot attribute.
"""

from __future__ import annotations

import base64
import copy
import hashlib
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
    monkeypatch.setattr(logo_fetch, "_logo_dev_rung", disabled, raising=False)


def test_brandfetch_original_is_attributed_and_usable_when_site_is_blocked(monkeypatch):
    from lumen_ingestion.capture.net import CaptureError
    from lumen_ingestion.logo_family import FamilyCell

    cell = FamilyCell(
        cell="light_lockup", body=_svg(), content_type="image/svg+xml",
        source="brandfetch", origin_url="https://asset.brandfetch.io/acme/logo.svg",
        evidence={"vendor_identity": {"domain": "acme.com", "name": "Acme", "passed": True}},
    )
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung", lambda site, company: ({"light_lockup": cell}, [], [])
    )
    def blocked(site, company):
        raise CaptureError("blocked", "unavailable")
    monkeypatch.setattr(logo_fetch, "_ladder_rung", blocked)
    outcome = logo_fetch.fetch_logo_family("acme.com", company_name="Acme")
    assert outcome.status == "ok"
    assert outcome.prepared[0].provenance["created_by"] == "brandfetch"
    assert outcome.prepared[0].body == cell.body
    assert outcome.identity["passed"] is True


def test_retired_provider_is_never_contacted(monkeypatch):
    def retired(site, company):
        pytest.fail("Retired provider must not receive requests or credentials")
    monkeypatch.setattr(logo_fetch, "_logo_dev_rung", retired, raising=False)
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup"), [], []),
    )
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: _resolution({}))
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.cells == {"light_lockup": "brandfetch"}
    assert outcome.prepared[0].provenance["created_by"] == "brandfetch"


def test_retired_provider_cache_is_refetched(monkeypatch):
    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup"), [], []),
    )
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: _resolution({}))
    previous = logo_fetch.fetch_logo_family("acme.com", company_name="Acme", cache=cache)
    previous.prepared[0].source = "logo_dev"
    result = logo_fetch.fetch_logo_family("acme.com", company_name="Acme", cache=cache)
    assert not result.cache_hit
    assert result.prepared[0].source == "brandfetch"


def test_cached_host_cannot_bypass_changed_company_identity(monkeypatch):
    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup"), [], []),
    )
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: _resolution({}))
    logo_fetch.fetch_logo_family("acme.com", company_name="Acme", cache=cache)
    seen = []
    def fresh(site, company):
        seen.append(company)
        return {}, [], []
    monkeypatch.setattr(logo_fetch, "_vendor_rung", fresh)
    result = logo_fetch.fetch_logo_family("acme.com", company_name="Acme Cloud", cache=cache)
    assert not result.cache_hit
    assert seen == ["Acme Cloud"]


def test_verified_vendor_does_not_certify_unrelated_ladder_logo(monkeypatch):
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup"), [], []),
    )
    ladder = _resolution({"dark": _slot(_svg("#fff"), lockup="full_lockup", variant="dark")})
    ladder.identity = {"passed": False, "reason": "partner logo"}
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)
    result = logo_fetch.fetch_logo_family("acme.com")
    assert result.cells == {"light_lockup": "brandfetch"}
    assert all(p.source == "brandfetch" for p in result.prepared + result.alternatives)


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
    tools = LumenDesignTools(runtime_config(tmp_path), "Make an ABM poster")
    # Editor Quality Plan 2 (item C): fetch_logo refuses on a pageless scene
    # BEFORE it calls the vendor, so these lane tests need the page the real
    # author would have compiled first. FakeCoreClient plants `page_test`.
    tools.compile_dsl_block("page page_test size(1080,1080,px)")
    return tools


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


@pytest.mark.skipif(
    not (REPO_ROOT / "target/release/lumen-api-helper").exists(),
    reason="release helper not built",
)
def test_fetched_scene_logo_is_viewable_valid_direction_source_and_independent_layer(
    tmp_path, monkeypatch
):
    """Exercise fetched-ID custody without adding it to the opening reference catalog."""
    from lumen_agent.tools import substrate
    from lumen_agent.tools.view import make_view_tool
    from lumen_agent.workspace import scaffold_workspace
    from lumen_api import core as core_module
    from PIL import Image
    from test_scene_skill_family import direction

    raw = _flat_png(240, 48, DARK_INK)
    _fake_site(
        monkeypatch,
        '<html><head><title>Acme Systems</title></head><body><header>'
        '<img src="/brand/acme-logo.png" alt="Acme Systems" width="240" height="48">'
        '</header></body></html>',
        {"https://acme.example/brand/acme-logo.png": (raw, "image/png")},
        "acme.example",
    )
    monkeypatch.setattr(
        core_module.settings, "lumen_core_helper",
        str(REPO_ROOT / "target/release/lumen-api-helper"),
    )
    core = core_module.CoreClient(repo_root=REPO_ROOT)
    monkeypatch.setattr(substrate, "CoreClient", lambda **_: core)
    config = replace(
        runtime_config(tmp_path), repo_root=REPO_ROOT, scene_skill_bundle="candidate",
        asset_store_root=tmp_path / "assets",
    )
    tools = LumenDesignTools(config, "Address an advertiser creative to Acme Systems")
    workspace = scaffold_workspace(tools, tools.prompt)
    opening_catalog = (workspace / "source_assets.json").read_bytes()
    payload = direction()
    path = workspace / "creative-direction.json"
    assert json.loads(tools.compile_dsl_block(
        'page square size(1080,1080,px)\n'
    ))["compile"]["status"] == "ok"
    assert tools.scene["nodes"] == {}

    result = json.loads(tools.fetch_logo("acme.example", "Acme Systems"))
    logo = next(row for row in result["logos"] if row["cell"] == "light_lockup")
    asset_id = logo["asset_id"]
    assert logo["source"] == "ladder"
    assert asset_id in tools.scene["assets"]
    stored_digest = tools.scene["assets"][asset_id]["media"]["digest"]["value"]
    assert stored_digest == hashlib.sha256(raw).hexdigest()
    assert not config.reference_assets and not config.asset_library and not config.brand_kit_assets
    assert (workspace / "source_assets.json").read_bytes() == opening_catalog
    blocks = make_view_tool(tools).invoke({"target": f"asset:{asset_id}"})
    image = next(block for block in blocks if block["type"] == "image")
    # Engine ingestion also derives a resized preview; original custody above
    # and the actual view pixels below must both remain tied to this target.
    with Image.open(io.BytesIO(base64.b64decode(image["data"]))) as preview:
        assert preview.width / preview.height == 5
        rgba = preview.convert("RGBA")
        assert rgba.getpixel((preview.width // 2, preview.height // 2)) == (*DARK_INK, 255)
        assert rgba.getpixel((0, 0))[3] == 0

    payload["source_roles"] = [{"asset_id": asset_id, "role": "logo"}]
    payload["layers"].append({
        "id": "target_logo", "kind": "authentic_image", "purpose": "Identify the addressee",
        "asset_id": asset_id,
        "placement": {"x": 0.1, "y": 0.3, "width": 0.3, "height": 0.08, "fit": "contain"},
    })
    path.write_text(json.dumps(payload))
    validated = json.loads(tools.validate_creative_direction())
    assert validated["status"] == "ok"
    assert validated["source_ids"] == [asset_id]
    assert validated["evidence_verified"] is False

    assert json.loads(tools.compile_dsl_block(
        '  headline text "Make the next step clear" p(80,80) s(800,150) '
        'font_size(48) fill(#123456)\n'
        '  target_logo fr p(80,320) s(300,80)'
    ))["compile"]["status"] == "ok"
    advertiser_before = copy.deepcopy(tools.scene["nodes"]["headline"])

    placed = json.loads(tools.asset(
        action="place", asset_id=asset_id, node_id="target_logo", fit="contain"
    ))
    assert placed["placement"]["status"] == "ok"
    assert tools.scene["nodes"]["headline"] == advertiser_before
    assert any(
        entry["source"] == "fetch_logo" and entry["operation"]["kind"] == "upsert_asset"
        for entry in tools.operations_ledger
    )
    assert tools.scene["nodes"]["target_logo"]["kind"]["asset_id"] == asset_id
    assert tools.scene["nodes"]["target_logo"]["asset_placement"]["fit"] == "contain"


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
        lambda site, company: (_vendor_cells(*logo_fetch.CELL_NAMES), [], []),
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
        logo_fetch, "_vendor_rung", lambda site, company: (_vendor_cells("light_lockup"), [], [])
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
    monkeypatch.setattr(logo_fetch, "_vendor_rung", lambda site, company: ({}, [], ["no record"]))
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: empty)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.needs_review and outcome.prepared == []


def test_dispatch_cache_hit_skips_both_rungs_and_force_refresh_overwrites(monkeypatch):
    from lumen_agent.tools import logo_fetch

    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells(*logo_fetch.CELL_NAMES), [], []),
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
        lambda site, company: (_vendor_cells("light_lockup"), [], []),
    )
    ladder = _resolution({})
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)
    third = logo_fetch.fetch_logo_family("acme.com", cache=cache, force_refresh=True)
    assert third.cache_hit is False and list(third.cells) == ["light_lockup"]


def test_dispatch_hesitant_ladder_only_family_is_needs_review_and_not_cached(monkeypatch):
    from lumen_agent.tools import logo_fetch

    cache = _RecordingCache()
    monkeypatch.setattr(logo_fetch, "_vendor_rung", lambda site, company: ({}, [], []))
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
        logo_fetch, "_vendor_rung", lambda site, company: (_vendor_cells("light_lockup"), [], [])
    )
    hesitant = _resolution({"dark": _slot(_svg("#fff"), lockup="full_lockup", variant="dark")})
    hesitant.status = "needs_review"
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: hesitant)
    outcome = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert outcome.status == "ok"
    assert outcome.cells == {"light_lockup": "brandfetch", "dark_lockup": "ladder"}
    assert "https://acme.com/" in cache.stored
    assert outcome.identity["reason"] == "mixed provider and official-site evidence"
    assert {s["source"] for s in outcome.identity["sources"]} == {"brandfetch", "ladder"}


def test_dispatch_keeps_vendor_cells_when_the_ladder_is_blocked(monkeypatch):
    """A blocked/unreachable site must not throw away what the vendor already answered."""
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.capture.net import CaptureError

    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup", "light_mark"), [], []),
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
    monkeypatch.setattr(logo_fetch, "_vendor_rung", lambda site, company: ({}, [], ["no record"]))

    def blocked(site, company):
        raise CaptureError("LUMI0501", "blocked")

    monkeypatch.setattr(logo_fetch, "_ladder_rung", blocked)
    with pytest.raises(CaptureError):
        logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert cache.stored == {}


@pytest.mark.parametrize(
    ("requested_name", "provider_domain", "provider_name", "provider_code"),
    [
        ("Hyatt Hotels", "hyatt.com", "Hyatt", "identity_mismatch"),
        ("Hyatt", "hyatt.com", "Hyatt Hotels", "identity_unverified"),
        ("Hyatt", "world.hyatt.com", "Hyatt", "identity_mismatch"),
    ],
)
def test_dispatch_retains_identity_refusal_when_official_site_is_rate_limited(
    monkeypatch, requested_name, provider_domain, provider_name, provider_code
):
    """A website failure must not hide why the provider's logo was refused."""
    import httpx
    from lumen_ingestion.capture.net import CaptureError
    from lumen_ingestion.logo_vendor import fetch_vendor_family

    requests = []

    def provider(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={
            "domain": provider_domain,
            "name": provider_name,
            "logos": [{"type": "logo", "theme": "dark", "formats": [{
                "format": "svg", "src": "https://asset.brandfetch.io/original.svg",
            }]}],
        })

    website_error = CaptureError(
        "LUMI0503", "page fetch failed for https://hyatt.com/: HTTP 429"
    )

    def blocked(site, company):
        raise website_error

    cache = _RecordingCache()
    monkeypatch.setattr(logo_fetch, "_ladder_rung", blocked)
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        monkeypatch.setattr(
            logo_fetch, "_vendor_rung",
            lambda site, company: fetch_vendor_family(
                site, company_name=company, api_key="test-secret-key",
                base_url="https://vendor.test", client=client,
            ),
        )
        with pytest.raises(CaptureError) as failure:
            logo_fetch.fetch_logo_family("hyatt.com", company_name=requested_name, cache=cache)

    assert failure.value.code == "LUMI0503"
    assert website_error.message in failure.value.message
    assert provider_code in failure.value.message
    assert "company/product" in failure.value.message
    assert "verified official source" in failure.value.message
    assert "test-secret-key" not in failure.value.message
    assert requests == ["/v2/brands/domain/hyatt.com"]  # rejected before asset download
    assert cache.stored == {}


def test_dispatch_failure_diagnostic_never_reflects_vendor_network_details(monkeypatch):
    from lumen_ingestion.capture.net import CaptureError
    from lumen_ingestion.logo_vendor import VendorLookupFailed

    def failed(site, company):
        raise VendorLookupFailed(
            "http", "request failed https://operator:private-password@vendor.test/"
            "?api_key=private-key Authorization: Bearer private-token"
        )

    def blocked(site, company):
        raise CaptureError("LUMI0503", "page fetch failed: HTTP 429")

    monkeypatch.setattr(logo_fetch, "_vendor_rung", failed)
    monkeypatch.setattr(logo_fetch, "_ladder_rung", blocked)
    with pytest.raises(CaptureError) as failure:
        logo_fetch.fetch_logo_family("acme.com")

    assert "vendor" in failure.value.message
    assert "http" in failure.value.message
    assert "HTTP 429" in failure.value.message
    assert "private-" not in failure.value.message
    assert "vendor.test" not in failure.value.message


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
        logo_fetch, "_vendor_rung", lambda site, company: ({"dark_lockup": vendor}, [], [])
    )
    ladder = _resolution({
        # The site's own short form is a DIFFERENT file from the vendor's copy of it
        # (different bytes, hence a different asset id), as it is live.
        "light": _slot(_flat_png(320, 176, DARK_INK), lockup="wordmark", variant="unknown",
                       url="https://freshcontext.ai/images/logo-mark.png",
                       content_type="image/png", width=320, height=176),
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

    # Both beaten assets are real: the vendor's short form (which the agent may still
    # want where a lockup does not fit) and the site's own header file.
    alternatives = {p.source_ref["url"]: p for p in outcome.alternatives}
    vendor_short = alternatives["https://cdn.brandfetch.io/freshcontext.ai/logo.png"]
    assert vendor_short.cell == "dark_lockup"
    assert vendor_short.evidence["competed_for"] == "dark_lockup"
    assert "ink measured" in vendor_short.evidence["reason"]
    assert vendor_short.label.endswith("logo (alternative: dark_lockup)")
    header = alternatives["https://freshcontext.ai/images/logo-mark.png"]
    assert header.cell == "light_lockup"
    assert header.evidence["competed_for"] == "light_lockup"
    assert header.evidence["reason"].startswith("lost on completeness, format or size")
    # Every alternative says what its ink MEASURED, never only what a label claimed.
    assert all(p.evidence.get("measured_verdict") for p in outcome.alternatives)


# --------------------------------------------------------------------------- #
# the alternatives beside the 2x2
# --------------------------------------------------------------------------- #


def _vendor_with_extras():
    """A vendor answer holding one cell plus two extras: an icon, and a second
    `logo` whose bytes are the cell's own (the duplicate a dedup must drop)."""
    from lumen_ingestion.logo_family import SOURCE_BRANDFETCH, FamilyCell

    lockup = _svg("#101820")
    cells = {
        "light_lockup": FamilyCell(
            cell="light_lockup", body=lockup, content_type="image/svg+xml",
            source=SOURCE_BRANDFETCH, origin_url="https://cdn.brandfetch.io/a/lockup.svg",
            evidence={"vendor_type": "logo"},
        )
    }
    extras = [
        FamilyCell(
            cell="", body=_png(96), content_type="image/png", source=SOURCE_BRANDFETCH,
            origin_url="https://cdn.brandfetch.io/a/icon.png",
            evidence={"vendor_type": "icon", "competed_for": None,
                      "reason": "vendor type 'icon' is not a family cell"},
        ),
        FamilyCell(
            cell="light_lockup", body=lockup, content_type="image/svg+xml",
            source=SOURCE_BRANDFETCH, origin_url="https://cdn.brandfetch.io/a/again.svg",
            evidence={"vendor_type": "logo", "competed_for": "light_lockup",
                      "reason": "a vendor asset already filled light_lockup"},
        ),
    ]
    return cells, extras


def _alternatives_fixture(monkeypatch):
    """Vendor cell + vendor extras + one ladder candidate that loses the same cell."""
    from lumen_agent.tools import logo_fetch

    cells, extras = _vendor_with_extras()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung", lambda site, company: (cells, extras, [])
    )
    ladder = _resolution({
        "light": _slot(_svg("#203040"), lockup="wordmark", variant="light",
                       url="https://acme.com/header.svg"),
    })
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)


def test_dispatch_pools_arbiter_losers_and_vendor_extras_into_alternatives(monkeypatch):
    """The cells stay the recommendation; everything else real is offered beside them."""
    from lumen_agent.tools import logo_fetch

    _alternatives_fixture(monkeypatch)
    outcome = logo_fetch.fetch_logo_family("acme.com")

    # The 2x2 is untouched by any of this.
    assert outcome.status == "ok"
    assert outcome.cells == {"light_lockup": "brandfetch"}
    assert [p.cell for p in outcome.prepared] == ["light_lockup"]

    # Losers first, then the vendor's extras; the duplicate of the winner is dropped.
    assert [p.cell for p in outcome.alternatives] == ["light_lockup", "unclassified"]
    loser, icon = outcome.alternatives
    assert loser.source == "ladder"
    assert loser.source_ref["url"] == "https://acme.com/header.svg"
    assert loser.label == "acme.com logo (alternative: light_lockup)"
    assert loser.evidence["competed_for"] == "light_lockup"
    assert loser.evidence["reason"]
    assert icon.source == "brandfetch"
    assert icon.label == "acme.com logo (alternative: icon)"
    assert icon.evidence["competed_for"] is None
    assert icon.evidence["vendor_type"] == "icon"
    winner_id = outcome.prepared[0].asset_id
    assert winner_id not in {p.asset_id for p in outcome.alternatives}


def test_every_alternative_carries_a_measured_ink_verdict(monkeypatch):
    """A vendor theme LABEL is not evidence — this session's freshcontext asset was
    labelled for dark surfaces and held dark ink. So an extra nobody measured is
    measured here, off its own bytes, before the agent ever sees it."""
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.logo_family import SOURCE_BRANDFETCH, FamilyCell

    icon = FamilyCell(
        cell="", body=_svg("#ffffff"), content_type="image/svg+xml",
        source=SOURCE_BRANDFETCH, origin_url="https://cdn.brandfetch.io/a/icon.svg",
        # The vendor filed it as art for LIGHT surfaces; its ink says otherwise.
        evidence={"vendor_type": "icon", "vendor_theme": "light", "theme": "dark",
                  "competed_for": None,
                  "reason": "vendor type 'icon' is not a family cell"},
    )
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung", lambda site, company: ({}, [icon], [])
    )
    ladder = _resolution({
        "light": _slot(_svg(), lockup="full_lockup", variant="light"),
    })
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)

    outcome = logo_fetch.fetch_logo_family("acme.com")

    assert outcome.alternatives[0].evidence["measured_verdict"] == "dark_variant"


def test_web_fetch_logo_registers_the_alternatives_too(tmp_path, monkeypatch):
    _alternatives_fixture(monkeypatch)
    tools = _web_tools(tmp_path)

    result = json.loads(tools.fetch_logo("acme.com", "Acme"))

    assert [entry["cell"] for entry in result["logos"]] == ["light_lockup"]
    assert "failed_alternatives" not in result
    alternatives = result["alternatives"]
    assert [entry["competed_for"] for entry in alternatives] == ["light_lockup", None]
    registry = tools.web_doc["assets"]
    created_by = {"brandfetch": "brandfetch", "ladder": "logo_ladder"}
    for entry in alternatives:
        assert entry["reason"]
        record = registry[entry["asset_id"]]
        assert record["provenance"]["created_by"] == created_by[entry["source"]]
    # Registered like a cell, and never confused with one.
    assert {e["asset_id"] for e in alternatives}.isdisjoint(
        {e["asset_id"] for e in result["logos"]}
    )


def test_scene_fetch_logo_registers_the_alternatives_too(tmp_path, monkeypatch):
    _alternatives_fixture(monkeypatch)
    tools = _scene_tools(tmp_path, monkeypatch)

    result = json.loads(tools.fetch_logo("acme.com", "Acme"))

    assert [entry["cell"] for entry in result["logos"]] == ["light_lockup"]
    assert [entry["competed_for"] for entry in result["alternatives"]] == [
        "light_lockup", None
    ]
    upserts = [
        op for op in tools.core.applied_operations if op.get("kind") == "upsert_asset"
    ]
    assert len(upserts) == 3  # one cell + two alternatives
    assert "use a cell first" in result["next"]


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


def test_every_logo_the_ladder_stands_behind_reaches_the_agent_as_an_alternative(monkeypatch):
    """Founder ask 2026-10-04: the agent sees all of the site's logos, not only the cells.

    A ranked candidate the ladder stands behind (fetched, positive score, first-party) and could
    read as logo artwork rides along as an alternative; a CSS background photo the ladder could
    not read as a logo (`lockup == "unknown"`) does not; the cell's own bytes are not repeated.
    """
    from lumen_ingestion.logo_ladder import LadderCandidate
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing

    def ranked(url, body, *, lockup, score=50.0, first_party=True, content_type="image/svg+xml"):
        candidate = LadderCandidate(url=url, rung="BRAND_PAGE", fmt="svg", dom_role="link rel=icon")
        candidate.body, candidate.content_type = body, content_type
        candidate.lockup, candidate.variant = lockup, "light"
        candidate.score, candidate.first_party = score, first_party
        return candidate

    cell = _slot(_svg(), lockup="full_lockup", variant="light", url="https://acme.com/logo.svg")
    resolution = _resolution({"light": cell})
    resolution.ranked = [
        ranked("https://acme.com/logo.svg", _svg(), lockup="full_lockup"),  # the cell itself
        ranked("https://acme.com/favicon.svg", _svg("#2050c0", 64, 64), lockup="symbol"),
        ranked("https://acme.com/footer-photo.jpg", _png(), lockup="unknown",
               content_type="image/png"),
        ranked("https://partner.com/badge.svg", _svg("#999999", 90, 90), lockup="symbol",
               first_party=False),
        ranked("https://acme.com/junk.svg", _svg("#123456", 70, 70), lockup="symbol", score=-5),
    ]
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: resolution)

    def no_vendor(site, company):
        raise VendorCredentialsMissing("no key in this test")

    monkeypatch.setattr(logo_fetch, "_vendor_rung", no_vendor)
    outcome = logo_fetch.fetch_logo_family("acme.com", company_name="Acme")

    assert [p.cell for p in outcome.prepared] == ["light_lockup"]
    urls = [p.source_ref["url"] for p in outcome.alternatives]
    assert urls == ["https://acme.com/favicon.svg"]
    assert outcome.alternatives[0].label == "Acme logo (site: light symbol, link rel=icon)"
