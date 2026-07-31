# Clue Trial implementation plan — Sumble-only backend acceptance harness

**Date:** 2026-07-31  
**Branch:** `platform/clue-trial`  
**Parent architecture:** [Harness requirements](../../architecture/clue-hq-harness-architecture-and-requirements.md)  
**Agent contract:** [Platform agent runtime](../../architecture/clue-hq-platform-agent-runtime.md)  
**Research-view contract:** [PC-C7](../../specs/PC-C7-research-views-derivations-and-handoff.md)  
**Executable acceptance map:** `tests/fixtures/clue_trial/sumble_acceptance_map.json`  
**Status:** APPROVED / IN PROGRESS

## 1. Outcome

Build a deliberately thin, local CLI acceptance harness that lets a founder drive one real
Sumble-only ABM research run through the platform backend and inspect its truth.

The first complete journey is:

```text
isolated trial workspace
  -> Stage 0 conversation
  -> human product confirmation
  -> ICP synthesis, discussion, and human confirmation
  -> direct account input by domain
  -> Sumble identity + organization/jobs/confirmed-tech acquisition
  -> typed claims and provenance
  -> scoring / explicit human admission
  -> governed account research
  -> verification
  -> production C7 account research view
  -> local HTML/JSON inspection report
```

The harness is a test instrument, not a temporary terminal implementation of the product.
Business state and execution remain in the backend. The CLI communicates over HTTP, displays
durable status, sends explicit human decisions, and exports read-only inspection artifacts.

This slice succeeds when a human can answer, with evidence:

1. what Sumble actually returned;
2. how the platform normalized and stored it;
3. which claims were direct versus derived;
4. why a derived conclusion is or is not supported;
5. what the agent learned during Stage 0;
6. which project/product/ICP/account scope was used;
7. what was spent in Sumble credits and model cost;
8. what failed, retried, resumed, or remained unknown; and
9. whether the final C7 output is useful enough to justify adding Exa.

## 2. Binding terminology and boundaries

### 2.1 “Sumble-only”

For this trial, Sumble-only means:

- `sumble_organizations`, `sumble_jobs`, and `sumble_tech_stack` are the only external factual
  acquisition sources enabled;
- Exa, Parallel, Firecrawl, Scrapling, Clay, Apollo, ZoomInfo, BuiltWith, CRM, and public
  registries are disabled for acquisition;
- user statements and uploaded first-party material remain valid first-party inputs;
- OpenRouter remains the model runtime for conversation, planning, synthesis, and verification;
- model output is always a derived candidate with support references, never a direct Sumble fact;
- the final manifest proves which source keys ran; an unexpected source is a failed trial.

### 2.2 Product versus project versus campaign

- A **project** is the end-to-end ABM motion tested here.
- A **campaign** is a later channel program and is outside this trial.
- One trial has exactly one workspace, brand, product candidate, project, confirmed ICP version,
  project run, and initially one direct-input account.

### 2.3 No second control plane

The CLI must not create:

- a second workflow engine;
- a second agent loop;
- a second claim/evidence store;
- a second project-run state machine;
- a Markdown/HTML truth store;
- a provider-specific downstream code path; or
- a sequence that imports and calls scripts `01` through `07`.

The report is a rendering of API/C7 data. It is never authoritative.

## 3. Current baseline and gaps

### 3.1 Reusable implementation

- `scripts/00_stage0_trial.py` proves the Head-of-ABM + Recipe 0 + C6 conversation path, durable
  history, scoped memory, Client-KB routing, human product/ICP confirmation, and restart/resume.
- The M4 source registry, resolver protocol, HTTP error taxonomy, claim constructors, waterfall,
  and source-yield telemetry exist.
- The M5/M6 phase handlers for reverse profiling, ICP confirmation, discovery, scoring, and tier
  checkpoint exist.
- The per-run production composer registers real phase handlers for discovery, scoring, deep,
  verification, review, and gated handoff.
- C7.9 has real database-backed production readers and a read-only CLI inspector.

### 3.2 Gaps this plan must close

1. No Sumble secret, manifests, typed client, resolver, discovery channel, or production binding.
2. The deterministic resolver registration entry point has no production caller.
3. The existing Stage 0 CLI has zero acquisition budget and `max_source_tier=0`.
4. The standalone scripts are module demos, not one governed end-to-end run.
5. Recipe 1 graph nodes call `advance_project_phase@1`; the trial must prove that each transition
   reaches its real composed phase handler rather than merely changing a phase label.
6. Direct human account input must converge on the same admitted-account/scoring/deep path as
   discovery without fabricating discovery provenance.
7. No thin HTTP trial surface or client exists.
8. No single report joins provider receipts, claims, verification, C7, costs, and execution state.

## 4. First provider surface

### 4.1 Enabled source keys

| Source key | Sumble endpoint | Trust treatment | Initial fields |
|---|---|---|---|
| `sumble_organizations` | `POST /v9/organizations` | Tier-1 structured API | `core.employee_count`, `core.primary_domain` |
| `sumble_jobs` | `POST /v9/jobs` | Tier-1 structured records | `account.hiring_velocity_eng` |
| `sumble_tech_stack` | `GET /v9/organizations/{id}/techs` | Tier-1 confirmed-used API | `core.primary_tech_stack` |

The exact request and response version is Sumble API `v9`.

### 4.2 Deferred Sumble surfaces

The following are not silently included:

- People and contact reveals;
- Teams;
- Organization Signals;
- Priority Signals;
- Intelligence Briefs;
- saved lists; and
- contact or organization write-back.

They land only after the account-only acceptance gate. Sumble Intelligence Briefs are a later
comparison arm because they are already AI-generated; they must not make the platform appear more
capable than its own grounded derivation path.

### 4.3 Source semantics

Raw identity, firmographic, job, and confirmed-used technology values may become direct claims.
Provider-generated explanations, sales angles, priority labels, summaries, or recommendations
must never be normalized as direct facts. If admitted later, they are explicitly lower-trust or
derived candidates with their own source key and policy.

## 5. Credit and spend contract

Sumble credits are not the same unit as the platform’s `cost_cents`.

The trial therefore records both:

- exact provider `credits_used` / `credits_remaining`; and
- platform monetary cost, only when a configured cents-per-credit conversion is available.

Rules:

1. `CLUE_SUMBLE_API_KEY` is the only Sumble credential.
2. Every live request has a deterministic operation key.
3. A preflight estimate is shown before the first charged request.
4. `--max-sumble-credits` is a hard provider-unit cap for endpoints with a caller-controlled
   maximum (`organizations` and `jobs` in this slice).
5. The provider’s response value is the authoritative realized credit count.
6. A request response is persisted before any dependent claim write is acknowledged.
7. Replaying a completed operation reads its persisted response receipt and does not spend again.
8. A transport failure before a response is retryable.
9. A connection loss after an indeterminate provider outcome is `spend_outcome_unknown`; it is
   never auto-retried without an idempotency or reconciliation guarantee.
10. HTTP `402` pauses/fails as insufficient provider credits; it is not a hard miss.
11. A legitimate no-match is a successful empty result and is not converted into a provider error.
12. Secrets and Authorization headers never enter receipts, artifacts, logs, or reports.
13. `GET /organizations/{id}/techs` has no caller-controlled result limit and charges per returned
    technology. A live tech-stack call therefore requires a separate
    `--allow-unbounded-sumble-tech` confirmation after showing that risk. The ordinary credit cap
    does not claim to bound this call; omitting the flag skips it visibly. Fixture replay never
    requires this approval and never spends provider credits.

The first implementation may use a run-scoped response cache for per-field reuse only after the
response receipt is durable. A process-memory-only cache is insufficient for restart safety.

## 6. Run lifecycle

The CLI presents these durable states:

```text
preflight
  -> stage0_in_progress
  -> product_confirmation_required
  -> icp_drafting
  -> icp_confirmation_required
  -> project_ready
  -> account_resolution_pending
  -> account_resolved | account_not_found | account_review_required
  -> research_admission_required
  -> scoring
  -> tier_checkpoint | direct_research_confirmation
  -> deep_research
  -> verification
  -> review
  -> research_view_ready
```

Background status is additive. The CLI may disconnect at any state and resume using the trial ID.

The initial direct-account path records a human research-admission decision. It does not forge a
Sumble discovery result or silently bypass policy. The later discovery path uses the confirmed ICP
to produce bounded Sumble filters and converges before scoring.

## 7. CLI contract

### 7.1 Process commands

```text
clue trial doctor
clue trial sumble new
clue trial sumble resume <trial-id>
clue trial sumble status <trial-id>
clue trial sumble report <trial-id> [--open]
```

`doctor` checks:

- database connection and exact migration head;
- required server/API reachability;
- real OpenRouter configuration (no accidental stub);
- Sumble credential presence without printing it;
- Sumble-only source policy;
- C7 read availability for the isolated canary workspace;
- writable local report directory; and
- feature/version compatibility.

### 7.2 Interactive commands

```text
/status
/jobs
/report
/confirm-product
/synthesize-icp
/confirm-icp <number>
/account add <domain>
/research <account-id>
/view <account-id>
/claims [field-key]
/evidence <claim-id>
/cost
/quit
```

Later, after the direct-account gate:

```text
/discover preview
/discover run
/accounts
/approve-tier <account-id>
```

### 7.3 CLI purity

The installed CLI package may depend on HTTP/client/rendering libraries. It must not import
`clue_research`, `clue_execution`, `clue_fleet`, `clue_memory`, or database row models.

The CLI may persist only:

- trial ID;
- API base URL;
- opaque session/resume token where required;
- workspace/project/run/subject IDs returned by the API; and
- display preferences.

## 8. HTTP trial surface

The trial API is local-development-only and feature-gated. Proposed routes:

```text
POST   /v1/trials
GET    /v1/trials/{trial_id}
POST   /v1/trials/{trial_id}/turns
POST   /v1/trials/{trial_id}/product:confirm
POST   /v1/trials/{trial_id}/icps:synthesize
POST   /v1/trials/{trial_id}/icps/{proposal}:confirm
POST   /v1/trials/{trial_id}/accounts
POST   /v1/trials/{trial_id}/accounts/{account_id}:research
GET    /v1/trials/{trial_id}/events
GET    /v1/trials/{trial_id}/cost
GET    /v1/trials/{trial_id}/report
```

Research views continue to use the canonical C7 routes. The trial API does not duplicate them.

Every mutating request requires `Idempotency-Key`. Changed scope/body under the same key is a
conflict. Trial IDs are opaque and authorize nothing by themselves.

## 9. Inspection artifact contract

Each local trial export lives at:

```text
.context/sumble-trials/<trial-id>/
  manifest.json
  transcript.md
  timeline.jsonl
  sumble-requests.sanitized.jsonl
  claims.json
  verification.json
  research-view.json
  report.html
  scorecard.md
  failures.json
```

`manifest.json` pins:

- workspace, project, project-run, product, ICP, and subject references;
- recipe/profile/skill/prompt/model versions;
- Sumble API version and selected source-manifest versions;
- allowed and observed source keys;
- credit cap, estimated credits, realized credits, and model budget;
- start/end timestamps and terminal state; and
- content hashes for the exported artifacts.

No exported file is an execution or research authority. Re-exporting reads current governed state.

## 10. Manual acceptance coverage

The executable map owns the detailed cases. At minimum the CLI must demonstrate:

### Provider

- valid organization match;
- unmatched domain;
- closed organization;
- domain/name mismatch;
- parent/subsidiary scope;
- jobs with and without matching engineering functions;
- confirmed technologies and empty stack;
- `401`, `402`, `422`, `429`, transport error, and malformed JSON;
- exact credits and no secret leakage.

### Stage 0 and ICP

- useful two-way interview;
- facts/preferences/project choices routed to the correct stores;
- corrections and supersession;
- human-only product/ICP confirmation;
- durable resume;
- explicit unknowns and missing evidence.

### Account research

- canonical identity;
- direct human admission;
- Sumble-only source trace;
- scoring and tier/deep decision;
- direct versus derived claims;
- complete support graph;
- unsupported derivation rejection;
- empty coverage without filler.

### C7

- exact project/run/product/subject scope;
- current direct and derived statements;
- fit/intent owner references;
- explicit coverage gaps;
- evidence actions without locators;
- deterministic repeat read;
- restricted/redacted/stale/conflict states;
- reference-only snapshot and governed recheck.

### Durability

- quit/restart Stage 0;
- crash before and after provider response persistence;
- duplicate idempotency key;
- changed payload conflict;
- crash during agent turn;
- crash before verification;
- no duplicate claim or provider spend on replay.

## 11. What manual CLI testing cannot close

The trial does not replace automated gates for:

- migration downgrade/reversibility;
- high-contention concurrency;
- exhaustive cross-tenant attacks;
- the full DSAR/retention surface matrix;
- query-count ceilings and load;
- secret scanning;
- production auth/RBAC/SSO;
- cloud deployment and alerting; or
- frontend accessibility, responsive layout, dossier comprehension, and visual hierarchy.

The actual frontend remains required to validate product UX.

## 12. Implementation slices and gates

### T0 — Contract and executable map

Deliver this plan, the JSON acceptance map, and a schema/test that rejects incomplete, duplicate,
unclassified, or non-Sumble first-wave cases.

Gate: every claimed CLI capability is `full`, `partial`, or `none`, and every `partial`/`none`
case names its required companion test surface.

### T1 — Sumble provider contracts

Deliver:

- secret/config contract;
- three source manifests;
- versioned typed request/response models;
- HTTP client over the shared fault taxonomy;
- pure normalizers;
- sanitized recorded fixtures;
- source registration/binding tests;
- credits/cap/replay receipt contract.

Gate: fixture-driven Organizations, Jobs, and Tech Stack calls normalize only registered fields,
with correct evidence, costs/credits, hard misses, and errors.

### T2 — Operational direct-account spine

Deliver:

- one durable direct-account intake/admission operation;
- per-run account lookup and Sumble binding at the API composition root;
- production phase-handler proof from Recipe 1 transition through C7;
- Sumble-only source-policy assertion;
- account-only committee posture that is explicit rather than a silent misconfiguration.

Gate: one fixture-backed run reaches a real C7 account view without invoking a standalone script
or unapproved source.

### T3 — Local HTTP API

Deliver feature-gated trial routes, idempotency, status/events, and canonical C7 links.

Gate: an HTTP client can create, resume, converse, confirm, add an account, research it, and fetch
the resulting view.

### T4 — Thin CLI

Deliver process commands, interactive commands, progress display, interruption/resume, and strict
HTTP-only dependency enforcement.

Gate: CLI process restart loses no authoritative state and no domain package enters its import
graph.

### T5 — Report and scorecard

Deliver deterministic HTML/JSON export, source/cost/coverage/verification views, and a human
quality rubric.

Gate: every visible report statement links to a C7 item, owner reference, or explicit
non-authoritative diagnostic record.

### T6 — Live Sumble canary

Run the fixed corpus under a small hard credit cap. Do not add Exa while resolving defects.

Gate to Exa:

- observed acquisition sources equal the Sumble-only allowlist;
- every promoted fact has evidence;
- every promoted derivation has complete support;
- zero fabricated or unsupported promoted claims;
- realized credits reconcile to response receipts;
- restart/retry causes no duplicate provider spend;
- C7 renders the real persisted state;
- weak coverage remains visibly weak; and
- the founder accepts the research usefulness score across the corpus.

## 13. Fixed decisions

1. Separate branch: `platform/clue-trial`.
2. REST/OpenAPI integration, not MCP.
3. Direct account before discovery.
4. Organizations, Jobs, and confirmed Tech Stack first.
5. No terminal signup/login.
6. OpenRouter is a reasoning runtime, not a factual source.
7. Sumble Intelligence Briefs, Signals, People, and Teams are deferred.
8. CLI communicates through HTTP only.
9. HTML/JSON inspection export is mandatory.
10. No Exa until the Sumble baseline is accepted.
11. No production feature flag is enabled by default.
12. No live Sumble spend occurs without an explicit user-run canary and hard credit cap.
