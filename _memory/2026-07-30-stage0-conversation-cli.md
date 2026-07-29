# 2026-07-30 — Stage 0 conversation CLI

## Goal

Give the founder a real, no-frontend quality trial of conversational Stage 0 before Exa, website
scraping, API, or full end-to-end testing. The trial must not preload the Gastro campaign or any
campaign directory; it learns company/product/project/ICP context from the user conversation.

## Implemented

- Added `scripts/00_stage0_trial.py` and API-root composition in
  `platform/api/clue_api/stage0_trial.py`.
- New sessions create an isolated workspace/brand/product-candidate/project/client identity and a
  zero-budget, `max_source_tier=0` Client-KB marker. The website is identity-only and is not fetched.
- Each turn runs through the active Head-of-ABM profile, C5 Recipe 0, C6 deepagent runtime, governed
  Stage-0 tools, durable artifacts, thread history, and scoped-memory assembly.
- The current user artifact key/digest is supplied as trusted context so the agent can call
  `submit_onboarding_input` and route exact quote offsets through `record_interview_answer`.
- Added a connection-bound `stage0_memory_write_factory` composition seam so memory writes share
  the Stage-0 tool transaction rather than committing independently. The executable script—not
  the API package—binds the private memory implementation, preserving the two approved core seams.
- After material interview claims, the harness runs a zero-acquisition reverse-profile refresh
  carrying current governed client claims as volunteered materials. This publishes the next
  immutable Client-KB version that ICP synthesis actually reads while preserving the original
  interview claim and statement lineage.
- Added human commands for product confirmation, inspectable ICP synthesis, and ICP confirmation.
  ICP proposals are saved locally and injected into the next frozen stage snapshot for agent
  critique. The agent is told not to call the existing `synthesize_icps@1` tool because that tool
  exposes only a proposal count, not the proposal content.
- Reports under `.context/stage0-trials/<session>/` include the transcript, current claims,
  memories, interview statement lineage, readiness, ICPs/proposals, model calls, and tool results.
- Added `docs/runbooks/stage0-conversation-trial.md`, script index entry, and focused unit tests.

## Verification

- `ruff` formatting/lint: green.
- targeted `mypy`: green.
- focused tests covering the new state/path/context contracts plus existing toolbelt, agent
  registry, C4, C5, and memory-import-boundary surfaces: green; DB tests skipped where Postgres
  was unavailable.
- `lint-imports`: all 24 contracts green.
- `scripts/00_stage0_trial.py --help`: green.
- Full `mypy`: green across 435 source files.
- The full test suite reached `1617 passed, 1120 skipped`; its only remaining failure after the
  memory-boundary fix is DB-environment drift: the running local database predates the C7
  `claim_flavor='derived'` enum migration.
- Repository-wide `make check` cannot be fully green while the user-owned untracked `.claude/` and
  `.codex/` structural-humanizer scripts are present because Ruff scans them and reports their
  intentional CLI `print` calls. Those files were not modified.

## Environment blockers / remaining verification

- `make db-up` failed because Docker Desktop/the Docker daemon is not running.
- `CLUE_OPENROUTER_API_KEY` is currently unset.
- Therefore a real DB-backed/model-backed conversation smoke has not run in this session. Once
  Docker Desktop is running and the key is set, use a migrated database:
  `make db-up && make migrate`, then
  `uv run python scripts/00_stage0_trial.py`.
- The existing `synthesize_icps@1` reference-only tool contract still returns only count/version.
  The CLI uses the same synthesis service at the human boundary and freezes proposals into the next
  turn context; a production fix should add a durable proposal-pack read surface rather than put
  proposal blobs into `ToolResult.references`.
