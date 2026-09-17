"""Deterministic source-pixel crops through the public tool and real engine.

No provider, database or service. A crop must remain an ordinary placeable image,
with exact decoded samples and source custody, rather than a generated UI remake.
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
from agent_fixtures import runtime_config
from langchain_core.tools import StructuredTool
from lumen_agent.tools.asset_preview import (
    _RASTER_PAGE_ID,
    _raster_image_node,
    _raster_page,
    blob_path_for_digest,
)
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_api import core as core_module
from PIL import Image
from test_image_crop_pixels import rgb16_png

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "target/release/lumen-api-helper"
pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")


def _png(*, orientation=None):
    image = Image.new("RGBA", (4, 3))
    image.putdata(
        [
            (10, 11, 12, 0),
            (20, 21, 22, 32),
            (30, 31, 32, 64),
            (40, 41, 42, 96),
            (50, 51, 52, 128),
            (60, 61, 62, 160),
            (70, 71, 72, 192),
            (80, 81, 82, 224),
            (90, 91, 92, 255),
            (100, 101, 102, 0),
            (110, 111, 112, 128),
            (120, 121, 122, 255),
        ]
    )
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", exif=exif)
    return buffer.getvalue()


@pytest.fixture
def crop_context(tmp_path, monkeypatch):
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(ROOT)
    store = tmp_path / "cache"
    original = _png()
    record = core.ingest_asset(
        store_root=str(store),
        bytes_base64=base64.b64encode(original).decode(),
        asset_id="source",
        label="Original screenshot",
        declared_mime_type="image/png",
        kind="raster_image",
        source={"kind": "website", "url": "https://example.test/"},
        provenance={"notes": ["verified original"]},
        license={"name": "owned", "allow_modification": True, "allow_export": True},
    )["asset"]["record"]
    scene = core.new_scene("doc_crop_test", "Crop test")
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
    tools = LumenDesignTools(config, "crop source", initial_scene=scene)

    class NoProvider:
        def __getattr__(self, name):
            pytest.fail(f"crop accessed provider: {name}")

    monkeypatch.setattr("lumen_agent.tools.substrate.image_provider", NoProvider())
    return tools, record, original, store


def _crop(tools, rect=None, **kwargs):
    return json.loads(tools.asset(action="crop_image", asset_id="source", crop_rect=rect, **kwargs))


def test_crop_preserves_exact_rgba_pixels_source_and_independent_placement(crop_context):
    tools, record, original, store = crop_context
    before = copy.deepcopy(tools.scene)
    result = _crop(tools, [1, 1, 4, 3])
    assert result.get("image_crop", {}).get("status") == "ok", result
    output = result["image_crop"]
    asset_id = output["asset_id"]
    assert asset_id != "source"
    derived = tools.scene["assets"][asset_id]
    data = blob_path_for_digest(store, derived["media"]["digest"]["value"]).read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (3, 2)
        assert image.mode == "RGBA"
        assert list(image.getdata()) == [
            (60, 61, 62, 160),
            (70, 71, 72, 192),
            (80, 81, 82, 224),
            (100, 101, 102, 0),
            (110, 111, 112, 128),
            (120, 121, 122, 255),
        ]
    assert tools.scene["assets"]["source"] == before["assets"]["source"]
    assert tools.config.asset_library["source"]["record"] == record
    assert (
        blob_path_for_digest(store, hashlib.sha256(original).hexdigest()).read_bytes() == original
    )
    assert tools.scene["nodes"] == before["nodes"]  # cropping never auto-places
    receipt = output["crop_receipt"]
    assert receipt["source_asset_id"] == "source"
    assert receipt["source_digest"] == hashlib.sha256(original).hexdigest()
    assert receipt["source_rect"] == [1, 1, 4, 3]
    assert receipt["source_dimensions"] == {"width": 4, "height": 3}
    assert receipt["output_dimensions"] == {"width": 3, "height": 2}
    assert receipt["output_digest"] == hashlib.sha256(data).hexdigest()
    assert receipt["orientation"] == "decoded_pixels_no_rotation"
    assert derived["source"]["kind"] == "manual"
    assert "model" not in derived["source"]
    assert derived["license"] == record["license"]
    notes = derived["provenance"]["notes"]
    assert "verified original" in notes
    assert (
        json.loads(
            next(
                note.removeprefix("asset_derivation=")
                for note in notes
                if note.startswith("asset_derivation=")
            )
        )
        == receipt
    )
    placed = json.loads(
        tools.asset(
            action="place",
            asset_id=asset_id,
            node_id="svg_raster_image",
            fit="contain",
            preserve_transparency=True,
        )
    )
    assert placed["placement"]["status"] == "ok", placed
    node = tools.scene["nodes"]["svg_raster_image"]
    assert node["kind"]["kind"] == "image"
    assert node["kind"]["asset_id"] == asset_id
    assert node["asset_placement"]["fit"] == "contain"
    assert node["asset_placement"]["preserve_transparency"] is True


@pytest.mark.parametrize(
    "rect",
    [
        None,
        [],
        [0, 0, 1],
        [0, 0, 1, 1, 2],
        [0, 0, 0, 1],
        [2, 1, 1, 2],
        [-1, 0, 2, 2],
        [0, 0, 5, 3],
        [0, 0, 4, 4],
        [True, 0, 2, 2],
        [0, 0, 2.0, 2],
        [0, "0", 2, 2],
        [0, 0, float("nan"), 2],
    ],
)
def test_invalid_crop_refuses_before_any_asset_or_scene_write(crop_context, monkeypatch, rect):
    tools, _, _, store = crop_context
    before = copy.deepcopy(tools.scene)
    blobs = sorted(str(p) for p in store.rglob("*") if p.is_file())
    monkeypatch.setattr(tools.core, "ingest_asset", lambda **kw: pytest.fail("ingest on refusal"))
    monkeypatch.setattr(
        tools.core, "apply_operations", lambda *a: pytest.fail("scene write on refusal")
    )
    result = _crop(tools, rect)
    assert result["status"] == "error", result
    assert result["error_code"] == "asset.crop_invalid_rect"
    assert tools.scene == before
    assert blobs == sorted(str(p) for p in store.rglob("*") if p.is_file())
    assert tools.operations_ledger == []


@pytest.mark.parametrize(
    "problem",
    [
        "unknown",
        "archived",
        "wrong_id",
        "missing",
        "corrupt",
        "bad_digest",
        "vector",
        "license",
        "orientation",
        "pageless",
    ],
)
def test_unusable_source_refuses_without_registration(crop_context, monkeypatch, problem):
    tools, record, original, store = crop_context
    source = tools.scene["assets"]["source"]
    path = blob_path_for_digest(store, hashlib.sha256(original).hexdigest())
    if problem == "unknown":
        del tools.scene["assets"]["source"]
        tools.config = replace(tools.config, asset_library=None)
    elif problem == "archived":
        source["status"] = "archived"
    elif problem == "wrong_id":
        source["id"] = "foreign"
    elif problem == "missing":
        path.unlink()
    elif problem == "corrupt":
        path.write_bytes(b"changed")
    elif problem == "bad_digest":
        source["media"]["digest"]["value"] = "../../outside"
    elif problem == "vector":
        source["kind"] = "vector"
        source["media"]["mime_type"] = "image/svg+xml"
    elif problem == "license":
        source["license"]["allow_modification"] = False
    elif problem == "orientation":
        oriented = _png(orientation=6)
        digest = hashlib.sha256(oriented).hexdigest()
        source["media"]["digest"]["value"] = digest
        oriented_path = blob_path_for_digest(store, digest)
        oriented_path.parent.mkdir(parents=True, exist_ok=True)
        oriented_path.write_bytes(oriented)
    else:
        tools.scene["pages"] = {}
    before = copy.deepcopy(tools.scene)
    monkeypatch.setattr(tools.core, "ingest_asset", lambda **kw: pytest.fail("ingest on refusal"))
    monkeypatch.setattr(
        tools.core, "apply_operations", lambda *a: pytest.fail("scene write on refusal")
    )
    result = _crop(tools, [0, 0, 2, 2])
    assert result["status"] == "error", result
    assert tools.scene == before
    assert tools.operations_ledger == []


def test_crop_accepts_original_library_bytes_without_prior_placement(crop_context):
    tools, _, _, _ = crop_context
    del tools.scene["assets"]["source"]
    result = _crop(tools, [0, 0, 4, 3])
    assert result["image_crop"]["status"] == "ok", result
    assert result["image_crop"]["asset_id"] in tools.scene["assets"]


def test_public_tool_schema_does_not_coerce_bool_or_float_rect(crop_context):
    tools, _, _, _ = crop_context
    public = StructuredTool.from_function(tools.asset)
    for rect in ([False, 0, 2, 2], [0, 0, 2.0, 2]):
        result = json.loads(
            public.invoke({"action": "crop_image", "asset_id": "source", "crop_rect": rect})
        )
        assert result["status"] == "error", result
        assert result["error_code"] == "asset.crop_invalid_rect"
    assert tools.operations_ledger == []


@pytest.mark.parametrize("generated", [False, True])
def test_crop_chain_keeps_generated_origin_checks_without_reclassifying_authentic_pixels(
    crop_context, generated
):
    tools, _, _, _ = crop_context
    if generated:
        tools.scene["assets"]["source"]["source"] = {"kind": "generated", "model": "test/model"}
    parent_id = "source"
    for rect in ([1, 0, 4, 3], [0, 0, 2, 2]):
        result = json.loads(tools.asset(action="crop_image", asset_id=parent_id, crop_rect=rect))
        output = result["image_crop"]
        assert output["crop_receipt"]["source_asset_id"] == parent_id
        parent_id = output["asset_id"]
        placed = json.loads(
            tools.asset(
                action="place", asset_id=parent_id, node_id="svg_raster_image", fit="contain"
            )
        )
        assert placed["placement"]["status"] == "ok"
        assert tools.scene_has_generated_imagery() is generated
        assert output["crop_receipt"].get("source_generated") is generated
        assert tools.scene["assets"][parent_id]["source"]["kind"] == "manual"


@pytest.mark.parametrize("alpha", [False, True])
def test_rgb16_source_refuses_before_ingest_or_scene_write(crop_context, monkeypatch, alpha):
    tools, _, _, store = crop_context
    raw = rgb16_png(alpha=alpha)
    digest = hashlib.sha256(raw).hexdigest()
    tools.scene["assets"]["source"]["media"]["digest"]["value"] = digest
    path = blob_path_for_digest(store, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    before = copy.deepcopy(tools.scene)
    blobs = sorted(str(p) for p in store.rglob("*") if p.is_file())
    monkeypatch.setattr(tools.core, "ingest_asset", lambda **kw: pytest.fail("ingest on refusal"))
    result = _crop(tools, [0, 0, 2, 1])
    assert result.get("status") == "error", result
    assert result["error_code"] == "asset.crop_unsupported"
    assert tools.scene == before
    assert tools.operations_ledger == []
    assert blobs == sorted(str(p) for p in store.rglob("*") if p.is_file())


@pytest.mark.parametrize("depth", [0, 1, 2])
def test_stub_origin_cannot_be_laundered_through_a_crop_chain(crop_context, monkeypatch, depth):
    tools, _, _, store = crop_context
    parent_id = "source"
    tools.scene["assets"]["source"]["source"] = {"kind": "generated", "model": "test/model"}
    # Build real receipts/bytes, then represent an older pre-fix stub derivative.
    for _ in range(depth):
        result = json.loads(
            tools.asset(action="crop_image", asset_id=parent_id, crop_rect=[0, 0, 2, 2])
        )
        parent_id = result["image_crop"]["asset_id"]
    tools.scene["assets"]["source"]["source"]["model"] = "stub-image-v0"
    before = copy.deepcopy(tools.scene)
    ledger = copy.deepcopy(tools.operations_ledger)
    blobs = sorted(str(p) for p in store.rglob("*") if p.is_file())
    monkeypatch.setattr(tools.core, "ingest_asset", lambda **kw: pytest.fail("ingest on refusal"))
    result = json.loads(
        tools.asset(action="crop_image", asset_id=parent_id, crop_rect=[0, 0, 1, 1])
    )
    assert result.get("status") == "error", result
    assert result["error_code"] == "asset.crop_unsupported_source"
    assert tools.scene == before
    assert tools.operations_ledger == ledger
    assert blobs == sorted(str(p) for p in store.rglob("*") if p.is_file())


def test_placeholder_kind_refuses_with_unsupported_source_error(crop_context, monkeypatch):
    tools, _, _, _ = crop_context
    tools.scene["assets"]["source"]["kind"] = "placeholder"
    monkeypatch.setattr(tools.core, "ingest_asset", lambda **kw: pytest.fail("ingest on refusal"))
    result = _crop(tools, [0, 0, 2, 2])
    assert result.get("status") == "error", result
    assert result["error_code"] == "asset.crop_unsupported_source"


@pytest.mark.parametrize("problem", ["missing_parent", "changed_parent_digest", "cycle"])
def test_crop_ancestry_must_resolve_before_reusing_a_derivative(crop_context, monkeypatch, problem):
    tools, _, _, _ = crop_context
    created = _crop(tools, [0, 0, 2, 2])["image_crop"]
    derived = tools.scene["assets"][created["asset_id"]]
    if problem == "missing_parent":
        del tools.scene["assets"]["source"]
        tools.config = replace(tools.config, asset_library=None)
    elif problem == "changed_parent_digest":
        tools.scene["assets"]["source"]["media"]["digest"]["value"] = "f" * 64
    else:
        receipt = copy.deepcopy(created["crop_receipt"])
        receipt["source_asset_id"] = derived["id"]
        receipt["source_digest"] = derived["media"]["digest"]["value"]
        derived["provenance"]["notes"].append("asset_derivation=" + json.dumps(receipt))
    before = copy.deepcopy(tools.scene)
    ledger = copy.deepcopy(tools.operations_ledger)
    monkeypatch.setattr(tools.core, "ingest_asset", lambda **kw: pytest.fail("ingest on refusal"))
    result = json.loads(
        tools.asset(action="crop_image", asset_id=derived["id"], crop_rect=[0, 0, 1, 1])
    )
    assert result.get("status") == "error", result
    assert result["error_code"] == "asset.crop_unsupported_source"
    assert tools.scene == before
    assert tools.operations_ledger == ledger
