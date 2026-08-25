#!/usr/bin/env python3
"""Capture a deterministic, re-runnable baseline of the image-generation pipeline.

WHY THIS EXISTS
---------------
We are building the image-model feature in sequenced steps (Slice 0, Steps 1..10).
To measure that each step actually *improves* the output we need a fixed reference
point: the same brief, run through the same pipeline, captured as artifacts we can
diff. This script is that reference point for the current branch state.

WHAT IT EXERCISES (end-to-end, server side)
-------------------------------------------
    recorded model response   (credit-free, --live swaps in the real OpenRouter call)
        -> image_provider.generate()           # real prompt-compose + decode + result shaping
        -> CoreClient.ingest_asset(source=generated)   # real content-addressed ingest
        -> compile_dsl_into_scene()            # real DSL -> scene
        -> inject asset_placement (fit/focal/alt)       # scene-level (not in DSL yet)
        -> export_preview(png, asset_store_root)        # real Skia render

DETERMINISM
-----------
The *photographic content* of a T2I model is non-deterministic and (right now) gated
behind OpenRouter account credits. That content is NOT what Steps 2..10 improve — they
improve decode, ingest provenance, placement (fit/focal), scrim, render fidelity and
(later) the agent's authoring decisions. So by default we substitute a fixed,
procedurally-generated reference image for the model's output and hold it constant.
This isolates *our* engineering from model noise. Use --live (with credits) to swap in
the real model and compare the real photo through the identical downstream pipeline.

USAGE
-----
    /tmp/lumen-smoke-venv/bin/python capture_baseline.py            # credit-free (default)
    /tmp/lumen-smoke-venv/bin/python capture_baseline.py --live     # real OpenRouter call

Requires: the built helper binary (target/debug/lumen-api-helper) and httpx.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path


# --- locate repo + wire imports -------------------------------------------------

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    while p != p.parent:
        if (p / "crates").is_dir() and (p / "apps").is_dir() and (p / "Cargo.toml").exists():
            return p
        p = p.parent
    raise SystemExit("could not locate repo root (looked for crates/ + apps/ + Cargo.toml)")


HERE = Path(__file__).resolve().parent
REPO = find_repo_root(HERE)


def load_env(repo: Path) -> None:
    envf = repo / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    # A real chat-completions image-output model id, used only when `.env` (read
    # above, and it wins — this is a setdefault) names none.
    #
    # W1.4: if your `.env` DOES set IMAGE_MODEL_ID, that value is what `--live`
    # uses, and a wrong one 404s with "No endpoints found that support the
    # requested output modalities: image, text". `openai/gpt-image-2` is the known
    # trap — real on OpenRouter's dedicated Image API, absent from the
    # chat-completions catalogue this path uses. Verified working ids:
    # openai/gpt-5.4-image-2, google/gemini-2.5-flash-image.
    os.environ.setdefault("IMAGE_MODEL_ID", "google/gemini-2.5-flash-image")
    # Point CoreClient straight at the built helper so it never shells out to cargo.
    helper = repo / "target" / "debug" / "lumen-api-helper"
    if helper.exists():
        os.environ.setdefault("LUMEN_CORE_HELPER", str(helper))


load_env(REPO)
sys.path.insert(0, str(REPO / "apps" / "api"))

from lumen_api import image_provider          # noqa: E402
from lumen_api.core import CoreClient          # noqa: E402


# --- deterministic reference image (stand-in for model output) ------------------

def make_reference_png(w: int, h: int, focal=(0.5, 0.4)) -> bytes:
    """A valid RGB PNG with a diagonal teal->navy gradient and a bright off-center
    'subject' disc at the focal point — so cover/focal-crop is visibly exercised."""
    fx, fy = focal[0] * w, focal[1] * h
    rad = min(w, h) * 0.22
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG filter type 0 (None) for this scanline
        for x in range(w):
            t = (x + y) / (w + h)
            r = int(8 + 22 * t)
            g = int(64 + 120 * (1 - t))
            b = int(96 + 120 * t)
            dx, dy = x - fx, y - fy
            d = (dx * dx + dy * dy) ** 0.5
            if d < rad:
                k = 1 - (d / rad)
                r = int(r + (238 - r) * k)
                g = int(g + (246 - g) * k)
                b = int(b + (224 - b) * k)
            rows += bytes((r & 255, g & 255, b & 255))

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit, RGB
    idat = zlib.compress(bytes(rows), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def png_dims(b: bytes):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", b[16:24])
        return "png", w, h
    if b[:3] == b"\xff\xd8\xff":
        return "jpeg", None, None
    if b[:5] == b"<?xml" or b[:4] == b"<svg":
        return "svg", None, None
    return "?", None, None


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --- the canonical brief --------------------------------------------------------

PROMPT = (
    "Editorial photograph of a focused neurosurgeon reviewing a glowing 3D brain scan "
    "on a translucent display in a modern hospital, cinematic teal-and-deep-navy lighting, "
    "shallow depth of field, premium healthcare brand aesthetic, no text"
)
BRAND_NOTES = ["calm clinical confidence", "deep navy + teal palette", "premium, uncluttered"]
ALT = "Neurosurgeon reviewing a 3D brain scan on a translucent display"
ASSET_ID = "hero_image"

# 4:5 social poster: image hero on top (fixed), brand band fills the rest and centers
# its text. No scrim / overlay / z-order dependency — scrim grammar is a later step, so
# this baseline deliberately reflects only what the CURRENT build supports.
DESIGN_LUMEN = """page hero_poster size(1080,1350,px)
  canvas al(v,g(0),pad(0),x(s)) p(0,0) s(1080,1350) fill($surface.page)
    hero img asset(hero_image) s(1080,810)
    band al(v,g($space.stack.default),pad($space.card.padding),x(s),y(c)) s(1080,fill) fill($surface.page)
      kicker text "CASE STUDY" s(936,48) style($type.body) wrap_text(true)
      headline text "Faster triage, calmer clinics" s(936,210) style($type.headline) wrap_text(true)
      body text "How Insight Health cut phone wait times by 63% with AI intake." s(936,160) style($type.body) wrap_text(true)
"""


# --- recorded-response monkeypatch (credit-free mode) ---------------------------

class _FakeResp:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)[:300]

    def json(self):
        return self._payload


def install_recorded_response(reference_png: bytes, captured: dict):
    """Patch httpx.post so image_provider sees a realistic OpenRouter chat-completion
    response carrying our reference image as a base64 data URL. We also capture the
    exact request body our adapter emits — that body IS part of the baseline contract."""
    import httpx

    data_url = "data:image/png;base64," + base64.b64encode(reference_png).decode()
    payload = {
        "id": "gen-baseline",
        "model": os.environ["IMAGE_MODEL_ID"],
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "images": [{"type": "image_url", "image_url": {"url": data_url}}],
                },
                "finish_reason": "stop",
            }
        ],
    }

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["body"] = json
        captured["headers"] = {
            k: ("<redacted>" if k.lower() == "authorization" else v)
            for k, v in (headers or {}).items()
        }
        return _FakeResp(payload)

    httpx.post = fake_post


# --- scene helpers --------------------------------------------------------------

def find_image_node(scene: dict):
    for nid, node in (scene.get("nodes") or {}).items():
        kind = node.get("kind") or {}
        if kind.get("kind") == "image":
            return nid, node
    return None, None


def find_artifact_bytes(resp: dict):
    """Pull rendered bytes out of an export_preview response.

    Current shape: resp["export"]["artifacts"][0]["bytes"] is a raw int array.
    Older/base64 shapes are tolerated as a fallback."""
    arts = ((resp.get("export") or {}).get("artifacts")) or resp.get("artifacts") or []
    for a in arts:
        if not isinstance(a, dict):
            continue
        b = a.get("bytes")
        if isinstance(b, list) and b:
            return bytes(b), a.get("mime_type") or "image/png", a
        for key in ("bytes_base64", "data_base64", "b64", "data"):
            v = a.get(key)
            if isinstance(v, str) and len(v) > 32:
                return base64.b64decode(v), a.get("mime_type") or "image/png", a
    return None, None, None


# --- main -----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="call the real OpenRouter model (needs credits)")
    ap.add_argument("--ref-width", type=int, default=1280)
    ap.add_argument("--ref-height", type=int, default=720)
    args = ap.parse_args()

    out = HERE  # write artifacts next to this script (the tracked fixture dir)
    manifest = {
        "baseline": "image-pipeline / step-1b (OpenRouter chat-completions adapter wired)",
        "mode": "live" if args.live else "recorded",
        "model_id": os.environ["IMAGE_MODEL_ID"],
        "brief": {"prompt": PROMPT, "brand_notes": BRAND_NOTES, "alt": ALT},
        "stages": {},
    }

    print(f"repo: {REPO}")
    print(f"mode: {'LIVE (real OpenRouter)' if args.live else 'recorded (credit-free)'}")
    print(f"model id: {os.environ['IMAGE_MODEL_ID']}")

    # Stage 0: reference image (the held-constant model stand-in)
    ref_png = make_reference_png(args.ref_width, args.ref_height)
    (out / "reference_source.png").write_bytes(ref_png)
    rfmt, rw, rh = png_dims(ref_png)
    manifest["stages"]["reference_source"] = {
        "note": "deterministic stand-in for model output (held constant across steps)",
        "format": rfmt, "width": rw, "height": rh,
        "bytes": len(ref_png), "sha256": sha256(ref_png),
    }
    print(f"[0] reference_source.png  {rfmt} {rw}x{rh}  {len(ref_png):,}B")

    # Stage 1: generate (real adapter; recorded transport unless --live)
    captured: dict = {}
    if not args.live:
        install_recorded_response(ref_png, captured)
    try:
        result = image_provider.generate(
            prompt=PROMPT, width=1080, height=810, aspect_ratio="4:3",
            brand_notes=BRAND_NOTES, request_id="baseline-step1b",
        )
    except image_provider.ImageGenerationError as e:
        print(f"[1] GENERATE FAILED: {e.code} (status {e.status_code}): {e}")
        if args.live:
            print("    (live mode needs OpenRouter credits; run without --live for the recorded baseline)")
        return 2

    gen_fmt, gw, gh = png_dims(result.image_bytes)
    (out / "generated_source.png").write_bytes(result.image_bytes)
    if captured:
        (out / "request.json").write_text(json.dumps(captured, indent=2) + "\n")
    (out / "result.meta.json").write_text(json.dumps({
        "mime_type": result.mime_type, "model": result.model,
        "license": result.license, "provenance": result.provenance,
        "image_bytes_sha256": sha256(result.image_bytes),
        "image_format": gen_fmt, "image_width": gw, "image_height": gh,
    }, indent=2) + "\n")
    manifest["stages"]["generate"] = {
        "request_endpoint": captured.get("url") if captured else "<live>",
        "request_modalities": (captured.get("body") or {}).get("modalities") if captured else None,
        "result_mime": result.mime_type, "result_model": result.model,
        "result_bytes": len(result.image_bytes), "result_sha256": sha256(result.image_bytes),
        "license_name": (result.license or {}).get("name"),
    }
    print(f"[1] generate -> {gen_fmt} {gw}x{gh}  {len(result.image_bytes):,}B  model={result.model}")

    # Stage 2: ingest as a `generated` asset (real content-addressed store)
    core = CoreClient(repo_root=REPO)
    store = Path(tempfile.mkdtemp(prefix="lumen-baseline-store-"))
    rec_resp = core.ingest_asset(
        store_root=str(store),
        bytes_base64=base64.b64encode(result.image_bytes).decode(),
        asset_id=ASSET_ID,
        label="Generated hero",
        declared_mime_type=result.mime_type,
        license=result.license,
        provenance=result.provenance,
        source={"kind": "generated", "request_id": ASSET_ID, "model": result.model},
        raise_on_error=False,
    )
    if not rec_resp.get("ok"):
        print(f"[2] INGEST FAILED: {json.dumps(rec_resp.get('error'))}")
        print(json.dumps(rec_resp.get("diagnostics"), indent=2))
        return 3
    asset_record = ((rec_resp.get("asset") or {}).get("record")) or rec_resp.get("record") or rec_resp
    (out / "asset_record.json").write_text(json.dumps(asset_record, indent=2) + "\n")
    src = (asset_record.get("source") if isinstance(asset_record, dict) else None) or {}
    manifest["stages"]["ingest"] = {
        "asset_id": (asset_record.get("id") if isinstance(asset_record, dict) else None),
        "source_kind": src.get("kind"),
        # store_root is an ephemeral per-run temp dir; normalized so the committed
        # manifest stays machine-independent and diffable.
        "store_root": "<ephemeral content-addressed store>",
    }
    print(f"[2] ingest -> asset id={manifest['stages']['ingest']['asset_id']} source.kind={src.get('kind')}")

    # Stage 3: compile DSL -> scene
    scene = core.new_scene("image_baseline_doc", "Image baseline poster")
    (out / "design.lumen").write_text(DESIGN_LUMEN)
    comp = core.compile_dsl_into_scene(scene, DESIGN_LUMEN)
    if not comp.get("ok", True):
        print(f"[3] COMPILE FAILED: {json.dumps(comp.get('error'))}")
        print(json.dumps(comp.get("diagnostics"), indent=2))
        return 4
    scene = comp.get("scene") or scene
    nid, node = find_image_node(scene)
    if node is None:
        print("[3] COMPILE OK but no image node found in scene")
        print("scene node kinds:", [n.get("kind", {}).get("kind") for n in (scene.get("nodes") or {}).values()])
        return 5
    print(f"[3] compile ok -> image node {nid}")

    # Stage 4a: embed the asset record into the scene so export can resolve bytes.
    # (This is the `upsert_asset` operation the product uses; without it the image
    # node has no record to resolve from -> LUME0211 + blank render.)
    op = core.apply_operations(scene, [{"kind": "upsert_asset", "asset": asset_record}])
    scene = op.get("scene") or scene
    if asset_record.get("id") not in (scene.get("assets") or {}):
        print(f"[4a] WARN: asset {asset_record.get('id')} not in scene.assets after upsert; keys={list((scene.get('assets') or {}).keys())}")
    else:
        print(f"[4a] upsert_asset ok -> scene.assets has {asset_record.get('id')}")

    # Stage 4b: preflight with the platform default brand kit. This resolves the
    # semantic tokens ($surface.*, $type.*, $space.*) AND computes hug/fill layout
    # geometry; it returns an updated scene. (Skipping this is why the first render
    # collapsed every node to (0,0) and left tokens unresolved.)
    brand_kit = core.platform_default_brand_kit()
    pre = core.preflight_scene(scene, brand_kit)
    scene = pre.get("scene") or scene
    pre_diags = (pre.get("preflight") or {}).get("diagnostics") or pre.get("diagnostics") or []
    pre_summary = [
        {"code": d.get("code"), "severity": d.get("severity"), "message": d.get("message")}
        for d in pre_diags if isinstance(d, dict)
    ]
    pre_errors = [d for d in pre_summary if d.get("severity") == "error"]
    manifest["stages"]["preflight"] = {
        "brand_kit_id": brand_kit.get("id"),
        "brand_kit_version": brand_kit.get("version"),
        "error_count": len(pre_errors),
        "diagnostics": pre_summary,
    }
    print(f"[4b] preflight ok (brand={brand_kit.get('id')}) errors={len(pre_errors)} diags={len(pre_summary)}")

    # Stage 4c: inject placement (fit/focal/alt) into the resolved scene — not yet
    # expressible in DSL, so set on the scene node directly (Step 7 will add DSL syntax).
    nid, node = find_image_node(scene)
    node["asset_placement"] = {"fit": "cover", "focal_point": {"x": 0.5, "y": 0.4}, "alt_text": ALT}
    node["source_asset_id"] = ASSET_ID
    if isinstance(node.get("kind"), dict):
        node["kind"]["alt"] = ALT
    manifest["stages"]["placement"] = node["asset_placement"]

    # Stage 5: render
    exp = core.export_preview(scene, "png", asset_store_root=str(store), raise_on_error=False)
    if not exp.get("ok", True):
        print(f"[5] EXPORT FAILED: {json.dumps(exp.get('error'))}")
        print(json.dumps(exp.get("diagnostics"), indent=2))
        print("export response keys:", list(exp.keys()))
        return 6
    render_bytes, render_mime, art = find_artifact_bytes(exp)
    if render_bytes is None:
        print("[5] EXPORT OK but no artifact bytes found; response keys:", list(exp.keys()))
        (out / "_export_debug.json").write_text(json.dumps(exp, indent=2)[:20000])
        return 7
    (out / "render.png").write_bytes(render_bytes)
    dfmt, dw, dh = png_dims(render_bytes)
    diags = ((exp.get("export") or {}).get("diagnostics")) or exp.get("diagnostics") or []
    diag_summary = [
        {"code": d.get("code"), "severity": d.get("severity"), "message": d.get("message")}
        for d in diags if isinstance(d, dict)
    ]
    manifest["stages"]["render"] = {
        "mime": render_mime, "format": dfmt, "width": dw, "height": dh,
        "bytes": len(render_bytes), "sha256": sha256(render_bytes),
        "diagnostics": diag_summary,
    }
    print(f"[5] render -> {dfmt} {dw}x{dh}  {len(render_bytes):,}B  saved render.png")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("\n=== BASELINE CAPTURED ===")
    print(f"artifacts written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
