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
#: How many elements an icon may nest, its `<svg>` included (the engine's `MAX_ICON_SVG_DEPTH`).
MAX_ICON_SVG_DEPTH = 32
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 ,.()%#+\-/]{1,200}$")
_UNSAFE = ("url(", "var(", "expression")
#: The elements that put ink down; a `<g>` or `<svg>` alone draws nothing.
_SVG_DRAWING_ELEMENTS = frozenset(
    {"path", "circle", "ellipse", "line", "polyline", "polygon", "rect"}
)
_SVG_ELEMENTS = _SVG_DRAWING_ELEMENTS | {"svg", "g"}
_SVG_ATTRIBUTES = {
    name.lower(): name
    for name in (
        "viewBox", "d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
        "stroke-miterlimit", "fill-rule", "clip-rule", "cx", "cy", "r", "rx", "ry", "x", "y", "x1",
        "y1", "x2", "y2", "points", "width", "height", "transform", "opacity", "fill-opacity",
        "stroke-opacity",
    )
}
#: An attribute value, checked with `fullmatch`: `$` alone also matches before a trailing newline.
_ATTRIBUTE_VALUE = re.compile(r"^[A-Za-z0-9 ,.()%#+\-]{0,2000}$")
#: A run of ASCII whitespace inside an attribute value: the cleaner writes each as one space, so a
#: `d` or `points` written over several lines is kept, on one line.
_ATTRIBUTE_WHITESPACE = re.compile(r"[ \t\n\r\f]+")
#: The attributes each drawing element draws with. It draws only when its cleaned markup carries all
#: of them with a value — a `line` any one of them, since the others default to 0.
_SVG_GEOMETRY = {
    "path": ("d",), "circle": ("r",), "ellipse": ("rx", "ry"), "rect": ("width", "height"),
    "line": ("x1", "y1", "x2", "y2"), "polyline": ("points",), "polygon": ("points",),
}


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
    """A button icon's SVG with drawing elements and drawing attributes only, or None. Whitespace
    inside a value is written as one space, so a `d` over several lines is kept on one line. None
    when nothing is left to draw — no drawing element keeps its geometry (an unresolved sprite `<use>`
    cleans to a bare `<svg>`) — and when any drawing element lost geometry it had (a `d` over the
    value cap): an icon missing a piece is a wrong icon. None too when it nests deeper than
    `MAX_ICON_SVG_DEPTH` or comes out longer than `MAX_ICON_SVG_BYTES`. What it returns is the one
    form the engine accepts (`normalizer.component_tokens.svg_ok`)."""
    if not isinstance(markup, str) or "<svg" not in markup.lower():
        return None
    root = LexborHTMLParser(markup).css_first("svg")
    if root is None:
        return None

    draws = lost = too_deep = False

    def emit(node: Any, depth: int) -> str:
        nonlocal draws, lost, too_deep
        tag = (node.tag or "").lower()
        if tag not in _SVG_ELEMENTS:
            return ""
        if depth > MAX_ICON_SVG_DEPTH:
            too_deep = True
            return ""
        geometry = _SVG_GEOMETRY.get(tag, ())
        kept: dict[str, str] = {}
        for name, value in (node.attributes or {}).items():
            key = _SVG_ATTRIBUTES.get(str(name).lower())
            if key is None:
                continue
            text = _ATTRIBUTE_WHITESPACE.sub(" ", "" if value is None else str(value)).strip(" ")
            if not _ATTRIBUTE_VALUE.fullmatch(text) or "url(" in text.lower():
                lost = lost or key in geometry
                continue
            kept[key] = text
        present = [bool(kept.get(key)) for key in geometry]
        draws = draws or (any(present) if tag == "line" else bool(present) and all(present))
        attributes = [f'{key}="{html.escape(text, quote=True)}"' for key, text in kept.items()]
        inner = "".join(emit(child, depth + 1) for child in node.iter(include_text=False))
        return f"<{' '.join([tag, *attributes])}>{inner}</{tag}>"

    cleaned = emit(root, 1)
    if not draws or lost or too_deep or len(cleaned.encode()) > MAX_ICON_SVG_BYTES:
        return None
    return cleaned
