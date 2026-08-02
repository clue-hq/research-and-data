# M6A D2 — Exa Websets typed client and paid submit

Status: **implementation complete; successful live-provider gate CLOSED on 2026-08-03**

Parent plan: `docs/specs/M06A-exa-websets-sumble-discovery-integration.md`

Predecessors: `docs/specs/M06A-D0-contract-freeze.md` and
`docs/specs/M06A-D1-durable-discovery-batch.md`

Scope: Websets `v0` request/response contracts, one-attempt create transport, deterministic paid
request identity, atomic provider-credit reservation, durable submit request/response receipts,
duplicate/uncertain reconciliation, and exact replay without another create

Out of scope: webhooks, polling to idle, pagination, final provider-credit settlement, item
snapshots, identity admission, claim materialization, field-resolution decisions, and batch seal

## 1. Delivered boundary

D2 adds the first provider-specific discovery adapter without weakening D1:

| Concern | Owner | Contract |
|---|---|---|
| Websets `v0` wire models and HTTP behavior | `clue_research.adapters.exa_websets` | No DB, claim, identity, scoring, or seal decision |
| Atomic reservation and create-dispatch claim | `clue_research.durable.discovery` | Provider-neutral D1 tables; cap read from immutable plan |
| Provider + durable composition | `clue_api.exa_websets_submit` | API-root-only import of adapter and durable worker |
| Bounded live/replay operator surface | `scripts/09_exa_websets_d2_canary.py` | Explicit DB, observation window, and live-create flag |

No provider-specific lifecycle table was added. The operation remains a D1
`DiscoveryOperation`, the request/receipt remain D1 content-addressed artifacts, and the project
remains in discovery. Review hardening added migration `fe7d6c0aee8a`, which adds provider-neutral
`cost_cents_reserved` columns to the existing batch and operation tables so the monetary cap is
enforced before dispatch rather than remaining a zero-valued reporting field.

## 2. Pinned provider contract

The adapter is pinned to:

- base URL `https://api.exa.ai/websets/v0`;
- `POST /websets` for create and `GET /websets/{id-or-externalId}` for reconciliation;
- `x-api-key` authentication;
- `search.query`, `search.count`, `search.entity`, up to five criteria, optional
  `maxPeoplePerCompany`, up to ten enrichments, metadata, and `externalId`;
- top-level Webset identity/lifecycle fields plus typed search/enrichment identities; and
- the documented `400/401/402/403/404/409/422/429/5xx` error classes.

The platform's `DiscoverySearchBehaviour.OVERRIDE` remains in the semantic fingerprint. It is not
sent in the create body because the current create schema does not accept a behavior field; the
created `WebsetSearch` returns `behavior=override`. Request models reject unknown fields. Response
models require the pinned identity/lifecycle fields while preserving additive provider fields in
the immutable raw response.

Official references used:

- <https://exa.ai/docs/websets/api-guide-for-coding-agents>
- <https://exa.ai/docs/websets/api/websets/create-a-webset>
- <https://exa.ai/docs/websets/api/websets/get-a-webset>
- <https://exa.ai/docs/reference/error-codes>
- <https://exa.ai/docs/reference/openapi-spec>

## 3. Request identity and maximum spend

`DiscoveryRequestFingerprintInput` contains workspace, source, API version, entity, normalized
query, ordered criteria, count, behavior, ordered enrichments, ICP/plan/policy versions, and the
observation window. It excludes secrets, timestamps, transport headers, and random ids.

The full SHA-256 becomes the D1 request fingerprint. `clue-<first-48-hex>` becomes Exa's
`externalId`; the full fingerprint and contract version are provider metadata. A duplicate or
uncertain result can therefore be looked up and target-checked without a second create.

The injected maximum-credit policy is versioned: 10 credits per all-criteria match, 2 per row for
each ordinary enrichment, 5 per returned email/phone value, and 2 per resolved import. The canary
requests two companies and no enrichment, so it reserves at most 20 credits. Reservation locks the
batch, reads both immutable plan caps, sums existing provider-unit and monetary reservations, and
inserts one operation transactionally. A 19-credit cap or a monetary cap below 8.980 cents fails
before provider traffic.

Exa does not return operation-level dollars. `cost_cents_*` therefore has the explicit semantics
`subscription-credit-allocation-equivalent`, not “card charged for this call.” The default runtime
policy is pinned to the public Pro allocation: USD 449 / 100,000 credits = 0.449 cents per credit.
Its version is `exa-websets-public-credit-policy-2026-08-03+pro-usd-allocation`. A plan with a
different policy version is rejected; a deployment on Starter or Enterprise must inject and pin
its own valuation instead of silently using the Pro quotient.

## 4. Dispatch and replay matrix

| Durable state/evidence | Behavior | Create calls |
|---|---|---:|
| no matching operation | reserve, claim `planned -> submitting`, create | 1 |
| matching successful/running operation with receipt | return stored operation | 0 |
| matching terminal failed/cancelled operation with receipt | return stored disposition | 0 |
| fresh `submitting` operation | join in-flight attempt during grace window | 0 |
| stale `submitting` or unknown spend | lookup deterministic `externalId` | 0 |
| proven pre-dispatch transport failure | `failed_retryable/not_dispatched`; same operation may retry | at most 1 later |
| create `409` | GET by `externalId`, validate fingerprint/request | 1 total |
| timeout/429/5xx/contract drift after possible acceptance | GET by `externalId`; never auto-create again | 1 total |
| lookup establishes matching Webset | preserve create + lookup receipts; wait | 1 total |
| lookup cannot establish outcome | `spend_outcome_unknown`; block another create | 1 total |
| terminal 400/401/402/403/422 | preserve receipt; known `not_charged`; require new approved identity | 1 total |

The client never retries POST. GET may retry bounded `429/5xx` responses and honors capped numeric
`Retry-After`. Connect/pool failures are distinct from read/write uncertainty. Error strings carry
only status, tag, and request id; raw response bodies are not logged.

## 5. Artifacts, counters, and traces

The exact canonical JSON request is stored before create; auth headers never enter it. A `201` body
is stored byte-for-byte. A duplicate or uncertain outcome stores an envelope containing exact
available create/lookup bodies as base64 plus independent hashes. Terminal errors use that envelope.

An accepted create records provider id, submit receipt, next poll time, and `provider_running`; the
aggregate batch becomes `provider_running` once every planned operation exists in that state. D3
transactionally adds one stable initial-poll wake at this
same boundary. Create does not report final credits, so D2 records the 20-credit maximum reservation
and zero realized units. D3 settles credits from terminal item facts after completion.

The composition emits `discovery.exa_websets.submit`; the adapter emits
`provider.exa_websets.create`/`lookup`. Attributes contain ids, fingerprint, count, reservation,
status, and replay outcome, never query text, response body, or credential.

## 6. Verification completed

```text
pytest -q tests/adapters/test_exa_websets_d2.py
passed

CLUE_DATABASE_URL=.../clue_discovery_fixture \
  pytest -q tests/api/test_exa_websets_submit_d2.py
passed
```

The named fixture database was migrated from `933c7b604f1c` to D1 head `283ab57486e8`. Tests prove
typed/canonical transport, one-attempt POST, safe GET retry, secret-safe errors, exact request and
response artifacts, 20-credit/8.980-cent reservation, provider-unit and monetary pre-HTTP
rejection, `409` reconciliation, pre-dispatch same-operation retry, terminal replay with zero
calls, batch counters, traces, and a fresh submitter instance with zero second provider call.
`ruff`, full `mypy` (467 source files), and all 24 import contracts pass. Migration smoke passed on
a clean disposable database through `head -> base -> head` and that database was removed.

## 7. Live-provider evidence and closed gate

The two earlier 401/not-charged operations remain immutable historical evidence. After an
API-enabled team/key became available, generation 4 used observation
`2026-08-03-d3-live-v1` for the approved two-company Insight Health/Aura workload:

```text
batch_id:                 14be6f08-3838-5b9a-9899-f0765ef42c08
operation_id:             38a236b2-52ef-43f7-a98c-e26de5671521
provider_operation_id:    webset_01kz2b6wcyb25pzt3c83s7vhs2
request_fingerprint:      c8f8c45854b22f5cb347ff396e50077f833b235d52c90826d33f3ae901566c36
units reserved/realized:  20 / 20
cost reserved/realized:   8.980 / 8.980 cents allocation-equivalent
operation/batch state:    succeeded / identity_resolution
```

The create returned a real provider operation visible in Exa. A replay-only fresh process then
reported `create_calls_this_process=0`, `lookup_calls_this_process=0`, the same operation and
artifacts, and the terminal settled counters. This closes Gate D2 without mutating either historical
failed fingerprint.

## 8. Boundary into D3

`M06A-D3-exa-websets-lifecycle.md` records the completed asynchronous retrieval boundary. D3
consumes the D1 operation and provider ids; it does not submit a new Webset. D2 does not
materialize accounts or advance the project.
