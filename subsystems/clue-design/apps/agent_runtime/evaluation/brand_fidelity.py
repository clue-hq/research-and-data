"""K4: deterministic brand-fidelity scoring of a design against its Brand Kit.

Scores a final scene (a run's ``final_scene.json`` or an accepted document's
scene) on how faithfully it APPLIES the attached kit — no vision model, no
taste: every axis is a mechanical fact about the scene. The in-loop reviewer
and the 3a imagery judge own the taste axes; this module owns the brand
contract. Works for ANY kit — nothing here is brand-specific.

Axes
----
typography_binding   fraction of text nodes bound to a kit type role via
                     ``style_token`` (the round-2 live baseline was 0/4 — text
                     that merely copies the kit's family detaches silently the
                     moment kit tokens change; LUMB0805 is the in-loop twin).
typography_family    fraction of text nodes whose EFFECTIVE family is a kit
                     family (bound tokens count automatically; literals must
                     match a kit family — catches the hardcoded-Inter subtitle).
palette_adherence    fraction of paints (page backgrounds + node fills) that
                     are kit token refs or literals equal to a kit color value.
logo_adoption        kit has logos → the scene places at least one of THOSE
                     assets (by asset id, the same identity brand governance
                     matches on). None (n/a) when the kit has no logos.
accent_usage         the kit's accent (brand card definition: most vivid
                     mid-lightness brand color) appears among the paints.
                     None (n/a) when no accent can be derived. INFORMATIONAL
                     — whether an accent moment belongs on this surface is an
                     archetype/taste call the in-loop reviewer owns; a
                     deterministic scorer reporting it would punish QUIET
                     surfaces for following the brand-application table.

Verdict: ship / tweak / redo with explicit reasons — thresholds are the
contract, not a learned score.

CLI: ``python -m evaluation.brand_fidelity <run_dir> --kit-file kit.json``
(``--kit-file`` optional when the run dir's ``input.json``/scene carries a
resolvable kit ref and LUMEN_API_DATABASE_PATH points at the library).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from py_lumen_config import settings

from lumen_deepagent.brand_card import _brightest_accent, _resolve_color

JsonObject = dict[str, Any]

#: typography_binding below this is an automatic redo — the design is not
#: actually wearing the kit, whatever it looks like.
BINDING_REDO_THRESHOLD = 0.5


def _kit_color_values(brand_kit: JsonObject) -> set[str]:
    colors = (brand_kit.get("tokens") or {}).get("colors") or {}
    values: set[str] = set()
    for name in colors:
        resolved = _resolve_color(name, colors, set())
        if isinstance(resolved, str):
            values.add(resolved.lower())
    return values


def _kit_families(brand_kit: JsonObject) -> set[str]:
    families: set[str] = set()
    for font in ((brand_kit.get("assets") or {}).get("fonts") or {}).values():
        if isinstance(font, dict) and isinstance(font.get("family"), str):
            families.add(font["family"])
    for token in ((brand_kit.get("tokens") or {}).get("typography") or {}).values():
        default = ((token or {}).get("value") or {}).get("default") or {}
        family = default.get("font_family")
        if isinstance(family, str):
            families.add(family)
    return families


def _kit_logo_asset_ids(brand_kit: JsonObject) -> set[str]:
    ids: set[str] = set()
    for logo in ((brand_kit.get("assets") or {}).get("logos") or {}).values():
        if not isinstance(logo, dict):
            continue
        for variant in logo.get("variants") or []:
            if isinstance(variant, dict) and variant.get("asset_id"):
                ids.add(str(variant["asset_id"]))
    return ids


def _paints(scene: JsonObject) -> list[JsonObject]:
    paints: list[JsonObject] = []
    for page in (scene.get("pages") or {}).values():
        for paint in (page or {}).get("background") or []:
            if isinstance(paint, dict) and isinstance(paint.get("paint"), dict):
                paints.append(paint["paint"])
    for node in (scene.get("nodes") or {}).values():
        for paint in (node or {}).get("fills") or []:
            if isinstance(paint, dict) and isinstance(paint.get("paint"), dict):
                paints.append(paint["paint"])
    return paints


def _paint_hex(paint: JsonObject) -> Optional[str]:
    color = paint.get("color")
    if isinstance(color, dict) and color.get("kind") == "hex":
        value = color.get("value")
        return value.lower() if isinstance(value, str) else None
    return None


def _text_nodes(scene: JsonObject) -> list[JsonObject]:
    out = []
    for node in (scene.get("nodes") or {}).values():
        kind = (node or {}).get("kind")
        if isinstance(kind, dict) and kind.get("kind") == "text":
            out.append(kind)
    return out


def score_brand_fidelity(scene: JsonObject, brand_kit: JsonObject) -> JsonObject:
    """The deterministic brand-fidelity scorecard for one scene + kit."""
    texts = _text_nodes(scene)
    families = _kit_families(brand_kit)
    bound = [t for t in texts if t.get("style_token")]
    on_family = [
        t
        for t in texts
        if t.get("style_token") or (t.get("font_family") in families)
    ]
    off_family = sorted(
        {
            str(t.get("font_family"))
            for t in texts
            if not t.get("style_token") and t.get("font_family") not in families
        }
    )

    kit_values = _kit_color_values(brand_kit)
    paints = _paints(scene)
    def paint_adheres(paint: JsonObject) -> bool:
        if paint.get("kind") == "token":
            return True
        value = _paint_hex(paint)
        return value is None or value in kit_values  # non-solid paints: n/a

    adhering = [p for p in paints if paint_adheres(p)]
    rogue_values = sorted(
        {
            str(_paint_hex(p))
            for p in paints
            if not paint_adheres(p) and _paint_hex(p)
        }
    )

    logo_ids = _kit_logo_asset_ids(brand_kit)
    placed_asset_ids = {
        str(node["kind"].get("asset_id"))
        for node in (scene.get("nodes") or {}).values()
        if isinstance((node or {}).get("kind"), dict)
        and node["kind"].get("kind") == "image"
        and node["kind"].get("asset_id")
    }
    logo_adoption: Optional[bool] = None
    if logo_ids:
        logo_adoption = bool(logo_ids & placed_asset_ids)

    colors = (brand_kit.get("tokens") or {}).get("colors") or {}
    accent = _brightest_accent(colors)
    accent_hex = (accent or {}).get("value")
    accent_usage: Optional[bool] = None
    if isinstance(accent_hex, str):
        accent_usage = accent_hex.lower() in {
            _paint_hex(p) for p in paints if _paint_hex(p)
        } or any(
            p.get("kind") == "token" and p.get("token") == (accent or {}).get("token")
            for p in paints
        )

    scores = {
        "typography_binding": (len(bound) / len(texts)) if texts else None,
        "typography_family": (len(on_family) / len(texts)) if texts else None,
        "palette_adherence": (len(adhering) / len(paints)) if paints else None,
        "logo_adoption": logo_adoption,
        "accent_usage": accent_usage,
    }

    reasons: list[str] = []
    verdict = "ship"
    binding = scores["typography_binding"]
    if binding is not None and binding < BINDING_REDO_THRESHOLD:
        verdict = "redo"
        reasons.append(
            f"typography_binding {len(bound)}/{len(texts)}: text is not bound to kit "
            "type roles (LUMB0805 class) — the design detaches from the kit on any "
            "token change"
        )
    if logo_adoption is False:
        verdict = "redo"
        reasons.append(
            "logo_adoption: the kit provides logo assets but none is placed in the scene"
        )
    if verdict != "redo":
        if binding is not None and binding < 1.0:
            verdict = "tweak"
            reasons.append(
                f"typography_binding {len(bound)}/{len(texts)}: unbound text remains"
            )
        if off_family:
            verdict = "tweak"
            reasons.append(f"typography_family: non-kit families {off_family}")
        if rogue_values:
            verdict = "tweak"
            reasons.append(f"palette_adherence: non-kit paint values {rogue_values}")
    if accent_usage is False:
        # Informational only: the reviewer owns whether THIS surface should
        # carry an accent moment (QUIET archetypes legitimately do not).
        reasons.append(
            f"note: the kit accent {accent_hex} appears nowhere in the scene"
        )
    if not reasons:
        reasons.append("all brand-fidelity axes clean")

    return {
        "verdict": verdict,
        "scores": scores,
        "detail": {
            "text_nodes": len(texts),
            "bound_text_nodes": len(bound),
            "off_family_literals": off_family,
            "rogue_paint_values": rogue_values,
            "kit_logo_asset_ids": sorted(logo_ids),
            "placed_asset_ids": sorted(placed_asset_ids),
            "accent": accent,
        },
        "reasons": reasons,
    }


# --- CLI -------------------------------------------------------------------------


def _load_scene(run_dir: Path) -> JsonObject:
    """Prefer the newest AUTHORED-scene snapshot: resolution deliberately
    consumes token bindings (resolution-once), so the resolved final_scene
    can never show style_token — binding is only observable pre-resolution."""
    authored = sorted(run_dir.glob("iterations/*/authored_scene.json"))
    path = authored[-1] if authored else (run_dir / "final_scene.json")
    scene = json.loads(path.read_text())
    return scene.get("scene", scene) if "scene" in scene else scene


def _kit_from_library(scene: JsonObject) -> Optional[JsonObject]:
    ref = (scene.get("meta") or {}).get("brand_kit")
    if not (isinstance(ref, dict) and ref.get("id")):
        return None
    database_path = str(settings.lumen_api_database_path)
    try:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT brand_kit_json FROM brand_kits WHERE brand_kit_id = ?
            ORDER BY version DESC LIMIT 1
            """,
            (str(ref["id"]),),
        ).fetchone()
        return json.loads(row["brand_kit_json"]) if row else None
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="run trace dir with final_scene.json")
    parser.add_argument("--kit-file", type=Path, default=None)
    args = parser.parse_args()

    scene = _load_scene(args.run_dir)
    kit = (
        json.loads(args.kit_file.read_text())
        if args.kit_file
        else _kit_from_library(scene)
    )
    if kit is None:
        print("brand kit unavailable: pass --kit-file or set LUMEN_API_DATABASE_PATH")
        return 2
    report = score_brand_fidelity(scene, kit)
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "ship" else 1


if __name__ == "__main__":
    raise SystemExit(main())
