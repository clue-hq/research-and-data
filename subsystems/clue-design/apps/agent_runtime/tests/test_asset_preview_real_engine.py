"""Real-engine proof for D3's on-demand SVG rasterization (asset_preview).

These tests drive the ACTUAL ``lumen-api-helper`` release binary — no
``_RasterizingCore`` stubs. The stub suite stayed green for D3's whole
shipped life while the real engine rejected the raster node outright
(``CoreError: missing field `corner```) inside a blanket swallow, so every
``view("asset:<svg>")`` answered ``asset_unavailable`` in production
(Wave-C D3 forensic, 2026-08-29). This tier exists so that class of
schema drift can never ship silently again.

Skipped loudly when the helper binary is not built
(``cargo build -p lumen-api-helper --release``).
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from lumen_agent.tools.asset_preview import (
    _RASTER_PAGE_ID,
    _raster_image_node,
    _raster_page,
    rasterize_vector_preview,
    rasterized_vector_path,
)

SUBSYSTEM_ROOT = Path(__file__).resolve().parents[3]
HELPER = SUBSYSTEM_ROOT / "target" / "release" / "lumen-api-helper"

pytestmark = pytest.mark.skipif(
    not HELPER.exists(),
    reason=(
        "lumen-api-helper release binary not built "
        "(cargo build -p lumen-api-helper --release)"
    ),
)

# A vector whose raster is unmistakable: a full-bleed black square. If the
# engine paints the artwork, the center pixel is black; if it paints AROUND
# missing bytes (the LUME0210 blank plate), everything is white.
SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    b'<rect width="64" height="64" fill="#000000"/></svg>'
)


@pytest.fixture()
def real_core(monkeypatch):
    from lumen_api import core as core_module

    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    return core_module.CoreClient(repo_root=SUBSYSTEM_ROOT)


def _seed_store(store_root: Path) -> str:
    digest = hashlib.sha256(SVG_BYTES).hexdigest()
    blob = store_root / "sha256" / digest[:2] / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(SVG_BYTES)
    return digest


def _record(asset_id: str, digest: str) -> dict:
    """A minimal engine-valid AssetRecord for the fixture SVG."""
    return {
        "id": asset_id,
        "label": "svg raster fixture",
        "kind": "vector",
        "status": "ready",
        "source": {
            "kind": "uploaded",
            "asset_id": None,
            "filename": "fixture.svg",
            "uploaded_by": None,
        },
        "media": {
            "mime_type": "image/svg+xml",
            "filename": "fixture.svg",
            "byte_length": len(SVG_BYTES),
            "digest": {"algorithm": "sha256", "value": digest},
            "location": {
                "provider": "engine-cache",
                "opaque_ref": f"sha256/{digest[:2]}/{digest}",
                "url": None,
            },
        },
    }


def test_the_raster_node_is_accepted_by_the_real_engine_schema(real_core, tmp_path):
    """The exact call that failed for D3's whole shipped life: apply_operations
    over ``_raster_image_node``. Before the fix this raised
    ``missing field `corner``` — the engine's Node schema has no serde default
    for it. Pinned against the REAL schema so a future field addition on the
    Rust side fails here, not silently in production."""
    digest = _seed_store(tmp_path)
    asset_id = "asset_fixture_svg"
    scene = real_core.new_scene("doc_svg_raster", "svg raster")
    scene["pages"] = {_RASTER_PAGE_ID: _raster_page()}
    scene.setdefault("assets", {})[asset_id] = _record(asset_id, digest)
    applied = real_core.apply_operations(
        scene,
        [{
            "kind": "insert_node",
            "parent": {"kind": "page", "id": _RASTER_PAGE_ID},
            "index": 0,
            "node": _raster_image_node(asset_id),
        }],
    )
    assert applied.get("scene"), "engine accepted the node and returned a scene"


def test_an_svg_becomes_real_pixels_through_the_real_engine(real_core, tmp_path):
    digest = _seed_store(tmp_path)
    asset_id = "asset_fixture_svg"
    out = rasterize_vector_preview(
        real_core, _record(asset_id, digest), asset_id, tmp_path
    )
    assert out is not None, "rasterization produced a cached preview"
    data = out.read_bytes()
    assert data[:4] == b"\x89PNG"
    Image = pytest.importorskip("PIL.Image")
    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size
        assert width == 512 and height == 512
        center = img.convert("RGB").getpixel((width // 2, height // 2))
        assert center == (0, 0, 0), (
            f"center pixel {center} is not the artwork's black — a white plate "
            "here means the engine painted around a problem"
        )
    # Second view: served from the digest-keyed cache, no engine round trip.
    assert rasterize_vector_preview(
        real_core, _record(asset_id, digest), asset_id, tmp_path
    ) == out


def test_missing_bytes_answer_none_and_never_touch_the_cache(real_core, tmp_path):
    """Probe D's poisoning scenario: bytes not materialized. The engine would
    paint a BLANK plate with only a warning diagnostic, and a digest-keyed
    cache write would serve that blank as the artwork forever. The precheck
    refuses before the round trip, and nothing is cached."""
    digest = hashlib.sha256(SVG_BYTES).hexdigest()  # bytes NOT written
    asset_id = "asset_fixture_svg"
    out = rasterize_vector_preview(
        real_core, _record(asset_id, digest), asset_id, tmp_path
    )
    assert out is None
    assert not rasterized_vector_path(tmp_path, digest).exists()
    assert not (tmp_path / "svg-preview").exists()


def test_a_diagnostic_naming_the_asset_refuses_the_cache(tmp_path):
    """Defense in depth behind the byte precheck: if an export ever comes back
    with a diagnostic naming this asset (the live LUME0210 shape, recorded from
    the real helper in the Wave-C probe), the plate is refused and nothing is
    cached. Exercised through a scripted core that answers the REAL response
    shape, because with the precheck in place the real engine can no longer be
    steered into this state from here."""
    digest = _seed_store(tmp_path)
    asset_id = "asset_fixture_svg"

    class DiagnosingCore:
        def new_scene(self, document_id, title):
            return {"pages": {}, "assets": {}}

        def apply_operations(self, scene, operations):
            return {"scene": scene}

        def export_preview(self, scene, fmt, **kwargs):
            return {
                "ok": True,
                "diagnostics": [{
                    "code": "LUME0210",
                    "severity": "warning",
                    "message": "image node svg_raster_image could not resolve bytes",
                    "subject": {"id": asset_id, "kind": "asset"},
                }],
                "export": {"artifacts": [{"bytes": [137, 80, 78, 71], "format": "png"}]},
            }

    out = rasterize_vector_preview(
        DiagnosingCore(), _record(asset_id, digest), asset_id, tmp_path
    )
    assert out is None
    assert not (tmp_path / "svg-preview").exists()
