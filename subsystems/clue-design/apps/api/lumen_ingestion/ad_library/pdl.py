"""The People Data Labs company-identity resolver (W5/R3-A) — the v1 implementation.

**This module is the only place in the repository that knows People Data Labs exists.**
Everything else goes through
:func:`lumen_ingestion.ad_library.company_identity.resolve_company_identity_resolver`, exactly
as everything ad-library goes through ``resolve_provider`` and never names the fetch vendor.

The endpoint contract, per the vendor's documented Company Enrichment schema:

    GET {base}/v5/company/enrich?website=<domain>
    X-Api-Key: <key>
    Accept: application/json
    -> 200 {"status": 200, "name": …, "linkedin_id": …, "linkedin_url": …, …}
    -> 404 {"status": 404, "error": {...}}      # no company matched — an ANSWER, not a fault

One enrichment is one credit. There is no retry loop and no batch mode: the lane resolves one
advertiser per job, and a resolver that quietly spent a second credit on a failure would be
harder to reason about than one that reports the failure and lets the lane fall back.

**A 404 is a typed absence, not an error.** The vendor saying "I have no record of this domain"
is a real, useful answer; treating it as a fault would turn every unknown domain into a red
job. It returns ``None`` and the lane falls back to the ad library's own domain resolution,
recording that nothing independent verified the result.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from py_lumen_config import settings

from .company_identity import (
    CompanyIdentity,
    CompanyIdentityCredentialsMissing,
    CompanyIdentityError,
)

__all__ = ["PDL_ENRICH_PATH", "PDL_RESOLVER_NAME", "PdlCompanyIdentityResolver"]

JsonObject = dict[str, Any]

PDL_RESOLVER_NAME = "pdl"

#: The company-enrichment path appended to the configured base. Kept as a constant because the
#: base-url normalizer below has to be able to recognise it already being there.
PDL_ENRICH_PATH = "/v5/company/enrich"

#: How much of an error body is threaded into the typed failure — enough to name the cause,
#: bounded so a vendor HTML error page cannot flood a job's evidence.
FAILURE_EXCERPT_MAX = 300


def _normalize_base_url(base_url: str) -> str:
    """Accept either the API HOST or the full enrichment ENDPOINT as the configured base.

    Both forms are in live use and both are defensible readings of "base url": the design
    named the host (``https://api.peopledatalabs.com``) while the founder's own ``.env``
    already carries the full endpoint (``https://api.peopledatalabs.com/v5/company/enrich``).
    Appending the path blindly would turn the second form into a doubled path and a 404 that
    looked exactly like "no such company" — the quietest possible misconfiguration, and a
    close cousin of the R3-A failure this module was written to end.

    So the trailing enrichment path is stripped if present and re-appended by the caller. This
    is tolerance at the credentials seam, not a contract change: one endpoint is still built,
    and it is still the one the design named.
    """
    trimmed = base_url.strip().rstrip("/")
    if trimmed.lower().endswith(PDL_ENRICH_PATH):
        trimmed = trimmed[: -len(PDL_ENRICH_PATH)].rstrip("/")
    return trimmed


def _domain_of(value: str) -> str:
    """The bare host of whatever the caller called a domain.

    The onboarding request's ``company_domain`` is operator-typed and arrives as ``apollo.io``,
    ``www.apollo.io`` or ``https://apollo.io/pricing`` depending on who typed it. The vendor
    matches on a website host, so all three are folded to one here rather than each caller
    remembering to. Nothing is invented: a value with no host at all is returned as-is and the
    vendor gets to say it does not know it.
    """
    text = value.strip()
    if not text:
        return ""
    candidate = text if "//" in text else f"//{text}"
    host = (urlsplit(candidate).hostname or text).strip().lower()
    return host[4:] if host.startswith("www.") else host


class PdlCompanyIdentityResolver:
    """One domain → one company identity, per call.

    Credentials are read from the environment at construction (``PDL_API_KEY`` /
    ``PDL_BASE_URL``) and refused loudly when absent — see
    :class:`~.company_identity.CompanyIdentityCredentialsMissing` for why that happens before
    any request is built, and why the lane treats it as a degrade rather than a failure. The
    key is held on the instance, never logged, and reaches exactly one place: the request
    header.
    """

    name = PDL_RESOLVER_NAME

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else settings.pdl_api_key).strip()
        self._base_url = _normalize_base_url(
            base_url if base_url is not None else settings.pdl_base_url
        )
        self._timeout_s = timeout_s if timeout_s is not None else settings.pdl_timeout_s
        if not self._api_key:
            raise CompanyIdentityCredentialsMissing(PDL_RESOLVER_NAME, ("PDL_API_KEY",))

    # -- the seam ----------------------------------------------------------------------

    def resolve(self, domain: str) -> CompanyIdentity | None:
        host = _domain_of(domain)
        if not host:
            raise CompanyIdentityError(
                "company_identity.bad_request",
                "a company domain is required to resolve an advertiser identity",
            )
        payload = self._get(host)
        return self.parse_identity(host, payload) if payload is not None else None

    # -- the pure half, exposed so it can be tested without a transport ------------------

    @property
    def endpoint(self) -> str:
        """The one URL this resolver calls. A property so a test can pin it exactly."""
        return f"{self._base_url}{PDL_ENRICH_PATH}"

    def parse_identity(self, domain: str, payload: JsonObject) -> CompanyIdentity | None:
        """Normalize one vendor record into the seam's typed identity.

        A body that carries an error status, or that names neither the company nor a LinkedIn
        page, is a typed absence rather than a malformed-response error: the vendor answered,
        it just did not answer usefully, and the lane's fallback handles that fine.

        ``linkedin_id`` is coerced to a string. The vendor documents it as a string and serves
        it as one, but the value is a numeric page id and a JSON number would otherwise flow
        all the way into a request body as an int — where it would still work, and would make
        every id comparison in the lane subtly type-dependent.
        """
        if not isinstance(payload, dict):
            raise CompanyIdentityError(
                "company_identity.malformed_response",
                f"expected a JSON object from the identity resolver, got "
                f"{type(payload).__name__}",
            )
        status = payload.get("status")
        if isinstance(status, int) and status >= 400:
            return None
        identity = CompanyIdentity(
            domain=domain,
            # `name` is the designed field and stays the one that decides. `display_name` is
            # consulted ONLY when `name` is absent — a record carrying just the display form
            # would otherwise resolve to an identity with no name at all, which the advertiser
            # cross-check reads as "nothing to compare". It can never loosen a comparison that
            # a present `name` would have made: verified live 2026-08-27, apollo.io answers
            # `name: "apollo.io"` and `display_name: "Apollo.io"`, and both fold to one key.
            name=_optional_str(payload.get("name"))
            or _optional_str(payload.get("display_name")),
            linkedin_id=_optional_str(payload.get("linkedin_id")),
            linkedin_url=_optional_str(payload.get("linkedin_url")),
            provider=PDL_RESOLVER_NAME,
        )
        if identity.name is None and identity.linkedin_id is None:
            return None
        return identity

    # -- transport ---------------------------------------------------------------------

    def _get(self, domain: str) -> JsonObject | None:
        """One HTTP round trip, or ``None`` for a documented not-found.

        The round trip goes through the unit of work's spend caller, like the ad-library vendor's:
        the enrichment credit lands on ``provider_call_ledger`` and a refusal (a 402 when the PDL
        account is out of credits, as on 2026-10-31) opens a provider incident when the scope
        drains. No retry: one enrichment is one credit (``max_attempts=1``).
        """
        import json as _json  # lazy: only the real network path needs it
        from decimal import Decimal
        from urllib.parse import urlencode

        from clue_spend import CallSpec, HttpRequest, SpendEstimate
        from lumen_api import spend

        request = HttpRequest(
            method="GET",
            url=f"{self.endpoint}?{urlencode({'website': domain})}",
            headers={"X-Api-Key": self._api_key, "Accept": "application/json"},
            timeout_s=self._timeout_s,
        )
        try:
            response = spend.caller().call(
                CallSpec(
                    provider=PDL_RESOLVER_NAME,
                    operation="design.ad_library.identity",
                    label="ad_library:company identity",
                    request=request,
                    estimate=SpendEstimate(credits=Decimal(1)),
                    max_attempts=1,
                    binary=False,
                )
            ).response
        except Exception as error:  # noqa: BLE001 - every transport failure is one typed code
            raise CompanyIdentityError(
                "company_identity.transport_error",
                f"{type(error).__name__}: {str(error)[:FAILURE_EXCERPT_MAX]}",
            ) from error
        # A refusal (PDL out of credits, a rejected key) is written now, not when the job ends.
        spend.flush_if_refused(PDL_RESOLVER_NAME, response.status, response.body)
        if response.status == 404:
            # The vendor's documented "no company matched". An answer, not a fault.
            return None
        if response.status >= 400:
            excerpt = response.body.decode("utf-8", "replace")[:FAILURE_EXCERPT_MAX]
            raise CompanyIdentityError(
                "company_identity.http_error", f"HTTP {response.status}: {excerpt}"
            )
        try:
            payload = _json.loads(response.body)
        except Exception as error:  # noqa: BLE001
            raise CompanyIdentityError(
                "company_identity.malformed_response",
                f"response was not JSON: {str(error)[:FAILURE_EXCERPT_MAX]}",
            ) from error
        return payload if isinstance(payload, dict) else {}


def _optional_str(value: Any) -> str | None:
    """``None`` for absent/blank, a stripped string otherwise. Never ``"None"``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
