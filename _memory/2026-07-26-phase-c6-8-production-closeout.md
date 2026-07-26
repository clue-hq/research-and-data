# 2026-07-26 — C6.8 production close-out

## Outcome

C6.8 and Phase C6 are complete on `platform/c6-deepagent-runtime`. Product behavior remains
mechanical by default. New Stage-0/account subjects obtain one immutable `legacy` or `deepagent`
owner only when the corresponding default-off rollout policy selects them. C7.0 is next.

## Implemented

- Added the reversible `a7eb7cbbcbc2` migration for append-only runtime ownership, final workspace
  usage, cleanup receipts, and model cache token attribution. Exactly one Alembic head remains.
- Added master/surface switches, JSON workspace allowlist, stable workspace+surface percentage
  cohorts, account-plan budget ceiling, retention, and cleanup cadence settings.
- Added durable choose-once routing with no post-failure fallback. Existing deepagent-owned account
  subjects keep the account runtime composed after rollout switches are reduced.
- Composed the real prepared account turn in the existing DEEP slot: promoted
  `account-research-unit@1`, deterministic execution/turn ids, exact stage/readiness/budget/input/
  resource artifacts, typed workspace-local context cards, fresh L1–L7 context, governed model,
  C5 adapter, coverage tool, completion guard, and honest finalization.
- Completed C5 account recipes only after completed finalization. A process restart securely
  reopens the same normalized execution root; every resource/context/manifest digest is rechecked
  before checkpoint resume.
- Added authenticated body-free registry, project-turn, turn, progress, telemetry, and route
  projections. No prompt, skill, artifact body, model body, absolute host path, or erased content
  is returned.
- Added cache-read/cache-creation tokens, tool reference yield, context exclusion/size, final
  workspace quota, child spend, and finalize-failure telemetry.
- Added the non-fatal fleet cleanup loop and append-only receipts. Only completed/failed/abandoned/
  privacy-tombstoned roots age out; `awaiting_input` remains live and is never cleanup-eligible.
- Added fail-closed comparative canary evaluation for invisible failures, duplicate effects,
  terminal/promotable/verified regression, and cost/round bands.
- Added the production operations runbook and C7.0 prerequisite/handoff plan; updated Doc A, the C6
  spec/plan, Phase-C index, and parent phase status.

## Verification

- Clean DB-enabled full repository suite passed: 2,616 tests, 0 failures/errors, 20 intentional
  skips (`135.170s`).
- Ruff format/check passed across all 856 tracked and owned C6.8 Python files.
- Mypy passed across 420 source files.
- Import-linter kept all 24 contracts across 481 files and 3,477 dependencies.
- Clean throwaway Postgres head→base→head smoke passed; sole head is `a7eb7cbbcbc2`.
- Scripts 01–06 passed as one offline chain.
- Generic eval and M9.6 verification eval completed; the latter correctly demonstrated a failing
  faithfulness model-swap gate.
- Focused routing, context-card locality, prepared budget, workspace reopen/digest verification,
  cache telemetry, projections, cleanup, DSAR, and migration tests passed.
- `git diff --check` passed.

## Verification incident

The first migration-smoke invocation reused the script-populated disposable database. The older
C5.3 downgrade correctly refused because pre-materialized tool nodes existed. The database was
dropped/recreated under the exact disposable name and the required clean head→base→head smoke then
passed. No shared or user database was touched.

## Operational decisions

- A route receipt is authority, not current configuration. Never edit/delete it or fall through to
  the other owner after failure.
- Rollout switch reduction stops new assignments; it does not strand an existing deepagent owner.
- `awaiting_input` is resumable, never terminal cleanup state.
- Account plan authority is clamped to the strictest durable envelope and deployment ceiling.
- Durable Postgres/artifact receipts remain authoritative; the isolated filesystem is ephemeral
  working state and contains no application code.

## Next

Start C7.0 only: freeze derivation/entailment, dossier/block/reference, re-check tool, coverage
appendix, production handoff-reader, and DSAR-reachability contracts. Close each named C8
prerequisite before its first C7 consumer; do not create a second agent loop, truth store,
execution journal, workspace backend, evaluator, or handoff path.
