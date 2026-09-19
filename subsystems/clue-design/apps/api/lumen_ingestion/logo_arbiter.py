"""One arbiter picks each cell of the 2x2 logo family (founder decision 2026-09-02).

Both sources — the Brandfetch vendor rung and the in-house site ladder — propose
candidates for every cell, and this module picks one per cell. It judges the
MEASURED ink first: a vendor theme label is a hint, never proof. On
freshcontext.ai a Brandfetch asset labelled for dark surfaces held dark brown
art, and vendor-first with per-cell backfill let it keep `dark_lockup` while the
site's real on-dark file was discarded.

Pure: no network and no I/O, only a read of bytes already in hand.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from .logo_family import CELL_NAMES, SOURCE_BRANDFETCH, FamilyCell

__all__ = [
    "COMPLETENESS_RANK",
    "Contender",
    "PROVEN_VERDICTS",
    "SOURCE_RANK",
    "THEME_OF_CELL",
    "choose_cells",
    "measure_verdict",
    "rank_key",
]

THEME_OF_CELL = {
    "light_lockup": "light",
    "dark_lockup": "dark",
    "light_mark": "light",
    "dark_mark": "dark",
}

#: What a candidate must MEASURE as (`logo_ladder.analyze_appearance` verdict) to
#: count as proven for a cell theme. Asymmetric on purpose: light ink on a dark
#: surface is the failure that makes a logo vanish, so a dark cell must PROVE
#: light ink; a light cell accepts an ambiguous (`unknown`, e.g. mid-tone orange)
#: logo.
PROVEN_VERDICTS = {
    "light": {"light_variant", "adaptive", "unknown"},
    "dark": {"dark_variant", "adaptive"},
}

#: The vendor's `logo` is an UNCLASSIFIED lockup, so it ranks with a wordmark: we
#: cannot know it is complete. The ladder measures `full_lockup`/`wordmark`/`symbol`.
COMPLETENESS_RANK = {"full_lockup": 3, "lockup": 2, "wordmark": 2, "symbol": 1, None: 0}

#: The vendor wins exact ties: it answered identity in one keyed call.
SOURCE_RANK = {"logo_dev": 1, "brandfetch": 1, "ladder": 0, "ladder-materialized": 0}

_FMT_FOR_CONTENT_TYPE = {
    "image/svg+xml": "svg",
    "image/png": "png",
    "image/webp": "webp",
    "image/jpeg": "jpeg",
}

_COMPLETENESS_FOR_VENDOR_TYPE = {"logo": "lockup", "symbol": "symbol"}


def measure_verdict(cell: FamilyCell) -> str:
    """The cell's own bytes, read by the ladder's appearance analyzer.

    One classifier for both sources, so a vendor file and a scraped file are
    judged the same way. Returns "unknown" on anything it cannot read.
    """
    from .logo_ladder import LadderCandidate, analyze_appearance

    fmt = _FMT_FOR_CONTENT_TYPE.get((cell.content_type or "").split(";")[0].strip().lower())
    if fmt is None or not cell.body:
        return "unknown"
    try:
        probe = LadderCandidate(url="", fmt=fmt, body=cell.body)
        return str(analyze_appearance(probe).get("verdict") or "unknown")
    except Exception:  # noqa: BLE001 - an unreadable candidate is unknown, never fatal
        return "unknown"


@dataclass(frozen=True)
class Contender:
    """One candidate for one cell, with the facts the ranking reads."""

    cell: str
    family_cell: FamilyCell
    completeness: str | None
    verdict: str
    proven: bool
    is_svg: bool
    pixel_area: int
    source_rank: int


def rank_key(contender: Contender) -> tuple:
    """Higher is better: proven ink, then completeness, then vector, size, source."""
    return (
        contender.proven,
        COMPLETENESS_RANK.get(contender.completeness, 0),
        contender.is_svg,
        contender.pixel_area,
        contender.source_rank,
    )


def choose_cells(
    candidates: Mapping[str, Sequence[FamilyCell]],
) -> tuple[dict[str, FamilyCell], list[FamilyCell], list[str]]:
    """Pick one candidate per cell, and say what each winner beat.

    Nothing is rejected outright: a candidate whose ink is not proven for the
    surface only ranks BELOW one whose ink is, so it still wins a cell no proven
    asset applied for — recorded as unverified rather than dropped. A cell with
    no candidates stays empty; the family is never completed by recoloring.

    Returns (chosen, alternatives, notes). `alternatives` is every beaten
    contender, in cell then rank order, each carrying `competed_for`,
    `lost_to` and a one-line `reason`: a loser is still a real asset for this
    brand, and only the agent looking at the placement can tell whether the
    winner actually fits it.
    """
    chosen: dict[str, FamilyCell] = {}
    alternatives: list[FamilyCell] = []
    notes: list[str] = []

    for name in CELL_NAMES:
        proposed = list(candidates.get(name) or [])
        if not proposed:
            continue
        theme = THEME_OF_CELL[name]
        contenders = sorted(
            (_contender(name, cell, theme) for cell in proposed), key=rank_key, reverse=True
        )
        winner, beaten = contenders[0], contenders[1:]

        evidence = dict(winner.family_cell.evidence or {})
        evidence["measured_verdict"] = winner.verdict
        evidence["arbitration"] = {
            "beat": [f"{c.family_cell.source}:{_tail(c.family_cell)}" for c in beaten],
            "proven": winner.proven,
        }
        chosen[name] = replace(winner.family_cell, cell=name, evidence=evidence)

        for loser in beaten:
            loser_evidence = dict(loser.family_cell.evidence or {})
            loser_evidence["measured_verdict"] = loser.verdict
            loser_evidence["competed_for"] = name
            loser_evidence["lost_to"] = (
                f"{winner.family_cell.source}:{_tail(winner.family_cell)}"
            )
            loser_evidence["reason"] = (
                f"ink measured {loser.verdict}, not proven for a {theme} surface"
                if winner.proven and not loser.proven
                else f"lost on completeness, format or size to {_tail(winner.family_cell)}"
            )
            alternatives.append(
                replace(loser.family_cell, cell=name, evidence=loser_evidence)
            )
            if loser.family_cell.source != SOURCE_BRANDFETCH:
                continue
            notes.append(
                f"{name}: took the {winner.family_cell.source} asset "
                f"({_tail(winner.family_cell)}) over brandfetch's "
                f"({_tail(loser.family_cell)}); {_why(winner, loser, theme)}"
            )
        if not winner.proven:
            notes.append(
                f"{name}: kept an unverified asset ({_tail(winner.family_cell)}) — its ink "
                f"measured {winner.verdict}, and nothing proven for a {theme} surface was offered"
            )

    return chosen, alternatives, notes


def _contender(name: str, cell: FamilyCell, theme: str) -> Contender:
    verdict = measure_verdict(cell)
    is_svg = (cell.content_type or "").split(";")[0].strip().lower() == "image/svg+xml"
    return Contender(
        cell=name,
        family_cell=cell,
        completeness=_completeness(cell),
        verdict=verdict,
        proven=verdict in PROVEN_VERDICTS[theme],
        is_svg=is_svg,
        # A vector has no pixel size to compare, and outranks any raster anyway.
        pixel_area=0 if is_svg else _pixel_area(cell),
        source_rank=SOURCE_RANK.get(cell.source, 0),
    )


def _completeness(cell: FamilyCell) -> str | None:
    evidence = cell.evidence or {}
    vendor_type = evidence.get("vendor_type")
    if vendor_type is not None:
        return _COMPLETENESS_FOR_VENDOR_TYPE.get(str(vendor_type))
    lockup = evidence.get("lockup")
    return str(lockup) if lockup else None


def _pixel_area(cell: FamilyCell) -> int:
    evidence = cell.evidence or {}
    try:
        width = int(evidence.get("width") or 0)
        height = int(evidence.get("height") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, width) * max(0, height)


def _tail(cell: FamilyCell) -> str:
    url = cell.origin_url or ""
    return url.rstrip("/").rsplit("/", 1)[-1] or url


def _why(winner: Contender, loser: Contender, theme: str) -> str:
    if winner.proven and not loser.proven:
        return f"the vendor asset measured {loser.verdict}, not ink for a {theme} surface"
    return "it is the more complete, better-formatted or larger file"
