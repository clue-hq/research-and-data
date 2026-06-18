# Clue-HQ — Discovery & Research: Staged Architecture
### Companion to the main research-layer architecture doc

Research is the foundation everything else stands on, so this document treats it with the precision it deserves. It refines, rather than replaces, the main architecture: the claim store, identity service, packs, waterfall, verification layer, two-pass economics and feedback loop all stand. What this adds is the missing structural truth — **"research" is not one operation. It is four, plus a collaborative front stage** — and the subsystem that makes the platform *intelligent about where to look*.

Illustrative schemas below are starting points, not final DDL.

---

## 1. The core reframe: research is a 2×2 of modes

Two axes:

- **Objective** — *Discovery* (open-ended: find entities matching a fuzzy ICP; optimized for **recall**) vs *Profiling* (closed/target-locked: fill the schema of an already-identified entity; optimized for **precision** and resistance to drift).
- **Level** — *Account* vs *Contact*.

|              | **Discovery (open-ended, recall)** | **Profiling (closed, target-locked, precision)** |
|--------------|-----------------------------------|--------------------------------------------------|
| **Account**  | **M1 — Account Discovery**        | **M2 — Account Profiling**                       |
| **Contact**  | **M3 — Committee Discovery**      | **M4 — Contact Profiling**                       |

Preceded by **Stage 0 — ICP Co-definition** (collaborative), which plans all four.

Each mode has its own orchestration pattern, source strategy, verification emphasis, output type, and cost profile. The single most important consequence: **discovery and profiling fail in opposite ways and need opposite safeguards.** A single research agent collapses this distinction and inherits both failure modes — which is what the prototype did.

> "Closed" does not mean a closed corpus. M2/M4 are still open-web; "closed" means **bounded and target-locked** to one resolved entity ("this exact company / person, do not drift"), versus discovery's **unbounded** search for unknown entities.

---

## 2. Stage 0 — ICP Co-definition (collaborative)

The platform must be intelligent about *what to do* with an ICP, while always letting the client contribute as much as they can about *whom* to target. This is an elicitation loop, not a form.

**Flow:** the client gives a vague description ("we sell observability tooling to frontier AI labs") → the platform proposes a structured ICP (firmographic dimensions, candidate signals, **seed accounts**, and a starting **source profile** for this industry) → the client edits, adds, removes, confirms. The platform suggests; the client always has the wheel.

**Output — a structured, versioned ICP spec that plans the next three stages.** It compiles (the research-plan builder / "schema resolver" from the main doc) into:

- the **active field set** (core + industry packs) — *what to know* about each account/contact;
- the **discovery strategy** for M1 (which channels, which ICP filters, which seeds for lookalikes);
- the **source profile** for M2/M4 (per-source priors/weights for this ICP — see §7);
- the **scoring rubric** (fit + intent weights over the active fields).

This is the contract the rest of the subsystem executes against. Reproducible because it is versioned.

---

## 3. M1 — Account Discovery (open-ended, **grounded only**)

Goal: produce a candidate account set with high recall — including companies the client didn't know existed.

**The non-negotiable principle: retrieval-grounded discovery, never parametric listing.** Candidates may only originate from *real returned records or URLs*:

- structured-DB ICP-filtered search (Clay / Apollo / ZoomInfo company search);
- web entity discovery (Exa Websets, Parallel FindAll-style) returning real domains;
- curated lists / directories / association membership / conference exhibitor lists;
- **lookalike expansion** from the client's seed accounts and existing customers (CRM).

What is **forbidden:** asking an LLM to "name 50 companies that fit." That is generation-from-memory and is the exact source of the prototype's fabricated accounts. The LLM may *plan and expand queries*; it may not *be* the source of entities.

**Orchestration — the *expand* pattern.** Parallel discovery queries across the planned channels, casting wide; results streamed into the identity service for dedup; a **stopping rule** on marginal yield (new-candidate rate drops below threshold) or a discovery budget cap, because open-ended search otherwise runs forever.

**The existence / identity gate (the anti-fabrication spine for this axis).** A discovered candidate is a *hypothesis*, not an account. Before admission it must resolve to a real canonical entity (live domain, corroborating record) via the identity service. Only then does it become an account entity, carrying **discovery-provenance**: where it was found, the matched signal, the discovery confidence. A hallucinated entity has nothing to resolve to and dies here, before a cent of profiling spend.

Output: admitted candidate accounts with discovery-provenance. **No deep facts yet** — verification at this stage is existence + cheap ICP-match plausibility only.

---

## 4. Bridge — Scoring pass + tiering (per main doc §5)

Discovered accounts flow into **Pass A**: cheap, deterministic-heavy fit + intent scoring on *all* of them → tier assignment → human checkpoint on cutoffs. Expensive profiling (M2, M3, M4) runs **only on high tiers**. Discovery is wide and cheap; profiling is narrow and deep. This is where the unit economics live.

---

## 5. M2 — Account Profiling (closed, target-locked)

Goal: fill the resolved account's field schema with verified, sourced claims. Precision over recall.

**Orchestration — the *converge* pattern.** A bounded, checklist-driven loop: read the active field schema + current claims, identify gap-fields, fill them, stop when the schema is satisfied or sources are exhausted. The opposite shape from discovery's open-ended expansion. The orchestrator/worker topology (parallel field-cluster workers, no cross-talk, writing claims back) from the main doc lives here.

**Target-lock (the anti-drift spine).** Every query and synthesis is bound to the resolved entity: entity-scoped queries (`site:` the canonical domain, canonical name + geo/disambiguators), and synthesized claims must cite entity-bound evidence. The prototype's "do not drift to similarly-named orgs" prompt, promoted to a structural constraint of the mode.

**Sources:** the trust-tiered waterfall (deterministic → official → third-party → synthesis). *Which* open-web sources are consulted within the synthesis tier is chosen by the **Source Planner** (§7) using the ICP's source profile — not a fixed list.

**Verification:** provenance + corroboration + faithfulness judge + freshness (main doc §6).

---

## 6. M3 — Committee Discovery & M4 — Contact Profiling

The account is the *what*; the committee is the *who*. Both are required (main doc §7), and they are themselves a discovery step followed by a profiling step.

**M3 — Committee Discovery (bounded discovery).** Within a known account, find the relevant people and hypothesize each one's role (champion / economic buyer / technical evaluator / blocker). Bounded universe (this company's people). Sources: people/org APIs (Apollo, ZoomInfo, LinkedIn), the account's own team/leadership pages, signal of who's publicly active. Each candidate person is **identity-resolved** (LinkedIn URL / verified email) and gated before admission — same existence-gate discipline as M1, one level down.

**M4 — Contact Profiling (closed, target-locked per person) — where open-internet heterogeneity truly bites.** "Everything publicly true about *this verified person*": role-relevant background, what they've posted, podcasts they've been on, talks, publications, stated interests. This is the mode that consumes YouTube/Vimeo, X/Substack/Medium, journals, podcasts — the long tail (handled by the Source Intelligence Layer, §7).

**Identity-binding is the make-or-break safeguard for M4.** Getting a personal fact *wrong* in 1:1 outreach is worse than omitting it. Every personal claim carries an `identity_binding` strength:

- **strong** — evidence is on the person's *verified* profile/handle, or co-occurs with multiple strong identifiers (name + employer + role + location);
- **weak** — name match only (the same-name trap).

Weak-binding personal claims are **not promoted** and **never drive outreach**. Better an empty "personal hook" field than someone else's hobby in the mailer. This is the contact-axis analogue of the evidence-span rule for facts.

---

## 7. The Source Intelligence Layer (the "intelligent about which sources for what" subsystem)

Sits parallel to the field registry. Fields say *what to know*; this says *where to learn it, and how much to trust each place — per industry, per ICP, and improving over time*. Five parts:

**(a) Source Registry.** Every source — structured API, web search, scraper, social platform, video host, podcast index, journal/preprint index — registers a capability manifest:

```
source_manifest
  source_key            "arxiv" | "youtube" | "apollo" | "g2" | "substack" ...
  modality              text | video | audio | pdf | structured
  entity_scope          account | contact | both
  yields                field_keys / field-classes it can populate
  tier                  1..4
  cost, latency
  geo_coverage
  freshness_profile
  identity_binding_strength   how tightly its data ties to a specific entity
```

**(b) Modality adapters — heterogeneity by registration, not enumeration.** A source isn't just "fetch URL"; many require *fetch → adapt → extract*. Video and podcasts go through transcription, PDFs/journals through text extraction, before claim extraction. Adding "anything on the internet" = registering a manifest + (if needed) an adapter. This is the architectural answer to your non-exhaustive list: the system is *open by construction*, like the field registry.

**(c) Source Profiles (per ICP / per pack).** Priors that weight and prioritize sources per field-class for an industry. Authored into packs, overridable per client. Examples:

- `frontier_ai` → arXiv / Semantic Scholar **high**, GitHub **high**, research-X **high**, press releases **medium**, Glassdoor **low**.
- `healthcare_practice` → NPI / CMS **high** (deterministic), Google/Places reviews **high**, job boards **high**, journals **low**.
- `data_infra` → job-posting tech mentions **high**, BuiltWith **high**, engineering blogs **medium**.

**(d) Source Planner.** Given (mode, entity, objective/field, ICP source profile), it selects and orders the source set to consult. **Config-bounded LLM planning:** the planner may expand specific queries and pick among sources, but only *within the pack's allowed, weighted set* — resolving the rigidity-vs-fabrication tension (pure config can't adapt; pure LLM is unbounded in cost and invention). For M2/M4 it also decides when an expensive modality (transcribe a 90-min podcast) is worth triggering — gated to high-tier entities and to profiles where that source class is weighted high.

**(e) Learning loop — how source importance honestly "adjusts per industry."** Profiles start as curated priors and are reweighted by *measured outcomes*, which your provenance layer already records for free. Per (ICP, field-class, source) track: precision (claims that survived verification), coverage (fields filled), freshness, cost, and downstream signal (did claims from this source drive accepted accounts / replies via the disposition feedback loop). Reweight accordingly. Start with priors, learn from yield — not autonomous magic, but a real adaptive loop.

---

## 8. Mode-specific anti-hallucination (mapped to the prototype's failures)

| Mode | Prototype failure it prevents | Mechanism |
|------|------------------------------|-----------|
| M1 Account Discovery | Made-up companies | Grounded-only candidates + existence/identity gate before admission |
| M2 Account Profiling | Fabricated facts, drift to wrong company | Target-lock + evidence-span requirement + faithfulness judge |
| M3 Committee Discovery | Invented / wrong people | Person identity-resolution + role plausibility gate |
| M4 Contact Profiling | Misattributed personal facts (same-name) | Identity-binding strength; weak-binding claims never promoted |

Universal rule across all modes: **an empty, flagged field is a correct output; fabrication is the only real failure.**

---

## 9. How it composes with the existing architecture

- **Claim store** gains a `research_mode` dimension and two provenance flavors: *discovery-provenance* (M1/M3: where an entity was found and why it matched) and *field-claim provenance* (M2/M4: value + evidence span + source + tier + `identity_binding` for contact claims). One substrate, richer typing.
- **Identity service** is the shared backbone for both axes: it powers the discovery existence-gate *and* the profiling target-lock — a discovered candidate must resolve through it, and a profiling run is bound to the entity it returns.
- **Packs** now carry two prior sets: the field set (what to know) *and* the source profile (where to look). Same per-industry extensibility story.
- **Verification layer** extends with identity-binding for contacts; everything else (gates, corroboration, judge, freshness, evals) is unchanged.
- **Feedback loop** now reweights *sources* (this doc §7e) in addition to scoring — the same disposition signal, pointed at one more target.
- **Two-pass economics** sit exactly where they did: between M1 and {M2, M3, M4}.

---

## 10. End-to-end sequence

```
Stage 0  ICP Co-definition (collaborative)
           → versioned ICP spec: field set + discovery strategy + source profile + scoring rubric
                  │
M1   Account Discovery (open, grounded)  → existence/identity gate → candidate accounts
                  │
PASS A   cheap fit/intent on ALL accounts → tiering → human checkpoint on cutoffs
                  │  (high tiers only, depth scales with tier)
                  ▼
M2   Account Profiling (closed, target-locked)        ── waterfall + Source Planner
M3   Committee Discovery (bounded)  → person gates
M4   Contact Profiling (closed, identity-bound)       ── waterfall + Source Planner
                  │
        Verification (gates · corroboration · faithfulness judge · identity-binding · freshness)
                  │
        Explainable fit/intent scores + persona-keyed, fully-sourced claims
                  │
        Human review (Tier-1) → Design / Content module     ┐
                  │                                          │ disposition + source-yield
                  └──────────────────────────────────────────┘  feedback → reweight scoring & source profiles
```

**The discipline in one line:** discovery is wide, cheap, and grounded; profiling is narrow, deep, and target-locked; sources are chosen by per-industry priors that learn from outcomes; and nothing — no entity, no fact, no personal hook — enters the store without surviving the gate appropriate to its mode.
