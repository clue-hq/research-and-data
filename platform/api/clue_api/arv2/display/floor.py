"""A4 MACHINERY — the safety floor over a written section, and the verbatim annotation.

Master plan §7's one non-negotiable: an ``outreach_safe=false`` claim may be cited **only** in
the three restricted sections (``context-only``, ``watch-outs``, ``do-not-mention``). The prompt
says so, the section input already withholds those rows from every other section, and this module
is the mechanical check that neither of those was enough — it reads the draft the model actually
wrote and refuses what it should not have said.

The floor is a *check* and a *repair*, kept apart on purpose. :func:`check_floor` names the
violation; :func:`apply_floor` drops it; :func:`forbidden_aliases_for` turns it into the input of
a regenerate call, so the page layer can choose between rewriting the section and shipping it
without the offending item. Nothing here is advisory: a violated floor never reaches a page.

:func:`verbatim_annotations` is the opposite kind of thing — Appendix A law 6: verbatim-quote
checking is an **annotation**, never a blocker. It counts what it finds and blocks nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from clue_api.arv2.display.gather import SectionInput
from clue_api.arv2.display.render import DisplayClaim
from clue_api.arv2.display.runner import SectionDraft, cited_payloads, claim_ids_of
from clue_api.arv2.text import substring_verdict

#: A quoted span shorter than this many words is punctuation, a single term or an aside — not a
#: quotation anyone would check, and counting it would drown the signal in noise.
MIN_QUOTED_WORDS = 4

#: Below this, an integer in display prose is a count the writer is entitled to state ("three
#: items", "7 offices"); at or above it, it is a figure that must have come from a claim.
MIN_CHECKED_NUMBER = 13

_STRAIGHT_QUOTED = re.compile(r'"([^"]+)"')
_CURLY_QUOTED = re.compile(r"“([^”]+)”")
_INTEGER = re.compile(r"\d[\d,]*")


@dataclass(frozen=True)
class FloorReport:
    """What the floor found: the offending claims, the items carrying them, and the verdict."""

    unsafe_outside_restricted: tuple[str, ...]
    offending_item_ids: tuple[str, ...]
    ok: bool


def _unsafe_ids(section: SectionInput) -> frozenset[str]:
    """The claims of this section the writer was not allowed to use, by claim id.

    A restricted section has none: every row it holds is exactly what it exists to show.
    """
    if section.recipe.restricted:
        return frozenset()
    return frozenset(claim.claim_id for claim in section.claims if claim.outreach_safe is False)


def check_floor(draft: SectionDraft, section: SectionInput) -> FloorReport:
    """Does this draft cite an unsafe claim outside a restricted section?

    Ids the runner already removed (an alias that resolved to nothing, a claim from another
    section) cannot appear here — a draft only ever cites claims of its own section input.
    """
    unsafe = _unsafe_ids(section)
    if not unsafe:
        return FloorReport((), (), True)

    violations: list[str] = []
    offending_items: list[str] = []

    for sentence in draft.intro:
        violations.extend(claim_id for claim_id in claim_ids_of(sentence) if claim_id in unsafe)
    for item in draft.items:
        item_violations = [
            claim_id
            for payload in cited_payloads(item)
            for claim_id in claim_ids_of(payload)
            if claim_id in unsafe
        ]
        if item_violations:
            violations.extend(item_violations)
            offending_items.append(str(item.get("id", "")))

    ordered = tuple(dict.fromkeys(violations))
    return FloorReport(ordered, tuple(offending_items), not ordered)


def apply_floor(draft: SectionDraft, report: FloorReport) -> SectionDraft:
    """The draft with every floor violation removed, and the repair recorded in ``checks``.

    Dropping the whole item, rather than the offending sentence, is deliberate: an item's h2 and
    its remaining sentences are written *about* the fact it cites, so a body with the unsafe
    sentence cut out still points at it. An intro sentence is independent prose, so only the
    sentence goes.
    """
    unsafe = frozenset(report.unsafe_outside_restricted)
    offending = frozenset(report.offending_item_ids)

    intro = [
        sentence
        for sentence in draft.intro
        if not any(claim_id in unsafe for claim_id in claim_ids_of(sentence))
    ]
    items = [item for item in draft.items if str(item.get("id", "")) not in offending]

    cited: list[str] = []
    for sentence in intro:
        cited.extend(claim_ids_of(sentence))
    for item in items:
        for payload in cited_payloads(item):
            cited.extend(claim_ids_of(payload))

    checks = dict(draft.checks)
    checks["floor_dropped_items"] = len(draft.items) - len(items)
    return replace(
        draft,
        intro=intro,
        items=items,
        cited_claim_ids=list(dict.fromkeys(cited)),
        checks=checks,
    )


def forbidden_aliases_for(report: FloorReport, aliases: Mapping[str, str]) -> list[str]:
    """The aliases a regenerate call must forbid, from the aliases the draft was written with.

    The map is the draft's own ``aliases`` (alias → claim id): the rewrite must be sent with the
    *same* section input, or the aliases named here would point at different claims.
    """
    unsafe = frozenset(report.unsafe_outside_restricted)
    return sorted(alias for alias, claim_id in aliases.items() if claim_id in unsafe)


# -- the verbatim annotation ----------------------------------------------------------------------


def _quoted_spans(text: str) -> list[str]:
    """Every quoted span of at least :data:`MIN_QUOTED_WORDS` words, straight or curly quotes."""
    spans = _STRAIGHT_QUOTED.findall(text) + _CURLY_QUOTED.findall(text)
    return [span for span in spans if len(span.split()) >= MIN_QUOTED_WORDS]


def _corpus(claim_ids: Sequence[str], claims: Mapping[str, DisplayClaim]) -> str:
    """Everything the cited claims actually say — their values and their evidence spans."""
    parts: list[str] = []
    for claim_id in claim_ids:
        claim = claims.get(claim_id)
        if claim is None:
            continue
        parts.append(claim.value)
        if claim.quote:
            parts.append(claim.quote)
    return " ".join(parts)


def _digits(text: str) -> str:
    return text.replace(",", "")


def _number_counts(text: str, corpus: str) -> tuple[int, int]:
    """``(checked, missing)`` — integers at or above the threshold, and how many are unsupported."""
    haystack = _digits(corpus)
    checked = missing = 0
    for raw in _INTEGER.findall(text):
        digits = _digits(raw)
        if not digits.isdigit() or int(digits) < MIN_CHECKED_NUMBER:
            continue
        checked += 1
        if not re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", haystack):
            missing += 1
    return checked, missing


def verbatim_annotations(draft: SectionDraft, section: SectionInput) -> dict[str, int]:
    """Count what the draft quotes and what it numbers, against the claims it cites.

    Law 6 makes this an annotation, so it answers a question rather than passing a verdict: of the
    spans this section put inside quotation marks, how many are really in the claims behind them,
    and of the figures it stated, how many appear in those claims at all. Pure and cheap; the page
    layer calls it only when ``settings.evidence_verbatim_check`` is on.

    The corpus is per *unit*: an item is checked against the claims that item cites, an intro
    sentence against the claims that sentence cites. A quote can therefore never be excused by a
    claim from somewhere else on the page.
    """
    claims = {claim.claim_id: claim for claim in section.claims}
    counts = {
        "quotes": 0,
        "exact": 0,
        "partial": 0,
        "not_found": 0,
        "numbers": 0,
        "numbers_missing": 0,
    }

    def _check(texts: Sequence[str], cited: Sequence[str]) -> None:
        corpus = _corpus(cited, claims)
        for text in texts:
            for span in _quoted_spans(text):
                counts["quotes"] += 1
                verdict = substring_verdict(span, corpus)
                counts["exact" if verdict == "EXACT" else verdict.lower()] += 1
            checked, missing = _number_counts(text, corpus)
            counts["numbers"] += checked
            counts["numbers_missing"] += missing

    for sentence in draft.intro:
        _check([str(sentence.get("text", ""))], claim_ids_of(sentence))

    for item in draft.items:
        payloads = cited_payloads(item)
        cited = [claim_id for payload in payloads for claim_id in claim_ids_of(payload)]
        texts = [str(item.get("h2", ""))]
        body = item.get("body")
        if isinstance(body, list):
            texts.extend(
                str(sentence.get("text", "")) for sentence in body if isinstance(sentence, Mapping)
            )
        send_line = item.get("sendLine")
        if isinstance(send_line, Mapping):
            texts.append(str(send_line.get("text", "")))
        _check(texts, cited)

    return counts
