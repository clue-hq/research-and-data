# M8B A0 — Account-deep provider contract and authority acceptance

- **Parent roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice A0
- **Recorded:** 2026-08-04
- **Status:** request contract amended by E0-R1 and response contract amended by E0-R2 on
  2026-08-04; no live provider call authorized
- **Exa endpoint:** `POST https://api.exa.ai/search`
- **Official reference:** `https://exa.ai/docs/reference/search-api-guide-for-coding-agents`
- **Reference reviewed:** 2026-08-04; the live documentation is mutable, so no current-page digest
  is represented as immutable provider evidence
- **Sumble companion:** `M06A-S2-sumble-committee-acceptance.md`

This record closes A0's missing Exa and cross-provider authority decisions. It freezes contracts,
fixtures, flags, operation ownership, identity, URLs, error/spend classification, and the source
authority boundary. It does not modernize or bind the legacy Exa resolver, dispatch a request, add
the E1 acquisition ledger, or authorize spend.

## 1. Exa Search Deep wire contract

### 1.1 Request

The accepted account-deep request is non-streaming `POST /search` with:

- `type` explicitly `deep` or `deep-reasoning`; `neural`, `auto`, and Websets are not accepted;
- product cap `numResults <= 50` even though the public API currently permits up to 100;
- zero to ten unique directional queries, compiled from a confirmed directive rather than
  arbitrary untrusted interpolation; zero is represented by omitting nullable
  `additionalQueries`, while a present array contains one to ten entries;
- a closed object `outputSchema` with one to eight reversible provider-safe aliases, all required,
  and `additionalProperties=false`; every alias hex-encodes exactly one admitted registry field key
  and the fixed system prompt carries the exact alias-to-field map;
- at most ten declared properties in total and at most two named property levels across the full
  schema, including nested object/array-item properties; over-budget bundles fail before dispatch
  so E1 can split them without guessing;
- one supported non-null type per field plus optional `null`; the compiler uses a JSON-Schema
  `type: [T, "null"]` union and adds `null` to an enum when necessary, never `anyOf`/`oneOf`;
- `systemPrompt` carrying the exact-account/no-drift, source-URL, and leave-null rules;
- `contents.text.maxCharacters=10000` and query-guided
  `contents.highlights.maxCharacters=2000` as explicit account-deep product budgets (not claimed
  provider maxima); deprecated `numSentences` and `highlightsPerUrl` are forbidden;
- `stream=false` for the first release so one durable JSON response owns settlement.

The golden request is
`tests/fixtures/providers/exa/search/deep_request.json`, SHA-256
`45a7ab41ab156bd4b6810db87c2e2852bc39b3e90049db307be42dd22cbf2f98`.
`ExaDeepSearchRequest` forbids unknown request members and fails on the old `neural` mode, an
over-cap request, dotted/injected provider properties, a missing alias map, deprecated/unbounded
content controls, an over-budget schema, unsupported schema composition, or missing target-lock
rules.

### 1.2 Successful response

The accepted settleable response requires:

- non-empty `requestId`;
- at least one result with a real source `url` and title, retaining returned text/highlights, unless
  the response is an all-null/no-grounding paid hard miss (where `results=[]` is valid);
- structured `output.content` keyed by the reversible provider aliases from the request;
- field-level `output.grounding` with at least one citation URL/title per grounding row when any
  output is non-null; an all-null paid hard miss may omit grounding or return an empty array;
- exactly one grounding row for every non-null top-level output field;
- every returned value, including nested values and nulls, validates against the exact admitted
  request property schema before normalization;
- every grounding citation resolves to a retained result carrying non-empty text or a highlight, so
  the response can produce an inspectable evidence span;
- `costDollars.total >= 0`.

The golden response is
`tests/fixtures/providers/exa/search/deep_response.json`, SHA-256
`7cf7c23aecb67a029902de97ea0d818f4fdd37aa32506cf1cdce7eaccf05687a`.
Response models tolerate additive provider fields at the response, result, output, citation, and
cost levels. They do not branch on deprecated `resolvedSearchType` or `context`. A structurally
valid all-null response retains `requestId` and reported cost and normalizes to an empty paid hard
miss, not `spend_unknown`.

### 1.3 Source and evidence URL semantics

- Exa's API URL is transport provenance, never claim evidence.
- `requestId` is provider operation correlation, not an entity or evidence key.
- each result `url` is the retrieved public page and is retained in the raw snapshot;
- each grounding citation `url` is the provider's field-level evidence link;
- a materialized claim's `source_url` is a grounding/result page URL, never `exa.ai`, a request id,
  or a synthetic fixture URL in production;
- the claim's evidence span must be inspectable text from the cited result. A structured value and
  citation URL without an evidence span remain unverified and cannot promote.
- normalization evaluates every citation separately, selects the best retained highlight/text
  passage with conservative overlap to that exact field value/key, and never assigns a page's
  unrelated first highlight merely because the page was cited;
- every provider citation becomes an immutable attribution record with field, URL, title,
  confidence and selection disposition; unsupported citations remain in the raw response and
  attribution set but do not become claim candidates.

### 1.4 Charging and settlement decision

Exa documents `costDollars` as an estimated completed-request cost, while billing is computed from
usage counters rather than that object. Therefore:

1. reserve the internal hard cap before dispatch;
2. pre-dispatch failure is not charged;
3. after dispatch, timeout/429/5xx or malformed/missing-cost success is `spend_unknown`, never zero;
4. a structurally valid 2xx response with `requestId` and `costDollars.total` may settle the run's
   provisional realized cost exactly once, retaining that the value is provider-reported estimate;
5. provider billing/usage reconciliation remains the final accounting authority;
6. 402 is a budget failure; 400/401/403/404 are hard request/auth failures; retryable transport
   classification never implies that a dispatched attempt was free.

E1 must durably store request, raw response, request id, reported cost, reservation, settlement and
reconciliation receipt before materialization.

## 2. Exact configuration authority

| Purpose | Name | Default |
|---|---|---|
| Existing secret | `CLUE_EXA_API_KEY` | absent |
| New paid account-deep authorization | `CLUE_EXA_ACCOUNT_DEEP_ACQUISITION_ENABLED` | `false` |
| Search mode | `CLUE_EXA_ACCOUNT_DEEP_SEARCH_TYPE` | `deep-reasoning` |
| Result cap | `CLUE_EXA_ACCOUNT_DEEP_MAX_RESULTS` | `50`, hard maximum 50 |
| Directional-query cap | `CLUE_EXA_ACCOUNT_DEEP_MAX_ADDITIONAL_QUERIES` | `10`, hard maximum 10 |
| Sumble S2 authorization | `CLUE_SUMBLE_COMMITTEE_ACQUISITION_ENABLED` | `false` |
| Sumble credential | `CLUE_SUMBLE_API_KEY` | absent |

Websets lifecycle/acquisition and targeted-enrichment flags never authorize account-deep Search.
The new Exa flag has no production consumer until E2 composition; default-off therefore produces
zero account-deep Search calls.

## 3. Operation-store decision

The inventory found four materially different durable lifecycles:

- `discovery_operation`: Exa Websets discovery pages/items and immutable batch seal;
- `targeted_enrichment_operation`: post-seal Exa Websets import/CSV lifecycle;
- `account_gap_operation`: synchronous bounded Sumble S1 organization/job/technology snapshots;
- `committee_acquisition_operation`: Sumble S2 synchronous Teams plus asynchronous People polling.

They cannot safely be overloaded for synchronous Exa Search: Websets tables require import/CSV or
batch paging semantics, while Sumble tables encode credit and Teams/People-specific transitions.

Decision:

1. retain existing ledgers and migrations; A0 performs no risky rewrite;
2. `ExternalResearchPreparation` is the provider-neutral control-plane return contract for READY,
   WAITING_EXTERNAL, INELIGIBLE and FAILED outcomes;
3. E1 introduces one generic `external_research_operation`/snapshot/attempt/receipt ledger for new
   account/contact research products, with Exa Search as its first adapter;
4. that ledger owns subject kind, account/contact id, directive id/version/digest, ICP coordinates,
   source key, request fingerprint, artifact refs, provider correlation, reservation, charged cost,
   spend-unknown and replay/freshness without provider-specific columns;
5. existing Sumble S2 may expose an adapter to the shared preparation contract, but is not migrated
   until a separate data-migration decision proves value;
6. no later provider may create another lifecycle table without a recorded incompatibility with the
   generic ledger.

## 4. Strong identity decisions

- Account-deep Search targets one resolved account id plus canonical name/domain and geography.
- Exa result ids/request ids are provenance only; they never create or re-key an account.
- Sumble `person_id` remains provider provenance, not a platform strong person key.
- Sumble committee admission still requires LinkedIn URL or independently verified email; the
  first S2 release requests neither email nor phone reveal.

## 5. Authority source map

### Decided from provider documentation

- Exa endpoint, deep modes, 1–100 public API result range, maximum ten additional queries,
  structured output and grounding shapes, deprecated fields, request id, and reported cost shape;
- Sumble v9 endpoint/status/credit/no-reveal details in the S2 companion record.

### Product-governed decisions

- 50-result Exa cap; non-streaming first release; closed registered-field schema; exact-account
  prompt; field-level grounding/evidence requirement; independent flags; spend-unknown handling;
- exact source-key authorization through a content-addressed effective field source plan;
- generic future external-research ledger rather than another provider-specific lifecycle.

### Unresolved until E0/E1/live canary

- account-specific Exa pricing/entitlement and billing export reconciliation;
- latency and timeout calibration for `deep` versus `deep-reasoning`;
- whether every live successful response supplies `requestId` and `costDollars.total` under the
  account's plan. Missing either fails closed as non-settleable/spend-unknown;
- live synthesis-field path details beyond the documented two-level contract; E0 keeps schemas
  bounded to two named property levels and ten total properties.

## 6. A0 exit gate

A0 is mechanically closed when:

1. request/response goldens match the recorded digests;
2. the request model rejects neural mode, over-cap results and field-schema injection;
3. the response accepts additive fields and a paid all-null/no-grounding miss, but rejects missing
   cost/output, missing grounding for a non-null field, and any value outside the admitted schema;
4. post-dispatch ambiguity classifies spend unknown;
5. exact independent flags load with default-off and hard caps;
6. the Sumble companion contract tests still pass;
7. no network call, production resolver binding, provider operation or paid spend occurs.
