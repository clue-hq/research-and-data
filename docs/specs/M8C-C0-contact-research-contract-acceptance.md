# M8C C0 — Contact research contract, field, and policy acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Branch:** `platform/c8-account-profiling-integration`
- **Frozen:** 2026-08-05
- **Status:** mechanically accepted after adversarial authority/contract remediation; no migration,
  live provider request, reveal, or identity mutation

This record freezes the provider-neutral selected-contact authorization, preparation outcome,
professional field vocabulary, and channel-validation semantics that C1 and later M8C slices may
consume. It does not add a project phase or a provider branch to `AccountDeepOrchestrator`.

## 1. Decided contract

### 1.1 Selection and preparation

`ContactResearchSelection` is an immutable, content-addressed action receipt. Its body pins the
workspace, project/run, exact canonical account, confirmed research-directive pin, selected
canonical contacts, committee and strong-identity claim references, admitted fields/questions,
separate email/phone permissions, source/policy/retention references, budget reservation, and
approver/time. It also embeds the complete resolved `ContactResearchPolicyPin`: provider-contract
references, source plans, freshness rules, selected-contact/field/query/result caps, and separate
channel native-unit/money caps. The body rejects a directive for another account, any unsupported
field class, an over-cap target, an unapproved provider, unused/widened channel authority, or an
aggregate reveal reservation above policy. `from_body` additionally requires the independently
resolved effective policy to equal the embedded pin. A later selection is a successor; it cannot
change a request pinned to an earlier digest.

`ContactResearchIntent` is one exact-contact input derived only through `from_selection`. It embeds
its parent receipt and validates every redundant authority member against it: workspace,
project/run, account, directive, contact, fields/questions, source profile, source plan, freshness,
and budget. Direct construction with a foreign contact/account, changed selection digest, widened
field/question set, or alternate source plan fails validation. The provider-neutral
`ContactResearchPreparer` returns only `READY`, `WAITING_EXTERNAL`, `BUDGET_PAUSED`,
`NOT_ELIGIBLE`, or `FAILED` plus durable references. Network and polling remain outside claim
transactions. `READY` requires an immutable snapshot reference; `WAITING_EXTERNAL` requires an
operation reference and next wake.

Changing the directive pin, contact, field set, questions, ordered source plan, source-profile,
freshness policy, budget reservation, provider contract revision, or channel authorization must
change the downstream request fingerprint. Replaying the same selection/intent reuses a fresh
snapshot. C0 defaults professional and personal-facet freshness to 30 days; an accepted policy
revision may replace the complete layered sub-tree.

### 1.2 Canonical fields

The C0 semantic freeze introduces no duplicate meaning:

| Meaning | Canonical key | C0/C1 disposition |
|---|---|---|
| current work email | `core.work_email` | reuse existing field; a raw observation is not verified identity |
| direct personal phone | `core.direct_phone` | reserved; register only in C5 after provider/governance acceptance |
| organization phone | `core.company_phone` | unchanged; never used for a person's direct number |
| current title | `contact.current_title` | C1 registers/materializes |
| job function | `contact.job_function` | C1 registers/materializes |
| job level | `contact.job_level` | C1 registers/materializes |
| team membership | `contact.team_membership` | C1 registers/materializes with modeled basis |
| current location | `contact.current_location` | C1 registers/materializes |
| organization relationship | `contact.organization_relationship` | C1 registers/materializes with explicit basis |

Professional facts are contact-scoped, deep-pass, `professional-public`, strongly identity-bound,
and tenant-private. They are snapshot materialization outputs with no waterfall tier plan.

### 1.3 Independent channel validation

The executable states are:

- `observed`: a provider value exists only as a claim;
- `corroborated`: at least one independent claim binds it to the exact person/employer;
- `validated`: corroboration matched and an independent validator found the channel reachable;
- `verified_identity`: email-only, validated, strongly bound, and eligible for a separate governed
  identity promotion operation; and
- `rejected`: conflict, unreachable result, or use denial.

Appropriateness/use permission is deliberately independent. A validated or verified email becomes
delivery-eligible only when the current use decision is `allowed`. Phone remains delivery data and
cannot participate in identity resolution. Raw output never writes `ContactEntity.verified_email`.

### 1.4 Source and budget defaults

The layered default policy admits `sumble_people` then `sumble_teams` for professional facts and
`exa_deep` for registered personal facets. The existing product decision remains Exa Search
`type=deep-reasoning`, at most 50 results and ten additional queries. The first release retains the
eight registered professional-public personal facets and permits at most three selected contacts
and eight fields per contact.

All contact reveals remain disabled. No email/phone provider is authorized; native-unit and money
reservations are zero; phone identity promotion is false. C5 must replace the complete policy
sub-tree with accepted provider, validation, privacy, jurisdiction, retention, approval, and
per-channel budget references before a reveal can execute.

## 2. Provider contract ruling

The accepted runtime Sumble contract remains the pinned, entitled REST v9 contract recorded in
`M06A-S2-sumble-committee-acceptance.md`: synchronous `POST /v9/teams`, asynchronous
`POST /v9/people`, exact-account bounded selects, immutable request/response artifacts, returned
credit settlement, and no selected email/phone. The already-live snapshot is the C1 input and costs
zero incremental credits to replay.

The public Sumble documentation reviewed on 2026-08-05 describes v3 and
`POST /v3/people/find`. It is captured as a dated, non-authorizing reference. It does not silently
migrate working v9 behavior and it authorizes no channel reveal. The exact relationship is:

```text
entitled, canary-proven v9 -> current runtime and reusable snapshots
public v3 documentation   -> reference/evaluation only
future migration/reveal   -> new acceptance + entitlement canary required
```

Exa Search capability fields are pinned to the official Search reference and the existing M8B
**account-level compatibility** request/response canary. They are not represented as an accepted
contact wire request: C3 owns the exact-person/employer target lock, registry-shaped schema,
directional questions, parser negatives, and contact request fingerprint. Exa Websets person import
plus email/phone enrichment is recorded only as
a plausible C5 option; it is not runtime-authorized until charging, binding, empty-result,
independent-validation, and replay semantics are canary-proven.

The machine-readable field-to-authority map is
`tests/fixtures/contact_research/c0_provider_contract_manifest.json`; the dated public Sumble
reference is `tests/fixtures/providers/sumble/v3/public_people_contract.json`.

## 3. Errors, rates, charging, and spend uncertainty

Provider error bodies are deliberately opaque unless a documented schema exists. C0 owns a stable
HTTP envelope over status, whether dispatch may have occurred, and parsed `Retry-After`; it never
invents or branches on an undocumented vendor message. The executable classifier covers validation
(422/other hard 4xx), authentication (401/403), insufficient credit (402), rate limit (429), server
(5xx), timeout/too-early, and transport-without-status. A retryable/ambiguous result after possible
dispatch is `spend_unknown`; the same transient before dispatch is retryable. Explicit
authentication/validation remains hard and 402 becomes `budget_paused`.

- Sumble native cost is credits. v9 People settles once on the first successful poll; repeated
  success is zero incremental credit. Teams settles from the successful returned rows/attributes.
- Exa Search native settlement is provider USD usage. `costDollars` is response evidence, not a
  preflight quote.
- Pre-dispatch transient failures may retry under the durable limiter. After dispatch, timeout,
  disconnect, or ambiguous rate-limit failure is `spend_unknown` until provider reconciliation;
  it is never silently treated as zero spend.
- Provider auth/validation failures are hard; insufficient credit/budget pauses; documented
  throttling observes `Retry-After`/the shared Sumble limiter.
- Websets and channel validators have no accepted charging event in C0 and therefore remain
  disabled.

## 4. Closed C0 decisions

1. v9 remains runtime authority; public v3 is non-authorizing; neither accepted S2 response
   exposes a C0 channel reveal.
2. Reuse `core.work_email`; reserve `core.direct_phone`; do not repurpose company phone.
3. No email/phone acquisition provider is authorized yet.
4. Verified email requires strong binding, independent identity corroboration, reachability, and
   conflict-free evidence; use permission remains separate.
5. Phone never participates in identity resolution.
6. Canonical LinkedIn profile URLs are the only approved profile-host family in the default;
   jurisdiction policy may narrow, never silently widen, that set.
7. Retain the eight registered facets; default caps are three contacts and eight fields each.
8. Reused Sumble snapshots cost zero; Exa remains within its existing account-deep cap; all reveal
   and validation budgets are zero until C5 acceptance.
9. Both email and phone reveal fail closed in the first release.
10. The final content-side consumer fixture is owned by C7/V0; C0 merely requires professional
    claims to remain reference/provenance-addressable and raw channels absent from drafting context.

## 5. C0 exit evidence

The C0 contract tests prove field meanings do not collide, selection digest tampering fails,
cross-account or non-selected intent construction fails, effective layered policy caps and exact
source/channel plans execute inside the receipt, policy changes alter selection/intent hashes,
channel validation and identity verification are distinct, disabled reveals cannot carry a
provider/budget, layered policy overrides remain auditable, every executable request field has a
documentation/canary authority, Sumble success/empty/pending/running/failed shapes parse, all five
HTTP failure classes execute in both dispatch states, the Exa fixtures are explicitly account-only
compatibility evidence, both Sumble versions have dated fixtures, and every referenced fixture
exists. No migration or live adapter work is introduced by C0.
