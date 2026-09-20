# Reference content and authorship

## What the Conduit result proves

It shows a useful information architecture, substantial product depth, commercial questions, proof boundaries and asset descriptions. It does not prove a fully automated researcher can create that quality. The current reference also contains draft language such as “published ICP” where the safer interpretation is “proposed ICP inferred from public evidence.” Do not turn every reference sentence into an acceptance requirement.

The original nine-document pilot was expanded to 25 documents. There are 23 model-backed specifications plus two manually authored organization/identity documents. Model-backed does not mean model-only: many were subsequently edited in `experiments/brand-context-agent-v1/curation.py`. Those edits remain in the preserved experiment. The `model` field on a final document records generation history, not sole authorship.

## Where the information came from

| Recorded source method | Records | What it means |
| --- | ---: | --- |
| direct_html | 75 | Python HTTP acquisition and text extraction; not Exa research |
| exa_search | 20 | Source records from ordinary Exa search results; not 20 research runs |
| browser_dom_capture | 5 | Supervised browser evidence |
| official_stylesheet_excerpts | 2 | Captured visual identity evidence |
| browser_dom_computed_style_observation | 1 | Observed website treatment |

These are 103 stored records across the reused and expanded corpus. The original run's ordinary Exa searches, Grok calls, manual follow-up discovery and editorial corrections must not be described as Exa deep research. Provider response caches preserve results/receipts/request hashes, but they do not universally preserve complete request bodies. Accordingly, the extracted source constants and reconstructed assembly logic are labelled accurately rather than asserted to be every exact historical request.

The exact URLs, timestamps and methods are in [source-index.json](reference/source-index.json); each document's source IDs are in [document-index.json](reference/document-index.json). Original full passages remain in `experiments/brand-context-agent-v1/runs/conduit-rework-20260919/sources.json`. Do not serve that run root publicly.

## Source families that made the output useful

| Source family | Information recovered | Equivalent action for another brand |
| --- | --- | --- |
| Home, company/about, legal notice, company profiles | Entity identity, positioning, origin, business model; conflicting headcount/history | Resolve the exact company; compare named claims and dates; preserve disagreements |
| Product pages, FAQ, linked technical documentation | Product boundaries, concrete workflows, limitations and action support | Follow each relevant product's full FAQ and setup/reference links through Exa retrieval |
| Pricing and billing documentation | Bundles, currencies, cadence, credits, different usage meters | Research full pricing context; preserve units and conflicting rates; never infer private terms |
| Integration directories and setup guides | Direct vs relayed connection, listing vs action support, availability conflicts | Require workflow-specific evidence; connector logos alone prove little |
| Named customer stories | Operating problem, product, reported outcome, attribution and limits | Capture the subject, baseline, denominator, period and measured/projected status |
| Vendor-owned comparison pages and competitors' own pages | Claimed differentiation, actual alternatives, build vs buy | Attribute seller comparisons; independently research a competitor before asserting its limits |
| Manifesto, official product copy, verified official ads | Vocabulary, tone and recurring positioning patterns | Research brand language as evidence; proposed writing rules remain proposals |
| Industry pages and customer evidence | Candidate account types, jobs, professional roles and qualification questions | Infer proposed buyer motions; do not mistake navigation labels for an approved ICP |

Do not hardcode Conduit's domains, customer names, hospitality categories, product count or source filters into production. Original filters in the archive explain the experiment; the new research tasks discover their equivalents.

## How the text was assembled

`rework.py` selected sources using hand-authored URL patterns, preferred direct HTML over thinner records for a URL, truncated each passage at 18,000 characters, and sent a document brief plus upstream drafts to Grok. It used phase-based parallelism; writing examples and messaging preceded full audience work. A separate model critic suggested changes, then Codex applied source-checked corrections and additional prose. This is the historical process, not the proposed architecture.

The exact current-source prompts are archived in [reference/prompts](reference/prompts). The 23 complete original specifications are exported rather than reduced to “write a good overview.” Final Markdown bodies are copied without modification into [reference/conduit-output](reference/conduit-output). Their internal `#knowledge/...` links retain the viewer routing; use the original viewer or the document index to resolve them offline.

## Turn manual improvements into pipeline rules

| Manual correction class | Reusable rule | Where it belongs |
| --- | --- | --- |
| Missing answer was in a FAQ or linked guide | Fetch complete relevant sections before concluding “not public”; track failed/truncated retrieval | Product/commercial research |
| Operator vs Operations, current vs historical product | Bind claims to an offering ID, generation, URL and availability state | Catalog/product research |
| Bundle rate treated as standalone license | Preserve offering/package/billing-unit distinction | Pricing research and verification |
| Voice credits differed by execution path | Retain each meter with its path, source and date; unresolved conflict becomes a question | Pricing/integration research |
| Story title and actual customer entity differed | Bind metrics to the entity in the evidence passage | Proof research |
| Expected savings presented as achieved | Record reported/measured/projected status; do not promote expectations | Proof research and verification |
| One product inherited another's case-study metric | Require product-specific attribution or keep result at company level | Proof-to-product mapping |
| Coming-soon directory conflicted with live setup docs | Preserve both; investigate actual workflow availability | Product/integration research |
| Generic persona needed useful titles and remit | Propose professional roles with evidence or explicit hypotheses | Audience research |
| Missing tech/timing became disqualification | Separate fit, readiness, urgency and owner policy; unknown means research | ICP/qualification |
| Attractive copy implied partnership or target pain | Require target evidence and approved claim/offer scope | Messaging examples and downstream campaign checks |
| Website treatment mistaken for a transparent logo master | Preserve original bytes, derivation and missing variants | Asset pipeline only |

These rules, not the edited answers, are what must survive a fresh brand run. Preserve negative findings and uncertainties even when a reference document looks polished.
