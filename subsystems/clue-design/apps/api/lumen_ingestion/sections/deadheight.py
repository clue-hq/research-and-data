"""Dead scroll height: a captured band far taller than anything visible in it (F3.0, D-F6).

Founder ruling D-F6 makes brokenness a thing the pipeline must NOTICE, not just something a
human eventually complains about: *"Never preserve a broken result merely because it came from
the original site."* The commonest way a cloned section is broken is the Ploy case — a scroll-
jacked band whose height is `400vh` because JavaScript was going to animate through it, cloned
into a page where that JavaScript does not exist. What the visitor gets is a screenful of
content followed by three screens of nothing, and nothing in the artifact says so.

**What is measured, and what is not.** Nothing here re-renders anything or asks a model
anything. Two facts the capture already produced meet:

* the band's height in CSS pixels, which the browser measured (``sections/bands.py``);
* the section's own crop of F0's full-page screenshot, which minting already produces for the
  fragment's preview.

A row of that crop is CONTENT when its pixels vary across the width — text, an image, a control,
a border. A row of flat colour is not, and neither is a row of a vertical gradient, because a
gradient varies DOWN the page and not across it. That distinction is the whole detector, and it
is what makes a full-bleed photographic background (which varies everywhere) correctly not dead,
while a 3000px expanse of brand navy correctly is.

The visible content is then the EXTENT from the first content row to the last, rather than a
count of them. A count would call an ordinary hero — big headline, sub-head, button, generous
padding — mostly empty, because most of an ordinary hero's rows genuinely are background. The
extent asks the question D-F6 actually asks: how much of this band's scroll cost has anything in
it at all.

**Two conditions, and both are floors against false positives.** The band must be taller than
:data:`DEAD_HEIGHT_MIN_SECTION_PX` (a thin divider or a flat colour strip is not artificial
scroll height, it is a design), and its content extent must be at most
:data:`DEAD_HEIGHT_MAX_CONTENT_FRACTION` of it. A section we only INFERRED a crop for (a nav or
footer, whose extent is derived from its neighbours' bands) is never judged: those pixels may
belong to another section, and judging a section on somebody else's picture is worse than not
judging it.

**Abstaining is a first-class answer, and it is not the same answer as "fine".** No screenshot,
a crop we only inferred, an unknown viewport, a crop the screenshot cut short, an undecodable
image — in every one of those the module has NO EVIDENCE, and it says so
(:attr:`DeadHeightAssessment.judged` is ``False``) rather than reporting a clean bill. That
distinction is load-bearing one caller up: a re-mint that converges onto an existing row may
CLEAR a degraded marker only on a pass that actually looked, because honest absence must never
be mistaken for a repair.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The machine-readable ``degraded_reason`` this detector writes. The repair ladder (F3.1) reads
#: it to know which rung to start on; it is a code, not a sentence, and the numbers behind it ride
#: in the fragment's provenance.
DEAD_HEIGHT_REASON = "dead_height"

#: A band shorter than this is never dead height, however empty it looks. Roughly two desktop
#: viewports: the ruling is about SCROLL COST (the reader dragging through nothing), and a band a
#: reader passes in one screen costs none. Real content sections stack well past this, which is
#: why the fraction below does the discriminating and this only sets the floor.
DEAD_HEIGHT_MIN_SECTION_PX = 1600.0

#: How much of a band's height its visible content may span before the band stops being mostly
#: nothing. At 0.35 the band is nearly three times its own content — "vastly exceeding", stated
#: as a number. An ordinary tall hero lands around 0.5–0.7 (padding above and below the copy);
#: the Ploy-class scroll-jack lands under 0.25.
DEAD_HEIGHT_MAX_CONTENT_FRACTION = 0.35

#: How much a row must vary across its width, in 8-bit grey levels, to count as showing
#: something. Small, because anti-aliased body text against its background is a low-contrast
#: signal and missing it would call a page of prose empty; comfortably above the ±1–2 levels PNG
#: re-encoding and a LANCZOS downscale of a flat region can introduce.
DEAD_HEIGHT_ROW_VARIATION = 12

#: Only a crop the section's OWN measured band produced may be judged. ``crop_extent``'s other
#: two answers are inferred from neighbours (a nav above the first band, a footer below the
#: last), and an estimated basis reconstructs tops by summing heights, so the pixels under an
#: estimated extent may be a different part of the page entirely.
DEAD_HEIGHT_JUDGED_BASIS = "measured"

#: How much of the band the crop must actually SHOW before the crop may speak for the band.
#:
#: The two halves of the measurement come from different places — the floor is the band's height
#: in CSS pixels, the fraction is counted over the crop's rows — so they have to be talking about
#: the same stretch of page. ``crop_preview`` clamps its bottom to the screenshot's height, so
#: the last section of a very long page can be cropped short: a 4000px band whose screenshot ends
#: 900px in yields a 900px slice, and if that slice happens to be the section's top padding the
#: fraction of the SLICE is tiny while the band itself is full of content below the cut. Born
#: ``degraded``, and F3.1 spends a repair run replacing a section that was never broken.
#:
#: So a crop that does not substantially cover its band does not get to judge it. 0.9 rather than
#: 1.0 because rounding between CSS pixels and device pixels legitimately costs a row or two.
DEAD_HEIGHT_MIN_CROP_COVERAGE = 0.9


@dataclass(frozen=True)
class DeadHeight:
    """One section's dead-height finding, with the numbers that produced it."""

    reason: str
    section_height_px: float
    content_fraction: float
    preview_rows: int
    content_rows: int

    def as_provenance(self) -> dict[str, object]:
        """The bounded shape the fragment row records — a handful of numbers, no pixels."""
        return {
            "reason": self.reason,
            "detector": "dead_height@1",
            "section_height_px": self.section_height_px,
            "content_fraction": round(self.content_fraction, 4),
            "preview_rows": self.preview_rows,
            "content_rows": self.content_rows,
            "max_content_fraction": DEAD_HEIGHT_MAX_CONTENT_FRACTION,
            "min_section_px": DEAD_HEIGHT_MIN_SECTION_PX,
        }


@dataclass(frozen=True)
class DeadHeightAssessment:
    """What one look at a section concluded — including "I could not look".

    ``judged`` is the distinction that matters, and it is NOT ``finding is not None``. A section
    whose band is 400px tall was genuinely looked at and genuinely is not dead height
    (``judged=True, finding=None``); a section with no screenshot was not looked at at all
    (``judged=False, finding=None``). Only the first is a clean bill.
    """

    judged: bool
    finding: DeadHeight | None = None
    #: Why this section was not judged, when it was not. A short code for the diagnostics.
    abstained_because: str | None = None


def assess_dead_height(
    preview: bytes | None,
    *,
    section_height_px: float | None,
    basis: str | None,
    viewport_width: int | None,
) -> DeadHeightAssessment:
    """Look at one section, and be honest about whether looking was possible.

    ``preview`` is the PNG minting already cropped for the fragment's thumbnail, so this costs
    one decode and one pass over its rows — no second screenshot, and no second crop that could
    disagree with the one a human will see in the picker.

    ``viewport_width`` is what turns the crop's ROWS back into CSS pixels, so the coverage guard
    can check that this crop is really showing this band (see
    :data:`DEAD_HEIGHT_MIN_CROP_COVERAGE`). Without it the two halves of the measurement are in
    different units and the module refuses to guess at the conversion.
    """
    if not preview:
        return DeadHeightAssessment(judged=False, abstained_because="no_preview")
    if basis != DEAD_HEIGHT_JUDGED_BASIS:
        return DeadHeightAssessment(judged=False, abstained_because="crop_not_measured")
    if section_height_px is None:
        return DeadHeightAssessment(judged=False, abstained_because="no_geometry")
    if not viewport_width or viewport_width <= 0:
        return DeadHeightAssessment(judged=False, abstained_because="viewport_unknown")

    measured = _content_extent(preview)
    if measured is None:
        return DeadHeightAssessment(judged=False, abstained_because="preview_unreadable")
    rows, width, content_rows = measured
    if rows <= 0 or width <= 0:
        return DeadHeightAssessment(judged=False, abstained_because="preview_unreadable")

    # The crop is the full page width downscaled to at most MAX_PREVIEW_WIDTH, so one preview row
    # is `viewport_width / preview_width` CSS pixels tall.
    covered_px = rows * (viewport_width / width)
    if covered_px < section_height_px * DEAD_HEIGHT_MIN_CROP_COVERAGE:
        return DeadHeightAssessment(judged=False, abstained_because="crop_clipped")

    # Looked at, and short. A judgement, not an abstention: the band is not scroll cost.
    if section_height_px < DEAD_HEIGHT_MIN_SECTION_PX:
        return DeadHeightAssessment(judged=True)

    fraction = content_rows / rows
    if fraction > DEAD_HEIGHT_MAX_CONTENT_FRACTION:
        return DeadHeightAssessment(judged=True)
    return DeadHeightAssessment(
        judged=True,
        finding=DeadHeight(
            reason=DEAD_HEIGHT_REASON,
            section_height_px=float(section_height_px),
            content_fraction=fraction,
            preview_rows=rows,
            content_rows=content_rows,
        ),
    )


def detect_dead_height(
    preview: bytes | None,
    *,
    section_height_px: float | None,
    basis: str | None,
    viewport_width: int | None,
) -> DeadHeight | None:
    """The finding alone, for a caller that does not need to know whether looking was possible."""
    return assess_dead_height(
        preview,
        section_height_px=section_height_px,
        basis=basis,
        viewport_width=viewport_width,
    ).finding


def _content_extent(preview: bytes) -> tuple[int, int, int] | None:
    """``(rows, width, rows from the first showing something to the last)``, or ``None``.

    A wholly featureless crop answers ``…, 0`` rather than ``None``: "there is nothing in this
    band" is a finding, and the loudest one this module can make. ``None`` is reserved for "the
    image would not open", which is not a finding about the page.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(_buffer(preview)) as opened:
            grey = opened.convert("L")
            width, height = grey.size
            data = grey.tobytes()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    first: int | None = None
    last: int | None = None
    for y in range(height):
        row = data[y * width : (y + 1) * width]
        if max(row) - min(row) >= DEAD_HEIGHT_ROW_VARIATION:
            if first is None:
                first = y
            last = y
    if first is None or last is None:
        return height, width, 0
    return height, width, last - first + 1


def _buffer(data: bytes):
    from io import BytesIO

    return BytesIO(data)


__all__ = [
    "DEAD_HEIGHT_JUDGED_BASIS",
    "DEAD_HEIGHT_MAX_CONTENT_FRACTION",
    "DEAD_HEIGHT_MIN_CROP_COVERAGE",
    "DEAD_HEIGHT_MIN_SECTION_PX",
    "DEAD_HEIGHT_REASON",
    "DEAD_HEIGHT_ROW_VARIATION",
    "DeadHeight",
    "DeadHeightAssessment",
    "assess_dead_height",
    "detect_dead_height",
]
