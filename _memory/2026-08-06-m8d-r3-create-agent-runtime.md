# 2026-08-06 — M8D R3 shared create-agent runtime

## Outcome

- Implemented one role-configured entity runtime for account, contact, and depth-one facet units.
- Every unit is built by `langchain.agents.create_agent()` with exact resources/context/tool pins,
  typed `ResearchFinalizationProposal`, bounded model/tool/runtime limits, and an injected
  checkpointer. No entity path imports or calls `create_deep_agent()`.
- Added mandatory engine guard seams for tool/batch authorization and yield/cost observation.
  Tool-call identity/input is durably journaled before the guard or handler can dispatch work.
- Added append-only model/tool/finalization events, external wait checkpoint receipts, exact cold
  replay, engine-receipt-only account/contact success, and non-terminal typed facet results.
- The resolved system prompt includes the pinned role profile, prompt, and skills. Exact
  construction identity also binds the model policy and initial task-instruction digest.
- Added the R2 driver adapter, but did not bind it in production. R1's fail-loud quarantine remains.

## Persistence

- Migration `ac980e12eb5e` adds immutable `entity_research_agent_turn` construction records and
  ordered `entity_research_agent_event` history/tool-causation rows.
- `PostgresEntityResearchCheckpointers` uses `AsyncPostgresSaver`; LangGraph owns its checkpoint
  tables. Facets receive deterministic fresh child threads under the authorized parent job.

## Verification

- Account/contact/facet executable factory, exact tools, guarded concurrent calls, typed
  finalization, bounded facet, and external-wait tests: green.
- R0/R1/R2/R3 focused regression: green.
- Fresh isolated Postgres database `clue_roseau_m8d_r3_20260806`: full migration to head green;
  R3 downgrade to `022b1154b3aa` then upgrade to `ac980e12eb5e` green.
- Combined R2/R3 live database tests: 6 passed. Cold replay used a fresh saver/runtime and made no
  second scripted model call; append-only mutation was rejected.
- Ruff, scoped mypy, and import-linter (24 kept, 0 broken): green.

## Boundary

- No provider credential, provider request, or paid spend occurred. R4 owns concrete governed
  provider/claim tools and complete persisted result projection. R5 owns account research behavior.
- Existing unrelated worktree edits were neither modified nor staged.
