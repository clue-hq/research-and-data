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
