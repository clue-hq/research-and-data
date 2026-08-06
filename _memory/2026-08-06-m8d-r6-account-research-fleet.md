# 2026-08-06 — M8D R6 account research fleet and user return

## Outcome

- Added the action-scoped confirmed-direction compiler and exact account-fleet launch. It does not
  require the legacy outer `DEEP` phase and creates no `account_deep_launch`.
- Added deterministic canary hold/release, supervisor diagnosis, pause/resume/reprioritize,
  cancellation/no-resurrection, honest external wait and worker-failure suspension.
- Added scoped fleet/read/latest-return projections with account results, committee identities,
  spend, and review queue; account runs cannot initiate contact research.
- Added R2-R5 production composition with run-scoped provider-action factories; the R5 static
  resolver is rejected at this composition boundary. Each job persists its exact compatibility
  `account_run` binding so a fresh provider factory never selects a latest/ambiguous run.
- Corrected R5 Exa bundling to distinguish primary Exa fields from structured-primary fields that
  merely authorize Exa as a fallback.

## Persistence

- Migration `4ff507129dd5` follows `85595185f793` and is the single head.
- Added account-fleet control, per-job admission, append-only control events, immutable user-return
  snapshots, persisted source operation/action identity, and unique action replay authority.
- Launch compilation, compatibility account-run pins, R2 run/jobs, canary controls, and queue offer
  now commit atomically.

## Verification

- Pure R0-R6 battery: 92 passed.
- R2-R6 isolated-Postgres battery: 21 passed.
- Retained Exa/Sumble provider-durability matrix: 33 passed.
- Migration down/up and one-head check passed on `clue_roseau_r6`.
- Ruff passed; repository source mypy passed 556 files; 24 import contracts kept.

## Boundary

- No live credentialed or paid provider call occurred. R10 owns cutover and bounded live Exa and
  Sumble account/contact canaries.
- R7 remains the next slice and owns separately approved exact contact selection/launch.
