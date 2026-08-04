# Research Subsystem — Build Specs (Milestones & Issues)

This is the master index that divides the [architecture doc set](../architecture/) into a buildable plan:
**14 milestone-layers (M0–M13)** and **65 issues**, each with a detailed spec. It is the source the
Linear **Research Subsystem** project mirrors 1:1.

- **Linear project:** https://linear.app/deeppresence/project/research-subsystem-f599f9350fde (team: Engineering)
- **Conventions & shared contracts (read before any spec):** [`_conventions.md`](./_conventions.md)
- **Architecture (the "why"):** [`docs/architecture/`](../architecture/) — overview → substrate → staged-flow → Docs B/C/D
- **Target:** end of day **2026-06-20**.

Each Linear issue references its spec section by repo-relative path, e.g.
`docs/specs/M01-claim-store-and-merge-policy.md §M1.2`. Every issue carries the `research-and-data`
label plus its `layer:*` label, is filed under its milestone, status **Todo**, unassigned.

## How to read this

1. [`_conventions.md`](./_conventions.md) — the DRY backbone: shared contracts (claim, `current_value`,
   `account_entity`, `Resolver`, `field_definition`, `source_manifest`, ICP spec, `account_handoff`),
   naming/taxonomies, modularity rules, the stack, the spec template, the open-decisions register.
2. This index — the milestone map, dependency order, and full issue list.
3. The per-milestone spec docs (`M00…M13`) — the exhaustive, per-issue specs.

## The build principle (substrate §11)

**Build the substrate before the agents.** The foundation (M0), claim store (M1), identity (M2),
schema compiler (M3) and source layer (M4) exist before any discovery/profiling. LLM synthesis (M11)
is added **last, behind the verification layer (M9)** — it is the least-trusted, tier-4 source. The two
passes (Pass A cheap scoring / Pass B deep research) sit between mode-M1 discovery (M6) and the deep
modes M2/M3/M4 (M8).

## Modularity & DRY (the product requirement)

Replaceability is enforced by **stable seams** declared in `_conventions.md §2`: the `Resolver` protocol,
the field & source registries, policy-as-data, and the claim store as the only shared substrate. Swapping
a component (Clay → direct APIs, one judge model → another, Postgres state machine → Temporal, one
discovery source → another) stays behind a seam and is a config/adapter change, not a rewrite. Every
issue spec states the exact interface it exposes/consumes.

## Milestone map

| # | Milestone | Layer label | Depends on | Priority | Issues | Spec |
|---|---|---|---|---|---|---|
| M0 | Foundations & Shared Contracts | `layer:foundations` | — | Urgent | 6 | [M00](./M00-foundations-and-shared-contracts.md) |
| M1 | Claim Store & Merge Policy | `layer:claim-store` | M0 | Urgent | 4 | [M01](./M01-claim-store-and-merge-policy.md) |
| M2 | Identity Resolution | `layer:identity` | M0, M1 | High | 5 | [M02](./M02-identity-resolution.md) |
| M3 | ICP & Research-Schema Compiler | `layer:icp-schema` | M1 | High | 4 | [M03](./M03-icp-and-research-schema-compiler.md) |
| M4 | Source Layer & Source Intelligence | `layer:source-layer` | M1, M2, M3 | High | 6 | [M04](./M04-source-layer-and-source-intelligence.md) |
| M5 | Stage 0 Front Edge | `layer:stage0` | M2, M3, M4 | Medium | 4 | [M05](./M05-stage0-front-edge.md) |
| M6 | Discovery (mode M1) + Pass A Scoring | `layer:discovery-scoring` | M2, M3, M4 | High | 5 | [M06](./M06-discovery-and-pass-a-scoring.md) |
| M6A | Durable Exa Websets discovery + gated Sumble enrichment | `layer:discovery-scoring` | M1–M4, M6, M7, M9 | High | Integration slices D0–D6, E1, S1–S2 | [M06A](./M06A-exa-websets-sumble-discovery-integration.md) |
| M7 | Durable Execution | `layer:durable-exec` | M1, M4 | High | 5 | [M07](./M07-durable-execution.md) |
| M8 | Deep Profiling (modes M2/M3/M4) | `layer:deep-profiling` | M4, M6, M7 | Medium | 5 | [M08](./M08-deep-profiling.md) |
| M8B | Exa Deep + Sumble account-deep integration | `layer:deep-profiling` | M6A, M8, M8A, M9–M11 | High | Integration slices A0–V1 | [M8B](./M8B-exa-sumble-account-deep-integration-roadmap.md) |
| M8C | Contact-deep research + selected-contact enrichment | `layer:deep-profiling` | M8B, M9, M10, M12 | High | Integration slices C0–C7, V0–V1 | [M8C](./M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md) |
| M9 | Verification Layer | `layer:verification` | M1, M4 | High | 6 | [M09](./M09-verification-layer.md) |
| M10 | Compliance & Personal-Data Governance | `layer:compliance` | M1, M8, M9 | Medium | 5 | [M10](./M10-compliance-and-personal-data.md) |
| M11 | Tier-4 LLM Synthesis | `layer:llm-synthesis` | M4, M8, M9 | Medium | 3 | [M11](./M11-tier4-llm-synthesis.md) |
| M12 | Value Narrative & Handoff | `layer:narrative-handoff` | M5, M8, M9 | Medium | 3 | [M12](./M12-value-narrative-and-handoff.md) |
| M13 | Review, Feedback & Observability | `layer:review-observability` | M6, M9, M12 | Medium | 4 | [M13](./M13-review-feedback-observability.md) |

## Harness-era phases (post-M13; harness doc §9 + Doc R)

| Phase | Work | Status | Spec |
|---|---|---|---|
| A | Restructure + spine: R0–R2, `workspace_id` rename, `libs/clue-spine`, R3 (api → `platform/api`) | **closed** | [PA](./PA-phase-a-restructure-and-spine.md) |
| B | Platform infra core: fleet worker (step 0) · storage (step 1) · memory slice 1 (Doc M) · toolbelt/projections (step 2) | **executed** | [PB](./PB-phase-b-platform-infra-core.md) |
| B4 | Toolbelt + projections/SSE + fleet run-start composition (step 2; `platform/b4-toolbelt-v0`) | **executed** | [PB-B4](./PB-B4-toolbelt-and-projections.md) |
| B2 | Storage lane: `libs/clue-storage` · `artifact` table + `claim.artifact_key` · evidence snapshots · scrapling scrape backend · DSAR snapshot reach · millicredit groundwork | **executed + integrated** | [PB-B2](./PB-B2-storage.md) |
| B3 | Scoped-memory slice 1: five-scope memory substrate · two seams · deterministic assembly · lifecycle/DSAR | **executed + integrated** | [PB-B3](./PB-B3-scoped-memory-slice-1.md) |
| C | Governed agency: Step 4 fan-out (coverage/proposals/ingestion/Stage 0) → journal/recipes → deepagent → structured research views | **C0–C7 implemented; only the pre-multi-worker legacy-write hard-fence item remains in C8** | [PC](./PC-phase-c-agentic-layer.md) · [C0](./PC-C0-step4-contract-freeze.md) · [C1](./PC-C1-coverage-and-goal-judge.md) · [C2](./PC-C2-field-source-proposals.md) · [C3](./PC-C3-ingestion.md) · [C4](./PC-C4-stage0-recipe0.md) · [C5](./PC-C5-run-graph-recipes-executor.md) · [C6](./PC-C6-platform-deepagent-and-skills.md) · [C7](./PC-C7-research-views-derivations-and-handoff.md) |

## Full issue list

**M0 — Foundations & Shared Contracts**
- M0.1 Repo & package structure + dependency rules (modular boundaries)
- M0.2 Core domain types & shared contracts (Entity, Claim, FieldDef, Resolver protocol, SourceManifest)
- M0.3 Postgres + pgvector + migrations tooling
- M0.4 Config, secrets & per-client jurisdiction/policy config skeleton
- M0.5 Observability & tracing skeleton (named spans per pipeline step)
- M0.6 Test + eval-harness scaffold + CI

**M1 — Claim Store & Merge Policy**
- M1.1 Claim table — append-only, supersede, provenance fields
- M1.2 current_value merge view (tier/freshness/corroboration policy + conflict flag)
- M1.3 Field registry (field_definition) + namespaced field-classes
- M1.4 research_mode dimension + discovery vs field-claim provenance flavors

**M2 — Identity Resolution**
- M2.1 Entity model (account_entity, contacts under accounts)
- M2.2 Dedup → record-link → canonicalize (deterministic + pgvector probabilistic + scorer)
- M2.3 Confidence-thresholded auto-merge + human review queue
- M2.4 Redis in-flight locks
- M2.5 Cross-tenant reuse with tenant isolation

**M3 — ICP & Research-Schema Compiler**
- M3.1 ICP spec data model (versioned)
- M3.2 Research-schema compiler (ICP → typed field plan; scoring vs deep tags)
- M3.3 Industry packs framework (field set + source profile, namespaced)
- M3.4 Scoring rubric model (fit + intent weights)

**M4 — Source Layer & Source Intelligence**
- M4.1 Resolver protocol + trust-tiered waterfall engine (stop-at-first-confident)
- M4.2 Source Registry + capability manifests
- M4.3 Modality-adapter framework (fetch → adapt → extract)
- M4.4 Deterministic resolvers: Clay (swappable) + Apollo/ZoomInfo + BuiltWith + registries
- M4.5 CRM import resolver (tier-1) + Firecrawl official-site scrape (tier-2)
- M4.6 Source Profiles + config-bounded Source Planner

**M5 — Stage 0 Front Edge**
- M5.1 Client reverse-profiling pipeline → versioned Client Knowledge Base
- M5.2 ICP synthesis & proposal (multi-ICP support — D5)
- M5.3 Import entry scenario (bulk identity resolution + ICP back-scoring + non-fit flagging — D6)
- M5.4 Hybrid lookalike seeding from imports / existing customers

**M6 — Discovery (mode M1) + Pass A Scoring**
- M6.1 Account Discovery (mode M1, grounded-only, expand pattern, stopping rule)
- M6.2 Existence/identity gate + discovery-provenance
- M6.3 Pass A scoring engine (two-tier deterministic proxies)
- M6.4 Tiering + human checkpoint (interrupt-based)
- M6.5 Coverage-confidence estimator

**M7 — Durable Execution**
- M7.1 Per-account orchestrator-worker graph (LangGraph + AsyncPostgresSaver; workers return references)
- M7.2 Bounded recursion knob (aspect/facet sub-workers; per-tier depth & worker caps)
- M7.3 Project-run state machine (phases, checkpointing, pause/resume/adjust)
- M7.4 Idempotency keys ((account,field,tier) + (project_run,phase))
- M7.5 Budget caps & cost-governance engine (per-account, per-run hard stops)

**M8 — Deep Profiling (modes M2/M3/M4)**
- M8.1 Account Profiling (mode M2, converge pattern + target-lock)
- M8.2 account.resonance.* field-class + collectors
- M8.3 Committee Discovery (mode M3, person resolution + role plausibility gate, persona keys)
- M8.4 Contact Profiling (mode M4, target-lock + identity-binding strength)
- M8.5 contact.facet.* field-class

**M9 — Verification Layer**
- M9.1 Pre-spend schema/identity gates
- M9.2 Corroboration rules (≥N independent tier≤3)
- M9.3 Faithfulness judge (LLM-as-judge, dedicated trace span)
- M9.4 Identity-binding gate (strong vs weak)
- M9.5 Freshness TTL engine + re-research cadence
- M9.6 Eval harness + golden account set + rubric scoring

**M10 — Compliance & Personal-Data Governance**
- M10.1 Jurisdiction resolution per contact entity (D4 resolved: mixed/global)
- M10.2 Use-class taxonomy tagging at extraction
- M10.3 Appropriateness/use gate (use_class × jurisdiction × client_policy)
- M10.4 Three postures as per-client config (D3 default: Option 1)
- M10.5 Lawful-basis recording + retention TTLs + DSAR/erasure (tombstone)

**M11 — Tier-4 LLM Synthesis**
- M11.1 Exa Deep resolver (field-level grounded synthesis)
- M11.2 Parallel Task resolver
- M11.3 Synthesis fields (operational_pain, strategic_moves, resonance narratives) behind the judge

**M12 — Value Narrative & Handoff**
- M12.1 Positioning step (account claims × client knowledge → per-persona value narrative)
- M12.2 account_handoff contract object + provenance index
- M12.3 Output/handoff API (boundary to the content layer)

**M13 — Review, Feedback & Observability**
- M13.1 Tier-1 review surface (per-claim approve/correct/reject, interrupt/resume)
- M13.2 Disposition capture → labeled training data
- M13.3 Source-yield + scoring learning loop (reweight source profiles & scores)
- M13.4 Client-facing cost & progress surface (phase progress, burn-down, per-source yield, verification health, pre-run estimate)

## Open decisions (overview §5)

Surfaced on the issues they touch; specs proceed on the recommended default without hardcoding:
D1 output boundary · D2 design-subsystem ingest interface · D3 personal-data posture ·
**D4 contact geography (resolved: mixed/global)** · D5 ICP multiplicity · D6 import non-fit behavior ·
D7 economics/budgets · D8 2026 legal verification.
