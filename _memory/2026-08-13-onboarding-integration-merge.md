# 2026-08-13 — Onboarding integration merge into Singapore

## Scope

- Current branch: `platform/pilot-budget-controls` in the Singapore worktree.
- Merged local `platform/onboarding-integration` at `4eb9f99e`.
- The onboarding branch owns FI-4 workspace onboarding: headless Clerk screens, replay-safe
  user/workspace/brand provisioning, profile persistence/DSAR, website capture, governed
  reverse profiling, per-field progress, and the onboarding Exa/LLM extraction composition.
- The already-integrated Stage-0 hardening branch remains authoritative after onboarding
  release: project interview, readiness, durable ICP synthesis/confirmation, and chat gates.
- FI-2 remains authoritative for explicit workspace selection and Accounts/Contacts flows.

## Conflict and integration rulings

- `/sign-in` keeps FI-2's explicit expired-session cleanup, then redirects ordinary sign-in
  to the approved `/onboarding/sign-in` headless-Clerk UI; the stock Clerk widget is retired.
- Session selection combines both contracts: fresh identities/no membership history route to
  onboarding; inactive former memberships route to access denied; any active membership still
  requires an explicit workspace cookie. Onboarding now selects the exact `workspace_id`
  returned by provisioning before starting setup rather than silently choosing the first row.
- `client_kb.py` combines onboarding's asynchronous per-field progress callback with the
  Stage-0 hardening readiness helpers and dynamic required-field support.
- Onboarding recon/progress uses all eleven baseline fields. The active ICP-synthesis gate
  explicitly retains its nine core-field denominator, so background-only competitor/buyer
  enrichment cannot silently change the ratified Insight Health result from 7/9 ready to
  7/11 blocked. A workspace may explicitly require those keys.
- Joined the provisioning migration branch with the existing Stage-0/FI-2 graph using
  Alembic revision `ea63efd38c3a`; the repository again has exactly one head.
- Recorded the denominator and explicit workspace-selection rulings in the onboarding API
  contract and FI-4 specification.

## Verification

- Frontend: 278 tests pass; ESLint and design-system token build pass; Next webpack production
  build and its TypeScript phase pass with all onboarding, Account, and Project routes present.
- Backend: focused onboarding, auth, extraction, Exa, Stage-0 hardening, agent registry,
  recipe, and toolbelt suites pass; Ruff format/lint pass across root-owned Python surfaces.
- Database: created isolated `clue_merge_onboarding_20260813`, ran full Alembic head -> base ->
  head plus self-serve provisioning, setup/progress, reverse-profile, dynamic Client-KB,
  ICP-synthesis/gate, and project-chat/read suites, then dropped only that temporary database.
  The shared Damascus `clue` database was not changed.
- The Next workspace-root warning remains the separately allocated `LF-BUILD-001` root-tooling
  issue and was not expanded into this merge.

## Preserved local state

- The pre-existing `.env.example` edit was stashed before the merge as
  `codex-preserve-user-env-before-onboarding-merge`. Restore it after committing the merge;
  it is user-owned and must remain uncommitted.
