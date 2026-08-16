# Part II D2.5B — SQLite is DELETED from the design API

Branch `platform/design-integration`, on top of D2.5A (`09eff3a0`). The D2 gate's final clause:
every `Repository` domain lives on Postgres, so the SQLite substrate is dead weight — removed
completely, suite proven green without it.

## What died

- **`apps/api/migrations/`** — all 14 `*.sql` files, directory removed.
- **`lumen_api/database.py`** 3435 → 323 lines. Gone: the `Repository` class (96 methods),
  `connect`, `run_migrations`, `backfill_edit_envelopes`, `ensure_column`, `MIGRATIONS_DIR`,
  `WEB_UNDO_STACK_CAP`, `ASSET_ROW_COLUMNS`/`_PLACEHOLDERS`/`asset_row_values`,
  `encode`/`encode_optional`/`decode`/`decode_optional`, `scene_status`, `new_batch_id`, and all
  25 `*_from_row` decoders. Each was grep-verified to have zero callers outside the module.
- Tests whose SUBJECT no longer exists (deleted with a one-line D2.5B citation at the site):
  `test_ingestion_jobs.py`'s migration-idempotence / pre-007-upgrade / 007-rebuild trio,
  `test_ingestion_describe.py::test_migration_idempotent`,
  `test_custom_component_compiler.py::test_compiler_migration_replay_…`,
  `test_custom_components.py::test_migration_is_deterministic_…`, and
  `test_api.py::test_backfill_wraps_pre_envelope_operation_rows` (skipped since D1).

## What survived, and why

- **`database.py` is now the API's pure contract/helper module** (docstring says so): the five
  error classes (`NotFoundError`, `WebDocumentVersionConflict`, `CustomComponentArtifactConflict`,
  `CustomComponentSourceVersionConflict`, `CustomComponentReferenceError` — main.py registers HTTP
  handlers for them and the bridge translates `clue_design` errors *into* them), the
  custom-component contract (`canonical_custom_component_blob`, the artifact/source candidates,
  `custom_component_nodes`/`_references`/`_props_schema_issue`), and `utc_now`.
- **`import sqlite3` in three files, deliberately.** `sqlite3.IntegrityError` is the API's
  *constraint-violation exception type*: `DesignStoreBridge` raises it for Postgres
  `IntegrityError`/`DataError`/SQLSTATE-22, and main.py's five `except` sites + the
  `@app.exception_handler(sqlite3.Error)` + `custom_component_compiler`'s `except sqlite3.Error`
  turn it into the unchanged 409/500 DTOs. Commented at every import. Renaming it to a
  design-native error is a follow-up (~8 handler sites), not part of a deletion slice.

## Shape changes

- **`HybridRepository` no longer subclasses `Repository`** — standalone, `__init__(self,
  workspace_id=None, *, ensure_workspace=True)`; the SQLite connection param is gone. **Name kept
  on purpose** — the rename is D5's, so this slice churns no call site's spelling.
- Two inherited methods had to be re-homed: `validate_custom_component_reference_changes` moved
  VERBATIM into `HybridRepository` (it was never overridden because both its reads already
  dispatched to Postgres), and `require_asset_metadata` became a `raise NotFoundError` stub —
  its only writer (`POST /asset-metadata`) has been 410-Gone since D1 (O3), so the retired table
  can hold no row and `GET /asset-metadata/{id}` still 404s exactly as before. The other six
  un-overridden methods (`append_envelope`, `append_operations`, `next_{envelope,operation,
  run_event}_sequence`, `create_asset_metadata`) had zero callers and were deleted.
- `IngestionJobStore` / `DescriptionStore` dropped BOTH vestigial ctor args (`connection` and
  `now_iso`); `apply_descriptions` / `describe_kit_assets` / `_ApplyDescriptionsCallable` /
  `_maybe_describe` and the three manifest helpers (`workspace_asset_library_manifest`,
  `brand_kit_asset_manifest`, `reference_asset_manifest`) dropped the `connection` pass-through
  that only fed `DescriptionStore`.
- `create_app` lost the `migrate` flag and the `run_migrations` call. **`database_path` is kept
  solely as the asset-store root ANCHOR** (`<database dir>/asset-store` when
  `LUMEN_ASSET_STORE_ROOT` is unset) — documented as a vestige at the site, D4 re-homes it. No
  file is created at that path, so `create_app(tmp_path / "api.sqlite3")` keeps working unchanged
  across ~25 test fixtures.
- The two turn workers and the SSE poller lost their `try/finally: store.connection.close()`
  plumbing; the workers' `isinstance(repo, HybridRepository)` fork is dead and gone.
  `scripts/provision_font_library.py` was ported off `connect`/`run_migrations` too.

## Verification

- `ruff format`/`check` (`subsystems/design tests/design`) clean; `mypy` 586 files clean;
  `lint-imports` 25/25. The design API tree is ruff-EXCLUDED, so it was additionally swept with
  `ruff check --select F401,F811,F821,F841`: 17 findings remain, all confirmed pre-existing
  against `HEAD`.
- Fresh `clue_d25b`: `db-smoke` (up→base→head) exit 0, single head `cf7dd82cf683`;
  `tests/design/` **46 passed**.
- Offline platform suite: **2176 passed, 1493 skipped**, exit 0 — byte-identical to the D2.5A
  baseline.
- Full design-API suite on Postgres — see the run log; no file named `*.sqlite3` is created
  anywhere during it.
- **73 connection-carrying `HybridRepository(...)` / `Repository(...)` construction sites → 0.**
  (11 in `main.py`, 3 in `lumen_ingestion/pipeline.py`, 1 in `agent_custom_components.py`, 2 in
  `scripts/provision_font_library.py`, 56 across 20 test modules.)

## Residuals

- `HybridRepository` is a misnomer now (nothing is hybrid). Rename = D5, with the bridge.
- The `sqlite3.IntegrityError` parity type (above) — the last thread to cut.
- `apps/agent_runtime/evaluation/brand_fidelity.py::_kit_from_library` still opens
  `sqlite3.connect(settings.lumen_api_database_path)` and SELECTs the old `brand_kits` table.
  Out of D2.5B's `apps/api` scope; it has been functionally dead since D2.3 (kits moved to
  Postgres) and fails safe to `None` inside a bare `except Exception`. Port or delete it when the
  agent-runtime lane is touched.
- `DurableAgentCustomComponentRegistry.database_path` and the three
  `run_*_ingestion(database_path=…)` entrypoints keep an unused `database_path` so their call
  sites were untouched by the deletion; documented at each site, D5 removes them.
- The D2.5A residual stands unchanged: the module-level `main.py` helpers
  (`resolve_agent_turn_brand_kit`, `resolve_web_turn_brand_kit`, `resolve_account_assets`,
  `resolve_agent_turn_references`) run off the request thread and still default to the dev
  workspace.
- A stray untracked `apps/api/apps/api/lumen-api.sqlite3` (dated 2026-08-07, before this work)
  survives from an old dev run; it is git-ignored and nothing reads it.
