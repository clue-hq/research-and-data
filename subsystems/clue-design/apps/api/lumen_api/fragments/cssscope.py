"""Scoping one cloned section's CSS so it cannot reach the rest of the page (F1.2).

A captured section ships the stylesheet rules it was written against — ``.btn``, ``h1``,
``:root``. Dropped into a document verbatim those rules would style everything else on the page
too, so every selector is re-anchored under the fragment's own wrapper class
(:func:`~lumen_api.fragments.refs.fragment_wrapper_class`), which the F1.3 render arm emits
around the markup.

The rulings this file implements, and why:

* **Media queries (and ``@supports``/``@container``/``@layer``) are preserved, and the selectors
  INSIDE them are scoped.** A responsive section that lost its breakpoints would be a different
  section.
* **``@import`` is stripped, loudly.** It is a live fetch of arbitrary CSS from a third party at
  render time — the one construct that could reintroduce everything the sanitizer just removed.
  It leaves a note rather than vanishing, because "your section's imported stylesheet is gone" is
  something a human has to be told.
* **``@font-face`` passes through UNSCOPED.** A font family is a global name by construction:
  ``.lumen-frag-x @font-face`` is not a thing, and a scoped one would simply never define the
  family the rules below it ask for. Faces are already rehosted (their ``url()`` still goes
  through the reference gate here) and are subject to the D-F2 licence posture at publish, so
  passing them through is a scoping decision, not a licensing one.
* **``@keyframes`` names are NAMESPACED** to ``<name>--<wrapper class>``, and every
  ``animation``/``animation-name`` declaration in this same stylesheet that names one is rewritten
  to match. Keyframe names live in a single global namespace, so two cloned sections that both
  animate ``fade`` would otherwise silently overwrite each other's timeline — the last stylesheet
  parsed wins, which is a bug that only appears once a second fragment lands on the page. A name
  that no local ``@keyframes`` declares is left alone: it belongs to the host document.
* **``:root``/``html``/``body`` selectors BECOME the wrapper** instead of being prefixed. Prefixing
  produces ``.lumen-frag-x :root``, which matches nothing, and a modern section keeps its custom
  properties on ``:root`` — so prefixing would silently strip the section's entire colour scheme.
  Rewriting to the wrapper puts those declarations on the element that actually contains the
  section. A note records it either way.

Every ``url()`` — at any nesting depth — goes through the same fail-closed reference gate the
HTML sanitizer uses (:func:`~lumen_api.fragments.refs.resolve_asset_reference`), so a section
whose background image was never rehosted refuses rather than rendering a hole.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import tinycss2
from tinycss2 import ast

from .refs import FragmentRefused, asset_url, fragment_wrapper_class, resolve_asset_reference

#: At-rules whose block holds declarations, not nested rules, and which are NOT scoped.
_GLOBAL_BLOCK_AT_RULES = frozenset({"font-face", "page", "counter-style", "property"})

#: Statement at-rules refused outright: a live third-party fetch, and two document-level
#: declarations that mean nothing inside a section subtree.
_REFUSED_AT_RULES = frozenset({"import", "charset", "namespace"})

_KEYFRAMES_AT_RULES = frozenset({"keyframes", "-webkit-keyframes", "-moz-keyframes"})

_ANIMATION_PROPERTIES = frozenset(
    {"animation", "animation-name", "-webkit-animation", "-webkit-animation-name"}
)

#: Selectors that address the document rather than anything inside the section.
_DOCUMENT_SELECTORS = frozenset({":root", "html", "body", "html body", ":host"})


@dataclass(frozen=True)
class ScopedCss:
    """One fragment's stylesheet, re-anchored and reference-checked."""

    css: str
    asset_digests: tuple[str, ...]
    notes: tuple[str, ...]


def scope_fragment_css(
    css: str, *, fragment_id: str, rehosted: Mapping[str, str]
) -> ScopedCss:
    """Scope one fragment's source CSS under its wrapper class. Refuses on a bad reference."""
    wrapper = fragment_wrapper_class(fragment_id)
    notes: list[str] = []
    digests: set[str] = set()
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    keyframe_names = _declared_keyframe_names(rules)
    renames = {name: f"{name}--{wrapper}" for name in keyframe_names}
    body = _scope_rules(rules, wrapper=wrapper, renames=renames, rehosted=rehosted,
                        digests=digests, notes=notes)
    return ScopedCss(css=body, asset_digests=tuple(sorted(digests)), notes=tuple(notes))


def rewrite_declaration_urls(
    declarations: str, rehosted: Mapping[str, str]
) -> tuple[str, tuple[str, ...]]:
    """Reference-gate the ``url()`` tokens of a bare declaration list (a ``style=`` attribute).

    Shared with the HTML sanitizer so an inline ``background-image`` is exactly as gated as the
    same declaration in a stylesheet — an ungated inline style would be the obvious hole in an
    otherwise fail-closed rule.
    """
    digests: set[str] = set()
    tokens = tinycss2.parse_component_value_list(declarations)
    _rewrite_urls(tokens, rehosted=rehosted, digests=digests)
    return tinycss2.serialize(tokens), tuple(sorted(digests))


# --------------------------------------------------------------------------- #
# rule walking
# --------------------------------------------------------------------------- #


def _scope_rules(
    rules: Sequence[object],
    *,
    wrapper: str,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
) -> str:
    out: list[str] = []
    for rule in rules:
        rendered = _scope_rule(
            rule, wrapper=wrapper, renames=renames, rehosted=rehosted, digests=digests, notes=notes
        )
        if rendered:
            out.append(rendered)
    return "\n".join(out)


def _scope_rule(
    rule: object,
    *,
    wrapper: str,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
) -> str:
    if isinstance(rule, ast.QualifiedRule):
        selector = _scope_selector(rule.prelude, wrapper=wrapper, notes=notes)
        if not selector:
            return ""
        content = _declaration_block(
            rule.content, renames=renames, rehosted=rehosted, digests=digests
        )
        return f"{selector} {{{content}}}"

    if isinstance(rule, ast.AtRule):
        return _scope_at_rule(
            rule, wrapper=wrapper, renames=renames, rehosted=rehosted, digests=digests, notes=notes
        )

    if isinstance(rule, ast.ParseError):
        notes.append(f"dropped unparseable css: {rule.message}")
        return ""
    return ""


def _scope_at_rule(
    rule: ast.AtRule,
    *,
    wrapper: str,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
) -> str:
    keyword = rule.lower_at_keyword
    prelude = tinycss2.serialize(rule.prelude).strip()

    if keyword in _REFUSED_AT_RULES:
        notes.append(f"stripped @{keyword} — a fragment may not pull in document-level css")
        return ""

    if rule.content is None:
        # A statement at-rule we have no opinion about (`@layer a, b;`): pass it through.
        return f"@{keyword} {prelude};".replace("  ", " ")

    if keyword in _GLOBAL_BLOCK_AT_RULES:
        # Global by nature — declarations only, no selectors to scope. References still gated.
        content = _declaration_block(
            rule.content, renames=renames, rehosted=rehosted, digests=digests
        )
        head = f"@{keyword} {prelude}".rstrip()
        return f"{head} {{{content}}}"

    if keyword in _KEYFRAMES_AT_RULES:
        name = _keyframes_name(rule.prelude)
        renamed = renames.get(name, name)
        inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
        frames = [
            f"{tinycss2.serialize(frame.prelude).strip()} "
            f"{{{_declaration_block(frame.content, renames=renames, rehosted=rehosted, digests=digests)}}}"
            for frame in inner
            if isinstance(frame, ast.QualifiedRule)
        ]
        return f"@{keyword} {renamed} {{ {' '.join(frames)} }}"

    # Everything else with a block (@media, @supports, @container, @layer {…}) nests RULES:
    # preserve the condition and scope what is inside it, at any depth.
    inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
    body = _scope_rules(
        inner, wrapper=wrapper, renames=renames, rehosted=rehosted, digests=digests, notes=notes
    )
    head = f"@{keyword} {prelude}".rstrip()
    return f"{head} {{ {body} }}"


def _scope_selector(prelude: Sequence[object], *, wrapper: str, notes: list[str]) -> str:
    parts: list[str] = []
    for group in _split_on_commas(prelude):
        text = tinycss2.serialize(group).strip()
        if not text:
            continue
        if text.lower() in _DOCUMENT_SELECTORS:
            notes.append(
                f"rewrote document-level selector {text!r} to the fragment wrapper "
                "(its declarations, including custom properties, now apply to the section)"
            )
            parts.append(f".{wrapper}")
        else:
            parts.append(f".{wrapper} {text}")
    return ", ".join(parts)


def _split_on_commas(tokens: Sequence[object]) -> list[list[object]]:
    groups: list[list[object]] = [[]]
    for token in tokens:
        if isinstance(token, ast.LiteralToken) and token.value == ",":
            groups.append([])
        else:
            groups[-1].append(token)
    return groups


def _keyframes_name(prelude: Sequence[object]) -> str:
    for token in prelude:
        if isinstance(token, ast.IdentToken):
            return token.value
        if isinstance(token, ast.StringToken):
            return token.value
    return ""


def _declared_keyframe_names(rules: Sequence[object]) -> set[str]:
    """Every ``@keyframes`` name this stylesheet declares, at any nesting depth."""
    names: set[str] = set()
    for rule in rules:
        if not isinstance(rule, ast.AtRule) or rule.content is None:
            continue
        if rule.lower_at_keyword in _KEYFRAMES_AT_RULES:
            name = _keyframes_name(rule.prelude)
            if name:
                names.add(name)
        elif rule.lower_at_keyword not in _GLOBAL_BLOCK_AT_RULES:
            names |= _declared_keyframe_names(
                tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
            )
    return names


# --------------------------------------------------------------------------- #
# declaration blocks: url() gating + animation-name namespacing
# --------------------------------------------------------------------------- #


def _declaration_block(
    tokens: Sequence[object],
    *,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
) -> str:
    """Serialize one ``{…}`` body, rewriting references and animation names IN PLACE.

    Deliberately token-level rather than ``parse_declaration_list``: the token list keeps the
    author's exact whitespace, comments, vendor prefixes and even declarations tinycss2 considers
    malformed (which browsers routinely still honour). A cloned section's CSS is not ours to
    reformat — we are re-anchoring it, not rewriting it.
    """
    mutable = list(tokens)
    _rewrite_urls(mutable, rehosted=rehosted, digests=digests)
    if renames:
        _rewrite_animation_names(mutable, renames=renames)
    return tinycss2.serialize(mutable)


def _rewrite_urls(tokens: Sequence[object], *, rehosted: Mapping[str, str], digests: set[str]) -> None:
    for token in tokens:
        if isinstance(token, ast.URLToken):
            digest = resolve_asset_reference(token.value, rehosted)
            if digest is None:
                continue
            digests.add(digest)
            token.value = asset_url(digest)
            # URLToken serializes its `representation`, not its value.
            token.representation = f'url("{token.value}")'
        elif isinstance(token, ast.FunctionBlock):
            if token.lower_name == "url":
                _rewrite_url_function(token, rehosted=rehosted, digests=digests)
            else:
                _rewrite_urls(token.arguments, rehosted=rehosted, digests=digests)
        elif isinstance(token, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)):
            _rewrite_urls(token.content, rehosted=rehosted, digests=digests)


def _rewrite_url_function(
    token: ast.FunctionBlock, *, rehosted: Mapping[str, str], digests: set[str]
) -> None:
    for argument in token.arguments:
        if isinstance(argument, ast.StringToken):
            digest = resolve_asset_reference(argument.value, rehosted)
            if digest is None:
                continue
            digests.add(digest)
            argument.value = asset_url(digest)
            argument.representation = f'"{argument.value}"'
            return
    # `url(var(--x))` and friends: a reference we cannot read is a reference we cannot vouch for.
    raise FragmentRefused(
        "fragment.unreadable_reference",
        f"fragment css has a url() we cannot resolve: {tinycss2.serialize([token])}",
        reference=tinycss2.serialize([token]),
    )


def _rewrite_animation_names(tokens: list[object], *, renames: Mapping[str, str]) -> None:
    for segment in _split_declarations(tokens):
        property_name = _declaration_property(segment)
        if property_name not in _ANIMATION_PROPERTIES:
            continue
        for token in segment:
            if isinstance(token, ast.IdentToken) and token.value in renames:
                token.value = renames[token.value]


def _split_declarations(tokens: Sequence[object]) -> list[list[object]]:
    segments: list[list[object]] = [[]]
    for token in tokens:
        if isinstance(token, ast.LiteralToken) and token.value == ";":
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _declaration_property(segment: Sequence[object]) -> str | None:
    for token in segment:
        if isinstance(token, ast.WhitespaceToken) or isinstance(token, ast.Comment):
            continue
        if isinstance(token, ast.IdentToken):
            return token.value.lower()
        return None
    return None
