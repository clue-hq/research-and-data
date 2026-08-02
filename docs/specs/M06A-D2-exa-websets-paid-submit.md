# M6A D2 — Exa Websets typed client and paid submit

Status: **implementation complete; successful live-provider gate OPEN because the configured Exa
team does not have Websets API access**

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

No migration or provider-specific lifecycle table was added. The operation remains a D1
`DiscoveryOperation`, the request/receipt remain D1 content-addressed artifacts, and the project
remains in discovery.

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

The injected maximum-credit policy is versioned: 10 credits per result, 2 per ordinary enrichment
per result, and 5 per email/phone enrichment per result. The canary requests two companies and no
enrichment, so it reserves at most 20 credits. Reservation locks the batch, reads the immutable
plan cap, sums existing reservations, and inserts one operation transactionally. A 19-credit plan
fails before provider traffic. Create starts only after request artifact and reservation commit.

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
batch becomes `waiting_external`. Create does not report final credits, so D2 records the 20-credit
maximum reservation and zero realized units. D3 settles realized units after completion.

The composition emits `discovery.exa_websets.submit`; the adapter emits
`provider.exa_websets.create`/`lookup`. Attributes contain ids, fingerprint, count, reservation,
status, and replay outcome, never query text, response body, or credential.

## 6. Verification completed

```text
pytest -q tests/adapters/test_exa_websets_d2.py
5 passed

CLUE_DATABASE_URL=.../clue_discovery_fixture \
  pytest -q tests/api/test_exa_websets_submit_d2.py
5 passed
```

The named fixture database was migrated from `933c7b604f1c` to D1 head `283ab57486e8`. Tests prove
typed/canonical transport, one-attempt POST, safe GET retry, secret-safe errors, exact request and
response artifacts, 20-credit reservation, 19-credit pre-HTTP rejection, `409` reconciliation,
pre-dispatch same-operation retry, terminal replay with zero calls, batch counters, traces, and a
fresh submitter instance with zero second provider call. `ruff check`, `ruff format --check`, and
`mypy` pass for the complete changed Python surface.

## 7. Live-provider evidence and open gate

On 2026-08-02 the canary attempted the approved two-company request from the persisted Insight
Health/Aura fixture:

```text
batch_id:                 3ba6c1c8-a086-5048-9f61-7bc7813342c6
operation_id:             302fd31e-9b2d-4a9d-a2c5-d6d0cc04c726
request_fingerprint:      7b69772be54f9cbc325c6ceed8f26d29caa1deaa029bed65867629f058411482
provider_external_id:     clue-7b69772be54f9cbc325c6ceed8f26d29caa1deaa029bed65
provider_request_id:      0712a0c5dc125016c3296230e8a4e1ef
units reserved/realized:  20 / 0
spend outcome:            not_charged
operation/batch state:    failed_terminal / failed_terminal
```

Exa returned HTTP 401 stating that the configured team lacks Websets API access and needs an
API-enabled plan. The exact response is retained only in the tenant-bound artifact. A fresh-process
replay then produced zero create calls, zero lookup calls, the same ids/artifacts, and one
`discovery.exa_websets.submit` trace.

This proves the live auth failure and idempotency paths, but it does **not** close Gate D2. Closure
still requires a `201` and real provider operation id visible in Exa. After an API-enabled team/key
is configured, an operator must approve a new observation/generation; the terminal fingerprint
above must not be mutated into success. The successful run must then be replayed in a new process
with zero second create.

## 8. Boundary into D3

D3 remains blocked until the successful-live row in §7 exists. It will consume the D1 operation
and provider ids, not submit a new Webset. D3 owns webhook verification, scheduled polling, cursor
pagination, page/item receipts, final reconciliation, and realized-credit settlement. D2 does not
materialize accounts or advance the project.
