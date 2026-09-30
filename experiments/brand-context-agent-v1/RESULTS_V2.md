# Conduit brand-context rework — review checkpoint

Open [the revised company overview](http://localhost:3046/#knowledge/company-overview), [the organization guide](http://localhost:3046/#knowledge/library-guide), [Assets](http://localhost:3046/#assets), [Brand kit](http://localhost:3046/#brand), or [the complete run report](http://localhost:3046/#evaluation).

This is a deeper standalone research draft. It has not been integrated into Clue or approved as production governance. The original 3045 preview and original run are preserved.

## What changed

| Folder | Documents | Decision supported |
| --- | ---: | --- |
| Company | 2 | Identity, business model, market position, customer evidence and material commercial unknowns |
| Product | 9 | Product catalog; Agents, Inbox, Portals and Workflows; Operator; developers; integrations; pricing |
| Brand & messaging | 4 | Positioning, brand voice, audience-to-message map and proposed campaign copy |
| Audience | 6 | Segment strategy, hotel/rental ICPs, buying committee, qualification and buyer problems/results |
| Proof | 2 | Attributed customer proof and comparison/alternative boundaries |
| Design | 1 | Original identity assets, display treatments, colors/type and missing variants |
| Library guide | 1 | Folder ownership, triggers, dependencies and existing-platform contract mapping |

Core product guides cover purpose, users/buyers, capabilities, limitations, concrete workflows, integration paths, packaging, differentiation, proof and discovery. Fit, implementation readiness and urgency are separate; unobserved technology is a research question, not automatic rejection. Titles/seniority/remit are professional buyer hypotheses, not invented personal demographics or numeric company gates.

## What the audit changed in the approach

The read-only Clue comparison showed that existing onboarding already had substantial individual product reports. The original pilot collapsed that depth into one page. Current onboarding also starts ICP before all detailed product research is complete. This experiment builds company/product/proof first, then messaging and audience decisions.

The experiment now accepts linked Markdown documentation, preserves citation cells in malformed tables, discovers official site/touch icons, detects transparency correctly in palette PNGs, and passes source-observed display treatments into structured Agent context. Research and generation instructions now require full FAQ coverage, entity/metric/window/causality checks, and explicit handling of conflicting sources. Those new instructions still require fresh cross-brand validation; manual correction of Conduit is not proof of autonomous generalization.

## Evidence and editorial quality

There are 103 public source records and 56 original assets. Assets combines website media with 16 distinct complete static LinkedIn creatives and three separate video covers. This revision reused the initial public harvest; it is not a fresh exhaustive ad search. Every asset exposes a human description and a separate Agent context panel. Original bytes and source lineage are preserved.

Separate critic calls reviewed 23 generated documents and produced 67 suggestions. Some were repeated or overreaching. Each has a recorded editorial disposition and document revision hash. Corrections included Easy BnB versus Bali Luxury Stays attribution, projected versus measured customer outcomes, staffed-support versus software-only savings, inconsistent credit meters, and Operator versus Operations. Two manually authored organization/identity documents were reviewed separately. No blind post-correction score or human approval is claimed.

## Verification

- 42 isolated unit tests passed.
- 12 real-run integrity checks passed, including exact evidence spans, document links, original hashes, separate approval state and unchanged original-run assets/sources.
- JavaScript syntax and Git whitespace checks passed.
- Browser inspection verified folders, rendered product tables/citations, source drawer, asset filtering/search, Agent context, four logo slots, and the review report. No console warnings/errors or desktop horizontal overflow were observed. Mobile responsiveness was not separately tested.
- Local preview/data/manifest returned HTTP 200. Environment, raw receipts and provider-cache routes returned 404.
- Six selected-bundle sales exercises: hotel fit, small-rental pricing, unknown PMS, product distinction and bounded copy passed on the first attempt. Logo handoff was partial, then passed a focused retest after adding the recorded website display treatment. These are parent-agent assessments, not a general retrieval benchmark, finished-ad test or human approval.

## Remaining gaps

The complete logo family is still **not four transparent originals**. Available: official dark SVG wordmark; its source-observed white footer display treatment; official transparent pale 512px icon. The light-background dark icon is only an opaque provider JPEG; request an official transparent master. Reverse-wordmark export requires the recorded treatment or a separate approved master. Palette roles, clear space and font permissions need owner confirmation.

Public availability, pricing paths, voice-credit rates and customer measurement windows contain conflicts. These remain specific questions alongside their sources. Target-company logos such as Hyatt are absent. No new ad image was generated.

Before integration: obtain human acceptance of representative company/product/messaging/ICP documents; resolve material commercial policies and identity masters; rerun the evidence-to-document pipeline on another brand without hand-curated answers; then agree the knowledge/asset contract changes and exercise production refresh, isolation, durability and latency. Existing claim-store and storage seams remain the intended production owners.

## Cost and runtime

Current-run reported model charges: **$5.92913**. A connection-failed logo test retained **$0.12053** as an uncertain reservation and was retried once; a reservation is not actual spend. The earlier reused run reported $4.010158 plus unreported Brandfetch/Adyntel costs. Development and Codex costs are excluded. Current-run ledger: 45 model attempts and 48 page attempts. No new paid ad harvest or image generation occurred.

This review required supervised research and editorial work. It does not establish onboarding latency or per-brand production cost.

## Files and restart

Source and tests are entirely inside `experiments/brand-context-agent-v1/`. Local outputs live in ignored `runs/conduit-rework-20260919/`: organized Markdown under `knowledge/`, structured documents, originals, sources, revision history, review/disposition records, exercises and a public preview. Provider responses and private runtime files are never served. No platform, database, environment or shared service changes were made. No push was performed.

From the repository root:

```sh
.venv/bin/python experiments/brand-context-agent-v1/server.py --run conduit-rework-20260919 --port 3046
```

From the experiment directory, these commands rebuild and verify saved local data without paid research:

```sh
../../.venv/bin/python rework.py package
../../.venv/bin/python -m unittest discover -q
node --check viewer/app.js
../../.venv/bin/python rework.py verify
```

Do not rerun paid research stages merely to open the result. Original model inputs and responses, failed validations and editorial history are retained for audit.
