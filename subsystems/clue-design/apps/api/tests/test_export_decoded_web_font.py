"""The engine-side half of option A (2026-09-02).

Red case, pinned on purpose: hand the exporter the WOFF2 bytes a brand kit used to store and
the SVG export refuses them (`export.font_embed_unsupported_container`) — the defect that left
~71% of brand fonts un-embeddable and, through P0.4's gate, un-checkpointed. Green case: the
same face decoded to sfnt at ingestion embeds as `@font-face` and shapes without a fallback.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from lumen_api.core import CoreClient
from lumen_api.font_containers import decode_web_font

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"

#: One page, one text run, in a family that exists ONLY as the brand face registered below —
#: so an embedded `@font-face` for it can only have come from the brand_fonts spec.
DSL = """
page page_font size(600,200,px)
  headline text "Decoded web font" p(40,40) s(520,120) font("InterWeb",40,400,left) fill(#111827)
"""

PROFILE = {
    "name": "decoded_face_svg",
    "format": "svg",
    "pdf_intent": None,
    "raster": None,
    "include_bleed": False,
    "embed_fonts": True,
}


@pytest.fixture(scope="module")
def core() -> CoreClient:
    return CoreClient()


@pytest.fixture(scope="module")
def inter_woff2() -> bytes:
    font = TTFont(BytesIO(INTER.read_bytes()), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def build_scene(core: CoreClient) -> dict:
    fresh = core.new_scene("doc_decoded_web_font", "Decoded web font fixture")
    compiled = core.compile_dsl_into_scene(fresh, DSL)
    compile_output = (compiled.get("dsl") or {}).get("compile_output") or {}
    errors = [
        entry
        for entry in compile_output.get("diagnostics") or []
        if entry.get("diagnostic", {}).get("severity") == "error"
    ]
    assert not errors, f"fixture DSL must compile clean: {errors}"
    return compiled["scene"]


def store_face(root: Path, data: bytes) -> str:
    """Place bytes where the helper's brand-font loader looks: sha256/{ab}/{digest}."""
    digest = hashlib.sha256(data).hexdigest()
    path = root / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest


def brand_fonts(root: Path, digest: str) -> dict:
    return {
        "store_root": str(root),
        "faces": [{"digest": digest, "family": "InterWeb", "weight": 400, "style": "normal"}],
    }


def export(core: CoreClient, scene: dict, export_format: str, spec: dict) -> dict:
    return core.export_preview(
        scene,
        export_format=export_format,
        page_ids=["page_font"],
        profile={**PROFILE, "format": export_format, "name": f"decoded_face_{export_format}"},
        raise_on_error=False,
        brand_fonts=spec,
    )


def artifact_text(response: dict) -> str:
    artifacts = response["export"]["artifacts"]
    assert artifacts, response
    return bytes(int(value) & 0xFF for value in artifacts[0]["bytes"]).decode("utf-8")


def test_the_woff2_face_still_refuses_svg_embedding_red_case(
    core: CoreClient, tmp_path: Path, inter_woff2: bytes
) -> None:
    scene = build_scene(core)
    digest = store_face(tmp_path, inter_woff2)
    response = export(core, scene, "svg", brand_fonts(tmp_path, digest))
    assert response.get("ok") is False, response
    assert response["error"]["code"] == "export.font_embed_unsupported_container"
    assert "SVG font embedding failed" in response["error"]["message"]


def test_the_decoded_face_embeds_in_svg_and_shapes_without_fallback(
    core: CoreClient, tmp_path: Path, inter_woff2: bytes
) -> None:
    decoded = decode_web_font(inter_woff2)
    assert decoded is not None
    scene = build_scene(core)
    digest = store_face(tmp_path, decoded.data)
    spec = brand_fonts(tmp_path, digest)

    svg = export(core, scene, "svg", spec)
    assert svg.get("ok"), svg
    text = artifact_text(svg)
    assert "@font-face" in text
    assert "InterWeb" in text
    assert "data:font/ttf;base64," in text

    png = export(core, scene, "png", spec)
    assert png.get("ok"), png
    diagnostics = list(png.get("diagnostics") or []) + list(
        png["export"].get("diagnostics") or []
    )
    fallbacks = [d for d in diagnostics if d.get("code") in ("LUMS0100", "LUMS0101")]
    assert not fallbacks, fallbacks
