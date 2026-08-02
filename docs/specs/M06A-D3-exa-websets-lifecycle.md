# M6A D3 — Exa Websets asynchronous retrieval lifecycle

Status: **mechanical implementation complete; live-provider acceptance gate OPEN because the
configured Exa team has no Websets API entitlement**

Parent plan: `docs/specs/M06A-exa-websets-sumble-discovery-integration.md`

Predecessors: `docs/specs/M06A-D0-contract-freeze.md`,
`docs/specs/M06A-D1-durable-discovery-batch.md`, and
`docs/specs/M06A-D2-exa-websets-paid-submit.md`

Scope: signed webhook ingestion, initial and scheduled poll wakes, single-driver reconciliation,
cursor pagination, immutable page/item snapshots, final request/result reconciliation, modeled
credit settlement, restart/crash recovery, and production HTTP/fleet composition

Out of scope: account identity admission, item normalization, candidate creation, claims,
field-resolution decisions, batch seal, project advance to scoring, Sumble, or general Exa Search

## 1. Acceptance contract

D3 passes mechanically only when all rows below are true. The live row remains separately open.

| Requirement | Pass condition | Implementation/evidence |
|---|---|---|
| Webhook authenticity | raw bytes verify against `HMAC-SHA256(timestamp + "." + raw_body)`; timestamp is within 300 seconds; any `v1` may match in constant time | `verify_exa_webhook_signature`; adapter tests |
| Raw webhook durability | a verified body is content-addressed before schema interpretation; malformed verified bodies are still retained | `ExaWebhookIngestor.ingest` |
| Event idempotency/order | unique `(workspace, operation, provider_event_id)`; duplicate content returns duplicate; changed content fails; delivery order has no authority | `record_discovery_event`; real-DB duplicate/out-of-order test |
| Webhook authority | webhook only appends event + wake; it cannot mark idle, reconcile, settle, materialize, or advance | ingestor test proves operation remains provider-running |
| Initial poll | every successful/reconciled D2 submit creates one transactional `exa-initial-poll:<operation>` wake | `DurableExaWebsetSubmitter._persist_success`; D2 replay test |
| Scheduled polling | fleet worker claims only `exa_websets` wakes; connection/408/425/429/5xx retries are visible as durable waits and honor capped `Retry-After` | `ExaDiscoveryWakeWorker`; lifecycle rate-limit test |
| Single driver | operation atomically enters `reconciling` with a two-minute lease; another worker joins; an expired lease is reclaimable | `claim_discovery_operation_reconciliation` |
| Wake crash recovery | a claimed-but-unprocessed wake becomes reclaimable after its lease, never before | `claim_due_discovery_wakes`; real-DB stale-lease test |
| Page-before-process | each provider page artifact and immutable receipt commits before item snapshot work begins | `_persist_page` then crash hook then `_persist_items` |
| Cursor resume | a stored `(operation, resource, request_cursor)` page is read from artifact storage; the provider cursor is not fetched again | real-DB crash/restart test |
| Item idempotency | immutable `(provider_item_id, item_sha256)` snapshots and page edges cannot duplicate cost or logical items | D1 constraints plus real-DB replay test |
| Final reconciliation | final poll is still idle; request fingerprint/external id/query/count/entity/criteria/enrichment shape match; search/enrichments completed; found count equals pagination; all item enrichment ids and webhook/event item ids exist | `_reconcile` and D2 request matcher |
| Typed drift failure | breaking provider/schema/reconciliation drift retains raw body and moves operation/batch to `failed_retryable`; it cannot succeed or materialize | real-DB drift test |
| Cancellation | canceled search becomes `cancelled` / `cancelled_unsealed`; no item retrieval or seal path runs | real-DB cancellation test |
| Cost exactly once | final operation units are the versioned public formula times durable unique returned rows, bounded by reservation; terminal replay performs zero calls and writes zero second cost | final receipt and real-DB replay test |
| D4 boundary | terminal D3 items remain `raw`; candidate and claim counts remain zero; batch stops at `identity_resolution` | real-DB success test |
| Runtime reachability | webhook route is mounted only with HMAC secret; poll loop is default-off, requires API key when enabled, and runs beside the fleet worker | production wiring tests |
| Live provider | the real D2 Webset reaches idle and its real pages/billing evidence reconcile | **OPEN — Websets API entitlement required** |

## 2. Provider boundary

`clue_research.adapters.exa_websets` now pins:

- `GET /websets/{id}` for one-attempt authoritative lifecycle polls;
- `GET /websets/{id}/items?cursor=&limit<=100`;
- `GET /events?cursor=&limit<=200`;
- typed Webset item and event identities plus additive-field preservation;
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

No migration was needed. D1 already supplied operation, event, page, item, page-item, wake, cost,
and reconciliation columns. D3 uses them as follows:

1. D2 stores request/submit receipt and, in the same transaction as the successful operation
   update, enqueues the stable initial poll wake.
2. A webhook verifies exact bytes, durably stores them, then records one event and one event-keyed
   wake transactionally. It never interprets `webset.idle` as completion.
3. A wake worker claims a wake and the lifecycle separately claims the operation reconciliation
   lease. Failure between those steps is recoverable through stale wake/operation leases.
4. Every fetched page is stored in one committed transaction. Item artifacts, snapshots, and
   page edges are written only afterward in another transaction.
5. Restart begins at the first cursor. Existing page receipts load their immutable artifact rather
   than making another HTTP call. A different payload for the same cursor is a replay conflict.
6. After pagination, a second authoritative Webset poll must still be idle. Reconciliation reads
   all durable pages/items/events, not the transient response alone.
7. One transaction stores raw/final manifests, settles cost, marks final reconciliation and
   pagination timestamps, terminalizes the operation, folds batch costs, and moves the batch only
   to `identity_resolution`.

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

The final receipt uses policy `exa-websets-public-credit-policy-2026-08-02`:

```text
per returned row = 10 base + 2 per ordinary enrichment + 5 per email/phone enrichment
realized modeled units = per-row units × durable unique item count
```

The operation refuses settlement above its pre-submit reservation. The fixture requests three
rows with LinkedIn URL, email, and phone enrichments: `(10 + 2 + 5 + 5) × 3 = 66` units. Replay
returns the same terminal operation without provider traffic or a second settlement.

This is explicitly **modeled from the public formula and durable provider output**, not verified
account-billing telemetry. The live gate must compare this result with Exa's available operation or
account usage evidence. Until then, D3 does not claim that an external account was actually debited
66 credits.

## 6. Production composition

- HTTP: `POST /v1/webhooks/exa-websets/{workspace_id}/{operation_id}` is mounted in the production
  projections app only when `CLUE_EXA_WEBSETS_WEBHOOK_SECRET` exists.
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
tests/api/test_exa_websets_lifecycle_d3.py
7 passed

D0-D3 + production app/fleet regression selection
59 passed, 1 expected D1 integration skip
```

The seven database cases cover signed duplicate/out-of-order events; invalid endpoint signature;
missed webhook recovery; two item cursors; terminal event page; raw item preservation; zero D4
candidates; 66-unit one-time settlement; terminal zero-call replay; committed-page/process-death
resume without first-page refetch; rate-limit delay; breaking schema drift with raw body; provider
cancellation; and stale wake reclaim. The combined selection includes D0 fixtures, D2 adapter and
real-DB submit/replay, D3 adapter/lifecycle/wiring, the projections app, and fleet wiring.

Static checks (`ruff`, `mypy`) cover every changed Python surface. The full repository check is
recorded in the D3 session note. Its default-environment run reached three unrelated existing
failures: one sandbox-blocked localhost compliance test, the known memory-boundary import, and a
pre-existing secret-shape fixture literal. No D0-D3 test failed.

## 8. Live gate and D4 handoff

Because the Exa team cannot currently create a Webset through the API, D3's code/mechanical
boundary is complete but Gate D3 remains open. Once an entitled account exists, the bounded live
acceptance must reuse a successful D2 operation and prove: real idle, real item/event cursor
exhaustion, raw artifacts, final reconciliation, billing comparison, process restart, and zero
duplicate call/cost. No new logic should be added merely to make that canary pass.

D4 may consume only the terminal raw item snapshots. It owns normalization, identity resolution,
candidate admission/exclusion, typed claims, and required-field dispositions. D3 exposes none of
those writes and cannot advance the project to scoring.
