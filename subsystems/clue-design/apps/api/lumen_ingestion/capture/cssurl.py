"""How this package reads a CSS ``url()`` — one regex, one unescape, three callers.

Why this module exists (F0 fix wave)
------------------------------------
The ``url()`` regex lived in three independent copies — ``candidates._CSS_URL_RE`` (the
collector's asset enumeration), ``imgsrc._CSS_URL_RE`` (the shared ``background-image``
reader) and an ad-hoc one inside ``parse._parse_font_face`` — and all three read the token
wrong in the same way: the unquoted branch was ``[^)'"\\s]+``, which stops dead at the
backslash of an escaped ``\\)`` and never unescapes ``\\(``/``\\)`` either.

That is not a hypothetical. Webflow escapes the parentheses a Designer-uploaded filename
carries, so the insighthealth.ai hero declares

    .aura-bg{background-image:url(https://cdn.…/…_Ellipse%202%20\\(1\\).png), …}

and the acceptance walk enumerated ``…_Ellipse%202%20\\(1\\`` — a URL the CDN answered 403
to. Two real hero background assets were lost behind a loud-but-wrong ``LUMI0503``. On the
font path the same defect is worse than a lost image: the evidence builder matches a face to
its bytes by EXACT URL string, so a mangled ``@font-face`` src costs the face its
``asset_id`` and every render falls back to Inter.

One reading, in one place, so the three cannot drift again. Deliberately NOT in scope: the
``@import`` regex in ``static.py`` (a stylesheet URL, not an asset reference) and
``logo_ladder``'s own background reader, both of which are their own owners' business.
"""

from __future__ import annotations

import re
from typing import Iterator

#: Every ``url()`` token, escape-aware in all three branches.
#:
#: The unquoted branch consumes ``\\<char>`` as one unit so an escaped ``)`` cannot end the
#: token, and the two quoted branches do the same so an escaped quote cannot end the string.
#: ``IGNORECASE`` because CSS keywords are case-insensitive and ``URL(…)`` is legal — both
#: previous copies were case-sensitive while the cheap ``"url(" in text.lower()`` guard in
#: front of them was not, so an uppercase declaration passed the guard and matched nothing.
CSS_URL_RE = re.compile(
    r"url\(\s*(?:"
    r"'((?:\\[\s\S]|[^'\\])*)'"
    r'|"((?:\\[\s\S]|[^"\\])*)"'
    r"|((?:\\[\s\S]|[^\\)'\"\s])+)"
    r")\s*\)",
    re.IGNORECASE,
)

#: A CSS escape: ``\<1-6 hex digits><optional single whitespace>`` or ``\<any one char>``.
_CSS_ESCAPE_RE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \n\r\t\f]?|(\r\n|[\s\S]))")

#: What an out-of-range codepoint escape becomes, per the CSS Syntax spec (U+FFFD).
_REPLACEMENT = "�"


def unescape_css(raw: str) -> str:
    """A CSS token's escapes resolved to the characters they stand for.

    ``\\(`` → ``(``, ``\\26 `` → ``&``, and a backslash-newline (a string line continuation)
    → nothing. Anything with no backslash in it is returned untouched, which is every URL on
    a normal page.
    """
    if "\\" not in raw:
        return raw
    return _CSS_ESCAPE_RE.sub(_unescape_one, raw)


def _unescape_one(match: re.Match) -> str:
    hex_digits, literal = match.group(1), match.group(2)
    if hex_digits is not None:
        code = int(hex_digits, 16)
        if code == 0 or code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            return _REPLACEMENT
        return chr(code)
    if literal in ("\n", "\r", "\f", "\r\n"):
        # A line continuation inside a string stands for nothing at all.
        return ""
    return literal


def iter_css_urls(css_text: str) -> Iterator[str]:
    """Every ``url()`` reference in some CSS, unescaped, in source order.

    Yields the token exactly as the author wrote it minus its escapes — NOT absolutized and
    NOT filtered. Resolving against a base and deciding what to do with ``data:``/fragment
    references is each caller's own policy and stays there.
    """
    if "url(" not in css_text.lower():
        return
    for match in CSS_URL_RE.finditer(css_text):
        raw = match.group(1) or match.group(2) or match.group(3) or ""
        token = unescape_css(raw).strip()
        if token:
            yield token
