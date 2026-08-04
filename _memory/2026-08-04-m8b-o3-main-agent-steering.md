# M8B O3 — Main-agent account-deep planning and steering

## Outcome

O3 is complete mechanically on `platform/c8-account-profiling-integration`. It adds the
conversational control plane around A2 directives and O2 launches without introducing a project
phase, automatic discovery-to-deep transition, provider-specific agent, or new engine authority.

## Implemented

- Promoted Head-of-ABM v18 with prompt v4 and progressively disclosed
  `account-deep-steering@v1`; promoted research-specialist v5 with `research-task@v2`.
- Added an API-root current-state compiler/materializer for one project run. It reads the tier
  checkpoint, newest exact directive and overrides, immutable launch receipt/membership, canonical
  accounts, and current account-run cursors, then persists an immutable steering card plus the
  exact directive as project context artifacts.
- Kept the context read-only: it performs no confirmation, transition, launch, enqueue, provider
  call, claim write, or status inference. Directive subject bindings use only exact directive
  membership; the wider steering card uses the union it actually describes.
- Added stable model-facing descriptions to governed tool descriptors without changing input or
  output schemas. Draft is described as non-spending/non-confirming; launch success is explicitly
  receipt/enqueue/replay rather than completed research.
- The Head skill covers show-only, discover-more, working previews, standard fields versus
  hypotheses, account/source/committee/privacy edits, explicit launch, edits after launch, and
  truthful waiting/running/completion narration. The current single reveal flag is stated
  honestly: removing phone reveals disables both email and phone in this no-reveal slice.
- The research skill separates pre-launch plan review from admitted execution and requires the
  exact directive and current steering-card artifacts rather than a parent paraphrase; the
  fresh-wake delegation seam grants both automatically when present.
- Added seven scripted behavior fixtures plus registry/runtime/context acceptance tests.

## Verification

- O3/catalog/runtime unit set: `40 passed`.
- Real-Postgres A2 + O2 + O3 regression set: `7 passed` against the isolated Roseau database.
- Ruff format/check: passed for all touched Python files.
- Mypy: passed across 515 source files.
- Import-linter: 24 contracts kept, 0 broken.
- No live model, Exa, or Sumble call occurred and no provider spend was attempted. Live
  conversational and provider canaries remain V1-owned; the broader fault matrix remains V0-owned.

## Operational notes

- `uv run` was unavailable because the sandbox could not access the user-level uv cache; the
  repository `.venv` entry points were used instead.
- A globally named sibling `clue-postgres` container prevented creating another compose service.
  Verification used the already isolated Roseau Postgres endpoint from this worktree's `.env` and
  did not stop or mutate the sibling container.
