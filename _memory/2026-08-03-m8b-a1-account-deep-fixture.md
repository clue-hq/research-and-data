# 2026-08-03 — M8B A1 account-deep synthetic handoff fixture

## Scope

- Implemented only M8B Slice A1: the additive synthetic Level A/Level B handoff and its offline
  acceptance paths. No Exa, Sumble, model, email/phone reveal, migration, or external spend ran.
- Kept the existing `AccountDeepOrchestrator` and provider-neutral resolver / `CommitteeSource`
  seams. The fixture does not introduce a pipeline, phase, fleet, or provider-specific orchestrator.

## Implemented

- Added `platform/api/clue_api/trial/account_deep_fixture.py` with a separate versioned
  gastroenterology deep ICP, versioned healthcare source override without Parallel, canonical
  synthetic account, complete Exa-Websets-shaped sealed generation, terminal required fields,
  must-have evidence, committed discovery/scoring/human-tier checkpoints, and a second project run
  ready at DEEP.
- Added one frozen fixture research directive with referral/fax/phone/DAC hypotheses and a bounded
  no-reveal committee plan. It is explicitly an A1 double, not A2's future production authority.
- Captured content-addressed, network-free Sumble Jobs/Technology/Teams/People and Exa Deep
  provider artifacts. Recorded account resolvers and an exact-account committee source bind behind
  existing seams; committee candidates use LinkedIn as the strong identity key and contain no
  email/phone reveal.
- The fixture never pre-creates `account_run`; the full production-entry test proves the real
  scheduler/handler/orchestrator creates and completes it. Replay is read-only and creates no
  provider calls, claims, contacts, or equivalent execution state.
- Repaired the pre-existing discovery fixture readiness replay comparison to include the resolved
  tenant-local readiness-policy metrics that `evaluate_readiness` now persists. This does not
  change the original fixture ICP or project run.

## Acceptance and decisions

- `tests/api/test_account_deep_fixture_a1.py` covers additive fixture lineage/replay, original
  shallow-ICP zero-gap behavior, four direct account gaps, full production entry, two admitted
  committee members, durable account-run completion, and replay without calls/writes.
- The real production pre-spend gate exposes a pre-existing plan mismatch: operational pain and
  strategic moves only sanction tier 4 in the shared field registry, but the healthcare override
  offers the tier-2 official source first. A1 asserts the fail-closed rejection; it does not weaken
  the gate or rewrite shared field definitions. E1/O2 must reconcile the field/question-specific
  effective source plan before live Exa acceptance.
- Verification: A1 3/3 passed; original discovery fixture plus deep composition/orchestrator
  regression selection 32/32 passed; A1-scoped Ruff passed; mypy passed across 499 source files;
  import-linter kept 24/24 contracts. The test module restores any pre-existing resolver bindings,
  so its Sumble/Exa doubles do not leak into later tests.
- The repository-wide `make check` is not green for pre-existing, out-of-scope reasons: Ruff names
  14 older files needing format; the full suite first hits the stale C6.4
  `evaluate_stage0_readiness@1` profile digest, and with that test deselected later hits an
  order-dependent clue-obs stdlib bridge test (the clue-obs test passes alone). These files were not
  changed. The exact A1 and adjacent regression gates remain green.

## Remaining M8B work

1. A2 durable directive, preview, confirmation, memory submission, and context binding.
2. Exa E0-E2 wire/acquisition/snapshot materialization.
3. Full O2 set-scoped launch composition, then O3 main-agent preview/steering behavior.
4. V0 offline combined acceptance and separately authorized V1 provider canaries/replay.
