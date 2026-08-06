# 2026-08-03 — M6A D5 post-review repair

## Scope

- D6 remains unimplemented and out of scope. This repair addresses only the three accepted D5
  review findings.
- Added the explicit ICP policy `scoring_mode=disabled` plus
  `selection_mode=discovery_criteria`; retained the durable SCORING and human TIER_CHECKPOINT
  phases without Pass-A provider calls or numeric fit/intent claims.
- Hardened `ScoreAccountsTool` and the PostgreSQL phase sequence against the seal-to-phase crash
  window and direct phase skips.

## Binding behavior

- The sealed reader now verifies and returns the exact claim manifest, all D4 item-rooted claims,
  immutable plan criteria, required account fields, and terminal field-resolution decisions.
- The normalized policy criteria must exactly equal the immutable plan criteria. Any drift fails
  closed.
- All criteria `yes` plus all required fields `resolved` selects; any `no` excludes; any
  `unclear`, absent criterion, confirmed-missing field, or conflict holds.
- The checkpoint exposes criterion reasoning/references/evidence claim ids and may approve all
  selected accounts or a selected subset. Only approved selected accounts receive a human-source,
  seal/run/ICP/policy-bound tier claim with `decision_basis=discovery_criteria`; no numeric score is
  synthesized.
- Deep composition accepts only the current run's matching criteria-selection tier claim.
- `ScoreAccountsTool` checks persisted phase=SCORING and status=ACTIVE both before and immediately
  before invoke.
- Migration `3f41f54d6238` enforces discovery -> scoring -> tier_checkpoint -> deep, requiring the
  committed scoring checkpoint and the approved/resumed committed human checkpoint.
- The Insight Health/Aura fixture is version `@2` and explicitly opts into the bypass policy. Its
  old scoring rubric remains dormant versioned data for a future explicit mode switch.

## Verification

- Isolated real PostgreSQL acceptance: 53 focused D4/D5/scoring/checkpoint/deep/tool/fixture tests
  passed. The strengthened D5 test proves each forbidden skip and the sole valid committed path to
  DEEP.
- Alembic has one head (`3f41f54d6238`) and the new migration passed downgrade one revision then
  upgrade to head.
- Ruff changed-file checks passed; mypy passed for 470 source files; all 24 import contracts held.
- A wider failure rerun left two unrelated pre-existing failures: the Stage-0 memory substrate
  import guard and a Sumble fixture string classified as secret-shaped.
- Both exact disposable databases named `clue_d5_repair_20260803` (host and `clue-postgres`) were
  verified at zero connections, dropped after testing, and confirmed absent. They are not
  recoverable and contained no user data.

## Follow-up

- D6 still owns confirmed ICP -> plan -> live Exa submit -> complete production-composition
  acceptance. Do not treat this mechanical/DB-backed D5 repair as D6 evidence.
