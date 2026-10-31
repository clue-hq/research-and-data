"""`asset(action="knock_out_background")` through the public tool and the real engine.

No provider, database or service. A knocked-out logo re-enters the SAME node with transparency
preserved; the original asset is never touched; a photo is refused without writing anything.
"""

from __future__ import annotations

import base64
import copy
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from agent_fixtures import runtime_config
from lumen_agent.tools.asset_preview import (
    _RASTER_PAGE_ID,
    _raster_image_node,
    _raster_page,
    blob_path_for_digest,
)
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_api import core as core_module
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "target/release/lumen-api-helper"
pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")

NODE = "svg_raster_image"


def _tile_png() -> bytes:
    """White bars on a black square: the Pallet icon's shape, in miniature."""
    image = Image.new("RGBA", (24, 24), (0, 0, 0, 255))
    for x in range(6, 18):
        for y in (7, 8, 11, 12, 15, 16):
            image.putpixel((x, y), (255, 255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _photo_png() -> bytes:
    image = Image.new("RGBA", (24, 24))
    image.putdata([((i * 37) % 256, (i * 91) % 256, (i * 13) % 256, 255) for i in range(576)])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _context(tmp_path, monkeypatch, png: bytes):
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(ROOT)
    store = tmp_path / "cache"
    record = core.ingest_asset(
        store_root=str(store),
        bytes_base64=base64.b64encode(png).decode(),
        asset_id="source",
        label="Pallet icon on black",
        declared_mime_type="image/png",
        kind="raster_image",
        source={"kind": "website", "url": "https://pallet.example/"},
        provenance={"notes": ["verified original"]},
        license={"name": "owned", "allow_modification": True, "allow_export": True},
    )["asset"]["record"]
    scene = core.new_scene("doc_knockout_test", "Knock-out test")
    scene = core.apply_operations(
        scene,
        [
            {"kind": "add_page", "page": _raster_page()},
            {"kind": "upsert_asset", "asset": record},
            {
                "kind": "insert_node",
                "parent": {"kind": "page", "id": _RASTER_PAGE_ID},
                "index": 0,
                "node": _raster_image_node("source"),
            },
        ],
    )["scene"]
    config = replace(
        runtime_config(tmp_path),
        repo_root=ROOT,
        asset_store_root=store,
        asset_library={"source": {"record": copy.deepcopy(record)}},
    )
    tools = LumenDesignTools(config, "knock out", initial_scene=scene)

    class NoProvider:
        def __getattr__(self, name):
            pytest.fail(f"knock-out accessed the image provider: {name}")

    monkeypatch.setattr("lumen_agent.tools.substrate.image_provider", NoProvider())
    return tools, record, store


def test_the_knocked_out_logo_replaces_the_tile_in_the_same_node(tmp_path, monkeypatch):
    tools, record, store = _context(tmp_path, monkeypatch, _tile_png())
    before = copy.deepcopy(tools.scene["assets"]["source"])
    result = json.loads(tools.asset(action="knock_out_background", node_id=NODE))
    output = result.get("knock_out", {})
    assert output.get("status") == "ok", result
    new_id = output["asset_id"]
    assert new_id != "source"
    node = tools.scene["nodes"][NODE]
    assert node["kind"]["asset_id"] == new_id
    assert node["asset_placement"]["preserve_transparency"] is True
    derived = tools.scene["assets"][new_id]
    data = blob_path_for_digest(store, derived["media"]["digest"]["value"]).read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert("RGBA")
        assert rgba.size == (12, 10)  # trimmed to the bars
        assert rgba.getpixel((0, 0)) == (255, 255, 255, 255)  # a bar
        assert rgba.getpixel((0, 2))[3] == 0  # the black between bars is gone
    assert tools.scene["assets"]["source"] == before  # the original is untouched
    assert derived["license"] == record["license"]
    assert derived["source"]["kind"] == "manual"
    receipt = output["knockout_receipt"]
    assert receipt["background_rgb"] == [0, 0, 0] and receipt["source_asset_id"] == "source"
    assert any(n.startswith("asset_derivation=") for n in derived["provenance"]["notes"])


def test_a_photo_is_refused_without_writing_anything(tmp_path, monkeypatch):
    tools, _record, _store = _context(tmp_path, monkeypatch, _photo_png())
    before = copy.deepcopy(tools.scene)
    result = json.loads(tools.asset(action="knock_out_background", node_id=NODE))
    assert result["error_code"] == "asset.knockout_background_not_plain", result
    assert tools.scene == before


def test_it_needs_a_node(tmp_path, monkeypatch):
    tools, _record, _store = _context(tmp_path, monkeypatch, _tile_png())
    result = json.loads(tools.asset(action="knock_out_background"))
    assert result["error_code"] == "asset.bad_request"
