"""The shared live-transport template for tier-1 HTTP backends (M4.4 / ENG-122).

The ``Resolver`` protocol hands a backend a *minimal* :class:`~clue_research.core.Entity` (an
``entity_id`` + type) and is **synchronous** — it has no DB connection. A live provider call,
though, needs the account's identifiers (domain / name / registry ids) to form a query. Two seams
bridge that gap without a resolver ever resolving identity (that is M2's) or holding a connection:

* :class:`AccountLookup` — supplied by the campaign orchestrator (M6/M7), which has *already* loaded
  the account records it is researching; it maps ``entity_id`` → the resolved
  :class:`~clue_research.core.AccountEntity`. Resolvers receive it by injection, never load it.
* :func:`fetch_via_http` — the one place the live request lifecycle lives: resolve the credential
  from the manifest ``auth_ref``, guard the lookup, issue the request through the shared
  :func:`~clue_research.resolvers.http.get_json` wrapper, and normalize the response. Each provider
  supplies only its ``build_request`` (the endpoint/auth shape) and ``normalize`` (response → typed
  fields). The *normalization* is pure and unit-tested per provider; the live network call is the
  ``# pragma: no cover`` boundary (CI binds backend doubles, locked decision #3), exactly as the
  M4.3 adapters deferred their live SDK clients.

Nothing here imports a provider SDK or a sibling worker (import-linter Rules 3/4): the transport is
generic HTTP. The provider-specific request/response shapes are the *documented assumed contract*,
finalized against recorded fixtures when live credentials land (the spec's recorded-fixture path).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, Protocol

from clue_research.core import AccountEntity, Entity, EntityId, FieldDef, ResolverError
from clue_research.resolvers.base import ResolvedField
from clue_research.resolvers.http import get_json, resolve_credential

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_research.config import Secrets


class AccountLookup(Protocol):
    """Resolve an ``entity_id`` to the loaded :class:`~clue_research.core.AccountEntity` whose
    ``primary_domain`` / ``canonical_name`` / ``registry_ids`` a live provider query needs.

    The orchestrator that drives the waterfall over a set of accounts (M6/M7) owns the account
    records and supplies this; resolvers never load entities themselves (identity is M2's, and
    ``resolve`` is sync with no connection). Returns ``None`` for an unknown id — a hard miss.
    """

    def key_for(self, entity_id: EntityId) -> AccountEntity | None: ...


@dataclass(frozen=True)
class HttpRequest:
    """A provider request the shared transport issues — what ``build_request`` returns."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = dataclass_field(default_factory=dict)
    params: dict[str, str] = dataclass_field(default_factory=dict)
    json_body: dict[str, Any] | None = None


# A provider's two pure pieces. ``build_request`` shapes the call from the account
# + resolved credential (``None`` for a public registry with no auth_ref); ``normalize`` maps the
# JSON response to provider-agnostic ResolvedFields.
BuildRequest = Callable[[AccountEntity, FieldDef, "SecretStr | None"], HttpRequest]
Normalize = Callable[[Mapping[str, Any], FieldDef], "list[ResolvedField]"]

# The HTTP fetcher seam (defaults to the shared wrapper; injectable so a test can drive the live
# orchestration with a fake transport without a network).
HttpFetcher = Callable[..., Any]


def fetch_via_http(
    *,
    source_key: str,
    auth_ref: str | None,
    entity: Entity,
    field: FieldDef,
    accounts: AccountLookup | None,
    build_request: BuildRequest,
    normalize: Normalize,
    http: HttpFetcher = get_json,
    secrets: Secrets | None = None,
) -> Sequence[ResolvedField]:
    """Run one tier-1 live enrichment call end to end (the shared request lifecycle).

    The orchestration — the account guard, the *optional* credential resolution, the response guard,
    and the hand-off to ``normalize`` — is exercised by the unit tests via an injected ``http``
    fetcher + :class:`AccountLookup` double; only the default ``http`` (the real
    :func:`~clue_research.resolvers.http.get_json` httpx call) is the un-covered network boundary.

    A missing :class:`AccountLookup` is a wiring error (the orchestrator supplies one); an unknown
    account is a *hard miss* (empty — the field may end empty+flagged). A transient transport/HTTP
    fault propagates as ``RetryableResolverError`` from the wrapper. The credential is resolved
    from the manifest ``auth_ref`` at call time only, and *only when one is declared* — a public
    registry (NPI/SEC/GLEIF) has no ``auth_ref`` and is queried without a token.
    """
    if accounts is None:
        raise ResolverError(
            f"{source_key!r} live backend requires an AccountLookup (wired by the M6/M7 "
            "orchestrator); inject a backend double to exercise it in tests"
        )
    account = accounts.key_for(entity.entity_id)
    if account is None:
        return ()
    token = (
        resolve_credential(auth_ref, source_key=source_key, secrets=secrets)
        if auth_ref is not None
        else None
    )
    request = build_request(account, field, token)
    payload = http(
        request.url,
        source_key=source_key,
        method=request.method,
        headers=request.headers,
        params=request.params,
        json_body=request.json_body,
    )
    if not isinstance(payload, Mapping):
        return ()
    return normalize(payload, field)


class HttpEnrichmentBackend:
    """A generic :class:`~clue_research.resolvers.base.EnrichmentBackend` over the shared live HTTP
    lifecycle — the default backend every provider's ``make_resolver`` wires unless a double is
    injected. The provider supplies only its ``source_key`` / ``auth_ref`` / ``build_request`` (the
    endpoint+auth shape) and ``normalize`` (response → typed fields); the network call is the
    ``fetch_via_http`` ``# pragma: no cover`` boundary. This is why no provider needs its own
    backend class — the only provider-specific code is the two pure pieces (conventions §2 DRY).
    """

    def __init__(
        self,
        *,
        source_key: str,
        auth_ref: str | None,
        build_request: BuildRequest,
        normalize: Normalize,
        accounts: AccountLookup | None = None,
        http: HttpFetcher = get_json,
        secrets: Secrets | None = None,
    ) -> None:
        self._source_key = source_key
        self._auth_ref = auth_ref
        self._build_request = build_request
        self._normalize = normalize
        self._accounts = accounts
        self._http = http
        self._secrets = secrets

    def fetch(self, entity: Entity, field: FieldDef) -> Sequence[ResolvedField]:
        return fetch_via_http(
            source_key=self._source_key,
            auth_ref=self._auth_ref,
            entity=entity,
            field=field,
            accounts=self._accounts,
            build_request=self._build_request,
            normalize=self._normalize,
            http=self._http,
            secrets=self._secrets,
        )
