# Lane B B1-B4 review remediation and activation

Date: 2026-08-08
Branch: `platform/platformlane-b-auth`

## Completed

- Fixed both confirmed critical defects: pre-B4 execution nodes with no authority row replay
  normally, and Clerk JWKS refresh replaces the prior keyset so rotated-out keys are rejected.
- Hardened B2: provider/JWKS outages are retryable 503s with refresh-failure throttling; enabled
  auth requires an explicit environment; production rejects local-header authority; every
  authorizer call names a permission; the provider-neutral identity shapes match the frozen
  contract; auth errors include request ids.
- Completed B3's enabled flow: one configured Clerk JWT template supplies the backend audience;
  post-sign-in seeds the first active workspace; every BFF request refreshes memberships and
  repairs absent/revoked selection; sign-out clears the Clue workspace cookie; `npm test` now
  discovers nested tests recursively.
- Activated B4: auth-enabled projection/ingestion/research routes resolve one cached
  `RequestPrincipal`, ignore browser `X-Actor`, enforce internal permissions, and inject internal
  user/membership ids into `ToolContext`. Detached agent/supervisor/recheck/executor sites now use
  stable service-principal identities. Human-only gates reject authenticated service contexts;
  membership-FK drift raises a typed authority-state error and maps to
  `MEMBERSHIP_STATE_CHANGED`.
- Closed contained B1 review gaps: public membership mutation APIs require an active managing
  membership, cannot remove the last active owner, can explicitly readmit a revoked member, and
  can erase an unaccepted invitation delivery target. The provider-key acceptance gate now also
  introspects the migrated live schema.

## Verification

- 124 focused backend auth/execution/API/ingestion/narrative/config tests passed against the
  Honiara-isolated Postgres on port 55050.
- Whole-repo Ruff lint passed; mypy passed across 590 source files; import-linter kept all 25
  contracts; Alembic remains at sole head `abbacac4df1f`; changed Python scope is formatted.
- Frontend: 33 recursively discovered tests, ESLint, design-system build, TypeScript/Next.js 16
  production build passed. React review moved sign-out pending state to `useTransition` and kept
  the server action behind a typed component prop.

## Boundaries / limits

- No Clerk credentials were present, so no live-provider sign-in/JWKS acceptance is claimed.
- Lane D still owns persisted `turn-action:<turn_id>` derivation/resolution and its chat-specific
  ToolContext join. FI-2-owned `frontend_read/**`, accounts feature files/contracts, and Lane-D
  project/chat files were not touched.
- Auth remains default-off. B5 still owns final removal of all legacy-null contexts and trusted
  header surfaces; authenticated production mode now fails configuration if local-header
  authority is selected.
- The unrelated untracked `.playwright-mcp/` directory was left untouched.
