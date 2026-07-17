# 2026-07-07 — Scoped memory & context organization: founder ruling on Q1 (+ campaign-scoped ICP)

## Context
Continuation of the 2026-07-06 memory/context-organization discussion (see
`2026-07-06-cofounder-plan-pack-comparison.md`). Six clarifying questions (Q1–Q6) were posed
before designing the scoped-memory system (pack model: `~/Downloads/plan/02-object-model-memory.md`
§1/§5 — five scopes, MemoryRecord lifecycle, context recipes). This session the founder ruled on Q1
and added a new requirement (campaign-scoped ICP + per-campaign interview).

## Decisions (founder-confirmed)

1. **Q1 = Option A — the species split survives.** Adopt the pack's *organization* (five scopes
   workspace/brand/product/campaign/account, most-specific-wins; lifecycle: graded born-trust,
   review queue, edited-against decay, caps/eviction; deterministic context recipes) but apply it
   **only to the preference/learning species**: generalize `client_memory` from one flat per-client
   store to the five-scope system. Facts stay claims in the CKB/claim store. A memory record may
   **reference** a claim by id but never duplicate its content. The pack's `kind: "fact"` memory
   disappears (or becomes a claim reference). Dual-truth pre-mortem guard #6 stands.

2. **Harness obligation:** context assembly must automatically surface the right scoped
   preferences when the deep agent works on a given product/campaign/account — preferences set for
   a product/campaign apply exactly when working within that product/campaign (the context-recipe
   mechanism, deterministic, not retrieval-vibes).

3. **ICP definitions are campaign-scoped.** Different campaigns for the same client can carry
   different ICP definitions. The ICP spec stays on the facts/config side (versioned `icp_spec`,
   NOT memory — no "ICP memory seeds"; any memory reference to ICP is a projection/ref, never a
   copy). Scoping changes: a campaign pins its own ICP spec (fork/refine from brand-level
   default), rather than one client-level ICP serving all campaigns.

4. **Each campaign starts with its own interview session** by the deep agent before research/spend
   proceeds for that campaign — Stage 0's governed interview generalizes from a one-time
   onboarding ritual to a per-campaign kickoff. First campaign = full Stage 0; Nth campaign starts
   pre-loaded (brand CKB claims + scoped memory + prior ICP specs as draft) so the interview
   shortens over time. Readiness spec gates spend per campaign.

## Implications accepted (to fold into the design)
- **Campaign becomes a first-class durable entity** in this repo (distinct from `campaign_run` —
  the object a run executes *for*; memory + ICP scope to the campaign). Products likewise need
  resolvable entity ids (product-scoped preferences + per-product fit already require this).
  → This pre-answers part of Q3.
- Existing `(client_id, icp_version)` keying (scoring config, source-profile overrides, pre-spend
  policy) extends naturally — campaign → pinned icp_spec version.
- Fit scores are per-ICP, hence effectively per-campaign; claims remain client-level reusable
  assets, so re-scoring an already-researched account under a new campaign's ICP is cheap Pass-A
  work (no re-research; freshness TTLs govern reuse).
- Facts learned in any campaign's interview remain **client-level claims** (true about the client
  generally); campaign scoping applies to ICP definitions and preferences, not facts —
  **CONFIRMED by founder (same day, round 2). Q1 fully closed.**
- Boundary rule **CONFIRMED**: changes to *who fits / how accounts score* → ICP-spec content
  (campaign-scoped versioned config); changes to *how the agent behaves/produces* → memory
  record; a verifiable statement about the world → claim at whatever entity it's about.
- Both named consequences (Campaign/Product as first-class entities; per-campaign re-scoring
  economics) explicitly accepted by founder.
- Running decision log created at
  `docs/architecture/clue-hq-scoped-memory-decisions-notepad.md` (uncommitted, per review
  convention) — all subsequent Q2–Q6 rulings get recorded there as they land.

## Q2 ruling (same day, later rounds) — CLOSED
Memory substrate lives **in this repo** behind **two seams** (write seam: all writers submit
candidates through one API, lifecycle rules enforced at the substrate, trust-no-writer; read
seam: consumers request task-scoped context bundles, never query storage; one enforcement point,
one journal of "what context did the agent see"). **Mechanism + storage format explicitly NOT
decided** — separate staged discussion; pack mechanics are reference input only.
**Charter ruling attached:** this repo becomes the **platform backend home** — future subsystems
and skills are built in this repo under the same scope-and-seam discipline; memory = second
shared substrate beside the claim store; one backend serves the whole treaty (§4.13 memory
endpoints here); research subsystem = first subsystem in the repo, four-outputs test stays
research-scoped. Full detail in `docs/architecture/clue-hq-scoped-memory-decisions-notepad.md`.

## Q3 ruling (same day) — CLOSED
Full object spine adopted as canonical scope keys: **workspace (= client org, tenancy root) →
brand (V1 1:1 w/ workspace) → { product / campaign / account }**. Products = resolvable entities
(enter as `client.*` CKB claims, resolved product ids — closes the products-as-entities open
doubt); Campaign = durable object distinct from `campaign_run` (runs execute *for* a campaign;
ICP pins to campaign); Brand modeled now so multi-brand is additive later; `tenant_id` vs
`client_id` debt resolves to workspace-as-tenancy-root (rename/migration = scheduled
implementation task). Spine matches the treaty's entity vocabulary 1:1. Detail in the notepad.

## Q4 ruling (same day) — CLOSED
Two learning systems stay separate: **config learning stays config** (M13.3 versioned revisions
from measured evidence — unchanged); **scoped memory holds conversational/behavioral learnings**.
Gray-zone experiential learnings ("this ROI framing wins with clinical buyers") → **memory**,
applied **suggestively** — the deep agent surfaces "what worked" as suggestions in similar
scenarios; user decides. Decision rule: deterministic behavior change → config; inform/suggest →
memory (memory feeds "LLM proposes", config governs "engine disposes"). Optional graduation
bridge (memory pattern → proposed M13.3 config revision) parked for design discussion.

## Q5 + Q6 rulings (same day) — CLOSED; all Q1–Q6 now closed
**Q5:** memory always **tenant-private, never reuse-scoped** — nothing crosses workspaces, even
for the same target account domain; agency case changes auth, not memory. Enforced fail-closed
at the substrate (like `reuse_scope`).
**Q6:** scoped memory + context assembly gets **its own architecture doc** (Doc-D pattern) with
hooks in the main harness doc. Founder rationale: memory = the company's second brain, builds
the moat over time.

## Design + documentation DONE (2026-07-08 → 2026-07-11)
Mechanism/storage design discussion held (memory-landscape research report as evidence, not spec)
and the standalone architecture doc **`docs/architecture/clue-hq-scoped-memory-and-context-assembly.md`
(Doc M, v1.0 CONFIRMED)** written. Consolidates Q1–Q6 (notepad) + new rulings Q7 (DSAR/personal
data) and Q8 (workspace kill-switch) + all mechanism rulings. Key mechanism decisions in Doc M:
one `memory` table + `memory_claim_ref` (append-only-in-spirit; status transitions, never silent
content mutation); two species types (`preference`/`behavioral_learning`); three-level scope tree
(third level = product/campaign/account siblings → most-specific-wins only along parent chain,
cross-branch tension surfaced+labeled not resolved); provenance-graded born-trust (user_stated→
active, edit_distilled→proposed-until-pattern, agent_observed→proposed+review-queue); write-time
reconciliation over active∪dormant (reactivation rule kills zombie twins); inject-only read seam
with deterministic gate→lexicographic sort(trust,freshness,confirmations)→stability-order assembly
→label→journal; **cycle-relative freshness, no wall-clock decay**; store cap→dormant vs bundle
budget→journaled; DSAR: person-adjacent memory carries fail-closed `subject_entity_id`, tombstone/
lock by keyed query, ids-never-bodies journals (no redaction debt); kill-switch = workspace toggle
at the two seams, typed `memory_disabled` no-op, off≠erasure. Deferred-with-triggers: search_memory,
consolidation pass, type→scope matrix, memory→config bridge, pgvector/graph, per-campaign override.

## Hooks wired into other docs (2026-07-11) — per Doc M §20
Added references (Doc M owns the design; these are pointers only):
- **harness-architecture-and-requirements.md**: §5 table (`client_memory` row → Scoped memory/Doc M);
  REQ-08 (interview = user_stated writer + re-confirm gate); REQ-12 (bundle journal extends run
  journal; manifest pins memory-enabled state); REQ-15 (memory joins DSAR surface); REQ-16/17
  (serve §4.13 endpoints/SSE/queue/seeding = Group A; kill-switch toggle+audit + client-facing
  bundle-journal projection = Group B); Decisions register (new Scoped-memory row); pre-mortem
  guard #6 (species check + body rule); cross-ref map (Doc M row).
- **compliance-and-personal-data.md (Doc D)** §4: scoped memory = second DSAR surface bullet.
- **research-layer-architecture.md** §1: sibling-substrate callout (facts=claims here, prefs=memory
  there; opposite cross-tenant default).
- **research-architecture-overview.md** §4: Doc M added as entry 7 + harness-era note.
- **stage0-client-and-icp.md (Doc B)** §5: per-campaign kickoff = memory writer/re-confirm gate note.

## Repo-charter rewrite DONE (2026-07-11)
Reframed the repo identity from "the data & research subsystem" to **platform-backend home;
research = subsystem one; scoped memory (Doc M) = subsystem two; future subsystems land here under
the same scope-and-seam discipline**. Edits: **CLAUDE.md** opening (subsystems-behind-substrates
framing + doc list extended to 8 — added harness architecture doc as entry 7 / harness-era
authoritative, Doc M as entry 8); **research-architecture-overview.md** intro scope-note. "This
subsystem" in the research docs now explicitly means the research subsystem, not the whole repo.

## Open / next
- Slice-1 build (Doc M §18): schema+migrations, two seams, inject-only assembly + journaling,
  user_stated writer in kickoff, kill-switch. Hard part = write-time reconciliation (ships with
  eval golden set). Treaty `memory_review` queue kind = frontend+backend.
- Carried: commit posture for uncommitted docs; Recipe #0 candidate-preview question; O4–O6
  working defaults.
- After Q2–Q6: architecture-design discussion, then documentation (founder's staged process).
- Also still open from the architecture doc session: commit posture for the 3 uncommitted docs;
  Recipe #0 candidate-account preview pre-ICP-confirm; O4–O6 working defaults; product-entity
  modeling (partially answered by this ruling).

No code changed this session; discussion + this note only.
