# Lane 3 slice 2 — the roots — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every production process exports OpenTelemetry spans and Sentry events that carry the run context, the trace started by the HTTP request that enqueues a turn or a job survives into the fleet worker that runs it, and every flag the code reads is in `.env.example` — all off by default.

**Architecture:** One `TracerProvider` per process, built by `clue_obs.otel.install.install_tracing`, becomes both the OTel global provider (for the FastAPI and httpx instrumentors) and `traced_step`'s provider, with a span processor that copies the structlog-bound run context onto every span through `safe_attributes`. `clue_obs.sentry` wraps `sentry_sdk` with the ruled posture. The run context is bound at the roots: a request-context middleware plus the tenant seams in the API, and a per-task wrapper in the fleet worker that also opens a `fleet.task` span as a child of the `traceparent` the enqueue stamped into the payload. `clue_api.production_tracing` composes it at `projections_main` and `fleet_main`.

**Tech Stack:** Python 3.12, opentelemetry-sdk 1.42 + instrumentation 0.63b1 (fastapi, httpx), sentry-sdk 2.x, structlog contextvars, pytest with the repo's rolled-back-connection DB harness, `uv`.

**Spec:** `docs/superpowers/specs/archive/2026-09-15-lane3-slice2-roots-design.md` (D1–D3 ruled 2026-09-15). Parent: `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` §4, §5.1, §5.2, §7, §9 slice 2, §10 items 2, 6, 7, 8.

## Global Constraints

- **Branch.** Work continues on the current branch `lane3/sice1b` (slices 1b's commits are on it). One commit per task, local only, never push; no AI attribution trailer.
- **Database.** This checkout's `.env` names `clue_semarang`, which a LIVE stack uses and which is behind the migration head. Never run tests or alembic against it. DB tests run after `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"` and after confirming `uv run alembic current` prints `d36bc7d32c9a (head)`. No migration is part of this slice.
- **Tests spend no money.** Run only the files each task names; never `make check`, never a broad `pytest`; `--ignore-glob='*_live.py'` when a directory is named. Known ambient `.env` leaks that fail otherwise-green tests when sourced: `CLUE_ARV2_DISCOVERY_ENABLED`, `CLUE_CHAT_REASONING_TRACE_MODE`, `CLUE_FLEET_WORKER_CONCURRENCY`, `CLUE_BRANDFETCH_CLIENT_ID`, the provider keys — strip them with `env -u` when a suite you did not edit fails on one, and report it as pre-existing.
- **Off by default (spec §1).** With every new setting at its shipped default a process behaves exactly as before: no exporter, no Sentry, spans in-process only. The instrumentors are on by default but produce spans that go nowhere without an endpoint.
- **Redaction (R6, §5.1).** Every span attribute passes `safe_attributes`; every Sentry event passes the secret-key redaction; `send_default_pii=False`, `include_local_variables=False`.
- **R9.** No SQLAlchemy / asyncpg / Redis instrumentation; no sampling. **R11 / R12.** Nothing under `subsystems/research/clue_research/**`, `subsystems/clue-design/**`, `apps/frontend/**`; `trial_main` and `handoff_app` untouched.
- **Env parity (founder rule 2026-08-31).** Every new setting appears in `.env.example` with its default the moment its code lands, and in the local `.env` at key parity (secrets and DSNs stay placeholders).
- **Gates per task:** `uv run ruff format <files> && uv run ruff check <files>`, `uv run mypy` (baseline exactly 4 pre-existing errors: `subsystems/design/clue_design/ad_assets.py:149`, `platform/api/clue_api/arv2/account_research_claims.py:1387`, `platform/api/clue_api/arv2/account_research_driver.py:181-182`; gate = no new error), `uv run lint-imports` (26 kept, 0 broken) after any import change.
- **Shell is zsh:** file lists as arrays. Never `git stash`.
- **OTel globals.** `trace.set_tracer_provider` accepts one provider per process (later calls are ignored with a warning) and `HTTPXClientInstrumentor().instrument()` is process-wide; tests pass `set_global=False` / `instrument_httpx=False` unless the test is about them, and uninstrument httpx in a `finally`.

## What the plan discovered (read before Task 1)

1. **No production code binds the run context** (`bind_workspace` etc. have zero callers outside the library docstring), so milestone item 6 is not met today — Task 5 binds it at the roots (D3).
2. The FastAPI instrumentor adds middleware, and Starlette refuses new middleware once the app has started: `instrument_app` must run at app **construction**, so `create_projections_app` takes the tracing runtime and instruments the app it builds; the lifespan only flushes.
3. `.env.example` lacks the three `CLUE_METRICS_*` settings the code reads (a pre-existing parity gap); Task 1 closes it.
4. `clue_fleet` already imports `clue_obs`; the OTel propagation calls live in `clue_obs.otel.propagation` so the fleet package gains no direct OTel import.
5. The existing frontend-read envelope middleware stamps `request.state.request_id` for `/frontend/v1` requests only; the new app-wide middleware reuses that attribute when present, else reads a safe `X-Request-Id`, else generates one, so both agree.
6. The dependency set resolves against the installed 1.42 / 0.63b1 line (`uv pip install --dry-run` on 2026-09-15: 7 packages would install).

## File structure

| File | Responsibility |
| --- | --- |
| `libs/clue-obs/pyproject.toml` | **Modify.** Three new dependencies. |
| `libs/clue-config/clue_config/settings.py`, `secrets.py` | **Modify.** Telemetry settings and secrets. |
| `.env.example`, `.env` | **Modify.** The telemetry block + the metrics gap. |
| `tests/test_telemetry_settings.py` | **Create.** Parity + defaults. |
| `libs/clue-obs/clue_obs/otel/attributes.py` | **Modify.** Run-context attribute keys join the allowlist. |
| `libs/clue-obs/clue_obs/otel/tracing.py` | **Modify.** `use_provider`, `get_tracer`. |
| `libs/clue-obs/clue_obs/otel/install.py` | **Create.** `RunContextSpanProcessor`, `parse_otlp_headers`, `TracingRuntime`, `install_tracing`. |
| `libs/clue-obs/clue_obs/otel/propagation.py` | **Create.** `carrier_from_current_span`, `context_from_carrier`. |
| `libs/clue-obs/clue_obs/otel/__init__.py` | **Modify.** Exports. |
| `tests/test_obs_install.py`, `tests/test_obs_propagation.py` | **Create.** |
| `libs/clue-obs/clue_obs/sentry.py` | **Create.** `install_sentry`, `capture`, `is_installed`. |
| `tests/test_obs_sentry.py` | **Create.** |
| `platform/fleet/clue_fleet/queue.py` | **Modify.** `enqueue_task` stamps the carrier. |
| `platform/fleet/clue_fleet/work_worker.py` | **Modify.** Per-task context + `fleet.task` span + `capture`. |
| `tests/fleet/test_trace_propagation.py`, `tests/fleet/test_trace_propagation_db.py` | **Create.** |
| `platform/api/clue_api/production_tracing.py` | **Create.** Root composition. |
| `platform/api/clue_api/projections_main.py`, `projections_app.py`, `auth_wiring.py`, `agent_turn_submission.py`, `fleet_main.py` | **Modify.** Install at the roots; bind context; capture at sweeps. |
| `tests/api/test_request_context_db.py` | **Create.** |
| `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md`, `docs/superpowers/plans/2026-09-13-lane-plan-index.md` | **Modify.** §3 correction, §7 names, §9 slice 2; index row 2. |
| `_memory/2026-09-15-lane3-slice2-roots.md` | **Create.** Session note (controller). |

---

### Task 1: Dependencies, settings, secrets, env parity

**Files:**
- Modify: `libs/clue-obs/pyproject.toml` (dependencies)
- Modify: `libs/clue-config/clue_config/settings.py` (after the `metrics_*` block ~L169-171; the validator at ~L950)
- Modify: `libs/clue-config/clue_config/secrets.py` (after `gemini_api_key` ~L110)
- Modify: `.env.example` (a new block before `# --- Fleet worker concurrency` ~L241), `.env` (same keys)
- Test: `tests/test_telemetry_settings.py`

**Interfaces:**
- Produces on `Settings`: `otel_traces_endpoint: str | None = None`, `otel_instrument_fastapi: bool = True`, `otel_instrument_httpx: bool = True`, `sentry_enabled: bool = False`, `sentry_environment: str = "lane-san-salvador"`, `release: str | None = None`. On `Secrets`: `sentry_dsn: SecretStr | None = None`, `otel_traces_headers: SecretStr | None = None`. Env names are `CLUE_` + the upper-cased field name.
- Produces the three packages importable: `opentelemetry.instrumentation.fastapi`, `opentelemetry.instrumentation.httpx`, `sentry_sdk`.

- [ ] **Step 1: Add the dependencies**

Run: `uv add --package clue-obs "opentelemetry-instrumentation-fastapi==0.63b1" "opentelemetry-instrumentation-httpx==0.63b1" "sentry-sdk>=2.30"`
Expected: `libs/clue-obs/pyproject.toml` gains the three lines under `dependencies`; `uv.lock` updates; `uv run python -c "import opentelemetry.instrumentation.fastapi, opentelemetry.instrumentation.httpx, sentry_sdk; print('ok')"` prints `ok`. If `uv add` puts them in the wrong table, edit the `dependencies = [...]` list by hand to read (keep the existing entries):

```toml
    "opentelemetry-instrumentation-fastapi==0.63b1",
    "opentelemetry-instrumentation-httpx==0.63b1",
    "sentry-sdk>=2.30",
```

- [ ] **Step 2: Write the failing parity test**

```python
# tests/test_telemetry_settings.py
"""Lane 3 slice 2, Task 1: the telemetry roots' settings ship their defaults and are documented."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Secrets, Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

#: Every slice 2 setting and the default it ships with (plus the three metrics settings the code
#: already read but .env.example did not document — closed by the same parity sweep).
TELEMETRY_SETTING_DEFAULTS: dict[str, object] = {
    "metrics_exporter": "memory",
    "metrics_otlp_endpoint": None,
    "metrics_export_interval_ms": 10_000,
    "otel_traces_endpoint": None,
    "otel_instrument_fastapi": True,
    "otel_instrument_httpx": True,
    "sentry_enabled": False,
    "sentry_environment": "lane-san-salvador",
    "release": None,
}
TELEMETRY_SECRET_FIELDS = ("sentry_dsn", "otel_traces_headers")


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_telemetry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [*TELEMETRY_SETTING_DEFAULTS, *TELEMETRY_SECRET_FIELDS]:
        monkeypatch.delenv(_env_name(name), raising=False)


def test_every_telemetry_setting_ships_its_default(unset_telemetry_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, default in TELEMETRY_SETTING_DEFAULTS.items():
        assert getattr(settings, field_name) == default, field_name


def test_the_telemetry_secrets_are_optional(unset_telemetry_env: None) -> None:
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    for field_name in TELEMETRY_SECRET_FIELDS:
        assert field_name in Secrets.model_fields
        assert getattr(secrets, field_name) is None


def test_every_telemetry_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in TELEMETRY_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        value = documented.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        shipped = "" if default is None else (str(default).lower() if isinstance(default, bool) else str(default))
        assert value == shipped, field_name
    for field_name in TELEMETRY_SECRET_FIELDS:
        assert re.search(rf"^{_env_name(field_name)}=$", text, re.MULTILINE), field_name


def test_an_empty_endpoint_string_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``source .env`` exports ``CLUE_OTEL_TRACES_ENDPOINT=`` as the empty string; the roots
    treat empty as "no exporter", so the setting must load without error."""
    monkeypatch.setenv("CLUE_OTEL_TRACES_ENDPOINT", "")
    monkeypatch.setenv("CLUE_SENTRY_ENABLED", "false")
    assert not Settings(_env_file=None).otel_traces_endpoint
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_telemetry_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'otel_traces_endpoint'` and the parity test's `absent from .env.example` for every name.

- [ ] **Step 4: Add the settings and secrets**

In `libs/clue-config/clue_config/settings.py`, directly after `metrics_export_interval_ms: int = Field(default=10_000, ge=100)`:

```python
    # --- telemetry roots (lane 3 slice 2; all off by default) ------------------------------
    # OTLP/HTTP traces endpoint (slice 3 points it at Langfuse). Empty → spans are created
    # in-process and exported nowhere, today's behaviour. Env: ``CLUE_OTEL_TRACES_ENDPOINT``.
    otel_traces_endpoint: str | None = None
    # Instrument the FastAPI app (server spans) and httpx (client spans) at the roots. On by
    # default because without an endpoint the spans cost nothing and go nowhere.
    # Env: ``CLUE_OTEL_INSTRUMENT_FASTAPI`` / ``CLUE_OTEL_INSTRUMENT_HTTPX``.
    otel_instrument_fastapi: bool = True
    otel_instrument_httpx: bool = True
    # Sentry (R6): installed only when enabled AND ``CLUE_SENTRY_DSN`` (a secret) is set; the
    # roots refuse ``enabled`` with no DSN. ``sentry_environment`` names the deployment posture
    # on every event; ``release`` is the code version (a git sha), empty → unset.
    # Env: ``CLUE_SENTRY_ENABLED`` / ``CLUE_SENTRY_ENVIRONMENT`` / ``CLUE_RELEASE``.
    sentry_enabled: bool = False
    sentry_environment: str = "lane-san-salvador"
    release: str | None = None
```

In `libs/clue-config/clue_config/secrets.py`, directly after `gemini_api_key: SecretStr | None = None`:

```python
    # --- telemetry roots (lane 3 slice 2) ---
    # Env: CLUE_SENTRY_DSN — the Sentry project DSN (it authorises event ingest, so a secret).
    sentry_dsn: SecretStr | None = None
    # Env: CLUE_OTEL_TRACES_HEADERS — "k=v,k2=v2" sent with every OTLP trace export (Langfuse's
    # basic-auth header in slice 3); a secret because it carries the project keys.
    otel_traces_headers: SecretStr | None = None
```

- [ ] **Step 5: Document every name**

Insert into `.env.example` immediately before the line `# --- Fleet worker concurrency (CLUE_FLEET_*; founder ruling 2026-09-10) ------`:

```
# --- Telemetry roots (lane 3 slice 2) — all off by default; an unconfigured process behaves as before ---
# OTLP/HTTP metrics export: the three settings below predate this block (parity sweep 2026-09-15).
CLUE_METRICS_EXPORTER=memory
CLUE_METRICS_OTLP_ENDPOINT=
CLUE_METRICS_EXPORT_INTERVAL_MS=10000
# OTLP/HTTP traces endpoint (slice 3 points it at Langfuse); empty → spans stay in-process.
CLUE_OTEL_TRACES_ENDPOINT=
# Headers sent with every trace export, "k=v,k2=v2" (a secret: Langfuse basic auth in slice 3).
CLUE_OTEL_TRACES_HEADERS=
# Server spans (FastAPI) and client spans (httpx) at the roots; no endpoint → nothing leaves.
CLUE_OTEL_INSTRUMENT_FASTAPI=true
CLUE_OTEL_INSTRUMENT_HTTPX=true
# Sentry cloud (free tier): installed only when enabled AND a DSN is set; PII off, local vars off.
CLUE_SENTRY_ENABLED=false
CLUE_SENTRY_DSN=
CLUE_SENTRY_ENVIRONMENT=lane-san-salvador
# The code version stamped on Sentry events (a git sha); empty → unset.
CLUE_RELEASE=

```

Append the same twelve `KEY=value` lines (no comments needed) to the local `.env` unless a key is already present there (`grep -c '^CLUE_OTEL_TRACES_ENDPOINT=' .env` first; the local `.env` is git-ignored and is never committed).

- [ ] **Step 6: Run the tests and gates**

Run: `uv run pytest tests/test_telemetry_settings.py tests/arv2/test_settings.py tests/arv2/test_onboarding_settings.py -v && uv run ruff format libs/clue-config/clue_config/settings.py libs/clue-config/clue_config/secrets.py tests/test_telemetry_settings.py && uv run ruff check libs/clue-config tests/test_telemetry_settings.py && uv run mypy`
Expected: all PASS (the ARV2 parity tests still pass: this block adds names, removes none); mypy unchanged.

- [ ] **Step 7: Commit**

```bash
git add libs/clue-obs/pyproject.toml uv.lock libs/clue-config/clue_config/settings.py libs/clue-config/clue_config/secrets.py .env.example tests/test_telemetry_settings.py
git commit -m "feat(config): telemetry root settings and secrets, documented at parity; instrumentation and sentry deps

CLUE_OTEL_TRACES_ENDPOINT / _HEADERS, CLUE_OTEL_INSTRUMENT_{FASTAPI,HTTPX}, CLUE_SENTRY_{ENABLED,DSN,ENVIRONMENT}, CLUE_RELEASE — all off by default — plus the three CLUE_METRICS_* names the code already read but .env.example never listed. clue-obs gains the FastAPI/httpx instrumentors and sentry-sdk (lane 3 slice 2)."
```

---

### Task 2: `clue_obs.otel.install` and `clue_obs.otel.propagation`

**Files:**
- Modify: `libs/clue-obs/clue_obs/otel/attributes.py` (new `ATTR_*` constants + `STANDARD_ATTRIBUTES`)
- Modify: `libs/clue-obs/clue_obs/otel/tracing.py` (add `use_provider`, `get_tracer`)
- Create: `libs/clue-obs/clue_obs/otel/install.py`, `libs/clue-obs/clue_obs/otel/propagation.py`
- Modify: `libs/clue-obs/clue_obs/otel/__init__.py` (exports)
- Test: `tests/test_obs_install.py`, `tests/test_obs_propagation.py`

**Interfaces:**
- Consumes: Task 1's packages.
- Produces:
  - `clue_obs.otel.RUN_CONTEXT_KEYS: frozenset[str]` — `{"request_id","workspace_id","project_id","run_id","thread_id","turn_id","job_id","account_id","actor","profile_version","task_id","work_id","fleet_kind","task_attempt","worker_id"}`.
  - `clue_obs.otel.RunContextSpanProcessor` — copies the bound context keys in `RUN_CONTEXT_KEYS` onto every span at start, via `safe_attributes`.
  - `clue_obs.otel.parse_otlp_headers(raw: str | None) -> dict[str, str]` — `"a=b,c=d"` → `{"a": "b", "c": "d"}`; empty/None → `{}`; a pair without `=` → `ValueError`.
  - `clue_obs.otel.TracingRuntime` (frozen dataclass: `provider`, `process_name`, `exporting: bool`) with `instrument_app(app) -> None` and `shutdown() -> None`.
  - `clue_obs.otel.install_tracing(*, process_name, endpoint=None, headers=None, instrument_httpx=True, set_global=True) -> TracingRuntime`.
  - `clue_obs.otel.tracing.use_provider(provider) -> TracerProvider`, `clue_obs.otel.get_tracer() -> Tracer` (the provider behind `traced_step`).
  - `clue_obs.otel.carrier_from_current_span() -> dict[str, str]` (W3C `traceparent`/`tracestate` of the current span, `{}` when none) and `clue_obs.otel.context_from_carrier(carrier: Mapping[str, object]) -> Context | None` (`None` when the carrier holds no `traceparent`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_obs_install.py
"""Lane 3 slice 2, Task 2: one provider per process, run context on every span, both
instrumentors behind one install."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from clue_obs import bound_context
from clue_obs.otel import (
    RUN_CONTEXT_KEYS,
    RunContextSpanProcessor,
    install_tracing,
    parse_otlp_headers,
    traced_step,
)


def _runtime(**kwargs: object):  # type: ignore[no-untyped-def]
    runtime = install_tracing(
        process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=False, **kwargs
    )
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))
    return runtime, exporter


def test_the_processor_copies_only_run_context_keys_through_the_redaction_chokepoint() -> None:
    runtime, exporter = _runtime()
    with bound_context(workspace_id="ws_1", turn_id="turn_1", api_key="sk-secret", note="x"):
        with traced_step("unit"):
            pass
    (span,) = exporter.get_finished_spans()
    assert span.attributes["workspace_id"] == "ws_1"
    assert span.attributes["turn_id"] == "turn_1"
    assert "api_key" not in span.attributes and "note" not in span.attributes
    assert {"workspace_id", "turn_id", "request_id", "fleet_kind"} <= RUN_CONTEXT_KEYS


def test_install_without_an_endpoint_exports_nothing_and_names_the_service() -> None:
    runtime, exporter = _runtime()
    assert runtime.exporting is False
    with traced_step("unit"):
        pass
    (span,) = exporter.get_finished_spans()
    assert span.resource.attributes["service.name"] == "clue-test"
    assert any(isinstance(p, RunContextSpanProcessor) for p in runtime.provider._active_span_processor._span_processors)


def test_httpx_client_spans_nest_under_the_current_span() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    runtime = install_tracing(process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=True)
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        with traced_step("parent") as parent:
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                client.get("https://example.test/ping")
        spans = {s.name: s for s in exporter.get_finished_spans()}
        client_span = next(s for s in spans.values() if s.kind is SpanKind.CLIENT)
        assert client_span.parent is not None
        assert client_span.parent.span_id == parent.get_span_context().span_id
    finally:
        HTTPXClientInstrumentor().uninstrument()


def test_instrument_app_yields_a_server_span_carrying_the_bound_context() -> None:
    runtime, exporter = _runtime()
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "yes"}

    runtime.instrument_app(app)
    with bound_context(request_id="req-1"):
        assert TestClient(app).get("/ping").status_code == 200
    server = next(s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER)
    assert server.attributes.get("http.route") == "/ping"
    assert server.attributes.get("request_id") == "req-1"


def test_parse_otlp_headers() -> None:
    assert parse_otlp_headers("a=b, c=d=e") == {"a": "b", "c": "d=e"}
    assert parse_otlp_headers("") == {} and parse_otlp_headers(None) == {}
    with pytest.raises(ValueError):
        parse_otlp_headers("novalue")
```

```python
# tests/test_obs_propagation.py
"""Lane 3 slice 2, Task 2: the W3C carrier round trip the fleet payload rides on."""

from __future__ import annotations

from opentelemetry import trace

from clue_obs.otel import carrier_from_current_span, collect_spans, context_from_carrier, get_tracer, traced_step


def test_no_current_span_yields_an_empty_carrier() -> None:
    assert carrier_from_current_span() == {}
    assert context_from_carrier({}) is None
    assert context_from_carrier({"turn_id": "x"}) is None


def test_a_carrier_round_trips_the_trace_id() -> None:
    with collect_spans():
        with traced_step("api.request") as parent:
            carrier = carrier_from_current_span()
        assert carrier["traceparent"].startswith("00-")
        restored = context_from_carrier({**carrier, "other": 1})
        assert restored is not None
        with get_tracer().start_as_current_span("fleet.task", context=restored) as child:
            pass
    assert child.get_span_context().trace_id == parent.get_span_context().trace_id
    assert child.parent is not None and child.parent.span_id == parent.get_span_context().span_id
    assert trace.get_current_span().get_span_context().is_valid is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_obs_install.py tests/test_obs_propagation.py -v`
Expected: FAIL with `ImportError: cannot import name 'install_tracing' from 'clue_obs.otel'` (and the propagation names).

- [ ] **Step 3: Extend the attribute allowlist**

In `libs/clue-obs/clue_obs/otel/attributes.py`, after `ATTR_N_SOURCES = "n_sources"` add:

```python
# Run context (lane 3 slice 2) — the ids and enums structlog binds at the roots, copied onto every
# span by ``RunContextSpanProcessor``. Identifiers and closed vocabularies only, never text.
ATTR_REQUEST_ID = "request_id"
ATTR_PROJECT_ID = "project_id"
ATTR_THREAD_ID = "thread_id"
ATTR_TURN_ID = "turn_id"
ATTR_JOB_ID = "job_id"
ATTR_ACCOUNT_ID = "account_id"
ATTR_ACTOR = "actor"
ATTR_PROFILE_VERSION = "profile_version"
ATTR_TASK_ID = "task_id"
ATTR_WORK_ID = "work_id"
ATTR_FLEET_KIND = "fleet_kind"
ATTR_TASK_ATTEMPT = "task_attempt"
ATTR_WORKER_ID = "worker_id"
```

and add all thirteen names to the `STANDARD_ATTRIBUTES` frozenset (after `ATTR_N_SOURCES`). Extend the `SpanAttributes` TypedDict with `request_id: str`, `project_id: str`, `thread_id: str`, `turn_id: UUID | str`, `job_id: UUID | str`, `account_id: UUID | str`, `actor: str`, `profile_version: str`, `task_id: UUID | str`, `work_id: str`, `fleet_kind: str`, `task_attempt: int`, `worker_id: str`.

- [ ] **Step 4: Give `tracing.py` the two seams**

Append to `libs/clue-obs/clue_obs/otel/tracing.py` after `_get_tracer`:

```python
def use_provider(provider: TracerProvider) -> TracerProvider:
    """Make an externally built provider the one behind :func:`traced_step` (the process-root
    install, lane 3 slice 2), so our spans and the instrumentors' spans are one trace."""
    global _provider, _tracer
    _provider = provider
    _tracer = provider.get_tracer(_INSTRUMENTATION)
    return provider


def get_tracer() -> Tracer:
    """The tracer behind :func:`traced_step`, for callers that need a parent ``context``."""
    return _get_tracer()
```

- [ ] **Step 5: Write the two modules**

```python
# libs/clue-obs/clue_obs/otel/install.py
"""The process-root tracing install (lane 3 slice 2).

One :class:`TracerProvider` per process, named after the process, exporting over OTLP/HTTP only
when an endpoint is configured — otherwise spans are created and go nowhere, the library default
since M0.5. The provider becomes both OTel's global provider (the FastAPI and httpx instrumentors
read that) and the one behind :func:`~clue_obs.otel.tracing.traced_step`, so a request span, the
handler's own steps and every outbound HTTP call are one trace. :class:`RunContextSpanProcessor`
copies the structlog-bound run context onto every span through the one redaction chokepoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from clue_obs.otel import tracing
from clue_obs.otel.attributes import (
    ATTR_ACCOUNT_ID,
    ATTR_ACTOR,
    ATTR_FLEET_KIND,
    ATTR_JOB_ID,
    ATTR_PROFILE_VERSION,
    ATTR_PROJECT_ID,
    ATTR_REQUEST_ID,
    ATTR_RUN_ID,
    ATTR_TASK_ATTEMPT,
    ATTR_TASK_ID,
    ATTR_THREAD_ID,
    ATTR_TURN_ID,
    ATTR_WORK_ID,
    ATTR_WORKER_ID,
    ATTR_WORKSPACE_ID,
    safe_attributes,
)

__all__ = [
    "RUN_CONTEXT_KEYS",
    "RunContextSpanProcessor",
    "TracingRuntime",
    "install_tracing",
    "parse_otlp_headers",
]

#: The bound-context keys that ride onto spans (and Sentry tags): identifiers and closed
#: vocabularies the roots bind, never free text.
RUN_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        ATTR_REQUEST_ID,
        ATTR_WORKSPACE_ID,
        ATTR_PROJECT_ID,
        ATTR_RUN_ID,
        ATTR_THREAD_ID,
        ATTR_TURN_ID,
        ATTR_JOB_ID,
        ATTR_ACCOUNT_ID,
        ATTR_ACTOR,
        ATTR_PROFILE_VERSION,
        ATTR_TASK_ID,
        ATTR_WORK_ID,
        ATTR_FLEET_KIND,
        ATTR_TASK_ATTEMPT,
        ATTR_WORKER_ID,
    }
)


def bound_run_context() -> dict[str, object]:
    """The currently bound run context, restricted to :data:`RUN_CONTEXT_KEYS`."""
    bound = structlog.contextvars.get_contextvars()
    return {key: value for key, value in bound.items() if key in RUN_CONTEXT_KEYS}


class RunContextSpanProcessor(SpanProcessor):
    """Copy the bound run context onto every span at start, through ``safe_attributes``."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        attrs = bound_run_context()
        if not attrs:
            return
        for key, value in safe_attributes(attrs).items():
            span.set_attribute(key, value)

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def parse_otlp_headers(raw: str | None) -> dict[str, str]:
    """``"k=v,k2=v2"`` → a header mapping. The value may itself contain ``=`` (base64 padding)."""
    if raw is None or not raw.strip():
        return {}
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"OTLP header pair without a value: {pair!r}")
        headers[key.strip()] = value.strip()
    return headers


@dataclass(frozen=True)
class TracingRuntime:
    """What a root holds after :func:`install_tracing`: the provider, and the two hooks."""

    provider: TracerProvider
    process_name: str
    exporting: bool

    def instrument_app(self, app: Any) -> None:
        """Server spans for one FastAPI app. Call at construction — Starlette refuses new
        middleware once the app has started."""
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=self.provider)

    def shutdown(self) -> None:
        """Flush the batch exporter and stop the provider (graceful shutdown)."""
        self.provider.force_flush()
        self.provider.shutdown()


def install_tracing(
    *,
    process_name: str,
    endpoint: str | None = None,
    headers: Mapping[str, str] | None = None,
    instrument_httpx: bool = True,
    set_global: bool = True,
) -> TracingRuntime:
    """Build the process's provider, make it the one every span uses, instrument httpx.

    ``endpoint`` empty/None → no exporter (spans stay in-process). ``set_global=False`` and
    ``instrument_httpx=False`` are for tests: OTel accepts one global provider per process and
    the httpx instrumentation is process-wide.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": process_name}))
    provider.add_span_processor(RunContextSpanProcessor())
    exporting = bool(endpoint)
    if exporting:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=dict(headers or {})))
        )
    if set_global:
        trace.set_tracer_provider(provider)
    tracing.use_provider(provider)
    if instrument_httpx:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    return TracingRuntime(provider=provider, process_name=process_name, exporting=exporting)
```

```python
# libs/clue-obs/clue_obs/otel/propagation.py
"""W3C trace-context propagation for the fleet payload (lane 3 slice 2, D1).

The API stamps the carrier of its current span into the task payload at enqueue; the worker
restores it as the parent of its ``fleet.task`` span. Kept here so ``clue_fleet`` imports only
``clue_obs``.
"""

from __future__ import annotations

from collections.abc import Mapping

from opentelemetry import propagate, trace
from opentelemetry.context import Context

__all__ = ["CARRIER_KEYS", "carrier_from_current_span", "context_from_carrier"]

#: The two W3C keys the carrier may hold.
CARRIER_KEYS: tuple[str, ...] = ("traceparent", "tracestate")


def carrier_from_current_span() -> dict[str, str]:
    """The current span's W3C carrier, or ``{}`` when no valid span is current."""
    if not trace.get_current_span().get_span_context().is_valid:
        return {}
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {key: value for key, value in carrier.items() if key in CARRIER_KEYS}


def context_from_carrier(carrier: Mapping[str, object]) -> Context | None:
    """The remote parent context a carrier names, or ``None`` when it holds no ``traceparent``."""
    subset = {
        key: value for key, value in carrier.items() if key in CARRIER_KEYS and isinstance(value, str)
    }
    if "traceparent" not in subset:
        return None
    return propagate.extract(subset)
```

In `libs/clue-obs/clue_obs/otel/__init__.py` add the imports

```python
from clue_obs.otel.install import (
    RUN_CONTEXT_KEYS,
    RunContextSpanProcessor,
    TracingRuntime,
    install_tracing,
    parse_otlp_headers,
)
from clue_obs.otel.propagation import CARRIER_KEYS, carrier_from_current_span, context_from_carrier
```

change the tracing import line to `from clue_obs.otel.tracing import apply_attributes, configure_tracing, get_tracer, traced, traced_step, use_provider`, and add to `__all__` (a new `# roots (lane 3 slice 2)` group after the tracing group): `"get_tracer"`, `"use_provider"`, `"RUN_CONTEXT_KEYS"`, `"RunContextSpanProcessor"`, `"TracingRuntime"`, `"install_tracing"`, `"parse_otlp_headers"`, `"CARRIER_KEYS"`, `"carrier_from_current_span"`, `"context_from_carrier"`. Also export the thirteen new `ATTR_*` names from `attributes` where the file already re-exports the others.

Circular import check: `install.py` imports `clue_obs.otel.tracing` (module) and `attributes`; `__init__` imports `install` after `tracing` — keep that order.

- [ ] **Step 6: Run the tests and gates**

Run: `uv run pytest tests/test_obs_install.py tests/test_obs_propagation.py tests/test_obs_tracing.py tests/test_obs_attributes.py tests/test_obs_spans.py -v && uv run ruff format libs/clue-obs/clue_obs/otel tests/test_obs_install.py tests/test_obs_propagation.py && uv run ruff check libs/clue-obs tests/test_obs_install.py tests/test_obs_propagation.py && uv run mypy && uv run lint-imports`
Expected: all PASS; mypy unchanged (the two new modules are strict-clean); import-linter 26/0.

- [ ] **Step 7: Commit**

```bash
git add libs/clue-obs/clue_obs/otel/attributes.py libs/clue-obs/clue_obs/otel/tracing.py libs/clue-obs/clue_obs/otel/install.py libs/clue-obs/clue_obs/otel/propagation.py libs/clue-obs/clue_obs/otel/__init__.py tests/test_obs_install.py tests/test_obs_propagation.py
git commit -m "feat(obs): install_tracing — one provider per process, run context on every span, httpx and FastAPI instrumented; W3C carrier helpers

The root builds one TracerProvider (OTLP only when an endpoint is set) that is both OTel's global and traced_step's, so instrumentor spans and our own are one trace; RunContextSpanProcessor copies the bound run context through safe_attributes; carrier_from_current_span / context_from_carrier are the fleet payload's propagation seam (lane 3 slice 2)."
```

---

### Task 3: `clue_obs.sentry`

**Files:**
- Create: `libs/clue-obs/clue_obs/sentry.py`
- Modify: `libs/clue-obs/clue_obs/__init__.py` (export `capture`, `install_sentry`, `sentry_is_installed`)
- Test: `tests/test_obs_sentry.py`

**Interfaces:**
- Consumes: Task 2's `RUN_CONTEXT_KEYS` / `bound_run_context`; `clue_obs.redact.redact_value`.
- Produces: `install_sentry(*, dsn: str | None, environment: str, release: str | None, process_name: str, transport: Any = None) -> bool` (False and nothing initialised when `dsn` is empty); `capture(exc: BaseException) -> None` (no-op unless installed); `sentry_is_installed() -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_obs_sentry.py
"""Lane 3 slice 2, Task 3: Sentry with the ruled posture — ids as tags, never customer text."""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.transport import Transport

from clue_obs import bound_context
from clue_obs.sentry import capture, install_sentry, sentry_is_installed


class StubTransport(Transport):
    def __init__(self, options: Any = None) -> None:
        super().__init__(options)
        self.envelopes: list[Any] = []

    def capture_envelope(self, envelope: Any) -> None:
        self.envelopes.append(envelope)


def test_no_dsn_installs_nothing_and_capture_is_a_noop() -> None:
    assert install_sentry(dsn=None, environment="t", release=None, process_name="p") is False
    assert install_sentry(dsn="  ", environment="t", release=None, process_name="p") is False
    capture(RuntimeError("ignored"))  # must not raise


def test_an_event_carries_the_bound_ids_as_tags_no_locals_and_redacted_extras() -> None:
    transport = StubTransport()
    assert install_sentry(
        dsn="https://public@o0.ingest.sentry.io/1",
        environment="lane-test",
        release="abc123",
        process_name="clue-test",
        transport=transport,
    )
    assert sentry_is_installed()
    try:
        with bound_context(workspace_id="ws_1", turn_id="turn_1", api_key="sk-secret"):
            with sentry_sdk.new_scope() as scope:
                scope.set_extra("api_key", "sk-secret")
                scope.set_extra("count", 3)
                try:
                    raise RuntimeError("boom")
                except RuntimeError as exc:
                    capture(exc)
        sentry_sdk.flush(timeout=5)
        events = [env.get_event() for env in transport.envelopes if env.get_event() is not None]
        assert len(events) == 1
        event = events[0]
        assert event["environment"] == "lane-test" and event["release"] == "abc123"
        assert event["tags"]["workspace_id"] == "ws_1" and event["tags"]["turn_id"] == "turn_1"
        assert "api_key" not in event["tags"]
        assert event["extra"]["api_key"] != "sk-secret"
        assert event["extra"]["count"] == 3
        frames = event["exception"]["values"][0]["stacktrace"]["frames"]
        assert all("vars" not in frame for frame in frames)
    finally:
        sentry_sdk.get_global_scope().set_client(None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_obs_sentry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clue_obs.sentry'`.

- [ ] **Step 3: Write the module**

```python
# libs/clue-obs/clue_obs/sentry.py
"""Sentry at the process roots (lane 3 slice 2, R6).

Errors leave the box with our ids and a stack trace, never customer text: PII capture off, local
variables off, the secret-key redaction over the event's extras and request, and the bound run
context copied onto the tags so an error opens to its workspace, run and turn. Sentry gets no
tracing (R7: OpenTelemetry owns that). Nothing here runs unless :func:`install_sentry` was given
a DSN; :func:`capture` is then a one-liner the worker loops call beside their ``log.exception``.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk

from clue_obs.otel.install import bound_run_context
from clue_obs.redact import redact_value

__all__ = ["capture", "install_sentry", "sentry_is_installed"]

_installed = False


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    del hint
    tags = dict(event.get("tags") or {})
    for key, value in bound_run_context().items():
        if value is not None:
            tags[key] = str(value)
    if tags:
        event["tags"] = tags
    for section in ("extra", "contexts", "request"):
        value = event.get(section)
        if isinstance(value, dict):
            event[section] = redact_value(value)
    return event


def install_sentry(
    *,
    dsn: str | None,
    environment: str,
    release: str | None,
    process_name: str,
    transport: Any = None,
) -> bool:
    """Initialise the SDK with the ruled posture. Returns ``False`` (and does nothing) without a
    DSN. ``transport`` is the test seam (a stub that records envelopes)."""
    global _installed
    if dsn is None or not dsn.strip():
        return False
    sentry_sdk.init(
        dsn=dsn.strip(),
        environment=environment,
        release=release or None,
        server_name=process_name,
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=0.0,
        before_send=_before_send,
        transport=transport,
    )
    _installed = True
    return True


def sentry_is_installed() -> bool:
    return _installed


def capture(exc: BaseException) -> None:
    """Report one caught exception; a no-op when Sentry is not installed."""
    if _installed:
        sentry_sdk.capture_exception(exc)
```

Export from `libs/clue-obs/clue_obs/__init__.py`: add `from clue_obs.sentry import capture, install_sentry, sentry_is_installed` beside the other imports and the three names to `__all__` (alphabetical). If importing `clue_obs.sentry` at package import creates a cycle through `clue_obs.otel.install` (which imports `clue_obs.otel.tracing`), import `bound_run_context` lazily inside `_before_send` instead.

- [ ] **Step 4: Run the tests and gates**

Run: `uv run pytest tests/test_obs_sentry.py tests/test_obs_install.py tests/test_obs_logging.py -v && uv run ruff format libs/clue-obs/clue_obs/sentry.py libs/clue-obs/clue_obs/__init__.py tests/test_obs_sentry.py && uv run ruff check libs/clue-obs tests/test_obs_sentry.py && uv run mypy && uv run lint-imports`
Expected: all PASS. If `redact_value` returns the masked mapping under a different marker than `"***"`, the test's `!= "sk-secret"` still holds. If sentry-sdk's stub transport API differs (`capture_envelope` signature), adapt the stub, not the module.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-obs/clue_obs/sentry.py libs/clue-obs/clue_obs/__init__.py tests/test_obs_sentry.py
git commit -m "feat(obs): install_sentry with the ruled posture — PII off, locals off, no tracing, ids as tags, secrets redacted

capture(exc) is the one-liner the worker loops call beside log.exception; nothing runs without a DSN (lane 3 slice 2, R6)."
```

---

### Task 4: The fleet carries the trace and binds the run context per task

**Files:**
- Modify: `platform/fleet/clue_fleet/queue.py:384-420` (`enqueue_task`)
- Modify: `platform/fleet/clue_fleet/work_worker.py` (`_run_task` ~L285-350; the three catch sites at ~L225, ~L259, ~L342; imports)
- Test: `tests/fleet/test_trace_propagation.py`, `tests/fleet/test_trace_propagation_db.py`

**Interfaces:**
- Consumes: Task 2's `carrier_from_current_span`, `context_from_carrier`, `get_tracer`, `safe_attributes`; Task 3's `capture`; `clue_obs.bound_context`.
- Produces: `enqueue_task` stamps `traceparent` (and `tracestate` when present) into the payload when a valid span is current, never overwriting a key the caller set; the worker runs `handler.handle(context)` inside `bound_context(task_id=, work_id=, fleet_kind=, task_attempt=, worker_id=, + payload ids)` and a `fleet.task` span parented on the payload's carrier; `capture(exc)` at the three catch sites. `PAYLOAD_CONTEXT_KEYS: tuple[str, ...] = ("workspace_id", "project_id", "run_id", "job_id", "turn_id", "thread_id", "account_id")` exported from `clue_fleet.work_worker`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/fleet/test_trace_propagation.py
"""Lane 3 slice 2, Task 4 (offline): the worker runs every handler inside the task's trace and
run context. Uses the fakes the worker's own tests use."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from opentelemetry import trace
from pydantic import JsonValue

from clue_fleet import (
    FleetTaskKind,
    FleetTaskRow,
    FleetTaskStatus,
    LeasedWorkWorker,
    WorkContext,
    WorkResult,
)
from clue_fleet.work_worker import PAYLOAD_CONTEXT_KEYS
from clue_obs.otel import carrier_from_current_span, collect_spans, traced_step
from tests.fleet.test_work_worker import _Leases, _Queue


class _Seeing:
    kind = FleetTaskKind.AGENT_TURN

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    async def handle(self, context: WorkContext) -> WorkResult:
        self.seen.append(
            {
                "trace_id": trace.get_current_span().get_span_context().trace_id,
                "bound": dict(structlog.contextvars.get_contextvars()),
            }
        )
        return WorkResult(outcome="done", references={})


def _row(payload: dict[str, JsonValue]) -> FleetTaskRow:
    now = datetime.now(UTC)
    return FleetTaskRow(
        task_id=uuid4(), kind=FleetTaskKind.AGENT_TURN, project_run_id="run-1", dedup_key="d",
        priority=0, status=FleetTaskStatus.QUEUED, attempts=2, payload=payload, result_ref={},
        claimed_by=None, claimed_at=None, available_at=now, enqueued_at=now, enqueue_seq=1, updated_at=now,
    )


def _drain(handler: _Seeing, row: FleetTaskRow) -> None:
    worker = LeasedWorkWorker(
        handlers=(handler,), queue=_Queue([row]), leases=_Leases(), worker_id="w1",
        poll_interval=timedelta(0), lease_ttl=timedelta(seconds=30), heartbeat_interval=timedelta(seconds=10),
    )
    asyncio.run(worker.drain_once())


def test_the_handler_runs_inside_the_payloads_trace_and_the_bound_context() -> None:
    handler = _Seeing()
    with collect_spans() as exporter:
        with traced_step("api.request") as api_span:
            carrier = carrier_from_current_span()
        row = _row({**carrier, "turn_id": "turn-1", "workspace_id": "ws-1", "thread_id": "thr-1"})
        _drain(handler, row)
    (seen,) = handler.seen
    assert seen["trace_id"] == api_span.get_span_context().trace_id
    bound = seen["bound"]
    assert bound["fleet_kind"] == "agent_turn" and bound["task_attempt"] == 2
    assert bound["turn_id"] == "turn-1" and bound["workspace_id"] == "ws-1" and bound["thread_id"] == "thr-1"
    assert bound["task_id"] == str(row.task_id) and bound["worker_id"] == "w1"
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert fleet_span.parent is not None and fleet_span.parent.span_id == api_span.get_span_context().span_id
    assert fleet_span.attributes["fleet_kind"] == "agent_turn"
    assert structlog.contextvars.get_contextvars().get("turn_id") is None  # cleared after


def test_a_payload_without_a_carrier_starts_a_fresh_trace() -> None:
    handler = _Seeing()
    with collect_spans() as exporter:
        _drain(handler, _row({"turn_id": "turn-2", "workspace_id": "ws-1"}))
    (seen,) = handler.seen
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert fleet_span.parent is None
    assert seen["trace_id"] == fleet_span.get_span_context().trace_id
    assert set(PAYLOAD_CONTEXT_KEYS) >= {"workspace_id", "turn_id", "job_id", "run_id"}
```

(`LeasedWorkWorker`'s constructor keyword names are the ones `tests/fleet/test_work_worker.py` uses — read that file's worker construction and match them exactly; `_Queue` and `_Leases` are its fakes.)

```python
# tests/fleet/test_trace_propagation_db.py
"""Lane 3 slice 2, Task 4 (DB): enqueue stamps the carrier into payload_json; a payload with
no current span is unchanged."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_core import ProjectRunId, decode_jsonb
from clue_fleet import FleetTaskKind, enqueue_task
from clue_obs.otel import collect_spans, traced_step
from tests.fleet.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_fleet_db")


def _payload_for(dedup: str) -> object:
    async def scenario() -> object:
        async with rollback_conn() as conn:
            await enqueue_task(
                conn,
                kind=FleetTaskKind.AGENT_TURN,
                project_run_id=ProjectRunId(f"run-{dedup}"),
                dedup_key=dedup,
                payload={"turn_id": "turn-1", "workspace_id": "ws-1"},
            )
            raw = (
                await conn.execute(
                    text("SELECT payload_json FROM fleet_task WHERE dedup_key = :d"), {"d": dedup}
                )
            ).scalar_one()
            return decode_jsonb(raw)

    return run_async(scenario())


def test_enqueue_under_a_span_stamps_the_carrier() -> None:
    with collect_spans():
        with traced_step("api.request") as span:
            payload = _payload_for(f"trace-{uuid4().hex[:8]}")
    assert isinstance(payload, dict)
    assert payload["turn_id"] == "turn-1"
    trace_hex = f"{span.get_span_context().trace_id:032x}"
    assert str(payload["traceparent"]).startswith(f"00-{trace_hex}-")


def test_enqueue_without_a_span_leaves_the_payload_alone() -> None:
    payload = _payload_for(f"plain-{uuid4().hex[:8]}")
    assert payload == {"turn_id": "turn-1", "workspace_id": "ws-1"}
```

(`ProjectRunId` is the type `enqueue_task` takes; if the fleet conftest exposes a `require_fleet_db` fixture under a different name, use that name — see `tests/fleet/test_fleet_db.py`'s marker.)

- [ ] **Step 2: Run them to verify they fail**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/fleet/test_trace_propagation.py tests/fleet/test_trace_propagation_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'PAYLOAD_CONTEXT_KEYS'`, and the DB carrier test's `KeyError: 'traceparent'`.

- [ ] **Step 3: Stamp the carrier at enqueue**

In `platform/fleet/clue_fleet/queue.py` add `from clue_obs.otel import carrier_from_current_span` to the imports and, in `enqueue_task`, replace `"payload": serialize_value_json(payload if payload is not None else {}),` with

```python
                "payload": serialize_value_json(_with_trace_carrier(payload)),
```

and add above `enqueue_task`:

```python
def _with_trace_carrier(payload: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    """The payload plus the current span's W3C carrier (lane 3 slice 2, D1).

    Stamped only when a valid span is current, and never over a key the caller set, so an enqueue
    outside any trace writes exactly the payload it was given.
    """
    stamped: dict[str, JsonValue] = dict(payload) if payload is not None else {}
    for key, value in carrier_from_current_span().items():
        stamped.setdefault(key, value)
    return stamped
```

- [ ] **Step 4: Wrap the handler in the worker**

In `platform/fleet/clue_fleet/work_worker.py` add imports:

```python
from clue_obs import bound_context, get_logger
from clue_obs.otel import context_from_carrier, get_tracer, safe_attributes
from clue_obs.sentry import capture
```

(replace the existing `from clue_obs import get_logger`). Add after `WorkResult`:

```python
#: Payload keys copied into the bound run context for every task, when present and non-empty
#: strings. Every kind's payload names its subject with these keys already; no handler changes.
PAYLOAD_CONTEXT_KEYS: tuple[str, ...] = (
    "workspace_id",
    "project_id",
    "run_id",
    "job_id",
    "turn_id",
    "thread_id",
    "account_id",
)
```

and add `"PAYLOAD_CONTEXT_KEYS"` to the module's `__all__` if it has one. In `_run_task` replace `work = asyncio.create_task(handler.handle(context))` with `work = asyncio.create_task(self._handle_in_context(handler, context, task))` and add the method:

```python
    async def _handle_in_context(
        self, handler: WorkHandler, context: WorkContext, task: WorkTaskRow
    ) -> WorkResult:
        """Run the handler inside the task's trace and run context (lane 3 slice 2).

        The bound context (task, kind, attempt, worker, and the payload's subject ids) rides onto
        every log line, every span (``RunContextSpanProcessor``) and every Sentry tag for the
        whole handle; the ``fleet.task`` span is a child of the ``traceparent`` the enqueue stamped
        into the payload, so the request that queued the work and the worker that runs it are one
        trace. No carrier → a fresh trace, still stamped.
        """
        bound: dict[str, object] = {
            "task_id": str(task.task_id),
            "work_id": str(task.work_id),
            "fleet_kind": task.kind.value,
            "task_attempt": task.attempts,
            "worker_id": self.worker_id,
        }
        for key in PAYLOAD_CONTEXT_KEYS:
            value = task.payload.get(key)
            if isinstance(value, str) and value:
                bound[key] = value
        parent = context_from_carrier(task.payload)
        with bound_context(**bound):
            with get_tracer().start_as_current_span(
                "fleet.task", context=parent, attributes=safe_attributes(bound)
            ):
                return await handler.handle(context)
```

At the three catch sites, bind the exception and report it: in `_drain_loop` change `except Exception:` (the `worker.slot_crashed` one) to `except Exception as exc:` and add `capture(exc)` after the `log.exception(...)` line; in `_run_task`'s `except Exception:` (`worker.work_error`) likewise `except Exception as exc:` + `capture(exc)` after the log call; where `heartbeat.exception()` is logged as `worker.heartbeat_crashed`, add `capture(error)` after that `log.error(...)`.

- [ ] **Step 5: Run the tests and gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; env -u CLUE_FLEET_WORKER_CONCURRENCY uv run pytest tests/fleet/test_trace_propagation.py tests/fleet/test_trace_propagation_db.py tests/fleet/test_work_worker.py tests/fleet/test_worker_loop.py tests/fleet/test_fleet_db.py -v --ignore-glob='*_live.py' && uv run ruff format platform/fleet/clue_fleet/queue.py platform/fleet/clue_fleet/work_worker.py tests/fleet/test_trace_propagation.py tests/fleet/test_trace_propagation_db.py && uv run ruff check platform/fleet tests/fleet/test_trace_propagation.py tests/fleet/test_trace_propagation_db.py && uv run mypy && uv run lint-imports`
Expected: all PASS; the existing worker tests are untouched by the wrapper (their fakes see the same `WorkContext`); import-linter 26/0 (`clue_fleet` imports only `clue_obs`).

- [ ] **Step 6: Commit**

```bash
git add platform/fleet/clue_fleet/queue.py platform/fleet/clue_fleet/work_worker.py tests/fleet/test_trace_propagation.py tests/fleet/test_trace_propagation_db.py
git commit -m "feat(fleet): the task payload carries the enqueuing span's traceparent; the worker runs every handler in that trace and its run context

enqueue_task stamps the W3C carrier only under a live span; the worker binds task/kind/attempt/worker and the payload's subject ids, opens fleet.task as the carrier's child, and reports its catch-site failures to Sentry (lane 3 slice 2, D1)."
```

---

### Task 5: The roots — install, bind, flush

**Files:**
- Create: `platform/api/clue_api/production_tracing.py`
- Modify: `platform/api/clue_api/projections_main.py` (`build_application`), `platform/api/clue_api/projections_app.py` (`create_projections_app` signature + middleware + `header_workspace_resolver` + `_projections_lifespan`), `platform/api/clue_api/auth_wiring.py` (`_request_id` → public `request_id_for`; the `workspace()` dependency binds), `platform/api/clue_api/agent_turn_submission.py` (~L534 bind), `platform/api/clue_api/fleet_main.py` (`_serve`; five sweep catch sites)
- Test: `tests/api/test_request_context_db.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `install_production_tracing(settings, secrets, *, service_name) -> TracingRuntime`; `install_production_sentry(settings, secrets, *, service_name) -> bool` (raises `RuntimeError` when enabled without a DSN); `production_tracing_lifespan(runtime: TracingRuntime | None)` async context manager; `create_projections_app(..., tracing: TracingRuntime | None = None)`; `auth_wiring.request_id_for(request) -> str`; `REQUEST_CONTEXT_HEADER = "X-Request-Id"` (the existing constant).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_request_context_db.py
"""Lane 3 slice 2, Task 5: a request through the projections app binds its request id and
workspace, echoes the id, and (when the app is instrumented) its server span carries them."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_obs.otel import install_tracing
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _app(conn: AsyncConnection, tracing: Any = None):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
        tracing=tracing,
    )


def test_the_request_id_is_echoed_and_a_safe_incoming_one_is_kept() -> None:
    async def scenario() -> tuple[str, str]:
        async with rollback_conn(seed_pack=False) as conn:
            async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn)), base_url="http://t") as client:
                kept = await client.get(
                    "/cost/report", headers={"X-Workspace-Id": "ws_ctx", "X-Request-Id": "req-abc.1"}
                )
                minted = await client.get("/cost/report", headers={"X-Workspace-Id": "ws_ctx"})
            return kept.headers["X-Request-Id"], minted.headers["X-Request-Id"]

    kept, minted = run_async(scenario())
    assert kept == "req-abc.1"
    assert len(minted) == 32 and minted != kept


def test_the_server_span_carries_the_bound_request_and_workspace_ids() -> None:
    runtime = install_tracing(process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=False)
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            app = _app(conn, tracing=runtime)
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                response = await client.get(
                    "/cost/report", headers={"X-Workspace-Id": "ws_span", "X-Request-Id": "req-span"}
                )
                assert response.status_code == 200

    run_async(scenario())
    server = next(s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER)
    assert server.attributes.get("request_id") == "req-span"
    assert server.attributes.get("workspace_id") == "ws_span"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_request_context_db.py -v`
Expected: FAIL — `TypeError: create_projections_app() got an unexpected keyword argument 'tracing'`.

- [ ] **Step 3: The root composition module**

```python
# platform/api/clue_api/production_tracing.py
"""Process lifecycle for tracing and error reporting at the roots (lane 3 slice 2).

Beside :mod:`clue_api.production_metrics`: the root reads the settings once, installs the
process's tracer provider (and Sentry when enabled), and flushes on graceful shutdown. Every
switch is off by default, so an unconfigured process behaves exactly as before.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from clue_config import Secrets, Settings
from clue_obs import get_logger, install_sentry
from clue_obs.otel import TracingRuntime, install_tracing, parse_otlp_headers

__all__ = [
    "install_production_sentry",
    "install_production_tracing",
    "production_tracing_lifespan",
]

log = get_logger("clue_api.tracing")


def install_production_tracing(
    settings: Settings, secrets: Secrets, *, service_name: str
) -> TracingRuntime:
    """Install the process's tracer provider from the settings; exports only with an endpoint."""
    raw_headers = (
        secrets.otel_traces_headers.get_secret_value()
        if secrets.otel_traces_headers is not None
        else None
    )
    endpoint = (settings.otel_traces_endpoint or "").strip() or None
    runtime = install_tracing(
        process_name=service_name,
        endpoint=endpoint,
        headers=parse_otlp_headers(raw_headers),
        instrument_httpx=settings.otel_instrument_httpx,
    )
    log.info(
        "tracing.installed",
        service_name=service_name,
        exporting=runtime.exporting,
        instrument_httpx=settings.otel_instrument_httpx,
        instrument_fastapi=settings.otel_instrument_fastapi,
    )
    return runtime


def install_production_sentry(settings: Settings, secrets: Secrets, *, service_name: str) -> bool:
    """Install Sentry when enabled. Enabled with no DSN refuses loudly at composition."""
    dsn = secrets.sentry_dsn.get_secret_value().strip() if secrets.sentry_dsn is not None else ""
    if not settings.sentry_enabled:
        log.info("sentry.not_installed", reason="CLUE_SENTRY_ENABLED is off")
        return False
    if not dsn:
        raise RuntimeError("CLUE_SENTRY_ENABLED=true requires CLUE_SENTRY_DSN")
    installed = install_sentry(
        dsn=dsn,
        environment=settings.sentry_environment,
        release=settings.release or None,
        process_name=service_name,
    )
    log.info(
        "sentry.installed",
        service_name=service_name,
        environment=settings.sentry_environment,
        release=settings.release or None,
    )
    return installed


@asynccontextmanager
async def production_tracing_lifespan(runtime: TracingRuntime | None) -> AsyncIterator[None]:
    """Flush and stop the provider on graceful shutdown; ``None`` is a process without one."""
    try:
        yield
    finally:
        if runtime is not None:
            runtime.shutdown()
            log.info("tracing.stopped", service_name=runtime.process_name)
```

- [ ] **Step 4: Wire the API root**

`platform/api/clue_api/auth_wiring.py`: rename `_request_id` to `request_id_for` (public; keep the body), update its callers in the file, add `"request_id_for"` to `__all__` if present. In the `workspace(...)` dependency returned by the authenticated resolver factory (the function that returns `principal.workspace_id`), bind before returning:

```python
    async def workspace(
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
    ) -> str:
        bind_workspace(principal.workspace_id)
        return principal.workspace_id
```

with `from clue_obs import bind_workspace` in the imports.

`platform/api/clue_api/projections_app.py`:
- imports: `from clue_obs import bind_workspace, bound_context` (extend the existing `clue_obs` import as needed), `from clue_obs.otel import TracingRuntime`, and `from clue_api.auth_wiring import REQUEST_ID_HEADER, request_id_for` (extend the existing `auth_wiring` import block).
- `header_workspace_resolver`: before `return x_workspace_id` add `bind_workspace(x_workspace_id)`.
- `create_projections_app(...)`: add the keyword parameter `tracing: TracingRuntime | None = None` (document: "the process's tracer runtime; when given and the settings ask for it, the app is instrumented at construction"). After `app.state.settings = resolved` add:

```python
    app.state.tracing = tracing
    if tracing is not None and resolved.otel_instrument_fastapi:
        # Lane 3 slice 2: server spans. At construction on purpose — Starlette refuses new
        # middleware once the app has started.
        tracing.instrument_app(app)

    @app.middleware("http")
    async def _request_context(request: Any, call_next: Any) -> Any:
        """Bind the request id for the whole request (log lines, span attributes, Sentry tags)
        and echo it. The frontend-read envelope middleware, when it runs first, has already
        minted one on ``request.state``; a safe incoming ``X-Request-Id`` is kept; else new."""
        existing = getattr(request.state, "request_id", None)
        request_id = existing if isinstance(existing, str) else request_id_for(request)
        request.state.request_id = request_id
        with bound_context(request_id=request_id):
            response = await call_next(request)
        response.headers.setdefault(REQUEST_ID_HEADER, request_id)
        return response
```

- `_projections_lifespan`: wrap the existing `async with (...)` block's contents so it also enters `production_tracing_lifespan(getattr(_app.state, "tracing", None))` (import it from `clue_api.production_tracing`), placed first in the `async with (...)` tuple so it is exited last.

`platform/api/clue_api/projections_main.py` `build_application()`: where the settings and secrets are resolved (read the function; it already builds `resolved`/`resolved_secrets`), add right after them:

```python
    tracing = install_production_tracing(resolved, resolved_secrets, service_name="clue-projections-api")
    install_production_sentry(resolved, resolved_secrets, service_name="clue-projections-api")
```

and pass `tracing=tracing` into `create_projections_app(...)`; import `install_production_sentry, install_production_tracing` from `clue_api.production_tracing`.

`platform/api/clue_api/agent_turn_submission.py`: after `turn_id = UUID(str(row["turn_id"]))` (before the payload is built) add `bind_context(project_id=str(row["project_id"]), thread_id=thread_id, turn_id=str(turn_id))` with `from clue_obs import bind_context` in the imports (extend the existing `clue_obs` import).

- [ ] **Step 5: Wire the fleet root**

In `platform/api/clue_api/fleet_main.py` `_serve()`: after `secrets = Secrets()` and `assert_product_path_composition(settings, secrets)` add

```python
    tracing = install_production_tracing(settings, secrets, service_name="clue-worker-fleet")
    install_production_sentry(settings, secrets, service_name="clue-worker-fleet")
```

and make the `async with (` tuple start with `production_tracing_lifespan(tracing),`. Imports: `from clue_api.production_tracing import install_production_sentry, install_production_tracing, production_tracing_lifespan` and `from clue_obs.sentry import capture`. At the five sweep catch sites (`fleet.orphan_sweep.error`, `fleet.stream_token_sweep.error`, `fleet.chat_sweep.error`, `fleet.agent_cleanup.error`, `fleet.external_research.wake_error`) change `except Exception:` to `except Exception as exc:` and add `capture(exc)` after the `log.warning(...)`.

- [ ] **Step 6: Run the tests and gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; env -u CLUE_CHAT_REASONING_TRACE_MODE -u CLUE_FLEET_WORKER_CONCURRENCY -u CLUE_ARV2_DISCOVERY_ENABLED -u CLUE_EXA_API_KEY -u CLUE_OPENROUTER_API_KEY uv run pytest tests/api/test_request_context_db.py tests/api/test_projections_app.py tests/api/test_fleet_wiring.py tests/api/test_cost_report_endpoint_db.py tests/api/test_frontend_read_display_pages_db.py -v --ignore-glob='*_live.py' && uv run python -c "import clue_api.projections_main" && uv run ruff format platform/api/clue_api/production_tracing.py platform/api/clue_api/projections_main.py platform/api/clue_api/projections_app.py platform/api/clue_api/auth_wiring.py platform/api/clue_api/agent_turn_submission.py platform/api/clue_api/fleet_main.py tests/api/test_request_context_db.py && uv run ruff check platform/api/clue_api tests/api/test_request_context_db.py && uv run mypy && uv run lint-imports`
Expected: all PASS. `import clue_api.projections_main` builds the app at import with the shipped defaults (no endpoint, Sentry off) and must not raise; if it needs env this checkout lacks, run it after the `.env` preamble.

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/production_tracing.py platform/api/clue_api/projections_main.py platform/api/clue_api/projections_app.py platform/api/clue_api/auth_wiring.py platform/api/clue_api/agent_turn_submission.py platform/api/clue_api/fleet_main.py tests/api/test_request_context_db.py
git commit -m "feat(roots): tracing and Sentry installed at the platform API and fleet worker; request id and workspace bound per request; turn ids bound at submission

install_production_tracing / install_production_sentry / production_tracing_lifespan beside the metrics lifespan; the app is instrumented at construction; the request-context middleware binds and echoes X-Request-Id; the tenant seams bind the workspace; sweep loops report to Sentry (lane 3 slice 2, D3)."
```

---

### Task 6: The design note and the lane index

**Files:**
- Modify: `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` (§3 row "Structured logs with run context"; §7 block; §9 slice 2)
- Modify: `docs/superpowers/plans/2026-09-13-lane-plan-index.md` (Lane 3 table row 2)

- [ ] **Step 1: Edit the design note**

§3 row `| Structured logs with run context | ... | Done. Milestone item 6. |` → State cell: `Bound at the roots since slice 2 (2026-09-15): the request-context middleware and tenant seams in the API, the per-task wrapper in the fleet worker. Before that nothing in production called the bind helpers, so item 6 was not met.`

§7: replace the fenced env block with the D2 names exactly as `.env.example` now documents them (the twelve `CLUE_*` lines), and change its lead sentence to `Every flag below lands in \`.env.example\` with its default the moment its code lands (CLUE_-prefixed, read through Settings/Secrets — the SDK-native names are not used, so nothing configures itself behind the parity rule):`.

§9 item 2 → `2. **Roots — DONE 2026-09-15** (design: \`2026-09-15-lane3-slice2-roots-design.md\`). \`clue_obs.otel.install_tracing\` + \`clue_obs.sentry\` at \`projections_main\` and \`fleet_main\`; run context bound at the roots; the trace rides the fleet payload (D1, no migration); env parity incl. the metrics gap.`

- [ ] **Step 2: Edit the lane index**

Row `| 2 | (to write) | OTel exporter + FastAPI/httpx instrumentors + Sentry at the roots; traceparent on turn and job rows | 1 (sequencing only) |` → `| 2 | \`2026-09-15-lane3-slice2-roots.md\` | tracing + Sentry installed at the platform API and fleet worker; run context bound at the roots; the trace rides the fleet payload; env parity | 1 (sequencing only) |`.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md docs/superpowers/plans/2026-09-13-lane-plan-index.md
git commit -m "docs(lane3): the design note records slice 2 as done and corrects the run-context claim; lane index row 2"
```

---

### Task 7: Verification and the memory note (controller)

- [ ] Whole-slice run on the lane DB (ambient vars stripped): `tests/test_obs_*.py tests/test_telemetry_settings.py tests/fleet tests/api/test_request_context_db.py tests/api/test_projections_app.py tests/api/test_fleet_wiring.py tests/arv2/test_settings.py` + the slice 1b set; gates; `uv run python -c "import clue_api.projections_main, clue_api.fleet_main"`.
- [ ] Zero-spend proof: with the shipped defaults, a request through the app gets an `X-Request-Id` and a server span carrying `workspace_id` (the Task 5 test); an enqueue under a span stamps `traceparent` and a worker drain restores the trace (the Task 4 tests). Owed, founder-triggered: after a stack restart with an OTLP endpoint (slice 3's Langfuse, or a local collector), one turn submitted from the frontend shows the API request span and the worker's `fleet.task` span under one trace id, and the worker's log lines for the turn carry `turn_id`/`workspace_id`.
- [ ] `_memory/2026-09-15-lane3-slice2-roots.md` + README index line; commit `docs(memory): lane 3 slice 2 — tracing and Sentry at the roots, run context bound, trace propagation`.

---

## Self-review

**Spec coverage.** §3.1 (provider, processor, global + traced_step, httpx, `instrument_app`, allowlist keys) → Task 2 + Task 5 (`instrument_app` at construction). §3.2 (Sentry posture, `capture` at the worker and sweep catch sites) → Tasks 3, 4, 5. §3.3 (API middleware + tenant seams; turn submission; fleet per-task binding) → Tasks 4, 5. §3.4 (carrier at enqueue, `fleet.task` child span, no migration) → Task 4. §3.5 (settings, secrets, `.env.example`, `.env`, the metrics gap, the enabled-without-DSN refusal) → Tasks 1, 5. §3.6 dependencies → Task 1. §5 tests → each task. §4 → no task touches R11/R12 files or adds a migration; `trial_main`/`handoff_app` untouched.

**Placeholders.** None: every step carries its code. Two constructor-keyword facts (the worker's keyword names in the offline test; the fleet DB fixture name) are pointed at the files that define them rather than guessed.

**Type consistency.** `install_tracing(..., set_global=, instrument_httpx=)` (Task 2) is what Tasks 4's tests and Task 5 call; `TracingRuntime.instrument_app`/`shutdown` are what Task 5 uses; `carrier_from_current_span`/`context_from_carrier`/`get_tracer`/`safe_attributes` (Task 2) are what Task 4 imports; `install_sentry(..., transport=)`/`capture` (Task 3) are what Tasks 4–5 use; `request_id_for` (Task 5) replaces `_request_id` everywhere in `auth_wiring`; `RUN_CONTEXT_KEYS` holds every key Tasks 4–5 bind.
