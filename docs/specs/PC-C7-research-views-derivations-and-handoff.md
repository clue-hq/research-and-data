# C7 — structured research views, derivations, and production handoff

**Status:** ACTIVE — C7.0–C7.5 complete; C7.6 production committee reader and handoff next
**Layer:** Phase C / harness build step 7
**Depends on:** C1–C6 complete; M9 verification; M10 governance; M12 narrative/handoff
**Branch:** `platform/c7-research-views`
**Detailed plan:** [2026-07-27 Phase C7 implementation plan](../superpowers/plans/2026-07-27-phase-c7-research-views.md)

**Architecture authority:** the
[harness architecture](../architecture/clue-hq-harness-architecture-and-requirements.md), especially
REQ-04, REQ-05, REQ-14–REQ-16, O11, and build step 7; the
[Phase C parent](./PC-phase-c-agentic-layer.md) §C7–C8; the
[platform-agent runtime](../architecture/clue-hq-platform-agent-runtime.md); the
[content and scaling contract](../architecture/clue-hq-content-and-artifact-scaling.md); the
[compliance architecture](../architecture/clue-hq-compliance-and-personal-data.md); and the
[M12 handoff spec](./M12-value-narrative-and-handoff.md).

This child spec is the binding engineering contract for C7. It incorporates the founder's
2026-07-27 clarification of the account and contact experience. It refines the older use of
“dossier” in REQ-05 without changing the claim-store, verification, governance, or downstream
content boundaries.

---

## 1. Product ruling: “dossier” is a research view, not a file

The C7 product is a structured, provenance-resolving backend read model used by normal account and
contact pages.

It is **not**:

- a canonical Markdown, HTML, PDF, or rich-text document;
- an opaque generated report body copied into a second store;
- a frontend page implementation;
- a replacement for canonical entities, scoring, coverage, activity, or committee ownership;
- a content artifact or campaign plan;
- a free-text editing surface.

The term `dossier` remains only where an existing architecture requirement, route, event, or tool
name needs compatibility. New internal types and public response vocabulary use
**research view**.

A saved “version” is a **composition receipt**: subject, schema/policy/config pins, ordered section
and statement references, dependency references, and hashes. It does not copy claim values,
evidence spans, personal text, or rendered prose. Resolving a receipt always passes through current
tenancy, erasure, verification, freshness, identity-binding, and use-policy checks.

An optional renderer may later turn a resolved view into Markdown, HTML, or another presentation.
That renderer is downstream and non-authoritative. C7 correctness cannot depend on it.

---

## 2. Outcome

C7 makes verified research usable by the account and contact surfaces while retaining one truth
store:

1. direct facts resolve to typed claims and evidence;
2. interpretive statements resolve to derived claims and all of their supporting claims;
3. account and contact research views expose structured sections, states, and actions;
4. scores, identity, activity, coverage, committee, and research remain visibly distinct data
   species even when one endpoint aggregates them;
5. stale, rejected, superseded, weakly-bound, disallowed, expired, erased, or cross-subject content
   cannot leak into a valid view;
6. the production committee reader closes the M12 placeholder and emits a real handoff;
7. refresh/re-check is additive and auditable rather than an in-place rewrite;
8. every persisted projection or receipt is DSAR-reachable and safe to re-resolve.

---

## 3. Frontend-derived contract

### 3.1 Shared page rules

The frontend must be able to render each item without parsing prose or inferring policy:

- a stable item id and semantic kind;
- the exact subject entity;
- display text/value from a claim resolved at read time;
- whether the item is direct or derived;
- claim id and, for a derivation, every support claim id;
- source/evidence availability and a permitted action kind;
- verification, freshness, confidence, and conflict state;
- identity-binding and use-policy state when personal data is involved;
- explicit unknown, unavailable, stale, restricted, or redacted states;
- the time the underlying evidence was observed and the time the projection was composed.

No API may turn “missing” into plausible prose.

### 3.2 Account surface

The account page may aggregate the following species, but C7 owns only their read composition:

| Surface area | Authoritative owner | C7 treatment |
|---|---|---|
| canonical name, domain, industry, location, employee range | identity/entity spine | reference, never rewrite |
| research run state and last-researched time | C5/C6 execution + run projection | reference |
| short account summary/about | verified direct or derived claims | compose |
| overall fit and criterion-level reasons | scoring authority | reference with evidence claim ids |
| insights and evidence | claim store + derivations | compose |
| buying-committee/contact list | committee and identity owners | production reader |
| activity/history | journal/projection owner | reference; never fabricate from research |
| coverage and gaps | C1 coverage ledger | compose as explicit appendix/section |

The fit section must preserve positive, negative, and unknown criterion outcomes. C7 may explain a
score using the scoring record's own evidence references; it may not recompute or silently override
the score.

### 3.3 Contact surface

The contact page may show:

- canonical identity, role, company, persona, committee role, and influence;
- public profile links and professional signals;
- overview and research highlights;
- evidence-backed quotes;
- governed personalization/icebreaker candidates;
- public personal background;
- career, education, publications, awards, and other registered field groups;
- freshness, deletion, restriction, and evidence availability.

These sections are registry-driven. The block vocabulary is closed for the API schema, but new
field keys remain open by registration rather than a hardcoded per-industry schema fork.

The page must distinguish:

- **display eligible** — a verified claim that policy permits the user to inspect;
- **outreach eligible** — a strongly identity-bound, use-classified claim that passes the active
  jurisdiction/client policy for use in outreach;
- **personalization candidate** — an outreach-eligible statement intentionally selected for
  personalization;
- **restricted/redacted** — known to exist but not available for display/use;
- **unknown** — not found, not researched, or not established.

A displayable fact is not automatically an icebreaker. C7 never turns medical, sensitive, weakly
bound, or otherwise inappropriate information into personalization merely because it is true.

### 3.4 Plan surface boundary

The campaign/project plan screen is downstream. It owns plan sections, channel/tactic choices,
generated drafts, human approval, and plan versioning.

C7 supplies referenced research blocks and evidence-backed inputs. It does not own the plan editor,
approval transition, or plan document. A plan may cite a C7 snapshot or individual statement ids;
it must not rely on copied dossier prose as research truth.

### 3.5 Adversarial identity rule

Every statement is locked to an exact resolved subject. The system must reject examples of the
following shape:

- a contact page whose biography belongs to a same-name or unrelated person;
- pronouns or personal history inconsistent with the resolved contact;
- account activity belonging to another company;
- a contact fact supported only by account-level evidence with no typed cross-entity relation;
- a derived statement whose supports refer to an unrelated subject.

Legitimate cross-entity reasoning is permitted only through typed support roles, for example
`employer_context`, `client_capability`, or `account_signal`. The derived claim still has one exact
target subject and the entailment check receives the target plus every support subject/relation.

---

## 4. Binding decisions

### C7-D1 — preserve one truth store

Direct and derived research statements are claims. Derivation edges, verdicts, and composition
receipts add lineage; they do not create a second store of prose.

### C7-D2 — add a derived claim flavor

Add `ClaimFlavor.DERIVED` for an inference whose evidence is other claims.

- A derived claim remains immutable and append-only.
- It carries one exact `entity_id`, `entity_type`, `field_key`, value, run, workspace/reuse scope,
  product scope, and verification state.
- Its evidence is the `claim_derivation` support set, not a fabricated public URL.
- Tier-4/model metadata remains recorded, but a derived claim is excluded from factual
  `current_value` merge selection.
- A research view reads accepted direct current values and accepted derived claims through
  separate selectors.
- The claim cannot become accepted until its support set exists, its entailment verdict supports
  it, its confidence has been conservatively propagated, and normal governance checks pass.

This is an additive core/DB enum change and must retain enum-parity tests.

### C7-D3 — derivations are normalized edges

`claim_derivation` stores one row per `(derived_claim_id, supporting_claim_id)` edge rather than a
mutable array. Edge order and a closed support-role vocabulary make explanations deterministic.

The write service validates in one transaction:

- both claims exist and are live;
- the derived claim has flavor `derived`;
- no self-edge or cycle exists;
- workspace/reuse and product scope are compatible;
- support roles permit any cross-entity relationship;
- contact-target supports satisfy identity-binding requirements;
- the full support set is frozen before judging.

Support sets are never edited. A changed support set creates a new derived claim.

### C7-D4 — entailment is a verification mode, not a new authority

The existing governed `LLMGateway` performs an entailment judge mode behind an injected protocol.
The judge answers only whether the proposed derived value is supported by the supplied claims.

The engine remains authoritative for:

- subject/scope checks;
- support-set integrity;
- confidence propagation;
- verification and policy gates;
- acceptance/rejection;
- staleness;
- idempotency and budget.

Malformed output and model errors fail closed to `unsupported`/`error`; they never promote.

### C7-D5 — no raw entailment rationale

New entailment verdict rows persist bounded reason codes, scores, model/prompt attribution, support
hashes, and trace references. They do not persist free-form model rationale containing copied
personal text.

The pre-existing `faithfulness_verdict.rationale` receives a one-way DSAR redaction path before C7
claims DSAR cleanliness. The verdict, prompt/model attribution, and non-personal audit metadata may
remain after the rationale is nulled and marked redacted.

### C7-D6 — conservative confidence

The accepted derived confidence is:

```text
min(minimum support confidence, entailment confidence, configured derivation ceiling)
```

It may never exceed its least-confident required support. Policy is versioned; the default cannot
be weakened by a request parameter or “quality mode.”

### C7-D7 — dependency state is resolved at read time

A derived statement is not eligible when any required support is:

- erased, purged, missing, rejected, or superseded;
- retention-expired;
- no longer visible in the requesting workspace;
- weakly identity-bound where strong binding is required;
- disallowed for the requested use;
- in unresolved conflict where policy requires review.

A merely freshness-stale support produces `stale`, not a fabricated replacement. The derivation is
excluded from the fresh/default view until re-check produces a new accepted derivation or policy
explicitly requests stale-inclusive review. The old row is not mutated.

### C7-D8 — compose structured views deterministically

`ResearchViewComposer` receives injected readers and emits a typed `ResearchView`.

Given identical subject, pins, and current underlying references, it produces the same ordered
sections, items, hashes, and receipt. It does not call a model to write connective prose.

### C7-D9 — nine treaty blocks are an adapter vocabulary

The existing nine block kinds remain representable for downstream compatibility:

1. `executive_summary`
2. `company_profile`
3. `fit_assessment`
4. `signal`
5. `committee_member`
6. `personalization`
7. `value_narrative`
8. `feasibility`
9. `coverage_gap`

They are typed projections over statement/reference items, not stored document sections. Account
and contact pages may group or label them differently without changing backend truth.

### C7-D10 — snapshots store references, never research bodies

A `research_view_snapshot` stores:

- workspace/project/run/subject;
- schema, policy, field-registry, scoring, and product pins;
- ordered section/block/item ids;
- referenced claim/derivation/coverage/score/committee ids;
- all reachable subject ids;
- a deterministic composition hash;
- timestamps and actor/operation identity.

It stores no claim value, evidence span, quote, biography, rationale, or rendered Markdown/HTML.

### C7-D11 — evidence access is capability-based

Response items expose an `EvidenceActionDescriptor`, never an object-storage key or permanent
signed URL.

Allowed action kinds are:

- `open_public_source`;
- `view_api_provenance`;
- `request_artifact_preview`;
- `unavailable`;
- `redacted`.

A separate API-root `EvidenceAccessService` revalidates workspace, subject/claim/artifact linkage,
artifact lifecycle, media/action policy, and a server-owned TTL before redirecting or minting a
short-lived preview. It is the only C7 consumer of `StorageBackend.presign`.

### C7-D12 — re-check is additive

`recheck_research_view` accepts a stored snapshot id and an optional closed section selector. It:

1. resolves the old receipt under current policy;
2. re-runs existing freshness, verification, identity, use, and derivation checks;
3. optionally requests governed re-research through the existing C5/C6 operation path;
4. writes new verdicts/claims/derivations/receipt rows;
5. returns a reference-only change report.

It does not update claim values, override verification, loosen policy, or create another research
loop.

### C7-D13 — display and outreach are separate decisions

Each personal statement carries a `display_decision` and an `outreach_decision`. A
personalization block additionally requires an allowed outreach decision and a recorded selection
reason. The frontend never infers outreach safety from a generic “verified” badge.

### C7-D14 — product scope is explicit

The account view accepts an optional `product_id`.

- Product-neutral identity and account facts may be shared.
- Product-scoped client claims, fit results, narratives, and selected committee relevance must
  match the requested product.
- A mixed-product response fails closed; it is not silently merged.
- Per-product fit is read from scoring authority and never recomputed by C7.
- `contact_class` is a registered, optional typed projection value, not a new hardcoded persona
  enum.

### C7-D15 — the production handoff reader lives at composition

`HandoffCommitteeReader` remains a narrative-owned protocol. Its production implementation is
wired at `clue_api` from canonical contact, committee, claim, verification, and use-gate readers.
The narrative package does not import sibling research packages.

The `narrative_emit_skipped` placeholder may disappear only after an integration test proves that
a real eligible committee produces the real narrative/handoff event and that an ineligible or
empty committee remains honest.

### C7-D16 — legacy dossier surfaces are compatibility adapters

If an existing client requires `compose_dossier`, `/dossier`, or `dossier.updated`, C7 retains them
as thin aliases over the structured research-view service:

- no distinct persistence;
- no Markdown/HTML body in the authoritative response;
- identical authorization, hashes, snapshot ids, and DSAR behavior;
- deprecation metadata pointing to the research-view vocabulary.

No new consumer may bind directly to a rendered dossier document.

---

## 5. Core read contract

The implementation may refine Python names during C7.0, but it must preserve this information
model.

### 5.1 Subject and state

```text
ResearchSubjectRef
  entity_id
  entity_type: account | contact
  canonical_entity_version
  parent_account_id?

ResearchItemState
  availability: available | unknown | unavailable | redacted | restricted
  verification: accepted | pending | rejected
  freshness: fresh | stale | expired
  conflict: none | review_required
  display_decision: allowed | denied | not_applicable
  outreach_decision: allowed | denied | not_applicable
  reason_codes[]
```

### 5.2 Statement

```text
ResearchStatement
  statement_id
  subject
  field_key
  value                      # resolved at read time; absent when unavailable/redacted
  statement_kind: direct | derived
  claim_id
  support_claim_ids[]        # empty for direct; complete and ordered for derived
  support_roles[]
  product_id?
  state
  confidence
  observed_at?
  collected_at
  evidence_actions[]
```

The contract does not expose raw storage keys, unrestricted evidence spans, model chain-of-thought,
or copied verdict rationale.

### 5.3 View

```text
ResearchView
  schema_version
  view_id                    # deterministic identity for this resolved composition
  snapshot_id?
  workspace_id
  project_id
  project_run_id
  subject
  product_id?
  composed_at
  source_state_hash
  status_summary
  sections[]
  provenance_index
  coverage_summary
```

Each section has a closed semantic `kind`, stable order, explicit state, and typed items. A section
may be empty with a reason; absence is not silently collapsed.

### 5.4 Account projection

The account projection composes:

- canonical account reference;
- research status;
- summary/about statements;
- fit reference with overall and criterion-level outcomes;
- insight/signal statements;
- committee member references;
- coverage/gaps;
- optional activity references owned by the activity projection.

### 5.5 Contact projection

The contact projection composes:

- canonical contact and employer references;
- committee role/persona/influence/contact-class references;
- overview and professional signals;
- quotes and registered research groups;
- governed personalization candidates;
- coverage/gaps and freshness state.

Contact lists and contact detail use the same eligibility resolver so a deleted/restricted contact
cannot remain in one projection after disappearing from another.

---

## 6. Durable data model

All new migrations use Alembic-generated hash ids and retain one migration head.

### 6.1 `claim_derivation`

Append-only edge table:

- `id`;
- `workspace_id`;
- `derived_claim_id`;
- `supporting_claim_id`;
- `support_role`;
- `ordinal`;
- `support_required`;
- `created_at`;
- unique `(derived_claim_id, supporting_claim_id, support_role)`;
- unique `(derived_claim_id, ordinal)`.

Both claim ids are immutable foreign keys. Deletion behavior must preserve audit while allowing
DSAR tombstoning/erasure to make resolution fail closed.

### 6.2 `entailment_verdict`

Append-only verdict table:

- `id`, `workspace_id`, `derived_claim_id`;
- `support_set_sha256`;
- `verdict`: `supported | unsupported | error`;
- `confidence`;
- bounded `reason_codes`;
- requested and answering model ids;
- prompt/policy versions;
- gateway/trace reference;
- cost and timestamps;
- `operation_id`;
- no free-text rationale.

The cache/idempotency key includes the derived claim, support-set hash, requested judge model, and
prompt version.

### 6.3 `research_view_snapshot`

Reference-only receipt table:

- identity/scope/subject fields;
- schema and policy/config pins;
- `source_state_sha256`;
- `composition_sha256`;
- creator and operation identity;
- creation time;
- optional `supersedes_snapshot_id`.

Normalized child tables record section/item/reference order and reachable subjects. They contain
ids, enums, pins, and hashes only.

### 6.4 Existing `account_handoff`

The existing materialized JSON payload is not C7's canonical research view. Before C7 closes, its
DSAR and freshness behavior must be made explicit:

- either migrate it to a reference-only receipt;
- or mark it legacy, rebuild-on-read, and prove subject-indexed purge/regeneration.

It may not remain an unindexed personal-text copy outside the erasure graph.

---

## 7. Ownership and import boundaries

| Concern | Owner | Exposes |
|---|---|---|
| cross-package research-view types and protocols | `libs/clue-core` | frozen models/protocols only |
| derivation edges and selectors | `claimstore` | claim-reference DAL/service |
| entailment judge | `verification` | injected judge implementation |
| deterministic research-view composition | `narrative` | composer/snapshot protocol |
| coverage/gaps | existing C1 owner | body-free reader |
| committee/contact resolution | existing identity/committee owners | production API-root adapter |
| account/contact query DTOs | `platform/projections` | read-only projections |
| evidence-access policy | `platform/api` composition | authorized action resolution |
| tools, routes, events, handoff wiring | `platform/api` | external adapters |

Rules:

- `core` imports no internal package;
- research sibling packages do not import each other;
- `narrative` consumes protocols, never concrete verification/compliance/identity implementations;
- cross-package aggregation happens in `clue_api`;
- the claim store remains the only research truth substrate;
- tools return references, not research/evidence bodies;
- downstream content reads claim/narrative/block references, not rendered dossier prose.

---

## 8. Tool, route, and event contract

### 8.1 Tools

| Exact tool | Replay policy | Output |
|---|---|---|
| `compose_dossier@1` | operation-idempotent | `ResearchViewReceipt` |
| `recheck_research_view@1` | operation-idempotent | `ResearchViewChangeReportRef` |
| `get_research_view@1` | effect-free | `ResearchViewRef` |

`compose_dossier@1` is retained to satisfy the parent requirement, but its description and typed
output define dossier as the structured research view. Tool results contain ids, status, hashes,
and fetch refs only.

### 8.2 Read API

Planned routes:

```text
GET  /v1/projects/{project_id}/accounts/{account_id}/research-view
GET  /v1/projects/{project_id}/contacts/{contact_id}/research-view
GET  /v1/research-view-snapshots/{snapshot_id}
POST /v1/research-view-snapshots
POST /v1/research-view-snapshots/{snapshot_id}/recheck
POST /v1/research-statements/{statement_id}/evidence-action
```

All routes require workspace/project/subject authorization. Cross-workspace and erased resources
return not-found semantics where disclosure itself would leak information.

Legacy `/dossier` routes, if retained, delegate to these handlers and return the same schema.

### 8.3 Events

Canonical events:

- `research_view.updated`;
- `research_view.section_stale`;
- `research_view.recheck_completed`.

Events contain scope, subject, snapshot/view ids, affected section/item ids, reason codes, and fetch
references. They never contain claim values, evidence spans, biographies, quotes, or rendered
prose. Legacy dossier event names may be emitted as aliases during a measured transition.

---

## 9. DSAR and retention contract

C7's subject-reachability graph includes:

- direct and derived claims;
- derivation edges;
- verdict references and any legacy rationale;
- snapshot subject/reference rows;
- existing `account_handoff` payloads or receipts;
- evidence artifacts;
- re-check reports;
- projection caches;
- outbox/event payloads;
- C6 workspace/history references that point to C7 outputs.

Erasure must:

1. tombstone/purge source claims and artifacts through their existing owners;
2. redact legacy personal rationale;
3. make dependent derivations unavailable immediately;
4. invalidate/re-resolve affected snapshots without copied text surviving;
5. remove the subject from account/contact list and detail projections consistently;
6. deny old evidence actions and signed-link renewal;
7. prevent cold replay or a legacy handoff payload from resurrecting erased content.

The extended DSAR test must scan serialized DB/event/artifact/projection outputs for a unique
sentinel, not merely assert that a row flag changed.

---

## 10. C8 prerequisites consumed by C7

| Prerequisite | C7 disposition |
|---|---|
| merge conflict honors field `equality_mode` | verify current implementation with joint merge/view tests; do not duplicate logic |
| retention-expired claims cannot win | prove retention sweep + composition order; add fail-closed read guard |
| `faithfulness_verdict.rationale` is DSAR-clean | add one-way redaction and sentinel test before derived views |
| production `HandoffCommitteeReader` | implement at API composition and prove real emission |
| presign scope policy | add `EvidenceAccessService` before any evidence action |
| per-product fit/contact class | consume explicit product scope and registered optional class; add cross-product negative tests |

No C7 consumer lands before the prerequisite in its row has a named automated test.

---

## 11. Acceptance criteria

C7 is complete only when:

1. account and contact fixture views resolve deterministically from references;
2. every displayed statement is a direct claim or accepted derived claim with complete supports;
3. no unprovenanced connective prose exists in the authoritative projection;
4. the three 2026-07-27 cross-subject contamination fixtures fail closed;
5. same-name, wrong-employer, wrong-account-activity, weak-binding, and disallowed-use tests pass;
6. positive, negative, unknown, stale, restricted, redacted, and coverage-gap states are explicit;
7. a superseded/erased/expired support invalidates its dependent derivation immediately;
8. re-check writes additive results and cannot weaken gates through request parameters;
9. evidence actions never expose storage keys and cannot cross workspace/subject/artifact scope;
10. product-scoped fit/narrative/contact relevance cannot bleed across products;
11. the production committee reader emits a real M12/C7 handoff and the placeholder is removed
    only after proof;
12. legacy dossier adapters share the same storage, authorization, snapshot, and DSAR semantics;
13. erased personal content is absent from claims, legacy rationale, snapshots, handoff payloads,
    projection responses, events, evidence previews, and cold replay;
14. downstream content can consume the typed block/reference projection without a document body;
15. dependency/import-contract, migration, DB smoke, unit, integration, eval, lint, and type gates
    are green.

---

## 12. Explicit non-goals

- frontend page implementation or visual styling;
- the campaign/project plan editor and approval workflow;
- free-text dossier editing;
- model-generated document prose as canonical state;
- a second agent/research loop;
- a new truth, scoring, entity, committee, activity, coverage, verification, or policy authority;
- arbitrary evidence URL signing;
- weakening display/outreach governance for a “best quality” mode;
- final downstream content or design artifact generation.
