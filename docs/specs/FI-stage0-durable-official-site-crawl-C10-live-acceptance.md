# FI Stage-0 durable official-site crawl — C10 live acceptance

**Status:** accepted 2026-08-14; rollout remains default-off and allowlisted

**Parent plan:** [FI-stage0-durable-official-site-crawl-plan.md](./FI-stage0-durable-official-site-crawl-plan.md)

**Test site:** Insight Health official website

## 1. Verdict and boundary

C10 passes its live provider/browser gate. Two independent fresh-database onboarding journeys
proved real Clerk provisioning, authoritative Stage-0 execution in the detached fleet, immutable
fast/background checkpoints over one crawl run, grounded Client-KB claims, automatic browser
release, and replay without provider or claim duplication:

- Firecrawl authoritative fast release: **30.800605 seconds**.
- Scrapling authoritative fast release: **28.785543 seconds**.

Both are below the agreed 40-second target. Firecrawl made real paid single-page calls and retained
ten unique provider request IDs; Scrapling made real local-provider network calls with no spend.
Both background phases completed the same run/frontier used by fast. The retained rows, files, and
privacy-safe logs reconcile.

The feature flag remains off by default. This acceptance proves the implementation is merge-ready;
it is not permission to enable every workspace or to discard the retained evidence. Provider quota
capacity, model-cost attribution, and recovery wake cadence remain explicit operational follow-ups
in §11.

## 2. Retained isolated resources

All databases are on the isolated local PostgreSQL instance at port 55040. None was dropped,
reset, or reused as a shared development database.

| Purpose | Database | Retained artifact/log root |
|---|---|---|
| Initial Firecrawl diagnostic | `clue_c10_firecrawl_20260814` | `/private/tmp/clue-c10-firecrawl-20260814` |
| Accepted tuned Firecrawl run | `clue_c10_firecrawl_tuned_20260814` | `/private/tmp/clue-c10-firecrawl-tuned-20260814` |
| Initial Scrapling redirect diagnostic | `clue_c10_scrapling_20260814` | `/private/tmp/clue-c10-scrapling-20260814` |
| Accepted Scrapling browser run | `clue_c10_scrapling_retry_20260814` | `/private/tmp/clue-c10-scrapling-retry-20260814` |
| Post-review live category canary | `clue_c10_scrapling_priority_20260814` | `/private/tmp/clue-c10-scrapling-priority-20260814` |
| C10 DB regressions | `clue_c10_cutover_tests_20260814` | test-only, no provider artifacts |
| Migration round trip | `clue_c10_migration_smoke_20260814` | migration-only |

The post-review database was freshly migrated and its server logs retained. A third browser repeat
against it was not claimed: the in-app browser controller refused the localhost action at its URL
security boundary. That restriction was not bypassed. The post-review proof is instead the earlier
two complete browser journeys plus provider-free lifecycle/real-PostgreSQL tests and a fresh real
Scrapling acquisition whose JSON evidence is retained under its root.

## 3. Real identity and provisioning proof

The browser used the designated verified Clerk test identity; no email, raw Clerk subject, token,
password, or verification code is recorded in repository documentation or logs.

Each accepted fresh database began with no internal identity. The browser journey caused
`POST /auth/v1/provision` to create exactly one row in each required internal ownership surface:

```text
platform_user=1
auth_identity=1
workspace=1
workspace_membership=1
brand=1
self_serve_provisioning=1
```

Firecrawl correlation:

```text
workspace_id  ws_cfb746ac15d34cb08fc52097efd8d5b4
user_id       usr_933f04a18e1b49a89b616b0d84a32e8d
brand_id      brd_d1b367a697e344bfbe97f53e37cb44b2
recon_run_id  96be1611-a341-5850-bde5-885e53c1faae
crawl_run_id  324fe60b-92bf-408b-92a7-2c8c915b1a04
```

Scrapling correlation:

```text
workspace_id  ws_cd86bbb039ee4f20b79b3be2cf6a296e
user_id       usr_24f2d469f1de40df8348425a55f91ed4
recon_run_id  7f5e05bd-2674-5b40-9884-b9e1e6400f4d
crawl_run_id  e4a214fa-2925-41d9-ba70-0e34fe1e932e
request_id    da4a3bc5-3f5a-4a41-9856-8299bb495be5
```

Provision replay returned `created=false`; all six row counts remained one. Session/principal
reads resolved the same Clue-owned user/workspace identities. Privacy-safe provisioning logs carry
request ID, outcome, `created`, internal user ID, and workspace ID, never raw credentials or token.

## 4. Accepted Firecrawl run

Configuration used a 15-second new-claim deadline, eight-page fast ceiling, 30-page total ceiling,
four workers, per-host capacity two, and eight-second request timeout. Firecrawl was called only
through the single-page `scrape` adapter; no crawl/map/recursive provider option was used.

Database timing:

```text
fast_started_at    2026-08-14 07:23:29.703019+00
fast_completed_at  2026-08-14 07:24:00.503624+00
fast_release       30.800605 seconds
background_done    2026-08-14 07:24:26.285160+00
```

Reconciliation:

| Surface | Result |
|---|---:|
| Page nodes | 30 unique fetch keys |
| Persisted page attempts | 10 |
| Quarantined ambiguous attempts | 20 |
| Unique Firecrawl provider request IDs | 10 |
| Provider-reported acquisition cost | 10 cents |
| URL snapshots | 10 |
| Distinct content hashes/blobs | 9 |
| Fast checkpoint | 8 snapshots, hash `15a4cf505333987a38127809e5ee57c66a9492ef92c212cb9218998270ad9fe2` |
| Background checkpoint | 10 snapshots, hash `e35256293d76bad9460ef4b1b113570ce6333fc2a2825292f2d818950d33d6d7` |
| Extraction operations | 20 materialized, 2 failed |
| Grounded `official_site` claims | 22 |
| Distinct cited snapshot/request refs | 5 / 5 |

The apex and `www` pages retained two URL-level snapshots pointing to one identical content blob,
proving content dedupe did not erase URL provenance. Filesystem reconciliation found 30 retained
artifact files and zero content-hash mismatches. Claim lineage found zero checkpoint-absent
snapshot references. No fetch key had more than one provider attempt.

The fast checkpoint contained homepage, three product/use-case pages, the exact `/pricing`, exact
`/about-us`, a partner/contact surface, and a trust/privacy surface. The site exposed no distinct
same-site founder, customer-story, case-study, or testimonial page in the bounded live inventory;
external customer/news URLs remained external-domain refusals. That is recorded as honest absence,
not synthesized coverage.

The 20 HTTP-429 outcomes returned no provider request/receipt identity. The adapter therefore
could not prove no charge and correctly quarantined them as `spend_unknown`/`ambiguous`; it did not
retry them blindly. Required fast coverage still came from the ten persisted calls.

## 5. Accepted Scrapling run

The initial Scrapling diagnostic refused the common apex-to-`www` redirect because the request
contract carried only exact allowed hosts. C10 corrected the shared `PageFetchRequest` to carry the
run-pinned registrable domain and subdomain policy. Redirect matching is boundary-safe; a suffix
such as `notinsighthealth.ai` remains refused.

The corrected browser run then followed the real 301 to `www`, released automatically without a
manual reload, and completed background on the same run.

Database timing:

```text
fast_started_at    2026-08-14 07:31:26.355927+00
fast_completed_at  2026-08-14 07:31:55.141470+00
fast_release       28.785543 seconds
background_done    2026-08-14 07:34:58.305237+00
```

Reconciliation:

| Surface | Result |
|---|---:|
| Page nodes | 30 unique fetch keys |
| Persisted no-spend attempts | 29 |
| Quarantined ambiguous attempts | 1 |
| URL snapshots | 29 |
| Distinct content hashes/blobs | 28 |
| Fast checkpoint | 7 snapshots, hash `d43e7fee0cf24c57316b0144e26c40daf2203f40299e01b73fcbacf038312fed` |
| Background checkpoint | 29 snapshots, hash `721766b64fedda9418859ab0f9fa5e589e91cff66a21d1c0028d4a73391060f2` |
| Extraction operations | 20 materialized, 2 failed |
| Grounded `official_site` claims | 24 |

Filesystem reconciliation found 50 retained artifact files and zero content-hash mismatches. The
29 successes produced 28 blobs because the apex and `www` snapshots shared content. Claim checks
found zero absent checkpoint refs, zero forged lineage, and zero duplicate page attempts.

One local fetch crossed a crash/persistence ambiguity boundary and had no provider receipt to
reconcile. C4 recovery quarantined it and made no duplicate network request. The background phase
still completed with the other 29 snapshots.

## 6. Live-discovered category-admission correction

The full Scrapling run exposed a provider-neutrality defect that Firecrawl's link order had hidden:
the repository applied the 30-page ceiling in provider/DOM order, so generic links could consume
capacity before observed `/pricing`, `/about-us`, and `/our-mission` pages.

C10 now orders every bounded discovery batch through the same unique-URL category quotas used by
fast claiming. The prefix is homepage, up to three product pages, pricing, up to two customer-proof
pages, company, partner, trust, and blog when those categories actually exist. Every duplicate,
excess category page, generic page, and refusal remains in the batch after the prefix; provenance
and background coverage are not deduplicated away. Initial root+sitemap seeds use the same order.

A second live finding corrected category honesty. Scrapling's anchor text for a blog card included
the word “plans,” causing text matching to label the explicit `/blog/...` path as pricing. The V1
classifier now resolves an explicit URL-path category first and consults bounded link text only for
an otherwise opaque path.

The final real Scrapling canary followed the live 301, returned 55 links, and produced this exact
frontier prefix:

```text
homepage  https://www.insighthealth.ai/
product   https://www.insighthealth.ai/solution-virtual-care-assistant
product   https://www.insighthealth.ai/use-cases/ai-powered-colonoscopy-recall-management
product   https://www.insighthealth.ai/use-cases/annual-wellness-visits
pricing   https://www.insighthealth.ai/pricing
company   https://www.insighthealth.ai/about-us
partner   https://www.insighthealth.ai/become-a-partner
trust     https://www.insighthealth.ai/privacy
blog      https://www.insighthealth.ai/blog
```

The raw provider order began with an external news story, a blog, `/`, CDN downloads, and brand
assets, demonstrating that the passing order came from Clue policy rather than provider luck. The
retained JSON is
`/private/tmp/clue-c10-scrapling-priority-20260814/evidence/live-scrapling-priority-canary.json`.
Pure, lifecycle, PostgreSQL ceiling, and all-category priority tests protect the behavior.

## 7. Browser progress and authoritative release

The first live Firecrawl attempt showed the setting-up screen could appear stalled even while
committed crawl rows/events advanced. The frontend stall signature included only legacy lane/field
events. It now includes official-site page, snapshot, checkpoint, extraction, and event counters;
a real crawl event resets the stall budget.

The initial authoritative composition also still invoked the historical field-by-field resolver
before launching the new crawl. C10 split Stage-0 into prepare/finalize seams: authoritative mode
prepares the client entity and recon, enqueues the durable crawl directly, and publishes the
Client-KB/recon completion only after grounded checkpoint claims commit. Shadow mode retains the
historical resolver behavior.

Finally, the first Firecrawl diagnostic released in 123.900319 seconds because the lifecycle waited
for already-dispatched ambiguous calls to drain before starting fast extraction. The immutable
fast checkpoint now begins grounded materialization concurrently with that safe drain. No paid call
is cancelled, no late result enters the frozen fast corpus, and user release waits for the real
Client-KB commit rather than elapsed UI time. This produced the two accepted sub-40-second runs.

## 8. Replay and idempotency

- Firecrawl browser replay completed in 2.663 seconds with zero new pages, attempts, snapshots,
  checkpoints, extraction operations, or claims.
- Scrapling browser replay completed in 1.223 seconds with the same zero-row-delta result.
- Setup replay reused each existing recon/crawl identity and background checkpoint.
- Provision replay returned `created=false`; identity/membership/brand/provision counts did not
  change.
- Completed-page fetch-key duplication query returned zero for both accepted databases.
- Cold replay did not invoke Firecrawl, Scrapling, or OpenRouter again.

## 9. Logs and privacy

Backend and fleet logs are retained under each accepted run root. They correlate request,
workspace, recon, crawl, page, checkpoint, snapshot, provider request, and event IDs. Page events
use host plus URL hash; provisioning logs contain internal IDs and outcome. They contain no raw
token, password, Clerk subject, email, raw provider receipt, or page/model body.

The Scrapling log demonstrates committed page-start/page-fetched rows, partial extraction,
background completion, and cold replay. It also exposes frequent `recovery_pending` wakes while
leases settled; this is retained as an operational cadence issue rather than hidden.

## 10. Final regression gates

- Complete affected backend target (`tests/official_site`, setup DB tests, and auth): passed.
- Post-review category policy/lifecycle target: 51 passed.
- Final PostgreSQL graph/coordinator/lifecycle target: 14 passed.
- Frontend: 229 tests passed; design tokens, ESLint, TypeScript, and Next production build passed;
  all 19 application routes generated.
- Ruff format/lint: passed after the final change.
- mypy: 658 source files, zero issues.
- import-linter: 25 contracts kept, zero broken.
- Alembic: sole head `a57463ec42ea`; fresh upgrade/downgrade/upgrade passed.
- Artifact hash, checkpoint membership, claim lineage, receipt uniqueness, and duplicate-attempt
  reconciliation: zero unexplained failures.

## 11. Typed exceptions and operational follow-ups

These do not invalidate the C10 data-integrity/browser result, but must remain visible:

1. **Firecrawl account capacity:** 20 live requests ended as HTTP 429 with no receipt. They are
   conservatively `spend_unknown` and not auto-retried. Production rollout should size provider
   concurrency/rate limits or add receipt-capable reconciliation before widening the allowlist.
2. **Model cost attribution:** real Luna responses recorded prompt/completion tokens, but the
   OpenRouter gateway reported zero cost, so durable model cost reconciles to provider-reported
   zero rather than an independent invoice. This requires billing-metadata monitoring before model
   cost is used as an enforcement-grade budget signal.
3. **Recovery wake cadence:** the Scrapling fleet repeatedly requeued while active leases drained.
   Correctness and provider-call uniqueness held, but backoff should replace the sub-second log/wake
   churn.
4. **Partial extraction is honest:** both accepted runs materialized 20 of 22 bounded operations;
   two field operations failed while successful siblings and claims were preserved. The UI and
   operator surface report partial state rather than fabricating completeness.
5. **Retained evidence:** all named databases and roots must remain untouched until founder review
   sign-off.

No unresolved C10 P1/P2 correctness or security finding remains. The capability may be merged with
its default-off/allowlisted rollout posture intact; widening production activation is a separate
operator decision subject to the follow-ups above.
