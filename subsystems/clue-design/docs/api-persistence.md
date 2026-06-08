# API Persistence V0

`api/persistence-v0` adds a minimal FastAPI + SQLite persistence surface for Design Engine documents. It stores the canonical Rust `Scene` JSON and canonical `Operation` JSON; Python owns HTTP envelopes, SQLite rows, IDs, and metadata only.

## Boundary

- `lumen-core` remains the semantic authority for scene creation, validation, checked operation application, preflight, layout geometry, platform default brand kit loading, and finalization.
- The API calls `crates/lumen-api-helper` over JSON for core-semantic actions.
- The API does not run agents, spawn prompts, critique screenshots, upload asset bytes, or redefine scene/slot/brand/layout semantics.
- DSL remains an authoring projection. Persistence stores scene snapshots and operation history, not DSL as the document source of truth.
- Mutation/reporting routes return compact DTO envelopes for orchestration. Canonical `Scene`, `Operation`, diagnostics, snapshots, template revisions, and asset refs remain the persisted source of truth.

## Response DTO Boundary

The API mirrors the `agents/design-loop-v0` DTO decision: rich engine artifacts are persisted and loaded through explicit canonical routes, while mutation responses return stable summaries.

DTO envelopes include:

- `schema_version`
- action `status`
- compact document summary and scene counts
- operation summaries by sequence/kind
- operation/preflight application counts
- diagnostic views:
  - `audit`: all diagnostics in the response
  - `current`: diagnostics from the current action
  - `latest`: deduped latest diagnostics by source/code/subject
- snapshot or template-revision summaries where applicable
- effective brand-kit summary for preflight

Canonical load routes still return full canonical JSON because replay/export/editor load workflows need it:

- `GET /documents/{id}`
- `GET /documents/{id}/operations`
- `GET /documents/{id}/snapshots/{snapshot_id}`
- `GET /template-revisions/{id}`
- `GET /asset-metadata/{asset_id}`

Summary/list/mutation routes avoid embedding full scenes:

- `POST /documents`
- `PUT /documents/{id}/scene`
- `POST /documents/{id}/operations`
- `POST /documents/{id}/snapshots`
- `GET /documents/{id}/snapshots`
- `POST /documents/{id}/preflight`
- `POST /documents/{id}/finalize`
- `GET /documents/{id}/diagnostics`

## SQLite Backend

Migrations live in `apps/api/migrations/` and are applied explicitly at app/test setup.

### `documents`

Stores the editable draft/current document state.

- `id`
- `title`
- `status`
- `current_scene_json`
- `current_version`
- `effective_brand_kit_source`
- `effective_brand_kit_id`
- `effective_brand_kit_version`
- `brand_kit_json`
- `created_at`
- `updated_at`

### `operation_log`

Append-only ordered operation history per document.

- `document_id`
- `sequence`
- `operation_json`
- `actor_kind`
- `actor_id`
- `source`: `editor`, `agent`, `api`, or `system`
- `diagnostics_json`
- `created_at`

### `snapshots`

Immutable point-in-time scene copies.

- `snapshot_id`
- `document_id`
- `version`
- `scene_json`
- `reason`
- `created_at`

### `template_revisions`

Immutable finalized template records for future ABM personalization workflows.

- `template_revision_id`
- `document_id`
- `source_snapshot_id`
- `version`
- `scene_json`
- `export_profiles_json`
- `slot_summary_json`
- `brand_ref_json`
- `created_at`

### `asset_metadata`

Asset references only. This branch does not upload, transform, or generate bytes.

- `asset_id`
- `document_id`
- `kind`
- `filename`
- `source_uri`
- `mime_type`
- `width`
- `height`
- `dpi`
- `provenance_json`
- `licensing_json`
- `created_at`

### `document_diagnostics`

Stores latest structural, preflight, and finalization diagnostics for agent readback.

## Routes

- `POST /documents`: create a draft from an initial canonical scene or a minimal title/artifact metadata envelope; returns a document DTO summary.
- `GET /documents/{id}`: load current document metadata and scene.
- `PUT /documents/{id}/scene`: replace the current scene after Rust validation; returns a DTO summary and diagnostics views.
- `POST /documents/{id}/operations`: apply canonical operations through Rust checked apply, append operation history, update scene, optionally snapshot, and return an operation-application DTO.
- `GET /documents/{id}/operations`: read ordered operation history.
- `POST /documents/{id}/snapshots`: snapshot the current scene; returns a snapshot summary DTO.
- `GET /documents/{id}/snapshots`: list snapshot summaries.
- `GET /documents/{id}/snapshots/{snapshot_id}`: read a snapshot.
- `POST /documents/{id}/preflight`: select an effective brand kit, run canonical preflight, persist diagnostics and successful preflight scene changes, and return a preflight DTO.
- `POST /documents/{id}/finalize`: run core finalization, create an immutable template revision, and return a template-revision summary DTO.
- `GET /template-revisions/{id}`: read an immutable template revision.
- `POST /asset-metadata`: store asset metadata references.
- `GET /asset-metadata/{asset_id}`: read asset metadata.
- `GET /documents/{id}/summary`: return document/page/node/slot/export summaries for agent context.
- `GET /documents/{id}/slots`: return slot summaries and bound node ids.
- `GET /documents/{id}/geometry`: return computed geometry already stored on the current scene.
- `GET /documents/{id}/diagnostics`: return latest stored diagnostics with raw diagnostics plus DTO views.

## Effective Brand Kit Selection

`POST /documents/{id}/preflight` chooses the brand kit before calling `preflight_scene`:

1. Request-provided `brand_kit`.
2. Persisted document/client `brand_kit_json`.
3. Request-provided `generated_default_brand_kit`.
4. `platform_default_brand_kit()` from `lumen-core`.
5. `None` only when `strict_no_fallback` is true.

Preflight DTO responses report `brand_kit.source`: `request`, `document`, `generated_default`, `platform_default`, or `none`, with ID/version/name when available.

Tokenized scenes are not preflighted with `None` unless strict/no-fallback mode is requested, preserving the canonical `LUMP0300` repair diagnostic only for intentional strict flows.

## Agent Handoff

This API provides persistence support for an agent loop:

- read document summaries,
- read slots and bound nodes,
- query persisted computed geometry,
- apply structured operations,
- read diagnostics for repair,
- finalize immutable template revisions.

It deliberately does not implement `agents/design-loop-v0`. Future agent orchestration should use these routes as storage/tool surfaces while continuing to call core/export adapters for semantics and rendered previews.

## Verification

Expected checks:

```sh
cargo fmt --check
cargo test
cargo check --target wasm32-unknown-unknown
pytest apps/api/tests
```
