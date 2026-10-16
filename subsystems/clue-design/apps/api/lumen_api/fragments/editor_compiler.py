"""Locate the renderer-owned compiler style without parsing large artifact CSS."""

from __future__ import annotations

from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser

MAX_COMPILER_PREFIX_BYTES = 64 * 1024
_BLOCK_START = '<style type="text/tailwindcss">'


class EditorCompilerError(ValueError):
    def __init__(self, message: str, *, kind: str = "block") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class EditorCompilerBlock:
    content_start: int
    content_end: int
    element_end: int


def editor_compiler_block(html: str) -> EditorCompilerBlock:
    """Require one exact, direct head style; return byte-preserving string offsets."""
    head_end = html.find("</head>")
    start = html.find(_BLOCK_START)
    content_start = start + len(_BLOCK_START)
    end = html.find("</style>", content_start)
    if html.count(_BLOCK_START) != 1 or not (0 <= start < end < head_end):
        raise EditorCompilerError("the canonical Tailwind head block is missing or ambiguous.")
    element_end = end + len("</style>")
    prefix = html[:element_end]
    if len(prefix) > MAX_COMPILER_PREFIX_BYTES or len(prefix.encode()) > MAX_COMPILER_PREFIX_BYTES:
        raise EditorCompilerError("the compiler head prefix exceeds its bound.", kind="limited")
    tree = LexborHTMLParser(prefix + "</head><body></body></html>")
    blocks = tree.css('head > style[type="text/tailwindcss"]')
    if len(blocks) != 1 or blocks[0].text() != html[content_start:end]:
        raise EditorCompilerError("the Tailwind block is not canonical head content.")
    return EditorCompilerBlock(content_start, end, element_end)
