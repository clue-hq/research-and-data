# Phase C1 — coverage and goal judge

Date: 2026-07-24
Branch: `platform/c1-coverage-goal-judge`
Base: C0 contract-freeze commit `421848f`
State: implemented and committed at `bae135a`; annotated checkpoint tag
`phase-c1-coverage-goal-judge-v1`

## Implemented

- Added the frozen C1 core IDs, attempt/terminal enums, and reference-only
  `ResearchGapRef`.
- Added validated, data-driven `ResearchLoopPolicy` defaults and transitions.
- Added reversible migration `2211464d398f` with append-only
  `coverage_attempt` and `coverage_decision` ledgers, idempotency constraints,
  workspace ownership, and a one-terminal-decision invariant.
- Added the research coverage package:
  - workspace-scoped ledger repository;
  - four stable, distinct research-strategy bands;
  - bounded round enforcement controller;
  - strict structured-output LLM goal evaluator with injection fencing;
  - offline useful-retry and honest-stop goldens.
- Authority correction after implementation review:
  - the governed C6 research agent is the primary planner for gaps and strategy;
  - before C6, the explicit tool caller owns those choices;
  - the engine validates caller-selected strategies against versioned transitions
    and owns budgets, policy, evidence, idempotency, and hard terminal states;
  - the goal evaluator only assesses whether requested gaps still appear
    meaningful and returns typed advisory warnings/recommendations;
  - evaluator output has no executable gap/source/strategy field and cannot
    create a terminal decision;
  - even a valid `propose_stop` assessment stays advisory and leaves an
    otherwise permitted retry non-terminal;
  - malformed evaluator output is recorded as advisory-unavailable and cannot
    stop an otherwise engine-permitted retry.
- The controller enforces per-account/per-run budgets and the existing
  pre-spend gate before provider work, records attempt and judge cost, re-reads
  returned claim references through the workspace boundary, and only counts
  structurally promotable claims as fills. Contact retries require the
  claim-tagger integration seam.
- Added the lane-local frozen `research_account_gaps` v1 tool implementation
  with durable run/account/tier/plan validation and entity single-flight.
- Added lane-local read-only `research_coverage` and
  `research_attempt_history` projections; neither exposes claim values.
- Added the optional waterfall attempt-observation hook without changing
  existing callers.
- Added C1 unit, DB, controller, projection, and waterfall-hook tests.

Per the C0 ownership treaty, central toolbelt registration and central
projection exports remain integration-owned and were not edited in this lane.

## Future C6 evaluator-placement flag

Product direction recorded after the C1 checkpoint: the advisory coverage
evaluation will probably move inside the platform deepagent or governed
research subagent when C6 lands.

This is an open placement decision, not a change to current C1 behavior. C1
keeps the bounded `LLMGateway` leaf call so its typed assessment and safety
boundaries remain executable before the agent exists. At C6:

- explicitly choose one evaluator owner;
- do not run both an engine-side evaluator and an agent-side evaluator;
- if it moves into the agent, remove or disable the standalone C1 evaluator
  call rather than duplicating its judgment;
- preserve agent planning authority and engine authority over promotable
  evidence, budget, policy, idempotency, and hard terminal states;
- preserve the append-only coverage ledger and reference-only contracts;
- keep malformed advice and `propose_stop` non-terminal by themselves;
- decide how agent-local advice is journaled/projected without making it
  authoritative durable state.

Until C6 closes this decision, the committed C1 leaf-call implementation is the
current contract.

## Verification

Using an isolated PostgreSQL/pgvector 16 container at port 55433 because the
shared Docker Compose container name was already owned by the `dar-es-salaam`
workspace:

- C1 unit tests after the authority correction: `9 passed`.
- C1 plus waterfall tests after the correction, twice: `44 passed` each run.
- `make check`: Ruff formatting/lint green, mypy green across 337 source files,
  23 import contracts kept, full suite `2272 passed, 20 skipped`.
- Immediate full `pytest -q` rerun: green.
- `make db-smoke`: clean upgrade -> downgrade base -> upgrade head green.
- `alembic heads`: exactly `2211464d398f (head)`.
- `git diff --check`: green.

The initial `docker compose up` attempt failed only because Docker container
`/clue-postgres` already existed under the sibling workspace; it was not
modified or removed.

## Handoff

- On Phase-C integration, register the C1 tool and projections only after the
  lanes are combined, per the C0 contract freeze.
- When C6 connects the governed research agent, pass its chosen gap set and
  strategy hint into `research_account_gaps`; never derive either from the goal
  evaluator's result.
- Preserve the append-only and reference-only boundaries when wiring later
  C2/C3 consumers.
