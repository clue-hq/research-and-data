# Phase C7 implementation plan — structured research views

**Date:** 2026-07-27
**Branch:** `platform/c7-research-views`
**Base:** completed C6 head `7755bea`
**Binding child spec:** [PC-C7](../../specs/PC-C7-research-views-derivations-and-handoff.md)
**Parent scope:** [PC §C7–C8](../../specs/PC-phase-c-agentic-layer.md)

## 1. Purpose

Implement C7 as the backend research-view layer for the current account and contact experience.
The plan deliberately does not build a document-oriented dossier backend. It builds structured,
typed, provenance-resolving views that the frontend can render as ordinary product pages.

The implementation must remain synchronized with five product facts:

1. the account page combines identity, research, scoring, committee, coverage, and activity, but
   those species keep their own authorities;
2. the contact page needs rich research while distinguishing display safety from outreach safety;
3. every visible research statement must resolve to a direct claim or supported derived claim;
4. the screenshots' wrong-person and wrong-account content are adversarial failures, not acceptable
   mock-data shortcuts;
5. the plan/approval screen is downstream and consumes C7 references; C7 does not own it.

This document is the session-by-session runbook. At the end of every C7 session, update the active
slice, evidence, decisions, failures, and next exact entry point in `_memory/`.

---

## 2. Non-negotiable implementation posture

- Work only on `platform/c7-research-views`; do not push without explicit instruction.
- Keep the claim store as the only research truth substrate.
- Preserve the existing C5 execution journal, C6 deepagent, C1 evaluator, M9 verification, M10
  policy, M12 narrative, identity, scoring, coverage, and activity authorities.
- Perform cross-package wiring at `platform/api`; do not make research sibling packages import one
  another.
- Use typed references in tools, journal payloads, events, snapshots, and handoffs.
- Never persist a canonical Markdown/HTML dossier body.
- Never expose object-storage keys or mint a signed URL without an API-root authorization service.
- Use additive immutable writes. Re-check and refresh create new rows/receipts.
- Prefer an explicit empty/unknown/restricted state over generated filler.
- Treat DSAR reachability as part of each storage task, not a final patch.
- Use Alembic-generated hash revision ids; preserve exactly one head; run clean DB smoke.
- Commit each green slice locally as a coherent checkpoint.

---

## 3. Current substrate and gaps

### 3.1 Reuse as-is

| Existing seam | C7 use |
|---|---|
| `Claim`, `CurrentValue`, claim store, field registry | direct research truth |
| `Claim.product_id` and tenant-private scope | product isolation |
| field `equality_mode` + `values_agree` | conflict semantics |
| M9 freshness, faithfulness, identity binding | eligibility inputs |
| M10 use/appropriateness and retention sweep | display/outreach/retention inputs |
| C1 `ResearchCoverage`/attempt history | coverage and gaps |
| M12 `ValueNarrativeItem`, `AccountHandoff` | existing narrative/handoff inputs |
| `HandoffCommitteeReader` protocol | production adapter target |
| C5 exact tools, operation ids, journal/outbox | compose/re-check execution |
| C6 governed deepagent/workspace | optional governed re-research request path |
| `StorageBackend` | storage only, behind new access policy |
| platform projections/SSE | read/event surfaces |

### 3.2 Gaps C7 must close

- no derived claim flavor, normalized derivation edges, or entailment verdict;
- no structured account/contact research-view contract;
- no reference-only composition receipt;
- no shared resolver for statement eligibility/dependency staleness;
- no authorized evidence-action service;
- no snapshot re-check operation;
- no production `HandoffCommitteeReader`;
- existing `account_handoff.payload` copies a materialized body and needs an explicit DSAR-safe
  disposition;
- existing faithfulness rationale lacks the required personal-text redaction path;
- old dossier API/PRD language assumes a document body;
- per-product fit/contact-class behavior needs a consumer-level contract and negative tests;
- account/contact frontend contamination fixtures are not yet in the eval suite.

---

## 4. Target flow

```text
canonical entity ─────────────┐
scoring result ───────────────┤
committee/contact graph ──────┤
C1 coverage/gaps ─────────────┤
activity projection ──────────┤
                              ▼
current direct claims ──► eligibility/dependency resolver
                                  │
support claims ─► entailment ─► derived claims
                                  │
                                  ▼
                         ResearchViewComposer
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
             live account/contact        reference-only snapshot
                  projection                   receipt
                    │                           │
                    ├──── evidence action ──────┤
                    │                           └── re-check
                    ▼
             frontend page / downstream plan-content consumers
```

The aggregation arrows are reads. Writes remain with their existing owners.

---

## 5. Slice sequence

| Slice | Outcome | Prerequisite closed |
|---|---|---|
| C7.0 | contract, schema, ownership, fixtures frozen | all C7 ambiguities |
| C7.1 | prerequisite hardening | equality, expiry, rationale, product/class |
| C7.2 | derivation + entailment substrate | supported derived statements |
| C7.3 | structured account/contact view composition | frontend read contract |
| C7.4 | reference snapshots + evidence actions | safe version/evidence semantics |
| C7.5 | additive re-check | refresh/staleness semantics |
| C7.6 | production committee + handoff cutover | real narrative emit |
| C7.7 | tools, API, projections, events, compatibility | product integration surface |
| C7.8 | adversarial, DSAR, and repository closeout | complete C7 proof |

Slices are serial on this branch because core enums, migrations, API aggregation, and DSAR tests
overlap. Isolated fixture/eval work may be prepared in parallel only if a future session explicitly
allocates separate worktrees and reserves shared files.

---

## 6. C7.0 — contract freeze and executable fixture map

**Status:** COMPLETE — implemented and verified 2026-07-27.

### Goal

Turn the binding child spec into exact implementation types and fixtures before migration or tool
code.

### Tasks

1. Add frozen cross-package contracts under `libs/clue-core/clue_core/research_view.py`:
   - subject refs;
   - statement kinds and states;
   - support roles;
   - evidence action descriptors;
   - section/block kinds;
   - account/contact view DTOs;
   - snapshot/re-check reference outputs;
   - reader/judge/composer protocols.
2. Add only genuinely shared enums to `clue_core.enums`; avoid importing implementation packages.
3. Write contract tests for:
   - strict schemas (`extra="forbid"`);
   - frozen values;
   - direct statement has no supports;
   - derived statement requires ordered supports;
   - a hidden/redacted statement cannot carry a value/evidence payload;
   - a personalization item requires outreach eligibility;
   - product scope consistency;
   - reference-only tool outputs.
4. Create sanitized fixture manifests derived from the frontend requirements:
   - account fixture with identity, fit reasons, insights, committee, activity, and gaps;
   - contact fixture with identity, overview, evidence, quotes, career/education/publications, and
     safe personalization;
   - explicit negative fixtures for wrong person, wrong pronoun/entity, medical/sensitive
     personalization, wrong account activity, and cross-product bleed.
5. Add a source-species mapping file/test so fields cannot be accidentally authored by the
   composer:
   - identity-owned;
   - score-owned;
   - claim/derivation-owned;
   - committee-owned;
   - coverage-owned;
   - activity-owned.
6. Confirm exact nine-block compatibility mapping and legacy alias policy.
7. Record the `account_handoff.payload` migration decision before C7.4:
   default is legacy + subject-indexed purge/rebuild first, followed by reference-only replacement
   if no live consumer requires the body.

### Expected files

```text
libs/clue-core/clue_core/research_view.py
libs/clue-core/clue_core/enums.py
tests/unit/core/test_research_view_contracts.py
tests/fixtures/research_views/...
tests/architecture/test_research_view_species.py
```

### Gate

- all contract tests green;
- import contract green;
- fixture manifests contain no proprietary/raw attachment text;
- no DB migration or tool handler exists before this gate.

### Checkpoint

Commit: `feat(c7): freeze structured research-view contracts`

---

## 7. C7.1 — prerequisite hardening

### Goal

Close every C8 item needed by a C7 read consumer before that consumer lands.

### C7.1a Conflict equality

The current merge code already reads field `equality_mode` and uses shared `values_agree`. Do not
rewrite it.

Add a joint test:

1. insert two authoritative values that differ in canonical JSON but agree under `numeric_tol` or
   `semantic`;
2. prove `current_value.conflict` and the corroboration surface agree;
3. compose a provisional item-state adapter and prove it does not show `review_required`.

Add the converse disagreement test.

### C7.1b Retention expiry

Prove and harden this order:

```text
retention sweep/tombstone
  → current-value selector
  → derivation dependency resolver
  → research-view composition
```

Add a fail-closed selector rule so a known retention-expired claim cannot be returned even if a
caller did not run the sweep immediately before the read. Preserve freshness `stale` as distinct
from retention `expired`.

Tests:

- expired personal claim cannot win or display;
- stale non-expired claim can be shown only with explicit stale state/policy;
- an expired support invalidates a derivation;
- account/contact list and detail agree after expiry.

### C7.1c Faithfulness rationale DSAR

Add a reversible migration that makes the existing rationale nullable and records one-way
redaction metadata if the current schema does not permit it.

Implement the redaction path through the existing DSAR owner:

- redact rationale to `NULL`;
- retain verdict/model/prompt/trace metadata when lawful;
- mark redaction time/reason;
- index or map subject reachability without copying the rationale elsewhere.

The test must insert a unique personal sentinel into rationale, erase the subject, and prove the
sentinel is absent from raw selected rows and serialized DSAR outputs.

### C7.1d Evidence presign policy seam

Define `EvidenceAccessAuthorizer`/`EvidenceAccessService` contracts now; implementation lands in
C7.4. Add a dependency test that no C7 route/tool imports or calls `StorageBackend.presign`
directly.

### C7.1e Product fit and contact class

Audit the current score record and committee/contact fields using real fixtures.

Bind the minimum additive contract:

- request `product_id` is optional but exact when present;
- fit/narrative claims with a product id must match;
- product-neutral facts remain reusable;
- contact class is a registered optional field/value with provenance;
- missing class is `unknown`, never guessed from title/persona;
- C7 reads score evidence; it does not calculate fit.

If existing score rows cannot identify product scope unambiguously, add the smallest scoring-owned
schema/contract delta before the view consumes them. Do not encode fit only in a C7 JSON payload.

### Gate

- named tests for all five prerequisite groups;
- one Alembic head;
- migration upgrade/downgrade/upgrade smoke;
- no C7 view can consume a prerequisite without its test.

### Checkpoint

Commit: `fix(c7): close research-view prerequisite gaps`

---

## 8. C7.2 — derivation and entailment substrate

**Status:** COMPLETE — implemented and verified 2026-07-27.

### Goal

Represent expert interpretation as immutable claims supported by other claims and judged for
entailment.

### C7.2a Core and schema

1. Add `ClaimFlavor.DERIVED`.
2. Update claim validation:
   - derived claim is field-shaped but carries no discovery envelope;
   - its external `source_url` may be null because supports are its evidence;
   - it remains tier-4/model-authored where applicable;
   - it is tenant/product scoped consistently with its supports;
   - it cannot be used as a direct current-value winner.
3. Update DB enum/checks and enum-parity tests.
4. Add hash-id migration for:
   - `claim_derivation`;
   - `entailment_verdict`;
   - indexes for derived/support claim lookup and idempotency;
   - immutable/append-only protection matching existing claim/verdict conventions.

### C7.2b Claimstore service

Implement a claimstore-owned `DerivationStore`:

- create an ordered support set transactionally;
- validate live claim ids;
- reject self-edge and cycle;
- enforce subject/relation rules;
- enforce workspace/reuse/product compatibility;
- compute stable support-set hash;
- read dependencies and reverse dependencies;
- list affected derivations for supersede/erasure/re-check;
- never return copied claim bodies across the seam.

Concurrency:

- stable operation id;
- advisory/row locks in deterministic claim-id order;
- duplicate operation returns the existing set;
- no partially-created support set after a crash.

### C7.2c Entailment judge

Add a verification-owned `EntailmentJudge` implementing the core protocol:

- strict structured response;
- fenced untrusted support/value input;
- bounded reason codes;
- requested and answering model attribution;
- no free-text rationale persistence;
- tracing and cost attribution;
- idempotent verdict caching;
- malformed/model-error fail closed.

### C7.2d Promotion/eligibility

At API composition, build a `DerivedClaimService` that:

1. creates the proposed derived claim and support set;
2. invokes entailment only after structural gates;
3. computes conservative confidence;
4. applies existing verification/governance policy;
5. writes accepted/rejected state;
6. returns ids only.

Do not place this orchestration inside `claimstore` or `verification`.

### C7.2e Dependency resolver

Implement a pure resolver that maps support state to:

- eligible/fresh;
- stale/recheck-required;
- review-required conflict;
- unavailable;
- rejected;
- redacted/restricted.

It must traverse bounded acyclic dependencies and memoize by claim id. Set a hard depth and node
limit even though write-time cycle checks exist.

### Tests

- direct one-support and multi-support derivations;
- conservative confidence;
- unsupported/malformed/error verdict cannot promote;
- self-cycle, indirect cycle, missing support, duplicate edge;
- wrong workspace, product, subject, and support role;
- wrong-person contact support;
- superseded/rejected/expired/erased support;
- deterministic hash/idempotent retry/crash boundary;
- append-only DB enforcement;
- no derived claim in factual `current_value`.

### Gate

- migration smoke;
- DB concurrency/idempotency tests;
- verification negative fixtures;
- dependency/import-contract green.

### Checkpoint

Commit: `feat(c7): add governed claim derivations and entailment`

---

## 9. C7.3 — account and contact research-view composition

**Status:** COMPLETE — implemented and verified 2026-07-27.

### Goal

Create deterministic live views matching the frontend's information needs without building a
frontend or authoring data owned elsewhere.

### C7.3a Injected readers

Define/implement body-free reader protocols:

- `CanonicalSubjectReader`;
- `DirectClaimReader`;
- `DerivedClaimReader`;
- `FitResultReader`;
- `CommitteeViewReader`;
- `CoverageViewReader`;
- `ActivityReferenceReader`;
- `StatementGovernanceReader`.

Only API-root adapters may aggregate concrete sibling implementations.

### C7.3b Statement resolver

For each candidate item:

1. verify subject and workspace;
2. resolve direct/derived state;
3. apply current verification/freshness/conflict state;
4. apply display and outreach decisions separately;
5. redact value when unavailable/restricted;
6. produce evidence action descriptors, not URLs;
7. attach exact refs and reason codes.

Unknown and unresearched fields are emitted as typed gaps when the schema expects them.

### C7.3c Account composer

Compose stable sections:

- identity reference;
- research status;
- summary/about;
- overall fit and criterion reasons;
- insights/signals/evidence;
- committee/contact references;
- activity references;
- coverage/gaps.

Rules:

- never author identity, fit, or activity;
- preserve negative and unknown score criteria;
- separate product-neutral and product-scoped items;
- no activity from another account;
- committee list and contact detail use the same subject ids.

### C7.3d Contact composer

Compose stable sections:

- identity/employer/committee role;
- professional overview and signals;
- verified evidence/quotes;
- registered background/career/education/publication/award groups;
- governed personalization candidates;
- coverage/gaps.

Rules:

- strong target lock;
- contact claims cannot be inferred from same-name search results;
- account-context supports require typed relation;
- sensitive facts never enter personalization;
- display eligibility does not imply outreach eligibility;
- empty categories remain explicit and non-embarrassing.

### C7.3e Block adapter

Map semantic sections/items to the nine treaty blocks. Test lossless reference preservation:

- every source statement id appears exactly where expected;
- adapter adds no prose;
- reverse provenance lookup is complete;
- frontend grouping changes do not affect source-state hash.

### Tests

- golden account/contact fixture resolution;
- deterministic ordering and hashing;
- direct and derived statements;
- all availability/freshness/governance states;
- wrong-person and wrong-account fixtures;
- source-species ownership;
- product isolation;
- no unprovenanced text fields;
- schema-version compatibility.

### Gate

- fixture views serialize exactly;
- no model call occurs during composition;
- no new truth/body store;
- unit/property/integration/import tests green.

### Checkpoint

Commit: `feat(c7): compose structured account and contact research views`

---

## 10. C7.4 — reference-only snapshots and evidence actions

**Status:** COMPLETE — implemented and verified 2026-07-28.

### Goal

Support “versions” and evidence click-through without copying research bodies or weakening access
control.

### C7.4a Snapshot storage

Add hash-id migration for:

- `research_view_snapshot`;
- ordered section/item/reference rows;
- reachable-subject rows;
- optional supersession relation;
- indexes for scope, subject, product, and DSAR traversal.

Store only ids, enums, policy/config pins, order, and hashes. Add DB/schema tests that reject value,
evidence-span, source-body, rationale, or rendered-body columns/keys.

Snapshot creation:

1. compose the live view;
2. reduce it to a reference receipt;
3. compute source-state/composition hashes;
4. insert idempotently under operation id;
5. return snapshot/view refs only.

Snapshot resolution:

1. authorize current scope;
2. load refs;
3. re-resolve each ref under current erasure/policy;
4. surface unavailable/redacted/stale differences;
5. never resurrect the old text.

### C7.4b Evidence access

Implement API-root `EvidenceAccessService`:

- accept workspace, actor, statement/claim id, desired action;
- load claim and validate exact subject/project relation;
- verify source/artifact state and display policy;
- public URL: allow only the stored normalized source URL and safe scheme;
- API evidence: return typed provider/source metadata permitted by contract;
- artifact: validate live artifact/media/purpose and mint a short server-capped preview;
- erased/restricted/missing: unavailable/redacted;
- audit access without logging evidence bodies or signed URLs.

Signed URLs are generated only at request time and never stored in a snapshot/event/tool result.

### C7.4c Existing handoff payload disposition

Inventory live readers of `account_handoff.payload`.

Preferred cutover:

- retain row identity/version/current pointer;
- store/fetch a reference receipt for new C7 writes;
- support legacy rows through an isolated adapter;
- subject-index and purge/rebuild legacy personal payloads;
- stop producing new body copies once all callers use references.

If immediate replacement is unsafe, document the bounded compatibility interval and enforce
subject-indexed erasure before any C7 closeout claim.

### Tests

- snapshot replay after claim supersede/erasure;
- snapshot contains no sentinel text;
- cross-workspace/project/subject evidence denial;
- storage-key leakage scan;
- expired signed-link renewal denied after erase;
- public/API/artifact/unavailable action matrix;
- idempotent compose under retry/crash;
- legacy handoff DSAR sentinel.

### Gate

- migration smoke;
- snapshot and evidence security suite;
- no direct `presign` consumer outside the authorized service;
- DB serialized-payload scan green.

### Checkpoint

Commit: `feat(c7): add reference-only snapshots and scoped evidence access`

### Implementation closeout (2026-07-28)

- Added append-only `research_view_snapshot` receipts with ordered section/item/support/action
  references, exact scope pins, source/composition hashes, reachable-subject rows, idempotent
  operation identity, and workspace-safe supersession. Snapshot tables contain no claim values,
  evidence spans, source bodies, rationales, rendered bodies, locators, or signed URLs.
- Added deterministic snapshot creation and live resolution. Resolution intersects the saved
  reference set with a fresh C7.3 composition, re-reads current claim/tombstone state, and emits
  unavailable, redacted, restricted, or stale state instead of reconstructing historical text.
- Added the API-root evidence-access service as the only C7 presign consumer. It validates the
  exact workspace/project/snapshot/action/statement/claim/subject relation, applies current
  authorization and retention/erasure state, caps artifact previews at 300 seconds, returns opaque
  capabilities, and writes body-free access audits.
- Kept `account_handoff.payload` as a bounded compatibility store because the C7.6 production
  committee handoff and C7.7 serving cutover have not happened. New C7 snapshots never write body
  copies. Existing handoff rows now have an optional snapshot pointer, a subject index backfilled
  from account/committee/provenance references, and a one-way payload purge marker.
- Live-reader inventory: `narrative.handoff_store` is the central legacy payload decoder used by
  `HandoffService`, the HTTP surface, and the toolbelt; `review.disposition_store` has one isolated
  direct SQL read for legacy ICP/provenance context. C7.6/C7.7 must move those callers to reference
  receipts before stopping the legacy writer and removing payload decoding.
- DSAR and objection handling purge any indexed legacy handoff payload that can reach the erased
  subject. Legacy writes refuse any account, committee member, or provenance-reachable claim
  subject already tombstoned, closing the erased-subject resurrection path during compatibility.
- Verification passed: targeted snapshot/evidence/DSAR/legacy suites, the full DB-enabled pytest
  suite, Mypy across 429 source files, scoped Ruff, one-head Alembic validation, clean isolated
  upgrade → downgrade → upgrade, and a manual pre-C7.4 legacy-row backfill check. The umbrella
  `make check` formatter passed; its lint stage also scans unrelated untracked `.claude/` and
  `.codex/` scripts and stopped on their pre-existing `T201` findings, while all C7.4 changed files
  pass Ruff.

---

## 11. C7.5 — additive re-check and refresh

### Goal

Let users refresh a stored view safely without introducing a second verifier or overwriting
history.

### C7.5a Contract

Input:

- workspace/project/subject;
- snapshot id;
- optional closed section kinds;
- optional `request_research` boolean;
- stable operation id.

Not accepted:

- custom verification thresholds;
- disabled identity/use gates;
- arbitrary prompts/models;
- direct claim values;
- arbitrary field/source expansion;
- signed URL TTL;
- “best quality” flags that weaken invariants.

Output is a reference-only change report:

- old/new snapshot ids and hashes;
- unchanged/added/removed/stale/restricted item ids;
- requested operation ids;
- reason codes;
- fetch reference.

### C7.5b Execution

1. Load and authorize the old receipt.
2. Resolve present dependency/policy state.
3. Compute affected fields/derivations.
4. Run existing verification/freshness/use checks.
5. When permitted, request bounded re-research through an existing C5 recipe/C6 governed tool
   operation; never call resolvers directly from the re-check handler.
6. Compose a new reference receipt.
7. Append change report/outbox event.
8. Return existing result on retry.

### C7.5c Section staleness

Propagate claim/derivation changes to section ids using reverse reference indexes. Emit body-free
`research_view.section_stale`; do not rebuild synchronously in an unrelated write transaction.

### Tests

- no-op re-check;
- stale support, superseded support, policy restriction, and erased support;
- bounded section selector;
- request validation rejects policy weakening;
- re-research uses existing durable operation and admission gates;
- crash after operation request/before snapshot;
- crash after snapshot/before event;
- replay returns one logical result;
- change report contains no bodies.

### Gate

- crash matrix;
- tool replay certification;
- no duplicate spend/writes/events;
- existing verification authority unchanged.

### Checkpoint

Commit: `feat(c7): add governed research-view recheck`

---

## 12. C7.6 — production committee reader and real handoff

### Goal

Replace the M12 in-memory/placeholder committee path with a production, governed reader and prove
real narrative emission.

### Tasks

1. Implement `HandoffCommitteeReader` at API composition using:
   - canonical surviving contacts;
   - committee/persona/role claims;
   - product scope;
   - identity binding;
   - display/outreach use decisions;
   - erasure/retention state.
2. Return references/typed values required by M12; never make narrative import identity,
   verification, or compliance.
3. Use one shared contact eligibility resolver for:
   - account committee list;
   - contact detail;
   - M12 handoff;
   - personalization eligibility.
4. Compose real `AccountHandoff`/C7 view references.
5. Emit the existing handoff outbox event only after materialization/receipt success.
6. Remove `narrative_emit_skipped` only when:
   - an eligible committee produces real output;
   - empty/ineligible committee behavior is explicit;
   - retry/crash behavior is proven.
7. Ensure product-scoped fit and contact relevance agree with the requested product.

### Tests

- real account + eligible committee + narrative emit;
- weakly-bound contact excluded;
- displayable but outreach-denied contact shown appropriately but not selected for personalization;
- erased/merged-loser contact excluded or redirected to survivor;
- product A contact/narrative not emitted for product B;
- empty committee honest state;
- outbox idempotency/crash recovery;
- legacy and C7 handoff reference parity.

### Gate

- production reader integration green;
- no in-memory fake in production composition;
- HANDOFF gap marker removed only in the same green checkpoint;
- DSAR and product isolation green.

### Checkpoint

Commit: `feat(c7): cut production committee research into handoff`

---

## 13. C7.7 — tools, API, projections, events, and compatibility

### Goal

Expose the completed C7 capability to the product and governed agent surfaces.

### C7.7a Toolbelt

Register exact descriptors:

- `compose_dossier@1`;
- `get_research_view@1`;
- `recheck_research_view@1`.

Requirements:

- strict input/output models;
- exact version pin;
- correct effect/replay policy;
- stable operation id;
- body-free result;
- workspace/project/subject authorization in production handler;
- central tool aggregation and replay audit.

The `compose_dossier@1` description explicitly defines dossier as a structured research-view
receipt. Do not add a second compose implementation under a newer name in C7.

### C7.7b API

Implement account/contact live-view, snapshot, re-check, and evidence-action routes from the child
spec.

HTTP behavior:

- stable schema version and ETag/source-state hash;
- pagination for large committee/evidence/coverage groups;
- not-found semantics for cross-scope/erased subject;
- typed unavailable/redacted states;
- no source body or permanent URL;
- idempotency header for mutating compose/re-check;
- request product id validated against project/product context.

### C7.7c Projections

Add body-free list/status projections where needed:

- research-view availability/status per account/contact;
- freshness/stale section counts;
- coverage summary;
- latest snapshot id/hash;
- re-check state.

Detailed values remain on authorized detail reads; list projections do not duplicate research
bodies.

### C7.7d Events/SSE

Aggregate canonical events centrally and expose them through the existing SSE substrate:

- `research_view.updated`;
- `research_view.section_stale`;
- `research_view.recheck_completed`.

Add schema tests proving payloads are scope/ref/reason-only.

### C7.7e Legacy compatibility

If the older frontend treaty endpoints are still consumed:

- route `/dossier` to the same view handlers;
- translate response names additively;
- emit legacy dossier event alias from the same outbox fact;
- mark deprecation metadata;
- do not create a document table, alternate snapshot, or renderer.

Update the frontend backend-contract document in the linked plan directory only if the user asks
to change that external source; the repository contract remains authoritative for backend work.

### Tests

- route auth and tenant isolation;
- exact tool replay;
- schema snapshots;
- pagination/order/hash stability;
- SSE resume and no body leakage;
- legacy alias parity;
- C6 agent can receive/refetch refs but not bypass policy;
- downstream block consumer fixture.

### Gate

- API/tool/projection/event integration suite;
- central aggregation counts updated;
- tool authority and replay audits green;
- legacy and canonical surfaces share ids/hashes/authorization.

### Checkpoint

Commit: `feat(c7): expose research views through tools and API`

---

## 14. C7.8 — adversarial, DSAR, and repository closeout

### Goal

Prove the whole story, remove temporary paths, and leave an exact C8 handoff.

### C7.8a Adversarial fixture suite

The suite must include:

- same-name wrong contact;
- wrong employer;
- wrong account activity;
- inconsistent pronoun/identity signals;
- medical/sensitive personal fact;
- public personal fact that is displayable but not outreach-eligible;
- weak binding;
- cross-workspace support;
- cross-product fit/narrative;
- invalid cross-entity support role;
- prompt-injection content inside a support/evidence span;
- stale, superseded, rejected, expired, erased, and conflicted dependencies.

Expected result is exclusion/restriction/unknown with reason codes, never a plausible replacement.

### C7.8b Extended DSAR sentinel

Use unique sentinels across:

- direct personal claim/evidence span;
- derived claim value;
- any legacy faithfulness rationale;
- evidence artifact;
- research-view snapshot;
- re-check report;
- legacy `account_handoff.payload`;
- projection cache;
- outbox/SSE payload;
- C6 workspace/history reference.

After erasure, scan every reachable serialized surface. Reference rows may remain for audit only
when they cannot resolve or reveal the subject/body.

### C7.8c Quality and performance

Measure:

- account/contact view query count;
- dependency resolver depth/node caps;
- snapshot composition latency;
- coverage/committee pagination;
- evidence action authorization latency;
- re-check batch bounds.

Eliminate N+1 claim/support reads with batch selectors. Do not add an unsafe body cache to meet
latency.

### C7.8d Documentation and operations

Update:

- Phase C parent status;
- specs index;
- architecture O11 ruling;
- C7 runbook: compose/re-check failures, stale sections, evidence denial, DSAR;
- migration/rollback notes;
- C7 closeout memory;
- C8 handoff with only genuinely remaining work.

### C7.8e Repository verification

Run, in order:

1. targeted unit and contract tests;
2. targeted DB integration and crash tests;
3. adversarial/eval suite;
4. extended DSAR sentinel suite;
5. import/dependency-contract tests;
6. enum/schema parity;
7. lint and type checks;
8. `alembic heads` (exactly one);
9. clean throwaway-DB upgrade → downgrade → upgrade;
10. full repository check with DB-enabled tests;
11. diff/status review against `origin/main` and branch base.

Record exact commands, counts, skipped tests, environment caveats, and failures in `_memory/`.

### Exit gate

C7 closes only when every acceptance criterion in the child spec has evidence and no temporary
document-body, fake-reader, direct-presign, or skipped-handoff path remains.

### Checkpoint

Commit: `docs(c7): close structured research-view implementation`

---

## 15. Test matrix

| Boundary | Positive proof | Negative proof |
|---|---|---|
| subject | exact account/contact | same name, wrong employer/account |
| provenance | direct claim or supported derivation | unreferenced prose |
| derivation | all supports live and entailing | cycle/missing/unsupported support |
| verification | accepted/fresh | rejected/expired/stale policy |
| personal data | strong binding + allowed display | weak/restricted/redacted |
| outreach | explicit allowed use decision | verified-but-disallowed personalization |
| product | matching product or neutral fact | product A leaked into B |
| evidence | authorized public/API/artifact action | key leak/cross-scope/erased artifact |
| snapshot | refs re-resolve | copied body resurrects old text |
| re-check | additive/idempotent | mutation/gate weakening/double spend |
| handoff | real eligible committee emit | fake/empty/erased committee |
| DSAR | all sentinels gone/unresolvable | legacy payload/event/workspace survivor |

---

## 16. Rollback and feature activation

Use separate default-off feature flags for:

- C7 research-view read routes;
- snapshot compose;
- evidence actions;
- re-check;
- production handoff cutover;
- legacy dossier alias.

Activation order:

1. shadow-compose fixtures/internal accounts;
2. compare C7 direct refs with existing handoff/provenance;
3. enable read-only account/contact views;
4. enable snapshots;
5. enable evidence actions;
6. enable re-check for canary workspaces;
7. cut production committee/handoff;
8. enable legacy adapter only where measured demand exists.

Rollback disables routing/handlers, not migrations or immutable rows. New receipts/verdicts remain
auditable and inert. Never roll back by deleting claims or rewriting history.

---

## 17. Known risks and guards

| Risk | Guard |
|---|---|
| “dossier” drifts back into a document table | schema tests forbid body columns; compatibility alias uses same service |
| frontend treats aggregate response as one truth species | explicit owner/source metadata and species contract tests |
| wrong-person personal research | exact subject lock, support roles, binding/use gates, adversarial fixtures |
| verified fact becomes creepy personalization | separate display/outreach decisions |
| derived prose outlives supports | live dependency resolution + reverse indexes + re-check |
| saved snapshot resurrects erased text | reference-only receipt and current-policy resolution |
| signed evidence URL escapes scope | single API-root authorizer, short TTL, no key/URL persistence |
| C7 recomputes fit or committee | injected authoritative readers and architecture test |
| product facts bleed together | exact product validation and negative fixtures |
| handoff body remains a DSAR orphan | explicit C7.4 cutover/purge gate |
| re-check becomes a second agent loop | durable existing operation only; no resolver/model authority in handler |
| N+1 reads prompt unsafe caching | batch selectors and bounded resolver, no body cache |

---

## 18. Session closeout template

At every checkpoint, add/update the C7 memory note with:

```text
Slice:
Branch/head:
Outcome:
Files/schema changed:
Decisions:
Verification commands and results:
Failures/caveats:
Feature flag state:
Next exact task:
Do not start next slice until:
```

The final C7 closeout additionally records migration head, full-suite totals, feature flags,
rollback procedure, legacy-adapter state, DSAR proof, and the exact next Phase C/C8 work.
