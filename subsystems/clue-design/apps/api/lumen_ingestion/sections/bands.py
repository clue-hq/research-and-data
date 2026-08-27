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

#: Where the children the probe DECLINED to measure live (F2 wave W1), and the flag saying the
#: probe stopped at its own ceiling. The band sequence is a subsequence of the measured root's
#: children; without a record of what was removed, a page that hides one of several same-class
#: sections leaves an alignment nothing can resolve. The browser is the only thing that can
#: answer "is this hidden?", so its answer rides here rather than being re-derived.
SNAPSHOT_META_SKIPPED_KEY = "skipped_bands"
SNAPSHOT_META_TRUNCATED_KEY = "bands_truncated"

#: Why the probe passed over a flow child. Closed vocabulary, mirrored from the probe.
SKIP_REASONS = ("hidden", "small", "cap")

_SKIPPED_KEYS: tuple[str, ...] = ("tag", "id", "classes", "reason")

#: How many band records one snapshot may carry — the probe's own ``MAX_SECTIONS``. A page that
#: reaches it was already truncated in the browser; re-stating the cap here keeps a hand-built
#: or replayed harvest from putting an unbounded list on the row.
MAX_PERSISTED_BANDS = 40

#: The only probe keys a persisted band record carries — everything :func:`measured_bands` reads,
#: and nothing else. ``padding`` and any future harvest key are dropped rather than stored on the
#: chance someone wants them, because this row is durable and a page controls its own contents.
_PERSISTED_KEYS: tuple[str, ...] = (
    "index",
    "tag",
    "id",
    "classes",
    "top",
    "height",
    "bg",
    "gradient",
    "bgImage",
)

#: How long a stored string value may be. A class attribute on a utility-CSS page runs long
#: legitimately, so this is generous rather than tight; the bounding that matters is dropping
#: ``bgImage``'s raw value, which has no upper size at all.
MAX_BAND_TEXT = 512


@dataclass(frozen=True)
class SkippedChild:
    """One flow child the browser saw and did not measure, with its reason.

    Deliberately the same identity triple a band carries (``tag`` + ``id``/``classes``), because
    its whole job is to be matched against a parsed candidate by exactly the rule that matches a
    band — a skip nobody can identify is a skip nobody can subtract.
    """

    tag: str
    element_id: str | None
    class_names: tuple[str, ...]
    reason: str


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

    PROJECTED, not copied. The probe's own dicts carry things a durable row must not: ``bgImage``
    is a raw CSS value, so a single band can arrive holding a base64 ``data:`` URI or a
    five-layer gradient, and there can be forty of them on one row. Nothing that reads these
    records wants more than "was there a background image at all", so that is all that is kept —
    the same reduction the evidence layer has always applied to it.

    The other keys are kept as the probe wrote them, with strings capped: a class attribute is
    the one field that is legitimately long (a utility-CSS page routinely runs past 200
    characters), so the cap is generous and the cut is made on a space, never mid-token, because
    a half-written class name is a name that matches nothing and could in principle match the
    wrong thing.

    The cost of projecting is that a key the probe learns to record tomorrow does NOT survive a
    snapshot written today until it is named here — paid deliberately, because the alternative is
    an unbounded row. A static-tier capture measured nothing and contributes ``[]``.
    """
    if not isinstance(geometry, Mapping):
        return []
    sections = geometry.get("sections")
    if not isinstance(sections, list):
        return []
    kept: list[dict[str, Any]] = []
    for entry in sections[: MAX_PERSISTED_BANDS * 2]:
        if not isinstance(entry, dict):
            continue
        kept.append(_project(entry))
        if len(kept) >= MAX_PERSISTED_BANDS:
            break
    return kept


def skipped_for_meta(geometry: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The probe's skipped-child records worth persisting, under the same caps as the bands.

    Projected to four keys and capped exactly like :func:`bands_for_meta`, for the same reason:
    this is a durable row and a page controls its own class attribute.
    """
    if not isinstance(geometry, Mapping):
        return []
    entries = geometry.get("skipped")
    if not isinstance(entries, list):
        return []
    kept: list[dict[str, Any]] = []
    for entry in entries[: MAX_PERSISTED_BANDS * 2]:
        if not isinstance(entry, dict):
            continue
        record = {
            key: (_cap(entry[key]) if isinstance(entry.get(key), str) else entry.get(key))
            for key in _SKIPPED_KEYS
            if key in entry
        }
        if str(record.get("reason") or "") not in SKIP_REASONS:
            continue
        kept.append(record)
        if len(kept) >= MAX_PERSISTED_BANDS:
            break
    return kept


def skipped_children(meta: Mapping[str, Any] | None) -> tuple[SkippedChild, ...]:
    """The skipped-child records a persisted snapshot carries, in the probe's own order.

    Empty for every snapshot written before this wave, which is exactly the pre-W1 behaviour —
    the segmenter's feasibility floor does not depend on these; they only let it bind with
    certainty when they are present.
    """
    if not isinstance(meta, Mapping):
        return ()
    raw = meta.get(SNAPSHOT_META_SKIPPED_KEY)
    if not isinstance(raw, list):
        return ()
    out: list[SkippedChild] = []
    for entry in raw[:MAX_PERSISTED_BANDS]:
        if not isinstance(entry, dict):
            continue
        reason = str(entry.get("reason") or "")
        if reason not in SKIP_REASONS:
            continue
        out.append(
            SkippedChild(
                tag=str(entry.get("tag") or "").lower(),
                element_id=_text(entry.get("id")),
                class_names=tuple((_text(entry.get("classes")) or "").split()),
                reason=reason,
            )
        )
    return tuple(out)


def bands_were_truncated(meta: Mapping[str, Any] | None) -> bool:
    """Did the probe stop at its own ``MAX_SECTIONS`` ceiling on this page? (W8)"""
    return bool(isinstance(meta, Mapping) and meta.get(SNAPSHOT_META_TRUNCATED_KEY))


def _project(entry: Mapping[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key in _PERSISTED_KEYS:
        if key not in entry:
            continue
        value = entry[key]
        if key == "bgImage":
            record[key] = bool(value)
        elif isinstance(value, str):
            record[key] = _cap(value)
        elif isinstance(value, (bool, int, float)) or value is None:
            record[key] = value
    return record


def _cap(value: str) -> str:
    if len(value) <= MAX_BAND_TEXT:
        return value
    cut = value[:MAX_BAND_TEXT]
    boundary = cut.rfind(" ")
    return cut[:boundary] if boundary > 0 else cut


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
