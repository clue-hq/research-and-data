"""The measured band sequence, carried from capture to the section harvest (F2.1).

The rendered tier already measures the page's real bands — ``capture/geometry.py``'s in-page
probe walks the top-level children of ``<main>`` (or the body, descended through single-child
wrappers) and records each band's tag, background and height. Two consumers read it today: the
brief agent's ``background_rhythm`` and ``normalizer/bands.py``'s ``surface.band.*`` mint. Both
take the *sequence* as a color finding and throw the geometry away.

F2.1 needs the geometry itself — a section's y-extent is what lets minting crop the right strip
out of the stored screenshot — and it needs it from the PERSISTED snapshot, long after the
browser is gone. So the band records ride into ``design_site_snapshot.meta_json`` under one key,
stated here once and read back here once, bounded by the same cap the probe itself enforces.

This module deliberately imports nothing: the capture-side writer (``site_snapshot``) and the
harvest-side reader (``segment``) share the key and the shape without either pulling in the
other's dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

#: Where a persisted snapshot's band records live inside ``meta_json``.
SNAPSHOT_META_BANDS_KEY = "bands"

#: How many band records one snapshot may carry — the probe's own ``MAX_SECTIONS``. A page that
#: reaches it was already truncated in the browser; re-stating the cap here keeps a hand-built
#: or replayed harvest from putting an unbounded list on the row.
MAX_PERSISTED_BANDS = 40


@dataclass(frozen=True)
class MeasuredBand:
    """One band the browser actually measured, normalized for the segmenter.

    ``top_px`` is ``None`` on a pre-F2.1 harvest: the probe recorded heights but no absolute
    tops until this phase asked for them, and a band whose top we do not know is honestly
    unknown rather than silently assumed to be zero.
    """

    index: int
    tag: str
    element_id: str | None
    class_names: tuple[str, ...]
    top_px: float | None
    height_px: float
    background: str | None
    gradient: bool
    has_image: bool


def bands_for_meta(geometry: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The band records worth persisting out of one raw geometry harvest.

    Kept RAW (the probe's own dicts, not ``MeasuredBand``) so a key the probe learns to record
    tomorrow survives a snapshot written today — the normalization happens on read. A static-tier
    capture measured nothing and contributes ``[]``.
    """
    if not isinstance(geometry, Mapping):
        return []
    sections = geometry.get("sections")
    if not isinstance(sections, list):
        return []
    return [entry for entry in sections if isinstance(entry, dict)][:MAX_PERSISTED_BANDS]


def measured_bands(meta: Mapping[str, Any] | None) -> tuple[MeasuredBand, ...]:
    """The band sequence a persisted snapshot's ``meta`` carries, in document order.

    Every field is tolerated absent — a snapshot persisted before this phase carries no bands at
    all, and one persisted by an older probe carries no ``top``/``id``/``classes``. Order is the
    probe's own (the list order), not the ``index`` field: the index is what the browser saw and
    is reported as-is, while the list is what was stored.
    """
    if not isinstance(meta, Mapping):
        return ()
    raw = meta.get(SNAPSHOT_META_BANDS_KEY)
    if not isinstance(raw, list):
        return ()
    bands: list[MeasuredBand] = []
    for position, entry in enumerate(raw[:MAX_PERSISTED_BANDS]):
        if not isinstance(entry, dict):
            continue
        bands.append(
            MeasuredBand(
                index=_int(entry.get("index"), position),
                tag=str(entry.get("tag") or "").lower(),
                element_id=_text(entry.get("id")),
                class_names=tuple((_text(entry.get("classes")) or "").split()),
                top_px=_optional_float(entry.get("top")),
                height_px=_float(entry.get("height")),
                background=_text(entry.get("bg")),
                gradient=bool(entry.get("gradient")),
                has_image=bool(entry.get("bgImage")),
            )
        )
    return tuple(bands)


def _int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
