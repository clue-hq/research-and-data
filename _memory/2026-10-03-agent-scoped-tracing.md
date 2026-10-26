# 2026-10-03 — agent-scoped tracing and one trace id across tools

Branch `obs/agent-scoped-tracing` (off `origin/research-streaming` 347a48a9b). Local commits only,
not pushed. Spec: `docs/superpowers/specs/archive/2026-10-03-agent-scoped-tracing-and-one-trace-id-design.md`
(founder-approved in chat; R1–R8). This PR = R1–R7. R8 + Grafana Tempo/Loki = PR 2.

## Why (found in production, first day)
- `clue-prod` Langfuse: ~1,195 of ~1,200 traces were FastAPI request traces; every trace labelled
  `default` (the env-less request root; `langfuse-sdk` observations themselves were `production`).
- A chat turn and every research job it launched were ONE trace (fleet task joined the enqueuer's
  trace): 1,300 observations for two accounts; 118 raw httpx `POST` spans; an empty
  `llm.gateway_call` generation duplicating every `GovernedAgentChatModel` generation.
- Sentry trace ids are Sentry's own (tracing off) — matched nothing. Logs had no trace id.
- `log_span` logged tool refusals at error → Sentry issue CLUE-PRODUCTION-3 (`read_discovery_run`
  before discovery; the agent repaired it).
- Design: only the inline leg lane passed the LangChain handler; queued `design_job` on the fleet
  and the brand-brief agent reported nothing to Langfuse.

## What changed (commits on the branch)
- R1/R2 `clue_obs.langfuse`: `should_export_span = langfuse.span_filter.is_default_export_span`
  (health-check filter removed). Env label follows automatically.
- R3 `clue_fleet.work_worker`: `fleet.task` is a NEW root (`clue_obs.otel.task_trace_start`) with a
  span link to the enqueuer; binds `launched_by_trace_id` (also in `RUN_CONTEXT_KEYS` +
  `STANDARD_ATTRIBUTES`, else `safe_attributes` redacts the hex); `propagate_trace` adds it to trace
  metadata. Research job trace tag `account:<domain>`. Supersedes slice-2 D1 join.
- R4 `clue_obs.otel.trace_ids.add_trace_ids` in the shared log pre-chain (+ twin in `py_lumen_obs`,
  which now declares `opentelemetry-api`); worker stamps escaping exceptions (`__clue_trace_ids__`).
- R5 `clue_obs.sentry`: event `contexts.trace` + `trace_id` tag = OTel ids (set AFTER redaction),
  `contexts.langfuse.trace_url = {host}/trace/<id>` (Langfuse redirects to the project; verified 307).
- R6 `log_span(expected=...)`; toolbelt runner expects `PreconditionFailed`, `ToolAwaitingInput`.
- R7: `ClueLangfuseHandler` MOVED `clue_api.langfuse_callbacks` → `clue_gateway.langfuse_handler`
  (re-export shim kept; import-linter exemption moved; clue-gateway declares langfuse). Design
  `DesignJobWorkHandler` opens `design.turn` / `design.ingestion` / `design.asset_analysis` per job
  (`named_trace=False` for the inline lane), defaults turn callbacks to the platform handler; brief
  agent runs with the handler.

## Verification
- Unit tests per requirement, each watched red first. Wide non-DB run: see closing entry.
- NOT yet verified in production (owed after deploy): Langfuse list holds only agent/model traces,
  all `production`; one turn launching research = 1 turn trace + 1 per job with
  `launched_by_trace_id`; a worker log `trace_id` opens the trace; a design job and an ingestion
  job appear as named traces with their model calls inside.

## Failures observed (not from this branch)
- Design `test_write_path_governance` x2 (`design_enrich_assets`, `asset_enrichment.py` from
  9cc82d08d on research-streaming); `tests/api/test_design_memory_fleet.py`
  `test_production_handler_gates_only_design_preference_producer` x3
  (`head_of_abm_continuation_enabled` missing on the SimpleNamespace settings). CORRECTION: the
  same file's `test_inline_and_drain_hosts_receive_same_resolver_factory` WAS broken by this branch
  (`named_trace` extra) and first misreported as pre-existing; fixed after the review.
- Design route tests hit the default `localhost:5432/clue` (Homebrew pg17, old revision
  7c4fe6965720, the design suite's accumulating scratch DB) → `workspace_hostname` missing. Run
  design DB tests only with an explicit disposable `CLUE_DATABASE_URL`.

## Open
- The sync `/agent/turn-preview` route (not a fleet job) opens no named trace and passes no
  handler. The embedded design-API worker (off in prod, `LUMEN_EMBEDDED_FLEET_WORKER=0`) builds the
  same design-side handler, so it gets named traces and the default handler too.
- PR 2: R8 (design non-agent OTel spans + log the silently stored failures) and Grafana Tempo/Loki
  (needs a founder Grafana token with logs/traces write; revoke the leaked one).

## Closing (2026-10-03)
- Fresh Opus review of the whole branch: 1 Important (the test above, fixed), minors: Sentry
  Langfuse link now only when the client is installed (fixed, test added), stale comments
  (fixed), remaining gaps written into spec §2.2.
- Wide offline run (obs, fleet, toolbelt, gateway, arv2, Langfuse/fleet-wiring api tests): green.
- Nothing pushed. Production verification owed after deploy (see Verification above).
