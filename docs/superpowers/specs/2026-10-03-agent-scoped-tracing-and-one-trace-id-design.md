# Agent-scoped Langfuse tracing and one trace id across tools — design

**Status:** approved in chat 2026-10-03 (founder). Parent: the telemetry and cost observability
design (`2026-09-14-telemetry-and-cost-observability-design.md`) and its Langfuse slice
(`2026-09-15-lane3-slice3-langfuse-design.md`). This document **supersedes slice 3's D1 export
rule** (Langfuse exports every span on the shared provider except health checks) and **slice 2's
D1 trace join** (a fleet task runs inside the trace of whatever enqueued it).

## 1. Why

Found on the first production day (2026-10-03):

- **Langfuse is flooded with web requests.** Of ~1,200 traces in `clue-prod` that day, ~1,195 were
  FastAPI request traces (`GET /auth/v1/session`, `…/principal`, page polls). Langfuse is attached to
  the process's shared tracer provider, and its export filter was "everything except health checks",
  so every request the frontend makes became a trace. Inside agent traces, raw httpx `POST` spans
  (118 in one research trace) duplicated the `provider.http_attempt` observations beside them, and
  an empty `llm.gateway_call` generation (no usage, no cost) duplicated every
  `GovernedAgentChatModel` generation.
- **Production traces were labelled `default`.** The Langfuse client stamps `production` on the
  spans it creates (verified: every `langfuse-sdk` observation was `production`); the FastAPI,
  httpx and `clue_research` spans carry no environment, and the trace took its label from them.
- **One chat message produced one giant trace.** A fleet task joined the trace of whatever enqueued
  it, so a chat turn and every research job it launched were one trace (one message → 2 research
  agents → 1,300 observations; 50 accounts would be 50 agents in one tree).
- **A Sentry error could not be followed anywhere.** Sentry runs with tracing off and invents its
  own trace id, which matches nothing in Langfuse or the logs. Log lines carry no trace id at all.
- **Harmless tool refusals page Sentry.** `log_span` logs every exception at error level, and
  Sentry's logging integration turns error logs into events, so an agent calling
  `read_discovery_run` before discovery ran (a refusal the agent repairs on its own) became issue
  CLUE-PRODUCTION-3.

## 2. Requirements

- **R1 — Langfuse holds the agent harness only.** Langfuse exports a span only when it is an
  agent/LLM span: Langfuse's own `langfuse.span_filter.is_default_export_span` (spans from the
  `langfuse-sdk` scope — the agent tree the LangChain handler reports, our `observation()` helpers,
  the gateway's `gateway.completion` generation, provider observations — plus `gen_ai.*` spans and
  known LLM instrumentors). FastAPI server spans, httpx client spans and our plain `clue_research`
  spans (`fleet.task`, `traced_step`, `llm.gateway_call`) never reach Langfuse. Model calls made
  outside an agent (display pages, exit judge, brand brief) stay in Langfuse: they go through the
  gateway's `gateway.completion` observation. A filtered parent leaves the top Langfuse observation
  as the trace root (Langfuse's documented behaviour); trace-level fields come from
  `propagate_trace`, which every agent entry point already sets.
- **R2 — Production traces are labelled `production`.** A consequence of R1 (every exported span is
  stamped by the client with `CLUE_LANGFUSE_ENVIRONMENT`); pinned by a test, no new setting.
- **R3 — One fleet task is one trace.** The `fleet.task` span starts a new trace instead of
  joining the enqueuer's. It carries a span link to the enqueuer's span and binds
  `launched_by_trace_id` into the run context, so it reaches every log line and the Langfuse trace
  metadata (`propagate_trace` adds it). A chat turn, each research job, each display page and each
  design job is its own trace, linked back to what launched it. An account research job's trace
  carries the tag `account:<domain>`.
- **R4 — Every log line carries the trace.** Both log chains (`clue_obs` and the design subsystem's
  `py_lumen_obs`) stamp `trace_id` and `span_id` (32/16 lowercase hex, the ids Langfuse shows) from
  the current OpenTelemetry span. An error logged after its span closed (the fleet worker's
  `worker.work_error`) carries the trace id the exception was raised under: the `fleet.task` span
  stamps it on the exception as it escapes.
- **R5 — Every Sentry event carries the same trace id.** `before_send` sets the event's trace
  context (`contexts.trace.trace_id` / `span_id`) to the current OpenTelemetry span — or the id
  stamped on the exception — adds a `trace_id` tag, and a `langfuse` context with
  `{CLUE_LANGFUSE_HOST}/trace/<trace_id>` (Langfuse redirects that path to the owning project).
  Sentry's own tracing stays off; this only labels events.
- **R6 — Expected refusals are warnings.** `log_span` logs `PreconditionFailed` and
  `ToolAwaitingInput` at warning (no traceback), so they never become Sentry events; every other
  exception stays at error.

## 3. Out of scope (follow-ups, agreed in chat)

- **PR 2 — one place to search:** export all spans (requests, workers) to Grafana Cloud Tempo
  through the existing `CLUE_OTEL_TRACES_ENDPOINT` and ship logs to Grafana Cloud Loki, so a trace
  id pasted into Grafana shows every log line from Railway and the VM. Needs a Grafana token with
  logs-write and traces-write (founder).
- **Frontend:** Sentry for Next.js and an `X-Trace-Id` response header shown on user-facing errors.

## 4. Verification

- Unit tests per requirement (export filter by scope; environment on every exported span; fleet task
  is a new root with a link and `launched_by_trace_id`; log lines carry the ids in both packages and
  for an exception logged after its span; Sentry event trace context, tag and Langfuse link; refusal
  at warning, other errors at error).
- After deploy, in production: the Langfuse trace list holds only agent/model traces, all
  `production`; one chat turn that launches research shows one turn trace plus one trace per job,
  each with `launched_by_trace_id`; a worker log line's `trace_id` opens the same trace in Langfuse.
