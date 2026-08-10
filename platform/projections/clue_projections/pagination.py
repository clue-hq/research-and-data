"""One opaque keyset cursor for every paginated projection (FI Lane D D0).

Keyset, not OFFSET: a chat transcript grows while it is being read, so an offset page silently
repeats or skips rows. Every paginated reader here orders by a **total** key (a timestamp plus the
row id, or a per-thread sequence) and pages with a row-value comparison against that key, so two
rows written in the same transaction still page deterministically.

The cursor is **opaque by contract** — callers pass back what they were given and never parse it.
Decoding fails loudly (:class:`InvalidCursorError`) rather than falling back to "start from the
beginning": a silently-ignored cursor makes a paging client re-serve page 1 forever, which looks
exactly like data loss.

The encoding intentionally matches the shape `frontend_read/accounts_list.py` already ships
(url-safe base64 over a separator-joined position) so the surface has one cursor idiom, but the
implementation is local — that package is another lane's territory.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence

__all__ = ["InvalidCursorError", "decode_cursor", "encode_cursor"]

_SEPARATOR = "|"


class InvalidCursorError(ValueError):
    """A cursor value this projection did not mint (or that has been tampered with)."""


def encode_cursor(*parts: str) -> str:
    """Encode a keyset position. At least one part; no part may contain the separator."""

    if not parts:
        raise ValueError("a cursor needs at least one position component")
    if any(_SEPARATOR in part for part in parts):
        raise ValueError("cursor components must not contain the separator")
    raw = _SEPARATOR.join(parts)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, *, parts: int) -> Sequence[str]:
    """Decode a cursor into exactly ``parts`` components, or raise :class:`InvalidCursorError`."""

    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursorError("cursor is not a value this endpoint issued") from exc
    decoded = raw.split(_SEPARATOR)
    if len(decoded) != parts or any(not item for item in decoded):
        raise InvalidCursorError("cursor is not a value this endpoint issued")
    return decoded
