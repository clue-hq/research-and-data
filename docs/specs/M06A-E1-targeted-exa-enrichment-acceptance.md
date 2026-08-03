# M06A E1 targeted Exa enrichment acceptance

- **Implementation status:** `PASS` on 2026-08-03
- **Live-provider status:** `OPEN` pending one eligible human-approved selected account
- **Branch:** `platform/c8-exa-sumble-discovery`
- **Implementation commit:** `e8270b4` (`feat(enrichment): add seal-bound Exa E1 imports`)
- **Migration:** `f2c0b2ed21dd` (single head)
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
not charged for null contact results.

## 5. Verification evidence

Against the dedicated PostgreSQL database:

- E1 adapter and database tests: **6 passed**;
- D2-D6 plus E1 and tier-checkpoint regression set: **71 passed**;
- Exa D0-D4 adapter/fixture set: **22 passed**;
- full mypy: **480 source files, no issues**;
- import-linter: **24 contracts kept, 0 broken**;
- targeted Ruff format/lint: pass; and
- Alembic `head -> base -> head`: pass with the single head `f2c0b2ed21dd`.

The repository-wide fail-fast run still reaches the already-recorded Stage-0 fixture failure where
the pinned `evaluate_stage0_readiness@1` schema digest is stale after the C8 merge. E1 does not
import or execute that surface; it remains untouched in this slice.

## 6. Live-provider gate

No paid E1 call was made during this implementation round. The D6 acceptance run has two held
accounts and zero human-approved selected accounts. Promoting either hold or fabricating a human
tier claim merely to make a provider call would violate E1's eligibility invariant.

To close the remaining provider gate, supply one genuinely approved selected account from an exact
sealed run and approve a bounded canary. The minimum ordinary-field canary is one account and one
field, with a maximum reservation of four credits: two for a resolved import plus two for the
ordinary enrichment row. The canary must prove the live import response, presigned upload, Webset,
item shape, realized receipt, and fresh-process zero-call replay before E1 is marked fully closed.
