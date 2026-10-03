"""Keep foreign fragment classes out of the editor's Tailwind candidate set.

Static delivery already scans document-only markup. The browser runtime instead
scans every class in the DOM, including names such as a captured site's
``container``. Its compiler supports ``@source not inline`` exclusions even though
``source(none)`` does not disable that DOM scan. Exclude only fragment-interior
candidates that no native element asks for. This is a compiler-input change: stored
artifacts, rendered markup, fragment CSS, and delivery HTML remain untouched.
"""

from __future__ import annotations

import re
from typing import Any

from selectolax.lexbor import LexborHTMLParser

MAX_RENDER_CHARS = 64 * 1024 * 1024
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_COMPILER_PREFIX_BYTES = 64 * 1024
MAX_SCAN_NODES = 100_000
MAX_DISTINCT_TOKENS = 16_384
MAX_EXCLUSIONS = 4_096
MAX_DIRECTIVE_BYTES = 128 * 1024
MAX_TOKEN_CHARS = 256

_BLOCK_START = '<style type="text/tailwindcss">'
_TOKEN = re.compile(r"[^\t\n\f\r ]+")  # HTML classList uses ASCII whitespace only.
# Quotes/backslashes cannot be safely round-tripped through this compiler's
# string handling. Braces invoke its unescaped expansion grammar, even inside
# quotes. Do not try to CSS-escape either into a different candidate. Reject
# unsupported syntax explicitly, also excluding markup closers and controls.
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_:/%.#\[\]()!,+*=~^|&?@$-]+\Z")


def _warning(code: str, message: str) -> dict[str, Any]:
    return {
        "severity": "warning",
        "phase": "web",
        "code": code,
        "message": message,
        "subject": None,
        "hint": (
            "Inspect editor and delivery output; incomplete isolation is not a fidelity pass."
        ),
    }


def isolate_fragment_candidates(html: str) -> tuple[str, list[dict[str, Any]]]:
    """Insert bounded exact exclusions into the engine's canonical editor block.

    The engine marks each outer clone boundary with ``data-fragment-root``.
    A nested source marker cannot turn an interior back into native markup.
    Root-wrapper classes stay native because they belong to the WebDoc node.
    A complete scan is required before subtracting native candidates: a partial
    scan could suppress a native utility encountered later in the document.
    """
    if 'data-fragment-root="true"' not in html:
        return html, []
    if len(html) > MAX_RENDER_CHARS:
        return html, [
            _warning(
                "fragment.editor_candidate_limited",
                "Candidate isolation was not applied: rendered HTML exceeds the input bound.",
            )
        ]

    # The engine emits one canonical head/body envelope. Its large fragment CSS
    # remains opaque: the real frozen AWS head exceeds 33 MB, but its body is
    # under 0.5 MB. Parsing CSS as DOM input would spend the wrong scan budget.
    head_end = html.find("</head>")
    body_start = head_end + len("</head>")
    while body_start < len(html) and html[body_start] in " \t\n\r\f":
        body_start += 1
    body_end = html.rfind("</body>")
    if head_end < 0 or not html.startswith("<body", body_start) or body_end < body_start:
        return html, [
            _warning(
                "fragment.editor_candidate_block",
                "Editor candidate isolation was not applied: "
                "the canonical head/body boundary is missing.",
            )
        ]
    body_html = html[body_start : body_end + len("</body>")]
    if len(body_html) > MAX_BODY_BYTES or len(body_html.encode("utf-8")) > MAX_BODY_BYTES:
        return html, [
            _warning(
                "fragment.editor_candidate_limited",
                "Editor candidate isolation was not applied: "
                "rendered body exceeds the scan byte bound.",
            )
        ]
    tree = LexborHTMLParser(body_html)
    native: set[str] = set()
    foreign: set[str] = set()
    stack = [(tree.root, False)] if tree.root is not None else []
    visited = 0
    while stack:
        node, inside_fragment = stack.pop()
        visited += 1
        if visited > MAX_SCAN_NODES:
            return html, [
                _warning(
                    "fragment.editor_candidate_limited",
                    "Editor candidate isolation was not applied: "
                    "rendered DOM exceeds the scan node bound.",
                )
            ]
        attrs = node.attributes
        target = foreign if inside_fragment else native
        target.update(match.group() for match in _TOKEN.finditer(attrs.get("class") or ""))
        if len(native) + len(foreign) > MAX_DISTINCT_TOKENS:
            return html, [
                _warning(
                    "fragment.editor_candidate_limited",
                    "Editor candidate isolation was not applied: "
                    "rendered classes exceed the scan token bound.",
                )
            ]
        if node.next is not None:
            stack.append((node.next, inside_fragment))
        if node.child is not None:
            stack.append((node.child, inside_fragment or attrs.get("data-fragment-root") == "true"))

    diagnostics: list[dict[str, Any]] = []
    shared = native & foreign
    if shared:
        diagnostics.append(
            _warning(
                "fragment.editor_shared_candidates",
                f"Native markup and cloned interiors share {len(shared)} class candidate(s). "
                "Native utilities remain enabled and may affect the clone; existing source-class "
                "collision diagnostics and visual comparison still apply.",
            )
        )
    exclusive = sorted(foreign - native)
    if not exclusive:
        return html, diagnostics

    # Only the renderer-owned, single direct head block may receive input. No
    # document parse/serialization round trip: that would change frozen markup.
    start = html.find(_BLOCK_START)
    compiler_end = html.find("</style>", start + len(_BLOCK_START))
    if html.count(_BLOCK_START) != 1 or not (0 <= start < compiler_end < head_end):
        diagnostics.append(
            _warning(
                "fragment.editor_candidate_block",
                "Editor candidate isolation was not applied: the canonical Tailwind head block "
                "is missing or ambiguous.",
            )
        )
        return html, diagnostics
    prefix = html[: compiler_end + len("</style>")]
    if (
        len(prefix) > MAX_COMPILER_PREFIX_BYTES
        or len(prefix.encode("utf-8")) > MAX_COMPILER_PREFIX_BYTES
    ):
        diagnostics.append(
            _warning(
                "fragment.editor_candidate_limited",
                "Editor candidate isolation was not applied: "
                "the compiler head prefix exceeds its bound.",
            )
        )
        return html, diagnostics
    compiler_tree = LexborHTMLParser(prefix + "</head><body></body></html>")
    blocks = compiler_tree.css('head > style[type="text/tailwindcss"]')
    if len(blocks) != 1 or blocks[0].text() != html[start + len(_BLOCK_START) : compiler_end]:
        diagnostics.append(
            _warning(
                "fragment.editor_candidate_block",
                "Editor candidate isolation was not applied: "
                "the Tailwind block is not canonical head content.",
            )
        )
        return html, diagnostics

    accepted: list[str] = []
    skipped = 0
    limited = 0
    directive_bytes = len('\n@source not inline("");\n')
    for token in exclusive:
        if len(token) > MAX_TOKEN_CHARS or _SAFE_TOKEN.fullmatch(token) is None:
            skipped += 1
            continue
        additional = len(token) + (1 if accepted else 0)  # accepted grammar is ASCII
        if len(accepted) >= MAX_EXCLUSIONS or directive_bytes + additional > MAX_DIRECTIVE_BYTES:
            limited += 1
            continue
        accepted.append(token)
        directive_bytes += additional
    if skipped:
        diagnostics.append(
            _warning(
                "fragment.editor_candidate_skipped",
                f"Candidate isolation skipped {skipped} unsupported/oversized class token(s); "
                "no quote, backslash, brace expansion, or markup syntax was interpolated. "
                "Those candidates remain eligible for the browser compiler.",
            )
        )
    if limited:
        diagnostics.append(
            _warning(
                "fragment.editor_candidate_limited",
                f"Candidate isolation omitted {limited} class token(s) at the directive count/byte "
                "bound; those candidates remain eligible for the browser compiler.",
            )
        )
    if not accepted:
        return html, diagnostics
    directive = '\n@source not inline("' + " ".join(accepted) + '");\n'
    offset = start + len(_BLOCK_START)
    return html[:offset] + directive + html[offset:], diagnostics
