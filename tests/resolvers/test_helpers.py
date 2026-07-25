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
