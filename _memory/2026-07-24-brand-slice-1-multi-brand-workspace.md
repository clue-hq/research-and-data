# 2026-07-24 — Brand correction Slice 1: multiple workspace-owned brand kits

## Founder ruling

- A future `customer_account` may own one or more workspaces; the first workspace is included and
  additional workspaces require additional subscriptions. Subscription/credit modeling is deferred.
- Brand kits remain owned by a workspace, not by the customer-account layer.
- A workspace may own multiple brand kits.
- Each ABM project selects exactly one brand kit from its own workspace.
- Target accounts are workspace-local and brand-neutral. Removing the obsolete
  `account_entity.brand_id` plumbing is Slice 2, not this slice.

## Slice 1 implementation

- Migration `799564102709` (off `82a80fb80c9e`) drops only
  `brand_one_per_workspace`. It preserves `brand_workspace_anchor` and the existing composite
  product/project FKs, so cross-workspace brand references remain structurally impossible.
- Downgrade restores `brand_one_per_workspace`; it fails loudly rather than deleting data if any
  workspace already owns multiple brands.
- Replaced the singular `get_brand_for_workspace` API with:
  - `get_brand(conn, *, workspace_id, brand_id)` — workspace-scoped, so a foreign brand is
    indistinguishable from missing;
  - `list_brands_for_workspace(conn, workspace_id)` — deterministic `name, brand_id` order.
- Updated spine exports, docs, authoritative Doc M ownership/context explanation, the Phase-A
  amendment, and the B3 residual note.
- Tests now prove multiple brands per workspace, different projects selecting different brands,
  fail-closed cross-workspace reads, and DB rejection of cross-workspace project-brand references.

## Explicitly not changed

- `account_entity.brand_id` and its research plumbing remain for Slice 2.
- `project_run.project_id` remains nullable and brand/version pinning is not yet wired.
- No `customer_account`, subscription, credit, `workspace_brand`, or brand-version table was added.
- The frozen scoped-memory decisions notepad and historical object-spine migration retain their
  original V1 record.

## Verification

- Focused DB suite: `10 passed`.
- `make check` with the local Postgres URL: `2250 passed, 20 skipped`; ruff, mypy (327 files), and
  23 import contracts green.
- `make db-smoke`: full head → base → head green.
- One Alembic head/current: `799564102709`.
- Live schema inspection: `brand` constraints are only `brand_pkey`, `brand_workspace_anchor`, and
  `brand_workspace_fk`; both `product_brand_fk` and `project_brand_fk` still reference
  `(brand_id, workspace_id)`.
- This workspace has no `.env`; DB-gated commands used the established local
  `postgresql+asyncpg://clue:clue@localhost:5432/clue` URL explicitly. The initial focused pytest
  without that environment skipped all 10 DB tests, then the explicit-URL rerun passed.
