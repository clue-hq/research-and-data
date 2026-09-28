"""A4 MACHINERY — one stored claim as the source drawer shows it (decision 8).

Every sentence on an accounts screen cites claim ids, and the drawer behind those ids is this
module's whole job: turn a :class:`~clue_core.Claim` into the small, honest card a marketer can
check — where it came from, what it actually said, when it was seen.

Three rules are worth stating out loud, because each of them is a decision rather than a mapping:

* **The quote is the evidence span, and nothing else.** A claim whose span is empty has no quote,
  and only then does the card fall back to ``research_excerpt`` — the *rendered value*, clearly a
  paraphrase of our own making rather than words the source used. The two never appear together,
  so a reader can always tell which one they are looking at.
* **``record`` is "there is no source to open", not "an API said so".** A claim an API returned
  with a url is as openable as a scrape; only a url-less API row (a provider's own database) is a
  record, and the card says so instead of showing a link that goes nowhere.
* **Nothing is fetched.** The favicon is a url the browser resolves, the domain is string work, and
  the dates come from the claim's own columns and value. This module makes no network call.

:func:`evidence_for_ids` is the only database-aware function here, and it reads through the
workspace-scoped claim reader — a cited id belonging to another tenant resolves to nothing rather
than to somebody else's evidence.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.render import render_value_text
from clue_core import Claim, ExtractionMethod
from clue_research.claimstore.quality import inspectable_claims_by_ids

#: The favicon service the drawer's source chip uses. A url, never a fetch.
FAVICON_TEMPLATE = "https://www.google.com/s2/favicons?domain={domain}&sz=32"

#: The value keys a source title may hide under, in the order they are trusted.
TITLE_KEYS: tuple[str, ...] = ("title", "source_title", "page_title")

#: The value keys a publication date may hide under, in the order they are trusted.
PUBLISHED_KEYS: tuple[str, ...] = ("published", "date")

_ISO_DATE_CHARS = 10


def source_domain(url: str | None) -> str | None:
    """The host of ``url``, lower-cased with ``www.`` folded away — ``None`` if there is no host.

    A string that is not a url (no scheme, no authority) has no host, so it has no domain: the
    card shows no chip rather than a chip naming a fragment of prose.
    """
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host.removeprefix("www.") or None


def favicon_url(domain: str | None) -> str | None:
    """The favicon url for ``domain``, or ``None`` when there is no domain to draw one for."""
    if not domain:
        return None
    return FAVICON_TEMPLATE.format(domain=domain)


def _string_entry(value: object, keys: Sequence[str]) -> str | None:
    """The first non-empty string ``keys`` finds in ``value``, when ``value`` is an object."""
    if not isinstance(value, dict):
        return None
    for key in keys:
        entry = value.get(key)
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
    return None


def _published_date(value: object) -> str | None:
    """The value's own publication date, when one of its date keys parses as an ISO date."""
    raw = _string_entry(value, PUBLISHED_KEYS)
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw[:_ISO_DATE_CHARS]).isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class EvidenceRef:
    """One claim's provenance, in the shape the source drawer renders.

    ``research_excerpt`` is present only when ``quote`` is not: a card shows the source's words if
    it has them, and our rendering of the value if it does not — never both.
    """

    claim_id: str
    source_url: str | None
    source_domain: str | None
    favicon_url: str | None
    title: str | None
    quote: str | None
    research_excerpt: str | None
    published_at: str | None
    verified_at: str
    verification_kind: str
    media_timestamp: str | None
    provider: str | None
    outreach_safe: bool
    source_kind: str | None = None
    source_excerpt: str | None = None
    qualifications: tuple[str, ...] = ()
    supporting_claim_ids: tuple[str, ...] = ()
    seller_passages: tuple[dict[str, object], ...] = ()

    def to_wire(self) -> dict[str, object]:
        """The camelCase contract shape. ``researchExcerpt`` appears only when there is one."""
        wire: dict[str, object] = {
            "claimId": self.claim_id,
            "sourceUrl": self.source_url,
            "sourceDomain": self.source_domain,
            "faviconUrl": self.favicon_url,
            "title": self.title,
            "quote": self.quote,
            "publishedAt": self.published_at,
            "verifiedAt": self.verified_at,
            "verificationKind": self.verification_kind,
            "mediaTimestamp": self.media_timestamp,
            "provider": self.provider,
            "outreachSafe": self.outreach_safe,
        }
        if self.source_kind is not None:
            wire.update(
                sourceKind=self.source_kind,
                sourceExcerpt=self.source_excerpt,
                qualifications=list(self.qualifications),
                supportingClaimIds=list(self.supporting_claim_ids),
                sellerPassages=list(self.seller_passages),
            )
        if self.research_excerpt is not None:
            wire["researchExcerpt"] = self.research_excerpt
        return wire


def _evidence_ref(claim: Claim) -> EvidenceRef:
    value = claim.value_json
    domain = source_domain(claim.source_url)
    markers = claim.write_markers or {}
    quality = bool(markers.get("quality_required"))
    kind = (
        (
            "inference"
            if markers.get("claim_kind") == "inference"
            else "primary_quote"
            if claim.source_key in ("research:web_snapshot", "research:transcript")
            and claim.evidence_span
            else "source_excerpt"
            if claim.evidence_span
            else "provider_record"
        )
        if quality
        else None
    )
    media = markers.get("media")
    if (
        quality
        and isinstance(media, dict)
        and claim.entity_type.value == "contact"
        and (media.get("attribution") != "evidence_backed")
    ):
        kind = "source_excerpt"
    quote = (claim.evidence_span or None) if kind in (None, "primary_quote") else None
    support = markers.get("support")
    supports = [s for s in support if isinstance(s, dict)] if isinstance(support, list) else []
    is_record = claim.extraction_method is ExtractionMethod.API and claim.source_url is None
    seen = claim.observed_at or claim.collected_at
    media_timestamp = _string_entry(value, ("media_timestamp",))
    raw_qualifications = markers.get("qualifications")
    qualifications = (
        [str(q) for q in raw_qualifications] if isinstance(raw_qualifications, list) else []
    )
    if quality and isinstance(media, dict):
        raw_segments = media.get("segments")
        segments = raw_segments if isinstance(raw_segments, list) else []
        stamps = [s for s in segments if isinstance(s, dict) and s.get("time_s") is not None]
        media_timestamp = (
            f"{stamps[0]['time_s']}s ({str(stamps[0].get('timing', 'unknown')).replace('_', ' ')})"
            if stamps
            else None
        )
        qualifications.append(
            f"Transcript version {media.get('version_ref')}; "
            f"characters {media.get('start')}–{media.get('end')}."
        )
        if not stamps:
            qualifications.append("Timestamp unavailable.")
    if quality and claim.field_key == "account.open_requisitions" and isinstance(value, list):
        from clue_api.arv2.quality_hiring import current_hiring_state

        qualifications.extend(
            f"Hiring: {current_hiring_state(row)}; observed {row.get('observed_on', 'unknown')}."
            for row in value
            if isinstance(row, dict)
        )
    claim_support_ids = [s.get("claim_ids") for s in supports if s.get("kind") == "claims"]
    return EvidenceRef(
        claim_id=str(claim.id),
        source_url=claim.source_url,
        source_domain=domain,
        favicon_url=favicon_url(domain),
        title=_string_entry(value, TITLE_KEYS),
        quote=quote,
        research_excerpt=None if quote else render_value_text(claim.field_key, value),
        published_at=_published_date(value),
        verified_at=seen.date().isoformat(),
        verification_kind="record" if is_record else "verified",
        media_timestamp=media_timestamp,
        provider=claim.source_key,
        outreach_safe=claim.outreach_safe,
        source_kind=kind,
        source_excerpt=claim.evidence_span if kind == "source_excerpt" else None,
        qualifications=tuple(str(q) for q in qualifications)
        if isinstance(qualifications, list)
        else (),
        supporting_claim_ids=tuple(
            str(id) for ids in claim_support_ids if isinstance(ids, list) for id in ids
        ),
        seller_passages=tuple(
            {
                "documentId": s["document_id"],
                "sha256": s["sha256"],
                "quote": s["quote"],
                "start": s["start"],
                "end": s["end"],
            }
            for s in supports
            if s.get("kind") == "seller_document"
        ),
    )


def resolve_evidence(claims: Sequence[Claim]) -> list[EvidenceRef]:
    """One :class:`EvidenceRef` per claim, ordered by claim id so a page's drawer is stable."""
    return [_evidence_ref(claim) for claim in sorted(claims, key=lambda claim: str(claim.id))]


async def evidence_for_ids(
    conn: AsyncConnection, *, workspace_id: str, claim_ids: Sequence[str]
) -> list[EvidenceRef]:
    """The evidence behind ``claim_ids``, read in this workspace's scope.

    An id that is unknown, superseded, retention-expired or another tenant's simply does not come
    back — the drawer shows the evidence that exists, and never a placeholder for evidence that
    does not.
    """
    if not claim_ids:
        return []
    found = await inspectable_claims_by_ids(
        conn, workspace_id=workspace_id, claim_ids=[uuid.UUID(id) for id in claim_ids]
    )
    return resolve_evidence(list(found.values()))
