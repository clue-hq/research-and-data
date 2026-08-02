# M6A D3 — Exa Websets asynchronous retrieval lifecycle

Status: **implementation complete; search-only and one-row enriched live-provider gates CLOSED on
2026-08-03**

Parent plan: `docs/specs/M06A-exa-websets-sumble-discovery-integration.md`

Predecessors: `docs/specs/M06A-D0-contract-freeze.md`,
`docs/specs/M06A-D1-durable-discovery-batch.md`, and
`docs/specs/M06A-D2-exa-websets-paid-submit.md`

Scope: team-level signed webhook ingestion, initial and scheduled poll wakes, single-driver
reconciliation, cursor pagination, immutable page/item snapshots, strict terminal request/result
reconciliation, rule-derived credit and attributed-money settlement, restart/crash recovery, and
production HTTP/fleet composition

Out of scope: account identity admission, item normalization, candidate creation, claims,
field-resolution decisions, batch seal, project advance to scoring, Sumble, or general Exa Search

## 1. Acceptance contract

D3 passes only when all rows below are true.

| Requirement | Pass condition | Implementation/evidence |
|---|---|---|
| Webhook authenticity | raw bytes verify against `HMAC-SHA256(timestamp + "." + raw_body)`; timestamp is within 300 seconds; any `v1` may match in constant time | `verify_exa_webhook_signature`; adapter tests |
| Webhook topology | one team-level Exa subscription targets one platform endpoint and owns one signing secret; no per-operation registration fiction | `ExaTeamWebhookProvisioner`; `/v1/webhooks/exa-websets` |
| Tenant-safe webhook routing | signature and event schema are verified, then `websetId` resolves the globally unique durable operation; only then may the raw event enter that operation's workspace | `ExaWebhookIngestor.ingest`; unrelated signed-event test |
| Event idempotency/order | unique `(workspace, operation, provider_event_id)`; duplicate content returns duplicate; changed content fails; delivery order has no authority | `record_discovery_event`; real-DB duplicate/out-of-order test |
| Webhook authority | webhook only appends event + wake; it cannot mark idle, reconcile, settle, materialize, or advance | ingestor test proves operation remains provider-running |
| Initial poll | every successful/reconciled D2 submit creates one transactional `exa-initial-poll:<operation>` wake | `DurableExaWebsetSubmitter._persist_success`; D2 replay test |
| Scheduled polling | fleet worker claims only `exa_websets` wakes; connection/408/425/429/5xx retries are visible as durable waits and honor capped `Retry-After` | `ExaDiscoveryWakeWorker`; lifecycle rate-limit test |
| Single driver | operation atomically enters `reconciling` with a two-minute lease; another worker joins; an expired lease is reclaimable | `claim_discovery_operation_reconciliation` |
| Wake crash recovery | a claimed-but-unprocessed wake becomes reclaimable after its lease, never before | `claim_due_discovery_wakes`; real-DB stale-lease test |
| Page-before-process | each provider page artifact and immutable receipt commits before item snapshot work begins | `_persist_page` then crash hook then `_persist_items` |
| Cursor resume | a stored `(operation, resource, request_cursor)` page is read from artifact storage; the provider cursor is not fetched again | real-DB crash/restart test |
| Item idempotency | immutable `(provider_item_id, item_sha256)` snapshots and page edges cannot duplicate cost or logical items | D1 constraints plus real-DB replay test |
| Final reconciliation | final poll is still idle; request fingerprint/external id/query/count/entity/criteria/enrichment identity match independent of array order; search/enrichments are completed; typed integral `found` equals pagination; every item is target search-sourced and has exactly one evaluation/result per requested identity | `_reconcile`, D2 request matcher, adversarial matrix |
| Typed drift failure | breaking provider/schema/reconciliation drift retains raw body and moves operation/batch to `failed_retryable`; it cannot succeed or materialize | real-DB drift test |
| Cancellation | canceled search becomes `cancelled` / `cancelled_unsealed`; no item retrieval or seal path runs | real-DB cancellation test |
| Cost exactly once | all-criteria matches, ordinary enrichment rows, and actual returned email/phone values are counted separately under the public rules; attributed cents use the pinned plan valuation; terminal replay performs zero calls and writes zero second cost | final receipt and real-DB replay test |
| Multi-search barrier | one successful operation cannot advance a batch while another planned operation is absent or non-terminal | `reconcile_discovery_batch_state`; two-search real-DB test |
| D4 boundary | terminal D3 items remain `raw`; candidate and claim counts remain zero; batch stops at `identity_resolution` | real-DB success test |
| Runtime reachability | webhook route is mounted only with HMAC secret; poll loop is default-off, requires API key when enabled, and runs beside the fleet worker | production wiring tests |
| Live provider | real search-only and enriched Websets reach idle, their pages reconcile, terminal cost persists, and terminal replay makes zero provider calls | **CLOSED for both bounded workloads** |

## 2. Provider boundary

`clue_research.adapters.exa_websets` now pins:

- `GET /websets/{id}` for one-attempt authoritative lifecycle polls;
- `GET /websets/{id}/items?cursor=&limit<=100`;
- `GET /events?cursor=&limit<=200`;
- the current required search progress, exclude/scope/recall/cancellation fields;
- nullable item `enrichments`, typed criterion evaluations, enrichment status/format/result,
  references and reasoning;
- full item/search/Webset event resources rather than id-only event stubs;
- current company properties, including headquarters and financials, while raw-preserving but not
  projecting `foundedYear` or `webTraffic`;
- typed team webhook create/list contracts and all 19 documented event values;
- typed item/event page envelopes with strict cursor/`hasMore` coherence; and
- the documented signature header containing `t` and one or more `v1` values.

The D2 `get_webset` lookup retains its bounded internal retry because it resolves an uncertain
create. D3 `poll_webset`, `list_items`, and `list_events` each make exactly one attempt. This keeps
every D3 retry time and outcome in PostgreSQL rather than hiding sleep/retry inside the SDK.

Official references:

- <https://exa.ai/docs/websets/api/webhooks/verifying-signatures>
- <https://exa.ai/docs/websets/api/websets/get-a-webset>
- <https://exa.ai/docs/websets/api/websets/items/list-all-items-for-a-webset>
- <https://exa.ai/docs/websets/api/events/list-all-events>

## 3. Durable state and transaction boundaries

The D1 tables remain provider-neutral. Review hardening added migration `fe7d6c0aee8a` for
`cost_cents_reserved` on operation and batch; no Exa-specific lifecycle table was introduced. D3
uses the substrate as follows:

1. D2 stores request/submit receipt and, in the same transaction as the successful operation
   update, enqueues the stable initial poll wake.
2. A webhook verifies exact bytes and parses the full event before persistence. Its `websetId`
   resolves the durable operation without a caller-supplied workspace. Unrelated team events are
   acknowledged without a tenant artifact. A matched event is stored under the resolved workspace,
   records one event and one event-keyed wake, and never treats `webset.idle` as completion.
3. A wake worker claims a wake and the lifecycle separately claims the operation reconciliation
   lease. Failure between those steps is recoverable through stale wake/operation leases.
4. Every fetched page is stored in one committed transaction. Item artifacts, snapshots, and
   page edges are written only afterward in another transaction.
5. Restart begins at the first cursor. Existing page receipts load their immutable artifact rather
   than making another HTTP call. A different payload for the same cursor is a replay conflict.
6. After pagination, a second authoritative Webset poll must still be idle. Reconciliation reads
   all durable pages/items/events, not the transient response alone.
7. One transaction stores raw/final manifests, settles credits and attributed cents, marks final
   reconciliation and pagination timestamps, terminalizes the operation, folds batch costs, and
   advances only when the planned operation count exists and every operation is terminal.

Two D1 corrections are part of this slice: seal readiness now requires signature verification on
stored webhook events, and page-item edge counts apply only to item pages (search/enrichment/event
pages do not have item edges). Neither weakens the fourteen-condition seal; both make it reflect
the intended resource model.

## 4. Event-feed tenancy rule

Exa's event-list endpoint is team-level and may return events for Websets belonging to other
workspaces. D3 therefore does **not** persist a foreign event page into a tenant artifact. It
filters the page to the target durable provider operation and stores that tenant-safe page plus
the SHA-256 of the upstream page. Webhook bodies and item/Webset pages remain byte-for-byte raw.
This is an intentional data-locality boundary, not silent loss: the cursor chain and upstream hash
remain durable, while unrelated workspace content never enters the artifact.

## 5. Cost settlement honesty

The final receipt uses policy
`exa-websets-public-credit-policy-2026-08-03+pro-usd-allocation`:

```text
10 credits × item where every requested criterion is yes
+ 2 credits × each ordinary enrichment row, including terminal null
+ 5 credits × each actual returned email/phone value
+ 2 credits × each resolved import (imports are forbidden in this search-only slice)
```

The adversarial fixture has one `yes`, one `unclear`, and one `no` row; three URL rows; and three
actual contact values. Its exact settlement is `10 + 6 + 15 = 31`, not the old 66-credit maximum.
The live one-row characterization produced three `yes` evaluations, two ordinary values, a
completed null email, and one phone: `10 + 4 + 0 + 5 = 19` credits.

The operation refuses settlement above its pre-submit reservation. `provider_units_charged` is a
deterministic application of Exa's public rules to terminal provider facts, with the full breakdown
in the final receipt. `cost_cents_charged` is explicitly a Pro subscription-allocation equivalent
at 0.449 cents/credit, not external card telemetry.

## 6. Production composition

- HTTP: one `POST /v1/webhooks/exa-websets` route is mounted only when
  `CLUE_EXA_WEBSETS_WEBHOOK_SECRET` exists. Workspace and operation never come from the URL.
- Provisioning: `ExaTeamWebhookProvisioner` lists the team subscriptions, identifies the managed
  endpoint by metadata, creates it only when absent, returns the one-time secret as `SecretStr`,
  and refuses silent URL/event changes or duplicate managed endpoints.
- Poll worker: `CLUE_EXA_WEBSETS_LIFECYCLE_ENABLED=false` by default. Enabling it without
  `CLUE_EXA_API_KEY` fails startup. The worker cadence is
  `CLUE_EXA_WEBSETS_POLL_WORKER_INTERVAL_S`.
- Auth: the API key and HMAC secret are separate credentials. The same Exa API key remains the
  provider key for Search/Websets; the HMAC secret authenticates webhook payloads and is not sent
  to Exa API endpoints.
- Observability: provider calls and lifecycle spans carry ids/counts/outcomes, never query bodies,
  response bodies, signatures, or credential values.

## 7. Mechanical verification

Executed against the configured local PostgreSQL database and filesystem storage:

```text
CLUE_DATABASE_URL=.../clue_discovery_fixture pytest -q \
  tests/durable/test_discovery_batch_d1.py \
  tests/api/test_exa_websets_submit_d2.py \
  tests/api/test_exa_websets_lifecycle_d3.py
passed; one unrelated opt-in D1 case skipped
```

The database matrix covers signed duplicate/out-of-order events; tenant-safe unrelated events;
invalid signatures; missed-webhook recovery; cursor exhaustion; current company financial/HQ raw
survival; exact 31-unit settlement; zero-call replay; committed-page/process-death resume;
rate-limit delay; cancellation; stale wake reclaim; the two-search completion barrier; monetary
pre-spend rejection; and fail-closed mutations for foreign/imported/wrong-entity items, missing or
duplicate criteria/enrichments, invalid statuses/formats/contact values, found/completion mismatch,
imports, and logical-field drift.

Static checks include `ruff`, full `mypy` over 467 source files, and 24/24 import contracts. A clean
disposable database passed Alembic `head -> base -> head`; it was then removed.

## 8. Live gate and D4 handoff

The live two-row search-only Webset `webset_01kz2b6wcyb25pzt3c83s7vhs2` reached idle through the
durable lifecycle. It produced two search-sourced company items, every criterion was `yes`, the
operation settled 20/20 credits and 8.980/8.980 attributed cents, the batch advanced to
`identity_resolution`, terminal D3 replay made zero poll/item/event calls, and replay-only D2 made
zero create/lookup calls. This closes the core live D3 gate.

A separately bounded one-row enriched operation
`webset_01kz2bbfchtsxxqn8segpd6nkx` closed the additional URL, revenue, email, and phone gate. While
Exa was running, the durable operation remained `waiting_external`, persisted no item, and settled
zero. At idle it produced one search-sourced company item with three `yes` evaluations; completed
URL, number, email, and phone results; and two contact values. The number result was terminal null,
which was preserved with its reasoning/references and still incurred the documented ordinary-row
charge. Exact settlement was:

```text
operation_id:             49f594bf-2714-421a-9fd4-0e3ee4e1e972
provider_operation_id:    webset_01kz2bbfchtsxxqn8segpd6nkx
units reserved/realized:  24 / 24
cost reserved/realized:   10.776 / 10.776 cents allocation-equivalent
breakdown:                10 search + 4 ordinary + 10 contact
operation/batch state:    succeeded / identity_resolution
```

Terminal replay returned the same item and settlement with zero poll/item/event calls. No second
Webset was created during lifecycle testing.

D4 may consume only the terminal raw item snapshots. It owns normalization, identity resolution,
candidate admission/exclusion, typed claims, and required-field dispositions. D3 exposes none of
those writes and cannot advance the project to scoring.
