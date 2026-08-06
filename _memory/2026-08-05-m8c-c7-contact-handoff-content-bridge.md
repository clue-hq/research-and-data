# 2026-08-05 — M8C C7 contact handoff/content bridge

## Scope completed

- Added a frozen reference-only `ContactContentHandoff` core contract and production composition
  service over existing research views, contact eligibility, selection, and channel ledgers.
- Routed the six C1 professional fields into the contact research view; raw email/phone remain
  unrouted and delivery-only.
- Added selected/skipped contact, field/source/channel coverage, safe drafting fallback, and
  product/run/selection exactness.
- Added exact-selection channel authorization: direct operations or immutable reuse receipts only.
- Made latest-selection ordering deterministic by explicit `approved_at`; a cancelled successor
  cannot fall back to its predecessor in C7.

## Important findings while testing

- The database correctly rejected synthetic Sumble/Exa claims without their provider lineage. The
  C7 projection fixture now uses neutral claim sources and reports the configured providers as
  unsearched instead of weakening lineage triggers.
- PostgreSQL `now()` is transaction-stable. Predecessor and successor selections inserted in one
  transaction had identical `created_at`, so UUID ordering intermittently elected the predecessor.
  `latest_contact_research_selection` now orders by body `approved_at` first, with a deterministic
  regression id.
- Reading all channel operations for a contact/run was too broad. C7 now requires the current
  selection's direct operation or exact reuse receipt; an older successful operation alone is not
  delivery authority.
- Numeric committee coverage is not currently durable in `account_run`; C7 emits an explicit null
  plus `committee_coverage_not_durable` rather than manufacturing a percentage.

## Verification

- 71 M8C/C7/committee tests passed against isolated DB `clue_roseau_m8c7`.
- The full repository pytest suite passed against the same isolated database.
- Ruff format/check passed for the owned files; repository mypy passed for 539 source files.
- Import-linter: 24/24 contracts kept across 606 files and 5,049 dependencies.
- Alembic has one head: `4d9b02f218dc`.
- No provider/model traffic or paid spend; C7 is read-side. V0 is next, V1 remains separately
  authorized live acceptance.

## User-owned state preserved

Unrelated modified/untracked architecture, model-surface, playbook, skill, artifact, and prior
memory files were not edited or staged.
