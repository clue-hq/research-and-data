"""Version-bound Tailwind preflight isolation, without changing cascade priority.

Core external renders enforce the runtime digest with SRI; inline previews verify
the actual bytes before replacing the default import.
Only selector subjects change: declarations, comments and source order remain exact.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import tinycss2

TAILWIND_VERSION = "4.3.3"
PREFLIGHT_SHA256 = "ace8310eed6dc5568a56fc16e1d695cf58da7528d81d66d81649e93cce644df6"
BROWSER_SHA256 = "a60c785630a06196808cbe79e6f7bdb4abcc8f4421a47b56f29338fc84805e3b"
BROWSER_SRI = "sha256-" + base64.b64encode(bytes.fromhex(BROWSER_SHA256)).decode("ascii")
MAX_PREFLIGHT_BYTES = 32 * 1024
MAX_SELECTORS = 128
MAX_RULES = 128
MAX_DEPTH = 4
_GUARD = ':not(:where([data-lumen-fragment="true"] *))'
_TRIVIA = {"comment", "whitespace"}


class PreflightError(ValueError):
    """The caller must retain original compiler input and report this limitation."""


def resource_path(name: str) -> Path:
    return Path(__file__).with_name("resources") / name


def preflight_source() -> str:
    """Read the unchanged, licensed upstream file; missing/drifted resources refuse."""
    try:
        raw = resource_path("tailwind-preflight-4.3.3.css").read_bytes()
        manifest = json.loads(resource_path("tailwind-preflight-4.3.3.json").read_text())
    except (OSError, ValueError) as exc:
        raise PreflightError("Pinned preflight resource or provenance is unreadable.") from exc
    if hashlib.sha256(raw).hexdigest() != PREFLIGHT_SHA256:
        raise PreflightError("Pinned preflight resource digest does not match.")
    if not isinstance(manifest, dict):
        raise PreflightError("Pinned preflight provenance must be an object.")
    if (
        manifest.get("version"),
        manifest.get("preflight_sha256"),
        manifest.get("browser_sha256"),
    ) != (
        TAILWIND_VERSION,
        PREFLIGHT_SHA256,
        BROWSER_SHA256,
    ):
        raise PreflightError("Pinned preflight provenance does not match this implementation.")
    return raw.decode("utf-8")


def supported_runtime(runtime: bytes) -> bool:
    """Exact bytes only; a URL, local package version or nearby file is not proof."""
    return hashlib.sha256(runtime).hexdigest() == BROWSER_SHA256


def qualify_preflight(css: str) -> str:
    """Insert a zero-specificity exclusion at every bounded preflight subject.

    Parser offsets locate edits in the original source. They are not obtained by
    serializing tokens, which can normalize string quotes or declaration bytes.
    Only the observed pinned grammar is supported: qualified declaration rules and
    conditional @supports groups; terminal double-colon pseudo-elements attach the
    guard to their originating element. Any unsupported construct refuses atomically.
    """
    try:
        size = len(css.encode("utf-8"))
    except UnicodeError as exc:
        raise PreflightError("Preflight source is not valid UTF-8.") from exc
    # tinycss2 normalizes these before calculating positions; refuse rather than
    # splice at an offset which might refer to a different original source byte.
    if size > MAX_PREFLIGHT_BYTES or any(c in css for c in ("\x00", "\r", "\f")):
        raise PreflightError("Preflight source exceeds bounds or uses unsupported line encoding.")
    if "</style" in css.lower():
        raise PreflightError("Preflight source contains an unsafe HTML style boundary.")
    lines = [0]
    lines.extend(i + 1 for i, char in enumerate(css) if char == "\n")
    edits: list[int] = []
    rule_count = 0

    def offset(token: Any) -> int:
        return lines[token.source_line - 1] + token.source_column - 1

    def validate_tokens(tokens: list[Any]) -> None:
        for token in tokens:
            if token.type == "error":
                raise PreflightError("Preflight CSS contains a parser error.")
            nested = getattr(token, "arguments", getattr(token, "content", None))
            if nested is not None:
                validate_tokens(nested)

    def subject(tokens: list[Any], end: int) -> None:
        while tokens and tokens[0].type in _TRIVIA:
            tokens = tokens[1:]
        while tokens and tokens[-1].type in _TRIVIA:
            end = offset(tokens[-1])
            tokens = tokens[:-1]
        if not tokens:
            raise PreflightError("Preflight selector list contains an empty branch.")
        validate_tokens(tokens)
        for i, token in enumerate(tokens):
            if token.type == "literal" and token.value in ("&", "{"):
                raise PreflightError("Nested or malformed preflight selectors are unsupported.")
            if token.type == "literal" and token.value == ":" and i + 1 < len(tokens):
                following = tokens[i + 1]
                if following.type == "literal" and following.value == ":":
                    tail = [t for t in tokens[i + 2 :] if t.type not in _TRIVIA]
                    if len(tail) != 1 or tail[0].type != "ident":
                        raise PreflightError("Only terminal simple pseudo-elements are supported.")
                    end = offset(token)
                    break
                if following.type == "ident" and following.value.lower() in {
                    "before",
                    "after",
                    "first-line",
                    "first-letter",
                }:
                    raise PreflightError("Legacy single-colon pseudo-elements are unsupported.")
        edits.append(end)
        if len(edits) > MAX_SELECTORS:
            raise PreflightError("Preflight selector count exceeds its bound.")

    def visit(rules: list[Any], depth: int = 0) -> None:
        nonlocal rule_count
        if depth > MAX_DEPTH:
            raise PreflightError("Preflight conditional nesting exceeds its bound.")
        for rule in rules:
            if rule.type in _TRIVIA:
                continue
            rule_count += 1
            if rule_count > MAX_RULES:
                raise PreflightError("Preflight rule count exceeds its bound.")
            if rule.type == "at-rule":
                if rule.lower_at_keyword != "supports" or rule.content is None:
                    raise PreflightError(
                        "Only conditional @supports preflight groups are supported."
                    )
                validate_tokens(rule.prelude)
                visit(tinycss2.parse_rule_list(rule.content), depth + 1)
                continue
            if rule.type != "qualified-rule" or not rule.content:
                raise PreflightError("Malformed or empty preflight rule is unsupported.")
            validate_tokens(rule.content)
            declarations = tinycss2.parse_declaration_list(rule.content)
            if any(d.type not in _TRIVIA | {"declaration"} for d in declarations):
                raise PreflightError("Nested or malformed preflight declarations are unsupported.")
            end = offset(rule.content[0]) - 1
            if css[end : end + 1] != "{":
                raise PreflightError("Preflight parser source positions are not canonical.")
            branch: list[Any] = []
            for token in rule.prelude:
                if token.type == "literal" and token.value == ",":
                    subject(branch, offset(token))
                    branch = []
                else:
                    branch.append(token)
            subject(branch, end)

    visit(tinycss2.parse_stylesheet(css))
    if not edits:
        raise PreflightError("Preflight contains no supported selectors.")
    for position in sorted(edits, reverse=True):
        css = css[:position] + _GUARD + css[position:]
    return css


def preflight_compiler_prefix() -> str:
    """Recreate the default import order in the same layers, with only guarded base."""
    filtered = qualify_preflight(preflight_source())
    return (
        "@layer theme, base, components, utilities;\n"
        # Nested imports resolve in the browser compiler but are ineligible for
        # the native HTML preload scanner, which scans even this inert style type.
        '@layer theme { @import "tailwindcss/theme.css"; }\n'
        "@layer base {\n" + filtered + "\n}\n"
        '@layer utilities { @import "tailwindcss/utilities.css"; }\n'
    )


def _warning(code: str, message: str) -> dict[str, Any]:
    return {
        "severity": "warning",
        "phase": "web",
        "code": code,
        "message": message,
        "subject": None,
        "hint": "Retain original rendering; this limitation prevents verified fragment fidelity.",
    }


def qualify_fragment_preflight(
    html: str,
    *,
    runtime_bytes: bytes | None = None,
    runtime_src: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Apply only to a resolved fragment, with runtime identity enforced at execution.

    External bytes are constrained by browser SRI on the exact engine-owned script.
    Inline callers supply the same bytes they will execute. Unsupported paths keep
    the entire original input; callers must treat warnings as unverified evidence.
    """
    import html as html_module
    import re

    from selectolax.lexbor import LexborHTMLParser

    from .editor_compiler import EditorCompilerError, editor_compiler_block

    if ' data-lumen-fragment="true"' not in html:
        return html, []
    try:
        if len(html) > 64 * 1024 * 1024:
            raise PreflightError("Rendered HTML exceeds the preflight input bound.")
        head_end = html.find("</head>")
        body_end = html.rfind("</body>")
        body_start = head_end + len("</head>")
        body = html[body_start : body_end + len("</body>")]
        if head_end < 0 or body_end < head_end or not body.lstrip().startswith("<body"):
            raise PreflightError("Canonical head/body boundary is missing.")
        if len(body.encode("utf-8")) > 16 * 1024 * 1024:
            raise PreflightError("Rendered body exceeds the preflight scan bound.")
        if not LexborHTMLParser(body).css('[data-lumen-fragment="true"]'):
            return html, []
        if (runtime_src is None) == (runtime_bytes is None):
            raise PreflightError("Exactly one runtime identity path is required.")
        if runtime_bytes is not None and not supported_runtime(runtime_bytes):
            return html, [
                _warning(
                    "fragment.editor_preflight_runtime_unsupported",
                    "Fragment preflight isolation was not applied: inline runtime bytes "
                    "do not match "
                    "the supported Tailwind browser 4.3.3 digest. "
                    "Original compiler input is retained.",
                )
            ]
        block = editor_compiler_block(html)
        prefix = preflight_compiler_prefix()
        content = html[block.content_start : block.content_end]
        installed = content.startswith(prefix)
        remainder = content[len(prefix) :] if installed else content

        # Renderer input consists of its own theme/directives. An additional import
        # could restore global preflight or change layer precedence; do not reinterpret it.
        def imports(tokens: list[Any]) -> bool:
            for token in tokens:
                if token.type == "at-keyword" and token.value.lower() == "import":
                    return True
                nested = getattr(token, "arguments", getattr(token, "content", None))
                if nested is not None and imports(nested):
                    return True
            return False

        if imports(tinycss2.parse_component_value_list(remainder)):
            raise PreflightError(
                "Existing compiler imports are unsupported for preflight isolation."
            )
        result = html
        if runtime_src is not None:
            match = re.match(
                r'\s*<script src="([^"]*)"([^>]*)></script>', html[block.element_end :]
            )
            if match is None or html_module.unescape(match.group(1)) != runtime_src:
                raise PreflightError(
                    "The external runtime is not the canonical engine-owned script."
                )
            expected = f' integrity="{BROWSER_SRI}" crossorigin="anonymous"'
            if match.group(2) not in ("", expected):
                raise PreflightError("The canonical runtime script has unsupported attributes.")
            if not match.group(2):
                position = block.element_end + match.end(1) + 1
                result = result[:position] + expected + result[position:]
        if not installed:
            result = result[: block.content_start] + prefix + result[block.content_start :]
        return result, []
    except (PreflightError, EditorCompilerError, UnicodeError) as exc:
        return html, [
            _warning(
                "fragment.editor_preflight_unsupported",
                "Fragment preflight isolation was not applied: " + str(exc),
            )
        ]
