"""Which of a captured page's CSS rules belong to ONE of its sections (clone-fidelity F2.2).

A cloned section ships the rules it was written against. Those rules live in the page's
stylesheets — all of them, for the whole site — so minting has to choose. This module makes the
choice, and it makes it **conservatively**, because the two ways of being wrong are not
symmetric:

* keep a rule the section does not use → the artifact carries some dead CSS. It costs bytes.
* drop a rule the section does use → the clone renders wrong, and the reason is invisible: the
  markup is right there, the stylesheet the human is reading has the rule in it, and nothing
  says it was dropped.

So the rule is: **a rule is kept when its selector's rightmost compound COULD match an element
inside the subtree.** Rightmost only — a real page's rules are written from the page root
(``.page-wrapper .hero_wrap .body-copy``), and a section subtree does not contain its own
ancestors by construction, so checking the whole selector would drop almost everything. And
*could*, not *does*: pseudo-classes, attribute selectors and functional pseudos are ignored
rather than evaluated, which can only ever keep MORE.

Three families are kept unconditionally, because they have no selector to match against:

* ``@font-face`` — the section's rules name a family; a face that is not defined is a font that
  does not load. Its ``url()`` still goes through the fragment reference gate downstream.
* ``@keyframes`` / ``@property`` / ``@counter-style`` — named global definitions the kept
  declarations refer to by name. The scoper namespaces the keyframe names afterwards.
* document-level selectors (``:root``, ``html``, ``body``) — a modern section keeps its custom
  properties there. The subtree contains no ``<html>``, so a naive match would drop the
  section's whole colour scheme before the scoper ever got to re-anchor it onto the wrapper.

The output is CSS text in source order, sheet by sheet, so the cascade a page relied on survives
the extraction. Nothing here rewrites a declaration: references, scoping and the markup-breakout
gate are the scoper's job, and this module must not pre-empt a fail-closed check by reformatting
what it will read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import tinycss2
from selectolax.parser import HTMLParser
from tinycss2 import ast

#: At-rules whose block holds declarations (not nested rules) and which are kept whole: they
#: define something the kept rules NAME, and a name with no definition is a silent failure.
_GLOBAL_BLOCK_AT_RULES = frozenset(
    {"font-face", "page", "counter-style", "property", "keyframes", "-webkit-keyframes",
     "-moz-keyframes"}
)

#: At-rules that nest RULES: recursed into, kept only if something inside survived.
_CONDITIONAL_AT_RULES = frozenset({"media", "supports", "container", "layer", "scope"})

#: Tag selectors that address the document rather than anything inside a section. The scoper
#: rewrites these onto the fragment wrapper (``cssscope._DOCUMENT_SELECTORS``), so dropping them
#: here would silently undo that rewrite before it could happen.
_DOCUMENT_TAGS = frozenset({"html", "body"})

#: Combinators that end a compound selector.
_COMBINATORS = frozenset({">", "+", "~", " ", "\t", "\n", "\r", "\f"})


@dataclass(frozen=True)
class MatchedCss:
    """The rules one section gets, and the arithmetic behind that choice.

    The counts are on the record rather than in a log line because "how much of the page's CSS
    did this fragment take?" is the question a human asks when a clone looks wrong, and it is
    the one number that separates "we dropped its rules" from "the page never had any".
    """

    css: str
    rules_considered: int
    rules_kept: int
    sheets_read: int
    notes: tuple[str, ...] = ()
    #: ``(sheet url, that sheet's kept rules)`` in source order. The joined text is what gets
    #: stored, but a ``url()`` inside a rule resolves against the sheet it was WRITTEN in — an
    #: ``/img/x.png`` in a stylesheet served from a CDN is a CDN url, not a page-relative one —
    #: so the reference harvest needs the blocks kept apart to know each one's base.
    blocks: tuple[tuple[str, str], ...] = ()

    @property
    def byte_length(self) -> int:
        return len(self.css.encode("utf-8"))


@dataclass(frozen=True)
class _Inventory:
    """What a subtree contains, in the only three terms a compound selector can ask about."""

    tags: frozenset[str]
    ids: frozenset[str]
    classes: frozenset[str]

    @classmethod
    def of(cls, html: str) -> "_Inventory":
        tree = HTMLParser(html or "")
        tags: set[str] = set()
        ids: set[str] = set()
        classes: set[str] = set()
        root = tree.body or tree.root
        if root is None:
            return cls(frozenset(), frozenset(), frozenset())
        for node in root.traverse(include_text=False):
            tag = (node.tag or "").lower()
            if not tag or tag in ("body", "html", "-undef"):
                continue
            tags.add(tag)
            element_id = (node.attributes.get("id") or "").strip()
            if element_id:
                ids.add(element_id)
            classes.update((node.attributes.get("class") or "").split())
        return cls(frozenset(tags), frozenset(ids), frozenset(classes))


def rules_for_subtree(
    stylesheets: Sequence[Any], *, subtree_html: str
) -> MatchedCss:
    """The page's rules that could style this subtree, in source order.

    ``stylesheets`` is duck-typed on ``LoadedStylesheet`` (``.url``, ``.text``) so this module
    never imports the snapshot read seam — the same discipline Task 11 applied to the segmenter,
    and for the same reason: a pure function must not drag the DAL in behind it.
    """
    inventory = _Inventory.of(subtree_html)
    counter = _Counter()
    blocks: list[tuple[str, str]] = []
    notes: list[str] = []
    sheets_read = 0
    for sheet in stylesheets:
        text = getattr(sheet, "text", "") or ""
        sheets_read += 1
        if not text.strip():
            continue
        rules = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
        sheet_url = str(getattr(sheet, "url", "") or "")
        rendered = _keep_rules(rules, inventory, counter, notes, sheet_url)
        if rendered:
            blocks.append((sheet_url, rendered))
    return MatchedCss(
        css="\n".join(block for _url, block in blocks),
        rules_considered=counter.considered,
        rules_kept=counter.kept,
        sheets_read=sheets_read,
        notes=tuple(notes),
        blocks=tuple(blocks),
    )


class _Counter:
    def __init__(self) -> None:
        self.considered = 0
        self.kept = 0


def _keep_rules(
    rules: Iterable[object],
    inventory: _Inventory,
    counter: _Counter,
    notes: list[str],
    sheet_url: str,
) -> str:
    out: list[str] = []
    for rule in rules:
        rendered = _keep_rule(rule, inventory, counter, notes, sheet_url)
        if rendered:
            out.append(rendered)
    return "\n".join(out)


def _keep_rule(
    rule: object,
    inventory: _Inventory,
    counter: _Counter,
    notes: list[str],
    sheet_url: str,
) -> str:
    if isinstance(rule, ast.QualifiedRule):
        counter.considered += 1
        selector = tinycss2.serialize(rule.prelude).strip()
        if not _selector_could_match(selector, inventory):
            return ""
        counter.kept += 1
        return f"{selector} {{{tinycss2.serialize(rule.content)}}}"

    if isinstance(rule, ast.AtRule):
        return _keep_at_rule(rule, inventory, counter, notes, sheet_url)

    if isinstance(rule, ast.ParseError):
        # A page's stylesheet is not ours to be strict about: browsers skip what they cannot
        # parse and render the rest, and so do we. Named, not swallowed.
        notes.append(f"skipped unparseable css in {sheet_url or 'a stylesheet'}: {rule.message}")
        return ""
    return ""


def _keep_at_rule(
    rule: ast.AtRule,
    inventory: _Inventory,
    counter: _Counter,
    notes: list[str],
    sheet_url: str,
) -> str:
    keyword = rule.lower_at_keyword
    prelude = tinycss2.serialize(rule.prelude).strip()

    if rule.content is None:
        # A statement at-rule (`@import url(x);`, `@layer a, b;`). Kept verbatim: the fragment
        # scoper has rulings about these (strip @import loudly, pass @layer through) and it is
        # the one place that decision belongs.
        return f"@{keyword} {prelude};".strip()

    if keyword in _GLOBAL_BLOCK_AT_RULES:
        return f"@{keyword} {prelude} {{{tinycss2.serialize(rule.content)}}}".replace(
            "  ", " "
        )

    if keyword in _CONDITIONAL_AT_RULES:
        inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
        body = _keep_rules(inner, inventory, counter, notes, sheet_url)
        if not body.strip():
            return ""
        head = f"@{keyword} {prelude}".rstrip()
        return f"{head} {{ {body} }}"

    # An at-rule nobody here has an opinion about. Keeping it is the conservative direction and
    # the scoper is the gate that decides what may actually be stored.
    return f"@{keyword} {prelude} {{{tinycss2.serialize(rule.content)}}}"


# --------------------------------------------------------------------------- #
# selector matching
# --------------------------------------------------------------------------- #


def _selector_could_match(selector: str, inventory: _Inventory) -> bool:
    """Any one part of a selector list matching is enough to keep the whole rule.

    A selector list is one rule with one declaration block; there is no way to keep half of it,
    and dropping it because two of its three parts belong elsewhere would drop the third.
    """
    if not selector:
        return False
    return any(
        _compound_could_match(_rightmost_compound(part), inventory)
        for part in _split_selector_list(selector)
    )


def _split_selector_list(selector: str) -> list[str]:
    """Split on top-level commas — the ones outside ``(``/``[``/quotes."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for char in selector:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            continue
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _rightmost_compound(selector: str) -> str:
    """The last compound of one selector — everything after the final top-level combinator.

    Combinators inside ``:is(…)``/``[…]``/a string are not combinators of THIS selector, which
    is why the scan tracks depth and quoting rather than splitting on whitespace.
    """
    depth = 0
    quote: str | None = None
    cut = 0
    for index, char in enumerate(selector):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char in "([":
            depth += 1
            continue
        if char in ")]":
            depth = max(0, depth - 1)
            continue
        if depth == 0 and char in _COMBINATORS:
            cut = index + 1
    return selector[cut:].strip()


def _compound_could_match(compound: str, inventory: _Inventory) -> bool:
    """Could an element inside the subtree match this compound? Ties go to "yes"."""
    if not compound:
        return False

    stripped, had_functional_pseudo = _strip_pseudos_and_attributes(compound)
    if had_functional_pseudo:
        # `:is(h1, h2)`, `:not(.x)`, `:has(…)` — the compound's real subjects live inside the
        # argument list, and evaluating them properly means implementing a selector engine.
        # Keeping the rule is the cheap, safe answer.
        return True

    tag, ids, classes = _parse_simple_compound(stripped)
    if tag in _DOCUMENT_TAGS:
        return True
    if tag is None and not ids and not classes:
        # `*`, or a compound that was nothing but pseudo-classes (`:root`, `:hover`).
        return True
    if tag is not None and tag != "*" and tag not in inventory.tags:
        return False
    if any(element_id not in inventory.ids for element_id in ids):
        return False
    return all(name in inventory.classes for name in classes)


def _strip_pseudos_and_attributes(compound: str) -> tuple[str, bool]:
    """Remove ``[…]`` and every pseudo; report whether any pseudo carried an argument list."""
    out: list[str] = []
    index = 0
    length = len(compound)
    functional = False
    while index < length:
        char = compound[index]
        if char == "[":
            index = _skip_balanced(compound, index, "[", "]")
            continue
        if char == ":":
            index += 1
            if index < length and compound[index] == ":":
                index += 1
            while index < length and (compound[index].isalnum() or compound[index] == "-"):
                index += 1
            if index < length and compound[index] == "(":
                functional = True
                index = _skip_balanced(compound, index, "(", ")")
            continue
        out.append(char)
        index += 1
    return "".join(out), functional


def _skip_balanced(text: str, start: int, opener: str, closer: str) -> int:
    depth = 0
    index = start
    quote: str | None = None
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _parse_simple_compound(compound: str) -> tuple[str | None, list[str], list[str]]:
    """``a.button.is-primary#x`` → ``("a", ["x"], ["button", "is-primary"])``.

    Runs only over a compound that has already had its ``[…]`` and pseudos removed, so the
    alphabet is exactly: an optional type selector, then ``.``- and ``#``-introduced names.
    """
    tag: list[str] = []
    ids: list[list[str]] = []
    classes: list[list[str]] = []
    target: list[str] = tag
    for char in compound:
        if char == ".":
            classes.append([])
            target = classes[-1]
        elif char == "#":
            ids.append([])
            target = ids[-1]
        else:
            target.append(char)
    return (
        "".join(tag).strip().lower() or None,
        ["".join(name) for name in ids if name],
        ["".join(name) for name in classes if name],
    )


__all__ = ["MatchedCss", "rules_for_subtree"]
