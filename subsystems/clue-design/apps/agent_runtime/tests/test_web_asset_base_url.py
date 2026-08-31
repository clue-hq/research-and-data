"""The asset origin the agent's own preview render resolves images against.

Regression cover for the root cause of "generated web pages never contain
imagery" (2026-08-20). `LumenWebTools` read its asset base URL with
``getattr(config, "asset_base_url", None) or "http://127.0.0.1:8000/asset-store"``
while `AgentRuntimeConfig` had no such field — so the hardcoded value ALWAYS won,
and nothing has listened on port 8000 since the design API moved to 8010. The
agent placed images, saw them 404 in its own screenshots, and stripped them,
reporting honestly that the assets "did not render in the constrained preview".

These tests pin the three things that must stay true: the value is CONFIGURED,
it reaches the tools, and a dead origin is never silent.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from py_lumen_config.config import Settings

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import web_substrate as ws
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]

_DIGEST = "a" * 64
_OTHER_DIGEST = "b" * 64


def _tools(tmp_path: Path, *, assets: dict | None = None, **cfg) -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        **cfg,
    )
    seed = {
        "schema_version": 1,
        "id": "doc_web_assets",
        "title": "Test site",
        "theme": {},
        "custom_css": "",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {
                        "id": "root",
                        "kind": "container",
                        "classes": "",
                        "new_tab": False,
                    }
                },
            }
        ],
        "assets": assets or {},
    }
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


def _asset_record(digest: str) -> dict:
    """A complete engine `AssetRecord` (the helper rejects a partial one)."""
    return {
        "id": "asset_probe",
        "kind": "raster_image",
        "label": "probe.png",
        "status": "ready",
        "source": {"kind": "brand_guide", "label": "probe.png"},
        "media": {
            "mime_type": "image/png",
            "filename": "probe.png",
            "byte_length": 128,
            "digest": {"algorithm": "sha256", "value": digest},
        },
        "raster": {
            "pixel_width": 1600,
            "pixel_height": 900,
            "dpi_x": None,
            "dpi_y": None,
            "has_alpha": None,
            "color_profile": None,
            "aspect_ratio": None,
        },
        "provenance": {
            "created_by": "test",
            "created_at": "2026-08-20T00:00:00+00:00",
            "source_label": "test",
            "confidence": 1.0,
            "notes": [],
        },
        "tags": [],
    }


def _trace_events(tools: LumenWebTools) -> list[dict]:
    path = tools.trace_dir / "trace.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- the setting ------------------------------------------------------------


def test_asset_base_url_is_derived_from_the_api_origin():
    settings = Settings(_env_file=None, lumen_api_origin="http://design.test:9001")
    assert settings.asset_base_url == "http://design.test:9001/asset-store"


def test_a_trailing_slash_on_the_origin_cannot_double_the_path():
    settings = Settings(_env_file=None, lumen_api_origin="http://design.test:9001/")
    assert settings.asset_base_url == "http://design.test:9001/asset-store"


def test_a_blank_origin_falls_back_to_the_canonical_dev_stack():
    """`VAR=` in a .env means unset — and unset must still name a LIVE port."""
    settings = Settings(_env_file=None, lumen_api_origin="   ")
    assert settings.lumen_api_origin == "http://127.0.0.1:8010"
    assert settings.asset_base_url == "http://127.0.0.1:8010/asset-store"


def test_the_default_origin_is_not_the_dead_port():
    """The whole defect in one assertion: 8000 has no listener."""
    settings = Settings(_env_file=None)
    assert ":8000" not in settings.asset_base_url


# --- the config field -------------------------------------------------------


def test_the_runtime_config_has_a_real_asset_base_url_field():
    """RED-PROOF: before this fix `AgentRuntimeConfig` had no such field at all,
    which is why the substrate's `getattr(config, "asset_base_url", None)`
    always returned None."""
    config = AgentRuntimeConfig.from_env(REPO_ROOT)
    assert "asset_base_url" in {f for f in config.__dataclass_fields__}
    assert config.asset_base_url
    assert config.asset_base_url.endswith("/asset-store")


# --- the tools read it ------------------------------------------------------


def test_tools_use_the_configured_asset_base_url(tmp_path: Path):
    """RED-PROOF: on the pre-fix code this is `http://127.0.0.1:8000/asset-store`
    no matter what the config says."""
    tools = _tools(tmp_path, asset_base_url="http://design.test:9001/asset-store")
    assert tools.asset_base_url == "http://design.test:9001/asset-store"


def test_tools_fall_back_only_when_the_config_names_nothing(tmp_path: Path):
    tools = _tools(tmp_path, asset_base_url=None)
    assert tools.asset_base_url == ws._FALLBACK_ASSET_BASE_URL


def test_the_last_resort_fallback_points_at_a_live_origin():
    assert ws._FALLBACK_ASSET_BASE_URL == "http://127.0.0.1:8010/asset-store"


def test_the_dead_port_appears_nowhere_in_the_web_substrate():
    """A guard rather than a comment: re-introducing `127.0.0.1:8000` anywhere in
    this module recreates a full day of misdiagnosis."""
    source = Path(ws.__file__).read_text()
    assert "127.0.0.1:8000" not in source


# --- the render contract ----------------------------------------------------


def test_a_placed_asset_renders_under_the_configured_base(tmp_path: Path):
    """End of the chain: the engine turns `<img data-asset=…>` into a src rooted
    at whatever base the tools hand it."""
    base = "http://design.test:9001/asset-store"
    tools = _tools(
        tmp_path,
        assets={"asset_probe": _asset_record(_DIGEST)},
        asset_base_url=base,
    )
    tools.web_doc["pages"][0]["nodes"]["root"]["children"] = ["img_hero"]
    tools.web_doc["pages"][0]["nodes"]["img_hero"] = {
        "id": "img_hero",
        "kind": "image",
        "classes": "",
        "new_tab": False,
        "asset_id": "asset_probe",
        "alt": "A hero",
    }
    response = tools.core.web_render(
        tools.web_doc,
        tools.page_id,
        mode="editor",
        asset_base_url=tools.asset_base_url,
        tailwind_runtime_src=None,
        brand_kit=None,
        font_face_css=None,
    )
    html = response.get("html") or ""
    assert f"{base}/{_DIGEST}" in html, html[:2000]


def test_the_preview_render_is_handed_the_configured_base(tmp_path: Path):
    """The call boundary inside the agent loop. `web_render` raising CoreError is
    the cheapest capture point — the tool then returns its error envelope, so
    nothing reaches Playwright."""
    from lumen_api.core import CoreError

    captured: dict = {}
    tools = _tools(tmp_path, asset_base_url="http://design.test:9001/asset-store")
    real_core = tools.core

    class _RecordingCore:
        def __getattr__(self, name):
            return getattr(real_core, name)

        def web_render(self, *args, **kwargs):
            captured.update(kwargs)
            raise CoreError(
                "test.stop", "stop here — the kwargs are what this test judges"
            )

    tools.core = _RecordingCore()

    result = json.loads(tools.render_web_preview())

    assert result["status"] == "error"
    assert captured["asset_base_url"] == "http://design.test:9001/asset-store"


# --- the preflight ----------------------------------------------------------


def test_an_unreachable_asset_origin_is_recorded_loudly(tmp_path: Path):
    """A dead asset origin must never be silent again. It also must not fail the
    turn — a degraded page beats an invisible outage."""
    tools = _tools(
        tmp_path,
        assets={"asset_probe": _asset_record(_DIGEST)},
        # Reserved-for-documentation address: nothing can listen here.
        asset_base_url="http://127.0.0.1:1/asset-store",
    )

    tools._preflight_asset_base_url()

    events = [e for e in _trace_events(tools) if e["event"] == "asset_base_url_unreachable"]
    assert len(events) == 1, _trace_events(tools)
    payload = events[0]["payload"]
    assert payload["reachable"] is False
    assert payload["asset_base_url"] == "http://127.0.0.1:1/asset-store"
    assert payload["probe_url"].endswith(_DIGEST)
    assert "broken images" in events[0]["output_summary"]


def test_a_live_asset_origin_is_recorded_as_reachable(tmp_path: Path, monkeypatch):
    class _Response:
        status_code = 200

    monkeypatch.setattr(ws.httpx, "get", lambda *a, **k: _Response())
    tools = _tools(
        tmp_path,
        assets={"asset_probe": _asset_record(_DIGEST)},
        asset_base_url="http://design.test:9001/asset-store",
    )

    tools._preflight_asset_base_url()

    events = [e for e in _trace_events(tools) if e["event"] == "asset_base_url_preflight"]
    assert len(events) == 1
    assert events[0]["payload"]["reachable"] is True
    assert events[0]["payload"]["status_code"] == 200


def test_the_preflight_runs_at_most_once_per_turn(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    class _Response:
        status_code = 200

    def _get(url, **kwargs):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(ws.httpx, "get", _get)
    tools = _tools(
        tmp_path,
        assets={"asset_probe": _asset_record(_DIGEST)},
        asset_base_url="http://design.test:9001/asset-store",
    )

    tools._preflight_asset_base_url()
    tools._preflight_asset_base_url()
    tools._preflight_asset_base_url()

    assert len(calls) == 1


def test_the_preflight_never_raises(tmp_path: Path, monkeypatch):
    def _explode(*args, **kwargs):
        raise RuntimeError("transport is on fire")

    monkeypatch.setattr(ws.httpx, "get", _explode)
    tools = _tools(
        tmp_path,
        assets={"asset_probe": _asset_record(_DIGEST)},
        asset_base_url="http://design.test:9001/asset-store",
    )

    tools._preflight_asset_base_url()

    events = [e for e in _trace_events(tools) if e["event"] == "asset_base_url_unreachable"]
    assert len(events) == 1
    assert "RuntimeError" in events[0]["payload"]["reason"]


def test_a_turn_with_nothing_to_probe_says_so_rather_than_guessing(
    tmp_path: Path, monkeypatch
):
    def _explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("no digest exists; nothing should have been fetched")

    monkeypatch.setattr(ws.httpx, "get", _explode)
    tools = _tools(tmp_path, asset_base_url="http://design.test:9001/asset-store")

    tools._preflight_asset_base_url()

    events = [e for e in _trace_events(tools) if e["event"] == "asset_base_url_preflight"]
    assert len(events) == 1
    assert events[0]["payload"]["reachable"] is None


def test_the_probe_prefers_a_digest_the_document_actually_carries(tmp_path: Path):
    tools = _tools(
        tmp_path,
        assets={"asset_probe": _asset_record(_DIGEST)},
        asset_base_url="http://design.test:9001/asset-store",
        brand_kit_assets={"kit_img": {"record": _asset_record(_OTHER_DIGEST)}},
    )
    assert tools._probe_digests()[0] == _DIGEST


def test_the_probe_falls_back_to_the_kit_manifest(tmp_path: Path):
    tools = _tools(
        tmp_path,
        asset_base_url="http://design.test:9001/asset-store",
        brand_kit_assets={"kit_img": {"record": _asset_record(_OTHER_DIGEST)}},
    )
    assert tools._probe_digests() == [_OTHER_DIGEST]


@pytest.mark.parametrize("junk", ["", "not-a-digest", "A" * 64, 17, None])
def test_the_probe_refuses_a_value_that_is_not_a_sha256(tmp_path: Path, junk):
    record = {"id": "x", "media": {"digest": {"algorithm": "sha256", "value": junk}}}
    tools = _tools(
        tmp_path,
        assets={"x": record},
        asset_base_url="http://design.test:9001/asset-store",
    )
    assert tools._probe_digests() == []
