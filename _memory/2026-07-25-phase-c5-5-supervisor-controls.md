# C5.5 — supervisor, controls, and deep canary

## Final state

- Branch: `platform/c5-recipe-execution`.
- Added versioned `SupervisorPolicy` with deterministic thresholds, sample floors, cooldowns,
  automatic-action allowlists, scope caps, envelope bounds, and bounded triage pins.
- Added run-scoped physical source-call telemetry keyed to execution/project/account/source. The
  waterfall records produced/empty/failed outcomes and exact source keys are present on every
  production pre-spend request.
- Added `ApiRunAggregateReader` over M13.4 progress/cost/verification/coverage, C1 coverage state,
  fleet/account stalls, execution failures, and the new source telemetry.
- Added deterministic observations and one optional closed-schema LLM diagnosis leaf. Malformed,
  low-confidence, and out-of-envelope advice is durably rejected and replayed without a second
  model call; diagnosis never acquires control authority.
- Added append-only, operation-idempotent control events for account quarantine, source breakers,
  runtime-envelope tightening, and escalation. Control ownership, observation/diagnosis lineage,
  actor authority, cooldowns, scope caps, and monotonic envelope reductions are enforced at write.
- Automatic-control validation resolves the exact project run's ICP policy. Execution ownership is
  checked before operation replay, so a known operation id cannot bypass workspace isolation.
- Account quarantine is read by the fleet scheduler and parks a governed-partial result; release
  explicitly reoffers it. Source breakers reject the exact source before the existing pre-spend
  gate/provider boundary. Runtime envelope overlays affect future executor node/depth/fan-out.
- The existing deep handler now executes a stable tier-priority canary, evaluates the supervisor
  gate, and opens the unchanged remainder only on pass. Failure applies only permitted controls,
  pauses deep, and preserves unrelated sources/executions.
- Registered typed, operation-id-required toolbelt tools for apply/release/acknowledge control
  actions and wired production fleet composition without creating a second deep pipeline.

## Schema

- Migration `ed7a01cd8845` adds run-control operation identity, supervisor query/uniqueness indexes,
  run-scoped `source_call_observation`, C1 project-run indexes, and append-only enforcement.
- Exactly one Alembic head remains.

## Verification

- Repository Ruff format/lint passed across project files.
- MyPy passed across 392 source files.
- All 24 import contracts passed.
- Clean DB-enabled repository suite: `2432 passed, 20 skipped`.
- Focused control-policy regression: 3 tests passed, including exact ICP-policy resolution and
  workspace-before-replay enforcement.
- Clean migration smoke passed: upgrade to head, downgrade to base, upgrade to head.
- `git diff --check` passed.
- Untracked user-local `.claude/` and `.codex/` directories were preserved and excluded from the
  repository lint invocation.

## C5.6 handoff

- Recipe #1 remains a non-executable placeholder.
- C5.6 must append/promote an executable revision, consume Recipe #0's confirmed-run lineage,
  atomically claim `project_run_execution_owner`, route only eligible new runs behind a feature
  flag, preserve legacy-run fallback/resume, expose recipe-aware run views, and prove normalized
  outcome parity against the fixed driver.
