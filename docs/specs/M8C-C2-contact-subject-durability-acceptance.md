# M8C C2 — Exact contact-subject durability acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** accepted M8C C0 subject contracts and the M8B external-research ledger
- **Branch:** `platform/c8-account-profiling-integration`
- **Accepted:** 2026-08-05
- **Status:** mechanically accepted after atomic-reservation and mandatory-Exa-lineage
  remediation; no provider call, contact field materialization, reveal, or fleet scheduling

C2 makes the existing provider-neutral external-research ledger safe for exact-contact work before
C3 compiles contact-targeted Exa requests. It preserves the account-deep behavior accepted in M8B:
one ledger and one dispatcher serve both subject kinds, and no provider-specific project phase or
contact orchestrator is introduced.

## 1. Exact durable subject

`ExternalResearchOperationRow` and `ExternalResearchSnapshotRef` now expose and validate the
immutable tuple:

```text
(workspace_id, subject_kind, account_id, contact_id)
```

An account subject requires `contact_id IS NULL`; a contact subject requires a non-null contact
under the exact account. New operations fail closed unless both entities belong to the workspace
and are their current canonical survivors. The database independently enforces the same
account/contact shape and canonical relationship at operation insertion.

The C2 migration copies the operation subject onto immutable snapshots and snapshot-use receipts,
then enforces equality between all three records. Contact claims carrying Exa external-research
lineage must name the exact snapshot contact; account claims retain the exact-account rule. A
same-name or same-employer contact cannot satisfy any of these joins.

## 2. Lookup, reuse, and replay

Reusable-operation, ready-snapshot, and active-materialization lookups compare `subject_kind`,
`account_id`, and `contact_id` explicitly. Account defaults remain backward-compatible, but an
account lookup cannot see contact snapshots and a contact lookup cannot see another contact's
snapshot. Subject-specific partial indexes support account and contact ready/replay paths.

The exact subject is also part of immutable replay validation. C2 proves that contact-specific
request and reuse fingerprints differ when the canonical contact/strong profile identity differs,
and a deliberately colliding fingerprint with another contact fails closed. C3 owns the production
Exa contact compiler that will generate these fingerprints from its exact-person/employer wire
request; C2 owns the ledger rule that prevents a compiler or caller from replaying them across
subjects.

`reserve_external_research_operation(...)` is now the sole owner of the provider-neutral,
transaction-scoped reuse lock. Under that lock it repeats semantic reuse lookup, exact replay
validation, shared-capacity admission, and insertion. A caller may use an unlocked lookup only as
an optimization; correctness no longer depends on manually composing
`lock -> lookup -> reserve`. Two fresh processes that call the public reserve function directly
elect one operation, including when their exact request fingerprints/windows differ but their
immutable wire request and semantic reuse identity are the same.

Once the winner reserves the operation, the other process joins it. Dispatch lease ownership,
attempt ordinal, receipt, snapshot, and spend settlement remain generic to the operation rather
than branching on provider or subject kind.

## 3. Merge and crash behavior

External provider history is immutable. If a contact is merged after acquisition, the historical
loser operation and snapshot remain auditable, but new lookup, adoption, or materialization through
the loser fails. The survivor cannot silently inherit that snapshot by name or employer; the next
slice must compile a survivor-specific request and fingerprint. A response that settles after a
merge may be preserved as paid provider history, but it is not materialization-eligible for either
the loser or survivor without a new governed operation.

A dispatch owner that crashes before a durable provider outcome is not retried as if no request
occurred. Before lease expiry, another process joins the active operation. After expiry, the
operation becomes spend-outcome-unknown and remains quarantined with one attempt and no invented
receipt, snapshot, or zero-cost assumption. Fresh-process ready replay adopts the immutable
snapshot and performs no HTTP or additional settlement.

## 4. Migration

Alembic revision `9e3afe93b8e1` adds C2's exact subject shape. Follow-up revision
`f9281fac77e1` closes the audited reservation and Exa-lineage gaps and is the repository's sole
head. Together they add:

- exact subject columns, foreign keys, and shape checks to snapshots and snapshot-use receipts;
- operation-canonicality, operation/snapshot equality, and snapshot-use equality triggers;
- contact-aware account/contact ready, snapshot, and adoption indexes; and
- exact account-versus-contact external-research claim-lineage enforcement;
- a database check requiring every `exa_deep` claim to carry operation, snapshot, provider-request,
  and result-artifact references; and
- an upgrade preflight that rejects legacy Exa rows with missing lineage instead of fabricating a
  backfill.

The first upgrade backfills every existing snapshot and use receipt from its immutable operation
subject. The hardening upgrade accepts only already-complete Exa lineage. Downgrade restores C2's
exact-subject but formerly optional Exa-lineage validator, then the prior account-only
snapshot/use schema and indexes.

## 5. Exit-gate evidence

The C2 tests prove:

1. account and contact snapshots cannot cross-satisfy;
2. two same-name contacts with different LinkedIn strong keys cannot reuse or materialize one
   another's operation, snapshot, use receipt, or claim lineage;
3. two fresh processes calling the public reserve API directly elect exactly one operation;
4. a simulated post-dispatch crash produces one attempt and no duplicate submit or charge;
5. ready replay in a new process adopts the same snapshot with zero provider calls;
6. a merged loser is rejected while its immutable history remains auditable;
7. account-deep E1/E2 acquisition and materialization remain compatible; and
8. exact Exa lineage succeeds, while all-null, partial, wrong-subject, wrong-snapshot, and
   wrong-result-artifact lineage fail at the database boundary;
9. pre-E1 resolver/verification doubles cannot impersonate the production `exa_deep` source; and
10. the migration passes upgrade to head, downgrade to the prior head, upgrade to head, and the
    complete head-to-base-to-head smoke on an isolated database.

Verification recorded on 2026-08-05:

- the focused C2, E1/E2, A1, contact-governance, resolver, and verification regressions passed;
- the complete clean-database pytest suite reached 100% with exit code 0 from 3,398 collected
  tests;
- Ruff lint and format checks passed on every C2 Python file;
- mypy passed across all 525 source files;
- all 24 import-linter contracts passed; and
- downgrade `f9281fac77e1 -> 26eaa6262063`, re-upgrade, and `alembic heads` reported only
  `f9281fac77e1`.

All provider-call counters in C2 acceptance remained zero. The durable response and $0.03
settlement used by the process test are synthetic ledger inputs, not an Exa or Sumble call or
provider charge.

## 6. Boundary retained

C2 does not compile an Exa contact request, call Exa or Sumble, materialize a contact facet, reveal
email or phone, or add a wake worker. The existing generic dispatch lease plus exact-subject rows
are the provider-neutral wake-dispatch foundation. C3 owns contact-targeted Exa compilation; C4
owns live durable acquisition and snapshot-backed materialization; C6 owns generic scheduling and
fleet composition.
