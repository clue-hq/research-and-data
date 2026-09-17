# ARV2 frontend polish backlog (opened 2026-09-10; NOT to be applied in the R4 session)

Founder ruling 2026-09-10: no frontend change of any kind in R4, including the screens lifted from
the dummy frontend. Suggestions are stored here for a separate polishing session. Each line says
what discovery (R4) already stores so the polish is a display change only.

| # | Suggestion | What the store already has | Where |
|---|---|---|---|
| 1 | A **target-accounts tab beside Gallery** inside a project, listing the project's discovered and approved accounts (the founder's own design intent). | `project_account` rows with `added_via = 'discovered'`; `arv2_discovery_candidate` rows with `decision` | project shell |
| 2 | A **chat gate card** for cohort approval (set-valued, pre-checked = Best fit), the same shape as O6's product-set gate, writing the same `project_account` rows. | candidate rows + verdicts; the gate pattern exists (`open_product_set_selection_gate@1`) | Head of ABM tools + chat card |
| 3 | An **"unclear" tone** on the ICP-qualification badge (today `badge` renders positive only for the literal "High", neutral otherwise). | `client.icp_qualification` value "Unclear" | `accounts-table.tsx` badge tone map |
| 4 | A **"Qualification" section on the account detail** page: one row per hard gate with verdict, reason and source link. | `arv2_discovery_candidate.verdicts_json` (gate, verdict, reason, references) | detail recipes + a registered field per gate |
| 5 | An **Overall-fit filter value for "Unclear"** in the filter panel. | fit score already honest; badge value "Unclear" | `accounts-filter-panel.tsx` |
| 6 | Show the **discovery source** (Websets item URL, the run) as provenance on the account detail rail. | `arv2_discovery_candidate.provider_snapshot_json`, `source` | detail rail |
| 7 | Frontend follow-ups already recorded by O6 (wrapped Knowledge titles visual check; refresh hook arming). | — | see `_memory/2026-09-09-arv2-onboarding-o6-head-of-abm.md` |

## Brand context polish — scope for branch `brand-context-polish` (founder, 2026-09-12)

Findings from the code (2026-09-12): the Knowledge tree rows drift because the O6 lift let long
titles wrap (`min-height`, `align-items: flex-start`, `white-space: normal` on `.documentItem*`),
which also lets the flex layout squeeze the 16 px document glyph on wrapped rows; the dummy keeps
every row a fixed 32 px single line. The document body uses the dummy's own
`parseKnowledgeMarkdown`, which knows only `#`–`###` headings, `-`/`*` bullets and paragraphs, so
tables, blockquotes, links, italic and numbered lists render as raw text. Simple
bold in paragraphs and bullet items was already supported by a separate inline helper.

| # | Item | Ruling / source |
|---|---|---|
| B1 | Tree rows: one uniform 32 px single-line row, uniform 16 px document glyph (`flex: none`), one font. A name wider than the column is clipped; on hover it scrolls once end-to-start (marquee, single pass) then returns to the start. | founder 2026-09-12 (new hover behaviour; not in the dummy) |
| B2 | Markdown: render the full document — GFM tables, blockquotes, links, emphasis, ordered lists, code — with the page's existing `.markdownPreview` typography; replace the hand parser with **react-markdown + remark-gfm** for rendering and keep **CodeMirror** (`@codemirror/lang-markdown`, as the dummy's `markdown-source-editor.tsx`) for editing — nothing in-house. | ENG-183; founder 2026-09-12 (library ruling) |
| B3 | Typography panel shows the sample text in the extracted font (load the kit's font asset via `@font-face`). | ENG-181 |
| B4 | Assets panel: the asset fills the display section; description beside/below it. | ENG-182 |
| B5 | Items 1–7 above remain candidates for this branch where the founder picks them up. | — |

### B1–B4 implemented (2026-09-12)

Founder selected these four repairs first and explicitly required removal of all
locally built Markdown rendering. The block parser and inline renderer are deleted;
Knowledge uses react-markdown + remark-gfm directly. Rendering is this slice's scope;
the existing read-only page remains so, with CodeMirror reserved for the agreed editor.

Follow-up, founder 2026-09-12: add the Markdown Edit/Preview toggle. CodeMirror now
provides source editing with temporary per-document drafts and Discard changes;
Preview remains react-markdown + remark-gfm. The UI states that drafts are not saved.
Backend persistence is a pending scope decision for this frontend-only branch;
no document-write endpoint is implemented. See the matching follow-up in
`apps/frontend/docs/api-contracts/brand-context.md`.

B1 uses fixed rows, protected icons, and a single CSS animation measured against the
title column; keyboard focus and reduced-motion are covered. B3 carries the existing
kit face references through the frontend schema/mapper into namespaced `@font-face`
rules. B4 fills the preview proportionally without cropping, retaining responsive details.

Validation: 89 Brand Context tests pass; design-system build, lint and production
build pass (two unchanged design-editor lint warnings). Browser evidence in
`.context/brand-context-polish-2026-09-12/`: 32 px rows / 16 px icons, one-pass
overflow scroll and return, reduced-motion, semantic Markdown, a loaded font face,
full-frame asset sizing, desktop/mobile layout, normal Brand Context and Home routes.
The browser run used fixtures and a temporary sample-data route, subsequently removed;
it did not exercise a real tenant's stored font or external font-host availability.
All other frontend defects remain deferred.
