"""Responsive brand type (spec docs/superpowers/specs/2026-10-18-responsive-brand-type-design.md §3.1–3.2).

The kit's twelve roles worked out at each width the capture narrowed to, exactly as desktop's are
(``build_type_styles``), keeping the elements desktop chose: a width's anchors take their sizes from
the same samples (by ``sample_index``). The result is the ``responsive_type`` kit section, kept
outside the engine like ``measured_components``. Desktop's own styles are never touched.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..evidence import BrandEvidence, TypeSample
from .typography import TypeAnchors

SECTION_VERSION = 1
#: A size is a step when it moves at least this much from the next wider width (sizes are kept to
#: half pixels); a line height when it moves at least this much.
SIZE_STEP = 0.5
LINE_HEIGHT_STEP = 0.01


def _anchors_at(anchors: TypeAnchors, current: dict[int, TypeSample]) -> TypeAnchors:
    """Desktop's anchors with each chosen sample swapped for the same element as drawn now."""
    def now(sample: TypeSample | None) -> TypeSample | None:
        if sample is None or sample.sample_index is None:
            return sample
        return current.get(sample.sample_index, sample)

    def size_of(index: int | None, fallback: float) -> float:
        sample = current.get(index) if index is not None else None
        return float(sample.size_px) if sample is not None and sample.size_px and sample.size_px > 0 else fallback

    return replace(
        anchors,
        headline_size=size_of(anchors.headline_index, anchors.headline_size),
        body_size=size_of(anchors.body_index, anchors.body_size),
        samples={label: now(sample) for label, sample in anchors.samples.items()},
    )


def responsive_type_section(
    anchors: TypeAnchors,
    evidence: BrandEvidence,
    build: Callable[[TypeAnchors], dict[str, dict]],
) -> dict | None:
    """The ``responsive_type`` section, or None when no narrower width was measured (an empty
    section would claim the type was measured and never changes)."""
    measured = evidence.type_widths
    if measured is None or not measured.widths:
        return None
    desktop = build(anchors)
    previous = {role: (style["font_size"], style["line_height"]) for role, style in desktop.items()}
    roles: dict[str, list[dict]] = {role: [] for role in desktop}
    # The same elements as drawn at the width being read; one gone or hidden there keeps how it was
    # drawn at the next wider width, so it never makes a step.
    current: dict[int, TypeSample] = {
        sample.sample_index: sample for sample in evidence.type_samples if sample.sample_index is not None
    }
    widths = sorted(measured.widths, key=lambda entry: entry.width, reverse=True)
    for entry in widths:
        current.update({sample.sample_index: sample for sample in entry.type_samples if sample.sample_index is not None})
        for role, style in build(_anchors_at(anchors, current)).items():
            size, line_height = style["font_size"], style["line_height"]
            was_size, was_line_height = previous[role]
            size_moved = abs(size - was_size) >= SIZE_STEP
            line_height_moved = abs(line_height - was_line_height) >= LINE_HEIGHT_STEP
            if not (size_moved or line_height_moved):
                continue
            step: dict = {"max_width": entry.width, "font_size": size}
            if line_height_moved:
                step["line_height"] = line_height
            roles[role].append(step)
            previous[role] = (size, line_height)
    source = evidence.source or {}
    return {
        "version": SECTION_VERSION,
        "measured_from": measured.capture_width,
        "widths": [entry.width for entry in widths],
        "source": {"url": source.get("url"), "measured_at": source.get("captured_at")},
        "roles": roles,
    }
