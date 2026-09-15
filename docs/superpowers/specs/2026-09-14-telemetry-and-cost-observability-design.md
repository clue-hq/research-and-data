# Telemetry and cost observability for the paid pilot (lane 3) — design

**Status:** draft for founder review, 2026-09-14. Supersedes the four-tool eventual architecture
(structlog + Langfuse + OpenTelemetry + OpenMeter, LiteLLM optional) discussed 2026-09-13 as the
lane 3 scope. Rulings taken in this note are recorded in
`_memory/2026-09-14-lane3-telemetry-rulings.md`.

## 1. What this is for

Before a paying customer runs research on the platform, an operator must be able to answer four
questions from one place each, without reconstructing a run from log files:

1. **What did the agent do** on this turn: which sub-agents ran, which tools they called, what
   each model saw and said, and what every external provider call returned.
2. **What broke**, where, on which release, for which workspace and run.
3. **What did it cost**: per run, per account-research job, per workspace, and overall, broken
   down by provider and operation, and separately by model.
4. **Which external call was slow or failing**, including the ones that carry no cost reader.

The pasted "Paid Pilot Observability v1" milestone (ten points) is the acceptance bar. Once the ten
points hold on the lane stack, lane 3 stops and the pilot ships. Everything past that bar is named
in §8 as deferred, with the trigger that re-opens it.

## 2. Founder rulings (2026-09-14)

- **R1 — Langfuse records every tool call and every spend.** Local tools (reads, writes,
  delegation) and provider tools alike, nested under the sub-agent that made the call. Every LLM
  call and every external provider call appears with its settled cost.
- **R2 — Postgres stays the ledger of record.** `provider_call_ledger` and `agent_model_call`
  are authoritative. The halt latch and the client cost cap read them in-process before the next
  call. Langfuse receives the settled figures as ingested cost and never recomputes them.
- **R3 — Full payloads leave the box, secrets stripped.** Prompts, completions, tool arguments
  and tool results go to Langfuse in full. The secret-key redaction rule applies to every
  observation before export. The claim-value masking rule that governs log lines does **not**
  apply to Langfuse payloads. The same text already leaves the box to OpenRouter and the model
  vendors on every call; Langfuse is a second processor of it with a longer retention, covered by
  R4 and R5.
- **R4 — Langfuse cloud, not self-hosted** (revised 2026-09-14; the earlier self-hosting
  condition is withdrawn). EU region, under Langfuse's data-processing agreement, with the
  project's retention set explicitly rather than left at the default.
- **R5 — DSAR erasure must reach Langfuse — owned by ARV2's DSAR floor, not lane 3.** ARV2 has
  no erasure path of its own today (master plan D10, unbuilt); the only `erase` in the tree is
  the old lane's, which lane 3 does not touch (R11). Lane 3's obligation is to make erasure
  *possible*: every trace is tagged with the entity ids whose claims it carried (§6). Deleting
  those traces through Langfuse's API is a step of ARV2's erasure when D10 is built. Until then,
  the pilot's DSAR answer for traces is manual deletion by entity tag, and this is recorded as a
  known gap, not hidden.
- **R6 — Sentry cloud, free tier**, with local-variable capture off and default PII off, so an
  event carries a stack trace and our ids, never customer text.
- **R7 — OTel spans export to Langfuse's OTLP endpoint.** FastAPI and httpx spans share one
  trace id with the agent tree in one viewer. A separate collector with Tempo or Jaeger is the
  deferred Grafana stack.
- **R8 — Provider-level cost attribution is in scope now.** Per run, per job, per workspace and
  overall, by provider and operation. This is a query over existing rows and is the first slice.
- **R9 — Deferred:** OpenMeter (until credits and quotas), SQLAlchemy and Redis
  auto-instrumentation (until DB latency is a real problem), LiteLLM (never for observability),
  agent-and-tool-level cost columns in Postgres (Langfuse shows that tree; see §5.5).
- **R10 — Every new provider goes through `ProviderCaller`** so it lands on the ledger and, via
  §5.3, in Langfuse. Websets included.
- **R11 — The legacy research lane's code is not touched.** "Legacy" means exactly the
  waterfall and the old account-research lane inside `subsystems/research/clue_research/`
  (§11 lists it), which ARV2 replaces. No tracing, Langfuse, Sentry capture or cost reader is
  added to those files. Process-wide instrumentation (httpx, FastAPI) at the roots observes their
  calls as spans without editing them; that is a side effect, not work. **Not legacy, and in
  scope:** the fleet worker processes, projections, the chat API, ARV2, the shared libraries, and
  the design subsystem. Every lane 3 plan carries a "files not touched" list naming §11.
- **R12 — The design subsystem is out of lane 3 for now, and HIGH PRIORITY as soon as it can
  be.** (Revised 2026-09-14.) The co-founder is changing the design subsystem's agent structure;
  until that is finalised, lane 3 does not instrument the design API root, does not add the
  Langfuse callback to the design leg, and does not put the design subsystem's paid calls on the
  ledger. The ruling on *what* to do is unchanged and stands ready: every paid call the design
  subsystem makes on its own (today: the text-to-image provider in `image_provider.py`, and the
  ad-DNA model call in `ad_runtime.py`, which posts straight to OpenRouter and bypasses the
  platform gateway, so it records **no cost today**) goes through a `ProviderCaller`-shaped seam
  and lands on `provider_call_ledger` like an ARV2 call, and the design root gets the same OTel
  and Sentry install as the other roots. §5.4 keeps the design so it is not re-derived. **This is
  the first thing lane 3 picks up after the design agent structure is finalised**; until then
  the pilot's cost picture is missing the design leg's image and ad-DNA spend, and that gap is
  stated in the pilot's cost note.
- **R13 — Erasure endpoints are second priority and a separate lane.** ARV2's DSAR floor (D10:
  access, rectify, erase, objection over ARV2's own rows, plus the Langfuse trace deletion of §6)
  is planned as its own lane after lane 3's first three slices, not inside lane 3. Lane 3's
  slice 4 (entity tags on traces) is the only lane 3 work it depends on.

## 3. What already exists (verified 2026-09-14)

| Capability | Where | State |
| --- | --- | --- |
| Structured logs with run context | `libs/clue-obs` — `clue_obs.context.bind_*` binds request, workspace, project, run, account, actor, profile version | Bound at the roots since slice 2 (2026-09-15): the request-context middleware and tenant seams in the API, the per-task wrapper in the fleet worker. Before that nothing in production called the bind helpers, so item 6 was not met. |
| Redaction | `libs/clue-obs/clue_obs/redact.py` — secret-shaped keys → `***`; claim-value keys → ids; blobs → placeholder; runs in every log mode | Done for logs. Reused for spans and Langfuse (secret rule only, per R3). |
| OTel spans | `clue_obs.otel.tracing.traced_step` / `configure_tracing`; module-local `TracerProvider`; OTLP HTTP exporter is a dependency | Spans are created and **dropped**: `configure_tracing` has no production caller. |
| LLM cost per call | `libs/clue-gateway/clue_gateway/tracing.py` — the factory's decorator records prompt, completion, cached tokens and `cost_cents` on every model call; `agent_model_call` receipts keyed by `turn_id` | Measured at the gateway on every call; the ARV2 research ledger records it. The conversation-turn receipt recorded 0 until slice 1 (Task 1–3) added cost_usd/cost_source. |
| Paid provider usage | `platform/api/clue_api/arv2/calls.py` `ProviderCaller` → `provider_call_ledger` (`workspace_id, project_id, project_run_id, entity_research_job_id, provider, operation, label, phase, http_status, latency_ms, attempts, cost_usd, credits, media_seconds, over_ceiling, outcome, cost_source, raw ref`) | Done for every ARV2 call. Milestone item 5 for the pilot path. |
| Onboarding / display / evidence spend | ProviderCaller over buffered sinks drained by the onboarding driver, the display page and the evidence tool (slice 1b) | On provider_call_ledger since 2026-09-14; the onboarding run id is the job stamp. |
| Outbound HTTP | httpx everywhere (32 files under `libs`, `subsystems`, `platform`; no `requests`, no `aiohttp`) | One instrumentor covers all of it. |
| Langfuse, Sentry, OTel instrumentors, OTLP endpoint config | — | Absent. No references anywhere in the tree or `.env.example`. |

Two consequences shape the design. First, the ledgers the plan calls `usage_events` already exist,
already keyed the way the plan wants, so no new cost table is built. Second, the missing pieces are
all *export and wiring*: nothing in lane 3 changes how a cost is computed or where it is stored.

## 4. The run context

The plan's `RunContext` is `clue_obs.context`. Lane 3 does not add a new object. It makes the same
fields ride three more channels:

| Field | structlog (today) | OTel span attribute | Langfuse | Sentry tag |
| --- | --- | --- | --- | --- |
| `workspace_id` | yes | yes | `metadata.workspace_id`, and the trace's `user_id` so Langfuse's per-user cost views become per-workspace | yes |
| `project_id` | yes | yes | `metadata.project_id` | yes |
| `run_id` (project run) | yes | yes | `metadata.run_id` | yes |
| `thread_id` / `turn_id` | via request/run binding | yes | `session_id` = thread; `metadata.turn_id` | yes |
| `entity_research_job_id` | via account binding | yes | `metadata.job_id` | yes |
| `actor`, `profile_version` | yes | yes | `metadata.*`; profile version as a tag | `release` carries the code version; profile version is a tag |

Propagation: the trace id is minted by the FastAPI span on the request that starts a turn, and
must survive into the fleet worker that picks the turn up. The turn request row is the carrier:
the API writes the W3C `traceparent` onto the turn when it enqueues it, and the worker restores it
as the parent of its own span before it opens the LangGraph run. Same for the account-research job
row on the ARV2 fleet. Without this step Sentry, Langfuse and the logs agree on `run_id` but not on
trace id, and "open the trace from the error" stops being a click.

## 5. The four layers

### 5.1 OpenTelemetry at the composition roots

One function, `clue_obs.otel.install(process_name)`, called once at each production root:

- the chat/API process (the FastAPI app the frontend talks to),
- `fleet_main` (turn and research workers),
- `projections_main`,
- and any other long-lived pilot process that opens spans (trial main is excluded).

**Not now (R12):** the design subsystem's API (`subsystems/clue-design/apps/api/lumen_api/main.py`).
When it is picked up, it is installed from inside the subsystem at its own root so the seam
discipline holds (the design root imports only `clue_obs`, which it already depends on).

It does exactly four things: `configure_tracing` with an OTLP HTTP exporter pointed at the
Langfuse endpoint (R7), the FastAPI instrumentor on the app (API and projections only), the httpx
instrumentor process-wide, and a span processor that copies the bound run context onto every span
at start. Span attributes pass through `safe_attributes`, which already applies the secret rule.

Not installed: SQLAlchemy, Redis, asyncpg (R9). The seam is one function, so turning one on later is
one line at the roots and nothing elsewhere.

`traced_step` callers across the research lane keep working unchanged; their spans now leave the
process.

### 5.2 Sentry at the composition roots

`clue_obs.sentry.install(process_name)` at the same roots: `sentry_sdk.init` with the DSN from env,
`include_local_variables=False`, `send_default_pii=False`, `release` from the build, `environment`
from `CLUE_DEPLOYMENT_PROFILE` or the stack name, and a `before_send` hook that runs the secret
redaction over the event and copies the bound run context (§4) onto its tags. The FastAPI and
asyncio integrations catch unhandled exceptions in requests and in worker tasks; the worker loops
that already catch-and-log gain an explicit `capture_exception` at the catch site so a swallowed
failure is still counted.

Sentry gets **no** tracing; OTel owns that.

### 5.3 Langfuse: the agent tree, tool calls, and spend

Three reporting paths, one per kind of call, never two for the same call:

1. **Graph calls.** The Langfuse LangChain callback handler is appended to the callback tuple the
   runtime already builds (`agent_runtime_wiring.py`, the tuple holding the model-call recorder,
   the work guard and the stream handler). It records the agent, every delegated sub-agent, every
   tool invocation with arguments and result, and every LLM generation with model, tokens and
   latency. The generation's cost is overwritten with the gateway's settled `cost_cents` (R2): the
   model-call recorder already sits in the same tuple and sees both the completion and the Langfuse
   observation, so it sets the cost on the observation and stamps the observation id on the
   `agent_model_call` row.
2. **Non-graph calls** (structuring, onboarding synthesis, judges, display prewrites): the gateway
   factory's tracing decorator opens a Langfuse generation directly, under the current trace if one
   is active, with the same settled cost. A gateway built for use inside the graph is built without
   this so a graph call is never reported twice.
3. **Provider calls.** `ProviderCaller.call` opens a Langfuse observation named
   `<provider>.<operation>` under the current observation (the tool that is running), with the
   settled dollars, credits and media seconds as ingested cost, the outcome, latency, HTTP status,
   attempts, `cost_source`, and the ledger row id. The ledger row gains the Langfuse trace id and
   observation id in `extras_json`. `ProviderCaller` is synchronous and runs inside tools; the
   observation is opened through the OTel context that the httpx instrumentor already sees, so
   nesting is correct without threading a handle through every caller.

Result: the Langfuse tree for a turn shows Head of ABM → specialist → tool → provider call, with
cost on every LLM generation and every provider call, and every local tool call recorded (R1).

**Payloads (R3).** Before export, every observation passes the secret-key rule from
`clue_obs.redact` and the blob rule (a downloaded audio file or an image is a placeholder, not
bytes). The claim-value rule is not applied. Tool results larger than the existing receipt limit are
truncated with the same `clue_obs.truncate` helper so a paged read does not ship a megabyte per
observation.

**Hosting (R4).** Langfuse cloud, EU region. One project per deployment posture (lane stack,
pilot), keys in env (§7). No containers are added to the stack. Retention is set on the project
explicitly for the pilot (unlimited until the pilot closes, then a stated window).

**Entity tagging (feeds R5).** Every observation that produces or reads claims about an account or
a contact adds the entity ids to the current trace's metadata (`entities: [...]`): the ARV2
research job's trace carries the account and every contact it wrote; a turn's trace gains the
ids each time a read tool (`read_account_research`, `read_claims`, `read_contact_*`) returns
claims about them. This is done in the ARV2 tool layer, not in the old lane (R11). It is what makes
"delete every trace that carried this person" a query rather than an archaeology exercise.

### 5.4 The design subsystem's paid calls (R12) — DEFERRED, HIGH PRIORITY

Deferred until the co-founder's changes to the design subsystem's agent structure are final;
kept here so the design is not re-derived. Nothing in this section is built by lane 3's slices 1–5.

`ProviderCaller` lives in `platform/api/clue_api/arv2/calls.py`, and the design subsystem may not
import platform internals (its seam discipline: design imports no research, memory or content
internals; it already depends on `clue_obs` and `clue_gateway`). Two ways to honour R12:

- **(a) Move the seam to a shared library.** `ProviderCaller`, `CallSpec`, `CallCost`, the
  `LedgerSink` protocol and the ledger writer move from `arv2/` to a shared package (a new
  `libs/clue-spend`, or into `clue_obs` if the founder prefers fewer packages). ARV2 keeps calling
  the same class from its new home; design calls it from its two provider files with its own
  transport and its own cost reader per provider. One class, one table, one set of tests.
- **(b) A design-local twin** that writes to the same table. Less movement, second copy of the
  laws (estimate-before-wire, save-raw-before-parse, halt latch) to keep in step.

The note recommends **(a)**: the repo's rule is that no logic is written twice, and the move is
mechanical (imports and one package boundary). The cost readers are the only new logic: the
image provider's per-image price from its config, and for the ad-DNA call the OpenRouter usage
block on the response, read the same way the gateway reads it. The ad-DNA call keeps its direct
OpenRouter transport (a routing change is not lane 3's), but it must report its cost once, via the
provider-caller path, not also via the gateway decorator (§5.3's one-path rule).

When it runs, this is the one lane 3 slice that edits design-subsystem files. It is reviewed under
the design subsystem's own gate, and lands after slice 3 so the design calls appear in Langfuse
under the design leg's observation with their cost, like every other provider call. Its plan must
be written against the *finalised* agent structure, not today's.

### 5.5 Cost attribution: the read

No new table. One read, `clue_projections.cost.cost_report`, over the two ledgers:

- provider spend from `provider_call_ledger` (`phase='result'` rows only), grouped by provider and
  operation, with the four `cost_source` labels counted per line, plus per-job and per-project
  lines. The ARV2 research agent's own model rounds are on this ledger as `openrouter` rows.
- conversation-turn model spend from `agent_model_call` joined through the turn to its project and
  thread, grouped by model and role. **Slice 1 discovered this table recorded every call at zero
  cost** (`cost_millicredits=0`, deferred to the credits milestone) and added `cost_usd` +
  `cost_source`, stamped from the cost the gateway already measures; rows older than that are
  blank and counted `unpriced`.

The two tables never hold the same call, so the total is their plain sum. Served as
`GET /cost/report` on the projections router and as `make cost-report`. Every report carries a
`not_covered` list naming the spend this read cannot see: the design subsystem's providers (R12
hold) and pre-cost-column turn rows. Slice 1b (2026-09-14) put the onboarding lane, the display
prewrite and the persona-evidence tool on the Postgres ledger, and made every OpenRouter row carry
its model and token counts.

Agent-and-tool-level cost is **not** materialised in Postgres (R9). Langfuse holds that tree, and
every ledger row and receipt carries the observation id (§5.3), so a ledger line opens to the agent
context that spent it. If a Postgres view of per-agent spend is wanted later, it is a join from the
stamped ids, not a new write path.

## 6. DSAR and the traces (R5, R11)

**The problem.** Once R3 is live, a trace holds copies of personal claims about contacts: a name,
a role, a quoted line from a podcast, inside a tool result or a prompt. Tombstoning the claim row
in Postgres does not remove those copies. A right-to-erasure request therefore has to reach
Langfuse, and to do that we must know *which* traces carried that person. Two kinds of trace do:
the research job that wrote the claims, and every later turn where the agent read them back
through a read tool. The first is keyed today (job id on the claim annotation row); the second is
not recorded anywhere, because nothing today needs to know which entities a turn read.

**What lane 3 does.** The entity tagging in §5.3: the ARV2 job and the ARV2 read tools tag the
current trace with the entity ids they wrote or returned. After that, "every trace that carried
contact X" is one Langfuse query by metadata.
Shipped 2026-09-15 (slice 4): the query is *traces with tag `entity:<id>`* (or metadata `entities`
contains `<id>`); the job's trace carries its subject, every entity it wrote about and each
committee member; a turn's trace carries every entity `read_account_research` / `read_claims`
served.

**What lane 3 does not do.** The erasure itself. ARV2 has no `erase` today; the only one in the
tree is the old lane's `compliance/dsar.py`, which tombstones old-lane claim rows and is off limits
(R11). Building ARV2's erasure is master-plan D10, unbuilt. When it is built, one of its steps is:
query Langfuse for traces tagged with the erased entity ids, delete them through the API, record
the deleted trace ids in the erasure audit, fail loud if Langfuse is unreachable so the erasure is
re-runnable. Lane 3's plan names this as D10's step, so it is not lost.

**Pilot posture until D10.** If a pilot contact asks for erasure before D10 exists, the operator
deletes the tagged traces by hand in Langfuse (a metadata filter, then delete), and the gap is
stated in the pilot's data-handling note. The Postgres ledgers (§5.5) carry ids and amounts only,
never claim text, so they are unaffected by erasure.

## 7. Environment (parity rule)

Every flag below lands in `.env.example` with its default the moment its code lands (CLUE_-prefixed, read through Settings/Secrets — the SDK-native names are not used, so nothing configures itself behind the parity rule):

```
# --- Telemetry (lane 3) ---
CLUE_LANGFUSE_ENABLED=true                     # on by default (2026-09-15); blank keys → logged skip
CLUE_LANGFUSE_HOST=https://cloud.langfuse.com  # EU region project (R4)
CLUE_LANGFUSE_PUBLIC_KEY=                      # secret
CLUE_LANGFUSE_SECRET_KEY=                      # secret
CLUE_LANGFUSE_ENVIRONMENT=lane-san-salvador
CLUE_METRICS_EXPORTER=memory
CLUE_METRICS_OTLP_ENDPOINT=
CLUE_METRICS_EXPORT_INTERVAL_MS=10000
CLUE_OTEL_TRACES_ENDPOINT=
CLUE_OTEL_TRACES_HEADERS=
CLUE_OTEL_INSTRUMENT_FASTAPI=true
CLUE_OTEL_INSTRUMENT_HTTPX=true
CLUE_SENTRY_ENABLED=false
CLUE_SENTRY_DSN=
CLUE_SENTRY_ENVIRONMENT=lane-san-salvador
CLUE_RELEASE=
```

Slice 2 (2026-09-15) shipped the OTel and Sentry names; slice 3a (2026-09-15) settled the Langfuse names as CLUE_-prefixed (D3 in its design note): the client attaches to the slice 2 provider, so CLUE_OTEL_TRACES_ENDPOINT stays empty for Langfuse and remains the seam for any other collector.

All three layers default **off**, so an unconfigured process behaves exactly as today. The pilot
overlay pins them on.

## 8. Deferred, with the trigger that re-opens each

| Deferred | Re-open when |
| --- | --- |
| OpenMeter | credits are sold, actions consume credits, double-charging must be impossible, usage must reconcile with billing |
| SQLAlchemy / asyncpg / Redis spans | "why is the DB slow" is asked twice |
| Separate OTel collector + Tempo/Jaeger | more than the current three process kinds, or Langfuse's span viewer cannot answer a latency question |
| Sampling | trace volume makes 100% retention a cost |
| Per-agent cost columns in Postgres | a product surface needs per-agent spend as a durable number |
| Cost readers for the legacy resolvers | never: R11; they are visible as httpx spans with latency only |
| **Design subsystem: root instrumentation, Langfuse on the design leg, ledger rows for its paid calls (§5.4)** | **HIGH PRIORITY.** The moment the co-founder's design agent-structure changes are finalised. Until then the pilot cost picture omits the design leg's image and ad-DNA spend (R12) |
| ARV2 erasure endpoints (D10) + Langfuse trace deletion | second priority; its own lane after lane 3 slices 1–3 (R13) |
| Non-graph gateway completions (value narrative, exit judge, Stage-0 extractor, judges) and the old lane's Sumble / Exa tier-3 provider calls on a Postgres ledger | founder ruling 2026-09-15: leave as is; they are visible in Langfuse with settled cost (gateway path) or as httpx spans (old-lane resolvers); the cost read does not see them |

## 9. Slices, in order

1. **Cost read** (§5.5). Spends nothing, needs no new service, answers the founder's question on
   day one. Projection endpoint + make target + tests over seeded ledger rows.
1b. **JSONL ledgers onto Postgres — DONE 2026-09-14.** The onboarding lane, the display
   prewrite and the persona-evidence tool drain their `ProviderCaller` sinks onto
   `provider_call_ledger` (design:
   `2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres-design.md`); OpenRouter rows carry model
   and usage.
2. **Roots — DONE 2026-09-15** (design: `2026-09-15-lane3-slice2-roots-design.md`).
   `clue_obs.otel.install_tracing` + `clue_obs.sentry` at `projections_main` and `fleet_main`; run
   context bound at the roots; the trace rides the fleet payload (D1, no migration); env parity
   incl. the metrics gap.
3. **Langfuse** (§5.3, R4 hosting; design: `2026-09-15-lane3-slice3-langfuse-design.md`).
   **3a — DONE 2026-09-15:** the client attached to the slice 2 provider (D1), the LangChain
   handler in the turn's callback tuple with the run registry and settled cost on every graph
   generation, receipt ids (D4, migration `b7193eb28363`), payload redaction, `make langfuse-check`,
   the streamed `answering_model` fix. **3b — DONE 2026-09-15:** the research job as one agent
   observation with priced rounds and generation ids on its ledger rows, the exit judge as an
   evaluator, gateway generations/embeddings, provider-caller observations with settled money
   and halt/ceiling guardrails, governed-tool/retriever observations with the disposition, the
   work-guard guardrail. Live proof owed (founder-triggered, after the keys are set and the stack
   restarted): one chat turn and one research job opened in Langfuse; the receipt's
   `langfuse_trace_id` and a ledger row's `extras_json.langfuse_trace_id` open those traces.
4. **Entity tagging on traces — DONE 2026-09-15** (design: `2026-09-15-lane3-slice4-entity-tags-design.md`):
   `clue_obs.langfuse.tag_entities`; the job tags its subject, its writes and its committee
   members; the two read tools tag what they served. The Langfuse deletion step is the erasure
   lane's (R13).

**Held, high priority (R12):** the design subsystem slice (§5.4: root instrumentation, Langfuse on
the design leg, provider-caller seam moved to a shared package, image provider and ad-DNA call on
the ledger). Starts the moment the design agent structure is finalised; planned against that
structure.

**The erasure lane (separate, after slices 1–3):** ARV2's D10 — access, rectify, erase and
objection over ARV2's own rows (never the old claim store), the Langfuse deletion step keyed on the
§6 tags, and the audit. It gets its own design note; the only lane 3 dependency is slice 4.

Each slice closes with a live proof on the lane stack: a real turn, opened in Langfuse, with the
same trace id visible in the FastAPI span, the worker span, the structlog lines, and a forced
exception in Sentry; and the cost read returning the same per-run total that the Langfuse trace
shows.

## 10. Acceptance: the ten points, mapped

| # | Milestone point | Closed by |
| --- | --- | --- |
| 1 | Every important workflow gets a run id | already true (project run, job, turn ids) |
| 2 | run id + workspace id propagate throughout | §4 (traceparent on turn/job rows) — slice 2 |
| 3 | Langfuse captures agent → sub-agent → LLM → tool → external API | §5.3 — slice 3 |
| 4 | LLM calls: model, latency, tokens, cost, outcome | already true; surfaced in Langfuse by slice 3 |
| 5 | Expensive APIs: provider, operation, latency, usage, cost | already true on the ledger; surfaced by slice 3 |
| 6 | structlog carries run/workspace ids | already true |
| 7 | Sentry errors carry run/workspace ids | §5.2 — slice 2 |
| 8 | Basic OTel: FastAPI, outbound HTTP, propagation | §5.1, §4 — slice 2 |
| 9 | 100% of pilot runs retained | no sampling configured; Langfuse retention set to unlimited for the pilot |
| 10 | Secrets and sensitive telemetry sanitised | §5.3 payload rules, §5.2 Sentry settings, §5.1 `safe_attributes`; erasure reachability via §6 entity tags |

## 11. Files lane 3 does not touch (R11) — the legacy research lane only

Inside `subsystems/research/clue_research/`:

- the trust-tiered waterfall and its resolvers: `resolvers/`, `sources/`, `adapters/`,
  `official_site/`, `ingestion/`;
- the old account-research lane: `profiling/`, `synthesis/`, `narrative/`, `verification/`,
  `coverage/`, `review/`, `proposals/`, `discovery_scoring/`, `stage0/` (the legacy recon behind
  `legacy_stage0_recon_enabled`), `durable/` (the project-run phase drivers), and the quarantined
  M8D entity-research runtime;
- the old claim-store substrate and its DSAR: `claimstore/`, `identity/`, `compliance/`
  (ARV2's rows are the only truth; its own erasure is D10, §6).

Also untouched: the legacy fleet *drivers* those packages register (the fleet worker *process*
itself is instrumented at its root, §5.1), and `apps/frontend/**` (lane 2's).

**In scope, not legacy:** `platform/**` (chat API, fleet workers, projections, agents, ARV2,
toolbelt) and `libs/**`. **`subsystems/clue-design/**` is in scope but held (R12)**: not edited by
slices 1–4; picked up first, as high priority, once its agent structure is finalised.

Each lane 3 plan repeats this list under "files not touched", and its review checks the diff
against it.
