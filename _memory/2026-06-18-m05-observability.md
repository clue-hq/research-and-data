# 2026-06-18 — M0.5 observability & tracing skeleton (ENG-125)

Implemented directly in the main loop (single serial issue; M0.5 → M0.6 is the serial M0 tail).
Linear ENG-125 → In Progress → Done. Depends on M0.2 (attr types) + M0.4 (redaction helper).

## What shipped (`src/clue_research/obs/`)
- `attributes.py` — standard attribute key constants (entity_id, entity_type, field_key, source_tier,
  source_key, research_mode, run_id, cost_cents, client_id, icp_id, campaign_run_id), `STANDARD_ATTRIBUTES`,
  `SpanAttributes` TypedDict, `to_otel_value` (coerce → OTel-acceptable), `safe_attributes` (redaction).
- `spans.py` — reserved span names: `resolve.<src>` (M4), `merge.current_value` (M1),
  `verification.{corroboration,faithfulness_judge,identity_binding}` (M9), `compliance.use_gate` (M10,
  DISTINCT from the judge — Doc D §5), `CAMPAIGN_PHASES` (exact Doc C §4 tuple) + `phase_span()`.
- `tracing.py` — `traced_step(name, **attrs)` context manager + `traced` decorator (ParamSpec). Owns a
  module-local `TracerProvider` (not the global) so `configure_tracing(exporter|console)` can reconfigure
  freely (test helper swaps it). Console exporter for dev; in-memory for tests; OTLP pluggable later.
- `metrics.py` — `MetricSink` Protocol (swappable backend; in-memory default `InMemorySink`) +
  `set_metric_sink`. Emitters read claim provenance: `record_source_yield`, `record_verification_health`,
  `record_cost_burndown` (exact Decimal sum), `record_phase_progress`. Metric name constants.
- `logging.py` — `RedactingFilter` (scrubs msg + string args via config.redact; keeps numeric args native
  so %d/%f formatting survives) + `configure_logging` + `get_logger`.
- `testing.py` — `collect_spans()` context manager (InMemorySpanExporter; saves/restores the provider).
- `__init__.py` — 48-symbol public seam.

## Key decisions
- **OTel for tracing** (the spec's "OpenTelemetry-shaped" requirement); **MetricSink abstraction** for
  metrics (OTel-metrics testing is heavy; the swappable-backend seam is the point — an OTel sink plugs in
  for prod). Flagged both judgment calls to the review.
- **UUID-safety in redaction (the key subtlety):** config's `_looks_secret` value-shape heuristic
  (`_OPAQUE_TOKEN = [A-Za-z0-9_\-]{24,}`) MATCHES a 36-char UUID → would mask entity_id/run_id. Fix:
  `safe_attributes` treats STANDARD keys as known-safe (coerce native, no value-shape redaction); only
  secret-NAMED keys + arbitrary EXTRA values get `redact_mapping` (force-mask secret-named, value-shape
  the rest). So entity_id stays unmasked; api_key / sk-… extras are masked.
- **per-source-yield keyed by `source_url`** (the spec says "by source_key", but M0.2 claims carry
  source_url not source_key) — documented; M4 normalizes to source_key. (Flagged to review.)
- Deps added: `opentelemetry-api>=1.20`, `opentelemetry-sdk>=1.20` (resolved to 1.42.1).

## Verification
- `make check` GREEN: ruff, mypy --strict **42 files**, import-linter **5 kept/0 broken** (obs imports
  only core+config; obs→config→core layering), **151 passed + 7 skipped** (+17 obs tests).
- Live span smoke: `traced_step("merge.current_value", entity_id=<uuid>, field_key=…, api_key=…)` →
  span name correct, entity_id present+unmasked, api_key ***REDACTED***.
- All 5 acceptance criteria have explicit tests (tracing name+attrs, judge≠use-gate distinct,
  secret redaction in span + log, metric increments from synthetic claims, phases == Doc C §4).

## Review outcome (wf_01b9a812-48b, 4 lenses → verify): 2 confirmed (3 rejected), both fixed
- **[major] secret leak via nested containers** — an extra attr like `payload=["safe","sk-live-tok"]`
  was `str()`-ed to `"['safe', 'sk-live-tok']"`, which the `^`-anchored secret patterns miss → leak
  (spans AND logs). FIX at the source: `config.redact()` now **recurses into Mappings/sequences**
  (element-wise) before the scalar str() fallback — NOT removing the `^` anchors (that would
  over-redact benign strings like "api-docs"). Hardens M0.4's helper for all callers. Added config
  container-redaction tests + an obs nested-secret span test. (This edits M0.4's secrets.py — a
  security fix riding with M0.5; ENG-120 left Done.)
- **[minor] per-source-yield keyed by source_url not source_key** — confirmed reasonable for M0.5
  (claims lack source_key until M4). FIX: strengthened `record_source_yield` docstring with the M4
  re-keying/migration note (dashboards + learning loop must treat it as a re-key, not a new source set).
- Post-fix `make check` GREEN: ruff, mypy 42 files, import-linter 5 kept/0 broken, **153 passed + 7 skipped**.

## Status
- Committed on current branch; ENG-125 → Done.
- Not committed yet. After review + fixes: commit on current branch + ENG-125 → Done.
- Next: **M0.6** (test + eval-harness scaffold + CI — the last M0 issue; depends on M0.3–M0.5). After
  M0.6, M0 closes and the graph fans out (M1 → {M2,M3} → M4 → {M5,M6,M7,M9} → …).
