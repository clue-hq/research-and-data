# Lane 3 slice 3a — Langfuse foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Langfuse (cloud, EU) receives every chat turn as one trace attached to the slice 2 tracer provider — the graph's agent, chain, tool and generation observations from the LangChain handler, each generation carrying the platform's settled cost — and every `agent_model_call` receipt carries the Langfuse trace and observation ids; payloads are redacted before export; the streamed `answering_model` is no longer doubled; all off unless enabled with keys.

**Architecture:** `clue_obs.langfuse` owns the SDK client (attached to the process's `TracerProvider`, with a `mask` that applies the secret-key and blob rules and truncation) and the platform-side helpers (`observation`, `event`, `guardrail`, `current_ids`, `propagate_trace`, `LangfuseRunRegistry`). `clue_api.langfuse_callbacks` subclasses the SDK's LangChain handler to fill the run registry at model-call start and to write the gateway's cost onto each generation before it ends. `agent_runtime_wiring` appends the handler to the turn's callback tuple, wraps the run in `propagate_trace`, and the durable recorder reads the registry to stamp the receipt. `clue_api.production_tracing` composes it at both roots.

**Tech Stack:** Python 3.12, langfuse 4.15 (OTel-based SDK), opentelemetry-sdk 1.42, langchain-core 1.x, pydantic-settings, alembic, pytest with the repo's rolled-back-connection DB harness, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-15-lane3-slice3-langfuse-design.md` (D1–D4 ruled 2026-09-15; this plan covers §3.1, §3.2, §3.3 runtime part, §3.8, §3.9, §3.10, §3.11). Parent: `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` §5.3, §7, §9 slice 3.

## Global Constraints

- **Branch.** Work continues on `lane3/sice1b`. One commit per task, local only, never push; no AI attribution trailer.
- **Database.** This checkout's `.env` names `clue_semarang`, which a LIVE stack uses and which is behind the migration head. Never run tests or alembic against it. Every DB command runs after `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"` and after confirming `uv run alembic current` prints the expected head (`d36bc7d32c9a (head)` before Task 4, the new revision after it). The migration round-trip (`tests/db/test_db_migrations.py`, `make db-smoke`) cannot run on that data-bearing DB; Task 4 runs it on a fresh empty database it creates and drops.
- **Tests spend no money.** Run only the files each task names; never `make check`, never a broad `pytest`; `--ignore-glob='*_live.py'` when a directory is named. Ambient `.env` leaks that fail otherwise-green tests when sourced: `CLUE_ARV2_DISCOVERY_ENABLED`, `CLUE_CHAT_REASONING_TRACE_MODE`, `CLUE_FLEET_WORKER_CONCURRENCY`, `CLUE_BRANDFETCH_CLIENT_ID`, `CLUE_PROJECTIONS_AUTH_MODE`, `CLUE_EXA_API_KEY`, `CLUE_OPENROUTER_API_KEY` — strip with `env -u` and report as pre-existing.
- **Off by default (spec §1).** With `CLUE_LANGFUSE_ENABLED=false` (the shipped default) nothing imports at the roots beyond the settings read, no client exists, every helper is a no-op, the callback tuple is exactly what it was, and every new receipt column is NULL.
- **One path per call (spec §3.3).** `clue_gateway.agent_model` opens no Langfuse observation; the LangChain handler reports the graph path.
- **Redaction (R3, spec §3.1).** Every payload that reaches Langfuse passes `make_mask`: `redact_value` (secret-key rule), `mask_blob` on every string, truncation at the limit. The claim-value rule is never applied.
- **No network in tests.** Langfuse is installed in tests through `tests/_langfuse.py::langfuse_installed()` (an `InMemorySpanExporter` handed to the SDK as `span_exporter`); never a real host.
- **R11 / R12.** Nothing under `subsystems/research/clue_research/**`, `subsystems/clue-design/**`, `apps/frontend/**`.
- **Env parity (founder rule 2026-08-31).** Every new setting appears in `.env.example` with its default the moment its code lands. The local `.env` already carries the five keys (added 2026-09-15, uncommitted, never committed) — do not edit or stage `.env`.
- **Gates per task:** `uv run ruff format <files> && uv run ruff check <files>`; `uv run mypy` (baseline exactly 4 pre-existing errors: `subsystems/design/clue_design/ad_assets.py:149`, `platform/api/clue_api/arv2/account_research_claims.py:1387`, `platform/api/clue_api/arv2/account_research_driver.py:181-182`; gate = no new error); `uv run lint-imports` after any import change (26 kept / 0 broken before Task 1; 27 kept / 0 broken from Task 1 on).
- **Shell is zsh:** file lists as arrays. Never `git stash`.
- **Langfuse SDK facts (probed 2026-09-15, v4.15.2):** `Langfuse(tracer_provider=p)` adds its own span processor to `p` (D1); `Langfuse(span_exporter=e)` replaces the OTLP exporter with `e` (the test seam); the client registry is per public key (`LangfuseResourceManager.reset()` clears it — tests only); `langfuse.langchain.CallbackHandler` keeps `self._runs: dict[UUID, observation]` from start to end; observation wrappers expose `.id` and `.trace_id` (hex strings); `propagate_attributes(...)` sets `langfuse.trace.name`, `session.id`, `user.id`, `langfuse.trace.metadata.<k>`, `langfuse.trace.tags` on every span opened inside it; `environment` must match `^(?!langfuse)[a-z0-9-_]+$`; `langfuse` ships `py.typed`.

## What the plan discovered (read before Task 1)

1. LangChain dispatches every handler's **start** event (inline, or in an executor with `copy_context().run`) and waits for all of them before the model call proceeds; **end** events of different handlers run concurrently. So ids captured at start are visible to every handler's end, and the cost update must happen in the Langfuse handler's own `on_llm_end` (before `super()` ends the observation), never from the recorder.
2. The Langfuse handler is a plain `BaseCallbackHandler` (not a streaming consumer), so appending it does not opt a turn into the streaming model path; `TurnStreamCallbackHandler` still decides that.
3. `clue_agents.runtime.run` already accepts `Sequence[BaseCallbackHandler]`; only `agent_runtime_wiring`'s tuple annotation is narrower (`AsyncCallbackHandler`).
4. `get_client()` returns a new wrapper over the same underlying resource manager (identity differs; the tracer and processor are shared), so `ClueLangfuseHandler()` needs no explicit client.
5. The doubled `answering_model` comes from two provider chunks each carrying `model_name` (the finish chunk and the usage chunk) plus our per-chunk stamp; LangChain's chunk merge concatenates string metadata. Only one chunk may carry each model key.
6. `agent_turn_fleet_wiring.py:1661` (the design leg's exit judge) is the one direct chat-model call outside a graph; it is plan 3b's (`evaluator`).

## File structure

| File | Responsibility |
| --- | --- |
| `libs/clue-obs/pyproject.toml`, `uv.lock` | **Modify.** `langfuse>=4.15,<5`. |
| `libs/clue-config/clue_config/settings.py`, `secrets.py` | **Modify.** Langfuse settings and secrets. |
| `.env.example` | **Modify.** The Langfuse block. |
| `tests/test_telemetry_settings.py` | **Modify.** Parity + defaults for the five names. |
| `pyproject.toml` | **Modify.** The Langfuse import-linter contract. |
| `libs/clue-obs/clue_obs/langfuse.py` | **Create.** Client install, mask, helpers, run registry. |
| `libs/clue-obs/clue_obs/truncate.py` | **Modify.** Public `truncate_str`. |
| `libs/clue-obs/clue_obs/__init__.py` | **Modify.** Exports. |
| `tests/_langfuse.py` | **Create.** The in-memory install helper. |
| `tests/test_obs_langfuse.py` | **Create.** |
| `platform/api/clue_api/production_tracing.py` | **Modify.** `install_production_langfuse`, shutdown in the lifespan. |
| `platform/api/clue_api/projections_main.py`, `fleet_main.py` | **Modify.** Compose at the roots. |
| `tests/api/test_production_langfuse.py` | **Create.** |
| `alembic/versions/<hash>_agent_model_call_langfuse_ids.py` | **Create.** Two nullable text columns. |
| `platform/agents/clue_agents/turns.py` | **Modify.** Receipt fields. |
| `platform/api/clue_api/agent_turn_wiring.py` | **Modify.** INSERT + replay compare. |
| `tests/db/test_agent_model_call_langfuse_ids_migration.py` | **Create.** |
| `tests/api/test_agent_model_call_cost_receipt_db.py` | **Modify.** Ids round trip + replay compare. |
| `platform/api/clue_api/langfuse_callbacks.py` | **Create.** `ClueLangfuseHandler`, `build_langfuse_callbacks`. |
| `tests/api/test_langfuse_callbacks.py` | **Create.** |
| `platform/api/clue_api/agent_runtime_wiring.py` | **Modify.** Recorder reads the registry; runner appends the handler under `propagate_trace`; prefers `clue_answering_model`. |
| `tests/api/test_agent_runtime_wiring_cost_stamp.py` | **Modify.** Ids on the receipt; answering-model preference. |
| `tests/api/test_agent_runtime_langfuse.py` | **Create.** The runner's callback tuple with Langfuse on and off. |
| `libs/clue-gateway/clue_gateway/agent_model.py` | **Modify.** One chunk carries the model keys. |
| `tests/gateway/test_agent_model.py` | **Modify.** The doubled-model regression. |
| `platform/api/clue_api/langfuse_check.py` | **Create.** `python -m clue_api.langfuse_check`. |
| `Makefile`, `scripts/dev_stack.sh` | **Modify.** `langfuse-check`; the status line. |
| `tests/api/test_langfuse_check.py` | **Create.** |
| `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md`, `docs/superpowers/plans/2026-09-13-lane-plan-index.md` | **Modify.** §7 names, §9 slice 3a done, index row. |

---

### Task 1: Settings, secrets, env parity, the dependency and the import contract

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after the `release` field, ~line 188)
- Modify: `libs/clue-config/clue_config/secrets.py` (after `otel_traces_headers`, ~line 116)
- Modify: `.env.example` (after `CLUE_RELEASE=`, ~line 258)
- Modify: `tests/test_telemetry_settings.py`
- Modify: `libs/clue-obs/pyproject.toml`, `uv.lock`
- Modify: `pyproject.toml` (a new `[[tool.importlinter.contracts]]` after the "LLM-vendor SDK" contract's `ignore_imports`, ~line 320)

**Interfaces:**
- Produces: `Settings.langfuse_enabled: bool = False`, `Settings.langfuse_host: str = "https://cloud.langfuse.com"`, `Settings.langfuse_environment: str = "lane-san-salvador"`, `Secrets.langfuse_public_key: SecretStr | None`, `Secrets.langfuse_secret_key: SecretStr | None`.

- [ ] **Step 1: Extend the parity test**

In `tests/test_telemetry_settings.py` add to `TELEMETRY_SETTING_DEFAULTS`:

```python
    # lane 3 slice 3
    "langfuse_enabled": False,
    "langfuse_host": "https://cloud.langfuse.com",
    "langfuse_environment": "lane-san-salvador",
```

and change the secrets tuple to:

```python
TELEMETRY_SECRET_FIELDS = (
    "sentry_dsn",
    "otel_traces_headers",
    "langfuse_public_key",
    "langfuse_secret_key",
)
```

Append one test:

```python
def test_langfuse_environment_is_a_langfuse_legal_name() -> None:
    """Langfuse refuses environments outside ``^(?!langfuse)[a-z0-9-_]+$``; the shipped
    default must be legal so enabling it never fails on the name."""
    default = Settings.model_fields["langfuse_environment"].default
    assert re.fullmatch(r"(?!langfuse)[a-z0-9-_]+", default), default
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_telemetry_settings.py -q`
Expected: FAIL (`langfuse_enabled` missing from `Settings`).

- [ ] **Step 3: Settings and secrets**

In `settings.py`, after `release: str | None = None`:

```python
    # --- Langfuse (lane 3 slice 3, R4: cloud, EU) -------------------------------------------
    # Installed only when enabled AND both keys (secrets) are set; the roots refuse ``enabled``
    # with a missing key. The client attaches to the process's tracer provider, so the agent
    # tree, the HTTP spans and the worker's task span are one trace. ``langfuse_environment``
    # names the deployment posture on every trace (Langfuse allows ``[a-z0-9-_]`` only).
    # Env: ``CLUE_LANGFUSE_ENABLED`` / ``CLUE_LANGFUSE_HOST`` / ``CLUE_LANGFUSE_ENVIRONMENT``.
    langfuse_enabled: bool = False
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "lane-san-salvador"
```

In `secrets.py`, after `otel_traces_headers`:

```python
    # --- Langfuse (lane 3 slice 3) ---
    # Env: CLUE_LANGFUSE_PUBLIC_KEY / CLUE_LANGFUSE_SECRET_KEY — the project's key pair (the
    # public key is also an identifier, but the pair authorises ingest, so both are secrets).
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
```

- [ ] **Step 4: `.env.example`**

After the `CLUE_RELEASE=` line (inside the telemetry block, before the blank line that precedes the fleet block) add:

```
# Langfuse (lane 3 slice 3): the agent-tree viewer, cloud EU project. Installed only when
# enabled AND both keys are set; attaches to the tracer provider above (no OTLP endpoint needed).
CLUE_LANGFUSE_ENABLED=false
CLUE_LANGFUSE_HOST=https://cloud.langfuse.com
CLUE_LANGFUSE_PUBLIC_KEY=
CLUE_LANGFUSE_SECRET_KEY=
CLUE_LANGFUSE_ENVIRONMENT=lane-san-salvador
```

- [ ] **Step 5: The dependency**

In `libs/clue-obs/pyproject.toml` add to `dependencies` after `"sentry-sdk>=2.30",`:

```
    # Langfuse (lane 3 slice 3): the OTel-based SDK, attached to the process provider
    "langfuse>=4.15,<5",
```

Run: `uv sync` (updates `uv.lock`; expect langfuse 4.15.x and its transitive packages to install). Then `uv run python -c "import langfuse; print(langfuse.__version__)"` → `4.15.x`.

- [ ] **Step 6: The import contract**

In the root `pyproject.toml`, after the "the LLM-vendor SDK lives only behind the gateway/ package" contract (its `ignore_imports` list ends at ~line 320), add:

```toml
# Lane 3 slice 3 — the Langfuse SDK lives only behind ``clue_obs.langfuse`` (the client and every
# platform-side helper) and ``clue_api.langfuse_callbacks`` (the LangChain adapter, which needs
# ``langchain_core`` and so cannot live in the base library). Everything else reaches Langfuse
# through those two modules' no-op-when-off helpers.
[[tool.importlinter.contracts]]
name = "the Langfuse SDK lives only behind clue_obs.langfuse and clue_api.langfuse_callbacks"
type = "forbidden"
source_modules = [
    "clue_research",
    "clue_core",
    "clue_config",
    "clue_obs",
    "clue_db",
    "clue_gateway",
    "clue_locks",
    "clue_spine",
    "clue_storage",
    "clue_auth",
    "clue_memory",
    "clue_content",
    "clue_design",
    "clue_toolbelt",
    "clue_agents",
    "clue_execution",
    "clue_fleet",
    "clue_projections",
    "clue_api",
]
forbidden_modules = ["langfuse"]
ignore_imports = [
    "clue_obs.langfuse -> langfuse",
    "clue_api.langfuse_callbacks -> langfuse.langchain",
]
```

(If Task 2 or Task 5 imports a different `langfuse` submodule, add that exact edge here in the same task.)

- [ ] **Step 7: Verify**

Run: `uv run pytest tests/test_telemetry_settings.py tests/arv2/test_settings.py -q` → PASS.
Run: `uv run lint-imports` → `27 kept, 0 broken` (the new contract is kept vacuously until Task 2).
Run: `uv run mypy` → the 4 baseline errors only.

- [ ] **Step 8: Commit**

```bash
git add libs/clue-config/clue_config/settings.py libs/clue-config/clue_config/secrets.py .env.example tests/test_telemetry_settings.py libs/clue-obs/pyproject.toml uv.lock pyproject.toml
git commit -m "feat(config): Langfuse settings and secrets (CLUE_LANGFUSE_*), the SDK dependency behind clue_obs, and its import contract (lane 3 slice 3a)"
```

---

### Task 2: `clue_obs.langfuse` — the client, the mask, the helpers, the run registry

**Files:**
- Create: `libs/clue-obs/clue_obs/langfuse.py`
- Modify: `libs/clue-obs/clue_obs/truncate.py` (public `truncate_str`)
- Modify: `libs/clue-obs/clue_obs/__init__.py` (exports)
- Create: `tests/_langfuse.py`
- Create: `tests/test_obs_langfuse.py`

**Interfaces:**
- Produces (all in `clue_obs.langfuse`, re-exported from `clue_obs`):
  - `install_langfuse(*, public_key: str | None, secret_key: str | None, host: str, environment: str, release: str | None, tracer_provider: TracerProvider, process_name: str, mask_limit: int = DEFAULT_MASK_LIMIT, span_exporter: SpanExporter | None = None) -> bool`
  - `langfuse_is_installed() -> bool`, `flush_langfuse() -> None`, `shutdown_langfuse() -> None`
  - `auth_check(*, public_key: str, secret_key: str, host: str) -> bool` (no tracing, for the check verb)
  - `make_mask(limit: int = DEFAULT_MASK_LIMIT) -> Callable[..., Any]`, `DEFAULT_MASK_LIMIT = 8_000`
  - `ObservationType` (Literal of the nine types), `Level` (Literal `DEBUG|DEFAULT|WARNING|ERROR`)
  - `observation(name: str, *, as_type: ObservationType = "span", **fields: Any) -> Iterator[ObservationLike]` (context manager)
  - `ObservationLike` (Protocol: `id`, `trace_id`, `update(**fields) -> Any`), `NullObservation`
  - `LangfuseIds(trace_id: str, observation_id: str | None)` (frozen dataclass), `current_ids() -> LangfuseIds | None`
  - `event(name, *, level="DEFAULT", status_message=None, metadata=None, input=None, output=None) -> None`
  - `guardrail(name, *, reason: str, metadata=None, level: Level = "WARNING") -> None`
  - `propagate_trace(*, trace_name: str, session_id: str | None = None, user_id: str | None = None, metadata: Mapping[str, object] | None = None, tags: Sequence[str] = ()) -> Iterator[None]` (context manager)
  - `LangfuseRunRegistry` with `remember(run_id: UUID, ids: LangfuseIds) -> None`, `get(run_id: UUID) -> LangfuseIds | None`, `pop(run_id) -> LangfuseIds | None`
- `tests/_langfuse.py`: `langfuse_installed(*, provider: TracerProvider | None = None) -> Iterator[tuple[InMemorySpanExporter, TracerProvider]]` (context manager; installs, yields, shuts down and resets the SDK registry) and `finished_spans(exporter) -> list[ReadableSpan]` (flushes first).

- [ ] **Step 1: The test helper**

`tests/_langfuse.py`:

```python
"""Langfuse installed against an in-memory exporter (lane 3 slice 3). No network, ever."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clue_obs.langfuse import flush_langfuse, install_langfuse, shutdown_langfuse


@contextmanager
def langfuse_installed(
    *, provider: TracerProvider | None = None
) -> Iterator[tuple[InMemorySpanExporter, TracerProvider]]:
    """Install the client on ``provider`` (a fresh one by default) with an in-memory exporter.

    The SDK keeps one resource manager per public key for the life of the process; the exit
    shuts the client down and clears that registry so the next test starts clean.
    """
    tracer_provider = provider if provider is not None else TracerProvider()
    exporter = InMemorySpanExporter()
    installed = install_langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://127.0.0.1:9",
        environment="lane-test",
        release="test",
        tracer_provider=tracer_provider,
        process_name="clue-test",
        span_exporter=exporter,
    )
    assert installed
    try:
        yield exporter, tracer_provider
    finally:
        shutdown_langfuse()
        LangfuseResourceManager.reset()


def finished_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    flush_langfuse()
    return list(exporter.get_finished_spans())
```

- [ ] **Step 2: The failing tests**

`tests/test_obs_langfuse.py`:

```python
"""Lane 3 slice 3a, Task 2: the Langfuse client at the roots, its redaction, and the no-op
posture when it is not installed."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from opentelemetry.sdk.trace import ReadableSpan

from clue_obs.langfuse import (
    DEFAULT_MASK_LIMIT,
    LangfuseIds,
    LangfuseRunRegistry,
    current_ids,
    event,
    guardrail,
    langfuse_is_installed,
    make_mask,
    observation,
    propagate_trace,
)
from tests._langfuse import finished_spans, langfuse_installed


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def test_not_installed_every_helper_is_a_no_op() -> None:
    assert not langfuse_is_installed()
    assert current_ids() is None
    with observation("x", as_type="tool", input={"a": 1}) as obs:
        assert obs.id is None and obs.trace_id is None
        assert obs.update(output={"b": 2}) is obs
    event("e", metadata={"k": "v"})
    guardrail("g", reason="halted")
    with propagate_trace(trace_name="t", session_id="s"):
        pass


def test_an_observation_exports_its_type_ids_and_payload_under_the_trace_attributes() -> None:
    with langfuse_installed() as (exporter, _provider):
        assert langfuse_is_installed()
        with (
            propagate_trace(
                trace_name="head-of-abm.turn",
                session_id="thread-1",
                user_id="ws-1",
                metadata={"turn_id": "turn-1", "skipped": None},
                tags=("head_of_abm",),
            ),
            observation("gateway.completion", as_type="generation", input={"q": "hi"}) as obs,
        ):
            ids = current_ids()
            assert ids == LangfuseIds(trace_id=obs.trace_id, observation_id=obs.id)
            obs.update(
                output={"a": "ok"},
                usage_details={"input": 3, "output": 1},
                cost_details={"total": 0.01},
            )
            guardrail("provider.ceiling", reason="usd over ceiling")
            event("note", metadata={"k": "v"})
        spans = finished_spans(exporter)
    by_name = {span.name: _attrs(span) for span in spans}
    generation = by_name["gateway.completion"]
    assert generation["langfuse.observation.type"] == "generation"
    assert generation["langfuse.observation.cost_details"] == '{"total": 0.01}'
    assert generation["langfuse.trace.name"] == "head-of-abm.turn"
    assert generation["session.id"] == "thread-1"
    assert generation["user.id"] == "ws-1"
    assert generation["langfuse.trace.metadata.turn_id"] == "turn-1"
    assert "langfuse.trace.metadata.skipped" not in generation
    assert generation["langfuse.environment"] == "lane-test"
    assert by_name["provider.ceiling"]["langfuse.observation.type"] == "guardrail"
    assert by_name["provider.ceiling"]["langfuse.observation.level"] == "WARNING"
    assert by_name["provider.ceiling"]["langfuse.observation.status_message"] == "usd over ceiling"
    assert by_name["note"]["langfuse.observation.type"] == "event"
    assert by_name["note"]["langfuse.observation.metadata.k"] == "v"


def test_the_mask_applies_the_secret_and_blob_rules_and_truncates_but_keeps_claim_values() -> None:
    mask = make_mask(limit=20)
    blob = "QUJD" * 200  # base64-looking, 800 chars
    masked = mask(
        data={
            "api_key": "sk-live-abc",
            "nested": {"authorization": "Bearer x", "value": "Acme uses Snowflake"},
            "attachment": blob,
            "long": "x" * 50,
            "n": 3,
        }
    )
    assert masked["api_key"] != "sk-live-abc"
    assert masked["nested"]["authorization"] != "Bearer x"
    assert masked["nested"]["value"] == "Acme uses Snowflake"  # the claim-value rule is NOT applied
    assert blob not in masked["attachment"]
    assert masked["long"].startswith("x" * 20) and "+30 chars" in masked["long"]
    assert masked["n"] == 3
    assert DEFAULT_MASK_LIMIT == 8_000


def test_the_installed_client_masks_payloads_before_export() -> None:
    with langfuse_installed() as (exporter, _provider):
        with observation("tool", as_type="tool", input={"api_key": "sk-live-abc", "q": "hi"}):
            pass
        spans = finished_spans(exporter)
    payload = _attrs(spans[0])["langfuse.observation.input"]
    assert "sk-live-abc" not in payload
    assert '"q": "hi"' in payload


def test_health_check_server_spans_are_not_exported() -> None:
    with langfuse_installed() as (exporter, provider):
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("GET /healthz", attributes={"http.route": "/healthz"}):
            pass
        with tracer.start_as_current_span("GET /accounts", attributes={"http.route": "/accounts"}):
            pass
        names = [span.name for span in finished_spans(exporter)]
    assert names == ["GET /accounts"]


def test_the_run_registry_remembers_and_pops_by_run_id() -> None:
    registry = LangfuseRunRegistry()
    run_id = uuid4()
    assert registry.get(run_id) is None
    registry.remember(run_id, LangfuseIds(trace_id="t", observation_id="o"))
    assert registry.get(run_id) == LangfuseIds(trace_id="t", observation_id="o")
    assert registry.pop(run_id) == LangfuseIds(trace_id="t", observation_id="o")
    assert registry.get(run_id) is None
```

- [ ] **Step 3: Run to see it fail**

Run: `uv run pytest tests/test_obs_langfuse.py -q` → FAIL (`clue_obs.langfuse` missing).

- [ ] **Step 4: `truncate_str` public**

In `libs/clue-obs/clue_obs/truncate.py` rename `_truncate_str` to `truncate_str` (keep a `_truncate_str = truncate_str` alias below it so nothing else changes) and add `"truncate_str"` to the module's `__all__` if one exists (else no change beyond the alias).

- [ ] **Step 5: The module**

`libs/clue-obs/clue_obs/langfuse.py`:

```python
"""Langfuse at the process roots (lane 3 slice 3, R4): the agent-tree viewer.

One client per process, attached to the tracer provider slice 2 built (D1), so the agent tree
the LangChain handler reports, the platform-side observations opened here, the FastAPI and httpx
spans and the worker's ``fleet.task`` span are one trace. Every payload passes :func:`make_mask`
before export (R3: the secret-key rule and the blob rule, plus truncation — never the claim-value
rule: this is the surface for debugging exactly those values). Nothing here does anything until
:func:`install_langfuse` was given both keys; every helper is a no-op otherwise, so an
unconfigured process behaves as it did after slice 2.

This module (and ``clue_api.langfuse_callbacks``, the LangChain adapter) are the only two that
import the SDK — an import-linter contract keeps it that way.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter

from clue_obs.redact import mask_blob, redact_value
from clue_obs.truncate import truncate_str

__all__ = [
    "DEFAULT_MASK_LIMIT",
    "LangfuseIds",
    "LangfuseRunRegistry",
    "Level",
    "NullObservation",
    "ObservationLike",
    "ObservationType",
    "auth_check",
    "current_ids",
    "event",
    "flush_langfuse",
    "guardrail",
    "install_langfuse",
    "langfuse_is_installed",
    "make_mask",
    "observation",
    "propagate_trace",
    "shutdown_langfuse",
]

ObservationType = Literal[
    "generation",
    "embedding",
    "span",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "guardrail",
]
Level = Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"]

#: Longest string any exported payload may carry; the turn's receipt limit is the same order.
DEFAULT_MASK_LIMIT = 8_000

#: Server spans for these routes are health probes: dropped before export.
HEALTH_ROUTES: frozenset[str] = frozenset({"/healthz", "/health", "/readyz", "/livez"})

# The SDK client, typed ``Any`` on purpose: the platform never depends on its exact typed
# surface, and every helper below tolerates ``None`` (not installed).
_client: Any | None = None


# --- the mask (R3) -------------------------------------------------------------------------


def _mask_value(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return truncate_str(mask_blob(value), limit)
    if isinstance(value, Mapping):
        return {str(k): _mask_value(v, limit) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask_value(v, limit) for v in value]
    return value


def make_mask(limit: int = DEFAULT_MASK_LIMIT) -> Callable[..., Any]:
    """The client's ``mask`` hook: secret-key rule, blob rule, truncation — in that order."""

    def mask(data: Any) -> Any:
        return _mask_value(redact_value(data), limit)

    return mask


def _not_a_health_check(span: ReadableSpan) -> bool:
    attributes = span.attributes or {}
    route = attributes.get("http.route") or attributes.get("url.path") or attributes.get("http.target")
    return route not in HEALTH_ROUTES


# --- install / lifecycle ---------------------------------------------------------------------


def install_langfuse(
    *,
    public_key: str | None,
    secret_key: str | None,
    host: str,
    environment: str,
    release: str | None,
    tracer_provider: TracerProvider,
    process_name: str,
    mask_limit: int = DEFAULT_MASK_LIMIT,
    span_exporter: SpanExporter | None = None,
) -> bool:
    """Build the client on ``tracer_provider``. Returns ``False`` (and builds nothing) unless both
    keys are present. ``span_exporter`` is the test seam (an in-memory exporter instead of the
    host)."""
    global _client
    if not (public_key or "").strip() or not (secret_key or "").strip():
        return False
    from langfuse import Langfuse

    _client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=host.rstrip("/"),
        environment=environment,
        release=release or None,
        tracer_provider=tracer_provider,
        mask=make_mask(mask_limit),
        should_export_span=_not_a_health_check,
        span_exporter=span_exporter,
        tracing_enabled=True,
    )
    del process_name  # named on the provider's resource by slice 2; kept for symmetry with Sentry
    return True


def langfuse_is_installed() -> bool:
    return _client is not None


def flush_langfuse() -> None:
    if _client is not None:
        _client.flush()


def shutdown_langfuse() -> None:
    global _client
    if _client is not None:
        _client.shutdown()
        _client = None


def auth_check(*, public_key: str, secret_key: str, host: str) -> bool:
    """Verify the key pair against the host without opening a trace (the check verb)."""
    from langfuse import Langfuse

    probe = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=host.rstrip("/"),
        tracing_enabled=False,
    )
    try:
        return bool(probe.auth_check())
    finally:
        probe.shutdown()


# --- observations -----------------------------------------------------------------------------


class ObservationLike(Protocol):
    @property
    def id(self) -> str | None: ...

    @property
    def trace_id(self) -> str | None: ...

    def update(self, **fields: Any) -> Any: ...


@dataclass
class NullObservation:
    """What :func:`observation` yields when Langfuse is not installed."""

    id: str | None = None
    trace_id: str | None = None

    def update(self, **fields: Any) -> NullObservation:
        del fields
        return self


@contextmanager
def observation(
    name: str, *, as_type: ObservationType = "span", **fields: Any
) -> Iterator[ObservationLike]:
    """Open one observation as the current span (a no-op handle when not installed).

    ``fields`` are the SDK's keyword fields: ``input``, ``output``, ``metadata``, ``level``,
    ``status_message``, ``model``, ``usage_details``, ``cost_details``.
    """
    if _client is None:
        yield NullObservation()
        return
    with _client.start_as_current_observation(name=name, as_type=as_type, **fields) as current:
        yield current


@dataclass(frozen=True)
class LangfuseIds:
    trace_id: str
    observation_id: str | None


def current_ids() -> LangfuseIds | None:
    """The current trace and observation ids, or ``None`` when not installed / no span."""
    if _client is None:
        return None
    trace_id = _client.get_current_trace_id()
    if not isinstance(trace_id, str) or not trace_id:
        return None
    observation_id = _client.get_current_observation_id()
    return LangfuseIds(
        trace_id=trace_id,
        observation_id=observation_id if isinstance(observation_id, str) else None,
    )


def event(
    name: str,
    *,
    level: Level = "DEFAULT",
    status_message: str | None = None,
    metadata: Mapping[str, object] | None = None,
    input: Any = None,
    output: Any = None,
) -> None:
    """A point-in-time observation under the current span."""
    if _client is None:
        return
    _client.create_event(
        name=name,
        level=level,
        status_message=status_message,
        metadata=dict(metadata) if metadata else None,
        input=input,
        output=output,
    )


def guardrail(
    name: str,
    *,
    reason: str,
    metadata: Mapping[str, object] | None = None,
    level: Level = "WARNING",
) -> None:
    """Record that a guardrail fired: a closed ``guardrail`` observation carrying the reason."""
    if _client is None:
        return
    with _client.start_as_current_observation(
        name=name,
        as_type="guardrail",
        level=level,
        status_message=reason,
        metadata=dict(metadata) if metadata else None,
    ):
        pass


@contextmanager
def propagate_trace(
    *,
    trace_name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
    tags: Sequence[str] = (),
) -> Iterator[None]:
    """Name the trace and stamp session, user, metadata and tags on every span opened inside.

    Metadata values are stringified (the SDK takes primitives) and ``None`` values are dropped.
    """
    if _client is None:
        yield
        return
    from langfuse import propagate_attributes

    cleaned = {k: str(v) for k, v in (metadata or {}).items() if v is not None}
    with propagate_attributes(
        trace_name=trace_name,
        session_id=session_id,
        user_id=user_id,
        metadata=cleaned or None,
        tags=list(tags) or None,
    ):
        yield


# --- the run registry (LangChain run id → Langfuse ids) --------------------------------------


@dataclass
class LangfuseRunRegistry:
    """Filled by the LangChain handler at model-call start; read by the durable recorder."""

    _ids: dict[UUID, LangfuseIds] = field(default_factory=dict)

    def remember(self, run_id: UUID, ids: LangfuseIds) -> None:
        self._ids[run_id] = ids

    def get(self, run_id: UUID) -> LangfuseIds | None:
        return self._ids.get(run_id)

    def pop(self, run_id: UUID) -> LangfuseIds | None:
        return self._ids.pop(run_id, None)
```

- [ ] **Step 6: Exports**

In `libs/clue-obs/clue_obs/__init__.py` add `from clue_obs.langfuse import (current_ids, event as langfuse_event, guardrail, install_langfuse, langfuse_is_installed, observation, propagate_trace, shutdown_langfuse)` — the `event` name is exported as `langfuse_event` to avoid the generic word at package level — and add each of those names to `__all__` (alphabetical). Keep the rest of `__all__` unchanged.

- [ ] **Step 7: Run to see it pass**

Run: `uv run pytest tests/test_obs_langfuse.py tests/test_obs_install.py tests/test_obs_sentry.py -q` → PASS.
If the SDK's `mask` is called with a different keyword than `data`, adapt `make_mask`'s inner signature to `def mask(*, data: Any) -> Any` and note it in the report.
If the SDK emits a warning about `process_name`, drop the `del` line and the parameter's use only (keep the parameter).

- [ ] **Step 8: Gates**

Run: `uv run ruff format libs/clue-obs/clue_obs/langfuse.py libs/clue-obs/clue_obs/truncate.py libs/clue-obs/clue_obs/__init__.py tests/_langfuse.py tests/test_obs_langfuse.py && uv run ruff check <same files>`; `uv run mypy` (4 baseline); `uv run lint-imports` → 27 kept / 0 broken (add any new `clue_obs.langfuse -> langfuse.<sub>` edge to the Task 1 contract if reported).

- [ ] **Step 9: Commit**

```bash
git add libs/clue-obs/clue_obs/langfuse.py libs/clue-obs/clue_obs/truncate.py libs/clue-obs/clue_obs/__init__.py tests/_langfuse.py tests/test_obs_langfuse.py pyproject.toml
git commit -m "feat(obs): clue_obs.langfuse — the client attached to the process provider, the payload mask, observation/event/guardrail helpers, the run registry (lane 3 slice 3a)"
```

---

### Task 3: The roots — `install_production_langfuse` at the platform API and the fleet worker

**Files:**
- Modify: `platform/api/clue_api/production_tracing.py`
- Modify: `platform/api/clue_api/projections_main.py` (~line 88–91), `platform/api/clue_api/fleet_main.py` (~line 823–824)
- Create: `tests/api/test_production_langfuse.py`

**Interfaces:**
- Consumes: `install_langfuse`, `shutdown_langfuse`, `flush_langfuse` (Task 2); `Settings.langfuse_*`, `Secrets.langfuse_*` (Task 1); `TracingRuntime.provider`.
- Produces: `install_production_langfuse(settings: Settings, secrets: Secrets, *, runtime: TracingRuntime, service_name: str) -> bool`.

- [ ] **Step 1: The failing tests**

`tests/api/test_production_langfuse.py`:

```python
"""Lane 3 slice 3a, Task 3: Langfuse composed at the roots — off by default, loud when enabled
without keys, attached to the process provider when enabled with keys."""

from __future__ import annotations

import pytest
from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clue_api.production_tracing import install_production_langfuse
from clue_config import Secrets, Settings
from clue_obs.langfuse import langfuse_is_installed, observation, shutdown_langfuse
from clue_obs.otel import install_tracing


def _runtime():  # type: ignore[no-untyped-def]
    return install_tracing(
        process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=False
    )


def test_disabled_installs_nothing() -> None:
    settings = Settings(_env_file=None, langfuse_enabled=False)
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert install_production_langfuse(settings, secrets, runtime=_runtime(), service_name="t") is False
    assert not langfuse_is_installed()


def test_enabled_without_both_keys_refuses_at_composition() -> None:
    settings = Settings(_env_file=None, langfuse_enabled=True)
    secrets = Secrets(_env_file=None, langfuse_public_key="pk-only")  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="CLUE_LANGFUSE_SECRET_KEY"):
        install_production_langfuse(settings, secrets, runtime=_runtime(), service_name="t")
    assert not langfuse_is_installed()


def test_enabled_with_keys_attaches_to_the_process_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client's processor is added to the runtime's provider: a platform observation is one
    span on that provider, carrying the Langfuse attributes."""
    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_host="http://127.0.0.1:9",
        langfuse_environment="lane-test",
    )
    secrets = Secrets(  # type: ignore[call-arg]
        _env_file=None, langfuse_public_key="pk-lf-root", langfuse_secret_key="sk-lf-root"
    )
    runtime = _runtime()
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Keep the SDK off the network: its own exporter is swapped for an in-memory one.
    from clue_api import production_tracing

    sink = InMemorySpanExporter()
    monkeypatch.setattr(production_tracing, "_span_exporter_override", sink)
    try:
        assert install_production_langfuse(settings, secrets, runtime=runtime, service_name="t")
        assert langfuse_is_installed()
        with observation("root.probe", as_type="tool"):
            pass
        spans = exporter.get_finished_spans()
        assert [span.name for span in spans] == ["root.probe"]
        assert spans[0].attributes is not None
        assert spans[0].attributes["langfuse.observation.type"] == "tool"
        assert spans[0].attributes["langfuse.environment"] == "lane-test"
    finally:
        shutdown_langfuse()
        LangfuseResourceManager.reset()
        monkeypatch.setattr(production_tracing, "_span_exporter_override", None)
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/api/test_production_langfuse.py -q` → FAIL (import error).

- [ ] **Step 3: Implement**

In `production_tracing.py`:

```python
from clue_obs.langfuse import flush_langfuse, install_langfuse, shutdown_langfuse
```

add to `__all__`: `"install_production_langfuse"`. Module-level test seam after `log = ...`:

```python
#: Test seam: an exporter handed to the SDK instead of the host (never set in production).
_span_exporter_override: Any | None = None
```

(import `Any` from `typing`.) Then:

```python
def install_production_langfuse(
    settings: Settings, secrets: Secrets, *, runtime: TracingRuntime, service_name: str
) -> bool:
    """Install Langfuse on the process's provider when enabled. Enabled with a missing key
    refuses loudly at composition (the Sentry posture); disabled installs nothing."""
    if not settings.langfuse_enabled:
        log.info("langfuse.not_installed", reason="CLUE_LANGFUSE_ENABLED is off")
        return False
    public_key = (
        secrets.langfuse_public_key.get_secret_value().strip()
        if secrets.langfuse_public_key is not None
        else ""
    )
    secret_key = (
        secrets.langfuse_secret_key.get_secret_value().strip()
        if secrets.langfuse_secret_key is not None
        else ""
    )
    if not public_key:
        raise RuntimeError("CLUE_LANGFUSE_ENABLED=true requires CLUE_LANGFUSE_PUBLIC_KEY")
    if not secret_key:
        raise RuntimeError("CLUE_LANGFUSE_ENABLED=true requires CLUE_LANGFUSE_SECRET_KEY")
    installed = install_langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=settings.langfuse_host,
        environment=settings.langfuse_environment,
        release=settings.release or None,
        tracer_provider=runtime.provider,
        process_name=service_name,
        span_exporter=_span_exporter_override,
    )
    log.info(
        "langfuse.installed",
        service_name=service_name,
        host=settings.langfuse_host,
        environment=settings.langfuse_environment,
        release=settings.release or None,
    )
    return installed
```

In `production_tracing_lifespan`'s `finally`, before `runtime.shutdown()`:

```python
        flush_langfuse()
        shutdown_langfuse()
```

(unconditionally — both are no-ops when not installed; Langfuse must flush before the provider it rides on stops).

In `projections_main.py`, after `install_production_sentry(...)`:

```python
    install_production_langfuse(
        resolved, resolved_secrets, runtime=tracing, service_name="clue-projections-api"
    )
```

and in `fleet_main.py` after its `install_production_sentry(...)`:

```python
    install_production_langfuse(settings, secrets, runtime=tracing, service_name="clue-worker-fleet")
```

adding the import to each file's existing `from clue_api.production_tracing import (...)` block.

- [ ] **Step 4: Run to see it pass**

Run: `env -u CLUE_PROJECTIONS_AUTH_MODE -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_production_langfuse.py tests/api/test_production_tracing.py -q` (the second file exists from slice 2; if its name differs, run the slice 2 root test file you find with `ls tests/api | grep -i tracing`) → PASS.

- [ ] **Step 5: Gates and commit**

ruff on the four files; `uv run mypy` (4 baseline); `uv run lint-imports` (27/0).

```bash
git add platform/api/clue_api/production_tracing.py platform/api/clue_api/projections_main.py platform/api/clue_api/fleet_main.py tests/api/test_production_langfuse.py
git commit -m "feat(roots): Langfuse installed on the process provider at the platform API and the fleet worker; enabled-without-keys refuses at composition (lane 3 slice 3a)"
```

---

### Task 4: The receipt migration — `agent_model_call.langfuse_trace_id` / `langfuse_observation_id`

**Files:**
- Create: `alembic/versions/<hash>_agent_model_call_langfuse_ids.py` (generated)
- Modify: `platform/agents/clue_agents/turns.py` (`AgentModelCallReceipt`)
- Modify: `platform/api/clue_api/agent_turn_wiring.py` (`record_model_call`, ~lines 617–700)
- Create: `tests/db/test_agent_model_call_langfuse_ids_migration.py`
- Modify: `tests/api/test_agent_model_call_cost_receipt_db.py`

**Interfaces:**
- Produces: `AgentModelCallReceipt.langfuse_trace_id: str | None = None`, `AgentModelCallReceipt.langfuse_observation_id: str | None = None`; both inserted and compared on replay.

- [ ] **Step 1: The migration**

With the lane DB env set (Global Constraints), run `uv run alembic revision -m "agent_model_call_langfuse_ids"`; open the generated file and replace its body with:

```python
"""agent model call langfuse ids

Revision ID: <keep the generated id>
Revises: d36bc7d32c9a
Create Date: <keep>

Lane 3 slice 3 (the Langfuse design note §3.8, D4). The LangChain handler reports every graph
model call to Langfuse as a generation; the durable recorder stamps that generation's trace and
observation ids on the receipt so a row in the cost read opens the tree it came from. Both are
nullable text: a turn run with Langfuse off, and every row written before this migration, is
NULL/NULL.

Reversible: the downgrade drops both columns; no other row data is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "<generated>"
down_revision: str | None = "d36bc7d32c9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "ADD COLUMN langfuse_trace_id text, "
        "ADD COLUMN langfuse_observation_id text"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "DROP COLUMN langfuse_observation_id, "
        "DROP COLUMN langfuse_trace_id"
    )
```

Confirm `uv run alembic heads` prints exactly one head (the new id). Migrate the lane DB: `uv run alembic upgrade head`; `uv run alembic current` → `<new id> (head)`.

- [ ] **Step 2: The migration test**

`tests/db/test_agent_model_call_langfuse_ids_migration.py`:

```python
"""Lane 3 slice 3a, Task 4: ``agent_model_call`` carries the Langfuse trace and observation ids
(nullable: NULL for Langfuse-off turns and every pre-migration row)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.db.conftest import run_async
from tests.profiling.conftest import (  # noqa: F401
    migrated_db,
    require_profiling_db,
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_agent_model_call_has_nullable_langfuse_ids() -> None:
    async def scenario() -> list[tuple[str, str, str]]:
        async with rollback_conn(seed_pack=False) as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'agent_model_call' "
                    "AND column_name IN ('langfuse_trace_id', 'langfuse_observation_id') "
                    "ORDER BY column_name"
                )
            )
            return [(r[0], r[1], r[2]) for r in rows]

    assert run_async(scenario()) == [
        ("langfuse_observation_id", "text", "YES"),
        ("langfuse_trace_id", "text", "YES"),
    ]
```

Run it on the lane DB → PASS.

- [ ] **Step 3: The receipt fields**

In `turns.py`, after `cost_source: ModelCostSource | None = None`:

```python
    # Lane 3 slice 3: the Langfuse generation this call became (D4) — stamped by the durable
    # recorder from the run registry the LangChain handler fills at model-call start. None when
    # Langfuse is off, and on every receipt replayed from a pre-migration row.
    langfuse_trace_id: str | None = None
    langfuse_observation_id: str | None = None
```

- [ ] **Step 4: The INSERT and the replay compare**

In `agent_turn_wiring.record_model_call`: add ` langfuse_trace_id, langfuse_observation_id` to the INSERT column list (after `cost_source`), `:langfuse_trace, :langfuse_observation` to the VALUES (same position), and to the parameter dict:

```python
                    "langfuse_trace": receipt.langfuse_trace_id,
                    "langfuse_observation": receipt.langfuse_observation_id,
```

In the replay SELECT add `"langfuse_trace_id, langfuse_observation_id, "` after `"cost_usd, cost_source, "`; in `actual` after `row["cost_source"],` add `row["langfuse_trace_id"], row["langfuse_observation_id"],` with the comment `# Lane 3 slice 3: the Langfuse ids are part of the immutable receipt too.`; in `expected` after `receipt.cost_source,` add `receipt.langfuse_trace_id, receipt.langfuse_observation_id,`.

- [ ] **Step 5: The receipt DB tests**

In `tests/api/test_agent_model_call_cost_receipt_db.py`: give `_receipt` two keyword parameters `langfuse_trace_id: str | None = None, langfuse_observation_id: str | None = None` passed through to the receipt; extend `_row` to also select `langfuse_trace_id, langfuse_observation_id` (returning a 4-tuple; update the existing assertions to compare 4-tuples with `None, None` appended). Add:

```python
def test_langfuse_ids_round_trip_and_are_part_of_the_immutable_receipt() -> None:
    async def scenario() -> tuple[tuple[Any, ...], str]:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed_turn(conn)
            journal = DbAgentTurnJournal(conn_factory=conn_session_factory(conn))
            receipt = _receipt(
                seeds,
                sequence=1,
                cost_usd=Decimal("0.01"),
                cost_source="metered",
                langfuse_trace_id="a" * 32,
                langfuse_observation_id="b" * 16,
            )
            await journal.record_model_call(receipt=receipt)
            await journal.record_model_call(receipt=receipt)  # identical replay: accepted
            drifted = receipt.model_copy(update={"langfuse_observation_id": "c" * 16})
            try:
                await journal.record_model_call(receipt=drifted)
            except ValueError as exc:
                refused = str(exc)
            else:
                refused = ""
            return await _row(conn, seeds, 1), refused

    row, refused = run_async(scenario())
    assert row[2:] == ("a" * 32, "b" * 16)
    assert "different immutable receipt" in refused
```

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_agent_model_call_cost_receipt_db.py tests/db/test_agent_model_call_langfuse_ids_migration.py tests/api/test_agent_runtime_wiring_db.py tests/api/test_p32_model_call_role_db.py -q` on the lane DB → PASS.

- [ ] **Step 6: The round trip on a fresh DB**

```bash
set -a; source .env; set +a
BASE="${CLUE_DATABASE_URL%/*}"
psql "${BASE}/postgres" -c 'CREATE DATABASE clue_lane3_smoke'   # adjust: use the same host/user the URL names; if psql is not on PATH, use `docker exec clue-pg-istanbul psql -U clue -c ...`
export CLUE_DATABASE_URL="${BASE}/clue_lane3_smoke"
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
uv run pytest tests/db/test_db_migrations.py -q
psql "${BASE}/postgres" -c 'DROP DATABASE clue_lane3_smoke'
```

Expected: the three alembic commands succeed and the test passes. Record the exact commands used in the report.

- [ ] **Step 7: Gates and commit**

ruff on the changed Python files; `uv run mypy` (4 baseline).

```bash
git add alembic/versions/*_agent_model_call_langfuse_ids.py platform/agents/clue_agents/turns.py platform/api/clue_api/agent_turn_wiring.py tests/db/test_agent_model_call_langfuse_ids_migration.py tests/api/test_agent_model_call_cost_receipt_db.py
git commit -m "feat(db): agent_model_call gains langfuse_trace_id and langfuse_observation_id on the receipt, inserted and compared on replay (lane 3 slice 3a)"
```

---

### Task 5: `clue_api.langfuse_callbacks` — the handler that fills the registry and prices the generation

**Files:**
- Create: `platform/api/clue_api/langfuse_callbacks.py`
- Create: `tests/api/test_langfuse_callbacks.py`

**Interfaces:**
- Consumes: `LangfuseRunRegistry`, `LangfuseIds`, `langfuse_is_installed` (Task 2); `cost_cents_from_metadata`, `ANSWERING_MODEL_KEY` (`clue_gateway.metadata`).
- Produces:
  - `class ClueLangfuseHandler(langfuse.langchain.CallbackHandler)` with `__init__(self, registry: LangfuseRunRegistry)`.
  - `@dataclass(frozen=True) class LangfuseCallbacks: handler: ClueLangfuseHandler; registry: LangfuseRunRegistry`.
  - `build_langfuse_callbacks() -> LangfuseCallbacks | None` (`None` when Langfuse is not installed).

- [ ] **Step 1: The failing test**

`tests/api/test_langfuse_callbacks.py`:

```python
"""Lane 3 slice 3a, Task 5: the LangChain handler fills the run registry at model-call start
and writes the gateway's settled cost onto the generation before it ends."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from clue_api.langfuse_callbacks import build_langfuse_callbacks
from clue_gateway.metadata import ANSWERING_MODEL_KEY, COST_CENTS_KEY, COST_SOURCE_KEY
from clue_obs.langfuse import propagate_trace
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async


def _model(metadata: dict[str, Any]) -> GenericFakeChatModel:
    return GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="hi",
                    response_metadata=metadata,
                    usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                )
            ]
        )
    )


def test_not_installed_builds_nothing() -> None:
    assert build_langfuse_callbacks() is None


def test_the_generation_carries_the_settled_cost_and_the_registry_its_ids() -> None:
    with langfuse_installed() as (exporter, _provider):
        callbacks = build_langfuse_callbacks()
        assert callbacks is not None
        model = _model(
            {"model_name": "x-ai/grok-4.6", ANSWERING_MODEL_KEY: "x-ai/grok-4.6",
             COST_CENTS_KEY: "1.25", COST_SOURCE_KEY: "metered"}
        )
        run_ids: list[Any] = []
        original = callbacks.handler.on_chat_model_start

        def spy(*args: Any, run_id: Any, **kwargs: Any) -> Any:
            run_ids.append(run_id)
            return original(*args, run_id=run_id, **kwargs)

        callbacks.handler.on_chat_model_start = spy  # type: ignore[method-assign]

        async def go() -> None:
            with propagate_trace(trace_name="t", session_id="s", user_id="u"):
                await model.ainvoke("hello", config={"callbacks": [callbacks.handler]})

        run_async(go())
        spans = finished_spans(exporter)
    generation = next(s for s in spans if (s.attributes or {}).get("langfuse.observation.type") == "generation")
    attrs = dict(generation.attributes or {})
    assert attrs["langfuse.observation.cost_details"] == '{"total": 0.0125}'
    assert attrs["langfuse.observation.metadata.clue_cost_source"] == "metered"
    assert attrs["langfuse.observation.model.name"] == "x-ai/grok-4.6"
    assert len(run_ids) == 1
    ids = callbacks.registry.get(run_ids[0])
    assert ids is not None
    assert ids.trace_id == format(generation.context.trace_id, "032x")
    assert ids.observation_id == format(generation.context.span_id, "016x")


def test_an_unpriced_answer_leaves_cost_alone() -> None:
    with langfuse_installed() as (exporter, _provider):
        callbacks = build_langfuse_callbacks()
        assert callbacks is not None
        model = _model({"model_name": "m", COST_CENTS_KEY: "0", COST_SOURCE_KEY: "unpriced"})

        async def go() -> None:
            await model.ainvoke("hello", config={"callbacks": [callbacks.handler]})

        run_async(go())
        spans = finished_spans(exporter)
    attrs = dict(spans[-1].attributes or {})
    assert "langfuse.observation.cost_details" not in attrs
    assert attrs["langfuse.observation.metadata.clue_cost_source"] == "unpriced"
```

- [ ] **Step 2: Run to see it fail** → import error.

- [ ] **Step 3: Implement**

`platform/api/clue_api/langfuse_callbacks.py`:

```python
"""The Langfuse LangChain handler, adapted for the platform (lane 3 slice 3, design §3.3).

The SDK's handler reports the graph — agent, chain nodes, sub-agents, tools, generations — and
keeps each LangChain run's observation in ``self._runs`` from its start event to its end event.
Two things it cannot know are added here: (1) at model-call start, the generation's trace and
observation ids are copied into a :class:`LangfuseRunRegistry` keyed by the LangChain run id, so
the durable recorder (which sees the same run id) stamps them on the ``agent_model_call``
receipt; (2) at model-call end, the gateway's settled cost stamp on the answer is written onto
the generation before the SDK ends it, so Langfuse shows the platform's number (R2), never its
own price-table estimate.

LangChain waits for every handler's start event before the model call proceeds, so the registry
is filled before any end event runs; end events of different handlers run concurrently, which is
why the cost update lives here and not in the recorder.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.outputs import LLMResult
from langfuse.langchain import CallbackHandler

from clue_gateway.metadata import ANSWERING_MODEL_KEY, cost_cents_from_metadata
from clue_obs.langfuse import LangfuseIds, LangfuseRunRegistry, langfuse_is_installed

__all__ = ["ClueLangfuseHandler", "LangfuseCallbacks", "build_langfuse_callbacks"]


class ClueLangfuseHandler(CallbackHandler):
    """The SDK handler plus the registry fill and the cost stamp."""

    def __init__(self, registry: LangfuseRunRegistry) -> None:
        super().__init__()
        self._registry = registry

    def _remember(self, run_id: UUID) -> None:
        current = getattr(self, "_runs", {}).get(run_id)
        trace_id = getattr(current, "trace_id", None)
        if not isinstance(trace_id, str):
            return
        observation_id = getattr(current, "id", None)
        self._registry.remember(
            run_id,
            LangfuseIds(
                trace_id=trace_id,
                observation_id=observation_id if isinstance(observation_id, str) else None,
            ),
        )

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any) -> Any:
        result = super().on_chat_model_start(serialized, messages, run_id=run_id, **kwargs)
        self._remember(run_id)
        return result

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID, **kwargs: Any) -> Any:
        result = super().on_llm_start(serialized, prompts, run_id=run_id, **kwargs)
        self._remember(run_id)
        return result

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> Any:
        current = getattr(self, "_runs", {}).get(run_id)
        if current is not None:
            update = _cost_update(response)
            if update:
                current.update(**update)
        return super().on_llm_end(response, run_id=run_id, **kwargs)


def _cost_update(response: LLMResult) -> dict[str, Any]:
    """What the gateway stamped on the answer, in the SDK's fields. Empty when there is no stamp."""
    try:
        generation = response.generations[-1][-1]
    except IndexError:
        return {}
    message = getattr(generation, "message", None)
    metadata = getattr(message, "response_metadata", None) or {}
    cents, source = cost_cents_from_metadata(metadata)
    update: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    if cents is not None:
        update["cost_details"] = {"total": float(cents / Decimal(100))}
    if source is not None:
        meta["clue_cost_source"] = source
    served = metadata.get(ANSWERING_MODEL_KEY)
    if isinstance(served, str) and served:
        update["model"] = served
        meta["clue_answering_model"] = served
    if meta:
        update["metadata"] = meta
    return update


@dataclass(frozen=True)
class LangfuseCallbacks:
    handler: ClueLangfuseHandler
    registry: LangfuseRunRegistry


def build_langfuse_callbacks() -> LangfuseCallbacks | None:
    """One handler + registry per graph invocation; ``None`` when Langfuse is not installed, so
    callers leave their callback tuples exactly as they were."""
    if not langfuse_is_installed():
        return None
    registry = LangfuseRunRegistry()
    return LangfuseCallbacks(handler=ClueLangfuseHandler(registry), registry=registry)
```

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/api/test_langfuse_callbacks.py -q` → PASS. If the cost assertion sees `0.0125` formatted differently (e.g. `0.012500000000000001`), round in `_cost_update`: `float(round(cents / Decimal(100), 6))`, and match the test.

- [ ] **Step 5: Gates and commit**

ruff; `uv run mypy` (4 baseline; if mypy complains about the override signatures, match the SDK's parameter names exactly — `serialized`, `messages`/`prompts`, keyword `run_id`, `**kwargs` — as written); `uv run lint-imports` (27/0 — the contract's `clue_api.langfuse_callbacks -> langfuse.langchain` edge covers this import).

```bash
git add platform/api/clue_api/langfuse_callbacks.py tests/api/test_langfuse_callbacks.py
git commit -m "feat(api): ClueLangfuseHandler fills the run registry at model-call start and prices the generation with the gateway's settled cost (lane 3 slice 3a)"
```

---

### Task 6: The turn runtime — handler in the tuple, trace named, receipt stamped

**Files:**
- Modify: `platform/api/clue_api/agent_runtime_wiring.py` (`DurableAgentModelCallHandler.__init__`/`on_llm_end`/`_record` ~lines 136–320; `DurableDeepAgentTurnRunner.run` ~lines 1310–1350)
- Modify: `tests/api/test_agent_runtime_wiring_cost_stamp.py`
- Create: `tests/api/test_agent_runtime_langfuse.py`

**Interfaces:**
- Consumes: `LangfuseRunRegistry`, `propagate_trace` (Task 2); `build_langfuse_callbacks` (Task 5); receipt fields (Task 4).
- Produces: `DurableAgentModelCallHandler(..., langfuse_ids: LangfuseRunRegistry | None = None)`.

- [ ] **Step 1: The failing tests**

Append to `tests/api/test_agent_runtime_wiring_cost_stamp.py` (extend `_handler` with an optional `langfuse_ids` parameter passed through):

```python
def test_the_receipt_carries_the_registry_ids_for_its_run() -> None:
    from clue_obs.langfuse import LangfuseIds, LangfuseRunRegistry

    async def scenario() -> Any:
        turns = _Turns()
        registry = LangfuseRunRegistry()
        handler = _handler(turns, langfuse_ids=registry)
        run_id = uuid4()
        registry.remember(run_id, LangfuseIds(trace_id="t" * 32, observation_id="o" * 16))
        await handler.on_chat_model_start({}, [[AIMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_end(_answer({"model_name": "x-ai/grok-4.6"}), run_id=run_id)
        return turns.receipts[0], registry.get(run_id)

    receipt, left = run_async(scenario())
    assert receipt.langfuse_trace_id == "t" * 32
    assert receipt.langfuse_observation_id == "o" * 16
    assert left is None  # popped: the registry does not grow with the turn


def test_without_a_registry_the_ids_are_blank() -> None:
    receipt = run_async(_drive({"model_name": "x-ai/grok-4.6"}))
    assert receipt.langfuse_trace_id is None and receipt.langfuse_observation_id is None


def test_the_gateway_stamp_names_the_answering_model_before_the_provider_field() -> None:
    from clue_gateway.metadata import ANSWERING_MODEL_KEY

    receipt = run_async(
        _drive({ANSWERING_MODEL_KEY: "served/model", "model_name": "served/modelserved/model"})
    )
    assert receipt.answering_model == "served/model"
```

`tests/api/test_agent_runtime_langfuse.py`:

```python
"""Lane 3 slice 3a, Task 6: the turn runner appends the Langfuse handler to the callback tuple
(and only then), names the trace, and leaves the tuple untouched when Langfuse is off."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import AsyncCallbackHandler

from clue_agents.contracts import AgentRole
from clue_agents.execution import AgentExecutionStatus, AgentTurnOutcome
from clue_api.agent_runtime_wiring import (
    DurableAgentModelCallHandler,
    DurableDeepAgentTurnRunner,
    TurnWorkGuard,
)
from clue_api.langfuse_callbacks import ClueLangfuseHandler
from clue_core import ExecutionId
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async


class _Runtime:
    def __init__(self) -> None:
        self.callbacks: tuple[Any, ...] = ()
        self.trace_attrs: dict[str, Any] = {}

    async def run(self, *, request: Any, callbacks: Any, **kwargs: Any) -> AgentTurnOutcome:
        del kwargs
        self.callbacks = tuple(callbacks)
        # Any span opened during the run carries the propagated trace attributes.
        from clue_obs.langfuse import observation

        with observation("probe", as_type="span"):
            pass
        return AgentTurnOutcome(
            turn_id=request.turn_id,
            execution_id=request.constitution.execution_id,
            status=AgentExecutionStatus.COMPLETED,
        )


class _Turns:
    async def mark_running(self, **kwargs: Any) -> None:
        del kwargs

    async def next_model_call_sequence(self, *, turn_id: Any) -> int:
        del turn_id
        return 1

    async def mark_unfinalized(self, **kwargs: Any) -> None:
        del kwargs


def _request() -> Any:
    return SimpleNamespace(
        turn_id=uuid4(),
        thread_id="thread-1",
        constitution=SimpleNamespace(
            workspace_id="ws-1",
            project_id="project-1",
            execution_id=ExecutionId(uuid4()),
            role=AgentRole.HEAD_OF_ABM,
            profile_ref=SimpleNamespace(name="head-of-abm", version="v1"),
            actor_id="user-1",
        ),
    )


def _run(runtime: _Runtime, *, before_work: Any = None) -> None:
    runner = DurableDeepAgentTurnRunner(
        runtime=runtime,  # type: ignore[arg-type]
        turns=_Turns(),  # type: ignore[arg-type]
        artifacts=SimpleNamespace(),  # type: ignore[arg-type]
        before_work=before_work,
    )
    run_async(
        runner.run(
            request=_request(),
            resolved_profile=SimpleNamespace(profile=SimpleNamespace(model=SimpleNamespace(model_id="m"))),  # type: ignore[arg-type]
            context=SimpleNamespace(),  # type: ignore[arg-type]
            lease=SimpleNamespace(backend=None),  # type: ignore[arg-type]
            tools=(),
        )
    )


def test_langfuse_off_leaves_the_callback_tuple_as_it_was() -> None:
    runtime = _Runtime()

    async def guard() -> None:
        return None

    _run(runtime, before_work=guard)
    kinds = [type(cb) for cb in runtime.callbacks]
    assert kinds == [TurnWorkGuard, DurableAgentModelCallHandler]
    assert all(isinstance(cb, AsyncCallbackHandler) for cb in runtime.callbacks)


def test_langfuse_on_appends_the_handler_and_names_the_trace() -> None:
    with langfuse_installed() as (exporter, _provider):
        runtime = _Runtime()
        _run(runtime)
        spans = finished_spans(exporter)
    kinds = [type(cb) for cb in runtime.callbacks]
    assert kinds == [DurableAgentModelCallHandler, ClueLangfuseHandler]
    probe = next(s for s in spans if s.name == "probe")
    attrs = dict(probe.attributes or {})
    assert attrs["langfuse.trace.name"] == "head-of-abm.turn"
    assert attrs["session.id"] == "thread-1"
    assert attrs["user.id"] == "ws-1"
    assert attrs["langfuse.trace.metadata.project_id"] == "project-1"
    assert attrs["langfuse.trace.tags"] == ("head_of_abm",)
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/api/test_agent_runtime_wiring_cost_stamp.py tests/api/test_agent_runtime_langfuse.py -q` → FAIL (`langfuse_ids` unexpected keyword; tuple lacks the handler).

- [ ] **Step 3: The recorder**

In `agent_runtime_wiring.py`:

- imports: `from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler`; `from clue_gateway.metadata import ANSWERING_MODEL_KEY, cost_cents_from_metadata`; `from clue_obs.langfuse import LangfuseRunRegistry, propagate_trace`; `from clue_api.langfuse_callbacks import build_langfuse_callbacks`.
- `DurableAgentModelCallHandler.__init__` gains `langfuse_ids: LangfuseRunRegistry | None = None` (stored as `self._langfuse_ids`).
- `on_llm_end`: the `answering_model` expression becomes

```python
        answering_model = str(
            response_metadata.get(ANSWERING_MODEL_KEY)
            or llm_output.get("model_name")
            or response_metadata.get("model_name")
            or response_metadata.get("model")
            or self._requested_model
        )
```

with the comment `# Lane 3 slice 3: the gateway's own stamp is the served model (fallback-aware, stamped once per stream); the provider's field is the fallback for a call that reached us without one.`

- `_record`: after `sequence, started_at, started_clock, input_ref = pending` add

```python
        langfuse = self._langfuse_ids.pop(run_id) if self._langfuse_ids is not None else None
```

and pass `langfuse_trace_id=langfuse.trace_id if langfuse is not None else None, langfuse_observation_id=langfuse.observation_id if langfuse is not None else None,` to the `AgentModelCallReceipt(...)`.

- [ ] **Step 4: The runner**

In `DurableDeepAgentTurnRunner.run`, replace the block from `model_calls = DurableAgentModelCallHandler(` through the `try:`/`outcome = await self._runtime.run(...)` with:

```python
        # Lane 3 slice 3: the Langfuse handler reports the graph (agent, nodes, sub-agents,
        # tools, generations); its registry hands each generation's ids to the recorder below.
        # ``None`` when Langfuse is off, so the tuple is then exactly what it was.
        langfuse = build_langfuse_callbacks()
        model_calls = DurableAgentModelCallHandler(
            request=request,
            requested_model=resolved_profile.profile.model.model_id,
            initial_sequence=await self._turns.next_model_call_sequence(turn_id=request.turn_id),
            artifacts=self._artifacts,
            turns=self._turns,
            langfuse_ids=langfuse.registry if langfuse is not None else None,
        )
        # FI Lane D D3: attaching the stream handler is also what opts *this* turn into the model's
        # streaming path (the handler is structurally a LangChain streaming consumer). With no
        # stream attached the callback tuple, and therefore the model path, is exactly what it was.
        # The Langfuse handler is a plain BaseCallbackHandler and does not opt the turn in.
        callbacks: tuple[BaseCallbackHandler, ...] = (model_calls,)
        if self._before_work is not None:
            callbacks = (TurnWorkGuard(self._before_work), *callbacks)
        if langfuse is not None:
            callbacks = (*callbacks, langfuse.handler)
        if stream is not None:
            callbacks = (*callbacks, TurnStreamCallbackHandler(emitter=stream))
        constitution = request.constitution
        try:
            with propagate_trace(
                trace_name="head-of-abm.turn",
                session_id=str(request.thread_id),
                user_id=workspace_id,
                metadata={
                    "project_id": constitution.project_id,
                    "turn_id": request.turn_id,
                    "execution_id": constitution.execution_id,
                    "profile": f"{constitution.profile_ref.name}@{constitution.profile_ref.version}",
                    "actor_id": constitution.actor_id,
                },
                tags=(constitution.role.value,),
            ):
                outcome = await self._runtime.run(
                    request=request,
                    resolved_profile=resolved_profile,
                    context=context,
                    backend=lease.backend,
                    governed_tools=tools,
                    callbacks=callbacks,
                )
```

(the existing `except BaseException:` and the rest of the method are unchanged). If `profile_ref` has no `name`/`version` attributes, read the real `AgentResourceRef` fields (`grep -n "class AgentResourceRef" -A 12 platform/agents/clue_agents/contracts.py`) and use them; update the test's `SimpleNamespace` accordingly and say so in the report.

- [ ] **Step 5: Run to see them pass**

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_agent_runtime_wiring_cost_stamp.py tests/api/test_agent_runtime_langfuse.py tests/api/test_agent_runtime_wiring_db.py tests/api/test_lane_d3_turn_stream_db.py -q` (lane DB for the `_db` files) → PASS.

- [ ] **Step 6: Gates and commit**

ruff; `uv run mypy` (4 baseline); `uv run lint-imports` (27/0).

```bash
git add platform/api/clue_api/agent_runtime_wiring.py tests/api/test_agent_runtime_wiring_cost_stamp.py tests/api/test_agent_runtime_langfuse.py
git commit -m "feat(runtime): the Langfuse handler joins the turn's callback tuple under a named trace; receipts carry the generation's Langfuse ids (lane 3 slice 3a)"
```

---

### Task 7: One chunk carries the model keys — the streamed `answering_model` fix

**Files:**
- Modify: `libs/clue-gateway/clue_gateway/agent_model.py` (`_astream_with_fallback` ~lines 724–760; a helper beside `_stamp_answering_model` ~line 1199)
- Modify: `tests/gateway/test_agent_model.py`

**Interfaces:** none new. `_stamp_answering_model` unchanged.

- [ ] **Step 1: The failing test**

Add to `tests/gateway/test_agent_model.py`, after `test_governed_agent_stream_preserves_usage_cost_and_answering_model`:

```python
class TwoModelChunksStreamingModel(StreamingChatModel):
    """A stream whose finish chunk AND usage chunk both carry ``model_name`` — what OpenRouter's
    stream looks like through langchain-openai — the source of the doubled answering model."""

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Any:
        del messages, stop, run_manager, kwargs
        yield ChatGenerationChunk(message=AIMessageChunk(content="streamed "))
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="answer",
                response_metadata={"model_name": "served/x", "finish_reason": "stop"},
            )
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                response_metadata={"model_name": "served/x"},
                usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                chunk_position="last",
            )
        )


def test_a_stream_whose_chunks_repeat_the_model_name_merges_to_one_answering_model() -> None:
    model = GovernedAgentChatModel(
        models=(TwoModelChunksStreamingModel(),),
        model_ids=("served/x",),
        requested_model="requested/model",
        gateway_config=GatewayConfig(),
    )
    chunks = list(model.stream("Stream the answer."))
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert merged.response_metadata["model_name"] == "served/x"
    assert merged.response_metadata["clue_answering_model"] == "served/x"
    assert merged.response_metadata["clue_requested_model"] == "requested/model"
    assert "".join(str(chunk.content) for chunk in chunks) == "streamed answer"
```

(`chunks` are `AIMessageChunk`s from `model.stream`; `+` is LangChain's merge.)

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/gateway/test_agent_model.py -k "repeat_the_model_name" -q` → FAIL (`"served/xserved/x"`).

- [ ] **Step 3: Implement**

Beside `_stamp_answering_model` add:

```python
_MODEL_KEYS: tuple[str, ...] = ("model_name", "model", _ANSWERING_MODEL_KEY)


def _strip_model_keys(message: BaseMessage) -> None:
    """LangChain's chunk merge concatenates equal string metadata, so only ONE chunk of a stream
    may carry the model keys (the last, which is the provider's truthful one)."""
    metadata = message.response_metadata
    if any(key in metadata for key in _MODEL_KEYS):
        message.response_metadata = {k: v for k, v in metadata.items() if k not in _MODEL_KEYS}
```

In `_astream_with_fallback`, replace the inner `async for` loop body with a one-chunk lookahead so the last chunk is the one stamped:

```python
                yielded = False
                pending: ChatGenerationChunk | None = None
                try:
                    async for chunk in model._astream(
                        messages,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    ):
                        if pending is not None:
                            _strip_model_keys(pending.message)
                            yielded = True
                            yield pending
                        pending = chunk
                    if pending is not None:
                        _stamp_answering_model(pending.message, fallback=model_id)
                        yielded = True
                        yield pending
                    return
```

(the `except Exception as exc:` clause and everything after it are unchanged; `yielded` keeps its meaning — set only when a chunk actually left this generator). Apply the identical lookahead to the **sync** `_stream_with_fallback` if one exists with the same per-chunk stamp (`grep -n "_stamp_answering_model(chunk" libs/clue-gateway/clue_gateway/agent_model.py` lists every site; every site must use the lookahead).

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/gateway/test_agent_model.py tests/gateway/test_openrouter_reasoning.py -q` → PASS (the existing streaming test still sees `clue_answering_model == "served/streaming-model"` on the final chunk and the `SPAN_LLM_GATEWAY_CALL` attributes unchanged).

- [ ] **Step 5: Gates and commit**

ruff; `uv run mypy` (4 baseline).

```bash
git add libs/clue-gateway/clue_gateway/agent_model.py tests/gateway/test_agent_model.py
git commit -m "fix(gateway): one chunk per stream carries the model keys, so the merged answer names the answering model once (lane 3 slice 3a)"
```

---

### Task 8: `make langfuse-check` and the stack status line

**Files:**
- Create: `platform/api/clue_api/langfuse_check.py`
- Modify: `Makefile` (after the `cost-report` target), `scripts/dev_stack.sh` (`status()`)
- Create: `tests/api/test_langfuse_check.py`

**Interfaces:**
- Consumes: `auth_check` (Task 2), `Settings`/`Secrets` (Task 1).
- Produces: `clue_api.langfuse_check.main(argv: Sequence[str] | None = None, *, settings: Settings | None = None, secrets: Secrets | None = None, check: Callable[..., bool] = auth_check) -> int` (0 ok; 1 misconfigured or refused; 2 disabled).

- [ ] **Step 1: The failing test**

`tests/api/test_langfuse_check.py`:

```python
"""Lane 3 slice 3a, Task 8: the check verb reads the settings, probes the keys, sends no trace."""

from __future__ import annotations

from typing import Any

import pytest

from clue_api.langfuse_check import main
from clue_config import Secrets, Settings


def _secrets(**kwargs: Any) -> Secrets:
    return Secrets(_env_file=None, **kwargs)  # type: ignore[call-arg]


def test_disabled_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([], settings=Settings(_env_file=None, langfuse_enabled=False), secrets=_secrets())
    assert code == 2
    assert "disabled" in capsys.readouterr().out


def test_enabled_without_keys_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([], settings=Settings(_env_file=None, langfuse_enabled=True), secrets=_secrets())
    assert code == 1
    assert "CLUE_LANGFUSE_PUBLIC_KEY" in capsys.readouterr().out


def test_enabled_with_keys_probes_and_reports(capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[dict[str, str]] = []

    def check(*, public_key: str, secret_key: str, host: str) -> bool:
        seen.append({"public_key": public_key, "secret_key": secret_key, "host": host})
        return True

    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_host="https://cloud.langfuse.com",
        langfuse_environment="lane-test",
    )
    code = main(
        [],
        settings=settings,
        secrets=_secrets(langfuse_public_key="pk", langfuse_secret_key="sk"),
        check=check,
    )
    assert code == 0
    assert seen == [{"public_key": "pk", "secret_key": "sk", "host": "https://cloud.langfuse.com"}]
    out = capsys.readouterr().out
    assert "langfuse: ok" in out and "env=lane-test" in out and "sk" not in out.replace("langfuse", "")


def test_a_refused_key_pair_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [],
        settings=Settings(_env_file=None, langfuse_enabled=True),
        secrets=_secrets(langfuse_public_key="pk", langfuse_secret_key="sk"),
        check=lambda **kwargs: False,
    )
    assert code == 1
    assert "refused" in capsys.readouterr().out
```

- [ ] **Step 2: Run to see it fail** → import error.

- [ ] **Step 3: Implement**

`platform/api/clue_api/langfuse_check.py`:

```python
"""``python -m clue_api.langfuse_check`` — is Langfuse configured and does the host accept the
keys? (lane 3 slice 3, design §3.10). Reads the same settings the roots read, calls the SDK's
auth check with tracing disabled, prints one line, sends no trace. Exit 0 = ok, 1 = misconfigured
or refused, 2 = disabled. ``make langfuse-check`` runs it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from clue_config import Secrets, Settings, load_settings
from clue_obs.langfuse import auth_check

__all__ = ["main"]


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    secrets: Secrets | None = None,
    check: Callable[..., bool] = auth_check,
) -> int:
    del argv  # no flags: the env is the only input
    resolved = settings if settings is not None else load_settings()
    resolved_secrets = secrets if secrets is not None else Secrets()
    if not resolved.langfuse_enabled:
        print("langfuse: disabled (CLUE_LANGFUSE_ENABLED=false)")
        return 2
    public_key = (
        resolved_secrets.langfuse_public_key.get_secret_value().strip()
        if resolved_secrets.langfuse_public_key is not None
        else ""
    )
    secret_key = (
        resolved_secrets.langfuse_secret_key.get_secret_value().strip()
        if resolved_secrets.langfuse_secret_key is not None
        else ""
    )
    missing = [
        name
        for name, value in (
            ("CLUE_LANGFUSE_PUBLIC_KEY", public_key),
            ("CLUE_LANGFUSE_SECRET_KEY", secret_key),
        )
        if not value
    ]
    if missing:
        print(f"langfuse: enabled but missing {', '.join(missing)}")
        return 1
    try:
        accepted = check(public_key=public_key, secret_key=secret_key, host=resolved.langfuse_host)
    except Exception as exc:  # the host unreachable, TLS, DNS — say what, never the keys
        print(f"langfuse: unreachable ({type(exc).__name__}: {exc})")
        return 1
    if not accepted:
        print(f"langfuse: refused the key pair ({resolved.langfuse_host})")
        return 1
    print(
        f"langfuse: ok ({resolved.langfuse_host}, env={resolved.langfuse_environment}, "
        f"public_key={public_key[:8]}…)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

(`load_settings` is what `projections_main` uses; confirm its import path with `grep -n "def load_settings" libs/clue-config/clue_config/*.py` and import from `clue_config` as the roots do.)

`Makefile`, after the `cost-report` target:

```make
# --- Langfuse (lane 3 slice 3) ----------------------------------------------
langfuse-check: ## Is Langfuse enabled and does the host accept the keys? Reads .env; sends no trace
	uv run python -m clue_api.langfuse_check
```

`scripts/dev_stack.sh`, at the end of `status()` (after the fleet-worker lines):

```bash
  load_env
  if [ "${CLUE_LANGFUSE_ENABLED:-false}" = "true" ]; then
    echo "  langfuse: enabled (${CLUE_LANGFUSE_HOST:-https://cloud.langfuse.com}, env=${CLUE_LANGFUSE_ENVIRONMENT:-unset}) — make langfuse-check to verify the keys"
  else
    echo "  langfuse: disabled"
  fi
```

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/api/test_langfuse_check.py -q` → PASS. Run `make langfuse-check` once with the sourced `.env` → prints `langfuse: disabled ...`, exit 2 (expected today). Run `bash -n scripts/dev_stack.sh` → no syntax error.

- [ ] **Step 5: Gates and commit**

ruff; `uv run mypy` (4 baseline); `uv run lint-imports` (27/0).

```bash
git add platform/api/clue_api/langfuse_check.py tests/api/test_langfuse_check.py Makefile scripts/dev_stack.sh
git commit -m "feat(ops): make langfuse-check probes the keys without a trace; the stack status line says whether Langfuse is on (lane 3 slice 3a)"
```

---

### Task 9: Docs — the design note's §7 names, §9 slice 3a, the lane index

**Files:**
- Modify: `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` (§7 lines ~289–294 and ~308; §9 item 3 ~line 343)
- Modify: `docs/superpowers/plans/2026-09-13-lane-plan-index.md` (the lane 3 table row `3`)

- [ ] **Step 1: §7**

Replace the four lines

```
LANGFUSE_HOST=https://cloud.langfuse.com      # EU region project (R4)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
CLUE_LANGFUSE_ENABLED=false                    # off → no handler, no export, no stamping
```

with

```
CLUE_LANGFUSE_ENABLED=false                    # off → no client, no handler, no stamping
CLUE_LANGFUSE_HOST=https://cloud.langfuse.com  # EU region project (R4)
CLUE_LANGFUSE_PUBLIC_KEY=                      # secret
CLUE_LANGFUSE_SECRET_KEY=                      # secret
CLUE_LANGFUSE_ENVIRONMENT=lane-san-salvador
```

and replace the sentence `Slice 2 (2026-09-15) shipped the OTel and Sentry names above; the Langfuse names are slice 3's to settle.` with `Slice 2 (2026-09-15) shipped the OTel and Sentry names; slice 3a (2026-09-15) settled the Langfuse names as CLUE_-prefixed (D3 in its design note): the client attaches to the slice 2 provider, so CLUE_OTEL_TRACES_ENDPOINT stays empty for Langfuse and remains the seam for any other collector.`

- [ ] **Step 2: §9**

Replace item 3 with:

```
3. **Langfuse** (§5.3, R4 hosting; design: `2026-09-15-lane3-slice3-langfuse-design.md`).
   **3a — DONE 2026-09-15:** the client attached to the slice 2 provider (D1), the LangChain
   handler in the turn's callback tuple with the run registry and settled cost on every graph
   generation, receipt ids (D4, migration), payload redaction, `make langfuse-check`, the
   streamed `answering_model` fix. **3b — next:** the research agent and the exit judge, the
   gateway decorator path, provider-caller observations, governed-tool and retriever
   observations, guardrails and events.
```

- [ ] **Step 3: The lane index**

Replace the row `| 3 | (to write) | ... | 2 |` with two rows:

```
| 3a | `2026-09-15-lane3-slice3a-langfuse-foundation.md` | Langfuse on the slice 2 provider; the LangChain handler + run registry in the turn tuple; receipt ids (migration); redaction; `make langfuse-check`; the streamed `answering_model` fix | 2 |
| 3b | `2026-09-15-lane3-slice3b-langfuse-richness.md` | research agent + exit judge traces; gateway generations/embeddings; provider-caller observations with cost; governed-tool/retriever observations; guardrails and events | 3a |
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md docs/superpowers/plans/2026-09-13-lane-plan-index.md
git commit -m "docs(lane3): the design note records slice 3a as done with the CLUE_LANGFUSE_* names; lane index rows 3a/3b"
```

---

## Self-review (done while writing)

- **Spec coverage:** §3.1 → Task 2; §3.2 → Tasks 1, 3; §3.3 runtime part → Tasks 5, 6; §3.8 → Task 4; §3.9 → Task 7; §3.10 → Task 8; §3.11 → Task 1; §5 tests: obs (T2), callbacks (T5), runtime receipts (T4 DB + T6 unit), streaming (T7), migration round trip (T4), parity (T1), lint-imports (T1). §3.3 research agent / summary call, §3.4–§3.7 → plan 3b.
- **Type consistency:** `LangfuseIds(trace_id, observation_id)`, `LangfuseRunRegistry.remember/get/pop`, `build_langfuse_callbacks() -> LangfuseCallbacks | None` with `.handler`/`.registry`, `DurableAgentModelCallHandler(langfuse_ids=)`, receipt fields `langfuse_trace_id`/`langfuse_observation_id`, `install_production_langfuse(settings, secrets, *, runtime, service_name)`, `auth_check(*, public_key, secret_key, host)` — used identically across tasks.
- **Placeholders:** the migration's revision id is generated by alembic (the only "fill in" and it is mechanical); everything else is literal.
