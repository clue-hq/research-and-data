# Clue-HQ Research Subsystem — Harness Re-platform Proposal

> **Status: PROPOSAL (draft for founder review — 2026-07-03).** Not yet adopted; nothing here is
> implemented. This responds to the founder's platform-level requirement clarification: the product
> is a **deep-agent / harness platform** — modular capabilities orchestrated by a skills-guided deep
> agent in a *dynamic* (non-linear) order, with a node-based representation for reproducibility —
> rather than a fixed linear ABM pipeline. It builds on, and supersedes parts of, the 2026-06-28
> two-plane orchestration recommendation (`_memory/2026-06-28-agent-orchestration-architecture.md`).
>
> **Addendum (2026-07-11).** The node-canvas rendering surface referenced throughout this proposal
> (the §1 plane diagram, §1.4, build step 5, §7 decision 6) was retired as a product surface on
> 2026-07-11 in favor of a Hyperagent-inspired **agent-workspace UX**: an agent registry of
> configurable platform agents, orchestrator-led composition, and run/activity/recipe-library
> views on one shared human–agent surface. The underlying reproducibility mechanics — run-graph
> journal, recipes, pinned configs — are unchanged. This document remains the frozen evidence
> trail; see `clue-hq-harness-architecture-and-requirements.md` v1.1 (REQ-12 revised,
> REQ-18–REQ-20 added) for the authoritative statement.

---

## 0. Verdict in one paragraph

The pivot is right, and this codebase is unusually well-positioned for it — *because of*, not in
spite of, the substrate-first bet. Verifiability, budget discipline, compliance, and idempotency
were built into the **data model and gates**, not into the phase order; the linear campaign state
machine is packaging, not foundation. The survey confirms it: every phase handler is already
near-tool-shaped, `AccountDeepOrchestrator.run_one` is already a standalone per-account tool, and
running phases out of order today produces *silent empty results, not corruption*
(`api/deep/handler.py:252` — missing tier cutoffs → empty high-tier set). So the re-platform is a
**re-packaging plus two new planes** (orchestration + reproducibility), not a rewrite: keep the
kernel, expose capabilities as governed tools with *loud* declared preconditions, let a deep agent
compose them, and journal every composition as a re-runnable graph. The current pipeline ships as
**Recipe #1**, so nothing regresses while agency is added.

The one iron rule carried forward from the 2026-06-28 analysis: **the LLM proposes, the engine
disposes.** The agent gains authority over *which tools, in what order, with what parameters* — it
never gains authority over fan-out size, spend, phase-internal sequencing, being the source of an
entity/fact/score, or bypassing a gate. Agency is safe here precisely because the gates are in the
substrate.

---

## 1. Target architecture — four planes

```
┌────────────────────────────────────────────────────────────────────────┐
│ 4. REPRODUCIBILITY PLANE      run-graph journal · recipes · node canvas │
├────────────────────────────────────────────────────────────────────────┤
│ 3. ORCHESTRATION PLANE        deep agent (chat) · skills · goal-judge   │
│                               loop · plan → execute → observe → replan  │
├────────────────────────────────────────────────────────────────────────┤
│ 2. CAPABILITY PLANE           the toolbelt: typed, precondition-checked,│
│    ("the research toolbox")   budgeted, idempotent, journaled tools     │
│                               (MCP-ready; two granularities)            │
├────────────────────────────────────────────────────────────────────────┤
│ 1. KERNEL (unchanged)         claim store · identity · field registry + │
│                               packs · source registry/manifests/profiles│
│                               · waterfall engine · verification gates · │
│                               compliance · budget ledger · config-as-   │
│                               data · obs                                │
└────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Kernel (plane 1) — keep, consolidate

Nothing conceptual changes. The claim store remains the only shared substrate; components still
compose through claims, never through imports. Two corrections land here (see §5): a small DRY
consolidation pass, and an explicit **contract-delta lane** for `core` so "frozen" stops being read
as "untouchable" (that misreading — not the import contracts — is what produced the helper copies).

### 1.2 Capability plane (plane 2) — the toolbelt

Each research capability becomes a **tool**: a typed façade over the existing module. This is mostly
packaging — the survey's tool-readiness table shows the handlers are close already.

**Tool contract (uniform envelope, every tool):**

- **Typed params** — entity ids / entity-set selectors, field sets, budget envelope, config refs.
- **Declared preconditions, checked loudly.** Today's failure mode ("deep with no tier cutoffs →
  silently zero accounts") becomes `PreconditionFailed("no tier cutoffs on run; run tiering or pass
  an explicit cutoff/override")`. Preconditions are *data* on the tool (introspectable by the
  planner and renderable in the canvas), not prose.
- **Idempotency** — same keys as today: `(entity, field, tier[, round])`, `(campaign_run, phase)`
  analogues per tool. Re-invocation is cheap and safe; this is what makes "apply X across all 500"
  and recipe re-runs tractable.
- **Cost estimate** — every tool exposes `estimate(params)` so a plan has a pre-run price
  (extends the M13.4 pre-run-estimate surface to arbitrary graphs).
- **Returns references + a coverage report** — claim ids, entity ids, gap/attempt summaries. Never
  blobs.
- **Journaled** — every invocation writes a run-graph node (plane 4) with pinned config versions
  (icp_spec version, source-profile version, skill/prompt versions, model ids).

**Two granularities, same engine underneath:**

| Level | Examples | Why |
|---|---|---|
| **Campaign ops** (set-scoped; engine-managed fan-out) | `discover_accounts`, `import_accounts`, `score_accounts`, `assign_tiers`, `deep_research_accounts(set)`, `verify_accounts(set)`, `build_handoffs(set)` | The agent must never hand-roll a 500-account fan-out; concurrency, locks, budget admission, exactly-once spend stay engine-owned |
| **Entity/field ops** (fine-grained) | `research_fields(entity, fields)`, `resolve_committee(account)`, `profile_contact(contact)`, `compose_dossier(account)`, `propose_field`, `propose_source`, `ingest_material`, `re_verify(claims)` | What the judge-loop, user steering, and non-linear sessions actually need |

**Human checkpoints become gate-tools, not phases.** `tier_checkpoint` and budget approval are
tools that pause for a decision (exactly the current PAUSED semantics) — the agent can place them
in any plan, and policy can *require* them before certain tools (e.g. `deep_research_accounts`
requires a tier decision precondition unless the client's policy allows auto-cutoff).

**MCP for free (later).** The toolbelt's typed schemas are exactly an MCP server surface; exposing
research tools to Claude Code / Cursor / the platform agent is one adapter, no new logic.

### 1.3 Orchestration plane (plane 3) — deep agent, skills, goal-judge loop

- **The deep agent** is the conversational control plane (per the 2026-06-28 rec) with expanded
  authority: it compiles intent into **plan graphs over the toolbelt** instead of only triggering
  `advance()`. It narrates progress to chat (the diagram's pink note) via the streaming surface
  (§6, build item).
- **Skills = versioned config, not code.** A skill is a prompt+policy bundle ("how to deep-research
  an account in this vertical", "how to run the gap-escalation loop", "how to write a dossier"),
  stored and versioned like source profiles / rubrics, proposed→promoted through the M13.3
  `config_revision` ledger, overridable per client/industry. Skills are what make agent behavior
  both good and *pinnable* (a recipe pins skill versions).
- **The goal-judge loop** (the diagram's "Judge — /loop until goal achieved"): a per-module loop
  around account research and contact research. The judge's verdict is a **typed gap set**, not
  free text: `goal spec (field set × coverage targets × verification health) − current state →
  gaps + next strategy`. An LLM may *critique* (propose reformulations, nominate sources); the
  loop's control decisions (continue/stop) are deterministic: `max_rounds`, budget, marginal yield
  — reusing the M8A `sub_phase` + `ExactlyOnceSpend` machinery with the key extended to
  `(account, field, tier, round)` exactly as the 2026-06-28 note planned. Note the naming split:
  the **goal judge** (coverage; new) is distinct from the **faithfulness judge** (M9.3, truth;
  exists).

### 1.4 Reproducibility plane (plane 4) — run graphs, recipes, canvas

The answer to "brilliant one-off session we can't reproduce":

- **Run-graph journal.** Every tool invocation = a node `(tool, params, pinned config versions,
  produced refs, cost, outcome)`; edges = data dependencies (what it read/wrote). The agent doesn't
  *maintain* this — the toolbelt journals it as a side effect, so it is always accurate.
- **Recipes.** A completed (or hand-edited) run graph can be **pinned as a recipe**: parameterized
  (client, ICP, account set become variables), versioned, shareable. Re-run = execute the graph
  through the same durable executor. **The current linear pipeline ships as Recipe #1** — the
  state machine's sequence expressed as a graph — so existing behavior is preserved verbatim and
  the migration is additive.
- **The node canvas** renders run graphs and recipes: nodes = tool invocations / task-specific
  sub-agents, live status from the streaming surface, pin/edit-params/re-run affordances. V1 is
  **agent-authors / user-pins-and-re-runs**; free-form user graph *authoring* can come later.
- **Honest replay semantics: outcome-reproducible, not transcript-identical.** Same recipe + same
  state ⇒ no-op (idempotency). Same recipe + new accounts ⇒ same *process*: same tool sequence,
  same pinned rubric/profile/skill/prompt/model versions, same gates and thresholds. LLM leaf
  nodes remain stochastic; what bounds them is pinned configs + verification floors + the M9.6
  eval battery + the M13.3 backtest gate. Promising bit-identical outputs would be false; this is
  the defensible version of repeatability, and it's the one enterprises actually audit.
- **Durable executor.** The campaign state machine generalizes: instead of one hardcoded phase
  enum, the M7 machinery (checkpoints, resume, pause/adjust, Temporal-shaped) executes **graphs**.
  The phase enum survives inside Recipe #1. This keeps the Temporal migration path intact.

**Where the "60 artifacts, one change across all" flexibility shows up here:** the research
analogues — re-score after an ICP edit, re-research after a field registration, re-verify after a
policy change — are all "bump a config version + re-run the affected sub-graph over the entity
set", cheap and safe because tools are idempotent and claims are append-only/versioned. The claim
store was built for exactly this; the toolbelt exposes it.

---

## 2. What the survey actually found (evidence the design leans on)

| Area | Finding |
|---|---|
| Phase order | Enforced only by the sequential state machine (`durable/campaign.py:83–90`); handlers don't validate predecessors; out-of-order = silent empty results, not corruption. Tool preconditions must make these loud. |
| Tool-readiness | `run_one` (M8A), discovery, reverse-profiling: standalone-ready. Scoring/verification/review/handoff: ready with "claims must pre-exist" preconditions. Deep: needs an explicit tier-cutoff precondition. |
| Execution topology | Inline, in-process (`campaign.py:454`, `scheduler.py:136`); **no detached worker**; single-driver documented but unenforced. Confirms 2026-06-28 Phase-0 as the hard prerequisite. |
| Waterfall duplication | **Refuted.** One engine (`sources/waterfall.py:176–354`); stage0 (`stage0/client_kb.py:187`), Pass-A scoring (`discovery_scoring/scoring/engine.py:163`), account aspect workers (`profiling/aspect_worker.py:406`) all call it. One true re-implementation: `profiling/contact/fill.py:103–218`, deliberate (per-claim identity-binding must be stamped *before* insert; the waterfall stamps the coarse manifest prior). Fix: a `claim_tagger` pre-insert hook on `resolve_field`, then contact fill calls the shared engine (−~115 duplicated lines). |
| Real DRY debt | Small and mostly already tracked in CLAUDE.md backlog: `reference_time` ×2, `normalize_url`/host ×3, jsonb scalar decode ×5, manual budget-threading pattern ×3 (wants a `BudgetTracker`). Root cause: the Beat-0 core freeze read as "never touch core" → local copies instead of contract-deltas. |
| Import contracts | Not over-applied: independence binds *milestone workers* to compose via claims; shared services (`core`, `claimstore`, `identity`, `icp`, `sources`) are importable by everyone and that's where shared logic already lives. Keep the contracts; fix the core-delta process. |
| Source planner | Deliberately bounded (staged-flow §7d: "config-bounded LLM planning"); allowed set = profile ∩ registry with off-set LLM picks dropped **and audited** (`sources/planner.py:260–275`). The registry is open-by-construction with a runtime `register_source()` (`sources/registry.py:283`) — what's missing is a *registrant path* for the agent + a tier-3 generic web resolver (Firecrawl resolver is tier-2 target-locked to the entity's own domain; Exa/Parallel are tier-4). |
| Field registration | Runtime `register_field()` exists with full validation (`claimstore/registry.py:207–323`); ICP synthesis currently **silently drops** LLM-proposed out-of-registry fields (`stage0/icp_synthesis.py` bounds step). The M13.3 `config_revision` proposed→promoted ledger is the exact staging pattern to reuse. |
| Gap handling | Gap *detection* exists (`durable/planning.py:110–137`, waterfall `StopReason`), freshness re-research exists for *stale* claims (M9.5) — but nothing retries *never-filled* fields, no attempt ledger, no unresearchable-to-review surfacing, no loop closure. |
| Dossier | Value narrative + handoff assembler + two-sided provenance exist (`narrative/`); no human-readable rendering, no derived/inference-claim concept (no `derived_from` edges). |
| Ingestion | Modality-adapter framework exists (pdf, transcription, firecrawl-html, passthrough; content-addressed `ArtifactCache`; `ClaimExtractor` seam) — no upload path, no docx/pptx/image adapters, no durable blob storage, CKB takes bare text only. |
| Storage | Nothing exists; Postgres-only. New uncommitted `config/settings.py` is the natural config slot. |

---

## 3. The five product requirements — design

### R1 — Dynamic field registration (LLM-proposable)

Reuse the M13.3 staging pattern:

1. **`field_definition_revision` table** (proposed | promoted | rejected) carrying the full
   `FieldDef` payload + `discovery_rationale` + `source_evidence` (claim ids) + proposer.
2. **`propose_field` tool** — validates everything `register_field` would (namespace shape, pack ↔
   namespace match, **`reuse_scope` mandatory for `<pack>.*`**, value-schema vocabulary,
   `equality_mode`, corroboration config), stages instead of activating. Idempotent on lineage.
3. **Stop the silent drop:** ICP synthesis captures out-of-bounds field names as proposals and
   surfaces them in the ICP co-confirmation step ("the agent also suggests researching X, Y — add?").
4. **Promotion policy:** human confirm inside ICP review by default; auto-promote allowed by policy
   for non-personal field-classes; `contact.*`/`contact.facet.*`/`sensitive` **always human**
   (Doc D). Promotion calls the existing `register_field` + bumps the ICP spec version so the field
   enters gap planning automatically.
5. Packs stay code-authored for now; a later `pack_definition_revision` can make whole packs
   data-proposable using the same ledger.

### R2 — Loop engineering (the judge-loop / exhaustive research)

1. **Coverage ledger:** extend `re_research_candidate` (or a sibling `research_attempt` table) with
   `attempts`, `last_attempt_at`, `strategies_tried`, `block_reason
   {no_source | below_confidence | conflict | gate_blocked | budget | unresearchable}` — covering
   *never-filled* fields, not just stale ones.
2. **Goal-judge loop** at the M8A composition root: after each account/contact round, recompute
   gaps → escalate strategy per round (skip exhausted sources, try alternate same-tier providers,
   invoke `propose_source`, reformulate queries, spawn facet sub-workers) → stop deterministically
   (`max_rounds` per tier, budget, marginal-yield). Keys: `(account, field, tier, round)`.
3. **Terminal gaps are first-class output:** review surface rows and a dossier "coverage & gaps"
   appendix — "tried Clay, official site, Exa across 3 rounds; not found; reason" — which is the
   *correct* behavior under the empty-is-correct principle and the coverage-confidence output rule.
4. Gate order: land after the deferred verification seams close (PreSpendGate routing,
   identity-binding pre-insert stamp, M9.6 adversarial fixtures) — same order the 2026-06-28 note
   set, because the loop multiplies whatever the gates miss.

### R3 — Research dossier (+ inference layer)

1. **Derived claims:** `claim_derivation(claim_id, derived_from_claim_ids[])` side table (mirror of
   `claim_support`); inferences are tier-4 claims whose "evidence" is *other claims*. The
   faithfulness judge gets an entailment mode: verdict = "is this inference supported by the cited
   claims?"; confidence propagates from supports; an inference citing an unverified claim stays
   unverified. No free-floating expert opinion — the inference layer keeps the provenance bet.
2. **`compose_dossier` tool:** deterministic template (per ICP/industry, config-as-data) + LLM prose
   pass over `AccountHandoff` + inferences, every sentence carrying claim-id citations (footnotes),
   ending with the coverage/gaps appendix and provenance index. Output = markdown (+ optional HTML)
   stored via R5 with the claim-snapshot pinned — a *regenerable view over claims*, never a new
   source of truth.
3. Boundary note (D1): the dossier is still "verified meaning" for the *user reviewing research* —
   it does not encroach on the downstream content layer's artifact-shaped outputs.

### R4 — Raw-material ingestion at Stage 0

1. Upload endpoint → bytes into **StorageBackend** (R5) → `artifact` row (sha256, mime, size,
   storage key).
2. Dispatch by mime through the existing adapter registry; **add `DocxAdapter`, `PptxAdapter`,
   image-OCR**; PDF/audio-transcript (YouTube)/HTML already exist. Adapters emit normalized text
   with **locators** (page / slide / paragraph / timestamp).
3. Existing `ClaimExtractor` seam turns segments into CKB claims: `source_url = upload://{artifact_id}`,
   `evidence_span` = locator + quote — so the faithfulness judge and DSAR erasure work unchanged.
4. Trust: client-provided material **about the client** enters as an authoritative source
   (tier 1–2, `tenant_private`); anything it asserts **about target accounts** caps at tier 3 and
   corroborates normally. Modeled as source-manifest rows (`client_upload_docx`, …) — ingestion is
   *just another resolver family*, per staged-flow §7b.

### R5 — StorageBackend adapter

`core/storage.py` protocol: `put / get / delete / presign_url` (+ content-addressed keys);
implementations `FileSystemStorageBackend` and one **S3-compatible** backend (covers S3, R2, MinIO
via endpoint config); selected in `config/settings.py`; wired at the composition root; `artifact`
metadata table in Postgres. Consumers: R4 uploads, tier-2 scrape snapshots (evidence permanence —
today spans point at live URLs that rot), dossier exports, run-graph exports. **DSAR hook:** M10.5
erasure must cascade to artifacts holding personal data (retention_class on `artifact`).

---

## 4. Opening the source planner (governed, not unbounded)

The founder's instinct is right and fits the existing design: staged-flow §7a is explicitly "open
by construction"; what was never specified is *who* may register a source at runtime. Answer: the
agent — through a gate.

1. **Seed a tier-3 generic-web source** (`web_scrape_generic` / `web_search`) + a tier-3
   **GenericWebResolver** (fetch arbitrary URL → adapter → extractor; no target-lock; evidence-span
   required). This alone gives "web search as a real source", up-weightable **today** per
   (pack, field_class, client) via source-profile overrides — the knob already exists.
2. **`propose_source` tool:** during planning/gap-escalation the agent may search the web and
   nominate a source; the nomination becomes a **draft manifest row** (modality, yields, estimated
   cost, `identity_binding_strength=WEAK`) staged through the `config_revision` ledger.
   **Tier is assigned by policy, never by the LLM:** registry/official-domain patterns → eligible
   tier 2 (human confirm), reputable third party → tier 3 (auto-promotable), else tier 3/4.
   Promotion → `register_source()` (exists) → fetchable via the generic resolver, planned via the
   normal allowed-set intersection.
3. **Invariants preserved:** the per-call planner stays bounded (allowed set = profile ∩ registry);
   the LLM never *is* the source of a fact — it *nominates fetchable places*, whose content then
   flows through the same waterfall, corroboration, faithfulness judging, and identity-binding as
   everything else. Novel domains enter at tier 3 max without a human. The M13.3 source-yield loop
   then measures each new source and reweights/demotes it from evidence.

This resolves the §7d rigidity-vs-fabrication tension at a second level: *bounded at call time,
extensible at registration time.*

---

## 5. Conventions correction (what actually needs fixing)

1. **Keep the import-independence contracts.** They are what make the toolbelt safe (workers
   compose via claims). The survey shows they did **not** cause a waterfall fork.
2. **Unfreeze `core` procedurally:** a lightweight contract-delta lane (small PR + checklist:
   protocol-compatible, enum-parity tests, grep for local copies to replace). The backlog's
   deferred consolidations (`EqualityMode`/`values_agree` → core, `decode_jsonb_scalar`,
   `normalize_host`, `reference_time`) become one batch PR, plus a `BudgetTracker` helper for the
   threading pattern.
3. **`claim_tagger` hook on `resolve_field`** → contact-facet fill rejoins the shared engine.
4. **Rewrite `_conventions.md` §2** with the explicit rule: *shared utilities live in `core` (via
   contract-delta); copying one into a milestone package is a defect; module-specific behavior is
   added by extension hooks/config on the shared engine, never by re-implementation.* Add a review
   gate (a simplification/duplication pass in CI or review checklist) so drift fails loudly.

---

## 6. Build sequence

Ordered to keep every step shippable and nothing regressing; steps 0–2 are the enabling spine.

| # | Work | Why here |
|---|---|---|
| 0 | **Detached `CampaignRunWorker` + per-run driver lease + task drain** (unchanged from 2026-06-28) | Agent sessions must not *be* the worker; prerequisite for everything interactive. De-risk test: kill -9 at 40% of a 500-account run → exactly-once completion. |
| 1 | **StorageBackend + `artifact` table** (R5) | Small, independent; unblocks ingestion, scrape snapshots, dossier storage. |
| 2 | **Toolbelt façade**: typed tool envelope over existing handlers, explicit preconditions (silent-empty → loud errors), `estimate()`, read/projection API + streaming progress endpoint | The platform seam (and later the MCP surface). |
| 3 | **Consolidation pass** (§5): core contract-deltas, `claim_tagger`, `BudgetTracker`, conventions rewrite | Do before new callers so new capabilities don't inherit the debt. |
| 4 | **Coverage ledger + goal-judge loop** (R2) · **`propose_field`** (R1) · **`propose_source` + tier-3 generic web resolver** (§4) · **ingestion** (R4) | The agentic capabilities, each independently shippable behind the toolbelt. Judge-loop lands after the deferred verification seams close. |
| 5 | **Run-graph journal + recipes + durable graph executor**; ship the linear pipeline as Recipe #1; canvas read/pin/re-run contract | Reproducibility plane. |
| 6 | **Deep agent + skills** (`agent/` package behind the import contract from the 2026-06-28 rec: may import the toolbelt façade + projections only; never claimstore-writes/resolvers/gateway) | Orchestration plane last, on top of hardened tools. |
| 7 | **`compose_dossier` + derivation edges** (R3) | Depends on entailment-mode judge; naturally after verification seams. |

Relation to the 2026-06-28 build sequence: 0 = its Phase 0; 2 ≈ its Phases 1–2; 4 ⊇ its Phases 3–5;
5–6 replace its "thin chat agent over the fixed state machine" endpoint with the graph/recipe
model. Its five open founder questions: Q3 (typed-intent ceiling) is now answered — the agent may
edit config-level objects (fields, sources, skills, profiles) **only through propose→promote
ledgers**; Q1 (worker topology scale), Q2 (concurrent-session semantics), Q4 (replan economics
default), Q5 (Stage-0 gating) remain open below.

---

## 7. Decisions needed (with recommended defaults)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Where does the deep agent live — platform repo or here? | Incubate here (`agent/`, import-contracted), design for lift-out; the toolbelt schema is the boundary the platform (incl. the design subsystem's tools) will consume. |
| 2 | Approval posture for agent-proposed fields/sources | Fields: human confirm in ICP review; personal-data classes always human. Sources: auto at tier 3 with audit + yield-based demotion; human for tier ≤ 2. |
| 3 | Dossier ownership | Own it here as a regenerable view over claims (it's "verified meaning" for research review); artifact-shaped content stays downstream (D1 intact). |
| 4 | Replay semantics | Commit to outcome-reproducibility (pinned configs + idempotency + eval floors); do not promise bit-identical LLM output. |
| 5 | Object store | S3-compatible client from day one (covers R2/S3/MinIO); pick the actual provider at deploy time. |
| 6 | Canvas V1 scope | Agent-authors / user-pins-and-re-runs first; free-form user graph authoring later. |
| 7 | Prior open Qs 1, 2, 4, 5 (topology scale, concurrent sessions, replan economics, Stage-0 gate) | Still need founder answers; none block steps 0–3. |

---

## 8. Pre-mortem (top failure modes and their guards)

1. **Agentic loops burn budget** → loop control is deterministic (rounds/budget/marginal-yield),
   spend stays behind the ledger + admission gates; replan economics measured against the
   BacktestGate before default-on (prior note's Q4).
2. **Silent-empty tools mislead the agent** → step 2's loud preconditions are non-negotiable; a
   planner that can't see *why* a tool no-opped will thrash.
3. **Recipe rot** (pinned configs age) → recipes pin versions but declare compatibility (a recipe
   referencing a retired field/source fails validation at load, not mid-run).
4. **Tier laundering via proposed sources** → tier assignment is policy code + human gate above
   tier 3; the LLM never sets trust.
5. **Two sources of truth for "what happened"** → the run-graph journal is written *by the
   toolbelt*, not by the agent; chat narration is a view over it.

---

## 9. Addendum (2026-07-03, round 2) — Stage 0 as a governed interview

Founder pointer: research must be preceded by genuine *client understanding* — the agent asks
questions (client's industry, target industry, ICP requirements, signals the client believes in,
signals the agent proposes), uses CRM connects and materials, and only then researches. Stage 0
must stop being a rigid sequence; agent-files/skill-files steer the conversation.

### 9.1 The unifying move: the interview is a source

Stage 0 already treats client-volunteered materials as a spend-bypassing source
(`stage0/client_kb.py:161–172`). Generalize that: register a **`client_interview` source manifest**
(modality `conversation`) whose *resolver is the chat agent itself*.

- For `client.*` facts, the client is the most authoritative source there is → **tier 1**, ahead of
  web scrape in the waterfall's source order for those fields.
- When the gap planner finds unfilled client/ICP-readiness fields whose best source is
  `client_interview`, the agent *asks* — that's what a waterfall "call" to this source means.
- The answer becomes a normal claim: `source = client_interview`, **evidence span = the verbatim
  quoted user turn + conversation turn ref**, idempotent on `(entity, field, turn)`. The
  faithfulness judge can verify interview claims like any other (value must be entailed by the
  quote) — no agent paraphrase is promotable without the quote behind it.
- **Client hypotheses about the market/targets are not world-facts.** "We sell to hospitals" →
  tier-1 client claim. "Hospitals running Epic churn less" → a **signal proposal** (R1) / ICP
  preference entry tagged `client_stated` — it shapes *what we research*, it never becomes a
  claim about the world without its own evidence.

Interview answers being claims also means later corrections ("actually we now target mid-market")
are ordinary supersedes with version history, and the ICP re-synthesizes from current truth.

### 9.2 Readiness spec replaces phase gate

Deprecate "reverse_profiling then icp_confirmed" as a fixed order; keep the *spend discipline* as a
**readiness spec** (config-as-data, per client/vertical): which field-classes must be covered at
what confidence before (a) ICP synthesis is worth running, (b) discovery may spend, (c) deep
research may spend. Enforced by the existing pre-spend gate machinery; computed by the same
goal-judge gap logic as R2; rendered to the user as "what I still need to learn."

- **How** each gap closes — ask the client / ingest a deck / connect CRM / research the web — is
  the agent's choice per gap, guided by the skill. That is the dynamicism.
- **Minimum-input preserved:** a URL-only client who answers nothing still reaches a confirmed ICP
  — the interview source simply yields nothing, web+materials fill what they can, and readiness is
  met at lower confidence with **flagged assumptions** presented at co-confirmation. Client always
  has the wheel: "just go" is allowed and recorded as an override.

### 9.3 Signals negotiation, interviewing craft, skill files

- **Signals**: client-stated and agent-proposed signals both become registered signal/field
  proposals (`client_stated` vs `agent_proposed` + rationale + evidence), each mapped to its
  two-tier form (cheap Pass-A proxy + deep Pass-B narrative). Co-confirmation shows both lists;
  the M13.3 learning loop later reports discriminating power per signal ("the signal you suggested
  has shown zero lift across 3 campaigns — drop it?").
- **Interview craft lives in the Stage-0 skill file**, not code: lead with what was already
  inferred ("here's what I learned from your site and CRM — correct me"), ask only gaps, confirm
  rather than interrogate, offer the CRM connect early (won/lost deals are the strongest lookalike
  seeds), time-box, escalate to synthesis when readiness is met.
- **Skill file shape** (the founder's "agent-files and skill files"): a versioned bundle —
  frontmatter (name, version, allowed tools, readiness-spec ref, per-vertical overlays) + prompt
  body — stored and promoted through the `config_revision` ledger like every other policy object;
  recipes pin skill versions. We ship defaults; per-client overlays are data, not forks.

**What survives:** the CKB waterfall fill, volunteered-material bypass, ICP synthesis, versioned
`icp_spec` + co-confirmation — all as tools. **What dies:** the fixed handler sequence as the only
path through them. **Build placement:** interview source + readiness spec land in step 4; the skill
registry lands with step 6 (a minimal loader for the Stage-0 skill may come earlier).

### 9.4 Eager preliminary recon (round-3 clarification: research starts at URL submission)

Founder clarification: when the client provides company name + URL (signup/onboarding), the
web/agent part of client research should start **in the background immediately** — so that by the
time the user opens chat, the deep agent already has context and asks *better* questions.

- **The recon run is just reverse-profiling, repackaged as a small background recipe** ("Recipe
  #0"), executed by the same detached worker with a **small hard budget envelope**, tiers 1–3 only
  (website scrape, official sources, reputable third-party) + light synthesis for the brief — no
  expensive tier-4 fan-out before the client has confirmed any direction. Spend follows commitment.
- **Two-speed:** a fast pass (client's own site + obvious official sources — seconds to minutes) so
  the agent has *something* if the user arrives immediately; the deeper pass continues in
  background. Neither blocks the other: recon and interview both write the same CKB, so the agent's
  context improves mid-conversation — the narrator can surface "just found your case-study page —
  looks like you sell mostly to mid-market logistics; is that right?" as claims arrive.
- **Output = a recon brief** (a miniature of R3's `compose_dossier`: what we learned, with
  provenance) **+ the gap list that seeds the interview.** The agent opens with the brief
  ("here's what I learned about you — correct me"), not with a blank questionnaire.
- **Discrepancy craft:** recon claim vs user statement conflicts are flagged by the existing
  corroborator; client-about-self (tier 1) outranks web, but the agent *confirms conversationally*
  ("your site says ~200 employees, you said 450 — recent growth?") rather than silently
  overwriting. Freshness TTLs cover the user who signs up, disappears, and returns weeks later.
- **Cost/abuse guards:** domain-keyed dedupe + per-signup envelope. Note the amortization win:
  recon claims about a company are `public_footprint` — the M6 reuse-scope machinery means a
  second tenant recon-ing the same domain largely reuses them.

### 9.5 Client memory: two layers (structured claims + preferences)

Founder clarification: during the session the agent must record facts the user states —
structured *or* unstructured — and keep the user's preferences in memory.

- **Layer 1 — facts about the client → the CKB.** If the statement maps to a registered field →
  structured claim (§9.1: verbatim-quote span, idempotent). If not → a **`volunteered_statement`**
  record (utterance, turn ref, topic tags) with two promotion paths: map it to a field later, or
  let it trigger `propose_field` (R1) when it looks like a recurring researchable aspect. Nothing
  the user says is dropped just because the registry didn't anticipate it.
- **Layer 2 — operating preferences → a `client_memory` store, not the claim store.** "Never
  target our competitors' customers," "our CEO hates the word 'synergy'," tone/exclusion/priority
  constraints — these are *instructions about how to operate*, not facts about the world. They
  live in a per-client memory the **skills read at prompt-assembly time**, versioned lightly
  (append + supersede), each entry carrying the quote that created it.
- Claude Code analogue (§10.4 extended): claim store ≈ the codebase; `client_memory` ≈
  `CLAUDE.md`/auto-memory; the recon brief ≈ the repo map an agent builds before its first edit.

### 9.6 CRM demoted to optional accelerator (never a prerequisite)

Founder constraint: new clients will rarely trust a new platform with CRM OAuth, so nothing may
depend on it. Consequences:

- The **readiness spec must be satisfiable from URL + interview + uploads alone.**
- Trust-light seed paths come first in the skill's craft: "name your 5–10 best customers" in
  conversation (the import scenario already handles messy free-text), pasted lists, **CSV export
  upload** (client exports their own CRM — far lower trust bar than OAuth, and R4 ingestion
  handles the file).
- OAuth CRM connect is offered *after value is proven* (e.g., post-first-campaign, when the M13.3
  learning loop can also use outcomes) — an accelerator for lookalike seeding, never a pillar.

**Build placement update:** Recipe #0 (recon) is tiny and early — it exercises step 0 (detached
worker) + step 2 (projections/narrator) on a real, low-risk workload before any fleet runs;
`volunteered_statement` + `client_memory` are small step-4 components alongside the interview
source.

---

## 10. Addendum (2026-07-03, round 2) — fleet scale, runtime supervision, live visibility

Founder pointer: how does an agent-native platform run 100–500 account researches without producing
crap, when no human can watch 50+ parallel researches — and how does the chat surface let the user
glimpse overall or per-account activity mid-run?

### 10.1 Topology — 500 accounts is queue depth, not 500 chat agents

- **Chat deep agent** = control plane. Session-scoped, conversational. Plans, launches, steers,
  answers questions. Never executes research in-session.
- **Detached `CampaignRunWorker`** (one per run; build step 0) = fleet driver. Pulls account jobs
  off a tier-priority queue under a concurrency window (~16–32 in flight), per-account budget
  envelopes, per-source rate limits (M2 token bucket), budget admission per job. Tier order means
  if budget exhausts, the *best* accounts got researched — the "never uniform deep research"
  principle operationalized.
- **Per-account M8A orchestrator graph** (exists) = the worker. Lead plans gap-fields, spawns
  bounded aspect/facet workers, checkpointed (LangGraph + `AsyncPostgresSaver`), idempotent on
  `(account, field, tier[, round])`, resumable after any crash.

Wall-clock scales with the concurrency window; cost is capped by envelopes + the campaign cap;
nothing about scale is conversational.

### 10.2 Quality without human eyes — the five-layer pyramid

1. **Hard determinism, every step (free, always-on):** fan-out/depth caps as runtime limits,
   per-account envelopes, pre-spend gates, target-lock, existence gates, stop-at-confident.
   "Unbounded generation in the wrong direction" is structurally impossible — a worker cannot
   exceed depth, cannot outspend its envelope, and **cannot promote an unsourced claim**.
2. **Per-claim LLM judgment, 100% of outputs (exists):** faithfulness judge, corroboration,
   identity binding, appropriateness/use gate. Crap can be *produced*; it cannot be *promoted*.
3. **Per-account goal-judge at round boundaries (R2):** coverage + verification health → another
   round / stop / flag. This is the per-research-unit "judged and steered at runtime."
4. **Run supervisor (new component):** the founder's "orchestrator keeping an eye" — but it reviews
   **signals, not transcripts**, which is what makes 500 viable. Deterministic monitors run
   continuously over aggregates: per-account verification health (judge-failure and conflict
   rates), gap ratio, spend-vs-yield, stall/latency, per-source error rates. Anomalies get periodic
   LLM triage (batch-diagnose similar failures). Its actions are bounded and journaled: quarantine
   an account (pause its graph, not the run), trip a source circuit breaker run-wide, tighten an
   envelope, escalate to the human *with a diagnosis*.
5. **Human = exceptions + canary + ranked review (M13.1) + samples.** Never 500 transcripts.

**Why not LLM-judging every worker turn:** prohibitive at fleet scale and redundant — intermediate
wandering cannot corrupt state (layer 1–2); worst case is bounded wasted spend inside one envelope,
which layer 4's yield monitor catches. Judge **outputs** always, **trajectories** at round
boundaries, **aggregates** continuously, **transcripts** by sample (M9.6 evals).

**Canary default (recommend in Recipe #1):** open with the top-tier ~10 accounts → supervisor
health gate (verification health ≥ floor, yield sane) → open the fleet. "Produce 10, judge, then
500" beats discovering systemic crap at account #480.

### 10.3 Live visibility — the chat glimpse

All the state already lands in Postgres (LangGraph checkpoints, `sub_phase` rows, gate decisions,
budget ledger, claims, spans). What's missing is packaging (build step 2):

- **Projection API:** `run_overview()` (accounts by state, burn-down, verification health, ETA),
  `account_progress(account)` (current node/round, fields filled vs planned, spend, flags, latest
  claims), `explain_flag(...)`. Chat answers "how's Acme going?" by *reading projections* — MVCC
  snapshot reads, never interrupting workers.
- **Narrator event stream:** outbox → SSE of run events (account started, aspect done, claim
  flagged, round judged, checkpoint reached); the chat agent renders periodic digests ("142/500
  scored · deep running on 38 · 3 flagged for conflicting revenue") with drill-down on demand —
  the diagram's pink "streams summaries like Claude Code" note, without spamming the chat.
- **Steering mid-run:** pause/resume account or run, reprioritize, add/remove fields, tighten
  budget, kill a source — the campaign machine's PAUSED/adjust semantics exposed as tools
  (destructive ones behind confirm gates).
- **Sessions are decoupled from runs:** the run lives in the detached worker; chat can close and
  reattach later — or a *different* teammate can attach — via the same projections. (Single-writer
  lease per run stays; readers are unlimited. Prior open Q2.)

### 10.4 The Claude Code correspondence (founder's observation — adopted as the mental model)

The platform is, deliberately, a **Claude-Code-shaped harness whose "filesystem" is the claim store
and whose "skills" are ABM playbooks**:

| Clue-HQ | Claude Code analogue |
|---|---|
| Chat deep agent | Interactive session |
| Toolbelt (typed, precondition-checked) | Tool registry |
| Agent-files + skill files (versioned config) | `CLAUDE.md` + skills |
| Per-account orchestrator graphs | Subagents (Task tool) |
| Detached run + supervisor + narrator digests | Background tasks + task notifications |
| Projections / `account_progress` | Task output + transcript inspection |
| Recipes (pinned run graphs) | Saved workflows |
| Confirm gates on destructive/spendy ops | Permission modes + hooks |
| Toolbelt-as-MCP (later) | MCP |

**Deliberate divergences** (where a coding harness would be the wrong thing to copy): the substrate
is a typed-claim database with provenance, not a filesystem — writes pass hard domain gates
(evidence spans, tiers, budget ledger, compliance) that no prompt can vibe past; runs are durable,
multi-tenant, and outlive sessions (detached worker, not in-session subagents); and reproducibility
is contractual (recipes + pinned config versions + eval floors), not incidental. Claude Code trusts
the developer to review diffs; Clue-HQ cannot assume a reviewer per account — that is exactly why
layers 1–4 of §10.2 exist.

---

## 11. Addendum (2026-07-06) — decisions after the co-founder plan-pack review + additive contract gaps

Context: the co-founder's product/frontend pack (`~/Downloads/plan`, 13 docs; binding artifact =
`08-backend-contract.md`, "the treaty"; the frontend builds entirely against MSW mocks of it). The
full comparison lives in `_memory/2026-07-06-cofounder-plan-pack-comparison.md`. Verdict there: the
pack *is* this proposal's harness pivot at platform level (Head-of-ABM supervisor + typed skills +
recipes + constrained composition + canvas ≈ planes 2–4; it also settles §7 decision 1 — the deep
agent lives at platform level, and this subsystem is the research capability provider behind the
treaty). Five mismatches were flagged; the founder resolved all five below.

**Standing rule for integration: nothing already planned or built in this subsystem is deleted or
weakened. All frontend-driven work is additive.**

### 11.1 Resolved decisions

| # | Mismatch flagged | Founder decision (2026-07-06) |
|---|---|---|
| 1 | Two-pass economics inverted — the pack's `full-campaign` recipe runs uniform deep research per account, then scores; tier gates package richness, not research depth | **Our principle prevails.** Pass A cheap scoring on all accounts → human tier checkpoint → Pass B deep research on high tiers only. Recipe order to be corrected at treaty review. Per-product fit becomes two-stage: provisional from Pass-A enrichment (FitModel already weights schema variables), final evidence-linked score recomputed from deep research for high tiers (the pack's 72/68/40 fixture bar applies to the final score). |
| 2, 3 | Stage 0 — the pack's Lock 6 reads as one-shot confirm-once onboarding | **Stage-0 design stands unchanged**: eager recon (Recipe #0, §9.4) + gap-driven interview-as-source (§9.1) + readiness spec (§9.2) + ICP re-synthesis. The frontend docs slightly misunderstood it. Lock 6 is honored as "one *scrape* pass" (recon dedupe/cost control), not "client understanding complete after one confirm." Additive onboarding flow adopted — §11.2. |
| 4 | Verification as a pipeline step / quality dial (pack: `claim.verify` node post-synthesis; Draft mode = link-alive check only) | **Verifiability stays a property of the data model — nothing in the backend changes.** The `claim.verify`/`fabrication.audit` node is adopted as an *additive visible re-check surface* over the existing substrate (M9 judging, corroboration, identity binding). Quality modes may vary breadth/variants/corroboration hunting — never the promotion bar; substrate invariants are mode-independent. |
| 5 | Personal-data governance thin (pack: a two-level `use_with_care` flag + cringe.check) | **M10 / Doc D proceeds exactly as planned — no compromise.** Jurisdiction switch, use-classes, sensitive-excluded-by-default, retention, DSAR remain the mechanism; the pack's `sensitivity: use_with_care` becomes a *projection* of use-class + client posture (US-permissive posture + per-use human confirm ≈ one policy configuration). Frontend is a skin and still in process. |

### 11.2 Onboarding flow refinement (additive; founder sketches 2026-07-06)

Three beats, each mapping onto machinery already in this proposal:

1. **URL submission → ingestion with real progress.** The UI ticks off *real* backend events —
   website scrape, knowledge-base scrape, brand guide, brand voice, ICP-intent understanding,
   value-prop extraction — ending in a brand "theme complete" beat. This is Recipe #0's two-speed
   recon made visible (fast pass drives the checklist; deep pass continues in background); brand-kit
   extraction is the design-side share of the same recon run. Consequence: recon must emit events
   granular enough for 1:1 checklist ticks (the pack's own "no fake progress" acceptance criterion).
2. **"How do you wanna get started" fork.** Card A — **"Surprise me"**: shows what recon already
   knows (ICP persona bullets, candidate accounts to reach, negative winners, "all the things we
   have context about") plus an "add more to the list" free-text input; this is the recon brief +
   gap list projected as a card, and it is the *discovery* entry scenario. Card B — **"I know my
   account"**: named target account(s) → deep research + collaterals; the *import* entry scenario.
   Both entries stay first-class and symmetric (existing principle).
3. **Either card lands in the chat interface** (confetti, first-credits moment) — and the
   **interview-as-source runs right there**: the agent opens from the recon brief ("correct me"),
   asks gap-driven questions, records facts as tier-1 claims (evidence span = verbatim quoted
   turn), preferences to `client_memory`, signal proposals tagged `client_stated`/`agent_proposed`;
   the readiness spec — not the screen order — gates when synthesis/discovery/deep may spend; the
   ICP re-synthesizes as the client corrects themselves.

### 11.3 Additive gaps — work to serve the frontend treaty (delete nothing)

**Group A — projection/serving surfaces this subsystem adds** (backend internals unchanged; these
are views and adapters over the existing substrate):

1. **Dossier block projection.** `compose_dossier` (R3) gains a `blocks` output in the pack's
   9-block vocabulary (metric, claim, score, qualifier, contact_card, evidence_list, narrative,
   feasibility_note, table) shaped by a per-brand DossierSchema. The dossier remains a regenerable
   view over claims (§7 decision 3 intact); dossier "versions"/refresh diffs are snapshots with
   claim supersede/merge underneath; block actions map onto claim-store ops (challenge claim →
   re-verify; refresh section → scoped re-research; exclude-from-artifacts → claim flag).
2. **Per-product fit dimension** on the scoring seam: FitScore keyed `(account × product)` with
   claim-id evidence refs, product qualifiers hard-gating, and `tier_recommendation`; two-stage per
   decision 1. Reserved `account.scoring.fit`/`.intent` fields stay; product-keyed additions only.
3. **Contact-class vocabulary.** Pack-registered per-workspace `contact_class` (e.g.
   clinical/business) emitted *alongside* the fixed committee personas — `(account, persona)` keys
   unchanged; the vocabulary is registered, not enumerated (field-registry philosophy).
4. **Run-manifest projection + mutation ops.** Project the campaign-run machine + per-account
   graphs into the treaty's manifest shape (`node_key`, `depends_on`, `status`, `account_scope`,
   `gate`, `quality_mode`, `est_cost`) and accept `PATCH …/manifest` ops (add/remove/
   set_dependencies/update_config/set_quality) with `expected_seq` optimistic concurrency;
   validation loud (extends step 2's loud-preconditions rule to plan edits).
5. **SSE per treaty §5.** The §10.3 narrator/outbox design pinned to the treaty vocabulary: exact
   envelope (`id`/`ts`/`type`/`refs`/`data.seq`), per-workspace ordering, at-least-once with seq
   idempotence, `Last-Event-ID` replay (≥24h / 10k events), single-use stream tokens, topics,
   `stream.hello`/`stream.reset`.
6. **`timeline_phase` emission.** Map worker/tracing states → thinking/reading/grepping/editing/
   done for `run.step.progress` and inspector timelines.
7. **Millicredit ledger with holds.** Client-facing integer-millicredit layer over the USD cost
   ledger (M13.4): debit/credit/grant/adjustment/hold/hold_release + `balance_after`; hold on run
   start, release/true-up at completion; 402 semantics; pause at 120% of estimate (maps onto the
   existing budget envelopes).
8. **Quality-mode mapping.** Draft/Standard/Best resolved server-side per tool into existing knobs
   (fan-out caps, model tier, variant count, corroboration breadth, retry budget). Hard rule from
   decision 4: modes never touch promotion/verification invariants.
9. **HTTP `Idempotency-Key` store** (24h key+response; 409 on same-key-different-body) on mutating
   endpoints — additive over the existing domain idempotency keys.
10. **Batch re-verification tool** (the pack's `claim.verify` node) + fabrication-audit rollup:
    re-open snapshot/source, quote-match, re-grade; emit `VerificationReport` {claims_checked,
    links_opened/working, items_flagged} and per-contact audit chips — computed from existing
    verification machinery + StorageBackend snapshots. Substrate judging unchanged.

**Group B — treaty additions to propose** (additive-only PRs against `08-backend-contract.md`;
inputs to its own "Treaty Review Agenda"):

11. **Richer verification fields** (optional, additive) on claim/provenance wire shapes: trust
    tier, corroboration/conflict flag, faithfulness verdict, identity-binding strength, use-class.
    `verified: boolean` stays as the coarse rollup; the UI can then render conflicts and review
    reasons it currently has no vocabulary for.
12. **Verification-review queue kind.** M13.1 ranked review rows feed queue items (new
    `queue_item.kind` or a subject-ref'd `review`); M13.2 dispositions flow back.
13. **Coverage & gaps surface.** Per-account attempt ledger (field, strategies tried, rounds, block
    reason) on the dossier ("coverage & gaps" appendix) and run projections — R2's terminal gaps as
    first-class output.
14. **Compliance surfaces reserved in the contract.** Per-client jurisdiction/posture config,
    use-class on personal claims (the pack's `sensitivity` maps to it), DSAR erase/export
    endpoints. Even if the V1 UI does not skin them, the treaty reserves them so nothing downstream
    is designed against their absence.
15. **Raw-material ingestion (R4) endpoints.** Upload → ingest-to-claims for docx/pptx/pdf/images/
    URLs/video; a source-manifest row per upload; trust policy (client-about-self = tier 1–2
    tenant-private; assertions about targets cap at tier 3). Frontend hook: composer "@ → Upload
    file…".
16. **`propose_field` / `propose_source` surfacing.** `field_definition_revision` proposals surface
    at co-confirmation (brief chips) and via `schema_change`-style gates mid-research;
    `propose_source` per §4 (tier assigned by policy, never by the LLM).
17. **Recipe-spine correction** (decision 1): tier checkpoint + budget-approval gates inserted in
    the `full-campaign` recipe between Pass A and deep research; the Grid/Flow lenses render the
    two passes. A sequencing change in the pack's docs, not a backend change.

### 11.4 Build-sequence placement (§6 unchanged; additions slot in)

- **Step 2** (toolbelt + projections + streaming) absorbs A4 (manifest projection/ops), A5 (SSE per
  treaty), A6 (phases), A9 (idempotency store), and the "Surprise me" readiness/coverage
  projection.
- **Steps 1–2 + M13.4** absorb A7 (millicredits).
- **Step 4** absorbs B13 (coverage surface, R2), B15 (ingestion, R4), B16 (propose_field/source,
  R1/§4), and the interview-flow anchors (§9 / §11.2).
- **Step 7** absorbs A1 (dossier block projection — R3's output shape) and A10 (re-verification
  tool; after the verification seams close).
- A2 (per-product fit) and A3 (contact-class) are spec-level deltas on the scoring/committee seams;
  schedule alongside the M12/handoff-adjacent work.
- A8 (quality modes) is config-as-data on the toolbelt envelope — a step-2 schema slot whose
  per-tool mappings fill in as tools land.
- Group B items are treaty PRs; sequence them at the first treaty review pass (the pack's
  `00-master-plan.md` §8 open item).
