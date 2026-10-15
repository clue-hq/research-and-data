"""Exa — search, contents and deep reasoning, over plain HTTP through the one wrapper.

Exa is the ARV2 lane's open-web instrument. It does three separate jobs, and conflating them is
how a research run quietly gets expensive: :meth:`ExaClient.search` finds *candidate URLs* for a
cent; :meth:`ExaClient.contents` reads pages Exa has already indexed for a fifth of a cent each;
:meth:`ExaClient.deep_reasoning` spends minutes and about five cents running an agentic research
pass whose answer is shaped by a caller-supplied ``outputSchema``.

Three rules this module exists to keep:

* **Only what the caller asked for goes on the wire.** ``includeDomains``, ``includeText``, the
  published-date bounds, ``category``, ``livecrawl`` and ``highlights`` are absent from the body
  unless the caller passed them. A module-level default domain list would silently narrow every
  search in the lane to whatever a previous caller happened to need.
* **The provider's own metering is the cost.** :func:`exa_cost_reader` reads ``costDollars.total``
  and ``requestId`` off the body and returns the per-component breakdown in the reading's
  ``extras``, so the ledger row carries what Exa charged rather than the estimate that reserved
  it (Appendix A law 1).
* **A deep-reasoning call can fail silently** — it answers 200 with a handful of results, a
  near-zero cost and a stub of a report. Appendix A law 4's guard recognises that signature and
  buys exactly one retry; see :func:`is_thin_deep_response`.

Nothing here opens a socket: every call is a :class:`~clue_api.arv2.calls.CallSpec` handed to the
:class:`~clue_api.arv2.calls.ProviderCaller` the client was constructed with.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import SecretStr

from clue_api.arv2.calls import (
    DEFAULT_MAX_ATTEMPTS,
    CallCost,
    CallResult,
    CallSpec,
    CostReading,
    ProviderCaller,
    SpendEstimate,
)
from clue_api.arv2.transport import HttpRequest, HttpResponse, json_request
from clue_obs import get_logger
from clue_obs.langfuse import observation

#: Exa's API root. A parameter on the client rather than a constant in a body builder, so a
#: proxy or a regional endpoint is a call-site decision.
EXA_BASE_URL = "https://api.exa.ai"

PROVIDER = "exa"

#: Pre-spend estimates (Appendix A law 2). These reserve the spend *before* the wire; the real
#: number replaces them on the result row as soon as :func:`exa_cost_reader` has read it.
SEARCH_ESTIMATE_USD = Decimal("0.01")
CONTENTS_ESTIMATE_USD_PER_URL = Decimal("0.002")
DEEP_REASONING_ESTIMATE_USD = Decimal("0.05")
#: One ``/answer`` call — a search plus one model pass over what it found. The R4 discovery
#: experiment metered them at roughly half a cent each; a cent is the honest reservation.
ANSWER_ESTIMATE_USD = Decimal("0.01")

#: Appendix A law 4's silent-fail signature, measured on the proof-of-concept: a deep-reasoning
#: call that "succeeded" with nine or fewer results **and** a cost that never left the floor did
#: not actually run the research pass. For a report-shaped schema, a sub-3000-character answer is
#: the same failure seen from the other end.
THIN_MAX_RESULTS = 9
THIN_MAX_COST_USD = Decimal("0.016")
THIN_MIN_REPORT_CHARS = 3000

#: A deep-reasoning call runs an agentic research pass: it is charged per call, is given up to
#: 1200 s, and law 4 may pay for a second one on top. Four attempts is therefore a worst case of
#: ~80 minutes and four charges for one dossier — and on top of that the law-4 retry can double
#: it. Two attempts still rides out a single transient failure without that tail.
DEEP_REASONING_MAX_ATTEMPTS = 2

#: Exa Agent (``/agent/runs``) — the async deep-research surface. Fixed efforts have a fixed
#: per-request price (Exa Agent guide, read 2026-09-07); ``auto``/``max`` are metered to a default
#: cap, which is the honest pre-spend reservation for them.
EXA_AGENT_EFFORTS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh", "auto", "max")
AGENT_EFFORT_ESTIMATE_USD: Mapping[str, Decimal] = {
    "minimal": Decimal("0.012"),
    "low": Decimal("0.025"),
    "medium": Decimal("0.10"),
    "high": Decimal("0.50"),
    "xhigh": Decimal("1.00"),
    "auto": Decimal("5"),
    "max": Decimal("20"),
}
AGENT_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
#: One create or one poll is a short HTTP exchange; the run itself takes minutes and is waited
#: for by polling, so neither leg needs the deep-reasoning budget.
AGENT_LEG_TIMEOUT_S = 60.0

#: Exa's livecrawl modes. Absent from the body means "serve the indexed copy", which is both the
#: cheap answer and the reproducible one.
LivecrawlMode = Literal["always", "fallback", "never"]


# -- value types -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExaHit:
    """One result row, in the shape ``/search`` and ``/contents`` both return it."""

    url: str | None
    title: str | None
    published_date: str | None
    author: str | None
    text: str | None
    highlights: tuple[str, ...]


@dataclass(frozen=True)
class ExaContentStatus:
    """Exa's per-URL verdict on a ``/contents`` request.

    Surfaced rather than folded into the results, because "this URL returned nothing" and "this
    URL was never asked for" are different facts and only the statuses tell them apart.
    """

    url: str | None
    status: str | None
    error: object | None


@dataclass(frozen=True)
class ExaSearchResult:
    """A completed ``/search`` call: its rows plus the references that make it auditable.

    ``cost`` is the whole money view of the request in the lane's uniform shape; ``cost_usd``,
    ``request_id``, ``raw_ref`` and ``ledger_row_id`` remain as their own fields because callers
    read them directly. Exa meters every one of these calls, so ``cost.cost_source`` is
    ``metered`` whenever Exa reported a total and ``estimate`` when it did not.
    """

    results: tuple[ExaHit, ...]
    status: int
    cost_usd: Decimal | None
    request_id: str | None
    raw_ref: str | None
    ledger_row_id: str
    cost: CallCost
    #: The written answer a ``type="deep-lite"`` search returns under ``output`` when the caller
    #: sent an ``outputSchema``; ``None`` for every other search. Read with :func:`_read_output`.
    output_text: str | None = None

    @property
    def n_results(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class ExaContentsResult:
    """A completed ``/contents`` call. ``statuses`` says what happened to each requested URL.

    ``cost`` is the request's money view in the lane's uniform shape (see
    :class:`ExaSearchResult`).
    """

    results: tuple[ExaHit, ...]
    statuses: tuple[ExaContentStatus, ...]
    status: int
    cost_usd: Decimal | None
    request_id: str | None
    raw_ref: str | None
    ledger_row_id: str
    cost: CallCost

    @property
    def n_results(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class ExaDeepResult:
    """A completed deep-reasoning call.

    ``output_text`` is always the answer as text. ``output_object`` is that answer parsed, and is
    ``None`` when the output was prose rather than JSON — a caller that asked for a structured
    schema and got ``None`` has learned something real, so it is not rounded to an empty dict.
    ``report_text`` is the ``report`` string when the schema asked for one. ``grounding`` is
    ``output.grounding`` exactly as Exa returned it: the per-field citations the platform artifact
    is built from, never re-shaped here.
    """

    output_text: str
    output_object: object | None
    report_text: str | None
    grounding: object | None
    results: tuple[ExaHit, ...]
    status: int
    cost_usd: Decimal | None
    request_id: str | None
    raw_ref: str | None
    ledger_row_id: str
    cost: CallCost
    retried: bool

    @property
    def n_results(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class ExaCitation:
    """One source ``/answer`` says it read. ``text`` is present only when ``text=True`` was sent.

    Kept as its own type rather than folded into :class:`ExaHit`: an answer's citation is the
    evidence *behind a verdict*, and the R4 gate verifier stores the URL, the date and the quoted
    passage against the claim it justifies. A field Exa did not report stays ``None``.
    """

    url: str
    title: str | None
    published_date: str | None
    text: str | None


@dataclass(frozen=True)
class ExaAnswerResult:
    """A completed ``/answer`` call: the answer, its sources, and the money row behind them.

    ``answer`` is whatever Exa returned in that key — a dict when an ``outputSchema`` was sent and
    honoured, a string when the answer was prose, and ``None`` when Exa returned no answer at all.
    None of the three is rounded into another: "Exa answered nothing" is a real verdict for a gate
    that cannot be decided, and an empty dict would hide it.

    ``cost`` is the request's money view in the lane's uniform shape (see :class:`ExaSearchResult`).
    """

    answer: object
    citations: tuple[ExaCitation, ...]
    status: int
    cost_usd: Decimal | None
    request_id: str | None
    raw_ref: str | None
    ledger_row_id: str
    cost: CallCost


@dataclass(frozen=True)
class ExaAgentRun:
    """A finished (or given-up-on) Exa Agent run.

    ``status`` is Exa's terminal status — ``completed``, ``failed``, ``cancelled`` — or the
    client's own ``timed_out`` when the run outlived ``timeout_s``. Only ``completed`` carries
    ``structured``/``output_text``/``grounding``. ``costs`` is every leg's :class:`CallCost` in
    order (create, then each poll); ``cost`` is the last leg's, which is the one metered leg on a
    run that reached a terminal status (every earlier leg is ``unpriced`` by design — one run,
    one charge). Nothing here raises for a provider-side failure: the driver's failure law
    (ARV2-ONBOARDING-PLAN.md §3) records it on the step.
    """

    run_id: str | None
    status: str
    stop_reason: str | None
    output_text: str | None
    structured: object | None
    grounding: list[Any]
    usage: Mapping[str, Any]
    cost_usd: Decimal | None
    error_code: str | None
    error_message: str | None
    polls: int
    raw_refs: tuple[str, ...]
    ledger_row_ids: tuple[str, ...]
    costs: tuple[CallCost, ...]
    cost: CallCost


def agent_run_body(
    *,
    query: str,
    output_schema: Mapping[str, object],
    effort: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Build the ``POST /agent/runs`` body. ``outputSchema`` is passed exactly as given: the
    Agent surface accepts full JSON Schema, and the shape is the caller's contract."""
    if effort not in EXA_AGENT_EFFORTS:
        raise ValueError(f"unknown Exa Agent effort {effort!r}; one of {EXA_AGENT_EFFORTS}")
    body: dict[str, Any] = {"query": query, "effort": effort, "outputSchema": dict(output_schema)}
    if system_prompt is not None:
        body["systemPrompt"] = system_prompt
    return body


# -- output schemas ----------------------------------------------------------------------------


def report_output_schema() -> dict[str, Any]:
    """The one-string-property schema a cited-markdown dossier is asked for with.

    The proof-of-concept established this the hard way: with **no** ``outputSchema`` Exa returns
    no ``output`` key at all, and with a multi-property schema the model splits its budget across
    the fields instead of writing the dossier. One required string property is the shape that
    produces a report.

    A fresh dict every call — a shared constant would let one caller's edit reach every other.
    """
    return {
        "type": "object",
        "required": ["report"],
        "additionalProperties": False,
        "properties": {
            "report": {
                "type": "string",
                "description": (
                    "The exhaustive cited markdown dossier answering every numbered section of "
                    "the charter, with a verbatim quote and URL behind every assertion and "
                    "explicit NOT FOUND markers."
                ),
            }
        },
    }


def product_catalog_output_schema() -> dict[str, Any]:
    """``ARV2-PRODUCT-CATALOG-CONTRACT.md`` §3, verbatim — nine properties, two levels deep.

    Exa's ``/search`` reference caps ``outputSchema`` at nesting depth 2 and ten properties, and
    returns citations in ``output.grounding`` rather than in the schema, so no citation field
    appears here. ``enum`` is not on Exa's documented keyword list; §3 rules that if a request is
    rejected for it the allowed values move into ``description`` and the enum is enforced
    platform-side. This function is the contract either way, so it is not changed speculatively.
    """
    return {
        "type": "object",
        "required": ["products"],
        "properties": {
            "coverage_note": {
                "type": "string",
                "description": "What was searched and what may still be missing.",
            },
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "short_description", "offering_kind"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "The offering's name exactly as its official_url page writes "
                                "it, keeping that page's spelling, spacing and capitalisation."
                            ),
                        },
                        "short_description": {
                            "type": "string",
                            "description": (
                                "One or two sentences at portfolio level. No pricing, capability "
                                "lists, integrations, competitors or customer names."
                            ),
                        },
                        "offering_kind": {
                            "type": "string",
                            "enum": [
                                "product",
                                "platform",
                                "integration",
                                "partner_program",
                                "service",
                            ],
                            "description": (
                                "product = standalone offering; platform = layer over several "
                                "products; integration = an existing product delivered inside a "
                                "third-party system; partner_program = white-label or embed "
                                "program; service = human-delivered offering."
                            ),
                        },
                        "family": {
                            "type": "string",
                            "description": (
                                "Umbrella brand or product family, when the company groups "
                                "offerings that way. Omit if none."
                            ),
                        },
                        "lifecycle": {
                            "type": "string",
                            "enum": ["active", "beta", "sunset", "unknown"],
                        },
                        "official_url": {
                            "type": "string",
                            "description": (
                                "The page on the company's own domain where this offering is "
                                "presented; a page may present several offerings. Not the "
                                "homepage, a pricing page or a blog post. Omit only if no such "
                                "page exists."
                            ),
                        },
                    },
                },
            },
        },
    }


# -- request shaping ---------------------------------------------------------------------------


def search_body(
    query: str,
    *,
    type: str = "auto",
    num_results: int = 8,
    include_domains: Sequence[str] | None = None,
    exclude_domains: Sequence[str] | None = None,
    include_text: Sequence[str] | None = None,
    start_published_date: str | None = None,
    end_published_date: str | None = None,
    category: str | None = None,
    text_max_chars: int = 1500,
    highlights: Mapping[str, object] | None = None,
    output_schema: Mapping[str, object] | None = None,
    extras: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build a ``/search`` body. Every optional key is absent unless the caller passed it.

    That absence is the point. ``includeDomains`` in particular is a hard filter — a default list
    would make every search in the lane silently blind to everything outside it, and the caller
    would have no way to tell a genuinely empty web from a narrowed one.
    """
    body: dict[str, Any] = {
        "query": query,
        "type": type,
        "numResults": num_results,
        "contents": {"text": {"maxCharacters": text_max_chars}},
    }
    if include_domains is not None:
        body["includeDomains"] = list(include_domains)
    if exclude_domains is not None:
        body["excludeDomains"] = list(exclude_domains)
    if include_text is not None:
        body["includeText"] = list(include_text)
    if start_published_date is not None:
        body["startPublishedDate"] = start_published_date
    if end_published_date is not None:
        body["endPublishedDate"] = end_published_date
    if category is not None:
        body["category"] = category
    if highlights is not None:
        body["contents"]["highlights"] = dict(highlights)
    if extras is not None:
        body["contents"]["extras"] = dict(extras)
    if output_schema is not None:
        # Copied, never aliased: the same rule ``agent_run_body`` keeps for its schema.
        body["outputSchema"] = dict(output_schema)
    return body


def contents_body(
    urls: Sequence[str],
    *,
    text_max_chars: int = 8000,
    livecrawl: LivecrawlMode | None = None,
    highlights: Mapping[str, object] | None = None,
    extras: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build a ``/contents`` body. No ``livecrawl`` key means Exa serves its indexed copy."""
    body: dict[str, Any] = {"urls": list(urls), "text": {"maxCharacters": text_max_chars}}
    if livecrawl is not None:
        body["livecrawl"] = livecrawl
    if highlights is not None:
        body["highlights"] = dict(highlights)
    if extras is not None:
        body["extras"] = dict(extras)
    return body


def answer_body(
    query: str,
    *,
    system_prompt: str,
    output_schema: Mapping[str, object],
    model: str = "exa",
    text: bool = True,
) -> dict[str, Any]:
    """Build an ``/answer`` body.

    ``text`` defaults on because an answer whose citations carry no passages cannot be audited:
    R4's gate verifier stores the quoted sentence its verdict rests on, and without ``text`` the
    only thing left to store is a URL and the model's word for what is on it. ``outputSchema`` is
    copied, not aliased — a caller that reuses one schema dict across every gate must not have it
    mutated by a body it built earlier.
    """
    return {
        "query": query,
        "model": model,
        "text": text,
        "systemPrompt": system_prompt,
        "outputSchema": dict(output_schema),
    }


def deep_reasoning_body(
    *,
    system_prompt: str,
    query: str,
    output_schema: Mapping[str, object],
    num_results: int = 20,
    additional_queries: Sequence[str] | None = None,
    include_domains: Sequence[str] | None = None,
    text_max_chars: int = 10000,
    highlights_query: str | None = None,
    highlights_max_chars: int = 2000,
    contents: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build a ``type="deep-reasoning"`` body.

    ``stream`` is pinned false: the wrapper saves one whole raw body per attempt (law 1), and a
    stream has no whole body to save. ``outputSchema`` is passed exactly as the caller gave it —
    the shape is the caller's contract with the model, and this module does not have an opinion
    about it beyond shipping the two known ones above.
    """
    body: dict[str, Any] = {
        "query": query,
        "type": "deep-reasoning",
        "systemPrompt": system_prompt,
        "numResults": num_results,
        "stream": False,
        "contents": {"text": {"maxCharacters": text_max_chars}},
        "outputSchema": dict(output_schema),
    }
    if additional_queries is not None:
        body["additionalQueries"] = list(additional_queries)
    if include_domains is not None:
        body["includeDomains"] = list(include_domains)
    if highlights_query is not None:
        body["contents"]["highlights"] = {
            "query": highlights_query,
            "maxCharacters": highlights_max_chars,
        }
    if contents is not None:
        body["contents"] = deepcopy(dict(contents))
    return body


# -- reading the response ----------------------------------------------------------------------


def _decimal(value: object) -> Decimal | None:
    """A provider-reported number as an exact Decimal, or ``None`` when it is not a number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def _body_json(response: HttpResponse) -> dict[str, Any]:
    """The response body as a dict, or an empty dict — never an exception, never a guess."""
    try:
        parsed = json.loads(response.body)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def exa_cost_reader(response: HttpResponse) -> CostReading:
    """Read Exa's own metering off a response — the total, the request id, and the breakdown.

    Appendix A law 1: the ledger carries the provider's own metering, not the estimate that
    reserved the spend. Exa reports a per-component *breakdown* (``costDollars.search.neural``,
    ``costDollars.contents.text``…) alongside ``costDollars.total``, and that breakdown is what
    answers "which part of this call was expensive" months later, so it is returned in the
    reading's ``extras`` rather than discarded the moment the total is extracted. The wrapper
    merges it into the result row and leaves the estimate row alone.

    Stateless on purpose: a reader reports what it read by returning it. A body that is not JSON,
    or carries no ``costDollars`` at all, yields an empty reading — "Exa did not tell us" is a
    real answer and the wrapper records it as such, never as zero.

    The exception is a 4xx. Exa refused the request before doing any work — out of credits, a key
    it does not accept, a body it could not validate — so nothing was sold, and the reading says
    so with an explicit zero. Left empty, the wrapper would fall back to the estimate and record a
    charge that never happened (seven refused Answer calls at a cent each on run ``ee79d837``).
    A 5xx keeps the empty reading: whether a failed call did billable work is not something this
    module can know.
    """
    body = _body_json(response)
    if 400 <= response.status < 500:
        request_id = body.get("requestId")
        return CostReading(
            cost_usd=Decimal(0),
            provider_request_id=request_id if isinstance(request_id, str) else None,
        )
    costs = body.get("costDollars")
    costs = costs if isinstance(costs, dict) else {}
    request_id = body.get("requestId")
    return CostReading(
        cost_usd=_decimal(costs.get("total")),
        provider_request_id=request_id if isinstance(request_id, str) else None,
        extras={"cost_breakdown": costs} if costs else {},
    )


def exa_agent_cost_reader(response: HttpResponse) -> CostReading:
    """Read an Agent run body. Only a **terminal** body settles money.

    Exa quotes ``costDollars`` (the effort's fixed price, with a projected ``usage``) on the
    create response and on every queued/running poll, long before the run has done anything —
    the live ledger of 2026-09-29 proved it: 208 poll rows each re-booked the same $0.10 / $0.50
    and a $1.30 onboarding read as $39.50. One run is one charge, so this reader settles it once,
    on the body whose ``status`` is terminal (``completed`` / ``failed`` / ``cancelled``): that is
    Exa's final word, and the only one that is right for ``auto`` effort or a run that stopped
    early. Every non-terminal body yields a reading that declares itself ``usd_unpriced`` — the
    row keeps the run id and the quote (as ``quoted_cost_breakdown``) but carries NULL USD, so
    the projection neither sums it nor mistakes it for a measured zero. The create leg's
    reservation still lives on its pre-wire *estimate* row (law 2), which is where the ceiling
    check reads it.

    Residual: a run the client gives up on (``timed_out``) never sees a terminal body, so its
    charge is not on the ledger — the step's ``failure_code`` says ``timeout`` and the quote is on
    every leg's row for a hand reconciliation.
    """
    body = _body_json(response)
    costs = body.get("costDollars")
    costs = costs if isinstance(costs, dict) else {}
    usage = body.get("usage")
    run_id = body.get("id")
    extras: dict[str, object] = {}
    if isinstance(usage, dict):
        extras["usage"] = usage
    if _agent_status(body) in AGENT_TERMINAL_STATUSES:
        if costs:
            extras["cost_breakdown"] = costs
        return CostReading(
            cost_usd=_decimal(costs.get("total")),
            provider_request_id=run_id if isinstance(run_id, str) else None,
            extras=extras,
        )
    extras["usd_unpriced"] = True
    extras["settles_on"] = "terminal_poll"
    if costs:
        extras["quoted_cost_breakdown"] = costs
    return CostReading(
        provider_request_id=run_id if isinstance(run_id, str) else None,
        extras=extras,
    )


def exa_halt_rule(response: HttpResponse) -> str | None:
    """Money truth blocks (master plan §2 item 3): does this response prove Exa will not sell?

    A 402 or 403, or a non-2xx body naming "credit", latches the provider. The credit check is
    deliberately restricted to non-2xx bodies: a successful deep-reasoning dossier about a
    fintech account will contain the word "credit" many times over, and latching the whole
    provider on the *content* of a successful research answer would be a self-inflicted outage.
    """
    if response.status == 402:
        return "payment_required"
    if response.status == 403:
        return "forbidden"
    if 200 <= response.status < 300:
        return None
    if "credit" in response.body.decode("utf-8", "replace").lower():
        return "credit_exhausted"
    return None


def _hits(rows: object) -> tuple[ExaHit, ...]:
    """Map Exa's result rows, keeping ``None`` for anything the provider did not report."""
    if not isinstance(rows, list):
        return ()
    hits: list[ExaHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        highlights = row.get("highlights")
        hits.append(
            ExaHit(
                url=row.get("url") if isinstance(row.get("url"), str) else None,
                title=row.get("title") if isinstance(row.get("title"), str) else None,
                published_date=(
                    row.get("publishedDate") if isinstance(row.get("publishedDate"), str) else None
                ),
                author=row.get("author") if isinstance(row.get("author"), str) else None,
                text=row.get("text") if isinstance(row.get("text"), str) else None,
                highlights=tuple(h for h in highlights if isinstance(h, str))
                if isinstance(highlights, list)
                else (),
            )
        )
    return tuple(hits)


def _statuses(rows: object) -> tuple[ExaContentStatus, ...]:
    """Map ``/contents``' per-URL statuses. Exa keys the URL as ``id``."""
    if not isinstance(rows, list):
        return ()
    out: list[ExaContentStatus] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get("id")
        status = row.get("status")
        out.append(
            ExaContentStatus(
                url=identifier if isinstance(identifier, str) else None,
                status=status if isinstance(status, str) else None,
                error=row.get("error"),
            )
        )
    return tuple(out)


def _citations(rows: object) -> tuple[ExaCitation, ...]:
    """Map ``/answer``'s citations. A row with no ``url`` is dropped: a passage that cannot be
    pointed at is not evidence, and keeping it would let an unattributable quote reach a claim."""
    if not isinstance(rows, list):
        return ()
    out: list[ExaCitation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        if not isinstance(url, str):
            continue
        published = row.get("publishedDate")
        title = row.get("title")
        text = row.get("text")
        out.append(
            ExaCitation(
                url=url,
                title=title if isinstance(title, str) else None,
                published_date=published if isinstance(published, str) else None,
                text=text if isinstance(text, str) else None,
            )
        )
    return tuple(out)


def _maybe_json(text: str) -> object | None:
    """Parse ``text`` when it looks like a JSON object/array, else ``None``.

    Prose is a legitimate deep-reasoning answer, so failing to parse is not an error here.
    """
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict | list) else None


def _read_output(body: Mapping[str, Any]) -> tuple[str, object | None, object | None]:
    """Split Exa's ``output`` into (text, parsed object, grounding).

    Exa returns ``output`` either as a bare string or as an object carrying ``content`` (the
    answer, itself a string or already-parsed JSON) and ``grounding`` (the per-field citations).
    Both shapes are handled because the proof-of-concept saw both.
    """
    output = body.get("output")
    if isinstance(output, str):
        return output, _maybe_json(output), None
    if not isinstance(output, dict):
        return "", None, None
    grounding = output.get("grounding")
    content = output.get("content")
    if isinstance(content, str):
        return content, _maybe_json(content), grounding
    if content is not None:
        return json.dumps(content, indent=2), content, grounding
    return json.dumps(output, indent=2), None, grounding


def _agent_status(run: Mapping[str, Any]) -> str:
    status = run.get("status")
    return status if isinstance(status, str) else "unparseable"


def _agent_result(
    run: Mapping[str, Any],
    run_id: str | None,
    legs: Sequence[CallResult],
    polls: int,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> ExaAgentRun:
    output = run.get("output")
    output = output if isinstance(output, dict) else {}
    error = run.get("error")
    error = error if isinstance(error, dict) else {}
    completed = status == "completed"
    grounding = output.get("grounding") if completed else None
    text = output.get("text") if completed else None
    stop_reason = run.get("stopReason")
    usage = run.get("usage")
    last = legs[-1]
    return ExaAgentRun(
        run_id=run_id,
        status=status,
        stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        output_text=text if isinstance(text, str) else None,
        structured=output.get("structured") if completed else None,
        grounding=list(grounding) if isinstance(grounding, list) else [],
        usage=dict(usage) if isinstance(usage, dict) else {},
        cost_usd=last.cost.cost_usd,
        error_code=error_code
        or (error.get("code") if isinstance(error.get("code"), str) else None),
        error_message=error_message
        or (error.get("message") if isinstance(error.get("message"), str) else None),
        polls=polls,
        raw_refs=tuple(ref for leg in legs for ref in leg.raw_refs),
        ledger_row_ids=tuple(leg.ledger_row_id for leg in legs),
        costs=tuple(leg.call_cost for leg in legs),
        cost=last.call_cost,
    )


def _read_report(parsed: object | None) -> str | None:
    """The ``report`` string out of a parsed output, or ``None`` when the schema had no report.

    Exa has returned ``report`` both as a plain string and wrapped as ``{"value": ...}``; the
    proof-of-concept unwrapped both, so this does too.
    """
    if not isinstance(parsed, dict):
        return None
    report = parsed.get("report")
    if isinstance(report, str):
        return report
    if isinstance(report, dict):
        value = report.get("value")
        return value if isinstance(value, str) else None
    return None


def read_deep_report(body: Mapping[str, Any], *, text_output: bool = False) -> str | None:
    """Read retained deep output without mistaking a JSON envelope for a text report."""
    output_text, parsed, _ = _read_output(body)
    report = _read_report(parsed)
    if report is not None:
        return report
    if text_output and parsed is None:
        # Missing/malformed output must not become a report containing the envelope JSON.
        output = body.get("output")
        if isinstance(output, str) or (
            isinstance(output, dict) and isinstance(output.get("content"), str)
        ):
            return output_text
    return None


#: How much of a result's own words a row keeps: enough to judge whether to open the page.
_RESULT_SNIPPET_CHARS = 300


def exa_result_rows(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One short row per result, in Exa's rank order: link, title, date and a snippet.

    The receipt preview shows these, so the agent sees what each result says without opening the
    saved response (2026-10-10: run 3's preview showed four bare links of ten, and the one it hid
    was the account's ABM case study). The snippet is Exa's highlights, else its summary, else the
    start of the page text. A result with no link is not a result the agent can open.
    """
    rows: list[dict[str, Any]] = []
    for result in body.get("results") or []:
        if not isinstance(result, Mapping) or not result.get("url"):
            continue
        highlights = result.get("highlights")
        candidates = (
            " ".join(h for h in highlights if isinstance(h, str))
            if isinstance(highlights, list)
            else None,
            result.get("summary"),
            result.get("text"),
        )
        snippet = next(
            (" ".join(c.split()) for c in candidates if isinstance(c, str) and c.strip()), ""
        )
        rows.append(
            {
                "url": result["url"],
                "title": result.get("title"),
                "published": result.get("publishedDate"),
                "text_head": snippet[:_RESULT_SNIPPET_CHARS],
            }
        )
    return rows


def is_thin_deep_response(
    *, n_results: int, cost_usd: Decimal | None, report_chars: int | None
) -> bool:
    """Appendix A law 4: does this 200 carry the deep-reasoning silent-fail signature?

    Two independent tells, either of which condemns the response:

    * few results **and** a cost that never left the floor — the research pass did not run;
    * a report-shaped schema whose report is shorter than a real dossier ever is.

    ``report_chars`` is ``None`` for a schema that asks for no report, in which case only the
    first tell applies. An unreported cost counts as zero: "Exa did not tell us what this cost"
    alongside nine results is exactly the state the guard exists to catch, and treating an
    unknown as expensive would let the real failure through.
    """
    if report_chars is not None and report_chars < THIN_MIN_REPORT_CHARS:
        return True
    cost = cost_usd if cost_usd is not None else Decimal(0)
    return n_results <= THIN_MAX_RESULTS and cost <= THIN_MAX_COST_USD


def _is_richer(candidate: ExaDeepResult, incumbent: ExaDeepResult) -> bool:
    """Did the retry actually buy more? Longer answer wins; equal answers break on result count.

    Length is the honest proxy here: the guard fired because the first answer was a stub, and a
    stub is short. Nothing is discarded on a tie — the incumbent is already paid for.
    """
    return (len(candidate.output_text), candidate.n_results) > (
        len(incumbent.output_text),
        incumbent.n_results,
    )


def _search_result(
    body: Mapping[str, Any],
    *,
    status: int,
    cost: CallCost,
    request_id: str | None,
    cost_usd: Decimal | None = None,
    raw_ref: str | None = None,
    ledger_row_id: str = "",
) -> ExaSearchResult:
    """Shape an :class:`ExaSearchResult` from a ``/search`` body. ``output`` is present only for a
    deep-lite search that sent an ``outputSchema``; an empty string is reported as ``None`` so
    callers test one thing.

    ``cost_usd`` is the provider's *own reading* — ``CallResult.cost.cost_usd``, which is ``None``
    when Exa reported no total — and is deliberately not taken from ``cost``, whose ``cost_usd``
    is the settled ledger number that falls back to the pre-spend estimate. The two differ exactly
    when Exa said nothing, and this field has always meant "what Exa charged, or we don't know".
    """
    text, _parsed, _grounding = _read_output(body)
    return ExaSearchResult(
        results=_hits(body.get("results")),
        status=status,
        cost_usd=cost_usd,
        request_id=request_id,
        raw_ref=raw_ref,
        ledger_row_id=ledger_row_id,
        cost=cost,
        output_text=text or None,
    )


# -- the client --------------------------------------------------------------------------------


class ExaClient:
    """Exa's three operations, each one :class:`CallSpec` through the caller it was given."""

    def __init__(
        self,
        caller: ProviderCaller,
        api_key: SecretStr,
        *,
        base_url: str = EXA_BASE_URL,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._caller = caller
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # Injected for the poll loop only (the wrapper has its own for retry backoff): a test
        # drives the sequence without waiting, production waits for real.
        self._sleep = sleep
        self._monotonic = monotonic

    def search(
        self,
        query: str,
        *,
        type: str = "auto",
        num_results: int = 8,
        include_domains: Sequence[str] | None = None,
        exclude_domains: Sequence[str] | None = None,
        include_text: Sequence[str] | None = None,
        start_published_date: str | None = None,
        end_published_date: str | None = None,
        category: str | None = None,
        text_max_chars: int = 1500,
        highlights: Mapping[str, object] | None = None,
        output_schema: Mapping[str, object] | None = None,
        extras: Mapping[str, object] | None = None,
        label: str = "exa-search",
        timeout_s: float = 180.0,
    ) -> ExaSearchResult:
        """One ``/search`` call — the cheap instrument that finds candidate URLs."""
        result = self._call(
            operation="search",
            label=label,
            path="/search",
            body=search_body(
                query,
                type=type,
                num_results=num_results,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                include_text=include_text,
                start_published_date=start_published_date,
                end_published_date=end_published_date,
                category=category,
                text_max_chars=text_max_chars,
                highlights=highlights,
                output_schema=output_schema,
                extras=extras,
            ),
            estimate=SpendEstimate(usd=SEARCH_ESTIMATE_USD),
            timeout_s=timeout_s,
        )
        body = _body_json(result.response)
        return _search_result(
            body,
            status=result.response.status,
            cost=result.call_cost,
            request_id=result.cost.provider_request_id,
            cost_usd=result.cost.cost_usd,
            raw_ref=result.raw_ref,
            ledger_row_id=result.ledger_row_id,
        )

    def contents(
        self,
        urls: Sequence[str],
        *,
        text_max_chars: int = 8000,
        livecrawl: LivecrawlMode | None = None,
        highlights: Mapping[str, object] | None = None,
        extras: Mapping[str, object] | None = None,
        label: str = "exa-contents",
        timeout_s: float = 240.0,
    ) -> ExaContentsResult:
        """One ``/contents`` call. Costs are per URL, so the estimate scales with the request."""
        urls = list(urls)
        result = self._call(
            operation="contents",
            label=label,
            path="/contents",
            body=contents_body(
                urls,
                text_max_chars=text_max_chars,
                livecrawl=livecrawl,
                highlights=highlights,
                extras=extras,
            ),
            estimate=SpendEstimate(usd=CONTENTS_ESTIMATE_USD_PER_URL * len(urls)),
            timeout_s=timeout_s,
        )
        body = _body_json(result.response)
        return ExaContentsResult(
            results=_hits(body.get("results")),
            statuses=_statuses(body.get("statuses")),
            status=result.response.status,
            cost_usd=result.cost.cost_usd,
            request_id=result.cost.provider_request_id,
            raw_ref=result.raw_ref,
            ledger_row_id=result.ledger_row_id,
            cost=result.call_cost,
        )

    def answer(
        self,
        query: str,
        *,
        system_prompt: str,
        output_schema: Mapping[str, object],
        model: str = "exa",
        label: str = "exa-answer",
        timeout_s: float = 120.0,
    ) -> ExaAnswerResult:
        """One ``/answer`` call — a search plus one model pass, answering a single question.

        This is R4's verifier: one gate, one question, one structured verdict with the passage it
        rests on. It is deliberately *not* :meth:`deep_reasoning` — a gate is a fact-check against
        what the open web already says, not a research pass, and at a hundredth of the price it
        can be run per company per gate.
        """
        result = self._call(
            operation="answer",
            label=label,
            path="/answer",
            body=answer_body(
                query,
                system_prompt=system_prompt,
                output_schema=output_schema,
                model=model,
            ),
            estimate=SpendEstimate(usd=ANSWER_ESTIMATE_USD),
            timeout_s=timeout_s,
        )
        body = _body_json(result.response)
        return ExaAnswerResult(
            answer=body.get("answer"),
            citations=_citations(body.get("citations")),
            status=result.response.status,
            cost_usd=result.cost.cost_usd,
            request_id=result.cost.provider_request_id,
            raw_ref=result.raw_ref,
            ledger_row_id=result.ledger_row_id,
            cost=result.call_cost,
        )

    def deep_reasoning(
        self,
        *,
        system_prompt: str,
        query: str,
        output_schema: Mapping[str, object],
        num_results: int = 20,
        additional_queries: Sequence[str] | None = None,
        include_domains: Sequence[str] | None = None,
        text_max_chars: int = 10000,
        highlights_query: str | None = None,
        highlights_max_chars: int = 2000,
        contents: Mapping[str, object] | None = None,
        label: str = "exa-deep",
        timeout_s: float = 1200.0,
    ) -> ExaDeepResult:
        """One agentic research pass, with Appendix A law 4's one-shot retry on a thin answer.

        The guard is why this method is not just ``_call`` plus a parse: Exa answers 200 to a
        deep-reasoning call it did not really run, so "the HTTP call succeeded" is not evidence
        that the research happened. When the signature shows, exactly one retry is bought and the
        richer of the two answers is kept — bounded, and recorded on ``retried``.
        """
        body = deep_reasoning_body(
            system_prompt=system_prompt,
            query=query,
            output_schema=output_schema,
            num_results=num_results,
            additional_queries=additional_queries,
            include_domains=include_domains,
            text_max_chars=text_max_chars,
            highlights_query=highlights_query,
            highlights_max_chars=highlights_max_chars,
            contents=contents,
        )
        wants_report = (
            "report" in _schema_properties(output_schema) or output_schema.get("type") == "text"
        )
        first = self._deep_call(body, label=label, timeout_s=timeout_s)
        report_chars = len(first.report_text or "") if wants_report else None
        if not is_thin_deep_response(
            n_results=first.n_results, cost_usd=first.cost_usd, report_chars=report_chars
        ):
            return first

        metadata = {
            "provider": PROVIDER,
            "operation": "deep-reasoning",
            "label": label,
            "next_label": f"{label}-retry",
            "reason": "thin_response",
            "first_ledger_row_id": first.ledger_row_id,
            "result_count": first.n_results,
            "report_chars": report_chars,
            "cost_usd": str(first.cost_usd),
        }
        with observation("exa.thin_response_retry", as_type="span", metadata=metadata):
            get_logger(__name__).info("provider.retry.scheduled", **metadata)
            retry = self._deep_call(body, label=f"{label}-retry", timeout_s=timeout_s)
        kept = retry if _is_richer(retry, first) else first
        return replace(kept, retried=True)

    def agent_run(
        self,
        *,
        query: str,
        output_schema: Mapping[str, object],
        effort: str,
        system_prompt: str | None = None,
        label: str = "exa-agent",
        poll_interval_s: float = 4.0,
        timeout_s: float = 900.0,
    ) -> ExaAgentRun:
        """One Exa Agent run: create, then poll until terminal or ``timeout_s`` of wall time.

        Blocking by design (R2 composition constraint): the driver calls this through
        ``asyncio.to_thread``. Each leg is one wrapped call with its own raw record and ledger
        row; the create leg reserves the effort's fixed price on its pre-wire estimate row, and
        the run's one charge is settled as metered on the terminal body alone — the create and
        every running poll settle ``usd_unpriced`` (see :func:`exa_agent_cost_reader`), so the
        legs of one run never sum to more than the run.
        """
        body = agent_run_body(
            query=query, output_schema=output_schema, effort=effort, system_prompt=system_prompt
        )
        started = self._monotonic()
        legs: list[CallResult] = []
        create = self._agent_call(
            operation="agent-create",
            label=label,
            method="POST",
            path="/agent/runs",
            body=body,
            estimate=SpendEstimate(usd=AGENT_EFFORT_ESTIMATE_USD[effort]),
        )
        legs.append(create)
        run = _body_json(create.response)
        run_id = run.get("id") if isinstance(run.get("id"), str) else None
        polls = 0
        while _agent_status(run) not in AGENT_TERMINAL_STATUSES:
            if run_id is None:
                return _agent_result(
                    run,
                    run_id,
                    legs,
                    polls,
                    status="unparseable",
                    error_code="no_run_id",
                    error_message="create returned no run id",
                )
            if self._monotonic() - started > timeout_s:
                return _agent_result(
                    run,
                    run_id,
                    legs,
                    polls,
                    status="timed_out",
                    error_code="timeout",
                    error_message=f"run not terminal after {timeout_s:.0f}s",
                )
            self._sleep(poll_interval_s)
            poll = self._agent_call(
                operation="agent-poll",
                label=f"{label}-poll",
                method="GET",
                path=f"/agent/runs/{run_id}",
                body=None,
                estimate=SpendEstimate(),
            )
            legs.append(poll)
            polls += 1
            run = _body_json(poll.response)
        return _agent_result(run, run_id, legs, polls, status=_agent_status(run))

    # -- internals -----------------------------------------------------------------------------

    def _agent_call(
        self,
        *,
        operation: str,
        label: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        estimate: SpendEstimate,
    ) -> CallResult:
        """One Agent leg. Bearer auth is what the Agent guide documents (search uses x-api-key)."""
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        if body is None:
            request = HttpRequest(
                method=method,
                url=f"{self._base_url}{path}",
                headers=headers,
                body=None,
                timeout_s=AGENT_LEG_TIMEOUT_S,
            )
        else:
            request = json_request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json_body=dict(body),
                timeout_s=AGENT_LEG_TIMEOUT_S,
            )
        return self._caller.call(
            CallSpec(
                provider=PROVIDER,
                operation=operation,
                label=label,
                request=request,
                estimate=estimate,
                cost_reader=exa_agent_cost_reader,
                halt_rule=exa_halt_rule,
            )
        )

    def _deep_call(self, body: Mapping[str, Any], *, label: str, timeout_s: float) -> ExaDeepResult:
        result = self._call(
            operation="deep-reasoning",
            label=label,
            path="/search",
            body=body,
            estimate=SpendEstimate(usd=DEEP_REASONING_ESTIMATE_USD),
            timeout_s=timeout_s,
            max_attempts=DEEP_REASONING_MAX_ATTEMPTS,
        )
        parsed_body = _body_json(result.response)
        output_text, output_object, grounding = _read_output(parsed_body)
        return ExaDeepResult(
            output_text=output_text,
            output_object=output_object,
            report_text=read_deep_report(
                parsed_body, text_output=body.get("outputSchema", {}).get("type") == "text"
            ),
            grounding=grounding,
            results=_hits(parsed_body.get("results")),
            status=result.response.status,
            cost_usd=result.cost.cost_usd,
            request_id=result.cost.provider_request_id,
            raw_ref=result.raw_ref,
            ledger_row_id=result.ledger_row_id,
            cost=result.call_cost,
            retried=False,
        )

    def _call(
        self,
        *,
        operation: str,
        label: str,
        path: str,
        body: Mapping[str, Any],
        estimate: SpendEstimate,
        timeout_s: float,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> CallResult:
        """Assemble the spec and hand it to the wrapper. This is the only egress in the module."""
        request = json_request(
            "POST",
            f"{self._base_url}{path}",
            headers={"x-api-key": self._api_key.get_secret_value()},
            json_body=dict(body),
            timeout_s=timeout_s,
        )
        return self._caller.call(
            CallSpec(
                provider=PROVIDER,
                operation=operation,
                label=label,
                request=request,
                estimate=estimate,
                max_attempts=max_attempts,
                cost_reader=exa_cost_reader,
                halt_rule=exa_halt_rule,
            )
        )


def _schema_properties(schema: Mapping[str, object]) -> Mapping[str, object]:
    """A schema's top-level ``properties`` map, or an empty one."""
    properties = schema.get("properties")
    return properties if isinstance(properties, Mapping) else {}
