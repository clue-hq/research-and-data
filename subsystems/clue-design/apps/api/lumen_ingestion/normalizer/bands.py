"""Recurring measured band backgrounds → `surface.band.*` color tokens.

`capture/geometry.py` measures every page band's background into
`BrandEvidence.geometry.background_sequence`, and `SectionBackground`'s own
docstring is right that the *sequence* is the finding — a rhythm, not a token.
But a color the page **stands on more than once** (Stripe's navy under two full
sections; a single statement band swallowing a fifth of the scroll) is a brand
surface by any honest reading, and until this module existed it reached the kit
under no name at all. The brief agent could then only approximate it, and every
generated page inherited the approximation.

So: the rhythm stays the rhythm, and the recurring *members* of it earn names.
Nothing here invents a color — every value is a hex read off the brand's own
rendered page, which is why these tokens carry `MEASURED_CONFIDENCE` and a
`website:` pointer rather than the 0.9 an atomic swatch gets.

Three rules keep the mint honest, and each one is a refusal:

* a band whose background is a gradient, an image, or TRANSLUCENT is not a
  flat opaque surface, so it names nothing — its hex is not what the page
  shows. The translucent case is the sneaky one: the capture only discards a
  *fully* transparent background, so a band painted `rgba(20, 40, 120, 0.04)`
  arrives as `#1428780A`, and nothing downstream reads that alpha byte — it
  would be minted as a near-black statement surface when the page renders it
  as barely-tinted white, and the alpha would ride into the web theme;
* a group already within merge distance of a color the kit carries names
  nothing — Stripe's five white bands are `surface.page`/`text.inverse` doing
  their job, not five new tokens;
* a group that neither recurs nor commands real height names nothing (a 380px
  footer tint is a footer tint).

Clustering follows `cluster.py`'s idiom: accumulate while the running mean
stays inside the same 0.03 OKLab merge distance, keep an OBSERVED hex as the
representative (never a drifted mean), order deterministically. The one
deviation is that the running mean here is unweighted: a band's weight is its
height, heights can legitimately be 0 in a degenerate harvest, and height is
already doing the load-bearing work of picking the representative and clearing
the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..colorspace import hex_alpha, hex_to_oklab, oklab_distance, relative_luminance
from ..evidence import SectionBackground
from .cluster import MERGE_DISTANCE

# `MERGE_DISTANCE` is `cluster.py`'s — two bands a human would call "the same
# navy" must not become two tokens, and the dedupe below is only correct while
# bands and evidence colors agree on what "the same color" means.
#
# A single band this share of the measured scroll is a statement surface, not a
# one-off: one huge band still earns a name without needing to repeat.
HEIGHT_SHARE = 0.20
# …otherwise the color has to actually recur.
MIN_BANDS = 2
# Relative luminance below this reads as a dark statement band; above it, a tint.
DARK_LUMINANCE = 0.5


@dataclass(frozen=True)
class BandSurface:
    """One minted band token: where it goes, what it is, and what measured it."""

    path: str
    hex: str
    provenance: str
    description: str


@dataclass
class _Group:
    members: list[SectionBackground]
    lab_sum: tuple[float, float, float]

    @property
    def mean(self) -> tuple[float, float, float]:
        n = float(len(self.members))
        return (self.lab_sum[0] / n, self.lab_sum[1] / n, self.lab_sum[2] / n)

    @property
    def height(self) -> float:
        return sum(_height(band) for band in self.members)

    @property
    def representative(self) -> SectionBackground:
        # Tallest wins; ties break on the earliest section, so the same harvest
        # always names the same hex.
        return min(self.members, key=lambda b: (-_height(b), b.index))


def build_band_surfaces(
    sequence: list[SectionBackground], kit_colors: list[str]
) -> list[BandSurface]:
    """The `surface.band.*` tokens this background sequence honestly supports.

    `kit_colors` is every color value already emitted on the kit (the semantic
    set, the ramps, the extras); a band group that matches one of them is that
    token, and minting a second name for it would split the vocabulary.

    Returns `[]` for evidence with no measured sequence. A brand whose every
    section sits on one canvas has no band language, and that IS the finding.
    """
    usable = [
        band
        for band in sequence
        if band.background
        and not band.gradient
        and not band.has_image
        # Opaque only. A translucent band's stored hex describes the paint, not
        # the pixels — and every reader downstream (OKLab, luminance, the web
        # theme) ignores the alpha byte, so minting it would be a lie twice
        # over. The band still shows in the rhythm; it just names nothing.
        and hex_alpha(band.background) >= 1.0
    ]
    if not usable:
        return []

    total_height = sum(_height(band) for band in usable)
    kit_labs = [hex_to_oklab(value) for value in kit_colors if value]

    minted: list[_Group] = []
    for group in _group(usable):
        rep_lab = hex_to_oklab(group.representative.background or "")
        if any(oklab_distance(rep_lab, lab) <= MERGE_DISTANCE for lab in kit_labs):
            continue
        recurs = len(group.members) >= MIN_BANDS
        commands = total_height > 0 and group.height >= HEIGHT_SHARE * total_height
        if recurs or commands:
            minted.append(group)

    # Deterministic emission order: the biggest presence on the page first.
    minted.sort(key=lambda g: (-g.height, min(b.index for b in g.members)))

    seen: dict[str, int] = {}
    surfaces: list[BandSurface] = []
    for group in minted:
        band = group.representative
        hex_value = band.background or ""
        kind = "statement" if relative_luminance(hex_value) < DARK_LUMINANCE else "tint"
        rank = seen.get(kind, 0) + 1
        seen[kind] = rank
        suffix = "" if rank == 1 else f"-{rank}"
        indices = sorted(member.index for member in group.members)
        surfaces.append(
            BandSurface(
                path=f"surface.band.{kind}{suffix}",
                hex=hex_value,
                provenance=(
                    f"{band.pointer.source}:{_page(band)} :: recurring band "
                    f"background (sections {', '.join(str(i) for i in indices)})"
                ),
                description=(
                    "recurring page band background "
                    f"({len(group.members)} {'band' if len(group.members) == 1 else 'bands'}"
                    f", {int(group.height)}px)"
                ),
            )
        )
    return surfaces


def _group(bands: list[SectionBackground]) -> list[_Group]:
    groups: list[_Group] = []
    for band in bands:
        lab = hex_to_oklab(band.background or "")
        for group in groups:
            if oklab_distance(group.mean, lab) <= MERGE_DISTANCE:
                group.members.append(band)
                group.lab_sum = (
                    group.lab_sum[0] + lab[0],
                    group.lab_sum[1] + lab[1],
                    group.lab_sum[2] + lab[2],
                )
                break
        else:
            groups.append(_Group(members=[band], lab_sum=lab))
    return groups


def _height(band: SectionBackground) -> float:
    return max(0.0, band.height_px)


def _page(band: SectionBackground) -> str:
    """The page URL out of the band's `<url> :: section N (tag)` locator."""
    return band.pointer.locator.split(" :: ", 1)[0]
