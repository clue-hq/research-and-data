"""Deterministic brand retokenization: raw literals → the kit tokens they equal.

K4 measured that the LLM repair path cannot incrementally rebind tokens
(run_bff3433f: 25 raw-token findings, five iterations, zero progress) and that
authoring obedience is coin-flip. This pass is the mechanical answer: scan the
agent's draft, and wherever a literal value EQUALS a kit token's value, bind
the token — pure data mapping, no model in the loop. Runs only on the agent's
own unseeded drafts (a human's literals are never rebound: resolution-once).

Binding rules (v1):
- solid fill/stroke paints whose hex equals a kit color token value → token
  paint (semantic tokens win over palette.* on value collisions)
- auto-layout gap / uniform padding equal to a spacing token → gap/padding
  token (semantic names like space.md win over numeric space.3)
- stroke width equal to a stroke token → width_token
- node opacity equal to an opacity token → opacity_token
- text without explicit typography tokens: bind only roles whose effective
  family, weight, leading, tracking and size are equivalent. An exact size-ramp
  override can accompany an otherwise equivalent role, or bind alone. Size
  snapping requires an explicit positive ``size_snap_tolerance``; all other
  typography remains unchanged. Ambiguous mode/alias/font/color candidates are
  left to the canonical resolver when explicitly authored.

Every change is a real ``update_node`` operation applied through the core
(validated, invertible) and logged to the operations ledger, so bindings
survive Accept exactly like any other mutation.
"""

from __future__ import annotations

import re
from typing import Any, Optional

JsonObject = dict[str, Any]

#: Automatic inference preserves size. Callers may explicitly opt into a
#: fractional size-only snap; that never permits leading/tracking drift.
SIZE_SNAP_TOLERANCE = 0.0

_NUMERIC_SPACE = re.compile(r"^space\.\d+$")


def _unchanged() -> JsonObject:
    return {"kind": "unchanged"}


def _set(value: Any) -> JsonObject:
    return {"kind": "set", "value": value}


def empty_node_patch() -> JsonObject:
    """A full-shape NodePatch with every field unchanged (the operation
    schema requires the non-defaulted fields to be present).

    Public because `autofix.py` builds `update_node` operations too, and a
    second hand-written copy of this field list is exactly the kind of drift
    that produces a "missing field" refusal from the helper months later."""
    return {
        "name": _unchanged(),
        "kind": _unchanged(),
        "transform": _unchanged(),
        "size": _unchanged(),
        "fills": _unchanged(),
        "strokes": _unchanged(),
        "corner": _unchanged(),
        "opacity": _unchanged(),
        "opacity_token": _unchanged(),
        "source_asset_id": _unchanged(),
        "asset_placement": _unchanged(),
        "clip": _unchanged(),
        "layout": _unchanged(),
        "computed": _unchanged(),
        "locked": _unchanged(),
    }


# --- kit value indexes ------------------------------------------------------------


def _resolve_color_hex(name: str, colors: JsonObject) -> Optional[str]:
    from .brand_card import _resolve_color

    resolved = _resolve_color(name, colors)
    return resolved.lower() if isinstance(resolved, str) else None


def _color_index(brand_kit: JsonObject) -> dict[str, str]:
    colors = (brand_kit.get("tokens") or {}).get("colors") or {}
    ranked = sorted(
        colors, key=lambda n: (1 if n.startswith("palette.") else 0, n)
    )
    index: dict[str, str] = {}
    for name in ranked:
        value = _resolve_color_hex(name, colors)
        if value and value not in index:
            index[value] = name
    return index


def _number_index(brand_kit: JsonObject, group: str, prefer_semantic: bool = False) -> dict[float, str]:
    tokens = (brand_kit.get("tokens") or {}).get(group) or {}

    def rank(name: str) -> tuple:
        numeric = bool(_NUMERIC_SPACE.match(name))
        return (numeric if prefer_semantic else False, name)

    index: dict[float, str] = {}
    for name in sorted(tokens, key=rank):
        default = ((tokens[name] or {}).get("value") or {}).get("default") or {}
        value = default.get("value")
        if isinstance(value, (int, float)) and float(value) not in index:
            index[float(value)] = name
    return index


def _invariant_value(brand_kit: JsonObject, name: str, token: JsonObject) -> JsonObject:
    """Only index direct values that are identical in every declared mode.

    Core owns selector precedence, alias lookup and font-asset resolution. This
    pass has no resolved candidate values, so it declines indirection rather
    than inventing a second resolver or treating defaults as the active mode.
    """
    if name in ((brand_kit.get("tokens") or {}).get("aliases") or {}):
        return {}
    values = (token or {}).get("value") or {}
    default = values.get("default") or {}
    if any(value != default for value in (values.get("modes") or {}).values()):
        return {}
    return default


def _type_roles(brand_kit: JsonObject) -> list[JsonObject]:
    roles = []
    typography = (brand_kit.get("tokens") or {}).get("typography") or {}
    for name, token in typography.items():
        default = _invariant_value(brand_kit, name, token)
        if default.get("kind") != "style" or default.get("font_asset") is not None:
            continue
        roles.append(
            {
                "token": name,
                "family": str(default.get("font_family") or ""),
                "size": float(default.get("font_size") or 0),
                "weight": int(default.get("font_weight") or 0),
                "line_height": default.get("line_height"),
                "letter_spacing": default.get("letter_spacing"),
                "color": default.get("color"),
            }
        )
    return roles


def _ramp_index(brand_kit: JsonObject) -> dict[float, str]:
    numbers = (brand_kit.get("tokens") or {}).get("numbers") or {}
    index: dict[float, str] = {}
    for name in sorted(numbers):
        if not name.startswith("type.size."):
            continue
        default = _invariant_value(brand_kit, name, numbers[name])
        if default.get("kind") != "number" or default.get("unit") not in ("unitless", "px", "mm"):
            continue
        value = default.get("value")
        if isinstance(value, (int, float)) and float(value) not in index:
            index[float(value)] = name
    return index


# --- per-node rewriting -----------------------------------------------------------


def _retokenize_paints(paints: Any, colors: dict[str, str]) -> Optional[list]:
    if not isinstance(paints, list) or not paints:
        return None
    changed = False
    out = []
    for entry in paints:
        paint = (entry or {}).get("paint") if isinstance(entry, dict) else None
        new_entry = dict(entry) if isinstance(entry, dict) else entry
        if isinstance(paint, dict) and paint.get("kind") == "solid":
            value = str(((paint.get("color") or {}).get("value")) or "").lower()
            token = colors.get(value)
            if token:
                new_entry = {**entry, "paint": {"kind": "token", "token": token}}
                changed = True
        out.append(new_entry)
    return out if changed else None


def _retokenize_text_kind(
    kind: JsonObject,
    roles: list[JsonObject],
    ramp: dict[float, str],
    kit_families: set[str],
    tolerance: float,
) -> Optional[tuple[JsonObject, JsonObject]]:
    # Scalar tokens can be newly authored while their numeric fields still
    # contain the previous resolved values. Inferring a role/ramp from those
    # stale literals would overwrite the requested repair before core resolves
    # it. Leave explicit typography to the canonical resolver, including its
    # missing-token diagnostics; this pass only fills in unbound literals.
    if any(kind.get(token) is not None for token in (
        "style_token", "font_size_token", "line_height_token", "letter_spacing_token"
    )):
        return None
    family = str(kind.get("font_family") or "")
    size = float(kind.get("font_size") or 0)
    weight = int(kind.get("font_weight") or 0)

    exact = [
        r for r in roles
        if r["family"] == family and r["weight"] == weight
        and all(r[field] is None or r[field] == kind.get(field)
                for field in ("line_height", "letter_spacing"))
    ]
    updated = dict(kind)
    for role in exact:
        if role["size"] == size:
            updated["style_token"] = role["token"]
            return updated, {"style": True}
    if exact and size in ramp:
        updated["style_token"] = exact[0]["token"]
        updated["font_size_token"] = ramp[size]
        return updated, {"style": True, "font_size": True}
    # No role fits: a ramp-exact size still earns its size token.
    if family.lower() in kit_families and size in ramp:
        updated["font_size_token"] = ramp[size]
        return updated, {"font_size": True}
    if family.lower() in kit_families and tolerance > 0 and ramp and size > 0:
        nearest = min(ramp, key=lambda step: abs(step - size))
        if abs(nearest - size) / size <= tolerance:
            updated["font_size_token"] = ramp[nearest]
            updated["font_size"] = nearest
            if exact:
                updated["style_token"] = exact[0]["token"]
                return updated, {"style": True, "font_size": True}
            return updated, {"font_size": True}
    return None


def build_retokenize_operations(
    scene: JsonObject,
    brand_kit: JsonObject,
    *,
    size_snap_tolerance: float = SIZE_SNAP_TOLERANCE,
) -> list[JsonObject]:
    colors = _color_index(brand_kit)
    spacing = _number_index(brand_kit, "spacing", prefer_semantic=True)
    strokes = _number_index(brand_kit, "stroke_widths")
    opacity = _number_index(brand_kit, "opacity")
    roles = _type_roles(brand_kit)
    ramp = _ramp_index(brand_kit)
    kit_families = {r["family"].lower() for r in roles}
    for font in ((brand_kit.get("assets") or {}).get("fonts") or {}).values():
        if isinstance(font, dict) and isinstance(font.get("family"), str):
            kit_families.add(font["family"].lower())

    operations: list[JsonObject] = []
    for node_id, node in (scene.get("nodes") or {}).items():
        if not isinstance(node, dict):
            continue
        patch = empty_node_patch()
        touched = False

        new_fills = _retokenize_paints(node.get("fills"), colors)
        if new_fills is not None:
            patch["fills"] = _set(new_fills)
            touched = True

        node_strokes = node.get("strokes")
        if isinstance(node_strokes, list) and node_strokes:
            changed = False
            out = []
            for stroke in node_strokes:
                new_stroke = dict(stroke) if isinstance(stroke, dict) else stroke
                paint = (stroke or {}).get("paint") if isinstance(stroke, dict) else None
                if isinstance(paint, dict) and paint.get("kind") == "solid":
                    value = str(((paint.get("color") or {}).get("value")) or "").lower()
                    token = colors.get(value)
                    if token:
                        new_stroke["paint"] = {"kind": "token", "token": token}
                        changed = True
                if (
                    isinstance(new_stroke, dict)
                    and not new_stroke.get("width_token")
                    and isinstance(new_stroke.get("width"), (int, float))
                    and float(new_stroke["width"]) in strokes
                ):
                    new_stroke["width_token"] = strokes[float(new_stroke["width"])]
                    changed = True
                out.append(new_stroke)
            if changed:
                patch["strokes"] = _set(out)
                touched = True

        layout = node.get("layout")
        if isinstance(layout, dict):
            new_layout = dict(layout)
            layout_changed = False
            gap = layout.get("gap")
            if (
                not layout.get("gap_token")
                and isinstance(gap, (int, float))
                and float(gap) in spacing
            ):
                new_layout["gap_token"] = spacing[float(gap)]
                layout_changed = True
            padding = layout.get("padding")
            if isinstance(padding, dict):
                edges = [padding.get(k) for k in ("top", "right", "bottom", "left")]
            elif isinstance(padding, list) and len(padding) == 4:
                edges = list(padding)
            else:
                edges = [None]
            if (
                not layout.get("padding_token")
                and all(isinstance(e, (int, float)) for e in edges)
                and len({float(e) for e in edges}) == 1
                and float(edges[0]) in spacing
            ):
                new_layout["padding_token"] = spacing[float(edges[0])]
                layout_changed = True
            if layout_changed:
                patch["layout"] = _set(new_layout)
                touched = True

        node_opacity = node.get("opacity")
        if (
            not node.get("opacity_token")
            and isinstance(node_opacity, (int, float))
            and float(node_opacity) in opacity
            and float(node_opacity) != 1.0
        ):
            patch["opacity_token"] = _set(opacity[float(node_opacity)])
            touched = True

        kind = node.get("kind")
        if isinstance(kind, dict) and kind.get("kind") == "text":
            # Core applies a role color only without an author-owned first
            # fill. Its synthesized `<node>_text_fill` remains role-owned.
            # Color resolution/contrast adaptation cannot be inferred here.
            fills = node.get("fills") or []
            has_author_fill = bool(fills and fills[0].get("id") != f"{node_id}_text_fill")
            safe_roles = [r for r in roles if r["color"] is None or has_author_fill]
            text_rebind = _retokenize_text_kind(
                kind, safe_roles, ramp, kit_families, size_snap_tolerance
            )
            if text_rebind is not None:
                new_kind, explicit_tokens = text_rebind
                patch["kind"] = _set(new_kind)
                # The ledger replays against unresolved authoring state.
                # Preserve deliberate same-token reapplication there too.
                patch["explicit_text_tokens"] = explicit_tokens
                touched = True
            elif new_fills is not None:
                # This is a paint rebind, not an authored text-color edit.
                # A fills-only core operation would detach the role when
                # replayed over unresolved authoring state and expose stale
                # literals. Carry current text even when no equivalent role
                # can be inferred, along with any explicit binding intent.
                patch["kind"] = _set(dict(kind))
                patch["explicit_text_tokens"] = {
                    "style": kind.get("style_token") is not None,
                    "font_size": kind.get("font_size_token") is not None,
                    "line_height": kind.get("line_height_token") is not None,
                    "letter_spacing": kind.get("letter_spacing_token") is not None,
                }

        if touched:
            operations.append(
                {"kind": "update_node", "node_id": node_id, "patch": patch}
            )
    return operations


# --- deterministic logo placement ------------------------------------------------


def _kit_logo_index(
    brand_kit: JsonObject,
) -> tuple[set[str], Optional[tuple[str, JsonObject]]]:
    """Return (all kit logo asset ids, the preferred (id, variant) to place).
    Preference order is mark → primary → wordmark; the full id set is used for
    presence detection so ANY kit logo variant counts as 'a logo is present'."""
    logos = (brand_kit.get("assets") or {}).get("logos") or {}
    kit_ids: set[str] = set()
    chosen: Optional[tuple[str, JsonObject]] = None
    for slot in ("mark", "primary", "wordmark"):
        for variant in (logos.get(slot) or {}).get("variants") or []:
            if isinstance(variant, dict) and variant.get("asset_id"):
                kit_ids.add(str(variant["asset_id"]))
                if chosen is None:
                    chosen = (str(variant["asset_id"]), variant)
    for logo in logos.values():
        for variant in (logo or {}).get("variants") or []:
            if isinstance(variant, dict) and variant.get("asset_id"):
                kit_ids.add(str(variant["asset_id"]))
    return kit_ids, chosen


def scene_has_kit_logo(scene: JsonObject, brand_kit: JsonObject) -> bool:
    """True when the scene already carries the brand mark — either an image node
    bound to a kit logo asset (author-placed) OR our `brand_logo_auto` overlay.
    The place-once caller uses this to remember a logo was present, so a later
    removal is respected instead of undone on the next preflight."""
    kit_ids, _ = _kit_logo_index(brand_kit)
    if not kit_ids:
        return False
    nodes = scene.get("nodes") or {}
    for node in nodes.values():
        kind = (node or {}).get("kind")
        if (
            isinstance(kind, dict)
            and kind.get("kind") == "image"
            and str(kind.get("asset_id")) in kit_ids
        ):
            return True
    return "brand_logo_auto" in nodes


def build_logo_placement_operations(
    scene: JsonObject, brand_kit: JsonObject
) -> list[JsonObject]:
    """One deterministic `insert_node` placing the kit's mark when the scene
    has none of the kit's logo assets (K4: authoring adoption measured at
    coin-flip and repair-scope constraints make 'please add it' structurally
    unactionable — sweep 3 traced ten delivered instructions to zero placed
    logos). Placement is a page-level overlay at the top-left margin: it
    never joins an auto-layout flow, so nothing reflows; the agent may move
    or restyle it in later iterations like any node, and the critic judges
    the result. The K2 preflight auto-register upserts the asset record.

    Presence-only: this returns [] whenever a logo is already present. The
    PLACE-ONCE / respect-removal policy lives in the caller (it tracks whether
    a logo was ever present), because this pure function cannot see run history.
    """
    kit_ids, chosen = _kit_logo_index(brand_kit)
    if not kit_ids or chosen is None:
        return []
    if scene_has_kit_logo(scene, brand_kit):
        return []

    pages = scene.get("pages") or {}
    if not pages:
        return []
    page_id, page = next(iter(pages.items()))
    size = page.get("size") or {}
    page_w = float(size.get("width") or 1080.0)
    page_h = float(size.get("height") or 1080.0)
    margin = round(min(page_w, page_h) * 0.06)
    height = max(48.0, round(min(page_w, page_h) * 0.05))
    asset_id, variant = chosen
    v_w, v_h = variant.get("width"), variant.get("height")
    aspect = (float(v_w) / float(v_h)) if v_w and v_h else 1.0
    width = round(height * aspect, 1)

    node = {
        "id": "brand_logo_auto",
        "name": "Brand logo",
        "kind": {"kind": "image", "asset_id": asset_id, "alt": "Brand logo"},
        "transform": {
            "x": float(margin), "y": float(margin), "rotation": 0.0,
            "skew_x": 0.0, "skew_y": 0.0, "flip_x": False, "flip_y": False,
        },
        "size": {
            "width": {"kind": "fixed", "value": float(width)},
            "height": {"kind": "fixed", "value": float(height)},
        },
        "children": [],
        "fills": [],
        "strokes": [],
        "corner": {"top_left": 0.0, "top_right": 0.0, "bottom_right": 0.0, "bottom_left": 0.0},
        "opacity": 1.0,
        "clip": False,
        "layout": None,
        "computed": None,
        "locked": False,
    }
    children = page.get("children") or []
    return [
        {
            "kind": "insert_node",
            "parent": {"kind": "page", "id": page_id},
            "index": len(children),
            "node": node,
        }
    ]
