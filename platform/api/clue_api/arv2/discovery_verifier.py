"""Ask one gate, then hold the answer to its evidence (spec §3).

The verifier is two halves. The first half is what we *send*: a system prompt that is the same
paragraph for every call, a question built entirely out of the gate's own words, and an output
schema with exactly five keys. The second half is what we *trust* — :func:`apply_guards`, which
takes the Answer object and holds it to what code can check.

One guard, for the error kind the proof-of-concept run produced that code can settle:

1. **Arithmetic is code's.** When the gate states a window, the evidence date is subtracted here.
   The model called a 2023 round "within 24 months"; code does not.

(The quote-on-the-page and right-company guards were removed by founder ruling 2026-10-01: on the
live hotel-operators run they turned correct verdicts to `unclear` — a renamed company's LinkedIn
page, a job board, a news article that shortened the company's name — and the model's own
verdict is trusted instead. Rows written before then may still carry `quote_not_on_page` or
`wrong_company` in `guard`.)

And one rule the guards enforce rather than request: **no source found is `unclear`, never
`fail`.** A gate we could not evidence is an open question for the human, not a rejection — and
R4's disposition vocabulary has no `fail` for exactly that reason.

Pure: an answer in, a verdict out. No provider call, no database, no clock of
its own (``today`` is passed in, so a replay of a stored answer grades the same way twice).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from clue_api.arv2.discovery_brief import Gate

__all__ = [
    "GUARDS",
    "MAIN_BUSINESS_CLAUSE",
    "OUTPUT_SCHEMA",
    "VERDICTS",
    "WEBSITE_SCHEMA",
    "GateVerdict",
    "apply_guards",
    "disposition",
    "fit_score",
    "gate_question",
    "months_between",
    "system_prompt",
    "website_question",
]

#: The only three answers a gate has. `fail` means a source contradicted the test; it is not the
#: answer for "we found nothing" (that is `unclear`).
VERDICTS = ("pass", "fail", "unclear")

#: Every guard label a verdict can carry. `ok` means the model's answer survived unchanged.
GUARDS = ("ok", "outside_window", "no_source", "malformed")

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "reasoning", "evidence_quote", "evidence_url", "evidence_date"],
    "additionalProperties": False,
    "properties": {
        "verdict": {
            "type": "string",
            "enum": list(VERDICTS),
            "description": (
                "pass when a source states the fact, fail when a source contradicts the test, "
                "unclear otherwise — including when no source answers it"
            ),
        },
        "reasoning": {
            "type": "string",
            "description": "one or two sentences: which source decided it, and why",
        },
        "evidence_quote": {
            "type": "string",
            "description": (
                "the sentence from the cited source that decides it, copied verbatim; empty when "
                "the verdict is unclear for want of a source"
            ),
        },
        "evidence_url": {
            "type": "string",
            "description": "the URL of the source the quote was copied from",
        },
        "evidence_date": {
            "type": "string",
            "description": (
                "the date the source states for the fact, as YYYY-MM-DD; empty if undated"
            ),
        },
    },
}

WEBSITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["website_domain", "evidence_url"],
    "additionalProperties": False,
    "properties": {
        "website_domain": {
            "type": "string",
            "description": "the registrable domain of the company's own website, e.g. probook.ai",
        },
        "evidence_url": {"type": "string"},
    },
}

_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m")


def system_prompt(today: date) -> str:
    """The one paragraph every Answer call is given, spec §3.

    Stated once, here, so that every gate of every company is judged by the same instructions and
    a stored answer can be read back against the words that produced it.
    """
    return (
        f"Today is {today.isoformat()}. Use only what the sources you cite actually say, never "
        "what you remember or infer; the most recent dated announcement of an event is the "
        "authority on the current state of that fact and older announcements are history, so cite "
        "the freshest relevant source; profile pages (LinkedIn, Crunchbase, CB Insights, Tracxn) "
        "rank below the company's own pages and dated news; never confuse the company with a "
        "same-name company on a different website; answer pass only when a source states the "
        "fact, fail only when a source contradicts the test, and unclear in every other case, "
        "including when you find no source at all; and copy the quote verbatim from the source "
        "you cite."
    )


#: Added to the question of a gate that excludes when it passes (founder ruling 2026-10-01). Asked
#: "does it do this?", the verifier excluded hotel operators for a side business (a software
#: subsidiary, a rentals line) and on a look-alike company's site; asked about the main business,
#: it kept all five and still excluded every real vendor (replay 2026-10-01, 15 of 15).
MAIN_BUSINESS_CLAUSE = (
    "This is an exclusion test. Answer pass only if this is the company's main business: what its "
    "own website presents it as, and what most of its revenue comes from. A side business, a "
    "subsidiary, one product line or a service it also offers does not make it pass; when the "
    "company's main business is something else, answer fail. "
)


def gate_question(company_name: str, url: str, gate: Gate) -> str:
    """The gate, asked in the document's own words — nothing here paraphrases the ICP."""
    return (
        f"Company: {company_name} (website {url}). "
        f"Test to verify: {gate.rule}. "
        f"How it is tested: {gate.test} "
        + (MAIN_BUSINESS_CLAUSE if gate.main_business else "")
        + "Decide pass, fail or unclear for THIS company today, "
        "citing the freshest relevant source."
    )


def website_question(company_name: str, websets_url: str) -> str:
    """Ask the company's own website, because the long list's domain is sometimes the wrong one.

    Websets returned ``probook.com`` for a company whose site is ``probook.ai``; the announcement's
    domain wins, and everything downstream — the dedupe, the right-company guard — keys on it.
    """
    return (
        f"Company: {company_name} (the long list gave the website {websets_url}). "
        "What is the registrable domain of this company's own website, as stated on its funding "
        "announcement or its LinkedIn page? Answer with that domain and the URL of the page that "
        "states it."
    )


def months_between(a: date, b: date) -> int:
    """Whole calendar months from ``a`` to ``b`` — the subtraction the model kept getting wrong."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def _parse_evidence_date(raw: str) -> date | None:
    """``YYYY-MM-DD`` or ``YYYY-MM`` (read as the first of the month), else ``None``."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class GateVerdict:
    """One gate's answer after the guards, and what the model said before them.

    ``model_verdict`` is kept beside ``verdict`` on purpose: the point of the experiment is to
    measure how often the model's answer had to be overturned, and a row that only stored the
    final verdict could not tell you.
    """

    gate_key: str
    verdict: str
    reasoning: str
    evidence_quote: str
    evidence_url: str
    evidence_date: str
    guard: str
    model_verdict: str

    def as_json(self) -> dict[str, Any]:
        """The shape ``arv2_discovery_candidate.verdicts_json`` stores."""
        return {
            "gate_key": self.gate_key,
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "evidence_quote": self.evidence_quote,
            "evidence_url": self.evidence_url,
            "evidence_date": self.evidence_date,
            "guard": self.guard,
            "model_verdict": self.model_verdict,
        }


def apply_guards(
    *,
    gate: Gate,
    answer: object,
    today: date,
) -> GateVerdict:
    """Grade one Answer response: the model's verdict, held to a source and to a gate's window.

    The checks run in order and the first one that fires decides.
    """
    if not isinstance(answer, Mapping):
        return GateVerdict(gate.key, "unclear", "", "", "", "", "malformed", "")

    model_verdict = str(answer.get("verdict") or "").strip().lower()
    reasoning = str(answer.get("reasoning") or "").strip()
    quote = str(answer.get("evidence_quote") or "").strip()
    url = str(answer.get("evidence_url") or "").strip()
    evidence_date = str(answer.get("evidence_date") or "").strip()

    def verdict_of(final: str, guard: str) -> GateVerdict:
        return GateVerdict(
            gate_key=gate.key,
            verdict=final,
            reasoning=reasoning,
            evidence_quote=quote,
            evidence_url=url,
            evidence_date=evidence_date,
            guard=guard,
            model_verdict=model_verdict,
        )

    # (1) Not an object, or not one of the three words: we did not get an answer.
    if model_verdict not in VERDICTS:
        return verdict_of("unclear", "malformed")

    # (2) The model already declined. Nothing to check, nothing to overturn.
    if model_verdict == "unclear":
        return verdict_of("unclear", "ok")

    # (3) A decision with no source is no decision — and it is never a `fail`.
    if not quote or not url:
        return verdict_of("unclear", "no_source")

    # (4) The one guard: when the gate names a window, code does the subtraction. A date it cannot
    # read leaves the verdict alone — an unreadable date is not evidence against a sourced fact.
    if gate.window_months is not None and model_verdict == "pass":
        when = _parse_evidence_date(evidence_date)
        if when is not None and months_between(when, today) > gate.window_months:
            return verdict_of("fail", "outside_window")

    return verdict_of(model_verdict, "ok")


def fit_score(verdicts: Sequence[GateVerdict]) -> float:
    """``passes / gates``, an unclear counted as half a pass (spec §3, rulings 4 and 5)."""
    if not verdicts:
        return 0.0
    earned = sum(
        1.0 if v.verdict == "pass" else 0.5 if v.verdict == "unclear" else 0.0 for v in verdicts
    )
    return earned / len(verdicts)


def disposition(verdicts: Sequence[GateVerdict]) -> str:
    """What the candidate turned out to be: ``pass``, ``partial`` or ``unclear``.

    There is deliberately no ``fail``. A candidate on the list is one the human is being shown, and
    a failed gate is a reason to read the verdict — never a reason to hide the row (ruling 1′).
    """
    outcomes = [v.verdict for v in verdicts]
    if outcomes and all(outcome == "pass" for outcome in outcomes):
        return "pass"
    if "fail" in outcomes:
        return "partial"
    return "unclear"
