# 2026-06-14 Roadmap Analysis

## Context Read

- Read `_memory/README.md` and the prior `2026-06-14-session.md`.
- Re-read `ARCHITECTURE.md`.
- Read `.context/attachments/26wazP/pasted_text_2026-06-14_01-00-34.txt`, which frames Clay as a swappable resolver rather than a dependency that must be removed wholesale.

## Key Understanding

- The MVP failure was not that Parallel Ultra AteX was weak. The failure was architectural: a max-depth LLM research product was asked to produce dossiers without a typed claim substrate, deterministic source hierarchy, field-level nullability, and claim-level faithfulness checks.
- When there is little left to research, a powerful research model can still over-synthesize if the system rewards completed prose instead of evidence-backed fields. The product-grade fix is to make empty/flagged fields valid and fabricated facts invalid.
- Clay should be supported in V1 as a normalized resolver behind the same interface as Apollo, ZoomInfo, BuiltWith, Firecrawl, registries, CRM, Exa, and Parallel. It should not leak into downstream contracts.
- Clay replacement should be per-field and evidence-driven, not a blanket product goal. The goal is to own differentiated vertical fields, verification, contact/persona graph, and client-positioning synthesis while buying commodity enrichment where economics favor it.

## Recommended Roadmap Shape

1. Build the substrate first: identity, claim store, field registry, source tiers, merge policy, and current-value views.
2. Add deterministic and commodity enrichment resolvers, including Clay, CRM import, official-site scraping, registries, and selected direct APIs.
3. Build Pass A scoring and tiering before any deep LLM research. This produces useful account prioritization with minimal hallucination risk.
4. Add verification gates: provenance validation, source-tier conflict handling, corroboration thresholds, freshness TTLs, and an eval harness.
5. Add tier-4 LLM field-fillers only after the substrate exists. The LLM should fill specific missing fields, never produce authoritative dossiers.
6. Add contact graph, persona keys, client knowledge ingestion, and positioning once account-level claims are trustworthy.
7. Add human review and feedback loops from the start for high-value accounts and for training extraction/scoring improvements.

## Decisions / Guidance

- Do not begin implementation with LangGraph research agents. Begin with the claim model and resolver contract.
- Do not expose dossier output as source of truth. Generate narrative only as a projection over approved claims.
- Do not aim to eliminate Clay globally. Measure Clay and internal resolvers per field on coverage, freshness, correctness, latency, and cost.
- Product success metric should be "verified useful claims per dollar and per account," not "depth of research."

## Failures / Observations

- `rg` is still unavailable in this workspace, so file inspection used `find`, `grep`, and `sed`.
- The current repository remains a documentation skeleton; no implementation code is present yet.

## Verification

- The analysis was based on the current `ARCHITECTURE.md`, the attached Clay dialogue, and existing project memory.
