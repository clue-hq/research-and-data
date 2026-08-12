# 2026-08-13 — FI-2 Slice 9A Account and Contact bulk actions

## Ratified behavior

- Selection never survives a search, filter, sort, page or page-size change; there is no hidden
  selection state or hidden-selection counter.
- Select-all means only the currently rendered page. It never implies all matching backend rows.
- Numbered pagination is shared by the Account and Contact tables. Page-size choices are exactly
  10, 20, 30, 50, 75 and 100; an authored page number is bounded to the real page range.
- Account bulk requests have a hard maximum of 100. Contact email lookup retains Slice 10's maximum
  of 20 because it dispatches external provider work.
- Keep the existing New Account and per-row email controls. Slice 9A closes only dead table
  selection, not the separate Account-create contract.

## Implementation

- Added reversible Alembic head `fdb5f0eb3b0e` with durable operation and per-item ledgers. Every
  mutation records workspace, actor, membership, idempotency key, normalized request hash, item
  outcome, counts and finalization time.
- Added authenticated capability and mutation routes. Capabilities are calculated by the backend
  from the RequestPrincipal rather than guessed from frontend roles; viewers receive no selection
  affordance.
- Account `Add to project` requires `project.write`, checks exact workspace membership, writes
  first-add-wins `project_account` rows with `added_via=manual`, treats existing membership as
  unchanged and never launches research.
- Contact `Look up work emails` requires `research.launch`, enforces Account committee membership
  and identity anchors, and delegates to the existing Slice 10 Exa/Sumble service. Existing monthly
  operations are reused; `not_found` is an empty terminal outcome, not a fabricated success.
- Added one same-origin BFF mutation helper and typed frontend repositories. Contextual action bars
  show the exact current-page count, expose clear/allowed actions and clear after completion.
- The Accounts list now supports stable numbered `page` plus `limit` metadata while retaining the
  legacy cursor contract for existing consumers. Cursor and page cannot be combined.
- Added one shared pagination footer to Account and Contact tables. Previous/next controls use 14 px
  Lucide chevrons at 1.5 stroke with concise accessible names. The footer uses the same
  `--clue-ds-product-dimension-sidebar-profile-height` token as the signed-in profile row, so both
  are exactly 40 px and vertically aligned.
- Updated `apps/frontend/docs/api-contracts/accounts.md` and closed LF-ACCOUNT-005 in the local
  `.context/defect-log.md`.

## Browser acceptance

- Ran a real authenticated Clerk browser journey at `http://localhost:3077` against an isolated
  pgvector database with 30 durable Accounts, two real projects and three governed Contacts.
- Accounts: verified `Showing 1–20 of 30`, exact page-size choices, direct page input, current-page
  select-all (20 only), next-page selection reset, search selection reset and tri-state header.
- Performed a real Account-to-project bulk mutation. PostgreSQL showed `added_via=manual`; the UI
  reported one added, cleared selection and retained membership across reload.
- Contacts: verified selection/search reset and current-page pagination, then started a three-row
  email batch. With both providers deliberately unconfigured, the durable result was three
  `provider_unavailable` failures, zero cost/credits/artifacts/claims and truthful `Try again` UI
  after reload; no fake `Email found` result appeared.
- Temporarily exercised a viewer membership: both tables rendered data with zero checkboxes. Owner
  restoration returned exactly one header plus the 20 current-page Account checkboxes.
- Measured Account and Contact footers in the real viewport: footer and sidebar profile row were
  both 40 px with identical top/bottom coordinates. Both navigation buttons contained SVG
  chevrons, no literal less-than/greater-than text, and retained `Previous page`/`Next page` names.
- Browser console contained no runtime errors; only the expected Clerk development-key warning and
  development HMR messages.

## Verification

- Frontend: 179/179 tests pass; focused ESLint and TypeScript pass; optimized Next webpack build
  passes.
- Backend focused: 83 Slice 9A/frontend-read/email/membership tests passed on disposable Postgres.
- Database: migration head-to-base-to-head smoke passed; `alembic heads` reports only
  `fdb5f0eb3b0e`.
- Repository static gate: Ruff formatting/lint, mypy across 636 source files and all 25 import
  contracts pass.
- Full repository run on a second disposable database: 4,381 passed, 23 skipped, 36 failed. None of
  the failures is a Slice 9A test. The failure set is the same known shared-database/workspace,
  retired-resource, logging-scan, Lane-E fixture and waterfall registry contamination baseline
  recorded by adjacent FI-2 slices; the prior Slice 10 baseline was 4,375 passed with the same 36
  failures.

## Operational boundary

- No paid provider call was made. Contact batch acceptance used deliberately unconfigured
  adapters, and its zero-spend terminal records were inspected.
- The disposable browser database and local servers were kept only for this acceptance run; no
  remote branch, pull request or external state was changed.
