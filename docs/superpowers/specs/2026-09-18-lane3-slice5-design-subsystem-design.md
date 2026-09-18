# Lane 3 slice 5 — cost, tracing and telemetry for the design subsystem (R12 lifted) — design

**Status:** approved by the founder 2026-09-18 (all six §6 rulings taken as recommended; SDD execution started the same day on `lane3/slice5-design-spend`). Lifts the R12 hold of the parent note
(`2026-09-14-telemetry-and-cost-observability-design.md` §5.4): PR #62 (`codex/design-agent-v1`,
merged 2026-09-17) finalised the design agent's structure, which was the hold's trigger. Six
rulings are requested in §6; the plan (`docs/superpowers/plans/2026-09-18-lane3-slice5-design-subsystem.md`)
is written on the recommendations and changes only where a ruling differs.

## 1. The problem

The pilot's cost picture stops at the design leg. The founder cannot answer "what did this landing
page cost" or "what did ingesting this brand kit cost", and the cost read says so in its
`NOT_COVERED` block. Concretely, verified 2026-09-17:

- **The design trio's model calls** (orchestrator, author, reviewer) already run on the platform's
  governed gateway inside the fleet worker, so each call gets an OTel span, a `model_call_usage`
  structlog event with role and cost, and OpenRouter's metered price. But nothing writes an
  `agent_model_call` row for them, so the cost read, the receipt id chain and the halt logic never
  see them, and no Langfuse handler is attached to those model instances, so a design turn has no
  trace of its own (only the exit judge, a separate evaluator observation).
- **Nine paid paths on the design side record no spend at all**: text-to-image generation
  (`image_provider.py`, its own credential, `usage` discarded), the four brand-kit ingestion models
  (assist, PDF vision, describe, ad-DNA distillation: hand-rolled `httpx.post` to OpenRouter with no
  `usage.include`), the ad style-group tie-break (`ad_runtime.choose_style_group`, same shape),
  the ingestion brief agent (governed gateway, so priced, but no durable row), Brandfetch's Brand
  API and Adyntel's ad harvest (paid or quota'd, unrecorded).
- **The design API process (port 8010) has no OTel, Sentry or Langfuse**, and with
  `LUMEN_EMBEDDED_FLEET_WORKER` it runs the same paid ingestion work the instrumented fleet worker
  runs.

## 2. What exists (verified 2026-09-17; anchors in the two scouting reports)

- **Ledgers of record.** `agent_model_call` (turn-keyed; `cost_usd`, `cost_source`, `langfuse_*`
  ids, `role` with `'design'` already in its CHECK) written by `DbAgentTurnJournal.record_model_call`
  from receipts built by `DurableAgentModelCallHandler` (an async LangChain handler, one
  construction site: the Head-of-ABM turn runtime). `provider_call_ledger` (workspace / project /
  run / job / provider / operation / phase / usd / credits / media seconds / `extras_json`), written
  by `ProviderCaller` → in-memory sinks → `drain_provider_calls(conn, raw, ledger, artifacts,
  LedgerStamp)`, which also opens provider incidents. `ProviderCaller` still lives in
  `platform/api/clue_api/arv2/calls.py`; nothing has moved to a shared package.
- **Pricing.** Model calls: the gateway stamps OpenRouter's own `usage.cost` (metered), falling
  back to `GET /generation?id=` and then `unpriced`. Provider calls: a per-provider cost reader
  (`openrouter_cost_reader` reads the same usage block), else the estimate stands in. No image
  price exists anywhere.
- **Langfuse.** `clue_obs.langfuse` (`install_langfuse`, `observation`, `propagate_trace`,
  `tag_entities`, `LangfuseRunRegistry`); `clue_api.langfuse_callbacks.ClueLangfuseHandler` writes
  the settled platform cost onto each generation; provider calls open `<provider>.<operation>`
  observations from inside `ProviderCaller`; governed tools open `governed.<tool>` observations from
  the toolbelt invoker.
- **Roots.** `clue_obs.otel.install_tracing` + `clue_obs.sentry.install_sentry` + Langfuse are
  installed by `clue_api.production_tracing.install_production_*` at `projections_main` and
  `fleet_main`. The design API root installs none.
- **Topology.** A design-leg turn runs **in the fleet worker process**: `design_leg_wiring._dispatch`
  → `InlineDesignLaneDriver.drive` → `lumen_api.fleet_handler` → `lumen_api.main.execute_*_turn_job`
  under `asyncio.to_thread` (the agent invoke is synchronous). The design leg already has its own
  `agent_turn` row with `role=design`. Ingestion jobs run through the same handler
  (`execute_ingestion_job`), in the fleet worker or in the design API's embedded worker.
- **Design-side telemetry.** structlog only (`py_lumen_obs`); `trace_callbacks.py` emits
  `llm_call_*` events with tokens but no cost; `run_metrics.py` sums tokens per role into
  `run_event`; `usage_capture.py` is retired dead code except its `_extract_usage`.
- **Seam discipline.** The design subsystem imports no research, memory or content internals; it
  already depends on `clue_obs`, `clue_gateway`, `clue_config` (secrets bridge), `clue_db`,
  `clue_design`. It must not import `clue_api`.

## 3. Design

### 3.1 One spend seam, shared: `libs/clue-spend`

`ProviderCaller`, `CallSpec`, `CallCost`, `SpendEstimate`, the `Transport` / `RawSink` /
`LedgerSink` protocols, the in-memory sinks, `drain_provider_calls` + `LedgerStamp`, and the
OpenRouter cost reader and halt rule move from `platform/api/clue_api/arv2/` to a new package
`libs/clue-spend` (`clue_spend`). ARV2, the onboarding lane, the display prewrite and the
evidence tool keep calling the same classes from the new home (the `arv2` modules become
re-exports for one release, then are deleted). The incident recording that `drain_provider_calls`
performs stays where the incident code lives: the drain takes an `on_failure` hook the platform
binds to `clue_api.provider_incidents`, so `clue_spend` does not import `clue_api`. The design
subsystem then depends on `clue_spend` the way it depends on `clue_gateway`. This is the parent
note's option (a); option (b), a design-local twin, is rejected there and here.

### 3.2 The design trio: durable receipts without an async handler in a thread

The durable handler is async and keyed to the platform's turn journal; the design agent invokes
synchronously on a worker thread. Rather than force an async DB writer into that thread, the
design runtime **collects** and the platform **persists**:

- `lumen_agent/usage_collector.py`: a small sync `BaseCallbackHandler` (`ModelCallCollector`) that,
  on `on_llm_end`, records one `CollectedModelCall` per call: requested model (from the instance),
  answering model and cost (`clue_gateway.metadata.cost_cents_from_metadata`, `ANSWERING_MODEL_KEY`),
  role label (`clue_role`, e.g. `design_author`), token counts (`_extract_usage`, moved out of the
  dead `usage_capture.py`), latency, status, error code, and the Langfuse run ids when a
  `LangfuseRunRegistry` is present. Attached in `_instrument` beside the trace and budget callbacks.
  Its list rides the turn result (`execute_*_turn_job` returns `model_calls=[...]`).
- The platform side (`design_leg_wiring._dispatch`, after `drive` returns) turns each collected
  call into an `AgentModelCallReceipt` on the design leg's own `agent_turn` (`role=AgentRole.DESIGN`,
  `sequence` from 1, `model_call_id` derived exactly as the Head-of-ABM handler derives it) and
  writes them through `DbAgentTurnJournal.record_model_call`, so replay compares them like every
  other receipt. Input/output artifacts are not persisted for design calls in this slice (the
  prompts are large scene payloads; the parent note's payload rule applies to Langfuse, where they
  go through `make_mask`).
- The role written to the row is `design` (the profile role, already legal in the CHECK); the
  sub-role (`design_orchestrator|author|reviewer`) rides the Langfuse generation metadata and the
  structlog event, where it already is. Ruling 6.1.
- The exit judge keeps its evaluator observation and gains `role=AgentRole.DESIGN` on `models.build`
  so its span and usage event carry the role. It stays off Postgres, consistent with the
  2026-09-15 leave-as-is ruling for non-graph completions.

### 3.3 Langfuse on the design leg

In `_dispatch`, before `drive`: `propagate_trace(trace_name="design-leg.turn",
session_id=thread_id, user_id=workspace_id, metadata={project_id, turn_id, execution_id, leg_id,
document_id, doc_kind}, tags=("design", doc_kind))` and an `observation("design-leg.turn",
as_type="agent")` around the drive. The `ClueLangfuseHandler` (with the run registry) is passed
into the design handler as an opaque LangChain callback and attached by `_instrument` next to the
collector, so every trio generation nests under the agent observation with the settled cost, and
the collector can stamp the generation ids on the receipts. OTel and Langfuse contexts propagate
into `asyncio.to_thread` because both are contextvar-based. Governed design tools already open
observations through the toolbelt invoker; the deep agent's sub-agent `task` calls appear as chains
under the same handler. `tag_entities` is called with the document id and, for account-targeted
ads, the account id (same accumulator as slice 4).

### 3.4 The paid provider calls, on the ledger

Each raw HTTP spend path is wrapped by a `ProviderCaller` built once per process in
`lumen_api/spend.py` (httpx transport, in-memory raw and ledger sinks, `openrouter_halt_rule` and
`openrouter_cost_reader` for OpenRouter operations). Their transports do not change; what changes
is that every request is a `CallSpec` with `provider`, `operation`, a `SpendEstimate`, and a cost
reader, and OpenRouter bodies gain `usage: {"include": true}` so the reader has a number.

| Path | provider | operation | cost reader |
|---|---|---|---|
| image generate / edit, chat style | `openrouter` | `design.image.generate` / `design.image.edit` | `openrouter_cost_reader`, else `/generation` lookup, else estimate |
| image, `images` API style | `openrouter` | same | `/generation` lookup, else estimate |
| ingestion assist | `openrouter` | `design.ingestion.assist` | `openrouter_cost_reader` |
| PDF vision | `openrouter` | `design.ingestion.vision` | same |
| describe | `openrouter` | `design.ingestion.describe` | same |
| ad-DNA distill | `openrouter` | `design.ingestion.ad_dna` | same |
| style-group tie-break | `openrouter` | `design.ad.style_group` | same |
| ingestion brief agent | governed gateway (unchanged) | receipt via the collector on the ingestion job | gateway stamp |
| Brandfetch Brand API | `brandfetch` | `design.logo.brand_api` | none: `free`, `credits=1` |
| Adyntel harvest | `adyntel` | `design.ad_library.harvest` | none: `free`, `credits=1` |

Rows are drained at the end of the unit that spent them, with a `LedgerStamp`: a design-leg turn
drains with `(workspace_id, project_id, job_id=design run id)`; an ingestion job drains with
`(workspace_id, job_id=ingestion job id)` and `extras.brand_kit_id`; the `/assets/generate` API
route drains inline with `(workspace_id, project_id?)`. The ingestion brief agent's governed calls
are collected the same way as the trio, but an ingestion job has no `agent_turn` to receipt them
on, so they land on `provider_call_ledger` through a small adapter that turns a
`CollectedModelCall` into a ledger row (`provider=openrouter`, `operation=design.ingestion.brief`,
the gateway's metered cost). One table per unit kind: turns → receipts, jobs → ledger.

A `ProviderHalted` (402 / credits) in an ingestion job fails the job with
`failure_code=provider_refused:openrouter:<reason>` and the drain opens the provider incident, so
the 2026-09-16 incident machinery covers design spend with no new channel; `_surface_for` learns
two labels, `design_ingestion` and `design_turn`, used only in Sentry's message.

### 3.5 The design API root

`lumen_api/main.py` installs the same three things `fleet_main` does, from the same settings and
secrets: OTel tracing (`process_name="clue-design-api"`, FastAPI and httpx instrumented), Sentry,
Langfuse. To keep one implementation, `install_production_tracing / _sentry / _langfuse` and
`production_tracing_lifespan` move from `clue_api.production_tracing` to `clue_obs.production`
(clue_obs gains a dependency on `clue_config`, which it already shares a repo with; ruling 6.4).
The design API reads `clue_config.load_settings()` / `Secrets()` for the `CLUE_OTEL_*`,
`CLUE_SENTRY_*`, `CLUE_LANGFUSE_*` values — the same `.env` the dev stack sources for it.

### 3.6 The cost read

No query changes: design provider rows join `_PROVIDER_LINES`, `_JOB_LINES` and the per-project
rollup by construction, and design receipts join `_TURN_MODEL_LINES` under `role=design`. The first
`NOT_COVERED` entry is deleted; the CLI test that asserts it is updated. The report gains nothing
else; if a per-surface view is wanted later, the `design.` operation prefix is the group key.

### 3.7 What is deliberately not done

- No new environment flag. The existing `CLUE_LANGFUSE_ENABLED`, `CLUE_SENTRY_ENABLED`, OTel
  endpoint and the Langfuse keys govern the design API exactly as they govern the fleet.
- No credits conversion (`cost_millicredits` stays 0, the uncomposed credits milestone's policy).
- No price table for images; the metered number or the generation lookup, else `estimate` from
  a zero reservation labelled as such. If OpenRouter never returns a cost for image outputs on this
  account, that shows up as `estimate` rows and becomes a follow-up, not a guess.
- No change to the design agent's structure, prompts, tools, transports or retries.
- No Langfuse deletion (the erasure lane's).
- The legacy research lane (R11) untouched.

## 4. Environment (parity rule)

No new keys. The design API's boot reads the existing `CLUE_OTEL_TRACES_ENDPOINT`,
`CLUE_OTEL_INSTRUMENT_FASTAPI`, `CLUE_OTEL_INSTRUMENT_HTTPX`, `CLUE_SENTRY_ENABLED`,
`CLUE_SENTRY_ENVIRONMENT`, `CLUE_LANGFUSE_*`, `CLUE_RELEASE` and the two secrets, all already in
`.env.example`. `.env.example`'s comment on the OTel block gains "and the design API" in its list
of roots.

## 5. Files this slice does not touch

The legacy research lane (parent §11). The design agent's skills, prompts and tools. The image
provider's transports and retry policy (only the request body and the caller wrapping change).
The frontend.

## 6. Rulings requested

1. **Durable role for trio calls: `design`** on the row, sub-role in Langfuse and logs. The
   alternative, three new `AgentRole` members plus a CHECK migration, widens a vocabulary that the
   registry, profiles and delegation tables also read, for a breakdown Langfuse already gives.
2. **`libs/clue-spend` as the shared home** for the provider-caller seam (parent option (a)). The
   alternative is folding it into `clue_obs`; that would give the observability package a
   SQLAlchemy dependency and a second purpose.
3. **Ingestion spend on `provider_call_ledger` keyed by the ingestion job**, including the governed
   brief agent's calls through the collector-to-ledger adapter. The alternative, a synthetic
   `agent_turn` per ingestion job, would invent a turn where no human turned.
4. **`install_production_*` move to `clue_obs.production`** so three roots share one
   implementation; `clue_obs` gains a `clue_config` dependency. The alternative is the design API
   calling the three `clue_obs` installers directly with values it reads itself (a second copy of
   the glue, but no new package edge).
5. **Brandfetch and Adyntel rows carry `cost_source=free`, `credits=1`** until a price is known; the
   count is what the report shows. The alternative is an env-documented per-call price for each,
   which is a number nobody has verified.
6. **The design API's own `/assets/generate` route drains inline** (a request-scoped caller), so
   spend from the editor's manual generation is on the ledger too, not only the agent's.

## 7. Acceptance

1. A web-page design turn on the lane produces `agent_model_call` rows with `role='design'`, one
   per trio call, each with `cost_usd`, `cost_source='metered'`, and Langfuse ids; the same turn
   is one `design-leg.turn` trace in Langfuse with the generations nested and priced; the cost
   report's per-project total includes them.
2. A brand-kit ingestion produces `provider_call_ledger` rows for describe/vision/assist/brief
   (and ad-DNA when enabled) keyed by the ingestion job, with model and tokens in `extras_json`,
   plus a Brandfetch row; Langfuse shows them under the ingestion job.
3. One image generation (agent tool and the API route) produces a `design.image.generate` row
   with a metered or looked-up cost.
4. A forced 402 on an ingestion model call fails the job with `provider_refused:openrouter:…`
   and opens a provider incident in Sentry.
5. The design API root emits FastAPI and httpx spans under `clue-design-api`, a forced exception
   reaches Sentry with run context, and Langfuse is installed (or skipped with the warning when
   keys are absent).
6. `NOT_COVERED` no longer names the design subsystem; `tests/projections/test_cost_cli.py`
   agrees.
7. Gates: focused pytest files named per task on the lane DB; `ruff`, `mypy`, `lint-imports`
   (the new package edge declared in the import-linter contracts); the design subsystem's
   `apps/agent_runtime` and `apps/api` suites for the files touched; no design Rust/wasm change.
