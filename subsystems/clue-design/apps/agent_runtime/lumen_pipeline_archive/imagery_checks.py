"""Deterministic imagery-quality checks (Phase 1 of the imagery-quality eval set).

Scores a compiled scene's USE of imagery on the dimensions that can be judged
WITHOUT taste — the cheap, hard gates that catch the ugliest failures:

- **placeholder_real** (#10): every placed image is a real ready asset, not the
  solid-color `stub-image-v0` placeholder or an unready/missing reference.
- **decision** (#6, the DECIDE guardrail): did the agent place an image when the
  brief calls for one (photo/icon) — and crucially NOT place a gratuitous image on a
  data/type brief whose correct answer is NONE.
- **aspect_fit** (#2): no stretch, no letterbox/pillarbox dead bands.
- **legibility** (#4): text overlapping an image sits under a covering scrim (or on
  its own surface).
- **hero_count** (#1, partial): at most one full-bleed image competes for dominance.

The taste dimensions (composition reads, theme/cliché, on-brand) need the LLM judge
(Phase 2). Each dimension returns ``{score: 0-3 | None, gate: bool, notes: [...]}``;
a ``gate`` failure is a hard fail that caps that dimension and blocks acceptance.
Pure dict-in/dict-out so it is unit-testable and reusable by the run scorer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

STUB_MODEL = "stub-image-v0"
Box = Tuple[float, float, float, float]


def _fixed(spec: Any) -> Optional[float]:
    if isinstance(spec, dict) and spec.get("kind") == "fixed":
        value = spec.get("value")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _kind(node: Dict[str, Any]) -> Optional[str]:
    kind = node.get("kind")
    return kind.get("kind") if isinstance(kind, dict) else None


def _node_box(node: Dict[str, Any]) -> Optional[Box]:
    bounds = (node.get("computed") or {}).get("layout_bounds") or {}
    width, height = bounds.get("width"), bounds.get("height")
    if not width or not height:
        size = node.get("size") or {}
        width, height = _fixed(size.get("width")), _fixed(size.get("height"))
    if not width or not height:
        return None
    return float(bounds.get("x", 0.0)), float(bounds.get("y", 0.0)), float(width), float(height)


def _asset_ratio(asset: Optional[Dict[str, Any]]) -> Optional[float]:
    raster = (asset or {}).get("raster") or {}
    if raster.get("aspect_ratio"):
        return float(raster["aspect_ratio"])
    pw, ph = raster.get("pixel_width"), raster.get("pixel_height")
    return (pw / ph) if (pw and ph) else None


def _overlap_area(a: Box, b: Box) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy


def _is_scrim(node: Dict[str, Any]) -> bool:
    if _kind(node) not in ("rect", "frame"):
        return False
    token = (node.get("opacity_token") or "")
    return node.get("opacity", 1.0) < 1.0 or token.endswith("scrim") or token.endswith("overlay")


def score_scene(scene: Dict[str, Any], expected_decision: Optional[str] = None) -> Dict[str, Any]:
    """Deterministically score a scene's use of imagery. Returns per-dimension
    sub-scores + an overall accept (no gate failure AND every scored dim >= 2)."""
    nodes: Dict[str, Any] = scene.get("nodes") or {}
    assets: Dict[str, Any] = scene.get("assets") or {}
    image_nodes = [(nid, n) for nid, n in nodes.items() if _kind(n) == "image"]
    text_nodes = [(nid, n) for nid, n in nodes.items() if _kind(n) == "text"]
    has_vector = any(_kind(n) in ("vector", "svg") for n in nodes.values())

    page_area: Optional[float] = None
    for page in (scene.get("pages") or {}).values():
        size = page.get("size") or {}
        if size.get("width") and size.get("height"):
            page_area = float(size["width"]) * float(size["height"])
            break

    dims: Dict[str, Dict[str, Any]] = {}
    real_count = 0

    # #10 placeholder-vs-real + #3 placement integrity
    if image_nodes:
        placeholder = unready = False
        for _nid, node in image_nodes:
            asset = assets.get((node.get("kind") or {}).get("asset_id"))
            if not asset:
                unready = True
                continue
            if asset.get("status") != "ready":
                unready = True
            if (asset.get("source") or {}).get("model") == STUB_MODEL or asset.get("kind") == "placeholder":
                placeholder = True
            else:
                real_count += 1
        gate = placeholder or unready
        notes = (["placeholder/stub image"] if placeholder else []) + (["unready/missing asset"] if unready else [])
        dims["placeholder_real"] = {"score": 0 if gate else 3, "gate": gate, "notes": notes}

    # #6 decision vs expected (the DECIDE guardrail)
    placed_image = bool(image_nodes)
    if expected_decision == "none":
        ok = not placed_image
        dims["decision"] = {
            "score": 3 if ok else 0,
            "gate": not ok,
            "notes": [] if ok else ["gratuitous image on a NONE-correct brief"],
        }
    elif expected_decision == "photo":
        dims["decision"] = {
            "score": 3 if placed_image else 1,
            "gate": False,
            "notes": [] if placed_image else ["expected a photo; none placed"],
        }
    elif expected_decision == "icon":
        ok = has_vector or placed_image
        dims["decision"] = {
            "score": 3 if (has_vector and not placed_image) else (2 if ok else 1),
            "gate": False,
            "notes": [] if ok else ["expected icons/illustration; none present"],
        }

    # #2 aspect-fit (stretch / dead-band)
    if image_nodes:
        worst, notes = 3, []
        for nid, node in image_nodes:
            box = _node_box(node)
            ratio = _asset_ratio(assets.get((node.get("kind") or {}).get("asset_id")))
            fit = (node.get("asset_placement") or {}).get("fit") or "contain"
            if box and ratio and box[3]:
                frame_ratio = box[2] / box[3]
                if fit == "contain" and abs(frame_ratio - ratio) / ratio > 0.1:
                    worst = min(worst, 1)
                    notes.append(f"{nid}: contain on a mismatched aspect → dead bands")
        dims["aspect_fit"] = {"score": worst, "gate": worst <= 1, "notes": notes}

    # #4 scrim / legibility over image
    if image_nodes:
        image_boxes = [b for b in (_node_box(n) for _, n in image_nodes) if b]
        scrim_boxes = [b for b in (_node_box(n) for n in nodes.values() if _is_scrim(n)) if b]
        overlaps = scrimmed = 0
        notes: List[str] = []
        for tnid, tnode in text_nodes:
            tb = _node_box(tnode)
            if not tb:
                continue
            text_area = tb[2] * tb[3]
            if any(_overlap_area(tb, ib) > 0.4 * text_area for ib in image_boxes):
                overlaps += 1
                if any(_overlap_area(tb, sb) >= 0.95 * text_area for sb in scrim_boxes):
                    scrimmed += 1
                else:
                    notes.append(f"{tnid}: text over image without a covering scrim")
        if overlaps == 0:
            dims["legibility"] = {"score": 3, "gate": False, "notes": ["no text overlaps image"]}
        else:
            ratio = scrimmed / overlaps
            score = 3 if ratio == 1 else (1 if ratio < 0.5 else 2)
            dims["legibility"] = {"score": score, "gate": ratio < 1, "notes": notes}

    # #1 hero count (full-bleed images competing)
    if image_nodes and page_area:
        full_bleed = sum(
            1 for _, n in image_nodes if (_node_box(n) and (_node_box(n)[2] * _node_box(n)[3]) >= 0.5 * page_area)
        )
        dims["hero_count"] = {
            "score": 3 if full_bleed <= 1 else 1,
            "gate": full_bleed > 1,
            "notes": [] if full_bleed <= 1 else [f"{full_bleed} full-bleed images compete for dominance"],
        }

    scored = [d for d in dims.values() if d.get("score") is not None]
    gate_failed = any(d.get("gate") for d in dims.values())
    accept = (not gate_failed) and all(d["score"] >= 2 for d in scored)
    return {
        "dimensions": dims,
        "gate_failed": gate_failed,
        "accept": bool(accept),
        "image_count": len(image_nodes),
        "real_image_count": real_count,
    }
