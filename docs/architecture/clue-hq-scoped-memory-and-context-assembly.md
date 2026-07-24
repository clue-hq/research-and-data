# Clue-HQ — Scoped Memory & Context Assembly (Doc M)

> **Status: CONFIRMED design record** (v1.0, 2026-07-11). This document consolidates the
> scoped-memory decisions notepad (`clue-hq-scoped-memory-decisions-notepad.md`, Q1–Q6, closed
> 2026-07-07) with the mechanism/storage design discussion of 2026-07-08 → 2026-07-11 (memory
> landscape research report; form/storage/write/read rulings; lifecycle; caps/eviction; Q7 DSAR;
> Q8 kill-switch) into one complete statement of the memory subsystem's model, mechanisms, and
> plan.
>
> **Authority.** For the scoped-memory + context-assembly system this document is authoritative;
> it supersedes the decisions notepad as the authoritative statement (the notepad remains the
> decision trail). The harness architecture doc
> (`clue-hq-harness-architecture-and-requirements.md`) remains authoritative for the harness era
> at large; this document extends it the way Doc D extended the substrate — nothing here weakens
> anything there. The industry research that informed the mechanism is the memory-landscape
> report (2026-07-08); it is evidence, not spec.
>
> **Naming.** This system is **"scoped memory + context assembly"** — never "harness" (which is
> the execution platform in our vocabulary, and the co-founder's eval rig in theirs), and never
> "the context graph" (we build a native substrate, not an embedded product).
>
> **Reading map.** Part I — what memory is here, and what it is not. Part II — the memory model
> (record shape, scopes, statuses). Part III — the two seams (write path, read path / assembly).
> Part IV — lifecycle (freshness, supersession, caps/eviction). Part V — compliance & personal
> data (Q7). Part VI — the workspace kill-switch (Q8). Part VII — deferred mechanisms and their
> named triggers. Part VIII — build plan, acceptance criteria, harness-doc hooks, pre-mortem,
> non-goals.

---

## Part I — Context

### 1. What this subsystem is

Scoped memory is the platform's **second shared substrate**, beside the claim store (Q2). It is
the accumulating record of **client preferences and behavioral learnings** — brand voice rules,
framings that work per buyer type, campaign style choices, account-level behavioral insights —
organized over the platform's object spine and assembled deterministically into agent context at
recipe execution time. It is the mechanism behind the product promise that the **Nth campaign is
better than the first**: each kickoff starts pre-loaded with what prior campaigns taught.

It is a **native living system of record** of this platform. Subsystems communicate with it only
through its two seams (never by importing it); every future subsystem in this repo is a
writer/reader through the same seams.

### 2. The species split (the load-bearing decision — Q1)

Two species of knowledge, two substrates, never mixed:

| Species | Substrate | Nature | Examples |
|---|---|---|---|
| **Facts** — verifiable statements about the world | Claim store (CKB) | Binding-verified: evidence span, tier, faithfulness judge | "Account X raised a Series C"; "their CFO joined in 2024" |
| **Preferences / behavioral learnings** | Scoped memory (this doc) | Advisory: informs proposals, never binds | "never use fear-based hooks"; "ROI framing wins with clinical buyers"; "this champion prefers short, numbers-first emails" |

Three consequences, all binding:

1. **A memory record may reference a claim by id, never duplicate its content.** The pack's
   `kind: "fact"` memory does not exist here. (Dual-truth pre-mortem guard #6.)
2. **Memory is advisory; config is binding** (Q4). Memory feeds the *proposing* side of
   "LLM proposes, engine disposes"; versioned config (incl. M13.3 learning) governs the
   *disposing* side. The routing rule: *must change system behavior deterministically → config;
   should inform/suggest → memory; verifiable statement about the world → claim.*
3. **ICP definitions are never memory** (Q1.4). An ICP is versioned `icp_spec` config, pinned per
   campaign; any memory mention of an ICP is a reference.

A negative design decision worth recording: because everything that must win unconditionally
(compliance postures, budget caps, jurisdiction policy) is config — not memory — this system
needs **no "authoritative scope" precedence inversion** (the Claude-Code enterprise-policy
pattern). Nothing authoritative lives in memory; the paradox never forms.

### 3. Inherited invariants

- **Tenant-private, always** (Q5). Nothing learned in one workspace ever crosses to another —
  the opposite default from `public_footprint` claims, deliberately. Enforced **fail-closed at
  the substrate**, like `reuse_scope` on claims: no writer stamping and no reader query can
  produce cross-tenant leakage, structurally. The agency case (one user, many workspaces)
  changes auth, not memory.
- **Two enforced seams, no path around them** (Q2). All writers submit through one API; all
  consumers receive context through one assembly engine. Lifecycle rules, tenancy, caps,
  compliance are enforced at the seams, identically for every writer/reader.
- **The seams are the contract; the substrate is swappable.** V1 storage is Postgres in this
  repo (append-only tables, Alembic conventions). No graph DB, no vector store in v1 — see
  Part VII for the named triggers that would change this.
- **Determinism at the engine, judgment at the agent.** Selection into context is a
  deterministic query, never retrieval-vibes (Q1.3). Reconciliation of *advice* is the agent's
  job; arbitration of *records* is the engine's.

---

## Part II — The memory model

### 4. Scopes (the Q3 spine)

Scope keys are the platform's canonical object spine:

```
workspace (= current tenancy root)
  ├── brand (zero or many brand kits)
  │     └── product
  ├── project (selects exactly one same-workspace brand; product optional)
  └── account (workspace-local target; brand-neutral)
```

> **Ownership ruling (2026-07-24).** A workspace owns multiple brand kits. A project selects
> exactly one of its workspace's brands. Target accounts do not belong to a brand; the selected
> project's brand supplies the sender context when work is performed for an account. A future
> customer-account/subscription layer may own one or more workspaces, but it is not part of this
> object-spine change.

> **Naming note (2026-07-17, founder-confirmed).** Under the harness doc's §1a terminology
> ruling (project ⊃ campaigns), the scope this document calls `campaign` is the **project**
> object. The memory tables are new code with no rename-churn concern, so the `scope_type` enum
> is named **`project` from birth**: `{workspace, brand, product, project, account}`. This
> document retains "campaign" in prose until its own revision; read campaign-scope → project.

Precision that the "five scopes" shorthand hides: database ownership and an assembled context
stack are not the same relationship. A product belongs to a brand; a project and target account
belong to the workspace; the project selects the brand and references target accounts. Context
assembly therefore combines the selected objects for one task rather than pretending they form
one containment chain. Consequences:

- **"Most-specific-wins" is only defined along a real parent-child chain.** Between the selected
  product, project, and account there is no "more specific" — they are orthogonal axes
  (offering / intent / audience). Cross-branch tension is therefore **surfaced, not resolved**
  (§10).
- **Workspace memory is its own shared layer**, above any selected brand, and remains the tenancy
  anchor and kill-switch scope.
- A typical recipe execution carries a scope **stack**:
  `(workspace, selected brand, product?, project, account?)`.
- **Persistence differs by branch.** Account- and product-scoped memories persist across
  projects. Project-scoped memories live and die with their project; on a reactivation-style
  project (e.g. annual), the prior project's memories surface only as **kickoff seeds** (§13),
  and "how it was run" is a **recipe** (plane 4), not memory.

### 5. The record shape

One table, `memory` (append-only in spirit: rows transition status, never silently mutate
content; content changes are supersessions). Fields, grouped:

**Identity & scope**
- `memory_id`
- `workspace_id` — tenancy root; every query is tenant-filtered at the seam, fail-closed
- `scope_type` ∈ {workspace, brand, product, campaign, account} + `scope_id` — the owning scope
  instance

**Content**
- `type` ∈ {`preference`, `behavioral_learning`} — the species tag (a finer type vocabulary is
  deferred; §17)
- `trigger` — short applicability description ("when writing outreach for clinical buyers…"),
  Devin-Knowledge style; used for labeling in v1, for selective matching later
- `body` — short, human-readable statement of the learning. **The body rule (write-seam
  enforced): the body carries the learning, never quoted personal-claim content.** Refs carry
  the facts; nothing smuggles content past the use gate.

**References** *(separate table)*
- `memory_claim_ref (memory_id, claim_id)` — indexed **both directions**. Forward serves
  assembly/labels; reverse serves the DSAR cascade and the reference-health staleness signal.
  One index, two consumers.

**Provenance & trust**
- `provenance_class` ∈ {`user_stated`, `edit_distilled`, `agent_observed`} — who produced it
- `trust_grade` — born from provenance class (§8), raised by confirmations, lowered by
  contradiction events
- `creating_quote` / source pointer — the conversational or diff evidence behind the record
  (carried over from the `client_memory` design)

**Status**
- `status` ∈ {`proposed`, `active`, `dormant`, `superseded`, `invalidated`, `locked`,
  `tombstoned`}
  - `proposed` — submitted, not yet activation-eligible (review queue or pattern-strength
    pending)
  - `active` — eligible for bundles
  - `dormant` — crowded out by the scope cap; still believed true; retains all metadata and
    signals; excluded from bundles, included in reconciliation and (future) search (§14)
  - `superseded` — replaced by a successor (`superseded_by` link); trail preserved
  - `invalidated` — shown wrong (contradiction), no successor
  - `locked` — Art. 21 objection lock: survives, excluded from every bundle (§16)
  - `tombstoned` — DSAR erasure (§16)
- Every status transition is journaled with actor/cause.

**Freshness (cycle-relative — no wall-clock fields drive behavior)**
- `confirmation_count`, `last_confirmed_at`, `cycles_since_confirmed` (kickoffs of the relevant
  scope since last confirmation; **off-cycles do not count** — §19)
- staleness signals are computed, not stored: reference health, scope churn, contradiction
  events (§12)

**Compliance**
- `subject_entity_id` (nullable) — resolved contact entity, **mandatory for any person-adjacent
  memory**, stamped fail-closed at the write seam (§16)
- `retention_class` — person-adjacent memories inherit the personal-claim minimization posture

### 6. What is deliberately absent from the record

No embedded claim content. No numeric blended scores. No wall-clock decay fields. No use-class
taxonomy (subject binding + retention class + objection lock covers memory's actual exposure;
a parallel use-class system would be machinery without a distinct job). No vector embedding
column in v1.

---

## Part III — The two seams

### 7. The write seam — submission

Every writer **submits** a candidate memory through one API; no writer inserts rows. V1 writers:

| Writer | Provenance class | Exists in v1? |
|---|---|---|
| Stage-0 / per-campaign kickoff interview | `user_stated` | Yes (slice 1) |
| Downstream distiller (artifact slot-diffs) | `edit_distilled` | No — depends on the content subsystem; the seam is ready for it |
| Agent observing mid-run | `agent_observed` | Yes, low-volume |

The seam enforces, identically for every writer: tenancy stamping (fail-closed), species check
(a fact-shaped submission is rejected toward the CKB path), the body rule, subject-binding
requirement for person-adjacent content (`PreconditionFailed` if absent — this one *is* an
error: the writer's proposal is malformed, not merely unwelcome), scope validity, kill-switch
state (§18), and reconciliation (§9).

### 8. Born trust (provenance-graded activation)

"LLM proposes, engine disposes," applied to memory writes:

- **`user_stated`** — the client literally said it in a governed interview → **born `active`**.
- **`edit_distilled`** — inferred from artifact edits → **born `proposed`**, activated on
  pattern strength (one edit is noise; the same edit across N artifacts is a preference).
  Thresholds are versioned config.
- **`agent_observed`** — an agent's mid-run inference → **born `proposed`**, queued to the
  treaty's `memory_review` queue for human review before activation.

This grading is also the memory-poisoning defense: untrusted content can never write an active
memory directly; activation is an engine decision at the seam, always.

### 9. Write-time reconciliation

Before any ADD, the seam reconciles the proposal against existing memories of the same scope and
type — **over `active ∪ dormant`, never active only**. Verdicts (LLM-assisted judgment, engine-
executed): ADD (genuinely new), UPDATE (refines an existing record → supersession with link),
DELETE-equivalent (contradicts → supersede/invalidate the old, trail preserved), NOOP
(restatement → increment `confirmation_count`, refresh freshness).

**The reactivation rule:** a match against a **dormant** record is treated as a promotion event —
the dormant record reactivates with its accumulated history (confirmation count incremented,
freshness reset), rather than a fresh ADD creating a zombie duplicate beside its dormant twin.
User re-statement is the strongest evidence an eviction was wrong. Frequent reactivations of
recently-evicted memories are the measurable signal that a cap is too tight (§15).

Same-scope, same-type contradictions are therefore **resolved at write time via supersession**;
the read path never arbitrates records.

### 10. The read seam — deterministic context assembly

Consumers never query memory storage. A recipe execution requests context for its task; the
assembly engine produces the bundle. **V1 is inject-only** — no search path (deferred with a
named trigger, §17).

The assembly pipeline, in full:

1. **Gate (deterministic filter):** `scope ∈ active stack` ∧ `type ∈ recipe's declared needs` ∧
   `status = active`, tenant-filtered fail-closed. Recipes declare which memory types they
   consume; a discovery recipe declaring none reads none — research unbiased by preference is a
   feature.
2. **Rank under bundle budgets:** one transparent **lexicographic sort** — `trust_grade`, then
   cycle-relative freshness, then `confirmation_count`. No blended numeric scores, no LLM-rated
   importance at read time. Ranking decides what fits the budget; it never decides who is
   *right*.
3. **Assemble in stability order:** brand → product → campaign → account. **This order is cache
   semantics (stable prefix first) and carries zero priority semantics.** All priority
   information lives in labels; position means nothing — stated here so no future implementer
   reads priority into position.
4. **Label everything:** scope, type, trigger, provenance class, trust grade, freshness,
   confirmation count, claim refs. The label *is* the reconciliation input for the agent.
5. **Journal the bundle** (§11).

**Cross-branch conflict posture (ruled):** when sibling-scope advice conflicts (campaign says
formal; account says this committee responds casual), the engine includes **both, labeled**, and
the agent reconciles at proposal time — legitimate because memory is advisory (Q4). The engine
never silently picks a winner across orthogonal axes. Every such labeled tension is journaled;
that journal is the empirical evidence from which a future type→scope validity matrix will be
designed (§17).

### 11. The bundle journal — a contractual surface

Every assembly writes a bundle-journal entry on the run graph: **memory ids + label metadata +
what was excluded by budget and why (the losing comparison)**. Never inlined bodies — the
toolbelt's "references, not blobs" rule extended to memory (this is what keeps DSAR from
becoming a journal-redaction debt; §16). Rendering a historical bundle dereferences live;
erased memories render as tombstones.

The journal is not a debug aid; it is the memory-layer extension of REQ-12's reproducibility
contract: *"what context did the agent see"* must be answerable definitively, and it is the
future answer to a client's "why did the artifact say this?" A client-facing projection of it
("what informed this artifact") is flagged for treaty review, not designed here.

---

## Part IV — Lifecycle

### 12. Freshness is cycle-relative and evidence-driven — never wall-clock

Time appears nowhere in staleness. The clock is **cycles and change events**, because for
low-cadence B2B (annual flagship campaigns) the calendar is a terrible proxy for "the world
changed" — an 11-month-old learning from the only prior run of an annual campaign is *one cycle
old* and likely the most valuable record in the scope. Staleness signals:

- **Reference health** — fraction of referenced claims still active. A superseded committee-
  contact claim (the champion left) presumptively stales every memory referencing it, regardless
  of age. Claim churn is a free, already-instrumented signal — the dual-substrate design paying
  rent.
- **Scope churn since write** — heavy claim churn at the owning scope (funding, leadership
  turnover, repositioning) flags pre-churn memories; a quiet account presumes fresh.
- **Contradiction events** — user edits cutting against a memory (the pack's "edited-against
  decay"): direct evidence, beats any clock; lowers trust, eventually supersedes, trail
  preserved.
- **Cycles-since-confirmed** — kickoffs of the relevant scope without reconfirmation
  (off-cycles excluded, §19).

No Ebbinghaus/wall-clock decay in v1 (the ChatGPT stale-preference failure was a
no-signal-that-things-changed problem, not a decay-math problem). Explicit **supersession, never
silent delete** — close the record's validity, link the successor, keep the trail (the
Graphiti insight, matching the claim store's append-only philosophy).

### 13. The kickoff interview is the re-confirmation gate

Per-campaign kickoff (Q1.5) is the freshness heartbeat most memory systems lack. At each
kickoff, the interview surfaces **only**:

- memories whose staleness signals actually fired ("last campaign we learned X about this
  account — still true?"), and
- prior-campaign-scoped **seeds** on a reactivation-style campaign (alongside the prior
  **recipe** — "run it the same way?" — which comes from plane 4, not from memory).

Confirm → freshness resets, counters reset, memory rides normally. Reject/amend → supersession.
High-trust, multiply-confirmed, healthy-referenced memories carry **silently** — surfacing
everything every kickoff teaches users to click through the gate, which is how gates die.
Prior-cycle memories never silently ride across a cycle boundary; injection across the boundary
requires passing this human-facing gate (suggestive, never forcible — structurally, because the
new campaign is a new scope instance).

Dormancy is **not** surfaced at the interview: dormant records are a priority question the sort
answers better than a user in a hurry; staleness questions only.

### 14. Store caps and dormancy

**Two distinct limits on opposite sides of the read seam** — never conflated:

| Mechanism | Side | Meaning of exclusion |
|---|---|---|
| **Store cap** (per scope instance) | Write/substrate | Record goes `dormant` — a status |
| **Bundle budget** (per recipe execution) | Read/assembly | Record merely lost today's ranking — journaled, still `active` |

`dormant` means **crowded out**: not contradicted, not wrong, not erased — below the cap line.
Dormant records retain trust grade, confirmations, refs; their staleness signals keep computing;
they participate in reconciliation (§9) and, later, search (§17). Store caps exist to keep the
active set human-auditable in one sitting, keep assembly O(small), force hygiene, and — most
usefully — to make **cap pressure a measurable signal** (§17).

### 15. Eviction and resurfacing

**Eviction order = bundle ranking inverted.** One lexicographic sort (trust, freshness,
confirmations), two consumers: what enters context and what stays active are decided by the same
transparent order, read from opposite ends. Structural guarantee: an unconfirmed
`agent_observed` hunch can never stay active while a multiply-confirmed `user_stated` rule goes
dormant. Every eviction is journaled with the losing comparison — an auditable sentence, not a
score.

Caps are **versioned config per scope type** (account small; brand perhaps larger), adjustable
per client via `config_revision`; the right numbers are an empirical question answered by the
pressure metric.

Dormant records resurface by exactly three paths:
1. **Automatic backfill** — a freed active slot (supersession, tombstone, lock) goes to the
   highest-ranked dormant record, deterministically, journaled.
2. **The future `search_memory` tool** (§17) — the dormant tail is precisely what it will query.
3. **Reconciliation reactivation** (§9) — user re-statement promotes the dormant twin with
   history intact.

No interview surfacing; no v1 consolidation pass (both gated on measured pressure, §17).

---

## Part V — Compliance & personal data (Q7 — closed 2026-07-11)

### 16. Person-adjacent memories are personal data, full stop

For learnings like "their champion prefers short, numbers-first emails," the personal data lives
**in the memory body itself** — no claim contains it. Honest consequence: **the memory substrate
joins the DSAR surface as a first-class citizen**, with the same tractability property the claim
store has — erasure resolves to a **deterministic query, never a substring scan**. The six
rulings:

1. **Subject binding, fail-closed at the write seam.** Any memory about an identifiable person
   carries `subject_entity_id` (same resolved contact key as claims). Stamped at write; a
   person-adjacent proposal without it is `PreconditionFailed`. Erasure = `WHERE
   subject_entity_id = :contact`.
2. **Claim refs are an indexed relation** (`memory_claim_ref`, both directions) — reverse lookup
   serves the cascade and the reference-health signal.
3. **Dangling-ref semantics by cause.** Referenced claim *superseded/aged-out* → staleness
   signal; memory survives; resurfaces at the interview gate. Referenced claim *erased* →
   subject-bound memories tombstone with the claims; incidental refs are severed, and severance
   is a hard staleness event.
4. **Journals and bundles carry memory ids, never bodies** (§11). Doc D's acceptance criterion
   extends: no personal substring of an erased value in any rendered bundle, journal view, or
   artifact — **structurally**, not by redaction sweeps. (Deliberately avoids a second
   `faithfulness_verdict.rationale`-style redaction debt.)
5. **Objection lock** (Art. 21, near-absolute for direct marketing — which a person-adjacent
   preference memory almost definitionally is): distinct `locked` status beside tombstone;
   memory survives, excluded from every bundle.
6. **Retention class on person-adjacent memories**, inheriting the personal-claim minimization
   posture; age-out reuses the staleness → interview-gate flow.

Boundary restated: **no use-class taxonomy on memory** (the appropriateness gate polices claims
entering artifacts; memory is advisory context) — but the **body rule** (§5) holds the line:
bodies never quote personal claim content, so nothing routes around the use gate.

DSAR access and rectification are served naturally: person-adjacent memories are short,
human-readable typed records keyed by subject.

---

## Part VI — The workspace kill-switch (Q8 — closed 2026-07-11)

### 17a. Semantics

One **workspace-level toggle**; memory read, write, and assembly on/off on demand.
Instant-effect user action (not a propose→promote ceremony), admin-gated in the treaty settings
surface, **audit-logged** (who, when — the audit entry is what makes journal claims of
"memory was off" verifiable).

Enforced at the two seams and nowhere else (there is no third path):

- **Write seam:** returns a quiet **typed no-op** (`memory_disabled`) — *not* an error; the user
  chose this state. But the no-op is typed precisely so skills honor it conversationally: the
  agent never implies retention that isn't happening ("since memory is off for this workspace, I
  won't carry this forward — want it in this campaign's brief instead?", said once, only when
  the user volunteers something memory-shaped). The statement can still land as brief content or
  a volunteered claim — facts and config never pause.
- **Read side:** the assembly engine **skips the memory step entirely** — no bundle object
  exists, no phantom "empty" artifact. Toggle state is recorded **once per run in the run
  manifest** (like any pinned config); a mid-run flip takes effect at the next seam call and is
  journaled as an **event** at its timestamp — no retroactive scrubbing of already-assembled
  context (which the journal has already truthfully recorded).

### 17b. What "off" is not

- **Off ≠ erasure.** The store freezes intact; toggling back on restores exactly what was there.
  Deletion is a different verb served by tombstone machinery — the settings UX must make this
  distinction visible.
- **Off does not pause DSAR.** Erasure, objection locks, retention age-out operate regardless —
  obligations attach to *holding* data, not using it.
- **Off does not stop fact capture.** Claims, ICP specs, M13.3 config learning continue; only
  the preference/learning species pauses. A memory-off client has a fully functional platform
  minus the "Nth campaign better than the first" compounding — the honest sentence for the
  settings UI.
- **Off-cycles don't age memories:** cycle counters increment only on kickoffs where memory was
  on (§12) — otherwise a client returns from two off-campaigns to a store wrongly flagged stale.
- **The interview degrades gracefully** to its fuller Stage-0-like form (no seeds, no
  re-confirmations — those are reads).

A per-campaign override ("run this one campaign memory-blind") is expressible later as a
scope-aware policy lookup at the same two checks; not built until asked.

---

## Part VII — Deferred mechanisms and their named triggers

Deferral discipline: nothing below is rejected; each is parked behind a **measurable trigger**,
and the v1 design already collects the evidence.

| Deferred | V1 posture | Named trigger to build it |
|---|---|---|
| **`search_memory` (pull-based retrieval)** | Inject-only bundles | Cap-eviction pressure: eligible-but-excluded rates from the bundle journal show tasks missing the dormant tail. Form is pre-decided: a **typed toolbelt tool** through the read seam, journaled like every tool — never a side channel; if semantic matching enters, it ranks *inside* the deterministic gate, never *as* the gate |
| **Consolidation pass** (background merge of near-duplicates) | Write-time reconciliation only | Same pressure metric; consolidation is a background LLM job with its own review/poisoning surface — unjustified at v1 volumes |
| **Type→scope validity matrix** (finer type vocabulary; which types may live at which scopes) | Two coarse types; cross-branch tension both-included-and-labeled | Journal evidence: accumulated labeled-conflict records tell us the real vocabulary. A premature matrix is a guess wearing the costume of rigor; wrong validity rules silently reject legitimate writes |
| **Memory→config graduation bridge** (Q4, parked) | None | A memory-recorded pattern accumulating strong evidence may be *proposed* into an M13.3 config revision through its normal human-reviewed pipeline — connects the two learning systems without merging them |
| **Vector/pgvector, graph storage** | Plain Postgres | Vector: only if trigger-matching at scale demands it (see search row). Graph: only if scope traversal or cross-memory relational queries become hot paths |
| **Per-campaign kill-switch override** | Workspace toggle only | User request |
| **Multi-brand** | **Shipped 2026-07-24:** workspace-owned brands; projects select one same-workspace brand | No longer deferred |

---

## Part VIII — Build plan, acceptance criteria, hooks

### 18. Build shape: thin vertical slice, then trailing depth

**Slice 1 — the demonstrable loop** (order of 3–5 focused engineer-weeks for the core
substrate): schema + migrations (`memory`, `memory_claim_ref`, status vocabulary, retention
class — all specified to the column level above); both seams; inject-only assembly with bundle
journaling; `user_stated` writer wired into the kickoff interview; kill-switch checks at both
seams (+ a day or two for the settings/audit surface). Demonstrable outcome: *"you told us X
last campaign; it showed up, labeled, in this campaign's context — and the journal proves it."*

The one genuinely hard component is **write-time reconciliation** (LLM-assisted
duplicate/update/contradiction judgment) — its quality determines store hygiene, and it ships
with the eval golden set beside it, because that part is iteration, not construction.

**Trailing before go-live:** DSAR cascade (lands with the rest of the Doc D backlog), caps/
eviction + dormancy, staleness signals, the `agent_observed` review queue (treaty
`memory_review` kind — as much a frontend question as a backend one).

**Explicitly not in v1:** the `edit_distilled` writer (depends on the content subsystem; the
seam is ready), everything in Part VII.

**Estimate honesty:** the figure above is the backend substrate. Review UX, the client-facing
"what does the system know about us" view, and treaty wiring are real work on the frontend/
treaty side. The durable cost of memory systems is never the initial build — it is
reconciliation quality and cap tuning over time; both are contained here by being journaled and
measurable, but contained is not zero.

### 19. Acceptance criteria (per part)

**Model & seams**
- No code path inserts or reads memory rows except through the two seams (import-boundary check,
  same machinery as the claim store).
- A fact-shaped submission is rejected at the write seam with the CKB path named.
- A memory body containing quoted personal-claim content is rejected (body-rule test).
- Cross-tenant leakage is structurally impossible: a fuzzed reader/writer matrix over workspaces
  produces zero cross-tenant rows/bundles (fail-closed test, mirrors `reuse_scope`).

**Write path**
- Born-trust matrix: `user_stated` → active; `edit_distilled` → proposed until pattern
  threshold; `agent_observed` → proposed + queued (provenance × status test).
- Reconciliation runs over active ∪ dormant; a re-stated dormant memory **reactivates with
  history intact** — never a duplicate ADD (zombie-twin test).
- Same-scope contradiction yields supersession with linked trail; the read path never serves
  both sides of a same-scope contradiction.

**Read path**
- Bundle assembly is reproducible: same store state + same recipe + same scope stack ⇒
  byte-identical bundle (determinism test).
- Every bundle journal entry lists included ids + labels and excluded ids + losing comparison;
  rendering a historical bundle after an erasure shows tombstones, never content.
- A recipe declaring no memory types receives no memory step at all.
- Cross-branch conflicting advice appears both-included-and-labeled (never silently dropped);
  the conflict is journaled.

**Lifecycle**
- Superseding a referenced claim flags (not kills) referencing memories; they surface at the
  next relevant kickoff (staleness → gate test).
- An annual-campaign fixture: an 11-month-old once-cycle-old memory ranks above a week-old
  unconfirmed `agent_observed` record (no-wall-clock test; trust inversion impossible).
- Eviction order equals bundle ranking inverted (property test over generated stores).

**Compliance (extends Doc D's criterion)**
- A DSAR erasure of a contact leaves no personal substring of the erased value in any served
  projection **including rendered bundles and journal views**; subject-bound memories are
  tombstoned; incidental refs severed with a hard staleness event (extended DSAR test).
- An objection lock excludes the memory from every subsequent bundle while preserving the row.

**Kill-switch**
- With memory off: write seam returns typed `memory_disabled` (not an error); interview skill's
  transcript never implies retention; assembly emits no memory step; run manifest records the
  state; a mid-run flip appears as one journaled event and subsequent nodes have no memory step.
- Off-cycles do not increment `cycles_since_confirmed` (freshness-fairness test).
- Toggle on → the store serves again unchanged (freeze-intact test).

### 20. Hooks into the harness architecture doc

To be added there (references only; this doc owns the design):

- **§5 data/config table:** replace the `client_memory` row with: *"Scoped memory — see Doc M;
  five-scope preference/learning substrate behind two seams; `memory` + `memory_claim_ref`
  tables; caps versioned config."*
- **REQ-08 (Stage 0):** kickoff interview is also the memory re-confirmation gate and the
  `user_stated` writer (Doc M §13, §7).
- **REQ-12 (reproducibility):** the bundle journal is the memory-layer extension of the run
  journal; run manifest carries memory-enabled state (Doc M §11, §17a).
- **REQ-15 (compliance):** person-adjacent memories join the DSAR surface (Doc M Part V).
- **REQ-16/17 (treaty):** §4.13 memory endpoints, `memory` SSE topic, `memory_review` queue
  kind, brief/confirm seeding; + flagged for treaty review: settings toggle surface, audit
  record, client-facing bundle-journal projection.
- **Decisions register:** Q1–Q6 (notepad, 2026-07-07), Q7 DSAR + Q8 kill-switch (this doc,
  2026-07-11), and the mechanism rulings (form/storage/write/read/lifecycle/caps — this doc).

### 21. Pre-mortem (named failure modes and their guards)

| Failure | Guard |
|---|---|
| Dual truth returns (facts leak into memory bodies) | Species check + body rule at the write seam; guard #6 test |
| Zombie duplicates (dormant twin + fresh ADD) | Reconciliation over active ∪ dormant; reactivation rule; zombie-twin test |
| Journal redaction debt (a second `rationale` mess) | Ids-never-bodies in journals/bundles, from day one |
| Trust inversion (recent hunch outranks confirmed rule) | Lexicographic sort with trust first; no recency-weighted scores; annual-campaign fixture |
| Retrieval-vibes creep | Inject-only v1; any future semantic matching ranks inside the deterministic gate, never as the gate |
| Position read as priority | §10.3 stated in the doc; labels carry all semantics |
| Interview fatigue kills the gate | Only fired-staleness + seeds surface; confirmed-healthy memories carry silently; dormancy never surfaces |
| Memory poisoning via untrusted content | Provenance-graded born trust; engine-gated activation; review queue for `agent_observed` |
| Agent implies retention while memory is off | Typed `memory_disabled` no-op + skill obligation + transcript test |
| Cap misconfiguration invisible | Eviction journaled with comparisons; reactivation-rate metric; caps as versioned config |

### 22. Non-goals (v1, explicit)

- No fact storage of any kind (facts are claims — the whole point).
- No cross-tenant memory reuse, ever (not a v1 deferral; a standing rule).
- No vector search, graph storage, or semantic retrieval; no LLM importance scoring at read
  time; no blended relevance scores.
- No wall-clock decay.
- No binding authority: memory never gates, never overrides config, never forces — it informs
  proposals. Anything that must bind is config and belongs to the disposing side.
- Not a context-graph product: this is a native substrate of this platform, full stop.
