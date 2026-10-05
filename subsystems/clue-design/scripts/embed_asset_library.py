"""Backfill CLIP image vectors for existing asset libraries (hybrid asset search, 2026-10-05).

New ingestions embed every asset as part of enrichment; this covers libraries ingested before.
Each asset is embedded from the same preview enrichment builds (`_downscale_preview` of the
original, or of the stored raster thumbnail for an SVG), so a later enrichment finds the vector
current and does not redo it.

Dry run by default: reports what it would embed. `--apply` writes.

usage (repo root, lane .env sourced):
  .venv/bin/python subsystems/clue-design/scripts/embed_asset_library.py --workspace ws_... [--apply]
  .venv/bin/python subsystems/clue-design/scripts/embed_asset_library.py --all [--apply]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def asset_rows(workspace_id: str) -> list[dict]:
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    async def read(conn):
        rows = await conn.execute(text(
            "SELECT asset_id, mime_type, digest_value, record_json FROM design_asset "
            "WHERE workspace_id = :w AND status <> 'archived' AND mime_type LIKE 'image/%'"),
            {"w": workspace_id})
        return [dict(r._mapping) for r in rows]

    return DesignStoreBridge(workspace_id)._run(read)


def workspaces() -> list[str]:
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    async def read(conn):
        rows = await conn.execute(text("SELECT DISTINCT workspace_id FROM design_asset ORDER BY 1"))
        return [r.workspace_id for r in rows]

    return DesignStoreBridge("ws_backfill_probe", ensure_workspace=False)._run(read)


def preview_for(asset_id: str, resolvers: tuple) -> tuple[str | None, str]:
    """(base64 preview, reason): exactly enrichment's preview — same resolvers, same SVG path."""
    from lumen_ingestion.describe import _downscale_preview, _vector_raster

    resolve_bytes, resolve_thumbnail, rasterize_svg = resolvers
    try:
        resolved = resolve_bytes(asset_id)
    except Exception as error:  # noqa: BLE001
        return None, f"bytes unreadable ({type(error).__name__})"
    if resolved is None:
        return None, "original bytes unavailable"
    data, mime = resolved
    if mime == "image/svg+xml":
        data = _vector_raster(asset_id, resolve_thumbnail, rasterize_svg)
        if not data:
            return None, "svg with no raster"
    preview = _downscale_preview(data)
    return (preview, "ok") if preview else (None, "no raster preview")


def run(workspace_id: str, apply: bool) -> dict:
    from clue_storage import storage_from_settings

    from lumen_api import asset_embeddings
    from lumen_api.design_store import DesignBlobStore, HybridRepository
    from lumen_api.main import api_engine_cache_root
    from lumen_ingestion.asset_enrichment import EnrichmentStore, embed_preview
    from lumen_ingestion.pipeline import (
        _make_rasterize_svg,
        _make_resolve_bytes,
        _make_resolve_thumbnail_bytes,
    )

    blobs = DesignBlobStore(storage_from_settings(), workspace_id)
    repo = HybridRepository(workspace_id=workspace_id)
    resolvers = (_make_resolve_bytes(repo, blobs), _make_resolve_thumbnail_bytes(repo, blobs),
                 _make_rasterize_svg(repo, blobs, str(api_engine_cache_root(workspace_id))))
    store = EnrichmentStore(workspace_id)
    space = asset_embeddings.model_info().space
    counts: dict[str, int] = {}
    started = time.time()
    for row in asset_rows(workspace_id):
        preview, reason = preview_for(row["asset_id"], resolvers)
        if preview is None:
            counts[f"skipped: {reason}"] = counts.get(f"skipped: {reason}", 0) + 1
            continue
        digest = hashlib.sha256(base64.b64decode(preview)).hexdigest()
        if not apply:
            current = store.embedding_digest(row["asset_id"], space) == digest
            key = "current" if current else "would embed"
        else:
            key = embed_preview(store, row["asset_id"], preview, digest)
        counts[key] = counts.get(key, 0) + 1
    counts["seconds"] = round(time.time() - started, 1)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--workspace")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true", help="write vectors (default: dry run)")
    opts = parser.parse_args()
    from lumen_api.asset_embeddings import EmbeddingUnavailable, model_info

    try:
        info = model_info()
    except EmbeddingUnavailable as error:
        raise SystemExit(f"visual search is unavailable here: {error}")
    print(f"model space {info.space} from {info.directory}; {'APPLY' if opts.apply else 'dry run'}")
    for workspace_id in (workspaces() if opts.all else [opts.workspace]):
        print(workspace_id, run(workspace_id, opts.apply), flush=True)


if __name__ == "__main__":
    main()
