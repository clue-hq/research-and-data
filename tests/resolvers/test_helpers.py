"""M4.4 — the shared resolver helpers (DB-free): HTTP status classification, the auth_ref→credential
resolver, and ``Secrets.for_auth_ref`` (the decision-3b machinery built once for every resolver).

The retryable-vs-hard fault split and credential resolution are the wrapper's correctness-bearing
decisions, so they are unit-tested directly even though the live ``get_json`` network call is the
un-covered boundary.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from clue_config import Secrets
from clue_core import RetryableResolverError
from clue_research.resolvers import (
    CredentialError,
    ProviderResponseError,
    classify_status,
    resolve_credential,
)


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_classify_status_2xx_is_success(status: int) -> None:
    classify_status(status, source_key="clay", url="https://x")  # 2xx → returns, no raise


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_classify_status_transient_is_retryable(status: int) -> None:
    with pytest.raises(RetryableResolverError):
        classify_status(status, source_key="clay", url="https://x")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_classify_status_hard_4xx_is_not_retryable(status: int) -> None:
    with pytest.raises(ProviderResponseError):
        classify_status(status, source_key="clay", url="https://x")


def test_hard_4xx_retains_the_bounded_provider_diagnostic_body() -> None:
    """A validated provider rejection must stay diagnosable from the durable ledger alone.

    The live R10 Sumble HTTP 400 was persisted as an opaque ``spend_outcome_unknown`` and had to
    be replayed manually just to read the status; the error body (which names the exact invalid
    member on a 422) was discarded entirely.
    """

    with pytest.raises(ProviderResponseError) as caught:
        classify_status(
            422,
            source_key="sumble_teams",
            url="https://api.sumble.com/v9/teams",
            body='{"detail":[{"loc":["filter","query"],"msg":"bad"}]}' + "x" * 5_000,
        )
    error = caught.value
    assert error.status_code == 422
    assert error.is_deterministic_rejection
    assert error.body_excerpt is not None
    assert error.body_excerpt.startswith('{"detail"')
    assert len(error.body_excerpt) <= 2_000


def test_malformed_body_without_status_is_not_a_deterministic_rejection() -> None:
    """A non-JSON 2xx body may still have charged; it must never classify as a clean refusal."""

    assert not ProviderResponseError("clay: non-JSON response").is_deterministic_rejection
    assert not ProviderResponseError("x", status_code=500).is_deterministic_rejection


def test_resolve_credential_returns_the_referenced_secret() -> None:
    secrets = Secrets(clay_api_key=SecretStr("clay-fixture-key"))
    secret = resolve_credential("CLUE_CLAY_API_KEY", source_key="clay", secrets=secrets)
    assert secret.get_secret_value() == "clay-fixture-key"


def test_resolve_credential_unset_key_raises() -> None:
    secrets = Secrets(clay_api_key=None)
    with pytest.raises(CredentialError):
        resolve_credential("CLUE_CLAY_API_KEY", source_key="clay", secrets=secrets)


def test_resolve_credential_none_auth_ref_raises() -> None:
    with pytest.raises(CredentialError):
        resolve_credential(None, source_key="npi", secrets=Secrets())


def test_for_auth_ref_maps_env_name_to_field() -> None:
    secrets = Secrets(apollo_api_key=SecretStr("apollo-fixture-key"))
    assert secrets.for_auth_ref("CLUE_APOLLO_API_KEY").get_secret_value() == "apollo-fixture-key"  # type: ignore[union-attr]


def test_for_auth_ref_unknown_reference_is_none() -> None:
    assert Secrets().for_auth_ref("CLUE_NOT_A_REAL_KEY") is None
    assert Secrets().for_auth_ref("NOPREFIX") is None
