"""Transport source rem lengths into a fragment without changing the host html.

CSS media-query thresholds deliberately stay in their original units: rem in a
media query refers to the browser's initial font, not the source root's font.
This supports literal html/:root font sizes and their media/supports overrides.
More complex root cascades are reported, never approximated from one viewport.
Original captured sheets and HTML remain immutable; only mint inputs change.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import tinycss2
from selectolax.parser import HTMLParser
from tinycss2 import ast

_NESTED = frozenset(
    {
        "media",
        "supports",
        "container",
        "layer",
        "scope",
        "keyframes",
        "-webkit-keyframes",
        "-moz-keyframes",
    }
)
_ROOTS = frozenset({"html", ":root"})
_FONT_PROPERTIES = frozenset({"font-size", "font", "all"})


@dataclass(frozen=True)
class _Sheet:
    url: str
    text: str


@dataclass(frozen=True)
class RootUnits:
    stylesheets: Sequence[Any]
    variable: str | None = None
    initial_px: float = 16.0
    basis: str = "legacy_chromium_default"
    rule_count: int = 0
    notes: tuple[str, ...] = ()

    def provenance(self) -> dict[str, Any]:
        return {
            "normalized": self.variable is not None,
            "root_rules": self.rule_count,
            "initial_font_px": self.initial_px,
            "initial_font_basis": self.basis,
            "limitations": list(self.notes),
        }

    def markup(self, html: str) -> str:
        if self.variable is None:
            return html
        tree = HTMLParser(html)
        for node in tree.css("[style]"):
            node.attrs["style"] = _declarations(node.attributes["style"], self.variable)
        if tree.body is None:
            return html
        children = []
        node = tree.body.child
        while node is not None:
            children.append(node.html or "")
            node = node.next
        return "".join(children)


def prepare_root_units(
    stylesheets: Sequence[Any],
    *,
    html: str,
    initial_font_px: float | None = None,
) -> RootUnits:
    """Derive an isolated unit context once per page, before matching sections.

    New captures supply measured browser-medium size. Older snapshots were captured
    with Chromium defaults; the 16px fallback is labelled in provenance, not a
    measured source-root value. Responsive source root rules remain responsive.
    """
    initial = 16.0
    basis = "legacy_chromium_default"
    if (
        isinstance(initial_font_px, (int, float))
        and not isinstance(initial_font_px, bool)
        and math.isfinite(initial_font_px)
        and 0 < initial_font_px <= 256
    ):
        initial, basis = float(initial_font_px), "captured_browser_medium"
    parsed = [
        (
            str(getattr(s, "url", "") or ""),
            tinycss2.parse_stylesheet(
                getattr(s, "text", "") or "", skip_comments=True, skip_whitespace=True
            ),
        )
        for s in stylesheets
    ]
    tree = HTMLParser(html)
    root_classes = (
        set((tree.root.attributes.get("class", "") or "").split()) if tree.root else set()
    )
    issues: set[str] = set()
    count = 0
    root_selectors: set[str] = set()
    for _, rules in parsed:
        for rule, ancestors in _walk(rules):
            if not isinstance(rule, ast.QualifiedRule):
                continue
            selectors = tinycss2.serialize(rule.prelude).strip().split(",")
            selectors = [s.strip() for s in selectors]
            decls = tinycss2.parse_declaration_list(rule.content)
            fonts = [
                d
                for d in decls
                if isinstance(d, ast.Declaration) and d.lower_name in _FONT_PROPERTIES
            ]
            if not fonts or not any(_possible_root(s, root_classes) for s in selectors):
                continue
            if not set(selectors) <= _ROOTS:
                issues.add("root font uses a compound, mixed or state selector")
                continue
            root_selectors.update(selectors)
            if any(a not in {"media", "supports"} for a in ancestors):
                issues.add("root font uses a layer, container, scope or keyframe context")
            for d in fonts:
                if d.lower_name != "font-size" or _root_length(d.value, initial) is None:
                    issues.add("root font uses a shorthand, variable, keyword or expression")
                else:
                    count += 1
    if tree.root and any(
        isinstance(d, ast.Declaration) and d.lower_name in _FONT_PROPERTIES
        for d in tinycss2.parse_declaration_list(tree.root.attributes.get("style", "") or "")
    ):
        issues.add("root font uses an inline declaration")
    if len(root_selectors) > 1:
        issues.add("root font combines html and :root specificity")
    if issues or not count:
        return RootUnits(stylesheets, initial_px=initial, basis=basis, notes=tuple(sorted(issues)))
    source = "\n".join(getattr(s, "text", "") or "" for s in stylesheets)
    variable = "--lumen-source-rem-" + hashlib.sha256(source.encode()).hexdigest()[:12]
    if variable in source or variable in html:
        return RootUnits(stylesheets, notes=("source root-unit property collision",))
    derived = [_Sheet("inline:source-root-unit", f":root {{{variable}:{initial:g}px}}")]
    try:
        for url, rules in parsed:
            derived.append(_Sheet(url, _rules(rules, variable, initial)))
        # Validate inline declaration serialization before changing any mint inputs.
        for node in tree.css("[style]"):
            _declarations(node.attributes["style"], variable)
    except (TypeError, ValueError):
        # Keep the original CSS so the existing per-section sanitizer/custody gates
        # still decide what can be reused. Never let this fidelity pass erase a page.
        return RootUnits(
            stylesheets,
            initial_px=initial,
            basis=basis,
            notes=("source declarations could not be normalized",),
        )
    return RootUnits(tuple(derived), variable, initial, basis, count)


def _possible_root(selector: str, classes: set[str]) -> bool:
    # Conservative: unsupported root contexts must not silently become a fixed scale.
    return (
        selector in _ROOTS
        or selector == "*"
        or selector in {"." + c for c in classes}
        or bool(re.search(r"(?<![\w-])html(?![\w-])|:root\b", selector))
    )


def _walk(rules, ancestors=()):
    for rule in rules:
        yield rule, ancestors
        if (
            isinstance(rule, ast.AtRule)
            and rule.content is not None
            and rule.lower_at_keyword in _NESTED
        ):
            yield from _walk(
                tinycss2.parse_rule_list(rule.content), (*ancestors, rule.lower_at_keyword)
            )


def _root_length(tokens, initial: float) -> str | None:
    values = [t for t in tokens if t.type not in {"whitespace", "comment"}]
    if len(values) != 1:
        return None
    value = values[0]
    if isinstance(value, ast.PercentageToken):
        return f"{value.value * initial / 100:g}px" if value.value >= 0 else None
    if isinstance(value, ast.DimensionToken) and value.lower_unit in {"px", "em", "rem"}:
        scale = 1 if value.lower_unit == "px" else initial
        return f"{value.value * scale:g}px" if value.value >= 0 else None
    return None


def _values(tokens, variable: str):
    out = []
    for token in tokens:
        if isinstance(token, ast.DimensionToken) and token.lower_unit == "rem":
            out.extend(
                tinycss2.parse_component_value_list(f"calc({token.value:g} * var({variable}))")
            )
        else:
            # Strings and URL tokens are opaque, including quoted url() arguments.
            if isinstance(token, ast.FunctionBlock) and token.lower_name != "url":
                token.arguments = _values(token.arguments, variable)
            elif isinstance(
                token, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)
            ):
                token.content = _values(token.content, variable)
            out.append(token)
    return out


def _declarations(content, variable: str, initial: float | None = None) -> str:
    declarations = tinycss2.parse_declaration_list(
        content, skip_comments=True, skip_whitespace=True
    )
    out = []
    for d in declarations:
        if isinstance(d, ast.Declaration):
            root_value = (
                _root_length(d.value, initial)
                if initial is not None and d.lower_name == "font-size"
                else None
            )
            if root_value is not None:
                important = " !important" if d.important else ""
                out.append(f"{d.name}:{root_value}{important};{variable}:{root_value}{important};")
                continue
            d.value = _values(d.value, variable)
        out.append(tinycss2.serialize([d]))
    return "".join(out)


def _rules(rules, variable: str, initial: float) -> str:
    out = []
    for rule in rules:
        if isinstance(rule, ast.QualifiedRule):
            selector = tinycss2.serialize(rule.prelude).strip()
            is_root = {s.strip() for s in selector.split(",")} <= _ROOTS
            content = _declarations(rule.content, variable, initial if is_root else None)
            out.append(f"{selector}{{{content}}}")
        elif isinstance(rule, ast.AtRule) and rule.content is not None:
            # Query/support/container preludes are not declaration values. Never rescale them.
            prelude = tinycss2.serialize(rule.prelude)
            if rule.lower_at_keyword in _NESTED:
                content = _rules(tinycss2.parse_rule_list(rule.content), variable, initial)
            else:
                content = _declarations(rule.content, variable)
            out.append(f"@{rule.at_keyword}{prelude}{{{content}}}")
        elif not isinstance(rule, ast.ParseError):
            out.append(tinycss2.serialize([rule]))
    return "\n".join(out)
