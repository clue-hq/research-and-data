"""The 2x2 logo-family vocabulary shared by the vendor rung, the ladder mapping,
the dispatch, and the cache (founder ruling 2026-09-02).

Two axes, four cells. THEME uses OUR semantics -- the background the asset is
FOR: `light` means "place on light backgrounds" (dark-colored art), `dark`
means "place on dark backgrounds" (light/white art). COMPLETENESS is `lockup`
(the full horizontal logo; a wordmark-only brand still fills this cell) or
`mark` (the bare symbol). This is deliberately the same 2x2 the deferred
batch-time slot-selection rule will consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

THEMES = ("light", "dark")
COMPLETENESS = ("lockup", "mark")
CELL_NAMES = ("light_lockup", "dark_lockup", "light_mark", "dark_mark")

#: `FamilyCell.source` values. "ladder-materialized" is the ladder's
#: observed-ink currentColor export (never synthesis -- see logo_ladder).
SOURCE_BRANDFETCH = "brandfetch"
SOURCE_LOGO_DEV = "logo_dev"
SOURCE_LADDER = "ladder"
SOURCE_LADDER_MATERIALIZED = "ladder-materialized"


def cell_name(theme: str, completeness: str) -> str:
    """`("light", "lockup") -> "light_lockup"`. Refuses unknown axis values loudly."""
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (expected one of {THEMES})")
    if completeness not in COMPLETENESS:
        raise ValueError(
            f"unknown completeness {completeness!r} (expected one of {COMPLETENESS})"
        )
    return f"{theme}_{completeness}"


@dataclass
class FamilyCell:
    """One resolved cell of the 2x2: real bytes plus where they came from."""

    cell: str
    body: bytes
    content_type: str
    source: str  # SOURCE_BRANDFETCH | SOURCE_LADDER | SOURCE_LADDER_MATERIALIZED
    origin_url: str
    evidence: dict = field(default_factory=dict)
