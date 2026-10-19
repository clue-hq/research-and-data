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

Source-html font-variable classes need one additional step: a single observed root class may
hold inherited custom properties while being absent from every section subtree. Those property
definitions receive a :root alias in their original order and conditional/layer context. Other
root-class declarations (such as document height) do not move. Compound/state selectors and
body/ancestor inheritance are not flattened.

The output is CSS text in source order, sheet by sheet. References, final fragment scoping and
the markup-breakout gate remain the scoper's job, including for the root-variable aliases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Sequence

import tinycss2
from selectolax.parser import HTMLParser
from tinycss2 import ast

if TYPE_CHECKING:
    from .source_context import SourceSectionContext

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
    #: Source-html class rules whose custom properties were re-anchored to the wrapper.
    root_variable_rules: int = 0

    @property
    def byte_length(self) -> int:
        return len(self.css.encode("utf-8"))


@dataclass(frozen=True)
class _Inventory:
    """What a subtree contains, in the only three terms a compound selector can ask about."""

    tags: frozenset[str]
    ids: frozenset[str]
    classes: frozenset[str]
    source_root_classes: frozenset[str] = frozenset()
    source_context: SourceSectionContext | None = None

    @classmethod
    def of(cls, html: str, source_root_classes: Sequence[str] = (),
           source_context: SourceSectionContext | None = None) -> _Inventory:
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
        return cls(
            frozenset(tags), frozenset(ids), frozenset(classes), frozenset(source_root_classes),
            source_context,
        )


def rules_for_subtree(
    stylesheets: Sequence[Any], *, subtree_html: str, source_root_classes: Sequence[str] = (),
    source_context: SourceSectionContext | None = None,
) -> MatchedCss:
    """The page's rules that could style this subtree, in source order.

    ``stylesheets`` is duck-typed on ``LoadedStylesheet`` (``.url``, ``.text``) so this module
    never imports the snapshot read seam — the same discipline Task 11 applied to the segmenter,
    and for the same reason: a pure function must not drag the DAL in behind it.
    """
    inventory = _Inventory.of(subtree_html, source_root_classes, source_context)
    counter = _Counter()
    blocks: list[tuple[str, str]] = []
    if source_context is not None:
        blocks.append(("inline:source-document-context", source_context.base_css()))
    notes: list[str] = []
    sheets_read = 0
    for sheet in stylesheets:
        text = getattr(sheet, "text", "") or ""
        sheets_read += 1
        if not text.strip():
            continue
        rules = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
        sheet_url = str(getattr(sheet, "url", "") or "")
        if source_context is not None and sheet_url == "inline:source-root-unit":
            # The trusted derived default belongs below authored root selectors. Keeping
            # its synthetic :root specificity would beat a later html unit assignment.
            continue
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
        root_variable_rules=counter.root_variables,
    )


class _Counter:
    def __init__(self) -> None:
        self.considered = 0
        self.kept = 0
        self.root_variables = 0


def _keep_rules(
    rules: Iterable[object],
    inventory: _Inventory,
    counter: _Counter,
    notes: list[str],
    sheet_url: str,
    conditions: tuple[str, ...] = (),
) -> str:
    out: list[str] = []
    for rule in rules:
        rendered = _keep_rule(rule, inventory, counter, notes, sheet_url, conditions)
        if rendered:
            out.append(rendered)
    return "\n".join(out)


def _keep_rule(
    rule: object,
    inventory: _Inventory,
    counter: _Counter,
    notes: list[str],
    sheet_url: str,
    conditions: tuple[str, ...] = (),
) -> str:
    if isinstance(rule, ast.QualifiedRule):
        counter.considered += 1
        selector = tinycss2.serialize(rule.prelude).strip()
        regular = _selector_could_match(selector, inventory)
        root_variables = _source_root_custom_properties(rule, inventory)
        if inventory.source_context is not None:
            projected = inventory.source_context.project(
                selector, rule.content, regular=regular, conditions=conditions
            )
            if projected:
                counter.kept += 1
                counter.root_variables += bool(root_variables)
            return projected
        if not regular and not root_variables:
            return ""
        counter.kept += 1
        out = [f"{selector} {{{tinycss2.serialize(rule.content)}}}"] if regular else []
        if root_variables:
            # A single class and :root both have specificity (0, 1, 0). The existing scoper
            # re-anchors :root to the fragment wrapper. Keep this at the original rule's
            # position and conditional/layer nesting; move only inherited custom properties,
            # never the original document's height, background, overflow or layout box.
            out.append(f":root {{{root_variables}}}")
            counter.root_variables += 1
        return "\n".join(out)

    if isinstance(rule, ast.AtRule):
        return _keep_at_rule(rule, inventory, counter, notes, sheet_url, conditions)

    if isinstance(rule, ast.ParseError):
        # A page's stylesheet is not ours to be strict about: browsers skip what they cannot
        # parse and render the rest, and so do we. Named, not swallowed.
        notes.append(f"skipped unparseable css in {sheet_url or 'a stylesheet'}: {rule.message}")
        return ""
    return ""


def _source_root_custom_properties(rule: ast.QualifiedRule, inventory: _Inventory) -> str:
    """Preserve definitions from an observed html-root class, without guessing root state.

    Next's font-variable classes are a common example. Only a single class selector is
    equivalent in specificity to :root. Compound, ancestor and pseudo-class selectors need
    their original context and are deliberately not flattened. Body/other ancestors are not
    root classes either: collapsing their inheritance levels would change the cascade.
    """
    if not inventory.source_root_classes:
        return ""
    for selector in _split_selector_list(tinycss2.serialize(rule.prelude)):
        tokens = [token for token in tinycss2.parse_component_value_list(selector)
                  if token.type not in ("whitespace", "comment")]
        if (len(tokens) == 2 and isinstance(tokens[0], ast.LiteralToken)
                and tokens[0].value == "." and isinstance(tokens[1], ast.IdentToken)
                and tokens[1].value in inventory.source_root_classes):
            declarations = tinycss2.parse_declaration_list(
                rule.content, skip_comments=True, skip_whitespace=True
            )
            return tinycss2.serialize([
                declaration for declaration in declarations
                if isinstance(declaration, ast.Declaration) and declaration.name.startswith("--")
            ])
    return ""


def _keep_at_rule(
    rule: ast.AtRule,
    inventory: _Inventory,
    counter: _Counter,
    notes: list[str],
    sheet_url: str,
    conditions: tuple[str, ...] = (),
) -> str:
    keyword = rule.lower_at_keyword
    prelude = tinycss2.serialize(rule.prelude).strip()

    if rule.content is None:
        # A statement at-rule (`@import url(x);`, `@layer a, b;`). Kept verbatim: the fragment
        # scoper has rulings about these (strip @import loudly, pass @layer through) and it is
        # the one place that decision belongs.
        return f"@{keyword} {prelude};".strip()

    if keyword in _GLOBAL_BLOCK_AT_RULES:
        # `rstrip`, never a `"  " -> " "` sweep over the whole rendered rule: an `@font-face`
        # legitimately contains `local("My  Font")`, and a family whose real name has two spaces
        # in it is not ours to tidy. The only double space this ever had to fix was the one
        # BETWEEN the keyword and an empty prelude, which is exactly what rstrip removes.
        head = f"@{keyword} {prelude}".rstrip()
        return f"{head} {{{tinycss2.serialize(rule.content)}}}"

    if keyword in _CONDITIONAL_AT_RULES:
        inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
        body = _keep_rules(inner, inventory, counter, notes, sheet_url, conditions + (keyword,))
        if not body.strip():
            return ""
        head = f"@{keyword} {prelude}".rstrip()
        return f"{head} {{ {body} }}"

    # Unknown nested rules cannot remain unguarded around synthetic context elements.
    if inventory.source_context is not None:
        inventory.source_context.note(f"unsupported source-context at-rule: @{keyword}")
        raise ValueError("source-context at-rule grammar is unsupported")
    # Without context transport, retain the existing conservative path to the scoper.
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
    """Split on top-level commas — the ones outside ``(``/``[``/quotes, and unescaped."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    index = 0
    while index < len(selector):
        char = selector[index]
        index += 1
        if quote is None and char == "\\":
            # An escaped character is part of an identifier and never a delimiter.
            _decoded, next_index = _read_escape(selector, index - 1)
            current.append(selector[index - 1 : next_index])
            index = next_index
            continue
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
    index = 0
    while index < len(selector):
        char = selector[index]
        if quote is None and char == "\\":
            # `\ ` is an escaped SPACE inside an identifier, not a descendant combinator.
            _decoded, index = _read_escape(selector, index)
            continue
        index += 1
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
            cut = index
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
    """Remove ``[…]`` and every pseudo; report whether any pseudo carried an argument list.

    Escapes are carried through UNTOUCHED (``\\`` plus whatever it escapes), because a
    backslash-escaped character is part of an identifier, not a delimiter. Tailwind's whole
    responsive and fractional vocabulary is written that way — ``.md\\:flex``, ``.w-1\\/2``,
    ``.\\32 xl\\:grid`` — so reading an escaped ``:`` as the start of a pseudo-class dropped
    every one of those rules from every real page, silently. :func:`_parse_simple_compound` is
    where the escapes are finally decoded, once the delimiters are known.
    """
    out: list[str] = []
    index = 0
    length = len(compound)
    functional = False
    while index < length:
        char = compound[index]
        if char == "\\":
            _decoded, next_index = _read_escape(compound, index)
            out.append(compound[index:next_index])
            index = next_index
            continue
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


def _read_escape(text: str, index: int) -> tuple[str, int]:
    """Decode one CSS identifier escape starting at the backslash. → ``(text, next index)``.

    Two forms, per the CSS syntax spec: one to six hex digits naming a code point, optionally
    followed by ONE whitespace character that terminates the escape and is consumed
    (``\\32 xl`` is ``2xl``, and that trailing space is why a naive split on whitespace also gets
    these wrong); or a backslash before any other character, which is that character literally.
    A trailing backslash is not an escape and is returned as itself.
    """
    index += 1
    if index >= len(text):
        return "\\", index
    digits = ""
    while index < len(text) and len(digits) < 6 and text[index] in "0123456789abcdefABCDEF":
        digits += text[index]
        index += 1
    if digits:
        if index < len(text) and text[index] in " \t\n\r\f":
            index += 1
        try:
            return chr(int(digits, 16)), index
        except (ValueError, OverflowError):
            return "�", index
    return text[index], index + 1


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
    alphabet is exactly: an optional type selector, then ``.``- and ``#``-introduced names —
    plus escapes, which are decoded HERE. Decoding last is what makes ``.a\\.b`` one class
    called ``a.b`` rather than two called ``a`` and ``b``: by this point an unescaped ``.`` is
    the only ``.`` that separates names.
    """
    tag: list[str] = []
    ids: list[list[str]] = []
    classes: list[list[str]] = []
    target: list[str] = tag
    index = 0
    while index < len(compound):
        char = compound[index]
        if char == "\\":
            decoded, index = _read_escape(compound, index)
            target.append(decoded)
            continue
        index += 1
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


# --- the un-hide block (phase fix wave, walk finding F-3 / final-review X3) ----------------------

#: The counter-declarations, one per property a rule can hide with. ``revert`` rather than a
#: guessed ``block``/``flex``: it returns the element to what it would have been WITHOUT the
#: hiding rule, which is the honest opposite of "the source hid it" — guessing a display type
#: would be a small fabrication. Only the property the rule actually hid is countered (wave
#: round 2, M1): a rule that hid with ``visibility`` alone gets no ``display: revert``, which
#: would clobber a separate author ``display`` on the same element.
UNHIDE_DISPLAY = "display: revert !important;"
UNHIDE_VISIBILITY = "visibility: visible !important;"

UNHIDE_BLOCK_HEADER = (
    "/* lumen un-hide (D-F8): the source site hides this section, and its harvested CSS carries\n"
    "   the very rules that hide it. Each rule below countermands one that hid the ROOT —\n"
    "   selected only when its selector positively names the root, appended last so source\n"
    "   order wins at equal specificity — an activated clone renders on the page and in its\n"
    "   isolation preview alike, off one sheet. A counter on a name the root shares with a\n"
    "   descendant reaches that descendant too; hiding that names only the section's own\n"
    "   internals is left alone. */"
)


def unhide_root_rules(
    css: str, *, tag: str, element_id: str | None, classes: Sequence[str]
) -> tuple[str, tuple[str, ...]]:
    """Counter every rule in ``css`` that hides the fragment's ROOT element.

    Returns ``(css with the appended un-hide block, the selectors countermanded)`` — unchanged
    ``css`` and ``()`` when nothing hides the root. "Hides" is ``display: none`` or
    ``visibility: hidden``; "the root" is matched with the same could-match reading the keeper
    logic above uses, over an inventory of exactly one element.
    """
    inventory = _Inventory(
        tags=frozenset(part for part in ((tag or "").strip().lower(),) if part),
        ids=frozenset(part for part in ((element_id or "").strip(),) if part),
        classes=frozenset(name for name in classes if name),
    )
    rules = tinycss2.parse_stylesheet(css or "", skip_comments=True, skip_whitespace=True)
    counters: list[str] = []
    selectors: list[str] = []
    _collect_unhide(rules, inventory, counters, selectors, media_prelude=None)
    if not counters:
        return css, ()
    block = UNHIDE_BLOCK_HEADER + "\n" + "\n".join(counters)
    return f"{css}\n{block}\n", tuple(dict.fromkeys(selectors))


def _collect_unhide(
    rules: Iterable[object],
    inventory: _Inventory,
    out: list[str],
    selectors: list[str],
    media_prelude: str | None,
) -> None:
    for rule in rules:
        if isinstance(rule, ast.QualifiedRule):
            hides_display, hides_visibility = _hiding_properties(rule.content)
            if not (hides_display or hides_visibility):
                continue
            prelude = tinycss2.serialize(rule.prelude).strip()
            matching = [
                part
                for part in _split_selector_list(prelude)
                if _positively_names_root(part, inventory)
            ]
            if not matching:
                continue
            declarations = " ".join(
                part
                for part, hides in (
                    (UNHIDE_DISPLAY, hides_display),
                    (UNHIDE_VISIBILITY, hides_visibility),
                )
                if hides
            )
            counter = f"{', '.join(matching)} {{ {declarations} }}"
            if media_prelude is not None:
                # The hiding rule applies only under its media condition, so the counter-rule
                # rides the same condition — un-hiding wider than the hiding would be a change,
                # not a countermand.
                counter = f"@media {media_prelude} {{ {counter} }}"
            out.append(counter)
            selectors.extend(matching)
        elif (
            isinstance(rule, ast.AtRule)
            and rule.lower_at_keyword == "media"
            and rule.content is not None
        ):
            inner = tinycss2.parse_stylesheet(
                tinycss2.serialize(rule.content), skip_comments=True, skip_whitespace=True
            )
            _collect_unhide(
                inner,
                inventory,
                out,
                selectors,
                media_prelude=tinycss2.serialize(rule.prelude).strip(),
            )


def _hiding_properties(content: Sequence[object]) -> tuple[bool, bool]:
    """``(hides via display, hides via visibility)`` for one rule's declarations."""
    hides_display = False
    hides_visibility = False
    declarations = tinycss2.parse_declaration_list(
        tinycss2.serialize(list(content)), skip_comments=True, skip_whitespace=True
    )
    for declaration in declarations:
        if getattr(declaration, "type", "") != "declaration":
            continue
        value = tinycss2.serialize(declaration.value).strip().lower()
        if declaration.lower_name == "display" and "none" in value:
            hides_display = True
        if declaration.lower_name == "visibility" and "hidden" in value:
            hides_visibility = True
    return hides_display, hides_visibility


def _positively_names_root(part: str, inventory: _Inventory) -> bool:
    """May this selector part be COUNTERMANDED as a rule that hides the root? (Wave round 2, I1.)

    Countermanding needs certainty in the opposite direction from keeping: `could match` keeps
    a rule on any doubt, and re-used here it un-hid ``[hidden]`` resets, ``*``,
    ``.card:not(.active)`` and every descendant selector whose rightmost name the root happens
    to share — the mega-menu shape the un-hide's own header forbids. So a countermand requires:
    ONE compound (no combinators — a descendant selector targets something inside the section),
    no functional pseudos (a ``:not(…)`` can invert the match), and at least one concrete name
    (tag, class or id) that the root actually carries, with every named constraint matching.
    A hiding rule this cannot certify (``[hidden]``, an in-situ ancestor chain) is left alone —
    the root markup strip covers the attribute case, and anything still hidden reaches the
    isolation render's typed refusal instead of a wrong guess.
    """
    part = part.strip()
    if not part or _rightmost_compound(part) != part:
        return False
    stripped, had_functional_pseudo = _strip_pseudos_and_attributes(part)
    if had_functional_pseudo:
        return False
    tag, ids, classes = _parse_simple_compound(stripped)
    if tag in _DOCUMENT_TAGS:
        return False
    named = (tag is not None and tag != "*") or bool(ids) or bool(classes)
    if not named:
        return False
    if tag is not None and tag != "*" and tag not in inventory.tags:
        return False
    if any(element_id not in inventory.ids for element_id in ids):
        return False
    return all(name in inventory.classes for name in classes)


def unhide_root_markup(html: str) -> tuple[str, tuple[str, ...]]:
    """Strip the ROOT element's own inline hiding — the commonest way a CMS parks a section.

    (Wave round 2, C1.) The stylesheet counter-rules above cannot reach ``style="display:none"``
    (inline-``!important`` beats any sheet) or the ``hidden`` attribute (a UA rule no
    same-selector counter targets certainly), so those two are countermanded at the MARKUP
    seam instead: removed from the stored artifact's root element, deterministically, and named
    in the returned record so provenance can say what changed. Descendants are untouched —
    their hiding is the section's own design.

    Returns ``(html, what_was_removed)`` — unchanged html and ``()`` when the root hides
    nothing inline.
    """
    tree = HTMLParser(html or "")
    body = tree.body
    elements: list[Any] = []
    if body is not None:
        elements = list(body.iter(include_text=False))
    if not elements:
        return html, ()
    if len(elements) > 1:
        # This function re-serializes the ROOT's outerHTML, so a multi-root fragment would
        # silently lose its siblings (wave round 2, N1). The mint never produces one today;
        # if one ever arrives, leaving it hidden-and-whole beats un-hiding half of it.
        return html, ()
    root = elements[0]
    removed: list[str] = []
    if "hidden" in root.attributes:
        del root.attrs["hidden"]
        removed.append("hidden attribute")
    style = root.attributes.get("style") or ""
    if style:
        # Parsed, not split on ";" (wave round 2, N2): a value can contain a semicolon
        # (`content: 'a;b'`, a data: URI) and a naive split would mangle it into a bad-url.
        kept: list[str] = []
        stripped_any = False
        for declaration in tinycss2.parse_declaration_list(
            style, skip_comments=True, skip_whitespace=True
        ):
            if getattr(declaration, "type", "") != "declaration":
                continue
            value = tinycss2.serialize(declaration.value).strip()
            name = declaration.lower_name
            if name == "display" and "none" in value.lower():
                removed.append("inline display: none")
                stripped_any = True
                continue
            if name == "visibility" and "hidden" in value.lower():
                removed.append("inline visibility: hidden")
                stripped_any = True
                continue
            bang = " !important" if declaration.important else ""
            kept.append(f"{declaration.name}: {value}{bang}")
        if stripped_any:
            if kept:
                root.attrs["style"] = "; ".join(kept)
            else:
                del root.attrs["style"]
    if not removed:
        return html, ()
    rendered = root.html or html
    return rendered, tuple(removed)


__all__ = ["MatchedCss", "rules_for_subtree", "unhide_root_markup", "unhide_root_rules"]
