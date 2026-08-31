# 2026-08-07 — Part II slice D1 executed: the `design_*` Postgres schema

## What landed (branch `platform/design-integration`)
Six hand-written reversible migrations chained off the ratified base `c6d84aa84b79` (single
head at every step; final head **`e79f192828b1`**):

1. `7bff99d2ad65` **D1a documents+history** — `design_document` (doc_kind scene|web,
   `current_scene_json` source of truth, CAS `current_version`, undo/redo stacks, `account_id`
   column born WITHOUT FK — added in D1e to break the a↔e cycle), `design_edit_envelope`
   (batch anchor + real self-FKs for reverts/reapplies), `design_operation_log` (real batch
   FK), `design_snapshot`, `design_template_revision`, `design_document_diagnostic`.
2. `51db518c2a68` **D1b brand** — `design_brand_kit` (PK `(brand_kit_id, version)`; O2:
   born-nullable composite `(brand_id, workspace_id) → brand`; THE platform versioned
   brand-kit payload), `design_brand_compat_report`.
3. `c6cb64259ef1` **D1c assets** — `design_asset` (registry only; bytes move at D4),
   `design_asset_description` (O3: full-behavior port; real 1:1 FK; `ai`-rows-have-model
   CHECK). `asset_metadata` NOT ported (O3).
4. `47d2e1ca25f1` **D1d personalization** — `design_binding_set`, `design_instance_batch`,
   `design_instance` (deterministic ids kept), `design_repair_request`; all real composite FKs
   to `design_template_revision`.
5. `86a9ce389e6e` **D1e web+components** — `design_account` (O1: born-nullable uuid
   `account_entity_id` composite-FK'd to `account_entity(id, workspace_id)`), the deferred
   `design_document_account_fk`, `design_web_batch`, `design_web_publish_revision`
   (content-address CHECK `publish_id = 'webpub_' || package_digest`; no-UPDATE **and**
   no-DELETE triggers), `design_web_publish` (O6: PK `(workspace_id, slug)`),
   `design_custom_component` (+ slug shape CHECK; current-revision FK added post-creation —
   component↔revision cycle), `design_custom_component_source_revision` / `_artifact` /
   `_compilation` (content-hash id shape CHECKs; shared no-UPDATE trigger fn).
6. `e79f192828b1` **D1f runs/events/ingestion** — `design_agent_run` (TEMPORARY shape → D5),
   `design_run_event` (TEMPORARY → dies at D7), `design_ingestion_job` (real composite result
   FK to the brand kit).

Tenancy laws applied everywhere: `workspace_id NOT NULL` + workspace FK; `*_workspace_anchor`
uniques; every child FK composite `(parent_id, workspace_id)`; composite `ON DELETE SET NULL
(col)` column-lists (PG15+; local Homebrew PG17 + CI pg16 both fine). Enums: 11 package-local
StrEnums in `clue_design/enums.py` + `DESIGN_PG_ENUMS` map (CHECK-backed/closed vocabularies
only per contract §4; engine-owned free-text stays text). Tests: `tests/design/` (identity-
pattern conftest: session `migrated_db` → upgrade head; rollback-isolated writes) — enum
parity, publish-revision UPDATE+DELETE rejection, custom-component UPDATE rejection ×3,
cross-workspace child insert = IntegrityError, O1 foreign-entity bind = IntegrityError
(same-workspace bind succeeds), offline single-head-descends-from-`c6d84aa84b79` guard.

## Verification
- `make db-smoke` (up→down→up) **PASS** on a clean throwaway DB (`clue_d1_smoke`, dropped after).
- `tests/design/` 6/6 pass against the migrated throwaway.
- Offline gates: ruff check clean; 25 import contracts kept; mypy clean (570 files);
  full offline pytest **2176 passed / 1453 skipped**; `alembic heads` = `e79f192828b1` (single).
- Two real bugs the smoke caught (fixed): an index named `design_instance_batch` collided with
  the table of that name (renamed `design_instance_batch_id` — indexes share the relation
  namespace); `RAISE EXCEPTION '%%…'` left no placeholder for `TG_TABLE_NAME` ("too many
  parameters for RAISE") — single `%` is correct through op.execute.

## Environment discovery (matters for every DB session on this machine)
`localhost:5432` is served by a **Homebrew PostgreSQL 17** (`/opt/homebrew/var/postgresql@17`),
whose loopback bind shadows the docker `clue-postgres` container's wildcard proxy — host
connections (incl. `CLUE_DATABASE_URL` defaults) hit the Homebrew instance, NOT docker. The
`clue` role/db exist there; `docker exec clue-postgres psql` reaches a DIFFERENT server. Create
throwaway DBs via `/opt/homebrew/opt/libpq/bin/psql -h localhost -U clue`, not docker exec.

## Pre-existing failure surfaced (NOT a D1 regression — evidence recorded)
The **full DB-enabled** suite has failures independent of D1: on a fresh throwaway at the
pre-D1 head `c6d84aa84b79` → 34 failed; with D1 → 26 failed; the same modules fail both sides
(e.g. `tests/sources/test_waterfall.py` fails 7/30 identically on both throwaways, and 30/30
on the long-lived dev `clue` DB). State/seed-dependent DB-test failures that predate Part II
(CI green because its ordering/state differs). Not investigated further — out of D1 scope;
flag to the platform owner alongside the 23-file ruff-format drift (also still pending).

## Next: D2 (persistence code port)
Blocked on: **O6b ratification** (interim `/p/{slug}` rule; recommendation (a) workspace in
public URLs) + the user's D2 go. Scope per contract §7: port Repository/IngestionJobStore/
DescriptionStore to per-domain async DAL modules in `clue_design` behind `ConnFactory`; R3
workspace entry for the design apps; O4 header seam; scene-write CAS; parent-row-lock seq
allocation; O5 bridge (one-coroutine-one-transaction for atomic ops); delete SQLite.
