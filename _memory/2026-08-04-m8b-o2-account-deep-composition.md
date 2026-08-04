# M8B O2 full account-deep composition

## Outcome

O2 is mechanically complete on `platform/c8-account-profiling-integration`. Discovery/tier
approval still does not start deep research. `launch_account_deep@1` creates the separate durable
authority for one exact selected set, then re-enqueues the existing project fleet. The existing
per-account `AccountDeepOrchestrator` remains provider-neutral and sequences account profiling,
Sumble committee preparation/materialization, and bounded contact fan-out.

## Implemented

- Added immutable `account_deep_launch` and `account_deep_launch_account` receipts (Alembic
  `a83e52bebc7c`) carrying project/run/workspace, exact directive version/digest and effective
  account pins, selected membership, canonical request digest, reviewed estimate, approved budget,
  actor/action, and operation reference. Exact replay survives directive supersession; changed
  inputs conflict. Money scale is canonicalized for replay identity.
- Added `launch_account_deep@1`, typed output, full-unit committee capability precondition, and
  Head-of-ABM v17 authority. Tier-checkpoint submission no longer re-enqueues when it transitions
  to DEEP; launch is the explicit spend boundary. Fine-grained account/committee/contact tools are
  unchanged.
- Production DEEP selection reads the immutable launch instead of ephemeral phase params, rechecks
  human-approved tier evidence, and propagates the effective directive and account budget into the
  account plan/run, profiler, committee worker, and contact admission.
- Added production Exa preparation: compile through the canonical field planner, validate/freeze
  the exact plan through the shared pre-spend gate, acquire durably outside claim transactions,
  map provider wait/failure, and bind only verified E2 snapshots into the account task.
- Added production Sumble committee inputs derived from the exact launch/account-run/directive,
  sealed membership, human tier, verified successful S1 organization snapshot, committee/privacy
  policy, and effective budget. The request remains bounded and forbids contact reveals.
- Composed one shared pre-spend gate, Exa provider, Sumble preparer, toolbelt, run driver, fleet,
  and existing account orchestrator at the production root.

## Findings fixed during real-DB acceptance

- Fresh Exa preparation initially loaded only an already-frozen effective plan, but on a first
  launch that row does not exist until the first gate. Preparation now asks the same deterministic
  planner for canonical authority and lets the gate remain the sole freeze owner.
- The Sumble input resolver initially assumed a nonexistent S1 `ready` state; the actual terminal
  state is `succeeded`. The resolver now uses the durable repository helper rather than raw SQL.
- `AccountRunRow` omitted `budget_cap_cents` from decoding, so persisted launch authority could not
  be proven on replay. The value is now selected, decoded, and exact-checked.
- Launch preview now requires one exact tier-1 human selected claim matching the run and effective
  effort tier; production resolution requires the same launch pin and tier.
- Exa preparation no longer treats the first ready snapshot as proof that a split acquisition
  plan is complete. It recompiles the exact plan and reconciles every bundle, so a crash between
  bundles cannot silently materialize partial research; ready bundles still replay without HTTP.
- The full-suite audit exposed stale catalog, authority-count, and Stage-0 surface expectations for
  Head-of-ABM v17 / `launch_account_deep`; those repository-wide contract tests now cover O2.

## Verification

- Real PostgreSQL O2/prerequisite/composition verification: 123 tests passed (A1, A2, E1, E2,
  S1, S2B-D, O1, O2, composition, toolbelt, active agent profile, authority audit, and Stage-0
  surface isolation).
- O2 acceptance proves explicit launch/enqueue, zero enqueue at tier approval, immutable replay,
  supersession replay, account budget propagation, one Exa fake-boundary call plus zero-call
  snapshot replay, and S1-backed no-reveal Sumble inputs.
- Alembic reports one head (`a83e52bebc7c`) and completed head -> base -> head on a clean database
  inside the isolated `clue-roseau-o2-postgres` container. A first attempt against the data-bearing
  test database stopped at the older C5.3 downgrade guard because tests had intentionally created
  execution nodes; no bypass or destructive cleanup was used.
- Mypy passed all 513 source files; import-linter kept all 24 contracts; Ruff format/check passed
  every O2-owned Python file.
- No new paid/live provider call was made; separately authorized successful Exa and Sumble canaries
  remain open.

## Next

O3 owns conversational research preview/edit/confirm/launch/narration behavior and evals. V0 still
owns the remaining combined fault matrix; successful paid canaries remain separate authorization.
