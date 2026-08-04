# 2026-08-05 — M8B V1 live acceptance attempt

## Outcome

- V1 remains open. No authenticated Exa, Sumble, or OpenRouter request was made.
- The checkout has blank/absent Exa, Sumble, and OpenRouter credentials; both paid provider flags
  are default-off; production stub mode is correctly disallowed.
- Detailed evidence is in `docs/specs/M8B-V1-live-acceptance.md`.

## Verification completed

- Created isolated `roseau_v1_9b3f7d2c4a61` and migrated it to single head `a83e52bebc7c`.
- Slice-owned A0–O3/V0 surface: 170/170 passed, including the 32-case V0 manifest and fresh-process
  concurrent replay.
- Full suite: 3,337 passed, 11 skipped, 0 failed (3,348 collected).
- Mypy: 515 source files; import-linter: 24/24 contracts; tracked Ruff: 1,073 files.
- Broad Ruff additionally found only intentional `print` statements in user-owned untracked
  `.claude/` and `.codex/` skill copies; do not edit them.
- Isolated DB inspection showed zero external/committee operations, launches, gate decisions, or
  model calls. Twelve fixture claims were left by committing tests only.

## Release blockers proved

1. No live credentials or provider authorization flags are configured in this checkout.
2. A1 uses `cascade-gastro.example` and fixture Sumble identities, so it is not a live target.
3. No shipped executable joins O3 Head-of-ABM conversation to O2 launch. Stage0Trial runs the Head
   agent but withholds `launch_account_deep`; fleet_main composes launch/providers/fleet but no Head
   turn surface; `prepare_account_deep_steering_context` is called only by its test.
4. Current Sumble v9 OpenAPI is reachable but its raw digest changed from the pinned S2 digest to
   `c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c`. The v9 Teams/People paths
   remain, but the delta must be reviewed before paid traffic; public docs now lead with v3.
5. Sumble cents-per-credit is zero and account-agent routing is disabled.

## Resume rule

Do not call M8B complete from offline evidence. Resume only after credentials are configured in
Roseau, the v9 subset is re-frozen, a real target/S1 identity exists, and one production-composed
Head turn can invoke O2. Then run Exa-only, Sumble-only, combined fleet, and fresh-process replay in
that order with explicit caps and inspect durable requests, artifacts, receipts, spend, claims,
verification, committee, projections, and zero-spend replay.
