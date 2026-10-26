# Lane 3 slice 3 — Langfuse (3a foundation + 3b richness) — 2026-09-15

Branch `lane3/sice1b` (the founder's; unpushed, no upstream), after slices 1b and 2. Design
`docs/superpowers/specs/archive/2026-09-15-lane3-slice3-langfuse-design.md` (cd962c712); plans
`docs/superpowers/plans/2026-09-15-lane3-slice3a-langfuse-foundation.md` and
`...slice3b-langfuse-richness.md`. Executed via SDD (Opus implementers, controller reviews). Both
SDD workspaces deleted after this note.

## What shipped

3a — 5bcea2819 settings/secrets/env/dependency/import contract · dcb6c6955 + dc204a52a
`clue_obs.langfuse` (client on the slice 2 provider, mask, observation/event/guardrail helpers, run
registry) · 1c66e774f roots (`install_production_langfuse` at `projections_main` and `fleet_main`;
the lifespan flushes Langfuse before the provider stops) · 58586fb5b migration `b7193eb28363`
(`agent_model_call.langfuse_trace_id` / `langfuse_observation_id`) + receipt fields + replay compare
· c970b3246 `clue_api.langfuse_callbacks.ClueLangfuseHandler` (registry filled at model-call start;
settled cost written onto the generation before the SDK ends it) · e6a169c8f the turn runtime
(handler in the tuple, `propagate_trace("head-of-abm.turn", session=thread, user=workspace)`,
receipts stamped, `clue_answering_model` preferred) · 42e2ee97e the streamed `answering_model` fix
(one-chunk lookahead in both stream paths) · b72ebd9d7 `make langfuse-check` + the stack status
line · 6e9add57d docs.

3b — 6e51be66b `TracingGateway` generation/embedding observations · 9015f4e8b + b81b84aa8
`ProviderCaller` observations (typed by operation; settled money; ledger row id; halt-latch and
ceiling guardrails; result rows carry the Langfuse ids; host without userinfo) · 764a814f5
`ToolInvoker` `governed.<tool>@<version>` tool/retriever observation with the disposition ·
fe8eb3660 + c9b964232 the research job as one `arv2.account_research` agent observation (priced
rounds with generation ids on their ledger rows, ending event, cap guardrails) · 5b796a3d8 the
exit judge as an `evaluator`, `TurnWorkGuard` guardrail.

## Decisions and rulings

- D1 one provider: Langfuse attaches to the slice 2 `TracerProvider` (no OTLP endpoint needed;
  `CLUE_OTEL_TRACES_ENDPOINT` stays the seam for any other collector). D2 settled cost on every
  graph generation via the handler's `_runs` map. D3 `CLUE_LANGFUSE_*` names beside the Sentry
  names. D4 exact receipt ids from the registry filled at model-call start.
- The mask applies the secret-key rule itself (recursive with key), the blob rule and truncation —
  never `redact_value` (whose claim-value rule would placeholder `value_json`/`evidence_span`).
- The Langfuse import contract exempts `clue_obs.langfuse -> langfuse` and
  `clue_api.langfuse_callbacks -> langfuse` (grimp squashes external submodules to the top-level
  package under `include_external_packages`).
- Tool-shaped provider calls carry money as `metadata.cost_usd`: the SDK writes native
  cost/usage only on generation-like observations; Postgres stays the authority (R2).
- READ governed tools are `retriever` observations, everything else `tool`; no per-tool declaration.
- The research agent's round rows take the registry's `latest()` ids (one round at a time). The
  job is wrapped in an `agent` observation because `propagate_attributes` opens no span and the
  handler's root chain span has ended by the time the graph returns — without it the ending event
  started its own trace.
- A stream that fails after one chunk that never left the generator now retries/falls back.

## Env and credentials (the founder's step)

Local `.env` (never committed) and `.env.example` carry `CLUE_LANGFUSE_ENABLED=false`,
`CLUE_LANGFUSE_HOST=https://cloud.langfuse.com`, `CLUE_LANGFUSE_PUBLIC_KEY=`,
`CLUE_LANGFUSE_SECRET_KEY=`, `CLUE_LANGFUSE_ENVIRONMENT=lane-san-salvador`. To go live: paste the EU
project's key pair into the lane's `.env`, set `CLUE_LANGFUSE_ENABLED=true`, run
`make langfuse-check` (exit 0 = the host accepted the keys; sends no trace), then restart both API
twins and the workers (`./scripts/dev_stack_san_salvador.sh` verbs). Enabled without a key
refuses at composition, like Sentry.

## Facts worth keeping

`Langfuse(tracer_provider=)` adds its processor to our provider; `Langfuse(span_exporter=)` is the
test seam (`tests/_langfuse.py::langfuse_installed()`); the SDK keeps one resource manager per public
key (`LangfuseResourceManager.reset()` in tests). LangChain runs every handler's start event before
the model call, so ids captured at start reach every handler's end; end events run concurrently,
which is why the cost update lives in the Langfuse handler. Health-check server spans are dropped
by `should_export_span`. The doubled `answering_model` came from two provider chunks each carrying
`model_name` plus our per-chunk stamp; LangChain's chunk merge concatenates strings.

## Verification

Per task: focused suites + ruff + mypy (4 pre-existing) + lint-imports (27 kept / 0 broken). 3a
whole-branch: 124 offline + 11 lane-DB tests; migration round trip on a fresh `clue_lane3_smoke`.
3b whole-branch: see the closing entry below. Lane DB `clue_lane3-cost-read` at head `b7193eb28363`.

**Owed (founder-triggered):** one chat turn and one research job opened in Langfuse after the keys
are set; the receipt's `langfuse_trace_id` and a ledger row's `extras_json.langfuse_trace_id` open
those traces. Next lane 3 work: slice 4 (entity tags on traces), the held design slice (R12), the
erasure lane (R13).
