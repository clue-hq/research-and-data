"""One-time migration: flatten ``@layer`` structure out of already-stored fragment payloads.

Fragments minted BEFORE the 2026-08-29 capture-time flattening ruling carry their source site's
cascade layers in stored CSS, which the editor render demotes below Tailwind's preflight reset
(the left-skew / collapsed-typography bug; root cause in
``_memory/2026-08-29-clone-assembly-layer-cascade-bug.md``). New captures are flattened at the
scope door (``lumen_api.fragments.cssflatten``); this script brings existing rows up to the same
contract so they don't have to be re-ingested.

Reversible by construction: the OLD payload blob is content-addressed and is NOT deleted — the
row's ``provenance_json`` records ``layer_flatten.previous_payload_digest``, so pointing the row
back is one UPDATE. Idempotent: a payload without ``@layer`` (including every already-migrated
one) is skipped.

The ``design_web_fragment_no_content_update`` trigger (rightly) refuses application-path edits
to a fragment's content, so ``--apply`` disables that ONE trigger inside its own transaction and
re-enables it before commit. That is the sanctioned shape for a deliberate one-time data
transform: the trigger exists to stop code from silently mutating captures, not to stop an
operator running a recorded, provenance-stamped migration. Everything happens in a single
transaction — an error re-raises with the trigger back in force and nothing half-written.

Usage (repo root, env carrying CLUE_DATABASE_URL + CLUE_STORAGE_FS_ROOT):

    .venv/bin/python subsystems/clue-design/scripts/flatten_stored_fragments.py           # dry run
    .venv/bin/python subsystems/clue-design/scripts/flatten_stored_fragments.py --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent / "apps/api"))

from lumen_api.fragments.cssflatten import flatten_css_layers  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write blobs and update rows")
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
    migrated = skipped = missing = 0
    with psycopg.connect(dsn) as conn:
        if args.apply:
            conn.execute(
                "ALTER TABLE design_web_fragment"
                " DISABLE TRIGGER design_web_fragment_no_content_update"
            )
        rows = conn.execute(
            "SELECT fragment_id, workspace_id, payload_digest, provenance_json"
            " FROM design_web_fragment ORDER BY created_at"
        ).fetchall()
        for fragment_id, workspace_id, payload_digest, provenance in rows:
            blob_path = Path(storage_root) / workspace_id / "design" / payload_digest
            if not blob_path.is_file():
                print(f"MISSING BLOB {fragment_id}: {payload_digest} — left untouched")
                missing += 1
                continue
            payload = json.loads(blob_path.read_text(encoding="utf-8"))
            css = str(payload.get("css") or "")
            if "@layer" not in css:
                skipped += 1
                continue
            notes: list[str] = []
            payload["css"] = flatten_css_layers(css, notes=notes)
            if not notes:
                # `@layer` appeared only in a string/comment — structurally nothing changed.
                skipped += 1
                continue
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            new_digest = hashlib.sha256(raw).hexdigest()
            print(f"{fragment_id}: {payload_digest[:12]} -> {new_digest[:12]}  ({notes[0]})")
            if args.apply:
                new_path = blob_path.with_name(new_digest)
                if not new_path.exists():
                    new_path.write_bytes(raw)
                    new_path.chmod(0o600)
                prov = dict(provenance or {})
                prov["layer_flatten"] = {
                    "previous_payload_digest": payload_digest,
                    "note": notes[0],
                    "migrated": "2026-08-29",
                }
                conn.execute(
                    "UPDATE design_web_fragment SET payload_digest = %s,"
                    " provenance_json = %s, updated_at = now()"
                    " WHERE fragment_id = %s AND workspace_id = %s",
                    (new_digest, json.dumps(prov), fragment_id, workspace_id),
                )
            migrated += 1
        if args.apply:
            conn.execute(
                "ALTER TABLE design_web_fragment"
                " ENABLE TRIGGER design_web_fragment_no_content_update"
            )
            conn.commit()

    mode = "applied" if args.apply else "dry run — nothing written"
    print(f"{mode}: {migrated} flattened, {skipped} already clean, {missing} missing blobs")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
