"""The published-site cleaner (Wave 2 Contract 3): strip, never refuse.

Every published or thumbnailed Puck site page passes through
:func:`sanitize_site_html` — the whole page (ruling 2026-10-11): agent sections, the seller's
clones and our own sections alike. Published sites are script-free. What goes, and why:

* elements, with their content: ``script iframe object embed form base meta link`` (the
  contract's list), plus ``noscript template frame frameset applet portal``, SVG's
  ``foreignObject`` and the SMIL animation elements, for the fragment sanitizer's reasons
  (``lumen_api/fragments/sanitize.py``: each is a way past an attribute-time gate). ``<style>``
  stays — the theme and the clones' captured CSS live there — and its ``url()``s are cleaned;
* every ``on*`` attribute, by prefix, and ``ping``, ``formaction``, ``action``, ``srcdoc``;
* a link (``href``, ``xlink:href``, ``cite``) whose scheme is not http(s), mailto, tel or sms
  (``fragments/refs.link_scheme_allowed``) — the attribute, not the element;
* a byte-loading reference (``src``, every ``srcset`` candidate, ``poster``, ``background``, an
  SVG asset ``href``, a CSS ``url()`` or ``image-set()``) that is not ``/asset-store/<sha256>``,
  a site-relative path, an in-document ``#fragment`` or ``data:``.

The caller adds its own head (charset, viewport, CSP, description, icon, manifest link) AFTER this
runs, so nothing of ours is ever stripped.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

import tinycss2
from selectolax.lexbor import LexborHTMLParser, LexborNode
from tinycss2 import ast

from .fragments.refs import asset_url_digest, link_scheme_allowed
from .fragments.sanitize import parse_srcset_candidates

STRIPPED_ELEMENTS = frozenset(
    {
        "script", "iframe", "object", "embed", "form", "base", "meta", "link",
        "noscript", "template", "frame", "frameset", "applet", "portal", "foreignobject",
        "animate", "set", "animatetransform", "animatemotion", "animatecolor", "discard",
    }
)
_ASSET_ATTRS = frozenset({"src", "poster", "background", "lowsrc", "dynsrc"})
_ASSET_LIST_ATTRS = frozenset({"srcset", "imagesrcset"})
_SVG_ASSET_ELEMENTS = frozenset({"use", "image", "feimage", "textpath", "mpath", "pattern"})
_LINK_ATTRS = frozenset({"href", "xlink:href", "cite"})
_ALWAYS_STRIPPED_ATTRS = frozenset({"ping", "formaction", "action", "srcdoc"})
_IMAGE_SET_FUNCTIONS = frozenset({"image-set", "-webkit-image-set"})


@dataclass(frozen=True)
class SanitizedHtml:
    html: str
    #: One note per removal, in document order ("stripped <script> and its content").
    removed: tuple[str, ...]


def asset_reference_allowed(value: str) -> bool:
    """Whether a byte-loading reference may stay on a published site page."""
    text = value.strip()
    if not text or text.startswith("#") or text.lower().startswith("data:"):
        return True
    if asset_url_digest(text) is not None:
        return True
    # A site-relative path; "//host" and "/\host" are other hosts to a browser.
    return text.startswith("/") and not text.startswith("//") and "\\" not in text


def _none(token: ast.Node) -> ast.IdentToken:
    return ast.IdentToken(token.source_line, token.source_column, "none")


def _clean_css_tokens(tokens: list[ast.Node], removed: list[str]) -> None:
    for index, token in enumerate(tokens):
        if isinstance(token, ast.URLToken):
            if not asset_reference_allowed(token.value):
                removed.append(f"stripped css url({token.value[:80]})")
                tokens[index] = _none(token)
        elif isinstance(token, ast.FunctionBlock):
            if token.lower_name == "url":
                target = next((arg.value for arg in token.arguments if isinstance(arg, ast.StringToken)), "")
                if not asset_reference_allowed(target):
                    removed.append(f"stripped css url({target[:80]})")
                    tokens[index] = _none(token)
            elif token.lower_name in _IMAGE_SET_FUNCTIONS:
                removed.append(f"stripped css {token.lower_name}()")
                tokens[index] = _none(token)
            else:
                _clean_css_tokens(token.arguments, removed)
        elif isinstance(token, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)):
            _clean_css_tokens(token.content, removed)


def clean_css(css: str, removed: list[str]) -> str:
    """A stylesheet with every foreign ``url()``/``image-set()`` replaced by ``none`` and every
    ``@import`` dropped."""
    kept: list[ast.Node] = []
    for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=False):
        if isinstance(rule, ast.AtRule) and rule.lower_at_keyword == "import":
            removed.append("stripped @import")
            continue
        if isinstance(rule, (ast.QualifiedRule, ast.AtRule)):
            _clean_css_tokens(rule.prelude, removed)
            if rule.content is not None:
                _clean_css_tokens(rule.content, removed)
        kept.append(rule)
    return tinycss2.serialize(kept)


def _clean_declarations(declarations: str, removed: list[str]) -> str:
    tokens = tinycss2.parse_component_value_list(declarations)
    _clean_css_tokens(tokens, removed)
    return tinycss2.serialize(tokens)


def _drop_elements(root: LexborNode, removed: list[str]) -> None:
    # Re-scan after each removal: decomposing a node invalidates its descendants.
    while True:
        target = next(
            (node for node in root.traverse(include_text=False) if (node.tag or "").lower() in STRIPPED_ELEMENTS),
            None,
        )
        if target is None:
            return
        removed.append(f"stripped <{(target.tag or '').lower()}> and its content")
        target.decompose()


def _clean_style_elements(tree: LexborHTMLParser, removed: list[str]) -> None:
    for node in list(tree.css("style")):
        css = node.text(deep=True)
        before = len(removed)
        cleaned = clean_css(css, removed)
        if len(removed) == before:
            continue
        attributes = "".join(f' {name}="{escape(value or "", quote=True)}"' for name, value in node.attributes.items())
        # "</" cannot appear in a stylesheet outside a string; escaping it keeps the new element whole.
        body = cleaned.replace("</", "<\\/")
        replacement = LexborHTMLParser("<style" + attributes + ">" + body + "</style>").css_first("style")
        if replacement is not None:
            node.replace_with(replacement)


def _clean_attributes(node: LexborNode, removed: list[str]) -> None:
    tag = (node.tag or "").lower()
    for name, value in list(node.attributes.items()):
        lowered = name.lower()
        raw = value or ""
        if lowered.startswith("on") or lowered in _ALWAYS_STRIPPED_ATTRS:
            del node.attrs[name]
            removed.append(f"stripped {lowered} on <{tag}>")
        elif lowered in _ASSET_ATTRS or (lowered in ("href", "xlink:href") and tag in _SVG_ASSET_ELEMENTS):
            if not asset_reference_allowed(raw):
                del node.attrs[name]
                removed.append(f"stripped {lowered}={raw.strip()[:80]} on <{tag}>")
        elif lowered in _ASSET_LIST_ATTRS:
            candidates = parse_srcset_candidates(raw)
            kept = [f"{url} {descriptor}".strip() for url, descriptor in candidates if asset_reference_allowed(url)]
            if len(kept) != len(candidates):
                removed.append(f"stripped {len(candidates) - len(kept)} {lowered} candidate(s) on <{tag}>")
                if kept:
                    node.attrs[name] = ", ".join(kept)
                else:
                    del node.attrs[name]
        elif lowered == "style":
            before = len(removed)
            cleaned = _clean_declarations(raw, removed)
            if len(removed) != before:
                node.attrs[name] = cleaned
        elif lowered in _LINK_ATTRS and not link_scheme_allowed(raw):
            del node.attrs[name]
            removed.append(f"stripped {lowered}={raw.strip()[:80]} on <{tag}>")


def sanitize_site_html(html: str) -> SanitizedHtml:
    """``html`` with everything a published site may not carry stripped (see the module docstring)."""
    removed: list[str] = []
    tree = LexborHTMLParser(html)
    root = tree.root
    if root is None:
        return SanitizedHtml(html="", removed=("input had no content",))
    _drop_elements(root, removed)
    _clean_style_elements(tree, removed)
    for node in root.traverse(include_text=False):
        if node.tag:
            _clean_attributes(node, removed)
    out = tree.html or ""
    if html.lstrip()[:9].lower() == "<!doctype" and out.lstrip()[:9].lower() != "<!doctype":
        out = "<!DOCTYPE html>" + out
    return SanitizedHtml(html=out, removed=tuple(removed))
