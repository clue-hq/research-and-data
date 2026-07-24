# Phase C4 — Governed Stage 0 and Recipe #0

**Status:** ready for parallel substrate implementation; integrates after C1–C3

**Parent:** [`PC-phase-c-agentic-layer.md`](./PC-phase-c-agentic-layer.md)

**Shared contracts:** [`PC-C0-step4-contract-freeze.md`](./PC-C0-step4-contract-freeze.md)

**Requirement:** harness REQ-08

---

## 1. Outcome

C4 builds the governed Stage-0 workload the future platform deepagent will operate.

Stage 0 is not one state-machine phase. It is the product boundary spanning:

```text
workspace onboarding
  name + URL → fast recon → background client/product understanding

project kickoff
  project chat → intent + gap-driven interview/uploads → readiness → ICP co-confirmation
```

C4 proves that workload through Recipe #0 and a minimal test actor. It does not pretend the final
Head-of-ABM deepagent exists; C6 supplies that mind.

---

## 2. Binding behavior

### 2.1 Three research speeds

1. **Fast recon:** owned site and obvious official surfaces; strict cents-scale envelope; emits a
   useful brief quickly.
2. **Background recon:** broader tier 1–3 client/product research; continues while the user chats
   and streams real events.
3. **Project-directed research:** open-ended/deeper work only after product/motion direction and
   readiness permit it.

Within a workspace, matching onboarding identity/context dedupes. Accounts and all research remain
workspace-local; there is no cross-tenant recon reuse.

### 2.2 Dual-layer readiness

- deterministic readiness specs enforce non-negotiable coverage/confidence/policy floors;
- the future deepagent makes open-ended sufficiency judgments for the particular motion;
- C4 reserves and records that agent-sufficiency slot but uses a minimal actor/fixture;
- a human can record “just go”; an agent cannot self-override.

Readiness is evaluated separately for ICP synthesis, discovery spend, and deep spend.

### 2.3 Open understanding

The interview is gap-driven, not a fixed walk through registered Client-KB fields.

```text
mapped fact              → claim
preference/learning      → scoped memory
project intent           → project state
unmapped statement       → volunteered_statement
new fact shape           → C2 field proposal
new credible source      → C2 source proposal
raw upload/turn/page     → artifact-backed evidence
```

Nothing important is dropped because the registry lacked a field.

---

## 3. Durable model

Implement the C0-owned C4 tables:

- `onboarding_input`;
- `recon_run`;
- `volunteered_statement`;
- `product_context_version`;
- `readiness_spec_revision`;
- `readiness_decision`;
- `readiness_override`;
- additive `project_run` pins.

C4 also owns the additive immutable `Claim.product_id` dimension, its same-workspace FK and
claim-store read/write/idempotency plumbing. Product-scoped `client.*` facts must carry it at
birth. Product-neutral target-account/contact facts leave it null. The product-context manifest
is a reproducible index over scoped truth; it is not an alternate way to scope otherwise
ambiguous claims.

C4 also adds nullable immutable lineage to `ICPSpec`/`icp_spec`:
`client_entity_id`, `client_kb_version`, and `product_id`. Legacy/manual specs may remain null;
every C4 harness confirmation must stamp the three values so run entry can prove the confirmed ICP
came from the pinned KB/product.

### 3.1 Onboarding input

Every website submission, user turn, pasted body, upload reference, or CRM reference is durable,
artifact-backed, actor-attributed, and brand/product/project scoped. The current transient
`ClientInput` is constructed from these durable refs when invoking existing capabilities.

### 3.2 Recon run

One logical recon has fast/background child envelopes and stores:

- dedupe identity/hash;
- workspace/brand/product/project coordinates;
- source/input refs;
- status/cost/budget;
- Client-KB result ref;
- event cursor/outbox refs;
- Recipe-#0 compatibility/version.

Fast completion does not imply background completion.

### 3.3 Product context version

A product context is an immutable manifest of references:

```text
product identity
Client-KB version
relevant product/client claim refs
memory bundle/version ref
artifact/asset refs
freshness snapshot
compiled-at timestamp and compiler version
```

It is reproducible because a project run pins the manifest id. The manifest is not a prose truth
store.

Two products under one brand must therefore be isolated at both layers: claim reads filter on
`product_id`, and the manifest may reference only claims/memories/assets belonging to its product.

### 3.4 Readiness decision

Each decision pins:

- readiness spec version;
- workspace/brand/product/project;
- Client-KB version;
- ICP key/version when available;
- product-context version;
- C1 gap refs;
- C2 proposal refs that remain unresolved;
- C3 ingestion refs still pending;
- deterministic metrics and display-safe reasons;
- future agent-sufficiency result/ref;
- override ref when present.

---

## 4. Interview as a source

Register `client_interview` as a conversation-modality source.

An answer:

1. snapshots the verbatim user turn;
2. records `onboarding_input`;
3. extracts/classifies statements;
4. writes mapped facts as claims whose evidence span points to the exact quote;
5. writes preferences through Doc M's `MemoryWritePort`;
6. writes project intent to project state;
7. preserves anything unmapped;
8. triggers readiness and, where relevant, ICP re-synthesis.

Idempotency is `(entity, field-or-statement, onboarding_input_id)`.

Corrections append a new turn and supersede the prior claim. The original evidence remains in
history. Unsupported paraphrases fail the faithfulness check.

Authority:

- the client is tier 1 for claims about itself/its product;
- client statements about target accounts remain capped at tier 3;
- personal facts still require identity/use governance;
- hypotheses are tagged `client_stated`/`agent_proposed`, not promoted as world facts.

---

## 5. Recipe #0

Recipe #0 composes existing and new capabilities through the toolbelt:

```text
submit_onboarding_input
  → start_recon
      → reverse_profile / live scrape composition
      → C1 coverage refs
      → recon_brief + progress
  ↔ record_interview_answer
      → C2 proposals when unmapped
      → C3 ingestion for uploads
      → claims / memory / project state
  → confirm_project_product
  → evaluate_stage0_readiness
  → synthesize_icps
  → confirm_icp
  → pin product context
  → start harness execution post-confirmation
```

The C4 runner implements a narrow `RecipeExecutor`-shaped protocol:

```python
class RecipeStep(BaseModel):
    tool_name: str
    input_refs: dict[str, JsonValue]
    depends_on: tuple[str, ...] = ()

class RecipeRunner(Protocol):
    async def run_step(...) -> ToolResult: ...
```

It may persist minimal recon cursor state, but must not invent the general run-graph journal. C5
replaces/generalizes this seam without rewriting Recipe #0.

### 5.1 Live resolver composition

C4 wires the existing scrape resolver at the API composition root behind settings and storage
snapshot binding. Tests must prove the real binding is present; a no-resolver fixture is not the
Recipe-#0 acceptance path.

C4 also threads the API-root `PreSpendGate` through the two audited Stage-0 waterfall callers that
remain ungated at C0 (`reverse_profile` and import CRM enrichment). Recipe #0 and the known-account
path cannot be considered live until provider-call probes prove the gate decision existed first.

---

## 6. Run-entry correction

The current `start_project_run` requires an already-confirmed ICP but creates the old machine at
`REVERSE_PROFILING`. That can generate a newer Client-KB than the one from which the pinned ICP was
derived.

C4 resolves this by adding a harness entry surface:

- validate project/workspace/brand/product;
- validate the exact Client-KB and ICP relationship;
- pin product context and readiness decision;
- create the run at `ProjectPhase.DISCOVERY`, the first post-confirmation execution phase;
- never invoke reverse profiling or ICP confirmation implicitly.

The legacy full fixed-phase path remains available as Recipe #1 until C5 formalizes it. Existing
callers are not silently reinterpreted.

The frozen explicit tool name is `start_confirmed_project_run`; do not overload
`start_project_run@1`. Its entry phase is `ProjectPhase.DISCOVERY`.

---

## 7. Minimal skill loader

C4 adds only what Recipe #0 needs:

- flat skills parent directory;
- versioned Stage-0 interview skill;
- progressive disclosure metadata;
- tool allowlist;
- readiness/interview policy guidance;
- pinned skill version in recon/Recipe refs.

It does not add a fake agent loop. The minimal test actor follows the skill deterministically so
the workload can be proven before C6.

---

## 8. Tools and projections

Implement the C0-frozen tools:

- `submit_onboarding_input`;
- `start_recon`;
- `record_interview_answer`;
- `confirm_project_product`;
- `evaluate_stage0_readiness`;
- `override_stage0_readiness`.
- `start_confirmed_project_run`.

Implement:

- `recon_brief`;
- `stage0_readiness`;
- `stage0_progress`.

C4 reads C1–C3 only through frozen protocols/projections. Its worktree tests use fakes until
integration.

---

## 9. Owned and forbidden surfaces

### Owns

- new Stage-0 recon/interview/readiness modules;
- C4 migrations and project-run pins;
- additive product scoping on the shared claim contract/store;
- additive Client-KB/product lineage on the shared ICP contract/store;
- lane-specific Stage-0 API tools and projections;
- Recipe-#0 seam/minimal runner;
- minimal skill loader + Stage-0 skill;
- C4 tests.

### Must not edit/finalize

- C1 coverage tables/controller;
- C2 proposal tables/policy;
- C3 ingestion tables/adapters;
- central tool/projection aggregation;
- general run-graph journal/executor (C5);
- platform deepagent/subagents (C6).

---

## 10. Verification

Required tests:

1. URL-only fast brief within hard envelope;
2. background recon continues after fast completion;
3. same identity dedupes within workspace but not across workspaces;
4. live scrape resolver is composed and snapshots evidence;
5. reverse-profile/import paid resolution records a gate decision before the provider call;
6. progress events correspond 1:1 with durable backend transitions;
7. gap agenda uses C1 refs and does not enumerate a fixed field questionnaire;
8. verbatim answer → entailed claim;
9. unsupported paraphrase rejects;
10. correction supersedes and re-synthesizes;
11. preferences reach memory, project intent reaches project state, unmapped text is preserved;
12. C2 proposal and C3 ingestion refs appear in readiness/progress;
13. known product enters confirm/refresh mode;
14. recon may propose a product but only a human confirmation updates `project.product_id`;
15. each readiness floor blocks/allows at the exact boundary;
16. only a human can record “just go”;
17. cross-workspace access fails closed;
18. post-confirmation run pins matching Client-KB/ICP/product context and skips old profiling;
19. Recipe #0 replays without duplicate spend/writes;
20. no fake deepagent class or scripted “agent” is introduced.

After C1–C3 merge, run the shared ten C0 journeys as the Step-4 integration exit gate.

---

## 11. Exit gate

C4 is complete only after integration: a URL-only client receives real two-speed recon; the
project kickoff can ask from live gaps, preserve open-ended input, accept uploads/proposals,
evaluate/override readiness, confirm an ICP, and start execution with coherent pinned context—
entirely through the toolbelt, without pretending C6's deepagent already exists.
