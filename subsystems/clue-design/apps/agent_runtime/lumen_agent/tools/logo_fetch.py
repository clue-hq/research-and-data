"""Fetch a target account's real logo family, mid-turn, for either lane.

Both design substrates expose this as a `fetch_logo` tool. The lanes differ
only in how a registered asset reaches their document — the WebDoc op key is
``record``, the scene's is ``asset`` — so everything up to that point lives
here: normalize the input, run the two rungs, and shape one ingest call per
resolved cell of the 2x2 family.

Two rungs, in order (founder decision 2026-08-31): the VENDOR (Brandfetch) is
asked first, because a licensed brand API answers in one call what a scrape
guesses at; the in-house LADDER then backfills only the cells the vendor left
empty. A vendor-full family never touches the site at all.

Static tier only on the ladder rung. A Playwright launch costs about thirty
seconds, which is more than a turn can spend, so a page that renders its header
in JavaScript comes back honestly empty rather than slowly right.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lumen_ingestion.logo_family import CELL_NAMES

JsonObject = Dict[str, Any]

# Tags let a later pass tell a fetched account logo from the workspace's own
# brand assets without re-deriving it from provenance.
LOGO_TAGS = ("target-account", "logo-ladder")

__all__ = [
    "CELL_NAMES",
    "LOGO_TAGS",
    "LogoFetchOutcome",
    "PreparedLogo",
    "fetch_logo_family",
    "ladder_cells",
    "review_payload",
]


@dataclass
class PreparedLogo:
    """One resolved cell, shaped for `core.ingest_asset`."""

    cell: str
    source: str  # "brandfetch" | "ladder" | "ladder-materialized"
    asset_id: str
    label: str
    body: bytes
    content_type: str
    provenance: JsonObject
    source_ref: JsonObject  # the ingest `source` kwarg (renamed field, same payload)
    evidence: JsonObject

    def ingest_kwargs(self, store_root: str) -> JsonObject:
        import base64

        return {
            "store_root": store_root,
            "bytes_base64": base64.b64encode(self.body).decode("ascii"),
            "asset_id": self.asset_id,
            "label": self.label,
            "declared_mime_type": self.content_type,
            "kind": "vector" if self.content_type == "image/svg+xml" else "raster_image",
            "provenance": self.provenance,
            "source": self.source_ref,
            "tags": list(LOGO_TAGS),
            "raise_on_error": False,
        }


@dataclass
class LogoFetchOutcome:
    status: str
    site: str
    company: Optional[str]
    prepared: List[PreparedLogo] = field(default_factory=list)
    cells: Dict[str, str] = field(default_factory=dict)  # cell -> source
    identity: JsonObject = field(default_factory=dict)
    lockup_completeness: str = "unknown"
    notes: List[str] = field(default_factory=list)
    vendor_notes: List[str] = field(default_factory=list)
    candidates: List[JsonObject] = field(default_factory=list)
    cache_hit: bool = False

    @property
    def needs_review(self) -> bool:
        return not self.prepared


def _vendor_rung(site: str, company_name: Optional[str]):
    """Module-level indirection so tests (and future vendors) swap it whole."""
    from lumen_ingestion.logo_vendor import fetch_vendor_family

    return fetch_vendor_family(site)


def _ladder_rung(site: str, company_name: Optional[str]):
    from lumen_ingestion import logo_ladder

    return asyncio.run(logo_ladder.fetch_logo_family(site, company_name=company_name))


def fetch_logo_family(
    url_or_domain: str,
    *,
    company_name: Optional[str] = None,
    force_refresh: bool = False,
    cache=None,
) -> LogoFetchOutcome:
    """Two-rung dispatch: cache -> Brandfetch -> ladder (per-cell backfill).

    Raises `CaptureError` only from the ladder rung (blocked/unreachable site);
    every vendor failure is a typed degrade recorded in the outcome notes.
    """
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing, VendorLookupFailed

    site = logo_ladder.normalize_site_url(url_or_domain)

    if cache is not None and not force_refresh:
        hit = cache.get(site)
        if hit is not None:
            hit.cache_hit = True
            return hit

    cells: dict = {}
    notes: List[str] = []
    vendor_notes: List[str] = []
    try:
        cells, vendor_notes = _vendor_rung(site, company_name)
    except VendorCredentialsMissing:
        notes.append("vendor rung disabled: no BRANDFETCH_API_KEY configured")
    except VendorLookupFailed as error:
        notes.append(f"vendor rung degraded ({error.code}): {error.message}")

    resolution = None
    missing = [name for name in CELL_NAMES if name not in cells]
    if missing:
        resolution = _ladder_rung(site, company_name)
        for name, cell in ladder_cells(resolution).items():
            if name in missing:
                cells[name] = cell

    outcome = _assemble(cells, resolution, site, company_name, notes, vendor_notes)
    if cache is not None and outcome.status == "ok":
        cache.put(site, outcome)
    return outcome


def _assemble(cells, resolution, site, company_name, notes, vendor_notes) -> LogoFetchOutcome:
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.logo_family import CELL_NAMES as _CELLS

    host = logo_ladder.host_of(site)
    label_base = company_name or logo_ladder.registrable_domain(host) or host

    prepared: List[PreparedLogo] = []
    for name in _CELLS:
        cell = cells.get(name)
        if cell is None or not cell.body:
            continue
        import hashlib

        # Content-addressed, so fetching the same brand twice in a run
        # re-registers the same id instead of duplicating the asset.
        digest = hashlib.sha256(cell.body).hexdigest()
        created_by = "brandfetch" if cell.source == "brandfetch" else "logo_ladder"
        prepared.append(
            PreparedLogo(
                cell=name,
                source=cell.source,
                asset_id=f"asset_ing_{digest[:16]}",
                label=f"{label_base} logo ({name})",
                body=cell.body,
                content_type=cell.content_type,
                provenance={
                    "created_by": created_by,
                    "source_label": "brandfetch" if created_by == "brandfetch" else "website",
                    "confidence": (resolution.confidence if resolution else 0.9),
                },
                source_ref={
                    # The engine's AssetSource has no vendor variant; a vendor-served file is
                    # a URL capture like any other, and `provenance` carries who served it.
                    "kind": "website",
                    "url": cell.origin_url,
                    "captured_at": _now(),
                },
                evidence={"cell": name, "source": cell.source, **cell.evidence},
            )
        )

    all_notes = list(notes)
    if resolution is not None:
        all_notes.extend(resolution.notes)
    if not prepared:
        all_notes.append(
            "no cell cleared both rungs (the vendor had no attributable asset and "
            "the ladder found nothing it could stand behind; a variant is never "
            "synthesized), so nothing was ingested"
        )

    # "ok" means at least one rung stood behind what it returned: a vendor cell is keyed
    # retrieval (identity answered by the vendor), and a RESOLVED ladder stood behind its
    # own. A ladder that hesitated (alternate lockups, a non-auto-accept rung) still
    # prepares its cells — the agent may place them — but the status carries the caveat,
    # exactly as it did before the vendor rung existed.
    vendor_backed = any(p.source == "brandfetch" for p in prepared)
    ladder_resolved = resolution is not None and resolution.status == "resolved"
    status = "ok" if prepared and (vendor_backed or ladder_resolved) else "needs_review"

    return LogoFetchOutcome(
        status=status,
        site=site,
        company=company_name,
        prepared=prepared,
        cells={p.cell: p.source for p in prepared},
        identity=(
            {
                "passed": resolution.identity.get("passed"),
                "evidence": resolution.identity.get("evidence", [])[:3],
                "reason": resolution.identity.get("reason"),
            }
            if resolution is not None
            else {"passed": bool(prepared), "evidence": [], "reason": None}
        ),
        lockup_completeness=(resolution.lockup_completeness if resolution else "unknown"),
        notes=all_notes,
        vendor_notes=vendor_notes,
        candidates=(
            [c.summary() for c in resolution.ranked[:6]] if resolution is not None else []
        ),
    )


def ladder_cells(resolution) -> dict:
    """The ladder's four slots folded into the 2x2. The ladder's `light`/`dark`
    are theme-correct already (its slot names use OUR background semantics);
    what this adds is the completeness split: a symbol-shaped primary is a
    MARK, not a lockup, and the wordmark slot backfills the light lockup."""
    from lumen_ingestion.logo_family import (
        SOURCE_LADDER,
        SOURCE_LADDER_MATERIALIZED,
        FamilyCell,
    )

    def to_cell(name: str, slot, ladder_slot: str) -> FamilyCell:
        return FamilyCell(
            cell=name,
            body=slot.body,
            content_type=slot.content_type,
            source=(
                SOURCE_LADDER_MATERIALIZED
                if slot.provenance == "materialized-adaptive"
                else SOURCE_LADDER
            ),
            origin_url=slot.candidate.url,
            evidence={
                "ladder_slot": ladder_slot,
                "rung": slot.candidate.rung,
                "basis": slot.basis[:200],
                "lockup": slot.candidate.lockup,
                **({"materialized_ink": slot.ink} if slot.ink else {}),
            },
        )

    cells: dict = {}
    for theme in ("light", "dark"):
        slot = resolution.slots.get(theme)
        if slot is None or not slot.body:
            continue
        completeness = "mark" if slot.candidate.lockup == "symbol" else "lockup"
        cells[f"{theme}_{completeness}"] = to_cell(f"{theme}_{completeness}", slot, theme)

    mark = resolution.slots.get("mark")
    if mark is not None and mark.body:
        name = "dark_mark" if mark.candidate.variant == "dark" else "light_mark"
        if name not in cells:
            cells[name] = to_cell(name, mark, "mark")

    wordmark = resolution.slots.get("wordmark")
    if wordmark is not None and wordmark.body and "light_lockup" not in cells:
        cells["light_lockup"] = to_cell("light_lockup", wordmark, "wordmark")
    return cells


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def review_payload(outcome: LogoFetchOutcome) -> JsonObject:
    """What the agent gets when nothing was safe to place.

    It lists what was found and ranked so a human can choose, and says plainly
    that guessing is not the fallback.
    """
    return {
        "status": "needs_review",
        "site": outcome.site,
        "identity": outcome.identity,
        "reason": (
            "no logo could be attributed to this company with confidence"
            if not outcome.identity.get("passed")
            else "the ladder resolved nothing it could stand behind"
        ),
        "notes": outcome.notes[:4],
        "vendor_notes": outcome.vendor_notes[:3],
        "ranked_candidates": outcome.candidates,
        "what_to_do": (
            "Tell the user the logo could not be confirmed and ask them for the file "
            "or the exact URL. Do not draw, recolor, or approximate a logo."
        ),
    }
