"""Fetch a target account's real logo family, mid-turn, for either lane.

Both design substrates expose this as a `fetch_logo` tool. The lanes differ
only in how a registered asset reaches their document — the WebDoc op key is
``record``, the scene's is ``asset`` — so everything up to that point lives
here: normalize the input, run the provider and official-site rungs, and shape one ingest call per
resolved cell of the 2x2 family.

Brandfetch and the in-house LADDER propose original candidates for
every cell. Providers validate exact product identity before downloading, and
`logo_arbiter.choose_cells` picks the best one per cell -- measured ink for the
surface first, because a vendor theme label is a hint, never proof.

The four cells are the RECOMMENDATION, and every other real asset found for the
company rides along as an ALTERNATIVE (founder decision 2026-09-02). The arbiter
can prove ink and identity; it cannot know whether a vendor "logo" is complete
or whether a short form fits the placement in front of the agent. So the beaten
candidates from both sources and the vendor's `icon`/`other` types are prepared
and registered too, each saying what it competed for and why it is not in a
cell. Three constraints: only VETTED assets travel (arbitration losers and the
vendor's unclassified types -- never the ladder's raw ranked list), the cells
stay the default and the prompts say so, and the notes stay short and factual.

Static tier only on the ladder rung. A Playwright launch costs about thirty
seconds, which is more than a turn can spend, so a page that renders its header
in JavaScript comes back honestly empty rather than slowly right.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from lumen_ingestion.logo_family import CELL_NAMES

JsonObject = Dict[str, Any]

# Tags let a later pass tell a fetched account logo from the workspace's own
# brand assets without re-deriving it from provenance.
LOGO_TAGS = ("target-account", "logo-ladder")

# Failure envelopes expose only our fixed provider explanations, never a vendor
# network exception or download note that may carry credential-bearing URLs.
_VENDOR_FAILURE_DIAGNOSTICS = {
    "identity_mismatch": (
        "vendor identity_mismatch: exact host or company/product name differs"
    ),
    "identity_unverified": (
        "vendor identity_unverified: exact host and company/product identity remain ambiguous"
    ),
    "quota": "vendor quota: provider rate or quota limit reached",
    "auth": "vendor auth: check BRANDFETCH_API_KEY configuration",
    "timeout": "vendor timeout: lookup timed out",
    "http": "vendor http: lookup failed",
    "malformed": "vendor malformed: invalid provider response",
}

__all__ = [
    "CELL_NAMES",
    "LOGO_TAGS",
    "LogoFetchOutcome",
    "PreparedLogo",
    "fetch_logo_family",
    "ladder_candidates",
    "review_payload",
]


@dataclass
class PreparedLogo:
    """One resolved cell, shaped for `core.ingest_asset`."""

    cell: str
    source: str  # "logo_dev" | "brandfetch" | "ladder" | "ladder-materialized"
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
    #: Every OTHER real asset found for this company, registered like the cells
    #: and each saying why it is not one. Never a cell, never a fallback the
    #: engine picks: the agent chooses one only when a cell does not fit.
    alternatives: List[PreparedLogo] = field(default_factory=list)
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

    return fetch_vendor_family(site, company_name=company_name)


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
    """Cache -> Brandfetch + official-site ladder -> arbiter.

    Both sources propose; the arbiter picks per cell.

    Raises `CaptureError` from the ladder rung (a blocked or unreachable site) only
    when the vendor filled no cell at all; when the vendor already answered at least
    one cell that same failure is recorded as a note and the partial family stands.
    Vendor failures survive in outcome notes or a safe combined failure message.
    """
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.capture.net import CaptureError
    from lumen_ingestion.logo_arbiter import choose_cells, measure_verdict
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing, VendorLookupFailed

    site = logo_ladder.normalize_site_url(url_or_domain)

    if cache is not None and not force_refresh:
        hit = cache.get(site)
        # An earlier host-only lookup cannot waive a later product/name constraint.
        same_name = hit is not None and (
            not company_name
            or (hit.company or "").strip().casefold() == company_name.strip().casefold()
        )
        supported_sources = hit is not None and all(
            asset.source in {"brandfetch", "ladder", "ladder-materialized"}
            for asset in [*hit.prepared, *hit.alternatives]
        )
        if same_name and supported_sources:
            hit.cache_hit = True
            return hit

    cells_by_source: dict = {name: [] for name in CELL_NAMES}
    vendor_cells: dict = {}
    vendor_extras: list = []
    notes: List[str] = []
    vendor_notes: List[str] = []
    vendor_failure = "vendor supplied no eligible logo cells"
    try:
        vendor_cells, extras, provider_notes = _vendor_rung(site, company_name)
        vendor_extras.extend(extras)
        vendor_notes.extend(provider_notes)
    except VendorCredentialsMissing:
        notes.append("vendor rung disabled: no BRANDFETCH_API_KEY configured")
        vendor_failure = "vendor disabled: no BRANDFETCH_API_KEY configured"
    except VendorLookupFailed as error:
        notes.append(f"vendor rung degraded ({error.code}): {error.message}")
        vendor_failure = _VENDOR_FAILURE_DIAGNOSTICS.get(
            error.code, "vendor lookup failed: no verified provider logo available"
        )
    for name, cell in vendor_cells.items():
        cells_by_source[name].append(cell)

    resolution = None
    try:
        # Always, even on a full vendor family: the site's own assets get to
        # compete for every cell (founder ruling 2026-09-02).
        resolution = _ladder_rung(site, company_name)
    except CaptureError as error:
        # A blocked or unreachable site cannot un-answer what the vendor already
        # served, so a vendor-only family stands. With no vendor candidate to
        # keep, retain both failure reasons under the original capture code.
        if not vendor_cells:
            raise CaptureError(
                error.code,
                f"{vendor_failure}; official-site ladder failed ({error.code}): "
                f"{error.message}. Verify the exact company/product identity; use an "
                "original logo from a verified official source or user upload.",
            ) from error
        notes.append(
            f"ladder unavailable ({error.code}): {error.message}; vendor candidates only"
        )
        # The partial family caches as-is; its empty cells are retried only on a
        # later `force_refresh=True` call (the plan's eviction affordance).
    if resolution is not None and resolution.identity.get("passed") is True:
        for name, found in ladder_candidates(resolution).items():
            cells_by_source[name].extend(found)
    elif resolution is not None:
        notes.append("ladder candidates withheld: company identity did not pass")

    cells, losers, arbitration_notes = choose_cells(cells_by_source)
    notes.extend(arbitration_notes)

    # The vetted pool: beaten candidates from either source, then the vendor's
    # icon/other types. Never the ladder's raw ranked list. Every one of them
    # states its MEASURED ink -- the arbiter measured its losers, and nobody has
    # measured the vendor's extras, whose theme LABEL is not evidence (a
    # freshcontext asset labelled for dark surfaces held dark ink).
    alternatives_cells = [
        cell
        if "measured_verdict" in (cell.evidence or {})
        else replace(
            cell,
            evidence={**(cell.evidence or {}), "measured_verdict": measure_verdict(cell)},
        )
        for cell in losers + vendor_extras
    ]

    outcome = _assemble(
        cells, alternatives_cells, resolution, site, company_name, notes, vendor_notes
    )
    if cache is not None and outcome.status == "ok":
        cache.put(site, outcome)
    return outcome


def _prepare(name, cell, resolution, label_base, *, label=None) -> PreparedLogo:
    """One `FamilyCell` shaped for `core.ingest_asset`. `name` is what the asset
    calls itself — a cell name for a cell, the cell it competed for (or
    "unclassified") for an alternative."""
    import hashlib

    # Content-addressed, so fetching the same brand twice in a run
    # re-registers the same id instead of duplicating the asset.
    digest = hashlib.sha256(cell.body).hexdigest()
    created_by = cell.source if cell.source in {"brandfetch", "logo_dev"} else "logo_ladder"
    return PreparedLogo(
        cell=name,
        source=cell.source,
        asset_id=f"asset_ing_{digest[:16]}",
        label=label or f"{label_base} logo ({name})",
        body=cell.body,
        content_type=cell.content_type,
        provenance={
            "created_by": created_by,
            "source_label": created_by if created_by != "logo_ladder" else "website",
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


def _assemble(
    cells, alternatives_cells, resolution, site, company_name, notes, vendor_notes
) -> LogoFetchOutcome:
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.logo_family import CELL_NAMES as _CELLS

    host = logo_ladder.host_of(site)
    label_base = company_name or logo_ladder.registrable_domain(host) or host

    prepared: List[PreparedLogo] = []
    for name in _CELLS:
        cell = cells.get(name)
        if cell is None or not cell.body:
            continue
        prepared.append(_prepare(name, cell, resolution, label_base))

    # The alternatives ride beside the cells; they never change what a cell is,
    # what the status says, or whether the family needs review.
    alternatives: List[PreparedLogo] = []
    seen = {p.asset_id for p in prepared}
    for cell in alternatives_cells or []:
        if not cell.body:
            continue
        competed_for = cell.evidence.get("competed_for")
        tag = competed_for or cell.evidence.get("vendor_type") or "other"
        candidate = _prepare(
            competed_for or "unclassified",
            cell,
            resolution,
            label_base,
            label=f"{label_base} logo (alternative: {tag})",
        )
        if candidate.asset_id in seen:
            continue  # same bytes as a cell or an earlier alternative: one asset
        seen.add(candidate.asset_id)
        alternatives.append(candidate)

    all_notes = list(notes)
    if resolution is not None:
        all_notes.extend(resolution.notes)
    if not prepared:
        all_notes.append(
            "no cell cleared the available sources (the vendor had no attributable asset and "
            "the ladder found nothing it could stand behind; a variant is never "
            "synthesized), so nothing was ingested"
        )

    # "ok" means at least one rung stood behind what it returned: a vendor cell is keyed
    # retrieval (identity answered by the vendor), and a RESOLVED ladder stood behind its
    # own. A ladder that hesitated (alternate lockups, a non-auto-accept rung) still
    # prepares its cells — the agent may place them — but the status carries the caveat,
    # exactly as it did before the vendor rung existed.
    vendor_backed = any(p.source in {"brandfetch", "logo_dev"} for p in prepared)
    ladder_resolved = resolution is not None and resolution.status == "resolved"
    status = "ok" if prepared and (vendor_backed or ladder_resolved) else "needs_review"

    has_site_winners = any(p.source.startswith("ladder") for p in prepared)
    provider_evidence = [
        p.evidence["vendor_identity"] for p in prepared if p.evidence.get("vendor_identity")
    ]
    site_evidence = (
        resolution.identity.get("evidence", [])
        if resolution is not None and has_site_winners else []
    )
    source_identities = [
        {"cell": p.cell, "source": p.source,
         "identity": p.evidence.get("vendor_identity")
         or (resolution.identity if resolution is not None else {})}
        for p in prepared
    ]
    return LogoFetchOutcome(
        status=status,
        site=site,
        company=company_name,
        prepared=prepared,
        cells={p.cell: p.source for p in prepared},
        alternatives=alternatives,
        identity=(
            {
                "passed": True,
                "evidence": provider_evidence + site_evidence,
                "reason": ("mixed provider and official-site evidence" if has_site_winners
                           else "exact provider identity"),
                "sources": source_identities,
            }
            if vendor_backed else
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


def ladder_candidates(resolution) -> dict:
    """The ladder's four slots folded into 2x2 CANDIDATES. The ladder's
    `light`/`dark` are theme-correct already (its slot names use OUR background
    semantics); what this adds is the completeness split: a symbol-shaped
    primary is a MARK, not a lockup. Nothing is dropped here — the wordmark
    slot competes for the light lockup instead of only backfilling it, and
    several candidates per cell are normal. The arbiter picks."""
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
                # The size the arbiter ranks on.
                "width": slot.candidate.width,
                "height": slot.candidate.height,
                **({"materialized_ink": slot.ink} if slot.ink else {}),
            },
        )

    found: dict = {}

    def propose(name: str, slot, ladder_slot: str) -> None:
        found.setdefault(name, []).append(to_cell(name, slot, ladder_slot))

    for theme in ("light", "dark"):
        slot = resolution.slots.get(theme)
        if slot is None or not slot.body:
            continue
        completeness = "mark" if slot.candidate.lockup == "symbol" else "lockup"
        propose(f"{theme}_{completeness}", slot, theme)

    mark = resolution.slots.get("mark")
    if mark is not None and mark.body:
        propose("dark_mark" if mark.candidate.variant == "dark" else "light_mark", mark, "mark")

    wordmark = resolution.slots.get("wordmark")
    if wordmark is not None and wordmark.body:
        propose("light_lockup", wordmark, "wordmark")
    return found


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
