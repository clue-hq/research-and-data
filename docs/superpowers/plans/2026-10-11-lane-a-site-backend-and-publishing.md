# Lane A: site backend, renderer and publishing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Puck `site` document kind everything the backend owes it — the shared site-kit
caught up with the spike, brand fidelity in the kit, safe writes with undo and versions, composer
targets, gallery kinds, a hardened-Chromium renderer and cleaner, thumbnails, publishing with a
script-free policy, ZIP and PDF export, and the move of published pages to their own domain.

**Architecture:** Agent-written section code only ever runs inside one hardened headless Chromium
page per render (`lumen_api/site_render.py`), loaded from `data:` URLs by site-kit's browser
render bundle; Python and Node never import it (Node only bundles, validates JSON and compiles
Tailwind over returned HTML text). Every site write goes through three governed tools
(`design_write_site` / `design_undo_site` / `design_redo_site`) over the existing kind-agnostic
document write, with whole-site snapshots as history. Publishing reuses the web publish write
path after a site-specific package builder, the sanitizer `lumen_api/site_sanitize.py` and a
per-publish CSP that the page origin reads from the manifest.

**Tech Stack:** Python 3.12, FastAPI, Playwright 1.61 (sync API, Chromium 149), selectolax,
tinycss2, pymupdf; TypeScript, React 19.2.4, `@puckeditor/core` 0.23.0, Zod 4.4.3
(`z.fromJSONSchema`), esbuild 0.28.2, Tailwind 4.3 (the design editor's `@tailwindcss/node` +
oxide); Cloudflare Workers (`infra/cloudflare/pages-edge`).

**Spec:** `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md` — "Global
constraints", "Review focus", "D2", and "Wave 2: rulings and cross-lane contracts (2026-10-11)",
Contracts 1, 2, 3, 8 (backend half) and 9 (published pages half), plus the brand-fidelity ruling
(site-kit half). Background: `docs/superpowers/specs/2026-10-08-puck-production-readiness-map.md`
§5–§9. Code surveys: `wave2-survey-lane-a.md`, `wave2-survey-brand-domains.md` (scratchpad,
2026-10-11).

---

## Open questions for the founder

Each question below is a product decision the rulings do not cover. The plan is written with the
recommendation, and each answer changes only the place named.

- **Q1. What the Head of ABM's reads call a site.** `read_artifact@1`
  (`platform/api/clue_api/artifact_read_tools.py:170`), the project library
  (`project_library.py:438`) and the account-research document body
  (`account_research_turn_wiring.py:257`) all tell the Head of ABM a document's kind.
  (a) Say `site`. (b) Say `web`, as for a WebDoc. **Recommended: (b)**, because the Head of ABM is
  unchanged by ruling and opened the leg with `doc_kind="web"`; the gallery and the editor still
  receive `site` (Contract 8). Changing it later touches only Task 10 Step 5.
- **Q2. The published site page's head.** (a) Per page: `<title>` and `og:title` from the page's
  own title (`root.props.title`, else the document title); description = the workspace's default
  page description; `og:image` = the workspace's default social preview; the workspace favicon;
  `noindex` when the document's durable flag or the request asks. (b) As (a), but derive each
  page's description from its first paragraph, as WebDoc does. **Recommended: (a)** for the first
  release; the agent writes the visible text and a derived description is a second judgement call.
  Changing it touches only `_site_page_head` (Task 20).
- **Q3. A "Button style" field on our own sections.** The kit gets a second button style for
  agent-written sections (Task 5). Should FeatureSplit and CtaBand gain a "Button style" select
  (primary / secondary)? A select is an existing field kind, but it is a new editor control, so the
  plan does **not** add it. **Recommended: yes, once you approve the control**; it is one schema
  enum and one field per section.
- **Q4. Extra and band surfaces on our own sections.** The kit's band and extra surfaces
  (`surface.band.*`, canvas, elevated, accent) reach agent-written sections (`kit.Shell` and the
  classes) and brand.md (Tasks 4, 5, 7). Our own sections keep their six fixed choices, because
  their schema is the same for every brand. (a) As written. (b) Make our sections' surface choices
  brand-dependent. **Recommended: (a).**
- **Q5 — ANSWERED 2026-10-12: retirement is out of scope for sites; (a) a retired section still
  publishes. The two publish refusals use founder-approved wording (Task 20).** Original question:
  **Clone pins at publish.** Publish refuses a cloned section that the workspace's registry
  does not hold, or holds as `draft` (Task 20). A section that was `deprecated` after the page used
  it: (a) still publishes (WebDoc's posture: a retirement never breaks published work), or (b) is
  refused. **Recommended: (a).** Changing it touches only `_PUBLISHABLE_CLONE_STATUSES`.
- **Q6. The custom-domain refusal copy in Settings → Pages.** The app shows "Hostnames under
  cluehq.ai cannot be connected." (`apps/frontend/src/features/settings/model/pages.ts:80`). After
  the move the new pages domain is refused as well. **Recommended copy:** "Hostnames under Clue's
  own domains cannot be connected." It is user-facing, so Task 23 Step 9 changes it only after your
  approval.
- **Agent-facing text to approve** (ruling: shown to the founder before it is written): the
  section-check refusals in Task 1 (ported from the spike), the three refusals in Task 6 (raw
  links, undefined brand classes, section ids), and the whole brand.md template in Task 7. Each
  task's first step is the review; nothing is written before your yes.

## Contract conflicts and ordering gaps

No contract is impossible as written. Five findings refine a contract inside Lane A's own code, and
one is an ordering gap between lanes that the master plan should record.

1. **Ordering gap: Lane A needs Lane B2's `BrandData` builder before saves, thumbnails, publish
   and export work end to end.** The site-kit validator (Contract 2), the renderer (Contract 3)
   and the font licence gate all need the site's `BrandData`, which the rulings give to Lane B
   ("turning the stored kit into `BrandData` → Lane B"). Lane A ships a seam
   (`app.state.site_brand_loader`, default `brand_loader_not_composed`) that refuses with
   **503 `site_inputs.unavailable`** until B2 replaces that one assignment in
   `lumen_api/main.py`. Likewise the agent-section modules and their stored props schemas come from
   B6's `get_site_sections` (Contract 4): until B6 replaces `app.state.site_section_loader`, a site
   with agent sections is refused (`site.invalid` on save, `site_publish.section_module_missing`
   on publish), and a site without them works. **Add to the master plan's order list: "B2's
   `BrandData` builder before C2's saves work against a real workspace."**
2. `render_site` gains two optional keyword arguments, `max_output_bytes` and `node_bin`
   (Contract 3 lists `timeout_s` only); `capture_site_screenshot` gains `height`, `scale` and
   `timeout_s`. Both are additions with defaults; every call in the contract still works.
3. `capture_site_screenshot` runs with JavaScript off and the network blocked, so it can only show
   images that are already `data:` URIs. Callers inline `/asset-store/` references first with
   `web_pdf.inline_asset_store_refs` (Tasks 18 and 22 do).
4. Playwright's `route_web_socket` is used, but its handler must **not** call `ws.close()`: with
   the render page's CSP, closing from the handler hung the page in Playwright 1.61 (probe,
   2026-10-11). A handler that never calls `connect_to_server()` keeps the socket mocked, so it
   never reaches the network.
5. `PUT /documents/{id}/site` and the undo, redo and restore routes add two refusals beside
   Contract 2's list: 409 `document.finalized` (every manual write route has it) and 503
   `site_inputs.unavailable` (gap 1).
6. `read_section_schema` also refuses a module whose schema is not a Zod object, lacks `id` or
   `surface`, carries `className`/`style`, or has no `render` (the checks the spike's
   `check-section` CLI ran after importing the module — D2 moves them into the render page).

### Controller review rulings (2026-10-11) — already applied to the tasks below

- **R3 — the editor's brand read.** No lane served the `BrandData` the editor frame's `init` needs
  (Lane C's K3). Task 13 adds `GET /documents/{id}/site/brand` → `{schema_version, brand}` through
  `app.state.site_brand_loader` (503 `site_inputs.unavailable` until B2).
- **R6 — the site tools are registered ungranted.** As first written, Task 12 granted
  `design_write_site` / `design_undo_site` / `design_redo_site` (and Task 21 `design_publish_site`)
  to `AgentRole.DESIGN` without a design profile pinning them. `build_agent_profile_registry`
  refuses that ("profile 'design' differs from reviewed authority", `agent_registry_wiring.py:1027-1040`)
  and runs at platform start-up (`agent_platform_wiring.py:474`), so the platform API would not
  have booted. No model names these tools (the editor's routes and the site turn's executor call
  them), so they are registered `()` on the ad-assets lane's footing, with a `SITE_DOCUMENT_LANE`
  set in the authority audit. Lane A mints no design profile; Lane B Task 14 mints `design@v5`.
- **R8 — `design_leg_wiring` labels and summaries are this lane's.** Task 9 owns
  `:338, :408, :869, :972, :1516-1520`; Lane B Task 13 no longer edits them and needs Task 9 landed.
- **R10 — section ids.** Task 6 adds a validator rule: a section id uses only letters, digits, `-`
  and `_`, so `site:<route>#<id>.<field>` (Task 14) is never ambiguous and the editor (whose schema
  enforces the same pattern) can open every stored site.
- **Order (master plan):** B2's `BrandData` builder before C2's saves work against a real
  workspace; Task 9 before Lane B Task 13; Lane C's C1 before Task 10's mapper.

---

## Global Constraints

- **Git:** never push. Commit locally at checkpoints, with no AI attribution in messages (no
  `Co-Authored-By`, no "Generated with" footer). Work stays on a feature branch, never `main`.
- **Env parity:** every new runtime flag goes into `.env.example` with its default the moment it
  is introduced. A design-API flag (`LUMEN_*`) also goes into `subsystems/clue-design/.env.example`.
  Mirror each new line into the lane's own `.env` at its default (never committed).
- **Alembic:** Lane A adds no migration. If one becomes necessary: `alembic revision -m "<slug>"`,
  a matching `downgrade()`, exactly one head, `make db-smoke` on `clue_trenton_wave1` only.
- **WebDoc stays untouched.** With the flag off, every existing path behaves byte-identically. No
  old-lane gate may block the new lane. Every refactor of a web function in this plan
  (`compile_tailwind_css`, `_commit_publish_package`, `_print_page`, `delivery_csp`) keeps the web
  output byte-identical, and the existing web suites prove it.
- **Founder rulings (2026-10-08 and 2026-10-09):** clones first; the marketer never sees "clones"
  or "components"; contracts live in code, judgement in prompts; agent-facing prompt or skill text
  is shown to the founder before it is written; the editor UI comes only from the existing
  chat-shell / dummy UI, so new controls need a design first; no pre-emptive caps on agents.
- **Engineering rulings for this lane (2026-10-11):** one save = one undo step, one agent turn = one
  step, cap 50; site writes refused during a running site turn; clone pins validated at publish
  (not every save); `GET /documents/{id}` treats site like web (no scene `render_context`,
  `account_id` exposed); exit-judge and summary labels treat site like web ("web page"); published
  sites are script-free; the sanitizer runs over the whole page; the font licence gate is reused;
  new modules are named `site_doc_*`, `site_render`, `site_sanitize`, `site_publish` because "site"
  already means WebDoc pages in `web_export.py`.
- **Agent-written code never runs on app.cluehq.ai or in a platform process (D2):** on the server
  only inside the hardened headless-Chromium render page. Node only transforms or scans agent code
  (esbuild, tsc, Tailwind); it never imports or runs it.
- **Brand fidelity (production requirement):** the agent sees every kit type role; surfaces cover
  band colours; the kit covers logos (`contain`), a second button style and in-site links.
- **Tests:**
  - never assert which model a setting names;
  - never run `*_live.py` or broad suites with real keys (`--ignore-glob='*_live.py'`);
  - database suites run only on `clue_trenton_wave1`, with the design stack down;
  - never run the whole design suite (over an hour); run the named files only.
- **Exact test commands:**
  - design API, from `subsystems/clue-design`:
    `set -a; source ../../.env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/<file> -q -o addopts="" --ignore-glob='*_live.py'`
  - platform, from the repo root:
    `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; .venv/bin/python -m pytest tests/<file> -q -o addopts="" --ignore-glob='*_live.py'`
  - site-kit: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts`
  - edge Worker, from the repo root: `node --test 'infra/cloudflare/pages-edge/*.test.js'`
  Below, `DESIGN_PYTEST <file>` and `PLATFORM_PYTEST <file>` stand for these two lines with the
  file filled in.

## Review Focus

1. **Two writers at once** (a stale tab saving with an old `base_version`, or a save while the
   agent's site turn runs): a typed 409 (`edits.base_version_mismatch` with `current_version`, or
   `document.agent_run_active` with `run_id`) and nothing written. Tests: Task 13.
2. **Undo, redo and restore sequences** (undo past the first save, redo after a new save cleared
   it, restore then undo the restore): each step lands exactly the site that stood before, and an
   empty stack answers 409 `undo.empty` / `redo.empty`. Tests: Task 13.
3. **An image from another workspace, or a digest nobody holds**, in a save: 422 `site.invalid`
   naming the image; the site is not stored (Contract 1 tenancy). Tests: Tasks 11 and 13.
4. **Hostile agent sections at render and publish** (an infinite loop, a huge page, fetch, an image
   beacon, a WebSocket, a `file://` read, injected `<script>`/`on*`/off-allowlist URLs, a missing or
   tampered module): a typed render failure with nothing sent out and the worker still rendering
   the next site; published HTML with the script, handlers and foreign URLs stripped; a missing or
   stale module refused with `site_publish.section_module_missing`. Tests: Tasks 16, 17, 20 and 21.
5. **Old published URLs after the domain move**: `https://<label>.pages.cluehq.ai/<path>?<q>`
   answers 301 to the same label, path and query on the new domain; custom hostnames and other
   `cluehq.ai` records are untouched; `*.cluehq.ai` stays unconnectable as a custom domain. Tests:
   Tasks 23 and 24.

---

## Cross-lane interfaces

**Lane A produces (other lanes rely on these names):**

- site-kit (Tasks 3, 15): `npm run build -w @clue/site-kit` writes `dist/validate-site.mjs`,
  `dist/build-catalog.mjs` and `dist/render-browser.js`; `validateSite(files, brand, agentSections,
  images?)`; `buildCatalog(brand, seller)`; `lint(source, options?)` and `LINK_REFUSAL`;
  `makeKit(href, brand)`; `tailwindThemeCss(brand)`; `extraSurfaceRoles(brand)`;
  `renderSitePages(...)` and `sectionPropsSchema(module)` in `src/render-core.tsx`.
- `lumen_api/site_render.py` (Task 17): `render_site`, `read_section_schema`,
  `capture_site_screenshot`, `site_page_html`, `site_routes`, `site_kit_dist`, `SiteRender`,
  `RenderedPage`, `SectionModule`, `SiteRenderError` and the four code constants.
- `lumen_api/site_sanitize.py` (Task 16): `sanitize_site_html(html) -> SanitizedHtml(html, removed)`.
- `lumen_api/site_doc_inputs.py` (Task 11): the two seams Lane B fills —
  `SiteBrandLoader = Callable[[HybridRepository, DesignBlobStore, JsonObject], JsonObject]`
  (B2: `(repo, blobs, document_row) -> BrandData`) and
  `SiteSectionLoader = Callable[[HybridRepository, DesignBlobStore, Mapping[str, str]], list[SectionModule]]`
  (B6: `(repo, blobs, {name: digest}) -> modules`, raising `SiteRenderError(SECTION_MODULE_MISSING)`
  for a digest this workspace does not hold). B2 and B6 each replace one assignment in
  `create_app` (`app.state.site_brand_loader = ...`, `app.state.site_section_loader = ...`) and pass
  the same loaders to the worker's `design_tool_host(...)` call in `execute_site_turn_job`.
- Governed tools (Tasks 12, 21), all four registered **ungranted** (ruling R6): `design_write_site@1` (input `{document_id, site, intent?,
  checkpoint_label?, actor_kind="editor", source="editor", expected_base_version}`),
  `design_undo_site@1` / `design_redo_site@1` (`{document_id, expected_base_version}`),
  `design_publish_site@1` (`{document_id, slug, noindex=False}`). B5 persists a turn with
  `design_write_site`, `actor_kind="agent"`, `source="agent"`, actor `"agent"`.
- Routes (Tasks 13, 21, 22) for Lane C: `PUT /documents/{id}/site`,
  `POST /documents/{id}/site/undo` · `/redo`, `GET /documents/{id}/site/versions?limit=`,
  `GET /documents/{id}/site/brand` (→ `{schema_version, brand}`; the editor frame's BrandData),
  `POST /documents/{id}/site/versions/{batch_id}/restore`, `POST /documents/{id}/site/publish`
  (body `{slug?, noindex?}`, response identical to `POST /web/publish`),
  `GET /documents/{id}/site/publish`, `GET /documents/{id}/site/export`,
  `GET /documents/{id}/site/export.pdf`. Unpublish and rollback stay
  `DELETE /web/publishes/{slug}` and `POST /web/publishes/{slug}/rollback`.
- Composer targets (Task 14): `design_node` refs with `object_id` `site:<route>#<componentId>`
  or `site:<route>#<componentId>.<propName>`, shell `site:shell#header|footer`;
  `validate_site_targets(site, ids)` and `resolve_site_targets(site, focus_refs)` in
  `platform/api/clue_api/design_turn_targets.py` (B5 builds the envelope from the latter).
- Wire kind (Task 10): `wire_kind(doc_kind) -> "web" | "ad" | "site"` in
  `platform/api/clue_api/design_leg_wiring.py`.
- Agent-section link convention (Task 6), for Lane B's writing-a-section skill: a section's link
  props are named `...Href` (case-insensitive suffix); a link prop whose name contains `cta` or
  `button` is a primary destination.

**Lane A consumes:** Lane C's C1 (the frontend accepts `"site"`) before Task 10's commit is
merged into a shared branch (Contract 8); Lane B's B2 and B6 loaders (gap 1).

---

## File Structure

```
apps/frontend/packages/site-kit/
  src/check-section.ts        MODIFY  D2 banned names, raw <a> refusal, brand-class allow-list; CLI never imports
  src/validate.ts             MODIFY  /asset-store paths, SiteImages, schema-only agent sections, agent links
  src/brand.ts                MODIFY  clone images by /asset-store digest
  src/theme.ts                MODIFY  extra + band surfaces, secondary button, tailwindThemeCss
  src/sections.tsx            MODIFY  surfaceClass(), Button variant
  src/agent-kit.tsx           MODIFY  Image fit contain + logo default, Button variant, Link, Shell surfaces
  src/shell.tsx               MODIFY  logoFiles()
  src/config.tsx              MODIFY  makeKit(href, brand)
  src/catalog.ts              MODIFY  brand.md: 12 roles, surfaces, buttons, links, rules, logos
  src/render-core.tsx         CREATE  renderSitePages(), sectionPropsSchema() (Node-testable)
  src/render-browser.tsx      CREATE  the browser entry inside the hardened page
  src/index.ts                MODIFY  exports
  bin/validate-site.ts        MODIFY  stored props JSON Schema mode only
  bin/build-catalog.ts        CREATE  catalog CLI
  bin/build-bundles.mjs       CREATE  esbuild -> dist/{validate-site.mjs,build-catalog.mjs,render-browser.js}
  package.json, .gitignore, README.md   MODIFY
  test/fixtures/*.json        MODIFY  /asset-store paths
  test/fixtures/hostile/*.tsx CREATE  the spike's six hostile sections
  test/{check-section,validate-site,asset-paths,bundles,theme,agent-kit,catalog,multipage,render-core}.test.ts(x)

subsystems/clue-design/apps/api/lumen_api/
  hardened_browser.py         CREATE  launch args, stripped env, sealed context, request blocking
  site_render.py              CREATE  render_site / read_section_schema / capture_site_screenshot
  site_sanitize.py            CREATE  sanitize_site_html (strip, never refuse)
  site_doc_inputs.py          CREATE  the brand + section loader seams
  site_doc_validate.py        CREATE  shape, custody and site-kit validator checks
  site_publish.py             CREATE  publish package, thumbnail, ZIP, PDF builders
  toolbelt/site_documents.py  CREATE  design_write_site / design_undo_site / design_redo_site
  toolbelt/publishes.py       MODIFY  _commit_publish_package (extracted), design_publish_site
  toolbelt/documents.py       MODIFY  design_document_not_site
  toolbelt/base.py, wiring.py, factory.py   MODIFY  host thunks, registration
  design_store.py             MODIFY  HybridRepository.update_site_document
  web_export.py               MODIFY  compile_tailwind_css (extracted)
  web_pdf.py                  MODIFY  render_pages_pdf(hardened=)
  main.py, models.py          MODIFY  routes, gates, app.state seams
subsystems/clue-design/scripts/web_static_css.mjs   (reused as is)
subsystems/design/clue_design/publishes.py          MODIFY  site CSP, manifest_delivery()
platform/page_origin/clue_page_origin/{reads,routes}.py  MODIFY  per-publish CSP
platform/api/clue_api/{design_leg_wiring,design_turn_targets,artifact_read_tools,project_library,account_research_turn_wiring}.py  MODIFY
platform/api/clue_api/chat/{composer_context,router,schemas}.py, frontend_read/contract_v1.py   MODIFY
platform/api/clue_api/agent_registry_wiring.py      MODIFY  authority for 4 tools
libs/clue-spine/clue_spine/hostnames.py             MODIFY  reservation, move_system_hostnames
libs/clue-config/clue_config/settings.py            MODIFY  pages_legacy_system_suffixes
platform/api/clue_api/frontend_read/settings_pages.py   MODIFY
scripts/move_system_hostnames.py                    CREATE
infra/cloudflare/pages-edge/{routing.js,worker.js,wrangler.toml,routing.test.js,README.md}  MODIFY
deploy/check_prod_env.py, docker/backend/{Dockerfile,smoke.sh}   MODIFY
docs/specs/pages-hosting-runbook.md, docs/deploy/runbook.md, DEV_STACK.md   MODIFY
.env.example, subsystems/clue-design/.env.example   MODIFY
tests: see each task
```

## Before you start

- [ ] **Branch.** `git switch -c puck/wave2-lane-a puck/integration-wave1` (skip if the orchestrator
  gave you a branch). Never commit to `main`.
- [ ] **Baseline.** Run, and record the result in your notes:
  - `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts` → `pass 26`, `fail 0`.
  - `DESIGN_PYTEST test_write_path_governance.py` → **2 failed, 5 passed** at `0b5f61fe2`. Both
    failures pre-date this lane: `test_design_tool_names_are_stable` (the registered
    `design_enrich_assets` is missing from the pinned set) and
    `test_converted_domain_mutations_are_only_called_from_the_toolbelt`
    (`lumen_api/asset_enrichment.py:51` calls `create_asset_record` directly). Task 12 adds the one
    missing pin; the second failure is not Lane A's and stays.
  - `PLATFORM_PYTEST tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py tests/api/test_agent_registry_wiring.py -k "not out_of_order"` → `55 passed`.
- [ ] **Tooling present.** `apps/frontend/node_modules` (run `npm ci` in `apps/frontend` if absent),
  `subsystems/clue-design/apps/editor/node_modules/@tailwindcss/node` (run `npm ci` in
  `subsystems/clue-design/apps/editor` if absent) and Playwright Chromium
  (`.venv/bin/python -m playwright install chromium`).
- [ ] **Design stack down** for every database suite (`scripts/dev_stack.sh status`; stop it if up).

---
## A0 — site-kit catch-up

### Task 1: The D2 banned names in the section check, and a check CLI that never imports the section

The spike's D2 lint (`trials/puck-spike/scripts/check-section.ts:31-74`, commit `412193a51`) never
reached site-kit, and site-kit's CLI still imports the section to read its schema
(`apps/frontend/packages/site-kit/src/check-section.ts:89-99`), which D2 forbids.

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/check-section.ts` (whole file below)
- Create: `apps/frontend/packages/site-kit/test/fixtures/hostile/{NetworkCall,CookieRead,ParentFrame,InjectedScript,InfiniteLoop,HugeOutput}.tsx` (copied from the spike)
- Modify: `apps/frontend/packages/site-kit/test/check-section.test.ts`
- Modify: `apps/frontend/packages/site-kit/README.md` (the CLI line)

**Interfaces:**
- Consumes: nothing new.
- Produces: `lint(source: string): string[]` now also returns the banned-name refusals;
  `typeCheck(file: string): string[]` unchanged; the CLI prints `{"ok": boolean, "errors": string[]}`
  (no `props` key any more — the props schema comes from `read_section_schema`, Task 17).

- [ ] **Step 1: Show the founder the refusal wording.** These six lines are agent-facing. They are
  the spike's own text (`trials/puck-spike/scripts/check-section.ts:35-62`), ported verbatim; ask
  for a yes before writing them:
  - `"<name>" reaches the page outside the section; a section renders its props and nothing else` (window, document, globalThis)
  - `"<name>" is a network call; a section renders its props and nothing else` (fetch, XMLHttpRequest, WebSocket)
  - `"<name>" runs code the check never saw; a section renders its props and nothing else` (eval, Function), and `"import(" loads code the check never saw; a section renders its props and nothing else`
  - `"dangerouslySetInnerHTML" writes raw HTML; a section renders its props and nothing else`
  - `"localStorage" reads the visitor's storage; …`, `"cookie" reads the visitor's cookies; …`, `"setTimeout" is a timer; a section renders once from its props; …` (and setInterval)
  - `"<onX>" is an event handler; a section is static`

- [ ] **Step 2: Copy the hostile fixtures.**

```bash
mkdir -p apps/frontend/packages/site-kit/test/fixtures/hostile
cp trials/puck-spike/scripts/hostile/*.tsx apps/frontend/packages/site-kit/test/fixtures/hostile/
ls apps/frontend/packages/site-kit/test/fixtures/hostile
```
Expected: `CookieRead.tsx HugeOutput.tsx InfiniteLoop.tsx InjectedScript.tsx NetworkCall.tsx ParentFrame.tsx`.

- [ ] **Step 3: Write the failing tests.** Append to `test/check-section.test.ts` (it already
  imports `assert`, `fs`, `path`, `test`, `fileURLToPath`, `lint`, `typeCheck` and defines
  `EXAMPLE`); add `import { execFileSync } from "node:child_process";` to its imports.

```ts
const HOSTILE = (name: string) =>
  fs.readFileSync(new URL(`./fixtures/hostile/${name}.tsx`, import.meta.url), "utf-8");

test("the D2 banned names refuse the four hostile sections that name them", () => {
  const cases: [string, RegExp][] = [
    ["NetworkCall", /^"fetch" is a network call/],
    ["CookieRead", /^"document" reaches the page outside the section/],
    ["ParentFrame", /^"window" reaches the page outside the section/],
    ["InjectedScript", /^"dangerouslySetInnerHTML" writes raw HTML/],
  ];
  for (const [name, why] of cases) {
    const errors = lint(HOSTILE(name));
    assert.ok(errors.some((e) => why.test(e)), `${name}: ${errors.join("; ")}`);
  }
});

test("resource abuse names nothing banned: the loop and the huge page pass (the render page bounds them)", () => {
  assert.deepEqual(lint(HOSTILE("InfiniteLoop")), []);
  assert.deepEqual(lint(HOSTILE("HugeOutput")), []);
});

test("a banned word in a section's text is not a banned name", () => {
  const prose = EXAMPLE.replace("{props.attribution}", "{props.attribution} window document fetch cookie");
  assert.deepEqual(lint(prose), []);
});

test("event handlers and dynamic imports are refused by name", () => {
  const handler = lint(EXAMPLE.replace("<p className", "<p onClick={() => 0} className"));
  assert.ok(handler.includes('"onClick" is an event handler; a section is static'), handler.join("; "));
  const dynamic = lint(`${EXAMPLE}\nexport const later = () => import("./x");\n`);
  assert.ok(dynamic.some((e) => e.startsWith('"import(" loads code the check never saw')), dynamic.join("; "));
});

test("the CLI checks a section without importing it", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const dir = path.join(root, ".section-check", "cli-test");
  fs.mkdirSync(dir, { recursive: true });
  try {
    const file = path.join(dir, "Loud.tsx");
    // A module that throws the moment anything imports it: the CLI must still answer ok.
    fs.writeFileSync(file, `${EXAMPLE}\nthrow new Error("the check imported the section");\n`);
    const out = execFileSync(process.execPath, ["--import", "tsx", "src/check-section.ts", file], { cwd: root });
    assert.deepEqual(JSON.parse(out.toString()), { ok: true, errors: [] });
  } finally {
    fs.rmSync(path.join(root, ".section-check"), { recursive: true, force: true });
  }
});
```

- [ ] **Step 4: Run the tests to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/check-section.test.ts`
Expected: FAIL — the four hostile cases find no banned-name message, the handler/import case fails,
and the CLI case fails with `Error: the check imported the section` (or a `props` key in the output).

- [ ] **Step 5: Replace `src/check-section.ts` with this file.**

```ts
// The check a section written by the agent must pass before it joins its site (E5).
//
// Usage: npx tsx src/check-section.ts <file.tsx>
// Prints {"ok": bool, "errors": [...]} as JSON.
//
// Structure is free; style is the brand's. Refused: colour values, Tailwind's own palette colours,
// Tailwind's default type sizes, families and weights, bracketed custom values for colour, type
// or corners (layout measures such as max-w-[30ch] are fine), inline styles, imports other than
// zod, react types and the kit, and the banned names below (page globals, network, eval, raw
// HTML, storage, timers, event handlers). The file must export `schema` (a zod object) and
// `render`, and must type-check.
//
// D2 (founder, 2026-10-09 and 2026-10-11): this check NEVER imports the section. The props schema,
// and the rules about it (an id and a surface, no className or style), are read inside the design
// API's hardened render page (lumen_api.site_render.read_section_schema), never in a platform
// process.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const ALLOWED_IMPORTS = new Set(["zod", "react", "@/puck/agent-kit"]);
const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const COLOUR_UTILITY = "text|bg|border|fill|stroke|ring|outline|decoration|divide|from|via|to|accent|caret|shadow|placeholder";
const RULES: { pattern: RegExp; why: string }[] = [
  { pattern: new RegExp(`^(${COLOUR_UTILITY})-(${PALETTE})-\\d{2,3}(\\/\\d+)?$`), why: "a Tailwind palette colour; use the brand's text-ink-*, bg-surface-* or border-line-*" },
  { pattern: new RegExp(`^(${COLOUR_UTILITY})-(black|white)(\\/\\d+)?$`), why: "a fixed colour; use the brand's text-ink-*, bg-surface-* or border-line-*" },
  { pattern: /^text-(xs|sm|base|lg|xl|[2-9]xl)$/, why: "a Tailwind type size; use a brand type role (text-title, text-body…)" },
  { pattern: /^font-(sans|serif|mono|thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/, why: "a Tailwind font or weight; use a brand type role (font-title, font-body…)" },
  { pattern: /^(text|bg|border|fill|stroke|ring|outline|decoration|font|leading|tracking|rounded|shadow|from|via|to)-\[/, why: "a custom colour, type or corner value; use the brand's tokens" },
];

// D2 spike (Task 4): names a section may not use, wherever they appear in its code (a variable, a
// property such as document.cookie, an object key). Read from the syntax tree, so the words in a
// section's text or strings never count. A guardrail against the obvious, not a sandbox: the
// hardened render page is the boundary (trials/puck-spike/RUNTIME-SECTIONS.md).
const BANNED: Record<string, string> = {
  window: "reaches the page outside the section",
  document: "reaches the page outside the section",
  globalThis: "reaches the page outside the section",
  fetch: "is a network call",
  XMLHttpRequest: "is a network call",
  WebSocket: "is a network call",
  eval: "runs code the check never saw",
  Function: "runs code the check never saw",
  dangerouslySetInnerHTML: "writes raw HTML",
  localStorage: "reads the visitor's storage",
  cookie: "reads the visitor's cookies",
  setTimeout: "is a timer; a section renders once from its props",
  setInterval: "is a timer; a section renders once from its props",
};

function bannedNames(source: string): string[] {
  const errors: string[] = [];
  const seen = new Set<string>();
  const add = (message: string) => {
    if (!seen.has(message)) {
      seen.add(message);
      errors.push(message);
    }
  };
  const file = ts.createSourceFile("section.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const visit = (node: ts.Node) => {
    if (ts.isIdentifier(node) && Object.hasOwn(BANNED, node.text)) add(`"${node.text}" ${BANNED[node.text]}; a section renders its props and nothing else`);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) add(`"import(" loads code the check never saw; a section renders its props and nothing else`);
    // An event handler, as a JSX prop or as a key of an object that might be spread into one.
    if (ts.isJsxAttribute(node) || ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node) || ts.isMethodDeclaration(node)) {
      const name = node.name.getText(file).replace(/^["'`]|["'`]$/g, "");
      if (/^on[A-Z]/.test(name)) add(`"${name}" is an event handler; a section is static`);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return errors;
}

function classTokens(source: string): string[] {
  const strings = [...source.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].map((m) => m[1] ?? m[2] ?? m[3] ?? "");
  return strings.flatMap((s) => s.split(/\s+/)).filter(Boolean).map((t) => t.split(":").pop() ?? t);
}

export function lint(source: string): string[] {
  const errors: string[] = [];
  for (const m of source.matchAll(/import\s+(?:type\s+)?[^"']*from\s+["']([^"']+)["']/g)) {
    if (!ALLOWED_IMPORTS.has(m[1])) errors.push(`import "${m[1]}" is not allowed; a section imports only zod, react types and @/puck/agent-kit`);
  }
  const withoutHrefs = source.replace(/href=\{?["'`][^"'`]*["'`]\}?/g, "");
  for (const m of withoutHrefs.matchAll(/#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g)) errors.push(`colour value ${m[0]}; use the brand's colour tokens`);
  for (const m of source.matchAll(/\b(rgba?|hsla?|oklch|oklab|lab|lch)\(/g)) errors.push(`colour function ${m[0]}…); use the brand's colour tokens`);
  if (/\bstyle\s*=/.test(source) || /\bstyle\s*:/.test(source)) errors.push("inline style; style only with the brand's classes");
  const seen = new Set<string>();
  for (const token of classTokens(source)) {
    for (const rule of RULES) {
      if (rule.pattern.test(token) && !seen.has(token)) {
        seen.add(token);
        errors.push(`class "${token}" is ${rule.why}`);
      }
    }
  }
  errors.push(...bannedNames(source));
  if (!/export\s+const\s+schema\b/.test(source)) errors.push("the file must export `schema` (a zod object of the section's props)");
  if (!/export\s+function\s+render\b/.test(source)) errors.push("the file must export `function render(props, kit)`");
  return errors;
}

export function typeCheck(file: string): string[] {
  const dir = path.dirname(file);
  // The package's tsconfig maps the kit's import (@/puck/agent-kit) to src/agent-kit.tsx. The file
  // must sit where zod and react resolve (inside apps/frontend), as in the spike.
  const root = fileURLToPath(new URL("..", import.meta.url));
  const tsc = createRequire(import.meta.url).resolve("typescript/bin/tsc");
  fs.writeFileSync(
    path.join(dir, "tsconfig.json"),
    JSON.stringify({
      extends: path.relative(dir, path.join(root, "tsconfig.json")),
      compilerOptions: { incremental: false, noEmit: true },
      include: [path.basename(file)],
      // Inheriting an exclude that covers the file's directory would silently type-check nothing.
      exclude: [],
    }),
  );
  try {
    execFileSync(process.execPath, [tsc, "-p", path.join(dir, "tsconfig.json")], { cwd: root, stdio: "pipe" });
    return [];
  } catch (error) {
    const out = String((error as { stdout?: Buffer }).stdout ?? error);
    return out.split("\n").filter((l) => l.includes("error TS")).slice(0, 8).map((l) => `type error: ${l.replace(/^.*?\(/, "(")}`);
  }
}

function main() {
  const file = path.resolve(process.argv[2] ?? "");
  const source = fs.readFileSync(file, "utf-8");
  const errors = lint(source);
  if (!errors.length) errors.push(...typeCheck(file));
  console.log(JSON.stringify({ ok: errors.length === 0, errors }));
}

if (process.argv[1]?.endsWith("check-section.ts")) main();
```

- [ ] **Step 6: Update the README's CLI line.** In `apps/frontend/packages/site-kit/README.md`,
  replace the line beginning `- \`tsx src/check-section.ts <file.tsx>\`` with:

```markdown
- `tsx src/check-section.ts <file.tsx>`: prints `{"ok": bool, "errors": [...]}`. It never imports
  the section (D2); the props schema is read inside the design API's hardened render page
  (`lumen_api.site_render.read_section_schema`).
```

- [ ] **Step 7: Run the package's tests and type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: every test passes (`fail 0`); `tsc --noEmit` prints nothing.

- [ ] **Step 8: Commit.**

```bash
git add apps/frontend/packages/site-kit/src/check-section.ts apps/frontend/packages/site-kit/test/check-section.test.ts apps/frontend/packages/site-kit/test/fixtures/hostile apps/frontend/packages/site-kit/README.md
git commit -m "site-kit: port the D2 banned-name lint; the section-check CLI never imports the section"
```

### Task 2: Production asset paths, `/asset-store/<sha256>` everywhere

Contract 1: every image, logo, font and generated picture is `/asset-store/<sha256>`. Today the
fixtures and the validator speak the spike's `/brands/…`, `/generated/…` and `/accounts/…`
(`src/validate.ts:89-91,166-182`), and `cloneImages` only finds `/brands/…<ext>` sources
(`src/brand.ts:28-45`).

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/brand.ts:27-45`
- Modify: `apps/frontend/packages/site-kit/src/validate.ts`
- Modify: `apps/frontend/packages/site-kit/test/fixtures/{assets,fonts,clones,garner-syracuse,conduit-atrium}.json`
- Create: `apps/frontend/packages/site-kit/test/asset-paths.test.ts`
- Modify: `apps/frontend/packages/site-kit/README.md` (the asset-path note)

**Interfaces:**
- Consumes: `validateSite` from Task 1's package state.
- Produces:
  - `export type SiteImages = { siteImages: string[]; accountLogos: string[] }`;
  - `export type AgentSectionSchemas = Record<string, { schema: { safeParse: (value: unknown) => { success: boolean } } }>`;
  - `validateSite(files: SiteFiles, brand: BrandData, agentSections: AgentSectionSchemas, images?: SiteImages): { valid: boolean; errors: string[] }`
    (an `AgentSectionModule` record still satisfies `AgentSectionSchemas`).

- [ ] **Step 1: Rewrite the fixtures to production paths.**

```bash
cd apps/frontend/packages/site-kit/test/fixtures
sed -E -i '' 's#/brands/[a-z0-9-]+/(assets|fonts)/([0-9a-f]{64})\.[a-z0-9]+#/asset-store/\2#g' assets.json fonts.json clones.json garner-syracuse.json conduit-atrium.json
grep -c '/brands/' assets.json fonts.json clones.json garner-syracuse.json conduit-atrium.json
cd -
```
Expected: every count is `0`. (On Linux use `sed -E -i` without the `''`.)

- [ ] **Step 2: Write the failing tests** in `test/asset-paths.test.ts`:

```ts
// Contract 1 (2026-10-11): every image, logo, font and generated picture a site names is
// /asset-store/<sha256>, a blob of the workspace. The spike's /brands, /generated and /accounts
// paths are gone; the validator takes this site's generated images and the account's logos as data.
import assert from "node:assert/strict";
import { test } from "node:test";
import { validateSite } from "../src/validate";
import { garner, site as readSite } from "./fixtures/garner";

const site = readSite("garner-syracuse");
const brand = garner();
const GENERATED = `/asset-store/${"a".repeat(64)}`;
const LOGO = `/asset-store/${"b".repeat(64)}`;
const STORE = /^\/asset-store\/[0-9a-f]{64}$/;

function withImage(image: string) {
  const analysis = structuredClone(site.pages["/analysis"]);
  analysis.content[0].props.image = image; // FeatureSplit "what"
  return { "/": site.pages["/"], "/analysis": analysis };
}

test("every brand asset, font and clone image is an /asset-store/<sha256> path", () => {
  for (const asset of Object.values(brand.assets)) assert.match(asset.file, STORE, asset.file);
  for (const face of brand.fonts) assert.match(face.file, STORE, face.file);
  assert.ok(Object.values(brand.assets).some((asset) => asset.kind === "captured_image"), "clone images are offered");
});

test("an image generated for this site is accepted; an image that is not is refused", () => {
  const files = { pages: withImage(GENERATED), shell: site.shell };
  assert.equal(validateSite(files, brand, {}, { siteImages: [GENERATED], accountLogos: [] }).valid, true);
  const refused = validateSite(files, brand, {});
  assert.ok(
    refused.errors.includes(`pages/analysis.content.0(what).image: image "${GENERATED}" is not in the brand's assets; pick a file from brand/brand.md`),
    refused.errors.join("\n"),
  );
});

test("the spike's old paths are refused", () => {
  for (const legacy of ["/brands/garner/assets/x.png", "/generated/garner-syracuse/x.png", "/accounts/garner-syracuse/logo.png"]) {
    assert.equal(validateSite({ pages: withImage(legacy), shell: site.shell }, brand, {}).valid, false, legacy);
  }
});

test("the header's account logo must be one of the account's logos", () => {
  const shell = structuredClone(site.shell);
  shell.header.accountLogo = LOGO;
  const pages = { "/": site.pages["/"], "/analysis": site.pages["/analysis"] };
  assert.equal(validateSite({ pages, shell }, brand, {}, { siteImages: [], accountLogos: [LOGO] }).valid, true);
  const refused = validateSite({ pages, shell }, brand, {});
  assert.ok(
    refused.errors.includes(`shell.header.accountLogo: "${LOGO}" is not this account's logo; use a file from "The account's logo" in brand/brand.md, or leave it empty`),
    refused.errors.join("\n"),
  );
});

test("an /asset-store image inside an agent section's props is checked like any other", () => {
  const home = structuredClone(site.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "page", photo: GENERATED } });
  const sections = { QuoteBand: { schema: { safeParse: () => ({ success: true }) } } };
  const result = validateSite({ pages: { "/": home, "/analysis": site.pages["/analysis"] }, shell: site.shell }, brand, sections);
  assert.ok(result.errors.some((e) => e.startsWith(`page.content.5(quote).photo: image "${GENERATED}"`)), result.errors.join("\n"));
});
```

- [ ] **Step 3: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/asset-paths.test.ts`
Expected: FAIL — no `captured_image` asset (cloneImages finds nothing), the generated image is
refused even with `siteImages`, and the account-logo message differs.

- [ ] **Step 4: Find clone images by digest** in `src/brand.ts`: replace the body of `cloneImages`
  (lines 28-45) with:

```ts
/** Photos and graphics captured with the seller's own sections, offered beside the kit's assets.
 * Clone HTML names its bytes as /asset-store/<sha256> (the fragment sanitizer rewrites them). */
function cloneImages(clones: Clone[]): Record<string, BrandAsset> {
  const found: Record<string, BrandAsset> = {};
  for (const clone of clones) {
    for (const match of clone.html.matchAll(/<img[^>]*?src="(\/asset-store\/[0-9a-f]{64})"[^>]*?(?:alt="([^"]*)")?/g)) {
      const file = match[1];
      if (found[file]) continue;
      found[file] = {
        kind: "captured_image",
        label: clone.label,
        description: match[2] || `From the seller's section "${clone.label}"`,
        mime: null,
        file,
        logo: null,
      };
    }
  }
  return found;
}
```

- [ ] **Step 5: Change the validator's image rules** in `src/validate.ts`:
  1. Replace the import of `AgentSectionModule` (line 14) with nothing, and add these exports right
     after the `SiteFiles` type (line 24):

```ts
/** A site's agent-written sections, as the validator needs them: only the schema (E5). The design
 * API builds each one from the section's STORED props JSON Schema (bin/validate-site.ts). */
export type AgentSectionSchemas = Record<string, { schema: { safeParse: (value: unknown) => { success: boolean } } }>;
/** Images a site may use besides the brand's assets: the ones generated for it, and the account's
 * own logos (the header's accountLogo only). Every one is /asset-store/<sha256> (Contract 1). */
export type SiteImages = { siteImages: string[]; accountLogos: string[] };
const NO_IMAGES: SiteImages = { siteImages: [], accountLogos: [] };
/** A string that names stored bytes: production's /asset-store/<sha256>, or one of the spike's
 * old prefixes, which are never in the allowed set and so are refused. */
const IMAGE_PATH = /^\/(asset-store|brands|generated|accounts)\//;
```

  2. Change the signature to:

```ts
export function validateSite(
  files: SiteFiles,
  brand: BrandData,
  agentSections: AgentSectionSchemas,
  images: SiteImages = NO_IMAGES,
): { valid: boolean; errors: string[] } {
```

  3. Replace the `assetFiles` / `imageAllowed` lines (89-91) with:

```ts
  const allowedImages = new Set([...Object.values(brand.assets).map((asset) => asset.file), ...images.siteImages]);
  const accountLogos = new Set(images.accountLogos);
  const imageAllowed = (value: unknown) =>
    value === "" || value === undefined || (typeof value === "string" && allowedImages.has(value));
  // One wording for every refused image (the spike's R3 text, founder-approved 2026-10-09).
  const imageError = (where: string, value: unknown) =>
    `${where}: image "${String(value)}" is not in the brand's assets; pick a file from brand/brand.md`;
```

  4. Use `imageError` at all three image checks:
     - the clone image slot (line 139): `errors.push(imageError(\`${at}.slots.${key}\`, value));`
     - FeatureSplit (lines 158-160): `errors.push(imageError(\`${at}.image\`, item.props.image));`
       (this adds the word "image" the spike's R3 version has; the old line lacked it);
     - the agent-section walk (lines 166-175): change its condition
       `typeof value === "string" && value.startsWith("/brands/") && !imageAllowed(value)` to
       `typeof value === "string" && IMAGE_PATH.test(value) && !imageAllowed(value)` and its push
       to `errors.push(imageError(where, value));`.

  5. Replace the account-logo check (lines 179-182) with:

```ts
  const accountLogo = shell.header?.accountLogo;
  if (accountLogo && !imageAllowed(accountLogo) && !accountLogos.has(String(accountLogo))) {
    errors.push(`shell.header.accountLogo: "${String(accountLogo)}" is not this account's logo; use a file from "The account's logo" in brand/brand.md, or leave it empty`);
  }
```

- [ ] **Step 6: Update the README note.** Replace the line `- Asset paths keep the trial's
  \`/brands/<slug>/...\` prefix for now.` with:

```markdown
- Every image, logo and font a site names is `/asset-store/<sha256>`, a blob of the workspace
  (Contract 1). `validateSite`'s fourth argument names this site's generated images and the
  account's logos; anything else must be one of the brand's assets.
```

- [ ] **Step 7: Run every site-kit test and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass, including the existing `validate-site`, `multipage`, `contracts` and `catalog`
tests (they read the rewritten fixtures); no type errors.

- [ ] **Step 8: Commit.**

```bash
git add apps/frontend/packages/site-kit/src/brand.ts apps/frontend/packages/site-kit/src/validate.ts apps/frontend/packages/site-kit/test apps/frontend/packages/site-kit/README.md
git commit -m "site-kit: /asset-store/<sha256> for every asset; the validator takes generated images and account logos as data"
```

### Task 3: The validator CLI checks agent sections against stored JSON Schemas; a catalog CLI; one-file bundles

`bin/validate-site.ts` imports each agent section module for its Zod schema
(`bin/validate-site.ts:19-22`), which D2 forbids in production. Zod 4.4.3 rebuilds a schema from
JSON Schema (`z.fromJSONSchema`), so the CLI takes the stored props schema instead. The design API
host has no `apps/frontend/node_modules`, so both CLIs ship as single files built by esbuild.

**Files:**
- Modify: `apps/frontend/packages/site-kit/bin/validate-site.ts` (whole file below)
- Create: `apps/frontend/packages/site-kit/bin/build-catalog.ts`
- Create: `apps/frontend/packages/site-kit/bin/build-bundles.mjs`
- Modify: `apps/frontend/packages/site-kit/package.json` (the `build` script)
- Modify: `apps/frontend/packages/site-kit/.gitignore` (add `dist/`)
- Modify: `apps/frontend/packages/site-kit/test/validate-site.test.ts` (the CLI test)
- Create: `apps/frontend/packages/site-kit/test/bundles.test.ts`
- Modify: `apps/frontend/packages/site-kit/README.md` (CLIs)

**Interfaces:**
- Consumes: `validateSite(files, brand, agentSections, images)`, `AgentSectionSchemas`, `SiteImages`
  (Task 2); `buildCatalog(brand, seller)`.
- Produces:
  - `node dist/validate-site.mjs` reading stdin
    `{"files": {"pages": {route: page}, "shell": shell|null}, "brand": BrandData, "agentSectionSchemas": {"<Name>": <JSON Schema>}, "images": {"siteImages": [...], "accountLogos": [...]}}`
    and printing `{"valid": bool, "errors": [string]}`;
  - `node dist/build-catalog.mjs` reading `{"brand": BrandData, "seller": string}` and printing
    `{"files": {relative path: markdown}}`;
  - `npm run build -w @clue/site-kit` (= `node bin/build-bundles.mjs`) writing both into `dist/`.

- [ ] **Step 1: Write the failing tests.** In `test/validate-site.test.ts`, replace the whole test
  `"the CLI validates a site with an agent section imported from its module path"` with:

```ts
test("the CLI checks an agent section against its stored props JSON Schema, never importing it", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const run = (page: unknown) =>
    JSON.parse(
      execFileSync(process.execPath, ["--import", "tsx", "bin/validate-site.ts"], {
        cwd: root,
        input: JSON.stringify({
          files: { pages: { ...pages, "/": page }, shell: site.shell },
          brand,
          agentSectionSchemas: { QuoteBand: z.toJSONSchema(quoteSchema) },
        }),
      }).toString(),
    );
  const withQuote = (surface: string) => {
    const page = structuredClone(pages["/"]);
    page.content.push({ type: "QuoteBand", props: { id: "quote", surface, quote: "Fewer surprises.", attribution: "A buyer" } });
    return page;
  };
  assert.deepEqual(run(withQuote("page")), { valid: true, errors: [] });
  const refused = run(withQuote("green"));
  assert.equal(refused.valid, false);
  assert.ok(refused.errors.some((e: string) => /^page\.content\.\d+\(quote\)\.surface/.test(e)), refused.errors.join("\n"));
});

test("a stored schema that cannot be read is named, not ignored", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const out = JSON.parse(
    execFileSync(process.execPath, ["--import", "tsx", "bin/validate-site.ts"], {
      cwd: root,
      input: JSON.stringify({ files: { pages, shell: site.shell }, brand, agentSectionSchemas: { Broken: { type: "no-such-type" } } }),
    }).toString(),
  );
  assert.equal(out.valid, false);
  assert.ok(out.errors.some((e: string) => e.startsWith("agent_sections.Broken: its stored props schema could not be read")), out.errors.join("\n"));
});
```
  and add to the file's imports:

```ts
import { z } from "zod";
import { schema as quoteSchema } from "./fixtures/section-example";
```

  Then create `test/bundles.test.ts`:

```ts
// The CLIs the design API and the site harness run ship as single files: they must work with
// plain node from a directory that has no node_modules at all.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { garner, site as readSite } from "./fixtures/garner";

const root = fileURLToPath(new URL("..", import.meta.url));
const site = readSite("garner-syracuse");
const brand = garner();

test("the build writes the validator and the catalog as single files that run with plain node", () => {
  execFileSync(process.execPath, ["bin/build-bundles.mjs"], { cwd: root });
  const validator = path.join(root, "dist", "validate-site.mjs");
  const catalog = path.join(root, "dist", "build-catalog.mjs");
  assert.ok(fs.existsSync(validator) && fs.existsSync(catalog));
  const away = fs.mkdtempSync(path.join(os.tmpdir(), "site-kit-bundle-"));
  try {
    const checked = JSON.parse(
      execFileSync(process.execPath, [validator], { cwd: away, input: JSON.stringify({ files: { pages: site.pages, shell: site.shell }, brand }) }).toString(),
    );
    assert.deepEqual(checked, { valid: true, errors: [] });
    const built = JSON.parse(execFileSync(process.execPath, [catalog], { cwd: away, input: JSON.stringify({ brand, seller: "Garner Health" }) }).toString());
    assert.ok(built.files["brand/brand.md"].startsWith("# Brand: Garner Health"));
    assert.ok(Object.keys(built.files).includes("catalog/index.md"));
  } finally {
    fs.rmSync(away, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/validate-site.test.ts test/bundles.test.ts`
Expected: FAIL — the CLI ignores `agentSectionSchemas` (`unknown component "QuoteBand"`), and
`bin/build-bundles.mjs` does not exist.

- [ ] **Step 3: Replace `bin/validate-site.ts`.**

```ts
// The validator as a CLI, for the design API and the site agent's harness.
//
// Usage: node dist/validate-site.mjs < input.json   (in development: npx tsx bin/validate-site.ts)
// Reads {"files": {"pages": {route: page}, "shell": shell | null}, "brand": BrandData,
//        "agentSectionSchemas": {"<Name>": <the section's STORED props JSON Schema>},
//        "images": {"siteImages": [...], "accountLogos": [...]}} from stdin.
// Each agent section is checked against its stored JSON Schema, rebuilt with zod's fromJSONSchema.
// This CLI never imports a section's module: agent code runs only inside the design API's hardened
// render page (D2). Prints {"valid": bool, "errors": ["where: message", ...]} as JSON.
import { z } from "zod";
import type { BrandData } from "../src/brand";
import { validateSite, type AgentSectionSchemas, type SiteFiles, type SiteImages } from "../src/validate";

type Input = {
  files: SiteFiles;
  brand: BrandData;
  agentSectionSchemas?: Record<string, unknown>;
  images?: Partial<SiteImages>;
};

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw) as Input;

const agentSections: AgentSectionSchemas = {};
const schemaErrors: string[] = [];
for (const [name, jsonSchema] of Object.entries(input.agentSectionSchemas ?? {})) {
  try {
    agentSections[name] = { schema: z.fromJSONSchema(jsonSchema as Parameters<typeof z.fromJSONSchema>[0]) };
  } catch (error) {
    schemaErrors.push(`agent_sections.${name}: its stored props schema could not be read (${(error as Error).message})`);
  }
}

const result = validateSite(input.files, input.brand, agentSections, {
  siteImages: input.images?.siteImages ?? [],
  accountLogos: input.images?.accountLogos ?? [],
});
const errors = [...schemaErrors, ...result.errors];
console.log(JSON.stringify({ valid: errors.length === 0, errors }));
```

- [ ] **Step 4: Create `bin/build-catalog.ts`.**

```ts
// The catalog as a CLI, for the site agent's harness.
//
// Usage: node dist/build-catalog.mjs < input.json   (in development: npx tsx bin/build-catalog.ts)
// Reads {"brand": BrandData, "seller": "<the seller's name>"} from stdin and prints
// {"files": {"<relative path>": "<markdown>"}}: catalog/index.md, catalog/clones/<id>.md,
// catalog/sections.md and brand/brand.md. The caller writes them where the agent reads them.
import type { BrandData } from "../src/brand";
import { buildCatalog } from "../src/catalog";

type Input = { brand: BrandData; seller: string };

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw) as Input;
console.log(JSON.stringify({ files: buildCatalog(input.brand, input.seller) }));
```

- [ ] **Step 5: Create `bin/build-bundles.mjs`.**

```js
// Builds the site kit's runnable files into dist/, each one file with its dependencies inside,
// so the design API and the fleet workers run them with plain `node` (their image has no
// apps/frontend/node_modules):
//   dist/validate-site.mjs   the validator CLI (bin/validate-site.ts)
//   dist/build-catalog.mjs   the catalog CLI (bin/build-catalog.ts)
// Usage: node bin/build-bundles.mjs   (npm run build -w @clue/site-kit)
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const banner = { js: "// Built by apps/frontend/packages/site-kit/bin/build-bundles.mjs. Do not edit." };

await Promise.all(
  ["validate-site", "build-catalog"].map((name) =>
    build({
      absWorkingDir: root,
      entryPoints: [`bin/${name}.ts`],
      outfile: path.join(dist, `${name}.mjs`),
      bundle: true,
      platform: "node",
      format: "esm",
      target: "node22",
      legalComments: "none",
      logLevel: "warning",
      banner,
    }),
  ),
);
console.error(`site-kit bundles written to ${dist}`);
```

- [ ] **Step 6: Add the build script and ignore `dist/`.** In `package.json`, change `"scripts"` to:

```json
  "scripts": { "test": "tsx --test test/*.test.ts", "typecheck": "tsc --noEmit", "build": "node bin/build-bundles.mjs" },
```
  and append `dist/` as a new line to `apps/frontend/packages/site-kit/.gitignore`.

- [ ] **Step 7: Update the README's CLI section.** Replace its first CLI bullet (the
  `tsx bin/validate-site.ts < input.json` one) with:

```markdown
- `node dist/validate-site.mjs < input.json` (development: `npx tsx bin/validate-site.ts`): reads
  `{"files": {"pages": {route: page}, "shell": shell | null}, "brand": BrandData, "agentSectionSchemas": {"<Name>": <stored props JSON Schema>}, "images": {"siteImages": [...], "accountLogos": [...]}}`
  and prints `{"valid": bool, "errors": [...]}`. It never imports a section module (D2).
- `node dist/build-catalog.mjs < input.json`: reads `{"brand": BrandData, "seller": "..."}` and
  prints `{"files": {path: markdown}}`.
- `npm run build -w @clue/site-kit` (from `apps/frontend`) writes those files, and the render
  bundle (`dist/render-browser.js`), into `dist/`.
```

- [ ] **Step 8: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass; no type errors.

- [ ] **Step 9: Commit.**

```bash
git add apps/frontend/packages/site-kit/bin apps/frontend/packages/site-kit/package.json apps/frontend/packages/site-kit/.gitignore apps/frontend/packages/site-kit/test/validate-site.test.ts apps/frontend/packages/site-kit/test/bundles.test.ts apps/frontend/packages/site-kit/README.md
git commit -m "site-kit: validator CLI checks agent sections against stored JSON Schemas; catalog CLI; one-file node bundles"
```

## A9 — brand fidelity in site-kit

These four tasks come before the renderer because the render bundle (Task 15) carries the theme,
the kit and `tailwindThemeCss`.

### Task 4: The theme covers the kit's band and extra surfaces, a second button style, and emits its own Tailwind mapping

Today `themeCss` emits a closed list of 20 colour roles and nine surfaces
(`src/theme.ts:11-26,113-117`), so a kit's `surface.band.*` colour never reaches a page, there is
one button style (`:146-179`), and the Tailwind `@theme inline` mapping lives only in the spike app
(`trials/puck-spike/app/globals.css:6-106`). The server CSS compile (Task 17) needs that mapping per
brand.

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/theme.ts` (whole file below)
- Modify: `apps/frontend/packages/site-kit/src/index.ts`
- Create: `apps/frontend/packages/site-kit/test/theme.test.ts`

**Interfaces:**
- Consumes: `BrandData` (`src/brand.ts`).
- Produces:
  - `extraSurfaceRoles(brand: BrandData): string[]` — kit `surface.*` colour roles beyond the nine
    (`surface.band.statement`, …), sorted;
  - `surfaceRoles(brand: BrandData): string[]` — the nine plus the extras;
  - `secondaryButton(brand: BrandData): { fg: string; borderWidth: string; radius: string; source: string }`
    (`source` is the recipe variant, e.g. `"outline.1"`, or `"generic"`);
  - `tailwindThemeCss(brand: BrandData): string` — `@theme inline { … }` mapping every `--brand-*`
    variable to a Tailwind theme variable;
  - `themeCss(brand)` now also emits the extras and `.brand-btn-secondary`.

- [ ] **Step 1: Write the failing tests** in `test/theme.test.ts`:

```ts
// Brand fidelity (Wave 2): the theme carries the kit's band and extra surfaces, a second button
// style read from the kit's own recipes, and the Tailwind mapping the server compile needs.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "../src/brand";
import { extraSurfaceRoles, secondaryButton, tailwindThemeCss, themeCss } from "../src/theme";
import { garner } from "./fixtures/garner";

function withBand(): BrandData {
  const brand = garner();
  const kit = structuredClone(brand.kit) as { tokens: { colors: Record<string, unknown> } };
  kit.tokens.colors["surface.band.statement"] = { value: { modes: {}, default: { kind: "hex", value: "#014036" } } };
  return { ...brand, kit };
}

test("only the kit's surfaces beyond the nine are extra", () => {
  assert.deepEqual(extraSurfaceRoles(garner()), []);
  assert.deepEqual(extraSurfaceRoles(withBand()), ["surface.band.statement"]);
});

test("a band surface gets its colour, its ink and the dark-surface swaps", () => {
  const css = themeCss(withBand());
  assert.match(css, /--brand-surface-band-statement:#014036/);
  assert.match(css, /--brand-on-surface-band-statement:var\(--brand-ink-inverse\)/);
  assert.match(css, /:is\([^)]*\.bg-surface-band-statement[^)]*\) \.brand-btn\{/);
});

test("the tailwind theme maps every brand variable once, the band surfaces included", () => {
  const css = tailwindThemeCss(withBand());
  assert.match(css, /^@theme inline \{\n/);
  for (const line of [
    "--color-surface-brand-subtle: var(--brand-surface-brand-subtle);",
    "--color-on-surface-inverse: var(--brand-on-surface-inverse);",
    "--color-ink-secondary: var(--brand-ink-secondary);",
    "--color-focus: var(--brand-focus);",
    "--font-body-small: var(--brand-font-body-small);",
    "--text-body-small--line-height: var(--brand-text-body-small-lh);",
    "--radius-card: var(--brand-radius-card);",
    "--color-surface-band-statement: var(--brand-surface-band-statement);",
    "--color-on-surface-band-statement: var(--brand-on-surface-band-statement);",
  ]) {
    assert.ok(css.includes(line), line);
  }
  assert.equal(css.split("--color-surface-page:").length, 2, "each variable is mapped once");
});

test("the secondary button is the kit's outline recipe; with none it is a plain outline", () => {
  assert.deepEqual(secondaryButton(garner()), {
    fg: "var(--brand-ink-primary)",
    borderWidth: "1px",
    radius: "var(--brand-radius-full)",
    source: "outline.1",
  });
  const bare = garner();
  const kit = structuredClone(bare.kit) as { brief: { component_recipes: unknown[] } };
  kit.brief.component_recipes = [];
  assert.deepEqual(secondaryButton({ ...bare, kit }), {
    fg: "var(--brand-ink-primary)",
    borderWidth: "1px",
    radius: "var(--brand-button-radius)",
    source: "generic",
  });
  const css = themeCss(garner());
  assert.match(css, /--brand-button-secondary-fg:var\(--brand-ink-primary\)/);
  assert.match(css, /\.brand-btn-secondary\{background:transparent;color:var\(--brand-button-secondary-fg\)/);
  assert.match(css, /\) \.brand-btn-secondary\{background:transparent;color:var\(--brand-button-secondary-light-fg\)\}/);
});
```

- [ ] **Step 2: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/theme.test.ts`
Expected: FAIL — `extraSurfaceRoles`, `secondaryButton` and `tailwindThemeCss` are not exported.

- [ ] **Step 3: Replace `src/theme.ts` with this file.**

```ts
// Brand kit -> one theme stylesheet.
//
// Per-brand values are emitted at runtime as `--brand-*` custom properties on `.brand-root`.
// tailwindThemeCss() maps them once into Tailwind v4 theme variables (`@theme inline`), so every
// section uses fixed class names (`text-headline`, `bg-surface-brand`, `rounded-card`) and the
// brand decides the values. Clones are untouched: they carry their own captured CSS.
import type { BrandData } from "./brand";

type Token = { value: { default: Record<string, unknown> } };

export const COLOR_ROLES = [
  "text.primary", "text.secondary", "text.muted", "text.inverse", "text.brand", "text.accent",
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
  "border.subtle", "border.default", "border.strong", "border.brand", "focus.ring",
] as const;

export const TYPE_ROLES = [
  "display", "headline", "title", "subtitle", "body", "body.small",
  "eyebrow", "cta", "stat", "label", "caption", "legal",
] as const;

export const SURFACES = [
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
] as const;

export const RADIUS_ROLES = ["none", "xs", "sm", "md", "lg", "xl", "card", "button", "badge", "full"] as const;

/** `text.primary` -> `ink-primary`, `surface.brand.subtle` -> `surface-brand-subtle`. */
export function colorVar(role: string): string {
  return role
    .replace(/^text\./, "ink.")
    .replace(/^border\./, "line.")
    .replace(/^focus\.ring$/, "focus")
    .replace(/\./g, "-");
}

export const typeVar = (role: string) => role.replace(/\./g, "-");

function tokens(brand: BrandData, group: string): Record<string, Token> {
  const all = (brand.kit as { tokens: Record<string, Record<string, Token>> }).tokens;
  return all[group] ?? {};
}

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

function isLight(rgb: string): boolean {
  const m = rgb.match(/\d+(\.\d+)?/g);
  if (!m) return false;
  const [r, g, b] = m.slice(0, 3).map(Number);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 200;
}

/** Every surface colour the kit has beyond the nine above: its band surfaces (`surface.band.*`,
 * which ingestion mints for colours that recur across bands) and any other `surface.<x>` token. */
export function extraSurfaceRoles(brand: BrandData): string[] {
  const colors = tokens(brand, "colors");
  const known = new Set<string>(SURFACES);
  return Object.keys(colors)
    .filter((role) => role.startsWith("surface.") && !known.has(role) && typeof colors[role]?.value?.default?.value === "string")
    .sort();
}

/** The nine surfaces plus the kit's extras: each gets a colour, an ink, and the light/dark rules. */
export function surfaceRoles(brand: BrandData): string[] {
  return [...SURFACES, ...extraSurfaceRoles(brand)];
}

/** Text colour role for each surface: the kit's own contrast pair first, else the better of
 * text.primary and text.inverse by contrast ratio. */
function onSurface(brand: BrandData): Record<string, string> {
  const colors = tokens(brand, "colors");
  const hex = (role: string) => colors[role]?.value.default.value as string | undefined;
  const pairs = ((brand.kit as { constraints?: { contrast_pairs?: { background: string; foreground: string }[] } })
    .constraints?.contrast_pairs ?? []);
  const out: Record<string, string> = {};
  for (const surface of surfaceRoles(brand)) {
    const bg = hex(surface);
    if (!bg) continue;
    const pair = pairs.find((p) => p.background === surface);
    if (pair && hex(pair.foreground)) {
      out[surface] = pair.foreground;
      continue;
    }
    const primary = hex("text.primary") ?? "#111111";
    const inverse = hex("text.inverse") ?? "#ffffff";
    out[surface] = contrast(bg, primary) >= contrast(bg, inverse) ? "text.primary" : "text.inverse";
  }
  return out;
}

function fluid(px: number): string {
  // Exact at 1440px wide (the size the kit measured); scales down on smaller screens.
  if (px <= 24) return `${px}px`;
  const min = Math.max(24, Math.round(px * 0.5));
  return `clamp(${min}px, ${(px / 14.4).toFixed(3)}vw, ${px}px)`;
}

function family(name: string, asset: string): string {
  const fallback = asset === "brand" ? "Georgia, serif" : "system-ui, sans-serif";
  return `"${name}", ${fallback}`;
}

type Recipe = { component?: string; variant?: string; text?: string | null; border?: string | null; radius?: string | null };

/** The second button style: the kit's own outline recipe (`brief.component_recipes`; Garner's
 * `outline.1` is a text.primary label, a stroke.width.thin border and radius.full), else a plain
 * outline in the text colour with the primary button's shape. There is no measured second button
 * (ruling 2026-10-11): its values come from the kit's tokens and recipes only. */
export function secondaryButton(brand: BrandData): { fg: string; borderWidth: string; radius: string; source: string } {
  const recipes = (brand.kit as { brief?: { component_recipes?: Recipe[] } }).brief?.component_recipes ?? [];
  const recipe = recipes.find((entry) => entry.component === "button" && /^outline/.test(entry.variant ?? ""));
  const colorRoles = new Set<string>(COLOR_ROLES);
  const fg = recipe?.text && colorRoles.has(recipe.text) ? `var(--brand-${colorVar(recipe.text)})` : "var(--brand-ink-primary)";
  const width = recipe?.border ? tokens(brand, "stroke_widths")[recipe.border]?.value.default.value : undefined;
  const radiusRole = recipe?.radius?.replace(/^radius\./, "");
  const radius =
    radiusRole && (RADIUS_ROLES as readonly string[]).includes(radiusRole) ? `var(--brand-radius-${radiusRole})` : "var(--brand-button-radius)";
  return { fg, borderWidth: typeof width === "number" ? `${width}px` : "1px", radius, source: recipe?.variant ?? "generic" };
}

export function themeCss(brand: BrandData): string {
  const lines: string[] = [];

  for (const face of brand.fonts) {
    lines.push(
      `@font-face{font-family:"${face.family}";src:url("${face.file}");` +
        `font-weight:${face.weight ?? 400};font-style:${face.style};font-display:swap}`,
    );
  }

  const vars: string[] = [];
  const colors = tokens(brand, "colors");
  for (const role of [...COLOR_ROLES, ...extraSurfaceRoles(brand)]) {
    const value = colors[role]?.value.default.value;
    if (typeof value === "string") vars.push(`--brand-${colorVar(role)}:${value}`);
  }

  const type = tokens(brand, "typography");
  for (const role of TYPE_ROLES) {
    const style = type[`type.${role}`]?.value.default as
      | { font_size: number; font_family: string; font_asset: string; font_weight: number;
          line_height: number; letter_spacing: number }
      | undefined;
    if (!style) continue;
    const name = typeVar(role);
    vars.push(
      `--brand-font-${name}:${family(style.font_family, style.font_asset)}`,
      `--brand-text-${name}:${fluid(style.font_size)}`,
      `--brand-text-${name}-lh:${style.line_height}`,
      `--brand-text-${name}-weight:${style.font_weight}`,
      `--brand-text-${name}-tracking:${style.letter_spacing}em`,
    );
  }

  const radii = tokens(brand, "radii");
  for (const role of RADIUS_ROLES) {
    const value = radii[`radius.${role}`]?.value.default.value;
    if (typeof value === "number") vars.push(`--brand-radius-${role}:${value}px`);
  }

  for (const [surface, ink] of Object.entries(onSurface(brand))) {
    vars.push(`--brand-on-${colorVar(surface)}:var(--brand-${colorVar(ink)})`);
  }

  // The primary button, measured from the brand's own hero clone. A white measured button is
  // the "on photo" variant, so the solid button falls back to the brand surface with its pair.
  const button = brand.measured?.primary_button;
  if (button) {
    const light = isLight(button.background);
    vars.push(
      `--brand-button-bg:${light ? "var(--brand-surface-brand)" : button.background}`,
      `--brand-button-fg:${light ? "var(--brand-on-surface-brand)" : button.color}`,
      `--brand-button-light-bg:#ffffff`,
      `--brand-button-light-fg:${light ? button.color : button.background}`,
      `--brand-button-radius:${button.borderRadius}`,
      `--brand-button-px:${button.paddingX}`,
      `--brand-button-height:${button.height}`,
      `--brand-button-font:${button.fontFamily}`,
      `--brand-button-size:${button.fontSize}`,
      `--brand-button-weight:${button.fontWeight}`,
    );
  } else {
    // No solid button in the captured sections: the kit's own (brand colour fill with its pair,
    // a pill, the cta type role).
    const cta = typeVar("cta");
    vars.push(
      "--brand-button-bg:var(--brand-surface-brand)",
      "--brand-button-fg:var(--brand-on-surface-brand,#ffffff)",
      "--brand-button-light-bg:#ffffff",
      "--brand-button-light-fg:var(--brand-surface-brand)",
      "--brand-button-radius:var(--brand-radius-full,9999px)",
      "--brand-button-px:1.25em",
      "--brand-button-height:2.75rem",
      `--brand-button-font:var(--brand-font-${cta},inherit)`,
      `--brand-button-size:var(--brand-text-${cta},1rem)`,
      `--brand-button-weight:var(--brand-text-${cta}-weight,600)`,
    );
  }

  // The second button style (variant "secondary"): the kit's outline recipe, else a plain outline.
  const secondary = secondaryButton(brand);
  vars.push(
    `--brand-button-secondary-fg:${secondary.fg}`,
    `--brand-button-secondary-border-width:${secondary.borderWidth}`,
    `--brand-button-secondary-radius:${secondary.radius}`,
    "--brand-button-secondary-light-fg:var(--brand-ink-inverse,#ffffff)",
  );

  // Heading ink on light surfaces, measured from the clones (kits often record it as unmapped).
  const headingInk = brand.measured?.heading_on_light?.color;
  vars.push(`--brand-heading-ink:${headingInk ?? "var(--brand-ink-primary)"}`);

  lines.push(`.brand-root{${vars.join(";")}}`);
  // Light vs dark is decided per brand from the surface's own colour (Conduit's brand surface is a
  // light cyan, Garner's a dark green): headings take the measured ink on light surfaces, and
  // buttons switch to the light variant on dark ones.
  const lightness = (role: string) => {
    const hex = colors[role]?.value.default.value as string | undefined;
    return hex ? luminance(hex) : 1;
  };
  const cls = (role: string) => `.bg-${colorVar(role)}`;
  const all = surfaceRoles(brand);
  const light = all.filter((s) => lightness(s) > 0.35).map(cls);
  const dark = all.filter((s) => lightness(s) <= 0.35).map(cls);
  // The nearest surface decides: each surface sets the heading colour as an inherited variable, so
  // a dark card inside a light section gets light headings (a descendant rule matched through the
  // nesting and put the brand's dark heading ink on black).
  if (light.length) lines.push(`:is(${light.join(",")}){--brand-heading-color:var(--brand-heading-ink)}`);
  if (dark.length) lines.push(`:is(${dark.join(",")}){--brand-heading-color:currentColor}`);
  lines.push(".brand-heading{color:var(--brand-heading-color,currentColor)}");
  if (dark.length) {
    lines.push(
      `@layer components{:is(${dark.join(",")}) .brand-btn{background:var(--brand-button-light-bg);color:var(--brand-button-light-fg)}}`,
    );
  }
  // Component rules live in the components layer so Tailwind utilities (hidden, sm:inline-flex…)
  // can still override them, as they would any component class.
  lines.push(
    "@layer components{" +
      ".brand-btn{display:inline-flex;align-items:center;gap:.5em;min-height:var(--brand-button-height);" +
      "padding:0 var(--brand-button-px);border-radius:var(--brand-button-radius);" +
      "font-family:var(--brand-button-font);font-size:var(--brand-button-size);" +
      "font-weight:var(--brand-button-weight);background:var(--brand-button-bg);" +
      "color:var(--brand-button-fg);text-decoration:none;white-space:nowrap}" +
      ".brand-btn-light{background:var(--brand-button-light-bg);color:var(--brand-button-light-fg)}" +
      ".brand-btn-secondary{background:transparent;color:var(--brand-button-secondary-fg);" +
      "border:var(--brand-button-secondary-border-width) solid currentColor;" +
      "border-radius:var(--brand-button-secondary-radius)}" +
      "}",
  );
  // After the dark .brand-btn swap, at the same specificity, so a secondary button on a dark
  // surface keeps its outline (light text and border) instead of taking the light fill.
  if (dark.length) {
    lines.push(
      `@layer components{:is(${dark.join(",")}) .brand-btn-secondary{background:transparent;color:var(--brand-button-secondary-light-fg)}}`,
    );
  }
  return lines.join("\n");
}

/** The Tailwind v4 mapping of every `--brand-*` variable this theme emits, as one `@theme inline`
 * block (the spike kept a static copy in its globals.css). The design API's server CSS compile
 * prepends `@import "tailwindcss";` and compiles it over a site's rendered HTML (Wave 2 Task 17);
 * per brand, because the kit's extra surfaces add classes. */
export function tailwindThemeCss(brand: BrandData): string {
  const extras = extraSurfaceRoles(brand);
  const lines: string[] = [];
  for (const surface of [...SURFACES, ...extras]) lines.push(`--color-on-${colorVar(surface)}: var(--brand-on-${colorVar(surface)});`);
  for (const role of [...COLOR_ROLES, ...extras]) lines.push(`--color-${colorVar(role)}: var(--brand-${colorVar(role)});`);
  for (const role of TYPE_ROLES) {
    const name = typeVar(role);
    lines.push(
      `--font-${name}: var(--brand-font-${name});`,
      `--text-${name}: var(--brand-text-${name});`,
      `--text-${name}--line-height: var(--brand-text-${name}-lh);`,
      `--text-${name}--font-weight: var(--brand-text-${name}-weight);`,
      `--text-${name}--letter-spacing: var(--brand-text-${name}-tracking);`,
    );
  }
  for (const role of RADIUS_ROLES) lines.push(`--radius-${role}: var(--brand-radius-${role});`);
  return `@theme inline {\n${lines.map((line) => `  ${line}`).join("\n")}\n}\n`;
}
```

- [ ] **Step 4: Export the new names.** In `src/index.ts`, replace `export { themeCss } from "./theme";` with:

```ts
export { extraSurfaceRoles, secondaryButton, surfaceRoles, tailwindThemeCss, themeCss } from "./theme";
```

- [ ] **Step 5: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass; no type errors.

- [ ] **Step 6: Commit.**

```bash
git add apps/frontend/packages/site-kit/src/theme.ts apps/frontend/packages/site-kit/src/index.ts apps/frontend/packages/site-kit/test/theme.test.ts
git commit -m "site-kit theme: the kit's band and extra surfaces, a secondary button from the kit's outline recipe, and its own Tailwind mapping"
```

### Task 5: The agent kit — whole logos, a second button style, a link, and the extra surfaces

`kit.Image` crops logos (`src/agent-kit.tsx:11-12,26-33`; cl3's AudienceBand cropped partner logos
with `fit="fill"`), `kit.Button` has one style (`:9,23`), and there is no `kit.Link`, so an agent
section's plain `<a href>` never gets the site's base path (`src/config.tsx:56-59`).

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/sections.tsx` (`Shell`, `Button`, new `surfaceClass`)
- Modify: `apps/frontend/packages/site-kit/src/agent-kit.tsx` (whole file below)
- Modify: `apps/frontend/packages/site-kit/src/shell.tsx` (new `logoFiles`)
- Modify: `apps/frontend/packages/site-kit/src/config.tsx:113`
- Modify: `apps/frontend/packages/site-kit/src/index.ts`
- Create: `apps/frontend/packages/site-kit/test/agent-kit.test.tsx`

**Interfaces:**
- Consumes: `themeCss` classes `.brand-btn-secondary` (Task 4).
- Produces:
  - `type AnySurface = Surface | (string & {})`, `surfaceClass(surface: AnySurface): string`,
    `type ButtonVariant = "primary" | "secondary"` (sections.tsx);
  - `logoFiles(brand: BrandData): Set<string>` (shell.tsx);
  - `makeKit(href: Href, brand: BrandData): Kit` — **signature change**; the only caller is
    `config.tsx`;
  - `Kit.Image` takes `fit?: "fill" | "contain"`; `Kit.Button` takes `variant?: ButtonVariant`;
    `Kit.Link({href, children, arrow?})`; `Kit.Shell` takes any surface name.

- [ ] **Step 1: Write the failing tests** in `test/agent-kit.test.tsx`:

```tsx
// Brand fidelity (Wave 2): the kit shows logos whole, has a second button style, resolves links to
// the site's address, and lets a section stand on the kit's extra surfaces.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { makeKit } from "../src/agent-kit";
import { logoFiles } from "../src/shell";
import { garner } from "./fixtures/garner";

const brand = garner();
const href = (value: string) => (value.startsWith("/") && !value.startsWith("//") ? `/s/x${value === "/" ? "" : value}` : value);
const kit = makeKit(href, brand);
const html = (node: ReactNode) => renderToStaticMarkup(<>{node}</>);

test("a logo from the kit is shown whole; fit decides for every other image", () => {
  const logos = logoFiles(brand);
  assert.ok(logos.size > 0, "Garner's kit has logo files");
  const logo = [...logos][0];
  assert.match(html(kit.Image({ src: logo })), /class="h-full w-full object-contain"/);
  const photo = Object.values(brand.assets).find((asset) => asset.kind === "raster_image" && !logos.has(asset.file))!.file;
  assert.match(html(kit.Image({ src: photo })), /class="w-full rounded-card object-cover"/);
  assert.match(html(kit.Image({ src: photo, fit: "contain" })), /class="h-full w-full object-contain"/);
  assert.match(html(kit.Image({ src: photo, fit: "fill" })), /class="absolute inset-0 h-full w-full object-cover"/);
});

test("the secondary button is the outline style; the primary keeps its class", () => {
  const primary = html(kit.Button({ label: "Request the analysis", href: "/analysis", surface: "page" }));
  assert.ok(primary.includes('href="/s/x/analysis"') && primary.includes('class="brand-btn"'), primary);
  const secondary = html(kit.Button({ label: "See how", href: "https://example.com", surface: "page", variant: "secondary" }));
  assert.ok(secondary.includes('class="brand-btn brand-btn-secondary"') && secondary.includes('href="https://example.com"'), secondary);
});

test("kit.Link resolves a route to the site's address and keeps other links as written", () => {
  const link = html(kit.Link({ href: "/analysis", children: "Read the analysis", arrow: true }));
  assert.ok(link.includes('href="/s/x/analysis"'), link);
  assert.ok(link.includes('class="font-cta text-cta underline underline-offset-4"'), link);
  assert.ok(link.includes("→"), link);
  assert.ok(html(kit.Link({ href: "#proof", children: "Proof" })).includes('href="#proof"'));
});

test("a section may stand on an extra surface by its brand.md name", () => {
  assert.ok(html(kit.Shell({ surface: "band-statement", children: "x" })).includes('class="bg-surface-band-statement text-on-surface-band-statement"'));
  assert.ok(html(kit.Shell({ surface: "brandSubtle", children: "x" })).includes('class="bg-surface-brand-subtle text-on-surface-brand-subtle"'));
});
```

- [ ] **Step 2: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/agent-kit.test.tsx`
Expected: FAIL — `logoFiles` is not exported and `kit.Link` is undefined.

- [ ] **Step 3: Change `src/sections.tsx`.** Replace lines 41-58 (from `export const Shell` through
  the end of `Button`) with:

```tsx
/** A surface a section may stand on: one of our six choices, or an extra surface of the kit by
 * the name brand.md gives it ("canvas", "band-statement" for surface.band.statement). */
export type AnySurface = Surface | (string & {});
export type ButtonVariant = "primary" | "secondary";

export function surfaceClass(surface: AnySurface): string {
  return SURFACE_CLASS[surface as Surface] ?? `bg-surface-${surface} text-on-surface-${surface}`;
}

export const Shell = ({ surface, children }: { surface: AnySurface; children: ReactNode }) => (
  <section className={surfaceClass(surface)}>
    <div className="mx-auto max-w-[75rem] px-6 py-16 md:px-10 md:py-24">{children}</div>
  </section>
);

export const Eyebrow = ({ children }: { children: Text }) =>
  children ? <p className="font-eyebrow text-eyebrow uppercase opacity-80">{children}</p> : null;

export function Button({ label, href, surface, variant = "primary" }: { label: Text; href: string; surface: AnySurface; variant?: ButtonVariant }) {
  if (!label) return null;
  return (
    <a href={href || "#"} className={variant === "secondary" ? "brand-btn brand-btn-secondary" : "brand-btn"} data-surface={surface}>
      {label}
      <span aria-hidden>→</span>
    </a>
  );
}
```

- [ ] **Step 4: Add `logoFiles` to `src/shell.tsx`,** right after `sellerLogo`:

```tsx
/** Every file of the kit's logos, all variants (mark, primary, reversed…). kit.Image shows these whole. */
export function logoFiles(brand: BrandData): Set<string> {
  const logos = (brand.kit as { assets?: { logos?: Logos } }).assets?.logos ?? {};
  const files = new Set<string>();
  for (const logo of Object.values(logos)) {
    for (const variant of logo?.variants ?? []) {
      const file = brand.assets[variant.asset_id]?.file;
      if (file) files.add(file);
    }
  }
  return files;
}
```

- [ ] **Step 5: Replace `src/agent-kit.tsx` with this file.**

```tsx
// The kit a section written by the agent (E5) builds with: the same Shell, Button and Eyebrow our
// own sections use, so a new section takes the brand's surfaces, text colours and buttons exactly
// as they do. Image takes only files from the brand's assets (the validator checks the path);
// Link and Button point a /route link at wherever the site is served.
import type { ReactNode } from "react";
import type { BrandData } from "./brand";
import { Button as BrandButton, Eyebrow, Shell, type AnySurface, type ButtonVariant, type Href } from "./sections";
import { logoFiles } from "./shell";

export type Kit = {
  /** surface: one of the six choices, or an extra surface brand.md lists ("canvas", "band-statement"). */
  Shell: (props: { surface: AnySurface; children: ReactNode }) => ReactNode;
  /** variant "secondary" is the brand's second button style (brand.md, Buttons). */
  Button: (props: { label: string; href: string; surface: AnySurface; variant?: ButtonVariant }) => ReactNode;
  Eyebrow: (props: { children: ReactNode }) => ReactNode;
  /** A text link: an https:// URL, a /route of this site or a #anchor; arrow adds " →". */
  Link: (props: { href: string; children: ReactNode; arrow?: boolean }) => ReactNode;
  /** fit="fill": covers its positioned parent (a background photo). fit="contain": the whole image
   * inside its box, never cropped or rounded (a logo). Neither: full width with the brand's corners.
   * A logo from the brand kit is always shown whole. */
  Image: (props: { src: string; alt?: string; fit?: "fill" | "contain"; className?: never }) => ReactNode;
};

export type AgentSectionModule = {
  schema: { safeParse: (value: unknown) => { success: boolean } };
  render: (props: never, kit: Kit) => ReactNode;
};

const IMAGE_CLASS = {
  fill: "absolute inset-0 h-full w-full object-cover",
  contain: "h-full w-full object-contain",
  standard: "w-full rounded-card object-cover",
} as const;

export function makeKit(href: Href, brand: BrandData): Kit {
  const logos = logoFiles(brand);
  return {
    Shell,
    Button: ({ label, href: target, surface, variant }) => (
      <BrandButton label={label} href={href(target)} surface={surface} variant={variant} />
    ),
    Eyebrow,
    Link: ({ href: target, children, arrow }) => (
      <a href={href(target) || "#"} className="font-cta text-cta underline underline-offset-4">
        {children}
        {arrow ? <span aria-hidden> →</span> : null}
      </a>
    ),
    // eslint-disable-next-line @next/next/no-img-element
    Image: ({ src, alt, fit }) =>
      src ? <img src={src} alt={alt ?? ""} className={IMAGE_CLASS[fit ?? (logos.has(src) ? "contain" : "standard")]} /> : null,
  };
}
```

- [ ] **Step 6: Pass the brand to the kit** in `src/config.tsx:113`: `const kit = makeKit(href);`
  becomes `const kit = makeKit(href, brand);`.

- [ ] **Step 7: Export the new names** from `src/index.ts`: change the shell export line to
  `export { SiteFooter, SiteHeader, logoFiles, sellerLogo, type FooterProps, type HeaderProps, type ShellData } from "./shell";`
  and add `export { surfaceClass, type AnySurface, type ButtonVariant } from "./sections";`.

- [ ] **Step 8: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass (the check-section type-check test still reports TS2322 for `<kit.Button href="/x">`,
which lacks `label` and `surface`); no type errors. Change the package's `test` script to
`"tsx --test test/*.test.ts test/*.test.tsx"` in `package.json` so `npm test` runs the `.tsx` file too.

- [ ] **Step 9: Commit.**

```bash
git add apps/frontend/packages/site-kit/src apps/frontend/packages/site-kit/test/agent-kit.test.tsx apps/frontend/packages/site-kit/package.json
git commit -m "site-kit kit: logos shown whole, a secondary button, kit.Link, and the kit's extra surfaces"
```

### Task 6: The section check refuses raw links and classes the theme does not define; the validator checks agent-section links

Issue 49 (`trials/puck-spike/ISSUES.md:214-217`): cl3 wrote `border-line-inverse` and
`bg-surface-brandSubtle`, which exist nowhere, and a plain `<a href>` that skips the base path; the
validator walks agent-section props for images only (`src/validate.ts:166-175`).

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/check-section.ts`
- Modify: `apps/frontend/packages/site-kit/src/validate.ts` (the agent-section walk)
- Modify: `apps/frontend/packages/site-kit/src/schemas.ts` (`pageSchemaWith`: the section-id rule)
- Modify: `apps/frontend/packages/site-kit/test/check-section.test.ts`
- Modify: `apps/frontend/packages/site-kit/test/multipage.test.ts`
- Create: `apps/frontend/packages/site-kit/test/section-ids.test.ts`

**Interfaces:**
- Consumes: `COLOR_ROLES`, `SURFACES`, `colorVar` (Task 4).
- Produces: `lint(source: string, options?: LintOptions): string[]`,
  `type LintOptions = { extraSurfaces?: string[] }` (kit roles such as `surface.band.statement`;
  B6 passes `extraSurfaceRoles(brand)`), `export const LINK_REFUSAL: string`.

- [ ] **Step 1: Show the founder the three new refusals and get a yes.** All are agent-facing:
  - `<a> is not allowed in a section; write links with kit.Link (or kit.Button for a button) so they reach the right page wherever the site is published`
  - `class "<class>" is not one of the brand's classes; the brand's colour classes are text-ink-*, bg-surface-*, text-on-surface-* and border-line-* (see brand/brand.md)`
  - `a section id may use only letters, digits, "-" and "_" (up to 200 characters); "<id>" does not`
    (controller ruling R10, 2026-10-11: the editor addresses a section as
    `site:<route>#<id>.<field>` and refuses to open a site whose ids break that, so the validator
    keeps such an id out of every stored site; all 50 ids the spike's agent wrote already comply)

- [ ] **Step 2: Write the failing tests.** Append to `test/check-section.test.ts` (import
  `LINK_REFUSAL` beside `lint`):

```ts
test("a raw <a> is refused; links go through kit.Link or kit.Button", () => {
  const errors = lint(EXAMPLE.replace("</kit.Shell>", '<a href="/analysis">More</a></kit.Shell>'));
  assert.ok(errors.includes(LINK_REFUSAL), errors.join("; "));
});

test("a colour class the theme does not define is refused by name", () => {
  for (const cls of ["border-line-inverse", "bg-surface-brandSubtle", "text-ink-tertiary"]) {
    const errors = lint(withClass(`mt-6 ${cls}`));
    assert.ok(errors.some((e) => e.startsWith(`class "${cls}" is not one of the brand's classes`)), `${cls}: ${errors.join("; ")}`);
  }
});

test("variants, opacity and every defined colour class pass", () => {
  assert.deepEqual(lint(withClass("mt-6 md:bg-surface-muted hover:border-line-subtle/50 text-on-surface-brand ring-focus bg-surface-canvas")), []);
});

test("the kit's extra surfaces pass only when the brand has them", () => {
  const band = withClass("mt-6 bg-surface-band-statement text-on-surface-band-statement");
  assert.ok(lint(band).some((e) => e.startsWith('class "bg-surface-band-statement" is not one of the brand\'s classes')));
  assert.deepEqual(lint(band, { extraSurfaces: ["surface.band.statement"] }), []);
});
```
  Append to `test/multipage.test.ts`:

```ts
test("an agent section's links are checked like the page's own: real pages, one destination", () => {
  const sections = { QuoteBand: { schema: { safeParse: () => ({ success: true }) } } };
  const home = structuredClone(site.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "page", ctaHref: "/pricing" } });
  const pages = () => ({ "/": home, "/analysis": site.pages["/analysis"] });
  const missing = validateSite({ pages: pages(), shell: site.shell }, brand, sections);
  assert.ok(missing.errors.some((e) => e.startsWith("page.content.5(quote).ctaHref: links to /pricing, which is not a page of this site")), missing.errors.join("\n"));
  home.content[5].props.ctaHref = "https://example.com/somewhere-else";
  const two = validateSite({ pages: pages(), shell: site.shell }, brand, sections);
  assert.ok(two.errors.some((e) => e.startsWith("site: a 1:1 page has one primary destination")), two.errors.join("\n"));
});
```

  And create `test/section-ids.test.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { pageSchemaWith } from "../src/schemas";

const page = (id: string) => ({ root: { props: { title: "T" } }, content: [{ type: "Unknown", props: { id } }] });
const idIssues = (id: string) => {
  const result = pageSchemaWith().safeParse(page(id));
  return result.success ? [] : result.error.issues.filter((issue) => issue.message.startsWith("a section id may use only"));
};

test("a section id is letters, digits, - and _ only, so an editor target is never ambiguous", () => {
  for (const id of ["hero", "analysis-hero", "Hero_2", "CtaBand-1a2b3c"]) assert.deepEqual(idIssues(id), [], id);
  for (const id of ["hero.v2", "a#b", "with space", "x".repeat(201)]) {
    const issues = idIssues(id);
    assert.equal(issues.length, 1, id);
    assert.deepEqual(issues[0].path, ["content", 0, "props", "id"]);
    assert.ok(issues[0].message.endsWith(`"${id}" does not`), issues[0].message);
  }
});
```

- [ ] **Step 3: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/check-section.test.ts test/multipage.test.ts test/section-ids.test.ts`
Expected: FAIL — no `LINK_REFUSAL` export, unknown classes pass, agent-section links are not checked,
and `hero.v2` passes as a section id.

- [ ] **Step 4: Add the rules to `src/check-section.ts`.**
  1. Add to the imports: `import { COLOR_ROLES, SURFACES as THEME_SURFACES, colorVar } from "./theme";`
  2. After the `RULES` array, add:

```ts
/** A colour class in the brand's own namespaces (text-ink-*, bg-surface-*, text-on-surface-*,
 * border-line-*, ring-focus). Its name must be one the theme defines: issue 49's
 * border-line-inverse and bg-surface-brandSubtle exist nowhere and render unstyled. */
const BRAND_COLOUR_CLASS = new RegExp(`^(?:${COLOUR_UTILITY})-((?:ink|surface|on-surface|line)(?:-[A-Za-z0-9-]+)?|focus)$`);

export const LINK_REFUSAL =
  "<a> is not allowed in a section; write links with kit.Link (or kit.Button for a button) so they reach the right page wherever the site is published";

/** extraSurfaces: the brand's extra surface roles (extraSurfaceRoles(brand)), whose classes exist. */
export type LintOptions = { extraSurfaces?: string[] };

function brandColourNames(extraSurfaces: string[]): Set<string> {
  const names = new Set<string>(COLOR_ROLES.map(colorVar));
  for (const surface of [...THEME_SURFACES, ...extraSurfaces]) {
    names.add(colorVar(surface));
    names.add(`on-${colorVar(surface)}`);
  }
  return names;
}
```
  3. In `bannedNames`'s `visit`, after the event-handler check, add:

```ts
    if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText(file) === "a") add(LINK_REFUSAL);
```
  4. Change `export function lint(source: string): string[] {` to
     `export function lint(source: string, options: LintOptions = {}): string[] {`, and right after
     the `for (const token of classTokens(source)) { … RULES … }` loop add:

```ts
  const known = brandColourNames(options.extraSurfaces ?? []);
  for (const token of classTokens(source)) {
    const bare = token.replace(/^!/, "").replace(/\/\d+$/, "");
    const match = BRAND_COLOUR_CLASS.exec(bare);
    if (match && !known.has(match[1]) && !seen.has(token)) {
      seen.add(token);
      errors.push(`class "${token}" is not one of the brand's classes; the brand's colour classes are text-ink-*, bg-surface-*, text-on-surface-* and border-line-* (see brand/brand.md)`);
    }
  }
```

- [ ] **Step 5: Check agent-section links in `src/validate.ts`.** Replace the agent-section block
  (`if (item.type in agentSections) { … walk(item.props, at); }`) with:

```ts
      if (item.type in agentSections) {
        // An agent section's images must be the brand's (or this site's). Its links — props named
        // …Href — must reach real pages, and a link prop named for a cta or a button is a primary
        // destination like any other button's (Wave 2 Lane A, Task 6).
        const walk = (value: unknown, where: string, key: string) => {
          if (typeof value === "string") {
            if (IMAGE_PATH.test(value)) {
              if (!imageAllowed(value)) errors.push(imageError(where, value));
            } else if (/href$/i.test(key)) {
              addWritten(value, where);
              if (/cta|button/i.test(key)) addDestination(value, where);
            }
          } else if (Array.isArray(value)) value.forEach((v, i) => walk(v, `${where}.${i}`, key));
          else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) walk(v, `${where}.${k}`, k);
        };
        walk(item.props, at, "");
      }
```

- [ ] **Step 5a: The section-id rule in `src/schemas.ts`.** In `pageSchemaWith`'s `superRefine`, at
  the top of the `page.content.forEach((entry, index) => {` body (before the unknown-type check, so
  every section is held to it, our own and agent-written alike), add:

```ts
      // Controller ruling R10: the editor and the composer address a section as
      // site:<route>#<id>.<field>, so an id may never carry "#", "." or anything else.
      const sectionId = entry.props.id;
      if (typeof sectionId === "string" && !SECTION_ID.test(sectionId)) {
        ctx.addIssue({
          code: "custom",
          path: ["content", index, "props", "id"],
          message: `a section id may use only letters, digits, "-" and "_" (up to 200 characters); "${sectionId}" does not`,
        });
      }
```
  and above `pageSchemaWith` add `const SECTION_ID = /^[A-Za-z0-9_-]{1,200}$/;`.

- [ ] **Step 6: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass (the skill's own example and the hostile fixtures' expectations are unchanged;
every fixture id already matches the rule).

- [ ] **Step 7: Commit.**

```bash
git add apps/frontend/packages/site-kit/src/check-section.ts apps/frontend/packages/site-kit/src/validate.ts apps/frontend/packages/site-kit/src/schemas.ts apps/frontend/packages/site-kit/test/check-section.test.ts apps/frontend/packages/site-kit/test/multipage.test.ts apps/frontend/packages/site-kit/test/section-ids.test.ts
git commit -m "site-kit: refuse raw links and undefined brand classes in agent sections; check their links and section ids in the validator"
```

### Task 7: brand.md tells the agent every type role, every surface, both buttons, links, logos and the kit's own rules

brand.md shows four type roles (`src/catalog.ts:203-206`), no kit names for surfaces, one button,
no link rule, no logos, and none of the kit's rules (issues 5, 47, 48). The parked patch
`trials/puck-spike/proposed/kit-rules-in-brand-md.patch` adds the kit-name column and the rules;
this task adopts it and adds the rest. **This whole file is agent-facing: nothing is written before
the founder approves the text in Step 1.**

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/catalog.ts` (`brandFile`, new `typeRoleBasis`)
- Modify: `apps/frontend/packages/site-kit/test/catalog.test.ts`

**Interfaces:**
- Consumes: `TYPE_ROLES`, `typeVar`, `colorVar`, `surfaceRoles`, `secondaryButton` (Task 4);
  `logoFiles` is not needed (logos are listed from `kit.assets.logos` with their backgrounds).
- Produces: `typeRoleBasis(source: string | undefined): string` (exported from `src/catalog.ts`);
  `buildCatalog(brand, seller)` returns the new `brand/brand.md`.

- [ ] **Step 1: Show the founder the brand.md template and get a yes.** Generate Garner's file from
  the code below once it is written in a scratch branch, or show this template (angle brackets are
  filled from the kit; sections in [brackets] appear only when the kit has them):

```markdown
# Brand: <seller>

Every brand section takes its colours, type and buttons from these values. You choose by name
(for example `surface: "brand"`); you never write a colour or a size.

## Surfaces
| choice | kit name | name | colour | text on it |
|---|---|---|---|---|
| page | surface.page | Page | #F9FAF8 | text.primary #0E1110 |
| … one row for each of card, muted, brandSubtle, brand, inverse … |

[### More surfaces in this kit (for sections you write)
Our sections take only the six choices above. A section you write may also stand on these, with
`kit.Shell surface="<choice>"` or the classes `bg-surface-<choice> text-on-surface-<choice>`.
| choice | kit name | colour | text on it |
|---|---|---|---|
| canvas | surface.canvas | #FBFCFA | chosen by contrast |
| band-statement | surface.band.statement | #014036 | chosen by contrast |]

## Type roles
Each role is a pair of classes, `font-<role> text-<role>` (for example `font-title text-title`).
"measured" means the seller's own site showed it, for the fields listed; "derived" means the kit
worked it out from the measured roles.
| role | classes | font | size at 1440 | weight | line height | from |
|---|---|---|---|---|---|---|
| display | `font-display text-display` | Stix Two Text | 139px | 500 | 1.05 | derived |
| headline | `font-headline text-headline` | Stix Two Text | 87px | 500 | 1 | measured: family, size, weight, line height |
| … one row for each of title, subtitle, body, body.small, eyebrow, cta, stat, label, caption, legal … |

Our sections' headings choose from display, headline and title (`headingRole`).

[Headings on light surfaces use the brand's heading ink <colour>.]

## Buttons
- Primary: `kit.Button` (the default). The brand's primary button, measured from its own hero:
  background <colour>, text <colour>, radius <radius>, <weight> weight.
  (or, with no measurement: No measured button; the kit's own button is used (its brand colour
  fill, its pill shape).)
- Secondary: `kit.Button variant="secondary"`. The kit's <variant> recipe: <text token> label, a
  <border token> border in the same colour, <radius token>.
  (or, with no recipe: A plain outline: the text colour for the label and a 1px border in the same
  colour, with the primary button's shape.)
On dark surfaces both switch to their light versions automatically.

## Links
Write every link with `kit.Link` (a text link; `arrow` adds " →") or `kit.Button`, never a bare
`<a>`. A link to another page of this site is written `/` or `/<page>`; the kit points it at the
right address wherever the site is published.

[## The brand's own rules (from its brand kit)
Where a rule names a kit colour such as `surface.brand`, the matching choice is in the surfaces tables.
- <rule> (<scope>)
- …]

## Logos (always shown whole)
`kit.Image` shows a logo whole: never cropped, never rounded.
- `/asset-store/<sha256>`: <logo title>, <variant name>; on <allowed backgrounds>
- … (or: This kit has no logo files.)

## Assets (the only images and logos a page may use)
- `/asset-store/<sha256>` (<kind>, <asset id>): <description>
- …
```

- [ ] **Step 2: Write the failing tests.** Append to `test/catalog.test.ts` (import `typeRoleBasis`
  from `../src/catalog` beside `buildCatalog`):

```ts
test("typeRoleBasis reads measured or derived from a token's provenance", () => {
  assert.equal(typeRoleBasis("website:rendered :: h1"), "measured");
  assert.equal(
    typeRoleBasis("derived:type.headline; measured=font_family,font_size,font_weight,line_height @ website:rendered :: h1"),
    "measured: family, size, weight, line height",
  );
  assert.equal(typeRoleBasis("derived:type.eyebrow; measured=none"), "derived");
  assert.equal(typeRoleBasis("default:type-scale"), "derived");
  assert.equal(typeRoleBasis(undefined), "derived");
});

test("brand.md lists all twelve type roles with their classes and where each came from", () => {
  const md = read("brand/brand.md");
  for (const [role, cls] of [
    ["display", "display"], ["headline", "headline"], ["title", "title"], ["subtitle", "subtitle"],
    ["body", "body"], ["body.small", "body-small"], ["eyebrow", "eyebrow"], ["cta", "cta"],
    ["stat", "stat"], ["label", "label"], ["caption", "caption"], ["legal", "legal"],
  ]) {
    assert.ok(md.includes(`| ${role} | \`font-${cls} text-${cls}\` |`), role);
  }
  assert.ok(md.includes("| headline | `font-headline text-headline` | Stix Two Text | 87px | 500 | 1 | measured: family, size, weight, line height |"), md);
  assert.ok(md.includes("| eyebrow | `font-eyebrow text-eyebrow` | Stix Two Text | 12px | 500 | 1.2 | derived |"), md);
});

test("brand.md names each surface's kit token and lists the kit's other surfaces", () => {
  const md = read("brand/brand.md");
  assert.ok(md.includes("| brandSubtle | surface.brand.subtle | Brand, subtle | #E1F5F0 |"), md);
  assert.ok(md.includes("| canvas | surface.canvas | #FBFCFA |"), md);
  assert.ok(md.includes('`kit.Shell surface="<choice>"`'), md);
});

test("brand.md gives both buttons, the link rule, the logos and the kit's own rules", () => {
  const md = read("brand/brand.md");
  assert.ok(md.includes('`kit.Button variant="secondary"`. The kit\'s outline.1 recipe: text.primary label, a stroke.width.thin border in the same colour, radius.full.'), md);
  assert.ok(md.includes("Write every link with `kit.Link`"), md);
  assert.ok(md.includes("- Filled and outline buttons are pills. Use radius.full. Do not use radius.button. (Buttons)"), md);
  assert.match(md, /## Logos \(always shown whole\)\n`kit\.Image` shows a logo whole: never cropped, never rounded\.\n- `\/asset-store\/[0-9a-f]{64}`: /);
});
```

- [ ] **Step 3: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/catalog.test.ts`
Expected: FAIL — `typeRoleBasis` is not exported, and brand.md has four type roles.

- [ ] **Step 4: Rewrite `brandFile` in `src/catalog.ts`.** Change the imports at the top to:

```ts
import { parse, TextNode, type HTMLElement } from "node-html-parser";
import { z } from "zod";
import type { BrandData } from "./brand";
import type { Clone } from "./clone";
import { COMPONENT_SCHEMAS, SURFACES, SURFACE_LABELS } from "./schemas";
import { TYPE_ROLES, colorVar, secondaryButton, surfaceRoles, typeVar } from "./theme";
```
  and replace everything from `type Token = { value: { default: Record<string, unknown> } };`
  through the end of `brandFile` with:

```ts
type Token = { value: { default: Record<string, unknown> } };
type TypeToken = {
  value: { default: { font_family: string; font_size: number; font_weight: number; line_height: number } };
  provenance?: { source?: string };
};
type Recipe = { component?: string; variant?: string; text?: string | null; border?: string | null; radius?: string | null };
type Constraint = { rule?: string; scope?: string } | string;
type LogoEntry = { title?: string; variants?: { name: string; asset_id: string }[]; allowed_backgrounds?: string[] };

const FIELD_WORDS: Record<string, string> = {
  font_family: "family", font_size: "size", font_weight: "weight", line_height: "line height", letter_spacing: "letter spacing",
};

/** Whether a type role was measured on the seller's site, read from its token's provenance.source
 * (lumen_ingestion/normalizer): "<source>:<locator>" is measured; "derived:type.X; measured=<fields>
 * …" is measured for those fields, or derived when the list is "none"; "default:type-scale" is derived. */
export function typeRoleBasis(source: string | undefined): string {
  if (!source || source.startsWith("default:")) return "derived";
  const derived = /^derived:[^;]*;\s*measured=([^\s@]+)/.exec(source);
  if (!derived) return source.startsWith("derived:") ? "derived" : "measured";
  if (derived[1] === "none") return "derived";
  return `measured: ${derived[1].split(",").map((field) => FIELD_WORDS[field.trim()] ?? field.trim()).join(", ")}`;
}

function brandFile(brand: BrandData, seller?: string): string {
  const kit = brand.kit as {
    name?: string;
    tokens: { colors: Record<string, Token>; typography: Record<string, TypeToken> };
    constraints?: { contrast_pairs?: { background: string; foreground: string }[] };
    brief?: { constraints?: Constraint[]; component_recipes?: Recipe[] };
    assets?: { logos?: Record<string, LogoEntry> };
  };
  const color = (role: string) => String(kit.tokens.colors[role]?.value.default.value ?? "");
  const pairs = kit.constraints?.contrast_pairs ?? [];
  const ink = (role: string) => {
    const foreground = pairs.find((pair) => pair.background === role)?.foreground;
    return foreground ? `${foreground}${foreground.startsWith("text.") ? ` ${color(foreground)}` : ""}` : "chosen by contrast";
  };
  const surfaces = SURFACES.map((choice) => {
    const role = SURFACE_ROLE[choice];
    return `| ${choice} | ${role} | ${SURFACE_LABELS[choice]} | ${color(role)} | ${ink(role)} |`;
  });
  const ours = new Set<string>(Object.values(SURFACE_ROLE));
  const extras = surfaceRoles(brand)
    .filter((role) => !ours.has(role) && color(role))
    .map((role) => `| ${colorVar(role).replace(/^surface-/, "")} | ${role} | ${color(role)} | ${ink(role)} |`);
  const typeRows = TYPE_ROLES.map((role) => {
    const classes = `\`font-${typeVar(role)} text-${typeVar(role)}\``;
    const token = kit.tokens.typography[`type.${role}`];
    if (!token) return `| ${role} | ${classes} | not in this kit | | | | |`;
    const style = token.value.default;
    return `| ${role} | ${classes} | ${style.font_family} | ${style.font_size}px | ${style.font_weight} | ${style.line_height} | ${typeRoleBasis(token.provenance?.source)} |`;
  });
  const button = brand.measured?.primary_button;
  const heading = brand.measured?.heading_on_light;
  const secondary = secondaryButton(brand);
  const recipe = (kit.brief?.component_recipes ?? []).find((entry) => entry.component === "button" && entry.variant === secondary.source);
  const rules = (kit.brief?.constraints ?? [])
    .map((entry) => (typeof entry === "string" ? { rule: entry, scope: "" } : { rule: entry.rule ?? "", scope: entry.scope ?? "" }))
    .filter((entry) => entry.rule)
    .map((entry) => `- ${entry.rule.replace(/\s+/g, " ")}${entry.scope ? ` (${entry.scope})` : ""}`);
  const logos = Object.values(kit.assets?.logos ?? {}).flatMap((logo) =>
    (logo.variants ?? [])
      .map((variant) => {
        const file = brand.assets[variant.asset_id]?.file;
        const on = logo.allowed_backgrounds?.length ? `; on ${logo.allowed_backgrounds.join(", ")}` : "";
        return file ? `- \`${file}\`: ${logo.title ?? "logo"}, ${variant.name.replace(/_/g, " ")}${on}` : "";
      })
      .filter(Boolean),
  );
  const assets = Object.entries(brand.assets).map(
    ([key, asset]) => `- \`${asset.file}\` (${asset.kind}${key.startsWith("asset_") ? `, ${key}` : ""}): ${(asset.description ?? asset.label ?? "").replace(/\s+/g, " ").slice(0, 220)}`,
  );
  return [
    `# Brand: ${seller ?? kit.name ?? brand.slug}`,
    "",
    "Every brand section takes its colours, type and buttons from these values. You choose by name",
    "(for example `surface: \"brand\"`); you never write a colour or a size.",
    "",
    "## Surfaces",
    "| choice | kit name | name | colour | text on it |",
    "|---|---|---|---|---|",
    ...surfaces,
    "",
    ...(extras.length
      ? [
          "### More surfaces in this kit (for sections you write)",
          "Our sections take only the six choices above. A section you write may also stand on these, with",
          "`kit.Shell surface=\"<choice>\"` or the classes `bg-surface-<choice> text-on-surface-<choice>`.",
          "| choice | kit name | colour | text on it |",
          "|---|---|---|---|",
          ...extras,
          "",
        ]
      : []),
    "## Type roles",
    "Each role is a pair of classes, `font-<role> text-<role>` (for example `font-title text-title`).",
    "\"measured\" means the seller's own site showed it, for the fields listed; \"derived\" means the kit",
    "worked it out from the measured roles.",
    "| role | classes | font | size at 1440 | weight | line height | from |",
    "|---|---|---|---|---|---|---|",
    ...typeRows,
    "",
    "Our sections' headings choose from display, headline and title (`headingRole`).",
    "",
    ...(heading ? [`Headings on light surfaces use the brand's heading ink ${heading.color}.`, ""] : []),
    "## Buttons",
    `- Primary: \`kit.Button\` (the default). ${
      button
        ? `The brand's primary button, measured from its own hero: background ${button.background}, text ${button.color}, radius ${button.borderRadius}, ${button.fontWeight} weight.`
        : "No measured button; the kit's own button is used (its brand colour fill, its pill shape)."
    }`,
    `- Secondary: \`kit.Button variant="secondary"\`. ${
      recipe
        ? `The kit's ${secondary.source} recipe: ${recipe.text ?? "text.primary"} label, a ${recipe.border ?? "1px"} border in the same colour, ${recipe.radius ?? "the primary button's corners"}.`
        : "A plain outline: the text colour for the label and a 1px border in the same colour, with the primary button's shape."
    }`,
    "On dark surfaces both switch to their light versions automatically.",
    "",
    "## Links",
    "Write every link with `kit.Link` (a text link; `arrow` adds \" →\") or `kit.Button`, never a bare",
    "`<a>`. A link to another page of this site is written `/` or `/<page>`; the kit points it at the",
    "right address wherever the site is published.",
    "",
    ...(rules.length
      ? [
          "## The brand's own rules (from its brand kit)",
          "Where a rule names a kit colour such as `surface.brand`, the matching choice is in the surfaces tables.",
          ...rules,
          "",
        ]
      : []),
    "## Logos (always shown whole)",
    "`kit.Image` shows a logo whole: never cropped, never rounded.",
    ...(logos.length ? logos : ["This kit has no logo files."]),
    "",
    "## Assets (the only images and logos a page may use)",
    ...assets,
    "",
  ].join("\n");
}
```

- [ ] **Step 5: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass, including the older brand.md test (Stix Two Text, `#047464`, "button", an asset file).

- [ ] **Step 6: Commit** (only after the founder's yes in Step 1).

```bash
git add apps/frontend/packages/site-kit/src/catalog.ts apps/frontend/packages/site-kit/test/catalog.test.ts
git commit -m "site-kit brand.md: all twelve type roles (measured or derived), kit surface names and extras, both buttons, links, logos and the kit's rules"
```

## A1 — kind branches

### Task 8: The design API treats a site like its own kind (document read, gates, tool refusals)

Survey A1.1/A1.2: `GET /documents/{id}` runs the scene `render_context` for anything not `web`
(`lumen_api/main.py:2606-2608`), `public_document` hides `account_id` for non-web documents
(`main.py:8160-8172`), and the tool gate reports a site as `design_document_not_web`
(`toolbelt/documents.py:146-151`). This task also creates the shared test helper the site suites
use from here on.

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:2606-2608` (GET document),
  `:7892-7908` (add `require_site_document` after `require_web_document`), `:8160-8172`
  (`public_document`), `:1215-1240` (`_document_refusals`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/documents.py:146-151`
- Create: `subsystems/clue-design/apps/api/tests/site_kit_support.py`
- Create: `subsystems/clue-design/apps/api/tests/test_site_document_kind.py`

**Interfaces:**
- Consumes: the Wave 1 `doc_kind="site"` DAL branch (`clue_design/documents.py:201,382`).
- Produces:
  - `require_site_document(document: JsonObject) -> None` (module level in `main.py`; 409
    `document.kind_unsupported` for any other kind);
  - reason code `design_document_not_site` from `document_failures(..., kind="site")`;
  - test helpers in `tests/site_kit_support.py`: `REPO_ROOT`, `SITE_KIT`, `garner_brand() -> dict`,
    `garner_site(document_id: str, title: str = "Garner for Syracuse") -> dict`,
    `born_site(document_id: str, title: str = "Garner for Syracuse") -> dict`,
    `store_site(site: dict, *, account_id: str | None = None) -> dict`,
    `png(color: tuple[int, int, int]) -> bytes`,
    `hold_site_images(site: dict, brand: dict, blobs) -> tuple[dict, dict]`,
    `install_site_inputs(app, brand: dict, sections: Sequence = ()) -> None`,
    `ensure_site_kit_dist() -> Path`.

- [ ] **Step 1: Create the shared helper** `apps/api/tests/site_kit_support.py`:

```python
"""Shared fixtures for the Puck site suites (Wave 2 Lane A).

The brand and the site come from site-kit's own test fixtures (`apps/frontend/packages/site-kit/
test/fixtures`), so the design API is tested against the exact data the kit's tests use. Site
documents are stored the way the platform births them (`clue_design.documents.create_document`
with `doc_kind="site"`).
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from clue_design.storage import SOURCE_KEY_ASSET

REPO_ROOT = Path(__file__).resolve().parents[5]
SITE_KIT = REPO_ROOT / "apps" / "frontend" / "packages" / "site-kit"
FIXTURES = SITE_KIT / "test" / "fixtures"
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")


def _read(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def garner_brand() -> dict[str, Any]:
    """Garner's BrandData as site-kit's `brandData()` builds it from the same fixtures, minus the
    clone-captured images (no suite here needs them)."""
    clones = _read("clones.json")
    return {
        "slug": "garner",
        "kit": _read("kit.json"),
        "fonts": _read("fonts.json"),
        "assets": _read("assets.json"),
        "clones": {clone["id"]: clone for clone in clones},
        "measured": _read("measured.json"),
    }


def garner_site(document_id: str, title: str = "Garner for Syracuse") -> dict[str, Any]:
    """The `garner-syracuse` site as a stored site document (Contract 1)."""
    stored = _read("garner-syracuse.json")
    return {
        "id": document_id,
        "title": title,
        "theme": {},
        "pages": stored["pages"],
        "shell": stored["shell"],
        "agent_sections": {},
    }


def born_site(document_id: str, title: str = "Garner for Syracuse") -> dict[str, Any]:
    """The empty site a website leg births (platform/api/clue_api/site_documents.py)."""
    return {
        "id": document_id,
        "title": title,
        "theme": {},
        "pages": {"/": {"root": {"props": {"title": title}}, "content": []}},
        "shell": None,
        "agent_sections": {},
    }


def store_site(site: dict[str, Any], *, account_id: str | None = None) -> dict[str, Any]:
    from lumen_api.design_store import HybridRepository

    return HybridRepository().create_document(site, doc_kind="site", account_id=account_id)


def png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


def hold_site_images(site: dict[str, Any], brand: dict[str, Any], blobs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Swap every /asset-store digest the site's pages and shell name for a tiny PNG this
    workspace holds — in the site and in the brand alike — so custody passes as in production."""
    named = json.dumps({"pages": site["pages"], "shell": site["shell"]})
    mapping: dict[str, str] = {}
    for index, old in enumerate(dict.fromkeys(_ASSET_REF.findall(named))):
        data = png(((index * 40) % 256, 120, 200))
        blobs.register(data, media_type="image/png", source_key=SOURCE_KEY_ASSET)
        mapping[old] = hashlib.sha256(data).hexdigest()

    def swap(value: Any) -> Any:
        text = _ASSET_REF.sub(lambda m: "/asset-store/" + mapping.get(m.group(1), m.group(1)), json.dumps(value))
        return json.loads(text)

    return swap(site), swap(brand)


def install_site_inputs(app: Any, brand: dict[str, Any], sections: Sequence[Any] = ()) -> None:
    """Stand in for Lane B's two loaders (site_doc_inputs): this brand, and these section modules."""
    app.state.site_brand_loader = lambda repo, blobs, document: brand
    app.state.site_section_loader = lambda repo, blobs, agent_sections: [
        module for module in sections if agent_sections.get(module.name) == module.digest
    ]


@functools.lru_cache(maxsize=1)
def ensure_site_kit_dist() -> Path:
    """Build site-kit's dist/ once per test process (needs node and apps/frontend/node_modules)."""
    if not (REPO_ROOT / "apps" / "frontend" / "node_modules" / "esbuild").is_dir():
        raise RuntimeError("apps/frontend/node_modules is missing: run `npm ci` in apps/frontend")
    subprocess.run(["node", "bin/build-bundles.mjs"], cwd=SITE_KIT, check=True, capture_output=True, text=True, timeout=300)
    return SITE_KIT / "dist"
```

- [ ] **Step 2: Write the failing tests** in `apps/api/tests/test_site_document_kind.py`:

```python
"""The site document kind in the design API's reads and gates (Wave 2 Lane A, Task 8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app, require_site_document
from lumen_api.toolbelt.documents import document_failures
from site_kit_support import garner_site, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def test_get_document_treats_a_site_like_a_web_document(client: TestClient) -> None:
    store_site(garner_site("site_kind_get"))
    body = client.get("/documents/site_kind_get").json()
    assert body["doc_kind"] == "site"
    assert "render_context" not in body  # no scene render context, no platform-default brand call
    assert "account_id" in body and body["account_id"] is None  # exposed, as for web
    assert "fragment_meta" not in body


def test_the_site_gate_refuses_every_other_kind() -> None:
    require_site_document({"id": "doc_s", "doc_kind": "site"})
    for kind in ("web", "scene"):
        with pytest.raises(HTTPException) as refused:
            require_site_document({"id": "doc_x", "doc_kind": kind})
        assert refused.value.status_code == 409
        assert refused.value.detail["code"] == "document.kind_unsupported"


def test_the_tool_gate_names_a_document_that_is_not_a_site(client: TestClient) -> None:
    store_site(garner_site("site_kind_gate"))
    repo = HybridRepository()
    assert document_failures(repo, "site_kind_gate", kind="site", draft=True) == ()
    web = client.post("/documents", json={"doc_kind": "web", "title": "A web page"}).json()["document"]
    (failure,) = document_failures(repo, web["id"], kind="site")
    assert failure.reason_code == "design_document_not_site"
    (scene_gate,) = document_failures(repo, "site_kind_gate", kind="web")
    assert scene_gate.reason_code == "design_document_not_web"
```

- [ ] **Step 3: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_document_kind.py`
Expected: FAIL — `ImportError: cannot import name 'require_site_document'`.

- [ ] **Step 4: The GET read.** In `main.py`, inside `get_document` (`:2606-2608`), replace

```python
        is_web = document.get("doc_kind") == "web"
        if not is_web:
            result["render_context"] = document_render_context(app.state.core, repo, document)
```
  with

```python
        is_web = document.get("doc_kind") == "web"
        # A Puck site (Wave 2) is like a web document here: it has no scene, so no scene render
        # context and no platform-default brand-kit call.
        if document.get("doc_kind") not in ("web", "site"):
            result["render_context"] = document_render_context(app.state.core, repo, document)
```

- [ ] **Step 5: The site gate.** After `require_web_document` (`main.py:7908`), add:

```python
def require_site_document(document: JsonObject) -> None:
    """Gate the Puck site endpoints (Wave 2 Contract 2) to site documents.

    The mirror of require_web_document: a scene or WebDoc payload means nothing to the site routes,
    and a site payload means nothing to theirs, so any other kind is a 409."""
    kind = document.get("doc_kind", "scene")
    if kind != "site":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document.kind_unsupported",
                "message": (
                    f"document {document['id']} is a {kind!r} document; this "
                    "endpoint operates only on site documents"
                ),
            },
        )
```

- [ ] **Step 6: `account_id` for sites.** In `public_document` (`main.py:8160-8172`), replace
  `is_web = document.get("doc_kind") == "web"` with
  `is_web = document.get("doc_kind") in ("web", "site")  # a site is a 1:1 page too (Wave 2 ruling)`.

- [ ] **Step 7: The tool gate.** In `toolbelt/documents.py:146-151`, replace

```python
                reason_code=(
                    "design_document_not_scene" if kind == "scene" else "design_document_not_web"
                ),
```
  with

```python
                reason_code={
                    "scene": "design_document_not_scene",
                    "web": "design_document_not_web",
                    "site": "design_document_not_site",
                }[kind],
```
  and in `main.py`'s `_document_refusals` add the line
  `"design_document_not_site": kind_conflict,` after `"design_document_not_web": kind_conflict,`.

- [ ] **Step 8: Run the new tests and the neighbours they touch.**

Run: `DESIGN_PYTEST test_site_document_kind.py` then `DESIGN_PYTEST test_web_documents.py` then `DESIGN_PYTEST test_document_thumbnails.py`
Expected: all pass (the web and scene reads are unchanged).

- [ ] **Step 9: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/lumen_api/toolbelt/documents.py subsystems/clue-design/apps/api/tests/site_kit_support.py subsystems/clue-design/apps/api/tests/test_site_document_kind.py
git commit -m "design API: a site reads like a web document (no scene context, account_id shown); site gate and design_document_not_site"
```

### Task 9: The platform names a site like a web page in its labels and summaries, and its wire models accept "site"

Survey A1.1/A1.2: the exit judge calls a site a "scene ad" (`design_leg_wiring.py:338,408`), a
site turn's result would get the scene summary (`:869`) and a duplicated version (`:972`), and a 1:1
site page gets no account card (`:1516-1520`). The wire `Literal`s (`chat/schemas.py:698`,
`frontend_read/contract_v1.py:481`) would 500 on `"site"`; widening them is harmless before the
mapper sends it (Task 10).

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py:338,408,869,972,1516-1520`
- Modify: `platform/api/clue_api/chat/schemas.py:698`
- Modify: `platform/api/clue_api/frontend_read/contract_v1.py:481`
- Create: `tests/api/test_site_kind_labels.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `design_kind_label(kind: str | None) -> str` and
  `_card_account_id(row: Mapping[str, Any] | None) -> str | None` in `design_leg_wiring.py`;
  `DesignArtifactWire.kind: Literal["web", "ad", "site"]`;
  `AccountArtifact.type: Literal["presentation", "document", "web", "ad", "email", "site"]`.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_site_kind_labels.py`:

```python
"""A site (Puck) reads like a web page to the exit judge and in the turn summaries (Wave 2)."""

from __future__ import annotations

from clue_api.chat.schemas import DesignArtifactWire
from clue_api.design_leg_wiring import (
    _assistant_summary,
    _card_account_id,
    batch_summary,
    design_kind_label,
)
from clue_api.frontend_read.contract_v1 import AccountArtifact


def test_a_site_is_a_web_page_to_the_exit_judge() -> None:
    assert design_kind_label("site") == "web page"
    assert design_kind_label("web") == "web page"
    assert design_kind_label("scene") == "scene ad"
    assert design_kind_label("ad") == "scene ad"
    assert design_kind_label(None) == "scene ad"


def test_a_site_turn_reads_back_like_a_web_turn() -> None:
    summary = _assistant_summary(
        {
            "status": "succeeded",
            "document_id": "doc_site",
            "result": {"status": "succeeded", "doc_kind": "site", "current_version": 4, "summary": "Built the page."},
        }
    )
    assert summary == "Design turn succeeded on website document doc_site (now version 4): Built the page."


def test_batch_summary_names_a_site_turns_version_once() -> None:
    items = [
        (
            {"title": "Syracuse site", "position": 0},
            {"status": "succeeded", "document_id": "doc_site", "result": {"status": "succeeded", "doc_kind": "site", "current_version": 4}},
        ),
        (
            {"title": "Apollo ad", "position": 1},
            {"status": "succeeded", "result": {"status": "proposed", "acceptance_scope": "design", "current_version": 2}},
        ),
    ]
    lines = batch_summary(items).splitlines()
    assert lines[0] == "Syracuse site: Design turn succeeded on website document doc_site (now version 4)."
    assert lines[1].startswith("Apollo ad: Design saved and accepted") and "version 2" in lines[1]


def test_a_site_document_gets_its_account_card() -> None:
    assert _card_account_id({"doc_kind": "site", "account_id": "acc_1"}) == "acc_1"
    assert _card_account_id({"doc_kind": "web", "account_id": "acc_2"}) == "acc_2"
    assert _card_account_id({"doc_kind": "scene", "account_id": "acc_3"}) is None
    assert _card_account_id(None) is None


def test_the_wire_models_accept_site() -> None:
    wire = DesignArtifactWire(id="d", project_id="p", document_id="d", kind="site", title="T", status="draft", current_version_id="1")
    assert wire.kind == "site"
    artifact = AccountArtifact(
        id="d", title="T", type="site", thumbnail_path="/api/clue/design/documents/d/thumbnail?v=1",
        last_edited_label="Last edited Oct 11, 2026",
    )
    assert artifact.type == "site"
```

- [ ] **Step 2: Run them to see them fail.**

Run: `PLATFORM_PYTEST tests/api/test_site_kind_labels.py`
Expected: FAIL — `ImportError: cannot import name '_card_account_id'`.

- [ ] **Step 3: Add the two helpers** to `design_leg_wiring.py`, just above
  `async def _exit_judge_artifact_lines` (`:313`):

```python
def design_kind_label(kind: str | None) -> str:
    """How the exit judge and the summaries name a design document. A Puck site and a WebDoc are
    both a "web page" (ruling 2026-10-11); a scene document — wire kind "ad" — is a "scene ad"."""
    return "web page" if kind in ("web", "site") else "scene ad"


def _card_account_id(row: Mapping[str, Any] | None) -> str | None:
    """The target account a leg document carries for the G2 account card: web and site documents
    are 1:1 pages for one account; a scene ad carries none here."""
    if row is None or row.get("doc_kind") not in ("web", "site"):
        return None
    account_id = row.get("account_id")
    return str(account_id) if account_id else None
```

- [ ] **Step 4: Use them.** In `design_leg_wiring.py`:
  - `:338` `kind = "web page" if document.get("doc_kind") == "web" else "scene ad"` →
    `kind = design_kind_label(document.get("doc_kind"))`
  - `:408` `kind = "web page" if shown.get("kind") == "web" else "scene ad"` →
    `kind = design_kind_label(shown.get("kind"))`
  - `:869` `if str(result.get("doc_kind") or "") == "web":` →
    `if str(result.get("doc_kind") or "") in ("web", "site"):`
  - `:972` `if str(result.get("doc_kind") or "") != "web" and stands_at:` →
    `if str(result.get("doc_kind") or "") not in ("web", "site") and stands_at:`
  - `:1516-1520` replace

```python
                account_id = (
                    row.get("account_id")
                    if row is not None and row.get("doc_kind") == "web"
                    else None
                )
```
    with `account_id = _card_account_id(row)`.

- [ ] **Step 5: Widen the wire models.** `chat/schemas.py:698`: `kind: Literal["web", "ad"]` →
  `kind: Literal["web", "ad", "site"]`. `frontend_read/contract_v1.py:481`:
  `type: Literal["presentation", "document", "web", "ad", "email"]` →
  `type: Literal["presentation", "document", "web", "ad", "email", "site"]`.

- [ ] **Step 6: Run the new tests and the suites around them.**

Run: `PLATFORM_PYTEST tests/api/test_site_kind_labels.py` then `PLATFORM_PYTEST tests/api/test_multi_artifact_leg_engine_db.py` then `PLATFORM_PYTEST tests/api/test_p34_design_leg_engine_db.py` then `PLATFORM_PYTEST tests/api/contract_v1/test_contract_v1.py`
Expected: all pass (the contract parity test compares field sets, not enum values).

- [ ] **Step 7: Commit.**

```bash
git add platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/chat/schemas.py platform/api/clue_api/frontend_read/contract_v1.py tests/api/test_site_kind_labels.py
git commit -m "platform: a site is a web page to the exit judge and in turn summaries; the wire models accept the site kind"
```

### Task 10: The one wire-kind mapper sends `"site"` (ordered after Lane C's C1)

Contract 8: `"site"` travels everywhere a kind travels, and **Lane C's acceptance of `"site"` lands
before this commit is merged into any branch the editor runs on.** Keep this task as its own
commit so it can be ordered.

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py:737` (`design_document_card_fields`), plus a
  new `wire_kind` and `head_of_abm_doc_kind`
- Modify: `platform/api/clue_api/chat/composer_context.py:784`
- Modify: `platform/api/clue_api/chat/router.py:1415`
- Modify: `platform/api/clue_api/artifact_read_tools.py:170`, `project_library.py:438`,
  `account_research_turn_wiring.py:257` (Q1)
- Create: `tests/api/test_site_wire_kind.py`

**Interfaces:**
- Consumes: the widened `Literal`s (Task 9).
- Produces: `wire_kind(doc_kind: str) -> Literal["web", "ad", "site"]`,
  `head_of_abm_doc_kind(doc_kind: str) -> str` in `design_leg_wiring.py`.

- [ ] **Step 1: Confirm Lane C's C1 is in your base, or keep this commit unmerged.** Run
  `git log --oneline -- apps/frontend/src/features/artifacts/model/artifact-library.ts | head -3`
  and check that `artifact-library.ts:14` reads `z.enum(["web", "ad", "site"])`. If it does not, do
  the work, commit it, and tell the orchestrator this commit waits for C1.

- [ ] **Step 2: Write the failing tests** in `tests/api/test_site_wire_kind.py`:

```python
"""The one wire-kind mapper (Contract 8): a site travels as "site"; the Head of ABM still reads
"web" for it (founder question Q1, recommendation (b))."""

from __future__ import annotations

import pytest

from clue_api.design_leg_wiring import design_document_card_fields, head_of_abm_doc_kind, wire_kind


@pytest.mark.parametrize(("doc_kind", "wire"), [("site", "site"), ("web", "web"), ("scene", "ad")])
def test_wire_kind(doc_kind: str, wire: str) -> None:
    assert wire_kind(doc_kind) == wire


def test_the_card_fields_say_site_for_a_site() -> None:
    fields = design_document_card_fields({"doc_kind": "site", "pages_json": None, "artifact_type": None})
    assert fields == {"kind": "site", "artifact_type": None, "width_px": None, "height_px": None}


def test_the_head_of_abm_reads_a_site_as_web() -> None:
    assert head_of_abm_doc_kind("site") == "web"
    assert head_of_abm_doc_kind("web") == "web"
    assert head_of_abm_doc_kind("scene") == "scene"
```

- [ ] **Step 3: Run them to see them fail.**

Run: `PLATFORM_PYTEST tests/api/test_site_wire_kind.py`
Expected: FAIL — `ImportError: cannot import name 'head_of_abm_doc_kind'`.

- [ ] **Step 4: Add the mapper and use it.** In `design_leg_wiring.py`, just above
  `def design_document_card_fields` (`:726`):

```python
def wire_kind(doc_kind: str) -> Literal["web", "ad", "site"]:
    """THE mapping from a document's ``doc_kind`` to the kind every artifact list and the composer
    send to the frontend (Contract 8): ``site`` and ``web`` as themselves, a scene as ``ad``."""
    if doc_kind == "site":
        return "site"
    return "web" if doc_kind == "web" else "ad"


def head_of_abm_doc_kind(doc_kind: str) -> str:
    """What the Head of ABM's own reads call a document's kind. It opens a website leg with
    doc_kind="web" and is unchanged by the Puck lane (ruling 2026-10-09), so a site reads as "web"
    to it (founder question Q1, recommendation (b))."""
    return "web" if doc_kind == "site" else doc_kind
```
  (add `Literal` to the module's `typing` import if it is not there). Then:
  - `design_leg_wiring.py:737` `"kind": "web" if document["doc_kind"] == "web" else "ad",` →
    `"kind": wire_kind(str(document["doc_kind"])),`
  - `chat/composer_context.py:784` `"kind": "web" if row["doc_kind"] == "web" else "ad",` →
    `"kind": wire_kind(str(row["doc_kind"])),` and add `wire_kind` to its
    `from clue_api.design_leg_wiring import ...` line (`:30`).
  - `chat/router.py:1415` `kind="web" if document["doc_kind"] == "web" else "ad",` →
    `kind=wire_kind(str(document["doc_kind"])),` and add `wire_kind` to the
    `from clue_api.design_leg_wiring import (` block (`:173`).

- [ ] **Step 5: The Head of ABM's reads (Q1).** With recommendation (b):
  - `artifact_read_tools.py:170` → `kind="web" if head_of_abm_doc_kind(str(document["doc_kind"])) == "web" else "ad",`
    and import `head_of_abm_doc_kind` beside `project_design_documents` (`:42`);
  - `project_library.py:438` → `"doc_kind": head_of_abm_doc_kind(str(row["doc_kind"])),` (import it
    from `clue_api.design_leg_wiring`, which the module already imports from);
  - `account_research_turn_wiring.py:257` → `"doc_kind": head_of_abm_doc_kind(str(document.get("doc_kind") or "")),`
    with `from clue_api.design_leg_wiring import head_of_abm_doc_kind` imported **inside the
    function that builds that body** (a module-level import risks a cycle through
    `agent_turn_wiring`, which both modules import).
  If the founder answers (a), use `kind=wire_kind(str(document["doc_kind"]))` at
  `artifact_read_tools.py:170`, leave the other two lines as they are, and drop
  `head_of_abm_doc_kind` and its test.

- [ ] **Step 6: Run the new tests and the feeds.**

Run: `PLATFORM_PYTEST tests/api/test_site_wire_kind.py` then `PLATFORM_PYTEST tests/api/test_design_artifact_feed_db.py` then `PLATFORM_PYTEST tests/api/test_frontend_read_artifacts_db.py` then `PLATFORM_PYTEST tests/api/test_artifact_read_tool_db.py` then `PLATFORM_PYTEST tests/api/test_project_library_db.py` then `PLATFORM_PYTEST tests/api/test_chat_composer_context.py`
Expected: all pass.

- [ ] **Step 7: Commit (its own commit — ordered after C1).**

```bash
git add platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/chat/composer_context.py platform/api/clue_api/chat/router.py platform/api/clue_api/artifact_read_tools.py platform/api/clue_api/project_library.py platform/api/clue_api/account_research_turn_wiring.py tests/api/test_site_wire_kind.py
git commit -m "platform: the one wire-kind mapper sends site (Contract 8; lands after Lane C's C1)"
```

## A2 — site write, undo, redo, versions and restore

### Task 11: The site inputs seams and the contract checks (shape, custody, the site-kit validator over JSON)

Contract 2: "Validation is contracts only: the site-kit validator run as a Node CLI over JSON,
with agent sections checked against their stored props JSON Schema." Contract 1: every image is a
blob of this workspace. The brand and the section modules come from Lane B (gap 1), so this task
also creates the two seams, and the renderer's shared types (the renderer itself is Task 17).

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/site_render.py` (types only, this task)
- Create: `subsystems/clue-design/apps/api/lumen_api/site_doc_inputs.py`
- Create: `subsystems/clue-design/apps/api/lumen_api/site_doc_validate.py`
- Modify: `.env.example` (after `LUMEN_CORE_HELPER_LOG=1`, `:740`) and
  `subsystems/clue-design/.env.example` (after `# LUMEN_TAILWIND_RUNTIME=`, `:378`)
- Create: `subsystems/clue-design/apps/api/tests/test_site_validation.py`

**Interfaces:**
- Consumes: `dist/validate-site.mjs` (Task 3); `DesignBlobStore.custody_states`,
  `CustodyState` (`lumen_api/design_store.py`).
- Produces:
  - `site_render.py`: `RENDER_TIMEOUT = "render.timeout"`, `OUTPUT_TOO_LARGE = "render.output_too_large"`,
    `SECTION_MODULE_MISSING = "render.section_module_missing"`, `RENDER_FAILED = "render.failed"`;
    `class SiteRenderError(Exception)` with `.code: str`, `.message: str`;
    `@dataclass(frozen=True) SectionModule(name: str, digest: str, module_js: str, css: str, props_schema: dict)`;
    `RenderedPage(route: str, html: str)`; `SiteRender(pages: list[RenderedPage], css: str, warnings: list[str])`;
    `site_kit_dist() -> Path`; `site_routes(site: dict) -> list[str]`;
    `pinned_modules(site: dict, sections: Sequence[SectionModule]) -> list[SectionModule]`.
  - `site_doc_inputs.py`: `SiteBrandLoader`, `SiteSectionLoader` (type aliases),
    `class SiteInputsUnavailable(Exception)` (`code = "site_inputs.unavailable"`),
    `brand_loader_not_composed(repo, blobs, document) -> dict`,
    `sections_not_stored(repo, blobs, agent_sections) -> list[SectionModule]`,
    `load_section_modules(loader, repo, blobs, site) -> list[SectionModule]`.
  - `site_doc_validate.py`: `SITE_KEYS`, `class SiteDocumentInvalid(Exception)` (`.errors: list[str]`),
    `class SiteValidatorUnavailable(Exception)` (`code = "site_validator.unavailable"`),
    `shape_errors(site, *, document_id) -> list[str]`,
    `prepare_site_for_write(document, site, *, allow_new_sections: bool) -> tuple[dict, list[str]]`,
    `site_asset_digests(site) -> list[str]`,
    `custody_errors(site, blobs) -> tuple[list[str], list[str]]` (errors, held `/asset-store/…` URLs),
    `run_site_validator(site, brand, *, section_schemas, site_images, node_bin="node") -> list[str]`,
    `check_site_document(site, *, document_id, brand, sections, blobs, node_bin="node") -> list[str]`.
  - Env `LUMEN_SITE_KIT_DIST` (default empty).

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_site_validation.py`:

```python
"""Contract checks on a site before it is stored (Wave 2 Lane A, Task 11)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from clue_design.storage import SOURCE_KEY_ASSET
from lumen_api.design_store import DesignBlobStore
from lumen_api.site_doc_inputs import (
    SiteInputsUnavailable,
    brand_loader_not_composed,
    load_section_modules,
    sections_not_stored,
)
from lumen_api.site_doc_validate import (
    SiteValidatorUnavailable,
    check_site_document,
    custody_errors,
    prepare_site_for_write,
    run_site_validator,
    shape_errors,
    site_asset_digests,
)
from lumen_api.site_render import SECTION_MODULE_MISSING, SectionModule, SiteRenderError
from site_kit_support import ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, png

QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "surface": {"type": "string", "enum": ["page", "card", "muted", "brandSubtle", "brand", "inverse"]},
        "quote": {"type": "string", "minLength": 1},
    },
    "required": ["id", "surface", "quote"],
    "additionalProperties": False,
}


def quote_module(module_js: str = "export const schema = null;\n") -> SectionModule:
    # The bytes are only hashed here; nothing in this suite runs them.
    return SectionModule(
        name="QuoteBand", digest=hashlib.sha256(module_js.encode()).hexdigest(),
        module_js=module_js, css="", props_schema=QUOTE_SCHEMA,
    )


@pytest.fixture()
def blobs(design_storage, workspace_id: str) -> DesignBlobStore:
    return DesignBlobStore(design_storage, workspace_id)


def test_shape_errors_name_each_problem() -> None:
    site = garner_site("doc_a")
    assert shape_errors(site, document_id="doc_a") == []
    assert shape_errors({**site, "id": "doc_b"}, document_id="doc_a") == ["site.id: must be this document's id 'doc_a'"]
    assert shape_errors({**site, "extra": 1}, document_id="doc_a") == [
        "site.extra: not a site field (the fields are id, title, theme, pages, shell, agent_sections)"
    ]
    bad_route = {**site, "pages": {**site["pages"], "/Pricing": {"root": {"props": {}}, "content": []}}}
    assert shape_errors(bad_route, document_id="doc_a") == [
        "site.pages['/Pricing']: a route is / or /<name> (lowercase letters, digits, dashes)"
    ]
    assert shape_errors({**site, "agent_sections": {"QuoteBand": "nope"}}, document_id="doc_a") == [
        "site.agent_sections: must map a section name to the sha256 of its compiled module"
    ]
    no_home = {**site, "pages": {"/analysis": site["pages"]["/analysis"]}}
    assert shape_errors(no_home, document_id="doc_a") == ['site.pages: must be an object of route -> page that includes "/"']


def test_a_manual_save_keeps_the_stored_theme_and_cannot_add_an_agent_section() -> None:
    stored = {"id": "doc_a", "scene": {**garner_site("doc_a"), "theme": {"brand_kit": {"id": "kit_1", "version": 2}}}}
    incoming = {**garner_site("doc_a"), "theme": {"brand_kit": {"id": "kit_other", "version": 9}}, "agent_sections": {"QuoteBand": "a" * 64}}
    prepared, errors = prepare_site_for_write(stored, incoming, allow_new_sections=False)
    assert prepared["theme"] == {"brand_kit": {"id": "kit_1", "version": 2}}
    assert errors == ["agent_sections.QuoteBand: a manual save cannot add or change an agent section"]
    _, agent_errors = prepare_site_for_write(stored, incoming, allow_new_sections=True)
    assert agent_errors == []


def test_custody_refuses_a_digest_this_workspace_does_not_hold(blobs: DesignBlobStore) -> None:
    data = png((1, 2, 3))
    blobs.register(data, media_type="image/png", source_key=SOURCE_KEY_ASSET)
    held, foreign = hashlib.sha256(data).hexdigest(), "f" * 64
    site = garner_site("doc_a")
    site["pages"]["/analysis"]["content"][0]["props"]["image"] = f"/asset-store/{held}"
    site["pages"]["/analysis"]["content"][2]["props"]["image"] = f"/asset-store/{foreign}"
    assert site_asset_digests(site) == [held, foreign]
    errors, urls = custody_errors(site, blobs)
    assert errors == [
        f"image /asset-store/{foreign} is not stored in this workspace; use one of the brand's assets or an image generated for this site"
    ]
    assert urls == [f"/asset-store/{held}"]


def test_the_site_kit_validator_runs_over_json() -> None:
    ensure_site_kit_dist()
    assert run_site_validator(garner_site("doc_a"), garner_brand(), section_schemas={}, site_images=[]) == []
    broken = garner_site("doc_a")
    broken["pages"]["/analysis"]["content"][0]["props"]["surface"] = "green"
    errors = run_site_validator(broken, garner_brand(), section_schemas={}, site_images=[])
    assert any(error.startswith("pages/analysis.content.0(what).surface") for error in errors), errors


def test_a_missing_validator_is_a_typed_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_SITE_KIT_DIST", str(tmp_path))
    with pytest.raises(SiteValidatorUnavailable):
        run_site_validator(garner_site("doc_a"), garner_brand(), section_schemas={}, site_images=[])


def test_check_site_document_checks_an_agent_section_against_its_stored_schema(blobs: DesignBlobStore) -> None:
    ensure_site_kit_dist()
    module = quote_module()
    site, brand = hold_site_images(garner_site("doc_a"), garner_brand(), blobs)
    site["agent_sections"] = {"QuoteBand": module.digest}
    site["pages"]["/"]["content"].append({"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": "Fewer surprises."}})
    assert check_site_document(site, document_id="doc_a", brand=brand, sections=[module], blobs=blobs) == []
    site["pages"]["/"]["content"][-1]["props"]["surface"] = "green"
    errors = check_site_document(site, document_id="doc_a", brand=brand, sections=[module], blobs=blobs)
    assert any(error.startswith("page.content.5(quote).surface") for error in errors), errors


def test_the_section_loader_is_checked_against_the_sites_own_pins() -> None:
    module = quote_module()
    site = {**garner_site("doc_a"), "agent_sections": {"QuoteBand": module.digest}}
    assert load_section_modules(lambda repo, blobs, pins: [module], None, None, site) == [module]
    with pytest.raises(SiteRenderError) as missing:
        load_section_modules(lambda repo, blobs, pins: [], None, None, site)
    assert missing.value.code == SECTION_MODULE_MISSING
    stale = SectionModule(name="QuoteBand", digest=module.digest, module_js=module.module_js + "// changed\n", css="", props_schema=QUOTE_SCHEMA)
    with pytest.raises(SiteRenderError) as tampered:
        load_section_modules(lambda repo, blobs, pins: [stale], None, None, site)
    assert tampered.value.code == SECTION_MODULE_MISSING and "stale" in tampered.value.message


def test_the_default_seams_refuse_until_lane_b_composes_them() -> None:
    assert sections_not_stored(None, None, {}) == []
    with pytest.raises(SiteRenderError) as refused:
        sections_not_stored(None, None, {"QuoteBand": "a" * 64})
    assert refused.value.code == SECTION_MODULE_MISSING
    with pytest.raises(SiteInputsUnavailable) as unavailable:
        brand_loader_not_composed(None, None, {"id": "doc_a"})
    assert unavailable.value.code == "site_inputs.unavailable"
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_validation.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'lumen_api.site_doc_inputs'`.

- [ ] **Step 3: Create `lumen_api/site_render.py` (types only for now).**

```python
"""The Puck site renderer (Wave 2 Lane A, Contract 3).

Every site render — publish, thumbnail, export, the agent's own preview — runs agent-written
section code inside ONE hardened headless Chromium page (D2, founder ruling 2026-10-11). Python and
Node never import or run it. This module starts with the shared types and paths (Task 11); the
render itself lands in Task 17.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]

RENDER_TIMEOUT = "render.timeout"
OUTPUT_TOO_LARGE = "render.output_too_large"
SECTION_MODULE_MISSING = "render.section_module_missing"
RENDER_FAILED = "render.failed"

#: The monorepo root — `subsystems/clue-design/apps/api/lumen_api/<this file>`.
_REPO_ROOT = Path(__file__).resolve().parents[5]
SITE_KIT_DIST_ENV = "LUMEN_SITE_KIT_DIST"
DEFAULT_SITE_KIT_DIST = _REPO_ROOT / "apps" / "frontend" / "packages" / "site-kit" / "dist"


class SiteRenderError(Exception):
    """A site render, a screenshot or a section-schema read that could not finish.

    ``code`` is one of the four contract codes above; ``message`` says why, in words a caller can
    show (a route's 409/502 body, or the agent's tool answer)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class SectionModule:
    """One compiled agent section as Lane B6's store returns it (Contract 4)."""

    name: str
    digest: str
    module_js: str
    css: str
    props_schema: JsonObject


@dataclass(frozen=True)
class RenderedPage:
    """One route of a rendered site: a whole HTML document, without the site's compiled CSS."""

    route: str
    html: str


@dataclass(frozen=True)
class SiteRender:
    pages: list[RenderedPage]
    css: str
    warnings: list[str] = field(default_factory=list)


def site_kit_dist() -> Path:
    """Where site-kit's built files are: ``LUMEN_SITE_KIT_DIST``, else the checkout's
    ``apps/frontend/packages/site-kit/dist`` (which ``npm run build -w @clue/site-kit`` writes and
    the backend image builds)."""
    override = os.environ.get(SITE_KIT_DIST_ENV, "").strip()
    return Path(override).expanduser() if override else DEFAULT_SITE_KIT_DIST


def site_routes(site: JsonObject) -> list[str]:
    """A site's routes in render order: "/" first, then the others alphabetically."""
    pages = site.get("pages") or {}
    return (["/"] if "/" in pages else []) + sorted(route for route in pages if route != "/")


def pinned_modules(site: JsonObject, sections: Sequence[SectionModule]) -> list[SectionModule]:
    """The modules the site's ``agent_sections`` pin, in pin order. Every pinned name must come
    with exactly its digest, and the module's bytes must hash to it: a module whose bytes changed is
    stale and is refused like a missing one, never rendered as a blank section (the master plan's Review focus 5)."""
    by_name = {module.name: module for module in sections}
    modules: list[SectionModule] = []
    for name, digest in (site.get("agent_sections") or {}).items():
        module = by_name.get(str(name))
        if module is None or module.digest != digest:
            raise SiteRenderError(SECTION_MODULE_MISSING, f"agent section {name} has no stored module {str(digest)[:12]}")
        if hashlib.sha256(module.module_js.encode("utf-8")).hexdigest() != digest:
            raise SiteRenderError(
                SECTION_MODULE_MISSING,
                f"agent section {name}'s stored module is stale (its bytes do not match {str(digest)[:12]})",
            )
        modules.append(module)
    return modules
```
  (add `import hashlib` and `from collections.abc import Sequence` to the module's imports).

- [ ] **Step 4: Create `lumen_api/site_doc_inputs.py`.**

```python
"""What a site check, render or publish needs besides the stored site: its brand and its
agent-section modules (Wave 2 Lane A; Lane B fills both).

Two seams, each a callable on ``app.state`` and on the governed tools' host:

* ``site_brand_loader(repo, blobs, document) -> BrandData`` — Lane B2 builds site-kit's
  ``BrandData`` from the document's brand kit (fonts and assets as ``/asset-store/<sha256>``).
  Until then the default refuses with ``site_inputs.unavailable``: a site cannot be checked,
  rendered or published without its brand.
* ``site_section_loader(repo, blobs, {name: digest}) -> [SectionModule]`` — Lane B6 reads the
  workspace's stored modules (Contract 4) and raises ``render.section_module_missing`` for a digest
  the workspace does not hold. Until then the default serves a site with no agent sections and
  refuses one that has them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .site_render import SECTION_MODULE_MISSING, SectionModule, SiteRenderError, pinned_modules

JsonObject = dict[str, Any]

SiteBrandLoader = Callable[[Any, Any, JsonObject], JsonObject]
SiteSectionLoader = Callable[[Any, Any, Mapping[str, str]], list[SectionModule]]


class SiteInputsUnavailable(Exception):
    """The site's brand (or another input Lane B owns) cannot be built in this process."""

    code = "site_inputs.unavailable"


def brand_loader_not_composed(repo: Any, blobs: Any, document: JsonObject) -> JsonObject:
    raise SiteInputsUnavailable(
        "the site's brand cannot be built in this process yet: the BrandData builder "
        "(Lane B2, app.state.site_brand_loader) is not composed"
    )


def sections_not_stored(repo: Any, blobs: Any, agent_sections: Mapping[str, str]) -> list[SectionModule]:
    if not agent_sections:
        return []
    raise SiteRenderError(
        SECTION_MODULE_MISSING,
        "no stored module for agent section(s) " + ", ".join(sorted(agent_sections))
        + " (the section store, Lane B6, is not composed)",
    )


def load_section_modules(loader: SiteSectionLoader, repo: Any, blobs: Any, site: JsonObject) -> list[SectionModule]:
    """The site's agent-section modules through ``loader``, checked against the site's own pins
    (``site_render.pinned_modules``)."""
    pins = {str(name): str(digest) for name, digest in (site.get("agent_sections") or {}).items()}
    return pinned_modules(site, loader(repo, blobs, pins))
```

- [ ] **Step 5: Create `lumen_api/site_doc_validate.py`.**

```python
"""Contract checks on a Puck site document before it is stored or published (Wave 2 Contract 2).

Contracts only (founder ruling 2026-10-08), three of them, in order:

1. **Shape** — the six stored keys, the document's own id, routes "/" or "/<name>", and the agent
   sections map (Contract 1).
2. **Custody** — every ``/asset-store/<sha256>`` the pages or the shell name is a blob of THIS
   workspace. The public byte route serves any workspace's blob by ruling (R-D4-7), so this is
   where a site is kept from showing another tenant's bytes.
3. **The site-kit validator** — ``node dist/validate-site.mjs`` with the brand, the site's held
   images and each agent section's STORED props JSON Schema. It never imports a section (D2).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from .design_store import CustodyState
from .site_render import SectionModule, site_kit_dist

JsonObject = dict[str, Any]

SITE_KEYS = ("id", "title", "theme", "pages", "shell", "agent_sections")
VALIDATOR_TIMEOUT_S = 20.0
_ROUTE = re.compile(r"^/(?:[a-z0-9][a-z0-9-]*)?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")


class SiteDocumentInvalid(Exception):
    """A site that fails its contract checks; ``errors`` are "where: message" lines."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors[:3]) or "the site is invalid")


class SiteValidatorUnavailable(Exception):
    """The site-kit validator could not run (not built, node missing, or it crashed)."""

    code = "site_validator.unavailable"


def shape_errors(site: Mapping[str, Any], *, document_id: str) -> list[str]:
    keys = set(site)
    errors = [f"site.{key}: missing" for key in SITE_KEYS if key not in keys]
    errors += [
        f"site.{key}: not a site field (the fields are {', '.join(SITE_KEYS)})"
        for key in sorted(keys - set(SITE_KEYS))
    ]
    if errors:
        return errors
    if site["id"] != document_id:
        errors.append(f"site.id: must be this document's id {document_id!r}")
    if not isinstance(site["title"], str) or not site["title"].strip():
        errors.append("site.title: must be a non-empty string")
    if not isinstance(site["theme"], dict):
        errors.append("site.theme: must be an object")
    pages = site["pages"]
    if not isinstance(pages, dict) or "/" not in pages:
        errors.append('site.pages: must be an object of route -> page that includes "/"')
    else:
        for route, page in pages.items():
            if not isinstance(route, str) or not _ROUTE.fullmatch(route):
                errors.append(f"site.pages[{route!r}]: a route is / or /<name> (lowercase letters, digits, dashes)")
            elif not isinstance(page, dict):
                errors.append(f"site.pages[{route!r}]: must be a page object")
    if site["shell"] is not None and not isinstance(site["shell"], dict):
        errors.append("site.shell: must be an object or null")
    sections = site["agent_sections"]
    if not isinstance(sections, dict) or any(
        not isinstance(name, str) or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
        for name, digest in sections.items()
    ):
        errors.append("site.agent_sections: must map a section name to the sha256 of its compiled module")
    return errors


def prepare_site_for_write(document: Mapping[str, Any], site: Any, *, allow_new_sections: bool) -> tuple[JsonObject, list[str]]:
    """The site as it will be stored, and what stops it.

    The theme is the platform's (the brand kit pinned at birth), so the stored theme always wins
    over whatever a client sent. Only the agent may add or change an agent section: its module is
    compiled and checked by Lane B6, which a manual save never goes through."""
    if not isinstance(site, dict):
        return {}, ["site: must be a JSON object"]
    stored = document["scene"]
    prepared: JsonObject = {**site, "theme": stored.get("theme") or {}}
    errors = shape_errors(prepared, document_id=str(document["id"]))
    if errors or allow_new_sections:
        return prepared, errors
    before = dict(stored.get("agent_sections") or {})
    for name, digest in prepared["agent_sections"].items():
        if before.get(name) != digest:
            errors.append(f"agent_sections.{name}: a manual save cannot add or change an agent section")
    return prepared, errors


def site_asset_digests(site: Mapping[str, Any]) -> list[str]:
    """Every /asset-store digest the site's pages and shell name, in order of first appearance."""
    named = json.dumps({"pages": site.get("pages"), "shell": site.get("shell")})
    return list(dict.fromkeys(_ASSET_REF.findall(named)))


def custody_errors(site: Mapping[str, Any], blobs: Any) -> tuple[list[str], list[str]]:
    """(errors for digests this workspace does not hold, the held ones as /asset-store URLs)."""
    digests = site_asset_digests(site)
    states = blobs.custody_states(digests) if digests else {}
    errors = [
        f"image /asset-store/{digest} is not stored in this workspace; use one of the brand's assets or an image generated for this site"
        for digest in digests
        if states.get(digest) is CustodyState.ABSENT
    ]
    held = [f"/asset-store/{digest}" for digest in digests if states.get(digest) is not CustodyState.ABSENT]
    return errors, held


def run_site_validator(
    site: Mapping[str, Any],
    brand: Mapping[str, Any],
    *,
    section_schemas: Mapping[str, JsonObject],
    site_images: Sequence[str],
    node_bin: str = "node",
) -> list[str]:
    """The site-kit validator's errors for this site (empty = valid). The held images ride as
    ``siteImages``, so an image this workspace holds passes wherever an image may go, the header's
    account logo included."""
    bundle = site_kit_dist() / "validate-site.mjs"
    if not bundle.is_file():
        raise SiteValidatorUnavailable(
            f"the site validator is not built ({bundle} is missing): run `npm run build -w @clue/site-kit` in apps/frontend"
        )
    payload = json.dumps(
        {
            "files": {"pages": site["pages"], "shell": site["shell"]},
            "brand": brand,
            "agentSectionSchemas": dict(section_schemas),
            "images": {"siteImages": list(site_images), "accountLogos": []},
        }
    )
    try:
        process = subprocess.run(
            [node_bin, str(bundle)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=VALIDATOR_TIMEOUT_S,
            env={"PATH": os.environ.get("PATH", "")},
            cwd=str(bundle.parent),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SiteValidatorUnavailable(f"the site validator did not run: {error}") from error
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()[:2000]
        raise SiteValidatorUnavailable(detail or f"the site validator exited {process.returncode}")
    try:
        result = json.loads(process.stdout)
    except ValueError as error:
        raise SiteValidatorUnavailable(f"the site validator printed no JSON: {process.stdout[:200]!r}") from error
    return [str(error) for error in result.get("errors") or []]


def check_site_document(
    site: Mapping[str, Any],
    *,
    document_id: str,
    brand: Mapping[str, Any],
    sections: Sequence[SectionModule],
    blobs: Any,
    node_bin: str = "node",
) -> list[str]:
    """Every contract error for ``site`` (empty = it may be stored or published)."""
    errors = shape_errors(site, document_id=document_id)
    if errors:
        return errors
    custody, held = custody_errors(site, blobs)
    return custody + run_site_validator(
        site,
        brand,
        section_schemas={module.name: module.props_schema for module in sections},
        site_images=held,
        node_bin=node_bin,
    )
```

- [ ] **Step 6: Document the setting in both env examples.** In `.env.example`, after the line
  `LUMEN_CORE_HELPER_LOG=1` (`:740`), and in `subsystems/clue-design/.env.example`, after the line
  `# LUMEN_TAILWIND_RUNTIME=` (`:378`), add (with a blank line before it):

```
# Puck sites (Wave 2): where site-kit's built files are (dist/validate-site.mjs, build-catalog.mjs,
# render-browser.js). Empty = the checkout's apps/frontend/packages/site-kit/dist, which
# `npm run build -w @clue/site-kit` (run from apps/frontend) writes and the backend image builds.
LUMEN_SITE_KIT_DIST=
```
  Add `LUMEN_SITE_KIT_DIST=` to the lane's `.env` as well (not committed).

- [ ] **Step 7: Run the tests.**

Run: `DESIGN_PYTEST test_site_validation.py`
Expected: all pass.

- [ ] **Step 8: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_render.py subsystems/clue-design/apps/api/lumen_api/site_doc_inputs.py subsystems/clue-design/apps/api/lumen_api/site_doc_validate.py subsystems/clue-design/apps/api/tests/test_site_validation.py .env.example subsystems/clue-design/.env.example
git commit -m "design API: site contract checks (shape, workspace custody, the site-kit validator over JSON) and the brand/section seams Lane B fills"
```

### Task 12: The governed site tools (`design_write_site`, `design_undo_site`, `design_redo_site`), in all four registries

Contract 2: history is `design_edit_envelope` with whole-site snapshots,
`operations = [{"kind": "replace_site", "site": new}]`,
`inverse_operations = [{"kind": "replace_site", "site": old}]`; one save or one agent turn is one
undo step; the cap is 50 (`clue_design/documents.py:51`, applied on push at `:635-637`). The DAL
write `update_web_document` (`documents.py:595-703`) reads only `web_doc["title"]`, so a site uses
it through a new store method that skips the WebDoc-shaped fragment and component validators
(`design_store.py:770-778`).

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (new `update_site_document`
  after `update_web_document`, `:750-794`)
- Create: `subsystems/clue-design/apps/api/lumen_api/toolbelt/site_documents.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/base.py` (`DesignToolHost`: two
  thunks)
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/wiring.py:256-283` (`design_tool_host`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/factory.py:87-93,127-132`
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:852-883` (app.state seams and host)
- Modify: `subsystems/clue-design/apps/api/tests/test_write_path_governance.py`
- Modify: `platform/api/clue_api/agent_registry_wiring.py:~423`
- Modify: `tests/api/test_agent_registry_wiring.py`, `tests/api/test_toolbelt_wiring.py`,
  `tests/agents/test_tool_authority_audit.py`
- Create: `subsystems/clue-design/apps/api/tests/test_site_tools.py`

**Interfaces:**
- Consumes: `check_site_document`, `prepare_site_for_write`, `SiteDocumentInvalid` (Task 11);
  `load_section_modules`, `SiteRenderError`, `SECTION_MODULE_MISSING` (Task 11).
- Produces:
  - `HybridRepository.update_site_document(document_id, site, *, intent, checkpoint_label, operations, inverse_operations, actor_kind, source, reverts_batch_id=None, reapplies_batch_id=None, expected_base_version=None) -> JsonObject`;
  - `toolbelt/site_documents.py`: `REPLACE_SITE = "replace_site"`,
    `replace_site_payload(operations: Any) -> JsonObject | None`,
    `class SiteHistoryEmpty(Exception)` (`.direction`),
    `class SiteHistoryRef(ToolOutput)` (`document_id, current_version, status, batch_id`),
    `write_site_document(*, repository, blobs, node_bin, brand_loader, section_loader, document_id, site, intent, checkpoint_label, actor_kind, source, expected_base_version) -> DocumentStateRef`,
    `step_site_history(*, repository, document_id, direction: Literal["undo", "redo"], expected_base_version: int) -> SiteHistoryRef`,
    tools `WriteSiteTool` (`design_write_site@1`), `UndoSiteTool` (`design_undo_site@1`),
    `RedoSiteTool` (`design_redo_site@1`), reason codes `site_undo_empty` / `site_redo_empty`;
  - `DesignToolHost.site_brand_loader` / `.site_section_loader` (thunks) and the same keyword
    arguments on `design_tool_host(...)`;
  - `app.state.site_brand_loader = brand_loader_not_composed`,
    `app.state.site_section_loader = sections_not_stored`.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_site_tools.py`:

```python
"""The governed site writes (Wave 2 Contract 2): an agent turn persists as ONE undoable write
through design_write_site, the same tool a manual save uses (REQ-20 parity)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.site_doc_validate import SiteDocumentInvalid
from site_kit_support import born_site, ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, install_site_inputs, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def test_an_agent_turn_persists_as_one_undoable_write(client: TestClient, workspace_id: str) -> None:
    site, brand = hold_site_images(garner_site("site_tool_agent"), garner_brand(), make_blob_store(client.app))
    store_site(born_site("site_tool_agent"))
    install_site_inputs(client.app, brand)
    result = client.app.state.design_tools.invoke(
        "design_write_site",
        {"document_id": "site_tool_agent", "site": site, "intent": "Site turn", "actor_kind": "agent", "source": "agent", "expected_base_version": 0},
        workspace_id=workspace_id,
        actor="agent",
    )
    assert result.references["current_version"] == 1
    repo = HybridRepository()
    document = repo.require_document("site_tool_agent")
    assert document["scene"]["pages"] == site["pages"]
    assert len(document["undo_stack"]) == 1 and document["redo_stack"] == []
    (envelope,) = repo.list_envelopes("site_tool_agent")
    assert envelope["operations"] == [{"kind": "replace_site", "site": document["scene"]}]
    assert envelope["inverse_operations"][0]["kind"] == "replace_site"
    assert envelope["inverse_operations"][0]["site"]["shell"] is None
    assert envelope["actor"]["kind"] == "agent"


def test_an_invalid_site_is_refused_and_nothing_is_written(client: TestClient, workspace_id: str) -> None:
    store_site(born_site("site_tool_bad"))
    install_site_inputs(client.app, garner_brand())
    broken = garner_site("site_tool_bad")
    broken["pages"]["/analysis"]["content"][0]["props"]["surface"] = "green"
    with pytest.raises(SiteDocumentInvalid) as refused:
        client.app.state.design_tools.invoke(
            "design_write_site",
            {"document_id": "site_tool_bad", "site": broken, "actor_kind": "agent", "source": "agent", "expected_base_version": 0},
            workspace_id=workspace_id,
            actor="agent",
        )
    assert any("surface" in error for error in refused.value.errors)
    assert HybridRepository().require_document("site_tool_bad")["current_version"] == 0
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_tools.py`
Expected: FAIL — `design_write_site` is not a registered tool.

- [ ] **Step 3: The store method.** In `design_store.py`, directly after `update_web_document`, add:

```python
    def update_site_document(
        self,
        document_id: str,
        site: JsonObject,
        *,
        intent: Optional[str],
        checkpoint_label: Optional[str],
        operations: List[JsonObject],
        inverse_operations: Optional[List[JsonObject]],
        actor_kind: str,
        source: str,
        reverts_batch_id: Optional[str] = None,
        reapplies_batch_id: Optional[str] = None,
        expected_base_version: Optional[int] = None,
    ) -> JsonObject:
        """The Puck site state write (Wave 2 Contract 2).

        The DAL's website write is kind-agnostic — it reads only the top-level title — so a site
        reuses it, with the same row lock, CAS, stack moves and 50-step cap. Unlike
        ``update_web_document`` it runs no WebDoc fragment or component validators: their page walk
        is WebDoc-shaped (a list of node maps) and means nothing for a site's dict of routes. The
        site's own checks (shape, custody, the site-kit validator) run in the tool before this."""
        return self._bridge._run(
            lambda conn: design_documents.update_web_document(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                web_doc=site,
                intent=intent,
                checkpoint_label=checkpoint_label,
                operations=operations,
                inverse_operations=inverse_operations,
                actor_kind=actor_kind,
                source=source,
                push_undo=True,
                reverts_batch_id=reverts_batch_id,
                reapplies_batch_id=reapplies_batch_id,
                expected_base_version=expected_base_version,
            )
        )
```

- [ ] **Step 4: Create `lumen_api/toolbelt/site_documents.py`.**

```python
"""Governed Puck site writes (Wave 2 Lane A, Contract 2).

Three tools over one store write (``HybridRepository.update_site_document``):

* ``design_write_site`` — a whole-site save. A manual save (route, ``actor="human"``,
  ``actor_kind="editor"``) and an agent turn's persist (Lane B5, ``actor="agent"``,
  ``actor_kind="agent"``) both go through it, so one save and one turn are each ONE undo step.
  It checks the site's contracts first (shape, custody, the site-kit validator) and refuses with
  ``SiteDocumentInvalid``; nothing is written then.
* ``design_undo_site`` / ``design_redo_site`` — one stack move. History is whole-site snapshots:
  a batch's ``operations`` carry the site it installed and its ``inverse_operations`` the site it
  replaced, so an undo reinstalls the inverse and a redo the forward snapshot, with no replay.

The CAS is ``expected_base_version``, checked under the row lock inside the write.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool
from .documents import DocumentStateRef, document_failures

__all__ = [
    "REPLACE_SITE",
    "RedoSiteTool",
    "SiteHistoryEmpty",
    "SiteHistoryInput",
    "SiteHistoryRef",
    "UndoSiteTool",
    "WriteSiteInput",
    "WriteSiteTool",
    "replace_site_payload",
    "step_site_history",
    "write_site_document",
]

JsonObject = dict[str, Any]
REPLACE_SITE = "replace_site"


def replace_site_payload(operations: Any) -> JsonObject | None:
    """The site a ``[{"kind": "replace_site", "site": …}]`` batch carries, else None."""
    if (
        isinstance(operations, list)
        and len(operations) == 1
        and isinstance(operations[0], dict)
        and operations[0].get("kind") == REPLACE_SITE
        and isinstance(operations[0].get("site"), dict)
    ):
        return operations[0]["site"]
    return None


class SiteHistoryEmpty(Exception):
    """Nothing to undo (or redo) on this site."""

    def __init__(self, direction: str) -> None:
        super().__init__(f"no {'undoable' if direction == 'undo' else 'redoable'} batches in document history")
        self.direction = direction


class SiteHistoryRef(ToolOutput):
    document_id: str
    current_version: int
    status: str
    #: The batch this step moved between the undo and redo stacks.
    batch_id: str


def write_site_document(
    *,
    repository: Any,
    blobs: Any,
    node_bin: str,
    brand_loader: Any,
    section_loader: Any,
    document_id: str,
    site: Any,
    intent: str | None,
    checkpoint_label: str | None,
    actor_kind: str,
    source: str,
    expected_base_version: int,
) -> DocumentStateRef:
    """THE site save: check the contracts, then write one whole-site snapshot."""
    from ..site_doc_inputs import load_section_modules
    from ..site_doc_validate import SiteDocumentInvalid, check_site_document, prepare_site_for_write
    from ..site_render import SECTION_MODULE_MISSING, SiteRenderError

    document = repository.require_document(document_id)
    prepared, errors = prepare_site_for_write(document, site, allow_new_sections=actor_kind == "agent")
    if errors:
        raise SiteDocumentInvalid(errors)
    try:
        sections = load_section_modules(section_loader, repository, blobs, prepared)
    except SiteRenderError as error:
        if error.code == SECTION_MODULE_MISSING:
            raise SiteDocumentInvalid([f"agent_sections: {error.message}"]) from error
        raise
    errors = check_site_document(
        prepared,
        document_id=document_id,
        brand=brand_loader(repository, blobs, document),
        sections=sections,
        blobs=blobs,
        node_bin=node_bin,
    )
    if errors:
        raise SiteDocumentInvalid(errors)
    updated = repository.update_site_document(
        document_id,
        prepared,
        intent=intent,
        checkpoint_label=checkpoint_label,
        operations=[{"kind": REPLACE_SITE, "site": prepared}],
        inverse_operations=[{"kind": REPLACE_SITE, "site": document["scene"]}],
        actor_kind=actor_kind,
        source=source,
        expected_base_version=expected_base_version,
    )
    return DocumentStateRef(
        document_id=updated["id"], current_version=updated["current_version"], status=updated["status"]
    )


def step_site_history(
    *, repository: Any, document_id: str, direction: Literal["undo", "redo"], expected_base_version: int
) -> SiteHistoryRef:
    """One undo or redo: reinstall the snapshot the stack's top batch names."""
    document = repository.require_document(document_id)
    stack = list(document.get("undo_stack" if direction == "undo" else "redo_stack") or [])
    if not stack:
        raise SiteHistoryEmpty(direction)
    target = repository.require_envelope(document_id, stack[-1])
    restored = replace_site_payload(target["inverse_operations"] if direction == "undo" else target["operations"])
    if restored is None:
        raise SiteHistoryEmpty(direction)
    moves = {"reverts_batch_id": target["batch_id"]} if direction == "undo" else {"reapplies_batch_id": target["batch_id"]}
    updated = repository.update_site_document(
        document_id,
        restored,
        intent=f"{direction}:{target['intent'] or target['batch_id']}",
        checkpoint_label="Undo" if direction == "undo" else "Redo",
        operations=[{"kind": REPLACE_SITE, "site": restored}],
        inverse_operations=[{"kind": REPLACE_SITE, "site": document["scene"]}],
        actor_kind="system",
        source="system",
        expected_base_version=expected_base_version,
        **moves,
    )
    return SiteHistoryRef(
        document_id=updated["id"], current_version=updated["current_version"], status=updated["status"], batch_id=target["batch_id"]
    )


class WriteSiteInput(ToolInput):
    document_id: str
    #: The whole site document (Contract 1). The stored theme always wins over the one sent.
    site: JsonObject
    intent: str | None = None
    checkpoint_label: str | None = None
    #: ``editor`` for a manual save, ``agent`` for a site turn's persist (Lane B5).
    actor_kind: str = "editor"
    source: str = "editor"
    #: The version the save was made from. Required: a turn taking minutes must never clobber a save.
    expected_base_version: int


class SiteHistoryInput(ToolInput):
    document_id: str
    expected_base_version: int


_REPLAY = ReplaySafety(
    policy=ReplayPolicy.OPERATION_IDEMPOTENT,
    durable_identity="workspace + document_id + ToolContext.operation_id",
    operation_id_required=True,
    external_boundary=ExternalReplayBoundary.NONE,
    notes=(
        "each execution bumps current_version and appends an envelope, so a blind retry is a "
        "second write; expected_base_version is checked under the row lock inside the write "
        "transaction, so a stale retry raises the typed version conflict instead"
    ),
)


class WriteSiteTool(DesignTool):
    """Save a whole Puck site document as one undoable step."""

    name = "design_write_site"
    version = "1"
    model_description = (
        "Save a whole Puck site document under its base version after its contract checks, "
        "appending one undoable history step."
    )
    input_model: ClassVar[type[ToolInput]] = WriteSiteInput
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    replay: ClassVar[ReplaySafety] = _REPLAY
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "actor_kind", "source", "expected_base_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, WriteSiteInput)
        return document_failures(
            self.host.repository(ctx.workspace_id), inputs.document_id, kind="site", draft=True, action="save the site"
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, WriteSiteInput)
        return write_site_document(
            repository=self.host.repository(ctx.workspace_id),
            blobs=self.host.blobs(ctx.workspace_id),
            node_bin=self.host.need("web_export_node_bin"),
            brand_loader=self.host.need("site_brand_loader"),
            section_loader=self.host.need("site_section_loader"),
            document_id=inputs.document_id,
            site=inputs.site,
            intent=inputs.intent,
            checkpoint_label=inputs.checkpoint_label,
            actor_kind=inputs.actor_kind,
            source=inputs.source,
            expected_base_version=inputs.expected_base_version,
        )


class UndoSiteTool(DesignTool):
    """Undo the most recent step on a Puck site document."""

    name = "design_undo_site"
    version = "1"
    model_description = "Undo the most recent step on a Puck site document, reinstalling the site it replaced."
    input_model: ClassVar[type[ToolInput]] = SiteHistoryInput
    output_model: ClassVar[type[ToolOutput]] = SiteHistoryRef
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    replay: ClassVar[ReplaySafety] = _REPLAY
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "expected_base_version")
    )
    _direction: ClassVar[Literal["undo", "redo"]] = "undo"

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SiteHistoryInput)
        repository = self.host.repository(ctx.workspace_id)
        failures = document_failures(repository, inputs.document_id, kind="site", draft=True, action=self._direction)
        if failures:
            return failures
        document = repository.require_document(inputs.document_id)
        if not (document.get("undo_stack" if self._direction == "undo" else "redo_stack") or []):
            return (
                PreconditionFailure(
                    reason_code=f"site_{self._direction}_empty",
                    message=str(SiteHistoryEmpty(self._direction)),
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SiteHistoryInput)
        return step_site_history(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            direction=self._direction,
            expected_base_version=inputs.expected_base_version,
        )


class RedoSiteTool(UndoSiteTool):
    """Redo the most recently undone step on a Puck site document."""

    name = "design_redo_site"
    version = "1"
    model_description = "Redo the most recently undone step on a Puck site document, reinstalling the site it had installed."
    _direction: ClassVar[Literal["undo", "redo"]] = "redo"
```

- [ ] **Step 5: The host thunks.** In `toolbelt/base.py`, add two fields to `DesignToolHost`
  after `compile_fn`:

```python
    #: Puck sites (Wave 2): the BrandData builder and the agent-section store (lumen_api.
    #: site_doc_inputs). Lane B2/B6 compose the real ones; the defaults refuse honestly.
    site_brand_loader: Callable[[], Callable[..., Any]] | None = None
    site_section_loader: Callable[[], Callable[..., Any]] | None = None
```
  In `toolbelt/wiring.py`, add the same two keyword arguments to `design_tool_host` (each
  `Callable[[], Callable[..., Any]] | None = None`, after `compile_fn`) and pass them to
  `DesignToolHost(...)` as `site_brand_loader=site_brand_loader, site_section_loader=site_section_loader,`.

- [ ] **Step 6: The app.state seams.** In `main.py`:
  - add to the imports: `from .site_doc_inputs import SiteInputsUnavailable, brand_loader_not_composed, sections_not_stored`
  - after `app.state.web_export_node_bin = "node"` (`:852`), add:

```python
    # Puck sites (Wave 2, Lane A gap 1): the site's BrandData builder and its agent-section store.
    # Lane B2 and B6 replace these two assignments; until then a site check, render or publish that
    # needs them refuses with a typed reason instead of guessing (lumen_api.site_doc_inputs).
    app.state.site_brand_loader = brand_loader_not_composed
    app.state.site_section_loader = sections_not_stored
```
  - in the `design_tool_host(...)` call (`:860-877`), after `compile_fn=lambda: compile_custom_component,` add:

```python
            site_brand_loader=lambda: app.state.site_brand_loader,
            site_section_loader=lambda: app.state.site_section_loader,
```

- [ ] **Step 7: Register the tools.** In `toolbelt/factory.py`, add
  `from .site_documents import RedoSiteTool, UndoSiteTool, WriteSiteTool` and, after
  `RedoWebDocumentTool,` in `DESIGN_TOOL_TYPES`, add:

```python
    # Wave 2 Lane A — Puck site documents (Contract 2).
    WriteSiteTool,
    UndoSiteTool,
    RedoSiteTool,
```

- [ ] **Step 8: The design-side governance pins.** In `apps/api/tests/test_write_path_governance.py`:
  - in `_GOVERNED`, after `"create_web_template": …`, add:

```python
    # --- Wave 2 Lane A: Puck site documents ------------------------------------------------
    "update_site_document": ("method", ("lumen_api/design_store.py",)),
    "write_site_document": ("function", ()),
    "step_site_history": ("function", ()),
```
  - in `test_every_governed_name_actually_exists`, add
    `from lumen_api.toolbelt import site_documents as toolbelt_site_documents` and add
    `toolbelt_site_documents,` to the tuple of modules searched;
  - in `test_design_tool_names_are_stable`, after `"design_redo_web_document",` add
    `"design_write_site", "design_undo_site", "design_redo_site",` and after
    `"design_ingest_ad_assets",` add `"design_enrich_assets",` (it was registered without a pin —
    the baseline failure noted in "Before you start").

- [ ] **Step 9: The platform's authority map and its tests.** The three tools are registered
  **ungranted** (controller ruling R6, 2026-10-11). Granting them to `AgentRole.DESIGN` would make
  `build_agent_profile_registry` refuse to compose ("profile 'design' differs from reviewed
  authority", `agent_registry_wiring.py:1027-1040`) until a design profile pinned them, and that
  registry is built at platform start-up (`agent_platform_wiring.py:474`), so the platform API would
  not boot. No model names these tools: the editor's routes call them as a person, and the site
  turn's executor (Lane B Task 12) calls `design_write_site` from code on the agent's behalf. That
  is the ad-assets lane's footing ("machine-invoked, merely unplanned by any model",
  `agent_registry_wiring.py:446-450`); the design API's `run_design_tool` never consults C6 grants
  (the ABM batch already calls the ungranted `design_set_web_noindex`, `main.py:5680`). Granting
  them later is a reviewed design profile bump. Lane A mints **no** design profile.
  - `platform/api/clue_api/agent_registry_wiring.py`: after `"design_redo_web_document": (AgentRole.DESIGN,),` add

```python
    # Wave 2 Lane A (Contract 2): the Puck site writes. Registered UNGRANTED, on the ad-assets
    # lane's footing: no model names them. The editor's site routes invoke them as the person, and
    # the site turn's executor persists the agent's finished request through design_write_site
    # from code. Granting any of them to a role later is a reviewed design profile bump.
    "design_write_site": (),
    "design_undo_site": (),
    "design_redo_site": (),
```
  - `tests/api/test_agent_registry_wiring.py`: do **not** add them to the `design_addresses` set;
    change **both** `assert len(by_address) == 169` lines to `== 172` with the comment
    `# + design_write_site@1, design_undo_site@1, design_redo_site@1, ungranted (Wave 2 Lane A)`.
  - `tests/api/test_toolbelt_wiring.py`: in `_MATRIX`, after the `"design_redo_web_document"` entry, add

```python
    "design_write_site": ("precondition", ("design_runtime_not_configured",)),
    "design_undo_site": ("precondition", ("design_runtime_not_configured",)),
    "design_redo_site": ("precondition", ("design_runtime_not_configured",)),
```
    in `_bodies()`, after the `"design_redo_web_document": {…}` entry, add

```python
        # Wave 2 Lane A — Puck site documents.
        "design_write_site": {
            "document_id": "doc_matrix",
            "site": {"id": "doc_matrix", "title": "Matrix"},
            "expected_base_version": 1,
        },
        "design_undo_site": {"document_id": "doc_matrix", "expected_base_version": 1},
        "design_redo_site": {"document_id": "doc_matrix", "expected_base_version": 1},
```
    and change both `assert len(registry.names()) == 144` to `== 147` and both
    `assert len(registry) == 169` to `== 172` (comment: `# Wave 2 Lane A: three site writes (+3 names, +3 addresses)`).
  - `tests/agents/test_tool_authority_audit.py:170`: `assert len(C6_AGENT_TOOL_AUTHORITY) == 144` → `== 147`
    (comment: `# Wave 2 Lane A adds the three Puck site writes, ungranted (144 -> 147).`).
  - `tests/agents/test_tool_authority_audit.py:286`: after the `AD_ASSETS_LANE` set and its two
    asserts, add

```python
    # Wave 2 Lane A (controller ruling R6, 2026-10-11): the Puck site writes are registered
    # ungranted for the ad-assets lane's reason: the editor's routes and the site turn's executor
    # invoke them, and no model names them. Granting one later is a reviewed profile bump.
    SITE_DOCUMENT_LANE = {"design_write_site", "design_undo_site", "design_redo_site"}
    assert set(design_grants) >= SITE_DOCUMENT_LANE
    assert all(design_grants[name] == () for name in SITE_DOCUMENT_LANE)
```
    and change the DESIGN-only assert's exclusion (`:313`) from
    `if name not in AD_ASSETS_LANE | HUMAN_ONLY_DESIGN` to
    `if name not in AD_ASSETS_LANE | HUMAN_ONLY_DESIGN | SITE_DOCUMENT_LANE`.
  If Lane B's B0 (`read_cited_claims@1`) landed first, start from its numbers and add 3.

- [ ] **Step 10: Run the tests.**

Run: `DESIGN_PYTEST test_site_tools.py` then `DESIGN_PYTEST test_write_path_governance.py` then
`PLATFORM_PYTEST tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py tests/api/test_agent_registry_wiring.py`
Expected: `test_site_tools.py` passes; the governance file has exactly **1 failure** left (the
pre-existing `asset_enrichment.py:51` one); the platform files pass, including
`test_out_of_order_matrix` on `clue_trenton_wave1`.

- [ ] **Step 11: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/design_store.py subsystems/clue-design/apps/api/lumen_api/toolbelt subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_write_path_governance.py subsystems/clue-design/apps/api/tests/test_site_tools.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_agent_registry_wiring.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py
git commit -m "design: governed site writes (design_write_site/undo/redo) with whole-site snapshot history, in all four registries"
```

### Task 13: The site routes — save, undo, redo, versions, restore

Contract 2's table, in `lumen_api/main.py`'s style (nested in `create_app`, gates first, the
governed tool for the write, typed bodies on refusal). Manual writes refuse while a design run
drives the document (`_refuse_if_agent_running`, `main.py:8060-8084`, kind-agnostic through
`clue_design.runs.active_run_for_document`), unlike the web routes, by the 2026-10-11 ruling.

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/models.py` (two request models after
  `WebOperationsRequest`, `:198-206`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (imports; routes after the web redo
  route, before `@app.get("/documents/{document_id}/web/theme")`, `:4517`)
- Create: `subsystems/clue-design/apps/api/tests/test_site_write_routes.py`

**Interfaces:**
- Consumes: the three tools, `SiteHistoryEmpty`, `replace_site_payload` (Task 12);
  `SiteDocumentInvalid`, `SiteValidatorUnavailable` (Task 11); `SiteInputsUnavailable`;
  `require_site_document` (Task 8).
- Produces (Lane C's contract):
  - `PUT /documents/{id}/site` body `{site, base_version, intent?}` → 200
    `{schema_version: 1, document: {id, current_version, doc_kind: "site"}}`; 409
    `edits.base_version_mismatch` (+`current_version`), 422 `site.invalid` (+`errors[]`), 409
    `document.agent_run_active` (+`run_id`), 409 `document.kind_unsupported`, 409
    `document.finalized`, 503 `site_inputs.unavailable` / `site_validator.unavailable`;
  - `POST /documents/{id}/site/undo` · `/redo` body `{base_version}` → 200
    `{schema_version: 1, document, undone_batch_id}` · `{…, redone_batch_id}`; 409 `undo.empty` ·
    `redo.empty`, 409 `edits.base_version_mismatch`;
  - `GET /documents/{id}/site/versions?limit=50` (1–200) → 200
    `{schema_version: 1, versions: [{batch_id, version, actor_kind, intent, created_at}]}` newest first;
  - `POST /documents/{id}/site/versions/{batch_id}/restore` body `{base_version}` → 200
    `{schema_version: 1, document}`; 404 `version.not_found`. The restore is one undoable write.
  - `GET /documents/{id}/site/brand` → 200 `{schema_version: 1, brand: BrandData}` (every `file`
    is `/asset-store/<sha256>`), from `app.state.site_brand_loader`; 503 `site_inputs.unavailable`
    until Lane B2 composes the builder; 409 `document.kind_unsupported` (controller ruling R3: the
    editor frame's `init` needs it and no other route served it).
  - models `SiteWriteRequest(site: JsonObject, base_version: int, intent: Optional[str] = None)`,
    `SiteHistoryRequest(base_version: int)`.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_site_write_routes.py`:

```python
"""The site routes (Wave 2 Contract 2): save, undo, redo, versions and restore, with the
refusals a second writer meets."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from py_lumen_config import settings

from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from site_kit_support import born_site, ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, install_site_inputs, store_site
from test_agent_run_write_lock import finish_run, start_leg_run

DOC = "site_routes"


@pytest.fixture(autouse=True)
def _no_embedded_fleet_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # The write-lock test seeds a running run row directly; nothing here offers fleet work.
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


@pytest.fixture()
def site_a(client: TestClient) -> dict:
    site, brand = hold_site_images(garner_site(DOC), garner_brand(), make_blob_store(client.app))
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand)
    return site


def with_heading(site: dict, heading: str) -> dict:
    changed = copy.deepcopy(site)
    changed["pages"]["/analysis"]["content"][3]["props"]["heading"] = heading  # CtaBand "cta"
    return changed


def save(client: TestClient, site: dict, base_version: int):
    return client.put(f"/documents/{DOC}/site", json={"site": site, "base_version": base_version})


def stored_site(client: TestClient) -> dict:
    return client.get(f"/documents/{DOC}").json()["scene"]


def test_a_save_writes_one_version(client: TestClient, site_a: dict) -> None:
    response = save(client, site_a, 0)
    assert response.status_code == 200, response.text
    assert response.json() == {"schema_version": 1, "document": {"id": DOC, "current_version": 1, "doc_kind": "site"}}
    assert stored_site(client)["pages"] == site_a["pages"]


def test_a_stale_save_is_refused_with_the_current_version(client: TestClient, site_a: dict) -> None:
    assert save(client, site_a, 0).status_code == 200
    stale = save(client, with_heading(site_a, "Second tab"), 0)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "edits.base_version_mismatch"
    assert stale.json()["detail"]["current_version"] == 1
    assert stored_site(client)["pages"] == site_a["pages"]


def test_an_invalid_site_is_refused_with_its_errors(client: TestClient, site_a: dict) -> None:
    broken = copy.deepcopy(site_a)
    broken["pages"]["/analysis"]["content"][0]["props"]["surface"] = "green"
    response = save(client, broken, 0)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "site.invalid"
    assert any("surface" in error for error in response.json()["detail"]["errors"])


def test_an_image_this_workspace_does_not_hold_is_refused_by_name(client: TestClient, site_a: dict) -> None:
    foreign = copy.deepcopy(site_a)
    foreign["pages"]["/analysis"]["content"][0]["props"]["image"] = "/asset-store/" + "e" * 64
    response = save(client, foreign, 0)
    assert response.status_code == 422
    assert f"image /asset-store/{'e' * 64} is not stored in this workspace" in " ".join(response.json()["detail"]["errors"])
    assert HybridRepository().require_document(DOC)["current_version"] == 0


def test_a_save_is_refused_while_a_site_turn_runs(client: TestClient, site_a: dict) -> None:
    repo = HybridRepository()
    run_id = start_leg_run(repo, DOC)
    try:
        response = save(client, site_a, 0)
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "document.agent_run_active", "run_id": run_id}
        undo = client.post(f"/documents/{DOC}/site/undo", json={"base_version": 0})
        assert undo.json()["detail"]["code"] == "document.agent_run_active"
    finally:
        finish_run(repo, run_id)
    assert save(client, site_a, 0).status_code == 200


def test_a_web_document_is_not_a_site(client: TestClient, site_a: dict) -> None:
    web = client.post("/documents", json={"doc_kind": "web", "title": "W"}).json()["document"]
    response = client.put(f"/documents/{web['id']}/site", json={"site": site_a, "base_version": 0})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "document.kind_unsupported"


def test_without_a_brand_builder_a_save_is_a_typed_503(client: TestClient, site_a: dict) -> None:
    from lumen_api.site_doc_inputs import brand_loader_not_composed

    client.app.state.site_brand_loader = brand_loader_not_composed
    response = save(client, site_a, 0)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "site_inputs.unavailable"
    brand = client.get(f"/documents/{DOC}/site/brand")
    assert brand.status_code == 503 and brand.json()["detail"]["code"] == "site_inputs.unavailable"


def test_the_brand_read_serves_the_composed_builders_brand(client: TestClient, site_a: dict) -> None:
    """Controller ruling R3: the editor frame's BrandData comes from the same seam the save uses."""
    seen: list[str] = []

    def builder(repo, blobs, document):
        seen.append(document["id"])
        return {"slug": "garner", "kit": {}, "fonts": [], "assets": {}, "clones": {}, "measured": None}

    client.app.state.site_brand_loader = builder
    response = client.get(f"/documents/{DOC}/site/brand")
    assert response.status_code == 200
    assert response.json() == {"schema_version": 1, "brand": builder(None, None, {"id": DOC})}
    assert seen[0] == DOC


def test_undo_and_redo_walk_the_snapshots_exactly(client: TestClient, site_a: dict) -> None:
    site_b = with_heading(site_a, "The analysis, free")
    assert save(client, site_a, 0).status_code == 200
    assert save(client, site_b, 1).status_code == 200
    undone = client.post(f"/documents/{DOC}/site/undo", json={"base_version": 2})
    assert undone.status_code == 200, undone.text
    assert undone.json()["document"]["current_version"] == 3 and undone.json()["undone_batch_id"]
    assert stored_site(client)["pages"] == site_a["pages"]
    assert client.post(f"/documents/{DOC}/site/undo", json={"base_version": 3}).status_code == 200
    assert stored_site(client)["shell"] is None  # back to the born site
    empty = client.post(f"/documents/{DOC}/site/undo", json={"base_version": 4})
    assert empty.status_code == 409 and empty.json()["detail"]["code"] == "undo.empty"
    redone = client.post(f"/documents/{DOC}/site/redo", json={"base_version": 4})
    assert redone.status_code == 200 and redone.json()["redone_batch_id"]
    assert stored_site(client)["pages"] == site_a["pages"]
    assert save(client, with_heading(site_a, "A new save"), 5).status_code == 200
    gone = client.post(f"/documents/{DOC}/site/redo", json={"base_version": 6})
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "redo.empty"


def test_versions_list_newest_first_and_a_restore_is_undoable(client: TestClient, site_a: dict) -> None:
    site_b = with_heading(site_a, "The analysis, free")
    assert save(client, site_a, 0).status_code == 200
    assert save(client, site_b, 1).status_code == 200
    versions = client.get(f"/documents/{DOC}/site/versions").json()["versions"]
    assert [entry["version"] for entry in versions] == [2, 1]
    assert {entry["actor_kind"] for entry in versions} == {"editor"}
    first = versions[1]["batch_id"]
    restored = client.post(f"/documents/{DOC}/site/versions/{first}/restore", json={"base_version": 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()["document"]["current_version"] == 3
    assert stored_site(client)["pages"] == site_a["pages"]
    assert client.post(f"/documents/{DOC}/site/undo", json={"base_version": 3}).status_code == 200
    assert stored_site(client)["pages"] == site_b["pages"]
    missing = client.post(f"/documents/{DOC}/site/versions/batch_nope/restore", json={"base_version": 4})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "version.not_found"
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_write_routes.py`
Expected: FAIL — `PUT /documents/{id}/site` answers 405 (no route).

- [ ] **Step 3: The request models.** In `models.py`, after `WebOperationsRequest`, add:

```python
class SiteWriteRequest(BaseModel):
    """A save of a whole Puck site document (Wave 2 Contract 2): the site JSON, the version it was
    edited from (required — a stale tab must never overwrite a newer save), and a history label."""

    site: JsonObject
    base_version: int
    intent: Optional[str] = None


class SiteHistoryRequest(BaseModel):
    """An undo, a redo or a restore of a Puck site, from the version the caller is looking at."""

    base_version: int
```
  and add `SiteHistoryRequest, SiteWriteRequest,` to `main.py`'s `from .models import (` block.

- [ ] **Step 4: The routes.** In `main.py`, add to the imports

```python
from .site_doc_validate import SiteDocumentInvalid, SiteValidatorUnavailable
from .toolbelt.site_documents import SiteHistoryEmpty, replace_site_payload
```
  (`SiteInputsUnavailable` is already imported, Task 12), and insert, right before
  `@app.get("/documents/{document_id}/web/theme")`:

```python
    # --- Puck site documents (Wave 2 Lane A, Contract 2) --------------------------------------- #

    def _site_refusal(error: Exception) -> HTTPException:
        """The typed body for each way a site write can be refused before it lands."""
        if isinstance(error, SiteDocumentInvalid):
            return HTTPException(
                status_code=422,
                detail={"code": "site.invalid", "message": "the site does not pass its contract checks", "errors": error.errors},
            )
        if isinstance(error, (SiteInputsUnavailable, SiteValidatorUnavailable)):
            return HTTPException(status_code=503, detail={"code": error.code, "message": str(error)})
        raise TypeError(f"not a site refusal: {error!r}")

    def _site_history_refusals(document_id: str) -> Dict[str, Any]:
        return {
            **_document_refusals(document_id),
            "site_undo_empty": lambda message: HTTPException(status_code=409, detail={"code": "undo.empty", "message": message}),
            "site_redo_empty": lambda message: HTTPException(status_code=409, detail={"code": "redo.empty", "message": message}),
        }

    def _site_document_ref(repo: HybridRepository, document_id: str) -> JsonObject:
        updated = repo.require_document(document_id)
        return {"id": updated["id"], "current_version": updated["current_version"], "doc_kind": "site"}

    def _guard_site_write(repo: HybridRepository, document_id: str, base_version: int, action: str) -> JsonObject:
        document = require_document(repo, document_id)
        require_site_document(document)
        require_draft_document(document, action)
        # Ruling 2026-10-11: no manual site write while a design run drives this document.
        _refuse_if_agent_running(document_id, repo)
        require_base_version(document, base_version)
        return document

    def _write_site(repo: HybridRepository, document_id: str, *, site: Any, intent: str, checkpoint_label: str, base_version: int) -> None:
        try:
            run_design_tool(
                "design_write_site",
                {
                    "document_id": document_id,
                    "site": site,
                    "intent": intent,
                    "checkpoint_label": checkpoint_label,
                    "actor_kind": "editor",
                    "source": "editor",
                    "expected_base_version": base_version,
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
        except WebDocumentVersionConflict as conflict:
            raise _base_version_conflict(conflict) from conflict
        except (SiteDocumentInvalid, SiteInputsUnavailable, SiteValidatorUnavailable) as error:
            raise _site_refusal(error) from error

    @app.put("/documents/{document_id}/site")
    def put_site_document(
        document_id: str, payload: SiteWriteRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """One save of the whole site: one undoable step (Contract 2)."""
        _guard_site_write(repo, document_id, payload.base_version, "save the site")
        _write_site(
            repo,
            document_id,
            site=payload.site,
            intent=payload.intent or "Manual edit",
            checkpoint_label="Manual edit",
            base_version=payload.base_version,
        )
        return {"schema_version": 1, "document": _site_document_ref(repo, document_id)}

    def _step_site(repo: HybridRepository, document_id: str, base_version: int, direction: str) -> JsonObject:
        document = _guard_site_write(repo, document_id, base_version, direction)
        if not (document.get("undo_stack" if direction == "undo" else "redo_stack") or []):
            raise HTTPException(
                status_code=409,
                detail={"code": f"{direction}.empty", "message": str(SiteHistoryEmpty(direction))},
            )
        try:
            refs = run_design_tool(
                f"design_{direction}_site",
                {"document_id": document_id, "expected_base_version": base_version},
                workspace_id=store_workspace_id(repo),
                refusals=_site_history_refusals(document_id),
            )
        except WebDocumentVersionConflict as conflict:
            raise _base_version_conflict(conflict) from conflict
        except SiteHistoryEmpty as error:
            raise HTTPException(status_code=409, detail={"code": f"{direction}.empty", "message": str(error)}) from error
        moved = "undone_batch_id" if direction == "undo" else "redone_batch_id"
        return {"schema_version": 1, "document": _site_document_ref(repo, document_id), moved: refs["batch_id"]}

    @app.post("/documents/{document_id}/site/undo")
    def undo_site_document(
        document_id: str, payload: SiteHistoryRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return _step_site(repo, document_id, payload.base_version, "undo")

    @app.post("/documents/{document_id}/site/redo")
    def redo_site_document(
        document_id: str, payload: SiteHistoryRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return _step_site(repo, document_id, payload.base_version, "redo")

    @app.get("/documents/{document_id}/site/brand")
    def get_site_brand(document_id: str, repo: HybridRepository = Depends(repository)) -> JsonObject:
        """The site's BrandData for the editor frame's ``init`` (Contract 6; controller ruling R3).

        Built by the one builder Lane B2 composes into ``app.state.site_brand_loader``; every asset
        and font ``file`` is ``/asset-store/<sha256>``. Until B2 lands the seam refuses typed."""
        document = require_document(repo, document_id)
        require_site_document(document)
        try:
            brand = app.state.site_brand_loader(repo, blob_store(repo), document)
        except SiteInputsUnavailable as error:
            raise HTTPException(status_code=503, detail={"code": error.code, "message": str(error)}) from error
        return {"schema_version": 1, "brand": brand}

    @app.get("/documents/{document_id}/site/versions")
    def list_site_versions(
        document_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """The site's history, newest first: one entry per save, agent turn, undo, redo or restore."""
        document = require_document(repo, document_id)
        require_site_document(document)
        envelopes = repo.list_envelopes(document_id, limit=limit, newest_first=True)
        return {
            "schema_version": 1,
            "versions": [
                {
                    "batch_id": envelope["batch_id"],
                    "version": int(envelope["base_revision"]) + 1,
                    "actor_kind": envelope["actor"]["kind"],
                    "intent": envelope["intent"],
                    "created_at": envelope["created_at"],
                }
                for envelope in envelopes
            ],
        }

    @app.post("/documents/{document_id}/site/versions/{batch_id}/restore")
    def restore_site_version(
        document_id: str,
        batch_id: str,
        payload: SiteHistoryRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Put back the site as it stood after ``batch_id``. The restore is itself one undoable save."""
        _guard_site_write(repo, document_id, payload.base_version, "restore a version")
        try:
            envelope = repo.require_envelope(document_id, batch_id)
        except NotFoundError:
            envelope = None
        site = replace_site_payload(envelope["operations"]) if envelope is not None else None
        if site is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "version.not_found", "message": f"no restorable version {batch_id!r} on document {document_id}"},
            )
        _write_site(
            repo,
            document_id,
            site=site,
            intent=f"restore:{batch_id}",
            checkpoint_label="Restore",
            base_version=payload.base_version,
        )
        return {"schema_version": 1, "document": _site_document_ref(repo, document_id)}
```

- [ ] **Step 5: Run the tests and the neighbours.**

Run: `DESIGN_PYTEST test_site_write_routes.py` then `DESIGN_PYTEST test_agent_run_write_lock.py` then `DESIGN_PYTEST test_web_operations.py`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/models.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_site_write_routes.py
git commit -m "design API: site save, undo, redo, versions and restore routes (Contract 2), refused while a site turn runs"
```

## A3 — composer targets

### Task 14: Site component targets on `design_node` refs, validated against the pinned site

`object_id` is `site:<route>#<componentId>` with an optional `.<propName>`
(`site:/analysis#Hero-1a2b.title`); the shell is `site:shell#header` / `site:shell#footer`. The
composer refuses every site target today (`chat/composer_context.py:271`). `DomainObjectRef.object_id`
allows 1–255 characters with no pattern (`platform/agents/clue_agents/contracts.py:91`); the wire
allows 200 (`chat/schemas.py:247-252`).

**Files:**
- Modify: `platform/api/clue_api/design_turn_targets.py` (site functions)
- Modify: `platform/api/clue_api/chat/composer_context.py:31-35,270-294`
- Modify: `tests/api/test_design_turn_targets.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (B5 builds the site turn's targets from `resolve_site_targets`):
  - `SITE_TARGET_PREFIX = "site:"`;
  - `@dataclass(frozen=True, slots=True) SiteTarget(route: str, component_id: str, prop: str | None)`
    (`route` is `"/"`, `"/<name>"` or `"shell"`);
  - `@dataclass(frozen=True, slots=True) SiteTargetNote(target: SiteTarget, note: str | None)`;
  - `@dataclass(frozen=True, slots=True) ResolvedSiteTargets(targets: tuple[SiteTarget, ...], target_notes: tuple[SiteTargetNote, ...])`;
  - `validate_site_targets(site: dict[str, Any], target_ids: Sequence[str]) -> tuple[SiteTarget, ...]`
    (raises `DesignTurnTargetError`);
  - `resolve_site_targets(site: dict[str, Any], focus_refs: Sequence[DomainObjectRef]) -> ResolvedSiteTargets | None`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/api/test_design_turn_targets.py` (add
  `validate_site_targets`, `resolve_site_targets`, `SiteTarget` to its import from
  `clue_api.design_turn_targets`):

```python
# --- site targets (Puck site documents, Wave 2 Lane A) -----------------------------------------


def _site_doc() -> dict[str, object]:
    return {
        "id": "doc_site",
        "pages": {
            "/": {"root": {"props": {}}, "content": [{"type": "StatsBand", "props": {"id": "proof", "heading": "H"}}]},
            "/analysis": {
                "root": {"props": {}},
                "content": [{"type": "FeatureSplit", "props": {"id": "Hero-1a2b", "title": "T", "body": "B"}},
                            {"type": "Quote", "props": {"id": "v2.quote", "quote": "Q"}}],
            },
        },
        "shell": {"header": {"preparedFor": "SCSD", "ctaLabel": "Go"}, "footer": {"legal": "©"}},
    }


def test_site_targets_name_a_component_its_prop_and_the_shell() -> None:
    assert validate_site_targets(
        _site_doc(),
        ("site:/analysis#Hero-1a2b.title", "site:/#proof", "site:shell#header.ctaLabel", "site:shell#footer", "site:/analysis#v2.quote"),
    ) == (
        SiteTarget(route="/analysis", component_id="Hero-1a2b", prop="title"),
        SiteTarget(route="/", component_id="proof", prop=None),
        SiteTarget(route="shell", component_id="header", prop="ctaLabel"),
        SiteTarget(route="shell", component_id="footer", prop=None),
        # An id with a dot in it is read whole first, so "v2.quote" is a component, not a prop.
        SiteTarget(route="/analysis", component_id="v2.quote", prop=None),
    )


@pytest.mark.parametrize(
    ("targets", "code"),
    [
        ((), "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
        (("site:/#proof", "site:/#proof"), "CONTEXT_REF_DUPLICATE"),
        (("frg_a",), "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
        (("site:/pricing#proof",), "CONTEXT_REF_NOT_FOUND"),
        (("site:/#ghost",), "CONTEXT_REF_NOT_FOUND"),
        (("site:/#proof.colour",), "CONTEXT_REF_NOT_FOUND"),
        (("site:shell#sidebar",), "CONTEXT_REF_NOT_FOUND"),
        (("site:/Analysis#Hero-1a2b",), "CONTEXT_REF_NOT_FOUND"),
    ],
)
def test_site_targets_refuse_what_the_stored_site_cannot_support(targets: tuple[str, ...], code: str) -> None:
    with pytest.raises(DesignTurnTargetError) as refused:
        validate_site_targets(_site_doc(), targets)
    assert refused.value.code == code


def test_resolve_site_targets_keeps_order_and_notes() -> None:
    resolved = resolve_site_targets(
        _site_doc(),
        [_web_ref("doc_site", object_type="design_document"), _web_ref("site:/#proof", "1. Bigger"), _web_ref("site:shell#header.ctaLabel", "2. Shorter")],
    )
    assert resolved is not None
    assert [(n.target.route, n.target.component_id, n.target.prop, n.note) for n in resolved.target_notes] == [
        ("/", "proof", None, "1. Bigger"),
        ("shell", "header", "ctaLabel", "2. Shorter"),
    ]
    assert resolve_site_targets(_site_doc(), [_web_ref("doc_site", object_type="design_document")]) is None


def test_validated_context_refs_accepts_targets_on_a_site_document(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_document(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"id": "doc_site", "doc_kind": "site", "current_version": 9, "scene": _site_doc()}

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    refs = (
        DomainObjectRef(workspace_id="ws_1", object_type="design_document", object_id="doc_site", version=9),
        _web_ref("site:/analysis#Hero-1a2b.title", "1. Shorter"),
    )
    assert asyncio.run(validated_context_refs(object(), workspace_id="ws_1", refs=refs, design_leg_document_ids=("doc_site",))) == refs  # type: ignore[arg-type]
    bad = (refs[0], _web_ref("site:/analysis#nope", "1."))
    with pytest.raises(ContextReferenceError) as refused:
        asyncio.run(validated_context_refs(object(), workspace_id="ws_1", refs=bad, design_leg_document_ids=("doc_site",)))  # type: ignore[arg-type]
    assert refused.value.code == "CONTEXT_REF_NOT_FOUND"
```

- [ ] **Step 2: Run them to see them fail.**

Run: `PLATFORM_PYTEST tests/api/test_design_turn_targets.py`
Expected: FAIL — `ImportError: cannot import name 'validate_site_targets'`.

- [ ] **Step 3: Add the site functions** to `design_turn_targets.py`. Add to `__all__`:
  `"ResolvedSiteTargets", "SITE_TARGET_PREFIX", "SiteTarget", "SiteTargetNote", "resolve_site_targets", "validate_site_targets",`,
  extend the module docstring with the paragraph below, and append the code:

```python
# Module docstring addition:
# Site documents (Puck, Wave 2): a target is a ``design_node`` ref whose object_id is
# ``site:<route>#<componentId>`` with an optional ``.<propName>`` (``site:/analysis#Hero-1a2b.title``),
# or ``site:shell#header`` / ``site:shell#footer``. It is validated against the stored site at the
# pinned version: the route is a page, the component's ``props.id`` is on it, the prop is one of
# its props.

SITE_TARGET_PREFIX = "site:"
_SITE_ROUTE = re.compile(r"^/(?:[a-z0-9][a-z0-9-]*)?$")
_SHELL_PARTS = ("header", "footer")


@dataclass(frozen=True, slots=True)
class SiteTarget:
    #: "/", "/<name>" or "shell".
    route: str
    #: The component's ``props.id``; "header" or "footer" for the shell.
    component_id: str
    prop: str | None


@dataclass(frozen=True, slots=True)
class SiteTargetNote:
    target: SiteTarget
    note: str | None


@dataclass(frozen=True, slots=True)
class ResolvedSiteTargets:
    targets: tuple[SiteTarget, ...]
    #: One entry per submitted ref, in submission order (annotations are numbered by the human).
    target_notes: tuple[SiteTargetNote, ...]


def _site_component_props(site: dict[str, Any], route: str, component_id: str) -> dict[str, Any] | None:
    """The props of the component a target names, or None when the stored site has no such one."""
    if route == "shell":
        shell = site.get("shell")
        part = shell.get(component_id) if isinstance(shell, dict) and component_id in _SHELL_PARTS else None
        return part if isinstance(part, dict) else None
    pages = site.get("pages")
    page = pages.get(route) if isinstance(pages, dict) else None
    content = page.get("content") if isinstance(page, dict) else None
    for item in content if isinstance(content, list) else ():
        props = item.get("props") if isinstance(item, dict) else None
        if isinstance(props, dict) and props.get("id") == component_id:
            return props
    return None


def _site_target(site: dict[str, Any], object_id: str) -> SiteTarget:
    if not object_id.startswith(SITE_TARGET_PREFIX) or "#" not in object_id:
        raise DesignTurnTargetError(
            "CONTEXT_REF_RELATIONSHIP_MISMATCH",
            "a target on a site document is site:<route>#<component>[.<prop>]",
        )
    route, _, rest = object_id[len(SITE_TARGET_PREFIX):].partition("#")
    if route != "shell" and not _SITE_ROUTE.fullmatch(route):
        raise DesignTurnTargetError("CONTEXT_REF_NOT_FOUND", "a targeted site page is not a route of this site")
    # The whole rest is a component id first (ids may contain dots); only then "<id>.<prop>".
    if _site_component_props(site, route, rest) is not None:
        return SiteTarget(route=route, component_id=rest, prop=None)
    component_id, dot, prop = rest.rpartition(".")
    props = _site_component_props(site, route, component_id) if dot else None
    if props is None or prop not in props:
        raise DesignTurnTargetError(
            "CONTEXT_REF_NOT_FOUND",
            "a targeted site component or field does not exist in the submitted site document",
        )
    return SiteTarget(route=route, component_id=component_id, prop=prop)


def validate_site_targets(site: dict[str, Any], target_ids: Sequence[str]) -> tuple[SiteTarget, ...]:
    """Refuse site targets the stored site cannot support; return them parsed, in order."""
    ordered = tuple(target_ids)
    if not ordered:
        raise DesignTurnTargetError("CONTEXT_REF_RELATIONSHIP_MISMATCH", "a focused design turn requires at least one design node")
    if len(set(ordered)) != len(ordered):
        raise DesignTurnTargetError("CONTEXT_REF_DUPLICATE", "the same design node may appear only once in a submission")
    return tuple(_site_target(site, object_id) for object_id in ordered)


def resolve_site_targets(site: dict[str, Any], focus_refs: Sequence[DomainObjectRef]) -> ResolvedSiteTargets | None:
    """The turn's ``design_node`` refs as site targets with their notes; None when there are none."""
    nodes = [ref for ref in focus_refs if ref.object_type == "design_node"]
    if not nodes:
        return None
    targets = validate_site_targets(site, [ref.object_id for ref in nodes])
    return ResolvedSiteTargets(
        targets=tuple(dict.fromkeys(targets)),
        target_notes=tuple(SiteTargetNote(target=target, note=ref.note) for target, ref in zip(targets, nodes)),
    )
```

- [ ] **Step 4: Dispatch site documents in the composer.** In `chat/composer_context.py`:
  - add `validate_site_targets,` to the `from clue_api.design_turn_targets import (` block (`:31-35`);
  - `:271` `if target_doc_kind not in {"scene", "web"}:` → `if target_doc_kind not in {"scene", "web", "site"}:`
  - in the `try` at `:285-294`, change the `else:` branch to:

```python
            elif target_doc_kind == "site":
                validate_site_targets(
                    target_document.get("scene") or {},
                    tuple(ref.object_id for ref in design_nodes),
                )
            else:
                validate_web_targets(
                    target_document.get("scene") or {},
                    tuple(ref.object_id for ref in design_nodes),
                )
```

- [ ] **Step 5: Run the tests and the composer suite.**

Run: `PLATFORM_PYTEST tests/api/test_design_turn_targets.py` then `PLATFORM_PYTEST tests/api/test_chat_composer_context.py`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add platform/api/clue_api/design_turn_targets.py platform/api/clue_api/chat/composer_context.py tests/api/test_design_turn_targets.py
git commit -m "platform: site component targets (site:<route>#<id>[.<prop>]) validated against the pinned site"
```

## A5 — the renderer and the cleaner

### Task 15: The site-kit render core, the browser entry, and the render bundle in the backend image

The render inside Chromium is site-kit code: a Node-testable core (`renderSitePages`,
`sectionPropsSchema`) and a thin browser entry that loads agent sections from `data:` URLs and
answers on a nonce-checked channel. esbuild bundles both into one classic script with React,
`react-dom/server` (browser build), Puck's `<Render>` (`@puckeditor/core/rsc`), Zod and the kit
inlined — 1.2 MB minified (probe, 2026-10-11, rendered Garner's home in 18 ms in Chromium 149).

**Files:**
- Create: `apps/frontend/packages/site-kit/src/render-core.tsx`
- Create: `apps/frontend/packages/site-kit/src/render-browser.tsx`
- Modify: `apps/frontend/packages/site-kit/bin/build-bundles.mjs` (the browser bundle)
- Modify: `apps/frontend/packages/site-kit/src/index.ts`, `README.md`
- Create: `apps/frontend/packages/site-kit/test/render-core.test.tsx`
- Modify: `apps/frontend/packages/site-kit/test/bundles.test.ts`
- Modify: `docker/backend/Dockerfile`, `docker/backend/smoke.sh`, `tests/deploy/test_backend_image.py`

**Interfaces:**
- Consumes: `makeConfig`, `makeKit(href, brand)` (Task 5), `tailwindThemeCss` (Task 4).
- Produces:
  - `src/render-core.tsx`: `type StoredSite = { title?: string; pages: Record<string, unknown>; shell: ShellData | null }`,
    `type RenderedSitePage = { route: string; html: string }`,
    `class RenderRefusal extends Error { code: string }`,
    `siteRoutes(site: StoredSite): string[]`,
    `renderSitePages(input: { site: StoredSite; brand: BrandData; basePath: string; routes?: string[]; agentSections: Record<string, AgentSectionModule>; maxOutputBytes: number }): { pages: RenderedSitePage[]; tailwindTheme: string; size: number; warnings: string[] }`,
    `sectionPropsSchema(module: { schema?: unknown; render?: unknown }): { props: unknown } | { errors: string[] }`;
  - `dist/render-browser.js`, a classic script. Its page contract (Task 17 relies on it): it reads
    `#clue-render-input` (an inert `<script type="application/json">`) holding
    `{mode: "render" | "schema", nonce, maxOutputBytes, site?, brand?, basePath?, routes?, sections: [{name, moduleJs}]}`,
    removes it, and finishes by setting the frozen object `window.__clueRender` to
    `{done: true, nonce, size, code, error, result}` where `result` is
    `{pages: [{route, html}], tailwindTheme, warnings}` (render) or `{props}` / `{errors}` (schema),
    and `code` is `null` or one of `render.failed` / `render.output_too_large`.

- [ ] **Step 1: Write the failing tests** in `test/render-core.test.tsx`:

```tsx
// The server render's React half (Wave 2 Lane A): plain renderToStaticMarkup of each route with
// Puck's <Render>, testable in Node. The browser entry runs exactly this inside the hardened page.
import assert from "node:assert/strict";
import { test } from "node:test";
import { z } from "zod";
import { RenderRefusal, renderSitePages, sectionPropsSchema, siteRoutes } from "../src/render-core";
import { garner, site as readSite } from "./fixtures/garner";
import { render as quoteRender, schema as quoteSchema } from "./fixtures/section-example";

const brand = garner();
const stored = readSite("garner-syracuse");
const site = { title: "Garner for Syracuse", pages: stored.pages, shell: stored.shell };

test("routes render home first, then the others in order", () => {
  assert.deepEqual(siteRoutes({ ...site, pages: { "/zeta": {}, "/": {}, "/alpha": {} } }), ["/", "/alpha", "/zeta"]);
});

test("a stored site renders every route as a document, with its links under the base path", () => {
  const result = renderSitePages({ site, brand, basePath: "/acme-site", agentSections: {}, maxOutputBytes: 10_000_000 });
  assert.deepEqual(result.pages.map((page) => page.route), ["/", "/analysis"]);
  const home = result.pages[0].html;
  assert.ok(home.startsWith('<!doctype html><html lang="en"><head><title>Garner Health for Syracuse City School District</title></head><body>'), home.slice(0, 200));
  assert.ok(home.includes('class="brand-root"'));
  assert.ok(home.includes('href="/acme-site/analysis"'), "the closing clone's /analysis link is rebased");
  assert.ok(result.tailwindTheme.startsWith("@theme inline {"));
  assert.equal(result.size, result.pages.reduce((total, page) => total + page.html.length, 0));
});

test("an agent section renders inside its data-agent-section wrapper, with the kit", () => {
  const home = structuredClone(stored.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "brand", quote: "Fewer surprises.", attribution: "A buyer" } });
  const result = renderSitePages({
    site: { ...site, pages: { "/": home } },
    brand,
    basePath: "",
    agentSections: { QuoteBand: { schema: quoteSchema, render: quoteRender as never } },
    maxOutputBytes: 10_000_000,
  });
  const html = result.pages[0].html;
  assert.ok(html.includes('<div data-agent-section="QuoteBand"><section class="bg-surface-brand text-on-surface-brand">'), html);
  assert.ok(html.includes("Fewer surprises."));
});

test("the output cap is a typed refusal", () => {
  assert.throws(
    () => renderSitePages({ site, brand, basePath: "", agentSections: {}, maxOutputBytes: 1000 }),
    (error) => error instanceof RenderRefusal && error.code === "render.output_too_large",
  );
  assert.throws(
    () => renderSitePages({ site, brand, basePath: "", routes: ["/nope"], agentSections: {}, maxOutputBytes: 10_000_000 }),
    (error) => error instanceof RenderRefusal && error.code === "render.failed",
  );
});

test("sectionPropsSchema reads the props schema and refuses the shapes the check used to", () => {
  const ok = sectionPropsSchema({ schema: quoteSchema, render: quoteRender });
  assert.ok("props" in ok);
  assert.deepEqual(Object.keys((ok.props as { properties: Record<string, unknown> }).properties).sort(), ["attribution", "id", "quote", "surface"]);
  assert.deepEqual(sectionPropsSchema({ schema: z.object({ id: z.string() }).strict(), render: quoteRender }), {
    errors: ['the props need "surface" (every section has an id and a surface)'],
  });
  assert.deepEqual(sectionPropsSchema({ schema: z.object({ id: z.string(), surface: z.string(), style: z.string() }), render: quoteRender }), {
    errors: ['the props may not include "style"'],
  });
  assert.deepEqual(sectionPropsSchema({ schema: {}, render: 1 }), {
    errors: ["`schema` must be a zod object (z.object({...}).strict())", "`render` must be a function (props, kit) => JSX"],
  });
});
```
  and add to `test/bundles.test.ts`, inside the existing test after the two `assert.ok(fs.existsSync(...))`:

```ts
  const browser = path.join(root, "dist", "render-browser.js");
  assert.ok(fs.existsSync(browser), "the render bundle is built");
  const text = fs.readFileSync(browser, "utf-8");
  assert.ok(text.length > 100_000 && !/^\s*import\s/m.test(text.slice(0, 2000)), "one classic script, nothing to resolve");
  assert.ok(text.includes("__clueRender") && text.includes("clue-render-input"));
```

- [ ] **Step 2: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/render-core.test.tsx test/bundles.test.ts`
Expected: FAIL — `Cannot find module '../src/render-core'`; no `dist/render-browser.js`.

- [ ] **Step 3: Create `src/render-core.tsx`.**

```tsx
// Rendering a stored site to static HTML: the React half of the server render (Wave 2 Lane A).
// Pure — no DOM, no file reads — so it is tested in Node; render-browser.tsx calls it inside the
// design API's hardened Chromium page after loading the site's agent sections.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Render } from "@puckeditor/core/rsc";
import type { Config, Data } from "@puckeditor/core";
import { z } from "zod";
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { makeConfig } from "./config";
import type { ShellData } from "./shell";
import { tailwindThemeCss } from "./theme";

export type StoredSite = { title?: string; pages: Record<string, unknown>; shell: ShellData | null };
export type RenderedSitePage = { route: string; html: string };

/** A render that cannot finish, with one of the contract codes (Contract 3). */
export class RenderRefusal extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "RenderRefusal";
  }
}

const escapeHtml = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** "/" first, then every other route alphabetically. */
export function siteRoutes(site: StoredSite): string[] {
  const others = Object.keys(site.pages).filter((route) => route !== "/").sort();
  return site.pages["/"] === undefined ? others : ["/", ...others];
}

export function renderSitePages(input: {
  site: StoredSite;
  brand: BrandData;
  /** Where the site is served ("/acme-site"); "" leaves /route links as written. */
  basePath: string;
  routes?: string[];
  agentSections: Record<string, AgentSectionModule>;
  /** Total characters of HTML allowed across the routes rendered. */
  maxOutputBytes: number;
}): { pages: RenderedSitePage[]; tailwindTheme: string; size: number; warnings: string[] } {
  const config = makeConfig(input.brand, {
    basePath: input.basePath || undefined,
    shell: input.site.shell ?? undefined,
    agentSections: input.agentSections,
  }) as Config;
  const pages: RenderedSitePage[] = [];
  const warnings: string[] = [];
  let size = 0;
  for (const route of input.routes ?? siteRoutes(input.site)) {
    const data = input.site.pages[route] as Data | undefined;
    if (!data) throw new RenderRefusal("render.failed", `the site has no page ${route}`);
    for (const item of (data.content ?? []) as { type: string; props: Record<string, unknown> }[]) {
      if (item.type === "ClonedSection" && !input.brand.clones[String(item.props?.fragmentId ?? "")]) {
        warnings.push(`${route}: cloned section ${String(item.props?.fragmentId)} is not one of the brand's clones`);
      }
    }
    const title = String((data.root as { props?: { title?: string } } | undefined)?.props?.title || input.site.title || "");
    const body = renderToStaticMarkup(createElement(Render as never, { config, data } as never));
    const html = `<!doctype html><html lang="en"><head><title>${escapeHtml(title)}</title></head><body>${body}</body></html>`;
    size += html.length;
    if (size > input.maxOutputBytes) {
      throw new RenderRefusal("render.output_too_large", `the rendered site passed ${input.maxOutputBytes} characters at ${route}`);
    }
    pages.push({ route, html });
  }
  return { pages, tailwindTheme: tailwindThemeCss(input.brand), size, warnings };
}

/** A loaded agent section's props JSON Schema, or the reasons it cannot join a site. The rules are
 * the ones the spike's check-section CLI applied after importing the module; D2 moved them here,
 * where the module is loaded only inside the hardened render page. */
export function sectionPropsSchema(module: { schema?: unknown; render?: unknown }): { props: unknown } | { errors: string[] } {
  const errors: string[] = [];
  let props: unknown = null;
  if (!(module.schema instanceof z.ZodObject)) {
    errors.push("`schema` must be a zod object (z.object({...}).strict())");
  } else {
    const keys = Object.keys(module.schema.shape);
    for (const key of ["className", "style"]) if (keys.includes(key)) errors.push(`the props may not include "${key}"`);
    for (const key of ["id", "surface"]) if (!keys.includes(key)) errors.push(`the props need "${key}" (every section has an id and a surface)`);
    props = z.toJSONSchema(module.schema);
  }
  if (typeof module.render !== "function") errors.push("`render` must be a function (props, kit) => JSX");
  return errors.length ? { errors } : { props };
}
```

- [ ] **Step 4: Create `src/render-browser.tsx`.**

```tsx
// The site render inside the design API's hardened Chromium page (D2, founder ruling 2026-10-11).
// Bundled by bin/build-bundles.mjs into dist/render-browser.js: ONE classic script with React,
// react-dom/server, Puck's <Render>, zod and this kit inlined. lumen_api/site_render.py loads it
// into a page whose CSP allows only inline script and data: modules, after an inert JSON script
// #clue-render-input that holds the render's input.
//
// What it does: reads and removes the input, exposes its own react, react/jsx-runtime and zod on
// globalThis.__clueSectionHost, imports each agent section from a data: URL whose three host
// imports are rewritten to data: shims over those copies (one React, one zod), renders, and answers
// on window.__clueRender — frozen once written, and only trusted by Python when it carries the
// render's nonce (which no section can read: the input is gone before any section loads).
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as zodNamespace from "zod";
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { RenderRefusal, renderSitePages, sectionPropsSchema, type StoredSite } from "./render-core";

type Input = {
  mode: "render" | "schema";
  nonce: string;
  maxOutputBytes: number;
  site?: StoredSite;
  brand?: BrandData;
  basePath?: string;
  routes?: string[];
  sections: { name: string; moduleJs: string }[];
};
type Channel = { done: boolean; nonce: string; size: number; code: string | null; error: string | null; result: unknown };

const HOST: Record<string, Record<string, unknown>> = {
  react: React as unknown as Record<string, unknown>,
  "react/jsx-runtime": jsxRuntime as unknown as Record<string, unknown>,
  zod: zodNamespace as unknown as Record<string, unknown>,
};
const RESERVED = new Set(
  ("break case catch class const continue debugger default delete do else enum export extends false finally for " +
    "function if import in instanceof new null return super switch this throw true try typeof var void while with " +
    "yield let static implements interface package private protected public await").split(" "),
);
const freeze = Object.freeze;
const channel: Channel = Object.seal({ done: false, nonce: "", size: 0, code: null, error: null, result: null });
Object.defineProperty(window, "__clueRender", { value: channel, writable: false, configurable: false });

const dataUrl = (source: string) => "data:text/javascript;charset=utf-8," + encodeURIComponent(source);

function shimFor(specifier: string): string {
  const names = Object.keys(HOST[specifier]).filter((name) => name !== "default" && /^[A-Za-z_$][\w$]*$/.test(name) && !RESERVED.has(name));
  return (
    `const M = globalThis.__clueSectionHost[${JSON.stringify(specifier)}];\n` +
    "export default (M.default ?? M);\n" +
    (names.length ? `export const { ${names.join(", ")} } = M;\n` : "")
  );
}

async function loadSection(moduleJs: string, shims: Record<string, string>): Promise<Record<string, unknown>> {
  const source = moduleJs.replace(
    /(\bfrom\s*|\bimport\s*)(["'])(react\/jsx-runtime|react|zod)\2/g,
    (_match, keyword: string, _quote: string, specifier: string) => `${keyword}${JSON.stringify(shims[specifier])}`,
  );
  return (await import(dataUrl(source))) as Record<string, unknown>;
}

function finish(nonce: string, fields: Partial<Channel>): void {
  Object.assign(channel, fields);
  channel.nonce = nonce;
  channel.done = true;
  freeze(channel);
}

async function main(): Promise<void> {
  const element = document.getElementById("clue-render-input");
  const input = JSON.parse(element?.textContent ?? "{}") as Input;
  element?.remove();
  const nonce = input.nonce;
  // WebRTC is not covered by the page's CSP; the launch flags and the proxy refuse it as well.
  for (const name of ["RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel"]) {
    try {
      delete (globalThis as Record<string, unknown>)[name];
    } catch {
      // A non-configurable global stays; the network layers below the page still refuse it.
    }
  }
  (globalThis as Record<string, unknown>).__clueSectionHost = HOST;
  const shims = Object.fromEntries(Object.keys(HOST).map((specifier) => [specifier, dataUrl(shimFor(specifier))]));
  try {
    const loaded: Record<string, Record<string, unknown>> = {};
    for (const section of input.sections) loaded[section.name] = await loadSection(section.moduleJs, shims);
    if (input.mode === "schema") {
      const result = sectionPropsSchema(Object.values(loaded)[0] ?? {});
      finish(nonce, { size: JSON.stringify(result).length, result });
      return;
    }
    const agentSections = Object.fromEntries(Object.entries(loaded).map(([name, module]) => [name, module as unknown as AgentSectionModule]));
    const rendered = renderSitePages({
      site: input.site as StoredSite,
      brand: input.brand as BrandData,
      basePath: input.basePath ?? "",
      routes: input.routes,
      agentSections,
      maxOutputBytes: input.maxOutputBytes,
    });
    finish(nonce, { size: rendered.size, result: { pages: rendered.pages, tailwindTheme: rendered.tailwindTheme, warnings: rendered.warnings } });
  } catch (error) {
    finish(nonce, {
      code: error instanceof RenderRefusal ? error.code : "render.failed",
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

void main();
```

- [ ] **Step 5: Bundle it.** In `bin/build-bundles.mjs`, update the header comment's list with
  `//   dist/render-browser.js   the site render inside the hardened Chromium page (src/render-browser.tsx)`
  and, after the `await Promise.all(...)` block, add:

```js
await build({
  absWorkingDir: root,
  entryPoints: ["src/render-browser.tsx"],
  outfile: path.join(dist, "render-browser.js"),
  bundle: true,
  platform: "browser",
  format: "iife",
  target: "chrome120",
  jsx: "automatic",
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "warning",
  banner,
});
```

- [ ] **Step 6: Export the core** from `src/index.ts`:

```ts
export { RenderRefusal, renderSitePages, sectionPropsSchema, siteRoutes, type RenderedSitePage, type StoredSite } from "./render-core";
```
  and add to the README's entry-point table the row
  `| \`@clue/site-kit\` (render-core) | \`renderSitePages\`, \`sectionPropsSchema\`, \`siteRoutes\`: the server render's React half, which \`dist/render-browser.js\` runs inside the design API's hardened Chromium page |`.

- [ ] **Step 7: Build the bundle in the backend image.** In `docker/backend/Dockerfile`, after the
  `editor` stage, add:

```dockerfile
# --- Site kit bundles (Puck sites: the hardened-browser render bundle and the validator CLI) -----
FROM node:24-bookworm-slim AS sitekit
WORKDIR /src/apps/frontend
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
COPY apps/frontend/packages/design-system/package.json ./packages/design-system/package.json
COPY apps/frontend/packages/site-kit ./packages/site-kit
RUN npm ci --ignore-scripts && npm run build -w @clue/site-kit \
    && test -f packages/site-kit/dist/render-browser.js \
    && test -f packages/site-kit/dist/validate-site.mjs \
    && test -f packages/site-kit/dist/build-catalog.mjs
```
  and in the runtime stage, after the `COPY --from=editor … public/vendor` line, add:

```dockerfile
COPY --from=sitekit /src/apps/frontend/packages/site-kit/dist /app/apps/frontend/packages/site-kit/dist
```
  In `docker/backend/smoke.sh`, after the `tailwind browser runtime` check, add:

```bash
check "site-kit bundles" run test -f /app/apps/frontend/packages/site-kit/dist/render-browser.js -a -f /app/apps/frontend/packages/site-kit/dist/validate-site.mjs
```
  and append to `tests/deploy/test_backend_image.py`:

```python
def test_the_image_builds_and_ships_the_site_kit_bundles() -> None:
    """Puck sites render and validate with site-kit's built files (Wave 2 Lane A); the runtime has
    no apps/frontend/node_modules, so the bundles are built in their own stage and copied in."""
    assert "FROM node:24-bookworm-slim AS sitekit" in DOCKERFILE
    assert "npm run build -w @clue/site-kit" in DOCKERFILE
    assert (
        "COPY --from=sitekit /src/apps/frontend/packages/site-kit/dist /app/apps/frontend/packages/site-kit/dist"
        in DOCKERFILE
    )
    assert 'check "site-kit bundles"' in SMOKE
```

- [ ] **Step 8: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && cd ../.. && npm run typecheck -w @clue/site-kit` then `PLATFORM_PYTEST tests/deploy/test_backend_image.py`
Expected: all pass; no type errors.

- [ ] **Step 9: Commit.**

```bash
git add apps/frontend/packages/site-kit/src/render-core.tsx apps/frontend/packages/site-kit/src/render-browser.tsx apps/frontend/packages/site-kit/src/index.ts apps/frontend/packages/site-kit/bin/build-bundles.mjs apps/frontend/packages/site-kit/README.md apps/frontend/packages/site-kit/test/render-core.test.tsx apps/frontend/packages/site-kit/test/bundles.test.ts docker/backend/Dockerfile docker/backend/smoke.sh tests/deploy/test_backend_image.py
git commit -m "site-kit: the server render's React core and the hardened-page browser bundle; the backend image builds them"
```

### Task 16: The cleaner — `sanitize_site_html` strips script, handlers and foreign bytes from a whole page

Contract 3: `sanitize_site_html(html) -> SanitizedHtml(html, removed)` strips `script`, `iframe`,
`object`, `embed`, `form`, `base`, `meta`, `link`, every `on*` attribute, `javascript:` URLs, and any
`src`, `srcset`, `poster` or CSS `url()` that is not `/asset-store/<sha256>`, a relative site route
or `data:`. It strips; it does not refuse. It builds on the selectolax fragment sanitizer's helpers
(`lumen_api/fragments/refs.py:91-127`, `fragments/sanitize.py:255-305`), whose own posture is to
refuse (`:184-227`) — the wrong posture for a published page, so this is a separate module.

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/site_sanitize.py`
- Create: `subsystems/clue-design/apps/api/tests/test_site_sanitize.py`

**Interfaces:**
- Consumes: `asset_url_digest`, `link_scheme_allowed` (`fragments/refs.py`),
  `parse_srcset_candidates` (`fragments/sanitize.py`).
- Produces: `@dataclass(frozen=True) SanitizedHtml(html: str, removed: tuple[str, ...])`,
  `sanitize_site_html(html: str) -> SanitizedHtml`, `asset_reference_allowed(value: str) -> bool`,
  `clean_css(css: str, removed: list[str]) -> str`, `STRIPPED_ELEMENTS: frozenset[str]`.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_site_sanitize.py`:

```python
"""The published-site cleaner (Wave 2 Contract 3): strip, never refuse — the master plan's Review focus 7."""

from __future__ import annotations

from lumen_api.site_sanitize import asset_reference_allowed, sanitize_site_html

DIGEST = "a" * 64


def test_scripts_frames_forms_and_document_elements_go_with_their_content() -> None:
    out = sanitize_site_html(
        '<!doctype html><html><head><title>T</title><meta http-equiv="refresh" content="0;url=https://evil.example">'
        '<link rel="stylesheet" href="https://evil.example/x.css"><base href="https://evil.example/"></head>'
        '<body><p>keep</p><script>steal()</script><iframe src="https://evil.example"></iframe><object data="x"></object>'
        '<embed src="x"><form action="https://evil.example"><input name="q"></form><noscript><img src="https://evil.example/n.gif"></noscript>'
        '<svg><foreignObject><div>x</div></foreignObject><set attributeName="href" to="javascript:alert(1)"/></svg></body></html>'
    )
    lowered = out.html.lower()
    for gone in ("<script", "<iframe", "<object", "<embed", "<form", "<meta", "<link", "<base", "<noscript", "foreignobject", "<set", "evil.example"):
        assert gone not in lowered, gone
    assert "<p>keep</p>" in out.html and "<title>T</title>" in out.html
    assert out.html.startswith("<!DOCTYPE html>")
    assert "stripped <script> and its content" in out.removed


def test_handlers_pings_and_script_links_go_and_real_links_stay() -> None:
    out = sanitize_site_html(
        '<html><body><a href="javascript:steal()" onclick="steal()" ping="https://evil.example/p">x</a>'
        '<a href="https://example.com/cta">cta</a><a href="/acme/analysis">next</a><a href="mailto:a@example.com">m</a>'
        '<a href="java\tscript:alert(1)">t</a><div onmouseover="x()" ONLOAD="y()">d</div></body></html>'
    )
    html = out.html.lower()
    assert 'href="https://example.com/cta"' in html and 'href="/acme/analysis"' in html and 'href="mailto:a@example.com"' in html
    for gone in ("javascript", "onclick", "ping=", "onmouseover", "onload", "java\tscript"):
        assert gone not in html, gone


def test_only_asset_store_site_paths_fragments_and_data_urls_load_bytes() -> None:
    out = sanitize_site_html(
        f'<html><body><img src="/asset-store/{DIGEST}"><img src="https://collector.example/p.gif">'
        '<img src="//cdn.example/x.png"><img src="/\\evil.example/x.png"><img src="data:image/png;base64,iVBOR">'
        f'<video poster="https://evil.example/p.png" src="/asset-store/{DIGEST}"></video>'
        f'<img srcset="/asset-store/{DIGEST} 1x, https://evil.example/2x.png 2x">'
        f'<svg><use href="https://evil.example/sprite.svg#i"></use><use href="#local"></use><image href="/asset-store/{DIGEST}"></image></svg>'
        "</body></html>"
    )
    html = out.html
    assert html.count(f"/asset-store/{DIGEST}") == 4
    for gone in ("collector.example", "cdn.example", "evil.example"):
        assert gone not in html, gone
    assert 'src="data:image/png;base64,iVBOR"' in html and 'href="#local"' in html
    assert f'srcset="/asset-store/{DIGEST} 1x"' in html


def test_css_urls_in_style_elements_and_attributes_are_neutralised() -> None:
    out = sanitize_site_html(
        "<html><head><style>@import url(https://evil.example/x.css);"
        ".a{background:url(https://evil.example/bg.png) no-repeat}"
        f'.b{{background:url("/asset-store/{DIGEST}")}}'
        "@font-face{font-family:X;src:url(https://evil.example/f.woff2)}"
        "@media (min-width:1px){.c{background-image:url(//evil.example/c.png)}}"
        '.d{background:image-set("https://evil.example/i.png" 1x)}</style></head>'
        '<body><div style="background:url(https://evil.example/s.png);color:red">s</div>'
        f'<div style="background:url(/asset-store/{DIGEST})">t</div></body></html>'
    )
    assert "evil.example" not in out.html
    assert out.html.count(f"/asset-store/{DIGEST}") == 2
    assert "color:red" in out.html.replace(" ", "")
    assert "stripped @import" in out.removed


def test_cleaning_twice_changes_nothing() -> None:
    once = sanitize_site_html(f'<html><body><a href="javascript:x()" onclick="y()">a</a><img src="/asset-store/{DIGEST}"></body></html>')
    twice = sanitize_site_html(once.html)
    assert twice.html == once.html and twice.removed == ()


def test_the_reference_rule() -> None:
    for kept in (f"/asset-store/{DIGEST}", "/analysis", "#grad", "data:image/png;base64,x", ""):
        assert asset_reference_allowed(kept), kept
    for refused in ("https://example.com/x.png", "//cdn.example/x.png", "/\\evil.example/x.png", "file:///etc/passwd", "javascript:x()"):
        assert not asset_reference_allowed(refused), refused
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_sanitize.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'lumen_api.site_sanitize'`.

- [ ] **Step 3: Create `lumen_api/site_sanitize.py`.**

```python
"""The published-site cleaner (Wave 2 Contract 3): strip, never refuse.

Every published, exported, thumbnailed or printed Puck site page passes through
:func:`sanitize_site_html` — the whole page (ruling 2026-10-11): agent sections, the seller's
clones and our own sections alike. Published sites are script-free. What goes, and why:

* elements, with their content: ``script iframe object embed form base meta link`` (the
  contract's list), plus ``noscript template frame frameset applet portal``, SVG's
  ``foreignObject`` and the SMIL animation elements, for the fragment sanitizer's reasons
  (``lumen_api/fragments/sanitize.py``: each is a way past an attribute-time gate). ``<style>``
  stays — the theme and the clones' captured CSS live there — and its ``url()``s are cleaned;
* every ``on*`` attribute, by prefix, and ``ping``, ``formaction``, ``action``, ``srcdoc``;
* a link (``href``, ``xlink:href``, ``cite``) whose scheme is not http(s), mailto, tel or sms
  (``fragments/refs.link_scheme_allowed``) — the attribute, not the element;
* a byte-loading reference (``src``, every ``srcset`` candidate, ``poster``, ``background``, an
  SVG asset ``href``, a CSS ``url()`` or ``image-set()``) that is not ``/asset-store/<sha256>``,
  a site-relative path, an in-document ``#fragment`` or ``data:``.

The caller adds its own head (charset, viewport, CSP, description, icon, manifest link) AFTER this
runs, so nothing of ours is ever stripped.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

import tinycss2
from selectolax.lexbor import LexborHTMLParser, LexborNode
from tinycss2 import ast

from .fragments.refs import asset_url_digest, link_scheme_allowed
from .fragments.sanitize import parse_srcset_candidates

STRIPPED_ELEMENTS = frozenset(
    {
        "script", "iframe", "object", "embed", "form", "base", "meta", "link",
        "noscript", "template", "frame", "frameset", "applet", "portal", "foreignobject",
        "animate", "set", "animatetransform", "animatemotion", "animatecolor", "discard",
    }
)
_ASSET_ATTRS = frozenset({"src", "poster", "background", "lowsrc", "dynsrc"})
_ASSET_LIST_ATTRS = frozenset({"srcset", "imagesrcset"})
_SVG_ASSET_ELEMENTS = frozenset({"use", "image", "feimage", "textpath", "mpath", "pattern"})
_LINK_ATTRS = frozenset({"href", "xlink:href", "cite"})
_ALWAYS_STRIPPED_ATTRS = frozenset({"ping", "formaction", "action", "srcdoc"})
_IMAGE_SET_FUNCTIONS = frozenset({"image-set", "-webkit-image-set"})


@dataclass(frozen=True)
class SanitizedHtml:
    html: str
    #: One note per removal, in document order ("stripped <script> and its content").
    removed: tuple[str, ...]


def asset_reference_allowed(value: str) -> bool:
    """Whether a byte-loading reference may stay on a published site page."""
    text = value.strip()
    if not text or text.startswith("#") or text.lower().startswith("data:"):
        return True
    if asset_url_digest(text) is not None:
        return True
    # A site-relative path; "//host" and "/\host" are other hosts to a browser.
    return text.startswith("/") and not text.startswith("//") and "\\" not in text


def _none(token: ast.Node) -> ast.IdentToken:
    return ast.IdentToken(token.source_line, token.source_column, "none")


def _clean_css_tokens(tokens: list[ast.Node], removed: list[str]) -> None:
    for index, token in enumerate(tokens):
        if isinstance(token, ast.URLToken):
            if not asset_reference_allowed(token.value):
                removed.append(f"stripped css url({token.value[:80]})")
                tokens[index] = _none(token)
        elif isinstance(token, ast.FunctionBlock):
            if token.lower_name == "url":
                target = next((arg.value for arg in token.arguments if isinstance(arg, ast.StringToken)), "")
                if not asset_reference_allowed(target):
                    removed.append(f"stripped css url({target[:80]})")
                    tokens[index] = _none(token)
            elif token.lower_name in _IMAGE_SET_FUNCTIONS:
                removed.append(f"stripped css {token.lower_name}()")
                tokens[index] = _none(token)
            else:
                _clean_css_tokens(token.arguments, removed)
        elif isinstance(token, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)):
            _clean_css_tokens(token.content, removed)


def clean_css(css: str, removed: list[str]) -> str:
    """A stylesheet with every foreign ``url()``/``image-set()`` replaced by ``none`` and every
    ``@import`` dropped."""
    kept: list[ast.Node] = []
    for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=False):
        if isinstance(rule, ast.AtRule) and rule.lower_at_keyword == "import":
            removed.append("stripped @import")
            continue
        if isinstance(rule, (ast.QualifiedRule, ast.AtRule)):
            _clean_css_tokens(rule.prelude, removed)
            if rule.content is not None:
                _clean_css_tokens(rule.content, removed)
        kept.append(rule)
    return tinycss2.serialize(kept)


def _clean_declarations(declarations: str, removed: list[str]) -> str:
    tokens = tinycss2.parse_component_value_list(declarations)
    _clean_css_tokens(tokens, removed)
    return tinycss2.serialize(tokens)


def _drop_elements(root: LexborNode, removed: list[str]) -> None:
    # Re-scan after each removal: decomposing a node invalidates its descendants.
    while True:
        target = next(
            (node for node in root.traverse(include_text=False) if (node.tag or "").lower() in STRIPPED_ELEMENTS),
            None,
        )
        if target is None:
            return
        removed.append(f"stripped <{(target.tag or '').lower()}> and its content")
        target.decompose()


def _clean_style_elements(tree: LexborHTMLParser, removed: list[str]) -> None:
    for node in list(tree.css("style")):
        css = node.text(deep=True)
        before = len(removed)
        cleaned = clean_css(css, removed)
        if len(removed) == before:
            continue
        attributes = "".join(f' {name}="{escape(value or "", quote=True)}"' for name, value in node.attributes.items())
        # "</" cannot appear in a stylesheet outside a string; escaping it keeps the new element whole.
        body = cleaned.replace("</", "<\\/")
        replacement = LexborHTMLParser("<style" + attributes + ">" + body + "</style>").css_first("style")
        if replacement is not None:
            node.replace_with(replacement)


def _clean_attributes(node: LexborNode, removed: list[str]) -> None:
    tag = (node.tag or "").lower()
    for name, value in list(node.attributes.items()):
        lowered = name.lower()
        raw = value or ""
        if lowered.startswith("on") or lowered in _ALWAYS_STRIPPED_ATTRS:
            del node.attrs[name]
            removed.append(f"stripped {lowered} on <{tag}>")
        elif lowered in _ASSET_ATTRS or (lowered in ("href", "xlink:href") and tag in _SVG_ASSET_ELEMENTS):
            if not asset_reference_allowed(raw):
                del node.attrs[name]
                removed.append(f"stripped {lowered}={raw.strip()[:80]} on <{tag}>")
        elif lowered in _ASSET_LIST_ATTRS:
            candidates = parse_srcset_candidates(raw)
            kept = [f"{url} {descriptor}".strip() for url, descriptor in candidates if asset_reference_allowed(url)]
            if len(kept) != len(candidates):
                removed.append(f"stripped {len(candidates) - len(kept)} {lowered} candidate(s) on <{tag}>")
                if kept:
                    node.attrs[name] = ", ".join(kept)
                else:
                    del node.attrs[name]
        elif lowered == "style":
            before = len(removed)
            cleaned = _clean_declarations(raw, removed)
            if len(removed) != before:
                node.attrs[name] = cleaned
        elif lowered in _LINK_ATTRS and not link_scheme_allowed(raw):
            del node.attrs[name]
            removed.append(f"stripped {lowered}={raw.strip()[:80]} on <{tag}>")


def sanitize_site_html(html: str) -> SanitizedHtml:
    """``html`` with everything a published site may not carry stripped (see the module docstring)."""
    removed: list[str] = []
    tree = LexborHTMLParser(html)
    root = tree.root
    if root is None:
        return SanitizedHtml(html="", removed=("input had no content",))
    _drop_elements(root, removed)
    _clean_style_elements(tree, removed)
    for node in root.traverse(include_text=False):
        if node.tag:
            _clean_attributes(node, removed)
    out = tree.html or ""
    if html.lstrip()[:9].lower() == "<!doctype" and out.lstrip()[:9].lower() != "<!doctype":
        out = "<!DOCTYPE html>" + out
    return SanitizedHtml(html=out, removed=tuple(removed))
```

- [ ] **Step 4: Run the tests.**

Run: `DESIGN_PYTEST test_site_sanitize.py`
Expected: all pass. If `test_cleaning_twice_changes_nothing` reports a difference, it is the
serializer normalising whitespace inside a `<style>`: the second pass must not replace a style
element whose cleaning removed nothing (the `len(removed) == before` guard) — check that guard.

- [ ] **Step 5: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_sanitize.py subsystems/clue-design/apps/api/tests/test_site_sanitize.py
git commit -m "design API: the published-site cleaner (strip script, handlers, frames, foreign bytes and CSS urls; never refuse)"
```

### Task 17: The hardened-Chromium renderer — `render_site`, `read_section_schema`, `capture_site_screenshot`

Contract 3 and D2: one fresh headless Chromium per render, a stripped environment, the network
refused in layers, a time limit and an output cap; agent sections load only inside the page, from
`data:` URLs. Probes on 2026-10-11 (Playwright 1.61, Chromium 149) confirmed: a `data:` module
whose host imports are rewritten to `data:` shims imports and renders under
`script-src 'unsafe-inline' data:`; `Function` via a constructor is blocked by the CSP; a page stuck
in a loop still times out `wait_for_function` and closes in 20 ms; `add_script_tag` loads the
1.2 MB bundle under the CSP; and `add_style_tag` hangs with JavaScript off (so the screenshot page
gets its CSS inside the HTML). The CSS is compiled by the design editor's Tailwind toolchain
(`subsystems/clue-design/scripts/web_static_css.mjs`, reused unchanged) over the rendered HTML text.

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/hardened_browser.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_render.py` (the render functions)
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_export.py:1243-1276`
  (extract `compile_tailwind_css` from `_compile_static_css`, byte-identical)
- Modify: `subsystems/clue-design/apps/api/pyproject.toml:45` (`playwright>=1.48,<2`) and `uv.lock`
- Modify: `.env.example`, `subsystems/clue-design/.env.example` (`LUMEN_SITE_RENDER_CHROMIUM_SANDBOX`)
- Modify: `subsystems/clue-design/apps/api/tests/site_kit_support.py` (section fixtures)
- Create: `subsystems/clue-design/apps/api/tests/test_site_render.py`

**Interfaces:**
- Consumes: `dist/render-browser.js` and its page contract (Task 15); `sanitize_site_html`
  (Task 16); `SectionModule`, `RenderedPage`, `SiteRender`, `SiteRenderError`, the codes,
  `pinned_modules`, `site_routes`, `site_kit_dist` (Task 11).
- Produces:
  - `hardened_browser.py`: `HARDENED_CHROMIUM_ARGS`, `CHROMIUM_SANDBOX_ENV`,
    `class HardenedBrowserUnavailable(Exception)`, `chromium_sandbox_enabled() -> bool`,
    `stripped_env(home: str) -> dict[str, str]`,
    `hardened_context(*, javascript: bool, viewport: dict | None = None, device_scale_factor: float = 1.0)`
    (context manager yielding `(context, blocked: list[str])`), `hardened_page(...)` (same
    arguments, yields `(page, blocked)`);
  - `site_render.py`: `DEFAULT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024`,
    `render_site(site, brand, sections, *, base_path: str, routes: Sequence[str] | None = None, timeout_s: float = 20.0, max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES, node_bin: str = "node") -> SiteRender`,
    `read_section_schema(module_js: str, *, timeout_s: float = 10.0) -> dict`,
    `capture_site_screenshot(page: RenderedPage, css: str, *, width: int, full_page: bool = True, height: int = 900, scale: float = 1.0, timeout_s: float = 20.0) -> bytes`,
    `site_page_html(page: RenderedPage, css: str) -> str`;
  - `web_export.compile_tailwind_css(html: str, input_css: str, node_bin: str, timeout_seconds: int = 120) -> str`;
  - test helpers `QUOTE_SCHEMA`, `QUOTE_JS`, `section_module(name: str, module_js: str, props_schema: dict = QUOTE_SCHEMA, css: str = "") -> SectionModule`,
    `site_with_section(document_id: str, name: str, digest: str, props: dict) -> dict`,
    `chromium_available() -> bool`;
  - env `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX` (default `1`).

- [ ] **Step 1: Add the section fixtures** to `apps/api/tests/site_kit_support.py`:

```python
QUOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "surface": {"type": "string", "enum": ["page", "card", "muted", "brandSubtle", "brand", "inverse"]},
        "quote": {"type": "string", "minLength": 1},
    },
    "required": ["id", "surface", "quote"],
    "additionalProperties": False,
}

#: A compiled agent section exactly as esbuild emits one (ESM, automatic JSX, three host imports).
QUOTE_JS = """import { jsx } from "react/jsx-runtime";
import { z } from "zod";
export const schema = z.object({ id: z.string(), surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]), quote: z.string().min(1) }).strict();
export function render(props, kit) {
  return jsx(kit.Shell, { surface: props.surface, children: jsx("blockquote", { className: "brand-heading font-headline text-headline", children: props.quote }) });
}
"""


def section_module(name: str, module_js: str, props_schema: dict[str, Any] | None = None, css: str = "") -> Any:
    from lumen_api.site_render import SectionModule

    return SectionModule(
        name=name,
        digest=hashlib.sha256(module_js.encode("utf-8")).hexdigest(),
        module_js=module_js,
        css=css,
        props_schema=props_schema if props_schema is not None else QUOTE_SCHEMA,
    )


def site_with_section(document_id: str, name: str, digest: str, props: dict[str, Any]) -> dict[str, Any]:
    """A one-page site holding one agent section, with Garner's shell."""
    site = garner_site(document_id)
    site["pages"] = {"/": {"root": {"props": {"title": "Section test"}}, "content": [{"type": name, "props": props}]}}
    site["agent_sections"] = {name: digest}
    return site


@functools.lru_cache(maxsize=1)
def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False
```

- [ ] **Step 2: Write the failing tests** in `apps/api/tests/test_site_render.py`:

```python
"""The hardened-Chromium site renderer (Wave 2 Contract 3) — the master plan's Review focus 8: a section that loops,
prints a huge page, tries the network or reads local files ends as a typed failure, nothing leaves,
and the next render still works."""

from __future__ import annotations

import io
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from PIL import Image

from lumen_api import web_export
from lumen_api.site_render import (
    OUTPUT_TOO_LARGE,
    RENDER_FAILED,
    RENDER_TIMEOUT,
    SECTION_MODULE_MISSING,
    RenderedPage,
    SiteRenderError,
    capture_site_screenshot,
    read_section_schema,
    render_site,
)
from site_kit_support import (
    QUOTE_JS,
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    section_module,
    site_with_section,
)

HEAD = 'import { jsx } from "react/jsx-runtime";\nimport { z } from "zod";\nexport const schema = z.object({ id: z.string(), surface: z.enum(["page"]) }).strict();\n'
HOSTILE_SCHEMA = {
    "type": "object",
    "properties": {"id": {"type": "string"}, "surface": {"type": "string", "enum": ["page"]}},
    "required": ["id", "surface"],
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def _browser_and_bundle() -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()


def hostile(name: str, body: str):
    module = section_module(name, HEAD + body, props_schema=HOSTILE_SCHEMA)
    return site_with_section(f"doc_{name.lower()}", name, module.digest, {"id": "h", "surface": "page"}), module


class _Recorder(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        _Recorder.hits.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture()
def listener():
    _Recorder.hits = []
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def test_a_site_renders_every_route_with_its_css_and_rebased_links() -> None:
    result = render_site(garner_site("doc_render"), garner_brand(), [], base_path="/acme-site")
    assert [page.route for page in result.pages] == ["/", "/analysis"]
    assert 'class="brand-root"' in result.pages[0].html
    assert 'href="/acme-site/analysis"' in result.pages[0].html
    assert ".bg-surface-brand-subtle" in result.css  # the StatsBand's surface, compiled from the HTML


def test_an_agent_section_renders_from_its_module_with_its_own_css() -> None:
    module = section_module("Quote", QUOTE_JS, css=".quote-extra{color:inherit}")
    site = site_with_section("doc_quote", "Quote", module.digest, {"id": "q", "surface": "brand", "quote": "Fewer surprises."})
    result = render_site(site, garner_brand(), [module], base_path="")
    html = result.pages[0].html
    assert '<div data-agent-section="Quote"><section class="bg-surface-brand text-on-surface-brand">' in html
    assert "Fewer surprises." in html
    assert ".quote-extra{color:inherit}" in result.css


def test_a_missing_or_stale_module_is_a_typed_refusal() -> None:
    module = section_module("Quote", QUOTE_JS)
    site = site_with_section("doc_missing", "Quote", module.digest, {"id": "q", "surface": "page", "quote": "Q"})
    with pytest.raises(SiteRenderError) as missing:
        render_site(site, garner_brand(), [], base_path="")
    assert missing.value.code == SECTION_MODULE_MISSING
    stale = section_module("Quote", QUOTE_JS + "// changed\n")
    with pytest.raises(SiteRenderError) as tampered:
        render_site(site, garner_brand(), [type(stale)(name="Quote", digest=module.digest, module_js=stale.module_js, css="", props_schema={})], base_path="")
    assert tampered.value.code == SECTION_MODULE_MISSING


def test_read_section_schema_reads_the_props_schema_inside_the_page() -> None:
    schema = read_section_schema(QUOTE_JS)
    assert sorted(schema["properties"]) == ["id", "quote", "surface"]
    no_id = 'import { z } from "zod";\nexport const schema = z.object({ surface: z.string() }).strict();\nexport function render() { return null; }\n'
    with pytest.raises(SiteRenderError) as refused:
        read_section_schema(no_id)
    assert refused.value.code == RENDER_FAILED and 'the props need "id"' in refused.value.message


def test_a_section_that_never_finishes_times_out() -> None:
    site, module = hostile("Loop", "export function render(props, kit) { for (;;) {} }\n")
    started = time.monotonic()
    with pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", timeout_s=3)
    assert refused.value.code == RENDER_TIMEOUT
    assert time.monotonic() - started < 15


def test_a_huge_page_is_refused_by_size() -> None:
    body = 'export function render(props, kit) { return jsx("div", { children: Array.from({ length: 20000 }, (_, i) => jsx("p", { children: "x".repeat(100) }, i)) }); }\n'
    site, module = hostile("Huge", body)
    with pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", max_output_bytes=1_000_000)
    assert refused.value.code == OUTPUT_TOO_LARGE


def test_nothing_leaves_the_page_and_the_next_render_still_works(listener: int) -> None:
    body = f"""
try {{ fetch("http://127.0.0.1:{listener}/fetch").catch(() => {{}}); }} catch (e) {{}}
try {{ new Image().src = "http://127.0.0.1:{listener}/img"; }} catch (e) {{}}
try {{ new WebSocket("ws://127.0.0.1:{listener}/ws"); }} catch (e) {{}}
try {{ navigator.sendBeacon("http://127.0.0.1:{listener}/beacon", "x"); }} catch (e) {{}}
let evalBlocked = false;
try {{ (() => 0).constructor("return 1")(); }} catch (e) {{ evalBlocked = true; }}
await new Promise((resolve) => setTimeout(resolve, 400));
export function render(props, kit) {{ return jsx("div", {{ children: "rendered eval-blocked=" + evalBlocked }}); }}
"""
    site, module = hostile("Beacon", body)
    result = render_site(site, garner_brand(), [module], base_path="")
    time.sleep(0.5)
    assert _Recorder.hits == []
    assert "rendered eval-blocked=true" in result.pages[0].html
    assert any("blocked a network request to ws://127.0.0.1" in warning for warning in result.warnings)
    again = render_site(garner_site("doc_after"), garner_brand(), [], base_path="")
    assert len(again.pages) == 2


def test_a_section_cannot_read_local_files(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET-1f2e3d")
    body = f"""
let text = "blocked";
try {{ const request = new XMLHttpRequest(); request.open("GET", "file://{secret}", false); request.send(); text = request.responseText || "blocked"; }} catch (e) {{}}
export function render(props, kit) {{ return jsx("div", {{ children: text }}); }}
"""
    site, module = hostile("FileRead", body)
    result = render_site(site, garner_brand(), [module], base_path="")
    assert "SECRET-1f2e3d" not in result.pages[0].html
    assert "blocked" in result.pages[0].html


def test_the_screenshot_shows_the_page_and_fetches_nothing(listener: int) -> None:
    page = RenderedPage(
        route="/",
        html=f'<!doctype html><html><head><title>T</title></head><body><div class="hero"></div><img src="http://127.0.0.1:{listener}/x.png"></body></html>',
    )
    png = capture_site_screenshot(page, ".hero{background:rgb(255,0,0);height:2000px}", width=400, height=300, full_page=False)
    time.sleep(0.3)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    assert image.size == (400, 300) and image.getpixel((200, 150)) == (255, 0, 0)
    assert _Recorder.hits == []


def test_compile_tailwind_css_is_the_shared_compile() -> None:
    css = web_export.compile_tailwind_css(
        '<div class="bg-surface-page"></div>',
        '@import "tailwindcss";\n@theme inline {\n  --color-surface-page: var(--brand-surface-page);\n}\n',
        "node",
        timeout_seconds=60,
    )
    assert ".bg-surface-page" in css
```

- [ ] **Step 3: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_render.py`
Expected: FAIL — `ImportError: cannot import name 'render_site'`.

- [ ] **Step 4: Extract the shared Tailwind compile** in `web_export.py`. Replace
  `_compile_static_css` (`:1243-1276`) with:

```python
def compile_tailwind_css(html: str, input_css: str, node_bin: str, timeout_seconds: int = 120) -> str:
    """Run the editor's Tailwind v4 toolchain (``scripts/web_static_css.mjs``) over ``html``
    against ``input_css``. Raises ``WebExportCompileError`` (stderr attached) on a non-zero exit —
    never returns an empty/unstyled stylesheet silently. Shared by the WebDoc export below and the
    Puck site render (``lumen_api.site_render``); the scanner only ever READS the html as text."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        html_file = tmp_path / "page.html"
        input_file = tmp_path / "input.css"
        out_file = tmp_path / "site.css"
        html_file.write_text(html, encoding="utf-8")
        input_file.write_text(input_css, encoding="utf-8")
        try:
            result = subprocess.run(
                [node_bin, STATIC_CSS_SCRIPT, str(html_file), str(input_file), str(out_file)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WebExportCompileError(f"static css compile failed to run: {error}") from error
        if result.returncode != 0:
            raise WebExportCompileError(
                (result.stderr or result.stdout or "").strip()
                or f"static css compile exited {result.returncode}"
            )
        return out_file.read_text(encoding="utf-8")


def _compile_static_css(
    html: str, theme: _CompiledTheme, node_bin: str, timeout_seconds: int = 120
) -> str:
    """Run the editor's Tailwind v4 toolchain over ``html`` against the doc's ``@theme`` tokens.

    ``timeout_seconds`` defaults to the export's own long bound (a whole page's worth of markup,
    run as a build step nobody is waiting on). A caller compiling one SECTION inside a tool call
    passes something far shorter — see :func:`compile_section_css`."""
    return compile_tailwind_css(html, _build_input_css(theme), node_bin, timeout_seconds)
```

- [ ] **Step 5: Create `lumen_api/hardened_browser.py`.**

```python
"""Hardened headless Chromium for anything that loads agent-written or site HTML (D2, founder
ruling 2026-10-11).

One fresh browser per use, launched with a stripped environment, and the network refused in
layers, any one of which is enough on its own:

1. the page's own CSP (the caller's markup);
2. ``--host-resolver-rules=MAP * ~NOTFOUND``: no hostname resolves;
3. a dead-end proxy (``127.0.0.1:9``, the discard port) with loopback NOT bypassed
   (``<-loopback>``), so an IP literal or localhost goes nowhere either;
4. WebRTC forced through that proxy (``disable_non_proxied_udp``);
5. Playwright: the context is offline, service workers are blocked, every routed request is
   aborted, and every WebSocket is mocked (its route never calls ``connect_to_server``; closing it
   from the handler hangs the page under the render CSP — Playwright 1.61, probe 2026-10-11).

Plus a V8 heap cap, Chromium's own sandbox (``LUMEN_SITE_RENDER_CHROMIUM_SANDBOX``, default on)
and the process-wide capture slots shared with the thumbnail and PDF captures. The browser is
closed — which also kills a page stuck in a loop — however the caller's block ends.

Sync Playwright: call from a thread with no running event loop (``asyncio.to_thread``).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .document_thumbnails import _CAPTURE_SLOTS

CHROMIUM_SANDBOX_ENV = "LUMEN_SITE_RENDER_CHROMIUM_SANDBOX"
HARDENED_CHROMIUM_ARGS: tuple[str, ...] = (
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--proxy-server=http://127.0.0.1:9",
    "--proxy-bypass-list=<-loopback>",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--no-pings",
    "--js-flags=--max-old-space-size=256",
)
DEFAULT_VIEWPORT = {"width": 1440, "height": 900}


class HardenedBrowserUnavailable(Exception):
    """Playwright is not installed in this process."""


def chromium_sandbox_enabled() -> bool:
    return os.environ.get(CHROMIUM_SANDBOX_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def stripped_env(home: str) -> dict[str, str]:
    """The browser process's whole environment: no API keys, database URLs or tokens."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "TMPDIR": home}


@contextmanager
def hardened_context(
    *, javascript: bool, viewport: dict[str, int] | None = None, device_scale_factor: float = 1.0
) -> Iterator[tuple[Any, list[str]]]:
    """A fresh hardened browser context. Yields ``(context, blocked)``; ``blocked`` collects the URL
    of every request and WebSocket the context refused."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise HardenedBrowserUnavailable("playwright is not installed") from error
    home = tempfile.mkdtemp(prefix="clue-hardened-")
    blocked: list[str] = []

    def refuse(route: Any) -> None:
        blocked.append(route.request.url)
        route.abort("blockedbyclient")

    try:
        with _CAPTURE_SLOTS, sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=list(HARDENED_CHROMIUM_ARGS),
                env=stripped_env(home),
                chromium_sandbox=chromium_sandbox_enabled(),
                timeout=30_000,
            )
            try:
                context = browser.new_context(
                    java_script_enabled=javascript,
                    offline=True,
                    service_workers="block",
                    accept_downloads=False,
                    viewport=viewport or dict(DEFAULT_VIEWPORT),
                    device_scale_factor=device_scale_factor,
                )
                context.route("**/*", refuse)
                context.route_web_socket("**/*", lambda socket: blocked.append(socket.url))
                yield context, blocked
            finally:
                browser.close()
    finally:
        shutil.rmtree(home, ignore_errors=True)


@contextmanager
def hardened_page(
    *, javascript: bool, viewport: dict[str, int] | None = None, device_scale_factor: float = 1.0
) -> Iterator[tuple[Any, list[str]]]:
    """One page in a fresh hardened context. The page is closed, then the browser."""
    from playwright.sync_api import Error as PlaywrightError

    with hardened_context(javascript=javascript, viewport=viewport, device_scale_factor=device_scale_factor) as (context, blocked):
        page = context.new_page()
        try:
            yield page, blocked
        finally:
            try:
                page.close()
            except PlaywrightError:
                pass  # a page stuck in a loop: closing the browser (above) still ends it
```

- [ ] **Step 6: Add the render functions** to `lumen_api/site_render.py`. Add to its imports:

```python
import functools
import json
import secrets
import time
from collections.abc import Mapping

from selectolax.lexbor import LexborHTMLParser

from . import web_export
from .hardened_browser import HardenedBrowserUnavailable, hardened_page
```
  and append:

```python
DEFAULT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
SCHEMA_MAX_OUTPUT_BYTES = 1024 * 1024
CSS_TIMEOUT_SECONDS = 60
_FONT_SETTLE_MS = 300
#: The render page's policy: the bundle runs inline, agent sections arrive as data: modules, and
#: nothing else may load, connect, frame or submit.
_RENDER_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' data:; style-src 'none'; img-src 'none'; "
    "font-src 'none'; media-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; "
    "worker-src 'none'; manifest-src 'none'; form-action 'none'; base-uri 'none'"
)
_DONE = "() => { const c = window.__clueRender; return !!c && c.done === true; }"
_HEAD = "() => { const c = window.__clueRender; return {nonce: c.nonce, size: c.size, code: c.code, error: c.error}; }"
_RESULT = "() => window.__clueRender.result"


@functools.lru_cache(maxsize=4)
def _read_bundle(path: str, mtime_ns: int) -> str:
    return Path(path).read_text(encoding="utf-8")


def _render_bundle() -> str:
    path = site_kit_dist() / "render-browser.js"
    if not path.is_file():
        raise SiteRenderError(
            RENDER_FAILED,
            f"the site render bundle is not built ({path} is missing): run `npm run build -w @clue/site-kit` in apps/frontend",
        )
    return _read_bundle(str(path), path.stat().st_mtime_ns)


def _shell_html(payload: JsonObject) -> str:
    # "<" escaped everywhere, so no string in the data can end or confuse the inert script element.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_RENDER_CSP}">'
        "</head><body>"
        f'<script id="clue-render-input" type="application/json">{data}</script>'
        "</body></html>"
    )


def _run_shell(payload: JsonObject, *, timeout_s: float, max_output_bytes: int) -> tuple[JsonObject, list[str]]:
    """Run the render bundle over ``payload`` in a hardened page; return (result, blocked URLs)."""
    try:
        from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout
    except ImportError as error:
        raise SiteRenderError(RENDER_FAILED, "playwright is not installed") from error
    bundle = _render_bundle()
    nonce = secrets.token_hex(16)
    deadline = time.monotonic() + timeout_s

    def remaining_ms() -> float:
        return max(1.0, (deadline - time.monotonic()) * 1000)

    try:
        with hardened_page(javascript=True) as (page, blocked):
            page.set_content(
                _shell_html({**payload, "nonce": nonce, "maxOutputBytes": max_output_bytes}),
                wait_until="domcontentloaded",
                timeout=remaining_ms(),
            )
            page.add_script_tag(content=bundle)
            page.wait_for_function(_DONE, timeout=remaining_ms(), polling=50)
            head = page.evaluate(_HEAD)
            if not isinstance(head, dict) or head.get("nonce") != nonce:
                raise SiteRenderError(RENDER_FAILED, "the render page answered without its nonce")
            if head.get("code"):
                raise SiteRenderError(str(head["code"]), str(head.get("error") or head["code"]))
            size = head.get("size")
            if not isinstance(size, int) or size > max_output_bytes:
                raise SiteRenderError(OUTPUT_TOO_LARGE, f"the rendered site is larger than {max_output_bytes} characters")
            result = page.evaluate(_RESULT)
            return (result if isinstance(result, dict) else {}), list(blocked)
    except PlaywrightTimeout as error:
        raise SiteRenderError(RENDER_TIMEOUT, f"the site did not render within {timeout_s:g}s") from error
    except PlaywrightError as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
    except HardenedBrowserUnavailable as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error


def _scan_text(html: str) -> str:
    """What the Tailwind scanner reads: the page without the clones (their captured class names
    must not mint utilities for our markup — the WebDoc W7 lesson, web_export._document_only_html)
    and without <style> text."""
    tree = LexborHTMLParser(html)
    for node in list(tree.css("[data-lumen-fragment]")):
        node.decompose()
    for node in list(tree.css("style")):
        node.decompose()
    return tree.html or ""


def _compile_css(pages: Sequence[RenderedPage], tailwind_theme: str, node_bin: str) -> str:
    try:
        web_export.require_static_css_toolchain(node_bin)
        return web_export.compile_tailwind_css(
            "\n".join(_scan_text(page.html) for page in pages),
            '@import "tailwindcss";\n' + tailwind_theme,
            node_bin,
            timeout_seconds=CSS_TIMEOUT_SECONDS,
        )
    except web_export.WebExportCompileError as error:
        raise SiteRenderError(RENDER_FAILED, f"the site's stylesheet did not compile: {error.stderr}") from error


def render_site(
    site: Mapping[str, Any],
    brand: Mapping[str, Any],
    sections: Sequence[SectionModule],
    *,
    base_path: str,
    routes: Sequence[str] | None = None,
    timeout_s: float = 20.0,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    node_bin: str = "node",
) -> SiteRender:
    """Render ``site`` (Contract 1) with ``brand`` (site-kit BrandData) and its agent ``sections``.

    ``base_path`` is where the site is served ("/acme-site"); "" leaves /route links as written.
    Each page comes back as a whole document without CSS; ``css`` is the site's compiled Tailwind
    plus each agent section's own stored CSS. Raises :class:`SiteRenderError`."""
    modules = pinned_modules(dict(site), sections)
    known = site_routes(dict(site))
    wanted = list(routes) if routes is not None else known
    missing = [route for route in wanted if route not in known]
    if missing:
        raise SiteRenderError(RENDER_FAILED, "the site has no page " + ", ".join(missing))
    payload = {
        "mode": "render",
        "site": {"title": site.get("title") or "", "pages": site.get("pages") or {}, "shell": site.get("shell")},
        "brand": dict(brand),
        "basePath": base_path,
        "routes": wanted,
        "sections": [{"name": module.name, "moduleJs": module.module_js} for module in modules],
    }
    result, blocked = _run_shell(payload, timeout_s=timeout_s, max_output_bytes=max_output_bytes)
    pages = [RenderedPage(route=str(page["route"]), html=str(page["html"])) for page in result.get("pages") or []]
    css = _compile_css(pages, str(result.get("tailwindTheme") or ""), node_bin)
    module_css = "\n".join(module.css for module in modules if module.css)
    warnings = [str(warning) for warning in result.get("warnings") or []]
    warnings += [f"blocked a network request to {url[:160]}" for url in dict.fromkeys(blocked)]
    return SiteRender(pages=pages, css=f"{css}\n{module_css}" if module_css else css, warnings=warnings)


def read_section_schema(module_js: str, *, timeout_s: float = 10.0) -> JsonObject:
    """Import ONE compiled agent section inside the hardened render page and return its props JSON
    Schema (Lane B6 calls this at compile time; nothing else imports an agent module on the server).
    Refuses a module whose schema is not a zod object, lacks id or surface, carries className or
    style, or has no render function."""
    result, _ = _run_shell(
        {"mode": "schema", "sections": [{"name": "Section", "moduleJs": module_js}]},
        timeout_s=timeout_s,
        max_output_bytes=SCHEMA_MAX_OUTPUT_BYTES,
    )
    errors = result.get("errors")
    if errors:
        raise SiteRenderError(RENDER_FAILED, "; ".join(str(error) for error in errors))
    props = result.get("props")
    if not isinstance(props, dict):
        raise SiteRenderError(RENDER_FAILED, "the section's props schema is not an object")
    return props


def site_page_html(page: RenderedPage, css: str) -> str:
    """The page as one document with the site's compiled CSS in its head."""
    if not css:
        return page.html
    style = '<style id="site-static-css">' + css.replace("</", "<\\/") + "</style>"
    return web_export._inject_before_head_close(page.html, style)


def capture_site_screenshot(
    page: RenderedPage,
    css: str,
    *,
    width: int,
    full_page: bool = True,
    height: int = 900,
    scale: float = 1.0,
    timeout_s: float = 20.0,
) -> bytes:
    """A PNG of ``page`` styled by ``css``, sanitized, in a hardened page with JavaScript OFF and
    the network blocked. Its images and fonts must already be ``data:`` URIs
    (``web_pdf.inline_asset_store_refs``): nothing else can load."""
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

    from .site_sanitize import sanitize_site_html

    html = sanitize_site_html(site_page_html(page, css)).html
    timeout_ms = timeout_s * 1000
    try:
        with hardened_page(javascript=False, viewport={"width": width, "height": height}, device_scale_factor=scale) as (shot, _blocked):
            shot.set_content(html, wait_until="load", timeout=timeout_ms)
            shot.wait_for_timeout(_FONT_SETTLE_MS)
            return shot.screenshot(type="png", full_page=full_page, timeout=timeout_ms)
    except PlaywrightTimeout as error:
        raise SiteRenderError(RENDER_TIMEOUT, f"the screenshot did not finish within {timeout_s:g}s") from error
    except PlaywrightError as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
    except HardenedBrowserUnavailable as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
```

- [ ] **Step 7: Raise the Playwright floor** (`route_web_socket` arrived in 1.48). In
  `subsystems/clue-design/apps/api/pyproject.toml:45`, `"playwright>=1.45,<2",` →
  `"playwright>=1.48,<2",` then run `uv lock` from the repo root.
  Expected: `uv.lock` changes only in the `lumen-api` specifier line (`>=1.48,<2`); the locked
  version stays `1.61.0`.

- [ ] **Step 8: Document the sandbox switch** in `.env.example` and
  `subsystems/clue-design/.env.example`, right after the `LUMEN_SITE_KIT_DIST=` block (Task 11):

```
# Puck sites (Wave 2): run the hardened render page with Chromium's own sandbox. Default ON.
# Set 0 only on a host where Chromium cannot start sandboxed ("No usable sandbox"), and record it.
LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=1
```
  Add `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=1` to the lane's `.env` too.

- [ ] **Step 9: Run the tests and the web neighbours of the refactor.**

Run: `DESIGN_PYTEST test_site_render.py` then `DESIGN_PYTEST test_web_export.py` then `DESIGN_PYTEST test_web_pdf_export.py`
Expected: all pass (the web export and PDF are byte-identical after the extraction).

- [ ] **Step 10: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/hardened_browser.py subsystems/clue-design/apps/api/lumen_api/site_render.py subsystems/clue-design/apps/api/lumen_api/web_export.py subsystems/clue-design/apps/api/pyproject.toml uv.lock .env.example subsystems/clue-design/.env.example subsystems/clue-design/apps/api/tests/site_kit_support.py subsystems/clue-design/apps/api/tests/test_site_render.py
git commit -m "design API: the hardened-Chromium site renderer (render, section schema, screenshot) with layered network blocking and hostile-section tests"
```

## A6 — thumbnails

### Task 18: Site thumbnails — render, sanitize, inline the bytes, capture with the network blocked

The thumbnail route sends anything not `web` down the scene engine
(`lumen_api/main.py:3953-4012`), and labels a web failure `render_failed` but anything else
`export_failed` (`:4052-4056`). A site gets its own arm: `render_site` → `site_page_html` →
`inline_asset_store_refs` → `capture_site_screenshot` (which sanitizes and runs with JavaScript off
and the network blocked). The cache by `(document, version)` is unchanged (`:3938-3945,4075-4081`).

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/site_publish.py` (starts with the thumbnail)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:3953-4074` (thumbnail route)
- Create: `subsystems/clue-design/apps/api/tests/test_site_thumbnails.py`

**Interfaces:**
- Consumes: `render_site`, `site_page_html`, `capture_site_screenshot`, `RenderedPage` (Task 17);
  `web_pdf.inline_asset_store_refs(html, read_blob, *, cache=None) -> (html, missing)`;
  `load_section_modules`, `SiteInputsUnavailable` (Task 11).
- Produces: `site_publish.site_thumbnail_png(document: JsonObject, *, blobs, brand: JsonObject, sections: Sequence[SectionModule], node_bin: str = "node") -> bytes`
  (724×543 PNG of the top of `/`, the gallery card's 4:3 at 2×).

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_site_thumbnails.py`:

```python
"""Gallery thumbnails for Puck sites (Wave 2 Lane A, Task 18)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import make_blob_store, make_client
from lumen_api import site_publish
from lumen_api.main import create_app
from site_kit_support import chromium_available, ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, install_site_inputs, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def stored(client: TestClient, document_id: str) -> None:
    site, brand = hold_site_images(garner_site(document_id), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)


def test_a_site_thumbnail_is_captured_once_then_served_from_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    stored(client, "site_thumb")
    first = client.get("/documents/site_thumb/thumbnail?v=0")
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert Image.open(io.BytesIO(first.content)).size == (724, 543)

    def must_not_run(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("a cached thumbnail must not be captured again")

    monkeypatch.setattr(site_publish, "site_thumbnail_png", must_not_run)
    assert client.get("/documents/site_thumb/thumbnail?v=0").content == first.content


def test_a_site_thumbnail_without_its_brand_is_a_typed_502(client: TestClient) -> None:
    from lumen_api.site_doc_inputs import brand_loader_not_composed

    stored(client, "site_thumb_nobrand")
    client.app.state.site_brand_loader = brand_loader_not_composed
    response = client.get("/documents/site_thumb_nobrand/thumbnail")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "thumbnail.render_failed"


def test_a_failed_site_render_is_labelled_render_failed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api.site_render import RENDER_TIMEOUT, SiteRenderError

    stored(client, "site_thumb_slow")

    def slow(*_args: object, **_kwargs: object) -> bytes:
        raise SiteRenderError(RENDER_TIMEOUT, "the site did not render within 20s")

    monkeypatch.setattr(site_publish, "site_thumbnail_png", slow)
    response = client.get("/documents/site_thumb_slow/thumbnail")
    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "thumbnail.render_failed", "message": "the site did not render within 20s"}
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_thumbnails.py`
Expected: FAIL — `ImportError: cannot import name 'site_publish'`.

- [ ] **Step 3: Create `lumen_api/site_publish.py` with the thumbnail.**

```python
"""Builders that turn a stored Puck site into something people see: the gallery thumbnail (Task
18), the publish package (Task 20), and the ZIP and PDF exports (Task 22). Every one renders
through ``site_render.render_site`` (agent code only inside the hardened page) and cleans the
result with ``site_sanitize.sanitize_site_html`` before anything sees it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .site_render import RenderedPage, SectionModule, capture_site_screenshot, render_site, site_page_html
from .web_pdf import inline_asset_store_refs

JsonObject = dict[str, Any]

#: The gallery card's own 4:3, captured at half scale (724×543 output) — web_thumbnail_png's frame.
THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT, THUMBNAIL_SCALE = 1448, 1086, 0.5


def site_thumbnail_png(
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    node_bin: str = "node",
) -> bytes:
    """The top of the site's home page as the gallery card shows it."""
    render = render_site(document["scene"], brand, sections, base_path="", routes=["/"], node_bin=node_bin)
    home = render.pages[0]
    inlined, _missing = inline_asset_store_refs(site_page_html(home, render.css), blobs.read_blob)
    return capture_site_screenshot(
        RenderedPage(route=home.route, html=inlined),
        "",
        width=THUMBNAIL_WIDTH,
        height=THUMBNAIL_HEIGHT,
        full_page=False,
        scale=THUMBNAIL_SCALE,
    )
```

- [ ] **Step 4: The site arm in the thumbnail route.** In `main.py`:
  - add `site_publish,` to the `from . import (…)` block (`:47-54`), and add
    `from .site_doc_inputs import load_section_modules` beside the Task 12 import of
    `SiteInputsUnavailable`, and `from .site_render import SiteRenderError`;
  - at `:3955`, replace `if kind == "web":` with:

```python
                if kind == "site":
                    # Wave 2: a Puck site renders in the hardened page, is cleaned, and is captured
                    # with JavaScript off and the network blocked (site_publish).
                    data = site_publish.site_thumbnail_png(
                        document,
                        blobs=blobs,
                        brand=app.state.site_brand_loader(repo, blobs, document),
                        sections=load_section_modules(app.state.site_section_loader, repo, blobs, document["scene"]),
                        node_bin=app.state.web_export_node_bin,
                    )
                elif kind == "web":
```
  - after the `except document_thumbnails.ThumbnailUnavailable as error:` handler (`:4030-4034`), add:

```python
            except (SiteRenderError, SiteInputsUnavailable) as error:
                raise HTTPException(
                    status_code=502,
                    detail={"code": "thumbnail.render_failed", "message": str(error)},
                ) from error
```
  - in the `(CoreError, NotFoundError)` handler's code (`:4052-4056`), change `if kind == "web"` to
    `if kind in ("web", "site")`.

- [ ] **Step 5: Run the tests and the existing thumbnail suite.**

Run: `DESIGN_PYTEST test_site_thumbnails.py` then `DESIGN_PYTEST test_document_thumbnails.py`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_publish.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_site_thumbnails.py
git commit -m "design API: site thumbnails (hardened render, cleaned, captured with the network blocked), cached like the others"
```

## A7 — publishing

### Task 19: A per-publish CSP: the page origin serves a site under the script-free policy its manifest names

The origin sends one CSP for every publish (`platform/page_origin/clue_page_origin/routes.py:45-55`,
`delivery_csp()` from `subsystems/design/clue_design/publishes.py:527-537`), which allows inline
script. Contract 3 gives sites their own policy, chosen per publish: the manifest carries
`"delivery": "site"`, `reads.py` reads it beside `noindex` (`:85,97-98`), and the routes send it.

**Files:**
- Modify: `subsystems/design/clue_design/publishes.py:527-537`
- Modify: `platform/page_origin/clue_page_origin/reads.py:21-112`
- Modify: `platform/page_origin/clue_page_origin/routes.py:45-55,137-170`
- Modify: `tests/page_origin/conftest.py` (`FakePageReads.publish`)
- Modify: `tests/page_origin/test_routes.py`, `tests/design/test_publish_delivery.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `SITE_DELIVERY_CSP_META`, `SITE_DELIVERY_CSP_HEADER`,
  `delivery_csp(*, meta: bool = False, delivery: str = "web") -> str`,
  `manifest_delivery(manifest: object) -> str` (in `clue_design.publishes`);
  `ServedPublish.delivery: str = "web"`, `ServedPage.delivery: str = "web"`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/design/test_publish_delivery.py`
  (import `SITE_DELIVERY_CSP_HEADER`, `SITE_DELIVERY_CSP_META`, `manifest_delivery`):

```python
SITE_HEADER = (
    "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; media-src 'self'; connect-src 'none'; form-action 'none'; "
    "base-uri 'none'; frame-ancestors 'self'"
)


def test_the_site_csp_is_contract_3_byte_for_byte() -> None:
    assert SITE_DELIVERY_CSP_HEADER == SITE_HEADER
    assert SITE_DELIVERY_CSP_META == SITE_HEADER.removesuffix("; frame-ancestors 'self'")
    assert delivery_csp(delivery="site") == SITE_DELIVERY_CSP_HEADER
    assert delivery_csp(meta=True, delivery="site") == SITE_DELIVERY_CSP_META
    assert delivery_csp() == DELIVERY_CSP_HEADER  # a web publish is unchanged


def test_only_a_manifest_that_says_site_gets_the_site_policy() -> None:
    assert manifest_delivery({"delivery": "site"}) == "site"
    for other in ({}, {"delivery": "web"}, {"delivery": "SITE"}, None, "site"):
        assert manifest_delivery(other) == "web"
```
  Append to `tests/page_origin/test_routes.py` (import `SITE_DELIVERY_CSP_HEADER` beside
  `DELIVERY_CSP_HEADER`):

```python
def test_a_site_publish_is_served_under_the_site_policy_on_every_route(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("acme-site", "<html>home</html>", routes={"/": "<html>home</html>", "/analysis": "<html>a</html>"}, delivery="site")
    for path in ("/acme-site", "/acme-site/analysis", "/acme-site/manifest.json"):
        response = client.get(path, headers=edge())
        assert response.status_code == 200, path
        assert response.headers["content-security-policy"] == SITE_DELIVERY_CSP_HEADER, path
    reads.publish("annual-report", "<html>web</html>")
    assert client.get("/annual-report", headers=edge()).headers["content-security-policy"] == DELIVERY_CSP_HEADER
```
  In `tests/page_origin/conftest.py`, replace `FakePageReads.publish` and `active_page` with:

```python
    def publish(
        self,
        slug: str,
        html: str,
        *,
        noindex: bool = False,
        routes: dict[str, str] | None = None,
        workspace_id: str = WS,
        delivery: str = "web",
    ) -> None:
        """Publish a site; ``routes`` are its F5 page rows (none = a pre-F5 publish); ``delivery``
        "site" marks a Puck site publish (Wave 2 Contract 3) as its manifest does."""
        manifest = {
            "slug": slug,
            **({"robots": "noindex"} if noindex else {}),
            **({"delivery": "site"} if delivery == "site" else {}),
        }
        manifest_json = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        self.publishes[(workspace_id, slug)] = ServedPublish(
            html=html,
            html_digest=_sha(html),
            manifest_json=manifest_json,
            manifest_digest=_sha(manifest_json),
            noindex=noindex,
            delivery=delivery,
        )
        for route, page_html in (routes or {}).items():
            self.pages[(workspace_id, slug, route)] = page_html

    async def active_page(self, workspace_id: str, slug: str, route: str) -> ServedPage | None:
        # Mirrors DbPageReads: the publish must be live; then its page row, else ``/`` falls
        # back to the publish's own html (a pre-F5 publish), else nothing.
        publish = self.publishes.get((workspace_id, slug))
        if publish is None:
            return None
        html = self.pages.get((workspace_id, slug, route))
        if html is not None:
            return ServedPage(html=html, html_digest=_sha(html), noindex=publish.noindex, delivery=publish.delivery)
        if route == "/":
            return ServedPage(
                html=publish.html, html_digest=publish.html_digest, noindex=publish.noindex, delivery=publish.delivery
            )
        return None
```

- [ ] **Step 2: Run them to see them fail.**

Run: `PLATFORM_PYTEST tests/design/test_publish_delivery.py tests/page_origin/test_routes.py`
Expected: FAIL — `ImportError: cannot import name 'SITE_DELIVERY_CSP_HEADER'`.

- [ ] **Step 3: The site policy.** In `clue_design/publishes.py`, replace `delivery_csp` (`:535-536`) with:

```python
#: A Puck SITE publish (Wave 2 Contract 3). Published sites are script-free, so script is refused
#: outright; styles may be same-origin or inline (the theme and the clones' captured CSS are inline);
#: images and fonts same-origin or data:; media same-origin. Chosen per publish by the manifest's
#: ``delivery`` field (``manifest_delivery``).
SITE_DELIVERY_CSP_META = (
    "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; media-src 'self'; connect-src 'none'; form-action 'none'; base-uri 'none'"
)
SITE_DELIVERY_CSP_HEADER = SITE_DELIVERY_CSP_META + "; frame-ancestors 'self'"


def delivery_csp(*, meta: bool = False, delivery: str = "web") -> str:
    if delivery == "site":
        return SITE_DELIVERY_CSP_META if meta else SITE_DELIVERY_CSP_HEADER
    return DELIVERY_CSP_META if meta else DELIVERY_CSP_HEADER


def manifest_delivery(manifest: object) -> str:
    """Which policy a publish is served under: ``site`` only when its manifest says exactly so."""
    return "site" if isinstance(manifest, dict) and manifest.get("delivery") == "site" else "web"
```

- [ ] **Step 4: The reads.** In `platform/page_origin/clue_page_origin/reads.py`, change the
  import to `from clue_design.publishes import get_web_publish, get_web_publish_page, manifest_delivery`,
  add one field to each model:

```python
class ServedPublish(BaseModel):
    """The slice of an active publish the origin serves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    html: str
    html_digest: str
    manifest_json: str
    manifest_digest: str
    noindex: bool
    #: "site" for a Puck site publish (its manifest says so): served under the site CSP.
    delivery: str = "web"


class ServedPage(BaseModel):
    """One route of an active publish (F5 multipage), as the origin serves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    html: str
    html_digest: str
    noindex: bool
    delivery: str = "web"
```
  and in `DbPageReads`: in `active_publish`, add `delivery=manifest_delivery(manifest),` as the last
  argument of `ServedPublish(...)`; in `active_page`, replace from
  `noindex = isinstance(manifest, dict) and manifest.get("robots") == "noindex"` to the end with:

```python
        noindex = isinstance(manifest, dict) and manifest.get("robots") == "noindex"
        delivery = manifest_delivery(manifest)
        if row is not None:
            html = str(row["html"])
            return ServedPage(
                html=html, html_digest=str(row.get("html_digest") or _sha(html)), noindex=noindex, delivery=delivery
            )
        if route == "/":
            html = str(publish["html"])
            return ServedPage(
                html=html,
                html_digest=str(publish.get("html_digest") or _sha(html)),
                noindex=noindex,
                delivery=delivery,
            )
        return None
```

- [ ] **Step 5: The routes.** In `routes.py`, change `_page_headers` to take the delivery:

```python
def _page_headers(digest: str, *, noindex: bool, delivery: str = "web") -> dict[str, str]:
    headers = {
        "Cache-Control": _SHORT,
        "ETag": f'"sha256-{digest}"',
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": delivery_csp(delivery=delivery),
    }
    if noindex:
        headers["X-Robots-Tag"] = "noindex"
    return headers
```
  and pass `delivery=publish.delivery` in the `manifest` and `page` routes and
  `delivery=served.delivery` in `route_page`.

- [ ] **Step 6: Run the tests.**

Run: `PLATFORM_PYTEST tests/design/test_publish_delivery.py tests/page_origin/test_routes.py tests/page_origin/test_main.py`
Expected: all pass; every existing route test still sees `DELIVERY_CSP_HEADER`.

- [ ] **Step 7: Commit.**

```bash
git add subsystems/design/clue_design/publishes.py platform/page_origin/clue_page_origin/reads.py platform/page_origin/clue_page_origin/routes.py tests/page_origin/conftest.py tests/page_origin/test_routes.py tests/design/test_publish_delivery.py
git commit -m "page origin: a per-publish CSP; a site publish is served under the script-free site policy its manifest names"
```

### Task 20: The site publish package — clone pins, the font licence gate, render, clean, head, manifest

`build_site_publish_package` feeds the same `PublishPackage` the web path builds
(`web_export.py:325-358`), so every write after it is unchanged. The manifest must carry a
`custom_components` dict or the publish core's `persist_publish_assets(…, manifest["custom_components"].get("assets"))`
raises `KeyError` (`toolbelt/publishes.py:131-135`). Internal links are rebased to `/{slug}{route}` by
rendering with the site's `link_path` as the base path (the kit's `href()` covers our sections, the
shell, the clones' slots and links, `kit.Button` and `kit.Link`).

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_publish.py`
- Modify: `subsystems/clue-design/apps/api/tests/site_kit_support.py` (`garner_site_without_clones`)
- Create: `subsystems/clue-design/apps/api/tests/test_site_publish_package.py`

**Interfaces:**
- Consumes: `render_site`, `site_page_html`, `pinned_modules`, `SiteRenderError` (Tasks 11, 17);
  `sanitize_site_html` (Task 16); `check_site_document`, `SiteDocumentInvalid` (Task 11);
  `SITE_DELIVERY_CSP_META` via `delivery_csp(meta=True, delivery="site")` (Task 19);
  `web_export._gather_fonts`, `_font_manifest_entries`, `_seo_snippet`, `_inject_before_head_close`,
  `_escape_attr`, `_sha256`, `_canonical_json`, `ROBOTS_NOINDEX_META`, `PublishPackage`,
  `PublishedPage`; `PublicSiteAddress`.
- Produces:
  - `class SitePublishRefused(Exception)` (`.code`, `.message`), codes
    `site_publish.clone_unresolved` and `site_publish.clone_not_approved`;
  - `SITE_DELIVERY = "site"`; `_PUBLISHABLE_CLONE_STATUSES = frozenset({"approved", "deprecated"})` (Q5);
  - `gated_brand(brand, repo, blobs) -> tuple[JsonObject, Any]` (the licence gate's faces as the
    brand's fonts);
  - `site_delivery_csp(*, meta: bool, static_bundle: bool = False) -> str`;
  - `build_site_publish_package(repo, document, *, blobs, brand, sections, slug, site_address, default_description=None, default_social_preview_sha256=None, noindex=False, node_bin="node", fragment_status=None) -> PublishPackage`
    (`fragment_status: Callable[[str], str | None]`, default reads `repo.find_web_fragment`);
  - test helper `garner_site_without_clones(document_id: str) -> dict`.

- [ ] **Step 1: Add the test helper** to `site_kit_support.py`:

```python
def garner_site_without_clones(document_id: str) -> dict[str, Any]:
    """Garner's site with only our own sections (no registry needed), and a nav link to /analysis."""
    site = garner_site(document_id)
    for page in site["pages"].values():
        page["content"] = [item for item in page["content"] if item["type"] != "ClonedSection"]
    site["shell"] = {**site["shell"], "header": {**site["shell"]["header"], "nav": [{"label": "The analysis", "href": "/analysis"}]}}
    return site
```

- [ ] **Step 2: Write the failing tests** in `apps/api/tests/test_site_publish_package.py`:

```python
"""The site publish package (Wave 2 Contract 3) — the master plan's Review focus 5 and 7."""

from __future__ import annotations

import pytest

from clue_design.publishes import SITE_DELIVERY_CSP_META
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.public_address import PublicSiteAddress
from lumen_api.site_publish import SitePublishRefused, build_site_publish_package
from lumen_api.site_render import SECTION_MODULE_MISSING, SiteRenderError
from site_kit_support import (
    QUOTE_SCHEMA,
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    garner_site_without_clones,
    hold_site_images,
    section_module,
    store_site,
)

ADDRESS = PublicSiteAddress(origin="https://acme.pages.test", site_path="/acme-site", asset_origin="https://acme.pages.test")
HOSTILE_JS = """import { jsx, jsxs } from "react/jsx-runtime";
import { z } from "zod";
export const schema = z.object({ id: z.string(), surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]), quote: z.string().min(1) }).strict();
export function render(props, kit) {
  return jsxs(kit.Shell, { surface: props.surface, children: [
    jsx("div", { dangerouslySetInnerHTML: { __html: '<script>steal()</script><img src="https://collector.example/p.gif" onerror="steal()"><a href="javascript:steal()">x</a><iframe src="https://collector.example/f"></iframe><div style="background:url(https://collector.example/bg.png)">y</div>' } }),
    jsx("img", { src: "https://collector.example/direct.png", alt: "" }),
    jsx("p", { children: props.quote }),
  ] });
}
"""


@pytest.fixture(autouse=True)
def _browser_and_bundle() -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()


@pytest.fixture()
def blobs(design_storage, workspace_id: str) -> DesignBlobStore:
    return DesignBlobStore(design_storage, workspace_id)


def build(document_id: str, site: dict, brand: dict, sections: list, **extra):
    store_site(site)
    document = HybridRepository().require_document(document_id)
    return build_site_publish_package(
        HybridRepository(), document, blobs=extra.pop("blobs"), brand=brand, sections=sections, slug="acme-site", site_address=ADDRESS, **extra
    )


def test_a_site_package_is_script_free_with_its_policy_manifest_and_rebased_links(blobs: DesignBlobStore) -> None:
    site, brand = hold_site_images(garner_site_without_clones("pub_pkg"), garner_brand(), blobs)
    package = build("pub_pkg", site, brand, [], blobs=blobs, default_description="An analysis for SCSD")
    assert [page.route for page in package.pages] == ["/", "/analysis"]
    home = package.html
    assert f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">' in home
    assert '<meta name="description" content="An analysis for SCSD">' in home
    assert 'href="/acme-site/analysis"' in home
    assert 'id="site-static-css"' in home and "<script" not in home.lower()
    manifest = package.manifest
    assert manifest["delivery"] == "site" and manifest["custom_components"] == {}
    assert [entry["route"] for entry in manifest["pages"]] == ["/", "/analysis"]
    assert manifest["canonical_url"] == "https://acme.pages.test/acme-site"
    assert "font_families_included" in manifest and package.assets == {} and package.runtime_version is None


def test_agent_html_publishes_without_script_handlers_or_foreign_urls(blobs: DesignBlobStore) -> None:
    module = section_module("Hostile", HOSTILE_JS, props_schema=QUOTE_SCHEMA)
    site, brand = hold_site_images(garner_site_without_clones("pub_hostile"), garner_brand(), blobs)
    site["agent_sections"] = {"Hostile": module.digest}
    site["pages"]["/"]["content"].append({"type": "Hostile", "props": {"id": "h", "surface": "page", "quote": "Still here."}})
    package = build("pub_hostile", site, brand, [module], blobs=blobs)
    html = package.html.lower()
    for gone in ("<script", "onerror", "javascript:", "<iframe", "collector.example"):
        assert gone not in html, gone
    assert "still here." in html


def test_a_missing_or_stale_module_refuses_the_publish(blobs: DesignBlobStore) -> None:
    module = section_module("Quote", HOSTILE_JS)
    site, brand = hold_site_images(garner_site_without_clones("pub_missing"), garner_brand(), blobs)
    site["agent_sections"] = {"Quote": module.digest}
    with pytest.raises(SiteRenderError) as refused:
        build("pub_missing", site, brand, [], blobs=blobs)
    assert refused.value.code == SECTION_MODULE_MISSING


def test_clone_pins_are_checked_at_publish(blobs: DesignBlobStore) -> None:
    site, brand = hold_site_images(garner_site("pub_clones"), garner_brand(), blobs)
    with pytest.raises(SitePublishRefused) as unresolved:
        build("pub_clones", site, brand, [], blobs=blobs, fragment_status=lambda fragment_id: None)
    assert unresolved.value.code == "site_publish.clone_unresolved"
    assert unresolved.value.message == (
        "This page uses a section that isn't in your brand's library. Ask the agent to replace it, then publish again."
    )
    document = HybridRepository().require_document("pub_clones")
    with pytest.raises(SitePublishRefused) as draft:
        build_site_publish_package(HybridRepository(), document, blobs=blobs, brand=brand, sections=[], slug="acme-site", site_address=ADDRESS, fragment_status=lambda fragment_id: "draft")
    assert draft.value.code == "site_publish.clone_not_approved"
    pinned = next(
        item["props"]["fragmentId"]
        for page in site["pages"].values()
        for item in page["content"]
        if item["type"] == "ClonedSection"
    )
    label = brand["clones"][pinned]["label"]
    assert draft.value.message == f'This page uses a section that isn\'t approved yet: "{label}". Approve your brand kit, then publish again.'
    assert "frag_" not in draft.value.message and "clone" not in draft.value.message.lower()
    package = build_site_publish_package(HybridRepository(), document, blobs=blobs, brand=brand, sections=[], slug="acme-site", site_address=ADDRESS, fragment_status=lambda fragment_id: "deprecated")
    assert package.manifest["fragments"]["ids"]
```

- [ ] **Step 3: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_publish_package.py`
Expected: FAIL — `ImportError: cannot import name 'SitePublishRefused'`.

- [ ] **Step 4: Add the package builder** to `lumen_api/site_publish.py`. Extend the imports:

```python
import re
from collections.abc import Callable

from clue_design.publishes import delivery_csp

from . import web_export
from .design_store import CustodyState
from .public_address import PublicSiteAddress
from .site_doc_validate import SiteDocumentInvalid, check_site_document
from .site_render import pinned_modules
from .site_sanitize import sanitize_site_html
```
  and append:

```python
SITE_DELIVERY = "site"
#: Founder ruling Q5 (2026-10-12): retiring sections is out of scope for sites, so a section retired
#: after the page used it still publishes (WebDoc's posture); a draft one never released, or one the
#: registry lacks, does not.
_PUBLISHABLE_CLONE_STATUSES = frozenset({"approved", "deprecated"})
#: The marketer reads these verbatim (the web editor shows a refusal's message as is,
#: apps/frontend/src/features/design-editor/engine/webDocuments.ts:2073), so they never say "clone"
#: or show an id. Founder-approved wording, 2026-10-12.
_SECTION_NOT_IN_LIBRARY = (
    "This page uses a section that isn't in your brand's library. "
    "Ask the agent to replace it, then publish again."
)


def _section_not_approved(label: str | None) -> str:
    named = f': "{label}"' if label else ""
    return f"This page uses a section that isn't approved yet{named}. Approve your brand kit, then publish again."
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")
_CSP_FILE_DIRECTIVES = frozenset({"style-src", "img-src", "font-src", "media-src"})


class SitePublishRefused(Exception):
    """A site that may not be published as it stands, with a stable ``site_publish.*`` code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clone_ids(site: JsonObject) -> list[str]:
    found: list[str] = []
    for page in (site.get("pages") or {}).values():
        for item in (page or {}).get("content") or []:
            if item.get("type") == "ClonedSection":
                fragment_id = str((item.get("props") or {}).get("fragmentId") or "")
                if fragment_id and fragment_id not in found:
                    found.append(fragment_id)
    return found


def check_clone_pins(site: JsonObject, brand: JsonObject, fragment_status: Callable[[str], str | None]) -> None:
    """Ruling 2026-10-11: clone pins are validated at publish, not on every save."""
    for fragment_id in _clone_ids(site):
        status = fragment_status(fragment_id)
        clone = (brand.get("clones") or {}).get(fragment_id)
        if status is None or clone is None:
            raise SitePublishRefused("site_publish.clone_unresolved", _SECTION_NOT_IN_LIBRARY)
        if status not in _PUBLISHABLE_CLONE_STATUSES:
            label = str(clone.get("label") or "").strip() or None
            raise SitePublishRefused("site_publish.clone_not_approved", _section_not_approved(label))


def gated_brand(brand: JsonObject, repo: Any, blobs: Any) -> tuple[JsonObject, Any]:
    """The brand with its fonts replaced by the licence gate's faces (``web_export._gather_fonts``,
    the gate every WebDoc publish uses): a family whose licence does not allow embedding is not
    shipped, and each shipped face is the WOFF2 the gate registered."""
    gate = web_export._gather_fonts(brand.get("kit"), repo, blobs)
    fonts = [{"family": face.family, "weight": face.weight, "style": face.style, "file": f"/asset-store/{face.digest}"} for face in gate.faces]
    return {**brand, "fonts": fonts}, gate


def site_delivery_csp(*, meta: bool, static_bundle: bool = False) -> str:
    """The site policy; ``static_bundle`` adds ``file:`` where the export ZIP loads its own files
    from disk (an opaque origin that ``'self'`` does not match), as web_export._delivery_csp does."""
    policy = delivery_csp(meta=meta, delivery=SITE_DELIVERY)
    if not static_bundle:
        return policy
    return "; ".join(
        directive + " file:" if directive.split(" ", 1)[0] in _CSP_FILE_DIRECTIVES else directive
        for directive in policy.split("; ")
    )


def _page_title(site: JsonObject, route: str) -> str:
    root = ((site.get("pages") or {}).get(route) or {}).get("root") or {}
    return str((root.get("props") or {}).get("title") or site.get("title") or "")


def _site_page_head(*, title: str, description: str, og_image: str | None, noindex: bool) -> str:
    """Our own head for a published page (founder question Q2, recommendation (a)). Added AFTER
    the cleaner runs, so nothing here is ever stripped."""
    head = '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    head += web_export._seo_snippet(title=title, description=description, og_image=og_image)
    head += '<link rel="icon" href="/favicon.ico">\n'
    if noindex:
        head += web_export.ROBOTS_NOINDEX_META + "\n"
    return head


def build_site_publish_package(
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    slug: str,
    site_address: PublicSiteAddress,
    default_description: str | None = None,
    default_social_preview_sha256: str | None = None,
    noindex: bool = False,
    node_bin: str = "node",
    fragment_status: Callable[[str], str | None] | None = None,
) -> web_export.PublishPackage:
    """One immutable publish package for a Puck site, same shape as the WebDoc one.

    Order: the modules the site pins (missing or stale refuses, ``render.section_module_missing``),
    the clone pins, the licence-gated fonts, the contract checks, the hardened render at the site's
    own path, the cleaner over each whole page, our head, the manifest (``delivery: "site"``, an
    empty ``custom_components``), and the CSP meta + manifest back-reference. Every URL it mints is
    root-relative except ``og:image``, as on the web path."""
    site = document["scene"]
    pinned_modules(site, sections)
    status = fragment_status or (lambda fragment_id: (repo.find_web_fragment(fragment_id) or {}).get("status"))
    check_clone_pins(site, brand, status)
    brand, gate = gated_brand(brand, repo, blobs)
    errors = check_site_document(site, document_id=str(document["id"]), brand=brand, sections=sections, blobs=blobs, node_bin=node_bin)
    if errors:
        raise SiteDocumentInvalid(errors)
    render = render_site(site, brand, sections, base_path=site_address.link_path, node_bin=node_bin)
    origin = site_address.origin.rstrip("/")
    og_image = f"{origin}/asset-store/{default_social_preview_sha256}" if default_social_preview_sha256 else None
    warnings = [*gate.warnings, *render.warnings]
    staged: list[tuple[str, str]] = []
    for page in render.pages:
        cleaned = sanitize_site_html(site_page_html(page, render.css)).html
        head = _site_page_head(title=_page_title(site, page.route), description=default_description or "", og_image=og_image, noindex=noindex)
        staged.append((page.route, web_export._inject_before_head_close(cleaned, head)))
    digests = list(dict.fromkeys(digest for _route, html in staged for digest in _ASSET_REF.findall(html)))
    states = blobs.custody_states(digests) if digests else {}
    unreadable = [digest for digest in digests if states.get(digest) is not CustodyState.READABLE]
    warnings += [f"image or font {digest[:12]} is not readable: the published page will serve a 404 where it goes" for digest in unreadable]
    manifest: JsonObject = {
        "schema_version": 2,
        "kind": "publish",
        "delivery": SITE_DELIVERY,
        "document_id": document["id"],
        "doc_version": document["current_version"],
        "page_id": "/",
        "pages": [{"page_id": route, "route": route, "html_digest": web_export._sha256(html)} for route, html in staged],
        "runtime": {"platform_version": 2, "custom_component_contract_version": None},
        "custom_components": {},
        "fragments": {"ids": _clone_ids(site), "missing": [], "asset_digests": digests, "missing_asset_digests": unreadable},
        "agent_sections": dict(site.get("agent_sections") or {}),
        "asset_digests": [],
        "warnings": warnings,
        **web_export._font_manifest_entries(gate),
        "slug": slug,
        "canonical_url": site_address.page_url("/"),
        **({"robots": "noindex"} if noindex else {}),
    }
    manifest_digest = web_export._sha256(web_export._canonical_json(manifest))
    manifest_head = (
        '<meta http-equiv="Content-Security-Policy" content="'
        f'{web_export._escape_attr(site_delivery_csp(meta=True))}">\n'
        f'<meta name="lumen-publish-manifest-digest" content="{manifest_digest}">\n'
        '<link rel="lumen-publish-manifest" href="'
        f'{web_export._escape_attr(f"{site_address.site_path}/manifest.json")}">\n'
    )
    pages: list[web_export.PublishedPage] = []
    for route, html in staged:
        final = web_export._inject_before_head_close(html, manifest_head)
        pages.append(web_export.PublishedPage(page_id=route, route=route, html=final, html_digest=web_export._sha256(final)))
    served = next(page for page in pages if page.route == "/")
    package_digest = web_export._sha256(
        web_export._canonical_json(
            {"manifest_digest": manifest_digest, "page_html_digests": sorted(page.html_digest for page in pages), "asset_digests": []}
        )
    )
    return web_export.PublishPackage(
        html=served.html,
        manifest=manifest,
        assets={},
        package_digest=package_digest,
        manifest_digest=manifest_digest,
        html_digest=served.html_digest,
        runtime_version=None,
        warnings=warnings,
        pages=pages,
    )
```

- [ ] **Step 5: Run the tests.**

Run: `DESIGN_PYTEST test_site_publish_package.py`
Expected: all pass. If the CSP assertion fails on quoting, check `web_export._escape_attr`: it must
leave `'` alone (the web package's own meta is built the same way, `web_export.py:2137-2142`).

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_publish.py subsystems/clue-design/apps/api/tests/site_kit_support.py subsystems/clue-design/apps/api/tests/test_site_publish_package.py
git commit -m "design API: the site publish package (clone pins at publish, licence-gated fonts, hardened render, cleaned pages, site CSP manifest)"
```

### Task 21: `design_publish_site` and the site publish routes, through the web path's one write sequence

**Decision: a new governed tool, `design_publish_site`, rather than widening `design_publish_web`.**
The web tool's input and refusal contract are WebDoc's (`toolbelt/publishes.py:243-306`: engine
render, custom components, `design_document_not_web`), and its replay notes name the node CSS
compile; a site needs the brand and section loaders and its own refusals
(`site_publish.section_module_missing`, `site_publish.clone_*`, `site.invalid`). What must stay
single — "persist assets → immutable revision → lock the hostname → swap the pointer → unpublish
other slugs" (`toolbelt/publishes.py:131-202`) — is extracted into `_commit_publish_package`, which
both tools call, so the write path still exists exactly once. Unpublish and rollback are slug-based
and kind-agnostic (`main.py:4850-4900`) and serve sites unchanged.

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/factory.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:4653-4848` (refusals, `_publish_site`,
  the shared response and state helpers, two routes)
- Modify: `subsystems/clue-design/apps/api/tests/test_write_path_governance.py`
- Modify: `platform/api/clue_api/agent_registry_wiring.py`, `tests/api/test_agent_registry_wiring.py`,
  `tests/api/test_toolbelt_wiring.py`, `tests/agents/test_tool_authority_audit.py`
- Create: `subsystems/clue-design/apps/api/tests/test_site_publish_routes.py`

**Interfaces:**
- Consumes: `build_site_publish_package`, `SitePublishRefused` (Task 20); `load_section_modules`
  (Task 11); `_site_refusal` (Task 13); `require_site_document` (Task 8).
- Produces:
  - `_commit_publish_package(*, repository, blobs, document, slug, package) -> WebPublishRef`;
  - `publish_site_document(*, repository, blobs, node_bin, brand_loader, section_loader, document, slug, noindex=False) -> WebPublishRef`;
  - `PublishSiteTool` (`design_publish_site@1`, input `PublishWebDocumentInput`, output
    `WebPublishRef`, reason `design_document_not_site`);
  - `POST /documents/{id}/site/publish` body `{slug?, noindex?}` → the same 200 body as
    `POST /documents/{id}/web/publish`; 409 `site_publish.section_module_missing`,
    `site_publish.clone_unresolved`, `site_publish.clone_not_approved`, `document.kind_unsupported`,
    `web_publish.slug_taken`; 422 `site.invalid`, `web_publish.bad_slug`; 502 `render.*`; 503
    `site_inputs.unavailable`;
  - `GET /documents/{id}/site/publish` → the same body as `GET /documents/{id}/web/publish`.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_site_publish_routes.py`:

```python
"""Publishing a Puck site (Wave 2 Lane A, Task 21)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clue_design.publishes import SITE_DELIVERY_CSP_META
from conftest import make_blob_store, make_client, published, published_html, published_manifest, published_page
from lumen_api.main import create_app
from site_kit_support import (
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    garner_site_without_clones,
    hold_site_images,
    install_site_inputs,
    section_module,
    store_site,
    QUOTE_JS,
)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def stored(client: TestClient, site: dict) -> dict:
    site, brand = hold_site_images(site, garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)
    return site


def test_publish_serve_state_republish_and_unpublish(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_pub"))
    response = client.post("/documents/site_pub/site/publish", json={"slug": "acme-site"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == "acme-site" and body["url"] == f"{body['public_origin']}/acme-site"
    assert body["routes"] == ["/", "/analysis"] and set(body["page_urls"]) == {"/", "/analysis"}
    html = published_html(workspace_id, "acme-site")
    assert f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">' in html
    assert "<script" not in html.lower()
    assert published_manifest(workspace_id, "acme-site")["delivery"] == "site"
    assert published_page(workspace_id, "acme-site", "/analysis") is not None
    state = client.get("/documents/site_pub/site/publish").json()
    assert state["published"] is True and state["slug"] == "acme-site"
    again = client.post("/documents/site_pub/site/publish", json={"slug": "acme-site"})
    assert again.status_code == 200 and again.json()["previous_available"] is True
    assert client.delete("/web/publishes/acme-site").json()["status"] == "unpublished"


def test_a_missing_agent_section_module_refuses_and_publishes_nothing(client: TestClient, workspace_id: str) -> None:
    site = garner_site_without_clones("site_pub_missing")
    site["agent_sections"] = {"Quote": section_module("Quote", QUOTE_JS).digest}
    stored(client, site)  # install_site_inputs with no modules: the loader returns none
    response = client.post("/documents/site_pub_missing/site/publish", json={"slug": "missing-site"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "site_publish.section_module_missing"
    assert published(workspace_id, "missing-site") is None


def test_a_clone_the_registry_does_not_hold_refuses(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site("site_pub_clone"))
    response = client.post("/documents/site_pub_clone/site/publish", json={"slug": "clone-site"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "site_publish.clone_unresolved"
    assert published(workspace_id, "clone-site") is None


def test_each_publish_route_refuses_the_other_kind(client: TestClient) -> None:
    stored(client, garner_site_without_clones("site_pub_kind"))
    web = client.post("/documents", json={"doc_kind": "web", "title": "A web page"}).json()["document"]
    to_site = client.post(f"/documents/{web['id']}/site/publish", json={})
    assert to_site.status_code == 409 and to_site.json()["detail"]["code"] == "document.kind_unsupported"
    to_web = client.post("/documents/site_pub_kind/web/publish", json={})
    assert to_web.status_code == 409 and to_web.json()["detail"]["code"] == "document.kind_unsupported"
```
  (`"unpublished"` is the status `UnpublishWebDocumentTool` assigns, `toolbelt/publishes.py:357`.)

- [ ] **Step 2: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_publish_routes.py`
Expected: FAIL — `POST /documents/{id}/site/publish` answers 405.

- [ ] **Step 3: Extract the shared write and add the site core.** In `toolbelt/publishes.py`:
  1. Replace the part of `publish_web_document` from `web_export.persist_publish_assets(` through
     the final `return WebPublishRef(...)` with `return _commit_publish_package(repository=repository, blobs=blobs, document=document, slug=slug, package=package)`,
     and add, above `publish_web_document`, the extracted function (its body is the removed code,
     unchanged apart from reading `package` from its argument):

```python
def _commit_publish_package(*, repository: Any, blobs: Any, document: dict[str, Any], slug: str, package: Any) -> WebPublishRef:
    """THE publish write sequence, for a WebDoc package and a Puck site package alike: persist the
    delivery assets, register the immutable revision (with its pages), lock the workspace's system
    label, swap the slug's pointer, and stop serving the document at any other slug."""
    from .. import web_export
    from ..database import utc_now

    web_export.persist_publish_assets(
        blobs,
        package.assets,
        package.manifest["custom_components"].get("assets"),
    )
    publish_id = f"webpub_{package.package_digest}"
    repository.register_web_publish_revision(
        {
            "publish_id": publish_id,
            "slug": slug,
            "document_id": document["id"],
            "doc_version": document["current_version"],
            "html": package.html,
            "html_digest": package.html_digest,
            "manifest": package.manifest,
            "manifest_digest": package.manifest_digest,
            "package_digest": package.package_digest,
            "runtime_version": package.runtime_version,
            "created_at": utc_now(),
            # F5: the whole site, immutable beside the package that produced it.
            "pages": [
                {"route": page.route, "page_id": page.page_id, "html": page.html, "html_digest": page.html_digest}
                for page in package.pages
            ],
        }
    )
    # F5 R-F5-5: the label stops being editable once a revision exists to be served at it.
    repository.lock_system_hostname()
    publish = repository.upsert_web_publish(
        slug,
        document["id"],
        document["current_version"],
        package.html,
        package.runtime_version,
        publish_id,
    )
    # A document lives at ONE address: republishing under a new slug moves it.
    repository.unpublish_other_slugs(document["id"], slug)
    return WebPublishRef(
        slug=slug,
        document_id=document["id"],
        publish_id=publish["publish_id"],
        doc_version=publish["doc_version"],
        status=publish["status"],
        runtime_version=publish["runtime_version"],
        manifest_digest=publish.get("manifest_digest"),
        package_digest=publish.get("package_digest"),
        html_digest=publish.get("html_digest"),
        previous_available=publish["previous_html"] is not None,
        page_count=len(package.pages),
        routes=[page.route for page in package.pages],
    )
```
  2. After `publish_web_document`, add:

```python
def publish_site_document(
    *,
    repository: Any,
    blobs: Any,
    node_bin: str,
    brand_loader: Any,
    section_loader: Any,
    document: dict[str, Any],
    slug: str,
    noindex: bool = False,
) -> WebPublishRef:
    """Publish a Puck site (Wave 2): build its package, then the same write sequence as the web."""
    from .. import site_publish
    from ..public_pages import site_address
    from ..site_doc_inputs import load_section_modules

    noindex = bool(noindex) or bool(document.get("web_noindex"))
    defaults = repository.pages_defaults()
    package = site_publish.build_site_publish_package(
        repository,
        document,
        blobs=blobs,
        brand=brand_loader(repository, blobs, document),
        sections=load_section_modules(section_loader, repository, blobs, document["scene"]),
        slug=slug,
        site_address=site_address(repository, slug),
        default_description=defaults["page_description"],
        default_social_preview_sha256=defaults["social_preview_sha256"],
        noindex=noindex,
        node_bin=node_bin,
    )
    return _commit_publish_package(repository=repository, blobs=blobs, document=document, slug=slug, package=package)
```
  3. In `PublishWebDocumentTool`, add `_kind: ClassVar[str] = "web"`, replace the kind block in
     `check` (`:283-291`) with `if document.get("doc_kind", "scene") != self._kind: return (self._kind_failure(inputs.document_id),)`,
     and add:

```python
    def _kind_failure(self, document_id: str) -> PreconditionFailure:
        return PreconditionFailure(
            reason_code="design_document_not_web",
            message=(
                f"document {document_id!r} is not a website-mode document; "
                "only web documents publish"
            ),
        )
```
  4. Add the site tool after `PublishWebDocumentTool`, and `"PublishSiteTool", "publish_site_document",`
     to `__all__`:

```python
class PublishSiteTool(PublishWebDocumentTool):
    """Publish one Puck site document to a workspace-local public slug (Wave 2 Lane A)."""

    name = "design_publish_site"
    version = "1"
    model_description = (
        "Publish a Puck site document to a public slug as static, script-free pages. Returns "
        "publish references (slug, publish id, content digests), never the rendered HTML."
    )
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + slug + content-derived webpub_<package_digest> revision",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the revision row is content-addressed and insert-or-no-op, but the slug's "
            "current/previous pointer rotates on every upsert, so only a same-operation retry "
            "(journal + A9) is a true no-op; the render runs in a local hardened browser and the "
            "CSS compile in a local node subprocess, neither an external provider"
        ),
    )
    _kind: ClassVar[str] = "site"

    def _kind_failure(self, document_id: str) -> PreconditionFailure:
        return PreconditionFailure(
            reason_code="design_document_not_site",
            message=f"document {document_id!r} is not a site document; only site documents publish here",
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, PublishWebDocumentInput)
        repository = self.host.repository(ctx.workspace_id)
        return publish_site_document(
            repository=repository,
            blobs=self.host.blobs(ctx.workspace_id),
            node_bin=self.host.need("web_export_node_bin"),
            brand_loader=self.host.need("site_brand_loader"),
            section_loader=self.host.need("site_section_loader"),
            document=repository.require_document(inputs.document_id),
            slug=inputs.slug,
            noindex=inputs.noindex,
        )
```
  5. In `factory.py`, import `PublishSiteTool` from `.publishes` and add it to `DESIGN_TOOL_TYPES`
     right after `PublishWebDocumentTool,`.

- [ ] **Step 4: The routes.** In `main.py`:
  - add to the imports: `from .site_publish import SitePublishRefused` and
    `from .site_render import SECTION_MODULE_MISSING` (beside `SiteRenderError`, Task 18);
  - in `_publish_refusals` add `"design_document_not_site": lambda message: HTTPException(status_code=409, detail={"code": "document.kind_unsupported", "message": message}),`;
  - after `_publish_web`, add:

```python
    def _publish_site(
        repo: HybridRepository,
        document: JsonObject,
        *,
        slug: str,
        idempotency_key: Optional[str] = None,
        noindex: bool = False,
    ) -> JsonObject:
        """Publish a Puck site through the governed tool (Wave 2 Lane A); typed refusals."""
        try:
            return run_design_tool(
                "design_publish_site",
                {"document_id": document["id"], "slug": slug, "noindex": noindex},
                workspace_id=store_workspace_id(repo),
                idempotency_key=idempotency_key,
                refusals=_publish_refusals(slug, document["id"]),
            )
        except SitePublishRefused as error:
            raise HTTPException(status_code=409, detail={"code": error.code, "message": error.message}) from error
        except SiteRenderError as error:
            if error.code == SECTION_MODULE_MISSING:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "site_publish.section_module_missing", "message": error.message},
                ) from error
            raise HTTPException(status_code=502, detail={"code": error.code, "message": error.message}) from error
        except (SiteDocumentInvalid, SiteInputsUnavailable, SiteValidatorUnavailable) as error:
            raise _site_refusal(error) from error
        except web_export.WebExportError as error:
            raise HTTPException(status_code=502, detail={"code": "web_export.failed", "message": str(error)}) from error

    def _publish_response(repo: HybridRepository, slug: str, publish: JsonObject) -> JsonObject:
        """The publish route's 200 body — one builder for the web and site routes."""
        address = site_address(repo, slug)
        custom = custom_site_address(repo, slug)
        routes = list(publish.get("routes") or []) or ["/"]
        return {
            "schema_version": 1,
            "slug": slug,
            "url": address.page_url("/"),
            "custom_url": None if custom is None else custom.page_url("/"),
            "public_origin": address.origin,
            "custom_origin": None if custom is None else custom.origin,
            "doc_version": publish["doc_version"],
            "runtime_version": publish["runtime_version"],
            "publish_id": publish["publish_id"],
            "manifest_digest": publish.get("manifest_digest"),
            "package_digest": publish.get("package_digest"),
            "html_digest": publish.get("html_digest"),
            "previous_available": publish["previous_available"],
            "routes": list(publish.get("routes") or []),
            "page_urls": {route: address.page_url(route) for route in routes},
            "custom_page_urls": ({} if custom is None else {route: custom.page_url(route) for route in routes}),
        }
```
  - in `publish_web_document` (the route), replace everything from `address = site_address(repo, slug)`
    to the end of its `return {...}` with `return _publish_response(repo, slug, publish)`;
  - move the body of `get_web_publish_state` after its two gate lines into a nested
    `def _publish_state(repo: HybridRepository, document_id: str) -> JsonObject:` defined just above
    it, and make the web route `return _publish_state(repo, document_id)`;
  - after `get_web_publish_state`, add:

```python
    @app.post("/documents/{document_id}/site/publish")
    def publish_site_document_route(
        document_id: str,
        payload: WebPublishRequest,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_site_document(document)
        slug = (payload.slug or "").strip() or web_default_slug(document["title"], document_id)
        publish = _publish_site(repo, document, slug=slug, idempotency_key=idempotency_key, noindex=payload.noindex)
        log_event(api_logger, logging.INFO, "site_publish_completed", document_id=document_id, slug=slug, doc_version=publish["doc_version"])
        return _publish_response(repo, slug, publish)

    @app.get("/documents/{document_id}/site/publish")
    def get_site_publish_state(document_id: str, repo: HybridRepository = Depends(repository)) -> JsonObject:
        document = require_document(repo, document_id)
        require_site_document(document)
        return _publish_state(repo, document_id)
```

- [ ] **Step 5: The four registries for the new tool.**
  - `test_write_path_governance.py`: in `_GOVERNED` add

```python
    "build_site_publish_package": ("function", ("lumen_api/site_publish.py",)),
    "publish_site_document": ("function", ()),
```
    add `site_publish` (`from lumen_api import site_publish`) and `toolbelt_publishes`
    (`from lumen_api.toolbelt import publishes as toolbelt_publishes`) to the modules searched in
    `test_every_governed_name_actually_exists`, and add `"design_publish_site",` after
    `"design_publish_web",` in `test_design_tool_names_are_stable`.
  - `agent_registry_wiring.py`: after `"design_publish_web": (AgentRole.DESIGN,),` add
    `"design_publish_site": (),  # Wave 2 Lane A: the Puck site publish, ungranted (ruling R6): only the person's Publish route invokes it`.
    Granting it to `AgentRole.DESIGN` here would stop the registry composing (Task 12 Step 9).
  - `tests/agents/test_tool_authority_audit.py`: add `"design_publish_site"` to the
    `SITE_DOCUMENT_LANE` set from Task 12 Step 9.
  - `tests/api/test_agent_registry_wiring.py`: do **not** add it to `design_addresses`;
    both `len(by_address)` asserts `172` → `173`.
  - `tests/api/test_toolbelt_wiring.py`: `_MATRIX` gets
    `"design_publish_site": ("precondition", ("design_runtime_not_configured",)),`; `_bodies()` gets
    `"design_publish_site": {"document_id": "doc_matrix", "slug": "matrix-site"},`; both name counts
    `147` → `148` and both address counts `172` → `173`.
  - `tests/agents/test_tool_authority_audit.py:170`: `147` → `148`.

- [ ] **Step 6: Run the tests.**

Run: `DESIGN_PYTEST test_site_publish_routes.py` then `DESIGN_PYTEST test_web_export.py` then `DESIGN_PYTEST test_public_pages.py` then `DESIGN_PYTEST test_write_path_governance.py` then `PLATFORM_PYTEST tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py tests/api/test_agent_registry_wiring.py`
Expected: the new suite passes; the web publish suites are unchanged; governance has only its one
pre-existing failure; the platform files pass.

- [ ] **Step 7: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py subsystems/clue-design/apps/api/lumen_api/toolbelt/factory.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_write_path_governance.py subsystems/clue-design/apps/api/tests/test_site_publish_routes.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_agent_registry_wiring.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py
git commit -m "design: design_publish_site and the site publish routes over the web path's one write sequence"
```

## A8 — export

### Task 22: Site export as a ZIP and as a PDF

The web exports are web-gated (`main.py:4545-4651`). A site's ZIP is its rendered, cleaned pages
with every `/asset-store/` byte copied into `assets/` and internal links in folder form
(`web_export.rewrite_zip_links`, `:145-160`); its PDF reuses `web_pdf.render_pages_pdf` with a new
`hardened` mode (JavaScript off, network blocked, the print sheet inside the HTML because
`add_style_tag` needs script). The web path stays byte-identical.

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_pdf.py:250-321`
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_publish.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (two routes after the web PDF route)
- Create: `subsystems/clue-design/apps/api/tests/test_site_export.py`

**Interfaces:**
- Consumes: `render_site`, `site_page_html` (Task 17); `sanitize_site_html` (Task 16);
  `gated_brand`, `site_delivery_csp`, `_page_title` (Task 20); `inline_asset_store_refs`.
- Produces: `render_pages_pdf(htmls, *, runtime=None, hardened=False) -> bytes`;
  `build_site_export_bundle(repo, document, *, blobs, brand, sections, generated_at, node_bin="node") -> ExportBundle`;
  `build_site_pdf(repo, document, *, blobs, brand, sections, node_bin="node") -> bytes`;
  `GET /documents/{id}/site/export` (zip `<slug>-<id8>.zip`) and
  `GET /documents/{id}/site/export.pdf`; refusals 409 `render.section_module_missing`, 502
  `render.*` / `web_pdf.render_failed`, 503 `site_inputs.unavailable`.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_site_export.py`:

```python
"""Exporting a Puck site as a ZIP and as a PDF (Wave 2 Lane A, Task 22)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from conftest import make_blob_store, make_client
from lumen_api.main import create_app
from site_kit_support import chromium_available, ensure_site_kit_dist, garner_brand, garner_site_without_clones, hold_site_images, install_site_inputs, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


@pytest.fixture()
def site(client: TestClient) -> dict:
    site, brand = hold_site_images(garner_site_without_clones("site_export"), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)
    return site


def test_the_zip_holds_every_page_its_bytes_and_folder_links(client: TestClient, site: dict) -> None:
    response = client.get("/documents/site_export/site/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert {"index.html", "analysis/index.html", "manifest.json"} <= names
    held = site["pages"]["/analysis"]["content"][0]["props"]["image"].removeprefix("/asset-store/")
    assert f"assets/{held}.png" in names
    analysis = archive.read("analysis/index.html").decode()
    assert f"../assets/{held}.png" in analysis and f"/asset-store/{held}" not in analysis
    home = archive.read("index.html").decode()
    assert 'href="/analysis/"' in home and "<script" not in home.lower()
    assert "img-src 'self' data: file:" in home
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["delivery"] == "site" and [page["route"] for page in manifest["pages"]] == ["/", "/analysis"]


def test_the_pdf_prints_every_page(client: TestClient, site: dict) -> None:
    response = client.get("/documents/site_export/site/export.pdf")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")
    with pymupdf.open(stream=response.content, filetype="pdf") as document:
        assert document.page_count >= 2


def test_a_web_document_is_not_exported_as_a_site(client: TestClient, site: dict) -> None:
    web = client.post("/documents", json={"doc_kind": "web", "title": "W"}).json()["document"]
    assert client.get(f"/documents/{web['id']}/site/export").json()["detail"]["code"] == "document.kind_unsupported"
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DESIGN_PYTEST test_site_export.py`
Expected: FAIL — the export routes answer 404.

- [ ] **Step 3: A hardened print mode in `web_pdf.py`.** Add `Any` to its `typing` import, and
  replace `render_pages_pdf` (`:250-321`) with:

```python
def _with_print_sheet(html: str) -> str:
    """The print sheet as the document's LAST style, for a page with JavaScript off
    (Playwright's add_style_tag needs script). Last in the body is last in the cascade, which is
    where add_style_tag puts it on the web path."""
    sheet = f"<style>{_PRINT_SHEET}</style>"
    index = html.rfind("</body>")
    return html + sheet if index == -1 else html[:index] + sheet + html[index:]


def _print_page(context: Any, html: str, *, runtime: Optional[bytes], sheet_inline: bool) -> bytes:
    """One html printed at the tablet layout onto margin-less A4 (see the module docstring)."""
    page = context.new_page()
    try:
        # `BrowserContext.new_page()` takes no per-page options, so the viewport is set on the page
        # itself: 768 is the `md:` breakpoint the layout depends on.
        page.set_viewport_size(dict(_VIEWPORT))
        content = inline_tailwind(html, runtime) if runtime is not None else html
        if sheet_inline:
            content = _with_print_sheet(content)
        # BEFORE the content, so nothing ever lays out under print media.
        page.emulate_media(media="screen")
        page.set_content(content, wait_until="load")
        page.wait_for_timeout(_SETTLE_MS)
        if not sheet_inline:
            # AFTER load, so it lands last in the cascade over the page's own sheet.
            page.add_style_tag(content=_PRINT_SHEET)
        return page.pdf(format="A4", print_background=True, prefer_css_page_size=False, margin=dict(_PDF_MARGIN))
    finally:
        page.close()


def render_pages_pdf(htmls: List[str], *, runtime: Optional[bytes] = None, hardened: bool = False) -> bytes:
    """Print each html to PDF in one browser, then merge the runs in order.

    ``hardened`` (a Puck site, Wave 2): the htmls are already cleaned and carry their bytes as data:
    URIs, so they print in a hardened context (lumen_api.hardened_browser) with JavaScript OFF and
    the network blocked. The web path (``hardened=False``) is unchanged.
    """

    if not htmls:
        raise WebPdfUnavailable("web_pdf.render_failed", "the site has no pages")
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as error:
        raise WebPdfUnavailable("web_pdf.render_failed", "playwright is not installed") from error

    parts: List[bytes] = []
    try:
        if hardened:
            from .hardened_browser import HardenedBrowserUnavailable, hardened_context

            try:
                with hardened_context(javascript=False, viewport=dict(_VIEWPORT)) as (context, _blocked):
                    for html in htmls:
                        parts.append(_print_page(context, html, runtime=None, sheet_inline=True))
            except HardenedBrowserUnavailable as error:
                raise WebPdfUnavailable("web_pdf.render_failed", str(error)) from error
        else:
            # One slot for the whole document: the span owns a browser process.
            with _CAPTURE_SLOTS, sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    context = browser.new_context(viewport=dict(_VIEWPORT))
                    for html in htmls:
                        parts.append(_print_page(context, html, runtime=runtime, sheet_inline=False))
                finally:
                    browser.close()
    except PlaywrightError as error:
        raise WebPdfUnavailable("web_pdf.render_failed", str(error)) from error

    return merge_pdfs(parts)
```

- [ ] **Step 4: The two builders** in `site_publish.py`. Add `import json`,
  `from . import web_pdf`, `from .database import NotFoundError` to its imports and append:

```python
_EXTENSION_BY_MEDIA = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "image/avif": "avif", "image/svg+xml": "svg", "video/mp4": "mp4",
    "font/woff2": "woff2", "font/woff": "woff", "font/ttf": "ttf", "font/otf": "otf",
}


def _export_head() -> str:
    return (
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{web_export._escape_attr(site_delivery_csp(meta=True, static_bundle=True))}">\n'
    )


def build_site_export_bundle(
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    generated_at: str,
    node_bin: str = "node",
) -> web_export.ExportBundle:
    """A self-contained static copy of the site: one folder per page, every stored byte it names
    under assets/, links in folder form, the site policy with ``file:`` for its own files."""
    site = document["scene"]
    brand, gate = gated_brand(brand, repo, blobs)
    render = render_site(site, brand, sections, base_path="", node_bin=node_bin)
    routes = [page.route for page in render.pages]
    files: dict[str, bytes] = {}
    warnings = [*gate.warnings, *render.warnings]
    copied: dict[str, str | None] = {}

    def asset_path(digest: str) -> str | None:
        if digest not in copied:
            try:
                media_type, data = blobs.read_blob(digest)
            except NotFoundError:
                copied[digest] = None
                warnings.append(f"image or font {digest[:12]} is missing from the asset store; the export keeps its reference")
            else:
                path = f"assets/{digest}.{_EXTENSION_BY_MEDIA.get(media_type.split(';')[0].strip(), 'bin')}"
                files[path] = data
                copied[digest] = path
        return copied[digest]

    pages: list[JsonObject] = []
    for page in render.pages:
        html = web_export.rewrite_zip_links(sanitize_site_html(site_page_html(page, render.css)).html, routes)
        prefix = web_export._relative_prefix(page.route)

        def repoint(match: "re.Match[str]", prefix: str = prefix) -> str:
            path = asset_path(match.group(1))
            return f"{prefix}{path}" if path else match.group(0)

        html = web_export._inject_before_head_close(_ASSET_REF.sub(repoint, html), _export_head())
        path = web_export._zip_page_path(page.route)
        files[path] = html.encode("utf-8")
        pages.append({"route": page.route, "path": path})
    files["manifest.json"] = json.dumps(
        {
            "schema_version": 1,
            "kind": "export",
            "delivery": SITE_DELIVERY,
            "document_id": document["id"],
            "doc_version": document["current_version"],
            "generated_at": generated_at,
            "pages": pages,
            "assets": sorted(path for path in copied.values() if path),
            "warnings": warnings,
            **web_export._font_manifest_entries(gate),
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    return web_export.ExportBundle(files=files, warnings=warnings)


def build_site_pdf(
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    node_bin: str = "node",
) -> bytes:
    """Every page of the site printed at the tablet layout, in route order (web_pdf's posture)."""
    brand, _gate = gated_brand(brand, repo, blobs)
    render = render_site(document["scene"], brand, sections, base_path="", node_bin=node_bin)
    cache: dict[str, str | None] = {}
    htmls: list[str] = []
    for page in render.pages:
        cleaned = sanitize_site_html(site_page_html(page, render.css)).html
        inlined, _missing = inline_asset_store_refs(cleaned, blobs.read_blob, cache=cache)
        htmls.append(inlined)
    return web_pdf.render_pages_pdf(htmls, runtime=None, hardened=True)
```

- [ ] **Step 5: The routes.** In `main.py`, after `export_web_document_pdf`, add:

```python
    def _site_render_inputs(repo: HybridRepository, document: JsonObject) -> tuple[JsonObject, list]:
        blobs = blob_store(repo)
        brand = app.state.site_brand_loader(repo, blobs, document)
        return brand, load_section_modules(app.state.site_section_loader, repo, blobs, document["scene"])

    def _site_export_refusal(error: Exception) -> HTTPException:
        if isinstance(error, SiteRenderError):
            status = 409 if error.code == SECTION_MODULE_MISSING else 502
            return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})
        if isinstance(error, SiteInputsUnavailable):
            return HTTPException(status_code=503, detail={"code": error.code, "message": str(error)})
        if isinstance(error, web_pdf.WebPdfUnavailable):
            return HTTPException(status_code=502, detail={"code": error.code, "message": str(error)})
        raise TypeError(f"not a site export refusal: {error!r}")

    @app.get("/documents/{document_id}/site/export")
    def export_site_document(document_id: str, repo: HybridRepository = Depends(repository)) -> Response:
        document = require_document(repo, document_id)
        require_site_document(document)
        try:
            brand, sections = _site_render_inputs(repo, document)
            bundle = site_publish.build_site_export_bundle(
                repo, document, blobs=blob_store(repo), brand=brand, sections=sections,
                generated_at=utc_now(), node_bin=app.state.web_export_node_bin,
            )
        except (SiteRenderError, SiteInputsUnavailable) as error:
            raise _site_export_refusal(error) from error
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.files):
                archive.writestr(path, bundle.files[path])
        filename = f"{web_slugify(document['title'])}-{document_id[:8]}.zip"
        log_event(api_logger, logging.INFO, "site_export_completed", document_id=document_id, file_count=len(bundle.files), warning_count=len(bundle.warnings))
        return Response(content=buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/documents/{document_id}/site/export.pdf")
    def export_site_document_pdf(document_id: str, repo: HybridRepository = Depends(repository)) -> Response:
        document = require_document(repo, document_id)
        require_site_document(document)
        try:
            brand, sections = _site_render_inputs(repo, document)
            content = site_publish.build_site_pdf(
                repo, document, blobs=blob_store(repo), brand=brand, sections=sections, node_bin=app.state.web_export_node_bin
            )
        except (SiteRenderError, SiteInputsUnavailable, web_pdf.WebPdfUnavailable) as error:
            raise _site_export_refusal(error) from error
        filename = f"{web_slugify(document['title'])}-{document_id[:8]}.pdf"
        log_event(api_logger, logging.INFO, "site_pdf_export_completed", document_id=document_id, byte_count=len(content))
        return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
```

- [ ] **Step 6: Run the tests and the web PDF suite.**

Run: `DESIGN_PYTEST test_site_export.py` then `DESIGN_PYTEST test_web_pdf_export.py` then `DESIGN_PYTEST test_web_export.py`
Expected: all pass (the web PDF still uses `add_style_tag`, unchanged).

- [ ] **Step 7: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/web_pdf.py subsystems/clue-design/apps/api/lumen_api/site_publish.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_site_export.py
git commit -m "design API: site export as a ZIP and a PDF (hardened print, the web path unchanged)"
```

## A10 — published pages on their own domain (Contract 9, published-pages half)

The founder registers the domain; its name arrives through `CLUE_PAGES_SYSTEM_SUFFIX`. Nothing in
this plan hard-codes it: tests use the reserved `.example` TLD (`clue-pages.example`).

### Task 23: Both registrable domains stay reserved, and a script moves every system hostname (label kept)

`validate_custom_hostname` reserves only `registrable_domain(system_suffix)`
(`libs/clue-spine/clue_spine/hostnames.py:185-208`), so after the move `*.cluehq.ai` would become
connectable as a customer domain; the ruling keeps `cluehq.ai` reserved. Every system row stores the
full `<label>.<suffix>` (`:253`), so changing the setting alone moves nothing; the script rewrites
the suffix of every system row in place, which keeps the label (and `locked_at`'s promise that the
address segment a visitor knows does not change). `workspace_hostname` has no foreign keys.

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py:935` (new setting after `pages_system_suffix`)
- Modify: `.env.example:601` (new line after `CLUE_PAGES_SYSTEM_SUFFIX=`)
- Modify: `libs/clue-spine/clue_spine/hostnames.py` (`parse_suffixes`, `validate_custom_hostname`,
  `move_system_hostnames`) and `libs/clue-spine/clue_spine/__init__.py` (exports)
- Modify: `platform/api/clue_api/frontend_read/settings_pages.py:300-302`
- Create: `scripts/move_system_hostnames.py`
- Modify: `tests/test_pages_settings.py`, `tests/clue_spine/test_hostnames_custom_pure.py`
- Create: `tests/clue_spine/test_hostnames_move_db.py`
- Modify (after the founder's yes, Q6): `apps/frontend/src/features/settings/model/pages.ts:80`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Settings.pages_legacy_system_suffixes: str = "pages.cluehq.ai"` (env
  `CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES`, comma-separated); `parse_suffixes(raw: str) -> tuple[str, ...]`;
  `validate_custom_hostname(value: str, *, system_suffix: str, legacy_suffixes: Sequence[str] = ()) -> str`;
  `move_system_hostnames(conn, *, from_suffix: str, to_suffix: str, apply: bool = False) -> dict`
  (keys `from_suffix, to_suffix, rows, collisions, applied, sample`); the CLI
  `python scripts/move_system_hostnames.py --database-url URL --to-suffix NEW [--from-suffix OLD] [--apply]`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_pages_settings.py`, add
  `"pages_legacy_system_suffixes": "pages.cluehq.ai",` to `PAGES_SETTING_DEFAULTS`. Append to
  `tests/clue_spine/test_hostnames_custom_pure.py` (import `parse_suffixes`):

```python
NEW = "clue-pages.example"


@pytest.mark.parametrize("bad", ["x.cluehq.ai", "cluehq.ai", "go.pages.cluehq.ai", "acme.clue-pages.example", "clue-pages.example"])
def test_after_the_move_both_registrable_domains_stay_reserved(bad: str) -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_custom_hostname(bad, system_suffix=NEW, legacy_suffixes=("pages.cluehq.ai",))
    assert caught.value.code == "hostname_reserved"


def test_the_refusal_names_the_domain_it_matched() -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_custom_hostname("x.cluehq.ai", system_suffix=NEW, legacy_suffixes=("pages.cluehq.ai",))
    assert caught.value.message == "Hostnames under cluehq.ai cannot be connected."
    assert validate_custom_hostname("go.acme.com", system_suffix=NEW, legacy_suffixes=("pages.cluehq.ai",)) == "go.acme.com"


def test_parse_suffixes() -> None:
    assert parse_suffixes(" pages.cluehq.ai, Old.Example. ,,") == ("pages.cluehq.ai", "old.example")
    assert parse_suffixes("") == ()
```
  Create `tests/clue_spine/test_hostnames_move_db.py`:

```python
"""Moving system hostnames to the published pages' own domain (Wave 2 Contract 9)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_spine import create_workspace
from clue_spine.hostnames import lock_system_hostname, move_system_hostnames, resolve_active_hostname, system_hostname

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


def _suffixes() -> tuple[str, str]:
    tag = uuid4().hex[:6]
    return f"old{tag}.test", f"new{tag}.test"


def test_a_move_keeps_every_label_and_lock_and_old_hosts_stop_resolving() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _suffixes()
            first = await create_workspace(conn, name="Move A " + uuid4().hex[:4], pages_system_suffix=old)
            await create_workspace(conn, name="Move B " + uuid4().hex[:4], pages_system_suffix=old)
            await lock_system_hostname(conn, workspace_id=first.workspace_id)
            before = await system_hostname(conn, first.workspace_id)
            assert before is not None
            dry = await move_system_hostnames(conn, from_suffix=old, to_suffix=new)
            assert dry["rows"] == 2 and dry["applied"] is False and dry["collisions"] == []
            assert await system_hostname(conn, first.workspace_id) == before
            done = await move_system_hostnames(conn, from_suffix=old, to_suffix=new, apply=True)
            assert done["applied"] is True
            after = await system_hostname(conn, first.workspace_id)
            assert after == before[: -len(old)] + new
            assert await resolve_active_hostname(conn, after) == first.workspace_id
            assert await resolve_active_hostname(conn, before) is None
            locked = (await conn.execute(text("SELECT locked_at FROM workspace_hostname WHERE hostname = :h"), {"h": after})).scalar()
            assert locked is not None

    run_async(scenario())


def test_a_move_that_would_collide_writes_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _suffixes()
            name = "Move Same " + uuid4().hex[:4]
            moving = await create_workspace(conn, name=name, pages_system_suffix=old)
            await create_workspace(conn, name=name, pages_system_suffix=new)  # the same label, already on the new suffix
            before = await system_hostname(conn, moving.workspace_id)
            result = await move_system_hostnames(conn, from_suffix=old, to_suffix=new, apply=True)
            assert result["applied"] is False and len(result["collisions"]) == 1
            assert await system_hostname(conn, moving.workspace_id) == before

    run_async(scenario())
```

- [ ] **Step 2: Run them to see them fail.**

Run: `PLATFORM_PYTEST tests/test_pages_settings.py tests/clue_spine/test_hostnames_custom_pure.py tests/clue_spine/test_hostnames_move_db.py`
Expected: FAIL — no `pages_legacy_system_suffixes`, no `parse_suffixes`, no `move_system_hostnames`.

- [ ] **Step 3: The setting and its env line.** In `settings.py`, after `pages_system_suffix`:

```python
    # Wave 2 Contract 9: suffixes system hostnames USED to end in (comma-separated). Their
    # registrable domains stay reserved, so no customer can connect `x.cluehq.ai` as a custom
    # domain once published pages live on their own domain; the edge Worker 301s the old hosts
    # (infra/cloudflare/pages-edge). Env: ``CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES``.
    pages_legacy_system_suffixes: str = "pages.cluehq.ai"
```
  In `.env.example`, after `CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai` (`:601`):

```
# Suffixes system hostnames used to end in (comma-separated): their registrable domains stay reserved
# for custom domains after published pages move to their own domain (Wave 2 Contract 9).
CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES=pages.cluehq.ai
```
  and mirror the line into the lane's `.env`.

- [ ] **Step 4: Reservation and the move** in `clue_spine/hostnames.py`. Add `Sequence` to the
  `collections.abc` import and `from sqlalchemy import bindparam` beside `text`, then replace
  `validate_custom_hostname` (`:185-208`) with:

```python
def parse_suffixes(raw: str) -> tuple[str, ...]:
    """A comma-separated suffix list from the environment, lowercased, without empty entries."""
    return tuple(dict.fromkeys(part.strip().lower().strip(".") for part in raw.split(",") if part.strip().strip(".")))


def validate_custom_hostname(value: str, *, system_suffix: str, legacy_suffixes: Sequence[str] = ()) -> str:
    """Normalise and refuse with the spec §7.3 codes. Returns the normalised hostname.

    Order is invalid → reserved → apex. Our own zone apexes match BOTH the apex rule and the
    reserved rule, and must report ``hostname_reserved`` — "this is ours", not "pick a subdomain",
    since no subdomain of them can be connected either. Reserved is the narrower rule and is tested
    first. Wave 2 Contract 9: the registrable domain of the system suffix AND of every legacy suffix
    is reserved, so ``cluehq.ai`` stays unconnectable after published pages move to their own domain.
    """
    try:
        hostname = normalize_hostname(value)
    except ValueError as error:
        raise HostnameRefused("hostname_invalid", f"{value!r} is not a valid hostname") from error
    for ours in dict.fromkeys(registrable_domain(suffix) for suffix in (system_suffix, *legacy_suffixes) if suffix):
        if hostname == ours or hostname.endswith("." + ours):
            raise HostnameRefused("hostname_reserved", f"Hostnames under {ours} cannot be connected.")
    registrable = registrable_domain(hostname)
    if hostname == registrable:
        raise HostnameRefused(
            "hostname_is_apex",
            f"A dedicated subdomain such as go.{registrable} is required; the bare domain "
            f"{registrable} cannot be connected.",
        )
    return hostname
```
  and add, after `backfill_system_hostnames`:

```python
async def move_system_hostnames(
    conn: AsyncConnection, *, from_suffix: str, to_suffix: str, apply: bool = False
) -> dict[str, object]:
    """Rewrite every system hostname under ``from_suffix`` to the same label under ``to_suffix``
    (Wave 2 Contract 9). The label is kept, so ``locked_at`` keeps its promise; the old host keeps
    answering through the edge Worker's 301. A dry run unless ``apply``; it refuses to write when any
    new hostname is already taken, and then nothing moves."""
    old = from_suffix.lower().strip(".")
    new = to_suffix.lower().strip(".")
    if not old or not new or old == new:
        raise ValueError("from_suffix and to_suffix must be non-empty and different")
    rows = await conn.execute(
        text(
            "SELECT hostname FROM workspace_hostname WHERE kind = 'system' "
            "AND right(hostname, :n) = :tail ORDER BY hostname"
        ),
        {"n": len(old) + 1, "tail": "." + old},
    )
    moves = [(str(row[0]), str(row[0])[: -len(old)] + new) for row in rows.all()]
    collisions: list[str] = []
    if moves:
        taken = await conn.execute(
            text("SELECT hostname FROM workspace_hostname WHERE hostname IN :targets").bindparams(
                bindparam("targets", expanding=True)
            ),
            {"targets": [target for _old, target in moves]},
        )
        collisions = sorted(str(row[0]) for row in taken.all())
    applied = bool(apply and moves and not collisions)
    if applied:
        for previous, target in moves:
            await conn.execute(
                text("UPDATE workspace_hostname SET hostname = :new, updated_at = now() WHERE hostname = :old AND kind = 'system'"),
                {"new": target, "old": previous},
            )
    return {
        "from_suffix": old,
        "to_suffix": new,
        "rows": len(moves),
        "collisions": collisions,
        "applied": applied,
        "sample": [{"from": previous, "to": target} for previous, target in moves[:5]],
    }
```
  Export `move_system_hostnames` and `parse_suffixes` from `clue_spine/__init__.py` (import list
  and `__all__`, beside `validate_custom_hostname`).

- [ ] **Step 5: Use the legacy suffixes when a customer connects a domain.** In
  `frontend_read/settings_pages.py:300-302`, replace the call with:

```python
            hostname = validate_custom_hostname(
                raw_hostname,
                system_suffix=self._settings.pages_system_suffix,
                legacy_suffixes=parse_suffixes(self._settings.pages_legacy_system_suffixes),
            )
```
  and import `parse_suffixes` beside `validate_custom_hostname` (`:43`).

- [ ] **Step 6: The script** `scripts/move_system_hostnames.py`:

```python
#!/usr/bin/env python3
"""Move every system hostname to the published pages' own domain (Wave 2 Contract 9).

    uv run python scripts/move_system_hostnames.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:5432/clue \
        --to-suffix <the new CLUE_PAGES_SYSTEM_SUFFIX> [--from-suffix pages.cluehq.ai] [--apply]

A DRY RUN unless --apply: it prints how many rows would move, the first five moves and any
collisions, and writes nothing. With --apply it rewrites `<label>.<from>` to `<label>.<to>` for every
system row in one transaction, or refuses (exit 1) when a new hostname is already taken. Run it
after the new domain's DNS, certificate and edge redirect are live (docs/specs/pages-hosting-runbook.md §8).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from clue_db import db_lifespan, transaction
from clue_spine.hostnames import move_system_hostnames


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rewrite <label>.<from> system hostnames to <label>.<to>.")
    parser.add_argument("--database-url", required=True, help="Async Postgres URL (required; never falls through to CLUE_DATABASE_URL).")
    parser.add_argument("--to-suffix", required=True, help="The new system suffix (the published pages' own domain).")
    parser.add_argument("--from-suffix", default="pages.cluehq.ai", help="The suffix rows end in today (default: pages.cluehq.ai).")
    parser.add_argument("--apply", action="store_true", help="Write the move; without it the script only reports.")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with db_lifespan(args.database_url), transaction() as conn:
        return await move_system_hostnames(conn, from_suffix=args.from_suffix, to_suffix=args.to_suffix, apply=args.apply)


def main() -> None:
    args = _args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2))
    if result["collisions"]:
        print(f"REFUSED: {len(result['collisions'])} new hostname(s) are already taken; nothing moved.", file=sys.stderr)
        sys.exit(1)
    if not args.apply:
        print("dry run: nothing written (pass --apply to move)", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the tests.**

Run: `PLATFORM_PYTEST tests/test_pages_settings.py tests/clue_spine/test_hostnames_custom_pure.py tests/clue_spine/test_hostnames_move_db.py tests/clue_spine/test_hostnames_custom_db.py tests/api/test_pages_hostname_status.py`
Expected: all pass (every existing caller of `validate_custom_hostname` passes no legacy suffixes
and behaves as before).

- [ ] **Step 8: Commit.**

```bash
git add libs/clue-config/clue_config/settings.py .env.example libs/clue-spine/clue_spine/hostnames.py libs/clue-spine/clue_spine/__init__.py platform/api/clue_api/frontend_read/settings_pages.py scripts/move_system_hostnames.py tests/test_pages_settings.py tests/clue_spine/test_hostnames_custom_pure.py tests/clue_spine/test_hostnames_move_db.py
git commit -m "pages: keep cluehq.ai reserved after the domain move; a dry-run-by-default script moves system hostnames (label kept)"
```

- [ ] **Step 9: Only after the founder approves Q6's copy:** in
  `apps/frontend/src/features/settings/model/pages.ts:80`, set
  `hostname_reserved: "Hostnames under Clue's own domains cannot be connected.",`, run
  `cd apps/frontend && npx tsx --test src/features/settings/model/pages.test.ts` (expected: pass),
  and commit it on its own:
  `git commit -am "settings: the custom-domain refusal names Clue's own domains (both are reserved)"`.

### Task 24: The edge Worker answers an old `*.pages.cluehq.ai` host with a 301 to the new domain

`routing.js` forwards `*.SYSTEM_SUFFIX` and every host outside the zone apex (custom domains), and
passes everything else in the zone through (`infra/cloudflare/pages-edge/routing.js:4-18`). After
the move one Worker serves two zones: the new domain's system hosts are forwarded, `cluehq.ai` keeps
the SaaS custom hostnames (fallback origin `pages.cluehq.ai`), and an old system host is redirected.

**Files:**
- Modify: `infra/cloudflare/pages-edge/routing.js`, `worker.js`, `wrangler.toml`, `README.md`
- Modify: `infra/cloudflare/pages-edge/routing.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces: `decide(request, env)` returns, besides `forward` / `passthrough` /
  `method_not_allowed`, `{kind: "redirect", status: 301, location}` for `<label>.<legacy suffix>`;
  Worker var `LEGACY_SYSTEM_SUFFIXES` (comma-separated, empty = no redirects).

- [ ] **Step 1: Write the failing tests.** Append to `routing.test.js`:

```js
const moved = {
  SYSTEM_SUFFIX: "clue-pages.example",
  LEGACY_SYSTEM_SUFFIXES: "pages.cluehq.ai",
  ORIGIN_HOST: "page-origin.cluehq.ai",
  EDGE_SECRET: "s",
};

test("after the move an old system hostname answers 301 to the same label, path and query", () => {
  assert.deepEqual(decide(req("https://acme.pages.cluehq.ai/annual-report/pricing?x=1"), moved), {
    kind: "redirect",
    status: 301,
    location: "https://acme.clue-pages.example/annual-report/pricing?x=1",
  });
  assert.equal(decide(req("https://acme.pages.cluehq.ai/x", "POST"), moved).kind, "method_not_allowed");
});

test("after the move new system hosts and custom hostnames are forwarded; other cluehq.ai records pass", () => {
  for (const url of ["https://acme.clue-pages.example/annual-report", "https://go.acme.com/annual-report", "https://pages.cluehq.ai/"]) {
    assert.equal(decide(req(url), moved).kind, "forward", url);
  }
  assert.equal(decide(req("https://app.cluehq.ai/login"), moved).kind, "passthrough");
  assert.equal(decide(req("https://cluehq.ai/"), moved).kind, "passthrough");
});

test("with no legacy suffix nothing redirects (today's configuration)", () => {
  assert.equal(decide(req("https://acme.pages.cluehq.ai/annual-report"), env).kind, "forward");
});
```

- [ ] **Step 2: Run them to see them fail.**

Run: `node --test 'infra/cloudflare/pages-edge/*.test.js'`
Expected: FAIL — the old host is forwarded, not redirected.

- [ ] **Step 3: Replace `routing.js`.**

```js
// Pure routing decision for the pages-edge Worker (custom-domain publishing spec §5.1; Wave 2
// Contract 9: published pages on their own registrable domain), kept separate from the fetch
// handler so it runs under `node --test` without a Workers runtime.
const apexOf = (suffix) => suffix.split(".").slice(-2).join(".");
const under = (host, suffix) => host === suffix || host.endsWith("." + suffix);

export function decide(request, env) {
  const url = new URL(request.url);
  const host = url.hostname.toLowerCase();
  const suffix = env.SYSTEM_SUFFIX.toLowerCase();
  const legacy = (env.LEGACY_SYSTEM_SUFFIXES || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter((value) => value && value !== suffix);
  const readOnly = request.method === "GET" || request.method === "HEAD";
  // An old system hostname (<label>.pages.cluehq.ai) answers 301 with the same label, path and
  // query on the new domain. The bare old suffix is the Cloudflare for SaaS fallback origin and is
  // left as it was (custom-domain traffic arrives with the customer's own Host).
  for (const old of legacy) {
    if (host.endsWith("." + old)) {
      if (!readOnly) return { kind: "method_not_allowed" };
      const label = host.slice(0, -(old.length + 1));
      return { kind: "redirect", status: 301, location: `https://${label}.${suffix}${url.pathname}${url.search}` };
    }
  }
  const apexes = [apexOf(suffix), ...legacy.map(apexOf)];
  const ours = under(host, suffix) || legacy.includes(host) || !apexes.some((apex) => under(host, apex));
  if (!ours) return { kind: "passthrough" };
  if (!readOnly) return { kind: "method_not_allowed" };
  const headers = new Headers(request.headers);
  headers.delete("x-clue-public-host");
  headers.delete("x-clue-edge-auth");
  headers.set("x-clue-public-host", host);
  headers.set("x-clue-edge-auth", env.EDGE_SECRET);
  const target = new URL(url.pathname + url.search, "https://" + env.ORIGIN_HOST).toString();
  return { kind: "forward", host, target, headers, method: request.method };
}
```

- [ ] **Step 4: Answer the redirect** in `worker.js`, after the `method_not_allowed` line:

```js
    if (decision.kind === "redirect") return Response.redirect(decision.location, decision.status);
```

- [ ] **Step 5: The Worker config.** In `wrangler.toml`, under `[vars]`, add:

```toml
# Wave 2 Contract 9 — published pages on their own domain. Empty today. At the move (runbook §8):
# SYSTEM_SUFFIX becomes the new domain, LEGACY_SYSTEM_SUFFIXES = "pages.cluehq.ai", and a second
# route `{ pattern = "*/*", zone_name = "<new domain>" }` joins the one above, so this Worker 301s
# every <label>.pages.cluehq.ai URL to <label>.<new domain> and serves the new hosts.
LEGACY_SYSTEM_SUFFIXES = ""
```
  and add to `README.md`: "After the published-pages domain move, the Worker also answers an old
  `<label>.pages.cluehq.ai` request with a 301 to the same path on `<label>.<SYSTEM_SUFFIX>`
  (`LEGACY_SYSTEM_SUFFIXES`); see `docs/specs/pages-hosting-runbook.md` §8."

- [ ] **Step 6: Run the tests.**

Run: `node --test 'infra/cloudflare/pages-edge/*.test.js'`
Expected: all pass, the three original tests included.

- [ ] **Step 7: Commit.**

```bash
git add infra/cloudflare/pages-edge
git commit -m "pages-edge: 301 old <label>.pages.cluehq.ai hosts to the published pages' own domain (inert until LEGACY_SYSTEM_SUFFIXES is set)"
```

### Task 25: The production env check, and the runbook for the move

`deploy/check_prod_env.py:20` pins `CLUE_PAGES_SYSTEM_SUFFIX` to `pages.cluehq.ai`, which would
refuse the move; it must instead accept today's value or a hostname off `cluehq.ai`, and once the
suffix has moved, insist the old suffix stays in `CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES`.

**Files:**
- Modify: `deploy/check_prod_env.py:18-23,64-70,89-110`
- Modify: `tests/deploy/test_check_prod_env.py`
- Modify: `docs/specs/pages-hosting-runbook.md` (new §8), `docs/deploy/runbook.md:23-24`,
  `DEV_STACK.md:148`

**Interfaces:**
- Consumes: the setting names from Task 23.
- Produces: `check_prod_env.LEGACY_PAGES_SUFFIX = "pages.cluehq.ai"`; the two new problem messages below.

- [ ] **Step 1: Write the failing tests.** Append to `tests/deploy/test_check_prod_env.py`:

```python
def test_the_pages_suffix_may_move_to_its_own_domain() -> None:
    env = {**GOOD_PLATFORM, "CLUE_PAGES_SYSTEM_SUFFIX": "clue-pages.example"}
    assert check.problems(env, "platform-api") == []


def test_the_pages_suffix_never_moves_to_another_cluehq_name_or_localhost() -> None:
    for value in ("pages2.cluehq.ai", "cluehq.ai"):
        env = {**GOOD_PLATFORM, "CLUE_PAGES_SYSTEM_SUFFIX": value}
        assert any("CLUE_PAGES_SYSTEM_SUFFIX must be pages.cluehq.ai or a hostname on the published pages' own domain" in p for p in check.problems(env, "platform-api")), value
    env = {**GOOD_PLATFORM, "CLUE_PAGES_SYSTEM_SUFFIX": "pages.localhost"}
    assert any("CLUE_PAGES_SYSTEM_SUFFIX points at localhost" in p for p in check.problems(env, "platform-api"))
    missing = {k: v for k, v in GOOD_PLATFORM.items() if k != "CLUE_PAGES_SYSTEM_SUFFIX"}
    assert any("CLUE_PAGES_SYSTEM_SUFFIX must be set" in p for p in check.problems(missing, "platform-api"))


def test_after_the_move_the_old_suffix_stays_a_legacy_suffix() -> None:
    env = {**GOOD_PLATFORM, "CLUE_PAGES_SYSTEM_SUFFIX": "clue-pages.example", "CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES": "old.example"}
    assert any("CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES must keep pages.cluehq.ai" in p for p in check.problems(env, "platform-api"))
    kept = {**env, "CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES": "old.example,pages.cluehq.ai"}
    assert check.problems(kept, "platform-api") == []
```

- [ ] **Step 2: Run them to see them fail.**

Run: `PLATFORM_PYTEST tests/deploy/test_check_prod_env.py`
Expected: FAIL — the new domain is refused ("must be 'pages.cluehq.ai'").

- [ ] **Step 3: Change the check.** In `deploy/check_prod_env.py`:
  - delete `"CLUE_PAGES_SYSTEM_SUFFIX": "pages.cluehq.ai",` from `EXACT`;
  - add `"CLUE_PAGES_SYSTEM_SUFFIX",` to `REQUIRED` and to `NOT_LOCAL`;
  - add after `EXACT`:

```python
#: Where published pages lived before they moved to their own registrable domain (Wave 2
#: Contract 9). A production suffix is this one, or a hostname off cluehq.ai.
LEGACY_PAGES_SUFFIX = "pages.cluehq.ai"
```
  - in `problems()`, after the `NOT_LOCAL` loop, add:

```python
    suffix = env.get("CLUE_PAGES_SYSTEM_SUFFIX", "").strip().lower()
    if suffix and suffix != LEGACY_PAGES_SUFFIX:
        if suffix == "cluehq.ai" or suffix.endswith(".cluehq.ai"):
            found.append(
                "CLUE_PAGES_SYSTEM_SUFFIX must be pages.cluehq.ai or a hostname on the published "
                f"pages' own domain, never another cluehq.ai name (is {suffix!r})"
            )
        legacy = env.get("CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES")
        if legacy is not None and LEGACY_PAGES_SUFFIX not in [part.strip().lower() for part in legacy.split(",")]:
            found.append(
                "CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES must keep pages.cluehq.ai once published pages "
                "move to their own domain (the custom-domain reservation depends on it)"
            )
```

- [ ] **Step 4: The runbook.** Append to `docs/specs/pages-hosting-runbook.md`:

```markdown
## 8. Moving published pages to their own domain (Wave 2, Contract 9) [FOUNDER]

Every workspace's published pages move from `<label>.pages.cluehq.ai` to `<label>.<new domain>`;
old URLs answer 301 at the edge; `cluehq.ai` stays reserved for custom domains (customers can never
connect a `*.cluehq.ai` hostname). Do the steps in order; each is safe to stop after.

1. Register the domain. Add it to Cloudflare as its own zone; add a proxied wildcard record
   `*` → the page-origin service (as `*.pages` is today, §5). A first-level wildcard is covered by
   Universal SSL. Apply to the Public Suffix List if the domain should be listed (§5 of the
   isolation research, `docs/superpowers/specs/2026-10-09-code-first-builder-isolation-research.md`).
2. Deploy the Worker with the new domain (`infra/cloudflare/pages-edge/wrangler.toml`):
   `SYSTEM_SUFFIX = "<new domain>"`, `LEGACY_SYSTEM_SUFFIXES = "pages.cluehq.ai"`, and a second
   route `{ pattern = "*/*", zone_name = "<new domain>" }`. Check:
   `curl -sI https://<a label>.pages.cluehq.ai/<a slug>` → `301` with
   `location: https://<a label>.<new domain>/<a slug>` — and the new URL serves the page once step 4 ran.
3. Set the env on every service (Railway shared variables and the VM's `/srv/clue/env`):
   `CLUE_PAGES_SYSTEM_SUFFIX=<new domain>`, `CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES=pages.cluehq.ai`.
   Leave `CLUE_PAGES_CNAME_TARGET=pages.cluehq.ai`: custom domains stay on the cluehq.ai zone.
   `python3 deploy/check_prod_env.py <role> <env file>` must pass for each role.
4. Move the rows: `uv run python scripts/move_system_hostnames.py --database-url <prod> --to-suffix <new domain>`
   (dry run: check `rows` and `collisions: []`), then the same with `--apply`. Restart the page
   origin and the platform API; their startup warning `pages.system_hostnames_off_suffix` must list
   nothing.
5. Republish isn't required: published HTML is root-relative. Only `og:image` and the manifest's
   `canonical_url` name the old host, and the 301 covers them; a republish refreshes them.
```
  In `docs/deploy/runbook.md:23-24`, change "(Worker, edge secret, Cloudflare for SaaS on
  `pages.cluehq.ai`)" to "(Worker, edge secret, Cloudflare for SaaS on `pages.cluehq.ai`; the move to
  the published pages' own domain is that runbook's §8)". In `DEV_STACK.md:148`, change
  "(`CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai`, edge-secret posture)" to
  "(`CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai`, `CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES=pages.cluehq.ai`,
  edge-secret posture)".

- [ ] **Step 5: Run the deploy tests.**

Run: `PLATFORM_PYTEST tests/deploy/test_check_prod_env.py tests/deploy/test_vm_deploy.py tests/deploy/test_vm_compose.py`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add deploy/check_prod_env.py tests/deploy/test_check_prod_env.py docs/specs/pages-hosting-runbook.md docs/deploy/runbook.md DEV_STACK.md
git commit -m "deploy: the pages suffix may move to its own domain (never another cluehq.ai name); runbook for the move"
```

---

## After the last task

- [ ] **Whole-lane check.** Run, and record the results in `_memory/`:
  - `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx`
  - `cd apps/frontend && npm run typecheck -w @clue/site-kit`
  - every design API file this plan created or changed, one `DESIGN_PYTEST` each:
    `test_site_document_kind.py test_site_validation.py test_site_tools.py test_site_write_routes.py
    test_site_sanitize.py test_site_render.py test_site_thumbnails.py test_site_publish_package.py
    test_site_publish_routes.py test_site_export.py test_write_path_governance.py test_web_export.py
    test_web_pdf_export.py test_web_operations.py test_document_thumbnails.py test_agent_run_write_lock.py
    test_public_pages.py test_web_documents.py`
  - the platform files: `tests/api/test_site_kind_labels.py tests/api/test_site_wire_kind.py
    tests/api/test_design_turn_targets.py tests/api/test_chat_composer_context.py
    tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py
    tests/api/test_agent_registry_wiring.py tests/page_origin tests/design/test_publish_delivery.py
    tests/test_pages_settings.py tests/clue_spine tests/deploy tests/api/contract_v1/test_contract_v1.py`
  - `node --test 'infra/cloudflare/pages-edge/*.test.js'`
- [ ] **Deploy risk to hand over:** `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=1` asks Chromium for its own
  sandbox. If the backend image cannot start it under the container's seccomp profile ("No usable
  sandbox"), the site renderer refuses with `render.failed`; set the variable to `0` for that
  service, record why, and tell the founder. Add `check "chromium launches sandboxed" run python -c
  "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(chromium_sandbox=True); b.close(); p.stop()"`
  to `docker/backend/smoke.sh` beside "chromium launches" to find out at image build time.
- [ ] **Session memory:** add a closing `_memory/` entry (what landed, which tests ran, the open
  founder questions, the B2/B6 seam assignments Lane B must replace).

## Self-review notes

- **Contract coverage.** Contract 1 (asset paths, routes, ids): Tasks 2, 11, 14. Contract 2 (routes,
  refusals, cap, snapshot history, CLI validation over stored schemas, the three governed tools in
  four registries): Tasks 3, 11, 12, 13. Contract 3 (renderer, schema read, screenshot, codes,
  cleaner, per-publish CSP): Tasks 15, 16, 17, 19. Contract 8 backend half: Tasks 9, 10. Contract 9
  published pages: Tasks 23, 24, 25. Brand fidelity site-kit half: Tasks 4–7. Assignments A0–A10:
  A0 = 1–3, A1 = 8–10, A2 = 11–13, A3 = 14, A4 = 10, A5 = 15–17, A6 = 18, A7 = 19–21, A8 = 22,
  A9 = 4–7, A10 = 23–25.
- **Review focus → tests.** 1: `test_a_stale_save_is_refused_with_the_current_version`,
  `test_a_save_is_refused_while_a_site_turn_runs` (Task 13). 2: `test_undo_and_redo_walk_the_snapshots_exactly`,
  `test_versions_list_newest_first_and_a_restore_is_undoable` (Task 13). 3:
  `test_custody_refuses_a_digest_this_workspace_does_not_hold` (Task 11),
  `test_an_image_this_workspace_does_not_hold_is_refused_by_name` (Task 13). 4: the hostile tests of
  Task 17, the cleaner tests of Task 16, `test_agent_html_publishes_without_script_handlers_or_foreign_urls`
  and the missing-module tests of Tasks 20–21. 5: Tasks 23–24.
- **Interfaces checked across tasks:** `makeKit(href, brand)` (5 → 15), `tailwindThemeCss` (4 → 15 →
  17), `validateSite(…, images)` (2 → 3 → 11), `pinned_modules` (11 → 17, 20), `load_section_modules`
  (11 → 12, 18, 21, 22), `SiteRenderError` codes (11 → 17 → 18, 20, 21, 22), `gated_brand` /
  `site_delivery_csp` (20 → 22), `_commit_publish_package` (21), `design_kind_label` (9) and
  `wire_kind` (10), `delivery_csp(delivery=…)` (19 → 20).
