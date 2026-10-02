# Record-only spend caps (founder ruling 2026-08-20, ruling 2)

Ruling source: `_memory/2026-08-20-seven-fix-night-close-out.md` §"Founder rulings 2026-08-20",
item 2 — *"Spend caps exist but do not block, for now."* Our own cost refusals on the Sumble
account-gap and committee-acquisition paths become record-only in the pilot posture: exact
accounting, loud log + metric, never a refusal that stops an otherwise-authorized provider call.

## Mechanism (no new flag)

Reuses the existing FI pilot switch `Settings.budget_controls_enabled` (`CLUE_BUDGET_CONTROLS_ENABLED`;
`INTEGRATION_PILOT_OVERLAY` already sets it False, and `.env` here sets `CLUE_PRODUCT_PATH=integration_pilot`),
threaded as `enforce_budget` from the composition roots that already threaded it.

New single decision point: `subsystems/research/clue_research/durable/spend_posture.py` —
`cap_refusal_is_enforced(enforce_budget, *, site, reason, amounts)`. Returns True → caller still
raises (today's behaviour). Returns False → emits `spend_cap.record_only` (structlog, with amounts)
plus the `research.spend.cap_record_only` counter labelled `{site, reason}`, and the caller proceeds.
Callers keep their own comparison, so nothing is recorded for a request that was within its cap.

## Sites converted

| site | reason | file |
| --- | --- | --- |
| `sumble_account_gap_preflight` | `cap_below_bounded_maximum`, `value_below_authorized_cap` | `platform/api/clue_api/sumble_account_gaps.py` |
| `sumble_account_gap_dispatch` | `charge_above_authorized_cap` (the one that fired live 2026-08-19) | same |
| `sumble_account_gap_reservation` | `reserved_units_above_cap`, `reserved_cost_above_cap`, `value_below_reserved_units` | `durable/account_gap_enrichment.py` |
| `sumble_committee_preflight` | `wire_plan_above_credit_cap`, `wire_plan_above_money_cap` | `platform/api/clue_api/sumble_committee_acquisition.py` |
| `sumble_committee_reservation` | `reserved_units_above_cap`, `reserved_cost_above_cap` | `durable/committee_acquisition.py` |
| `project_run_provider_spend` | `project_run_cap_exceeded` | `durable/provider_spend.py` — was *already* record-only; only the announcement is new |

## Accounting invariant kept, not weakened

`account_gap_operation_bounded_charge` (`unbounded_call_approved OR charged <= reserved`) and the
`AccountGapOperation` model validator still hold. Because the preflight cap refusal is now skipped,
a request could be charged the bounded maximum while reserving less — so
`_authorized_provider_credit_cap()` **raises the reservation to the bounded worst case** in the
record-only posture (reserve honestly larger, never relax the CHECK). That number is durable, so
`SumbleAccountGapStarter` re-derives it the same way before comparing a replay's stored
authorization; otherwise an exact replay of the caller's own arguments would read as a changed
authorization. Committee reservations are already the wire plan's own maximum and need no raising.

## Deliberately NOT converted

- **`allow_unbounded_tech` coherence** (`(_TECH in field_keys) != allow_unbounded_tech`, preflight).
  Not a cap: it refuses nothing on amount, it makes the caller state which shape it is buying, and
  the value is durable (`unbounded_call_approved`) and load-bearing for the bounded-charge CHECK
  *and* for `AccountGapOperation._coherent`. Silently deriving it would either corrupt the
  accounting or force weakening the invariant. Both directions cost zero and are trivially
  satisfiable by the caller.
- Provider truth: a real Sumble 4xx (`_mark_provider_rejected`), `SumbleCreditContractViolation`
  (provider charged above its own documented maximum), and the `spend_outcome_unknown` quarantine.
- A9 idempotency / same-window field re-buy guard / every structural + authority gate (incl. the
  M9.1 pre-spend authority gate, which the FI ruling keeps on in both modes).
- **Out of the ruling's named scope, same shape if it is ever extended:**
  `durable/discovery_gap.py:186`, `durable/targeted_enrichment.py:128`,
  `platform/api/clue_api/sumble_discovery_gaps.py` — reserved-vs-cap refusals on the *discovery*
  and Exa targeted-enrichment paths. One `cap_refusal_is_enforced(...)` clause each.

## Tests

`tests/api/test_pilot_provider_cap_record_only.py` (5 tests, DB-backed, rollback-only; reuses the
S1 and S2B harnesses). Both directions are pinned in each test: enforcing arm asserts the original
refusal/message, record-only arm asserts the proceed + exact ledger numbers + the log/metric pair.
Red-proofed in both directions — forward (all three cap tests failed before the conversion) and
reverse (stubbing `cap_refusal_is_enforced` to always record-only failed the same three, so the
enforcing pins are not vacuous). Each posture gets its own `rollback_conn`/seeded account: gap
purchases are append-only and same-window-unique, so the two arms cannot share one transaction.

Green: the new suite, plus `test_sumble_account_gaps_s1`, `test_sumble_committee_acquisition_s2b`,
`test_sumble_unreconciled_spend_settlement_db`, `test_pilot_budget_controls`,
`test_comprehensive_account_execution_db`, `test_fi2_63_sumble_freshness_db`,
`test_account_research_fleet_launch_r6_db`, and a 288-test `tests/api` sweep. ruff + mypy clean.

Pre-existing, unrelated failures on this branch (identical with and without this change, verified by
stash): `tests/api/test_frontend_bulk_actions.py` (3, `lookupWorkEmails` capability) and 21 in
`tests/durable` + `tests/integration` (Lane E/F, FI-2 read layer).
