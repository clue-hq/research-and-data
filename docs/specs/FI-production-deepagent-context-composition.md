# Production Deepagent Context Composition

**Status:** IMPLEMENTED on `platform/onboarding-integration`; production release blocked by the
live fast-lane latency exception recorded in the S6 acceptance
**Date:** 2026-08-14
**Owners:** frontend/backend integration + platform agent runtime
**Authority:** contract delta to Doc A Part III and PC-C8 for this production composition. Where
this document conflicts with the provisional note in root `CLAUDE.md`, this document wins.

**Founder supersession (2026-08-19):** the S5.0
`selected_without_product_knowledge` state is historical-only. Product confirmation now
atomically bootstraps an empty 0/N Product-KB v1, and new turn pins use
`company-and-selected-product-required-v3`, which requires an exact Product-KB version whenever a
product is selected. The empty lineage admits the bounded ProductKnowledgeCard and its governed
tools without fabricating facts or requiring a verification judge; later product research fills
the registered open gaps. See the child contract callout for replay and repair semantics.

**Implementation checkpoint (2026-08-15):** S0-S5 are implemented. S4-A's version-aware reader,
S4-B's immutable contract freeze, S4-C's trusted `@2` implementations, S4-D's production
composition, and S4-E's privacy/injection/replay hardening all pass their gates. The previously
shipped `@1` tools and Head-of-ABM `v24` / Stage-0 skill `v11` / Recipe #0 `v7` graph remain frozen
historical replay resources; S4-D's profile `v25` / skill `v12` also remain immutable. Current
historical production selected `@2`, profile `v26`, skill `v13`, and Recipe #0 `v8`. S3.1 adds the immutable
per-turn scope receipt, statement-level production-card DSAR binding, exact vN retry behavior, and
real-fleet acceptance. S5.0 ratifies the separate company/product knowledge model, paired
selected-product card/tools, trusted-only product scope, `ClientKnowledgeCard@2` catalog, and the
new-turn `company-and-selected-product-v2` policy in the
[S5.0 child contract](./FI-production-deepagent-context-S50-product-knowledge-contract.md). S5-A–F
now ship the grounded catalog/product materializer, catalog-to-spine lineage, V2/product cards,
trusted product tools, durable version pair, real fleet composition, and human product-selection
gate through profile `v27`, skill `v14`, and Recipe #0 `v9`. S6 adds publication refresh,
privacy-safe OTLP observability, body-free operator reads, and full production composition. The
closure run promotes profile `v28` / skill `v15`, proves real catalog selection and product
knowledge use, and records the blocking 103.759-second fast phase in the
[S6 acceptance](./FI-production-deepagent-context-composition-S6-acceptance.md).

## 1. Purpose

This plan composes onboarding recon, customer-account knowledge, brand context, active-project
context, and Stage-0 interview state into the production platform deepagent. It does not stop at
model classes, fixture-only compilers, or the trial harness.

The user-visible outcome is:

1. onboarding recon researches the customer's company once;
2. eager and background recon publish versioned, provenance-backed Client-KB claims;
3. every project in that customer workspace can use that same Client-KB;
4. every turn also receives its own brand, project, thread, and confirmed-product context;
5. only the active project's Stage-0 interview/readiness state is supplied;
6. the agent sees short, interpretable knowledge descriptions and follows references when it
   needs exact facts or provenance;
7. the agent can present the discovered product catalog and a human can confirm which product the
   current project concerns.

“Customer account” in this document means the client/workspace using Clue. It never means a target
account being researched for an ABM project.

## 2. Current production truth

### 2.1 Present

- The L1-L7 deterministic context assembler exists.
- L2 already attempts to load brand and confirmed-product cards through
  `WorkspaceProductLayerSource`.
- L3 already loads one `project_card_ref`, one budget envelope, and any explicitly constituted
  `project_context_artifacts`.
- The production `AGENT_TURN` worker creates an always-present `project_conversation_card`.
- That worker attaches a paired `ClientKnowledgeCard` and active-project-only
  `Stage0ProjectStateCard` whenever the canonical client has a published account-wide KB version.
- The resulting constitution carries exact client/version and project domain refs; the context
  receipt retains exact artifact refs, hashes, and materialized paths.
- Onboarding recon establishes an insert-once canonical client binding for the workspace; every
  valid project resolves the same client without inspecting project-scoped inputs.
- The PC-C8 projection compiles a hard-bounded `Stage0ProjectCard` containing project identity,
  Client-KB briefs/refs/gaps, interview state, readiness, ICP state, omissions, and lineage.
- The claim store, version-scoped `read_client_kb_claims`, field registry descriptions, statement
  evidence reader, durable artifacts, toolbelt, role registry, and product spine exist.
- `confirm_project_product` already provides human-authorized, idempotent project/product binding.

### 2.2 Missing or incorrectly composed

- The legacy trial compatibility projection still combines account and project state; production
  no longer consumes it.
- Recon's product description is not yet a durable multi-product catalog bound to product rows.

### 2.3 Brand-context boundary

L2's production reader can currently compile the durable `brand` row and confirmed `product` row.
The platform brand-kit/voice substrate from the design subsystem is not yet integrated on this
branch. This work must not fabricate it or import design internals in violation of the branch
charter. Production will:

- always compose the real brand identity available now;
- compose the confirmed product card when one exists;
- represent unavailable brand-kit/voice context honestly;
- accept the future compiled brand-context card behind the existing L2 reader seam without an L3
  contract change.

## 3. Binding decisions

### D1 — Context is a bundle of independently owned bounded artifacts

The opening context is not one giant JSON document and not two competing “whole L3 cards.”

```text
L2 workspace/product
├── BrandContextCard                    brand-scoped
└── ProductProfileCard                  selected-product-scoped, conditional

S5 selected-product extension
└── ProductKnowledgeCard                selected-product-scoped, conditional on product KB

L3 project
├── ProjectConversationCard             active project/thread envelope, always present
├── ClientKnowledgeCard                 account-wide; V2 adds bounded product catalog in S5
└── Stage0ProjectStateCard              active-project-scoped, conditional on Client-KB
```

The budget envelope remains separate authority, not descriptive context.

### D2 — One owner per model-visible field

`ProjectConversationCard` owns:

- workspace, brand, project, and thread identity;
- project name/status;
- confirmed `product_id`;
- typed availability of the account-wide Client-KB and project Stage-0 context.

`ClientKnowledgeCard` owns:

- `client_entity_id` and exact `client_kb_version`;
- bounded topic/field descriptions, briefs, claim refs, gaps, coverage, and Client-KB omissions.
- in V2, the bounded company product catalog and its catalog-claim refs, but never detailed
  product-scoped facts.

`ProductProfileCard` owns selected-product identity: product/brand ids, name, aliases, and status.

`ProductKnowledgeCard` owns the selected product's exact product-KB version, bounded knowledge
index, gaps, coverage, omissions, and lineage. Its body does not repeat profile identity.

`Stage0ProjectStateCard` owns:

- current-effective statements for exactly one project;
- statement selection/omissions and evidence exclusions;
- current readiness decisions and history omission;
- project-specific product-selection status;
- project-originated field-proposal refs;
- ICP refs/proposal state;
- project-state compilation lineage.

Repeated identifiers are removed from model-visible child payloads. Scope validation remains
engine-side and is stricter than before; removing JSON duplication never removes authorization.

### D3 — Shared Client-KB, isolated project state

One durable binding establishes the workspace's canonical client entity. It is immutable under
ordinary production flows. Every project in that workspace inherits it.

```text
Project A -> ClientKnowledgeCard(client, vN) + Stage0ProjectStateCard(A)
Project B -> ClientKnowledgeCard(client, vN) + Stage0ProjectStateCard(B)
```

Project B must never read Project A's statements, readiness rows, ICP proposal state, or Stage-0
artifact. Cross-workspace reads fail as an indistinguishable miss/refusal.

### D4 — A turn is pinned to one coherent knowledge version

Before card compilation or model/tool execution, the worker inserts one immutable
`agent_turn_scope_pin` row containing the trusted workspace, project snapshot, brand, confirmed
project product, canonical `client_entity_id`, account-wide `client_kb_version`, policy version,
and DB timestamp. Every worker retry reads that row. The envelope, constitution, Client-KB card,
Stage-0 card, governed S4 arguments, checkpoints, finalization, and replay all use that exact pin.

If background recon publishes vN+1 while a vN turn is running, the running turn stays on vN. The
same rule applies after a crash: a reclaimed vN turn completes on vN, while only a newly submitted
turn receives vN+1. A committed legacy turn that predates the receipt may replay its retained
artifacts, but production must not fabricate a historical pin from current state. Partial version
mixing is forbidden.

The frozen `company-account-wide-v1` policy has one precise meaning: the Client-KB card and S4
reads select only the account-wide marker/claims (`product_id IS NULL`). `project.product_id` is a
separate project pin used by L2 and Stage-0 project state; it never silently filters the shared
Client-KB. S5.0 ratifies, but does not yet cut over, `company-and-selected-product-v2`: new turns
will pin the company version plus the independently current selected-product version (when one
exists) in one DB snapshot. Historical V1 rows remain replayable and are never reinterpreted.

### D5 — References must explain what they lead to

Each bounded Client-KB reference contains:

```json
{
  "field_key": "client.differentiator",
  "label": "Differentiators",
  "description": "What distinguishes the company from alternatives",
  "topic": "positioning",
  "brief_value": "…",
  "claim_id": "…",
  "brief_truncated": false
}
```

Descriptions come from the registered field definition or a versioned deterministic fallback.
The model never invents labels and an opaque id alone does not count as usable context.

### D6 — Full facts are pulled on demand

Opening context remains bounded. The Head-of-ABM production profile receives two governed reads:

1. `list_client_knowledge@2` — browse/search the exact turn-pinned Client-KB by topic, field,
   cursor, and bounded page size;
2. `inspect_client_claim@2` — resolve one referenced claim into value and bounded provenance.

The preliminary `@1` tools remain immutable historical replay/compatibility resources after the
S4-D atomic cutover; they are not current production authority or the default contract.

The exact-claim result includes field metadata, value, public source origin/key/tier, evidence span,
bounded artifact/provider lineage, confidence, verification, freshness timestamps, product scope,
and lineage refs. The exact URL is represented by a SHA-256 digest so credentials, query tokens,
fragments, and path-embedded secrets cannot enter model context. It never returns raw page bodies
or an unbounded claim table.

Both tools derive workspace/client/version authority from the trusted `ToolContext`/constitution.
The model cannot choose a workspace, client entity, or KB version. Unknown, foreign, expired,
wrong-version, or non-member claims fail closed. A vN row superseded only by vN+1 remains a vN
member and must continue to resolve for an already-pinned vN turn.

S5 adds separate `list_product_knowledge@1` and `inspect_product_claim@1` addresses. Their only
model fields are the same bounded filters/reference; trusted runtime injection supplies
workspace/client/confirmed-product/product-version. The company tools never gain a product scope
argument, and each tool pair refuses claims from the other scope.

### D7 — Human-confirmed product choice is project-specific

Recon may discover multiple customer products. Those candidates are account/brand catalog data,
not a project decision. The agent may describe the catalog and ask which product this project is
about. Only the human-authorized `confirm_project_product` operation writes `project.product_id`.

The same catalog can be offered in Projects A and B; the confirmed product can differ.

### D8 — Production entrypoints are part of every slice

A slice is incomplete until its capability is composed through the real worker, assembler,
toolbelt/profile/recipe, durable artifacts/database, and replay path where applicable. Trial-only
or fixture-only success is not an exit.

### D9 — Human gates share one exact-subject authority contract

Directive confirmation, ICP confirmation, and product selection use one durable gate/answer
substrate. Every gate retains the exact subject reference, nullable revision, immutable snapshot
and digest, permitted decisions, human addressee, scope, and erasure bindings. Cost and currency
are a paired nullable value: non-spend gates store null, and a withheld amount is never projected
as zero. Erased, stale, foreign, malformed, unsupported, or already-answered gates are
non-interactive.

The answer envelope has two deliberately separate extension points:

- `decision_payload` is bounded auxiliary input. Its only current member is the non-blank
  `revision_request` required by `icp_confirmation + revised`.
- `selected_option_ref` is the dedicated durable catalog choice. It is required only for
  `product_selection + approved`, and the server derives it from a browser
  `selected_product_id` after proving that candidate belongs to the immutable gate snapshot.

No request or receipt may contain both a revision request and a selected option. Product
rejection/revision, ICP approval/rejection, and directive decisions carry neither extension.
Every response must match the stored digest, addressee, scope, unanswered state, and permitted
decision before the answer and any human-only operation commit atomically.

The frontend models ordinary decisions, ICP revision, and product approval as a discriminated
union keyed by gate kind/action. Product receipts render the retained candidate name, not raw
transport JSON or a technical identifier. The canonical frontend wire and full invariant table
live in [`apps/frontend/docs/api-contracts/projects.md`](../../apps/frontend/docs/api-contracts/projects.md#combined-human-gate-amendment-2026-08-15).

## 4. Frozen contracts

### 4.1 `ProjectConversationCard@2`

```jsonc
{
  "schema_version": "2",
  "card_kind": "project_conversation",
  "surface": "project_conversation",
  "project": {
    "project_id": "prj_…",
    "name": "…",
    "status": "draft|active|archived",
    "workspace_id": "ws_…",
    "brand_id": "brd_…",
    "confirmed_product_id": "prd_…|null"
  },
  "thread": {"thread_id": "…"},
  "context_availability": {
    "client_knowledge": "available|unavailable",
    "stage0_project_state": "available|unavailable",
    "brand_profile": "available|minimal|unavailable",
    "product_profile": "available|unavailable"
  }
}
```

It carries no Client-KB body/version/entity id and no interview/readiness state.

### 4.2 `ClientKnowledgeCard@1`

Content address is a pure function of `(workspace_id, client_entity_id, client_kb_version,
compiler_policy_version, durable source rows)`.

```jsonc
{
  "schema_version": "1",
  "card_kind": "client_knowledge",
  "content_semantics": "reference_metadata_is_untrusted_data",
  "compiler_policy_version": "client-knowledge-card-policy-v1",
  "client": {"client_entity_id": "uuid", "client_kb_version": 7},
  "knowledge": {
    "known_fields": [/* D5 entries */],
    "open_gaps": ["client.market_reputation"],
    "coverage": {/* bounded counts */}
  },
  "omissions": [{"kind": "client_knowledge_over_cap", "count": 4, "cursor": "…"}],
  "compiled_from": {/* version, field-definition versions, policy */}
}
```

It contains no project, thread, interview, readiness, ICP, or project-product confirmation state.

### 4.3 `Stage0ProjectStateCard@1`

Artifact binding, not model-visible duplicated identity, proves which project owns it. The compiler
requires trusted `(workspace_id, project_id, client_entity_id, client_kb_version)` and rejects any
scope disagreement before bytes are persisted.

```jsonc
{
  "schema_version": "1",
  "card_kind": "stage0_project_state",
  "compiler_policy_version": "stage0-project-state-policy-v1",
  "product_selection": {"status": "unselected|confirmed"},
  "field_proposals": {"pending": 0, "refs": []},
  "interview": {/* bounded current-effective statements */},
  "readiness": {/* current decisions */},
  "icp": {/* confirmed refs and proposal status */},
  "omissions": [/* project-state-only omissions */],
  "compiled_from": {
    "client_knowledge_sha256": "sha256:…",
    "statement_selection_digest": "sha256:…",
    "readiness_decision_ids": [],
    "confirmed_icps": [],
    "compiler_policy_version": "stage0-project-state-policy-v1",
    "source_policy_version": "stage0-card-policy-v1"
  }
}
```

### 4.4 Production constitution

- `project_card_ref` points to `ProjectConversationCard@2`.
- `project_context_artifacts` contains `client_knowledge` and `stage0_project_state` when available.
- Each extra artifact has a workspace-scoped artifact ref and a typed domain ref.
- The Stage-0 domain ref is for the active `project_id` only.
- The Client-KB domain ref is for the canonical `client_entity_id` and exact KB version.
- `AgentConstitution.client_entity_id` carries the same trusted client pin for engine-side tool
  argument injection. It is authority, not a second model-facing fact.

### 4.5 S5 product-knowledge contract

S5.0 freezes the additive `ClientKnowledgeCard@2`, `ProductProfileCard@1`,
`ProductKnowledgeCard@1`, separate product `@1` tools, and trusted product-version pin. Exact
ownership, state transitions, authority fields, compatibility, and privacy requirements live in
[`FI-production-deepagent-context-S50-product-knowledge-contract.md`](./FI-production-deepagent-context-S50-product-knowledge-contract.md).
These are current new-turn production surfaces after S5-A–F passed. Historical receipts retain
their original media types, policy versions, and resources.

## 5. Data and lifecycle

### 5.1 Canonical client binding

Add `workspace_client_binding`:

- `workspace_id` primary key/FK;
- `client_entity_id` workspace-composite FK to `account_entity`;
- `source_recon_run_id` nullable provenance FK;
- timestamps;
- ordinary production writes are insert-once/idempotent-same and refuse a different entity.

The authoritative onboarding fleet writes this binding in the same transaction that establishes
the recon's client identity. Existing project-scoped onboarding rows are not the account binding.

### 5.2 Durable turn-scope receipt

`agent_turn_scope_pin` is the retry authority for production `AGENT_TURN` composition:

- exactly one append-only row per `agent_turn_submission.turn_id`;
- workspace-composite FKs for the submission, project, brand, optional product, and optional
  canonical client entity;
- a coherent optional `(client_entity_id, client_kb_version)` pin;
- DB-authored `pinned_at` and explicit `knowledge_scope_policy_version`;
- atomic `INSERT ... ON CONFLICT DO NOTHING`, after which a losing concurrent attempt reads the
  winning row rather than using its discarded current-state observation;
- workspace-scoped reads and fail-closed rejection of unsupported policy versions.

The row is created before cards, context assembly, model execution, or tools. Ordinary retries,
crash recovery, and committed replay never update or delete it.

S5 adds `product_kb_version` and the `company-and-selected-product-v2` meaning to new rows.
The existing `client_kb_version` remains the physical company-version column; it is not renamed or
reinterpreted. V2 resolves the optional selected-product version in the same DB snapshot and
supports honest `(confirmed product, no product KB)` rows.

### 5.3 Card persistence

Cards are content-addressed immutable artifacts with privacy/DSAR subject bindings:

- Client-KB card: client subject binding, no project binding required for identity;
- Stage-0 card: client subject binding, one `derived` subject binding for every exact statement
  quote embedded in the body, plus exactly one project binding;
- conversation envelope: active project binding and client binding when available.

Identical Client-KB versions across projects persist/reuse one blob while each turn retains its
own context receipt.

### 5.4 Refresh and retry

- Fast recon commit creates/updates the current account-wide Client-KB version; the next unpinned
  turn persists that current version.
- Background recon does the same without mutating an already pinned or assembled turn.
- Interview-derived Client-KB claims publish a new version before a later turn can reference them.
- A Stage-0 project-state change recompiles only that project's artifact.
- A crash/retry before finalization reuses the immutable scope pin even if a newer version exists.
- Replay of a committed turn reuses its original scope/context receipts and performs zero
  recon/model/tool work.

## 6. Product catalog

S5 adds `client.product_catalog` as a registered tenant-private Client-KB field shaped as a bounded
list of objects with at least `name` and optional `description`/`aliases`. Official-site extraction
grounds each catalog claim in exact snapshots like every other Client-KB claim.

At the API composition root, a catalog synchronizer:

- reads the pinned catalog claim after Client-KB commit;
- normalizes names conservatively;
- inserts/reuses active `product` rows under the recon brand;
- never archives or renames an existing product automatically;
- records claim-to-product lineage;
- is idempotent on replay;
- refuses cross-workspace/brand rows.

`ClientKnowledgeCard@2` describes available products with product refs and bounded catalog
claim lineage. It never embeds detailed product facts. After confirmation, the independently
versioned Product-KB card/tools describe only that product. The Stage-0 agent proposes from the
catalog refs; existing human-only `confirm_project_product` remains the sole project-binding write.

## 7. Sliced roadmap

### S0 — Contract freeze and adversarial fixtures

**Deliverables**

- Land this specification and update Doc A/PC-C8/CLAUDE authority notes.
- Freeze the three model-visible schemas, domain refs, media types, caps, cursor shapes, tool
  contracts, and production composition seam.
- Add provider/DB-free fixtures for pre-recon, post-fast-recon, post-background-recon, Project A,
  Project B, product-unselected, and product-confirmed states.

**Passing criteria**

- Contract fixtures validate without network or DB.
- No unresolved decision can change DDL, card ownership, or tool input authority.
- Static assertions fail if Client-KB facts appear in the conversation or Stage-0 card.
- Static assertions fail if project interview/readiness data appears in the Client-KB card.

**Implemented evidence:** `tests/fixtures/production_context/s0_contract_fixture.json` and
`tests/projections/test_production_context_contracts.py`.

### S1 — Card split and deterministic compilers

**Deliverables**

- Implement `ClientKnowledgeCard` and `compile_client_knowledge_card`.
- Implement `Stage0ProjectStateCard` and `compile_stage0_project_state_card`.
- Upgrade the generic envelope to `ProjectConversationCard@2`.
- Preserve a temporary compatibility compiler only for existing trial callers; production cannot
  consume the legacy combined payload.
- Derive readable labels/descriptions/topics from the field registry.

**Passing criteria and tests**

- Byte-identical durable inputs produce byte-identical cards and SHA-256s.
- Client card changes when KB version/claim/field-description/policy changes.
- Project card changes for Project A statements/readiness and not for Project B.
- No duplicated ownership fields occur in serialized payloads.
- Every claim ref has non-empty label, description, topic, and brief.
- Caps, UTF-8 boundaries, omissions, cursor determinism, DSAR missing evidence, and adversarial
  field descriptions pass.

**Implemented evidence:** `platform/projections/clue_projections/production_context.py`, the v2
envelope seam in `platform/api/clue_api/agent_turn_fleet_wiring.py`, and the provider-free/DB/API
tests in `tests/{projections,api}/test_production_context_*`.

### S2 — Canonical account binding and inheritance

**Deliverables**

- Add reversible Alembic migration and repository primitives for `workspace_client_binding`.
- Bind the authoritative onboarding recon client in production.
- Replace project-input inference with canonical workspace binding for production conversations.
- Retain project-scoped onboarding rows as statement/evidence provenance only.

**Passing criteria and tests**

- One Alembic head; clean upgrade/downgrade/upgrade.
- Repeating the same bind is a no-op; a different entity is refused.
- Cross-workspace entity binding fails at DB and repository boundaries.
- A newly created Project B inherits the same client as Project A without fixture assistance.
- No target-account entity can be substituted through user/model input.

**Implemented evidence:** `alembic/versions/b2f815da0f31_workspace_client_context_binding.py`,
`platform/api/clue_api/client_context_binding.py`, production fleet composition in
`stage0_setup_fleet.py`, the canonical conversation reader, and the database/adversarial coverage
in `tests/api/test_{client_context_binding,stage0_setup}_db.py`.

### S3 — Production brand/envelope/Client-KB/Stage-0 composition

**Deliverables**

- Compose real L2 brand and confirmed-product cards.
- Compile/persist the envelope, Client-KB card, and active-project Stage-0 card in the production
  `AGENT_TURN` worker.
- Attach the latter two through `project_context_artifacts` with exact domain refs.
- Pin one coherent Client-KB version per turn and add privacy-safe composition logs.

**Passing criteria and tests**

- Pre-recon turn: brand + envelope, typed Client-KB/Stage-0 unavailability, no fabricated artifacts.
- Post-recon turn: brand + envelope + Client-KB + active project's Stage-0 artifact.
- Project B receives shared Client-KB and only Stage0(B), never Stage0(A).
- Background vN+1 during a vN turn affects only the next turn.
- Missing/cross-workspace artifacts fail closed before model invocation.
- Context receipt enumerates the exact refs/hashes/materialized paths.
- Production replay reuses the original receipt and card refs.

**Implemented evidence:** production composition and account-wide version pinning in
`platform/api/clue_api/agent_turn_fleet_wiring.py`; immutable pre-composition replay in
`platform/api/clue_api/conversation_turns.py`; exact paired-domain-ref enforcement in
`platform/agents/clue_agents/contracts.py`; null-safe separation of account-wide and product-scoped
KB version sequences in `subsystems/research/clue_research/stage0/client_kb.py`; and the pre/post-
recon, Project-A/B, mixed-account/product-version, background-version, receipt, missing-artifact,
cross-workspace, privacy-log, and replay acceptance in
`tests/api/test_production_context_s3_db.py` plus the production fleet replay tests.

### S4 — Governed Client-KB discovery and exact claim inspection

S4 continues as five internal checkpoints. Existing preliminary `@1` work is retained, but S4 is
not complete until S4-E passes. The word **superseded** has one precise tool-read meaning here: a
claim is unavailable when it is absent from the exact pinned version. A row selected into vN does
not become unavailable to a vN turn merely because a later vN+1 row supersedes it globally.

#### S4-A — Version-aware Client-KB readers

**Deliverables**

- Resolve exact version membership through the Client-KB marker/run graph.
- Classify and filter by the registered field key and bounded knowledge topic.
- Resolve both the card's included references and its omitted continuation.
- Read retention-eligible historical rows with `include_superseded=True` without reviving expired
  rows.
- Provide deterministic baseline-then-extension ordering, bounded pages, and shorter continuation
  windows without refetching or rewriting claims.
- Fail closed at the workspace plus canonical-client boundary.

**Passing criteria and tests**

- A vN turn resolves its exact vN row after a published vN+1 row sets vN's `superseded_by` edge.
- A same-version replacement makes the old row a non-member and therefore unavailable.
- Unknown, foreign, outside-version, same-version non-member, and retention-expired claim refs
  produce the same non-oracular refusal.
- Foreign workspace/client bindings and invented continuation positions fail closed.
- Included and omitted refs resolve; topic/field filters, ordering, and multi-page traversal are
  deterministic and duplicate-free.

**Implemented evidence:** `platform/api/clue_api/client_knowledge_reader.py` is the shared reader
seam. The preliminary `@1` tools now consume that seam instead of treating a global supersession
edge as version membership. Real version-marker, claim-lineage, retention, workspace/client,
included/omitted, classification, ordering, and pagination acceptance lives in
`tests/api/test_client_knowledge_tools_s4_db.py` and runs against an isolated PostgreSQL database.

#### S4-B — Immutable tool-contract freeze

The preliminary `list_client_knowledge@1` and `inspect_client_claim@1` schemas were already
committed and pinned by immutable production resources before this checkpoint was amended. They
must not be rewritten in place. The frozen target is consequently
`list_client_knowledge@2`/`inspect_client_claim@2`; after S4-D, `@1` remains only a historical
replay/compatibility surface while current production selects `@2` atomically.

**Deliverables**

- Freeze strict `@2` input and nested output schemas and their canonical schema hashes.
- Freeze client/claim/run identifiers as UUID-shaped values and claim method/status/lineage plus
  timestamps as typed enums/datetimes rather than unconstrained strings.
- Freeze model-visible list inputs as `topic?`, `field_key?`, `cursor?`, and `limit?`; freeze the
  inspect input as `claim_id` only.
- Freeze runtime authority as `workspace_id` from `ToolContext` plus injected
  `client_entity_id`/`client_kb_version`; project and product are not public tool inputs.
- Freeze default page size 10, maximum page size 20, a 4,096-byte cursor ceiling, a 32,768-byte
  list-response ceiling, and a 16,384-byte inspection-response ceiling.
- Freeze deterministic v2 cursors bound to client, version, continuation position, topic, field,
  and limit. Accept an S1 v1 omission cursor only for the default unfiltered continuation.
- Freeze explicit UTF-8 byte ceilings and truncation markers for descriptions, briefs, values,
  evidence spans, and provider/artifact references.
- Freeze source URL output to a public HTTP(S) origin plus exact-URL SHA-256; credentials, path,
  query, fragment, localhost/private-IP, and local/internal hostnames never cross the output
  boundary.
- Freeze three refusal codes: scope unavailable, cursor invalid, and claim not found. Malformed,
  foreign, cross-version, stale, and cross-filter cursor failures share the same public semantics.
- Mark all returned descriptions, values, and evidence as untrusted evidence, never instructions.

**Passing criteria and tests**

- Contract fixtures and schema-hash checks run without DB, network, storage, or provider access.
- Unknown input/nested-output fields are rejected and authority fields are absent from the
  model-visible field allowlists.
- Cursor encoding is deterministic; malformed, cross-client, cross-version, cross-topic,
  cross-field, and cross-limit cursors refuse identically.
- Page/count/continuation invariants and every byte/truncation/source-sanitization boundary are
  machine checked.
- No remaining S4-C implementation decision can change the public tool schema; any future public
  change requires another immutable version.
- `@2` is not production-registered by S4-B; that authority belongs only to S4-D.

**Implemented evidence:** the provider/DB-free contract module is
`platform/api/clue_api/client_knowledge_contracts.py`; the frozen manifest is
`tests/fixtures/production_context/s4b_tool_contract_fixture.json`; and exhaustive pure acceptance
is in `tests/api/test_client_knowledge_contracts_s4b.py`.

#### S4-C — Trusted authority and `@2` tool implementation

**Deliverables**

- Implement both frozen `@2` contracts over the S4-A reader seam.
- Limit model-authored arguments to the S4-B allowlists.
- Inject workspace/client/version from the validated turn constitution and paired
  `client_knowledge` domain reference.
- Resolve the S1 omission cursor and subsequent v2 cursors without exposing cross-scope state.

**Exit gate**

- Injected client/version match the paired context artifact, and no model-authored authority value
  can override them.
- An included ref and an omitted ref resolve at the exact pinned version.
- Cross-workspace and unavailable-version scopes share `client_knowledge_unavailable`. Within a
  valid pinned scope, unknown, foreign, outside-version, same-version non-member, and expired claim
  refs share `client_claim_not_found`; neither class discloses which internal scope/ref check failed.
- The implementation conforms byte-for-byte to S4-B schemas without changing their hashes.

**Implemented evidence:** `platform/api/clue_api/client_knowledge_tools.py` provides the separate
`@2` builder and effect-free implementations over the S4-A reader; S4-D registers that builder at
the central composition root while retaining the separate `@1` builder for immutable replay;
`platform/api/clue_api/client_context_authority.py` makes `@2` require the validated paired
`client_knowledge` artifact while preserving only `@1`'s frozen trial compatibility fallback; and
the governed execution seam injects that exact version alongside the constitution client and
`ToolContext` workspace. Provider-schema, smuggling, pairing, no-fallback, central-registry
boundary, real-PostgreSQL included/omitted/pagination/version/refusal/truncation/provenance, and
zero-write/cost replay acceptance lives in
`tests/api/test_client_knowledge_tools_s4c{,_db}.py`. The shared tool runner now validates durable
results in JSON mode, so strict UUID/enum/datetime/Decimal/tuple outputs survive fresh execution and
cold replay without weakening the frozen models.

#### S4-D — Production toolbelt composition

**Deliverables**

- Register `@2` through the central registry, capability authority, Head-of-ABM production
  profile, project-conversation surface policy, progressive Stage-0 skill, recipe compatibility
  pins, and user-facing tool guidance.
- Create new immutable profile, skill, and recipe versions instead of editing the preliminary
  Head-of-ABM `v24`, Stage-0 skill `v11`, or Recipe #0 `v7` in place.
- Cut all required production surfaces over atomically; do not mistake trial/fixture wiring for
  production composition.

**Exit gate**

- Static audits prove `@2` is both centrally registered and actually granted on the production
  surface.
- The production conversation recipe resolves the new profile and skill revisions.
- No coordinator branches on provider identity or special test mode.
- The prior `@1` resource graph remains replayable but is no longer the current default.

**Implemented evidence:** the central toolbelt now registers both immutable versions and elects
`list_client_knowledge@2` / `inspect_client_claim@2` as name defaults. Exact-address authority
admits only `@2` for the Head of ABM, while `@1` remains inventory-visible and role-unavailable.
The production project-conversation surface resolves Head-of-ABM profile `v25`, progressive
Stage-0 skill `v12`, and both `@2` tools. Recipe #0 `v8` replaces only the two tool pins, the shared
production conversation pin selects `v8`, and normal recipe promotion supersedes `v7` without
rewriting it. Static registry/profile/surface/schema/recipe audits and DB-backed recipe-promotion,
interaction-slot, fleet-conversation, and exact replay tests cover the cutover; the registration is
unconditional and contains no provider or test-mode branch.

#### S4-E — Privacy, injection, and replay hardening

**Deliverables**

- Trace inspected facts through tool execution events, tool-result artifacts, LangGraph
  checkpoints/tool messages, stream/outbox events, context receipts, and finalization receipts.
- Add subject binding or bounded redaction/erasure semantics to every durable exact-value/evidence
  copy.
- Treat claim values, descriptions, evidence spans, and page text as untrusted evidence in both
  the contract and agent instructions.
- Prove replay is effect-free and cannot resurrect erased fact bodies.

**Exit gate**

- DSAR removes every durable copy and subsequent replay cannot restore it.
- Prompt-shaped claim content cannot influence tool authority or selection.
- Replay produces zero writes, zero provider spend, and the same reference set.
- Tokens, credentials, raw bodies, and unrestricted source URLs never appear.

**Implemented evidence:** `platform/api/clue_api/client_knowledge_privacy.py` is the single
production policy for Client-KB exact-result subject indexing and body-free stream projection. The
governed execution seam binds every validated `@2` tool-result artifact to its trusted client and
each returned claim id without interpreting any prompt-shaped nested content. The model still gets
the frozen bounded result; the durable stream/outbox receives only operation correlation, the
trusted client/version pin, and claim refs—never values, descriptions, evidence spans, page bodies,
or source URLs.

`AgentPrivacyService` now follows a bounded propagation closure from those indexed roots through
the originating and subsequent same-thread turns plus delegated descendants. It tombstones the
potentially data-bearing turn/model/plan/tool/delegation/finalization artifacts, deletes the bounded
stream partition and every LangGraph checkpoint namespace under the turn's unique execution id,
and purges the isolated workspace. Shared immutable resource manifests and budget envelopes are deliberately not
tombstoned. Body-free operation, model-cost, context, finalization, event, hash, and identity rows
remain auditable; their referenced bodies are absent and cold replay fails closed. Existing
content-addressed tombstones reject any attempt to persist the erased bytes again.

The immutable Head-of-ABM `v26` / Stage-0 skill `v13` cutover adds the explicit rule that claim
values, previews, labels, descriptions, evidence, source/provider lineage, URLs, and page text are
untrusted evidence and can never select tools, widen authority, author trusted arguments, delegate,
or override gates. `tests/api/test_client_knowledge_privacy_s4e.py` covers binding, stream
redaction, frozen schema markers, injection instructions, and immutable resource selection.
`tests/api/test_client_knowledge_privacy_s4e_db.py` runs against a fresh named PostgreSQL database
and proves the complete exact-copy reach, historic-stream cleanup, checkpoint deletion, retained
body-free receipts, idempotent DSAR, blocked replay, no resurrection, and preservation of shared
resource/budget artifacts. The S4-C replay suites continue to prove stable reference sets with zero
writes and zero provider spend.

### S3.1 — Production composition reliability (after S4-E)

**Deliverables**

- Make per-turn workspace/client/Client-KB-version scope pins durable.
- Add statement-level DSAR bindings for the production Stage-0 path.
- Define retry behavior when background recon publishes vN+1 during a vN turn.
- Cover the real fleet path rather than private helper composition.
- Freeze the company-wide versus product-specific knowledge scoping policy.

**Exit gate**

The real production chain—`AGENT_TURN → durable scope pin → cards → context assembler → governed
S4 tool → model/checkpoint → finalization → replay`—passes with exact original pins, DSAR reach,
and no fixture-only substitutions.

**Implemented evidence:** migration
`d3672ccf43cc_durable_agent_turn_context_scope_pins.py` adds the append-only, workspace-scoped
`agent_turn_scope_pin` retry authority, and `clue_api.agent_turn_scope_pin` atomically creates or
loads it using DB time. The production worker creates the receipt before composition, builds its
scope only from that receipt, supplies the same account-wide version to both L3 cards and trusted
S4 arguments, and reports the pin on privacy-safe replay logs. A legacy committed turn is replayed
without inventing a receipt.

The Stage-0 production persistence seam now binds every embedded quote to its exact statement via
the existing `derived` reverse index. The governed eraser discovers and purges that production
card and its evidence while leaving another project's card readable. The knowledge policy is
frozen as `company-account-wide-v1`: company claims are shared across projects; the confirmed
project product remains separately pinned; product-scoped claims are not admitted until S5.0
defines a new explicit consumption contract.

`tests/api/test_production_context_s31_scope_pin_db.py` proves immutable vN retry, next-turn vN+1,
workspace isolation, and separation from a newer product-specific KB sequence.
`tests/api/test_production_context_s31_fleet_db.py` drives the actual task row and `AGENT_TURN`
handler through real recipes, cards, the seven-layer assembler, `list_client_knowledge@2`, the
Postgres LangGraph saver, finalization, and cold replay; only the external model is deterministic.
It inspects the exact L3 artifact bytes, S4 result artifact, checkpoint rows, finalization commit,
and replay model-call count, then erases a real quoted statement and proves the L3 card/evidence,
propagated turn artifacts, every checkpoint namespace under the turn execution id, and cold replay
are all closed. The production privacy root now recognizes exact `agent_context_ref` artifacts;
the replay reader also handles intentionally empty context layers after erasure without an alias
collision. This path additionally found and fixed a production-only strict-output bug:
the C5 adapter now reuses the toolbelt's canonical JSON-mode result validator, covered by a focused
UUID/tuple wire-shape regression.

### S5.0 — Product-knowledge consumption decision

**Status:** implemented and contract-frozen 2026-08-15. Runtime delivery remains S5.

The binding decision is documented exhaustively in
[`FI-production-deepagent-context-S50-product-knowledge-contract.md`](./FI-production-deepagent-context-S50-product-knowledge-contract.md)
and frozen by `clue_api.product_knowledge_decision` plus
`tests/fixtures/production_context/s50_product_knowledge_decision.json`.

The five decisions are:

1. company facts remain in the account-wide (`product_id IS NULL`) Client-KB;
2. detailed product facts use independently versioned product-scoped knowledge;
3. selected-product consumption uses both `ProductKnowledgeCard@1` and separate governed
   `list_product_knowledge@1` / `inspect_product_claim@1` tools;
4. product scope comes only from the human-confirmed product and exact version in the trusted turn
   pin—never model arguments;
5. S5 introduces additive `ClientKnowledgeCard@2` for a typed, bounded product catalog while V1
   remains immutable for replay.

The target new-turn policy is `company-and-selected-product-v2`. A turn pins the company and
optional selected-product versions in one DB snapshot, reuses the pair on retry, and permits only
a later turn to observe background updates. S5.0 intentionally performs no migration, extraction,
synchronization, runtime card compilation, tool registration, or production cutover.

**Exit evidence:** `tests/api/test_product_knowledge_decision_s50.py` validates the complete
decision fixture and four context states without a DB/provider, proves product tool schemas expose
no scope coordinates, proves the existing company tools and `ClientKnowledgeCard@1` are unchanged,
and assigns every runtime responsibility to S5-A through S5-F.

### S5 — Recon product catalog and human project selection

**Status:** implemented and verified 2026-08-15. Checkpoint-level runtime/test evidence is in the
[S5 child contract §9](./FI-production-deepagent-context-S50-product-knowledge-contract.md#9-s5-implementation-checkpoints-unlocked-by-this-decision).

S5 implements the S5.0 contract in six ordered checkpoints. The child contract §9 owns their full
boundaries: S5-A product/card/tool contracts; S5-B grounded catalog extraction/synchronization and
lineage; S5-C exact product readers/card compilers; S5-D governed product tools; S5-E durable pair
pin and real production composition; S5-F human selection/refresh acceptance.

**Aggregate deliverables**

- Register/extract `client.product_catalog` and product-specific knowledge from the official-site
  corpus without crossing their scopes.
- Add durable claim-to-product lineage and idempotent catalog-to-spine synchronization.
- Ship `ClientKnowledgeCard@2`, `ProductProfileCard@1`, and `ProductKnowledgeCard@1` through the
  real assembler with bounded omissions and DSAR reach.
- Ship separate trusted-scope product list/inspect tools through the production profile, recipe,
  skill, execution, checkpoint, stream, finalization, and replay paths.
- Add the `company-and-selected-product-v2` durable pin pair without rewriting historical V1
  receipts.
- Update Stage-0 guidance so the agent presents catalog options, asks the human, and uses only the
  existing human-only confirmation operation.

**Passing criteria and tests**

- Multi-product fixture produces grounded catalog claims and distinct same-brand product rows.
- Replaying extraction/synchronization creates zero duplicate products/lineage.
- Same-name normalization never merges different explicit products without an alias match.
- Company tools cannot read product claims; product tools cannot read company or another product's
  claims; no model schema contains workspace/client/product/version authority.
- A selected product with no product KB yields an honest profile-only state.
- Background company/product updates cannot change either member of a pinned turn's version pair.
- Project A and B can confirm different products from the same catalog.
- The model cannot directly confirm or repoint a project product.
- Cross-brand/cross-workspace confirmation is refused.

### S6 — Refresh, replay, observability, and production acceptance

**Status:** implementation and full company/product production journey proven 2026-08-15; release
remains blocked by the measured fast-lane latency exception under
`FI-production-deepagent-context-release-closure.md`. The retained evidence is reconciled in
`FI-production-deepagent-context-composition-S6-acceptance.md`. S6 does not introduce another
card, knowledge store, turn runner, or operator-only source of truth.

S6 is delivered through five ordered checkpoints:

#### S6-A — Governed publication and next-turn refresh

- Treat the account-wide and selected-product `client.kb_version` markers as the only publication
  boundary. A claim is not visible to a later production turn merely because its row committed.
- Route interview-authored company fields to the account-wide sequence and the frozen S5 product
  field set to the selected product's independent sequence. Reject product facts when no human
  product selection exists; never infer product scope from model-authored data.
- When `record_interview_answer@1` commits one or more client claims, publish/reuse exactly one
  derived version per affected scope in the same transaction. Keep the existing model-facing tool
  schema immutable; the domain result carries the versions for composition tests and the next
  production turn's durable scope pin is the authoritative consumer.
- Treat the production caller's already-durable `agent_turn_scope_pin` as proof that the active
  version is historically consumed and therefore requires an append-only derived version. Keep
  that assertion at the composition seam instead of importing agent-runtime tables into research.
- Preserve the existing rule that project-state statements change only the addressed project's
  Stage-0 card and do not publish a Client-KB version.

**Checkpoint gate:** company and product claims advance only their intended sequence; replay adds
no marker/claim; a project-state-only answer advances neither sequence; the current turn keeps its
original pair while the next submitted turn pins the new pair.

#### S6-B — Privacy-safe production observability

- Emit one structured observation for every compiled card with card kind, schema version, content
  hash, availability, and bounded omission count.
- Emit context-receipt totals and governed tool outcomes from the real production execution path.
- Metric labels are bounded, low-cardinality kinds/versions/outcomes only. Workspace, project,
  client, product, turn, claim, artifact, or hash identifiers may appear in structured logs where
  operational correlation needs them, but never in metric labels.
- Claim values, briefs, descriptions, evidence spans, raw bodies, source URLs, email addresses,
  credentials, and tokens are forbidden in both logs and metric attributes.

**Checkpoint gate:** in-memory sink tests prove exact counters/gauges; log-capture/static tests prove
required keys and reject sensitive keys/content; replay is recorded as replay rather than a second
successful tool effect.

#### S6-C — Body-free operator context-reference read

- Add an always-registered, authenticated `thread.read` endpoint for the exact persisted context
  receipt. It exposes assembly identity/version/hash, per-layer counts, and included/excluded
  artifact/domain pointers, but has no body-hydration option.
- Keep the dev inspector separate. Its optional body hydration remains structurally absent in
  production, while this operator/read surface is safe to register in every environment.
- Apply the existing workspace/project/thread/turn 404-not-403 scoping rule and return an honest
  `pending` state before a receipt exists.

**Checkpoint gate:** same-workspace reads return the exact receipt refs; foreign workspace/project/
thread/turn reads are indistinguishable 404s; route/schema/static tests prove that body, text,
email, token, credential, claim value, evidence span, and source URL fields cannot appear.

#### S6-D — Production-chain adversarial acceptance

- Drive `AGENT_TURN -> durable pair pin -> four-card L3 composition -> context receipt -> governed
  company/product tools -> checkpoint/tool-result/finalization -> cold replay` with only the model
  and external providers substituted.
- Cover account-wide refresh, product refresh, project-state-only refresh, Project A/B isolation,
  workspace isolation, DSAR, replay, crash before/after card persistence, timeout, and concurrent
  first-turn pinning.
- Assert database rows, artifact hashes, tool receipts, context refs, and metric/log observations,
  not only returned Python objects.

**Checkpoint gate:** every old turn remains byte/hash/pin stable, every eligible next turn observes
the published version, and no crash/replay path creates duplicate claims, markers, provider spend,
or finalization.

#### S6-E — Fresh live production acceptance

- Upgrade a fresh named PostgreSQL database, use a separate retained artifact/log root, and run the
  real API, fleet, frontend, auth/provisioning, onboarding recon, project turn, governed knowledge
  inspection, background refresh, and replay path.
- Use real Firecrawl or Scrapling acquisition according to the configured production provider; a
  provider/environment refusal is reported as typed evidence and never replaced with fixture data.
- Correlate browser/API/server logs, turn/scope/context/tool/finalization rows, claim/version rows,
  artifact hashes, and provider receipts by their durable identifiers.

**Checkpoint gate:** the complete acceptance list below passes, or every unmet item is reported as
an explicit evidence-backed exception. The database and artifact/log roots remain retained until
review sign-off.

**Deliverables**

- Compose recon and interview KB-version publication with next-turn card refresh.
- Add privacy-safe logs/metrics for card kind/version/hash, context availability, omitted counts,
  and tool outcomes—never claim values, raw bodies, email, or tokens.
- Add an operator/read test surface for exact context refs without bodies.
- Execute the full production-path acceptance on a fresh isolated PostgreSQL database and artifact
  root.

**Passing criteria and tests**

- Browser/onboarding or equivalent real production route produces a fast Client-KB commit.
- A production project turn receives real brand, shared Client-KB, and its own Stage-0 state.
- The Head-of-ABM follows an interpretable ref through the real toolbelt to exact provenance.
- Background recon advances the next turn without changing the prior context receipt.
- Interview update affects only the active project's Stage-0 state and the account-wide KB version
  when it writes a governed client claim.
- Project A/B isolation, workspace isolation, DSAR, replay, crash-before/after-card-persistence,
  timeout, and concurrent-turn tests pass.
- Backend unit/DB/static/type/import gates and frontend contract tests pass with zero unexplained
  failures.

## 8. Global adversarial matrix

Every slice contributes fixtures to this matrix:

- workspace A attempts to load workspace B's client/card/claim/product;
- Project B is deliberately given Stage0(A)'s artifact ref;
- Client-KB version changes between scope resolution and card persistence;
- a card references a same-version non-member, a later-version-superseded historical member, or a
  retention-expired claim;
- a field-registry description contains prompt-like instructions;
- an evidence artifact is erased after statement read;
- background recon commits while two turns start concurrently;
- a product catalog repeats aliases, Unicode/case variants, or malicious strings;
- a provider/recon replay re-emits the same catalog claim;
- a worker crashes after persisting one of three context artifacts;
- a committed turn is replayed after the current Client-KB has advanced;
- no Client-KB, empty Client-KB, partial Client-KB, and over-cap Client-KB remain distinct.

## 9. Rollout and compatibility

- Default production conversation composition moves atomically to the new bundle; no flag may
  expose a half-composed state to the model.
- The legacy combined `Stage0ProjectCard` may remain only as a short-lived trial compatibility
  adapter and must be labelled deprecated. New production code and tests may not import it.
- Old frontend clients are unaffected: this is agent-internal context plus additive operator truth.
- Existing context receipts remain immutable and replayable with their historical media types.
- DSAR reaches every new artifact and claim-to-product lineage row before rollout.

The implementation order is fixed:

```text
S4-A readers
→ S4-B contract freeze
→ S4-C trusted @2 tools
→ S4-D production registration
→ S4-E privacy/security/replay
→ S3.1 production composition reliability
→ S5.0 product-knowledge decision (complete)
→ S5-A product/card/tool contracts (complete)
→ S5-B catalog extraction/synchronization + lineage (complete)
→ S5-C product readers/cards (complete)
→ S5-D governed product tools (complete)
→ S5-E durable pair pin + production composition (complete)
→ S5-F human selection + refresh acceptance (complete)
→ S6 production composition (implemented and full product path live-proven; latency release gate open)
```

## 10. Definition of done

This roadmap is complete only when a production-composed Head-of-ABM turn can, without fixture
assistance:

1. inherit the onboarding client's account-wide Client-KB in a newly created project;
2. receive real brand identity and honest brand-profile availability;
3. receive only that project's Stage-0 interview/readiness state;
4. understand which reference answers a product, positioning, competitor, buyer, proof, pricing,
   or customer question;
5. dereference the selected claim through the governed production toolbelt;
6. ask for and record a human-confirmed project product from the recon-derived catalog; and
7. replay with the exact original context and zero duplicate work or spend.
