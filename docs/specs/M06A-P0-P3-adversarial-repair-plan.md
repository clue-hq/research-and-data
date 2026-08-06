# M06A adversarial repair plan — P0 through P3

**Status:** `PASS` on 2026-08-03

**Authority:** contract delta to `M06A-exa-websets-sumble-discovery-integration.md`

**Scope:** repair the Stage-0 -> Exa discovery -> required-field waterfall -> D5 seal path without
weakening the existing post-selection E1/S1 eligibility contracts.

## 1. Binding sequencing decision

Required discovery-envelope fields are resolved while the discovery generation is still open.
They are not repaired by mutating a D5 seal and they do not require a fabricated human tier claim.

```text
confirmed Stage-0 handoff
  -> Exa acquisition and terminal reconciliation
  -> D4 identity admission and Exa claim materialization
  -> required missing field = pending
  -> deterministic next-source decision
       -> eligible + source enabled: one durable, bounded provider operation
       -> ineligible: terminal blocked-by-policy decision, zero provider calls
       -> no supported source: terminal confirmed-missing decision, zero provider calls
  -> pending resolution transitions once to resolved / conflict / confirmed-missing /
     blocked-by-policy
  -> D5 manifests include the waterfall claims, receipts, and settled spend
  -> immutable D5 seal
  -> scoring-disabled discovery-criteria selection
  -> human tier checkpoint
  -> optional selected-account E1/S1 in DEEP
```

The existing selected-account S1 contract remains exact-seal + exact-human-tier + active-DEEP
only. Pre-seal operations use a separate provider-neutral ledger because retrofitting nullable seal
and tier identifiers into the S1 request would weaken its database guarantees and invalidate the
fingerprints of already durable S1 requests.

## 2. P0 — required-field sequencing and seal correctness

### Design

- D4 writes `pending` only for an unresolved **required attempted** field. Hard identities still fail
  closed; optional attempts still receive an honest terminal missing outcome.
- A discovery-gap orchestrator runs only after Exa operations, pagination, reconciliation, identity
  admission, and D4 materialization are complete. It never holds a database transaction across a
  provider request.
- One operation is keyed by workspace, batch, canonical account, source, observation window, and a
  fingerprint over the exact field plan and provider/pricing contracts.
- Eligibility requires: the exact active current unsealed batch; the canonical admitted survivor;
  a pending required-field resolution; every required Exa criterion equal to `yes`; the source in
  the canonical field's registered tier plan; positive expected value; and a bounded project/provider
  reservation.
- A provider-disabled or criteria-ineligible decision is terminal and explicit, with zero spend. It
  cannot leave discovery waiting forever.
- Sumble and Exa claims remain independent. Resolution uses the ordinary claim merge and
  corroboration policy; disagreement becomes `conflict`, never a provider overwrite.
- D5 readiness includes discovery-gap operation terminality and spend reconciliation. Its claim and
  raw-artifact manifests include the gap claims, raw request/response, and receipt. Sealing while a
  gap operation is planned, running, materializing, failed-retryable, or spend-unknown is forbidden.

### Acceptance

1. A real PostgreSQL run cannot seal while one required resolution is pending.
2. An all-yes account with one missing Sumble-supported field reserves once, dispatches at most once,
   materializes evidence, terminalizes the original resolution, and then seals.
3. An unclear/no/missing-criterion account makes zero Sumble calls and receives a terminal policy
   disposition before seal.
4. Disabled provider, exhausted budget, foreign tenant/account/batch, non-canonical account, stale
   generation, and field-plan/source mismatch all fail before provider I/O.
5. A crash after possible dispatch becomes spend-unknown and blocks the seal; it is never
   automatically retried.
6. Same-process, fresh-process, and concurrent replay create no second operation, claim, charge, or
   provider call.
7. The sealed claim/raw manifests and settled cost include the pre-seal waterfall work; late writes
   cannot change the seal.

## 3. P1 — Stage-0 replay and provider-contract truth

### Stage-0 fixture

`evaluate_readiness` owns the canonical persisted metric shape, including workspace-readiness
augmentation. It must compare the complete immutable replay payload, not silently accept a reused id
with changed metrics. The Insight Health fixture verifies its supplied metric subset against that
canonical record instead of comparing an unaugmented local dictionary with the augmented row.

### Sumble contract

The implementation remains explicitly pinned to the v9 wire contract until a bounded live canary
proves or disproves that endpoint. Current public documentation advertising another version is a
deployment-risk signal, not evidence that v9 is unavailable. A golden request/response fixture must
be independent of the adapter. A live canary records the actual path, request id, credits used,
response artifact, normalized claim, and a zero-call fresh-process replay. If v9 returns a terminal
version/path error, a separately versioned adapter is required; no silent path substitution is
allowed.

### Acceptance

- The fixture seeds and replays on a clean migrated PostgreSQL database with identical ids and table
  counts.
- A changed readiness metric under the same decision id is rejected.
- The independent Sumble wire fixture and parser/normalizer tests pass.
- The bounded live canary outcome is reported as live success, live contract failure, or blocked by
  credentials/configuration—never as mechanical PASS.

## 4. P2 — adversarial coverage

The acceptance suite must contain real-PostgreSQL tests for:

- production sequencing from a Stage-0 handoff (no manual phase jump and no synthetic tier claim);
- provider-disabled and criterion-ineligible zero-call paths;
- cross-workspace, wrong batch, stale generation, merged-loser, field/source mismatch, and project
  budget rejection;
- duplicate/concurrent reserve, fresh-process replay, and crash-after-dispatch quarantine;
- independent Exa/Sumble claim preservation plus resolution conflict;
- D5 manifest membership and the hard phase barrier; and
- exact account-subject reachability and tombstoning for every new content artifact; immutable
  bounded operation/field receipts remain as the non-content audit ledger under the existing
  retention contract.

Mocks are allowed at the HTTP boundary to drive failure timing, but PostgreSQL, storage, claim merge,
discovery resolution, manifests, and project phase transitions are real.

## 5. P3 — reporting semantics

Reports must use distinct names and definitions:

- `sealed_claim_count`: number of claim ids in the immutable D5 claim manifest;
- `field_resolution_count`: number of discovery-field resolution rows, including honest terminal
  missing/policy outcomes that do not have a value claim;
- `field_resolution_claim_count`: distinct claims linked through discovery field resolutions;
- `materialized_provider_claim_count`: provider claims created/reused by the materializer; and
- `provider_units_charged` / `cost_cents_charged`: settled values from all acquisition and pre-seal
  gap operations included in the seal.

No generic `claim_count` may represent only one of those populations. Acceptance compares every
reported count with a direct database/manifest read.

## 6. Implementation order and stop conditions

1. Repair and test readiness replay.
2. Add the provider-neutral discovery-gap contracts, migration, repository, and DSAR lineage.
3. Change D4 required-missing outcomes to `pending` and add pure eligibility/source planning.
4. Add the bounded Sumble organization coordinator and resolution reconciliation.
5. Compose the orchestrator before D5 seal creation and include its claims/artifacts/spend in D5.
6. Add the adversarial real-PostgreSQL suite and fresh-process replay.
7. Correct report fields and reconcile them against sealed artifacts.
8. Run migrations up/down/up, focused tests, static checks, bounded live canary, and terminal replay.

No later step is accepted while an earlier invariant is red. A paid live failure does not justify
weakening an eligibility, budget, provenance, or seal guarantee.

## 7. Acceptance record

### Mechanical and database evidence

- Migration `6e8737f21ec4` upgrades from `bd0b7e62a2b4`, downgrades cleanly, and is the sole head.
- The impacted D1-D6/S1 suite passes against a dedicated migrated PostgreSQL database. The opt-in
  committed gate runs two independent database connections concurrently and proves one durable
  operation and one provider dispatch.
- A process-death regression interrupts after field reconciliation but before the operation receipt
  and success update; a fresh D5 handler resumes the durable `materializing` operation from its
  stored response, emits the receipt, and seals without a second provider dispatch.
- Fault tests cover disabled/unclear zero-call paths, project budget rejection, foreign workspace,
  merged-loser rejection, source/item lineage tampering, crash-after-dispatch quarantine,
  terminal immutability, Exa/Sumble conflict preservation, subject-artifact tombstoning, sealed
  replay, and the aggregate-cost fold after Sumble settlement.
- Full mypy passes for 488 source files; all 24 import contracts are kept.

### Bounded live evidence

The dedicated database `clue_m6a_live_p0p3_20260803` was migrated and seeded from the
Insight Health/Aura Stage-0 handoff before production composition ran.

| Evidence | Result |
|---|---|
| Exa submit path | create attempt `409`, deterministic external-id lookup `200`, then live poll/pages |
| Exa Webset | `webset_01kz3bczvnsh1svtzv4xg3psc8` |
| Accounts | 2 |
| New Sumble calls | 2 REST-v9 `/organizations` requests |
| Sumble request ids | `019fc879-0a48-7971-8df7-0bd48a6cdada`, `019fc879-0cce-7978-bfe6-b1dd655cf8de` |
| Sumble credits | 4 charged, 2 per matched account |
| Sumble outcomes | 2 `discovery.industry` fields resolved with independent claims |
| Final provider units | 32 = 28 Exa + 4 Sumble |
| Final field states | 13 resolved, 1 confirmed missing |
| Immutable seal | `ec6cef9abd2dedd8077b9edf187090af156b09e76ff37032f7e03f065b58fc88` |
| Counts | 14 field-resolution rows, 17 sealed claims, 13 field-resolution claims, 17 materialized-provider claims |
| Selection | 1 selected/approved for `DEEP`, 1 held for missing revenue, 0 excluded |
| Fresh-process replay | same 2 accounts and seal; Exa create/lookup/poll/pages/events all zero |

The two stored Sumble response artifacts have the live v9 envelope keys `id`, `credits_used`,
`credits_remaining`, `organizations`, `matched_count`, and `total`; each matched organization has
`input`, `attributes`, and `entities`, with the selected attributes `id`, `name`, `url`,
`sumble_url`, and `industry`. This closes the v9 organization-field contract used by the pre-seal
waterfall. It does not claim live closure for E1 or the post-selection S1 jobs/technology endpoints.

### Repository-wide baseline

The repository-wide pytest run completed with ten failures outside this repair surface: stale
agent tool pins, older phase-transition fixtures, one global-state performance fixture, logging
capture order, the pre-existing memory import boundary, and a stale ICP tier-plan expectation.
The focused D1-D6/S1 suites, static typing, imports, migration, committed concurrency gate, and
live/replay acceptance above are green; these unrelated failures were not edited in this repair.
