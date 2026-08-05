# M8C C5 — Selected-contact channel enrichment and validation acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** C0 selected-contact authority and the M8B/C4 durable provider substrates
- **Branch:** `platform/c8-account-profiling-integration`
- **Recorded:** 2026-08-05
- **Status:** mechanically accepted; paid selected-contact provider canary and concrete production
  validator binding remain separately authorization- and composition-gated

C5 implements one exact-contact, exact-channel enrichment operation. Exa Websets is the selected
acquisition adapter. Independent corroboration/reachability remains behind the provider-neutral
`ContactChannelValidator` seam; C6 owns the concrete production registration and wake/resume
composition. C5 does not add a fleet, project phase, provider branch to the orchestrator, or
automatic reveal after committee discovery.

## 1. Authority before traffic

`compile_contact_channel_preflight` re-resolves every mutable database authority before the first
pre-spend decision or provider call:

- the immutable selected-contact receipt and its complete effective-policy digest;
- the exact target contact and separately approved email or phone authorization;
- the confirmed research directive, including `contact_profiling_allowed=true` and
  `contact_reveals_allowed=true`;
- the exact project run, workspace, project, account, and directive ICP;
- canonical non-merged account/contact ownership and an approved strong profile host;
- a current provenance-backed jurisdiction claim and no standing objection;
- one active acquisition source and one different active validation source, each declaring the
  exact channel field; and
- separate acquisition and validation native-unit and monetary caps.

The confirmed directive grants only the general ability to perform contact reveals. The later
human-approved selected-contact receipt is the narrower authority for the contact, channel,
provider, validator, field, and budgets. A policy-disabled reveal, directive-disabled reveal,
unselected contact, or email-only approval presented as phone exits before provider traffic.

## 2. Exa Websets acquisition contract

C5 reuses the accepted repository transport contract
`exa-websets-v0-openapi-2026-08-03` and pins the current effective acceptance reference into every
request fingerprint. One canonical professional-profile URL is placed in a one-row person import;
one and only one approved `email` or `phone` enrichment is attached to a run-scoped Webset. The
stable `externalId` is derived from the complete content-addressed request.

The public Websets guide documents person imports, asynchronous Websets, external ids, and email
and phone enrichment formats. Those public pages are supporting documentation, not evidence of
this deployment's entitlement or billing behavior:

- <https://exa.ai/docs/websets/api-guide>
- <https://exa.ai/docs/websets/api-guide-for-coding-agents>

The operation records the request, imported CSV, sanitized import response, Webset create/poll,
the exact returned person item, validation result, and no-raw terminal receipt as immutable
artifacts. Every artifact is indexed to the exact contact for DSAR and retention handling. Provider
traffic occurs outside database and claim transactions.

## 3. State, spend, and crash boundaries

The append-only request ledger has independent acquisition and validation spend outcomes:

```text
planned -> submitting -> waiting_external
         -> ready_to_validate -> validating
         -> succeeded | rejected | failed_terminal | spend_outcome_unknown
```

The observed claim, lawful-basis record, operation linkage, acquisition charge, and project-run
spend increment commit atomically. A process cannot leave a detached raw channel claim or a
charged ready operation without the matching budget debit.

Immediately before the possibly-paid validator call, C5 atomically leases
`ready_to_validate -> validating` and marks validation spend unknown. A live lease joins without a
second call. An expired lease is quarantined as `spend_outcome_unknown`; C5 never guesses that an
interrupted validator dispatch was free. A terminal validation result, validation/receipt
artifacts, exact provider units/cost, and budget debit then commit together.

Database checks and triggers independently reject:

- cross-workspace/account/contact operations;
- request mutation or deletion and any mutation after terminal state;
- channel/field mismatch or acquisition and validator source equality;
- ready/success states without charged observed evidence;
- success without charged, use-allowed independent validation;
- observed claims that lack exact operation, artifact, field, contact, source, weak-binding, or
  tenant-private lineage; and
- reuse receipts that do not point to a successful exact-subject operation.

Fresh cross-window reuse is allowed only while both freshness and retention remain valid and the
complete provider contract, validator contract, pricing policy, effective policy, contact/profile,
field, and sources match. It writes an append-only reuse receipt and performs zero acquisition,
validation, or budget spend.

## 4. Observed, validated, and identity state

The Exa result first becomes a tenant-private `core.work_email` or `core.direct_phone` claim with
provider-returned provenance, exact operation/snapshot/request references, and **weak** identity
binding. It never writes `ContactEntity.verified_email`.

Before validation, the existing platform `UseGate` evaluates the observed claim. Use denial
rejects the operation without calling or charging the validator. An admitted independent validator
must then return:

- a reachable result;
- strong binding to the exact person/employer;
- a matching corroboration disposition;
- at least one separately sourced corroborating claim with the exact contact, field, value, and
  workspace; and
- durable provider references, evidence, native units, and cost inside the reserved caps.

The coordinator rechecks those claim ids rather than trusting the adapter's assertion. Missing,
weak, conflicting, unreachable, mismatched, rejected, superseded, Exa-self-corroborated, or
cross-tenant evidence is rejected. Only an allowed, strongly validated email may be promoted to
the canonical `verified_email` key, and the identity layer locks the contact and rejects conflicts
or ownership by another contact. Phone remains delivery data and can never become an identity key.

## 5. Privacy, retention, and erasure

`contact_channel_is_usable` serves only a successful, fresh, unexpired operation with no standing
objection or channel suppression. Validation rejection and use denial make that operation
unusable, but do not create an irreversible subject-wide suppression; a future explicitly
authorized operation may use a different validator or policy. Subject-wide suppression is
reserved for objection, erasure, and retention expiry.

Objection and erasure tombstone the live channel claims, suppress email and phone use, sever every
C5 discovery-artifact subject edge, and mark all request/CSV/provider/validation/receipt artifacts
for physical deletion. Email erasure and retention expiry also clear the promoted canonical email.
The ledger, hashes, cost fields, and no-raw audit state remain.

## 6. C5 exit-gate evidence

| C5 gate | Executable evidence |
|---|---|
| disabled reveals cause zero traffic | policy-disabled and confirmed-directive-disabled cases stop before Exa or validator calls |
| email never authorizes phone | email-only receipt rejects a phone start before traffic |
| non-selected contact causes zero traffic | an intent projected to another contact is rejected against the immutable receipt |
| raw result never writes identity | canonical `verified_email` remains empty after acquisition and changes only after accepted validation |
| failed/conflicting/weak remains unusable | weak binding, conflicting corroboration, and use denial all reject without identity promotion |
| costs settle once per channel | acquisition and validation units/cost equal the one project-run spend delta; terminal replay does not move spend |
| replay performs zero spend | same-window and fresh cross-window replay call neither Exa nor validator and append governed reuse receipts |
| crash does not duplicate validation | interrupted validator dispatch is quarantined after lease expiry and the validator call count remains one |
| acquisition settlement is atomic | an injected settlement failure rolls back observed claim linkage, operation state, units, and budget together |
| objection/DSAR suppresses channel use | objection makes the channel unusable, tombstones the claim, and physically purges every subject-bound C5 artifact; erasure clears identity |

### Recorded mechanical verification (2026-08-05)

- A fresh isolated PostgreSQL database accepted the complete migration chain through
  `fd8d61eb482f`.
- A second fresh database passed `upgrade head -> downgrade base -> upgrade head`; both the
  repository and the final database reported `fd8d61eb482f` as the single head.
- The 174-test C5/affected integration set passed on the fresh schema. It covers the contact
  research contracts and coordinator, source waterfall and manifests, resolver governance,
  field registry, DSAR and governance, identity promotion, industry packs, and the existing Exa
  Deep E1 boundary.
- Production-path mypy, scoped Ruff, and all 24 import-boundary contracts passed. The seven C5
  acceptance tests passed independently as well.
- A broader non-destructive repository run exposed 24 pre-existing order/isolation failures from
  suites committing shared global seed rows into one session database (principally source-manifest
  redefinition and discovery cardinality assumptions). No C5 assertion failed in that run, and the
  same affected set passed from a clean database. This is test-harness debt, not live-provider
  evidence and not concealed by this acceptance record.

## 7. Acceptance boundary

The database and offline provider suite proves C5 mechanics, policy enforcement, durable state,
privacy, and replay. It does not prove that the development account is entitled to Exa person
imports/contact enrichment, that Exa bills exactly as the pinned public allocation model predicts,
or that a chosen independent validation vendor behaves as expected.

A paid canary is therefore still required after separate authorization and C6 production
composition. It must use the populated development database, one already-selected contact, one
explicitly approved channel, the actually configured validator, and bounded caps. Acceptance must
show real endpoint traffic, immutable raw/sanitized artifacts, observed and validated states,
provider-native settlement, optional email promotion, privacy eligibility, and a fresh-process
zero-traffic replay. Until then C5 is **mechanically accepted, not live-provider accepted**.
