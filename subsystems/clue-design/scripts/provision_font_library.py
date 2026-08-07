#!/usr/bin/env python
"""Provision the curated open-font library into this environment.

Materializes the ~27 curated Google-Fonts families (static instances per
curated weight) into the content-addressed asset store + SQLite asset records,
and regenerates the checked-in manifest `apps/api/font-library/manifest.json`.

Run from the repo root with the API venv:

    PYTHONPATH=apps/api .venv/bin/python scripts/provision_font_library.py \
        --fonts-repo .context/google-fonts

The fonts repo is a sparse clone of github.com/google/fonts pinned to the
commit recorded in the manifest provenance. Deterministic: same commit + same
fontTools version => identical bytes/digests => idempotent re-runs (the asset
store dedups by digest; records upsert by asset_id).

Modes:
  (default)   materialize everything + rewrite the manifest
  --check     verify the environment matches the checked-in manifest (digest
              drift, missing store bytes, missing records) — no writes
  --families  comma-separated slugs to (re)provision a subset
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from py_lumen_config import settings  # noqa: E402
from lumen_api.core import CoreClient  # noqa: E402
from lumen_api.database import Repository, connect, run_migrations  # noqa: E402
from lumen_ingestion.font_library import (  # noqa: E402
    CURATED_FAMILIES,
    FontLibraryError,
    build_manifest,
    materialize_family,
    provision_family,
    write_agent_inventory,
    write_manifest,
)
from lumen_ingestion.normalizer.font_metrics import extract_font_metrics  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "apps" / "api" / "font-library" / "manifest.json"
AGENT_INVENTORY_DOC = (
    REPO_ROOT
    / "apps"
    / "agent_runtime"
    / "knowledge_docs"
    / "knowledge"
    / "design"
    / "font-library.md"
)


def fonts_repo_commit(fonts_repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(fonts_repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def check_environment(manifest_path: Path, store_root: Path, database_path: Path) -> int:
    import json

    from lumen_api.database import NotFoundError

    manifest = json.loads(manifest_path.read_text())
    connection = connect(database_path)
    repo = Repository(connection)
    problems: list[str] = []
    try:
        for family in manifest["families"]:
            for face in family["faces"]:
                digest = face["digest"]
                blob = store_root / "sha256" / digest[:2] / digest
                if not blob.is_file():
                    problems.append(f"{family['slug']} w{face['weight']}: store bytes missing ({blob})")
                try:
                    repo.require_asset_record(face["asset_id"])
                except NotFoundError:
                    problems.append(f"{family['slug']} w{face['weight']}: asset record missing ({face['asset_id']})")
    finally:
        connection.close()
    if problems:
        print(f"FONT LIBRARY CHECK FAILED — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        print("Run scripts/provision_font_library.py to materialize this environment.")
        return 1
    total = sum(len(f["faces"]) for f in manifest["families"])
    print(f"FONT LIBRARY OK — {len(manifest['families'])} families / {total} faces present.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonts-repo", type=Path, default=REPO_ROOT / ".context" / "google-fonts")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--families", type=str, default=None, help="comma-separated slugs subset")
    parser.add_argument("--check", action="store_true", help="verify env against manifest; no writes")
    args = parser.parse_args()

    database_path = args.database or settings.lumen_api_database_path
    store_root = args.store_root or (
        settings.lumen_asset_store_root or database_path.parent / "asset-store"
    )

    if args.check:
        return check_environment(args.manifest, Path(store_root), database_path)

    if not args.fonts_repo.is_dir():
        print(
            f"fonts repo not found at {args.fonts_repo} — sparse-clone it first:\n"
            "  git clone --depth 1 --filter=blob:none --sparse "
            "https://github.com/google/fonts.git <dest>\n"
            "  git -C <dest> sparse-checkout set ofl/<family> ..."
        )
        return 1

    import fontTools

    commit = fonts_repo_commit(args.fonts_repo)
    selected = CURATED_FAMILIES
    if args.families:
        wanted = {slug.strip() for slug in args.families.split(",") if slug.strip()}
        unknown = wanted - {f.slug for f in CURATED_FAMILIES}
        if unknown:
            print(f"unknown family slugs: {', '.join(sorted(unknown))}")
            return 1
        selected = [f for f in CURATED_FAMILIES if f.slug in wanted]

    run_migrations(database_path)
    connection = connect(database_path)
    repo = Repository(connection)
    core = CoreClient()
    entries = []
    try:
        for curated in selected:
            print(f"[{curated.slug}] materializing {len(curated.weights)} face(s)...")
            faces, coverage = materialize_family(args.fonts_repo, curated)
            metrics = extract_font_metrics(faces[0].bytes_)
            entry = provision_family(
                curated,
                faces,
                coverage,
                metrics,
                ingest=core.ingest_asset,
                create_record=repo.create_asset_record,
                store_root=str(store_root),
                google_fonts_commit=commit,
            )
            total_kb = sum(f["byte_length"] for f in entry["faces"]) // 1024
            print(f"[{curated.slug}] ok — {len(entry['faces'])} faces, {total_kb} KiB")
            entries.append(entry)
    except FontLibraryError as error:
        print(f"PROVISIONING FAILED: {error}")
        return 1
    finally:
        connection.close()

    if args.families:
        # Subset run: merge into the existing manifest instead of truncating it.
        import json

        existing = (
            json.loads(args.manifest.read_text()) if args.manifest.is_file() else None
        )
        if existing and existing.get("families"):
            merged = {f["slug"]: f for f in existing["families"]}
            for entry in entries:
                merged[entry["slug"]] = entry
            order = [f.slug for f in CURATED_FAMILIES]
            entries = sorted(
                merged.values(),
                key=lambda f: order.index(f["slug"]) if f["slug"] in order else 999,
            )

    manifest = build_manifest(entries, commit, fontTools.version)
    write_manifest(manifest, args.manifest)
    write_agent_inventory(manifest, AGENT_INVENTORY_DOC)
    total = sum(len(f["faces"]) for f in entries)
    print(f"MANIFEST WRITTEN — {len(entries)} families / {total} faces -> {args.manifest}")
    print(f"AGENT INVENTORY WRITTEN -> {AGENT_INVENTORY_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
