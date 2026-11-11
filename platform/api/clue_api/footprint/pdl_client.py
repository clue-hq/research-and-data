"""People Data Labs person enrichment: the X and Facebook handles PDL holds for a person.

``GET /v5/person/enrich`` with ``X-Api-Key``. A match costs one credit, about $0.28 at our plan
(ledger section 6, tested on 20 people: all X and Facebook handles found by any route, none wrong);
no match (HTTP 404) costs nothing. PDL's answer does not state the price, so a match is recorded
at that plan price.

Only the handle fields are kept (review C1): PDL's record also holds personal emails, phones, birth
dates and home addresses, so the body is trimmed by the call's ``raw_scrubber`` before it is stored
or read — the same law that drops AI Ark's birth dates. A failure is reported as one (review I5),
never as "no match"; out of credit (402) or a refused key (401) stops PDL for the caller.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, Field, SecretStr

from clue_spend.calls import CallSpec, CostReading, ProviderCaller
from clue_spend.errors import ProviderHalted, ProviderTransportError
from clue_spend.transport import HttpRequest, HttpResponse

PDL_PERSON_ENRICH_URL = "https://api.peopledatalabs.com/v5/person/enrich"
PDL_MATCH_USD = Decimal("0.28")
#: The only person fields kept from PDL's record.
KEPT_FIELDS = ("twitter_username", "twitter_url", "facebook_username", "facebook_url")


class PdlLookup(BaseModel):
    state: Literal["matched", "no_match", "failed"]
    #: The kept handle fields of a match.
    data: dict[str, Any] = Field(default_factory=dict)
    #: PDL's confidence in the match, 1 to 10.
    likelihood: int | None = None
    failure: str | None = None
    #: PDL refused to sell (``payment_required`` / ``auth_invalid``): stop asking it in this job.
    stopped: str | None = None


def keep_handles_only(value: object) -> object:
    """The raw scrubber: a PDL body with every person field but the handles removed."""
    if not isinstance(value, dict):
        return value
    kept: dict[str, Any] = {k: value[k] for k in ("status", "likelihood", "error") if k in value}
    data = value.get("data")
    if isinstance(data, dict):
        kept["data"] = {k: data[k] for k in KEPT_FIELDS if k in data}
    return kept


def pdl_halt_rule(response: HttpResponse) -> str | None:
    if response.status == 402:
        return "payment_required"
    if response.status == 401:
        return "auth_invalid"
    return None


def _cost(response: HttpResponse) -> CostReading:
    matched = response.status == 200
    return CostReading(
        cost_usd=PDL_MATCH_USD if matched else Decimal(0),
        credits=Decimal(1) if matched else Decimal(0),
    )


def _message(body: Any) -> str | None:
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else error
    return message[:200] if isinstance(message, str) and message else None


def pdl_person(
    caller: ProviderCaller,
    key: SecretStr,
    *,
    name: str,
    company: str | None,
    linkedin_url: str | None,
) -> PdlLookup:
    params = {"name": name, **({"company": company} if company else {})}
    if linkedin_url:
        params["profile"] = linkedin_url
    try:
        result = caller.call(
            CallSpec(
                provider="pdl",
                operation="person/enrich",
                label="footprint.pdl_person",
                request=HttpRequest(
                    "GET",
                    f"{PDL_PERSON_ENRICH_URL}?{urlencode(params)}",
                    headers={"X-Api-Key": key.get_secret_value()},
                    timeout_s=30,
                ),
                max_attempts=2,
                cost_reader=_cost,
                halt_rule=pdl_halt_rule,
                raw_scrubber=keep_handles_only,
            )
        )
    except ProviderHalted as halted:
        reason = halted.reason_code.removeprefix("latched:")
        return PdlLookup(state="failed", failure=f"PDL refused ({reason})", stopped=reason)
    except ProviderTransportError as exc:
        return PdlLookup(state="failed", failure=f"PDL did not answer ({str(exc)[:160]})")
    status = result.response.status
    try:
        body = json.loads(result.response.body)
    except ValueError:
        body = None
    if status == 404:
        return PdlLookup(state="no_match")
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        said = _message(body)
        return PdlLookup(state="failed", failure=f"HTTP {status}" + (f": {said}" if said else ""))
    likelihood = body.get("likelihood")
    return PdlLookup(
        state="matched",
        data=body["data"],
        likelihood=likelihood if isinstance(likelihood, int) else None,
    )
