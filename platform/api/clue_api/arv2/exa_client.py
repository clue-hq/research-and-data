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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import SecretStr

from clue_api.arv2.calls import (
    DEFAULT_MAX_ATTEMPTS,
    CallResult,
    CallSpec,
    CostReading,
    ProviderCaller,
    SpendEstimate,
)
from clue_api.arv2.transport import HttpResponse, json_request

#: Exa's API root. A parameter on the client rather than a constant in a body builder, so a
#: proxy or a regional endpoint is a call-site decision.
EXA_BASE_URL = "https://api.exa.ai"

PROVIDER = "exa"

#: Pre-spend estimates (Appendix A law 2). These reserve the spend *before* the wire; the real
#: number replaces them on the result row as soon as :func:`exa_cost_reader` has read it.
SEARCH_ESTIMATE_USD = Decimal("0.01")
CONTENTS_ESTIMATE_USD_PER_URL = Decimal("0.002")
DEEP_REASONING_ESTIMATE_USD = Decimal("0.05")

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
    """A completed ``/search`` call: its rows plus the references that make it auditable."""

    results: tuple[ExaHit, ...]
    status: int
    cost_usd: Decimal | None
    request_id: str | None
    raw_ref: str | None
    ledger_row_id: str

    @property
    def n_results(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class ExaContentsResult:
    """A completed ``/contents`` call. ``statuses`` says what happened to each requested URL."""

    results: tuple[ExaHit, ...]
    statuses: tuple[ExaContentStatus, ...]
    status: int
    cost_usd: Decimal | None
    request_id: str | None
    raw_ref: str | None
    ledger_row_id: str

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
    retried: bool

    @property
    def n_results(self) -> int:
        return len(self.results)


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
                                "Official product name exactly as the company writes it."
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
                                "Canonical page for this offering on the company's own domain. "
                                "Omit if none exists."
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
    include_text: Sequence[str] | None = None,
    start_published_date: str | None = None,
    end_published_date: str | None = None,
    category: str | None = None,
    text_max_chars: int = 1500,
    highlights: Mapping[str, object] | None = None,
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
    return body


def contents_body(
    urls: Sequence[str],
    *,
    text_max_chars: int = 8000,
    livecrawl: LivecrawlMode | None = None,
    highlights: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build a ``/contents`` body. No ``livecrawl`` key means Exa serves its indexed copy."""
    body: dict[str, Any] = {"urls": list(urls), "text": {"maxCharacters": text_max_chars}}
    if livecrawl is not None:
        body["livecrawl"] = livecrawl
    if highlights is not None:
        body["highlights"] = dict(highlights)
    return body


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
    """
    body = _body_json(response)
    costs = body.get("costDollars")
    costs = costs if isinstance(costs, dict) else {}
    request_id = body.get("requestId")
    return CostReading(
        cost_usd=_decimal(costs.get("total")),
        provider_request_id=request_id if isinstance(request_id, str) else None,
        extras={"cost_breakdown": costs} if costs else {},
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


# -- the client --------------------------------------------------------------------------------


class ExaClient:
    """Exa's three operations, each one :class:`CallSpec` through the caller it was given."""

    def __init__(
        self,
        caller: ProviderCaller,
        api_key: SecretStr,
        *,
        base_url: str = EXA_BASE_URL,
    ) -> None:
        self._caller = caller
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def search(
        self,
        query: str,
        *,
        type: str = "auto",
        num_results: int = 8,
        include_domains: Sequence[str] | None = None,
        include_text: Sequence[str] | None = None,
        start_published_date: str | None = None,
        end_published_date: str | None = None,
        category: str | None = None,
        text_max_chars: int = 1500,
        highlights: Mapping[str, object] | None = None,
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
                include_text=include_text,
                start_published_date=start_published_date,
                end_published_date=end_published_date,
                category=category,
                text_max_chars=text_max_chars,
                highlights=highlights,
            ),
            estimate=SpendEstimate(usd=SEARCH_ESTIMATE_USD),
            timeout_s=timeout_s,
        )
        body = _body_json(result.response)
        return ExaSearchResult(
            results=_hits(body.get("results")),
            status=result.response.status,
            cost_usd=result.cost.cost_usd,
            request_id=result.cost.provider_request_id,
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
        )
        wants_report = "report" in _schema_properties(output_schema)
        first = self._deep_call(body, label=label, timeout_s=timeout_s)
        report_chars = len(first.report_text or "") if wants_report else None
        if not is_thin_deep_response(
            n_results=first.n_results, cost_usd=first.cost_usd, report_chars=report_chars
        ):
            return first

        retry = self._deep_call(body, label=f"{label}-retry", timeout_s=timeout_s)
        kept = retry if _is_richer(retry, first) else first
        return replace(kept, retried=True)

    # -- internals -----------------------------------------------------------------------------

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
            report_text=_read_report(output_object),
            grounding=grounding,
            results=_hits(parsed_body.get("results")),
            status=result.response.status,
            cost_usd=result.cost.cost_usd,
            request_id=result.cost.provider_request_id,
            raw_ref=result.raw_ref,
            ledger_row_id=result.ledger_row_id,
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
