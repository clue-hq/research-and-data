"""The Adyntel LinkedIn ad-library provider (ruling D3) — the v1 implementation of the seam.

**This module is the only place in the repository that knows Adyntel exists.** Everything
else goes through :func:`lumen_ingestion.ad_library.provider.resolve_provider`.

The endpoint contract, as verified against the frozen Ramp fetch (spec §2, ``.context/
ramp-ads/``):

    POST {base_url}/linkedin
    {"api_key": …, "email": …, "company_domain": … | "linkedin_page_id": …,
     "continuation_token": …?, "date_filter": …?}
    -> {"page_id", "continuation_token", "is_last_page", "total_ads", "ads": [...]}

One page is ~24–25 ads and costs ~1 credit.

**``all_ads`` is never sent, and cannot be.** The vendor's ``all_ads: true`` mode delivers
every ad the page has ever run to a *webhook*, asynchronously, with no way to stop it once
started — an unbounded, unstoppable spend against a body this code would never see the reply
to. The request builder below has no branch that can produce that key, and a test asserts the
absence rather than trusting the reading.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from py_lumen_config import settings

from .provider import (
    AdLibraryAd,
    AdLibraryCredentialsMissing,
    AdLibraryError,
    AdLibraryPage,
)

__all__ = ["ADYNTEL_PROVIDER_NAME", "AdyntelProvider"]

JsonObject = dict[str, Any]

ADYNTEL_PROVIDER_NAME = "adyntel"

#: Keys this provider will never put on the wire, whatever it is asked for. ``all_ads``
#: starts an unstoppable webhook delivery (see the module docstring); the guard is here, at
#: the one place a body is built, so it holds for every caller.
FORBIDDEN_REQUEST_KEYS = frozenset({"all_ads"})

#: How much of an error body is threaded into the typed failure — enough to name the cause,
#: bounded so a vendor HTML error page cannot flood a job's error column.
FAILURE_EXCERPT_MAX = 300


class AdyntelProvider:
    """One page of an advertiser's LinkedIn ads, per call.

    Credentials are read from the environment at construction (``ADYNTEL_API_KEY`` /
    ``ADYNTEL_EMAIL``) and refused loudly when absent — see
    :class:`~.provider.AdLibraryCredentialsMissing` for why that happens before any request
    is built. They are held on the instance and never logged; the only place the key reaches
    is the request body.
    """

    name = ADYNTEL_PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str | None = None,
        email: str | None = None,
        base_url: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else settings.adyntel_api_key).strip()
        self._email = (email if email is not None else settings.adyntel_email).strip()
        self._base_url = (
            base_url if base_url is not None else settings.adyntel_base_url
        ).strip().rstrip("/")
        self._timeout_s = (
            timeout_s if timeout_s is not None else settings.adyntel_timeout_s
        )
        if not self._api_key or not self._email:
            raise AdLibraryCredentialsMissing(
                ADYNTEL_PROVIDER_NAME, ("ADYNTEL_API_KEY", "ADYNTEL_EMAIL")
            )

    # -- the seam ----------------------------------------------------------------------

    def fetch_page(
        self,
        *,
        company_domain: str | None = None,
        page_id: str | None = None,
        continuation_token: str | None = None,
        date_filter: str | None = None,
    ) -> AdLibraryPage:
        body = self.build_request_body(
            company_domain=company_domain,
            page_id=page_id,
            continuation_token=continuation_token,
            date_filter=date_filter,
        )
        payload = self._post(body)
        return self.parse_page(payload)

    # -- the two halves, exposed so they can be tested without a transport --------------

    def build_request_body(
        self,
        *,
        company_domain: str | None = None,
        page_id: str | None = None,
        continuation_token: str | None = None,
        date_filter: str | None = None,
    ) -> JsonObject:
        """The exact JSON body for one page request.

        Exactly one advertiser selector is required. Accepting both would leave the vendor to
        break the tie, and accepting neither would spend a credit on a request that cannot
        mean anything — both are refused here rather than discovered from a 4xx.
        """
        domain = (company_domain or "").strip()
        page = (page_id or "").strip()
        if bool(domain) == bool(page):
            raise AdLibraryError(
                "ad_library.bad_request",
                "exactly one of company_domain / page_id identifies the advertiser",
            )
        body: JsonObject = {"api_key": self._api_key, "email": self._email}
        if domain:
            body["company_domain"] = domain
        else:
            body["linkedin_page_id"] = page
        if continuation_token:
            body["continuation_token"] = continuation_token
        if date_filter:
            body["date_filter"] = date_filter
        # Belt and braces over the module docstring's promise: this is a closed builder with
        # no `all_ads` branch, and it stays that way even if someone adds one.
        assert not (FORBIDDEN_REQUEST_KEYS & set(body)), "all_ads must never be requested"
        return body

    def parse_page(self, payload: JsonObject) -> AdLibraryPage:
        """Normalize one vendor response into the seam's typed page.

        ``ads`` that are not objects are dropped rather than raising: one malformed record in
        a page of two dozen must not cost the whole harvest.
        """
        if not isinstance(payload, dict):
            raise AdLibraryError(
                "ad_library.malformed_response",
                f"expected a JSON object from the ad library, got {type(payload).__name__}",
            )
        raw_ads = payload.get("ads")
        records = raw_ads if isinstance(raw_ads, list) else []
        ads = tuple(
            AdLibraryAd.from_wire(record) for record in records if isinstance(record, dict)
        )
        total = payload.get("total_ads")
        return AdLibraryPage(
            page_id=_optional_str(payload.get("page_id")),
            total_ads=int(total) if isinstance(total, int) and not isinstance(total, bool) else None,
            ads=ads,
            continuation_token=_optional_str(payload.get("continuation_token")),
            is_last_page=bool(payload.get("is_last_page")),
            provider=ADYNTEL_PROVIDER_NAME,
            raw_meta={
                key: payload.get(key)
                for key in ("keyword", "countries")
                if payload.get(key) is not None
            },
        )

    # -- transport ---------------------------------------------------------------------

    def _post(self, body: JsonObject) -> JsonObject:
        """One HTTP round trip. ``httpx`` is imported here so the seam stays transport-free.

        No retry loop: a page costs a credit, so a failed page is reported rather than
        silently paid for twice (``max_attempts=1`` — the caller must not retry this one).
        The bounded harvest loop above decides what a failure means.

        The round trip goes through the unit of work's ``ProviderCaller``, so the credit it
        spends lands on ``provider_call_ledger`` as one reserved credit. Adyntel reports no cost
        of its own, so the row is ``cost_source=free`` with ``credits=1`` (spec ruling 6.5).
        """
        import json as _json  # lazy: only the real network path needs it

        from clue_spend import CallSpec, HttpRequest, SpendEstimate
        from lumen_api import spend

        request = HttpRequest(
            method="POST",
            url=f"{self._base_url}/linkedin",
            headers={"Content-Type": "application/json"},
            body=_json.dumps(body).encode("utf-8"),
            timeout_s=self._timeout_s,
        )
        try:
            response = spend.caller().call(
                CallSpec(
                    provider="adyntel",
                    operation="design.ad_library.harvest",
                    label="ad_library:linkedin page",
                    request=request,
                    estimate=SpendEstimate(credits=Decimal(1)),
                    max_attempts=1,
                    binary=False,
                )
            ).response
        except Exception as error:  # noqa: BLE001 - every transport failure is one typed code
            raise AdLibraryError(
                "ad_library.transport_error",
                f"{type(error).__name__}: {str(error)[:FAILURE_EXCERPT_MAX]}",
            ) from error
        if response.status >= 400:
            excerpt = response.body.decode("utf-8", "replace")[:FAILURE_EXCERPT_MAX]
            raise AdLibraryError(
                "ad_library.http_error",
                f"HTTP {response.status}: {excerpt}",
            )
        try:
            payload = _json.loads(response.body)
        except Exception as error:  # noqa: BLE001
            raise AdLibraryError(
                "ad_library.malformed_response",
                f"response was not JSON: {str(error)[:FAILURE_EXCERPT_MAX]}",
            ) from error
        return payload if isinstance(payload, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
