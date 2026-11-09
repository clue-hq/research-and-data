"""One paid call to a treg catalog tool, through the spend wrapper.

treg (https://treg.to) runs third-party tools on its own provider accounts and bills our team per
call. A catalog tool is ``GET https://treg.to/call/<tool id>?<query>`` with the team token in
``X-Treg-Token`` (masked in every raw record). What the call cost is treg's own
``X-Treg-Cost-Micro`` header, in micro-USD; a provider refusal treg relays (any 4xx) costs nothing
and is returned to the caller to read, not raised. A 5xx or a dropped connection, after the
wrapper's retries, raises :class:`~clue_spend.errors.ProviderTransportError`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import urlencode

from pydantic import BaseModel, JsonValue, SecretStr

from clue_spend.calls import CallSpec, CostReading, ProviderCaller
from clue_spend.errors import ProviderTransportError
from clue_spend.transport import HttpRequest, HttpResponse

TREG_BASE_URL = "https://treg.to"


class TregReply(BaseModel):
    body: JsonValue
    cost_usd: float
    call_id: str | None
    status: int


def _header(response: HttpResponse, name: str) -> str | None:
    wanted = name.lower()
    return next((v for k, v in response.headers.items() if k.lower() == wanted), None)


def _cost_micro(response: HttpResponse) -> int | None:
    value = _header(response, "X-Treg-Cost-Micro")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _cost_reader(response: HttpResponse) -> CostReading:
    micro = _cost_micro(response)
    return CostReading(
        cost_usd=Decimal(micro) / Decimal(1_000_000) if micro is not None else None,
        provider_request_id=_header(response, "X-Treg-Call-Id"),
    )


def treg_call(
    caller: ProviderCaller,
    token: SecretStr,
    tool_id: str,
    query: dict[str, str | int],
    *,
    base_url: str = TREG_BASE_URL,
) -> TregReply:
    url = f"{base_url.rstrip('/')}/call/{tool_id}?{urlencode(query)}"
    result = caller.call(
        CallSpec(
            provider="treg",
            operation=tool_id,
            label=f"treg.{tool_id}",
            request=HttpRequest(
                "GET",
                url,
                headers={"X-Treg-Token": token.get_secret_value(), "Accept": "application/json"},
                timeout_s=120,
            ),
            cost_reader=_cost_reader,
        )
    )
    response = result.response
    if response.status >= 500:
        raise ProviderTransportError("treg", result.attempts, f"HTTP {response.status}")
    try:
        body: JsonValue = json.loads(response.body) if response.body else None
    except ValueError:
        body = response.body.decode("utf-8", errors="replace")
    micro = _cost_micro(response)
    return TregReply(
        body=body,
        cost_usd=micro / 1_000_000 if micro is not None else 0.0,
        call_id=_header(response, "X-Treg-Call-Id"),
        status=response.status,
    )
