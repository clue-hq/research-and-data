# 2026-08-13 — Stage-0 project hardening merge into Singapore

## Scope

- Current branch: `platform/pilot-budget-controls` in the Singapore worktree.
- Merged local `platform/stage0-project-hardening` at `437a3cca`.
- The source branch was treated as the owner of the Stage-0/project-chat defect allocation:
  durable ICP synthesis and gates, readiness correctness, gate presentation/recovery,
  composer clearing, chat layout, sticky scrolling, and conversation-first empty Gallery.
- Existing FI-2 work remained authoritative for Accounts/Contacts transport and for the
  Account/Contact-to-project composer handoff.

## Conflict rulings

- Kept `head-of-abm@v24` byte-for-byte as the historical FI-2 replay profile.
- Made `head-of-abm@v25` the combined active profile: `stage0-interview@v12`, trusted
  readiness/synthesis `@2`, `open_icp_confirmation_gate@1`,
  `account-deep-steering@v4`, and `launch_selected_account_research@1`.
- Kept FI-2's typed `accepted | failed | not_submitted` submission result and clears
  transferred context only after durable acceptance.
- Applied Stage-0's exact-draft clearing rule in the same composer path so a newer draft
  typed while a request is in flight is not erased.
- Combined the FI-2 handoff/thread initialization with Stage-0's conversation-first focus
  when Gallery is empty.
- Recorded the combined authority contract in
  `apps/frontend/docs/api-contracts/projects.md`.
- Joined the Stage-0 and FI-2 Alembic branches with revision `19000e4134a1`; the repository
  again reports exactly one head.

## Verification

- Frontend: 207 tests pass; ESLint passes; design-system token build passes; Next webpack
  production build and its TypeScript phase pass.
- Backend: the focused agent catalog, tool authority, registry, Stage-0 contract, recipe,
  toolbelt, runtime, and routing tests pass; Ruff format and lint pass across the root-owned
  Python surfaces.
- Database: created the isolated database `clue_merge_stage0_fi2_20260813`, ran the full
  Alembic head -> base -> head smoke plus DB-backed Stage-0 gate/tool and project chat/read
  tests, then dropped only that temporary database. The shared Damascus `clue` database was
  not changed.
- The default Turbopack root warning remains assigned to the separate integration/root-
  tooling worktree (`LF-BUILD-001`); the accepted webpack build gate is green here.

## Preserved local state

- The pre-existing `.env.example` edit was stashed before the merge as
  `codex-preserve-user-env-before-stage0-hardening-merge`. Restore it after committing the
  merge; it is user-owned and must remain uncommitted.
