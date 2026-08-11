# Stage-0 and project-chat hardening

Date: 2026-08-11
Branch: `platform/stage0-project-hardening`
Base: Singapore head `8949058f46ddfbcefede85abacfc503fb60dc61c`

## Scope and evidence

- The current worktree was already clean, on the requested branch, and at the
  exact current Singapore head. Singapore's unrelated `.env.example` edit was
  left untouched.
- Primary defect evidence: `.context/defect-log.md` and
  `_memory/2026-08-11-lane-f-browser-e2e.md`.
- Fixture procedure: the supplied attachment describing the replay-safe
  Insight Health/Aura AI fixture from commit `227d1fa3`.
- The browser probe reached real Stage-0 interview writes but found no
  `icp_spec`, no durable `agent_gate`, model-supplied zero readiness metrics,
  and a focused Slate editor that retained submitted text.

## Ratified implementation boundary

1. Governed synthesis persists draft, versioned `icp_spec` records and returns
   their durable refs.
2. ICP confirmation is a durable gate over an exact stored spec snapshot. The
   gate stores its permitted decisions and human addressee.
3. Structured gate answers verify the expected digest and decision before the
   immutable receipt is written; approval activates only that draft version.
4. Readiness is compiled from product-scoped Client-KB claims and labels its
   revision as a readiness-policy version.
5. Only supported, fetched durable gates render controls. Thin/model-only refs
   are notices.
6. The frontend also clears focused Slate state, repairs workspace sizing and
   overflow, collapses empty Gallery with a reopen affordance, displays the
   workspace name, and uses a durable derived/explicit project name.

## Verification plan

- Focused domain/tool/gate/auth/chat tests and migration up/down/up.
- Frontend model/repository/component regressions, design-system build, lint,
  tests, and webpack production build.
- Replay the supplied Insight Health fixture in a fresh paired DB/filesystem,
  then verify browser -> API -> Postgres for synthesis, gate answer, ICP status,
  readiness metrics, project title, and composer behavior.

## Open state

- The founder approved Slice 0 only. The contract amendment is ratified; Slices
  1-6 remain pending and must not be implemented without the next instruction.

## Slice 0 closeout — contract and test foundation

- Added unregistered strict contracts in
  `platform/api/clue_api/stage0_project_contracts.py` for
  `evaluate_stage0_readiness@2`, `synthesize_icps@2`, durable draft ICP refs,
  exact ICP-confirmation gates, and structured digest-bound answers. Historical
  `@1` contracts remain unchanged for replay.
- Added schema fingerprints and forbidden-old-shape tests. Model-authored
  readiness metrics/scope, transient synthesis outputs, `human_only` subjects,
  stale digests, and incomplete permitted decisions are rejected.
- Updated the active-skill materialization test to read the resolved Stage-0
  skill bundle's `materialized_path`; it no longer hard-codes v9 or v10.
- Repaired the durable-turn acceptance fixture by using the production
  `TurnLayerSource` for L7. L6 remains append-only conversation; the exact
  current user-message artifact is the sole required L7 instruction.
- Ratified and expanded the source-of-truth frontend project contract. No tool
  registration, migration, runtime behavior, or frontend control changed.

Verification on a dedicated migrated database
`copenhagen_stage0_slice0_20260811`:

- owning contract/registry/context/durable-turn suites: 49 passed;
- Ruff format/lint on changed Python: green;
- mypy on the new contract module: green;
- import-linter: 25 kept, 0 broken;
- `git diff --check`: green.

The first `make contracts` attempt was blocked by sandbox access to the existing
uv cache; the same command was rerun with approved access and passed.

The repository-wide `make check` completed Ruff, mypy (632 files), and all 25
import contracts, then was stopped after the pytest phase crossed known
out-of-scope red boundaries: 4 failed, 1,306 passed, and 1,081 skipped at the
stop point. Three pilot-budget tests hit the existing shared-database lifecycle
problem after `field_definition.research_scope` disappeared (LF-TEST-001), and
the root logging test crossed the excluded design subtree (LF-TEST-003). These
were already recorded in `.context/defect-log.md`; Slice 0 does not weaken or
repair those separate tests.
