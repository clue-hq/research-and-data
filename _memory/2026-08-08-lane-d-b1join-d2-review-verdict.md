# 2026-08-08 — Lane D B1-join + D2 orchestrator review verdict (Fable adversarial review)

## Verdict: both slices ACCEPTED

B1-join (`8429eb5e`…`1c10e915`) and D2 (`2487e5b0`, `ebbcca23`, `c103b3ef`) reviewed against
briefs + charter. Single Alembic head `fba208917f89` (D2 chained off B1-join's `c4ccc7b11810` —
no fork, no merge needed). Independently verified: combined suites (both new suites + all
amended chat/turn/trial/fleet suites + tests/fleet) = **174 passed, 0 failed** on the dedicated
damascus DB (55040). The one first-pass failure was the KNOWN order-dependent
`test_b4_composed_run_db::…deep_quarantines` flake (pre-existing; D2 proved by source-revert;
my identical rerun green). Hand-reviewed: B1-join FK migration preflight (house `82a80fb80c9e`
pattern, per-column offender naming), hardened `ensure_platform_thread`
(RETURNING + conflict-only re-read, typed `ThreadOwnershipMismatch`, no existence leak),
`agent_turn_submission` DDL, dispatch call-graph, HTTP-gateway isolation guard design.

## D2's accepted design deviation — FOUNDER AWARENESS REQUIRED

The brief said the route persists "the turn row". Impossible without violating the
gateway-isolation law: `agent_turn` FKs `execution` and pins a resolved constitution, whose
components builder also constructs the model provider. D2's adaptation — **two-phase identity on
one derived turn_id**: an immutable `agent_turn_submission` row at the route (NOT NULL human
identity, capture-before-spend FK to `onboarding_input`, thread/project/user/membership FKs,
immutable-by-trigger, `turn_id = uuid5(idempotency identity)` so duplicate POST lands on the
same PK; typed conflict when one idempotency key names different bytes) + the `agent_turn` row
created by the worker, copying the submitter from the submission row (never from the queue
payload). I judge this CORRECT — it preserves persist-before-enqueue, durable-row identity
authority, and HTTP/model separation. **Consequence for D3/D5 (record in their briefs): a
queued-not-yet-executed turn is visible only as a submission row (`submissions_for_thread`) —
read surfaces must union submissions with agent_turn events.**

## Mechanisms accepted

- Single-flight: at most one non-terminal AGENT_TURN task per thread, chained dispatch under
  `pg_advisory_xact_lock`; `work_id = uuid5(workspace, thread)` rides the existing fleet lease
  as a per-thread fence; earliest submission without terminal task, `ORDER BY requested_at,
  turn_id`. Chosen over claim-then-bounce so a busy thread never head-of-line-blocks others.
- Composition: `build_conversation_turn_engine` + `ConversationTurnEngine.execute` are now the
  single turn-execution implementation; worker builds ONE engine at startup; the trial still
  composes per request (deliberately different toolbelt) but through the same builder/execute.
- Replay short-circuit proven with a runtime that raises if invoked (0 calls, replayed=True,
  one commit row); crash/retry re-claims the same task (attempts=2) into the short-circuit.
- Gateway isolation: import-graph walk over the route's first-party imports (red-proofed) +
  assertion that projections_main's build_toolbelt passes no gateway.
- `PROJECT_CONVERSATION_SURFACE` declared with the trial's exact subtraction; the
  `test_c8_trial_surface` single-surface assertion correctly widened to assert both surfaces +
  reason codes.

## Follow-ups (fold into D3/D4 briefs)

1. **Stranded-dispatch gap (narrow):** crash between task-finalize and dispatch-next leaves
   queued submissions waiting until the thread's next POST. Fix: periodic sweep or
   dispatch-on-read. Not blocking (self-heals on activity).
2. **Trial latent bug (pre-existing, D4-relevant):** `stage0_trial` calls
   `decide_gate(actor="agent")` against recipe0's HUMAN-authority gate; production runner uses
   "human". Reconcile when D4 builds the gate machinery.
3. Retry/stop surface (`retry_of_turn_id`, stop-turn) is D3's per charter §3.5; today a FAILED
   turn is terminal and the thread moves on.
4. `created_via_membership_id` production writer arrives at Lane B B4; chat suite's
   `wsm_d0_test` names no row until then (B1-join report).
5. `StartupDevPrincipalResolver` wired in projections_main only; other entrypoints fall back to
   the unprovisioned resolver.
6. `client_entity_id` None until Stage-0 recon / PC-C4 brand-aware onboarding input.

## State

Lane D now has D0+D1+B1-join+D2 landed and reviewed. The Option-B chain through the worker is
real: production POST → durable submission (real principal identity) → queued AGENT_TURN →
worker executes platform deepagent with ambient turn-derived actor_id/action_ref. Next: founder
rules on the 9 thread-contract deviations (D0 report) + this verdict's two-phase-identity
consequence; then D3 (streaming) ∥ D4 (kickoff) briefs.
