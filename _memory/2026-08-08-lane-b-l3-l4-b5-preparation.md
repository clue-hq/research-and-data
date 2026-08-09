# Lane B L3/L4 and B5 pre-join preparation

Date: 2026-08-08
Branch: `platform/platformlane-b-auth`

## Completed

- L3: account-fleet job projections now expose the latest coverage row's
  `unresolved_field_keys` and `committee_status`; regression coverage proves both values survive
  the projection.
- L4: `suspend_failure` now appends a subject-neutral `entity_research_job_event` for the atomic
  `running -> queued` transition, including bounded reason/task/lease/error-digest references. The
  shared fleet event writer became a public seam; no schema change was needed because `queued` is
  the truthful existing destination event kind.
- B5 preparation: a declared production environment refuses trusted-header tenancy even before
  the deployment flip, and production app construction refuses an absent authenticated-principal
  service. Free-standing legacy human contexts cannot pass human-only gates.
- B5 adversarial evidence now covers provider-session swap continuity into durable internal tool
  authority, cross-workspace tool/launch/stream refusal before writes, and immediate membership
  revocation. Existing suites cover disabled users, token/JWKS failures, provider-key schema
  isolation, ambient-authority injection, and frontend session/BFF behavior.
- Added `docs/runbooks/authenticated-principal-cutover.md` with configuration, provisioning,
  pre-join evidence, live smoke, rollback, and exact Lane-D pause boundaries.

## Intentional pause boundary

- One compatibility exception remains only for a non-receipt human effect already declared as a
  durable C5 execution node. Lane D must replace that executor-created context with its persisted
  internal turn principal and remove the exception before D5. Every action-reference-bearing gate
  remains closed without Lane D.
- Acceptance rows 4, 9, and 12, real Clerk/browser proof, and the D5 production flip remain for the
  integrated Lane-D environment. FI-2 `frontend_read/**` and accounts files remain untouched.

## Verification

- L3 account-fleet DB suite: 8 passed.
- L4 account-fleet plus subject-neutral entity-research suites: 17 passed.
- Final B5 auth/config/projections/gated-tool/frontend-adjacent backend selection: green.
- Ruff, mypy (590 source files), and all 25 import contracts passed; Alembic remains at sole head
  `abbacac4df1f`.
- Frontend tests, ESLint, TypeScript, design-system build, and Next.js production build passed.
- A whole backend suite was also attempted. Its failures reproduced known unrelated baseline
  classes (stale v9 agent-resource assertion, clue-design logging scope, destructive migration-test
  ordering/database pollution). Re-running the affected discovery/durable/fleet/waterfall groups
  on a freshly migrated Honiara database passed; the B5-caused Recipe-0 fixture drift was repaired
  and its suite then passed.

## Repository hygiene

- No provider traffic, credential mutation, branch merge, cherry-pick, push, or Lane-D/FI-2 file
  edit was performed.
- The unrelated untracked `.playwright-mcp/` directory remains untouched.
