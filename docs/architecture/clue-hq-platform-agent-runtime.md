# Clue-HQ — Platform Agent Runtime & Context Assembly (Doc A)

> **Status: DESIGN RECORD v1.6 (2026-07-26 · v1.5 2026-07-26 · v1.4 2026-07-26 · v1.3 2026-07-26 · v1.2 2026-07-18 · v1.1 2026-07-17 · v1.0 2026-07-16).** Authoritative for the platform's *agentic schema*:
> what the words "agent," "deepagent," "sub-agent," "skill," "tool," and "worker fleet" mean
> mechanically, how the platform deepagent is constructed, and how context is assembled for every
> model call. Extends `clue-hq-harness-architecture-and-requirements.md` (REQ-02, REQ-18–REQ-22)
> and `clue-hq-scoped-memory-and-context-assembly.md` (Doc M — the memory layer of assembly).
> The **reference implementation** for the deepagent shape is the design subsystem's live harness
> (`havana` repo: `docs/deepagent-architecture.md`, `apps/agent_runtime/lumen_agent/`) — proven
> in production probes; this document generalizes that architecture to the platform, it does not
> invent a new one.
>
> **Prime directive (founder, 2026-07-16, verbatim in spirit):** no fake agency. If this document
> says deepagent, the implementation is a deepagent — an orchestrator with real tools, real
> subagents, a real filesystem record, and journaled context. Anything that is actually a
> deterministic pipeline is *named* a worker or a fleet, never an agent — and, symmetrically,
> anything whose task is open-ended exploration is given real bounded agency, never faked with a
> blind call chain. Violating this vocabulary in code, prompts, or product copy is a defect.
>
> **v1.1 (2026-07-17) — the fleet refinement (founder challenge, accepted).** "Worker fleet" was
> conflating the governance shell with the intelligence of the unit inside it. §1.3 now splits
> them: the **fleet shell** (queue, envelopes, idempotency, checkpoints, supervisor) is always
> mechanical; the **unit inside a slot** is either a *deterministic worker* (content
> instantiation, batch derivation) or a *governed worker agent* (per-account deep research —
> a real bounded agent). The canonical evidence both ways is havana's record: the archived
> quality loop (three blind one-shot calls, no tools) lost 3/3 to the tool-bearing deepagent —
> agency wins on open-ended tasks; and instantiating a frozen template needs no agency at all.
> Also added: §3a (the tool-output lifecycle — losslessness by construction) and the campaign &
> content strategist reframe in §1.5 (founder review comment).
>
> **v1.2 (2026-07-18) — §2.3 delegation-policy amendment (founder review).** Context transfer is
> the orchestrator's judgment (inline verbatim for small content, files for large, domain refs
> for stored objects; only paraphrase-in-place-of-original is banned); returns are proportionate
> to the task, governed by canonicality rather than brevity; and havana is the reference for the
> *mechanics* of delegation, not a stencil for its *policies*.
>
> **v1.3 (2026-07-26) — C6 resource/workspace implementation ruling (founder review).** V1
> prompts, skills, and profiles are canonical versioned **folder resources**, not database or
> hosted-hub bodies. Exact bytes and digests are materialized read-only into an external,
> per-execution agent workspace; the backend is always `virtual_mode=True` and exposes only paths
> relative to that virtual root. `config_revision` may govern profile/reference promotion
> metadata, but it does not store prompt/skill bodies. LangSmith/Langfuse prompt hubs are future
> catalog adapters, outside C6. The runtime workspace contains no application code or executable
> skill/tool surface.
>
> **v1.4 (2026-07-26) — C6.6 implemented-state update.** The governed Head-of-ABM Stage-0
> runtime is built with the real deepagents construction, exact folder resources, isolated
> workspace backend, C5-only tool execution, per-role model construction, and honest
> finalization. Fresh-wake research, content-drafter, and reviewer specialists are active behind
> governed delegation with typed task/file/ref transfer and durable reference-only returns.
> Product routing/canary activation remains C6.8.
>
> **v1.5 (2026-07-26) — C6.7 account-agent and evaluator-ownership ruling.** The governed
> per-account agent is built as the unit inside the existing fleet slot, with one replay-safe
> C5-backed gap-research tool and no facet delegation in v1. The fleet shell, evidence path, and
> deterministic coverage terminalization remain authoritative. C1's engine-owned `GoalJudge` is
> the sole independent coverage evaluator; agent stop proposals and evaluator advice are
> append-only and non-authoritative. Default-off routing and comparative canary activation remain
> C6.8.
>
> **v1.6 (2026-07-26) — C6 production activation record.** The API root now composes the
> governed model, immutable resource registry, isolated workspace, exact L1–L7 context,
> durable turn/replay/privacy adapters, and single-owner router. Master/surface switches default
> off; allowlist/percentage assignments are append-only per subject, so failure cannot fall
> through to a second owner. Authenticated body-free registry/turn/progress/telemetry projections,
> canary comparison, cache/workspace telemetry, and terminal-workspace cleanup (never live
> `awaiting_input` state) are production-composable. C6 is complete; the frontend shell remains
> downstream and C7 owns dossier/derivation/handoff output.

---

## Part I — The honest taxonomy (binding vocabulary)

Every "AI-ish" thing in the platform is exactly one of the following. The table in §1.5 classifies
every component we have or plan.

### 1.1 Tool

A typed, precondition-checked, budgeted, idempotent, journaled function over the substrate
(the toolbelt envelope, harness doc §4.2). A tool has no goals, no loop, no memory. Tools are the
**only write path** to domain state — for agents *and* humans (REQ-20).

### 1.2 Skill

A **versioned prompt + policy bundle** (resource/config, not code): frontmatter (tool allowlist,
readiness-spec ref, overlays) + a craft body. In V1 the canonical bytes live in the reviewed
folder catalog; an exact version + SHA-256 is pinned by recipes and run journals and materialized
read-only into the execution workspace. `config_revision` may ledger promotion metadata or a
profile binding, but does not hold the body. A skill *loads into* an agent's context; it is never
itself an actor. Skills load by **progressive disclosure** (name + description visible; body
loaded on invocation) — proven in havana (`SkillsMiddleware`; the flat skills-parent-dir lesson
is inherited: skills live under one parent directory or they silently do not load).
The current resource paths and immutable version-change workflow are maintained in
[`docs/agents/skill-and-profile-authoring.md`](../agents/skill-and-profile-authoring.md).

### 1.3 Worker fleet — the shell is mechanical; the unit inside may not be *(revised 2026-07-17)*

**The fleet shell** is a deterministic engine fan-out and is never a mind: tier-priority queue +
concurrency window + per-unit budget envelopes + idempotency keys + checkpoint/resume + circuit
breakers + canary gate + run supervisor. Calling the *shell* "an agent" is a defect. Between the
platform deepagent and the units there is **no agentic middle-orchestrator** — scheduling, money
allocation, and fleet halting carry no judgment content and are exactly the authorities the iron
rule reserves for the engine. Mid-run judgment lives in the supervisor's bounded LLM *triage*
(diagnose + propose; journaled bounded actions execute), never in an LLM scheduler.

**The unit inside a slot** comes in exactly two classes, chosen by one principle — **match
runtime agency to runtime uncertainty**:

- **Deterministic worker** — for closed, contract-bounded work: template instantiation,
  programmatic resolve, batch derivation, QA gating. Control flow is code; LLM appears only as
  fixed skill-derived leaf calls (or a bounded micro-loop: fetch → produce → deterministic checks
  → grounding self-check → at most one guided retry). The thinking already happened upstream (the
  strategy, the schema, the exemplar); runtime creativity here is a defect — consistency is the
  product. Doc S §6 is this class.
- **Governed worker agent** — for open-ended exploration: **per-account deep research**. A real
  (small) agent per §1.4, one account per slot: reasons over the typed gap set, chooses tools,
  strategies, and stopping within deterministic backstops (max rounds, envelope, marginal-yield
  floor, fan-out caps — *limits, not scripts*); runs its own micro-loop by default and may spawn
  **facet sub-agents** for context isolation only (a transcript, a doc-site crawl, one contact's
  footprint) — depth-capped at one, count-capped, drawing the same account envelope,
  LangGraph-checkpointed for exactly-once resume. The substrate is what makes this safe: no unit,
  however clever, can promote an evidence-less claim, set a tier, or exceed an envelope — the
  quality floor is the data model, so agency raises the ceiling without lowering the floor.
  Per-unit cost telemetry (havana's `model_call_usage` pattern) rides from day one so
  agency-vs-coverage is *measured* per tier; a tier where agency buys no coverage degrades to a
  cheaper posture by config.

The canonical evidence both ways: havana's archived quality loop — three blind one-shot LLM
calls, no tools, no verification — lost 3/3 to the tool-bearing deepagent and is formally retired
(*a worker where an agent belongs*); havana's live telemetry (author mind ~1.65M input tokens
over 21 calls in one turn) is why nobody puts a ReAct loop inside 5,000 template instantiations
(*an agent where a worker belongs*).

**The three-layer execution stack** (binding):

| Layer | Nature | Decides |
|---|---|---|
| Platform deepagent (thread) | Agentic | whether/what to run — one campaign-op tool call enqueues a fleet run |
| Fleet shell (worker + driver + supervisor) | Mechanical (+ bounded LLM triage in the supervisor) | scheduling, envelopes, checkpoints, breakers, canary, halt |
| Unit per slot | Deterministic worker **or** governed worker agent (per above) | everything inside one unit of work, within its backstops |

### 1.4 Agent / deepagent

An agent is precisely this assembly (the havana-proven shape, on the same stack —
`deepagents`/LangGraph `create_deep_agent` or its successor):

1. **An orchestrator mind** — the deepagent orchestrator (`create_deep_agent`), with a role
   system prompt ending in an exhaustive resource map (its tools, its workspace layout, what it
   does NOT have — havana M4). Not a hand-rolled single LLM loop.
2. **A tool surface** — an explicit, minimal, per-role allowlist from the toolbelt. Tool absence
   is an enforcement mechanism (havana: `request_clarification` removed when not permitted).
3. **Subagents** — invoked via `task(subagent, prompt)`; each wakes **fresh** (system prompt +
   skills + task prompt only), shares the typed state and filesystem, returns only its final
   report. Continuity lives in files and typed state, never in a subagent's memory.
4. **A filesystem workspace as the record** — per-run directory (brief, state, rounds/steps,
   reports, previews, trace). Files are canonical; chat is a view. Live domain state (claims,
   scenes, scores) is deliberately NOT files — projections/`inspect` are the live truth.
5. **Typed constitution state** — a small set of typed fields riding LangGraph state into every
   mind (`workspace_id`, `project_id`, the project's pinned sender `brand_id`, `product_id`, stage
   snapshot ref, budget envelope ref, profile versions, focus refs). Tiny by design.
6. **Skills** loaded per §1.2; **model gateway** per role (per-role model/effort overrides, output
   bounds, timeouts, retries — havana D10/L3); **append-only history** for prefix-cache stability
   (havana L1: ~95% cached prefill when history is never mutated; any in-place edit forfeits it).
7. **Journaling** — every tool invocation journals to the run graph (REQ-12); every assembled
   context bundle journals ids-not-bodies (Doc M §11); an honest finalize envelope ends every
   turn (a turn that did not finalize is *failed*, never silently successful — havana's
   honest-finalize guarantee).

The agent gains authority only over *which tools, in what order, with what parameters* — the
iron rule (LLM proposes, engine disposes) and the authority table (harness doc §2.5) bind every
agent identically.

### 1.5 Classification of every component (no exceptions)

| Component | Class | Status |
|---|---|---|
| Head-of-ABM platform deepagent | **Deepagent** (Part II) | **LIVE behind default-off C6.8 ownership routing** |
| Design deepagent (havana `lumen_agent`) | **Deepagent** (orchestrator + author + reviewer subagents) | **LIVE** — reference implementation |
| Research specialist | **Subagent** of the platform deepagent (judgment tasks) + the research **toolbelt** (project ops) — O10 split | **LIVE in C6.6** — fresh-wake profile, skill, governed delegation |
| Campaign & content strategist | **Role of the platform deepagent** (strategy is the main conversation, not a delegation): first the **VP-of-growth hat** — which channel campaigns to run at all, for which account-signal strengths and tiers — then the artifact/content strategy that follows per campaign, with strategy skills | Skills to author |
| Content drafter (exemplar, one account) | **Subagent** of the platform deepagent | **LIVE in C6.6** — exemplar only |
| Content scaling (N accounts × artifacts) | **Deterministic workers in the fleet shell** (§1.3; bounded micro-loop, honestly not an agent — Doc S §6) | To build |
| Pass-A scoring / discovery fan-out | **Deterministic workers in the fleet shell** (scoring is code; rubric is config) | Substrate built |
| Per-account deep research (Pass B) | **Governed worker agents in the fleet shell** (§1.3): one bounded agent per account, waterfall as its power tool; facet delegation only after measured need | **LIVE behind default-off C6.8 ownership routing** |
| Review/QA of scaled artifacts | **Deterministic workers** (gates + judge leaf calls) + M13.1 human surface; a review *subagent* only for exemplar-level critique | Exemplar reviewer **LIVE in C6.6**; scaled QA remains future |
| Faithfulness/goal/grounding judges | **LLM leaf calls inside engines** (never minds with tools) | M9 built; C1 `GoalJudge` is the sole coverage evaluator owner; grounding judge new |
| Recipes, waterfalls, scoring, derivation | **Engine** (no LLM in control flow) | Built |

## Part II — The platform deepagent (Head-of-ABM)

### 2.1 Position

One platform deepagent fronts **every thread** (REQ-21): the user's single conversational
companion for a project, end to end. Specialist capability reaches the thread only as (a) toolbelt
calls, (b) subagent delegations whose outputs persist in the thread, or (c) the one surface-bound
exception — the design editor's own deepagent, reached by handoff (Doc S §8) because design
carries a heavy surface-specific context (canvas, brand kit, editor) that must not pollute the
strategy thread, and vice versa. Threads never bind to specialist agents (founder ruling,
2026-07-16).

### 2.2 Anatomy of a turn

```
user turn (thread, project-scoped)
  │
  ▼
CONTEXT ASSEMBLER (engine code, deterministic — Part III)
  builds the turn context: profile + skills + cards + memory bundle + focus refs + history
  journals the bundle (ids, never bodies)
  │
  ▼
ORCHESTRATOR mind (Head-of-ABM system prompt, resource map, toolbelt allowlist)
  plans; converses; invokes tools; delegates via governed delegate_specialist:
    ├── research subagent      (fresh; gap-chasing, source judgment, dossier questions)
    ├── content-drafter subagent (fresh; exemplar drafting against the content schema)
    ├── review subagent        (fresh; critique of exemplars — never edits)
    └── … (registry-defined, REQ-18 profiles govern availability + delegation rules)
  every spending/executing call goes through the toolbelt → engine gates
  fleet work (discovery, deep research, scaling) is LAUNCHED, never performed, in-thread:
    the tool enqueues to the detached worker; the narrator streams progress back (REQ-11)
  │
  ▼
honest finalize envelope → thread message(s) + typed object refs (REQ-21) + journal
```

Blocking rules carried from the research architecture: the thread session **never executes**
long-running work (step-0 worker owns runs; sessions attach/detach); human gates pause and
surface identically whether reached directly or inside a delegation (REQ-19).

### 2.3 Subagent contract *(revised 2026-07-18)*

Per REQ-19, plus the havana-proven mechanics: subagents wake amnesiac; continuity lives in typed
state, exact artifact refs, and immutable file copies, never in a subagent's memory. Each platform
child has a distinct execution workspace; an original granted from the parent is copied
byte-for-byte through the artifact store and materialized read-only at a receipt-backed child path.
This preserves canonical bytes without sharing writable authority or host paths.

**Context transfer is the orchestrator's judgment, within one ban.** The orchestrator equips a
subagent with a well-written task prompt (goal, constraints) plus whatever context the task
needs, choosing the channel by size and nature: **small content rides the task prompt verbatim**
(an excerpt, a field spec, a handful of claims); **large or canonical content rides as workspace
files** the subagent reads at full fidelity (briefs, exemplars, artifacts); **stored domain
objects ride as refs** (claim ids, dossier blocks) the subagent pulls through tools. The one
banned move is **paraphrase standing in for the original** — a mind retelling an artifact from
memory where the original is available to read; that lossy relay is the disease that killed
havana's archived pipeline.

**Returns are proportionate to the task, governed by canonicality.** A reviewer's verdict may be
ten lines; a research subagent's gap analysis may be pages — return shape is sized per subagent,
decided when each subagent is designed. The invariant is not brevity but **canonicality: the
return is for the orchestrator to act on; it is never the storage.** Anything durable the
subagent produced must land as a workspace file or a domain write through a tool (both
journaled) before the return references it — returns live only in the orchestrator's context,
and context is a cache (§3a).

Structured outputs use tool-strategy format (havana D11) — never trust native structured output
across gateways. Scope note: **havana is the reference for the *mechanics* of delegation**
(state sharing, fresh wake, filesystem record, structured-output pitfalls), **not a stencil for
its *policies*** — its delegation policies were tuned for single-document design turns; the
platform deepagent's per-subagent policies (context richness, return shape, budgets) are
designed against this platform's tasks.

### 2.4 Where it runs, and what exists

The platform deepagent is **to be built** — in the platform backend repo (dar-es-salaam), on the
same framework the design deepagent already runs in production probes. The research repo's
in-repo deep agent (`agent/`, build step 6) becomes this agent's research-specialist facet; its
lift-out design (harness doc §10, agent-location decision) is exactly this landing. Nothing in
this section is speculative architecture: every mechanism cited above has a live, tested
implementation in havana with recorded evidence trails; the work is instantiation, not invention.

### 2.5 Tool-error recovery (implemented 2026-09-25)

Native parallel tool batches settle completely before the next model call. Governed failures
return per-call feedback; successful sibling receipts remain valid. The checkpointed allowance
counts failed batches followed by corrective model rounds, not the number of sibling errors.
Ten corrective rounds are available per agent turn; an eleventh failed batch stops before another call.
Finalization must be a separate call after reading sibling results, so it cannot commit midway
through an unfinished batch.

A corrected governed call may supply `retry_of`, naming failed node keys for that same work.
This is plan metadata, never a provider argument or authority field. The executor validates the
same execution, workspace, agent interaction slot and tool, and requires a successful replacement
receipt before appending `node.recovered`. The original `node.failed` event remains unchanged.
Recovery applies to direct agent leaves without dependent graph nodes; it does not rewrite graph
edges or turn the original failure into a successful receipt. Unrelated successes clear nothing.
An execution can settle after all its failed leaves are explicitly recovered; unresolved failures
still prevent a successful finalization. Replaying an already recovered failed attempt is refused.

`PlanToolStep.retry_of` defaults to an empty tuple and is omitted from serialized historical
plans when empty. Migration `4c916b02ed9b` adds the recovery event vocabulary. Downgrade is safe
on a clean database; it refuses to rewrite existing recovery audit records into older event types.
Research `record_research_finding@3` independently derives exact-retry write identities from
canonical finding content and resolved sources within its job. This does not deduplicate meaning
or replace the explicit claim-correction tools.

## Part III — Context assembly (the pipeline, exactly)

**Assembly is engine code.** The agent never "gathers its own context" for a turn's opening
frame; it *requests more* via tools (inspect/read/view-equivalents) mid-turn. Every assembled
bundle is journaled per Doc M §11 (ids + labels + what the budget excluded and why), so "what did
the agent see" is always answerable, and DSAR never becomes a journal-redaction debt.

Layers, assembled in order, each with a hard token budget (budgets are versioned config):

| # | Layer | Content | Source | Never includes |
|---|---|---|---|---|
| L1 | Identity | Agent profile system prompt (pinned version) + resource map; skill names/descriptions (progressive disclosure) | REQ-18 registry | other roles' prompts |
| L2 | Workspace/product | **Product profile card** (§4.2) + brand-voice card — hard-capped digests | compiled projections | full claim dumps, raw uploads, full brand kit JSON (havana's context-blowup lesson: the kit rides engine-side; the card teaches) |
| L3 | Project | Bounded composition: always-present project-conversation envelope + account-wide Client-KB index when available + only the active project's Stage-0/project-state projection | projection API; exact production contract in `docs/specs/FI-production-deepagent-context-composition.md` | run transcripts; full claim dumps; another project's Stage-0 state |
| L4 | Memory | Doc M context-assembly bundle: scoped memories (workspace→brand→product→project→account), deterministic selection, advisory-never-binding | Doc M seams | memory bodies of other tenants (structurally impossible); superseded records |
| L5 | Focus | The user's active tab refs + @-mentions, resolved to **object cards** (dossier block excerpts, account card, draft excerpt) by reference | REQ-21 object-ref vocabulary → projections | whole dossiers/tables (the agent pulls specifics via tools) |
| L6 | Conversation | Thread history, **append-only** (cache stability); summarization middleware armed on the orchestrator only as emergency net (havana D4) — files-first offloading means nothing summarized is ever the only copy | thread store | mutated/rewritten history |
| L7 | Turn | The user message + attachments (as refs + staged files) | — | — |

**The never-in-context list (binding):** full claim tables; full brand kits; raw scraped pages or
uploaded binaries (ingestion produces claims; agents read claims/projections); worker-fleet
transcripts (supervisors read aggregates — REQ-10); another mind's paraphrase where a pointer
exists; anything a tool can fetch on demand at higher fidelity.

**Cards are compiled, versioned projections.** A "card" (product profile card, project state
card, account card, brand-voice card) is a hard-capped, engine-compiled digest with a version and
a provenance line, regenerated when its sources change — the platform generalization of havana's
`brand_card.json`. Cards teach; engines enforce; the full data never rides the prompt.

### §3a — The tool-output lifecycle: losslessness by construction *(added 2026-07-17)*

**The context window is a cache; it is never a store.** Losslessness is achieved by writing
everything durable *engine-side, at the moment of acquisition, before the agent sees a summary*.
One `research_fields(...)` call produces five durable writes before its return value exists:

| # | What | Where | Property |
|---|---|---|---|
| 1 | Raw source bytes (every page/PDF/transcript touched) | Content-addressed snapshot, `artifact` table (REQ-07) | Evidence points into stored bytes, never live URLs; identical bytes dedupe |
| 2 | Extracted facts | Claim store: value + source + evidence span (offsets into the snapshot) + tier + confidence + freshness; append-only, supersede-not-overwrite | No fact exists as paraphrase-only; history survives |
| 3 | The attempt — including failures | Coverage ledger per `(entity, field)`: round, strategy, outcome, stop_reason, cost | Failed effort is data (goal-judge + gaps appendix read it) |
| 4 | The invocation | Run-graph journal node (params, pinned config versions, produced refs, cost) — written by the toolbelt, never the agent | "What happened" survives any context compaction or crash |
| 5 | Spend | Budget ledger draw-down, exactly-once on the idempotency key | No double spend on resume |

What returns to the agent is deliberately small: **claim ids + brief values + a typed coverage
report** — a receipt, not the goods. The agent reasons over the receipt and *pulls* detail on
demand (claim text, span, ledger history) at full fidelity by reference. Tool results in the
conversation are transient and safely compactable *because nothing in them was ever the only
copy*. A facet sub-agent may read a full transcript in its own disposable context — but the
transcript was snapshotted first, and the child's conclusions exist only if they land as
claims-with-spans through the extractor seam; its context dies, its knowledge doesn't. Workspace
files record the *reasoning trail* (durable, but explicitly not a fact store: a finding written
only in a note and never landed as a claim does not exist). Crash/resume: checkpoint restores
typed state; everything factual is re-derivable by reference; duplicate work is a no-op on the
keys. DSAR: journals and bundles hold ids-never-bodies, so erasure is a deterministic
tombstone-and-cascade (claims → snapshots), never a transcript hunt.

**The waterfall seam, restated for agents:** the trust-tiered source waterfall executes *inside*
the toolbelt tools. The unit agent decides **where to point the drill** — which fields/facets this
round, strategy hints (query widening, source-family preference), `propose_source` nominations
(tier assigned by policy/human, never by the agent), and how to read typed stop-reasons; the
waterfall *is* the drill, and every trust mechanic runs identically no matter who pulled the
trigger.

## Part IV — Product profiles & cross-project continuity (Stage-0 consciousness)

### 4.1 What it is

Per founder (2026-07-16): a workspace's **products are first-class**. Each product line (e.g.
Microsoft 365 consumer vs. Microsoft's enterprise suite) accumulates its own research substrate —
audiences, competitors, reviews, imagery, brand voice — and every new project declares (or
discovers) which product it serves. The Nth project on a product starts from what the platform
already knows, conversationally: *"we already have these about this product — anything you want
to change?"* Nothing in Stage 0 as designed (REQ-08) is removed; this is a **reuse-awareness
layer** on top.

### 4.2 Mechanism (no new stores — a new dimension + a card)

- **`product` entity** (platform backend): id, workspace, name, aliases, status. Projects carry
  `product_id` (declared at kickoff or proposed by recon and confirmed).
- **Product-scoped truth is claims, as always.** `client.*`/product facts carry reuse-scope at
  product granularity (the claim store's reuse-scope machinery already exists for exactly this
  partitioning); product-scoped assets (brand-voice guide, imagery) live in the artifact store;
  preferences/learnings live at Doc M's **product scope** (already one of the five scopes).
- **Product profile card** (context layer L2): the compiled digest — positioning, audiences,
  named competitors, voice summary, proof points, asset inventory — every line resolvable to a
  claim/memory/asset id. Versioned; recompiled on substrate change.
- **Kickoff behavior = the readiness spec, satisfied early.** A new project on a known product
  finds its Stage-0 readiness floors already substantially met by existing product-scoped claims;
  the interview then runs in **confirm/refresh mode**: only fired-staleness claims, stale
  memories (Doc M §13 kickoff gate), and genuinely new gaps surface as questions. A new product
  runs classic full Stage 0 and *creates* the profile. The brand-voice guide, when missing, is
  produced by a skill-guided workflow (a deepagent activity, exemplar-level) and stored as a
  product-scoped asset + claims.
- **Freshness is inherited, not reinvented:** claim TTLs/age-out (M9.5) + Doc M staleness signals
  drive what the kickoff re-asks. Corrections at kickoff are ordinary supersedes.

## Part V — Honesty ledger & pre-mortem additions

**Current state, plainly:** design deepagent — live (havana). Research substrate (claims,
waterfall, verification, scoring, M8A fleets) — built. Research toolbelt envelope, detached
worker, projections — build steps 0–2 pending. Platform deepagent, content plane, workspace
shell, product profiles — designed here, not yet built. Anyone reading this doc should be unable
to confuse the built with the planned.

Pre-mortem (extends harness doc §11):

1. **Class mismatch (fake agency and its two inverses)** — a "pipeline in an agent costume"
   ships (fixed call sequence marketed as an agent); an unbounded agent lands where a
   deterministic worker belongs (5,000 instantiations on ReAct loops); or a blind worker lands
   where an agent belongs (the havana quality-loop failure — the canonical citation). Guard: §1.5
   classification is binding; changing a component's class is a decisions-register event; §1.3's
   uncertainty principle decides new cases.
2. **Context bloat** — cards grow into dumps. Guard: hard per-layer budgets as versioned config;
   bundle journal makes every overflow visible; havana's kit lesson cited in review.
3. **Paraphrase relay** — subagent briefs start pasting artifacts. Guard: pointers-not-paraphrase
   is a prompt-pinned contract + trace review; the file/state channels exist precisely so relays
   stay thin.
4. **Cache-busting edits** — anything that rewrites history in place forfeits prefix caching and
   multiplies cost silently. Guard: append-only history invariant, telemetry on cached-prefill %.
5. **Two sources of truth** — the workspace files drift from domain state. Guard: files are the
   *record of the work*; domain truth stays in Postgres behind tools; live state is never a file.

## Cross-references

| Topic | Where |
|---|---|
| Requirements this doc satisfies | Harness doc REQ-02, REQ-18–REQ-22 |
| Memory layer of assembly, bundle journal, kickoff gate | Doc M §7–§13 |
| Content plane, scaling fleets, design handoff pack | Doc S (`clue-hq-content-and-artifact-scaling.md`) |
| Reference deepagent implementation & its decision ledger | havana `docs/deepagent-architecture.md` |
| Fleet quality pyramid, run supervisor | Harness doc REQ-10 |
