# Provider Incidents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an external provider stops serving us (credits exhausted, key limit, invalid key, or repeated 429/5xx/timeouts), open one durable incident, tell the founders once in Sentry on open and once on close, and make every affected surface say why it failed in one sentence.

**Architecture:** One pure classifier in `clue_core` turns a provider response or SDK exception into a `ProviderFailure`. Two writers feed a `provider_incident` table: the ARV2 ledger drain (which already sees every research, discovery, display and onboarding provider call, plus the research agent's model rounds) and the chat turn's model-call handler. Whichever process wins the insert or the close fires the single Sentry event. Jobs and turns keep the classified reason on their own row. Three readers render the same sentence inline: the research card, the empty overview section, the failed chat turn.

**Tech Stack:** Python 3.12, SQLAlchemy async + asyncpg, Alembic, sentry-sdk 2.69, pytest (`-p no:cacheprovider`, `--ignore-glob='*_live.py'`), Next.js frontend with Zod and `node:test`.

**Spec:** `docs/superpowers/specs/archive/2026-09-16-provider-incidents-design.md`

**Spec amendment recorded by this plan (§3.4 writers).** The spec named "the model gateway" as the second writer through a root-installed hook. The plan places both writers where the platform already catches the failure with a database connection in hand, so the gateway (`libs/clue-gateway`) is **not modified**: (1) the ARV2 provider caller classifies at settle time and stamps the classification onto the ledger row's `extras`; `drain_provider_calls` — the one function every ARV2 row passes through, with an `AsyncConnection` and a `LedgerStamp` — records incidents; the research agent's model rounds are ledger rows too and get the same stamp from their exception. (2) The chat turn's `DurableAgentModelCallHandler` classifies in `on_llm_error` and records through a connection factory. Same guarantees, fewer seams, no change to a library the design subsystem also depends on.

## Global Constraints

- **Refusal reasons open on first sight:** `credits_exhausted`, `key_limit`, `auth_invalid`, `account_suspended`.
- **Failure reasons open after ≥ 3 classified failures for one provider within 5 minutes:** `rate_limited` (429 counts — founder 2026-09-16), `server_error` (5xx), `timeout` (transport error / timeout).
- **A 2xx, a 404, a 400, a 422 are never a provider failure:** the classifier returns `None`.
- **One open incident per `(provider, reason)`, platform-wide:** partial unique index `WHERE closed_at IS NULL`.
- **Sentry: exactly one event on open (`level="error"`), one on close (`level="info"`), fingerprint `["provider-incident", provider, reason, opened_at ISO]`;** no event per failing call.
- **Open-event title:** `{Provider} refused: {reason words}` for refusals, `{Provider} failing: {reason words}` for failures. **Close-event title:** `{Provider} recovered after {duration} — {n} calls failed ({surface breakdown})`.
- **Provider display names:** `openrouter → Model provider`, `exa` and `exa_websets → Discovery provider`, `live_http → Website fetch`, anything else → the provider id.
- **Reason words:** `credits_exhausted → credits exhausted`, `key_limit → key limit exceeded`, `auth_invalid → API key rejected`, `account_suspended → account suspended`, `rate_limited → rate limited`, `server_error → server errors`, `timeout → timeouts`.
- **Inline sentence** (`incident_sentence`): `"{Provider display} {refused|failing}: {reason words}. Since {HH:MM}{, {n} {calls|jobs} affected}.{ Clue has been notified.}"` — "Clue has been notified." only when `sentry_open_event_id IS NOT NULL`.
- **Failure codes on rows:** `provider_refused:{provider}:{reason}` and `provider_failed:{provider}:{reason}` (lowercase, `^[a-z0-9_.:-]+$`).
- **The recorder never raises into the call it observes:** every public method catches, logs `provider_incident.recorder_failed`, and returns.
- **No new env flags.** Sentry uses `CLUE_SENTRY_ENABLED` / `CLUE_SENTRY_DSN` / `CLUE_SENTRY_ENVIRONMENT` (already set on the lane).
- **Tests:** `uv run pytest <paths> -p no:cacheprovider -q`; DB suites only on the lane DB (`.env` loaded with `set -a; source .env; set +a`), `env -u CLUE_CHAT_REASONING_TRACE_MODE` for `tests/api`. Never `make check`, never `*_live.py`.
- **Commits:** local only, no push, no AI attribution.
- **Standing rule:** no old-lane gate may block a new-lane turn; nothing here adds a gate.

---

### Task 1: The classifier (`clue_core.provider_failures`)

**Files:**
- Create: `libs/clue-core/clue_core/provider_failures.py`
- Modify: `libs/clue-core/clue_core/__init__.py` (export the four names)
- Test: `tests/core/test_provider_failures.py`

**Interfaces:**
- Produces:
  ```python
  FailureKind = Literal["refusal", "failure"]
  FailureReason = Literal["credits_exhausted", "key_limit", "auth_invalid", "account_suspended", "rate_limited", "server_error", "timeout"]
  @dataclass(frozen=True, slots=True)
  class ProviderFailure: provider: str; kind: FailureKind; reason: FailureReason; message: str
  def classify_http(provider: str, status: int | None, body: str | None) -> ProviderFailure | None
  def classify_exception(provider: str, exc: BaseException) -> ProviderFailure | None
  def failure_code(failure: ProviderFailure) -> str   # "provider_refused:openrouter:key_limit"
  def parse_failure_code(code: str | None) -> tuple[str, FailureKind, FailureReason] | None
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_provider_failures.py
from __future__ import annotations

import pytest

from clue_core.provider_failures import (
    ProviderFailure,
    classify_exception,
    classify_http,
    failure_code,
    parse_failure_code,
)

EXA_402 = '{"requestId":"18ff","error":"You have exceeded your credits limit. Please top up to keep using Exa at dashboard.exa.ai","tag":"NO_MORE_CREDITS"}'
OPENROUTER_403 = "{'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/workspaces/default/keys/3faff', 'code': 403}}"
WEBSETS_402 = '{"error":"payment_required","message":"Your plan requires payment"}'


@pytest.mark.parametrize(
    ("provider", "status", "body", "kind", "reason"),
    [
        ("exa", 402, EXA_402, "refusal", "credits_exhausted"),
        ("exa_websets", 402, WEBSETS_402, "refusal", "credits_exhausted"),
        ("openrouter", 403, OPENROUTER_403, "refusal", "key_limit"),
        ("openrouter", 401, '{"error":{"message":"No auth credentials found"}}', "refusal", "auth_invalid"),
        ("openrouter", 403, '{"error":{"message":"Forbidden"}}', "refusal", "auth_invalid"),
        ("openrouter", 403, '{"error":{"message":"Your account has been suspended"}}', "refusal", "account_suspended"),
        ("openrouter", 429, '{"error":{"message":"Rate limit exceeded"}}', "failure", "rate_limited"),
        ("exa", 503, "upstream unavailable", "failure", "server_error"),
        ("exa", 500, None, "failure", "server_error"),
    ],
)
def test_http_statuses_and_bodies_classify_as_the_spec_says(provider, status, body, kind, reason) -> None:
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
    denied = classify_exception("openrouter", PermissionDeniedError(403, "Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/x"))
    assert denied is not None and (denied.kind, denied.reason) == ("refusal", "key_limit")
    limited = classify_exception("openrouter", RateLimitError(429, "Rate limit exceeded"))
    assert limited is not None and (limited.kind, limited.reason) == ("failure", "rate_limited")
    assert classify_exception("openrouter", APITimeoutError("Request timed out")) == ProviderFailure("openrouter", "failure", "timeout", "Request timed out")
    assert classify_exception("openrouter", APIConnectionError("Connection error")) == ProviderFailure("openrouter", "failure", "timeout", "Connection error")
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
    assert failure_code(ProviderFailure("exa", "failure", "server_error", "503")) == "provider_failed:exa:server_error"
    assert parse_failure_code("provider_refused:openrouter:key_limit") == ("openrouter", "refusal", "key_limit")
    assert parse_failure_code("model_error") is None
    assert parse_failure_code(None) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_provider_failures.py -p no:cacheprovider -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clue_core.provider_failures'`

- [ ] **Step 3: Write the classifier**

```python
# libs/clue-core/clue_core/provider_failures.py
"""What an external provider's answer means for the platform, classified once for everyone.

A provider can stop serving us in two ways. A **refusal** is a decision — the account is out of
credit, the key hit its cap, the key is wrong, the account is suspended — and no retry changes it.
A **failure** is a fault — a 429, a 5xx, a timeout — that usually passes. The two are told apart
here, from an HTTP status and body or from an SDK exception, and nowhere else; the incident
recorder, the ledger rows, the job and turn failure codes and the three inline surfaces all read
this one verdict. Pure: no I/O, no provider SDK import (exceptions are read by duck typing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "FailureKind",
    "FailureReason",
    "ProviderFailure",
    "classify_exception",
    "classify_http",
    "failure_code",
    "parse_failure_code",
]

FailureKind = Literal["refusal", "failure"]
FailureReason = Literal[
    "credits_exhausted",
    "key_limit",
    "auth_invalid",
    "account_suspended",
    "rate_limited",
    "server_error",
    "timeout",
]

#: The provider's own sentence is kept, capped, so a Sentry title or an inline message can quote
#: it. Never request content: only the response body (or the exception's message) is read.
MESSAGE_CHARS = 300

_REFUSALS: frozenset[str] = frozenset(
    {"credits_exhausted", "key_limit", "auth_invalid", "account_suspended"}
)
_CREDIT_WORDS = re.compile(
    r"credit|insufficient|no_more_credits|payment.required|top up|billing", re.IGNORECASE
)
_KEY_LIMIT_WORDS = re.compile(r"key limit|spend limit|limit exceeded", re.IGNORECASE)
_SUSPENDED_WORDS = re.compile(r"suspended|disabled|banned", re.IGNORECASE)
_TIMEOUT_CLASS_WORDS = re.compile(r"timeout|timed out|connection", re.IGNORECASE)
_CODE_RE = re.compile(r"^provider_(refused|failed):([a-z0-9_.-]+):([a-z_]+)$")


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    kind: FailureKind
    reason: FailureReason
    message: str


def _message(text: str | None, fallback: str) -> str:
    cleaned = " ".join((text or "").split())
    return (cleaned or fallback)[:MESSAGE_CHARS]


def _reason_for(status: int | None, body: str) -> tuple[FailureKind, FailureReason] | None:
    if status is None:
        return "failure", "timeout"
    if 200 <= status < 300:
        return None
    if status == 402 or (status in (401, 403) and _CREDIT_WORDS.search(body)):
        return "refusal", "credits_exhausted"
    if status == 403 and _KEY_LIMIT_WORDS.search(body):
        return "refusal", "key_limit"
    if status in (401, 403) and _SUSPENDED_WORDS.search(body):
        return "refusal", "account_suspended"
    if status in (401, 403):
        return "refusal", "auth_invalid"
    if status == 429:
        return "failure", "rate_limited"
    if status >= 500:
        return "failure", "server_error"
    # 400, 404, 409, 422 and the rest of 4xx: our request, or nothing there — not the provider
    # refusing to serve.
    return None


def classify_http(provider: str, status: int | None, body: str | None) -> ProviderFailure | None:
    """A provider's HTTP answer as a failure, or ``None`` when it is not one.

    ``status is None`` means no response at all (a transport fault): a timeout-class failure.
    """
    text = body or ""
    verdict = _reason_for(status, text)
    if verdict is None:
        return None
    kind, reason = verdict
    fallback = f"HTTP {status}" if status is not None else "no response"
    return ProviderFailure(provider, kind, reason, _message(text, fallback))


def classify_exception(provider: str, exc: BaseException) -> ProviderFailure | None:
    """An SDK or transport exception as a failure, read by duck typing.

    ``status_code`` (the OpenAI SDK's ``APIStatusError`` family) decides first, with the
    exception's message as the body. Without a status, a class name naming a timeout or a
    connection fault is a ``timeout``; anything else (a malformed reply, a programming error) is
    not a provider failure and returns ``None``.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    message = str(exc)
    if isinstance(status, int):
        return classify_http(provider, status, message)
    if _TIMEOUT_CLASS_WORDS.search(type(exc).__name__):
        return ProviderFailure(provider, "failure", "timeout", _message(message, type(exc).__name__))
    return None


def failure_code(failure: ProviderFailure) -> str:
    """The stable code a job or turn row records: ``provider_refused:<provider>:<reason>``."""
    head = "provider_refused" if failure.kind == "refusal" else "provider_failed"
    return f"{head}:{failure.provider}:{failure.reason}"


def parse_failure_code(code: str | None) -> tuple[str, FailureKind, FailureReason] | None:
    """The inverse of :func:`failure_code`; ``None`` for any other code."""
    if code is None:
        return None
    match = _CODE_RE.match(code)
    if match is None:
        return None
    head, provider, reason = match.groups()
    kind: FailureKind = "refusal" if head == "refused" else "failure"
    if reason not in FailureReason.__args__:  # type: ignore[attr-defined]
        return None
    return provider, kind, reason  # type: ignore[return-value]
```

- [ ] **Step 4: Export from `clue_core.__init__`**

Add to the import block and `__all__` of `libs/clue-core/clue_core/__init__.py`:

```python
from clue_core.provider_failures import (
    ProviderFailure,
    classify_exception,
    classify_http,
    failure_code,
    parse_failure_code,
)
```

and the five names in `__all__` (alphabetical position).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_provider_failures.py -p no:cacheprovider -q && uv run ruff check libs/clue-core/clue_core/provider_failures.py tests/core/test_provider_failures.py && uv run mypy libs/clue-core/clue_core/provider_failures.py`
Expected: all pass; ruff and mypy clean. (If mypy rejects the `FailureReason.__args__` check, replace it with an explicit `frozenset` of the seven reason strings named `_REASONS` and test membership against that.)

- [ ] **Step 6: Commit**

```bash
git add libs/clue-core/clue_core/provider_failures.py libs/clue-core/clue_core/__init__.py tests/core/test_provider_failures.py
git commit -m "feat(core): one classifier for provider refusals and failures — status and body, or SDK exception, to a ProviderFailure"
```

---

### Task 2: The incident table and recorder (`clue_api.provider_incidents`)

**Files:**
- Create: `alembic/versions/<hash>_provider_incident.py` (generate with `uv run alembic revision -m "provider incident"`; `down_revision = "b7193eb28363"`)
- Create: `platform/api/clue_api/provider_incidents.py`
- Test: `tests/api/test_provider_incidents_db.py`

**Interfaces:**
- Consumes: `ProviderFailure`, `failure_code` (Task 1); `clue_obs.sentry.sentry_is_installed`; `sentry_sdk`.
- Produces:
  ```python
  FAILURE_THRESHOLD = 3; FAILURE_WINDOW = timedelta(minutes=5)
  @dataclass(frozen=True) class OpenIncident: incident_id: UUID; provider: str; kind: str; reason: str; opened_at: datetime; failure_count: int; sample_message: str; surfaces: dict[str, int]; notified: bool
  async def record_failure(conn, failure: ProviderFailure, *, surface: str, workspace_id: str | None, now: datetime) -> OpenIncident | None
  async def record_success(conn, provider: str, *, now: datetime) -> tuple[OpenIncident, ...]   # the incidents it closed
  async def open_incidents(conn, *, providers: Iterable[str] | None = None) -> tuple[OpenIncident, ...]
  def incident_sentence(*, provider: str, kind: str, reason: str, since: datetime, affected: int | None, unit: str, notified: bool) -> str
  def provider_display(provider: str) -> str; def reason_words(reason: str) -> str
  ```
  Every function swallows its own exceptions (logs `provider_incident.recorder_failed`) and returns `None` / `()`.

- [ ] **Step 1: Write the migration**

```python
"""provider incident

Revision ID: <hash>
Revises: b7193eb28363
Create Date: <generated>

Provider incidents (design 2026-09-16 §3.3). One row per stretch during which an external
provider refused to serve us or failed repeatedly. The partial unique index is the open-once
rule: two processes seeing the same refusal race on the insert and exactly one wins, so exactly
one Sentry event leaves the box. Rows are never deleted; ``closed_at`` ends a stretch.

Reversible: the downgrade drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<hash>"
down_revision: str | None = "b7193eb28363"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE provider_incident (
            incident_id           uuid PRIMARY KEY,
            provider              text NOT NULL,
            kind                  text NOT NULL CHECK (kind IN ('refusal', 'failure')),
            reason                text NOT NULL,
            opened_at             timestamptz NOT NULL,
            last_failure_at       timestamptz NOT NULL,
            failure_count         integer NOT NULL CHECK (failure_count >= 1),
            sample_message        text NOT NULL,
            surfaces_json         jsonb NOT NULL DEFAULT '{}'::jsonb,
            workspaces_json       jsonb NOT NULL DEFAULT '[]'::jsonb,
            closed_at             timestamptz,
            sentry_open_event_id  text,
            sentry_close_event_id text,
            CONSTRAINT provider_incident_closed_after_open CHECK (closed_at IS NULL OR closed_at >= opened_at)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX provider_incident_one_open "
        "ON provider_incident (provider, reason) WHERE closed_at IS NULL"
    )
    op.execute("CREATE INDEX provider_incident_provider_opened ON provider_incident (provider, opened_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE provider_incident")
```

- [ ] **Step 2: Write the failing DB tests**

```python
# tests/api/test_provider_incidents_db.py
"""The incident recorder on the lane database: open once, count, close once, tell Sentry twice."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sentry_sdk.transport import Transport
from sqlalchemy import text

from clue_api.provider_incidents import (
    FAILURE_THRESHOLD,
    incident_sentence,
    open_incidents,
    record_failure,
    record_success,
)
from clue_core.provider_failures import ProviderFailure
from clue_obs.sentry import install_sentry
from tests.claimstore.conftest import require_claimstore_db, rollback_conn  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

NOW = datetime(2026, 9, 16, 10, 31, 23, tzinfo=UTC)
KEY_LIMIT = ProviderFailure("openrouter", "refusal", "key_limit", "Key limit exceeded (weekly limit)")
FIVE_OH_THREE = ProviderFailure("exa", "failure", "server_error", "upstream unavailable")


class StubTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


@pytest.fixture
def sentry() -> StubTransport:
    transport = StubTransport()
    assert install_sentry(dsn="https://k@o1.ingest.sentry.io/1", environment="test", release=None, process_name="t", transport=transport)
    return transport


def test_a_refusal_opens_once_counts_afterwards_and_closes_on_success(sentry: StubTransport) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            opened = await record_failure(conn, KEY_LIMIT, surface="research_job", workspace_id="ws_a", now=NOW)
            assert opened is not None and opened.failure_count == 1 and opened.notified
            again = await record_failure(conn, KEY_LIMIT, surface="display_section", workspace_id="ws_b", now=NOW + timedelta(seconds=12))
            assert again is not None and again.incident_id == opened.incident_id
            assert again.failure_count == 2 and again.surfaces == {"research_job": 1, "display_section": 1}
            (live,) = await open_incidents(conn, providers=["openrouter"])
            assert live.incident_id == opened.incident_id
            closed = await record_success(conn, "openrouter", now=NOW + timedelta(hours=2, minutes=14))
            assert [c.incident_id for c in closed] == [opened.incident_id]
            assert await open_incidents(conn) == ()
            row = (await conn.execute(text("SELECT closed_at, sentry_open_event_id, sentry_close_event_id FROM provider_incident WHERE incident_id = :id"), {"id": opened.incident_id})).one()
            assert row.closed_at is not None and row.sentry_open_event_id and row.sentry_close_event_id
    run_async(scenario())
    titles = [e.get("message") or e.get("logentry", {}).get("message") for e in sentry.events]
    assert titles == [
        "Model provider refused: key limit exceeded",
        "Model provider recovered after 2h 14m — 2 calls failed (1 research job, 1 overview section)",
    ]
    assert [e["level"] for e in sentry.events] == ["error", "info"]
    assert sentry.events[0]["tags"]["provider"] == "openrouter" and sentry.events[0]["tags"]["reason"] == "key_limit"
    assert sentry.events[0]["fingerprint"] == sentry.events[1]["fingerprint"]


def test_failures_open_only_at_the_threshold_inside_the_window(sentry: StubTransport) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            for n in range(FAILURE_THRESHOLD - 1):
                assert await record_failure(conn, FIVE_OH_THREE, surface="discovery", workspace_id=None, now=NOW + timedelta(seconds=n)) is None
            assert await open_incidents(conn) == ()
            opened = await record_failure(conn, FIVE_OH_THREE, surface="discovery", workspace_id=None, now=NOW + timedelta(seconds=5))
            assert opened is not None and opened.kind == "failure" and opened.failure_count == FAILURE_THRESHOLD
            # An old failure outside the window does not count toward a new incident.
            await record_success(conn, "exa", now=NOW + timedelta(minutes=1))
            assert await record_failure(conn, FIVE_OH_THREE, surface="discovery", workspace_id=None, now=NOW + timedelta(minutes=30)) is None
    run_async(scenario())
    assert [e["level"] for e in sentry.events] == ["error", "info"]
    assert (sentry.events[0].get("message") or sentry.events[0]["logentry"]["message"]) == "Discovery provider failing: server errors"


def test_two_writers_racing_on_the_same_refusal_open_one_incident(sentry: StubTransport) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            results = await asyncio.gather(
                record_failure(conn, KEY_LIMIT, surface="chat_turn", workspace_id="ws_a", now=NOW),
                record_failure(conn, KEY_LIMIT, surface="research_job", workspace_id="ws_a", now=NOW),
            )
            ids = {r.incident_id for r in results if r is not None}
            assert len(ids) == 1
    run_async(scenario())
    assert len([e for e in sentry.events if e["level"] == "error"]) == 1


def test_the_recorder_never_raises_into_the_call_it_observes() -> None:
    class BrokenConn:
        async def execute(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("db down")
    async def scenario() -> None:
        assert await record_failure(BrokenConn(), KEY_LIMIT, surface="x", workspace_id=None, now=NOW) is None  # type: ignore[arg-type]
        assert await record_success(BrokenConn(), "openrouter", now=NOW) == ()  # type: ignore[arg-type]
    run_async(scenario())


def test_the_inline_sentence_reads_as_the_founder_approved() -> None:
    since = datetime(2026, 9, 16, 16, 1, tzinfo=UTC)
    assert incident_sentence(provider="openrouter", kind="refusal", reason="key_limit", since=since, affected=45, unit="jobs", notified=True) == (
        "Model provider refused: key limit exceeded. Since 16:01, 45 jobs affected. Clue has been notified."
    )
    assert incident_sentence(provider="exa_websets", kind="refusal", reason="credits_exhausted", since=since, affected=None, unit="calls", notified=False) == (
        "Discovery provider refused: credits exhausted. Since 16:01."
    )
    assert incident_sentence(provider="openrouter", kind="failure", reason="server_error", since=since, affected=7, unit="calls", notified=True) == (
        "Model provider failing: server errors. Since 16:01, 7 calls affected. Clue has been notified."
    )
```

- [ ] **Step 3: Apply the migration to the lane DB and run the tests to verify they fail**

Run: `set -a; source .env; set +a; uv run alembic upgrade head && env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_provider_incidents_db.py -p no:cacheprovider -q`
Expected: migration applies (`provider incident`); tests FAIL with `ModuleNotFoundError: clue_api.provider_incidents`.

- [ ] **Step 4: Write the recorder**

```python
# platform/api/clue_api/provider_incidents.py
"""Provider incidents: the durable record that a provider stopped serving us, and the two
Sentry events per incident (design 2026-09-16 §3.3).

Two writers feed :func:`record_failure` / :func:`record_success` — the ARV2 ledger drain and the
chat turn's model-call handler. The partial unique index ``provider_incident_one_open`` is the
open-once rule; the process whose insert returns a row fires the open event, the process whose
close returns rows fires the close event. Nothing here may raise into the call it observes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import sentry_sdk
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core.provider_failures import ProviderFailure
from clue_obs import get_logger
from clue_obs.sentry import sentry_is_installed

__all__ = [
    "FAILURE_THRESHOLD",
    "FAILURE_WINDOW",
    "OpenIncident",
    "incident_sentence",
    "open_incidents",
    "provider_display",
    "reason_words",
    "record_failure",
    "record_success",
]

log = get_logger("clue_api.provider_incidents")

#: A failure (429, 5xx, timeout) opens an incident only when the provider has failed this many
#: times inside the window — the caller's own retries absorb a single fault. Refusals open on the
#: first sight; a refusal is a decision, not a fault.
FAILURE_THRESHOLD = 3
FAILURE_WINDOW = timedelta(minutes=5)

_DISPLAY = {
    "openrouter": "Model provider",
    "exa": "Discovery provider",
    "exa_websets": "Discovery provider",
    "live_http": "Website fetch",
}
_REASON_WORDS = {
    "credits_exhausted": "credits exhausted",
    "key_limit": "key limit exceeded",
    "auth_invalid": "API key rejected",
    "account_suspended": "account suspended",
    "rate_limited": "rate limited",
    "server_error": "server errors",
    "timeout": "timeouts",
}
_SURFACE_WORDS = {
    "research_job": ("research job", "research jobs"),
    "display_section": ("overview section", "overview sections"),
    "chat_turn": ("chat turn", "chat turns"),
    "discovery": ("discovery call", "discovery calls"),
    "onboarding": ("onboarding call", "onboarding calls"),
}


def provider_display(provider: str) -> str:
    return _DISPLAY.get(provider, provider)


def reason_words(reason: str) -> str:
    return _REASON_WORDS.get(reason, reason.replace("_", " "))


@dataclass(frozen=True)
class OpenIncident:
    incident_id: UUID
    provider: str
    kind: str
    reason: str
    opened_at: datetime
    failure_count: int
    sample_message: str
    surfaces: dict[str, int]
    notified: bool


_INSERT = text(
    """
    INSERT INTO provider_incident (incident_id, provider, kind, reason, opened_at, last_failure_at,
        failure_count, sample_message, surfaces_json, workspaces_json)
    VALUES (:id, :provider, :kind, :reason, :now, :now, :count, :message,
        CAST(:surfaces AS jsonb), CAST(:workspaces AS jsonb))
    ON CONFLICT (provider, reason) WHERE closed_at IS NULL DO NOTHING
    RETURNING incident_id
    """
)
_INCREMENT = text(
    """
    UPDATE provider_incident
       SET failure_count = failure_count + 1,
           last_failure_at = :now,
           surfaces_json = surfaces_json || jsonb_build_object(:surface,
               COALESCE((surfaces_json ->> :surface)::int, 0) + 1),
           workspaces_json = CASE WHEN :workspace IS NULL OR workspaces_json ? :workspace
               THEN workspaces_json ELSE workspaces_json || to_jsonb(:workspace::text) END
     WHERE provider = :provider AND reason = :reason AND closed_at IS NULL
    RETURNING incident_id, provider, kind, reason, opened_at, failure_count, sample_message,
              surfaces_json, sentry_open_event_id
    """
)
_SELECT_OPEN = text(
    """
    SELECT incident_id, provider, kind, reason, opened_at, failure_count, sample_message,
           surfaces_json, sentry_open_event_id
      FROM provider_incident
     WHERE closed_at IS NULL AND (:all OR provider = ANY(:providers))
     ORDER BY opened_at
    """
)
_CLOSE = text(
    """
    UPDATE provider_incident SET closed_at = :now
     WHERE provider = :provider AND closed_at IS NULL
    RETURNING incident_id, provider, kind, reason, opened_at, failure_count, sample_message,
              surfaces_json, sentry_open_event_id
    """
)
_STAMP_EVENT = text(
    "UPDATE provider_incident SET sentry_open_event_id = COALESCE(sentry_open_event_id, :open_id), "
    "sentry_close_event_id = COALESCE(sentry_close_event_id, :close_id) WHERE incident_id = :id"
)
#: Recent classified failures for one provider, from the two ledgers that already exist: the
#: ARV2 provider ledger (Task 3 stamps ``extras_json.provider_failure``) and the chat turn's
#: model-call receipts (Task 5 stamps ``provider_failed:`` codes).
_RECENT_FAILURES = text(
    """
    SELECT (SELECT count(*) FROM provider_call_ledger
             WHERE phase = 'result' AND provider = :provider AND recorded_at > :since
               AND extras_json -> 'provider_failure' ->> 'kind' = 'failure')
         + (SELECT count(*) FROM agent_model_call
             WHERE status = 'failed' AND started_at > :since
               AND error_code LIKE 'provider_failed:' || :provider || ':%')
    """
)


def _incident(row: Any) -> OpenIncident:
    surfaces = row.surfaces_json if isinstance(row.surfaces_json, dict) else json.loads(row.surfaces_json or "{}")
    return OpenIncident(
        incident_id=row.incident_id,
        provider=row.provider,
        kind=row.kind,
        reason=row.reason,
        opened_at=row.opened_at,
        failure_count=row.failure_count,
        sample_message=row.sample_message,
        surfaces={str(k): int(v) for k, v in surfaces.items()},
        notified=row.sentry_open_event_id is not None,
    )


def _sentry_event(title: str, *, level: str, incident: OpenIncident) -> str | None:
    if not sentry_is_installed():
        return None
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("provider", incident.provider)
        scope.set_tag("reason", incident.reason)
        scope.set_tag("kind", incident.kind)
        scope.fingerprint = ["provider-incident", incident.provider, incident.reason, incident.opened_at.isoformat()]
        scope.set_extra("failure_count", incident.failure_count)
        scope.set_extra("surfaces", incident.surfaces)
        scope.set_extra("sample_message", incident.sample_message)
        return sentry_sdk.capture_message(title, level=level)


def _surface_breakdown(surfaces: dict[str, int]) -> str:
    parts = []
    for surface, count in sorted(surfaces.items(), key=lambda item: (-item[1], item[0])):
        one, many = _SURFACE_WORDS.get(surface, (surface, surface + "s"))
        parts.append(f"{count} {one if count == 1 else many}")
    return ", ".join(parts)


def _duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def incident_sentence(*, provider: str, kind: str, reason: str, since: datetime, affected: int | None, unit: str, notified: bool) -> str:
    verb = "refused" if kind == "refusal" else "failing"
    sentence = f"{provider_display(provider)} {verb}: {reason_words(reason)}. Since {since:%H:%M}"
    if affected:
        sentence += f", {affected} {unit} affected"
    sentence += "."
    if notified:
        sentence += " Clue has been notified."
    return sentence


async def record_failure(conn: AsyncConnection, failure: ProviderFailure, *, surface: str, workspace_id: str | None, now: datetime) -> OpenIncident | None:
    """One classified failure. Returns the open incident it landed on, or ``None`` when none is open
    (a failure below the threshold), or on any error of its own."""
    try:
        incremented = (await conn.execute(_INCREMENT, {"now": now, "surface": surface, "workspace": workspace_id, "provider": failure.provider, "reason": failure.reason})).first()
        if incremented is not None:
            return _incident(incremented)
        if failure.kind == "failure":
            recent = (await conn.execute(_RECENT_FAILURES, {"provider": failure.provider, "since": now - FAILURE_WINDOW})).scalar_one()
            if int(recent) < FAILURE_THRESHOLD:
                return None
        count = FAILURE_THRESHOLD if failure.kind == "failure" else 1
        inserted = (await conn.execute(_INSERT, {
            "id": uuid.uuid4(), "provider": failure.provider, "kind": failure.kind, "reason": failure.reason,
            "now": now, "count": count, "message": failure.message,
            "surfaces": json.dumps({surface: 1}), "workspaces": json.dumps([workspace_id] if workspace_id else []),
        })).first()
        if inserted is None:
            # Lost the race to another process: count ours onto theirs.
            again = (await conn.execute(_INCREMENT, {"now": now, "surface": surface, "workspace": workspace_id, "provider": failure.provider, "reason": failure.reason})).first()
            return _incident(again) if again is not None else None
        (row,) = (await conn.execute(_SELECT_OPEN, {"all": False, "providers": [failure.provider]})).all() or (None,)
        if row is None:
            return None
        incident = _incident(row)
        title = f"{provider_display(incident.provider)} {'refused' if incident.kind == 'refusal' else 'failing'}: {reason_words(incident.reason)}"
        event_id = _sentry_event(title, level="error", incident=incident)
        if event_id is not None:
            await conn.execute(_STAMP_EVENT, {"open_id": event_id, "close_id": None, "id": incident.incident_id})
        log.warning("provider_incident.opened", provider=incident.provider, reason=incident.reason, kind=incident.kind, surface=surface, sentry_event_id=event_id)
        return _incident((await conn.execute(_SELECT_OPEN, {"all": False, "providers": [failure.provider]})).one())
    except Exception:
        log.exception("provider_incident.recorder_failed", provider=failure.provider, reason=failure.reason, surface=surface)
        return None


async def record_success(conn: AsyncConnection, provider: str, *, now: datetime) -> tuple[OpenIncident, ...]:
    """One successful call: closes every open incident of the provider, one Sentry event each."""
    try:
        rows = (await conn.execute(_CLOSE, {"now": now, "provider": provider})).all()
        closed: list[OpenIncident] = []
        for row in rows:
            incident = _incident(row)
            title = (
                f"{provider_display(provider)} recovered after {_duration(now - incident.opened_at)} — "
                f"{incident.failure_count} calls failed ({_surface_breakdown(incident.surfaces)})"
            )
            event_id = _sentry_event(title, level="info", incident=incident)
            if event_id is not None:
                await conn.execute(_STAMP_EVENT, {"open_id": None, "close_id": event_id, "id": incident.incident_id})
            log.info("provider_incident.closed", provider=provider, reason=incident.reason, failure_count=incident.failure_count, sentry_event_id=event_id)
            closed.append(incident)
        return tuple(closed)
    except Exception:
        log.exception("provider_incident.recorder_failed", provider=provider, reason="close")
        return ()


async def open_incidents(conn: AsyncConnection, *, providers: Iterable[str] | None = None) -> tuple[OpenIncident, ...]:
    try:
        wanted = list(providers) if providers is not None else []
        rows = (await conn.execute(_SELECT_OPEN, {"all": providers is None, "providers": wanted})).all()
        return tuple(_incident(row) for row in rows)
    except Exception:
        log.exception("provider_incident.recorder_failed", reason="read")
        return ()
```

Notes for the implementer: `sentry_sdk.new_scope()` and `scope.fingerprint = [...]` are sentry-sdk 2.x; `capture_message` returns the event id string. The Sentry title assertions in the test read `event["message"]` or `event["logentry"]["message"]` — keep both spellings in the test as written. `Provider` display words in the close title use `provider_display`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_provider_incidents_db.py -p no:cacheprovider -q && uv run ruff check platform/api/clue_api/provider_incidents.py tests/api/test_provider_incidents_db.py && uv run mypy platform/api/clue_api/provider_incidents.py`
Expected: 5 passed; lint and mypy clean. Also run `uv run alembic heads` → exactly one head (the new revision).

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/*_provider_incident.py platform/api/clue_api/provider_incidents.py tests/api/test_provider_incidents_db.py
git commit -m "feat(incidents): provider_incident table and recorder — open once per (provider, reason), count, close on success; one Sentry event each way"
```

---

### Task 3: The ARV2 caller stamps the classification; the drain records incidents

**Files:**
- Modify: `platform/api/clue_api/arv2/calls.py` (the `transport_error` result row at ~line 388, the halt path at ~466, the non-2xx settle at ~476, and `_settle` itself at 668)
- Modify: `platform/api/clue_api/arv2/provider_ledger.py::drain_provider_calls` (line 186)
- Test: `tests/arv2/test_calls.py` (append), `tests/arv2/test_provider_ledger_db.py` (append)

**Interfaces:**
- Consumes: `classify_http` (Task 1); `record_failure`, `record_success` (Task 2).
- Produces: a failing `result` ledger row carries `extras["provider_failure"] = {"kind", "reason", "message"}` (JSON-safe strings); a successful `result` row carries no such key. `drain_provider_calls` calls `record_success(conn, provider, now=row.recorded_at)` once per provider that had an `ok` result row in the batch, and `record_failure(conn, ProviderFailure(...), surface=<from stamp>, workspace_id=stamp.workspace_id, now=row.recorded_at)` once per stamped failing row, **after** the ledger rows are inserted (so the threshold count sees them). `surface` is `"research_job"` when `stamp.job_id` is set, `"discovery"` when `stamp.project_run_id` is set without a job, else `"display_section"` for `operation == "chat/completions"` and labels starting `display-`, else `"onboarding"` for labels starting `onboarding`, else the row's `operation`.

- [ ] **Step 1: Write the failing caller tests** (append to `tests/arv2/test_calls.py`, using its `_caller`, `_spec`, `HttpResponse`, `TransportFailure`, `ProviderHalted` already imported there)

```python
def test_a_refusal_row_carries_the_classified_provider_failure() -> None:
    body = b"{'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/x', 'code': 403}}"
    caller, _, _, ledger, _ = _caller([HttpResponse(403, {}, body)])
    spec = _spec(provider="openrouter", operation="chat/completions", label="display-overview-what-they-do", max_attempts=1)
    result = caller.call(spec)
    assert result.response.status == 403
    (row,) = [r for r in ledger.rows if r.phase == "result"]
    assert row.extras["provider_failure"] == {"kind": "refusal", "reason": "key_limit", "message": "Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/x"}


def test_a_halt_row_carries_the_classification_too() -> None:
    body = b'{"error":"payment_required"}'
    caller, _, _, ledger, _ = _caller([HttpResponse(402, {}, body)])
    spec = _spec(provider="exa_websets", operation="websets:create", label="websets", max_attempts=1, halt_rule=lambda r: "payment_required" if r.status == 402 else None)
    with pytest.raises(ProviderHalted):
        caller.call(spec)
    (row,) = [r for r in ledger.rows if r.phase == "result"]
    assert row.outcome == "halted"
    assert row.extras["provider_failure"] == {"kind": "refusal", "reason": "credits_exhausted", "message": '{"error":"payment_required"}'}


def test_a_transport_error_row_is_a_timeout_failure_and_a_success_row_carries_nothing() -> None:
    caller, _, _, ledger, _ = _caller([TransportFailure("connection reset")])
    with pytest.raises(Exception):
        caller.call(_spec(provider="live_http", max_attempts=1))
    (row,) = [r for r in ledger.rows if r.phase == "result"]
    assert row.extras["provider_failure"] == {"kind": "failure", "reason": "timeout", "message": "connection reset"}
    caller, _, _, ledger, _ = _caller([HttpResponse(200, {}, b"{}")])
    caller.call(_spec(max_attempts=1))
    (ok,) = [r for r in ledger.rows if r.phase == "result"]
    assert "provider_failure" not in ok.extras
```

(If `_spec` does not accept `halt_rule`/`provider`/`operation`/`label` keyword overrides, read its definition at `tests/arv2/test_calls.py:67` — it builds a `CallSpec` from `**overrides`; pass the same names `CallSpec` uses.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_calls.py -k "provider_failure or classification or transport_error_row" -p no:cacheprovider -q`
Expected: FAIL — `KeyError: 'provider_failure'`.

- [ ] **Step 3: Stamp the classification in the caller**

In `platform/api/clue_api/arv2/calls.py`:

1. Import: `from clue_core.provider_failures import classify_http`.
2. Add a module-level helper after `_observation_input`:

```python
def _failure_extras(provider: str, status: int | None, body: bytes | str | None) -> dict[str, object]:
    """The classified failure as JSON-safe extras for a failing result row; ``{}`` for a success."""
    text_body = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    failure = classify_http(provider, status, text_body)
    if failure is None:
        return {}
    return {"provider_failure": {"kind": failure.kind, "reason": failure.reason, "message": failure.message}}
```

3. In the `TransportFailure` branch (the `self._record(..., outcome="transport_error", ...)` call), change `extras=` to `extras={"last_error": str(exc), **_failure_extras(spec.provider, None, str(exc)), **_langfuse_extras(current)}`.
4. In `_settle`, where the result row's `extras` are built (`extras={**cost.extras, "cost_source": source}` at the `_record` call), change to `extras={**cost.extras, **_failure_extras(spec.provider, status, response_body), "cost_source": source}`. `_settle` does not receive the body today: add a keyword parameter `response_body: bytes | None = None` to `_settle` and pass `response.body` from the two `_settle` call sites that have a response (the halt path and the final settle), leaving the raw-scrub-failed call site as is (its body was never trusted; `status` alone still classifies a 5xx).

- [ ] **Step 4: Run the caller tests to verify they pass**

Run: `uv run pytest tests/arv2/test_calls.py tests/arv2/test_calls_langfuse.py -p no:cacheprovider -q`
Expected: all pass (the existing tests included — the stamp is additive).

- [ ] **Step 5: Write the failing drain tests** (append to `tests/arv2/test_provider_ledger_db.py`, reusing its `FakeArtifacts`, `NOW`, `rollback_conn`, `run_async`)

```python
from clue_api.provider_incidents import open_incidents
from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink, LedgerStamp, drain_provider_calls
from clue_api.arv2.sinks import LedgerRow
from decimal import Decimal


def _result_row(provider: str, *, status: int, extras: dict[str, object], label: str = "round-1", operation: str = "agent_completion") -> LedgerRow:
    return LedgerRow(
        row_id=str(uuid4()), call_id=str(uuid4()), phase="result", provider=provider, operation=operation,
        label=label, recorded_at=NOW, http_status=status, latency_ms=10, attempts=1,
        cost_usd=Decimal(0), outcome="ok" if status < 400 else "client_error", extras=extras,
    )


def test_the_drain_opens_an_incident_from_a_stamped_refusal_and_closes_it_on_a_later_success() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            stamp = LedgerStamp(workspace_id="ws_drain", project_id="prj_1", project_run_id=str(uuid4()), job_id=uuid4())
            ledger = BufferedLedger()
            ledger.record(_result_row("openrouter", status=403, extras={"provider_failure": {"kind": "refusal", "reason": "key_limit", "message": "Key limit exceeded"}, "cost_source": "unpriced"}))
            await drain_provider_calls(conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp)
            (incident,) = await open_incidents(conn, providers=["openrouter"])
            assert incident.reason == "key_limit" and incident.surfaces == {"research_job": 1}
            ledger.record(_result_row("openrouter", status=200, extras={"cost_source": "metered"}))
            await drain_provider_calls(conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp)
            assert await open_incidents(conn, providers=["openrouter"]) == ()
    run_async(scenario())


def test_the_drain_counts_failures_toward_the_threshold_across_drains() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            stamp = LedgerStamp(workspace_id="ws_drain", project_run_id=str(uuid4()))
            for _ in range(2):
                ledger = BufferedLedger()
                ledger.record(_result_row("exa", status=503, operation="answer", label="discovery:x", extras={"provider_failure": {"kind": "failure", "reason": "server_error", "message": "503"}, "cost_source": "estimate"}))
                await drain_provider_calls(conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp)
            assert await open_incidents(conn, providers=["exa"]) == ()
            ledger = BufferedLedger()
            ledger.record(_result_row("exa", status=503, operation="answer", label="discovery:y", extras={"provider_failure": {"kind": "failure", "reason": "server_error", "message": "503"}, "cost_source": "estimate"}))
            await drain_provider_calls(conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp)
            (incident,) = await open_incidents(conn, providers=["exa"])
            assert incident.kind == "failure" and incident.surfaces == {"discovery": 1}
    run_async(scenario())
```

- [ ] **Step 6: Run the drain tests to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_provider_ledger_db.py -k "incident or threshold" -p no:cacheprovider -q`
Expected: FAIL — `open_incidents` returns `()` after the refusal drain.

- [ ] **Step 7: Record incidents in the drain**

In `platform/api/clue_api/arv2/provider_ledger.py`:

```python
from clue_api.provider_incidents import record_failure, record_success
from clue_core.provider_failures import ProviderFailure


def _surface_for(row: LedgerRow, stamp: LedgerStamp) -> str:
    if stamp.job_id is not None:
        return "research_job"
    if row.operation == "chat/completions" and row.label.startswith("display-"):
        return "display_section"
    if stamp.project_run_id is not None:
        return "discovery"
    if row.label.startswith("onboarding"):
        return "onboarding"
    return row.operation


def _stamped_failure(row: LedgerRow) -> ProviderFailure | None:
    stamped = row.extras.get("provider_failure")
    if not isinstance(stamped, Mapping):
        return None
    try:
        return ProviderFailure(row.provider, stamped["kind"], stamped["reason"], str(stamped.get("message", "")))  # type: ignore[arg-type]
    except KeyError:
        return None


async def _record_incidents(conn: AsyncConnection, rows: Sequence[LedgerRow], *, stamp: LedgerStamp) -> None:
    """After the rows are in: every stamped failure lands on an incident, every provider with an
    ``ok`` result closes its incidents. Successes are folded per provider so a batch of thirty
    good rows costs one indexed UPDATE, and closes run AFTER failures so a batch that holds both
    (a retry that finally worked) ends closed, which is what the provider's last word was."""
    results = [row for row in rows if row.phase == "result"]
    for row in results:
        failure = _stamped_failure(row)
        if failure is not None:
            await record_failure(conn, failure, surface=_surface_for(row, stamp), workspace_id=stamp.workspace_id, now=row.recorded_at)
    recovered: dict[str, datetime] = {}
    for row in results:
        if row.outcome == "ok" and _stamped_failure(row) is None:
            recovered[row.provider] = max(recovered.get(row.provider, row.recorded_at), row.recorded_at)
    for provider, at in recovered.items():
        await record_success(conn, provider, now=at)
```

and in `drain_provider_calls`, after the `for row in rows: await conn.execute(_INSERT_LEDGER, ...)` loop and before building `results`, add `await _record_incidents(conn, rows, stamp=stamp)`. Add `Sequence` and `Mapping` to the `collections.abc` import if missing.

- [ ] **Step 8: Run the drain tests and the ledger suites to verify they pass**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_provider_ledger.py tests/arv2/test_provider_ledger_db.py -p no:cacheprovider -q && uv run ruff check platform/api/clue_api/arv2/calls.py platform/api/clue_api/arv2/provider_ledger.py && uv run mypy platform/api/clue_api/arv2/provider_ledger.py platform/api/clue_api/arv2/calls.py`
Expected: all pass; clean. Then the import guard, which must stay green: `uv run pytest tests/arv2/test_import_guard.py -p no:cacheprovider -q` — it fails today for `icp_authoring.py` only (pre-existing); this task must add no second offender (`clue_api.provider_incidents` is under `clue_api.*`; the guard's allowlist names `clue_api.arv2`, `clue_api.composition`, `clue_api.arv2_wiring` — if the guard flags `clue_api.provider_incidents`, add it to the allowlist in the guard test with a one-line reason: the incident recorder is platform infrastructure the lane reports into, not lane logic).

- [ ] **Step 9: Commit**

```bash
git add platform/api/clue_api/arv2/calls.py platform/api/clue_api/arv2/provider_ledger.py tests/arv2/test_calls.py tests/arv2/test_provider_ledger_db.py tests/arv2/test_import_guard.py
git commit -m "feat(incidents): the ARV2 caller stamps the classified failure on its ledger row; the drain opens, counts and closes incidents"
```

---

### Task 4: Research jobs carry the provider reason

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_agent.py` (`_ModelUsageRecorder.awrap_model_call` at ~155 and `_record` at ~160-215; `AgentOutcome` at ~104; the `model_error` outcome at ~349)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`finish_job` call at ~922-935)
- Test: `tests/arv2/test_account_research_agent.py` (append), `tests/arv2/test_account_research_driver_db.py` (append)

**Interfaces:**
- Consumes: `classify_exception`, `failure_code` (Task 1).
- Produces: a round row that raised carries `extras["provider_failure"]` when the exception classifies (so Task 3's drain opens the incident); `AgentOutcome` gains `provider_failure: ProviderFailure | None = None`; `finish_job` receives `failure_code=failure_code(outcome.provider_failure)` when set, else `"model_error"` as today.

- [ ] **Step 1: Write the failing agent test** (append to `tests/arv2/test_account_research_agent.py`; find how that file builds a `_ModelUsageRecorder` or an `AgentOutcome` — it already constructs a fake `ToolRuntime` with a `model_ledger`; reuse its helper names)

```python
class _Denied(Exception):
    status_code = 403
    def __init__(self) -> None:
        super().__init__("Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)', 'code': 403}}")


def test_a_round_that_is_refused_stamps_the_provider_failure_on_its_ledger_row() -> None:
    runtime = _fake_runtime()  # the module's existing fake, with a BufferedLedger at runtime.model_ledger
    recorder = _ModelUsageRecorder(runtime, attempt=1)

    async def handler(_request: object) -> object:
        raise _Denied()

    with pytest.raises(_Denied):
        asyncio.run(recorder.awrap_model_call(object(), handler))
    (row,) = runtime.model_ledger.drain()
    assert row.error_code == "_Denied"
    assert row.extras["provider_failure"] == {"kind": "refusal", "reason": "key_limit", "message": "Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)', 'code': 403}}"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/arv2/test_account_research_agent.py -k stamps_the_provider_failure -p no:cacheprovider -q`
Expected: FAIL — `KeyError: 'provider_failure'`.

- [ ] **Step 3: Stamp the round row and carry the failure on the outcome**

In `account_research_agent.py`:

```python
from clue_core.provider_failures import ProviderFailure, classify_exception, failure_code
```

- `_ModelUsageRecorder.awrap_model_call`: in the `except Exception as error:` branch, compute `failure = classify_exception("openrouter", error)` and pass `provider_failure=failure` to `self._record(...)`; also keep the last classified failure on the recorder: `self.last_provider_failure = failure` (initialise to `None` in `__init__`).
- `_ModelUsageRecorder._record`: add the keyword `provider_failure: ProviderFailure | None = None`; when it is not `None`, add `"provider_failure": {"kind": ..., "reason": ..., "message": ...}` to `extras` (the `extras` dict is built at the top of `_record` — add the key after `cost_source`).
- `AgentOutcome`: add `provider_failure: ProviderFailure | None = None`.
- Where the loop returns `AgentOutcome("model_error", rounds.count, runtime.tool_calls, detail, rounds.spend)` (~line 349), pass `provider_failure=rounds.last_provider_failure`.

In `account_research_driver.py` (~line 922):

```python
            status = "needs_review" if outcome.reason == "model_error" else "completed"
            code = None
            if status == "needs_review":
                code = failure_code(outcome.provider_failure) if outcome.provider_failure else "model_error"
            await self._store.finish_job(
                conn,
                job_id=composition.job.job_id,
                status=status,
                finalization=finalization,
                failure_code=code,
                ...
```

(import `failure_code` from `clue_core.provider_failures`). The `arv2_research_job_failure` biconditional CHECK is satisfied: `needs_review` ⇔ a non-null code.

- [ ] **Step 4: Write the failing driver DB test** (append to `tests/arv2/test_account_research_driver_db.py`, using that module's existing fixtures for a job and a driver with a scripted agent; assert on the stored row)

```python
def test_a_refused_model_round_lands_the_provider_reason_as_the_job_failure_code() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            job = await _seed_job(conn)  # the module's existing seeding helper
            outcome = AgentOutcome("model_error", 1, 0, "Key limit exceeded", provider_failure=ProviderFailure("openrouter", "refusal", "key_limit", "Key limit exceeded"))
            await _drive_with_outcome(conn, job, outcome)  # the module's existing driver harness
            row = (await conn.execute(text("SELECT status, failure_code FROM arv2_research_job WHERE job_id = :id"), {"id": job.job_id})).one()
            assert (row.status, row.failure_code) == ("needs_review", "provider_refused:openrouter:key_limit")
    run_async(scenario())
```

(The two helper names are illustrative of what that file already has — use its real ones. If the file has no way to inject an `AgentOutcome`, test the mapping in isolation instead: extract the three lines that compute `code` into `def _job_failure_code(outcome: AgentOutcome) -> str | None` in the driver module and unit-test that function with the two outcomes.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_account_research_agent.py tests/arv2/test_account_research_driver.py tests/arv2/test_account_research_driver_db.py -p no:cacheprovider -q && uv run ruff check platform/api/clue_api/arv2/account_research_agent.py platform/api/clue_api/arv2/account_research_driver.py && uv run mypy platform/api/clue_api/arv2/account_research_agent.py platform/api/clue_api/arv2/account_research_driver.py`
Expected: all pass; clean.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_agent.py platform/api/clue_api/arv2/account_research_driver.py tests/arv2/test_account_research_agent.py tests/arv2/test_account_research_driver_db.py
git commit -m "feat(incidents): a refused model round stamps its failure on the ledger row and the job records provider_refused:<provider>:<reason>"
```

---

### Task 5: Chat turns carry the provider reason and feed the recorder

**Files:**
- Modify: `platform/api/clue_api/agent_runtime_wiring.py` (`DurableAgentModelCallHandler.__init__` at 140-157, `on_llm_end` at 191, `on_llm_error` at 251-269; construction at 1347)
- Modify: `platform/agents/clue_agents/runtime.py` (`_error_code` at 265)
- Test: `tests/api/test_agent_runtime_wiring_answering_model.py` (append — it already has fakes for the handler), `tests/agents/test_runtime_error_code.py` (create)

**Interfaces:**
- Consumes: `classify_exception`, `failure_code` (Task 1); `record_failure`, `record_success` (Task 2); `ConnFactory` from `clue_db`.
- Produces: `DurableAgentModelCallHandler(..., incidents_conn_factory: ConnFactory | None = None)`; a failed model call's receipt `error_code` is `provider_refused:openrouter:key_limit` (or `provider_failed:…`) when the exception classifies, else `_stable_error_code(error)` as today; `on_llm_error` calls `record_failure(conn, failure, surface="chat_turn", workspace_id=<constitution workspace>, now=datetime.now(UTC))`, `on_llm_end` calls `record_success(conn, "openrouter", now=...)`, both under `async with self._incidents_conn_factory() as conn:` and both skipped when the factory is `None`. `clue_agents.runtime._error_code(exc)` returns `failure_code(classify_exception("openrouter", exc))` when it classifies, else the class-name code — so the turn's `failure_code` reads `provider_refused:openrouter:key_limit` instead of `permission_denied_error`.

- [ ] **Step 1: Write the failing handler tests** (append to `tests/api/test_agent_runtime_wiring_answering_model.py`; extend its `_Turns` fake to also capture `error_code` via `receipt.error_code`, and add a fake conn factory)

```python
from contextlib import asynccontextmanager


class _Recording:
    """Stands in for the incident recorder's connection: records what the handler asked for."""
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []


def _handler_with_incidents(turns: _Turns, recorder_calls: list[tuple[str, object]]) -> DurableAgentModelCallHandler:
    @asynccontextmanager
    async def factory():
        yield object()
    handler = DurableAgentModelCallHandler(
        request=_request(), requested_model="x-ai/grok-4.6", initial_sequence=1,
        artifacts=_Artifacts(), turns=turns, incidents_conn_factory=factory,  # type: ignore[arg-type]
    )
    return handler


class _Denied(Exception):
    status_code = 403
    def __init__(self) -> None:
        super().__init__("Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)', 'code': 403}}")


def test_a_refused_model_call_records_the_provider_code_and_an_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    async def fake_failure(conn, failure, *, surface, workspace_id, now):
        calls.append(("failed", (failure.reason, surface, workspace_id)))
    async def fake_success(conn, provider, *, now):
        calls.append(("succeeded", provider))
    monkeypatch.setattr("clue_api.agent_runtime_wiring.record_failure", fake_failure)
    monkeypatch.setattr("clue_api.agent_runtime_wiring.record_success", fake_success)
    turns = _Turns()
    handler = _handler_with_incidents(turns, calls)
    run_id = UUID("00000000-0000-0000-0000-00000000b22b")

    async def drive() -> None:
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_error(_Denied(), run_id=run_id)

    asyncio.run(drive())
    (receipt,) = turns.receipts
    assert receipt.error_code == "provider_refused:openrouter:key_limit"
    assert calls == [("failed", ("key_limit", "chat_turn", "ws_test"))]


def test_a_completed_model_call_closes_the_providers_incidents(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    async def fake_success(conn, provider, *, now):
        calls.append(("succeeded", provider))
    monkeypatch.setattr("clue_api.agent_runtime_wiring.record_success", fake_success)
    turns = _Turns()
    handler = _handler_with_incidents(turns, calls)
    run_id = UUID("00000000-0000-0000-0000-00000000b33b")

    async def drive() -> None:
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="ok", response_metadata={"clue_answering_model": "x-ai/grok-4.6"}))]]), run_id=run_id)

    asyncio.run(drive())
    assert calls == [("succeeded", "openrouter")]


def test_without_a_factory_the_handler_records_nothing_and_keeps_the_class_code() -> None:
    turns = _Turns()
    # the module's existing handler builder without incidents_conn_factory
    ...
    assert turns.receipts[0].error_code == "_denied"
```

(`_request()` is the `SimpleNamespace` request the file already builds inline — extract it into a helper if needed. `ws_test` is that file's workspace id.)

- [ ] **Step 2: Write the failing runtime test**

```python
# tests/agents/test_runtime_error_code.py
from clue_agents.runtime import _error_code


class PermissionDeniedError(Exception):
    status_code = 403
    def __init__(self) -> None:
        super().__init__("Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)'}}")


class WeirdThingHappened(Exception): ...


def test_a_classified_provider_failure_becomes_the_provider_code() -> None:
    assert _error_code(PermissionDeniedError()) == "provider_refused:openrouter:key_limit"


def test_anything_else_keeps_the_class_name_code() -> None:
    assert _error_code(WeirdThingHappened()) == "weird_thing_happened"
```

- [ ] **Step 3: Run both to verify they fail**

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_agent_runtime_wiring_answering_model.py tests/agents/test_runtime_error_code.py -p no:cacheprovider -q`
Expected: FAIL — `TypeError: unexpected keyword argument 'incidents_conn_factory'`; `assert 'permission_denied_error' == 'provider_refused:...'`.

- [ ] **Step 4: Implement**

`platform/agents/clue_agents/runtime.py`:

```python
from clue_core.provider_failures import classify_exception, failure_code

def _error_code(exc: BaseException) -> str:
    # A provider that refused or failed is named for what it did, not for the SDK class that
    # carried the news: the transcript and the incident record read the same code.
    failure = classify_exception("openrouter", exc)
    if failure is not None:
        return failure_code(failure)
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
    return value or "agent_turn_failed"
```

(`clue_agents` already imports `clue_core` in three modules, so the dependency is allowed.)

`platform/api/clue_api/agent_runtime_wiring.py`:

```python
from clue_api.provider_incidents import record_failure, record_success
from clue_core.provider_failures import classify_exception, failure_code
```

- `__init__`: add `incidents_conn_factory: ConnFactory | None = None`, store as `self._incidents_conn_factory`.
- `on_llm_end`: after `await self._record(...)`, add

```python
        if self._incidents_conn_factory is not None:
            async with self._incidents_conn_factory() as conn:
                await record_success(conn, "openrouter", now=datetime.now(UTC))
```

- `on_llm_error`: compute `failure = classify_exception("openrouter", error)`; pass `error_code=failure_code(failure) if failure is not None else _stable_error_code(error)`; after the record, when `failure is not None and self._incidents_conn_factory is not None`:

```python
            async with self._incidents_conn_factory() as conn:
                await record_failure(conn, failure, surface="chat_turn", workspace_id=self._request.constitution.workspace_id, now=datetime.now(UTC))
```

- Construction at line 1347: add `incidents_conn_factory=self._conn_factory` (the runner class holds the conn factory it gives `DbAgentTurnJournal`; if the attribute has another name there, use it — `grep -n "conn_factory" platform/api/clue_api/agent_turn_fleet_wiring.py`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_agent_runtime_wiring_answering_model.py tests/agents/test_runtime_error_code.py tests/agents -p no:cacheprovider -q --ignore-glob='*_live.py' && uv run ruff check platform/api/clue_api/agent_runtime_wiring.py platform/agents/clue_agents/runtime.py && uv run mypy platform/agents/clue_agents/runtime.py platform/api/clue_api/agent_runtime_wiring.py`
Expected: pass; clean. Then the receipt DB suites on the lane DB: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_agent_runtime_wiring_db.py tests/api/test_agent_model_call_cost_receipt_db.py -p no:cacheprovider -q` — pass.

- [ ] **Step 6: Commit**

```bash
git add platform/agents/clue_agents/runtime.py platform/api/clue_api/agent_runtime_wiring.py platform/api/clue_api/agent_turn_fleet_wiring.py tests/api/test_agent_runtime_wiring_answering_model.py tests/agents/test_runtime_error_code.py
git commit -m "feat(incidents): a chat turn's refused model call records provider_refused:<provider>:<reason> and feeds the incident recorder; a success closes"
```

---

### Task 6: The three inline surfaces read the same sentence

**Files:**
- Modify: `platform/api/clue_api/arv2/research_progress.py` (`ProgressJob` at 64: add `failure_code: str | None`; `_reason` at 145)
- Modify: `platform/api/clue_api/frontend_read/research_progress.py` (`_JOBS` SQL: select `j.failure_code`; the `ProgressJob(...)` build; `ResearchProgressV1`: add `incident: ResearchProgressIncidentV1 | None`)
- Modify: `platform/api/clue_api/frontend_read/display_pages.py` (`PageRead`: add `unavailable_message: str | None`; `page()`: set `empty_message` on missing sections when generation was degraded by a classified failure or an incident is open for `openrouter`)
- Modify: `apps/frontend/src/features/projects/model/research-progress.ts` (schema: `incident` optional), `apps/frontend/src/features/projects/model/research-progress-line.ts` (attention line uses the sentence), `apps/frontend/src/features/projects/model/design-leg.ts::designTurnFailureNotice` (map `provider_refused:*` / `provider_failed:*` codes)
- Test: `tests/arv2/test_research_progress.py` (append), `tests/api/test_frontend_read_research_progress.py` (append), `tests/api/test_frontend_read_display_pages_db.py` (append), `apps/frontend/src/features/projects/model/research-progress-line.test.ts` (append), `apps/frontend/src/features/projects/model/design-leg.test.ts` (append or create)

**Interfaces:**
- Consumes: `parse_failure_code` (Task 1); `open_incidents`, `incident_sentence`, `provider_display`, `reason_words` (Task 2); `PageResult.failed`, `degraded_reason` (existing).
- Produces:
  - Research card: an attention row's `reason` for a job whose `failure_code` parses is `incident_sentence(provider, kind, reason, since=job.finished_at, affected=None, unit="jobs", notified=<open incident notified>)`; the card payload gains `incident: {"provider_label": str, "reason_label": str, "since": iso, "affected": int, "notified": bool} | null` — the open incident for the provider named by the most recent parsed job code, else `null`.
  - Overview sections: every section with `empty: true` whose key is not in live blocks gets `empty_message = "Not generated: <provider display> <refused|failing> (<reason words>). Retries automatically."` when the read's generation was degraded by `ProviderHalted`/`ProviderTransportError` **or** an incident is open for `openrouter`; `PageRead.unavailable_message` carries the same sentence for callers.
  - Failed chat turn: `designTurnFailureNotice("provider_refused:openrouter:key_limit")` → `"Model provider refused: key limit exceeded. Send another message once it is restored — Clue has been notified."`; `provider_failed:*` → `"Model provider failing: <reason words>. Send another message to try again — Clue has been notified."`. The label tables (`provider_display`, `reason_words`) are duplicated in TypeScript in `design-leg.ts` with a comment naming the Python source; a Python↔TS drift guard is out of scope.

- [ ] **Step 1: Write the failing fold test** (append to `tests/arv2/test_research_progress.py`; use its `_job(...)` helper — add `failure_code=` to the helper's signature with default `None` if it has none)

```python
def test_a_provider_refusal_reads_as_the_incident_sentence_on_the_card() -> None:
    finished = datetime(2026, 9, 16, 10, 31, 29, tzinfo=UTC)
    job = _job(status="needs_review", subject_type="person", failure_message="PermissionDeniedError: Error code: 403 - ...", failure_code="provider_refused:openrouter:key_limit", finished_at=finished)
    card = fold_progress([job], run_statuses={job.run_id: "needs_review"}, now=finished + timedelta(minutes=1))
    assert card is not None
    assert card.attention[0].reason == "Model provider refused: key limit exceeded. Since 10:31."
```

(`notified` is unknown to the pure fold, so the fold's sentence never says "Clue has been notified"; the route appends it when the open incident carries a Sentry id — see Step 5.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/arv2/test_research_progress.py -k incident_sentence -p no:cacheprovider -q`
Expected: FAIL — `TypeError: unexpected keyword 'failure_code'` or the raw `PermissionDeniedError…` text.

- [ ] **Step 3: Fold: parse the code**

`platform/api/clue_api/arv2/research_progress.py`:

```python
from clue_api.provider_incidents import incident_sentence
from clue_core.provider_failures import parse_failure_code

@dataclass(frozen=True)
class ProgressJob:
    ...
    failure_message: str | None
    failure_code: str | None = None


def _reason(job: ProgressJob) -> str:
    if job.status == "suspended":
        return "paused, waiting for a worker"
    parsed = parse_failure_code(job.failure_code)
    if parsed is not None and job.finished_at is not None:
        provider, kind, reason = parsed
        return incident_sentence(provider=provider, kind=kind, reason=reason, since=job.finished_at, affected=None, unit="jobs", notified=False)
    return _clip(job.failure_message or "needs review")
```

- [ ] **Step 4: Run the fold tests**

Run: `uv run pytest tests/arv2/test_research_progress.py -p no:cacheprovider -q` — pass.

- [ ] **Step 5: Route: select the code, add `incident` to the payload** — failing test first (append to `tests/api/test_frontend_read_research_progress.py`, inside its existing scenario style: seed a run with one `needs_review` job whose `failure_code = 'provider_refused:openrouter:key_limit'` via `UPDATE arv2_research_job`, and an open incident via `record_failure`; then GET the route and assert)

```python
def test_a_refused_job_shows_the_incident_and_the_card_names_the_provider(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            run = await _launch(conn, fixture, ...)  # as the module's first test does
            await conn.execute(text("UPDATE arv2_research_job SET status='needs_review', failure_code='provider_refused:openrouter:key_limit', failure_message='Key limit exceeded', finished_at=now() WHERE run_id=:run"), {"run": run.run_id})
            await record_failure(conn, ProviderFailure("openrouter", "refusal", "key_limit", "Key limit exceeded"), surface="research_job", workspace_id=fixture.workspace_id, now=datetime.now(UTC))
            async with _client(_app(conn, storage)) as client:
                body = (await client.get(f"{FRONTEND_READ_PREFIX}/projects/{fixture.project_id}/research/progress", headers=_headers(fixture.workspace_id))).json()["data"]
            assert body["pill"] == "needs_attention"
            assert body["attention"][0]["reason"].startswith("Model provider refused: key limit exceeded. Since ")
            assert body["incident"] == {"provider_label": "Model provider", "reason_label": "key limit exceeded", "since": body["incident"]["since"], "affected": 1, "notified": False}
    run_async(scenario())
```

Then implement in `frontend_read/research_progress.py`: add `j.failure_code` to `_JOBS`' select list and `failure_code=row["failure_code"]` to the `ProgressJob(...)`; add

```python
class ResearchProgressIncidentV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider_label: str
    reason_label: str
    since: str
    affected: int
    notified: bool
```

and `incident: ResearchProgressIncidentV1 | None` on `ResearchProgressV1`. In the route, after `fold_progress`, find the newest job whose code parses (`parse_failure_code`), and if any, `incidents = await open_incidents(conn, providers=[provider])` (inside the `async with conn_factory() as conn:` block — move the fold inside it or open a second connection); build `incident` from the first match (`affected=incident.failure_count`, `since=incident.opened_at.isoformat()`), else `None`. When the incident is `notified`, rewrite each attention reason that ends with `"."` and starts with the provider display to `reason + " Clue has been notified."`.

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_frontend_read_research_progress.py -p no:cacheprovider -q` — pass.

- [ ] **Step 6: Display: the empty section says why** — failing test first (append to `tests/api/test_frontend_read_display_pages_db.py`, reusing its `DisplayPages` construction with a runner whose transport answers 403 — that file already imports `ProviderHalted` and D2's `RoutingTransport`; script the OpenRouter route to return `HttpResponse(403, {}, b"{'error': {'message': 'Key limit exceeded (weekly limit)'}}")`)

```python
def test_a_refused_generation_leaves_the_empty_sections_saying_why(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            pages = _display_pages_with_openrouter_answering(conn, tmp_path, status=403, body=b"{'error': {'message': 'Key limit exceeded (weekly limit)'}}")
            read = await pages.page(conn, workspace_id=WS, subject_kind="account", subject_id=ACCOUNT, page="overview")
            assert read.unavailable_message == "Not generated: model provider refused (key limit exceeded). Retries automatically."
            empties = [s for s in read.display_block["sections"] if s["empty"]]
            assert empties and all(s["empty_message"] == read.unavailable_message for s in empties)
    run_async(scenario())
```

Implement in `frontend_read/display_pages.py`: `PageRead` gains `unavailable_message: str | None`. In `page()`, keep a `degrading_failure: ProviderFailure | None = None`: in the `except _DEGRADING as exc:` branch, `degrading_failure = classify_exception("openrouter", exc) if isinstance(exc, ProviderHalted | ProviderTransportError) else None` — for `ProviderHalted` use `classify_http(exc.provider, exc.http_status, exc.reason_code)` instead, since the halt carries the provider and status. After composing `display_block`, decide the sentence:

```python
        unavailable: str | None = None
        if degrading_failure is not None:
            unavailable = _unavailable_sentence(degrading_failure.provider, degrading_failure.kind, degrading_failure.reason)
        else:
            live = await open_incidents(conn, providers=["openrouter"])
            if live:
                unavailable = _unavailable_sentence(live[0].provider, live[0].kind, live[0].reason)
        if unavailable is not None:
            for section in display_block["sections"]:
                if section["empty"] and section["key"] not in blocks:
                    section["empty_message"] = unavailable
```

with

```python
def _unavailable_sentence(provider: str, kind: str, reason: str) -> str:
    verb = "refused" if kind == "refusal" else "failing"
    return f"Not generated: {provider_display(provider).lower()} {verb} ({reason_words(reason)}). Retries automatically."
```

(`blocks` is the `live_blocks` mapping the function already reads. `ResearchSection.empty_message` is already an optional wire field, and the frontend already renders `section.emptyMessage` in its empty state — no frontend change for this surface.)

Run: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_frontend_read_display_pages_db.py tests/api/test_frontend_read_account_detail.py -p no:cacheprovider -q` — pass.

- [ ] **Step 7: Frontend — failing tests first**

Append to `apps/frontend/src/features/projects/model/research-progress-line.test.ts`:

```ts
test("an attention reason is shown as the server's sentence, verbatim", () => {
  const card = ResearchProgressSchema.parse({
    requested_accounts: 10, queued: 0, running: 0, finished: 10, progress_pct: 100,
    pill: "needs_attention", last_finished_at: null, agents: [],
    attention: [{ account_name: "Borland Groover", reason: "Model provider refused: key limit exceeded. Since 16:01. Clue has been notified." }],
    incident: { provider_label: "Model provider", reason_label: "key limit exceeded", since: "2026-09-16T10:31:23Z", affected: 45, notified: true },
  });
  assert.equal(researchProgressLine(card, 0), "Borland Groover: Model provider refused: key limit exceeded. Since 16:01. Clue has been notified.");
});

test("a card without an incident still parses", () => {
  const card = ResearchProgressSchema.parse({ requested_accounts: 1, queued: 0, running: 1, finished: 0, progress_pct: 0, pill: "running", last_finished_at: null, agents: [], attention: [] });
  assert.equal(card.incident, null);
});
```

Create or append `apps/frontend/src/features/projects/model/design-leg.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { designTurnFailureNotice } from "./design-leg";

test("a provider refusal on a turn reads as a sentence, not a code", () => {
  assert.equal(
    designTurnFailureNotice("provider_refused:openrouter:key_limit"),
    "Model provider refused: key limit exceeded. Send another message once it is restored — Clue has been notified.",
  );
  assert.equal(
    designTurnFailureNotice("provider_failed:openrouter:server_error"),
    "Model provider failing: server errors. Send another message to try again — Clue has been notified.",
  );
  assert.equal(designTurnFailureNotice("provider_refused:exa:credits_exhausted"), "Discovery provider refused: credits exhausted. Send another message once it is restored — Clue has been notified.");
  assert.equal(designTurnFailureNotice("permission_denied_error"), "permission_denied_error");
});
```

Run: `cd apps/frontend && npx tsx --test src/features/projects/model/research-progress-line.test.ts src/features/projects/model/design-leg.test.ts` — FAIL (schema rejects `incident`; notice returns the raw code).

- [ ] **Step 8: Frontend — implement**

`research-progress.ts`: add to `ResearchProgressSchema`

```ts
  incident: z.object({
    provider_label: z.string(), reason_label: z.string(), since: z.string(), affected: z.number().int().nonnegative(), notified: z.boolean(),
  }).nullable().catch(null),
```

(`.catch(null)` so an older backend without the field still parses; `.nullable()` because the backend sends `null`.) `research-progress-line.ts` needs no change: it already prints `${account_name}: ${reason}`.

`design-leg.ts`, above `designTurnFailureNotice`:

```ts
// Mirrors clue_api.provider_incidents.provider_display / reason_words. A code the tables do not
// know still renders as itself (true, if terse), like every other unknown code here.
const PROVIDER_DISPLAY: Readonly<Record<string, string>> = {
  openrouter: "Model provider", exa: "Discovery provider", exa_websets: "Discovery provider", live_http: "Website fetch",
};
const REASON_WORDS: Readonly<Record<string, string>> = {
  credits_exhausted: "credits exhausted", key_limit: "key limit exceeded", auth_invalid: "API key rejected",
  account_suspended: "account suspended", rate_limited: "rate limited", server_error: "server errors", timeout: "timeouts",
};

function providerFailureNotice(code: string): string | null {
  const match = /^provider_(refused|failed):([a-z0-9_.-]+):([a-z_]+)$/.exec(code);
  if (!match) return null;
  const [, head, provider, reason] = match;
  const who = PROVIDER_DISPLAY[provider] ?? provider;
  const what = REASON_WORDS[reason] ?? reason.replace(/_/g, " ");
  return head === "refused"
    ? `${who} refused: ${what}. Send another message once it is restored — Clue has been notified.`
    : `${who} failing: ${what}. Send another message to try again — Clue has been notified.`;
}
```

and as the first line of `designTurnFailureNotice`'s body after the null check: `const provider = providerFailureNotice(code); if (provider) return provider;`.

- [ ] **Step 9: Run frontend tests, lint, and the two suites**

Run: `cd apps/frontend && npx tsx --test src/features/projects/model/research-progress-line.test.ts src/features/projects/model/design-leg.test.ts src/features/projects/model/research-progress-contract.test.ts && npx eslint src/features/projects/model/research-progress.ts src/features/projects/model/design-leg.ts src/features/projects/model/design-leg.test.ts src/features/projects/model/research-progress-line.test.ts && npm test 2>&1 | grep -E "ℹ (tests|pass|fail)"`
Expected: pass; `ℹ fail 0`.

- [ ] **Step 10: Commit**

```bash
git add platform/api/clue_api/arv2/research_progress.py platform/api/clue_api/frontend_read/research_progress.py platform/api/clue_api/frontend_read/display_pages.py tests/arv2/test_research_progress.py tests/api/test_frontend_read_research_progress.py tests/api/test_frontend_read_display_pages_db.py apps/frontend/src/features/projects/model/research-progress.ts apps/frontend/src/features/projects/model/design-leg.ts apps/frontend/src/features/projects/model/design-leg.test.ts apps/frontend/src/features/projects/model/research-progress-line.test.ts
git commit -m "feat(incidents): the research card, the empty overview section and the failed chat turn say why a provider failed, in one sentence"
```

---

### Task 7: Live proof, the frontend contract note, and the memory note

**Files:**
- Modify: `apps/frontend/docs/api-contracts/projects.md` (research progress: the `incident` field; the failed-turn codes `provider_refused:*` / `provider_failed:*`), `apps/frontend/docs/api-contracts/accounts.md` (overview sections: `emptyMessage` may carry the not-generated sentence)
- Create: `_memory/2026-09-16-provider-incidents.md`
- Modify: `_memory/README.md` (one row)

- [ ] **Step 1: Restart the lane stack on the new code** (this is also the moment Sentry goes live, since the running processes booted with the flag off)

```bash
./scripts/dev_stack_san_salvador.sh down > /tmp/san-salvador_down.txt 2>&1
./scripts/dev_stack_san_salvador.sh up > /tmp/san-salvador_up.txt 2>&1; sleep 30
./scripts/dev_stack_san_salvador.sh status > /tmp/san-salvador_status.txt 2>&1; cat /tmp/san-salvador_status.txt
pgrep -f "next dev.*3020" >/dev/null || { rm -rf apps/frontend/.next; ( cd apps/frontend && npm run dev -- --port 3020 > /tmp/san-salvador_frontend.log 2>&1 & ); sleep 30; }
grep -h "sentry" /tmp/san-salvador_platform_api_8020.log /tmp/san-salvador_fleet_worker.log | head -3   # expect sentry.installed, not sentry.not_installed
```

- [ ] **Step 2: Force one refusal with a call that spends nothing** — the lane's Exa Search key is out of credits, so a single search is a real 402. From a Python one-liner using the ARV2 caller against the live Exa endpoint with a `BufferedLedger`, then drain into the lane DB with a `LedgerStamp(workspace_id="ws_2875e9e3dc5c452885db3774076de8c4")`:

```bash
set -a; source .env; set +a
uv run python - <<'EOF'
import asyncio, json
from datetime import UTC, datetime
from clue_api.arv2.calls import CallSpec, ProviderCaller
from clue_api.arv2.exa_client import exa_halt_rule
from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink, LedgerStamp, drain_provider_calls
from clue_api.arv2.transport import HttpxTransport, json_request
from clue_api.provider_incidents import open_incidents
from clue_db import create_engine
import os
raw, ledger = BufferedRawSink(), BufferedLedger()
caller = ProviderCaller(transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC))
req = json_request("POST", "https://api.exa.ai/search", headers={"x-api-key": os.environ["CLUE_EXA_API_KEY"]}, json_body={"query": "gastroenterology practice", "numResults": 1}, timeout_s=30)
try:
    caller.call(CallSpec(provider="exa", operation="search", label="incident-probe", request=req, halt_rule=exa_halt_rule, max_attempts=1))
except Exception as exc:
    print("call raised (expected):", type(exc).__name__)
async def main():
    engine = create_engine(os.environ["CLUE_DATABASE_URL"])
    async with engine.begin() as conn:
        class _A:
            async def persist_body(self, *, workspace_id, data, media_type):
                from clue_agents.contracts import ArtifactRef
                import hashlib
                d = hashlib.sha256(data).hexdigest()
                return ArtifactRef(workspace_id=workspace_id, artifact_key=f"probe/{d}", sha256=d, media_type=media_type, byte_count=len(data))
        await drain_provider_calls(conn, raw=raw, ledger=ledger, artifacts=_A(), stamp=LedgerStamp(workspace_id="ws_2875e9e3dc5c452885db3774076de8c4"))
        print([ (i.provider, i.reason, i.notified) for i in await open_incidents(conn) ])
asyncio.run(main())
EOF
```

Expected: `call raised (expected): ProviderHalted`, then `[('exa', 'credits_exhausted', True)]`. (If the transport or request helper names differ, read `clue_api/arv2/transport.py` — the plan names the shapes the caller tests use; the sole point of this step is one real 402 through the real caller and drain.) Then open Sentry: one event, "Discovery provider refused: credits exhausted", tags `provider=exa`, `reason=credits_exhausted`.

- [ ] **Step 3: Close it** — once the founder tops up Exa Search credits, run the same probe again; expected `[]` and a second Sentry event "Discovery provider recovered after … — 1 calls failed (1 search)". If credits are not topped up during the walk, record the close as owed in the memory note; do not fake a success row.

- [ ] **Step 4: Check the three surfaces in the browser** (the founder's walk): on a project whose research jobs failed with the OpenRouter key limit yesterday, the research card's attention line reads the sentence; opening Capital Digestive Care while an `openrouter` incident is open shows "Not generated: model provider refused (key limit exceeded). Retries automatically." under each empty overview section; a chat turn refused by the model shows the sentence instead of `permission_denied_error`. Historical rows written before this plan still carry `model_error` / `permission_denied_error` and render as before — expected, recorded.

- [ ] **Step 5: Docs and memory**

In `apps/frontend/docs/api-contracts/projects.md`, under the research-progress contract, add: `incident: { provider_label, reason_label, since, affected, notified } | null` — the open provider incident behind a `needs_attention` card, else `null`; attention `reason` may be a full sentence ending "Clue has been notified." Under the failed-turn codes: `provider_refused:<provider>:<reason>` and `provider_failed:<provider>:<reason>` render as sentences via `designTurnFailureNotice`. In `accounts.md`, under overview sections: `emptyMessage` may read `"Not generated: <provider> refused (<reason>). Retries automatically."` while a provider incident is open.

Write `_memory/2026-09-16-provider-incidents.md`: what landed (commits), the rulings (B, inline only, Sentry only, per incident, 429 counts), the spec amendment (writers are the drain and the turn handler; gateway untouched), the live proof result (the Exa 402 incident id and Sentry event), what is owed (the close event if credits were not topped up; the pre-existing `test_import_guard` failure is unrelated), and the operator notes: the threshold constants, that historical rows keep their old codes, that `provider_incident` rows are never deleted. Add one row to `_memory/README.md`.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/docs/api-contracts/projects.md apps/frontend/docs/api-contracts/accounts.md _memory/2026-09-16-provider-incidents.md _memory/README.md
git commit -m "docs(incidents): contract notes for the incident field and provider failure codes; memory note with the live Exa 402 proof"
```

---

## Self-review

**Spec coverage.** §3.2 classifier → Task 1. §3.3 table, open/close rules, threshold, Sentry events, never-raise → Task 2. §3.4 writers → Tasks 3 (caller stamp + drain), 4 (research rounds), 5 (chat turn); the spec's gateway hook is replaced as recorded in the header amendment. §3.5 reasons on rows → Tasks 4 (jobs) and 5 (turns). §3.6 three readers → Task 6 (research card, overview sections via `empty_message`, failed turn). §3.7 no new flags → none added. §4 tests → each task; live → Task 7. §5 answers → Task 7 restarts the stack (Sentry live) and 429 counts (Task 1 `rate_limited` is a `failure`; Task 2 counts it).

**Placeholder scan.** Two test steps (Task 4 Step 4, Task 5 Step 1's third test, Task 6 Step 5) reference helper names in existing test files by description; each names the file and the fallback if the helper differs. No TBDs.

**Type consistency.** `ProviderFailure(provider, kind, reason, message)` positional order is used identically in Tasks 1–6. `record_failure(conn, failure, *, surface, workspace_id, now)` and `record_success(conn, provider, *, now)` match between Task 2's definitions and Tasks 3, 5, 6, 7. `failure_code` / `parse_failure_code` names match across Tasks 1, 4, 5, 6. `incident_sentence(provider=, kind=, reason=, since=, affected=, unit=, notified=)` matches Tasks 2 and 6.
