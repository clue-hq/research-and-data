# Exa-led brand context: implementation handoff

Prepared 20 September 2026. **Proposal and prompt pack, not a deployed pipeline.** The Conduit preview at localhost:3046 and all original experiment files are preserved.

## The decision

Extend Aryan's existing onboarding worker, Exa client, provider ledger, document store and Markdown mappers. Exa performs discovery, research and evidence-led reasoning. Python validates and renders. An optional inexpensive model may repair formatting under strict semantic equivalence; it must not invent, research or rewrite substance. Grok remains the current platform ICP/persona model until an explicitly reviewed implementation changes that path. This package changes no model configuration.

We want the useful coverage and decisions of the Conduit library, not identical wording, a mandatory 25-file count, or the uncorrected assertions in that library. Conduit is a supervised reference with unresolved facts, not a gold-standard answer key. A fresh run must reproduce useful knowledge from sources without Codex supplying research or editing answers.

## Read in this order

1. [What was actually produced and how](01-reference-and-authorship.md).
2. [Proposed architecture and contracts](02-pipeline-design.md).
3. [Output families and document ownership](03-document-catalog.md).
4. [Research prompts](prompts/00-research-system.md), then the task-specific files in [the prompt index](prompts/README.md).
5. [Exact backend change map](04-backend-change-map.md).
6. [Evaluation and rollout gates](05-evaluation.md).
7. [Implementation plan](../superpowers/plans/2026-09-20-exa-brand-context-handoff.md).
8. [Handoff verification and remaining implementation gates](06-handoff-verification.md).

## What is in the handoff

- All **25 preserved final document bodies**, copied into [reference/conduit-output](reference/conduit-output), with hashes and source links in [document-index.json](reference/document-index.json).
- All **23 original model document specifications**, including their briefs, source filters, requested headings and dependencies, in [original-document-briefs.json](reference/original-document-briefs.json).
- Four archived **current-source** system prompts: initial researcher, initial synthesis, expanded synthesis and critic. These are forensic material; the proposed prompts supersede their Conduit-specific assumptions and document-level `agent_context` requirement.
- A **103-record source inventory** with retrieval methods, timestamps and per-document references. [Open the source inventory](reference/source-inventory.md). These are records, not 103 independent corroborating sources or 103 Exa calls.
- General research instructions and 12 task prompts for reuse across companies, plus an offline schema for their proposed outputs.
- A proposed dependency order, dynamic product/segment expansion, refresh rules, cost controls and an evaluation plan that forbids manual answer repair.

## Practical scope

The new work is documentation, reference export and offline verification only. There are no edits to the experiment, `.env`, active skills, platform runtime, databases or running services. No provider request or fresh brand research was made. Nothing is pushed remotely.

The library should expose friendly titles and rendered Markdown. Evidence metadata remains available for audit, without a separate “Agent context” panel on knowledge documents. Rich “when/how to use” context belongs to Assets: logos, website imagery and the ad library. Normal document identifiers and provenance are still necessary; they are not creative-usage guidance.

## Verify the handoff without research

From the repository root:

```sh
python3 docs/brand-context-research-handoff-v1/tools/verify_handoff.py
```

This uses Python's standard library and the frontend's already installed AJV 8 through Node. It checks reference fidelity, links, prompt/catalog coverage, schema examples and the protected experiment's hashes. It does not establish Exa output quality. Live acceptance is specified separately and requires a new output directory, not changes to 3046.
