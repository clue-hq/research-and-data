"""Small, pure mirrors of engine-side truth, shared by the agent surfaces.

Two facts have to be restated in Python, and both are consumed by BOTH the
brand card and the web substrate:

* **the web theme compiler's color rules** — how a kit color key becomes a
  token name, and whether a kit color resolves to a concrete color at all
  (`crates/lumen-web/src/theme.rs`: `sanitize_token_name`, `resolve_color`,
  `css_color_value_ok`, `ALIAS_DEPTH_CAP`). Every Python surface that names a
  token to the author is claiming the compiled theme carries it, so a divergence
  here is an invitation to write a class the engine then rejects;
* **where an asset record keeps its true pixel dimensions** — the `raster`
  (else `logo`) block, which is what `view("asset:<id>")` reports as SOURCE
  size and what the brand card's `px` field states.

They live here, below both consumers, because the alternative is a second copy:
`web_substrate` already imports `brand_card`, and `brand_card` cannot import
back through `lumen_agent.tools` without a cycle. Nothing in this module imports
anything internal — that is the point.
"""

from __future__ import annotations

from typing import Any, Optional

JsonObject = dict[str, Any]

#: `theme.rs::ALIAS_DEPTH_CAP` — an alias chain deeper than this does not
#: resolve (which is also what bounds a cycle).
ALIAS_DEPTH_CAP = 8

#: `theme.rs::css_color_value_ok` — token values are embedded into `<style>`
#: payloads, so anything outside a plain CSS-color charset is markup injection,
#: not a color. Deliberately a CHARSET check, not a hex parse: the engine
#: accepts any value made of these characters (`white` and `oklch(…)` included).
_CSS_COLOR_VALUE_MAX_CHARS = 128
_CSS_COLOR_EXTRA_CHARS = frozenset("#%.,  ()-/+")


def sanitize_token_name(name: str) -> str:
    """Mirror `theme.rs::sanitize_token_name`: keep [a-z0-9-], lowercase [A-Z],
    map ./_/space to '-', drop everything else, then trim leading/trailing '-'.
    """
    out: list[str] = []
    for ch in name:
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "-":
            out.append(ch)
        elif "A" <= ch <= "Z":
            out.append(ch.lower())
        elif ch in "._ ":
            out.append("-")
        # any other character is dropped
    return "".join(out).strip("-")


def css_color_value_ok(value: str) -> bool:
    """Mirror `theme.rs::css_color_value_ok`."""
    trimmed = value.strip()
    if not trimmed or len(trimmed) > _CSS_COLOR_VALUE_MAX_CHARS:
        return False
    return all(
        ch.isascii() and (ch.isalnum() or ch in _CSS_COLOR_EXTRA_CHARS) for ch in trimmed
    )


def resolve_kit_color(
    name: str, colors: JsonObject, depth: int = 0
) -> Optional[JsonObject]:
    """The concrete color block `name` resolves to in a kit's color tokens, or
    None when the compiled theme would carry no color for it.

    Mirrors `theme.rs::resolve_color` decision for decision — a token missing
    from the kit, an alias chain deeper than `ALIAS_DEPTH_CAP` (a cycle included),
    or a hex value outside the CSS-color charset all yield None, which is exactly
    the case Rust reports as LUMW0302 and SKIPS when preserving kit colors.
    Returns the block itself (`{"kind": "hex"|"oklch", …}`) rather than a bool so
    callers that need the VALUE — the brand card quotes hex — do not walk the
    alias chain a second time.

    One deliberate deviation, in the fail-closed direction: Rust accepts every
    `oklch` block unconditionally because a malformed one fails kit
    deserialization long before the theme compiles; Python has no such gate, so
    an oklch block whose l/c/h are not numbers is treated as unresolvable here.
    A kit that reaches the engine can never contain one.
    """
    if depth > ALIAS_DEPTH_CAP:
        return None
    token = colors.get(name)
    if not isinstance(token, dict):
        return None
    default = (token.get("value") or {}).get("default") or {}
    if not isinstance(default, dict):
        return None
    kind = default.get("kind")
    if kind == "hex":
        raw = default.get("value")
        return default if isinstance(raw, str) and css_color_value_ok(raw) else None
    if kind == "oklch":
        if all(
            isinstance(default.get(axis), (int, float))
            and not isinstance(default.get(axis), bool)
            for axis in ("l", "c", "h")
        ):
            return default
        return None
    if kind == "alias":
        target = default.get("token")
        if not isinstance(target, str):
            return None
        return resolve_kit_color(target, colors, depth + 1)
    return None


def record_pixel_dims(record: JsonObject) -> Optional[tuple]:
    """An asset's TRUE pixel dimensions from its own metadata block, or None.

    Same blocks the shared preview resolver reads for a non-thumbnailed raster
    (`raster`, else `logo`); a vector or a record that never carried dimensions
    honestly has none."""
    dims = record.get("raster") or record.get("logo") or {}
    width, height = dims.get("pixel_width"), dims.get("pixel_height")
    return (width, height) if width and height else None
