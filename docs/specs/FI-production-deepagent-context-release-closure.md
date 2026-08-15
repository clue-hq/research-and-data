# Production Deepagent Context — Release Closure Plan

**Status:** IN PROGRESS — R0–R2 complete; R3 active on `platform/onboarding-integration`
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

**Status:** in progress 2026-08-15.

**Deliverables**

- Re-run the whole backend suite on a fresh isolated database.
- Fix branch regressions; either fix historical failures or capture an exact executable quarantine
  whose node set, reason, owner, and removal condition are reviewed.
- Correct the parent roadmap and S6 acceptance record, including the live catalog absence and the
  fact that both retained live turns pinned v2.

**Passing criteria**

- Focused S3–S6 tests are green.
- The broad suite has zero unexplained failures; an added or removed failure changes the executable
  baseline and fails its guard until reviewed.
- Documentation never calls the product journey live-proven before R5.

**Current evidence**

- Fresh database `clue_context_release_20260815_broad_c2` upgraded to the single
  `df332fd7904c` head before the full run and is retained for review.
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
- No S3–S6 context-composition test failed. R3 remains open because the six Lane-E failures still
  require an owning fix/quarantine decision and the monolithic database harness still needs
  isolation rather than a misleading green label.

### R4 — Offline release gate

**Deliverables**

- Run backend unit/DB/adversarial suites, frontend tests/lint/design-token/build, Ruff, mypy,
  import contracts, one-head check, and clean database migration smoke.
- Exercise crash-before/after-snapshot-redaction and crash-before/after-version-publication.

**Passing criteria**

- Zero unexplained failures.
- Replay produces zero provider spend and no duplicate claims, markers, products, lineage, or
  gates.
- Worktree and retained evidence inventories are recorded before live execution.

### R5 — Fresh real-provider and browser acceptance

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
remains quarantined. R5 must prove V2 with a new run and must not mutate or replay the C2 rows.

## 5. Completion rule

This closure is complete only when R0–R5 pass and the parent acceptance record is amended with the
new evidence. Passing R1–R4 makes the implementation mechanically release-ready; only R5 permits
the complete S3–S6 customer journey to be described as live-proven.
