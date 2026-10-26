# Lane 3 slice 5 — cost, tracing and telemetry for the design subsystem — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every dollar the design subsystem spends — the design trio's model calls, the brand-kit ingestion models, image generation, ad-DNA, Brandfetch, Adyntel — lands on the platform's ledgers of record and in Langfuse with its settled cost, and the design API process carries the same OTel and Sentry roots as the fleet.

**Architecture:** The provider-caller seam moves out of ARV2 into a shared package (`libs/clue-spend`) so the design subsystem can put its raw HTTP spend on `provider_call_ledger` without importing platform internals. The design trio keeps the governed gateway it already has; a small sync collector on the design side gathers per-call receipts and the platform persists them as `agent_model_call` rows on the design leg's own turn. Langfuse observations are opened by the platform around the design turn and by the design side around ingestion jobs; the platform's Langfuse handler is injected into the design run as an opaque callback. The three `install_production_*` helpers move to `clue_obs` and the design API root calls them.

**Tech Stack:** Python 3.12, SQLAlchemy text SQL + asyncpg, LangChain callbacks, `clue_obs` (OTel, Sentry, Langfuse SDK v4), httpx, pytest on the lane database.

**Spec:** `docs/superpowers/specs/archive/2026-09-18-lane3-slice5-design-subsystem-design.md` (rulings §6; this plan follows the recommendations). Parent: `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` §5.4.

## Global Constraints

- **Local commits only. Never `git push`, never open a PR.** No AI attribution in commit messages.
- **Never use `git stash`.** Set work aside with a WIP commit.
- **Never run `make check`, the whole pytest suite, or any `*_live.py` test.** Run only the files named per task, always with `-p no:cacheprovider --ignore-glob='*_live.py'`; DB tests need the lane `.env` sourced (`set -a; source .env; set +a`) and use `tests.claimstore.conftest` / `tests.db.conftest.run_async`. Design-subsystem suites run from `subsystems/clue-design` with `PYTHONPATH=.:apps/api:apps/agent_runtime` and only the files named; never the whole `apps/api` suite.
- **No new environment flag.** The existing `CLUE_OTEL_*`, `CLUE_SENTRY_*`, `CLUE_LANGFUSE_*`, `CLUE_RELEASE` govern the design API too. If a task seems to need a new key, stop and escalate.
- **Seam discipline:** nothing under `subsystems/clue-design` imports `clue_api`, `clue_research`, `clue_projections` or any other platform internal. It may import `clue_spend`, `clue_obs`, `clue_gateway`, `clue_config`, `clue_db`, `clue_design`. Declare every such dependency in the two lumen `pyproject.toml` files. The import-linter contracts in the root `pyproject.toml` gain the new edges.
- **One path per spend.** A call is priced and reported exactly once: governed-gateway calls through the gateway stamp; raw HTTP calls through `ProviderCaller`. Never both.
- **Legacy research lane untouched** (parent §11). Design prompts, skills, tools, transports and retry policies untouched.
- **Operation names (verbatim):** `design.image.generate`, `design.image.edit`, `design.ingestion.assist`, `design.ingestion.vision`, `design.ingestion.describe`, `design.ingestion.brief`, `design.ingestion.ad_dna`, `design.ad.style_group`, `design.logo.brand_api`, `design.ad_library.harvest`. Providers: `openrouter`, `brandfetch`, `adyntel`. Trace name `design-leg.turn`; observation names `design-leg.turn` (agent), `design.ingestion.job` (agent). Durable role for trio receipts: `design`.
- **Gates per task:** the named pytest files; `uv run ruff check` and `uv run mypy` on changed platform/lib files; `uv run lint-imports` when a contract changed; the design files' own suites as named.
- Do not dispatch subagents of your own; report back.

---

## File map

| File | Responsibility |
|---|---|
| `libs/clue-spend/` (new: `pyproject.toml`, `clue_spend/__init__.py`, `calls.py`, `sinks.py`, `transport.py`, `openrouter.py`, `ledger.py`) | The provider-caller seam, moved from `platform/api/clue_api/arv2/` (Task 1) |
| `platform/api/clue_api/arv2/{calls,sinks,transport,openrouter,provider_ledger}.py` | Thin re-exports for one release (Task 1) |
| `libs/clue-obs/clue_obs/production.py` | `install_production_*` + lifespan, moved from `clue_api.production_tracing` (Task 2) |
| `platform/api/clue_api/production_tracing.py` | Re-export shim (Task 2) |
| `subsystems/clue-design/apps/api/lumen_api/main.py` | Root instrumentation; spend scopes around the job executors and `/assets/generate` (Tasks 2, 3) |
| `subsystems/clue-design/apps/api/lumen_api/spend.py` (new) | `SpendScope`, `caller()`, `drain()` (Task 3) |
| `subsystems/clue-design/apps/api/lumen_api/image_provider.py`, `lumen_ingestion/{assist,describe}.py`, `lumen_ingestion/capture/pdf_vision.py`, `lumen_ingestion/ad_library/{distill,adyntel}.py`, `lumen_ingestion/logo_vendor.py`, `lumen_api/ad_runtime.py` | Each raw HTTP call becomes a `CallSpec` through the scope's caller (Task 3) |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/usage_collector.py` (new), `harness.py`, `usage_capture.py` (deleted), `trace_callbacks.py` | The collector, its attachment, `_extract_usage` relocation (Task 4) |
| `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py`, `lumen_ingestion/brief_agent.py` | Callback injection; brief-agent collection to ledger (Task 4) |
| `platform/api/clue_api/design_fleet.py`, `design_leg_wiring.py`, `agent_turn_fleet_wiring.py`, `provider_ledger.py`→`clue_spend` surface labels, `platform/projections/clue_projections/cost.py` | Trace, receipts, exit-judge role, incident labels, `NOT_COVERED` (Task 5) |
| `_memory/2026-09-18-lane3-slice5-design-subsystem.md`, `_memory/README.md`, `.env.example` comment | Close-out (Task 6) |

---

### Task 1: `libs/clue-spend` — the provider-caller seam leaves ARV2

**Files:**
- Create: `libs/clue-spend/pyproject.toml`, `libs/clue-spend/clue_spend/__init__.py`, `calls.py`, `sinks.py`, `transport.py`, `openrouter.py`, `ledger.py`
- Modify: `platform/api/clue_api/arv2/calls.py`, `sinks.py`, `transport.py`, `openrouter.py`, `provider_ledger.py` (become re-exports), root `pyproject.toml` (workspace member + import-linter), `uv.lock`
- Test: `tests/spend/test_package_boundary.py` (new), plus the existing `tests/arv2/test_calls.py`, `tests/arv2/test_provider_ledger_db.py`, `tests/arv2/test_sinks.py` (if present) run unchanged

**Interfaces:**
- Consumes: today's `clue_api.arv2.calls.{ProviderCaller, CallSpec, CallCost, CallResult, SpendEstimate, Ceilings, HaltRule, CostReader, CostReading, ProviderHalted}`, `arv2.sinks.{RawSink, LedgerSink, MemoryRawSink, MemoryLedger, BufferedRawSink, BufferedLedger, LedgerRow, RawRecord, SpendTotals}`, `arv2.transport.{HttpRequest, HttpResponse, Transport}` and its httpx implementation, `arv2.openrouter.{openrouter_cost_reader, openrouter_halt_rule}`, `arv2.provider_ledger.{drain_provider_calls, LedgerStamp, DrainReport, ledger_id_for}`.
- Produces: the same names importable from `clue_spend`; `drain_provider_calls(conn, *, raw, ledger, artifacts: ArtifactSink | None, stamp, on_failure: FailureHook | None = None)` where `FailureHook = Callable[[AsyncConnection, LedgerRow, LedgerStamp], Awaitable[None]]`; `HttpxTransport` in `clue_spend.transport`.

- [ ] **Step 1: Boundary test first**

Create `tests/spend/test_package_boundary.py`:

```python
"""clue_spend is the shared home of the provider-caller seam (lane 3 slice 5, parent §5.4 (a)).

It may depend on clue_core/clue_obs/clue_storage and SQLAlchemy; it never imports clue_api,
clue_research or clue_projections, so the design subsystem can import it.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "libs" / "clue-spend" / "clue_spend"
FORBIDDEN = ("clue_api", "clue_research", "clue_projections", "lumen_api", "lumen_agent")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", sorted(PACKAGE.rglob("*.py")), ids=lambda p: p.name)
def test_no_platform_internals(path: Path) -> None:
    offenders = [name for name in _imports(path) if name.split(".")[0] in FORBIDDEN]
    assert not offenders, f"{path.name} imports platform internals: {offenders}"


def test_public_surface() -> None:
    module = importlib.import_module("clue_spend")
    for name in (
        "ProviderCaller", "CallSpec", "CallCost", "CallResult", "SpendEstimate", "Ceilings",
        "ProviderHalted", "RawSink", "LedgerSink", "MemoryRawSink", "MemoryLedger",
        "BufferedRawSink", "BufferedLedger", "LedgerRow", "LedgerStamp", "DrainReport",
        "drain_provider_calls", "ledger_id_for", "HttpRequest", "HttpResponse", "Transport",
        "HttpxTransport", "openrouter_cost_reader", "openrouter_halt_rule",
    ):
        assert hasattr(module, name), name


def test_arv2_names_still_resolve_to_the_shared_classes() -> None:
    from clue_api.arv2 import calls as arv2_calls
    from clue_spend import ProviderCaller

    assert arv2_calls.ProviderCaller is ProviderCaller
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/spend/test_package_boundary.py -p no:cacheprovider -q`
Expected: FAIL — `ModuleNotFoundError: clue_spend`.

- [ ] **Step 3: Create the package**

`libs/clue-spend/pyproject.toml` (mirror `libs/clue-obs/pyproject.toml`'s build-system and name style):

```toml
[project]
name = "clue-spend"
version = "0.1.0"
description = "The provider-caller seam: estimate before the wire, raw before parse, one ledger of record."
requires-python = ">=3.12"
dependencies = [
  "sqlalchemy>=2.0",
  "clue-core",
  "clue-obs",
  "clue-storage",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["clue_spend"]
```

Check the exact build-system block `libs/clue-obs/pyproject.toml` uses and copy it. Add `libs/clue-spend` to the root `pyproject.toml` `[tool.uv.workspace] members` and to the root project's dependencies where `clue-obs` is listed; run `uv sync`.

Move the modules with `git mv`-equivalent content copies:

| From (`platform/api/clue_api/arv2/`) | To (`libs/clue-spend/clue_spend/`) |
|---|---|
| `transport.py` (`HttpRequest`, `HttpResponse`, `Transport`, the httpx implementation — if the httpx class lives elsewhere, e.g. `arv2/http_transport.py`, move it too and name it `HttpxTransport`) | `transport.py` |
| `sinks.py` | `sinks.py` |
| `calls.py` | `calls.py` |
| `openrouter.py` — only `openrouter_cost_reader`, `openrouter_halt_rule` and their private helpers; the OpenRouter *client* stays in ARV2 | `openrouter.py` |
| `provider_ledger.py` — `LedgerStamp`, `DrainReport`, `ledger_id_for`, `_INSERT_LEDGER`, `drain_provider_calls`, `_stamped_failure`, `_surface_for` | `ledger.py` |

Inside the moved files, rewrite intra-package imports (`from clue_api.arv2.sinks import …` → `from .sinks import …`). Two things are platform-specific and must not move:

1. `provider_ledger._record_incidents` calls `clue_api.provider_incidents.record_failure`. Replace it with a hook:

```python
FailureHook = Callable[[AsyncConnection, LedgerRow, LedgerStamp, str], Awaitable[None]]
"""Called once per failed result row after the rows are inserted: (conn, row, stamp, surface)."""


async def drain_provider_calls(
    conn: AsyncConnection,
    *,
    raw: BufferedRawSink,
    ledger: BufferedLedger,
    artifacts: ArtifactSink | None,
    stamp: LedgerStamp,
    on_failure: FailureHook | None = None,
) -> DrainReport:
```

`artifacts=None` means raw bodies are not persisted (rows get `request_artifact_key=None`, `response_artifact_key=None`); keep the existing behaviour when a sink is given. After the inserts, for each result row with a stamped failure call `await on_failure(conn, row, stamp, _surface_for(row, stamp))` when the hook is present. `_surface_for` moves with the module and gains the two design labels:

```python
def _surface_for(row: LedgerRow, stamp: LedgerStamp) -> str:
    if row.operation.startswith("design.ingestion."):
        return "design_ingestion"
    if row.operation.startswith("design."):
        return "design_turn"
    # (existing branches unchanged below)
```

2. `ProviderCaller` opens Langfuse observations via `clue_obs.langfuse` — that dependency is allowed and stays.

- [ ] **Step 4: ARV2 re-exports and the platform hook**

Each of the five ARV2 modules becomes:

```python
"""Re-export shim: the provider-caller seam lives in ``clue_spend`` since lane 3 slice 5."""

from clue_spend.calls import *  # noqa: F401,F403
from clue_spend.calls import __all__  # noqa: F401
```

(one per module, pointing at its new home; keep the OpenRouter client code in `arv2/openrouter.py` and import the two moved functions from `clue_spend.openrouter` at its top so existing `from clue_api.arv2.openrouter import openrouter_cost_reader` keeps working). Ensure each moved module defines `__all__`.

`arv2/provider_ledger.py` keeps one real function so callers do not change:

```python
from clue_spend.ledger import DrainReport, LedgerStamp, ledger_id_for  # noqa: F401
from clue_spend.ledger import drain_provider_calls as _drain


async def drain_provider_calls(conn, *, raw, ledger, artifacts, stamp) -> DrainReport:
    """ARV2's drain: the shared drain with the platform's incident recorder bound."""
    from clue_api.provider_incidents import record_failure

    async def on_failure(conn_, row, stamp_, surface):
        failure = _stamped_failure(row)
        if failure is not None:
            await record_failure(conn_, failure, surface=surface, workspace_id=stamp_.workspace_id, now=row.recorded_at)

    return await _drain(conn, raw=raw, ledger=ledger, artifacts=artifacts, stamp=stamp, on_failure=on_failure)
```

Read the current `_record_incidents` body before writing this and keep its exact `record_failure` call (arguments, the `now` it passes, the "closes only if the provider's last ok row is later" rule); `_stamped_failure` moves to `clue_spend.ledger` and is imported from there.

- [ ] **Step 5: Import-linter and the guard**

In the root `pyproject.toml` import-linter section: add `clue_spend` to the layer/contract where `clue_obs` and `clue_gateway` sit (below `clue_api`), and add a contract forbidding `clue_spend` → `clue_api|clue_research|clue_projections`. `tests/arv2/test_import_guard.py` has an allowlist; add `clue_spend` where `clue_obs` is allowed.

- [ ] **Step 6: Run the moved seam's tests and the boundary**

Run: `set -a; source .env; set +a; uv run pytest tests/spend tests/arv2/test_calls.py tests/arv2/test_provider_ledger_db.py tests/api/test_provider_incidents_db.py tests/api/test_onboarding_evidence_tools.py -p no:cacheprovider --ignore-glob='*_live.py' -q`. Expected: PASS. Then `uv run lint-imports`, `uv run ruff check libs/clue-spend platform/api/clue_api/arv2`, `uv run mypy libs/clue-spend`.

- [ ] **Step 7: Commit**

```bash
git add libs/clue-spend pyproject.toml uv.lock platform/api/clue_api/arv2 tests/spend tests/arv2/test_import_guard.py
git commit -m "refactor(spend): move the provider-caller seam from arv2 into libs/clue-spend; arv2 re-exports; drain takes an incident hook"
```

---

### Task 2: Roots — `clue_obs.production` and the design API's instrumentation

**Files:**
- Create: `libs/clue-obs/clue_obs/production.py`
- Modify: `platform/api/clue_api/production_tracing.py` (shim), `subsystems/clue-design/apps/api/lumen_api/main.py:697-750` (lifespan + app), `subsystems/clue-design/apps/api/pyproject.toml`, `subsystems/clue-design/apps/agent_runtime/pyproject.toml`
- Test: `subsystems/clue-design/apps/api/tests/test_api_root_instrumentation.py` (new), `tests/api/test_production_tracing.py` (existing, if present — run unchanged)

**Interfaces:**
- Consumes: `install_production_tracing(settings, secrets, *, service_name) -> TracingRuntime`, `install_production_sentry(settings, secrets, *, service_name) -> bool`, `install_production_langfuse(settings, secrets, *, runtime, service_name) -> bool`, `production_tracing_lifespan(runtime)` — moved verbatim from `clue_api.production_tracing`.
- Produces: the same four names in `clue_obs.production`; `lumen_api.main` installs them at import of the app module with `service_name="clue-design-api"` and instruments the FastAPI app.

- [ ] **Step 1: Failing design-side test**

Create `subsystems/clue-design/apps/api/tests/test_api_root_instrumentation.py`:

```python
"""The design API root carries the platform's OTel, Sentry and Langfuse installers (lane 3 slice 5)."""

from __future__ import annotations

import importlib

import pytest
from opentelemetry import trace


def test_design_api_installs_tracing_under_its_own_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_OTEL_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv("CLUE_SENTRY_ENABLED", "false")
    monkeypatch.delenv("CLUE_LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("CLUE_LANGFUSE_SECRET_KEY", raising=False)
    import lumen_api.main as main

    importlib.reload(main)
    provider = trace.get_tracer_provider()
    resource = getattr(provider, "resource", None)
    assert resource is not None and resource.attributes.get("service.name") == "clue-design-api"
    assert main.app.state.tracing_runtime is not None
```

If reloading `lumen_api.main` is not viable in this suite (module-level side effects), test the factory instead: expose `install_design_api_telemetry(app) -> TracingRuntime` in `lumen_api/main.py` and call it in the test on a fresh `FastAPI()`; assert the same service name.

- [ ] **Step 2: Run to see it fail**

From `subsystems/clue-design`: `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/python -m pytest apps/api/tests/test_api_root_instrumentation.py -q -p no:cacheprovider`. Expected: FAIL (`service.name` is not set / attribute missing).

- [ ] **Step 3: Move the helpers**

Create `libs/clue-obs/clue_obs/production.py` with the four functions copied verbatim from `platform/api/clue_api/production_tracing.py` (imports become `from clue_config import Secrets, Settings`, `from .langfuse import …`, `from .otel import …`, `from . import get_logger, install_sentry`). `clue_obs` already depends on `clue-config`. Replace `production_tracing.py`'s body with:

```python
"""Re-export shim: the production installers live in ``clue_obs.production`` (lane 3 slice 5)."""

from clue_obs.production import (  # noqa: F401
    install_production_langfuse,
    install_production_sentry,
    install_production_tracing,
    production_tracing_lifespan,
)

__all__ = [
    "install_production_langfuse",
    "install_production_sentry",
    "install_production_tracing",
    "production_tracing_lifespan",
]
```

- [ ] **Step 4: The design API root**

In `subsystems/clue-design/apps/api/lumen_api/main.py`, next to the existing lifespan (`:697-750`):

```python
from clue_config import Secrets, load_settings
from clue_obs.production import (
    install_production_langfuse,
    install_production_sentry,
    install_production_tracing,
    production_tracing_lifespan,
)


def install_design_api_telemetry(app: FastAPI) -> Any:
    """OTel + Sentry + Langfuse at this root, from the same .env the fleet reads.

    The dev stack sources the repo-root .env for this process; the CLUE_OTEL_*/CLUE_SENTRY_*/
    CLUE_LANGFUSE_* keys are the fleet's. Missing Langfuse keys skip with a warning; Sentry off by
    default; no OTLP endpoint means spans are created and dropped — same as the fleet.
    """

    settings = load_settings()
    secrets = Secrets()
    runtime = install_production_tracing(settings, secrets, service_name="clue-design-api")
    install_production_sentry(settings, secrets, service_name="clue-design-api")
    install_production_langfuse(settings, secrets, runtime=runtime, service_name="clue-design-api")
    if settings.otel_instrument_fastapi:
        runtime.instrument_app(app)
    app.state.tracing_runtime = runtime
    return runtime
```

Call it right after `app = FastAPI(...)` (`:750`), and wrap the existing lifespan so `production_tracing_lifespan(app.state.tracing_runtime)` encloses it (flush + shutdown on exit). Read `lifespan` first: it already composes `db_lifespan`; nest the new context manager outermost.

Declare dependencies: add `"clue-obs"`, `"clue-config"`, `"clue-gateway"`, `"clue-spend"` to `apps/api/pyproject.toml` dependencies and `"clue-gateway"`, `"clue-obs"`, `"clue-spend"` to `apps/agent_runtime/pyproject.toml` (the gateway import at `lumen_agent/llm.py` has been undeclared since P3.2). Re-run the design venv's install per `subsystems/clue-design/AGENTS.md` (uv or pip editable, whichever it documents).

- [ ] **Step 5: Run and gate**

The design test from Step 2 → PASS. Platform: `uv run pytest tests/api -k "production_tracing or fleet_wiring" -p no:cacheprovider --ignore-glob='*_live.py' -q` (only files matching those names). `uv run ruff check libs/clue-obs platform/api/clue_api/production_tracing.py`; `uv run mypy libs/clue-obs`. Boot proof: `./scripts/dev_stack_san_salvador.sh restart-api` is not the design API; run `.venv/bin/python -c "import lumen_api.main"` with `PYTHONPATH=.:apps/api:apps/agent_runtime` from `subsystems/clue-design` after `set -a; source ../../.env; set +a` and confirm no exception and the structlog line from `install_production_langfuse`.

- [ ] **Step 6: Commit**

```bash
git add libs/clue-obs/clue_obs/production.py platform/api/clue_api/production_tracing.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/pyproject.toml subsystems/clue-design/apps/agent_runtime/pyproject.toml subsystems/clue-design/apps/api/tests/test_api_root_instrumentation.py
git commit -m "feat(obs): production installers move to clue_obs; the design API root installs OTel, Sentry and Langfuse"
```

---

### Task 3: Design-side spend scope — every raw HTTP spend path on the ledger

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/spend.py`
- Modify: `lumen_api/image_provider.py:893-907, 983-1000`, `lumen_ingestion/describe.py:691-740`, `lumen_ingestion/assist.py:88-115`, `lumen_ingestion/capture/pdf_vision.py:96-135`, `lumen_ingestion/ad_library/distill.py:223-280`, `lumen_ingestion/ad_library/adyntel.py:174-184`, `lumen_ingestion/logo_vendor.py:283-346`, `lumen_api/ad_runtime.py:380-431`, `lumen_api/main.py` (`execute_ingestion_job`, `execute_agent_turn_job`, `execute_web_turn_job`, the `/assets/generate` and edit routes at `:7427/7436`)
- Test: `subsystems/clue-design/apps/api/tests/test_spend_scope.py` (new), `test_ingestion_describe.py`, `test_api.py` (the generate route), `test_logo_vendor.py`, `test_ad_library_provider.py`

**Interfaces:**
- Consumes: `clue_spend.{ProviderCaller, CallSpec, SpendEstimate, HttpRequest, HttpResponse, HttpxTransport, BufferedRawSink, BufferedLedger, LedgerStamp, drain_provider_calls, openrouter_cost_reader, openrouter_halt_rule, ProviderHalted}`; `clue_gateway.agent_model.OpenRouterGenerationCost` (the `/generation?id=` reader) — check its constructor (`base_url`, `api_key`, timeout) and `.lookup(generation_id) -> Decimal | None` method name before use; `clue_db.get_engine`.
- Produces (`lumen_api/spend.py`):
  ```python
  @dataclass
  class SpendScope:
      stamp: LedgerStamp
      caller: ProviderCaller
      raw: BufferedRawSink
      ledger: BufferedLedger
      langfuse_ids: LangfuseRunRegistry | None = None   # Task 4 fills it for the brief agent

  @contextmanager
  def spend_scope(stamp: LedgerStamp) -> Iterator[SpendScope]: ...   # sets the contextvar
  def current_scope() -> SpendScope | None: ...
  def caller() -> ProviderCaller: ...      # the scope's caller, or the unscoped fallback (warns once per process)
  def openrouter_call(*, operation: str, body: dict, label: str, timeout_s: float, api_key: str, base_url: str, estimate_usd: Decimal = Decimal(0), extras: Mapping[str, object] = {}) -> HttpResponse
  async def drain(scope: SpendScope, conn: AsyncConnection) -> DrainReport
  def drain_sync(scope: SpendScope) -> DrainReport    # asyncio.run on a private loop via clue_db.get_engine, for the sync executors
  ```

- [ ] **Step 1: Tests first**

Create `subsystems/clue-design/apps/api/tests/test_spend_scope.py`:

```python
"""Every raw HTTP spend path on the design side goes through one ProviderCaller per unit of work."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

from clue_spend import HttpRequest, HttpResponse, LedgerStamp
from lumen_api import spend


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.sent.append(request)
        return self.responses.pop(0)


def _openrouter_ok(cost: float = 0.0123) -> HttpResponse:
    body = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": cost},
        "model": "x-ai/grok-4.5",
    }
    return HttpResponse(status=200, body=json.dumps(body).encode())


def test_openrouter_call_lands_a_priced_result_row_with_usage_include() -> None:
    transport = _Transport([_openrouter_ok()])
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t", job_id=uuid4()), transport=transport) as scope:
        response = spend.openrouter_call(
            operation="design.ingestion.describe", body={"model": "x-ai/grok-4.5", "messages": []},
            label="describe:3 assets", timeout_s=30.0, api_key="k", base_url="https://or.example/api/v1",
        )
    assert response.status == 200
    sent = json.loads(transport.sent[0].body)
    assert sent["usage"] == {"include": True}
    rows = [row for row in scope.ledger.rows if row.phase == "result"]
    assert len(rows) == 1
    assert rows[0].provider == "openrouter" and rows[0].operation == "design.ingestion.describe"
    assert rows[0].cost_usd == Decimal("0.0123")
    assert rows[0].extras["cost_source"] == "metered" and rows[0].extras["model"] == "x-ai/grok-4.5"


def test_a_402_halts_the_provider_and_raises() -> None:
    import pytest
    from clue_spend import ProviderHalted

    transport = _Transport([HttpResponse(status=402, body=b'{"error":"insufficient credits"}')])
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=transport) as scope:
        with pytest.raises(ProviderHalted):
            spend.openrouter_call(operation="design.ingestion.assist", body={"model": "m", "messages": []},
                                  label="assist", timeout_s=5.0, api_key="k", base_url="https://or.example/api/v1")
        assert scope.caller.halted("openrouter") == "payment_required"


def test_unscoped_calls_record_to_memory_and_warn_once(caplog) -> None:
    transport = _Transport([_openrouter_ok(), _openrouter_ok()])
    spend.reset_unscoped_for_tests(transport=transport)
    for _ in range(2):
        spend.openrouter_call(operation="design.ad.style_group", body={"model": "m", "messages": []},
                              label="style", timeout_s=5.0, api_key="k", base_url="https://or.example/api/v1")
    assert sum(1 for record in caplog.records if "spend.unscoped_call" in record.getMessage()) == 1
```

The `transport=` keyword on `spend_scope` exists for tests; production callers omit it and get `HttpxTransport()`.

- [ ] **Step 2: Run to see it fail**

`PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/python -m pytest apps/api/tests/test_spend_scope.py -q -p no:cacheprovider` from `subsystems/clue-design`. Expected: FAIL — no module `lumen_api.spend`.

- [ ] **Step 3: `lumen_api/spend.py`**

```python
"""The design subsystem's spend seam (lane 3 slice 5).

One ``ProviderCaller`` per unit of work — an ingestion job, a design-leg turn, one API request —
carried in a contextvar so the clients that spend (image provider, ingestion models, ad-DNA,
Brandfetch, Adyntel) do not thread a caller through every signature. The scope drains onto
``provider_call_ledger`` when the unit ends. A call made with no scope open is still recorded
(in memory) and warned about once, so a missed scope is visible and never silently unpriced.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from clue_obs.langfuse import LangfuseRunRegistry
from clue_spend import (
    BufferedLedger,
    BufferedRawSink,
    CallSpec,
    DrainReport,
    HttpRequest,
    HttpResponse,
    HttpxTransport,
    LedgerStamp,
    ProviderCaller,
    SpendEstimate,
    Transport,
    drain_provider_calls,
    openrouter_cost_reader,
    openrouter_halt_rule,
)

log = logging.getLogger(__name__)
_SCOPE: ContextVar["SpendScope | None"] = ContextVar("lumen_spend_scope", default=None)


@dataclass
class SpendScope:
    stamp: LedgerStamp
    caller: ProviderCaller
    raw: BufferedRawSink
    ledger: BufferedLedger
    langfuse_ids: LangfuseRunRegistry | None = None


def _new_scope(stamp: LedgerStamp, transport: Transport | None) -> SpendScope:
    raw, ledger = BufferedRawSink(), BufferedLedger()
    caller = ProviderCaller(
        transport=transport or HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
    )
    return SpendScope(stamp=stamp, caller=caller, raw=raw, ledger=ledger)


@contextmanager
def spend_scope(stamp: LedgerStamp, *, transport: Transport | None = None) -> Iterator[SpendScope]:
    scope = _new_scope(stamp, transport)
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def current_scope() -> SpendScope | None:
    return _SCOPE.get()


_UNSCOPED: SpendScope | None = None
_UNSCOPED_WARNED = False


def reset_unscoped_for_tests(*, transport: Transport | None = None) -> None:
    global _UNSCOPED, _UNSCOPED_WARNED
    _UNSCOPED = _new_scope(LedgerStamp(workspace_id="unscoped"), transport)
    _UNSCOPED_WARNED = False


def caller() -> ProviderCaller:
    global _UNSCOPED, _UNSCOPED_WARNED
    scope = _SCOPE.get()
    if scope is not None:
        return scope.caller
    if _UNSCOPED is None:
        _UNSCOPED = _new_scope(LedgerStamp(workspace_id="unscoped"), None)
    if not _UNSCOPED_WARNED:
        _UNSCOPED_WARNED = True
        log.warning("spend.unscoped_call: a design spend path ran with no spend scope open; rows stay in memory")
    return _UNSCOPED.caller


def openrouter_call(
    *,
    operation: str,
    body: dict,
    label: str,
    timeout_s: float,
    api_key: str,
    base_url: str,
    estimate_usd: Decimal = Decimal(0),
    extras: Mapping[str, object] | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    """One OpenRouter chat/completions call through the scope's caller, priced by its usage block."""

    wire = {**body, "usage": {"include": True}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **(extra_headers or {})}
    request = HttpRequest(
        method="POST", url=base_url.rstrip("/") + "/chat/completions", headers=headers,
        body=json.dumps(wire).encode("utf-8"), timeout_s=timeout_s,
    )
    spec = CallSpec(
        provider="openrouter", operation=operation, label=label, request=request,
        estimate=SpendEstimate(usd=estimate_usd), halt_rule=openrouter_halt_rule,
        cost_reader=openrouter_cost_reader, extras=dict(extras or {}),
    )
    return caller().call(spec).response


async def drain(scope: SpendScope, conn) -> DrainReport:
    return await drain_provider_calls(conn, raw=scope.raw, ledger=scope.ledger, artifacts=None, stamp=scope.stamp)


def drain_sync(scope: SpendScope) -> DrainReport:
    """Drain from a synchronous executor: one private loop, one transaction, same as DesignStoreBridge."""

    from clue_db import get_engine

    async def run() -> DrainReport:
        engine = get_engine()
        async with engine.begin() as conn:
            return await drain(scope, conn)

    return asyncio.run(run())
```

Check `CallResult`'s attribute for the response (`.response`) and `ProviderCaller.__init__`'s required `now` argument against `clue_spend.calls` before finalising; adjust names, not shape. `HttpxTransport` must send `HttpRequest.body` bytes with the given headers and return `HttpResponse(status, headers, body)`; if `clue_spend.transport` lacks one after Task 1, add it there (10 lines over `httpx.request`).

- [ ] **Step 4: Route the five OpenRouter clients through it**

Each `_invoke` keeps its body, its 2-attempt loop semantics (the caller's `max_attempts`/`retry_statuses` replace the hand loop: pass `max_attempts=2` by extending `openrouter_call` with `max_attempts: int = 4`), its parsing, and its swallow-on-failure behaviour, and replaces `httpx.post(url, json=body, headers=headers, timeout=…)` with:

```python
response = spend.openrouter_call(
    operation="design.ingestion.describe",           # per table in the spec §3.4
    body=body, label=f"describe:{len(items)} assets", timeout_s=DEFAULT_TIMEOUT_S,
    api_key=self.api_key, base_url=self.base_url,
)
if response.status >= 400:
    ...existing error path with response.body.decode()[:300]...
payload = json.loads(response.body)
```

Sites and labels: `describe.py` → `design.ingestion.describe`; `assist.py` → `design.ingestion.assist`; `capture/pdf_vision.py` → `design.ingestion.vision`; `ad_library/distill.py` → `design.ingestion.ad_dna`; `ad_runtime.choose_style_group` → `design.ad.style_group` (label `style_group:<n> names`). A `ProviderHalted` propagates out of the ingestion clients (the job must fail loud; see Step 7); `choose_style_group` catches it like every other exception and returns `None` (its contract).

- [ ] **Step 5: Image generation**

In `image_provider.py`:
- `_invoke_chat_completions`: replace the `httpx.post` with `spend.openrouter_call(operation=operation_name, body=body, label=f"image:{config.model_id}", timeout_s=config.timeout_s, api_key=config.api_key, base_url=config.base_url, extra_headers=_openrouter_headers(config) minus Authorization, extras={"api_style": "chat"})`, where `operation_name` is `"design.image.edit"` when `source_images` is given, else `"design.image.generate"`. Keep the `_warn_if_model_not_found` / `ImageGenerationError` path on `response.status >= 400` reading `response.body`.
- `_invoke_images_api`: the same shape against `/images/generations` (or the endpoint it uses today) with `cost_reader=image_generation_cost_reader` — a new reader in `lumen_api/spend.py`:

```python
def image_generation_cost_reader(response: HttpResponse):
    """Images-API responses carry no usage; price from the generation id via OpenRouter's lookup."""
    from clue_spend.calls import CostReading
    try:
        payload = json.loads(response.body)
    except ValueError:
        return CostReading()
    generation_id = payload.get("id")
    if not generation_id:
        return CostReading()
    cost = _generation_lookup().lookup(str(generation_id))
    return CostReading() if cost is None else CostReading(usd=cost, extras={"generation_id": generation_id})
```

`_generation_lookup()` builds `clue_gateway.agent_model.OpenRouterGenerationCost` once from the image model's `base_url`/`api_key`. Read `CostReading`'s fields in `clue_spend.calls` (it is what `openrouter_cost_reader` returns) and match them.
- `_record_request_receipt`: add `"ledger_row_id"` and `"cost_usd"` to the receipt when the scope's ledger has a result row for this call (`scope.ledger.rows[-1]` immediately after the call, guarded by `provider == "openrouter"`), so `design_generation_result.record_json` names the ledger row.

- [ ] **Step 6: Brandfetch and Adyntel**

`logo_vendor.fetch_vendor_family`: replace the `httpx.Client` GET with `caller().call(CallSpec(provider="brandfetch", operation="design.logo.brand_api", label=f"brand:{domain}", request=HttpRequest(method="GET", url=…, headers=…, timeout_s=…), estimate=SpendEstimate(credits=Decimal(1))))`; the 429 → `"quota"` typed refusal is preserved by reading `response.status` (no halt rule — quota is not credit exhaustion). `adyntel._post`: `provider="adyntel"`, `operation="design.ad_library.harvest"`, `estimate=SpendEstimate(credits=Decimal(1))`, `binary=False`. Both without a cost reader: rows record `cost_source=free`, `credits=1` (spec ruling 6.5).

- [ ] **Step 7: Open scopes at the units of work**

In `lumen_api/main.py`:
- `execute_ingestion_job(envelope, *, host, expected_generation=None)`: wrap the body in `with spend.spend_scope(LedgerStamp(workspace_id=envelope.workspace_id, job_id=UUID(str(envelope.job_id)))) as scope:` and `finally: spend.drain_sync(scope)`; wrap the drain in `try/except Exception` that logs `spend.drain_failed` (a ledger failure must not turn a finished job into a failed one — but it must be loud). Add `extras` on every row via `scope.stamp`? No — `LedgerStamp` has no extras; put the brand kit id in each `CallSpec.extras` (`{"brand_kit_id": …}`) at the ingestion clients when the job envelope carries it (read how the clients learn the kit today; if they do not, skip — the job id is the key). A `ProviderHalted` raised by a client sets the job's failure code to `f"provider_refused:openrouter:{reason}"` (find where the job status is written in `execute_ingestion_job` and add the branch).
- `execute_agent_turn_job` / `execute_web_turn_job`: the same scope with `LedgerStamp(workspace_id=envelope.workspace_id, project_id=envelope.project_id, job_id=UUID(str(envelope.run_id)))` (check the envelope's field names for project and run id) around the turn body, drained in `finally`.
- The `/assets/generate` and `/assets/edit` routes: a request-scoped scope with `LedgerStamp(workspace_id=…, project_id=<from the request when present>)`, drained with `await spend.drain(scope, conn)` on the request's connection if the route has one, else `drain_sync` in a thread.

- [ ] **Step 8: Run and gate**

From `subsystems/clue-design`: `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/python -m pytest apps/api/tests/test_spend_scope.py apps/api/tests/test_ingestion_describe.py apps/api/tests/test_api.py apps/api/tests/test_logo_vendor.py apps/api/tests/test_ad_library_provider.py apps/api/tests/test_ad_assets_distill_pregenerate.py -q -p no:cacheprovider`. Existing tests that patched `httpx.post` now patch `lumen_api.spend.caller` or pass a transport — update them to the transport fake from Step 1 rather than weakening assertions. Expected: PASS. Lane DB proof (platform side): `set -a; source .env; set +a; uv run pytest tests/arv2/test_provider_ledger_db.py -p no:cacheprovider -q` still green (the drain with `artifacts=None`).

- [ ] **Step 9: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api/spend.py subsystems/clue-design/apps/api/lumen_api/image_provider.py subsystems/clue-design/apps/api/lumen_api/ad_runtime.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/lumen_ingestion subsystems/clue-design/apps/api/tests
git commit -m "feat(design): every raw HTTP spend path runs through a per-job ProviderCaller and drains onto provider_call_ledger"
```

---

### Task 4: The collector — design model calls become receipts; the Langfuse handler is injected

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/usage_collector.py`
- Modify: `lumen_agent/harness.py:215-271, 963-989`, `lumen_agent/trace_callbacks.py:117-121`, `lumen_agent/budget.py`/`cancellation.py` (no change; reference only), delete `lumen_agent/usage_capture.py`, `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py:169-178, 521-577, 644-658`, `lumen_api/main.py` executors (`callbacks` kwarg), `lumen_ingestion/brief_agent.py:174-184`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_usage_collector.py` (new), `test_deepagent_fs_and_usage.py` (the retirement test now asserts the collector), `apps/api/tests/test_ingestion_brief.py`

**Interfaces:**
- Produces (`lumen_agent/usage_collector.py`):
  ```python
  @dataclass(frozen=True)
  class CollectedModelCall:
      run_id: UUID; sequence: int; requested_model: str; answering_model: str | None
      status: Literal["completed", "failed"]; role: str | None      # clue_role, e.g. design_author
      input_tokens: int; output_tokens: int; cache_read_input_tokens: int
      cost_cents: Decimal | None; cost_source: str | None            # from clue_gateway.metadata
      langfuse_trace_id: str | None; langfuse_observation_id: str | None
      latency_ms: float; error_code: str | None; started_at: datetime; completed_at: datetime
      def as_json(self) -> dict: ...                                   # rides the run result

  class ModelCallCollector(BaseCallbackHandler):
      def __init__(self, *, langfuse_ids: LangfuseRunRegistry | None = None) -> None: ...
      calls: list[CollectedModelCall]

  @dataclass(frozen=True)
  class TurnCallbacks:
      handlers: tuple[BaseCallbackHandler, ...]
      langfuse_ids: LangfuseRunRegistry | None
  ```
  `execute_agent_turn_job(..., callbacks: TurnCallbacks | None = None)` and the web twin; their response dict gains `"model_calls": [call.as_json() ...]`. `build_design_job_handler(*, host_provider=None, checkpointer_factory=..., turn_callbacks_factory: Callable[[], TurnCallbacks | None] | None = None)`.

- [ ] **Step 1: Collector tests**

Create `subsystems/clue-design/apps/agent_runtime/tests/test_usage_collector.py`:

```python
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from lumen_agent.usage_collector import ModelCallCollector


def _result(**metadata):
    message = AIMessage(
        content="ok",
        response_metadata={"model_name": "x-ai/grok-4.6", "clue_role": "design_author", "clue_cost_cents": "1.23",
                           "clue_cost_source": "metered", "clue_answering_model": "x-ai/grok-4.6", **metadata},
        usage_metadata={"input_tokens": 100, "output_tokens": 7, "total_tokens": 107,
                        "input_token_details": {"cache_read": 40}},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_collects_one_priced_call_per_llm_end() -> None:
    collector = ModelCallCollector()
    run_id = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": "x-ai/grok-4.6"})
    collector.on_llm_end(_result(), run_id=run_id)
    (call,) = collector.calls
    assert call.sequence == 1 and call.run_id == run_id
    assert call.requested_model == "x-ai/grok-4.6" and call.answering_model == "x-ai/grok-4.6"
    assert call.role == "design_author" and call.status == "completed"
    assert call.input_tokens == 100 and call.output_tokens == 7 and call.cache_read_input_tokens == 40
    assert call.cost_cents == Decimal("1.23") and call.cost_source == "metered"
    assert call.error_code is None and call.latency_ms >= 0


def test_a_failed_call_is_collected_with_its_error_code() -> None:
    collector = ModelCallCollector()
    run_id = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": "m"})
    collector.on_llm_error(TimeoutError("slow"), run_id=run_id)
    (call,) = collector.calls
    assert call.status == "failed" and call.error_code == "timeout_error" and call.answering_model is None


def test_as_json_round_trips_decimals_as_strings() -> None:
    collector = ModelCallCollector()
    run_id = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": "m"})
    collector.on_llm_end(_result(), run_id=run_id)
    payload = collector.calls[0].as_json()
    assert payload["cost_cents"] == "1.23" and payload["run_id"] == str(run_id)
```

- [ ] **Step 2: Run to see it fail**

`PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/python -m pytest apps/agent_runtime/tests/test_usage_collector.py -q -p no:cacheprovider`. Expected: FAIL — module missing.

- [ ] **Step 3: The collector**

```python
"""Per-call receipts for the design runtime's governed model calls (lane 3 slice 5).

The design trio runs on the platform's governed gateway, which stamps every answer with the
answering model, the settled cost and the role (``clue_gateway.metadata``). This handler collects
those stamps into ``CollectedModelCall`` records that ride the turn result; the platform turns
them into ``agent_model_call`` rows on the design leg's own turn. It is synchronous because the
design agent invokes synchronously on a worker thread. It never prices anything itself.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from clue_gateway.metadata import ANSWERING_MODEL_KEY, ROLE_KEY, cost_cents_from_metadata
from clue_obs.langfuse import LangfuseRunRegistry
from langchain_core.callbacks import BaseCallbackHandler

from .trace_callbacks import extract_usage


@dataclass(frozen=True)
class CollectedModelCall:
    run_id: UUID
    sequence: int
    requested_model: str
    answering_model: str | None
    status: Literal["completed", "failed"]
    role: str | None
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cost_cents: Decimal | None
    cost_source: str | None
    langfuse_trace_id: str | None
    langfuse_observation_id: str | None
    latency_ms: float
    error_code: str | None
    started_at: datetime
    completed_at: datetime

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["run_id"] = str(self.run_id)
        data["cost_cents"] = None if self.cost_cents is None else str(self.cost_cents)
        data["started_at"] = self.started_at.isoformat()
        data["completed_at"] = self.completed_at.isoformat()
        return data


def _error_code(error: BaseException) -> str:
    name = type(error).__name__
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class ModelCallCollector(BaseCallbackHandler):
    raise_error = False

    def __init__(self, *, langfuse_ids: LangfuseRunRegistry | None = None) -> None:
        super().__init__()
        self._langfuse_ids = langfuse_ids
        self._pending: dict[UUID, tuple[int, str, datetime, float]] = {}
        self._sequence = 0
        self.calls: list[CollectedModelCall] = []

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any) -> None:
        params = kwargs.get("invocation_params") or {}
        model = str(params.get("model") or (kwargs.get("metadata") or {}).get("ls_model_name") or "unknown")
        self._sequence += 1
        self._pending[run_id] = (self._sequence, model, datetime.now(UTC), time.monotonic())

    on_llm_start = on_chat_model_start

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            return
        metadata = _response_metadata(response)
        usage = extract_usage(response) or {}
        cents, source = cost_cents_from_metadata(metadata)
        self._append(run_id, pending, status="completed",
                     answering_model=str(metadata.get(ANSWERING_MODEL_KEY) or metadata.get("model_name") or pending[1]),
                     role=metadata.get(ROLE_KEY), usage=usage, cents=cents, source=source, error_code=None)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            return
        self._append(run_id, pending, status="failed", answering_model=None, role=None, usage={},
                     cents=None, source=None, error_code=_error_code(error))

    def _append(self, run_id, pending, *, status, answering_model, role, usage, cents, source, error_code) -> None:
        sequence, requested, started_at, started_clock = pending
        ids = self._langfuse_ids.pop(run_id) if self._langfuse_ids is not None else None
        self.calls.append(CollectedModelCall(
            run_id=run_id, sequence=sequence, requested_model=requested, answering_model=answering_model,
            status=status, role=role, input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cost_cents=cents, cost_source=source,
            langfuse_trace_id=getattr(ids, "trace_id", None), langfuse_observation_id=getattr(ids, "observation_id", None),
            latency_ms=(time.monotonic() - started_clock) * 1000, error_code=error_code,
            started_at=started_at, completed_at=datetime.now(UTC)))


def _response_metadata(response: Any) -> dict[str, Any]:
    try:
        generation = response.generations[0][0]
        return dict(getattr(generation.message, "response_metadata", None) or {})
    except (AttributeError, IndexError):
        return {}


@dataclass(frozen=True)
class TurnCallbacks:
    """What the platform injects into a design run: opaque LangChain handlers and the id registry."""

    handlers: tuple[BaseCallbackHandler, ...] = ()
    langfuse_ids: LangfuseRunRegistry | None = None
```

`extract_usage`: move `_extract_usage` from `usage_capture.py` into `trace_callbacks.py` as a public `extract_usage` (same body, plus `cache_read_input_tokens` from `usage_metadata["input_token_details"]["cache_read"]` when present), update `trace_callbacks.py:117-121` to use it, delete `usage_capture.py`, and delete/relocate its tests in `test_deepagent_fs_and_usage.py` (the `UsageCaptureHandler` tests go; the retirement test at `:691` now asserts a `ModelCallCollector` is present on the invoke config's callbacks). Verify `LangfuseRunRegistry.pop` returns an object with `trace_id`/`observation_id` attributes (see `clue_obs/langfuse.py:402-419`).

- [ ] **Step 4: Attach in the harness**

In `harness.py` at the invoke config (`:963`):

```python
        collector = ModelCallCollector(langfuse_ids=(callbacks.langfuse_ids if callbacks else None))
        invoke_config = {
            "recursion_limit": 200,
            "configurable": {"thread_id": thread_id or tools.run_id},
            # Config-level callbacks see every model, tool and sub-agent event in the graph
            # (instance-level ones see only on_llm_*). The platform's Langfuse handler rides here
            # so the whole design run nests under the design-leg observation with settled cost.
            "callbacks": [collector, *((callbacks.handlers) if callbacks else ())],
        }
```

`callbacks: TurnCallbacks | None` is a new keyword on the harness's run entry point (find the function that builds `invoke_config` and its caller chain from `execute_agent_turn_job`; thread the kwarg through, default `None`). After the run, the harness returns `collector.calls` alongside its result; `execute_agent_turn_job` / `execute_web_turn_job` put `"model_calls": [c.as_json() for c in calls]` into the response dict on every path that returns a terminal status (success and failure). Confirm in `fleet_handler._execute_turn` that `response` is what is persisted as the run's `result_json` (it is passed to the store's finish call); if a different dict is persisted, put `model_calls` on that one.

Delete the stale comment at `harness.py:503-504` about `usage_capture`.

- [ ] **Step 5: Thread the injection through the fleet handler**

`fleet_handler.py`:

```python
def build_design_job_handler(*, host_provider=None, checkpointer_factory=postgres_design_checkpointer,
                             turn_callbacks_factory: Callable[[], TurnCallbacks | None] | None = None):
    return DesignJobWorkHandler(host_provider=host_provider, checkpointer_factory=checkpointer_factory,
                                turn_callbacks_factory=turn_callbacks_factory)
```

`DesignJobWorkHandler.__init__` stores it; `_execute` passes `self._turn_callbacks_factory` to `_execute_turn`, which calls it once per turn (`callbacks = factory() if factory else None`) and forwards `callbacks=callbacks` to the executor. `_build_embedded_fleet_worker` passes no factory (the design API has no platform handler; its runs still collect receipts into `result_json` and open their own generations under the process's Langfuse client, without the cost update — acceptable: the embedded worker is a dev convenience).

- [ ] **Step 6: The ingestion brief agent**

`brief_agent.py:174-184`: after `init_model(...)`, attach a `ModelCallCollector` instance-level (the same `model.callbacks` pattern as `attach_trace_callback`) and, when the run finishes, convert each collected call to a ledger row on the current spend scope:

```python
from lumen_api import spend
from clue_spend import LedgerRow

scope = spend.current_scope()
if scope is not None:
    for call in collector.calls:
        scope.ledger.record(LedgerRow(
            ...  # provider="openrouter", operation="design.ingestion.brief", label="brief",
                 # phase="result", outcome="ok" if call.status == "completed" else "client_error",
                 # cost_usd=None if call.cost_cents is None else call.cost_cents / 100,
                 # extras={"model": call.answering_model, "prompt_tokens": call.input_tokens,
                 #         "completion_tokens": call.output_tokens, "cost_source": call.cost_source or "unpriced",
                 #         "langfuse_trace_id": ..., "langfuse_observation_id": ...},
                 # latency_ms, attempts=1, recorded_at=call.completed_at, call_id=call.run_id
        ))
```

Read `LedgerRow`'s dataclass (`clue_spend.sinks`) and fill every required field; put this conversion in `lumen_api/spend.py` as `record_collected_model_call(scope, call, *, operation, label)` so it is written once. Note the cost-source vocabulary difference (`unpriced` on the gateway, `free` on the ledger): map gateway `unpriced` → ledger `estimate` with `estimate_usd=0` recorded, and say so in the docstring.

- [ ] **Step 7: Run and gate**

From `subsystems/clue-design`: `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/python -m pytest apps/agent_runtime/tests/test_usage_collector.py apps/agent_runtime/tests/test_deepagent_fs_and_usage.py apps/agent_runtime/tests/test_deepagent_per_role_models.py apps/agent_runtime/tests/test_trace_callbacks_and_viewer.py apps/api/tests/test_ingestion_brief.py apps/api/tests/test_spend_scope.py -q -p no:cacheprovider`. Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent subsystems/clue-design/apps/agent_runtime/tests subsystems/clue-design/apps/api/lumen_api/fleet_handler.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/lumen_ingestion/brief_agent.py subsystems/clue-design/apps/api/lumen_api/spend.py subsystems/clue-design/apps/api/tests
git commit -m "feat(design-agent): collect per-call receipts from the governed gateway; accept injected turn callbacks; brief-agent calls on the ledger"
```

---

### Task 5: Platform — the design-leg trace, the receipts, the judge's role, the cost read

**Files:**
- Modify: `platform/api/clue_api/design_fleet.py:419-436`, `platform/api/clue_api/design_leg_wiring.py:1438-1540`, `platform/api/clue_api/agent_turn_fleet_wiring.py:1660-1671`, `platform/projections/clue_projections/cost.py:59-64`, `tests/projections/test_cost_cli.py`
- Test: `tests/api/test_design_leg_receipts_db.py` (new), `tests/api/test_design_fleet.py` (existing, if present), `tests/projections/test_cost_cli.py`, `tests/projections/test_cost_db.py`

**Interfaces:**
- Consumes: `build_langfuse_callbacks() -> LangfuseCallbacks | None` (`clue_api.langfuse_callbacks`), `propagate_trace`, `observation`, `tag_entities` (`clue_obs.langfuse`), `DbAgentTurnJournal.record_model_call`, `AgentModelCallReceipt`, `lumen_agent.usage_collector.TurnCallbacks` (imported lazily in `design_fleet`, like `fleet_handler` is), `CollectedModelCall.as_json()` shape from Task 4.
- Produces: `build_design_leg_lane_driver(..., turn_callbacks_factory=...)`; `receipts_from_design_run(run_result: Mapping, *, request: AgentTurnRequest) -> tuple[AgentModelCallReceipt, ...]` in `design_leg_wiring.py`; the `design-leg.turn` trace; exit judge built with `role=AgentRole.DESIGN`; `NOT_COVERED` without the design entry.

- [ ] **Step 1: DB test for the receipts**

Create `tests/api/test_design_leg_receipts_db.py`:

```python
"""A design run's collected model calls become agent_model_call rows on the design leg's turn."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from clue_agents.contracts import AgentRole
from clue_api.design_leg_wiring import receipts_from_design_run
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _collected(sequence: int, *, status: str = "completed", role: str = "design_author") -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "run_id": str(uuid4()), "sequence": sequence, "requested_model": "x-ai/grok-4.6",
        "answering_model": "x-ai/grok-4.6" if status == "completed" else None, "status": status,
        "role": role, "input_tokens": 120, "output_tokens": 9, "cache_read_input_tokens": 40,
        "cost_cents": "0.87" if status == "completed" else None,
        "cost_source": "metered" if status == "completed" else None,
        "langfuse_trace_id": "t1", "langfuse_observation_id": f"o{sequence}", "latency_ms": 812.5,
        "error_code": None if status == "completed" else "timeout_error",
        "started_at": now, "completed_at": now,
    }


def test_receipts_carry_the_design_role_and_the_gateway_cost(design_turn_request) -> None:
    receipts = receipts_from_design_run(
        {"model_calls": [_collected(1), _collected(2, status="failed")]}, request=design_turn_request
    )
    assert [r.sequence for r in receipts] == [1, 2]
    assert all(r.role is AgentRole.DESIGN for r in receipts)
    assert receipts[0].cost_usd == Decimal("0.008700") and receipts[0].cost_source == "metered"
    assert receipts[0].langfuse_observation_id == "o1"
    assert receipts[1].status == "failed" and receipts[1].error_code == "timeout_error"
    assert receipts[1].cost_usd is None


def test_a_run_without_model_calls_yields_no_receipts(design_turn_request) -> None:
    assert receipts_from_design_run({}, request=design_turn_request) == ()
```

`design_turn_request` is a fixture in the same file building an `AgentTurnRequest` with `role=AgentRole.DESIGN` the way `design_leg_wiring.py:897-912` does (copy that construction with placeholder ids; it needs no DB). The DB half — the rows landing — is covered by extending `tests/api/test_p32_model_call_role_db.py` with one test that writes a `receipts_from_design_run` receipt through `DbAgentTurnJournal.record_model_call` on a seeded design `agent_turn` and reads back `role='design'` and `cost_usd`; mirror that file's existing seed.

- [ ] **Step 2: Run to see it fail**

`env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_design_leg_receipts_db.py -p no:cacheprovider -q`. Expected: FAIL — `ImportError: receipts_from_design_run`.

- [ ] **Step 3: Receipts and the trace in `design_leg_wiring.py`**

```python
def receipts_from_design_run(
    run_result: Mapping[str, Any], *, request: AgentTurnRequest
) -> tuple[AgentModelCallReceipt, ...]:
    """The design run's collected model calls as receipts on the leg's own turn.

    The collector on the design side stamped each call from the governed gateway's metadata; this
    only re-keys them onto the platform's turn and writes ``role=design`` (the profile role, the
    one the ledger's CHECK knows). The sub-role stays in Langfuse and the logs.
    """

    receipts: list[AgentModelCallReceipt] = []
    for item in run_result.get("model_calls") or ():
        cents = item.get("cost_cents")
        cost_usd = None if cents is None else (Decimal(str(cents)) / Decimal(100)).quantize(Decimal("0.000001"))
        receipts.append(
            AgentModelCallReceipt(
                model_call_id=UUID(str(item["run_id"])),
                turn_id=request.turn_id,
                execution_id=request.constitution.execution_id,
                workspace_id=request.constitution.workspace_id,
                sequence=int(item["sequence"]),
                requested_model=str(item["requested_model"]),
                answering_model=item.get("answering_model"),
                status=AgentModelCallStatus(item["status"]),
                input_tokens=int(item.get("input_tokens") or 0),
                cache_read_input_tokens=int(item.get("cache_read_input_tokens") or 0),
                cache_creation_input_tokens=0,
                output_tokens=int(item.get("output_tokens") or 0),
                cost_millicredits=0,
                cost_usd=cost_usd,
                cost_source=item.get("cost_source"),
                langfuse_trace_id=item.get("langfuse_trace_id"),
                langfuse_observation_id=item.get("langfuse_observation_id"),
                latency_ms=float(item.get("latency_ms") or 0.0),
                error_code=item.get("error_code"),
                role=AgentRole.DESIGN,
                started_at=datetime.fromisoformat(item["started_at"]),
                completed_at=datetime.fromisoformat(item["completed_at"]),
            )
        )
    return tuple(receipts)
```

Check `AgentModelCallStatus`'s member values (`completed`/`failed`) against `clue_agents.turns`; the collector emits those two strings. In `_dispatch`, around `await self._lane.drive(envelope=envelope)` (`:1535`):

```python
        doc_kind = str(pinned_document.get("doc_kind") or "")
        with propagate_trace(
            trace_name="design-leg.turn",
            session_id=submission.thread_id,
            user_id=workspace_id,
            metadata={
                "project_id": submission.project_id, "turn_id": str(turn_request.turn_id),
                "execution_id": str(execution_id), "leg_id": str(leg_id),
                "document_id": str(pinned_document.get("id") or ""), "doc_kind": doc_kind,
            },
            tags=("design", doc_kind) if doc_kind else ("design",),
        ), observation("design-leg.turn", as_type="agent", input={"doc_kind": doc_kind}):
            tag_entities([str(pinned_document.get("id") or "")])
            await self._lane.drive(envelope=envelope)
        async with self._conn_factory() as conn:
            run = await design_runs.get_run(conn, workspace_id=workspace_id, run_id=run_id)
        if run is None or run["status"] not in _TERMINAL_RUN_STATUSES:
            raise RuntimeError("the design lane returned without a terminal design run")
        for receipt in receipts_from_design_run(run.get("result_json") or {}, request=turn_request):
            await self._turns.record_model_call(receipt=receipt)
        return run
```

Read how `propagate_trace`/`observation` are used at `agent_runtime_wiring.py:1423-1434` and match their exact keyword names. If `pinned_document` is not the object carrying id/doc_kind here, take them from `leg`. Confirm the run row column that holds the executor's response (`result_json`) by reading `design_runs.get_run`.

- [ ] **Step 4: Inject the Langfuse handler from `design_fleet`**

```python
def build_design_leg_lane_driver(*, enabled: bool, preference_resolver_factory=None):
    from clue_api.langfuse_callbacks import build_langfuse_callbacks

    def turn_callbacks():
        from lumen_agent.usage_collector import TurnCallbacks  # lazy, like fleet_handler

        built = build_langfuse_callbacks()
        if built is None:
            return TurnCallbacks()
        return TurnCallbacks(handlers=(built.handler,), langfuse_ids=built.registry)

    handler = build_design_job_handler(
        enabled=enabled, purpose="design_leg_inline_lane",
        preference_resolver_factory=preference_resolver_factory,
        turn_callbacks_factory=turn_callbacks,
    )
```

and thread `turn_callbacks_factory` through the platform-side `build_design_job_handler` wrapper in `design_fleet.py` into lumen's `build_design_job_handler(..., turn_callbacks_factory=...)`.

- [ ] **Step 5: The exit judge's role**

`agent_turn_fleet_wiring.py:1663-1671`: add `role=AgentRole.DESIGN.value` to `models.build(...)` (check the `build` signature at `clue_gateway/agent_model.py:958-1006` for the parameter name). No durable receipt (spec §3.2).

- [ ] **Step 6: The cost read**

`cost.py:59-64`: delete the design entry from `NOT_COVERED`; the comment above gains "Slice 5 put the design subsystem's providers and the design trio's receipts on the ledgers." Update `tests/projections/test_cost_cli.py` (the fixture at `:85-100` uses `NOT_COVERED` directly, so it follows; if any assertion names "design subsystem", change it to assert the remaining entry). Add one row-level test in `tests/projections/test_cost_db.py`: seed a `provider_call_ledger` result row with `provider='openrouter', operation='design.ingestion.describe'` and an `agent_model_call` row with `role='design'`, and assert both appear in `cost_report` under their provider line and turn-receipt line respectively.

- [ ] **Step 7: Run and gate**

`set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_design_leg_receipts_db.py tests/api/test_p32_model_call_role_db.py tests/api/test_design_fleet.py tests/projections/test_cost_cli.py tests/projections/test_cost_db.py tests/api/test_cost_report_endpoint_db.py -p no:cacheprovider --ignore-glob='*_live.py' -q` (drop `test_design_fleet.py` if it does not exist). `uv run ruff check` + `uv run mypy` on the four platform files.

- [ ] **Step 8: Commit**

```bash
git add platform/api/clue_api/design_fleet.py platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/agent_turn_fleet_wiring.py platform/projections/clue_projections/cost.py tests/api/test_design_leg_receipts_db.py tests/api/test_p32_model_call_role_db.py tests/projections
git commit -m "feat(design-leg): design-leg.turn trace with injected Langfuse handler; design model calls become agent_model_call receipts; exit judge carries the design role; cost read no longer excludes design"
```

---

### Task 6: Close-out — env comment, memory, live-proof checklist

**Files:**
- Modify: `.env.example` (the OTel/Sentry/Langfuse block comment: "installed at the projections API, the fleet worker and the design API"), `_memory/README.md`
- Create: `_memory/2026-09-18-lane3-slice5-design-subsystem.md`

- [ ] **Step 1: Env comment**

Find the comment above `CLUE_OTEL_TRACES_ENDPOINT=` in `.env.example` and add the design API to its list of roots. No key changes; parity stays.

- [ ] **Step 2: Memory note**

Write `_memory/2026-09-18-lane3-slice5-design-subsystem.md`: the rulings taken (spec §6), the commit list of Tasks 1–5, the seam move (what moved, what re-exports), the collector-to-receipt path, the spend-scope path and its unscoped fallback, the incident labels, and the **owed live proofs** (founder-triggered, on the lane stack after restart):

1. One web-page design turn → `design-leg.turn` in Langfuse with priced generations; `SELECT sequence, role, answering_model, cost_usd, cost_source FROM agent_model_call WHERE role='design' ORDER BY started_at DESC LIMIT 10` shows the trio's calls; `make cost-report ARGS="--workspace … --project …"` includes them.
2. One brand-kit ingestion → `SELECT operation, cost_usd, extras_json->>'model' FROM provider_call_ledger WHERE operation LIKE 'design.ingestion.%' AND phase='result'` shows describe/vision/assist/brief rows keyed by the job; a `design.logo.brand_api` row with `credits=1`.
3. One image generation from the agent and one from the editor route → `design.image.generate` rows with `cost_source` metered or estimate.
4. A forced 402 (a wrong OpenRouter key on the ingestion model) → job `failure_code=provider_refused:openrouter:auth_invalid` or `payment_required`, and a Sentry incident event.
5. The design API root: a FastAPI span under `clue-design-api` in the OTLP target (or the tracer provider's resource name in a log line), one forced exception in Sentry with run context.

Add the README row.

- [ ] **Step 3: Restart the lane stack and record**

`./scripts/dev_stack_san_salvador.sh down` / `up` (outputs to files), status, then run proof 1 only if the founder asks (it spends money); otherwise leave all five as owed.

- [ ] **Step 4: Commit**

```bash
git add .env.example _memory/2026-09-18-lane3-slice5-design-subsystem.md _memory/README.md
git commit -m "docs(memory): lane 3 slice 5 — design subsystem cost, tracing and telemetry; owed live proofs"
```

---

## Self-review (2026-09-18, against the spec)

- **Spec coverage.** §3.1 → Task 1. §3.2 → Task 4 (collector) + Task 5 (receipts, judge role). §3.3 → Task 5 (trace, observation, tags, injected handler) + Task 4 (config-level attachment). §3.4 → Task 3 (all ten operations; brief agent via Task 4 Step 6; scopes at the three unit kinds; halt → job failure code; incident labels via Task 1's `_surface_for`). §3.5 → Task 2. §3.6 → Task 5 Step 6. §3.7 / §4 → no new env; Task 6 comment only. §7 acceptance 1–5 are the owed live proofs in Task 6; 6 is Task 5 Step 6; 7 is each task's gate.
- **Rulings assumed (spec §6):** 6.1 role `design` (Task 5 Step 3); 6.2 `libs/clue-spend` (Task 1); 6.3 ingestion on the ledger incl. the brief agent (Task 3/4); 6.4 `clue_obs.production` (Task 2); 6.5 Brandfetch/Adyntel `free` + `credits=1` (Task 3 Step 6); 6.6 the editor's generate route drains inline (Task 3 Step 7). A different ruling changes only the named step.
- **Type consistency.** `TurnCallbacks(handlers, langfuse_ids)` is defined in Task 4 and consumed in Tasks 4 and 5; `CollectedModelCall.as_json()` keys are exactly what `receipts_from_design_run` reads; `spend.openrouter_call` signature matches its five call sites; `drain_provider_calls(..., artifacts=None, on_failure=...)` is defined in Task 1 and used in Task 3's `drain`; `_surface_for` labels defined in Task 1 are the ones Sentry shows.
- **Verifications the implementer must do, not invent:** `CallResult.response` and `ProviderCaller.__init__(now=...)` (Task 3), `CostReading` fields (Task 3 Step 5), `LedgerRow` required fields (Task 4 Step 6), `LangfuseRunRegistry.pop` return shape (Task 4 Step 3), `AgentModelCallStatus` values and the run row's `result_json` column (Task 5 Step 3), `models.build`'s role parameter name (Task 5 Step 5), `propagate_trace`/`observation` keyword names (Task 5 Step 3). Each is a read of an existing signature named with its file.
- **Sequencing.** Task 1 before 3 (design imports `clue_spend`); Task 2 before 4 (dependency declarations); Task 4 before 5 (`TurnCallbacks`, `model_calls`). Tasks 1 and 2 are independent of each other.
