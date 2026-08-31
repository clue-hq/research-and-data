# Stage-0 durable official-site crawling — C4 acquisition and recovery contract

**Status:** C4 implemented and verified; C5 coordination is complete and C6 composition is next

**Parent:** [durable official-site crawl implementation plan](./FI-stage0-durable-official-site-crawl-plan.md)

**Depends on:** C0 frozen seams, C1 PostgreSQL ledger, C2 content/link policy, C3 single-page
provider adapters, and PB-B2 `StorageBackend`

---

## 1. Outcome and scope boundary

C4 implements the durable boundary around one already-approved page request:

```text
ordinary CrawlLease
  -> prepared attempt (PostgreSQL)
  -> dispatched attempt (PostgreSQL, before provider I/O)
  -> exactly one PageFetcher.fetch_one call
  -> sanitized body-free result/receipt (PostgreSQL)
  -> workspace-scoped content-addressed blob (PB-B2)
  -> URL-level page snapshot (PostgreSQL)
  -> fetched page completion + queued link expansion (one PostgreSQL transaction)
```

`DurablePageAcquirer` owns that protocol. `OfficialSiteArtifactStore` owns exact-byte capture,
artifact attachment/reload, and reference-only workspace/run reachability. Both depend on frozen
provider-neutral protocols; neither imports or branches on Firecrawl, Scrapling, or another
provider package.

C4 does **not** implement the crawl worker pool, global/per-host concurrency, depth expansion,
frontier scheduling, heartbeat loop, fast/background lifecycle, Stage-0 claim materialization,
projection/API surfaces, or production feature-flag composition. No onboarding behavior changes in
this slice. C5 consumes this one-page operation from bounded PostgreSQL claims.

## 2. Durable attempt and persistence protocol

For a new ordinary lease, acquisition executes these ordered committed boundaries:

1. `begin_attempt` persists `prepared` with the stable caller-generated `operation_key`.
2. `mark_attempt_dispatched` atomically changes the attempt to `dispatched` and the page to
   `provider_started` before external I/O.
3. Exactly one `PageFetcher.fetch_one` call is made. There is no SDK- or C4-owned retry loop.
4. The receipt is recursively sanitized and bounded; `record_provider_result` stores only the
   body-free `ProviderResultMetadata` and changes a success to
   `provider_succeeded + persistence_pending`.
5. Exact successful bytes are SHA-256 content-addressed as
   `<workspace_id>/<content_sha256>`. The shared PB-B2 artifact row is upserted, the blob is put if
   absent, the stored bytes are read and hash/size/scope verified, and the attempt is attached to
   the artifact.
6. `persist_snapshot` writes or reuses one immutable URL-level snapshot and marks the attempt
   `persisted`.
7. `complete_page` publishes that exact snapshot, clears its acquisition lease, and creates one
   snapshot-keyed `official_site_link_expansion` row in the same transaction. Discovery writes do
   not run inside page completion.

The attempt row never stores page bytes or outgoing-link bodies. The artifact row owns bytes and
content identity; the page snapshot owns requested/final URL, redirect, provider, fetch time,
MIME/status, and attempt provenance. The bounded expansion row retains the exact outgoing-link
observations needed for provider-free retry. Two URL snapshots may therefore cite one artifact.

PB-B2 is used without changing its storage abstraction:

- identical bytes deduplicate inside one workspace;
- identical bytes never deduplicate across workspaces;
- filesystem/S3 choice remains injected configuration;
- every artifact row/blob is verified before a snapshot can cite it;
- rolled-back blob puts remain content-addressed/orphan-safe for the existing PB-B2 sweeper.

## 3. Persistence-only recovery

A provider success is not fetched again merely because storage or PostgreSQL persistence failed.
There are three recovery paths:

### 3.1 Same-process retained bytes

After result metadata commits, a storage/snapshot error raises
`AcquisitionPersistencePendingError` containing the already-returned typed result. Calling
`retry_persistence` reuses those bytes and the same attempt. It cannot invoke `fetch_one`.

### 3.2 Fresh-process staged blob

Once the artifact row/blob and attempt reference commit, lease expiry releases the
`persistence_pending` page. `claim_persistence` obtains a fresh page generation and
`resume_persistence` reloads and verifies the staged PB-B2 blob. It reconstructs the body-free
metadata from the attempt, deterministically re-extracts HTML link observations, and finishes the
snapshot/page without provider I/O.

### 3.3 Snapshot committed, completion lost

C4 closes an uncovered C1 crash boundary: `claim_persistence` also admits an attempt already in
`persisted` when its page remains `persistence_pending`. `persist_snapshot` returns the existing
immutable snapshot, then the replacement worker replays only the atomic page-completion/expansion-
enqueue transaction. No duplicate snapshot, expansion job, or provider call is created.

### 3.4 Acquisition/expansion boundary amendment (2026-08-15)

Link expansion is no longer a pre-completion hook. A durable snapshot is usable by the fast corpus
as soon as page completion and expansion enqueue commit. Expansion has a separate generation-
fenced lease, heartbeat, retry/backoff, and terminal partial-failure state. An expansion error can
reduce recursive coverage, but it cannot relabel a captured page as `persistence_pending` or force
the original provider request to run again.

If a recorded provider success has neither caller-retained bytes nor a verified attached blob,
recovery cannot reconstruct content. It quarantines the attempt/page with
`provider_success_artifact_unrecoverable`; it never fabricates content and never redispatches.

## 4. Dispatch ambiguity and spend reconciliation

An exception/cancellation/process loss after the dispatched commit deliberately leaves the
attempt at `dispatched`. C1 expiry reclamation moves it to
`spend_unknown + reconciliation_pending`. C4 then permits only:

- `ProviderOperationLookup.lookup_operation` when the injected provider capability declares
  operation lookup. This is receipt/status recovery for the existing operation, not a page fetch.
  A recovered success follows the normal artifact/snapshot path; recovered no-spend/failure state
  follows the frozen C1 transition matrix.
- quarantine with `provider_operation_lookup_unavailable` when lookup is absent, unsupported, or
  belongs to another provider.

The current C3 Firecrawl and Scrapling adapters both declare no operation lookup. Therefore an
ambiguous current-provider dispatch is quarantined and retains `spend_unknown` for cost/operator
audit. This is intentionally stricter than a retry. A future adapter may add the capability only
behind the same lookup seam and common recovery suite.

Recovery methods accept `PersistenceClaim` or `ReconciliationClaim`; neither claim authorizes a
new acquisition dispatch. Provider fallback may not bypass an unresolved attempt.

## 5. Receipt privacy and provenance

Before any provider receipt reaches PostgreSQL, C4:

- recursively removes credential/body-shaped keys, including authorization, tokens, secrets,
  cookies, headers, raw responses, HTML/markdown/content, and `*body` fields;
- caps nesting depth, collection size, key length, and string length;
- replaces a still-oversized optional receipt with a body-free omission marker instead of turning
  a known success into spend ambiguity.

Provider request ID, requested/final URL, status, cost, spend classification, and retry class stay
in typed columns. Raw page bytes stay only in governed artifact storage.

The C4 provenance chain now reaches:

```text
crawl run -> page -> attempt -> URL snapshot -> artifact row -> immutable blob
```

`OfficialSiteArtifactStore.evidence_reach` returns sorted reference-only run, attempt, snapshot,
and artifact sets scoped by workspace and optional crawl run. This is the C4 DSAR/retention
composition seam. It fails closed across workspaces; physical erasure continues through PB-B2's
existing artifact lifecycle after the owning workspace/claim erasure path drops live references.
C7 later adds checkpoint/claim edges to the same chain.

## 6. Acceptance and review record

The C4 suite proves:

- successful acquisition creates one durable attempt, blob, snapshot, and page completion;
- a storage put failure retries persistence only; provider call count remains one;
- a PostgreSQL snapshot failure retries persistence only from the staged blob;
- a snapshot commit followed by lost page completion reuses that snapshot under a fresh fence;
- a success whose body was never staged, or whose staged blob is missing/erased/tampered,
  quarantines without refetch; transient storage-backend failures remain retryable persistence
  work rather than being misclassified as permanent content loss;
- a post-dispatch crash without operation lookup quarantines and preserves `spend_unknown`;
- a lookup-capable provider fake recovers the original operation, persists it, and never calls the
  page fetcher again;
- every non-success lookup classification (retryable-no-spend, ambiguous, permanent,
  robots-refused, and policy-refused) follows its durable transition without redispatch;
- identical bytes from two URLs produce one workspace artifact/blob and two URL snapshots;
- sanitized durable receipts contain cost/request references but no credentials or bodies;
- workspace/run evidence reach includes exactly the attempt/snapshot/artifact chain and excludes a
  neighboring workspace;
- C4 recovery source contains no provider-package imports or provider-name branching.

The complete C0-C4 official-site suite passes 117 tests on the separate fresh isolated database
`clue_c4_official_site_20260814_focused`; the 14 focused C4 tests pass independently. Live evidence
was not reused as a test database. The untouched database
`clue_c4_official_site_20260814_0628` remains retained with two live single-page canaries and the
artifact root remains at `/private/tmp/clue-c4-official-site-20260814-0628-live-artifacts`:

| Provider | Run → attempt → snapshot | Durable outcome | Blob proof |
|---|---|---|---|
| Firecrawl | `9886bc95-bde4-41ed-adb2-0bdc26954c37` → `20e3a4d3-cb7d-432b-9b7d-995f38c137be` → `15d3f247-7ff7-4f3c-abe8-612135c7ddbe` | one call; `persisted/fetched`; `spend_confirmed`; provider request ID present; receipt keys are only `cache_state`, `credits_used`, `scrape_id` | `7f8c26a916385719500fb8b9d2f7412826aae41d075ffb8e25d37678abd687aa`; stored bytes re-hash exactly |
| Scrapling | `40ed72ce-69d1-404c-a9cc-5724772a73d6` → `a839ff46-0c97-410b-b140-2da00f341d5a` → `b4b2ebb8-9ca6-4175-97da-90289068c4fd` | one call; `persisted/fetched`; `no_spend`; no provider receipt/ID | `ff67a9d764d6a2367a187734e697f6a53217db9a21c101d410a113ca871a299d`; stored bytes re-hash exactly |

The one-head downgrade/upgrade smoke, repository-wide Ruff/mypy/import-linter gates, provider-free
tests, and the final critical sweep are recorded in the C4 `_memory` note. The sweep removed a
redundant completion flag and unused recovery reads, and distinguished permanent blob loss from a
transient storage outage; it found no unresolved P1/P2 issue in C4.

## 7. C5 handoff (fulfilled)

C5 fulfills the following handoff in the
[C5 coordinator contract](./FI-stage0-durable-official-site-crawl-C5-coordinator-contract.md):

C5 now:

- generates stable operation keys before calling `DurablePageAcquirer.acquire`;
- constructs requests only after C2 preflight/robots approval;
- maintains the lease heartbeat and never cancels an already-dispatched paid call merely because
  the fast claim deadline elapsed;
- routes ordinary, persistence, and reconciliation claims to their distinct C4 methods;
- applies C2 post-response validation and link ceilings before durable discovery insertion;
- accepts injected fetcher/lookup implementations and uses capabilities, never provider-name
  conditionals; C6 owns registry selection;
- leaves stuck quarantine/spend-unknown work for C8 operator surfaces instead of redispatching it.

C5 may not weaken C4 by adding an in-memory retry loop, calling `fetch_one` from recovery, storing
page bodies in PostgreSQL, or collapsing URL snapshots when content hashes match.
