# 2026-06-21 — M6 ↔ M7 run-telemetry ownership decision (AGREED with user)

> Cross-branch coordination point flagged in the M5–M9 parallelisation rules ("M6↔M7 co-own
> run-telemetry; agree ownership before both create overlapping tables"). User confirmed the
> resolution below. **Binds M7.3 and M7.5 on this branch.** M7.1 (account_run) is unaffected.

## The problem
"Run telemetry" = operational metrics about how a run went (NOT account facts — those are claims).
Three pieces are claimed in words by BOTH M6 and M7 specs; one already physically exists. If each
branch makes its own table for the same concept, `alembic merge` reconciles the migration graph but
NOT the duplicate modelling → two tables for one thing, split writes. M6 spec repeatedly says
"no bespoke table — reuse/extend the run telemetry M7 owns", but M7's spec never defines a *generic*
run-telemetry table (M7 owns campaign_run, account_run, campaign_phase_checkpoint, budget_event).

## Agreed ownership (DO THIS)
1. **Per-source / per-channel yield** (counts keyed (run_id, source_key, field_class): claims
   produced / survived verification / cost) → **REUSE the existing `source_yield` table** (M4.6,
   migration `eab62cbb1366` = the head both branches fork from). It is per-(client, icp, field_class,
   source) with a **nullable run_id** — designed so per-run rows fit. Writer already exists:
   `sources/source_yield.record_source_yield`. **M7 creates NO new run-telemetry / run_source_yield
   table.** M7.5's burn-down "per-source yield" READS/relates to `source_yield`, does not duplicate it.
2. **Tier checkpoint record** (M6.4: {campaign_run, phase='tier_checkpoint', proposed_cutoffs,
   tier_distribution, cost_estimate, decision}) → **M7 owns `campaign_phase_checkpoint`**
   ({campaign_run_id, phase, idempotency_key, status, payload_json, committed_at}). M6.4's
   tier-checkpoint handler persists its data via **`payload_json`** on that row, idempotent on
   `(campaign_run, phase='tier_checkpoint')` (= the frozen `phase_key` shape). M6 creates NO
   tier_checkpoint table. **M7.3 OBLIGATION:** land `campaign_phase_checkpoint` with a usable
   `payload_json` + a **read-back API** that M6's checkpoint phase writes into. The frozen
   PhaseHandler/PhaseResult seam already supports this (phase returns `PhaseResult.payload`;
   durability is M7's job → M7.3 persists PhaseResult.payload into payload_json and can read it back).
3. **Coverage report** (M6.5: {coverage_estimate_band, channels_searched/not_searched,
   per_channel_curve, stopping_reason} keyed (run_id)) → **M6 owns its own `coverage_report` table**
   (M7 never reads it). Not M7's concern.
4. **account_tier** → M6 owns (uncontested). Not M7's concern.

## Net effect for THIS (M7) branch
- M7.1: no change (account_run is M7-owned, uncontested). ✅
- M7.3: `campaign_phase_checkpoint` MUST have `payload_json` + read-back (M6 writes tier-checkpoint
  payload there). Do not create any separate tier/telemetry table.
- M7.5: burn-down's per-source yield READS the existing `source_yield` table; create only
  `budget_event` (+ account_run.budget_cap_cents). No generic run-telemetry table.
