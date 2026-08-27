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

Answering ``None`` is the honest, common case — no screenshot, no measured geometry, an
undecodable preview — and it means exactly "no evidence", never "fine".
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


def detect_dead_height(
    preview: bytes | None, *, section_height_px: float | None, basis: str | None
) -> DeadHeight | None:
    """Is this section mostly artificial scroll height? ``None`` when nothing says.

    ``preview`` is the PNG minting already cropped for the fragment's thumbnail, so this costs
    one decode and one pass over its rows — no second screenshot, and no second crop that could
    disagree with the one a human will see in the picker.
    """
    if not preview or basis != DEAD_HEIGHT_JUDGED_BASIS:
        return None
    if section_height_px is None or section_height_px < DEAD_HEIGHT_MIN_SECTION_PX:
        return None

    measured = _content_extent(preview)
    if measured is None:
        return None
    rows, content_rows = measured
    if rows <= 0:
        return None

    fraction = content_rows / rows
    if fraction > DEAD_HEIGHT_MAX_CONTENT_FRACTION:
        return None
    return DeadHeight(
        reason=DEAD_HEIGHT_REASON,
        section_height_px=float(section_height_px),
        content_fraction=fraction,
        preview_rows=rows,
        content_rows=content_rows,
    )


def _content_extent(preview: bytes) -> tuple[int, int] | None:
    """``(total rows, rows from the first showing something to the last)``, or ``None``.

    A wholly featureless crop answers ``(rows, 0)`` rather than ``None``: "there is nothing in
    this band" is a finding, and the loudest one this module can make. ``None`` is reserved for
    "the image would not open", which is not a finding about the page.
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
        return height, 0
    return height, last - first + 1


def _buffer(data: bytes):
    from io import BytesIO

    return BytesIO(data)


__all__ = [
    "DEAD_HEIGHT_JUDGED_BASIS",
    "DEAD_HEIGHT_MAX_CONTENT_FRACTION",
    "DEAD_HEIGHT_MIN_SECTION_PX",
    "DEAD_HEIGHT_REASON",
    "DEAD_HEIGHT_ROW_VARIATION",
    "DeadHeight",
    "detect_dead_height",
]
