"""People Data Labs person enrichment: the X and Facebook handles PDL holds for a person.

``GET /v5/person/enrich`` with ``X-Api-Key``. A match costs one credit, about $0.28 at our plan
(ledger section 6, tested on 20 people: all X and Facebook handles found by any route, none wrong);
no match (HTTP 404) costs nothing. PDL's answer does not state the price, so a match is recorded
at that plan price.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from pydantic import SecretStr

from clue_spend.calls import CallSpec, CostReading, ProviderCaller
from clue_spend.errors import ProviderTransportError
from clue_spend.transport import HttpRequest, HttpResponse

PDL_PERSON_ENRICH_URL = "https://api.peopledatalabs.com/v5/person/enrich"
PDL_MATCH_USD = Decimal("0.28")


def _cost(response: HttpResponse) -> CostReading:
    matched = response.status == 200
    return CostReading(
        cost_usd=PDL_MATCH_USD if matched else Decimal(0),
        credits=Decimal(1) if matched else Decimal(0),
    )


def pdl_person(
    caller: ProviderCaller,
    key: SecretStr,
    *,
    name: str,
    company: str | None,
    linkedin_url: str | None,
) -> dict[str, Any] | None:
    """The matched person's record, or ``None`` when PDL has no match or is unreachable."""
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
            )
        )
    except ProviderTransportError:
        return None
    if result.response.status != 200:
        return None
    try:
        body = json.loads(result.response.body)
    except ValueError:
        return None
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else None
