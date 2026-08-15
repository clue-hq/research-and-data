# FI Stage-0 durable official-site crawl — C8 progress and operations contract

**Status:** implemented 2026-08-14

**Parent plan:** [FI-stage0-durable-official-site-crawl-plan.md](./FI-stage0-durable-official-site-crawl-plan.md)

**Runtime schema:** `stage0-official-site-c8-v1`

## 1. Slice boundary

C8 makes the C1–C7 crawl observable and recoverable without creating a second lifecycle model.
PostgreSQL crawl, attempt, snapshot, checkpoint, extraction, and run-event rows remain authoritative.
Events and logs are visibility aids; elapsed UI time is never evidence that work advanced.

C8 does not:

- change C7 extraction/claim semantics or provider spend behavior;
- expose page bodies, query-bearing URLs, raw provider receipts, tokens, cookies, email addresses,
  or Clerk subjects;
- perform automatic retry after an ambiguous paid call;
- change the existing setup release gate. C10 owns the live browser/cutover acceptance;
- add a public mutation endpoint. Recovery is an explicit operator CLI over workspace-scoped,
  generation-fenced repository operations.

No migration is required. C8 deliberately reuses the existing official-site ledger and the
`run_event` outbox.

## 2. Durable event contract

The lifecycle/coordinator emit the following `run.step.progress` events through one
`CrawlProgressSink`:

| Event | Emission authority |
|---|---|
| `stage0.crawl.started` | crawl run creation |
| `stage0.crawl.discovery_completed` | initial root/sitemap discovery commit |
| `stage0.crawl.page_started` | successful PostgreSQL page claim |
| `stage0.crawl.page_fetched` | committed page snapshot and fetched-page transition |
| `stage0.crawl.page_refused` | committed robots/policy refusal |
| `stage0.crawl.fast_checkpoint_frozen` | immutable fast checkpoint commit |
| `stage0.crawl.extraction_started` | materialization invocation for a checkpoint |
| `stage0.crawl.extraction_completed` | terminal per-field materialization partition |
| `stage0.crawl.background_started` | run transition to background-active |
| `stage0.crawl.background_completed` | committed background checkpoint and completed run |
| `stage0.crawl.failed` | an unexpected fleet handler failure after a crawl row exists |

Events are at-least-once. `event_id` is a stable UUID5 over schema version, crawl run, event kind,
and a stable subject such as page generation, snapshot, or checkpoint. `run_event.seq` provides
ordering. Readers deduplicate by `event_id` and retain the greatest sequence, so replayed event
writes cannot inflate semantic progress.

Event payloads use explicit fields only (`extra='forbid'`). Page events contain a fetch-key SHA-256,
host, page/snapshot IDs, provider key, graph depth, lease generation, bounded provider/request
labels, HTTP/retry/spend state, duration, bytes, cost, artifact key, and outcome; they do not contain
the discovered/requested URL or content. Free-form provider identifiers/statuses are replaced by a
SHA-256 label before they reach the event/log contract. Visibility emission is best effort: an
event failure cannot fail, cancel, or repeat acquisition/materialization.

## 3. Rows-first progress reduction

`PostgresOfficialSiteOperations` is workspace-scoped and calculates progress at read time from:

- `official_site_crawl_run` for phase and terminal state;
- `official_site_crawl_page` for queued, leased, provider-active, reconciliation,
  persistence, retry, fetched, refused, failed, and quarantined counts;
- `official_site_fetch_attempt` for active `spend_unknown` and recorded cost;
- `official_site_page_snapshot` for URL-level snapshots and distinct content blobs;
- `official_site_link_expansion` for queued, leased, retry-wait, completed, and failed recursive
  discovery work after page publication;
- `official_site_extraction_operation` for prepared, active, materialized, empty, failed, and
  extraction-spend-unknown counts;
- `official_site_corpus_checkpoint` for committed corpus checkpoints;
- reduced crawl `run_event` rows for the latest user-visible transition.

Malformed or foreign progress events are ignored; they never invalidate the row projection.
Completed/quarantined ambiguity is not counted as active spend-unknown. Duplicate content retains
every URL-level snapshot while the unique-blob counter deduplicates extraction storage.

The operator state vocabulary is a non-exclusive set:

| State | Durable meaning |
|---|---|
| `queued` | discovered/queued or retry-wait pages remain |
| `leased` | a worker owns an un-dispatched claim |
| `provider-active` | a dispatch has started under an active lease |
| `spend-unknown` | a fetch or extraction outcome is financially ambiguous |
| `persisted` | at least one URL snapshot exists |
| `extracted` | at least one extraction operation exists |
| `partial` | useful persisted/extracted output exists alongside an explicit gap/failure |
| `completed` | the crawl run committed its completed transition |

The message is selected from those durable states. It never advances by timer.

## 4. Additive setup contract

`GET /stage0/setup/current` retains every existing field and adds nullable `official_site`.
No crawl row (or a pre-C8 server) is represented as `null`; the endpoint does not invent zero
progress. When present, the object contains body-free counts, states, the latest reduced event,
and `recovery_required`/`partial`/`completed` booleans.

The frontend Zod contract treats this field as optional+nullable with a `null` default, tolerates
future object fields and open status vocabularies, and still validates all known counters and
booleans. Both the HTTP repository and the fixture repository pass through the same schema. The
fixture walkthrough's release behavior is intentionally unchanged until C10.

## 5. Metrics and structured logs

The read projection emits the §17.4 matrix: frontier ready/leased/quarantined; DB-derived average
claim latency and generation/attempt contention; page/snapshot/unique-blob counts and duplicate
content ratio; current provider/hashed-host concurrency; provider latency, retry outcome, and cost;
active spend-unknown count and oldest age; fast-checkpoint latency and fixed-vocabulary category
coverage; extraction materialized/empty/failed/spend-unknown outcomes; background completion
latency; and recovery-item count. A coordinator fencing rejection increments the stale-completion
counter. Event emission increments a counter by event kind, phase, and provider. Workspace/run IDs
are intentionally not metric labels.

Structured event and recovery logs may contain workspace/recon/crawl/page/snapshot/checkpoint IDs,
event sequence, provider key, fetch-key hash, host, lease generation, aggregate counts, and bounded
outcome. They must never contain authorization material, user identity, full URLs, raw response
bodies, raw extraction output, or full receipts. Operator inspection output declares these privacy
properties and contains only row counts and bounded metadata.

## 6. Recovery contract

The operator command is `scripts/18_official_site_c8_operator.py`. Every invocation requires an
explicit async PostgreSQL URL, workspace ID, and crawl-run ID.

- `inspect` is read-only and returns the progress projection plus body-free recovery targets.
- `reclaim-expired` calls the C1 DB-time reclaim primitive. It requires an exact repeated crawl-run
  confirmation. Pre-dispatch leases return to the frontier; dispatched ambiguity moves to
  reconciliation; retained provider success moves to persistence-only recovery.
- `quarantine-spend-unknown` requires an exact attempt confirmation and expected lease generation.
  It can update only an unleased `reconciliation_pending` page paired with an active
  `spend_unknown` attempt. It performs no provider call. A stale generation, wrong workspace/run,
  active lease, or already-settled attempt changes zero rows.

Extraction `spend_unknown` is also returned as a body-free recovery item containing the extraction
operation, category, field key, sanitized model/failure labels, and age. C7 intentionally makes
that state terminal because a failed gateway call may already have incurred spend and there is no
provider-operation lookup contract at the model gateway seam. Its permitted action is therefore
manual billing/incident review with **no automatic retry**; successful sibling fields remain
materialized. C8 does not invent a retry or mutable acknowledgement state.

Provider receipt lookup/reconciliation remains C4/C5 worker behavior. The operator never blindly
resubmits an ambiguous paid request. A missing provider lookup capability leads to quarantine, not
new spend.

## 7. Verification checkpoints

C8 is complete only when all of the following remain green:

1. Stable event identities reduce duplicate deliveries once and use the latest sequence.
2. Event models reject URL/body/receipt escape-hatch fields.
3. Lifecycle and coordinator tests prove transitions emit events from actual work.
4. Dedicated PostgreSQL tests prove rows/events combine correctly, tenancy fails closed, DB-time
   expiry works, generation-fenced quarantine is replay-safe, and operator output is body-free.
5. Setup backend tests preserve old response behavior; frontend fixture and live HTTP transports
   parse the additive object through the same schema.
6. C0–C8 official-site and setup regressions pass on a fresh isolated migrated database.
7. Read-only inspection of retained C7 evidence derives truthful progress even though that run
   predates C8 event emission, proving rows are the authority.

Recorded 2026-08-14 evidence:

- fresh isolated database `clue_c8_official_site_20260814_v2` upgraded to the sole head
  `a57463ec42ea`;
- 164 C0–C8 official-site/wiring/setup tests passed on that clean database;
- repository-wide Ruff, mypy (658 source files), and 25 import contracts passed;
- all 228 frontend tests, ESLint, design-token build, TypeScript, and Next.js production build
  passed;
- read-only inspection of the retained Insight Health C7 run reconstructed 16 pages, 15 fetched
  snapshots, 14 unique blobs, two checkpoints, 19 materialized extraction operations, two failed
  operations, one extraction spend-unknown, explicit partial+completed state, and the exact
  body-free ambiguity item from rows while `event_count=0`. No provider call or retained-row
  mutation occurred.

The local/production procedure and state-by-state decision tree are in
[the official-site crawl runbook](../runbooks/stage0-official-site-crawl.md).
