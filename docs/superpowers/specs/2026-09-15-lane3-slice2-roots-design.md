# Lane 3 slice 2 — the roots: OpenTelemetry, Sentry, run context, trace propagation — design

**Status:** approved in chat 2026-09-15 (decisions D1–D3 below). Parent: the telemetry and cost
design note (`2026-09-14-telemetry-and-cost-observability-design.md`, §4, §5.1, §5.2, §7, §9
slice 2, §10 items 2, 6, 7, 8). Rulings R6 (Sentry posture), R7 (OTel export target), R9
(deferred instrumentors), R11 (legacy lane untouched), R12 (design subsystem held).

## 1. Purpose

After this slice every production process exports OpenTelemetry spans and Sentry events that carry
the run context, the trace started by the HTTP request that enqueues a turn or a job survives into
the fleet worker that runs it, and every flag the code reads is in `.env.example`. All of it is off
by default: an unconfigured process behaves exactly as today.

Slice 3 (Langfuse) plugs into these roots; nothing here knows Langfuse exists.

## 2. What exists, and one correction (verified 2026-09-15)

- `clue_obs.otel.tracing`: `traced_step` / `traced` over a **module-local** `TracerProvider`;
  `configure_tracing(exporter=)` swaps it; `collect_spans()` is the test helper. No production
  root calls `configure_tracing`: spans are created and dropped.
- `clue_obs.otel.attributes.safe_attributes`: the one redaction chokepoint for span attributes
  (a curated allowlist coerced natively; everything else name-and-value redacted).
- `clue_obs.context`: `bind_*` helpers over `structlog.contextvars`. **Correction to the parent
  note §3:** no production code calls them. Log lines carry run ids only where a caller passes
  them explicitly. Milestone item 6 is therefore not met today; this slice meets it.
- Metrics precedent: `clue_api.production_metrics.production_metrics_lifespan(settings,
  service_name=)` installs an OTLP metric exporter at two roots — `projections_main` (the
  platform API on 8020/8030, which also serves chat) and `fleet_main`. `trial_main` is excluded;
  the design API root is held (R12). **Parity gap:** the three `CLUE_METRICS_*` settings the code
  reads are absent from `.env.example`.
- The fleet: `clue_fleet.queue.enqueue_task` serialises a task's `payload` into
  `fleet_task.payload_json`; `clue_fleet.work_worker.LeasedWorkWorker` claims a task, builds a
  `WorkContext(payload=task.payload, ...)` and awaits `handler.handle(context)`, catching failures
  at three sites (`worker.slot_crashed`, `worker.heartbeat_crashed`, `worker.work_error`).
  Every payload already carries the ids the handler needs (`workspace_id`, `project_id`,
  `thread_id`, `turn_id` for turns; `job_id`, `run_id`, `workspace_id` for research jobs; and
  so on).
- Installed: `opentelemetry-api/sdk/exporter-otlp-proto-http` 1.42 (through `clue-obs`), and
  `opentelemetry.propagate`. Not installed: the FastAPI and httpx instrumentors, `sentry-sdk`.

## 3. Design

### 3.1 `clue_obs.otel.install` — one provider, one trace

`clue_obs.otel.install.install_tracing(*, process_name: str, endpoint: str | None,
headers: Mapping[str, str] | None, instrument_httpx: bool) -> TracingRuntime`:

- builds one `TracerProvider` with `Resource(service.name=process_name)`;
- adds an OTLP HTTP `BatchSpanProcessor` **only** when `endpoint` is set (else spans are created
  and stay in-process, today's behaviour);
- adds `RunContextSpanProcessor`, whose `on_start` copies the currently bound structlog context
  (`structlog.contextvars.get_contextvars()`) onto the span through `safe_attributes`;
- sets the provider as the OTel **global** provider and hands it to `configure_tracing`, so the
  instrumentors' spans and `traced_step`'s spans are one trace (the module-local provider stays
  the test seam: `collect_spans()` is unchanged);
- instruments httpx process-wide (`HTTPXClientInstrumentor().instrument()`) when asked;
- returns `TracingRuntime` with `instrument_app(app: FastAPI)` (the FastAPI instrumentor,
  applied at app **construction**, before the first request — Starlette refuses middleware after
  startup) and `async shutdown()` (flush the batch processor).

`clue_api.production_tracing` wraps it for the roots: `install_production_tracing(settings,
secrets, *, service_name)` reads the settings, and `production_tracing_lifespan(runtime)` flushes
on shutdown, beside `production_metrics_lifespan`. `projections_main.build_application()` installs
it and instruments the app it builds; `fleet_main._serve()` installs it before the lifespans.

The allowlist in `safe_attributes` gains the run-context keys that are ids or enums, never text:
`project_id`, `thread_id`, `turn_id`, `job_id`, `account_id`, `task_id`, `work_id`, `request_id`,
`actor`, `profile_version`, `fleet_kind`, `task_attempt`, `worker_id`.

### 3.2 `clue_obs.sentry` — errors with ids, never customer text (R6)

`clue_obs.sentry.install_sentry(*, dsn: str | None, environment: str, release: str | None,
process_name: str) -> bool`: `sentry_sdk.init(dsn=, environment=, release=,
send_default_pii=False, include_local_variables=False, traces_sample_rate=0.0,
before_send=_before_send, default_integrations=True)`; returns whether it installed (no DSN →
`False`, nothing initialised). `_before_send` runs `redact_value` over the event's `extra` and
`request` sections and copies the bound run context onto `event["tags"]` (same keys as 3.1).
`clue_obs.sentry.capture(exc: BaseException) -> None` is a no-op unless installed.

The fleet worker's three catch sites and `fleet_main`'s sweep-loop catch sites call
`capture(exc)` beside their existing `log.exception`. Sentry's FastAPI/Starlette integration is
auto-enabled by the SDK when the packages are present; the OTel/Sentry tracing integration is not
enabled (OTel owns tracing, R7).

### 3.3 Run context is bound at the roots (D3)

- **API.** `header_workspace_resolver` and the authenticated workspace resolver call
  `bind_workspace(workspace_id)`. A request-id middleware installed by `create_projections_app`
  binds `request_id` (the incoming `X-Request-Id` when present, else a new uuid) and echoes it
  on the response; the context is cleared at request end (`bound_context`).
- **Turn submission.** `agent_turn_submission` binds `project_id`, `thread_id`, `turn_id` for the
  rest of the request once the turn row exists.
- **Fleet worker.** Around every `handler.handle(context)` the worker binds `task_id`,
  `work_id`, `fleet_kind`, `task_attempt`, `worker_id` and every well-known id present in the
  payload (`workspace_id`, `project_id`, `run_id`, `job_id`, `turn_id`, `thread_id`,
  `account_id`) with `bound_context`, so structlog lines, span attributes (3.1) and Sentry tags
  (3.2) all carry them without per-handler edits.

### 3.4 Trace propagation through the fleet payload (D1)

- `enqueue_task` injects the current W3C context (`opentelemetry.propagate.inject`) into the
  payload under `"traceparent"` (and `"tracestate"` when present) **only when a valid span is
  active**; with no span the payload is unchanged, so every existing enqueue test holds.
- The worker, before `handler.handle`, extracts that context from the payload and opens a
  `fleet.task` span (`fleet_kind`, `task_id`, `work_id`, `task_attempt` attributes) as a child of
  it — the handler's spans, the drivers' `traced_step`s and every instrumented httpx call nest
  under the request's trace. A payload without a `traceparent` starts a new trace.
- No migration: `fleet_task.payload_json` already persists the id.

### 3.5 Env parity (D2, §7)

Settings (`CLUE_` prefix, read through `Settings` / `Secrets`, all in `.env.example` and `.env`):

```
# --- Telemetry (lane 3 slice 2) ---
CLUE_OTEL_TRACES_ENDPOINT=            # empty → spans stay in-process (today's behaviour)
CLUE_OTEL_TRACES_HEADERS=             # secret; "k=v,k2=v2" (Langfuse basic auth in slice 3)
CLUE_OTEL_INSTRUMENT_FASTAPI=true
CLUE_OTEL_INSTRUMENT_HTTPX=true
CLUE_SENTRY_ENABLED=false
CLUE_SENTRY_DSN=                      # secret
CLUE_SENTRY_ENVIRONMENT=lane-san-salvador
CLUE_RELEASE=                         # empty → Sentry release unset
```

plus the pre-existing gap: `CLUE_METRICS_EXPORTER=memory`, `CLUE_METRICS_OTLP_ENDPOINT=`,
`CLUE_METRICS_EXPORT_INTERVAL_MS=10000`. `Settings` validates: `sentry_enabled` with no DSN
refuses at composition (loud, like the metrics rule); a non-empty `otel_traces_headers` parses
as `k=v` pairs.

### 3.6 Dependencies

`libs/clue-obs/pyproject.toml` gains `opentelemetry-instrumentation-fastapi`,
`opentelemetry-instrumentation-httpx` (the versions that match the installed 1.42 / 0.63b1 line)
and `sentry-sdk`. `clue_obs` remains a base library the import-linter contracts allow everywhere.

## 4. What does not change

- No legacy research-lane file (R11), no design-subsystem file (R12), no frontend file.
- No SQLAlchemy / asyncpg / Redis instrumentation (R9); no sampling; no Langfuse (slice 3).
- `traced_step` callers keep working unchanged; their spans now leave the process when an
  endpoint is configured.
- No migration.

## 5. Testing

- `tests/test_obs_install.py`: the processor copies bound context onto spans through
  `safe_attributes` (a secret-named key is masked); `install_tracing` with no endpoint exports
  nothing and sets the global provider; httpx instrumentation yields a client span under a
  parent (an in-process ASGI/mock transport, no network); `instrument_app` on a tiny FastAPI app
  yields a server span with the request id attribute.
- `tests/test_obs_sentry.py`: `install_sentry(dsn=None)` returns False and `capture` is a no-op;
  with a stub transport, an event carries the bound tags, no local variables, redacted extras.
- `tests/fleet/test_trace_propagation_db.py`: enqueue under an active span → the stored payload
  carries `traceparent`; a worker claiming it runs the handler inside a span with the same trace
  id and the bound ids; enqueue with no span → payload unchanged.
- `tests/api/test_request_context_db.py`: a request through the projections app carries
  `X-Request-Id` back and the workspace/request ids are bound during the handler.
- `tests/arv2/test_settings.py` parity: every new variable in `.env.example`; the metrics gap
  closed.
- Live proof (founder-triggered, after a stack restart): one turn submitted from the frontend
  leaves `traceparent` in its `fleet_task.payload_json`, and the worker's log lines for that turn
  carry the same trace id as the API's request line.

## 6. Deferred

- The OTLP endpoint has nothing to receive until slice 3 composes Langfuse; the exporter path is
  exercised in tests against an in-process receiver only.
- Per-handler spans beyond `fleet.task` (the turn runtime already opens its own).
