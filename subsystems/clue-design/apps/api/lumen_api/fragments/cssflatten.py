"""Flatten ``@layer`` structure out of a fragment stylesheet at capture (2026-08-29 ruling).

Why stored CSS may not carry cascade layers: the editor render wraps every fragment sheet in
the platform's own ``@layer base`` block (so a human's inspector utilities can override theme
defaults), which demotes a clone's internal layers to NESTED sub-layers — and the cascade ranks
a layer's direct rules above all of its sub-layers, specificity never consulted. Tailwind's
zero-specificity preflight reset (``* { margin: 0; padding: 0 }``, ``h1 { font-size: inherit }``)
therefore beat every scoped clone rule: sections lost their centering and headings collapsed to
body size on the Stripe recreate. Root-cause record:
``_memory/2026-08-29-clone-assembly-layer-cascade-bug.md``.

The browser's layer ranking is emulated with plain source order, which the cascade resolves the
same way at equal specificity:

* layers rank by FIRST declaration (a ``@layer a, b;`` statement or a block), in declaration
  order — an earlier-declared layer loses to a later one, so its rules serialize first;
* un-layered rules beat every layer, so they serialize last;
* within one rank, source order is preserved;
* a conditional wrapper (``@media``/``@supports``/``@container``) around layered content is
  re-emitted around the same content at the layer's rank, so no breakpoint is lost;
* a nested sub-layer collapses into its outermost layer's rank, keeping source order — the
  fine-grained sub-ranking is not representable in plain order, and no harvested site has
  needed it.

Known, deliberate approximation: order emulates layer priority only at EQUAL specificity. A
sheet relying on a weak selector in a high layer beating a strong selector in a low layer
flattens differently than it cascades natively. The flatten note names every collapsed layer so
a human has the thread to pull if a site ever trips this; ``:where()`` de-specifying is the
escape hatch when one does.
"""

from __future__ import annotations

import tinycss2
from tinycss2 import ast

__all__ = ["flatten_css_layers"]

#: Conditional group rules whose condition must survive around re-bucketed content.
_CONDITIONAL_AT_RULES = frozenset({"media", "supports", "container"})

#: Rank of rules outside any layer: they win, so they serialize after every real rank.
_UNLAYERED = float("inf")


def flatten_css_layers(css: str, *, notes: list[str]) -> str:
    """Return ``css`` with all ``@layer`` structure removed, order emulating layer rank.

    Appends one human-readable note when anything was flattened; a sheet with no ``@layer``
    comes back byte-identical.
    """
    if "@layer" not in css:
        return css

    ranks: dict[str, int] = {}
    anonymous = 0

    def rank_of(name: str) -> int:
        if name not in ranks:
            ranks[name] = len(ranks)
        return ranks[name]

    # (rank, sequence, condition-stack, rule text); sequence keeps the sort stable so
    # source order survives within a rank.
    buckets: list[tuple[float, int, tuple[str, ...], str]] = []

    def emit(rank: float, condition: tuple[str, ...], text: str) -> None:
        buckets.append((rank, len(buckets), condition, text))

    def walk(rules: list[object], condition: tuple[str, ...], rank: float) -> None:
        nonlocal anonymous
        for rule in rules:
            if isinstance(rule, ast.AtRule) and rule.lower_at_keyword == "layer":
                prelude = tinycss2.serialize(rule.prelude).strip()
                if rule.content is None:
                    # Statement form (`@layer a, b;`): fixes the ranking, emits nothing.
                    for name in (part.strip() for part in prelude.split(",")):
                        if name:
                            rank_of(name)
                    continue
                if prelude:
                    name = prelude
                else:
                    # Every anonymous block is its own layer, per spec.
                    anonymous += 1
                    name = f"<anonymous {anonymous}>"
                inner = tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )
                # A sub-layer collapses into its outermost layer's rank (module docstring).
                walk(inner, condition, rank if rank != _UNLAYERED else float(rank_of(name)))
                continue
            if (
                isinstance(rule, ast.AtRule)
                and rule.lower_at_keyword in _CONDITIONAL_AT_RULES
                and rule.content is not None
            ):
                head = f"@{rule.at_keyword} {tinycss2.serialize(rule.prelude).strip()}".rstrip()
                inner = tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )
                walk(inner, condition + (head,), rank)
                continue
            if isinstance(rule, ast.ParseError):
                # The scoper already dropped unparseable css with a note; nothing to keep here.
                continue
            emit(rank, condition, rule.serialize().strip())

    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    walk(rules, (), _UNLAYERED)
    if not ranks:
        # `@layer` appeared only in text (a string, a comment): nothing structural to do.
        return css

    buckets.sort(key=lambda item: (item[0], item[1]))

    # Re-serialize, coalescing ADJACENT same-condition rules back into one wrapper so a
    # split conditional does not multiply into one block per rule.
    out: list[str] = []
    open_condition: tuple[str, ...] = ()
    run: list[str] = []

    def flush() -> None:
        nonlocal run
        if not run:
            return
        text = "\n".join(run)
        for head in reversed(open_condition):
            text = f"{head} {{ {text} }}"
        out.append(text)
        run = []

    for _, _, condition, text in buckets:
        if condition != open_condition:
            flush()
            open_condition = condition
        run.append(text)
    flush()

    notes.append(
        "flattened css cascade layers into plain rule order: " + ", ".join(ranks)
    )
    return "\n".join(out)
