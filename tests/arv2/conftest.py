"""Shared fixtures for the ARV2 tests.

Global Constraint 3: every test here calls the real provider with the key read from the repo-root
``.env`` through ``clue_config.Secrets``; a missing key is a ``skip`` naming the env var, never a
mock. Raw records and the ledger go under ``.artifacts/arv2/`` (git-ignored, Constraint 4).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from clue_api.arv2.calls import Ceilings, ProviderCaller
from clue_api.arv2.sinks import FileRawSink, JsonlLedger
from clue_api.arv2.transport import HttpRequest, HttpResponse, HttpxTransport, Transport
from clue_config import Secrets


@pytest.fixture(scope="session")
def live_secrets() -> Secrets:
    """The real provider keys, read from ``.env`` — never printed, logged or written anywhere."""
    return Secrets()


def require_secret(secrets: Secrets, field_name: str) -> str:
    """Return a live key, or skip the test naming the env var the operator has to set.

    A blank line in ``.env`` — ``CLUE_AI_ARK_API_KEY=``, exactly what ``.env.example`` ships —
    loads as ``SecretStr('')``, not ``None``. Treating that as "set" would send an empty key to a
    real provider and report the provider's 401 as a test failure, hiding the actual problem
    (nobody filled the key in). Blank is unset.
    """
    value = getattr(secrets, field_name, None)
    if value is None or not value.get_secret_value().strip():
        pytest.skip(f"CLUE_{field_name.upper()} is unset")
    return str(value.get_secret_value())


@pytest.fixture(scope="session")
def arv2_raw_root() -> Path:
    """Where live-test raw records and the ledger land (Constraint 4). Never committed."""
    root = Path(".artifacts/arv2")
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def make_caller(arv2_raw_root: Path) -> Callable[..., ProviderCaller]:
    """Factory for a caller writing to the on-disk raw sink and JSONL ledger.

    A transport that carries its own ``sleep`` (:class:`ScriptedJsonTransport` does) supplies the
    caller's retry delay, so an offline test of a retryable status does not really wait out the
    wrapper's ``12·(n+1)`` s backoff. A live transport keeps ``time.sleep``: a real 429 must still
    be paced.
    """

    def _make(
        transport: Transport | None = None,
        *,
        ceilings: Ceilings | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> ProviderCaller:
        return ProviderCaller(
            transport=transport or HttpxTransport(),
            raw_sink=FileRawSink(arv2_raw_root / "raw"),
            ledger=JsonlLedger(arv2_raw_root / "ledger.jsonl"),
            ceilings=ceilings,
            sleep=sleep or getattr(transport, "sleep", time.sleep),
            now=lambda: datetime.now(UTC),
        )

    return _make


@dataclass(frozen=True)
class RecordedRequest:
    """One request a scripted transport received, with its JSON body already parsed."""

    request: HttpRequest

    @property
    def json_body(self) -> Any:
        """The request body parsed as JSON (``None`` when the request carried no body)."""
        return json.loads(self.request.body) if self.request.body else None

    @property
    def method(self) -> str:
        return self.request.method

    @property
    def url(self) -> str:
        return self.request.url

    @property
    def headers(self) -> Mapping[str, str]:
        return self.request.headers


class ScriptedJsonTransport:
    """Answers every request with one canned JSON response, recording what it was asked.

    Global Constraint 3 keeps ARV2 tests on the real provider; the exception is the same one
    :class:`~clue_api.arv2.transport.ScriptedTransport` already carries — request *shape* and the
    wrapper's own arithmetic (retries, malformed answers, a 5xx) cannot be demonstrated on demand
    by a live provider. Unlike ``ScriptedTransport`` this one never exhausts, so a retried status
    is answered on every attempt, and it records the backoff instead of sleeping it.
    """

    def __init__(
        self, *, status: int, body: object, headers: Mapping[str, str] | None = None
    ) -> None:
        self.status = status
        self.body = json.dumps(body).encode()
        self.headers = dict(headers or {"content-type": "application/json"})
        self.requests: list[RecordedRequest] = []
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        """Record a retry backoff the wrapper asked for; never actually wait."""
        self.slept.append(seconds)

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(RecordedRequest(request))
        return HttpResponse(status=self.status, headers=self.headers, body=self.body)


@pytest.fixture
def scripted_transport() -> Callable[..., ScriptedJsonTransport]:
    """Factory for a :class:`ScriptedJsonTransport` — ``scripted_transport(status=…, body=…)``."""

    def _make(
        *, status: int, body: object, headers: Mapping[str, str] | None = None
    ) -> ScriptedJsonTransport:
        return ScriptedJsonTransport(status=status, body=body, headers=headers)

    return _make
