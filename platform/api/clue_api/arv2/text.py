"""Verbatim-matching primitives, ported from the proof-of-concept's ``z4e_quote_verify.py``.

Appendix A law 6: verbatim-quote checking is an **annotation** on a claim, never a blocker, and
v1 ships with it off. These two functions are what that annotation is computed from, so they live
once, here, rather than inside each client that quotes a source.

The normalisation is a deliberate, faithful port: the same NFKC fold, the same quote
straightening, the same "collapse whitespace, lower-case, then blank out everything outside
``[a-z0-9 ]``" order as the proof-of-concept. Keeping it identical is what lets a verdict computed
here be compared against a verdict the PoC recorded.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

MatchVerdict = Literal["EXACT", "PARTIAL", "NOT_FOUND"]

_WHITESPACE = re.compile(r"\s+")
_NON_MATCHABLE = re.compile(r"[^a-z0-9 ]+")


def normalize_for_match(s: str | None) -> str:
    """Fold a string down to what a verbatim comparison should actually be sensitive to.

    NFKC (so a full-width or composed character equals its plain form), curly single/double quotes
    straightened, runs of whitespace collapsed to one space, lower-cased, then every character
    outside ``[a-z0-9 ]`` replaced by a space. Punctuation differences therefore cannot make a
    genuinely verbatim quote look invented.
    """
    folded = (
        unicodedata.normalize("NFKC", s or "")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    collapsed = _WHITESPACE.sub(" ", folded).strip().lower()
    return _NON_MATCHABLE.sub(" ", collapsed).strip()


def substring_verdict(
    needle: str,
    haystack: str,
    *,
    window: int = 40,
    stride: int = 10,
) -> MatchVerdict:
    """Is ``needle`` really present in ``haystack``? EXACT / PARTIAL / NOT_FOUND.

    EXACT when the normalised needle is a substring of the normalised haystack. PARTIAL when any
    ``window``-character slice of the needle, taken every ``stride`` characters, is — the case
    where a model dropped or added a word inside an otherwise real quote. NOT_FOUND otherwise,
    which is the honest answer for a fabricated quote.
    """
    normalized_needle = normalize_for_match(needle)
    normalized_haystack = normalize_for_match(haystack)
    if not normalized_needle:
        return "NOT_FOUND"
    if normalized_needle in normalized_haystack:
        return "EXACT"
    for start in range(0, max(1, len(normalized_needle) - window), stride):
        if normalized_needle[start : start + window] in normalized_haystack:
            return "PARTIAL"
    return "NOT_FOUND"
