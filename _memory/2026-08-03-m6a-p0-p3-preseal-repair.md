# M6A P0-P3 pre-seal waterfall repair — 2026-08-03

## Scope and decision

- Repaired the Stage-0 -> Exa D2-D4 -> required-field waterfall -> D5 seal order.
- An unresolved required attempted Exa field now remains `pending`; a durable pre-seal provider
  operation must terminalize it before D5 can seal.
- The pre-seal ledger is intentionally distinct from post-selection S1. S1 still requires the exact
  immutable seal, human-approved tier, and active `DEEP` phase.
- Exa and Sumble claims are independently preserved and reconciled through the existing merge and
  corroboration policy; Sumble never overwrites Exa by source precedence alone.

## Implementation

- Added provider-neutral discovery-gap contracts, the `6e8737f21ec4` migration, durable repository,
  operation/field immutability, shared project budget accounting, artifact lineage, and D5 barriers.
- Added the Sumble REST-v9 pre-seal coordinator for supported organization fields and explicit
  zero-call terminal dispositions for unsupported, disabled, or criteria-ineligible work.
- Shared one snapshot-to-claim materializer between the pre-seal waterfall and S1.
- Hardened Sumble organization identity matching to require the canonical requested domain and to
  reject ambiguous multiple matches.
- Corrected Stage-0 readiness replay so a reused decision id must match the complete canonical
  immutable payload; fixture-supplied metrics are checked as a subset of stored augmented metrics.
- Replaced ambiguous report `claim_count` semantics with `sealed_claim_count`,
  `field_resolution_claim_count`, and `materialized_provider_claim_count`.

## Verification

- Migration up -> down -> up succeeded on an isolated database; `6e8737f21ec4` is the sole head.
- Focused D1-D6/S1 tests passed. The opt-in committed gate passed `7 passed` and
  demonstrated one operation and one provider dispatch under concurrency.
- The final adversarial regression simulates a crash after field reconciliation but before the
  operation receipt/success update; a fresh D5 handler resumes from the stored response and seals
  without a second provider dispatch.
- Full mypy passed for 488 source files; import-linter kept all 24 contracts.
- Repository-wide pytest had ten failures outside this repair surface: stale agent-tool pins, older
  phase-transition fixtures, one global-state performance fixture, logging capture order, the
  pre-existing memory import boundary, and a stale ICP tier-plan expectation. They were not edited.

## Bounded live acceptance

- Dedicated database: `clue_m6a_live_p0p3_20260803`.
- Seeded the Insight Health/Aura Stage-0 handoff; production composition started in `DISCOVERY`.
- Exa create returned deterministic duplicate `409`; external-id lookup returned the existing paid
  Webset `webset_01kz3bczvnsh1svtzv4xg3psc8`, followed by live poll/items/events reconciliation.
- Made two new Sumble REST-v9 `/organizations` requests. Each charged 2 credits and resolved one
  missing `discovery.industry` field with an independent claim.
- Final aggregate: 32 provider units (28 Exa + 4 Sumble), 17 sealed claims, 14 field-resolution
  rows, 13 distinct linked field-resolution claims, and 17 materialized provider claims.
- Final field states: 13 resolved and 1 confirmed missing. Selection was 1 selected/human-approved
  into `DEEP`, 1 held for missing revenue, and 0 excluded. No numeric scoring claims were written.
- Seal: `ec6cef9abd2dedd8077b9edf187090af156b09e76ff37032f7e03f065b58fc88`.
- Fresh-process replay returned the same accounts and seal with zero Exa traffic. Database tests
  separately prove a sealed replay cannot enter the Sumble resolver.
- Sumble monetary allocation used zero cents per credit because no account-specific conversion was
  configured. Credits are exact; the monetary total intentionally contains only configured Exa
  conversion and must not be presented as a complete cross-provider cash cost.

## Remaining gates

- The post-selection S1 organization/jobs/technology parent-ledger live canary remains open; only
  the shared v9 organization endpoint and materializer were proven live in this repair.
- E1 retains its separately bounded live acceptance gate.
- Do not report the recovered Exa duplicate as a newly paid Webset creation: the create request was
  real, but the live run reused the deterministic existing Webset after the provider's `409`.
