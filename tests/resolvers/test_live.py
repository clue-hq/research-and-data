"""M4.4 — the shared live request lifecycle (DB-free), driven by a fake HTTP + AccountLookup.

``fetch_via_http`` / :class:`HttpEnrichmentBackend` are the one place the live call is orchestrated:
account guard → optional credential → request → response guard → normalize. A fake ``http``
and a fake :class:`AccountLookup` exercises all of that without a network; only the default ``http``
(the real ``get_json`` httpx call) and each provider's assumed ``_build_request`` stay uncovered.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from clue_config import Secrets
from clue_core import (
    AccountEntity,
    Entity,
    EntityType,
    FieldDef,
    PassKind,
    ResolverError,
    RetryableResolverError,
    new_entity_id,
)
from clue_research.resolvers import (
    CredentialError,
    HttpEnrichmentBackend,
    HttpRequest,
    clay,
    fetch_via_http,
    resolved_field,
)


class _FakeAccounts:
    def __init__(self, account: AccountEntity | None) -> None:
        self._account = account

    def key_for(self, entity_id: object) -> AccountEntity | None:
        return self._account


class _RecordingHttp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        return self._payload


def _entity() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


def _field(field_key: str = "core.employee_count") -> FieldDef:
    return FieldDef(field_key=field_key, value_type="int", pass_kind=PassKind.SCORING)


def _account(domain: str | None = "acme.com") -> AccountEntity:
    return AccountEntity(
        id=new_entity_id(),
        canonical_name="Acme",
        primary_domain=domain,
        workspace_id="ws-test",
    )


def _build(account: AccountEntity, field: FieldDef, token: object) -> HttpRequest:
    params = {"domain": account.primary_domain or ""}
    if token is not None:
        params["api_key"] = token.get_secret_value()  # type: ignore[attr-defined]
    return HttpRequest(url="https://provider.test/enrich", params=params)


def _normalize(payload: Any, field: FieldDef) -> list[Any]:
    return [
        resolved_field(field.field_key, payload["value"], source_url="https://r", confidence=0.9)
    ]


def _call(
    *, accounts: Any, http: Any, auth_ref: str | None = None, secrets: Secrets | None = None
) -> Any:
    return fetch_via_http(
        source_key="clay",
        auth_ref=auth_ref,
        entity=_entity(),
        field=_field(),
        accounts=accounts,
        build_request=_build,
        normalize=_normalize,
        http=http,
        secrets=secrets,
    )


def test_happy_path_returns_normalized_fields() -> None:
    http = _RecordingHttp({"value": 1200})
    (rf,) = _call(accounts=_FakeAccounts(_account()), http=http)
    assert rf.value == 1200
    assert http.calls[0]["url"] == "https://provider.test/enrich"
    assert http.calls[0]["source_key"] == "clay"


def test_unknown_account_is_a_hard_miss() -> None:
    assert _call(accounts=_FakeAccounts(None), http=_RecordingHttp({"value": 1})) == ()


def test_missing_account_lookup_is_a_wiring_error() -> None:
    with pytest.raises(ResolverError):
        _call(accounts=None, http=_RecordingHttp({"value": 1}))


def test_credential_is_resolved_when_auth_ref_declared() -> None:
    recorded: dict[str, Any] = {}

    def _build_record(account: AccountEntity, field: FieldDef, token: object) -> HttpRequest:
        recorded["token"] = token
        return HttpRequest(url="https://provider.test/e")

    fetch_via_http(
        source_key="clay",
        auth_ref="CLUE_CLAY_API_KEY",
        entity=_entity(),
        field=_field(),
        accounts=_FakeAccounts(_account()),
        build_request=_build_record,
        normalize=_normalize,
        http=_RecordingHttp({"value": 1}),
        secrets=Secrets(clay_api_key=SecretStr("clay-fixture-key")),
    )
    assert (
        recorded["token"].get_secret_value() == "clay-fixture-key"
    )  # the credential reached build_request


def test_missing_credential_raises_credential_error() -> None:
    with pytest.raises(CredentialError):
        _call(
            accounts=_FakeAccounts(_account()),
            http=_RecordingHttp({"value": 1}),
            auth_ref="CLUE_CLAY_API_KEY",
            secrets=Secrets(clay_api_key=None),
        )


def test_public_source_passes_no_token() -> None:
    recorded: dict[str, Any] = {}

    def _build_record(account: AccountEntity, field: FieldDef, token: object) -> HttpRequest:
        recorded["token"] = token
        return HttpRequest(url="https://public.test")

    fetch_via_http(
        source_key="cik",
        auth_ref=None,  # a public registry
        entity=_entity(),
        field=_field(),
        accounts=_FakeAccounts(_account()),
        build_request=_build_record,
        normalize=_normalize,
        http=_RecordingHttp({"value": 1}),
    )
    assert recorded["token"] is None  # no credential resolved for a public source


def test_non_mapping_response_is_a_hard_miss() -> None:
    assert (
        _call(accounts=_FakeAccounts(_account()), http=_RecordingHttp(["not", "a", "mapping"]))
        == ()
    )


def test_transient_http_fault_propagates() -> None:
    def _raise(url: str, **kwargs: Any) -> Any:
        raise RetryableResolverError("503")

    with pytest.raises(RetryableResolverError):
        _call(accounts=_FakeAccounts(_account()), http=_raise)


def test_http_enrichment_backend_composes_a_real_normalize() -> None:
    # The generic backend + a provider's REAL normalize (clay), driven by a fake transport: proves
    # the backend→normalize composition end to end without inventing the provider's live endpoint.
    backend = HttpEnrichmentBackend(
        source_key="clay",
        auth_ref="CLUE_CLAY_API_KEY",
        build_request=_build,
        normalize=clay.normalize,
        accounts=_FakeAccounts(_account()),
        http=_RecordingHttp({"employee_count": 1200, "match_confidence": 0.93}),
        secrets=Secrets(clay_api_key=SecretStr("clay-fixture-key")),
    )
    (rf,) = backend.fetch(_entity(), _field("core.employee_count"))
    assert rf.value == 1200 and rf.confidence == pytest.approx(0.93)
