#!/usr/bin/env python
"""Re-measure one brand kit's responsive type (spec docs/superpowers/specs/2026-10-18-responsive-brand-type-design.md §3.5).

Loads the kit's source page in the capture's browser, reads how its type changes with the window,
and builds the kit's ``responsive_type`` section with each step applied to the kit's STORED desktop
sizes (the desktop never changes). Roles the page no longer matches are left out and named.

Dry run by default: prints the section and writes nothing. ``--apply`` publishes it as the kit's
next version (kit versions are immutable), identical to the latest except that section.
``--repin-documents`` then moves what is pinned to the old version onto the new one: sites (their
``theme.brand_kit.version``, saved as one undoable system step) and every document's
``effective_brand_kit_version``. A published site shows the change only after it is republished.

Never run without the founder's yes and a time estimate (standing rule: no extraction runs
without asking).

    set -a; source .env; set +a
    .venv/bin/python subsystems/clue-design/scripts/remeasure_kit_type_steps.py --workspace WS --kit KIT
    .venv/bin/python subsystems/clue-design/scripts/remeasure_kit_type_steps.py --workspace WS --kit KIT --apply --repin-documents
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
from datetime import datetime, timezone

import httpx
import psycopg

from lumen_api.design_store import HybridRepository
from lumen_api.toolbelt.site_documents import REPLACE_SITE
from lumen_ingestion.capture.evidence_builder import type_evidence
from lumen_ingestion.capture.net import BoundedFetcher
from lumen_ingestion.capture.parse import parse_site
from lumen_ingestion.capture.rendered import fetch_rendered
from lumen_ingestion.evidence import BrandEvidence
from lumen_ingestion.normalizer.responsive_type import kit_with_section, remeasured_section
from lumen_ingestion.normalizer.typography import build_type_styles, resolve_anchors
from rederive_kit_type_units import _repin  # noqa: E402 — this script's own directory

DIAGNOSTIC = "LUMI0547"


def source_url(kit: dict) -> str | None:
    """The kit's website source, the page its type was measured on."""
    for source in kit.get("sources") or []:
        if isinstance(source, dict) and source.get("kind") == "website" and source.get("url"):
            return str(source["url"])
    return None


async def capture_type(url: str) -> BrandEvidence:
    """Today's type on the page, read exactly as an ingestion reads it (the same capture and parse)."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=15.0) as client:
        # measure_states: the entry-page passes, the type widths among them.
        snapshot = await fetch_rendered(url, BoundedFetcher(client), lambda *_: None, fetched_at=fetched_at, measure_states=True)
    samples, widths = type_evidence(parse_site(snapshot))
    return BrandEvidence(source={"kind": "website", "url": url, "captured_at": fetched_at}, type_samples=samples, type_widths=widths)


def _repin_sites(repo: HybridRepository, conn, workspace_id: str, kit_id: str, old: int, new: int) -> int:
    rows = conn.execute(
        "SELECT id FROM design_document WHERE workspace_id = %s AND doc_kind = 'site' AND archived_at IS NULL"
        " AND current_scene_json->'theme'->'brand_kit'->>'id' = %s"
        " AND current_scene_json->'theme'->'brand_kit'->>'version' = %s",
        (workspace_id, kit_id, str(old)),
    ).fetchall()
    for (document_id,) in rows:
        document = repo.require_document(document_id)
        site = copy.deepcopy(document["scene"])
        site["theme"]["brand_kit"]["version"] = new
        repo.update_site_document(
            document_id,
            site,
            intent=f"brand kit re-measured (type steps): v{old} -> v{new}",
            checkpoint_label=None,
            operations=[{"kind": REPLACE_SITE, "site": site}],
            inverse_operations=[{"kind": REPLACE_SITE, "site": document["scene"]}],
            actor_kind="system",
            source="system",
            expected_base_version=int(document["current_version"]),
        )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True, help="the kit's workspace id")
    parser.add_argument("--kit", required=True, help="the brand_kit_id to re-measure")
    parser.add_argument("--apply", action="store_true", help="publish the section as the kit's next version")
    parser.add_argument("--repin-documents", action="store_true", help="with --apply: move sites and documents onto the new version")
    args = parser.parse_args()

    repo = HybridRepository(workspace_id=args.workspace)
    row = repo.require_brand_kit(args.kit, None)
    kit, version = row["brand_kit"], int(row["version"])
    url = source_url(kit)
    if url is None:
        print(f"SKIP {args.kit} v{version}: the kit has no website source to measure", file=sys.stderr)
        return 1
    evidence = asyncio.run(capture_type(url))
    section, skipped = remeasured_section(kit, evidence, resolve_anchors, lambda anchors: build_type_styles(anchors)[0])
    if section is None:
        reason = f"no role matches the kit's stored sizes (left out: {', '.join(skipped)})" if skipped else "no narrower width could be measured"
        print(f"SKIP {args.kit} v{version}: {reason} on {url}; nothing published", file=sys.stderr)
        return 1
    print(json.dumps(section, indent=2))
    if skipped:
        print(f"LEFT OUT (drawn as unmeasured): {', '.join(skipped)}")
    if not args.apply:
        return 0
    diagnostics = list(row["diagnostics"] or []) + [
        {"code": DIAGNOSTIC, "severity": "info", "message": f"responsive type re-measured from {url}; left out: {', '.join(skipped) or 'none'}"}
    ]
    published = repo.publish_next_brand_kit_version(
        kit_with_section(kit, section), row["brand_summary"], diagnostics, row["source"], expected_base_version=version
    )
    new_version = int(published["version"])
    print(f"PUB  {args.kit} v{version} -> v{new_version}")
    if args.repin_documents:
        with psycopg.connect(os.environ["CLUE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")) as conn:
            sites = _repin_sites(repo, conn, args.workspace, args.kit, version, new_version)
            documents = _repin(conn, args.workspace, args.kit, version, new_version)
        print(f"PIN  {args.kit}: {sites} site(s), {documents} document(s) v{version} -> v{new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
