"""The HTTP boundary of the provider-caller seam — one request shape, one response, one seam.

Nothing above this module speaks to a vendor SDK: a provider client builds an
:class:`HttpRequest` and hands it to :class:`~clue_spend.calls.ProviderCaller`, which sends it
through a :class:`Transport`. Two implementations ship here — :class:`HttpxTransport` (the real
network, lazy-importing ``httpx`` inside :meth:`~HttpxTransport.send` so importing this module
needs no library) and :class:`ScriptedTransport` (the wrapper's own retry/halt arithmetic is the
one thing that cannot be asserted against a live provider, so it gets the one test double the
lane allows).

A transport raises :class:`TransportFailure` **only** for a network-level failure. A non-2xx
status is a perfectly normal :class:`HttpResponse`: deciding what a 429 or a 402 means is the
wrapper's job (Appendix A law 2), never the socket's.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "BROWSER_USER_AGENT",
    "HttpRequest",
    "HttpResponse",
    "HttpxTransport",
    "ScriptedTransport",
    "Transport",
    "TransportFailure",
    "json_request",
    "lower_headers",
]

#: The Chrome 126 / macOS user-agent string the proof-of-concept used. Several sources ARV2 reads
#: (Ashby's public job board among them) answer 403 to a default client string and 200 to this
#: one, so it is the lane's default browser identity for un-credentialed public fetches.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def lower_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Lower-case header names so every consumer (redaction, ``Retry-After``) has one spelling."""
    return {str(name).lower(): str(value) for name, value in headers.items()}


@dataclass(frozen=True)
class HttpRequest:
    """One outbound request, fully built by the client before the wrapper ever sees it."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout_s: float = 120.0


@dataclass(frozen=True)
class HttpResponse:
    """One response. ``headers`` keys are always lower-cased (normalised on construction)."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", lower_headers(self.headers))


class TransportFailure(Exception):
    """A network-level failure: no response arrived. Never raised for a non-2xx status."""


class Transport(Protocol):
    """The seam a provider call is sent through."""

    def send(self, request: HttpRequest) -> HttpResponse: ...


class HttpxTransport:
    """The live transport. ``httpx`` is imported inside :meth:`send`, never at module import."""

    def send(self, request: HttpRequest) -> HttpResponse:
        """Send one request, following redirects; a network fault becomes ``TransportFailure``."""
        import httpx

        try:
            with httpx.Client(follow_redirects=True, timeout=request.timeout_s) as client:
                response = client.request(
                    request.method,
                    request.url,
                    headers=dict(request.headers),
                    content=request.body,
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransportFailure(f"{type(exc).__name__}: {exc}") from exc
        return HttpResponse(
            status=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )


class ScriptedTransport:
    """A queue of responses/failures consumed in order — the lane's ONE permitted test double.

    Global Constraint 3: every other ARV2 test calls the real provider. This exists because the
    wrapper's retry backoff, halt latching and raw/ledger ordering are timing and sequencing
    facts that a live provider cannot be made to demonstrate on demand.
    """

    def __init__(self, script: list[HttpResponse | TransportFailure]) -> None:
        self._script = list(script)
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if not self._script:
            raise AssertionError("ScriptedTransport exhausted: an unscripted request was sent")
        item = self._script.pop(0)
        if isinstance(item, TransportFailure):
            raise item
        return item


def json_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    json_body: Any,
    timeout_s: float,
) -> HttpRequest:
    """Build a JSON request with a byte-stable body.

    ``sort_keys`` + the compact separators make the serialisation deterministic, so the raw
    record's ``body_sha256`` identifies the request content rather than a dict ordering.
    """
    body = json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode()
    return HttpRequest(
        method=method,
        url=url,
        headers={**headers, "Content-Type": "application/json"},
        body=body,
        timeout_s=timeout_s,
    )
