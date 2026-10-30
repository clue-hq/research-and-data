"""What capture observed on an inline SVG, and the two ways it is used (2026-10-29).

Capture (`rendered._SERIALIZE_HTML_JS`) records what the browser showed on every element of every
top-level ``<svg>`` as data, never as a style:

* ``data-clue-svg-look`` — the element's own look: the values the page's rules set on it. An
  inherited property (colour, fill, stroke, font) is written only where it differs from the
  parent's, so inherited values keep flowing from whatever the site's own rules say;
* ``data-clue-svg-context`` (the root only) — the inherited values the root took from the page
  around it, which a logo file needs and a clone gets from its own section.

Two readers, two needs:

* a **logo** lifted into its own file has no page CSS at all, so :func:`bake_svg_looks` writes the
  context and the look back inline with ``!important``, as capture used to (an inline logo that
  takes its colour from the page must not turn black);
* a **clone** carries the site's own rules — hover, focus, the phone layout — so
  :func:`lift_svg_looks` turns each look into a zero-specificity rule placed before them: the
  site's rule wins wherever one reaches the element, and the observed value applies only where
  nothing does. Inline ``!important`` beat every one of those rules (Pallet's hero arrow could
  never nudge on hover, 2026-10-28).
"""

from __future__ import annotations

from typing import Mapping

import tinycss2
from selectolax.lexbor import LexborHTMLParser

__all__ = ["CONTEXT_ATTR", "FALLBACK_ATTR", "LOOK_ATTR", "bake_svg_looks", "lift_svg_looks", "look_hides"]

LOOK_ATTR = "data-clue-svg-look"
CONTEXT_ATTR = "data-clue-svg-context"
#: A clone element's handle for its fallback rule: ``:where([data-clue-svg="<n>"])``.
FALLBACK_ATTR = "data-clue-svg"


def _declarations(text: str | None) -> list[tuple[str, str]]:
    out = []
    for item in tinycss2.parse_declaration_list(text or "", skip_comments=True, skip_whitespace=True):
        if item.type == "declaration":
            out.append((item.lower_name, tinycss2.serialize(item.value).strip()))
    return out


def look_hides(attributes: Mapping[str, str | None]) -> bool:
    """Whether an element was hidden where it was captured (``display: none`` or not visible)."""

    look = dict(_declarations(attributes.get(LOOK_ATTR)))
    return look.get("display") == "none" or look.get("visibility") in ("hidden", "collapse")


def _fragment_html(tree: LexborHTMLParser) -> str:
    body = tree.body
    return "".join(child.html or "" for child in body.iter(include_text=True)) if body is not None else ""


def bake_svg_looks(markup: str) -> str:
    """An inline SVG as a standalone file: its context and every look written inline with
    ``!important``, artwork that was hidden where it was captured left out."""

    if LOOK_ATTR not in markup and CONTEXT_ATTR not in markup:
        return markup
    tree = LexborHTMLParser(markup)
    root = tree.css_first("svg")
    for node in tree.css(f"[{LOOK_ATTR}], [{CONTEXT_ATTR}]"):
        if node is not root and dict(_declarations(node.attributes.get(LOOK_ATTR))).get("display") == "none":
            node.decompose()
            continue
        baked = _declarations(node.attributes.get(CONTEXT_ATTR)) + _declarations(node.attributes.get(LOOK_ATTR))
        own = (node.attributes.get("style") or "").strip().rstrip(";").strip()
        style = "; ".join([own] * bool(own) + [f"{name}: {value} !important" for name, value in baked])
        for name in (LOOK_ATTR, CONTEXT_ATTR):
            if name in node.attributes:
                del node.attrs[name]
        if style:
            node.attrs["style"] = style
    return _fragment_html(tree)


def lift_svg_looks(markup: str) -> tuple[str, str]:
    """A section's markup with its SVG looks taken out, and the fallback CSS they become: one
    ``:where([data-clue-svg="<n>"])`` rule per element that had a look, in document order. The
    rules go BEFORE the section's own, so any rule of the site's that reaches an element wins."""

    if LOOK_ATTR not in markup and CONTEXT_ATTR not in markup:
        return markup, ""
    tree = LexborHTMLParser(markup)
    rules: list[str] = []
    for node in tree.css(f"[{LOOK_ATTR}], [{CONTEXT_ATTR}]"):
        look = _declarations(node.attributes.get(LOOK_ATTR))
        for name in (LOOK_ATTR, CONTEXT_ATTR):
            if name in node.attributes:
                del node.attrs[name]
        if look:
            handle = str(len(rules) + 1)
            node.attrs[FALLBACK_ATTR] = handle
            body = "; ".join(f"{name}: {value}" for name, value in look)
            rules.append(f':where([{FALLBACK_ATTR}="{handle}"]) {{ {body} }}\n')
    return _fragment_html(tree), "".join(rules)
