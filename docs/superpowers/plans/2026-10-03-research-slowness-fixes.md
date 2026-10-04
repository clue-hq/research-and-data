# Research Slowness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the waiting that makes production research jobs take 50–70 minutes (about 10 of which is model work), and fix the finalize-ordering bug that ended McKee's job in `needs_review`, without changing what research produces or weakening any storage, erasure or retry guarantee.

**Architecture:** Nine independent changes, each with its own tests: a timer that logs slow lock-holding sections; one shared S3 client per process; research artifact saves that upload before taking a *shared* project lock and write derivation edges in one statement; evidence saving split into prepare (no lock) and publish (lock once); dossier import through a storage wrapper that prefetches reads and sends uploads concurrently; a fleet worker that only claims what it can start; finalize checks that run before outputs are frozen; explicit database pool settings and pgbouncer visibility.

**Tech Stack:** Python 3.12, SQLAlchemy async + asyncpg, PostgreSQL (via pgbouncer in transaction mode in production), aioboto3 15.5 / aiobotocore 2.25 (Cloudflare R2), structlog via `clue_obs`, pytest (sync test bodies driving coroutines with `run_async`).

**Spec:** `docs/superpowers/specs/2026-10-03-research-slowness-fixes-design.md` (read it first; the evidence behind every change is in `_memory/2026-10-03-production-research-slowness.md`).

## Global Constraints

- One PR on branch `perf/research-slowness-fixes`, worktree `/Users/aryankeshri/conductor/workspaces/research-and-data/dushanbe`. Commit locally after each task. **Never push.** No AI/Claude attribution in commit messages (project rule).
- No database migration.
- Storage rule, unchanged: **record the artifact row before the blob upload** (`record_artifact` docstring, `libs/clue-storage/clue_storage/artifacts.py`).
- Every new runtime setting appears in `.env.example` with its default, in the same commit that introduces it (project parity rule). New settings: `CLUE_DB_CRITICAL_SECTION_LOG_MS=500`, `CLUE_STORAGE_S3_MAX_POOL_CONNECTIONS=50`, `CLUE_DB_POOL_SIZE=5`, `CLUE_DB_MAX_OVERFLOW=10`, `CLUE_DB_POOL_TIMEOUT_S=30`.
- Tests: never run broad suites with real API keys; run focused files. DB tests run only against a throwaway database (`CLUE_DATABASE_URL` pointing at a database you created for this lane), never a shared lane DB. Test command prefix used below: `uv run pytest -q`.
- Before each commit: `uv run ruff check <changed files>` and `uv run ruff format --check <changed files>`; at the end `uv run mypy` over changed packages (Task 10).
- The `.env` in this worktree is a copy of addis-ababa's and points at `clue_addis-ababa`: for DB tests, export `CLUE_DATABASE_URL` to a throwaway DB, e.g. `postgresql+asyncpg://<user>:<pw>@localhost:55040/clue_dushanbe_test` (create it once with `createdb`; migrations run automatically via the `migrated_db` fixture).

## Review Focus

1. **A dossier save that runs on a borrowed connection** (`ResearchArtifacts` inside `quality_json_dossier.py`'s transaction): the project lock is shared and taken last, so it must not block a concurrent save — pinned by Task 3's two-writers test and Task 4's lock-after-upload test.
2. **The same evidence source saved by two concurrent transactions:** exactly one `arv2_evidence_source` row, both callers get the same `source_id` — pinned in Task 5.
3. **`recover_acquisitions` with more than 100 pending receipts:** paging must not loop forever now that publication is deferred — pinned in Task 5 by a 101-receipt test with the batch size patched to 2.
4. **An artifact erased between the import's prefetch and its use:** still refused, because the row checks run inside the transaction — pinned in Task 6.
5. **A handler that raises, or a claim that returns nothing:** the worker's per-kind in-flight count must be released, or the kind starves forever — pinned in Task 7.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `libs/clue-obs/clue_obs/critical_section.py` | create | Time a lock-holding section; log `db.critical_section` when slow |
| `libs/clue-obs/clue_obs/__init__.py` | modify | Export `critical_section` |
| `libs/clue-storage/clue_storage/s3.py` | rewrite | One shared aioboto3 client per (event loop, configuration); one rebuild on connection errors; `close_shared_s3_clients()` |
| `libs/clue-storage/clue_storage/factory.py`, `__init__.py` | modify | Pass the pool size; export the close function |
| `libs/clue-config/clue_config/settings.py` | modify | `storage_s3_max_pool_connections` |
| `platform/api/clue_api/fleet_main.py`, `projections_app.py`, `platform/page_origin/clue_page_origin/main.py` | modify | Close shared S3 clients at shutdown |
| `platform/api/clue_api/agent_turn_wiring.py` | modify | `DurableAgentArtifactStore`: `_record_body` + `_bind_projects` helpers; shared project lock for writers |
| `platform/api/clue_api/quality_research_artifacts.py` | modify | Upload before the project lock; one-statement derivation insert |
| `platform/api/clue_api/arv2/quality_evidence.py` | modify | `prepare_source` / `publish_sources`; `persist_source` = both |
| `platform/api/clue_api/arv2/quality_acquisition.py` | modify | Prepare all sources, publish once |
| `platform/api/clue_api/arv2/import_storage.py` | create | `ImportStorage`: prefetched reads, deferred concurrent uploads |
| `platform/api/clue_api/arv2/dossier_import.py` | modify | Run the import through `ImportStorage` |
| `platform/fleet/clue_fleet/work_worker.py`, `__init__.py` | modify | `InFlightLimited` protocol; skip kinds at their limit |
| `platform/api/clue_api/arv2/account_research_driver.py` | modify | `max_in_flight` on the ARV2 handler |
| `platform/agents/clue_agents/ports.py` | modify | `check_finalizable` on `AgentExecutionAdapter` |
| `platform/api/clue_api/agent_execution_wiring.py` | modify | `C5AgentExecutionAdapter.check_finalizable` |
| `platform/api/clue_api/agent_runtime_wiring.py` | modify | `finalize_turn` calls it first |
| `libs/clue-db/clue_db/engine.py` | modify | Pool size / overflow / timeout from env |
| `.env.example`, `docs/deploy/runbook.md` | modify | Settings, concurrency explanation, pgbouncer stats and pool raise |

---

### Task 1: Log slow lock-holding sections

**Files:**
- Create: `libs/clue-obs/clue_obs/critical_section.py`
- Modify: `libs/clue-obs/clue_obs/__init__.py` (import + `__all__`, line ~57)
- Modify: `.env.example`
- Test: `tests/clue_obs/test_critical_section.py`

**Interfaces:**
- Produces: `clue_obs.critical_section(name: str, **fields: object) -> ContextManager[None]` (a sync context manager usable around `await`s); event name `db.critical_section` with fields `name`, `held_ms`, plus `**fields`.

- [ ] **Step 1: Write the failing test**

```python
"""clue_obs.critical_section: a slow lock-holding section names itself in the log."""

from __future__ import annotations

import pytest

import clue_obs.critical_section as critical_section_module
from clue_obs import critical_section
from clue_obs.testing import capture_events


def _clock(monkeypatch: pytest.MonkeyPatch, *readings: float) -> None:
    values = iter(readings)
    monkeypatch.setattr(critical_section_module.time, "monotonic", lambda: next(values))


def test_a_section_over_the_threshold_logs_its_name_duration_and_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "100")
    _clock(monkeypatch, 10.0, 10.25)
    with capture_events(mode="info") as cap:
        with critical_section("artifact.persist", job_id="j1"):
            pass
    event = cap.first("db.critical_section")
    assert event is not None
    assert event["name"] == "artifact.persist"
    assert event["held_ms"] == 250.0
    assert event["job_id"] == "j1"


def test_a_fast_section_stays_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "100")
    _clock(monkeypatch, 10.0, 10.05)
    with capture_events(mode="info") as cap:
        with critical_section("artifact.persist"):
            pass
    assert not cap.has("db.critical_section")


def test_default_threshold_is_500_ms_and_a_bad_value_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "not-a-number")
    _clock(monkeypatch, 0.0, 0.499)
    with capture_events(mode="info") as cap:
        with critical_section("x"):
            pass
    assert not cap.has("db.critical_section")


def test_the_section_is_logged_even_when_its_body_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "0")
    _clock(monkeypatch, 0.0, 1.0)
    with capture_events(mode="info") as cap:
        with pytest.raises(RuntimeError):
            with critical_section("x"):
                raise RuntimeError("boom")
    assert cap.has("db.critical_section")
```

(`critical_section_module` is the module, imported by its dotted path; `critical_section` is the function `clue_obs/__init__.py` exports. Because the package attribute `clue_obs.critical_section` becomes the function, always import the module by its full dotted path as above.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/clue_obs/test_critical_section.py`
Expected: FAIL — `ImportError: cannot import name 'critical_section' from 'clue_obs'`.

- [ ] **Step 3: Write the implementation**

`libs/clue-obs/clue_obs/critical_section.py`:

```python
"""Time a lock-holding database section and log it when it runs long.

Research slowness fix (2026-10-03, spec ``docs/superpowers/specs/
2026-10-03-research-slowness-fixes-design.md`` part 0): the production diagnosis could see that
transactions held shared locks for seconds but not *which code* held them. ``critical_section``
wraps such a section, always measures it, and logs one ``db.critical_section`` event when it took
at least ``CLUE_DB_CRITICAL_SECTION_LOG_MS`` milliseconds (default 500) — quiet in normal
operation, self-naming when slow.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

from clue_obs.config import get_logger

__all__ = ["CRITICAL_SECTION_LOG_MS_ENV", "critical_section"]

CRITICAL_SECTION_LOG_MS_ENV = "CLUE_DB_CRITICAL_SECTION_LOG_MS"
_DEFAULT_THRESHOLD_MS = 500.0

log = get_logger("clue_obs.critical_section")


def _threshold_ms() -> float:
    raw = os.environ.get(CRITICAL_SECTION_LOG_MS_ENV, "").strip()
    if not raw:
        return _DEFAULT_THRESHOLD_MS
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD_MS


@contextmanager
def critical_section(name: str, **fields: object) -> Iterator[None]:
    """Measure the wrapped block; log ``db.critical_section`` if it was slow (even if it raised)."""
    started = time.monotonic()
    try:
        yield
    finally:
        held_ms = (time.monotonic() - started) * 1000
        if held_ms >= _threshold_ms():
            log.info("db.critical_section", name=name, held_ms=round(held_ms, 1), **fields)
```

In `libs/clue-obs/clue_obs/__init__.py`, add next to the other imports:

```python
from clue_obs.critical_section import critical_section
```

and add `"critical_section",` to `__all__` (keep the list's existing order style).

In `.env.example`, add near the other `CLUE_DB_*` / observability lines:

```
# Log a lock-holding database section (artifact saves, evidence publish, dossier import) as
# db.critical_section when it holds its lock at least this many milliseconds.
CLUE_DB_CRITICAL_SECTION_LOG_MS=500
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/clue_obs/test_critical_section.py`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check libs/clue-obs/clue_obs/critical_section.py libs/clue-obs/clue_obs/__init__.py tests/clue_obs/test_critical_section.py
uv run ruff format libs/clue-obs/clue_obs/critical_section.py tests/clue_obs/test_critical_section.py
git add libs/clue-obs/clue_obs/critical_section.py libs/clue-obs/clue_obs/__init__.py tests/clue_obs/test_critical_section.py .env.example
git commit -m "A slow lock-holding database section names itself in the log

critical_section measures a block and logs db.critical_section when it held its lock longer than
CLUE_DB_CRITICAL_SECTION_LOG_MS (default 500 ms), so the post-deploy check can see which code
holds shared locks and for how long."
```

---

### Task 2: One shared S3 client per process

**Files:**
- Rewrite: `libs/clue-storage/clue_storage/s3.py`
- Modify: `libs/clue-storage/clue_storage/factory.py` (the `S3Storage(...)` call)
- Modify: `libs/clue-storage/clue_storage/__init__.py` (export `close_shared_s3_clients`)
- Modify: `libs/clue-config/clue_config/settings.py:322-324` (add the pool field after `storage_s3_region`)
- Modify: `.env.example:35-39` (S3 block)
- Modify: `platform/api/clue_api/fleet_main.py` (the `finally:` at ~1433), `platform/api/clue_api/projections_app.py` (lifespan `finally:` at ~826), `platform/page_origin/clue_page_origin/main.py` (lifespan at ~41)
- Test: `tests/storage/test_s3_shared_client.py`

**Interfaces:**
- Produces: `S3Storage(bucket, *, endpoint_url=None, region=None, access_key_id=None, secret_access_key=None, max_pool_connections: int = 50)`; `async def close_shared_s3_clients() -> None` (closes the current event loop's shared clients); `S3Storage._new_client_context(self) -> Any` (the test seam).

- [ ] **Step 1: Write the failing tests**

`tests/storage/test_s3_shared_client.py`:

```python
"""S3Storage reuses one client per (event loop, configuration) — no SDK, no MinIO needed."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from clue_storage import ArtifactNotFound, StorageError, close_shared_s3_clients
from clue_storage.s3 import S3Storage


class ConnectionClosedError(Exception):
    """Named like botocore's, which is how S3Storage recognises a connection-level failure."""


class _AccessDenied(Exception):
    def __init__(self) -> None:
        super().__init__("denied")
        self.response = {"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}}


class _Missing(Exception):
    def __init__(self) -> None:
        super().__init__("missing")
        self.response = {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self) -> _Body:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._data


class _Client:
    def __init__(self, store: dict[str, bytes], failures: list[BaseException]) -> None:
        self._store = store
        self._failures = failures

    def _maybe_fail(self) -> None:
        if self._failures:
            raise self._failures.pop(0)

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self._maybe_fail()
        self._store[Key] = Body

    async def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self._maybe_fail()
        if Key not in self._store:
            raise _Missing()
        return {"Body": _Body(self._store[Key])}


class _Context:
    def __init__(self, client: _Client) -> None:
        self.client = client
        self.closed = False

    async def __aenter__(self) -> _Client:
        return self.client

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True


@pytest.fixture
def contexts(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"made": [], "store": {}, "failures": []}

    def factory(self: S3Storage) -> _Context:
        context = _Context(_Client(state["store"], state["failures"]))
        state["made"].append(context)
        return context

    monkeypatch.setattr(S3Storage, "_new_client_context", factory)
    return state


def _storage() -> S3Storage:
    return S3Storage("bucket", endpoint_url="https://r2.example", access_key_id="k", secret_access_key="s")


def test_many_calls_and_instances_share_one_client(contexts: dict[str, Any]) -> None:
    async def scenario() -> None:
        first, second = _storage(), _storage()
        await first.put("a", b"1", media_type="text/plain")
        await second.put("b", b"2", media_type="text/plain")
        assert await first.get("b") == b"2"
        assert await second.get("a") == b"1"
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert len(contexts["made"]) == 1
    assert contexts["made"][0].closed


def test_a_different_configuration_gets_its_own_client(contexts: dict[str, Any]) -> None:
    async def scenario() -> None:
        await _storage().put("a", b"1", media_type="text/plain")
        other = S3Storage("bucket", endpoint_url="https://other.example", access_key_id="k", secret_access_key="s")
        await other.put("b", b"2", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert len(contexts["made"]) == 2


def test_each_event_loop_gets_its_own_client(contexts: dict[str, Any]) -> None:
    async def one_call() -> None:
        await _storage().put("a", b"1", media_type="text/plain")

    asyncio.run(one_call())
    asyncio.run(one_call())
    assert len(contexts["made"]) == 2


def test_a_connection_error_rebuilds_the_client_once_and_retries(contexts: dict[str, Any]) -> None:
    contexts["failures"].append(ConnectionClosedError("reset by peer"))

    async def scenario() -> None:
        await _storage().put("a", b"1", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert contexts["store"] == {"a": b"1"}
    assert len(contexts["made"]) == 2
    assert contexts["made"][0].closed


def test_a_second_connection_error_surfaces_as_storage_error(contexts: dict[str, Any]) -> None:
    contexts["failures"].extend([ConnectionClosedError("1"), ConnectionClosedError("2")])

    async def scenario() -> None:
        with pytest.raises(StorageError):
            await _storage().put("a", b"1", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())


def test_an_access_error_is_not_retried(contexts: dict[str, Any]) -> None:
    contexts["failures"].append(_AccessDenied())

    async def scenario() -> None:
        with pytest.raises(StorageError):
            await _storage().put("a", b"1", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert len(contexts["made"]) == 1


def test_a_missing_key_is_still_a_typed_not_found(contexts: dict[str, Any]) -> None:
    async def scenario() -> None:
        with pytest.raises(ArtifactNotFound):
            await _storage().get("nope")
        await close_shared_s3_clients()

    asyncio.run(scenario())
```

Add to `tests/storage/test_factory.py` (keep its existing style; it builds `Settings(_env_file=None, ...)`):

```python
def test_s3_pool_size_comes_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        storage_backend="s3",
        storage_s3_bucket="b",
        storage_s3_max_pool_connections=7,
    )
    backend = storage_from_settings(settings, Secrets(_env_file=None))
    assert backend._max_pool_connections == 7  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/storage/test_s3_shared_client.py tests/storage/test_factory.py`
Expected: FAIL — `ImportError: cannot import name 'close_shared_s3_clients'` (and the factory test errors on the unknown setting).

- [ ] **Step 3: Write the implementation**

Replace `libs/clue-storage/clue_storage/s3.py` with:

```python
"""S3-compatible :class:`~clue_storage.protocol.StorageBackend` (B2.1).

One implementation covers AWS S3, Cloudflare R2, and MinIO — the *endpoint URL* is config
(REQ-07: "endpoint config covers R2/S3/MinIO"), so swapping object stores is a settings change,
never code. The ``aioboto3`` SDK is imported **lazily, only in this module** (the Rule-4
provider-SDK discipline) and is guarded by a dedicated import-linter contract.

**One shared client per event loop and configuration** (research slowness fix, 2026-10-03). The
original design opened a fresh client per operation on the theory that snapshot traffic was low;
in production research saves hundreds of blobs per job, and every call paid client construction
plus a new TLS handshake to R2 (~200 ms measured from the worker VM, against 3 ms for the
database). Now every ``S3Storage`` with the same configuration, on the same event loop, reuses one
long-lived client and its keep-alive connection pool (``max_pool_connections``). Clients are kept
per event loop because an aiohttp session must not cross loops (tests run many loops); a loop's
entry disappears with the loop. ``close_shared_s3_clients()`` closes the current loop's clients at
process shutdown. A connection-level failure discards the client and retries the operation once
on a fresh one; anything else surfaces as before.
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from clue_storage.protocol import ArtifactNotFound, StorageError

__all__ = ["DEFAULT_MAX_POOL_CONNECTIONS", "S3Storage", "close_shared_s3_clients"]

DEFAULT_MAX_POOL_CONNECTIONS = 50

_T = TypeVar("_T")

# botocore / aiohttp exception class names that mean "the connection broke", matched by name so
# this module never imports those packages at module level.
_CONNECTION_ERROR_NAMES = frozenset(
    {
        "EndpointConnectionError",
        "ConnectionClosedError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "HTTPClientError",
        "ClientConnectorError",
        "ClientOSError",
        "ServerDisconnectedError",
        "ConnectionResetError",
        "BrokenPipeError",
    }
)


@dataclass
class _LoopClients:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # configuration key -> (client context manager, entered client)
    clients: dict[tuple[object, ...], tuple[Any, Any]] = field(default_factory=dict)


_BY_LOOP: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopClients] = (
    weakref.WeakKeyDictionary()
)


def _loop_clients() -> _LoopClients:
    loop = asyncio.get_running_loop()
    held = _BY_LOOP.get(loop)
    if held is None:
        held = _LoopClients()
        _BY_LOOP[loop] = held
    return held


async def close_shared_s3_clients() -> None:
    """Close the current event loop's shared S3 clients (call once, at process shutdown)."""
    held = _BY_LOOP.pop(asyncio.get_running_loop(), None)
    if held is None:
        return
    for context, _client in held.clients.values():
        with contextlib.suppress(Exception):
            await context.__aexit__(None, None, None)


def _is_connection_error(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    for _ in range(5):  # the exception, then a few causes/contexts
        if seen is None:
            return False
        if type(seen).__name__ in _CONNECTION_ERROR_NAMES:
            return True
        seen = seen.__cause__ or seen.__context__
    return False


class S3Storage:
    """Store blobs in an S3-compatible bucket (AWS S3 / R2 / MinIO — endpoint is config)."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        max_pool_connections: int = DEFAULT_MAX_POOL_CONNECTIONS,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._max_pool_connections = max_pool_connections

    def _config_key(self) -> tuple[object, ...]:
        return (
            self._endpoint_url,
            self._region,
            self._access_key_id,
            self._secret_access_key,
            self._max_pool_connections,
        )

    def _new_client_context(self) -> Any:
        """A fresh ``aioboto3`` client context manager (lazy import — the one sanctioned home of
        the SDK; a missing install fails loud with the fix). The test seam."""
        try:
            import aioboto3
            from aiobotocore.config import AioConfig
        except ImportError as exc:  # pragma: no cover - CI installs the s3 extra
            raise StorageError(
                "aioboto3 is required for the S3 storage backend; install clue-storage[s3]"
            ) from exc
        return aioboto3.Session().client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            config=AioConfig(max_pool_connections=self._max_pool_connections),
        )

    async def _client(self) -> Any:
        held = _loop_clients()
        key = self._config_key()
        cached = held.clients.get(key)
        if cached is None:
            async with held.lock:
                cached = held.clients.get(key)
                if cached is None:
                    context = self._new_client_context()
                    cached = (context, await context.__aenter__())
                    held.clients[key] = cached
        return cached[1]

    async def _discard(self, client: Any) -> None:
        held = _loop_clients()
        key = self._config_key()
        cached = held.clients.get(key)
        if cached is not None and cached[1] is client:
            del held.clients[key]
            with contextlib.suppress(Exception):
                await cached[0].__aexit__(None, None, None)

    async def _call(self, operation: Callable[[Any], Awaitable[_T]]) -> _T:
        client = await self._client()
        try:
            return await operation(client)
        except Exception as exc:
            if not _is_connection_error(exc):
                raise
            await self._discard(client)
        return await operation(await self._client())

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        try:
            await self._call(
                lambda s3: s3.put_object(
                    Bucket=self._bucket, Key=key, Body=data, ContentType=media_type
                )
            )
        except Exception as exc:
            raise StorageError(f"could not store {key!r}: {exc}") from exc

    async def get(self, key: str) -> bytes:
        async def read(s3: Any) -> bytes:
            response = await s3.get_object(Bucket=self._bucket, Key=key)
            async with response["Body"] as body:
                data: bytes = await body.read()
                return data

        try:
            return await self._call(read)
        except Exception as exc:
            if _is_missing_key(exc):
                raise ArtifactNotFound(f"no artifact stored under {key!r}") from exc
            raise StorageError(f"could not read {key!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            # S3 DeleteObject is idempotent (204 for a missing key) — matches the protocol's
            # safe-to-retry DSAR-erasure semantics with no extra existence check.
            await self._call(lambda s3: s3.delete_object(Bucket=self._bucket, Key=key))
        except Exception as exc:
            raise StorageError(f"could not delete {key!r}: {exc}") from exc

    async def exists(self, key: str) -> bool:
        try:
            await self._call(lambda s3: s3.head_object(Bucket=self._bucket, Key=key))
        except Exception as exc:
            if _is_missing_key(exc):
                return False
            raise StorageError(f"could not stat {key!r}: {exc}") from exc
        return True

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        s3 = await self._client()
        try:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket):
                for obj in page.get("Contents", ()):
                    modified: datetime = obj["LastModified"]
                    yield str(obj["Key"]), modified
        except Exception as exc:
            raise StorageError(f"could not list bucket {self._bucket!r}: {exc}") from exc

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        try:
            await self._call(lambda s3: s3.head_object(Bucket=self._bucket, Key=key))
        except Exception as exc:
            if _is_missing_key(exc):
                raise ArtifactNotFound(f"no artifact stored under {key!r}") from exc
            raise StorageError(f"could not stat {key!r}: {exc}") from exc
        s3 = await self._client()
        url: str = await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url


def _is_missing_key(exc: Exception) -> bool:
    """Whether a botocore ClientError means "key/object absent" (404 / NoSuchKey), duck-typed so
    this module never imports botocore's exception types at module level."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error", {})
    code = str(error.get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404
```

Note on `get`: `_is_missing_key` looks at the exception passed to `except`, which is the client's own error when the failure was not a connection error (it is re-raised unchanged by `_call`). Keep that order.

`libs/clue-config/clue_config/settings.py`, after `storage_s3_region: str | None = None`:

```python
    # Keep-alive connections the shared S3 client may hold (research slowness fix 2026-10-03).
    # Env: ``CLUE_STORAGE_S3_MAX_POOL_CONNECTIONS``.
    storage_s3_max_pool_connections: int = Field(default=50, ge=1)
```

`libs/clue-storage/clue_storage/factory.py` — add `max_pool_connections=settings.storage_s3_max_pool_connections,` to the `S3Storage(...)` call.

`libs/clue-storage/clue_storage/__init__.py` — import `close_shared_s3_clients` from `clue_storage.s3` and add it to `__all__`. Check first whether `__init__.py` imports `s3` at module level; if it deliberately does not (the lazy-SDK rule), import it as `from clue_storage.s3 import close_shared_s3_clients` — `s3.py` imports no SDK at module level, so this stays within the rule.

`.env.example`, after `CLUE_STORAGE_S3_SECRET_ACCESS_KEY=`:

```
# Keep-alive connections the process-wide shared S3/R2 client may hold.
CLUE_STORAGE_S3_MAX_POOL_CONNECTIONS=50
```

Shutdown: in `platform/api/clue_api/fleet_main.py`, at the end of the `finally:` block that cancels the background tasks (~line 1433-1450), add:

```python
            from clue_storage import close_shared_s3_clients

            await close_shared_s3_clients()
```

Do the same at the end of the lifespan `finally:` in `platform/api/clue_api/projections_app.py` (~line 826) and after the `async with db_lifespan():` body in `platform/page_origin/clue_page_origin/main.py` (~line 41, inside the lifespan, in a `try/finally`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q tests/storage/test_s3_shared_client.py tests/storage/test_factory.py tests/storage/test_backends.py`
Expected: the new tests pass; `test_backends.py`'s S3 leg skips unless `CLUE_TEST_MINIO_ENDPOINT` is set (if you have MinIO, set it and confirm the S3 leg passes too).

- [ ] **Step 5: Commit**

```bash
uv run ruff check libs/clue-storage libs/clue-config/clue_config/settings.py tests/storage platform/api/clue_api/fleet_main.py platform/api/clue_api/projections_app.py platform/page_origin/clue_page_origin/main.py
git add libs/clue-storage libs/clue-config/clue_config/settings.py .env.example tests/storage platform/api/clue_api/fleet_main.py platform/api/clue_api/projections_app.py platform/page_origin/clue_page_origin/main.py
git commit -m "One shared S3 client per process instead of a new connection per call

Every storage call built a client and a fresh TLS connection to R2 (~200 ms from the worker VM).
S3Storage now reuses one keep-alive client per event loop and configuration, rebuilds it once on
a connection error, and is closed at process shutdown. Pool size: CLUE_STORAGE_S3_MAX_POOL_CONNECTIONS."
```

---

### Task 3: The project artifact lock is shared for writers

**Files:**
- Modify: `platform/api/clue_api/agent_turn_wiring.py:236-342` (`DurableAgentArtifactStore.persist_body`)
- Test: `tests/api/test_project_artifact_lock_db.py`

**Interfaces:**
- Produces (used by Task 4):
  - `async def DurableAgentArtifactStore._record_body(self, conn: AsyncConnection, *, workspace_id: str, key: str, digest: str, size: int, media_type: str, subject_bindings: Sequence[tuple[UUID, str]]) -> ArtifactRecord`
  - `async def DurableAgentArtifactStore._bind_projects(self, conn: AsyncConnection, *, workspace_id: str, key: str, project_bindings: Sequence[tuple[str, str]]) -> None`
  - `def _artifact_ref(workspace_id: str, key: str, record: ArtifactRecord) -> ArtifactRef` (module-level helper in `agent_turn_wiring.py`)
  - `PROJECT_ARTIFACTS_LOCK = "agent-project-artifacts:{workspace_id}:{project_id}"` (module constant, `.format(...)`-ed at the three lock sites)

- [ ] **Step 1: Write the failing test**

`tests/api/test_project_artifact_lock_db.py`:

```python
"""Two artifact writers in one project never block each other; project erasure excludes both.

Production 2026-10-03: every research save took the project-wide advisory lock exclusively, so all
jobs in a project queued on it (waits up to 280 s). Writers now take it shared; erasure keeps it
exclusive. Real, independent, committed Postgres transactions.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.agent_turn_wiring import PROJECT_ARTIFACTS_LOCK, DurableAgentArtifactStore
from clue_db import db_lifespan
from clue_storage import artifact_key, content_address
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db, run_async  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_two_writers_share_the_project_lock_and_erasure_waits_for_both() -> None:
    async def case() -> None:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                project = await seed_project(conn, f"ws-lock-{uuid4()}", name="Lock test")
            store = DurableAgentArtifactStore(storage=None)  # type: ignore[arg-type]
            scope = PROJECT_ARTIFACTS_LOCK.format(
                workspace_id=project.workspace_id, project_id=project.project_id
            )

            async def bind(conn, data: bytes) -> None:
                digest = content_address(data)
                key = artifact_key(project.workspace_id, digest)
                await store._record_body(
                    conn,
                    workspace_id=project.workspace_id,
                    key=key,
                    digest=digest,
                    size=len(data),
                    media_type="text/plain",
                    subject_bindings=(),
                )
                await store._bind_projects(
                    conn,
                    workspace_id=project.workspace_id,
                    key=key,
                    project_bindings=((project.project_id, "account_research_context"),),
                )

            first_bound = asyncio.Event()
            release_first = asyncio.Event()

            async def first_writer() -> None:
                async with engine.begin() as conn:
                    await bind(conn, b"first")
                    first_bound.set()
                    await release_first.wait()

            async def second_writer() -> None:
                await first_bound.wait()
                async with engine.begin() as conn:
                    await bind(conn, b"second")

            async def eraser() -> None:
                # engine.connect + explicit rollback: after the lock timeout Postgres has aborted
                # this transaction, so it must be rolled back, never committed.
                await first_bound.wait()
                async with engine.connect() as conn:
                    await conn.begin()
                    await conn.execute(text("SET LOCAL lock_timeout = '300ms'"))
                    with pytest.raises(DBAPIError):
                        await conn.execute(
                            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                            {"scope": scope},
                        )
                    await conn.rollback()

            first = asyncio.create_task(first_writer())
            # The second writer completes while the first still holds its (shared) lock.
            await asyncio.wait_for(second_writer(), timeout=5)
            # Erasure's exclusive lock cannot be taken while a writer holds the shared one.
            erase_attempt = asyncio.create_task(eraser())
            await asyncio.wait_for(erase_attempt, timeout=5)
            release_first.set()
            await asyncio.wait_for(first, timeout=5)
            # Once the writer committed, erasure gets the lock immediately.
            async with engine.begin() as conn:
                await conn.execute(text("SET LOCAL lock_timeout = '300ms'"))
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": scope},
                )

    run_async(case())
```

`DurableAgentArtifactStore(storage=None)` is enough here: the test calls only the two recording helpers, which never touch storage.

- [ ] **Step 2: Run test to verify it fails**

Run: `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/api/test_project_artifact_lock_db.py`
Expected: FAIL — `ImportError: cannot import name 'PROJECT_ARTIFACTS_LOCK'`.

- [ ] **Step 3: Write the implementation**

In `platform/api/clue_api/agent_turn_wiring.py`:

Add near the top-level constants:

```python
# Serialises project-artifact binding against project erasure. Writers take it SHARED (they never
# block each other — production 2026-10-03 showed all research jobs of a project queueing on the
# exclusive form); erase_project and its binding cleanup take it EXCLUSIVE.
PROJECT_ARTIFACTS_LOCK = "agent-project-artifacts:{workspace_id}:{project_id}"


def _artifact_ref(workspace_id: str, key: str, record: ArtifactRecord) -> ArtifactRef:
    return ArtifactRef(
        workspace_id=workspace_id,
        artifact_key=key,
        sha256=record.content_sha256,
        media_type=record.media_type,
        byte_count=record.size_bytes,
    )
```

(`ArtifactRecord` comes from `clue_storage`; add it to the existing `clue_storage` import.)

Replace `persist_body` (lines 236-342) with the three methods below. The SQL and the long comment are moved verbatim from the current method; only the lock function and the split change.

```python
    async def persist_body(
        self,
        *,
        workspace_id: str,
        data: bytes,
        media_type: str,
        subject_bindings: Sequence[tuple[UUID, str]] = (),
        project_bindings: Sequence[tuple[str, str]] = (),
    ) -> ArtifactRef:
        digest = content_address(data)
        key = artifact_key(workspace_id, digest)
        async with self._conn_factory() as conn:
            record = await self._record_body(
                conn,
                workspace_id=workspace_id,
                key=key,
                digest=digest,
                size=len(data),
                media_type=media_type,
                subject_bindings=subject_bindings,
            )
            await self._bind_projects(
                conn, workspace_id=workspace_id, key=key, project_bindings=project_bindings
            )
        # The row is committed before external storage mutation. A crash here is body-unavailable
        # and therefore fail-closed; retry converges on this same content-addressed key.
        await self._storage.put(key, data, media_type=record.media_type)
        return _artifact_ref(workspace_id, key, record)

    async def _record_body(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        key: str,
        digest: str,
        size: int,
        media_type: str,
        subject_bindings: Sequence[tuple[UUID, str]],
    ) -> ArtifactRecord:
        """Record the artifact row (before any upload — the storage rule) and its subjects."""
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )
        tombstone = await conn.execute(
            text(
                "SELECT 1 FROM agent_artifact_tombstone "
                "WHERE workspace_id = :workspace_id AND artifact_key = :key LIMIT 1"
            ),
            {"workspace_id": workspace_id, "key": key},
        )
        if tombstone.first() is not None:
            raise ValueError("erased agent artifact bytes cannot be resurrected")
        record = await record_artifact(
            conn,
            storage_key=key,
            workspace_id=workspace_id,
            content_sha256=digest,
            media_type=media_type,
            size_bytes=size,
        )
        for subject_entity_id, binding_kind in sorted(
            subject_bindings,
            key=lambda item: (str(item[0]), item[1]),
        ):
            await conn.execute(
                text(
                    "INSERT INTO agent_artifact_subject "
                    "(workspace_id, artifact_key, subject_entity_id, binding_kind) "
                    "VALUES (:workspace_id, :key, :subject, :kind) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "workspace_id": workspace_id,
                    "key": key,
                    "subject": subject_entity_id,
                    "kind": binding_kind,
                },
            )
        return record

    async def _bind_projects(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        key: str,
        project_bindings: Sequence[tuple[str, str]],
    ) -> None:
        """Bind the artifact to its projects under the SHARED project lock (erasure is exclusive)."""
        for project_id, binding_kind in sorted(set(project_bindings)):
            await conn.execute(
                text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:scope, 0))"),
                {
                    "scope": PROJECT_ARTIFACTS_LOCK.format(
                        workspace_id=workspace_id, project_id=project_id
                    )
                },
            )
            inserted = await conn.execute(
                text(
                    "INSERT INTO agent_artifact_project "
                    "(workspace_id, project_id, artifact_key, binding_kind) "
                    "SELECT :workspace_id, :project_id, :key, :kind FROM project "
                    "WHERE project_id=:project_id AND workspace_id=:workspace_id "
                    "ON CONFLICT DO NOTHING RETURNING artifact_key"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "key": key,
                    "kind": binding_kind,
                },
            )
            if inserted.first() is None:
                # <-- keep the existing multi-line comment about the PK and binding_kind here,
                #     verbatim from the current method (lines ~313-321) -->
                existing = await conn.execute(
                    text(
                        "SELECT 1 FROM agent_artifact_project "
                        "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                        "AND artifact_key=:key"
                    ),
                    {"workspace_id": workspace_id, "project_id": project_id, "key": key},
                )
                if existing.first() is None:
                    raise ValueError("agent artifact project binding is absent or cross-workspace")
```

(The `<-- keep ... -->` line is an instruction to copy the existing comment block, not text to paste.)

At the two erasure sites (`erase_project`, ~lines 1795-1798 and ~1827-1830), replace the f-string scope with `PROJECT_ARTIFACTS_LOCK.format(workspace_id=workspace_id, project_id=project_id)` and **keep** `pg_advisory_xact_lock` (exclusive).

- [ ] **Step 4: Run tests to verify they pass**

Run: `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/api/test_project_artifact_lock_db.py tests/api/test_agent_turn_wiring_db.py`
Expected: all pass (including the existing `test_project_bound_context_blocks_orphaning_and_is_erased_before_project_delete`).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/agent_turn_wiring.py tests/api/test_project_artifact_lock_db.py
git commit -m "Artifact writers take the project lock shared; project erasure keeps it exclusive

All research jobs of a project queued on one exclusive advisory lock (waits up to 280 s in
production). Writers never conflict with each other, only with erasure, so they now take it in
shared mode. persist_body is split into _record_body and _bind_projects for the research sink."
```

---

### Task 4: Research artifact saves upload before the project lock and write derivation edges in one statement

**Files:**
- Modify: `platform/api/clue_api/quality_research_artifacts.py:27-134` (`ResearchArtifacts.persist_body`)
- Test: `tests/api/test_research_artifacts_db.py`

**Interfaces:**
- Consumes: `_record_body`, `_bind_projects`, `_artifact_ref`, `PROJECT_ARTIFACTS_LOCK` from Task 3; `critical_section` from Task 1.
- Produces: unchanged public signature of `ResearchArtifacts.persist_body`.

- [ ] **Step 1: Write the failing tests**

`tests/api/test_research_artifacts_db.py`:

```python
"""ResearchArtifacts.persist_body: upload before the project lock, one derivation statement."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import event, text

from clue_api.agent_turn_wiring import PROJECT_ARTIFACTS_LOCK
from clue_api.quality_research_artifacts import ResearchArtifacts
from clue_storage import StorageError
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


class _LockProbeStorage:
    """Delegates to FsStorage; at put time records whether this backend holds the project lock."""

    def __init__(self, inner: FsStorage, conn: Any, scope: str, fail: bool = False) -> None:
        self._inner, self._conn, self._scope, self._fail = inner, conn, scope, fail
        self.lock_held_at_put: list[bool] = []

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        held = (
            await self._conn.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() "
                    "AND locktype='advisory' "
                    "AND (classid::bigint<<32 | objid::bigint)=hashtextextended(:s,0)"
                ),
                {"s": self._scope},
            )
        ).scalar_one()
        self.lock_held_at_put.append(held > 0)
        if self._fail:
            raise StorageError("simulated upload failure")
        await self._inner.put(key, data, media_type=media_type)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _borrowed(conn: Any):
    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield conn

    return factory


async def _sink(conn: Any, storage: Any, job: Any, cid: Any) -> ResearchArtifacts:
    sink = ResearchArtifacts(storage=storage, conn_factory=_borrowed(conn))
    sink.scope = job
    sink.context_id = cid
    return sink


def test_upload_happens_before_the_project_lock_and_the_lock_is_held_after(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            scope = PROJECT_ARTIFACTS_LOCK.format(
                workspace_id=job.workspace_id, project_id=job.project_id
            )
            probe = _LockProbeStorage(fs, conn, scope)
            sink = await _sink(conn, probe, job, cid)
            await sink.persist_body(
                workspace_id=job.workspace_id, data=b'{"x":1}', media_type="application/json"
            )
            assert probe.lock_held_at_put == [False]
            after = (
                await conn.execute(
                    text(
                        "SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() "
                        "AND locktype='advisory' "
                        "AND (classid::bigint<<32 | objid::bigint)=hashtextextended(:s,0)"
                    ),
                    {"s": scope},
                )
            ).scalars().all()
            assert after == ["ShareLock"]

    run_async(case())


def test_derivation_edges_are_one_statement_with_the_same_rows(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            for i in range(25):
                await save(conn, fs, op, f"Source body number {i}.", url=f"https://e.test/{i}")
            parents = set(
                (
                    await conn.execute(
                        text(
                            "SELECT artifact_key FROM arv2_evidence_source "
                            "WHERE workspace_id=:ws AND run_id=:run AND account_id=:account"
                        ),
                        {"ws": op.workspace_id, "run": op.run_id, "account": op.account_id},
                    )
                ).scalars()
            )
            statements: list[str] = []

            def count(conn_, cursor, statement, *args: Any) -> None:
                if "INSERT INTO artifact_derivation" in statement:
                    statements.append(statement)

            event.listen(conn.sync_connection, "before_cursor_execute", count)
            try:
                sink = await _sink(conn, fs, job, cid)
                ref = await sink.persist_body(
                    workspace_id=job.workspace_id, data=b'{"y":2}', media_type="application/json"
                )
            finally:
                event.remove(conn.sync_connection, "before_cursor_execute", count)
            assert len(statements) == 1
            linked = set(
                (
                    await conn.execute(
                        text(
                            "SELECT parent_key FROM artifact_derivation "
                            "WHERE workspace_id=:ws AND child_key=:key"
                        ),
                        {"ws": job.workspace_id, "key": ref.artifact_key},
                    )
                ).scalars()
            )
            assert parents <= linked

    run_async(case())


def test_a_failed_upload_leaves_no_binding_or_derivation(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            await save(conn, fs, op, "Only source.", url="https://e.test/only")
            scope = PROJECT_ARTIFACTS_LOCK.format(
                workspace_id=job.workspace_id, project_id=job.project_id
            )
            sink = await _sink(conn, _LockProbeStorage(fs, conn, scope, fail=True), job, cid)
            savepoint = await conn.begin_nested()
            with pytest.raises(StorageError):
                await sink.persist_body(
                    workspace_id=job.workspace_id, data=b'{"z":3}', media_type="application/json"
                )
            await savepoint.rollback()
            rows = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_artifact_project ap "
                        "WHERE ap.workspace_id=:ws AND ap.artifact_key LIKE :k"
                    ),
                    {"ws": job.workspace_id, "k": f"{job.workspace_id}/%"},
                )
            ).scalar_one()
            derived = (
                await conn.execute(
                    text("SELECT count(*) FROM artifact_derivation WHERE workspace_id=:ws"),
                    {"ws": job.workspace_id},
                )
            ).scalar_one()
            assert rows == 0
            assert derived == 0

    run_async(case())
```

If `setup()` already persists artifacts that are bound to the project or derived (check by running the third test before the change: if the counts are non-zero before `persist_body`, record them first and compare `after == before` instead of `== 0`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/api/test_research_artifacts_db.py`
Expected: the first test FAILS with `assert [True] == [False]` (today the inner store uploads after taking the project lock); the second FAILS with `assert 25-ish == 1` statements.

- [ ] **Step 3: Write the implementation**

Replace the body of `ResearchArtifacts.persist_body` from `async with self._conn_factory() as conn:` to the end with (the two reads and the `FOR SHARE` check are unchanged; copy them as they are):

```python
        digest = content_address(data)
        key = artifact_key(workspace_id, digest)
        async with self._conn_factory() as conn:
            with critical_section(
                "research_artifacts.persist_body",
                job_id=str(scope.job_id),
                project_id=scope.project_id,
            ):
                params = {...}            # unchanged
                subjects = ...            # unchanged query
                sources = ...             # unchanged query
                parents = sorted(set(sources) - {key})
                live = ...                # unchanged FOR SHARE query
                if len(live) != len(parents):
                    raise ArtifactIntegrityError(
                        "research context or evidence has been erased or expired"
                    )
                # The row first (the storage rule), then the upload, and only then the shared
                # project lock — it is held for the few statements below, never across R2.
                record = await self._record_body(
                    conn,
                    workspace_id=workspace_id,
                    key=key,
                    digest=digest,
                    size=len(data),
                    media_type=media_type,
                    subject_bindings=tuple(
                        set(subject_bindings) | {(s, "derived") for s in subjects}
                    ),
                )
                await self._storage.put(key, data, media_type=record.media_type)
                await self._bind_projects(
                    conn,
                    workspace_id=workspace_id,
                    key=key,
                    project_bindings=tuple(
                        set(project_bindings) | {(scope.project_id, "research_execution")}
                    ),
                )
                if parents:
                    await conn.execute(
                        text(
                            "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                            "SELECT :ws, parent, :key FROM unnest(CAST(:parents AS text[])) "
                            "AS parent ON CONFLICT DO NOTHING"
                        ),
                        {"ws": workspace_id, "parents": parents, "key": key},
                    )
                await retain_artifact(
                    conn,
                    workspace_id=workspace_id,
                    storage_key=key,
                    reference_kind="research_execution_output",
                    reference_id=str(scope.job_id),
                )
                return _artifact_ref(workspace_id, key, record)
```

Remove the now-unused `same_transaction` / inner `sink` code and the `key = artifact_key(workspace_id, content_address(data))` line it replaces. Update imports: add `from clue_api.agent_turn_wiring import DurableAgentArtifactStore, _artifact_ref` and `from clue_obs import critical_section`; drop `asynccontextmanager` / `AsyncIterator` if unused. Update the module docstring's last sentence to add: "Saves record the artifact row, upload, then take the shared project lock for the bindings, and write all derivation edges in one statement (research slowness fix 2026-10-03)."

- [ ] **Step 4: Run tests to verify they pass**

Run: `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/api/test_research_artifacts_db.py tests/arv2/test_quality_json_dossier_db.py tests/arv2/test_quality_dossier_db.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/quality_research_artifacts.py tests/api/test_research_artifacts_db.py
git commit -m "Research artifact saves upload before the project lock and write derivations at once

Each save took the project lock, uploaded to R2 inside it and inserted one derivation row per
evidence source, holding the lock 3-18 s. Now the row is recorded, the bytes uploaded, and only
then the shared lock taken for the bindings; all derivation edges go in one statement."
```

---

### Task 5: Evidence saving prepares without the account lock and publishes once

**Files:**
- Modify: `platform/api/clue_api/arv2/quality_evidence.py:111-256` (`persist_source`)
- Modify: `platform/api/clue_api/arv2/quality_acquisition.py:23-50` (`index_acquisition`), `:65-98` (`recover_acquisitions`), `:101-…` (`_index_receipts`)
- Test: `tests/arv2/test_evidence_publish_db.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class PreparedSource: existing: SourceRef | None; pending: Mapping[str, Any] | None`
  - `async def prepare_source(conn, storage, scope, *, kind, body, original_key, origin_locator, observed_at, source_url=None, ledger_id=None, operation_id=None, metadata=None, normalizer_version="v1") -> PreparedSource`
  - `async def publish_sources(conn, scope, prepared: Sequence[PreparedSource]) -> tuple[SourceRef, ...]`
  - `persist_source(...)` keeps its exact signature and return type.
  - `_index_receipts(...) -> tuple[PreparedSource, ...]` (was `tuple[SourceRef, ...]`).

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_evidence_publish_db.py`:

```python
"""Evidence saving: uploads run without the account lock; publication is locked once."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_evidence import prepare_source, publish_sources
from clue_db import db_lifespan
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests.arv2 import test_quality_evidence_db as evidence
from tests.arv2.test_quality_claims_db import setup
from tests.claimstore.conftest import migrated_db, require_claimstore_db, run_async  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")
NOW = datetime(2026, 10, 3, tzinfo=UTC)


class _SlowStorage(FsStorage):
    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        await asyncio.sleep(0.3)
        await super().put(key, data, media_type=media_type)


def _unique_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evidence,
        "seed_icp_fixture",
        partial(evidence.seed_icp_fixture, workspace_id=f"pub-{uuid4()}", user_id=f"u-{uuid4()}"),
    )


async def _prepare(conn, storage, op, body: str):
    return await prepare_source(
        conn,
        storage,
        op,
        kind="web_snapshot",
        body=body,
        original_key=None,
        origin_locator="fixture",
        observed_at=NOW,
        source_url="https://example.test/" + body[:8],
    )


def test_two_transactions_upload_in_parallel_and_revisions_stay_gap_free(
    tmp_path, monkeypatch
) -> None:
    _unique_workspace(monkeypatch)

    async def case() -> None:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                op, _, _ = await setup(conn, FsStorage(tmp_path))
            storage = _SlowStorage(tmp_path)

            async def batch(tag: str) -> list[int]:
                async with engine.begin() as conn:
                    prepared = [await _prepare(conn, storage, op, f"{tag} body {i}") for i in range(3)]
                    refs = await publish_sources(conn, op, prepared)
                    return [r.revision for r in refs]

            started = time.monotonic()
            a, b = await asyncio.gather(batch("alpha"), batch("beta"))
            elapsed = time.monotonic() - started
            # Serial would be ~1.8 s (6 x 0.3 s); parallel uploads ~0.9 s.
            assert elapsed < 1.5, elapsed
            revisions = sorted(a + b)
            assert revisions == list(range(revisions[0], revisions[0] + 6))

    run_async(case())


def test_the_same_source_saved_concurrently_is_one_row(tmp_path, monkeypatch) -> None:
    _unique_workspace(monkeypatch)

    async def case() -> None:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                op, _, _ = await setup(conn, FsStorage(tmp_path))
            storage = _SlowStorage(tmp_path)

            async def save_same() -> str:
                async with engine.begin() as conn:
                    prepared = [await _prepare(conn, storage, op, "identical body")]
                    (ref,) = await publish_sources(conn, op, prepared)
                    return str(ref.source_id)

            first, second = await asyncio.gather(save_same(), save_same())
            assert first == second
            async with engine.begin() as conn:
                count = (
                    await conn.execute(
                        text("SELECT count(*) FROM arv2_evidence_source WHERE source_id=:id"),
                        {"id": first},
                    )
                ).scalar_one()
            assert count == 1

    run_async(case())
```

Add to `tests/arv2/test_quality_evidence_db.py` (or a new test in this file, using its `rollback_conn` style) a paging test for `recover_acquisitions`: seed 5 ledger rows whose `response_artifact_key` points at stored provider envelopes (copy the seeding used by the existing recovery test in `tests/arv2/` — find it with `git grep -n "recover_acquisitions" tests/`), monkeypatch the batch size constant `_RECOVERY_BATCH` (introduced in Step 3) to `2`, call `recover_acquisitions` once, and assert it returns every source exactly once and terminates (wrap in `asyncio.wait_for(..., 10)`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/arv2/test_evidence_publish_db.py`
Expected: FAIL — `ImportError: cannot import name 'prepare_source'`.

- [ ] **Step 3: Write the implementation**

In `quality_evidence.py`, add `from collections.abc import Sequence` (if missing), `from clue_obs import critical_section`, and replace `persist_source` with:

```python
@dataclass(frozen=True)
class PreparedSource:
    """A source whose bytes are stored and retained but not yet published (no revision yet).

    ``existing`` is set when the deterministic source id was already recorded; otherwise
    ``pending`` holds every ``SourceRef`` field except ``revision``.
    """

    existing: SourceRef | None
    pending: Mapping[str, Any] | None


async def _existing_source(conn: AsyncConnection, sid: UUID) -> SourceRef | None:
    row = (
        (await conn.execute(text("SELECT * FROM arv2_evidence_source WHERE source_id=:id"), {"id": sid}))
        .mappings()
        .one_or_none()
    )
    return None if row is None else SourceRef.model_validate(dict(row))


async def prepare_source(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    *,
    kind: SourceKind,
    body: str | Mapping[str, JsonValue] | list[JsonValue],
    original_key: str | None,
    origin_locator: str,
    observed_at: datetime,
    source_url: str | None = None,
    ledger_id: UUID | None = None,
    operation_id: UUID | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
    normalizer_version: str = "v1",
) -> PreparedSource:
    """Store, verify and retain one source's bytes WITHOUT the account-wide manifest lock.

    The artifact row is still recorded before the upload (the storage rule); only publication —
    the revision and the ``arv2_evidence_source`` row — needs the account lock
    (:func:`publish_sources`).
    """
    subject = await _subject(conn, scope)
    raw = (
        body if isinstance(body, str) else json.dumps(body, sort_keys=True, separators=(",", ":"))
    ).encode()
    media = "text/plain" if isinstance(body, str) else "application/json"
    sha = content_address(raw)
    key = artifact_key(scope.workspace_id, sha)
    identity = json.dumps(
        [
            str(scope.job_id),
            str(ledger_id),
            str(operation_id),
            original_key,
            origin_locator,
            kind,
            source_url,
            sha,
            normalizer_version,
        ],
        separators=(",", ":"),
    )
    sid = uuid5(NAMESPACE_URL, "research-source:" + identity)
    existing = await _existing_source(conn, sid)
    if existing is not None:
        await _body(conn, storage, existing)
        return PreparedSource(existing=existing, pending=None)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=scope.workspace_id,
        content_sha256=sha,
        media_type=media,
        size_bytes=len(raw),
    )
    await storage.put(key, raw, media_type=media)
    for retained in sorted({key, *([original_key] if original_key else [])}):
        await retain_artifact(
            conn,
            workspace_id=scope.workspace_id,
            storage_key=retained,
            reference_kind="research_source",
            reference_id=str(sid),
        )
    if original_key and original_key != key:
        # Retention above holds both artifact locks; erasure cannot slip between check and link.
        await read_verified_artifact(
            conn, storage, workspace_id=scope.workspace_id, storage_key=original_key
        )
        await conn.execute(
            text(
                "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                "VALUES(:ws,:parent,:child) ON CONFLICT DO NOTHING"
            ),
            {"ws": scope.workspace_id, "parent": original_key, "child": key},
        )
    return PreparedSource(
        existing=None,
        pending={
            "source_id": sid,
            "workspace_id": scope.workspace_id,
            "run_id": scope.run_id,
            "account_id": scope.account_id,
            "job_id": scope.job_id,
            "subject_id": subject,
            "kind": kind,
            "artifact_key": key,
            "artifact_sha256": sha,
            "byte_size": len(raw),
            "media_type": media,
            "original_key": original_key,
            "source_url": source_url,
            "observed_at": observed_at,
            "ledger_id": ledger_id,
            "operation_id": operation_id,
            "origin_locator": origin_locator,
            "normalizer_version": normalizer_version,
            "metadata": dict(metadata or {}),
        },
    )


async def publish_sources(
    conn: AsyncConnection, scope: OperationScope, prepared: Sequence[PreparedSource]
) -> tuple[SourceRef, ...]:
    """Publish prepared sources: one account-lock acquisition, revisions in the given order."""
    if all(item.existing is not None for item in prepared):
        return tuple(item.existing for item in prepared if item.existing is not None)
    params = _params(scope)
    refs: list[SourceRef] = []
    with critical_section("arv2.evidence.publish", job_id=str(scope.job_id), sources=len(prepared)):
        await conn.execute(
            text(
                "INSERT INTO arv2_evidence_manifest(workspace_id,run_id,account_id) "
                "VALUES(:ws,:run,:account) ON CONFLICT DO NOTHING"
            ),
            params,
        )
        # One account's sequence lock gives manifest revision a real publication order.
        await conn.execute(
            text(
                "SELECT revision FROM arv2_evidence_manifest WHERE workspace_id=:ws "
                "AND run_id=:run AND account_id=:account FOR UPDATE"
            ),
            params,
        )
        for item in prepared:
            if item.existing is not None:
                refs.append(item.existing)
                continue
            assert item.pending is not None
            already = await _existing_source(conn, item.pending["source_id"])
            if already is not None:  # published by a concurrent save while we prepared
                refs.append(already)
                continue
            revision = (
                await conn.execute(
                    text(
                        "UPDATE arv2_evidence_manifest SET revision=revision+1 WHERE "
                        "workspace_id=:ws AND run_id=:run AND account_id=:account "
                        "RETURNING revision"
                    ),
                    params,
                )
            ).scalar_one()
            ref = SourceRef(revision=revision, **item.pending)
            values = ref.model_dump()
            values["metadata"] = json.dumps(values["metadata"])
            columns = ",".join(values)
            binds = ",".join(
                "CAST(:metadata AS jsonb)" if k == "metadata" else ":" + k for k in values
            )
            await conn.execute(
                text(f"INSERT INTO arv2_evidence_source({columns}) VALUES({binds})"), values
            )
            log.info(
                "arv2.evidence_recorded",
                source_id=str(ref.source_id),
                job_id=str(scope.job_id),
                revision=revision,
                ledger_id=str(ref.ledger_id) if ref.ledger_id else None,
                kind=ref.kind,
            )
            refs.append(ref)
    return tuple(refs)


async def persist_source(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    *,
    kind: SourceKind,
    body: str | Mapping[str, JsonValue] | list[JsonValue],
    original_key: str | None,
    origin_locator: str,
    observed_at: datetime,
    source_url: str | None = None,
    ledger_id: UUID | None = None,
    operation_id: UUID | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
    normalizer_version: str = "v1",
) -> SourceRef:
    """Trusted acquisition only. Commit before returning this handle to an agent.

    A provider report and its individual pages are separate descriptors; repeat observations have
    distinct ledger IDs even when bytes match. Re-draining one observation reuses its source ID.
    One source: prepare, then publish.
    """
    prepared = await prepare_source(
        conn,
        storage,
        scope,
        kind=kind,
        body=body,
        original_key=original_key,
        origin_locator=origin_locator,
        observed_at=observed_at,
        source_url=source_url,
        ledger_id=ledger_id,
        operation_id=operation_id,
        metadata=metadata,
        normalizer_version=normalizer_version,
    )
    (ref,) = await publish_sources(conn, scope, (prepared,))
    return ref
```

Copy the exact parameter type names (`SourceKind` or whatever the current `kind` annotation is) from the current `persist_source` signature (lines 111-125) — use the same annotations, do not invent new ones. Export `PreparedSource`, `prepare_source`, `publish_sources` in the module's `__all__` if it has one.

In `quality_acquisition.py`:

```python
from clue_api.arv2.quality_evidence import (
    PreparedSource,
    SourceRef,
    prepare_source,
    publish_sources,
)

_RECOVERY_BATCH = 100


async def index_acquisition(conn, storage, scope, report, *, operation_id=None) -> tuple[SourceRef, ...]:
    prepared = await _index_receipts(conn, storage, scope, tuple(...unchanged receipts...))
    return await publish_sources(conn, scope, prepared)


async def recover_acquisitions(
    conn: AsyncConnection, storage: StorageBackend, scope: OperationScope
) -> tuple[SourceRef, ...]:
    """Rebuild missing descriptors from settled ledger artifacts, never from another purchase.

    Every batch is prepared (stored, verified, retained) first and everything is published once
    at the end, so the account lock is never held across an upload. Rows already prepared in
    this call are excluded by id, because they are not published yet.
    """
    prepared: list[PreparedSource] = []
    seen: list[UUID] = []
    while True:
        rows = (
            (
                await conn.execute(
                    text("""
          SELECT l.ledger_id,l.provider,l.operation,l.recorded_at,l.http_status,l.error_code,
                 l.response_artifact_key AS key,o.operation_id
          FROM provider_call_ledger l LEFT JOIN arv2_research_operation o
            ON o.ledger_id=l.ledger_id AND o.workspace_id=l.workspace_id AND o.job_id=:job
          WHERE l.workspace_id=:ws AND l.entity_research_job_id=:job AND l.phase='result'
            AND l.provider NOT IN ('openrouter','model')
            AND NOT EXISTS(SELECT 1 FROM arv2_evidence_source s
                           WHERE s.workspace_id=l.workspace_id AND s.ledger_id=l.ledger_id)
            AND NOT (l.ledger_id = ANY(CAST(:seen AS uuid[])))
          ORDER BY l.recorded_at,l.ledger_id LIMIT :batch
        """),
                    {"ws": scope.workspace_id, "job": scope.job_id, "seen": seen, "batch": _RECOVERY_BATCH},
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return await publish_sources(conn, scope, prepared)
        seen.extend(row["ledger_id"] for row in rows)
        prepared.extend(
            await _index_receipts(
                conn, storage, scope, tuple(AcquisitionReceipt(**dict(r)) for r in rows)
            )
        )
```

In `_index_receipts`: change its return annotation to `tuple[PreparedSource, ...]`, rename the local list to `prepared`, replace the one direct `persist_source(...)` call (the `acquisition_gap` branch) with `prepare_source(...)` (same arguments), and change `save = partial(persist_source, ...)` to `save = partial(prepare_source, ...)`. Everything else is unchanged.

Known residual (document it in the `_memory` note in Task 10, do not fix here): in `quality_provider_tools.py:~161` the recovery path runs `recover_acquisitions` and then `index_transcripts` in one transaction, so `index_transcripts`' single-source `persist_source` uploads while the account lock taken by the recovery's publish is still held. That path runs only when a tool call lost its race (`not won`), not on the hot path.

- [ ] **Step 4: Run tests to verify they pass**

Run: `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/arv2/test_evidence_publish_db.py tests/arv2/test_quality_evidence_db.py $(git grep -l "recover_acquisitions\|index_acquisition" tests/)`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/quality_evidence.py platform/api/clue_api/arv2/quality_acquisition.py tests/arv2/test_evidence_publish_db.py tests/arv2/test_quality_evidence_db.py
git commit -m "Evidence saving uploads without the account lock and publishes a batch at once

persist_source took the account-wide manifest lock first and uploaded under it, and acquisition
saved dozens of sources in one transaction, so every upload after the first ran under the lock.
Saving is now prepare (row, upload, retain, no lock) then publish (one lock, revisions in order)."
```

---

### Task 6: Dossier import prefetches its reads and sends its uploads concurrently

**Files:**
- Create: `platform/api/clue_api/arv2/import_storage.py`
- Modify: `platform/api/clue_api/arv2/dossier_import.py:75-…` (`import_research_dossier`)
- Test: `tests/arv2/test_import_storage.py` (no DB), `tests/arv2/test_dossier_import_db.py` (add tests)

**Interfaces:**
- Produces: `class ImportStorage(StorageBackend)` with `__init__(self, inner: StorageBackend, *, concurrency: int = 8)`, `async prefetch(keys: Iterable[str]) -> None`, `async flush() -> None`; `async def import_read_keys(conn, grant, *, scope, context_id, records, source_aliases) -> set[str]` in `dossier_import.py`.

- [ ] **Step 1: Write the failing unit tests**

`tests/arv2/test_import_storage.py`:

```python
"""ImportStorage: prefetched reads, deferred concurrent uploads, failures surface."""

from __future__ import annotations

import asyncio
import time

import pytest

from clue_api.arv2.import_storage import ImportStorage
from clue_storage import ArtifactNotFound, StorageError


class _Slow:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {"a": b"A", "b": b"B", "c": b"C"}
        self.gets: list[str] = []
        self.puts: list[str] = []
        self.fail_put = False

    async def get(self, key: str) -> bytes:
        self.gets.append(key)
        await asyncio.sleep(0.2)
        if key not in self.data:
            raise ArtifactNotFound(key)
        return self.data[key]

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        await asyncio.sleep(0.2)
        if self.fail_put:
            raise StorageError("upload failed")
        self.puts.append(key)
        self.data[key] = data

    async def exists(self, key: str) -> bool:
        return key in self.data


def test_prefetch_runs_concurrently_and_serves_reads_from_memory() -> None:
    async def scenario() -> None:
        inner = _Slow()
        staged = ImportStorage(inner, concurrency=8)  # type: ignore[arg-type]
        started = time.monotonic()
        await staged.prefetch(["a", "b", "c", "a"])
        assert time.monotonic() - started < 0.45
        assert await staged.get("b") == b"B"
        assert sorted(inner.gets) == ["a", "b", "c"]

    asyncio.run(scenario())


def test_a_missing_key_at_prefetch_is_left_for_the_real_read_to_refuse() -> None:
    async def scenario() -> None:
        staged = ImportStorage(_Slow(), concurrency=8)  # type: ignore[arg-type]
        await staged.prefetch(["nope"])
        with pytest.raises(ArtifactNotFound):
            await staged.get("nope")

    asyncio.run(scenario())


def test_uploads_are_deferred_then_sent_concurrently_and_readable_before_flush() -> None:
    async def scenario() -> None:
        inner = _Slow()
        staged = ImportStorage(inner, concurrency=8)  # type: ignore[arg-type]
        for key in ("p1", "p2", "p3"):
            await staged.put(key, key.encode(), media_type="application/json")
        assert inner.puts == []
        assert await staged.get("p2") == b"p2"
        started = time.monotonic()
        await staged.flush()
        assert time.monotonic() - started < 0.45
        assert sorted(inner.puts) == ["p1", "p2", "p3"]

    asyncio.run(scenario())


def test_a_failed_upload_raises_from_flush() -> None:
    async def scenario() -> None:
        inner = _Slow()
        inner.fail_put = True
        staged = ImportStorage(inner, concurrency=8)  # type: ignore[arg-type]
        await staged.put("p1", b"x", media_type="application/json")
        with pytest.raises(StorageError):
            await staged.flush()

    asyncio.run(scenario())
```

Add to `tests/arv2/test_dossier_import_db.py` (reuse its `context()` / `invoke()` helpers and `document()` / `finding()`):

```python
class _CountingStorage:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.gets: dict[str, int] = {}

    async def get(self, key: str) -> bytes:
        self.gets[key] = self.gets.get(key, 0) + 1
        return await self._inner.get(key)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def test_import_reads_each_blob_once_however_many_findings_cite_it(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            ctx = await context(conn, tmp_path)
            storage, job, grant, kwargs = ctx
            counting = _CountingStorage(storage)
            body = document(finding("F001"), finding("F002"), finding("F003"))
            await invoke(conn, (counting, job, grant, kwargs), body)
            assert counting.gets and max(counting.gets.values()) == 1

    run_async(case())


def test_an_artifact_erased_after_prefetch_is_still_refused(tmp_path, monkeypatch) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            ctx = await context(conn, tmp_path)
            storage, job, grant, kwargs = ctx
            source_id = next(iter(kwargs["source_aliases"].values()))
            from clue_api.arv2 import import_storage

            original_prefetch = import_storage.ImportStorage.prefetch

            async def prefetch_then_erase(self, keys):
                await original_prefetch(self, keys)
                await conn.execute(
                    text(
                        "UPDATE artifact SET erased_at=now() WHERE storage_key=("
                        "SELECT artifact_key FROM arv2_evidence_source WHERE source_id=:id)"
                    ),
                    {"id": source_id},
                )

            monkeypatch.setattr(import_storage.ImportStorage, "prefetch", prefetch_then_erase)
            result = await invoke(conn, ctx, document(finding("F001")))
            assert "evidence_not_resolved" in json.dumps(result, default=str)

    run_async(case())
```

(Add `import json` and `from sqlalchemy import text` to the file's imports if missing. If the import's result shape names the refusal differently, assert on the status the existing `test_unknown_sources_revoked_grant_and_cross_context_never_become_success` asserts for an unresolvable source — read that test first and match it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/arv2/test_import_storage.py` and `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/arv2/test_dossier_import_db.py -k "once or erased"`
Expected: FAIL — `ModuleNotFoundError: clue_api.arv2.import_storage`; the DB test fails on `max(...) == 1` (the context manifest is read once per finding today).

- [ ] **Step 3: Write the implementation**

`platform/api/clue_api/arv2/import_storage.py`:

```python
"""Storage for one dossier import: prefetched reads, deferred concurrent uploads.

Research slowness fix (2026-10-03, spec part 3b). A dossier import runs inside its caller's
transaction and, finding by finding, read the research-context manifest, each cited source, and
uploaded proposal and disposition receipts — one R2 round trip at a time (~2.5 s per finding in
production). This wrapper lets the import fetch everything it will read up front, concurrently,
and send its uploads together just before it returns. It only changes where bytes come from and
when they leave: every artifact row check in ``read_verified_artifact`` still runs inside the
transaction, rows are still recorded before ``put`` is called, and a failed upload still raises
before the caller commits.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from datetime import datetime

from clue_storage import ArtifactNotFound, StorageBackend

__all__ = ["IMPORT_STORAGE_CONCURRENCY", "ImportStorage"]

IMPORT_STORAGE_CONCURRENCY = 8


class ImportStorage:
    def __init__(self, inner: StorageBackend, *, concurrency: int = IMPORT_STORAGE_CONCURRENCY) -> None:
        self._inner = inner
        self._limit = asyncio.Semaphore(concurrency)
        self._bytes: dict[str, bytes] = {}
        self._pending: dict[str, tuple[bytes, str]] = {}

    async def prefetch(self, keys: Iterable[str]) -> None:
        async def one(key: str) -> None:
            async with self._limit:
                try:
                    self._bytes[key] = await self._inner.get(key)
                except ArtifactNotFound:
                    pass  # the verified read inside the transaction refuses it

        wanted = sorted({key for key in keys if key and key not in self._bytes})
        await asyncio.gather(*(one(key) for key in wanted))

    async def get(self, key: str) -> bytes:
        held = self._bytes.get(key)
        return held if held is not None else await self._inner.get(key)

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self._bytes[key] = data
        self._pending[key] = (data, media_type)

    async def flush(self) -> None:
        pending, self._pending = self._pending, {}

        async def one(key: str, data: bytes, media_type: str) -> None:
            async with self._limit:
                await self._inner.put(key, data, media_type=media_type)

        await asyncio.gather(*(one(k, d, m) for k, (d, m) in pending.items()))

    async def exists(self, key: str) -> bool:
        return key in self._pending or await self._inner.exists(key)

    async def delete(self, key: str) -> None:
        self._bytes.pop(key, None)
        self._pending.pop(key, None)
        await self._inner.delete(key)

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        if key in self._pending:
            await self.flush()
        return await self._inner.presign(key, expires_in=expires_in)

    def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return self._inner.list_blobs()
```

In `dossier_import.py`:

1. Rename the existing `import_research_dossier` to `_import_research_dossier` (same signature, same body).
2. Add:

```python
async def import_read_keys(
    conn: AsyncConnection,
    grant: EvidenceGrant,
    *,
    scope: JobScope,
    context_id: UUID,
    records: Sequence[DossierRecord],
    source_aliases: Mapping[str, UUID] | None,
) -> set[str]:
    """Every storage key the import will read: the context manifest and each cited source's
    artifact and original. Resolved exactly as the import resolves them; unresolvable paths are
    skipped here and refused by the import itself."""
    keys: set[str] = set()
    manifest = (
        await conn.execute(
            text(
                "SELECT manifest_key FROM arv2_research_context_pin "
                "WHERE context_id=:id AND workspace_id=:ws"
            ),
            {"id": context_id, "ws": scope.workspace_id},
        )
    ).scalar_one_or_none()
    if manifest:
        keys.add(manifest)
    paths = {path for record in records for path in record.entry.source_paths}
    for path in sorted(paths):
        reference = source_aliases.get(path) if source_aliases is not None else path
        if reference is None:
            continue
        try:
            ref = await resolve_source(conn, grant, reference)
        except EvidenceUnavailable:
            continue
        keys.add(ref.artifact_key)
        if ref.original_key:
            keys.add(ref.original_key)
    return keys


async def import_research_dossier(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    grant: EvidenceGrant,
    *,
    context_id: UUID,
    actor_ref: str,
    import_id: UUID,
    body: bytes,
    expected_sha256: str,
    source_aliases: Mapping[str, UUID] | None = None,
    reuse_entries: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Import a dossier with prefetched reads and concurrent uploads (spec part 3b)."""
    staged = ImportStorage(storage)
    with critical_section("arv2.dossier.import", job_id=str(scope.job_id)):
        try:
            records = parse_json_dossier(body).records
        except Exception:
            records = ()  # the import itself raises the proper error below
        await staged.prefetch(
            await import_read_keys(
                conn,
                grant,
                scope=scope,
                context_id=context_id,
                records=records,
                source_aliases=source_aliases,
            )
        )
        result = await _import_research_dossier(
            conn,
            staged,
            scope,
            grant,
            context_id=context_id,
            actor_ref=actor_ref,
            import_id=import_id,
            body=body,
            expected_sha256=expected_sha256,
            source_aliases=source_aliases,
            reuse_entries=reuse_entries,
        )
        await staged.flush()
    return result
```

Keep `import_account_dossier = import_research_dossier` pointing at the public function. Add imports: `ImportStorage` from `clue_api.arv2.import_storage`, `critical_section` from `clue_obs`, `EvidenceUnavailable` and `resolve_source` from `clue_api.arv2.quality_evidence` (if not already imported), `DossierRecord` from the module that defines it (`dossier_json`, already used for `parse_json_dossier`), and `Sequence` from `collections.abc`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q tests/arv2/test_import_storage.py` and `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/arv2/test_dossier_import_db.py tests/arv2/test_quality_json_dossier_db.py tests/arv2/test_quality_claims_db.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/import_storage.py platform/api/clue_api/arv2/dossier_import.py tests/arv2/test_import_storage.py tests/arv2/test_dossier_import_db.py
git commit -m "Dossier import prefetches its reads and sends its uploads together

The import read the context manifest and every cited source, and uploaded two receipts per
finding, one R2 round trip at a time inside its transaction (~2.5 s per finding). It now fetches
what it will read up front, concurrently, and uploads at the end; all row checks stay inside."
```

---

### Task 7: A worker claims only what it can start

**Files:**
- Modify: `platform/fleet/clue_fleet/work_worker.py` (new protocol after `CapabilityGated` at ~line 113; `__init__` ~line 172; `drain_once` lines 265-295)
- Modify: `platform/fleet/clue_fleet/__init__.py` (export `InFlightLimited`, `__all__` at ~line 105)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`Arv2AccountResearchWorkHandler`, after `__init__` ~line 487)
- Modify: `.env.example:181-182` and `:317-327` (comments)
- Test: `tests/fleet/test_work_worker.py`, `tests/arv2/test_account_research_driver.py`

**Interfaces:**
- Produces: `@runtime_checkable class InFlightLimited(Protocol): max_in_flight: int | None` (a property); `Arv2AccountResearchWorkHandler.max_in_flight -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/fleet/test_work_worker.py` (it already defines `_Queue`, `_Leases`, `_BarrierHandler`, `_Handler`, `_task`, `_spin`):

```python
class _LimitedBarrierHandler(_BarrierHandler):
    def __init__(self, kind: FleetTaskKind, *, expected: int, limit: int) -> None:
        super().__init__(kind, expected=expected)
        self._limit = limit

    @property
    def max_in_flight(self) -> int:
        return self._limit


def test_a_worker_never_claims_past_a_kinds_in_flight_limit() -> None:
    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(6)]
        queue = _Queue(list(tasks))
        handler = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=4, limit=4)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:limited",
            poll_interval=0.001,
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
            concurrency=10,
        )
        running = asyncio.create_task(worker.run())
        await asyncio.wait_for(handler.expected_reached.wait(), timeout=2.0)
        for _ in range(200):
            await asyncio.sleep(0)
        assert handler.peak == 4
        assert len(queue.rows) == 2  # two tasks stay unclaimed for another worker
        handler.release.set()
        worker.stop()
        await asyncio.wait_for(running, timeout=2.0)

    asyncio.run(scenario())


def test_a_second_worker_takes_the_overflow() -> None:
    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(6)]
        queue = _Queue(list(tasks))
        first = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=4, limit=4)
        second = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=2, limit=4)

        def worker(name: str, handler: _BarrierHandler) -> LeasedWorkWorker:
            return LeasedWorkWorker(
                handlers=(handler,),
                queue=queue,
                leases=_Leases(),
                worker_id=name,
                poll_interval=0.001,
                heartbeat_interval=10,
                lease_ttl=timedelta(seconds=30),
                concurrency=10,
            )

        a, b = worker("worker:a", first), worker("worker:b", second)
        run_a = asyncio.create_task(a.run())
        await asyncio.wait_for(first.expected_reached.wait(), timeout=2.0)
        run_b = asyncio.create_task(b.run())
        await asyncio.wait_for(second.expected_reached.wait(), timeout=2.0)
        assert first.peak == 4 and second.peak == 2
        first.release.set()
        second.release.set()
        a.stop()
        b.stop()
        await asyncio.wait_for(asyncio.gather(run_a, run_b), timeout=2.0)

    asyncio.run(scenario())


def test_a_kind_at_its_limit_does_not_stop_other_kinds() -> None:
    async def scenario() -> None:
        research = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(2)]
        pages = [_task(FleetTaskKind.ARV2_DISPLAY_PAGE)]
        queue = _Queue(list(research + pages))
        limited = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=1, limit=1)
        other = _Handler(FleetTaskKind.ARV2_DISPLAY_PAGE)
        worker = LeasedWorkWorker(
            handlers=(limited, other),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:mixed",
            poll_interval=0.001,
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
            concurrency=4,
        )
        running = asyncio.create_task(worker.run())
        await asyncio.wait_for(limited.expected_reached.wait(), timeout=2.0)
        await _spin(lambda: len(other.contexts) == 1)
        assert limited.peak == 1
        limited.release.set()
        worker.stop()
        await asyncio.wait_for(running, timeout=2.0)

    asyncio.run(scenario())


class _FailingLimitedHandler(_Handler):
    def __init__(self, kind: FleetTaskKind) -> None:
        super().__init__(kind)
        self.calls = 0

    @property
    def max_in_flight(self) -> int:
        return 1

    async def handle(self, context: WorkContext) -> WorkResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("first task fails")
        return await super().handle(context)


def test_a_failing_task_releases_its_slot() -> None:
    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(2)]
        queue = _Queue(list(tasks))
        handler = _FailingLimitedHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:fail",
            poll_interval=0.001,
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
            concurrency=3,
        )
        running = asyncio.create_task(worker.run())
        await _spin(lambda: handler.calls == 2)
        worker.stop()
        await asyncio.wait_for(running, timeout=2.0)

    asyncio.run(scenario())
```

Check `_spin`'s signature at line ~640 and `_Handler.handle`'s return before running; adjust the two calls above to match (e.g. if `_spin` is `async def _spin(predicate, *, limit=...)`, call it as written). Import `WorkContext`, `WorkResult` if the file does not already.

In `tests/arv2/test_account_research_driver.py`, next to the test that asserts `handler.kind` (~line 475), add:

```python
def test_the_research_handler_declares_its_per_process_limit() -> None:
    from clue_fleet import InFlightLimited

    handler = Arv2AccountResearchWorkHandler(
        settings=Settings(_env_file=None, arv2_account_max_parallel_jobs=3),
        conn_factory=FakeConnFactory(),
        artifacts=FakeArtifacts(),
        storage=object(),
        clients=FakeClients(),
        model_provider=FakeModels(_finalizes_at_once()),
        model_id="x-ai/grok-4.6",
        writer=FakeWriter(),
        store=FakeStore(_run_row(), _job_row(_run_row())),
    )
    assert isinstance(handler, InFlightLimited)
    assert handler.max_in_flight == 3
```

(All the fakes and `_run_row` / `_job_row` / `_finalizes_at_once` are already defined in that file — see its `_handler` factory at ~line 418.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/fleet/test_work_worker.py -k "limit or overflow or other_kinds or releases" tests/arv2/test_account_research_driver.py -k per_process_limit`
Expected: `test_a_worker_never_claims_past_a_kinds_in_flight_limit` FAILS on `assert len(queue.rows) == 2` (today all six are claimed, so 0 rows remain — the extra two slots claim and then block inside the handler); the second-worker test times out waiting for `second.expected_reached`; the driver test fails with `ImportError: cannot import name 'InFlightLimited'`.

- [ ] **Step 3: Write the implementation**

In `work_worker.py`, after `CapabilityGated`:

```python
@runtime_checkable
class InFlightLimited(Protocol):
    """A handler that runs at most ``max_in_flight`` tasks at once in one process.

    The worker does not claim a task of this kind while that many are already running here, so
    a claimed task is always a running task and another worker can take the rest (research
    slowness fix 2026-10-03: a worker claimed 10 research tasks while able to run 4, and two
    person jobs sat claimed for 50 minutes while another worker was idle). ``None`` means no
    per-kind limit. Its own protocol, like ``CapabilityGated``, so the worker detects it with one
    ``isinstance``.
    """

    @property
    def max_in_flight(self) -> int | None: ...
```

In `__init__`, after `self._active_work: set[WorkId] = set()`:

```python
        self._in_flight: dict[FleetTaskKind, int] = {}
```

Add a helper after `_capabilities`:

```python
    def _at_limit(self, kind: FleetTaskKind) -> bool:
        handler = self._handlers[kind]
        if not isinstance(handler, InFlightLimited):
            return False
        limit = handler.max_in_flight
        return limit is not None and self._in_flight.get(kind, 0) >= limit

    def _release(self, kind: FleetTaskKind) -> None:
        self._in_flight[kind] = self._in_flight.get(kind, 0) - 1
```

Replace the claim-and-run part of `drain_once`:

```python
            if self._at_limit(kind):
                continue
            # Reserve before awaiting the claim: slots share this loop, and between this check
            # and the claim's return another slot could otherwise pass the same check.
            self._in_flight[kind] = self._in_flight.get(kind, 0) + 1
            try:
                task = await self._queue.claim_next(
                    kind=kind,
                    worker_id=self.worker_id,
                    stale_after=self._task_stale_after,
                    capabilities=capabilities,
                )
            except BaseException:
                self._release(kind)
                raise
            if task is None:
                self._release(kind)
                continue
            self._next_kind = (index + 1) % len(self._kind_order)
            try:
                await self._run_task(task, self._handlers[kind], slot=slot)
            finally:
                self._release(kind)
            return True
        return False
```

Export `InFlightLimited` in `platform/fleet/clue_fleet/__init__.py` next to `CapabilityGated` (import and `__all__`).

In `Arv2AccountResearchWorkHandler` (after `__init__`):

```python
    @property
    def max_in_flight(self) -> int:
        """Research jobs (account, person and quality continuations share this kind) one process
        runs at once — the same number as the ``self._jobs`` semaphore, which by construction now
        never makes a claimed task wait (research slowness fix 2026-10-03)."""
        return self._settings.arv2_account_max_parallel_jobs
```

`.env.example` — replace the comment above `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=4` with:

```
# Research jobs (account, person, quality continuation) ONE worker process runs at once. A worker
# never claims more research tasks than this; CLUE_FLEET_WORKER_CONCURRENCY is the total across
# all task kinds. Fleet-wide research capacity = batch workers x this value.
```

and add one line to the "Fleet worker concurrency" comment block: `# Research tasks are additionally capped by CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS per process.`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q tests/fleet/test_work_worker.py tests/api/test_fleet_wiring.py tests/arv2/test_account_research_driver.py tests/deploy/test_vm_compose.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform/fleet/clue_fleet/work_worker.py platform/fleet/clue_fleet/__init__.py platform/api/clue_api/arv2/account_research_driver.py .env.example tests/fleet/test_work_worker.py tests/arv2/test_account_research_driver.py
git commit -m "A fleet worker claims only the tasks it can start

A batch worker could claim up to 10 research tasks while running at most 4, so claimed tasks sat
waiting while another worker was idle (two person jobs for 50+ minutes). Handlers may declare
max_in_flight; the worker skips a kind at its limit. The research handler declares its job limit."
```

---

### Task 8: Finalize refuses before it freezes outputs

**Files:**
- Modify: `platform/agents/clue_agents/ports.py:266-289` (`AgentExecutionAdapter`)
- Modify: `platform/api/clue_api/agent_execution_wiring.py:2095-2117` (`C5AgentExecutionAdapter`)
- Modify: `platform/api/clue_api/agent_runtime_wiring.py:1288-1291` (`finalize_turn`)
- Modify test fakes: `tests/agents/test_finalize_contract.py:213` (`_RecordingFinalization`), `tests/agents/test_runtime.py:320` (`_FinalizingExecution`), `tests/agents/test_ports.py:101` (`_ExecutionPort`)
- Test: `tests/agents/test_finalize_contract.py`

**Interfaces:**
- Produces: `async def check_finalizable(self, *, status: FinalizeStatus) -> None` on `AgentExecutionAdapter` (Protocol) and `C5AgentExecutionAdapter`; raises `ValueError` to refuse, changes no state.

- [ ] **Step 1: Write the failing test**

Append to `tests/agents/test_finalize_contract.py`:

```python
class _RefuseOnceExecutionAdapter(_FinalizingExecutionAdapter):
    """Refuses the first completed finalize the way the executor does for unresolved failures."""

    def __init__(self) -> None:
        super().__init__()
        self.checks = 0

    async def check_finalizable(self, *, status: FinalizeStatus) -> None:
        self.checks += 1
        if status is FinalizeStatus.COMPLETED and self.checks == 1:
            raise ValueError(
                "Unresolved failed tool attempts remain: agent_search_evidence_1. "
                "Correct using retry_of, or finalize with an honest blocked status."
            )


class _FreezingBackend(_EmptyOutputBackend):
    """Counts snapshots; after one, the outputs folder refuses writes like the real backend."""

    def __init__(self) -> None:
        self.snapshots = 0

    async def snapshot_outputs(self, *, empty_after: bool = False) -> tuple[ArtifactRef, ...]:
        del empty_after
        self.snapshots += 1
        return ()


def test_a_refused_finalize_freezes_nothing_and_the_repaired_finalize_completes() -> None:
    backend = _FreezingBackend()
    guard_calls: list[FinalizeStatus] = []

    async def writes_outputs_guard(model_input: ModelFinalizeRequest) -> None:
        # The real research guard writes outputs/research.json; after a snapshot that write
        # raises WorkspaceConflict (a RuntimeError the repair loop cannot recover from).
        from clue_agents.workspace_policy import WorkspaceConflict

        if backend.snapshots:
            raise WorkspaceConflict("snapshotted outputs are immutable")
        guard_calls.append(model_input.status)

    execution = _RefuseOnceExecutionAdapter()
    outcome, recorded, _calls = _run(
        (
            _finalize_call("finalize-refused", status="completed", user_message="Done."),
            _finalize_call("finalize-repaired", status="completed", user_message="Done."),
        ),
        backend=backend,
        completion_guard=writes_outputs_guard,
        execution=execution,
    )
    assert outcome.status is AgentExecutionStatus.COMPLETED
    assert recorded is execution
    assert execution.checks == 2
    assert backend.snapshots == 1
    assert guard_calls == [FinalizeStatus.COMPLETED]
    assert [e.status for e in execution.envelopes] == [FinalizeStatus.COMPLETED]
```

Give the file's existing `_run` helper one optional parameter so a test can supply its own fake: add `execution: _FinalizingExecutionAdapter | None = None` to its signature and change its first line to `execution = execution if execution is not None else _FinalizingExecutionAdapter()`. Existing callers are unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/agents/test_finalize_contract.py -k refused_finalize_freezes_nothing`
Expected: FAIL — today `finalize_turn` never calls `check_finalizable` (the refusal never happens, `execution.checks == 0`); after Step 3's call is added but before the Protocol change, fakes would raise `AttributeError` — that is fixed in Step 3 too.

- [ ] **Step 3: Write the implementation**

`platform/agents/clue_agents/ports.py` — import `FinalizeStatus` from `clue_agents.contracts` (add to the existing import list) and add to `AgentExecutionAdapter`, before `finalize`:

```python
    async def check_finalizable(self, *, status: FinalizeStatus) -> None:
        """Refuse a finalization this execution cannot accept yet — before anything is frozen.

        Raises ``ValueError`` (a refusal the model can repair, e.g. unresolved failed tool
        attempts for ``completed``); never changes state. ``finalize_turn`` calls it first,
        because once ``outputs/`` is snapshotted the repair the refusal asks for is impossible
        (production 2026-10-03, McKee).
        """
        ...
```

`platform/api/clue_api/agent_execution_wiring.py` — in `C5AgentExecutionAdapter`:

```python
    async def check_finalizable(self, *, status: FinalizeStatus) -> None:
        if status is not FinalizeStatus.COMPLETED:
            return
        unresolved = await self._executor.unresolved_interaction_failures(
            execution_id=self._constitution.execution_id,
            workspace_id=self._constitution.workspace_id,
            slot_key=self._slot_key,
        )
        if unresolved:
            raise ValueError(
                "Unresolved failed tool attempts remain: "
                + ", ".join(unresolved)
                + ". Correct using retry_of, or finalize with an honest blocked status."
            )

    async def finalize(self, *, envelope: AgentFinalizeEnvelope) -> ArtifactRef:
        # The honest finalization authority is composed in agent_runtime_wiring and injected here
        # after construction to keep this adapter focused on plan/tool execution.
        authority = getattr(self, "_finalization_authority", None)
        if authority is None:
            raise RuntimeError("finalization authority is not composed")
        # Backstop: finalize_turn already ran this check before freezing outputs.
        await self.check_finalizable(status=FinalizeStatus(envelope.status.value))
        return await authority.finalize(  # type: ignore[no-any-return]
            turn_id=self._turn_id,
            workspace_id=self._constitution.workspace_id,
            envelope=envelope,
        )
```

(Import `FinalizeStatus` from `clue_agents` in this module if it is not imported already.)

`platform/api/clue_api/agent_runtime_wiring.py` — in `finalize_turn`, right after `model_input = ModelFinalizeRequest.model_validate(kwargs)`:

```python
            # Every refusal must come before the completion guard writes outputs/ and before the
            # snapshot freezes it; afterwards the repair a refusal asks for cannot be made.
            await self._execution.check_finalizable(status=model_input.status)
```

Test fakes — add to each of `_RecordingFinalization` (`tests/agents/test_finalize_contract.py:213`), `_FinalizingExecution` (`tests/agents/test_runtime.py:320`) and `_ExecutionPort` (`tests/agents/test_ports.py:101`):

```python
    async def check_finalizable(self, *, status: Any) -> None:
        del status
```

(The fakes that subclass the Protocol inherit its no-op body and need nothing.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q tests/agents/test_finalize_contract.py tests/agents/test_runtime.py tests/agents/test_ports.py tests/agents/test_governed_tool_feedback.py tests/api/test_stage0_routing_honesty.py` and `CLUE_DATABASE_URL=<throwaway> uv run pytest -q tests/api/test_agent_runtime_wiring_db.py tests/api/test_specialist_wiring_db.py tests/arv2/test_quality_runtime_db.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/ports.py platform/api/clue_api/agent_execution_wiring.py platform/api/clue_api/agent_runtime_wiring.py tests/agents/test_finalize_contract.py tests/agents/test_runtime.py tests/agents/test_ports.py
git commit -m "Finalize refuses before it freezes outputs, so the requested repair can finish

The unresolved-failed-tools refusal ran after finalize_turn had written outputs/research.json and
frozen outputs/, so the agent's repair-and-retry crashed with WorkspaceConflict (McKee's job ended
needs_review). check_finalizable now runs first; finalize keeps the same check as a backstop."
```

---

### Task 9: Explicit database pool settings; pgbouncer visibility in the runbook

**Files:**
- Modify: `libs/clue-db/clue_db/engine.py:74-90` (`create_engine`)
- Modify: `.env.example` (DB block)
- Modify: `docs/deploy/runbook.md:213-225` (pgbouncer step) and add a "Research capacity and connection checks" subsection after it
- Test: `tests/db/test_db_engine.py`

**Interfaces:**
- Produces: env `CLUE_DB_POOL_SIZE` (default 5), `CLUE_DB_MAX_OVERFLOW` (10), `CLUE_DB_POOL_TIMEOUT_S` (30) read by `create_engine`.

- [ ] **Step 1: Write the failing test**

Append to `tests/db/test_db_engine.py`:

```python
def test_pool_settings_default_to_the_library_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLUE_DB_POOL_SIZE", "CLUE_DB_MAX_OVERFLOW", "CLUE_DB_POOL_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)

    async def check() -> None:
        engine = create_engine()
        try:
            pool = engine.sync_engine.pool
            assert pool.size() == 5  # type: ignore[attr-defined]
            assert pool._max_overflow == 10  # type: ignore[attr-defined]
            assert pool._timeout == 30  # type: ignore[attr-defined]
        finally:
            await engine.dispose()

    run_async(check())


def test_pool_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_DB_POOL_SIZE", "7")
    monkeypatch.setenv("CLUE_DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("CLUE_DB_POOL_TIMEOUT_S", "12")

    async def check() -> None:
        engine = create_engine()
        try:
            pool = engine.sync_engine.pool
            assert pool.size() == 7  # type: ignore[attr-defined]
            assert pool._max_overflow == 3  # type: ignore[attr-defined]
            assert pool._timeout == 12  # type: ignore[attr-defined]
        finally:
            await engine.dispose()

    run_async(check())
```

(Use the `run_async` the file already imports; `create_engine` needs no live database.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/db/test_db_engine.py -k pool_settings`
Expected: the second test FAILS (`assert 5 == 7`).

- [ ] **Step 3: Write the implementation**

In `libs/clue-db/clue_db/engine.py`:

```python
POOL_SIZE_ENV = "CLUE_DB_POOL_SIZE"
MAX_OVERFLOW_ENV = "CLUE_DB_MAX_OVERFLOW"
POOL_TIMEOUT_ENV = "CLUE_DB_POOL_TIMEOUT_S"


def _env_number(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default
```

and in `create_engine`, add to the `create_async_engine(...)` call:

```python
        # Per-process connection pool, explicit rather than a silent library default (research
        # slowness fix 2026-10-03). Behind pgbouncer (transaction mode) a pooled connection
        # holds a real Postgres connection only during a transaction.
        pool_size=int(_env_number(POOL_SIZE_ENV, 5)),
        max_overflow=int(_env_number(MAX_OVERFLOW_ENV, 10)),
        pool_timeout=_env_number(POOL_TIMEOUT_ENV, 30),
```

`.env.example`, next to `CLUE_DATABASE_URL`:

```
# Per-process database connection pool (SQLAlchemy). Defaults are the library's.
CLUE_DB_POOL_SIZE=5
CLUE_DB_MAX_OVERFLOW=10
CLUE_DB_POOL_TIMEOUT_S=30
```

`docs/deploy/runbook.md` — in step 5's pgbouncer block add the line `STATS_USERS=clue_worker` (read-only `SHOW POOLS` / `SHOW STATS` for the app user; confirm the variable name against the `edoburu/pgbouncer` README for tag `v1.23.1-p3`, as the step already says), and add after step 5:

```markdown
**Research capacity and connection checks (2026-10-03).**
- Research jobs run at once, fleet-wide = batch workers × `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS`
  (today 3 × 4 = 12). A worker never claims more research tasks than it can run.
- To see whether transactions wait for a pgbouncer server connection: from a worker container,
  connect to the `pgbouncer` admin database on port 6432 as `clue_worker` and run `SHOW POOLS;`.
  `cl_waiting > 0` for long means the pool is too small.
- `DEFAULT_POOL_SIZE` goes from 20 to 40 **only after** the research slowness fixes are deployed
  and measured: raising it before would let more transactions wait on the same locks. Postgres
  allows 200 connections and the Railway services use about 10. Edit `/srv/clue/pgbouncer.env`,
  then `docker compose up -d pgbouncer` from `/srv/clue/app/deploy/vm` as `clue`.
- Lock waits: sample `pg_stat_activity` for `wait_event_type='Lock'` while research runs, and
  look for `db.critical_section` lines in the batch workers' logs (`docker logs vm-batch1-1`).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q tests/db/test_db_engine.py`
Expected: all pass (the DB-required tests skip without a database).

- [ ] **Step 5: Commit**

```bash
git add libs/clue-db/clue_db/engine.py .env.example docs/deploy/runbook.md tests/db/test_db_engine.py
git commit -m "Explicit database pool settings; runbook: research capacity and pgbouncer checks

Pool size, overflow and timeout are now CLUE_DB_* settings with the library defaults. The runbook
adds a read-only pgbouncer stats user, how to read SHOW POOLS, the fleet-wide research capacity,
and raising the pgbouncer pool from 20 to 40 only after these fixes are deployed and measured."
```

---

### Task 10: Whole-branch verification and the session note

**Files:**
- Modify: `_memory/2026-10-03-production-research-slowness.md` (append an "Implementation" section)

- [ ] **Step 1: Lint and types over every changed package**

Run:
```bash
uv run ruff check libs/clue-obs libs/clue-storage libs/clue-db libs/clue-config platform/fleet platform/agents platform/api/clue_api tests/storage tests/fleet tests/agents tests/arv2 tests/api tests/db tests/clue_obs
uv run ruff format --check $(git diff --name-only origin/research-streaming...HEAD -- '*.py')
uv run mypy libs/clue-obs/clue_obs libs/clue-storage/clue_storage libs/clue-db/clue_db platform/fleet/clue_fleet platform/agents/clue_agents platform/api/clue_api
```
Expected: no errors. Fix anything reported before continuing.

- [ ] **Step 2: Import-linter contracts**

Run: `uv run lint-imports`
Expected: all contracts kept (the S3 SDK is still imported only inside `clue_storage/s3.py`).

- [ ] **Step 3: Focused suites on the throwaway database**

Run (no real API keys exported; `CLUE_DATABASE_URL` = the throwaway DB):
```bash
uv run pytest -q --ignore-glob='*_live.py' tests/storage tests/fleet tests/agents tests/clue_obs tests/db/test_db_engine.py tests/api/test_project_artifact_lock_db.py tests/api/test_research_artifacts_db.py tests/api/test_agent_turn_wiring_db.py tests/api/test_agent_runtime_wiring_db.py tests/api/test_fleet_wiring.py tests/arv2
```
Expected: all pass. Any failure: decide whether it existed before this branch by running the same test on `origin/research-streaming` in a temporary worktree; record pre-existing failures by name in the note, fix new ones.

- [ ] **Step 4: Append the implementation record to the note and commit**

Append to `_memory/2026-10-03-production-research-slowness.md` a section `## Implementation (branch perf/research-slowness-fixes)` listing: the commits of Tasks 1–9 (one line each), the test commands run in Step 3 and their results, any pre-existing failures by name, the residual from Task 5 (recovery path's `index_transcripts` uploads under the lock taken by the recovery publish), and the owed post-deploy measurement (spec §1 success criteria 1–5, the founder triggers the run).

```bash
git add _memory/2026-10-03-production-research-slowness.md
git commit -m "Record the research slowness implementation and its verification"
```
