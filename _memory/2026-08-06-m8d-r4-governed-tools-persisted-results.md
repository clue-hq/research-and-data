# 2026-08-06 — M8D R4 governed tools and persisted results

## Outcome

- Implemented exact account/contact semantic-tool composition over the R3 `create_agent()`
  runtime. Model arguments contain intent only; all job/target/tenant/policy/budget authority is
  injected from the active task-local runtime.
- Added immutable governed tool requests and provider observations. A provider operation must be
  caused after reservation but before dispatch; replay/join observations never claim spend.
- Added complete persisted result/field/evidence projection and scope-bound lossless
  `read_research_result` / `read_evidence` tools.
- Reused Exa contact compilation, acquisition, snapshot/receipt, materialization, and claim
  services for the first concrete end-to-end semantic action. Replays spend zero; typed additive
  follow-ups create separate parent-linked operations.
- Added R4 result/value artifact subject bindings to contact DSAR erasure.
- Corrected the unreleased R2/R3 migrations and contracts to use the authoritative text IDs for
  workspace/project/product; runs/jobs/entities remain UUIDs.

## Persistence

- Migration `f643425d0be4` adds append-only request, provider-observation, result, result-field, and
  result-evidence tables plus cross-scope and chronology triggers.
- Stable evidence IDs may be indexed by multiple replay results; result occurrence identity is
  `(result_id, field_ordinal, evidence_ordinal)`.
- Complete results and separately indexed values are content-addressed artifacts. Raw response,
  normalized snapshot, provider results, receipt, cost settlement, claims, evidence, and lineage
  are all validated before success returns to the agent.

## Verification

- Focused R0/R2/R3/R4 and C3/C4 no-DB tests: green.
- Isolated Postgres dependency/regression battery: 63 passed.
- R4 test proves one fixture-provider call, complete indexed model result, lossless reads, zero-call
  replay, distinct additive follow-up, append-only rejection, exact scope, and DSAR purge.
- Causation callback failure leaves the operation planned with zero attempts/provider calls.
- Fresh database upgraded through R4; R4 down to R3 and up again passed; one Alembic head.
- Ruff and scoped source mypy: green.
- Repository-wide mypy: 549 source files green. Import contracts: 24 kept, 0 broken.
- Whole-repository pytest is blocked by two stale pre-R4 tests that still expect the R1-quarantined
  legacy account-deep launch/DEEP handler to run. Whole-repository format also reports unrelated
  files; none was changed for R4.

## Boundary

- No credentialed or paid provider call occurred. R10 owns bounded live-provider acceptance.
- R1's fail-loud production quarantine remains. R5 owns account-agent behavior and concrete
  account/organization-map/committee tool composition; R9 owns atomic job-budget admission and
  reconciliation.
- Existing unrelated worktree edits were not staged.
