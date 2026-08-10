# 2026-08-08 — Lane D §6 decision register fully ratified (worktree: damascus, branch `platform/platformlane-d-chat-launch`)

## Scope
Documentation-only session. Founder resolved every remaining Lane D §6 decision; rulings recorded
in `docs/specs/FI-lane-D-production-chat-and-launch.md` (status → RATIFIED CHARTER, build-ready)
and `docs/specs/FI-lane-demarcation.md` §4. No runtime, DB, frontend, or API code changed.

## Founder rulings (this session)
- **D1 — RATIFIED:** async worker-executed turns (§3-P3). `AGENT_TURN` fleet task; HTTP route
  persists + enqueues + 202; fleet worker executes the graph. Gateway-in-HTTP rejected.
- **D3 — RATIFIED:** new durable, **generic** `agent_gate` substrate as an **immutable gate row +
  insert-once answer/event record** (open/answered derived from the answer record's presence,
  never a mutated status column). P5(a) amended to this two-record shape.
- **D5 — RATIFIED as DEFERRED for V1:** no `estimate_account_research@1`; `estimate_project@1`
  stays reserved. No conversational estimates/cost breakdowns in V1. The backend computes ONE
  server-derived maximum-spend amount (Σ per-account `effort_policy.budget_cap_cents`) when
  creating the directive-confirmation gate, stores it durably on the immutable gate row, and
  re-verifies it at launch (`expected_estimated_cost_cents` exact-match). Richer estimation +
  cost-explanation surface are post-V1. (Founder's opening line said "agree with D5
  recommendation" but the explicit final paragraph deferring it is controlling — confirmed as
  the recorded verdict.)
- **D6 — RATIFIED:** keep the stage-0 trial as dev-only harness, unchanged.
- D2 (complete token streaming) and D4 (real authenticated Clue principal) were already ratified;
  D4 is formalized in `docs/specs/FI-lane-B-authenticated-principal-contract.md` (cherry-picked
  onto this branch as `0e31a7ab` — read it: RequestPrincipal seam, no-provider-FK rule, Clerk
  authentication-only, B0–B5 slices, Lane-D join gates in its §9).

## Lane B ⇄ Lane D contract highlights (binding on all Lane D work)
- `actor_id = platform_user.user_id`; humans act via `workspace_membership.membership_id`; no
  Clerk id/email/claim as any key. Lane D consumes the closed `RequestPrincipal` only.
- D0's thread table uses `created_by_user_id` FK → `platform_user` + `created_via_membership_id`;
  D0's ownership migration chains AFTER Lane B B1. D2 may run with a deterministic injected test
  `RequestPrincipal`; production D1 joins B2/B4; D5 joins B3. No temporary user headers inside
  domain code.
- SSE auth: short-lived single-use principal/workspace/turn-scoped stream token (no bearer in URL).

## Working-model rule (re-confirmed this session, saved to persistent memory)
Fable (main loop, exactly one, never a Fable subagent) does ALL thinking/brainstorming/design/
planning/review + debugging diagnosis. Opus agents do ALL implementation (code, migrations,
tests, mechanical edits). Fixes for diagnosed bugs are delegated back to Opus.

## State / next steps
- Lane D charter fully ratified → build-ready. Next: plan slice briefs. Per the post-B0 ordering:
  D0 non-FK work ∥ D1 Lane-D half ∥ D3 scaffolding can start now (Opus agents); D0 ownership FKs
  wait for Lane B B1 (separate lane/worktree).
- Untracked in this worktree, not mine, left untouched: `.playwright-mcp/`,
  `tests/claimstore/test_lens_isolation.py` (pre-existing).
