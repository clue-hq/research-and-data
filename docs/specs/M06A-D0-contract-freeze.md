# M6A D0 — Durable discovery contract freeze

Status: **implemented; D0 gate evidence recorded in §10**

Parent plan: `docs/specs/M06A-exa-websets-sumble-discovery-integration.md`

Scope: shared contracts, field policy/registry, executable sanitized fixtures, and D1 schema review

Out of scope: migrations, provider credentials, external calls, webhooks, polling, materialization,
and any Sumble call

## 1. Purpose and authority

D0 freezes the platform-owned meaning of a discovery request and of a completed discovery batch
before any provider implementation can spend money. The provider may report progress or `idle`; it
does not decide when the platform may advance to scoring. The project remains in discovery until
the immutable batch seal exists.

The current Exa Websets `v0` documentation was rechecked on 2026-08-02. It describes an
asynchronous lifecycle, cursor-paginated items/events, HMAC-SHA256 webhooks, company item
properties, `yes | no | unclear` evaluations, and enrichment results represented as string arrays
or `null`. Those are provider-boundary facts. The fourteen-condition seal, request identity,
field-resolution rules, claim/provenance requirements, and tenancy policy are Clue-owned
contracts.

Primary references:

- <https://exa.ai/docs/websets/api-guide-for-coding-agents>
- <https://exa.ai/docs/websets/api-guide>
- <https://exa.ai/docs/reference/search>

## 2. Frozen scope and non-goals

D0 provides:

1. one shared Pydantic contract module for plan, operation, event, page, item snapshot, field
   resolution, failure, readiness, and seal;
2. one byte-canonical request fingerprint and deterministic provider `externalId` derivation;
3. one versioned account-envelope policy plus the registered field definitions it names;
4. sanitized local Exa fixtures for every D0 provider-shape scenario;
5. a fourteen-row seal truth table; and
6. a reviewed D1 ownership/schema map with tenancy, retention, artifact, and DSAR requirements.

D0 deliberately does not:

- add or alter a database table;
- add `WAITING_EXTERNAL` to the live project state machine (D1 owns that runtime delta);
- submit, preview, poll, cancel, enrich, or otherwise call Exa;
- implement a provider response parser or HTTP client (D2);
- accept webhooks or paginate live results (D3);
- admit identities or write discovery field claims (D4); or
- call Sumble (later tier-gated slices only).

## 3. Contract and import ownership

| Concern | Owner/module | Allowed dependencies | Forbidden coupling |
|---|---|---|---|
| Shared discovery ids, enums, plans, operation/event/page/item/field/seal/failure contracts | `libs/clue-core/clue_core/discovery.py` | Python, Pydantic, other `clue_core` primitives | No research worker, DB, HTTP, Exa, or Sumble import |
| Versioned account-envelope policy | `subsystems/research/clue_research/discovery_scoring/discovery/field_policy.py` | `clue_core` only | No durable/provider import |
| Canonical field definitions | `subsystems/research/clue_research/claimstore/packs.py` | Existing registry seams | No discovery lifecycle state |
| Sanitized provider payloads | `tests/fixtures/discovery/exa_websets/` | Local JSON only | No credentials or live ids |
| D1 repositories and transactional seal writer | Future `clue_research.durable.discovery` | `clue_core`, DB/storage seams | Must not import `discovery_scoring` or a provider |
| D2 typed Websets transport/signature code | Future provider-owned adapter package | `clue_core`, shared HTTP/snapshot seams | No claim-store write or scoring decision |
| D3 webhook HTTP endpoint and scheduler wake-up | `clue_api` composition root | Provider adapter + durable repository protocols | Webhook request must not materialize claims |
| D4 normalized snapshot-to-candidate/claim logic | `discovery_scoring` plus existing identity/claim seams | Shared contracts and stored snapshot references | No live provider call from normalization |
| Composition across worker packages | `clue_api` only | May bind independent packages | No worker-to-worker imports |

This preserves the existing distinction between an entity-producing `DiscoveryChannel` and a
known-entity field `Resolver`. The D2 transport persists provider operations and payloads; D4 may
surface stored, normalized candidate records through the channel seam. The resolver waterfall is
not repurposed to create companies.

## 4. Shared contract inventory

The authoritative exports are in `clue_core.discovery`.

### 4.1 Plan

`DiscoveryPlan` is immutable and carries:

- plan id/version and workspace/project/project-run/ICP lineage;
- provider-policy, field-policy, and provider-contract versions;
- ordered channel and search plans;
- ordered criteria and typed enrichments;
- required and optional logical account fields;
- provider-credit and money caps; and
- stopping and snapshot-reuse policy references.

Validation rejects duplicate channels/search keys/fields, required/optional overlap, a search for an
undeclared channel, more than five criteria, more than ten enrichments, an options enrichment with
no options, duplicate enrichment fields/options, and `max_people_per_company` on a non-person
search.

### 4.2 Operation, event, page, and item

- `DiscoveryOperation` is the replay/spend identity for one provider request. Its state and spend
  outcome are separate so `spend_outcome_unknown` cannot be mistaken for a retryable no-charge
  failure.
- `DiscoveryProviderEvent` records the provider event id, signature-verification result, raw
  artifact reference, provider/receipt timestamps, and processing disposition. Duplicate,
  superseded, and late-after-seal states are first-class.
- `DiscoveryPageReceipt` uses a non-null `__first_page__` sentinel. This is intentional: a normal
  Postgres `UNIQUE(..., request_cursor)` permits multiple `NULL` first-page rows. `has_more=true`
  requires `next_cursor`; a terminal page requires `next_cursor=null`.
- `DiscoveryItemSnapshot` identifies immutable raw bytes by SHA-256 and keeps normalization state
  separate. Unknown additive provider fields remain in the raw artifact even when the current
  normalizer does not understand them.

### 4.3 Field resolution

`DiscoveryFieldResolutionState` freezes:

```text
pending
resolved
confirmed_missing
conflict
review_required
accepted_missing
account_excluded
blocked_by_policy
failed_retryable
failed_terminal
```

The seal-terminal states are `resolved`, `confirmed_missing`, `conflict`, `accepted_missing`,
`account_excluded`, and `blocked_by_policy`. `pending`, `review_required`, `failed_retryable`, and
an undisposed `failed_terminal` block sealing. A resolved field requires a winning claim contained
in its claim-id set. A missing value is a disposition, never a null-valued claim.

### 4.4 Failure

`DiscoveryFailure` carries a typed, secret-safe code, retryability, spend outcome, optional provider
status, and receipt reference. `indeterminate_dispatch` is valid only with `spend_outcome=unknown`.
This makes “the request may have reached the paid provider” structurally different from “nothing
was dispatched.”

## 5. Exact request identity

`DiscoveryRequestFingerprintInput.canonical_bytes()` serializes UTF-8 JSON with sorted object keys,
compact separators, explicit `null` values, and ordered arrays. Query/criterion/enrichment/option
text is Unicode NFKC-normalized with whitespace collapsed before hashing.

The SHA-256 input contains exactly:

- workspace id;
- provider source key and API version;
- entity type and custom description when applicable;
- normalized query;
- ordered criteria descriptions;
- requested count and search behavior;
- ordered enrichment field keys, descriptions, formats, and option labels;
- `max_people_per_company` when applicable;
- ICP key/version;
- discovery-plan version;
- field-policy version;
- provider-contract version; and
- observation window/freshness bucket.

It excludes secrets, headers, random ids, webhook material, incidental timestamps, retry number,
and scheduler state. Ordering is deliberately significant. Workspace scope is deliberately
significant. The provider external id is `clue-` plus the first 48 lowercase hex characters of the
validated fingerprint; because workspace scope participates in the fingerprint, two workspaces do
not collide.

Golden inputs, exact canonical byte strings, and expected digests live in
`tests/fixtures/discovery/request-fingerprint-vectors.json`. A subprocess test runs them under two
different Python hash seeds and compares bytes, not merely semantic JSON.

## 6. Account discovery envelope v1

Policy id: `discovery-envelope-v1`.

| Logical requirement | Requirement | Ordered canonical storage/attempt | Seal behavior |
|---|---|---|---|
| `identity.account_name` | hard identity | `account_entity.canonical_name` | must resolve; no missing disposition |
| `identity.primary_domain` | hard identity | `account_entity.primary_domain`, `core.primary_domain` | must resolve; no missing disposition |
| `discovery.company_linkedin_url` | required attempt | `core.company_linkedin_url` | value or honest terminal disposition |
| `discovery.industry` | required attempt | `core.industry` | value or honest terminal disposition |
| `discovery.employee_size` | required attempt | `core.employee_count` then `core.employee_range` | exact preferred; range fallback |
| `discovery.headquarters` | required attempt | `account_entity.hq_geo`, `core.hq_location` | value or honest terminal disposition |
| `discovery.revenue` | required attempt | `core.annual_revenue` then `core.revenue_band` | sourced amount preferred; band fallback |
| `discovery.company_email` | optional attempt | `core.company_email` | separately budgeted; not personal reveal |
| `discovery.company_phone` | optional attempt | `core.company_phone` | separately budgeted; not personal reveal |

The registry now contains all eight missing canonical fields. `core.annual_revenue` requires amount,
currency, as-of, and one explicit estimate kind: `reported`, `provider_estimate`, or
`third_party_estimate`. `core.revenue_band` is a bounded enum. `core.company_email` and
`core.company_phone` mean a public general company channel; they are intentionally separate from a
person's work email or direct phone.

Required attempt does not mean “fabricate a value.” It means all configured attempts reached a
terminal, evidenced outcome. Honest missing/conflict/policy dispositions remain valid outputs.

## 7. Fourteen-condition seal barrier

The shared `DiscoverySealReadiness` and `evaluate_discovery_seal()` contract assigns one stable
blocker code to each condition:

| # | Condition | Blocker code |
|---:|---|---|
| 1 | Plan exists and workspace/project/project-run/ICP lineage matches | `plan_lineage` |
| 2 | Every planned operation is succeeded or explicitly accepted terminal failure | `operation_terminality` |
| 3 | Dispatch/response or indeterminate receipts and raw artifacts exist | `dispatch_receipts` |
| 4 | Every accepted event is verified, durable, and processed/superseded | `provider_events` |
| 5 | Final authoritative poll reconciliation is complete | `final_reconciliation` |
| 6 | Every paginated resource is exhausted with page receipts | `pagination_exhaustion` |
| 7 | Every provider item has raw and normalized records | `item_materialization` |
| 8 | Every candidate identity is admitted, merged, or excluded | `candidate_identity` |
| 9 | Every admitted account has hard identities | `hard_identities` |
| 10 | Every required logical field is seal-terminal | `required_fields` |
| 11 | Every value has claims/provenance or a durable disposition | `claim_or_disposition` |
| 12 | Duplicate identities collapse and every source item maps to survivor | `survivor_links` |
| 13 | Provider units and money reconcile to durable receipts | `spend_reconciliation` |
| 14 | Account/claim/raw-artifact manifests and referenced artifacts exist | `final_manifests` |

D1 must evaluate these from one database transaction snapshot and insert the seal in that same
transaction. It may not perform a check, release the transaction, and then write a seal.

## 8. Executable Exa fixture matrix

| Fixture | Required D0 scenario |
|---|---|
| `webset-running.json` | asynchronous running submit state |
| `items-page-1.json` | company base fields, `yes`, `unclear`, null enrichment, non-terminal cursor |
| `items-page-2.json` | `no`, excluded-style item, terminal cursor |
| `events-duplicate-out-of-order.json` | duplicate provider event id and non-monotonic delivery order |
| `webset-cancelled.json` | canceled search and enrichment remain non-success |
| `schema-drift-additive.json` | unknown top-level/nested fields preserved in raw bytes |

The test suite verifies all fixtures are local JSON, secret-marker free, and usable with network
sockets disabled. These are not evidence of live provider behavior and do not close D2 or D3.

## 9. D1 table, tenancy, retention, and DSAR review

The parent spec's conceptual tables stand, with these binding refinements for D1:

### 9.1 Keys and tenant enforcement

- Every discovery table carries non-null `workspace_id`, even when it is derivable from a parent.
  Child rows use composite foreign keys such as `(workspace_id, operation_id)` so a bad join cannot
  bind a row to another tenant's operation.
- Every repository method requires workspace scope and includes it in reads, updates, and conflict
  targets. There is no unscoped `get(id)` production method.
- `discovery_batch` remains unique on `(workspace_id, project_run_id, generation)`.
- `discovery_operation` remains unique on
  `(workspace_id, source_key, request_fingerprint, observation_window)`.
- Provider external ids are unique on `(source_key, provider_external_id)`; their deterministic
  fingerprint already includes workspace scope.
- First-page uniqueness uses a non-null `request_cursor_key='__first_page__'`, not a nullable cursor
  in a normal unique constraint.
- Event uniqueness is `(workspace_id, operation_id, provider_event_id)`; item lineage uniqueness is
  `(workspace_id, operation_id, provider_item_id, item_sha256)`.
- `discovery_batch_seal.batch_id` is the primary key. Concurrent seal attempts either insert the
  identical seal once or observe the existing identical seal; divergent content is an error.

### 9.2 Artifact and truth boundaries

- Postgres is authoritative for lifecycle, lineage, idempotency, dispositions, receipts, and seal.
- Object storage holds immutable raw request/response/event/page/item/manifests. Every row stores a
  content hash and tenant-bound artifact key.
- All raw provider payloads are tenant-bound because a body can contain personal data even when its
  materialized account claim is reusable public footprint.
- Claims remain the only factual truth store. Discovery operation/item tables are execution and
  evidence lineage, never an alternative firmographic profile.
- Secrets, authorization headers, API keys, webhook secrets, and credential-bearing URLs are
  rejected before artifact capture and never enter logs/traces/receipts.

### 9.3 Retention and erasure

- Operation metadata, receipts, seal, and manifest hashes follow the project audit-retention
  policy. Provider-side event retention (currently documented as 60 days) is not relied upon for
  replay; accepted events are captured internally before acknowledgement.
- Raw provider artifacts use a versioned workspace retention class. D1 must support tombstoning and
  verified object deletion when workspace policy or DSAR requires it; a hash/reference tombstone
  may remain for audit, but erased bytes may not.
- Account/contact subject indexes map item snapshots, claims, events, and manifests to resolved
  entities. A DSAR can therefore find raw payloads as well as materialized claims.
- A late event after erasure or seal is recorded with a non-materializing disposition. It cannot
  silently recreate erased personal data or mutate a sealed generation.
- Cross-tenant snapshot reuse is forbidden at the raw-artifact layer. Reusable public claims may be
  re-materialized only through the existing reuse-scope policy and provenance rules.

### 9.4 Required D1 schema proof

D1 acceptance must prove with real Postgres/object storage:

1. composite tenant foreign keys and scoped repositories reject cross-workspace access;
2. the first page cannot be inserted twice under a null-cursor loophole;
3. duplicate/out-of-order events and duplicate pages/items converge idempotently;
4. a process crash after raw page persistence resumes without refetch/recharge;
5. all fourteen barrier predicates are SQL-derived and one false predicate prevents sealing;
6. concurrent seal writers produce one identical immutable seal; and
7. DSAR enumeration finds every tenant-bound raw artifact reference for the subject.

## 10. D0 gate evidence

The D0 gate is contract/schema proof only; by design it makes no external provider call.

Recorded 2026-08-02:

```text
.venv/bin/python -m pytest \
  tests/discovery_scoring/test_discovery_contracts_d0.py \
  tests/discovery_scoring/test_exa_websets_fixtures_d0.py \
  tests/discovery_scoring/test_discovery_field_policy_d0.py -q
35 passed

CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_discovery_fixture \
  .venv/bin/python -m pytest \
  tests/claimstore/test_field_registry.py \
  tests/claimstore/test_core_pack_tier4_routing.py \
  tests/claimstore/test_discovery_envelope_fields.py -q
16 passed against the real fixture-bearing Postgres database

CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_d0_contract_test_<run> \
  .venv/bin/python -m pytest tests/discovery_scoring -q
150 passed against an ephemeral clean, migrated Postgres database; the database was then dropped
```

Additional closeout commands and their final counts are recorded in the corresponding `_memory/`
session note. D1 may begin only after the full changed-surface lint/type/import-contract/regression
gate remains green and the D0 commit is isolated.
