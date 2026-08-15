# Production Deepagent Context — Release Closure Plan

**Status:** IMPLEMENTATION AND EVIDENCE COMPLETE — production release blocked by the measured
fast-lane latency exception; R0–R5 executed on `platform/onboarding-integration`

**Date:** 2026-08-15
**Parent contract:** `FI-production-deepagent-context-composition.md`
**Acceptance contract:** `FI-production-deepagent-context-composition-S6-acceptance.md`

## 1. Purpose

S3–S6 built the production composition for account-wide Client-KB knowledge, active-project
Stage-0 state, selected-product knowledge, governed exact-claim inspection, durable context pins,
replay, and refresh. The adversarial review found that the account-wide path is materially real,
but that the roadmap cannot yet claim complete production acceptance.

This plan closes the remaining release blockers in dependency order. A live browser/provider run
is the final proof of the completed contracts; it is not a substitute for enforcing those
contracts offline first.

## 2. Scope

### 2.1 In scope

1. Make company-versus-product field scope an enforceable field-registry and claim-write
   invariant, including direct-SQL protection and defensive reads.
2. Give durable product-selection gate snapshots subject binding, bounded erasure/redaction, and
   no-resurrection replay behavior.
3. Replace the process-local-only production metric path with a configurable OpenTelemetry/OTLP
   exporter composition while retaining deterministic in-memory tests.
4. Turn the repository-wide known-failure baseline into an executable, reviewable quarantine or
   resolve its causes; new failures must never disappear inside the historical set.
5. Correct roadmap and acceptance statements so implemented, offline-proven, live-proven, and
   typed-exception states remain distinct.
6. Run a fresh retained real production journey proving catalog extraction, human product
   selection, product cards/tools, fast/background version continuity, and governed interview
   publication.

### 2.2 Explicitly deferred

The model-visible `product_id` authority issue identified in the adversarial review is intentionally
deferred by founder direction. This closure does not hide, inject, or otherwise change model
control of `product_id` on existing write-bearing tools, and completion of this plan must not be
reported as resolving that separate risk.

## 3. Non-negotiable invariants

- `client.*` company fields cannot be written with a product ID.
- Product-knowledge fields cannot be written without a product ID.
- The shared claim-write substrate, not individual S5 writers, owns that rule.
- Historical malformed scope cannot enter company or product cards/tools even before remediation.
- Exact catalog bodies retained for a human gate are erasable by their bound client subject.
- Erased catalog bodies cannot reappear through cold gate replay, transcript replay, or a repeated
  product-selection tool invocation.
- Production metrics export only bounded labels; facts, evidence, URLs, emails, tokens, and
  credentials never become metric attributes.
- A fast v1 turn remains pinned to v1 after background publishes v2; only a later turn sees v2.
- Company and product interview publications advance only their independent intended sequences.
- No fixture catalog, product, claim, provider response, or context card may be substituted in the
  final live acceptance.

## 4. Ordered checkpoints

### R0 — Contract and evidence freeze

**Status:** complete 2026-08-15.

**Deliverables**

- Freeze a provider-neutral field-level product-scope policy with `forbidden`, `required`, and
  legacy/general `optional` semantics.
- Freeze gate snapshot erasure semantics and the retained body-free audit surface.
- Freeze OTLP configuration, startup, shutdown, and bounded-label behavior.
- Record the exact existing broad-suite failure set before remediation.

**Exit gate**

- No unresolved question can change DDL or the field/gate/metrics public contracts.
- The existing retained S5/S6 databases and artifact roots remain untouched.

### R1 — Shared company/product scope enforcement

**Status:** complete 2026-08-15.

**Deliverables**

- Add product-scope policy to global and workspace field definitions.
- Mark the frozen product-knowledge field set `required`; make `client.*` default fail-safe to
  `forbidden`; keep the dual company/product KB-version marker explicitly `optional`.
- Enforce the effective policy in `insert_claim` and a database trigger.
- Make Client-KB readers select only fields eligible for the requested company/product scope.
- Add an operator-visible read of historical scope violations without mutating old claims.

**Passing criteria**

- Application and direct-SQL writes both refuse required-without-product and
  forbidden-with-product claims.
- Company readers cannot return product-required fields with `product_id IS NULL`.
- Product readers cannot return company-forbidden fields with a product ID.
- Valid company fields, product fields, and both KB-version marker forms remain accepted.
- Global/workspace registry registration, redefinition, proposal, import, and enum/static tests
  pass.
- Fresh upgrade → downgrade → upgrade returns to one Alembic head.

### R2 — Gate privacy and operational metrics

**Status:** complete 2026-08-15.

**Deliverables**

- Bind product-selection gates to the client subject that supplied the catalog.
- Redact the exact gate snapshot under the normal agent privacy service while retaining a
  body-free erasure receipt and immutable gate identity/digest.
- Make cold transcript/gate reads report unavailable/redacted state without restoring options.
- Add a concrete OpenTelemetry metric sink and configurable OTLP exporter lifecycle to both the
  production API and fleet process.
- Remove raw URL fallback from metric labels and apply the shared observability redaction boundary
  to every exported attribute.

**Passing criteria**

- DSAR removes the catalog body, descriptions, aliases, and selectable options from every durable
  gate read; repeat erasure is idempotent.
- Replaying the originating turn or tool cannot restore the snapshot.
- Foreign-workspace erasure changes zero rows and reveals no gate existence.
- In-memory tests remain deterministic; an exporter fake receives real counters/gauges after
  startup and flush; shutdown flushes and closes once.
- OTLP mode refuses missing/invalid endpoint configuration and never logs/export labels containing
  forbidden values.

### R3 — Baseline and documentation truth

**Status:** complete 2026-08-15.

**Deliverables**

- Re-run the whole backend suite on a fresh isolated database.
- Fix branch regressions; either fix historical failures or capture an exact executable quarantine
  whose node set, reason, owner, and removal condition are reviewed.
- Correct the parent roadmap and S6 acceptance record, preserving the earlier live catalog absence
  while separately recording the closure run's catalog success and v1-to-v2 receipt continuity.

**Passing criteria**

- Focused S3–S6 tests are green.
- The broad suite has zero unexplained failures; an added or removed failure changes the executable
  baseline and fails its guard until reviewed.
- Documentation never calls the product journey live-proven before R5.

**Current evidence**

- Fresh database `clue_context_release_20260815_broad_c4` upgraded to the single
  `df332fd7904c` head before the final full run and is retained for review. Its JUnit and text log
  are `/private/tmp/clue-context-release-20260815-broad-c4.xml` and
  `/private/tmp/clue-context-release-20260815-broad-c4-pytest.log`.
- The exact monolithic result is 32 failures, replacing the obsolete 40-failure estimate.
- Twenty-six are shared-database ordering/contamination failures: three migration tests that
  correctly refuse downgrade after earlier tests create fleet work, and twenty-three
  discovery/scoring, durable, fleet, and waterfall tests whose global registries/data are changed
  by earlier modules. The migration tests pass on a pristine migration database; all twenty-three
  other nodes pass when their groups run in isolation.
- Six are genuine pre-existing Lane-E acceptance drift:
  `test_lane_e_e1_acceptance.py` (one), `test_lane_e_e2_acceptance.py` (one), and
  `test_lane_e_e3_acceptance.py` (four). They concern verified summary/overview/narrative,
  unresolved-client, feature-flag, and second-delivery expectations rather than S3–S6 context
  composition.
- No S3–S6 context-composition test failed. The exact node set, owner, reason, and removal condition
  are frozen in `tests/fixtures/production_context/release_broad_quarantine.json`. Script 19 runs
  every test and accepts only that exact set: an added failure or a repaired-but-still-listed node
  fails the release guard. This is an executable debt boundary, not a green monolithic suite.

### R4 — Offline release gate

**Status:** complete 2026-08-15.

**Deliverables**

- Run backend unit/DB/adversarial suites, frontend tests/lint/design-token/build, Ruff, mypy,
  import contracts, one-head check, and clean database migration smoke.
- Exercise crash-before/after-snapshot-redaction and crash-before/after-version-publication.

**Passing criteria**

- Zero unexplained failures.
- Replay produces zero provider spend and no duplicate claims, markers, products, lineage, or
  gates.
- Worktree and retained evidence inventories are recorded before live execution.

**Evidence**

- The final focused S3–S6 matrix passed 90 tests, including scope enforcement, gate DSAR,
  OpenTelemetry export, fleet composition, version refresh, card/tool isolation, replay, and the
  new 32-connection stream-sequence race regression.
- Ruff, changed-source mypy, the previously completed full 679-file mypy/import gates, frontend
  tests/lint/build, one-head inspection, and clean migration smoke passed. The broad C4 suite
  matched the exact reviewed 32-node quarantine with zero additions or removals.

### R5 — Fresh real-provider and browser acceptance

**Status:** executed 2026-08-15 with a production-blocking fast-lane latency exception.

**Deliverables**

- Create a fresh named PostgreSQL database and separate retained artifact/log root.
- Run real Clerk provisioning, Scrapling official-site acquisition, configured extraction model,
  frontend/browser onboarding, project creation, and production Head-of-ABM turns.
- Correlate browser, API, fleet, database, artifact, provider receipt, and metric/log evidence by
  durable IDs.

**Passing criteria**

1. Fast Client-KB v1 commits and releases the browser within 40 seconds, or a typed measured
   exception is reported.
2. The real extractor publishes a non-empty grounded product catalog.
3. The agent presents only those catalog products; the human confirms one through the production
   gate and answer route.
4. The next turn pins the confirmed product, composes `ProductProfileCard@1`, and—when a product KB
   exists—`ProductKnowledgeCard@1`.
5. The agent lists and inspects an exact product claim through the production toolbelt.
6. A v1 turn receipt remains byte/hash/version stable while background publishes v2; a later turn
   pins v2 without refetching completed pages.
7. A governed company interview answer advances only the company version; a governed product
   answer advances only the selected-product version; prior receipts remain unchanged.
8. Project A/B, workspace, replay, DSAR, provider-spend, snapshot, claim, and lineage reconciliation
   pass with no unexplained duplicate or missing row.

The fresh database and artifact/log roots remain untouched until review sign-off.

The earlier C2 run is discovery evidence, not R5 acceptance: both fast and background
`client.product_catalog` operations received HTTP 200 responses but emitted no usable output and
were recorded as `spend_unknown` under the V1 extraction policy. The corrected V2 policy uses a
bounded 4,096-token envelope with reasoning effort `none`; known terminal HTTP responses are now
retained and cost-accounted as failed rather than ambiguously spent, while transport ambiguity
remains quarantined. The fresh closure run below proves the V2 path without mutating or replaying
those earlier `clue_s6_live_20260815_c2` rows.

**Fresh live evidence**

- Retained database: `clue_context_release_20260815_live_c2`.
- Retained artifact/log root: `/private/tmp/clue-context-release-20260815-live-c2`.
- Real Clerk provisioning, Scrapling single-page acquisition, Luna extraction, browser project
  creation, and Terra Head-of-ABM execution were correlated to workspace
  `ws_c95041606e5f4746b12e8614fd976579` without fixture cards, claims, products, or provider
  responses.
- Recon `e1dcb377-4b7e-59bf-b334-bb4359acd3aa` and crawl
  `eac3f589-e8cb-43c7-99d6-e3a6f469c6e1` produced an 11-snapshot fast checkpoint and 53-snapshot
  background checkpoint on the same frontier. Background completed 53 pages, retained 52 unique
  content hashes, quarantined two ambiguous pages, and had zero duplicate successful page fetches.
- The fast phase took **103.759 seconds** (11:23:14.155 to 11:24:57.914 IST), despite a claim
  deadline at 11:23:54.201. The browser timed out and required the explicit Continue-anyway path.
  This is a measured typed exception, not a successful `<=40s` result, and blocks production
  release until corrected and rerun.
- The lifecycle correction is now implemented offline: a clean unresolved lease no longer cancels
  the fast deadline or blocks publication after the immutable checkpoint. It stays in the same
  run/frontier, is eligible for exactly one fenced background acquisition, is absent from fast v1,
  and may enter background v2. Tests cover a 90-second lease hint, authoritative v1/v2 separation,
  and `fast_closing` cold replay. This changes the implementation state, not the retained R5
  evidence; a fresh real-provider/browser run without Continue-anyway is still required.
- A real catalog exposed Virtual Care Assistant and Aura Anywhere across the retained catalog
  lineage. The production human gate approved Aura Anywhere; subsequent turns composed its
  product profile/knowledge, listed exact product references, and inspected exact bounded
  provenance.
- A historical turn remained pinned to company v1 with bundle/hash
  `cd12afe3-34f5-5d88-917f-e3d7999b3f34` /
  `5a9346324ec626e751d315cae1eeb4e50887f92a4dc28825bef10cf978682b49` while background published
  v2; later turns pinned v2 and company interview publication advanced only company v3.
- Human-selected product publication advanced Aura Anywhere independently from product v1 to v2
  and v3 while company remained v3. A final production turn pinned the exact `(company v3,
  product v3)` pair, listed four product references, and persisted 49 unique contiguous stream
  events (`1..49`).
- The run exposed a legitimate multi-emitter stream race. The repaired allocator takes a
  transaction-scoped advisory lock in a separate statement before reading the high-water mark;
  32 independent connections now allocate `1..32` without collision. Interim fault-repair turns
  remain in the retained database/logs and are not misrepresented as clean acceptance.
- Password/Device-Trust sign-in was not rerun in this closure; the retained real authenticated
  Clerk session and backend provisioning were used. The product-gate human message also still
  renders its structured response as raw JSON, a frontend presentation defect outside the context
  authority proof.

## 5. Completion rule

R0–R5 implementation and evidence collection are complete, and the product-context customer
journey is now live-proven. That does **not** make the branch production-release-ready: the final
R5 run missed the fast release target by 63.759 seconds and required manual continuation. The
stuck-page deferral correction is implemented and deterministically verified, but release still
requires a new retained run at `<=40s` without the manual override. The two ambiguous Scrapling
pages, raw gate-response presentation, real password/Device-Trust rerun, and the owned 32-node
broad-suite debt remain explicit follow-ups. The model-visible `product_id` authority concern also
remains intentionally deferred by founder direction under §2.2.
