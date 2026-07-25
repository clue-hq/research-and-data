# Clue-HQ — Research & Data Subsystem: Overview & Output Contract

### Read this first. It is the map; the other docs are the territory.

> **Scope note (platform-backend reframe).** This repo is the platform's **backend home**, organized as **subsystems behind shared substrates and seams**. This document maps its **first subsystem — data & research**; the **second — scoped memory & context assembly** — is Doc M (`clue-hq-scoped-memory-and-context-assembly.md`), the first substrate added under the harness era. Future subsystems land in the same repo under the same seam discipline. Where this doc says "this subsystem" it means the research subsystem specifically; "the repo" or "the platform backend" means the whole. The harness-era authoritative record is `clue-hq-harness-architecture-and-requirements.md`.

The two original architecture docs (`clue-hq-research-layer-architecture.md`, the **substrate doc**, and `clue-hq-discovery-and-research-staged-architecture.md`, the **staged-flow doc**) were written reacting to a scrappy prototype — they are organized around *not repeating its failures*. That framing is defensible but backwards for orientation. This doc derives the subsystem from the **outputs it must produce**, indexes the full document set, and pins the one boundary the originals left implicit: **what this subsystem hands downstream.**

Nothing here overturns the original two docs. The core bet still stands: *verifiability is a property of the data model (the typed claim with provenance), not a QA pass.* This doc adds the front edge, the output edge, and the cross-cutting governance the prototype never lived long enough to reach.

---

## 1. The four required outputs (the output-first spine)

Everything in the subsystem exists to produce exactly four things. If a component doesn't serve one of these, it's overhead.

**Output 1 — A scored, ICP-fit account list with evidence-backed signals.**
Every candidate account, whether we discovered it or the client imported it, carries: a fit score, an intent score, the **cheap deterministic signals** those scores are computed from (firmographic, technographic, growth, hiring, funding), and a provenance link behind every signal. No score without its evidence.
*Produced by:* Stage 0 → entry scenario (discover/import) → Pass A scoring. *See Docs B, C.*

**Output 2 — A verified, fully-sourced account profile per high-tier account.**
For accounts that clear the tier cutoff: the deep account picture — operational pain, strategic moves, and the **resonance layer** (culture, employee sentiment, frustrations) — every claim target-locked to the exact entity and backed by an evidence span, or left blank.
*Produced by:* M2 Account Profiling (deep pass). *See staged-flow §5, Doc C.*

**Output 3 — A buying committee per high-tier account, each contact identity-verified and deeply, *governed*, profiled.**
The committee (champion / economic buyer / technical evaluator / blocker), each person identity-resolved, each persona-tagged, each personal claim carrying an **identity-binding strength** and a **use-class** so only true, right-person, *and lawful/appropriate* hooks can drive outreach.
*Produced by:* M3 Committee Discovery + M4 Contact Profiling. *See staged-flow §6, Docs C, D.*

**Output 4 — A persona-keyed, evidence-backed claim bundle + grounded value narrative.**
The actual handoff to content/design: not raw facts, but facts *plus the argument* — per persona — for why the client's product matters to this account, every line of that argument sourced on both sides (account evidence × client capability). This is the subsystem's product. *See §3 below.*

---

## 2. End-to-end map

```
STAGE 0  Client & ICP  (Doc B)
  client name + website (worst case)
     → Client Reverse-Profiling → Client Knowledge Base
     → ICP Synthesis → propose ICP(s) → client edits/confirms (always has the wheel)
     → versioned ICP spec(s): field set + discovery strategy + source profile + scoring rubric
                 │
        ┌────────┴─────────┐
   SCENARIO A          SCENARIO B
   we discover         client imports list
   M1 Account          bulk identity-resolution
   Discovery           + ICP back-scoring
   (grounded only)     (flag non-fitting accounts)
        └────────┬─────────┘   (hybrid: import list = seeds for lookalike discovery)
                 ▼
   PASS A  cheap, deterministic-heavy fit + intent on ALL accounts  →  tiering
                 │
        ── human checkpoint: review/adjust tier cutoffs ──
                 │  (high tiers only; depth scales with tier)
                 ▼
   PASS B  M2 Account Profiling · M3 Committee Discovery · M4 Contact Profiling
           (deep, target-locked, identity-bound, governed)   (Docs C, D)
                 │
        Verification (gates · corroboration · faithfulness judge · identity-binding · use-gate · freshness)
                 │
   OUTPUT  persona-keyed claims + grounded value narrative   →  [ Content layer → Design subsystem ]
                 │
        Human review (Tier-1) → disposition + source-yield feedback → reweight scoring & source profiles
```

This refines the staged-flow doc's §10 sequence by making Stage 0 (Doc B) and the two entry scenarios first-class, and by inserting the output contract (§3) at the hand-off.

---

## 3. The output contract — where this subsystem ends

The single most important boundary decision. There are **three layers** of output; the subsystem owns the first two and stops there.

| Layer | What it is | Owner |
|---|---|---|
| **Raw claims** | Verified atomic facts, each sourced and typed. "Acme runs Snowflake" [src]; "eng headcount +40% YoY" [src]. Persona-agnostic. | **Research subsystem** |
| **Value narrative** | The synthesized *argument* joining claims to the client's capabilities, shaped per persona, itself a claim-with-provenance pointing at both the account evidence and the client evidence. The "ammunition." | **Research subsystem** |
| **Content schema / content** | The artifact-shaped output (mailer headline/body/CTA slots; landing-page sections) the design agent maps into a template. Artifact- and template-specific. | **Downstream content layer** (not this repo) |

**Recommended boundary:** research stops at the value narrative. A content schema is a function of artifact type (mailer vs. landing page vs. ad) and the design template — neither of which research should need to know — so binding research to it would couple the subsystem to one artifact type. By stopping at *verified meaning*, one research output feeds mailers, landing pages, ads, and emails alike.

**The contract object handed across the boundary** (illustrative, per high-tier account):

```
account_handoff
  account_entity_id
  fit_score, intent_score        (decomposed, each linked to its claims — Output 1)
  account_profile_claims[]       (verified, sourced — Output 2; incl. resonance claims)
  committee[]                    (Output 3)
    contact_entity_id, persona, role_on_committee
    profile_claims[]             (each: value, evidence_span, source_tier,
                                  identity_binding, use_class)
  value_narrative[]              (Output 4; per (account, persona))
    claim_id                     (the narrative is itself a provenance-backed claim)
    persona
    argument                     (the grounded "why we matter / which angle")
    supporting: account_evidence_ids[] + client_knowledge_ids[]
  provenance_index               (every fact → its source, so "every line is sourced" is literally true)
```

> **Open dependency — confirm before finalizing:** what does the already-built design subsystem actually ingest? If it consumes a content schema directly (rather than research output via a content layer), the content layer must produce that schema and research must feed it the right primitives. The recommended boundary above assumes a content layer sits between research and design. *Tracked in §5.*

---

## 4. Document index & reading order

1. **This doc** — overview, the four outputs, end-to-end map, output contract, open decisions.
2. **`clue-hq-research-layer-architecture.md`** (substrate) — claim store, identity resolution, field registry + packs, the trust-tiered source waterfall, per-account execution, verification layer, scoring, build order, stack. *The spine. Unchanged.*
3. **`clue-hq-discovery-and-research-staged-architecture.md`** (staged flow) — the 2×2 of research modes (M1–M4), Stage 0, the Source Intelligence Layer. *Unchanged; extended by Docs B and C.*
4. **`clue-hq-stage0-client-and-icp.md`** (Doc B) — the front edge: client reverse-profiling, ICP synthesis, and the two entry scenarios. *Extends substrate §8 and staged-flow §2.*
5. **`clue-hq-signal-execution-cost.md`** (Doc C) — the two-tier signal model, new resonance/personal-facet field-classes, the bounded two-level fan-out, campaign-level orchestration, cost governance, observability. *Extends substrate §3, §5 and staged-flow §4.*
6. **`clue-hq-compliance-and-personal-data.md`** (Doc D) — jurisdiction switch, use-class taxonomy, the appropriateness/use gate, lawful basis, and the three deep-research postures. *Extends substrate §6 and staged-flow §6, §8.*
7. **`clue-hq-scoped-memory-and-context-assembly.md`** (Doc M) — the **second shared substrate** beside the claim store: the five-scope (workspace/brand/product/campaign/account) preference & behavioral-learning store behind two seams, deterministic context assembly, freshness/caps/eviction, and its DSAR surface. *Harness-era; extends the harness architecture doc the way Doc D extends the substrate. Facts stay claims — memory holds only advisory preferences/learnings.*
8. **`clue-hq-platform-agent-runtime.md`** (Doc A) — the binding agentic taxonomy (tool / skill / worker fleet / deepagent), the platform deepagent's anatomy, the seven-layer context-assembly pipeline, and product profiles. *Harness-era.*
9. **`clue-hq-content-and-artifact-scaling.md`** (Doc S) — the content plane between research handoff and the design engine: content schema ↔ slot contract, template finalization, per-account/contact scaled derivation. *Harness-era; resolves D2.*

> **Harness-era note.** Entries 1–6 are the substrate-era doc set and remain authoritative for the data layer. The platform has since pivoted to a deep-agent harness; the authoritative statement of that era is **`clue-hq-harness-architecture-and-requirements.md`** (with `clue-hq-harness-replatform-proposal.md` as its evidence trail), and **Doc M** (entry 7) is the first substrate added under it.

---

## 5. Open-decisions register

Decisions that shape the docs and are deliberately left to the founders / data-and-compliance owner. Nothing below is hardcoded until resolved.

| # | Decision | Current state | Owner |
|---|---|---|---|
| D1 | **Output boundary** — claims only vs. + value narrative vs. through content schema | Recommended: **+ value narrative** (§3). Assumed in all docs, pending confirm. | Founders |
| D2 | **Design-subsystem interface** — what does the built design system ingest? | **Resolved (2026-07-16):** binding sets validated against a frozen template slot contract, produced by the content plane — a content layer sits between research and design exactly as §3 recommended. See Doc S (`clue-hq-content-and-artifact-scaling.md`). | — |
| D3 | **Personal-data posture** — conservative-default vs. gather-broadly-gate-at-use vs. professional-only | All three documented as per-client config (Doc D); decision deferred. | Data/compliance owner |
| D4 | **Contact geography** | **Resolved: mixed/global** → jurisdiction is a first-class per-client switch (Doc D). | — |
| D5 | **ICP multiplicity** — one ICP per client vs. several segments | Recommended: **support multiple ICPs**, each compiles its own plan (Doc B). | Founders |
| D6 | **Import-list non-fit behavior** — flag vs. exclude vs. re-derive ICP | Recommended: **flag + proceed**, surface to client (Doc B). | Founders |
| D7 | **Economics defaults** — per-pass budgets, % that goes deep, cost pass-through | Defaults proposed in Doc C; confirm against real campaign sizes. | Founders |
| D8 | **2026 legal specifics** — current US state laws, EU AI Act touchpoints, DPA scraping stances | To verify before operationalizing Doc D. | Data/compliance owner (+ research pass) |
