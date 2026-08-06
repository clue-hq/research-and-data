# M06A E1 targeted Exa enrichment acceptance

- **Overall E1 gate:** `OPEN` pending the bounded live-provider canary
- **Mechanical/provider-contract status:** `PASS` after adversarial repair on 2026-08-03
- **Live-provider status:** `OPEN` pending one eligible human-approved selected account
- **Branch:** `platform/c8-exa-sumble-discovery`
- **Implementation commit:** `e8270b4` (`feat(enrichment): add seal-bound Exa E1 imports`)
- **Adversarial-repair commit:** `3b7458a` (`fix(discovery): harden D6 and E1 production lifecycle`)
- **Migrations:** `f2c0b2ed21dd` plus hardening head `fffa2a8ba17c` (single head)
- **Dedicated final regression database:** `clue_c8_e1_hardened_20260803`

This record covers E1 only. It does not authorize a held/excluded discovery account, Sumble gap
enrichment, contact discovery, or general Exa Search.

## 1. Implemented boundary

E1 is a separate post-seal acquisition ledger. It does not reopen the discovery batch, append to
the immutable D5 manifest, alter its field resolutions, or add another discovery-row charge.

Preflight requires every requested account to:

- belong to the exact current sealed batch for the project run and pinned ICP;
- still be the workspace-local canonical account survivor;
- have a canonical primary domain; and
- have exactly one live tier claim written by the human checkpoint, with source tier 1,
  `decision_basis=discovery_criteria`, `disposition=selected`, an eligible approved tier, and exact
  project-run/batch/seal/ICP lineage.

A machine-authored lookalike claim, hold, exclusion, stale seal, foreign workspace, merged loser,
or unsealed run fails before provider work. The request is bounded by explicit account and field
lists and versioned provider, pricing, field-policy, and observation-window values.

## 2. Provider workflow

The adapter implements the documented import-only sequence:

```text
create CSV import
  -> upload exact content-addressed CSV to one-time presigned URL
  -> create Webset with singular `import` and no `search`
  -> poll to idle
  -> exhaust item pagination
  -> reconcile items by sourceEntityId
```

The presigned URL is a `SecretStr`, is sent without the Exa API-key header, and is redacted from
the persisted import receipt. Create and upload request bodies are mechanically checked with an
HTTP mock at the real client boundary.

Terminal reconciliation requires the expected import id, company type, import source, Webset id,
empty evaluations, exact enrichment-definition/result coverage, and one-to-one
`sourceEntityId -> selected account` mapping. The resolved company URL must remain on the input
company domain. A mismatched domain is quarantined as `spend_outcome_unknown`; it creates no
claim and leaves the field decisions pending for operator review.

## 3. Durability and idempotency

Migration `f2c0b2ed21dd` adds:

- seal-bound targeted-enrichment operations;
- immutable ordered targets;
- immutable provider-response artifact events;
- immutable provider item snapshots; and
- per-account/per-field terminal outcomes.

The request fingerprint covers the exact seal, targets, field plan, provider/pricing contracts,
caps, and observation window. PostgreSQL reserves the operation before the first provider call.
Exact terminal replay reads the same operation and performs zero import, upload, create, lookup,
poll, or item-page calls. Equivalent claim materialization is content/artifact keyed and writes no
duplicate claim.

Artifact events use response identity rather than content key alone. Identical response bytes may
therefore legitimately occur at different lifecycle points, while replay of the same event is
idempotent.

Concurrent starters serialize on the durable dispatch claim: the winner performs one import call
and the loser returns `joined_in_flight`. A possibly accepted paid create is recovered by its
deterministic external id. An ambiguous crash before that create is quarantined rather than
blindly spending again.

Hardening migration `fffa2a8ba17c` and the repaired runtime additionally enforce:

- terminal and spend-quarantined operation immutability, including receipts and charges;
- exact workspace/account/field lineage for the human tier claim and every result claim;
- no second account/field purchase in the same stable observation window, even under a differently
  bundled request;
- one shared project-run budget reservation across D6 and E1, with actual charge settlement into
  `project_run.spent_cents` in the same transaction as terminal success;
- active `DEEP` phase for new E1 work, while the lifecycle worker can still drain accepted work;
- DSAR subject indexing for request, CSV, lifecycle, item, receipt, and manifest artifacts; and
- database-only terminal replay before artifact capture, preventing an erased artifact/subject edge
  from being resurrected by a retry.

The production Head-of-ABM tool is `enrich_selected_accounts@1`. It accepts only account ids and
approved field keys; provider descriptions, formats, and option vocabularies come from the pinned
field policy. New spend has its own default-off switch. Fleet polling is instead controlled by the
Websets lifecycle switch, so disabling new E1 work cannot strand an already accepted operation.

## 4. Spend settlement

The bounded database test requested one selected account and two ordinary enrichments:

| Component | Credits |
|---|---:|
| Resolved CSV import | 2 |
| LinkedIn URL row, terminal null | 2 |
| Revenue-band row, resolved | 2 |
| Discovery search rows | 0 |
| **Total** | **6** |

At the pinned Pro-plan allocation this reserves and settles `2.694` internal cents. The receipt
records the zero search component. The original sealed discovery operation's charge and state are
unchanged. Email/phone settlement is value-based at five credits per actual returned value and is
not charged for null contact results. A concurrent request sees the first operation's outstanding
reservation, and a terminal replay increments neither provider calls nor project spend.

## 5. Verification evidence

Against PostgreSQL and an isolated migration-smoke database after the repair:

- E1 adapter/tool/fleet/database tests: **4 passed**;
- repaired D2-D6 plus E1 and scoring-bypass regression set: **81 passed**;
- full mypy: **481 source files, no issues**;
- import-linter: **24 contracts kept, 0 broken**;
- targeted Ruff format/lint: pass; and
- Alembic `head -> base -> head`: pass on a newly created throwaway database, which was removed
  after the run, with the single head `fffa2a8ba17c`.

The DB suite also detected a historical long-lived-database drift from the D4 review-lineage
migration: an older single-column review-task FK and stricter stale shape check were still present.
The hardening migration idempotently restores the canonical workspace-composite FK and preserves
review lineage after admission; the adversarial cross-workspace case now fails at PostgreSQL.

## 6. Live-provider gate

No paid E1 call was made during this repair round. A read-only eligibility audit returned zero
active `DEEP` account/run pairs with the exact live human-selected tier and seal lineage. The D6
acceptance run likewise has two held accounts and zero human-approved selected accounts. Promoting
either hold or fabricating a human tier claim merely to make a provider call would violate E1's
eligibility invariant.

To close the remaining provider gate, supply one genuinely approved selected account from an exact
sealed run and approve a bounded canary. The minimum ordinary-field canary is one account and one
field, with a maximum reservation of four credits: two for a resolved import plus two for the
ordinary enrichment row. The canary must prove the live import response, presigned upload, Webset,
item shape, realized receipt, and fresh-process zero-call replay before E1 is marked fully closed.
