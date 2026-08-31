# Production deepagent context composition — S6 acceptance

**Date:** 2026-08-15

**Branch:** `platform/onboarding-integration`

**Result:** production composition and full product journey live-proven; release blocked by the
measured 103.759-second fast phase and manual browser continuation

## 1. Outcome

S6 composes the production path rather than stopping at independently testable components. The
fresh retained closure run proved this chain through company and selected-product knowledge:

```text
real Clerk session
→ internal workspace/client provisioning
→ real Scrapling official-site acquisition
→ fast Client-KB publication
→ browser release and project creation
→ durable company/optional-product version-pair pin
→ brand + company Client-KB + project Stage-0 card composition
→ context receipt
→ real Terra Head-of-ABM turn
→ real catalog presentation and human-only product selection
→ product profile + Product-KB card composition
→ governed company/product list and exact-claim inspection
→ governed company/product interview publication on independent versions
→ checkpoint, stream, finalization, and replay-safe durable state
→ same-run background extraction and a later pinned company version
```

The same run also preserved a v1 context receipt while background published v2, then composed
later v2/v3 turns. No S5 fixture was substituted for the catalog, product, claims, cards, model,
gate, or tool execution. The result is functionally live-proven but not release-accepted: the fast
phase took 103.759 seconds and the browser required the explicit Continue-anyway path.

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

### S6-E — Live production closure run

The retained closure run used the real browser, Clerk session, backend API, fleet, Scrapling
acquisition, OpenRouter Luna extraction, and OpenRouter Terra Head-of-ABM. No fixture card, claim,
product option, or provider response was substituted. It proved the missing product journey and
also exposed the blocking latency, stream-race, and gate-presentation issues recorded below.

## 3. Correlated live evidence

### Fast and background recon

- Retained database: `clue_context_release_20260815_live_c2`; retained root:
  `/private/tmp/clue-context-release-20260815-live-c2`.
- Recon: `e1dcb377-4b7e-59bf-b334-bb4359acd3aa`; crawl:
  `eac3f589-e8cb-43c7-99d6-e3a6f469c6e1`.
- Fast lane: 2026-08-15 11:23:14.155 IST to 11:24:57.914 IST, **103.759 seconds**.
  The crawl's fast claim deadline was 11:23:54.201. The run therefore missed the `<=40s` target
  by 63.759 seconds and required the browser's explicit Continue-anyway action.
- Fast checkpoint: 11 immutable snapshots at 11:24:48.328. Background checkpoint: 53 snapshots at
  11:28:22.658 on the same crawl/frontier. Background completed at 11:28:32.265.
- Final frontier: 53 fetched pages, two quarantined pages, 53 URL-level snapshots, 52 unique
  content hashes, 55 attempts, and zero pages with duplicate successful provider acquisition.
  Both ambiguous Scrapling pages remained quarantined and were not blindly retried.
- Client-KB v1 is the fast publication; v2 is the background publication. Turn
  `67a06adf-64ee-5b32-91f7-cca6019e6e05` remained pinned to v1 with context bundle
  `cd12afe3-34f5-5d88-917f-e3d7999b3f34` and aggregate hash
  `5a9346324ec626e751d315cae1eeb4e50887f92a4dc28825bef10cf978682b49`. Later turns pinned v2,
  and a governed company interview publication advanced company knowledge to v3 without changing
  that historical receipt.

### Browser and deepagent

- Real Clerk authentication and internal workspace/client provisioning were reused from the same
  retained browser journey. Password and Device-Trust entry were not rerun in this closure, so
  this is real-session composition proof rather than a second password/MFA acceptance.
- The real catalog lineage contained Virtual Care Assistant and Aura Anywhere. Production turn
  `9ad377be-97ee-5876-95b9-d02453235af4` composed the company v3 catalog with no selected product
  and opened product gate `43ab5609-b400-5b5b-94a2-91bf8c4b81a4`.
- The authenticated human approved Aura Anywhere (`prd_65ae1808204e59f59776574e9b6d6dee`).
  Turn `d6cf1d5c-43c2-57c4-b43a-55dfae89a1c1` then pinned `(company v3, product v1)`, composed the
  selected-product profile and knowledge card, and exercised both company and product inspectors.
- Human product facts advanced only the selected product from v1 to v2 and then v3. Turn
  `a367dabc-ebf3-57c4-a3be-51708204fed3` pinned product v2 and inspected its exact governed claim.
  The final clean turn `99e1a99a-17c6-55a4-8811-939d7c65f111` pinned `(company v3, product v3)`,
  listed four exact product references without bodies, and persisted 49 unique contiguous stream
  sequences (`1..49`). Company remained v3 throughout the product-only publications.
- Context cards, list/inspect tools, model/checkpoint messages, finalization, and replay all used
  the immutable turn pair rather than resolving whichever company/product marker was newest.

### Honest live exceptions

1. The fast phase took 103.759 seconds and the browser required manual continuation. This blocks
   production release even though the eventual catalog/product context was correct. A subsequent
   offline lifecycle correction now freezes at the configured fast deadline when a clean lease is
   unresolved, publishes from the completed snapshot set, and defers that page on the same
   frontier to background. Deterministic tests prove authoritative v1 excludes it and v2 includes
   it after one background fetch. This historical live result remains failed until a fresh
   no-override real-provider/browser rerun proves the correction at `<=40s`.
2. Scrapling quarantined two `spend_unknown` pages (`/blog` and
   `/direct-access-colonoscopy`) without duplicate calls. The remaining 53 pages and both corpus
   checkpoints reconciled; these two ambiguous outcomes remain operator-visible.
3. Legitimate stream, tool, and finalization emitters raced on `max(sequence)+1`. The first live
   product-write turn exposed the collision while its durable turn still completed. The final fix
   serializes allocation with a transaction-scoped per-turn advisory lock in a separate SQL
   statement before reading the high-water mark; a 32-independent-connection regression and the
   final live turn's `49/49` event/sequence count prove the repaired behavior. Interim fault turns
   remain in the retained evidence and are not called clean acceptance.
4. The product-selection answer is functionally processed but its human message is rendered as raw
   JSON in the browser. This is a presentation defect, not a context-authority failure, and must be
   repaired before calling the user experience polished.
5. The explicit founder-deferred model-visible `product_id` authority concern was not changed by
   this closure and remains recorded in the release-closure plan.

## 4. Verification matrix

| Gate | Result |
|---|---:|
| Final focused S3–S6 backend/API/fleet/replay/DB matrix | 90 passed |
| New exact broad-quarantine guard | 2 passed |
| Independent-connection stream allocator fault test | 32 writers, sequences 1..32 |
| Frontend tests | 232 passed |
| Frontend lint | passed |
| Design-system token build | passed |
| Default frontend production build | passed, 19 routes |
| Ruff format/check | passed |
| Mypy | passed, 679 source files |
| Import-linter | 25 kept, 0 broken |
| Alembic heads | one head, `df332fd7904c` |
| Fresh upgrade/downgrade/upgrade smoke | passed |
| Broad backend C4 gate | exact reviewed 32-node quarantine; zero added/removed |
| Real browser + Clerk + Scrapling + Luna + Terra | company/product path passed; fast latency failed |

The final repository-wide run used fresh database `clue_context_release_20260815_broad_c4` and
produced **the same exact 32 failures** as C3: 26 suite-order/shared-database isolation failures and
six genuine pre-existing Lane-E acceptance failures. No S3–S6 context-composition node failed.
`scripts/19_production_context_release_gate.py` now executes or reads the JUnit result and passes
only when the exact reviewed node set matches
`tests/fixtures/production_context/release_broad_quarantine.json`. A count match with a different
node, a new node, or a repaired node left in quarantine fails closed. The monolithic suite is not
called green; its debt is owned and mechanically bounded.

Next 16's default Turbopack production compiler also reproducibly deadlocked in this checkout even
after its workspace root was pinned. The supported webpack compiler completed the full build,
typecheck, and route generation, so the frontend's default `npm run build` now explicitly uses
`next build --webpack`. `turbopack.root` and `outputFileTracingRoot` remain pinned to the frontend
package to prevent unrelated ancestor lockfiles from expanding the application root.

## 5. Retained review evidence

Do not modify or delete these until review sign-off:

- Closure live database: `clue_context_release_20260815_live_c2`.
- Closure live artifacts/logs: `/private/tmp/clue-context-release-20260815-live-c2`.
- Final broad database: `clue_context_release_20260815_broad_c4`.
- Final broad JUnit: `/private/tmp/clue-context-release-20260815-broad-c4.xml`.
- Final broad log: `/private/tmp/clue-context-release-20260815-broad-c4-pytest.log`.
- Earlier accepted company-path database: `clue_s6_live_20260815_c2`.
- Earlier accepted company-path artifacts/logs: `/private/tmp/clue-s6-live-20260815-c2`.
- Shared frontend log for that browser session:
  `/private/tmp/clue-s6-live-20260815-c1/logs/frontend.log`.
- Discovery/fault-repair database: `clue_s6_live_20260815_c1`.
- Discovery/fault-repair artifacts/logs: `/private/tmp/clue-s6-live-20260815-c1`.
- Clean migration database: `clue_s6_migration_20260815_c1`.

The retained roots contain provider receipts and operational logs but this report intentionally
contains no credentials, user email, raw page bodies, or claim values.

## 6. Current verdict

S3–S6 production context composition is implemented and the real company + selected-product
journey is live-proven end to end. The shared claim substrate enforces company/product field scope;
cards and tools retain exact turn pins; gate snapshots have DSAR/no-resurrection coverage; metrics
have a production OTLP path; the human catalog selection and independent interview publications
worked through the production fleet.

The branch is **not production-release-ready**. The final live fast phase missed the target by
63.759 seconds and required manual continuation. The stuck-page deferral fix is implemented and
offline-proven, but has not yet replaced that failed live evidence. Two Scrapling pages remain
spend-unknown, password/Device-Trust entry was not rerun, the gate answer has a raw-JSON
presentation defect, and the broad backend suite remains green only under an exact owned 32-node
quarantine rather than in absolute terms. The product-context architecture is materially ready;
release should wait for a new no-override retained run. The model-visible product-scope authority
issue remains deliberately deferred by founder direction.
