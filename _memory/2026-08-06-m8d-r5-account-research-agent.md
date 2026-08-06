# 2026-08-06 — M8D R5 account research agent

## Outcome

- Implemented the bounded account `langchain.agents.create_agent()` definition and R3/R4
  composition without restoring production cutover; R1 remains fail-loud until R6.
- Added result-informed account state/evidence/coverage/review/finalization engine tools.
- Added bundled Exa account qualitative research over E1/E2 and separate Sumble structured
  account enrichment over S1.
- Added grounded buying-unit scope plus office-coherent Sumble Teams/People committee formation;
  committee results project identity-admitted contacts but never launch contact research.
- Added explicit persisted `confirmed_empty_discovery` for a genuinely empty committee.
- Preserved provider-neutral additive follow-up lineage and exact field/source authority.

## Persistence

- Migration `85595185f793` follows `5764311c620d` and is the single head.
- Added result cost/empty state, subject-aware committee result fields, immutable Sumble
  projections, buying-unit scope, coverage, review, finalization intent, and provider-operation
  settlement folding.
- Settlement folding is atomic and idempotent by provider operation. This fixed a real regression
  found by the R4 replay test: a replay result had been folding the original provider charge into
  the job/run budget a second time.

## Verification

- Pure R0–R5 battery: 92 passed.
- R2–R5 isolated-Postgres battery: 12 passed.
- Retained Exa/Sumble/R4 database matrix: 22 passed.
- Final R5 plus replay-spend smoke after migration down/up: 4 passed.
- Migration `85595185f793 -> 5764311c620d -> 85595185f793`: passed; one Alembic head.
- Ruff passed on the R5 set; scoped mypy passed; repository-wide mypy passed 553 files; all 24
  import contracts were kept.
- Whole-worktree `git diff --check` remains blocked only by an unrelated user-owned blank line at
  EOF in `docs/architecture/clue-hq-content-and-artifact-scaling.md`.

## Acceptance boundary

- The executable account model observed the first Exa result, justified a separate Sumble Jobs
  call, formed a two-person same-office committee, completed coverage/finalization, settled 8.75
  cents across distinct fixture-provider operations, and created zero contact-research requests.
- No credentialed or paid provider call occurred. R10 owns bounded live Exa/Sumble acceptance.
- R6 owns production shared-fleet composition/cutover; do not register the R5 static resolver as a
  production shortcut.
