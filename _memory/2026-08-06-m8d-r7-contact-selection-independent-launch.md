# 2026-08-06 — M8D R7 contact selection and independent launch

## Outcome

- Generalized the M8C durable selection receipt to exact human-selected committee or associated
  non-committee contacts.
- Persisted target-local fields, field-to-source authority, directional questions, facets,
  channels, policies, budgets, identity/association evidence, and approvals.
- Added separate idempotent human launch into the shared R2 contact fleet. Automatic committee
  preparation alone cannot launch research.
- Added per-job contact authority so one contact cannot consume the run-wide union of another
  contact's research plan.

## Persistence and enforcement

- Migration `02e552db75da` follows `4ff507129dd5` and is the single head.
- Added `entity_research_contact_launch`, `entity_research_contact_job_authority`, the R2 contact
  selection pin, scoped/immutable guards, and the deferred exact-run completion trigger.
- Direct contact-run insertion, stale/cancelled selection, missing human selection, cross-contact
  evidence, partial authority, and changed operation replay fail atomically.
- Launch/cancel/successor share a selection-scope lock, and active R2 jobs fence selection
  cancellation or succession until accepted fleet finalization/cancellation receipts make them
  terminal.
- Preserved exact-replay reconstruction for pre-R7 M8C committee receipts.

## Verification

- R7 isolated-Postgres acceptance: 5 passed after downgrade/upgrade.
- Combined retained M8C C0-C7 and M8D R0-R7 regression matrix: 188 passed.
- Scoped Ruff, repository mypy over 557 source files, and all 24 import contracts passed; Alembic
  reports one head.
- Assertions prove selection/launch creates no provider, external-research, or channel operations.

## Unrelated repository diagnostics

- `make check` stops at formatting for 12 non-R7 files already in the shared dirty worktree.
- Full-suite diagnostics found two stale account-deep expectations and one targeted-enrichment
  event wait that assume the R1-quarantined old flow can launch. They fail/wait at the intended
  `entity_research_agent_not_composed` boundary. R7 reaches and passes before the wait.

## Boundary

- R7 queues authorized contact work; it does not compose or execute a contact agent.
- R8 owns contact `create_agent()` execution on the shared fleet.
- R10 owns credentialed live Exa/Sumble canaries. No live or paid provider call occurred in R7.
