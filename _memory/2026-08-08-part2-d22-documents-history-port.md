# 2026-08-08 — Part II slice D2.2 executed: documents + history on Postgres

## What landed (branch `platform/design-integration`)
- **DAL** (`subsystems/design/clue_design/`): `_codec.py` (jsonb/ISO codecs), `documents.py`
  (create/get/replace/update_document_state/update_web_document/templates/account-stamp/
  reference-count — every write path row-locked `FOR UPDATE`; **scene-write CAS added**, the
  ported lost-update gap closed), `history.py` (append-only envelopes/op-log via the D2.1
  allocators; real revert/reapply lineage), `snapshots.py`, `diagnostics.py`.
- **The store switch** (`subsystems/clue-design/apps/api/lumen_api/design_store.py`):
  `HybridRepository(Repository)` overrides ONLY the document domain onto the O5 bridge
  (one `asyncio.run` = one engine/connection/transaction; disposable, dies at D5); everything
  else stays SQLite until D2.3–D2.5. Cross-domain seams sequenced at the overrides:
  component-reference validation (SQLite) BEFORE the PG write; scene-asset registry promotion
  (SQLite) AFTER it. Plus PG-feed overrides for the two SQLite readers that joined `documents`:
  `list_running_runs` (doc_kind enrichment) and `list_custom_component_usages` (walks the new
  `list_web_documents_for_account` DAL feed). Workspace: `X-Workspace-Id` header else
  `LUMEN_DEV_WORKSPACE_ID` default (strict 401 at D2.5); dev workspace row lazily ensured.
  `main.py`: repository dependency + both turn workers + `_fail_orphaned_runs` build the
  hybrid; **legacy `POST /asset-metadata` now 410s** (`asset_metadata.gone`, per O3).
- **Migration `7a9881f9717a`** (head): (1) `design_document` PK → `(id, workspace_id)`; op-log
  PK and envelope doc-seq unique gain `workspace_id` (allocators filter accordingly);
  (2) **workspace-locality extended — NEEDS FOUNDER RATIFICATION** — PKs of
  `design_template_revision`, `design_account`, `design_brand_kit`, `design_web_publish_revision`,
  `design_custom_component_source_revision`, `design_custom_component_artifact` now include
  `workspace_id` (client-supplied ids can be squatted; identical content hashes collide across
  tenants; server-minted-uuid namespaces stay global); child FKs were already on the anchors —
  safe re-keys; (3) `design_document_account_fk` DROPPED until D2.4 re-adds it with the account
  port; (4) `design_effective_brand_source` gains `platform_default` (ADD VALUE — the D1
  inventory under-read the closed set; member appended last, parity holds).
- **Design test-suite adaptation:** per-test unique workspaces (autouse env fixture in their
  conftest); direct `Repository(...)` seeding → `HybridRepository` (18 files); backfill test
  skip-with-reason (machinery not ported per contract §4); asset-metadata tests now assert
  410; jsonb-order fix (containers selected BY ID — **jsonb does not preserve object key
  order**, the C8§6c hazard; never select nodes by dict position); the publish corruption
  simulation re-pointed at `design_document` with a zero-row regression guard.
- **Merge-fallout repairs:** restored 4 fixtures the merge-day png-glob strip collaterally
  deleted (api image_baseline ×3 + `crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png`);
  installed `apps/editor` + `apps/custom-component-compiler` node_modules (export/compile
  paths shell out to node). **Remaining stripped-fixture debt (restore when their gates come
  online, likely Step-2/CI):** `crates/lumen-skia/tests/goldens/*.png`,
  `crates/lumen-core/fixtures/visual_regression/baselines/*.png`,
  `apps/agent_runtime/evaluation/imagery_fixtures/**/render.png` — all present in the old
  checkout at `/Users/aryankeshri/conductor/repos/clue-design`.

## Verification
- **Design-API suite: 497 collected — 487 passed / 10 skipped / 0 failed** (fresh throwaway DB
  at head; root venv + `PYTHONPATH=subsystems/clue-design:...apps/api:...apps/agent_runtime`).
- Platform: `make db-smoke` green (incl. `7a9881f9717a` up→down→up); `tests/design/` 14/14;
  mypy 577 files clean; 25 import contracts kept; ruff clean; offline pytest 2176 passed;
  `alembic heads` = `7a9881f9717a` (single).

## Process note (per the 2026-08-08 hard rule)
Mid-slice the founder made the Fable/Opus split binding: Fable plans/debugs/reviews only;
ALL code implementation is done by Opus agents. The last three fix rounds ran that way
(three Opus agents, briefed with file-exact specs, each verifying on throwaway DBs; Fable
diagnosed from suite logs and reviewed diffs). Root causes of the long D2.2 tail, for the
retro: ~10-min full-suite feedback loop (per-call-engine bridge), the legacy suite's SQLite
assumptions (direct-Repository seeding, fixed fixture ids), a self-inflicted import-inserter
bug that corrupted TSX string fixtures (two wasted rounds), and unpaid environment debt
(node_modules, stripped fixtures).

## Known interim states (deliberate, documented in code)
- Bridge = engine per call → design suite runs ~8-10 min. Optional optimization (O5-compliant):
  one persistent loop thread + one engine per process. Revisit if D2.3/D2.4 iteration hurts.
- `register_scene_assets` (SQLite) runs post-commit outside the PG txn (idempotent; heals on
  next save). Component validation TOCTOU vs the PG write — interim, closes as domains port.
- `design_document.account_id` is advisory (no FK) until D2.4.

## Next: D2.3 (brand + assets + ingestion port) — after founder ratifies the 7a9881f9717a
workspace-local-PK extension. Fable writes the brief; Opus implements.
