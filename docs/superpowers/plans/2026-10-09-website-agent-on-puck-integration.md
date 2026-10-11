# Website agent on Puck: integration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal.** A marketer asks Head of ABM for a 1:1 site in chat. The Puck agent builds it, the
marketer edits it in our editor, and it publishes to their domain. Everything runs on the existing
platform services, as a third document kind (`site`) beside `scene` and `web`, behind a
per-workspace flag.

**Architecture.**
- **The platform keeps:** legs, runs, the fleet, SSE, stop, the exit judge, research reads, cost
  ledgers, publish storage, the page origin and domains.
- **Puck plugs in at five existing switch points,** cited below.
- **Three pieces are new:**
  - a Node site renderer feeding the existing `PublishPackage` contract;
  - runtime loading of agent-written sections (option A, proven by the Wave 1 spike);
  - the editor domain: the Puck editor served from its own domain, with no login there, embedded
    in app.cluehq.ai as one frame (D2, decided 2026-10-09; see "D2" below).
- **Shared code** lives in one workspace package, `@clue/site-kit`, inside `apps/frontend`.

**Tech stack.**
- Python 3.12, FastAPI, Alembic and Postgres (design API and platform).
- deepagents 0.6.12 (`subsystems/clue-design/apps/agent_runtime/pyproject.toml:45`).
- Next 16.2.12, React 19.2.4, Zod 4 and Tailwind 4 (`apps/frontend/package.json`, the same stack
  as `trials/puck-spike/package.json`).
- `@puckeditor/core` 0.23.0.
- esbuild 0.28.2 (already present as a dependency of tsx).

**Spec.** `docs/superpowers/specs/2026-10-08-puck-production-readiness-map.md`, with the roadmap
`docs/superpowers/specs/2026-10-08-website-agent-on-puck-roadmap.md` and the founder rulings
recorded there and below. Both are drafts. The founder approved this direction on 2026-10-09:
option A for agent code, one Node renderer, a per-workspace flag, and Head of ABM unchanged.
The founder decided D2 later the same day: the separate-domain editor.

---

## Evidence: the switch points this plan builds on

Every task below changes one of these. Paths are relative to the repo root.

| # | Today (file:line) | What it does | Change |
|---|---|---|---|
| S1 | `platform/api/clue_api/design_leg_tools.py:540`: birth through an injectable `WebDocumentMinter`; `create_document(doc_kind="web")` at `:1002`; production wiring `toolbelt_wiring.py:3183` passes only `enabled=` | A new website is born as an empty WebDoc from the Rust helper (`design_tools.py:84` `mint_empty_web_document`) | Behind the flag, mint an empty **site** document (no engine) with `doc_kind="site"`. Head of ABM keeps calling `open_design_leg(doc_kind="web")` |
| S2 | `subsystems/design/clue_design/documents.py:188` `create_document`: branches only `if doc_kind == "web"`; any other kind reads `scene["meta"]["id"]` | Stores a document; stamps the approved kit at birth (`:64`, which only sets `theme.brand_kit`) | Add `"site"` to the `web` branch. `update_web_document` (`:595`) only reads `web_doc["title"]`, so it is reused as is |
| S3 | `platform/api/clue_api/design_leg_wiring.py:2568`: `"web_turn" if doc_kind == "web" else "agent_turn"` | Picks the runtime from the document kind | `site` → `site_turn` |
| S4 | `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py:679` picks an executor between two; capabilities `{"agent_turn","web_turn"}` at `:213`; `execute_web_turn_job` at `lumen_api/main.py:11099` | Runs a design turn: spend scope, model-call collector, CAS persist | Add `execute_site_turn_job` and the `site_turn` capability |
| S5 | `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx:471`: `artifactKind === "web" ? <WebArtifactCanvas> : <SceneArtifactCanvas>`; artifact kind `z.enum(["web","ad"])` in `design-editor/model/artifact.ts:17,31` | Picks the editor canvas | `site` → `<SiteArtifactCanvas>` (Puck) |
| P | `subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py:94` `publish_web_document`; `PublishPackage.pages=[{page_id, route, html, html_digest}]` at `web_export.py:325-346`; Node is already run from `web_export.py:72` | Builds the package, then writes the revision, locks the hostname, upserts the publish and unpublishes old slugs | A site package builder feeds the same `PublishPackage`; everything after it is unchanged |

**Database enums** (one column each; no index or constraint references them):
- `design_doc_kind` (`scene`, `web`) on `design_document.doc_kind`, default `'scene'`
  (`alembic/versions/7bff99d2ad65…:79`);
- `design_run_kind` (`agent_turn`, `web_turn`) on `design_agent_run.kind`
  (`alembic/versions/50b84c524fa2…:116,124`).

Parity with `clue_design.enums` (labels and order) is tested by
`tests/design/test_design_schema_db.py:83`. Postgres cannot drop an enum label, so reversible
widening rebuilds the type (the pattern at `50b84c524fa2…:101-111`). The current head is
`10edab6dd974`.

**Kind branches that assume "web or else scene"** (a site document must never fall into the
scene path). `doc_kind == "web"` appears at:
- `artifact_read_tools.py:170`;
- `design_leg_tools.py:775`;
- `design_leg_wiring.py:315, 714, 1491, 2568`;
- `chat/composer_context.py:285, 784`;
- `chat/router.py:1415`;
- `clue_design/documents.py:201, 382`;
- `lumen_api/dto.py:14`;
- `lumen_api/design_store.py:649`;
- `lumen_api/main.py:2507, 2606, 8161, 8190`.

Two SQL filters use `doc_kind = 'web'` (`documents.py:299, 741`; templates and account documents,
out of scope until templates).

**Reads the agent reuses** (`platform/api/clue_api/design_platform_reads.py`):
`read_project_accounts:189`, `read_account_research:202`, `read_claims:224`, `web_search:305`,
`seller_knowledge:340`. The spike's harness already gets the same object from
`trials/web-agent/run_trial.py:152` `build_platform_reads`.

**Image generation:** `lumen_api/image_provider.py:249` `generate(prompt, width, height,
aspect_ratio, reference_images, …) -> ImageGenerationResult(image_bytes, mime_type, width,
height, …)`.

**Released clones:** `lumen_api/agent_cloned_sections.py` (the registry behind
`search_cloned_sections`, with degraded and lineage logic); payloads come from
`read_web_fragment(storage, workspace_id, fragment_id)` (used by
`trials/puck-spike/export/export_brand.py:198`).

## Global constraints

- **Git:** never push. Commit locally at checkpoints, with no AI attribution in messages. Work
  stays on a feature branch, never `main`.
- **Env parity:** every new runtime flag goes into `.env.example` with its default the moment it is
  introduced. A design-API flag also goes into `subsystems/clue-design/.env.example`.
- **Alembic:**
  - create migrations with `alembic revision -m "<slug>"`, never hand-picking ids;
  - every `upgrade()` has a matching `downgrade()`;
  - exactly one head (`alembic heads`);
  - Python enums mirror database enums;
  - `make db-smoke` runs on a throwaway database.
- **WebDoc stays untouched.** With the flag off, every existing path behaves byte-identically. No
  old-lane gate may block the new lane.
- **Founder rulings (2026-10-08 and 2026-10-09):**
  - clones first; a component is built only when a request needs more than a clone allows;
  - the marketer never sees "clones" or "components";
  - contracts live in code, judgement in prompts;
  - agent-facing prompt or skill text is shown to the founder before it is written;
  - the editor UI comes only from the existing chat-shell / dummy UI, so new controls need a
    design first;
  - no pre-emptive caps on agents: 100 rounds, 50 calls per round, 30 minutes.
- **Tests:**
  - never assert which model a setting names;
  - never run `*_live.py` or broad suites with real keys (`--ignore-glob='*_live.py'`);
  - database suites run only on the lane's throwaway DB, with the design stack down;
  - live model runs spend money and need the founder's go.
- **Brand fidelity (production requirement, roadmap phase 1):** the agent sees every kit type
  role; surfaces cover band colours; the kit covers logos (`contain`), a second button style and
  in-site links.
- **Agent-written code never runs on app.cluehq.ai or in a platform process (D2):** in the
  browser only on the editor domain; on the server only inside the hardened headless-Chromium
  render page (founder 2026-10-11). Node only transforms or scans agent code (esbuild, tsc,
  Tailwind); it never imports or runs it.

## Review focus

Each failure mode has a test in its owning task.

1. **A site document reaching a scene-only path** (any kind branch listed above): it must refuse
   with a typed error or treat site as its own kind. Never scene. Tests in Task 2, Task 3 and A1.
2. **Flag off is byte-identical:** a workspace not in the flag births a WebDoc exactly as today.
   Test in Task 3.
3. **A site turn before the site executor exists:** a born site document must not route to
   `agent_turn`. It refuses until B5 lands. Test in Task 3.
4. **Tenant isolation of agent-written sections:** workspace A can never load workspace B's
   modules, in the editor or the renderer. Tests in Task 4 (spike) and B6.
5. **Publish with a missing or stale agent-section module** refuses with a typed reason. It never
   publishes a blank section. Test in A7.
6. **An agent section reaching the marketer's session:** in the editor, the spike's hostile
   sections (tracking pixel, `Function` via a constructor, `top`/`parent` navigation, cookie and
   API reads) are contained by the editor domain and its policy. Test in C11.
7. **Agent script in published HTML:** a section that emits `<script>`, an `on*` handler or an
   off-allowlist URL publishes without it. Test in A7.
8. **A server render that misbehaves:** a section that loops forever, prints a huge page, tries the
   network (fetch, an image, a WebSocket) or tries to read local files ends as a typed render
   failure with nothing sent out and the worker unharmed. Test in A5.

---

## D2: where agent-written code runs (decided 2026-10-09)

**Why.**
- Task 4 showed option A gives no containment. Puck mounts components into its `srcDoc` canvas
  with `createPortal`, so section code runs in the editor's window, with the marketer's session.
  Four hostile probes passed the lint (`trials/puck-spike/RUNTIME-SECTIONS.md`).
- The research found every AI and code-first builder runs generated code away from the logged-in
  app, one boundary per surface, never per section
  (`docs/superpowers/specs/2026-10-09-code-first-builder-isolation-research.md`).

**The design.**
- **The editor domain.** The Puck canvas is a page on a separate registrable domain that never
  holds the marketer's login. app.cluehq.ai embeds it as one `<iframe>` in the stage and keeps chat,
  header, gallery, asset library, versions and publish. **Fields and Layers stay in the app's
  designed dock** (founder 2026-10-11): the frame describes the selected component's fields as
  data, the app draws them with the inspector primitives, and edits go back to the frame as
  messages. Agent code still only ever runs in the frame. Decided
  (founder, 2026-10-09): one subdomain per workspace (Framer's per-project pattern) on one wildcard
  domain. That is one deployment, one wildcard DNS record and one wildcard certificate; no servers
  per workspace.
- **Frame attributes.** `sandbox="allow-scripts allow-same-origin"`, with no `allow-top-navigation`
  or popups. `allow-same-origin` is safe here only because the editor domain differs from the
  app's; Puck needs it for its own canvas frame and browser storage.
- **The editor domain's headers.** A content security policy:
  - `script-src 'self'`, with no `'unsafe-eval'` and no `blob:`;
  - `connect-src` limited to the editor domain and the asset store;
  - `img-src` and `font-src` limited to the asset store (plus `data:`);
  - `frame-ancestors` limited to app.cluehq.ai.
- **Messages.**
  - App → frame: page data, agent updates, the brand catalog, short-lived module links, chosen
    assets.
  - Frame → app: page changes (batched), selections, asset-picker requests.
  - The app checks the source, schema and document id of every message, and saves with the
    marketer's login.
- **Server render (founder 2026-10-11): hardened headless Chromium for every site,** with no
  container and no split by content. A fresh browser context per render, Chromium launched with a
  stripped environment, the network blocked in layers (the render page's CSP,
  `--host-resolver-rules`, a dead-end proxy, WebRTC off, Playwright request blocking), a time limit
  and an output cap; the HTML is sanitized before it is published. The locked container stays the
  documented upgrade if agent sections become common.
- **Publish.** An allow-list sanitizer over agent-section HTML, and a security policy on published
  pages.
- **Accepted latency (founder, 2026-10-09).** First open a few hundred ms; a few ms per message.
  No measurement spike.
- **Published-page domain (founder decision, 2026-10-09): its own registrable domain from the
  start.** It replaces the `*.pages.cluehq.ai` default (`.env.example:601`) and is distinct from
  the editor domain. The name is to be chosen. Owner A7.
- **Research input (founder ruling, 2026-10-09, D3):** the brief gives direction and suggestions;
  the page agent reads the research and chooses its facts on its own reasoning (Task 5).

---

## Wave 2: rulings and cross-lane contracts (2026-10-11)

The lane plans (`2026-10-11-lane-a-…`, `-lane-b-…`, `-lane-c-…`) implement these contracts. A lane
may refine a detail inside its own code, but a change to anything below is a change to this section
first, with the founder's sign-off where it is product-facing.

### Rulings

- **R4 is dropped** (founder). The week-6 regression run adds: each page is at least as good as its
  spike version, plus a founder look beside the platform pages already on record.
- **R2 (on-demand rebuild during edits) → Lane B; R5 (rich text with our inline menu) → Lane C.**
- **Brand fidelity is split:** site-kit's kit, theme and `brand.md` (all 12 type roles marked
  measured or derived, `contain` image fit, a second button style, `kit.Link`, extra and band
  surfaces, the kit's own rules) → Lane A; turning the stored kit into `BrandData` → Lane B. There
  is no production "measured" button: button styles come from the kit's tokens, `brief.constraints`
  and `brief.component_recipes`.
- **B4 is wiring only:** the hybrid image search arrived with the scene-ad merge (`deb3a0e98`).
- **Editor layout:** canvas in the frame, fields and Layers in the app (see D2).
- **Pages UI (founder 2026-10-11, the Ploy reference):** for sites, the stage's top bar gets a
  **Pages** toggle that opens a page panel on the left of the canvas (a count, a search box, one row
  per page with a home icon for `/`), and a browser-style **URL toolbar** (back, forward, the device
  menu, the current route, editable to jump, and reload). Adding, renaming and deleting pages stays
  with the agent until designed. Header and footer are edited by selecting them on the canvas.
- **Server render:** hardened headless Chromium (see D2).
- **Published-pages domain (founder 2026-10-11):** every workspace moves to the new registrable
  domain; old `*.pages.cluehq.ai` URLs redirect at the edge; `cluehq.ai` stays reserved for custom
  domains. The domain name is the founder's to register.
- **The frontend's Railway build** must copy `packages/site-kit` before `npm ci`
  (`apps/frontend/Dockerfile.railway:10-12`); it is Lane C's first task.
- **Plan review (controller, 2026-10-11)** — rulings applied to the contracts below and to the lane
  plans (each lane plan lists them under "Controller review rulings"):
  - **Site tools are registered ungranted** (R6). `design_write_site`, `design_undo_site`,
    `design_redo_site` and `design_publish_site` are called by the editor's routes (as the person)
    and by the site turn's executor (from code), never named by a model, so they sit on the
    ad-assets lane's footing. Granting them to the design role without a profile pin would have
    stopped `build_agent_profile_registry` composing at platform start-up. No model can save, undo,
    redo or publish a site directly; granting one later is a reviewed profile bump.
  - **The marketer's selection reaches the site agent** (R9, Contract 7). The first plans carried it
    only as far as the composer.
  - **Order:** Lane C's C1 before Lane A's mapper (Contract 8); Lane A Task 9 (labels, summaries,
    account card) before Lane B Task 13; Lane B2's `BrandData` builder before Lane C's saves, the
    renderer, thumbnails, publish and export work against a real workspace (until then they refuse
    with 503 `site_inputs.unavailable`); Lane B6's section loader before a site with agent sections
    saves or publishes.

### Contract 1: the site document

Stored in `design_document.current_scene_json` for `doc_kind = 'site'`:

```json
{
  "id": "doc_…", "title": "…", "theme": {"brand_kit": {"id": "…", "version": 2}},
  "pages": {
    "/":         {"root": {"props": {"title": "…"}}, "content": [{"type": "Hero", "props": {"id": "Hero-1a2b", "…": "…"}}]},
    "/analysis": {"root": {"props": {"title": "…"}}, "content": []}
  },
  "shell": {"header": {"id": "header", "…": "…"}, "footer": {"id": "footer", "…": "…"}},
  "agent_sections": {"AnalysisSteps": "<sha256 of the compiled module>"}
}
```

- Routes are `/` or `/<name>` with `<name>` matching `^[a-z0-9][a-z0-9-]*$` (site-kit `validate.ts`).
- Every image, logo and generated picture in props is `/asset-store/<sha256>`, a blob of this
  workspace. No `/brands/…`, `/generated/…` or `/accounts/…` paths in production.
- `props.id` is unique within a page and matches `^[A-Za-z0-9_-]{1,200}$` (the site-kit validator
  refuses anything else, R10), so `site:<route>#<id>.<field>` is never ambiguous; the shell's header
  and footer carry `id` `header`/`footer`.
- The kit ref under `theme.brand_kit` uses the design DAL's own key, `id` (`clue_design/brand.py:299`).
- A component in an agent section is `type == <Name>` where `<Name>` is a key of
  `agent_sections`.

### Contract 2: writing, undoing and versions (design API, Lane A)

| Route | Body | Success | Refusals |
|---|---|---|---|
| `PUT /documents/{id}/site` | `{site, base_version, intent?}` | 200 `{schema_version: 1, document: {id, current_version, doc_kind: "site"}}` | 409 `edits.base_version_mismatch` + `current_version`; 422 `site.invalid` + `errors[]`; 409 `document.agent_run_active` while a site turn runs; 409 `document.kind_unsupported` for a non-site; 409 `document.finalized`; 503 `site_inputs.unavailable` (no brand builder yet) / `site_validator.unavailable` |
| `POST /documents/{id}/site/undo` · `/redo` | `{base_version}` | 200 `{document, undone_batch_id}` · `{document, redone_batch_id}` | 409 `undo.empty` · `redo.empty`; 409 `edits.base_version_mismatch` |
| `GET /documents/{id}/site/versions?limit=` | | 200 `{versions: [{batch_id, version, actor_kind, intent, created_at}]}` newest first | |
| `POST /documents/{id}/site/versions/{batch_id}/restore` | `{base_version}` | 200 `{document}`; the restore is itself an undoable write | 404 `version.not_found` |
| `GET /documents/{id}/site/brand` (R3) | | 200 `{schema_version: 1, brand: BrandData}`, every `file` `/asset-store/<sha256>`; the editor frame's `init` | 503 `site_inputs.unavailable` until Lane B2; 409 `document.kind_unsupported` |

- One save is one undo step; one agent turn is one undo step; the stack cap is 50 (the web cap).
- History is `design_edit_envelope` with whole-site snapshots: `operations = [{"kind":
  "replace_site", "site": new}]`, `inverse_operations = [{"kind": "replace_site", "site": old}]`.
- Validation is contracts only: the site-kit validator run as a Node CLI over JSON, with agent
  sections checked against their **stored props JSON Schema**, never by importing the module.
- Governed tools (all four registries updated together): `design_write_site`,
  `design_undo_site`, `design_redo_site`, registered **ungranted** (R6).
- `GET /documents/{id}` answers a site like a web document (`scene`, `current_version`,
  `undo_stack`/`redo_stack`, no scene `render_context`); the editor reads the stack depths there and
  counts between loads, as the web editor does.

### Contract 3: the renderer and the cleaner (Lane A; Lane B calls it)

- `lumen_api/site_render.py`:
  - `render_site(site, brand, sections, *, base_path, routes=None, timeout_s=20.0, max_output_bytes=…, node_bin="node") -> SiteRender`
  - `SiteRender(pages: list[RenderedPage], css: str, warnings: list[str])`,
    `RenderedPage(route: str, html: str)`
  - `SectionModule(name: str, digest: str, module_js: str, css: str, props_schema: dict)`
  - `read_section_schema(module_js: str, *, timeout_s=10.0) -> dict`: imports one compiled agent
    section inside the hardened render page and returns its props JSON Schema (Lane B6 calls it at
    compile time; nothing else ever imports an agent module on the server).
  - `capture_site_screenshot(page: RenderedPage, css: str, *, width: int, full_page: bool = True,
    height=…, scale=…, timeout_s=…) -> bytes`: a PNG of rendered, sanitized HTML in a hardened page
    with JavaScript off and the network blocked (Lane B3's `render_page`, Lane A6's thumbnails).
    It can only show images that are already `data:` URIs, so callers inline `/asset-store/`
    references first (`web_pdf.inline_asset_store_refs`).
  - `read_section_schema` also refuses a module whose schema is not a Zod object, lacks `id` or
    `surface`, carries `className`/`style`, or has no `render`.
  - WebSockets are mocked by a route that never connects and never calls `ws.close()` (closing from
    the handler hung the render page under its CSP, Playwright 1.61).
  - Failures raise `SiteRenderError(code)` with `code` in `render.timeout`,
    `render.output_too_large`, `render.section_module_missing`, `render.failed`.
- How it works: one headless Chromium page per render, in a fresh context, loads a render shell
  (site-kit's browser render bundle, the page data, `BrandData` and the section modules) through
  `set_content`, waits for the shell's done signal and reads back each route's HTML. The CSS is
  compiled by Node Tailwind over that HTML (scanning text only).
- `lumen_api/site_sanitize.py`: `sanitize_site_html(html) -> SanitizedHtml(html, removed)` strips
  `script`, `iframe`, `object`, `embed`, `form`, `base`, `meta`, `link`, every `on*` attribute,
  `javascript:` URLs, and any `src`, `srcset`, `poster` or CSS `url()` that is not
  `/asset-store/<sha256>`, a relative site route or `data:`. It strips; it does not refuse.
- The published page's CSP: `default-src 'none'; script-src 'none'; style-src 'self'
  'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src
  'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'`, chosen per publish at the
  page origin.

### Contract 4: agent sections (Lane B stores, Lane A renders, Lane C loads)

- Table `design_site_section`: `workspace_id`, `digest` (sha256 of the compiled module),
  `name`, `source_sha256`, `module_sha256`, `css_sha256`, `props_schema_json`, `created_at`,
  `created_by_run_id`; primary key `(workspace_id, digest)`. Bytes live in `DesignBlobStore`.
- DAL `subsystems/design/clue_design/site_sections.py`: `record_site_section(...)`,
  `get_site_sections(conn, *, workspace_id, digests) -> list[...]`.
- Compile (esbuild, tsc, the lint) runs in Node and never executes the module. The props schema is
  read inside the hardened render page.
- **Never served through `/asset-store`:** the public byte read skips blobs whose `source_key` is
  `design_site_section` (Lane B Task 2). The editor gets a module through a short-lived link:
  the app asks `POST /documents/{id}/site/section-links` (the document must reference the digest)
  and receives `{"schema_version": 1, "links": [{name, digest, token, expires_at, props_schema}]}`
  (R1); the token is an HMAC over `(workspace_id, document_id, digest, expires_at)` with
  `CLUE_SITE_SECTION_LINK_SECRET`, 10 minutes. The editor app's own server routes
  `GET /sections/<digest>.mjs|.css?t=<token>` call the design API's headerless, token-gated
  `GET /site-sections/{digest}.mjs?t=` (the module) and `GET /site-sections/{digest}.css?t=` (its
  stored CSS, possibly empty), which answer `x-clue-workspace-id: <the token's workspace>`; the
  editor server refuses a module whose workspace is not the one its `Host` label names (R2).

### Contract 5: the cited-claims read (Lane B)

`read_cited_claims@1`, input `{entity_id, claim_ids: [≤ 200]}`, output `{claims:
[AccountClaimView], dispositions: {claim_id: "served" | "held:<reason>" | "not_found"}}`, built
from `inspectable_claims_by_ids` then `gate_claims`. Granted to `AgentRole.DESIGN` through a
`design@v5` profile (Lane B Task 14), which also pins `design_record_site_section@1` and nothing
else new.

### Contract 6: the editor protocol (Lane C; shared Zod in site-kit `src/editor-protocol.ts`)

- Every message: `{channel: "clue-site-editor", v: 1, documentId, nonce, type, payload}`. The app
  checks `event.origin` against the workspace's exact editor origin, `event.source`, the nonce and
  the document id; the frame checks `event.source === window.parent` and the app origin. No
  `"*"` target origins.
- App → frame: `init {site, brand, sections: [{name, digest, token, propsSchema}], mode, route,
  device}`, `replace_site {site, version}`, `set_mode {mode}`, `navigate {route}`, `set_props
  {route, componentId, props}`, `select {route, componentId | null}`, `insert_asset {route,
  componentId, prop, url}`.
- Frame → app: `ready`, `changed {site}` (debounced), `selected {route, componentId, componentType,
  fields: FieldDescription[], props}`, `deselected`, `navigated {route}`, `request_asset {route,
  componentId, prop}`, `annotate {route, componentId, geometry}`, `error {code, message}`.
- `FieldDescription = {name, label, kind: "text" | "textarea" | "select" | "image" | "link" |
  "number" | "boolean" | "list", options?, item?: FieldDescription[]}`.
- **Refinements (Lane C plan, 2026-10-11, K6; additive, not product-facing):**
  - frame → app `shortcut {action: "undo" | "redo"}`: ⌘Z/⇧⌘Z pressed while focus is in the frame (Puck's in-frame history is not the source of undo; the server stack is);
  - `route` in `selected`, `annotate`, `request_asset`, `set_props`, `select` and `insert_asset` is a page route or the literal `"shell"` (the header/footer), which is what makes the C7 object id `site:shell#header`;
  - the frame posts `navigated {route}` once after it has applied an `init`; the app treats it as "the frame now shows this document";
  - component ids match `^[A-Za-z0-9_-]{1,200}$` at the protocol seam (plan K5).
  The schemas live in `apps/frontend/packages/site-kit/src/editor-protocol.ts`.

### Contract 7: the site turn (Lane B)

- Envelope `kind = "site_turn"`; the executor returns `{status, summary, current_version,
  model_calls, doc_kind: "site", clarification?, error?, stop_reason?}`.
- It persists through `design_write_site` under CAS (one turn, one undo step).
- It emits `site_document_saved {document_id, version}` (never an `operations` key), which the
  event forwarder turns into the `design.checkpoint` frame, so the frontend's existing
  `designRefreshForEvent` reloads the canvas.
- `design_leg_wiring` treats `doc_kind == "site"` like web in its labels and summaries — **Lane A
  Task 9** makes those changes (R8); Lane B Task 13 does the envelope, the refusal removal and the
  forwarder.
- The site request is `{prompt, base_version}`, plus `targets: [{object_id, note}]` in submission
  order when the person pointed at parts of the site (R9; object ids `site:<route>#<id>[.<field>]`
  or `site:shell#header|footer`). The executor appends one short block naming them after the
  person's words (Lane B Task 13a; its wording is founder-approved text T15).

### Contract 8: kinds on the wire

`"site"` is a new value everywhere a kind travels: backend `Literal`s (`chat/schemas.py:698`,
`frontend_read/contract_v1.py:481`) and frontend Zod enums (`design-editor/model/artifact.ts:17,31`,
`artifacts/model/artifact-library.ts:14`). **Lane C's acceptance of `"site"` lands before Lane A's
mapper starts sending it**; until both land, no workspace is in the flag.

### Contract 9: domains

- **Editor:** `https://<label>.<CLUE_SITE_EDITOR_SUFFIX>`, where `<label>` is an opaque token
  derived from the workspace id (never the renameable handle); dev
  `http://<label>.editor.localhost:<DEV_STACK_EDITOR_PORT>`. Both settings go into `.env` and
  `.env.example` the moment they are introduced.
- **Published pages:** `CLUE_PAGES_SYSTEM_SUFFIX` set to the new domain; a migration script
  rewrites every system hostname (label kept); the edge Worker answers an old
  `*.pages.cluehq.ai` host with a 301 to the new one; `validate_custom_hostname` reserves both
  registrable domains.

---

## Waves and lanes

```
Wave 1 (week 1)        T1 site-kit package ─┬─> Lane A (backend + renderer)
                       T2 site kind (DB)    ─┤   Lane B (agent on the fleet)
                       T3 site birth + flag ─┤   Lane C (editor)
                       T4 D2 spike (option A, done; D2 decided) ──> B6, C9, C11, A7
                       T5 R1 + R3 experiments ──> B2, B3
Waves 2–3 (weeks 2–5)  Lanes A, B, C in parallel (outlines below; each expanded into its own plan;
                       Lane C may run into week 6 with the editor domain)
Wave 4 (week 6)        Hardening and rollout
```

---

## Wave 1, detailed

### Task 1: `@clue/site-kit`, the shared package (pure, no file reads)

The spike's portable code is 2,178 lines across `trials/puck-spike/{puck,lib,scripts}`. It moves
into an npm workspace package inside `apps/frontend`, because `next.config.ts` keeps Turbopack's
root at `apps/frontend` and the workspace is `"workspaces": ["packages/*"]`. Two spike modules
read files and become pure:
- `lib/brands.ts` (`loadBrand` reads `data/brands/<slug>`);
- `scripts/validate-page.ts` (`loadBrand` plus the static `AGENT_SECTIONS` index).

`config.tsx` gets agent sections as an option instead of importing the static index. **The spike
stays as it is, as the frozen reference** (copy, don't move).

**Files:**
- Create: `apps/frontend/packages/site-kit/{package.json,tsconfig.json,README.md}`
- Create: `apps/frontend/packages/site-kit/src/{brand.ts,clone.ts,theme.ts,schemas.ts,sections.tsx,shell.tsx,agent-kit.tsx,config.tsx,validate.ts,catalog.ts,check-section.ts,index.ts}`
- Create: `apps/frontend/packages/site-kit/src/editor/{clone-editor.tsx,asset-picker.tsx}`
- Create: `apps/frontend/packages/site-kit/test/{contracts,catalog,multipage,check-section}.test.ts`
  plus fixtures in `test/fixtures/`
- Modify: `apps/frontend/package.json` (add `"@clue/site-kit": "*"`)

**Interfaces (produced, used by Lanes A, B and C):**

```ts
// brand.ts
export type BrandData = { slug: string; measured: …; kit: Record<string, unknown>; fonts: FontFace[];
  assets: Record<string, BrandAsset>; clones: Record<string, Clone> };   // unchanged shape
export function brandData(input: { slug: string; kit: Record<string, unknown>; fonts: FontFace[];
  kitAssets: Record<string, BrandAsset>; clones: Clone[]; measured: BrandData["measured"] }): BrandData;
// config.tsx
export type ConfigOptions = { basePath?: string; shell?: ShellData; editor?: EditorParts;
  agentSections?: Record<string, AgentSectionModule> };                  // replaces `site` lookup
export function makeConfig(brand: BrandData, options: ConfigOptions): Config;
// validate.ts
export type SiteFiles = { pages: Record<string, unknown>; shell: unknown | null };   // route -> page JSON
export function validateSite(files: SiteFiles, brand: BrandData,
  agentSections: Record<string, AgentSectionModule>): { valid: boolean; errors: string[] };
// catalog.ts
export function buildCatalog(brand: BrandData, seller: string): Record<string, string>;  // path -> markdown
// check-section.ts
export function lint(source: string): string[];
export function typeCheck(file: string): string[];
```

- [ ] **Step 1: Create the package skeleton.**

```bash
mkdir -p apps/frontend/packages/site-kit/{src/editor,test/fixtures,bin}
```

`apps/frontend/packages/site-kit/package.json`:
```json
{
  "name": "@clue/site-kit",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./src/index.ts",
    "./editor": "./src/editor/index.ts",
    "./validate": "./src/validate.ts",
    "./catalog": "./src/catalog.ts",
    "./check-section": "./src/check-section.ts"
  },
  "scripts": { "test": "tsx --test test/*.test.ts", "typecheck": "tsc --noEmit" },
  "dependencies": { "@puckeditor/core": "0.23.0", "node-html-parser": "^7.1.0", "zod": "^4.4.3" },
  "peerDependencies": { "react": "19.2.4", "react-dom": "19.2.4" },
  "devDependencies": { "tsx": "^4.23.15", "typescript": "^5", "esbuild": "^0.28.2" }
}
```

`apps/frontend/packages/site-kit/tsconfig.json`:
```json
{
  "compilerOptions": { "target": "ES2022", "module": "ESNext", "moduleResolution": "Bundler", "jsx": "react-jsx",
    "strict": true, "noEmit": true, "skipLibCheck": true, "types": ["node"] },
  "include": ["src", "test", "bin"]
}
```

- [ ] **Step 2: Copy the spike's modules and rewrite the `@/` imports to relative ones.** The spike
uses five aliases: `@/lib/brands` ×4, `@/lib/clone` ×2, `@/lib/theme` ×1, `@/puck/agent-kit` ×7,
`@/puck/shell` ×1.

```bash
S=trials/puck-spike; K=apps/frontend/packages/site-kit/src
cp $S/lib/clone.ts $S/lib/theme.ts $K/
cp $S/puck/schemas.ts $S/puck/sections.tsx $S/puck/shell.tsx $S/puck/agent-kit.tsx $S/puck/config.tsx $K/
cp $S/puck/clone-editor.tsx $S/puck/asset-picker.tsx $K/editor/
cp $S/scripts/check-section.ts $K/check-section.ts
sed -i '' -e 's#"@/lib/brands"#"./brand"#; s#"@/lib/clone"#"./clone"#; s#"@/lib/theme"#"./theme"#; s#"@/puck/agent-kit"#"./agent-kit"#; s#"@/puck/shell"#"./shell"#' $K/*.ts $K/*.tsx
sed -i '' -e 's#"@/lib/clone"#"../clone"#' $K/editor/*.tsx
grep -rn '"@/' $K && echo "UNREWRITTEN ALIAS" || echo "aliases rewritten"
```
Expected: `aliases rewritten`.

- [ ] **Step 3: Write `src/brand.ts`.** The types and `cloneImages` come verbatim from
`trials/puck-spike/lib/brands.ts:7-53`; `loadBrand`'s file reads become `brandData`'s arguments.

```ts
// The brand data the sections, the theme, the validator and the catalog need, built from the
// stored kit and clones by the caller (the design API, the agent harness or the editor).
import type { Clone } from "./clone";

export type FontFace = { family: string; weight: number | null; style: string; file: string };
export type BrandAsset = { kind: string; label: string | null; description: string | null; mime: string | null; file: string; logo: unknown };
export type MeasuredButton = { background: string; color: string; borderRadius: string; paddingY: string; paddingX: string;
  height: string; fontFamily: string; fontSize: string; fontWeight: string; letterSpacing: string };
export type BrandData = {
  slug: string;
  measured: { primary_button: MeasuredButton | null; heading_on_light?: { color: string } | null } | null;
  kit: Record<string, unknown>;
  fonts: FontFace[];
  assets: Record<string, BrandAsset>;
  clones: Record<string, Clone>;
};

/** Photos and graphics captured with the seller's own sections, offered beside the kit's assets. */
function cloneImages(clones: Clone[]): Record<string, BrandAsset> {
  const found: Record<string, BrandAsset> = {};
  for (const clone of clones) {
    for (const match of clone.html.matchAll(/<img[^>]*?src="([^"]+\.(?:png|jpe?g|webp|avif))"[^>]*?(?:alt="([^"]*)")?/g)) {
      const file = match[1];
      if (!file.startsWith("/brands/") || found[file]) continue;
      found[file] = { kind: "captured_image", label: clone.label,
        description: match[2] || `From the seller's section "${clone.label}"`, mime: null, file, logo: null };
    }
  }
  return found;
}

export function brandData(input: {
  slug: string; kit: Record<string, unknown>; fonts: FontFace[]; kitAssets: Record<string, BrandAsset>;
  clones: Clone[]; measured: BrandData["measured"];
}): BrandData {
  return {
    slug: input.slug, kit: input.kit, measured: input.measured, fonts: input.fonts,
    assets: { ...input.kitAssets, ...cloneImages(input.clones) },
    clones: Object.fromEntries(input.clones.map((clone) => [clone.id, clone])),
  };
}
```

**Note on asset paths:** the spike's `/brands/<slug>/assets/<sha>` prefix is a spike convention.
Lane A replaces it with the design API's `/asset-store/<digest>`. Keep the prefix test for now; A5
changes it with a test.

- [ ] **Step 4: Make agent sections an option in `src/config.tsx`.** In the copy, replace the
static lookup `AGENT_SECTIONS[options.site ?? ""] ?? {}` (spike `puck/config.tsx:114-116`) with
`options.agentSections ?? {}`. Then delete the `site` key from `ConfigOptions` and the import of
`./agent-sections`.

```ts
// before (spike)
const agentSections = Object.fromEntries(
  Object.entries(AGENT_SECTIONS[options.site ?? ""] ?? {}).map(([name, module]) => [ … ]),
);
// after (site-kit)
const agentSections = Object.fromEntries(
  Object.entries(options.agentSections ?? {}).map(([name, module]) => [ … ]),
);
```
Run `grep -n "agent-sections\|options.site" apps/frontend/packages/site-kit/src/config.tsx`.
Expected: no output.

- [ ] **Step 5: Port the validator as a pure function in `src/validate.ts`.** Take the body of
`validate()` from `trials/puck-spike/scripts/validate-page.ts` unchanged, except for its three
input reads:
- `run`/`loadBrand` becomes the `brand` parameter;
- `AGENT_SECTIONS[run.site]` becomes the `agentSections` parameter;
- the `fs` reads of `page.json`, `shell.json` and `pages/*.json` become `files.pages` (route →
  page) and `files.shell`.

Missing files map to the same messages: `files.pages["/"] === undefined` gives "page.json: does
not exist yet…", and `files.shell === null` gives "shell.json: …". Error locations keep the
spike's names (`page.content.3(proof)…`, `pages/analysis.content.0(hero)…`) so the agent's skills
still match.

```ts
export function validateSite(files: SiteFiles, brand: BrandData,
  agentSections: Record<string, AgentSectionModule>): { valid: boolean; errors: string[] } {
  // body of the spike's validate(), with the three reads replaced as described
}
```

Add `bin/validate-site.ts`. It reads `{files, brand, agentSections: {name: {schema: <json schema>}}}`
from stdin and prints `{"valid", "errors"}`; this is the CLI Lane B's harness calls.

- [ ] **Step 6: Port the catalog builder as a pure function in `src/catalog.ts`.** Take the body
of `trials/puck-spike/scripts/build-catalog.ts`, with `loadBrand` replaced by the `brand`
parameter and file writes replaced by a returned `{relativePath: markdown}` map. That covers
`catalog/index.md`, `catalog/clones/<id>.md`, `catalog/sections.md` and `brand/brand.md`.

- [ ] **Step 7: Port the tests with fixtures.**
- Copy `trials/puck-spike/data/sites/garner-syracuse.json` and `data/brands/garner/*.json` into
  `test/fixtures/`.
- Add a helper `test/fixtures/garner.ts` that returns `brandData({…})` from them.
- Port `scripts/{contracts,catalog,multipage}.test.ts` and the `lint`/`typeCheck` cases of
  `agent-sections.test.ts`, replacing `validate(workspaceDir)` calls with `validateSite(files,
  garner, {})`.
- The skill example the agent-sections test reads stays in the spike, so copy that example into
  `test/fixtures/section-example.tsx`.
- `tailwind-scan.test.ts` belongs to the spike app and does not move; Lane C adds the equivalent
  for the frontend's `globals.css`.

```bash
cd apps/frontend && npm install && npm test -w @clue/site-kit 2>&1 | tail -6
```
Expected: every ported test passes (the spike's counts: contracts, catalog, multipage and the
check-section lint cases). If a test fails, the port changed behaviour; fix the port, not the test.

- [ ] **Step 8: Type-check the frontend app with the package in it.**

```bash
cd apps/frontend && npm run typecheck -w @clue/site-kit && npx tsc --noEmit -p tsconfig.json | tail -3
```
Expected: no errors.

- [ ] **Step 9: Commit.**

```bash
git add apps/frontend/packages/site-kit apps/frontend/package.json apps/frontend/package-lock.json
git commit -m "site-kit: the Puck spike's components, schemas, theme, clone renderer, validator and catalog as a pure workspace package"
```

### Task 2: the `site` document kind and `site_turn` run kind (database and DAL)

**Files:**
- Modify: `subsystems/design/clue_design/enums.py:19-23` (`DesignDocKind`) and `:88-97`
  (`DesignRunKind`)
- Create: `alembic/versions/<generated>_design_site_document_kind.py`
- Modify: `subsystems/design/clue_design/documents.py:201` (birth branch) and `:382` (rename path)
- Modify: `subsystems/design/clue_design/envelopes.py:72` (`kind: Literal[...]`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/dto.py:14` (summary for site)
- Test: `tests/design/test_documents_dal_db.py` (new site cases); the existing
  `tests/design/test_design_schema_db.py:83` parity test

**Interfaces (produced):**
- `DesignDocKind.SITE = "site"`;
- `DesignRunKind.SITE_TURN = "site_turn"`;
- `create_document(…, doc_kind="site")` stores `{id, title, theme:{brand_kit?}, pages, shell, agent_sections}` and returns the stored row;
- `dto.site_document_summary(document)`.

**The stored site document shape** (satisfies S2's top-level contract):
```json
{ "id": "doc_…", "title": "…", "theme": { "brand_kit": { "id": "…", "version": 2 } },
  "pages": { "/": { "root": { "props": { "title": "…" } }, "content": [] } },
  "shell": null, "agent_sections": {} }
```

- [ ] **Step 1: Write the failing DAL test** in `tests/design/test_documents_dal_db.py`, beside
`_web_doc` (`:37`).

```python
def _site_doc(doc_id: str, title: str = "S") -> dict[str, object]:
    return {"id": doc_id, "title": title, "theme": {}, "pages": {"/": {"root": {"props": {"title": title}}, "content": []}},
            "shell": None, "agent_sections": {}}


def test_site_documents_are_born_like_web_documents(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _seed_brand_kit(conn, workspace_id=ws, version=1, approval_status="approved")
            doc_id = f"site_{uuid4().hex}"
            born = await design_documents.create_document(conn, workspace_id=ws, scene=_site_doc(doc_id), doc_kind="site")
            assert born["doc_kind"] == "site"
            assert born["title"] == "S"
            assert born["scene"]["theme"]["brand_kit"] == {"id": "kit_workspace_brand", "version": 1}
            renamed = await design_documents.rename_document(conn, workspace_id=ws, document_id=doc_id, title="Renamed")
            assert renamed["scene"]["title"] == "Renamed"          # top-level title, not meta.title
            updated = await design_documents.update_web_document(
                conn, workspace_id=ws, document_id=doc_id, web_doc={**renamed["scene"], "shell": {"header": {}}},
                intent="site_write", checkpoint_label=None, operations=[{"op": "replace_site"}],
                inverse_operations=[{"op": "replace_site", "site": renamed["scene"]}],
                expected_base_version=renamed["current_version"])
            assert updated["current_version"] == renamed["current_version"] + 1
            await txn.rollback()
    run_async(_check())
```
Check the exact `rename_document` signature against `documents.py:361` before running.

- [ ] **Step 2: Run it and watch it fail.**

```bash
set -a; source .env; set +a; .venv/bin/python -m pytest tests/design/test_documents_dal_db.py -k site -q 2>&1 | tail -5
```
Expected: FAIL. The insert is refused by the enum (`invalid input value for enum design_doc_kind: "site"`).

- [ ] **Step 3: Widen the Python enums** (`clue_design/enums.py`): add `SITE = "site"` after `WEB`
in `DesignDocKind`, and `SITE_TURN = "site_turn"` after `WEB_TURN` in `DesignRunKind`.

- [ ] **Step 4: Generate the migration and write its body.**

```bash
set -a; source .env; set +a; .venv/bin/alembic revision -m "design site document kind and site_turn run kind"
```

```python
"""design site document kind (Puck) and site_turn run kind.

Rebuilds both enums (PostgreSQL cannot drop a label, so a rebuild keeps the change reversible),
the pattern of 50b84c524fa2 `_rebuild_run_status`. Each enum has exactly one column.
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "<generated>"
down_revision: str | None = "10edab6dd974"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (parity-tested in tests/design/test_design_schema_db.py).
_DOC_KIND_AFTER = ("scene", "web", "site")
_DOC_KIND_BEFORE = ("scene", "web")
_RUN_KIND_AFTER = ("agent_turn", "web_turn", "site_turn")
_RUN_KIND_BEFORE = ("agent_turn", "web_turn")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _rebuild(type_name: str, table: str, column: str, values: tuple[str, ...], default: str | None = None) -> None:
    op.execute(f"ALTER TYPE {type_name} RENAME TO {type_name}_prev")
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({_values(values)})")
    if default is not None:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
    op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_name} USING {column}::text::{type_name}")
    if default is not None:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'")
    op.execute(f"DROP TYPE {type_name}_prev")


def upgrade() -> None:
    _rebuild("design_doc_kind", "design_document", "doc_kind", _DOC_KIND_AFTER, default="scene")
    _rebuild("design_run_kind", "design_agent_run", "kind", _RUN_KIND_AFTER)


def downgrade() -> None:
    bind = op.get_bind()
    sites = bind.execute(text("SELECT count(*) FROM design_document WHERE doc_kind = 'site'")).scalar()
    turns = bind.execute(text("SELECT count(*) FROM design_agent_run WHERE kind = 'site_turn'")).scalar()
    if sites or turns:
        raise RuntimeError(f"cannot downgrade: {sites} site documents and {turns} site_turn runs exist")
    _rebuild("design_run_kind", "design_agent_run", "kind", _RUN_KIND_BEFORE)
    _rebuild("design_doc_kind", "design_document", "doc_kind", _DOC_KIND_BEFORE, default="scene")
```

- [ ] **Step 5: Branch the DAL.** In `documents.py:201`, `if doc_kind == "web":` becomes
`if doc_kind in ("web", "site"):` (the same top-level id, title and `theme.brand_kit`). At `:382`,
`path = ["title"] if document["doc_kind"] == "web" else ["meta", "title"]` becomes
`path = ["title"] if document["doc_kind"] in ("web", "site") else ["meta", "title"]`.

- [ ] **Step 6: Widen the envelope literal.** At `envelopes.py:72`,
`kind: Literal["agent_turn", "web_turn"]` becomes `kind: Literal["agent_turn", "web_turn", "site_turn"]`.

- [ ] **Step 7: Add the site summary.** At `dto.py:14`, add a site branch before the web one;
`web_document_summary` calls `web_doc_counts` (WebDoc-specific), so a site gets its own:

```python
    if document.get("doc_kind") == "site":
        return site_document_summary(document)
```
```python
def site_document_summary(document: JsonObject) -> JsonObject:
    site = document["scene"]
    theme = site.get("theme") or {}
    pages = site.get("pages") or {}
    return {
        "id": document["id"], "title": document["title"], "status": document["status"], "doc_kind": "site",
        "current_version": document["current_version"], "artifact_type": "website", "medium": "web",
        "brand_kit": theme.get("brand_kit"),
        "effective_brand_kit": {"source": document.get("effective_brand_kit_source"), "id": document.get("effective_brand_kit_id"),
                                "version": document.get("effective_brand_kit_version"), "mode": document.get("effective_brand_mode")},
        "counts": {"pages": len(pages), "sections": sum(len((p or {}).get("content") or []) for p in pages.values())},
        "created_at": document["created_at"], "updated_at": document["updated_at"],
    }
```

- [ ] **Step 8: Run the migration round trip and the tests.**

```bash
set -a; source .env; set +a; .venv/bin/alembic heads        # exactly one head: the new revision
make db-smoke                                                # up -> down -> up on a throwaway DB
.venv/bin/python -m pytest tests/design/test_documents_dal_db.py tests/design/test_design_schema_db.py -q 2>&1 | tail -3
```
Expected: one head; db-smoke passes; the site test and the enum parity test pass.

- [ ] **Step 9: Commit.**

```bash
git add subsystems/design/clue_design/{enums,documents,envelopes}.py subsystems/clue-design/apps/api/lumen_api/dto.py alembic/versions/*design_site_document_kind*.py tests/design/test_documents_dal_db.py
git commit -m "design: the site document kind and site_turn run kind (enum rebuild migration, DAL branch, summary)"
```

### Task 3: site birth behind a per-workspace flag, fail-closed until the site executor exists

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (beside `design_runtime_enabled`, `:633`)
- Modify: `.env.example` (beside `CLUE_DESIGN_RUNTIME_ENABLED=1`, `:587`)
- Create: `platform/api/clue_api/site_documents.py` (`mint_empty_site_document`)
- Modify: `platform/api/clue_api/design_leg_tools.py` (`OpenDesignLegTool.__init__` `:660`, web
  birth `:990-1002`, `build_design_leg_tools` `:1840`)
- Modify: `platform/api/clue_api/toolbelt_wiring.py:3183` (pass the flag)
- Modify: `platform/api/clue_api/design_leg_wiring.py:2568` (site refuses until B5)
- Test: `tests/api/test_site_leg_birth_db.py` (new)

**Interfaces (produced):**
- `Settings.design_site_engine_workspaces: str = ""` (env `CLUE_DESIGN_SITE_ENGINE_WORKSPACES`,
  comma-separated workspace ids; empty means off);
- `mint_empty_site_document(*, document_id, title, brand_kit_ref) -> dict`;
- `build_design_leg_tools(…, site_engine_workspaces: frozenset[str] = frozenset())`;
- typed refusal `SiteRuntimeNotComposedError` raised by `_envelope` for `doc_kind == "site"` until
  B5 replaces it.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_site_leg_birth_db.py`. They reuse the
fixtures of `tests/api/test_genad_leg_document_birth_db.py`:
- `_seed_conversation`, `_open` and `_RecordingSceneMinter` (`:280-345`);
- `engine_web_doc` from `tests/api/test_genweb_leg_document_birth_db.py`;
- `migrated_db` and `rollback_conn` from `tests/profiling/conftest.py`.

The flag-off case mirrors that file's `test_web_birth_is_byte_unchanged` (`:650`).

```python
"""Site birth behind CLUE_DESIGN_SITE_ENGINE_WORKSPACES (plan 2026-10-09, Task 3)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clue_api.design_leg_tools import OpenDesignLegTool
from clue_design.documents import get_document
from clue_toolbelt import ToolRegistry
from tests.api.test_genad_leg_document_birth_db import _open, _RecordingSceneMinter, _seed_conversation
from tests.api.test_genweb_leg_document_birth_db import engine_web_doc
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401


def _refusing_web_minter(**_: Any) -> dict[str, Any]:
    raise AssertionError("a listed workspace must never mint a WebDoc")


def _registry(seeds: dict[str, Any], *, listed: bool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        OpenDesignLegTool(
            conn_factory=seeds["conn_factory"],
            storage=seeds["storage"],
            scene_document_minter=_RecordingSceneMinter(),
            web_document_minter=_refusing_web_minter if listed else engine_web_doc,
            site_engine_workspaces=frozenset({seeds["workspace_id"]}) if listed else frozenset(),
        ),
        make_default=True,
    )
    return registry


def test_a_listed_workspace_births_a_site_document(tmp_path: Path, migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="site")
            result = await _open(seeds, _registry(seeds, listed=True), doc_kind="web")
            document = await get_document(conn, workspace_id=seeds["workspace_id"],
                                          document_id=str(result.references["document_id"]))
            assert document["doc_kind"] == "site"
            assert document["scene"]["pages"]["/"]["content"] == []
            assert document["current_version"] == 0

    run_async(scenario())


def test_an_unlisted_workspace_births_a_webdoc_unchanged(tmp_path: Path, migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="web-unlisted")
            result = await _open(seeds, _registry(seeds, listed=False), doc_kind="web")
            document = await get_document(conn, workspace_id=seeds["workspace_id"],
                                          document_id=str(result.references["document_id"]))
            assert document["doc_kind"] == "web"
            assert document["scene"]["pages"][0]["id"] == "home"

    run_async(scenario())
```

**The third case (Review focus 3)** goes in the leg runner's tests. Find the test that drives
`DesignLegTurnRunner._envelope` or `run_leg_turn` with a pinned web document (`grep -rln "run_leg_turn\|_envelope" tests/api`). Copy it with a pinned `doc_kind="site"` document, and assert that
`SiteRuntimeNotComposedError` is raised or surfaced and no `design_agent_run` row is written.

- [ ] **Step 2: Run them and watch them fail.**

```bash
.venv/bin/python -m pytest tests/api/test_site_leg_birth_db.py -q 2>&1 | tail -5
```
Expected: FAIL (`mint_empty_site_document` and the flag don't exist yet).

- [ ] **Step 3: Add the setting and the env line.** In `settings.py`, after
`design_runtime_enabled`:

```python
    # Website agent on Puck (2026-10-09 plan): workspaces whose NEW websites are born as Puck
    # `site` documents instead of WebDocs. Comma-separated workspace ids; empty = off everywhere,
    # so every existing path is byte-identical. Head of ABM is unchanged: `open_design_leg`
    # with doc_kind="web" births a site for listed workspaces. Env: CLUE_DESIGN_SITE_ENGINE_WORKSPACES.
    design_site_engine_workspaces: str = ""
```
In `.env.example`, under the design block:
```
# Website agent on Puck: workspaces whose new websites are Puck site documents (comma-separated; empty = off)
CLUE_DESIGN_SITE_ENGINE_WORKSPACES=
```
Mirror the same line into `.env`, at its default, per the parity rule.

- [ ] **Step 4: Write the site minter** (`platform/api/clue_api/site_documents.py`):

```python
"""The empty Puck site document a website leg births when its workspace is on the site engine.

Pure (no engine round-trip): the stored shape is the site-kit's own JSON, top-level id/title/
theme so the design DAL's creation contract (`clue_design.documents.create_document`) treats it
like a web document and stamps the approved brand kit at birth.
"""
from __future__ import annotations

from typing import Any


def mint_empty_site_document(*, document_id: str, title: str, brand_kit_ref: dict[str, Any] | None) -> dict[str, Any]:
    theme: dict[str, Any] = {} if brand_kit_ref is None else {"brand_kit": brand_kit_ref}
    return {
        "id": document_id,
        "title": title,
        "theme": theme,
        "pages": {"/": {"root": {"props": {"title": title}}, "content": []}},
        "shell": None,
        "agent_sections": {},
    }
```

- [ ] **Step 5: Birth a site when the workspace is listed.** In `OpenDesignLegTool`:
- the constructor takes `site_engine_workspaces: frozenset[str] = frozenset()` and
  `site_document_minter = mint_empty_site_document`;
- at the web birth (`:990-1002`), when `workspace_id in self._site_engine_workspaces`, call the
  site minter (no thread hop, since it's pure) and `create_document(…, doc_kind="site", …)`.
  Otherwise keep the existing code byte-for-byte.

`build_design_leg_tools` gains the parameter and passes it through. In `toolbelt_wiring.py:3183`:

```python
    for tool in build_design_leg_tools(
        conn_factory=conn_factory,
        storage=storage,
        enabled=resolved_settings.design_runtime_enabled,
        site_engine_workspaces=frozenset(
            w.strip() for w in resolved_settings.design_site_engine_workspaces.split(",") if w.strip()
        ),
    ):
```

- [ ] **Step 6: Fail closed for site turns until B5.** At `design_leg_wiring.py:2568`, before the
`web_turn`/`agent_turn` choice:

```python
        if document.get("doc_kind") == "site":
            # The Puck site runtime lands in Lane B (B5, `execute_site_turn_job`). Until then a
            # site document must never fall into the scene runtime (the `else "agent_turn"` arm).
            raise SiteRuntimeNotComposedError(str(document_id))
```
Define `SiteRuntimeNotComposedError` beside the module's other typed errors. Make the leg runner
surface it the way it surfaces other refusals: find the existing typed refusal handling around
`_dispatch_batch` (`:2215`) and add this error to it, so the user sees an honest message.

- [ ] **Step 7: Run the tests, plus the existing leg tests.**

```bash
.venv/bin/python -m pytest tests/api/test_site_leg_birth_db.py -q 2>&1 | tail -3
.venv/bin/python -m pytest tests/api -k "design_leg" --ignore-glob='*_live.py' -q 2>&1 | tail -3
```
Expected: the new tests pass; the existing design-leg tests still pass unchanged (flag off).

- [ ] **Step 8: Commit.**

```bash
git add libs/clue-config/clue_config/settings.py .env.example platform/api/clue_api/{site_documents,design_leg_tools,design_leg_wiring,toolbelt_wiring}.py tests/api/test_site_leg_birth_db.py
git commit -m "design legs: birth Puck site documents for listed workspaces (CLUE_DESIGN_SITE_ENGINE_WORKSPACES); site turns refuse until the site runtime lands"
```

### Task 4: D2 spike, loading agent-written sections at runtime (option A, no iframes)

**Done** (`412193a51`). Results are in `trials/puck-spike/RUNTIME-SECTIONS.md`; they led to the
D2 decision above.

A throwaway experiment in the spike app; the answer is a results note, not production code. It
uses the five cl3 components (`trials/puck-spike/puck/agent-sections/agent-cl3/*.tsx`) and E5's
`AnalysisSteps` as fixtures.

**The questions:**
1. Can a compiled module be loaded at runtime into Puck's config, in the editor and in the server
   render?
2. Do in-place editing and fields work on it?
3. How long from write to visible?
4. Does the strict check refuse six hostile sections?
5. Does a page with agent sections render to static HTML in a no-network process?
6. Can workspace A ever load workspace B's module?

**Files (all under `trials/puck-spike/`):**
- Create: `scripts/compile-section.ts`
- Create: `app/compiled/[workspace]/[digest]/route.ts`
- Create: `app/edit-runtime/[site]/page.tsx` and `client.tsx`
- Create: `scripts/render-site.ts`
- Create: `scripts/hostile/*.tsx` (six fixtures)
- Create: `RUNTIME-SECTIONS.md` (the results)

- [ ] **Step 1: Compile and store.** `scripts/compile-section.ts <workspace> <file.tsx>`:
- runs the existing `lint` and `typeCheck` (from `scripts/check-section.ts`);
- bundles with esbuild: `format: "esm"`, `jsx: "automatic"`, with `react`, `react/jsx-runtime`
  and `zod` external;
- writes `data/compiled/<workspace>/<sha256>.mjs`;
- prints `{name, digest, propsSchema}`.

- [ ] **Step 2: Serve per workspace.** The route `app/compiled/[workspace]/[digest]/route.ts`
returns the module only when `<digest>` exists under `<workspace>`, and 404 otherwise. That's the
tenant-isolation check (question 6). Send `Content-Type: text/javascript`.

- [ ] **Step 3: Load in the editor.** `client.tsx`:
- `await import(/* webpackIgnore: true */ \`/compiled/${ws}/${digest}.mjs\`)` for each section of
  the site;
- adds `{name: {render: (props) => module.render(props, kit), fields: fieldsFrom(propsSchema)}}`
  to the config built by `makeConfig`;
- renders `<Puck>`.

Record two things: whether React is shared between host and module (an import map, or `react`
exposed as a global), and whether `contentEditable` fields work on a loaded section.

- [ ] **Step 4: Render on the server.** `scripts/render-site.ts`:
- loads the page JSON and the modules from disk;
- `renderToString(<Render config data />)` using `@puckeditor/core/rsc` as in
  `app/s/[site]/[[...route]]/page.tsx`;
- writes HTML;
- runs with `docker run --rm --network none -v $PWD:/w:ro node:24-alpine node /w/…`.

Record whether it worked, its time, and whether the HTML matches `/s/<site>` (screenshot diff via
the existing `_difference` in `agent/trials_puck_agent/tools.py`).

- [ ] **Step 5: The strict check against hostile sections.** Add to `lint` a list of banned
identifiers:
- `window`, `document`, `globalThis`;
- `fetch`, `XMLHttpRequest`, `WebSocket`, `eval`, `Function`, `import(`;
- `dangerouslySetInnerHTML`;
- `localStorage`, `cookie`, `setTimeout`, `setInterval`;
- any `on[A-Z]` event prop.

Then write six fixtures (network call, cookie read, parent frame, infinite loop, huge output,
injected script). Expected: each refused by `lint`, with its reason. Also confirm the five cl3
components and `AnalysisSteps` still pass (a false positive is a finding).

- [ ] **Step 6: Write the results.** `RUNTIME-SECTIONS.md` gets one table: each question, its
answer, its numbers, and anything that failed. End with a recommendation for B6 and C9.

- [ ] **Step 7: Commit** (local only):

```bash
git add trials/puck-spike/{scripts/compile-section.ts,scripts/render-site.ts,scripts/hostile,app/compiled,app/edit-runtime,RUNTIME-SECTIONS.md}
git commit -m "Puck spike: D2, agent sections compiled, served per workspace and loaded at runtime (results in RUNTIME-SECTIONS.md)"
```

### Task 5: agent experiments R1 (research input) and R3 (images) in the spike harness

**Live model runs: about $5 plus image costs; the founder's go is needed before Steps 4 and 7.**

**Files:**
- `trials/puck-spike/agent/trials_puck_agent/{workspace,tools,harness}.py`
- `trials/puck-spike/agent/tests/*`
- `trials/puck-spike/scripts/validate-page.ts` (accept generated images for their own site)
- New skill text `agent/skills/images-and-logos/SKILL.md`, **only after founder review**

**Changed 2026-10-09 (founder rulings D3 and the outreach-safe gate), replacing Steps 1–2:**
- the brief is direction; the page agent chooses its own facts (prompt wording approved);
- the research files keep every statement type and its notes, plus the Watch-outs and Context only
  sections marked as background, never on the page;
- each statement ends with short claim labels (`[c4, c9]`), and `research/claims.md` lists each
  claim (what it says, topic, notes, source link). It is read from the claims the research cites,
  through the source drawer's read (`inspectable_claims_by_ids`), and gated by `gate_claims`;
- platform: `gate_claims` (`arv2/read_tools.py`) serves account research findings and value
  narratives while `CLUE_VERIFICATION_ENABLED=false`. Reputation risks, biography, milestones,
  sensitive facts and media gaps stay held back, and statements citing them are left out of the
  research files;
- production needs a governed design read for the cited claims (B2).
- **Result (2026-10-10, runs r1a/r1b, spike ISSUES.md 54–58):** no untraced figure in either arm;
  the claims file is the standard (D3 decided); account-page-copy now keeps the research's notes on
  how to approach the account off the page.

- [ ] **Step 1: R1, keep claim ids in the research files.** In `workspace.research_markdown`
(`trials_puck_agent/workspace.py:42`), append each statement's `cited_claim_ids` as
` [claims: id1, id2]`. Test: a section with `cited_claim_ids` renders them; one without renders
none.

- [ ] **Step 2: R1, add a `read_claims` tool.** `PageTools.read_claims(entity_id, field_prefix=None)`
wraps `self.reads.read_claims(entity_id=…, field_prefix=…, limit=20)`
(`design_platform_reads.py:224`) and returns `claim_id`, `field_key`, `value`, `source_url` and
`evidence` per claim. Register it in `page_tool_set` with this description: "Look up the claims
behind a research statement (its [claims: …] ids) or about the account: each claim's value,
source and quote." Test with a fake `reads`.

- [ ] **Step 3: R1, run the comparison.** Syracuse (case A) and Dana.AI (case B), each built
twice, from git revisions with and without Steps 1–2. Compare:
- facts on the page that trace to a claim;
- quotes used verbatim;
- facts with no source;
- cost and calls.

The results go to `ISSUES.md` (R1).

- [ ] **Step 4: R3, add a `generate_image` tool.** `PageTools.generate_image(prompt, aspect_ratio)`
calls `lumen_api.image_provider.generate(prompt=…, aspect_ratio=…)` (`image_provider.py:249`),
saves `result.image_bytes` to `public/generated/<site>/<sha256>.<ext>`, and returns the path and
the real `width`/`height`. The validator accepts `/generated/<site>/` images for that site only
(contract: an image the site itself generated). Tests: a fake provider, and a cross-site path is
refused.

- [ ] **Step 5: R3, add a `search_assets` tool** over the brand's assets and their descriptions
(keyword ranking, the same order as the platform's `search_assets` in `web_substrate.py:4137`:
id, then phrase, then token count, then pixel area). CLIP comes in B4.

- [ ] **Step 6: R3, the images skill.** Draft `images-and-logos` (when to reuse a brand image,
when to generate, how to prompt in the brand's style, logos) and **show it to the founder before
writing it**.

- [ ] **Step 7: R3, run it.** Two Syracuse builds with the image tools. Report:
- how many images were generated or reused;
- whether they look on brand (side by side);
- the cost per image.

- [ ] **Step 8: Commit** (local only), each step's code with its tests, and the results in
`ISSUES.md`.

---

## Waves 2–3: the lanes (detailed plans written 2026-10-11)

Each lane has its own plan, written against the code at `d723a17ae` and the four code surveys of
2026-10-11. They implement the contracts above.

- **Lane A, backend, renderer and publishing** —
  `docs/superpowers/plans/2026-10-11-lane-a-site-backend-and-publishing.md`:
  A0 site-kit catch-up (spike R3 and D2 lint, catalog CLI, `/asset-store` assets, schema-based
  validation); A1 kind-branch audit; A2 write, undo, redo and versions; A3 composer targets;
  A4 gallery and library; A5 the hardened-browser renderer and the cleaner; A6 thumbnails;
  A7 publish with the per-publish CSP; A8 export; A9 brand fidelity in site-kit; A10 the
  published-pages domain move.
- **Lane B, the agent on the platform** —
  `docs/superpowers/plans/2026-10-11-lane-b-site-agent-on-platform.md`:
  B0 `read_cited_claims@1` and `design@v5`; B1 the site harness package; B2 the workspace view
  from the database; B3 tools; B4 hybrid image search wiring; B5 the site executor; B6 agent
  sections (compile, schema, store, links); B7 cost and tracing; B8 R2 on-demand rebuild.
- **Lane C, the editor** — `docs/superpowers/plans/2026-10-11-lane-c-site-editor.md`:
  C0 the Railway build fix; C1 the `site` kind in the frontend; C2 the site repository and save
  policy; C3 the editor app on the editor domain; C4 the app's frame host and protocol; C5 fields
  and Layers in the dock; C6 images; C7 annotations; C8 edit toggle, live reload, run lock, undo;
  C9 versions; C10 the Pages toggle and URL toolbar; C11 dev stack, deploy and the hostile
  probes; C12 R5 rich text; C13 insert, delete and duplicate (after the founder's designs).

Order between lanes: A0 first (B and C consume site-kit); C1 before A1's mapper (Contract 8);
A2 before B5's persist and C2; A5 before B3's `render_page` and A6–A8; B6's section links before
C3 loads agent sections.

## Wave 4: hardening and rollout (about 1 week)

- **End to end on Garner, Conduit and Alt Carbon:** chat → build → edit → publish to a domain.
- **The skills regression set:** cases A, B and C, the ten edits, E5, cl3.
- **Cost and Langfuse check per turn.**
- **Each regression page at least as good as its spike version,** and a founder look beside the
  platform pages already on record (this replaces R4, founder 2026-10-11).
- **Flag on for chosen workspaces.** The WebDoc path stays as it is.

## Self-review notes

- **Spec coverage:** the readiness map's §2 tool verdicts are covered by B3 and B4; §3 research
  by Task 5 and B2; §4 skills by B1 and Task 5's images skill; §5 editor by Lane C; §6 coupling
  points by Tasks 2–3 and A1–A8; §8 effort by the waves; §9 decisions D1 (site kind, Task 2), D2
  (Task 4, then the "D2" section, A5, A7, B6, C9 and C11), D3 (Task 5), D4 (C10), D5 (Node renderer, A5) and D6 (the flag, Task 3).
- **Open by design:** Lanes A, B and C are outlines, expanded into their own plans when the wave
  starts. The detail depends on Wave 1's results, which is why it is not written now.
