"""SVG raster helper (`make_rasterize_svg`) regression guards.

Two bugs made the describe-backfill decline EVERY SVG (LUMI0804 "svg preview
unavailable"), proven live against `asset_ing_c03b83ed754765b1` in kit
`brand_kit_ing_60eae5eb…`:

1. the helper rastered against `core.new_scene(...)`, which yields a scene with
   ZERO pages — so the early `if not pages: return None` fired before export;
2. the engine emits raw pixel bytes under the artifact key `bytes` (a list of
   ints), never `bytes_base64` — reading the wrong key silently dropped the
   preview even when the export succeeded.

These tests inject a fake CoreClient + repo so they lock the glue without an
engine build. The full end-to-end raster (real engine, real 617KB SVG →
512×512 PNG, 7223 distinct colors) was verified live during the fix.
"""

from __future__ import annotations

from lumen_ingestion.pipeline import make_rasterize_svg


class _FakeRepo:
    def require_asset_record(self, asset_id: str) -> dict:
        return {"asset": {"id": asset_id, "kind": "vector"}}


class _FakeCore:
    """Mimics the engine seam: new_scene returns a PAGELESS scene (the real
    behavior that broke the helper); export returns pixels under `bytes`."""

    def __init__(self) -> None:
        self.exported_page_ids: list[str] | None = None
        self.inserted_parents: list[str] = []

    def new_scene(self, document_id: str, title: str, *a, **k) -> dict:
        return {"pages": {}, "nodes": {}, "assets": {}, "meta": {"id": document_id}}

    def apply_operations(self, scene: dict, ops: list[dict]) -> dict:
        for op in ops:
            self.inserted_parents.append(op["parent"]["id"])
        return {"scene": scene, "diagnostics": []}

    def export_preview(self, scene, fmt, *, page_ids, raise_on_error, asset_store_root):
        self.exported_page_ids = list(page_ids)
        # Raw pixel bytes as a list of ints — exactly the engine's artifact shape.
        return {
            "export": {
                "artifacts": [
                    {"page_id": page_ids[0], "format": fmt, "bytes": [1, 2, 3, 4]}
                ]
            }
        }


def test_rasterize_creates_a_page_and_reads_bytes(monkeypatch) -> None:
    core = _FakeCore()
    import lumen_api.core as core_module

    monkeypatch.setattr(core_module, "CoreClient", lambda: core)

    rasterize = make_rasterize_svg(_FakeRepo(), "/tmp/asset-store")
    out = rasterize("asset_svg")

    # The helper no longer declines on new_scene's empty page set: it makes its
    # own page, inserts into it, and exports it.
    assert out == bytes([1, 2, 3, 4])
    assert core.inserted_parents == ["page_svg_raster"]
    assert core.exported_page_ids == ["page_svg_raster"]


def test_rasterize_returns_none_when_no_artifact_bytes(monkeypatch) -> None:
    class _EmptyCore(_FakeCore):
        def export_preview(self, *a, **k):
            return {"export": {"artifacts": []}}

    core = _EmptyCore()
    import lumen_api.core as core_module

    monkeypatch.setattr(core_module, "CoreClient", lambda: core)

    rasterize = make_rasterize_svg(_FakeRepo(), "/tmp/asset-store")
    assert rasterize("asset_svg") is None
