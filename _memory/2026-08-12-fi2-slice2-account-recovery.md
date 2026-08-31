# 2026-08-12 — FI-2 Slice 2 typed Account recovery

Branch: `platform/fi2-accounts-cutover` in the Monterrey worktree.

## Scope and decisions

- Implemented LF-ACCOUNT-003 only. Deferred New Account durability, bulk selection, Contact email
  enrichment, research source precision, and governance remain unchanged.
- Expected Account failures are a closed data-layer result: session expiry, workspace selection,
  forbidden membership, service unavailable, and contract/configuration error. Unknown programming
  errors still throw.
- Retry exists only for service outages. Contract/configuration failures show support guidance and
  a safe request reference when present; backend messages and framework details never enter props.
- Missing, stale, or multi-membership workspace state now opens an explicit chooser rather than
  silently selecting the first membership. Backend principal validation still authorizes the choice.
- A stale Clerk session now renders an explicit `Sign in again` action that clears the workspace
  cookie and signs out on user activation; the previous generic Clerk SignIn screen was blank while
  the provider still considered the browser authenticated.
- The reserved `/frontend/v1` prefix installs its error envelope even when read routes are disabled.
  Routes stay absent/404, but configuration failures now carry the standard request id. Off-prefix
  response behavior is unchanged.

## Verification

- Frontend: 149/149 tests passed; TypeScript passed; full ESLint passed; design-system build passed.
- Production: `next build --webpack` passed, including the new `/select-workspace` route.
- Backend: 33 focused auth/frontend-read/FI-2 tests passed against the isolated Slice-1 Postgres
  database. Frontend-read Ruff lint and format checks passed.
- Authenticated browser matrix on `http://localhost:3000/accounts`:
  - durable healthy state returned the Insight Health workspace and zero-account copy;
  - a real stopped API produced one retryable protected-session outage and recovered on `Try again`;
  - a flag-off real API produced non-retryable Account support state with a 32-character request id;
  - controlled authenticated responses produced workspace-selection and forbidden states with no
    retry control, internal message, or framework overlay;
  - the access action reached `/access-denied`, and expiry reached a visible `Sign in again` action;
  - a two-membership session opened `/select-workspace`; choosing one wrote the cookie, re-authorized
    the principal, and returned to Accounts;
  - an Account-only 503 showed the only Account retry button and recovered to zero-state after the
    service returned;
  - every final healthy check had no Next error overlay or issue badge.
- The disposable response harness lived only under `/private/tmp`, asserted server-authored bearer
  and workspace headers, and was stopped. It is not an application fixture or repository file.

## Final state

- LF-ACCOUNT-003 is closed in `.context/defect-log.md` with acceptance evidence.
- Insight Health selection and the real zero-account state were restored after controlled testing.
- No deferred Slice 3+ control or research/governance issue was changed.
