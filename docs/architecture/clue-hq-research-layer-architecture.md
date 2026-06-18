# Clue-HQ — Data & Research Layer
## Product-Grade Architecture (V1)

This is the design for the data and research stage: ICP → target list → prioritization → per-account research → buying-committee contact graph → scored, provenance-backed claims that feed the design/content module. It folds in what the current market (Clay, 6sense/Demandbase, 11x/Artisan, Anthropic's research system, the grounding literature, Exa/Parallel) gets right and wrong, plus the failure modes from the scrappy prototype.

Schemas and topologies below are **illustrative starting points**, not final DDL.

---

## 0. The one architectural bet

**Verifiability is a property of the data model, not a QA pass bolted on at the end.**

The prototype's deepest flaw was that its unit of research was the *dossier* — a blob audited probabilistically after the fact by "Claude QA." That is the exact pattern the grounding literature identifies as the source of shipped hallucinations: the model overrides correct evidence with a smoother fabrication, and nothing catches it because there is no claim-level eval layer. It is also why the prototype's merge logic was broken ("bad base facts never overwritten") — you can't merge safely over untyped blobs.

Everything else in this document follows from inverting that. The atomic unit of the system is a **typed claim with provenance**, and "research" becomes the act of producing, corroborating, and scoring claims. Verification stops being a vibe-check and becomes a deterministic property: merge is a policy over source tiers, conflicts are visible instead of silently resolved, staleness is queryable, and the human review surface and your fit/intent scores read directly from the same structured substrate.

This is the one thing to get right before writing the first research agent. The prototype built the research agents first and the data discipline last; that ordering is what produced most of its pain.

---

## 1. The claim store — the spine

Every fact about an account or contact is a row, not a field on a document.

```
claim
------
  id                uuid pk
  entity_id         uuid     -- FK -> account or contact (via identity service)
  entity_type       enum(account, contact)
  field_key         text     -- e.g. "employee_count", "uses_snowflake",
                              --       "recent_funding", "hiring_velocity_eng"
  value_json        jsonb    -- typed payload; shape defined by field registry
  source_url        text
  source_tier       int      -- 1=deterministic API, 2=official site,
                              --   3=reputable third party, 4=LLM synthesis
  extraction_method enum(api, scrape, llm_synthesis, human, crm_import)
  evidence_span     text     -- the exact retrieved text the value came from
  confidence        numeric  -- 0..1, from the resolver (Exa/Parallel give this)
  corroborations    int      -- # of independent tier<=3 sources agreeing
  observed_at       timestamptz   -- when the source published/was seen
  collected_at      timestamptz
  cost_cents        numeric
  run_id            uuid     -- which research run produced it
  superseded_by     uuid     -- nullable; append-only history, never UPDATE-in-place
```

Design rules:

- **Append-only.** New observations don't overwrite old ones; they supersede. You get a full audit trail and time-travel for free, which matters when a client disputes a claim that drove outreach.
- **`evidence_span` is mandatory for tier-4 (LLM) claims.** No span → the claim cannot be promoted past `unverified`. This single constraint kills the prototype's "made-up facts" class of error at the schema level: a fabricated fact has no span to point at.
- **The field registry is the contract.** A separate `field_definition` table declares each `field_key`'s type, validation, which source tiers may populate it, freshness TTL, and whether it's a *scoring-pass* or *deep-pass* field (see §3, §5). Per-vertical fields (NPI for healthcare, FDA clearances, etc.) are just rows here — the prototype hardcoded these and couldn't generalize.

The **merge view** (the "current truth" the rest of the platform reads) is a deterministic function, not an agent:

```
current_value(entity, field) =
  among non-superseded claims, pick by:
    1. highest source_tier that satisfies the field's freshness TTL
    2. tie-break on corroborations desc, then confidence desc, then collected_at desc
  emit value + the winning claim's provenance + a conflict flag
    if two tier<=2 sources disagree
```

Because merge is a pure policy, an LLM-synthesized (tier-4) value can *never* become the base that a later trustworthy source fails to overwrite — the inverse of the prototype's bug. Conflicts between authoritative sources surface as a flag for review rather than being silently resolved.

---

## 2. Identity resolution — the front door

Promote the prototype's "identity-lock prompt" into a first-class service. Every other component takes an `account_id`/`contact_id` from this service and **never a free-text company name.** This is the standard entity-resolution discipline: deduplicate → record-link → canonicalize, with confidence-thresholded auto-merge and a review queue for ambiguous cases.

```
account_entity
  id              uuid pk
  canonical_name  text
  primary_domain  text       -- the strong key
  aliases         text[]
  hq_geo          jsonb
  registry_ids    jsonb      -- NPI, DUNS, CIK, LEI... vertical-dependent
  status          enum(candidate, active, merged)
  merged_into     uuid
```

- **Resolution = deterministic first, probabilistic second.** Exact domain / registry-ID match auto-resolves. Otherwise fuzzy match on name+geo+aliases (embeddings in pgvector for the candidate set, then a scorer). High-confidence (≈≥0.95) auto-merges; the mid-band routes to the human review queue rather than guessing. Never let a near-match silently collapse two real companies.
- **Distributed in-flight locks** (Redis) replace the prototype's `run_pause.flag` and ad-hoc in-flight checks: `lock(account_id)` before any expensive work so two workers never research the same account.
- **Cross-tenant reuse, carefully.** Public-footprint claims about a company (employee count, tech stack, funding) are partially reusable across clients and amortize cost; client-specific scoring and any client-private data stay strictly tenant-isolated. This is a real moat — your claim store gets better and cheaper per account as more clients touch the same public entities.
- **Contacts resolve under accounts**, keyed on LinkedIn URL / verified email, with the same alias+confidence machinery.

---

## 3. Research schema compilation — ICP becomes a typed plan

This is the generalization move the prototype couldn't make (it was welded to dental/NPI). **A client's ICP definition compiles into a research schema**: a typed list of `field_key`s, each mapped to (a) the ordered source tier list that may populate it and (b) the gates that apply.

```
ICP definition (client onboarding)
   │  industry, size band, geo, tech stack, the signals they care about
   ▼
Research Schema  (per client, versioned)
   field_key            tier_plan (ordered)              pass        gate
   ─────────────────────────────────────────────────────────────────────
   employee_count       [Apollo, ZoomInfo, site, LLM]    scoring     —
   primary_tech_stack   [BuiltWith, site_scrape, LLM]    scoring     —
   recent_funding       [API, news_search, LLM]          scoring     —
   hiring_velocity_eng  [jobs_api, scrape, LLM]          deep        tier>=1
   operational_pain     [LLM_synthesis]                  deep        committee-gated
   strategic_moves      [news, LLM_synthesis]            deep        tier>=1
```

Two things this buys you:

1. **Vertical pluggability.** NPI registry becomes a resolver that only activates for healthcare ICPs. Adding a vertical = registering resolvers + field definitions, not forking the pipeline.
2. **The two-pass economics live here.** Each field is tagged `scoring` (cheap, run on the whole list) or `deep` (expensive synthesis, run only after tiering). The schema is where "what do we spend on whom" is declared and auditable.

---

## 4. The trust-tiered source waterfall

Per field, resolve in **trust-tier order** and stop at the first result that clears the field's confidence threshold — the Clay pattern, but ordered by *trustworthiness* (which correlates with but isn't identical to cost), and writing typed claims instead of cells.

```
Tier 1  Deterministic APIs        registries, Apollo/ZoomInfo, Places,
        (highest trust)           the client's own CRM, BuiltWith
            │ miss / low-confidence
            ▼
Tier 2  Official-source scrape    company site, careers page, SEC/filings,
                                  verified LinkedIn company page  (Firecrawl)
            │ miss
            ▼
Tier 3  Reputable third party     news, G2/review sites, curated DBs
            │ field still empty
            ▼
Tier 4  LLM research agent        Exa Deep / Parallel Task — ONLY for fields
        (last resort, synthesis)  that genuinely require synthesis
                                  (operational pain, strategic narrative)
```

Why this ordering matters specifically for your correctness problem: **research agents are your least trustworthy source, so they go last, not first.** The prototype ran Ultra first and treated deterministic data as "enrichment" — backwards. Here, the trustworthy data *is* the base. The LLM only ever fills fields that no deterministic or official source can answer, and even then it must return an `evidence_span` and citation, so its output enters as a tier-4 claim that the merge policy will defer to any tier-1–3 fact.

Each resolver implements one uniform interface so they're hot-swappable and individually testable:

```python
class Resolver(Protocol):
    tier: int
    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]: ...
    # returns claims with value, source_url, evidence_span, confidence, cost
```

The CRM resolver is worth calling out: pulling the client's existing account/contact data in as **tier-1 claims** both grounds research and lets you detect "already a customer / already in pipeline" early — cheap, high-trust, and something pure-web tools miss.

---

## 5. Execution model — two passes, orchestrator-worker, durable state

### 5a. Two passes over the list

```
List (1k–10k accounts)
        │
   PASS A — SCORING  (cheap, deterministic-heavy, fully parallel)
        │   populate scoring-pass fields only (tiers 1–3, minimal/no LLM)
        │   compute provisional fit + intent  →  Tier 1/2/3 assignment
        ▼
   ┌──────────── human checkpoint: review/adjust tier cutoffs ───────────┐
        │
   PASS B — DEEP RESEARCH  (expensive, orchestrator-worker, tier-gated)
        │   only accounts above threshold; depth scales with tier
        ▼
   Buying-committee contact graph + persona-calibrated claims → design module
```

Pass A is what makes the unit economics work and what builds client trust *before* you burn the expensive credits — they adjust cutoffs against transparent provisional scores, then you spend. This is the Clay "premium-for-Tier-1" discipline, made into a product surface.

### 5b. Per-account deep research = orchestrator-worker (LangGraph)

For each Tier-1/2 account, one research graph instance:

```
        ┌─────────────── Orchestrator (lead) ───────────────┐
        │  reads research schema + current claims            │
        │  plans which gap-fields need filling               │
        │  spawns field-cluster workers in parallel          │
        │  workers DO NOT talk to each other                 │
        └───────────────────────────────────────────────────┘
              │            │             │            │
        ┌─────▼───┐  ┌─────▼────┐  ┌─────▼────┐  ┌────▼─────┐
        │firmo/   │  │tech-     │  │signals/  │  │committee │
        │funding  │  │stack     │  │intent    │  │/contacts │
        └─────────┘  └──────────┘  └──────────┘  └──────────┘
              │            │             │            │
              └──── each writes CLAIMS to the store ──┘
                          │
                  Verification pass (§6)  — separate step
                          │
                  Scoring (§9)  →  status: ready_for_review
```

Adopt these specific lessons from the SOTA so you don't re-learn them:

- **Workers return references, not blobs.** Subagents write claims to the store and hand the orchestrator lightweight pointers; the orchestrator doesn't re-ingest every detail into its own context. (Anthropic's "artifact pattern" — keeps lead-agent tokens and cost down.) Your claim store *is* the shared filesystem.
- **Externalize the plan early.** Persist the orchestrator's plan + state to Postgres before context grows; the run must survive truncation and crashes.
- **Effort-scaling is explicit.** Tier-1 gets more workers / deeper passes than Tier-2. Bake the budget into the orchestrator's instructions and as a hard cap (below), or it will over-spend on easy accounts — the failure mode where research agents spawn excessive subagents for simple queries.
- **Tools over skills.** Give workers well-described resolver tools rather than long "be a great researcher" prompts. More reliable, fewer tokens.

### 5c. Durable execution — the part the prototype hand-rolled

The prototype's worker pools, retry flags, pause file, and in-flight locks are a fragile reimplementation of durable workflow execution. At 5k-account scale, research *is defined by* partial failure, rate limits, and long-running steps — treat it as such.

- **V1:** a Postgres-backed state machine. Each account-research is a workflow row; each step is idempotent keyed on `(account_id, field_key, source_tier)` so retries never double-charge or double-write; per-step retry policy with backoff; per-account and per-run **budget caps** (hard stop when `sum(cost_cents)` exceeds the tier's allowance). LangGraph's `AsyncPostgresSaver` checkpointing gives you crash-resumability inside each graph; the outer state machine owns scheduling, concurrency limits, and budget. This is squarely in your wheelhouse from the WatsonX/Iris work.
- **Graduate to Temporal** when you need cross-service orchestration, human-task timers (review SLAs), and first-class long-running durability — not on day one, but the state-machine design should be Temporal-shaped so the migration is mechanical.
- **Get Airtable out of the write path entirely.** It was the prototype's fragility point because it was simultaneously the database and the UI. **Postgres is the system of record;** the review surface reads from it. (Optionally sync a slim, read-only projection to a client's tool of choice, but never write-through it.)

---

## 6. The verification layer — grounding made deterministic

This is where you directly answer "our research must be correct and accurate." Three mechanisms, layered, each cheap relative to the cost of bad outreach to a named enterprise account.

**(1) Schema/identity gates (pre-spend).** Keep the prototype's genuinely good ideas: official-domain requirement, geo/canonical-name lock, dedup registry, in-flight lock, target-locked prompts ("this exact company, this domain — do not drift to similarly named orgs"). These were the prototype's strongest contribution; preserve them as the entry gate.

**(2) Provenance + corroboration (structural).** Falls out of the claim store: a tier-4 claim with no `evidence_span` cannot be promoted; a field that matters for scoring or content can require ≥N independent tier-≤3 corroborations before it's `verified`; conflicting tier-≤2 claims raise a flag instead of being silently merged.

**(3) Faithfulness judge (the missing eval layer).** For every tier-4 synthesized claim, a separate LLM-as-judge call scores whether `value_json` is actually entailed by its `evidence_span` — claim-level groundedness, not document-level. Unsupported → reject the claim and trigger re-retrieval (or leave the field empty, which is *correct behavior* — empty beats fabricated). This is the step that takes you from the prototype's leaky probabilistic QA to the 10%→sub-1% hallucination reductions the literature reports, and it's the difference the grounding research keeps stressing: the model isn't the problem, the absent judge is. Run it as a distinct graph step with its own observability span so faithfulness is measured, not assumed.

**Freshness as a first-class signal.** Every claim has `observed_at` + a field-level TTL; the merge view treats stale claims as eligible for refresh and the scoring layer can discount them. The "master database is a myth" reality — the modern workforce and tech stack churn constantly — means re-research on a cadence (≈90-day default, signal-fields faster) is part of the system, not an afterthought.

**Evals.** Stand up an eval set of hand-verified accounts and run the standard battery: LLM-as-judge with rubrics for factual accuracy / citation validity / source quality, plus periodic human spot-checks to catch what judges miss. This is how you defend an accuracy claim to an enterprise buyer and how you catch regressions when you swap a model or resolver.

---

## 7. Buying-committee contact graph — your wedge, built in V1

Account-level truth is necessary but not sufficient: the email goes to a *person*, the mailer lands on a *desk*, and your V2 ads are *contact-level*. Build the contact graph in V1 or you'll re-pay for research in V2.

Per account, resolve the committee and, for each contact, attach:

- **Role on the committee** — champion / economic buyer / technical evaluator / blocker (inferred from title + org context, stored as a claim with confidence).
- **Per-contact signal** — recent LinkedIn activity, role changes, posts, mentions (the per-person layer Artisan-style tools do well and 6sense structurally cannot, since it stops at the company).
- **Persona key.** Content calibration and the design module's template→instance mapping key on **(account, persona)**, not just account: the report for the economic buyer argues ROI; the technical evaluator's version argues architecture. Same account truth, persona-shaped framing.

This account-truth + verifiable-committee + persona fusion is exactly what neither the account-level platforms nor the contact-level SDR tools deliver today.

---

## 8. Client knowledge ingestion — stage 0

Every artifact answers "how does *our client's* product benefit this account," which is impossible without deep ingestion of the client's own side: product docs, case studies, pricing, differentiators, customer evidence. Treat it as a first-class module (the "knowledge base + positioning" pattern the better SDR tools ship), not an onboarding form.

- Ingest docs/site/decks/calls → chunk → embed (pgvector) → a typed **client knowledge base**.
- A **positioning step** (its own graph node) joins verified account claims with client capabilities to produce the grounded value narrative the content layer consumes — and its outputs are themselves claims with provenance pointing at both the account evidence and the client-knowledge source.
- The quality ceiling of every generated artifact is set here, and it has its own freshness problem (pricing/positioning changes), so version it.

---

## 9. Scoring — explainable, provenance-backed, learning

Don't ship an opaque "87/100." The market's own critique is that a single number tells a rep nothing; multi-dimensional, explainable scoring is the standard, and it's what makes outreach defensible.

- **Decompose:** Fit (firmographic / technographic / vertical) and Intent (signal growth, hiring, funding, web/engagement) as separate, inspectable sub-scores — each traceable to the claims that produced it ("trending because eng hiring +40% and two committee members are new").
- **Provenance-backed:** because scores read from claims, every score links to its evidence. This is both a trust feature for the client and a debugging tool for you.
- **The feedback loop is free in V1.** When the client's sales team accepts/rejects accounts you scored highly, that disposition is **labeled training data** for the fit model. Capture it from day one — static-scoring competitors can't claim a model that improves on the client's own outcomes.

---

## 10. Human-in-the-loop — designed surface, not a caveat

The prototype's conclusion ("treat the final artifact as needing human spot review") is right, but in the product it's a *designed checkpoint*, not a disclaimer.

- **Tier-1 review before content generation:** show each claim with its source, confidence, freshness, and corroboration; approve / correct / reject per claim. Use `interrupt()`-style pause-and-resume (the secure-input pattern you already built maps directly) so the graph suspends durably at the checkpoint and resumes on the human action.
- **Two compounding payoffs:** corrections become labeled training data for extraction *and* scoring; and per-claim provenance is what gets an enterprise GTM team to actually put generated content in front of a named account. **"Every fact in this report links to its source" is a sales line your competitors mostly can't say** — and with this architecture it's literally true.

---

## 11. Build order

The prototype integrated research agents first and data discipline last — that ordering caused most of its pain. Invert it. Research agents are the *last* thing to add, because everything depends on the substrate they write into.

1. **Identity service + claim store with provenance** (the data model — everything hangs off this).
2. **Field registry + research-schema compiler** (ICP → typed field plan).
3. **Deterministic resolvers + the trust-tiered waterfall** (tiers 1–3; real, verifiable data with zero LLM).
4. **Two-pass orchestration + durable state machine** (scoring pass, tiering, budget caps, idempotency).
5. **Verification layer** (provenance gates → corroboration → faithfulness judge + evals).
6. **LLM research agents as tier-4 field-fillers** (Exa Deep / Parallel Task), behind the judge — added only now, on top of a substrate that constrains and checks them.
7. **Contact graph + persona keys.**
8. **Client-knowledge ingestion + positioning.**
9. **Review surface** (and the disposition feedback loop).

Steps 1–4 produce a genuinely useful, *trustworthy* account list before a single synthesis LLM call exists — which is also the most honest demo you can give an enterprise buyer.

---

## 12. Stack mapping (to your foundation)

| Concern | Recommendation |
|---|---|
| System of record | **Postgres** (claims, identity, accounts, contacts, schemas). JSONB for per-vertical field payloads; real columns + indexes on hot query paths. **No Airtable in the write path.** |
| Dedup / KB retrieval | **pgvector** for candidate-set matching and client-knowledge retrieval. |
| Per-account research | **LangGraph** orchestrator-worker, `AsyncPostgresSaver` checkpointing for crash-resumability (you've shipped this shape on Iris/WatsonX). |
| Durable execution | V1: **Postgres-backed state machine**, idempotency keys on `(account, field, tier)`, per-account/run budget caps. Design it **Temporal-shaped** for a clean later migration. |
| Locks / ephemeral state | **Redis** for in-flight account locks and rate-limit coordination. |
| Search / synthesis (tier 4) | **Exa Deep** (field-level grounding) and/or **Parallel Task API** (Basis: citations + reasoning + confidence) as pluggable resolvers; **Firecrawl** for tier-2 official-site scraping with livecrawl freshness. |
| Deterministic (tiers 1–3) | Apollo / ZoomInfo / BuiltWith / Places / registries / **client CRM**, each behind the uniform `Resolver` interface. |
| Verification | Separate **LLM-as-judge** faithfulness step with its own trace span; eval harness over a hand-verified account set. |
| Human checkpoints | `interrupt()`-based pause/resume (your secure-input pattern) for Tier-1 review. |
| API | **FastAPI** with the lifespan/`asynccontextmanager` pattern you're already using for pools and clients. |

---

## 13. Anti-patterns to refuse (from the prototype and the market)

- **LLM research as the base layer.** It's the least trustworthy source; it goes last and only fills genuine synthesis gaps. Never let it be the foundation later sources fail to overwrite.
- **Untyped dossiers + after-the-fact QA.** This is the hallucination-shipping pattern by construction. Claims + a faithfulness judge, not blobs + a vibe-check.
- **One mega-agent.** Single-agent / many-tools produces tool confusion, loops, and mediocre output (11x lived this). Constrained orchestrator-worker; workers don't talk to each other.
- **Uniform deep research on the whole list.** Economically broken and ~15x the token cost. Two passes, tier-gated depth, hard budget caps.
- **Account-only data model.** You'll re-pay for everything in V2. Contact graph + persona keys in V1.
- **Filling a field with a plausible guess.** An empty, flagged field is a *correct* output. Fabrication is the only real failure.
- **Opaque scores / opaque facts.** Provenance and decomposition are trust features and your defensible differentiator — not overhead.
