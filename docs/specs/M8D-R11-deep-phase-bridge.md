# M8D R11 — DEEP-phase bridge: project-run integration of the entity-research fleet

**Status:** DRAFT — awaiting founder ratification of §6 before implementation
**Authority:** founder ruling 2026-08-07 (this spec's §1); `M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md`; `M8D-R1-active-path-quarantine-acceptance.md`; `M8D-R6-account-research-fleet-acceptance.md`
**Context trail:** `_memory/2026-08-07-dead-code-stale-endpoint-audit.md` (gap discovery + verified mechanics); CLAUDE.md backlog `[M8D×M7×frontend]`

## 1. Ratified diagnosis (founder, 2026-08-07)

> M8D correctly quarantined the wrong orchestration and successfully built its replacement, but
> the outer project-run state machine and verification selector were never migrated to that
> replacement.

The R1 quarantine retired the M8A/M8B/M8C orchestration model (mechanical account orchestrator,
pre-agent provider preparation, committee walking, automatic account→contact progression) because
it did not match the M8D requirement: one subject-neutral fleet, one bounded `create_agent()`
unit per account/contact, separately authorized account and contact research. R6 deliberately
made the replacement fleet independent of the outer machine: *"no legacy `account_deep_launch`
is created, and the launch works without the outer project state machine being at `DEEP`"*
(`M8D-R6-account-research-fleet-acceptance.md:30`). What was left unfinished is the follow-up
integration. **The fix is forward integration with the M8D fleet. Unquarantining or restoring
any M8C code path is out of the question; the R1 quarantine handler leaves the DEEP slot only
when the R11 adapter replaces it.**

## 2. Boundary

In scope:
1. Replace `EntityResearchQuarantinePhaseHandler` in the project-run DEEP slot with an
   M8D-compatible phase adapter (R11.1).
2. Have that adapter join/wait on the M8D account-research fleet (R11.1–R11.2).
3. Make VERIFICATION (both the composed phase handler and `run_verification@1`) select accounts
   from M8D research-run membership/finalization instead of the legacy `account_deep_launch`
   ledger (R11.3).
4. Preserve M8D's separate human approval before contact research (non-goal below restates).

Non-goals (violating any of these fails acceptance):
- **No unquarantine.** `QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES` and the
  `ReplayOnlyEntityResearchTool` wrappers are untouched; the superseded implementation trees are
  deleted only by the separately triggered cleanup PR (CLAUDE.md `[audit 2026-08-07]`).
- **No automatic account→contact progression.** Contact research remains separately authorized
  (`approve_contact_research_selection@2` → `launch_contact_research@1`).
- **No HANDOFF cutover change.** HANDOFF stays fail-closed behind
  `c7_production_handoff_enabled`; R11 only makes the phase *reachable*.
- **No new fleet, no provider-specific controller** (R6 boundary holds).

## 3. Verified substrate facts the design stands on (all verified 2026-08-07)

- The phase machine already supports non-human external waits **for DEEP specifically**:
  `PhaseStatus.WAITING_EXTERNAL` is valid only for DISCOVERY and DEEP
  (`durable/project.py:494-506`), lands a `WAITING_EXTERNAL` checkpoint, and *"deliberately
  falls through: a scheduled/webhook wake re-enters the same handler with the persisted
  batch/operation refs"* (`durable/project.py:440-442`). `PAUSED` is the human/budget hold.
- The typed DEEP wait payload `core.external_research.DeepExternalWait` is shaped for the legacy
  per-account provider waits (`pending_accounts[].account_run_id` +
  `preparation.retry_after`) — a fleet-shaped wait needs a contract-delta (R11.4).
- `AccountResearchFleetLauncher.launch` requires an attributable human-confirmed action
  (`actor`, `source_action_ref`, `source_operation_id`), binds to a real `project_run_id`
  (`account_research_fleet_launch.py:160`), commits compile+offer in one transaction, is
  idempotent per action/operation, and produces a content-addressed account selection plus
  compatibility `account_run` rows. The launch authorization **is** the R6 fleet selection.
- Fleet observability exists: `EntityResearchJobStore.get_run`/`list_jobs`
  (`clue_fleet/entity_research.py:320,324`; `list_jobs` currently has zero callers — R11 is its
  first customer, else it goes in the cleanup PR), and the account-fleet controller computes
  `all_terminal` and a `return_kind: "suspended" | "terminal"`
  (`account_research_fleet.py:1001,207`).
- `ExternalResearchWakeDispatcher` (`external_research_wake.py:128`) takes a pluggable
  `sources` sequence feeding a `ProjectRunWaker` — the seam for a fleet-terminal wake source.
- The defect R11.3 closes: `build_high_tier_resolver` (`deep/composition.py:200`) returns `()`
  when `get_account_deep_launch` finds no row; the row's only production writer is the
  quarantined `launch_account_deep@1` (`toolbelt_wiring.py:1463`). Both the composed
  VERIFICATION handler (`run_composition.py`) and `run_verification@1`
  (`toolbelt_wiring.py:2155,2190`) consume it, so verification silently reports
  `accounts_processed=0` on M8D-researched accounts.

## 4. Design

### R11.1 — DEEP adapter (`EntityResearchDeepPhaseHandler`, join-only)

Registered for `ProjectPhase.DEEP` in `run_composition.py`, replacing the quarantine handler.
**Join-only:** the adapter never launches the fleet itself — launch authority stays with the
human-confirmed `launch_account_research@1` (R6: the confirmed selection is the authorization;
an adapter-initiated launch would recreate exactly the automatic progression M8D retired).

Per `run(ctx)` evaluation, keyed on the M8D account-research run(s) bound to
`ctx.project_run_id`:

| Fleet state | PhaseResult | Semantics |
|---|---|---|
| No account-research run exists | `PAUSED` (or AWAITING_INPUT-style checkpoint — §6b) | Durable human gate: the confirmed launch is the resume action, parity with TIER_CHECKPOINT |
| Run exists, jobs nonterminal | `WAITING_EXTERNAL` + R11.4 payload | Non-human wait; wake re-enters this handler |
| Fleet suspended (canary block / review fraction / worker failure) | `PAUSED`, payload carries the durable diagnosis/return-snapshot refs | Human decision point — never silent, never `FAILED` (the fleet's suspension is honest, not broken) |
| All jobs terminal | `COMPLETED`; `accounts_processed` = terminal account count; `cost_cents` from fleet settlement refs | Run advances to VERIFICATION |

Idempotent on `(project_run, phase)` per the existing ledger; re-entry after crash re-evaluates
fleet state (pure read — the adapter owns no spend, so double-entry is harmless by construction).

### R11.2 — Fleet-terminal wake source

A new `ExternalResearchWakeSource` registered in `ExternalResearchWakeDispatcher.sources`: lists
project runs holding a DEEP `WAITING_EXTERNAL` checkpoint whose bound account-research run went
terminal (or suspended) since the checkpoint, and re-offers them to the `ProjectRunWaker`.
Scheduled-poll fallback via the payload's `next_poll_at` stays (same discipline as discovery).

### R11.3 — Verification account selector

New `build_entity_research_account_resolver`: reads the R6 content-addressed account selection +
per-account finalization outcomes for the project run's account-research run, yields the
`AccountSpec` set for accepted/terminal accounts. Replaces `build_high_tier_resolver` at **both**
consumers (`run_composition.py` VERIFICATION registration; `run_verification@1`). **Fail loud:**
no M8D account-research run for the project run → typed error, never an empty-success
(`accounts_processed=0`) — closing the audit's silent-zero defect. `build_high_tier_resolver`
and the `account_deep_launch` read move to the cleanup-PR inventory once nothing consumes them.

### R11.4 — Contract-delta: fleet-shaped DEEP wait payload

Frozen-core delta (same process as prior `core` deltas): either (a) a new
`DeepFleetExternalWait` model (`research_run_id`, job-state counts, `next_poll_at`,
`wake_reason`) accepted by the DEEP `WAITING_EXTERNAL` validation arm alongside the legacy
shape, or (b) extend `DeepExternalWait` with an alternative fleet variant. Option (a)
recommended — the legacy shape keeps validating historical checkpoints byte-for-byte.

## 5. Acceptance criteria (sketch — frozen at implementation kickoff)

1. A composed project run at DEEP with a confirmed `launch_account_research@1` fleet run reaches
   VERIFICATION after the fleet goes terminal, with `accounts_processed` equal to the fleet's
   terminal account count. No `account_deep_launch` row exists anywhere in the flow.
2. A composed run at DEEP with **no** fleet run holds durably (no failure, no silent completion)
   and resumes on the confirmed launch.
3. Fleet suspension surfaces as a PAUSED run carrying the diagnosis refs; operator resume after
   fleet resume re-enters DEEP and proceeds.
4. `run_verification@1` on a project run with no M8D research run fails loud (typed error);
   on an M8D-researched run it processes exactly the R6 selection's terminal accounts.
5. No contact-research launch occurs anywhere in the bridge path (the R6 "contact-research
   request suspends honestly" behavior is preserved).
6. Every quarantined address still refuses a cache-miss invocation (R1 regression gate re-run).
7. Crash/replay: SIGKILL during WAITING_EXTERNAL and during COMPLETED-finalize replays to the
   same terminal state (existing phase-ledger discipline).

## 6. Open decisions for ratification

- **(a) Branch placement.** Recommended: its own research-lane worktree branch (like B3/B4),
  merged into `platform/frontend-integration` when accepted — this branch's charter stays
  frontend-only. Alternative: implement directly here since phase-2 depends on it.
- **(b) "No fleet run yet" semantics.** Plain `PAUSED` (operator resumes after launching) vs an
  `AWAITING_INPUT`-style checkpoint like TIER_CHECKPOINT (the launch tool doubles as the gate
  decision and auto-resumes). Recommended: start with `PAUSED` (smaller surface), upgrade if the
  phase-2 frontend wants a first-class gate card.
- **(c) Multiple fleet runs per project run** (relaunch after suspension, partial re-research):
  does DEEP completion key on the *latest* run, or the union of terminal runs? Recommended:
  latest confirmed run wins; earlier runs remain visible history.
- **(d) Budget attribution.** DEEP is budget-gated (`_BUDGET_GATED_PHASES`) but the fleet has
  its own R9 admission/settlement. The adapter must report fleet cost without double-gating:
  recommended — adapter reports `cost_cents` from settlement for the ledger, and the M7.5
  pre-gate keeps operating on the project-run cap as today (single enforcement at fleet
  admission; phase-level gate remains a coarse pre-check).
- **(e) Interim `run_verification@1` guard.** R11.3 replaces its resolver; no separate interim
  fail-loud patch unless R11 is deferred — if it is, add the loud missing-ledger error first.
