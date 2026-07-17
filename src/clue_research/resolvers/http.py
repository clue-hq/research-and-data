"""Shared resolver transport helpers — the generic HTTP/SDK client wrapper, the retry/error
classification, and the ``auth_ref`` → credential entry point (M0.2 / M4 kickoff decision 3b).

Built **once**, here, *before* the first concrete resolver, so no provider re-implements HTTP,
retry, or credential resolution (conventions §2 DRY; the spec's "generic HTTP/SDK client wrapper +
credential-reference resolver from M0.2"). Every tier-1 resolver's live backend routes its network
call through :func:`get_json` and obtains its key through :func:`resolve_credential`.

Two design rules this module obeys:

* **Imports no provider SDK and no sibling worker.** It depends only on ``core`` (the error
  taxonomy) and ``config`` (the typed secret store) — never ``clue_research.adapters`` /
  ``verification`` / ``discovery_scoring`` (import-linter Rule 3), nor a vendor SDK (Rule 4).
* **The network is a lazy, hermetic boundary.** ``httpx`` is imported *inside* :func:`get_json`
  (``# pragma: no cover``) so importing this module never needs the library and the doubles-driven
  CI path (locked decision #3) makes no live call. The *decisions* a wrapper makes that matter for
  correctness — which HTTP status is transient, whether a credential resolved — are pure functions
  exercised directly by the unit tests.

The retryable/hard-miss split is the source-layer contract (substrate §4/§5; M4.4): a transient
fault raises :class:`~clue_core.RetryableResolverError` (the engine/M7 retries); a hard
provider miss is an *empty claim list* the resolver returns (not an error). A malformed/forbidden
response is a :class:`ProviderResponseError` — a real fault, but not one a retry would fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clue_core import ResolverError, RetryableResolverError
from clue_research.config import Secrets

if TYPE_CHECKING:
    from pydantic import SecretStr

# HTTP statuses worth retrying: request timeout / too-early, rate-limit, and the transient 5xx band.
# A 4xx other than these is a hard, non-retryable response (bad request / auth / not-found).
_RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

DEFAULT_TIMEOUT_S: float = 10.0
DEFAULT_RETRIES: int = (
    2  # total attempts = 1 + retries; backoff is the durable scheduler's job (M7)
)


class ProviderResponseError(ResolverError):
    """A provider returned a response we cannot use and a retry would not fix (a hard 4xx — bad
    request / auth / not-found — or a malformed body). Distinct from a *hard miss* (empty list, a
    correct empty+flagged output) and from a *transient* fault (:class:`RetryableResolverError`)."""


class CredentialError(ResolverError):
    """No credential resolved for a manifest ``auth_ref`` (the referenced ``CLUE_*`` key is unset).

    Raised at call time, never at import/bind time — so binding a resolver never needs a live key,
    and the failure is a clear, typed configuration error rather than an opaque provider 401.
    """


def classify_status(status: int, *, source_key: str, url: str) -> None:
    """Map an HTTP status to the resolver fault taxonomy (pure; the tested core of the wrapper).

    Returns ``None`` for a 2xx success. Raises :class:`~clue_core.RetryableResolverError`
    for a transient status (so M7 retries) and :class:`ProviderResponseError` for a hard 4xx/other
    (so the run fails fast instead of looping on a request that can never succeed).
    """
    if 200 <= status < 300:
        return
    detail = f"{source_key}: HTTP {status} from {url}"
    if status in _RETRYABLE_STATUS:
        raise RetryableResolverError(detail)
    raise ProviderResponseError(detail)


def resolve_credential(
    auth_ref: str | None, *, source_key: str, secrets: Secrets | None = None
) -> SecretStr:
    """Resolve a manifest ``auth_ref`` to a live secret, or raise :class:`CredentialError`.

    The single entry point a resolver's live backend uses for credentials — it delegates the
    name→field mapping to :meth:`Secrets.for_auth_ref` (config owns secret mechanics; resolvers
    never read ``os.environ``). ``secrets`` is injectable so a test can supply a constructed store
    without touching the process environment.
    """
    if auth_ref is None:
        raise CredentialError(
            f"source {source_key!r} declares no auth_ref but a credential was requested"
        )
    secret = (secrets or Secrets()).for_auth_ref(auth_ref)
    if secret is None:
        raise CredentialError(
            f"no credential resolved for auth_ref {auth_ref!r} (source {source_key!r}); "
            f"set {auth_ref} in the environment, or inject a backend double for tests"
        )
    return secret


def get_json(
    url: str,
    *,
    source_key: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    method: str = "GET",
    timeout: float = DEFAULT_TIMEOUT_S,
    retries: int = DEFAULT_RETRIES,
) -> Any:  # pragma: no cover - live network boundary; CI binds backend doubles instead
    """Issue one HTTP request and return the decoded JSON, applying the shared fault classification.

    The live network path (``# pragma: no cover``): transport errors (DNS/connect/read timeouts)
    and transient statuses raise :class:`~clue_core.RetryableResolverError`; hard 4xx raise
    :class:`ProviderResponseError`; a non-JSON body raises :class:`ProviderResponseError`. ``httpx``
    is imported lazily so neither importing this module nor the tests need the library.
    """
    import httpx

    last_error: Exception | None = None
    for _ in range(retries + 1):
        try:
            response = httpx.request(
                method, url, headers=headers, params=params, json=json_body, timeout=timeout
            )
        except httpx.HTTPError as exc:
            last_error = RetryableResolverError(f"{source_key}: transport error for {url}: {exc}")
            continue
        try:
            classify_status(response.status_code, source_key=source_key, url=url)
        except RetryableResolverError as exc:
            last_error = exc
            continue
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"{source_key}: non-JSON response from {url}: {exc}"
            ) from exc
    assert last_error is not None  # the loop only falls through after a retryable failure
    raise last_error
