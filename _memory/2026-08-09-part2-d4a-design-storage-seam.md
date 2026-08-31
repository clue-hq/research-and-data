# Part II D4 — Round A: the design storage seam + pure-Python byte trees on `clue_storage`

Branch `platform/design-integration`. Contract: `docs/specs/PD-part2-design-substrate.md` (D4).
Scope of this round: the two **pure-Python** byte trees only — custom-component blobs and
publish delivery assets. The MAIN asset store (`sha256/{ab}/{digest}` under `asset_store_root`:
fonts, images, ingestion staging, engine artifacts) is **Round B** and is untouched.

## What landed

- **`subsystems/design/clue_design/storage.py`** (new) — the design byte seam.
  `design_storage_key` / `register_design_bytes` / `read_design_blob` / `read_design_bytes` /
  `design_bytes_exist`, plus `SOURCE_KEY_CUSTOM_COMPONENT` / `SOURCE_KEY_PUBLISH_ASSET`.
  Row-before-blob via `clue_storage.artifacts.record_artifact`, then `storage.put` iff absent.
  Reads are fail-closed: absent / foreign-workspace / erased / bytes-missing all raise the same
  `DesignNotFoundError`.
- **`lumen_api.design_store.DesignBlobStore`** — the sync facade, the byte-store sibling of
  `HybridRepository`, on the SAME O5 bridge. One method = one bridged coroutine (row + blob in
  one transaction). Carries its workspace; `ensure_workspace=False` for the anonymous route.
- **`create_app(..., storage=None)`** → `app.state.storage` (default `storage_from_settings()`).
  `app.state.custom_component_store_root` and the `custom-components/` tree are **deleted**.
- Custom components + publish assets rewritten onto the seam; the publish `{digest}.meta.json`
  sidecar is deleted (media type lives on the `artifact` row).

## Two findings that changed the plan (both required, both deliberate)

1. **The `artifact_key_encodes_scope` CHECK forbade the ruled key shape.** B2's migration
   `d0c2e361f7d4` pinned `storage_key = COALESCE(workspace_id,'public') || '/' || content_sha256`
   — so R-D4-2's `{ws}/design/{sha}` was **unrepresentable** and every design write would have
   raised a CheckViolation. New migration **`13cd5078d697`** widens the CHECK to admit exactly
   the two shapes (bare evidence + design). The invariant is unchanged (the key still encodes its
   scope and its content hash); the downgrade restores the bare-only CHECK and therefore fails
   loud on a DB that already holds design rows — correct, and only relevant on a populated DB
   (the `up→down→up` gate runs on a clean one).
2. **One namespace means component blobs and publish assets can be the SAME row.** R-D4-3 puts
   both in `{ws}/design/{sha}`, and a compiled `first_frame` is byte-identical to the publish
   delivery asset minted from it. `record_artifact`'s `ON CONFLICT` preserves the FIRST writer's
   `media_type`, so storing component members as a blanket `application/octet-stream` made
   `/p-assets/{digest}.html` 404 (the read checks extension↔media-type). Fix: component members
   are stored with their TRUE media types
   (`CUSTOM_COMPONENT_MEMBER_MEDIA_TYPES` in `custom_components.py` — the same table the member
   route serves from), so the two writers agree instead of racing.
   **Residual (documented, not fixed):** two members of one artifact with identical bytes and
   different types (e.g. an empty `css` and an empty `first_frame`) would still collide on one
   row and one media type. Implausible in practice (a first frame is rendered HTML).

## Other deliberate deviations from the round brief

- `persist_publish_assets(blobs, assets, records)` / `resolve_publish_asset(blobs, digest, ext)`
  take the handle only, not `(seam, workspace_id)` — `DesignBlobStore` already carries the
  workspace, and duplicating it invites the two disagreeing.
- Added `read_design_blob` (→ `(media_type, bytes)`) alongside the brief's `read_design_bytes`,
  so the publish read is ONE bridged transaction rather than two (O5).
- The ext↔media-type table is `{js, css, html}` — the brief said "js/css/html/fonts/images", but
  the sidecar writer it told me to read only ever accepted those three, and publish assets only
  ever come from `_DeliveryAssetCatalog`.
- `database.canonical_custom_component_blob` hardcoded `opaque_ref == sha256/{ab}/{digest}`;
  extracted `custom_component_opaque_ref_is_canonical`, which accepts the D4 storage key AND the
  legacy path (immutable registry rows can never be rewritten). Readers resolve by DIGEST, never
  by parsing the ref.
- `DurableAgentCustomComponentRegistry._repository()` now takes its workspace from the injected
  blob-store handle instead of `default_workspace_id()`. This **fixes** part of the D2.5A
  residual (the agent turn used to read the dev tenant's registry rows when the request named a
  different tenant); the row store and the byte store now cannot name different tenants.

## Gates (all green)

`ruff format --check` + `ruff check` + `mypy` (588 files) + `lint-imports` (25 kept, 0 broken —
no contract edit needed; Rule S4 already permits `clue_design → clue_storage`).
`pytest tests/design/` = 59 passed (4 new in `tests/design/test_storage_seam.py`).
Targeted design-API set (6 files) = 40 passed. Offline platform suite = **2177 passed**,
1505 skipped (baseline 2176 + the one new key-shape test that needs no DB).
Adjacent design-API suites re-run green as insurance: workspace-seam, asset-store-serving,
web-batches, export-parity, phase-g-conformance, and the six `test_web_*` files.

**Trap for the next agent:** the DB-gated platform suite must run against a **pristine**
database. Running it twice against the same throwaway DB produces ~33 failures (migration
up/down + discovery-scoring/waterfall/fleet state) purely from committed rows accumulating —
verified pre-existing and unrelated: all pass on a fresh DB, all reappear on a re-run.

## Round B (still open)

- The MAIN asset store tree: fonts (`_gather_fonts`), the `build_export_bundle` image copy,
  `font_library.library_font_spec`, `image_cache`, ingestion staging (`ingest_tmp`), and the
  engine `store_root` handed to the Rust helper (`core.py`). `store_root: str` is still threaded
  through `build_export_bundle` / `build_publish_package` for exactly those.
- `settings.effective_asset_store_root` / `app.state.asset_store_root` / the vestigial
  `database_path` anchor all die with it.
- `design_asset.record_json.media.location` re-pointing (PD §5 row 9) is Round B's, not done.
- The `/asset-store/{digest}` public route is still API-local and O4-exempt.
