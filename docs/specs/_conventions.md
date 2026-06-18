# Research Subsystem — Spec Conventions & Shared Contracts

> **Status:** living document. This is the DRY backbone for every milestone spec under `docs/specs/`
> and every Linear issue in the **Research Subsystem** project. Specs MUST NOT redefine anything
> fixed here — they reference it. If a contract needs to change, change it here once.
>
> **Source of truth:** the architecture doc set in [`docs/architecture/`](../architecture/). Read the
> overview first (`clue-hq-research-architecture-overview.md`), then the substrate
> (`clue-hq-research-layer-architecture.md`), staged-flow
> (`clue-hq-discovery-and-research-staged-architecture.md`), and Docs B/C/D.

---

## 1. What these specs are

The architecture docs describe **what** the subsystem is and **why**. These spec docs describe
**how it is built and in what order** — decomposed into milestone-layers and, within each, discrete,
independently-buildable issues. Every Linear issue has a matching spec section; the issue body
summarises the spec and links back to it by repo-relative path (e.g. `docs/specs/M01-claim-store-and-merge-policy.md §M1.2`).

The build order is non-negotiable in one respect (substrate §11): **the substrate is built before the
agents.** LLM synthesis (tier-4) is the *last* capability added, behind the verification layer.

---

## 2. Modularity & DRY — the rules every issue must honour

The product's explicit requirement: any one component must be replaceable without breaking its
neighbours. We achieve this with **stable seams** — narrow contracts that hide implementations:

- **Everything keys on a resolved `entity_id`, never a free-text name.** Identity resolution (M2) is the
  only thing allowed to turn a name into an id.
- **The claim store (M1) is the only shared substrate.** Components communicate by reading/writing
  typed claims, not by calling each other. Workers return *references* (claim ids), not blobs.
- **Resolvers are hot-swappable behind one `Resolver` protocol (§5.3).** Clay, Apollo, ZoomInfo,
  BuiltWith, registries, CRM, Firecrawl, Exa, Parallel are all *just resolvers*. Nothing downstream
  knows a specific provider exists. Swapping Clay → direct APIs is a registry/config change.
- **Open by registration, not enumeration.** New fields = rows in the field registry (M1.3). New
  sources/modalities = a manifest (+ adapter) in the source registry (M4.2/M4.3). Never fork the
  pipeline to add a vertical, a field, or a source.
- **Policy is data, not code.** Merge policy, scoring rubric, source profiles, tier/budget caps,
  jurisdiction/use-class policy, freshness TTLs are all versioned config the engine reads — swappable
  per client/ICP without code changes.
- **Durable execution is Temporal-shaped** so the V1 Postgres state machine → Temporal migration is
  mechanical (substrate §5c/§12).
- **DRY:** shared domain types, the `Resolver` protocol, provenance/claim helpers, the tracing wrapper,
  and config loaders live in one shared package (M0.2). Resolvers/adapters/judges/scorers import them;
  they never re-implement them.

Each issue spec carries an **Interface / seam** section stating exactly what contract it exposes and
what it consumes, so the replaceability boundary is explicit.

---

## 3. Canonical naming & taxonomies

**Field-key namespaces** (field registry, M1.3 — these are *registered*, never hardcoded enums):
- `core.*` — commodity facts (employee_count, primary_domain, work_email, primary_tech_stack…).
- `account.*` — account facts (recent_funding, hiring_velocity_eng, operational_pain, strategic_moves…).
- `account.resonance.*` — culture/sentiment/frustrations (Doc C §2; tier-4, deep pass).
- `contact.*` — contact facts (role_on_committee, persona…).
- `contact.facet.*` — rich personal hooks (Doc C §2; governed entirely by Doc D / M10).
- `<pack>.*` — vertical packs, e.g. `healthcare.npi`, `frontier_ai.arxiv_activity`.

**Source tiers** (trust order, substrate §4): `1` deterministic API · `2` official-source scrape ·
`3` reputable third party · `4` LLM synthesis (last resort). Resolve in tier order, stop at first
result clearing the field's confidence threshold.

**Research modes** (staged-flow §1, the 2×2): `M1` Account Discovery · `M2` Account Profiling ·
`M3` Committee Discovery · `M4` Contact Profiling. (Disambiguate from milestone "M<n>" by context;
specs write research modes as "mode M1…M4".)

**Committee personas / roles:** champion · economic_buyer · technical_evaluator · blocker.

**Use-classes** (Doc D §2): `professional-public` · `personal-public-non-sensitive` · `sensitive`.

**Identity-binding strength** (staged-flow §6): `strong` · `weak`. Weak never promotes / drives outreach.

**Campaign-run phases** (Doc C §4):
`reverse_profiling → icp_confirmed → discovery → scoring → tier_checkpoint(human) → deep → verification → handoff`.

---

## 4. Canonical data contracts (illustrative starting points — not final DDL)

Specs reference these by name and may add columns; they must not contradict them.

**`claim`** (substrate §1 — the spine; append-only, never UPDATE-in-place):
`id, entity_id, entity_type{account|contact}, field_key, value_json, source_url, source_tier(1..4),
extraction_method{api|scrape|llm_synthesis|human|crm_import}, evidence_span, confidence(0..1),
corroborations, observed_at, collected_at, cost_cents, run_id, research_mode, superseded_by`.
Plus provenance flavors (staged-flow §9): *discovery-provenance* (where/why an entity matched) and
*field-claim provenance* (value+span+tier, plus `identity_binding` + `use_class` for contact claims).
**Rule:** a tier-4 claim with no `evidence_span` cannot be promoted past `unverified`.

**`current_value(entity, field)`** (substrate §1) — pure deterministic merge policy, *not* an agent:
highest tier satisfying the field's freshness TTL → tie-break corroborations desc, confidence desc,
collected_at desc → emit value + winning provenance + conflict flag if two tier≤2 sources disagree.

**`account_entity`** (substrate §2):
`id, canonical_name, primary_domain, aliases[], hq_geo, registry_ids{NPI|DUNS|CIK|LEI…},
status{candidate|active|merged}, merged_into`. Contacts resolve under accounts (LinkedIn URL / verified email).

**`Resolver` protocol** (substrate §4 — the swappability seam):
```python
class Resolver(Protocol):
    tier: int
    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]: ...
    # returns claims with value, source_url, evidence_span, confidence, cost
```

**`field_definition`** (substrate §1/§3): `field_key, type, validation, tier_plan (ordered resolvers),
freshness_ttl, pass{scoring|deep}, gate`.

**`source_manifest`** (staged-flow §7a): `source_key, modality{text|video|audio|pdf|structured},
entity_scope{account|contact|both}, yields(field_keys/classes), tier, cost, latency, geo_coverage,
freshness_profile, identity_binding_strength`.

**Versioned `ICP spec`** (staged-flow §2 / Doc B) — compiler output: active field set (core + packs) ·
discovery strategy (mode M1) · source profile (M2/M4) · scoring rubric (fit + intent weights).

**`account_handoff`** (overview §3 — the output contract this subsystem ends at):
`account_entity_id, fit_score, intent_score (decomposed, each linked to claims),
account_profile_claims[], committee[]{contact_entity_id, persona, role_on_committee,
profile_claims[]{value, evidence_span, source_tier, identity_binding, use_class}},
value_narrative[]{claim_id, persona, argument, supporting{account_evidence_ids[], client_knowledge_ids[]}},
provenance_index`.

---

## 5. The two gates & the universal rule (apply across all modes)

- **Accuracy / identity-binding gate** (substrate §6, staged-flow §6): is it true, and is it *this*
  entity? — evidence span + faithfulness judge + identity-binding strength.
- **Appropriateness / use gate** (Doc D §3, M10): may we lawfully & tastefully *use* it? —
  `(use_class × jurisdiction × client_policy)`. Distinct from accuracy; separate trace span.
- A personal hook drives outreach only if it clears **both**.
- **Universal rule:** an empty, flagged field is a *correct* output. Fabricated, misattributed, *or
  inappropriate* is the only real failure.

---

## 6. Stack (substrate §12) — the defaults specs assume

Postgres (system of record; JSONB for per-vertical payloads) · pgvector (dedup candidate sets +
client-knowledge retrieval) · LangGraph + `AsyncPostgresSaver` (per-account graphs) · Postgres-backed
state machine, Temporal-shaped (durable execution) · Redis (in-flight locks, rate-limit coordination) ·
Firecrawl (tier-2 scrape) · Exa Deep / Parallel Task (tier-4 synthesis, pluggable) · FastAPI
(`lifespan`/`asynccontextmanager`) · LLM-as-judge with its own trace span (verification). **No Airtable
or any external tool in the write path; Postgres is the only source of truth.**

---

## 7. Milestone map & dependency order

| Milestone | Layer label | Depends on | Priority |
|---|---|---|---|
| M0 Foundations & Shared Contracts | `layer:foundations` | — | Urgent |
| M1 Claim Store & Merge Policy | `layer:claim-store` | M0 | Urgent |
| M2 Identity Resolution | `layer:identity` | M0, M1 | High |
| M3 ICP & Research-Schema Compiler | `layer:icp-schema` | M1 | High |
| M4 Source Layer & Source Intelligence | `layer:source-layer` | M1, M2, M3 | High |
| M5 Stage 0 Front Edge | `layer:stage0` | M2, M3, M4 | Medium |
| M6 Discovery (mode M1) + Pass A Scoring | `layer:discovery-scoring` | M2, M3, M4 | High |
| M7 Durable Execution | `layer:durable-exec` | M1, M4 | High |
| M8 Deep Profiling (modes M2/M3/M4) | `layer:deep-profiling` | M4, M6, M7 | Medium |
| M9 Verification Layer | `layer:verification` | M1, M4 | High |
| M10 Compliance & Personal Data | `layer:compliance` | M1, M8, M9 | Medium |
| M11 Tier-4 LLM Synthesis | `layer:llm-synthesis` | M4, M8, M9 | Medium |
| M12 Value Narrative & Handoff | `layer:narrative-handoff` | M5, M8, M9 | Medium |
| M13 Review, Feedback & Observability | `layer:review-observability` | M6, M9, M12 | Medium |

Every issue also carries the `research-and-data` label. The two passes (Pass A scoring / Pass B deep)
sit between mode M1 (discovery) and modes {M2,M3,M4} — i.e. between M6 and M8.

---

## 8. Spec doc template (every `docs/specs/M*.md` follows this)

```
# M<n> — <Milestone name>
**Layer label:** layer:<slug>  ·  **Depends on:** <milestones>  ·  **Priority:** <p>
**Architecture sources:** <doc §refs>

## Goal & scope of this milestone
<what this layer delivers; where it sits in the end-to-end map; what is explicitly NOT here>

## Issues
### M<n>.<k> — <title>
- **Purpose:** <one paragraph: the problem this solves and why it exists>
- **Architecture sources:** <specific doc §refs>
- **Scope / deliverables:** <bulleted, concrete>
- **Interface / seam:** <contract exposed + consumed — the replaceability boundary>
- **Data model / schema:** <tables/types touched, referencing §4 contracts>
- **Dependencies:** <issue keys that block this; what it unblocks>
- **Acceptance criteria:** <testable checklist>
- **Out of scope:** <explicitly deferred, with the milestone that owns it>
- **Open decisions:** <D1–D8 touchpoints, if any>
```

---

## 9. Open decisions register (overview §5) — surface on the issues they touch

D1 output boundary (claims + value narrative) · D2 design-subsystem ingest interface ·
D3 personal-data posture · D4 contact geography (**resolved: mixed/global**) · D5 ICP multiplicity ·
D6 import non-fit behavior · D7 economics/budgets · D8 2026 legal verification. Specs note the relevant
Dx as **Open decisions** and proceed on the recommended default without hardcoding the decision.
