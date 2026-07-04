#!/usr/bin/env python
"""Render a Lumen DSL doc that references a real image asset to PNG (Step 10 probe).

Unlike render-probe.py, this ingests a real image into a temp content-addressed
store, registers it on the scene under a fixed asset id, compiles the DSL
(which references `asset(<id>)`), applies a cover-fit + focal placement on the
image node(s) (what `place_asset_in_node` does in the agent loop), and exports a
PNG with bytes resolved from the store. So the hero photo renders as real pixels,
cover-cropped under the scrim, with a legible headline — the Slice-0 image idiom.

Usage:
    python .context/render-probe-image.py <doc.lumen> <image.png> <out.png> [asset_id]
Requires: PYTHONPATH=apps/api:apps/agent_runtime, LUMEN_CORE_HELPER set (recommended).
"""
import base64
import json
import sys
import tempfile

from lumen_api.core import CoreClient

COVER_FOCAL = {"x": 0.5, "y": 0.38}


def _is_image_node(node: dict) -> bool:
    kind = node.get("kind")
    return isinstance(kind, dict) and kind.get("kind") == "image"


def main(src: str, image_path: str, out: str, asset_id: str = "hero_photo") -> None:
    dsl = open(src).read()
    img_bytes = open(image_path, "rb").read()
    c = CoreClient()
    store_root = tempfile.mkdtemp(prefix="lumen-img-probe-")

    ingest = c.ingest_asset(
        store_root=store_root,
        bytes_base64=base64.b64encode(img_bytes).decode("ascii"),
        asset_id=asset_id,
        label="Hero photo",
        declared_mime_type="image/png",
        kind="raster_image",
        source={"kind": "generated", "request_id": asset_id, "model": "render-probe"},
        raise_on_error=False,
    )
    if not ingest.get("ok"):
        print(json.dumps({"ok": False, "stage": "ingest", "error": ingest.get("error")}, indent=2))
        return
    record = (ingest.get("asset") or {}).get("record") or {}

    scene = c.new_scene("img-probe", "img-probe")
    scene.setdefault("assets", {})[asset_id] = record

    res = c.compile_dsl_into_scene(scene, dsl)
    co = (res.get("dsl") or {}).get("compile_output") or {}
    cerrs = [d for d in (co.get("diagnostics") or []) if d and d.get("severity") in ("error", "blocker")]
    if co.get("halted_at") or cerrs:
        print(json.dumps({"ok": False, "stage": "compile", "errors": cerrs, "halted": co.get("halted_at")}, indent=2))
        return
    compiled = res["scene"]

    # Resolve brand tokens ($surface.*, $opacity.scrim, $type.*) + compute
    # geometry by preflighting against the platform brand kit — the same step
    # the agent loop runs before rendering a preview. Without this the scrim
    # opacity and inverse colors stay unresolved.
    pf = c.preflight_scene(compiled, c.platform_default_brand_kit())
    resolved = pf.get("scene")
    if not isinstance(resolved, dict):
        print(json.dumps({"ok": False, "stage": "preflight", "error": "no resolved scene"}, indent=2))
        return

    # Apply a cover-fit + focal placement on every image node (what
    # place_asset_in_node carries; the DSL `image asset(id)` line itself does not).
    placed = 0
    for node in (resolved.get("nodes") or {}).values():
        if _is_image_node(node) and not node.get("asset_placement"):
            node["asset_placement"] = {
                "fit": "cover",
                "focal_point": dict(COVER_FOCAL),
                "alt_text": "Hero photo",
            }
            placed += 1

    exp = c.export_preview(resolved, "png", asset_store_root=store_root)
    artifacts = (exp.get("export") or {}).get("artifacts") or []
    wrote = False
    for a in artifacts:
        b64 = a.get("bytes") or a.get("bytes_base64") or a.get("data_base64") or a.get("base64")
        if isinstance(b64, list):
            open(out, "wb").write(bytes(b64)); wrote = True; break
        if b64:
            open(out, "wb").write(base64.b64decode(b64)); wrote = True; break
    diags = (exp.get("export") or {}).get("diagnostics") or []
    asset_diags = [d.get("code") for d in diags if str(d.get("code", "")).startswith(("LUME020", "LUME021", "LUMA"))]
    print(json.dumps({"ok": wrote, "out": out, "placements_applied": placed,
                      "store_root": store_root, "asset_diagnostics": asset_diags}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
