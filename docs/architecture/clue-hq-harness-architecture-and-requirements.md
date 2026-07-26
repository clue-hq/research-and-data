# Clue-HQ Research Subsystem — Harness Architecture & Requirements

> **Status: CONFIRMED design record** (v1.2, 2026-07-16 · v1.1, 2026-07-11 · v1.0, 2026-07-06). This document consolidates the harness
> re-platform proposal (`clue-hq-harness-replatform-proposal.md` §1–§11) with the founder decisions
> of 2026-07-03 → 2026-07-06 (rounds 1–3 of the harness discussion, plus the co-founder plan-pack
> review) into one complete statement of the subsystem's requirements, architecture, and plan.
>
> **v1.1 (2026-07-11) — product-surface revision.** The founders retired the node-based canvas as a
> product surface in favor of an **agent-workspace UX** (inspired by Hyperagent): an agent registry
> of configurable platform agents, orchestrator-led composition, and run/activity/recipe-library
> views, on one surface humans and agents share. The substrate, the four planes, and every v1.0
> requirement stand. Changes: REQ-12 and Plane 4 re-expressed (journal/recipes unchanged; canvas
> rendering retired), REQ-16 A4's consumer reframed, REQ-17's canvas-op item retired, and
> REQ-18–REQ-20 added (agent registry & profiles, sub-agent delegation contract, human–agent
> parity).
>
> **v1.2 (2026-07-16) — workspace shell, product continuity, and the agentic-schema split.**
> Founder rulings: every thread is fronted by the platform deepagent only (specialists are
> sub-agents whose outputs persist in the thread; the design editor is the one surface-bound
> exception); project ⊃ campaigns terminology (§1a); the research tab is block-actions-only
> (edits go through the fact store); the v1 personalization unit is both account- and
> contact-level; Stage 0 gains product-profile continuity. Changes: REQ-21 (workspace shell) and
> REQ-22 (product profiles) added; REQ-08 gains a product hook; O11 flagged. Two peer docs join
> the set and carry the detail: **Doc A** (`clue-hq-platform-agent-runtime.md` — the binding
> agentic taxonomy and context-assembly pipeline) and **Doc S**
> (`clue-hq-content-and-artifact-scaling.md` — content plane, template finalization, scaled
> derivation; resolves overview D2).
>
> **Authority.** For the *harness-era* design this document is authoritative. The proposal doc
> remains the analysis/evidence trail (code survey with file:line findings, pre-mortem, addenda
> history). The original doc set (overview, research-layer, staged-flow, Stage-0, signal/cost,
> compliance) remains authoritative for the substrate it describes — nothing in this document
> weakens or replaces it; this document describes what is **added around** that substrate and how
> its shape of execution changes. Where this document says "unchanged," the older doc governs.
>
> **Reading map.** Part I — context and the invariants we inherit. Part II — the twenty-two
> requirements, each with rationale, design, current-state delta, plan, and acceptance criteria.
> Part III — the architecture in detail (four planes, data/config model, runtime topology,
> external interfaces, the Stage-0 walkthrough). Part IV — build sequence, decisions register,
> pre-mortem, non-goals, cross-references.

---

## Part I — Context

### 1. What this subsystem is, and where it now sits

The overall product (working name **Clue**) is an AI-native, agentic ABM execution platform:
account list in → verified dossier → approved angle → per-account artifact packages (print, ads,
landing pages, email) → activation and attribution-lite out, orchestrated by a platform-level
**Head-of-ABM supervisor agent** under human approval gates.

This repository is the platform's **data & research subsystem**: the trustworthy data layer that
turns a client's ICP into a prioritized, deeply-researched, *verifiable* view of target accounts
and their buying committees. Everything downstream — angles, copy, design, artifacts — consumes
what this subsystem produces and never does its own web research (the "downstream sufficiency"
rule both sides of the company independently arrived at).

**Division of labor** (per the co-founder's plan pack, `~/Downloads/plan/00-master-plan.md`):

| Owner | Domain | Binding artifact |
|---|---|---|
| Shank (frontend/product) | Product, design, the Next.js app; builds entirely against mocks | The plan pack + `08-backend-contract.md` |
| Aryan (backend/agents) | Backend + agent runtime — this repository and its siblings | `08-backend-contract.md` ("the treaty") |

**What changed with the harness pivot.** The subsystem was originally packaged as a linear
pipeline (a sequential campaign state machine:
`reverse_profiling → icp_confirmed → discovery → scoring → tier_checkpoint(human) → deep →
verification → handoff`). The 2026-07 discussions established that the *platform* is a deep-agent
harness — modular capabilities exposed as tools, workflow order dynamic per team, agents steered
by versioned skills, run-graph journaling for reproducibility. The five-way code survey
(proposal §2) confirmed this is a **re-packaging, not a rewrite**: verifiability, budget,
compliance, and idempotency live in the data model and gates, not in the phase order; every phase
handler is already near-tool-shaped; the linear pipeline survives verbatim as **Recipe #1** so
nothing regresses while agency is added.

**What did not change.** The substrate (claim store, identity resolution, field registry + packs,
source waterfall, verification, compliance, scoring, cost governance, durable execution) is kept
in full. The 2026-07-06 review of the co-founder's plan pack resolved five potential mismatches
**in favor of this subsystem's existing principles** (two-pass economics, Stage-0 design,
verification-as-substrate, M10 compliance) with a standing rule: **nothing already planned or
built here is deleted or weakened; all frontend-driven work is additive** (§ REQ-16/REQ-17,
proposal §11).

### 1a. Terminology update (2026-07-16): project ⊃ campaigns

**Project** = one end-to-end ABM motion — what this document and the substrate docs historically
call a "campaign" (campaign_run, campaign-scoped ICP, Doc M's campaign scope all map to
*project*). **Campaign** now means a channel program *within* a project (the mailer drop, the
LinkedIn ads campaign, the micro-site campaign). One workspace → many projects → each project →
multiple channel campaigns → artifacts. New documents (Doc A, Doc S) use the new vocabulary;
existing docs retain the historical term until their own revision — readers map "campaign" →
"project" when reading pre-v1.2 text. A mechanical rename across docs/schema is deliberately
deferred to avoid churning built substrate identifiers. **Update (2026-07-22): the mechanical
`campaign_run` → `project_run` rename landed** (stage 1 on the fleet lane; stage 2 — schema,
code, and the empty-allowlist guard — immediately after Phase-B integration, per
`docs/specs/PB-rename-campaign-run-to-project-run.md`). Bare "campaign" remains the
channel-program concept; the frozen `IdempotencyScope` ledger *value* `"campaign_phase"` is
durable data and deliberately unrenamed.

### 2. Inherited invariants (restated as binding)

#### 2.1 The four required outputs (the output-first spine)

Every component exists to produce exactly four things; a component that serves none of them is
overhead.

1. **Scored, ICP-fit account list** — every candidate (discovered or imported) carries fit and
   intent scores, the cheap deterministic signals behind them, and a provenance link behind every
   signal. No score without its evidence. *(Harness-era refinement: fit is additionally keyed per
   product and staged provisional → final — REQ-13.)*
2. **Verified, fully-sourced account profile** per high-tier account — operational pain, strategic
   moves, and the resonance layer, each claim target-locked and backed by an evidence span, or
   left blank.
3. **A buying committee** per high-tier account — champion / economic buyer / technical evaluator /
   blocker, identity-resolved, persona-tagged, governed (identity-binding strength + use-class on
   every personal claim). *(Harness-era refinement: a per-workspace `contact_class` vocabulary is
   emitted alongside the fixed personas — REQ-16.)*
4. **A persona-keyed, evidence-backed claim bundle + grounded value narrative** — facts plus the
   argument, per persona, sourced on both sides (account evidence × client capability).
   *(Harness-era refinement: rendered additionally as a human-readable dossier with an inference
   layer and a typed block projection — REQ-05, REQ-16.)*

#### 2.2 The output contract (the D1 boundary, now concretized)

Three output layers: **raw claims** and the **value narrative** are owned here; the **content
schema / content** (artifact-shaped output) is owned downstream. The harness era adds a concrete
boundary artifact: the **dossier block projection** (nine typed block kinds per the treaty —
metric, claim, score, qualifier, contact_card, evidence_list, narrative, feasibility_note, table),
which is a *regenerable view over claims*, owned here, and is what downstream renderers and the
design subsystem ingest. Research still stops at verified meaning; the block grammar is the wire
shape of that meaning, not a move of ownership.

#### 2.3 The core bet

**Verifiability is a property of the data model, not a QA step bolted on at the end.** The atomic
unit is a typed claim with provenance (value + source + evidence span + tier + confidence +
freshness), never a free-text dossier. "Research" is the act of producing, corroborating, and
scoring claims. A prior prototype did the opposite and shipped fabricated facts; we do not repeat
that. *(Confirmed unchanged on 2026-07-06 — REQ-14.)*

#### 2.4 Principles / non-negotiables (all carried forward)

- LLM research is the **least-trusted** source: tier 4, runs last, fills only what no
  deterministic/official source can answer.
- A claim with **no evidence span cannot be promoted**. Empty-and-flagged is a correct output;
  fabrication is the only real failure.
- A personal claim drives outreach only if it clears **both** gates: strong identity-binding and an
  allowed use-class for its jurisdiction under the client's policy.
- **Design for the strict (GDPR-grade) case and switch down**; `sensitive` data excluded from
  outreach by default; lighter regimes are a relaxation of the same machinery.
- **Minimum-input, client-always-has-the-wheel** — URL-only clients still reach a confirmed ICP
  and a running job; the platform suggests, the client confirms/edits/pauses/adjusts.
- **One constrained orchestrator/worker** — not a mega-agent, not a brittle hardcoded workflow;
  prefer giving workers tools over over-prompting them.
- **Never run uniform deep research on the whole list** — two passes, tier-gated depth, hard
  budget caps. *(Reaffirmed against the plan pack on 2026-07-06 — REQ-13.)*
- **Account-level data is insufficient** — the contact graph and persona keys are built here.
- **Scores and facts are provenance-backed and explainable**; that traceability is the
  differentiator and what makes DSAR erasure tractable.
- **Coverage confidence, not a completeness guarantee** — report estimated coverage and name the
  unsearched channels.
- **Postgres is the only source of truth.** No external tool sits in the write path.
- **Build the substrate before the agents.** (Done: the substrate is M0–M13; the agents are the
  harness era.)

#### 2.5 The iron rule and the authority boundary

**The LLM proposes; the engine disposes.** The agent (platform supervisor, in-repo deep agent,
aspect workers) gains authority over *which tools, in what order, with what parameters*. It never
gains authority over the rows below:

| Authority | Holder | Mechanism |
|---|---|---|
| Fan-out size / recursion depth | Engine | Per-tier caps as runtime limits, not prompt guidance |
| Spend | Engine + human | Budget envelopes, pre-spend gates, admission control, credit holds |
| Trust tier of a source | Policy code + human | `propose_source` stages a draft; tier assigned by policy (≤3 auto with audit, ≤2 human) |
| Gate bypass | Nobody | Gate closure validated at plan compile time, not runtime |
| Claim promotion | Engine | Evidence-span requirement, faithfulness judge, corroboration, binding + use gates |
| Config mutation (fields, sources, skills, profiles) | Ledgered | Only through propose → promote ledgers (`config_revision` pattern) |
| Verification depth floor | Engine | Quality modes vary breadth/variants, never the promotion bar (REQ-14) |

---

## Part II — Requirements

Each requirement below states: **Requirement** (what must be true), **Rationale** (why),
**Design** (how), **Current state → delta** (what exists vs. what is new), **Plan** (which build
step, Part IV §9), and **Acceptance criteria**.

---

### REQ-01 — Non-linear, harness-shaped execution

**Requirement.** ABM execution must not be restricted by a fixed stage order. Teams differ in how
they run ABM (research-first, design-first, content-first, back-and-forth edits across scaled
artifacts); the individual capabilities stay the same while the flow between them varies per team
and per campaign. The research subsystem must therefore expose its capabilities as composable,
independently-invokable units, not as phases of one hardcoded workflow.

**Rationale.** Research is inherently non-linear — it rarely proceeds correctly in one pass. The
founder's platform-level clarification (2026-07-03): the platform is a deep-agent/harness product;
"the individual general components remain the same, only the workflows remain dynamic."

**Design.** Every research capability becomes a **typed tool** over the existing module (the
capability plane, §4.2): CKB fill, ICP synthesis, co-confirmation, discovery, import, Pass-A
scoring, tier assignment, per-account deep research, committee resolution, verification passes,
narrative/dossier composition, handoff. Tools are invokable in any order; safety comes from the
substrate (claims, gates, budgets), **loud preconditions** (a tool whose prerequisites are unmet
fails with `PreconditionFailed` and a machine-readable reason — never a silent empty result), and
gate-tools placeable anywhere in a plan. The current pipeline ships as **Recipe #1**, so the
linear flow remains available verbatim.

**Current state → delta.** Phase handlers are near-tool-shaped already;
`AccountDeepOrchestrator.run_one` is standalone-ready. The delta is the tool envelope (schema,
preconditions, `estimate()`, journaling) and converting today's silent-empty out-of-order behavior
(e.g. DEEP with no tier cutoffs → empty set) into loud errors.

**Plan.** Build step 2 (toolbelt façade + loud preconditions), step 5 (recipes).

**Acceptance criteria.**
- Every capability listed above is invokable through the toolbelt with a typed request/response.
- Invoking any tool out of order yields `PreconditionFailed` with the missing prerequisite named —
  verified by a test matrix over (tool × missing-prereq).
- Recipe #1 reproduces the current pipeline end-to-end with unchanged outputs on the golden set.

---

### REQ-02 — Bounded agency ("agency guided by well-defined prompts and skills")

**Requirement.** Agents plan and adapt (which tools, what order, what parameters, which gaps to
chase), guided by versioned prompt/skill bundles — but every safety-relevant decision remains with
the engine or a human (the authority boundary, §2.5).

**Rationale.** Quality research needs agency; fabricated research came from *unbounded* agency.
The design keeps the creative loop open and the failure modes structurally closed.

**Design.** The orchestration plane (§4.3): a deep agent compiles intent into **plan graphs over
the toolbelt**; **skills are versioned resources/config, not code** — prompt + policy bundles with
frontmatter (tool allowlist, readiness-spec reference, per-vertical/client overlays) and a prompt
body. Per the 2026-07-26 C6 ruling, V1 canonical bodies live in the reviewed folder catalog and
are pinned by exact version + digest; `config_revision` may ledger promotion metadata/profile
bindings but does not store the bodies. Plan validation enforces: registry-only nodes,
type-checked edges, DAG with declared bounded loops only, gate closure (no path externalizes
ungated), cost estimation before approval.

**Current state → delta.** `config_revision` ledger exists (M13.3). Delta: the skill loader, the
`agent/` package (import-contracted: may import the toolbelt façade + projections only; never
claim-store writes, resolvers, or the gateway directly), plan-graph compiler + validator.

**Plan.** Step 6 (deep agent + skills); a minimal skill loader may land early for Stage 0 (step 4).

**Acceptance criteria.**
- A plan containing an ungated externalizing path is rejected at validation, not at runtime.
- Skills resolve through the versioned folder catalog; a run journal records their exact versions
  and content digests.
- Import-linter contracts prove `agent/` cannot reach claim-store writes or provider SDKs.
- No prompt content can alter fan-out caps, spend ceilings, tiers, or gates (attempted-override
  tests in the eval battery).

---

### REQ-03 — Dynamic field registration (LLM-proposable)

**Requirement.** New research fields/aspects discovered at any point — Stage-0 ICP synthesis, the
interview, mid-research — must be registrable without code changes, including by the agent itself,
under an approval posture.

**Rationale.** Founder requirement #1. Industries and ICPs surface aspects no pack anticipated;
dropping them silently loses signal the client explicitly cares about.

**Design.** The field registry stays open-by-registration (`register_field()` exists with full
validation). Add a **`field_definition_revision` staging table** (clone of the M13.3 ledger
pattern) and a **`propose_field` tool**: the agent stages a field definition (key, field-class,
type, equality mode, freshness TTL, reuse-scope — a `<pack>.*` field must declare one), the
proposal surfaces in ICP co-confirmation (and, per the plan pack, as brief "schema variable chips"
and `schema_change` gates), and promotion writes the registry row. **Approval posture (decided):**
fields are human-confirmed in ICP review; personal-data field-classes (`contact.facet.*`,
anything `sensitive`) always require a human.

**Current state → delta.** Runtime registration exists; ICP synthesis currently *silently drops*
out-of-registry LLM proposals. Delta: the staging table, the tool, the co-confirmation surfacing,
and un-dropping the synthesis path (proposals become staged rows instead of discards).

**Plan.** Step 4.

**Acceptance criteria.**
- An LLM-proposed out-of-registry field during ICP synthesis lands as a staged proposal visible at
  co-confirmation — nothing silently dropped (regression test on the synthesis path).
- Promoting a proposal makes the field immediately fillable by the waterfall with no code change.
- A `contact.facet.*` proposal cannot be promoted without a human approval record.

---

### REQ-04 — Exhaustive research loops; gaps are first-class output

**Requirement.** Fields that could not be researched are retried in later rounds with escalated
strategies; if they terminally fail, they are flagged clearly to the user with the full attempt
history — "loop engineering" so the agent researches exhaustively, and honest gaps instead of
silence.

**Rationale.** Founder requirement #2 (and the founder's judge-loop diagram,
`proposed-research-design.png`). Empty-is-correct only works as a product if *empty is visible and
explained*.

**Design.** Three parts:
1. **Coverage ledger** — per `(entity, field)`: attempts `[{round, strategy/source, outcome,
   stop_reason, cost}]`, terminal status (`filled | unfilled_terminal | blocked_by_policy |
   budget_exhausted`), block reason. Written by the waterfall/workers, read by the judge, the
   review surface, and the dossier.
2. **Goal-judge loop** — at each round boundary the per-account goal-judge scores coverage +
   verification health and emits a **typed gap set**; the planner escalates strategy per round
   (different source family, wider query, facet sub-worker). Deterministic stop conditions: max
   rounds per tier, budget envelope, marginal-yield floor. Reuses M8A's `sub_phase` +
   exactly-once-spend machinery with idempotency keys extended to `(account, field, tier, round)`.
3. **Terminal gaps as output** — review-surface rows plus a dossier "coverage & gaps" appendix:
   "tried Clay, official site, Exa over 3 rounds — not found; here's why."

**Current state → delta.** Gap *detection* exists (planning gap-fields, waterfall StopReason, M9.5
stale-claim re-research); nothing retries never-filled fields, no attempt ledger, no loop closure.
All three parts are new.

**Plan.** Step 4 (after the deferred verification seams close).

**Acceptance criteria.**
- A field that fails in round 1 is retried with a *different* strategy in round 2 (ledger shows
  distinct strategies), and the loop halts on each stop condition (three targeted tests).
- Every unfilled field in a completed deep run has a coverage-ledger row with a human-readable
  block reason; the dossier renders the appendix.
- Re-running a completed round is a no-op (idempotency on `(account, field, tier, round)`).

---

### REQ-05 — Human-readable research dossier with an inference layer

**Requirement.** Research output must include a well-synthesized, readable dossier for the user —
not raw claim rows — including *inferences*: what the facts mean, as experts would read them.

**Rationale.** Founder requirement #3. The claim store is the substrate; humans review documents.
The co-founder's fixtures (Eagle Physicians) set the calibration bar for what "good" reads like.

**Design.**
- **Inferences are claims whose evidence is other claims.** A `claim_derivation` side table
  (mirroring `claim_support`) records `derived_claim_id → supporting_claim_ids`. The faithfulness
  judge gains an **entailment mode** (is the derived statement entailed by its supports?);
  confidence propagates conservatively from supports (default: min of supports, policy-tunable).
  Derived claims obey every promotion rule ordinary claims do.
- **`compose_dossier` tool** renders a cited, *regenerable* view over claims: markdown/HTML with a
  provenance index, plus (REQ-16) the treaty's nine-block projection shaped by a per-brand
  DossierSchema. Sections cover the account profile, signals/evidence per product slot, committee
  cards (with binding/audit chips), positioning narrative, feasibility notes, and the REQ-04
  coverage & gaps appendix.
- **Dossier ownership (decided):** owned here as a view over claims — "verified meaning" — with
  artifact-shaped content remaining downstream (D1 intact). Dossier "versions" are snapshots of
  the projection; refresh diffs map to claim supersede/merge underneath.

**Current state → delta.** Narrative, handoff, and two-sided provenance exist (M12 lineage).
Delta: `claim_derivation`, the entailment judge mode, `compose_dossier`, the block projection.

**Plan.** Step 7 (depends on the entailment-mode judge; after verification seams).

**Acceptance criteria.**
- Every sentence in a composed dossier is either a rendered claim (click-through to evidence) or a
  derived claim with visible supports — zero unprovenanced prose (rendering-time check).
- A derived claim whose supports are superseded is flagged stale and excluded from regeneration
  until re-judged.
- The Eagle Physicians fixture dossier is representable block-for-block by the projection
  (calibration test shared with the frontend).

---

### REQ-06 — Raw-material ingestion (client uploads → claims)

**Requirement.** Clients upload raw materials at Stage 0 and beyond — .docx, .txt, .md, .pdf,
.pptx, images, web pages, YouTube — and the platform ingests them correctly into the claim layer.

**Rationale.** Founder requirement #4. Client-volunteered material is the cheapest, most
authoritative source for `client.*` truth and a strong seed for target assertions.

**Design.** Ingestion is **just another resolver family**: an upload becomes a source-manifest
row; modality adapters convert it to text/segments; the `ClaimExtractor` seam produces typed
claims with evidence spans pointing into the stored artifact. **Trust policy:** client material
*about the client* enters at tier 1–2, `tenant_private`; assertions *about targets* cap at tier 3
and corroborate normally (client says "hospitals running Epic churn less" → that is a
`client_stated` signal proposal, never a world-fact without its own evidence). Content-addressed
storage (REQ-07) deduplicates re-uploads.

**Current state → delta.** The modality-adapter framework exists (PDF, transcription,
Firecrawl-HTML, passthrough; content-addressed `ArtifactCache`; `ClaimExtractor` seam). Delta:
upload endpoint(s), docx/pptx/OCR adapters, durable blob storage (REQ-07), CKB file orchestration,
and the treaty-side wiring (composer "@ → Upload file…" is the frontend hook — REQ-17).

**Plan.** Step 4 (storage lands step 1).

**Acceptance criteria.**
- Each supported format round-trips: upload → claims with evidence spans that resolve into the
  stored artifact (per-format fixture tests).
- A client-uploaded deck asserting a fact about a *target account* produces a tier-≤3 claim that
  requires normal corroboration before promotion (policy test).
- Re-uploading identical bytes creates no duplicate artifact or claims (content-address test).

---

### REQ-07 — Pluggable storage backend

**Requirement.** A `StorageBackend` adapter selected by config: local filesystem or any
S3-compatible object store (R2, S3, MinIO), without code changes elsewhere.

**Rationale.** Founder requirement #5; also fixes a latent defect — scrape evidence pointing at
live URLs that rot. Snapshots make evidence durable and re-verification (REQ-14's re-check node)
possible.

**Design.** A `StorageBackend` protocol — `put / get / delete / presign / exists` over
content-addressed keys (sha256) — with filesystem and one S3-compatible implementation (endpoint
config covers R2/S3/MinIO), selected in `config/settings.py`. An **`artifact` table** records
(key, content hash, media type, size, tenant scope, source-manifest link, timestamps) with a
**DSAR-erasure hook** (M10.5 tombstones cascade to stored blobs). Evidence spans reference
snapshots, not live URLs. Signed URLs serve the frontend (treaty §2.8).

**Current state → delta.** Nothing exists; `config/settings.py` is the config slot. All new,
small, independent.

**Plan.** Step 1.

**Acceptance criteria.**
- Swapping filesystem ↔ S3-compatible is a settings change; the full test suite passes against
  both (CI matrix).
- Every new scrape stores a snapshot; the claim's evidence span resolves offline from the
  snapshot alone.
- DSAR erasure of a contact removes/tombstones the associated stored artifacts (erasure test).

---

### REQ-08 — Stage 0: eager recon + governed interview + readiness spec *(confirmed 2026-07-06)*

**Requirement.** Stage 0 is a dynamic client-understanding conversation, not a rigid stage: at URL
submission, preliminary research runs in the background; the chat agent then interviews the client
from a position of context, records stated facts, and research spend is gated by a **readiness
spec**, not a screen order. The ICP re-synthesizes as the client corrects themselves.

**Rationale.** Rounds 2–3 of the harness discussion. Confirmed 2026-07-06 against the plan pack:
the design **stands unchanged**; the frontend docs' "single-pass, confirm-once" reading was a
misunderstanding — Lock 6 is honored as "one *scrape* pass" (recon dedupe/cost control), not
"client understanding complete after one confirm."

**Design.** Four mechanisms:

1. **Eager recon (Recipe #0).** At name+URL submission, client reverse-profiling runs in the
   background on the detached worker: small hard per-signup envelope (order of cents; exact size
   is an open decision), tiers 1–3 + light synthesis only — no tier-4 spend before the client
   confirms direction. **Two-speed:** a fast pass (own site + obvious officials, seconds-to-
   minutes) so the agent has context if chat opens immediately; the deeper pass continues behind
   and streams in mid-conversation. Guards: domain-keyed dedupe; per-signup envelope (abuse
   vector: 50 pasted URLs must cost cents, not dollars). Recon claims about the company are
   `public_footprint`-scoped, so a second tenant hitting the same domain reuses them — recon cost
   amortizes across the tenant base. Output = a **recon brief** (mini `compose_dossier`) + a gap
   list that *is* the interview agenda.

   > **Superseded 2026-07-23 ([B3×research]):** accounts are now workspace-local (founder ruling
   > 2026-07-22; provider licensing + GDPR controller separation). Public-footprint claims are no
   > longer shareable across workspaces — the cross-tenant recon amortization described above (and
   > the duplicate-domain reuse acceptance criterion below) is retired; each tenant re-runs recon in
   > its own workspace. `reuse_scope` survives only as the privacy classification (write-leak guard
   > + DSAR selector).
2. **The interview is a source.** A registered `client_interview` source (modality: conversation;
   tier 1 for `client.*` fields — the client is the most authoritative source about themselves)
   whose resolver *is the chat agent*: when the gap planner finds unfilled client/ICP fields whose
   best source is the interview, "calling the source" means asking the question in chat. Answers
   become ordinary claims: evidence span = the **verbatim quoted user turn**, idempotent on
   `(entity, field, turn)`, faithfulness-judgeable (the recorded value must be entailed by the
   quote — the agent cannot paraphrase the client into something they didn't say). Corrections are
   ordinary supersedes with version history → the ICP re-synthesizes from current truth.
   **Hypotheses are not world-facts:** "we sell to hospitals" = tier-1 client claim; "hospitals
   running Epic churn less" = a signal proposal tagged `client_stated`; agent-proposed signals
   enter tagged `agent_proposed` with rationale; both lists surface at co-confirmation, and the
   M13.3 learning loop later reports each signal's discriminating power.
3. **Readiness spec replaces the phase gate.** Versioned config declaring coverage/confidence
   floors per spend gate: what must be known before ICP synthesis is worth running, before
   discovery may spend, before deep research may spend — enforced by the existing pre-spend
   machinery. *How* each gap closes (ask, ingest a deck, connect CRM, research the web) is the
   agent's choice per gap, steered by the Stage-0 **skill file**. Minimum-input survives: a
   URL-only client who answers nothing still reaches a confirmed ICP at lower confidence with
   flagged assumptions; "just go" remains a client override.
4. **The confirmed onboarding flow (frontend anchors, 2026-07-06 sketches).**
   URL submission → ingestion screen ticking **real backend events** (website scrape, knowledge-
   base scrape, brand guide, brand voice, ICP-intent understanding, value-prop extraction →
   brand "theme complete"; brand-kit extraction is the design-side share of the same recon run;
   recon must emit events granular enough for 1:1 ticks — no fake progress) → **"How do you wanna
   get started" fork**: card A **"Surprise me"** (recon-derived ICP persona bullets, candidate
   accounts, negative winners, "add more to the list" input — the recon brief + gap list projected
   as a card; the *discovery* entry) or card B **"I know my account"** (named targets → deep
   research + collaterals; the *import* entry) → **either card lands in the chat interface**,
   where the interview-as-source runs directly. Both entry scenarios remain first-class and
   symmetric; they converge at the Pass-A scoring bridge as always.

**Memory hook (Doc M).** The same kickoff interview is scoped memory's `user_stated` writer *and*
its per-campaign re-confirmation gate: stated preferences and behavioral learnings become memory
records (born `active`, tenant-private), not claims — the species split holds (facts still become
claims, above) — and memories whose staleness signals fired resurface here for confirm/amend, which
is the freshness heartbeat that makes the Nth campaign start smarter than the first. See
`clue-hq-scoped-memory-and-context-assembly.md` §7 (write seam), §13 (kickoff = re-confirmation gate).

**Product hook (v1.2, REQ-22 / Doc A Part IV).** Stage 0 is additionally *product-conscious*: kickoff
declares (or recon proposes) the project's `product_id`; a known product pre-satisfies readiness
floors from existing product-scoped claims and memory, flipping the interview into
confirm/refresh mode — only fired-staleness items and new gaps surface as questions. Nothing in
this requirement is removed; REQ-22 layers reuse-awareness on top.

**Current state → delta.** CKB waterfall fill, synthesis, versioned `icp_spec`, co-confirmation
all exist and survive *as tools*; the fixed handler sequence as the only path dies. New: the
`client_interview` source + resolver, `volunteered_statement` capture (REQ: nothing the client
says is dropped because the registry didn't anticipate it — unmapped statements land as
`volunteered_statement` records with promotion paths → mapped claim or `propose_field`), the
readiness-spec config + gate wiring, Recipe #0, the recon-brief projection feeding the fork card.

**Plan.** Interview source + readiness spec + Recipe #0 in step 4; a minimal skill loader early;
the fork-card projection rides step 2's projection API. Recipe #0 is deliberately the lowest-risk
first exercise of the step-0 worker + step-2 projections (one account, cents).

**Acceptance criteria.**
- A signup with URL only produces a recon brief within the envelope; a duplicate-domain signup
  reuses `public_footprint` claims (cost assertion).
- An interview answer produces a claim whose evidence span is the verbatim turn; a paraphrase that
  isn't entailed by the quote is rejected by the judge (fixture test).
- A client correction mid-conversation supersedes the prior claim and triggers ICP re-synthesis;
  co-confirmation shows both `client_stated` and `agent_proposed` signal lists.
- Deep-research spend is impossible before the readiness spec's deep floor is met, and possible
  immediately after (gate test); the "just go" override is recorded as an explicit decision.
- The ingestion checklist ticks map 1:1 to emitted recon events (no synthetic progress).

---

### REQ-09 — CRM as optional accelerator, never a prerequisite

**Requirement.** Everything in Stage 0 (and beyond) must work without a CRM connection; CRM is
offered late, after value is proven.

**Rationale.** Round 3: new clients will not OAuth a new platform into their CRM; trust is earned.

**Design.** The readiness spec must be satisfiable from URL + interview + uploads alone. The
skill craft encodes the **trust ladder**: (1) free — "name your 5–10 best customers" in chat (the
import scenario already handles messy free-text; five names give the lookalike machinery real
signal); (2) low trust — pasted list or CSV export upload (REQ-06); (3) high trust — OAuth CRM
connect offered post-value-proof (post-first-campaign, which is also when the learning loop can
use outcome data). CRM remains just one resolver family; nothing downstream knows it exists.

**Current state → delta.** Import/identity-resolution machinery exists; the delta is skill-file
craft (step 4/6) and the CSV path riding REQ-06.

**Acceptance criteria.**
- A tenant reaches confirmed ICP → discovery → deep research with zero CRM connection (end-to-end
  test without any CRM resolver registered).
- Named-customer free-text in chat seeds lookalike discovery identically to a CSV import of the
  same names.

---

### REQ-10 — Fleet scale (100–500 accounts) with runtime quality

**Requirement.** Research must scale to 100–500 accounts per campaign with runtime judging and
steering that keeps a swarm from "producing crap" — without a human reviewing 500 transcripts and
without LLM-judging every worker turn.

**Rationale.** Round 2. Accepted verbatim by the founder including the anti-pattern rejection:
turn-by-turn LLM judging is cost-prohibitive and redundant.

**Design.**
- **Topology: 500 accounts is queue depth, not 500 conversations.** The chat agent is control
  plane only — it plans, launches, steers, answers; it never executes research in-session. A
  detached `CampaignRunWorker` (build step 0 — the hard prerequisite) drives a **tier-priority
  queue** of account jobs under a concurrency window (~16–32 in flight), per-account budget
  envelopes, per-source rate limits. Each job is the existing M8A per-account orchestrator graph —
  bounded fan-out, checkpointed, idempotent, resumable. *(Refined 2026-07-17: the per-account job
  may be a **governed worker agent** — Doc A §1.3 — choosing strategy, tools, and capped facet
  sub-agents at runtime within the same envelope/checkpoint/idempotency contract; the
  queue/window/canary shell is unchanged.)* Tier-priority order means budget
  exhaustion still researched the *best* accounts first (composes with REQ-13's two passes).
- **Five-layer quality pyramid:**
  1. *Hard determinism at every step (always-on, free):* fan-out/depth caps as runtime limits,
     envelopes, pre-spend gates, target-lock, stop-at-confident. Unbounded wrong-direction
     generation is structurally impossible; the worst case is bounded wasted spend inside one
     envelope.
  2. *Per-claim LLM judgment on 100% of outputs (exists — M9):* faithfulness, corroboration,
     identity binding, use gate. Crap can be produced; it cannot be **promoted**.
  3. *Per-account goal-judge at round boundaries* (REQ-04): coverage + verification health →
     another round, stop, or flag.
  4. *Run supervisor (new):* reviews **signals, not transcripts**. Deterministic monitors run
     continuously over aggregates — per-account verification health, gap ratio, spend-vs-yield,
     stalls, per-source error rates — with periodic LLM triage batch-diagnosing similar failures.
     Actions are bounded and journaled: quarantine one account (pause its graph, not the run),
     trip a source circuit-breaker run-wide, tighten an envelope, escalate to the human *with a
     diagnosis attached*.
  5. *Human = exceptions, canaries, and the M13.1 ranked review surface* — never 500 transcripts.
- **The judging pattern:** outputs always, trajectories at round boundaries, aggregates
  continuously, transcripts by sample (the M9.6 eval battery).
- **Canary default in Recipe #1:** run the top-tier ~10 accounts → supervisor health gate → open
  the fleet. "Produce 10, judge, then 500" beats discovering a systemic failure at account #480.

**Current state → delta.** M8A graphs, M9 judging, M13.1/13.4 surfaces exist. New: detached
worker + per-run driver lease + task drain (step 0), the queue/window/envelope scheduler, the run
supervisor (steps 4–5), the canary gate in Recipe #1.

**Acceptance criteria.**
- kill -9 the worker at 40% of a 500-account run → resume completes exactly-once (step-0 de-risk
  test; no double spend on `(account, field, tier)`).
- A source going bad mid-run trips its circuit breaker and quarantines affected accounts without
  pausing the fleet (fault-injection test).
- A canary health-gate failure blocks fleet open with a diagnosis attached to the escalation.
- No code path LLM-judges intermediate worker turns (architecture test: judge invocations keyed to
  outputs/rounds/aggregates/samples only).

---

### REQ-11 — Live visibility and mid-run steering

**Requirement.** While a swarm runs, the user can ask the chat about any account's progress or the
run overall and get an immediate answer; the system proactively narrates meaningful progress; the
user can steer mid-run (pause an account, reprioritize, add a field, kill a source, tighten
budget). Sessions are decoupled from runs.

**Rationale.** Round 2 — "the user would like to know that something is running in the
background… at overall level or for a specific account." It is very similar to how Claude Code
surfaces background tasks (§4.5 mental model).

**Design.** All state already lands in Postgres (checkpoints, sub-phase rows, gate decisions,
budget ledger, claims, spans); the delta is packaging:
- **Projection API** — `run_overview()` (accounts by state, burn-down, health, ETA),
  `account_progress(account)` (current node/round, fields filled vs planned, spend, flags, latest
  claims), `explain_flag(...)`. MVCC snapshot reads that never interrupt a worker. "How's the Acme
  research going?" is a snapshot read.
- **Narrator event stream** — transactional outbox → SSE; periodic digests ("142/500 scored ·
  deep running on 38 · 3 flagged for conflicting revenue") with drill-down on demand. Pinned to
  the treaty's exact SSE contract (envelope, per-workspace ordering, at-least-once + `seq`
  idempotence, `Last-Event-ID` replay ≥ 24 h / 10 k events, single-use stream tokens, topics,
  `stream.hello`/`stream.reset`) — REQ-16.
- **Steering tools** — the campaign machine's existing pause/adjust semantics exposed as toolbelt
  tools; destructive ones behind confirm gates.
- **Session decoupling** — runs live in the detached worker; close chat and reattach tomorrow, or
  a teammate attaches to the same run (single-writer lease for steering).

**Plan.** Step 2 (projections + streaming), supervisor digests alongside steps 4–5.

**Acceptance criteria.**
- `account_progress` answers during a running fleet without measurable worker slowdown (load
  test).
- Killing and reopening the chat session does not affect the run; reattachment restores the
  narrated view from the event cursor with zero gap (replay test).
- Every steering action is journaled with actor + before/after and takes effect within one
  scheduling cycle.

---

### REQ-12 — Repeatability: recipes and the run-graph journal *(revised 2026-07-11)*

**Requirement.** Work that produced a good result must be reproducible: runs are journaled as
graphs, pinnable as parameterized **recipes**, re-runnable later — surfaced in the product as
**run views, activity timelines, and a recipe library** (the node-based canvas is retired as a
product surface, 2026-07-11). "It worked great once but can't be reproduced" is a product failure.

**Rationale.** Founder platform requirement (balance between agency and reproducibility). Revised
2026-07-11: the units being composed are themselves agentic — self-directed specialists, not dumb
steps needing wiring — so a node-DAG editor is the wrong interaction model. Composition happens
through the orchestrator agent and the shared screens (REQ-18–REQ-20); reproducibility is
unchanged as a requirement.

**Design.** The reproducibility plane (§4.4): every tool invocation is journaled as a node —
parameters + **pinned config versions** (ICP spec, source profile, skill, prompt, model). A run
graph can be pinned as a recipe: parameterized, versioned, re-runnable; recipes declare
compatibility so one referencing a retired field/source fails at load, not mid-run. **Honest
semantics (decided):** *outcome-reproducible, not transcript-identical* — same process, same
pinned configs, same gates, LLM leaf variance bounded by verification floors and the eval battery.
The journal is written **by the toolbelt**, never by the agent; chat narration is a view over it.
Rendering (revised 2026-07-11): the journal surfaces as a **run view** (steps, dependencies,
gates, per-node pinned versions — a timeline/tree over the A4 manifest projection), an **activity
feed**, and a **recipe library** (browse / pin / edit parameters / re-run); free-form graph
authoring is out of scope. The run-graph journal projects into the treaty's manifest shape for
those run screens (REQ-16). The founder's "change across all 60 artifacts" flexibility has the research analogue for
free: re-score after an ICP edit, re-research after a field registration, re-verify after a policy
change = bump a config version + re-run the affected sub-graph — cheap because tools are
idempotent and claims append-only.

**Memory hook (Doc M).** The context-assembly **bundle journal** is the memory-layer extension of
this run journal: every assembled context bundle records the memory ids + label metadata it
injected and what the bundle budget excluded and why — references, never bodies — so *"what context
did the agent see"* stays definitively answerable (and DSAR never becomes a journal-redaction debt).
The run manifest also pins per-run memory-enabled state, like any pinned config. See
`clue-hq-scoped-memory-and-context-assembly.md` §11 (bundle journal), §17a (kill-switch in manifest).

**Plan.** Step 5 (journal + recipes + durable graph executor; pipeline ships as Recipe #1).

**Acceptance criteria.**
- Re-running a pinned recipe on the same inputs yields the same *outcomes* (same fields filled,
  same gates, same verification floors) — golden-set assertion, explicitly not byte-identical
  text.
- A recipe referencing a retired config version fails validation at load with the incompatibility
  named.
- The journal for any historical run renders as a complete, navigable run view — every step with
  its dependencies and per-node pinned versions (no orphan invocations).

---

### REQ-13 — Two-pass cost discipline + two-stage per-product fit *(decision 2026-07-06)*

**Requirement.** Score all accounts cheaply first; a human tier checkpoint gates deep spend; deep
research runs only on high tiers. Additionally (from the plan pack's fixtures, adopted): fit is
scored **per product** — `(account × product)` with evidence refs and product qualifiers — and a
`tier_recommendation` is emitted.

**Rationale.** The plan pack's `full-campaign` recipe ran uniform deep research then scored from
the dossier (tier gating only package richness). Decided: **our principle prevails** — at 500
accounts, ungated deep research is $1.5–4 k per campaign and breaks the fleet design (tier-
priority queue, canary). The pack's per-product scoring (Eagle: referral 72 / DAC 68 / recall 40)
is adopted as a genuine improvement.

**Design.** **Two-stage per-product fit:**
- *Provisional fit* (Pass A): deterministic scoring from enrichment-level data — the per-product
  fit model weights **schema variables** (registry fields) that cheap enrichment fills; product
  qualifiers hard-gate (a hit disqualifier marks the account disqualified; downstream skipped).
  Emits `tier_recommendation`. Scoring is code, not LLM; rubric is config-as-data per client/ICP.
- *Tier checkpoint* (human): unchanged — confirms/edits cutoffs before deep spend; exposed as a
  gate-tool placeable in any plan, and required by Recipe #1 between the passes.
- *Final fit* (post-Pass B, high tiers only): recomputed with dossier-evidence refs (claim ids)
  justifying the score — the fixture bar (72/68/40 with rationale links) applies here.
Reserved fields `account.scoring.fit`/`.intent` remain (tenant-private); product-keyed additions
only. The recipe-spine correction in the co-founder's docs is a treaty-review item (REQ-17).

**Current state → delta.** Pass A/tier machinery exists per-ICP; delta is the product dimension on
the scoring seam, the two-stage recording (which stage produced the current score), and
`tier_recommendation` in the wire shape.

**Plan.** Scoring-seam delta scheduled with M12/handoff-adjacent work; recipe correction at treaty
review.

**Acceptance criteria.**
- Deep-research spend on any account below the confirmed tier cutoff is impossible (gate test).
- Fit rows exist per `(account, product)`; each final score's `evidence_refs` resolve to promoted
  claims; provisional vs final stage is recorded and visible.
- The Eagle fixture reproduces: three product scores, one hard qualifier pass, intent `med`,
  tier 2 — from the golden dataset.

---

### REQ-14 — Verification is substrate; re-check surfaces are additive *(decision 2026-07-06)*

**Requirement.** Nothing about the verification substrate changes: claims are born with provenance
and evidence spans or cannot be promoted; the faithfulness judge, corroboration, identity binding,
use gate, freshness, and eval battery operate exactly as built (M9.x). The plan pack's
`claim.verify` / `fabrication.audit` node is adopted **additively** as a visible re-check surface.
Quality modes (Draft/Standard/Best) may vary breadth, variants, and corroboration hunting — they
**never move the promotion bar**.

**Rationale.** The pack modeled verification as a pipeline step whose depth varies with a
user-facing dial (Draft = link-alive check only). Decided: verifiability stays a property of the
data model — that is exactly what makes agent-composed plans safe (a plan cannot "skip"
verification because verification is not a plan step).

**Design.**
- **Substrate (unchanged):** pre-spend gate (M9.1), corroboration with per-field equality modes
  (M9.2), faithfulness judge with injection-hardened prompts (M9.3), identity-binding classifier
  (M9.4), freshness TTLs + age-out (M9.5), golden-set eval harness + regression gate (M9.6).
- **Additive re-check tool** (the pack's node): batch re-verification over already-judged claims —
  re-open the snapshot/source (REQ-07), exact-match the quote, re-grade confidence; emit a
  `VerificationReport` (`claims_checked`, `links_opened/working`, `items_flagged[]`) and
  per-contact **fabrication-audit rollups** (the fixtures' "Links opened: 8 of 8 · Items flagged:
  0" chips) computed from existing verification + snapshot data. It is a *view/refresh* mechanism;
  it grants nothing the substrate didn't already grant.
- **Quality-mode rule (hard):** modes map server-side per tool to fan-out caps, model tier,
  variant count, corroboration breadth, retry budget. The set of invariants — evidence-span
  requirement, faithfulness at write, binding + use gates, corroboration rules for promotion — is
  identical across modes.

**Plan.** Re-check tool in step 7 (needs snapshots + verification seams); quality-mode mapping is
a step-2 toolbelt-envelope schema slot filled per tool as tools land.

**Acceptance criteria.**
- In every quality mode, an unjudged or evidence-less claim cannot be promoted (mode × invariant
  test matrix).
- The re-check tool's report is derivable purely from stored snapshots + verification tables (no
  new judging authority; runs offline against fixtures).
- The M9.6 regression gate stays green across the toolbelt refactor (no verification behavior
  drift).

---

### REQ-15 — Compliance per Doc D / M10, without compromise *(decision 2026-07-06)*

**Requirement.** The compliance machinery proceeds exactly as designed and built: per-client
jurisdiction switch, use-class taxonomy, appropriateness/use gate (distinct from accuracy), the
three deep-research postures, sensitive/special-category data excluded from outreach by default,
retention TTLs, DSAR erasure. The frontend is a skin over this — its simpler `use_with_care` flag
is a *projection* of use-class + client posture, never a replacement.

**Rationale.** The plan pack's only personal-data control was a two-level sensitivity flag with
human opt-in, and its fixtures celebrate special-category hooks (faith, family history). Decided:
no compromise — design-strict-and-switch-down stands. A US-permissive posture with per-use human
confirmation is expressible as *one policy configuration* of the existing machinery; EU design
partners get the strict posture by flipping the switch, not by re-engineering.

**Design (unchanged, restated).** Personal claims carry identity-binding strength + use-class;
outreach use requires both gates; `sensitive` is excluded by default and, where a permissive
jurisdiction + client policy allows, requires explicit per-use human opt-in at the gate (which is
precisely what the pack's letter-draft gate does — the projection is faithful). Retention horizons
can be shorter than field TTLs (minimization); DSAR erase/objection/age-out tombstone claims and
cascade to stored artifacts (REQ-07) and derived text (the known `faithfulness_verdict.rationale`
redaction follow-up in the backlog — must land before go-live). Frontend/wire consequences are
REQ-17 items: use-class on personal-claim wire shapes, jurisdiction/posture config surface, DSAR
endpoints reserved in the treaty.

**Memory hook (Doc M).** Scoped memory joins this DSAR surface as a first-class citizen: because a
person-adjacent preference/behavioral learning holds the personal data in the record *body* (no
claim contains it), each such memory carries a fail-closed `subject_entity_id`, inherits the
personal-claim minimization/retention posture, and is tombstoned/objection-locked by the same
machinery — a deterministic query, never a substring scan — with ids-never-bodies journals so no
personal substring survives in any rendered bundle. Extends this requirement's DSAR acceptance
criterion. See `clue-hq-scoped-memory-and-context-assembly.md` Part V.

**Plan.** No new backend work beyond the already-tracked backlog items; wire surfaces at treaty
review.

**Acceptance criteria.**
- Under the strict posture, a special-category hook never appears in any outreach-eligible
  projection regardless of prompt or plan (policy test).
- Under a permissive posture, the same hook appears only behind a per-use human confirmation
  record.
- A DSAR erasure leaves no personal substring of the erased value/span in any served projection —
  including the dossier block projection and re-check reports (extended DSAR test).

---

### REQ-16 — Serve the frontend treaty (Group A: projection/serving surfaces)

**Requirement.** The subsystem serves the shapes the treaty (`08-backend-contract.md`) already
defines, by adding views and adapters over the existing substrate — backend internals unchanged,
nothing deleted. The frontend builds against mocks; the same contract test suite must eventually
run green against our staging (treaty Mode B).

**Design — the ten serving surfaces** (proposal §11.3 Group A):

| # | Surface | Design essentials |
|---|---|---|
| A1 | **Dossier block projection** | `compose_dossier` gains a `blocks` output: the nine-block vocabulary shaped by a per-brand DossierSchema; dossier versions = snapshots; refresh diffs = claim supersede/merge underneath; block actions map to claim ops (challenge → re-verify; refresh section → scoped re-research; exclude-from-artifacts → claim flag) |
| A2 | **Per-product fit** | REQ-13's `(account × product)` FitScore + qualifiers + `tier_recommendation` in the treaty's `fit_scores` shape |
| A3 | **Contact-class vocabulary** | Pack-registered per-workspace `contact_class` (e.g. clinical/business) emitted alongside the fixed committee personas; `(account, persona)` keys unchanged; registered, not enumerated |
| A4 | **Run-manifest projection + ops** | Project campaign-run machine + per-account graphs into the manifest shape (`node_key`, `depends_on`, `status`, `account_scope`, `gate`, `quality_mode`, `est_cost`); accept `PATCH …/manifest` ops (add/remove/set_dependencies/update_config/set_quality) with `expected_seq` optimistic concurrency; invalid ops rejected loudly (422 with reason); consumer reframed 2026-07-11 — run-detail/steering screens (timeline/tree rendering), not a canvas; shape unchanged, re-confirm at treaty review |
| A5 | **SSE per treaty §5** | The REQ-11 narrator pinned to the exact envelope/order/replay/token/topic contract |
| A6 | **`timeline_phase` emission** | Worker/tracing states → `thinking/reading/grepping/editing/done` on `run.step.progress` + inspector timelines |
| A7 | **Millicredit ledger with holds** | Client-facing integer-millicredit layer over the USD cost ledger (M13.4): `debit/credit/grant/adjustment/hold/hold_release` + `balance_after`; hold at run start, release/true-up at completion; 402 semantics; pause at 120% of estimate (existing envelopes) |
| A8 | **Quality-mode mapping** | REQ-14's server-side per-tool mode → knob resolution |
| A9 | **HTTP `Idempotency-Key` store** | 24 h key+response replay; 409 on same-key-different-body; additive over domain idempotency keys |
| A10 | **Batch re-verification tool + audit rollups** | REQ-14's re-check node + fabrication-audit chips |

**Plan.** A4/A5/A6/A9 + the "Surprise me" readiness/coverage projection land in step 2; A7 rides
steps 1–2 + M13.4; A1/A10 in step 7; A2/A3 with the scoring/committee seam work; A8 is a step-2
schema slot.

**Acceptance criteria.**
- The treaty contract test suite (Mode B) runs green against staging for every endpoint/event this
  subsystem owns.
- Mock-vs-real divergence on any owned surface is treated as a backend or treaty bug — never
  patched around (the treaty's own rule 4).
- The block projection renders both golden dossier fixtures losslessly (shared calibration test,
  REQ-05).

---

### REQ-17 — Evolve the treaty additively (Group B: contract additions)

**Requirement.** Everything this subsystem knows that the treaty cannot yet express is proposed as
**additive-only** treaty PRs (new optional fields, endpoints, event types, enum values — per the
treaty's own versioning rules), sequenced at the first treaty review pass. Nothing existing in the
treaty is broken; nothing planned here is dropped because the treaty lacks a field.

**Design — the seven proposals** (proposal §11.3 Group B):

| # | Proposal | Content |
|---|---|---|
| B11 | **Richer verification fields** | Optional additions on claim/provenance wire shapes: trust tier, corroboration/conflict flag, faithfulness verdict, identity-binding strength, use-class; `verified: boolean` stays as the coarse rollup — gives the UI vocabulary for conflicts and review reasons |
| B12 | **Verification-review queue kind** | M13.1 ranked review rows feed queue items; M13.2 dispositions flow back |
| B13 | **Coverage & gaps surface** | REQ-04's attempt ledger on the dossier ("coverage & gaps" appendix) + run projections |
| B14 | **Compliance surfaces reserved** | Per-client jurisdiction/posture config, use-class on personal claims (the pack's `sensitivity` maps onto it), DSAR erase/export endpoints — reserved even before the V1 UI skins them |
| B15 | **Ingestion endpoints** | REQ-06 upload → ingest-to-claims (docx/pptx/pdf/images/URLs/video); source-manifest per upload; composer "@ → Upload file…" hook |
| B16 | **`propose_field` / `propose_source` surfacing** | REQ-03 staged proposals at co-confirmation + `schema_change`-style gates mid-research; `propose_source` with policy-assigned tiers |
| B17 | **Recipe-spine correction** | REQ-13's tier checkpoint + budget gates between Pass A and deep research in the pack's `full-campaign` docs — a docs/sequencing change on the frontend side, not a backend change |

Delivery guidance: separate small PRs per item (each independently reviewable in minutes; none
blocks the frontend's mock-driven waves). Known pack-internal items to settle in the same pass:
confidence scale (numeric 0–1 vs high/med/low), gate/queue taxonomy layering, "Rust +
LangGraph" stack label correction; the canvas-op vocabulary item is **retired** with the node-canvas
surface (2026-07-11).

**Memory hook (Doc M).** *Serve existing treaty shapes (Group A):* the §4.13 memory endpoints, the
`memory` SSE topic, the `memory_review` queue kind (the `agent_observed` review path), and
brief/confirm memory seeding are backed by the scoped-memory substrate. *Propose additively at
treaty review (Group B):* the workspace memory **kill-switch** settings toggle + its audit record,
and a client-facing **bundle-journal projection** ("what informed this artifact"). See
`clue-hq-scoped-memory-and-context-assembly.md` §7–§11 (seams + journal), §17a (kill-switch), §20.

**Acceptance criteria.**
- Every Group B item exists as a treaty PR (or an explicit deferral decision) after the first
  treaty review pass; all are additive under the treaty's versioning rules.
- No backend capability in this document is silently dropped for lack of a wire shape (traceable
  mapping REQ → treaty surface or → reserved).

---

### REQ-18 — Agent registry & profiles: the agent-native product surface *(added 2026-07-11)*

**Requirement.** Every subsystem the platform exposes ships as a named **platform agent** — an
agent + tools + skills kit — listed in an **agent registry** and presented to the user as a
configurable **agent profile**: identity (name, description, system prompt), skill bundle, tool
allowlist, model & limits (model tier, reasoning effort, per-query budget cap, turn timeout),
autonomy posture, memory access (per Doc M), invocation configuration (chat/thread, schedules,
supervisor delegation; other channels later), and delegation settings (whether and how the
platform supervisor may invoke it, and what it may delegate onward). V1 ships a **fixed set** of
platform agents (this subsystem's research agent among its siblings: content, design, review, and
the Head-of-ABM supervisor); users configure profiles — they do not author new agents (open
registration deferred; O9 governs which fields are user-editable).

**Rationale.** Founder direction 2026-07-11, replacing the node-canvas surface: the product face
is an **agent workspace** (inspired by Hyperagent's agent-profile model) — a roster of specialist
agents the user can inspect, tune, and invoke, with the orchestrator composing them. The profile
is the *legible face of config that already exists*; this requirement is packaging, not new
authority.

**Design.** A profile is a **composition of versioned resource/config kinds** — folder-backed
skills (tool allowlists in frontmatter), budget envelopes, quality-mode mappings,
memory-access policy (Doc M), gate/approval postures — bound together by one small new
`agent_profile` config kind, versioned and promoted through the same propose → promote ledger as
everything else. In V1 that ledger kind records the promoted folder-resource address, digest, and
policy bindings; it does not store the profile, prompt, or skill body. **Autonomy posture is a
projection over gate policy (decided 2026-07-11):** a
profile chooses among postures the policy table already allows per gate; an "auto" posture can
never auto-approve a gate policy marks human-required (personal-data field classes, tier-≤2
source promotion, spend beyond envelope, a recipe-required tier checkpoint). The registry and
profiles project through the step-2 projection API for the frontend's agent screens; runs pin the
exact profile version like any other config.

**Current state → delta.** Every constituent (skills, envelopes, modes, gates, memory policy)
exists or is already planned; the delta is the `agent_profile` binding kind, the registry
projection, and profile-edit wiring through the config ledgers.

**Plan.** Rides step 6 (deep agent + skills); registry/profile projections ride the step-2 API
family; treaty shapes for the agent screens are a Group-B item at treaty review.

**Acceptance criteria.**
- Profile changes are ledgered (proposer, approver, versions); a run journal records the exact
  profile version behind every invocation.
- No autonomy setting can bypass a policy-required human gate (posture × gate test matrix, riding
  the REQ-02 attempted-override battery).
- The registry projection lists every platform agent with its live profile version; a recipe
  pinning a retired profile version fails at load (REQ-12 compatibility rule).

---

### REQ-19 — Sub-agent delegation contract (supervisor ↔ subsystem agents) *(added 2026-07-11)*

**Requirement.** The platform-level Head-of-ABM supervisor composes campaigns by invoking the
subsystem agents as sub-agents. That invocation is a **contract**, not an implementation detail:
what may be delegated, under what budget, whose gates apply, how it is journaled, and when the
sub-agent must refuse.

**Rationale.** The 2026-07-11 product direction makes the orchestrator the user's primary
end-to-end companion and each subsystem an agentic expert it consults as-and-when needed. The
v1.0 doc specified only the toolbelt seam; the agent-to-agent seam needs the same rigor.

**Design.**
- **Same seam, no private channel.** Delegation happens over the published toolbelt/agent schema —
  a delegated task can do nothing a directly-invoked one could not.
- **Envelope scoping.** Every delegation carries a budget envelope that is a child of the campaign
  envelope; the sub-agent cannot exceed it, and its spend rolls up to the parent ledger.
- **Gate inheritance (hard rule).** Human gates remain human gates: delegation never converts a
  human approval into an agent approval. A gate reached inside a delegated run pauses and surfaces
  to the human exactly as it would in a direct run.
- **Pinned context.** A delegation names the config versions it runs under (or "current
  promoted"); the journal records a **delegation node** — delegator identity, task spec, envelope,
  pinned versions — parenting the sub-run's graph.
- **Loud refusal.** `PreconditionFailed` and authority-boundary violations propagate to the
  supervisor as typed errors; a sub-agent never silently degrades scope to "make it work."
- **Lift-out unchanged.** The in-repo deep agent remains designed for lift-out (§10 agent-location
  decision); whether the supervisor consults the research *agent* (agent-to-agent) or calls
  *toolbelt tools* directly is a per-capability choice recorded in profile delegation settings
  (O10 working default: campaign ops via toolbelt; judgment/strategy tasks agent-to-agent).

**Current state → delta.** Toolbelt envelope, budget machinery, and journal are v1.0 plan items;
the delta is the delegation node type, child-envelope wiring, and profile delegation settings.

**Plan.** Lands with step 6 and the platform-supervisor integration; delegation-node journaling
extends step 5's journal schema.

**Acceptance criteria.**
- A delegated task cannot spend beyond its delegated envelope (enforcement test), and its spend is
  visible in the parent rollup.
- A human gate inside a delegated run produces the same pause/approval record as a direct run
  (parity test with REQ-20).
- Every delegation is a journaled node naming the delegator; no sub-run exists without a parent
  delegation node (journal integrity check).

---

### REQ-20 — Human–agent parity: one shared operating surface *(added 2026-07-11)*

**Requirement.** Agents and humans operate on the **same surface over the same substrate**. Every
domain object — campaign, run, account list, account, committee, dossier, artifact handoff — has a
screen; any operation an agent performs through a toolbelt tool must be performable manually by a
human from the corresponding screen, under the same gates, producing the same journal record
(differing only in recorded actor: human, agent, or delegated agent).

**Rationale.** Founder direction 2026-07-11: "everything an agent can do, a human can also
manually do." This is also the trust story — the human can inspect, intervene, and take over
anywhere without a parallel path — and the audit story: one write path means one journal.

**Design.** The toolbelt is the **single write path** for both actors. Screens invoke the same
tools with an actor identity; there are no screen-only mutations (invisible to agents and the
journal) and no agent-only mutations (un-inspectable and un-fixable by hand). Existing
review/steering surfaces (REQ-11 steering tools, M13.1 review + M13.2 dispositions,
co-confirmation, tier checkpoint) are instances of this rule, not exceptions. The chat/agent
sidebar coexists with direct manipulation on every screen; reads go through the same projection
API for both actors.

**Current state → delta.** Toolbelt-as-single-write-path is already the v1.0 architecture; the
delta is stating parity as binding, the actor field on journal nodes, and a traceability matrix
(tool ↔ screen affordance) maintained as Group-A screens land.

**Plan.** Standing exit check on step-2-and-later surface work; the matrix reviews at each treaty
review pass.

**Acceptance criteria.**
- Traceability matrix: every toolbelt tool maps to a screen affordance or carries an explicit,
  reviewed "agent-only because…" record — no unmapped tools.
- The same operation performed by human and by agent yields journal entries identical up to actor
  identity (golden comparison test).
- Architecture test: no frontend mutation endpoint reaches storage except through the toolbelt.

---

### REQ-21 — Workspace shell: projects, threads, tabs, artifact catalog *(added 2026-07-16)*

**Requirement.** The product shell is a project-scoped chat-plus-tabs workspace (Obvious-inspired):
a persistent chat pane and a tabbed work pane over typed domain objects, plus a drive-style
project catalog. Binding rules:

- **Threads belong to projects** (`thread(project_id, created_by, status)`); a new chat requires
  choosing or creating a project. **Every thread is fronted by the platform deepagent** (Doc A
  Part II) — threads never bind to specialist agents; specialists act as sub-agents whose outputs
  persist in the thread. The design editor's embedded deepagent is the one surface-bound
  exception, reached via a handoff card (Doc S §8).
- **A typed object-reference vocabulary** (account_list, account, dossier, content_draft,
  design_document, template_revision, instance_batch, campaign_run, thread, …): thread messages
  and SSE events carry `refs[]` (kind, id, title, thumbnail, deep-link) so chat can open tabs and
  hand off surfaces — additive treaty items.
- **Tabs carry declared edit contracts** (REQ-20 made concrete): content-draft tab = true editor
  over `content_draft` (versioned, actor-recorded); accounts tab = dispositions/steering
  gate-tools; design tab = the design-engine editor; **research/dossier tab = block actions only**
  (challenge → re-verify, refresh → scoped re-research, exclude-from-artifacts → claim flag,
  annotations as a separate layer; a typed factual correction becomes a `client_stated`
  supersede — the interview-as-source mechanism). Free-text dossier editing is rejected by
  design (decided 2026-07-16; presentation format itself remains open — O11).
- **Project artifact catalog** (`campaign_artifact`: project, kind, ref, title, status,
  thumbnail, actor, timestamps) backs the drive view; the design engine deliberately stays
  catalog-free and is wrapped, never modified, for this.

**Rationale.** Founder direction 2026-07-13/16 (Obvious.ai-inspired shell; classic-SaaS parity
alongside agent-native operation). The shell is a skin over existing surfaces — projections
(REQ-11), treaty shapes (REQ-16), parity (REQ-20) — plus the thread/ref/catalog entities above.

**Current state → delta.** Projections/SSE/steering exist or are scheduled (steps 0–2). New:
thread model + APIs, object-ref message parts (treaty PR), `campaign_artifact` catalog +
thumbnail wiring, per-tab edit-contract enforcement tests.

**Acceptance criteria.**
- A thread cannot exist without a project; every thread turn is answered by the platform
  deepagent profile pinned in the run journal.
- Every mutation from any tab lands through a toolbelt tool with actor identity (REQ-20 matrix
  extended with a tab column); a free-text dossier write path does not exist (negative test).
- A chat `ref` round-trips: emitted in SSE, opens the correct tab state from a cold reload.

---

### REQ-22 — Product profiles & cross-project continuity *(added 2026-07-16)*

**Requirement.** Products are first-class per workspace: each product line accumulates its own
product-scoped truth (claims at product reuse-scope), assets (brand-voice guide, imagery), and
memory (Doc M product scope). Projects declare a `product_id` at kickoff (stated or
recon-proposed, user-confirmed). The Nth project on a known product starts from the existing
**product profile card** — Stage 0 runs in confirm/refresh mode ("we already have these — anything
to change?"), asking only staleness-fired and genuinely new questions. A missing brand-voice
guide is produced by a skill-guided workflow and stored as product-scoped assets + claims.
Detail: Doc A Part IV.

**Rationale.** Founder direction 2026-07-16 (the Microsoft 365-consumer vs enterprise-suite
example): different products of one client have different audiences, competitors, reviews, and
voice; the platform must be consciously aware of what it already knows before asking again.

**Current state → delta.** Claims reuse-scope, TTL/staleness, Doc M scopes, and the kickoff
re-confirmation gate all exist by design; new: the `product` entity, product dimension on
CKB/asset scoping, the compiled product profile card (context layer L2, Doc A Part III), and the
confirm/refresh interview posture in the Stage-0 skill.

**Acceptance criteria.**
- Two projects on the same product share product-scoped claims without re-research (cost
  assertion); two products of one workspace never cross-contaminate voice/competitor claims
  (scoping test).
- A kickoff on a known product asks no question answerable from fresh product-scoped truth
  (fixture test: only staleness-fired + new-gap questions surface).
- Every product profile card line resolves to a claim/memory/asset id (no unprovenanced teaching).

---

## Part III — Architecture design

### 4. The four planes

The target architecture is four planes. Plane 1 exists; planes 2–4 are the harness era.

#### 4.1 Plane 1 — Kernel (keep, consolidate)

The substrate, unchanged in role: **claim store** (typed claims + provenance + evidence spans +
merge/current-value + reuse-scope enforcement), **identity resolution** (dedup → linkage →
canonicalization; everything keys on resolved `entity_id`), **field registry + industry packs**
(open by registration; field-classes for resonance and personal facets), **source registry /
profiles / trust-tiered waterfall** (deterministic APIs → official scrape → reputable third party
→ LLM synthesis last; stop at first confident hit; config-bounded source planner),
**verification** (M9.1–M9.6), **compliance** (M10.1–M10.5), **scoring** (deterministic Pass-A
engine + rubric-as-config), **budget/cost ledger + observability** (M13.4), **review surface +
disposition capture + learning loop** (M13.1–M13.3), **durable execution** (per-account LangGraph
graphs with `AsyncPostgresSaver` under the campaign-run state machine; idempotent on
`(account, field, tier)` and `(campaign_run, phase)`).

Kernel consolidation (scheduled, not structural): the known DRY batch — one shared
`normalize_host`, one shared freshness `reference_time`, one `decode_jsonb_scalar`, a
`BudgetTracker`, the `claim_tagger` pre-insert hook on `resolve_field` (which lets contact-facet
fill rejoin the shared waterfall engine, deleting the one true re-implementation) — plus a
procedural unfreeze of `core` (a lightweight contract-delta lane) and the `_conventions.md §2`
rewrite: shared utilities live in core; copying one is a defect; module-specific behavior extends
the shared engine via hooks/config, never re-implements it. The import-independence contracts
stay — they are what makes tool-ification safe.

#### 4.2 Plane 2 — Capability plane: the toolbelt

Every research capability becomes a typed tool over its existing module, with one uniform
envelope:

- **Typed request/response** (JSON-schema'd; the same schemas later serve MCP).
- **Declared preconditions, checked loudly** — `PreconditionFailed` with a machine-readable reason
  replaces every silent-empty path (non-negotiable; a planner that cannot see *why* a tool
  no-opped will thrash).
- **`estimate()`** — cost preview per invocation (feeds plan costing and the treaty's
  `/estimates`).
- **Idempotency** on the existing domain keys; safe re-invocation.
- **Returns references, not blobs** — claim ids + a coverage report; workers and tools never pass
  raw content around.
- **Automatic journaling** — every invocation writes the run-graph journal (plane 4) with pinned
  config versions; the journal is written by the toolbelt, never by the agent.
- **Budgeted** — every spending tool passes the pre-spend gate and draws down an envelope.

**Two granularities.** *Campaign ops* (set-scoped; engine-owned fan-out — the agent invokes
"deep-research tier-1 accounts", never hand-rolls a 500-account loop) and *entity/field ops*
(single account/field/claim — what the judge loop, block actions, and user steering need).
**Gate-tools** (tier checkpoint, budget approval, co-confirmation, package-style approvals) are
placeable anywhere in a plan; plan validation guarantees gate closure. **Quality mode** is an
envelope-level parameter resolved per REQ-14's rule. The toolbelt is, verbatim, the future MCP
surface — one adapter, no new logic.

#### 4.3 Plane 3 — Orchestration plane: deep agent, skills, goal-judge

- **Deep agent** (in `agent/`, import-contracted; designed for lift-out — the platform-level
  Head-of-ABM supervisor consumes the same toolbelt schema): compiles conversational intent into
  plan graphs over the toolbelt; requests context bundles; never freestyles context or writes
  state directly.
- **Skills as versioned folder resources/config**: prompt + policy bundles (frontmatter: tool
  allowlist, readiness-spec ref, per-vertical/per-client overlays; body: craft — e.g. the Stage-0
  interviewing skill: lead with what you already inferred, ask only gaps, confirm rather than
  interrogate, offer trust-light seeds early). V1 resolves exact reviewed folder versions and
  digests; `config_revision` may promote reference metadata/profile bindings; recipes pin the
  exact resource manifest; overlays resolve per client/industry.
- **Goal-judge loop** (REQ-04): per-account, at round boundaries; verdict is a typed gap set;
  deterministic stop conditions; strategy escalation per round.
- **Run supervisor** (REQ-10 layer 4): aggregate monitors + periodic LLM triage; bounded journaled
  actions.

#### 4.4 Plane 4 — Reproducibility plane: run graphs, recipes, run views

Journal → recipes → run views, per REQ-12. The run-graph journal is the single "what happened"
record (pre-mortem guard: chat narration is a view over it, never a second source of truth).
Recipes pin config versions and declare compatibility. The run-view contract is read/pin/re-run
in V1; the journal projects into the treaty manifest shape (REQ-16 A4) so the run screens render
real runs (node-canvas rendering retired 2026-07-11). Standing recipes: **#0 recon** (REQ-08), **#1 the classic pipeline** (with canary
default and the REQ-13 tier gate), and pinned client-specific graphs as they emerge.

### 5. Data & config model (harness-era additions)

All additions are append-only tables or config kinds beside the existing schema; migrations follow
the repo's Alembic conventions (hash revision ids; one head; reversible).

| Addition | Shape (essentials) | Serves |
|---|---|---|
| `claim_derivation` | `derived_claim_id → supporting_claim_ids[]`; entailment verdict; propagated confidence | REQ-05 |
| Coverage ledger | `(entity_id, field_key)` → attempts `[{round, strategy, outcome, stop_reason, cost}]`, terminal status, block reason | REQ-04, B13 |
| `field_definition_revision` | staged field proposals (proposer, definition, status, approver) | REQ-03, B16 |
| Source proposals | draft source-manifest rows staged via `config_revision`; policy-assigned tier; yield-loop reweighting/demotion | §4.2 of proposal, B16 |
| Readiness spec | versioned config: per-gate coverage/confidence floors (`icp_synthesis`, `discovery_spend`, `deep_spend`) + override records | REQ-08 |
| `client_interview` source + `volunteered_statement` | conversation-modality source manifest; unmapped statements with promotion paths | REQ-08 |
| **Scoped memory** (supersedes `client_memory`) | Five-scope (workspace/brand/product/campaign/account) preference/learning substrate behind two seams; `memory` + `memory_claim_ref` tables; provenance-graded born-trust; caps + eviction as versioned config; tenant-private fail-closed; references claims, never duplicates them (facts → CKB; the two species never mix). **See Doc M** (`clue-hq-scoped-memory-and-context-assembly.md`) — authoritative for the design | REQ-08, Doc M |
| Skill catalog | versioned folder-backed skill bundles + digests; optional ledgered reference metadata; overlays | REQ-02 |
| Run-graph journal + recipes | node = tool invocation + params + pinned versions; recipe = parameterized pinned graph + compatibility declaration | REQ-12 |
| `artifact` table + StorageBackend | content-addressed blobs; DSAR hook | REQ-07 |
| Credit ledger (millicredits) | integer ledger with holds over the USD cost ledger; pricing config maps cost → credits | A7 |
| Idempotency-key store | 24 h HTTP key+response | A9 |
| Per-product fit rows | `(account_id, product_id)` score + stage (provisional/final) + evidence refs + qualifiers + tier_recommendation | REQ-13 |
| Contact-class vocabulary | pack-registered per-workspace classes on committee contacts | A3 |

**Policy is data, not code** (unchanged, now wider): merge policy, scoring rubric + fit models,
source profiles, tier/budget caps, jurisdiction/use-class policy, freshness TTLs, readiness spec,
skills, recipes, quality-mode mappings — all versioned config the engine reads, swappable per
client/ICP without code changes, mutable only through propose → promote ledgers.

### 6. Runtime topology

```
chat session(s)  ──(plans, steering, questions)──►  deep agent / platform supervisor
      ▲                                                     │ compiles plan graphs
      │ narrator digests (SSE)                              ▼
projection API ◄── Postgres (claims, journal, ledgers) ◄── toolbelt (typed, gated, journaled)
      ▲                                                     ▲
      │                                        detached CampaignRunWorker (step 0)
      │                                          │ per-run driver lease · task drain
      │                                          ▼
      │                              tier-priority queue (window ~16–32)
      │                                          │ per-account budget envelopes
      │                                          ▼
      └── run supervisor (aggregate monitors  per-account M8A graphs (LangGraph,
          + LLM triage; bounded actions)       checkpointed, idempotent, rounds via goal-judge)
```

- **Sessions never execute research**; the worker owns execution; a per-run driver lease enforces
  a single driver; sessions attach/detach freely (single-writer lease for steering).
- **All entry surfaces converge on the toolbelt** (2026-07-11): chat sessions, human operations on
  the shared screens (REQ-20), supervisor delegations (REQ-19), and scheduled/recipe runs invoke
  the same tools under the same gates; the journal records the actor on every node.
- **Rounds** live inside per-account graphs (goal-judge at boundaries); the fleet sees accounts,
  not rounds.
- **Canary**: Recipe #1 opens with top-tier ~10 → supervisor health gate → fleet.
- **Failure containment**: account quarantine pauses one graph; source circuit-breakers act
  run-wide; envelopes bound worst-case waste; kill -9 anywhere → exactly-once resume.

### 7. External interfaces

1. **Toolbelt schema** — the internal seam, and the boundary the platform (including the design
   subsystem's tools) consumes; later exposed 1:1 over MCP.
2. **Projection API** — `run_overview`, `account_progress`, `explain_flag`, readiness/coverage
   projections (feeds the "Surprise me" card), review-surface reads. Snapshot reads only.
3. **Treaty HTTP + SSE** — the shapes of `08-backend-contract.md` this subsystem owns: accounts /
   discovery / import, dossiers + block actions, contacts, fit scores, research runs + manifest
   ops, queue items it originates, credits, ingestion (B15), compliance (B14). Language-neutral
   (JSON Schema; the treaty forbids anything TS- or Rust-specific being normative). Contract
   tests: the frontend's identical suite runs against staging (Mode B) — first green run = treaty
   honored.
4. **Handoff** — the persona-keyed claim bundle + value narrative + dossier (blocks + rendered),
   consumed by the downstream content/design layers (D1 boundary).

### 8. Stage-0 flow, end to end (confirmed)

Signup (name + URL) → **Recipe #0 recon** starts in background (small envelope, two-speed,
tiers 1–3, domain-deduped) → ingestion screen ticks real recon events → brand theme complete →
**fork**: "Surprise me" (recon brief + gap list + candidate accounts + negative winners; discovery
entry) or "I know my account" (named targets; import entry) → **chat** (confetti; first credits):
agent opens with the recon brief ("correct me"), runs the gap-driven interview — facts → claims
(verbatim-quote evidence spans), preferences → `client_memory`, hypotheses → tagged signal
proposals, uploads → ingestion, named customers → import seeds — while deeper recon streams in
mid-conversation (narrator: "just found your case-studies page — mostly mid-market logistics, did
I read that right?") → **readiness spec met** → ICP synthesis → **co-confirmation** (proposed
fields + signals from both sides; recon-vs-stated discrepancies flagged by the corroborator) →
discovery may spend → Pass A scores all accounts → **tier checkpoint** → deep research on high
tiers (canary → fleet) → verification → dossiers + handoff. No fixed order inside Stage 0; the
readiness spec is the only gate; "just go" remains a recorded client override; a URL-only silent
client still reaches a confirmed ICP with flagged assumptions.

---

## Part IV — Plan

### 9. Build sequence

Steps 0–7 unchanged from the proposal (§6), with the REQ-16/17 additions slotted (§11.4). Each
step is shippable; nothing regresses (Recipe #1 preserves the pipeline throughout).

| # | Work | Slotted additions | De-risk / exit test |
|---|---|---|---|
| 0 | **Detached `CampaignRunWorker` + per-run driver lease + task drain** | — | kill -9 at 40% of a 500-account run → exactly-once completion |
| 1 | **StorageBackend + `artifact` table** (REQ-07) | millicredit ledger groundwork (A7, with M13.4) | fs ↔ S3 swap via settings; snapshot round-trip |
| 2 | **Toolbelt façade** — envelope, loud preconditions, `estimate()`, projection API + streaming | A4 manifest projection/ops · A5 SSE per treaty · A6 phases · A9 idempotency store · A8 mode schema slot · "Surprise me" readiness/coverage projection | out-of-order tool matrix → loud errors; treaty SSE replay test |
| 3 | **Consolidation pass** — core contract-deltas, `claim_tagger`, `BudgetTracker`, conventions §2 rewrite | — | contact fill rejoins shared waterfall (−~115 lines); DRY greps clean |
| 4 | **Coverage ledger + goal-judge loop** (REQ-04) · **`propose_field`** (REQ-03) · **`propose_source` + tier-3 generic web resolver** · **ingestion** (REQ-06) · **interview source + readiness spec + Recipe #0** (REQ-08) · minimal skill loader | B13 · B15 · B16 anchors | REQ-04/06/08 acceptance tests; Recipe #0 as first live exercise of steps 0+2 |
| 5 | **Run-graph journal + recipes + durable graph executor**; pipeline ships as Recipe #1 (with canary + tier gate) | run supervisor (with 4) | recipe outcome-reproducibility on golden set |
| 6 | **Deep agent + skills** (`agent/`, import-contracted) | — | plan-validation + authority-boundary tests |
| 7 | **`compose_dossier` + derivation edges** (REQ-05) | A1 block projection · A10 re-check tool | fixture dossiers render losslessly; DSAR-clean projections |

Cross-cutting: A2 per-product fit + A3 contact-class ride the scoring/committee seams (schedule
with M12-adjacent work); Group B treaty PRs sequence at the first treaty review pass (the pack's
`00-master-plan.md` §8 open item). The pre-existing backlog (CLAUDE.md "Backlog / known caveats")
keeps its own schedule; several items (api-root gate wiring, binding stamping, merge retention
awareness, verdict-rationale redaction) are prerequisites for specific steps above and are cited
in place there. v1.1 additions: REQ-18's `agent_profile` config kind + registry projection ride
steps 2 and 6; REQ-19's delegation contract lands with step 6 and the platform-supervisor
integration; REQ-20's parity traceability matrix is a standing exit check as Group-A screens land.

### 10. Decisions register

**Resolved.**

| Decision | Resolution | When |
|---|---|---|
| Platform shape | Deep-agent harness; four planes; pipeline survives as Recipe #1 | 2026-07-03 |
| Agent location | Platform-level Head-of-ABM supervisor exists (co-founder pack); in-repo deep agent incubates in `agent/` behind the toolbelt schema, designed for lift-out | 2026-07-03/06 |
| Config mutation ceiling | Only through propose → promote ledgers | 2026-07-03 |
| Field/source approval posture | Fields: human at ICP review, personal classes always; sources: tier ≤3 auto with audit + yield demotion, tier ≤2 human | 2026-07-03 |
| Dossier ownership | Here, as a regenerable view over claims; D1 intact; block projection is the boundary artifact | 2026-07-03/06 |
| Replay semantics | Outcome-reproducible, not transcript-identical | 2026-07-03 |
| Object store | S3-compatible client from day one | 2026-07-03 |
| Canvas V1 | Agent-authors / user-pins-and-re-runs — **superseded 2026-07-11** by the product-surface decision below (canvas retired; journal/recipes stand) | 2026-07-03 |
| Fleet quality | Five-layer pyramid; no turn-by-turn LLM judging; canary default | 2026-07-03 (accepted verbatim) |
| Stage 0 | Recon + interview-as-source + readiness spec + ICP re-synthesis; onboarding flow per 2026-07-06 sketches; Lock 6 = one scrape pass | 2026-07-06 |
| Two-pass economics | Prevail; two-stage per-product fit; recipe-spine correction to frontend docs | 2026-07-06 |
| Verification | Substrate unchanged; re-check node additive; modes never move the promotion bar | 2026-07-06 |
| Compliance | M10/Doc D exactly as planned; `use_with_care` is a projection | 2026-07-06 |
| Frontend integration | Delete nothing; Group A serving surfaces + Group B additive treaty PRs | 2026-07-06 |
| Scoped memory | Second shared substrate beside the claim store; five-scope preference/learning behind two seams; facts stay claims (species split); tenant-private fail-closed; advisory, never binding; own doc (**Doc M**). Q1–Q6 (notepad), Q7 DSAR + Q8 kill-switch, mechanism rulings (form/storage/write/read/lifecycle/caps) | 2026-07-07 / 2026-07-11 |
| Product surface | Agent-workspace UX (Hyperagent-inspired): agent registry + configurable profiles, orchestrator-led composition, run/activity/recipe-library views on a shared human–agent surface; node-based canvas **retired** as a product surface (REQ-12 revised, REQ-18–REQ-20 added; run-graph journal & recipes unchanged) | 2026-07-11 |
| Agent registry scope | V1 ships a fixed set of platform agents with user-configurable profiles; open agent authoring deferred | 2026-07-11 |
| Per-agent autonomy | Profile autonomy (auto vs ask-first) is a projection over gate policy — it can never bypass a policy-required human gate | 2026-07-11 |
| Human–agent parity | One shared operating surface; the toolbelt is the single write path for human and agent actors alike | 2026-07-11 |
| Thread model | Threads are project-scoped and fronted by the platform deepagent only; specialists are sub-agents in-thread; the design editor is the sole surface-bound exception | 2026-07-16 |
| Terminology | Project = end-to-end ABM motion (historical "campaign"); campaign = channel program within a project (§1a) | 2026-07-16 |
| Research tab posture | Block actions only (Option A); typed corrections become `client_stated` supersedes; free-text dossier editing rejected. Presentation format itself stays open (O11) | 2026-07-16 |
| Personalization unit | Both account-level and contact-level in v1, declared per artifact (Doc S §1) | 2026-07-16 |
| Product profiles | Products first-class; product-scoped claims/assets/memory; kickoff confirm/refresh (REQ-22) | 2026-07-16 |
| Agentic schema | Doc A is binding for agent/deepagent/fleet vocabulary and context assembly; no fake agency — a component's class change is a register event | 2026-07-16 |
| D2 (overview) | Resolved: design ingests binding sets against a frozen template slot contract via the content plane (Doc S) | 2026-07-16 |
| Fleet refinement | Fleet = the governance shell (queue, envelopes, idempotency, checkpoints, supervisor — always mechanical); units inside are **deterministic workers** (content instantiation, batch derivation, Pass-A scoring) or **governed worker agents** (per-account deep research: bounded agency, own micro-loop, capped facet sub-agents); no agentic middle-orchestrator between the platform deepagent and the units. Doc A §1.3/§1.5 (v1.1) | 2026-07-17 |
| Repo structure & observability | uv workspace (libs/ · subsystems/ · platform/); shared machinery promoted out of `clue_research` into `clue_*` libs (shim-and-deprecate); structlog-first via `clue-obs` (ported py_lumen_obs pattern; actor/ids-not-values redaction); phases R0–R3 on `platform/workspace-restructure-v0`; R1 subsumes build step 3. **Doc R** is the plan record | 2026-07-17 |

**Open.**

| # | Question | Working default until decided |
|---|---|---|
| O1 | Worker topology scale (process/queue tech at multi-tenant scale; Temporal migration timing) | V1 Postgres state machine, Temporal-shaped seams |
| O2 | Concurrent-session semantics detail (beyond single-writer steering lease) | Lease + read-everywhere |
| O3 | Replan economics default (when the agent may auto-replan vs. propose) | Propose-only until BacktestGate evidence |
| O4 | Recon envelope size per signup | Cents: single-digit resolver calls + one synthesis pass |
| O5 | Fact-capture UX posture | Implicit-with-visibility ("noted: ✓" trail; batch review at co-confirmation) |
| O6 | Recon brief: chat-only or persistent artifact | Both (it is the first wow artifact) |
| O7 | Quality-mode customer label ("Best" vs "Premium") | Shank's call before ticket cut (pack open item) |
| O8 | Exact millicredit pricing map (USD → mc, margins) | Ledger built value-agnostic; pricing config versioned |
| O9 | Which agent-profile fields are user-editable in V1 (vs admin/policy-locked) | Skills overlay choice, autonomy within policy, budget caps, model tier |
| O10 | Delegation granularity default (supervisor → sub-agent vs supervisor → toolbelt, per capability) | Campaign ops via toolbelt; judgment/strategy tasks agent-to-agent; recorded per profile |
| O11 | **Dossier as the research-presentation format** (block-action posture is decided; the *document shape* is not). **Standing flag: notify the founder before any upstream implementation binds to the dossier document shape specifically** — downstream consumers read claims/narrative/block projections, not rendered dossiers (Doc S O-S1) | Dossier + block projection as designed; consumers insulated |
| O12 | Review posture for scaled artifacts (canary + flagged tail vs full-table review) | Canary + flagged tail; gates trusted for the green tail (Doc S §6) |

### 11. Pre-mortem (failure modes and standing guards)

1. **Agentic loops burn budget** → deterministic loop control (rounds/budget/marginal-yield);
   spend behind ledger + admission gates; replan economics measured before default-on (O3).
2. **Silent-empty tools mislead the planner** → loud preconditions are non-negotiable (step 2).
3. **Recipe rot** → recipes pin versions *and* declare compatibility; retired refs fail at load.
4. **Tier laundering via proposed sources** → tier is policy code + human gate above tier 3; the
   LLM never sets trust.
5. **Two sources of truth for "what happened"** → the journal is written by the toolbelt; chat
   narration is a view.
6. **Dual truth for client facts** → facts live in the CKB only; scoped memory (**Doc M**) holds
   preferences/behavioral learnings only, enforced at the write seam by the species check + body
   rule (a fact-shaped or personal-claim-quoting submission is rejected toward the CKB path); a
   memory record references claims by id, never duplicates content; the frontend's memory "fact"
   kind resolves to claim references at the treaty boundary. Guard #6 test in Doc M §21.
7. **Quality modes eroding verification** → the mode → knob mapping is config with an explicit
   invariant set that no mode may touch; tested per mode (REQ-14).
8. **Fleet-scale systemic failure discovered late** → canary gate default; supervisor aggregate
   monitors; source circuit breakers.
9. **Treaty drift** → additive-only rule + both-party PR review + the shared contract test suite
   run against staging (Mode B); divergence is a backend/treaty bug, never a frontend workaround.
10. **Autonomy settings quietly widen authority** → profile autonomy resolves through the same
    gate-policy table; "auto" postures are validated against policy at profile-promotion time, and
    attempted-bypass tests ride the REQ-02 eval battery (REQ-18).

### 12. Non-goals and honest limits

- **No completeness guarantee** — coverage confidence with named unsearched channels, never
  "we found everyone."
- **No transcript-identical replay** — outcome-reproducibility is the contract (REQ-12).
- **No turn-by-turn LLM supervision** of workers — by design, not omission (REQ-10).
- **No artifact/content generation here** — research stops at verified meaning + the block
  projection; angles, copy, design, rendering are downstream.
- **No LLM authority over trust, spend, fan-out, or gates** — ever (§2.5).
- **No CRM dependency** in any required path (REQ-09).
- **No engagement analytics ownership** — UTM/snippet/rollups are platform-side (treaty §4.14/§6);
  this subsystem only consumes engagement signals if/when the learning loop ingests them.

### 13. Cross-reference map

| Topic | Where |
|---|---|
| Analysis & evidence trail (code survey, addenda history) | `clue-hq-harness-replatform-proposal.md` |
| Substrate architecture (claims, waterfall, verification, scoring) | `clue-hq-research-layer-architecture.md` |
| Scoped memory & context assembly (the second shared substrate) | `clue-hq-scoped-memory-and-context-assembly.md` (Doc M) |
| Agentic schema, platform deepagent, context assembly, product profiles | `clue-hq-platform-agent-runtime.md` (Doc A) |
| Content plane, template finalization, artifact scaling, design handoff | `clue-hq-content-and-artifact-scaling.md` (Doc S) |
| Four outputs, output contract, open-decision register D1–D8 | `clue-hq-research-architecture-overview.md` |
| Staged flow, research modes M1–M4, source intelligence | `clue-hq-discovery-and-research-staged-architecture.md` |
| Stage-0 front edge (pre-harness baseline) | `clue-hq-stage0-client-and-icp.md` |
| Signals, bounded fan-out, cost governance | `clue-hq-signal-execution-cost.md` |
| Compliance machinery (jurisdiction, use-classes, postures, DSAR) | `clue-hq-compliance-and-personal-data.md` |
| Non-technical narrative | `clue-hq-research-harness-founder-brief.md` |
| The frontend treaty + plan pack | `~/Downloads/plan/08-backend-contract.md` (+ docs 00–11) |
| Plan-pack comparison + decisions log | `_memory/2026-07-06-cofounder-plan-pack-comparison.md` |
| Harness discussion log (rounds 1–3) | `_memory/2026-07-03-harness-replatform-analysis.md` |
| Known caveats / scheduled fixes | `CLAUDE.md` §"Backlog / known caveats" |
