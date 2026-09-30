# Existing implementation → proposed change

Audited against this checkout and the original checkout on 19 September; core onboarding files matched. Revalidate before implementation because upstream work may advance. This package does not install new skills, routes, migrations or settings.

## Runtime ownership

| Existing file | Current responsibility | Proposed modification |
| --- | --- | --- |
| `platform/api/clue_api/onboarding_routes.py` | Creates/enqueues onboarding run; triggers separate brand-kit ingestion | Preserve trigger/idempotency and progressive status; expose honest coverage only through a reviewed contract |
| `platform/api/clue_api/arv2/onboarding_driver.py` | Parallel company/catalog/reviews; background products; Grok ICP/persona launches | Pass product URLs/aliases/sibling names; wait for selected evidence dependencies; add scoped Exa research tasks for messaging and proposed ICP output |
| `platform/api/clue_api/arv2/onboarding_requests.py` | Exa prompts and response schemas | Version task instructions/schema; add needed detail/contradiction/proof fields; keep shallow catalog/persona schema separate |
| `platform/api/clue_api/arv2/exa_client.py` | `/agent/runs` create/poll and `/search` deep-reasoning, cost/raw response wrapping | Reuse; do not build another HTTP client or bypass the governed caller; verify richer schema support before rollout |
| `platform/api/clue_api/arv2/onboarding_documents.py` | Pure conversion to Markdown with front matter | Extend section/table mapping and evidence preservation; no new writing model needed |
| `platform/api/clue_api/arv2/onboarding_store.py` | Durable runs, steps, documents and versions | Support explicit dependency/provisional/coverage representation through a reviewed additive contract; do not invent enum states without migrations |
| `platform/api/clue_api/arv2/onboarding_reconcile.py` | Batched model-assisted product identity matching | Retain existing configured GPT-5 mini role initially; audit identity confidence and aliases |
| `platform/api/clue_api/onboarding_synthesis_wiring.py` | Pins input files and runs one ICP/per-ICP persona turn; registers outputs | Introduce an explicit alternative Exa producer boundary; keep validation, ownership, registration and confirmed-document preservation. Do not merely delete the current launcher |
| `platform/api/clue_api/onboarding_evidence_tools.py` | Exa persona evidence search | Reuse first-person role-evidence retrieval and ledger; thread exact ICP/product scope |
| `platform/agents/catalog/skills/icp-synthesis/v3/SKILL.md` | Two-to-three profiles, file-only ICP reasoning | New reviewed version: evidence-led cardinality, criterion provenance, unknown handling, fit/readiness/urgency and owner confirmation. Keep historical v3 immutable |
| `platform/agents/catalog/skills/audience-persona/v2/SKILL.md` | Per-role evidence and persona prose | New version aligned to professional role scope, current product evidence and proposed Exa producer |
| `platform/agents/catalog/profiles/onboarding-synthesis/v3/profile.yaml` and registry wiring | Current Grok synthesis profile/tool surface | Deliberate activation decision: Exa task path replaces substantive Grok writing for this lane only; do not change Head of ABM or claim an env-only switch does this |
| `platform/api/clue_api/brand_knowledge_context.py` | Read/pin knowledge for downstream agents | Index new approved kinds, titles and exact versions; preserve project/brand boundaries and current citations |
| `platform/api/clue_api/frontend_read/brand_knowledge.py` and frontend repository/schema seam | Reader-facing knowledge projection | Review new folder/kinds/title/coverage schema; rendered Markdown remains reader output. No ad-usage panel for knowledge |
| `platform/api/clue_api/brand_kit_ingestion.py` | Triggers design-owned website ingestion | Keep independent visual setup; no cross-import into research internals |

## Specific corrections, in order

1. `_product_research` currently calls `product_research_query` with `official_url=None` and `sibling_names=[]`. Preserve catalog provenance through `ProductLink`/lineage and pass resolved source context. Do not reuse an unrelated homepage when an official offering URL is available.
2. `_run` launches `_synthesis_step` before awaiting product tasks. Replace this accidental partial-input behavior with a selected-evidence readiness checkpoint. A slow unrelated product need not block another selected scope; missing relevant product evidence must be explicit. Cancellation and final task settlement still need containment.
3. Replace the fixed profile count and file-only reasoning limitation for the proposed Exa path. Version the current skill rather than editing history. Hard gates need support and owner-policy treatment, not just YAML validity.
4. Add **brand and messaging** as an explicit research family. Positioning/voice may run alongside audience research after product/proof readiness. Message map and examples depend on both. Existing general research supports the sources; missing functionality is the task/output contract and dependency wiring.
5. Extend the current Markdown mappers and register outputs through the existing document store. Do not introduce a second JSON knowledge store in production or import experiment code.
6. Route evidence findings into bounded provider follow-up or owner questions. Keep prior candidates and receipts. Do not recreate `curation.py` as brand-specific correction rules.

## Contracts Aryan must review before integration

- Existing `product-research` should retain stable product IDs and paths. Decide whether capability/developer guides remain that kind or receive a distinct kind, preserving query compatibility.
- New knowledge kinds for commercial context, proof, jobs, ICP strategy and messaging need explicit accepted identifiers and reader mappings. `Brand & messaging` is a proposed display folder, not an already supported backend enum.
- New response evidence records must map to platform provenance/claim mechanisms. A completed Exa response is a candidate, not an automatically verified claim. Reuse existing typed claim/source helpers; source confidence is not approval.
- General research schema uses `qualification_criteria` for a rich proposal. Existing ICP projection requires `icp_key`, `product_ids`, `hard_gates`, `exclusions`, `persona_map` and `qualifier_fields`. Map only justified/approved-policy gates; retain non-gating preferences, readiness and urgency as distinct research context. Never let the adapter promote every criterion into `hard_gates`.
- Preserve the current ICP status `proposed`, existing confirmed rows, per-project variants and exact version pins. Provider output cannot set `confirmed`, retire a human decision or supply arbitrary scope IDs.
- Brand-wide messaging examples are proposed context, not generated campaign artifacts. Downstream Head of ABM remains responsible for campaign-specific decisions. Do not add a separate conversational brand agent just to render documents.
- Document-level `agent_context` exists in the preserved experiment only; the proposed knowledge schema omits it. Asset usage guidance extends the asset seam separately after contract review.

## Model and configuration policy

Current checked settings: onboarding enabled; overview `high`; product/reviews `medium`; reviews in fast phase; background cap 6; reconciliation enabled with `openai/gpt-5-mini`; persona evidence enabled; synthesis `x-ai/grok-4.6`. They are unchanged.

Exa Agent output and Grok deepagent output have different execution/projection paths. The implementation must select one substantive producer per task and compare candidates in a separate evaluation run, not double-publish both. Optional cheap parsing is disabled unless equivalence is proven. A future Luna selection requires a real supported model identifier and capability check at implementation time; this proposal invents neither.

Any new flag appears in `.env.example` and the owning subsystem's example at introduction. Preserve local `.env` values, DSNs, ports and paths. New runtime controls belong in versioned policy where appropriate. Migrations, if required by enum/schema changes, use random-hash Alembic revisions and a disposable branch DB; none are created now.
