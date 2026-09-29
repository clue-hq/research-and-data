# Turn budget: honest wrap-up instead of a graph-fuse crash — 2026-09-27

Founder rulings this session: research AND Head-of-ABM get 350 model rounds; round/time limits
are env settings, never profile content; no timeout for now (0) with a Sentry warning after 1 h;
at the limit research finalizes `blocked`, Head-of-ABM finalizes `awaiting_input` ("reply
continue"); warn 3 rounds before; same warn-and-finalize ~3 minutes before a time limit.

## The defect fixed
`superstep_ceiling(n)` was `2n+4`, but a Deep Agent round costs more LangGraph steps (to-do
after_model hook; ToolRepairRoundsMiddleware before_model added 2026-09-25). Offline probe with a
fake model: 100 configured rounds died with GraphRecursionError at 68 (before the repair hook) and
51 (after). Every Deep Agent (v20+ researchers, Head-of-ABM) was affected. The research allowance
and the old fuse both ended a turn FAILED with no finalize_turn.

## What changed (uncommitted at session end — awaiting founder go to commit)
- `clue_agents/runtime.py`: `TurnBudgetMiddleware` (rounds counted in graph state
  `turn_budget_*`; finalize-only from round N-2 so both finalize repairs fit inside N; 3 warned
  rounds before; time windows min(180 s, limit/4) warn and min(60 s, limit/10) finalize-only;
  notices appended per call, never persisted). Fuse now `n*6+10`. Long-turn watchdog:
  log `agent.long_turn` + Langfuse tag `long_turn` + one Sentry warning per turn.
  Logs `agent.wrap_up_warned` / `agent.{round,time}_budget_reached`; same names as trace tags.
- `MAX_RUNTIME_MODEL_ROUNDS` 200 -> 500; settings bound le=500 on both round settings.
- Settings/env: `CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS=350`, `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S=0`,
  new `CLUE_HEAD_OF_ABM_MAX_MODEL_ROUNDS=350`, `CLUE_HEAD_OF_ABM_TURN_TIMEOUT_S=0`,
  `CLUE_AGENT_LONG_TURN_ALERT_S=3600` (.env and .env.example). Head-of-ABM reads them via
  `AgentPlatformComponents`, no longer from the profile's max_model_rounds/turn_timeout_s.
- `clue_obs.langfuse.flag_trace`, `clue_obs.sentry.warn` helpers.
- Tests: `tests/agents/test_turn_budget.py` (probe reaches exactly N=12 and 350 rounds and ends
  via finalize), `tests/test_agent_turn_limit_settings.py`; updated test_execution/test_settings.

## Verification
Run in a throwaway worktree at 296922df1 + only these changes (the live tree's uncommitted
`account-research-briefing/v1/SKILL.md` edit breaks the Head-of-ABM pin, so HoA tests cannot load
there). tests/agents + registry + settings: 419 run, 2 failures that also fail on clean HEAD.
tests/api + tests/arv2 offline: 2753 run, 11 failures, all identical on clean HEAD. Ruff,
format, mypy (changed modules) clean; import-linter 28 kept / 0 broken. No DB, no live calls.

## Head-of-ABM v65 (founder approved the exact wording in chat, same day)
- Active pin v64 -> v65 (`C6_ACTIVE_PROFILE_VERSIONS`, `PROJECT_CONVERSATION_AGENT_PROFILE_ID`).
  v65 = v64 surface exactly; manual `manual-*@v11` (limits/errors/turn/siblings reworded:
  limits stated without numbers, wrap-up notice, repair budget = 10 rounds per 2026-09-25 rule);
  prompt v17 and stage0-interview v38 = v16/v37 with only briefing v1->v2 and manual v10->v11
  literal paths. `{{skills.*.path}}` placeholders were tried and rejected: a narrowed surface
  that drops the briefing skill makes the renderer refuse the prompt.
- `account-research-briefing` v2 = founder's in-place edit ("for seller Clue"); v1 restored to
  its committed bytes so v64 loads again.
- `clue_api/manual_build.py` fixed (it imported the removed `_MAX_GOVERNED_TOOL_FAILURES`; the
  builder now reads `MAX_TOOL_REPAIR_ROUNDS`, and `GovernedToolFailure.governed_repair_budgeted`
  got its field note). `make manual-check`: 4 chapters current.
- Tests: catalog inventory, registry digest (9b961077…), tamper target v17, s4e/comprehensive
  pins. Live-tree offline run: 3138 tests, 15 failures = 12 pre-existing HEAD failures + 3
  Langfuse tests that fail only in a full run on a tree whose .env has real Langfuse keys (a
  tests/api test installs the real client and even exports spans); each passes alone.

## Capability map (closed same day, founder go)
- `ResolvedAgentProfile.generated_resource_map` (every agent's system prompt) no longer prints
  the profile's `turn_timeout_s` / `max_model_rounds`; it says the limits are set by the
  deployment and that a notice arrives near one. Asserted in test_agent_registry_wiring.

## Open
- Pre-existing: three person trial tests import removed `media_acquisition.duration_of`.
- Research allowance still counts ExactAgentToolSurface's plain-text recovery call; a turn that
  needs it at the very end could hit the allowance before finalizing (rare).
- A time limit only exists if an operator sets one; with 0 only the round budget applies.
