"""Ask one gate, then hold the answer to its evidence (spec §3).

The verifier is two halves. The first half is what we *send*: a system prompt that is the same
paragraph for every call, a question built entirely out of the gate's own words, and an output
schema with exactly five keys. The second half is what we *trust* — :func:`apply_guards`, which
takes the Answer object plus the citations Exa says it read and refuses anything the sources do
not carry.

Three guards, one per error kind the proof-of-concept run actually produced, and nothing else:

1. **Quote on the page.** The quoted sentence must appear in the text of a citation, compared
   after :func:`normalise` so typography and wrapping cannot decide a fact. A quote nobody's page
   contains is a quote the model wrote.
2. **Right company.** The page carrying the quote must be on the company's own domain, or name the
   company in its text — a job posting for *infinIT* is not evidence about *INFI*.
3. **Arithmetic is code's.** When the gate states a window, the evidence date is subtracted here.
   The model called a 2023 round "within 24 months"; code does not.

And one rule the guards enforce rather than request: **no source found is `unclear`, never
`fail`.** A gate we could not evidence is an open question for the human, not a rejection — and
R4's disposition vocabulary has no `fail` for exactly that reason.

Pure: an answer and its citations in, a verdict out. No provider call, no database, no clock of
its own (``today`` is passed in, so a replay of a stored answer grades the same way twice).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from clue_api.arv2.discovery_brief import Gate
from clue_api.arv2.exa_client import ExaCitation
from clue_research.identity.normalize import registrable_domain

__all__ = [
    "GUARDS",
    "OUTPUT_SCHEMA",
    "QUOTE_PREFIX_CHARS",
    "VERDICTS",
    "WEBSITE_SCHEMA",
    "GateVerdict",
    "apply_guards",
    "disposition",
    "fit_score",
    "gate_question",
    "months_between",
    "normalise",
    "system_prompt",
    "website_question",
]

#: The only three answers a gate has. `fail` means a source contradicted the test; it is not the
#: answer for "we found nothing" (that is `unclear`).
VERDICTS = ("pass", "fail", "unclear")

#: Every guard label a verdict can carry. `ok` means the model's answer survived unchanged.
GUARDS = ("ok", "quote_not_on_page", "wrong_company", "outside_window", "no_source", "malformed")

#: How much of the quote must be found on the page. A prefix, not the whole quote: models trim and
#: re-join long passages, and a paragraph-length quote would fail on an ellipsis the page never had.
QUOTE_PREFIX_CHARS = 60

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

#: Typography a page and a model spell differently. Folded before anything is compared.
_TYPOGRAPHIC = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
    }
)

_KEEPABLE = re.compile(r"[^a-z0-9' -]")

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


def gate_question(company_name: str, url: str, gate: Gate) -> str:
    """The gate, asked in the document's own words — nothing here paraphrases the ICP."""
    return (
        f"Company: {company_name} (website {url}). "
        f"Test to verify: {gate.rule}. "
        f"How it is tested: {gate.test} "
        "Decide pass, fail or unclear for THIS company today, citing the freshest relevant source."
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


def normalise(text: str) -> str:
    """Fold a page's text and a model's quote onto common ground before comparing them.

    NFKC, lower case, typographic quotes and dashes to ASCII, every other non-alphanumeric to a
    space, whitespace collapsed. What survives is the words — which is all a quote check should
    turn on, since a page's line wrapping and a model's smart quotes are not facts.
    """
    folded = unicodedata.normalize("NFKC", text or "").translate(_TYPOGRAPHIC).lower()
    return " ".join(_KEEPABLE.sub(" ", folded).split())


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


def _names_company(company_name: str, text: str | None) -> bool:
    """Whether ``text`` names the company as a whole word run, not as a prefix of another name.

    A substring test would read "infinIT" as naming "INFI" — which is precisely the confusion the
    right-company guard exists to catch — so both sides are padded and compared on word edges.
    """
    name = normalise(company_name)
    if not name:
        return False
    return f" {name} " in f" {normalise(text or '')} "


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
    citations: Sequence[ExaCitation],
    company_domain: str,
    company_name: str,
    today: date,
) -> GateVerdict:
    """Grade one Answer response against the sources behind it.

    The guards run in order and the first one that fires decides, because each later guard assumes
    the earlier ones held: there is no point asking whether the right company appears on a page
    that does not carry the quote.
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

    # (4) Guard one: the quote must be on a page Exa says it read.
    needle = normalise(quote)[:QUOTE_PREFIX_CHARS]
    supporting = [
        citation for citation in citations if needle and needle in normalise(citation.text or "")
    ]
    if not supporting:
        return verdict_of("unclear", "quote_not_on_page")

    # (5) Guard two: that page is the company's own, or it names the company.
    domain = registrable_domain(company_domain) or company_domain.strip().lower()
    if not any(
        registrable_domain(citation.url) == domain or _names_company(company_name, citation.text)
        for citation in supporting
    ):
        return verdict_of("unclear", "wrong_company")

    # (6) Guard three: when the gate names a window, code does the subtraction. A date it cannot
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
