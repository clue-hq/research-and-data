"""Scene asset inspection uses current registered assets without widening access.

Offline view regressions: real tools, resolver, temporary PNG bytes and image
blocks. A hand-seeded core response models a completed generation; generation,
core validation, placement and persistence are outside this read-path test.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
from pathlib import Path

import pytest
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import view as view_mod
from lumen_agent.tools.substrate import LumenDesignTools
from PIL import Image


def _scene(assets=None):
    return {
        "meta": {"id": "doc_view_test", "title": "View test", "medium": "ad"},
        "pages": {},
        "nodes": {},
        "slots": {},
        "assets": assets or {},
    }


def _tools(tmp_path: Path, *, assets=None, store=None, **manifests):
    config = AgentRuntimeConfig(
        repo_root=tmp_path,
        model="openai:test",
        max_iterations=1,
        preview_format="png",
        trace_dir=tmp_path / "runs",
        asset_store_root=store or tmp_path / "store",
        **manifests,
    )
    # Initial scene avoids even a local helper subprocess; view is a read.
    return LumenDesignTools(config, "Inspect artwork", initial_scene=_scene(assets))


def _raster(store: Path, asset_id: str, color: tuple[int, int, int]):
    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), color).save(buffer, format="PNG")
    raw = buffer.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    path = store / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "id": asset_id,
        "label": asset_id,
        "kind": "raster_image",
        "status": "ready",
        "source": {"kind": "generated", "request_id": asset_id, "model": "fixture"},
        "media": {
            "mime_type": "image/png",
            "filename": f"{asset_id}.png",
            "digest": {"algorithm": "sha256", "value": digest},
            "location": {
                "provider": "opaque_asset_store",
                "opaque_ref": f"workspace/design/{digest}",
            },
        },
        "raster": {"pixel_width": 512, "pixel_height": 512},
    }, raw


def _view(tools, target):
    return view_mod.make_view_tool(tools).invoke({"target": target})


def _assert_pixels(blocks, raw):
    assert isinstance(blocks, list), blocks
    images = [block for block in blocks if block["type"] == "image"]
    assert len(images) == 1, blocks
    assert base64.b64decode(images[0]["data"]) == raw


def _assert_unavailable(blocks):
    assert isinstance(blocks, list), blocks
    assert not any(block["type"] == "image" for block in blocks)
    return "\n".join(block["text"] for block in blocks if block["type"] == "text")


def test_newly_registered_scene_asset_is_viewable_without_refreshing_config(tmp_path):
    tools = _tools(tmp_path)
    record, raw = _raster(tmp_path / "store", "asset_generated", (12, 34, 56))
    tools._replace_scene_from_core_response(
        {"scene": _scene({"asset_generated": record})},
        "generate_image",
        [{"kind": "upsert_asset", "asset": record}],
    )
    scene_before = copy.deepcopy(tools.scene)
    ledger_before = copy.deepcopy(tools.operations_ledger)

    _assert_pixels(_view(tools, "asset:asset_generated"), raw)

    assert tools.config.brand_kit_assets is None
    assert tools.config.asset_library is None
    assert tools.scene == scene_before
    assert tools.operations_ledger == ledger_before


@pytest.mark.parametrize("manifest", ["brand_kit_assets", "asset_library"])
def test_existing_manifest_asset_remains_viewable_without_scene_registration(tmp_path, manifest):
    record, raw = _raster(tmp_path / "store", "asset_existing", (90, 80, 70))
    tools = _tools(tmp_path, **{manifest: {"asset_existing": {"record": record}}})

    _assert_pixels(_view(tools, "asset:asset_existing"), raw)


@pytest.mark.parametrize("include_kit", [True, False])
def test_scene_fallback_preserves_kit_then_library_precedence(tmp_path, include_kit):
    store = tmp_path / "store"
    kit, kit_raw = _raster(store, "asset_shared", (200, 1, 1))
    library, library_raw = _raster(store, "asset_shared", (1, 200, 1))
    scene, _ = _raster(store, "asset_shared", (1, 1, 200))
    tools = _tools(
        tmp_path,
        assets={"asset_shared": scene},
        brand_kit_assets={"asset_shared": {"record": kit}} if include_kit else None,
        asset_library={"asset_shared": {"record": library}},
    )

    _assert_pixels(_view(tools, "asset:asset_shared"), kit_raw if include_kit else library_raw)


def test_unknown_id_lists_current_scene_assets_once_without_returning_pixels(tmp_path):
    tools = _tools(
        tmp_path,
        assets={"asset_new": {}, "asset_kit": {}, "asset_library": {}},
        brand_kit_assets={"asset_kit": {"record": {}}},
        asset_library={"asset_library": {"record": {}}, "asset_kit": {"record": {}}},
    )

    text = _assert_unavailable(_view(tools, "asset:unknown"))

    assert "unknown" in text
    assert view_mod._asset_manifest_ids(tools) == ["asset_kit", "asset_library", "asset_new"]
    for asset_id in ("asset_kit", "asset_library", "asset_new"):
        assert text.count(asset_id) == 1


def test_asset_in_another_scene_is_not_viewable_even_when_bytes_share_store(tmp_path):
    store = tmp_path / "shared-store"
    record, raw = _raster(store, "asset_other_scene", (5, 10, 15))
    owner = _tools(tmp_path / "owner", assets={"asset_other_scene": record}, store=store)
    current = _tools(tmp_path / "current", store=store)

    _assert_pixels(_view(owner, "asset:asset_other_scene"), raw)
    text = _assert_unavailable(_view(current, "asset:asset_other_scene"))

    assert "no viewable preview" in text
    assert view_mod._asset_manifest_ids(current) == []


def test_scene_record_cannot_resolve_bytes_from_another_workspace_store(tmp_path):
    foreign_store = tmp_path / "foreign" / "store"
    record, raw = _raster(foreign_store, "asset_current", (21, 31, 41))
    digest = record["media"].pop("digest")["value"]
    # Even an absolute opaque ref is reduced to its digest, then looked up in
    # the current run's store. It is never treated as a filesystem path.
    record["media"]["location"]["opaque_ref"] = str(
        foreign_store / "sha256" / digest[:2] / digest
    )
    current_store = tmp_path / "current" / "store"
    tools = _tools(
        tmp_path / "current", assets={"asset_current": record}, store=current_store
    )

    text = _assert_unavailable(_view(tools, "asset:asset_current"))

    assert "preview file is missing" in text
    assert not current_store.exists()
    assert (foreign_store / "sha256" / digest[:2] / digest).read_bytes() == raw


def test_scene_asset_uses_existing_thumbnail_preference(tmp_path):
    store = tmp_path / "store"
    primary, _ = _raster(store, "asset_primary", (100, 101, 102))
    thumb, thumb_raw = _raster(store, "asset_thumb", (50, 51, 52))
    primary["media"]["thumbnail"] = {
        "location": thumb["media"]["location"],
        "mime_type": "image/png",
        "pixel_width": 512,
        "pixel_height": 512,
    }
    tools = _tools(tmp_path, assets={"asset_primary": primary})

    _assert_pixels(_view(tools, "asset:asset_primary"), thumb_raw)


@pytest.mark.parametrize("ink, opaque, translucent, on_light, on_dark", [
    ((255, 255, 255, 255), 65536, 0, (255, 255, 255), (255, 255, 255)),
    ((0, 0, 0, 255), 65536, 0, (0, 0, 0), (0, 0, 0)),
    ((0, 0, 0, 128), 0, 65536, (127, 127, 127), (16, 16, 16)),
])
def test_transparent_asset_view_shows_controlled_surfaces_without_changing_source(
    tmp_path, ink, opaque, translucent, on_light, on_dark,
):
    """A transparent wordmark must not look like a baked plate or vanish on white."""
    import json
    from PIL import ImageDraw

    tools = _tools(tmp_path, scene_skill_bundle="candidate")
    record, _ = _raster(tmp_path / "store", "logo", (1, 2, 3))
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((128, 128, 383, 383), fill=ink)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / "store" / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    record["media"]["digest"]["value"] = digest
    record["media"]["location"]["opaque_ref"] = f"workspace/design/{digest}"
    tools.scene["assets"]["logo"] = record
    before = copy.deepcopy(tools.scene)

    blocks = _view(tools, "asset:logo")
    images = [b for b in blocks if b["type"] == "image"]
    assert len(images) == 2, "Source plus controlled light/dark inspection needed"
    assert base64.b64decode(images[0]["data"]) == raw
    facts = json.loads(blocks[2]["text"])["preview_alpha"]
    assert facts["transparent_pixels"] == 196608
    assert facts["opaque_pixels"] == opaque
    assert facts["translucent_pixels"] == translucent
    assert facts["visible_bounds_px"] == [128, 128, 384, 384]
    comparison = Image.open(io.BytesIO(base64.b64decode(images[1]["data"])))
    assert comparison.mode == "RGB"
    w, h = comparison.size
    # Left is white, right charcoal; both preserve the exact opaque source ink.
    assert comparison.getpixel((0, 0)) == (255, 255, 255)
    assert comparison.getpixel((w - 1, 0)) == (32, 32, 32)
    assert comparison.getpixel((w // 4, h // 2)) == on_light
    assert comparison.getpixel((3 * w // 4, h // 2)) == on_dark
    assert path.read_bytes() == raw
    assert tools.scene == before
    from dataclasses import replace
    tools.config = replace(tools.config, scene_skill_bundle="legacy")
    _assert_pixels(_view(tools, "asset:logo"), raw)


def test_candidate_opaque_asset_view_does_not_add_a_transparency_comparison(tmp_path):
    tools = _tools(tmp_path, scene_skill_bundle="candidate")
    record, raw = _raster(tmp_path / "store", "opaque", (21, 32, 43))
    tools.scene["assets"]["opaque"] = record
    _assert_pixels(_view(tools, "asset:opaque"), raw)
