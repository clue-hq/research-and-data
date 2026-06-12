# Structured Logging

Date: 2026-06-12

Status: Phase F operational observability baseline.

## Purpose

The API now emits compact structured logs for product/runtime behavior without
turning logs into another source of truth. The canonical records remain:

- operation history, snapshots, and agent traces for audit;
- compiler/preflight/export diagnostics for user-actionable repair;
- structured operational logs for runtime observability.

Do not store full prompts, DSL blocks, scene JSON, Brand Kits, asset bytes, or
API keys in operational logs by default.

## Python API Logging

FastAPI configures JSON logging when `create_app()` is called. Every HTTP
request receives or preserves an `x-request-id` value, and every response
includes that same header.

Core request log fields:

- `timestamp`
- `level`
- `logger`
- `event`
- `message`
- `request_id`
- `method`
- `path`
- `route`
- `status_code`
- `duration_ms`
- `client_host`

Product workflow events include compact summaries:

- `document_created`
- `document_scene_replaced`
- `operation_batch_applied`
- `preflight_completed`
- `export_preview_completed`
- `document_export_completed`
- `agent_turn_preview_completed`
- `database_error`

These events log identifiers and counts, not raw payloads. Examples:

- `document_id`
- `run_id`
- `operation_count`
- `applied_operations`
- `diagnostic_count`
- `error_count`
- `warning_count`
- `top_diagnostic_codes`
- `artifact_count`
- `artifact_formats`
- `artifact_ids`
- `effective_brand_source`
- `brand_kit_id`
- `profile_name`

## Rust Helper Boundary Logging

The Rust helper is instrumented only at process/action boundaries. It writes JSON
lines to stderr so stdout remains the machine-readable helper response.

Helper events:

- `core_helper_started`
- `core_helper_completed`

Boundary fields:

- `source: lumen-api-helper`
- `request_id`
- `helper_call_id`
- `action`
- `duration_ms`
- `diagnostic_count`
- `has_error_diagnostics`
- `applied_operations`
- `has_scene`
- `has_geometry`
- `artifact_count`
- `error_code`

The helper does not log individual node operations or scene internals. Operation
history already records canonical mutations, and diagnostics already carry
user-actionable failures.

## Environment

```bash
LUMEN_LOG_LEVEL=INFO
LUMEN_CORE_HELPER_LOG=1
```

Set `LUMEN_CORE_HELPER_LOG=0` to disable Rust helper stderr logs. Python still
logs the helper invocation summary from `CoreClient`.

Future deep engine tracing should be gated separately, for example:

```bash
LUMEN_TRACE_ENGINE=1
LUMEN_LOG_LEVEL=DEBUG
```

That future mode may add per-pass layout/text/token/export spans, but it should
remain opt-in and should not change deterministic engine behavior.

## Redaction

The JSON formatter redacts fields whose key names look secret-bearing, including
API keys, auth headers, credentials, passwords, secrets, and tokens. This is a
safety net, not permission to log sensitive payloads.

Route and helper logs should continue to prefer:

- IDs over full records;
- counts over arrays;
- diagnostic codes over full failure dumps when possible;
- artifact references over artifact bytes;
- action names over raw operation payloads.
