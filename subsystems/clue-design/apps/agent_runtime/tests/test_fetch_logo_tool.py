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

    slots = {p.slot for p in outcome.prepared}
    assert {"light", "dark"} <= slots
    assert not outcome.needs_review

    light = next(p for p in outcome.prepared if p.slot == "light")
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
    assert result["logos"], "at least one slot must be registered"
    slots = {entry["slot"] for entry in result["logos"]}
    assert "light" in slots

    # Registered into the WebDoc's own asset table...
    for entry in result["logos"]:
        assert entry["asset_id"] in tools.web_doc["assets"]
    # ...through the checked op path, and the WEB key is `record`.
    upserts = [op for op in tools.operations_ledger if op.get("kind") == "upsert_asset"]
    assert upserts, "the registration must be in the replayable ledger"
    assert all("record" in op for op in upserts)
    assert all("asset" not in op for op in upserts)

    # Evidence travels with each slot so the agent can explain the choice.
    light = next(e for e in result["logos"] if e["slot"] == "light")
    assert light["rung"] in ("HEADER", "NAV_VISIBLE", "INLINE_SVG", "PAGE_LOGO_NAMED")
    assert light["provenance"] in ("genuine", "materialized-adaptive")
    assert result["identity"]["passed"] is True


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
