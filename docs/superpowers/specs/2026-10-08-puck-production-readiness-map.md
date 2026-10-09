# Website agent on Puck: production readiness map

Status: **draft for founder discussion** (2026-10-08). Companion to the roadmap
(`2026-10-08-website-agent-on-puck-roadmap.md`) and the spike findings
(`trials/puck-spike/AGENT-FINDINGS.md`, `trials/puck-spike/ISSUES.md`).

Built from three read-only code surveys of this branch, plus my own checks:
- the platform website agent: 34 design tools, 4 platform reads, 7 built-ins and 35 skills;
- the website editor: 24 features;
- the backend surfaces, with 14 places that assume the WebDoc format or the Rust engine.

Founder ruling already in force: clones first; a component is made only when a request needs
more than a clone allows (2026-10-08).

## 1. The two agents side by side

| | Platform website agent (solo) | Puck spike agent |
|---|---|---|
| Tools | 34 design + 4 reads + 7 built-ins + `task` (about 46) | 12 (15 with section writing) |
| Fixed prompt | about 33k–48k tokens before the first message (prompt ~11k, tool descriptions ~14k, built-ins ~3.5k, skill catalog ~2.5k, brand card) | about 6.7k tokens, skills included |
| Skills | 35 listed, 18 of them for ads or print; the 17 web skills are about 42.7k words if all read | 3 (about 2,200 words), plus 2 for writing sections |
| Page format | WebDoc nodes and Tailwind classes, written by HTML authoring and engine ops | JSON over our React components, written with file tools |
| Cost of a Syracuse page | $4.14 (run 3) | $0.57–0.99 |

## 2. Tools: what to keep, port, replace or drop

**Verdicts:**
- **Keep:** the spike already has it, or uses the same platform service.
- **Port:** wrap the platform's existing code as a tool in the new harness.
- **Replace:** the job is done differently on Puck.
- **Drop:** not needed.

### 2.1 Logos and images

| Platform tool | What it does | Verdict for Puck | Notes |
|---|---|---|---|
| `fetch_logo` | Brandfetch plus a scrape of the company's site; four logo variants; cached per workspace | **Port** | The same `logo_fetch.py` and cache. The account's logo becomes an asset the page references. |
| `bind_account_logo` | Binds a logo to a design account for `{{account.logo}}` templates | Later | Needed only for one-to-many templates (roadmap phase 4). |
| `asset(generate_image)` | OpenRouter image model, with brand style references; ledgered | **Port** | Founder direction: the agent generates images at runtime. |
| `asset(use_*)` | Registers an image so the page can reference it | Replace | On Puck an image is an asset file in a prop; there is nothing to register. |
| `search_assets` | Searches the workspace library, the brand kit and the document. **Keyword ranking only on this branch.** | **Port, with the CLIP search** | Hybrid keyword + CLIP image search exists on `design/linkedin-ad-skill-testing` (commit `deb3a0e98`), wired for the ad agent only. Merge it and use it for websites too. Today the spike lists every brand image in `brand.md`, which won't scale to a workspace library. |
| `view(asset:)` | Looks at an image | Keep | The spike's `view_asset` already reuses the platform's image block. |

### 2.2 Web evidence and research

| Platform tool | What it reads | Verdict | Notes |
|---|---|---|---|
| `web_search` | Exa, about 1¢ per call, recorded on the cost ledger | Keep | The spike already calls the platform's own read. |
| `fetch_page` | A public page, behind SSRF, size and time guards | **Port the guards** | The spike's own fetcher has none of these guards. |
| `provenance` | Cites fetched sources on page nodes | Later | Decide whether the page needs per-section citations for review. Today the spike keeps evidence in `fetched/` and the plan. |
| `read_project_accounts` | The project's accounts | **Port** | Needed when one request covers several accounts. |
| `read_account_research` (`@3`) | **ARV2 display pages** (overview, insights), the buying committee, and gated claims. Dossiers and research-view snapshots are not granted to design. | **Keep the display pages; port the claims read as a tool** | The spike reads overview and insights once into `research/` but strips the claim ids. See §3. |
| `read_claims` | The claim store, gated (no sensitive, unverified tier-4 or outreach-unsafe claims) | **Port** | On demand: check a fact's source and quote before using it. |
| Seller knowledge (files) | The pinned brand-knowledge documents, the confirmed product set and the ICP | Keep | The spike reads the same pin. |
| Project context (files) | The pinned `instructions.md` and `decisions.md` | **Port** | The spike lacks it; it's a file mount. |

### 2.3 Clones and sections

| Platform tool | Verdict | On Puck |
|---|---|---|
| `search_cloned_sections`, `inspect_cloned_section` | Replace | The catalog (`catalog/index.md` plus one card per clone) and `view_clone`. In production the catalog is built at session start from the workspace's **released** clones, honouring the `degraded` flag. At hundreds of clones a search tool may be needed again. |
| `insert_cloned_section`, `assemble_cloned_sections`, `recreate_cloned_page` | Drop | The agent writes `ClonedSection` entries into the page JSON directly. |
| `repair_cloned_section`, `compose_web_section`, `release_repair` | Replace | Clone slots, replacements and links cover small changes. Bigger changes go through an on-demand rebuild into a component (`view_clone`, `write_section`, `compare_section`; the founder ruling). No raw HTML composition. |
| `mint_campaign_shells`, `assemble_abm_page` | Replace | The spike's `shell.json` (a header with "prepared for", and a footer), built from the brand. |
| `review_cloned_page` | Stays in ingestion | A capture-quality check, not the page agent's job. Its `degraded` verdicts feed the catalog. |
| Custom components (5 tools; sandboxed TSX, account-local) | Replace | `write_section` (brand-token lint, type check, schema). How agent code runs safely in production is decision D2. |

### 2.4 Building, rendering and finishing

| Platform tool | Verdict | On Puck |
|---|---|---|
| `author_web_page`, `author_web_subtree`, `patch_web_page`, `web_ops` (8 op kinds) | Replace | File tools on `page.json` plus `validate_page`. The spike made no Puck mistakes in 296 calls. |
| `list_pages`, `add_page`, `remove_page`, `switch_page` | Replace | `pages/` plus shell navigation (done in the spike). |
| `render_web_preview` plus `view(preview, layout, typography, state, review, doc, node)` | Keep `render_page` | Desktop and mobile tiles with facts. Tablet and interaction-state captures could be added if needed. Typography reference checks aren't needed: brand sections set type by construction. |
| `set_web_typography_reference` | Drop | As above. |
| `finalize_web_run` | **Port the contract** | The leg runner needs a run result: status, summary, current version, model calls, clarification. The spike's finish guard plus final message map onto it. |
| `request_clarification` | Later | Scene agent only today. |
| `write_todos`, `task` (and a probable unintended general-purpose subagent) | Drop | Keep the harness lean. |
| Limits: 75 mutations per render, recursion 200 | Align | The spike's 40-call safety stop should follow the standing ruling (100 rounds, 50 calls per round, 30 min). |

### 2.5 The resulting tool set

**Removed completely (27):**
- **Engine authoring:** `author_web_page`, `author_web_subtree`, `patch_web_page`, `web_ops`.
- **Pages:** `list_pages`, `add_page`, `remove_page`, `switch_page`.
- **Clone placement and repair:** `search_cloned_sections`, `inspect_cloned_section`, `insert_cloned_section`, `assemble_cloned_sections`, `recreate_cloned_page`, `repair_cloned_section`, `compose_web_section`, `release_repair`.
- **Campaign shells:** `mint_campaign_shells`, `assemble_abm_page`.
- **Rendering and checks:** `render_web_preview` and its many `view` targets, `set_web_typography_reference`.
- **Custom components:** `list_custom_components`, `inspect_custom_component`, `write_custom_component_source`, `compile_custom_component`, `place_custom_component`.
- **Other:** `provenance`, `bind_account_logo` (until templates), `write_todos`, `task`.
- **Moved out of the agent:** `review_cloned_page` stays in ingestion.

**Reused from the platform (8):**
- `fetch_logo`
- image generation
- `search_assets`, with the CLIP search merged in
- `read_project_accounts`
- `read_account_research` (used at session start to write the research files)
- `read_claims`
- `web_search`
- `fetch_page`'s safety guards

The image block behind `view_asset` is already reused. The run-result contract lives in the harness, not in a tool.

**The Puck agent's tools (about 19):**
- file tools (6);
- `validate_page`, `render_page`, `restore_version`, `view_asset`;
- `web_search`, `fetch_page`, `fetch_logo`, `generate_image`, `search_assets`, `read_claims`, `read_project_accounts`;
- with section writing: `write_section`, `view_clone`, `compare_section`.

That is about 19 tools against about 46 today.

### 2.6 Tools to add (nothing like them exists on the platform)

The tools the spike added stay: `validate_page`, `restore_version`, `write_section`, `view_clone`
and `compare_section`.

## 3. Which research the agent should read

Three candidate sources:

| Source | Readable | Has the evidence | Granted to design | Cost to the context |
|---|---|---|---|---|
| ARV2 display pages (overview, insights, contacts) | Yes: curated sections | Each section lists its cited claim ids | Yes | Small (about 12 KiB per read) |
| Claims (`read_claims`) | Atomic facts | Source URL, quote, tier, verification | Yes | Paged; good for checking one fact |
| Dossier / research-view snapshots | Long and unstructured | Partly | **No** | Large |

**Recommendation:**
- **Display pages, written to files at session start.** The agent reads them, and every fresh session sees the same stable files. Keep the claim ids in the markdown; the spike strips them today.
- **`read_claims` as a tool,** for checking a fact's source and quote before it goes on the page.
- **No dossiers:** they aren't granted to design, are unstructured, and belong to the old lane.

Experiment R1 (§7) confirms this before we commit.

## 4. Skills: platform skill → Puck skill

| Platform skills | Verdict |
|---|---|
| create-website, campaign-page-workflow, campaign-landing-page, plan-design | Replace with the system prompt's steps, `building-with-puck`, and `plan.md` |
| conversion-copywriting (copy-craft), web-account-personalization (account-argument), web-decision-material | Replace with `account-page-copy`. Port specific proven rules from copy-craft and account-argument, each only with a failing case (the lean rule). |
| web-contact-personalization | Later, for person-level pages |
| web-media-composition (and the ad lane's generative-imagery lessons) | **New short skill, `images-and-logos`,** written when `generate_image`, `search_assets` and `fetch_logo` arrive |
| web-product-story | Later, if product-UI storytelling pages are wanted |
| design-guidance, web-source-readiness (faithful-repair, authoring-vocabulary, readiness, layout evidence), source-format-contract, repair-cloned-sections, edit-website, review-website, web-motion-fidelity, custom-components | Drop: they exist for HTML authoring, the repair rungs and engine conventions. Their jobs are done by the component model, `validate_page`, `page-review`, `writing-a-section` and `rebuilding-a-section`. |
| 18 ad and print skills | Drop. Today they are listed in the website agent's catalog by mistake: `brand-imagery` was read in all four baseline web runs. |

**The resulting skill set:**
- **The three base skills** (`account-page-copy`, `building-with-puck`, `page-review`), in the system prompt.
- **Loaded with section writing:** `writing-a-section` and `rebuilding-a-section`.
- **Coming:** `images-and-logos` when its tools land; contact pages later.

## 5. The editor on Puck, feature by feature

**How to read the table:**
- **Upgrade:** Puck gives something today's website editor lacks.
- **Port:** existing logic or UI moves over.
- **Build:** new work.
- **Same:** generic UI that stays.

| Today's website feature | On Puck | Effort |
|---|---|---|
| Edit/View toggle; device preview (desktop, tablet, mobile) | Puck preview and viewports | Same / small |
| Select an element | Puck selects a **section** (component). Selecting inner elements needs per-item fields or inline editing. | Port, with a design question (D4) |
| Inspector per element kind (Tailwind class "facets") | Each component's fields, rendered with our `inspector-primitives`. Brand choices (surface, heading role) are selects, not class strings. | Build (moderate) |
| Inline rich-text editing (Lexical in the iframe) | **Native in Puck 0.23:** text, textarea and rich-text fields take `contentEditable: true`, and rich text uses a built-in TipTap editor whose inline menu we can render ourselves (`renderInlineMenu`). Phase 1 already edits our sections' text and clone slot text in place (T5, T9). Left to do: use the rich-text field where formatting is wanted, and skin its menu. | Small |
| Clone text edits | The `ClonedSection` component's slots and replacements as fields, plus in-place editing of slot text (built in phase 1, `puck/clone-editor.tsx`) | Done in the spike; port |
| Replace image (**upload only today**) | An asset field using the ad lane's asset-library panel: library, upload, generate | **Upgrade** |
| Layers (depth 1, no reorder) | Puck outline: full depth, drag to reorder | Upgrade |
| Layout controls (flex/grid/gap/padding) | Whatever props each component exposes (governed by the brand). No free positioning, as today. | Same scope |
| Insert, delete, duplicate, reorder sections (**agent-only today**) | Native in Puck | Upgrade (needs a UI design ruling, D4) |
| Annotations sent to the agent | Port the reducer and popover; refs become component id plus prop path | Port, plus a backend change (§6, point 7) |
| Chat edits interleaved with manual edits | Same seam: reload on the agent's events, refuse manual writes during a run | Port |
| Undo/redo (server inverse ops) | Puck history in the client, plus server versions as JSON snapshots | Simpler |
| Version history (**a placeholder today**) | Real: full JSON snapshots per version (pages are small) | Upgrade |
| Multi-page: page switcher, page settings | The site model from the spike | Port |
| Publish, share, export (ZIP, PDF) | New publish package builder (§6, point 11); the menus stay | Build (backend) |
| Custom domains; gallery and artifacts library; tabs; rename and archive | Unchanged | Same |
| Custom component props form | Fields generated from each agent section's zod schema (already computed by the check) | Upgrade |
| Brand kit controls | Theme from the kit; token selects | Same |

**Visual design:**
- **We don't use Puck's own UI.** We use its parts (preview, fields, outline, component list) inside the chat-shell layout, skinned with:
  - `inspector-primitives` (1,852 lines);
  - `chat-shell.module.css` (3,481 lines);
  - the `@clue/design-system` tokens.
- **The standing rule applies:** the dummy UI is the presentation truth. The new abilities (insert palette, outline drag, versions panel, asset field) need designs from it before they are wired (D4).

**Size today, for comparison:**
- the website lane in the editor is about 14.5k lines of production code, plus about 8k of chrome;
- the Rust `lumen-web` engine is about 18.7k lines;
- `web_bridge.py` is 2,004 lines and `web_export.py` 2,223 lines.

On Puck the engine, bridge and class facets go away; the chrome (tabs, header, share menu, gallery, stage) stays.

## 6. Backend: what changes and what doesn't

**Unchanged (already format-agnostic):**
- design legs, runs, leases and the inline lane;
- the chat SSE plumbing and stop;
- the exit judge, clarification cards and derived turns;
- research and seller reads;
- the cost ledgers and Langfuse;
- publish storage, the page origin, the hostname registry and lock-at-first-publish;
- workspace scoping, which all of the above already do.

**The 14 places that assume WebDoc or the engine, and the change for each:**

| # | Place | Change | Size |
|---|---|---|---|
| 1 | `design_doc_kind` enum (`scene`, `web`) | Add `site` (one migration) | Small |
| 2–3 | Kind checks in `POST /documents` and the composer context | Accept `site` | Small |
| 4 | `create_document` / `update_web_document` read `id`, `title`, `theme.brand_kit` | Store the site as `{id, title, theme:{brand_kit}, pages, shell}`, which satisfies the existing contract with no DAL change | Small |
| 5 | Births (`mint_empty_web_document`) | Mint an empty site without the engine | Small |
| 6 | Envelope kind `web_turn` and its request | Add `site_turn` and a branch in the leg runner's `_envelope` | Small |
| 7 | Composer target validation (WebDoc node paths) | Validate component ids and prop paths against the page JSON | Small |
| 8 | Gallery and library SQL (`{meta,artifact_type}`, `{pages}`, web-or-else-ad mapping) | Map `site` | Small |
| 9 | Undo/redo by engine inverse ops | JSON snapshots (the undo stacks already exist) | Small |
| 10 | `/web/render`, thumbnails, export | **A site renderer:** server-side render of Puck pages to HTML, then Playwright for thumbnails and PDF | **Medium–large** |
| 11 | `build_publish_package` (engine plus Tailwind compile) | Static HTML per route plus one CSS file per site and assets, written into the existing publish tables | Medium |
| 12 | `design.op_batch` / `design.checkpoint` payloads | A "document changed" frame; the editor reloads | Small |
| 13 | Asset custody (AssetRecord-shaped) | Scan the page JSON for referenced assets and register custody | Small |
| 14 | Brand kit and asset records validated by the engine | Unchanged: we only read the kit | None |

**New backend pieces:**
- **A `site_turn` executor in the design fleet** that runs the Puck harness and returns the run result contract. The model calls flow into `agent_model_call` as today; the spike already records per-call cost.
- **A workspace view built from the database per request:**
  - the brand kit, turned into `brand.md` and the theme;
  - released clones, turned into the catalog;
  - the seller pin;
  - the research reads;
  - project context;
  - the site's current files.

  The page JSON is written back under CAS on `current_version`.
- **Agent-written sections in production** (D2): where their code lives (database or blob, not repo files), how it's built safely, and how the renderer loads it per workspace.
- **Head of ABM:** `open_design_leg` gains `doc_kind: site`, behind a per-workspace flag.

## 7. Readiness

**Proven by the spike:**
- the page model and validation;
- clones rendering as captured;
- the brand theme;
- multi-page sites;
- cheap builds and edits with a lean harness;
- components rebuilt from brand tokens;
- the two harness bugs found and fixed (the type check and Tailwind scanning).

**Not yet proven, with the cheapest test for each:**

| # | Open question | Test | Cost |
|---|---|---|---|
| R1 | Research input: display pages alone, or plus `read_claims` | Syracuse and Dana.AI builds both ways; compare fact accuracy, quotes and cost | about $3 |
| R2 | On-demand rebuild during edits | Three edits a clone can't do on a built page; time, look, cost | about $2–3 |
| R3 | Images | Wire `generate_image` and `search_assets` (with CLIP) into the spike; two builds | about $2 plus images |
| R4 | Quality parity with the platform agent | Blind founder rating: 3 accounts × 2 sellers, platform against Puck | about $15–20 |
| R5 | Rich-text formatting with our own inline menu (plain in-place editing is already proven in phase 1) | A short engineering check, no model spend | 1 day |
| R6 | Agent sections in production (build and isolation) | A design spike on D2 | 2–3 days |

## 8. Effort (revised from the roadmap's 8 engineer-weeks)

| Workstream | Engineer-weeks |
|---|---|
| 1. Shared package (components, schemas, theme, clone renderer, validator, catalog) | 1 |
| 2. Storage and the `site` kind (§6, points 1–9, 12–13) | 1 |
| 3. Site renderer and publish (points 10–11) | 1.5 |
| 4. Agent on the fleet (executor, workspace view, ported tools: logo, images, CLIP search, reads, fetch guards; result contract; legs) | 2–3 |
| 5. Editor in our UI (fields with our primitives, asset field, annotations, rich-text menu, pages, versions, live reload) | 2 |
| 6. Agent sections in production (after D2) | 1–2 |
| 7. Hardening: QA across sellers, the skills regression set, coexistence with WebDoc | 1 |
| **Total** | **about 9.5–11 engineer-weeks; 5–6 calendar weeks with 2–3 lanes** |

It is higher than the roadmap's 8 weeks because of the site renderer and agent sections in production.
(Correction 2026-10-09: inline editing is native in Puck and was proven in phase 1; it is not a risk.)

## 9. Decisions to make

| # | Decision | Recommendation |
|---|---|---|
| D1 | Where site documents live | A new `site` kind in `design_document`, in a shape that satisfies today's contract |
| D2 | Agent-written code in production | Decide after R6. The options: TSX built in a sandbox and loaded per workspace; a JSON layout language instead of code; or no agent code at first (which would delay on-demand rebuilds) |
| D3 | Research input | Display pages in files plus `read_claims` on demand; confirm with R1 |
| D4 | Which new Puck abilities get UI now | Insert/reorder/delete, versions, the asset library and the rich-text menu, each with a design from the dummy UI first |
| D5 | Where the renderer runs | The frontend app's server rendering, or a separate Node render service |
| D6 | Coexistence | A per-workspace flag. Existing WebDoc documents stay on the old engine; no conversion |
