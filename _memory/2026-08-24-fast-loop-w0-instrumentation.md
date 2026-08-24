# 2026-08-24 — Fast Loop v1, W0: per-run deepagent metrics (instrumentation first)

Implements §7 "Metrics first" of `subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md`
(RATIFIED 2026-08-24). Base HEAD `59b557931`. Behaviour-neutral and purely additive: no
existing event shape changed, no field removed, no loop change.

## Why
The spec's §1 frozen baseline (43m18s, 178 LLM calls, 13.5M input tokens, first preview at
+15.4 min) was hand-aggregated from ~6000 raw log lines. Every number was already in the trace
and unreadable without a spreadsheet. W0 makes that aggregation automatic so the §1 gate table
can be proven or refuted per run, BEFORE any loop change moves the numbers.

## What landed
- **`lumen_agent/run_metrics.py` (new)** — `RunMetrics`, the per-run accumulator (integer
  counters under one `threading.Lock`, needed because batched read-only tool calls arrive from
  langgraph's ToolNode thread pool). Plus `emit_run_metrics(tools, …)` and `count_round_dirs`.
  No LLM call, no tool call, no hot-loop I/O — one file write at run end.
- **`trace_callbacks.py`** — `TraceCallbackHandler(role, metrics=None)` /
  `attach_trace_callback(model, role, metrics=None)`. `on_llm_end` / `on_llm_error` fold the call
  into the accumulator inside their already-wrapped bodies. A metrics object that raises is
  dropped at construction (tracing carries on).
- **`tools/substrate.py`** — `LumenDesignTools.metrics` born in `__init__` (earliest run moment,
  so `wall_time_ms` covers the whole turn); `mark_compile_iteration()` in `compile_dsl_block`;
  `mark_first_preview()` in `_write_and_validate_preview_artifacts`, only for a VALIDATED
  artifact (a written-but-broken preview is not something the agent could see).
- **`harness.py`** — `_instrument` threads `getattr(tools, "metrics", None)` to the tracer;
  `run_deepagent_turn`'s tail is wrapped in `try/finally` so ONE summary is emitted on EVERY
  terminal outcome, failures included.
- **`trace.py`** — the CLI viewer renders `run_metrics` (and it survives `--role` /
  `--tools-only` / `--messages-only`, because the summary belongs to the whole run).
- **`apps/api/lumen_api/run_view.py`** — `_extract_run_metrics` lifts the summary out of the
  `design.run.event` stream into `RunView.metrics` + `manifest["metrics"]`; absence becomes a gap.
- **`scripts/run_view.py`** — a "## Run metrics" README section: the §1 gate table beside the
  run's own numbers, plus the per-role split.

## Three sinks, one set of numbers
`logs/run.jsonl` (obs logger, what the trace viewer reads) · `metrics.json` in the run directory
next to `final.json` · the substrate `record` whose `sink_extra={"metrics": …}` puts it on the
durable `run_event` stream, which is how the run view sees it without touching the worker's disk.

## Schema (`run_metrics` event == `metrics.json` == `run_event` payload `data.metrics`)
`run_id, outcome, status, stop_reason, wall_time_ms, llm_calls_total, llm_calls_failed,
llm_calls_over_30s, input_tokens_total, output_tokens_total, time_to_first_preview_ms (null if
never), rounds_total, compile_iterations_total, by_role{<role>: {calls, failed,
duration_ms_total, duration_ms_max, input_tokens, output_tokens}}`.

## Verified
- `apps/agent_runtime`: `pytest tests/` → 630 passed, 3 skipped (incl. the new
  `tests/test_run_metrics.py`, 17 tests: accumulator, tracer wiring, emission, the real
  `run.jsonl` sink, the substrate marks, the FAILURE path, the viewer).
- `apps/api`: `pytest tests/test_run_view.py` → 15 passed, 4 skipped (need `CLUE_DATABASE_URL`);
  `tests/test_api.py` re-run clean.
- The design full suite (>1h) was deliberately NOT run inline.

## Residuals / not done
- **`autofix_count`** (also named in §7) has no producer yet — deterministic autofix is §5.4,
  a later slice. Add the counter with it.
- **The web harness (`harness_web.py` / `web_substrate.py`) is not wired.** `_instrument` already
  passes `getattr(tools, "metrics", None)`, so it degrades to no-op cleanly. Its `iteration` counts
  RENDERS, not DSL compiles, and it has no `rounds/round_N` tree — emitting `compile_iterations_total`
  and `rounds_total` for it would be dishonest. Wiring it needs a per-harness decision on those two
  fields first.
- `rounds_total` is a directory count taken at run end (the orchestrator creates round dirs through
  its own file tools; the harness never sees a "round started" call). Cheap, but it is a filesystem
  inference, not an observed event.
- Per-call `duration_ms` comes from the tracer's own monotonic pairing, so a call whose
  `on_llm_start` never fired contributes 0 rather than being dropped.
- The §1 baseline row still needs re-recording under the new counters on ONE unchanged run
  (spec §7 "calibration") — that is a live-run task, not a code task.
