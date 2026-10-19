# Website ABM baseline — 19 September 2026

Four real website-generation runs completed on `codex/design-agent-v1` at `e646707b`. All four persisted as version 1 and reopened after a browser reload. All four returned `completed_with_warnings`. None is ready to promote as the requested high-fidelity, account-grounded standard.

This was a baseline, not an implementation pass. No application code, skills, brand approvals, authentication, environment files, or existing creatives were manually changed. The normal generation tools did create documents, register assets, and release composed sections/one campaign variant into their respective workspace libraries. Those generated sections must be excluded from the next source-library baseline.

## Runs and review links

| Seller → target | Saved page | Design time | Model calls | Preview rounds | Metered design-model cost |
| --- | --- | ---: | ---: | ---: | ---: |
| Clue → Google | [Open page](http://localhost:3021/projects/prj_f5efcb3b52f25cc091b81dccff354e37/chats/thr_030619f39ec9504793df1aa63148e4ec?surface=web) | 9m 36s | 32 | 2 | $2.27 |
| AWS → Insight Health | [Open page](http://localhost:3022/projects/prj_7a1276f31495561ebea13ac6ecd0f99a/chats/thr_835aa0c1f8445255aa1b732b7cd7c17e?surface=web) | 10m 28s | 36 | 2 | $2.78 |
| Google Cloud → NVIDIA | [Open page](http://localhost:3023/projects/prj_f98c45bf2fe15cdaaf17a9a64cbe53eb/chats/thr_5d528c939b015322a8b2a5261fa98ae3?surface=web) | 9m 03s | 21 | 1 | $2.07 |
| Conduit → Hyatt | [Open page](http://localhost:3024/projects/prj_b33b08e0cb955094b668a560b7462f18/chats/thr_7f03a5e66886506e901f595aa87a16ee?surface=web) | 7m 51s | 25 | 3 | $2.13 |

The links may reopen the project Gallery; select its single microsite card. All four artifact tabs were reopened for review. Nothing was published externally.

Time is database run creation to terminal persistence, excluding the initial Head-of-ABM conversation and the required second message. Cost totals $9.26 before rounding individual rows, for design-model calls only; it excludes the initial chat, logo/page services, and infrastructure. One run per workspace is diagnostic evidence, not a success-rate estimate.

## Test procedure and limitations

Each workspace received the same ordinary request shape:

> Create an ABM landing page for [seller] aimed at [target]'s [team]. Invite them to discuss a pilot. Match [seller]'s real website design and use our existing brand context and website components.

Teams were Google's marketing team, Insight Health's technology team, NVIDIA's technology team, and Hyatt's hotel operations team. These reuse the prior ad-test pairings. Insight Health was not independently entity-resolved; its exact company/domain remains ambiguous.

The Head of ABM opened a design session but required a second message. Every session received exactly “Go ahead and create it.” The design runs started within 44 seconds of each other and overlapped. No prescribed headline, component ID, image prompt, manually supplied reference, or private prompt override was used.

Verification performed:

- Reviewed the final rendered screenshots at 1440, 768, and 375 pixels for all four pages.
- Checked each saved artifact in the authenticated app, reloaded, and reopened it from Gallery.
- Checked database status, document version, account binding, final outcome, tool traces, and model-call receipts.
- Opened the real seller websites separately and inspected their hero designs and visible content. Source viewport screenshots are saved. This is a qualitative comparison, not a controlled pixel-difference score; source sites can change or rotate hero slides.
- Opened and closed Conduit's booking dialog and inspected its outgoing booking link. No external form was submitted. Other CTA destinations were inspected, not submitted or exhaustively tested downstream.

No source change was made, so no code-test suite was run. Cross-account derivation, website publishing, keyboard accessibility, and export were not tested in this pass.

## What the current system actually does

1. Website ingestion captures rendered HTML, CSS, screenshots, assets, and measured geometry; extracts the brand kit; and attempts to mint reusable section fragments. Fragment/snapshot failures are deliberately nonfatal to brand-kit ingestion.
2. The platform conversation opens a web design leg with a frozen brief, selected kit, document, and optional account context.
3. The web harness exposes the skill catalog and tools. The current local configuration uses `LUMEN_AGENT_WEB_SOLO=1`: one Grok 4.6 agent performs planning, authoring, and its own review. A separate visual reviewer is not active in these runs.
4. The agent searches approved fragments and brand assets, views candidates, fetches public source text, writes a section plan, and selects between pinning, slot rebinding, deriving a campaign variant, repairing a broken source, composing raw HTML/CSS, or authoring with the typed component vocabulary.
5. The engine renders previews. The agent inspects them and may repair the page, then chooses its final outcome.
6. The API replays and validates the operation history before persisting the website. The website is committed at the end of the turn, so a user can wait several minutes without seeing an applied intermediate page.

These four runs reused existing or fetched images. Their traces contain no image-generation event. Website generation here was primarily copy, markup, asset selection, and layout; it did not generate a new background image each time.

## Source map

Paths below are relative to this subsystem unless explicitly rooted elsewhere.

| Responsibility | Current files | Audit finding |
| --- | --- | --- |
| Capture and ingestion | `apps/api/lumen_ingestion/pipeline.py` (`run_website_ingestion`, `_mint_page_fragments`); `site_snapshot.py`; `capture/snapshot.py` | A successful kit is not proof of complete, reusable website capture. |
| Section segmentation | `apps/api/lumen_ingestion/sections/{bands,segment,mint}.py` | Preserve DOM/CSS/geometry/provenance; coverage and segmentation need a separate readiness check. |
| Fragment search and release | `apps/api/lumen_api/agent_cloned_sections.py` | Search lists approved rows only. Capture drafts and generated sections have different release paths. |
| Fragment mechanics | `apps/api/lumen_api/fragments/{artifact,cssscope,isolation,render,slots,abm_page,campaign_shell,registry,sanitize,cssflatten}.py` | Native layout custody, scoped CSS, editable slots, campaign shells, and variant lineage already exist. |
| Web request/persistence | `apps/api/lumen_api/main.py` (`run_web_agent_turn`, `_execute_web_turn_job`) | Frozen context in; replayable operations out; persistence checks structure rather than source fidelity. |
| Harness and instructions | `apps/agent_runtime/lumen_agent/{harness_web,prompts_web,knowledge}.py` | Solo mode and long sequential model/tool loop are active. Developer docs are not agent skills. |
| Website tool surface | `apps/agent_runtime/lumen_agent/tools/web_substrate.py` | Search/view/fetch/compose/render/review/finalize; finalization lacks an explicit fresh source-comparison/visual-verdict gate. |
| Skills and recipe | `apps/agent_runtime/knowledge_docs/skills/`; `knowledge_docs/knowledge/web/abm-page.md` | Several relevant skills already exist; there are conflicting shell/personalization instructions. |
| Visual rubric | `apps/agent_runtime/lumen_agent/rubrics/clone-review-rubric.md` | Structural checks do not establish the requested fidelity and craft standard. |
| Frontend | repository root `apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx`; `engine/{webDocuments,webBridge}.ts`; `data/web-publish.repository.ts` | Saved microsites render in the existing project artifact surface. |

## Findings, in priority order

### 1. Three workspaces had zero usable captured sections

The inventory was frozen before generation:

| Workspace | Captured fragments present | Approved and searchable | Draft |
| --- | ---: | ---: | ---: |
| Clue | 8 | 0 | 8 |
| AWS | 4 | 2 | 2 |
| Google Cloud | 4 | 0 | 4 |
| Conduit | 1 | 0 | 1 |

Clue had an older eight-section capture, but its latest selected kit had no corresponding fragments. Google's sparse captures mostly resembled navigation/security text and a footer. Conduit had only a hero. AWS's approved set was a security hero and global-infrastructure section, not a complete site.

The approved-only filter is a real boundary, not a claim that these drafts should be blindly approved. The missing step is a usable capture → review → release path and a readiness report that exposes incomplete capture before the design run.

Result: Clue and Google composed every final section; Conduit authored through the component vocabulary. Only AWS derived a section from a released capture. “Use our existing website components” therefore could not achieve faithful reuse in three workspaces.

### 2. Campaign-shell setup prevents the intended assembly path

AWS, Google, and Conduit minted header/footer shells, but these remained draft and uninsertable until kit re-approval. Clue's shell tool reported no usable kit logo even though the agent could find a usable Clue mark elsewhere. Google also hit an unmatched `prepared_for` slot when composing a campaign header.

All four fell back to composing page chrome. This needs a coherent preflight and release lifecycle, plus consistent logo selection. It is not fixed by telling the model to “make it on-brand.”

### 3. None of these pages has a target-account binding

All four persisted `account_id = null`; their frozen context had no account claim references/binding set. Clue, AWS, and Google used literal company names; Conduit used Hyatt as a fallback variable value. These are personalized concept pages, not verified account-derived templates.

Seller facts can still be grounded in fetched public pages. What is missing is the target side: resolved identity, relevant needs, verified stack/initiatives, and the reason to select two or three features. The next test must attach an actual account through the existing shared context seam and exercise derivation; it should not start fresh discovery or invent research inside the design subsystem.

### 4. Current review passes visible defects

| Page | What worked | What prevents acceptance |
| --- | --- | --- |
| Clue | Recognizable serif, warm/dark palette, real product imagery; readable mobile text | Hero replaces the real landscape/centered composition with a flat beige, left-aligned text block. Long desktop and mobile page. “Discuss a pilot” goes to the homepage, not a pilot endpoint. |
| AWS | Real captured hero lineage and cubes; coherent type/buttons; readable mobile layout | Body is mostly repetitive text bands with little account-specific proof. Target identity unresolved; no target logo. Healthcare fit follows the name, not a researched account. |
| Google Cloud | Recognizable typography, blue buttons, authentic marks and imagery | Large mobile gaps; imagery poorly explains the adjacent infrastructure/agent claims; repeated seller wordmarks. Copy exposes planning caveats such as “These are named, not linked” instead of explaining buyer value. |
| Conduit | Recognizable serif, real product screens/landscape; working booking dialog | Several section headings are smaller than supporting copy; closing text has weak contrast over the gradient; footer shows an arrow-like mark instead of the seller wordmark. Hyatt logo absent after a loyalty-program asset was correctly rejected. |

The Clue/AWS/Google automated page walks reported no broken clones or page findings. All outcomes were still warnings, not accepted. The finalization function accepts the agent's outcome string and writes the result; the API's operation-replay checks do not add a visual-quality decision. Solo self-review is not sufficient evidence of fidelity.

### 5. Instructions conflict, despite being loaded

Runtime filesystem logs after the first model call show nine shared skill reads in all four runs: `campaign-page-workflow`, `campaign-landing-page`, `conversion-copywriting`, `create-website`, `edit-website`, `repair-cloned-sections`, `plan-design`, `design-guidance`, and `brand-imagery`. Conduit also read `review-website`. This is evidence of loading, not proof of compliance or quality.

The workflow allows native navigation versus minimal campaign chrome as a judgment call. The ABM recipe mandates campaign shells and forbids native navigation. It also requires reusable account markers, while the ordinary name-only handoff supplies no bound account. The solo prompt says personalization markers are not a reason to abandon raw fragments, yet Conduit's plan used that as its reason for a whole-page vocabulary build.

The recipe's prohibition on resource links also surfaced literally in visitor-facing copy. Internal limitations and safety reasoning should remain in the review report; the page should contain useful, substantiated buyer copy.

### 6. Latency is primarily the model/tool conversation

The four design runs made 114 metered model calls. Summed model latency was 521.7s (Clue), 580.6s (AWS), 504.6s (Google), and 424.4s (Conduit), approximately 90–93% of each persisted run duration. This excludes the first chat handoff. It is not primarily image-generation time: none of these runs generated imagery.

Each first model request already carried roughly 37–38k input tokens. Repeated context across the turn totals millions of input tokens per run; those totals are repeated requests, not unique source content. Clue registered 53 assets. Setup gaps then caused extra composition, shell fallback, slot/operation repairs, and render rounds.

Fix prerequisites first; then reduce repeated catalog/context and unnecessary sequential calls. Increasing the number of agents or skills without this work is unlikely to improve latency.

## Proposed implementation sequence

1. **Isolate website work.** Create `codex/website-generation-v1` from the agreed current design checkpoint after review. Give it its own database, storage, agent workspace, ports, workers, logs, and Next cache. Keep the existing Brand Asset Intelligence and `ICP-definition/head-of-ABM-improvements` worktrees separate. A Git worktree alone does not isolate runtime state.
2. **Make source components usable.** Audit the capture/segmentation diagnostics; retain real CSS, fonts, assets, breakpoints, interactions, source screenshot, and kit version. Establish reviewed reusable coverage for the required bands. Report unavailable/degraded components explicitly. Do not blanket-approve capture drafts.
3. **Repair preflight contracts.** Resolve seller light/dark logos and working CTA; prepare usable campaign chrome through the approved release policy; bind the target account and a bounded claim bundle. Resolve the shell/recipe contradiction before changing presentation contracts.
4. **Tighten the existing skill family.** Preserve the division below rather than adding a generic skill for every layout. Reference actual section ancestors and choose flexible compositions based on the evidence.
5. **Enforce review and shorten the loop.** Require fresh rendered evidence tied to the final document, source comparison for reused/derived bands, readable hierarchy/contrast, working conversion, and explicit account grounding. Make warnings and unverified fidelity visible. Evaluate an independent bounded review only after those inputs are available. Separate small edit turns from new-page planning and expose durable intermediate preview progress.
6. **Repeat the frozen four-brand test.** Keep the original pages intact. Use the same briefs, model settings, and source snapshot cutoff; exclude sections generated by this baseline. Compare first delivery, edit latency, source fidelity, factual targeting, and responsive quality. Then test another account per seller and repeated generations to establish robustness.

| Existing skill responsibility | Improvement to make |
| --- | --- |
| `campaign-page-workflow` | Readiness/coverage checks and compact source manifest; clear report when real reuse is unavailable. |
| `campaign-landing-page` | Account-specific argument and evidence selection; reconcile campaign chrome policy. |
| `conversion-copywriting` | Evidence-backed relevance, concise headings, density matched to source, no internal caveats in page copy. |
| `create-website` | Preserve native section geometry/assets/type and distinguish faithful reuse from approximation. |
| `edit-website` | Small scoped edits with preserved components and a bounded render/verification loop. |
| `repair-cloned-sections` | Explicit campaign variant versus canonical repair; preserve untouched responsive behavior. |
| `review-website` | Source-visible review and concrete checks for the defects observed here; final-state evidence. |
| Shared planning/design/imagery skills | One compact reference context; correct logo mode, image purpose, crop, and semantic type roles. |

Acceptance should distinguish **delivery** from **quality**. This baseline achieved 4/4 persisted drafts, but 0/4 pages cleared the complete proposed promotion bar: source-faithful visual system, verified target relevance, correct identity, responsive readability, real conversion, and reproducible account derivation. This is an audit judgment on four samples, not a statistically measured quality percentage. No four-minute website SLA has been established by this test.

## Evidence and continuation

Local evidence is under `../.design-runs/evaluation/website-baseline-20260919/`: initial inventory and source hashes, completion snapshot, run results with model receipts, and per-brand plans, traces, final documents, source viewport captures, and final 1440/768/375 previews. This directory is ignored and is not part of the source commit.

Run IDs: Clue `run_98b8c34402c7565e97e6b5b691089e95`; AWS `run_a4b49298279850d689498e2c3a77b158`; Google `run_19aab70b4b5653ec98002afb90061463`; Conduit `run_f726f44dd1d25d2baf2ed6b36462c2f4`.

One misleading agent self-report was checked: AWS warned its campaign variant could replace future canonical pins. The saved `derived_reason` contains `campaign variant`, and `_resolve_lineages` explicitly separates those variants from canonical replacement. Do not treat that warning as a confirmed canonical overwrite.

The run-view helper found no `run_metrics` stream event for these website runs. Timing/cost above comes from database terminal timestamps and persisted `model_calls`, not an inferred missing metrics file. Missing source-comparison evidence is recorded in run summaries; the exact provenance/capture cause still needs the next implementation audit rather than being assumed solved here.
