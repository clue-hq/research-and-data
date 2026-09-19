"""One-time migration: decode already-stored WOFF/WOFF2 font assets to sfnt (option A).

Fonts ingested BEFORE 2026-09-02 were stored exactly as harvested — 367 WOFF2 and 2 WOFF faces
across 47 workspaces on the dev store — and none of the engines that read stored fonts speaks
WOFF2 (the SVG embedder refused every one of them; CanvasKit in the browser cannot load them;
FreeType on Linux cannot parse them). New ingests are decoded at the chokepoint
(``lumen_api.font_containers`` via ``CoreClient.ingest_asset``); this script brings existing
rows up to the same invariant so they don't have to be re-ingested.

Reversible by construction: the OLD blob is content-addressed and is NOT deleted — the record's
``provenance.notes`` gains ``backfill previous digest sha256:<old>``, so pointing the row back is
one UPDATE. Idempotent: a row whose bytes already sniff as sfnt is skipped (or, when only the
label lies, relabelled), and decoding is byte-deterministic, so re-runs converge.

A design blob is only readable when its CUSTODY ROW exists (the DAL resolves the digest through
the ``artifact`` table before touching bytes), so ``--apply`` writes the row before the file —
the same shape ``flatten_stored_fragments.py`` learned live on 2026-08-29.

Usage (repo root, env carrying CLUE_DATABASE_URL + CLUE_STORAGE_FS_ROOT):
    .venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py            # dry run
    .venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py --apply
    .venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py --workspace ws_x
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psycopg

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent / "apps/api"))

from lumen_api.font_containers import (  # noqa: E402
    SFNT_MIME,
    FontContainerError,
    decode_note,
    decode_web_font,
    sfnt_filename,
    sniff_font_container,
)

WEB_MIMES = ("font/woff2", "font/woff", "application/font-woff2", "application/font-woff")


@dataclass
class Summary:
    decoded: int = 0
    relabelled: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0


def _select_rows(conn, workspace_id: Optional[str]):
    sql = (
        "SELECT asset_id, workspace_id, digest_value, mime_type, filename, record_json"
        " FROM design_asset WHERE kind = 'font' AND mime_type = ANY(%(mimes)s)"
    )
    params: dict = {"mimes": list(WEB_MIMES)}
    if workspace_id:
        sql += " AND workspace_id = %(ws)s"
        params["ws"] = workspace_id
    sql += " ORDER BY workspace_id, asset_id"
    return conn.execute(sql, params).fetchall()


def _mirror_custody_row(conn, *, workspace_id: str, old: str, new: str, media_type: str, size: int):
    conn.execute(
        "INSERT INTO artifact"
        " (storage_key, workspace_id, content_sha256, media_type, size_bytes, source_key)"
        " SELECT %(key)s, workspace_id, %(digest)s, %(media_type)s, %(size)s, source_key"
        " FROM artifact"
        " WHERE content_sha256 = %(old)s AND workspace_id = %(ws)s"
        "   AND NOT EXISTS ("
        "     SELECT 1 FROM artifact"
        "     WHERE content_sha256 = %(digest)s AND workspace_id = %(ws)s)"
        " LIMIT 1",
        {
            "key": f"{workspace_id}/design/{new}",
            "digest": new,
            "media_type": media_type,
            "size": size,
            "old": old,
            "ws": workspace_id,
        },
    )


def _update_row(
    conn,
    *,
    asset_id: str,
    workspace_id: str,
    record: dict,
    mime_type: str,
    digest: str,
    byte_length: int,
    filename: Optional[str],
) -> None:
    conn.execute(
        "UPDATE design_asset SET mime_type = %s, digest_value = %s, byte_length = %s,"
        " filename = %s, record_json = %s, updated_at = now()"
        " WHERE asset_id = %s AND workspace_id = %s",
        (mime_type, digest, byte_length, filename, json.dumps(record), asset_id, workspace_id),
    )


def decode_stored_web_fonts(
    conn,
    storage_root: Path,
    *,
    workspace_id: Optional[str] = None,
    apply: bool = False,
) -> Summary:
    summary = Summary()
    for asset_id, ws, digest, mime_type, filename, record in _select_rows(conn, workspace_id):
        record = dict(record or {})
        blob_path = Path(storage_root) / ws / "design" / str(digest)
        if not digest or not blob_path.is_file():
            print(f"MISSING BLOB {ws}/{asset_id}: {digest} — left untouched")
            summary.missing += 1
            continue
        data = blob_path.read_bytes()
        container = sniff_font_container(data)
        media = dict(record.get("media") or {})
        provenance = dict(record.get("provenance") or {})
        notes = list(provenance.get("notes") or [])

        if container in SFNT_MIME:
            # The bytes are already sfnt; only the label lied. Relabel, keep the digest.
            new_mime = SFNT_MIME[container]
            new_name = sfnt_filename(filename, container)
            print(f"RELABEL {ws}/{asset_id}: {mime_type} -> {new_mime} (bytes already sfnt)")
            if apply:
                media["mime_type"] = new_mime
                media["filename"] = new_name
                notes.append(
                    f"backfill relabelled {mime_type} -> {new_mime};"
                    " bytes were already sfnt"
                )
                provenance["notes"] = notes
                record["media"], record["provenance"] = media, provenance
                _update_row(
                    conn,
                    asset_id=asset_id,
                    workspace_id=ws,
                    record=record,
                    mime_type=new_mime,
                    digest=digest,
                    byte_length=len(data),
                    filename=new_name,
                )
            summary.relabelled += 1
            continue

        try:
            decoded = decode_web_font(data)
        except FontContainerError as error:
            print(f"FAILED {ws}/{asset_id}: {error} — left untouched")
            summary.failed += 1
            continue
        if decoded is None:
            print(f"SKIP {ws}/{asset_id}: bytes sniff as {container!r}, not a web font")
            summary.skipped += 1
            continue

        new_digest = hashlib.sha256(decoded.data).hexdigest()
        new_name = sfnt_filename(filename, decoded.container)
        print(
            f"{ws}/{asset_id}: {digest[:12]} ({decoded.source_container},{len(data)}B)"
            f" -> {new_digest[:12]} ({decoded.container},{len(decoded.data)}B)"
        )
        if apply:
            new_path = blob_path.with_name(new_digest)
            _mirror_custody_row(
                conn,
                workspace_id=ws,
                old=digest,
                new=new_digest,
                media_type=decoded.mime_type,
                size=len(decoded.data),
            )
            if not new_path.exists():
                new_path.write_bytes(decoded.data)
                new_path.chmod(0o600)
            media["mime_type"] = decoded.mime_type
            media["digest"] = {"algorithm": "sha256", "value": new_digest}
            media["byte_length"] = len(decoded.data)
            media["filename"] = new_name
            media["location"] = {
                "provider": "clue-storage",
                "opaque_ref": f"{ws}/design/{new_digest}",
                "url": None,
            }
            notes.append(decode_note(decoded))
            notes.append(f"backfill previous digest sha256:{digest}")
            provenance["notes"] = notes
            record["media"], record["provenance"] = media, provenance
            _update_row(
                conn,
                asset_id=asset_id,
                workspace_id=ws,
                record=record,
                mime_type=decoded.mime_type,
                digest=new_digest,
                byte_length=len(decoded.data),
                filename=new_name,
            )
        summary.decoded += 1
    if apply:
        conn.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write blobs and update rows")
    parser.add_argument("--workspace", default=None, help="limit to one workspace id")
    args = parser.parse_args()
    database_url = os.environ.get("CLUE_DATABASE_URL", "")
    storage_root = os.environ.get("CLUE_STORAGE_FS_ROOT", "")
    if not database_url or not storage_root:
        print("CLUE_DATABASE_URL and CLUE_STORAGE_FS_ROOT are required", file=sys.stderr)
        return 2
    if not Path(storage_root).is_absolute():
        print("CLUE_STORAGE_FS_ROOT must be absolute (see .env.example)", file=sys.stderr)
        return 2
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    with psycopg.connect(dsn) as conn:
        summary = decode_stored_web_fonts(
            conn, Path(storage_root), workspace_id=args.workspace, apply=args.apply
        )
    mode = "applied" if args.apply else "dry run — nothing written"
    print(
        f"{mode}: {summary.decoded} decoded, {summary.relabelled} relabelled,"
        f" {summary.skipped} skipped, {summary.missing} missing blobs, {summary.failed} failed"
    )
    return 1 if (summary.missing or summary.failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
