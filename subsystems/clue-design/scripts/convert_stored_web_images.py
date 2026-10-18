"""One-time backfill: convert already-stored AVIF/ICO image assets to PNG (2026-10-18).

The engine's sniffer reads PNG, JPEG, GIF, WebP, SVG and PDF only, so an AVIF or ICO ingested
before 2026-10-18 was stored as `application/octet-stream` with no thumbnail: the agent could
not view it and the renderer could not paint it. New ingests are converted at the chokepoint
(``lumen_api.image_containers`` via ``CoreClient.ingest_asset``); this script brings existing
rows up to the same invariant.

Each row is re-ingested through that same chokepoint, so the new record (PNG bytes, pixel
size, thumbnail) is exactly what a fresh ingest would produce, and its bytes get durable
custody through ``register_engine_write`` like any engine write. The asset id, label, tags,
source and license are kept. Reversible by construction: the OLD blob is content-addressed and
is NOT deleted — the record's ``provenance.notes`` gains ``backfill previous digest
sha256:<old>``. Idempotent: a converted row is image/png and is never selected again.

Usage (repo root, env carrying CLUE_DATABASE_URL and the CLUE_STORAGE_* settings):
    .venv/bin/python subsystems/clue-design/scripts/convert_stored_web_images.py            # dry run
    .venv/bin/python subsystems/clue-design/scripts/convert_stored_web_images.py --apply
    .venv/bin/python subsystems/clue-design/scripts/convert_stored_web_images.py --workspace ws_x
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Optional

import psycopg

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_SCRIPTS))
sys.path.insert(0, os.path.join(os.path.dirname(_SCRIPTS), "apps", "api"))

from clue_design.storage import SOURCE_KEY_ASSET  # noqa: E402
from lumen_api.asset_custody import register_engine_write  # noqa: E402
from lumen_api.core import CoreClient  # noqa: E402
from lumen_api.database import NotFoundError  # noqa: E402
from lumen_api.design_store import DesignBlobStore  # noqa: E402
from lumen_api.image_containers import (  # noqa: E402
    ImageContainerError,
    convert_to_png,
    sniff_image_container,
)

#: The MIME labels an AVIF/ICO payload was stored under before the conversion existed.
CANDIDATE_MIMES = (
    "application/octet-stream",
    "image/avif",
    "image/x-icon",
    "image/vnd.microsoft.icon",
)


@dataclass
class Summary:
    converted: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0


def _select_rows(conn, workspace_id: Optional[str]):
    sql = (
        "SELECT asset_id, workspace_id, digest_value, filename, record_json"
        " FROM design_asset WHERE mime_type = ANY(%(mimes)s)"
    )
    params: dict = {"mimes": list(CANDIDATE_MIMES)}
    if workspace_id:
        sql += " AND workspace_id = %(ws)s"
        params["ws"] = workspace_id
    sql += " ORDER BY workspace_id, asset_id"
    return conn.execute(sql, params).fetchall()


def _reingest(
    core: CoreClient, blobs: DesignBlobStore, *, asset_id: str, data: bytes, digest: str,
    filename: Optional[str], record: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Ingest the original bytes again (the chokepoint converts them) and give the result custody."""
    provenance = dict(record.get("provenance") or {})
    provenance["notes"] = [
        *(provenance.get("notes") or []),
        f"backfill previous digest sha256:{digest}",
    ]
    with tempfile.TemporaryDirectory() as cache_dir:
        result = core.ingest_asset(
            store_root=cache_dir,
            bytes_base64=base64.b64encode(data).decode("ascii"),
            asset_id=asset_id,
            label=record.get("label") or asset_id,
            filename=filename,
            kind="raster_image",
            license=record.get("license"),
            provenance=provenance,
            source=record.get("source"),
            tags=record.get("tags"),
            raise_on_error=False,
        )
        if result.get("ok") is False:
            print(f"FAILED {blobs.workspace_id}/{asset_id}: {result.get('error')} — left untouched")
            return None
        new_record = (result.get("asset") or {}).get("record")
        if not new_record:
            print(f"FAILED {blobs.workspace_id}/{asset_id}: the helper returned no record")
            return None
        register_engine_write(blobs, cache_dir, record=new_record, source_key=SOURCE_KEY_ASSET)
    if record.get("status"):
        new_record["status"] = record["status"]
    return new_record


def convert_stored_web_images(
    conn,
    storage,
    *,
    workspace_id: Optional[str] = None,
    apply: bool = False,
    core: Optional[CoreClient] = None,
) -> Summary:
    summary = Summary()
    core = core or CoreClient()
    stores: dict[str, DesignBlobStore] = {}
    for asset_id, ws, digest, filename, record in _select_rows(conn, workspace_id):
        record = dict(record or {})
        blobs = stores.setdefault(ws, DesignBlobStore(storage, ws, ensure_workspace=False))
        try:
            data = blobs.read(str(digest))
        except NotFoundError:
            print(f"MISSING BLOB {ws}/{asset_id}: {digest} — left untouched")
            summary.missing += 1
            continue
        if sniff_image_container(data) is None:
            print(f"SKIP {ws}/{asset_id}: bytes are not AVIF or ICO")
            summary.skipped += 1
            continue
        try:
            converted = convert_to_png(data)
        except ImageContainerError as error:
            print(f"FAILED {ws}/{asset_id}: {error} — left untouched")
            summary.failed += 1
            continue
        assert converted is not None  # the sniff above said AVIF/ICO
        print(
            f"{ws}/{asset_id}: {str(digest)[:12]} ({converted.source_container},{len(data)}B)"
            f" -> png {converted.width}x{converted.height} ({len(converted.data)}B)"
        )
        if apply:
            new_record = _reingest(
                core, blobs, asset_id=asset_id, data=data, digest=str(digest),
                filename=filename, record=record,
            )
            if new_record is None:
                summary.failed += 1
                continue
            media = new_record["media"]
            conn.execute(
                "UPDATE design_asset SET kind = %s, mime_type = %s, digest_value = %s,"
                " byte_length = %s, filename = %s, record_json = %s, updated_at = now()"
                " WHERE asset_id = %s AND workspace_id = %s",
                (
                    new_record["kind"],
                    media["mime_type"],
                    media["digest"]["value"],
                    media["byte_length"],
                    media.get("filename"),
                    json.dumps(new_record),
                    asset_id,
                    ws,
                ),
            )
        summary.converted += 1
    if apply:
        conn.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write blobs and update rows")
    parser.add_argument("--workspace", default=None, help="limit to one workspace id")
    args = parser.parse_args()
    database_url = os.environ.get("CLUE_DATABASE_URL", "")
    if not database_url:
        print("CLUE_DATABASE_URL is required", file=sys.stderr)
        return 2
    from clue_storage import storage_from_settings

    dsn = database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    with psycopg.connect(dsn) as conn:
        summary = convert_stored_web_images(
            conn, storage_from_settings(), workspace_id=args.workspace, apply=args.apply
        )
    mode = "applied" if args.apply else "dry run — nothing written"
    print(
        f"{mode}: {summary.converted} converted, {summary.skipped} skipped,"
        f" {summary.missing} missing blobs, {summary.failed} failed"
    )
    return 1 if (summary.missing or summary.failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
