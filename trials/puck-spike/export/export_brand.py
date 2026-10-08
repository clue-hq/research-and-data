"""Export one brand's kit, fonts, assets and cloned sections for the Puck spike (read only).

Reads the lane database and blob store through the design API's own helpers, and writes:

    trials/puck-spike/data/brands/<brand>/kit.json      the brand kit as stored
    trials/puck-spike/data/brands/<brand>/fonts.json    [{family, weight, style, file}]
    trials/puck-spike/data/brands/<brand>/assets.json   kit logos and images, with files
    trials/puck-spike/data/brands/<brand>/clones.json   each clone: html, css, slots, wrapper class
    trials/puck-spike/public/brands/<brand>/...         every referenced byte, named by digest

Clone markup and CSS keep the engine's own conventions (`data-lumen-slot`, `.lumen-frag-<hex>`);
only `/asset-store/<digest>` references are rewritten to the exported files.

Usage (repo root):
    set -a; source .env; set +a
    .venv/bin/python trials/puck-spike/export/export_brand.py garner
    .venv/bin/python trials/puck-spike/export/export_brand.py conduit
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[1]

BRANDS = {
    "garner": {
        "workspace_id": "ws_c080123a7c434454898aa5ae1a8f698b",
        "kit_id": "brand_kit_ing_ba0708281cb44f7c847dfb8949110103",
        "kit_version": 2,
    },
    "conduit": {
        "workspace_id": "ws_3c96440b557a413fa02bda3fbf90cc5e",
        "kit_id": "brand_kit_ing_c162dc8c5b99418284b42a21a7a80298",
        "kit_version": 3,
    },
    "altcarbon": {
        "workspace_id": "ws_d4e6f4b1e1514e77bc3cb7dacafe0db3",
        "kit_id": "brand_kit_ing_28663a7003024d9d82651d9b93427e5f",
        "kit_version": 1,
    },
}

SKIP_ROLES = {"nav", "footer"}
SKIP_LABELS = ("Iframe is blocked", "Preferences Manage Consent", "Sign up for our newsletter")
ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")
EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/avif": "avif",
    "image/gif": "gif", "image/svg+xml": "svg", "video/mp4": "mp4", "video/webm": "webm",
    "font/ttf": "ttf", "font/otf": "otf", "font/woff": "woff", "font/woff2": "woff2",
    "font/sfnt": "ttf", "application/font-sfnt": "ttf", "application/x-font-ttf": "ttf",
}


def sniff(data: bytes) -> str:
    """Extension for bytes stored without a useful media type."""
    head = data[:16]
    if head.startswith(b"\x89PNG"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    if data[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if head[:4] in (b"\x00\x01\x00\x00", b"true"):
        return "ttf"
    if head[:4] == b"OTTO":
        return "otf"
    if head[:4] == b"wOF2":
        return "woff2"
    if head[:4] == b"wOFF":
        return "woff"
    if b"<svg" in data[:512]:
        return "svg"
    if head[:3] == b"GIF":
        return "gif"
    return "bin"


def main() -> int:
    brand = sys.argv[1]
    spec = BRANDS[brand]
    workspace_id = spec["workspace_id"]

    from lumen_api.design_store import HybridRepository
    from lumen_api.fragments.registry import read_web_fragment
    from lumen_api.fragments.refs import fragment_wrapper_class
    from lumen_api.main import (
        api_blob_store,
        api_engine_cache_root,
        brand_kit_asset_manifest,
        brand_kit_font_spec,
    )

    repo = HybridRepository(workspace_id)
    blobs = api_blob_store(workspace_id)
    cache = str(api_engine_cache_root(workspace_id))

    data_dir = SPIKE / "data" / "brands" / brand
    public_dir = SPIKE / "public" / "brands" / brand
    (public_dir / "assets").mkdir(parents=True, exist_ok=True)
    (public_dir / "fonts").mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, str] = {}

    def copy_bytes(digest: str, folder: str) -> str | None:
        """Copy one stored byte object; return its public URL, or None if it is not held."""
        if digest in copied:
            return copied[digest]
        try:
            media_type, data = blobs.read_blob(digest)
        except Exception as error:  # a missing byte is reported, not invented
            print(f"  missing bytes {digest[:12]}: {error}")
            return None
        ext = EXTENSIONS.get((media_type or "").split(";")[0].strip()) or sniff(data)
        target = public_dir / folder / f"{digest}.{ext}"
        target.write_bytes(data)
        url = f"/brands/{brand}/{folder}/{digest}.{ext}"
        copied[digest] = url
        return url

    def rewrite(text: str) -> str:
        def swap(match: re.Match[str]) -> str:
            url = copy_bytes(match.group(1), "assets")
            return url or match.group(0)

        return ASSET_REF.sub(swap, text)

    # Kit.
    record = repo.require_brand_kit(spec["kit_id"], spec["kit_version"])
    kit = record["brand_kit"]
    (data_dir / "kit.json").write_text(json.dumps(kit, indent=2))

    # Fonts.
    font_spec = brand_kit_font_spec(repo, kit, blobs, cache) or {}
    fonts = []
    for face in font_spec.get("faces") or []:
        url = copy_bytes(face["digest"], "fonts")
        if url:
            fonts.append({
                "family": face["family"],
                "weight": face.get("weight"),
                "style": face.get("style") or "normal",
                "file": url,
            })
    (data_dir / "fonts.json").write_text(json.dumps(fonts, indent=2))

    # Kit logos and images.
    manifest = brand_kit_asset_manifest(repo, kit, blobs, cache) or {}
    assets = {}
    for asset_id, entry in manifest.items():
        rec = entry.get("record") or {}
        media = rec.get("media") or {}
        digest = (media.get("digest") or {}).get("value")
        url = copy_bytes(digest, "assets") if digest else None
        if not url:
            continue
        assets[asset_id] = {
            "kind": rec.get("kind"),
            "logo": rec.get("logo"),
            "label": rec.get("label"),
            "tags": rec.get("tags"),
            "description": entry.get("description") or rec.get("description"),
            "mime": media.get("mime_type"),
            "width": media.get("width"),
            "height": media.get("height"),
            "file": url,
        }
    (data_dir / "assets.json").write_text(json.dumps(assets, indent=2))

    # Clones: approved originals of this kit version, captured from the seller's site.
    rows = [
        row for row in repo.list_web_fragments()
        if row.get("status") == "approved"
        and not row.get("derived_from")
        and row.get("source_kit_version") == spec["kit_version"]
        and str(row.get("source_url") or "").startswith("http")
        and row.get("section_role") not in SKIP_ROLES
        and not any(skip in str(row.get("label") or "") for skip in SKIP_LABELS)
    ]

    def order(row: dict) -> tuple:
        provenance = row.get("provenance_json") or row.get("provenance") or {}
        return (str(row.get("source_url")), int(provenance.get("section_index") or 0))

    clones = []
    for row in sorted(rows, key=order):
        fragment_id = str(row["fragment_id"])
        loaded = read_web_fragment(blobs.storage, workspace_id=workspace_id, fragment_id=fragment_id)
        provenance = loaded.row.get("provenance") if isinstance(loaded.row.get("provenance"), dict) else {}
        slots = {
            key: {"kind": entry.get("kind"), "fallback": entry.get("fallback")}
            for key, entry in (loaded.slot_manifest or {}).items()
            if isinstance(entry, dict)
        }
        clones.append({
            "id": fragment_id,
            "role": row.get("section_role"),
            "label": row.get("label"),
            "page_url": row.get("source_url"),
            "section_index": provenance.get("section_index"),
            "wrapper_class": fragment_wrapper_class(fragment_id),
            "html": rewrite(loaded.html),
            "css": rewrite(loaded.css),
            "slots": slots,
            "native_dependencies": loaded.payload.get("native_dependencies"),
            "viewport_width": provenance.get("viewport_width"),
        })
        print(f"  clone {fragment_id} {row.get('section_role'):12} slots={len(slots):2} "
              f"html={len(loaded.html):6} css={len(loaded.css):7} {str(row.get('label'))[:50]}")
    (data_dir / "clones.json").write_text(json.dumps(clones, indent=2))

    print(f"{brand}: {len(clones)} clones, {len(fonts)} font faces, {len(assets)} kit assets, "
          f"{len(copied)} files copied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
