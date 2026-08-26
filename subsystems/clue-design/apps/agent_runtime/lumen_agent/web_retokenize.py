"""Deterministic brand retokenization for the WEB lane: raw geometry classes →
the kit utility that already renders exactly that value.

The scene lane's `retokenize.py` proved the shape — the agent cannot reliably
rebind tokens by being asked to, so a mechanical pass does it. This is the web
twin over class strings, and it is deliberately narrower.

THE CONTRACT: a rebind NEVER changes rendered output. A raw class becomes a
brand utility only when its CSS value is byte-equal (after unit normalization)
to that utility's kit-resolved value, so the swap is a pure RENAMING. What
changes is what the class FOLLOWS: `rounded-2xl` is a frozen 16 pixels, while
`rounded-card` is the kit's pin — flip the kit version and the page re-renders
with the brand. It also silences the LUMW0306 advice for exactly the classes
where the advice was right. Anything not provably equal stays as authored.

Ruled axes (v1):

* **radius** — the stock all-corner steps and `rounded-[<N>px]`, against
  `rounded-button` / `rounded-card` / `rounded-badge`. Three candidates, so a
  value two of them share is AMBIGUOUS and skipped: a rename the pass cannot
  justify is a rename it does not make.
* **spacing** — `py-<n>`/`py-[<N>px]` → `py-section`, `p-…` → `p-card`,
  `gap-…` → `gap-stack`. One candidate per axis; a value is never carried
  across axes (`p-24` is 96px, but 96px is the SECTION rhythm, not card
  padding).

Excluded on purpose: **shadows** (a stock `shadow-lg`'s compound value is never
meaningfully byte-equal to a measured brand elevation) and **border widths**
(compound `border` semantics, and every brand's hairline is 1px, so the axis is
one enormous tie).

The pass is pure: same document + same geometry map → the same operations in
the same order. Applying them is the caller's business (`web_substrate.py` runs
it at the start of `render_web_preview`, under the seeded/kit guards).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Tuple

JsonObject = Dict[str, Any]

#: Pixels per rem. The compiled web theme's `base_css` sets `body` font-size,
#: never the ROOT font-size, so `rem` stays browser-default 16px in both the
#: editor preview and the static export pipeline.
REM_PX = Decimal(16)

#: The stock all-corner radius steps, VERIFIED against the installed Tailwind
#: theme — `apps/editor/node_modules/tailwindcss/theme.css` (v4.3.2), the
#: `--radius-*` custom properties plus the deprecated bare `--radius` that a
#: lone `rounded` still compiles to. Values are the theme's own rem literals so
#: the drift guard in `tests/test_web_retokenize.py` can compare them
#: character-for-character; a Tailwind upgrade that moves a step fails there
#: instead of silently rebinding a class to a radius it no longer renders.
#:
#: Two stock steps are deliberately ABSENT. `rounded-full` compiles to
#: `calc(infinity * 1px)` in v4 (confirmed by compiling it through
#: `scripts/web_static_css.mjs`), which is byte-equal to no measured px radius —
#: not even a 999px badge. `rounded-none` is outside the ruled axis list: a
#: square corner is a shape decision, not drift.
STOCK_RADIUS_REM: Dict[str, str] = {
    "rounded": "0.25",
    "rounded-xs": "0.125",
    "rounded-sm": "0.25",
    "rounded-md": "0.375",
    "rounded-lg": "0.5",
    "rounded-xl": "0.75",
    "rounded-2xl": "1",
    "rounded-3xl": "1.5",
    "rounded-4xl": "2",
}

#: `--spacing: 0.25rem` — the multiplier behind every numeric `p-<n>` /
#: `py-<n>` / `gap-<n>` step. Same source, same drift guard.
SPACING_STEP_REM = "0.25"


def _canonical(value: Decimal) -> str:
    """One spelling per number, so equality is exact and unit-free.

    `Decimal.normalize()` collapses trailing zeros (`16.00` → `16`) but can
    produce exponent form for round numbers (`1E+1`); `format(..., "f")` puts
    it back in plain notation.
    """
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "0E+0") else text


#: Stock radius steps as canonical pixel strings.
STOCK_RADIUS_PX: Dict[str, str] = {
    utility: _canonical(Decimal(rem) * REM_PX)
    for utility, rem in STOCK_RADIUS_REM.items()
}

#: One numeric step of the spacing scale, in pixels.
SPACING_STEP_PX: Decimal = Decimal(SPACING_STEP_REM) * REM_PX

#: The radius axis: (utility class, the geometry map key it resolves through).
RADIUS_UTILITIES: Tuple[Tuple[str, str], ...] = (
    ("rounded-button", "radius-button"),
    ("rounded-card", "radius-card"),
    ("rounded-badge", "radius-badge"),
)

#: The spacing axes: raw class namespace → (utility class, geometry map key).
#: Each namespace has exactly ONE candidate, and values never cross axes.
SPACING_UTILITIES: Dict[str, Tuple[str, str]] = {
    "py": ("py-section", "spacing-section"),
    "p": ("p-card", "spacing-card"),
    "gap": ("gap-stack", "spacing-stack"),
}

# `\d+(\.\d+)?` only: a negative radius or padding is not a thing, and refusing
# to parse one keeps `-p-4`-shaped nonsense out of the match entirely.
_NUMBER = r"\d+(?:\.\d+)?"
_ARBITRARY_RADIUS = re.compile(rf"^rounded-\[({_NUMBER})px\]$")
_SPACING_STEP = re.compile(rf"^(p|py|gap)-({_NUMBER})$")
_SPACING_ARBITRARY = re.compile(rf"^(p|py|gap)-\[({_NUMBER})px\]$")
_WHITESPACE = re.compile(r"(\s+)")


# --- the resolved geometry map ----------------------------------------------


def _css_px(value: Any) -> Optional[str]:
    """A geometry map value as a canonical pixel string, or None when it is not
    a plain px length this pass can compare (a shadow, a `calc()`, an empty
    fallback). Bare `0` counts — that is how the engine formats a zero length.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("px"):
        text = text[:-2].strip()
    elif text not in ("0", "-0"):
        return None
    try:
        return _canonical(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _radius_index(geometry: Mapping[str, str]) -> List[Tuple[str, str]]:
    """(utility, canonical px) for every radius utility with a usable value."""
    index: List[Tuple[str, str]] = []
    for utility, key in RADIUS_UTILITIES:
        px = _css_px(geometry.get(key))
        if px is not None:
            index.append((utility, px))
    return index


def _spacing_index(geometry: Mapping[str, str]) -> Dict[str, Tuple[str, str]]:
    """namespace → (utility, canonical px) for every usable spacing utility."""
    index: Dict[str, Tuple[str, str]] = {}
    for namespace, (utility, key) in SPACING_UTILITIES.items():
        px = _css_px(geometry.get(key))
        if px is not None:
            index[namespace] = (utility, px)
    return index


# --- class-string surgery ---------------------------------------------------


def _split_variants(token: str) -> Tuple[str, str]:
    """(everything up to and including the last top-level `:`, the base).

    Mirrors `classes.rs::split_prefixes`: a `:` inside `[...]` (an arbitrary
    value) is part of the value, not a variant separator.
    """
    depth = 0
    start = 0
    for index, char in enumerate(token):
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif char == ":" and depth == 0:
            start = index + 1
    return token[:start], token[start:]


def _raw_radius_px(base: str) -> Optional[str]:
    """The pixel value a raw radius class renders, or None when the class is
    not an all-corner radius this pass reads (side/corner variants such as
    `rounded-t-lg` never match — their table key does not exist)."""
    stock = STOCK_RADIUS_PX.get(base)
    if stock is not None:
        return stock
    match = _ARBITRARY_RADIUS.match(base)
    if match is None:
        return None
    return _canonical(Decimal(match.group(1)))


def _raw_spacing_px(base: str) -> Optional[Tuple[str, str]]:
    """(namespace, pixel value) for a raw spacing class, or None."""
    match = _SPACING_STEP.match(base)
    if match is not None:
        return match.group(1), _canonical(Decimal(match.group(2)) * SPACING_STEP_PX)
    match = _SPACING_ARBITRARY.match(base)
    if match is not None:
        return match.group(1), _canonical(Decimal(match.group(2)))
    return None


def _rebound_base(
    base: str,
    radius_index: List[Tuple[str, str]],
    spacing_index: Dict[str, Tuple[str, str]],
) -> Optional[str]:
    """The utility this raw class provably equals, or None.

    Exact-or-nothing, and unambiguous-or-nothing: the scene lane's size snap is
    for type ramps, where becoming more branded is the point; a geometry value
    is a rendered pixel and a near miss is a different page.
    """
    radius_px = _raw_radius_px(base)
    if radius_px is not None:
        hits = [utility for utility, value in radius_index if value == radius_px]
        return hits[0] if len(hits) == 1 else None

    spacing = _raw_spacing_px(base)
    if spacing is not None:
        namespace, value = spacing
        candidate = spacing_index.get(namespace)
        if candidate is not None and candidate[1] == value:
            return candidate[0]
    return None


def _rebind_classes(
    classes: str,
    radius_index: List[Tuple[str, str]],
    spacing_index: Dict[str, Tuple[str, str]],
) -> Optional[str]:
    """The rebound class string, or None when nothing in it provably matched.

    Separators are preserved verbatim (the split keeps them), so every token
    the pass does not rebind survives byte-identically, in its original
    position.
    """
    changed = False
    out: List[str] = []
    for part in _WHITESPACE.split(classes):
        if not part or part.isspace():
            out.append(part)
            continue
        prefix, base = _split_variants(part)
        utility = _rebound_base(base, radius_index, spacing_index)
        if utility is None:
            out.append(part)
        else:
            out.append(prefix + utility)
            changed = True
    return "".join(out) if changed else None


# --- the pass ---------------------------------------------------------------


def build_web_retokenize_operations(
    web_doc: JsonObject,
    geometry: Mapping[str, str],
) -> List[JsonObject]:
    """The `set_node_classes` operations that rebind this document's raw
    geometry classes to the kit utilities they already equal.

    `geometry` is the compiled web theme's geometry channel — utility CSS-var
    name → CSS value — exactly as `core.web_validate(doc, kit)["web_theme"]
    ["geometry"]` hands it across the FFI.

    Pure: the document is only read, and the operation order is pages in stored
    order, then nodes in stored order.
    """
    radius_index = _radius_index(geometry)
    spacing_index = _spacing_index(geometry)
    if not radius_index and not spacing_index:
        return []

    operations: List[JsonObject] = []
    for page in web_doc.get("pages") or []:
        if not isinstance(page, dict):
            continue
        page_id = page.get("id")
        nodes = page.get("nodes")
        if not isinstance(page_id, str) or not isinstance(nodes, dict):
            continue
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            classes = node.get("classes")
            if not isinstance(classes, str) or not classes.strip():
                continue
            rebound = _rebind_classes(classes, radius_index, spacing_index)
            if rebound is None:
                continue
            operations.append(
                {
                    "kind": "set_node_classes",
                    "page_id": page_id,
                    "id": str(node_id),
                    "classes": rebound,
                }
            )
    return operations


def summarize_class_pairs(
    web_doc: JsonObject, operations: List[JsonObject]
) -> List[str]:
    """`"rounded-2xl→rounded-card ×3"` lines for the trace, in first-seen order.

    Read against the document the operations were built from, so it must be
    called BEFORE they are applied. Tokens are paired positionally, which is
    exact here: the pass only ever rewrites a token in place.
    """
    nodes: Dict[Tuple[str, str], JsonObject] = {}
    for page in web_doc.get("pages") or []:
        if not isinstance(page, dict):
            continue
        page_id = page.get("id")
        for node_id, node in (page.get("nodes") or {}).items():
            if isinstance(page_id, str) and isinstance(node, dict):
                nodes[(page_id, str(node_id))] = node

    counts: Dict[str, int] = {}
    for operation in operations:
        node = nodes.get((operation.get("page_id"), operation.get("id")))
        if not isinstance(node, dict):
            continue
        before = str(node.get("classes") or "").split()
        after = str(operation.get("classes") or "").split()
        if len(before) != len(after):
            continue
        for old, new in zip(before, after):
            if old != new:
                counts[f"{old}→{new}"] = counts.get(f"{old}→{new}", 0) + 1
    return [f"{pair} ×{count}" for pair, count in counts.items()]
