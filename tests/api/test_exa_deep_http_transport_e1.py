"""Provider-free tests for E1's dormant real HTTP transport boundary."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from clue_api.exa_deep_acquisition import ExaDeepHttpAcquisitionTransport
from clue_config import Secrets
from clue_core import AccountEntity, RetryableResolverError, new_entity_id
from clue_research.resolvers.exa import (
    ExaDeepRequestFailure,
    ExaDeepSearchRequest,
    compile_exa_deep_request,
)
from clue_research.resolvers.exa.deep_contract import ExaDeepFailureClass, ExaDeepFieldSpec
from clue_research.resolvers.http import ProviderResponseError


def _request() -> ExaDeepSearchRequest:
    return compile_exa_deep_request(
        AccountEntity(
            id=new_entity_id(),
            canonical_name="Cascade Gastroenterology",
            primary_domain="cascade.example",
            workspace_id="ws-e1-http",
        ),
        (
            ExaDeepFieldSpec(
                field_key="account.operational_pain",
                value_schema={"type": "string"},
            ),
        ),
        research_intent="operational evidence",
    )


def _secrets() -> Secrets:
    return Secrets(exa_api_key=SecretStr("test"), _env_file=None)


def test_http_transport_dispatches_once_with_no_wrapper_retry() -> None:
    calls: list[dict[str, Any]] = []

    def http(url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"url": url, **kwargs})
        return {"requestId": "exa-e1-http", "output": {}, "costDollars": {"total": 0}}

    payload = ExaDeepHttpAcquisitionTransport(secrets=_secrets(), http=http).search(_request())
    assert payload["requestId"] == "exa-e1-http"
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["retries"] == 0
    assert calls[0]["json_body"]["type"] == "deep-reasoning"
    assert calls[0]["headers"]["x-api-key"] == "test"


def test_http_transport_classifies_missing_credential_before_dispatch() -> None:
    transport = ExaDeepHttpAcquisitionTransport(
        secrets=Secrets(exa_api_key=None, _env_file=None),
        http=lambda *_args, **_kwargs: pytest.fail("missing credential must not dispatch"),
    )
    with pytest.raises(ExaDeepRequestFailure) as caught:
        transport.search(_request())
    assert caught.value.failure_class is ExaDeepFailureClass.HARD
    assert not caught.value.dispatched


@pytest.mark.parametrize(
    ("failure", "expected_class", "status_code"),
    [
        (
            ProviderResponseError("bad request", status_code=400),
            ExaDeepFailureClass.HARD,
            400,
        ),
        (
            ProviderResponseError("budget exhausted", status_code=402),
            ExaDeepFailureClass.BUDGET,
            402,
        ),
        (
            ProviderResponseError("unauthorized", status_code=401),
            ExaDeepFailureClass.HARD,
            401,
        ),
        (
            ProviderResponseError("forbidden", status_code=403),
            ExaDeepFailureClass.HARD,
            403,
        ),
        (
            ProviderResponseError("not found", status_code=404),
            ExaDeepFailureClass.HARD,
            404,
        ),
        (
            ProviderResponseError("rate limited", status_code=429),
            ExaDeepFailureClass.SPEND_UNKNOWN,
            429,
        ),
        (
            ProviderResponseError("server error", status_code=500),
            ExaDeepFailureClass.SPEND_UNKNOWN,
            500,
        ),
        (
            ProviderResponseError("unavailable", status_code=503),
            ExaDeepFailureClass.SPEND_UNKNOWN,
            503,
        ),
        (
            RetryableResolverError("timeout"),
            ExaDeepFailureClass.SPEND_UNKNOWN,
            None,
        ),
        (
            ProviderResponseError("malformed response"),
            ExaDeepFailureClass.SPEND_UNKNOWN,
            None,
        ),
    ],
)
def test_http_transport_preserves_post_dispatch_spend_classification(
    failure: Exception,
    expected_class: ExaDeepFailureClass,
    status_code: int | None,
) -> None:
    def http(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise failure

    transport = ExaDeepHttpAcquisitionTransport(secrets=_secrets(), http=http)
    with pytest.raises(ExaDeepRequestFailure) as caught:
        transport.search(_request())
    assert caught.value.failure_class is expected_class
    assert caught.value.dispatched
    assert caught.value.status_code == status_code


# --- the request goes through the spend layer (design 2026-10-31) ------------------------------


class _SpendTransport:
    def __init__(self, status: int, body: bytes) -> None:
        from clue_spend import HttpResponse

        self.response = HttpResponse(status=status, body=body)
        self.sent: list[Any] = []

    def send(self, request: Any) -> Any:
        self.sent.append(request)
        return self.response


def _caller(transport: _SpendTransport):
    from datetime import UTC, datetime

    from clue_spend import BufferedLedger, BufferedRawSink, ProviderCaller

    ledger = BufferedLedger()
    caller = ProviderCaller(
        transport=transport, raw_sink=BufferedRawSink(), ledger=ledger,
        now=lambda: datetime.now(UTC),
    )
    return caller, ledger


def test_an_exa_deep_402_through_the_spend_layer_is_ledgered_and_still_budget() -> None:
    from clue_api.exa_deep_acquisition import spend_caller

    spend = _SpendTransport(402, b'{"error":"You have exceeded your credits limit"}')
    caller, ledger = _caller(spend)
    transport = ExaDeepHttpAcquisitionTransport(secrets=_secrets())
    with spend_caller(caller), pytest.raises(ExaDeepRequestFailure) as caught:
        transport.search(_request())
    assert caught.value.failure_class is ExaDeepFailureClass.BUDGET
    assert caught.value.status_code == 402 and caught.value.dispatched
    (request,) = spend.sent
    assert request.method == "POST" and request.headers["x-api-key"] == "test"
    (row,) = [row for row in ledger.rows if row.phase == "result"]
    assert row.provider == "exa"
    assert row.extras["provider_failure"]["reason"] == "credits_exhausted"


def test_an_exa_deep_success_through_the_spend_layer_returns_the_payload() -> None:
    from clue_api.exa_deep_acquisition import spend_caller

    spend = _SpendTransport(200, b'{"requestId": "exa-ledgered", "output": {}}')
    caller, ledger = _caller(spend)
    with spend_caller(caller):
        payload = ExaDeepHttpAcquisitionTransport(secrets=_secrets()).search(_request())
    assert payload["requestId"] == "exa-ledgered"
    assert [row.outcome for row in ledger.rows if row.phase == "result"] == ["ok"]


def test_the_coordinator_drains_the_dispatch_it_ledgered() -> None:
    """The coordinator opens the caller around the threaded dispatch and drains it afterwards."""
    import asyncio
    from contextlib import asynccontextmanager

    from clue_api import exa_deep_acquisition as module

    drained: list[Any] = []

    async def fake_drain(conn: Any, *, raw: Any, ledger: Any, artifacts: Any, stamp: Any) -> None:
        drained.append((conn, [row.provider for row in ledger.rows], stamp.workspace_id))

    @asynccontextmanager
    async def conn_factory():
        yield "conn"

    spend = _SpendTransport(200, b'{"requestId": "x", "output": {}}')
    transport = ExaDeepHttpAcquisitionTransport(secrets=_secrets())
    original = module.drain_provider_calls
    module.drain_provider_calls = fake_drain  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            module.dispatch_ledgered(
                transport, _request(), conn_factory=conn_factory, workspace_id="ws-e1-http",
                spend_transport=spend,
            )
        )
    finally:
        module.drain_provider_calls = original  # type: ignore[assignment]
    assert payload["requestId"] == "x"
    assert drained == [("conn", ["exa", "exa"], "ws-e1-http")]
