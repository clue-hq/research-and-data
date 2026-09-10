"""Compile a confirmed ICP document into the discovery brief (spec §2–§3).

R4's principle is that **the ICP document is the program**: the long list's query, the criteria
Websets filters on, and the tests the verifier asks each candidate are all read out of the
document a human confirmed. So this module knows the *shape* of a hard gate — a key, a rule, a
test, and possibly a window stated in months — and nothing whatever about any particular gate. It
contains no vertical, no round name, no job title and no geography; the only pattern it matches
over the document's prose is a count of months, because a window is arithmetic and arithmetic is
code's job (spec §3, guard 3).

Every gate in the document is verified; the document's ``exclusions`` are compiled and, in R4,
asked of nobody — see :attr:`DiscoveryBrief.exclusions`. Only the gates the caller names become
**webset criteria**, because the provider takes at most :data:`MAX_CRITERIA` of them — the rest
are asked by the verifier afterwards, where a gate costs an Answer call instead of a place in the
long list's filter. If a criteria slot is left over, the buyer sentence from the body fills it, so
the webset still carries the ICP's own description of who we sell to.

Nothing here touches a database, a provider or an agent: a document in, a brief out.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "MAX_CRITERIA",
    "QUERY_MAX_CHARS",
    "BriefError",
    "DiscoveryBrief",
    "Gate",
    "buyer_sentence",
    "compile_brief",
    "parse_window_months",
]

#: How many criteria the webset takes. A fourth is refused, never dropped — see
#: :func:`compile_brief`.
MAX_CRITERIA = 3

#: The long-list query is a sentence, not an essay; a runaway paragraph is cut here.
QUERY_MAX_CHARS = 600

#: The one regular expression this module runs over the document's prose. A window is arithmetic.
_WINDOW = re.compile(r"(\d+)\s*months")

#: A blank line — possibly carrying whitespace — is what separates two paragraphs of a body.
_PARAGRAPH = re.compile(r"\n\s*\n")


class BriefError(ValueError):
    """The confirmed document cannot be compiled into a brief, and says which part is wrong.

    Raised rather than defaulted: a discovery run whose gates came out wrong would spend real
    money asking the wrong questions, and the human who confirmed the document is the only one who
    can fix it.
    """


@dataclass(frozen=True)
class Gate:
    """One hard gate, exactly as the ICP document states it.

    ``rule`` and ``test`` are the document's own words — they travel verbatim into the webset
    criterion and into the verifier's question, so the human reading a verdict recognises the
    sentence they confirmed. ``window_months`` is the one thing read *out* of those words
    (:func:`parse_window_months`), because the model proved unable to do the subtraction.
    """

    key: str
    rule: str
    test: str
    window_months: int | None


@dataclass(frozen=True)
class DiscoveryBrief:
    """Everything one discovery run asks, compiled from one document version."""

    query: str
    criteria: tuple[str, ...]
    criteria_gate_keys: tuple[str, ...]
    gates: tuple[Gate, ...]
    #: **Reserved — R4 compiles the document's exclusions but asks none of them.** Spec §3's "one
    #: ``POST /answer`` per hard gate (and per page-answerable exclusion)" is implemented for the
    #: gates only: the driver iterates :attr:`gates` and nothing reads this. Asking each
    #: page-answerable exclusion (one Answer per exclusion per candidate) and deciding how an
    #: exclusion scores against ``fit = passes / gates`` is a **founder decision**, recorded as a
    #: follow-up (final review I3) rather than guessed here — the cost is real (the Clue ICP states
    #: eight exclusions, so about eight more Answer calls, roughly $0.04, per company) and a
    #: disqualifier that silently halves a fit is worse than one that is not yet asked. Compiled
    #: rather than dropped so the field is ready for the pass that will ask them.
    exclusions: tuple[str, ...]


def parse_window_months(*texts: str) -> int | None:
    """The first month count stated across a gate's rule and test, or ``None`` for no window.

    ``"announced within the last 36 months"`` → ``36``. A gate with no window ("listed today")
    returns ``None`` and its verdict is never date-checked.
    """
    for text in texts:
        match = _WINDOW.search(text or "")
        if match is not None:
            return int(match.group(1))
    return None


def buyer_sentence(body: str) -> str:
    """The document body's first real paragraph — its description of who we sell to.

    Headings are skipped, the paragraph's lines are joined on single spaces (a document is
    hard-wrapped; a query is not), and the result is cut at :data:`QUERY_MAX_CHARS`.
    """
    for block in _PARAGRAPH.split(body):
        lines = [line.strip() for line in block.splitlines()]
        prose = [line for line in lines if line and not line.startswith("#")]
        if prose:
            return " ".join(prose)[:QUERY_MAX_CHARS]
    return ""


def _gate_from(entry: Any) -> Gate:
    if not isinstance(entry, Mapping):
        raise BriefError(f"hard_gates entry is not a mapping: {entry!r}")
    key = str(entry.get("key") or "").strip()
    rule = str(entry.get("rule") or "").strip()
    test = str(entry.get("test") or "").strip()
    if not key:
        raise BriefError(f"hard gate has no key: {entry!r}")
    if not rule:
        raise BriefError(f"hard gate {key!r} has no rule")
    return Gate(key=key, rule=rule, test=test, window_months=parse_window_months(rule, test))


def compile_brief(
    front: Mapping[str, Any], body: str, *, criteria_gate_keys: Sequence[str]
) -> DiscoveryBrief:
    """Turn a confirmed ICP document into the brief one discovery run executes.

    ``front`` is the document's parsed front matter and ``body`` its markdown.
    ``criteria_gate_keys`` names which gates become webset criteria, in the order they should
    appear.

    Raises :class:`BriefError` when the document declares no ``hard_gates``, when a named criteria
    key is not one of them, or when more than :data:`MAX_CRITERIA` keys are named — the last of
    which is refused rather than truncated, so a criterion never goes missing in silence.
    """
    raw_gates = front.get("hard_gates")
    if not isinstance(raw_gates, Sequence) or isinstance(raw_gates, str) or not raw_gates:
        raise BriefError("icp has no hard_gates")
    gates = tuple(_gate_from(entry) for entry in raw_gates)

    if len(criteria_gate_keys) > MAX_CRITERIA:
        raise BriefError(
            f"at most {MAX_CRITERIA} criteria gate keys, got {len(criteria_gate_keys)}: "
            f"{list(criteria_gate_keys)}"
        )
    by_key = {gate.key: gate for gate in gates}
    chosen: list[Gate] = []
    for key in criteria_gate_keys:
        gate = by_key.get(key)
        if gate is None:
            raise BriefError(f"unknown criteria gate key {key!r}; document has {sorted(by_key)}")
        chosen.append(gate)

    query = buyer_sentence(body)
    criteria = [gate.rule for gate in chosen]
    if len(criteria) < MAX_CRITERIA and query:
        criteria.append(query)

    exclusions = tuple(
        str(item).strip() for item in (front.get("exclusions") or ()) if str(item).strip()
    )
    return DiscoveryBrief(
        query=query,
        criteria=tuple(criteria),
        criteria_gate_keys=tuple(gate.key for gate in chosen),
        gates=gates,
        exclusions=exclusions,
    )
