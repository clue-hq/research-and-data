# Stage-0 durable official-site crawling — C0 contract freeze

**Status:** C0–C4 implemented and verified; C5 is next

**Parent:** [durable official-site crawl implementation plan](./FI-stage0-durable-official-site-crawl-plan.md)

**Executable authority:** `clue_research.official_site` plus
`tests/fixtures/official_site/c0_contract_fixture.json`

---

## 1. C0 outcome

C0 freezes the shape that C1–C10 implement. It deliberately performs no database migration,
network acquisition, provider call, artifact write, or production cutover.

The frozen boundary is:

```text
Stage-0 setup/recon
    -> CrawlRepository.create_or_get_run
    -> PostgreSQL frontier/ledger (C1)
    -> coordinator claims one URL (C5)
    -> PageFetcher.fetch_one (C3)
    -> artifact + URL snapshot (C4)
    -> immutable fast/background corpus checkpoint (C6)
    -> OfficialSiteCorpusMaterializer.materialize (C7)
    -> append-only client.* claims with source_key=official_site
```

Firecrawl and Scrapling never appear in the coordinator or materializer contracts. Each adapter
must declare `single_page_only=true`, lookup/idempotency/redirect/link/cost/receipt/no-spend
capabilities, and implement exactly `fetch_one(PageFetchRequest)`.

## 2. Frozen names and versions

| Item | Frozen value |
|---|---|
| Contract version | `stage0-official-site-c0-v1` |
| Logical tier-2 claim source | `official_site` |
| Historical source keys | `firecrawl_site`, `scrapling_site` |
| Maximum link-graph depth | exactly `2` in V1 |
| Fast hard deadline ceiling | 40 seconds |
| Scheduling authority | PostgreSQL only |
| Provider operation | one page per request |
| Fast/background ownership | phases/checkpoints of one crawl run |

The eight table names are:

1. `official_site_crawl_run`
2. `official_site_crawl_page`
3. `official_site_url_observation`
4. `official_site_link_edge`
5. `official_site_fetch_attempt`
6. `official_site_page_snapshot`
7. `official_site_alias_observation`
8. `official_site_corpus_checkpoint`

The executable enums and transition graphs are pinned in the fixture. Adding, removing, or
renaming a state requires a contract-version change, fixture review, and a parent-plan delta.

## 3. Frozen data definition for C1

C1 uses one random-hash Alembic migration, hand-written and reversible. SQL enum types are not
created; constrained `text` columns mirror the Python `StrEnum`s, following the repository's
existing migration style. All timestamps default to database `now()` and all lease/deadline
comparisons use database time.

### 3.1 `official_site_crawl_run`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
brand_id text NOT NULL
client_entity_id uuid
recon_run_id uuid NOT NULL
root_discovered_url text NOT NULL
root_fetch_key text NOT NULL
allowed_registrable_domain text NOT NULL
status text NOT NULL DEFAULT 'queued'
max_graph_depth smallint NOT NULL DEFAULT 2
fast_claim_deadline_at timestamptz NOT NULL
overall_page_ceiling integer NOT NULL
fast_page_ceiling integer NOT NULL
provider_policy_version text NOT NULL
url_policy_version text NOT NULL
robots_policy_version text NOT NULL
config_json jsonb NOT NULL
failure_code text
created_at timestamptz NOT NULL DEFAULT now()
updated_at timestamptz NOT NULL DEFAULT now()
completed_at timestamptz
failed_at timestamptz
cancelled_at timestamptz
```

Constraints:

- primary key `official_site_crawl_run_pkey`;
- unique anchor `(id, workspace_id)`;
- unique `(workspace_id, recon_run_id)`—one official-site crawl per recon;
- composite FK `(brand_id, workspace_id) -> brand(brand_id, workspace_id)`;
- composite FK `(client_entity_id, workspace_id) -> account_entity(id, workspace_id)`;
- C1 adds `recon_run_scope_anchor UNIQUE (id, workspace_id)` if absent, then uses composite FK
  `(recon_run_id, workspace_id) -> recon_run(id, workspace_id)`;
- status CHECK equals the frozen `CrawlRunStatus` values;
- `max_graph_depth = 2`;
- positive overall/fast ceilings and `fast_page_ceiling <= overall_page_ceiling`;
- `config_json` is an object;
- exactly the matching terminal timestamp is required for `completed|failed|cancelled`; nonterminal
  states have no terminal timestamp.

Indexes:

- `(status, fast_claim_deadline_at, created_at, id)` for run scheduling;
- `(workspace_id, created_at DESC)` for tenant reads;
- `(allowed_registrable_domain, status)` for host operations.

### 3.2 `official_site_crawl_page`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
crawl_run_id uuid NOT NULL
fetch_key text NOT NULL
fetch_key_hash text NOT NULL
representative_requested_url text NOT NULL
host text NOT NULL
graph_depth smallint
priority integer NOT NULL
priority_reason_json jsonb NOT NULL DEFAULT '[]'
eligibility text NOT NULL
state text NOT NULL DEFAULT 'discovered'
lease_owner text
lease_generation bigint NOT NULL DEFAULT 0
lease_acquired_at timestamptz
lease_expires_at timestamptz
attempt_count integer NOT NULL DEFAULT 0
expanded_min_depth smallint
next_attempt_at timestamptz
latest_snapshot_id uuid
terminal_reason text
discovered_at timestamptz NOT NULL DEFAULT now()
queued_at timestamptz
fetched_at timestamptz
updated_at timestamptz NOT NULL DEFAULT now()
```

Constraints:

- unique anchor `(id, workspace_id)`;
- run-local child anchor `(id, crawl_run_id, workspace_id)`;
- composite FK `(crawl_run_id, workspace_id) -> official_site_crawl_run(id, workspace_id)`;
- unique `(crawl_run_id, fetch_key_hash, fetch_key)`; the hash alone is never identity;
- `fetch_key_hash` is 64 lowercase hexadecimal characters;
- `graph_depth`/`expanded_min_depth` are NULL or `0..2`;
- non-negative priority, generation, and attempt count;
- eligibility/state CHECKs equal the frozen enums;
- `leased|provider_started` require all lease fields;
  `reconciliation_pending|persistence_pending` may carry either all lease fields (actively claimed
  by the matching recovery worker) or none (waiting for recovery); every other state carries none;
- terminal state/timestamp/reason coherence;
- `latest_snapshot_id` receives its composite FK after the snapshot table is created.

Indexes:

- claim order `(crawl_run_id, state, eligibility, priority, graph_depth, discovered_at, id)` with a
  partial predicate on claimable states;
- global/host capacity `(host, state, lease_expires_at)`;
- reclaim `(state, lease_expires_at)` for leased/provider-active rows;
- `(workspace_id, crawl_run_id, state)` for progress.

### 3.3 `official_site_url_observation`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
crawl_run_id uuid NOT NULL
page_id uuid
parser_replay_key text NOT NULL
discovered_url text NOT NULL
discovered_via text NOT NULL
source_page_id uuid
graph_depth smallint
link_text_bounded text
sitemap_url text
observed_at timestamptz NOT NULL DEFAULT now()
policy_outcome text NOT NULL
policy_reason text
```

Constraints:

- composite run FK plus page/source-page FKs on `(page_id, crawl_run_id, workspace_id)` preserve
  both workspace and run locality;
- unique `(crawl_run_id, parser_replay_key)` prevents parser replay duplication without collapsing
  separate provenance observations;
- origin/policy CHECKs equal the frozen enums;
- sitemap observations require `graph_depth IS NULL`;
- `link_text_bounded` is at most 500 characters;
- admitted observations require `page_id`; refused observations do not require one.

Indexes: `(crawl_run_id, page_id, observed_at)` and `(crawl_run_id, discovered_via)`.

### 3.4 `official_site_link_edge`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
crawl_run_id uuid NOT NULL
from_page_id uuid NOT NULL
to_page_id uuid NOT NULL
discovered_url text NOT NULL
link_relation text NOT NULL
observed_at timestamptz NOT NULL DEFAULT now()
```

Constraints:

- composite run FK plus from/to page FKs on `(page_id, crawl_run_id, workspace_id)` preserve
  workspace and run locality;
- relation CHECK equals `LinkRelation`;
- unique `(crawl_run_id, from_page_id, to_page_id, discovered_url, link_relation)`.

Indexes: `(crawl_run_id, from_page_id)` and `(crawl_run_id, to_page_id)`.

### 3.5 `official_site_fetch_attempt`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
crawl_run_id uuid NOT NULL
page_id uuid NOT NULL
attempt_number integer NOT NULL
lease_generation bigint NOT NULL
worker_id text NOT NULL
operation_key text NOT NULL
provider_key text NOT NULL
state text NOT NULL DEFAULT 'prepared'
provider_request_id text
provider_receipt_json jsonb
requested_url text NOT NULL
final_url text
redirect_chain_json jsonb NOT NULL DEFAULT '[]'
provider_status text
http_status integer
media_type text
size_bytes bigint
cost_cents numeric
cost_kind text NOT NULL DEFAULT 'none'
spend_status text NOT NULL DEFAULT 'no_spend'
retry_class text
artifact_key text
content_sha256 text
started_at timestamptz NOT NULL DEFAULT now()
dispatched_at timestamptz
provider_completed_at timestamptz
persisted_at timestamptz
finished_at timestamptz
```

Constraints:

- unique anchor `(id, workspace_id)`;
- snapshot-reference anchor `(id, crawl_run_id, page_id, workspace_id)`;
- composite run FK and page FK `(page_id, crawl_run_id, workspace_id)` plus composite artifact FK
  `(artifact_key, workspace_id) ->
  artifact(storage_key, workspace_id)`;
- unique `operation_key`; unique `(page_id, attempt_number)`;
- state/cost/spend/retry CHECKs equal frozen enums;
- positive attempt/generation, non-negative cost/size, SHA-256 shape, JSON object/array shapes;
- `prepared` has no dispatch timestamp; every post-dispatch state has one;
- `provider_succeeded|persisted|reconciled_succeeded` require provider completion metadata;
- `persisted` requires artifact key, hash, size, media type, and persisted timestamp;
- `spend_unknown` state requires `spend_status='spend_unknown'` and cannot transition directly to
  another dispatch;
- actual/estimated cost requires `cost_cents`; `cost_kind='none'` requires NULL cost.

Indexes:

- `(page_id, attempt_number DESC)`;
- `(state, dispatched_at)` for reconciliation;
- partial unique provider receipt `(provider_key, provider_request_id)` when request ID is present;
- `(workspace_id, spend_status, started_at)` for audit.

### 3.6 `official_site_page_snapshot`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
crawl_run_id uuid NOT NULL
page_id uuid NOT NULL
fetch_attempt_id uuid NOT NULL
requested_url text NOT NULL
final_url text NOT NULL
redirect_chain_json jsonb NOT NULL DEFAULT '[]'
fetched_at timestamptz NOT NULL
provider_key text NOT NULL
provider_request_id text
http_status integer
media_type text NOT NULL
artifact_key text NOT NULL
content_sha256 text NOT NULL
size_bytes bigint NOT NULL
robots_decision_ref text NOT NULL
policy_version text NOT NULL
created_at timestamptz NOT NULL DEFAULT now()
```

Constraints:

- unique anchor `(id, workspace_id)`;
- page-local anchor `(id, page_id, crawl_run_id, workspace_id)`;
- composite run/page FKs and an attempt FK on
  `(fetch_attempt_id, crawl_run_id, page_id, workspace_id)` plus composite artifact FK
  `(artifact_key, workspace_id) ->
  artifact(storage_key, workspace_id)`;
- unique `fetch_attempt_id`—one URL-level snapshot per successful attempt;
- hash/size/HTTP/JSON shape checks.

Indexes:

- `(crawl_run_id, page_id, fetched_at DESC)`;
- `(workspace_id, content_sha256)`—content reuse lookup without collapsing snapshots;
- `(artifact_key)` for DSAR/reference traversal.

After creation, C1 adds the page-owned circular FK
`(latest_snapshot_id, id, crawl_run_id, workspace_id) ->
official_site_page_snapshot(id, page_id, crawl_run_id, workspace_id)` to the page table.

### 3.7 `official_site_alias_observation`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
crawl_run_id uuid NOT NULL
source_page_id uuid NOT NULL
alias_url text NOT NULL
kind text NOT NULL
verification_status text NOT NULL DEFAULT 'observed'
target_page_id uuid
observed_at timestamptz NOT NULL DEFAULT now()
```

Constraints:

- composite run FK plus source/target page FKs on `(page_id, crawl_run_id, workspace_id)`;
- frozen kind/status CHECKs;
- unique `(crawl_run_id, source_page_id, alias_url, kind)`;
- cross-domain canonical hints use `rejected_external` and may not carry `target_page_id`.

Indexes: `(crawl_run_id, target_page_id)` and `(crawl_run_id, verification_status)`.

### 3.8 `official_site_corpus_checkpoint`

Columns:

```text
id uuid PRIMARY KEY
workspace_id text NOT NULL
crawl_run_id uuid NOT NULL
phase text NOT NULL
version integer NOT NULL
snapshot_ids_json jsonb NOT NULL
snapshot_set_sha256 text NOT NULL
coverage_json jsonb NOT NULL
created_at timestamptz NOT NULL DEFAULT now()
```

Constraints:

- unique anchor `(id, workspace_id)`;
- composite run FK;
- unique `(crawl_run_id, phase, version)`;
- positive version, SHA-256 shape, snapshot array and coverage object checks;
- `snapshot_ids_json` is a duplicate-free array of lowercase UUID strings in lexical order;
  `snapshot_set_sha256` is SHA-256 over its compact UTF-8 JSON (`["uuid",...]`, no whitespace);
- a `BEFORE INSERT` trigger rejects any snapshot ID that is absent, erased, or belongs to another
  workspace/run and recomputes that hash;
- an append-only trigger rejects UPDATE; later versions insert new rows.

Indexes: `(crawl_run_id, phase, version DESC)` and `(workspace_id, created_at DESC)`.

## 4. State-machine decisions

The executable transition manifest is authoritative. Consequential rulings are:

- Run: `queued -> fast_active -> fast_closing -> fast_complete -> background_active -> completed`.
  Fast may transition directly from `fast_complete` to `completed` only when no background work is
  eligible. Terminal run states do not reopen.
- Page: provider success enters `persistence_pending`; the page is not `fetched` until the durable
  snapshot commits. A proven no-spend transient enters `retry_wait`; only that state can requeue.
- Page: an expired or ambiguous dispatched attempt enters `reconciliation_pending` with its lease
  cleared. `claim_reconciliation` increments the page generation and leases that state without
  changing its semantic state; this claim can inspect/reuse the existing provider operation but
  cannot dispatch a new provider call.
- Page: a recorded provider success whose lease expires stays `persistence_pending` with its lease
  cleared. `claim_persistence` obtains a fresh generation and resumes artifact/snapshot persistence
  from recorded metadata; it cannot invoke `PageFetcher`.
- Attempt: `spend_unknown` may become `reconciled_no_spend`, `reconciled_succeeded`, or
  `quarantined`. It can never transition to `dispatched`.
- Reconciled success still must reach `persisted`; provider success is not artifact durability.
- The attempt retains its original dispatch generation. `ReconciliationClaim` pairs it with the
  new page lease, so repository predicates fence the current reconciler without rewriting history.
- `AttemptOutcome` admits only four coherent pairs: no-spend retry to
  `retryable_no_spend|reconciled_no_spend + retry_wait`, permanent failure to `failed + failed`,
  ambiguity to `spend_unknown + reconciliation_pending`, and quarantine to
  `quarantined + quarantined`. Only a no-spend retry carries `retry_at`.
- Expiry reclamation is deterministic and counted by `ReclaimResult`: a prepared/not-dispatched
  attempt is failed and its page requeued (`requeued_pre_dispatch`); a dispatched unresolved
  attempt becomes `spend_unknown + reconciliation_pending`
  (`moved_to_reconciliation_pending`); a recorded success keeps `persistence_pending` and only
  clears stale ownership (`released_persistence_pending`).
- Stale-generation writes update zero rows and do not create alternate state transitions.

## 5. `PageFetcher` contract decisions

`PageFetchResult` includes the provider key/request ID, requested/final URLs, redirect chain,
provider and HTTP status, exact bytes, MIME type, outgoing-link observations, fetch timestamp,
actual/estimated/none cost, spend status, retry classification, and a sanitized receipt.

There is deliberately no `retryable_charged` outcome. The only automatic retry classification is
`retryable_no_spend`. Once dispatch could have charged, an unresolved result is `ambiguous` plus
`spend_unknown`; recovery reconciles or quarantines it.

The PostgreSQL attempt state freezes the dispatch crash boundary; there is no second client-owned
dispatch clock or duplicate phase enum:

1. `begin_attempt` commits `prepared` plus the stable `operation_key` before external I/O;
2. `mark_attempt_dispatched` conditionally changes `prepared -> dispatched` and stamps
   `dispatched_at` with database time before `fetch_one` is invoked;
3. `record_provider_result` persists sanitized body-free result/receipt metadata after the provider
   returns;
4. a crash after step 2 is conservatively `spend_unknown` until operation lookup/idempotent reuse
   proves the outcome, or the attempt is quarantined.

Provider request ID/cost may therefore be absent after dispatch. Secrets, raw headers, cookies,
and raw provider payloads are outside the metadata contract.

`PageFetchResult.metadata()` produces the body-free `ProviderResultMetadata` accepted by the
attempt ledger. Page bytes and outgoing links pass only to artifact/snapshot persistence; the
attempt row never becomes an accidental page-content store.

The frozen repository exposes three different claim operations:

- `claim_next(ClaimNextRequest)`: leases ordinary queued acquisition work;
- `claim_reconciliation(ClaimReconciliationRequest)`: leases only
  `reconciliation_pending`/`spend_unknown` work and never authorizes `PageFetcher.fetch_one`.
- `claim_persistence(ClaimPersistenceRequest)`: leases only
  `persistence_pending` plus `provider_succeeded|reconciled_succeeded` work and resumes persistence
  from the recorded result without fetching again.

Both increment and return a page `lease_generation`; every subsequent state mutation carries that
generation and the workspace scope.

`ArtifactRef`, `PageSnapshotRef`, `CrawlLease`, `FetchAttemptRef`, `CrawlRunRef`,
`CorpusCheckpointRef`, and `CrawlProgress` carry explicit workspace scope. An official-site
artifact key must equal `<workspace_id>/<content_sha256>`; the C1 composite FKs make a public or
cross-workspace blob unrepresentable on this path.

## 6. Exact Stage-0 materialization seam

The crawler ends at `CorpusCheckpointRef`. C7 accepts
`OfficialSiteMaterializationRequest(workspace_id, crawl_run_id, recon_run_id, claim_run_id,
client_entity_id, checkpoint_id, phase, model_id, prompt_version, schema_version)`.

It returns references only:

```text
OfficialSiteMaterializationResult
  source_key = official_site
  client_kb_version
  claim_ids[]
  filled_fields[]
  empty_fields[]
  failed_fields[]
```

The three field groups must be disjoint. The materializer cannot fetch URLs and cannot cite a
snapshot outside the checkpoint. Existing claim construction, validation, source-tier, target-lock,
reuse-scope, evidence-span, and append-only rules remain authoritative.

## 7. Logical source-key migration

The decision is additive and non-rewriting:

1. C1 seeds `official_site` as a tier-2, account-scoped, Clue-owned logical source with zero
   per-field acquisition estimate. Provider cost is recorded on fetch attempts, not copied to each
   derived claim.
2. Historical `firecrawl_site` and `scrapling_site` manifests and claims remain immutable and
   queryable. They are not renamed or backfilled.
3. Shadow mode writes crawl/attempt/snapshot/checkpoint rows and comparison evidence, but does not
   publish `official_site` Client-KB claims or drive user release.
4. At authoritative cutover, new Stage-0 owned-surface claims use `official_site`. The historical
   field-level scrape resolvers are unbound for the new run path; no provider name appears in the
   Client-KB `tier_plan` authority.
5. Current-value/claim reads naturally consider old and new append-only claims under normal
   freshness/merge rules; no history rewrite is permitted.

## 8. Spike disposition

| Experimental change | C0 disposition | Reason/next owner |
|---|---|---|
| `firecrawl-py` dependency and lockfile | Retain | Required SDK boundary; C3 uses `scrape`, never provider crawl. |
| Existing Firecrawl adapter on SDK v4 | Retain after correction | Kept single-page via `client.scrape`; historical path remains accepted until cutover. |
| `asyncio.to_thread` around synchronous resolver leaves | Retain | General non-blocking prerequisite; provider-neutral and independently tested. |
| Self-serve startup source-registry seeding | Retain | Fixes onboarding-only composition independently of crawling. |
| Caller-transaction pre-spend-gate binding | Retain | Fixes uncommitted Stage-0 client visibility; independent governance prerequisite. |
| Privacy-safe lane failure logging | Retain | General diagnostic prerequisite; no crawl semantics. |
| Firecrawl `client.crawl(...)` depth-two call | Removed | Provider-owned recursion violates the approved architecture. |
| 50-page aggregation into one `RawArtifact` | Removed | Collapsed URL provenance and page-level retry/cost state. |
| ContextVar/task-local scrape session cache | Removed | Non-durable, process-local, and drifted from PostgreSQL authority. |
| `materialization_only` waterfall/gate bypass | Removed | Derived from the rejected task-local cache and bypassed ordinary admission semantics. |
| Crawl result metadata overriding per-field cost | Removed | C4 owns actual provider cost on attempts; claims do not duplicate acquisition cost. |
| Fast budget increase from 25¢ to 100¢ | Removed | Was justified only by the monolithic 50-page provider crawl. |
| 400k-character field extractor input | Removed | C7 must use checkpoint/category-bounded extraction, not one giant document. |
| Stage-0 Luna environment setting | Deferred to C7 | Model selection is valid, but no unconsumed production setting lands in C0. |
| Firecrawl 429 retry loop from the spike | Deferred to C3/C4 | Retry requires durable attempt/spend state, not an in-adapter sleep loop. |

Unrelated Clerk/profile/onboarding-auth changes already present in the worktree were preserved and
are outside this inventory.

## 9. File and ownership manifest

| Slice | Owner | Files/directories |
|---|---|---|
| C0 contracts | Research official-site domain | `clue_research/official_site/{contracts,seams,transitions}.py` |
| C1 DDL/repository | M7 durability + research | Alembic revision; `official_site/models.py`, `repository.py` |
| C2 URL/graph/safety | M4 source acquisition | `official_site/{url_policy,discovery,safety,robots}.py` |
| C3 fetch adapters | Provider packages | `adapters/firecrawl_page/`, `adapters/scrapling_page/` |
| C4 artifacts/recovery | PB-B2 + official-site | `official_site/{artifacts,reconciliation}.py` |
| C5 coordinator | M4/M7 | `official_site/coordinator.py`; worker handler registration |
| C6 run lifecycle | M5/FI-4 + fleet | worker composition; setup/status adapter; no long work in API process |
| C7 materializer | M5 + gateway/claim store | `official_site/materializer.py`; grounded extraction fixtures |
| C8 projections/ops | FI-4 + observability | additive setup projection, logs, metrics, runbook |
| C9–C10 acceptance | Integration | isolated DB/artifact roots and retained browser/provider evidence |

No crawl-domain type is promoted into `clue_core` in C0. It has one consumer and stays within the
research subsystem. Provider SDK imports remain confined to provider adapter modules.

## 10. Feature-flag rollout contract

C1 adds validated settings only after their repository consumers exist:

```text
CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off|shadow|authoritative  # default off
CLUE_STAGE0_OFFICIAL_SITE_CRAWL_WORKSPACE_ALLOWLIST=[]
CLUE_STAGE0_PAGE_FETCHER=firecrawl|scrapling
CLUE_STAGE0_CRAWL_MAX_DEPTH=2
CLUE_STAGE0_CRAWL_FAST_DEADLINE_SECONDS=40
...the remaining validated knobs from the parent plan
```

- `off`: historical field-oriented resolver remains authoritative; no crawl row is created.
- `shadow`: named allowlisted workspaces create the new durable crawl and comparison evidence, but
  historical behavior still drives claims/user release.
- `authoritative`: permitted only after C9 and C10; the new checkpoint/materializer drives the
  owned-surface Client-KB path. Startup refuses recursive provider configuration.
- The mode and all effective knobs are pinned to each crawl run. Changing environment values never
  changes an existing run.
- Rollback returns new starts to `off`; it never deletes or steals in-flight/retained crawl state.

## 11. C0 verification and handoff

C0 acceptance requires:

- canonical fixture validates all enums, transitions, fetch payloads, and materialization payloads;
- unsafe depth/deadline/concurrency/lease settings fail construction;
- sitemap discovery cannot claim graph depth;
- spend ambiguity cannot become an automatic retry;
- reconciliation obtains a fresh page fence while preserving the original attempt generation;
- persistence recovery obtains a fresh fence and cannot re-fetch a recorded provider success;
- attempt-ledger result metadata contains no page bytes or outgoing-link payload;
- all protocols are structurally satisfiable by provider-free doubles;
- an AST guard proves the C0 package imports no Firecrawl, Scrapling, HTTP, SQLAlchemy, or asyncpg;
- the historical Firecrawl adapter calls single-page `scrape`, never `crawl`;
- targeted lint, type, import, and provider-free tests pass.

C1 implemented the exact DDL and repository operations, C2 preserved those frozen shapes, C3
implemented provider adapters, and C4 implemented artifact/recovery behavior behind the frozen
seams. C5 may not change table names, states, `PageFetcher`, `CrawlRepository`, or materialization
shapes without reopening C0.
