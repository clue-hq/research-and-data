"""One-off run: ingest cursor.com through the brandkit pipeline, dump everything to files.

Run from apps/api:  ../../.venv/bin/python ../../.context/cursor-design/run_cursor_ingest.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path

logging.disable(logging.INFO)
API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from lumen_api.core import CoreClient  # noqa: E402
from lumen_ingestion.capture import capture_website  # noqa: E402
from lumen_ingestion.capture.evidence_builder import build_evidence  # noqa: E402
from lumen_ingestion.evidence import BrandEvidence  # noqa: E402
from lumen_ingestion.normalizer import normalize_evidence  # noqa: E402
from lumen_ingestion.normalizer.cluster import cluster_colors  # noqa: E402

# ---------------------------------------------------------------------------
# Runner-local monkeypatches (per task rules: never edit the shipped package).
#
# cursor.com's /about page has a cyclic CSS custom-property reference
# (var(--a) -> ... -> var(--a)). The shipped parse_color_value() resolves var()
# hops recursively with no cycle guard, so it blows the Python recursion limit
# and sinks the whole run. We wrap it to bound var-resolution depth: a chain
# deeper than 24 hops is a cycle, so we bail to None (a colour we simply skip).
# Behaviour is identical for every non-cyclic value.
# ---------------------------------------------------------------------------
import lumen_ingestion.capture.parse as _parse_mod  # noqa: E402

_orig_parse_color_value = _parse_mod.parse_color_value
_MAX_VAR_HOPS = 24


def _guarded_parse_color_value(raw, custom_props, _depth=0):
    if _depth > _MAX_VAR_HOPS:
        return None
    text = str(raw).strip()
    m = re.match(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)", text, re.IGNORECASE)
    if m:
        name = m.group(1)
        resolved = custom_props.get(name)
        if resolved is None:
            fallback = m.group(2)
            if fallback is None:
                return None
            return _guarded_parse_color_value(fallback, custom_props, _depth + 1)
        return _guarded_parse_color_value(resolved, custom_props, _depth + 1)
    return _orig_parse_color_value(text, custom_props)


_parse_mod.parse_color_value = _guarded_parse_color_value

# cursor.com also emits Tailwind colours whose alpha channel is itself a var(),
# e.g. `rgba(24 24 27 / var(--tw-text-opacity))`. The shipped _parse_alpha()
# does float(token) and dies on the var() token. We wrap it to treat any
# non-numeric alpha as fully opaque (255) — CSS default when the var is unset.
_orig_parse_alpha = _parse_mod._parse_alpha


def _guarded_parse_alpha(token):
    try:
        return _orig_parse_alpha(token)
    except (ValueError, TypeError):
        return 255


_parse_mod._parse_alpha = _guarded_parse_alpha

DESIGN = Path(__file__).resolve().parents[1]
OUT = DESIGN / "research"
ASSETS = DESIGN / "assets"
TOKENS = DESIGN / "tokens"
STORE_ROOT = OUT / "asset-store"
PAGES = [
    "https://cursor.com",
    "https://cursor.com/pricing",
    "https://cursor.com/enterprise",
    "https://cursor.com/students",
    "https://cursor.com/blog",
]


def reporter(stage: str, progress: float) -> None:
    print(f"  [{progress:4.0%}] {stage}", flush=True)


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "asset"


def dump_downloads(snapshot, page_slug: str) -> list[dict]:
    index = []
    for entry in snapshot.downloads:
        kind_dir = ASSETS / f"{entry.kind}s"
        kind_dir.mkdir(parents=True, exist_ok=True)
        base = sanitize(Path(entry.url.split("?")[0]).name) if entry.url else "inline"
        fname = f"{entry.sha256[:12]}_{base}"
        if "." not in base:
            ext = {
                "font": ".woff2", "image": ".png", "logo": ".svg",
                "screenshot": ".png", "og_image": ".png",
            }.get(entry.kind, ".bin")
            fname += ext
        path = kind_dir / fname
        path.write_bytes(base64.b64decode(entry.bytes_b64))
        index.append({
            "file": str(path.relative_to(DESIGN)),
            "kind": entry.kind,
            "url": entry.url,
            "sha256": entry.sha256,
            "content_type": entry.content_type,
            "page": page_slug,
            "bytes": path.stat().st_size,
        })
    return index


def merge_evidence(bundles: list[BrandEvidence]) -> BrandEvidence:
    head = bundles[0]
    merged = head.model_copy(deep=True)
    seen_logos = {l.asset_id for l in merged.logos}
    seen_images = {i.asset_id for i in merged.images}
    seen_fonts = {(f.family, tuple(sorted(ff.source_url or "" for ff in f.faces))) for f in merged.fonts}
    for b in bundles[1:]:
        merged.colors.extend(b.colors)
        merged.type_samples.extend(b.type_samples)
        merged.numbers.extend(b.numbers)
        merged.shadows.extend(b.shadows)
        merged.rules.extend(b.rules)
        merged.screenshots.extend(s for s in b.screenshots if s not in merged.screenshots)
        for f in b.fonts:
            key = (f.family, tuple(sorted(ff.source_url or "" for ff in f.faces)))
            if key not in seen_fonts:
                seen_fonts.add(key)
                merged.fonts.append(f)
        for l in b.logos:
            if l.asset_id not in seen_logos:
                seen_logos.add(l.asset_id)
                merged.logos.append(l)
        for i in b.images:
            if i.asset_id not in seen_images:
                seen_images.add(i.asset_id)
                merged.images.append(i)
    return merged


async def capture_all() -> tuple[list, list[dict]]:
    outcomes, asset_index = [], []
    for url in PAGES:
        slug = url.replace("https://cursor.com", "") or "/"
        print(f"capturing {url} (rendered)…", flush=True)
        try:
            outcome = await capture_website(url, reporter=reporter, force_render=True)
        except Exception as err:  # noqa: BLE001 — a 404/blocked page must not sink the run
            print(f"  !! {url} failed: {err}", flush=True)
            continue
        outcomes.append((slug, outcome))
        asset_index.extend(dump_downloads(outcome.snapshot, slug))
        (OUT / "snapshots").mkdir(exist_ok=True)
        (OUT / "snapshots" / f"{sanitize(slug.strip('/') or 'landing')}.json").write_text(
            outcome.snapshot.model_dump_json()
        )
    return outcomes, asset_index


def main() -> None:
    for d in (OUT, ASSETS, TOKENS, STORE_ROOT, OUT / "snapshots"):
        d.mkdir(parents=True, exist_ok=True)
    outcomes, asset_index = asyncio.run(capture_all())
    if not outcomes:
        raise SystemExit("no page captured")

    core = CoreClient()
    bundles = []
    for slug, outcome in outcomes:
        print(f"building evidence for {slug}…", flush=True)
        bundles.append(build_evidence(outcome, core=core, store_root=str(STORE_ROOT), reporter=reporter))
    evidence = merge_evidence(bundles)

    print("normalizing…", flush=True)
    result = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_cursor",
        name="Cursor",
        created_at=date.today().isoformat(),
        version=1,
    )
    validation = core.validate_brand_kit(result.brand_kit, product_ready=False, raise_on_error=False)
    print("validate ok:", validation.get("ok"), flush=True)

    clusters = cluster_colors(evidence.colors)
    (OUT / "evidence.json").write_text(json.dumps(evidence.model_dump(), indent=1, sort_keys=True))
    (OUT / "ingestion-report.json").write_text(json.dumps(result.ingestion_report, indent=1, sort_keys=True))
    (TOKENS / "cursor-brand-kit.json").write_text(json.dumps(result.brand_kit, indent=1, sort_keys=True))
    (OUT / "asset-index.json").write_text(json.dumps(asset_index, indent=1))
    (OUT / "diagnostics.json").write_text(json.dumps(
        result.diagnostics + [d for _, o in outcomes for d in o.diagnostics], indent=1))

    # ---- the detailed tokens YAML -------------------------------------------
    import yaml

    kit = result.brand_kit

    def flat_colors(cat: dict) -> dict:
        out = {}
        for path, tok in sorted(cat.items()):
            entry = {"value": tok["value"]["default"].get("value"),
                     "role": tok["role"],
                     "provenance": tok["provenance"]["source"]}
            dark = (tok["value"].get("modes") or {}).get("theme.dark")
            if dark:
                entry["dark"] = dark.get("value")
            if tok.get("description"):
                entry["description"] = tok["description"]
            out[path] = entry
        return out

    def flat_numbers(cat: dict) -> dict:
        return {p: t["value"]["default"].get("value") for p, t in sorted(cat.items())}

    def flat_type(cat: dict) -> dict:
        out = {}
        for path, tok in sorted(cat.items()):
            v = tok["value"]["default"]
            out[path] = {k: v.get(k) for k in
                         ("font_family", "font_size", "font_weight", "line_height", "letter_spacing", "color")}
        return out

    custom_props = {}
    for _, outcome in outcomes:
        for k, v in (outcome.snapshot.custom_props or {}).items():
            custom_props.setdefault(k, v)

    doc = {
        "meta": {
            "brand": "Cursor",
            "source_pages": [u for u in PAGES],
            "captured_at": date.today().isoformat(),
            "pipeline": "lumen brandkit ingestion v1 (rendered tier)",
            "dark_colorway": result.ingestion_report["dark_colorway"],
        },
        "tokens": {
            "colors": flat_colors(kit["tokens"]["colors"]),
            "typography": flat_type(kit["tokens"]["typography"]),
            "spacing": flat_numbers(kit["tokens"]["spacing"]),
            "radii": flat_numbers(kit["tokens"]["radii"]),
            "stroke_widths": flat_numbers(kit["tokens"]["stroke_widths"]),
            "opacity": flat_numbers(kit["tokens"]["opacity"]),
            "aliases": {k: v["token"] for k, v in sorted(kit["tokens"]["aliases"].items())},
        },
        "assets": {
            "fonts": kit["assets"]["fonts"],
            "logos": kit["assets"]["logos"],
            "images": kit["assets"]["images"],
        },
        "constraints": kit["constraints"],
        "raw_evidence": {
            "css_custom_properties": dict(sorted(custom_props.items())),
            "color_clusters_by_weight": [
                {"hex": c.representative, "weight": round(c.weight, 2), "theme": c.theme,
                 "hints": c.role_hints[:6], "name": c.name}
                for c in clusters[:60]
            ],
            "type_samples": [
                {"label": s.label, "family": s.family, "size_px": s.size_px,
                 "weight": s.weight, "line_height": s.line_height,
                 "letter_spacing": s.letter_spacing}
                for s in evidence.type_samples
            ],
            "font_faces": [
                {"family": f.family, "role_hint": f.role_hint, "license_hint": f.license_hint,
                 "faces": [{"weight": ff.weight, "style": ff.style, "url": ff.source_url}
                           for ff in f.faces]}
                for f in evidence.fonts
            ],
            "spacing_radius_samples": [
                {"kind": n.kind, "value": n.value, "hints": n.role_hints}
                for n in evidence.numbers[:80]
            ],
            "narrative": evidence.narrative.model_dump(),
        },
    }
    (TOKENS / "cursor-design-tokens.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110))

    print("\nDONE. Outputs in", OUT)
    print("assets:", len(asset_index), "| clusters:", len(clusters),
          "| fonts:", len(evidence.fonts), "| images:", len(evidence.images),
          "| type samples:", len(evidence.type_samples))


if __name__ == "__main__":
    main()
