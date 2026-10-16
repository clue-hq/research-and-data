"""Measured section backgrounds → `surface.band.<hex>` colour tokens (rewritten, Wave 2 A9).

`capture/geometry.py` measures every page band's background into
`BrandEvidence.geometry.background_sequence`, and the text colour on it (`ink`). Every flat, opaque
band colour is a surface the seller's page stands on, so it reaches the kit as a surface token — and
through it, site-kit's extra surfaces and the agent's surfaces table (founder, 2026-10-12).

Rules, each a refusal or an exact match:

* a band whose background is a gradient, an image, or translucent names nothing: its hex is not
  what the page shows (a band painted `rgba(20, 40, 120, 0.04)` reads as barely-tinted white but
  arrives as `#1428780A`);
* a band colour an existing `surface.*` token holds EXACTLY is that token, alpha included (a
  translucent `#F5F5F580` does not hold a flat `#F5F5F5`). Surface tokens only: a band named after
  an ink role (`text.inverse`) would teach the wrong vocabulary (the grammar audit's rule,
  `grammar_audit._surface_token`); near misses are minted, never merged (no tolerance);
* the name is the colour (`surface.band.014036`), so a band order that shifts between extractions
  never renames a surface and the same site always yields the same names;
* at most `MAX_BAND_SURFACES`, the most present first: each one adds a row to the agent's surfaces
  table and an option to the marketer's Surface field.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..colorspace import contrast_ratio, hex_alpha
from ..evidence import SectionBackground

MAX_BAND_SURFACES = 12
#: Relative luminance below this reads as a dark band. No longer part of a band's name; the grammar
#: audit's dark/light band reading (`grammar_audit`) still uses it.
DARK_LUMINANCE = 0.5


@dataclass(frozen=True)
class BandSurface:
    """One minted band token: where it goes, what it is, what measured it, the text on it."""

    path: str
    hex: str
    provenance: str
    description: str
    ink_hex: str | None


def band_path(hex_value: str) -> str:
    return f"surface.band.{hex_value[1:7].lower()}"


def opaque_hex(value: str) -> str | None:
    """`#RRGGBB` of an opaque hex colour (`#RRGGBB`, or `#RRGGBBFF`); None for a translucent one."""
    text = value.upper()
    if len(text) == 7 or (len(text) == 9 and text.endswith("FF")):
        return text[:7]
    return None


def build_band_surfaces(
    sequence: list[SectionBackground], surface_colors: dict[str, str]
) -> tuple[list[BandSurface], int]:
    """The band surfaces this background sequence supports, and how many the cap left out.

    `surface_colors` maps the kit's `surface.*` tokens to their hex.
    """
    usable = [
        band for band in sequence
        if band.background and not band.gradient and not band.has_image and hex_alpha(band.background) >= 1.0
    ]
    taken = {opaque for value in surface_colors.values() if value and (opaque := opaque_hex(value))}
    by_hex: dict[str, list[SectionBackground]] = {}
    for band in usable:
        by_hex.setdefault((band.background or "")[:7].upper(), []).append(band)
    ordered = sorted(
        ((hex_value, members) for hex_value, members in by_hex.items() if hex_value not in taken),
        key=lambda item: (-sum(_height(b) for b in item[1]), min(b.index for b in item[1])),
    )
    surfaces: list[BandSurface] = []
    for hex_value, members in ordered[:MAX_BAND_SURFACES]:
        tallest_first = sorted(members, key=lambda b: (-_height(b), b.index))
        representative = tallest_first[0]
        indices = ", ".join(str(i) for i in sorted(b.index for b in members))
        inks = [b.ink for b in tallest_first if b.ink and hex_alpha(b.ink) >= 1.0]
        count = len(members)
        surfaces.append(BandSurface(
            path=band_path(hex_value),
            hex=hex_value,
            provenance=f"{representative.pointer.source}:{_page(representative)} :: section background (sections {indices})",
            description=f"section background ({count} {'band' if count == 1 else 'bands'}, {int(sum(_height(b) for b in members))}px)",
            ink_hex=inks[0][:7].upper() if inks else None,
        ))
    return surfaces, max(0, len(ordered) - MAX_BAND_SURFACES)


def _height(band: SectionBackground) -> float:
    return max(0.0, band.height_px)


def _page(band: SectionBackground) -> str:
    """The page URL out of the band's `<url> :: section N (tag)` locator."""
    return band.pointer.locator.split(" :: ", 1)[0]


#: A band's text must read on it (WCAG 1.4.3), the normalizer's `_CONTRAST_MIN`.
READABLE_RATIO = 4.5


def readable_ink(band: BandSurface, candidates: list[str]) -> tuple[str, bool]:
    """The text colour to store for a band, and whether it is the one measured there (S6-1, D4).

    The measured colour when it reads on the band (4.5:1). Otherwise the brand's own text colour
    wins whenever it reads: the best-reading of `candidates` (the kit's text.primary and
    text.inverse) that reaches 4.5:1. Only when none does, black (#0B0F14) or white, whichever reads
    better. `band.ink_hex` must be set."""
    measured = str(band.ink_hex)
    if contrast_ratio(measured, band.hex) >= READABLE_RATIO:
        return measured, True
    readable = [c[:7].upper() for c in candidates if c and contrast_ratio(c[:7], band.hex) >= READABLE_RATIO]
    options = readable or ["#FFFFFF", "#0B0F14"]
    best = max(options, key=lambda option: contrast_ratio(option, band.hex))
    return best, False
