"""Our page against F0's reference capture — measured, explainable, and nothing more (F3.3).

The gate compares the full-page screenshot the behavioural walk took against the full-page
screenshot ``design_site_snapshot`` kept of the client's real page (F0.1). There is no model in
this file and no similarity score pretending to be a judgement: it reports **dimensions,
presence and region differences**, per band wherever the fragment map lets it, and the reviewing
agent reads those numbers under the shared rubric.

That division is D-F7's, not a preference. The rubric is SOFT on minor differences and STRICT on
brokenness, and only a reader who knows which is which can apply it — a number that had already
decided "this band is wrong" would have made the rubric's soft half unreachable.

**How a band is located on each side.**

* On the REFERENCE, from the fragment's own mint provenance: ``geometry.top_px`` /
  ``bottom_px`` are what the capture's browser measured, in CSS pixels, and the screenshot is the
  page at ``viewport_width``, so one CSS pixel is ``screenshot_width / viewport_width`` image
  pixels. This is the same conversion the mint's preview crop makes, deliberately — a band
  compared against a differently-derived crop of the same picture would be comparing our
  arithmetic, not the page.
* On OUR page, from the walk's own DOM measurement of the band's wrapper.

A band the fragment map cannot place on one side or the other is SKIPPED and named, never
guessed at.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Any

COMPARISON_SCHEMA_VERSION = 1

#: The grid a region difference is measured on. 24x24 cells over whatever the band's real size
#: is: coarse enough that a one-pixel layout shift or a font hinting difference does not register,
#: fine enough that a missing image, a collapsed column or a colour inversion does.
COMPARE_GRID = 24

#: How different a band's cells must be, on average, before it is worth the agent's attention.
#: 0.08 of full-scale grey (~20 levels of 255): re-encoding, downscaling and anti-aliasing move
#: a cell by a couple of levels; a band that has genuinely changed moves by dozens.
DRIFT_PIXEL_DELTA = 0.08

#: How far a band's rendered height may differ from the reference's before the same. 15%: brand
#: fonts, a slot filled with a longer string and a repaired band are all legitimate reasons for a
#: band to breathe differently, and none of them is a fidelity defect.
DRIFT_HEIGHT_TOLERANCE = 0.15


@dataclass(frozen=True)
class ReferenceBand:
    """Where a band sat on the reference page, in the capture's own CSS pixels."""

    fragment_id: str
    top_px: float
    bottom_px: float

    @property
    def height_px(self) -> float:
        return max(0.0, self.bottom_px - self.top_px)


@dataclass(frozen=True)
class RenderedBand:
    """Where the same band sits on the page we rendered, in CSS pixels."""

    fragment_id: str
    top_px: float
    height_px: float


def compare_to_reference(
    *,
    reference_png: bytes | None,
    capture_png: bytes | None,
    reference_viewport_width: int | None,
    rendered_viewport_width: int,
    reference_bands: Sequence[ReferenceBand] = (),
    rendered_bands: Sequence[RenderedBand] = (),
) -> dict[str, Any]:
    """The whole comparison, or an honest statement of why there is none.

    Every unavailable input has its own ``because`` code rather than one shared "unavailable":
    "the client's site was captured without a screenshot" and "our own walk could not photograph
    the page" are different problems with different owners, and a reviewer told only that the
    comparison is missing cannot tell which of them to chase.
    """
    if not reference_png:
        return _unavailable("no_reference_screenshot")
    if not capture_png:
        return _unavailable("no_page_capture")
    if not reference_viewport_width or reference_viewport_width <= 0:
        return _unavailable("reference_viewport_unknown")

    reference = _open_grey(reference_png)
    capture = _open_grey(capture_png)
    if reference is None:
        return _unavailable("reference_unreadable")
    if capture is None:
        return _unavailable("capture_unreadable")

    reference_scale = reference.width / float(reference_viewport_width)
    capture_scale = capture.width / float(max(rendered_viewport_width, 1))

    reference_by_id = {band.fragment_id: band for band in reference_bands}
    rendered_by_id = {band.fragment_id: band for band in rendered_bands}

    bands: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for fragment_id in rendered_by_id:
        rendered = rendered_by_id[fragment_id]
        reference_band = reference_by_id.get(fragment_id)
        if reference_band is None:
            skipped.append({"fragment_id": fragment_id, "because": "no_reference_geometry"})
            continue
        if reference_band.height_px <= 0 or rendered.height_px <= 0:
            skipped.append({"fragment_id": fragment_id, "because": "zero_height"})
            continue
        left = reference.cells(
            reference_band.top_px * reference_scale,
            reference_band.bottom_px * reference_scale,
        )
        right = capture.cells(
            rendered.top_px * capture_scale,
            (rendered.top_px + rendered.height_px) * capture_scale,
        )
        if left is None or right is None:
            skipped.append({"fragment_id": fragment_id, "because": "outside_capture"})
            continue
        delta = _cell_delta(left, right)
        height_ratio = rendered.height_px / reference_band.height_px
        bands.append(
            {
                "fragment_id": fragment_id,
                "reference_height_px": round(reference_band.height_px, 1),
                "rendered_height_px": round(rendered.height_px, 1),
                "height_ratio": round(height_ratio, 3),
                "pixel_delta": round(delta, 4),
                "drifted": (
                    delta > DRIFT_PIXEL_DELTA
                    or abs(height_ratio - 1.0) > DRIFT_HEIGHT_TOLERANCE
                ),
            }
        )

    reference_css_height = reference.height / reference_scale if reference_scale else 0.0
    capture_css_height = capture.height / capture_scale if capture_scale else 0.0
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": "ok",
        "reference": {
            "image_px": [reference.width, reference.height],
            "viewport_width": reference_viewport_width,
            "page_height_px": round(reference_css_height, 1),
        },
        "capture": {
            "image_px": [capture.width, capture.height],
            "viewport_width": rendered_viewport_width,
            "page_height_px": round(capture_css_height, 1),
        },
        "page_height_ratio": (
            round(capture_css_height / reference_css_height, 3)
            if reference_css_height
            else None
        ),
        "whole_page_pixel_delta": round(_whole_page_delta(reference, capture), 4),
        "bands": bands,
        "skipped_bands": skipped,
        "thresholds": {
            "grid": COMPARE_GRID,
            "pixel_delta": DRIFT_PIXEL_DELTA,
            "height_tolerance": DRIFT_HEIGHT_TOLERANCE,
        },
    }


def _unavailable(because: str) -> dict[str, Any]:
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": "unavailable",
        "because": because,
    }


class _Grey:
    """One screenshot as 8-bit grey, with a cell sampler over any horizontal slice of it."""

    def __init__(self, data: bytes, width: int, height: int) -> None:
        self._data = data
        self.width = width
        self.height = height

    def cells(self, top: float, bottom: float) -> list[float] | None:
        """The mean grey of a ``COMPARE_GRID`` x ``COMPARE_GRID`` sample of one horizontal slice.

        ``None`` when the slice falls outside the image — which happens legitimately (a capture
        that is shorter than the reference does not contain the reference's footer) and must be
        reported as a skip rather than sampled off the edge.
        """
        first = int(max(0, round(top)))
        last = int(min(self.height, round(bottom)))
        if last - first < COMPARE_GRID or self.width < COMPARE_GRID:
            return None
        rows = last - first
        out: list[float] = []
        for cell_y in range(COMPARE_GRID):
            y0 = first + (rows * cell_y) // COMPARE_GRID
            y1 = first + (rows * (cell_y + 1)) // COMPARE_GRID
            for cell_x in range(COMPARE_GRID):
                x0 = (self.width * cell_x) // COMPARE_GRID
                x1 = (self.width * (cell_x + 1)) // COMPARE_GRID
                total = 0
                count = 0
                for y in range(y0, max(y0 + 1, y1)):
                    row = self._data[y * self.width : (y + 1) * self.width]
                    slab = row[x0 : max(x0 + 1, x1)]
                    total += sum(slab)
                    count += len(slab)
                out.append(total / count if count else 0.0)
        return out


def _open_grey(data: bytes) -> _Grey | None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(data)) as opened:
            grey = opened.convert("L")
            # Normalize the width so two screenshots taken at different device pixel ratios are
            # compared cell for cell rather than pixel for pixel. Height rides along so the
            # aspect (and therefore where a band sits) is preserved.
            width, height = grey.size
            if width <= 0 or height <= 0:
                return None
            if width != _NORMALIZED_WIDTH:
                scale = _NORMALIZED_WIDTH / float(width)
                grey = grey.resize(
                    (_NORMALIZED_WIDTH, max(1, int(round(height * scale)))),
                    Image.Resampling.LANCZOS,
                )
            return _Grey(grey.tobytes(), grey.width, grey.height)
    except (UnidentifiedImageError, OSError, ValueError):
        return None


#: Both screenshots are resampled to this width before anything is measured. A fixed width means
#: the scale factor arithmetic above is exact on both sides and a retina capture does not read as
#: a different page from a 1x one. 960 keeps a 1440px page's detail while making the pure-Python
#: cell sum cheap enough to run on a tall page without numpy.
_NORMALIZED_WIDTH = 960


def _cell_delta(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    total = sum(abs(a - b) for a, b in zip(left, right))
    return total / (len(left) * 255.0)


def _whole_page_delta(reference: _Grey, capture: _Grey) -> float:
    left = reference.cells(0, reference.height)
    right = capture.cells(0, capture.height)
    if left is None or right is None:
        return 1.0
    return _cell_delta(left, right)


def reference_bands_from_fragments(
    fragments: Sequence[Mapping[str, Any]],
) -> tuple[tuple[ReferenceBand, ...], int | None, str | None]:
    """Read the reference geometry straight out of the fragments' own mint provenance.

    Returns ``(bands, viewport_width, snapshot_id)``. A fragment whose provenance carries no
    measured geometry contributes no band — the mint recorded ``geometry: null`` exactly when the
    capture did not measure the section, and inventing a rectangle for it would put the
    comparison's numbers on a stretch of page nobody measured.

    The snapshot id is the one the MOST fragments name. A page's clones all come from one
    capture, so a tie is not a real case; picking the plurality rather than the first is only so
    a single stray fragment from another walk cannot redirect the whole comparison.
    """
    bands: list[ReferenceBand] = []
    viewport_counts: dict[int, int] = {}
    snapshot_counts: dict[str, int] = {}
    for row in fragments:
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        snapshot_id = provenance.get("snapshot_id")
        if isinstance(snapshot_id, str) and snapshot_id:
            snapshot_counts[snapshot_id] = snapshot_counts.get(snapshot_id, 0) + 1
        width = provenance.get("viewport_width")
        if isinstance(width, int) and width > 0:
            viewport_counts[width] = viewport_counts.get(width, 0) + 1
        geometry = provenance.get("geometry")
        if not isinstance(geometry, Mapping):
            continue
        top = geometry.get("top_px")
        bottom = geometry.get("bottom_px")
        fragment_id = row.get("fragment_id")
        if not isinstance(fragment_id, str) or top is None or bottom is None:
            continue
        try:
            bands.append(
                ReferenceBand(
                    fragment_id=fragment_id, top_px=float(top), bottom_px=float(bottom)
                )
            )
        except (TypeError, ValueError):
            continue
    return (
        tuple(bands),
        max(viewport_counts, key=lambda key: viewport_counts[key]) if viewport_counts else None,
        max(snapshot_counts, key=lambda key: snapshot_counts[key]) if snapshot_counts else None,
    )


__all__ = [
    "COMPARE_GRID",
    "COMPARISON_SCHEMA_VERSION",
    "DRIFT_HEIGHT_TOLERANCE",
    "DRIFT_PIXEL_DELTA",
    "ReferenceBand",
    "RenderedBand",
    "compare_to_reference",
    "reference_bands_from_fragments",
]
