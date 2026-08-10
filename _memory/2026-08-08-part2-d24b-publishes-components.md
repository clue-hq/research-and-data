# Part II D2.4B — web publishes + custom-component registry on Postgres (+ O6b public route)

Branch `platform/design-integration`. Builds on the uncommitted D2.4A work (personalization +
accounts). The LAST D2.4 port.

## What landed

**New DAL modules** (`subsystems/design/clue_design/`):
- `publishes.py` — `design_web_publish` + `design_web_publish_revision`.
  `register_web_publish_revision` / `require_web_publish_revision` / `get_web_publish` /
  `require_web_publish` / `get_web_publish_for_document` / `upsert_web_publish` /
  `set_web_publish_status` / `rollback_web_publish`.
- `components.py` — `design_custom_component` + `_source_revision` / `_artifact` /
  `_compilation`. 16 functions (register artifact, CAS source revision, record compilation,
  getters/lists/requires, current-revision read).

Both are workspace-scoped, fail-closed, INSERT-only on the immutable tables, and reproduce the
SQLite `*_from_row` shapes with ISO timestamps.

**Decisions taken**
- `register_web_publish_revision` DERIVES `publish_id = 'webpub_' || package_digest` instead of
  trusting the caller's (the CHECK is structural now). Both call sites already minted exactly
  that.
- Contract validation (blob canonicalization, slug shape, `ccart_`/`ccsrc_` id shapes) stays in
  `lumen_api`, extracted into two new module functions
  `database.custom_component_artifact_candidate` / `custom_component_source_candidate` that BOTH
  the SQLite `Repository` and the `HybridRepository` override call. The DAL takes an
  already-canonical candidate — no duplication of the P6 contract inside `clue_design`.
- Two new `clue_design.errors` types (`DesignArtifactConflictError`,
  `DesignSourceVersionConflictError`) translated in `DesignStoreBridge._run` back into
  `CustomComponentArtifactConflict` / `CustomComponentSourceVersionConflict`, so main.py's
  registered 409 handlers are untouched.
- `validate_custom_component_reference_changes` is NOT overridden — porting its two reads
  (`get_web_account`, `get_custom_component_artifact`) makes Python dispatch run the inherited
  walk against Postgres. **This closes the last cross-domain seam**; `design_store.py`'s module
  docstring now says so.

**O6b interim public route (ratified option (a))**
- `/p/{slug}`, `/p/{slug}/manifest.json`, `/p-assets/{asset_name}` → `/w/{workspace_id}/p/...`.
  The bare routes are DELETED (404), not kept as a fallback, with a route-level comment citing
  O6b + Part-IV item 5.
- New `main.public_repository` dependency: workspace from the PATH, and
  `HybridRepository(..., ensure_workspace=False)` so an anonymous GET never creates a workspace
  row (an unknown tenant 404s through the fail-closed reads).
- URL builders: `main.public_publish_path` (the ONE builder; publish response, publish-state
  response, batch manifest rows) and `web_export.build_publish_package(..., workspace_id=...)`
  which prefixes canonical / og:url / manifest link / `p-assets` URLs. `/asset-store` URLs stay
  unprefixed (not part of the publish surface).
- OUT OF SCOPE (Part IV): `apps/editor/src/components/web/WebPublishDialog.tsx:121` still mints
  `/p/{slug}/manifest.json` client-side — that one link 404s until Part IV. The "view page" link
  uses the API-returned `url`, which is correct.

## Two defects found and fixed during the port

1. **`DesignStoreBridge` could not run two concurrent calls.** It used `db_lifespan()`, which
   registers a PROCESS-GLOBAL engine and raises "db_lifespan is already active" on re-entry —
   so the component source-CAS race test (two threads, on purpose) failed once that write moved
   onto the bridge. Fixed: the bridge now uses `clue_db.create_engine()` + `dispose()` (a
   private engine per call). Nothing under the bridge reads the global; O5 already demanded one
   engine/connection/transaction per call bound to THIS loop.
2. **`design_custom_component_compilation.artifact_id ON DELETE SET NULL` is unreachable** — the
   SET NULL is itself an UPDATE, which the table's own no-UPDATE immutability trigger rejects.
   Verified harmless in production: there is NO artifact-delete path (the registry is
   INSERT-only), and the account CASCADE deletes compilations outright (probed against the DB:
   `DELETE FROM design_account` with a compilation present succeeds). Only test code that
   simulates a purge is affected — those tests now delete the citing compilation rows first,
   with the reason recorded at the site. **Follow-up (cosmetic, D8-ish):** either drop the dead
   `ON DELETE SET NULL (artifact_id)` clause or teach the trigger to permit exactly that
   FK-driven null-out.

## Collateral test adaptations (design suite)

- `tests/conftest.py`: `_isolated_design_workspace` now RETURNS the id; new `workspace_id`
  fixture for the path-scoped public routes.
- `test_web_export.py`, `test_web_batches.py`, `test_custom_component_publish.py`: publish/asset
  URLs re-homed under `/w/{workspace_id}/...`.
- Immutability checks that poked raw SQLite (`custom_component_artifacts`,
  `custom_component_source_revisions`, `custom_component_compilations`,
  `web_publish_revisions`) now assert the **Postgres** triggers via `repository._bridge._run`
  and `sqlalchemy.exc.DBAPIError` — same intent, real enforcement point.
  (`test_custom_components.py::test_..._migrations` still counts the legacy SQLite tables at 0;
  that assertion is about `run_migrations`, unchanged.)

## New tests

`tests/design/test_publishes_components_dal_db.py` (6): republish current→previous shift +
rollback swapping BOTH html and publish_id pointers; the `not_found` / `no_previous` markers;
the same slug in two workspaces; append-only revisions (UPDATE and DELETE → `DBAPIError`) plus
the content-address CHECK; component register → source revision (CAS 0→1→2) → compilation with
the identity pointer advance and a stale-CAS conflict; artifact workspace/account scoping and
the account CASCADE.

## Verification

- ruff format/check (`subsystems/design tests/design`) clean; `mypy` 585 files clean;
  `lint-imports` 25/25.
- `make db-smoke` on a clean `clue_d24b`: exit 0. `tests/design/`: 40 passed.
- Full design-API suite (`subsystems/clue-design/apps/api/tests`) on Postgres: see the session
  report — 10 pre-adaptation failures, all resolved.
- Offline platform suite: 2176 passed, 1487 skipped.
