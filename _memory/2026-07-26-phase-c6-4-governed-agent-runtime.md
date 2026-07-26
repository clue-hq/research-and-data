# 2026-07-26 — C6.4 governed agent runtime

## Outcome

C6.4 is complete on `platform/c6-deepagent-runtime`. The platform now has the real deepagents
loop, whole-proposal C5 compiler, governed tool bridge, durable delegation lifecycle, model-call
receipts, async-Postgres checkpoints, and honest finalization authority. There is deliberately no
Stage-0 route, feature activation, or ownership cutover; C6.5 is next.

## Implemented

- Added package-local plan policy/review, stable execution+node operation ids, authority digests,
  bounded typed operation receipts, and terminal turn outcomes without infrastructure imports.
- Added a real `create_deep_agent` loop using the injected governed model, exact tools, isolated
  backend, `ClueDeepAgentState`, durable checkpointer, model-call callback, timeout and round
  ceilings. Normal model/framework stop is never success.
- Added C5 interaction-slot inspection and a compiler that validates the entire proposal against
  the exact profile/tool schemas, dynamic slot allowlist, C5 graph rules, node/depth/fan-out,
  delegation and budget ceilings before any domain effect.
- Tool calls append a C5 dynamic node and invoke through `RecipeExecutor`/mandatory `ToolInvoker`;
  only model-controlled domain parameters enter the proposal. Trusted constitution, call identity,
  operation identity, journaling, output validation, and authority are injected.
- Added reversible migration `6628a407e993` for append-only plans/events/operations/dependencies,
  tool-result refs, delegation grants/events/results, and finalization authority.
- Delegations persist parent authority and narrowed task/path/ref/resource/budget grants before a
  fresh child wake. Child execution identity is stable; completed results recover from durable refs
  without waking the child again.
- Added exact effective framework tools plus required `finalize_turn`. Finalization verifies every
  ref and frozen output snapshot, commits the envelope and turn terminal event atomically, rejects
  a different retry, treats an exact retry as a no-op, and authorizes workspace cleanup only after
  durable authority.
- Added production `AsyncPostgresSaver` factory and artifact-backed input/output model receipts.

## Failures found and resolved

- Real LangGraph execution showed that an exact strict tool schema rejected the trusted injected
  `ToolRuntime`. Internal validation schemas now add that injected field while LangGraph excludes
  it from the model-visible schema; exact descriptor inputs remain unchanged.
- A crash after finalization commit but before cursor/cleanup recovery could append a false
  failed/running state and leave cleanup unauthorized. Terminal commit now blocks later
  non-authoritative status events, and exact retry restores cleanup authorization.
- A crash after child completion could wake the child again. Delegation recovery now reconstructs
  the persisted reference-only result before considering another wake.
- `make check` sees unrelated untracked `.claude/` and `.codex/` CLI scripts and Ruff flags their
  intentional `print` calls. Those user-owned files were preserved. The identical format/lint gate
  passed with those two directories excluded.
- The first migration smoke used the populated full-suite DB and correctly stopped at the older
  C5.3 downgrade safety guard. The isolated schema was reset and the required clean smoke passed.

## Verification

- Real deepagents tests cover normal-stop failure, authoritative finalize, and an actual exact
  governed descriptor tool call through LangGraph.
- Fault coverage: model failure/receipt, plan append, C5 pre-tool/post-domain/completion events,
  post-tool result, child start/complete, artifact store, finalize event, and cursor update.
- Authority tests reject tool/slot/schema/budget/node/depth/fan-out/delegation/workspace bypass
  before domain execution; retries retain one domain effect and one final authority.
- Ruff format/check: green across the repository with unrelated untracked skill directories
  excluded (844 files).
- Mypy: 413 source files, green.
- Import-linter: 24 contracts kept, 0 broken.
- Full DB-enabled repository suite: 2,554 passed, 20 skipped.
- One Alembic head: `6628a407e993`.
- Clean isolated Postgres `make db-smoke`: head→base→head green.
- `git diff --check`: green before close-out.

## Next

Proceed with C6.5 only: compose the Head-of-ABM Stage-0 vertical against Recipe #0 and readiness
tools, preserve human confirmation/override and current C4 outcome/recovery behavior, keep the
C1 evaluator independent, and retain default-off/no-dual-ownership routing.
