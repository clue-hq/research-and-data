# Phase C4 — Governed Stage 0 and Recipe #0 implementation plan

**Date:** 2026-07-24
**Branch:** `platform/workspace-restructure`
**Authority:** `PC-C0-step4-contract-freeze.md`, `PC-C4-stage0-recipe0.md`, harness REQ-08,
Doc A, Doc B, and Doc M.

## 1. Product outcome and boundary

C4 turns the existing Stage-0 research substrate into a durable product workload:

```text
workspace onboarding
  durable input → fast official-surface recon → background client/product recon

project kickoff
  durable verbatim interview/upload → governed routing → readiness → ICP confirmation

post-confirmation
  immutable KB → ICP → product-context pins → project run starts at DISCOVERY
```

Recipe #0 is a deterministic, resumable composition over tools. It is not an agent loop. C6 may
later decide which C4 tool to call and what to ask, but C4 owns the safety floors, authority checks,
lineage validation, and durable state transitions.

## 2. One-way-door invariants

1. **One truth per species.** Facts are claims, preferences/learnings use `MemoryWriteSeam`,
   project instructions remain project-scoped durable statements, and raw bodies remain artifacts.
2. **Product truth is born scoped.** A product-level `client.*` claim carries immutable
   `product_id` at insert. It is never fixed up later.
3. **No cross-tenant product reference.** `claim(product_id, workspace_id)` has a composite FK to
   `product(product_id, workspace_id)`.
4. **Confirmed lineage is provable.** A C4-confirmed ICP stores
   `(client_entity_id, client_kb_version, product_id)`.
5. **Execution cannot drift.** `start_confirmed_project_run` verifies the project, ICP lineage,
   product-context manifest, and effective discovery-readiness decision before creating a run at
   `ProjectPhase.DISCOVERY`.
6. **Fast is not background.** Recon stores independent fast/background lifecycle fields. Fast
   completion never marks background complete.
7. **Progress is evidence-backed.** Stage-0 progress is derived from durable recon/input/statement/
   readiness/ingestion state and durable events, never synthetic checklist ticks.
8. **Human authority is explicit.** Only `actor="human"` may confirm a project product or create a
   readiness override. Agent output may propose, never silently mutate those decisions.
9. **Open input is lossless.** Every interview statement either returns a routed reference or is
   preserved as a `volunteered_statement`.
10. **Paid calls are gated first.** Both remaining Stage-0 waterfall callers construct a
    `PreSpendRequest` before each resolver provider call.

## 3. Shared contract changes

### 3.1 `clue_core`

Add the C0-frozen IDs, enums, and reference models in a dedicated `stage0.py` module:

- `OnboardingInputId`, `ReconRunId`, `VolunteeredStatementId`;
- `ProductContextVersionId`, `ReadinessDecisionId`, `ReadinessOverrideId`;
- `OnboardingInputKind`, `ReadinessGate`, `ReadinessVerdict`;
- `OnboardingInputRef`, `ProductContextRef`, `ReadinessSnapshotRef`.

Extend:

- `Claim.product_id: str | None`;
- `ICPSpec.client_entity_id: EntityId | None`;
- `ICPSpec.client_kb_version: int | None`;
- `ICPSpec.product_id: str | None`.

`Claim` validates that a non-null product is tenant-private and has `workspace_id`.

### 3.2 `clue_config`

Add `stage0.py` with the frozen `ReadinessFloor`, `ReadinessSpec`, and `Stage0Policy`. Defaults:

- fast recon: cents-scale, official surfaces only;
- background recon: bounded tier 1–3;
- ICP synthesis: URL-only compatible, product required once project-scoped;
- discovery: product + confirmed ICP + sufficient non-policy-blocked coverage;
- deep: stricter verified coverage and no open policy blocks.

Tool inputs cannot raise these ceilings.

## 4. Migration and durable model

Create one random-hash Alembic revision from the current single head.

### 4.1 Additive lineage

- `claim.product_id`, composite same-workspace FK, index, immutable-trigger coverage;
- `icp_spec.client_entity_id`, `client_kb_version`, `product_id`, immutable-trigger coverage;
- `project_run.client_entity_id`, `client_kb_version`, `product_id`,
  `product_context_version_id`, `readiness_decision_id`.

Legacy rows remain nullable. New C4 harness writes populate the relevant fields.

### 4.2 New C4 tables

- `onboarding_input`: append-only artifact-backed input metadata and Stage-0 coordinates;
- `recon_run`: mutable execution cursor with separate fast/background status, budgets, costs,
  research-run refs, input refs, KB result, recipe/skill versions, and timestamps;
- `volunteered_statement`: append-only exact-quote coordinates, routing kind/ref, correction links,
  and actor/context;
- `product_context_version`: immutable reference manifest with claim/memory/artifact refs,
  freshness snapshot, compiler version, and KB/product coordinates;
- `readiness_spec_revision`: immutable versioned readiness policy;
- `readiness_decision`: append-only pinned evaluation across one gate;
- `readiness_override`: append-only human override of one blocked decision.

Foreign keys and composite context checks make cross-workspace/brand/product/project references
unrepresentable where the spine exposes an anchor. Append-only triggers protect evidence and
decision history; only recon lifecycle fields are mutable.

## 5. Claim and ICP plumbing

1. Extend claim SQL insert/select/row reconstruction and tombstone copying with `product_id`.
2. Add product-aware claim reads without changing legacy unfiltered reads.
3. Thread `product_id` through waterfall idempotency so one product never reuses another product's
   client claim.
4. Extend Stage-0 claim construction:
   - reverse-profile/material claims receive the selected product;
   - C3 `CLIENT_ABOUT_PRODUCT` claims receive `job.product_id`;
   - target account/contact claims stay null.
5. Extend ICP repository create/read/diff-idempotency and `confirm_icp` lineage arguments.
6. Require all three lineage values from the C4 confirmation path while keeping legacy callers
   source-compatible.

## 6. Remaining pre-spend closure

Add optional injected `PreSpendGate` to:

- `reverse_profile`;
- `import_accounts` → `_crm_enrich`;
- their handlers/tools/composition constructors.

Each field builds a per-source `SourceGate` that submits:

```text
entity id/type + field key + manifest tier + run id
```

and allows only non-`REJECT` decisions. Remove both C4 exceptions from the static spend inventory
and add temporal tests where the fake provider asserts the decision already exists.

## 7. Stage-0 services

### 7.1 Onboarding input service

- accept either already-captured `artifact_key` or raw body;
- content-address raw body under the caller workspace;
- validate artifact and every supplied spine coordinate;
- store actor, kind, hash, and references;
- return `OnboardingInputRef`, never body content.

### 7.2 Recon service

`start_recon`:

- validates the onboarding input and scope;
- derives a stable context/input dedupe hash;
- under a transaction-scoped advisory lock, reuses a live equivalent recon or creates one;
- allocates independent fast/background child envelope IDs and research run IDs;
- records recipe and Stage-0 skill versions.

Execution is deliberately split:

- fast execution uses the strict fast budget and rejects source tiers above official tier 2;
- background execution has its own budget and runs the full tier 1–3 client pack;
- each transition is persisted before a corresponding event is emitted;
- replay of a completed child is a no-op.

Fast and background use separate claim runs/KB versions so a supposedly pinned Client-KB version
never mutates after publication. The small duplicated official-surface spend is bounded by the fast
envelope and is preferable to mutable version semantics.

### 7.3 Interview service

The C4 minimal actor supplies explicit typed classifications; C4 validates and routes them. This
keeps intelligence replaceable and avoids a scripted fake deepagent.

For every classified statement:

- `quote` must be an exact substring of the stored verbatim input;
- mapped string claims must be entailed by that quote (strict normalized containment);
- self/product facts are tier 1; target assertions are capped at tier 3;
- corrections append a new claim and supersede the referenced prior claim;
- preferences call `MemoryWriteSeam` with `USER_STATED` provenance;
- project intent is preserved as a project-scoped routed statement;
- unknown but valid field/source shapes call C2 proposal services;
- everything else is preserved as an unmapped statement.

Idempotency is enforced on `(entity, field-or-statement route key, onboarding_input_id)`.

### 7.4 Product context compiler

Compile an immutable manifest after product confirmation and client-KB availability:

- validate every claim ref belongs to the workspace and either the selected product or the allowed
  product-neutral client scope;
- validate memory/artifact refs are scoped to the same product/workspace;
- record claim, memory, artifact, KB, freshness, compiler, and recipe refs;
- hash the canonical manifest for idempotent reuse.

### 7.5 Readiness evaluator

Load/version the configured readiness spec, then compose only public C1–C3 projections:

- C1 research gaps/coverage;
- unresolved C2 field/source proposals;
- pending/failed C3 ingestion jobs.

Compute deterministic metrics and display-safe reason codes for each gate. Record the future
agent-sufficiency slot as `not_evaluated` unless the injected minimal fixture supplies a result.
An override changes effective readiness only through a linked human-authored row; it never mutates
the original decision.

## 8. Recipe #0 and Stage-0 skill

Add:

- frozen `RecipeStep`;
- narrow `RecipeRunner` protocol;
- deterministic runner over the existing `ToolRegistry`/`invoke_tool`;
- a versioned flat Stage-0 skill directory containing metadata, tool allowlist, readiness policy,
  and interview guidance.

Recipe state is limited to recon cursor/version refs. No general recipe journal, graph executor,
agent class, subagent, or planning loop lands in C4.

## 9. Tool and projection integration

Add a lane-specific `clue_api.stage0_tools` module and register:

- `submit_onboarding_input`;
- `start_recon`;
- `record_interview_answer`;
- `confirm_project_product`;
- `evaluate_stage0_readiness`;
- `override_stage0_readiness`;
- `start_confirmed_project_run`.

Add `clue_projections.stage0`:

- `recon_brief`;
- `stage0_readiness`;
- `stage0_progress`.

The API router exposes the three workspace-scoped reads. Absent and foreign IDs return the same
shape. C4 projection composition calls C1–C3 projection functions, never their tables.

## 10. Run-entry correction

`start_confirmed_project_run` performs one transaction:

1. load project in caller workspace and require exact brand/product;
2. load the requested ICP version and require exact client/KB/product lineage;
3. load immutable product context and require the same coordinates;
4. load the requested discovery-readiness decision and resolve any human override;
5. create a `project_run` at `DISCOVERY` with all C4 pins;
6. return reference-only pins.

The legacy `start_project_run@1` and full fixed-phase Recipe #1 remain unchanged.

## 11. Verification plan

### Unit/contract

- C4 config validation and enum/reference round trips;
- artifact-backed input and scope checks;
- claim/ICP product lineage validation;
- quote entailment and correction semantics;
- readiness floor/override logic;
- Recipe step replay and skill metadata/allowlist.

### DB-backed

- migration up/down/up and exactly one Alembic head;
- append-only trigger coverage;
- same-workspace composite FKs;
- recon dedupe/isolation/lifecycle;
- product-context manifest isolation;
- readiness pins and human-only overrides;
- confirmed run starts at `DISCOVERY` with exact pins.

### Integration

- real scrape resolver registration + snapshot binding;
- pre-spend decision temporally precedes both Stage-0 provider paths;
- fast completion while background remains non-terminal;
- C1 gaps, C2 proposals, and C3 jobs appear through projections;
- memory/project/unmapped interview routing;
- URL-only and known-product Recipe-#0 journeys;
- all ten C0 shared journeys;
- static guard proves no fake agent class and no ungated waterfall caller.

### Repository gates

Run focused tests continuously, then:

```text
ruff
mypy
import-linter
pytest (DB-enabled)
alembic heads
make db-smoke on a clean throwaway database
make check
```

## 12. Implementation checkpoints

1. contracts/config + migration + repository models;
2. product-aware claim/ICP/run plumbing and pre-spend closure;
3. onboarding/recon/interview/product-context/readiness engines;
4. Stage-0 tools, projections, Recipe #0, and skill;
5. C1–C3 composition and full shared journeys;
6. docs/memory synchronization and final green verification.
