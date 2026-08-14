# Stage-0 durable official-site crawling — implementation plan

**Status:** C0–C5 implemented and verified; C6–C10 not yet accepted

**Branch:** `platform/onboarding-integration`

**Owners:** M4 source acquisition + M5 Stage-0 composition + M7 durability + FI-4 onboarding

**Depends on:** M4.1–M4.5, M5.1, M7.4, PB-B1, PB-B2, FI-4 slices 2–3

**Supersedes for this scope:** the proposal to make one provider-owned recursive Firecrawl call and
reuse its in-memory result across onboarding fields

**Does not supersede:** the `Resolver` protocol, source tiers, claim-store write contract,
content-addressed artifact storage, or the existing frontend progress repository seam

---

## 1. Decision and outcome

The binding decision is:

> **Clue owns crawl semantics. Firecrawl, Scrapling, and future providers fetch exactly one page
> per acquisition request.**

Stage-0 needs a broad, source-grounded picture of the client's official website: homepage,
products and use cases, pricing, company/founder pages, customers/case studies/testimonials,
partners, integrations, trust, and other relevant owned surfaces. That coverage must not be
implemented by handing recursion, deduplication, prioritization, or retry ownership to one hosted
provider. Those are platform semantics and must stay identical when the fetch provider changes.

This plan introduces a **new durable official-site crawling capability**. It is not a cosmetic
change to `FirecrawlScrapeBackend`, and it is not merely a Firecrawl-to-Scrapling adapter swap. The
capability owns:

- a PostgreSQL-backed URL frontier and crawl ledger;
- conservative URL identity and alias observations;
- atomic, fenced concurrent work claiming;
- link-graph depth and sitemap-origin distinctions;
- provider-neutral single-page acquisition;
- per-URL and per-attempt provenance;
- content-addressed snapshot reuse without provenance collapse;
- fast-lane and background-lane continuity over one crawl run;
- provider-spend ambiguity and recovery;
- safety policy, progress truth, and operational evidence.

The user-visible target is a **truthful fast result within 40 seconds** when the site and configured
providers respond within their bounds. The system releases the user using the best durably
completed official-source evidence at the fast deadline; the background phase continues the same
frontier. It never claims that a large site was exhaustively crawled in 40 seconds.

### 1.1 Why the monolithic crawl is rejected

The 2026-08-14 isolated Insight Health acceptance spike is evidence, not an accepted implementation:

- one Firecrawl recursive job eventually reached its 50-page ceiling and charged 50 credits;
- the SDK crossed the application's 300-second wait deadline immediately before the provider job
  became retrievable as completed;
- the fast recon lane failed after roughly 501 seconds;
- the returned URL set did contain useful product, pricing, company, partner, integration, trust,
  and blog pages, proving the discovery goal but disproving the execution shape;
- while the synchronous call owned the web event loop, onboarding polling could not expose honest
  progress.

No implementation checkpoint may restore provider-owned recursion under another name.

---

## 2. Current state, target state, and migration boundary

### 2.1 Current accepted baseline

The accepted Stage-0 path is essentially homepage-oriented and field-oriented:

- a resolved client entity is bound to the tier-2 official-site source;
- the existing scrape adapter fetches a page and snapshots its bytes;
- `reverse_profile` walks registered `client.*` fields through the waterfall;
- per-field progress events and lane truth drive the onboarding screen;
- Firecrawl and Scrapling already sit behind a scrape-backend seam, but that seam is not a durable
  multi-page crawl scheduler;
- the web composition currently owns the Stage-0 driver and contains synchronous provider/model
  leaves that can block its event loop when enabled with real credentials.

### 2.2 Target state

The target path separates acquisition from claim materialization:

1. `start_recon` creates or reuses one durable official-site crawl run.
2. The crawl coordinator discovers and prioritizes candidate URLs.
3. Concurrent workers claim individual URLs from PostgreSQL.
4. A configured `PageFetcher` fetches one URL per call.
5. Clue records the URL-level fetch result, exact provider receipt, and page artifact.
6. Clue—not the provider—extracts links, applies safety/normalization policy, and expands the
   depth-bounded frontier.
7. The fast checkpoint freezes the completed snapshot set available by the deadline.
8. Concurrent, grounded extraction materializes tier-2 Client-KB claims from that snapshot set.
9. The fast Client-KB version releases the user; the background phase resumes the same frontier,
   adds late/remaining pages, and produces a later Client-KB version.

### 2.3 Cutover boundary

The new path becomes authoritative only after the offline and live exit gates in this plan pass.
Until then:

- the current resolver remains the accepted implementation;
- any uncommitted depth-two provider-owned crawl is a disposable spike;
- no docs or UI may claim broad durable crawling is live;
- no migration is applied to a shared development database for acceptance testing;
- no old claim, artifact, or provisioning row is rewritten to simulate the new path.

---

## 3. Scope

### 3.1 In scope

- Same-site `http`/`https` official-page discovery beginning from the submitted canonical homepage.
- Bounded sitemap discovery as inventory and priority evidence.
- A homepage-rooted link graph with maximum graph depth two.
- Explicit policy admission of high-value sitemap-only pages into the fast lane while their
  `graph_depth` remains unknown.
- PostgreSQL as both the V1 frontier and durable ledger.
- Atomic URL claiming using row locks and `FOR UPDATE SKIP LOCKED`.
- Lease expiry, renewal, generation fencing, and stale-worker rejection.
- One crawl run with fast and background phases.
- Provider-neutral single-page Firecrawl and Scrapling implementations.
- Conservative URL keys plus complete discovered/requested/final URL provenance.
- Redirect, canonical-hint, sitemap, and link-edge records.
- Content-addressed page blobs with distinct URL-level snapshot records.
- Concurrent acquisition and concurrent grounded extraction.
- Paid-provider dispatch/receipt/spend reconciliation.
- Domain, SSRF, redirect, robots, MIME, size, page, time, and concurrency controls.
- Durable progress projections suitable for the existing onboarding repository seam.
- DSAR/erasure and retention reachability for crawl artifacts and ledgers.
- Offline fault tests, provider conformance tests, isolated-DB tests, and live browser acceptance.

### 3.2 Explicitly out of scope

- General internet search or third-party discovery; Exa search remains a separate tier-3 source.
- Logged-in/private pages, customer portals, authentication workflows, or CAPTCHA circumvention.
- Restricted-platform scraping such as LinkedIn/X outside authorized provider/API contracts.
- Arbitrary cross-domain crawling.
- An autonomous research agent deciding crawl mechanics.
- Redis or an in-memory scheduling authority in V1.
- Cross-workspace sharing of crawl results in V1.
- Treating a canonical tag as authoritative identity without verification.
- Guaranteeing exhaustive depth-two completion before the 40-second fast deadline.
- Replacing the M9 accuracy/faithfulness gates or the claim-store merge policy.
- Brand-kit extraction, which remains owned by the design-integration plan.
- A Temporal migration; the state machine remains shaped so it can move later.

### 3.3 Terminology

| Term | Meaning |
|---|---|
| Crawl run | One workspace-scoped official-site traversal, shared by fast and background phases. |
| URL observation | One exact URL string observed from a link, sitemap, redirect, or canonical hint. |
| Fetch key | Conservative normalized identity used to suppress duplicate acquisition within one run. |
| Page node | The durable frontier item associated with a fetch key. |
| Fetch attempt | One provider dispatch for one page node under one lease generation. |
| Snapshot | One URL-level acquisition record pointing to an immutable content-addressed blob. |
| Corpus checkpoint | The exact ordered snapshot set admitted to fast or background extraction. |
| Graph depth | Shortest verified homepage-link path; sitemap discovery alone yields `unknown`. |
| Traversal expansion | Enqueuing outgoing links from a fetched node whose verified graph depth is below two. |

---

## 4. Binding invariants

These are implementation gates, not aspirations:

1. **PostgreSQL is the only scheduling authority in V1.** No Redis queue or shared process map is
   required for correctness.
2. **A provider call fetches one page.** Recursive provider options are disabled and asserted in
   every provider conformance test.
3. **One page node has at most one active lease generation.** Completion/failure writes must match
   `(page_id, lease_owner, lease_generation)`.
4. **A stale worker cannot publish.** A fenced completion updating zero rows is a terminal stale
   result for that worker, even if it holds valid page bytes.
5. **No check-then-act dedupe.** Discover/upsert and claim operations are atomic at the database.
6. **Fast and background are phases of one crawl run.** Background never creates a second crawl
   solely to continue onboarding.
7. **The fast deadline stops new fast claims; it does not cancel an already-dispatched call.** Late
   safe results can join the background checkpoint.
8. **Spend ambiguity blocks blind retry.** `provider_dispatched` with no reconcilable terminal
   receipt becomes `spend_unknown`; it is never automatically called again.
9. **Content dedupe never erases URL provenance.** Identical bytes may share one blob, while every
   URL fetch/snapshot/receipt remains independently queryable.
10. **Sitemap discovery is not graph depth.** A sitemap-only page has `graph_depth = NULL` until a
    verified link path establishes depth.
11. **Provider output cannot weaken coordinator policy.** Requested/final URLs, redirects, links,
    MIME, size, and host are revalidated by Clue.
12. **All evidence is page attributable.** A claim cites the URL-level snapshot from which its
    exact evidence span was validated.
13. **No fake progress.** Every visible count/status is reduced from committed crawl, extraction,
    or claim state.
14. **Public-site bytes remain workspace scoped in V1.** Cross-tenant reuse is deferred to a
    separately reviewed reuse/privacy design.
15. **Empty is correct.** A refused, timed-out, disallowed, or unsupported page produces an
    explicit outcome; it never produces guessed claims.

---

## 5. System architecture and ownership

```text
Stage0ReconCoordinator
    |
    +-- OfficialSiteCrawlService
    |       +-- CrawlRepository              (Postgres frontier + ledger)
    |       +-- UrlPolicy                    (normalization + domain/safety decisions)
    |       +-- SitemapDiscoverer            (inventory, not graph depth)
    |       +-- LinkExtractor                (shared, provider-neutral)
    |       +-- RobotsPolicy                 (shared, host-scoped cache)
    |       +-- PageFetcher                  (single-page protocol)
    |       |       +-- FirecrawlPageFetcher
    |       |       +-- ScraplingPageFetcher
    |       +-- SnapshotStore                (PB-B2 StorageBackend + artifact rows)
    |       +-- CrawlProgressSink            (durable events/read projection)
    |
    +-- OfficialSiteCorpusMaterializer
            +-- CorpusReader
            +-- grounded concurrent extractor (OpenRouter; configured model)
            +-- existing claim validation/write path
```

### 5.1 Ownership boundary

| Component | Owns | Must not own |
|---|---|---|
| Crawl coordinator | Frontier, priority, depth, deadlines, concurrency, safety, retries | Provider SDK details; claim truth decisions |
| `PageFetcher` | One provider request and a typed result/receipt | Recursion, global dedupe, frontier mutation, claim writes |
| URL policy | Fetch-key derivation and allow/refuse decisions | Network acquisition |
| Link extractor | Raw outgoing-link observations from captured page content | Frontier claiming or provider calls |
| Snapshot store | Immutable bytes and artifact metadata | URL equivalence or claim extraction |
| Corpus materializer | Grounded drafts/claims from a frozen snapshot set | Fetching new URLs |
| Existing waterfall/claim store | Source ordering, validation, append-only claims, merge | Crawl scheduling |
| API process | Capture/start/status surfaces | Long-running page acquisition or model loops |
| Worker process | Crawl/extraction execution | Human session authority |

### 5.2 Package placement

The recommended V1 placement is:

- `subsystems/research/clue_research/official_site/` — crawl domain types, repository, URL policy,
  discovery, coordinator, corpus reader/materializer, and tests;
- `subsystems/research/clue_research/adapters/firecrawl_page/` — Firecrawl SDK boundary only;
- `subsystems/research/clue_research/adapters/scrapling_page/` — Scrapling boundary only;
- `platform/api/clue_api/` — composition, setup/status projection, and worker wiring;
- `libs/clue-storage` — reused unchanged except for generally useful artifact helpers proven to
  have more than one consumer;
- `libs/clue-core` — only truly shared value types; do not promote crawl-only types prematurely.

Provider packages may import their SDK. The coordinator and materializer may not branch on a
provider name; the composition root selects a registered `PageFetcher`.

---

## 6. Provider-neutral contracts

### 6.1 `PageFetcher`

The C0 executable package freezes the exact models; this abbreviated view mirrors that authority:

```python
class PageFetcher(Protocol):
    capabilities: PageFetcherCapabilities  # includes single_page_only=True

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult: ...


class PageFetchRequest(BaseModel):
    operation_key: str
    requested_url: str
    allowed_hosts: tuple[str, ...]
    timeout_seconds: float
    max_response_bytes: int
    accepted_mime_types: tuple[str, ...]
    max_redirects: int
    robots_decision_ref: str


class PageFetchResult(BaseModel):
    provider_key: str
    provider_request_id: str | None
    requested_url: str
    final_url: str | None
    redirect_chain: tuple[RedirectHop, ...]
    provider_status: str
    http_status: int | None
    content: bytes | None
    media_type: str | None
    outgoing_links: tuple[LinkObservation, ...]
    fetched_at: datetime
    cost_cents: Decimal | None
    cost_kind: Literal["actual", "estimated", "none"]
    spend_status: Literal["spend_confirmed", "spend_unknown", "no_spend"]
    retry_class: Literal[
        "success", "retryable_no_spend", "permanent",
        "robots_refused", "policy_refused", "ambiguous"
    ]
    receipt: dict[str, JsonValue] | None
```

Rules:

- The coordinator creates and persists `operation_key` before dispatch.
- Providers use it as an idempotency key when their API supports one.
- `outgoing_links` are observations, not automatically trusted frontier items. The shared link
  extractor and URL policy remain authoritative; provider-supplied link lists may supplement but
  never bypass them.
- A provider returning no receipt support declares that capability. Recovery then quarantines an
  ambiguous dispatched attempt rather than retrying it.
- There is no `retryable_charged` result. Once a call may have charged, an unresolved outcome is
  `ambiguous`/`spend_unknown` and must reconcile or quarantine; it never authorizes a blind retry.
- Request/response headers, credentials, raw tokens, and full provider payloads are never logged.

### 6.2 `CrawlRepository`

The repository exposes transaction-sized operations, not a mutable in-memory collection:

```python
create_or_get_run(...)
record_discoveries(run_id, observations)
claim_next(run_id, worker_id, eligible_phase, lease_ttl) -> CrawlLease | None
claim_reconciliation(run_id, worker_id, lease_ttl) -> ReconciliationClaim | None
claim_persistence(run_id, worker_id, lease_ttl) -> PersistenceClaim | None
renew_lease(page_id, worker_id, generation, lease_ttl) -> bool
begin_attempt(lease, provider_key, operation_key) -> FetchAttemptRef
mark_attempt_dispatched(lease, attempt) -> bool  # DB stamps dispatched_at before external I/O
record_provider_result(lease, attempt, body_free_result_metadata) -> bool
persist_snapshot(lease, attempt, artifact_ref, result_metadata, link_observations) -> snapshot | None
complete_page(lease, snapshot_id) -> bool
disposition_attempt(lease, attempt, outcome) -> bool
reclaim_expired_leases(run_id)
freeze_corpus_checkpoint(run_id, phase)
transition_phase(run_id, expected_status, next_status)
read_progress(run_id)
```

Every mutation carries `workspace_id` internally or derives it through a workspace-scoped parent
row. Every worker-owned mutation carries the lease generation.

---

## 7. Durable schema

One additive Alembic migration uses the repository's random-hash revision convention and must
leave exactly one head. Names below are binding intent; C0 may shorten them while preserving the
constraints.

### 7.1 `official_site_crawl_run`

| Column | Contract |
|---|---|
| `id` | UUID primary key; stable crawl identity. |
| `workspace_id` | Required tenancy key and indexed. |
| `brand_id` | Provisioned brand lineage. |
| `client_entity_id` | Resolved client entity; nullable only before identity creation commits. |
| `recon_run_id` | Stage-0 lineage; one live crawl per recon official-site acquisition. |
| `root_discovered_url` | Exact submitted homepage URL. |
| `root_fetch_key` | Conservative normalized root key. |
| `allowed_registrable_domain` | Coordinator policy input. |
| `status` | `queued|fast_active|fast_closing|fast_complete|background_active|completed|failed|cancelled`. |
| `max_graph_depth` | V1 value `2`; CHECK `= 2`. |
| `fast_claim_deadline_at` | DB timestamp after which fast claims are refused. |
| `overall_page_ceiling` | Safety bound, not a claim of completeness. |
| `fast_page_ceiling` | Maximum pages admitted before the fast deadline. |
| `provider_policy_version` | Pins provider selection/fallback behavior. |
| `url_policy_version` | Pins normalization/domain/safety semantics. |
| `robots_policy_version` | Pins robots behavior. |
| `created_at/updated_at/completed_at` | DB-clock lifecycle timestamps. |

Constraints/indexes:

- unique live identity on `(workspace_id, recon_run_id)`;
- status/timestamp CHECKs prevent terminal rows without terminal timestamps;
- index `(status, fast_claim_deadline_at)` for worker scheduling;
- no URL query string in operational log keys.

### 7.2 `official_site_crawl_page`

| Column | Contract |
|---|---|
| `id`, `crawl_run_id`, `workspace_id` | Primary and tenant lineage. |
| `fetch_key`, `fetch_key_hash` | Conservative per-run acquisition identity. |
| `representative_requested_url` | Exact URL chosen for acquisition; not silently rewritten later. |
| `host` | Normalized host for policy/concurrency. |
| `graph_depth` | Nullable shortest verified homepage-link path `0..2`; `NULL` for sitemap-only/unknown. |
| `priority`, `priority_reason_json` | Stable scheduling order plus explainability. |
| `eligibility` | `fast|background|both|refused`. |
| `state` | `discovered|queued|leased|provider_started|reconciliation_pending|persistence_pending|retry_wait|fetched|failed|quarantined|refused`. |
| `lease_owner`, `lease_generation`, `lease_acquired_at`, `lease_expires_at` | Fenced ownership. |
| `attempt_count` | Number of durable attempts, never inferred from logs. |
| `expanded_min_depth` | Shallowest depth at which saved outgoing links were expanded. |
| `latest_snapshot_id`, `terminal_reason` | Reference-only result/terminal detail. |
| timestamps | DB-clock discovery/queue/fetch lifecycle. |

Constraints/indexes:

- unique `(crawl_run_id, fetch_key_hash, fetch_key)`; hash alone is never identity;
- leased/provider-started states require owner, generation, and unexpired lease fields;
  reconciliation-pending and persistence-pending carry either all lease fields while actively
  claimed by their recovery worker or none while waiting;
- non-leased terminal states clear holder fields;
- claim-next index `(crawl_run_id, state, eligibility, priority, discovered_at)`;
- index `(crawl_run_id, host, state, lease_expires_at)` for per-host capacity and reclaim.

### 7.3 `official_site_url_observation`

Preserves every provenance-bearing URL occurrence even when it maps to an existing page node:

`id, workspace_id, crawl_run_id, page_id, discovered_url, discovered_via
{root|link|sitemap|redirect|canonical}, source_page_id, graph_depth, link_text_bounded,
sitemap_url, observed_at, policy_outcome, policy_reason`.

No unique constraint collapses distinct observations. A narrow idempotency constraint prevents the
same parser replay from inserting an identical observation repeatedly.

### 7.4 `official_site_link_edge`

`id, crawl_run_id, from_page_id, to_page_id, discovered_url, link_relation, observed_at` with a
unique replay key. It preserves the verified link graph separately from sitemap inventory,
redirects, and canonical hints.

When a fetched node is later discovered through a shallower link path:

1. update `graph_depth` using `LEAST`;
2. do not refetch the node;
3. if the new depth is below `max_graph_depth` and is shallower than `expanded_min_depth`, expand
   its already-saved outgoing observations at `new_depth + 1`;
4. make that expansion idempotent through the edge/upsert keys.

### 7.5 `official_site_fetch_attempt`

| Column | Contract |
|---|---|
| `id`, `workspace_id`, `crawl_run_id`, `page_id` | Lineage. |
| `attempt_number`, `lease_generation`, `worker_id` | Fenced execution identity. |
| `operation_key` | Stable unique provider idempotency/reconciliation key. |
| `provider_key` | Implementation used, separate from source authority. |
| `state` | `prepared|dispatched|provider_succeeded|persisted|retryable_no_spend|failed|spend_unknown|reconciled_no_spend|reconciled_succeeded|quarantined`. |
| `provider_request_id`, `provider_receipt_json` | Sanitized durable receipt. |
| `requested_url`, `final_url`, `redirect_chain_json` | Exact acquisition provenance. |
| `provider_status`, `http_status`, `media_type`, `size_bytes` | Typed outcome. |
| `cost_cents`, `cost_kind`, `spend_status`, `retry_class` | Honest actual/estimated/none cost and retry state. |
| `artifact_key`, `content_sha256` | Result refs only; bytes live in storage. |
| `started_at`, `provider_completed_at`, `persisted_at`, `finished_at` | DB/provider timestamps. |

Constraints:

- unique `operation_key` and `(page_id, attempt_number)`;
- `provider_succeeded` requires a confirmed success outcome but may precede artifact persistence;
- `persisted` requires artifact/content refs;
- `spend_unknown` cannot transition automatically to another dispatch;
- terminal updates require the matching `lease_generation` through repository predicates.

### 7.6 `official_site_page_snapshot`

One row per URL-level successful acquisition:

`id, workspace_id, crawl_run_id, page_id, fetch_attempt_id, requested_url, final_url,
redirect_chain_json, fetched_at, provider_key, provider_request_id, http_status, media_type,
artifact_key, content_sha256, size_bytes, robots_decision_ref, policy_version`.

Two snapshots may point to the same `artifact_key/content_sha256`. They remain two snapshot rows
because URL, redirect path, time, provider, cost receipt, and HTTP outcome are provenance.

### 7.7 `official_site_alias_observation`

`id, crawl_run_id, source_page_id, alias_url, kind{redirect|canonical_hint},
verification_status{observed|verified_same_content|verified_redirect|rejected_external|conflicting},
target_page_id, observed_at`.

A canonical tag starts as `observed`. It never changes the fetch key or suppresses acquisition by
itself. Cross-domain canonical hints are recorded as rejected and are never followed automatically.

### 7.8 `official_site_corpus_checkpoint`

`id, workspace_id, crawl_run_id, phase{fast|background}, version, snapshot_ids_json,
snapshot_set_sha256, coverage_json, created_at`.

The checkpoint is immutable. Extraction and Client-KB versions pin this exact corpus identity so a
late background page cannot retroactively change the fast result.

### 7.9 Global and host concurrency

V1 uses PostgreSQL only. Claiming acquires a short transaction-scoped global claim advisory lock,
then a host advisory lock derived from the normalized host, always in that order. Under those locks
it reclaims expired leases, counts active global and host leases, and selects/updates an eligible
page with `FOR UPDATE SKIP LOCKED`. The host key is not crawl-run scoped: concurrent runs targeting
the same host must share the same capacity. All expiry comparisons use database `now()`.

The global lock protects the global count across different hosts; the host lock protects the
per-host count across different runs. Both are held only for the claim transaction, never during a
network call. This avoids a racy `COUNT` while also avoiding a second scheduler. If profiling later
shows advisory-lock contention, explicit PostgreSQL global/host slot rows are the first alternative;
Redis is not introduced without measurements and a new decision record.

---

## 8. Conservative URL identity

### 8.1 Preserve four identities

Never overload one URL column. Preserve:

1. **discovered URL** — exact string found in source material;
2. **fetch key** — conservative within-run acquisition identity;
3. **requested URL** — exact URL sent to the provider;
4. **final URL** — provider-observed terminal URL after redirects.

Redirect and canonical observations are separate records. A user or reviewer can always reconstruct
why a page was fetched and what actually answered.

### 8.2 Default fetch-key rules

The versioned V1 policy:

- resolve relative references against the exact source page URL;
- accept only `http` and `https`;
- normalize scheme/host case and IDNA representation;
- remove a default port only;
- normalize only unreserved percent-encoding equivalence;
- preserve path case;
- preserve `/pricing`, `/pricing/`, `/`, and `/index.html` as distinct keys;
- preserve query order, repeated keys, and all non-tracking parameters;
- remove only an explicit, versioned allowlist of tracking parameters (`utm_*`, `gclid`,
  `fbclid`, etc.), while retaining the discovered URL and the normalization decision;
- do not treat a canonical hint as equivalence;
- strip ordinary same-document fragments because HTTP does not transmit them, but retain known
  routing fragments such as `#/...`/`#!/...` as a distinct routing discriminator; the exact
  classification is pinned by fixtures;
- apply no content-dependent aliasing before a response is captured.

### 8.3 Content deduplication

- Blob identity is the exact captured-byte SHA-256 under PB-B2.
- URL snapshots remain distinct even when hashes match.
- Extraction may reuse a result for identical artifact bytes **only** when extractor model,
  prompt/schema version, policy version, and relevant page metadata identity also match.
- Reuse records both source snapshot IDs; it never rewrites one snapshot to masquerade as another.

---

## 9. Discovery, prioritization, and depth

### 9.1 Discovery channels

- **Root:** submitted homepage; verified graph depth `0`.
- **Link:** extracted from a fetched page; depth `parent_depth + 1` when parent depth is known.
- **Sitemap:** bounded inventory; graph depth `unknown` until independently linked.
- **Redirect:** acquisition provenance; not an independent statement of graph depth.
- **Canonical:** an untrusted identity hint; not depth and not an automatic fetch instruction.

### 9.2 Sitemap behavior

The coordinator may inspect `robots.txt`, sitemap declarations, `/sitemap.xml`, and bounded sitemap
indexes. XML size, nested-index depth, URL count, host, and MIME are capped. Sitemap parsing:

- creates URL observations with `discovered_via=sitemap`;
- assigns category/priority evidence;
- never assigns graph depth;
- may admit policy-selected high-value pages into the fast queue with `graph_depth=NULL`;
- does not recursively expand a sitemap-only page until a verified homepage link path gives it a
  graph depth below two. This preserves the meaning of “depth two from the homepage.”

### 9.3 Deterministic priority categories

V1 classification uses URL path, bounded link text, page title/metadata, and configured patterns—no
LLM in the scheduler. Categories are versioned data:

1. homepage;
2. product/solution/use case (target several distinct pages);
3. pricing;
4. customer/case study/testimonial/proof;
5. about/company/mission/founder/team;
6. partner/integration;
7. trust/security/compliance;
8. selected blog/news pages relevant to product positioning;
9. remaining eligible depth-two pages.

Fast defaults target 8–12 pages with category quotas rather than simply taking the first links in
DOM order. Missing categories are reported as missing; the classifier does not invent pages.

### 9.4 Frontier insertion

Every discovery batch is processed transactionally:

1. validate and normalize each observation;
2. record the exact observation even if refused or already known;
3. upsert the page node on `(crawl_run_id, fetch_key)`;
4. lower `graph_depth` when a shorter verified path appears;
5. recompute priority only according to the pinned policy;
6. enqueue only if within domain/safety/depth/page policy and not already terminal or active;
7. record/link edges independently from page dedupe.

---

## 10. Concurrency, leasing, and fencing

### 10.1 Claim order

Within an active run:

1. eligible fast work before background work;
2. smaller category priority first;
3. shallower known graph depth first;
4. older discovery first;
5. page ID as deterministic tie-breaker.

Background claiming is disabled while the run is `fast_active` except for attempts already in
flight. After `fast_complete`, the same nodes/frontier continue under `background_active`.

Across runs, fast-active runs outrank background-active runs. A background request already sent to
a provider is not cancelled when new fast work arrives; the next available claim goes to fast work.
Per-request timeouts bound that temporary occupancy.

### 10.2 Atomic claim

In one transaction:

1. take the global claim advisory lock;
2. inspect priority-ordered candidates using `FOR UPDATE SKIP LOCKED`;
3. take the selected candidate's host advisory lock in the fixed global-then-host order;
4. reclaim expired global/host leases and verify both capacities;
5. if that host is full, leave the page queued and inspect the next eligible host without changing
   priority data;
6. increment `lease_generation` on the selected page;
7. stamp owner/acquired/expiry and `state=leased` using DB time;
8. commit and return the lease token.

No worker checks a Python set before this transaction.

### 10.3 Heartbeat and expiry

- `2 × heartbeat_interval < lease_ttl` is a construction-time invariant.
- Renewal matches owner and generation and uses DB time.
- A renewal updating zero rows fences the worker; it stops making new external calls.
- A provider call already dispatched is allowed to finish, but the fenced worker may not publish a
  receipt, snapshot, page completion, or claim. Its result can only be adopted after a separate
  reconciliation claim obtains the new generation; unadopted bytes remain orphan-safe.
- Expired leases become reclaimable only after attempt state is examined. A `dispatched` attempt
  first becomes `spend_unknown` or is reconciled; it is not blindly redispatched.
- Reclamation clears the expired lease and moves ambiguous dispatched work to
  `reconciliation_pending`. `claim_reconciliation` obtains a new generation without changing that
  semantic page state, pairs the new page lease with the original attempt, and never authorizes a
  second provider dispatch.
- A recorded success with expired persistence ownership remains `persistence_pending` with the
  lease cleared. `claim_persistence` obtains a new generation and resumes from its body-free result
  metadata/content-addressed blob; it never invokes the provider again.

### 10.4 Completion fence

Every result transition includes:

```sql
WHERE page_id = :page_id
  AND lease_owner = :worker_id
  AND lease_generation = :lease_generation
  AND state IN ('leased', 'provider_started', 'reconciliation_pending', 'persistence_pending')
```

Zero affected rows means stale completion. Artifact bytes may remain content-addressed/orphan-safe,
but no page/snapshot/claim state is published from that stale authority.

---

## 11. Fast/background lifecycle and the 40-second contract

### 11.1 One run, two immutable checkpoints

- `fast_active` starts at durable crawl creation.
- The fast claim deadline is stored in PostgreSQL, not calculated independently by workers.
- At the deadline (or earlier coverage satisfaction), the coordinator transitions to
  `fast_closing`, atomically stops new fast claims, and freezes all safely persisted snapshots
  currently eligible for fast extraction.
- Calls already dispatched continue. They are not part of the frozen fast checkpoint unless they
  had safely persisted before the freeze.
- The fast materializer writes a pinned Client-KB version and the run becomes `fast_complete`.
- The onboarding UI releases on the existing fast-complete truth.
- The run then becomes `background_active`; late safe results and remaining frontier work form a
  later immutable background checkpoint and Client-KB version.

### 11.2 Time budget

Default target envelope, configurable and measured:

| Work | Target |
|---|---:|
| Durable start + root/sitemap discovery | 3–5 s |
| Concurrent prioritized page acquisition | 12–20 s |
| Concurrent category extraction | 8–12 s |
| Validation, commit, projection | 2–3 s |
| Application hard release target | ≤40 s |

The deadline is a latency contract, not a reason to fabricate completeness. If the homepage or all
useful pages fail, the fast outcome is typed partial/failure and the existing recovery surface is
used. The exact minimum release policy is frozen in C0 and tested with missing-category fixtures.

### 11.3 Cancellation rules

- Stop claiming new fast pages at the deadline.
- Do not cancel a provider call whose spend status could become ambiguous.
- Do not move its page back to `queued` while the original attempt is unresolved.
- Permit a clean no-spend local fetch to be cancelled/retried only when the provider contract proves
  no external effect occurred.
- Shutdown stops claims, persists attempt state, and lets the lease/reconciler model handle recovery.

---

## 12. Provider behavior

### 12.1 Firecrawl

- Use the single-page scrape API only.
- Explicitly disable/omit crawl, map-driven recursion, sitemap recursion, and hidden multi-page
  options.
- Return provider request ID/receipt, final URL, status, exact content, MIME, links, and credits
  whenever the API exposes them.
- Declare whether operation-key lookup/idempotency is supported. Do not imply exactly-once provider
  behavior when it is not.
- A Firecrawl SDK timeout after dispatch is `spend_unknown` until status/receipt reconciliation.

### 12.2 Scrapling

- Fetch one approved URL under the same request contract.
- Use coordinator-supplied timeout, size, MIME, robots, and redirect constraints.
- A local fetch that definitively made no billable provider call returns `no_spend`.
- Browser/adaptive modes remain policy-selected capabilities; they do not change frontier rules.

### 12.3 Conformance suite

Every provider implementation must pass the same tests for:

- exactly one requested page;
- redirect/final-URL reporting;
- status and MIME reporting;
- bounded response size/time;
- outgoing-link observation shape;
- confirmed/no-spend/unknown spend classifications;
- retry classification;
- sanitized receipts;
- no secret logging;
- cancellation semantics;
- no recursive provider behavior.

---

## 13. Safety policy

Safety decisions live in the coordinator and are versioned.

### 13.1 Domain and redirects

- Derive the allowed registrable domain from the verified root.
- Same host is allowed by default; same registrable-domain subdomains are separately configurable.
- Revalidate every redirect hop and final URL.
- An off-domain redirect is refused/quarantined before its content enters extraction.
- Login/auth/account subdomains and paths may be denied by policy even when registrable-domain
  related.
- External canonical hints are recorded but never followed automatically.

### 13.2 SSRF and network targets

Before dispatch, and for redirects when locally observable:

- resolve DNS and reject loopback, RFC1918/private, link-local, multicast, reserved, unspecified,
  carrier-grade NAT, and cloud-metadata ranges for IPv4 and IPv6;
- reject IP-literal private/reserved targets;
- reject non-HTTP schemes and credential-bearing URLs;
- bound DNS answers and resolution time;
- for a remote hosted fetcher, enable its equivalent threat/SSRF protection and still validate the
  returned final URL; provider safety is defense in depth, not coordinator authority;
- for local Scrapling, use a redirect-aware safe resolver/transport so DNS rebinding cannot bypass
  the preflight check.

### 13.3 Robots and content

- Respect robots policy by default; cache a versioned host decision with expiry.
- Bound robots and sitemap response size.
- Allow only configured MIME classes (initially HTML/XHTML/plain text and explicitly enabled PDF).
- Reject archives, executables, media blobs, and unsupported binary content.
- Enforce decompressed response-size limits, not only compressed transfer size.
- Treat malformed markup as a typed parse outcome, not a reason to relax safety.
- Strip active content before extraction; never execute page-provided instructions as agent/tool
  commands.

### 13.4 Resource ceilings

- overall page ceiling;
- fast page ceiling;
- maximum graph depth two;
- sitemap URL/index ceilings;
- global and per-host concurrency;
- per-request and phase deadlines;
- maximum redirects;
- maximum outgoing links retained per page;
- bounded link text/title metadata;
- maximum extraction corpus bytes/tokens per call.

These are safety/reliability bounds and honesty surfaces. They do not reinstate the rejected policy
of truncating onboarding merely to save cost.

---

## 14. Artifact, provenance, and erasure

### 14.1 Persistence order

For a successful provider response:

1. validate final URL, redirects, MIME, and size;
2. compute content SHA-256 over exact captured bytes;
3. put the content-addressed blob through `StorageBackend`;
4. in one database transaction, record/reuse the `artifact` row, URL-level snapshot, sanitized
   provider receipt, outgoing-link observations, page completion, and progress event;
5. only then expose the snapshot to corpus freezing/extraction.

If step 3 or 4 fails while the worker still holds the result, retry persistence under the same
attempt; never re-fetch. If the process dies, recovery follows the attempt state and provider
reconciliation rules below.

### 14.2 Provenance chain

Every official-site claim must be traceable:

```text
claim
  -> corpus checkpoint
  -> URL-level page snapshot
  -> artifact row / immutable blob
  -> fetch attempt
  -> requested URL + redirect chain + final URL
  -> provider receipt + spend outcome
  -> crawl run + recon run + workspace
```

The claim's `source_url` is the snapshot's attributable final/requested URL under policy. An LLM may
not supply an arbitrary URL found in page text.

### 14.3 DSAR and retention

- Crawl runs, pages, observations, attempts, snapshots, checkpoints, and derived claims are
  workspace-scoped.
- Workspace/user erasure follows existing provisioning → workspace → artifact reachability.
- Shared content hashes do not imply shared tenant authorization; deleting one URL-level record
  cannot expose another workspace's artifact.
- Provider receipts are retained only as long as necessary for spend/replay/audit and are sanitized
  before storage.
- Public-page content reuse across workspaces is deferred until side-channel, authorization,
  retention, and deletion semantics receive a separate contract.

---

## 15. Paid-call crash ambiguity and retry policy

### 15.1 Attempt protocol

1. Persist `prepared` attempt with stable `operation_key`.
2. Fence-check lease generation.
3. Transition to `dispatched` immediately before the external call.
4. Call the provider once.
5. Persist receipt/result metadata as soon as returned.
6. Persist the artifact/snapshot under the same attempt.
7. Complete the page with the same generation.

### 15.2 Recovery matrix

| Durable state at recovery | Allowed action |
|---|---|
| `prepared`, never dispatched | Retry dispatch under a new lease generation using the same operation key. |
| `dispatched`, provider supports operation lookup | Reconcile by operation key/request ID; reuse result/receipt. |
| `dispatched`, no lookup and no terminal receipt | Mark `spend_unknown`; no automatic provider retry. |
| `provider_succeeded`, artifact missing, process alive/result retained | Retry persistence only. |
| `provider_succeeded`, process died, provider result retrievable | Reconcile and persist; no new fetch. |
| `provider_succeeded`, result unrecoverable | Quarantine as spend-confirmed/unknown; do not fabricate content. |
| `persisted`, page completion lost | Replay fenced DB completion from recorded refs; no provider call. |
| `retryable_no_spend` | Requeue within attempt/backoff policy. |
| `permanent`/policy/robots refusal | Terminal explicit empty/refusal; no retry. |

Provider fallback is allowed only by versioned policy and never bypasses an unresolved
`spend_unknown` attempt for the same page.

---

## 16. Concurrent extraction and claim materialization

### 16.1 Separation from crawling

The crawler ends at immutable corpus checkpoints. It does not write semantic Client-KB claims.
Materialization begins from a checkpoint and cannot fetch new URLs.

### 16.2 Fast extraction groups

Run bounded concurrent extraction jobs over page subsets chosen by deterministic category:

- product, value proposition, differentiators;
- pricing and proof;
- customers, ICP evidence, testimonials, delivered value, market reputation;
- company/founders/partners/integrations/trust context.

`openai/gpt-5.6-luna` is the proposed default model through the existing OpenRouter gateway;
`openai/gpt-5.6-terra` remains a configuration alternative/fallback. Model choice never affects
crawl identity.

### 16.3 Grounding and idempotency

- Each draft names one snapshot ID and attributable URL.
- Exact evidence span must occur in that snapshot's normalized content.
- Snapshot ID, content hash, extractor model, prompt/schema version, field key, and run identity
  form the extraction idempotency key.
- Concurrent extractors use independent DB connections; no SQLAlchemy connection is shared across
  tasks.
- Claim writes remain append-only and pass existing schema, source-tier, target-lock, reuse-scope,
  and verification rules.
- A partial extraction failure does not roll back other successfully materialized fields.
- No category extractor may turn a missing category into a guessed claim.

### 16.4 Source identity

The logical tier-2 source becomes **official-site evidence**, not the fetch vendor. The contract
freeze decides the migration from historical `source_key='firecrawl_site'` to a provider-neutral
logical key such as `official_site`:

- historical claims remain immutable;
- new claims record the logical official-site source;
- provider identity lives on the fetch attempt/snapshot;
- the waterfall still sees one registered tier-2 source;
- switching Firecrawl ↔ Scrapling changes composition, not `field_definition.tier_plan`.

The existing field-level resolver must stop initiating network calls after cutover. It either reads
the pinned corpus/materialization cache or is replaced by an equivalent logical official-site
materializer that preserves the waterfall/claim-write contract. C0 freezes this exact integration
before schema/code work.

---

## 17. Progress, API, and observability

### 17.1 Durable progress events

Add crawl-specific run events, reduced into the existing setup status rather than exposing provider
internals directly:

- `stage0.crawl.started`;
- `stage0.crawl.discovery_completed`;
- `stage0.crawl.page_started`;
- `stage0.crawl.page_fetched`;
- `stage0.crawl.page_refused`;
- `stage0.crawl.fast_checkpoint_frozen`;
- `stage0.crawl.extraction_started/completed`;
- `stage0.crawl.background_started/completed`;
- `stage0.crawl.failed`.

At-least-once events carry stable identities and sequence numbers. Read models reduce them
idempotently. The frontend continues to show clean business groups rather than one row per URL.

### 17.2 Suggested user-visible truth

- Discovering company pages.
- Scraping selected product and company pages (`n/m` when known).
- Understanding products and value.
- Finding pricing and customer proof.
- Validating sourced facts.
- Fast research complete; deeper research continuing.

No timer advances these labels. A stalled/retry/partial state comes from durable status.

### 17.3 Privacy-safe structured logs

Logs include:

- request/run/recon/workspace IDs;
- provider key and sanitized request ID;
- URL hash and host, not full query-bearing URLs;
- lease generation/outcome;
- graph depth/discovery channel/category;
- latency, bytes, page counts, cost, spend status, retry class;
- artifact/snapshot IDs and terminal outcome.

Logs never include tokens, cookies, authorization headers, raw page bodies, full provider receipts,
emails, or Clerk subjects. Traces follow the same rule.

### 17.4 Metrics

- frontier ready/leased/quarantined counts;
- claim latency and lease contention;
- pages and unique blobs per run;
- duplicate URL/content ratios;
- per-host/provider concurrency;
- provider latency/status/cost;
- spend-unknown count/age;
- fast checkpoint latency and category coverage;
- extraction success/empty/failure counts;
- background completion latency;
- stale completion rejection count.

---

## 18. Configuration

All knobs are validated settings and pinned to the crawl run:

- `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off|shadow|authoritative` (default `off`);
- `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_WORKSPACE_ALLOWLIST`;
- `CLUE_STAGE0_PAGE_FETCHER=firecrawl|scrapling`;
- `CLUE_STAGE0_CRAWL_MAX_DEPTH=2` (V1 refuses greater values);
- `CLUE_STAGE0_CRAWL_FAST_DEADLINE_SECONDS`;
- `CLUE_STAGE0_CRAWL_FAST_PAGE_CEILING`;
- `CLUE_STAGE0_CRAWL_TOTAL_PAGE_CEILING`;
- `CLUE_STAGE0_CRAWL_WORKER_CONCURRENCY`;
- `CLUE_STAGE0_CRAWL_PER_HOST_CONCURRENCY`;
- `CLUE_STAGE0_CRAWL_LEASE_TTL_SECONDS`;
- `CLUE_STAGE0_CRAWL_HEARTBEAT_SECONDS`;
- `CLUE_STAGE0_CRAWL_REQUEST_TIMEOUT_SECONDS`;
- `CLUE_STAGE0_CRAWL_MAX_RESPONSE_BYTES`;
- `CLUE_STAGE0_CRAWL_ALLOW_SUBDOMAINS`;
- `CLUE_STAGE0_CRAWL_ROBOTS_POLICY`;
- `CLUE_STAGE0_CRAWL_URL_POLICY_VERSION`;
- `CLUE_STAGE0_EXTRACTION_MODEL`.

Startup fails closed for invalid lease timing, unsupported provider selection, missing required
credentials, recursive-provider configuration, unsafe depth, or incompatible MIME/size settings.
Auth/session endpoints must remain available even when crawl composition is disabled.

---

## 19. Implementation sequence and checkpoints

Each checkpoint is independently reviewable. No later checkpoint starts before the previous gate is
green and its contract delta is recorded.

### C0 — Contract freeze and spike disposition

**Status: complete (2026-08-14).** The frozen DDL, enums, transition graphs, seams, source-key
migration, spike inventory, ownership map, and rollout contract are recorded in the
[C0 contract freeze](./FI-stage0-durable-official-site-crawl-C0-contract.md). Executable authority
lives in `clue_research.official_site` and
`tests/fixtures/official_site/c0_contract_fixture.json`. C0 made no migration, provider call, or
production cutover. C1 through C8 have since landed; C9 is the next implementation slice.

**Deliverables**

- Freeze domain types, enums, table names, transition graphs, fetcher/repository interfaces, and
  exact Stage-0 materialization seam.
- Inventory every current/uncommitted Firecrawl depth-crawl change.
- Retain only generally correct prerequisites (for example, SDK dependency and non-blocking leaf
  execution if separately justified); remove/quarantine provider-owned recursion and task-local
  crawl caching.
- Record the logical `official_site` source-key migration decision.
- Produce a file/ownership manifest and feature-flag rollout plan.

**Exit gate**

- Contract fixtures compile without provider/network/DB access.
- No unresolved question can change DDL or the `PageFetcher` result shape.
- Docs state current vs planned behavior consistently.

### C1 — Migration and repository primitives

**Status: complete (2026-08-14).** One reversible migration and the workspace-scoped PostgreSQL
repository implement the frozen ledger, atomic claiming, generation fencing, paid-call recovery,
and immutable checkpoints. C2 subsequently built on those tables without another migration.

**Deliverables**

- Add the crawl tables, enums, CHECKs, FKs, uniqueness rules, indexes, and reversible migration.
- Implement workspace-scoped repository reads/writes.
- Add atomic run creation, discovery upsert, claim-next, renew, fenced finish, and reclaim.
- Use DB time everywhere.

**Exit gate**

- One Alembic head; clean database upgrade/downgrade/upgrade.
- Ten concurrent claimers acquire one page once.
- Stale generation completion/renewal changes zero rows.
- Cross-workspace reads/writes fail closed.

### C2 — URL policy, graph, sitemap, and safety

**Status: complete (2026-08-14).** The binding implementation details, policy versions, additive
sitemap-source provenance correction, safety ceilings, verification matrix, and C3/C5 handoff are
recorded in the
[C2 policy contract](./FI-stage0-durable-official-site-crawl-C2-policy-contract.md).

**Deliverables**

- Implement versioned conservative fetch-key policy.
- Preserve observations/edges/aliases separately.
- Implement shorter-path re-expansion without refetch.
- Add bounded sitemap/robots parsing.
- Add domain, redirect, SSRF, MIME, size, and link ceilings.

**Exit gate**

- Full normalization/adversarial fixture matrix passes.
- `/pricing` and `/pricing/`, `/` and `/index.html`, semantic query variants remain distinct.
- Tracking/fragment/routing-fragment cases match the frozen policy.
- Sitemap-only pages retain unknown graph depth.
- External redirects/canonical hints/private-IP targets are refused.

### C3 — Single-page provider contract and adapters

**Status: complete (2026-08-14).** Firecrawl and Scrapling now implement the same frozen one-page
`PageFetcher` seam under provider-isolated adapter packages. Firecrawl uses only async `scrape` and
maps unresolved paid outcomes to `spend_unknown`; Scrapling uses manual redirects and C2-approved
DNS pinning at connect time. The shared conformance/static suite and exact capability/spend
decisions are recorded in the
[C3 provider contract](./FI-stage0-durable-official-site-crawl-C3-provider-contract.md). C3 does not
wire production crawling. C4 persists artifacts/recovery and C5 now supplies the coordinator;
production run/checkpoint/fleet activation remains C6.

**Deliverables**

- Implement `PageFetcher` and capability declaration.
- Implement Firecrawl single-page adapter.
- Implement Scrapling single-page adapter.
- Add provider conformance suite and SDK import guards.

**Exit gate**

- Both adapters pass one common suite.
- Call counters prove one URL request per invocation.
- Tests fail if Firecrawl crawl/map/recursive options appear.
- No provider name appears in coordinator branching.

### C4 — Durable acquisition, artifacts, and spend recovery

**Status: complete (2026-08-14).** The exact attempt ordering, PB-B2 artifact integration,
persistence-only replay, operation-lookup/quarantine policy, receipt privacy bounds, URL-level
provenance, DSAR reach, fault matrix, and C5 handoff are recorded in the
[C4 acquisition contract](./FI-stage0-durable-official-site-crawl-C4-acquisition-contract.md).
C4 itself does not schedule a crawl or enable production onboarding. C5–C8 subsequently added
scheduling, lifecycle, materialization, and operations without changing C4's acquisition contract.

**Deliverables**

- Implement prepared/dispatched/receipt/persistence attempt protocol.
- Integrate PB-B2 artifact storage and URL-level snapshots.
- Implement receipt lookup/reconciliation capabilities and `spend_unknown` quarantine.
- Add persistence-only retry and identical-content behavior.

**Exit gate**

- Provider success followed by DB/storage failure never triggers a second provider call while the
  result is retained/recoverable.
- Crash-after-dispatch ambiguity does not auto-retry.
- Identical content produces one blob and two provenance snapshots.
- Artifact/attempt/snapshot DSAR reach is proven.

### C5 — Concurrent crawl coordinator

**Status: complete (2026-08-14).** The bounded PostgreSQL worker pool, cross-run global/host
capacity, heartbeats, graceful stop, deterministic category quotas, no-refetch depth expansion,
fast/background fairness, recovery routing, and multiprocess fault evidence are recorded in the
[C5 coordinator contract](./FI-stage0-durable-official-site-crawl-C5-coordinator-contract.md).
C5 does not activate onboarding or own phase/checkpoint/fleet lifecycle; C6–C8 subsequently added
those layers without moving concurrency semantics out of C5.

**Deliverables**

- Implement bounded worker pool over PostgreSQL claims.
- Implement advisory-lock per-host capacity, heartbeat, reclaim, and graceful shutdown.
- Implement deterministic priority/category quotas and depth expansion.
- Ensure fast work outranks background claims without cancelling existing provider calls.

**Exit gate**

- Race/fault suite passes under multiple processes, not merely asyncio tasks.
- Provider concurrency never exceeds global/per-host configuration.
- Shorter-path discovery expands saved links once and never refetches.
- Background work cannot take a new claim while eligible fast work should win.

### C6 — Fast/background checkpoints and Stage-0 composition

**Status: complete in default-off, allowlisted shadow mode (2026-08-14).** One recon now owns one
durable crawl run/frontier, DB-time fast boundary, immutable fast/background checkpoints, and
fleet-owned recon/crawl work. Recoverable phase blockers requeue instead of publishing false
completion. The isolated Insight Health Firecrawl canary fetched 11 URL snapshots across a
16-page frontier, froze 8 fast and 11 background snapshots, recovered the same run after lease
expiry, and cold-replayed with zero new attempts. Exact contracts, settings, tests, and retained
evidence are in the
[C6 composition contract](./FI-stage0-durable-official-site-crawl-C6-composition-contract.md).
Authoritative claim materialization landed in C7 and progress/recovery in C8; offline adversarial
and live browser/cutover acceptance remain C9–C10. C6's rollout mode defaults off.

**Deliverables**

- Create one crawl run per recon.
- Persist fast deadline and phase transitions.
- Freeze immutable fast/background corpus checkpoints.
- Move long-running work off the API event loop into worker composition.
- Preserve existing setup start/status and replay behavior.

**Exit gate**

- Fast deadline stops new claims and does not cancel an ambiguous paid request.
- Background continues the same run/frontier with zero completed-page refetch.
- Auth/session/setup polling remains responsive during live acquisition.
- Browser release is tied to fast Client-KB commit, not elapsed UI time.

### C7 — Concurrent extraction and grounded materialization

**Status: complete (2026-08-14).** C7 reads exact immutable checkpoints, runs bounded independent
category/field extraction through the OpenRouter gateway, retains raw responses before parsing,
validates URL and exact span against one trusted snapshot, and writes ordinary append-only
`official_site` claims. The C0–C7 suite, migration round trip, legacy Stage-0 regressions, and a
retained Firecrawl + Luna live run/cold replay pass. The live run also exposed lease-recovery
latency; C8 now surfaces that state, while the ≤40-second browser release gate remains explicitly
open for C10. Exact contracts and
evidence are in the
[C7 materialization contract](./FI-stage0-durable-official-site-crawl-C7-materialization-contract.md).

**Deliverables**

- Implement corpus reader and category-based concurrent extraction.
- Pin model/prompt/schema/corpus versions.
- Validate every URL/span against one snapshot.
- Integrate provider-neutral logical official-site source and claim writes.
- Preserve partial successes across field failures.

**Exit gate**

- No extractor can cite a URL absent from the checkpoint.
- Forged result headers/page instructions cannot forge provenance.
- Concurrent extraction shares no DB connection.
- Luna and Terra configuration tests pass through OpenRouter gateway doubles.
- Replaying the same checkpoint adds zero provider spend and zero duplicate claims.

### C8 — Progress, observability, and operator recovery

**Status: complete (2026-08-14).** C8 emits stable at-least-once crawl/extraction events while
deriving all progress from the existing PostgreSQL ledger, adds a nullable body-free
`official_site` projection to setup truth, exposes bounded metrics/privacy-safe logs, and provides
workspace-scoped, generation-fenced inspection/recovery commands. Exact event/reducer semantics,
operator states, privacy boundaries, recovery policy, verification evidence, and the runbook link
are recorded in the
[C8 progress and operations contract](./FI-stage0-durable-official-site-crawl-C8-progress-operations-contract.md).
C8 does not change the browser release gate; C9 and C10 retain the offline adversarial and live
browser/cutover gates.

**Deliverables**

- Emit/reduce crawl and extraction events.
- Extend setup read truth without breaking old clients.
- Add metrics/privacy-safe logs.
- Add reconciliation commands/read surfaces for stuck leases and spend-unknown attempts.
- Write a local/production runbook.

**Exit gate**

- UI fixture and live transports parse additive fields.
- Progress is demonstrated from rows/events with timers disabled.
- Operator can distinguish queued, leased, provider-active, spend-unknown, persisted, extracted,
  partial, and completed states without reading raw bodies.

### C9 — Offline adversarial acceptance and migration gate

**Status: complete (2026-08-14).** C9 maps all 53 §20 rows and nine provider-crash boundaries to
executable tests, closes recovered-result validation/receipt/provenance and complete-retention-reach
gaps found by adversarial review, and passes the hardened 200-test C0–C9 target on a fresh isolated
database. Alembic up/down/up, the sole-head check, Ruff, mypy, all import contracts, and the full
frontend test/lint/build stack pass. The repository-wide monolithic DB baseline remains red for
independently reproduced agent-resource/test-fixture and shared-schema isolation defects; those
failures are separated and explained in the
[C9 offline acceptance record](./FI-stage0-durable-official-site-crawl-C9-offline-acceptance.md).
C10 remains the live provider/browser/cutover gate.

**Deliverables**

- Execute the complete matrix in §20 against a fresh isolated PostgreSQL database.
- Run provider fakes for every crash boundary.
- Run frontend tests/lint/build and backend unit/DB/static/type/import gates.
- Run Alembic smoke and one-head checks.

**Exit gate**

- Zero unexplained failures.
- Any shared-DB baseline contamination is separated from branch regressions.
- A critical/adversarial review has no unresolved P1/P2 findings.

### C10 — Live provider and browser acceptance

**Deliverables**

- Fresh named database and separate artifact/log root retained for review.
- Real Clerk identity → internal user/workspace/brand provisioning proof.
- Real Firecrawl single-page concurrent run; repeat with Scrapling where environment permits.
- Browser/API/log/database/artifact/provider-receipt evidence correlated by IDs.
- Provision and crawl replay/idempotency proof.

**Exit gate**

- Fast release target measured at ≤40 seconds under the agreed test site/provider conditions, or a
  typed evidence-backed exception is reported rather than hidden.
- Required fast categories have honest coverage/absence evidence.
- Background completes/resumes the same frontier.
- No URL is provider-fetched twice without an explicit permitted new attempt.
- Snapshot URLs/content hashes/claims/costs reconcile.
- Both databases and artifact roots remain untouched until review sign-off.

---

## 20. Acceptance matrix

### 20.1 Frontier and deduplication

- Ten workers discover/claim one normalized fetch key; one provider call occurs.
- Duplicate link/sitemap observations retain provenance but create one page node.
- Hash collision safety compares full fetch keys, not hash alone.
- A fetched page discovered later at a shorter depth expands saved links without refetch.
- Same URL in a later crawl run is independently eligible; run-scoped dedupe does not suppress
  legitimate freshness.
- Background reuses all fast terminal pages.

### 20.2 Lease fencing and crashes

- Stale lease renewal rejected.
- Stale completion/failure/persistence publication rejected.
- Lease expiry with no dispatch safely reclaims.
- Lease expiry after dispatch enters reconciliation/spend-unknown, not blind retry.
- Worker dies after blob put but before DB commit; recovery never issues a provider call solely to
  repair persistence.
- Worker dies after page commit but before task acknowledgement; replay returns stored refs.
- Heartbeat configuration violating `2h < ttl` fails construction.

### 20.3 URL and graph correctness

- Relative, protocol-relative, IDNA, percent-encoding, default-port, path-case, and query fixtures.
- `/pricing` vs `/pricing/`; `/` vs `/index.html`; ordered/repeated semantic queries remain distinct.
- Ordinary anchors vs hash-router fragments follow the pinned policy.
- Sitemap discovery keeps `graph_depth=NULL`.
- Link depth never exceeds two.
- Cross-domain canonical hint does not merge or fetch.
- Redirect chain preserves every hop and refuses an off-domain/private target.
- Redirect/canonical loops terminate explicitly.

### 20.4 Safety

- IPv4/IPv6 private, loopback, link-local, reserved, metadata, credential-bearing, and non-HTTP
  targets refused.
- DNS rebinding defense tested for the local fetcher.
- Robots refusal is terminal and visible.
- Unsupported MIME, oversized decompressed body, redirect overflow, sitemap bomb, and excessive
  outgoing links are bounded.
- Provider-returned final URL/content cannot bypass policy.

### 20.5 Provider and spend

- Firecrawl and Scrapling pass identical conformance cases.
- Firecrawl recursive methods/options are absent.
- Provider 429/5xx/timeouts map to the correct retry/spend class.
- Provider succeeds and charges, then worker crashes before completion: reconcile/reuse or
  quarantine; never blind retry.
- Provider success followed by persistence failure retries persistence only.
- Confirmed no-spend failure may retry under policy.
- Sanitized receipts contain no secrets/raw bodies.

### 20.6 Artifacts and provenance

- Identical bytes from two URLs produce one blob and two snapshots.
- Different bytes under canonical hints remain distinct.
- Every claim resolves to checkpoint → snapshot → artifact → attempt → receipt.
- Evidence span is exact in the cited snapshot.
- A page-injected fake URL/header cannot become claim provenance.
- Workspace isolation, retention, and erasure cover every new table/blob/reference.

### 20.7 Fast/background and progress

- Fast deadline stops claims at DB time.
- In-flight ambiguous paid request is not cancelled/requeued.
- Fast checkpoint is immutable after background pages arrive.
- Background cannot starve ready fast claims.
- Background resumes after process restart.
- Setup status remains responsive during fetch/extraction.
- Every visible progress change corresponds to committed state.
- Fast partial/failure and background failure have honest recovery behavior.

### 20.8 Extraction

- Category jobs run concurrently under a bound.
- Missing categories remain empty.
- One category failure does not erase other fields.
- Model/prompt/schema/corpus replay is idempotent.
- Luna/Terra selection is config-only.
- No pre-confirmation source exceeds tier three.

---

## 21. Rollout and rollback

### 21.1 Feature rollout

1. Land schema and dark repository primitives with crawl flag off.
2. Run offline fault suite and local Scrapling canary.
3. Run isolated Firecrawl canary with no user release dependency.
4. Enable new acquisition for a named workspace allowlist.
5. Compare coverage, latency, duplicate ratio, spend, and claim provenance against the old path.
6. Enable Stage-0 fast release on the new path only after live exit gates pass.
7. Remove network acquisition from the historical field-level Firecrawl resolver.
8. Retain a rollback flag for one release window; remove it once replays/migrations are proven.

### 21.2 Rollback rules

- Rollback changes composition, not durable history.
- Never delete/mutate crawl rows to make the old path believe work did not occur.
- Do not roll back into provider-owned recursive crawling.
- A crawl started on the new path either completes/reconciles under its pinned policy or remains
  explicitly suspended/quarantined; another implementation does not steal it.
- Schema downgrade is tested but not run against retained acceptance evidence.

---

## 22. Documentation and decision checkpoints

At each checkpoint update:

- this plan's status and decision ledger;
- `docs/specs/README.md` index;
- M4.5/M5.1 cross-references when the capability actually changes their current contract;
- `docs/specs/FI-onboarding-contract-gap-review.md` ratification log;
- `apps/frontend/docs/api-contracts/onboarding.md` current-vs-planned behavior;
- `_memory/` operational handoff;
- runbook and env examples when settings land.

Do not document a future checkpoint as shipped. Every claim of live readiness must cite browser,
API, logs, database, artifact, and provider-receipt evidence from the same isolated run.

---

## 23. Risks and explicit follow-ups

| Risk | Required treatment |
|---|---|
| PostgreSQL frontier contention | Measure claim latency/advisory-lock contention before adding an accelerator. |
| Provider call has no lookup/idempotency | Quarantine ambiguous dispatch; no automatic duplicate spend. |
| 40-second target vs slow/large sites | Freeze best completed fast corpus; background continues; report partial truth. |
| Sitemap-only category page has unknown depth | Fetch by explicit policy if needed; do not label depth; do not expand until link depth exists. |
| Canonical/redirect equivalence mistakes | Preserve observations and verify; content dedupe instead of premature URL merge. |
| Hosted provider SSRF behavior differs | Coordinator preflight + provider threat controls + final URL validation; fail closed. |
| API process still drives long work | Cut over to worker composition before live flag enablement. |
| Model extraction bottlenecks fast lane | Bounded category concurrency, corpus/token caps, measured fallback; never loosen grounding. |
| Historical `firecrawl_site` claims | Keep immutable; migrate only new logical source writes. |
| Shared public-page reuse temptation | Defer until tenancy/side-channel/retention contract is approved. |

No Redis/in-memory scheduler, Temporal migration, cross-tenant cache, or autonomous crawl agent may
be added as a “small optimization” inside these checkpoints. Each requires evidence and a new
decision record.

---

## 24. Definition of done

This capability is done only when all are true:

- the C0–C10 exit gates pass;
- one reversible migration leaves one Alembic head;
- Postgres alone provides correct concurrent claiming and recovery;
- lease-generation fences reject stale writes at every worker-owned transition;
- Firecrawl and Scrapling are single-page, conformant, swappable fetchers;
- Clue owns link discovery, normalization, depth, priority, dedupe, safety, and retries;
- fast/background share one run/frontier and two immutable corpus checkpoints;
- fast release is truthful and measured against the 40-second target;
- background resumes without re-fetching completed URLs;
- content reuse preserves all URL-level provenance;
- paid-call crash ambiguity cannot cause blind retry;
- every claim is grounded in a durable attributable snapshot;
- progress is durable rather than timer-driven;
- DSAR, privacy-safe logs, metrics, and operator reconciliation are complete;
- offline adversarial review and live isolated browser acceptance have retained evidence;
- docs distinguish current, planned, and live behavior accurately;
- the implementation is locally committed in coherent checkpoints and not pushed without explicit
  founder instruction.

Until then, the architecture is approved but the capability is **not merge-ready as a completed
durable crawler**.
