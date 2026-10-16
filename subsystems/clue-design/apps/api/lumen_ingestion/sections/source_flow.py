"""Read-only, bounded normal-flow envelopes from an immutable source snapshot.

An envelope is assembled once around unchanged sibling fragment pins. It is not a
new fragment and confers no release or fidelity status. Unsupported layout refuses
with a named gap; no browser measurements or invented spacing are substituted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import tinycss2
from selectolax.parser import HTMLParser
from tinycss2 import ast

from .cssmatch import _split_selector_list
from .rootunits import prepare_root_units
from .source_context import _INHERITED, _parts, _root_box_sizing

MAX_MEMBERS = 40
MAX_ANCESTORS = 8
MAX_CSS_BYTES = 65536
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_DEPTH = 32
_MAX_RULES = 100000
_BOX = frozenset(
    {
        "display",
        "position",
        "inset",
        "inset-block",
        "inset-inline",
        "top",
        "right",
        "bottom",
        "left",
        "z-index",
        "width",
        "height",
        "min-width",
        "max-width",
        "min-height",
        "max-height",
        "margin",
        "margin-top",
        "margin-right",
        "margin-bottom",
        "margin-left",
        "margin-block",
        "margin-inline",
        "margin-block-start",
        "margin-block-end",
        "margin-inline-start",
        "margin-inline-end",
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
        "padding-block",
        "padding-inline",
        "padding-block-start",
        "padding-block-end",
        "padding-inline-start",
        "padding-inline-end",
        "box-sizing",
        "overflow",
        "overflow-x",
        "overflow-y",
        "background",
        "background-color",
        "background-image",
        "border",
        "border-width",
        "border-style",
        "border-color",
        "border-radius",
        "box-shadow",
        "opacity",
        "backface-visibility",
        "float",
        "clear",
        "transform",
        "translate",
        "rotate",
        "scale",
        "contain",
        "content-visibility",
        "animation",
        "animation-name",
        "transition",
        "visibility",
        "content",
        "all",
        "direction",
        "writing-mode",
    }
)
_PAINT = frozenset(
    {
        "background",
        "background-color",
        "background-image",
        "border",
        "border-width",
        "border-style",
        "border-color",
        "border-radius",
        "box-shadow",
        "opacity",
    }
)
_BOX = _BOX - _PAINT
_NON_LAYOUT = frozenset(
    {
        "pointer-events",
        "cursor",
        "-webkit-tap-highlight-color",
        "touch-action",
        "user-select",
        "-webkit-user-select",
        "scroll-behavior",
        "scroll-margin-top",
    }
)
_NORMAL = {
    "display": {"block", "flow-root"},
    "position": {"static", "relative"},
    "float": {"none"},
    "transform": {"none"},
    "translate": {"none"},
    "rotate": {"none"},
    "scale": {"none"},
    "contain": {"none", "style"},
    "content-visibility": {"visible"},
    "animation": {"none"},
    "animation-name": {"none"},
    "transition": {"none"},
    "visibility": {"visible"},
    "direction": {"ltr"},
    "writing-mode": {"horizontal-tb"},
}


class SourceFlowUnavailable(ValueError):
    def __init__(self, code: str, message: str):
        self.code = "source_flow." + code
        super().__init__(f"{self.code}: {message}")


def _refuse(code, message):
    raise SourceFlowUnavailable(code, message)


def _path(value):
    if (
        not isinstance(value, (list, tuple))
        or not value
        or len(value) > MAX_DEPTH
        or any(type(x) is not int or x < 0 for x in value)
    ):
        _refuse("source_mismatch", "source DOM path is absent or invalid")
    return tuple(value)


def _children(node):
    return [n for n in node.iter(include_text=False) if n.tag and not n.tag.startswith("-")]


def _resolve(tree, path):
    node = tree.root
    for index in path:
        children = _children(node)
        if index >= len(children):
            _refuse("source_mismatch", "source DOM path does not resolve")
        node = children[index]
    return node


def _simple(compound):
    """Type, id, class and universal only; no dynamic or structural assumptions."""
    i = 0
    while i < len(compound):
        token = compound[i]
        if (
            isinstance(token, ast.IdentToken)
            and i == 0
            or isinstance(token, (ast.SquareBracketsBlock, ast.HashToken))
            or isinstance(token, ast.LiteralToken)
            and token.value == "*"
            and i == 0
        ):
            i += 1
        elif (
            isinstance(token, ast.LiteralToken)
            and token.value == "."
            and i + 1 < len(compound)
            and isinstance(compound[i + 1], ast.IdentToken)
        ):
            i += 2
        else:
            return False
    return True


def _potential(compound, node):
    """Fast negative on literal subject identity, including unsupported selectors."""
    classes = set((node.attributes.get("class") or "").split())
    for i, token in enumerate(compound):
        if i == 0 and isinstance(token, ast.IdentToken) and token.lower_value != node.tag:
            return False
        if isinstance(token, ast.SquareBracketsBlock) and node.css_first(token.serialize()) != node:
            return False
        if isinstance(token, ast.FunctionBlock) and token.lower_name in ("is", "where"):
            branches = [
                _parts(s)[0][-1] for s in _split_selector_list(tinycss2.serialize(token.arguments))
            ]
            if not any(_potential(branch, node) for branch in branches):
                return False
        if isinstance(token, ast.HashToken) and token.value != node.attributes.get("id"):
            return False
        if isinstance(token, ast.LiteralToken) and token.value == "." and i + 1 < len(compound):
            nxt = compound[i + 1]
            if isinstance(nxt, ast.IdentToken) and nxt.value not in classes:
                return False
    return True


def _may_match(parts, links, node):
    if node is None or not _potential(parts[-1], node):
        return False
    if not links:
        return True
    link = links[-1]
    cursor = node.parent if link in (" ", ">") else node.prev
    while cursor is not None:
        if cursor.tag and not cursor.tag.startswith("-"):
            if _may_match(parts[:-1], links[:-1], cursor):
                return True
            if link in (">", "+"):
                return False
        cursor = cursor.parent if link == " " else cursor.prev if link == "~" else None
    return False


def _specificity(parts):
    return (
        sum(isinstance(t, ast.HashToken) for p in parts for t in p),
        sum(
            isinstance(t, ast.SquareBracketsBlock)
            or isinstance(t, ast.LiteralToken)
            and t.value == "."
            for p in parts
            for t in p
        ),
        sum(isinstance(p[0], ast.IdentToken) for p in parts),
    )


def _tokens(tokens):
    for token in tokens:
        yield token
        if isinstance(token, ast.FunctionBlock):
            yield from _tokens(token.arguments)
        elif hasattr(token, "content"):
            yield from _tokens(token.content)


def _bounded_source(snapshot):
    strings = [snapshot.html, *(s.text for s in snapshot.stylesheets)]
    if sum(len(s.encode()) for s in strings) > MAX_SOURCE_BYTES:
        _refuse("bound", "snapshot exceeds the bounded source size")
    # Before tinycss2's recursive tokenizer: count delimiters outside CSS strings/comments.
    for text in strings[1:]:
        depth = 0
        quote = None
        comment = False
        escaped = False
        index = 0
        while index < len(text):
            char = text[index]
            pair = text[index : index + 2]
            if comment:
                if pair == "*/":
                    comment = False
                    index += 1
            elif escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif pair == "/*":
                comment = True
                index += 1
            elif char in ('"', "'"):
                quote = char
            elif char in "({[":
                depth += 1
                if depth > MAX_DEPTH:
                    _refuse("bound", "CSS nesting exceeds the supported depth")
            elif char in ")}]":
                depth -= 1
            index += 1


def compile_source_flow(snapshot: Any, members: Sequence[dict]) -> dict:
    try:
        return _compile_source_flow(snapshot, members)
    except SourceFlowUnavailable:
        raise
    except (ValueError, TypeError, RecursionError, AttributeError, IndexError) as error:
        raise SourceFlowUnavailable(
            "invalid_source", "captured source could not be safely parsed"
        ) from error


def _compile_source_flow(snapshot: Any, members: Sequence[dict]) -> dict:
    if not members or len(members) > MAX_MEMBERS:
        _refuse("bound", "group member count exceeds the supported bound")
    _bounded_source(snapshot)
    tree = HTMLParser(snapshot.html)
    if sum(1 for _ in tree.root.traverse()) > 100000:
        _refuse("bound", "HTML node count exceeds the supported bound")
    ordered = sorted(members, key=lambda r: _path((r.get("provenance") or {}).get("dom_path")))
    first = ordered[0].get("provenance") or {}
    recovery = first.get("recovery") or {}
    parent_path = _path(recovery.get("parent_dom_path"))
    parent = _resolve(tree, parent_path)
    if parent.parent != tree.body:
        _refuse(
            "unsupported_topology", "layout ancestors above the recovery parent are not represented"
        )
    resolved = []
    for row in ordered:
        p = row.get("provenance") or {}
        r = p.get("recovery") or {}
        if (
            row.get("derived_from")
            or p.get("snapshot_id") != snapshot.snapshot_id
            or p.get("page_url") != snapshot.page_url
            or r.get("mode") != "authored-descendant-after-refusal"
            or _path(r.get("parent_dom_path")) != parent_path
            or r.get("parent_section_index") != recovery.get("parent_section_index")
        ):
            _refuse(
                "source_mismatch",
                "members do not share the exact captured parent; repairs require separate proof",
            )
        path = _path(p.get("dom_path"))
        if path[: len(parent_path)] != parent_path or len(path) <= len(parent_path):
            _refuse("source_mismatch", "member is outside the captured parent")
        node = _resolve(tree, path)
        if (
            node.tag != "section"
            or p.get("tag") != node.tag
            or p.get("element_id") != node.attributes.get("id")
        ):
            _refuse("source_mismatch", "member tag or identity differs from the frozen source")
        if not set(p.get("class_names") or []).issubset(
            (node.attributes.get("class") or "").split()
        ):
            _refuse("source_mismatch", "member classes differ from the frozen source")
        resolved.append(node)
    if len({n.mem_id for n in resolved}) != len(resolved) or any(
        n.parent != resolved[0].parent for n in resolved
    ):
        _refuse("unsupported_topology", "members are not distinct direct siblings")
    chain = []
    node = resolved[0].parent
    while node is not None:
        chain.append(node)
        if node == parent:
            break
        node = node.parent
    if not chain or chain[-1] != parent or len(chain) > MAX_ANCESTORS:
        _refuse("unsupported_topology", "common ancestor chain exceeds the supported bound")
    chain.reverse()
    # Root/body are non-layout contexts solely for custom-property inheritance.
    targets = [tree.root, tree.body, *chain]
    extras = []
    for i, ancestor in enumerate(chain):
        expected = [chain[i + 1]] if i + 1 < len(chain) else resolved
        for child in _children(ancestor):
            if child not in expected:
                if i + 1 == len(chain) and child.tag == "section":
                    continue  # Unreleased/refused sibling stays absent, reported below.
                extras.append(child)
        child = ancestor.child
        while child is not None:
            if child.tag == "-text" and child.text().strip():
                _refuse("unsupported_topology", "ancestor contains unrepresented text")
            child = child.next
    targets.extend(extras)
    units = prepare_root_units(
        snapshot.stylesheets,
        html=snapshot.html,
        initial_font_px=(snapshot.meta or {}).get("initial_font_px"),
    )
    if units.notes:
        _refuse("unsupported_units", "; ".join(units.notes))
    entries = []
    winners: dict[tuple[int, str], tuple[tuple, str]] = {}
    variables: dict[str, list[tuple[int, Any]]] = {}
    rules_seen = 0
    max_ids = 0
    match_cache = {}

    def keep(selector, declarations, conditions):
        nonlocal max_ids
        try:
            parts, links = _parts(selector)
        except ValueError:
            _refuse("unsupported_selector", "unparseable source selector")
        # :root is an exact source fact, with class-level specificity.
        is_root = selector == ":root"
        simple = is_root or all(_simple(p) for p in parts) and all(c in (" ", ">") for c in links)
        specificity = (0, 1, 0) if is_root else _specificity(parts)
        max_ids = max(max_ids, specificity[0])
        for owner, target in enumerate(targets):
            relevant = [d for d in declarations if d.lower_name not in _NON_LAYOUT]
            if not relevant or not (
                is_root and owner == 0 or not is_root and _potential(parts[-1], target)
            ):
                continue
            if not is_root and not _may_match(parts, links, target):
                continue
            if not simple:
                # Pseudo-element resets without generated content do not create boxes.
                text = selector.lower()
                if ("::" in text or ":before" in text or ":after" in text) and not any(
                    d.lower_name == "content" for d in relevant
                ):
                    continue
                _refuse("unsupported_selector", f"layout may depend on {selector[:160]}")
            key = (selector, owner)
            if key not in match_cache:
                match_cache[key] = (owner == 0) if is_root else _may_match(parts, links, target)
            if not match_cache[key]:
                continue
            if any(k not in ("media", "supports") for k, _ in conditions):
                _refuse(
                    "unsupported_condition",
                    "ancestor layout uses an unsupported conditional or layer",
                )
            for d in relevant:
                if owner < 2 + len(chain) and not (
                    d.name.startswith("--")
                    or d.lower_name in _BOX
                    or owner < 2
                    and d.lower_name in _INHERITED | _PAINT
                ):
                    _refuse("unsupported_property", f"ancestor property {d.name} is not supported")
                if (
                    owner < 2
                    and conditions
                    and not (
                        d.name.startswith("--")
                        or d.lower_name == "box-sizing"
                        or d.lower_name in _INHERITED - {"direction", "writing-mode"}
                    )
                ):
                    _refuse(
                        "unsupported_document_layout",
                        "conditional document layout cannot be represented by a non-layout context",
                    )
                entries.append((owner, selector, d, conditions, specificity, False))
                if d.name.startswith("--"):
                    variables.setdefault(d.name, []).append((owner, d))
                if not conditions:
                    rank = (d.important, 0, *specificity, len(entries))
                    prior = winners.get((owner, d.lower_name))
                    if prior is None or rank > prior[0]:
                        winners[owner, d.lower_name] = (rank, tinycss2.serialize(d.value).strip())
                elif (
                    d.lower_name in _NORMAL
                    and tinycss2.serialize(d.value).strip() not in _NORMAL[d.lower_name]
                ):
                    _refuse(
                        "unsupported_layout", f"conditional {d.lower_name} is outside normal flow"
                    )

    def walk(rules, conditions=()):
        nonlocal rules_seen
        for rule in rules:
            rules_seen += 1
            if rules_seen > _MAX_RULES:
                _refuse("bound", "stylesheet rule count exceeds bound")
            if isinstance(rule, ast.QualifiedRule):
                declarations = [
                    d
                    for d in tinycss2.parse_declaration_list(
                        rule.content, skip_whitespace=True, skip_comments=True
                    )
                    if isinstance(d, ast.Declaration)
                ]
                for selector in _split_selector_list(tinycss2.serialize(rule.prelude)):
                    keep(selector.strip(), declarations, conditions)
            elif (
                isinstance(rule, ast.AtRule)
                and rule.content is not None
                and rule.lower_at_keyword
                not in ("font-face", "keyframes", "-webkit-keyframes", "property")
            ):
                walk(
                    tinycss2.parse_rule_list(
                        rule.content, skip_whitespace=True, skip_comments=True
                    ),
                    (*conditions, (rule.lower_at_keyword, tinycss2.serialize(rule.prelude))),
                )

    normalized_sheets = list(units.stylesheets)
    if units.variable is not None:
        synthetic = normalized_sheets.pop(0)
        walk(tinycss2.parse_stylesheet(synthetic.text, skip_whitespace=True, skip_comments=True))
        # The root-unit seam's generated default is a fallback, not an authored
        # :root selector that may outrank a later html font-size rule.
        entries[:] = [(o, "*", d, c, (0, 0, 0), inline) for o, _, d, c, _, inline in entries]
    for original, normalized in zip(snapshot.stylesheets, normalized_sheets, strict=True):
        if getattr(original, "disabled", False):
            continue
        conditions = (("media", original.media),) if getattr(original, "media", None) else ()
        walk(
            tinycss2.parse_stylesheet(normalized.text, skip_whitespace=True, skip_comments=True),
            conditions,
        )
    for owner, target in enumerate(targets):
        for d in tinycss2.parse_declaration_list(
            target.attributes.get("style", ""), skip_comments=True, skip_whitespace=True
        ):
            if not isinstance(d, ast.Declaration) or d.lower_name in _NON_LAYOUT:
                continue
            if owner < 2 + len(chain) and not (
                d.name.startswith("--")
                or d.lower_name in _BOX
                or owner < 2
                and d.lower_name in _INHERITED | _PAINT
            ):
                _refuse(
                    "unsupported_property", f"inline ancestor property {d.name} is not supported"
                )
            if any(
                isinstance(t, ast.DimensionToken) and t.lower_unit == "rem"
                for t in _tokens(d.value)
            ):
                _refuse(
                    "unsupported_units",
                    "inline rem layout requires normalized source inline context",
                )
            entries.append((owner, "", d, (), (max_ids + 1, 0, 0), True))
            if d.name.startswith("--"):
                variables.setdefault(d.name, []).append((owner, d))
            rank = (d.important, 1, 0, 0, 0, len(entries))
            prior = winners.get((owner, d.lower_name))
            if prior is None or rank > prior[0]:
                winners[owner, d.lower_name] = (rank, tinycss2.serialize(d.value).strip())
    body_margin = winners.get((1, "margin"))
    physical_sides = [
        winners.get((1, "margin-" + side)) for side in ("top", "right", "bottom", "left")
    ]
    if body_margin is None and not all(physical_sides):
        _refuse(
            "unsupported_document_layout",
            "source body has no proven neutral margin reset; "
            "browser default margin is not represented",
        )
    for owner in range(2):
        for (subject, name), (_, value) in winners.items():
            if (
                subject != owner
                or name.startswith("--")
                or name == "box-sizing"
                or name in _INHERITED - {"direction", "writing-mode"}
                or name in {"background", "background-color", "background-image"}
            ):
                continue
            neutral = (
                name == "direction"
                and value == "ltr"
                or name == "writing-mode"
                and value == "horizontal-tb"
                or name == "display"
                and value == "block"
                or name == "position"
                and value == "static"
                or name in {"top", "right", "bottom", "left", "inset", "width", "height"}
                and value in {"auto", "unset", "initial"}
                or name.startswith(("margin", "padding"))
                and all(v in {"0", "0px"} for v in value.split())
                or name in {"overflow", "overflow-x", "overflow-y"}
                and value in {"visible", "auto", "scroll"}
                or owner == 0
                and name == "height"
                and value == "100%"
                and winners.get((1, "height"), (None, "auto"))[1] in {"auto", "unset", "initial"}
            )
            if not neutral:
                _refuse(
                    "unsupported_document_layout",
                    f"document {name}:{value} cannot be represented by a non-layout context",
                )
    for owner in range(2, 2 + len(chain)):
        for name, allowed in _NORMAL.items():
            found = winners.get((owner, name))
            if found and found[1] not in allowed:
                _refuse("unsupported_layout", f"{name}:{found[1]} is outside normal flow")
        if winners.get((owner, "all")) or winners.get((owner, "content")):
            _refuse("unsupported_layout", "ancestor reset or generated content is not supported")
        if chain[owner - 2].tag not in ("div", "main", "section", "article") and not winners.get(
            (owner, "display")
        ):
            _refuse("unsupported_layout", "source custom element lacks an explicit block display")
    omitted = []
    for owner, extra in enumerate(extras, 2 + len(chain)):
        display = winners.get((owner, "display"), (None, ""))[1]
        position = winners.get((owner, "position"), (None, ""))[1]
        if display != "none" and position != "fixed":
            _refuse("unsupported_topology", "unrepresented ancestor child participates in flow")
        if any(o == owner and c for o, _, _, c, _, _ in entries):
            _refuse("unsupported_topology", "omitted child has conditional layout")
        omitted.append(
            {"tag": extra.tag, "reason": "display:none" if display == "none" else "position:fixed"}
        )
    used_variables = set()
    dependency_checks = 0
    checked_variables = set()

    def dependencies(tokens, owner, visiting=(), allow_inherit=False):
        nonlocal dependency_checks
        dependency_checks += 1
        if dependency_checks > _MAX_RULES:
            _refuse("bound", "custom-property dependency expansion exceeds bound")
        if len(visiting) > MAX_DEPTH:
            _refuse("bound", "custom-property dependency depth exceeds bound")
        for t in _tokens(tokens):
            if isinstance(t, ast.IdentToken) and (
                t.lower_value in {"revert", "revert-layer", "currentcolor"}
                or t.lower_value == "inherit"
                and not allow_inherit
            ):
                _refuse(
                    "unsupported_context",
                    "ancestor value depends on unrepresented inherited or host context",
                )
            if isinstance(t, ast.DimensionToken) and t.lower_unit in {
                "em",
                "ex",
                "ch",
                "cap",
                "ic",
                "lh",
                "rlh",
                "rex",
                "rch",
                "rcap",
                "ric",
            }:
                _refuse(
                    "unsupported_units",
                    "font-relative ancestor layout lacks a verified font context",
                )
            if (
                t.type in ("url", "error")
                or isinstance(t, ast.FunctionBlock)
                and t.lower_name in ("url", "image-set", "-webkit-image-set")
            ):
                _refuse(
                    "unowned_dependency", "ancestor CSS requires byte-loading or invalid values"
                )
            if not isinstance(t, ast.FunctionBlock) or t.lower_name != "var":
                continue
            args = [a for a in t.arguments if a.type not in ("whitespace", "comment")]
            if not args or not isinstance(args[0], ast.IdentToken):
                _refuse("unresolved_variable", "invalid custom-property reference")
            name = args[0].value
            if name in visiting:
                _refuse("unresolved_variable", "cyclic custom-property dependency")
            definitions = [(o, d) for o, d in variables.get(name, []) if o <= owner]
            fallback = any(isinstance(a, ast.LiteralToken) and a.value == "," for a in args)
            if not definitions and not fallback:
                _refuse("unresolved_variable", f"no captured definition for {name}")
            used_variables.add(name)
            if (name, owner, allow_inherit) not in checked_variables:
                for o, d in definitions:
                    dependencies(d.value, o, (*visiting, name), allow_inherit)
                checked_variables.add((name, owner, allow_inherit))

    for owner, _, d, _, _, _ in entries:
        if 2 <= owner < 2 + len(chain) and not d.name.startswith("--"):
            dependencies(d.value, owner, allow_inherit=d.lower_name == "box-sizing")
    identity = json.dumps(
        [snapshot.snapshot_id, parent_path, [r["fragment_id"] for r in ordered]],
        separators=(",", ":"),
    )
    prefix = "lumen-source-flow-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    classes = [prefix + "-n" + str(i) for i in range(2 + len(chain))]
    css = [
        ":where(" + ",".join("." + c for c in classes) + "){box-sizing:content-box;}",
        f":where(.{classes[0]},.{classes[1]})" + "{display:contents!important;}",
    ]
    for owner, selector, d, conditions, specificity, inline in entries:
        if owner >= len(classes) or d.name.startswith("--") and d.name not in used_variables:
            continue
        if owner < 2 and not d.name.startswith("--") and d.lower_name != "box-sizing":
            continue
        target = f":where(.{classes[owner]})"
        if inline:
            target += "".join(f":not(#{prefix}-absent-{i})" for i in range(specificity[0]))
        elif selector != "*":
            target += f":is({selector},:where(.{classes[owner]}))"
        serialized = d.serialize() + ";"
        if owner == 0 and d.lower_name == "box-sizing":
            normalized = _root_box_sizing(d.value)
            if normalized is not None:
                serialized = (
                    "box-sizing:"
                    + tinycss2.serialize(normalized)
                    + ("!important" if d.important else "")
                    + ";"
                )
        text = target + "{" + serialized + "}"
        for keyword, condition in reversed(conditions):
            text = "@" + keyword + " " + condition + "{" + text + "}"
        css.append(text)
    css = "\n".join(css)
    if len(css.encode()) > MAX_CSS_BYTES or "</style" in css.lower() or "@import" in css.lower():
        _refuse("bound", "projected CSS exceeds the safe response boundary")
    missing = [
        n.attributes.get("id") or n.tag
        for n in _children(chain[-1])
        if n.tag == "section" and n not in resolved
    ]
    return {
        "group_id": prefix,
        "snapshot_id": snapshot.snapshot_id,
        "source_html_sha256": hashlib.sha256(snapshot.html.encode()).hexdigest(),
        "parent_dom_path": list(parent_path),
        "member_ids": [r["fragment_id"] for r in ordered],
        "nodes": [
            {"classes": classes[i], "source_tag": n.tag}
            for i, n in enumerate(targets[: len(classes)])
        ],
        "css": css,
        "omitted_nonflow": omitted,
        "omitted_authored_sections": missing,
        "limitations": [
            "Only the shared ancestor box is reconstructed; document paint and "
            "source programs remain outside this envelope."
        ],
        "fidelity_verified": False,
    }
