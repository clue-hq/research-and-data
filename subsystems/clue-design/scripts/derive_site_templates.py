#!/usr/bin/env python
"""Derive a workspace's site header and footer templates from its stored captures (site element
inspector, plan 6), for brand kits extracted before templates were made at extraction.

No extraction runs: the templates come from the kit's captured ``nav`` and ``footer`` fragments
already in the database and blob store. Dry run by default: prints the band each template would be
derived from, its slots and notes, and (with --preview-dir) writes ``<role>.html`` previews of the
derived markup with the captured CSS. --apply mints the templates and releases them (no approval gate).

    set -a; source .env; set +a
    .venv/bin/python subsystems/clue-design/scripts/derive_site_templates.py --workspace WS [--kit KIT] [--preview-dir DIR]
    .venv/bin/python subsystems/clue-design/scripts/derive_site_templates.py --workspace WS --apply

Run from the repo root with PYTHONPATH=subsystems/clue-design:subsystems/clue-design/apps/api:subsystems/clue-design/apps/agent_runtime.
Needs CLUE_DATABASE_URL and the storage settings the design API uses (CLUE_STORAGE_FS_ROOT locally).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from html import escape
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", required=True, help="the workspace whose kit to derive from")
    parser.add_argument("--kit", help="a brand kit id (default: the workspace's newest kit)")
    parser.add_argument("--preview-dir", type=Path, help="write <role>.html previews here")
    parser.add_argument("--apply", action="store_true", help="mint and release the templates")
    args = parser.parse_args(argv)

    from clue_storage import storage_from_settings

    from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
    from lumen_api.design_store import DesignBlobStore, HybridRepository
    from lumen_api.fragments import read_web_fragment
    from lumen_api.fragments.site_templates import TemplateNotDerivable, derive_site_template

    blobs = DesignBlobStore(storage_from_settings(), args.workspace)
    registry = DurableAgentClonedSectionRegistry(blobs=blobs, cache_dir=tempfile.gettempdir())
    kits = HybridRepository(args.workspace).list_brand_kits(all_versions=True)
    chosen = [kit for kit in kits if not args.kit or kit.get("brand_kit_id") == args.kit]
    if not chosen:
        print(f"no brand kit {args.kit or ''} in {args.workspace}", file=sys.stderr)
        return 1
    # The newest kit version whose capture minted bands: a later version made by a re-measure (type
    # units, responsive steps) re-uses the bands of the capture before it.
    kit_id, version = "", 0
    for kit in sorted(chosen, key=lambda row: (str(row.get("brand_kit_id")), int(row.get("version") or 0)), reverse=True):
        sources = registry.site_template_sources(kit_id=str(kit["brand_kit_id"]), kit_version=int(kit["version"]))
        if any(sources.values()):
            kit_id, version = str(kit["brand_kit_id"]), int(kit["version"])
            break
    if not kit_id:
        print("no kit version of this workspace has captured nav or footer bands", file=sys.stderr)
        return 1
    print(f"kit {kit_id} v{version} (the newest version with captured bands)")

    if args.apply:
        for result in registry.mint_site_templates(kit_id=kit_id, kit_version=version):
            print(f"  {result['role']}: " + (f"skipped ({result['skipped']})" if result.get("skipped") else f"{result['fragment_id']} {result['status']} — {result['label']}"))
        return 0

    for role, source in registry.site_template_sources(kit_id=kit_id, kit_version=version).items():
        if source is None:
            print(f"  {role}: no usable captured band")
            continue
        loaded = read_web_fragment(blobs.storage, workspace_id=args.workspace, fragment_id=str(source["fragment_id"]))
        try:
            derived = derive_site_template(role, loaded.html, placeholder_src="/asset-store/" + "0" * 64,
                                           seller_logo_src=registry._kit_logo_file(kit_id, version))
        except TemplateNotDerivable as error:
            print(f"  {role}: from {source['fragment_id']} — not derivable ({error.reason})")
            continue
        print(f"  {role}: from {source['fragment_id']} ({source.get('label')})")
        print(f"    slots: {', '.join(f'{spec.key} ({spec.kind})' for spec in derived.slots)}")
        for note in derived.notes:
            print(f"    note: {note}")
        if args.preview_dir:
            args.preview_dir.mkdir(parents=True, exist_ok=True)
            wrapper = "lumen-frag-" + str(source["fragment_id"]).removeprefix("frag_")
            css = f"{loaded.css}\n{derived.css_addition.replace('.clue-', f'.{wrapper} .clue-')}"
            page = f"<!doctype html><meta charset=utf-8><title>{escape(role)}</title><style>{css}</style><div class=\"{wrapper}\">{derived.html}</div>"
            (args.preview_dir / f"{role}.html").write_text(page)
            print(f"    preview: {args.preview_dir / f'{role}.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
