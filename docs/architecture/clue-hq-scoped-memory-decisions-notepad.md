# Scoped Memory & Context Organization — Decisions Notepad

> **What this is.** A running decision log for the scoped-memory / context-organization design
> conversation (started 2026-07-06, continuing). Every ruling the founder makes in this discussion
> gets recorded here as it lands, before any of it is folded into the formal architecture docs.
> This is the working notepad, not the design doc — when the design is documented (per the staged
> process: clarify → design discussion → document), that doc supersedes this file as the
> authoritative statement; this file remains the decision trail.
>
> **Background.** The co-founder's plan pack (`~/Downloads/plan/02-object-model-memory.md` §1/§5)
> defines a five-scope memory + deterministic context-recipe system. Six clarifying questions
> (Q1–Q6) were posed before adapting it to this subsystem's architecture. Related session notes:
> `_memory/2026-07-06-cofounder-plan-pack-comparison.md`,
> `_memory/2026-07-07-scoped-memory-q1-ruling.md`.

---

## Q1 — The species split — **CLOSED 2026-07-07**

**Ruling: Option A.** Adopt the pack's *organization* — the five scopes
(workspace / brand / product / campaign / account, most-specific-wins), the lifecycle mechanics
(provenance-graded born-trust, review queue, edited-against decay, caps/eviction), and the
deterministic context recipes — but apply it **only to the preference/learning species**.

Sub-decisions:

1. **Facts stay claims.** Facts about the client, products, and target accounts live in the
   CKB/claim store only. A memory record may **reference** a claim by id, never duplicate its
   content. The pack's `kind: "fact"` memory disappears (or becomes a claim reference).
   Dual-truth pre-mortem guard #6 stands.
2. **`client_memory` generalizes** from one flat per-client store to the five-scope system.
3. **Harness obligation:** context assembly must automatically surface the preferences scoped to
   the product/campaign/account the deep agent is currently working on — via deterministic
   context recipes, never retrieval-vibes.
4. **ICP definitions are campaign-scoped.** Each campaign pins its own ICP spec (typically forked
   from a brand-level default and refined). The ICP remains a versioned `icp_spec` on the
   facts/config side — **never** memory; no "ICP memory seeds" (any memory mention of ICP is a
   reference, not a copy). Two campaigns for the same client may define fit differently.
5. **Each campaign opens with its own interview session** by the deep agent before research/spend
   for that campaign. Stage 0's governed interview generalizes from a one-time onboarding ritual
   to the per-campaign kickoff; the readiness spec gates spend per campaign. First campaign =
   full Stage 0; the Nth campaign starts pre-loaded (brand CKB claims + scoped memory + prior ICP
   specs as draft), so the interview shortens over time ("Nth campaign better than the first").
6. **Facts learned in any campaign's interview land at the level they're true at** — a general
   client fact is a client-level claim usable by every campaign, not scoped to the campaign whose
   interview surfaced it. Campaign scoping applies to ICP definitions and preferences, not facts.
7. **The routing boundary rule (confirmed):**
   - changes *who fits / how accounts score* → **ICP-spec content** (campaign-scoped, versioned config);
   - changes *how the agent behaves or produces* → **memory record** (at the narrowest correct scope);
   - a *verifiable statement about the world* → **claim**, at whatever entity it's about.

Accepted consequences:

- **Campaign becomes a first-class durable entity** in this repo (distinct from `campaign_run` —
  the object a run executes *for*; memory and ICP scope to it). **Products** likewise become
  resolvable entities (product-scoped preferences + per-product fit both require it). This
  pre-answers part of Q3.
- Existing `(client_id, icp_version)` keying (scoring config, source-profile overrides, pre-spend
  policy) extends naturally: campaign → pinned ICP spec version. Fit scores are per-ICP, hence
  effectively per-campaign. Claims remain client-level reusable assets, so re-scoring an
  already-researched account under a new campaign's ICP is cheap Pass-A work over existing claims
  (freshness TTLs govern reuse) — no re-research.

---

## Q2 — Who owns the memory substrate? — **CLOSED 2026-07-07**

**Ruling: the memory substrate lives in this repo, behind two seams, with enforcement at the
substrate — the claim-store pattern applied to memory.**

1. **Write seam.** Anyone producing a candidate memory — the Stage-0/kickoff interview
   (`user_stated`), the downstream distiller (`edit_distilled` from artifact slot-diffs), an
   agent observing mid-run (`agent_observed`) — **submits** it through one API and never inserts
   rows directly. Whatever lifecycle rules are later designed (born-trust grading,
   review-before-active, scope caps, tenancy isolation) are applied at this seam, to every writer
   identically. The distiller's *logic* lives downstream next to the artifacts, but it is just a
   writer: it owns no store and cannot create an "active" memory by fiat, exactly as a resolver
   cannot create a promoted claim by fiat.
2. **Read seam.** Consumers — research agents and downstream content skills alike — never query
   memory storage directly. They request the context for their task ("task-type X, account A,
   campaign C") and receive whatever the assembly engine deterministically produces. There is
   exactly one place where "what context did the agent see" is decided and recorded.
3. **One enforcement point, no path around it** — so the eventual mechanism's guarantees are
   real regardless of writer/reader.

**Mechanism and storage format remain explicitly undecided** (founder framing note, same day):
Q1 settled scoping/boundaries; the memory mechanism + storage format is a separate staged
discussion still to come. The pack's mechanics (record shape, confidence numbers, decay math,
recipes) are reference input, not adopted-as-is. Q2 decides only the address and the enforcer.

**Charter ruling attached (larger than Q2 itself):** the substrate is **repo-scoped, and this
repo is the platform's backend home** — future subsystems and skills will be built *in this
repo*, following the same scope-and-seam discipline defined here. Consequences:
- The charter tension dissolves: the repo is not "research-only, awkwardly widened" — the
  research subsystem becomes the *first* subsystem in the repo; the four-outputs test remains
  the research subsystem's test, not the whole repo's.
- **Memory becomes the second shared substrate** beside the claim store. The modularity rule
  generalizes: subsystems communicate through substrates/seams (typed claims; memory via the two
  seams), never by importing each other; the machine-checked import boundaries extend to every
  future subsystem.
- One backend serves the whole treaty — §4.13 memory endpoints (+ `memory` SSE topic,
  `memory_review` queue kind, `brief/confirm` seeding) are implemented here; no second backend
  is ever invented.
- When the content subsystem is eventually built, it (and the distiller) live here as their own
  packages — still writers/readers through the seams; in-process vs HTTP is an implementation
  detail, the seam is the contract.

## Q3 — The object spine — **CLOSED 2026-07-07**

**Ruling: the full object spine is adopted as this repo's canonical scope keys.**
`workspace (= client org, tenancy root) → brand (V1: exactly one per workspace) →
{ product / campaign / account }`.

1. **Products become resolvable entities** here — they enter as `client.*` CKB claims during
   reverse-profiling/interview and get resolved product entity ids (this also closes the
   architecture doc's earlier open doubt #2: products are not platform-side-only opaque ids).
   Per-product fit (REQ-13) and product-scoped memory both key on them.
2. **Campaign becomes a durable object distinct from `campaign_run`** — the object a run
   executes *for*. Runs reference their campaign; the campaign pins its ICP spec (Q1); memory
   scopes to the campaign, never the run.
3. **Brand becomes an entity, V1 1:1 with workspace** — modeled now so multi-brand later is
   additive, not a migration crisis. Accounts remain brand-scoped reusable assets across
   campaigns (consistent with Q1's economics ruling).
4. **The `tenant_id` vs `client_id` naming debt is resolved by the chain**: workspace = the
   client org = the tenancy root. The long-standing backlog item ("harmonize at leisure") now has
   its target shape; the actual rename/migration is an implementation task to schedule, not a
   blocker.
5. Adopting the pack's spine means our scope keys match the treaty's entity vocabulary 1:1
   (Workspace → Brand → {Products, Accounts, Campaigns}), simplifying the memory endpoints and
   every cross-contract surface.

Left for the design discussion (details, not decisions): the canonical column name for the
tenancy root (`workspace_id` vs keeping `tenant_id` as an alias), whether `brand_id` is stamped
on rows now or derived via workspace while 1:1, and migration sequencing for the rename.

## Q4 — Boundary with the M13.3 learning loop — **CLOSED 2026-07-07**

**Ruling: the two learning systems stay separate, and the gray zone defaults to memory,
applied suggestively.**

1. **Config learning stays config.** M13.3 tunes engine behavior from measured evidence (source
   yields, signal discriminating power) through versioned, reviewed config revisions — never a
   memory blob. Unchanged.
2. **Scoped memory holds conversational/behavioral learnings** not expressible as config.
3. **Gray-zone experiential learnings ("this ROI framing wins with clinical buyers") → memory.**
   They arise conversationally — recorded from chats between user and agent as *what was
   accepted / what worked* — and land at the narrowest correct scope (here: product).
4. **Memory is advisory; config is binding.** In a similar future scenario the deep agent is
   *suggestive* from memory ("last time, this framing worked with clinical buyers") — it informs
   the agent's proposals; the user still decides. A config revision, by contrast, changes engine
   behavior deterministically. This gives the decision rule: **must it change system behavior
   deterministically → config (M13.3 path); should it inform/suggest → memory.**
5. Coheres with "LLM proposes, engine disposes": memory feeds the *proposing* side; config
   governs the *disposing* side. The pack's account-scoped "outcome history" is experiential →
   memory; measured yields/weights remain config.

Parked for the design discussion (optional, not decided): a graduation bridge — whether a
memory-recorded pattern that accumulates strong evidence can be *proposed* into an M13.3 config
revision (through its normal human-reviewed pipeline), so the two systems connect without
merging.

## Q5 — Tenancy of memory — **CLOSED 2026-07-07**

**Ruling: memory is always tenant-private, never reuse-scoped.** Nothing learned in one
workspace ever crosses to another — even for the same target account domain. This is the
opposite default from `public_footprint` claims, deliberately: claims about the public world can
amortize across tenants; learnings about a client's preferences and what worked for them are the
client's alone. The agency case (one user in many workspaces) changes **auth, not memory** —
no cross-workspace memory access rides on a shared user.

Enforcement note (follows from Q2's trust-no-writer pattern): tenant-privacy is enforced
**fail-closed at the substrate**, like `reuse_scope` on claims — no writer stamping and no
reader query can produce cross-tenant leakage, structurally.

## Q6 — Documentation shape — **CLOSED 2026-07-07**

**Ruling: scoped memory + context assembly gets its own architecture doc**, with references and
hooks in the main harness architecture doc (the same pattern compliance got with Doc D).
Founder rationale: *memory is the company's second brain — it builds the moat over time* — a
load-bearing substrate in its own right (consistent with Q2's "second shared substrate" ruling),
not a feature section. The doc gets written in the documentation phase, **after** the
mechanism/storage design discussion.

---

## Status: Q1–Q6 all CLOSED (2026-07-07)

Next, per the founder's staged process:
1. **Design discussion** — the memory *mechanism* and *storage format* (explicitly not yet
   discussed; pack mechanics are reference input only). Agenda candidates: record shape; scope
   keying over the new spine; lifecycle mechanics (born-trust, review queue, promotion, decay,
   eviction); the two seams' API shape; the context-assembly engine + recipes; bundle journaling
   on runs; fail-closed tenancy enforcement; interaction with M10 compliance for person-adjacent
   memories; the optional memory→config graduation bridge (Q4); claim-ref integrity
   (supersede/erasure of a referenced claim).
2. **Documentation** — the new standalone doc + hooks in
   `clue-hq-harness-architecture-and-requirements.md` (+ the repo-charter rewrite noted under Q2).

---

## Also still open (carried from the 2026-07-06 architecture-doc session)

- Commit posture for the uncommitted docs (proposal, comparison note, architecture doc, this file).
- Whether Recipe #0 recon includes a cheap candidate-account preview before ICP confirmation
  (the "Surprise me" card shows "possible accounts to reach").
- O4–O6 working defaults (recon envelope = cents; fact-capture = implicit-with-visibility; recon
  brief = chat + persistent artifact) — treat as decided or keep open.
- Terminology note: in the plan pack "harness" = their eval/grading rig; in our docs "harness" =
  the execution platform. This system is named **"scoped memory + context assembly"** to avoid
  the collision.
