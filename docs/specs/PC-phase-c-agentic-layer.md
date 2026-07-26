# Phase C — governed agency: Step 4 through Step 7

**Status:** ACTIVE — C0–C6 implemented; C7 is the next engineering session
(2026-07-26)

**Integration branch:** `platform/workspace-restructure`

**Authority:** [harness architecture](../architecture/clue-hq-harness-architecture-and-requirements.md)
§8–§9 (especially REQ-03/04/06/08),
[Doc A](../architecture/clue-hq-platform-agent-runtime.md) (binding agent/tool/skill/fleet
vocabulary), [Doc M](../architecture/clue-hq-scoped-memory-and-context-assembly.md)
(claims-versus-memory species split), the [Phase-B execution treaty](./PB-phase-b-platform-infra-core.md),
and the founder's Stage-0 clarification recorded 2026-07-23/24.

**Depends on:** Phase A complete; Phase B complete; `[B3×research]` workspace-localization and
the multi-brand/project-run context amendments complete.

This is the parent execution plan for Phase C. It records the product behavior, dependency order,
parallel-worktree boundaries, integration sequence, and exit gates. Each implementation lane must
write its own child spec before code. A child spec may refine file placement and types; it may not
weaken the decisions or authority boundaries fixed here.

---

## 1. Outcome

Phase C turns the completed substrate into a governed agentic system:

1. research attempts and terminal gaps become durable, explainable state;
2. the system can discover new fact shapes and sources without letting an LLM mutate policy;
3. client uploads become claims with stored evidence;
4. Stage 0 becomes eager recon plus a conversational, readiness-governed project kickoff;
5. every tool action becomes reproducible through a run-graph journal and pinned recipes;
6. the platform deepagent becomes a real deepagent over the toolbelt, not a renamed pipeline;
7. dossiers become regenerable, fully-provenanced views over claims and derivations.

The core constraint remains: **agency chooses what to try; engines and humans retain authority over
spend, trust, promotion, compliance, fan-out, and durable truth.**

---

## 2. Current baseline (what Phase C may assume)

As of the C4 completion checkpoint on `platform/workspace-restructure`:

- Phase A is complete: uv workspace structure, `workspace_id` vocabulary, object spine, shared
  libraries, platform/subsystem boundaries, and API composition root.
- Phase B is complete:
  - detached project-run fleet and lease/task machinery;
  - storage backend, artifact table, source snapshots, DSAR reach, and millicredit groundwork;
  - scoped-memory slice 1 and both enforced memory seams;
  - 24-tool typed toolbelt, loud preconditions, workspace-scoped A9 idempotency;
  - projection API, run manifest, run-event outbox, and treaty SSE;
  - per-run `ComposingRunDriver` capable of driving the existing fixed project-run state machine.
- Account/contact ownership is mandatory and workspace-local. Identity resolution, strong-key
  uniqueness, merges, artifact caches, and account/contact tool access are workspace-scoped.
- A workspace may own multiple brands. Target accounts are brand-neutral.
- Every project run requires a same-workspace project and durably pins its selected brand.
- The claim store, waterfall, verification, compliance, ICP compiler, discovery/scoring,
  deep-research workers, value narrative, review surfaces, and observability substrate exist.
- Governed Stage 0 is implemented: artifact-backed onboarding/interview input, independent
  fast/background recon, product-aware Client-KB/ICP lineage, product-context manifests,
  deterministic readiness plus human override, Stage-0 tools/projections/SSE, and the narrow
  Recipe-#0 runner C5 will generalize.
- A confirmed Stage-0 run starts at `DISCOVERY` with immutable Client-KB/ICP/product-context/
  readiness pins; the legacy full state-machine entry remains unchanged.
- The legacy scripts 01–06 pipeline remains the Recipe-#1 regression reference.
- Verification at the C1–C3 integration checkpoint: DB-enabled `make check` green; 23 import
  contracts kept; 2328 tests passed / 20 external-service-gated skips; one Alembic head
  `fc1f3d22a167`.

### 2.1 C1–C3 integration checkpoint

The platform now has:

- a durable research-coverage attempt/decision ledger, one-round coverage tool, bounded goal
  evaluator, and coverage/history projections;
- durable field/source proposals, governed decision/promotion tools, proposal projections, and the
  fixed tier-3 generic-web resolver registration seam;
- durable upload jobs and stable segments, supported document adapters, claim/proposal routing,
  authoritative contact binding/use classification before insert, exact-source tombstoning on
  erasure, upload/submit/retry tools, and ingestion projection/upload routes;
- one Alembic head joining the three parallel C1/C2/C3 migration branches;
- a static claim-producing spend-path inventory. The two remaining ungated waterfall callers are
  exactly the C4-owned Stage-0 paths named in C0.

### 2.2 What is still absent

- no generic run-graph journal or recipe executor;
- no durable Recipe-#0 execution beyond C4's narrow in-memory topological seam;
- C5.0 now supplies an exact-version tool registry, typed graph-output descriptors, stable
  operation ids, and a standing Recipe-#0/#1 replay audit; the append-only execution journal and
  execution-lifetime invocation replay are still absent until C5.1;
- no run supervisor, account-quarantine enforcement, or run-local source circuit breaker;
- no platform deepagent, research subagent, or governed per-account worker agent;
- no production `HandoffCommitteeReader`;
- no `compose_dossier` / derivation projection.

Phase C must not describe any item in this list as already built merely because its substrate or a
test fake exists.

---

## 3. Binding product model

### 3.1 Stage 0 is a product boundary, not one state-machine phase

The old M5 sequence is reusable capability exposed through tools. It is not the final product
experience. Stage 0 spans two connected activities:

```text
A. Initial onboarding
   name + URL
   → immediate official-source recon
   → broader client/product recon continues in the background

B. Project kickoff
   project-scoped chat
   → agent reads prior recon and selected product context
   → asks only questions that materially close this motion's gaps
   → ingests uploads, corrections, named accounts, exclusions, and intent
   → readiness judgment + ICP co-confirmation
```

Only after the relevant readiness gate does ABM execution begin:

```text
confirmed ICP + pinned client/product context
   → discovery/import
   → Pass A scoring
   → tier checkpoint
   → bounded deep research
   → verification
   → handoff/dossier
```

There is no fixed order inside Stage 0. Readiness, not a screen sequence, is the gate.

### 3.2 Three research speeds

1. **Immediate fast pass:** owned website and obvious official sources, small abuse-resistant
   envelope, useful results in seconds-to-minutes.
2. **Background broad pass:** case studies, customer surfaces, reputable review/directory sources,
   predominantly tiers 1–3, continuing while the user enters chat.
3. **Project-directed deep pass:** open-ended or expensive work only after the product and ABM
   direction are known.

The system must not spend to “understand everything about the company” before it knows which
product and motion matter.

### 3.3 Dual-layer readiness

- A **deterministic readiness spec** defines non-negotiable evidence/confidence floors before ICP
  synthesis, discovery spend, and deep-research spend.
- The **deepagent** later makes an open-ended sufficiency judgment for the specific motion.
- The user retains a durable **“just go” override** with actor, rationale, timestamp, readiness
  snapshot, and resulting risk/assumption flags.

The deterministic layer cannot claim nuanced judgment; the LLM layer cannot bypass the
deterministic floor or fabricate readiness.

### 3.4 Open-minded discovery, governed promotion

The registries are promotion boundaries, not perception boundaries:

| Observation | Durable route |
|---|---|
| Fits an existing registered fact shape | Typed claim through the claim store |
| New potentially factual shape | `volunteered_statement` + `propose_field` |
| Newly discovered credible source | `propose_source` |
| Preference or behavioral learning | Scoped-memory write seam |
| Project-specific intent/instruction | Project brief/config/state |
| Raw page, file, image, transcript | Artifact/snapshot store |

The agent may investigate and nominate a source. It may not assign that source tier-1/2 authority.
Policy/human promotion remains the trust boundary. No statement is silently dropped merely because
the current field registry did not anticipate it.

### 3.5 Persistence and scope

| Species | Example | Home | Reuse |
|---|---|---|---|
| Brand/product fact | “Enterprise pricing starts at…” | Claim store | Same workspace and relevant brand/product |
| Preference | “Never use fear-based messaging” | Scoped memory | Deterministic scope assembly |
| Behavioral learning | “ROI framing worked for clinical buyers” | Scoped memory | Product/account scopes as applicable |
| Project intent | “Expand existing gastro accounts” | Project state | This project |
| Campaign instruction | “Use direct mail for this channel program” | Project/campaign plan | Declared scope |
| Unclassified user statement | Novel claim not yet mapped | Staging ledger | Preserved until classified |

Facts never become memory. Preferences/learnings never become claims. Project intent never leaks
into cross-project client truth.

### 3.6 Honest agency

- C1's goal judge is a bounded LLM leaf call inside an engine, not an agent.
- C4 builds the governed Stage-0/interview/readiness substrate and its minimal skill-loading seam.
- C6 builds the real platform deepagent: orchestrator, tools, subagents, workspace record, typed
  state, skills, journaling, and honest finalize.
- A scripted questionnaire or hand-written model loop marketed as the Stage-0 deepagent is a
  defect.

---

## 4. Phase-C decisions fixed before implementation

### PC-D1 — onboarding and project kickoff are distinct durable activities

Initial recon is anchored at least to `(workspace_id, brand_id)` and may propose or attach a
`product_id`. Project kickoff is anchored to `project_id` and its pinned brand/product context.
They share client/product truth through claims and memory; they do not share mutable ad-hoc chat
state.

### PC-D2 — onboarding input is durable and brand-aware

The B4 `client_input_provider` is only an adapter seam. C4 must create a durable input record for
name, canonical website, submitted materials, actor, and version/provenance. A workspace-wide
singleton is invalid because a workspace may own multiple brands. Raw material bodies live in
artifact storage; the input record stores references.

The child spec chooses the final table/type name. It must expose a lookup by durable context and
make ambiguous/missing input fail loudly.

### PC-D3 — product context becomes reproducible

Projects already carry optional `product_id`; project runs currently pin project and brand but not
product. Before product-conscious Stage 0 is complete, a confirmed product (or an explicit
“product not yet known” state during onboarding) must be represented, and execution runs must pin
the product/context version they use. Do not invent a `brand_version` before a versioned brand-kit
payload contract exists.

### PC-D4 — the harness path may not re-profile after ICP confirmation

The interactive path naturally performs:

```text
reverse_profile → synthesize_icps → confirm_icp → start_project_run
```

Today `start_project_run` nevertheless starts at `REVERSE_PROFILING`. C4 must remove this
version-coherence hazard. The semantic ruling is:

- Stage-0 recon/kickoff produces explicit Client-KB and ICP version references.
- The ABM execution run starts from the first post-confirmation phase and pins those references.
- Recipe #1 may retain the legacy all-phases exercise for regression compatibility, but the
  harness product path never silently mints a newer KB after confirming an ICP derived from an
  older one.

The C4 child spec chooses between a parameterized entry phase and a separate execution-start
surface after inspecting migration/API compatibility. It must not keep two implicit truths.

### PC-D5 — Recipe #0 is not throwaway orchestration

C4 may implement the minimum Recipe-#0 runner needed to exercise worker + toolbelt + projections,
but it must do so behind a narrow versioned recipe/journal seam that C5 generalizes. C5 migrates
Recipe #0 onto the generic durable graph executor without changing its observable semantics.

### PC-D6 — the toolbelt stays the single domain write path

Humans, deepagents, subagents, recipes, and supervisors invoke the same typed tools. C4/C6 may not
write claims, memory, readiness decisions, source/field proposals, or project state directly from
prompt code.

### PC-D7 — C4 integrates after C1–C3

The four Step-4 lanes may develop concurrently after their child specs freeze shared contracts.
C4 integrates last because:

- its interview agenda and recon brief consume C1 gap/coverage reads;
- unmapped interview content consumes C2 proposal paths;
- uploaded kickoff material consumes C3 ingestion;
- its readiness and progress projections compose all three.

This is an integration dependency, not a requirement that C4 coding wait idle.

---

## 5. Phase C execution map

```text
Serial C0: contract freeze + prerequisite closure
          │
          ├──────── C1 coverage + goal judge ────────┐
          ├──────── C2 proposals + web resolver ─────┤
          ├──────── C3 ingestion ─────────────────────┤
          └──────── C4 Stage-0 substrate (parallel) ──┘
                                                     │
                                      integrate C1 → C2 → C3 → C4
                                                     │
                                  C5 journal + recipes + executor
                                                     │
                                  C6 platform deepagent + skills
                                                     │
                                  C7 dossier + derivation views

C8 cross-cutting prerequisites land before the dependent slice.
```

### C0 — contract freeze and prerequisite closure (serial)

**Purpose.** Prevent four worktrees from inventing incompatible ledgers, config shapes, tool
contracts, and Stage-0 identities.

**Executed record:** [`PC-C0-step4-contract-freeze.md`](./PC-C0-step4-contract-freeze.md).
Its shared types, schema ownership, tool/projection names, fixtures, and worktree treaty are
binding on all four child specs:

- [`PC-C1 — coverage and goal judge`](./PC-C1-coverage-and-goal-judge.md);
- [`PC-C2 — field/source proposals`](./PC-C2-field-source-proposals.md);
- [`PC-C3 — ingestion`](./PC-C3-ingestion.md);
- [`PC-C4 — governed Stage 0 and Recipe #0`](./PC-C4-stage0-recipe0.md).

**Deliverables before worktrees open:**

1. child specs `PC-C1` through `PC-C4`, each with owned/must-not-touch surfaces;
2. exact shared core/config types required across lanes;
3. schema ownership for coverage, proposals, ingestion, onboarding input, readiness, and override;
4. tool/projection names and reference-only response shapes;
5. integration fixtures shared by all four lanes;
6. C8 prerequisite disposition:
   - complete all-path `PreSpendGate.check` enforcement before a new loop/resolver can spend;
   - stamp per-claim identity binding before insert on contact-claim paths used by the new loops;
7. current documentation/backlog synchronization.

**Exit gate:** the four child specs can be implemented without any lane editing another lane's
owned package or independently defining the same domain shape. **Closed 2026-07-24.**

### C1 — coverage ledger + goal evaluation (REQ-04)

**Goal.** Make every research attempt, retry, stop reason, and terminal gap durable and visible.

**Scope:**

- coverage attempt ledger per `(project_run, entity, field, tier, round)`;
- append-only attempt records: strategy/source family, outcome, stop reason, cost, produced refs;
- terminal state: `filled`, `unfilled_terminal`, `blocked_by_policy`, `budget_exhausted`;
- typed gap set and read projection;
- bounded goal-judge leaf call at round boundaries;
- deterministic controller: max rounds, envelope, marginal-yield floor, allowed escalation;
- idempotency on the full round key;
- evaluation/golden set for retry usefulness, stop correctness, and gap honesty.

**Authority boundary:** the governed research agent chooses the next gap set and strategy. The
bounded goal evaluator independently challenges whether meaningful gaps remain and returns typed
advice only. Engine code validates the request, decides whether a round is permitted, verifies
promotable evidence, and enforces budget/backstops. C1 ships the substrate before C6 connects the
agent; that sequencing does not transfer planning authority to the evaluator.

**Future placement flag:** C1 implements the advisory evaluator as a bounded engine-invoked leaf so
the contract is testable before C6. Product direction is that the evaluator will probably move
inside the platform deepagent or governed research subagent. C6 must choose one final owner, remove
the other execution path, and preserve the agent/evaluator/engine authority split plus C1's durable
ledger contracts.

**Exit gates:**

- a failed field retries with a genuinely different strategy;
- every stop condition halts deterministically;
- rerunning a completed round is a no-op;
- every unfilled field in a completed run has a human-readable terminal reason;
- coverage attempts and spend reconcile.

### C2 — field/source proposals + generic tier-3 web resolver (REQ-03)

**Goal.** Keep research open-ended without making registry or trust policy prompt-controlled.

**Scope:**

- `propose_field` staging and promotion ledger;
- `propose_source` staging and promotion ledger;
- un-drop out-of-registry ICP-synthesis outputs into staging;
- human/policy approval records and audit trail;
- personal field-class proposals always require human approval;
- source tier ≤2 requires human authority; tier-3 auto-promotion may be policy-enabled with audit
  and yield-based demotion;
- generic tier-3 web resolver behind the existing `Resolver`/source-manifest seams;
- toolbelt and projection surfaces for proposal, review, promotion, rejection, and status;
- reuse the existing `config_revision` pattern rather than create a second config-mutation system.

**Exit gates:**

- an out-of-registry proposal is visible at co-confirmation, never discarded;
- promotion makes a field/source usable without code deployment;
- an agent cannot assign tier-1/2 trust;
- a `contact.facet.*` proposal cannot promote without a human approval record;
- cross-workspace proposal access fails closed.

### C3 — ingestion: uploads to claims (REQ-06)

**Goal.** Convert client-provided material into stored, segment-addressable evidence and typed
claims through the same source/adapter/extractor pipeline.

**Scope:**

- first-class ingestion job and artifact metadata;
- `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, and image/OCR adapters in the first supported set;
- artifact snapshot before extraction;
- segment/evidence-span addressing into stored bytes or canonical extracted representation;
- client-about-self trust policy versus client-about-target trust cap;
- toolbelt submit/status/retry surfaces and ingestion progress events;
- idempotency by content hash + declared context;
- DSAR and retention behavior.

**Exit gates:**

- each supported fixture round-trips to stable evidence spans;
- identical uploads do not double-spend or duplicate claims;
- client assertions about targets do not inherit client-about-self authority;
- erased material is absent from serving/projections and no derived personal text survives;
- unsupported/corrupt inputs fail loudly with a durable reason.

### C4 — Stage 0: recon, interview source, readiness, Recipe #0 (REQ-08)

**Goal.** Build the governed Stage-0 workload that the eventual platform deepagent operates.

**Scope:**

- durable brand-aware onboarding input (PC-D2);
- product/context resolution and pinning (PC-D3);
- fast and background recon envelopes, dedupe within the workspace, and abuse controls;
- live Stage-0 scrape-resolver composition behind settings;
- recon brief + gap-list projection and real progress events;
- `client_interview` source/resolver:
  - verbatim user-turn evidence;
  - idempotency on `(entity, field-or-statement, turn)`;
  - correction as claim supersede;
  - tier-1 authority only for client statements about the client; claims about target accounts
    retain the target-assertion trust cap and normal verification;
  - facts/memory/project-state/staging routing per §3.5;
- `volunteered_statement` preservation and classification;
- versioned readiness specs for ICP synthesis, discovery, and deep spend;
- recorded “just go” override;
- minimal progressive-disclosure skill loader and Stage-0 interview skill;
- Recipe #0 over the toolbelt, worker, storage, memory, C1–C3, projections, and SSE;
- remove the run-entry/KB-version incoherence (PC-D4).

**Not C4:** the final Head-of-ABM deepagent or a fake scripted substitute. C4 proves the domain
workflow through a test harness/minimal actor; C6 binds the real mind to the same tools and state.

**Exit gates:**

- URL-only onboarding emits a recon brief within the hard envelope;
- fast results arrive before the background pass completes;
- the interview asks from a gap agenda rather than enumerating fields;
- an answer becomes a claim with the verbatim turn as evidence; unsupported paraphrase rejects;
- a correction supersedes prior truth and re-synthesizes the ICP;
- preferences reach memory, project intent reaches project state, unmapped statements reach
  staging;
- readiness gates block spend below the floor and admit it immediately after;
- “just go” is durable and visible;
- project execution uses pinned Client-KB/ICP/product context and does not re-profile implicitly;
- Recipe #0 is the first live end-to-end exercise of B1+B4.

### C5 — run-graph journal, recipes, executor, supervisor (Step 5)

**Implementation state:** complete. Recipe #0 and Recipe #1 execute through the durable graph
runtime; new-run routing is feature-gated and defaults off; legacy runs retain their fixed-driver
fallback; normalized legacy/two-run Recipe #1 outcomes, historical views, SSE replay, scripts
01–06, the full suite, and migration smoke are green.

**Goal.** Make work outcome-reproducible and crash-resumable beyond the fixed pipeline.

**Scope:**

- append-only run-graph journal written by the toolbelt;
- recipe/version/compatibility records;
- pinned tool, skill, profile, policy, and input versions;
- durable graph executor;
- run supervisor over existing progress/yield/verification aggregates;
- Recipe #0 migration from the minimal C4 seam;
- legacy pipeline as Recipe #1 with canary + tier gate.

**Exit gate:** outcome reproducibility on a golden set—same pinned inputs/config produce equivalent
claims/gaps/decisions, not transcript-identical prose. Retired or incompatible references fail at
load.

### C6 — platform deepagent + skills (Step 6)

**Goal.** Build the real Head-of-ABM deepagent over the governed substrate.

**Binding child spec:** [`PC-C6 — platform deepagent, isolated workspace, and skills`](./PC-C6-platform-deepagent-and-skills.md).

**Scope:**

- import-contracted `platform/agents` implementation using the Doc-A deepagent shape;
- orchestrator resource map and minimal per-role tool allowlists;
- versioned folder-backed prompts, skills, and profiles with exact resource-manifest pins
  (`config_revision` may govern reference/profile promotion metadata, not V1 prompt/skill bodies);
- typed constitution state:
  `workspace_id`, `project_id`, pinned `brand_id`, `product_id`, readiness/stage snapshot,
  budget/profile/focus refs;
- seven-layer deterministic context assembly;
- research/content/review subagent profiles with fresh-wake delegation;
- shared filesystem record plus typed domain refs;
- plan compiler/validator and authority checks;
- delegation-node and context-bundle journaling through C5;
- an explicit decision on whether C1's advisory coverage evaluator remains a bounded engine leaf or
  moves inside the deepagent/research subagent, including one-owner/no-duplication enforcement and
  journaling of non-authoritative advice;
- honest finalize envelope.

**Exit gates:**

- plan-validation and authority-boundary tests;
- unavailable tools cannot be invoked;
- subagents cannot bypass the toolbelt or durable-write policy;
- context bundles journal ids, never bodies;
- the Stage-0 conversation demonstrates open-ended sufficiency reasoning over C4 without bypassing
  readiness;
- exactly one coverage-evaluator path exists, and its advice cannot create engine terminal state;
- a non-finalized turn is failed, never silently successful.

**Not C6:** the frontend project/thread/tab shell. C6 provides the backend agent runtime and
contracts that shell consumes; the product surface remains downstream unless a child spec
explicitly brings it into scope.

### C7 — dossier + derivation views (Step 7)

**Goal.** Produce readable, regenerable research output without turning rendered prose into a
second truth store.

**Scope:**

- `claim_derivation` edges and entailment judge mode;
- `compose_dossier` tool;
- dossier/block projection with provenance;
- coverage-and-gaps appendix from C1;
- re-check tool over snapshots + verification;
- production `HandoffCommitteeReader` and real narrative emit;
- DSAR-clean projection guarantees.

**Exit gates:**

- every sentence is a claim or a derived claim with visible supports;
- superseded supports stale/exclude dependent derivations until re-judged;
- fixture dossiers render losslessly;
- the HANDOFF gap marker disappears only when real narrative emission is proven;
- erased personal content is absent from dossier, rationale, snapshots, and projections.

### C8 — cross-cutting prerequisites and ride-alongs

These are not an independent “miscellaneous” worktree. Each item lands before the slice that
depends on it:

| Item | Must land before |
|---|---|
| All claim-producing spend paths audited through `PreSpendGate.check` + integration/lint guard | C1/C2 external spend |
| Per-claim identity-binding classification stamped before immutable claim insert | C1/C2 contact-claim loops |
| Merge conflict equality uses field `equality_mode` consistently | C7 conflict/dossier consumption |
| Retention-expired claims cannot win current-value merge | C7 handoff/dossier |
| DSAR redacts/deletes personal text in `faithfulness_verdict.rationale` | C7 DSAR-clean claim |
| Production `HandoffCommitteeReader` | C7 real handoff |
| Presign scope policy | Any evidence-serving consumer |
| Hard lease fence tokens | Multi-worker production deployment |
| Per-product fit + contact-class additions | M12-adjacent/C7 integration as specified |

Every child spec must list the C8 item it consumes and the test proving closure.

---

## 6. Parallel-worktree treaty

### 6.1 Branches

After C0 commits:

- `platform/c1-coverage-goal-judge`
- `platform/c2-field-source-proposals`
- `platform/c3-ingestion`
- `platform/c4-stage0-recipe0`

All branch from the same reviewed C0 head and integrate back into
`platform/workspace-restructure`. Do not rename the integration branch.

### 6.2 Logical ownership

| Lane | Owns | Must not independently define |
|---|---|---|
| C1 | coverage attempts, terminal gaps, goal-evaluator/enforcement controller, coverage projections | proposal, ingestion, onboarding/readiness schemas |
| C2 | field/source proposals, promotion policy, generic web resolver | coverage, ingestion, interview/readiness schemas |
| C3 | ingestion jobs, file adapters, artifact-to-segment/claim flow | coverage, proposal, interview/readiness schemas |
| C4 | onboarding input, interview source, readiness, recon, Recipe #0, Stage-0 projections | alternate coverage/proposal/ingestion stores |

### 6.3 Shared surfaces

Only these may overlap, and integration owns the final composition:

1. Alembic heads—hash ids; reversible migrations; `alembic merge` at each integration as needed.
2. `libs/clue-core`—contract deltas only; one canonical type, never lane-local copies.
3. `libs/clue-config`—append-only versioned config shapes.
4. Root `pyproject.toml` and import contracts—mechanical additions.
5. `platform/api`—concrete cross-package construction lands on the integration branch.
6. `platform/toolbelt` and `platform/projections`—shared envelope/protocol changes freeze in C0;
   lane-specific concrete registrations land at integration.
7. Shared end-to-end fixtures—C0 owns the vocabulary and ids; lanes extend, never fork.

If a lane needs another lane's owned surface, it records an integration request and stops. It does
not edit the other lane's implementation.

### 6.4 Integration order

1. C1 — foundational gap/coverage reads.
2. C2 — proposal paths used by Stage 0.
3. C3 — ingestion used by Stage 0.
4. C4 — composes C1–C3 and closes the Step-4 end-to-end gate.
5. C5.
6. C6.
7. C7.

After each merge: repair migrations/import contracts, perform an adversarial integration review,
then run the standing gates. A later lane does not open its serial successor merely because tests
compile; the preceding exit gate must be substantively proven.

---

## 7. Standing verification and review gates

Every slice and integration merge:

1. `make check`: format, lint, mypy, import-linter, full configured test suite.
2. Full DB suite on a fresh schema and immediate rerun.
3. `make db-smoke`: head → base → head on a clean throwaway DB; exactly one head.
4. Recipe #1 scripts 01–06 remain green until C5 formally adopts them.
5. Workspace/cross-tenant negative tests for every new read/write surface.
6. Idempotency retry tests, including crash/re-entry at the riskiest boundary.
7. Budget/spend reconciliation for every new external or LLM call.
8. Snapshot/evidence resolution offline for every new acquisition path.
9. DSAR tests for every new personal-data body or derived-text store.
10. Golden/eval gates for C1 goal-judge quality and C4 interview/readiness quality.
11. Independent adversarial review after each coherent implementation slice; confirmed findings
    fixed before dependent work integrates.
12. `_memory/` note with decisions, failures, verification, and unresolved follow-ups.

Green construction tests are necessary but insufficient for C1 and C4. Their quality bars are
eval-driven: useful retries, honest stopping, material questions, correct routing, and calibrated
readiness.

---

## 8. Phase-level completion definition

Phase C is complete only when:

- Step-4 REQ-03/04/06/08 acceptance tests pass;
- Recipe #0 executes the intended Stage-0 experience through real worker/toolbelt/projection seams;
- C5 journals and reproduces Recipe #0 and Recipe #1 outcomes;
- C6 is a real Doc-A deepagent and passes authority boundaries;
- C7 produces fully-provenanced, DSAR-clean dossier/handoff projections;
- all dependent C8 prerequisites are closed or explicitly proven irrelevant;
- documentation distinguishes built from planned state;
- the integration branch is clean, has one migration head, and the complete gate battery is green.

Phase C completion does **not** mean the frontend shell, every downstream content/design workflow,
or multi-worker production hardening is complete unless a child spec explicitly adds and proves
those surfaces.

---

## 9. Deferred decisions child specs must close

These are deliberately not guessed in the parent plan:

1. exact onboarding-input table/type name and version key;
2. whether project-run entry is represented by an explicit `entry_phase` or a separate
   post-confirmation start surface;
3. exact readiness-rule config schema and thresholds;
4. exact fast/background recon envelopes and abuse limits;
5. which tier-3 source promotions may auto-approve by policy;
6. first supported OCR engine and file-size/page limits;
7. goal-evaluator model/rubric and advisory calibration thresholds;
8. Recipe-#0 minimal runner representation before C5 generalization;
9. product-context pinning migration shape;
10. which C6 subagent profiles ship in the first vertical slice.
11. whether the advisory C1 coverage evaluator remains an engine leaf or moves into the
    deepagent/research subagent, and how agent-local advice is journaled without duplicating the
    evaluator or becoming authoritative state.

Each decision must be recorded once in the owning child spec and implemented as config or a stable
contract—not scattered conditionals.
