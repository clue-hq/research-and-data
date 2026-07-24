# 2026-07-24 — B3 residual 1 closed: workspace ownership is mandatory

## Decision
The founder confirmed every database is development-only and contains synthetic/test data. Do not
backfill legacy account ownership: discard the development database state. `brand_id` is explicitly
out of scope until the next discussion.

## Implementation
- Reset this workspace's local `public` schema with `make db-fresh`; it contained 0 accounts and
  0 contacts before reset.
- Added hash migration `82a80fb80c9e` off `7f1868a127aa`.
  - Fails loud with `make db-fresh && make migrate` guidance if a development DB still contains a
    NULL-workspace account/contact; it does not surgically delete entity rows because account/contact
    ids are soft references in multiple append-only/audit tables and partial deletion could leave
    dangling history.
  - Makes `account_entity.workspace_id` and `contact_entity.workspace_id` `NOT NULL`.
  - Deletes the legacy NULL-only strong-key indexes.
  - Rebuilds the workspace strong-key indexes without redundant `workspace_id IS NOT NULL`
    predicates.
  - Downgrade restores the transitional nullable/index shape. `brand_id` remains nullable.
- Contract-delta: `core.AccountEntity.workspace_id` and `core.ContactEntity.workspace_id` are now
  required `str` fields.
- Removed legacy-NULL behavior from live docs/tool descriptions and converted tests/fixtures to
  required ownership. `CLAUDE.md` marks residual (a) resolved and leaves only `brand_id`.

## Verification
- Deliberately downgraded to `7f1868a127aa`, inserted an unscoped synthetic account, and confirmed
  upgrade fails with the intended reset instruction; then reset/rebuilt cleanly.
- `CLUE_DATABASE_URL=... make check`: 2249 passed, 20 skipped; ruff, mypy, and 23 import contracts
  green. The first full run exposed two unstamped test fixtures (memory contact seed and pure
  contact-binding fixture); both were corrected before the green rerun.
- `make db-smoke`: full up -> base -> head green.
- `alembic heads/current`: one head, `82a80fb80c9e`.
- Live schema inspection: account/contact `workspace_id` both `is_nullable=NO`; no `*legacy*`
  indexes; all domain/registry/LinkedIn/email uniqueness remains `(workspace_id, key)`.

## Remaining B3 residual
`account_entity.brand_id` remains nullable and unstamped by research. No brand behavior changed in
this slice.
