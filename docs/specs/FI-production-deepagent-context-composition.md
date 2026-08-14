# Production Deepagent Context Composition

**Status:** RATIFIED for implementation on `platform/onboarding-integration`  
**Date:** 2026-08-14  
**Owners:** frontend/backend integration + platform agent runtime  
**Authority:** contract delta to Doc A Part III and PC-C8 for this production composition. Where
this document conflicts with the provisional note in root `CLAUDE.md`, this document wins.

**Implementation checkpoint (2026-08-14):** S0-S4 are implemented. S4-A's version-aware reader,
S4-B's immutable contract freeze, S4-C's trusted `@2` implementations, S4-D's production
composition, and S4-E's privacy/injection/replay hardening all pass their gates. The previously
shipped `@1` tools and Head-of-ABM `v24` / Stage-0 skill `v11` / Recipe #0 `v7` graph remain frozen
historical replay resources; S4-D's profile `v25` / skill `v12` also remain immutable. Current
production selects `@2`, profile `v26`, skill `v13`, and Recipe #0 `v8`. S3.1, S5.0, S5, and S6
remain outside this checkpoint.

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

L3 project
├── ProjectConversationCard             active project/thread envelope, always present
├── ClientKnowledgeCard                 customer-account-scoped, conditional on Client-KB
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

The worker resolves `client_entity_id` and current `client_kb_version` once. The envelope,
constitution, Client-KB card, Stage-0 card, and admitted tools for that turn all use that exact pin.

If background recon publishes vN+1 while a vN turn is running, the running turn stays on vN. The
next turn receives vN+1. Partial version mixing is forbidden.

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

### D7 — Human-confirmed product choice is project-specific

Recon may discover multiple customer products. Those candidates are account/brand catalog data,
not a project decision. The agent may describe the catalog and ask which product this project is
about. Only the human-authorized `confirm_project_product` operation writes `project.product_id`.

The same catalog can be offered in Projects A and B; the confirmed product can differ.

### D8 — Production entrypoints are part of every slice

A slice is incomplete until its capability is composed through the real worker, assembler,
toolbelt/profile/recipe, durable artifacts/database, and replay path where applicable. Trial-only
or fixture-only success is not an exit.

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

### 5.2 Card persistence

Cards are content-addressed immutable artifacts with privacy/DSAR subject bindings:

- Client-KB card: client subject binding, no project binding required for identity;
- Stage-0 card: client subject binding plus exactly one project binding;
- conversation envelope: active project binding and client binding when available.

Identical Client-KB versions across projects persist/reuse one blob while each turn retains its
own context receipt.

### 5.3 Refresh

- Fast recon commit creates/updates the current Client-KB version; the next turn compiles that pin.
- Background recon does the same without mutating an already assembled turn.
- Interview-derived Client-KB claims publish a new version before a later turn can reference them.
- A Stage-0 project-state change recompiles only that project's artifact.
- Replay of a committed turn reuses its original context receipt and performs zero recon/model/tool
  work.

## 6. Product catalog

Add `client.product_catalog` as a registered tenant-private Client-KB field shaped as a bounded
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

The Client-KB card describes available products with product refs. The Stage-0 agent proposes from
those refs. Existing human-only `confirm_project_product` remains the sole project-binding write.

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
stream partition and exact `agent-turn:<turn_id>` LangGraph checkpoint namespace, and purges the
isolated workspace. Shared immutable resource manifests and budget envelopes are deliberately not
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

### S5.0 — Product-knowledge consumption decision

Before catalog synchronization begins, ratify that company facts belong to the account-wide
Client-KB and product facts belong to product-scoped knowledge. Decide whether selected-product
context uses a `ProductKnowledgeCard`, product-filtered S4 tools, or both, and whether the S5
catalog requires `ClientKnowledgeCard@2`. No S5 schema or synchronization code proceeds while one
of these decisions can still change how the agent consumes product knowledge.

### S5 — Recon product catalog and human project selection

**Deliverables**

- Register and extract `client.product_catalog` from the official-site corpus.
- Add durable claim-to-product lineage and idempotent catalog-to-spine synchronization.
- Include bounded catalog descriptors/product refs in Client-KB context.
- Update Stage-0 guidance so the agent asks the human to select a product and then uses the
  existing human-only confirmation operation.

**Passing criteria and tests**

- Multi-product fixture produces grounded catalog claims and distinct same-brand product rows.
- Replaying extraction/synchronization creates zero duplicate products/lineage.
- Same-name normalization never merges different explicit products without an alias match.
- Project A and B can confirm different products from the same catalog.
- The model cannot directly confirm or repoint a project product.
- Cross-brand/cross-workspace confirmation is refused.

### S6 — Refresh, replay, observability, and production acceptance

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
→ S5.0 product-knowledge decision
→ S5 catalog and selection
→ S6 browser/live acceptance
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
