# 2026-08-03 — M6A D5 discovery seal and phase barrier

## Outcome

- Implemented Slice D5 on `platform/c8-exa-sumble-discovery` in commit `e0a49cd`.
- Acceptance contract: `docs/specs/M06A-D5-discovery-seal-phase-barrier.md`.
- Migration: `0567b5fdf1ad` (`413e800f79b5 -> 0567b5fdf1ad`, one head).
- D5 performs no provider call and introduces no Exa/Sumble spend.

## Binding behavior

- The exact current discovery generation must satisfy all fourteen D1 readiness predicates before
  one canonical relational manifest bundle and one seal can commit.
- The four content-addressed manifests pin account membership, claim ids, raw provider artifacts,
  and non-exhaustive coverage. Replays reuse identical rows/blobs; divergent content fails.
- A PostgreSQL trigger rejects `discovery -> scoring` unless the current batch, seal, manifest,
  four live artifact rows, and committed checkpoint all share exact run/project/ICP lineage.
- Every durable batch is non-deletable. Failed/cancelled/replaced generations and their children
  remain frozen; only the one-time replacement lineage edge is allowed.
- Pause suppresses wake claiming; resume folds existing operation state; cancel retires wakes;
  replacement creates only the next serialized generation.
- Late sealed events are stored as `late_after_seal`; terminal-old-generation events are stored as
  `superseded`. Neither enters the manifest.
- Production run composition is always seal-aware once a durable batch exists, independently of
  the Exa provider activation flag. D4 re-enqueues the owning run after materialization.
- Scoring receives exact account ids through `SealedDiscoveryAccountReader`; mutable discovery
  provenance outside the sealed manifest is ignored.

## Verification

- Dedicated real PostgreSQL database `clue_d5_test_20260803` plus filesystem artifact storage.
- 98-test D1-D5/phase/scoring regression selection passed; one explicitly opt-in test skipped.
- Each of the fourteen blockers independently rejected both sealing and the project transition.
- Active-batch deletion, direct transition, missing/erased blob, late-event mutation, pause/cancel/
  replace, replay, and sealed-only scoring membership were exercised.
- Full migration graph passed `head -> base -> head`; D5 acceptance passed after rebuild;
  `alembic heads` returned only `0567b5fdf1ad`.
- `mypy`: 469 source files clean. `lint-imports`: 24 kept, 0 broken. Changed-file Ruff clean.
- The same D5 acceptance passed against the workspace's existing local development database after
  non-destructively aligning the finalized guard functions.
- The exact disposable database was verified to have zero connections, dropped after testing, and
  confirmed absent. It contained no user data and is not recoverable.

## Environment notes

- The shared development database contains 521 pre-existing account fixtures. Older scoring tests
  that assert the global table begins empty report 522/523 accounts there, and a D4 deterministic
  review fixture can collide with prior durable state. The identical suite passes on the required
  clean per-branch database; no shared fixture data was deleted.
- A broader pre-existing suite failure remains outside D5: the frozen
  `evaluate_stage0_readiness@1` Agent Profile schema digest is stale. Do not fold that correction
  into M6A.
