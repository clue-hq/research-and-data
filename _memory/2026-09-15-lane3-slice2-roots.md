# 2026-09-15 — Lane 3 slice 2: the roots — OpenTelemetry, Sentry, run context, trace propagation

Branch `lane3/sice1b` (continues after slice 1b; unpushed). Design:
`docs/superpowers/specs/2026-09-15-lane3-slice2-roots-design.md` (D1–D3). Plan:
`docs/superpowers/plans/2026-09-15-lane3-slice2-roots.md`. Commits: `3f6ea1ba8` (design),
`057ac12c3` (plan), `ef32972da` (T1 settings/secrets/deps/env parity), `2e751e58c` (T2
`clue_obs.otel.install` + propagation), `19c5c35a8` (T3 `clue_obs.sentry`), `609e67a9f` (T4 fleet
carrier + per-task context), `d702dac4b` (T5 roots), `17a47fc74` (T6 docs), and this note.

## What landed
- Settings `otel_traces_endpoint`, `otel_instrument_fastapi`, `otel_instrument_httpx`, `sentry_enabled`,
  `sentry_environment`, `release`; secrets `sentry_dsn`, `otel_traces_headers`; all documented in
  `.env.example` (plus the three `CLUE_METRICS_*` names the code already read — a pre-existing parity
  gap closed). Deps on `clue-obs`: the FastAPI/httpx instrumentors 0.63b1 and sentry-sdk 2.69.
- `clue_obs.otel.install_tracing(process_name, endpoint, headers, instrument_httpx, set_global)` → one
  `TracerProvider` per process (service name; OTLP/HTTP only with an endpoint), set as OTel's global
  AND as `traced_step`'s provider (`tracing.use_provider`), with `RunContextSpanProcessor` copying the
  bound structlog context (`RUN_CONTEXT_KEYS`, 15 id/enum keys) onto every span through
  `safe_attributes`; `TracingRuntime.instrument_app(app)` (FastAPI, at construction) and
  `shutdown()`. `bind_and_annotate(**fields)` binds AND stamps the current span (needed for fields
  learnt after a span opened). `carrier_from_current_span()` / `context_from_carrier()` are the W3C seam.
- `clue_obs.sentry.install_sentry(dsn, environment, release, process_name)` with the ruled posture
  (PII off, locals off, `traces_sample_rate=0`, `before_send` = secret redaction over extra/contexts/
  request + bound ids as tags); `capture(exc)` no-op unless installed.
- Fleet: `enqueue_task` stamps `traceparent`/`tracestate` into the payload only under a live span (both
  enqueue paths converge on it); the worker runs every handler inside `bound_context(task_id, work_id,
  fleet_kind, task_attempt, worker_id, + workspace/project/run/job/turn/thread/account ids from the
  payload)` and a `fleet.task` span parented on the carrier; `capture` at its three catch sites.
- Roots (`d702dac4b`): `clue_api.production_tracing` (`install_production_tracing`,
  `install_production_sentry` — enabled with no DSN refuses at composition — and
  `production_tracing_lifespan` beside the metrics lifespan). `projections_main.build_application`
  installs both at import and hands the runtime to `create_projections_app(tracing=)`, which
  instruments the app at construction and adds a request-context middleware (binds and echoes
  `X-Request-Id`, reusing the frontend-read envelope's id when it minted one); the header and the
  authenticated tenant seams `bind_and_annotate(workspace_id=)`; the turn submission binds project,
  thread and turn; `fleet_main._serve` installs before its lifespans and the five sweep loops
  `capture(exc)`. `auth_wiring._request_id` became the public `request_id_for`.
- Docs (`17a47fc74`): the parent design note's §3 run-context row corrected (bound at the roots since
  slice 2; before that nothing in production called the bind helpers), §7 block moved to the shipped
  `CLUE_*` names (the Langfuse lines kept for slice 3), §9 item 2 DONE; the lane index row 2 names this
  slice's plan.

## Proof (zero spend)
- Whole-slice run on the lane DB (ambient vars stripped): 336 green across tests/test_obs_*.py, tests/test_telemetry_settings.py, tests/fleet, tests/gateway, tests/projections, the request-context, projections-app, fleet-wiring, cost-endpoint, evidence-tool, toolbelt-wiring, display-pages and contacts api files, the arv2 settings/ledger/openrouter/driver/persona/display files and the authority audit; ruff clean; mypy exactly the 4 pre-existing errors; lint-imports 26/0; both roots import with the shipped defaults (no exporter, Sentry off); no migration, no R11/R12/frontend file, no attribution trailer, no new `os.environ` read.
- The Task 5 request-context test proves the server span carries `request_id` and `workspace_id`; the Task 4 tests prove the payload carries `traceparent` under a live span and the worker restores the trace and binds the ids.

## Rulings taken (all in the SDD ledger, repeated here)
1. The FastAPI test drives the app with `ASGITransport` in the same task (a `TestClient` portal thread
   never sees contextvars bound in the test thread).
2. No private SDK attribute assertions.
3. `bind_and_annotate` exists because the server span opens before route dependencies bind the workspace.
4. The httpx instrumentor wraps the real HTTP transport, so mock/ASGI-transport clients emit no client
   span; the test uses a loopback server; the request-context test asserts the server span only.
5. T4 test corrections: worker kwargs are floats; the fake queue hands back `WorkTaskRow`; `WorkId` and
   `ProjectRunId` are UUID NewTypes.
6. The FastAPI instrumentor patches `build_middleware_stack`, so its server span wraps every user
   middleware: the request-context middleware also `bind_and_annotate`s the request id onto the
   already-open span (found RED by the Task 5 implementer).
7. The design note's §7 block keeps its Langfuse lines (slice 3's) and replaces only the OTel/Sentry
   names with the shipped `CLUE_*` ones.

## Pre-existing, attributed, not fixed
- The design note's claim that structlog already carried run context in production was false (no
  production caller of `bind_*`); slice 2 binds it at the roots (D3) and the note is corrected.
- Ambient `.env` leaks (see the slice 1b note) still fail otherwise-green tests when sourced.

## Deferred minors
- `sentry_environment` defaults to `lane-san-salvador` (the spec's value) — a deployment beyond the lane
  must set `CLUE_SENTRY_ENVIRONMENT` (founder's call).
- `install_tracing` swaps the module-local provider process-wide without a restore seam.
- `clue_obs.sentry._installed` has no reset seam.
- `auth_wiring`'s provision route and `PrincipalError` handler mint their own request id via
  `request_id_for(request)` instead of reading `request.state.request_id`; with no incoming header it
  can differ from the middleware-bound one (one-line follow-up).
- `CLUE_PROJECTIONS_AUTH_MODE` joined the ambient-leak list; `tests/api/test_c7_production_readers.py`
  has a pre-existing query-count-ceiling failure (`assert 33 <= 31`, three parametrised cases) that
  reproduces with slice 2's files reverted.

## Verification owed (founder-triggered)
- After a stack restart with `CLUE_OTEL_TRACES_ENDPOINT` set (slice 3's Langfuse, or any OTLP/HTTP
  receiver), one turn submitted from the frontend: the API request span and the worker's `fleet.task`
  span share one trace id; the worker's log lines for the turn carry `turn_id`/`workspace_id`;
  `fleet_task.payload_json` for that turn holds `traceparent`.
- With `CLUE_SENTRY_ENABLED=true` + a DSN: one forced exception in a sweep loop appears in Sentry with
  the workspace/run tags and no local variables.
