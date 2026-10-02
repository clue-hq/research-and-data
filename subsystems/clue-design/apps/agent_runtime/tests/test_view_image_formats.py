"""Vision observations carry truthful encoding and do not mutate source assets."""

from __future__ import annotations

import base64
import copy
import hashlib
import io

import pytest
from PIL import Image

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import view as view_mod
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.tools.web_substrate import LumenWebTools, make_web_view_tool


def _image_bytes(fmt, size=(600, 600), *, animated=False):
    buffer = io.BytesIO()
    first = Image.new("RGB", size, (20, 40, 60))
    options = {}
    if animated:
        options.update(
            save_all=True,
            append_images=[Image.new("RGB", size, (200, 100, 50))],
            duration=[100, 100],
            loop=0,
        )
    first.save(buffer, format=fmt, **options)
    return buffer.getvalue()


@pytest.mark.parametrize("fmt,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png")])
def test_in_band_static_image_preserves_bytes_and_declares_its_actual_mime(fmt, mime):
    raw = _image_bytes(fmt)
    emitted, actual_mime = view_mod._normalize_image_bytes(raw)
    assert emitted == raw
    assert actual_mime == mime
    with Image.open(io.BytesIO(emitted)) as image:
        assert image.format == fmt


@pytest.mark.parametrize("animated", [False, True])
def test_gif_observation_is_a_static_png_of_the_first_source_frame(animated):
    raw = _image_bytes("GIF", animated=animated)
    emitted, mime = view_mod._normalize_image_bytes(raw)
    with Image.open(io.BytesIO(raw)) as source, Image.open(io.BytesIO(emitted)) as observed:
        assert mime == "image/png"
        assert observed.format == "PNG"
        assert not getattr(observed, "is_animated", False)
        assert observed.convert("RGBA").tobytes() == source.convert("RGBA").tobytes()


@pytest.mark.parametrize("fmt,animated", [("JPEG", False), ("PNG", False), ("GIF", True)])
@pytest.mark.parametrize("size,ceiling", [((8, 16), 7500), ((1600, 1200), 1000)])
def test_resized_observation_is_png_with_preserved_aspect_and_first_frame(fmt, animated, size, ceiling):
    raw = _image_bytes(fmt, size, animated=animated)
    emitted, mime = view_mod._normalize_image_bytes(raw, max_px=ceiling)
    with Image.open(io.BytesIO(emitted)) as observed, Image.open(io.BytesIO(raw)) as source:
        assert mime == "image/png" and observed.format == "PNG"
        assert not getattr(observed, "is_animated", False)
        assert max(observed.size) <= ceiling
        assert min(observed.size) >= 512
        assert observed.width / observed.height == pytest.approx(size[0] / size[1], abs=0.002)
        assert observed.convert("RGB").getpixel((0, 0)) == source.convert("RGB").getpixel((0, 0))


@pytest.mark.parametrize("lane,target", [
    ("scene", "asset:animation"), ("scene", "reference:1"), ("web", "asset:animation"),
])
@pytest.mark.parametrize("thumbnail", [False, True])
def test_real_view_labels_observed_frame_and_preserves_original_custody(tmp_path, lane, target, thumbnail):
    raw = _image_bytes("GIF", animated=True)
    digest = hashlib.sha256(raw).hexdigest()
    store = tmp_path / "store"
    path = store / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    record = {
        "id": "animation", "kind": "raster_image", "status": "ready",
        "media": {
            "mime_type": "image/gif", "digest": {"algorithm": "sha256", "value": digest},
            "location": {"provider": "opaque_asset_store", "opaque_ref": f"workspace/design/{digest}"},
        },
        "raster": {"pixel_width": 600, "pixel_height": 600},
    }
    preview_digest = digest
    if thumbnail:
        # A derived thumbnail need not depict source frame zero. Do not invent
        # a source-frame mapping when the record does not provide one.
        preview = io.BytesIO()
        Image.new("RGB", (600, 600), (200, 100, 50)).save(preview, format="PNG")
        preview_digest = hashlib.sha256(preview.getvalue()).hexdigest()
        preview_path = store / "sha256" / preview_digest[:2] / preview_digest
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_bytes(preview.getvalue())
        record["media"]["thumbnail"] = {
            "mime_type": "image/png",
            "location": {"provider": "opaque_asset_store", "opaque_ref": preview_digest},
            "pixel_width": 600, "pixel_height": 600,
        }
    config = AgentRuntimeConfig(
        repo_root=tmp_path, model="openai:test", max_iterations=1, preview_format="png",
        trace_dir=tmp_path / "runs", asset_store_root=store,
        asset_library={"animation": {"record": record}},
        reference_assets={"animation": {"record": record, "preview_digest": preview_digest, "order": 0}},
    )
    # An initial scene prevents any helper/backend startup; this test invokes
    # only the real local view tool and registered source resolver.
    scene = {"meta": {"id": "doc", "medium": "ad"}, "pages": {}, "nodes": {}, "assets": {}}
    if lane == "scene":
        tools = LumenDesignTools(config, "Inspect the reference", initial_scene=scene)
        document = tools.scene
        before = copy.deepcopy(document)
        content = view_mod.make_view_tool(tools).invoke({"target": target})
    else:
        web_doc = {
            "schema_version": 1, "id": "doc", "title": "Test site",
            "theme": {}, "custom_css": "", "assets": {},
            "pages": [{
                "id": "home", "name": "Home", "route": "/", "root": "root",
                "nodes": {"root": {"id": "root", "kind": "container", "classes": "", "new_tab": False}},
            }],
        }
        tools = LumenWebTools(config, "Inspect the asset", initial_web_doc=web_doc)
        document = tools.web_doc
        before = copy.deepcopy(document)
        content = make_web_view_tool(tools).invoke({"target": target})
    assert isinstance(content, list), content
    text = " ".join(block["text"] for block in content if block["type"] == "text")
    if thumbnail:
        assert "source frame" in text.lower() and "unknown" in text.lower()
        assert "frame index 0" not in text.lower()
    else:
        assert "first frame" in text.lower() and "frame index 0" in text.lower()
    assert "animation" in text.lower() and "not reviewed" in text.lower()
    images = [block for block in content if block["type"] == "image"]
    assert len(images) == 1 and images[0]["mime_type"] == "image/png"
    with Image.open(io.BytesIO(base64.b64decode(images[0]["data"]))) as image:
        assert image.format == "PNG" and not getattr(image, "is_animated", False)
        assert image.convert("RGB").getpixel((0, 0)) == ((200, 100, 50) if thumbnail else (20, 40, 60))
    assert path.read_bytes() == raw
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert document == before
