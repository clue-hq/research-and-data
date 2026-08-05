# M8C C6 — Provider-neutral contact preparation and composition acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** C0–C5 accepted contact contracts, snapshots, and durable operations
- **Branch:** `platform/c8-account-profiling-integration`
- **Recorded:** 2026-08-05
- **Status:** mechanically accepted; paid provider canaries and concrete selected-channel validator
  deployment remain separately gated

C6 composes the accepted contact capabilities behind one provider-neutral post-committee seam. It
does not introduce another project phase, fleet, or provider branch in `AccountDeepOrchestrator`.
The same durable selection and preparation authority is used by the existing account-deep fleet
and the independently invocable `profile_contact@2` tool.

## 1. Durable selection and steering authority

After committee identity, role plausibility, and persona claims exist for the exact account run,
`ContactResearchSelectionMaterializer` resolves the pinned research directive and current contact
policy into one content-addressed receipt. Automatic selection admits only strongly identified,
plausible committee members and professional/facet fields; it never turns the directive's coarse
reveal switch into email or phone authority.

The `contact_research_selection` table is immutable and exact-scoped to workspace, project run,
account run, account, directive, committee claims, contacts, and predecessor. Concurrent replay of
the same content elects one receipt and returns its original id. Steering is an append-only
`contact_research_selection_cancellation`; automatic re-entry observes the cancelled latest receipt
and cannot silently resurrect it. A different authority requires an explicitly approved successor.

## 2. Provider-neutral ordered preparation

`ContactResearchBatchPreparer` derives one immutable `ContactResearchIntent` per selected contact.
`RegisteredContactResearchPreparer` validates the active project run and cancellation state, proves
that every exact source-plan key has one and only one registered adapter, and then executes adapters
in source-plan order. A later, possibly paid adapter does not start while an earlier adapter is
waiting, paused, failed, or ineligible. Resume replays its ready snapshot and advances without a
second submit or settlement.

Production registration is provider-neutral:

- the existing Sumble committee snapshot supplies professional/team claims without another Sumble
  request;
- Exa Search contact acquisition and C4 snapshot materialization are registered behind an
  independently default-off feature flag; and
- C5 channel preparation is registered only when a concrete validator-backed coordinator is
  supplied. Enabling the feature without that production dependency fails startup loudly.

Every adapter returns only `READY`, `WAITING_EXTERNAL`, `BUDGET_PAUSED`, `NOT_ELIGIBLE`, or
`FAILED`, plus immutable operation/snapshot/settlement references. The orchestrator never inspects
provider identity.

## 3. Transaction and replay boundary

Project-run, selection, and cancellation checks happen in short database contexts that close before
an adapter may submit or poll. Provider acquisition owns its durable operation and snapshot first;
snapshot-backed materialization then runs separately in a short transaction.

For Stage 3B, the existing `profile_contact` worker accepts the exact prepared claim references.
That mode projects only current exact-contact claims and never enters its resolver waterfall. It
also excludes email and phone claims from generic profile output; channel eligibility remains the
separate governed C5/C7 surface. This makes an intentionally empty prepared field an honest empty
result rather than an accidental second provider call under the claim transaction.

## 4. Existing fleet wait/resume and independent invocation

`AccountDeepOrchestrator` still exposes the established sequence:

```text
profile_account -> discover_committee -> bounded profile_contact fan-out
```

After committee materialization it calls the injected contact-preparation protocol. A pending
operation folds selection, operation, snapshot, settlement, and audit refs into the existing
`account_run`, leaves the sub-phase at `COMMITTEE_DISCOVERED`, and returns the existing
`WAITING_EXTERNAL` shape. Resume reuses the account and committee work, re-enters preparation, and
fans out only the exact selected contacts and fields after `READY`.

The generic external-research wake dispatcher scans only enabled durable source registries,
deduplicates owning project runs, and re-offers them to the existing detached fleet. It does not
poll a provider itself. The former Sumble-only wake loop is therefore generalized without adding a
worker fleet or project phase.

`profile_contact@2` accepts an exact project run, account, and contact. The independent service
requires the directive-pinned account run at `COMMITTEE_DISCOVERED` or `CONTACTS_COMPLETE`, proves
the contact belongs to the materialized committee and selection, uses the same preparation seam,
and performs the same prepared-claim-only materialization. Historical `profile_contact@1` pins
remain addressable, while current research-agent profiles and delegation authority pin v2.

## 5. C6 exit-gate evidence

| C6 gate | Executable evidence |
|---|---|
| provider-neutral orchestrator | one injected `ContactStagePreparer`; no Exa/Sumble branch in the orchestrator |
| no new fleet or phase | generic wake dispatcher re-offers the existing project run; account sub-phase remains `COMMITTEE_DISCOVERED` while waiting |
| wait and resume | orchestrator regression proves first-run wait, second-run readiness, and no repeated account/committee work |
| durable cancellation/no duplicate spend | cancelled selection produces zero further adapter calls; same-content selection elects one receipt; ordered adapter test prevents downstream calls while waiting |
| independent contact | database test invokes the same selection/preparation seam for one exact committee contact and narrows fields |
| no network under claim transaction | adapter test asserts database context is closed; prepared-worker regression fails if the resolver-gap path is entered |
| existing paths regress | full repository suite and combined C4–C6/deep-orchestrator database suite pass on the final schema |

### Recorded mechanical verification (2026-08-05)

- A disposable PostgreSQL database passed `upgrade head -> downgrade base -> upgrade head`; the
  final database and repository both reported the single head `4d9b02f218dc`.
- The combined C4, C5, C6, API deep-orchestrator, and durable deep-orchestrator database regressions
  passed on that schema.
- The complete repository pytest suite passed against a newly created clean disposable database.
- Mypy passed for 537 source files. All 24 import-boundary contracts passed across 604 files and
  5,022 dependencies. Scoped Ruff format and lint checks passed for every C6-owned Python file.
- Repository-wide Ruff also traverses pre-existing untracked local skill directories, and the
  repository-wide format check names two unrelated pre-existing tracked files. Those user-owned
  files were not changed to manufacture a clean C6 result.

The seeded development database on port 55010 was not migrated or mutated. The destructive
migration cycle and affected regressions used the isolated C6 database on port 64466; the final
full-suite gate used a newly created clean database on port 64467. Re-running the complete suite on
an already-used test database reproduces known cross-suite seed/order pollution (principally
source-manifest redefinition and downgrade guards), so it is not treated as a C6 failure or hidden
as clean evidence.

## 6. Acceptance boundary

This record proves selection, registration, ordering, waiting, resume, cancellation, transaction
boundaries, independent invocation, and replay mechanics. It does not claim live Sumble/Exa or
validator traffic. Per the roadmap, paid calls require separate authorization and belong to V1.

The channel flag remains fail-closed until a concrete independently accepted validator coordinator
is deployed. That is an explicit deployment dependency, not permission to bind a fake validator or
to auto-reveal contacts. C7 may proceed on the mechanically accepted C6 interfaces; V1 remains the
provider-behavior release gate.
