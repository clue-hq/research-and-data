# Lane 3 slice 5 — the design subsystem's cost, tracing and telemetry — 2026-09-18

Branch `lane3/slice5-design-spend` (unpushed, local commits only), off `research-streaming` after
PR #62 lifted the R12 hold. Design
`docs/superpowers/specs/archive/2026-09-18-lane3-slice5-design-subsystem-design.md`; plan
`docs/superpowers/plans/2026-09-18-lane3-slice5-design-subsystem.md`. SDD with Opus implementers;
the controller reviewed every task personally and re-ran each task's named suites first-hand.

Before this slice the design subsystem was the last live spender off the platform's stack: the
trio ran on the governed gateway (so cost and role existed per call) but wrote no `agent_model_call`
row; five raw httpx OpenRouter clients and the image provider discarded `usage` entirely; the
design API root installed no OTel, Sentry or Langfuse. The slice-4 coverage audit recorded exactly
this as "NOT on Postgres — the design subsystem's image/ad-DNA calls (R12 hold): nothing".

## What shipped

- **Task 1 — `13cd532df`.** The provider-caller seam moved out of the ARV2 lane into
  `libs/clue-spend` (`clue_spend`): `ProviderCaller`, the ledger/raw sinks, the drain, the
  OpenRouter cost reader and halt rule, the transport, the typed errors. `clue_api.arv2.*` are now
  re-export shims — the same classes, so `except ProviderHalted` written against either import path
  catches the same object. The package depends only on `clue_core`, `clue_obs` and SQLAlchemy (no
  `clue_api`, no `clue_research`, no `lumen_*`), which is what lets a subsystem import it without
  importing the platform; `tests/spend` enforces that. `drain_provider_calls` gained an
  `on_failure` incident hook, an optional `artifacts=None` (a lane whose bodies are not persisted
  to the platform's artifact store lands rows citing nothing there), and `DrainReport.result_rows`.
- **Task 2 — `bd9732169`.** `clue_obs.production` now owns the three production installers; the
  design API root (`lumen_api/main.py`) installs OTel, Sentry and Langfuse under service name
  `clue-design-api`, guarded on "no SDK tracer provider yet" because the fleet worker lazily
  imports `lumen_api.main` and must not re-install over the worker's own provider. The lumen
  pyprojects declare their `clue-obs` / `clue-gateway` dependencies for the first time.
- **Task 3 — `bd7a27879` + `504c86251`.** `lumen_api/spend.py`: one `SpendScope` per unit of work
  (an ingestion job, a design-leg turn, one API request) carried in a contextvar, so the clients
  that spend do not thread a caller through every signature. All ten operations now go through it —
  `design.image.generate` / `design.image.edit`, the four ingestion models
  (`design.ingestion.describe` / `.vision` / `.assist` / `.brief`), `design.ingestion.ad_dna`,
  `design.ad.style_group`, `design.logo.brand_api`, `design.ad_library.harvest`. The image receipt
  names its own ledger row. Brandfetch and Adyntel are `free` with `credits=1` (ruling §6.5).
  `ProviderHalted` becomes job `failure_code=provider_refused:openrouter:<reason>` in
  `lumen_ingestion/jobs.py`. The ad style-group tie-break makes one attempt, never a retry.
- **Task 4 — `2a20090ff`.** `lumen_agent/usage_collector.py`: `ModelCallCollector`,
  `CollectedModelCall`, `TurnCallbacks`, `turn_collector`. Attached at the INVOKE CONFIG, not on
  the model instances — a config-level callback sees every model, tool and sub-agent event in the
  graph, so one collector per turn sees the orchestrator, the author, the reviewer and anything
  they delegate to, and each receipt's role comes from the gateway's own stamp rather than from
  which object the handler was bolted to. The executor stamps `result_json.model_calls` on every
  terminal return. The brief agent records through `record_collected_model_call`.
  `usage_capture.py` is deleted; `extract_usage` is public.
- **Task 5 — `d5e9cb93a`, `11237d238`, `70ca1fdce`.** The design leg's turn runs inside a
  `design-leg.turn` trace + observation with `tag_entities`; `design_fleet` injects the Langfuse
  factory on the leg lane (once per turn — a shared handler would cross-attribute one turn's model
  calls onto another's observation) and the ARV2 drain on both lanes; `receipts_from_design_run`
  reads `run["result"]` and re-keys the collected calls onto the platform's turn;
  `DesignTurnEnvelope.project_id`; the exit judge runs with `role=design`; the `NOT_COVERED` design
  entry is removed from the coverage map. Receipts are recorded on **every** terminal return of
  `_dispatch`, not only after a drive.
- **Task 6 — this note, the `.env.example` telemetry-roots comment (no key change; parity
  verified empty), and two parked naming nits in `576af23d7`: `clue_spend.errors.Arv2Error` →
  `SpendError` with `Arv2Error` kept as an exported alias (not a subclass), and
  `clue_obs.production`'s logger renamed off its inherited `clue_api.tracing`.**

## The three paths worth remembering

- **Collector → receipt.** Gateway stamps (`clue_gateway.metadata`: answering model, settled cost,
  role) → `ModelCallCollector` (sync, because the design agent invokes synchronously on a worker
  thread; it never prices anything itself) → `CollectedModelCall.as_json()` → the run row's
  `result_json.model_calls` → `receipts_from_design_run` → `agent_model_call` with
  `role=design`. `cost_cents` rides as a STRING so the Decimal survives the jsonb round trip;
  `None` stays `None` — an unpriced call is never a measured zero. The sub-role (orchestrator /
  author / reviewer) stays in Langfuse and the logs, because `design` is the profile role the
  ledger's CHECK knows.
- **Spend scope → ledger, and the unscoped fallback.** `spend_scope` per unit of work →
  buffered raw + ledger sinks → drain at unit end onto `provider_call_ledger`. The drain is
  INJECTED whole (`drain_fn`), not a hook: the library drain writes rows and nothing else, and the
  platform wraps it with its own provider-incident bookkeeping at its composition root, so the ARV2
  last-word close rule is written once and this module never learns the platform exists. A design
  process running alone falls back to the bare library drain. `drain_sync` exists for the
  synchronous executors and owns a **private** engine on its own loop (`clue_db.get_engine()` is
  process-global — it raises in a design worker and is bound to another loop where it does not).
  **A call made with no scope open is still recorded in memory and warned about once**, so a missed
  scope is visible and never silently unpriced.
- **Incident labels.** `_surface_for` reads the design operations first: `design.ingestion.*` →
  `design_ingestion`, any other `design.*` → `design_turn`. Ingestion is separated from a turn
  because brand-kit ingestion is a one-off cost with a different owner than a marketer's turn, and
  a breakdown that folded them would answer neither question. The design branches must stay first:
  a design turn carries no ARV2 stamp, so every later branch would fall through to the raw
  operation and the design surfaces would never be named.

## Finding F-1 — a live bug this slice found and fixed (`d5e9cb93a`)

Since lane 3 slice 2, `clue_fleet.queue._with_trace_carrier` stamped `traceparent`/`tracestate`
into every enqueued payload. `DesignTurnEnvelope` and `DesignIngestionEnvelope` are
`extra="forbid"`, so **every QUEUED design job failed at `lumen_api.fleet_handler._parse`** with
`design_job.preamble_error` — 47 such failures in this lane's worker logs on 2026-09-17 between
20:39 and 21:03Z. Inline design-leg turns bypass that parse, which is why chat-driven page
generation kept working while brand-kit ingestion and queued design turns did not. Fixed at the
worker: `WorkContext.payload` excludes `clue_obs.otel.CARRIER_KEYS`, and the span still parents on
the row's carrier.

## Rulings

- Spec §6.1–6.6 taken as recommended: role `design`; the seam's home is `libs/clue-spend`;
  ingestion spend (including the brief agent) lands on the ledger; the installers live in
  `clue_obs.production`; Brandfetch/Adyntel are `free` + `credits=1`; the editor's generate route
  drains inline.
- **PRE-1b** — inject the whole drain, not a hook, so the ARV2 last-word close rule is written once.
- **PRE-2** — task order 1, 2, 3, 4, 5, 6.
- **PRE-3 / T3-2** — `openrouter_call(max_attempts=4)`; the ingestion clients 2; style-group 1.
- **T1-1** — `tests/arv2/test_import_guard.py` stays red on its two pre-existing offenders; the
  seam move does not adopt them.
- **T3-1** — `DesignTurnEnvelope.project_id`.
- **T5-1** — receipts on every terminal return, not only after a drive.

## Verification

Each task's named suites re-run first-hand by the controller. `lint-imports` 28/0 throughout;
`mypy` clean. Task 6: `tests/spend` + `tests/arv2/test_calls.py` +
`tests/api/test_production_langfuse.py` → 42 passed; `uv run ruff check` clean on the three
touched files; `.env.example` ⇄ `.env` key parity prints nothing.

**Run the design-subsystem suites that touch the queue with the lane stack DOWN** — a live design
API's embedded worker and the live fleet workers claim test jobs out of the shared lane DB. With it
down: `test_ingestion_brief` + `test_ingestion_jobs` → 33 passed; the five fleet-queue DB suites
(`tests/design/test_design_fleet_{turns,r3b,reaper}_db.py`, `tests/fleet/test_fleet_db.py`,
`tests/fleet/test_exit_gate.py`) → 47 passed.

Two failures on this machine are `.env` key leaks into the test process, not code:
`test_fleet_wiring::…lane_flag_and_the_key…` and
`test_production_langfuse::test_enabled_without_both_keys_skips_and_boots`. Run the langfuse one
without the lane `.env` sourced.

The lane stack was taken `down` and brought back `up` on this branch by the controller; all six
processes are UP. No restart is owed.

## Owed live proofs (founder-triggered, on the lane stack — they spend money)

Nothing below has been run; all five are owed.

1. **One web-page design turn** → a `design-leg.turn` trace in Langfuse with priced generations
   nested under it, and:
   ```sql
   SELECT sequence, role, answering_model, cost_usd, cost_source, langfuse_observation_id
   FROM agent_model_call WHERE role='design' ORDER BY started_at DESC LIMIT 10;
   ```
   shows the trio's calls; `make cost-report ARGS="--workspace <ws> --project <project>"` includes
   them.
2. **One brand-kit ingestion** →
   ```sql
   SELECT operation, outcome, cost_usd, credits, extras_json->>'model' AS model,
          extras_json->>'cost_source' AS cost_source
   FROM provider_call_ledger WHERE operation LIKE 'design.%' AND phase='result'
   ORDER BY recorded_at DESC LIMIT 20;
   ```
   shows describe / vision / assist / brief rows keyed by the job, plus a `design.logo.brand_api`
   row with `credits=1`.
3. **One image generation from the agent and one from the editor route** → `design.image.generate`
   rows with `cost_source` metered or estimate.
4. **A forced 402** (a wrong OpenRouter key on the ingestion model) → job
   `failure_code=provider_refused:openrouter:auth_invalid` (or `payment_required`) and a Sentry
   incident event.
5. **The design API root** → a FastAPI span under `clue-design-api` in the OTLP target (or the
   tracer provider's resource name in a log line), and one forced exception in Sentry with run
   context.

## Follow-ups

- Proof 2 is also the first real confirmation that F-1 is closed end to end: before `d5e9cb93a`
  every queued ingestion died at the envelope parse, so no operator has yet seen a design ingestion
  job succeed on this lane.
- The slice-4 coverage audit's "NOT on Postgres" list should be re-read once the proofs land; the
  design entry is the one this slice removes.
