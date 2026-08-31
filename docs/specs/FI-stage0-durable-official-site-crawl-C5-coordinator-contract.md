# Stage-0 durable official-site crawling — C5 coordinator contract

**Status:** C5 implemented and verified; C6 fast/background lifecycle composition is next

**Parent:** [durable official-site crawl implementation plan](./FI-stage0-durable-official-site-crawl-plan.md)

**Depends on:** C0 frozen seams, C1 PostgreSQL ledger, C2 URL/graph/safety policy, C3 one-page
fetchers, and C4 durable acquisition/recovery

---

## 1. Outcome and scope boundary

C5 implements one provider-neutral, bounded worker pool over the PostgreSQL frontier:

```text
phase worker
  -> persistence recovery claim, if any
  -> link-expansion claim, if any
  -> reconciliation claim, if any
  -> ordinary fast/background page claim
  -> C2 DNS/IP preflight
  -> bounded robots authorization
  -> one C4 durable acquisition operation
  -> C2 redirect/content/link validation
  -> fenced page completion + expansion enqueue

independent expansion worker
  -> durable link/alias observations and depth expansion
  -> fenced expansion completion/retry/partial failure
```

`ConcurrentCrawlCoordinator` owns logical workers, heartbeats, graceful stopping, safety
composition, recovery routing, and replay-safe link discovery. `PostgresCrawlRepository` remains
the only frontier and scheduling authority. There is no in-memory/Redis scheduler, task-local URL
map, provider recursion, or provider-name branch.

C5 does **not** create the crawl run from onboarding, close the fast phase, freeze corpus
checkpoints, launch the background phase, register the work with the durable fleet, materialize
Client-KB claims, emit product progress projections, or enable the new path in production. Those
are C6-C8 boundaries. The existing Stage-0 production resolver remains authoritative.

## 2. PostgreSQL claiming and capacity

Ordinary and reconciliation claims use this transaction order:

1. acquire `official-site:claim:global` with `pg_advisory_xact_lock`;
2. reclaim expired work using database `now()`;
3. validate the run state/deadline and candidate phase;
4. count live provider-bearing leases across **all** workspaces and crawl runs;
5. acquire `official-site:claim:host:<normalized-host>` after the global lock;
6. count live leases for that host across all runs;
7. select/update one eligible row under `FOR UPDATE SKIP LOCKED`;
8. increment `lease_generation`, stamp owner/acquired/expiry from database time, and commit.

The host lock is deliberately not run-scoped. Two tenants crawling the same host share one host
capacity. Capacity is conservative when simultaneously active runs pin different settings: the
effective limit is the minimum of the candidate run's configured limit and the limits of active
runs contributing leases. Locks are held only for the claim transaction, never for network I/O.

Persistence-only claims do not invoke a provider and therefore do not consume provider
concurrency. Reconciliation claims may call the provider's operation-lookup seam, so they use the
same global/host capacity and fast-lane fairness rules as ordinary calls.

## 3. Deterministic priority, quotas, and retry bounds

The scheduler orders queued candidates by persisted priority, known graph depth before unknown
depth, discovery time, and page UUID. This makes a persisted frontier replay deterministic without
pretending that same-transaction sitemap input order has semantic authority.

The frozen V1 fast targets are:

| Category | Target |
|---|---:|
| homepage | 1 |
| product/solution/use case | 3 |
| pricing | 1 |
| customer/case study/testimonial | 2 |
| company/about/founder/team | 1 |
| partner/integration | 1 |
| trust/security/compliance | 1 |
| selected blog/news | 1 |

The run-pinned `fast_page_ceiling` remains the hard ceiling. Missing categories never block other
work. Already-attempted no-spend retries may finish even after the selection ceiling so a selected
page is not abandoned merely because it consumed a recoverable attempt.

`retryable_no_spend` is bounded to three dispatch attempts under this contract version. The fourth
claim is never created: reclaim moves the page to terminal `failed` with
`no_spend_retry_exhausted`. Ambiguous or possibly charged calls never enter this retry path.

## 4. Fast/background fairness

A background ordinary or reconciliation claimant must yield whenever any fast-active run has a
claimable, quota-eligible page and global/host capacity. The fairness check covers all workspaces
and runs and reclaims expired fast leases while holding the global claim lock. Consequently an
expired-but-recoverable fast page cannot be bypassed by new background work.

Fairness affects only **new claims**. A provider call already dispatched under a background lease
is not cancelled when fast work appears. Similarly, a fast deadline/stop signal prevents new
claims but does not cancel an in-flight call whose spend may be ambiguous.

## 5. Worker lifecycle, heartbeat, and shutdown

The pool size is exactly the run-pinned `worker_concurrency`. Each worker checks work in this
order: persistence-only recovery, link expansion, reconciliation, then ordinary phase work. This
prioritizes publishing retained results and unlocking their frontier before new acquisition,
without allowing any recovery/expansion path to call `fetch_one`.

Every claimed operation has a heartbeat task. Renewal includes workspace, run, page, worker, and
`lease_generation`; zero updated rows fence the worker. The C0 invariant
`2 * heartbeat_seconds < lease_ttl_seconds` is revalidated in the run config. A stale worker may
finish its local network call, but C1 fenced writes prevent it from publishing a receipt, snapshot,
page completion, or discoveries over a replacement generation.

Graceful stop sets a shared event. Workers cease claiming after their active operation returns.
Caller cancellation is shielded around the pool: it requests the same graceful stop, waits for
already-dispatched bounded calls, and then propagates cancellation. Provider request timeout is
still the outer bound supplied to the one-page fetcher.

## 6. Safety and durable depth expansion

An ordinary page is dispatched only after C2 URL and DNS/IP preflight. Robots authorization is
not consulted until that preflight succeeds, because a C6 live authorizer may itself need bounded
host access. A preflight or robots refusal goes through the durable C4 attempt state machine with
`no_spend`, but the provider delegate receives zero calls.

After one provider call, the coordinator rechecks:

- redirect continuity, count, domain, and every hop/final DNS/IP target;
- final URL consistency;
- MIME allowlist and decompressed response-size ceiling;
- the outgoing-link count/text ceilings.

Only an admitted success can reach artifact/snapshot persistence. C4 then atomically publishes the
page as `fetched` and queues one snapshot-keyed expansion job. The coordinator claims that job
under an independent generation fence and records redirect/canonical/anchor observations through
the C2 discovery policy. Links from a known depth below two are admitted at `parent + 1`; links
from a sitemap-only unknown-depth page remain parked. If that page is later found through a shorter
homepage path, C1 expands its saved link edges at the new depth without fetching the page again.

If discovery persistence fails, the already-fetched page and snapshot remain usable. The expansion
job enters bounded DB-clock exponential backoff and the background phase resumes the same job. A
stale expansion worker cannot renew, complete, or disposition a replacement generation. Exact
observation replay is idempotent, so a crash after discovery commit but before expansion completion
does not duplicate page nodes or force provider I/O. Three failed expansion attempts end in an
explicit partial-coverage state without failing the page.

## 7. Acceptance and review record

The C5 suite proves:

- four spawned operating-system processes racing one run cannot exceed the global lease cap;
- four spawned processes targeting one host cannot exceed the shared per-host cap;
- ordinary and reconciliation background claims yield to eligible fast work;
- an expired fast lease is reclaimed and wins before background work;
- category quotas select homepage, three product pages, pricing, and customer proof before excess
  same-category pages;
- in-flight provider concurrency stays within the configured worker/host bounds;
- heartbeat renewal keeps a slow valid call fenced and publishable;
- idle sibling workers remain available while a slow page is active, then fetch its newly
  discovered children concurrently instead of collapsing the recursive crawl to one worker;
- a sitemap-only fetched company page is later shortened to depth one, expands its already-saved
  team link to depth two, fetches each URL once, and never refetches the company page;
- graceful shutdown finishes one active call and leaves the next page queued;
- `retryable_no_spend` performs exactly three calls and then fails terminally;
- a private-IP preflight refuses durably with zero robots/provider calls;
- lost completion after snapshot/discovery persistence reclaims under a new generation, reuses
  one original-URL snapshot, does not re-fetch the original URL, and does not duplicate link
  provenance;
- coordinator source contains no Firecrawl/Scrapling import or name branch, and operation keys are
  stable within one generation but fenced across generations.

The complete C0-C5 official-site suite collects and passes **128 tests** on the fresh isolated
database `clue_c5_official_site_20260814_final`; C5 contributes 11 focused tests, including nine
real-PostgreSQL cases and the spawned-process race suite. Alembic reports one head
`6e7ba5968751`; isolated `head -> da5f3fe5a90f -> head` downgrade/re-upgrade succeeds. Ruff and
focused mypy are green. No shared database or retained C4 live evidence was modified.

No paid/live provider call is claimed as C5 evidence. C3/C4 already retain one-call Firecrawl and
Scrapling canaries; C5's acceptance target is deterministic cross-process scheduling and fault
recovery. A real multi-page onboarding canary belongs after C6 supplies the run/checkpoint/fleet
composition so it can prove the actual product lifecycle rather than a hand-composed coordinator.

## 8. C6 handoff

C6 must:

- create/reuse exactly one official-site crawl run per recon;
- compose the live bounded robots authorizer and provider/lookup registry;
- run fast workers off the API event loop and stop new fast claims at the persisted deadline;
- freeze the immutable fast corpus checkpoint, transition the same run to background, and resume
  its existing frontier without completed-page refetch;
- register the durable fleet operation and cold-resume behavior;
- map committed crawl/checkpoint counters into truthful setup progress;
- preserve auth/session/setup polling responsiveness and existing replay semantics;
- keep the feature default-off until the C6 browser/live gates pass.

C6 may not create a second background crawl, cancel a dispatched call at the deadline, replace the
PostgreSQL frontier with process memory, or release the browser from a timer rather than a committed
fast Client-KB version.
