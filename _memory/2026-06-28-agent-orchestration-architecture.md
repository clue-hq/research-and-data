# 2026-06-28 — Agent orchestration architecture (chat-first deep agent) — RECOMMENDATION (pending founder confirm)

## Question
Founder wants a chat-first product (Mutiny/Ploy/Claude-Code style): one user-facing "deep agent"
+ a generative right-canvas. Asked: how to orchestrate the modular research subsystem behind it —
a single "deep agent" orchestrator, a deterministic workflow orchestrator, or a hybrid?

## Method
Design workflow: 4 independent architectures (deep-agent-maximalist / two-plane control-plane /
hybrid-control+agentic-inner-loops / per-stage-specialist-router), each adversarially stress-tested,
+ a patterns-research track (Temporal/LangGraph/Claude Code/DeepAgents/11x/Mutiny/Ploy), then synthesis.
Agents read the real code. All four verdicts converged: "survives-with-changes" → SAME answer.

## Recommendation (committed)
**Two-plane: a thin conversational CONTROL PLANE (one deep agent = intent-compilation + narration +
canvas-binding + Stage-0 elicitation) over the existing M7 durable engine as the DATA PLANE / system
of record. The agentic plan→work→JUDGE→replan loop lives INSIDE the per-account deep path as bounded
leaf nodes. Stage specialists = config/routing, not separate codebases.** The "one agent that spawns
the right module" feeling is the state machine + PhaseHandlerRegistry doing deterministic module
selection; the LLM only triggers `advance()` and narrates.

Rule: **LLM proposes, engine disposes** — reduce every LLM output to a typed/validated structure
before it touches the store. LLM must NEVER own: the 500-account fan-out (cost), phase
sequencing/budget/retry (determinism+idempotency), being the source of any entity/fact/score/merge
(verifiability bet). Enforce structurally: new top-of-tree `agent/` package, import-linter contract
(may import `api` facade + read projections only; forbidden from claimstore-writes/resolvers/gateway).

## The load-bearing finding (verified in code — the gap all 4 critiques caught)
The founder's two headline requirements DO NOT WORK on the engine as built:
- Execution is **inline**: `campaign.py:454` `result = await handler.run(...)` → `scheduler.py:136`
  `asyncio.gather` over ALL accounts in one event loop/process. **No detached runner exists.** So
  "close the tab, 500 keep running" is false today — the chat request *is* the worker.
- Single-driver-per-run is a **documented but UNENFORCED** precondition (`campaign.py:98`
  `DEFAULT_PHASE_STALE_AFTER=timedelta(0)`, docstring L327-353). Chat-first + multi-session is the
  perfect machine for violating it → two sessions can concurrently re-run an `in_progress` spend phase.
  (Matches our own M7.3/M7.4 memory: "no same-run driver lock", "per-run driver lock = scheduler/ops layer".)

→ **Phase 0 = a detached `CampaignRunWorker` + per-run driver lease (reuse Redis `entity_lock` keyed on
campaign_run_id) + a recoverable `(campaign_run, account)` deep-task drain.** This is the first slice
of the eventual Temporal migration (not throwaway). De-risk test: start 500-account deep phase,
`kill -9` worker at ~40%, restart, assert every account completes exactly-once / zero double-charge
against BudgetEngine ledger; fire two concurrent `advance`/`submit_checkpoint`, assert lease serializes.

## In-run loop (Phase 5) — scoping correction
Production deep path = `api/deep/handler.py::run_one` (account→committee→contact) via `asyncio.gather`
+ `sub_phase` markers + `DbExactlyOnceSpend` — NOT the LangGraph `Send` super-step (that's
`durable/graph.py`, M2 account-axis only). Build the judge→replan loop in the orchestrator's per-stage
sequence reusing the proven sub_phase + ExactlyOnceSpend machinery. 3 LLM sites only (planner / workers
/ judge); replan|stop is DETERMINISTIC (SpawnGuard depth/count + new max_replan_rounds + budget +
marginal-yield). Extend exactly-once key → `(account, field, tier, replan_round)`. Ship behind per-tier
flag, top-tier first, AFTER closing deferred verification seams (PreSpendGate routing, identity-binding
pre-insert stamp, freshness age-out on core seam) + M9.6 adversarial judge fixtures (injection surface).

## Build sequence
0 worker+lease+drain → 1 read/projection API (canvas) → 2 thin chat agent (intent→Command|question;
`agent/` import contract) → 3 Stage-0 (interview-answers-as-claims CKB + deterministic coverage gate;
run a real 500-acct campaign on TODAY's static plan→fanout→collect→handoff first) → 4 close deferred
seams → 5 in-run judge→replan loop → 6 surface M13.3 learning loop/BacktestGate + per-source-yield in
chat as confirmable suggestions; split budget_event categories per LLM source.

## Open questions to founder (unresolved)
1. Worker topology / Temporal trigger: single asyncio supervisor now vs. Temporal activities-per-account?
   Real target concurrency — hundreds on one box or thousands on a fleet? (decides build-twice risk)
2. Concurrent-session UX: 2nd session read-only vs. collaborative last-writer-wins + adjustment_journal?
3. Typed-intent expressiveness ceiling: novel steering = a versioned icp_spec/rubric/source-profile
   config edit; where is the line the agent must never cross?
4. In-run replan economics: default-on top tier vs. opt-in measured against BacktestGate? acceptable
   marginal cost-per-net-new-supported-claim?
5. Stage-0 "enough collected": hard-block vs. advise-with-override (client-always-has-the-wheel tension)?

## Status
Recommendation delivered to founder; NOT yet implemented. No code/docs changed this session except this
note. Next: founder confirms direction + answers open Qs → write ADR/design doc → prototype Phase 0.
