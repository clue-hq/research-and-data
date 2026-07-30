# C7.9 implementation plan — production research-view readers and activation

**Date:** 2026-07-30
**Branch:** `platform/c7-research-views`
**Parent plan:** [Phase C7 structured research views](2026-07-27-phase-c7-research-views.md)
**Binding spec:** [PC-C7](../../specs/PC-C7-research-views-derivations-and-handoff.md)
**Review input:** `_memory/2026-07-29-c7-implementation-review.md`
**Status:** IMPLEMENTED — automated gates are green; all flags remain default-off pending the real
Exa-first manual quality trial and explicit canary approval

## 1. Outcome

Implement the real database-backed read stack that turns the existing C7 contracts into a
production-served account or contact research view.

This slice is complete only when a request made through the production API or the governed C6 tool
uses real persisted identity, claims, derivations, scores, committee membership, coverage,
activity, governance, and evidence authorities. Test stubs, a dependency-injection-only factory,
or an app that silently omits the route do not count as a production implementation.

The result remains presentation-neutral:

- it does not create a dossier document, Markdown body, HTML body, or second truth store;
- it emits direct and derived research statements from the claim store;
- it emits references for identity, scores, committee, coverage, status, and activity owned
  elsewhere;
- it resolves display, outreach, freshness, conflict, erasure, and evidence actions from current
  authority state;
- the frontend decides whether to render the result as cards, tabs, a feed, tooltips, or another
  layout.

The latest frontend understanding is binding. An account page needs canonical identity, current
research status, summary/about, fit with positive/negative/unknown criteria, insights and evidence,
contacts, activity, and explicit gaps. A contact page needs exact person/account identity,
committee role, professional signals, overview, evidence, quotes, background, career, education,
publications, awards, and separately governed personalization. Wrong-person, wrong-employer,
wrong-account, wrong-product, and sensitive-personalization output are structural failures.

## 2. Why this is a separate corrective slice

C7.0–C7.8 established the contracts, derivation substrate, deterministic composer, reference-only
snapshots, evidence access seam, recheck, committee/handoff integration, API routes, tools, flags,
and adversarial fixtures. The post-closeout review found that the production read path itself is
still absent:

1. all eight reader protocols exist, but only the committee reader has a concrete adapter;
2. `build_research_view_composer()` has no production caller;
3. `create_projections_app()` accepts prebuilt C7 collaborators but constructs none;
4. the read route can be silently absent even when its flag is enabled;
5. the fleet toolbelt is built without the C7 collaborators;
6. `StatementGovernanceReader` and `EvidenceAccessAuthorizer` have no production implementation.

This means the frozen view contract is real, but the switch from stored research to a served view
has not been built. C7 must therefore remain default-off until C7.9 closes.

## 3. Definition of a production research-view reader

A production reader is a thin, deterministic adapter over an existing authoritative store or
service. It is not an agent and does not research, infer, score, verify, or invent prose.

Every production reader must:

- read real persisted state through an owner-defined repository or projection service;
- run inside one request-scoped, read-only, repeatable-read transaction;
- enforce exact workspace, project, project-run, subject, parent-account, product, and canonical
  identity scope;
- distinguish legitimate absence from infrastructure or contract failure;
- return typed C7 statements or body-free owner references;
- batch its reads and avoid per-claim, per-support, or per-contact connection/query loops;
- use deterministic ordering and identifiers;
- fail closed on malformed, ambiguous, missing-authority, or cross-scope state;
- never call a model, resolver, scraper, Exa, Firecrawl, or another acquisition tool;
- never write a cache or materialized dossier body.

The read stack may evaluate current policy and derive a view state, but a GET must not mutate
claims, use decisions, verdicts, snapshots, or execution state.

## 4. Non-goals

C7.9 does not:

- build the frontend;
- improve Exa, Firecrawl, scraper, or research-agent output quality;
- create claims that upstream research did not produce;
- recompute identity, fit, intent, committee roles, coverage, or activity;
- turn all public personal facts into personalization;
- add a second policy or verification authority inside C7;
- replace the C5 journal, C6 runtime, C1 coverage ledger, M9 verification, M10 compliance, M12
  narrative, claim store, identity service, or scoring engine;
- persist view bodies for performance;
- make the default-off flags default-on.

The readers will expose the quality of the current research truth accurately. Empty fields remain
empty/unknown; readers must not mask weak acquisition quality with generated filler.

## 5. Frozen architectural decisions

### 5.1 One request-scoped read unit of work

Do not build eight app-global readers that each open their own connection.

Add a `ProductionResearchViewComposer` wrapper. For every `compose(request)` call it:

1. opens one read-only `REPEATABLE READ` transaction;
2. resolves and authorizes the complete request scope once;
3. constructs connection-bound reader adapters and governance evaluator;
4. calls the existing `build_research_view_composer(...)`;
5. composes the complete view from one MVCC snapshot;
6. closes the transaction.

Proposed shape:

```text
ProductionResearchViewComposer
  └── compose(request)
      └── ResearchViewReadUnitOfWork(read-only, repeatable-read)
          ├── ResolvedResearchViewScope
          ├── DbCanonicalSubjectReader
          ├── DbDirectClaimReader
          ├── DbDerivedClaimReader
          ├── DbFitResultReader
          ├── DbCommitteeViewReader
          ├── DbCoverageViewReader
          ├── DbActivityReferenceReader
          └── ProductionStatementGovernanceReader
              └── CurrentStatementGovernanceEvaluator
```

Correctness takes priority over parallel SQL execution. Do not run concurrent statements on the
same `AsyncConnection`. Batch preload owner state, then perform deterministic in-memory mapping.

### 5.2 One shared scope resolver

Add an API-root `ResearchViewScopeResolver` returning an immutable
`ResolvedResearchViewScope`. It is reused by every reader, evidence authorization, snapshots, and
recheck.

The resolved scope must contain at least:

- workspace;
- project;
- project run and pinned product;
- requested subject type and ID;
- canonical survivor ID and canonical version;
- exact merged-member IDs allowed to contribute immutable historical claims;
- parent account for a contact;
- owning account run and its research/execution run IDs;
- pinned ICP key/version where applicable;
- current workspace policy version;
- subject admission/reference membership.

The resolver must validate:

- the project run belongs to the requested workspace/project;
- the request product equals the project-run product;
- the account is a member of that project run;
- a contact belongs to that account and was admitted by the account-run committee/profiling
  references;
- the entity is live and resolves to the exact canonical survivor;
- a foreign, erased, missing, or ambiguous subject returns an opaque not-found result.

Add an optional `subject_entity_type` to `ResearchViewReadRequest`. Account/contact HTTP routes
and current tools must always supply it. Legacy callers that omit it may resolve both identity
tables, but ambiguity must fail closed. A later major schema version can make it required.

### 5.3 Preserve merged-entity claim history

Claims are immutable and may remain keyed to an identity record that later merged into the
canonical subject. Do not rewrite those claims and do not clone them with a new entity ID.

Extend the internal subject read contract with the exact canonical membership set. The composer
may accept a candidate whose immutable origin entity belongs to that set, but it always emits the
canonical `ResearchSubjectRef`. No reader may accept a merely similar name/domain/employer as
membership.

Canonical merge changes must increment the canonical entity version so snapshot/view hashes and
frontend identity caches cannot pretend the subject is unchanged.

### 5.4 Explicit, registry-driven field routing

`ResearchStatementCandidate` requires a semantic section, but the field registry currently does
not own a field-to-research-section mapping. Hardcoded prefix ladders or a fallback
`everything -> insights` rule are forbidden.

Add versioned projection metadata, proposed as:

```text
research_view_field_route
  id
  field_key FK field_definition
  entity_type
  view_schema_version
  section_kind
  purpose                  display | personalization_candidate
  context_scope            subject_current | project_run_pinned
  product_mode             neutral_or_exact | exact_required | neutral_only
  ordinal
  route_version
  active
  created_at
```

Required constraints:

- one active primary display route per `(field_key, entity_type, view_schema_version)`;
- a route section must be legal for that entity type;
- a personalization route is legal only for a contact field designed as an explicit
  personalization derivation;
- scoring, coverage, activity, identity, committee, and execution-status fields cannot be routed
  as claim statements when their owner already emits a reference;
- vertical/industry packs add routes by registration;
- unmapped fields produce bounded telemetry and remain absent/unknown; they are never guessed into
  a section.

Initial routes must cover the actual registered core/deep fields, including:

- account operational pain, strategic moves, resonance, and value narrative;
- contact professional role/signals;
- public quotes/appearances;
- background/interests;
- career history;
- education/alma mater;
- publications;
- awards where a registered field exists.

The plan must not invent a summary, overview, awards, or icebreaker claim if upstream does not
write one. To populate those frontend blocks, upstream must register and write explicit supported
derived fields. C7.9 only routes them once they exist.

### 5.5 Personalization is a dedicated governed derivation

A raw personal facet may be displayable in background, career, education, quotes, or publications
while being forbidden for outreach. Do not move every outreach-denied fact into a hidden state,
and do not duplicate the same claim into two sections.

The `PERSONALIZATION` section accepts only an explicit derived personalization/icebreaker claim
registered for that purpose. It must:

- be a contact-derived claim;
- have a complete support graph;
- be strongly identity-bound;
- pass display policy;
- pass outreach policy for the root and every required transitive personal support;
- be non-sensitive;
- retain a selection reason.

The raw supporting fact remains in its semantic display section when display policy permits it.

### 5.6 Display and outreach policy remain independent

`UseDecision` is an outreach authority; it is not a display-policy authority.

Freeze a versioned, data-driven workspace display policy rather than embedding a temporary rule in
the reader. The conservative default is:

- live verified/flagged account claims may be displayed;
- live professional/public contact claims require correct strong identity binding;
- public-personal contact claims may be displayed when strongly bound even if outreach is denied;
- sensitive, erased, retention-expired, weak/missing-binding, cross-scope, rejected, incomplete,
  and unsupported claims are denied/restricted/redacted;
- sensitive claims are never personalization candidates;
- missing/malformed policy fails closed.

For schema 1.0, display policy is workspace-level after API workspace authorization. If display
eligibility later varies by actor/role, that requires an explicit contract/hash change because
`ResearchViewReadRequest` does not currently carry actor identity.

### 5.7 Activity means subject-bound research/execution activity

For C7 account views, `activity` means structured research/execution history such as account
creation/admission, research updates, contact additions, and rechecks. It does not mean downstream
sales dispositions or an inferred feed made from claim timestamps.

Build or extend a C5-journal-owned subject activity projection. Every row/reference must be bound
to exact workspace, project run, account run, subject, and product where applicable. If an old
journal event cannot prove that binding, omit it. Do not infer account activity from run-level
events.

Contact views currently do not include an activity section and must return `not_applicable`.

## 6. Shared schema and authority prerequisites

These changes land before the reader adapters.

### 6.1 Canonical entity version

Add `canonical_version INTEGER NOT NULL DEFAULT 1 CHECK (canonical_version >= 1)` to account and
contact identity tables.

Increment it on every sanctioned canonical identity mutation and merge affecting the frontend
identity contract. Prefer a database trigger over relying on every current/future writer to
remember the increment. The trigger must compare an explicit canonical-column tuple rather than
incrementing for unrelated bookkeeping writes.

Add identity repository operations for:

- batch resolving survivors;
- batch loading canonical accounts/contacts;
- listing the exact merged-member set for a survivor;
- returning the durable canonical version.

Tests must prove:

- ordinary reads do not increment;
- canonical mutation increments once;
- merge increments the survivor;
- loser-origin claims still resolve to the survivor;
- unrelated workspace entities never enter the member set.

### 6.2 Field presentation routes

Add the route table and owner repository described in §5.4. Route rows are projection metadata,
not research truth.

Add pack-registration validation so a registered view field has:

- compatible entity type;
- compatible C7 section;
- declared context/product scope;
- a stable route ordinal;
- no duplicate active primary display route.

### 6.3 Product-aware current claim selection

Add a claimstore-owned repository operation rather than API-owned SQL, proposed as:

```text
current_values_resolved_for_product(
  canonical_entity_id,
  member_entity_ids,
  field_routes,
  workspace_scope,
  product_id,
  account_run_scope
)
```

The product filter must execute before winner selection:

- `exact_required`: only exact `product_id`;
- `neutral_only`: only `product_id IS NULL`;
- `neutral_or_exact`: exact product contenders outrank neutral contenders, then normal merge
  ranking applies within that product class;
- a neutral request never reads a non-neutral claim.

The operation must also apply supersession, retention, verification eligibility, reuse scope,
freshness, and current merge/conflict policy. It must return one current winner or an explicit
conflict/ambiguity; it must not choose an arbitrary row.

### 6.4 Product/run-correct score supersession

Fix fit-claim writes and reads so the uniqueness/supersession domain includes the exact product
and owning run/pinned ICP context. Multiple live fits for different products or project runs may
exist, but there must not be two current fits for the same:

```text
(workspace, account, field, product, owning account run, pinned ICP key/version)
```

The reader fails closed on an ambiguous exact tuple. It never lets a newer product-A score hide or
replace the requested product-B score.

Also add `product_id` to the research-view change/recheck report projection and include product in
the legacy handoff uniqueness/cutover logic where that path remains reachable.

### 6.5 Subject-bound activity projection

If no existing projection can prove subject binding, add a reference-only activity projection
owned by the execution/journal layer with:

- workspace/project/project-run/account-run;
- subject type/id;
- product;
- journal/event owner reference;
- structured event kind;
- occurred-at;
- actor category where safe;
- no copied claim/evidence body.

Backfill only events whose account-run/subject relation is mechanically provable.

### 6.6 Versioned display policy

Extend the existing workspace policy/config authority with the display-policy fields in §5.6.
Keep one policy loader shared by governance, evidence authorization, and snapshot re-resolution.

### 6.7 Migration rules

Use Alembic-generated hash revisions, reversible upgrades/downgrades, named constraints/indexes,
and exactly one head.

Required migration verification:

1. upgrade a clean database;
2. inspect new defaults and constraints;
3. exercise canonical-version triggers;
4. downgrade to the previous head;
5. re-upgrade;
6. run enum/schema parity;
7. run `alembic heads` and `make db-smoke`.

## 7. Cross-cutting correctness fixes required before flag-on

These are not optional cleanup. A production reader would otherwise expose known incorrect
semantics.

### 7.1 C7-D7 derived-support use-policy enforcement

The dependency resolver currently evaluates verification, freshness, conflict, supersession,
retention, and erasure, but not whether a required support is allowed for the requested use.

Extend the resolver output, or add a sibling-neutral injected dependency-use protocol, so the
API-root governance evaluator receives all transitive support claim IDs and required/optional
roles without reimplementing recursion.

For display:

- every required support must be displayable under display policy;
- a display-denied required support restricts the derived display;
- outreach denial alone does not restrict a displayable derivation.

For outreach/personalization:

- every required use-governed personal support must have a current allowed use decision;
- missing decision, denied use, standing objection, sensitive class, weak binding, or stale policy
  version denies the derived outreach use;
- required company/public facts with outreach `not_applicable` do not block;
- optional denied supports do not block, but remain unavailable as evidence.

Use bounded reason codes such as `support_display_disallowed`,
`support_use_decision_missing`, `support_use_disallowed`, and `support_outreach_objected`.

### 7.2 `FLAGGED` derived root must not mask redacted support

For a derived `FLAGGED` root, record local `review_required` and continue traversing required
supports. Aggregate with the frozen precedence:

```text
redacted > restricted > rejected > unavailable > review_required > stale > eligible
```

A required erased support therefore produces `redacted`, even when the derived root is flagged.
Direct flagged claims may still resolve directly to a review state.

### 7.3 Retention and objection sweep parity

Make background retention/objection sweeps as complete as interactive erase:

- expand tombstones to dependent derived claims;
- purge or make unresolvable any reachable legacy `account_handoff.payload`;
- preserve audit-only references without subject/body recovery;
- distinguish erasure, objection, and retention-expiry tombstone reasons.

Run the extended DSAR sentinel suite before enabling any C7 read/evidence flag.

### 7.4 Entailment response parsing

Reuse the existing bounded first-JSON-object parsing/harness behavior from faithfulness for
entailment verdicts. Valid fenced JSON must not be rejected merely because of harmless wrapper
text. Malformed, ambiguous, injected, or schema-invalid output still fails closed.

Remove the parallel parser/harness copy rather than maintaining two interpretations.

## 8. Reader-by-reader implementation

### 8.1 `DbCanonicalSubjectReader`

**Authority**

- workspace-local `account_entity` / `contact_entity`;
- identity survivor/member resolution;
- project-run/account-run repositories;
- C5/C6 execution status projection.

**Algorithm**

1. consume the already resolved request scope;
2. load the canonical entity and version from the shared transaction;
3. for contacts, verify the exact parent account and account-run admission;
4. create the canonical `ResearchSubjectRef`;
5. emit an `IDENTITY` owner reference to the canonical identity revision;
6. emit a `RESEARCH_STATUS` owner reference to the exact account/project run;
7. return explicit unknown status only when owner state is legitimately absent.

**Failure semantics**

- foreign/missing/erased/ambiguous subject: opaque not found;
- merged loser request: either canonical redirect by an explicitly documented API rule or opaque
  not found; never serve a loser as a separate person/account;
- missing durable version or malformed run membership: composition failure, not version `1`.

**Frontend alignment**

The reader does not copy name, domain, industry, employees, current role, or employer into C7.
Identity-owned values must be resolvable through an owner read surface; research-owned industry,
employee count, role, and employer evidence remain claims/statements.

### 8.2 `DbDirectClaimReader`

**Authority**

- claim store current-value/merge policy;
- field registry;
- research-view field routes;
- resolved canonical membership and workspace/product/run scope.

**Algorithm**

1. load active routes for subject type/schema version;
2. exclude fields owned by identity, score, committee, coverage, activity, or execution status;
3. batch select current field-claim winners using product filtering before merge;
4. accept only `FIELD_CLAIM`, never `DISCOVERY` or `DERIVED`;
5. preserve the immutable origin claim and canonical-member attestation;
6. map each winner to exactly one semantic section;
7. sort by `(section ordinal, route ordinal, field_key, claim_id)`;
8. hand candidates to governance; do not decide visibility inside the reader.

**Empty semantics**

- no upstream claim: no candidate; coverage owns the gap;
- unmapped field: omit, emit `unmapped_research_view_field` telemetry;
- configured field with only rejected/expired rows: no visible body and an explicit gap/reason via
  coverage/governance where a candidate can still be safely identified.

**Required tests**

- exact and neutral product precedence;
- cross-product newer winner cannot hide requested product;
- merged-loser origin accepted only through exact canonical membership;
- retention/supersession/verification filtering;
- deterministic ordering;
- no discovery or derived row leakage.

### 8.3 `DbDerivedClaimReader`

**Authority**

- claim store derived roots;
- immutable ordered `claim_derivation` edges;
- entailment verdicts;
- bounded `DerivationDependencyResolver`;
- route registry.

**Repository additions**

- batch list live derived roots for canonical subject/member set, workspace, product, and run
  context;
- public batch support-edge read preserving contiguous ordinals and required/optional roles;
- batch dependency resolution returning transitive required claim IDs and current state.

**Algorithm**

1. select exact product/context-eligible derived roots;
2. load all support edges in one batch;
3. reject a root with missing, duplicate, noncontiguous, cross-scope, or role-invalid edges;
4. compare candidate supports to the exact immutable DB support set;
5. route the derived field explicitly;
6. leave current dependency/use/display/outreach resolution to shared governance;
7. never return a partially loaded support graph.

**Required tests**

- direct and nested derivations;
- complete ordered supports;
- cycle/depth/node caps;
- cross-workspace/entity/product support;
- stale/superseded/rejected/erased/retention-expired support;
- flagged root plus erased support;
- required use-denied support laundering;
- optional use-denied support behavior;
- same-name/wrong-employer support contamination.

### 8.4 `DbFitResultReader`

**Authority**

- scoring-owned `account.scoring.fit` claim/projection;
- project run's pinned ICP key/version and product;
- score component evidence IDs.

**Algorithm**

1. for contacts, return `not_applicable`;
2. require an exact product because `ResearchOwnedReference` requires one for score refs;
3. load the exact current score for account run + pinned ICP + product;
4. do not recompute or reinterpret the score;
5. emit one `SCORE` owner reference with all component evidence claim IDs;
6. make positive, negative, and unknown criteria resolvable at the scoring owner surface.

**Failure semantics**

- legacy neutral score for a product view: `unknown/product_score_missing`, schedule upstream
  re-score separately;
- no fit result: explicit unknown;
- two live results for the exact tuple: conflict/review required, never arbitrary newest;
- any evidence claim outside the canonical/product/workspace scope: unavailable.

### 8.5 Request-scoped committee reader

**Authority**

- identity/contact graph;
- account-run committee reference index;
- product-scoped role/persona claims;
- shared current-use decision service;
- shared contact eligibility resolver.

The existing `GovernedCommitteeViewReader` cannot be installed app-wide because its resolver is
bound permanently to one project run and product. Replace or wrap it with a request-scoped
connection-bound adapter.

**Algorithm**

1. use the resolved account run and requested product;
2. batch load referenced committee/persona/facet claims;
3. batch resolve canonical contacts and exact parent account;
4. batch load latest use decisions;
5. return account committee-member refs or the contact's own membership ref;
6. preserve display and personalization eligibility separately at the owner projection;
7. share the same underlying eligibility evaluation with M12 handoff without sharing a
  run-bound mutable reader instance.

**Performance correction**

Remove per-claim `surviving_id`/`get_contact` calls. `resolve_contact` must query one exact contact,
not resolve the entire account committee and filter afterward.

### 8.6 `DbCoverageViewReader`

**Authority**

- C1 `coverage_attempt` and `coverage_decision`;
- account-run research plan/required field set;
- exact workspace/project-run/run/entity scope.

**Algorithm**

1. obtain required fields from the persisted account-run plan;
2. load attempts and latest decisions in exact SQL scope;
3. classify fields as filled, unfilled terminal, blocked by policy, budget exhausted, or
  unresearched/unknown;
4. emit the frozen coverage summary counts and stable coverage owner refs;
5. retain distinctions between an empty result, a policy block, a budget stop, and a terminal gap.

**Contact limitation**

The current contact profiler persists aggregate gap counts but not a durable per-contact,
per-field terminal ledger. Until that ledger exists, contact coverage must be explicit
`unknown/contact_coverage_not_persisted`. It must not convert transient counts into a completeness
claim. Implementing the contact coverage ledger is a prerequisite if the product wants detailed
contact gap rows in this release.

### 8.7 `DbActivityReferenceReader`

**Authority**

- the subject-bound C5 execution/journal activity projection frozen in §5.7.

**Algorithm**

1. for contacts, return `not_applicable`;
2. for accounts, read only rows matching exact workspace, project run, account run, subject, and
  product;
3. return owner references in deterministic reverse chronological order with stable pagination;
4. copy no event prose, claim value, evidence span, or mutable payload into C7;
5. return unknown when no subject-bound activity exists.

**Prohibited shortcuts**

- no activity inferred from `claim.created_at`;
- no run-wide event attached to every account;
- no feedback/sales disposition mixed into research activity;
- no wrong-account event selected because names happen to match.

### 8.8 `ProductionStatementGovernanceReader`

**Authority**

- current claim/merge state;
- derivation dependency resolver;
- verification and identity binding;
- field freshness TTL;
- retention and DSAR tombstones;
- versioned display policy;
- active workspace compliance policy;
- latest use decisions and standing objections;
- evidence artifact/source metadata.

Implement one shared pure evaluator and thin adapters:

```text
CurrentStatementGovernanceEvaluator
  ├── ProductionStatementGovernanceReader
  └── ProductionEvidenceAccessAuthorizer
```

Extract the private latest-use-decision SQL from `ContactEligibilityResolver` into a shared,
batch-capable current-use service. Committee, statement governance, derived-support governance,
handoff, and evidence authorization must not have five subtly different definitions of current
use eligibility.

Change the governance protocol to batch:

```text
resolve_statements(request, subject, candidates)
  -> mapping[candidate identity, StatementGovernanceResult]
```

Keep `resolve_statement` only as a compatibility wrapper for focused tests. The composer must make
one batch call.

**Evaluation order**

1. revalidate exact request scope and canonical membership;
2. reload all candidate/root/support claims in one scoped batch;
3. classify tombstone/retention before ordinary absence;
4. for direct claims, prove the claim is the exact current winner;
5. for derived claims, prove the exact support tuple and resolve the current graph;
6. aggregate dependency state using the frozen precedence;
7. apply display policy independently to root and required supports;
8. apply outreach policy to the contact root and required transitive personal supports;
9. check standing objections even if a new claim appeared after the last sweep;
10. derive safe evidence-action descriptors only for available statements;
11. return stable, bounded reason codes in deterministic order.

**State mapping**

| Current authority state | Availability | Display | Outreach | Evidence |
|---|---|---|---|---|
| verified, fresh, current account claim | available | allowed | not applicable | allowed actions |
| verified, stale but not expired | available or unavailable per field policy | allowed when available | denied/recheck | allowed only when available |
| flagged direct claim | available for review | allowed | denied by default | allowed actions |
| rejected/unverified/not-current | unavailable | denied | denied/not applicable | none |
| erased support/root | redacted | denied | denied | none |
| retention-expired | redacted + expired | denied | denied | none |
| weak/missing contact binding | restricted | denied | denied | none |
| public-personal, strong, outreach denied | available | allowed | denied | allowed actions |
| sensitive contact claim | restricted | denied | denied | none |
| derived with required display-denied support | restricted/redacted by precedence | denied | denied | none |
| derived with required outreach-denied support | available if display-safe | allowed | denied | display-safe actions only |
| missing/malformed policy or support graph | unavailable/restricted | denied | denied | none |

Derived stale/review states must follow the binding PC-C7 default-view rule. If a recheck is
required before display, return unavailable with the stale/review reason instead of exposing the
old derived value.

**Evidence descriptors**

Use deterministic UUID5 action IDs over workspace/project/run/subject/claim/action kind.

- safe public HTTP(S) source: `OPEN_PUBLIC_SOURCE`;
- governed API source metadata: `VIEW_API_PROVENANCE`;
- live previewable artifact: `REQUEST_ARTIFACT_PREVIEW`;
- unavailable/redacted statement: no actionable descriptor.

Never place source URLs, storage keys, evidence spans, signed URLs, credentials, or raw provider
payloads in the descriptor.

## 9. Owner-reference resolution required for a usable frontend

C7 intentionally returns references for non-claim species. A production frontend cannot render
an opaque reference unless the owner can resolve it.

Before flag-on, prove or add authenticated batch owner reads for:

- canonical identity revision;
- research/execution status;
- fit score and positive/negative/unknown components;
- committee membership/persona;
- coverage decisions/gaps;
- subject-bound activity entries.

These owner surfaces remain authoritative and may return their own structured values. C7 must not
copy those values into a new aggregate table merely to make the frontend convenient.

Every owner resolver must:

- enforce the same workspace/project-run/subject/product scope;
- reject stale or foreign references;
- preserve DSAR and retention behavior;
- support bounded batch resolution to avoid frontend waterfalls;
- expose a stable version/ETag.

## 10. Runtime composition and production serving

### 10.1 Add one shared production runtime builder

Add a composition-root builder, proposed as `build_production_research_view_runtime(...)`, that
constructs:

- `ProductionResearchViewComposer`;
- snapshot service;
- recheck service;
- production evidence authorizer/access service;
- deferred governed research-operation requester;
- owner reference resolvers;
- readiness probe.

The runtime must be used by both the projections/API process and the fleet toolbelt. Do not create
one API read implementation and another agent-tool implementation.

### 10.2 Resolve the recheck/tool-invoker construction cycle

Current dependencies form a cycle:

```text
recheck -> governed requester -> ToolInvoker
ToolInvoker -> ToolRegistry -> build_toolbelt -> recheck
```

Add a deferred requester adapter that:

- fails closed before binding;
- binds exactly once after `ToolInvoker` exists;
- is asserted bound at startup whenever recheck is enabled;
- never silently converts `request_research=true` into a no-op or fake success.

### 10.3 Add a launchable projections entrypoint

Add a production entrypoint analogous to `fleet_main.py`, proposed:

```text
platform/api/clue_api/projections_main.py
python -m clue_api.projections_main
```

Construction order:

1. settings, logging/metrics, DB, storage, and authentication;
2. owner repositories and policy services;
3. production C7 composer;
4. snapshots;
5. deferred governed requester and recheck;
6. central toolbelt and `ToolInvoker`;
7. bind the deferred requester;
8. production evidence authorizer, capability broker, and access service;
9. owner resolution and observability surfaces;
10. fully populated `create_projections_app(...)`.

### 10.4 Startup must fail on enabled-but-unconfigured capability

Replace silent route/tool omission with explicit startup validation:

- read enabled => real composer and owner reference resolution available;
- snapshot enabled => composer and snapshot service available;
- evidence enabled => production authorizer/access service available;
- recheck enabled => service and bound governed requester available;
- handoff enabled => product/run-correct committee reader available;
- legacy alias enabled => canonical read/compose capability available.

All flags remain master kill switches and default off.

Add a workspace canary activation policy instead of overloading global flags. A request must pass
both the global flag and workspace admission. Rollback removes routing/access; it does not delete
immutable rows.

### 10.5 Readiness

At application lifespan startup, after the database engine is available, verify:

- database connectivity;
- required tables/columns/enums/migration head;
- all enabled collaborators are present;
- the deferred requester is bound when required;
- production authentication is configured, unless an explicit local-dev header mode is selected;
- no test reader/authorizer class is installed.

Do not compose customer data during startup.

## 11. Error and failure semantics

| Situation | Required behavior |
|---|---|
| missing or foreign subject | opaque 404 |
| cross-workspace/project/run/product relation | opaque 404 |
| legitimate missing owner data | typed unknown/unavailable section |
| missing field route | omit body, bounded telemetry, explicit gap where available |
| incomplete derivation/support graph | unavailable/restricted; no partial statement |
| missing/malformed policy | restricted/unavailable; never allowed |
| DB timeout/outage | 503/500 with opaque correlation ID; no partial view |
| one reader fails | abort complete composition |
| enabled feature lacks runtime collaborator | fail application startup |
| evidence action no longer allowed | deny at access time even if an old snapshot contains the action ID |
| unbound recheck requester | fail before any mutation |

API errors and logs must never include SQL, claim values, evidence spans, URLs, storage keys,
provider payloads, or personal data.

## 12. Performance and consistency requirements

### 12.1 Query shape

The number of SQL round trips must remain bounded as statements grow.

Required batching:

- one scope resolution batch;
- one canonical identity/member batch;
- one route lookup;
- one direct/current-value batch;
- one derived-root/support/dependency batch sequence bounded by depth/node limits;
- one score read;
- one committee/contact/use-decision batch;
- one coverage read;
- one activity read;
- one governance/policy/evidence-metadata batch.

The exact ceiling should be measured after the owner repositories exist, then frozen in integration
tests. A 100-statement view must not add 99 governance, use-decision, contact, or evidence queries
compared with a 1-statement view.

### 12.2 Snapshot consistency

Add a concurrency test that supersedes/erases a claim between reader phases. The returned view must
observe either the before state or the after state from one repeatable-read snapshot, never a torn
mix.

Concurrent requests for different workspaces, products, and runs must never share:

- connection-bound readers;
- resolved scope;
- committee eligibility;
- current-use decisions;
- policy;
- dependency graphs;
- evidence actions.

### 12.3 Caching

Do not add a research-view body cache.

Reference-only snapshot receipts remain allowed. Any metadata cache must be immutable/version-keyed
and must not bypass current governance, erasure, retention, or evidence authorization.

## 13. Observability

Add a `research_view.compose` span with child spans for scope and each reader. Record only bounded
metadata:

- subject type;
- live versus snapshot mode;
- reader name;
- outcome;
- candidate/reference/section counts;
- available/restricted/redacted/stale/review counts;
- unmapped field count;
- dependency depth/node-cap outcomes;
- query count;
- duration;
- source-hash creation outcome.

Do not use workspace, account, contact, claim, URL, field value, or evidence text as metric labels.

Add:

- startup log showing enabled C7 capabilities and successfully bound components;
- readiness state without research bodies;
- counters for fail-closed reason codes;
- audit events for evidence authorization without locators/body;
- alerts for product/scope mismatches, ambiguous current scores, missing routes, and query-ceiling
  regression.

### 13.1 Proposed code ownership and file map

Final names may follow nearby package conventions, but ownership must remain as follows:

| Area | Proposed file/change | Responsibility |
|---|---|---|
| frozen core contract | `libs/clue-core/clue_core/research_view.py` | optional subject type, any shared DTO additions |
| composer protocols | `subsystems/research/clue_research/narrative/research_views.py` | canonical-member input, batch governance seam, deterministic composition |
| database schema | `libs/clue-db/alembic/versions/<hash>_*.py` | canonical versions, field routes, policy/activity/product additions |
| identity owner | `subsystems/research/clue_research/identity/entities.py` or a focused projection module | canonical versions, batch survivors/members/entities |
| claim-store owner | new `subsystems/research/clue_research/claimstore/research_view_queries.py` | product-aware direct and derived current reads |
| derivation owner | `subsystems/research/clue_research/claimstore/derivations.py` | batch supports, transitive IDs, D7 and precedence fixes |
| field registry | `subsystems/research/clue_research/claimstore/registry.py` and pack registrations | route registration/validation |
| scoring owner | focused scoring projection repository plus claim write path | run/product/ICP current fit |
| compliance owner | focused current-use/display-policy service and `compliance/dsar.py` | shared decisions, objections, sweep parity |
| coverage owner | `platform/projections/clue_projections/research_coverage.py` plus repository query | exact scoped coverage/gaps |
| activity owner | execution journal/projection package | subject-bound research activity |
| API scope/readers | new `platform/api/clue_api/research_view_readers.py` | shared scope resolver and thin eight-reader adapters |
| API governance | new `platform/api/clue_api/research_view_governance.py` | shared statement/evidence evaluator |
| API runtime | new `platform/api/clue_api/research_view_runtime.py` | request UoW and complete production builder |
| current factory | `platform/api/clue_api/research_view_wiring.py` | retain low-level injected builder, add real caller |
| committee path | `platform/api/clue_api/contact_eligibility.py` | request binding, shared use service, batch contacts |
| evidence path | `platform/api/clue_api/evidence_access.py` | production authorizer integration, no policy duplication |
| application roots | `platform/api/clue_api/projections_app.py`, new `projections_main.py`, and `fleet_main.py` | fail-fast app and shared runtime injection |
| feature settings | `libs/clue-config/clue_config/settings.py` | master flags plus canary policy inputs |
| tests | existing C7 contract/DB/API/eval/DSAR suites plus focused production-reader modules | all gates in §15 |
| operations | `docs/runbooks/` and a sanitized Postman collection | Exa-first, scraper-second, API-third manual proof |

Owner packages expose reusable query/policy operations. API adapters only join those operations
into the C7 contracts; they must not embed duplicate scoring, merge, compliance, or identity SQL.

## 14. Implementation slices and commit boundaries

The slices are serial because shared contracts, migrations, governance, runtime wiring, and API
activation overlap.

### C7.9.0 — corrective contract freeze

**Work**

- add this plan and link it from the original C7 closeout;
- freeze activity semantics;
- freeze field-route schema;
- freeze display-policy default;
- freeze canonical-member handling;
- add optional subject entity type;
- add batch governance protocol;
- update executable frontend fixture map with owner-reference expectations.

**Exit**

- contract tests compile;
- no implementation flag is enabled;
- every account/contact fixture field has one declared owner and route or an explicit upstream gap.

**Commit**

`docs(c7): plan production research-view readers`

### C7.9.1 — schema and substrate correctness

**Work**

- canonical entity versions and batch membership operations;
- field-route metadata and seed rows;
- versioned display policy;
- product-aware current-value query;
- product/run-correct fit supersession and change-report attribution;
- subject-bound activity projection;
- D7 support-use and flagged/redacted precedence fixes;
- sweep parity;
- shared entailment parser.

**Exit**

- reversible migrations, one head, DB smoke;
- focused identity/claim/derivation/compliance/DSAR/product tests green;
- no unresolved route for fields claimed by the executable fixtures.

**Suggested commits**

- `feat(identity): version canonical research subjects`
- `feat(c7): register research-view field routes and display policy`
- `fix(c7): enforce product and dependency governance before view reads`
- `fix(compliance): align retention and objection sweep reachability`

### C7.9.2 — owner query services and shared scope

**Work**

- `ResearchViewScopeResolver`;
- product-scoped current claim repository;
- derived root/support batch repository;
- score projection repository;
- exact project-run coverage query;
- subject activity projection reader;
- batch canonical contact/member queries;
- shared current-use decision service.

**Exit**

- real PostgreSQL integration tests for each authority;
- exact workspace/run/product/subject isolation;
- deterministic results and no per-item connection loop.

**Suggested commit**

`feat(c7): add scoped owner queries for production research views`

### C7.9.3 — governance and evidence authorization

**Work**

- shared current statement governance evaluator;
- batch production governance reader;
- production evidence access authorizer backed by the same evaluator;
- evidence descriptor creation;
- current standing-objection check;
- governance matrix and adversarial tests.

**Exit**

- every direct/derived state in §8.8 covered;
- D7 laundering and flagged+erased fixtures pass;
- displayable/outreach-denied fact remains visible but never selected for personalization;
- snapshot evidence action is denied after later erasure;
- query count does not grow per candidate.

**Suggested commit**

`feat(c7): enforce current statement and evidence governance`

### C7.9.4 — eight real readers and deterministic composition

**Work**

- implement the eight request-scoped adapters;
- call batch governance once;
- call `build_research_view_composer(...)` from production wrapper;
- remove committee N+1/exact-contact inefficiency;
- add owner-reference resolution;
- update source-hash/canonical-member tests.

**Exit**

- complete account and contact views built against real PostgreSQL with no stubs;
- positive/negative/unknown/restricted/redacted/stale/gap cases explicit;
- stable ordering, IDs, hashes, and ETags;
- one read-only repeatable-read transaction per view.

**Suggested commit**

`feat(c7): compose account and contact views from production readers`

### C7.9.5 — runtime, API, fleet, and activation

**Work**

- production C7 runtime builder;
- deferred recheck requester;
- production projections entrypoint;
- inject same runtime into API and fleet toolbelt;
- fail-fast startup validation;
- canary activation policy;
- readiness/observability;
- local runbook and Postman collection.

**Exit**

- enabled read flag cannot start without all real dependencies;
- API route and `get_research_view@1` use the same production composer;
- all-off startup remains inert;
- no test adapter is importable through the production root;
- process can be launched locally.

**Suggested commit**

`feat(c7): wire production research-view runtime`

### C7.9.6 — adversarial, performance, DSAR, and manual closeout

**Work**

- multi-workspace/run/product database matrix;
- canonical merge and concurrency tests;
- query ceilings at 1/25/100 statements;
- full DSAR sentinel;
- real Exa-only persisted trial;
- scraper-enabled comparison trial;
- Postman/API trial;
- docs, migration/rollback, closeout memory.

**Exit**

- every gate in §15 and §16 is green;
- manual output is inspectable and traceable to actual claims/supports/evidence;
- read-only canary is explicitly approved before any broader activation.

**Suggested commit**

`test(c7): close production research-view activation gates`

## 15. Verification matrix

### 15.1 Contract and mapping

- strict DTO schemas and frozen enums;
- optional/required subject-type compatibility;
- canonical member origins accepted only for exact survivor;
- every registered route is legal and unique;
- no field inferred from prose/prefix;
- dedicated personalization derivations only.

### 15.2 Reader unit tests

- typed row-to-contract mapping;
- deterministic ordering;
- legitimate empty versus authority failure;
- exact subject/product/run filtering;
- invalid owner data fails closed.

### 15.3 Real PostgreSQL integration

- all eight production adapters;
- account and contact fixtures;
- two workspaces with same names/domains;
- two project runs for one account;
- two products with competing claims/scores/personas;
- canonical loser/survivor claims;
- contact with correct and wrong parent account;
- no reader/test stub injection.

### 15.4 Governance/adversarial

- verified, flagged, rejected, missing;
- fresh, stale, retention-expired;
- conflicted and superseded;
- erased, objected, sensitive;
- strong, weak, missing binding;
- display allowed/outreach denied;
- required versus optional denied supports;
- transitive denied/erased/stale supports;
- wrong person/employer/account/product/workspace;
- prompt injection in evidence/support;
- cycle/depth/node cap;
- evidence locator leakage.

### 15.5 Consistency/performance

- mutation during compose produces one coherent snapshot;
- concurrent products/runs do not share state;
- SQL count at 1/25/100 statements;
- exact-contact read does not scan full committee;
- no per-candidate governance connection;
- dependency breadth remains capped.

### 15.6 Runtime/API

- all flags off;
- each flag enabled with dependency absent => startup failure;
- read-only enabled with full runtime => route/tool available;
- tenant hiding and local-dev auth behavior;
- account/contact GET;
- stable repeated ETag;
- reference-only snapshot and current re-resolution;
- evidence allow/deny;
- recheck idempotency and deferred requester binding;
- legacy alias parity where enabled;
- API/fleet use identical composer builder.

### 15.7 Migration/repository

- targeted unit/contract tests;
- targeted DB tests;
- adversarial/eval tests;
- extended DSAR sentinel;
- import/dependency contracts;
- Ruff and mypy;
- enum/schema parity;
- one Alembic head;
- clean upgrade -> downgrade -> upgrade;
- DB-enabled full repository check;
- diff/status review preserving unrelated user changes.

## 16. Manual quality-validation sequence

The implementation must support the user's chosen evaluation order:

### Stage A — Exa-only persisted research

1. run one real account/contact research job with Exa enabled and scraping disabled;
2. persist the resulting claims, supports, verdicts, scores, committee, and coverage normally;
3. invoke the production composer directly through a small body-safe CLI using the same runtime as
   the API;
4. inspect the structured output and trace each visible statement to claim/support/evidence IDs;
5. judge research quality before enabling scraping or HTTP.

The CLI must not contain alternate fixture readers or bypass governance.

### Stage B — scraper comparison

1. enable the approved scraping source for the same or a controlled comparable subject;
2. rerun additively;
3. compose again;
4. compare coverage, source tiers, conflicts, freshness, derivations, and visible output;
5. verify that the scraper adds evidence rather than overwriting history.

### Stage C — Postman/API

Prerequisites:

- local PostgreSQL running and migrated;
- real persisted project/run/account/contact IDs;
- explicit local-dev header authentication;
- only `CLUE_C7_RESEARCH_VIEW_READ_ENABLED=true` initially;
- API launched through the new production entrypoint.

Initial calls:

```http
GET /v1/projects/{project_id}/accounts/{account_id}/research-view
X-Workspace-Id: {workspace_id}
X-Actor: human
```

```http
GET /v1/projects/{project_id}/contacts/{contact_id}/research-view
X-Workspace-Id: {workspace_id}
X-Actor: human
```

Repeat each GET and verify the same ETag/source hash when authority state is unchanged. Resolve
identity, score, committee, coverage, and activity owner refs. Inspect direct/derived claim IDs,
support edges, reason codes, display/outreach separation, and evidence action kinds.

Only after read quality is accepted, enable and test in order:

1. snapshot composition;
2. saved snapshot resolution;
3. evidence actions;
4. recheck;
5. production handoff;
6. legacy aliases, only if still required.

Check in a sanitized Postman collection and a local runbook containing exact environment
variables, launch command, seed/scope discovery, requests, expected status codes, and rollback.

## 17. Rollout and rollback

Activation order:

1. flags off while migrations and readers land;
2. internal fixture/database shadow composition;
3. Exa-only manual trial through direct production composer;
4. scraper comparison;
5. API/Postman local trial;
6. read-only internal workspace canary;
7. snapshot canary;
8. evidence canary;
9. recheck canary;
10. handoff cutover;
11. broader workspace admission.

Rollback:

- remove workspace from canary policy or disable the corresponding global flag;
- stop serving routes/tools/actions;
- leave additive claims, verdicts, receipts, and audit rows intact;
- never delete research history or rewrite claims to roll back a read adapter;
- do not downgrade migrations while any process at the new code version is running.

## 18. Definition of done

C7.9 is done only when all of the following are true:

1. a real production caller constructs and invokes `build_research_view_composer`;
2. all eight readers use real stores/services;
3. API and fleet share one production runtime builder;
4. every view is composed in one read-only repeatable-read unit of work;
5. canonical identity versions and merged-member claims are correct;
6. field routing is registered, versioned, and non-heuristic;
7. current claims and scores are exact-product/run safe;
8. derived required supports cannot launder display- or outreach-disallowed content;
9. flagged derived roots cannot mask redacted supports;
10. retention/objection sweep reachability matches interactive erase;
11. statement governance and evidence authorization share one current evaluator;
12. display and outreach remain independent;
13. the committee path is request-scoped and batch-loaded;
14. contact coverage is honest about its current durable limitations;
15. activity is exact-subject and journal-owned;
16. all non-claim owner references are resolvable by authenticated owner reads;
17. enabled-but-unconfigured flags fail startup;
18. query-count, concurrency, adversarial, DSAR, migration, and full-repository gates pass;
19. a real Exa-only run can be composed and inspected before scraper/API testing;
20. the read flag remains default-off until explicit canary activation.

Anything less is a partially implemented read seam, not a production research-view subsystem.

## 19. Implementation closeout

### 19.1 Delivered

C7.9.0–C7.9.6 are implemented end to end:

- migration `6a7f8eed5b23` adds canonical identity versions, registered field routes,
  exact-subject activity, display policy, product-aware change reports, and product-safe legacy
  handoff identity;
- owner queries resolve exact workspace/project/project-run/account-run/product/subject scope,
  canonical members, run-pinned claims, scores, committee eligibility, coverage, and activity;
- current governance and evidence authorization share one batch evaluator over verification,
  freshness, conflicts, erasure, objections, display policy, outreach policy, and the transitive
  derivation support graph;
- all eight database readers compose through one read-only `REPEATABLE READ` production wrapper;
- API, governed tools, fleet, snapshots, recheck, evidence actions, handoff, and owner-reference
  resolution share the same production runtime;
- enabled-but-incomplete startup fails closed, local header auth and workspace canaries are
  explicit, and every C7 capability remains independently default-off;
- retention/objection sweeps use the same dependent expansion and legacy-payload purge as
  interactive erase;
- entailment and faithfulness use one strict JSON response parser;
- the body-safe production trial CLI, Exa-first runbook, and sanitized Postman collection are
  checked in.

The implementation remains presentation-neutral. It reads typed claims, derivations, governed
states, and body-free owner references; it does not create a Markdown dossier or frontend model.

### 19.2 Automated verification

The closeout gates were run from clean isolated PostgreSQL databases:

- Ruff passed for every changed Python surface; mypy passed for 446 source files;
- all 24 import contracts passed over 508 files and 3,799 dependencies;
- the focused C7/adjacent suite passed, including readers, D7 support governance, DSAR, scoring,
  handoff, API, fleet, contracts, identity, and migration-dependent paths;
- production composition passed the same bounded query ceiling at 1, 25, and 100 statements;
- the DB-enabled repository suite passed with the three pre-existing order-sensitive
  logging/OpenTelemetry tests deselected, and those three passed separately;
- Alembic reports the single head `6a7f8eed5b23`;
- a clean database passed full `head -> base -> head` migration reversibility;
- the production CLI help/startup contract and checked-in Postman JSON were validated;
- scoped `git diff --check` passed while unrelated worktree changes were preserved.

### 19.3 Activation state and remaining manual acceptance

No C7 flag was enabled and no live Exa, scraper, or customer-data trial was fabricated. The
remaining gate is deliberately a human quality decision, not missing reader code:

1. persist one normal governed Exa-only account/contact research run;
2. inspect it with `scripts/07_research_view_trial.py`;
3. decide whether the actual research quality is worth continuing;
4. only then run the scraper comparison;
5. only after that enable the read flag for one workspace and use the Postman collection.

The CLI is read-only and has no fixture/acquisition fallback. If routes or persisted scope are
missing it fails explicitly. Operational rollback remains flag/canary removal; migration downgrade
is a development reversibility proof, not the live rollback strategy.
