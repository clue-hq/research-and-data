"""Fetch a target account's real logo family, mid-turn, for either lane.

Both design substrates expose this as a `fetch_logo` tool. The lanes differ
only in how a registered asset reaches their document — the WebDoc op key is
``record``, the scene's is ``asset`` — so everything up to that point lives
here: normalize the input, fetch through the shared SSRF/size guard, run the
ladder, and shape one ingest call per resolved slot.

Static tier only. A Playwright launch costs about thirty seconds, which is more
than a turn can spend, so a page that renders its header in JavaScript comes
back honestly empty rather than slowly right.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JsonObject = Dict[str, Any]

# Tags let a later pass tell a fetched account logo from the workspace's own
# brand assets without re-deriving it from provenance.
LOGO_TAGS = ("target-account", "logo-ladder")

# The slots an agent can place, in the order they are reported.
SLOT_NAMES = ("light", "dark", "mark", "wordmark")


@dataclass
class PreparedLogo:
    """One resolved slot, shaped for `core.ingest_asset`."""

    slot: str
    asset_id: str
    label: str
    body: bytes
    content_type: str
    provenance: JsonObject
    source: JsonObject
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
            "source": self.source,
            "tags": list(LOGO_TAGS),
            "raise_on_error": False,
        }


@dataclass
class LogoFetchOutcome:
    status: str
    site: str
    company: Optional[str]
    prepared: List[PreparedLogo] = field(default_factory=list)
    identity: JsonObject = field(default_factory=dict)
    lockup_completeness: str = "unknown"
    notes: List[str] = field(default_factory=list)
    candidates: List[JsonObject] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return not self.prepared


def fetch_logo_family(
    url_or_domain: str, *, company_name: Optional[str] = None
) -> LogoFetchOutcome:
    """Blocking wrapper around the ladder's async driver.

    Raises `CaptureError` for a blocked or unreachable site; the caller turns
    that into a typed tool error.
    """
    from lumen_ingestion import logo_ladder

    site = logo_ladder.normalize_site_url(url_or_domain)
    resolution = asyncio.run(
        logo_ladder.fetch_logo_family(site, company_name=company_name)
    )
    return _prepare(resolution, site, company_name)


def _prepare(resolution, site: str, company_name: Optional[str]) -> LogoFetchOutcome:
    from lumen_ingestion import logo_ladder

    host = logo_ladder.host_of(site)
    label_base = company_name or logo_ladder.registrable_domain(host) or host

    prepared: List[PreparedLogo] = []
    for slot_name in SLOT_NAMES:
        slot = resolution.slots.get(slot_name)
        if slot is None or not slot.body:
            continue
        import hashlib

        digest = hashlib.sha256(slot.body).hexdigest()
        prepared.append(
            PreparedLogo(
                slot=slot_name,
                # Content-addressed, so fetching the same brand twice in a run
                # re-registers the same id instead of duplicating the asset.
                asset_id=f"asset_ing_{digest[:16]}",
                label=f"{label_base} logo ({slot_name})",
                body=slot.body,
                content_type=slot.content_type,
                provenance={
                    "created_by": "logo_ladder",
                    "source_label": "website",
                    "confidence": resolution.confidence,
                },
                source={
                    "kind": "website",
                    "url": slot.candidate.url,
                    "captured_at": _now(),
                },
                evidence={
                    "slot": slot_name,
                    "url": slot.candidate.url,
                    "rung": slot.candidate.rung,
                    "provenance": slot.provenance,
                    "lockup": slot.candidate.lockup,
                    "basis": slot.basis[:200],
                    **({"materialized_ink": slot.ink} if slot.ink else {}),
                },
            )
        )

    notes = list(resolution.notes)
    if not prepared:
        notes.append(
            "no asset cleared both guards (the asset must carry this brand's own name "
            "evidence, and a variant is never synthesized), so nothing was ingested"
        )

    return LogoFetchOutcome(
        status="ok" if prepared and resolution.status == "resolved" else "needs_review",
        site=site,
        company=company_name,
        prepared=prepared,
        identity={
            "passed": resolution.identity.get("passed"),
            "evidence": resolution.identity.get("evidence", [])[:3],
            "reason": resolution.identity.get("reason"),
        },
        lockup_completeness=resolution.lockup_completeness,
        notes=notes,
        candidates=[c.summary() for c in resolution.ranked[:6]],
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
        "ranked_candidates": outcome.candidates,
        "what_to_do": (
            "Tell the user the logo could not be confirmed and ask them for the file "
            "or the exact URL. Do not draw, recolor, or approximate a logo."
        ),
    }
