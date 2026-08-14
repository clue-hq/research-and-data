# Production deepagent context composition — S6 acceptance

**Date:** 2026-08-15

**Branch:** `platform/onboarding-integration`

**Result:** accepted with all observed live exceptions typed, retained, and reconciled

## 1. Outcome

S6 closes the production path rather than stopping at independently testable components. The
accepted chain is:

```text
real Clerk session
→ internal workspace/client provisioning
→ real Scrapling official-site acquisition
→ fast Client-KB publication
→ browser release and project creation
→ durable company/product version-pair pin
→ brand + company Client-KB + project Stage-0 card composition
→ context receipt
→ real Terra Head-of-ABM turn
→ governed Client-KB list and exact-claim inspection
→ checkpoint, stream, finalization, and replay-safe durable state
→ same-run background extraction and next-turn version refresh
```

The implementation does not add another knowledge store, conversation runner, or card species.
It composes the S1–S5 contracts through the real API/fleet path and adds only the S6 publication,
observability, and operator-read seams.

## 2. Checkpoint delivery

### S6-A — Governed publication and next-turn refresh

- Interview-authored company claims publish into a new account-wide Client-KB version.
- The frozen product field set publishes only into a separately versioned, human-selected product
  scope. Product knowledge is refused when no product has been confirmed.
- Project/interview state that is not a governed client claim changes only the active project's
  Stage-0 card and publishes no Client-KB marker.
- Version allocation is transactionally serialized and replay-stable. A production caller may
  require an append-only derived version because the prior version is already durably pinned.
- Fast and background recon are phases of the same run. The background marker now records the
  exact prior company/product marker as `base_version`, so a partial background extractor overlays
  new knowledge without erasing still-valid fast facts or changing an earlier turn.
- The model-facing `record_interview_answer@1` contract remains unchanged. Publication versions
  are internal domain results; the next turn's immutable database pin remains authoritative.

### S6-B — Privacy-safe observability

- Card events record card kind, schema version, availability, content hash, omission count, and
  the durable correlation identifiers required by operators.
- Receipt events record schema/policy/hash and included/excluded reference counts.
- Tool events record the governed tool address, bounded outcome, replay flag, and reference count.
- Metrics use only bounded low-cardinality labels. Tests reject negative counters and sensitive
  attributes. Claim values, evidence spans, raw bodies, source URLs, email addresses, tokens, and
  credentials are absent.

### S6-C — Body-free operator read

- `GET /api/v1/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/context-refs` is always
  registered and protected by the existing authenticated `thread.read` scope.
- Before composition it returns an honest `pending` state. Afterwards it returns the exact
  persisted assembly identity, versions, hashes, counts, and included/excluded references.
- The frozen response has no hydration switch and no body, text, claim value, evidence span,
  source URL, email, token, or credential field.
- Workspace/project/thread/turn mismatches follow the existing fail-closed 404 behavior.

### S6-D — Production-chain adversarial acceptance

The isolated database matrix covers company-only publication, product-only publication,
project-state-only changes, Project A/B isolation, missing-product refusal, stable historical
pins, replay, crash before and after context persistence, runtime timeout, receipt/body privacy,
fleet composition, trusted product-selection pins, and same-run fast/background continuity.

### S6-E — Live production acceptance

The retained C2 run used the real browser, Clerk session, backend API, fleet, Scrapling acquisition,
OpenRouter Luna extraction, and OpenRouter Terra Head-of-ABM. No fixture card, claim, product option,
or provider response was substituted into the live path.

## 3. Correlated live evidence

### Fast and background recon

- Recon: `bae04840-bb13-5c9f-9f54-17d17a1016f1`.
- Fast lane: 2026-08-15 04:05:23.557 IST to 04:05:59.361 IST, **35.804 seconds**. This satisfies
  the agreed `<=40 seconds` release target.
- Fast checkpoint: 7 immutable snapshots.
- Background checkpoint: 29 immutable snapshots; it continued the same run/frontier.
- Final frontier: 30 attempts, 29 fetched/persisted and one quarantined `spend_unknown` attempt.
  The ambiguous paid/provider outcome was not blindly called again.
- Client-KB version 1 is the fast publication. Version 2 is the background publication with
  `base_version=1`; the historical v1 corpus and the first turn receipt remain unchanged.

### Browser and deepagent

- The browser was released only after the fast Client-KB marker committed and reached the real
  Home/project experience.
- The production turn composed the real brand card, account-wide `ClientKnowledgeCard@2`, and
  only that project's Stage-0 state. No product card was invented because no product was selected.
- In the first real Terra turn the model mistyped a claim identifier copied from the bounded card.
  Exact inspection refused it without widening scope. This is the intended fail-closed result.
- In the second real Terra turn the Head-of-ABM called `list_client_knowledge@2`, received an exact
  pinned reference, passed that exact reference to `inspect_client_claim@2`, and rendered bounded
  official-site provenance, freshness, confidence, verification, and lineage through the real
  toolbelt. This path incurred no new acquisition spend.
- Both turns used the immutable `company-and-selected-product-v2` policy and pinned Client-KB v2.

### Honest live exceptions

1. Luna's live extraction produced a partial company result and did not publish
   `client.product_catalog`. The product-selection gate therefore returned
   `product_catalog_empty` instead of presenting fabricated choices. Product catalog extraction,
   synchronization, selection, and pair-pin behavior remain covered by the S5 isolated/live-fleet
   acceptance, while this C2 condition proves the production empty-state contract.
2. One Scrapling attempt ended `spend_unknown` and remained quarantined. There was no duplicate
   provider call or hidden success claim.
3. C2 exposed an observability bug: `background_started_at` had been recorded only at completion,
   although the crawl event log proved the background phase actually started about 40.83 seconds
   earlier. `BACKGROUND_STARTED` now advances the recon lane to `RUNNING` in the same transaction
   as its durable event. A dedicated idempotency regression proves start is recorded once and
   completion remains owned by Client-KB materialization. The retained C2 database intentionally
   preserves the pre-fix row as discovery evidence; the fix was verified offline after the live
   run rather than rewriting retained evidence.

## 4. Verification matrix

| Gate | Result |
|---|---:|
| Focused S1–S6 backend/API/fleet/replay/DB matrix | 131 passed |
| Final background timestamp, overlay, and trusted gate regressions | 3 passed |
| Frontend tests | 231 passed |
| Frontend lint | passed |
| Design-system token build | passed |
| Default frontend production build | passed, 19 routes |
| Ruff format/check | passed |
| Mypy | passed, 678 source files |
| Import-linter | 25 kept, 0 broken |
| Alembic heads | one head, `1043a61823f1` |
| Fresh upgrade/downgrade/upgrade smoke | passed |
| Real browser + Clerk + Scrapling + Luna + Terra | passed with typed exceptions above |

The repository-wide backend suite retained the branch's documented **40-failure shared-baseline
set**. The failing node categories are unchanged: source-manifest/shared-registry contamination,
merged design logging discipline, migration tests run against a populated monolithic database,
downstream seeded-state collisions, and the pre-existing workspace-token rename guard. The clean
migration database and the 131-test S6 matrix separate those baseline failures from this change;
no S6-focused test failed and there is no unexplained S6 regression.

Next 16's default Turbopack production compiler also reproducibly deadlocked in this checkout even
after its workspace root was pinned. The supported webpack compiler completed the full build,
typecheck, and route generation, so the frontend's default `npm run build` now explicitly uses
`next build --webpack`. `turbopack.root` and `outputFileTracingRoot` remain pinned to the frontend
package to prevent unrelated ancestor lockfiles from expanding the application root.

## 5. Retained review evidence

Do not modify or delete these until review sign-off:

- Accepted live database: `clue_s6_live_20260815_c2`.
- Accepted live artifacts/logs: `/private/tmp/clue-s6-live-20260815-c2`.
- Shared frontend log for that browser session:
  `/private/tmp/clue-s6-live-20260815-c1/logs/frontend.log`.
- Discovery/fault-repair database: `clue_s6_live_20260815_c1`.
- Discovery/fault-repair artifacts/logs: `/private/tmp/clue-s6-live-20260815-c1`.
- Clean migration database: `clue_s6_migration_20260815_c1`.

The retained roots contain provider receipts and operational logs but this report intentionally
contains no credentials, user email, raw page bodies, or claim values.

## 6. Acceptance verdict

S6 is accepted. A real production route now publishes and refreshes Client-KB versions, preserves
old turn receipts, composes the brand/shared-company/project-specific context bundle, exposes its
body-free exact references to operators, lets the production Head-of-ABM resolve bounded refs
through governed tools, and reports real row/event progress without UI timers. The partial catalog,
ambiguous provider spend, and pre-fix background timestamp are explicit evidence—not hidden or
replaced with fixture success.
