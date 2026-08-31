# 2026-08-14 — Production deepagent context S0/S1

## Scope

- Implemented only S0 and S1 from `docs/specs/FI-production-deepagent-context-composition.md`.
- The previously started S2 workspace-client migration/binding files remain uncommitted and were
  deliberately not included in this checkpoint.
- S3 production attachment, S4 claim tools, S5 product catalog, and S6 live acceptance remain
  planned. The real worker's v2 envelope therefore reports Client-KB and project Stage-0 context
  as unavailable until S3 actually attaches them.

## Changes

- Added the strict `ProjectConversationCard@2`, account-wide `ClientKnowledgeCard@1`, and
  active-project-only `Stage0ProjectStateCard@1` contracts.
- Added deterministic compilers with caps, UTF-8-safe truncation, interpretable field metadata,
  exact Client-KB version/scope validation, deterministic omission cursors, and policy lineage.
- Kept the old combined `Stage0ProjectCard` as a trial compatibility contract. The split project
  compiler reuses its interview/readiness selection with Client-KB payload selection disabled, so
  account facts cannot consume or alter the project-state size budget.
- Upgraded the real production conversation envelope to schema v2 without pretending S3 has
  composed the conditional artifacts.
- Extended the existing Stage-0 statement DSAR binding helper to the split project-state card.
- Added the seven-state S0 fixture and provider-free, DB, API-seam, Project-A/B isolation, cursor,
  policy, UTF-8, scope, and erased-evidence tests.

## Verification

- Pure S0/API contract tests: 9 passed.
- Split compiler DB tests: 3 passed.
- Projection + PC-C8 context/evidence/inspection/DSAR regression selection: all passed (94 tests).
- Architecture/dependency/import selection: 26 passed, 2 expected skips.
- S1 source and owned-test mypy checks passed; import-linter kept all 25 contracts.
- Full-repository mypy is currently red only in the deliberately uncommitted S2
  `client_context_binding.py`; do not attribute those four errors to S0/S1.

## Follow-up

- Review and commit only S0/S1 paths.
- Resume S2 separately, fixing its typing and running its migration downgrade/upgrade gates before
  composition work begins.
