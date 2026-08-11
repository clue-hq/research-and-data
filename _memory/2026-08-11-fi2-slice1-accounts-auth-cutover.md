# 2026-08-11 — FI-2 Slice 1 Accounts authenticated cutover

Branch: `platform/fi2-accounts-cutover` in the Monterrey worktree.

## Scope and decisions

- Implemented only LF-ACCOUNT-001 and LF-ACCOUNT-002.
- Removed Accounts, Account-detail, Contact, and Account-workspace runtime fixtures completely.
- Kept New Account/local creation, Account/Contact selection controls, email lookup, research
  source precision, and research-governance UI unchanged for their separately approved slices.

## Implementation

- Accounts and Contacts repositories are live-only and call `/frontend/v1`; no unset-variable or
  fixture fallback remains.
- Added one server-only authenticated backend primitive shared by Server Component repositories
  and the same-origin `/api/clue/**` BFF. It derives the Clerk proof server-side, reloads the Clue
  principal/membership, strips browser-authored authorization and workspace headers, and sends
  `Authorization` plus `X-Clue-Workspace-Id` to FastAPI.
- Removed `CLUE_ACCOUNTS_API_BASE_URL`, `CLUE_WORKSPACE_ID`, the legacy `X-Workspace-Id` Accounts
  transport, and the unauthenticated Next rewrite.
- A workspace with zero durable accounts now renders “No accounts exist in this workspace yet.”
  Unserved workspace tabs return explicit empty models and never demo activity/artifacts.
- Updated the Accounts contract, frontend architecture, environment example, and README to record
  the live-only/authenticated contract.

## Verification

- Frontend: 141/141 tests passed; ESLint passed; design-system build passed.
- Production build: `next build --webpack` passed compilation, TypeScript, eight static pages, and
  all dynamic Account/Contact routes. Default Turbopack repeated the known no-output build stall and
  was stopped after a bounded 40 seconds.
- Backend: 131 focused auth/frontend-read/FI-2 cases passed on the isolated database.
- Durable state: Insight Health workspace has one active membership, zero `account_entity` rows,
  and zero `contact_entity` rows.
- Browser, signed out: `/accounts` redirected to `/sign-in?reason=session_expired`; a browser call to
  `/api/clue/frontend/v1/accounts` returned `401 AUTHENTICATION_REQUIRED`, and its request carried
  neither authorization nor workspace headers.
- Browser, signed in: pending. The local Playwright profile had no Clerk session and the connected
  Chrome control path timed out. Creating a short-lived Clerk sign-in token from another worktree's
  secret was rejected because it needs explicit user approval; no workaround was attempted.
- Root `make check`: formatting, Ruff, mypy, and all 25 import contracts passed. Pytest completed
  with 4,352 passed, 23 skipped, and 35 failures in untouched backend/design paths. Failures include
  the known shared-state/migration cluster plus independently reproducible pre-existing failures
  (`test_resolved_snapshot_materializes_through_c61_backend` and the design-subsystem logging
  discipline scan). The FI-2-focused suites remain green.

## Runtime and cleanup

- Frontend and API development servers were stopped.
- Preserved the paired acceptance database/artifact root and the isolated full-gate database for
  reproducibility. A failed compose attempt left `monterrey_default` and the unattached
  `monterrey_clue_pgdata`; removal was not authorized, so both remain. The accidental empty
  misnamed database created during setup was verified to contain no schema/data and dropped.

## Remaining acceptance

Run one signed-in browser pass for the seeded Clerk subject and verify: zero-account copy, no demo
companies, `/api/clue` same-origin browser calls, FastAPI `X-Clue-Workspace-Id`, no legacy header,
and denied unauthenticated/cross-workspace requests. Then LF-ACCOUNT-001/002 can be marked closed.
