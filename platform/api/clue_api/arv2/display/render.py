"""A4 MACHINERY — a claim row as the display layer hands it to the writer.

Three jobs, none of which the prompt should be asked to do:

* :func:`render_value_text` turns a claim's ``value_json`` — a string, a number, the D1 media wrap,
  a list, an object — into one flat line of text. The model reads text, not JSON shapes.
* :func:`dedupe_near_duplicates` folds the near-duplicate rows the store legitimately holds (the
  control test found the same cocktail hobby twice) so the writer does not write the same item
  twice, and so a fold never crosses the ``outreach_safe`` line.
* :func:`alias_table` replaces every claim uuid with an alias ``c1…cN`` and drops the url from
  the payload entirely. Master plan §7: the model cannot type a source it never saw. The alias
  map is how a cited alias is resolved back to its claim when the page is stored.

Nothing here calls a model or touches the database.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from clue_api.arv2.text import normalize_for_match
from clue_core import Claim

#: A single rendered value is a line on a page, not a document. Longer values are clipped rather
#: than dropped: the claim still exists, the writer just sees its head.
MAX_VALUE_CHARS = 1200

_WHITESPACE = re.compile(r"\s+")


def _render(value: object, *, list_sep: str) -> str:
    """One value as flat text. ``list_sep`` is what a list at *this* depth joins its items with."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool | int | float):
        return str(value)
    if isinstance(value, list):
        parts = [_render(item, list_sep=", ") for item in value]
        return list_sep.join(part for part in parts if part)
    if isinstance(value, dict):
        wrapped = value.get("text")
        if isinstance(wrapped, str) and wrapped.strip():
            return wrapped.strip()  # the D1 media wrap: {"text": …, "media_url": …}
        parts = []
        for key in sorted(value):
            rendered = _render(value[key], list_sep=", ")
            if rendered:
                parts.append(f"{key}: {rendered}")
        return "; ".join(parts)
    return str(value)


def render_value_text(field_key: str, value_json: object) -> str:
    """A claim's stored value as the one line of text the writer is given.

    ``field_key`` is part of the signature because rendering is a per-field decision the field
    registry may later want to make; today every field renders the same way.
    """
    del field_key
    text = _WHITESPACE.sub(" ", _render(value_json, list_sep="; ")).strip()
    if len(text) > MAX_VALUE_CHARS:
        return text[:MAX_VALUE_CHARS].rstrip() + "…"
    return text


@dataclass(frozen=True)
class DisplayClaim:
    """One claim, flattened for display. ``source_url`` rides along but never reaches the model."""

    claim_id: str
    field_key: str
    value: str
    quote: str | None
    observed_at: str | None  # ISO date, e.g. "2026-09-02"; the writer renders it in words
    priority: int
    outreach_safe: bool
    subject: str | None
    media_timestamp: str | None
    use_class: str | None
    source_url: str | None  # for the frontend's source chip only — never sent to the model
    entity_id: str
    extraction_method: str
    source_key: str | None
    collected_at: datetime


def display_claim(claim: Claim, *, subject: str | None) -> DisplayClaim:
    """Flatten a stored :class:`~clue_core.Claim` into its display shape."""
    value_json = claim.value_json
    media_timestamp: str | None = None
    if isinstance(value_json, dict):
        raw = value_json.get("media_timestamp")
        if raw is not None:
            media_timestamp = str(raw)
    return DisplayClaim(
        claim_id=str(claim.id),
        field_key=str(claim.field_key),
        value=render_value_text(str(claim.field_key), value_json),
        quote=claim.evidence_span,
        observed_at=claim.observed_at.date().isoformat() if claim.observed_at else None,
        priority=claim.signal_priority,
        outreach_safe=claim.outreach_safe,
        subject=subject,
        media_timestamp=media_timestamp,
        use_class=str(claim.use_class.value) if claim.use_class else None,
        source_url=claim.source_url,
        entity_id=str(claim.entity_id),
        extraction_method=claim.extraction_method.value,
        source_key=claim.source_key,
        collected_at=claim.collected_at,
    )


def _near_duplicates(left: frozenset[str], right: frozenset[str], threshold: float) -> bool:
    """Do two normalised token sets say the same thing?

    Containment first — a short restatement whose every word appears in a longer claim is the
    common shape ("cocktail YouTuber (side hobby)" inside "Cocktail YouTuber, a side hobby,
    creator of the Cocktail Chemistry channel"), and its Jaccard score is low precisely because
    the longer row says *more*. Then Jaccard, for two rows that overlap without either containing
    the other. An empty set matches nothing: a value that normalises away is never a duplicate.
    """
    if not left or not right:
        return False
    if left <= right or right <= left:
        return True
    return len(left & right) / len(left | right) >= threshold


def dedupe_near_duplicates(
    claims: Sequence[DisplayClaim], *, threshold: float = 0.7
) -> tuple[list[DisplayClaim], dict[str, str]]:
    """Fold near-duplicate claims, returning what survives and ``{dropped_id: kept_id}``.

    Grouped by ``(field_key, outreach_safe)``, so a fold can never move a fact across the safety
    line — an unsafe row is never collapsed into the safe row that resembles it, which was exactly
    the upstream defect the control test found. Within a group the row with the longest quote
    wins (it is the one that can be shown), ties broken by the earlier collection and then the
    claim id, so the outcome does not depend on the order the caller read the rows in.
    """
    groups: dict[tuple[str, bool], list[DisplayClaim]] = {}
    for claim in claims:
        groups.setdefault((claim.field_key, claim.outreach_safe), []).append(claim)

    dropped: dict[str, str] = {}
    for group in groups.values():
        ordered = sorted(group, key=lambda c: (-len(c.quote or ""), c.collected_at, c.claim_id))
        kept: list[tuple[DisplayClaim, frozenset[str]]] = []
        for claim in ordered:
            tokens = frozenset(normalize_for_match(claim.value).split())
            winner = next(
                (
                    other
                    for other, other_tokens in kept
                    if _near_duplicates(tokens, other_tokens, threshold)
                ),
                None,
            )
            if winner is None:
                kept.append((claim, tokens))
            else:
                dropped[claim.claim_id] = winner.claim_id
    return [claim for claim in claims if claim.claim_id not in dropped], dropped


def alias_table(
    claims: Sequence[DisplayClaim],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """The claim payload the model receives, plus ``{alias: claim_id}`` to resolve what it cites.

    Ordered by priority, then field key, then collection time, then claim id, so the same claim
    set always yields the same aliases — the payload is part of the cacheable prefix. Keys whose
    value is unknown are omitted rather than sent as ``null``; ``source_url`` is never a key at
    all.
    """
    ordered = sorted(claims, key=lambda c: (c.priority, c.field_key, c.collected_at, c.claim_id))
    rows: list[dict[str, object]] = []
    aliases: dict[str, str] = {}
    for index, claim in enumerate(ordered, start=1):
        alias = f"c{index}"
        aliases[alias] = claim.claim_id
        row: dict[str, object] = {
            "id": alias,
            "fieldKey": claim.field_key,
            "value": claim.value,
        }
        if claim.quote is not None:
            row["quote"] = claim.quote
        if claim.observed_at is not None:
            row["observedAt"] = claim.observed_at
        row["priority"] = claim.priority
        row["outreachSafe"] = claim.outreach_safe
        if claim.subject is not None:
            row["subject"] = claim.subject
        if claim.media_timestamp is not None:
            row["mediaTimestamp"] = claim.media_timestamp
        rows.append(row)
    return rows, aliases
