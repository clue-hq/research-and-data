# Lane 3 slice 3 — Langfuse: the agent-tree viewer over the slice 2 roots — design

**Status:** approved in chat 2026-09-15 (decisions D1–D4 below); 3a and 3b executed 2026-09-15. Parent: the telemetry and cost
design note (`2026-09-14-telemetry-and-cost-observability-design.md`, §5.3, §7, §9 slice 3, §10).
Rulings R2 (Postgres is the cost authority), R3 (payload redaction), R4 (Langfuse cloud EU), R7
(one OTel export target), R11 (legacy lane untouched), R12 (design subsystem held).

## 1. Purpose

After this slice, every chat turn, every ARV2 research job and every non-graph model call the
platform makes is visible in Langfuse as one trace: the fleet task or HTTP request at the root,
the agent's graph under it (agent, chain nodes, sub-agents, tools, generations), every governed
tool's platform-side decision, every paid provider hop with what it cost, and every guardrail
that stopped or refused work. Each observation carries the ids that join it back to Postgres, and
Postgres carries the Langfuse ids that join it back to the tree. Payloads are redacted before
export. All of it is off unless enabled with keys: an unconfigured process behaves exactly as it
does after slice 2.

This slice also fixes the doubled `answering_model` on streamed turns, found in slice 1.

## 2. What exists (verified 2026-09-15)

- **Slice 2 roots.** `clue_obs.otel.install_tracing` builds the process's one `TracerProvider`
  (`TracingRuntime.provider`), `RunContextSpanProcessor` copies the bound run context onto every
  span, the FastAPI and httpx instrumentors emit server and client spans, the fleet worker opens a
  `fleet.task` span from the payload's `traceparent`, and `clue_api.production_tracing` composes
  it at `projections_main` and `fleet_main`. `Settings` has `otel_traces_endpoint`,
  `sentry_environment`, `release`; `Secrets` has `otel_traces_headers`.
- **The turn runtime.** `agent_runtime_wiring.DurableAgentTurnRunner.run` builds the callback
  tuple `(TurnWorkGuard?, DurableAgentModelCallHandler, TurnStreamCallbackHandler?)` and passes it
  to `clue_agents.runtime.run(callbacks: Sequence[BaseCallbackHandler])`, which builds the deep
  agent graph and invokes it. `DurableAgentModelCallHandler.on_chat_model_start` records the
  pending call per LangChain `run_id`; `on_llm_end` reads usage, `answering_model` and the
  gateway's cost stamp (`cost_cents_from_metadata`) and writes an `AgentModelCallReceipt`
  through `DbAgentTurnJournal.record_model_call` (INSERT, replay compares every column).
- **The ARV2 research agent.** `arv2/account_research_agent.py` builds `create_agent(...)` with
  middleware and calls `agent.ainvoke(opening, config=RunnableConfig(recursion_limit=...))`; no
  callbacks are attached. `_ModelUsageRecorder` writes each model round onto the job's ledger.
- **Direct chat-model calls outside a graph.** `agent_turn_fleet_wiring.py:1661` awaits a
  gateway chat model's `ainvoke(prompt)` directly (the design leg's exit judge); no callbacks are attached.
- **The gateway decorator.** `clue_gateway.tracing.TracingGateway.complete/embed` wrap the inner
  gateway in the `llm.gateway_call` span and call `record_model_call`. `clue_gateway.factory`
  wraps every gateway it builds. Non-graph callers: `clue_api.claim_extraction` (structuring) and
  the legacy faithfulness judge (R11: not edited, covered through the decorator).
- **Provider calls.** `arv2/calls.py::ProviderCaller.call(spec)` (sync): latch check, estimate
  row, attempts, raw save, cost reader, halt rule, `_settle` → result row through `_record`,
  which builds a `LedgerRow(extras={**spec.extras, **extras})`. `CallSpec` carries `provider`,
  `operation`, `label`, `request` (method, url), `estimate`, `extras`. `CallResult` carries
  `ledger_row_id`, `call_cost` (usd, credits, media_seconds, source), `attempts`, `latency_ms`,
  `over_ceiling`. `ProviderHalted` is raised on a latched provider or a halt rule.
- **Governed tools.** `clue_toolbelt.invoker.ToolInvoker.invoke(name, body, context, *, version,
  idempotency_key)`: validate → snapshot → `journal.begin` (COMPLETED replay / BLOCKED refusal) →
  steering snapshots → `invoke_tool` → `journal.completed/blocked/awaiting_input/failed`.
  `ToolContext` carries `workspace_id`, `actor`, `operation_id`; `ToolDescriptor` carries
  `effect_class`; `ToolResult` carries `references`, `replayed`, `meta`.
- **Redaction helpers.** `clue_obs.redact.redact_value(value, key)` (secret-key rule, recursive),
  `mask_blob(str)` (base64/binary rule), `is_claim_value_key`; `clue_obs.truncate._truncate`.
- **The streaming defect.** `clue_gateway.agent_model._astream_with_fallback` calls
  `_stamp_answering_model(chunk.message, fallback=model_id)` on every chunk, so every chunk's
  `response_metadata` carries `model_name`/`clue_answering_model`; LangChain's chunk merge
  concatenates equal string values, and the runtime's receipt reads `model_name` from the merged
  message → `grok-4.6grok-4.6…`. The gateway's own usage record uses one chunk and is clean.
- **Langfuse SDK 4.15.2** (probed, not yet a dependency): `Langfuse(public_key, secret_key,
  base_url, environment, release, tracer_provider, mask, should_export_span,
  blocked_instrumentation_scopes, span_exporter, tracing_enabled, flush_at, flush_interval, ...)`
  adds its own `LangfuseSpanProcessor` to the **given** provider; `start_as_current_observation(
  name, as_type in {generation, embedding, span, agent, tool, chain, retriever, evaluator,
  guardrail}, input, output, metadata, level, status_message, model, usage_details,
  cost_details, ...)`; every observation wrapper has `.id`, `.trace_id`, `.update(...)`,
  `.end()`; `create_event(name, input, output, metadata, level, status_message)`;
  `get_current_trace_id()`, `get_current_observation_id()`, `flush()`, `shutdown()`;
  module-level `propagate_attributes(user_id, session_id, metadata, tags, trace_name,
  environment)`; `langfuse.langchain.CallbackHandler(public_key=None, trace_context=None)` keeps
  `self._runs: dict[UUID, observation]` from `on_*_start` until `on_*_end`, chooses the
  observation type from the LangChain run (`agent`/`chain`/`tool`/`retriever`/`generation`), and
  reads `langfuse_*` keys out of the run's metadata at the root. LangChain dispatches every
  handler's start event (inline or in an executor with `copy_context().run`) before the model
  call proceeds, so ids captured at start are visible to every handler's end event.

## 3. Design

### 3.1 `clue_obs.langfuse` — the client and the observation helpers

One module owns the SDK import for the client side (an import-linter contract keeps `langfuse`
out of every other module but the LangChain adapter in 3.3):

- `install_langfuse(*, public_key, secret_key, host, environment, release, tracer_provider,
  process_name, mask_limit=8_000) -> bool`: builds `Langfuse(tracer_provider=tracer_provider,
  mask=make_mask(mask_limit), environment=environment, release=release,
  should_export_span=_not_a_health_check, additional_headers=None)` and returns `True`; with
  no keys returns `False` and constructs nothing. The client is registered in Langfuse's own
  client registry (`get_client()`), which the LangChain handler reads. **D1 (ruled):** it is
  attached to the slice 2 provider, so FastAPI, httpx, `traced_step` and `fleet.task` spans
  export to Langfuse under the same trace id as the agent tree; no second provider, no second
  trace per turn. `should_export_span` drops server spans whose route is a health check
  (`/healthz`, `/health`, `/readyz`).
- `langfuse_is_installed() -> bool`; `flush_langfuse()`; `shutdown_langfuse()` (the roots'
  lifespans call it after the OTel flush).
- `observation(name, *, as_type, input=None, metadata=None, **fields)`: a context manager over
  `start_as_current_observation(...)` that yields the observation (or a `NullObservation` with
  the same `update`/`end`/`id`/`trace_id` surface, ids `None`, when Langfuse is not installed).
  Every platform-side observation goes through it, so the "not installed" branch is one place.
- `current_ids() -> LangfuseIds | None` (`trace_id`, `observation_id`) from
  `get_current_trace_id()`/`get_current_observation_id()`; `None` when not installed or when no
  observation is current.
- `event(name, *, level="DEFAULT", status_message=None, metadata=None, input=None,
  output=None)` over `create_event`; `guardrail(name, *, reason, metadata=None)` opens and
  immediately closes a `guardrail` observation with `level="WARNING"` and
  `status_message=reason`. Both no-ops when not installed.
- `make_mask(limit)` (R3): the `mask=` hook. It runs `redact_value` (the secret-key rule) over
  the payload, `mask_blob` over every string, and truncates strings longer than `limit` with the
  `clue_obs.truncate` marker. It never applies the claim-value rule: Langfuse is the debugging
  surface for exactly those values. The turn's own receipt limit is the default `limit`.
- `propagate_trace(*, trace_name, session_id, user_id, metadata, tags=())`: a thin wrapper over
  `langfuse.propagate_attributes` (no-op contextmanager when not installed) so callers never
  import the SDK.

`libs/clue-obs/pyproject.toml` gains `langfuse>=4.15,<5`.

### 3.2 The roots and the env

`clue_api.production_tracing.install_production_langfuse(settings, secrets, *, runtime,
service_name) -> bool`: enabled with no keys refuses at composition (`RuntimeError`, like
Sentry); disabled logs `langfuse.not_installed`; enabled calls `install_langfuse(...,
tracer_provider=runtime.provider, environment=settings.langfuse_environment,
release=settings.release, process_name=service_name)`. Called at `projections_main` and
`fleet_main` right after `install_production_tracing`; `production_tracing_lifespan` calls
`shutdown_langfuse()` before the OTel flush on shutdown.

Settings (`Settings`) and secrets (`Secrets`), all in `.env.example` and the local `.env`
(parity rule):

```
# --- Langfuse (lane 3 slice 3) — off by default; keys are the EU cloud project's ---
CLUE_LANGFUSE_ENABLED=false
CLUE_LANGFUSE_HOST=https://cloud.langfuse.com   # the EU region (R4)
CLUE_LANGFUSE_PUBLIC_KEY=                       # secret
CLUE_LANGFUSE_SECRET_KEY=                       # secret
CLUE_LANGFUSE_ENVIRONMENT=lane-san-salvador
```

**D3 (ruled):** `CLUE_LANGFUSE_ENVIRONMENT` sits beside `CLUE_SENTRY_ENVIRONMENT`, both
defaulting to the lane string; no shared telemetry-environment setting. The design note's §7
`LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` lines are replaced by these.
With Langfuse attached to the provider, `CLUE_OTEL_TRACES_ENDPOINT` stays empty for Langfuse
(the SDK exports itself); it remains the seam for any other OTLP collector.

### 3.3 Graph calls: the LangChain handler and the run registry

`clue_api.langfuse_callbacks` (the only other module that imports `langfuse`; it needs
`langfuse.langchain`, which needs `langchain_core`, so it cannot live in `clue_obs`):

- `LangfuseRunRegistry`: a per-invocation map `run_id → LangfuseIds` filled at
  `on_chat_model_start`/`on_llm_start` and read by anyone holding the registry.
- `ClueLangfuseHandler(langfuse.langchain.CallbackHandler)`: overrides `on_chat_model_start`
  and `on_llm_start` to call `super()` then record `self._runs[run_id].trace_id/.id` in the
  registry (guarded: a missing entry records nothing), and `on_llm_end` to read the gateway's
  cost stamp from the response (`cost_cents_from_metadata`, the shared reader) and, when the
  observation is still held, `update(cost_details={"total": usd}, metadata={"clue_cost_source":
  source, "clue_answering_model": served})` **before** `super().on_llm_end` ends it. **D2
  (ruled, improved):** graph generations therefore carry the platform's settled cost, not
  Langfuse's price-table estimate; Postgres remains the authority (R2), Langfuse shows the same
  number. `build_langfuse_callbacks() -> tuple[ClueLangfuseHandler, LangfuseRunRegistry] |
  None`: `None` when Langfuse is not installed, so callback tuples are unchanged today.

Where it is attached:

- **The turn runtime** (`DurableAgentTurnRunner.run`): the handler is appended to the callback
  tuple after the recorder, the registry is handed to `DurableAgentModelCallHandler`
  (`langfuse_ids: LangfuseRunRegistry | None`), and the whole `self._runtime.run(...)` call is
  wrapped in `propagate_trace(trace_name="head-of-abm.turn", session_id=thread_id,
  user_id=workspace_id, metadata={project_id, turn_id, execution_id, profile_ref, role, actor},
  tags=(profile role,))`. The callback tuple's type widens to `BaseCallbackHandler` (what
  `clue_agents.runtime.run` already accepts).
- **The ARV2 research agent** (`_run_agent`): `config = RunnableConfig(recursion_limit=...,
  callbacks=[handler])` under `propagate_trace(trace_name="arv2.account_research",
  session_id=str(run_id), user_id=workspace_id, metadata={job_id, account_id, attempt})`. The
  registry's ids for each round are written into that round's ledger row extras by
  `_ModelUsageRecorder` (`langfuse_trace_id`, `langfuse_observation_id`) when the recorder holds
  a registry; the middleware's `request` carries the LangChain run id through its `runtime`
  config when available, else the extras carry the trace id only.
- **The exit judge** (`agent_turn_fleet_wiring.py:1661`, the design leg's): `ainvoke(prompt,
  config={"callbacks": [handler]})` inside `observation("design-leg.exit_judge", as_type="evaluator")` under `propagate_trace(trace_name="design-leg.exit_judge",
  ...)`, so it is one generation in its own trace rather than an invisible call.

The handler types the graph for us: the deep agent root is `agent`, LangGraph nodes are
`chain`, sub-agent delegations are nested `agent`s, tool calls are `tool`, model calls are
`generation`. Nothing in `clue_gateway.agent_model` opens a Langfuse observation: the graph path
is reported once, by the handler (the one-path-per-call rule).

### 3.4 Non-graph model calls: the gateway decorator

`TracingGateway.complete` opens `observation(f"gateway.{call_kind}", as_type="generation",
model=model, input=_messages_summary(messages), metadata={"requested_model": model})` inside the
`llm.gateway_call` span, and after the inner call `update(model=completion.model, output=
_completion_summary(completion), usage_details={"input": prompt, "output": completion,
"cache_read_input": cached}, cost_details={"total": usd}, metadata={"cost_source": ...,
"duration_ms": ...})`. `embed` does the same with `as_type="embedding"` (input = the count and
total characters, never the texts). The summaries carry the role and the text of each message
(the mask truncates and redacts); the completion summary carries the content and finish reason.
`record_model_call` is unchanged. The stub gateway path emits the same observation, so the
offline tests prove it.

### 3.5 Provider calls: `ProviderCaller` observations

`ProviderCaller.call` opens one observation around the attempts loop and the settlement, closed
in a `finally`:

- name `f"{spec.provider}.{spec.operation}"`; `as_type`: `generation` when `spec.operation` is
  `chat/completions` or `agent_completion`, `embedding` when it contains `embed`, else `tool`.
- `input`: `{"method", "host", "path", "label", "estimate": {usd, credits, media_seconds},
  "over_ceiling_estimate"}` — the URL's host and path only, never the query or the body.
- on settlement: `update(output={"status", "outcome", "attempts", "latency_ms",
  "provider_request_id", "raw_ref"}, cost_details={"total": usd}, usage_details={tokens from
  the reading's extras when present, else credits / media_seconds as their own keys},
  metadata={"ledger_row_id", "call_id", "cost_source", "over_ceiling", **spec.extras ids},
  model=<reading's model when present>, level="ERROR"/status_message=error_code on a
  non-`ok` outcome)`.
- on `ProviderHalted` (latched or halt rule) and on transport exhaustion: `level="ERROR"`,
  `status_message=reason`, then re-raise. A latched provider (no wire, no row) still records a
  `guardrail("provider.halt_latch", reason=...)` so the refusal is visible in the tree.
- `over_ceiling` (estimate or settled) records `guardrail("provider.ceiling", reason=...)` beside
  the observation; the call proceeds exactly as today (ceilings only record).
- **Ids back onto the ledger:** `_settle` receives the observation's ids and writes
  `extras["langfuse_trace_id"]` / `extras["langfuse_observation_id"]` on the result row (the
  estimate row is written before the observation exists and stays as it is). `LedgerRow` and
  the drain are unchanged: `extras_json` already carries arbitrary keys.

The caller is synchronous and runs on worker threads (`asyncio.to_thread` copies the context),
so the observation nests under whichever tool or step opened it.

### 3.6 Governed tools and retrievers

`ToolInvoker.invoke` opens `observation(f"governed.{name}@{version}", as_type=<"retriever" when
descriptor.effect_class is READ, else "tool"> (ruled 2026-09-15: no per-tool declaration),
input={"operation_id", "actor", "workspace_id", "inputs": <validated inputs>},
metadata={"effect_class", "version"})` around the journal path and updates it on every exit:

- COMPLETED replay: `output={"replayed": True, "references": ...}`, `metadata.disposition=
  "replayed"`.
- BLOCKED at begin or `PreconditionFailed`: `level="WARNING"`, `status_message=", ".join(reason
  codes)`, `metadata.disposition="blocked"`; re-raise.
- `ToolAwaitingInput`: `level="DEFAULT"`, `status_message=reason_code`, `metadata.disposition=
  "awaiting_input"`; re-raise.
- any other failure: `level="ERROR"`, `status_message=error code`; re-raise.
- completion: `output={"references": result.references, "meta": result.meta}`.

The LangChain handler already opens a `tool` observation for the model's call; this one nests
inside it and carries what the handler cannot see (the platform's decision). Tool inputs pass
through the mask like every payload.

### 3.7 Guardrails and events

- `TurnWorkGuard`: when `check()` raises, `guardrail("turn.work_guard", reason=<exception class
  or code>)` then re-raise.
- The agent's round cap and tool-wave shape (`_RoundShapeMiddleware`,
  `ModelCallLimitMiddleware` exit) in the research agent: `_FinalizeEndsMiddleware` and the
  outcome path record `event("arv2.agent.ending", output={"ending": outcome kind})`; a
  `round_cap` ending records `guardrail("arv2.round_cap", reason=...)`.
- Pre-spend refusals in the toolbelt (`artifacts_not_configured`, `exa_not_configured` and
  their kin) are BLOCKED outcomes of 3.6 — `level="WARNING"`, no separate mechanism.

### 3.8 Receipts: the migration (D4)

Migration `agent_model_call_langfuse_ids` (hash id, `down_revision = "d36bc7d32c9a"`) adds
`langfuse_trace_id text NULL` and `langfuse_observation_id text NULL` to `agent_model_call`,
reversible. `AgentModelCallReceipt` gains both fields (`str | None = None`);
`record_model_call` inserts them and the replay comparison includes them (a replay of a
Langfuse-off turn compares `None` to `None`). `DurableAgentModelCallHandler._record` reads
`self._langfuse_ids.get(run_id)` when a registry is present. **D4 (ruled):** the ids are
exact, from the registry filled at model-call start (3.3), not best-effort.

### 3.9 The streamed `answering_model` fix

`_astream_with_fallback` stamps `clue_answering_model` on the **first** chunk of a stream and,
on every later chunk, removes `model_name`, `model` and `clue_answering_model` from
`response_metadata` before yielding, so the merged message carries each key once. `_astream`'s
own record already uses one chunk. The runtime's `on_llm_end` prefers `clue_answering_model`
over `model_name` (the gateway's own stamp is the served model, fallback-aware). A regression
test streams three chunks through the merge and asserts the merged `answering_model` equals the
model id once.

### 3.10 `make langfuse-check` and the stack status line

`clue_api.langfuse_check` (`python -m clue_api.langfuse_check`): reads settings and secrets,
prints whether Langfuse is enabled and configured, and when it is, calls the SDK's
`auth_check()` against the host and prints `langfuse: ok (<host>, env=<environment>)` or the
failure; exit 0 on ok, 1 otherwise; sends no trace. `make langfuse-check` runs it.
`scripts/dev_stack.sh status` prints one line `langfuse: enabled|disabled` from the sourced env.
No compose service (R4: cloud).

### 3.11 Import discipline

A new `import-linter` contract: `langfuse` may be imported only by `clue_obs.langfuse` and
`clue_api.langfuse_callbacks` (the kept count becomes 27, broken stays 0). `clue_obs` keeps its
layer position (`obs → config → core`).

## 4. What does not change

- No legacy research-lane file (R11), no design-subsystem file (R12), no frontend file.
- `clue_gateway.agent_model` opens no Langfuse observation (the handler reports the graph path).
- `LedgerRow`, `drain_provider_calls`, the cost read, `record_model_call`'s INSERT-or-compare
  posture, the OTel span names and attributes, the Sentry install.
- `CLUE_OTEL_TRACES_ENDPOINT` semantics.

## 5. Testing

Offline, with `Langfuse(span_exporter=InMemorySpanExporter(), tracing_enabled=True,
tracer_provider=<test provider>)` (the helper `langfuse_installed()` in `tests/_langfuse.py`
that installs against an in-memory exporter and returns it):

- `tests/test_obs_langfuse.py`: not installed → `observation` yields the null handle,
  `current_ids()` is `None`, `event`/`guardrail` no-op; installed → an observation exports a
  span with the Langfuse type attribute, `current_ids()` matches the span, the mask redacts a
  secret-named key, masks a base64 blob, truncates a long string and leaves a claim value alone;
  `should_export_span` drops a `/healthz` server span.
- `tests/api/test_langfuse_callbacks.py`: a fake chat model run through `ClueLangfuseHandler`
  fills the registry at start with the generation's ids and the exported generation carries
  `cost_details.total` from the response's cost stamp.
- `tests/api/test_agent_runtime_langfuse_db.py`: a turn through the runner with Langfuse
  installed writes receipts whose `langfuse_trace_id`/`langfuse_observation_id` equal the
  exported generation's ids; with Langfuse off both are NULL and the callback tuple is unchanged.
- `tests/test_gateway_tracing.py` (extend): `TracingGateway.complete/embed` over the stub export
  a `generation`/`embedding` with usage and cost details.
- `tests/arv2/test_calls_langfuse.py`: a `ProviderCaller` call exports one observation typed by
  operation with cost details and the ledger row id, the result row's extras carry the ids, a
  halted call exports `level=ERROR` and a `provider.halt_latch` guardrail on the next call, an
  over-ceiling estimate exports `provider.ceiling`.
- `tests/toolbelt/test_invoker_langfuse.py`: completed, replayed, blocked and failed invocations
  export the four dispositions.
- `tests/test_agent_model_streaming.py`: the merged streamed message's `answering_model` is the
  model id once.
- `tests/db`: the migration round-trips (on a fresh empty DB); `tests/arv2/test_settings.py`
  parity for the five env names; lint-imports 27 kept / 0 broken.
- Live proof (founder-triggered, after keys are set and the stack restarted): one chat turn
  and one `make cost-report --job` research job appear in Langfuse as trees; the receipt's
  `langfuse_trace_id` opens that trace.

## 6. Plans

Two plans, executed back to back on this branch:

- **3a — the foundation:** 3.1, 3.2, 3.3 (runtime + registry), 3.8, 3.9, 3.10, 3.11, and the
  docs.
- **3b — the richness:** 3.3 (research agent + summary call), 3.4, 3.5, 3.6, 3.7.

## 7. Deferred

- Registering the OpenRouter model prices in Langfuse (an operator step; our generations carry
  the settled cost regardless).
- Prompt management, scores and datasets in Langfuse (not in the lane).
- Design-subsystem observations (R12) and the legacy lane's judge as an `evaluator` (R11).
- Slice 4's entity tags ride on `propagate_trace` metadata once they exist.
