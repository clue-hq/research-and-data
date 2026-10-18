"""Exa Websets — the long-list instrument, through the one wrapper.

A webset is an *asynchronous* search: you describe the companies you want and the criteria they
must satisfy, Exa spends minutes finding and evaluating candidates, and you read the result back
as a page of items each carrying a company record and a per-criterion verdict. That is a
different shape from :mod:`clue_api.arv2.exa_client`'s synchronous calls, and the difference is
why this is its own client rather than four more methods there: a webset is created, polled and
*then* read, and only the read is billed.

Five rules this module exists to keep:

* **A refusal is reported, never read as an empty answer.** Every view carries ``error`` — Exa's
  own words — when the call was not a 2xx, so a caller cannot mistake "Exa rejected this request"
  for "Exa found nothing" (the old widening search was rejected with a 400 on every run and read as
  a search that found nobody). Raising is the caller's business: a client never invents a failure
  type (``clue_spend.errors``).
* **The bill is read on the items page, not guessed at creation.** Websets charges ten credits
  per *all-green* result — a row whose every criterion was satisfied. :func:`websets_items_cost`
  is that arithmetic in one place, and :meth:`ExaWebsetsClient.items` records it as the call's
  cost — **once per row per run**: a webset is read on every poll and again on every resume, and
  every read returns every row, so the caller carries the ids it has already been charged for
  (:func:`newly_priced`). Creation reserves the worst case (``count`` × ten credits) as a law-2
  pre-spend estimate and records only the recall estimate's own five credits as its cost, because
  recording the reservation as spend too would double-count every match: once when the search
  was asked for, once when its results were read.
* **Exa bills a row when it finds it, not when we read it.** A run that stops reading before its
  webset is ``idle`` must :meth:`ExaWebsetsClient.cancel` it and read it once more, or Exa keeps
  finding — and charging for — companies the ledger never sees.
* **A GET carries no body.** ``json_request(..., json_body=None)`` would serialise the literal
  ``null`` onto the wire; the read paths build their :class:`~clue_api.arv2.transport.HttpRequest`
  directly instead.
* **A refusal to sell latches the provider.** A 401 or 402 means the next call cannot succeed
  either, and a webset is exactly the kind of long poll that would otherwise retry a dead key a
  few hundred times.

Nothing here opens a socket: every call is a :class:`~clue_api.arv2.calls.CallSpec` handed to the
:class:`~clue_api.arv2.calls.ProviderCaller` the client was constructed with.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from pydantic import SecretStr

from clue_api.arv2.calls import (
    CallResult,
    CallSpec,
    CostReading,
    ProviderCaller,
    SpendEstimate,
)
from clue_api.arv2.exa_client import EXA_BASE_URL
from clue_api.arv2.transport import HttpRequest, HttpResponse, json_request

PROVIDER = "exa_websets"

#: The Websets API lives under its own version path, beside the synchronous ``/search``.
WEBSETS_BASE_PATH = "/websets/v0/websets"
#: Exa Imports: our own list of companies, which a search can ``exclude`` (spec 2026-10-16 §4.6).
IMPORTS_PATH = "/websets/v0/imports"

#: Websets' price list, in credits, for one result that satisfied every criterion. Rows that
#: failed a criterion are returned and are **not** charged.
CREDITS_PER_MATCH = 10

#: Websets' price for the recall estimate a search is created with (``recall: true``), per search.
RECALL_CREDITS = 5

#: The items endpoint's page size. 100 is its documented maximum, and a webset the lane creates
#: asks for tens of results, so this is normally one page.
ITEMS_PAGE_LIMIT = 100

#: A runaway guard on the cursor walk, not a cap on the answer: at 100 items a page this allows
#: 10 000 items, far past anything an ARV2 discovery run asks for. A provider that kept answering
#: ``hasMore: true`` with the same cursor would otherwise page for ever.
MAX_ITEM_PAGES = 100

#: Creating, reading or extending a webset is a short JSON exchange — the *work* happens between
#: calls, and is waited for by polling :meth:`ExaWebsetsClient.get`.
WEBSETS_TIMEOUT_S = 60.0

#: One items page carries up to 100 company records with their page content, so it is both the
#: biggest and the slowest body this client reads.
ITEMS_TIMEOUT_S = 180.0

__all__ = [
    "CREDITS_PER_MATCH",
    "IMPORTS_PATH",
    "ExaImportError",
    "ImportHandle",
    "ImportStatus",
    "import_csv",
    "ITEMS_PAGE_LIMIT",
    "ITEMS_TIMEOUT_S",
    "MAX_ITEM_PAGES",
    "PROVIDER",
    "RECALL_CREDITS",
    "WEBSETS_BASE_PATH",
    "WEBSETS_TIMEOUT_S",
    "ExaWebsetsClient",
    "WebsetItem",
    "WebsetItemsResult",
    "WebsetSearchView",
    "WebsetView",
    "is_all_green",
    "newly_priced",
    "websets_halt_rule",
    "websets_items_cost",
]


# -- value types -------------------------------------------------------------------------------


@dataclass(frozen=True)
class WebsetSearchView:
    """One search inside a webset: what it was asked for, and how it is going.

    ``found``/``analyzed`` are the poll surface — "15 found out of 333 candidates analysed" is
    what tells a driver whether a webset is progressing or stuck. ``criteria_success_rates``
    carries each criterion with the share of analysed candidates that satisfied it (``None``
    until Exa has computed one), which is what makes a criterion that rejects everything visible
    as a *criterion* problem rather than an empty market.
    """

    search_id: str
    status: str
    count: int
    found: int | None
    analyzed: int | None
    recall_estimate: int | None
    criteria_success_rates: tuple[tuple[str, float | None], ...]


class ExaImportError(RuntimeError):
    """Exa refused an Import step; the caller goes on without it (the domain skip still applies)."""


@dataclass(frozen=True)
class ImportHandle:
    import_id: str
    upload_url: str


@dataclass(frozen=True)
class ImportStatus:
    """An Import as Exa last described it: its ``status`` and ``count``, the rows Exa read from the
    file (``None`` while Exa has not said). ``completed`` with ``count`` 0 is an Import that holds
    nothing and so excludes nothing."""

    status: str
    count: int | None


def import_csv(domains: Sequence[str]) -> bytes:
    """The Import file: a ``url`` column, one ``https://<domain>`` per distinct domain, sorted so
    the same list is the same bytes."""
    rows = "".join(f"https://{domain}\n" for domain in sorted(set(domains)))
    return f"url\n{rows}".encode()


@dataclass(frozen=True)
class WebsetView:
    """A webset as Exa last described it, plus the references that make the call auditable."""

    webset_id: str
    status: str
    searches: tuple[WebsetSearchView, ...]
    raw_ref: str | None
    ledger_row_id: str
    #: Exa's reason when the call was not a 2xx, else ``None``. A view with an error describes
    #: nothing: its id, status and searches are whatever an error body happened to contain.
    error: str | None = None


@dataclass(frozen=True)
class WebsetItem:
    """One company Websets found, with the per-criterion verdicts it was kept or failed on.

    The mapped fields are the ones a discovery driver reads; ``raw`` is the whole item exactly as
    Exa returned it, so nothing this mapper does not model is lost. ``evaluations`` stays in
    Exa's own shape (``criterion``/``satisfied``/``reasoning``/``references``) rather than being
    reduced to booleans: the reasoning and the references are the evidence behind a verdict, and
    a gate decision recorded without them cannot be audited later.
    """

    item_id: str
    search_id: str | None
    url: str
    name: str
    description: str | None
    hq_city: str | None
    hq_state: str | None
    hq_country_code: str | None
    employees: int | None
    revenue_annual: int | None
    funding_total: int | None
    evaluations: tuple[Mapping[str, Any], ...]
    raw: Mapping[str, Any]
    #: ``properties.company.logoUrl`` as Exa returned it — a LinkedIn company mark for most
    #: companies, a site-hosted image (often a social banner, not a logo) for the rest. The
    #: discovery driver keeps only the marks it trusts; see ``logo_resolution.websets_mark_url``.
    logo_url: str | None = None


@dataclass(frozen=True)
class WebsetItemsResult:
    """Every item of a webset, and what reading them cost.

    One :class:`WebsetItemsResult` is several calls — one per cursor page — so it carries the
    references of all of them (``raw_refs``/``ledger_row_ids``) and the sum of their costs rather
    than a single :class:`~clue_api.arv2.calls.CallCost`.
    """

    items: tuple[WebsetItem, ...]
    all_green: int
    credits_est: int
    cost_usd: Decimal
    raw_refs: tuple[str, ...]
    ledger_row_ids: tuple[str, ...]
    #: Exa's reason when a page was not a 2xx; the walk stops there and ``items`` holds only the
    #: pages before it.
    error: str | None = None
    #: The ids of the all-green rows THIS read paid for — every id not already in the caller's
    #: ``priced_item_ids``. The caller adds them to that set so the next read of the same webset
    #: prices only what is new; ``all_green``/``credits_est``/``cost_usd`` count exactly these.
    priced_item_ids: tuple[str, ...] = ()


# -- reading the response ----------------------------------------------------------------------


def _body_json(response: HttpResponse) -> dict[str, Any]:
    """The response body as a dict, or an empty dict — never an exception, never a guess."""
    try:
        parsed = json.loads(response.body)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object) -> int | None:
    """An integer Exa reported, or ``None``. ``bool`` is not a number here."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def _recall_estimate(search: Mapping[str, Any]) -> int | None:
    """Exa's estimate of how many companies in total match this search: ``recall.expected.total``.

    ``recall`` is ``null`` until Exa has computed it and absent when the search did not ask for
    it; both read as ``None``. Recorded from the live API (webset of run ``f1549f76``,
    2026-09-16): ``{"expected": {"total": 300, "confidence": "medium", "bounds": {"min": 160,
    "max": 650}}, "reasoning": "..."}``.
    """
    expected = _mapping(_mapping(search.get("recall")).get("expected"))
    return _int(expected.get("total"))


def _search_view(search: Mapping[str, Any]) -> WebsetSearchView:
    progress = _mapping(search.get("progress"))
    criteria = search.get("criteria")
    rates: list[tuple[str, float | None]] = []
    if isinstance(criteria, list):
        for criterion in criteria:
            description = _str(_mapping(criterion).get("description"))
            if description is None:
                continue
            rates.append((description, _float(_mapping(criterion).get("successRate"))))
    return WebsetSearchView(
        search_id=_str(search.get("id")) or "",
        status=_str(search.get("status")) or "unknown",
        count=_int(search.get("count")) or 0,
        found=_int(progress.get("found")),
        analyzed=_int(progress.get("analyzed")),
        recall_estimate=_recall_estimate(search),
        criteria_success_rates=tuple(rates),
    )


def _searches(body: Mapping[str, Any]) -> tuple[WebsetSearchView, ...]:
    """Every search on a webset body."""
    searches = body.get("searches")
    if isinstance(searches, list):
        return tuple(_search_view(_mapping(search)) for search in searches)
    return ()


def _webset_view(result: CallResult, *, fallback_id: str | None = None) -> WebsetView:
    """Map a webset response into the one view the driver reads."""
    body = _body_json(result.response)
    return WebsetView(
        webset_id=_str(body.get("id")) or fallback_id or "",
        status=_str(body.get("status")) or "unknown",
        searches=_searches(body),
        raw_ref=result.raw_ref,
        ledger_row_id=result.ledger_row_id,
        error=_refusal(result.response),
    )


def _refusal(response: HttpResponse) -> str | None:
    """Exa's own words for a non-2xx answer, or ``None`` for a 2xx."""
    if 200 <= response.status < 300:
        return None
    return f"http {response.status}: {_error_message(response)}"


def _evaluations(item: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    evaluations = item.get("evaluations")
    if not isinstance(evaluations, list):
        return ()
    return tuple(evaluation for evaluation in evaluations if isinstance(evaluation, Mapping))


def is_all_green(item: Mapping[str, Any]) -> bool:
    """Did this row satisfy every criterion it was evaluated against — the billed shape?

    An item with *no* evaluations counts as green, matching what Exa charges for: a webset
    created with no criteria still bills ten credits for each result it found, and there is
    nothing there to fail. Erring the other way would under-report real spend.
    """
    return all(evaluation.get("satisfied") == "yes" for evaluation in _evaluations(item))


def _item_view(item: Mapping[str, Any]) -> WebsetItem:
    properties = _mapping(item.get("properties"))
    company = _mapping(properties.get("company"))
    headquarters = _mapping(company.get("headquarters"))
    financials = _mapping(company.get("financials"))
    return WebsetItem(
        item_id=_str(item.get("id")) or "",
        search_id=_str(item.get("sourceId")),
        url=_str(properties.get("url")) or "",
        name=_str(company.get("name")) or "",
        description=_str(properties.get("description")),
        hq_city=_str(headquarters.get("city")),
        hq_state=_str(headquarters.get("state")),
        hq_country_code=_str(headquarters.get("countryCode")),
        employees=_int(company.get("employees")),
        revenue_annual=_int(financials.get("revenueAnnual")),
        funding_total=_int(financials.get("fundingTotal")),
        evaluations=_evaluations(item),
        raw=item,
        logo_url=_str(company.get("logoUrl")),
    )


def _page_items(body: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    data = body.get("data")
    if not isinstance(data, list):
        return ()
    return tuple(row for row in data if isinstance(row, Mapping))


# -- money -------------------------------------------------------------------------------------


def websets_items_cost(all_green: int, usd_per_credit: Decimal) -> Decimal:
    """What a page of results cost: ten credits per all-green row, at the account's credit rate.

    The rate is a parameter rather than a constant because it is a *contract* number — a plan's
    price per credit — and pinning one here would silently misreport every account on another.
    """
    return Decimal(all_green * CREDITS_PER_MATCH) * usd_per_credit


def newly_priced(
    page: Sequence[Mapping[str, Any]], already_priced: frozenset[str]
) -> tuple[int, tuple[str, ...]]:
    """The all-green rows of one page that have not been paid for yet, and their ids.

    Websets charges when a *search produces a result*, not when a page is read — but the page is
    the only place the bill is visible, so reading the same webset again (every poll, every resume)
    shows every row a second time. Pricing those rows twice
    would over-report real spend on the exact number §8's exit gate divides by. A row Exa gave no
    id for cannot be recognised on a later read, so it is priced every time: over-reporting one
    unidentifiable row is the safe direction, silently dropping it is not.
    """
    count = 0
    ids: list[str] = []
    for item in page:
        if not is_all_green(item):
            continue
        item_id = _str(item.get("id")) or ""
        if item_id and item_id in already_priced:
            continue
        count += 1
        if item_id:
            ids.append(item_id)
    return count, tuple(ids)


def _items_cost_reader(
    usd_per_credit: Decimal, already_priced: frozenset[str]
) -> Callable[[HttpResponse], CostReading]:
    """The cost reader for one items page, closing over the credit rate and what is already paid.

    Websets does not meter a call in its response the way ``/search`` does — the page *is* the
    bill, and reading it is the only place the lane can know what a webset charged. The reading
    carries both the credits (the unit Exa charges in) and their dollar value, and counts only the
    rows this run has not already been charged for (:func:`newly_priced`).
    """

    def read(response: HttpResponse) -> CostReading:
        page = _page_items(_body_json(response))
        all_green, _ = newly_priced(page, already_priced)
        return CostReading(
            cost_usd=websets_items_cost(all_green, usd_per_credit),
            credits=Decimal(all_green * CREDITS_PER_MATCH),
            extras={"all_green": all_green, "items": len(page)},
        )

    return read


def _create_cost_reader(
    usd_per_credit: Decimal, *, recall: bool
) -> Callable[[HttpResponse], CostReading]:
    """The cost of creating a webset: the recall estimate's credits when it was asked for.

    Only a webset Exa actually created is charged — a refused create sold nothing.
    """

    def read(response: HttpResponse) -> CostReading:
        if not recall or not 200 <= response.status < 300:
            return _zero_cost_reader(response)
        return CostReading(
            cost_usd=Decimal(RECALL_CREDITS) * usd_per_credit,
            credits=Decimal(RECALL_CREDITS),
            extras={"recall_credits": RECALL_CREDITS},
        )

    return read


def _zero_cost_reader(response: HttpResponse) -> CostReading:
    """Reading, extending or cancelling a webset is free; only its results are charged.

    A reader that returns an explicit zero rather than no reader at all is the difference between
    "this call cost nothing" and "we never asked" — and, crucially, it stops the wrapper falling
    back to the pre-spend estimate, which for a create is the whole webset's worst-case bill.
    """
    return CostReading(cost_usd=Decimal(0), credits=Decimal(0))


def _error_message(response: HttpResponse) -> str:
    """The provider's own words for why it refused, or the bare status when it gave none.

    ``message`` first: Exa's validation refusals carry a generic ``error`` ("Validation Error")
    beside the ``message`` that says what was wrong.
    """
    body = _body_json(response)
    for key in ("message", "error", "detail"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = value.get("message")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return f"http {response.status}"


def websets_halt_rule(response: HttpResponse) -> str | None:
    """Money truth (master plan §2 item 3): does this response prove Websets will not sell?

    A 402 (out of credits) or a 401 (the key is not accepted) will answer the same way to every
    subsequent call, so the provider is latched rather than retried. A 404 — "no such webset" —
    is a request problem, not a wallet problem, and must not take the whole provider offline.
    """
    if response.status in (401, 402):
        return f"exa websets: {_error_message(response)}"
    return None


# -- the client --------------------------------------------------------------------------------


class ExaWebsetsClient:
    """Websets' operations, each one :class:`CallSpec` through the caller it was given."""

    def __init__(
        self,
        caller: ProviderCaller,
        api_key: SecretStr,
        *,
        usd_per_credit: Decimal,
        base_url: str = EXA_BASE_URL,
    ) -> None:
        self._caller = caller
        self._api_key = api_key
        self._usd_per_credit = usd_per_credit
        self._base_url = base_url.rstrip("/")

    def create(
        self,
        *,
        query: str,
        count: int,
        criteria: Sequence[str],
        external_id: str,
        title: str,
        exclude_webset_ids: Sequence[str] = (),
        recall: bool = True,
        exclude_import_ids: Sequence[str] = (),
    ) -> WebsetView:
        """Create a webset with one search. Returns immediately; the work happens after.

        ``externalId`` is the caller's own key for this webset, which is what makes a re-read after
        a crash a lookup (:meth:`find`) rather than a second, separately billed webset.

        ``exclude_webset_ids`` are earlier websets whose companies this search must not find again
        — and so must not charge for again. A whole webset is the smallest thing Exa's ``exclude``
        accepts (``webset`` or ``import``; a single search was refused with a 400).
        """
        search: dict[str, Any] = {
            "query": query,
            "count": count,
            "entity": {"type": "company"},
            "criteria": [{"description": description} for description in criteria],
        }
        exclude = [{"source": "webset", "id": webset_id} for webset_id in exclude_webset_ids]
        exclude += [{"source": "import", "id": import_id} for import_id in exclude_import_ids]
        if exclude:
            search["exclude"] = exclude
        if recall:
            # Absent unless asked for: ``recall`` makes Exa estimate how many companies match the
            # search in total, and it costs :data:`RECALL_CREDITS`, so the caller opts into it.
            search["recall"] = True
        estimate = self._search_estimate(count)
        if recall:
            recall_credits = Decimal(RECALL_CREDITS)
            estimate = SpendEstimate(
                usd=estimate.usd + recall_credits * self._usd_per_credit,
                credits=estimate.credits + recall_credits,
            )
        result = self._call(
            operation="create",
            label="websets-create",
            method="POST",
            path=WEBSETS_BASE_PATH,
            body={"title": title, "externalId": external_id, "search": search},
            estimate=estimate,
            cost_reader=_create_cost_reader(self._usd_per_credit, recall=recall),
            timeout_s=WEBSETS_TIMEOUT_S,
        )
        return _webset_view(result)

    def create_import(self, *, csv_bytes: bytes, count: int, title: str) -> ImportHandle:
        """Open an Import for ``csv_bytes`` (see :func:`import_csv`). Free. The file itself goes up
        with :meth:`upload_import` to the address Exa returns, within the hour it stays valid."""
        result = self._call(
            operation="import-create",
            label="websets-import-create",
            method="POST",
            path=IMPORTS_PATH,
            body={
                "format": "csv",
                "entity": {"type": "company"},
                "count": count,
                "size": len(csv_bytes),
                "title": title,
                # The URL column, by its position counted from 0. Exa's documented example shows 1,
                # but 1 names a column this file does not have, and Exa then completes the Import
                # having read none of its rows (live, 2026-10-16: 0 of 24 read at 1, 24 of 24 at 0).
                "csv": {"identifier": 0},
            },
            estimate=SpendEstimate(),
            cost_reader=_zero_cost_reader,
            timeout_s=WEBSETS_TIMEOUT_S,
        )
        refusal = _refusal(result.response)
        body = _body_json(result.response)
        import_id, upload_url = _str(body.get("id")), _str(body.get("uploadUrl"))
        if refusal is not None or not import_id or not upload_url:
            raise ExaImportError(refusal or "exa returned no import id or upload url")
        return ImportHandle(import_id=import_id, upload_url=upload_url)

    def upload_import(self, *, upload_url: str, csv_bytes: bytes) -> None:
        """PUT the file to Exa's signed upload address. The address is not Exa's API, so the API
        key is never sent to it."""
        result = self._caller.call(
            CallSpec(
                provider=PROVIDER,
                operation="import-upload",
                label="websets-import-upload",
                request=HttpRequest(
                    method="PUT",
                    url=upload_url,
                    headers={"content-type": "text/csv"},
                    body=csv_bytes,
                    timeout_s=WEBSETS_TIMEOUT_S,
                ),
                estimate=SpendEstimate(),
                cost_reader=_zero_cost_reader,
                max_attempts=1,
            )
        )
        if not 200 <= result.response.status < 300:
            raise ExaImportError(f"import upload refused: http {result.response.status}")

    def get_import(self, import_id: str) -> ImportStatus:
        """The Import's status (``pending``, ``processing``, ``completed``, ``failed`` or
        ``canceled``) and how many rows Exa read from its file."""
        result = self._call(
            operation="import-get",
            label="websets-import-get",
            method="GET",
            path=f"{IMPORTS_PATH}/{import_id}",
            body=None,
            estimate=SpendEstimate(),
            cost_reader=_zero_cost_reader,
            timeout_s=WEBSETS_TIMEOUT_S,
        )
        refusal = _refusal(result.response)
        if refusal is not None:
            raise ExaImportError(refusal)
        body = _body_json(result.response)
        count = body.get("count")
        return ImportStatus(
            status=_str(body.get("status")) or "unknown",
            count=count if isinstance(count, int) and not isinstance(count, bool) else None,
        )

    def cancel(self, webset_id: str) -> WebsetView:
        """Stop every search still running on a webset. Free; Exa marks the webset ``idle``.

        What Exa had already found before the cancel is still billed, so the caller reads the
        webset once more afterwards to put those rows on the ledger.
        """
        result = self._call(
            operation="cancel",
            label="websets-cancel",
            method="POST",
            path=f"{WEBSETS_BASE_PATH}/{webset_id}/cancel",
            body=None,
            estimate=SpendEstimate(),
            cost_reader=_zero_cost_reader,
            timeout_s=WEBSETS_TIMEOUT_S,
        )
        return _webset_view(result, fallback_id=webset_id)

    def find(self, external_id: str) -> WebsetView | None:
        """The webset created under this ``externalId``, or ``None`` when Exa has none (a 404).

        Exa reads a webset by its id or its external id, so an attempt that died between asking
        Exa for a webset and recording its id finds it again here instead of buying another.
        """
        result = self._call(
            operation="get",
            label="websets-find",
            method="GET",
            path=f"{WEBSETS_BASE_PATH}/{quote(external_id, safe='')}",
            body=None,
            estimate=SpendEstimate(),
            cost_reader=_zero_cost_reader,
            timeout_s=WEBSETS_TIMEOUT_S,
        )
        if result.response.status == 404:
            return None
        return _webset_view(result)

    def get(self, webset_id: str) -> WebsetView:
        """Read a webset's current state — the poll surface, free and body-less."""
        result = self._call(
            operation="get",
            label="websets-get",
            method="GET",
            path=f"{WEBSETS_BASE_PATH}/{webset_id}",
            body=None,
            estimate=SpendEstimate(),
            cost_reader=_zero_cost_reader,
            timeout_s=WEBSETS_TIMEOUT_S,
        )
        return _webset_view(result, fallback_id=webset_id)

    def items(
        self, webset_id: str, *, priced_item_ids: frozenset[str] = frozenset()
    ) -> WebsetItemsResult:
        """Every item of a webset, following ``nextCursor`` until ``hasMore`` is false.

        This is the billed call: each page's cost reader prices that page's all-green rows, and
        the result sums them, so "what did this webset cost" is the sum of rows the ledger
        already holds rather than a number computed twice.

        ``priced_item_ids`` is what the caller has already been charged for on this webset. A
        webset is read on every poll and again by a resumed attempt, and every read returns every
        row. Rows named here are still returned; they are simply not priced a second time.
        The rows this read did pay for come back on
        :attr:`WebsetItemsResult.priced_item_ids` for the caller to carry forward.
        """
        items: list[WebsetItem] = []
        raw_refs: list[str] = []
        ledger_row_ids: list[str] = []
        priced: list[str] = []
        already = set(priced_item_ids)
        cost = Decimal(0)
        all_green = 0
        cursor: str | None = None
        for _ in range(MAX_ITEM_PAGES):
            path = f"{WEBSETS_BASE_PATH}/{webset_id}/items?limit={ITEMS_PAGE_LIMIT}"
            if cursor:
                # An opaque cursor is base64 far more often than not, so ``+``, ``=`` and ``/``
                # are ordinary contents of one — and an unencoded ``+`` decodes server-side as a
                # space, which silently walks the wrong page.
                path = f"{path}&cursor={quote(cursor, safe='')}"
            result = self._call(
                operation="items",
                label="websets-items",
                method="GET",
                path=path,
                body=None,
                estimate=SpendEstimate(),
                cost_reader=_items_cost_reader(self._usd_per_credit, frozenset(already)),
                timeout_s=ITEMS_TIMEOUT_S,
            )
            if result.raw_ref is not None:
                raw_refs.append(result.raw_ref)
            ledger_row_ids.append(result.ledger_row_id)
            cost += result.call_cost.cost_usd or Decimal(0)
            error = _refusal(result.response)
            if error is not None:
                return WebsetItemsResult(
                    items=tuple(items),
                    all_green=all_green,
                    credits_est=all_green * CREDITS_PER_MATCH,
                    cost_usd=cost,
                    raw_refs=tuple(raw_refs),
                    ledger_row_ids=tuple(ledger_row_ids),
                    error=error,
                    priced_item_ids=tuple(priced),
                )
            body = _body_json(result.response)
            page = _page_items(body)
            # The same arithmetic the cost reader just ran on this page, against the same
            # already-priced set — so what the ledger was charged and what the caller carries
            # forward can never disagree.
            page_green, page_ids = newly_priced(page, frozenset(already))
            all_green += page_green
            priced.extend(page_ids)
            already.update(page_ids)
            items.extend(_item_view(item) for item in page)
            next_cursor = _str(body.get("nextCursor"))
            if not body.get("hasMore") or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return WebsetItemsResult(
            items=tuple(items),
            all_green=all_green,
            credits_est=all_green * CREDITS_PER_MATCH,
            cost_usd=cost,
            raw_refs=tuple(raw_refs),
            ledger_row_ids=tuple(ledger_row_ids),
            priced_item_ids=tuple(priced),
        )

    # -- internals -----------------------------------------------------------------------------

    def _search_estimate(self, count: int) -> SpendEstimate:
        """Law 2's reservation for a search: the worst case, every requested result all-green."""
        credits = Decimal(count * CREDITS_PER_MATCH)
        return SpendEstimate(usd=credits * self._usd_per_credit, credits=credits)

    def _call(
        self,
        *,
        operation: str,
        label: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        estimate: SpendEstimate,
        cost_reader: Callable[[HttpResponse], CostReading],
        timeout_s: float,
    ) -> CallResult:
        """Assemble the spec and hand it to the wrapper. This is the only egress in the module."""
        headers = {"x-api-key": self._api_key.get_secret_value()}
        url = f"{self._base_url}{path}"
        if body is None:
            # Never ``json_request(..., json_body=None)``: that puts the literal ``null`` on the
            # wire as the body of a GET.
            request = HttpRequest(method=method, url=url, headers=headers, timeout_s=timeout_s)
        else:
            request = json_request(
                method, url, headers=headers, json_body=dict(body), timeout_s=timeout_s
            )
        return self._caller.call(
            CallSpec(
                provider=PROVIDER,
                operation=operation,
                label=label,
                request=request,
                estimate=estimate,
                cost_reader=cost_reader,
                halt_rule=websets_halt_rule,
            )
        )
