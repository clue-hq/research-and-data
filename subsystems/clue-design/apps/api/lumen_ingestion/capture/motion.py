"""Motion and icons read out of what the capture already holds (Wave 2 A9).

The probe sees WHICH animations run and the icon each button draws; the `@keyframes` bodies live in
the stylesheets the capture fetched (cross-origin ones included, which the browser's CSSOM refuses
to show), and an icon arrives as the page's own SVG markup. Both are cut down here to values a
generated page may carry: keyframes animate compositing and paint properties only, with values that
cannot load anything (no `url()`, no `var()`); an icon keeps drawing elements and drawing attributes
only. The same rules are the engine's (`lumen-core` `validate_style_tokens`), so nothing kept here
is refused later.
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable, Iterator

import tinycss2
from selectolax.lexbor import LexborHTMLParser

from ..evidence import KeyframeStep, MotionEvidence

KEYFRAME_PROPERTIES = frozenset({
    "opacity", "transform", "translate", "scale", "rotate", "filter", "color",
    "background-color", "border-color", "box-shadow", "background-position",
})
MAX_KEYFRAME_STEPS = 32
MAX_KEYFRAME_DECLARATIONS = 12
MAX_ICON_SVG_BYTES = 4096
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 ,.()%#+\-/]{1,200}$")
_UNSAFE = ("url(", "var(", "expression")
_SVG_ELEMENTS = frozenset({"svg", "g", "path", "circle", "ellipse", "line", "polyline", "polygon", "rect"})
_SVG_ATTRIBUTES = {
    name.lower(): name
    for name in (
        "viewBox", "d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
        "stroke-miterlimit", "fill-rule", "clip-rule", "cx", "cy", "r", "rx", "ry", "x", "y", "x1",
        "y1", "x2", "y2", "points", "width", "height", "transform", "opacity", "fill-opacity",
        "stroke-opacity",
    )
}
_ATTRIBUTE_VALUE = re.compile(r"^[A-Za-z0-9 ,.()%#+\-]{0,2000}$")


def safe_style_value(value: str) -> bool:
    """A CSS value that only draws: plain characters, nothing that loads or substitutes."""
    lower = value.lower()
    return bool(_SAFE_VALUE.match(value)) and not any(bad in lower for bad in _UNSAFE)


def _offsets(prelude: list) -> list[float]:
    """A keyframe selector's offsets, or `[]` when any part is not one: CSS ignores a rule whose
    selector is unparseable or outside 0-100%, and the engine refuses such an offset (LUMB0264)."""
    out: list[float] = []
    for part in tinycss2.serialize(prelude).split(","):
        word = part.strip().lower()
        if word == "from":
            out.append(0.0)
        elif word == "to":
            out.append(100.0)
        elif word.endswith("%"):
            try:
                offset = round(float(word[:-1]), 2)
            except ValueError:
                return []
            if not 0.0 <= offset <= 100.0:
                return []
            out.append(offset)
        else:
            return []
    return out


def _keyframes_rules(rules: Iterable[Any]) -> Iterator[tuple[str, list]]:
    for rule in rules:
        if getattr(rule, "type", "") != "at-rule" or rule.content is None:
            continue
        keyword = rule.lower_at_keyword
        if keyword in ("keyframes", "-webkit-keyframes"):
            yield tinycss2.serialize(rule.prelude).strip().strip("\"'"), rule.content
        elif keyword in ("media", "supports", "layer", "container"):
            yield from _keyframes_rules(
                tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
            )


def keyframe_steps(stylesheets: Iterable[Any], name: str) -> list[KeyframeStep]:
    """The last `@keyframes <name>` in cascade order, as clean steps; `[]` when absent or unusable."""
    found = None
    for sheet in stylesheets:
        text = getattr(sheet, "text", "") or ""
        if name not in text:
            continue
        parsed = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
        for rule_name, content in _keyframes_rules(parsed):
            if rule_name == name:
                found = content
    if found is None:
        return []
    steps: dict[float, dict[str, str]] = {}
    for rule in tinycss2.parse_rule_list(found, skip_comments=True, skip_whitespace=True):
        if getattr(rule, "type", "") != "qualified-rule":
            continue
        declarations: dict[str, str] = {}
        for decl in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
            if getattr(decl, "type", "") != "declaration":
                continue
            value = tinycss2.serialize(decl.value).strip()
            if decl.lower_name in KEYFRAME_PROPERTIES and safe_style_value(value):
                declarations[decl.lower_name] = value
        if not declarations:
            continue
        for offset in _offsets(rule.prelude):
            steps.setdefault(offset, {}).update(declarations)
    ordered = [
        KeyframeStep(offset=offset, declarations=dict(list(decls.items())[:MAX_KEYFRAME_DECLARATIONS]))
        for offset, decls in sorted(steps.items())
    ]
    return ordered if 2 <= len(ordered) <= MAX_KEYFRAME_STEPS else []


def attach_keyframes(motion: MotionEvidence, stylesheets: Iterable[Any]) -> MotionEvidence:
    """The animations whose definition the capture holds, with it; the rest are dropped."""
    sheets = list(stylesheets)
    kept = []
    for animation in motion.animations:
        steps = keyframe_steps(sheets, animation.name)
        if steps:
            kept.append(animation.model_copy(update={"frames": steps}))
    return motion.model_copy(update={"animations": kept})


def clean_icon_svg(markup: object) -> str | None:
    """A button icon's SVG with drawing elements and drawing attributes only, or None."""
    if not isinstance(markup, str) or "<svg" not in markup.lower():
        return None
    root = LexborHTMLParser(markup).css_first("svg")
    if root is None:
        return None

    def emit(node: Any) -> str:
        tag = (node.tag or "").lower()
        if tag not in _SVG_ELEMENTS:
            return ""
        attributes = []
        for name, value in (node.attributes or {}).items():
            key = _SVG_ATTRIBUTES.get(str(name).lower())
            text = "" if value is None else str(value)
            if key is None or not _ATTRIBUTE_VALUE.match(text) or "url(" in text.lower():
                continue
            attributes.append(f'{key}="{html.escape(text, quote=True)}"')
        inner = "".join(emit(child) for child in node.iter(include_text=False))
        return f"<{' '.join([tag, *attributes])}>{inner}</{tag}>"

    cleaned = emit(root)
    return cleaned if len(cleaned.encode()) <= MAX_ICON_SVG_BYTES else None
