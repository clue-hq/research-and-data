# FI — Pilot budget-controls toggle (`CLUE_BUDGET_CONTROLS_ENABLED`)

**Status: RATIFIED 2026-08-11 (founder).** Branch `platform/pilot-budget-controls` (this
worktree, cut off Lane F head `642064e6`; Lane F's branch stays frozen as reviewed).

## Ruling

For the pilot, users must never be shown a cost/budget number, and **nothing on the platform
may stop a pre-approved action on budget grounds** — hard spend control lives at the provider
consoles. Spend **recording** stays complete. Founder-selected shape: **silent internal
estimate kept for approval integrity; presentation + enforcement off.**

One deployment flag: `Settings.budget_controls_enabled` (`CLUE_BUDGET_CONTROLS_ENABLED`),
default `true` (today's behavior); pilot deployments set `false`. Deployment-scoped, not
pinned per run (same accepted caveat as `CLUE_VERIFICATION_ENABLED`).

## With the flag OFF

1. **Presentation off.** The directive-confirmation gate still computes and durably stores
   `max_spend_cents` on the immutable gate row (audit + integrity), but the amount leaves
   every model-/human-visible surface: the gate tool's result references and the gate wire
   payload carry no amount (the Lane D gate contract already declares the amount optional).
2. **Enforcement off — record-only spend.**
   - R9 atomic admission (`DbEntityResearchToolBatchCoordinator.admit`) never refuses on the
     job/run budget caps; it still writes its reservation/settlement rows unchanged. Applies
     to both fleets (account + contact) via the shared coordinator.
   - The M7.5 project-run budget pre-gate does not stop runs (no `BudgetEngine` pre-gate
     verdict can pause a phase).
   - `BUDGET_STOPPED` finalizations become unreachable; any other pre-action budget refusal
     found by the implementation sweep is gated the same way (refuse→record).
3. **Launch integrity kept, courier field ignored.** The launcher skips the caller-supplied
   `expected_estimated_cost_cents` equality check (the agent has no number to echo); approval
   integrity rides the gate's directive-digest binding (`expected_subject_sha256`), which is
   unchanged and remains the load-bearing stale-approval guard. The launcher still recomputes
   and logs the estimate for the durable record. Tool input schemas are NOT changed (pinned
   profile digests stay valid); the field is simply ignored when off.
4. **Recording untouched, both modes:** `spent_cents` accumulation, settlement receipts,
   reservation rows, M13.4 cost observability, and Lane F's settled-spend copy into the
   project ledger at DEEP completion.

Kept ON in both modes: depth/fanout structural caps, the exact human-approved account
selection, canary/quality suspension (not budget), pre-spend *authority* gate (M9.1 — not
economics), all human tools (`adjust_budget` stays functional and inert-by-consequence).

## Acceptance

1. Flag on: byte-identical behavior; existing suites green.
2. Flag off: a tool batch exceeding the job/run cap is admitted, executes, and its spend is
   recorded (reservation + settlement rows exist; `spent_cents` exceeds the cap honestly);
   no `BUDGET_STOPPED` outcome anywhere.
3. Flag off: a project run whose recorded spend exceeds its cap advances through every
   budget-gated phase without a graceful stop.
4. Flag off: the gate row stores `max_spend_cents`; the gate tool result and wire payload
   carry no amount; launch succeeds with any `expected_estimated_cost_cents` value; the
   directive-digest mismatch still refuses launch (integrity proof).
5. Both modes: no tool descriptor/schema digest changes (profile pins unaffected).
