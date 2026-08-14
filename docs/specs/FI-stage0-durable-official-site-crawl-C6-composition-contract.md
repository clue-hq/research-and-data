# FI Stage-0 durable official-site crawl — C6 composition contract

**Status:** implemented and accepted in shadow mode on 2026-08-14

**Authority:** C6 execution/composition detail under
[`FI-stage0-durable-official-site-crawl-plan.md`](./FI-stage0-durable-official-site-crawl-plan.md)

**Next authority:** C7 owns checkpoint-to-claim extraction/materialization and the authoritative
cutover.

## 1. Outcome and scope

C6 makes C1–C5 executable as one durable Stage-0 capability without changing the currently
authoritative onboarding Client-KB path. It adds:

- exactly one official-site crawl run per `(workspace_id, recon_run_id)`;
- persisted database-time fast deadlines and phase transitions;
- immutable fast and background corpus checkpoints;
- a fleet-owned Stage-0 recon task and a separately leased official-site crawl task;
- default-off, workspace-allowlisted shadow composition for Firecrawl or Scrapling;
- bounded robots/sitemap seed discovery at the API composition root;
- recovery-aware phase publication: unresolved leased/provider/reconciliation/persistence work
  requeues and cannot be reported as complete;
- a retained live Firecrawl canary and cold-replay proof.

C6 does **not** extract claims from a checkpoint, replace the legacy `official_site` resolver, or
make the durable crawl authoritative. Those are C7 responsibilities. The browser continues to be
released only after the existing fast Client-KB commit is visible; C6 shadow acquisition starts
after that same durable fact and cannot delay or counterfeit release.

## 2. User-visible and process flow

1. `POST /stage0/setup` persists the onboarding input and enqueues a reference-only
   `stage0_recon` task. The request does not execute recon on the API event loop.
2. The fleet task rehydrates the workspace-owned input and drives one legacy recon lane per claim.
   It requeues until legacy fast/background work reaches its existing terminal state.
3. As soon as the committed legacy fast Client-KB version exists, the fleet enqueues one
   `official_site_crawl` task for the same recon. The payload contains only workspace/recon IDs.
4. The crawl task rehydrates the company website and tenancy from PostgreSQL, then opens or
   replays the single run pinned to the recon.
5. The C5 coordinator claims and fetches single pages concurrently. At the database fast deadline,
   new fast claims stop. Already-dispatched work is awaited; it is never cancelled merely to meet
   the UI deadline.
6. The fast snapshot set freezes once. Late safe completions remain on the same frontier and can
   enter only the background checkpoint.
7. Background resumes the same run. Completed pages are never fetched again. Recoverable blockers
   return `recovery_pending` with `requeue=true`; the background checkpoint and completed status
   cannot publish early.
8. Background freezes once after the frontier settles. Any later replay returns the same run and
   checkpoint IDs and performs zero provider acquisition.

## 3. Durable transition contract

```text
queued
  -> fast_active
  -> fast_closing          (atomic deadline close + immutable fast checkpoint)
  -> fast_complete         (authoritative mode additionally requires fast materialization)
  -> background_active
  -> completed             (immutable background checkpoint published)
```

The database owns time. `fast_claim_deadline_at` is written at run creation and remaining time is
computed with PostgreSQL `now()`. A process restart therefore cannot restart or extend the fast
window.

At the fast boundary, queued/delayed no-spend work may continue in background, but these states
block publication: `leased`, `provider_started`, `reconciliation_pending`, and
`persistence_pending`. At the background boundary, `queued` and `retry_wait` block as well. A C5
worker/fence error with no durable recovery state is a hard error; an associated durable blocker
is a requeue, never a false success.

`fast_closing` is cold-resumable. It permits C4 persistence/reconciliation claims but C1 refuses a
new ordinary fast URL claim. This lets a replacement worker publish retained bytes and complete
the fence without changing the already-frozen fast corpus.

## 4. Checkpoint and materialization boundary

Each phase has at most one version-1 checkpoint per crawl run. Its ordered snapshot IDs and
`snapshot_set_sha256` are immutable. Checkpoint replay returns the existing row.

Shadow mode records acquisition/checkpoint evidence but invokes no model and writes no Client-KB
claims. Authoritative mode is deliberately fail-closed at composition until a C7
`OfficialSiteCorpusMaterializer` is supplied. When C7 lands, `fast_complete` must remain behind the
successful fast materialization commit; elapsed time or a frozen crawl checkpoint alone can never
release the browser.

The configured extraction model defaults to `openai/gpt-5.6-luna`, but C6 only pins the future C7
request metadata. C6 does not call Luna, Terra, or any other model.

## 5. Provider and safety composition

Provider selection occurs only in `clue_api.official_site_crawl_wiring`. The lifecycle and
coordinator receive `PageFetcher`; neither branches on Firecrawl/Scrapling.

- Firecrawl uses the C3 single-page `scrape` adapter only.
- Scrapling uses the C3 DNS-pinned single-page transport.
- Robots and sitemap control documents use bounded DNS-pinned local transport, independent of the
  selected page provider.
- The common apex-to-`www` redirect is allowed only when the run-pinned subdomain policy is true.
  Arbitrary external redirects remain refused.
- A high-fanout page that reaches the run page ceiling still commits its snapshot. Excess URLs are
  retained as refused URL observations with `overall_page_ceiling_reached`; they cannot roll back
  paid success or expand the frontier.

Provider exceptions after dispatch remain `spend_unknown`. Without a receipt-lookup capability,
recovery quarantines them and does not call the provider again. Pre-dispatch leases are safely
reclaimable after expiry.

## 6. Fleet and privacy boundary

Migration `93113e83bf2f` appends `stage0_recon` and `official_site_crawl` to the shared fleet task
kind. The migration is reversible and refuses downgrade while either task kind is retained.

Both task payloads are reference-only. They contain no URL, page body, Clerk token, email,
provider key, or raw provider receipt. Workers rehydrate trusted workspace-scoped state from
PostgreSQL. Completion/recovery logs contain workspace/recon/crawl/checkpoint IDs, phase, outcome,
and aggregate counts only.

The setup API retains its existing start/status/replay response vocabulary. Focused unit tests may
inject the old in-process driver explicitly, but production app construction always supplies the
fleet enqueuer.

## 7. Rollout settings

All settings are default-off. Enabling either shadow or authoritative mode requires a non-empty
workspace allowlist.

```dotenv
CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off
CLUE_STAGE0_OFFICIAL_SITE_CRAWL_WORKSPACE_ALLOWLIST=[]
CLUE_STAGE0_PAGE_FETCHER=firecrawl
CLUE_STAGE0_CRAWL_MAX_DEPTH=2
CLUE_STAGE0_CRAWL_FAST_DEADLINE_SECONDS=40
CLUE_STAGE0_CRAWL_FAST_PAGE_CEILING=12
CLUE_STAGE0_CRAWL_TOTAL_PAGE_CEILING=100
CLUE_STAGE0_CRAWL_WORKER_CONCURRENCY=8
CLUE_STAGE0_CRAWL_PER_HOST_CONCURRENCY=3
CLUE_STAGE0_CRAWL_LEASE_TTL_SECONDS=90
CLUE_STAGE0_CRAWL_HEARTBEAT_SECONDS=20
CLUE_STAGE0_CRAWL_REQUEST_TIMEOUT_SECONDS=30
CLUE_STAGE0_CRAWL_MAX_RESPONSE_BYTES=5000000
CLUE_STAGE0_CRAWL_ALLOW_SUBDOMAINS=false
CLUE_STAGE0_CRAWL_ROBOTS_POLICY=respect
CLUE_STAGE0_CRAWL_URL_POLICY_VERSION=official-site-url-v1
CLUE_STAGE0_EXTRACTION_MODEL=openai/gpt-5.6-luna
```

Rollout order is `off` -> one named shadow workspace -> measured shadow cohort -> C7
materialization verification -> explicit authoritative allowlist. Authoritative startup before C7
fails. Firecrawl startup without its API key fails. No wildcard allowlist exists.

## 8. Verification and retained live evidence

Offline/database verification covers:

- deadline stop, in-flight non-cancellation, late-result checkpoint separation, and cold replay;
- materialization-before-fast-complete ordering;
- recoverable worker errors refusing checkpoint/terminal publication;
- one-run replay and DB-time deadline persistence;
- immutable checkpoint replay and cross-workspace fail-closed reads;
- setup polling responsiveness while the fleet enqueuer is blocked;
- reference-only task payloads and fleet task-kind guards;
- default-off/allowlist/credential/authoritative composition refusal;
- bounded robots/sitemap discovery with unknown sitemap graph depth;
- page-ceiling overflow provenance without snapshot rollback;
- the complete C0–C5 official-site regression suites.

The retained 2026-08-14 Firecrawl shadow canary used:

- isolated database `clue_c6_official_site_20260814`;
- isolated artifact root `/private/tmp/clue-c6-official-site-20260814-live-artifacts`;
- target `https://insighthealth.ai/`;
- depth 2, total ceiling 16, fast ceiling 8, four workers, per-host capacity 2, and 40-second
  deadline.

Final evidence for crawl run `94b425e6-f252-4c34-841b-a478c3467cc3`:

| Evidence | Result |
|---|---:|
| crawl runs for recon | 1 |
| durable pages | 16 |
| fetched URL snapshots | 11 |
| unique content blobs | 10 |
| fast checkpoint snapshots | 8 |
| background checkpoint snapshots | 11 |
| provider attempts | 16 |
| ambiguous attempts safely quarantined | 5 |
| provider-attempt delta on cold replay | 0 |
| cold replay duration | 0.010 s |
| final status | `completed` |

The first process stopped honestly at `background_active` with one unexpired pre-dispatch lease.
After expiry, the same run reclaimed it, fetched one additional page, froze the background corpus,
and completed. Five dispatched Firecrawl exceptions had no receipt/request ID, remained
`spend_unknown`, and were quarantined without blind retry. This is expected conservative recovery,
not five confirmed charges.

## 9. C6 exit-gate verdict and residual boundary

C6's implementation gate is accepted:

- the fast deadline stops new claims and never cancels an ambiguous paid request;
- background continues the same run/frontier with zero completed-page refetch;
- setup/auth/status polling stays on the API loop while recon/crawl work runs in the fleet;
- browser release remains tied to the committed legacy fast Client-KB version;
- live Firecrawl acquisition, durable recovery, checkpointing, and cold replay are proven.

This is **not** a completed durable-crawler product release. C7 must materialize grounded claims
from checkpoints and prove authoritative browser/API/database/artifact/provider lineage before the
flag can move beyond shadow. C8–C10 retain progress/observability, DSAR/retention, and final rollout
gates from the parent plan.
