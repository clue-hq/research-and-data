# Clue-HQ — Signal Model, Execution Depth, Cost & Observability

### Doc C. Extends the substrate doc §3 (field registry), §5 (execution) and the staged-flow doc §4 (the scoring bridge).

This doc resolves the central tension in the founders' product spec — *"discovery should carry rich signals for scoring"* vs. *"discovery must stay cheap and grounded"* — and specifies the parts the originals leave at the per-account level: how deep the fan-out goes, what a whole campaign run looks like, what it costs, and what the client sees while it runs.

---

## 1. The two-tier signal model (resolves "is discovery too shallow?")

Both instincts are right once you split each signal in two. **Every signal class has a cheap deterministic proxy and a deep synthesized narrative.**

- **Cheap proxy** — a deterministic, tier-1/2 fact, computed on **all** accounts in **Pass A**. Cheap enough to run on the whole discovered/imported list. This is the "signal-rich discovery" the founders want — it just lives in the scoring pass, deterministic-first, not in M1.
- **Deep narrative** — an expensive, often tier-4 *synthesis*, computed only on **high-tier** accounts in **Pass B**. This is the "why," the texture, the thing worth paying for once an account has earned it.

| Signal class | Cheap proxy (Pass A, all accounts) | Deep narrative (Pass B, high tier) |
|---|---|---|
| **Intent** | job-count delta (jobs API), recent funding event (Crunchbase), headcount growth (LinkedIn/API) — all tier-1 | synthesized *"why are they in-market"* — strategic moves, narrative read of multiple weak signals |
| **Growth** | headcount trend, funding stage, office/geo expansion (deterministic) | trajectory analysis, what the growth implies for the client's product |
| **Hiring** | open-req count, eng-req count (jobs API) | what the roles reveal about initiatives, stack shifts, pain |
| **Technographic** | BuiltWith / job-posting tech mentions (tier-1/2) | architecture inferences, migration signals, stack-fit reasoning |
| **Firmographic** | size band, revenue band, geo (deterministic) | — (rarely needs synthesis) |

**The principle to hold:** M1 discovery stays existence-only and grounded; **Pass A is signal-rich but deterministic-first and cheap**; depth (the narratives) is tier-gated to Pass B. The discovery-shallowness worry dissolves because the signals live in Pass A, not M1 — and they're cheap because they're proxies, not synthesis.

The research-plan builder (substrate §3) already tags fields *scoring* vs. *deep*; this doc makes explicit that **a single signal class spans both tags** — its proxy is `scoring`, its narrative is `deep`.

---

## 2. Field-class extensions (extends substrate §3 registry)

Two new field-classes, both **registered, not enumerated** (open by construction, like everything in the registry). They capture the *resonance* the founders asked for — account culture/frustrations and rich contact hooks.

**`account.resonance.*` — the account's emotional/cultural texture (M2, deep pass).**
Beyond "operational pain" and "strategic moves," the deep account profile gathers culture and sentiment for content resonance: employee sentiment (Glassdoor and similar), morale/attrition/layoff signals, engineering-blog tone, public frustrations, "what it's like to work and buy here." Tier-4 by nature, evidence-bound. These feed the value narrative's emotional register, not just its ROI math.

**`contact.facet.*` — rich personal hooks (M4, deep pass).**
Nickname, stated interests, communication style, public appearances (podcasts/talks), publications, causes, alma mater, professional history beyond the title. This is the field-class that produces the "they really know me" hooks. **Every `contact.facet.*` claim is governed by Doc D** — strong identity-binding *and* an appropriate use-class are required before it can drive outreach. Power and governance are specified together, never separately.

Both classes are populated by the source-intelligence layer's modality adapters (staged-flow §7) — video→transcript, audio→transcript, etc. — so "anything on the internet" remains a registration problem, not a code fork.

---

## 3. Execution depth — the bounded two-level fan-out

The founders observed that a GTM engineer's high-autonomy agent run got its best, most surprising results from a **two-level** fan-out: a per-entity orchestrator that spawns aspect workers, and aspect workers that themselves spawn facet sub-workers. That depth is real power and worth having. It is also exactly the thing that, ungoverned, becomes the prototype's "spawn excessive subagents" cost blowout.

**Specification:** the per-account orchestrator/worker graph (substrate §5b) gains a **bounded recursion knob**:

```
Orchestrator (per high-tier entity)
   └─ Aspect workers (parallel, no cross-talk)        [firmographics, tech, signals, committee, resonance]
        └─ Facet sub-workers (parallel, no cross-talk) [only for the richest aspects, e.g. a single contact's interests]
```

- **Depth and worker-count are capped per tier.** Top tier gets the full two-level dive; lower tiers get one level or none. The cap is part of the orchestrator's instructions *and* a hard runtime limit, so "be thorough" can never translate into unbounded spawn.
- **Workers return references, not blobs** (substrate §5b, the artifact pattern). Sub-workers write claims to the store and hand up lightweight pointers; the orchestrator's context never re-ingests the detail.
- **Per-entity hard budget cap.** A single account/contact cannot exceed its tier's allowance; the run stops at the cap (substrate §5c). This is what keeps "go to any lengths" affordable — the lengths are bounded by tier and budget, not by the agent's enthusiasm.

This is the reconciliation of the engineer's powerful fan-out with the architecture's discipline: **same depth, applied selectively, capped explicitly, evidence-bound, and identity/use-governed.**

---

## 4. Campaign-level orchestration (new — above substrate §5c)

The substrate doc nails *per-account* durable execution. It does not model the **campaign run** — the long-lived job spanning Stage 0 → discovery (thousands of accounts) → Pass A → checkpoint → Pass B (potentially days of work). That needs its own state.

- **A campaign-run state machine** sits above the per-account graphs. Phases: `reverse_profiling → icp_confirmed → discovery → scoring(Pass A) → tier_checkpoint(human) → deep(Pass B) → verification → handoff`. Each phase is checkpointed; the run survives crashes and resumes.
- **Pause / resume / adjust mid-run.** The tier checkpoint is the obvious human gate, but the client can also pause a long discovery, adjust the ICP, or raise/lower the budget mid-flight, and the run picks up from its last checkpoint.
- **Idempotency at both levels.** Per-account steps are idempotent on `(account, field, tier)` (substrate §5c); campaign phases are idempotent on `(campaign_run, phase)` so re-entry never double-spends.
- **Temporal-shaped, Postgres-backed for V1** (substrate §12) — the campaign state machine is the outer scheduler; LangGraph + `AsyncPostgresSaver` owns each per-account graph.

---

## 5. Cost dial & governance

The founders' entire cost concern reduces to one dial: **fan-out cost per account × accounts per pass.** Make it explicit and client-controllable.

**Proposed default budget bands (confirm — D7):**

| Stage | Who runs | Order-of-magnitude cost | Cap |
|---|---|---|---|
| Client reverse-profiling | the one client entity, once | low-moderate (deep, single entity) | per-client |
| Pass A scoring | **all** discovered/imported accounts | cents/account (deterministic-only) | per-run |
| Pass B — M2 account profiling | top ~10–20% by tier | dollars/account | per-account, tiered |
| Pass B — M3/M4 committee + deep contact | committee of the **very top** tier only | highest per-entity cost | per-contact, tiered |

- **Pre-run cost estimate.** Before any spend, show the client an estimate: *"~N accounts discovered → at these cutoffs, ~M go deep → estimated $X."* The two-pass design exists precisely to make this predictable; surface it.
- **Client-set per-campaign hard cap.** The run stops (gracefully, at a checkpoint) when projected spend would exceed the cap, and asks the client to raise it or tighten cutoffs.
- **Cost pass-through (confirm — D7):** whether research cost is billed through to clients decides whether cost-governance is a **client-facing surface** (estimates, caps, burn-down the client sees) or an **internal control**. Recommended: client-facing — cost transparency is a trust feature for expensive deep research, and it makes the two-pass discipline legible as a benefit rather than hidden plumbing.

---

## 6. Observability & progress surface

A campaign run is long; the client should never stare at a spinner. Expose:

- **Phase progress** — "discovery 60% (1,240 accounts found), Pass A scoring 12%."
- **Cost burn-down** — spent vs. estimated vs. cap, live.
- **Per-source yield** — which sources are producing surviving claims. This isn't only a dashboard: it's the **same signal the source-intelligence learning loop consumes** (staged-flow §7e) to reweight source profiles. Observability and the learning loop read the same provenance data.
- **Verification health** — share of tier-4 claims passing the faithfulness judge; share of personal claims at strong binding (Doc D). A drop here is the early-warning that a model or resolver swap regressed quality.

---

## 7. Coverage confidence (not a completeness guarantee)

The founders want *"all the accounts that fit."* Open-ended discovery can never *prove* completeness — so the product should express **coverage confidence**, not exhaustiveness. The staged-flow stopping rule (marginal-yield drop) is a **cost** control; coverage is a **separate estimate**: given the channels searched and the diminishing new-candidate rate, report *"estimated ~X% of the addressable set found via these channels,"* and name the channels *not* yet searched (so the client can ask for more). Honesty here is a trust feature; implying "we found them all" is a claim we can't back.

---

## 8. Open items (tracked in overview §5)

- **D7 — Economics:** confirm the budget bands (§5), typical campaign size (hundreds vs. thousands of accounts), and cost pass-through (client-facing vs. internal).
- Per-tier fan-out depth caps (§3) — set the concrete depth/worker numbers per tier once real cost data exists.
