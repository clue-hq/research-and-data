# M6A — Durable Exa Websets account discovery and gated Sumble enrichment

**Status:** Binding implementation plan; D0-D6 implemented; E1 and S1 mechanical integration
closed; their separately bounded live canaries remain open on 2026-08-03

**Branch:** `platform/c8-exa-sumble-discovery` (branched from `platform/c8-context-card`)

**Depends on:** M1 claim store, M2 identity, M3 ICP compiler, M4 source layer, M6 discovery/scoring,
M7 durable execution, M9 verification

**Architecture sources:** staged-flow §§1–4, 7–10; Doc C §§1, 4–7; M4, M6, M7, M8, M9 specs

**Provider contracts:** Exa Websets API `v0`; Sumble REST API `v9`

This document is the acceptance contract for adding Exa Websets account discovery and the agreed
Sumble waterfall to the current backend. It is deliberately more specific than M6: every slice has
an observable boundary, durable state, failure semantics, and a pass/fail gate. A slice that only
passes unit tests is not complete when its scope includes a database, queue, webhook, provider, or
project-run transition.

---

## 1. Outcome and binding decisions

The first production outcome is a **sealed discovery batch** for one confirmed ICP version. The
batch contains a canonical, deduplicated account set and a terminal resolution record for every
required discovery field. Only a sealed batch may advance the project run from `discovery` to
`scoring`.

The following decisions are binding for this implementation:

1. **Exa Websets is the first implemented account-discovery provider.** It produces grounded
   company candidates, base company properties, criterion evaluations, references, and configured
   enrichments. It is registered behind the provider-neutral discovery seam; no downstream package
   branches on `provider == "exa"`.
2. **Discovery is a closed, durable batch.** A partial list is progress, not phase completion. The
   project remains in `ProjectPhase.DISCOVERY` until every planned provider operation, page,
   enrichment, event, identity disposition, required-field attempt, receipt, artifact, and cost
   record is terminal and an immutable `DiscoveryBatchSeal` has been committed. Reaching the
   requested row count, receiving an `idle` webhook, or completing a worker is never sufficient by
   itself.
3. **Cheap discovery facts are preserved.** This spec narrows M6's older “discovery produces no
   field claims” ruling: provider-returned identity/firmographic values and explicitly purchased
   discovery enrichments are materialized as ordinary typed claims after identity admission. Deep
   signals and synthesized research remain outside discovery.
4. **Every admitted account has two hard identity values:** canonical account name and primary
   domain. A candidate lacking either cannot enter the sealed account set; it remains in identity
   review or is excluded with a durable disposition.
5. **Every admitted account has terminal decisions for the discovery envelope:** LinkedIn company
   URL, industry, employee count or size band, headquarters/location, and revenue or revenue band.
   “Terminal” means resolved, confirmed missing, conflicting, or human-disposed after review. It
   never means fabricating a value or waiting forever for a non-null result.
6. **Company email and phone are optional discovery attempts.** They are persisted when found and
   receive the same evidence, policy, and cost treatment, but missing email/phone does not prevent
   the batch from sealing. They are separately budgeted because Exa bills email and phone at a
   different rate from ordinary enrichments.
7. **Buying-committee discovery is top-tier-only.** Sumble people/teams/jobs may run only after
   scoring and the human tier checkpoint, and only for accounts whose must-have ICP criteria are
   satisfied and whose approved tier is configured as committee-eligible. No whole-list Sumble
   people search is permitted.
8. **Sumble atomic intent signals, Priority Signals, and Intelligence Briefs are deferred.** This
   plan defines no implementation slice for them. They require a later source-semantics and product
   decision.
9. **Claims never overwrite one another by provider rank.** Exa, Sumble, and official-source claims
   are retained independently. Field-specific merge/corroboration policy selects a current value or
   raises a conflict. An authoritative conflict blocks automatic verification.
10. **Production uses Sumble REST v9, not MCP.** MCP remains suitable for manual exploration only.

---

## 2. Scope boundary

### 2.1 In scope for the first implementation wave

- Exa Websets company discovery from a confirmed ICP and a versioned discovery plan.
- Durable asynchronous operation submission, wake-up, polling, webhooks, pagination, and final
  reconciliation.
- Immutable storage of requests, raw responses, pages, item snapshots, evaluations, enrichment
  results, provider events, and cost receipts.
- Exact-query replay and reuse without another provider request.
- Candidate deduplication and M2 identity admission.
- Materialization of the required discovery envelope into account identity/current-value claims.
- Terminal missing/conflict/review dispositions for required fields.
- An immutable batch seal and a hard `discovery -> scoring` transition guard.
- A live two-row Exa acceptance run with crash/replay and no-double-spend evidence.
- Provider-neutral contracts that a later structured discovery provider can implement.

### 2.2 Later, gated slices described here but not part of the first discovery gate

- Sumble organization/jobs/confirmed-technology gap enrichment for selected accounts.
- Sumble people/teams/jobs committee discovery after the approved top-tier gate.
- Targeted Exa import Websets for selected accounts or contacts after discovery.
- General Exa Search as an agent web-search tool.

### 2.3 Explicitly out of scope

- Sumble Signals, Priority Signals, signal relevance feedback, and Intelligence Briefs.
- Monitoring/continuous refresh of a sealed discovery batch. A monitor run creates a new observation
  generation; it never mutates a historical seal.
- Claim-free provider blobs as a downstream data interface.
- A guarantee that every public company has published revenue, email, or phone data.
- Automatic committee research on every discovered account.
- Direct provider access from an agent or a provider-specific branch in scoring/deep research.
- A frontend implementation.

---

## 3. Current baseline and contract deltas

The existing backend has the correct broad seams but not the lifecycle this integration requires:

- `DiscoveryChannel.discover(query) -> list[CandidateRecord]` assumes an invocation can return a
  complete list. Exa Websets is asynchronous and may still be searching or enriching after the
  submit response.
- `CandidateRecord` carries grounding, identity hints, confidence, and aggregate cost, but cannot
  reference a durable provider item snapshot or its field/evaluation records.
- the current discovery phase writes admission provenance and source-yield telemetry but explicitly
  writes no field claims;
- the production `ChannelRegistry` is empty unless a composition root injects channels;
- the existing Exa resolver is a field-level Search/highlights resolver, not a Websets adapter; and
- the current Sumble integration exposes organization, engineering-jobs, and confirmed-tech
  snapshots only. It does not provide discovery, people, teams, signals, or contact reveals.

This plan preserves the existing distinction between **entity-producing discovery channels** and
**known-entity field resolvers**. It adds an asynchronous acquisition contract around discovery; it
does not misuse the field-level `Resolver` protocol to produce companies.

### 3.1 Required shared contract delta

The project-run phase vocabulary needs a non-human external-wait outcome:

```python
class PhaseStatus(StrEnum):
    COMPLETED = "completed"
    WAITING_EXTERNAL = "waiting_external"  # new
    PAUSED = "paused"                      # human/budget hold only
    FAILED = "failed"

class PhaseCheckpointStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    WAITING_EXTERNAL = "waiting_external"  # new
    AWAITING_INPUT = "awaiting_input"
    COMMITTED = "committed"
    FAILED = "failed"
```

`WAITING_EXTERNAL` keeps the project run **active at `discovery`** and carries only references:
`discovery_batch_id`, pending operation ids, `next_poll_at`, and wake reason. A webhook or scheduled
poll re-enqueues the same phase operation. It is not a human pause and must not require a human
resume action.

The phase idempotency ledger must not mark the discovery phase `SUCCEEDED` while it waits. The
batch's smaller provider operations have their own idempotency keys and durable outcomes. The
phase checkpoint becomes `COMMITTED` only after the batch seal exists.

---

## 4. Discovery plan and required account envelope

### 4.1 Versioned `DiscoveryPlan`

The confirmed ICP compiles into one immutable discovery plan:

```text
DiscoveryPlan
  plan_version
  workspace_id / project_id / project_run_id
  icp_key / icp_version
  provider_policy_version
  field_policy_version
  channels[]
  searches[]
    channel_key
    normalized_query
    entity_type
    requested_count
    criteria[]                 # ordered, maximum per provider contract
    enrichments[]              # ordered, typed
    max_people_per_company?    # person searches only; not first wave
  required_account_fields[]
  optional_account_fields[]
  provider_credit_cap
  money_budget_cap
  stopping_policy
  snapshot_reuse_policy
```

The plan, not an agent, owns the provider count, criteria, enrichments, and caps. Any material ICP,
query, criterion, field, provider-version, or policy change produces a new plan version and therefore
a new operation fingerprint.

### 4.2 Account discovery envelope

The sealed read model projects identity rows plus current field claims; it is not a second truth
store:

| Logical field | Canonical storage | Requirement | Acceptable resolution |
|---|---|---|---|
| account name | `account_entity.canonical_name` | hard identity | non-empty canonical name |
| primary domain | `account_entity.primary_domain` + `core.primary_domain` claim | hard identity | normalized registrable domain |
| LinkedIn company URL | new `core.company_linkedin_url` field | required attempt | resolved URL or terminal missing/conflict disposition |
| industry | new `core.industry` field | required attempt | resolved value or terminal missing/conflict disposition |
| employee count | existing `core.employee_count` | required attempt | exact count preferred |
| employee range | new `core.employee_range` | alternative to exact count | range only when exact count is unavailable |
| headquarters/location | new `core.hq_location` + `account_entity.hq_geo` | required attempt | normalized location object or terminal disposition |
| annual revenue | new `core.annual_revenue` | preferred when explicitly sourced | amount + currency + as-of + estimate kind |
| revenue band | new `core.revenue_band` | acceptable alternative | bounded enum + evidence |
| company email | new `core.company_email` | optional attempt | public company/general contact email |
| company phone | new `core.company_phone` | optional attempt | public company/general contact phone |

`core.annual_revenue` must distinguish `reported`, `provider_estimate`, and `third_party_estimate`.
An inferred number must never be represented as reported revenue. A revenue band satisfies the
discovery envelope when an exact, sourced amount is unavailable.

### 4.3 Field-resolution state

Every `(batch, account, required logical field)` has exactly one current operational resolution:

```text
pending
  -> resolved
  -> confirmed_missing
  -> conflict
  -> review_required -> resolved | accepted_missing | account_excluded
  -> blocked_by_policy
  -> failed_retryable
  -> failed_terminal
```

For batch sealing:

- `resolved`, `confirmed_missing`, `conflict`, `accepted_missing`, and `blocked_by_policy` are
  terminal and honest;
- `pending`, `review_required`, and `failed_retryable` block the seal;
- `failed_terminal` blocks the seal until a human excludes the account or accepts the field as
  missing with a durable reason; and
- an identity `review_required` candidate must be admitted or excluded. It cannot appear in a
  sealed batch with an unresolved entity id.

This distinction prevents “field completeness” from becoming a fabrication requirement.

---

## 5. Exa Websets request policy

### 5.1 Base company properties

The current Exa company item exposes company name, URL/domain, location, employees, industry,
about text, structured headquarters, and financials (annual revenue, total funding, and latest
funding round) when available. The raw snapshot preserves the full provider object. D4 may project
only the approved discovery fields: name, URL/domain, location, employees, industry/about,
headquarters, annual revenue, total funding, and latest funding round. It must deliberately ignore
`foundedYear` and `webTraffic`, and it must not purchase a duplicate enrichment merely to obtain a
second copy of a populated base property.

### 5.2 First-wave enrichments

The initial company Webset requests at most these enrichments:

1. LinkedIn company URL (`url`, ordinary enrichment).
2. Revenue band (`options`, ordinary enrichment) with a versioned closed range vocabulary.
3. Public company/general contact email (`email`, optional and separately budgeted).
4. Public company/general contact phone (`phone`, optional and separately budgeted).

If a specific vertical requires an additional discovery field, it must be added through the field
registry and a new plan version. It cannot be embedded as an unversioned prompt change.

Email and phone are not “two-credit ordinary enrichments”; Exa's current public Websets pricing
meters them separately. Preflight must show ordinary-enrichment, email, and phone maximums as
separate provider units.

### 5.3 Criterion semantics

- Use one to three must-have criteria by default; never exceed the provider contract maximum.
- A normal Exa search item is an admitted provider match. The platform still persists every returned
  criterion evaluation and its `yes | no | unclear` state.
- A `no` or `unclear` evaluation on a returned/imported item is not silently rewritten as `yes`.
- A missing enrichment is persisted as `result = null` plus its reasoning/references, then becomes a
  `confirmed_missing` field attempt when the enrichment operation is terminal.
- Provider reasoning is evidence metadata, not an authoritative field value by itself.

---

## 6. Durable asynchronous discovery model

### 6.1 State machine

```text
PLANNED
  -> SUBMITTING
  -> PROVIDER_RUNNING
  -> INGESTING_EVENTS_AND_PAGES
  -> RECONCILING
  -> IDENTITY_RESOLUTION
  -> FIELD_MATERIALIZATION
  -> SEAL_PENDING
  -> SEALED

Any non-terminal state may enter:
  WAITING_EXTERNAL | PAUSED_BY_USER | SPEND_OUTCOME_UNKNOWN | FAILED_RETRYABLE

Terminal non-success states:
  FAILED_TERMINAL | CANCELLED_UNSEALED
```

The project-run phase remains `discovery` for every state above except `SEALED`. A failed or
cancelled batch never permits scoring. The user may create a replacement plan/batch; the failed
batch remains immutable evidence.

At the provider-operation level, `succeeded` is seal-terminal. A non-retryable provider failure is
not seal-terminal until an authorized operator records `accepted_terminal_failure`, the spend
outcome is known, and every affected field/account has a terminal disposition. Cancellation and
unknown spend always block sealing. This allows an honest, explicitly accepted missing field to
finish without allowing an unexamined failure to masquerade as completion.

### 6.2 Completion barrier

`DiscoveryBatchSeal` may be committed only when one transaction proves all of the following:

1. the batch's `DiscoveryPlan` exists and its ICP/project/workspace lineage matches the project run;
2. every planned provider operation is `succeeded` or an explicitly authorized
   `accepted_terminal_failure`; none is running, retryable, cancelled, spend-unknown, or missing;
3. every provider dispatch attempt has a durable receipt and request artifact; every response body
   has a raw artifact reference; and transport failures have a durable no-response/indeterminate
   receipt;
4. every accepted webhook event has been signature-verified, durably recorded, and processed or
   explicitly superseded;
5. final polling reconciliation has observed the Webset as idle and every search/enrichment as
   terminal;
6. item pagination is exhausted (`hasMore=false`) and every cursor/page receipt is durable;
7. every provider item has an immutable raw item snapshot and a normalized item record;
8. every candidate identity is terminal: admitted, merged into a survivor, or excluded;
9. every admitted account has its hard identity values;
10. every required discovery-envelope field has a seal-terminal resolution;
11. every materialized value has a typed claim with evidence/provenance, or the field has a durable
    missing/conflict/policy disposition;
12. duplicate domains/entities have been collapsed and every source item maps to the survivor;
13. provider units and money cost are reconciled to durable receipts; and
14. the final account membership manifest and all referenced artifacts exist.

The guard is evaluated inside the same database transaction that inserts the seal. A check followed
by a separate seal write is disallowed because a late event could race between them.

### 6.3 Immutable seal

```text
DiscoveryBatchSeal
  batch_id
  project_run_id
  icp_key / icp_version
  discovery_plan_id / plan_sha256
  sealed_at
  account_count
  account_manifest_artifact_key
  account_manifest_sha256
  excluded_candidate_count
  field_resolution_summary
  provider_operation_ids[]
  request_fingerprints[]
  raw_artifact_manifest_key
  claim_id_manifest_key
  provider_units_charged
  cost_cents_charged
  coverage_report_ref
  seal_sha256
```

A late or duplicated event cannot mutate a seal. It is recorded as a late event and reconciled
against the sealed generation. Material new data requires a new batch/observation generation.

---

## 7. Persistence model

Postgres remains the system of record; object storage holds immutable provider bodies. Operational
tables coordinate execution but never replace field claims as truth.

### 7.1 New or extended durable records

`discovery_batch`

```text
id, workspace_id, project_id, project_run_id, icp_key, icp_version,
discovery_plan_id, state, generation, started_at, updated_at, sealed_at,
provider_units_reserved, provider_units_charged, cost_cents_reserved, cost_cents_charged,
failure_code, replacement_batch_id
UNIQUE(project_run_id, generation)
```

`discovery_operation`

```text
id, workspace_id, batch_id, source_key, provider_api_version, request_fingerprint,
observation_window,
provider_external_id, provider_operation_id, state, next_poll_at,
submitted_receipt_ref, final_receipt_ref, raw_request_artifact_key,
raw_response_manifest_key, provider_units_reserved, provider_units_charged,
cost_cents_reserved, cost_cents_charged, spend_outcome, started_at, terminal_at
UNIQUE(workspace_id, source_key, request_fingerprint, observation_window)
UNIQUE(source_key, provider_external_id)
```

`discovery_provider_event`

```text
id, operation_id, provider_event_id, event_type, signature_verified,
payload_artifact_key, provider_created_at, received_at, processed_at,
processing_disposition
UNIQUE(operation_id, provider_event_id)
```

`discovery_page_receipt`

```text
id, operation_id, resource_kind, request_cursor, next_cursor,
has_more, payload_artifact_key, item_count, fetched_at
UNIQUE(operation_id, resource_kind, request_cursor)
```

`discovery_item_snapshot`

```text
id, operation_id, provider_item_id, source_kind, source_id,
raw_artifact_key, item_sha256, observed_at, normalized_at
UNIQUE(operation_id, provider_item_id, item_sha256)
```

`discovery_candidate_link`

```text
batch_id, item_snapshot_id, raw_name, candidate_domain, source_url,
admission_status, account_entity_id, survivor_entity_id, disposition_reason
UNIQUE(batch_id, item_snapshot_id)
```

`discovery_field_resolution`

```text
batch_id, account_entity_id, logical_field_key, state,
claim_ids[], winning_claim_id, source_item_ids[], reason_code,
review_disposition_ref, updated_at
UNIQUE(batch_id, account_entity_id, logical_field_key)
```

`discovery_batch_seal`

```text
batch_id PK, seal_sha256 UNIQUE, manifest_artifact_key,
account_count, provider_units_charged, cost_cents_charged, sealed_at
```

The implementation may fold a proposed table into an existing generic receipt/event table only if
all uniqueness, lineage, queryability, and acceptance criteria remain enforceable. A JSON blob in a
phase payload is not an acceptable substitute for queryable operation/item/field status.

### 7.2 Artifact policy

Persist, content-address, and tenant-bind:

- canonical request body with secret headers removed;
- submit response;
- each webhook body;
- each polled Webset/search/enrichment response;
- every paginated item page;
- every immutable item snapshot;
- final operation manifest;
- final account/claim manifests; and
- the batch seal manifest.

Authorization headers, API keys, webhook secrets, and private credential material never enter the
artifact store, logs, traces, or receipts.

---

## 8. Exact-query idempotency, caching, and replay

### 8.1 Request fingerprint

The exact-query fingerprint is SHA-256 over canonical JSON containing:

```text
workspace scope
provider source key + API version
entity type
normalized query
ordered criteria descriptions
requested count
search behavior
ordered enrichment descriptions, formats, and option labels
max-people-per-company when present
ICP key/version
discovery-plan version
field-policy version
provider-contract version
observation-window / freshness bucket
```

Secrets, timestamps unrelated to freshness, random ids, and transport headers are excluded.

### 8.2 Replay rule

For the same workspace, provider, fingerprint, and active observation window:

- `SEALED/SUCCEEDED`: reuse the stored operation, item artifacts, claims, and seal references; make
  **zero provider calls**;
- `PROVIDER_RUNNING/WAITING_EXTERNAL`: join the existing operation and wait/reconcile; do not submit
  another Webset;
- `SPEND_OUTCOME_UNKNOWN`: block automatic resubmission and reconcile by deterministic
  `externalId`/provider lookup;
- `FAILED_RETRYABLE` before dispatch: retry the same operation key;
- `FAILED_TERMINAL`: require a new plan/fingerprint or an explicit operator disposition; and
- explicit refresh: advance the observation window/generation, preserving the old snapshot.

Exa's `externalId` is derived from the operation fingerprint plus workspace-safe scope. A duplicate
create response (`409`) triggers lookup/reconciliation of the existing Webset; it is not treated as
a new chargeable operation.

### 8.3 Claim replay

Replaying a sealed snapshot returns existing claim ids and field-resolution rows. It does not write
duplicate equivalent claims. A later explicit refresh creates new observations that participate in
ordinary append-only supersession/merge; cache reuse must not suppress legitimate freshness.

---

## 9. Webhook, polling, pagination, and reconciliation

### 9.1 Webhooks are wake-ups, not truth

- Verify the Exa HMAC signature over the exact raw request body before accepting an event.
- Use one team-level subscription and endpoint, not one webhook per operation.
- Parse the signed event and resolve its globally unique `websetId` to a durable operation before
  choosing a workspace or persisting the raw body. A valid event for an unrelated team Webset is
  acknowledged without entering any tenant artifact store.
- Store a matched verified raw event in the resolved operation's workspace before acknowledging
  success.
- Deduplicate on provider event id.
- Accept duplicate and out-of-order delivery.
- Never mark an operation complete solely because an `idle` webhook arrived.
- Webhook handlers enqueue/resume work; they do not materialize claims inside the HTTP request.

### 9.2 Polling is mandatory reconciliation

Even with webhooks enabled, poll:

- after submit, using bounded backoff and provider rate limits;
- when a webhook signals item/enrichment/idle progress;
- when the scheduled `next_poll_at` expires; and
- once more before sealing to obtain authoritative terminal status.

Transient 408/425/429/5xx responses remain retryable without changing the operation identity.
Transport loss after dispatch is `spend_outcome_unknown` until provider lookup reconciles it.

### 9.3 Pagination

- Fetch until `hasMore=false`; expanded Webset items are not assumed complete.
- Persist every cursor request and page before normalizing it.
- A crash after page persistence but before normalization resumes from the stored page.
- Re-fetching the same cursor is content-hash compared and deduplicated.
- An item repeated on multiple pages/events maps to one provider item lineage and one candidate.

### 9.4 Final reconciliation

Before the completion barrier, compare:

- searches declared by the plan versus searches present on the Webset;
- enrichments declared versus provider enrichments and item results;
- provider progress/found counts versus unique item snapshots;
- item ids referenced by events versus item ids obtained by pagination;
- provider charge/usage data versus internal receipts; and
- every requested enrichment id versus its stored description/schema version.

Any mismatch is a typed reconciliation failure and blocks sealing.

---

## 10. Identity, deduplication, and claim materialization

### 10.1 Admission order

1. Persist provider item snapshot.
2. Extract identity hints without writing field claims.
3. Normalize the registrable domain.
4. Resolve/deduplicate through M2.
5. Record `admitted | merged | review_required | excluded`.
6. Only after a canonical survivor exists, materialize item properties/evaluations/enrichments as
   claims attached to that survivor.

No claim is keyed to a free-text account name or a losing merged id.

### 10.2 Multiple items for one account

All source items remain independently referenced. Values become separate claims when their
evidence differs. The merger/corroborator may agree, select, or conflict them. Deduplication must
not discard evidence simply because two URLs map to one company.

### 10.3 Exa normalization

- company name/domain feed identity and also retain provider evidence;
- base location, employee count, and industry become typed claims when present;
- LinkedIn URL, revenue band, email, and phone become claims only from their mapped enrichment id;
- each criterion evaluation becomes structured discovery evidence, not an untyped text blob;
- `result=null` becomes a terminal attempt record, not a null-valued claim;
- reasoning/references and the raw snapshot artifact key remain attached to provenance;
- source tier/trust is determined by field/evidence policy, not by a blanket “Exa is Tier 1” rule;
  and
- conflicts preserve every claim and block automatic verification where policy requires.

### 10.4 Discovery-phase output

The successful phase payload contains references only:

```json
{
  "discovery_batch_id": "...",
  "discovery_batch_seal_ref": "...",
  "account_manifest_ref": "...",
  "claim_manifest_ref": "...",
  "coverage_report_ref": "...",
  "provider_receipt_manifest_ref": "..."
}
```

Scoring loads the exact sealed account manifest. It must not re-query “all accounts discovered by
this run” from a mutable or incompletely reconciled source.

---

## 11. Cost and spend safety

The batch records provider units and money separately.

### 11.1 Exa preflight

For `M` accepted rows, `R` ordinary enrichments, and enabled contact enrichments `E`/`P`:

```text
maximum modeled Websets credits =
  10 * M
  + 2 * R * M
  + 5 * E * M
  + 5 * P * M
  + preview/recall/import units when those operations are in the plan
```

This is a conservative reservation, not final settlement. The current account-discovery contract
requests at most one value for each email/phone enrichment and rejects a provider result that
violates that shape. Final credits are derived from terminal item facts under the pinned public
rules: 10 only for rows whose every requested criterion is `yes`; 2 per ordinary enrichment row,
including a terminal null; 5 per actual returned email/phone value; and 2 per resolved import when
imports are part of a future plan. Exa does not return operation-level dollars, so monetary
reservation/settlement is a versioned subscription-allocation equivalent, not card telemetry.
Pricing is versioned config, never embedded in the normalizer.

### 11.2 Spend invariants

- reserve before dispatch;
- derive one stable provider operation key before any network call;
- persist the raw provider response and receipt before acknowledging completion;
- never release an idempotency claim after a possible paid response;
- never auto-retry spend-unknown work;
- count a charge once across operation, phase, account, and project views;
- prevent aggregate reservation from exceeding the project cap under concurrency; and
- show the optional email/phone increment independently before dispatch.

S1 closes the account-gap portion of the Sumble spend-safety backlog with request-versioned keys,
one project-run aggregate reservation, coalesced endpoint snapshots, conservative
spend-outcome-unknown quarantine, exact response-credit receipts, cumulative project cost, and
terminal zero-call replay. S2 must reuse these guarantees rather than calling the legacy live
resolver path directly.

---

## 12. Sumble and contact-level boundaries

### 12.1 Account-level Sumble gap enrichment

After the Exa batch is sealed and Pass A identifies accounts worth further work, Sumble may fill
native account gaps through REST v9:

- organization fields;
- job postings/hiring evidence; and
- confirmed-used technology.

Each endpoint is a distinct governed source key and durable snapshot. Sumble is not called merely
because “something is missing”; the field plan must identify Sumble as the native next source and
the expected value must justify the credit reservation.

### 12.2 Committee eligibility gate

No Sumble people/team/related-person request may execute unless all are true:

1. the account belongs to a sealed discovery batch;
2. Pass A completed for that exact account and ICP version;
3. all ICP must-have criteria have evidence-backed passing dispositions;
4. the human-approved tier is in the versioned `committee_eligible_tiers` set;
5. an explicit committee field plan exists;
6. the personal-data pre-spend, jurisdiction, use-class, identity-binding, and budget gates pass;
   and
7. no reusable fresh snapshot already satisfies the same request.

The platform first buys role/person/team data without contact reveals. Email/phone reveals occur
only for the final selected committee candidates and use separate operation keys/budgets.

### 12.3 Deferred Sumble capabilities

There is intentionally no implementation task here for:

- organization/atomic signals;
- Priority Signals;
- signal feedback/relevance updates; or
- Intelligence Briefs.

Adding any of these requires a new contract delta defining atomic evidence, derived summaries,
trust tiers, freshness, and whether the result can influence scoring.

---

## 13. Implementation slices and strict exit gates

Slices are sequential. A later slice may not begin merely because earlier unit tests are green.
The gate named for each slice must be recorded in `_memory/` with commands, artifacts, provider ids
where applicable, database evidence, cost, and unresolved failures.

### Slice P0 — Reproducible Stage-0 handoff fixture

**Purpose:** Test discovery against a realistic, already-confirmed Stage-0 result without making
Stage 0 part of every discovery acceptance run.

**Scope and deliverables:**

- one isolated, migrated Postgres database containing an Insight Health AI workspace, brand, Aura
  AI product, and discovery project;
- a human website-onboarding receipt over an immutable homepage artifact (the current backend has
  no separate application-user table, so it does not fabricate one for the fixture);
- content-addressed snapshots of the official Insight Health homepage, Aura Ambient page, Aura
  Anywhere page, and neurosurgery-referral case-study page;
- seven product-scoped Client-KB claims: value proposition, product, differentiator, pricing
  posture, proof point, named testimonial organization, and ICP evidence;
- every website-derived fact stamped `source_tier=2`, `extraction_method=scrape`,
  `verification_status=unverified`, exact evidence span, source URL, source key, and artifact key;
- a confirmed `independent_neurosurgery_spine_practices_us` ICP carrying Client-KB and Aura product
  lineage, a two-row Exa discovery strategy, required/optional discovery fields, and an initial
  explainable rubric;
- one immutable product-context version and one `READY` discovery-spend decision; and
- one durable project run stopped exactly at `ProjectPhase.DISCOVERY`.

The fixture builder is network-free. It consumes prior Firecrawl `search --scrape` results, and a
fixed Stage-0 run id makes an exact rerun reuse the same claims and lineage. It must never downgrade
the official-site numbers into “verified results”: Insight Health is authoritative for what its
site asserts, not independent proof of its savings, ROI, compliance, or customer relationship.

**Gate P0:** pure loader/evidence tests pass; a real migrated Postgres + filesystem-artifact test
proves claim provenance, ICP/context/readiness/run lineage, and exact replay with unchanged table
counts; the builder is then run twice over the real harvested pages and returns the same ids. P0
does not close any Exa or Sumble provider slice.

### Slice D0 — Contract freeze and executable fixtures

**Implementation record:** `docs/specs/M06A-D0-contract-freeze.md` freezes the shared types,
fingerprint vectors, account-envelope policy, fourteen-condition truth table, fixture matrix, and
D1 tenancy/retention/DSAR schema review.

**Purpose:** Freeze request, lifecycle, field, state, receipt, seal, and error contracts before
provider code.

**Deliverables:**

- Pydantic/core contracts for plan, operation, event, page, item, field resolution, and seal.
- Canonical request-fingerprint algorithm and golden vectors.
- Sanitized Exa payload fixtures covering company items, all evaluation states, null enrichment,
  pagination, duplicate/out-of-order events, cancellation, and schema drift.
- Field registry definitions and discovery-envelope policy.
- Migration/table design reviewed against tenancy, retention, and DSAR requirements.
- Architecture/import-contract map assigning each type/repository/adapter/composition owner.

**Gate D0:** schema/contract tests pass; request fingerprints are byte-stable across processes; the
seal barrier truth table covers every non-terminal blocker; no external call occurs.

### Slice D1 — Durable discovery-batch substrate

**Implementation record:** `docs/specs/M06A-D1-durable-discovery-batch.md` records the final
schema, repository/replay contracts, external-wait lifecycle, fourteen-condition SQL barrier,
accepted-terminal-failure semantics, sealed-generation guards, and real-database gate evidence.

**Purpose:** Add database/object-store execution state without a provider dependency.

**Deliverables:**

- Alembic migration with one head and reversible downgrade.
- Repositories for batch, operation, event, page, item, candidate link, field resolution, and seal.
- Transactional completion-barrier/seal writer.
- Artifact capture and subject/workspace binding.
- Query/replay readers and bounded status projections.
- `WAITING_EXTERNAL` project-phase/checkpoint contract delta and scheduler wake seam.

**Gate D1:** real Postgres/object-storage integration proves create -> wait -> crash -> resume ->
seal; concurrent seal attempts produce one identical seal; cross-workspace reads/writes fail;
migration head -> base -> head passes; no provider fake can bypass the SQL barrier.

### Slice D2 — Exa Websets typed client and paid submit

**Implementation record:** `docs/specs/M06A-D2-exa-websets-paid-submit.md` records the typed v0
contract, atomic provider-unit and monetary reservation, dispatch/replay state machine, durable
artifacts, historical `401/not_charged` evidence, and the successful generation-4 live run. Gate D2
closed on 2026-08-03: the real two-row Webset completed, and fresh-process replay made zero create
or lookup calls.

**Purpose:** Submit exactly one real two-row company Webset safely.

**Deliverables:**

- Typed request/response models pinned to Websets `v0`.
- Auth/timeout/retry/error taxonomy with secret-safe logging.
- Pre-spend reservation and deterministic `externalId`.
- Durable submit request/response artifacts and receipt.
- Provider-operation lookup/reconciliation on duplicate or uncertain submit.

**Gate D2:** one real two-row submit is visible in Exa and durable internally; repeating the exact
submit—including after a process restart—makes zero second create calls; request/operation ids,
artifacts, reserved/realized units, and traces reconcile. A mock-only test cannot close D2.

### Slice D3 — Webhooks, polling, pagination, and reconciliation

**Implementation record:** `docs/specs/M06A-D3-exa-websets-lifecycle.md` records the team-level
signed webhook, tenant-safe routing, scheduled poll worker, cursor/page/item durability, strict
terminal schema/identity/evaluation/enrichment reconciliation, exact credit settlement, production
wiring, and real-Postgres crash/replay evidence. Both bounded live gates closed on 2026-08-03: the
two-row search-only operation settled 20 credits, and the one-row URL/revenue/email/phone operation
settled 24 credits from exact terminal item facts. Each terminal replay made zero provider calls.

**Purpose:** Retrieve the entire asynchronous operation and survive missing/duplicate delivery.

**Deliverables:**

- HMAC-verifying webhook endpoint with raw-body preservation and event deduplication.
- Scheduled polling/backoff/rate-limit handling.
- Cursor-paginated searches/enrichments/items/events retrieval with durable page receipts.
- Final authoritative reconciliation and typed mismatch failures.
- Restart-safe resume from stored events/pages.

**Gate D3:** the real D2 operation reaches provider idle and all pages/items are durable. Acceptance
must also demonstrate: duplicate event, out-of-order event, missed webhook recovered by polling,
and process death after page persistence but before normalization. No duplicate item or cost is
created.

### Slice D4 — Identity admission and discovery-field materialization

**Implementation record:** `docs/specs/M06A-D4-exa-identity-field-materialization.md` records the
snapshot-only composition boundary, approved company-field mappings, M2 admission and durable
review continuation, transitive survivor replay, append-only claim/artifact evidence, field
resolution policy, and the exact adversarial/live acceptance matrix.

**Purpose:** Turn provider items into canonical accounts and typed claims without losing evidence.

**Deliverables:**

- Exa Websets `DiscoveryChannel`/normalizer over durable item snapshots.
- M2 admission, domain deduplication, survivor redirection, and review/exclusion paths.
- Required field definitions and mappings.
- Claim materializer for base properties, evaluations, and enrichment results.
- Field-resolution ledger including terminal missing/conflict states.
- Reuse of prior snapshots/claim ids on replay.

**Gate D4:** real two-row items become the expected canonical accounts, claims, provenance/artifact
links, and field-resolution rows. Replaying materialization writes zero duplicate equivalent claims.
At least one fixture/live case demonstrates an honest missing field; at least one adversarial case
demonstrates domain dedup and evidence preservation.

### Slice D5 — Batch seal and hard project-phase barrier

**Implementation record:** `docs/specs/M06A-D5-discovery-seal-phase-barrier.md` freezes the
current-generation rule, immutable relational/artifact manifest bundle, database project-phase
guard, pause/cancel/replace semantics, and sealed-manifest scoring reader.

**Purpose:** Make partial discovery structurally unable to advance.

**Deliverables:**

- Transactional fourteen-condition completion barrier.
- Immutable seal/manifest.
- Discovery handler returning `WAITING_EXTERNAL` until sealable.
- `ProjectRun` guard requiring the exact current batch seal before `SCORING`.
- Pause/cancel/replace-plan behavior with immutable failed/replaced generations.
- Sealed-manifest reader used by scoring.

**Gate D5:** a database-backed project run is unable to advance for each individual blocker in
§6.2; after resolving the final blocker, one seal commits and the same run advances exactly once to
scoring. A late event cannot alter membership or fields under the seal.

**Post-review repair (2026-08-03):** the project must still traverse a committed `SCORING` phase
and an approved human `TIER_CHECKPOINT` before `DEEP`; direct phase skips are rejected in
PostgreSQL. For the Insight Health/Aura ICP, numeric scoring is explicitly disabled and selection
uses the immutable Exa criteria: all required `yes` -> selected, any `no` -> excluded, and any
`unclear`/missing criterion or unresolved required field -> hold. The checkpoint may approve only
selected accounts and writes seal/run-bound tier decisions without synthetic fit or intent scores.
`ScoreAccountsTool` refuses unless the persisted run is active in `SCORING`.

### Slice D6 — Full live Exa discovery acceptance

**Status:** `PASS` on 2026-08-03. The implementation and live/replay evidence are recorded in
`docs/specs/M06A-D6-production-composition-acceptance.md`.

**Purpose:** Prove the complete production composition, not isolated adapters.

**Live workload:** one confirmed synthetic/non-sensitive ICP, one two-result Exa company Webset,
LinkedIn URL + revenue-band enrichments, optional email/phone enabled only after preflight approval.

**Gate D6:** all of the following are evidenced from the production composition:

- confirmed ICP -> durable discovery plan;
- one paid submit and no duplicate on exact replay;
- webhook and polling reconciliation;
- all pagination exhausted;
- two raw item snapshots and preserved evaluations/references/enrichments;
- identity admission/dedup;
- required-field terminal states for both accounts;
- claims, evidence spans, artifact references, and field resolution persisted;
- provider units/internal cost reconciled;
- immutable batch seal;
- project held in discovery before the seal and advanced only after it; and
- process restart/replay returns the same accounts, claims, and seal with zero new provider calls.

Failure of any row leaves D6 open. Exit code zero, “completed,” or a green fixture suite is not a
substitute for this evidence.

**Observed scoring-bypass result:** both live accounts passed all three required Exa criteria, but
required discovery fields remained terminally missing. The project correctly paused at the human
checkpoint with `selected=0, hold=2, excluded=0`, wrote no numeric scores, and did not enter deep
research. The positive selected -> approved -> deep path remains database-backed; the live holds
are inputs to the later Sumble gap waterfall, not grounds for weakening the admission policy.

### Slice E1 — Targeted Exa import enrichment for selected accounts

**Status:** overall E1 gate `OPEN`; adversarially repaired mechanical/provider-contract path
`PASS`; bounded live canary `OPEN` on 2026-08-03. Repair commit `3b7458a`; see
`M06A-E1-targeted-exa-enrichment-acceptance.md`.

**Purpose:** Enrich only selected accounts without applying new fields to the entire discovery
Webset.

**Eligibility and lineage:**

- E1 is a post-seal operation. It never appends to or mutates the sealed discovery batch.
- Every target must be a canonical account in the exact current D5 seal and have a live,
  human-approved `account.scoring.tier` claim whose `decision_basis`, project run, batch, seal,
  ICP, disposition, and approved tier all match that seal. A hold/excluded/stale/foreign account
  causes preflight to fail before any provider call.
- The request carries an explicit bounded account list and an explicit versioned field plan. It
  cannot implicitly enrich every discovered account.

**Provider contract:**

1. Create a CSV import containing only the selected accounts' canonical URL identifiers.
2. Upload the exact content-addressed CSV to the returned presigned URL. The URL is a credential:
   it is never logged or durably stored, and the durable import receipt records this redaction.
3. Create an import-only Webset with that import plus the requested enrichments and no search.
4. Poll to `idle`, exhaust item pagination, and reconcile the returned import/enrichment objects.

Imported items must have `source=import`, the expected import `sourceId`, their original URL in
`sourceEntityId`, no criterion evaluations, one terminal result for every requested enrichment,
and the requested company entity type. `sourceEntityId`, not provider result ordering or a fuzzy
name, binds the result back to the already-canonical account. A missing imported row or terminal
null enrichment becomes an explicit terminal field outcome; it never creates a null claim.

**Durability and spend:**

- The request fingerprint covers the exact seal, sorted account/identifier pairs, field plan,
  provider/pricing contracts, and observation window. Reserve before the first provider request.
- Persist the input plan/CSV, sanitized import receipt, Webset receipts, every item page/item,
  claim/provenance links, field outcomes, and the final cost receipt. A terminal replay reads these
  records and makes zero provider calls.
- E1 settlement has no discovery-search row component: `2 × resolved imports`, plus `2 × ordinary
  enrichment rows` (including terminal nulls), plus `5 × actual email/phone values`. The receipt
  records a zero search charge and the original sealed batch's charge is unchanged.
- A crash after a possibly accepted Webset create is reconciled by deterministic `externalId`
  lookup; it is never blindly re-created. Presigned upload URLs are not durable credentials, so a
  known pre-dispatch import/upload failure may start a fresh uncharged import. A process crash after
  upload but before the paid create is quarantined as unknown until an operator completes the
  deterministic absence audit; the system never infers safety from one `404` and blindly creates.

**Gate E1:** a real PostgreSQL/storage run imports a bounded selected-account set, materializes the
expected claims and terminal missing outcomes, settles only the documented import/enrichment units,
and proves the original discovery row cost is not incurred again. Concurrent/restarted replay makes
no provider call and writes no duplicate equivalent claim. A bounded live canary closes the
provider-contract portion; until then mechanical integration may pass while E1 remains `OPEN`.

### Slice S1 — Sumble account gaps after scoring

**Status:** overall S1 provider gate `OPEN`; mechanical REST-v9/ledger/claim integration `PASS` on
2026-08-03; the separately authorized one-account/one-field paid live canary remains `OPEN`. See
`M06A-S1-sumble-account-gap-acceptance.md`. Implementation commit `ae05542`.

**Eligibility:** one canonical account from the exact current seal, one exact human-selected tier
claim, an active `DEEP` project run, and an explicit positive-value field plan. The approved first
wave is limited to organization employee count/domain/industry/headquarters, engineering hiring,
and confirmed technology. A confident current value, absent Sumble source in the field's tier plan,
unjustified provider cap, stale/foreign lineage, or unapproved unbounded technology call fails
before the operation ledger or HTTP boundary.

**Durability and reconciliation:** the parent operation reserves the whole authorized bundle before
dispatch. Organization, jobs, and confirmed-tech calls have independent request/response snapshots
and credit receipts. A possible paid response without a durable receipt becomes terminal
`spend_outcome_unknown`; it is never blindly retried. Terminal replay is database-only. Sumble
claims retain their own source/artifact/evidence identity, Exa claims remain live, and the shared
field merge/corroborator chooses a current value or records a conflict without provider overwrite.

**Gate S1:** the same selected account's organization/jobs/confirmed-tech snapshots are acquired by
REST v9, stored once, replayed without spend, normalized into claims, and merged/corroborated against
Exa without deleting either provider's claim. The mechanical portion proves this against real
PostgreSQL and the pinned v9 wire contract; the overall gate closes only after the separately
approved paid canary and fresh-process replay.

### Slice S2 — Top-tier buying-committee discovery

**Blocked by:** S1, the committee eligibility gate, and personal-data governance acceptance.

**Gate S2:** a non-eligible account causes zero Sumble people/team calls; an eligible account
produces identity-resolved committee candidates with inferred relationships explicitly labeled;
contact reveals run only for selected candidates and replay without spend.

### Separate future work

- Sumble signals/priority signals/briefs: no slice until separately approved.
- General Exa Search tool: separate spec and acceptance run; it must not share Websets billing or
  automatically promote search output into claims.

The 2026-08-03 live characterization made one bounded synchronous `/search` request for two neural
results. It returned the documented request/result/cost envelope plus additive production fields
such as top-level `searchTime` and per-result `score`; the call reported USD 0.007. Production also
accepted the legacy `neural` search type even though the current published OpenAPI enum has moved.
This confirms the architectural boundary: Search needs its own tolerant response adapter, request
contract/version, dollar receipt, and acceptance tests. It must not reuse the asynchronous Websets
lifecycle, credit policy, or terminal account-admission semantics.

---

## 14. Test and verification policy

### 14.1 Required layers

| Test layer | What it proves | Can it close a provider slice? |
|---|---|---|
| unit tests | parsing, normalization, hashes, state transitions, pure policy | no |
| contract fixtures | pinned request/response shapes and schema-drift behavior | no |
| real-service integration | Postgres, migrations, object storage, Redis/locks, HTTP composition | only non-provider slices |
| fault injection | crash boundaries, duplicates, ordering, retries, concurrency | required where applicable |
| live provider canary | authentication, current provider contract, async lifecycle, cost, real data | yes, required |
| production-composition acceptance | end-to-end backend behavior and durable downstream output | yes, final gate |

Unit tests may use deterministic doubles. Integration gates must use the real database and storage
implementations. Provider gates must make a bounded live call with explicit approval/cap and retain
sanitized evidence. Recorded live payloads become future regression fixtures but never replace the
live acceptance for the integration's first release.

### 14.2 Required fault matrix

- crash before provider dispatch;
- crash after dispatch before submit receipt persistence;
- duplicate create/retry;
- duplicate webhook;
- out-of-order webhook;
- invalid webhook signature;
- missed webhook with polling recovery;
- 429 with retry-after;
- provider 5xx before and after an indeterminate dispatch boundary;
- page persisted, normalization not committed;
- item normalized, claim transaction rolled back;
- identity merge between two source items;
- required enrichment returns null;
- provider reports idle but pagination/reconciliation is incomplete;
- late event after seal;
- concurrent driver/seal attempt;
- process restart in every non-terminal batch state; and
- exact query repeated after restart.

Each case asserts provider-call count, ledger status, durable artifacts, claims, cost, batch state,
and whether the project phase may advance.

### 14.3 Slice closure record

The closeout for each slice records:

- branch commit;
- exact commands/tests and results;
- database/migration identity;
- live provider request/operation ids where applicable;
- provider credits/cost before and after where observable;
- artifact/receipt/seal references;
- expected versus actual account/claim counts;
- crash/replay result;
- known limitations; and
- explicit `PASS` or `OPEN`, never “mostly passed.”

---

## 15. Final release acceptance

The account-discovery integration is releasable only if:

1. D0–D6 are all recorded `PASS` in order;
2. one exact two-row query has been run twice but submitted to Exa only once;
3. every byte returned by the provider is either preserved in an immutable artifact or explicitly
   excluded by a documented secret/redaction rule;
4. every provider item is traceable to a candidate disposition and every admitted account to a
   canonical entity;
5. every required discovery field is terminal for every sealed account;
6. every resolved value is traceable to typed claims and evidence;
7. the database, object-store, idempotency, event, page, claim, field-resolution, cost, and seal
   records reconcile;
8. no process restart or duplicate event creates a second provider operation, item, account,
   equivalent claim, cost charge, or seal;
9. scoring demonstrably reads the sealed account manifest and cannot see an unsealed partial batch;
10. the current provider contract has been exercised live, not only through fabricated responses;
    and
11. repository checks are green or every pre-existing unrelated failure is separately identified
    with evidence and cannot mask a changed-surface regression.

The leading failure signal is simple: any run marked discovery-complete without a seal, or any seal
whose referenced operation/page/item/field/cost records do not reconcile. Either condition is a
release blocker.
