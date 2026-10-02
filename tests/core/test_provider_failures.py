from __future__ import annotations

from typing import get_args

import pytest

from clue_core import provider_failures
from clue_core.provider_failures import (
    ProviderFailure,
    classify_exception,
    classify_http,
    failure_code,
    parse_failure_code,
)

EXA_402 = (
    '{"requestId":"18ff","error":"You have exceeded your credits limit. '
    'Please top up to keep using Exa at dashboard.exa.ai","tag":"NO_MORE_CREDITS"}'
)
OPENROUTER_403 = (
    "{'error': {'message': 'Key limit exceeded (weekly limit). Manage it using "
    "https://openrouter.ai/workspaces/default/keys/3faff', 'code': 403}}"
)
WEBSETS_402 = '{"error":"payment_required","message":"Your plan requires payment"}'

AUTH_401 = '{"error":{"message":"No auth credentials found"}}'
FORBIDDEN_403 = '{"error":{"message":"Forbidden"}}'
SUSPENDED_403 = '{"error":{"message":"Your account has been suspended"}}'
RATE_LIMITED_429 = '{"error":{"message":"Rate limit exceeded"}}'


@pytest.mark.parametrize(
    ("provider", "status", "body", "kind", "reason"),
    [
        ("exa", 402, EXA_402, "refusal", "credits_exhausted"),
        ("exa_websets", 402, WEBSETS_402, "refusal", "credits_exhausted"),
        ("openrouter", 403, OPENROUTER_403, "refusal", "key_limit"),
        ("openrouter", 401, AUTH_401, "refusal", "auth_invalid"),
        ("openrouter", 403, FORBIDDEN_403, "refusal", "auth_invalid"),
        ("openrouter", 403, SUSPENDED_403, "refusal", "account_suspended"),
        ("openrouter", 429, RATE_LIMITED_429, "failure", "rate_limited"),
        ("exa", 503, "upstream unavailable", "failure", "server_error"),
        ("exa", 500, None, "failure", "server_error"),
    ],
)
def test_http_statuses_and_bodies_classify_as_the_spec_says(
    provider: str,
    status: int,
    body: str | None,
    kind: str,
    reason: str,
) -> None:
    failure = classify_http(provider, status, body)
    assert failure is not None
    assert (failure.provider, failure.kind, failure.reason) == (provider, kind, reason)
    assert failure.message and len(failure.message) <= 300


@pytest.mark.parametrize("status", [200, 201, 204, 400, 404, 409, 422])
def test_a_success_or_our_own_mistake_is_not_a_provider_failure(status: int) -> None:
    assert classify_http("exa", status, '{"error":"whatever"}') is None


def test_a_transport_failure_with_no_status_is_a_timeout() -> None:
    failure = classify_http("live_http", None, "connection reset by peer")
    assert failure == ProviderFailure("live_http", "failure", "timeout", "connection reset by peer")


class _SdkError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = {"error": {"message": message, "code": status_code}}


class PermissionDeniedError(_SdkError): ...


class RateLimitError(_SdkError): ...


class APITimeoutError(Exception): ...


class APIConnectionError(Exception): ...


def test_sdk_exceptions_classify_by_status_then_by_class_name() -> None:
    denied = classify_exception(
        "openrouter",
        PermissionDeniedError(
            403,
            "Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/x",
        ),
    )
    assert denied is not None and (denied.kind, denied.reason) == ("refusal", "key_limit")
    limited = classify_exception("openrouter", RateLimitError(429, "Rate limit exceeded"))
    assert limited is not None and (limited.kind, limited.reason) == ("failure", "rate_limited")
    assert classify_exception(
        "openrouter", APITimeoutError("Request timed out")
    ) == ProviderFailure("openrouter", "failure", "timeout", "Request timed out")
    assert classify_exception(
        "openrouter", APIConnectionError("Connection error")
    ) == ProviderFailure("openrouter", "failure", "timeout", "Connection error")
    assert classify_exception("openrouter", ValueError("a malformed reply")) is None


def test_the_message_is_the_providers_sentence_capped_and_never_request_content() -> None:
    failure = classify_http("openrouter", 403, OPENROUTER_403)
    assert failure is not None
    assert failure.message.startswith("Key limit exceeded (weekly limit)")
    long = classify_http("exa", 503, "x" * 1000)
    assert long is not None and len(long.message) == 300


def test_failure_codes_round_trip() -> None:
    failure = ProviderFailure("openrouter", "refusal", "key_limit", "Key limit exceeded")
    assert failure_code(failure) == "provider_refused:openrouter:key_limit"
    server_error = ProviderFailure("exa", "failure", "server_error", "503")
    assert failure_code(server_error) == "provider_failed:exa:server_error"
    assert parse_failure_code("provider_refused:openrouter:key_limit") == (
        "openrouter",
        "refusal",
        "key_limit",
    )
    assert parse_failure_code("model_error") is None
    assert parse_failure_code(None) is None


def test_the_runtime_reason_set_is_exactly_the_type_alias() -> None:
    # Ruling PI-3 forbids deriving the runtime set from the alias in the classifier itself; this
    # is where the two are held to each other instead, so neither can grow a reason alone.
    declared = frozenset(get_args(provider_failures.FailureReason))
    assert declared == provider_failures._REASONS
