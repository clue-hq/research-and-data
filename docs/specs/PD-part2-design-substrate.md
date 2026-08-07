# PD — Part II: Design-Substrate Adoption (implementation contract)

**Status:** D0 EXECUTED 2026-08-07; **D1 EXECUTED 2026-08-07** (six migrations
`7bff99d2ad65 → 51db518c2a68 → c6cb64259ef1 → 47d2e1ca25f1 → 86a9ce389e6e → e79f192828b1`
chained off `c6d84aa84b79`, single head throughout; `clue_design.enums` + the `tests/design/`
acceptance suite; `make db-smoke` up→down→up green on a clean throwaway DB). Slice map and D0
rulings ADOPTED; **O1–O6 RATIFIED by the founder 2026-08-07** (with refinements — see §6). One
sub-decision remains open: **O6b** (the D2 interim public-serving rule), to be ratified at the
D2 discussion.
**Parent:** `docs/specs/design-integration-master-plan.md` §Part II (the authoritative plan).
This document is Part II's frozen implementation contract: slices, gates, the SQLite→Postgres
table map, mapping rules, and the decisions register. Where this doc and the master plan
conflict, the master plan's *intent* governs and this doc's *mechanics* govern.
**Inputs:** column-level inventory of the merged design tree's SQLite layer
(`subsystems/clue-design/apps/api/{migrations/*.sql, lumen_api/database.py}`) and of the
platform substrate seams (spine / alembic / storage / run_event / fleet / toolbelt), taken
2026-08-07.

---

## 1. Slice map

| Slice | Name | Plan item | Depends on | Gate |
|---|---|---|---|---|
| **D0** | Preflight & contract freeze | prereq | — | one alembic head verified; `clue_design` registered under every root gate; this doc ratified |
| **D1** | Tenancy + Postgres schema (`design_*` migrations) | II.1 | D0 | `make db-smoke` green (clean per-branch DB); enum-parity + immutability-trigger + tenancy-isolation tests green; single head maintained |
| **D2** | Persistence code port (DAL swap; SQLite deleted) | II.1 | D1 | design API suite green on Postgres; `MAX(seq)+1` races fixed; SQLite files + `migrations/*.sql` + `run_migrations` deleted; design apps re-enter uv workspace |
| **D3** | Concept joins: brand kits ↔ brand spine; design accounts ↔ `account_entity` | II.2 | D2 | joins live at the composition root; born-nullable FKs tightened per O1/O2 rulings |
| **D4** | Assets onto `clue_storage` (content-addressed fs/S3) | II.2 | D2 | asset bytes in platform storage via `record_artifact` (row-before-blob); API-local `asset-store/` retired |
| **D5** | Durable execution (fleet per the master plan; host re-examined per the O5 founder FYI — concurrent multi-session design runs are binding either way) | II.3 | D2 | design runs survive worker kill + restart (kill-and-resume test); daemon threads gone; LangGraph state in `AsyncPostgresSaver` |
| **D6** | Design writes through the toolbelt | II.4 | D5 | every design mutation behind a registered, precondition-checked, idempotency-keyed tool |
| **D7** | Design events onto `run_event` | II.5 | D5 | `design.*` topics on the durable stream; single-use stream tokens; SQLite-polling SSE deleted |
| **D8** | Part II closeout | gate | all | master-plan Part-II gate verified end to end; DSAR reach over design rows assessed; docs + `_memory` |

D3 ∥ D4 (independent after D2). D5 → D6 → D7 in order. The master-plan Part-II gate maps:
tenant-scoped rows (D1/D2), restart-safe runs (D5), tool-governed writes (D6), SQLite deleted
(D2), one SSE stream (D7).

## 2. D0 rulings (ratified)

- **R1 — Alembic base.** The tree has **exactly one head: `c6d84aa84b79`** (founder-confirmed;
  verified `uv run alembic heads`; the false 4-head reading counted Phase-C tips already joined
  by `fc1f3d22a167`). The first design migration sets `down_revision = "c6d84aa84b79"`. No
  merge revision is needed. All later design migrations chain linearly; `make db-smoke` on a
  clean per-branch throwaway DB gates every one. Context:
  `_memory/2026-08-07-alembic-single-head-c6d84aa84b79.md`.
- **R2 — Package topology.** All ported substrate code lives in the platform-native package
  **`subsystems/design/clue_design`** (dist `clue-design`), full conventions from birth (uv
  member via the `subsystems/*` glob; mypy strict; ruff; import-linter: independence + Rule S4
  purity "design substrate imports only core + db + config + obs + storage"; nothing imports it
  except the api root and — from D2 — the design apps). The merged three-language tree
  `subsystems/clue-design/` remains excluded from the workspace and is **not** this package.
- **R3 — Design-app workspace entry (mechanism, executed in D2).** `subsystems/clue-design/apps/api`
  (and `apps/agent_runtime` when D5 needs it) get minimal `pyproject.toml`s and re-enter the uv
  workspace **as explicit members by exact path** (the merge-day `exclude = ["subsystems/clue-design"]`
  guard stays; the Python apps re-enter individually, per the master plan's Step-2 wording).
  This is a narrow, sanctioned sliver of Part-I Step 2 pulled forward; the rest of Step 2
  (py_lumen_obs/py_lumen_config dedup, one deepagents pin, strict-gate burn-down, path-filtered
  CI) remains open Part-I work, not Part II's.

## 3. Tenancy laws (non-negotiable, applied to every `design_*` table)

1. `workspace_id text NOT NULL` + `<t>_workspace_fk FOREIGN KEY (workspace_id) REFERENCES
   workspace(workspace_id)` on **every** table, from birth.
2. Every parent gets `<t>_workspace_anchor UNIQUE (id, workspace_id)`; every child FK to a
   design parent is **composite** `(parent_id, workspace_id)` against that anchor — a
   cross-workspace reference is unrepresentable, not merely refused (the spine's
   `product`/`project` pattern).
3. Spine references use the same composite idiom: brand as `(brand_id, workspace_id) → brand`
   (anchor `brand_workspace_anchor`), accounts as `(account_entity_id, workspace_id) →
   account_entity(id, workspace_id)`. Never a bare cross-spine id column.
4. Named constraints/indexes (`<table>_<what>`), `COMMENT ON TABLE`, hand-written reversible
   `upgrade()`/`downgrade()`, hash revision ids, single head, `make db-smoke`.

## 4. Type & idiom mapping rules (SQLite → Postgres)

| SQLite idiom | Postgres rule |
|---|---|
| TEXT ISO-8601 timestamps | `timestamptz NOT NULL DEFAULT now()` (nullable only where the source column is genuinely nullable: `web_publishes.created_at/updated_at` — normalize to NOT NULL, dev data resets) |
| INTEGER 0/1 booleans | `boolean NOT NULL DEFAULT false` (`product_ready`, `layout_managed_editing`, `is_template`, `publish`) |
| `*_json` TEXT columns | `jsonb` + `CHECK (jsonb_typeof(col) = 'object' / 'array')` per payload shape |
| TEXT prefixed ids (`doc_…`, `snap_…`, `batch_…`, content-hash `ccart_<sha>`/`ccsrc_<sha>`/`webpub_<sha>`) | **kept verbatim** as `text` PKs — matches the spine's `ws_`/`brd_` style; content-hash ids keep their shape CHECKs (`~ '^ccart_[0-9a-f]{64}$'` etc.) |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `bigint GENERATED ALWAYS AS IDENTITY` |
| `MAX(seq)+1` per-parent sequences (`operation_log.sequence`, `edit_envelopes.seq`, `run_events.seq`) | allocate under `SELECT … FOR UPDATE` on the parent row (`design_document` / `design_agent_run`) — race-free under concurrent writers, preserves per-parent monotonic contract |
| free-text `status`/`kind` columns with SQLite CHECKs | package-local `StrEnum`s in `clue_design` mirrored as PG enums, with the standard pg_enum parity tests (fleet precedent — **not** `core.enums`) |
| 5 SQLite immutability triggers | PG trigger equivalents (claim append-only trigger precedent): `design_custom_component_artifact` (no UPDATE), `design_custom_component_source_revision` (no UPDATE), `design_custom_component_compilation` (no UPDATE), `design_web_publish_revision` (no UPDATE, no DELETE) |
| `007`'s drop-and-rebuild-`brand_kits`-every-boot; `backfill_edit_envelopes()`; `brand_kits_new` | **not ported** — versioned migrations only; dev data resets so there is nothing to backfill |
| deliberately-missing FKs (`agent_runs.document_id`, `web_accounts.logo_asset_id`, `binding_sets/instances → template_revisions`, `asset_descriptions.asset_id`, `web_publishes.document_id`, …) | become **real FKs** with soft semantics preserved (nullable + `ON DELETE SET NULL` where a dangling reference was tolerated by design; composite with `workspace_id` throughout) |

Dev-only SQLite data is **not migrated** (master plan): schema + code port; dev data resets.

## 5. Table map (22 SQLite tables → `design_*`)

Singular table names, platform-style. "WS" = tenancy laws §3 applied (always). Migration
grouping for D1: **(a)** documents+history, **(b)** brand, **(c)** assets, **(d)**
personalization, **(e)** web+components, **(f)** runs/events — six reversible migrations
chained off `c6d84aa84b79`, one head throughout.

| # | SQLite | Postgres | Key structure & notes |
|---|---|---|---|
| 1 | `documents` | `design_document` | PK `id text` (`doc_…`); `title`, `status` (enum), `doc_kind` enum (`scene`\|`web`), `current_scene_json jsonb` (full scene/WebDoc — source of truth, rewritten per write), `current_version int NOT NULL` (CAS counter — **extended to scene writes in D2**, closing the ported lost-update gap), effective-brand columns (`effective_brand_kit_source` enum, `_id`, `_version`, `effective_brand_mode_json jsonb`, denormalized `brand_kit_json jsonb`), `undo_stack_json`/`redo_stack_json jsonb` (batch-id arrays, cap 50), `agent_instructions text`, `layout_managed_editing bool`, `is_template bool`, `template_document_id` (composite self-FK, SET NULL), `template_doc_version int`, `account_id` → O1 (composite FK to `design_account`, SET NULL), timestamps. Anchor + WS. |
| 2 | `operation_log` | `design_operation_log` | PK `(document_id, sequence)`; composite FK `(document_id, workspace_id)` CASCADE; `operation_json jsonb`, `actor_kind`, `actor_id`, `source` enum (`editor`\|`agent`\|`api`\|`system`), `diagnostics_json jsonb`, `batch_id text` (→ `design_edit_envelope.batch_id`, real FK now), `created_at`. Sequence via parent-row lock (§4). Append-only discipline documented; no compaction (deferred, see §8). |
| 3 | `edit_envelopes` | `design_edit_envelope` | PK `id bigint identity`; `batch_id text UNIQUE`; composite doc FK CASCADE; `seq int` UNIQUE `(document_id, seq)` via parent-row lock; `envelope_version int` (0 = legacy backfill — dead in PG; keep for shape parity), `base_revision int`, actor/source/intent/`checkpoint_label`, `touched_targets_json`/`operations_json`/`inverse_operations_json jsonb` (inverse batch = undo substrate), `lineage_json jsonb`, `reverts_batch_id`/`reapplies_batch_id`, `created_at`. Index `(document_id, seq DESC)`. |
| 4 | `snapshots` | `design_snapshot` | PK `snapshot_id text` (`snap_…`); composite doc FK CASCADE; `version int`, `scene_json jsonb` (full copy), `reason` enum-ish text, `created_at`. |
| 5 | `template_revisions` | `design_template_revision` | PK `template_revision_id text` (`tmpl_…`); composite doc FK CASCADE; `source_snapshot_id` FK SET NULL; `version int`, `scene_json jsonb` (frozen), `export_profiles_json`/`slot_summary_json jsonb`, `brand_ref_json jsonb` (`{id, version}`), `created_at`. Anchor (children: binding sets, instances, batches, repairs). |
| 6 | `document_diagnostics` | `design_document_diagnostic` | PK `id bigint identity`; composite doc FK CASCADE; `kind`, `diagnostics_json jsonb`, `created_at`. Append-only, read = latest per kind; index `(document_id, id DESC)`. |
| 7 | `brand_kits` | `design_brand_kit` | PK `(brand_kit_id, version)`; `name`, `approval_status` enum (`draft`\|`generated_unreviewed`\|`approved`\|`deprecated`), `product_ready bool`, `source` enum (9 values incl. `website`\|`pdf`\|`asset_upload`), `brand_kit_json jsonb` (full kit: tokens/modes/assets-by-reference/constraints — bytes live in the asset registry, never here), `brand_summary_json`/`diagnostics_json jsonb`, timestamps. **O2:** born-nullable composite `(brand_id, workspace_id) → brand` via `brand_workspace_anchor`. Anchor `(brand_kit_id, version, workspace_id)`. |
| 8 | `brand_compatibility_reports` | `design_brand_compat_report` | PK `report_id text`; two composite FKs to `design_brand_kit` (from/to, each `(id, version, workspace_id)`) CASCADE; `report_json`/`diagnostics_json jsonb`; `created_at`. |
| 9 | `assets` | `design_asset` | PK `asset_id text` (`asset_…`/`asset_qr_…`/`asset_gen_…`); `label`, `kind`, `status` enum, `mime_type`, `digest_algorithm`+`digest_value` (sha256 shape CHECK), `byte_length`, `filename`, `tags_json jsonb`, `record_json jsonb` (canonical Rust `AssetRecord`; other columns are projections of it), timestamps. Indexes `(workspace_id, digest_value)`, `(workspace_id, kind, status)`. Bytes: API-local store until **D4**, then platform `artifact`/`clue_storage` (`{ws}/{sha}` keys; `record_json.media.location` re-pointed). |
| 10 | `asset_descriptions` | `design_asset_description` | PK `asset_id` = composite **real** FK to `design_asset` CASCADE (1:1); `title`/`description`/`usage`, `tags_json jsonb`, `origin` enum (`ai`\|`human`), `model`, timestamps. Human-wins conditional upsert preserved in DAL. |
| 11 | `asset_metadata` | **not ported** (O3) | Legacy parallel of the real registry; single write endpoint, no load-bearing readers. Endpoint → 410 in D2. |
| 12 | `binding_sets` | `design_binding_set` | PK `binding_set_id text` (`bind_…`); composite FK → `design_template_revision` (now real, CASCADE); `binding_json jsonb`, `status` enum, `diagnostics_json jsonb`, timestamps. Index on revision. |
| 13 | `instances` | `design_instance` | PK `instance_id text` (deterministic `inst_<rev>_<bind>` — kept; uniqueness now also DB-enforced); composite FKs → revision + binding set + batch (SET NULL); `status`/`fit_status` enums, `derived_scene_json jsonb` (re-derivable cache), `diagnostics_json`/`audit_json`/`fit_report_json`/`artifacts_json`/`generated_assets_json jsonb`, timestamps. |
| 14 | `instance_batches` | `design_instance_batch` | PK `batch_id text`; composite FK → revision; `status` enum, `binding_set_ids_json`/`export_formats_json jsonb`, `chunk_size`/`cursor int` (resume seam — superseded by fleet in D5 but ported as-is), `counts_json`/`manifest_json`/`diagnostics_json jsonb`, `export_profile_json jsonb NULL`, timestamps. |
| 15 | `repair_queue` | `design_repair_request` | PK `repair_id text` (deterministic `rep_…` — kept); composite FKs → revision, binding set, instance (SET NULL); `slot_key`, `node_id`, `reason`, `status` enum, timestamps. |
| 16 | `agent_runs` | `design_agent_run` | **Temporary shape** (reshaped in D5 onto the fleet job pattern: `lease_generation`, `checkpoint_thread_id`, subject columns — the `entity_research_job` precedent). D1/D2 port: PK `run_id text` (`run_…`); `status` enum (`running`\|`succeeded`\|`failed`); `document_id` composite FK SET NULL (real FK now); `result_json jsonb`; timestamps. |
| 17 | `run_events` | `design_run_event` | **Explicitly temporary — dies in D7** (replaced by `design.*` topics on the platform `run_event` stream; subject widening follows the C5.1 precedent: nullable design-subject FK column + partial index, NOT a repurposed `run_id`). D1/D2 port: PK `id bigint identity`; composite FK → `design_agent_run` CASCADE; `seq int` UNIQUE `(run_id, seq)` via parent-row lock; `event_type text` (free vocabulary preserved), `data_json jsonb`, `created_at`. |
| 18 | `ingestion_jobs` | `design_ingestion_job` | PK `job_id text` (`ingest_…`); `kind` enum (`website`\|`pdf`\|`asset_upload`), `status` enum (`queued`\|`running`\|`succeeded`\|`failed`), `stage`, `progress real` (0–1 CHECK), `request_json jsonb` (staged-file `tmp_path`s move to platform storage keys in D4), `evidence_json jsonb`, result pointer `(brand_kit_id, brand_kit_version)` composite FK SET NULL (real now), `error_json jsonb`, timestamps. Index `(workspace_id, status, created_at)`. Execution → fleet in D5 (fixes the no-orphan-sweep restart hole). |
| 19 | `web_publishes` | `design_web_publish` | **PK `(workspace_id, slug)` — O6 RATIFIED** (slugs workspace-local; global URL uniqueness is a serving-layer concern; interim `/p/{slug}` ambiguity rule = O6b, ratify at D2). `document_id` composite FK; `doc_version int`, `html`/`previous_html text` (one-step rollback buffer), `previous_doc_version`, `runtime_version`, `status` enum (`active`\|`unpublished`), `publish_id`/`previous_publish_id` FKs → `design_web_publish_revision` (real now), timestamps NOT NULL. Index `(workspace_id, document_id, updated_at DESC)` (fixes the unindexed lookup). |
| 20 | `web_publish_revisions` | `design_web_publish_revision` | PK `publish_id text` (`webpub_<package_digest>` — content-hash, shape CHECK); `slug`, composite doc FK; `doc_version`, `html text`, `html_digest`, `manifest_json jsonb`, `manifest_digest`, `package_digest`, `runtime_version`, `created_at`. Immutable: no-UPDATE **and** no-DELETE triggers. Indexes `(workspace_id, slug, created_at DESC)`, `(workspace_id, document_id, created_at DESC)`. |
| 21 | `web_accounts` | `design_account` | PK `account_id text` (`acc_…`); `name`, `domain`, `logo_asset_id` composite FK → `design_asset` SET NULL (real now); `data_json jsonb` (flat string map → `account.<key>` substitution vars), `notes text` (agent-context only — **never** a substitution value; documented in `COMMENT`), timestamps. **O1:** born-nullable composite FK `(account_entity_id, workspace_id) → account_entity(id, workspace_id)`; joined + tightened in D3. Anchor. |
| 22 | `web_batches` | `design_web_batch` | PK `batch_id text` (`wbatch_…`); composite FK template doc; `template_doc_version` pin, `status` enum, `account_ids_json jsonb`, `publish bool`, `slug_base`, `cursor int` (D5 supersedes), `manifest_json jsonb`, timestamps. |
| 23 | `custom_components` | `design_custom_component` | PK `(account_id, slug)` → becomes `(workspace_id, account_id, slug)`; composite FK → `design_account` CASCADE; `source_version int`, `current_source_revision_id` FK; timestamps. |
| 24 | `custom_component_artifacts` | `design_custom_component_artifact` | PK `artifact_id text` (`ccart_<sha256>`, shape CHECK); composite FK → `design_custom_component`; source/bundle/css/first-frame digest+opaque-ref+byte-length column groups (opaque refs re-pointed to platform storage in D4); `manifest_json`/`provenance_json jsonb`; `created_at`. **Immutable (no-UPDATE trigger).** Digest indexes ws-scoped. |
| 25 | `custom_component_source_revisions` | `design_custom_component_source_revision` | PK `revision_id text` (`ccsrc_<sha>` content-hash, shape CHECK); composite FK → component; `source_version int >0`, UNIQUE `(workspace_id, account_id, slug, source_version)`; entry/snapshot digest columns; `files_manifest_json`/`provenance_json jsonb`; `created_at`. **Immutable.** |
| 26 | `custom_component_compilations` | `design_custom_component_compilation` | PK `compilation_id text` (`cccmp_…`); FK → source revision; `status` enum (`succeeded`\|`failed`\|`transient_error`), compiler protocol/version columns, `diagnostics_json jsonb`, `artifact_id` FK SET NULL (real now); `created_at`. **Immutable.** |

(26 rows because `asset_metadata` is dropped and rows 23–26 unpack the 4 custom-component
tables; the transient `brand_kits_new` does not exist at rest.)

## 6. Decisions register — O1–O6 RATIFIED (founder, 2026-08-07)

- **O1 — RATIFIED as recommended.** `design_account.workspace_id NOT NULL`;
  `account_entity_id NULLABLE`; when present the DB enforces the composite FK
  `(account_entity_id, workspace_id) → account_entity(id, workspace_id)`. D3 wires
  resolve-or-create at the api composition root and decides NOT NULL promotion.
- **O2 — RATIFIED as recommended, and the D3 promotion question is decided NOW:
  `design_brand_kit` becomes THE platform versioned brand-kit payload.** Born-nullable
  composite `(brand_id, workspace_id) → brand` FK in D1; D3 completes the join. Product
  context recorded for D3/Part IV: each client workspace gets a complete knowledge base plus a
  **brand studio** surface per brand — a brand-design-kit section carrying the brand design
  system tokens *and* the brand's asset store. `design_brand_kit` (+ `design_asset`) is the
  durable payload behind that surface, and the version-pinned kit Part III's delegation bundle
  references. (Founder's Figma screenshots of the brand-studio design exist but were not
  captured into the repo yet — attach at D3.)
- **O3 — RATIFIED with clarified wording: drop ONLY the legacy `asset_metadata` table.**
  `asset_descriptions` is expressly **preserved and ported** as `design_asset_description` with
  its full behavior: AI generation, human-wins conditional upsert, model attribution, caching,
  and description stamping into versioned brand kits (§5 row 10; the D2 DAL port carries the
  behavior, not just the rows).
- **O4 — RATIFIED as recommended.** Interim tenancy source = the platform's `X-Workspace-Id`
  header-resolver seam (401 when absent) from the first Postgres write; editor dev harness
  sends a configured dev workspace id; real authn is Part IV.
- **O5 — RATIFIED as recommended, with the atomicity rule made binding:** the D2 bridge is
  `asyncio.run(dal_coroutine(...))` per operation, each bridge call obtaining a connection
  bound to *its own* loop (never a pool/connection from another loop). **Any operation that
  needs atomicity — e.g. lock-parent-and-allocate-next-sequence — must be ONE DAL coroutine in
  ONE transaction, never composed from several `asyncio.run` calls.** Known costs accepted
  (loop/connection churn, awkward cancellation, restart still kills in-flight work); both the
  daemon threads and the bridge are deleted at D5.
  **Founder FYI recorded for D5 planning:** the fleet may NOT end up hosting the design
  deepagent (current leaning, not committed). The binding requirements regardless of host:
  design runs survive restarts, and **multiple concurrent design-deepagent sessions per user**
  (start a second design session while the first still works) must be possible. D5's
  discussion re-opens the host question against those requirements before implementation.
- **O6 — RATIFIED: publish slugs are workspace-local.** `design_web_publish` PK =
  `(workspace_id, slug)`; e.g. `(ws_alpha, "acme-q3")` and `(ws_beta, "acme-q3")` coexist.
  Slug namespaces stay tenant-local (no cross-tenant squatting; "slug taken" leaks nothing).
  Global URL uniqueness is a **serving-layer concern** (Part IV candidates: tenant subdomain,
  `/w/{workspace}/{slug}` paths, or a globally-allocated public alias).
  - **O6b — RATIFIED (founder, 2026-08-07): option (a).** D2 replaces the ambiguous
    `/p/{slug}` route with the temporary workspace-scoped `/w/{workspace_id}/p/{slug}` —
    dev-only traffic, no new table, deliberately disposable. **Part IV owns the real public
    routing and DELETES this interim route when it ships** — recorded as Part-IV item 5 (and
    in its gate) in `docs/specs/design-integration-master-plan.md` so it cannot be forgotten.

## 7. D1 / D2 acceptance criteria

**D1:** six reversible migrations chained off `c6d84aa84b79` (single head at every commit);
tenancy laws §3 on every table; enums + parity tests; immutability triggers + tests proving
UPDATE/DELETE rejection; a tenancy-isolation test proving a cross-workspace composite FK insert
fails with `IntegrityError`; `make db-smoke` green on a clean per-branch DB; **no code-port in
D1** (`clue_design` gains only enums + row-model types).

**D2:** the `Repository`/`IngestionJobStore`/`DescriptionStore` surface ported to per-domain
async DAL modules in `clue_design` behind `ConnFactory`; design API switched (R3 workspace
entry executed); O4 header seam live; scene-write CAS added; seq allocation per §4; SQLite
artifacts deleted from `subsystems/clue-design/apps/api`; design API tests green against a
throwaway Postgres DB; `make check` green.

## 8. Deferred / explicitly out of Part-II-D1/D2 scope

- **The append-only, full-history discipline is a PRESERVED PRINCIPLE, not a porting
  accident** (founder ruling 2026-08-07): the operation log, edit envelopes, diagnostics,
  snapshots, and publish revisions stay append-only with no history truncation — undo/redo
  writes new *forward* envelopes (`reverts_batch_id`/`reapplies_batch_id`), never rewrites or
  deletes history, exactly as today. What D8 may revisit is narrowly scoped: DSAR/erasure reach
  over design rows (the platform's tombstone discipline, which is itself append-only) and
  operational storage concerns (partitioning, archival tiers) — **never** silent compaction
  that destroys design history.
- The `run_event` subject widening (D7) and fleet job reshape (D5) — schemas noted temporary in
  §5 rows 16–17.
- Full Part-I Step 2 (lib dedup, deepagents pin, strict-gate burn-down, path-filtered CI).
- Pre-existing repo-wide `ruff format` drift (23 M8D-era files fail `make lint` at
  `origin/main` — predates Part II; owner ruling pending, tracked in
  `_memory/2026-08-07-part2-d0-preflight.md`).
