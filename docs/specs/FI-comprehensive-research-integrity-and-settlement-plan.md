# Comprehensive Research Integrity and Settlement Repair Plan

**Status:** founder-ratified implementation plan  
**Date:** 2026-08-19  
**Branch:** `platform/comprehensive-account-contact-research`  
**Applies to:** newly launched comprehensive Account research and committee discovery jobs  
**Builds on:** `docs/FI-comprehensive-account-contact-research-contract.md` and
`docs/specs/FI-comprehensive-account-contact-research-plan.md`

## 1. Outcome

A confirmed comprehensive Account-research launch must do real, bounded work against its exact
immutable discovery selection, and an Account may settle only after every requested profile field
and committee source has an honest terminal disposition.

This repair keeps lineage integrity blocking while moving research-quality judgments out of the
execution stop path:

- discovery must be sealed once, inside the launch transaction;
- the resulting immutable seal receipt travels with every job authorization;
- downstream provider work consumes that receipt instead of revalidating mutable present-day
  discovery membership;
- coverage/finalization cannot close until each field is either evidence-backed or every
  authorized source for that field was actually dispatched and terminally settled;
- zero-result committee discovery cannot close until every authorized committee source was
  actually dispatched and terminally settled.

The result is best-effort research with a mechanical definition of done, not a completeness or
quality threshold. Empty fields remain valid; no-attempt fields do not.

## 2. Ratified policy line

### 2.1 Blocking integrity controls

These remain fail-closed:

1. exact subject identity and canonical entity binding;
2. workspace/tenant isolation;
3. explicit human authorization and exact directive/selection scope;
4. hard spend authority and provider reservation/settlement accounting;
5. idempotency and immutable replay identity;
6. no promoted claim without evidence;
7. an intact discovery seal at Account-research launch;
8. execution completeness before settlement, as defined in section 5.

### 2.2 Shadow/review quality controls

These may annotate, warn, or create review work, but do not stop authorized execution:

- coverage percentage floors;
- verification/faithfulness judge verdicts;
- expectations that a field contain a successful claim;
- expectations that every committee role be found or inferred;
- other semantic result-quality scoring.

Execution completeness is not a quality floor. It asks whether authorized work was attempted and
durably settled; it does not require the provider to find an answer.

## 3. Confirmed defects

### 3.1 Mutable seal revalidation

`DbSealedDiscoveryAccountManifestReader` reads the immutable manifest artifacts, but then calls
`discovery_manifest_members()` again and compares those stored manifests with a live claim query.
That live query can absorb later Account-profiling claims when they share the discovery item's raw
artifact key. The sealed generation is therefore incorrectly declared corrupt after legitimate
downstream work.

### 3.2 Launch receipt discarded

`AccountResearchFleetLauncher` already checks that discovery is sealed inside the launch
transaction, but discards the returned batch/generation/seal receipt. Each provider handler later
tries to rediscover authority from mutable current state.

### 3.3 No-work settlement

`AccountResearchStateStore.assess()` currently permits a zero-result close when its completed
fields are borrowed. It does not require unresolved fields to have exhausted their authorized
sources. The finalization engine checks pending operations, evidence, coverage shape, spend, and
state identity, but not the field/source attempt matrix. An agent can therefore run
`read -> assess -> finalize` and settle a 21-field profile after doing no provider work.

## 4. Immutable launch authority design

### 4.1 Receipt shape

Add a frozen `SealedDiscoveryLaunchReceipt` to the entity-research contract with:

- `discovery_batch_id`;
- `discovery_generation`;
- `discovery_seal_sha256`;
- `account_manifest_ref`;
- `account_manifest_sha256`;
- `claim_manifest_ref`;
- `claim_manifest_sha256`.

Add `discovery_receipt: SealedDiscoveryLaunchReceipt | None = None` to
`EntityResearchSelection`.

Compatibility rules:

- historical serialized authorizations remain readable because the field defaults to `None`;
- contact selections continue to use `None`;
- every newly compiled Account selection must carry a receipt;
- the launcher includes the receipt in `request_sha`, so the exact discovery seal is part of
  selection/run/job idempotency;
- no database migration is required because selection is already persisted as versioned JSON.

### 4.2 Launch transaction

Expand `require_sealed_account_discovery()` to verify and return the complete stored manifest
receipt. The launcher must:

1. take the existing launch advisory lock;
2. lock/read the current discovery batch;
3. require `SEALED` and validate exact project-run/ICP lineage;
4. verify the seal and stored manifest bundle agree;
5. verify every explicitly selected Account is in the stored account membership;
6. embed the receipt in the selection and request hash;
7. persist the run/jobs in the same transaction.

If discovery is absent, unsealed, terminal-unsealed, invalid, or does not contain an explicitly
selected Account, launch fails before any research run/job/provider write.

### 4.3 Stored-membership reader

At seal creation, `discovery_manifest_members()` remains the mechanism that captures the final
membership. After sealing, readers must validate the immutable stored forms against each other:

- seal row;
- `discovery_batch_manifest.account_ids` and `.claim_ids`;
- hashed account-manifest artifact;
- hashed claim-manifest artifact;
- frozen discovery plan and terminal field-resolution rows.

They must not recompute membership from live claims. Later claims cannot change a sealed receipt.

### 4.4 Downstream behavior

New Account jobs use `selection.discovery_receipt` as their authority. Provider preparation may
load the immutable manifest by that exact receipt, but must not require that it is still the
current generation and must not rebuild claim membership.

Any diagnostic comparison with live discovery membership is shadow-only telemetry. It must not
cancel, suspend, or reject a job that was validly launched.

Historical jobs without a receipt retain the corrected stored-manifest reader as their
compatibility path; they do not gain a fabricated receipt.

## 5. Definition of done

### 5.1 Account field disposition

For every field in the comprehensive 21-field profile, exactly one of these must be true before
coverage can be written or finalization accepted:

1. **Satisfied:** a fresh, conflict-free, evidence-backed claim/reuse/result/derivation answers the
   field under the existing scope policy; or
2. **Exhausted:** every source authorized and applicable to that field was actually dispatched and
   has a durable terminal result or settlement.

The launcher currently partitions the fixed profile into:

- acquisition fields, each with an exact `FieldSourceAuthority` source list;
- zero-acquisition fields:
  - `core.account_name`, satisfied by evidence-backed canonical/existing identity truth;
  - `core.employee_range`, derived from governed `core.employee_count` evidence;
  - `core.revenue_band`, derived from governed `core.annual_revenue` evidence.

A derive-only field is satisfied by its evidence-backed derived/reused claim. If it cannot be
derived, it is exhausted only when its source field has itself reached a terminal satisfied or
exhausted disposition.

### 5.2 What counts as a terminal provider attempt

For `(field_key, source_key)`, the durable entity-research ledgers must contain:

1. a tool request belonging to the exact job;
2. an observation bound to a provider operation;
3. a provider-operation row whose `source_key` and `field_keys` include the exact pair;
4. `dispatched_at IS NOT NULL`; and
5. either:
   - a durable `entity_research_result`, or
   - an idempotent `entity_research_provider_settlement_fold` representing a terminal provider
     rejection/empty failure that will never produce a result.

These do **not** count:

- a model tool call with no provider reservation;
- a reserved operation that was never dispatched;
- a waiting/joined in-flight operation;
- a platform validation or eligibility failure before dispatch;
- cancellation caused by a sibling task;
- a cancelled lease or process crash with no terminal provider settlement;
- an agent-authored `not_researched` reason.

A successful evidence-backed claim may stop the waterfall for that field. Remaining lower-priority
sources need not be called after the field is satisfied.

### 5.3 Committee disposition

If the selection authorizes committee discovery, coverage may settle only when either:

- at least one terminal committee result exists for an authorized source, including a genuinely
  `confirmed_empty_discovery` result; or
- every authorized committee source has a dispatched terminal result/settlement.

For the current Exa/Sumble pilot, the compiled committee source set is exact and normally contains
Sumble People. A zero-member outcome is honest only after that source was actually attempted.
Missing or uninferred committee roles remain a quality/review concern, not an execution blocker.

### 5.4 Enforcement points

Implement one shared, deterministic `AccountResearchExecutionCompleteness` reader derived from
the authorization plus durable result/operation/settlement ledgers.

Use it twice:

1. `AccountResearchStateStore.assess()` refuses to write a coverage row while required field/source
   or committee attempts remain unattempted/pending;
2. `AccountResearchFinalizationEngine.accept()` independently re-derives the same invariant and
   refuses finalization even if a malformed or historical coverage row exists.

The projection should expose unresolved execution pairs in tool-readable errors so the agent can
continue with the exact missing source work. It must not convert a quality gap into an integrity
failure after all applicable sources are terminal.

## 6. Implementation sequence

### Slice 1 - Freeze and repair discovery authority

- add the receipt contract to `clue_core.entity_research`;
- expand the launch readiness reader to load the stored manifest bundle;
- stop `DbSealedDiscoveryAccountManifestReader` from recomputing live claim membership;
- add exact-receipt read support while retaining the historical current-generation path;
- pin the complete receipt into the account selection and launch hash;
- enforce selected-Account membership at launch.

### Slice 2 - Consume receipt downstream

- thread the job authorization/receipt into Exa Account preparation, Sumble Account-gap
  preparation, and committee discovery eligibility/input compilation;
- use exact stored batch/seal membership for new jobs;
- retain compatibility for historical jobs;
- ensure a later profile claim or newer discovery generation cannot suspend already-authorized
  provider work.

### Slice 3 - Add execution-completeness reader

- compute evidence-backed satisfied fields;
- compute dispatched terminal `(field, source)` pairs;
- distinguish dispatched terminal settlement from reserved/pending/not-created work;
- project missing field/source pairs and committee-source pairs;
- account for the three zero-acquisition profile fields without authorizing fake provider calls.

### Slice 4 - Enforce assessment and finalization

- reject premature assessment with the exact outstanding work;
- remove the zero-result/no-work loophole;
- retain valid zero-spend closure when every field is already evidence-backed;
- independently enforce the invariant in finalization;
- retain honest `needs_review` settlement when all attempts are terminal but fields/roles remain
  unresolved.

### Slice 5 - Regression and integration proof

Add focused tests for:

1. later claims sharing a raw discovery artifact do not invalidate the seal;
2. stored manifest/artifact/hash tampering still fails closed;
3. `seal_pending` launch remains refused with `account_discovery_in_progress`;
4. selected Account absent from sealed membership is refused before run/job writes;
5. newly launched Account jobs pin the exact complete receipt and replay identically;
6. historical selection JSON without a receipt remains readable;
7. no-results/no-attempts cannot assess or finalize;
8. reserved-but-undispatched operations do not count;
9. dispatched-but-pending operations do not count;
10. dispatched terminal zero-result/failure settlement counts for its exact source/fields;
11. an evidence-backed field stops its waterfall without requiring lower-priority sources;
12. unresolved fields settle `needs_review` after all authorized sources are terminal;
13. committee discovery cannot settle before an authorized committee source is terminal;
14. `confirmed_empty_discovery` permits honest zero-member settlement;
15. cancellation of one parallel source does not mark sibling fields attempted.

Run the smallest focused suites first, then the comprehensive Account execution matrix and the
relevant API/static gates. Do not restart or mutate the preserved live Missoula runtime until the
code and database-backed regression suite are green. Do not touch Tunis.

## 7. File map

Expected primary files:

- `libs/clue-core/clue_core/entity_research.py`
- `platform/api/clue_api/account_research_discovery_readiness.py`
- `platform/api/clue_api/account_research_fleet_launch.py`
- `platform/api/clue_api/discovery_seal.py`
- `platform/api/clue_api/account_entity_research.py`
- Account Exa/Sumble/committee composition files identified by the receipt-threading trace
- focused `tests/api/` and `tests/core/` coverage
- `_memory/` operational closeout note

No schema migration is planned. If implementation proves the JSON receipt cannot provide the
required immutable authority, stop and amend this plan before introducing a table or migration.

## 8. Commit checkpoints

1. documentation: this ratified plan;
2. discovery receipt contract, launch pin, and immutable stored-membership reader;
3. downstream receipt consumption and compatibility path;
4. execution-completeness enforcement plus tests;
5. verification/memory closeout.

Stage paths explicitly. Never include the user-owned
`libs/clue-config/clue_config/settings.py` concurrency change in these commits.

## 9. Exit criteria

This plan is complete when:

- a new Account job cannot exist without a launch-pinned discovery receipt;
- provider work for that job cannot be invalidated by later mutable claim membership;
- corrupted stored seal/manifests still fail closed;
- `read -> assess -> finalize` with no adequate provider work is mechanically impossible;
- each of the 21 fields is settled as evidence-backed or exhausted across all exact authorized
  sources;
- committee zero-result settlement proves terminal source attempts;
- quality shortfalls produce honest gaps/review rather than blocking execution;
- focused database-backed tests pass;
- the intentional concurrency-default edit remains untouched and uncommitted by this work;
- Tunis remains untouched.

