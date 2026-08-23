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
from lumen_api.design_store import (  # noqa: E402
    HybridRepository,
    default_workspace_id,
)
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


def _blob_store(workspace_id: str):
    """The design byte store for the provisioning tenant (D4)."""
    from clue_storage import storage_from_settings
    from lumen_api.design_store import DesignBlobStore

    return DesignBlobStore(storage_from_settings(), workspace_id)


def fonts_repo_commit(fonts_repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(fonts_repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def check_environment(manifest_path: Path, workspace_id: str) -> int:
    import json

    from lumen_api.database import NotFoundError

    manifest = json.loads(manifest_path.read_text())
    # D2.5B: the store is Postgres via clue_design. D4: the face BYTES live in platform storage
    # (a cache file proves nothing — it can be wiped at any moment), so the check asks the
    # durable seam, not the filesystem.
    repo = HybridRepository(workspace_id)
    blobs = _blob_store(workspace_id)
    problems: list[str] = []
    for family in manifest["families"]:
        for face in family["faces"]:
            digest = face["digest"]
            # `has_readable_bytes`, not `exists`: a row is a CLAIM of custody, and this is a
            # VERIFIER. Under the row/blob divergence the genad2 walk found (2026-08-23) the
            # row-only probe reported the font library healthy while every face 404'd, which is
            # the one failure a check script must never miss.
            if not blobs.has_readable_bytes(digest):
                problems.append(
                    f"{family['slug']} w{face['weight']}: durable bytes missing ({digest})"
                )
            try:
                repo.require_asset_record(face["asset_id"])
            except NotFoundError:
                problems.append(f"{family['slug']} w{face['weight']}: asset record missing ({face['asset_id']})")
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
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="tenant that owns the provisioned faces (default: the dev workspace)",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=None,
        help="engine materialization cache root (default: LUMEN_ASSET_STORE_ROOT)",
    )
    parser.add_argument("--families", type=str, default=None, help="comma-separated slugs subset")
    parser.add_argument("--check", action="store_true", help="verify env against manifest; no writes")
    args = parser.parse_args()

    # D4: the font library is one shared, openly-licensed set, so it is provisioned into ONE
    # workspace's durable storage (see `lumen_api.font_library.library_workspace_id`, which
    # reads the same default). The cache dir is that workspace's engine cache — a mirror the
    # engine ingests through, not the store.
    workspace_id = args.workspace or default_workspace_id()
    cache_root = args.cache_root or settings.effective_asset_store_root
    cache_dir = Path(cache_root) / workspace_id

    if args.check:
        return check_environment(args.manifest, workspace_id)

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

    repo = HybridRepository(workspace_id)
    blobs = _blob_store(workspace_id)
    core = CoreClient()
    cache_dir.mkdir(parents=True, exist_ok=True)
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
                blobs=blobs,
                cache_dir=str(cache_dir),
                google_fonts_commit=commit,
            )
            total_kb = sum(f["byte_length"] for f in entry["faces"]) // 1024
            print(f"[{curated.slug}] ok — {len(entry['faces'])} faces, {total_kb} KiB")
            entries.append(entry)
    except FontLibraryError as error:
        print(f"PROVISIONING FAILED: {error}")
        return 1

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
