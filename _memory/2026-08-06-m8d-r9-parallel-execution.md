# 2026-08-06 — M8D R9 parallel execution and external-wait hardening

## Scope and result

Implemented and accepted R9 only. Account/contact `create_agent()` units now share one
provider-neutral durable tool-batch coordinator for dependency checks, aggregate job/run budget
admission, provider concurrency permits, partial completion, composite waits, and cold resume.
R10 credentialed provider canaries and final cutover remain separate.

## Main changes

- Added engine-only provider family, worst-case reservation, rate-policy, and concurrency metadata
  to provider actions/tool bindings/calls; production account/contact composition requires it.
- Added `DbEntityResearchToolBatchCoordinator` and migration `0070930672a4` for exact running-job
  batches, members, reservations, permits, events/releases, and composite waits.
- Independent Exa/Sumble calls remain concurrent; additive follow-up, overlapping fields,
  reveal+validation, coverage, finalization, and duplicate work remain sequential/fail closed.
- Runtime reconstructs a persisted model wave when a Postgres checkpoint resumes directly at the
  tool node, so the new turn re-runs the same guard and atomic admission before dispatch.
- Completed provider siblings join from durable results; internal reads never replay stale state.
- Crash takeover reuses the outstanding exact reservation/permit; wait resume reuses the
  reservation and acquires only a new permit after the prior wait released it.
- Pure replay/resume waves do not reapply admission cost to an already-reserved operation. This
  prevents a provider settlement folded before the terminal tool event from being double-counted
  as `spent + active reservation`; mixed waves with any new reservation remain fail-closed.
- Added all-member composite wake plus `R9EntityResearchJobStore` reconciliation for the
  provider-callback-before-R2-wait race; duplicate callbacks cannot re-offer a job.
- Indexed subjects in duplicated result projections and added one-way DSAR redaction, including a
  contact nested inside an account committee result.

## Acceptance defects found and fixed

- PostgreSQL rejected an ambiguous `USING (batch_id)` replay join; replaced with explicit joins.
- Cold resume skipped model-time admission and had no new-turn batch; tool-node state now restores
  and serializes the exact wave.
- LangChain middleware returned a `ToolMessage`, which made the first settlement read zero cost;
  R9 now normalizes its semantic JSON before hashing, joining, and cost settlement.
- Initial crash admission could strand a reservation/permit; exact active admission is reusable.
- Joining internal tool results could return stale claim/coverage state; joining is provider-only.
- A provider callback arriving before R2 persisted its wait could be lost; post-wait reconciliation
  now wakes the already-ready composite.
- Rechecking a pure resume against `spent + active reservation` could strand an already-admitted
  operation after early spend folding; budget admission now charges only genuinely new exposure.
- The first in-progress migration downgrade failed because the local test DB held an earlier R9
  schema shape. The disposable R9 DB was recreated, then the final migration passed down/up.

## Verification

- Dedicated R9 isolated-Postgres suite: 5 passed.
- Combined R0–R9 plus retained M8C C4–C6 matrix: 159 passed.
- Alembic `0070930672a4 -> 7bb3178d7580 -> 0070930672a4`; one head.
- Repository mypy: 565 source files, no issues.
- Import-linter: 24 contracts kept.
- Scoped Ruff, format, and diff checks passed.
- `make typecheck contracts` could not initialize the sandboxed global uv cache; direct
  `.venv/bin/mypy` and `.venv/bin/lint-imports` ran the same gates successfully.

No live or paid provider request was made. R10 owns credentialed Exa/Sumble canaries and final
cutover.
