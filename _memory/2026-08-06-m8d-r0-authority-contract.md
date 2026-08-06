# 2026-08-06 — M8D R0 authority contract and forbidden-flow battery

## Outcome

- Implemented R0 only; no R1 runtime quarantine or replacement work started.
- Added `clue_core.entity_research`, an isolated shared-kernel contract module with no provider,
  database, runtime, or agent-construction side effects.
- Froze exact component ownership: one Head-of-ABM deepagent, one subject-neutral fleet and job
  controller, one account and one contact `langchain.agents.create_agent()` class, bounded facet
  agents, and provider dispatch only through an engine service.
- Froze exact account/contact selection and job scope, including non-committee contact selection;
  separately confirmed run lifecycles; field/source authority; governed tool requests; lossless
  persisted results; provider causation; facet/concurrency limits; and engine-only finalization.
- Added a canonical valid fixture, 13 public JSON-schema fingerprints, and a 56-case forbidden-flow
  battery. Forbidden payloads must fail for their named reason while the suite stays green.
- Added `docs/specs/M8D-R0-authority-contract-acceptance.md` and marked only R0 accepted in M8D.

## Verification

- Focused R0 suite: 60 passed.
- Core plus existing agent contract/catalog regression: 115 passed.
- Ruff format/check passed for scoped Python files.
- Mypy passed for the contract module and R0 tests.
- Import-linter: 24 contracts kept, 0 broken.
- `git diff --check` passed for scoped files.

## Scope boundary / next work

- No model, database, external provider, credential, or paid call was used.
- No active profile, recipe, composition, orchestrator, controller, provider transport, claim path,
  migration, or environment flag changed.
- Existing unrelated dirty worktree files were not staged or modified by R0.
- R1 remains the next slice and owns dependency-guided quarantine of forbidden active paths. R0
  does not claim the current runtime is already compliant with the frozen contracts.
