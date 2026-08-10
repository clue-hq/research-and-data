# 2026-08-08 — Part II slice D2.4 phase A: personalization + web accounts/batches on Postgres

Branch `platform/design-integration` (no commit made — the implementing agent was git-read-only;
Fable/founder commits). Ported the last two big SQLite domains before components/publishes.

## What landed
- **`subsystems/design/clue_design/personalization.py`** — binding sets (upsert / get / list /
  delete), instances (upsert / get / list), instance batches (create / progress / get), repair
  queue (upsert / get / list). Deterministic ids kept; upserts stay upserts; the SQLite
  `*_from_row` shapes reproduced with `iso()` timestamps.
- **`subsystems/design/clue_design/accounts.py`** — web accounts (create / get→None /
  require / list / partial-patch update / delete) + web batches (create / progress / require).
  `account_values` stays in `lumen_api` (value marshalling, not storage). Batch `counts` stay
  DERIVED from `manifest_json` at read time — no stored column.
- **`design_store.HybridRepository`** — 21 new overrides covering the whole enumerated surface.
- **Migration `cf7dd82cf683`** (head, chained off `cf4f80537c8e`), TWO halves:
  1. re-adds `design_document_account_fk` (the D2.2g deferral, closable now that accounts live
     on Postgres) — `(account_id, workspace_id)` composite, `ON DELETE SET NULL (account_id)`;
  2. **re-keys `design_binding_set` / `design_instance` / `design_repair_request` PKs to
     `(…, workspace_id)`.** Not in the original brief — forced out by the design suite: binding
     ids are CLIENT-SUPPLIED (fixture ids like `bind_acme_dr_sharma`) and instance/repair ids
     are derived from them, so with a global PK the per-test workspaces collided
     (`/binding-sets` → 500 IntegrityError in 5 test_api cases). This is exactly the
     `7a9881f9717a` ruling ("client-supplied id namespaces become workspace-local;
     server-minted-uuid namespaces stay global") applied to the D1d tables, which were created
     before that ruling existed. `design_instance_batch` / `design_web_batch` ids are
     `new_id(prefix) = <prefix>_<uuid4hex>` → stay global. Child FKs point at the existing
     `(id, workspace_id)` anchors, so nothing else moved. **Worth a founder nod for the same
     reason 7a9881f9717a needed one.**

## Behaviour changes the port forces (documented at each site)
- `design_account_logo_fk` is REAL now: an account can no longer carry a logo id that resolves
  to nothing, and deleting the asset SET-NULLs the pointer. This made the SQLite-era ghost-logo
  state unreachable, so `test_derive_rejected_on_missing_logo_asset_422` was rewritten as
  `test_account_logo_cannot_dangle_and_detaches_when_the_asset_goes` (asserts the FK refusal +
  the SET-NULL detach, then that the derive still runs with `account.logo` in `unbound_slots`).
  `account_values`' defensive `except NotFoundError` is now belt-and-braces, not reachable.
- `design_instance` FKs template revisions / binding sets / batches for real — a dangling
  reference surfaces as `sqlite3.IntegrityError` through the bridge translation.
- Deleting a PG account leaves the SQLite `custom_components` rows for that account_id behind
  (SQLite had no FK either, but the two stores can now drift). Comment at
  `HybridRepository.delete_web_account`; closes at **D2.4B** when components port.
- Web-batch manifests carry account ids with no FK — ported as-is (historical record, not a
  live join).

## Tests
- `tests/design/test_personalization_accounts_dal_db.py` (7): binding-set upsert round-trip +
  workspace-local twin id, instance upsert idempotency, batch create/progress, repair
  re-detection, account CRUD + fail-closed cross-workspace require, account delete SET-NULLs a
  document stamp, web batch create + manifest progress.
- Design-suite repairs: `test_api.py`'s batch-resume rewind now goes through
  `HybridRepository.update_batch_progress` (was a direct SQLite `UPDATE instance_batches`);
  `test_web_derive.py` ghost-logo rewrite (above).

## Verification (fresh throwaway `clue_d24a`, dropped afterwards)
- ruff clean; mypy 583 files clean; 25 import contracts kept.
- `make db-smoke` green incl. `cf7dd82cf683` up→down→up; `alembic heads` = `cf7dd82cf683`.
- `tests/design/` 34 passed.
- Design API subset (web accounts/batches/derive/templates/turns + test_api):
  **181 passed / 1 skipped**. Full design suite NOT run — phase B owns it.
- Note: `pytest -q` in this repo swallows the summary line; run without `-q` to see counts.

## Next: D2.4 phase B — custom components (+ web publishes/revisions), then D2.5.
