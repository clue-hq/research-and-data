"""Bounded HTML/body style context for detached sections; never source document layout.

Two private, non-layout elements retain the inheritance levels. Ordinary selectors exclude
those elements at zero specificity; separately projected rules address captured HTML/body
facts. This is not arbitrary ancestor, sibling, dynamic-state, or source-program recovery.
"""

from __future__ import annotations

import html as html_lib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import tinycss2
from selectolax.parser import HTMLParser
from tinycss2 import ast

from .cssmatch import _split_selector_list
from .rootunits import RootUnits, _root_length

# Deliberately narrower than every inherited CSS property: no source visibility or layout.
_INHERITED = frozenset(
    {
        "color",
        "font",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "font-stretch",
        "font-variant",
        "font-feature-settings",
        "font-variation-settings",
        "font-kerning",
        "font-optical-sizing",
        "font-synthesis",
        "line-height",
        "letter-spacing",
        "word-spacing",
        "text-align",
        "text-align-last",
        "text-indent",
        "text-transform",
        "text-rendering",
        "text-size-adjust",
        "-webkit-text-size-adjust",
        "-ms-text-size-adjust",
        "-webkit-font-smoothing",
        "-moz-osx-font-smoothing",
        "white-space",
        "word-break",
        "overflow-wrap",
        "word-wrap",
        "hyphens",
        "tab-size",
        "direction",
        "writing-mode",
        "text-orientation",
        "color-scheme",
    }
)
# box-sizing is not inherited by default, but source resets often explicitly inherit it.
# Retain it on the display:contents context nodes without recovering document layout.
_CONTEXT_PROPERTIES = _INHERITED | {"box-sizing"}
_SELECTOR_FUNCTIONS = frozenset({"is", "where", "not", "has"})
_STATIC_PSEUDOS = frozenset(
    {
        "root",
        "first-child",
        "last-child",
        "only-child",
        "first-of-type",
        "last-of-type",
        "only-of-type",
        "empty",
    }
)
_STRUCTURAL = (":first-", ":last-", ":only-", ":nth-", ":empty")
_ROOT_NAMES = frozenset({"html", "body"})
_MAX_NOTES = 32
_MAX_BOX_SIZING_FALLBACK_DEPTH = 32


def _root_box_sizing(tokens: Sequence[Any], depth: int = 0) -> list[Any] | None:
    """Normalize explicit root inheritance, including var fallbacks, without resolving vars."""
    if depth > _MAX_BOX_SIZING_FALLBACK_DEPTH:
        raise ValueError("source root box-sizing var fallback nesting exceeds supported bound")
    significant = [t for t in tokens if t.type not in {"whitespace", "comment"}]
    if len(significant) != 1:
        return None
    token = significant[0]
    if isinstance(token, ast.IdentToken) and token.lower_value == "inherit":
        replacement = ast.IdentToken(token.source_line, token.source_column, "initial")
    elif isinstance(token, ast.FunctionBlock) and token.lower_name == "var":
        comma = next(
            (
                i
                for i, part in enumerate(token.arguments)
                if isinstance(part, ast.LiteralToken) and part.value == ","
            ),
            None,
        )
        if comma is None:
            return None
        name = [t for t in token.arguments[:comma] if t.type not in {"whitespace", "comment"}]
        if not (
            len(name) == 1
            and isinstance(name[0], ast.IdentToken)
            and name[0].value.startswith("--")
        ):
            return None
        fallback = _root_box_sizing(token.arguments[comma + 1 :], depth + 1)
        if fallback is None:
            return None
        replacement = ast.FunctionBlock(
            token.source_line,
            token.source_column,
            token.name,
            [*token.arguments[: comma + 1], *fallback],
        )
    else:
        return None
    # Keep the stylesheet AST shared with body/ordinary rules unchanged.
    return [replacement if part is token else part for part in tokens]


def _parts(selector: str) -> tuple[list[list[Any]], list[str]]:
    """Split outside blocks/strings; escapes remain CSS tokens, never string-replaced."""
    compounds: list[list[Any]] = []
    combinators: list[str] = []
    current: list[Any] = []
    pending = " "
    for token in tinycss2.parse_component_value_list(selector):
        if token.type == "comment":
            continue
        if token.type == "whitespace" or (
            isinstance(token, ast.LiteralToken) and token.value in {">", "+", "~"}
        ):
            if current:
                if compounds:
                    combinators.append(pending)
                compounds.append(current)
                current = []
                pending = " "
            if token.type != "whitespace":
                pending = token.value
            continue
        if token.type == "error" or (
            isinstance(token, ast.LiteralToken) and token.value in {"&", "|", ",", ";"}
        ):
            raise ValueError("unsupported selector nesting, namespace, or separator")
        current.append(token)
    if current:
        if compounds:
            combinators.append(pending)
        compounds.append(current)
    if not compounds:
        raise ValueError("empty selector")
    return compounds, combinators


def _join(compounds: Sequence[str], combinators: Sequence[str]) -> str:
    result = compounds[0]
    for combinator, compound in zip(combinators, compounds[1:], strict=True):
        result += (" " if combinator == " " else f" {combinator} ") + compound
    return result


def _document_head(compound: Sequence[Any]) -> bool:
    first = compound[0]
    return (isinstance(first, ast.IdentToken) and first.lower_value in _ROOT_NAMES) or (
        len(compound) >= 2
        and isinstance(first, ast.LiteralToken)
        and first.value == ":"
        and isinstance(compound[1], ast.IdentToken)
        and compound[1].lower_value in {"root", "host"}
    )


def _static(compound: Sequence[Any]) -> bool:
    for index, token in enumerate(compound):
        if isinstance(token, ast.FunctionBlock):
            # Only simple static negation is evaluated against the frozen document.
            if token.lower_name != "not":
                return False
            try:
                parts, links = _parts(tinycss2.serialize(token.arguments))
            except ValueError:
                return False
            if links or len(parts) != 1 or not _static(parts[0]):
                return False
        if isinstance(token, ast.LiteralToken) and token.value == ":":
            following = compound[index + 1] if index + 1 < len(compound) else None
            if (
                isinstance(following, ast.IdentToken)
                and following.lower_value not in _STATIC_PSEUDOS
            ):
                return False
            if isinstance(following, ast.LiteralToken):
                return False
    return True


@dataclass
class SourceDocumentContext:
    tree: Any
    root_units: RootUnits
    root_tag: str
    body_tag: str
    notes: list[str] = field(default_factory=list)
    match_cache: dict[tuple[str, int], bool] = field(default_factory=dict)
    active: bool = False
    unsupported: bool = False

    @classmethod
    def prepare(cls, html: str, stylesheets: Sequence[Any], root_units: RootUnits):
        tree = HTMLParser(html)
        # Actual element tags, not text inside CSS strings, determine markup collisions.
        tags = {node.tag.lower() for node in tree.root.traverse(include_text=False) if node.tag}

        def identifiers(tokens):
            for token in tokens:
                if isinstance(token, ast.IdentToken):
                    yield token.lower_value
                elif isinstance(token, ast.FunctionBlock):
                    yield from identifiers(token.arguments)

        qualified = []

        def selectors(rules):
            for rule in rules:
                if isinstance(rule, ast.QualifiedRule):
                    qualified.append(rule)
                    yield from identifiers(rule.prelude)
                elif (
                    isinstance(rule, ast.AtRule)
                    and rule.content is not None
                    and rule.lower_at_keyword
                    in {"media", "supports", "container", "layer", "scope"}
                ):
                    yield from selectors(tinycss2.parse_rule_list(rule.content))

        for sheet in stylesheets:
            tags.update(selectors(tinycss2.parse_stylesheet(getattr(sheet, "text", "") or "")))
        for attempt in range(16):
            # The fragment wrapper already isolates these tags. Short names prevent the
            # zero-specificity guard from multiplying large captured stylesheets.
            suffix = "" if attempt == 0 else f"-{attempt:x}"
            root_tag, body_tag = f"ls-h{suffix}", f"ls-b{suffix}"
            if not ({root_tag, body_tag} & tags):
                break
        else:
            return None
        context = cls(tree, root_units, root_tag, body_tag)
        if stylesheets and all(
            getattr(sheet, "source_order", None) is not None for sheet in stylesheets
        ):
            context.note("source stylesheet order uses captured source_order metadata")
        else:
            context.note("source stylesheet order is supplied and not independently verified")
        probe = SourceSectionContext(context, tree.body)
        for owner, node in enumerate((tree.root, tree.body)):
            if node is None:
                continue
            if any(name in node.attributes for name in ("lang", "dir")) or probe.declarations(
                node.attributes.get("style") or "", owner
            ):
                context.active = True
            if (node.attributes.get("dir") or "").lower() == "auto":
                context.note("source document dir=auto directionality is unsupported")
        try:
            for rule in qualified:
                projected = probe.project(
                    tinycss2.serialize(rule.prelude), rule.content, regular=False
                )
                if projected:
                    context.active = True
        except ValueError as error:
            context.active = False
            context.unsupported = True
            context.note(str(error))
        for note in probe.notes:
            context.note(note)
        return context

    def note(self, note: str) -> None:
        if note not in self.notes and len(self.notes) < _MAX_NOTES:
            self.notes.append(note)

    def for_section(self, node: Any):
        if not self.active:
            return None
        section = SourceSectionContext(self, node, list(self.notes))
        if node.parent is not None and node.parent.tag != "body":
            section.note("ancestors between body and the section are not reconstructed")
        return section


@dataclass
class SourceSectionContext:
    document: SourceDocumentContext
    source_node: Any
    notes: list[str] = field(default_factory=list)
    inherited_rules: int = 0
    descendant_rules: int = 0

    def note(self, note: str) -> None:
        if note not in self.notes and len(self.notes) < _MAX_NOTES:
            self.notes.append(note)

    @property
    def tags(self) -> tuple[str, str]:
        return self.document.root_tag, self.document.body_tag

    @property
    def guard(self) -> str:
        return f":not(:where({','.join(self.tags)}))"

    def guard_selector(self, selector: str) -> str:
        compounds, links = _parts(selector)
        result = []
        for compound in compounds:
            pieces: list[str] = []
            # Context nodes have no class/id, and their collision-checked type names
            # cannot equal an explicit source type. Only these token facts make a
            # guard redundant; functional/attribute/universal matches stay guarded.
            inserted = (
                isinstance(compound[0], ast.IdentToken) and compound[0].lower_value not in self.tags
            ) or any(
                isinstance(token, ast.HashToken)
                and token.is_identifier
                or isinstance(token, ast.LiteralToken)
                and token.value == "."
                and index + 1 < len(compound)
                and isinstance(compound[index + 1], ast.IdentToken)
                for index, token in enumerate(compound)
            )
            for index, token in enumerate(compound):
                if isinstance(token, ast.LiteralToken) and token.value == ":":
                    following = compound[index + 1] if index + 1 < len(compound) else None
                    pseudo_element = (
                        isinstance(following, ast.LiteralToken) and following.value == ":"
                    ) or (
                        isinstance(following, ast.IdentToken)
                        and following.lower_value
                        in {"before", "after", "first-line", "first-letter"}
                    )
                    if pseudo_element and not inserted:
                        pieces.append(self.guard)
                        inserted = True
                if isinstance(token, ast.FunctionBlock) and token.lower_name in _SELECTOR_FUNCTIONS:
                    args = ",".join(
                        self.guard_selector(s)
                        for s in _split_selector_list(tinycss2.serialize(token.arguments))
                    )
                    pieces.append(f"{token.name}({args})")
                else:
                    pieces.append(token.serialize())
            if not inserted:
                pieces.append(self.guard)
            result.append("".join(pieces))
        rendered = _join(result, links)
        leading = selector.lstrip()[:1]
        return (leading + " " + rendered) if leading in {">", "+", "~"} else rendered

    def _alias(self, compound: Sequence[Any], owner: int) -> str:
        tag = self.tags[owner]
        text = tinycss2.serialize(compound).strip()
        if text == "*":
            return f":where({tag})"
        # The private type branch adds no specificity to a non-universal simple compound.
        return f":where({tag}):is({text},{tag})"

    def _functional_document_subject(self, compound: Sequence[Any]) -> bool:
        for token in compound:
            if (
                not isinstance(token, ast.FunctionBlock)
                or token.lower_name not in _SELECTOR_FUNCTIONS
            ):
                continue
            for branch in _split_selector_list(tinycss2.serialize(token.arguments)):
                try:
                    parts, _ = _parts(branch)
                except ValueError:
                    continue
                if (
                    _document_head(parts[0])
                    or any(self._matches(parts[0], n) for n in (0, 1))
                    or self._functional_document_subject(parts[0])
                ):
                    return True
        return False

    def _matches(self, compound: Sequence[Any], owner: int) -> bool:
        node = self.document.tree.root if owner == 0 else self.document.tree.body
        if node is None or not _static(compound):
            return False
        text = tinycss2.serialize(compound)
        key = (text, owner)
        if key in self.document.match_cache:
            return self.document.match_cache[key]
        # Fast negatives avoid scanning a large source document for every absent class.
        classes = set((node.attributes.get("class") or "").split())
        for index, token in enumerate(compound):
            if index == 0 and isinstance(token, ast.IdentToken) and token.lower_value != node.tag:
                self.document.match_cache[key] = False
                return False
            if isinstance(token, ast.HashToken) and token.value != node.attributes.get("id"):
                self.document.match_cache[key] = False
                return False
            if isinstance(token, ast.LiteralToken) and token.value == ".":
                following = compound[index + 1] if index + 1 < len(compound) else None
                if isinstance(following, ast.IdentToken) and following.value not in classes:
                    self.document.match_cache[key] = False
                    return False
        try:
            # css_matches means ANY descendant matches in selectolax, not this node.
            matched = node.css_first(text) == node
            self.document.match_cache[key] = matched
            return matched
        except (ValueError, RuntimeError):
            self.note("a source document selector could not be evaluated")
            return False

    def declarations(self, content: Sequence[Any] | str, owner: int) -> str:
        out: list[str] = []
        dropped: set[str] = set()
        for declaration in tinycss2.parse_declaration_list(
            content, skip_comments=True, skip_whitespace=True
        ):
            if not isinstance(declaration, ast.Declaration):
                continue
            if (
                declaration.lower_name not in _CONTEXT_PROPERTIES
                and not declaration.name.startswith("--")
            ):
                dropped.add(declaration.lower_name)
                continue
            if owner == 0 and declaration.lower_name == "box-sizing":
                try:
                    normalized = _root_box_sizing(declaration.value)
                except ValueError as error:
                    self.note(str(error))
                    self.document.unsupported = True
                    normalized = None
                if normalized is not None:
                    # The source document root inherits the initial value; the synthetic
                    # root must not inherit the host wrapper's box model instead.
                    priority = "!important" if declaration.important else ""
                    out.append(f"box-sizing:{tinycss2.serialize(normalized)}{priority};")
                    continue
            if owner == 0 and declaration.lower_name == "font-size":
                value = _root_length(declaration.value, self.document.root_units.initial_px)
                if value is not None:
                    priority = "!important" if declaration.important else ""
                    out.append(f"font-size:{value}{priority};")
                    continue
                text = tinycss2.serialize(declaration.value).strip()
                if text not in {"initial", "medium"} and not text.endswith("px"):
                    self.note("source root font-size has unsupported relative/variable semantics")
            if owner == 0 and declaration.lower_name == "font":
                self.note("source root font shorthand is unsupported")
                continue
            out.append(declaration.serialize() + ";")
        if dropped:
            self.note("omitted document layout/paint declarations: " + ", ".join(sorted(dropped)))
        return "".join(out)

    def project(
        self,
        selector: str,
        content: Sequence[Any],
        *,
        regular: bool,
        conditions: tuple[str, ...] = (),
    ) -> str:
        declarations = tinycss2.serialize(content)
        out: list[str] = []
        for branch in _split_selector_list(selector):
            try:
                compounds, links = _parts(branch)
                guarded = self.guard_selector(branch)
            except ValueError as error:
                # Refuse transport of an unsupported selector; never leave an unguarded rule
                # able to style the synthetic inheritance nodes.
                self.note(str(error))
                raise ValueError("source-context selector grammar is unsupported") from error
            rooted = _document_head(compounds[0])
            if not _static(compounds[0]) and self._functional_document_subject(compounds[0]):
                self.note("unsupported functional document selector: " + branch[:100])
                self.document.unsupported = True
            if regular and not rooted:
                out.append(f"{guarded} {{{declarations}}}")
            if any(pseudo in branch for pseudo in _STRUCTURAL):
                self.note("source sibling positions outside the section are not recovered")
            owners = [owner for owner in (0, 1) if self._matches(compounds[0], owner)]
            if not owners and rooted:
                self.note("source document state/selector was not projected: " + branch[:100])
            if set(conditions) & {"container", "scope"}:
                if owners:
                    self.note(
                        "document inheritance under container/scope conditions is unsupported"
                    )
                continue
            if "layer" in conditions and owners:
                self.note("source layer ranking uses the existing CSS flattening approximation")
            prefixes: list[tuple[list[str], int, int]] = [
                ([self._alias(compounds[0], owner)], 1, owner) for owner in owners
            ]
            if (
                0 in owners
                and len(compounds) > 1
                and links[0] in {" ", ">"}
                and self._matches(compounds[1], 1)
            ):
                prefixes.append(
                    ([self._alias(compounds[0], 0), self._alias(compounds[1], 1)], 2, 1)
                )
            for prefix, consumed, owner in prefixes:
                if consumed == len(compounds):
                    inherited = self.declarations(content, owner)
                    if inherited:
                        out.append(f"{_join(prefix, links[: consumed - 1])} {{{inherited}}}")
                        self.inherited_rules += 1
                    continue
                next_link = links[consumed - 1]
                if next_link in {"+", "~"}:
                    self.note("source document sibling selectors are unsupported")
                    continue
                if next_link == ">":
                    parent = self.source_node.parent
                    expected = "html" if owner == 0 else "body"
                    if parent is None or parent.tag.lower() != expected:
                        self.note(
                            "direct document-child selector needs an omitted intermediate ancestor"
                        )
                        continue
                    if any(pseudo in branch for pseudo in _STRUCTURAL):
                        self.note("direct document-child structural selectors are unsupported")
                        continue
                rest = _join(
                    [tinycss2.serialize(c) for c in compounds[consumed:]], links[consumed:]
                )
                combined = _join(prefix, links[: consumed - 1])
                combined += " " if next_link == " " else f" {next_link} "
                combined += self.guard_selector(rest)
                out.append(f"{combined} {{{declarations}}}")
                self.descendant_rules += 1
        return "\n".join(dict.fromkeys(out))

    def base_css(self) -> str:
        # Source HTML inherits browser defaults, not the host brand kit. Relative source-root
        # font declarations are normalized separately; no computed source pixels are copied.
        names = sorted(_CONTEXT_PROPERTIES - {"font", "direction"})
        reset = ";".join(f"{name}:initial" for name in names)
        direction = (self.document.tree.root.attributes.get("dir") or "").lower()
        if direction == "auto":
            self.note("source root dir=auto directionality is unsupported")
        reset += ";direction:" + ("rtl" if direction == "rtl" else "ltr")
        units = self.document.root_units
        if units.variable is not None:
            reset += f";{units.variable}:{units.initial_px:g}px"
        return f":where({self.tags[0]}) {{{reset}}}"

    def wrap(self, markup: str) -> str:
        body = markup
        for owner in (1, 0):
            source = self.document.tree.root if owner == 0 else self.document.tree.body
            style = (
                self.declarations(source.attributes.get("style", "") or "", owner) if source else ""
            )
            # Reuse the existing rem normalizer on an isolated inline-style carrier.
            carrier = '<span style="' + html_lib.escape(style, quote=True) + '"></span>'
            normalized = self.document.root_units.markup(carrier) if style else carrier
            style_node = HTMLParser(normalized).css_first("span")
            style = (style_node.attributes.get("style", "") or "") if style_node else style
            attrs = (
                ' style="' + html_lib.escape(style + "display:contents!important", quote=True) + '"'
            )
            for name in ("lang", "dir"):
                value = source.attributes.get(name) if source else None
                if value is not None or (owner == 0 and name == "lang"):
                    # Empty language on the private root prevents inheriting host language.
                    attrs += f' {name}="{html_lib.escape(value or "", quote=True)}"'
            tag = self.tags[owner]
            body = f"<{tag}{attrs}>{body}</{tag}>"
        return body

    def wrap_slots(self, detected):
        return replace(
            detected,
            specs=tuple(
                replace(
                    spec,
                    selector=spec.selector.replace(
                        "body > ", "body > *:nth-child(1) > *:nth-child(1) > ", 1
                    ),
                )
                for spec in detected.specs
            ),
        )

    def provenance(self) -> dict[str, Any]:
        return {
            "mode": "source-html-body-inheritance",
            "inherited_rules": self.inherited_rules,
            "descendant_rules": self.descendant_rules,
            "layout_preserved": False,
            "limitations": list(self.notes),
            "fidelity_verified": False,
        }
