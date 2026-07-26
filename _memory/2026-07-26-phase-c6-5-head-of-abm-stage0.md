# 2026-07-26 — C6.5 Head-of-ABM Stage-0 vertical

## Outcome

C6.5 is complete on `platform/c6-deepagent-runtime`. The real Head-of-ABM deepagent can now run
the governed Stage-0 vertical over C4/C5 with exact resources, nine minimal tools, per-role model
construction, isolated workspace access, exhaustive capability disclosure, and honest durable
finalization. No public route, feature flag, canary, or ownership cutover was added; C6.8 retains
that responsibility. C6.6 is next.

## Implemented

- Added immutable `head-of-abm@v2`, prompt v2, and `stage0-interview@v3` resources. The old v1
  resources remain unchanged for historical replay; production selects exact versions explicitly.
- Reduced the promoted Head direct surface to onboarding, recon, interview evidence, readiness,
  ICP synthesis, field/source proposal, ingestion, and confirmed-run start. Human confirmations,
  readiness override, proposal decisions, budgets/checkpoints, post-Stage-0 tools, and delegation
  are structurally absent.
- Generated an exhaustive host-free map for all 32 platform tools plus framework, workspace,
  model, resource, delegation, and unavailable-capability facts. The runtime appends this map last
  after DeepAgents framework prompt middleware.
- Added exact-surface middleware that removes the framework's default `task` subagent until C6.6,
  rejects fabricated/unexpected capabilities, and fails if the backend exposes execution.
- Added `HeadOfAbmStage0Runtime` and its execution builder. One execution-bound C5 adapter owns
  governed tools, model loop, exact resource pins, durable receipts, recovery, and finalization.
- Added Recipe #0 v3 with replay-certified field/source proposal and ingestion tools plus
  proposal/ingestion policy pins. Proposal identity is complete scope plus immutable payload hash;
  ingestion identity is workspace plus artifact-content and declared-context hashes.
- Extended the agent compiler to resolve and validate the same `Stage0StepPinProvider` requests
  used by direct Recipe #0 before dynamic-node append.

## Authority and behavior decisions

- The agent decides which material gap is useful to ask next. It does not declare deterministic
  evidence sufficiency or readiness.
- Product confirmation, ICP confirmation, and readiness override remain human-only. The Head can
  request those actions and report their absence but has no corresponding model tool.
- `start_confirmed_project_run` is the only Head start path and revalidates confirmation and
  readiness/override lineage before Recipe #1.
- The standalone C1 coverage evaluator is not duplicated in Stage 0. Its final C6.7 ownership
  decision remains open; `research_account_gaps@1` stays replay-blocked and absent.
- Specialist roles are not activated early. The Head v2 has no delegation and DeepAgents'
  general-purpose subagent is removed until C6.6.

## Failures found and resolved

- The initial vertical wrapper accepted a preconstructed runtime that could have been bound to a
  different execution adapter than its governed tools. It now accepts the model provider and
  constructs `DeepAgentTurnRuntime` per turn with the exact same adapter.
- The C6 agent path originally compiled through C5 but omitted C4/Recipe-0 resource-pin
  resolution. It now resolves, validates, and forwards exact dynamic pins before execution.
- A C6.4 delegation DB regression inherited the newly promoted non-delegating Head v2. The test
  now explicitly resolves historical Head v1, preserving the frozen C6.4 contract without
  broadening production C6.5 authority.
- The full suite found the C6.0 authority audit still treating the three newly certified tools as
  blocked. The standing audit now separates the four current residual blocked tools from the
  C6.5 certifications.
- Re-running the full DB suite on the same populated throwaway schema correctly triggered the
  C5.3 downgrade safety guard and source-registry redefinition checks. Resetting only the isolated
  test schema produced the required clean pass. One attempted inline schema-reset command had a
  Python syntax error; the repository `make db-fresh` target was used instead.
- `make check` would include unrelated user-owned `.claude/` and `.codex/` scripts. The equivalent
  repository gate was run with only those directories excluded; no user-owned files were changed.

## Verification

- Ruff format/check: green across 845 files, excluding only unrelated `.claude/` and `.codex/`.
- Mypy: green.
- Import-linter: 24 contracts kept, 0 broken across 475 files and 3,368 dependencies.
- DB-enabled full repository suite: all 2,589 collected tests green on a clean dedicated Postgres
  instance; expected skips only.
- Focused C4/Recipe #0 parity, crash recovery, and C6.4 delegation/finalization DB tests: green.
- One Alembic head: `6628a407e993`.
- Clean isolated `make db-smoke`: head to base to head green.
- No C6.5 migration was added.

## Next

Proceed with C6.6 only: activate the research, content-drafter, and reviewer specialist profiles
through the already durable fresh-wake delegation contract. Define exact task/ref/path grants,
role-specific model and workspace policy, durable-before-return behavior, parent/child spend
rollup, and gate parity. Do not add C6.8 product routing or canary ownership early.
