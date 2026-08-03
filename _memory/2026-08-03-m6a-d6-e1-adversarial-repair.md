# 2026-08-03 — M6A D6/E1 adversarial repair

## Outcome

- Repair commit: `3b7458a` (`fix(discovery): harden D6 and E1 production lifecycle`).
- Exa CSV import wire serialization now preserves the required `format=csv` discriminator and
  identifier object; independent golden bytes guard the real boundary.
- D6 and E1 new spend require active eligible phases and reserve against one locked project-run
  capacity that includes outstanding operations from both ledgers.
- Terminal success transactionally settles actual internal cost into `project_run.spent_cents`;
  terminal E1 state, receipts, charges, field outcomes, and claim lineage are database-guarded.
- E1 is composed through `enrich_selected_accounts@1`, a separate default-off spend switch, and a
  lifecycle-controlled fleet poller. Provider prompts/formats/options are pinned policy.
- Every E1 artifact is account-indexed for DSAR. Terminal replay reads the operation before artifact
  capture, so an erased subject edge/blob is not resurrected; an erased D5 manifest makes a fresh
  production start fail closed before provider work.
- Added an idempotent Exa team-webhook provisioning script with secret-safe output handling.
- Hardening migration `fffa2a8ba17c` self-heals historical D4 review-task tenant-lineage drift in
  long-lived databases and retains the resolved review reference after admission.

## Verification

- D2-D6/E1/scoring-bypass PostgreSQL regression: 81 passed.
- E1 tool -> reservation -> fleet lease -> polling -> claims/cost -> DSAR/replay: 4 passed.
- mypy: 481 files, no issues.
- import-linter: 24 contracts kept.
- targeted Ruff format/lint: pass.
- Alembic: single head `fffa2a8ba17c`; full head -> base -> head passed on the isolated temporary
  database `clue_m6a_repair_smoke_20260803`, which was then removed.

## Live gate

- Read-only eligibility audit found zero active `DEEP` account/run pairs with exact live
  human-selected tier and seal lineage.
- No paid E1 call was made. The bounded live E1 canary remains `OPEN`; do not promote a hold or
  fabricate human approval to close it.
