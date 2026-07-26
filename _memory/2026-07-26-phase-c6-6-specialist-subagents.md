# 2026-07-26 — C6.6 fresh-wake specialist subagents

## Outcome

C6.6 is complete on `platform/c6-deepagent-runtime`. Head-of-ABM v3 can delegate bounded work to
the research, content-drafter, and reviewer v2 profiles through the C5 delegation journal. Every
specialist wakes in a distinct C6.1 workspace and execution with no parent conversation history,
uses a pinned role prompt/skill/profile/model/tool surface, writes a durable role-specific output,
and returns references only. No public route, canary, ownership cutover, or migration was added;
C6.7 is next.

## Implemented

- Added the frozen `SpecialistTaskEnvelope` and `DelegatedFileGrant` contracts. Small context is
  preserved verbatim; canonical parent files are copied byte-for-byte into content-addressed
  artifacts and materialized read-only below `context/delegated/`; domain state stays typed refs.
- Added the governed `delegate_specialist` wrapper. It validates role authority, freezes the task,
  compiles one `PlanDelegationStep`, executes through the same C5 adapter, and returns its durable
  receipt. DeepAgents' general-purpose `task` tool remains permanently filtered as an authority
  bypass.
- Added `FreshWakeSpecialistRunner`, child execution journaling, workspace/execution/spend seams,
  empty-history and empty-L6 enforcement, immutable resource/task materialization, per-role model
  construction, role time/round limits, non-empty output enforcement, budget validation, and
  reference-only result mapping.
- Parent delegation now assigns only the remaining execution budget after prior child spend and
  binds the durable child runner before plan validation.
- Added additive Head v3 plus research/content/reviewer v2 prompts and profiles. Added
  `research-task@v1`, `content-exemplar@v1`, and `artifact-review@v1`. Historical versions remain
  unchanged and addressable.
- Research can use the four governed research operations and writes
  `outputs/research-strategy.md`; the drafter can use `compose_handoff@1` and writes
  `outputs/content-exemplar.md`; the reviewer can use `compose_handoff@1` and writes
  `outputs/review-verdict.md`. Specialists cannot recursively delegate.
- Added `docs/agents/skill-and-profile-authoring.md`, the maintainer map for every active
  main/subagent prompt, skill, profile, selector, materialization path, immutable version workflow,
  and future prompt-hub seam.

## Authority decisions

- A specialist is a governed child execution, not an in-process prompt helper.
- The parent passes exact artifacts and typed refs, never hidden chat state or an unverified
  paraphrase in place of a canonical source.
- Reviewer output is critique only; it cannot edit or approve canonical artifacts. Drafter output
  is one exemplar, not claim truth or scaled production. Research outputs strategy/questions;
  durable findings still require governed claim/proposal tools.
- Human gates and `awaiting_input`/`blocked` results propagate to the parent. A completed child
  cannot return until its role output and honest finalization envelope are durable.

## Verification

- No-DB full suite: 1,519 passed, 1,076 skipped.
- Dedicated-Postgres full suite: 2,575 passed, 20 skipped in 128.92 seconds.
- DB-backed fresh-wake reviewer test proves empty history, distinct child execution, exact
  canonical-file materialization, durable output refs, spend reporting, and parent linkage.
- Ruff check and format-check: green across 847 files.
- Mypy: 415 source files clean.
- Import-linter: 24 contracts kept, 0 broken across 476 files and 3,382 dependencies.
- Alembic has one head, `6628a407e993`; isolated head to base to head smoke passed.
- `git diff --check` passed. No C6.6 migration was added.
- Unrelated user-owned changes in `platform/agents/clue_agents/model.py`, `.claude/`, `.codex/`,
  the scripted-model memory note, and the research-model-surface document were left untouched and
  unstaged.

## Next

Proceed with C6.7 only: integrate one governed per-account research agent while preserving the
existing fleet, leases/fencing, pre-spend gates, waterfall, claim/provenance/verification paths,
coverage ledger, budgets, and recovery semantics. Resolve the C1 evaluator owner explicitly and
do not create a duplicate agent-local goal judge. C6.8 retains production routing/canary ownership.
