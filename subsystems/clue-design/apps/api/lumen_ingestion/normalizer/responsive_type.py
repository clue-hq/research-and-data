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
from .typography import TypeAnchors, anchor_for_role

#: The roles worked out from the headline's size; every other role comes from the body's.
_HEADLINE_ROLES = {"display", "headline", "title", "stat"}

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


def _source_index(role: str, anchors: TypeAnchors) -> int | None:
    """The rendered sample a role's size comes from: its own measured element, else the headline's
    or the body's."""
    anchor = anchor_for_role(role, anchors)
    if anchor is not None and anchor.sample_index is not None:
        return anchor.sample_index
    return anchors.headline_index if role in _HEADLINE_ROLES else anchors.body_index


def _own_index(role: str, anchors: TypeAnchors) -> int | None:
    """The rendered sample a role has of its own (Garner's button, an h2), or None when its size
    comes from the headline or the body."""
    anchor = anchor_for_role(role, anchors)
    if anchor is None or anchor.sample_index is None:
        return None
    return None if anchor.sample_index in (anchors.headline_index, anchors.body_index) else anchor.sample_index


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
    # A role is measured only if the element it comes from was read at a narrower width at all;
    # sites that draw a separate copy of the page per break point hide the desktop copy, and a
    # role whose element was never read there must stay unmeasured, not "never changes".
    read = {sample.sample_index for entry in widths for sample in entry.type_samples if sample.sample_index is not None}
    if anchors.headline_index not in read and anchors.body_index not in read:
        return None
    title = float(desktop["type.title"]["font_size"]) if "type.title" in desktop else None
    for entry in widths:
        drawn = {sample.sample_index for sample in entry.type_samples if sample.sample_index is not None}
        current.update({sample.sample_index: sample for sample in entry.type_samples if sample.sample_index is not None})
        built = build(_anchors_at(anchors, current))
        for role, style in built.items():
            size, line_height = style["font_size"], style["line_height"]
            was_size, was_line_height = previous[role]
            own = _own_index(role.removeprefix("type."), anchors)
            if own is not None and own not in drawn:
                # Founder, 2026-10-18 (option A): its element is not drawn at this width (a button hidden
                # below a break point), so it follows the nearest role's narrowing here — the headline's
                # at or above the title size, else the body's — as a hand-set size does (edits.ts
                # fontSizeCss), instead of keeping its last measured step at every narrower width.
                reference = "type.headline" if title is not None and desktop[role]["font_size"] >= title else "type.body"
                ratio = built[reference]["font_size"] / desktop[reference]["font_size"]
                size, line_height = round(desktop[role]["font_size"] * ratio * 2) / 2, was_line_height
            size_moved = abs(size - was_size) >= SIZE_STEP
            line_height_moved = abs(line_height - was_line_height) >= LINE_HEIGHT_STEP
            if not (size_moved or line_height_moved):
                continue
            step: dict = {"max_width": entry.width, "font_size": size}
            if line_height_moved:
                step["line_height"] = line_height
            roles[role].append(step)
            previous[role] = (size, line_height)
    for role in list(roles):
        if _source_index(role.removeprefix("type."), anchors) not in read:
            del roles[role]
    source = evidence.source or {}
    return {
        "version": SECTION_VERSION,
        "measured_from": measured.capture_width,
        "widths": [entry.width for entry in widths],
        "source": {"url": source.get("url"), "measured_at": source.get("captured_at")},
        "roles": roles,
    }


#: A re-measure leaves a role out when today's page draws its desktop size this far from the kit's
#: stored one: the page changed, the capture window differs, or the kit was edited, and the steps
#: would not describe the kit's own type.
REMEASURE_TOLERANCE = 0.15


def _round_half(value: float) -> float:
    return round(value * 2) / 2


def _stored_size(kit: dict, role: str) -> float | None:
    try:
        size = kit["tokens"]["typography"][role]["value"]["default"]["font_size"]
    except (KeyError, TypeError):
        return None
    return float(size) if isinstance(size, (int, float)) and size > 0 else None


def remeasured_section(
    kit: dict,
    evidence: BrandEvidence,
    build_anchors: Callable[[BrandEvidence], TypeAnchors],
    build: Callable[[TypeAnchors], dict[str, dict]],
) -> tuple[dict | None, list[str]]:
    """The ``responsive_type`` section for an EXISTING kit from today's page (spec §3.5): each step is
    today's narrowing applied to the kit's stored desktop size (step ÷ today's desktop × stored),
    so the kit's desktop stays exactly as it is. A role the stored kit does not carry, or whose
    desktop size today is more than ``REMEASURE_TOLERANCE`` away from the stored one, is left out
    (drawn as unmeasured) and named in the second value."""
    anchors = build_anchors(evidence)
    section = responsive_type_section(anchors, evidence, build)
    if section is None:
        return None, []
    today = build(anchors)
    kept: dict[str, list[dict]] = {}
    skipped: list[str] = []
    for role, steps in section["roles"].items():
        stored = _stored_size(kit, role)
        fresh = float(today[role]["font_size"])
        if stored is None or abs(fresh - stored) / stored > REMEASURE_TOLERANCE:
            skipped.append(role)
            continue
        scaled: list[dict] = []
        previous = stored
        for step in steps:
            size = _round_half(step["font_size"] / fresh * stored)
            if abs(size - previous) < SIZE_STEP and "line_height" not in step:
                continue
            scaled.append({**step, "font_size": size})
            previous = size
        kept[role] = scaled
    if not kept:
        # Nothing on today's page matches the kit: there is nothing to publish.
        return None, skipped
    return {**section, "roles": kept, "scaled_to_stored_desktop": True}, skipped


def kit_with_section(kit: dict, section: dict | None) -> dict:
    """The kit with the re-measured section, and nothing else changed (no section: the kit as is)."""
    return {**kit, "responsive_type": section} if section is not None else kit
