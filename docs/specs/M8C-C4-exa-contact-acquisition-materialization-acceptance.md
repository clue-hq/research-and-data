# M8C C4 — Durable Exa contact acquisition and snapshot materialization acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** C0 selected-contact authority, C2 exact contact-subject durability, and C3
  contact-targeted Exa compilation
- **Branch:** `platform/c8-account-profiling-integration`
- **Recorded:** 2026-08-05
- **Status:** mechanically accepted; paid one-contact provider canary remains separately
  authorization-gated

C4 connects the C3 exact-contact request to the shared external-research durability substrate and
then replays its immutable snapshot through the existing governed contact-field worker. It does
not add a second fleet, a provider branch to the orchestrator, contact channel reveals, or Sumble
network traffic. C6 owns production preparation/wait/resume composition; C5 owns separately gated
email/phone acquisition and validation.

## 1. Acquisition and transaction boundary

`clue_api.exa_contact_acquisition.ExaDeepContactAcquisitionService` first compiles one selected
contact against the current database authority. A rejected selection, directive, policy, account,
contact, field, or exact `exa_deep` source plan exits before the coordinator and causes zero
provider calls.

The compiler database context is closed before any coordinator/provider dispatch. The shared
`ExaDeepAcquisitionCoordinator` then owns atomic reuse/reservation, exactly-once submit election,
response-first durability, normalization, receipt settlement, failure classification, and
crash/restart joining. Its short ledger transactions do not become claim transactions.

Every contact request artifact freezes:

- the `exa-search-contact-deep-acquisition-c4-request-v1` contract revision;
- complete external-research request lineage and request fingerprint;
- the complete C0 contact-intent digest;
- canonical person/employer target lock;
- exact field source plans;
- accepted C3 Exa configuration; and
- the exact provider wire request.

The response, normalization, and each retained result are immutable verified artifacts. The ready
snapshot is indexed by `subject_kind=contact`, exact contact, employer account, workspace,
directive, project run, source, and observation window; it cannot cross-satisfy an account or
another contact.

## 2. Cost truth and settlement

Exa's Search reference describes `costDollars.total` as an endpoint-dependent estimated dollar
cost. C4 therefore records and settles that provider-reported response estimate exactly once while
marking the receipt `pending_provider_billing`. The existing external-research reconciliation seam
is the authority for later provider billing evidence. Replay and claim materialization never
settle or charge again.

This distinction is deliberate: a provider response is durable cost evidence, but it is not
represented as a final invoice. Official reference: <https://exa.ai/docs/reference/search>

## 3. Snapshot authority and same-name defense

`clue_api.exa_contact_materialization.ExaDeepContactSnapshotResolverProvider` obtains only ready,
fresh snapshots for the exact selected intent. Before exposing any candidate it verifies the
integrity and cross-consistency of the request, response, normalization, and every result artifact;
reconstructs the accepted C3 preflight; recomputes exact-person/employer normalization; and checks
provider request id, reported cost, all-null disposition, requested fields, source plans, and
relational artifact indexes.

Only a C3 `exact` candidate with an inspectable evidence span and retained result artifact reaches
the provider-neutral snapshot resolver. Same-name/wrong-employer and contradictory-profile
results remain in the immutable normalization for audit but produce no claim. Newer ready
snapshots shadow older ones per requested field, and materialization fails closed unless the
selected field set is completely covered.

## 4. Governed contact materialization

`GroundedContactSnapshotResolver` is a materialization-only implementation of the existing
provider-neutral `Resolver` seam. It performs no network or database I/O and exposes only the exact
contact's grounded `contact.facet.*` candidates with complete operation, snapshot, provider-request,
and result-artifact lineage.

`ExaDeepContactSnapshotMaterializer` opens the claim transaction only after snapshot verification.
It binds the resolver for the run and calls the existing `fill_contact_field` worker for every
selected facet. The worker revalidates the current canonical contact/account, planning budget,
exact effective source plan, personal-data policy, identity binding, use class, pre-spend decision,
and claim-store insertion. The immutable snapshot plan must equal the planner's current plan;
policy or source-plan drift fails closed rather than silently rematerializing stale authority.

## 5. Exit-gate evidence

| C4 gate | Executable evidence |
|---|---|
| non-eligible/unselected contact makes zero calls | a stale-policy selected intent is rejected during database compilation and the recording transport remains unused |
| one eligible intent creates one request | the populated synthetic handoff compiles one bounded bundle, persists one contact operation/snapshot, and calls the recording transport once |
| provider request is outside claim transaction | the test connection tracker proves no compiler/materialization database context is active when transport dispatch occurs |
| ready snapshot produces governed claims | immutable replay through `fill_contact_field` writes the strongly bound, use-classified facet with exact four-part Exa lineage |
| same-name/employer mismatch fails closed | wrong-employer and contradictory-profile fixtures remain reviewable normalization rows and write zero claims |
| cost settles once | response cost produces one receipt and one settled operation; replay returns the ready snapshot without another receipt or transport call |
| crash/restart does not duplicate submit | a simulated post-dispatch process crash leaves one active operation; a fresh coordinator joins it without another provider call or operation |
| fresh-process replay is provider-free | a new provider/materializer instance reads verified artifacts and returns the same claim refs with zero transport traffic |
| malformed charged response remains auditable | the raw response is retained, the operation becomes terminal spend-unknown, and no fabricated receipt or ready snapshot is created |

## 6. Verification recorded

Recorded on 2026-08-05:

- all five C4 real-Postgres tests passed against the populated synthetic development database;
- 23 combined C3/C4/E1/E2 tests passed;
- 86 contact/external-research/governance regression tests passed;
- the complete repository test suite reached 100% with exit code 0 against a separate disposable
  database migrated from base to the single Alembic head `f9281fac77e1`;
- the disposable database completed head-to-base-to-head migration smoke and was deleted afterward;
- Ruff passed across repository source/test directories;
- mypy passed over all six changed C4 production modules;
- all 24 import-linter contracts passed over 596 files and 4,913 dependencies; and
- the repository-wide mypy command was also run and reported the existing baseline of 1,263 errors
  in 189 files, beginning in legacy merge migrations and unrelated tests. C4 adds no production
  mypy error; its test-only check reaches one pre-existing untyped fixture in
  `tests/profiling/conftest.py`.

The database tests used a recording Exa transport with real persistence and governance plumbing;
they did not contact Exa or consume provider spend. No Sumble call belongs to C4. The paid
one-contact Exa canary remains an explicit acceptance action after separate authorization and must
prove real endpoint traffic, immutable provider artifacts, receipt/settlement, governed downstream
claim output, and zero-traffic replay before it may be described as live accepted.

## 7. C5/C6 handoff

C5 may add separately authorized email/phone operations and independent validation without
modifying this contact-facet acquisition path. C6 should compose the C4 acquisition and
materialization services behind the provider-neutral contact preparation outcome, translate
incomplete external work into `WAITING_EXTERNAL`, and wake/resume the existing account-deep fleet.
It must not place polling inside `fill_contact_field` or add an Exa-specific orchestrator branch.
