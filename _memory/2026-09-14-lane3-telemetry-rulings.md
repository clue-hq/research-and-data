# Lane 3 (telemetry + cost) — founder rulings, 2026-09-14

Scope reset: the founder replaced the four-tool eventual architecture (structlog + Langfuse +
OTel + OpenMeter, LiteLLM optional) with the "Paid Pilot Observability v1" ten-point milestone
(pasted plan 2026-09-14 13:58). No design doc or code exists for lane 3 yet.

## Rulings
- **Langfuse records every tool call the agent makes** — local tools and provider tools alike —
  and **every spend** (LLM and external provider), nested under the sub-agent that made it.
  Langfuse is the observability layer, not the source of truth.
- **Postgres stays the ledger of record.** `provider_call_ledger` (workspace / project /
  project_run / job / provider / operation / phase / usd / credits / media_seconds) and
  `agent_model_call` are authoritative; the halt latch and the client cost cap read them
  in-process. Langfuse receives the settled figures as ingested cost — never recomputes.
- Provider-level cost attribution (per run, per account-research job, per workspace, overall,
  by provider and operation) is in scope now; it is a GROUP BY over existing ledger rows plus a
  read that joins the model-call receipts. Build the cost read as the FIRST slice.
- Deferred, per the pasted plan: OpenMeter (until credits/quotas), SQLAlchemy/Redis
  auto-instrumentation (until DB latency is a real problem), LiteLLM (never for observability).
- Every new provider (Websets included) must go through `ProviderCaller` so it lands on the ledger.
- Stamp the Langfuse trace id + observation id on each ledger row / model-call receipt so a
  ledger row can be opened in Langfuse (cheap four-level attribution without a four-level schema).

## Already built (verified 2026-09-14)
- `libs/clue-obs`: structlog with `bind_*` run context; `redact.py` strips secret keys, masks
  claim values, collapses blobs; OTel `traced_step` + `configure_tracing` — **no production
  caller**, so spans are created and dropped today.
- Gateway tracing decorator: tokens + `cost_cents` per model call; `agent_model_call` receipts.
- `platform/api/clue_api/arv2/calls.py` `ProviderCaller` → `provider_call_ledger`, `CallCost`
  with `cost_source` metered/free/estimate.
- All outbound HTTP is httpx (32 files; no `requests`/`aiohttp`) → one instrumentor covers all.
- Not present anywhere: Langfuse, Sentry, OTel instrumentors, OTLP endpoint in `.env.example`.

## Decisions
1. **RULED 2026-09-14:** full prompt / tool payloads go to Langfuse with secrets stripped
   (secret-key rule only; claim-value masking does NOT apply). **REVISED later the same day:
   Langfuse CLOUD (EU), not self-hosted** — the self-hosting condition is withdrawn.
   DSAR: ARV2 has NO erase path (master plan D10 unbuilt); the only `erase` is the old lane's
   `compliance/dsar.py`, which is off limits. Lane 3 only tags traces with entity ids so deletion
   is a query; the Langfuse deletion step belongs to D10.
4. **RULED 2026-09-14: the LEGACY research lane is never touched by lane 3** — legacy means
   only the waterfall + the old account-research lane inside `subsystems/research/clue_research/`
   (resolvers/sources/adapters/official_site/ingestion; profiling/synthesis/narrative/
   verification/coverage/review/proposals/discovery_scoring/stage0/durable; claimstore/identity/
   compliance; the M8D quarantine; the legacy fleet drivers). **Founder corrected my over-draw:
   the fleet worker processes, projections, chat API, ARV2, libs, and the design subsystem are
   live and IN scope.** Process-wide httpx/FastAPI instrumentation observes legacy calls as a side
   effect only. Every lane 3 plan carries a "files not touched" list (design note §11).
5. **RULED 2026-09-14, then HELD the same day:** the design subsystem is OUT of lane 3 for now —
   the co-founder is changing its agent structure. **HIGH PRIORITY to pick up first once that is
   final** (root OTel/Sentry, Langfuse on the design leg, ledger rows for its paid calls). The
   ruling on what to do stands: design subsystem's own external calls get `provider_call_ledger` rows
   via a `ProviderCaller`-shaped seam — today that is `lumen_api/image_provider.py` (T2I) and
   `lumen_api/ad_runtime.py` (ad-DNA model: posts straight to OpenRouter, bypasses the gateway,
   records NO cost today). Recommended: move ProviderCaller/CallSpec/CallCost/LedgerSink out of
   `arv2/calls.py` into a shared lib so design can import it (seam discipline). Design-gate review.
6. **RULED 2026-09-14: erasure endpoints (ARV2 D10 + Langfuse trace deletion) = second priority,
   its own lane** after lane 3 slices 1–3; depends only on lane 3's entity-tagging slice.
2. **RULED 2026-09-14:** Sentry cloud (free tier), `include_local_variables=False`,
   `send_default_pii=False`; run context (workspace/project/run/thread/turn) on every event.
3. **RULED 2026-09-14:** OTel spans export to the self-hosted Langfuse's OTLP endpoint, so
   FastAPI/httpx spans and the agent tree share one trace id in one viewer. A separate
   collector + Tempo/Jaeger is the deferred Grafana stack.

## Proposed slices (not yet approved)
1. Cost read over the two ledgers. 2. Roots: OTel exporter + FastAPI/httpx instrumentors +
Sentry, run context on spans, `.env.example` parity. 3. Langfuse: LangGraph callback in the
runtime callback tuple (`agent_runtime_wiring.py` ~L1336), gateway decorator for non-graph
calls (one path per call), provider caller reports settled cost onto the tool observation,
redaction before export, ids stamped back onto ledger rows.

## Design note
`docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` (draft, written
2026-09-14 after all three decisions were ruled; awaiting founder review; not committed).
